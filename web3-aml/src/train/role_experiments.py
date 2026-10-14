"""Frozen, chronological comparison of evidence routes with one graph encoder."""
import hashlib
import json
import time
import joblib
import numpy as np
import pandas as pd
import torch
from lightgbm import LGBMClassifier, early_stopping
from sklearn.metrics import average_precision_score
from filelock import FileLock

from src.utils.io import ROOT, load_config, read_json, save_json, file_sha256
from src.utils.logging import get_logger
from src.model.feature_transform import fit_feature_transform, transform_features
from src.model.directed_structure import directed_structure, STRUCTURE_NAMES
from src.model.topology_features import NAMES
from src.model.calibration import weighted_probability_logits, fit_temperature, calibrated_probability
from src.train.risk_experiments import chronological_masks, review_metrics
from src.train.investigation_experiments import logits_from_probability
from src.train.evaluate import evaluate_predictions, choose_threshold
from src.inference.investigation import simplex_weights, blend_probabilities

LABELS = {
    "local_behavior": "个体行为树（45项）", "structure8": "有向结构树（8项）",
    "structure18": "有向结构树（18项）", "undirected3": "无向结构树（3项）",
    "graphsage": "关联上下文 GraphSAGE", "dual_view": "原双线路 Gate",
    "behavior": "独立行为 MLP", "behavior_head": "共享模型行为头",
    "graph_head": "共享模型关联头", "enhanced_tree": "旧行为＋拓扑树",
    "selected": "职责清晰的选定组合", "old_redundant": "旧重复三专家组合",
}


def validate_routes(experts):
    """A dual-view model already includes GraphSAGE; never add a second one."""
    graph_routes = {"graphsage", "dual_view", "graph_head"}
    if len(set(experts) & graph_routes) > 1:
        raise ValueError("Candidate contains duplicate GraphSAGE encoders")
    if "dual_view" in experts and "behavior_head" in experts:
        raise ValueError("Fused and behavior-head scores are overlapping routes")


class RoleExperiment:
    def __init__(self, root=ROOT):
        self.root = root
        self.settings = load_config("role_experiments.yaml", root)["experiment"]
        torch.set_num_threads(4)
        self.folder = root / "artifacts/experiments" / self.settings["name"]
        self.source = root / "artifacts/experiments" / self.settings["source_experiment"]
        self.old = root / "artifacts/experiments" / self.settings["source_investigation"]
        self.metadata = read_json(root / "data/processed/metadata.json")
        self.labels = np.load(root / "data/processed/labels.npy")
        self.times = np.load(root / "data/processed/timesteps.npy")
        self.raw = np.load(root / "data/processed/raw_features.npy", mmap_mode="r")
        self.edges = torch.load(root / "data/processed/edge_index_directed.pt", weights_only=True).numpy()
        self.names = read_json(root / "data/processed/feature_names.json")
        self.features = read_json(self.source / "selection.json")["features"]
        self.local_columns = [i for i, name in enumerate(self.names)
                              if not any(name.startswith(prefix) for prefix in self.settings["local_exclude_prefixes"])]
        for experts in self.settings["families"].values():
            validate_routes(experts)
        self.logger = get_logger("role_experiments", root)
        manifest = {"settings": self.settings, "dataset_fingerprint": self.metadata["fingerprint"],
                    "local_features": [self.names[i] for i in self.local_columns],
                    "structure_features": STRUCTURE_NAMES,
                    "source_selection_sha256": file_sha256(self.source / "selection.json"),
                    "structure_code_sha256": file_sha256(root / "src/model/directed_structure.py"),
                    "test_already_observed": True, "selection_uses_test": False}
        path = self.folder / "manifest.json"
        if path.exists() and read_json(path) != manifest:
            raise RuntimeError("Role experiment settings changed: use a new name")
        save_json(path, manifest)

    def masks(self, fold=None):
        if fold:
            return chronological_masks(self.labels, self.times, fold["train_end"], fold["val_end"])
        return tuple(np.load(self.root / f"data/processed/{phase}_mask.npy") for phase in ("train", "val"))

    def structure(self, cutoff=None):
        path = self.folder / "cache" / f"structure_{cutoff if cutoff is not None else 'full'}.npy"
        if not path.exists():
            path.parent.mkdir(parents=True, exist_ok=True)
            np.save(path, directed_structure(self.edges, len(self.labels), self.times, cutoff))
        return np.load(path, mmap_mode="r")

    def input(self, name, mask, cutoff, state=None):
        if name == "local_behavior":
            return transform_features(self.raw[mask], state)[:, self.local_columns]
        structure = self.structure(cutoff)
        if name == "structure8":
            return structure[mask, :8]
        if name == "structure18":
            return structure[mask]
        if name == "undirected3":
            return structure[mask][:, [2, 7]]  # degree and isolation, plus mean undirected neighbor degree
        raise ValueError(name)

    def fit_tree(self, name, folder, train, val, train_cutoff, val_cutoff):
        if (folder / "validation.json").exists():
            return read_json(folder / "validation.json")
        folder.mkdir(parents=True, exist_ok=True)
        state = fit_feature_transform(self.raw, train, self.names, self.features) if name == "local_behavior" else None
        xtrain = self.input(name, train, train_cutoff, state)
        xval = self.input(name, val, val_cutoff, state)
        names = ([self.names[i] for i in self.local_columns] if name == "local_behavior" else
                 NAMES if name == "structure8" else STRUCTURE_NAMES if name == "structure18" else ["log_neighbor_count", "is_isolated"])
        started = time.monotonic()
        model = LGBMClassifier(**self.settings["tree"], random_state=self.settings["seed"],
                               class_weight="balanced", verbosity=-1, metric="average_precision")
        model.fit(xtrain, self.labels[train], eval_set=[(xval, self.labels[val])],
                  callbacks=[early_stopping(self.settings["patience"], verbose=False)])
        weight = float((self.labels[train] == 0).sum()/(self.labels[train] == 1).sum())
        z = weighted_probability_logits(model.predict_proba(xval)[:, 1], weight)
        temperature = fit_temperature(z, self.labels[val])
        p = calibrated_probability(z, temperature)
        info = {"name": name, "validation_ap": float(average_precision_score(self.labels[val], p)),
                "temperature": temperature, "positive_weight": weight,
                "threshold": choose_threshold(self.labels[val], p), "best_iteration": model.best_iteration_,
                "seconds": time.monotonic()-started, "features": names, "input_transform": state}
        joblib.dump(model, folder / "model.pkl")
        np.savez_compressed(folder / "validation_predictions.npz", node_idx=np.flatnonzero(val), probability=p)
        save_json(folder / "validation.json", info)
        self.logger.info("Completed %s AP %.4f", folder, info["validation_ap"])
        return info

    def neural(self, name, phase, fold=None, seed=42):
        head = {"behavior_head": "behavior", "graph_head": "graph"}.get(name, "fused")
        model = "dual_view" if name in {"behavior_head", "graph_head"} else name
        if fold:
            train, _ = self.masks(fold)
            folder = (self.source / f"development/behavior/{self.features['name']}_bce/{fold['name']}"
                      if model == "behavior" else self.source / f"development/fusion/{'gated' if model == 'dual_view' else model}/{fold['name']}")
        else:
            folder = self.source / f"final/{model}/seed_{seed}"
        outputs = np.load(folder / f"{phase}_predictions.npz")
        ids = outputs["node_idx"]
        z = outputs[f"{head}_logits"].astype(float)
        if fold:
            z -= np.log(float((self.labels[train] == 0).sum()/(self.labels[train] == 1).sum()))
        calibration_path = self.folder / "calibration" / (fold["name"] if fold else f"seed_{seed}") / f"{name}.json"
        if not calibration_path.exists():
            if phase != "validation":
                raise RuntimeError("Neural calibration must be frozen before test reads")
            temperature = fit_temperature(z, self.labels[ids])
            p = calibrated_probability(z, temperature)
            save_json(calibration_path, {"temperature": temperature, "threshold": choose_threshold(self.labels[ids], p),
                                         "prediction_sha256": file_sha256(folder / f"{phase}_predictions.npz")})
        calibration = read_json(calibration_path)
        return ids, calibrated_probability(z, calibration["temperature"]), calibration["threshold"]

    def probabilities(self, phase, fold=None, seed=42):
        train, val = self.masks(fold)
        mask = val if phase == "validation" else np.load(self.root / "data/processed/test_mask.npy")
        ids = np.flatnonzero(mask)
        split = fold or self.metadata["split"]
        base = self.folder / (f"development/{fold['name']}" if fold else "final/trees")
        result, thresholds = {}, {}
        for name in self.settings["trees"]:
            info = self.fit_tree(name, base / name, train, val, split["train_end"], split["val_end"])
            if phase == "validation":
                p = np.load(base / name / "validation_predictions.npz")["probability"]
            else:
                model = joblib.load(base / name / "model.pkl")
                x = self.input(name, mask, None, info["input_transform"])
                p = calibrated_probability(weighted_probability_logits(model.predict_proba(x)[:, 1], info["positive_weight"]), info["temperature"])
            result[name], thresholds[name] = p, info["threshold"]
        for name in ["graphsage", "dual_view", "behavior", "behavior_head", "graph_head"]:
            neural_ids, p, threshold = self.neural(name, phase, fold, seed)
            if not np.array_equal(neural_ids, ids):
                raise ValueError("Neural IDs do not align")
            result[name], thresholds[name] = p, threshold
        old_folder = self.old / (f"development/{fold['name']}/topology_tree" if fold else f"final/seed_{seed}/topology_tree")
        info = read_json(old_folder / "validation.json")
        if phase == "validation":
            result["enhanced_tree"] = np.load(old_folder / "validation_predictions.npz")["probability"]
        else:
            old_outputs = np.load(self.old / f"final/seed_{seed}/test_predictions.npz")
            if not np.array_equal(old_outputs["node_idx"], ids):
                raise ValueError("Old expert IDs do not align")
            result["enhanced_tree"] = old_outputs["expert_probability"][:, 2]
        thresholds["enhanced_tree"] = info["threshold"]
        return ids, result, thresholds

    def development(self):
        path = self.folder / "selection.json"
        if path.exists():
            return read_json(path)
        rows = []
        for fold in self.settings["folds"]:
            ids, predictions, _ = self.probabilities("validation", fold)
            y = self.labels[ids]
            for family, experts in self.settings["families"].items():
                matrix = np.column_stack([predictions[name] for name in experts])
                for weights in simplex_weights(len(experts), self.settings["weight_step"]):
                    key = "/".join(f"{w:g}" for w in weights)
                    p = blend_probabilities(matrix, weights)
                    rows.append({"family": family, "weights": key, "fold": fold["name"],
                                 "ap": float(average_precision_score(y, p))})
            pd.DataFrame(rows).to_csv(self.folder / "development.csv", index=False)
        table = pd.DataFrame(rows)
        scores = table.groupby(["family", "weights"], sort=False).ap.agg(["mean", "min"])
        choices = {}
        for family in self.settings["families"]:
            best = scores.loc[family].sort_values(["mean", "min"], ascending=False, kind="stable").iloc[0]
            weights = [float(v) for v in best.name.split("/")]
            choices[family] = {"experts": self.settings["families"][family], "weights": weights,
                               "mean_development_ap": float(best["mean"]), "worst_fold_ap": float(best["min"])}
        best_family = max(choices, key=lambda name: (choices[name]["mean_development_ap"], choices[name]["worst_fold_ap"]))
        selected = choices[best_family]
        selection = {"selected_family": best_family, **selected, "family_choices": choices,
                     "active_experts": [e for e, w in zip(selected["experts"], selected["weights"]) if w > 0],
                     "tested_weight_configurations": len(scores), "selection_rule": self.settings["selection_rule"],
                     "test_used_for_selection": False}
        save_json(path, selection)
        self.logger.info("Frozen selection %s", selection)
        return selection

    def final(self):
        with FileLock(str(self.folder / "experiment.lock"), timeout=5):
            selection = self.development()
            if (self.folder / "final_summary.json").exists():
                return read_json(self.folder / "final_summary.json")
            seeds = self.settings["final_seeds"]
            validation = []
            for seed in seeds:
                ids, predictions, thresholds = self.probabilities("validation", seed=seed)
                calibrations = {}
                for family, choice in selection["family_choices"].items():
                    matrix = np.column_stack([predictions[name] for name in choice["experts"]])
                    p = blend_probabilities(matrix, choice["weights"])
                    t = fit_temperature(logits_from_probability(p), self.labels[ids])
                    calibrations[family] = {"temperature": t, "threshold": choose_threshold(self.labels[ids], calibrated_probability(logits_from_probability(p), t)),
                                             "validation_ap": float(average_precision_score(self.labels[ids], p))}
                info = {"seed": seed, "families": calibrations, "expert_thresholds": thresholds}
                save_json(self.folder / f"final/seed_{seed}/calibration.json", info)
                validation.append(info)
            representative = max(validation, key=lambda row: row["families"][selection["selected_family"]]["validation_ap"])["seed"]
            freeze = {"selection": selection, "representative_seed": representative, "validation": validation,
                      "test_used_for_selection": False, "test_already_observed": True}
            save_json(self.folder / "final_freeze.json", freeze)
            rows, reviews = [], []
            for seed in seeds:
                ids, predictions, thresholds = self.probabilities("test", seed=seed)
                y = self.labels[ids]
                calibration = read_json(self.folder / f"final/seed_{seed}/calibration.json")
                folder = self.folder / f"final/seed_{seed}"
                combined_predictions = dict(predictions)
                for family, choice in selection["family_choices"].items():
                    matrix = np.column_stack([predictions[name] for name in choice["experts"]])
                    uncalibrated = blend_probabilities(matrix, choice["weights"])
                    c = calibration["families"][family]
                    combined_predictions[family] = calibrated_probability(logits_from_probability(uncalibrated), c["temperature"])
                    thresholds[family] = c["threshold"]
                combined_predictions["selected"] = combined_predictions[selection["selected_family"]]
                thresholds["selected"] = thresholds[selection["selected_family"]]
                old = np.load(self.old / f"final/seed_{seed}/test_predictions.npz")
                combined_predictions["old_redundant"] = old["probability"]
                thresholds["old_redundant"] = read_json(self.old / f"final/seed_{seed}/calibration.json")["threshold"]
                selected_active = selection["active_experts"]
                # Fixed-weight removal: one route deleted, remaining weights renormalized. No test selection.
                if len(selected_active) > 1:
                    weights = np.array(selection["weights"])
                    for i, name in enumerate(selection["experts"]):
                        if weights[i] <= 0:
                            continue
                        w = weights.copy(); w[i] = 0; w /= w.sum()
                        key = "without_"+name
                        combined_predictions[key] = blend_probabilities(np.column_stack([predictions[e] for e in selection["experts"]]), w)
                        # Threshold not needed: AP and ranking budget only for removal controls.
                for name, p in combined_predictions.items():
                    review = review_metrics(y, p, self.settings["review_top_k"], self.settings["review_fractions"])
                    if name.startswith("without_"):
                        result = {"pr_auc": float(average_precision_score(y, p)), "review": review}
                    else:
                        result = evaluate_predictions(y, p, thresholds[name]); result["review"] = review
                    save_json(folder / f"{name}_test.json", result)
                    rows.append({"candidate": name, "seed": seed, **{k: result[k] for k in ("pr_auc", "f1", "precision", "recall", "roc_auc", "brier_score") if k in result}})
                    for budget, counts in review.items():
                        reviews.append({"candidate": name, "seed": seed, "budget": budget, **counts})
                np.savez_compressed(folder / "test_predictions.npz", node_idx=ids, **combined_predictions)
            pd.DataFrame(rows).to_csv(self.folder / "final_comparison.csv", index=False)
            pd.DataFrame(reviews).to_csv(self.folder / "review_all_seeds.csv", index=False)
            summary = {**freeze, "dataset_fingerprint": self.metadata["fingerprint"]}
            save_json(self.folder / "final_summary.json", summary)
            return summary
