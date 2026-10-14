"""Paired authored-fault contract study and real-evidence integration checks.

Mock repairs are explicitly labeled; no measured natural LLM hallucination rate.
Baseline and typed protocol have different expression spaces, reported openly.
"""
import _bootstrap
import argparse
import copy
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import pandas as pd
from src.utils.io import ROOT,load_config,save_json,read_json,file_sha256
from src.report.evidence_builder import build_evidence
from src.report.fact_catalog import FactCatalog
from src.report.claim_schema import empty_document,blueprint
from src.report.claim_validator import validate_document
from src.report.llm_reporter import LLMReporter
from src.report.legacy_reporter import KEYS,validate_and_render
from src.report.report_audit import reporting_revision
from src.tracing.graph_loader import DirectedGraph


def fixture(i,rng):
    a,b,c=[f'{name}_fixture_{i}' for name in ('A','B','C')]
    score=float(rng.uniform(60,80))
    return build_evidence({'address_id':a,'risk':{'overall_score':score,'risk_level':'HIGH'}},
        behavior_evidence=[{'feature':'feature_fixture','value':2.0,'contribution':.2}],
        graph_evidence={'out_degree':1},trace_result={'seed_address':a,'config':{'max_depth':4,'risk_threshold':30},
        'top_paths':[{'rank':1,'nodes':[a,b,c],'node_risks':[score,16.1,61.02],'hop_count':2,
            'path_score':.3791,'path_id':'fixture_path','evidence_id':'fixture_trace','bridge_witnesses':[]}]},
        metadata={'risk_revision':'fixture_revision'})


def candidate(catalog):
    document=empty_document()
    for section in document['sections']:
        section['claims']=[blueprint(f) for f in catalog.facts.values() if f['required'] and f['section']==section['section']]
    return document


def paired_fault(kind,catalog,document):
    d=copy.deepcopy(document);baseline=dict.fromkeys(KEYS,'当前证据不足，建议人工复核。')
    claim=d['sections'][0]['claims'][0]
    correct=copy.deepcopy(claim)
    slot={'section':'overview','position':0,'claim':correct}
    if kind=='unreferenced_number':
        baseline['overview']='模型风险为99。';claim['value']=99
    elif kind=='missing_reference':
        baseline['overview']='{{e:missing.score}}';claim['fact_ids']=['E_missing']
    elif kind=='path_score_as_risk':
        baseline['overview']='地址风险为{{e:trace_analysis.top_paths.0.path_score}}。'
        claim['fact_ids']=[next(f['fact_id'] for f in catalog.facts.values() if f['fact_type']=='relation_path')]
    elif kind=='chinese_amount':
        baseline['overview']='资金流转金额为一百枚比特币。';claim['text']=baseline['overview']
    elif kind=='invented_time':
        baseline['overview']='资金昨日转入，并于今日完成转移。';claim['text']=baseline['overview']
    elif kind=='invented_identity':
        baseline['overview']='实际控制者为张三。';claim['text']=baseline['overview']
    elif kind=='legal_conclusion':
        baseline['overview']='可以认定该地址实施了洗钱行为。';claim['wording']='legal_conclusion'
    elif kind=='metadata_as_risk':
        baseline['overview']='模型风险为{{e:meta.risk_revision}}。';claim['fact_ids']=['E_metadata_not_a_registered_fact']
    elif kind=='subject_swap':
        baseline['overview']='下游地址风险为{{e:risk_analysis.overall_score}}。';claim['subject']={'address_id':'OTHER'}
    elif kind=='unit_swap':
        baseline['overview']='金额为{{e:risk_analysis.overall_score}}枚比特币。';claim['unit']='BTC'
    return baseline,d,slot


def mock_client(*documents):
    iterator=iter(documents);calls=[]
    def create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(iterator))))])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))),calls


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--experiment',default='report_v3_release')
    args=parser.parse_args()
    if not args.experiment.replace('_','').isalnum():raise ValueError('Invalid experiment name')
    folder=ROOT/'artifacts/experiments'/args.experiment;folder.mkdir(parents=True,exist_ok=True)
    config=load_config('report_experiments.yaml');settings=load_config('reporting.yaml')
    frozen_revision=reporting_revision()
    save_json(folder/'protocol.json',{'config':config,'reporting':settings,'reporting_revision':reporting_revision(),
        'script_sha256':file_sha256(Path(__file__)),
        'baseline_sha256':file_sha256(ROOT/'src/report/legacy_reporter.py'),
        'scope':'authored paired fault injections; mock repair responses; real-evidence offline integration',
        'live_llm_tested':False,'different_expression_spaces':True})
    offline={**settings,'persist_audit':False}
    cfg={'enabled':True,'base_url':'https://invalid.example/v1','api_key':'mock','model':'mock','temperature':.2,'timeout':1}
    rows=[];rng=np.random.default_rng(config['seed'])
    for i in range(config['variants']):
        evidence=fixture(i,rng);catalog=FactCatalog(evidence,settings);clean=candidate(catalog)
        good=validate_document(clean,catalog,settings)
        assert not good['structural_error'] and not good['errors']
        for kind in config['faults']:
            baseline,bad,repair=paired_fault(kind,catalog,clean)
            try:validate_and_render(baseline,evidence);old_rejected=False
            except Exception:old_rejected=True
            typed=validate_document(bad,catalog,settings)
            client,calls=mock_client(bad,{'repairs':[repair]})
            result=LLMReporter(ROOT,config=cfg,client=client,reporting_config=offline).generate(evidence)
            audit=result['audit']
            rows.append({'variant':i,'fault':kind,'legacy_rejected':old_rejected,
                'typed_rejected':bool(typed['errors'] or typed['structural_error']),
                'mock_repaired':audit['repaired_count']==1,'initial_valid':audit['initial_passed_count'],
                'preserved':audit['initial_passed_preserved'],'api_calls':len(calls),
                'final_unresolved':audit['unresolved_final_claims'],'required_coverage':audit['required_fact_coverage']})
    save_json(folder/'fault_rows.json',rows);pd.DataFrame(rows).to_csv(folder/'fault_rows.csv',index=False)
    graph=DirectedGraph.load()
    active=read_json(ROOT/'artifacts/risk_scores/metadata.json')
    risks=pd.read_parquet(ROOT/'artifacts/risk_scores/risk_scores.parquet',columns=['address_id','overall_risk_score']).set_index('address_id').overall_risk_score.to_dict()
    cases=read_json(ROOT/'artifacts/demo_cases.json')
    addresses=list(dict.fromkeys(a for values in cases.values() if isinstance(values,list) for a in values))
    addresses.append('12e1Cni7bu2fYNVJR1x98PcpfFUrup1TJo')
    actual=[]
    for address in addresses:
        path=ROOT/'artifacts/reports'/f'{address}_evidence.json'
        if not path.exists():continue
        e=read_json(path)
        assert e['meta']['risk_revision']==active['risk_revision']
        report=LLMReporter(ROOT,config={'enabled':False},reporting_config=settings).generate(e,graph=graph,risk_scores=risks)
        audit=report['audit']
        assert audit['unresolved_final_claims']==0 and audit['required_fact_coverage']==1
        # Exact all-source values and full paths remain in the snapshot.
        assert report['evidence_snapshot']==e
        assert all(f['display_locator'].get('path_index',0)<len(e['trace_analysis']['top_paths'])
            for f in report['fact_catalog']['facts'].values() if f['display_locator']['view'] in ('path','bridge'))
        actual.append({'address_id':address,'report_id':report['report_id'],'bundle_path':report['bundle_path'],
            'statement_count':audit['final_statement_count'],'required_coverage':audit['required_fact_coverage'],
            'max_hops':max((p['hop_count'] for p in e['trace_analysis']['top_paths']),default=0),
            'raw_csv_facts':sum(bool(f['raw_source_locations']) for f in report['fact_catalog']['facts'].values())})
    save_json(folder/'real_cases.json',actual)
    result={'fault_cases':len(rows),'valid_protocol_cases':config['variants'],
        'legacy_rejections':sum(r['legacy_rejected'] for r in rows),'typed_rejections':sum(r['typed_rejected'] for r in rows),
        'mock_repairs_succeeded':sum(r['mock_repaired'] for r in rows),
        'initial_valid_statements':sum(r['initial_valid'] for r in rows),'preserved_valid_statements':sum(r['preserved'] for r in rows),
        'real_cases':len(actual),'max_real_hops':max((r['max_hops'] for r in actual),default=0),
        'live_llm_tested':False,'scope':'protocol failure detection, mock repair mechanism and snapshot integration; not natural hallucination rate',
        'reporting_revision':reporting_revision()}
    if reporting_revision()!=frozen_revision: raise RuntimeError('Reporting source changed during experiment; rerun in a fresh directory')
    save_json(folder/'results.json',result)
    (folder/'REPORT.md').write_text('# 模块三协议核验与真实证据闭环实验\n\n'
        '范围：人为故障注入＋模拟API修复＋真实Evidence模板闭环。没有真实LLM自然生成样本。\n\n'
        f"- 故障用例：{result['fault_cases']}；旧引用校验拒绝{result['legacy_rejections']}，新类型协议拒绝{result['typed_rejections']}。\n"
        f"- 正确协议用例：{result['valid_protocol_cases']}，均通过。\n"
        f"- 模拟正确修复响应：{result['mock_repairs_succeeded']}次成功；保留已通过声明{result['preserved_valid_statements']}/{result['initial_valid_statements']}。\n"
        f"- 真实证据闭环：{result['real_cases']}个案例，最长{result['max_real_hops']}跳，快照完整且必选事实覆盖齐全。\n\n"
        '表达空间不同：新协议拒绝任意事实自由文本，以程序回填事实；不能据此宣称通用语义理解全面提升或自然幻觉下降某个比例。模拟修复不代表真实LLM修复成功率。\n\n'
        '[逐故障结果](fault_rows.csv) · [真实案例与审计包位置](real_cases.json) · [运行前协议](protocol.json)\n',encoding='utf-8')
    print(result,flush=True)


if __name__=='__main__':main()
