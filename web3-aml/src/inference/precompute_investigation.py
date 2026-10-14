"""Offline full-population overlay; no training occurs in the Web app."""
import copy
import hashlib
import json
import numpy as np
import pandas as pd
import torch

from src.data.preprocess import load_processed
from src.model.dual_view_model import DualViewModel
from src.model.feature_transform import transform_features
from src.model.topology_features import topology_features
from src.model.calibration import calibrated_probability
from src.train.train import predict_nodes
from src.train.investigation_experiments import InvestigationExperiment, logits_from_probability
from src.inference.investigation import blend_probabilities, diagnose_experts
from src.utils.io import ROOT, read_json, save_json, file_sha256, load_config
from src.utils.seed import set_seed
from src.utils.logging import get_logger


def precompute_investigation(root=ROOT):
    logger = get_logger("investigation_inference", root)
    experiment = InvestigationExperiment(root)
    final = read_json(experiment.folder / "final_summary.json")
    selected = final["selection"]
    seed = final["representative_seed"]
    folder = experiment.folder / f"final/seed_{seed}"
    table = pd.read_parquet(root / "artifacts/risk_scores/risk_scores.parquet").sort_values("node_idx")
    risk_metadata = read_json(root / "artifacts/risk_scores/metadata.json")
    if risk_metadata["dataset_fingerprint"] != experiment.metadata["fingerprint"]:
        raise RuntimeError("Base risk scores belong to a different dataset.")
    for field, filename in (("model_sha256", "dual_view_model.pt"), ("calibration_sha256", "temperature.json")):
        if risk_metadata[field] != file_sha256(root / "artifacts/model" / filename):
            raise RuntimeError("Base scores are stale. Run 06 first.")
    data, metadata = load_processed(root)
    probabilities, hashes = [], {}
    for name in ("graphsage", "dual_view"):
        source = experiment.source / f"final/{name}/seed_{seed}"
        for filename in ("model.pt", "calibration.json"):
            hashes[(source / filename).relative_to(root).as_posix()] = file_sha256(source / filename)
        if name == "dual_view" and hashes[(source / "model.pt").relative_to(root).as_posix()] == risk_metadata["model_sha256"]:
            probabilities.append(table["overall_risk_score"].to_numpy()/100)
            continue
        checkpoint = torch.load(source / "model.pt", weights_only=True, map_location="cpu")
        if checkpoint["dataset_fingerprint"] != metadata["fingerprint"]:
            raise RuntimeError("Expert belongs to different graph.")
        config = copy.deepcopy(checkpoint["config"])
        set_seed(config["training"]["seed"], config["training"]["torch_threads"])
        data.x = torch.from_numpy(transform_features(experiment.raw, config["input_transform"]))
        config["graphsage"]["batch_size"] = config["graphsage"]["inference_batch_size"]
        model = DualViewModel(checkpoint["input_dim"], config["model"], checkpoint["mode"])
        model.load_state_dict(checkpoint["state_dict"])
        logger.info("Predicting full-population expert %s seed %s", name, seed)
        outputs = predict_nodes(model, data, metadata, torch.arange(len(table)), config, torch.device("cpu"))
        if not np.array_equal(outputs["node_idx"], table.node_idx.to_numpy()):
            raise ValueError("Full-population IDs differ.")
        temperature = read_json(source / "calibration.json")["temperature"]
        probabilities.append(calibrated_probability(outputs["fused_logits"], temperature))
    del data
    logger.info("Predicting full-population topology tree")
    probabilities.append(experiment.tree_probability(folder / "topology_tree", np.ones(len(table), dtype=bool)))
    for filename in ("model.pkl", "input_transform.json", "validation.json"):
        path = folder / "topology_tree" / filename
        hashes[path.relative_to(root).as_posix()] = file_sha256(path)
    calibration = read_json(folder / "calibration.json")
    hashes[(folder / "calibration.json").relative_to(root).as_posix()] = file_sha256(folder / "calibration.json")
    matrix = np.column_stack(probabilities)
    priority = calibrated_probability(logits_from_probability(blend_probabilities(matrix, selected["weights"])), calibration["temperature"])*100
    diagnostics = load_config("investigation.yaml", root)["diagnostics"]
    thresholds = [100*read_json(experiment.source / f"final/{name}/seed_{seed}/calibration.json")["threshold"]
                  for name in ("graphsage", "dual_view")]
    thresholds.append(100*read_json(folder / "topology_tree/validation.json")["threshold"])
    result = pd.DataFrame({"address_id": table.address_id, "node_idx": table.node_idx,
                           "priority_score": priority, "base_risk_score": table.overall_risk_score,
                           "graphsage_expert_score": matrix[:, 0]*100,
                           "dual_view_expert_score": matrix[:, 1]*100,
                           "topology_tree_expert_score": matrix[:, 2]*100,
                           **diagnose_experts(matrix*100, thresholds, diagnostics["low_threshold_fraction"])})
    result["priority_uplift"] = result.priority_score-result.base_risk_score
    result["priority_rank"] = result.priority_score.rank(method="first", ascending=False).astype(int)
    result["base_risk_rank"] = result.base_risk_score.rank(method="first", ascending=False).astype(int)
    result["rank_gain"] = result.base_risk_rank-result.priority_rank
    out = root / "artifacts/investigation"
    out.mkdir(parents=True, exist_ok=True)
    np.save(out / "topology_features.npy", topology_features(experiment.edges, len(table)))
    result.to_parquet(out / "priorities.parquet.tmp", index=False)
    (out / "priorities.parquet.tmp").replace(out / "priorities.parquet")
    selection_hash = file_sha256(experiment.folder / "selection.json")
    overlay = {"experiment": experiment.settings["name"], "seed": seed, "weights": selected["weights"],
               "experts": selected["experts"], "risk_revision": risk_metadata["risk_revision"],
               "warning_thresholds": dict(zip(selected["experts"], thresholds)),
               "dataset_fingerprint": metadata["fingerprint"], "num_nodes": len(result),
               "source_hashes": hashes, "selection_sha256": selection_hash, "diagnostics": diagnostics,
               "topology_sha256": file_sha256(out / "topology_features.npy"),
               "source_sampling": "same seed; full-population NeighborLoader differs from test-only batches",
               "statuses": result.review_status.value_counts().to_dict()}
    overlay["revision"] = hashlib.sha256(json.dumps(overlay, sort_keys=True).encode()).hexdigest()
    # Metadata committed last; resource caches reload when the overlay revision changes.
    save_json(out / "metadata.json", overlay)
    examples = {}
    for status in ("共识告警", "模型分歧"):
        subset = result[result.review_status == status]
        sort = "expert_disagreement" if status == "模型分歧" else "priority_score"
        examples[status] = subset.sort_values(sort, ascending=False).head(3).address_id.tolist()
    uplift = result[(result.rank_gain > 0) & (result.priority_rank <= diagnostics["uplift_queue_size"])]
    examples["排序上调"] = uplift.sort_values("rank_gain", ascending=False).head(3).address_id.tolist()
    save_json(out / "examples.json", examples)
    logger.info("Investigation overlay saved %s", overlay["statuses"])
    return overlay
