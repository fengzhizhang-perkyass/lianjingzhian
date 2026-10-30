"""Real frozen services: one-address report jobs reuse only matching evidence."""
import time
import pytest
from fastapi.testclient import TestClient
from api.main import app


@pytest.fixture(scope='module',params=['bitcoin','ethereum'])
def client(request):
    with TestClient(app) as c:
        c.dataset=request.param
        response=c.get('/api/meta',params={'dataset_id':c.dataset})
        assert response.status_code==200,response.text
        c.meta=response.json();c.runtime=app.state.runtime
        yield c


def analyze(c,address=None):
    r=c.get('/api/risk',params={'dataset_id':c.dataset,'address':address or c.meta['examples']['high_risk_known'][0]})
    assert r.status_code==200,r.text
    return r.json()


def trace(c,a,params=None):
    r=c.post('/api/traces',json={'dataset_id':c.dataset,'analysis_id':a['analysis_id'],
        'params':params or {'max_depth':3,'edge_budget':1900,'top_paths':3}})
    assert r.status_code==200,r.text
    return r.json()


def submit(c,address,**extra):
    r=c.post('/api/reports/from-address',json={'dataset_id':c.dataset,'address':address,'mode':'template',**extra})
    assert r.status_code==202,r.text
    initial=r.json();deadline=time.monotonic()+30
    while time.monotonic()<deadline:
        r=c.get('/api/jobs/'+initial['job_id'],params={'dataset_id':c.dataset})
        assert r.status_code==200,r.text
        job=r.json()
        if job['status'] in ('completed','failed','interrupted'):break
        time.sleep(.025)
    assert job['status']=='completed',job
    result=job['result']
    assert result['report']['source']=='template'
    assert result['report']['audit']['unresolved_final_claims']==0
    return job


def test_identical_valid_analysis_and_trace_are_reused_without_rerunning(client,monkeypatch):
    a=analyze(client);t=trace(client,a)
    def forbidden(*args,**kwargs):raise AssertionError('A valid saved analysis/trace was recomputed')
    monkeypatch.setattr(client.runtime,'analyze',forbidden)
    monkeypatch.setattr(client.runtime,'trace',forbidden)
    j=submit(client,a['address_id'],reuse_analysis_id=a['analysis_id'],reuse_trace_id=t['trace_id'])
    assert j['reuse']['analysis'] and j['reuse']['trace']
    assert j['result']['analysis_id']==a['analysis_id'] and j['result']['trace_id']==t['trace_id']
    assert j['result']['trace']['result']['config']['edge_budget']==1900


def test_missing_trace_only_fills_trace_and_keeps_requested_parameters(client,monkeypatch):
    a=analyze(client)
    def forbidden(*args,**kwargs):raise AssertionError('Valid risk was recomputed')
    monkeypatch.setattr(client.runtime,'analyze',forbidden)
    j=submit(client,a['address_id'],reuse_analysis_id=a['analysis_id'],trace_mode='quick',
             trace_params={'max_depth':2,'edge_budget':1800,'top_paths':2})
    assert j['reuse']['analysis'] and not j['reuse']['trace']
    assert j['result']['analysis_id']==a['analysis_id']
    config=j['result']['trace']['result']['config']
    assert config['max_depth']==2 and config['edge_budget']==1800 and config['top_paths']==2


def test_changed_parameters_do_not_reuse_old_paths(client):
    a=analyze(client);t=trace(client,a)
    j=submit(client,a['address_id'],reuse_analysis_id=a['analysis_id'],reuse_trace_id=t['trace_id'],
             trace_params={'max_depth':2,'edge_budget':1700,'top_paths':2})
    assert j['reuse']['analysis'] and not j['reuse']['trace']
    assert j['reuse']['trace_refresh_reason']=='parameters_changed'
    assert j['result']['trace_id']!=t['trace_id']
    assert j['result']['trace']['result']['config']['max_depth']==2


def test_edited_target_wins_over_previous_analysis_ids(client):
    a=analyze(client);t=trace(client,a)
    other=client.meta['examples']['low_risk_known'][0]
    assert other!=a['address_id']
    j=submit(client,other,reuse_analysis_id=a['analysis_id'],reuse_trace_id=t['trace_id'])
    assert not j['reuse']['analysis'] and not j['reuse']['trace']
    assert j['address_id']==j['result']['address_id']==other
    assert j['result']['analysis']['address_id']==other
    assert j['result']['trace']['address_id']==other


def test_stale_revision_refreshes_evidence_instead_of_reusing_it(client):
    a=analyze(client)
    stale={k:v for k,v in a.items() if k!='analysis_id'}
    stale['versions']={**stale['versions'],'calibration_revision':'obsolete'}
    key,_=client.runtime.store.write('analysis',stale)
    j=submit(client,a['address_id'],reuse_analysis_id=key)
    assert not j['reuse']['analysis']
    assert j['reuse']['analysis_refresh_reason']=='revision_changed'
    assert j['result']['analysis_id']!=key
    assert j['result']['versions']==client.runtime.registry.get(client.dataset).versions


def test_other_chain_reuse_id_and_invalid_input_are_rejected_before_job(client):
    a=analyze(client);other='ethereum' if client.dataset=='bitcoin' else 'bitcoin'
    other_meta=client.get('/api/meta',params={'dataset_id':other}).json()
    r=client.post('/api/reports/from-address',json={'dataset_id':other,
        'address':other_meta['examples']['high_risk_known'][0],'reuse_analysis_id':a['analysis_id'],'mode':'template'})
    assert r.status_code==409,r.text
    count=len(list(client.runtime.jobs_folder.glob('job_*.json')))
    r=client.post('/api/reports/from-address',json={'dataset_id':client.dataset,'address':'DOES_NOT_EXIST','mode':'template'})
    assert r.status_code==404 and len(list(client.runtime.jobs_folder.glob('job_*.json')))==count
    r=client.post('/api/reports/from-address',json={'dataset_id':client.dataset,'address':a['address_id'],
        'trace_params':{'edge_budget':99},'mode':'template'})
    assert r.status_code==422


def test_machine_scores_remain_numeric_and_exact_grade_boundaries_are_shared(client):
    table=client.runtime.registry.get(client.dataset).predictor.table
    assert (table.raw_probability==table.calibrated_probability).all()
    r=client.get('/api/queue',params={'dataset_id':client.dataset,'limit':10}).json()
    assert all(isinstance(row['overall_risk_score'],(float,int)) for row in r['rows'])
    assert all(row['overall_risk_score']<100 for row in r['rows'])
    from api.datasets.base import risk_level
    assert [risk_level(x) for x in [0,29.999,30,59.999,60,79.999,80,100]]==[
        'LOW','LOW','MEDIUM','MEDIUM','HIGH','HIGH','CRITICAL','CRITICAL']
