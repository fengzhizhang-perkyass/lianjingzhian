"""Real CPU native models and exact backend contracts; no project risk data."""
import builtins
import json

import joblib
import lightgbm as lgb
import numpy as np
import pytest

from src.inference.native_tree import load_native_tree


@pytest.fixture
def sample():
    rng = np.random.default_rng(42)
    x = rng.normal(size=(240, 8)).astype(np.float32)
    y = (x[:, 0]+.6*x[:, 1]-.2*x[:, 3] > .1).astype(int)
    return x, y


def train_lgb(tmp_path, sample):
    x, y = sample
    model = lgb.LGBMClassifier(n_estimators=35, num_leaves=7, min_child_samples=5,
        random_state=42, n_jobs=1, verbosity=-1).fit(x, y)
    filename = tmp_path/'model.pkl'
    joblib.dump(model, filename)
    return filename, model


@pytest.mark.parametrize('backend', ['lightgbm_joblib', 'xgboost_ubj'])
def test_actual_native_reload_probability_raw_units_and_treeshap(tmp_path, sample, backend):
    x, y = sample
    if backend == 'lightgbm_joblib':
        filename, original = train_lgb(tmp_path, sample)
        expected = original.predict_proba(x)[:, 1]
    else:
        xgb = pytest.importorskip('xgboost')
        original = xgb.train({'objective': 'binary:logistic', 'device': 'cpu',
            'tree_method': 'hist', 'max_depth': 3, 'seed': 42, 'nthread': 1},
            xgb.DMatrix(x, label=y), num_boost_round=35)
        filename = tmp_path/'model.ubj'
        original.save_model(filename)
        expected = original.predict(xgb.DMatrix(x))
    tree = load_native_tree(filename, backend=backend, expected_features=8)
    second = load_native_tree(filename, backend=backend, expected_features=8)
    p, margin, shap = tree.predict_probability(x), tree.raw_margin(x), tree.tree_shap(x)
    assert not hasattr(tree, 'booster_')
    assert np.array_equal(p, expected)
    assert np.array_equal(p, second.predict_probability(x))
    assert shap.shape == (240, 9)
    assert np.max(np.abs(shap.sum(axis=1, dtype=np.float64)-margin.astype(np.float64))) <= tree.shap_tolerance
    assert np.max(np.abs(p-1/(1+np.exp(-margin.astype(np.float64))))) < 1e-6
    assert tree.shap_tolerance == (1e-5 if backend == 'lightgbm_joblib' else 2e-4)
    if backend == 'xgboost_ubj':
        assert json.loads(tree._model.save_config())['learner']['generic_param']['device'] == 'cpu'
    with pytest.raises(ValueError, match='width'):
        load_native_tree(filename, backend=backend, expected_features=7)
    for invalid in [x[:, :7], x[0], np.empty((0, 8)), np.full((1, 8), np.nan)]:
        with pytest.raises(ValueError):
            tree.tree_shap(invalid)


def test_lightgbm_works_when_xgboost_import_is_unavailable(tmp_path, sample, monkeypatch):
    filename, _ = train_lgb(tmp_path, sample)
    original = builtins.__import__
    def guard(name, *args, **kwargs):
        if name == 'xgboost' or name.startswith('xgboost.'):
            raise ImportError('XGBoost deliberately unavailable')
        return original(name, *args, **kwargs)
    monkeypatch.setattr(builtins, '__import__', guard)
    model = load_native_tree(filename, backend='lightgbm_joblib')
    assert model.tree_shap(sample[0]).shape == (240, 9)
    assert model.predict_probability(sample[0]).shape == (240,)


def test_unknown_backend_and_noninteger_width_rejected_without_loading(tmp_path):
    with pytest.raises(ValueError, match='Unknown'):
        load_native_tree(tmp_path/'missing', backend='pretend_lgb')
    for width in [0, -1, True, 8.0]:
        with pytest.raises(ValueError, match='positive integer'):
            load_native_tree(tmp_path/'missing', backend='lightgbm_joblib', expected_features=width)


def test_native_shap_cannot_hide_residual_or_bad_output(tmp_path, sample, monkeypatch):
    filename, _ = train_lgb(tmp_path, sample)
    model = load_native_tree(filename, backend='lightgbm_joblib')
    original = model._predict
    def wrong_margin(rows, mode):
        value = original(rows, mode)
        return value+.1 if mode == 'margin' else value
    monkeypatch.setattr(model, '_predict', wrong_margin)
    with pytest.raises(RuntimeError, match='reconstruct'):
        model.tree_shap(sample[0])
    monkeypatch.setattr(model, '_predict', lambda rows, mode: np.full((len(rows),), np.nan))
    with pytest.raises(RuntimeError, match='finite'):
        model.predict_probability(sample[0])
