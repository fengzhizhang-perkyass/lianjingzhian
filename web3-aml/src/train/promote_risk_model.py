"""Install the frozen candidate after guardrails pass; preserve the prior Demo."""
import shutil
from pathlib import Path

import pandas as pd
import yaml

from src.train.evaluate import save_evaluation
from src.utils.io import ROOT, read_json, save_json


def promote(root: Path = ROOT, name="risk_v2"):
    folder = root / "artifacts/experiments" / name
    review = read_json(folder / "deployment_review.json")
    if not review["eligible"]:
        raise RuntimeError("Frozen model did not pass the predeclared deployment guardrails; preserve the Demo.")
    summary = read_json(folder / "final_summary.json")
    manifest = read_json(folder / "manifest.json")
    selection = read_json(folder / "selection.json")
    processed = read_json(root / "data/processed/metadata.json")
    if manifest["dataset_fingerprint"] != processed["fingerprint"]:
        raise RuntimeError("Experiment belongs to different processed data.")
    backup = folder / "previous_demo"
    if not backup.exists():
        backup.mkdir(parents=True)
        for item in ("model", "metrics", "risk_scores", "traces", "reports"):
            source = root / "artifacts" / item
            if source.exists():
                shutil.copytree(source, backup / item)
        shutil.copy2(root / "config/model.yaml", backup / "model.yaml")
        shutil.copy2(root / "artifacts/demo_cases.json", backup / "demo_cases.json")
        save_json(backup / "backup_complete.json", {"experiment": name, "dataset_fingerprint": processed["fingerprint"]})
    if not (backup / "backup_complete.json").exists():
        raise RuntimeError("Incomplete backup. Repair it before changing the active Demo.")
    comparison = pd.DataFrame(summary["comparison"])
    for model in ("behavior", "graphsage", "dual_view", "lightgbm"):
        chosen = comparison[comparison.candidate == model].sort_values("validation_ap", ascending=False, kind="stable").iloc[0]
        source = (folder / chosen.run_id).resolve()
        if not source.is_relative_to(folder.resolve()):
            raise ValueError("Run path escaped the experiment directory.")
        result = read_json(source / "test.json")
        validation = read_json(source / "validation.json")
        result.update(scope=processed["scope"], dataset_fingerprint=processed["fingerprint"], split_method="time",
                      seed=int(chosen.seed), experiment_name=name, model_version="V1.1", best_val_pr_auc=float(chosen.validation_ap))
        target = root / "artifacts/model"
        if model == "lightgbm":
            shutil.copy2(source / "model.pkl", target / "lightgbm_model.pkl")
            shutil.copy2(source / "input_transform.json", target / "lightgbm_input_transform.json")
            shutil.copy2(source / "calibration.json", target / "lightgbm_calibration.json")
        else:
            if model == "dual_view" and chosen.run_id != summary["production_candidate"]["run_id"]:
                raise RuntimeError("Representative model disagrees with the frozen validation selection.")
            result.update(epochs_run=validation["epochs_run"], temperature=validation["temperature"])
            shutil.copy2(source / "model.pt", target / f"{model}_model.pt")
            shutil.copy2(source / "calibration.json", target / f"{model}_temperature.json")
            shutil.copy2(source / "history.json", target / f"{model}_training_history.json")
            if model == "dual_view":
                shutil.copy2(source / "model.pt", target / "best_model.pt")
                shutil.copy2(source / "calibration.json", target / "temperature.json")
                shutil.copy2(source / "history.json", target / "training_history.json")
                import torch
                checkpoint = torch.load(source / "model.pt", map_location="cpu", weights_only=True)
                save_json(target / "model_config.json", checkpoint["config"])
        save_evaluation(model, result, root)
    config = manifest["base_config"]
    config["feature_preprocessing"] = {key: value for key, value in selection["features"].items() if key != "name"}
    config["model"].update({key: value for key, value in selection["fusion"].items() if key not in {"name", "mode"}})
    settings = manifest["experiment"]
    config["training"].update(seed=summary["production_candidate"]["seed"], epochs=settings["final_epochs"],
                               learning_rate=settings["learning_rate"], early_stop_patience=settings["early_stop_patience"],
                               loss=selection["loss"], gradient_clip=settings["gradient_clip"],
                               auxiliary_behavior_weight=settings["auxiliary_behavior_weight"],
                               auxiliary_graph_weight=settings["auxiliary_graph_weight"])
    (root / "config/model.yaml").write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")
    active = read_json(root / "artifacts/metrics/comparison.json")
    pd.DataFrame(active).T[["precision", "recall", "f1", "pr_auc", "roc_auc", "scope"]].to_csv(root / "artifacts/metrics/comparison.csv", index_label="model")
    shutil.copy2(folder / "final_comparison.csv", root / "artifacts/metrics/multiseed_comparison.csv")
    save_json(folder / "promotion.json", {"model_installed": True, "risk_scores_need_refresh": True,
                                          "production_candidate": summary["production_candidate"], "backup": str(backup)})
    return {"installed": True, "next": "Recompute risk scores, rebuild Demo cases, validate before restarting the server."}
