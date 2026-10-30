"""V3 real-release API regression; WEB_API_DATASETS=ethereum selects one chain."""
import copy
import csv
import hashlib
import io
import json
import os
import time
import zipfile
import pytest
from fastapi.testclient import TestClient
from api.main import app
from api.store import wire
from src.report.fact_catalog import digest
from src.utils.io import ROOT, read_json

DATASETS = tuple(os.environ.get('WEB_API_DATASETS', 'bitcoin,ethereum').split(','))
if not DATASETS or any(d not in ('bitcoin', 'ethereum') for d in DATASETS):
    raise ValueError('WEB_API_DATASETS must contain bitcoin and/or ethereum')


@pytest.fixture(scope='module', params=DATASETS)
def client(request):
    # No implicit bitcoin load, fake service, or skip for an unready release.
    with TestClient(app) as value:
        value.dataset_id = request.param
        response = value.get('/api/meta', params=scope(value))
        assert response.status_code == 200, response.text
        value.meta = response.json()
        value.service = app.state.runtime.registry.get(value.dataset_id)
        yield value


def scope(client, **params):
    return {'dataset_id': client.dataset_id, **params}


def risk(client, address):
    response = client.get('/api/risk', params=scope(client, address=address))
    assert response.status_code == 200, response.text
    return response.json()


def trace(client, analysis, **extra):
    response = client.post('/api/traces', json=scope(client, analysis_id=analysis['analysis_id'], **extra))
    assert response.status_code == 200, response.text
    return response.json()


def report(client, analysis, traced=None):
    response = client.post('/api/reports', json=scope(client, analysis_id=analysis['analysis_id'],
        trace_id=traced['trace_id'] if traced else None, mode='template'))
    assert response.status_code == 200, response.text
    return response.json()


def check_bundle(client, record):
    response = client.get('/api/reports/'+record['report_id']+'/bundle', params=scope(client))
    assert response.status_code == 200, response.text
    with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
        manifest = json.loads(archive.read('manifest.json'))
        assert manifest['report_id'] == record['report_id']
        assert manifest['evidence_hash'] == record['report']['audit']['evidence_hash']
        assert len(manifest['file_sha256']) == 6
        for filename, expected in manifest['file_sha256'].items():
            assert hashlib.sha256(archive.read(filename)).hexdigest() == expected
        assert json.loads(archive.read('evidence.json')) == record['report']['evidence_snapshot']
        assert json.loads(archive.read('audit.json')) == record['report']['audit']
    return response.content


def assert_report(client, generated, source='template'):
    output = generated['report']
    audit = output['audit']
    assert generated['dataset_id'] == output['dataset_id'] == client.dataset_id
    assert output['source'] == audit['source'] == source
    assert audit['unresolved_final_claims'] == 0 and audit['required_fact_coverage'] == 1
    assert audit['relation_graph_checked'] and audit['frozen_risk_table_checked']
    assert audit['evidence_hash'] == digest(output['evidence_snapshot'])
    assert 'LightGBM' not in output['markdown']
    if source == 'template':
        assert audit['api_calls'] == 0 and output['fallback_reason'] is None
    for statement in output['statements']:
        fact = output['fact_catalog']['facts'][statement['claim']['fact_ids'][0]]
        assert fact['subject']['dataset_id'] == client.dataset_id
        assert fact['display_locator'] == statement['display_locator']
        assert fact['source_pointers'] == statement['source_pointers']
    check_bundle(client, generated)


def assert_paths(service, result):
    for path in result['top_paths']:
        assert len(path['nodes']) == len(set(path['nodes'])) == path['hop_count']+1
        assert len(path['node_risks']) == len(path['nodes'])
        assert all(b in service.graph.out_neighbors(a) for a,b in zip(path['nodes'],path['nodes'][1:]))
        assert path['node_risks'] == [service.risks.get(a) for a in path['nodes']]
    for node in result['subgraph']['nodes']:
        assert node['is_scored'] == (node['address_id'] in service.risks)
        assert node['risk_score'] == service.risks.get(node['address_id'])
        if not node['is_scored']:
            assert node['risk_level'] == 'UNSCORED'


def long_case(client):
    return max(client.meta['long_cases'], key=lambda item: item['hops'])


def test_landing_and_workspace_urls_share_app_shell(client):
    for path in ['/', '/workspace', '/workspace/queue', '/workspace/risk', '/workspace/trace', '/workspace/report']:
        response = client.get(path)
        assert response.status_code == 200
        assert 'id="landing-view"' in response.text and 'id="workspace-view" hidden' in response.text
        assert '链境智安' in response.text
        assert '<script defer src="/assets/vendor/plotly.min.js">' not in response.text


@pytest.mark.parametrize('group,index', [(g,i) for g in ['high_risk_known','low_risk_known','high_risk_unknown'] for i in range(3)])
def test_nine_real_examples_keep_frozen_results(client, group, index):
    address = client.meta['examples'][group][index]
    analyzed = risk(client, address)
    assert analyzed['analysis'] == wire(client.service.analyze(address))
    scoring = analyzed['analysis']['scoring_analysis']
    assert abs(scoring['additivity_residual']) < 1e-5
    if client.dataset_id == 'ethereum':
        assert all(abs(b['additivity_residual']) < 1e-5 for b in scoring['branches'])
        assert abs(scoring['fusion']['reconstruction_error']) < 1e-10
        assert sum(b['weighted_probability'] for b in scoring['branches']) == pytest.approx(
            analyzed['analysis']['risk']['overall_score']/100, abs=1e-12)
    traced = trace(client, analyzed)
    direct = wire(client.service.trace(address))
    # Wall-clock time varies; every algorithmic output must match.
    via_http = copy.deepcopy(traced['result'])
    for result in [via_http, direct]:
        elapsed = result.get('search_budget', {}).pop('elapsed_ms', None)
        assert elapsed is None or elapsed >= 0
    assert via_http == direct
    assert_paths(client.service, traced['result'])
    assert_report(client, report(client, analyzed, traced))


def test_real_long_path_case_and_node_id(client):
    case = long_case(client)
    analyzed = risk(client, case['address_id'])
    assert risk(client, str(analyzed['analysis']['node_idx']))['analysis_id'] == analyzed['analysis_id']
    traced = trace(client, analyzed, mode='long', params=case['trace_config'])
    assert max(p['hop_count'] for p in traced['result']['top_paths']) == case['hops']
    assert traced['result']['config']['max_depth'] == case['trace_config']['max_depth']
    assert_paths(client.service, traced['result'])


def test_report_autotrace_and_immutable_download(client):
    analyzed = risk(client, client.meta['examples']['high_risk_unknown'][0])
    old = report(client, analyzed)
    assert old['generated_trace']['trace_id'] == old['trace_id']
    before = check_bundle(client, old)
    changed = trace(client, analyzed, params={'max_depth':2, 'top_paths':1})
    fresh = report(client, analyzed, changed)
    assert old['report_id'] != fresh['report_id']
    assert client.get('/api/reports/'+old['report_id'],params=scope(client)).json()['trace_id'] == old['trace_id']
    assert before == client.get('/api/reports/'+old['report_id']+'/bundle',params=scope(client)).content
    for format in ['md','txt','evidence']:
        response = client.get(f"/api/reports/{old['report_id']}/export",params=scope(client,format=format))
        assert response.status_code == 200 and 'attachment' in response.headers['content-disposition']
        if format == 'evidence':
            assert response.json() == old['report']['evidence_snapshot']
        else:
            assert response.text == old['report']['markdown']
    assert client.get(f"/api/traces/{changed['trace_id']}/export",params=scope(client)).json() == changed['result']


def test_validation_mismatches_and_missing_results(client):
    a = risk(client, client.meta['examples']['high_risk_known'][0])
    b = risk(client, client.meta['examples']['low_risk_known'][0])
    t = trace(client,a)
    assert client.post('/api/reports',json=scope(client,analysis_id=b['analysis_id'],trace_id=t['trace_id'],mode='template')).status_code == 409
    missing = client.get('/api/risk',params=scope(client,address='ADDRESS_NOT_IN_SNAPSHOT'))
    assert missing.status_code == 404 and missing.json()['dataset_id'] == client.dataset_id
    assert client.get('/api/risk',params=scope(client,address='')).status_code == 422
    assert client.get('/api/reports/report_missing',params=scope(client)).status_code == 404
    assert client.get('/api/queue',params=scope(client,limit=1000000)).status_code == 422
    assert client.get('/api/meta',params={'dataset_id':'not_a_dataset'}).status_code == 422
    for params in [{'max_depth':33},{'edge_budget':99},{'max_depth':'3'},{'unexpected':1}]:
        assert client.post('/api/traces',json=scope(client,analysis_id=a['analysis_id'],params=params)).status_code == 422
    bad, _ = app.state.runtime.store.write('analysis', {'dataset_id':client.dataset_id,
        'address_id':a['address_id'],'analysis':a['analysis'],
        'versions':{**a['versions'],'risk_revision':'stale_model_revision'}})
    assert client.post('/api/traces',json=scope(client,analysis_id=bad)).status_code == 409


def test_dataset_mismatch_rejected_before_loading_other_dataset(client):
    other = 'ethereum' if client.dataset_id == 'bitcoin' else 'bitcoin'
    a = risk(client,client.meta['examples']['high_risk_known'][0])
    t = trace(client,a)
    r = report(client,a,t)
    for kind,identifier in [('traces',t['trace_id']),('reports',r['report_id'])]:
        assert client.get(f'/api/{kind}/{identifier}',params={'dataset_id':other}).status_code == 409
    assert client.post('/api/traces',json={'dataset_id':other,'analysis_id':a['analysis_id']}).status_code == 409
    assert client.post('/api/reports',json={'dataset_id':other,'analysis_id':a['analysis_id'],
        'trace_id':t['trace_id'],'mode':'template'}).status_code == 409


def test_empty_trace_report_keeps_evidence_and_valid_download(client):
    analyzed = risk(client,client.meta['examples']['high_risk_known'][0])
    empty = trace(client,analyzed,params={'risk_threshold':100,'max_depth':1})
    assert empty['result']['top_paths'] == []
    generated = report(client,analyzed,empty)
    assert generated['report']['evidence_snapshot']['trace_analysis']['top_paths'] == []
    assert_report(client,generated)
    assert client.post('/api/reports/'+generated['report_id']+'/demo',
        json=scope(client,kind='path_score_as_risk')).status_code == 409


def test_queue_and_evaluation_preserve_frozen_release(client):
    page = client.get('/api/queue',params=scope(client,limit=10,offset=0)).json()
    assert page['dataset_id'] == client.dataset_id
    assert page['total'] == client.meta['dataset']['scored_addresses'] == len(client.service.risks)
    assert len(page['rows']) == 10
    scores = [r['overall_risk_score'] for r in page['rows']]
    assert scores == sorted(scores,reverse=True)
    assert page['rows'] == wire(client.service.queue_page(10,0))['rows']
    exported = client.get('/api/queue/export',params=scope(client,limit=10,offset=0)).content.decode('utf-8-sig')
    rows = list(csv.DictReader(io.StringIO(exported)))
    assert len(rows) == 10
    assert [r['address_id'] for r in rows] == [r['address_id'] for r in page['rows']]
    assert {r['dataset_id'] for r in rows} == {client.dataset_id}
    evaluation = client.get('/api/evaluation',params=scope(client)).json()
    assert evaluation['dataset_id'] == client.dataset_id
    # Removed evaluation UI has no history/comparison contract. Its compatibility
    # endpoint still exposes the actual frozen test result of the chosen model.
    if client.dataset_id == 'bitcoin':
        original = read_json(ROOT/'model_upgrade/remote_records/long_and_refit_test/model_upgrade/all_pretest_refit/releases/fixed_s42/test.json')
    else:
        original = read_json(ROOT/'model_upgrade/ethereum/artifacts/test_evaluation.json')['test']
    assert evaluation['current'] == wire(original)


@pytest.mark.parametrize('kind',['path_score_as_risk','invented_amount','subject_swap'])
def test_fault_demonstration_stays_simulated(client,kind):
    case = long_case(client)
    analyzed = risk(client,case['address_id'])
    traced = trace(client,analyzed,mode='long',params=case['trace_config'])
    original = report(client,analyzed,traced)
    response = client.post('/api/reports/'+original['report_id']+'/demo',json=scope(client,kind=kind))
    assert response.status_code == 200, response.text
    demo = response.json()
    assert demo['report']['source'] == demo['report']['audit']['source'] == 'simulation'
    assert 'simulated' in demo['report']['demonstration']['scope']
    assert demo['report']['audit']['candidate_error_count'] > 0
    assert_report(client,demo,source='simulation')
    assert client.get('/api/reports/'+original['report_id'],params=scope(client)).json()['report'] == original['report']


def test_independent_address_report_job_and_missing_address(client):
    address = long_case(client)['address_id']
    submitted = client.post('/api/reports/from-address',json=scope(client,address=address,mode='template'))
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()['job_id']
    deadline = time.monotonic()+60
    while time.monotonic() < deadline:
        response = client.get('/api/jobs/'+job_id,params=scope(client))
        assert response.status_code == 200, response.text
        job = response.json()
        if job['status'] in ('completed','failed','interrupted'):
            break
        time.sleep(.05)
    assert job['status'] == job['stage'] == 'completed', job
    result = job['result']
    assert result['address_id'] == address
    assert result['analysis']['analysis_id'] == result['analysis_id']
    assert result['trace']['trace_id'] == result['trace_id']
    assert result['trace']['analysis_id'] == result['analysis_id']
    assert result['analysis']['dataset_id'] == result['trace']['dataset_id'] == client.dataset_id
    assert_report(client,result)
    other = 'ethereum' if client.dataset_id == 'bitcoin' else 'bitcoin'
    assert client.get('/api/jobs/'+job_id,params={'dataset_id':other}).status_code == 409
    missing = client.post('/api/reports/from-address',json=scope(client,address='ADDRESS_NOT_IN_SNAPSHOT',mode='template'))
    assert missing.status_code == 404 and missing.json()['dataset_id'] == client.dataset_id
    assert 'job_id' not in missing.json()
    assert client.get('/api/jobs/job_'+'0'*32,params=scope(client)).status_code == 404

