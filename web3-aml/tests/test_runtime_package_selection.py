import importlib.util
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
from package_runtime_data import runtime_file_names


def prepare(root, feature='artifacts/evidence_scoring/features.npy'):
    for name in ['artifacts/evidence_scoring/features.npy',
                 'artifacts/risk_scores/graph_statistics.parquet',
                 'data/processed/raw_features.npy']:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'toy')
    (root / 'artifacts/risk_scores/metadata.json').write_text(json.dumps({'features_path': feature}))


def test_original_input_is_not_duplicated(tmp_path):
    prepare(tmp_path)
    assert len(runtime_file_names(tmp_path)) == 3


def test_new_active_input_is_included(tmp_path):
    prepare(tmp_path, 'model_upgrade/selected/features.npy')
    path = tmp_path / 'model_upgrade/selected/features.npy'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'new feature input')
    assert runtime_file_names(tmp_path)[-1] == 'model_upgrade/selected/features.npy'


@pytest.mark.parametrize('value', ['../../outside.npy', '/tmp/outside.npy', '', '.'])
def test_unsafe_input_is_rejected(tmp_path, value):
    prepare(tmp_path, value)
    with pytest.raises(ValueError):
        runtime_file_names(tmp_path)


def test_missing_active_input_is_rejected(tmp_path):
    prepare(tmp_path, 'missing.npy')
    with pytest.raises(ValueError, match='Missing'):
        runtime_file_names(tmp_path)
