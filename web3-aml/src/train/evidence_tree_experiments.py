"""Joint feature fusion with three accountable evidence groups, no graph network."""
import hashlib
import json
import time
import joblib
import numpy as np
import pandas as pd
from lightgbm import LGBMClassifier, early_stopping
from sklearn.metrics import average_precision_score
from filelock import FileLock
from src.train.graph_signal_experiments import GraphSignalExperiment
from src.model.graph_signals import adjacency_operators
from src.model.neighborhood_statistics import neighborhood_statistics
from src.model.directed_structure import STRUCTURE_NAMES
from src.model.calibration import weighted_probability_logits, fit_temperature, calibrated_probability
from src.train.evaluate import evaluate_predictions, choose_threshold
from src.train.risk_experiments import review_metrics
from src.utils.io import ROOT, load_config, read_json, save_json, file_sha256
from src.utils.logging import get_logger


GROUPS = {'self': 'behavior', 'structure': 'structure'}


class EvidenceTreeExperiment:
    def __init__(self, root=ROOT):
        self.root = root
        self.settings = load_config('evidence_tree_experiments.yaml', root)['experiment']
        self.signals = GraphSignalExperiment(root)
        self.roles = self.signals.roles
        self.folder = root / 'artifacts/experiments' / self.settings['name']
        self.recipes = {**self.settings['recipes'], **self.settings['matched_controls']}
        self.logger = get_logger('evidence_tree_experiments', root)
        if not np.isclose(sum(self.settings['selection_weights'].values()), 1):
            raise ValueError('Validation period weights must sum to one')
        manifest = {'settings': self.settings, 'dataset_fingerprint': self.roles.metadata['fingerprint'],
                    'signal_manifest_sha256': file_sha256(self.signals.folder / 'manifest.json'),
                    'statistic_code_sha256': file_sha256(root / 'src/model/neighborhood_statistics.py'),
                    'test_already_observed': True, 'selection_uses_test': False,
                    'design': 'self behavior + directional neighborhood context + explicit structure; joint feature fusion'}
        path = self.folder / 'manifest.json'
        if path.exists() and read_json(path) != manifest:
            raise RuntimeError('Evidence tree settings changed; use a new name')
        save_json(path, manifest)

    def extra_cache(self, fold=None, cutoff=None):
        name = fold['name'] if fold else 'final'
        folder = self.folder / 'cache' / name / (str(cutoff) if cutoff is not None else 'full')
        if (folder / 'complete.json').exists():
            return folder
        source = self.signals.cache(fold, cutoff)
        x = np.load(source / 'self.npy', mmap_mode='r')
        operators = adjacency_operators(self.roles.edges, len(x), self.roles.times, cutoff)
        folder.mkdir(parents=True, exist_ok=True)
        for name, values in neighborhood_statistics(x, operators, self.settings['zscore_std_floor'], self.settings['zscore_clip']):
            np.save(folder / f'{name}.npy', values)
        save_json(folder / 'complete.json', {'source_transform': read_json(source / 'complete.json')['transform_sha256'],
                                           'num_nodes': len(x), 'cutoff': cutoff})
        return folder

    def inputs(self, recipe, mask, fold=None, cutoff=None):
        source = self.signals.cache(fold, cutoff)
        chunks = []
        for block in self.recipes[recipe]:
            if block == 'structure':
                chunks.append(self.roles.structure(cutoff)[mask])
            elif block.endswith(('_std', '_zscore')):
                chunks.append(np.load(self.extra_cache(fold, cutoff) / f'{block}.npy', mmap_mode='r')[mask])
            else:
                chunks.append(np.load(source / f'{block}.npy', mmap_mode='r')[mask])
        return np.column_stack(chunks)

    def schema(self, recipe):
        return [{'block': block, 'group': GROUPS.get(block, 'context'), 'feature': feature,
                 'name': block+'::'+feature}
                for block in self.recipes[recipe]
                for feature in (STRUCTURE_NAMES if block == 'structure' else self.signals.names)]

    def fit(self, recipe, parameter, seed=42, fold=None, run_folder=None):
        phase = f"development/{fold['name']}" if fold else f'final/seed_{seed}'
        folder = run_folder or self.folder / phase / f'{recipe}__{parameter}'
        if (folder / 'validation.json').exists():
            return read_json(folder / 'validation.json'), folder
        train, val = self.roles.masks(fold)
        split = fold or self.roles.metadata['split']
        xtrain = self.inputs(recipe, train, fold, split['train_end'])
        xval = self.inputs(recipe, val, fold, split['val_end'])
        model = LGBMClassifier(**self.settings['tree_common'], **self.settings['tree_candidates'][parameter],
                               random_state=seed, class_weight='balanced', metric='average_precision', verbosity=-1)
        started = time.monotonic()
        model.fit(xtrain, self.roles.labels[train], eval_set=[(xval, self.roles.labels[val])],
                  callbacks=[early_stopping(self.settings['patience'], verbose=False)])
        weight = float((self.roles.labels[train] == 0).sum()/(self.roles.labels[train] == 1).sum())
        z = weighted_probability_logits(model.predict_proba(xval)[:, 1], weight)
        t = fit_temperature(z, self.roles.labels[val])
        p = calibrated_probability(z, t)
        schema = self.schema(recipe)
        info = {'recipe': recipe, 'parameter': parameter, 'seed': seed,
                'validation_ap': float(average_precision_score(self.roles.labels[val], p)),
                'positive_weight': weight, 'temperature': t, 'threshold': choose_threshold(self.roles.labels[val], p),
                'seconds': time.monotonic()-started, 'best_iteration': model.best_iteration_,
                'blocks': self.recipes[recipe], 'schema': schema}
        folder.mkdir(parents=True, exist_ok=True)
        joblib.dump(model, folder / 'model.pkl')
        np.savez_compressed(folder / 'validation_predictions.npz', node_idx=np.flatnonzero(val), probability=p)
        save_json(folder / 'validation.json', info)
        pd.DataFrame({'feature': [item['name'] for item in schema], 'group': [item['group'] for item in schema],
                      'gain': model.booster_.feature_importance(importance_type='gain')}).to_csv(folder / 'feature_importance.csv', index=False)
        self.logger.info('Completed %s AP %.4f (%.1fs)', folder, info['validation_ap'], info['seconds'])
        return info, folder

    def selection(self):
        path = self.folder / 'selection.json'
        if path.exists():
            return read_json(path)
        rows = []
        periods = [(fold['name'], fold) for fold in self.settings['folds']]+[('final_validation', None)]
        for period, fold in periods:
            for recipe in self.recipes:
                for parameter in self.settings['tree_candidates']:
                    info, _ = self.fit(recipe, parameter, self.settings['seed'], fold)
                    rows.append({'recipe': recipe, 'parameter': parameter, 'period': period,
                                 'validation_ap': info['validation_ap'], 'seconds': info['seconds']})
                    pd.DataFrame(rows).to_csv(self.folder / 'validation_comparison.csv', index=False)
        table = pd.DataFrame(rows)
        table['weighted_ap'] = table.validation_ap*table.period.map(self.settings['selection_weights'])
        scored = table.groupby(['recipe', 'parameter']).weighted_ap.sum()
        choices = {}
        for recipe in self.recipes:
            subset = scored.loc[recipe]
            best = subset.idxmax()
            choices[recipe] = {'parameter': best, 'weighted_validation_ap': float(subset.loc[best])}
        selected_recipe = max(self.settings['recipes'], key=lambda name: choices[name]['weighted_validation_ap'])
        selection = {'recipe': selected_recipe, **choices[selected_recipe], 'recipe_choices': choices,
                     'rule': self.settings['selection_metric'], 'selection_weights': self.settings['selection_weights'],
                     'test_used_for_selection': False, 'test_already_observed': True}
        save_json(path, selection)
        self.logger.info('Frozen evidence tree %s', selection)
        return selection

    def final(self):
        with FileLock(str(self.folder / 'experiment.lock'), timeout=5):
            selection = self.selection()
            path = self.folder / 'final_summary.json'
            if path.exists():
                return read_json(path)
            # Final controls use the selected joint model's budget, not an easier independently tuned budget.
            parameter = selection['parameter']
            candidates = [selection['recipe'], *self.settings['matched_controls']]
            validations = []
            for recipe in candidates:
                for seed in self.settings['final_seeds']:
                    info, _ = self.fit(recipe, parameter, seed)
                    validations.append({k: info[k] for k in ['recipe', 'parameter', 'seed', 'validation_ap']})
            representative = max([v for v in validations if v['recipe'] == selection['recipe']], key=lambda v: v['validation_ap'])['seed']
            freeze = {'selection': selection, 'validation': validations, 'representative_seed': representative,
                      'matched_parameter': parameter, 'test_used_for_selection': False, 'test_already_observed': True}
            save_json(self.folder / 'final_freeze.json', freeze)
            test = np.load(self.root / 'data/processed/test_mask.npy')
            ids = np.flatnonzero(test)
            rows, reviews = [], []
            for recipe in candidates:
                for seed in self.settings['final_seeds']:
                    info, folder = self.fit(recipe, parameter, seed)
                    model = joblib.load(folder / 'model.pkl')
                    x = self.inputs(recipe, test)
                    p = calibrated_probability(weighted_probability_logits(model.predict_proba(x)[:, 1], info['positive_weight']), info['temperature'])
                    result = evaluate_predictions(self.roles.labels[test], p, info['threshold'])
                    result['review'] = review_metrics(self.roles.labels[test], p, self.settings['review_top_k'], self.settings['review_fractions'])
                    save_json(folder / 'test.json', result)
                    np.savez_compressed(folder / 'test_predictions.npz', node_idx=ids, probability=p)
                    rows.append({'candidate': recipe, 'seed': seed, **{k: result[k] for k in ['pr_auc', 'f1', 'precision', 'recall', 'roc_auc', 'brier_score']}})
                    for budget, counts in result['review'].items():
                        reviews.append({'candidate': recipe, 'seed': seed, 'budget': budget, **counts})
            pd.DataFrame(rows).to_csv(self.folder / 'final_comparison.csv', index=False)
            pd.DataFrame(reviews).to_csv(self.folder / 'review_all_seeds.csv', index=False)
            final = {**freeze, 'dataset_fingerprint': self.roles.metadata['fingerprint'],
                     'seed_note': 'Only randomized recipe uses genuine stochastic subsampling; other configurations may be identical'}
            save_json(path, final)
            return final
