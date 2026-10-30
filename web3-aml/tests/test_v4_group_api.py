"""HTTP/context guards for read-only group expansion; no model/LLM loads."""
import copy
import threading
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

import api.main as main
from api.runtime_v3 import Conflict, Runtime
from api.store import SnapshotStore


class ReadOnlyGroups:
    def __init__(self, dataset):
        self.dataset = dataset
        self.versions = {'dataset_id': dataset, 'risk_revision': 'frozen',
                         'dense_group_revision': 'groups-1'}
        self.lock = threading.RLock()
        self.calls = []

    def related_groups(self, trace, path_id=None):
        self.calls.append(('groups', copy.deepcopy(trace), path_id))
        if path_id not in (None, 'path_allowed'):
            raise KeyError('路径不属于当前追踪结果。')
        return {'dataset_id': self.dataset, 'seed_address': 'seed', 'path_id': path_id,
                'status': 'available', 'enabled': True, 'revision': 'groups-1',
                'groups': [{'group_id': 'dense_allowed', 'member_count': 3}]}

    def group_detail(self, trace, group_id, offset=0, limit=500, path_id=None):
        self.related_groups(trace, path_id)
        self.calls.append(('detail', group_id, offset, limit))
        if group_id != 'dense_allowed':
            raise KeyError('群组不属于当前追踪范围。')
        nodes = [{'address_id': 'seed', 'risk_score': 12.3456789,
                  'risk_level': 'LOW', 'is_scored': True}]
        edges = [{'src': 'seed', 'dst': 'peer'}]
        return {'dataset_id': self.dataset, 'group_id': group_id,
                'revision': 'groups-1', 'status': 'available', 'summary': {},
                'nodes': nodes[offset:offset+limit], 'edges': edges[offset:offset+limit],
                'offset': offset, 'limit': limit, 'total_nodes': 1, 'total_edges': 1,
                'next_offset': None, 'has_more': False, 'complete': True}


@pytest.fixture
def context(tmp_path, monkeypatch):
    services = {d: ReadOnlyGroups(d) for d in ('bitcoin', 'ethereum')}
    runtime = Runtime.__new__(Runtime)
    runtime.registry = SimpleNamespace(get=lambda d: services[d])
    runtime.store = SnapshotStore(tmp_path/'runs')
    runtime.executor = SimpleNamespace(shutdown=lambda **_: None)
    traces = {}
    for dataset, service in services.items():
        key, record = runtime.store.write('trace', {'dataset_id': dataset,
            'address_id': 'seed', 'analysis_id': 'analysis_original',
            'versions': service.versions,
            'result': {'seed_address': 'seed', 'top_paths': [],
                       'search_budget': {'actual_edge_inspections': 8}}})
        traces[dataset] = {'trace_id': key, **record}
    monkeypatch.setattr(main, 'Runtime', lambda: runtime)
    with TestClient(main.app) as client:
        yield SimpleNamespace(client=client, runtime=runtime, services=services, traces=traces)


@pytest.mark.parametrize('dataset', ['bitcoin', 'ethereum'])
def test_group_queries_do_not_modify_or_recompute_trace(context, dataset, monkeypatch):
    traced = context.traces[dataset]
    trace_id = traced['trace_id']
    before = (context.runtime.store.folder/(trace_id+'.json')).read_bytes()

    def forbidden(*args, **kwargs):
        raise AssertionError('Group view triggered inference, tracing or snapshot writing')

    for name in ('analyze', 'trace'):
        monkeypatch.setattr(context.runtime, name, forbidden)
    monkeypatch.setattr(context.runtime.store, 'write', forbidden)
    response = context.client.get(f'/api/traces/{trace_id}/groups',
                                  params={'dataset_id': dataset, 'path_id': 'path_allowed'})
    assert response.status_code == 200, response.text
    assert response.json()['trace_id'] == trace_id
    assert response.json()['path_id'] == 'path_allowed'
    response = context.client.get(f'/api/traces/{trace_id}/groups/dense_allowed',
        params={'dataset_id': dataset, 'path_id': 'path_allowed', 'offset': 0, 'limit': 1})
    assert response.status_code == 200, response.text
    assert response.json()['nodes'][0]['risk_score'] == 12.3456789
    assert response.json()['complete'] and not response.json()['has_more']
    assert (context.runtime.store.folder/(trace_id+'.json')).read_bytes() == before


def test_cross_dataset_and_stale_index_are_rejected_before_group_lookup(context):
    trace_id = context.traces['bitcoin']['trace_id']
    for suffix in ('groups', 'groups/dense_allowed'):
        response = context.client.get(f'/api/traces/{trace_id}/{suffix}',
                                      params={'dataset_id': 'ethereum'})
        assert response.status_code == 409
    assert context.services['ethereum'].calls == []
    context.services['bitcoin'].versions['dense_group_revision'] = 'groups-2'
    for suffix in ('groups', 'groups/dense_allowed'):
        response = context.client.get(f'/api/traces/{trace_id}/{suffix}',
                                      params={'dataset_id': 'bitcoin'})
        assert response.status_code == 409
    assert context.services['bitcoin'].calls == []


def test_unknown_group_and_path_have_context_errors(context):
    trace_id = context.traces['bitcoin']['trace_id']
    response = context.client.get(f'/api/traces/{trace_id}/groups/dense_other')
    assert response.status_code == 404
    response = context.client.get(f'/api/traces/{trace_id}/groups', params={'path_id': 'path_other'})
    assert response.status_code == 404
    response = context.client.get('/api/traces/trace_missing/groups')
    assert response.status_code == 404


@pytest.mark.parametrize('params', [
    {'offset': -1}, {'offset': '1.5'}, {'limit': 0}, {'limit': 1001},
    {'path_id': ''}, {'path_id': 'x'*101}, {'dataset_id': 'other-chain'},
])
def test_group_endpoint_rejects_invalid_parameters(context, params):
    trace_id = context.traces['bitcoin']['trace_id']
    response = context.client.get(f'/api/traces/{trace_id}/groups/dense_allowed', params=params)
    assert response.status_code == 422
    assert context.services['bitcoin'].calls == []


def test_pagination_is_forwarded_without_returning_other_pages(context):
    trace_id = context.traces['ethereum']['trace_id']
    response = context.client.get(f'/api/traces/{trace_id}/groups/dense_allowed',
                                  params={'dataset_id': 'ethereum', 'offset': 1, 'limit': 1})
    assert response.status_code == 200
    assert response.json()['nodes'] == response.json()['edges'] == []
    assert context.services['ethereum'].calls[-1] == ('detail', 'dense_allowed', 1, 1)
