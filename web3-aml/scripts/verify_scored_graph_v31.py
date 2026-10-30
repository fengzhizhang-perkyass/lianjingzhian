"""Read-only real graph/model parity verification; no Runtime or LLM requests."""
from pathlib import Path
from datetime import datetime, timezone
import json
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from api.datasets.ethereum import EthereumService
from api.datasets.scored_graph import TRACE_SCOPE, verify_scored_trace_graph
from src.utils.io import file_sha256, read_json, save_json


def main():
    service = EthereumService(ROOT)
    folder = service.folder
    manifest = read_json(folder/'manifest.json')
    graph_manifest = verify_scored_trace_graph(
        service.trace_folder, source_manifest=manifest,
        calibration_revision=service.calibration.revision)
    raw = pd.read_parquet(folder/'risk_scores.parquet')
    assert service.trace_scope == TRACE_SCOPE
    assert set(service.graph.address_to_idx) == set(raw.address_id) == set(service.risks)
    assert len(service.source_graph.address_to_idx) == manifest['graph_nodes']

    # Compare all edges, not just selected examples, with the original graph.
    membership = set(service.risks)
    actual, incoming = set(), set()
    for src_idx, dsts in service.graph.outgoing.items():
        src = service.graph.idx_to_address[int(src_idx)]
        for dst_idx in dsts:
            actual.add((src, service.graph.idx_to_address[int(dst_idx)]))
    for dst_idx, srcs in service.graph.incoming.items():
        dst = service.graph.idx_to_address[int(dst_idx)]
        for src_idx in srcs:
            incoming.add((service.graph.idx_to_address[int(src_idx)], dst))
    expected = {(a,b) for a in membership for b in service.source_graph.out_neighbors(a) if b in membership}
    assert actual == incoming == expected
    assert len(actual) == graph_manifest['graph_edges']

    mappings = read_json(service.trace_folder/'node_mappings.json')
    for i, row in enumerate(raw.itertuples()):
        address = str(row.address_id)
        assert mappings['score_row_by_address'][address] == i == service._score_row[address]
        assert mappings['source_node_idx_by_address'][address] == int(row.node_idx)
        assert mappings['trace_node_idx_by_address'][address] == service.graph.address_to_idx[address]

    # Actual native inference over every scored account, against both frozen
    # branch outputs. Nothing is fitted and no benchmark label array is opened.
    attribute = service._attribute.predict(service._x, num_threads=2)
    joint_inputs = np.concatenate([service._x, service._embedding], axis=1)
    joint = service._joint.predict(joint_inputs, num_threads=2)
    attribute_error = float(np.max(np.abs(attribute-raw.attribute_probability.to_numpy())))
    joint_error = float(np.max(np.abs(joint-raw.joint_probability.to_numpy())))
    fused = .6*attribute+.4*joint
    risk_error = float(np.max(np.abs(fused*100-raw.overall_risk_score.to_numpy())))
    assert attribute_error <= 1e-12 and joint_error <= 1e-12 and risk_error <= 1e-10
    assert np.array_equal(service.predictor.table.overall_risk_score.to_numpy(), raw.overall_risk_score.to_numpy())

    source_assets = {}
    for name, record in manifest['runtime_assets'].items():
        p = folder/name
        source_assets[name] = {'sha256':file_sha256(p), 'bytes':p.stat().st_size}
        assert source_assets[name] == record
    models = {}
    for key, relative in manifest['model_paths'].items():
        sha = file_sha256(ROOT/relative)
        assert sha == manifest['source_hashes'][relative]
        models[key] = {'path':relative, 'sha256':sha}

    cases = read_json(service.trace_folder/'long_cases.json')
    assert cases['versions'] == service.versions
    witnessed = []
    for case in cases['cases']:
        result = service.trace(case['address_id'], case['trace_config'])
        assert all(node['address_id'] in membership and node['is_scored'] and node['risk_score'] is not None
                   for node in result['subgraph']['nodes'])
        assert all((edge['src'],edge['dst']) in expected for edge in result['subgraph']['edges'])
        assert any(p['nodes']==case['nodes'] and p['hop_count']==case['hops'] for p in result['top_paths'])
        assert all(a in membership for p in result['top_paths'] for a in p['nodes'])
        assert all(node['risk_score']==service.risks[node['address_id']] for node in result['subgraph']['nodes'])
        assert all(edge['evidence'] for edge in result['subgraph']['edges'])
        witnessed.append({'address_id':case['address_id'], 'actual_hops':case['hops'],
                          'returned_paths':len(result['top_paths']),
                          'actual_edge_inspections':result['search_budget']['actual_edge_inspections']})

    # Keep the original model's observed context, even though a narrower graph
    # is used for tracing. This address has 147 observed versus 1 scored peer.
    address = '0xd635cb5d0fc7688ab4cde7b71276b6f0cb40f2af'
    analysis = service.analyze(address)
    structure = analysis['scoring_analysis']['structure_summary']
    assert structure['observed_counterparty_count'] == len(service.source_graph.neighbors(address)) == 147
    assert len(service.graph.neighbors(address)) == 1

    low_bridge = None
    tested = set()
    for middle in service.graph.address_to_idx:
        if service.risks[middle] >= 30:
            continue
        mi = service.graph.address_to_idx[middle]
        previous = [service.graph.idx_to_address[int(i)] for i in service.graph.incoming.get(mi, [])]
        anchors = [a for a in service.graph.out_neighbors(middle) if service.risks[a] >= 30]
        for seed in previous:
            if not anchors or seed in tested:
                continue
            tested.add(seed)
            result = service.trace(seed, {'max_depth':8,'max_bridge_nodes':7,'top_paths':30,'edge_budget':10000})
            eligible = [p for p in result['top_paths'] if any(a in p['nodes'][1:-1] and service.risks[a]<30 for a in p['nodes'])]
            if eligible:
                path = eligible[0]
                low_bridge = {'seed':seed, 'nodes':path['nodes'], 'node_risks':path['node_risks'],
                              'bridge_nodes':path['bridge_nodes'], 'hop_count':path['hop_count']}
                break
        if low_bridge is not None:
            break

    output = ROOT/'artifacts/v31_graph_verification'
    output.mkdir(parents=True,exist_ok=True)
    record = {'verified_utc':datetime.now(timezone.utc).isoformat(), 'passed':True,
              'trace_scope':service.trace_scope, 'versions':service.versions,
              'trace_graph_nodes':len(membership), 'trace_graph_edges':len(actual),
              'source_graph_nodes':len(service.source_graph.address_to_idx),
              'source_graph_edges':manifest['graph_edges'],
              'all_trace_edges_are_exact_induced_original_edges':True,
              'incoming_matches_outgoing':True, 'explicit_node_mappings_checked':len(raw),
              'native_probability_checks':{'rows':len(raw), 'attribute_max_error':attribute_error,
                                           'joint_max_error':joint_error, 'fusion_score_max_error':risk_error},
              'identity_current_scores_exactly_match_frozen_scores':True,
              'source_runtime_assets_unchanged':source_assets, 'frozen_models_unchanged':models,
              'actual_cases':witnessed, 'actual_low_scored_bridge':low_bridge,
              'low_bridge_candidates_traced':len(tested),
              'model_context_preserved':{'address_id':address, 'observed_peers':147,'trace_scored_peers':1},
              'runtime_created':False, 'external_llm_calls':0, 'models_trained':False, 'labels_opened':False}
    save_json(output/'verification.json',record)
    print(json.dumps({k:v for k,v in record.items() if k not in ('source_runtime_assets_unchanged','frozen_models_unchanged')},ensure_ascii=False),flush=True)


if __name__ == '__main__':
    main()
