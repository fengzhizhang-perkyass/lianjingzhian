"""Risk-anchor-guided topology-only dense groups for relation tracing.

This module deliberately does not claim transaction amount or temporal flow.
It builds deterministic bipartite dense blocks from the frozen directed
address graph, then exposes a versioned address-to-group lookup used only as
an online search prior. Address risks remain unchanged and every reported path
must still be witnessed by original directed edges.
"""
from collections import defaultdict
from pathlib import Path
import hashlib
import json
import math
import time
import heapq

from src.utils.io import file_sha256, read_json, save_json


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


class DenseGroupIndex:
    """Frozen topology-only dense groups and deterministic membership lookup."""

    def __init__(self, graph, groups, memberships, metadata):
        self.graph = graph
        self.groups = {str(key): value for key, value in groups.items()}
        self.memberships = {str(address): tuple(sorted(ids)) for address, ids in memberships.items()}
        self.metadata = dict(metadata)

    @staticmethod
    def validate_build_config(config):
        integer_keys = ('max_anchors', 'radius', 'max_nodes_per_anchor', 'min_group_nodes',
                        'min_group_edges', 'max_groups')
        for key in integer_keys:
            if type(config[key]) is not int or config[key] < 1:
                raise ValueError(f'{key} must be a positive integer')
        for key in ('min_density', 'overlap_threshold'):
            if not math.isfinite(float(config[key])) or not 0 <= float(config[key]) <= 1:
                raise ValueError(f'{key} must be within [0,1]')
        threshold = float(config['anchor_threshold'])
        if not math.isfinite(threshold) or not 0 <= threshold <= 100:
            raise ValueError('anchor_threshold must be within [0,100]')
        weights = config['score_weight']
        if set(weights) != {'density', 'mean_risk', 'anchor_fraction'} or any(
                not math.isfinite(float(value)) or value < 0 for value in weights.values()
        ) or not math.isclose(sum(weights.values()), 1.0):
            raise ValueError('Dense-group score weights must be nonnegative and sum to one')

    @classmethod
    def build(cls, graph, risks, config, provenance=None):
        """Build dense blocks around the highest frozen-risk anchors.

        The graph is represented as sender and receiver copies of each address.
        A deterministic two-sided peeling routine keeps the local block with the
        highest m/sqrt(|U||V|) objective. Risk only selects anchor-centred local
        regions and ranks completed groups; it is never rewritten.
        """
        config = dict(config)
        cls.validate_build_config(config)
        if set(risks) != set(graph.address_to_idx):
            raise ValueError('Risk table and graph must contain the same addresses')
        if any(not math.isfinite(float(value)) or not 0 <= float(value) <= 100 for value in risks.values()):
            raise ValueError('Address risks must be finite and within [0,100]')
        started = time.perf_counter()
        threshold = float(config['anchor_threshold'])
        anchors = sorted((address for address, value in risks.items() if value >= threshold),
                         key=lambda address: (-risks[address], address))[:config['max_anchors']]
        candidates = []
        inspected = 0
        for anchor in anchors:
            nodes = cls._local_nodes(graph, anchor, config['radius'], config['max_nodes_per_anchor'])
            block, count = cls._densest_block(graph, nodes)
            inspected += count
            if block is None or anchor not in block['members']:
                continue
            if (len(block['members']) < config['min_group_nodes']
                    or len(block['edges']) < config['min_group_edges']
                    or block['density'] < config['min_density']):
                continue
            members = block['members']
            anchor_members = [address for address in members if risks[address] >= threshold]
            mean_risk = sum(float(risks[address]) for address in members) / len(members)
            anchor_fraction = len(anchor_members) / len(members)
            weights = config['score_weight']
            score = 100 * (weights['density'] * block['density']
                           + weights['mean_risk'] * mean_risk / 100
                           + weights['anchor_fraction'] * anchor_fraction)
            signature = {'members': members, 'edges': block['edges']}
            candidates.append({
                'group_id': 'dense_' + _digest(signature)[:20],
                'mode': 'topology_only',
                'member_addresses': members,
                'source_members': block['sources'],
                'target_members': block['targets'],
                'internal_edges': block['edges'],
                'member_count': len(members),
                'edge_count': len(block['edges']),
                'topology_density': block['density'],
                'dense_objective': block['objective'],
                'group_score': min(max(score, 0.0), 100.0),
                'anchor_count': len(anchor_members),
                'anchor_addresses': anchor_members,
                'mean_risk': mean_risk,
                'max_risk': max(float(risks[address]) for address in members),
                'discovery_anchor': anchor,
                'amount_evidence': 'unavailable',
                'transaction_time_evidence': 'unavailable',
            })
        candidates.sort(key=lambda group: (-group['group_score'], -group['edge_count'],
                                           -group['member_count'], group['group_id']))
        accepted = []
        seen_signatures = set()
        for candidate in candidates:
            signature = tuple(candidate['member_addresses'])
            if signature in seen_signatures:
                continue
            members = set(candidate['member_addresses'])
            if any(len(members & set(group['member_addresses'])) / len(members | set(group['member_addresses']))
                   >= config['overlap_threshold'] for group in accepted):
                continue
            accepted.append(candidate)
            seen_signatures.add(signature)
            if len(accepted) >= config['max_groups']:
                break
        groups = {group['group_id']: group for group in accepted}
        memberships = defaultdict(list)
        for group_id, group in groups.items():
            for address in group['member_addresses']:
                memberships[address].append(group_id)
        metadata = {**dict(provenance or {}), 'provenance': dict(provenance or {}),
            'algorithm': 'risk_anchor_bipartite_peeling_v1',
            'algorithm_sha256': file_sha256(Path(__file__)),
            'mode': 'topology_only',
            'amount_evidence': 'unavailable',
            'transaction_time_evidence': 'unavailable',
            'build_config': config,
            'anchor_candidates': len(anchors),
            'group_count': len(groups),
            'member_address_count': len(memberships),
            'construction_edge_inspections': inspected,
            'construction_seconds': time.perf_counter() - started,
        }
        metadata['revision'] = _digest({'provenance': provenance or {}, 'config': config,
                                        'groups': groups, 'algorithm': metadata['algorithm_sha256']})
        return cls(graph, groups, memberships, metadata)

    @staticmethod
    def _local_nodes(graph, anchor, radius, limit):
        visited, frontier = {anchor}, {anchor}
        for _ in range(radius):
            discovered = set()
            for address in sorted(frontier):
                discovered.update(graph.neighbors(address))
            discovered.difference_update(visited)
            remaining = limit - len(visited)
            if remaining <= 0:
                break
            frontier = set(sorted(discovered)[:remaining])
            visited.update(frontier)
            if not frontier:
                break
        return visited

    @staticmethod
    def _densest_block(graph, nodes):
        """Two-sided deterministic peeling on sender/receiver copies."""
        node_set = set(nodes)
        edges = set()
        inspected = 0
        for source in sorted(node_set):
            for target in graph.iter_out_neighbors(source):
                inspected += 1
                if target in node_set and source != target:
                    edges.add((source, target))
        if not edges:
            return None, inspected
        source_edges, target_edges = defaultdict(set), defaultdict(set)
        for source, target in edges:
            source_edges[source].add(target)
            target_edges[target].add(source)
        sources, targets, active_edges = set(source_edges), set(target_edges), set(edges)
        # The two minimum-degree heaps give exactly the original deterministic
        # peeling order while avoiding rescanning all edges for every deletion.
        source_degree = {a: len(v) for a, v in source_edges.items()}
        target_degree = {a: len(v) for a, v in target_edges.items()}
        source_heap = [(d, a) for a, d in source_degree.items()]
        target_heap = [(d, a) for a, d in target_degree.items()]
        heapq.heapify(source_heap)
        heapq.heapify(target_heap)
        member_count = len(sources | targets)
        best, best_key = None, None
        while sources and targets and active_edges:
            density = len(active_edges) / (len(sources) * len(targets))
            objective = len(active_edges) / math.sqrt(len(sources) * len(targets))
            prefix = (objective, density, len(active_edges), -member_count)
            if best_key is None or prefix >= best_key[:4]:
                members = sorted(sources | targets)
                key = prefix + (tuple(members),)
                if best_key is None or key > best_key:
                    best_key = key
                    best = {'members': members, 'sources': sorted(sources), 'targets': sorted(targets),
                            'edges': [list(edge) for edge in sorted(active_edges)],
                            'density': density, 'objective': objective}
            for heap, degrees, active in ((source_heap, source_degree, sources),
                                          (target_heap, target_degree, targets)):
                while heap and (heap[0][1] not in active or degrees[heap[0][1]] != heap[0][0]):
                    heapq.heappop(heap)
            sd, sa = source_heap[0]
            td, ta = target_heap[0]
            _, _, side, address = min((sd / len(targets), sd, 0, sa),
                                      (td / len(sources), td, 1, ta))
            if side == 0:
                sources.remove(address)
                if address not in targets:
                    member_count -= 1
                for target in source_edges[address]:
                    if target in targets:
                        active_edges.remove((address, target))
                        target_degree[target] -= 1
                        heapq.heappush(target_heap, (target_degree[target], target))
            else:
                targets.remove(address)
                if address not in sources:
                    member_count -= 1
                for source in target_edges[address]:
                    if source in sources:
                        active_edges.remove((source, address))
                        source_degree[source] -= 1
                        heapq.heappush(source_heap, (source_degree[source], source))
        return best, inspected

    def save(self, folder: Path):
        folder.mkdir(parents=True, exist_ok=True)
        save_json(folder / 'groups.json', self.groups)
        save_json(folder / 'memberships.json', {key: list(value) for key, value in self.memberships.items()})
        metadata = dict(self.metadata)
        metadata['file_sha256'] = {name: file_sha256(folder / name)
                                   for name in ('groups.json', 'memberships.json')}
        save_json(folder / 'metadata.json', metadata)
        self.metadata = metadata

    @classmethod
    def load(cls, graph, folder: Path, provenance=None, risks=None):
        metadata = read_json(folder / 'metadata.json')
        for key, value in dict(provenance or {}).items():
            if metadata.get(key) != value:
                raise ValueError(f'Dense group index {key} mismatch')
        if metadata.get('algorithm_sha256') != file_sha256(Path(__file__)):
            raise ValueError('Dense group index algorithm revision mismatch')
        for name in ('groups.json', 'memberships.json'):
            if metadata.get('file_sha256', {}).get(name) != file_sha256(folder / name):
                raise ValueError('Dense group index file hash mismatch')
        groups, memberships = read_json(folder / 'groups.json'), read_json(folder / 'memberships.json')
        expected_revision = _digest({'provenance': metadata['provenance'],
            'config': metadata['build_config'], 'groups': groups,
            'algorithm': metadata['algorithm_sha256']})
        if metadata.get('revision') != expected_revision:
            raise ValueError('Dense group content revision mismatch')
        index = cls(graph, groups, memberships, metadata)
        index.validate_contents(risks)
        return index

    def validate_contents(self, risks=None):
        """Validate original edges, membership, and optional frozen-score math."""
        self.validate_build_config(self.metadata['build_config'])
        expected_memberships = defaultdict(list)
        out_cache = {}
        known = set(self.graph.address_to_idx)
        threshold = self.metadata['build_config']['anchor_threshold']
        weights = self.metadata['build_config']['score_weight']
        for group_id, group in self.groups.items():
            members = group['member_addresses']
            sources, targets = group['source_members'], group['target_members']
            edges = [tuple(edge) for edge in group['internal_edges']]
            if (group_id != group['group_id'] or len(set(members)) != len(members)
                    or not set(members).issubset(known)
                    or set(members) != set(sources) | set(targets)
                    or len(sources) != len(set(sources)) or len(targets) != len(set(targets))
                    or not sources or not targets or len(edges) != len(set(edges))
                    or group['member_count'] != len(members) or group['edge_count'] != len(edges)):
                raise ValueError('Dense group members or counts are inconsistent')
            if risks is not None and not set(members).issubset(risks):
                raise ValueError('Dense group contains an unscored member')
            for source, target in edges:
                if source not in sources or target not in targets or source == target:
                    raise ValueError('Dense group edge has an invalid role')
                if source not in out_cache:
                    out_cache[source] = set(self.graph.iter_out_neighbors(source))
                if target not in out_cache[source]:
                    raise ValueError('Dense group edge is absent from the original graph')
            signature = {'members': members, 'edges': group['internal_edges']}
            if group_id != 'dense_' + _digest(signature)[:20]:
                raise ValueError('Dense group identity is inconsistent')
            expected = {'topology_density': len(edges)/(len(sources)*len(targets)),
                        'dense_objective': len(edges)/math.sqrt(len(sources)*len(targets))}
            if risks is not None:
                anchors = [a for a in members if risks[a] >= threshold]
                mean = sum(risks[a] for a in members)/len(members)
                expected.update(mean_risk=mean, max_risk=max(risks[a] for a in members),
                    group_score=100*(weights['density']*expected['topology_density']
                    + weights['mean_risk']*mean/100 + weights['anchor_fraction']*len(anchors)/len(members)))
                if group['anchor_count'] != len(anchors) or group['anchor_addresses'] != anchors:
                    raise ValueError('Dense group risk anchors differ from the frozen table')
            for key, value in expected.items():
                if not math.isfinite(float(group[key])) or not math.isclose(group[key], value, abs_tol=1e-9):
                    raise ValueError('Dense group statistic mismatch: '+key)
            for address in members:
                expected_memberships[address].append(group_id)
        normalized = {a: tuple(sorted(ids)) for a, ids in expected_memberships.items()}
        if normalized != self.memberships:
            raise ValueError('Dense group membership is inconsistent')
        if (self.metadata['group_count'] != len(self.groups)
                or self.metadata['member_address_count'] != len(self.memberships)):
            raise ValueError('Dense group metadata counts differ')

    def affinity(self, seed, address, entry_weight=0.5):
        candidate_ids = set(self.memberships.get(address, ()))
        if not candidate_ids:
            return 0.0, []
        shared = candidate_ids & set(self.memberships.get(seed, ()))
        relevant = shared or candidate_ids
        score = max(float(self.groups[group_id]['group_score']) for group_id in relevant)
        return score * (1.0 if shared else entry_weight), sorted(relevant)

    def path_evidence(self, seed, nodes):
        touched = set()
        for address in nodes:
            touched.update(self.memberships.get(address, ()))
        evidence = []
        for group_id in sorted(touched):
            group = self.groups[group_id]
            members_on_path = [address for address in nodes if group_id in self.memberships.get(address, ())]
            evidence.append(self._summary(group, members_on_path, seed in group['member_addresses']))
        return sorted(evidence, key=lambda item: (-item['group_score'], item['group_id']))

    def seed_context(self, seed, limit=None):
        groups = [self.groups[group_id] for group_id in self.memberships.get(seed, ())]
        groups.sort(key=lambda group: (-group['group_score'], group['group_id']))
        return [self._summary(group, [seed], True) for group in groups[:limit]]

    @staticmethod
    def _summary(group, members_on_path, shared_with_seed):
        return {key: group[key] for key in ('group_id', 'mode', 'member_count', 'edge_count',
                'topology_density', 'dense_objective', 'group_score', 'anchor_count',
                'mean_risk', 'max_risk', 'amount_evidence', 'transaction_time_evidence')} | {
            'source_count': len(group['source_members']), 'target_count': len(group['target_members']),
            'members_on_path': list(members_on_path), 'shared_with_seed': bool(shared_with_seed)}
