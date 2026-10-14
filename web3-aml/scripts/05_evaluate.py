import _bootstrap
import pandas as pd
from src.utils.io import ROOT, read_json

if __name__ == "__main__":
    comparison = read_json(ROOT / "artifacts/metrics/comparison.json")
    required = {"lightgbm", "behavior", "graphsage", "dual_view"}
    if required-set(comparison):
        raise RuntimeError(f"Missing model evaluations: {required-set(comparison)}")
    fingerprints = {v["dataset_fingerprint"] for v in comparison.values()}
    if len(fingerprints) != 1:
        raise RuntimeError("Models were evaluated on different processed datasets. Retrain before comparison.")
    table = pd.DataFrame(comparison).T[["precision", "recall", "f1", "pr_auc", "roc_auc", "scope"]]
    table.to_csv(ROOT / "artifacts/metrics/comparison.csv", index_label="model")
    print(table.to_string())
