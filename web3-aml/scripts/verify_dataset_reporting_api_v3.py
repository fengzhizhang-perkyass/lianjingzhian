"""Verify a running V3 service using real data and template-only reports.

No external LLM call is made. Run explicitly; not collected as an offline unit test.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
import traceback
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8001')
    parser.add_argument('--dataset',choices=('bitcoin','ethereum'),default='ethereum')
    parser.add_argument('--output')
    args=parser.parse_args()
    out=Path(args.output or ('artifacts/v3_reporting_api_'+args.dataset)).resolve();out.mkdir(parents=True,exist_ok=True)
    result={'started_at':datetime.now(timezone.utc).isoformat(),'base_url':args.url,
            'dataset_id':args.dataset,'mode':'template','external_llm_calls':0,'events':[],'cases':[],
            'scope':'Real local running service, frozen model, observed graph, report/export/demo/background-task contracts'}

    def save():
        (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))

    def request(path,body=None,expected=200,raw=False):
        data=None if body is None else json.dumps(body).encode()
        req=Request(args.url+path,data=data,headers={'Content-Type':'application/json'} if data else {})
        started=time.monotonic()
        try:
            with urlopen(req,timeout=90) as response:
                status=response.status;payload=response.read()
        except HTTPError as exc:
            status=exc.code;payload=exc.read()
        event={'method':'POST' if body is not None else 'GET','path':path,'status':status,
               'elapsed_seconds':time.monotonic()-started}
        result['events'].append(event);save()
        if status!=expected:
            event['body']=payload.decode(errors='replace')[:3000];save()
            raise AssertionError(f'{path}: expected {expected}, got {status}: {payload[:500]!r}')
        return payload if raw else json.loads(payload)

    def scoped(path,**params):
        return path+'?'+urlencode({'dataset_id':args.dataset,**params})

    def check_report(record,name):
        report=record['report'];audit=report['audit'];facts=report['fact_catalog']['facts']
        assert record['dataset_id']==args.dataset
        assert report['dataset_id']==args.dataset and report['source']=='template'
        assert audit['api_calls']==0 and audit['unresolved_final_claims']==0
        assert audit['required_fact_coverage']==1 and audit['relation_graph_checked']
        assert audit['frozen_risk_table_checked']
        assert 'LightGBM' not in report['markdown']
        assert all(fact['subject']['dataset_id']==args.dataset for fact in facts.values())
        assert all(fact_id in facts for statement in report['statements'] for fact_id in statement['claim']['fact_ids'])
        assert all(statement['source_pointers']==facts[statement['claim']['fact_ids'][0]]['source_pointers']
                   for statement in report['statements'])
        for fact in facts.values():
            if fact['fact_type']=='path_node_unscored':
                assert fact['value']['score'] is None
        base='/api/reports/'+record['report_id']
        retrieved=request(scoped(base))
        assert retrieved['report']==report
        md=request(scoped(base+'/export',format='md'),raw=True)
        txt=request(scoped(base+'/export',format='txt'),raw=True)
        evidence=json.loads(request(scoped(base+'/export',format='evidence'),raw=True))
        assert md.decode()==txt.decode()==report['markdown']
        assert evidence==report['evidence_snapshot']
        archive=request(scoped(base+'/bundle'),raw=True)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            manifest=json.loads(package.read('manifest.json'))
            assert manifest['report_id']==record['report_id']
            assert manifest['evidence_hash']==audit['evidence_hash']
            assert all(hashlib.sha256(package.read(filename)).hexdigest()==sha
                       for filename,sha in manifest['file_sha256'].items())
            assert json.loads(package.read('audit.json'))==audit
            assert json.loads(package.read('evidence.json'))==evidence
        (out/(name+'_report.json')).write_text(json.dumps(record,ensure_ascii=False,indent=2))
        (out/(name+'_report.md')).write_bytes(md)
        (out/(name+'_audit.zip')).write_bytes(archive)
        return {'report_id':record['report_id'],'statements':audit['final_statement_count'],
                'required_fact_count':audit['required_fact_count'],
                'raw_source_location_count':audit['raw_source_location_count'],
                'unscored_facts':sum(f['fact_type']=='path_node_unscored' for f in facts.values()),
                'transaction_facts':sum(f['fact_type']=='transaction_observation' for f in facts.values()),
                'bundle_sha256':hashlib.sha256(archive).hexdigest()}

    try:
        meta=request(scoped('/api/meta'))
        (out/'meta.json').write_text(json.dumps(meta,ensure_ascii=False,indent=2))
        result['versions']=meta['versions']
        cases=meta['long_cases']
        if args.dataset=='ethereum':
            by_hops={case['hops']:case for case in cases}
            assert {10,5,4}.issubset(by_hops)
            cases=[by_hops[n] for n in (10,5,4)]
        elif not cases:
            cases=[{'address_id':meta['examples']['high_risk_known'][0],'hops':0,'trace_config':{}}]
        first=None
        for index,case in enumerate(cases[:3]):
            name=f'case_{index+1}_{case["hops"]}hop'
            analysis=request(scoped('/api/risk',address=case['address_id']))
            assert analysis['dataset_id']==args.dataset and analysis['address_id']==case['address_id']
            trace=request('/api/traces',{'dataset_id':args.dataset,'analysis_id':analysis['analysis_id'],
                'mode':'long','params':case.get('trace_config',{})})
            paths=trace['result']['top_paths']
            maximum=max((path['hop_count'] for path in paths),default=0)
            assert maximum>=case['hops'],(case['hops'],maximum)
            assert all(len(p['nodes'])==len(p['node_risks'])==p['hop_count']+1 for p in paths)
            assert all(node['risk_score'] is None for node in trace['result']['subgraph']['nodes'] if not node['is_scored'])
            report=request('/api/reports',{'dataset_id':args.dataset,'analysis_id':analysis['analysis_id'],
                'trace_id':trace['trace_id'],'mode':'template'})
            summary=check_report(report,name)
            result['cases'].append({'address_id':case['address_id'],'expected_hops':case['hops'],
                'actual_max_hops':maximum,'analysis_id':analysis['analysis_id'],'trace_id':trace['trace_id'],
                'path_count':len(paths),'unscored_path_nodes':sum(score is None for p in paths for score in p['node_risks']),
                **summary})
            (out/(name+'_analysis.json')).write_text(json.dumps(analysis,ensure_ascii=False,indent=2))
            (out/(name+'_trace.json')).write_text(json.dumps(trace,ensure_ascii=False,indent=2))
            save();print(json.dumps({'case':name,'passed':True,**summary}),flush=True)
            if first is None:first=(analysis,trace,report)
        analysis,trace,report=first
        result['demos']=[]
        for kind in ('path_score_as_risk','invented_amount','subject_swap'):
            if kind=='path_score_as_risk' and not trace['result']['top_paths']:
                request('/api/reports/'+report['report_id']+'/demo',
                        {'dataset_id':args.dataset,'kind':kind},expected=409)
                result['demos'].append({'kind':kind,'expected_rejection':'no_paths','status':409})
                continue
            demo=request('/api/reports/'+report['report_id']+'/demo',{'dataset_id':args.dataset,'kind':kind})
            d=demo['report'];assert d['source']=='simulation' and d['audit']['source']=='simulation'
            assert d['audit']['candidate_error_count']>=1 and d['audit']['unresolved_final_claims']==0
            assert 'simulated' in d['demonstration']['scope']
            original=request(scoped('/api/reports/'+report['report_id']))
            assert original['report']==report['report']
            result['demos'].append({'kind':kind,'report_id':demo['report_id'],
                'errors':d['audit']['candidate_error_count'],'repaired':d['audit']['repaired_count']})
            (out/('demo_'+kind+'.json')).write_text(json.dumps(demo,ensure_ascii=False,indent=2))
        job=request('/api/reports/from-address',{'dataset_id':args.dataset,'address':analysis['address_id'],'mode':'template'},expected=202)
        result['job_id']=job['job_id'];stages=[];deadline=time.monotonic()+120
        while time.monotonic()<deadline:
            job=request(scoped('/api/jobs/'+job['job_id']))
            stages.append({'status':job['status'],'stage':job['stage']})
            if job['status'] in ('completed','failed','interrupted'):break
            time.sleep(.15)
        assert job['status']=='completed',job
        complete=job['result']
        assert complete['analysis']['analysis_id']==complete['analysis_id']
        assert complete['trace']['trace_id']==complete['trace_id']
        assert complete['trace']['analysis_id']==complete['analysis_id']
        assert complete['analysis']['dataset_id']==complete['trace']['dataset_id']==args.dataset
        result['one_click']={'observed_stages':stages,**check_report(complete,'one_click')}
        foreign='bitcoin' if args.dataset=='ethereum' else 'ethereum'
        request('/api/reports/'+report['report_id']+'?'+urlencode({'dataset_id':foreign}),expected=409)
        request('/api/traces/'+trace['trace_id']+'?'+urlencode({'dataset_id':foreign}),expected=409)
        request('/api/jobs/'+job['job_id']+'?'+urlencode({'dataset_id':foreign}),expected=409)
        request('/api/traces',{'dataset_id':foreign,'analysis_id':analysis['analysis_id'],'params':{}},expected=409)
        request('/api/reports',{'dataset_id':foreign,'analysis_id':analysis['analysis_id'],
            'trace_id':trace['trace_id'],'mode':'template'},expected=409)
        wrong=request(scoped('/api/risk',address='not_a_dataset_address'),expected=404)
        assert wrong['code']=='not_found' and wrong['dataset_id']==args.dataset
        wrong=request('/api/reports/from-address',{'dataset_id':args.dataset,'address':'not_a_dataset_address','mode':'template'},expected=404)
        assert wrong['code']=='not_found' and 'job_id' not in wrong
        request('/api/meta?dataset_id=not_a_dataset',expected=422)
        result['passed']=True
        result['completed_at']=datetime.now(timezone.utc).isoformat();save()
        print(json.dumps({'passed':True,'output':str(out),'events':len(result['events']),
                          'cases':len(result['cases']),'external_llm_calls':0}),flush=True)
    except Exception:
        result['passed']=False;result['failure']=traceback.format_exc();save()
        raise


if __name__=='__main__':
    main()
