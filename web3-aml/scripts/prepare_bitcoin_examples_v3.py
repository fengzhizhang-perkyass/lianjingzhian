"""Recheck real BTC demonstration paths against the frozen serving release.

Old cases supply candidate addresses only: their scores, hops and evidence IDs
are never copied. This is an explicit offline step, not a request-time builder.
"""
from __future__ import annotations

import hashlib
import itertools
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]


def prepare_bitcoin_examples(root=ROOT, *, service=None, max_candidates=100, max_cases=3):
    root = Path(root).resolve()
    if max_candidates < 1 or max_cases < 1:
        raise ValueError('max_candidates and max_cases must be positive')
    if service is None:
        if str(ROOT) not in sys.path:
            sys.path.insert(0, str(ROOT))
        from api.datasets.bitcoin import BitcoinService
        service = BitcoinService(root)
    if service.dataset_id != 'bitcoin':
        raise ValueError('Bitcoin cases require the Bitcoin serving context')
    folder = Path(service.folder)
    destination = folder/'long_cases.json'
    candidates_path = root/'artifacts/tracing/long_path_cases.json'
    candidate_bytes = candidates_path.read_bytes() if candidates_path.exists() else b''
    candidate_hash = hashlib.sha256(candidate_bytes).hexdigest()
    historical = json.loads(candidate_bytes) if candidate_bytes else {}
    trace_config = {
        **service.tracer.config.get('long_path_profile', {}),
        'edge_budget': int(service.tracer.config['edge_budget']),
        'top_paths': int(service.tracer.config['top_paths']),
    }
    provenance = {
        'dataset_id': 'bitcoin', 'versions': dict(service.versions),
        'graph_revision': service.metadata['graph_revision'],
        'risk_revision': service.metadata['risk_revision'],
        'tracing_revision': service.tracer.revision,
        'candidate_source_sha256': candidate_hash,
        'trace_config': trace_config,
        'preparation_limits': {'max_candidates': max_candidates, 'max_cases': max_cases},
    }
    if destination.exists():
        previous = json.loads(destination.read_text(encoding='utf-8'))
        if (all(previous.get(key) == value for key, value in provenance.items())
                and all(case.get('trace_config') == trace_config for case in previous.get('cases', []))):
            return previous

    # Candidate order uses old demonstration seeds, then frozen predictions.
    # Neither existing hop annotations nor address truth labels are inspected.
    old_seeds = [str(case['address_id']) for case in historical.get('cases', [])
                 if isinstance(case, dict) and case.get('address_id')]
    candidates = itertools.chain(old_seeds, map(str, service.queue.address_id))
    cases, skipped = [], []
    seen = set()
    checked = 0
    for candidate in candidates:
        if checked >= max_candidates or len(cases) >= max_cases:
            break
        if candidate in seen:
            continue
        seen.add(candidate)
        try:
            address = service.predictor.resolve(candidate)
        except KeyError:
            skipped.append({'address_id': candidate, 'reason': 'not_in_current_scored_set'})
            continue
        checked += 1
        traced = service.trace(address, dict(trace_config))
        valid_paths = []
        for path in traced.get('top_paths', []):
            nodes = path.get('nodes', [])
            if len(nodes) < 3:
                continue
            actual_hops = len(nodes)-1
            if nodes[0] != address or path.get('hop_count', actual_hops) != actual_hops:
                raise ValueError('Returned BTC demonstration path has inconsistent seed/hop_count')
            valid_paths.append(path)
        if not valid_paths:
            continue
        best = max(valid_paths, key=lambda item: (len(item['nodes']), float(item.get('path_score', 0))))
        cases.append({
            'address_id': address, 'hops': len(best['nodes'])-1,
            'nodes': list(best['nodes']), 'path_score': float(best['path_score']),
            'trace_config': dict(trace_config), 'versions': dict(service.versions),
            'candidate_source': 'historical_seed' if candidate in old_seeds else 'frozen_prediction_queue',
            'method': 'Actual returned directed path under the current long profile and default top_paths',
        })
    # Sort by the newly observed path length, never by old demonstration hops.
    cases.sort(key=lambda item: (-item['hops'], -item['path_score'], item['address_id']))
    result = {
        **provenance, 'cases': cases, 'candidates_traced': checked,
        'skipped_candidates': skipped,
        'selection': 'Historical seeds followed by frozen predicted-risk order; actual returned paths only',
        'selection_bias': 'Selected demonstrations, not representative detection or tracing performance',
        'status': 'prepared' if cases else 'no_returned_path_with_at_least_two_hops',
        'training_performed': False, 'labels_opened': False,
    }
    temporary = destination.with_suffix('.json.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    temporary.replace(destination)
    return result


if __name__ == '__main__':
    prepared = prepare_bitcoin_examples()
    print(json.dumps({'dataset_id': 'bitcoin', 'cases': len(prepared['cases']),
                      'hops': [case['hops'] for case in prepared['cases']],
                      'status': prepared['status']}, ensure_ascii=False))
