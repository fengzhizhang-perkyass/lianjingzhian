from pathlib import Path
import pandas as pd
from src.utils.io import ROOT, load_config, save_json
from src.utils.logging import get_logger


def inspect_dataset(root: Path = ROOT):
    config = load_config("data.yaml", root)
    cols, dataset = config["columns"], config["dataset"]
    logger = get_logger("preprocess", root)
    result = {"dataset": dataset["name"], "files": {}}
    for kind in ("features", "labels", "edges"):
        path = root / dataset[f"{kind}_file"]
        if not path.exists():
            raise FileNotFoundError(f"Missing {path}. Run scripts/00_download_data.py first.")
        preview = pd.read_csv(path, nrows=5)
        rows = sum(len(chunk) for chunk in pd.read_csv(path, usecols=[0], chunksize=200000))
        result["files"][kind] = {"path": str(path), "shape": [rows, len(preview.columns)],
                                  "columns": preview.columns.tolist()}
        logger.info("%s shape=%s columns=%s", kind, result["files"][kind]["shape"], preview.columns.tolist())
    labels = pd.read_csv(root / dataset["labels_file"], dtype="str")
    result["raw_label_distribution"] = labels[cols["label"]].value_counts(dropna=False).to_dict()
    result["unique_addresses"] = int(labels[cols["address_id"]].nunique())
    logger.info("Labels: %s", result["raw_label_distribution"])
    save_json(root / "artifacts/metrics/dataset_inspection.json", result)
    return result
