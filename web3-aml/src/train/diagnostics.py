"""Audit saved risk models without retraining or changing production artifacts."""
from pathlib import Path

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score, brier_score_loss

from src.data.preprocess import load_processed
from src.model.calibration import calibrated_probability
from src.model.dual_view_model import DualViewModel
from src.model.feature_transform import transform_features
from src.train.train import make_loader
from src.utils.io import ROOT, load_config, read_json, save_json
from src.utils.logging import get_logger
from src.utils.seed import set_seed


def distribution(values):
    values = np.asarray(values, dtype=np.float64)
    if values.size == 0 or not np.isfinite(values).all():
        raise ValueError("Diagnostics require nonempty finite values.")
    quantiles = np.quantile(values, [0, .01, .5, .99, 1])
    return dict(zip(("min", "p01", "median", "p99", "max"), map(float, quantiles)))


def probability_summary(labels, logits, temperature, boundary, bins):
    labels, logits = np.asarray(labels), np.asarray(logits)
    probabilities = calibrated_probability(logits, temperature)
    # Equal-width ECE is descriptive and depends on the binning choice.
    assignments = np.minimum((probabilities * bins).astype(int), bins - 1)
    ece = 0.0
    for index in range(bins):
        selected = assignments == index
        if selected.any():
            ece += selected.mean() * abs(probabilities[selected].mean() - labels[selected].mean())
    return {
        "logit_ap": float(average_precision_score(labels, logits)),
        "probability_ap": float(average_precision_score(labels, probabilities)),
        "negative_log_likelihood": float(np.mean(np.logaddexp(0, logits / temperature) - labels * logits / temperature)),
        "brier_score": float(brier_score_loss(labels, probabilities)),
        "ece": float(ece),
        "low_saturation_fraction": float((probabilities <= boundary).mean()),
        "high_saturation_fraction": float((probabilities >= 1 - boundary).mean()),
        "logits": distribution(logits),
        "probabilities": distribution(probabilities),
    }


def feature_summary(features, names, extreme, top_features):
    values = np.asarray(features)
    if values.ndim != 2 or values.shape[1] != len(names) or not np.isfinite(values).all():
        raise ValueError("Feature dimensions or values are invalid.")
    rates = (np.abs(values) > extreme).mean(axis=0)
    order = np.argsort(-rates, kind="stable")[:top_features]
    return {
        "max_abs": float(np.abs(values).max()),
        "rows_with_extreme_features_fraction": float((np.abs(values) > extreme).any(axis=1).mean()),
        "top_extreme_features": [
            {"feature": names[i], "extreme_fraction": float(rates[i]), **distribution(values[:, i])}
            for i in order
        ],
    }


@torch.no_grad()
def collect_diagnostics(model, data, metadata, nodes, config, phase, device):
    """Capture seed-node embedding norms from the same forward pass as logits."""
    model.eval()
    captures = {}
    handles = []
    for name in ("behavior", "graph"):
        def capture(module, inputs, output, key=name):
            captures[key] = output
        handles.append(getattr(model, f"{name}_norm").register_forward_hook(capture))
    outputs = {key: [] for key in ("node_idx", "behavior_logits", "graph_logits", "fused_logits", "gate")}
    for name in ("behavior", "graph"):
        outputs[f"{name}_embedding_norm"] = []
    devices = [device.index if device.index is not None else torch.cuda.current_device()] if device.type == "cuda" else []
    try:
        with torch.random.fork_rng(devices=devices):
            torch.manual_seed(config["training"]["seed"])
            loader = make_loader(data, metadata, nodes, config, model.mode, phase)
            for batch in loader:
                n = batch.batch_size
                outputs["node_idx"].append(batch.n_id[:n].cpu().numpy())
                captures.clear()
                batch = batch.to(device)
                prediction = model(batch.x, batch.edge_index)
                for key, value in prediction.items():
                    outputs[key].append(value[:n].cpu().numpy())
                for name, value in captures.items():
                    outputs[f"{name}_embedding_norm"].append(value[:n].norm(dim=1).cpu().numpy())
    finally:
        for handle in handles:
            handle.remove()
    return {key: np.concatenate(parts) for key, parts in outputs.items() if parts}


def diagnose(root: Path = ROOT):
    settings = load_config("diagnostics.yaml", root)["diagnostics"]
    if not settings["phases"] or not set(settings["phases"]) <= {"train", "val"}:
        raise ValueError("The optimization audit accepts train/val only; keep test independent.")
    if not 0 < settings["gate_boundary"] < .5 or not 0 < settings["probability_boundary"] < .5:
        raise ValueError("Saturation boundaries must be within (0, 0.5).")
    if settings["calibration_bins"] < 1 or settings["top_features"] < 1 or settings["extreme_standardized_value"] <= 0:
        raise ValueError("Diagnostic counts and feature threshold must be positive.")
    logger = get_logger("risk_diagnostics", root)
    data, metadata = load_processed(root)
    names = read_json(root / "data/processed/feature_names.json")
    report = {"dataset_fingerprint": metadata["fingerprint"], "settings": settings, "phases": {}, "models": {}}
    for phase in settings["phases"]:
        mask = getattr(data, f"{phase}_mask")
        report["phases"][phase] = {
            "nodes": int(mask.sum()), "illicit_fraction": float(data.y[mask].float().mean()),
            "features": feature_summary(data.x[mask].numpy(), names,
                                        settings["extreme_standardized_value"], settings["top_features"]),
        }
    rows = []
    for mode in settings["modes"]:
        checkpoint = torch.load(root / f"artifacts/model/{mode}_model.pt", map_location="cpu", weights_only=True)
        if checkpoint["dataset_fingerprint"] != metadata["fingerprint"] or checkpoint["mode"] != mode:
            raise ValueError(f"Mismatched checkpoint: {mode}")
        config = checkpoint["config"]
        if config.get("input_transform"):
            data.x = torch.from_numpy(transform_features(np.load(root / "data/processed/raw_features.npy"), config["input_transform"]))
        else:
            data.x = torch.from_numpy(np.load(root / "data/processed/features.npy"))
        set_seed(config["training"]["seed"], config["training"]["torch_threads"])
        device = torch.device("cuda" if torch.cuda.is_available() and config["training"]["device"] != "cpu" else "cpu")
        model = DualViewModel(checkpoint["input_dim"], config["model"], mode).to(device)
        model.load_state_dict(checkpoint["state_dict"])
        calibration = read_json(root / f"artifacts/model/{mode}_temperature.json")
        report["models"][mode] = {"temperature": calibration["temperature"], "phases": {},
                                 "input_features": {phase: feature_summary(data.x[getattr(data, f"{phase}_mask")].numpy(), names,
                                    settings["extreme_standardized_value"], settings["top_features"]) for phase in settings["phases"]}}
        for phase in settings["phases"]:
            logger.info("Auditing %s/%s", mode, phase)
            outputs = collect_diagnostics(model, data, metadata, getattr(data, f"{phase}_mask"), config, phase, device)
            labels = data.y[outputs["node_idx"]].numpy()
            heads = ("fused", "behavior", "graph") if mode == "dual_view" else ("fused",)
            result = {"heads": {}, "embedding_norms": {}}
            for head in heads:
                # Only the fused head currently has a learned temperature.
                temperatures = {"raw": 1.0}
                if head == "fused":
                    temperatures["calibrated"] = calibration["temperature"]
                result["heads"][head] = {}
                for kind, temperature in temperatures.items():
                    summary = probability_summary(labels, outputs[f"{head}_logits"], temperature,
                                                  settings["probability_boundary"], settings["calibration_bins"])
                    result["heads"][head][kind] = summary
                    rows.append({"model": mode, "phase": phase, "head": head, "score_type": kind,
                                 **{key: value for key, value in summary.items() if not isinstance(value, dict)}})
            for branch in ("behavior", "graph"):
                key = f"{branch}_embedding_norm"
                if key in outputs:
                    result["embedding_norms"][branch] = distribution(outputs[key])
            if mode == "dual_view":
                gate = outputs["gate"]
                boundary = settings["gate_boundary"]
                result["gate"] = {**distribution(gate), "mean": float(gate.mean()),
                                  "graph_dominant_fraction": float((gate <= boundary).mean()),
                                  "behavior_dominant_fraction": float((gate >= 1-boundary).mean())}
            report["models"][mode]["phases"][phase] = result
    folder = root / "artifacts/metrics/risk_diagnostics"
    save_json(folder / "diagnostics.json", report)
    pd.DataFrame(rows).to_csv(folder / "head_metrics.csv", index=False)
    logger.info("Read-only diagnostics saved to %s", folder)
    return report
