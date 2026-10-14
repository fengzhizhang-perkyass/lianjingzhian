import numpy as np
import pytest
import torch
from torch_geometric.data import Data

from src.model.dual_view_model import DualViewModel
from src.train.diagnostics import collect_diagnostics, feature_summary, probability_summary
from src.utils.io import load_config


def test_saturation_and_calibration_do_not_change_logit_ranking():
    labels = np.array([0, 0, 1, 1])
    logits = np.array([-100., -1., 1., 100.])
    raw = probability_summary(labels, logits, 1, .01, 10)
    scaled = probability_summary(labels, logits, .5, .01, 10)
    assert raw["logit_ap"] == scaled["logit_ap"] == 1
    assert raw["low_saturation_fraction"] == raw["high_saturation_fraction"] == .25
    assert 0 <= raw["ece"] <= 1


def test_feature_audit_reports_extremes_by_column():
    summary = feature_summary(np.array([[0., 20.], [0., -30.]]), ["stable", "extreme"], 10, 1)
    assert summary["top_extreme_features"][0]["feature"] == "extreme"
    assert summary["rows_with_extreme_features_fraction"] == 1
    with pytest.raises(ValueError):
        feature_summary(np.array([[np.nan]]), ["invalid"], 10, 1)


def test_audit_captures_seed_embeddings_and_removes_hooks():
    config = load_config("model.yaml")
    data = Data(x=torch.randn(6, 4), y=torch.tensor([0, 1, 0, 1, -1, -1]),
                edge_index=torch.tensor([[0, 1, 2, 3, 4], [1, 2, 3, 4, 5]]))
    model = DualViewModel(4, config["model"])
    before = torch.get_rng_state().clone()
    result = collect_diagnostics(model, data, {"split": {"method": "stratified"}},
                                 torch.tensor([0, 1, 2]), config, "val", torch.device("cpu"))
    assert torch.equal(before, torch.get_rng_state())
    assert np.array_equal(result["node_idx"], [0, 1, 2])
    assert result["behavior_embedding_norm"].shape == result["graph_embedding_norm"].shape == (3,)
    assert not model.behavior_encoder._forward_hooks and not model.graph_encoder._forward_hooks
