"""Explicit preparation of an induced tracing graph over scored ETH addresses.

The original graph remains model context. No paths are contracted, no labels are
opened, and no model or feature is changed. All remappings are persisted.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import hashlib
import json
import pickle
import time
import uuid

import numpy as np
import pandas as pd

from src.tracing.graph_loader import DirectedGraph
from src.tracing.anchor_index import RiskAnchorIndex
from src.utils.io import read_json, save_json, file_sha256, load_config


TRACE_SCOPE = 'ethereum_scored_addresses_only'
GRAPH_FILES = ('outgoing_neighbors.pkl', 'incoming_neighbors.pkl',
               'address_to_idx.json', 'idx_to_address.json')


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    allow_nan=False).encode()).hexdigest()


def effective_risk_revision(frozen_revision, calibration_revision):
    return stable_hash({'frozen_risk_revision': frozen_revision,
                        'calibration_revision': calibration_revision})


def prepare_bitcoin_trace_index(root):
    """Prepare versioned BTC anchors offline, retaining the previous index."""
    root = Path(root)
    folder = root/'artifacts/datasets/bitcoin/current'
    manifest = read_json(folder/'manifest.json')
    from src.probability_calibration import load_calibration
    calibration = load_calibration(root, 'bitcoin', manifest)
    revision = effective_risk_revision(manifest['risk_revision'], calibration.revision)
    target = folder/'anchor_index_v31'/revision[:16]
    graph = load_graph(folder, manifest)
    settings = load_config('tracing.yaml', root)
    provenance = {'dataset_id': 'bitcoin', 'dataset_fingerprint': manifest['fingerprint'],
                  'risk_revision': revision, 'graph_revision': manifest['graph_revision'],
                  'trace_scope': 'bitcoin_scored_addresses_only',
                  'calibration_revision': calibration.revision}
    try:
        index = RiskAnchorIndex.load(graph, target, provenance, settings['risk_threshold'], 64)
    except (FileNotFoundError, ValueError, KeyError):
        frame = pd.read_parquet(folder/'risk_scores.parquet')
        scores = frame.overall_risk_score.to_numpy(dtype=np.float64)
        if calibration.describe()['mode'] != 'identity':
            scores = calibration.apply(scores/100)*100
        risks = dict(zip(frame.address_id.astype(str), map(float, scores)))
        index = RiskAnchorIndex.build(graph, risks, settings['risk_threshold'], 64, provenance)
        index.save(target)
    return target


def load_graph(folder, metadata=None):
    folder = Path(folder)
    with (folder/'outgoing_neighbors.pkl').open('rb') as stream:
        outgoing = pickle.load(stream)
    with (folder/'incoming_neighbors.pkl').open('rb') as stream:
        incoming = pickle.load(stream)
    return DirectedGraph(outgoing, incoming, read_json(folder/'address_to_idx.json'),
                         read_json(folder/'idx_to_address.json'), dict(metadata or {}))


def induced_scored_graph(source_graph, table, metadata=None):
    """Return true induced edges and explicit source/score/trace row mappings."""
    if not {'address_id', 'node_idx'}.issubset(table.columns):
        raise ValueError('Score table needs address and original graph node index')
    if not table.address_id.is_unique or not table.node_idx.is_unique:
        raise ValueError('Score address and source node index must be unique')
    score_rows = {str(row.address_id): i for i, row in enumerate(table.itertuples())}
    source_indices = {str(row.address_id): int(row.node_idx) for row in table.itertuples()}
    if any(source_graph.address_to_idx.get(a) != i for a, i in source_indices.items()):
        raise ValueError('Score table and original graph address mapping differ')
    addresses = sorted(source_indices, key=lambda a: source_indices[a])
    mapping = {a: i for i, a in enumerate(addresses)}
    reverse = {i: a for a, i in mapping.items()}
    source_to_trace = {source_indices[a]: i for a, i in mapping.items()}
    outgoing, incoming = {}, {}
    edge_count = 0
    for address in addresses:
        src = mapping[address]
        # Preserve the source's deterministic adjacency order; never replace a
        # missing intermediate by a shortcut to one of its descendants.
        seen, targets = set(), []
        for source_dst in source_graph.outgoing.get(source_indices[address], []):
            dst = source_to_trace.get(int(source_dst))
            if dst is not None and dst not in seen:
                targets.append(dst)
                seen.add(dst)
                incoming.setdefault(dst, []).append(src)
        if targets:
            outgoing[src] = targets
            edge_count += len(targets)
    graph = DirectedGraph(outgoing, incoming, mapping, reverse, dict(metadata or {}))
    maps = {'source_node_idx_by_address': source_indices,
            'score_row_by_address': score_rows,
            'trace_node_idx_by_address': mapping,
            'semantics': 'Model row, original source graph index, and tracing index are separate identifiers'}
    return graph, maps, edge_count


def graph_statistics(graph, risks):
    """Only actual induced neighbours contribute to the tracing context."""
    if set(risks) != set(graph.address_to_idx):
        raise ValueError('Scored tracing graph must contain exactly the risk addresses')
    rows = []
    for address in graph.address_to_idx:
        neighbors = graph.neighbors(address)
        values = [risks[a] for a in neighbors]
        out_degree, in_degree = graph.degrees(address)
        high = sum(v >= 60 for v in values)
        rows.append({'address_id': address, 'out_degree': out_degree, 'in_degree': in_degree,
                     'one_hop_neighbor_count': len(neighbors), 'one_hop_scored_count': len(neighbors),
                     'one_hop_avg_risk': float(np.mean(values)) if values else None,
                     'one_hop_high_risk_count': high,
                     'one_hop_high_risk_ratio': high/len(values) if values else None})
    return pd.DataFrame(rows)


def verify_scored_trace_graph(folder, *, source_manifest=None, calibration_revision=None):
    folder = Path(folder)
    path = folder/'manifest.json'
    if not path.is_file():
        raise FileNotFoundError('以太坊已评分地址追踪图尚未准备，请运行 python scripts/prepare_v3_runtime.py --dataset ethereum。')
    manifest = read_json(path)
    if manifest.get('dataset_id') != 'ethereum' or manifest.get('trace_scope') != TRACE_SCOPE:
        raise ValueError('Scored tracing graph identity or scope mismatch')
    for name in (*GRAPH_FILES, 'node_mappings.json', 'graph_statistics.parquet'):
        if name not in manifest.get('runtime_assets', {}):
            raise ValueError('Scored tracing manifest omits asset: '+name)
    for name, record in manifest['runtime_assets'].items():
        relative = Path(name)
        target = (folder/relative).resolve()
        if relative.is_absolute() or not target.is_relative_to(folder.resolve()):
            raise ValueError('Scored tracing asset path escapes release')
        if not target.is_file() or target.stat().st_size != record['bytes'] or file_sha256(target) != record['sha256']:
            raise ValueError('Scored tracing asset hash mismatch: '+name)
    if source_manifest is not None:
        for key in ('graph_revision', 'risk_revision', 'fingerprint'):
            if manifest['source_'+key] != source_manifest[key]:
                raise ValueError('Scored tracing source revision mismatch: '+key)
        if manifest['graph_nodes'] != source_manifest['scored_addresses']:
            raise ValueError('Scored tracing node count differs from scored cohort')
    if calibration_revision is not None and manifest['calibration_revision'] != calibration_revision:
        raise ValueError('Scored tracing calibration revision mismatch; prepare the runtime again')
    return manifest


def prepare_scored_trace_graph(root):
    """Maintenance task only; never called from a normal web request."""
    root = Path(root).resolve()
    source = root/'artifacts/datasets/ethereum/current'
    source_manifest = read_json(source/'manifest.json')
    if source_manifest.get('dataset_id') != 'ethereum':
        raise ValueError('Wrong source dataset for scored tracing graph')
    from src.probability_calibration import load_calibration
    calibration = load_calibration(root, 'ethereum', source_manifest)
    final = source/'trace_scored'
    if (final/'manifest.json').is_file():
        try:
            return verify_scored_trace_graph(final, source_manifest=source_manifest,
                                             calibration_revision=calibration.revision)
        except (ValueError, FileNotFoundError, KeyError):
            # A replacement is built atomically, keeping the previous complete
            # tracing release available in an explicitly named backup directory.
            pass
    started = time.monotonic()
    source_hashes = {}
    for name in (*GRAPH_FILES, 'risk_scores.parquet'):
        record = source_manifest['runtime_assets'][name]
        path = source/name
        actual = file_sha256(path)
        if path.stat().st_size != record['bytes'] or actual != record['sha256']:
            raise ValueError('Original Ethereum runtime asset changed: '+name)
        source_hashes[name] = actual
    table = pd.read_parquet(source/'risk_scores.parquet')
    table['address_id'] = table.address_id.astype(str)
    raw = table.overall_risk_score.to_numpy(dtype=np.float64)/100
    scores = (table.overall_risk_score.to_numpy(dtype=np.float64)
              if calibration.describe()['mode'] == 'identity'
              else np.asarray(calibration.apply(raw), dtype=np.float64)*100)
    if len(table) != source_manifest['scored_addresses'] or not np.isfinite(scores).all():
        raise ValueError('Invalid source risk cohort')
    risks = dict(zip(table.address_id, map(float, scores)))
    source_graph = load_graph(source, source_manifest)
    graph, mappings, edge_count = induced_scored_graph(source_graph, table)
    build = source/('trace_scored.build_'+uuid.uuid4().hex)
    build.mkdir()
    for name, value in [('outgoing_neighbors.pkl', graph.outgoing), ('incoming_neighbors.pkl', graph.incoming)]:
        with (build/name).open('wb') as stream:
            pickle.dump(value, stream, protocol=pickle.HIGHEST_PROTOCOL)
    save_json(build/'address_to_idx.json', graph.address_to_idx)
    save_json(build/'idx_to_address.json', graph.idx_to_address)
    save_json(build/'node_mappings.json', mappings)
    graph_statistics(graph, risks).to_parquet(build/'graph_statistics.parquet', index=False)
    assets = {p.name: {'bytes': p.stat().st_size, 'sha256': file_sha256(p)}
              for p in sorted(build.iterdir()) if p.is_file()}
    topology = {name: assets[name]['sha256'] for name in GRAPH_FILES}
    graph_revision = stable_hash({'trace_scope': TRACE_SCOPE, 'source_graph_revision': source_manifest['graph_revision'],
                                  'topology': topology, 'mapping': assets['node_mappings.json']['sha256']})
    risk_revision = effective_risk_revision(source_manifest['risk_revision'], calibration.revision)
    metadata = {**source_manifest, 'graph_revision': graph_revision, 'trace_scope': TRACE_SCOPE,
                'graph_nodes': len(graph.address_to_idx), 'graph_edges': edge_count}
    graph.metadata = metadata
    settings = load_config('tracing.yaml', root)
    provenance = {'dataset_id': 'ethereum', 'dataset_fingerprint': source_manifest['fingerprint'],
                  'risk_revision': risk_revision, 'graph_revision': graph_revision,
                  'trace_scope': TRACE_SCOPE, 'calibration_revision': calibration.revision}
    index = RiskAnchorIndex.build(graph, risks, settings['risk_threshold'], 64, provenance)
    index.save(build/'anchor_index')
    for p in sorted((build/'anchor_index').iterdir()):
        assets[str(p.relative_to(build))] = {'bytes': p.stat().st_size, 'sha256': file_sha256(p)}
    manifest = {'dataset_id': 'ethereum', 'trace_scope': TRACE_SCOPE,
                'source_graph_revision': source_manifest['graph_revision'],
                'source_risk_revision': source_manifest['risk_revision'],
                'source_fingerprint': source_manifest['fingerprint'],
                'source_graph_nodes': len(source_graph.address_to_idx),
                'source_graph_edges': source_manifest['graph_edges'],
                'graph_nodes': len(graph.address_to_idx), 'graph_edges': edge_count,
                'graph_revision': graph_revision, 'risk_revision': risk_revision,
                'calibration_revision': calibration.revision, 'source_hashes': source_hashes,
                'runtime_assets': assets, 'preparation_seconds': time.monotonic()-started,
                'prepared_utc': datetime.now(timezone.utc).isoformat(),
                'construction': 'Induced directed subgraph over exactly the frozen scored-address cohort; no path contraction',
                'labels_loaded': False, 'models_trained': False, 'source_assets_modified': False}
    save_json(build/'manifest.json', manifest)
    verify_scored_trace_graph(build, source_manifest=source_manifest, calibration_revision=calibration.revision)
    if final.exists():
        final.rename(source/('trace_scored.previous_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S')+'_'+uuid.uuid4().hex[:6]))
    build.rename(final)
    print(json.dumps({'stage': 'scored_trace_graph_prepared', 'graph_nodes': manifest['graph_nodes'],
                      'graph_edges': edge_count, 'seconds': manifest['preparation_seconds']}), flush=True)
    return manifest
