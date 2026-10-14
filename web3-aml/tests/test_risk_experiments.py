import numpy as np
import pytest
import torch

from src.model.feature_transform import fit_feature_transform, transform_features
from src.model.dual_view_model import DualViewModel
from src.utils.io import load_config
from src.train.risk_experiments import chronological_masks, review_metrics
from src.train.risk_experiments import RiskExperiment
from torch_geometric.data import Data
from src.inference.risk_predictor import RiskPredictor
from src.inference.precompute_scores import load_model
from src.explain.behavior_explainer import BehaviorLogit
from src.utils.io import save_json, file_sha256
from src.model.calibration import correct_weighted_bce_heads, weighted_probability_logits


def test_transform_fits_training_only_and_round_trips_state():
    raw = np.array([[0., np.nan], [2., 4.], [1e12, 1e12]])
    state = fit_feature_transform(raw, [True, True, False], ["a", "b"],
                                  {"method": "signed_log", "standardized_clip": 8})
    assert state["medians"] == [1., 4.]
    assert state["fit_nodes"] == 2
    result = transform_features(raw, state)
    assert np.allclose(result[:2].mean(axis=0), 0)
    assert np.isfinite(result).all() and np.abs(result).max() <= 8
    assert raw[2, 0] == 1e12
    single_row_chunks = transform_features(raw, {**state, "transform_chunk_rows": 1})
    assert np.array_equal(single_row_chunks, result)


def test_exclusions_preserve_feature_indices():
    state = fit_feature_transform(np.array([[1., 2.], [3., 4.]]), [True, True], ["height", "count"],
                                  {"exclude_features": ["height"]})
    result = transform_features(np.array([[1e9, 2.]]), state)
    assert result.shape == (1, 2) and result[0, 0] == 0
    with pytest.raises(ValueError):
        fit_feature_transform(np.zeros((2, 2)), [True, True], ["a", "b"], {"exclude_features": ["absent"]})


def test_fixed_fusion_is_an_explicit_ablation_and_normalization_has_gradients():
    config = {**load_config("model.yaml")["model"], "embedding_normalization": "layernorm",
              "fusion_mode": "fixed", "fixed_behavior_weight": .5}
    model = DualViewModel(4, config)
    result = model(torch.randn(6, 4), torch.tensor([[0, 1, 2], [1, 2, 3]]))
    assert torch.equal(result["gate"], torch.full((6,), .5))
    result["fused_logits"].sum().backward()
    assert model.behavior_norm.weight.grad is not None and model.graph_norm.weight.grad is not None


def test_old_checkpoint_architecture_remains_compatible():
    config = load_config("model.yaml")["model"]
    model = DualViewModel(4, config)
    assert not any("_norm" in key for key in model.state_dict())


def test_inner_chronological_split_excludes_unknown_and_later_labels():
    labels = np.array([0, 1, -1, 0, 1, 0, 1])
    train, val = chronological_masks(labels, np.array([1, 1, 1, 2, 2, 3, 3]), 1, 2)
    assert np.array_equal(np.flatnonzero(train), [0, 1])
    assert np.array_equal(np.flatnonzero(val), [3, 4])
    assert not (train & val).any()


def test_review_budget_uses_ranking_and_actual_positive_count():
    result = review_metrics(np.array([0, 1, 1, 0]), np.array([.1, .9, .8, .2]), [2], [.5])
    assert result["top_2"] == {"reviewed": 2, "illicit_found": 2, "precision": 1., "recall": 1.}
    assert result["top_0.5_fraction"] == result["top_2"]


def test_new_checkpoint_and_behavior_explanation_share_normalized_encoder(tmp_path):
    model_config = {**load_config("model.yaml")["model"], "embedding_normalization": "layernorm"}
    model = DualViewModel(4, model_config).eval()
    folder = tmp_path / "artifacts/model"
    folder.mkdir(parents=True)
    torch.save({"state_dict": model.state_dict(), "config": {"model": model_config},
                "input_dim": 4, "mode": "dual_view", "dataset_fingerprint": "test"}, folder / "dual_view_model.pt")
    save_json(tmp_path / "data/processed/metadata.json", {"fingerprint": "test"})
    loaded, _ = load_model(tmp_path)
    x = torch.randn(3, 4)
    assert torch.allclose(BehaviorLogit(loaded)(x), loaded.behavior_head(loaded.encode_behavior(x)).flatten())


def test_risk_table_rejects_changed_model_even_on_the_same_dataset(tmp_path):
    import pandas as pd
    folder = tmp_path / "artifacts/risk_scores"
    folder.mkdir(parents=True)
    model_path = tmp_path / "artifacts/model/dual_view_model.pt"
    model_path.parent.mkdir(parents=True)
    model_path.write_bytes(b"first model")
    pd.DataFrame({"address_id": ["A"], "node_idx": [0]}).to_parquet(folder / "risk_scores.parquet")
    save_json(folder / "metadata.json", {"dataset_fingerprint": "test", "model_sha256": file_sha256(model_path)})
    save_json(tmp_path / "data/processed/metadata.json", {"fingerprint": "test"})
    assert RiskPredictor(tmp_path).resolve("A") == "A"
    model_path.write_bytes(b"different model")
    with pytest.raises(RuntimeError, match="different model"):
        RiskPredictor(tmp_path)


def test_weighted_bce_odds_correction_preserves_gate_and_logit_order():
    model = DualViewModel(4, load_config("model.yaml")["model"]).eval()
    x, edges = torch.randn(6, 4), torch.tensor([[0, 1, 2], [1, 2, 3]])
    before = model(x, edges)
    correction = correct_weighted_bce_heads(model, 9)
    after = model(x, edges)
    assert torch.equal(before["gate"], after["gate"])
    for key in ("behavior_logits", "graph_logits", "fused_logits"):
        assert torch.allclose(after[key], before[key] - np.log(9), atol=1e-6)
        assert torch.equal(before[key].argsort(), after[key].argsort())
    assert correction["logit_offset"] == pytest.approx(np.log(9))


def test_weighted_probability_recovers_original_probability():
    # Weighted CE multiplies true odds by the positive weight.
    true = np.array([.01, .1, .5, .9])
    weighted = 9*true/(1-true+9*true)
    corrected = weighted_probability_logits(weighted, 9)
    recovered = 1/(1+np.exp(-corrected))
    assert np.allclose(recovered, true)


def test_export_correction_is_idempotent_and_recovers_interrupted_calibration(tmp_path):
    config = load_config("model.yaml")
    config["training"]["loss"] = "bce"
    model = DualViewModel(4, config["model"], "behavior")
    run_id = "final/behavior/seed_42"
    folder = tmp_path / run_id
    folder.mkdir(parents=True)
    torch.save({"state_dict": model.state_dict(), "input_dim": 4, "config": config, "mode": "behavior"}, folder / "model.pt")
    save_json(folder / "validation.json", {"validation_ap": .5, "temperature": 1., "best_epoch": 1})
    save_json(folder / "calibration.json", {"temperature": 1., "threshold": .5})
    experiment = object.__new__(RiskExperiment)
    experiment.folder = tmp_path
    experiment.metadata = {"split": {"method": "stratified"}}
    experiment.data = Data(x=torch.randn(6, 4), y=torch.tensor([0, 0, 0, 1, 0, 1]),
                           edge_index=torch.tensor([[0, 1, 2], [1, 2, 3]]),
                           train_mask=torch.tensor([True]*4+[False]*2),
                           val_mask=torch.tensor([False]*4+[True]*2))
    experiment.calibrate_final_export(run_id)
    first = torch.load(folder / "model.pt", weights_only=True)
    first_hash = file_sha256(folder / "model.pt")
    experiment.calibrate_final_export(run_id)
    assert file_sha256(folder / "model.pt") == first_hash
    # Simulate a lost sidecar: replay validation, but never subtract the weight twice.
    save_json(folder / "calibration.json", {"temperature": 1., "threshold": .5})
    experiment.calibrate_final_export(run_id)
    replayed = torch.load(folder / "model.pt", weights_only=True)
    assert torch.equal(replayed["state_dict"]["fusion_head.bias"], first["state_dict"]["fusion_head.bias"])
