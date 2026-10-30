"""Submit exactly one live address-report task and archive its true outcome."""
from __future__ import annotations

import argparse
from datetime import datetime,timezone
import hashlib
import io
import json
from pathlib import Path
import time
import traceback
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request,urlopen
import zipfile


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--url',default='http://127.0.0.1:8001')
    parser.add_argument('--dataset',choices=('bitcoin','ethereum'),required=True)
    parser.add_argument('--address')
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    out=Path(args.output).resolve();out.mkdir(parents=True,exist_ok=True)
    receipt=out/'verification.json'
    if (out/'submitted_task.json').exists():
        raise SystemExit('A task has already been submitted in this output directory; do not submit a duplicate.')
    verification={'started_at':datetime.now(timezone.utc).isoformat(),'dataset_id':args.dataset,
                  'source_mode_requested':'auto','task_submissions':0,'base_url':args.url,'checks':[]}

    def save():receipt.write_text(json.dumps(verification,ensure_ascii=False,indent=2))
    def request(path,body=None,expected=200,raw=False):
        payload=None if body is None else json.dumps(body).encode()
        req=Request(args.url+path,data=payload,headers={'Content-Type':'application/json'} if payload else {})
        try:
            with urlopen(req,timeout=45) as response:status=response.status;data=response.read()
        except HTTPError as exc:status=exc.code;data=exc.read()
        if status!=expected:raise ValueError(f'HTTP{status} {path}: '+data.decode(errors='replace')[:600])
        return data if raw else json.loads(data)
    def scoped(path):return path+'?'+urlencode({'dataset_id':args.dataset})

    try:
        meta=request(scoped('/api/meta'))
        if args.address:address=args.address
        else:
            cases=meta.get('long_cases',[])
            if args.dataset=='ethereum':case=next(item for item in cases if item['hops']==10)
            else:case=cases[0] if cases else {'address_id':meta['examples']['high_risk_known'][0]}
            address=case['address_id']
        verification.update(address_id=address,versions=meta['versions'],llm_configured=meta['capabilities']['llm_configured'])
        assert verification['llm_configured'],'Server does not report configured LLM support'
        (out/'input.json').write_text(json.dumps({'dataset_id':args.dataset,'address':address,'mode':'auto'},ensure_ascii=False,indent=2))
        # This is the only POST that can issue a real LLM request. Never retry it.
        verification['task_submissions']=1;save()
        job=request('/api/reports/from-address',{'dataset_id':args.dataset,'address':address,'mode':'auto'},expected=202)
        (out/'submitted_task.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
        verification['job_id']=job['job_id'];verification['observed_stages']=[];save()
        deadline=time.monotonic()+600;last=None
        while time.monotonic()<deadline:
            job=request(scoped('/api/jobs/'+job['job_id']))
            marker=(job['status'],job['stage'])
            if marker!=last:
                verification['observed_stages'].append({'at':datetime.now(timezone.utc).isoformat(),
                    'status':job['status'],'stage':job['stage'],'message':job.get('message')})
                save();print(json.dumps({'status':job['status'],'stage':job['stage'],'message':job.get('message')},ensure_ascii=False),flush=True)
                last=marker
            if job['status'] in ('completed','failed','interrupted'):break
            time.sleep(.7)
        (out/'task_final.json').write_text(json.dumps(job,ensure_ascii=False,indent=2))
        assert job['status']=='completed',job.get('error',job['status'])
        result=job['result'];report=result['report'];audit=report['audit']
        (out/'report.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
        (out/'report.md').write_text(report['markdown'])
        (out/'audit.json').write_text(json.dumps(audit,ensure_ascii=False,indent=2))
        verification.update(report_id=result['report_id'],actual_source=report['source'],
            api_calls=audit['api_calls'],client_request_attempts=audit.get('client_request_attempts'),
            candidate_request_count=audit.get('candidate_request_count'),
            candidate_error_count=audit['candidate_error_count'],repaired_count=audit['repaired_count'],
            coverage_added_count=audit['coverage_added_count'],local_fallback_count=audit['local_fallback_count'],
            unresolved_final_claims=audit['unresolved_final_claims'],required_fact_coverage=audit['required_fact_coverage'],
            final_statement_count=audit['final_statement_count'],request_failures=audit.get('request_failures',[]),
            fallback_reason=report.get('fallback_reason'),
            paths=len(report['evidence_snapshot']['trace_analysis'].get('top_paths',[])))
        archive=request(scoped('/api/reports/'+result['report_id']+'/bundle'),raw=True)
        (out/'audit.zip').write_bytes(archive)
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            manifest=json.loads(package.read('manifest.json'))
            assert manifest['report_id']==result['report_id']
            assert manifest['evidence_hash']==audit['evidence_hash']
            assert json.loads(package.read('audit.json'))==audit
            assert all(hashlib.sha256(package.read(name)).hexdigest()==sha for name,sha in manifest['file_sha256'].items())
        verification['audit_zip_sha256']=hashlib.sha256(archive).hexdigest()
        verification['checks'].append('ZIP member hashes and evidence/audit identity verified')
        assert result['dataset_id']==result['analysis']['dataset_id']==result['trace']['dataset_id']==args.dataset
        assert result['analysis_id']==result['analysis']['analysis_id']==result['trace']['analysis_id']
        assert result['address_id']==report['evidence_snapshot']['target']['address_id']==address
        assert audit['required_fact_coverage']==1 and audit['unresolved_final_claims']==0
        assert audit['relation_graph_checked'] and audit['frozen_risk_table_checked']
        assert 'LightGBM' not in report['markdown']
        verification['checks'].append('Dataset/address/analysis/trace/facts bound and final schema revalidated')
        assert report['source']=='llm','Task completed using template fallback, not a live LLM success'
        assert audit['api_calls']>=1
        verification['checks'].append('Actual live LLM source and positive client-call count confirmed')
        verification['passed']=True;verification['completed_at']=datetime.now(timezone.utc).isoformat();save()
        print(json.dumps({k:verification[k] for k in ['passed','report_id','actual_source','api_calls',
            'candidate_error_count','repaired_count','unresolved_final_claims','required_fact_coverage',
            'final_statement_count','audit_zip_sha256']},ensure_ascii=False),flush=True)
    except Exception:
        verification['passed']=False;verification['failure']=traceback.format_exc();save();raise


if __name__=='__main__':main()
