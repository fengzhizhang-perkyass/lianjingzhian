import copy
import json
from types import SimpleNamespace
import pytest
from src.report.evidence_builder import build_evidence
from src.report.fact_catalog import FactCatalog,resolve_pointer
from src.report.claim_schema import empty_document,blueprint
from src.report.claim_validator import validate_document
from src.report.llm_reporter import LLMReporter
from src.utils.io import load_config,file_sha256


@pytest.fixture
def settings():
    return {**load_config('reporting.yaml'),'persist_audit':False}


@pytest.fixture
def evidence():
    return build_evidence({'address_id':'A','risk':{'overall_score':72.76,'risk_level':'HIGH'}},
        behavior_evidence=[{'feature':'F','value':2.1,'contribution':.3}],
        graph_evidence={'out_degree':1,'one_hop_avg_risk':34.0},
        trace_result={'seed_address':'A','config':{'max_depth':4,'risk_threshold':30},
            'top_paths':[{'rank':1,'nodes':['A','B','C'],'node_risks':[72.76,16.1,61.02],
                'hop_count':2,'path_score':.3791,'path_id':'path_fixture','evidence_id':'trace_fixture',
                'bridge_witnesses':[{'bridge_node':'B','bridge_nodes':['B'],'anchor_node':'C','edges':[['A','B'],['B','C']]}]}],
            'search_budget':{'configured_limit':2000,'actual_edge_inspections':3,'stop_reason':'NO_ELIGIBLE_EXPANSIONS'}},
        metadata={'risk_revision':'r','fingerprint':'g'})


def document(catalog):
    result=empty_document()
    for section in result['sections']:
        section['claims']=[blueprint(f) for f in catalog.facts.values() if f['required'] and f['section']==section['section']]
    return result


def first_fact(catalog,kind):
    return next(f for f in catalog.facts.values() if f['fact_type']==kind)


def client_for(*responses):
    items=iter(responses)
    calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        response=next(items)
        if isinstance(response,Exception): raise response
        text=response if isinstance(response,str) else json.dumps(response)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=text))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),calls


def reporter(tmp_path,settings,client=None):
    return LLMReporter(tmp_path,config={'enabled':client is not None,'base_url':'https://invalid.example/v1',
        'api_key':'fixture','model':'fixture','temperature':.2,'timeout':1},client=client,reporting_config=settings)


def test_pointer_escaping_nonnegative_indices_and_scalar_boundaries():
    e={'a/b':{'~value':[4,5]}}
    assert resolve_pointer(e,'/a~1b/~0value/1')==5
    for pointer in ('/a~1b/~0value/-1','/a~1b/~0value/01','/a~1b/~0value/0/x','/a~2b'):
        with pytest.raises((ValueError,KeyError)): resolve_pointer(e,pointer)


def test_catalog_freezes_source_and_detects_internal_tampering(evidence,settings):
    catalog=FactCatalog(evidence,settings)
    evidence['risk_analysis']['overall_score']=99
    assert first_fact(catalog,'address_model_risk')['value']['score']==72.76
    catalog.verify()
    first_fact(catalog,'address_model_risk')['unit']='probability'
    with pytest.raises(ValueError,match='integrity'):catalog.verify()


@pytest.mark.parametrize('field,value,code',[
    ('claim_type','address_model_risk','CLAIM_FACT_TYPE_MISMATCH'),
    ('unit','score_0_100','UNIT_MISMATCH'),
    ('subject',{'address_id':'OTHER'},'SUBJECT_MISMATCH'),
    ('wording','该地址肯定参与洗钱','WORDING_UNSUPPORTED'),
    ('fact_ids',['E_missing'],'REFERENCE_MISSING')])
def test_wrong_type_unit_subject_reference_and_wording_rejected(evidence,settings,field,value,code):
    catalog=FactCatalog(evidence,settings)
    claim=blueprint(first_fact(catalog,'relation_path'));claim[field]=value
    d=empty_document();d['sections'][3]['claims']=[claim]
    checked=validate_document(d,catalog,settings)
    assert checked['errors'][0]['error_code']==code
    assert not checked['valid']


@pytest.mark.parametrize('text',['一百枚比特币昨日转出','实际控制者是张三','据此认定洗钱','风险改成九十九分'])
def test_llm_factual_free_text_cannot_bypass_protocol(evidence,settings,text):
    catalog=FactCatalog(evidence,settings)
    claim=blueprint(first_fact(catalog,'address_model_risk'));claim['text']=text
    d=empty_document();d['sections'][0]['claims']=[claim]
    assert validate_document(d,catalog,settings)['errors'][0]['error_code']=='SCHEMA_INVALID'


def test_local_repair_keeps_passed_claim_and_revalidates_failed_slot(tmp_path,evidence,settings):
    catalog=FactCatalog(evidence,settings);d=document(catalog)
    preserved=copy.deepcopy(d['sections'][0]['claims'][0])
    correct=copy.deepcopy(d['sections'][3]['claims'][0])
    d['sections'][3]['claims'][0]['unit']='BTC'
    client,calls=client_for(d,{'repairs':[{'section':'paths','position':0,'claim':correct}]})
    result=reporter(tmp_path,settings,client).generate(evidence)
    assert result['source']=='llm' and len(calls)==2
    assert result['audit']['repaired_count']==1
    assert result['audit']['initial_passed_preserved']==result['audit']['initial_passed_count']
    assert preserved in result['claims_document']['sections'][0]['claims']
    assert result['audit']['unresolved_final_claims']==0


def test_repair_cannot_overwrite_passed_claim_or_add_unrequested_slots(tmp_path,evidence,settings):
    catalog=FactCatalog(evidence,settings);d=document(catalog)
    protected=copy.deepcopy(d['sections'][0]['claims'][0])
    d['sections'][3]['claims'][0]['unit']='BTC'
    client,calls=client_for(d,{'repairs':[{'section':'overview','position':0,'claim':protected}]})
    result=reporter(tmp_path,settings,client).generate(evidence)
    assert result['audit']['repaired_count']==0 and result['audit']['local_fallback_count']==1
    assert protected in result['claims_document']['sections'][0]['claims']
    assert len(calls)==2


def test_failed_repair_is_bounded_and_keeps_valid_content(tmp_path,evidence,settings):
    catalog=FactCatalog(evidence,settings);d=document(catalog)
    d['sections'][3]['claims'][0]['unit']='BTC'
    client,calls=client_for(d,TimeoutError('fixture'))
    result=reporter(tmp_path,settings,client).generate(evidence)
    assert len(calls)==2 and result['audit']['local_fallback_count']==1
    assert result['audit']['required_fact_coverage']==1
    assert result['audit']['initial_passed_preserved']==result['audit']['initial_passed_count']


def test_empty_candidate_does_not_claim_complete_evidence_coverage(tmp_path,evidence,settings):
    client,calls=client_for(empty_document())
    result=reporter(tmp_path,settings,client).generate(evidence)
    assert result['audit']['required_fact_coverage']==1
    assert result['statements']
    assert any(f['value'].get('evidence_id')=='trace_fixture' for f in result['fact_catalog']['facts'].values()
               if f['fact_type']=='relation_path')
    assert result['audit']['initial_passed_count']==0


def test_disabled_api_uses_same_fact_contract_and_persists_verifiable_bundle(tmp_path,evidence,settings):
    from pathlib import Path
    result=reporter(tmp_path,{**settings,'persist_audit':True}).generate(evidence)
    assert result['source']=='template' and result['audit']['api_calls']==0
    folder=Path(result['bundle_path'])
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert all(file_sha256(folder/name)==sha for name,sha in manifest['file_sha256'].items())
    bridge=next(s for s in result['statements'] if s['claim']['claim_type']=='bridge_reason')
    assert bridge['display_locator']['hops']==[0,1,2]
    assert '16.10' in bridge['text'] and '61.02' in bridge['text']
    assert bridge['source_pointers'][0]=='/trace_analysis/top_paths/0/bridge_witnesses/0'


def test_source_revision_and_fake_witness_are_rejected(evidence,settings):
    bad=copy.deepcopy(evidence);bad['trace_analysis']['provenance']={'risk_revision':'other'}
    with pytest.raises(ValueError,match='version'):FactCatalog(bad,settings)
    bad=copy.deepcopy(evidence);bad['trace_analysis']['top_paths'][0]['bridge_witnesses'][0]['edges']=[['A','C']]
    with pytest.raises(ValueError,match='edge'):FactCatalog(bad,settings)


def test_long_path_all_nodes_remain_in_snapshot_and_locator(tmp_path,settings):
    nodes=[f'N{i}' for i in range(33)]
    e=build_evidence({'address_id':nodes[0]},trace_result={'seed_address':nodes[0],
        'config':{'max_depth':32},'top_paths':[{'rank':1,'nodes':nodes,'node_risks':[5.0]*32+[65.0],
            'hop_count':32,'path_score':.01,'path_id':'long','evidence_id':'trace_long','bridge_witnesses':[]}]})
    r=reporter(tmp_path,settings).generate(e)
    fact=next(f for f in r['fact_catalog']['facts'].values() if f['fact_type']=='relation_path')
    assert fact['value']['nodes']==nodes
    assert '32 跳' in r['markdown'] and '33 个不同地址' in r['markdown']
    assert any(f['display_locator'].get('hop')==31 for f in r['fact_catalog']['facts'].values())


def test_duplicate_json_key_does_not_reach_generation_output(tmp_path,evidence,settings):
    client,calls=client_for('{"schema_version":"a","schema_version":"b"}')
    r=reporter(tmp_path,settings,client).generate(evidence)
    assert r['source']=='template' and len(calls)==1
    assert r['audit']['unresolved_final_claims']==0


@pytest.mark.parametrize('kind,code',[
    ('path_score_as_risk','CLAIM_FACT_TYPE_MISMATCH'),
    ('invented_amount','SCHEMA_INVALID'),
    ('subject_swap','SUBJECT_MISMATCH')])
def test_fault_demo_preserves_primary_report_and_labels_all_audit_exports(tmp_path,evidence,settings,kind,code):
    import hashlib
    import io
    from pathlib import Path
    import zipfile
    import yaml
    from src.report.fault_demo import generate_fault_demo
    from src.ui.report_evidence import bundle_zip
    (tmp_path/'config').mkdir()
    (tmp_path/'config/reporting.yaml').write_text(yaml.safe_dump(settings),encoding='utf-8')
    primary=reporter(tmp_path,settings).generate(evidence)
    original=copy.deepcopy(primary)
    demo=generate_fault_demo(tmp_path,primary,kind)
    assert primary==original
    assert demo['evidence_snapshot']==primary['evidence_snapshot']
    assert demo['source']==demo['audit']['source']=='fault_demo'
    assert 'no real API call' in demo['audit']['demonstration']['scope']
    audit=demo['audit']
    assert audit['candidate_error_count']==1
    assert audit['candidate_errors'][0]['error_code']==code
    assert audit['api_calls']==2 and audit['repaired_count']==1
    assert audit['initial_passed_preserved']==audit['initial_passed_count']
    assert audit['initial_passed_count']==len(primary['statements'])-1
    assert demo['claims_document']==primary['claims_document']
    folder=Path(demo['bundle_path'])
    manifest=json.loads((folder/'manifest.json').read_text(encoding='utf-8'))
    assert all(file_sha256(folder/name)==sha for name,sha in manifest['file_sha256'].items())
    assert json.loads((folder/'audit.json').read_text(encoding='utf-8'))['source']=='fault_demo'
    with zipfile.ZipFile(io.BytesIO(bundle_zip(demo))) as archive:
        zip_manifest=json.loads(archive.read('manifest.json'))
        assert all(hashlib.sha256(archive.read(name)).hexdigest()==sha
                   for name,sha in zip_manifest['file_sha256'].items())
        assert json.loads(archive.read('audit.json'))['demonstration']['kind']==kind
        assert json.loads(archive.read('evidence.json'))==primary['evidence_snapshot']


@pytest.mark.parametrize('provider',[None,'deepseek'])
def test_request_adapter_sends_thinking_only_to_deepseek(tmp_path,settings,provider):
    client,calls=client_for({'ok':True})
    r=reporter(tmp_path,settings,client)
    r.config.update(provider=provider,model='deepseek-v4-flash' if provider else 'fixture',max_tokens=8192)
    raw,_=r._request([{'role':'user','content':'Return JSON'}])
    assert json.loads(raw)=={'ok':True}
    assert calls[0]['model']==r.config['model'] and calls[0]['max_tokens']==8192
    assert calls[0]['response_format']=={'type':'json_object'}
    if provider:
        assert calls[0]['extra_body']=={'thinking':{'type':'disabled'}}
    else:
        assert 'extra_body' not in calls[0]


def test_truncated_model_output_is_not_accepted_even_if_json_valid(tmp_path,evidence,settings):
    catalog=FactCatalog(evidence,settings)
    def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='length',
            message=SimpleNamespace(content=json.dumps(document(catalog))))])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result=reporter(tmp_path,settings,client).generate(evidence)
    assert result['source']=='template' and result['audit']['api_calls']==1
    assert result['audit']['initial_passed_count']==0
    assert result['candidates'][0]['stage']=='generation_failure'
