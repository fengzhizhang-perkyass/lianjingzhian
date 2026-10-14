"""Explicit authored fault / simulated repair showcase; never a live model claim."""
import copy
import json
from pathlib import Path
from types import SimpleNamespace
from src.utils.io import load_config,file_sha256
from src.report.llm_reporter import LLMReporter
from src.report.legacy_reporter import KEYS,validate_and_render
from src.report.report_audit import save_bundle


def generate_fault_demo(root,report,kind,graph=None,risk_scores=None):
    if kind not in ('path_score_as_risk','invented_amount','subject_swap'):raise ValueError('Unknown demo fault')
    evidence=report['evidence_snapshot'];document=copy.deepcopy(report['claims_document'])
    section=next(s for s in document['sections'] if s['section']=='overview')
    position=next(i for i,c in enumerate(section['claims']) if c['claim_type']=='address_model_risk')
    correct=copy.deepcopy(section['claims'][position]);bad=section['claims'][position]
    baseline=dict.fromkeys(KEYS,'当前证据不足，建议人工复核。')
    score=evidence['risk_analysis']['overall_score']
    if kind=='path_score_as_risk':
        fact=next(f for f in report['fact_catalog']['facts'].values() if f['fact_type']=='relation_path')
        bad['fact_ids']=[fact['fact_id']]
        idx=fact['subject']['path_index']
        baseline['overview']=f'综合地址风险为{{{{e:trace_analysis.top_paths.{idx}.path_score}}}}。'
        sentence=f"把路径排序分 {fact['value']['path_score']:.4f} 写成地址风险，实际综合地址风险为 {score:.2f}。"
    elif kind=='invented_amount':
        bad['text']='交易金额为一百枚比特币。'
        baseline['overview']=bad['text']
        sentence='注入“交易金额为一百枚比特币”，当前Evidence没有逐笔金额证据。'
    else:
        bad['subject']={'address_id':'OTHER_FAULT_FIXTURE'}
        baseline['overview']='下游地址风险为{{e:risk_analysis.overall_score}}。'
        sentence='把目标地址的评分说成另一地址的评分。'
    try:validate_and_render(baseline,evidence);legacy_accepted=True
    except Exception:legacy_accepted=False
    responses=iter([document,{'repairs':[{'section':'overview','position':position,'claim':correct}]}])
    def create(**kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(next(responses))))])
    client=SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
    settings={**load_config('reporting.yaml',root),'persist_audit':False}
    result=LLMReporter(root,config={'enabled':True,'base_url':'https://invalid.example/v1','api_key':'mock',
        'model':'mock','temperature':.2,'timeout':1},client=client,reporting_config=settings).generate(evidence,graph=graph,risk_scores=risk_scores)
    context={'kind':kind,'scope':'authored fault and simulated correct repair response; no real API call',
        'legacy_accepted':legacy_accepted,'injected_description':sentence,'injected_claim':bad,'corrected_claim':correct,
        'demo_code_sha256':file_sha256(Path(__file__))}
    result['source']='fault_demo';result['audit']['source']='fault_demo';result['audit']['demonstration']=context
    result['demonstration']=context
    result['bundle_path']=save_bundle(root,result)
    return result
