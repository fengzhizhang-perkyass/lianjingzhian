"""Isolated chronological experiments, frozen selection, and final comparisons."""
from pathlib import Path
import copy
import hashlib
import json
import time

import numpy as np
import pandas as pd
import torch
from sklearn.metrics import average_precision_score
from lightgbm import LGBMClassifier, early_stopping
from filelock import FileLock

from src.data.preprocess import load_processed
from src.model.dual_view_model import DualViewModel
from src.model.feature_transform import fit_feature_transform, transform_features
from src.model.focal_loss import FocalLoss
from src.model.calibration import fit_temperature, calibrated_probability, correct_weighted_bce_heads, weighted_probability_logits
from src.train.train import make_loader, predict_nodes
from src.train.evaluate import choose_threshold, evaluate_predictions
from src.utils.io import ROOT, load_config, read_json, save_json
from src.utils.logging import get_logger
from src.utils.seed import set_seed


def chronological_masks(labels, timesteps, train_end, val_end):
    known = np.asarray(labels) >= 0
    times = np.asarray(timesteps)
    train = known & (times <= train_end)
    val = known & (times > train_end) & (times <= val_end)
    if train_end >= val_end or not train.any() or not val.any():
        raise ValueError("Invalid chronological development boundaries.")
    if any(len(np.unique(np.asarray(labels)[mask])) < 2 for mask in (train, val)):
        raise ValueError("Both periods need both supervised classes.")
    return train, val


def review_metrics(labels, scores, counts, fractions):
    labels, scores = np.asarray(labels), np.asarray(scores)
    # Stable ties make the selection reproducible; scores are raw logits.
    order = np.argsort(-scores, kind="stable")
    total_positive = int((labels == 1).sum())
    budgets = {f"top_{k}": min(int(k), len(labels)) for k in counts}
    budgets.update({f"top_{fraction:g}_fraction": max(1, int(np.ceil(len(labels)*fraction))) for fraction in fractions})
    return {name: {"reviewed": k, "illicit_found": int(labels[order[:k]].sum()),
                   "precision": float(labels[order[:k]].mean()),
                   "recall": float(labels[order[:k]].sum()/max(total_positive, 1))}
            for name, k in budgets.items()}


def ranking_ap(labels, outputs):
    heads = ("fused", "behavior", "graph")
    return {head: float(average_precision_score(labels, outputs[f"{head}_logits"])) for head in heads}


class RiskExperiment:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.base = load_config("model.yaml", root)
        self.settings = load_config("risk_experiments.yaml", root)["experiment"]
        self.folder = root / "artifacts/experiments" / self.settings["name"]
        manifest = self.folder / "manifest.json"
        if manifest.exists():
            # An existing experiment always resumes its frozen base configuration.
            self.base = read_json(manifest)["base_config"]
        self.logger = get_logger("risk_experiments", root)
        self.data, self.metadata = load_processed(root)
        if self.metadata["split"]["method"] != "time":
            raise ValueError("This experiment requires chronological data.")
        self.raw = np.load(root / "data/processed/raw_features.npy", mmap_mode="r")
        self.names = read_json(root / "data/processed/feature_names.json")
        self.original_masks = (self.data.train_mask, self.data.val_mask)
        self.original_metadata = copy.deepcopy(self.metadata)
        if any(fold["val_end"] > self.metadata["split"]["train_end"] for fold in self.settings["development_folds"]):
            raise ValueError("Development folds must stay inside the original training interval.")
        signature = {"experiment": self.settings, "base_config": self.base,
                     "dataset_fingerprint": self.metadata["fingerprint"]}
        self.signature = hashlib.sha256(json.dumps(signature, sort_keys=True).encode()).hexdigest()
        if manifest.exists() and read_json(manifest)["signature"] != self.signature:
            raise ValueError("Experiment settings changed. Use a new experiment.name to preserve prior results.")
        if not manifest.exists():
            save_json(manifest, {"signature": self.signature, **signature, "selection_uses_test": False})
        historical = self.folder / "historical_baseline.json"
        if not historical.exists():
            save_json(historical, read_json(root / "artifacts/metrics/comparison.json"))
        policy = self.folder / "probability_export_policy.json"
        if not policy.exists():
            save_json(policy, {"weighted_bce": "subtract log(training positive weight) from linear head biases",
                               "lightgbm": "undo balanced class-weight odds multiplier",
                               "temperature": "fit on validation after correction", "test_used_for_policy": False})

    def prepare(self, features, fold=None):
        if fold:
            train, val = chronological_masks(self.data.y.numpy(), self.data.timestep.numpy(),
                                             fold["train_end"], fold["val_end"])
            self.data.train_mask, self.data.val_mask = torch.from_numpy(train), torch.from_numpy(val)
            self.metadata = copy.deepcopy(self.original_metadata)
            self.metadata["split"].update(train_end=fold["train_end"], val_end=fold["val_end"])
        else:
            self.data.train_mask, self.data.val_mask = self.original_masks
            self.metadata = copy.deepcopy(self.original_metadata)
        state = fit_feature_transform(self.raw, self.data.train_mask.numpy(), self.names, features)
        self.data.x = torch.from_numpy(transform_features(self.raw, state))
        return state

    def fit(self, run_id, candidate, state, seed, epochs, loss):
        folder = self.folder / run_id
        folder.mkdir(parents=True, exist_ok=True)
        with FileLock(str(folder / "training.lock"), timeout=3600):
            return self._fit_unlocked(run_id, candidate, state, seed, epochs, loss)

    def _fit_unlocked(self, run_id, candidate, state, seed, epochs, loss):
        folder = self.folder / run_id
        result_path = folder / "validation.json"
        if result_path.exists():
            self.logger.info("Resume completed run %s", run_id)
            return read_json(result_path)
        config = copy.deepcopy(self.base)
        config["model"].update({key: candidate[key] for key in ("embedding_normalization", "fusion_mode") if key in candidate})
        config["model"]["fixed_behavior_weight"] = self.settings["fixed_behavior_weight"]
        config["training"].update(seed=seed, epochs=epochs, learning_rate=self.settings["learning_rate"],
                                   early_stop_patience=self.settings["early_stop_patience"], loss=loss,
                                   gradient_clip=self.settings["gradient_clip"],
                                   auxiliary_behavior_weight=self.settings["auxiliary_behavior_weight"],
                                   auxiliary_graph_weight=self.settings["auxiliary_graph_weight"])
        config["input_transform"] = state
        set_seed(seed, config["training"]["torch_threads"])
        device = torch.device("cuda" if torch.cuda.is_available() and config["training"]["device"] != "cpu" else "cpu")
        mode = candidate["mode"]
        model = DualViewModel(self.data.num_node_features, config["model"], mode).to(device)
        optimizer = torch.optim.Adam(model.parameters(), lr=self.settings["learning_rate"],
                                     weight_decay=config["training"]["weight_decay"])
        if loss == "focal":
            criterion = FocalLoss(**config["focal_loss"])
        elif loss == "bce":
            targets = self.data.y[self.data.train_mask]
            weight = (targets == 0).sum().float()/(targets == 1).sum().clamp_min(1)
            criterion = torch.nn.BCEWithLogitsLoss(pos_weight=weight.to(device))
        else:
            raise ValueError("Loss must be focal or bce.")
        loader = make_loader(self.data, self.metadata, self.data.train_mask, config, mode, "train", shuffle=True)
        history, best_score, best_state, stale, best_epoch = [], -1., None, 0, 0
        started = time.monotonic()
        for epoch in range(epochs):
            model.train()
            total_loss, count = 0., 0
            for batch in loader:
                batch = batch.to(device)
                n = batch.batch_size
                targets = batch.y[:n].float()
                if (targets < 0).any():
                    raise RuntimeError("Unknown label entered training.")
                optimizer.zero_grad()
                output = model(batch.x, batch.edge_index)
                batch_loss = criterion(output["fused_logits"][:n], targets)
                if mode == "dual_view":
                    batch_loss += self.settings["auxiliary_behavior_weight"] * criterion(output["behavior_logits"][:n], targets)
                    batch_loss += self.settings["auxiliary_graph_weight"] * criterion(output["graph_logits"][:n], targets)
                if not torch.isfinite(batch_loss):
                    raise RuntimeError("Training produced a non-finite loss.")
                batch_loss.backward()
                torch.nn.utils.clip_grad_norm_(model.parameters(), self.settings["gradient_clip"])
                optimizer.step()
                total_loss += batch_loss.item()*n
                count += n
            outputs = predict_nodes(model, self.data, self.metadata, self.data.val_mask, config, device, "val")
            labels = self.data.y[outputs["node_idx"]].numpy()
            scores = ranking_ap(labels, outputs)
            record = {"epoch": epoch+1, "loss": total_loss/count, "validation_ap": scores["fused"],
                      "gate_mean": float(outputs["gate"].mean())}
            if mode == "dual_view":
                record.update(behavior_ap=scores["behavior"], graph_ap=scores["graph"])
            history.append(record)
            self.logger.info("%s %s", run_id, record)
            if scores["fused"] > best_score:
                best_score, stale, best_epoch = scores["fused"], 0, epoch+1
                best_state = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
            else:
                stale += 1
            if stale >= self.settings["early_stop_patience"]:
                break
        model.load_state_dict(best_state)
        outputs = predict_nodes(model, self.data, self.metadata, self.data.val_mask, config, device, "val")
        labels = self.data.y[outputs["node_idx"]].numpy()
        temperature = fit_temperature(outputs["fused_logits"], labels, config["calibration"]["max_iter"])
        probabilities = calibrated_probability(outputs["fused_logits"], temperature)
        threshold = choose_threshold(labels, probabilities)
        metrics = evaluate_predictions(labels, probabilities, threshold)
        summary = {key: value for key, value in metrics.items() if key not in {"pr_curve", "roc_curve", "num_test_nodes"}}
        summary.update(validation_ap=best_score, best_epoch=best_epoch, epochs_run=len(history),
                       temperature=temperature, seed=seed, mode=mode, loss=loss,
                       train_nodes=int(self.data.train_mask.sum()), validation_nodes=len(labels),
                       seconds=time.monotonic()-started)
        folder.mkdir(parents=True, exist_ok=True)
        checkpoint = {"state_dict": best_state, "input_dim": self.data.num_node_features,
                      "config": config, "mode": mode, "dataset_fingerprint": self.metadata["fingerprint"],
                      "experiment_signature": self.signature, "best_epoch": best_epoch}
        torch.save(checkpoint, folder / "model.pt")
        np.savez_compressed(folder / "validation_predictions.npz", **outputs)
        save_json(folder / "history.json", history)
        save_json(folder / "calibration.json", {"temperature": temperature, "threshold": threshold})
        save_json(result_path, summary)
        return summary

    def development(self):
        selection_path = self.folder / "selection.json"
        if selection_path.exists():
            return read_json(selection_path)
        rows = []
        for features in self.settings["feature_candidates"]:
            for fold in self.settings["development_folds"]:
                state = self.prepare(features, fold)
                for loss in self.settings["loss_candidates"]:
                    run_id = f"development/behavior/{features['name']}_{loss}/{fold['name']}"
                    result = self.fit(run_id, {"mode": "behavior"}, state, self.settings["development_seed"],
                                      self.settings["development_epochs"], loss)
                    rows.append({"features": features["name"], "loss": loss, "fold": fold["name"],
                                 "validation_ap": result["validation_ap"]})
                    pd.DataFrame(rows).to_csv(self.folder / "behavior_development.csv", index=False)
        table = pd.DataFrame(rows)
        grouped = table.groupby(["features", "loss"], sort=False)["validation_ap"].agg(["mean", "min"])
        choice = grouped.sort_values(["mean", "min"], ascending=False, kind="stable").index[0]
        features = next(item for item in self.settings["feature_candidates"] if item["name"] == choice[0])
        loss = choice[1]
        fusion_rows = []
        for fold in self.settings["development_folds"]:
            state = self.prepare(features, fold)
            for candidate in self.settings["fusion_candidates"]:
                run_id = f"development/fusion/{candidate['name']}/{fold['name']}"
                result = self.fit(run_id, candidate, state, self.settings["development_seed"],
                                  self.settings["development_epochs"], loss)
                fusion_rows.append({"candidate": candidate["name"], "fold": fold["name"],
                                    "validation_ap": result["validation_ap"]})
                pd.DataFrame(fusion_rows).to_csv(self.folder / "fusion_development.csv", index=False)
        fusion_table = pd.DataFrame(fusion_rows)
        learned = [candidate["name"] for candidate in self.settings["fusion_candidates"]
                   if candidate["mode"] == "dual_view" and candidate["fusion_mode"] == "learned"]
        grouped = fusion_table[fusion_table.candidate.isin(learned)].groupby("candidate", sort=False)["validation_ap"].agg(["mean", "min"])
        best_name = grouped.sort_values(["mean", "min"], ascending=False, kind="stable").index[0]
        candidate = next(item for item in self.settings["fusion_candidates"] if item["name"] == best_name)
        selection = {"signature": self.signature, "features": features, "loss": loss, "fusion": candidate,
                     "selection_rule": "mean development AP, minimum fold AP as tie breaker",
                     "development_only": True, "test_used_for_selection": False}
        save_json(selection_path, selection)
        self.logger.info("Frozen development selection: %s", selection)
        return selection

    def train_fusion_fold(self, name):
        table = pd.read_csv(self.folder / "behavior_development.csv")
        expected = (len(self.settings["feature_candidates"]) * len(self.settings["loss_candidates"])
                    * len(self.settings["development_folds"]))
        if len(table) != expected:
            raise RuntimeError("Finish all behavior development runs before parallel fusion folds.")
        grouped = table.groupby(["features", "loss"], sort=False)["validation_ap"].agg(["mean", "min"])
        choice = grouped.sort_values(["mean", "min"], ascending=False, kind="stable").index[0]
        features = next(item for item in self.settings["feature_candidates"] if item["name"] == choice[0])
        fold = next((item for item in self.settings["development_folds"] if item["name"] == name), None)
        if fold is None:
            raise ValueError("Unknown development fold.")
        state = self.prepare(features, fold)
        return [self.fit(f"development/fusion/{candidate['name']}/{name}", candidate, state,
                         self.settings["development_seed"], self.settings["development_epochs"], choice[1])
                for candidate in self.settings["fusion_candidates"]]

    def test_saved(self, run_id, state):
        folder = self.folder / run_id
        if (folder / "test.json").exists():
            return read_json(folder / "test.json")
        checkpoint = torch.load(folder / "model.pt", map_location="cpu", weights_only=True)
        set_seed(checkpoint["config"]["training"]["seed"], checkpoint["config"]["training"]["torch_threads"])
        model = DualViewModel(checkpoint["input_dim"], checkpoint["config"]["model"], checkpoint["mode"])
        model.load_state_dict(checkpoint["state_dict"])
        started = time.monotonic()
        outputs = predict_nodes(model, self.data, self.metadata, self.data.test_mask,
                                checkpoint["config"], torch.device("cpu"))
        inference_seconds = time.monotonic()-started
        labels = self.data.y[outputs["node_idx"]].numpy()
        calibration = read_json(folder / "calibration.json")
        probability = calibrated_probability(outputs["fused_logits"], calibration["temperature"])
        result = evaluate_predictions(labels, probability, calibration["threshold"])
        result.update(logit_ap=float(average_precision_score(labels, outputs["fused_logits"])),
                      review=review_metrics(labels, outputs["fused_logits"], self.settings["review_top_k"],
                                            self.settings["review_top_fractions"]),
                      model_parameters=sum(parameter.numel() for parameter in model.parameters()),
                      checkpoint_bytes=(folder / "model.pt").stat().st_size,
                      test_inference_seconds=inference_seconds, inference_device="cpu",
                      dataset_fingerprint=self.metadata["fingerprint"], scope=self.metadata["scope"])
        np.savez_compressed(folder / "test_predictions.npz", **outputs)
        save_json(folder / "test.json", result)
        return result

    def calibrate_final_export(self, run_id):
        """Correct completed weighted-CE checkpoints once, before final test use."""
        folder = self.folder / run_id
        if (folder / "test.json").exists():
            raise RuntimeError("Cannot change calibration after final test evaluation.")
        checkpoint = torch.load(folder / "model.pt", map_location="cpu", weights_only=True)
        validation = read_json(folder / "validation.json")
        calibration = read_json(folder / "calibration.json")
        if checkpoint["config"]["training"]["loss"] != "bce":
            return read_json(folder / "validation.json")
        if (checkpoint.get("posterior_correction") and validation.get("posterior_correction")
                and calibration.get("posterior_correction")):
            return validation
        model = DualViewModel(checkpoint["input_dim"], checkpoint["config"]["model"], checkpoint["mode"])
        model.load_state_dict(checkpoint["state_dict"])
        labels = self.data.y[self.data.train_mask]
        weight = float((labels == 0).sum()/(labels == 1).sum())
        correction = checkpoint.get("posterior_correction") or correct_weighted_bce_heads(model, weight)
        set_seed(checkpoint["config"]["training"]["seed"], checkpoint["config"]["training"]["torch_threads"])
        previous = predict_nodes(model, self.data, self.metadata, self.data.val_mask,
                                 checkpoint["config"], torch.device("cpu"), "val")
        labels = self.data.y[previous["node_idx"]].numpy()
        temperature = fit_temperature(previous["fused_logits"], labels, checkpoint["config"]["calibration"]["max_iter"])
        probability = calibrated_probability(previous["fused_logits"], temperature)
        threshold = choose_threshold(labels, probability)
        metrics = evaluate_predictions(labels, probability, threshold)
        old = read_json(folder / "validation.json")
        if not (folder / "validation_before_odds_correction.json").exists():
            save_json(folder / "validation_before_odds_correction.json", old)
        shutil_source = folder / "model_weighted_training.pt"
        if not shutil_source.exists():
            import shutil
            shutil.copy2(folder / "model.pt", shutil_source)
        checkpoint["state_dict"] = {key: value.detach().cpu().clone() for key, value in model.state_dict().items()}
        checkpoint["posterior_correction"] = correction
        np.savez_compressed(folder / "validation_predictions.npz", **previous)
        save_json(folder / "calibration.json", {"temperature": temperature, "threshold": threshold,
                                                "posterior_correction": correction})
        old.update({key: value for key, value in metrics.items() if key not in {"pr_curve", "roc_curve", "num_test_nodes"}})
        old.pop("num_test_nodes", None)
        old["temperature"] = temperature
        old["posterior_correction"] = correction
        save_json(folder / "validation.json", old)
        # Commit the corrected model last; interrupted exports can replay validation.
        torch.save(checkpoint, folder / "model.pt.tmp")
        (folder / "model.pt.tmp").replace(folder / "model.pt")
        return old

    def final_candidates(self, selection):
        selected = selection["fusion"]
        return [
            {"name": "behavior", "mode": "behavior"},
            {"name": "graphsage", "mode": "graphsage"},
            {**selected, "name": "dual_view"},
            {**selected, "name": "fixed_fusion", "fusion_mode": "fixed"},
        ]

    def train_final_candidate(self, name):
        if not (self.folder / "selection.json").exists():
            if name not in {"behavior", "graphsage"}:
                raise RuntimeError("Finish development and freeze fusion selection before dual-view training.")
            table = pd.read_csv(self.folder / "behavior_development.csv")
            expected = (len(self.settings["feature_candidates"])*len(self.settings["loss_candidates"])
                        *len(self.settings["development_folds"]))
            if len(table) != expected:
                raise RuntimeError("Finish behavior development before independent final baselines.")
            grouped = table.groupby(["features", "loss"], sort=False)["validation_ap"].agg(["mean", "min"])
            choice = grouped.sort_values(["mean", "min"], ascending=False, kind="stable").index[0]
            selection = {"features": next(item for item in self.settings["feature_candidates"] if item["name"] == choice[0]),
                         "loss": choice[1], "test_used_for_selection": False}
            with FileLock(str(self.folder / "independent_selection.lock")):
                if not (self.folder / "independent_selection.json").exists():
                    save_json(self.folder / "independent_selection.json", selection)
            candidate = {"name": name, "mode": name}
        else:
            selection = read_json(self.folder / "selection.json")
            candidates = self.final_candidates(selection)
            candidate = next((item for item in candidates if item["name"] == name), None)
        if candidate is None:
            raise ValueError(f"Unknown final candidate {name}")
        state = self.prepare(selection["features"])
        return [self.fit(f"final/{name}/seed_{seed}", candidate, state, seed,
                         self.settings["final_epochs"], selection["loss"]) for seed in self.settings["final_seeds"]]

    def final(self):
        selection = self.development()
        state = self.prepare(selection["features"])
        candidates = self.final_candidates(selection)
        validation_rows = []
        for candidate in candidates:
            for seed in self.settings["final_seeds"]:
                run_id = f"final/{candidate['name']}/seed_{seed}"
                result = self.fit(run_id, candidate, state, seed, self.settings["final_epochs"], selection["loss"])
                if not (self.folder / run_id / "test.json").exists():
                    result = self.calibrate_final_export(run_id)
                validation_rows.append({"candidate": candidate["name"], "run_id": run_id, "seed": seed,
                                        "validation_ap": result["validation_ap"]})
        # Freeze representative seed selection BEFORE any new final test inference.
        best = max((row for row in validation_rows if row["candidate"] == "dual_view"),
                   key=lambda row: row["validation_ap"])
        freeze = {"selection": selection, "production_candidate": best,
                  "probability_policy": read_json(self.folder / "probability_export_policy.json"),
                  "seed_rule": "highest validation AP; never select using test metrics",
                  "runs": validation_rows}
        save_json(self.folder / "final_freeze.json", freeze)
        rows = []
        for row in validation_rows:
            result = self.test_saved(row["run_id"], state)
            rows.append({**row, **{key: result[key] for key in
                                 ("precision", "recall", "f1", "pr_auc", "roc_auc", "brier_score", "model_parameters", "checkpoint_bytes", "test_inference_seconds")}})
        self.final_lightgbm(state, rows)
        table = pd.DataFrame(rows)
        table.to_csv(self.folder / "final_comparison.csv", index=False)
        summary = table.groupby("candidate")[ ["precision", "recall", "f1", "pr_auc", "roc_auc"] ].agg(["mean", "std"])
        summary.to_csv(self.folder / "final_mean_std.csv")
        chosen_result = read_json(self.folder / best["run_id"] / "test.json")
        passed = (chosen_result["pr_auc"] >= self.settings["promotion_min_test_ap"]
                  and chosen_result["f1"] >= self.settings["promotion_min_test_f1"])
        result = {"signature": self.signature, "production_candidate": best,
                  "promotion_guardrails_passed": passed, "test_used_for_selection": False,
                  "previous_test_was_already_observed": True, "comparison": rows}
        save_json(self.folder / "final_summary.json", result)
        return result

    def final_lightgbm(self, state, rows):
        import joblib
        folder = self.folder / "final/lightgbm"
        if not (folder / "test.json").exists():
            config = self.base
            x, y = self.data.x.numpy(), self.data.y.numpy()
            train, val, test = (getattr(self.data, f"{phase}_mask").numpy() for phase in ("train", "val", "test"))
            classifier = LGBMClassifier(**config["baseline"], class_weight="balanced", verbosity=-1,
                                        metric="average_precision", random_state=self.settings["development_seed"])
            classifier.fit(x[train], y[train], eval_set=[(x[val], y[val])], eval_metric="average_precision",
                           callbacks=[early_stopping(self.settings["early_stop_patience"], verbose=False)])
            positive_weight = float((y[train] == 0).sum()/(y[train] == 1).sum())
            val_logits = weighted_probability_logits(classifier.predict_proba(x[val])[:, 1], positive_weight)
            temperature = fit_temperature(val_logits, y[val], config["calibration"]["max_iter"])
            val_probability = calibrated_probability(val_logits, temperature)
            threshold = choose_threshold(y[val], val_probability)
            folder.mkdir(parents=True, exist_ok=True)
            save_json(folder / "validation.json", {"validation_ap": float(average_precision_score(y[val], val_probability)),
                                                    "threshold": threshold, "seed": self.settings["development_seed"]})
            joblib.dump(classifier, folder / "model.pkl")
            save_json(folder / "calibration.json", {"temperature": temperature, "positive_weight": positive_weight,
                                                    "method": "weighted_odds_then_temperature"})
            probability = calibrated_probability(weighted_probability_logits(classifier.predict_proba(x[test])[:, 1], positive_weight), temperature)
            result = evaluate_predictions(y[test], probability, threshold)
            result["review"] = review_metrics(y[test], probability, self.settings["review_top_k"], self.settings["review_top_fractions"])
            save_json(folder / "test.json", result)
            save_json(folder / "input_transform.json", state)
        result, val_result = read_json(folder / "test.json"), read_json(folder / "validation.json")
        rows.append({"candidate": "lightgbm", "run_id": "final/lightgbm", "seed": val_result["seed"],
                     "validation_ap": val_result["validation_ap"],
                     **{key: result[key] for key in ("precision", "recall", "f1", "pr_auc", "roc_auc", "brier_score")}})
