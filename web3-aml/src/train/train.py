from pathlib import Path
import copy
import time
import numpy as np
import torch
from torch_geometric.data import Data
from torch_geometric.loader import NeighborLoader
from src.data.preprocess import load_processed
from src.model.dual_view_model import DualViewModel
from src.model.focal_loss import FocalLoss
from src.model.calibration import fit_temperature, calibrated_probability, correct_weighted_bce_heads
from src.model.feature_transform import fit_feature_transform, transform_features
from src.train.evaluate import evaluate_predictions, choose_threshold, save_evaluation
from src.utils.io import ROOT, load_config, save_json
from src.utils.seed import set_seed
from src.utils.logging import get_logger


def phase_data(data, metadata, phase):
    """For temporal splits, exclude future node edges in train/validation message passing."""
    edges = data.edge_index
    if metadata["split"]["method"] == "time" and phase in {"train", "val"}:
        cutoff = metadata["split"][f"{phase}_end"]
        eligible = data.timestep <= cutoff
        edges = edges[:, eligible[edges[0]] & eligible[edges[1]]]
    return Data(x=data.x, y=data.y, edge_index=edges)


def make_loader(data, metadata, nodes, config, mode, phase="test", shuffle=False):
    neighbors = [0, 0] if mode == "behavior" else config["graphsage"]["num_neighbors"]
    graph = phase_data(data, metadata, phase)
    return NeighborLoader(graph, input_nodes=nodes, num_neighbors=neighbors,
                          batch_size=config["graphsage"]["batch_size"], shuffle=shuffle,
                          num_workers=config["graphsage"]["num_workers"])


@torch.no_grad()
def predict_nodes(model, data, metadata, nodes, config, device, phase="test"):
    model.eval()
    outputs = {key: [] for key in ("node_idx", "behavior_logits", "graph_logits", "fused_logits", "gate")}
    devices = [device.index if device.index is not None else torch.cuda.current_device()] if device.type == "cuda" else []
    # Stable evaluation samples must not reset training's shuffle/dropout random stream.
    with torch.random.fork_rng(devices=devices):
        torch.manual_seed(config["training"]["seed"])
        loader = make_loader(data, metadata, nodes, config, model.mode, phase)
        for batch in loader:
            n = batch.batch_size
            outputs["node_idx"].append(batch.n_id[:n].numpy())
            batch = batch.to(device)
            prediction = model(batch.x, batch.edge_index)
            for key in prediction:
                outputs[key].append(prediction[key][:n].cpu().numpy())
    return {key: np.concatenate(value) for key, value in outputs.items()}


def train_model(root: Path = ROOT, mode="dual_view", epochs=None):
    config = load_config("model.yaml", root)
    if epochs is not None:
        config["training"]["epochs"] = epochs
    settings = config["training"]
    set_seed(settings["seed"], settings["torch_threads"])
    device = torch.device("cuda" if settings["device"] == "auto" and torch.cuda.is_available()
                          else "cpu" if settings["device"] == "auto" else settings["device"])
    logger = get_logger("train", root)
    data, metadata = load_processed(root)
    if config.get("feature_preprocessing"):
        from src.utils.io import read_json
        config["input_transform"] = fit_feature_transform(
            np.load(root / "data/processed/raw_features.npy"), data.train_mask.numpy(),
            read_json(root / "data/processed/feature_names.json"), config["feature_preprocessing"])
        data.x = torch.from_numpy(transform_features(np.load(root / "data/processed/raw_features.npy"), config["input_transform"]))
    model = DualViewModel(data.num_node_features, config["model"], mode).to(device)
    optimizer = torch.optim.Adam(model.parameters(), lr=settings["learning_rate"], weight_decay=settings["weight_decay"])
    if settings.get("loss", "focal") == "focal":
        criterion = FocalLoss(**config["focal_loss"])
    elif settings["loss"] == "bce":
        known = data.y[data.train_mask]
        weight = (known == 0).sum().float() / (known == 1).sum().clamp_min(1)
        criterion = torch.nn.BCEWithLogitsLoss(pos_weight=weight.to(device))
    else:
        raise ValueError("training.loss must be focal or bce")
    loader = make_loader(data, metadata, data.train_mask, config, mode, "train", shuffle=True)
    history, best_score, best_state, stale = [], -1, None, 0
    from sklearn.metrics import average_precision_score
    for epoch in range(settings["epochs"]):
        model.train()
        total_loss, count = 0.0, 0
        started = time.monotonic()
        for batch in loader:
            batch = batch.to(device)
            n = batch.batch_size
            targets = batch.y[:n].float()
            if (targets < 0).any():
                raise RuntimeError("Unknown label entered supervision.")
            optimizer.zero_grad()
            output = model(batch.x, batch.edge_index)
            loss = criterion(output["fused_logits"][:n], targets)
            if mode == "dual_view":
                loss = (loss + settings.get("auxiliary_behavior_weight", 0.2)*criterion(output["behavior_logits"][:n], targets)
                        + settings.get("auxiliary_graph_weight", 0.2)*criterion(output["graph_logits"][:n], targets))
            loss.backward()
            if settings.get("gradient_clip"):
                torch.nn.utils.clip_grad_norm_(model.parameters(), settings["gradient_clip"])
            optimizer.step()
            total_loss += loss.item()*n
            count += n
        val = predict_nodes(model, data, metadata, data.val_mask, config, device, "val")
        score = float(average_precision_score(data.y[val["node_idx"]].numpy(), val["fused_logits"]))
        record = {"epoch": epoch+1, "loss": total_loss/count, "val_pr_auc": score,
                  "seconds": time.monotonic()-started}
        history.append(record)
        logger.info("%s %s", mode, record)
        if score > best_score:
            best_score, stale = score, 0
            best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
        else:
            stale += 1
        if stale >= settings["early_stop_patience"]:
            break
    model.load_state_dict(best_state)
    posterior_correction = None
    if settings.get("loss") == "bce":
        posterior_correction = correct_weighted_bce_heads(model, float(weight))
        best_state = {k: v.detach().cpu().clone() for k, v in model.state_dict().items()}
    val = predict_nodes(model, data, metadata, data.val_mask, config, device, "val")
    val_labels = data.y[val["node_idx"]].numpy()
    temperature = fit_temperature(val["fused_logits"], val_labels, config["calibration"]["max_iter"])
    threshold = choose_threshold(val_labels, calibrated_probability(val["fused_logits"], temperature))
    test = predict_nodes(model, data, metadata, data.test_mask, config, device)
    result = evaluate_predictions(data.y[test["node_idx"]].numpy(),
                                  calibrated_probability(test["fused_logits"], temperature), threshold)
    result.update({"scope": metadata["scope"], "dataset_fingerprint": metadata["fingerprint"],
                   "split_method": metadata["split"]["method"], "epochs_run": len(history),
                   "temperature": temperature, "best_val_pr_auc": best_score})
    save_evaluation(mode, result, root)
    folder = root / "artifacts/model"
    folder.mkdir(parents=True, exist_ok=True)
    checkpoint = {"state_dict": best_state, "input_dim": data.num_node_features,
                  "config": config, "mode": mode, "dataset_fingerprint": metadata["fingerprint"],
                  "posterior_correction": posterior_correction}
    torch.save(checkpoint, folder / f"{mode}_model.pt")
    save_json(folder / f"{mode}_temperature.json", {"temperature": temperature, "threshold": threshold})
    save_json(folder / f"{mode}_training_history.json", history)
    if mode == "dual_view":
        save_json(folder / "temperature.json", {"temperature": temperature, "threshold": threshold})
        save_json(folder / "model_config.json", config)
        save_json(folder / "training_history.json", history)
        torch.save(checkpoint, folder / "best_model.pt")
    logger.info("%s test metrics: %s", mode, {k: v for k, v in result.items() if not isinstance(v, (dict, list))})
    return result
