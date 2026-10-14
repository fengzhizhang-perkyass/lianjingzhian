from pathlib import Path
import shutil
import numpy as np
import pandas as pd
import pytest
import torch
from src.data.preprocess import preprocess, split_nodes
from src.utils.io import ROOT, read_json


@pytest.fixture
def dataset_root(tmp_path):
    (tmp_path / "config").mkdir()
    shutil.copy(ROOT / "config/data.yaml", tmp_path / "config/data.yaml")
    raw = tmp_path / "data/raw"
    raw.mkdir(parents=True)
    features, labels, edges = [], [], []
    for step in range(1, 21):
        for label in (1, 2, 3):
            address = f"S{step}C{label}"
            features.append({"address": address, "Time step": step, "feature_a": step*label,
                             "feature_b": np.nan if label == 3 else label})
            labels.append({"address": address, "class": label})
            edges.append({"input_address": address, "output_address": f"S{min(step+1, 20)}C{label}"})
    pd.DataFrame(features).to_csv(raw / "wallets_features.csv", index=False)
    pd.DataFrame(labels).to_csv(raw / "wallets_classes.csv", index=False)
    pd.DataFrame(edges).to_csv(raw / "AddrAddr_edgelist.csv", index=False)
    return tmp_path


def test_preprocessing_masks_mapping_and_scaler(dataset_root):
    metadata = preprocess(dataset_root)
    folder = dataset_root / "data/processed"
    labels = np.load(folder / "labels.npy")
    masks = [np.load(folder / f"{phase}_mask.npy") for phase in ("train", "val", "test")]
    assert metadata["num_nodes"] == 60 and metadata["num_edges"] > 0
    assert not np.logical_or.reduce(masks)[labels == -1].any()
    assert not (masks[0] & masks[1]).any()
    features = np.load(folder / "features.npy")
    assert np.isfinite(features).all()
    assert np.allclose(features[masks[0]].mean(0), 0, atol=1e-5)
    assert abs(features[masks[2], 0].mean()) > 0.1
    mapping = read_json(folder / "address_to_idx.json")
    reverse = read_json(folder / "idx_to_address.json")
    assert all(reverse[str(i)] == a for a, i in mapping.items())
    directed = torch.load(folder / "edge_index_directed.pt", weights_only=True)
    model = torch.load(folder / "edge_index.pt", weights_only=True)
    pairs = set(map(tuple, model.T.tolist()))
    assert all((v, u) in pairs for u, v in directed.T.tolist())


def test_conflicting_labels_rejected(dataset_root):
    path = dataset_root / "data/raw/wallets_classes.csv"
    frame = pd.read_csv(path)
    bad = frame.iloc[[0]].copy()
    bad["class"] = 2
    pd.concat([frame, bad]).to_csv(path, index=False)
    with pytest.raises(ValueError, match="Conflicting"):
        preprocess(dataset_root)


def test_stratified_unknown_is_excluded():
    labels = np.array([0]*60+[1]*60+[-1]*10)
    masks, metadata = split_nodes(labels, None, [.7, .15, .15], 42)
    assert metadata["method"] == "stratified"
    assert sum(m.sum() for m in masks) == 120
    assert not any(m[-10:].any() for m in masks)
