"""Activate the frozen, deterministic evidence tree and preserve the previous Demo."""
import hashlib
import json
import shutil
import joblib
import numpy as np
import pandas as pd
from src.train.evidence_tree_experiments import EvidenceTreeExperiment
from src.model.calibration import weighted_probability_logits, calibrated_probability
from src.inference.precompute_scores import risk_level
from src.utils.io import ROOT, read_json, save_json, file_sha256, load_config
from src.utils.logging import get_logger


def precompute_evidence(root=ROOT):
    experiment = EvidenceTreeExperiment(root)
    settings = load_config('scoring.yaml', root)
    final = read_json(experiment.folder / 'final_summary.json')
    recipe, parameter = final['selection']['recipe'], final['matched_parameter']
    seed = final['representative_seed']
    joint = experiment.folder / f'final/seed_{seed}/{recipe}__{parameter}'
    info = read_json(joint / 'validation.json')
    logger = get_logger('evidence_inference', root)
    logger.info('Precomputing frozen evidence model %s', recipe)
    all_nodes = np.ones(len(experiment.roles.labels), dtype=bool)
    x = experiment.inputs(recipe, all_nodes)
    out = root / 'artifacts/evidence_scoring'
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / 'features.npy', x)
    model = joblib.load(joint / 'model.pkl')
    margin = model.booster_.predict(x, raw_score=True)
    z = margin-np.log(info['positive_weight'])
    scores = 100*calibrated_probability(z, info['temperature'])
    hashes = {}
    for path in [joint / 'model.pkl', joint / 'validation.json', experiment.folder / 'selection.json',
                 root / 'artifacts/experiments/graph_signals_v1/transforms/final.json', out / 'features.npy']:
        hashes[path.relative_to(root).as_posix()] = file_sha256(path)
    route_scores, route_thresholds = {}, {}
    for role, path, columns in [
        ('behavior', experiment.folder / f'final/seed_{seed}/behavior_only__{parameter}', [i for i, item in enumerate(info['schema']) if item['group'] == 'behavior']),
        ('context', root / 'artifacts/experiments/evidence_tree_v1_ablation/context_z_only', [i for i, item in enumerate(info['schema']) if item['group'] == 'context']),
        ('structure', experiment.folder / f'final/seed_{seed}/structure_only__{parameter}', [i for i, item in enumerate(info['schema']) if item['group'] == 'structure']),
    ]:
        route_info = read_json(path / 'validation.json')
        route_model = joblib.load(path / 'model.pkl')
        p = route_model.predict_proba(x[:, columns])[:, 1]
        route_scores[role] = 100*calibrated_probability(weighted_probability_logits(p, route_info['positive_weight']), route_info['temperature'])
        route_thresholds[role] = 100*route_info['threshold']
        for filename in ['model.pkl', 'validation.json']:
            hashes[(path / filename).relative_to(root).as_posix()] = file_sha256(path / filename)
    addresses = read_json(root / 'data/processed/idx_to_address.json')
    thresholds = load_config('model.yaml', root)['risk_level']
    table = pd.DataFrame({'address_id': [addresses[str(i)] for i in range(len(scores))], 'node_idx': np.arange(len(scores)),
                          'behavior_score': route_scores['behavior'], 'graph_score': route_scores['context'],
                          'structure_score': route_scores['structure'], 'overall_raw_score': 100*calibrated_probability(z, 1),
                          'overall_risk_score': scores, 'behavior_weight': np.nan, 'graph_weight': np.nan})
    table['risk_level'] = [risk_level(score, thresholds) for score in scores]
    table['risk_rank'] = table.overall_risk_score.rank(method='first', ascending=False).astype(int)
    table.to_parquet(out / 'risk_scores.parquet', index=False)
    hashes[(out / 'risk_scores.parquet').relative_to(root).as_posix()] = file_sha256(out / 'risk_scores.parquet')
    metadata = {'model_kind': 'evidence_tree', 'model_name': settings['model_name'], 'model_version': settings['version'],
                'experiment': experiment.settings['name'], 'recipe': recipe, 'parameter': parameter,
                'dataset_fingerprint': experiment.roles.metadata['fingerprint'], 'scope': experiment.roles.metadata['scope'],
                'num_nodes': len(table), 'seed': seed, 'temperature': info['temperature'], 'branch_scores_calibrated': True,
                'fusion': 'joint_feature_fusion', 'route_thresholds': route_thresholds,
                'model_path': (joint / 'model.pkl').relative_to(root).as_posix(),
                'validation_path': (joint / 'validation.json').relative_to(root).as_posix(),
                'features_path': (out / 'features.npy').relative_to(root).as_posix(),
                'metrics_path': (joint / 'test.json').relative_to(root).as_posix(),
                'source_hashes': hashes, 'test_used_for_selection': False,
                'inference': 'deterministic precomputed whole-snapshot features; same rows used for test and Demo'}
    metadata['risk_revision'] = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
    save_json(out / 'metadata.json', metadata)
    active = root / 'artifacts/risk_scores'
    backup = experiment.folder / 'previous_demo'
    if not (backup / 'complete.json').exists():
        for relative in ['artifacts/risk_scores', 'artifacts/demo_cases.json', 'artifacts/traces', 'artifacts/reports']:
            source = root / relative
            destination = backup / relative
            if source.is_dir():
                shutil.copytree(source, destination, dirs_exist_ok=True)
            elif source.exists():
                destination.parent.mkdir(parents=True, exist_ok=True); shutil.copy2(source, destination)
        save_json(backup / 'complete.json', {'previous_revision': read_json(active / 'metadata.json')['risk_revision']})
    shutil.copy2(out / 'risk_scores.parquet', active / 'risk_scores.parquet')
    # Commit metadata last so readers reject stale optional overlays and statistics.
    save_json(active / 'metadata.json', metadata)
    logger.info('Activated %s; %s', metadata['risk_revision'], table.risk_level.value_counts().to_dict())
    return metadata
