"""Explicit real-service V3.1 report verification; template mode is the default.

Use --mode auto only when a live LLM validation has been explicitly scheduled.
One report job is submitted; failed report jobs are never automatically resubmitted.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
from pathlib import Path
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8001')
    parser.add_argument('--dataset', choices=('bitcoin', 'ethereum'), required=True)
    parser.add_argument('--mode', choices=('template', 'auto'), default='template')
    parser.add_argument('--address')
    parser.add_argument('--output')
    args = parser.parse_args(argv)
    folder = Path(args.output or f'artifacts/v31_reporting_{args.dataset}_{args.mode}').resolve()
    folder.mkdir(parents=True, exist_ok=True)
    receipt = {'started_at': datetime.now(timezone.utc).isoformat(), 'base_url': args.url,
               'dataset_id': args.dataset, 'requested_mode': args.mode, 'report_job_submissions': 0,
               'requests': [], 'checks': [], 'passed': False}

    def save():
        (folder/'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')

    def request(path, body=None, expected=200, raw=False):
        payload = None if body is None else json.dumps(body).encode()
        req = Request(args.url+path, data=payload,
                      headers={'Content-Type': 'application/json'} if payload else {})
        try:
            with urlopen(req, timeout=120) as response:
                status, data = response.status, response.read()
        except HTTPError as error:
            status, data = error.code, error.read()
        receipt['requests'].append({'method': 'POST' if body is not None else 'GET',
                                    'path': path, 'status': status})
        save()
        if status != expected:
            raise AssertionError(f'{path}: HTTP {status}, expected {expected}: {data[:400]!r}')
        return data if raw else json.loads(data)

    def scoped(path, **params):
        return path+'?'+urlencode({'dataset_id': args.dataset, **params})

    def write_json(name, data):
        (folder/name).write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n')

    try:
        meta = request(scoped('/api/meta'))
        write_json('meta.json', meta)
        receipt['versions'] = meta['versions']
        case = next(iter(meta.get('long_cases', [])), {})
        address = args.address or case.get('address_id') or meta['examples']['high_risk_known'][0]
        receipt['address_id'] = address
        analysis = request(scoped('/api/risk', address=address))
        traced = request('/api/traces', {'dataset_id': args.dataset,
                         'analysis_id': analysis['analysis_id'], 'mode': 'long',
                         'params': case.get('trace_config', {})})
        write_json('analysis.json', analysis)
        write_json('trace.json', traced)
        receipt['checks'].append('Real current analysis and trace created before the report job')
        submitted = request('/api/reports/from-address', {'dataset_id': args.dataset,
                            'address': address, 'mode': args.mode,
                            'reuse_analysis_id': analysis['analysis_id'],
                            'reuse_trace_id': traced['trace_id'], 'trace_mode': 'long',
                            'trace_params': case.get('trace_config', {})}, expected=202)
        receipt['report_job_submissions'] = 1
        receipt['job_id'] = submitted['job_id']
        write_json('submitted_task.json', submitted)
        stages = []
        deadline = time.monotonic()+240
        while time.monotonic() < deadline:
            job = request(scoped('/api/jobs/'+submitted['job_id']))
            state = {key: job.get(key) for key in ('status', 'stage', 'message')}
            if not stages or stages[-1] != state: stages.append(state)
            if job['status'] in ('completed', 'failed', 'interrupted'): break
            time.sleep(.25)
        receipt['observed_stages'] = stages
        write_json('task_final.json', job)
        assert job['status'] == 'completed', job.get('error', job.get('message'))
        record = job['result']
        assert record['analysis_id'] == analysis['analysis_id']
        assert record['trace_id'] == traced['trace_id']
        report, audit = record['report'], record['report']['audit']
        receipt['checks'].append('Same-address valid analysis and user trace were reused')
        assert record['versions'] == meta['versions']
        assert record['dataset_id'] == report['dataset_id'] == args.dataset
        assert audit['unresolved_final_claims'] == 0 and audit['required_fact_coverage'] == 1
        assert audit['native_calibration_probability_chain_checked']
        assert audit['calibration_revision'] == meta['versions']['calibration_revision']
        assert audit['trace_scope'] == meta['versions']['trace_scope']
        if args.mode == 'template':
            assert report['source'] == 'template' and audit['api_calls'] == 0
        else:
            assert report['source'] == 'llm' and audit['api_calls'] >= 1
            assert report['fallback_reason'] is None
        receipt.update(report_id=record['report_id'], actual_source=report['source'],
                       actual_client_requests=audit['api_calls'],
                       candidate_error_count=audit['candidate_error_count'],
                       final_statement_count=audit['final_statement_count'],
                       unresolved_final_claims=audit['unresolved_final_claims'],
                       required_fact_coverage=audit['required_fact_coverage'])
        snapshot = report['evidence_snapshot']
        score = snapshot['risk_analysis']['overall_score']
        assert score == analysis['analysis']['risk']['overall_score']
        expected_level = 'LOW' if score < 30 else 'MEDIUM' if score < 60 else 'HIGH' if score < 80 else 'CRITICAL'
        assert snapshot['risk_analysis']['risk_level'] == expected_level
        assert not any(term in report['markdown'] for term in ('融合权重', '加权风险分', '按0.6', '按0.4', 'LightGBM'))
        if 99.995 <= score < 100: assert '>99.99 / 100' in report['markdown']
        for statement in report['statements']:
            for fact_id in statement['claim']['fact_ids']:
                assert fact_id in report['fact_catalog']['facts']
        if args.dataset == 'ethereum':
            assert snapshot['meta']['trace_scope'] == 'ethereum_scored_addresses_only'
            assert snapshot['scoring_analysis']['fusion']['weights'] == {'attribute': .6, 'joint': .4}
            assert '未评分' not in report['markdown']
            assert all(node['is_scored'] and node['risk_score'] is not None
                       for node in snapshot['trace_analysis']['subgraph']['nodes'])
            assert all(score is not None for path in snapshot['trace_analysis']['top_paths']
                       for score in path['node_risks'])
            receipt['checks'].append('Scored-only true paths, no unscored public prose; audit fusion retained')
        receipt['checks'].append('Precise scores, exact grade and native/calibration chain verified')
        base = '/api/reports/'+record['report_id']
        md = request(scoped(base+'/export', format='md'), raw=True)
        txt = request(scoped(base+'/export', format='txt'), raw=True)
        evidence = request(scoped(base+'/export', format='evidence'))
        archive = request(scoped(base+'/bundle'), raw=True)
        assert md.decode() == txt.decode() == report['markdown']
        assert evidence == snapshot
        with zipfile.ZipFile(io.BytesIO(archive)) as package:
            manifest = json.loads(package.read('manifest.json'))
            assert manifest['report_id'] == record['report_id']
            assert all(hashlib.sha256(package.read(name)).hexdigest() == sha
                       for name, sha in manifest['file_sha256'].items())
            assert json.loads(package.read('audit.json')) == audit
            assert json.loads(package.read('evidence.json')) == snapshot
        receipt['checks'].append('Markdown/TXT/Evidence/ZIP match and every ZIP member hash verified')
        write_json('report.json', report)
        write_json('audit.json', audit)
        (folder/'report.md').write_bytes(md)
        (folder/'audit.zip').write_bytes(archive)
        receipt['audit_zip_sha256'] = hashlib.sha256(archive).hexdigest()
        receipt.update(passed=True, completed_at=datetime.now(timezone.utc).isoformat())
        save()
        print(json.dumps(receipt, ensure_ascii=False, indent=2))
        return 0
    except Exception as error:
        receipt['error'] = {'type': type(error).__name__, 'message': str(error)}
        save()
        raise


if __name__ == '__main__':
    raise SystemExit(main())
