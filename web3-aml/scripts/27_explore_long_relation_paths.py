"""Long-path diagnostics on real directed relations, without AML path truth.

Separates repeated 108 stratified seeds from deliberately selected long-distance
demo seeds. Every displayed edge and unchanged risk is checked against the graph.
No default deployment or old experimental records are modified.
"""
import _bootstrap
import argparse
from collections import Counter
from pathlib import Path
import time
import numpy as np
import pandas as pd
from src.utils.io import ROOT, load_config, read_json, save_json, file_sha256
from src.tracing.graph_loader import DirectedGraph
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.budgeted_tracer import BudgetedRelationTracer


def check(result, graph, risks):
    for path in result['top_paths']:
        assert len(path['nodes']) == len(set(path['nodes']))
        assert path['node_risks'] == [float(risks[a]) for a in path['nodes']]
        for a, b in zip(path['nodes'], path['nodes'][1:]):
            assert graph.address_to_idx[b] in graph.outgoing.get(graph.address_to_idx[a], [])
    assert result['search_budget']['actual_edge_inspections'] <= result['config']['edge_budget']


def row(result, seed, method):
    paths = result['top_paths']
    return {**seed, 'method': method, 'paths': len(paths),
        'longest_hops': max((p['hop_count'] for p in paths), default=0),
        'unique_edges': result['selection_analysis']['unique_edges'],
        'anchors': len({a for p in paths for a in p['nodes'][1:]
                       if result['_risks'][a] >= result['config']['risk_threshold']}),
        'checks': result['search_budget']['actual_edge_inspections'],
        'elapsed_ms': result['search_budget']['elapsed_ms'],
        'stop_reason': result['search_budget']['stop_reason']}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--experiment', default='tracing_long_paths_v2')
    args = parser.parse_args()
    if not args.experiment.replace('_', '').isalnum():
        raise ValueError('Invalid experiment name')
    settings = load_config('tracing_long_paths.yaml')
    config = load_config('tracing.yaml')
    folder = ROOT / 'artifacts/experiments' / args.experiment
    folder.mkdir(parents=True, exist_ok=True)
    save_json(folder/'protocol.json', {'config': settings, 'base_tracing_config': config,
        'script_sha256': file_sha256(Path(__file__)),
        'scope': 'exploratory repeat public-data seeds; selected demos are not performance estimates',
        'all_parameters_saved_before_runs': True})
    started = time.perf_counter()
    graph = DirectedGraph.load()
    meta = read_json(ROOT/'artifacts/risk_scores/metadata.json')
    provenance = {k: meta[k] for k in ('risk_revision', 'dataset_fingerprint')}
    risks = pd.read_parquet(ROOT/'artifacts/risk_scores/risk_scores.parquet',
        columns=['address_id', 'overall_risk_score']).set_index('address_id').overall_risk_score.to_dict()
    stats_meta = read_json(ROOT/'artifacts/risk_scores/graph_statistics_metadata.json')
    assert all(stats_meta[k] == provenance[k] for k in provenance)
    stats = pd.read_parquet(ROOT/'artifacts/risk_scores/graph_statistics.parquet',
        columns=['address_id','one_hop_avg_risk']).set_index('address_id').to_dict(orient='index')
    index = RiskAnchorIndex.build(graph, risks, config['risk_threshold'], settings['index_depth'], provenance)
    index.save(folder/'anchor_index')
    histogram = dict(sorted(Counter(map(int, index.distance)).items()))
    save_json(folder/'graph_diagnostics.json', {'provenance': provenance,
        'nodes': len(risks), 'edges': sum(len(v) for v in graph.outgoing.values()),
        'shortest_anchor_distance_histogram': histogram, 'index': index.metadata,
        'loading_and_index_seconds': time.perf_counter()-started})
    print('Distance histogram:', histogram, flush=True)
    tracer = BudgetedRelationTracer(graph, risks, config, stats, provenance, index)
    manifest = read_json(ROOT/'artifacts/experiments/tracing_v2_release_stable/seed_manifest.json')
    seeds = manifest['seeds']
    # Select farthest reachable seeds by distance then address, using no labels.
    demo_depth = max(m['max_depth'] for m in settings['methods'].values())
    eligible = sorted((a for a in risks if 8 <= index.distance[graph.address_to_idx[a]] <= demo_depth),
        key=lambda a: (-int(index.distance[graph.address_to_idx[a]]), a))
    demo_seeds = [{'split': 'selected_demo', 'address_id': a,
        'shortest_anchor_distance': int(index.distance[graph.address_to_idx[a]])}
        for a in eligible[:settings['demo_count']]]
    save_json(folder/'seed_manifest.json', {'repeated_seeds': seeds, 'selected_demo_seeds': demo_seeds,
        'demo_selection': 'longest finite shortest-anchor distance within tested depth, then address; no labels'})
    rows, demos = [], []
    for i, seed in enumerate(seeds + demo_seeds):
        for method, overrides in settings['methods'].items():
            result = tracer.trace(seed['address_id'], overrides)
            check(result, graph, risks)
            result['_risks'] = risks
            rows.append(row(result, seed, method))
            del result['_risks']
            if seed['split'] == 'selected_demo' or any(p['hop_count'] >= 8 for p in result['top_paths']):
                demos.append({'method': method, 'seed': seed, 'result': result})
        if (i+1) % 12 == 0:
            print('Completed seeds:', i+1, flush=True)
    frame = pd.DataFrame(rows)
    frame.to_csv(folder/'rows.csv', index=False)
    summary = []
    for (split, method), group in frame.groupby(['split','method']):
        summary.append({'split': split, 'method': method, 'seeds': len(group),
            'nonempty': int((group.paths > 0).sum()), 'max_hops': int(group.longest_hops.max()),
            'seeds_ge8_hops': int((group.longest_hops >= 8).sum()),
            'seeds_ge16_hops': int((group.longest_hops >= 16).sum()),
            'mean_longest_hops': float(group.longest_hops.mean()),
            'sum_unique_edges': int(group.unique_edges.sum()), 'sum_anchors': int(group.anchors.sum()),
            'mean_checks': float(group.checks.mean()), 'p95_ms': float(group.elapsed_ms.quantile(.95))})
    save_json(folder/'results.json', {'provenance': provenance, 'tracing_revision': tracer.revision,
        'summary': summary, 'rows': rows, 'checks': 'all returned edges real, simple paths, frozen risks, budget respected'})
    save_json(folder/'selected_demo_traces.json', demos)
    print(pd.DataFrame(summary).to_string(index=False), flush=True)


if __name__ == '__main__':
    main()
