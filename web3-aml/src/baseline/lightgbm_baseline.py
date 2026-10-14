from pathlib import Path
import joblib
import numpy as np
from lightgbm import LGBMClassifier, early_stopping
from src.utils.io import ROOT, load_config, read_json
from src.train.evaluate import evaluate_predictions, choose_threshold, save_evaluation
from src.utils.logging import get_logger
from src.model.feature_transform import fit_feature_transform, transform_features
from src.model.calibration import weighted_probability_logits, calibrated_probability, fit_temperature


def train_baseline(root: Path = ROOT):
    cfg = load_config("model.yaml", root)
    folder = root / "data/processed"
    x, y = np.load(folder / "features.npy"), np.load(folder / "labels.npy")
    train, val, test = (np.load(folder / f"{name}_mask.npy") for name in ("train", "val", "test"))
    metadata = read_json(folder / "metadata.json")
    state = None
    if cfg.get("feature_preprocessing"):
        state = fit_feature_transform(np.load(folder / "raw_features.npy"), train,
                                      read_json(folder / "feature_names.json"), cfg["feature_preprocessing"])
        x = transform_features(np.load(folder / "raw_features.npy"), state)
    classifier = LGBMClassifier(**cfg["baseline"], class_weight="balanced", verbosity=-1, metric="average_precision",
                                random_state=cfg["training"]["seed"])
    classifier.fit(x[train], y[train], eval_set=[(x[val], y[val])], eval_metric="average_precision",
                   callbacks=[early_stopping(cfg["training"]["early_stop_patience"], verbose=False)])
    positive_weight = float((y[train] == 0).sum()/(y[train] == 1).sum())
    val_logits = weighted_probability_logits(classifier.predict_proba(x[val])[:, 1], positive_weight)
    temperature = fit_temperature(val_logits, y[val], cfg["calibration"]["max_iter"])
    threshold = choose_threshold(y[val], calibrated_probability(val_logits, temperature))
    result = evaluate_predictions(y[test], calibrated_probability(
        weighted_probability_logits(classifier.predict_proba(x[test])[:, 1], positive_weight), temperature), threshold)
    result.update({"scope": metadata["scope"], "dataset_fingerprint": metadata["fingerprint"],
                   "split_method": metadata["split"]["method"]})
    save_evaluation("lightgbm", result, root)
    destination = root / "artifacts/model/lightgbm_model.pkl"
    destination.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(classifier, destination)
    from src.utils.io import save_json
    save_json(destination.with_name("lightgbm_calibration.json"), {"positive_weight": positive_weight,
                                                                "temperature": temperature, "method": "weighted_odds_then_temperature"})
    if state is not None:
        save_json(destination.with_name("lightgbm_input_transform.json"), state)
    get_logger("train", root).info("LightGBM F1=%.4f PR-AUC=%.4f", result["f1"], result["pr_auc"])
    return result
