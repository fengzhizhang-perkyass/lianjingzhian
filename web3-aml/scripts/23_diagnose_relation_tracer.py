"""Planning audit of existing saved traces; synthetic example is explicitly separate."""
import _bootstrap
from src.utils.io import ROOT, read_json, load_config, save_json, artifact_key
from src.tracing.graph_loader import DirectedGraph
from src.tracing.beam_search import RiskGuidedTracer


def main():
    metadata = read_json(ROOT / 'artifacts/risk_scores/metadata.json')
    cases = read_json(ROOT / 'artifacts/demo_cases.json')
    tracing_config = load_config('tracing.yaml')
    archive = ROOT/'artifacts/experiments/tracing_v2_release/previous_demo'
    source_root = archive if tracing_config.get('method') == 'budgeted' else ROOT
    if source_root == archive:
        import yaml
        tracing_config = yaml.safe_load((archive/'tracing.yaml').read_text(encoding='utf-8'))
    rows = []
    for group, addresses in cases.items():
        for address in addresses:
            trace = read_json(source_root / 'artifacts/traces' / f'{artifact_key(address)}.json')
            evidence = read_json(source_root / 'artifacts/reports' / f'{artifact_key(address)}_evidence.json')
            if evidence['meta']['risk_revision'] != metadata['risk_revision']:
                raise RuntimeError('Saved case belongs to a different scoring revision')
            paths = [tuple(p['nodes']) for p in trace['top_paths']]
            prefixes = sum(any(len(path) < len(other) and other[:len(path)] == path for other in paths) for path in paths)
            edges = [(a, b) for path in paths for a, b in zip(path, path[1:])]
            rows.append({'address': address, 'group': group, 'path_count': len(paths),
                         'strict_prefix_count': prefixes, 'strict_prefix_fraction': prefixes / len(paths) if paths else 0,
                         'maximal_path_count': len(paths)-prefixes, 'edge_occurrences': len(edges), 'unique_edges': len(set(edges)),
                         'duplicate_edge_occurrence_fraction': 1-len(set(edges))/len(edges) if edges else 0,
                         'max_depth': trace['statistics']['max_reached_depth'], 'threshold': trace['config']['risk_threshold']})
    graph = DirectedGraph({0: [1], 1: [2]}, {1: [0], 2: [1]}, {'A': 0, 'B': 1, 'C': 2}, {'0': 'A', '1': 'B', '2': 'C'})
    result = RiskGuidedTracer(graph, {'A': 95, 'B': 10, 'C': 95}, tracing_config).trace('A')
    assert not result['top_paths']
    output = {'status': 'baseline_diagnosed', 'risk_revision': metadata['risk_revision'],
              'sample_scope': 'Nine hand-selected Demo cases; descriptive audit, not representative benchmark',
              'baseline_trace_source':str(source_root),
              'prefix_definition': 'A returned node sequence is a strict prefix of another returned sequence',
              'duplicate_edge_definition': '1 - unique directed edges / total edge occurrences across returned paths',
              'cases': rows, 'synthetic_threshold_failure': {'scope': 'constructed mechanism example, not real transactions',
                  'edges': [['A', 'B'], ['B', 'C']], 'scores': {'A': 95, 'B': 10, 'C': 95},
                  'threshold': result['config']['risk_threshold'], 'returned_paths': len(result['top_paths'])},
              'new_algorithm_implemented': False, 'new_algorithm_performance_validated': False}
    save_json(ROOT / 'artifacts/experiments/tracing_v2_planning/baseline_diagnosis.json', output)
    print(output)


if __name__ == '__main__':
    main()
