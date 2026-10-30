"""Group provenance, exact peeling equivalence and bounded tracing invariants."""
from collections import defaultdict
import copy
import math
import random

import pytest

from api.datasets.base import DatasetService, load_dense_groups
from src.tracing.dense_group_index import DenseGroupIndex
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.tracing.graph_loader import DirectedGraph
from src.utils.io import load_config, save_json, file_sha256


def graph_for(edges, risks):
    mapping = {a:i for i,a in enumerate(sorted(risks))}
    outgoing, incoming = defaultdict(list), defaultdict(list)
    for src,dst in edges:
        outgoing[mapping[src]].append(mapping[dst])
        incoming[mapping[dst]].append(mapping[src])
    return DirectedGraph(dict(outgoing),dict(incoming),mapping,{str(i):a for a,i in mapping.items()})


def fixture():
    risks = dict(S=20,B=35,A=90,C=85,X=55,Z=95)
    edges = [('S','B'),('S','X'),('B','A'),('B','C'),('A','B'),('A','C'),
             ('C','A'),('C','B'),('X','Z')]
    cfg = copy.deepcopy(load_config('tracing.yaml'))
    cfg['dense_group_build'].update(anchor_threshold=60,max_anchors=10,radius=1,
        max_nodes_per_anchor=20,min_group_nodes=3,min_group_edges=4)
    provenance = dict(dataset_id='bitcoin',dataset_fingerprint='fixture',risk_revision='frozen',
                      graph_revision='real',trace_scope='bitcoin_scored_addresses_only',calibration_revision='identity')
    graph = graph_for(edges,risks)
    index = DenseGroupIndex.build(graph,risks,cfg['dense_group_build'],provenance)
    return graph,risks,cfg,provenance,index


def slow_original_block(graph,nodes):
    """Reference of the inspected package's deterministic two-sided peeling."""
    edges = {(s,t) for s in nodes for t in graph.iter_out_neighbors(s) if t in nodes and s!=t}
    count = sum(1 for s in nodes for _ in graph.iter_out_neighbors(s))
    if not edges:
        return None,count
    sources,targets = {s for s,t in edges},{t for s,t in edges}
    best,best_key = None,None
    while sources and targets and edges:
        members=sorted(sources|targets)
        density=len(edges)/(len(sources)*len(targets))
        objective=len(edges)/math.sqrt(len(sources)*len(targets))
        key=(objective,density,len(edges),-len(members),tuple(members))
        if best_key is None or key>best_key:
            best_key=key
            best=dict(members=members,sources=sorted(sources),targets=sorted(targets),
                      edges=[list(e) for e in sorted(edges)],density=density,objective=objective)
        choices=[]
        for side,addresses,other in [(0,sources,targets),(1,targets,sources)]:
            for a in addresses:
                d=sum(s==a if side==0 else t==a for s,t in edges)
                choices.append((d/len(other),d,side,a))
        _,_,side,a=min(choices)
        if side==0:
            sources.remove(a);edges={e for e in edges if e[0]!=a}
        else:
            targets.remove(a);edges={e for e in edges if e[1]!=a}
    return best,count


def test_heap_peeling_matches_package_reference_on_random_graphs():
    rng=random.Random(20261030)
    for size in range(2,23):
        risks={f'N{i:02d}':50 for i in range(size)}
        for _ in range(8):
            edges=[(a,b) for a in risks for b in risks if a!=b and rng.random()<.26]
            g=graph_for(edges,risks)
            assert DenseGroupIndex._densest_block(g,set(risks)) == slow_original_block(g,set(risks))


def test_index_revision_determinism_roundtrip_and_frozen_risks(tmp_path):
    graph,risks,cfg,prov,index=fixture()
    original=dict(risks)
    again=DenseGroupIndex.build(graph,risks,cfg['dense_group_build'],prov)
    assert index.metadata['revision']==again.metadata['revision']
    index.validate_contents(risks)
    index.save(tmp_path)
    loaded=DenseGroupIndex.load(graph,tmp_path,prov,risks)
    assert loaded.groups==index.groups and risks==original
    assert any(set(g['member_addresses'])=={'A','B','C'} for g in index.groups.values())
    with pytest.raises(ValueError,match='risk_revision'):
        DenseGroupIndex.load(graph,tmp_path,{**prov,'risk_revision':'different'},risks)


def test_membership_and_original_edge_tampering_are_rejected():
    graph,risks,cfg,prov,index=fixture()
    index.memberships['S']=('nonexistent',)
    with pytest.raises(ValueError,match='membership'):
        index.validate_contents(risks)
    graph,risks,cfg,prov,index=fixture()
    group=next(iter(index.groups.values()))
    source,target=group['internal_edges'][0]
    graph.outgoing[graph.address_to_idx[source]].remove(graph.address_to_idx[target])
    with pytest.raises(ValueError,match='original graph'):
        index.validate_contents(risks)


def test_guidance_changes_priority_without_rewriting_risk_or_bypassing_budget():
    graph,risks,cfg,prov,index=fixture()
    cfg.update(anchor_index_enabled=False,bridge_enabled=False,max_neighbors_per_node=1,
               max_depth=2,top_paths=3,dense_group_weight=.9,dense_group_entry_weight=.7)
    before=dict(risks)
    base=BudgetedRelationTracer(graph,risks,{**cfg,'dense_group_enabled':False},provenance=prov)
    guided=BudgetedRelationTracer(graph,risks,cfg,provenance=prov,group_index=index)
    b,g=base.trace('S'),guided.trace('S')
    assert b['top_paths'][0]['nodes']==['S','X','Z']
    assert any('B' in p['nodes'] for p in g['top_paths'])
    assert risks==before
    assert g['provenance']['dense_group_revision']==index.metadata['revision']
    assert g['search_budget']['actual_edge_inspections']<=cfg['edge_budget']
    for path in g['top_paths']:
        assert len(path['nodes'])==len(set(path['nodes']))
        assert path['node_risks']==[risks[a] for a in path['nodes']]
        assert all(t in graph.iter_out_neighbors(s) for s,t in zip(path['nodes'],path['nodes'][1:]))


def test_missing_and_corrupt_optional_index_fall_back(tmp_path):
    graph,risks,cfg,prov,index=fixture()
    assert load_dense_groups(tmp_path,graph,risks,prov,cfg)[1]=='missing'
    path=tmp_path/'dense_groups'/index.metadata['revision'];index.save(path)
    save_json(path.parent/'active.json',{'revision':index.metadata['revision']})
    assert load_dense_groups(tmp_path,graph,risks,prov,cfg)[1]=='ready'
    save_json(path/'groups.json',{})
    assert load_dense_groups(tmp_path,graph,risks,prov,cfg)[1]=='invalid'
    bad=copy.deepcopy(cfg);bad['dense_group_enabled']=False
    assert load_dense_groups(tmp_path,graph,risks,prov,bad)[1]=='disabled'


def service_fixture():
    graph,risks,cfg,prov,index=fixture()
    cfg['anchor_index_enabled']=False
    tracer=BudgetedRelationTracer(graph,risks,cfg,provenance=prov,group_index=index)
    trace=tracer.trace('A');trace['dataset_id']='bitcoin'
    service=DatasetService.__new__(DatasetService)
    service.dataset_id='bitcoin';service.graph=graph;service.risks=risks
    service.group_index=index;service.group_status='ready';service.dense_group_revision=index.metadata['revision']
    service.versions={**prov,'dense_group_revision':index.metadata['revision']}
    service.metadata={'graph_revision':'real'}
    return service,trace


def test_group_query_is_context_bound_and_pagination_is_complete():
    service,trace=service_fixture()
    result=service.related_groups(trace)
    assert result['groups'] and result['revision']==service.dense_group_revision
    group_id=result['groups'][0]['group_id'];nodes=[];edges=[];offset=0
    while True:
        page=service.group_detail(trace,group_id,offset=offset,limit=2)
        nodes.extend(page['nodes']);edges.extend(page['edges'])
        if page['complete']:
            assert not page['has_more'] and page['next_offset'] is None
            break
        offset=page['next_offset']
    group=service.group_index.groups[group_id]
    assert len(nodes)==group['member_count'] and len(edges)==group['edge_count']
    assert all(n['is_scored'] and n['risk_score']==service.risks[n['address_id']] for n in nodes)
    with pytest.raises(KeyError):service.related_groups(trace,'not_a_path')
    with pytest.raises(KeyError):service.group_detail(trace,'not_a_group')
    stale=copy.deepcopy(trace);stale['provenance']['dense_group_revision']='old'
    with pytest.raises(ValueError,match='version'):service.related_groups(stale)
    wrong=copy.deepcopy(trace);wrong['dataset_id']='ethereum'
    with pytest.raises(ValueError,match='dataset'):service.related_groups(wrong)


def test_group_query_does_not_modify_saved_trace():
    service,trace=service_fixture();before=copy.deepcopy(trace)
    for path in trace['top_paths']:
        groups=service.related_groups(trace,path['path_id'])['groups']
        for group in groups:service.group_detail(trace,group['group_id'],path_id=path['path_id'])
    assert trace==before
