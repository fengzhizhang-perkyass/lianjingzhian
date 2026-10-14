"""Lightweight paper-inspired graph filters, with transparent source attribution."""
import hashlib
import json
import time
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping
from sklearn.metrics import average_precision_score
from filelock import FileLock
from src.utils.io import ROOT, read_json, save_json, load_config, file_sha256
from src.utils.logging import get_logger
from src.model.feature_transform import fit_feature_transform, transform_features
from src.model.graph_signals import adjacency_operators, signal_blocks
from src.model.directed_structure import STRUCTURE_NAMES
from src.model.calibration import weighted_probability_logits, fit_temperature, calibrated_probability
from src.train.role_experiments import RoleExperiment
from src.train.investigation_experiments import logits_from_probability
from src.train.evaluate import evaluate_predictions, choose_threshold
from src.train.risk_experiments import review_metrics
from src.inference.investigation import simplex_weights, blend_probabilities


class GraphSignalExperiment:
    def __init__(self, root=ROOT):
        self.root = root
        self.settings = load_config('graph_signal_experiments.yaml', root)['experiment']
        self.roles = RoleExperiment(root)
        self.labels = self.roles.labels
        self.folder = root / 'artifacts/experiments' / self.settings['name']
        self.columns = [i for i, name in enumerate(self.roles.names) if name not in self.roles.features['exclude_features']]
        self.names = [self.roles.names[i] for i in self.columns]
        self.logger = get_logger('graph_signal_experiments', root)
        manifest = {'settings': self.settings, 'dataset_fingerprint': self.roles.metadata['fingerprint'],
                    'behavior_features': self.names, 'signal_code_sha256': file_sha256(root / 'src/model/graph_signals.py'),
                    'source_role_manifest_sha256': file_sha256(self.roles.folder / 'manifest.json'),
                    'test_already_observed': True, 'selection_uses_test': False,
                    'implementation': 'SIGN/Dir-GNN/BWGNN-inspired precomputed features + LightGBM; not original neural reproductions'}
        path = self.folder / 'manifest.json'
        if path.exists() and read_json(path) != manifest:
            raise RuntimeError('Graph-signal experiment settings changed; use a new name')
        save_json(path, manifest)

    def cache(self, fold=None, cutoff=None):
        train, _ = self.roles.masks(fold)
        name = fold['name'] if fold else 'final'
        folder = self.folder / 'cache' / name / (str(cutoff) if cutoff is not None else 'full')
        state_path = self.folder / 'transforms' / f'{name}.json'
        if not state_path.exists():
            save_json(state_path, fit_feature_transform(self.roles.raw, train, self.roles.names, self.roles.features))
        if (folder / 'complete.json').exists():
            return folder
        self.logger.info('Precomputing label-free signals %s', folder)
        folder.mkdir(parents=True, exist_ok=True)
        state = read_json(state_path)
        x = transform_features(self.roles.raw, state)[:, self.columns]
        operators = adjacency_operators(self.roles.edges, len(self.labels), self.roles.times, cutoff)
        for block, values in signal_blocks(x, operators):
            if not (folder / f'{block}.npy').exists():
                np.save(folder / f'{block}.npy', values.astype(np.float32))
        save_json(folder / 'complete.json', {'transform_sha256': file_sha256(state_path), 'cutoff': cutoff,
                                           'columns': self.names, 'num_nodes': len(x)})
        return folder

    def inputs(self, name, mask, fold=None, cutoff=None):
        cache = self.cache(fold, cutoff)
        chunks = []
        for block in self.settings['candidates'][name]:
            chunks.append(self.roles.structure(cutoff)[mask] if block == 'structure' else
                          np.load(cache / f'{block}.npy', mmap_mode='r')[mask])
        return np.column_stack(chunks)

    def feature_names(self, name):
        return [feature for block in self.settings['candidates'][name] for feature in
                (STRUCTURE_NAMES if block == 'structure' else [block+'::'+name for name in self.names])]

    def fit(self, name, fold=None):
        phase = f"development/{fold['name']}" if fold else 'final/models'
        folder = self.folder / phase / name
        if (folder / 'validation.json').exists():
            return read_json(folder / 'validation.json')
        train, val = self.roles.masks(fold)
        split = fold or self.roles.metadata['split']
        xtrain = self.inputs(name, train, fold, split['train_end'])
        xval = self.inputs(name, val, fold, split['val_end'])
        model = LGBMClassifier(**self.settings['tree'], random_state=self.settings['seed'], class_weight='balanced',
                               metric='average_precision', verbosity=-1)
        started = time.monotonic()
        model.fit(xtrain, self.labels[train], eval_set=[(xval, self.labels[val])],
                  callbacks=[early_stopping(self.settings['patience'], verbose=False)])
        weight = float((self.labels[train] == 0).sum()/(self.labels[train] == 1).sum())
        z = weighted_probability_logits(model.predict_proba(xval)[:, 1], weight)
        temperature = fit_temperature(z, self.labels[val])
        p = calibrated_probability(z, temperature)
        info = {'validation_ap': float(average_precision_score(self.labels[val], p)), 'positive_weight': weight,
                'temperature': temperature, 'threshold': choose_threshold(self.labels[val], p),
                'best_iteration': model.best_iteration_, 'seconds': time.monotonic()-started,
                'blocks': self.settings['candidates'][name], 'features': self.feature_names(name)}
        folder.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, folder / 'model.pkl')
        np.savez_compressed(folder / 'validation_predictions.npz', node_idx=np.flatnonzero(val), probability=p)
        pd.DataFrame({'feature': info['features'], 'gain': model.booster_.feature_importance(importance_type='gain')}).to_csv(folder / 'feature_importance.csv', index=False)
        save_json(folder / 'validation.json', info)
        self.logger.info('Completed %s AP %.4f in %.1fs', folder, info['validation_ap'], info['seconds'])
        return info

    def probabilities(self, phase, fold=None, seed=42):
        _, val = self.roles.masks(fold)
        mask = val if phase == 'validation' else np.load(self.root / 'data/processed/test_mask.npy')
        ids = np.flatnonzero(mask)
        split = fold or self.roles.metadata['split']
        predictions, thresholds = {}, {}
        for name in self.settings['candidates']:
            info = self.fit(name, fold)
            folder = self.folder / (f"development/{fold['name']}" if fold else 'final/models') / name
            if phase == 'validation':
                p = np.load(folder / 'validation_predictions.npz')['probability']
            else:
                path = folder / 'test_predictions.npz'
                if not path.exists():
                    model = joblib.load(folder / 'model.pkl')
                    x = self.inputs(name, mask)
                    p = calibrated_probability(weighted_probability_logits(model.predict_proba(x)[:, 1], info['positive_weight']), info['temperature'])
                    np.savez_compressed(path, node_idx=ids, probability=p)
                p = np.load(path)['probability']
            predictions[name], thresholds[name] = p, info['threshold']
        role_ids, role_p, role_t = self.roles.probabilities(phase, fold, seed)
        if not np.array_equal(role_ids, ids):
            raise ValueError('Prediction IDs differ')
        for name in ['graphsage', 'dual_view', 'structure18', 'structure8', 'enhanced_tree']:
            predictions[name], thresholds[name] = role_p[name], role_t[name]
        return ids, predictions, thresholds

    def development(self):
        path = self.folder / 'selection.json'
        if path.exists():
            return read_json(path)
        rows = []
        for fold in self.settings['folds']:
            ids, predictions, _ = self.probabilities('validation', fold)
            y = self.labels[ids]
            for name, p in predictions.items():
                rows.append({'candidate': name, 'weights': '', 'fold': fold['name'],
                             'ap': float(average_precision_score(y, p))})
            for family, experts in self.settings['families'].items():
                matrix = np.column_stack([predictions[e] for e in experts])
                for weights in simplex_weights(len(experts), self.settings['weight_step']):
                    rows.append({'candidate': family, 'weights': '/'.join(f'{w:g}' for w in weights),
                                 'fold': fold['name'], 'ap': float(average_precision_score(y, blend_probabilities(matrix, weights)))})
            pd.DataFrame(rows).to_csv(self.folder / 'development.csv', index=False)
        table = pd.DataFrame(rows)
        scores = table.groupby(['candidate', 'weights'], sort=False, dropna=False).ap.agg(['mean', 'min'])
        choices = {}
        for name in dict.fromkeys(table.candidate):
            best = scores.loc[name].sort_values(['mean', 'min'], ascending=False, kind='stable').iloc[0]
            experts = self.settings['families'].get(name, [name])
            weights = [float(w) for w in best.name.split('/')] if best.name else [1.0]
            choices[name] = {'experts': experts, 'weights': weights, 'mean_development_ap': float(best['mean']),
                             'worst_fold_ap': float(best['min'])}
        best_name = max(choices, key=lambda name: (choices[name]['mean_development_ap'], choices[name]['worst_fold_ap']))
        selection = {'selected_candidate': best_name, **choices[best_name], 'candidate_choices': choices,
                     'test_used_for_selection': False, 'selection_rule': 'highest mean development AP, then worst-fold AP',
                     'tested_weight_configurations': len(scores)}
        save_json(path, selection)
        self.logger.info('Frozen selected method %s', {k: v for k, v in selection.items() if k != 'candidate_choices'})
        return selection

    def final(self):
        with FileLock(str(self.folder / 'experiment.lock'), timeout=5):
            selection = self.development()
            if (self.folder / 'final_summary.json').exists():
                return read_json(self.folder / 'final_summary.json')
            validations = []
            for seed in self.settings['final_seeds']:
                ids, predictions, thresholds = self.probabilities('validation', seed=seed)
                c = {}
                for name, choice in selection['candidate_choices'].items():
                    p = blend_probabilities(np.column_stack([predictions[e] for e in choice['experts']]), choice['weights'])
                    t = fit_temperature(logits_from_probability(p), self.labels[ids])
                    c[name] = {'temperature': t, 'threshold': choose_threshold(self.labels[ids], calibrated_probability(logits_from_probability(p), t)),
                               'validation_ap': float(average_precision_score(self.labels[ids], p))}
                info = {'seed': seed, 'candidates': c, 'expert_thresholds': thresholds}
                save_json(self.folder / f'final/seed_{seed}/calibration.json', info)
                validations.append(info)
            seed = max(validations, key=lambda v: v['candidates'][selection['selected_candidate']]['validation_ap'])['seed']
            freeze = {'selection': selection, 'validation': validations, 'representative_seed': seed,
                      'test_already_observed': True, 'test_used_for_selection': False}
            save_json(self.folder / 'final_freeze.json', freeze)
            rows, reviews = [], []
            for seed in self.settings['final_seeds']:
                ids, p, thresholds = self.probabilities('test', seed=seed)
                c = read_json(self.folder / f'final/seed_{seed}/calibration.json')['candidates']
                combinations = {}
                for name, choice in selection['candidate_choices'].items():
                    blended = blend_probabilities(np.column_stack([p[e] for e in choice['experts']]), choice['weights'])
                    combinations[name] = calibrated_probability(logits_from_probability(blended), c[name]['temperature'])
                combinations['selected'] = combinations[selection['selected_candidate']]
                c['selected'] = c[selection['selected_candidate']]
                for name, probability in combinations.items():
                    result = evaluate_predictions(self.labels[ids], probability, c[name]['threshold'])
                    result['review'] = review_metrics(self.labels[ids], probability, self.settings['review_top_k'], self.settings['review_fractions'])
                    save_json(self.folder / f'final/seed_{seed}/{name}_test.json', result)
                    rows.append({'candidate': name, 'seed': seed, **{k: result[k] for k in ['pr_auc', 'f1', 'precision', 'recall', 'roc_auc', 'brier_score']}})
                    for budget, counts in result['review'].items():
                        reviews.append({'candidate': name, 'seed': seed, 'budget': budget, **counts})
                np.savez_compressed(self.folder / f'final/seed_{seed}/test_predictions.npz', node_idx=ids, **combinations)
            pd.DataFrame(rows).to_csv(self.folder / 'final_comparison.csv', index=False)
            pd.DataFrame(reviews).to_csv(self.folder / 'review_all_seeds.csv', index=False)
            final = {**freeze, 'dataset_fingerprint': self.roles.metadata['fingerprint'],
                     'seed_note': 'Trees are deterministic; variation is only from reused neural experts where active'}
            save_json(self.folder / 'final_summary.json', final)
            return final
