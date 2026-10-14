"""Deterministic path coverage selection; no submodularity guarantee claimed."""


def edges(path):
    return set(zip(path['nodes'], path['nodes'][1:]))


def fold_prefixes(paths):
    maximal, records = [], []
    ordered = sorted(paths, key=lambda p: (len(p['nodes']), tuple(p['nodes'])))
    for path in ordered:
        supersets = [other for other in ordered if len(other['nodes']) > len(path['nodes'])
                    and other['nodes'][:len(path['nodes'])] == path['nodes']]
        if supersets:
            other = min(supersets, key=lambda p: (-len(p['nodes']), tuple(p['nodes'])))
            records.append({'nodes': path['nodes'], 'folded_into_nodes': other['nodes'],
                            'path_score': path['path_score'], 'reason_code': 'STRICT_PREFIX_FOLDED'})
        else:
            maximal.append(path)
    return maximal, records


def select_paths(paths, count, risks, seed, coverage_weight, overlap_weight, diverse=True, edge_weight=.1):
    remaining = sorted(paths, key=lambda p: (-p['path_score'], tuple(p['nodes'])))
    selected, seen_nodes, seen_edges = [], set(), set()
    scale = max((sum(risks[a]/100 for a in sorted(set(p['nodes'])-{seed})) + edge_weight*len(edges(p))
                 for p in remaining), default=1) or 1
    while remaining and len(selected) < count:
        choices = []
        # With diversity disabled, sorted order fully determines the winner.
        # Compute audit metadata for that winner only; avoid artificially slowing
        # ordinary Beam baselines with unused overlap calculations.
        for path in (remaining if diverse else remaining[:1]):
            node_set, edge_set = set(path['nodes'])-{seed}, edges(path)
            added_nodes, added_edges = node_set-seen_nodes, edge_set-seen_edges
            gain = sum(risks[a]/100 for a in sorted(added_nodes)) + edge_weight*len(added_edges)
            overlap = max((len(edge_set & edges(other))/len(edge_set | edges(other))
                           for other in selected), default=0)
            utility = path['path_score'] + (coverage_weight*gain/scale-overlap_weight*overlap if diverse else 0)
            choices.append((utility, path, gain, overlap, added_nodes, added_edges))
        utility, path, gain, overlap, added_nodes, added_edges = min(
            choices, key=lambda row: (-row[0], tuple(row[1]['nodes'])))
        chosen = {**path, 'selection': {'utility': utility, 'marginal_risk_coverage': gain,
                   'new_nodes': len(added_nodes), 'new_edges': len(added_edges),
                   'max_edge_overlap': overlap}}
        selected.append(chosen)
        seen_nodes.update(chosen['nodes'])
        seen_edges.update(edges(chosen))
        remaining.remove(path)
    return selected


def coverage_statistics(paths, risks, seed):
    node_set = {a for p in paths for a in p['nodes']}-{seed}
    occurrences = [(a,b) for p in paths for a,b in zip(p['nodes'],p['nodes'][1:])]
    prefixes = sum(any(len(p['nodes']) < len(q['nodes']) and q['nodes'][:len(p['nodes'])] == p['nodes']
                       for q in paths) for p in paths)
    pairs = [(edges(p), edges(q)) for i,p in enumerate(paths) for q in paths[i+1:]]
    return {'unique_nodes_excluding_seed': len(node_set), 'unique_edges': len(set(occurrences)),
            'edge_occurrences': len(occurrences), 'strict_prefix_count': prefixes,
            'duplicate_edge_fraction': 1-len(set(occurrences))/len(occurrences) if occurrences else 0,
            'mean_pairwise_edge_jaccard': sum(len(a & b)/len(a | b) for a,b in pairs)/len(pairs) if pairs else 0,
            'risk_weighted_node_coverage': sum(risks[a]/100 for a in sorted(node_set))}
