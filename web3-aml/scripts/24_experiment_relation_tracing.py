"""Reproducible mechanism study and stratified real-graph proxy evaluation.

Does not tune module-one scores or use labels in the search. Manifest/configs
are saved before any run. --split development permits reviewing components
before the separately sampled evaluation; evaluation is a repeat public-data
benchmark, not externally blinded money-flow ground truth.
"""
import _bootstrap
import argparse
from pathlib import Path
import time
import platform
import re
import numpy as np
import pandas as pd
from src.tracing.graph_loader import DirectedGraph
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.path_selection import coverage_statistics
from src.utils.io import ROOT, read_json, load_config, save_json, file_sha256


def re_fullmatch_name(name):
    return bool(re.fullmatch(r'[a-z0-9_]+',name))


def mechanism_graph(kind, trial, rng):
    risks = {'S':90.0}
    edges, targets = [], []
    def add(src,dst,risk):
        risks[dst] = float(risk)
        edges.append((src,dst))
    if kind == 'low_bridge':
        for i in range(3):
            add('S',f'B{i}',rng.uniform(4,24))
            add(f'B{i}',f'T{i}',rng.uniform(70,99))
            targets.append(f'T{i}')
        for i in range(trial % 9 + 3):
            add('S',f'N{i}',rng.uniform(0,8))
    elif kind == 'parallel':
        add('S','J',rng.uniform(60,85))
        for i in range(8):
            add('J',f'B{i}',rng.uniform(45,95))
            add(f'B{i}',f'T{i}',rng.uniform(45,95))
            targets.append(f'T{i}')
        # Planted target status is not derived from model scores.
    elif kind == 'hub_noise':
        add('S','H',rng.uniform(75,99))
        for i in range(40+trial*2):
            add('H',f'N{i}',rng.uniform(0,85))
            if i % 4 == 0:
                add(f'N{i}',f'D{i}',rng.uniform(0,85))
        add('S','B',rng.uniform(3,22))
        add('B','T',rng.uniform(65,99))
        targets.append('T')
    elif kind == 'cycle_deadend':
        add('S','A',rng.uniform(50,95))
        add('A','C',rng.uniform(50,95))
        edges.append(('C','S'))
        add('S','L',rng.uniform(3,22))
        add('L','T',rng.uniform(65,99))
        add('S','D',rng.uniform(3,22))
        targets.append('T')
    mapping = {a:i for i,a in enumerate(sorted(risks))}
    outgoing, incoming = {}, {}
    for src,dst in edges:
        outgoing.setdefault(mapping[src],[]).append(mapping[dst])
        incoming.setdefault(mapping[dst],[]).append(mapping[src])
    graph = DirectedGraph(outgoing,incoming,mapping,{str(i):a for a,i in mapping.items()})
    stats = {a:{'one_hop_avg_risk':np.mean([risks[n] for n in graph.neighbors(a)])
                if graph.neighbors(a) else 0} for a in risks}
    return graph,risks,stats,targets


def metrics(result, risks, seed, graph, labels=None):
    paths = result['top_paths']
    nodes = {a for p in paths for a in p['nodes']}-{seed}
    for path in paths:
        assert len(path['nodes']) == len(set(path['nodes']))
        assert path['hop_count'] <= result['config']['max_depth']
        for a,b in zip(path['nodes'],path['nodes'][1:]):
            assert graph.address_to_idx[b] in graph.outgoing.get(graph.address_to_idx[a],[])
    budget = result['search_budget']
    assert budget['actual_edge_inspections'] <= budget['configured_limit']
    assert sum(budget['stage_edge_inspections'].values()) == budget['actual_edge_inspections']
    row = {**coverage_statistics(paths,risks,seed),'path_count':len(paths),
        'has_path':bool(paths),'edge_inspections':budget['actual_edge_inspections'],
        'elapsed_ms':budget['elapsed_ms'],'max_depth':result['statistics']['max_reached_depth'],
        'bridge_count':len({a for p in paths for a in p['bridge_nodes']}),
        'risk_anchor_nodes':sum(risks[a] >= 30 for a in nodes),
        'anchored_path_count':sum(risks[p['nodes'][-1]] >= 30 for p in paths),
        'predicted_high_risk_nodes':sum(risks[a] >= 60 for a in nodes)}
    if labels is not None:
        row.update(known_illicit_hits=int(sum(labels[graph.address_to_idx[a]] == 1 for a in nodes)),
            known_licit_hits=int(sum(labels[graph.address_to_idx[a]] == 0 for a in nodes)),
            unknown_hits=int(sum(labels[graph.address_to_idx[a]] == -1 for a in nodes)))
    return row


def summarize(rows, group_keys):
    frame = pd.DataFrame(rows)
    records = []
    for keys, group in frame.groupby(group_keys,sort=True):
        if not isinstance(keys,tuple): keys = (keys,)
        record = dict(zip(group_keys,keys))
        record['seed_count'] = len(group)
        for field in ['path_count','has_path','unique_nodes_excluding_seed','unique_edges',
            'duplicate_edge_fraction','mean_pairwise_edge_jaccard','strict_prefix_count',
            'risk_weighted_node_coverage','edge_inspections','bridge_count','predicted_high_risk_nodes',
            'known_illicit_hits','known_licit_hits','unknown_hits','target_recall','non_target_nodes','risk_anchor_nodes','anchored_path_count']:
            if field in group: record['mean_'+field] = float(group[field].mean())
        for quantile in [.5,.95]:
            record[f'latency_p{int(quantile*100)}_ms'] = float(group.elapsed_ms.quantile(quantile))
        records.append(record)
    return records


def sample_seeds(graph, table, labels, masks, config):
    indices = table.node_idx.to_numpy(dtype=np.int64)
    risks = table.overall_risk_score.to_numpy()
    degree = np.zeros(len(labels),dtype=np.int64)
    for idx,neighbors in graph.outgoing.items(): degree[idx] = len(neighbors)
    eligible = degree[indices] > 0
    groups = []
    rng = np.random.default_rng(config['seed'])
    for split in ('development','evaluation'):
        n = config[f'{split}_seeds_per_risk_band']
        known_mask = masks[split][indices] & (labels[indices] >= 0)
        unknown_mask = (labels[indices] == -1) & ((indices % 2) == (0 if split == 'development' else 1))
        for low,high in [(0,30),(30,60),(60,101)]:
            band = eligible & (risks >= low) & (risks < high)
            for category,mask in [('known',known_mask),('unknown',unknown_mask)]:
                pool = np.flatnonzero(band & mask)
                selected = rng.choice(pool,size=min(n//2,len(pool)),replace=False)
                for row in selected:
                    groups.append({'split':split,'category':category,'risk_band':f'{low}-{min(high,100)}',
                        'address_id':str(table.iloc[row].address_id),'node_idx':int(indices[row])})
    assert len({s['address_id'] for s in groups}) == len(groups)
    return groups


def run_mechanisms(config,folder):
    rng = np.random.default_rng(config['seed'])
    rows = []
    for kind in ('low_bridge','parallel','hub_noise','cycle_deadend'):
        for trial in range(12):
            graph,risks,stats,targets = mechanism_graph(kind,trial,rng)
            anchor_index = RiskAnchorIndex.build(graph,risks,config['common']['risk_threshold'],config['common']['max_depth'],{})
            tracer = BudgetedRelationTracer(graph,risks,config['common'],stats,anchor_index=anchor_index)
            for method,settings in config['methods'].items():
                result = tracer.trace('S',settings)
                row = metrics(result,risks,'S',graph)
                nodes = {a for p in result['top_paths'] for a in p['nodes']}-{'S'}
                row.update(kind=kind,trial=trial,method=method,
                    target_recall=len(nodes & set(targets))/len(targets),
                    non_target_nodes=len(nodes-set(targets)))
                rows.append(row)
    save_json(folder/'mechanism_results.json',{'scope':'synthetic planted relation mechanisms, not AML truth',
        'summary':summarize(rows,['kind','method']),'rows':rows})
    pd.DataFrame(rows).to_csv(folder/'mechanism_rows.csv',index=False)
    print('Mechanism cases:',48,'methods:',len(config['methods']),flush=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--split',choices=['development','evaluation','all'],default='development')
    parser.add_argument('--mechanisms-only',action='store_true')
    parser.add_argument('--experiment',default='tracing_v2_anchors')
    args = parser.parse_args()
    config = load_config('tracing_experiments.yaml')
    if not re_fullmatch_name(args.experiment):
        raise ValueError('Experiment name must contain only lowercase letters, digits and underscores')
    folder = ROOT/'artifacts/experiments'/args.experiment
    folder.mkdir(parents=True,exist_ok=True)
    save_json(folder/'protocol.json',{'config':config,'config_sha256':file_sha256(ROOT/'config/tracing_experiments.yaml'),
        'script_sha256':file_sha256(Path(__file__)),'created_before_runs':True,
        'hardware':platform.platform(),'metrics':'real graph coverage proxies; labels offline only; no path ground truth',
        'budget_definition':'each adjacency edge read incl repeated PPR/bridge/search; cached context shared; selection time included'})
    run_mechanisms(config,folder)
    if args.mechanisms_only: return
    started = time.perf_counter()
    graph = DirectedGraph.load()
    metadata = read_json(ROOT/'artifacts/risk_scores/metadata.json')
    table = pd.read_parquet(ROOT/'artifacts/risk_scores/risk_scores.parquet',
                           columns=['address_id','node_idx','overall_risk_score'])
    risks = table.set_index('address_id').overall_risk_score.to_dict()
    cachemeta = read_json(ROOT/'artifacts/risk_scores/graph_statistics_metadata.json')
    assert cachemeta['risk_revision'] == metadata['risk_revision']
    assert cachemeta['dataset_fingerprint'] == metadata['dataset_fingerprint']
    stats = pd.read_parquet(ROOT/'artifacts/risk_scores/graph_statistics.parquet',
        columns=['address_id','one_hop_avg_risk']).set_index('address_id').to_dict(orient='index')
    labels = np.load(ROOT/'data/processed/labels.npy')
    masks = {'development':np.load(ROOT/'data/processed/val_mask.npy'),
             'evaluation':np.load(ROOT/'data/processed/test_mask.npy')}
    seeds = sample_seeds(graph,table,labels,masks,config)
    manifest = {'seeds':seeds,'risk_revision':metadata['risk_revision'],
        'dataset_fingerprint':metadata['dataset_fingerprint'],
        'sampling':'outgoing>0, stratified by risk band and known/unknown; known val/test; unknown even/odd node index',
        'demo_cases_used_for_tuning':False}
    manifest_path = folder/'seed_manifest.json'
    if manifest_path.exists() and read_json(manifest_path) != manifest:
        raise RuntimeError('Seed protocol changed: create a new experiment directory')
    save_json(manifest_path,manifest)
    provenance = {k:metadata[k] for k in ('risk_revision','dataset_fingerprint')}
    anchor_index = RiskAnchorIndex.build(graph,risks,config['common']['risk_threshold'],config['common']['max_depth'],provenance)
    anchor_index.save(folder/'anchor_index')
    tracer = BudgetedRelationTracer(graph,risks,config['common'],stats,provenance,anchor_index)
    load_seconds = time.perf_counter()-started
    splits = ['development','evaluation'] if args.split == 'all' else [args.split]
    for split in splits:
        rows,traces = [],[]
        selected = [s for s in seeds if s['split'] == split]
        rng = np.random.default_rng(config['seed']+ (split=='evaluation'))
        for index,seed in enumerate(selected):
            methods = list(config['methods'])
            rng.shuffle(methods)
            for method in methods:
                result = tracer.trace(seed['address_id'],config['methods'][method])
                row = {**seed,'method':method,**metrics(result,risks,seed['address_id'],graph,labels)}
                rows.append(row)
                traces.append({'seed':seed,'method':method,'result':result})
            if (index+1) % 12 == 0: print(split,'seeds:',index+1,'/',len(selected),flush=True)
        output = {'risk_revision':metadata['risk_revision'],'tracing_revision':tracer.revision,
            'load_seconds':load_seconds,'scope':'stratified outgoing-address sample; not representative whole-graph mean',
            'anchor_index_construction':anchor_index.metadata,
            'summary':summarize(rows,['method']),
            'stratified_summary':summarize(rows,['risk_band','category','method']),'rows':rows}
        save_json(folder/f'{split}_results.json',output)
        save_json(folder/f'{split}_traces.json',traces)
        pd.DataFrame(rows).to_csv(folder/f'{split}_rows.csv',index=False)
        print(pd.DataFrame(output['summary'])[['method','mean_unique_edges','mean_risk_weighted_node_coverage',
            'mean_known_illicit_hits','mean_edge_inspections','latency_p95_ms']].to_string(index=False),flush=True)


if __name__ == '__main__':
    main()
