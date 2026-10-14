"""Versioned, bounded relation tracing with optional relevance/bridges/coverage.

Risk scores are frozen module-one predictions. All traversed edges, including
lookahead and PPR, share a request-local budget; no ground-truth labels are read.
"""
from collections import Counter
from pathlib import Path
import hashlib
import json
import math
import time
import numpy as np
from src.tracing.search_budget import SearchBudget
from src.tracing.local_relevance import local_push
from src.tracing.path_scorer import expand_score, path_score
from src.tracing.path_selection import select_paths, fold_prefixes, coverage_statistics
from src.utils.io import ROOT, save_json, artifact_key, file_sha256


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode('utf-8')).hexdigest()


class BudgetedRelationTracer:
    def __init__(self, graph, risk_scores, config, graph_statistics=None, provenance=None, anchor_index=None):
        self.graph, self.risks, self.config = graph, risk_scores, dict(config)
        self.graph_statistics = graph_statistics or {}
        self.provenance = dict(provenance or {})
        self.anchor_index = anchor_index
        fingerprint = graph.metadata.get('fingerprint')
        if fingerprint and self.provenance.get('dataset_fingerprint') != fingerprint:
            raise ValueError('Tracing graph and risk table dataset fingerprints do not match')
        if set(risk_scores) != set(graph.address_to_idx):
            raise ValueError('Risk table and graph must contain the same addresses')
        if any(not math.isfinite(float(v)) or not 0 <= v <= 100 for v in risk_scores.values()):
            raise ValueError('Address risks must be finite and within [0,100]')
        self.degree_p99 = float(np.percentile([sum(graph.degrees(a)) for a in risk_scores],99)) if risk_scores else 0
        folder = Path(__file__).parent
        self.revision = stable_hash({name: file_sha256(folder/name) for name in (
            'budgeted_tracer.py','search_budget.py','local_relevance.py','path_selection.py','path_scorer.py','graph_loader.py','anchor_index.py')})

    @staticmethod
    def validate(config):
        for key in ('max_depth','beam_width','max_neighbors_per_node','top_paths','edge_budget','max_frontier','max_ppr_pushes','max_bridge_candidates','max_bridge_nodes','max_event_records'):
            if type(config[key]) is not int or config[key] < 1:
                raise ValueError(f'{key} must be a positive integer')
        for key in ('risk_threshold','high_risk_threshold','output_anchor_threshold'):
            if not math.isfinite(config[key]) or not 0 <= config[key] <= 100:
                raise ValueError(f'{key} must be within [0,100]')
        for key in ('ppr_budget_fraction','bridge_budget_fraction','relevance_weight','coverage_weight','overlap_weight','bridge_penalty','edge_coverage_weight'):
            if not math.isfinite(config[key]) or not 0 <= config[key] <= 1:
                raise ValueError(f'{key} must be within [0,1]')
        if not 0 < config['restart_probability'] < 1 or not 0 < config['ppr_tolerance'] < 1:
            raise ValueError('Invalid PPR restart or tolerance')
        if not config['cycle_check']:
            raise ValueError('Budgeted tracing requires cycle_check')
        for key in ('ppr_enabled','bridge_enabled','diverse_search','diverse_selection','fold_prefixes','cycle_check','anchor_index_enabled'):
            if type(config[key]) is not bool:
                raise ValueError(f'{key} must be a boolean')
        weights = config['score_weight']
        if set(weights) != {'risk','neighbor_risk','degree_penalty'} or any(
                not math.isfinite(v) or v < 0 for v in weights.values()) or not math.isclose(sum(weights.values()),1):
            raise ValueError('Expansion weights must be nonnegative and sum to one')
        if config['traversal'] not in ('beam','bfs'):
            raise ValueError('Unsupported traversal')
        if not math.isfinite(config['length_decay']) or config['length_decay'] < 0:
            raise ValueError('Invalid length decay')

    def trace(self, seed, overrides=None):
        if seed not in self.risks:
            raise KeyError(f'Unknown seed: {seed}')
        config = {**self.config, **(overrides or {})}
        self.validate(config)
        if config['anchor_index_enabled']:
            if self.anchor_index is None:
                raise ValueError('Anchor index is required for this method')
            for key,value in {**self.provenance,'threshold':config['risk_threshold']}.items():
                if self.anchor_index.metadata.get(key) != value:
                    raise ValueError(f'Anchor index {key} mismatch')
            if self.anchor_index.metadata['max_depth'] < config['max_depth']:
                raise ValueError('Anchor index depth is insufficient')
        started = time.perf_counter()
        budget = SearchBudget(config['edge_budget'])
        reasons, events = Counter(), []
        considered, retained = set(), {seed}
        expansion_cache = {}
        bridge_limit = int(config['edge_budget']*config['bridge_budget_fraction'])
        event_count = 0

        def reason(code, nodes=None, witness=None):
            nonlocal event_count
            reasons[code] += 1
            if nodes:
                event_count += 1
                if len(events) < config['max_event_records']:
                    events.append({'reason_code':code, 'nodes':list(nodes), 'witness':witness})

        def expansion(address):
            if address not in expansion_cache:
                # All methods receive identical cached context. Missing cache is explicit,
                # not a hidden graph traversal that could bypass the inspection budget.
                stats = self.graph_statistics.get(address)
                neighbor_risk = float(stats['one_hop_avg_risk']) if stats is not None else 0.0
                expansion_cache[address] = expand_score(self.risks[address], neighbor_risk,
                    sum(self.graph.degrees(address)), self.degree_p99, config['score_weight'])
            return expansion_cache[address]

        ppr, relevance = {}, {'enabled':False}
        if config['ppr_enabled']:
            ppr, relevance = local_push(self.graph, seed, budget,
                int(config['edge_budget']*config['ppr_budget_fraction']), config['restart_probability'],
                config['ppr_tolerance'], config['max_ppr_pushes'])
            relevance['enabled'] = True

        def make_path(nodes, bridges):
            base = path_score([expansion(a) for a in nodes[1:]],config['length_decay'])
            related = sum(ppr.get(a,0) for a in nodes[1:])/(len(nodes)-1)
            weight = config['relevance_weight'] if config['ppr_enabled'] else 0
            penalty = config['bridge_penalty']*sum(len(w['bridge_nodes']) for w in bridges)/(len(nodes)-1)
            return {'nodes':nodes, 'path_score': max(0.0,(1-weight)*base+weight*related-penalty),
                    'bridge_witnesses':bridges, 'score_components':{'risk_path_score':base,
                    'seed_relevance_score':related, 'relevance_weight':weight,'bridge_penalty':penalty}}

        def bridge_connections(nodes, neighbor):
            if config['anchor_index_enabled']:
                connection = self.anchor_index.connection(neighbor,set(nodes),config['max_bridge_nodes'],
                    config['max_depth']-len(nodes),budget)
                if connection:
                    reason('ANCHOR_INDEX_WITNESS',nodes+connection[0]+[connection[1]])
                    return [connection]
                # A shortest witness may point back into this path; bounded online
                # lookahead can still find an alternative. Negative distance certifies
                # absence only within the index's recorded depth.
                distance = int(self.anchor_index.distance[self.graph.address_to_idx[neighbor]])
                if distance < 0 or distance > min(config['max_bridge_nodes'],config['max_depth']-len(nodes)):
                    reason('NO_REACHABLE_ANCHOR_WITHIN_DEPTH',nodes+[neighbor])
                    return []
            # Atomic completion: no unfinished low-risk prefix enters the output.
            frontier, connections = [[neighbor]], []
            while frontier and budget.total < budget.limit and budget.counts['bridge'] < bridge_limit:
                connector = frontier.pop(0)
                witnesses = list(budget.scan(self.graph,connector[-1],'bridge',bridge_limit))
                considered.update(witnesses)
                witnesses.sort(key=lambda a:(-self.risks[a],a))
                for anchor in witnesses[:config['max_neighbors_per_node']]:
                    if anchor in nodes or anchor in connector:
                        reason('CYCLE_BLOCKED',nodes+connector+[anchor])
                        continue
                    if self.risks[anchor] >= config['risk_threshold']:
                        connections.append((connector,anchor))
                    elif len(connector) < config['max_bridge_nodes'] and len(nodes)+len(connector)+1 <= config['max_depth']:
                        if len(frontier) < config['max_frontier']:
                            frontier.append(connector+[anchor])
                        else:
                            reason('FRONTIER_LIMIT')
            return sorted(connections,key=lambda row:(-self.risks[row[1]],len(row[0]),tuple(row[0]),row[1]))[:config['max_neighbors_per_node']]

        beam = [{'nodes':[seed], 'bridge_witnesses':[], 'path_score':0}]
        completed = {}
        rounds = 0
        while beam and rounds < config['max_depth'] and budget.total < budget.limit:
            rounds += 1
            candidates = {}
            for path in beam:
                nodes = path['nodes']
                if len(nodes)-1 >= config['max_depth']:
                    continue
                neighbors = list(budget.scan(self.graph,nodes[-1],'search'))
                considered.update(neighbors)
                if len(neighbors) < self.graph.degrees(nodes[-1])[0]:
                    reason('BUDGET_EXHAUSTED',nodes)
                neighbors.sort(key=lambda a:(-self.risks[a],a))
                if len(neighbors) > config['max_neighbors_per_node']:
                    reasons['NEIGHBOR_LIMIT'] += len(neighbors)-config['max_neighbors_per_node']
                # Bridge quota supplements the normal top-risk neighbor list. The union
                # remains bounded; scanning all candidates has already been charged.
                selected_neighbors = neighbors[:config['max_neighbors_per_node']]
                if config['bridge_enabled']:
                    extras = [a for a in neighbors if self.risks[a] < config['risk_threshold']][:config['max_bridge_candidates']]
                    selected_neighbors = list(dict.fromkeys(selected_neighbors+extras))
                bridge_attempts = 0
                for neighbor in selected_neighbors:
                    if neighbor in nodes:
                        reason('CYCLE_BLOCKED',nodes+[neighbor])
                        continue
                    if self.risks[neighbor] >= config['risk_threshold']:
                        item = make_path(nodes+[neighbor],path['bridge_witnesses'])
                        candidates[tuple(item['nodes'])] = item
                        continue
                    reason('RISK_BELOW_THRESHOLD',nodes+[neighbor])
                    if not config['bridge_enabled'] or len(nodes)+1 > config['max_depth']:
                        continue
                    if bridge_attempts >= config['max_bridge_candidates']:
                        reason('BRIDGE_CANDIDATE_LIMIT')
                        continue
                    bridge_attempts += 1
                    connections = bridge_connections(nodes,neighbor)
                    for connector,anchor in connections:
                        witness_nodes = [nodes[-1]]+connector+[anchor]
                        witness = {'bridge_node':neighbor,'bridge_nodes':connector,'anchor_node':anchor,
                            'edges':[list(edge) for edge in zip(witness_nodes,witness_nodes[1:])],
                            'reason_code':'BRIDGE_WITNESS_FOUND'}
                        item = make_path(nodes+connector+[anchor],path['bridge_witnesses']+[witness])
                        candidates[tuple(item['nodes'])] = item
                        reason('BRIDGE_WITNESS_FOUND',item['nodes'],witness)
                    if not connections:
                        reason('BRIDGE_WITHOUT_WITNESS',nodes+[neighbor])
            if not candidates:
                beam = []
                break
            candidates = list(candidates.values())
            if config['traversal'] == 'bfs':
                beam = sorted(candidates,key=lambda p:tuple(p['nodes']))[:config['max_frontier']]
                reasons['FRONTIER_LIMIT'] += max(0,len(candidates)-len(beam))
            else:
                beam = select_paths(candidates,config['beam_width'],self.risks,seed,
                    config['coverage_weight'],config['overlap_weight'],config['diverse_search'],config['edge_coverage_weight'])
                reasons['BEAM_PRUNED'] += max(0,len(candidates)-len(beam))
            for path in beam:
                retained.update(path['nodes'])
                completed[tuple(path['nodes'])] = path

        candidates = list(completed.values())
        candidates = [path for path in candidates if self.risks[path['nodes'][-1]] >= config['output_anchor_threshold']]
        folded = []
        if config['fold_prefixes']:
            candidates, folded = fold_prefixes(candidates)
        paths = select_paths(candidates,config['top_paths'],self.risks,seed,
            config['coverage_weight'],config['overlap_weight'],config['diverse_selection'],config['edge_coverage_weight'])
        provenance = {**self.provenance,'tracing_revision':self.revision,'config_hash':stable_hash(config)}
        for rank,path in enumerate(paths,1):
            path['rank'] = rank
            path['node_risks'] = [float(self.risks[a]) for a in path['nodes']]
            path['hop_count'] = len(path['nodes'])-1
            path['path_id'] = 'path_'+stable_hash([self.provenance,path['nodes']])[:24]
            path['evidence_id'] = 'trace_'+stable_hash([provenance,path['nodes']])[:24]
            path['bridge_nodes'] = [a for w in path['bridge_witnesses'] for a in w['bridge_nodes']]
            path['reason_codes'] = ['RISK_GUIDED_PATH']+(['BRIDGE_WITNESS_FOUND'] if path['bridge_nodes'] else [])
            path['source_references'] = {'risk_field':'overall_risk_score',
                'risk_revision':self.provenance.get('risk_revision'),'graph':'original_directed_address_relations'}
            path['amount_evidence'] = 'unavailable'
            path['transaction_time_evidence'] = 'unavailable'
        view_nodes = {seed} | {a for p in paths for a in p['nodes']}
        view_edges = {}
        for path in paths:
            for src,dst in zip(path['nodes'],path['nodes'][1:]):
                edge = view_edges.setdefault((src,dst),{'src':src,'dst':dst,'path_rank':path['rank'],'path_ids':[]})
                edge['path_ids'].append(path['path_id'])
        depth = max((len(p['nodes'])-1 for p in completed.values()),default=0)
        stop = ('BUDGET_EXHAUSTED' if budget.total >= budget.limit else
                'MAX_DEPTH_REACHED' if depth >= config['max_depth'] else 'NO_ELIGIBLE_EXPANSIONS')
        reasons[stop] += 1
        selection = {**coverage_statistics(paths,self.risks,seed), 'prefix_folding':folded,
                     'candidate_paths':len(completed),'displayed_paths':len(paths)}
        return {'seed_address':seed,'config':config,'method':'budgeted_relation_tracer_v1',
            'provenance':provenance,'search_budget':{'configured_limit':budget.limit,
                'actual_edge_inspections':budget.total,'stage_edge_inspections':dict(budget.counts),
                'elapsed_ms':(time.perf_counter()-started)*1000,'stop_reason':stop,
                'adjacency_order':'stored_node_index_order_before_risk_sort',
                'neighbor_context':'precomputed' if self.graph_statistics else 'unavailable_zero_context'},
            'statistics':{'visited_nodes':len(retained),'candidate_nodes':len(considered-{seed}),
                'high_risk_nodes':sum(self.risks[a] >= config['high_risk_threshold'] for a in retained-{seed}),
                'pruned_nodes':len(considered-retained),'pruned_expansions':sum(reasons[code] for code in (
                    'CYCLE_BLOCKED','BEAM_PRUNED','NEIGHBOR_LIMIT','FRONTIER_LIMIT','BRIDGE_WITHOUT_WITNESS')),
                'max_reached_depth':depth}, 'top_paths':paths,
            'subgraph':{'nodes':[{'address_id':a,'risk_score':float(self.risks[a]),'is_seed':a==seed}
                                  for a in sorted(view_nodes)],'edges':list(view_edges.values())},
            'selection_analysis':selection,'seed_relevance':relevance,
            'anchor_reachability':{'enabled':config['anchor_index_enabled'],
                'metadata':self.anchor_index.metadata if config['anchor_index_enabled'] else None},
            'reason_summary':dict(reasons),'search_events':events,'events_truncated':event_count>len(events)}

    def save(self,result,root:Path=ROOT):
        save_json(root/'artifacts/traces'/f"{artifact_key(result['seed_address'])}.json",result)
