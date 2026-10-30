"""Frozen-model probability postprocessing, independent from score formatting.

No model fitting or label loading occurs in a web request. Missing/unqualified
calibration data uses an explicitly described identity map, never fake scaling.
"""
from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import math

import numpy as np


def stable_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False, separators=(',', ':')).encode()).hexdigest()


def model_signature(dataset_id, manifest):
    paths = ([manifest['model_path']] if manifest.get('model_path') else
             list(manifest.get('model_paths', {}).values()))
    hashes = manifest.get('source_hashes', {})
    return stable_digest({'dataset_id': dataset_id,
                          'fingerprint': manifest.get('fingerprint'),
                          'feature_revision': manifest.get('feature_revision'),
                          'model_hashes': {p: hashes.get(p) for p in sorted(paths)}})


def _parameters(mode, values):
    if not isinstance(values, dict):
        raise ValueError('Calibration parameters must be a mapping')
    expected = {'identity': set(), 'temperature': {'temperature'}, 'sigmoid': {'slope', 'intercept'}}
    if mode not in expected or set(values) != expected[mode]:
        raise ValueError('Unsupported calibration mode or parameters')
    if any(type(v) not in (float, int) or not math.isfinite(v) for v in values.values()):
        raise ValueError('Calibration parameters must be finite numbers')
    if mode == 'temperature' and values['temperature'] <= 0:
        raise ValueError('Calibration temperature must be positive')
    if mode == 'sigmoid' and values['slope'] <= 0:
        raise ValueError('Calibration slope must be positive to preserve ordering')
    return values


def apply_calibration_descriptor(probability, descriptor):
    """Recompute the postprocessed probability from the actual raw probability."""
    if not isinstance(descriptor, dict):
        raise ValueError('Missing calibration descriptor')
    mode = descriptor.get('mode')
    params = _parameters(mode, descriptor.get('parameters', {}))
    values = np.asarray(probability, dtype=np.float64)
    if not np.isfinite(values).all() or np.any((values < 0) | (values > 1)):
        raise ValueError('Raw probabilities must be finite and within [0,1]')
    if mode == 'identity':
        result = values.copy()
    else:
        # Endpoints remain honest endpoints. Clip only interior log computation,
        # never invent a display-friendly cap or change the frozen raw values.
        with np.errstate(divide='ignore', over='ignore'):
            logits = np.log(values) - np.log1p(-values)
            if mode == 'temperature':
                logits = logits / params['temperature']
            else:
                logits = params['slope'] * logits + params['intercept']
            result = np.exp(-np.logaddexp(0., -logits))
    if not np.isfinite(result).all():
        raise ValueError('Calibration produced non-finite probabilities')
    return float(result) if values.ndim == 0 else result


@dataclass(frozen=True)
class ProbabilityCalibration:
    record: dict

    @property
    def revision(self):
        return stable_digest(self.record)

    def apply(self, probability):
        return apply_calibration_descriptor(probability, self.record)

    def describe(self, raw_probability=None):
        result = {key: self.record[key] for key in ('dataset_id', 'mode', 'status', 'parameters')}
        result.update(revision=self.revision, model_signature=self.record['model_signature'])
        if raw_probability is not None:
            result.update(raw_probability=float(raw_probability),
                          calibrated_probability=float(self.apply(raw_probability)))
        return result


def load_calibration(root, dataset_id, manifest):
    """Load a source-bound prepared release; no implicit fit, split or download."""
    signature = model_signature(dataset_id, manifest)
    path = Path(root)/'artifacts/calibration'/dataset_id/'current/manifest.json'
    if not path.exists():
        return ProbabilityCalibration({'dataset_id': dataset_id, 'model_signature': signature,
                                       'mode': 'identity', 'status': 'not_audited', 'parameters': {}})
    record = json.loads(path.read_text())
    if record.get('dataset_id') != dataset_id or record.get('model_signature') != signature:
        raise ValueError('Calibration release does not match the frozen model inputs')
    _parameters(record.get('mode'), record.get('parameters', {}))
    if record.get('status') not in ('needs_data', 'not_needed', 'enabled'):
        raise ValueError('Unqualified calibration release status')
    if record['mode'] != 'identity':
        evidence = record.get('qualification', {})
        required = ('base_model_frozen', 'original_splits_unchanged', 'fit_disjoint_from_base_training',
                    'check_disjoint_from_fit', 'test_not_used_for_fitting_or_selection',
                    'independent_check_improved')
        if record['status'] != 'enabled' or any(evidence.get(k) is not True for k in required):
            raise ValueError('Postprocessing lacks independent-data qualification')
    elif record['status'] == 'enabled':
        raise ValueError('Identity must not be advertised as enabled calibration')
    audit = path.with_name('audit.json')
    if not audit.is_file() or hashlib.sha256(audit.read_bytes()).hexdigest() != record.get('audit_sha256'):
        raise ValueError('Calibration audit hash mismatch')
    return ProbabilityCalibration(record)
