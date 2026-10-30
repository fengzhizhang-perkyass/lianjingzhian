"""Real graph search must keep unscored bridges without inventing risk values."""
import json
import pytest
from api.datasets.base import DatasetService
from src.tracing.graph_loader import DirectedGraph
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.tracing.anchor_index import RiskAnchorIndex
from src.utils.io import load_config


def graph(edges):
    names = sorted({a for edge in edges for a in edge})
    mapping = {a: i for i, a in enumerate(names)}
    outgoing, incoming = {}, {}
    for a, b in edges:
        outgoing.setdefault(mapping[a], []).append(mapping[b])
        incoming.setdefault(mapping[b], []).append(mapping[a])
    return DirectedGraph(outgoing, incoming, mapping, {i:a for a,i in mapping.items()})


def tracer(edges, risks, **extra):
    g = graph(edges)
    settings = {**load_config('tracing.yaml'), 'allow_unscored_nodes': True,
                'show_observed_context': True, **extra}
    index = RiskAnchorIndex.build(g, risks, settings['risk_threshold'], 64, {})
    return BudgetedRelationTracer(g, risks, settings, anchor_index=index)


def test_unscored_chain_is_a_real_bridge_and_not_a_zero_prediction():
    result = tracer([('S','U'),('U','V'),('V','T')], {'S':91.,'T':95.}).trace('S')
    path = next(p for p in result['top_paths'] if p['nodes'] == ['S','U','V','T'])
    assert path['node_risks'] == [91., None, None, 95.]
    assert path['bridge_nodes'] == ['U','V']
    assert path['bridge_witnesses'][0]['edges'] == [['S','U'],['U','V'],['V','T']]
    nodes = {n['address_id']:n for n in result['subgraph']['nodes']}
    assert nodes['U']['risk_score'] is None and not nodes['U']['is_scored']
    assert result['selection_analysis']['risk_weighted_node_coverage'] == pytest.approx(.95)
    json.dumps(result, allow_nan=False)


def test_zero_threshold_does_not_turn_missing_risk_into_anchor():
    result = tracer([('S','U')], {'S':0.}, risk_threshold=0).trace('S')
    assert result['top_paths'] == []
    assert {n['address_id'] for n in result['subgraph']['nodes']} == {'S','U'}
    edge = result['subgraph']['edges'][0]
    assert edge['src']=='S' and edge['dst']=='U' and edge['context_only']
    assert result['search_budget']['actual_edge_inspections'] <= 2000


def test_coverage_stats_count_only_observed_scored_neighbors():
    service = DatasetService.__new__(DatasetService)
    service.graph = graph([('S','U'),('S','L'),('U','T')])
    service.risks = {'S':90.,'L':0.,'T':80.}
    first = service.graph_summary('S')
    assert first['one_hop_neighbor_count']==2
    assert first['one_hop_scored_count']==1 and first['one_hop_unscored_count']==1
    assert first['one_hop_avg_risk']==0.
    only_missing = service.graph_summary('T')
    assert only_missing['one_hop_avg_risk'] is None
    assert only_missing['one_hop_high_risk_ratio'] is None


def test_partial_coverage_requires_explicit_opt_in_and_never_accepts_foreign_risks():
    g = graph([('S','U')]); config = load_config('tracing.yaml')
    with pytest.raises(ValueError, match='same addresses'):
        BudgetedRelationTracer(g, {'S':91.}, config)
    with pytest.raises(ValueError, match='same addresses'):
        BudgetedRelationTracer(g, {'S':91.,'OTHER':90.}, {**config,'allow_unscored_nodes':True})
