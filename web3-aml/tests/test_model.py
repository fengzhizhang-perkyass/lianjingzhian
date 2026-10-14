import numpy as np
import pytest
import torch
from src.model.dual_view_model import DualViewModel
from src.model.focal_loss import FocalLoss
from src.model.calibration import calibrated_probability, fit_temperature
from src.utils.io import load_config
from src.train.train import phase_data, predict_nodes
from torch_geometric.data import Data


@pytest.mark.parametrize("mode", ["dual_view", "behavior", "graphsage"])
def test_forward_and_gradient(mode):
    model = DualViewModel(4, load_config("model.yaml")["model"], mode)
    result = model(torch.randn(6, 4), torch.tensor([[0, 1, 2, 3], [1, 2, 3, 4]]))
    assert result["fused_logits"].shape == (6,)
    assert ((result["gate"] >= 0) & (result["gate"] <= 1)).all()
    probabilities = torch.sigmoid(result["fused_logits"])
    assert ((probabilities >= 0) & (probabilities <= 1)).all()
    loss = FocalLoss()(result["fused_logits"], torch.tensor([0, 1, 0, 1, 0, 1]))
    loss.backward()
    assert torch.isfinite(loss)
    assert model.fusion_head.weight.grad is not None


def test_temperature_is_positive_and_finite():
    logits, labels = np.array([-2, -1, 1, 2]*5), np.array([0, 1, 0, 1]*5)
    temperature = fit_temperature(logits, labels)
    assert 0 < temperature < float("inf")
    probs = calibrated_probability(logits, temperature)
    assert np.isfinite(probs).all() and ((probs >= 0) & (probs <= 1)).all()


def test_temporal_message_passing_excludes_future_edges():
    data = Data(x=torch.zeros(3, 2), y=torch.tensor([0, 1, -1]),
                edge_index=torch.tensor([[0, 1, 1, 2], [1, 0, 2, 1]]), timestep=torch.tensor([1., 2., 3.]))
    metadata = {"split": {"method": "time", "train_end": 2, "val_end": 3}}
    assert phase_data(data, metadata, "train").edge_index.shape[1] == 2
    assert phase_data(data, metadata, "test").edge_index.shape[1] == 4


def test_validation_sampling_preserves_training_random_stream():
    cfg = load_config("model.yaml")
    graph = Data(x=torch.randn(6, 4), y=torch.tensor([0, 1, 0, 1, -1, -1]),
                 edge_index=torch.tensor([[0, 1, 2, 3, 4], [1, 2, 3, 4, 5]]))
    model = DualViewModel(4, cfg["model"])
    before = torch.get_rng_state().clone()
    first = predict_nodes(model, graph, {"split": {"method": "stratified"}}, torch.tensor([0, 1, 2]), cfg, torch.device("cpu"))
    assert torch.equal(before, torch.get_rng_state())
    second = predict_nodes(model, graph, {"split": {"method": "stratified"}}, torch.tensor([0, 1, 2]), cfg, torch.device("cpu"))
    assert np.array_equal(first["node_idx"], second["node_idx"])
    assert np.allclose(first["fused_logits"], second["fused_logits"])
