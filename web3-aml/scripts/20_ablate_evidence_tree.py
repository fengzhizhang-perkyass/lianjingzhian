"""Matched removals and direction control; cannot reselect the frozen main model."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import numpy as np
import pandas as pd
import joblib
from src.train.evidence_tree_experiments import EvidenceTreeExperiment
from src.model.graph_signals import adjacency_operators
from src.model.neighborhood_statistics import neighborhood_statistics
from src.model.directed_structure import directed_structure
from src.model.calibration import weighted_probability_logits, calibrated_probability
from src.train.evaluate import evaluate_predictions
from src.train.risk_experiments import review_metrics
from src.utils.io import ROOT, load_config, read_json, save_json, file_sha256

settings = load_config('evidence_tree_ablation.yaml')['experiment']
experiment = EvidenceTreeExperiment()
selected = read_json(experiment.folder / 'final_freeze.json')
folder = ROOT / 'artifacts/experiments' / settings['name']
manifest = {'settings': settings, 'main_selection_sha256': file_sha256(experiment.folder / 'selection.json'),
            'purpose': 'post-freeze matched removal controls; no main reselection', 'test_already_observed': True}
if (folder / 'manifest.json').exists() and read_json(folder / 'manifest.json') != manifest:
    raise RuntimeError('Ablation settings changed; use a new name')
save_json(folder / 'manifest.json', manifest)
experiment.recipes.update(settings['recipes'])
original_inputs = experiment.inputs


def directionless_inputs(recipe, mask, fold=None, cutoff=None):
    if recipe != 'direction_removed':
        return original_inputs(recipe, mask, fold, cutoff)
    source = experiment.signals.cache(fold, cutoff)
    cache = folder / 'cache' / str(cutoff)
    if not (cache / 'complete.json').exists():
        cache.mkdir(parents=True, exist_ok=True)
        x = np.load(source / 'self.npy', mmap_mode='r')
        edges = np.concatenate([experiment.roles.edges, experiment.roles.edges[::-1]], axis=1)
        operators = adjacency_operators(edges, len(x), experiment.roles.times, cutoff)
        for name, values in neighborhood_statistics(x, operators, experiment.settings['zscore_std_floor'], experiment.settings['zscore_clip']):
            np.save(cache / f'{name}.npy', values)
        np.save(cache / 'structure.npy', directed_structure(edges, len(x), experiment.roles.times, cutoff))
        save_json(cache / 'complete.json', {'cutoff': cutoff, 'directed': False})
    return np.column_stack([np.load(source / 'self.npy', mmap_mode='r')[mask],
                            np.load(cache / 'out_zscore.npy', mmap_mode='r')[mask],
                            np.load(cache / 'in_zscore.npy', mmap_mode='r')[mask],
                            np.load(cache / 'structure.npy', mmap_mode='r')[mask]])


experiment.inputs = directionless_inputs
parameter, seed = selected['matched_parameter'], settings['seed']
validation = []
for recipe in settings['recipes']:
    info, _ = experiment.fit(recipe, parameter, seed, run_folder=folder / recipe)
    validation.append({'recipe': recipe, 'validation_ap': info['validation_ap']})
save_json(folder / 'freeze.json', {'parameter': parameter, 'seed': seed, 'validation': validation,
                                 'main_selection_unchanged': True})
test = np.load(ROOT / 'data/processed/test_mask.npy')
rows = []
for recipe in settings['recipes']:
    target = folder / recipe
    info = read_json(target / 'validation.json')
    model = joblib.load(target / 'model.pkl')
    x = experiment.inputs(recipe, test)
    p = calibrated_probability(weighted_probability_logits(model.predict_proba(x)[:, 1], info['positive_weight']), info['temperature'])
    result = evaluate_predictions(experiment.roles.labels[test], p, info['threshold'])
    result['review'] = review_metrics(experiment.roles.labels[test], p, experiment.settings['review_top_k'], experiment.settings['review_fractions'])
    save_json(target / 'test.json', result)
    np.savez_compressed(target / 'test_predictions.npz', node_idx=np.flatnonzero(test), probability=p)
    rows.append({'candidate': recipe, 'seed': seed, **{k: result[k] for k in ['pr_auc', 'f1', 'precision', 'recall', 'roc_auc']}})
pd.DataFrame(rows).to_csv(folder / 'comparison.csv', index=False)
print(pd.DataFrame(rows).round(4).to_string(index=False))
