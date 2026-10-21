"""Real artifacts, real algorithms, offline reports: web migration regression checks."""
import hashlib
import io
import json
import zipfile
import pytest
from fastapi.testclient import TestClient
from api.main import app
from src.report.fact_catalog import digest


@pytest.fixture(scope='module')
def client():
    with TestClient(app) as value:
        assert value.get('/api/meta').status_code == 200
        yield value


def test_landing_and_workspace_urls_share_app_shell(client):
    for path in ['/', '/workspace', '/workspace/queue', '/workspace/risk', '/workspace/trace', '/workspace/report']:
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="landing-view"' in response.text and 'id="workspace-view" hidden' in response.text
        assert '链境智安' in response.text
        assert '<script defer src="/assets/vendor/plotly.min.js">' not in response.text


def risk(client, address):
    response = client.get('/api/risk', params={'address': address})
    assert response.status_code == 200, response.text
    return response.json()


def trace(client, analysis, **extra):
    response = client.post('/api/traces', json={'analysis_id': analysis['analysis_id'], **extra})
    assert response.status_code == 200, response.text
    return response.json()


def report(client, analysis, traced=None):
    response = client.post('/api/reports', json={'analysis_id': analysis['analysis_id'],
        'trace_id': traced['trace_id'] if traced else None, 'mode': 'template'})
    assert response.status_code == 200, response.text
    return response.json()


def check_bundle(client, record):
    response = client.get('/api/reports/'+record['report_id']+'/bundle')
    assert response.status_code == 200
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['report_id'] == record['report_id']
        assert len(manifest['file_sha256']) == 6
        for filename, expected in manifest['file_sha256'].items():
            assert hashlib.sha256(archive.read(filename)).hexdigest() == expected
        assert json.loads(archive.read('evidence.json')) == record['report']['evidence_snapshot']
    return response.content


@pytest.mark.parametrize('group,index', [(g,i) for g in ['high_risk_known','low_risk_known','high_risk_unknown'] for i in range(3)])
def test_nine_real_examples_keep_original_results(client, group, index):
    meta = client.get('/api/meta').json()
    address = meta['examples'][group][index]
    analyzed = risk(client, address)
    service = app.state.runtime.service
    assert analyzed['analysis'] == service.analyze(address)
    assert abs(analyzed['analysis']['scoring_analysis']['additivity_residual']) < 1e-5
    traced = trace(client, analyzed)
    direct = service.trace(address)
    # Wall-clock measurement varies; every algorithmic output must match.
    via_http = json.loads(json.dumps(traced['result']))
    for result in [via_http, direct]:
        elapsed = result.get('search_budget', {}).pop('elapsed_ms', None)
        assert elapsed is None or elapsed >= 0
    assert via_http == direct
    for path in traced['result']['top_paths']:
        assert len(path['nodes']) == len(set(path['nodes']))
        assert all(b in service.graph.out_neighbors(a) for a,b in zip(path['nodes'],path['nodes'][1:]))
    generated = report(client, analyzed, traced)
    output = generated['report']
    assert output['source'] == 'template'
    assert output['audit']['unresolved_final_claims'] == 0
    assert output['audit']['evidence_hash'] == digest(output['evidence_snapshot'])
    for statement in output['statements']:
        fact = output['fact_catalog']['facts'][statement['claim']['fact_ids'][0]]
        assert fact['display_locator'] == statement['display_locator']
    check_bundle(client, generated)


def test_32_hop_case_and_node_id(client):
    meta = client.get('/api/meta').json(); case = meta['long_cases'][0]
    analyzed = risk(client, case['address_id'])
    assert risk(client, str(analyzed['analysis']['node_idx']))['analysis_id'] == analyzed['analysis_id']
    traced = trace(client, analyzed, mode='long')
    assert max(p['hop_count'] for p in traced['result']['top_paths']) == case['hops'] == 32
    assert traced['result']['config']['max_depth'] == 32


def test_report_autotrace_and_immutable_download(client):
    address = client.get('/api/meta').json()['examples']['high_risk_unknown'][0]
    analyzed = risk(client, address); old = report(client, analyzed)
    assert old['generated_trace']['trace_id'] == old['trace_id']
    before = check_bundle(client, old)
    changed = trace(client, analyzed, params={'max_depth':2, 'top_paths':1})
    fresh = report(client, analyzed, changed)
    assert old['report_id'] != fresh['report_id']
    assert client.get('/api/reports/'+old['report_id']).json()['trace_id'] == old['trace_id']
    assert before == client.get('/api/reports/'+old['report_id']+'/bundle').content
    for format in ['md','txt','evidence']:
        response = client.get(f"/api/reports/{old['report_id']}/export",params={'format':format})
        assert response.status_code == 200
        assert 'attachment' in response.headers['content-disposition']
    exported = client.get(f"/api/traces/{changed['trace_id']}/export")
    assert exported.json() == changed['result']


def test_validation_mismatches_and_missing_results(client):
    meta = client.get('/api/meta').json()
    a = risk(client,meta['examples']['high_risk_known'][0]); b = risk(client,meta['examples']['low_risk_known'][0]); t = trace(client,a)
    assert client.post('/api/reports',json={'analysis_id':b['analysis_id'],'trace_id':t['trace_id']}).status_code == 409
    assert client.get('/api/risk',params={'address':'ADDRESS_NOT_IN_SNAPSHOT'}).status_code == 404
    assert client.get('/api/risk',params={'address':''}).status_code == 422
    assert client.get('/api/reports/report_missing').status_code == 404
    assert client.get('/api/queue',params={'limit':1000000}).status_code == 422
    for params in [{'max_depth':33},{'edge_budget':99},{'max_depth':'3'},{'unexpected':1}]:
        assert client.post('/api/traces',json={'analysis_id':a['analysis_id'],'params':params}).status_code == 422
    bad, _ = app.state.runtime.store.write('analysis', {'address_id':a['address_id'],'analysis':a['analysis'],'versions':{}})
    assert client.post('/api/traces',json={'analysis_id':bad}).status_code == 409


def test_empty_trace_report_keeps_boundary_and_valid_download(client):
    analyzed = risk(client,client.get('/api/meta').json()['examples']['high_risk_known'][0])
    empty = trace(client, analyzed, params={'risk_threshold':100,'max_depth':1})
    assert empty['result']['top_paths'] == []
    generated = report(client,analyzed,empty)
    assert generated['report']['evidence_snapshot']['trace_analysis']['top_paths'] == []
    check_bundle(client,generated)
    assert client.post('/api/reports/'+generated['report_id']+'/demo',json={'kind':'path_score_as_risk'}).status_code == 409


def test_queue_and_evaluation_preserve_metrics(client):
    page = client.get('/api/queue?limit=10&offset=0').json()
    assert page['total'] == 822942 and len(page['rows']) == 10
    scores = [r['overall_risk_score'] for r in page['rows']]
    assert scores == sorted(scores,reverse=True)
    csv = client.get('/api/queue/export?limit=10&offset=0').content.decode('utf-8-sig')
    assert page['rows'][0]['address_id'] in csv and len(csv.splitlines()) == 11
    evaluation = client.get('/api/evaluation').json()
    assert len(evaluation['history']) == 4 and len(evaluation['comparison']) > 4
    from src.utils.io import ROOT,read_json
    original = read_json(ROOT/app.state.runtime.service.predictor.metadata['metrics_path'])
    for field in ['precision','recall','f1','pr_auc','roc_auc','confusion_matrix']:
        assert evaluation['current'][field] == original[field]


@pytest.mark.parametrize('kind',['path_score_as_risk','invented_amount','subject_swap'])
def test_fault_demonstration_stays_simulated(client,kind):
    analyzed = risk(client,client.get('/api/meta').json()['examples']['high_risk_unknown'][0])
    original = report(client,analyzed)
    response = client.post('/api/reports/'+original['report_id']+'/demo',json={'kind':kind})
    assert response.status_code == 200, response.text
    demo = response.json()
    assert demo['report']['source'] == 'fault_demo'
    assert demo['report']['audit']['candidate_error_count'] > 0
    assert demo['report']['audit']['unresolved_final_claims'] == 0
    check_bundle(client,demo)
    assert client.get('/api/reports/'+original['report_id']).json()['report']['source'] == 'template'
