"""Scored-only tracing is an actual induced graph, never visual contraction."""
from pathlib import Path
import hashlib
import json

import numpy as np
import pandas as pd
import pytest

from api.datasets.scored_graph import (
    TRACE_SCOPE, GRAPH_FILES, induced_scored_graph, graph_statistics,
    verify_scored_trace_graph,
)
from src.tracing.graph_loader import DirectedGraph
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.utils.io import load_config


ROOT = Path(__file__).resolve().parents[1]


def source_graph(edges, mapping=None):
    mapping = mapping or {a: i for i, a in enumerate(sorted({a for edge in edges for a in edge}))}
    outgoing, incoming = {}, {}
    for a, b in edges:
        outgoing.setdefault(mapping[a], []).append(mapping[b])
        incoming.setdefault(mapping[b], []).append(mapping[a])
    return DirectedGraph(outgoing, incoming, mapping, {v:k for k,v in mapping.items()})


def test_missing_middle_is_removed_without_a_synthetic_shortcut():
    source = source_graph([('S','U'), ('U','T')])
    table = pd.DataFrame({'address_id':['S','T'], 'node_idx':[source.address_to_idx[a] for a in ['S','T']]})
    graph, maps, count = induced_scored_graph(source, table)
    assert set(graph.address_to_idx) == {'S','T'}
    assert count == 0 and graph.out_neighbors('S') == []
    assert source.out_neighbors('S') == ['U']
    assert maps['score_row_by_address'] == {'S':0, 'T':1}


def test_low_scored_bridge_survives_and_source_feature_rows_are_explicit():
    source = source_graph([('S','U'), ('U','T'), ('S','L'), ('L','T')],
                          {'S':7, 'U':11, 'L':20, 'T':42})
    table = pd.DataFrame({'address_id':['T','S','L'], 'node_idx':[42,7,20]})
    graph, maps, count = induced_scored_graph(source, table)
    assert graph.address_to_idx == {'S':0,'L':1,'T':2}
    assert maps['score_row_by_address'] == {'T':0,'S':1,'L':2}
    assert maps['source_node_idx_by_address'] == {'T':42,'S':7,'L':20}
    assert count == 2 and graph.out_neighbors('S') == ['L']
    assert graph.out_neighbors('L') == ['T']
    risks = {'S':90., 'L':0., 'T':95.}
    settings = {**load_config('tracing.yaml'), 'allow_unscored_nodes':False,
                'show_observed_context':True}
    index = RiskAnchorIndex.build(graph, risks, 30, 64, {'trace_scope':TRACE_SCOPE})
    traced = BudgetedRelationTracer(graph, risks, settings, anchor_index=index,
                                    provenance={'trace_scope':TRACE_SCOPE}).trace('S')
    path = next(p for p in traced['top_paths'] if p['nodes'] == ['S','L','T'])
    assert path['node_risks'] == [90.,0.,95.]
    assert path['bridge_nodes'] == ['L']
    assert all(n['is_scored'] and n['risk_score'] is not None for n in traced['subgraph']['nodes'])
    assert traced['search_budget']['actual_edge_inspections'] <= settings['edge_budget']


def test_graph_statistics_are_for_induced_neighbors_not_original_coverage():
    source = source_graph([('S','U'), ('S','L'), ('L','T')])
    table = pd.DataFrame({'address_id':['S','L','T'],
                          'node_idx':[source.address_to_idx[a] for a in ['S','L','T']]})
    graph, _, _ = induced_scored_graph(source, table)
    stats = graph_statistics(graph, {'S':90.,'L':0.,'T':80.}).set_index('address_id')
    assert stats.loc['S','one_hop_neighbor_count'] == 1
    assert stats.loc['S','one_hop_avg_risk'] == 0.
    assert set(source.neighbors('S')) == {'U','L'}
    assert not any('unscored' in name for name in stats.columns)


def test_original_self_edges_and_isolated_scored_nodes_are_preserved():
    source = source_graph([('S','S')], {'S':1,'I':8})
    table = pd.DataFrame({'address_id':['I','S'],'node_idx':[8,1]})
    graph, _, count = induced_scored_graph(source, table)
    assert count == 1 and graph.out_neighbors('S') == ['S']
    assert graph.degrees('I') == (0,0)
    assert set(graph.address_to_idx) == {'S','I'}


@pytest.mark.parametrize('table', [
    pd.DataFrame({'address_id':['S'], 'node_idx':[999]}),
    pd.DataFrame({'address_id':['S','S'], 'node_idx':[0,1]}),
    pd.DataFrame({'address_id':['FOREIGN'], 'node_idx':[0]}),
])
def test_wrong_source_mapping_or_foreign_score_membership_is_rejected(table):
    with pytest.raises(ValueError):
        induced_scored_graph(source_graph([('S','T')]), table)


def _tiny_manifest(folder):
    folder.mkdir()
    names = [*GRAPH_FILES,'node_mappings.json','graph_statistics.parquet']
    assets = {}
    for name in names:
        (folder/name).write_bytes(('fixed:'+name).encode())
        p = folder/name
        assets[name] = {'bytes':p.stat().st_size,'sha256':hashlib.sha256(p.read_bytes()).hexdigest()}
    manifest = {'dataset_id':'ethereum','trace_scope':TRACE_SCOPE,'runtime_assets':assets,
                'source_graph_revision':'source_graph','source_risk_revision':'source_risk',
                'source_fingerprint':'source_fingerprint','calibration_revision':'calib',
                'graph_nodes':3}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    return manifest


def test_trace_assets_validate_scope_sources_and_tampering(tmp_path):
    folder = tmp_path/'trace_scored'
    manifest = _tiny_manifest(folder)
    source = {'graph_revision':'source_graph','risk_revision':'source_risk',
              'fingerprint':'source_fingerprint','scored_addresses':3}
    assert verify_scored_trace_graph(folder,source_manifest=source,calibration_revision='calib') == manifest
    with pytest.raises(ValueError,match='calibration'):
        verify_scored_trace_graph(folder,calibration_revision='changed')
    with pytest.raises(ValueError,match='source revision'):
        verify_scored_trace_graph(folder,source_manifest={**source,'graph_revision':'changed'})
    (folder/'outgoing_neighbors.pkl').write_bytes(b'changed')
    with pytest.raises(ValueError,match='hash mismatch'):
        verify_scored_trace_graph(folder)


@pytest.fixture(scope='module')
def ethereum_service():
    from api.datasets.ethereum import EthereumService
    return EthereumService(ROOT)


def test_real_graph_has_only_scored_nodes_and_all_edges_exist_in_original(ethereum_service):
    s = ethereum_service
    assert s.trace_scope == TRACE_SCOPE
    assert len(s.graph.address_to_idx) == len(s.risks) == 103171
    assert len(s.source_graph.address_to_idx) == 497340
    edge_count = 0
    for a in s.graph.address_to_idx:
        original = set(s.source_graph.out_neighbors(a))
        for b in s.graph.out_neighbors(a):
            edge_count += 1
            assert b in s.risks and b in original
    assert edge_count == s.metadata['graph_edges'] == 3228
    assert s.manifest['graph_edges'] == 746306
    assert s.metadata['source_graph_revision'] == s.manifest['graph_revision']
    assert s.metadata['graph_revision'] != s.manifest['graph_revision']


def test_real_model_context_and_identity_probability_are_unchanged(ethereum_service):
    s = ethereum_service
    frozen = pd.read_parquet(s.folder/'risk_scores.parquet')
    assert np.array_equal(s.predictor.table.overall_risk_score.to_numpy(), frozen.overall_risk_score.to_numpy())
    a = '0xd635cb5d0fc7688ab4cde7b71276b6f0cb40f2af'
    result = s.analyze(a)
    summary = result['scoring_analysis']['structure_summary']
    assert summary['observed_counterparty_count'] == len(s.source_graph.neighbors(a)) == 147
    assert summary['observed_counterparty_count'] > len(s.graph.neighbors(a))
    assert result['risk']['overall_score'] == float(frozen.set_index('address_id').loc[a,'overall_risk_score'])
    assert result['risk']['calibration']['mode'] == 'identity'
    assert result['risk']['raw_probability'] == result['risk']['calibrated_probability']


def test_real_new_examples_and_trace_provenance_match_scored_graph(ethereum_service):
    s = ethereum_service
    from api.datasets.ethereum import prepare_trace_examples
    cases = prepare_trace_examples(s)
    assert cases['trace_scope'] == TRACE_SCOPE and cases['versions'] == s.versions
    assert cases['cases'], 'Current actual graph has eligible paths; absence must be investigated'
    for case in cases['cases']:
        traced = s.trace(case['address_id'],case['trace_config'])
        assert traced['trace_scope'] == TRACE_SCOPE
        assert all(traced['provenance'][key] == s.versions[key] for key in (
            'dataset_id','dataset_fingerprint','risk_revision','graph_revision','trace_scope','calibration_revision'))
        assert any(p['nodes'] == case['nodes'] and p['hop_count'] == case['hops'] for p in traced['top_paths'])
        for node in traced['subgraph']['nodes']:
            assert node['address_id'] in s.risks and node['risk_score'] is not None and node['is_scored']
        for edge in traced['subgraph']['edges']:
            assert edge['src'] in s.risks and edge['dst'] in s.risks
            assert edge['dst'] in s.source_graph.out_neighbors(edge['src'])
            assert edge['evidence'] and edge['evidence'][0]['tx_hash']
        assert 'unscored_nodes' not in traced['statistics']
        assert 'unscored_nodes_excluding_seed' not in traced['selection_analysis']
