"""Read public paper metadata and diagnose current report validation boundaries.

Fault sentences are authored injections, not real LLM samples. This script
does not modify the deployed reporter or send project evidence to an API.
"""
import _bootstrap
from pathlib import Path
from datetime import date
import json
import re
from urllib.request import Request, urlopen
from urllib.parse import urlencode
from src.utils.io import ROOT, save_json, file_sha256
from src.report.evidence_builder import build_evidence
from src.report.llm_reporter import KEYS, validate_and_render


def diagnose(folder):
    evidence = build_evidence({'address_id':'A','risk':{'overall_score':72.76,'risk_level':'HIGH'}},
        trace_result={'seed_address':'A','config':{'max_depth':4},'top_paths':[
            {'rank':1,'nodes':['A','B','C'],'node_risks':[72.76,16.10,61.02],
             'hop_count':2,'path_score':0.3791,'evidence_id':'trace_fixture'}]},
        metadata={'risk_revision':'fixture_risk_revision'})
    cases = [
        ('valid_risk_reference','overview','地址 {{e:target.address_id}}，模型风险 {{e:risk_analysis.overall_score}}。',True,'引用值与声明类型一致'),
        ('valid_path_reference','paths','关系路径排序分 {{e:trace_analysis.top_paths.0.path_score}}。',True,'正确区分路径效用与风险'),
        ('unreferenced_number','overview','该地址风险为 99。',False,'无数字来源'),
        ('missing_field','graph','金额 {{e:missing.amount}}。',False,'字段不存在'),
        ('path_score_as_address_risk','overview','地址风险为 {{e:trace_analysis.top_paths.0.path_score}}。',False,'字段存在但含义错配'),
        ('invented_amount_chinese','paths','这笔交易金额为一百枚比特币。',False,'没有逐笔金额证据'),
        ('invented_transaction_time','paths','资金在昨日转入，随后于今日完成归集。',False,'没有逐笔时间与连续资金流证据'),
        ('invented_identity','assessment','地址 {{e:target.address_id}} 的实际控制者是张三。',False,'没有身份来源'),
        ('unsupported_legal_conclusion','assessment','据此可以认定该地址实施了洗钱行为。',False,'模型/关系不能支持法律认定'),
        ('metadata_as_risk','overview','综合风险为 {{e:meta.risk_revision}}。',False,'元数据不能当风险数值')]
    rows = []
    for name, section, sentence, expected, issue in cases:
        sections = dict.fromkeys(KEYS,'当前证据不足，建议人工复核。')
        sections[section] = sentence
        try:
            rendered = validate_and_render(sections,evidence)
            accepted, error = True,None
        except Exception as exc:
            accepted,error = False,type(exc).__name__
        rows.append({'case':name,'sentence':sentence,'expected_accept':expected,
            'current_accept':accepted,'error':error,'reason':issue})
    save_json(folder/'validator_diagnosis.json', {'scope':'10 authored contract/fault cases; not measured LLM hallucination rate',
        'production_reporter_unchanged':True,'reporter_sha256':file_sha256(ROOT/'src/report/llm_reporter.py'),
        'rows':rows,'correct_cases_accepted':sum(r['current_accept'] for r in rows if r['expected_accept']),
        'fault_cases':sum(not r['expected_accept'] for r in rows),
        'fault_cases_rejected':sum(not r['current_accept'] for r in rows if not r['expected_accept'])})
    print('Current validation diagnosis:', [(r['case'],r['current_accept']) for r in rows],flush=True)


def research(folder):
    queries = ['Enabling Large Language Models to Generate Text with Citations',
               'RARR Researching and Revising What Language Models Say Using Language Models']
    metadata_path = folder/'literature_metadata.json'
    papers = json.loads(metadata_path.read_text(encoding='utf-8')) if metadata_path.exists() else []
    failures = []
    for title in queries:
        normalized_title = re.sub('[^a-z0-9]', '', title.lower())
        if any(normalized_title == re.sub('[^a-z0-9]', '', p['title'].lower()) for p in papers):
            continue
        url = 'https://api.crossref.org/works?'+urlencode({'query.bibliographic':title,'rows':3})
        try:
            with urlopen(Request(url,headers={'User-Agent':'Web3AML-research/1.0'}),timeout=20) as response:
                items = json.load(response)['message']['items']
            item = next(i for i in items if normalized_title in
                        re.sub('[^a-z0-9]', '', ' '.join(i.get('title',[])).lower()))
            identifier = item['DOI'].split('/v1/')[-1]
            paper = {'title':item['title'][0],
                'authors':[' '.join((a.get('given',''),a.get('family',''))).strip() for a in item.get('author',[])],
                'year':item.get('published',item.get('issued'))['date-parts'][0][0],
                'venue':' '.join(item.get('container-title',[])),
                'doi':item['DOI'],'publication_type':item.get('type'),
                'citation_count':None,'full_text_status':'unknown','pdf_url':None,
                'source_platforms':['crossref'],'fetched_at':'2026-10-12',
                'publisher_url':'https://aclanthology.org/'+identifier+'/',
                'code_url':None,'abstract':None,'download_status':'not_requested'}
            papers.append(paper)
            save_json(folder/(identifier+'_crossref.json'),item)
            print('Verified metadata:',paper['title'],paper['doi'],flush=True)
        except Exception as exc:
            failures.append({'query':title,'error':type(exc).__name__})
            print('Metadata lookup unavailable:',title,type(exc).__name__,flush=True)
    save_json(folder/'literature_metadata.json',papers)
    save_json(folder/'literature_lookup_status.json',{'failures':failures})


if __name__ == '__main__':
    folder = ROOT/'artifacts/experiments/report_v3_planning'
    folder.mkdir(parents=True,exist_ok=True)
    diagnose(folder)
    research(folder)
