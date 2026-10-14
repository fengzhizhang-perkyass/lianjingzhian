"""Train pointwise evidence routing over cached graph filters, on CPU."""
import hashlib
import json
import time
import numpy as np
import pandas as pd
import torch
from torch.utils.data import TensorDataset, DataLoader
from sklearn.metrics import average_precision_score
from filelock import FileLock
from src.model.multievidence_model import MultiEvidenceModel
from src.model.calibration import fit_temperature, calibrated_probability
from src.train.graph_signal_experiments import GraphSignalExperiment
from src.train.evaluate import evaluate_predictions, choose_threshold
from src.train.risk_experiments import review_metrics
from src.utils.io import ROOT, load_config, read_json, save_json, file_sha256
from src.utils.seed import set_seed
from src.utils.logging import get_logger


class MultiEvidenceExperiment:
    def __init__(self, root=ROOT):
        self.root = root
        self.settings = load_config('multievidence_experiments.yaml', root)['experiment']
        self.signals = GraphSignalExperiment(root)
        self.roles = self.signals.roles
        self.folder = root / 'artifacts/experiments' / self.settings['name']
        self.logger = get_logger('multievidence_experiments', root)
        manifest = {'settings': self.settings, 'dataset_fingerprint': self.roles.metadata['fingerprint'],
                    'signal_manifest_sha256': file_sha256(self.signals.folder / 'manifest.json'),
                    'model_sha256': file_sha256(root / 'src/model/multievidence_model.py'),
                    'test_already_observed': True, 'selection_uses_test': False}
        path = self.folder / 'manifest.json'
        if path.exists() and read_json(path) != manifest:
            raise RuntimeError('Multi-evidence settings changed; use a new experiment name')
        save_json(path, manifest)

    def inputs(self, candidate, mask, fold, cutoff):
        cache = self.signals.cache(fold, cutoff)
        return [np.column_stack([self.roles.structure(cutoff)[mask] if block == 'structure' else
                                 np.load(cache / f'{block}.npy', mmap_mode='r')[mask]
                                 for block in self.settings['routes'][route]])
                for route in self.settings['candidates'][candidate]['routes']]

    def normalize(self, xs, states):
        return [torch.from_numpy(np.clip((x-np.array(state['mean'], dtype=np.float32))/np.array(state['scale'], dtype=np.float32),
                                       -self.settings['signal_clip'], self.settings['signal_clip']).astype(np.float32))
                for x, state in zip(xs, states)]

    def model(self, candidate, dims):
        return MultiEvidenceModel(dims, self.settings['hidden_dim'], self.settings['embedding_dim'], self.settings['dropout'],
                                  self.settings['candidates'][candidate]['fusion'])

    @torch.no_grad()
    def predict(self, model, xs):
        model.eval()
        outputs = {'logits': [], 'route_logits': [], 'weights': []}
        for start in range(0, len(xs[0]), self.settings['batch_size']):
            batch = [x[start:start+self.settings['batch_size']] for x in xs]
            result = model(batch)
            for key in outputs:
                outputs[key].append(result[key].numpy())
        return {k: np.concatenate(v) for k, v in outputs.items()}

    def fit(self, candidate, seed, fold=None):
        name = f"development/{fold['name']}/{candidate}" if fold else f'final/{candidate}/seed_{seed}'
        folder = self.folder / name
        if (folder / 'validation.json').exists():
            return read_json(folder / 'validation.json')
        set_seed(seed, self.settings['torch_threads'])
        train, val = self.roles.masks(fold)
        split = fold or self.roles.metadata['split']
        xtrain = self.inputs(candidate, train, fold, split['train_end'])
        states = []
        for x in xtrain:
            mean = x.mean(axis=0); scale = x.std(axis=0); scale[scale < 1e-6] = 1
            states.append({'mean': mean.tolist(), 'scale': scale.tolist()})
        xt = self.normalize(xtrain, states)
        del xtrain
        xv = self.normalize(self.inputs(candidate, val, fold, split['val_end']), states)
        ytrain = torch.from_numpy(self.roles.labels[train].astype(np.float32))
        yval = self.roles.labels[val]
        if (ytrain < 0).any():
            raise RuntimeError('Unknown label entered training')
        dims = [x.shape[1] for x in xt]
        model = self.model(candidate, dims)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.settings['learning_rate'], weight_decay=self.settings['weight_decay'])
        weight = float((ytrain == 0).sum()/(ytrain == 1).sum())
        criterion = torch.nn.BCEWithLogitsLoss(pos_weight=torch.tensor(weight))
        loader = DataLoader(TensorDataset(*xt, ytrain), batch_size=self.settings['batch_size'], shuffle=True,
                            generator=torch.Generator().manual_seed(seed), num_workers=0)
        history, best, stale, best_state = [], -1, 0, None
        started = time.monotonic()
        for epoch in range(self.settings['epochs']):
            model.train()
            total, count = 0., 0
            for batch in loader:
                xs, y = batch[:-1], batch[-1]
                optimizer.zero_grad()
                output = model(xs)
                loss = criterion(output['logits'], y)
                if len(xs) > 1:
                    loss = loss+self.settings['auxiliary_weight']*sum(criterion(output['route_logits'][:, i], y) for i in range(len(xs)))
                if not torch.isfinite(loss):
                    raise RuntimeError('Non-finite evidence model loss')
                loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), self.settings['gradient_clip'])
                optimizer.step()
                total += float(loss.detach())*len(y); count += len(y)
            output = self.predict(model, xv)
            ap = float(average_precision_score(yval, output['logits']))
            record = {'epoch': epoch+1, 'loss': total/count, 'validation_ap': ap, 'mean_weights': output['weights'].mean(0).tolist()}
            history.append(record)
            self.logger.info('%s epoch %d AP %.4f', name, epoch+1, ap)
            if ap > best:
                best, stale = ap, 0
                best_state = {k: v.detach().clone() for k, v in model.state_dict().items()}
            else:
                stale += 1
            if stale >= self.settings['patience']:
                break
        model.load_state_dict(best_state)
        output = self.predict(model, xv)
        logits = output['logits']-np.log(weight)
        t = fit_temperature(logits, yval)
        probability = calibrated_probability(logits, t)
        route_calibration = []
        for i in range(len(dims)):
            route_z = output['route_logits'][:, i]-np.log(weight)
            rt = fit_temperature(route_z, yval)
            rp = calibrated_probability(route_z, rt)
            route_calibration.append({'temperature': rt, 'threshold': choose_threshold(yval, rp)})
        info = {'candidate': candidate, 'seed': seed, 'validation_ap': best, 'temperature': t,
                'threshold': choose_threshold(yval, probability), 'positive_weight': weight,
                'route_calibration': route_calibration, 'input_dims': dims, 'normalization': states,
                'epochs_run': len(history), 'best_epoch': max(history, key=lambda r: r['validation_ap'])['epoch'],
                'seconds': time.monotonic()-started, 'routes': self.settings['candidates'][candidate]['routes']}
        folder.mkdir(parents=True, exist_ok=True)
        torch.save({'state_dict': best_state, 'input_dims': dims, 'candidate': candidate,
                    'settings': self.settings, 'dataset_fingerprint': self.roles.metadata['fingerprint']}, folder / 'model.pt')
        np.savez_compressed(folder / 'validation_predictions.npz', node_idx=np.flatnonzero(val), logits=logits,
                            probability=probability, weights=output['weights'], route_logits=output['route_logits']-np.log(weight))
        save_json(folder / 'validation.json', info)
        save_json(folder / 'history.json', history)
        return info

    def development(self):
        path = self.folder / 'selection.json'
        if path.exists():
            return read_json(path)
        rows = []
        for fold in self.settings['folds']:
            for candidate in self.settings['candidates']:
                result = self.fit(candidate, self.settings['seed'], fold)
                rows.append({'candidate': candidate, 'fold': fold['name'], 'ap': result['validation_ap'], 'seconds': result['seconds']})
                pd.DataFrame(rows).to_csv(self.folder / 'development.csv', index=False)
        means = pd.DataFrame(rows).groupby('candidate').ap.agg(['mean', 'min'])
        best = means.sort_values(['mean', 'min'], ascending=False, kind='stable').index[0]
        selection = {'candidate': best, 'mean_development_ap': float(means.loc[best, 'mean']),
                     'rule': 'highest mean development AP, then worst fold', 'test_used_for_selection': False,
                     'development_candidates': means.reset_index().to_dict(orient='records')}
        save_json(path, selection)
        return selection

    def final(self):
        with FileLock(str(self.folder / 'experiment.lock'), timeout=5):
            selection = self.development()
            path = self.folder / 'final_summary.json'
            if path.exists():
                return read_json(path)
            candidates = list(dict.fromkeys([selection['candidate'], 'behavior_only', 'context_only', 'contrast_only']))
            validations = []
            for candidate in candidates:
                for seed in self.settings['final_seeds']:
                    info = self.fit(candidate, seed)
                    validations.append({k: info[k] for k in ['candidate', 'seed', 'validation_ap']})
            representative = max([r for r in validations if r['candidate'] == selection['candidate']], key=lambda r: r['validation_ap'])['seed']
            freeze = {'selection': selection, 'final_candidates': candidates, 'validation': validations,
                      'representative_seed': representative, 'test_used_for_selection': False, 'test_already_observed': True}
            save_json(self.folder / 'final_freeze.json', freeze)
            test = np.load(self.root / 'data/processed/test_mask.npy')
            ids = np.flatnonzero(test)
            rows, reviews = [], []
            for candidate in candidates:
                for seed in self.settings['final_seeds']:
                    folder = self.folder / f'final/{candidate}/seed_{seed}'
                    info = read_json(folder / 'validation.json')
                    model = self.model(candidate, info['input_dims'])
                    model.load_state_dict(torch.load(folder / 'model.pt', weights_only=True)['state_dict'])
                    xs = self.normalize(self.inputs(candidate, test, None, None), info['normalization'])
                    output = self.predict(model, xs)
                    probability = calibrated_probability(output['logits']-np.log(info['positive_weight']), info['temperature'])
                    result = evaluate_predictions(self.roles.labels[test], probability, info['threshold'])
                    result['review'] = review_metrics(self.roles.labels[test], probability, self.settings['review_top_k'], self.settings['review_fractions'])
                    save_json(folder / 'test.json', result)
                    np.savez_compressed(folder / 'test_predictions.npz', node_idx=ids, probability=probability,
                                        weights=output['weights'], route_logits=output['route_logits']-np.log(info['positive_weight']))
                    rows.append({'candidate': candidate, 'seed': seed, **{k: result[k] for k in ['pr_auc', 'f1', 'precision', 'recall', 'roc_auc', 'brier_score']}})
                    for budget, counts in result['review'].items():
                        reviews.append({'candidate': candidate, 'seed': seed, 'budget': budget, **counts})
            pd.DataFrame(rows).to_csv(self.folder / 'final_comparison.csv', index=False)
            pd.DataFrame(reviews).to_csv(self.folder / 'review_all_seeds.csv', index=False)
            save_json(path, freeze)
            return freeze
