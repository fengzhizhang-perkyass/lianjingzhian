"""V3 reports bind real numerical fields to dataset-scoped, null-safe facts."""
import copy
import json
import math
from types import SimpleNamespace

import httpx
import pytest
from openai import APITimeoutError, AuthenticationError

from api.exporter import bundle_zip
from src.report.claim_schema import blueprint, empty_document
from src.report.claim_validator import validate_document
from src.report.dataset_reporting import (
    DatasetFactCatalog, DatasetReportGenerator, build_dataset_evidence,
    generate_dataset_report, generate_dataset_fault_demo,
)
from src.report.fact_catalog import digest
from src.report.fault_demo import generate_fault_demo
from src.utils.io import file_sha256, load_config


@pytest.fixture
def settings():
    return {**load_config('reporting.yaml'), 'persist_audit': False}


def service_inputs(root, dataset_id='ethereum'):
    fingerprint = dataset_id + '_fingerprint'
    revision = dataset_id + '_risk'
    risks = {'A': 56.0 if dataset_id=='ethereum' else 80., 'C': 85.}
    if dataset_id=='bitcoin':
        risks['U'] = 4.
    graph = SimpleNamespace(metadata={'fingerprint':fingerprint},
                            out_neighbors=lambda a: {'A':['U'],'U':['C'],'C':[]}[a])
    service = SimpleNamespace(root=root,dataset_id=dataset_id,graph=graph,risks=risks,
        versions={'dataset_id':dataset_id,'dataset_fingerprint':fingerprint,
                  'risk_revision':revision,'feature_revision':'f','graph_revision':'g'},
        metadata={'fingerprint':fingerprint,'risk_revision':revision,
                  'feature_count':56 if dataset_id=='ethereum' else 1783,
                  'model_threshold':.5776478277617538 if dataset_id=='ethereum' else .1622163259483896},
        edge_evidence=lambda src,dst,limit=3:[{'src':src,'dst':dst,'source_file':'synthetic_fixture.csv',
            'source_row':2,'source_type':'test_fixture','relation_exists':True}])

    def tree(key, probability, groups):
        margin=math.log(probability/(1-probability))
        return {'key':key,'label':key,'probability':probability,
                'raw_margin':margin,'base_value':margin-sum(g['contribution'] for g in groups),
                'groups':groups,'evidence':{groups[0]['key']:[{
                    'feature':'合成测试特征','raw_feature':'fixture','feature_value':2.0,
                    'model_input_value':2.0,'contribution':groups[0]['contribution'],
                    'attribution_target':key+'_raw_margin'}]},'additivity_residual':0.}
    if dataset_id=='ethereum':
        a=tree('attribute',.4,[{'key':'behavior','label':'交易属性画像','contribution':.2}])
        b=tree('joint',.8,[{'key':'behavior','label':'交易属性画像','contribution':.3},
                           {'key':'structure','label':'交易结构表征','contribution':.4}])
        a.update(weight=.6,weighted_probability=.24)
        b.update(weight=.4,weighted_probability=.32)
        scoring={**copy.deepcopy(b),'kind':'dual_view','branches':[a,b],
                 'route_scores':{},'revision':revision,'structure_summary':{'dimensions':32},
                 'fusion':{'method':'weighted_probability','weights':{'attribute':.6,'joint':.4},
                           'probability':.56}}
    else:
        scoring=tree('joint',.8,[{'key':'behavior','label':'交易行为画像','contribution':.4},
                                {'key':'context','label':'邻域行为偏离','contribution':.6},
                                {'key':'structure','label':'资金流转特征','contribution':-.2}])
        scoring.update(kind='grouped_tree',route_scores={},revision=revision)
    analysis={'dataset_id':dataset_id,'address_id':'A','node_idx':0,
              'risk':{'overall_score':risks['A'],'risk_level':'MEDIUM' if dataset_id=='ethereum' else 'CRITICAL'},
              'scoring_analysis':scoring,'behavior_evidence':[],
              'graph_evidence':{'out_degree':1,'in_degree':0,'one_hop_avg_risk':None,
                                'one_hop_scored_count':0 if dataset_id=='ethereum' else 1,
                                'one_hop_unscored_count':1 if dataset_id=='ethereum' else 0}}
    trace={'dataset_id':dataset_id,'seed_address':'A','provenance':service.versions,
           'config':{'risk_threshold':30,'max_depth':4},
           'top_paths':[{'rank':1,'nodes':['A','U','C'],'node_risks':[risks['A'],risks.get('U'),85.],
              'hop_count':2,'path_score':.48,'path_id':'path_synthetic',
              'bridge_witnesses':[{'bridge_node':'U','bridge_nodes':['U'],'anchor_node':'C',
                                  'edges':[['A','U'],['U','C']]}]}],
           'search_budget':{'configured_limit':2000,'actual_edge_inspections':2,'stop_reason':'COMPLETED'}}
    return service,analysis,trace


def llm_document(catalog):
    document=empty_document()
    for section in document['sections']:
        section['claims']=[blueprint(fact) for fact in catalog.facts.values()
                           if fact['section']==section['section'] and fact['required']]
    return document


def generator(root, settings, responses, progress=None):
    replies=iter(responses);calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        item=next(replies)
        if isinstance(item,Exception):
            raise item
        return SimpleNamespace(choices=[SimpleNamespace(finish_reason='stop',message=SimpleNamespace(
            content=item if isinstance(item,str) else json.dumps(item)))])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    result=DatasetReportGenerator(root,config={'enabled':True,'base_url':'https://invalid.example/v1',
        'api_key':'fixture-secret','model':'fixture','temperature':.2,'timeout':1},
        client=client,reporting_config=settings,progress=progress)
    return result,calls


@pytest.mark.parametrize('dataset_id',['bitcoin','ethereum'])
def test_template_full_contract_exports_and_frozen_snapshot(tmp_path,dataset_id):
    service,analysis,trace=service_inputs(tmp_path,dataset_id)
    evidence=build_dataset_evidence(service,analysis,trace)
    report=generate_dataset_report(service,evidence,mode='template')
    assert report['dataset_id']==dataset_id
    assert report['fallback_reason'] is None and report['audit']['requested_mode']=='template'
    assert report['audit']['required_fact_coverage']==1
    assert report['audit']['unresolved_final_claims']==0
    assert report['audit']['relation_graph_checked'] and report['audit']['frozen_risk_table_checked']
    assert 'LightGBM' not in report['markdown']
    assert '温度校准' not in report['markdown'] and '单组诊断分' not in report['markdown']
    assert report['statements'] and all(s['claim']['fact_ids'] and s['citation_label'] for s in report['statements'])
    assert all(f['subject']['dataset_id']==dataset_id for f in report['fact_catalog']['facts'].values())
    folder=tmp_path/'artifacts/reports'/report['report_id']
    manifest=json.loads((folder/'manifest.json').read_text())
    assert json.loads((folder/'audit.json').read_text())==report['audit']
    assert all(file_sha256(folder/name)==sha for name,sha in manifest['file_sha256'].items())
    assert bundle_zip(report).startswith(b'PK')
    original=copy.deepcopy(report['evidence_snapshot'])
    analysis['risk']['overall_score']=99
    trace['top_paths'][0]['node_risks'][1]=0
    assert report['evidence_snapshot']==original


def test_unscored_connector_is_not_a_zero_score_or_anchor(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    catalog=DatasetFactCatalog(evidence,settings,service.graph,service.risks)
    unscored=[f for f in catalog.facts.values() if f['fact_type']=='path_node_unscored']
    assert len(unscored)==1 and unscored[0]['value']['score'] is None
    assert not any(f['fact_type']=='path_node_risk' and f['subject']['address_id']=='U' for f in catalog.facts.values())
    assert not any(f['label']=='一跳邻居平均风险' for f in catalog.facts.values())
    bad=copy.deepcopy(evidence);bad['trace_analysis']['top_paths'][0]['node_risks'][1]=0
    with pytest.raises(ValueError,match='fabricated'):
        DatasetFactCatalog(bad,settings,service.graph,service.risks)
    bad=copy.deepcopy(evidence);bad['trace_analysis']['top_paths'][0]['bridge_witnesses'][0]['anchor_node']='U'
    with pytest.raises(ValueError,match='subject'):
        DatasetFactCatalog(bad,settings,service.graph,service.risks)


@pytest.mark.parametrize('where',['analysis_dataset','trace_dataset','revision','fingerprint'])
def test_cross_dataset_or_revision_is_rejected(tmp_path,where):
    service,analysis,trace=service_inputs(tmp_path)
    if where=='analysis_dataset':analysis['dataset_id']='bitcoin'
    if where=='trace_dataset':trace['dataset_id']='bitcoin'
    if where=='revision':trace['provenance']={**trace['provenance'],'risk_revision':'old_model'}
    if where=='fingerprint':trace['provenance']={**trace['provenance'],'dataset_fingerprint':'foreign'}
    with pytest.raises(ValueError):build_dataset_evidence(service,analysis,trace)


@pytest.mark.parametrize('tamper',['weight','branch_probability','fusion','additivity','legacy_scores'])
def test_frozen_native_explanations_and_fusion_are_verified(tmp_path,tamper):
    service,analysis,trace=service_inputs(tmp_path)
    scoring=analysis['scoring_analysis']
    if tamper=='weight':scoring['branches'][0]['weight']=.5
    if tamper=='branch_probability':scoring['branches'][0]['probability']=.41
    if tamper=='fusion':scoring['fusion']['probability']=.6
    if tamper=='additivity':scoring['branches'][0]['groups'][0]['contribution']=5
    if tamper=='legacy_scores':scoring['route_scores']={'behavior':88.}
    with pytest.raises(ValueError):build_dataset_evidence(service,analysis,trace)


def test_graph_edges_and_typed_claim_subjects_are_verified(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    wrong_graph=SimpleNamespace(metadata=service.graph.metadata,out_neighbors=lambda a:[])
    with pytest.raises(ValueError,match='edge'):
        DatasetFactCatalog(evidence,settings,wrong_graph,service.risks)
    catalog=DatasetFactCatalog(evidence,settings,service.graph,service.risks)
    document=llm_document(catalog)
    claim=document['sections'][0]['claims'][0]
    claim['subject']['dataset_id']='bitcoin'
    assert validate_document(document,catalog,settings)['errors'][0]['error_code']=='SUBJECT_MISMATCH'


def test_timeout_retry_success_has_no_stale_template_notice(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    catalog=DatasetFactCatalog(evidence,settings,service.graph,service.risks)
    stages=[]
    error=APITimeoutError(request=httpx.Request('POST','https://invalid.example'))
    reporter,calls=generator(tmp_path,settings,[error,llm_document(catalog)],stages.append)
    report=reporter.generate(evidence,service.graph,service.risks)
    assert len(calls)==2 and report['source']=='llm' and report['fallback_reason'] is None
    assert report['audit']['request_failures']==[{'code':'timeout','error_type':'APITimeoutError'}]
    assert stages[:2]==['generation','generation'] and stages[-1]=='validation'
    assert report['audit']['api_calls']==2
    assert report['audit']['candidate_request_count']==1


def test_auth_error_is_not_retried_and_secrets_are_not_in_audit(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    error=AuthenticationError('fixture-secret',response=httpx.Response(401,
        request=httpx.Request('POST','https://invalid.example')),body=None)
    reporter,calls=generator(tmp_path,settings,[error])
    report=reporter.generate(evidence,service.graph,service.risks)
    assert len(calls)==1 and report['source']=='template'
    assert '密钥验证失败' in report['fallback_reason']
    assert 'fixture-secret' not in json.dumps(report,ensure_ascii=False)


def test_unsupported_llm_prose_cannot_enter_the_report(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    catalog=DatasetFactCatalog(evidence,settings,service.graph,service.risks)
    document=llm_document(catalog)
    document['sections'][0]['claims'][0]['text']='昨日转出一百枚以太币，已证实洗钱'
    reporter,_=generator(tmp_path,settings,[document,{'repairs':[]}])
    report=reporter.generate(evidence,service.graph,service.risks)
    assert report['audit']['candidate_error_count']==1
    assert report['audit']['unresolved_final_claims']==0
    assert '昨日转出' not in report['markdown']
    assert report['audit']['local_fallback_count']==1


def test_dataset_fault_demo_uses_the_same_catalog_and_preserves_primary(tmp_path):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    report=generate_dataset_report(service,evidence,mode='template')
    baseline=digest(report)
    demo=generate_fault_demo(tmp_path,report,'invented_amount',service.graph,service.risks)
    assert digest(report)==baseline
    assert demo['source']=='fault_demo'
    assert demo['audit']['candidate_error_count']==1
    assert demo['audit']['unresolved_final_claims']==0
    assert demo['audit']['repaired_count']==1


@pytest.mark.parametrize('kind',['path_score_as_risk','invented_amount','subject_swap'])
def test_service_fault_demo_is_explicitly_simulated_and_hash_consistent(tmp_path,kind):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    report=generate_dataset_report(service,evidence,mode='template')
    demo=generate_dataset_fault_demo(service,report,kind)
    assert demo['source']=='simulation' and demo['audit']['source']=='simulation'
    assert demo['audit']['api_calls']==2 and demo['audit']['unresolved_final_claims']==0
    assert 'simulated' in demo['demonstration']['scope']
    folder=tmp_path/'artifacts/reports'/demo['report_id']
    assert json.loads((folder/'audit.json').read_text())==demo['audit']


def test_fault_demo_without_paths_is_rejected(tmp_path):
    service,analysis,trace=service_inputs(tmp_path)
    trace['top_paths']=[]
    report=generate_dataset_report(service,build_dataset_evidence(service,analysis,trace),'template')
    with pytest.raises(ValueError,match='没有关系路径'):
        generate_dataset_fault_demo(service,report,'path_score_as_risk')


def test_transaction_observations_keep_exact_units_and_source_positions(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    def edge(src,dst,limit=3):
        return [{'src':src,'dst':dst,'tx_hash':'0x'+'a'*64,
                 'value_wei':'1000000000000000001','value_eth':'1.000000000000000001','unit':'ETH',
                 'block_timestamp':1700000000,'source_file':'synthetic.csv','source_row':2,
                 'raw_source_locations':[{'source_file':'synthetic.csv','source_row':2,'source_sha256':'fixture'}]}]
    service.edge_evidence=edge
    evidence=build_dataset_evidence(service,analysis,trace)
    catalog=DatasetFactCatalog(evidence,settings,service.graph,service.risks)
    fact=next(f for f in catalog.facts.values() if f['fact_type']=='transaction_observation')
    assert fact['value']['value_eth']=='1.000000000000000001'
    assert fact['raw_source_locations'][0]['source_row']==2
    report=generate_dataset_report(service,evidence,'template')
    assert '1.000000000000000001 ETH' in report['markdown']
    def bad_edge(src,dst,limit=3):
        record=edge(src,dst,limit)[0];record['value_eth']='1.1';return [record]
    service.edge_evidence=bad_edge
    with pytest.raises(ValueError,match='unit conversion'):
        build_dataset_evidence(service,analysis,trace)


def test_wrong_direction_source_record_is_rejected(tmp_path):
    service,analysis,trace=service_inputs(tmp_path)
    service.edge_evidence=lambda src,dst,limit=3:[{'src':dst,'dst':src}]
    with pytest.raises(ValueError,match='directed relation'):
        build_dataset_evidence(service,analysis,trace)


def test_source_filename_is_only_locator_not_a_risk_label(tmp_path,settings):
    service,analysis,trace=service_inputs(tmp_path)
    evidence=build_dataset_evidence(service,analysis,trace)
    catalog=DatasetFactCatalog(evidence,settings,service.graph,service.risks)
    reporter=DatasetReportGenerator(tmp_path,config={'enabled':False},reporting_config=settings)
    prompt=reporter._prompt(catalog)
    assert 'phisher、normal' in prompt[0]['content']
    assert '不得据此推断目标地址标签' in prompt[0]['content']
    assert any(f['policy_key']=='source_name_boundary' for f in catalog.facts.values())
