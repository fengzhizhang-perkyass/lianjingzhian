"""Actual binary tree backends; all attributions are uncalibrated raw-margin units.

Use load_native_tree(path, backend='lightgbm_joblib'|'xgboost_ubj',
expected_features=N). The returned object offers predict_probability(X),
raw_margin(X), and tree_shap(X) (feature columns followed by the bias column).
No class-weight correction, thresholding or temperature scaling is applied.
"""
from pathlib import Path
import json

import joblib
import numpy as np


class NativeTree:
    """Explicit native backend; never impersonates an sklearn booster_ API."""

    def __init__(self, model, backend, n_features):
        self._model, self.backend, self.n_features = model, backend, int(n_features)
        self.shap_tolerance = {'lightgbm_joblib': 1e-5, 'xgboost_ubj': 2e-4}[backend]

    def _rows(self, values):
        rows = np.asarray(values, dtype=np.float32)
        if rows.ndim != 2 or rows.shape[1] != self.n_features or not len(rows) or not np.isfinite(rows).all():
            raise ValueError('Native tree inputs require nonempty finite rows with the actual model width')
        return rows

    def _predict(self, rows, mode):
        if self.backend == 'lightgbm_joblib':
            return self._model.predict(rows, raw_score=mode == 'margin', pred_contrib=mode == 'shap', num_threads=1)
        import xgboost as xgb  # Optional dependency, never imported for LightGBM.
        return self._model.predict(xgb.DMatrix(rows, nthread=1), output_margin=mode == 'margin',
            pred_contribs=mode == 'shap', approx_contribs=False, validate_features=True)

    @staticmethod
    def _finite_shape(values, shape):
        result = np.asarray(values)
        if result.shape != shape or not np.isfinite(result).all():
            raise RuntimeError('Native tree output shape or finite-value contract failed')
        return result

    def predict_probability(self, values):
        rows = self._rows(values)
        probability = self._finite_shape(self._predict(rows, 'probability'), (len(rows),))
        if np.any((probability < 0) | (probability > 1)):
            raise RuntimeError('Binary native probability must lie in [0,1]')
        return probability

    def raw_margin(self, values):
        rows = self._rows(values)
        return self._finite_shape(self._predict(rows, 'margin'), (len(rows),))

    def tree_shap(self, values):
        rows = self._rows(values)
        contributions = self._finite_shape(self._predict(rows, 'shap'), (len(rows), self.n_features+1))
        margin = self._finite_shape(self._predict(rows, 'margin'), (len(rows),))
        # Accumulate in float64; XGBoost contributions themselves are float32.
        residual = np.abs(contributions.sum(axis=1, dtype=np.float64)-margin.astype(np.float64))
        if np.any(residual > self.shap_tolerance):
            raise RuntimeError('Actual native TreeSHAP does not reconstruct its own raw margin')
        return contributions


def load_native_tree(filename, *, backend, expected_features=None):
    """Load trusted local artifacts with an explicit format and CPU native model.

    joblib inputs, like the existing application models, must be trusted files.
    expected_features is a schema-width assertion, never a tolerance override.
    """
    if backend not in {'lightgbm_joblib', 'xgboost_ubj'}:
        raise ValueError('Unknown native tree backend')
    if expected_features is not None and (type(expected_features) is not int or expected_features <= 0):
        raise ValueError('Expected feature width must be a positive integer')
    filename = Path(filename)
    if backend == 'lightgbm_joblib':
        import lightgbm as lgb
        estimator = joblib.load(filename)
        if not isinstance(estimator, lgb.LGBMClassifier) or not np.array_equal(estimator.classes_, [0, 1]):
            raise ValueError('Require an actual binary LightGBM classifier with classes[0,1]')
        native = estimator.booster_
        if native.params.get('objective') != 'binary' or float(native.params.get('sigmoid', 1.)) != 1. or native.num_model_per_iteration() != 1:
            raise ValueError('Require one binary LightGBM margin with identity logistic link')
        n_features = native.num_feature()
    else:
        import xgboost as xgb
        if xgb.__version__ != '2.1.4':
            raise RuntimeError('This native UBJ backend is validated for XGBoost2.1.4')
        native = xgb.Booster(params={'device': 'cpu', 'nthread': 1})
        native.load_model(filename)
        native.set_param({'device': 'cpu', 'nthread': 1})
        config = json.loads(native.save_config())['learner']
        if config['objective']['name'] != 'binary:logistic' or int(config['learner_model_param']['num_class']) != 0:
            raise ValueError('Require an actual binary:logistic XGBoost model')
        n_features = native.num_features()
    if n_features <= 0 or (expected_features is not None and n_features != expected_features):
        raise ValueError('Native model width differs from the expected schema')
    return NativeTree(native, backend, n_features)
