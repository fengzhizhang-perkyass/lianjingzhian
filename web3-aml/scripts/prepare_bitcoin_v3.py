"""Prepare the frozen B3 serving release without training or test-label access."""
from pathlib import Path
import sys
import hashlib
import json
import shutil
import os
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import numpy as np
import pandas as pd
from src.utils.io import file_sha256, read_json, save_json
from src.inference.native_tree import load_native_tree
from api.datasets.base import risk_level

EXPECTED_FEATURE_SHA = 'a2ed1c8b29d1fd6a55725b2746bf9f61ab09dec766767e51aac35fed324fb232'
EXPECTED_MODEL_SHA = 'caf785077e055ae5ecb0a05b3296e505aefd224f3dc040320699c1a7155805d3'


def prepare_bitcoin(root=ROOT):
    root = Path(root)
    folder = root/'artifacts/datasets/bitcoin/current'
    if (folder/'manifest.json').exists():
        return folder
    folder.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    source = root/'model_upgrade/remote_records/entity_refit/model_upgrade/all_pretest_refit/runs/fixed_s42'
    model_path = source/'model.pkl'
    # Prefer the exact frozen input: ARM and x86 float32 log1p can differ by
    # one ULP, so a local rebuild must never silently replace these bytes.
    frozen_path = root/'model_upgrade/transaction_evidence/cache_v3_frozen/features.npy'
    features_path = frozen_path if frozen_path.exists() else root/'model_upgrade/transaction_evidence/cache/features.npy'
    schema_path = features_path.with_name('schema.json')
    if not features_path.exists() or not schema_path.exists():
        raise RuntimeError('比特币1783维冻结特征尚未准备完成，请补齐原实验缓存并核验SHA256。')
    if file_sha256(model_path) != EXPECTED_MODEL_SHA:
        raise ValueError('Frozen B3 model hash mismatch')
    feature_sha = file_sha256(features_path)
    if feature_sha != EXPECTED_FEATURE_SHA:
        raise ValueError(f'1783 cache does not match frozen feature bytes: {feature_sha}')
    x = np.load(features_path, mmap_mode='r')
    if x.shape != (822942, 1783):
        raise ValueError('Wrong B3 feature shape')
    model = load_native_tree(model_path, backend='lightgbm_joblib', expected_features=1783)
    fixture = np.load(source/'reload_samples.npz')
    ids = fixture['node_idx']
    if not np.array_equal(x[ids], fixture['features']):
        raise ValueError('Prepared inputs differ from frozen source fixtures')
    error = float(np.max(np.abs(model.predict_probability(x[ids])-fixture['probability'])))
    if error > 1e-12:
        raise ValueError('B3 native reload differs from frozen probabilities')
    group_map = []
    for original in read_json(schema_path):
        item = dict(original)
        item['group'] = ('structure' if str(item['feature']).startswith('tx_') else original['group'])
        group_map.append(item)
    if len(group_map) != 1783 or set(i['group'] for i in group_map) != {'behavior', 'context', 'structure'}:
        raise ValueError('Every model input needs one display group')
    save_json(folder/'schema.json', group_map)
    arrays = ('address_to_idx.json', 'idx_to_address.json', 'outgoing_neighbors.pkl', 'incoming_neighbors.pkl')
    source_hashes = {}
    for name in arrays:
        p = root/'data/processed'/name
        source_hashes[str(p.relative_to(root))] = file_sha256(p)
        shutil.copy2(p, folder/name)
    mapping = read_json(folder/'idx_to_address.json')
    probability = np.empty(len(x), np.float64)
    for begin in range(0, len(x), 8192):
        end = min(begin+8192, len(x))
        probability[begin:end] = model._model.predict(np.asarray(x[begin:end]), num_threads=4)
        if begin % (8192*16) == 0:
            print(json.dumps({'stage': 'bitcoin_scores', 'completed': end, 'total': len(x)}), flush=True)
    if not np.isfinite(probability).all() or (probability < 0).any() or (probability > 1).any():
        raise ValueError('Invalid native B3 probabilities')
    table = pd.DataFrame({'address_id': [mapping[str(i)] for i in range(len(x))],
                          'node_idx': np.arange(len(x)), 'overall_risk_score': probability*100})
    table['risk_level'] = [risk_level(v) for v in table.overall_risk_score]
    table.to_parquet(folder/'risk_scores.parquet', index=False)
    source_hashes.update({str(model_path.relative_to(root)): EXPECTED_MODEL_SHA,
                          str(features_path.relative_to(root)): feature_sha,
                          str(schema_path.relative_to(root)): file_sha256(schema_path)})
    def digest(v):
        return hashlib.sha256(json.dumps(v, sort_keys=True).encode()).hexdigest()
    metadata = read_json(root/'data/processed/metadata.json')
    graph_revision = digest({k: v for k, v in source_hashes.items() if k.startswith('data/processed/')})
    feature_revision = digest([feature_sha, file_sha256(folder/'schema.json')])
    manifest = {'dataset_id': 'bitcoin', 'label': '比特币', 'dataset': 'Elliptic++',
        'fingerprint': metadata['fingerprint'], 'graph_revision': graph_revision,
        'risk_revision': digest([EXPECTED_MODEL_SHA, feature_sha, .1622163259483896]),
        'feature_revision': feature_revision, 'model_display_name': '多维证据风险识别',
        'model_threshold': .1622163259483896, 'feature_count': 1783,
        'scored_addresses': len(x), 'graph_nodes': len(x), 'graph_edges': metadata['num_edges'],
        'features_path': str(features_path.relative_to(root)), 'model_path': str(model_path.relative_to(root)),
        'source_hashes': source_hashes, 'runtime_hashes': {n: file_sha256(folder/n) for n in [*arrays, 'schema.json', 'risk_scores.parquet']},
        'verification': {'frozen_feature_bytes_match': True, 'frozen_fixture_rows': len(ids),
                         'fixture_probability_max_error': error, 'training_performed': False,
                         'test_labels_loaded': False},
        'seconds': time.monotonic()-started}
    save_json(folder/'manifest.json', manifest)
    print(json.dumps({'dataset': 'bitcoin', 'ready': True, 'rows': len(x), 'seconds': manifest['seconds']}), flush=True)
    return folder


if __name__ == '__main__':
    prepare_bitcoin()
