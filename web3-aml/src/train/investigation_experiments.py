"""Topology expert and validation-selected late fusion, isolated from the Demo."""
from pathlib import Path
import copy
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

from src.utils.io import ROOT, read_json, save_json, load_config, file_sha256
from src.utils.logging import get_logger
from src.model.feature_transform import fit_feature_transform, transform_features
from src.model.topology_features import topology_features, NAMES
from src.model.calibration import weighted_probability_logits, fit_temperature, calibrated_probability
from src.train.evaluate import evaluate_predictions, choose_threshold
from src.train.risk_experiments import chronological_masks, review_metrics
from src.inference.investigation import blend_probabilities, simplex_weights


def logits_from_probability(values):
    values = np.clip(np.asarray(values, dtype=np.float64), 1e-12, 1-1e-12)
    return np.log(values)-np.log1p(-values)


class InvestigationExperiment:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.settings = load_config("investigation.yaml", root)["experiment"]
        self.folder = root / "artifacts/experiments" / self.settings["name"]
        self.source = root / "artifacts/experiments" / self.settings["source_experiment"]
        self.metadata = read_json(root / "data/processed/metadata.json")
        self.labels = np.load(root / "data/processed/labels.npy")
        self.times = np.load(root / "data/processed/timesteps.npy")
        self.raw = np.load(root / "data/processed/raw_features.npy", mmap_mode="r")
        self.edges = torch.load(root / "data/processed/edge_index_directed.pt", weights_only=True).numpy()
        self.names = read_json(root / "data/processed/feature_names.json")
        self.features = read_json(self.source / "selection.json")["features"]
        self.logger = get_logger("investigation_experiments", root)
        manifest = {"settings": self.settings, "dataset_fingerprint": self.metadata["fingerprint"],
                    "source_selection_sha256": file_sha256(self.source / "selection.json"),
                    "topology_features": NAMES, "test_already_observed": True,
                    "selection_uses_test": False}
        manifest["signature"] = hashlib.sha256(json.dumps(manifest, sort_keys=True).encode()).hexdigest()
        path = self.folder / "manifest.json"
        if path.exists() and read_json(path) != manifest:
            raise RuntimeError("Investigation config changed: use a new experiment name.")
        save_json(path, manifest)

    def masks(self, fold=None):
        if fold:
            return chronological_masks(self.labels, self.times, fold["train_end"], fold["val_end"])
        return tuple(np.load(self.root / f"data/processed/{phase}_mask.npy") for phase in ("train", "val"))

    def fit_tree(self, folder, train, val, train_cutoff, val_cutoff, seed, topology=True):
        if (folder / "validation.json").exists():
            return read_json(folder / "validation.json")
        folder.mkdir(parents=True, exist_ok=True)
        state = fit_feature_transform(self.raw, train, self.names, self.features)
        x = transform_features(self.raw, state)
        xtrain, xval = x[train], x[val]
        if topology:
            train_structure = topology_features(self.edges, len(x), self.times, train_cutoff)
            xtrain = np.column_stack([xtrain, train_structure[train]])
            del train_structure
            val_structure = topology_features(self.edges, len(x), self.times, val_cutoff)
            xval = np.column_stack([xval, val_structure[val]])
            del val_structure
        model = LGBMClassifier(**self.settings["tree"], class_weight="balanced", verbosity=-1,
                               metric="average_precision", random_state=seed)
        started = time.monotonic()
        model.fit(xtrain, self.labels[train], eval_set=[(xval, self.labels[val])],
                  callbacks=[early_stopping(self.settings["patience"], verbose=False)])
        positive_weight = float((self.labels[train] == 0).sum()/(self.labels[train] == 1).sum())
        logits = weighted_probability_logits(model.predict_proba(xval)[:, 1], positive_weight)
        temperature = fit_temperature(logits, self.labels[val])
        probability = calibrated_probability(logits, temperature)
        result = {"validation_ap": float(average_precision_score(self.labels[val], logits)),
                  "seed": seed, "temperature": temperature, "positive_weight": positive_weight,
                  "threshold": choose_threshold(self.labels[val], probability),
                  "best_iteration": model.best_iteration_, "seconds": time.monotonic()-started,
                  "topology": topology, "train_cutoff": train_cutoff, "val_cutoff": val_cutoff}
        joblib.dump(model, folder / "model.pkl")
        save_json(folder / "input_transform.json", state)
        np.savez_compressed(folder / "validation_predictions.npz", node_idx=np.flatnonzero(val), probability=probability)
        importance = pd.DataFrame({"feature": self.names+(NAMES if topology else []),
                                   "gain": model.booster_.feature_importance(importance_type="gain")})
        importance.sort_values("gain", ascending=False).to_csv(folder / "feature_importance.csv", index=False)
        save_json(folder / "validation.json", result)
        self.logger.info("Tree completed %s %s", folder.name, result)
        return result

    def neural_probability(self, folder, phase, train=None):
        values = np.load(folder / f"{phase}_predictions.npz")
        ids, logits = values["node_idx"], values["fused_logits"]
        if train is not None:  # Old development checkpoints precede weighted-odds correction.
            weight = float((self.labels[train] == 0).sum()/(self.labels[train] == 1).sum())
            logits = logits-np.log(weight)
            temperature = fit_temperature(logits, self.labels[ids])
        else:
            temperature = read_json(folder / "calibration.json")["temperature"]
        return ids, calibrated_probability(logits, temperature)

    def development(self):
        selection_path = self.folder / "selection.json"
        if selection_path.exists():
            return read_json(selection_path)
        rows, folds = [], []
        for fold in self.settings["folds"]:
            if fold["val_end"] > self.metadata["split"]["train_end"]:
                raise ValueError("Development fold extends beyond original training.")
            train, val = self.masks(fold)
            target_ids = np.flatnonzero(val)
            scores = []
            for expert in ("graphsage", "gated"):
                ids, probability = self.neural_probability(self.source / f"development/fusion/{expert}/{fold['name']}", "validation", train)
                if not np.array_equal(ids, target_ids):
                    raise ValueError("Development prediction IDs are not aligned.")
                scores.append(probability)
            for topology, name in ((False, "raw_tree"), (True, "topology_tree")):
                folder = self.folder / "development" / fold["name"] / name
                result = self.fit_tree(folder, train, val, fold["train_end"], fold["val_end"], self.settings["seed"], topology)
                probability = np.load(folder / "validation_predictions.npz")["probability"]
                rows.append({"candidate": name, "fold": fold["name"], "ap": result["validation_ap"]})
                if topology:
                    scores.append(probability)
            matrix = np.column_stack(scores)
            folds.append((fold["name"], self.labels[val], matrix))
        for weights in simplex_weights(len(self.settings["experts"]), self.settings["weight_step"]):
            key = "/".join(f"{w:g}" for w in weights)
            for fold, labels, matrix in folds:
                rows.append({"candidate": key, "fold": fold,
                             "ap": float(average_precision_score(labels, blend_probabilities(matrix, weights)))})
        table = pd.DataFrame(rows)
        table.to_csv(self.folder / "development.csv", index=False)
        # raw_tree is the topology ablation, not a weight configuration.
        blends = table[table.candidate.str.contains("/")].groupby("candidate")["ap"].agg(["mean", "min"])
        best = blends.sort_values(["mean", "min"], ascending=False, kind="stable").iloc[0]
        weights = [float(value) for value in best.name.split("/")]
        selection = {"experts": self.settings["experts"], "weights": weights,
                     "mean_development_ap": float(best["mean"]), "worst_fold_ap": float(best["min"]),
                     "selection_rule": "highest mean development AP, worst fold AP as tie breaker",
                     "test_used_for_selection": False}
        save_json(selection_path, selection)
        self.logger.info("Frozen investigation selection %s", selection)
        return selection

    def tree_probability(self, folder, mask, cutoff=None):
        state = read_json(folder / "input_transform.json")
        x = transform_features(self.raw, state)[mask]
        info = read_json(folder / "validation.json")
        if info["topology"]:
            structure = topology_features(self.edges, len(self.labels), self.times, cutoff)
            x = np.column_stack([x, structure[mask]])
        classifier = joblib.load(folder / "model.pkl")
        logits = weighted_probability_logits(classifier.predict_proba(x)[:, 1], info["positive_weight"])
        return calibrated_probability(logits, info["temperature"])

    def final(self):
        selection = self.development()
        if (self.folder / "final_summary.json").exists():
            return read_json(self.folder / "final_summary.json")
        train, val = self.masks()
        split = self.metadata["split"]
        source_manifest = read_json(self.source / "manifest.json")
        seeds = source_manifest["experiment"]["final_seeds"]
        validation = []
        for seed in seeds:
            folder = self.folder / f"final/seed_{seed}"
            self.fit_tree(folder / "topology_tree", train, val, split["train_end"], split["val_end"], seed)
            matrices = []
            for expert in ("graphsage", "dual_view"):
                ids, probability = self.neural_probability(self.source / f"final/{expert}/seed_{seed}", "validation")
                if not np.array_equal(ids, np.flatnonzero(val)):
                    raise ValueError("Final validation IDs differ.")
                matrices.append(probability)
            matrices.append(np.load(folder / "topology_tree/validation_predictions.npz")["probability"])
            uncalibrated = blend_probabilities(np.column_stack(matrices), selection["weights"])
            logits = logits_from_probability(uncalibrated)
            temperature = fit_temperature(logits, self.labels[val])
            probability = calibrated_probability(logits, temperature)
            info = {"seed": seed, "validation_ap": float(average_precision_score(self.labels[val], uncalibrated)),
                    "temperature": temperature, "threshold": choose_threshold(self.labels[val], probability)}
            save_json(folder / "calibration.json", info)
            validation.append(info)
        chosen = max(validation, key=lambda item: item["validation_ap"])
        # No reads of source test predictions before this freeze.
        freeze = {"selection": selection, "validation": validation, "representative_seed": chosen["seed"],
                  "seed_rule": "highest validation AP", "test_used_for_selection": False}
        save_json(self.folder / "final_freeze.json", freeze)
        test = np.load(self.root / "data/processed/test_mask.npy")
        ids = np.flatnonzero(test)
        rows = []
        for item in validation:
            seed, matrix = item["seed"], []
            folder = self.folder / f"final/seed_{seed}"
            tree = self.tree_probability(folder / "topology_tree", test)
            for expert in ("graphsage", "dual_view"):
                expert_ids, p = self.neural_probability(self.source / f"final/{expert}/seed_{seed}", "test")
                if not np.array_equal(expert_ids, ids):
                    raise ValueError("Test prediction IDs differ.")
                matrix.append(p)
            matrix.append(tree)
            combined = calibrated_probability(logits_from_probability(blend_probabilities(np.column_stack(matrix), selection["weights"])), item["temperature"])
            for name, p, threshold in [
                ("graphsage", matrix[0], read_json(self.source / f"final/graphsage/seed_{seed}/calibration.json")["threshold"]),
                ("dual_view", matrix[1], read_json(self.source / f"final/dual_view/seed_{seed}/calibration.json")["threshold"]),
                ("topology_tree", tree, read_json(folder / "topology_tree/validation.json")["threshold"]),
                ("review_priority", combined, item["threshold"]),
            ]:
                result = evaluate_predictions(self.labels[test], p, threshold)
                result["review"] = review_metrics(self.labels[test], p, self.settings["review_top_k"], self.settings["review_fractions"])
                save_json(folder / f"{name}_test.json", result)
                rows.append({"candidate": name, "seed": seed, **{k: result[k] for k in ("pr_auc", "f1", "recall", "precision", "roc_auc", "brier_score")}})
            np.savez_compressed(folder / "test_predictions.npz", node_idx=ids, expert_probability=np.column_stack(matrix), probability=combined)
        pd.DataFrame(rows).to_csv(self.folder / "final_comparison.csv", index=False)
        final = {**freeze, "comparison": rows, "dataset_fingerprint": self.metadata["fingerprint"]}
        save_json(self.folder / "final_summary.json", final)
        return final

    def raw_tree_ablation(self):
        """Matched-budget control, reported separately; cannot change frozen selection."""
        folder = self.folder / "ablation/raw_tree"
        if (folder / "test.json").exists():
            return read_json(folder / "test.json")
        if not (self.folder / "final_freeze.json").exists():
            raise RuntimeError("Freeze main candidates before final ablation.")
        train, val = self.masks()
        split = self.metadata["split"]
        info = self.fit_tree(folder, train, val, split["train_end"], split["val_end"], self.settings["seed"], topology=False)
        test = np.load(self.root / "data/processed/test_mask.npy")
        probability = self.tree_probability(folder, test)
        result = evaluate_predictions(self.labels[test], probability, info["threshold"])
        result["review"] = review_metrics(self.labels[test], probability, self.settings["review_top_k"], self.settings["review_fractions"])
        result["purpose"] = "matched topology ablation only; no model reselection"
        save_json(folder / "test.json", result)
        return result


def run(root=ROOT, stage="all"):
    experiment = InvestigationExperiment(root)
    with FileLock(str(experiment.folder / "experiment.lock"), timeout=5):
        return experiment.development() if stage == "development" else experiment.final()
