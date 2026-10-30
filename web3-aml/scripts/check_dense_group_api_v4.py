"""Real local two-chain group API/report acceptance; no training or score writes."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import re
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
import zipfile

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', default='http://127.0.0.1:8001')
    args = parser.parse_args(argv)
    folder = ROOT/'artifacts/v4_upgrade/api_acceptance'
    folder.mkdir(parents=True, exist_ok=True)
    receipt = {'base_url': args.url, 'scope': 'real frozen BTC/ETH, template reports; no fixtures',
               'passed': False, 'checks': [], 'datasets': {}, 'requests': []}

    def save():
        (folder/'verification.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2)+'\n')

    def check(label, **details):
        receipt['checks'].append({'name': label, **details})
        save()
        print('PASS', label, flush=True)

    def request(path, data=None, expected=200, raw=False):
        body = None if data is None else json.dumps(data).encode()
        req = Request(args.url+path, data=body,
                      headers={'Content-Type': 'application/json'} if body else {})
        try:
            with urlopen(req, timeout=180) as response:
                status, content = response.status, response.read()
        except HTTPError as error:
            status, content = error.code, error.read()
        receipt['requests'].append({'path': path, 'method': 'POST' if body else 'GET', 'status': status})
        save()
        assert status == expected, (path, status, content[:400])
        return content if raw else json.loads(content)

    def scoped(path, dataset, **params):
        return path+'?'+urlencode({'dataset_id': dataset, **params})

    try:
        for dataset in ('bitcoin', 'ethereum'):
            release = ROOT/'artifacts/datasets'/dataset/'current'
            active = json.loads((release/'dense_groups/active.json').read_text())
            index_folder = release/'dense_groups'/active['revision']
            groups = json.loads((index_folder/'groups.json').read_text())
            index = json.loads((index_folder/'metadata.json').read_text())
            group = max(groups.values(), key=lambda g: g['edge_count'])
            address, group_id = group['discovery_anchor'], group['group_id']
            meta = request(scoped('/api/meta', dataset))
            assert meta['ready'] and meta['versions']['dense_group_revision'] == active['revision']
            frame = pd.read_parquet(release/'risk_scores.parquet',
                                    columns=['address_id', 'overall_risk_score'])
            risks = frame.set_index('address_id').overall_risk_score
            baseline = json.loads((ROOT/'artifacts/v4_upgrade/baseline.json').read_text())
            assert hashlib.sha256((release/'risk_scores.parquet').read_bytes()).hexdigest() == (
                baseline['frozen_assets'][dataset]['files']['risk_scores.parquet']['sha256'])
            check(dataset+': active scoped index and original frozen risk table')
            analyzed = request(scoped('/api/risk', dataset, address=address))
            assert analyzed['analysis']['risk']['overall_score'] == float(risks[address])
            traced = request('/api/traces', {'dataset_id': dataset,
                             'analysis_id': analyzed['analysis_id'], 'mode': 'quick', 'params': {}})
            trace_id = traced['trace_id']
            assert traced['result']['dense_group_guidance']['enabled']
            assert traced['result']['provenance']['dense_group_revision'] == active['revision']
            trace_url = scoped('/api/traces/'+trace_id, dataset)
            before = request(trace_url)
            matched = request(scoped('/api/traces/'+trace_id+'/groups', dataset))
            assert matched['enabled'] and group_id in {g['group_id'] for g in matched['groups']}
            for path in traced['result']['top_paths'][:3]:
                result = request(scoped('/api/traces/'+trace_id+'/groups', dataset, path_id=path['path_id']))
                allowed_nodes = set(path['nodes']) | {address}
                assert all(set(groups[g['group_id']]['member_addresses']) & allowed_nodes for g in result['groups'])
            check(dataset+': discovery is tied to real seed and saved paths')
            nodes, edges, offset, pages = {}, {}, 0, 0
            while True:
                result = request(scoped('/api/traces/'+trace_id+'/groups/'+group_id,
                                         dataset, offset=offset, limit=137))
                pages += 1
                assert result['revision'] == active['revision']
                for node in result['nodes']:
                    assert node['is_scored'] is True and node['risk_score'] == float(risks[node['address_id']])
                    assert node['address_id'] not in nodes
                    nodes[node['address_id']] = node
                for edge in result['edges']:
                    key = (edge['src'], edge['dst'])
                    assert key not in edges and key in map(tuple, group['internal_edges'])
                    assert edge['evidence'] and all(e.get('dataset_id', dataset) == dataset for e in edge['evidence'])
                    edges[key] = edge
                if result['complete']:
                    assert not result['has_more'] and result['next_offset'] is None
                    break
                assert result['next_offset'] > offset
                offset = result['next_offset']
                assert pages < 10000
            assert set(nodes) == set(group['member_addresses'])
            assert set(edges) == set(map(tuple, group['internal_edges']))
            added = set(nodes)-{n['address_id'] for n in traced['result']['subgraph']['nodes']}
            assert added, 'Case must exercise members outside the original path graph'
            assert request(trace_url) == before, 'Discovery or expansion modified the immutable trace'
            check(dataset+': complete pagination, original edges, frozen scores and immutable trace',
                  members=len(nodes), edges=len(edges), pages=pages, added_members=len(added))
            request(scoped('/api/traces/'+trace_id+'/groups', dataset, path_id='path_not_in_trace'), expected=404)
            request(scoped('/api/traces/'+trace_id+'/groups/dense_not_in_trace', dataset), expected=404)
            other = 'ethereum' if dataset == 'bitcoin' else 'bitcoin'
            request(scoped('/api/traces/'+trace_id+'/groups', other), expected=409)
            for invalid in ({'offset': -1}, {'limit': 0}, {'limit': 1001}):
                request(scoped('/api/traces/'+trace_id+'/groups/'+group_id, dataset, **invalid), expected=422)
            check(dataset+': real cross-dataset/path/group/bounds rejection')
            # A report is generated without a browser discovery action or selected-group input.
            report = request('/api/reports', {'dataset_id': dataset, 'analysis_id': analyzed['analysis_id'],
                             'trace_id': trace_id, 'mode': 'template'})
            output = report['report']
            snapshot, audit = output['evidence_snapshot'], output['audit']
            assert audit['dense_groups_checked'] and audit['dense_group_revision'] == active['revision']
            assert audit['unresolved_final_claims'] == 0 and audit['required_fact_coverage'] == 1
            assert output['source'] == 'template' and audit['api_calls'] == 0
            assert group_id in {r['group']['group_id'] for r in snapshot['dense_group_analysis']['groups']}
            assert any(f['fact_type'] == 'dense_group' for f in output['fact_catalog']['facts'].values())
            assert '关联群组' in output['markdown'] and 'LightGBM' not in output['markdown']
            if dataset == 'ethereum':
                assert not re.search(r'融合权重|0\.6\s*[×*]|0\.4\s*[×*]|0\.6\s*[＋+]\s*0\.4', output['markdown'])
            bundle = request(scoped('/api/reports/'+report['report_id']+'/bundle', dataset), raw=True)
            with zipfile.ZipFile(io.BytesIO(bundle)) as archive:
                manifest = json.loads(archive.read('manifest.json'))
                for name, value in manifest['file_sha256'].items():
                    assert hashlib.sha256(archive.read(name)).hexdigest() == value
                assert json.loads(archive.read('evidence.json')) == snapshot
            (folder/(dataset+'_report.json')).write_text(json.dumps(report, ensure_ascii=False)+'\n')
            (folder/(dataset+'_trace.json')).write_text(json.dumps(traced, ensure_ascii=False)+'\n')
            receipt['datasets'][dataset] = {'seed': address, 'group_id': group_id, 'index': index,
                'analysis_id': analyzed['analysis_id'], 'trace_id': trace_id,
                'report_id': report['report_id'], 'group_members': len(nodes), 'group_edges': len(edges)}
            check(dataset+': automatic verified report facts and intact downloadable evidence bundle')
        receipt['passed'] = True
        save()
    except Exception as error:
        receipt['error'] = {'type': type(error).__name__, 'message': str(error)}
        save()
        raise
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
