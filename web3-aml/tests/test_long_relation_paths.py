"""Long-range witness completion, budget boundaries and report continuity."""
import pytest
from tests.test_budgeted_tracing import make_graph
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.report.evidence_builder import build_evidence
from src.report.template_reporter import TemplateReporter
from src.utils.io import load_config


def long_tracer():
    nodes = [f'N{i:02d}' for i in range(33)]
    risks = {a: 5.0 for a in nodes}
    risks[nodes[-1]] = 65.0
    edges = list(zip(nodes, nodes[1:])) + [(nodes[10], nodes[2])]
    graph = make_graph(edges, risks)
    config = load_config('tracing.yaml')
    index = RiskAnchorIndex.build(graph, risks, 30, 64, {})
    return BudgetedRelationTracer(graph, risks, config, anchor_index=index), nodes, risks


def test_long_chain_requires_complete_witness_and_preserves_all_scores():
    tracer, nodes, risks = long_tracer()
    assert not tracer.trace(nodes[0])['top_paths']
    result = tracer.trace(nodes[0], {'max_depth':32, 'max_bridge_nodes':31})
    assert len(result['top_paths']) == 1
    path = result['top_paths'][0]
    assert path['nodes'] == nodes
    assert path['hop_count'] == 32
    assert path['node_risks'] == [5.0]*32+[65.0]
    assert len(path['bridge_nodes']) == 31
    assert len(path['bridge_witnesses'][0]['edges']) == 32
    assert result['search_budget']['actual_edge_inspections'] == 32
    assert all(risks[a] == 5 for a in nodes[:-1])


@pytest.mark.parametrize('overrides', [
    {'max_depth':31,'max_bridge_nodes':31},
    {'max_depth':32,'max_bridge_nodes':30},
    {'max_depth':32,'max_bridge_nodes':31,'edge_budget':31}])
def test_partial_or_underbudget_connector_is_never_a_completed_path(overrides):
    tracer, nodes, _ = long_tracer()
    result = tracer.trace(nodes[0], overrides)
    assert not result['top_paths']
    assert result['search_budget']['actual_edge_inspections'] <= result['config']['edge_budget']


def test_long_chain_reaches_report_with_stable_evidence_reference():
    tracer, nodes, _ = long_tracer()
    result = tracer.trace(nodes[0], {'max_depth':32,'max_bridge_nodes':31})
    evidence = build_evidence({'address_id':nodes[0]}, trace_result=result)
    report = TemplateReporter().generate(evidence)['markdown']
    assert result['top_paths'][0]['evidence_id'] in report
    assert nodes[-1] in report
    assert evidence['trace_analysis']['top_paths'][0]['hop_count'] == 32
