from pathlib import Path
import numpy as np
import pandas as pd
import torch
from src.data.preprocess import load_processed
from src.model.dual_view_model import DualViewModel
from src.model.feature_transform import transform_features
from src.model.calibration import calibrated_probability
from src.train.train import predict_nodes
from src.utils.io import ROOT, read_json, save_json, file_sha256
from src.utils.logging import get_logger
from src.utils.seed import set_seed


def load_model(root: Path = ROOT):
    checkpoint = torch.load(root / "artifacts/model/dual_view_model.pt", map_location="cpu", weights_only=True)
    metadata = read_json(root / "data/processed/metadata.json")
    if checkpoint["dataset_fingerprint"] != metadata["fingerprint"]:
        raise RuntimeError("Model belongs to a different processed dataset. Retrain before inference.")
    model = DualViewModel(checkpoint["input_dim"], checkpoint["config"]["model"], checkpoint["mode"])
    model.load_state_dict(checkpoint["state_dict"])
    model.eval()
    return model, checkpoint["config"]


def risk_level(score, thresholds):
    if not 0 <= score <= 100:
        raise ValueError("Risk score must be within [0,100].")
    if score < thresholds["low"]:
        return "LOW"
    if score < thresholds["medium"]:
        return "MEDIUM"
    if score < thresholds["high"]:
        return "HIGH"
    return "CRITICAL"


def precompute(root: Path = ROOT):
    logger = get_logger("inference", root)
    model, config = load_model(root)
    set_seed(config["training"]["seed"], config["training"]["torch_threads"])
    data, metadata = load_processed(root)
    if config.get("input_transform"):
        data.x = torch.from_numpy(transform_features(np.load(root / "data/processed/raw_features.npy"), config["input_transform"]))
    config["graphsage"]["batch_size"] = config["graphsage"]["inference_batch_size"]
    device = torch.device("cuda" if torch.cuda.is_available() and config["training"]["device"] != "cpu" else "cpu")
    model.to(device)
    logger.info("Predicting %s addresses on %s", data.num_nodes, device)
    outputs = predict_nodes(model, data, metadata, torch.arange(data.num_nodes), config, device)
    temperature = read_json(root / "artifacts/model/temperature.json")["temperature"]
    addresses = read_json(root / "data/processed/idx_to_address.json")
    table = pd.DataFrame({"address_id": [addresses[str(i)] for i in outputs["node_idx"]],
                          "node_idx": outputs["node_idx"],
                          "behavior_score": 100*calibrated_probability(outputs["behavior_logits"], 1),
                          "graph_score": 100*calibrated_probability(outputs["graph_logits"], 1),
                          "overall_raw_score": 100*calibrated_probability(outputs["fused_logits"], 1),
                          "overall_risk_score": 100*calibrated_probability(outputs["fused_logits"], temperature),
                          "behavior_weight": outputs["gate"], "graph_weight": 1-outputs["gate"]})
    table["risk_level"] = table["overall_risk_score"].map(lambda s: risk_level(s, config["risk_level"]))
    folder = root / "artifacts/risk_scores"
    folder.mkdir(parents=True, exist_ok=True)
    table.to_parquet(folder / "risk_scores.parquet", index=False)
    model_hash = file_sha256(root / "artifacts/model/dual_view_model.pt")
    calibration_hash = file_sha256(root / "artifacts/model/temperature.json")
    save_json(folder / "metadata.json", {"dataset_fingerprint": metadata["fingerprint"],
                                         "model_sha256": model_hash, "calibration_sha256": calibration_hash,
                                         "risk_revision": model_hash + ":" + calibration_hash,
                                         "scope": metadata["scope"], "num_nodes": len(table),
                                         "temperature": temperature, "branch_scores_calibrated": False,
                                         "sampling": config["graphsage"]["num_neighbors"],
                                         "seed": config["training"]["seed"]})
    logger.info("Risk table saved: %s", table["risk_level"].value_counts().to_dict())
    return table
