import copy
import json
import pytest
from src.tracing.graph_loader import DirectedGraph
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.tracing.search_budget import SearchBudget
from src.tracing.local_relevance import local_push
from src.tracing.anchor_index import RiskAnchorIndex
from src.utils.io import load_config
from src.report.evidence_builder import build_evidence
from src.report.template_reporter import TemplateReporter


def make_graph(edges, risks, metadata=None):
    mapping = {a:i for i,a in enumerate(sorted(risks))}
    outgoing, incoming = {}, {}
    for src,dst in edges:
        outgoing.setdefault(mapping[src],[]).append(mapping[dst])
        incoming.setdefault(mapping[dst],[]).append(mapping[src])
    return DirectedGraph(outgoing,incoming,mapping,{str(i):a for a,i in mapping.items()},metadata)


def make_tracer(edges, risks, method='full', **overrides):
    config = load_config('tracing_experiments.yaml')
    settings = {**config['common'],**config['methods'][method],**overrides}
    return BudgetedRelationTracer(make_graph(edges,risks),risks,settings)


def test_bridge_requires_a_real_directional_witness_and_keeps_risk():
    risks = dict(A=95,B=10,C=95,D=5,E=99)
    edges = [('A','B'),('B','C'),('A','D'),('E','D'),('C','A')]
    trace = make_tracer(edges,risks).trace('A')
    assert any(p['nodes'] == ['A','B','C'] for p in trace['top_paths'])
    assert not any('D' in p['nodes'] for p in trace['top_paths'])
    path = next(p for p in trace['top_paths'] if p['nodes'] == ['A','B','C'])
    assert path['node_risks'] == [95,10,95]
    assert path['bridge_witnesses'][0]['edges'] == [['A','B'],['B','C']]
    assert risks['B'] == 10
    assert path['amount_evidence'] == 'unavailable'
    assert trace['search_budget']['actual_edge_inspections'] <= 2000
    assert not make_tracer(edges,risks,method='budget_beam').trace('A')['top_paths']


def test_bridge_cannot_exceed_depth_or_span_two_low_nodes():
    risks = dict(A=95,B=10,C=5,D=99)
    edges = [('A','B'),('B','C'),('C','D')]
    assert not make_tracer(edges,risks).trace('A')['top_paths']
    tracer = make_tracer([('A','B'),('B','D')],risks)
    assert not tracer.trace('A',{'max_depth':1})['top_paths']
    assert all(p['hop_count'] <= 2 for p in tracer.trace('A',{'max_depth':2})['top_paths'])


def test_same_budget_counts_ppr_lookahead_and_search_and_caps_hubs():
    risks = {'A':95,**{f'N{i:04d}':10 for i in range(1000)},'Z':99}
    edges = [('A',a) for a in risks if a not in ('A','Z')]+[('N0000','Z')]
    result = make_tracer(edges,risks,edge_budget=17).trace('A')
    budget = result['search_budget']
    assert budget['actual_edge_inspections'] == 17
    assert sum(budget['stage_edge_inspections'].values()) == 17
    assert budget['stop_reason'] == 'BUDGET_EXHAUSTED'
    assert budget['stage_edge_inspections']['ppr'] == 2
    assert not result['top_paths']


def test_local_push_preserves_probability_mass_when_budget_stops_mid_push():
    risks = dict(A=95,B=10,C=99)
    graph = make_graph([('A','B'),('A','C'),('C','A')],risks)
    scores, stats = local_push(graph,'A',SearchBudget(1),1,.2,.0001,100)
    assert stats['settled_mass']+stats['residual_mass'] == pytest.approx(1)
    assert stats['edge_inspections'] == 1
    assert not stats['converged']
    scores, stats = local_push(graph,'A',SearchBudget(10000),10000,.2,.00001,1000)
    assert stats['settled_mass']+stats['residual_mass'] == pytest.approx(1)
    assert scores['C'] >= scores['B']


def test_fold_prefixes_and_unique_subgraph_keep_multiple_real_branches():
    risks = dict(A=95,B=94,C=91,D=93,E=90)
    edges = [('A','B'),('B','C'),('B','D'),('D','E')]
    result = make_tracer(edges,risks).trace('A')
    assert result['selection_analysis']['strict_prefix_count'] == 0
    assert result['selection_analysis']['prefix_folding']
    assert {tuple(p['nodes']) for p in result['top_paths']} == {('A','B','C'),('A','B','D','E')}
    assert len(result['subgraph']['edges']) == 4
    assert all(len(p['nodes']) == len(set(p['nodes'])) for p in result['top_paths'])


def test_deterministic_paths_stable_ids_and_config_provenance():
    tracer = make_tracer([('A','B'),('B','C')],dict(A=95,B=10,C=99))
    first, second = tracer.trace('A'), tracer.trace('A')
    assert first['top_paths'] == second['top_paths']
    assert first['provenance'] == second['provenance']
    changed = tracer.trace('A',{'top_paths':1})
    assert changed['top_paths'][0]['path_id'] == first['top_paths'][0]['path_id']
    assert changed['top_paths'][0]['evidence_id'] != first['top_paths'][0]['evidence_id']
    json.dumps(first,allow_nan=False)


def test_invalid_scores_versions_and_search_config_are_rejected():
    with pytest.raises(ValueError,match='finite'):
        make_tracer([],dict(A=float('nan')))
    graph = make_graph([],dict(A=99),metadata={'fingerprint':'graph-v1'})
    config = load_config('tracing_experiments.yaml')['common']
    with pytest.raises(ValueError,match='fingerprints'):
        BudgetedRelationTracer(graph,dict(A=99),config,provenance={'dataset_fingerprint':'graph-v2'})
    tracer = make_tracer([],dict(A=99))
    for overrides in ({'edge_budget':0},{'risk_threshold':float('nan')},{'cycle_check':False}):
        with pytest.raises(ValueError): tracer.trace('A',overrides)
    with pytest.raises(KeyError): tracer.trace('missing')


def test_module_three_preserves_version_and_bridge_evidence():
    tracer = make_tracer([('A','B'),('B','C')],dict(A=95,B=10,C=99))
    result = tracer.trace('A')
    analysis = {'address_id':'A','risk':{'overall_score':95,'risk_level':'CRITICAL'}}
    evidence = build_evidence(analysis,trace_result=result)
    assert evidence['trace_analysis']['top_paths'][0]['bridge_nodes'] == ['B']
    assert evidence['trace_analysis']['provenance'] == result['provenance']
    assert '低分中间连接' in TemplateReporter().generate(evidence)['markdown']


def test_module_three_rejects_other_seed_and_scoring_revision():
    trace = make_tracer([('A','B')],dict(A=95,B=99)).trace('A')
    with pytest.raises(ValueError,match='Seed'):
        build_evidence({'address_id':'B'},trace_result=trace)
    trace['provenance']['risk_revision'] = 'old'
    with pytest.raises(ValueError,match='revision'):
        build_evidence({'address_id':'A'},trace_result=trace,metadata={'risk_revision':'new'})


def test_multistep_bridge_has_complete_witness_and_exact_depth_limit():
    risks = dict(A=95,B=10,C=5,D=99,E=1)
    tracer = make_tracer([('A','B'),('B','C'),('C','D'),('A','E')],risks,max_bridge_nodes=2)
    result = tracer.trace('A',{'max_depth':3})
    path = next(p for p in result['top_paths'] if p['nodes'] == ['A','B','C','D'])
    assert path['bridge_nodes'] == ['B','C']
    assert path['bridge_witnesses'][0]['edges'] == [['A','B'],['B','C'],['C','D']]
    assert not tracer.trace('A',{'max_depth':2})['top_paths']


def test_anchor_distances_match_independent_shortest_paths_and_are_directed(tmp_path):
    import networkx as nx
    risks = dict(A=90,B=10,C=5,D=95,E=1,F=1,G=1)
    edges = [('A','B'),('B','C'),('C','D'),('E','A'),('F','E'),('G','F')]
    graph = make_graph(edges,risks)
    index = RiskAnchorIndex.build(graph,risks,30,3,{'risk_revision':'r1'})
    nxgraph = nx.DiGraph(edges)
    for address,idx in graph.address_to_idx.items():
        distances = [nx.shortest_path_length(nxgraph,address,anchor) for anchor in ('A','D')
                     if nx.has_path(nxgraph,address,anchor)]
        expected = min(distances) if distances else -1
        if expected > 3: expected = -1
        assert index.distance[idx] == expected
    index.save(tmp_path)
    loaded = RiskAnchorIndex.load(graph,tmp_path,{'risk_revision':'r1'},30,3)
    budget = SearchBudget(2)
    assert loaded.connection('B',{'A'},3,3,budget) == (['B','C'],'D')
    assert budget.total == 2
    with pytest.raises(ValueError,match='mismatch'):
        RiskAnchorIndex.load(graph,tmp_path,{'risk_revision':'r2'},30,3)
    with (tmp_path/'next_node.npy').open('ab') as stream: stream.write(b'corrupt')
    with pytest.raises(ValueError,match='hash'):
        RiskAnchorIndex.load(graph,tmp_path,{'risk_revision':'r1'},30,3)


def test_index_does_not_create_a_reverse_edge_or_return_a_cycle():
    risks = dict(A=95,B=10,C=99,E=1)
    graph = make_graph([('A','B'),('B','A'),('B','C'),('C','E')],risks)
    config = load_config('tracing_experiments.yaml')
    settings = {**config['common'],**config['methods']['indexed_bridge3']}
    index = RiskAnchorIndex.build(graph,risks,30,4,{})
    # If canonical witness leads back to Seed A, the online bounded fallback
    # must either find C or safely abstain; never include a loop as evidence.
    tracer = BudgetedRelationTracer(graph,risks,settings,anchor_index=index)
    result = tracer.trace('A')
    assert any(p['nodes'] == ['A','B','C'] for p in result['top_paths'])
    assert all(len(p['nodes']) == len(set(p['nodes'])) for p in result['top_paths'])
    assert not tracer.trace('E')['top_paths']


def test_path_selection_is_reproducible_across_python_hash_seeds():
    import subprocess,os,sys
    code = '''import json
from src.tracing.path_selection import select_paths,coverage_statistics
risks = dict(S=95,A=93,B=81,C=75,D=63,E=49)
paths = [dict(nodes=['S','A','B','C'],path_score=.4),dict(nodes=['S','A','D','E'],path_score=.4)]
result = select_paths(paths,2,risks,'S',.3,.15)
print(json.dumps([result,coverage_statistics(result,risks,'S')],sort_keys=True))
'''
    outputs = [subprocess.run([sys.executable,'-c',code],env={**os.environ,'PYTHONHASHSEED':seed},
        check=True,text=True,capture_output=True).stdout for seed in ('1','99')]
    assert outputs[0] == outputs[1]
