import pandas as pd
import pytest

from src.train.experiment_report import write_experiment_report
from src.train.promote_risk_model import promote
from src.utils.io import save_json, read_json


def test_report_uses_validation_representative_and_paired_seed_comparison(tmp_path):
    folder = tmp_path / "artifacts/experiments/risk_v2"
    selected = {"candidate": "dual_view", "run_id": "final/dual_view/seed_42", "seed": 42, "validation_ap": .9}
    save_json(folder / "final_summary.json", {"production_candidate": selected, "promotion_guardrails_passed": True})
    save_json(folder / "selection.json", {"features": {"name": "test"}, "loss": "bce", "fusion": {"name": "gated"}})
    save_json(folder / "manifest.json", {"dataset_fingerprint": "test", "experiment": {"final_seeds": [42, 43, 44]}})
    save_json(folder / "historical_baseline.json", {"dual_view": {"f1": .2, "pr_auc": .1}})
    rows = []
    for candidate, offset in (("behavior", 0), ("graphsage", .1), ("fixed_fusion", .05), ("dual_view", .2), ("lightgbm", .1)):
        seeds = [42] if candidate == "lightgbm" else [42, 43, 44]
        for seed in seeds:
            run_id = f"final/{candidate}/seed_{seed}"
            rows.append({"candidate": candidate, "run_id": run_id, "seed": seed,
                         "validation_ap": .9 - (seed-42)*.1,
                         "precision": .5, "recall": .4, "f1": .44, "roc_auc": .7,
                         "pr_auc": .1 + (seed-42)*.1 + offset})
            save_json(folder / run_id / "test.json", {"review": {
                "top_100": {"reviewed": 100, "illicit_found": 20, "precision": .2, "recall": .1},
                "top_0.01_fraction": {"reviewed": 200, "illicit_found": 40, "precision": .2, "recall": .2}}})
    folder.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows).to_csv(folder / "final_comparison.csv", index=False)
    result = write_experiment_report(tmp_path)
    assert result["fusion_gains"]["graphsage"]["mean_ap_difference"] == pytest.approx(.1)
    assert result["fusion_gains"]["graphsage"]["seeds_with_positive_ap_gain"] == 3
    review = pd.read_csv(folder / "review_budget_comparison.csv")
    assert (review.seed == 42).all()  # Seed 44 has the highest test AP, but cannot be chosen.
    assert read_json(folder / "deployment_review.json")["production_candidate"] == selected


def test_failed_guardrails_prevent_any_promotion(tmp_path):
    save_json(tmp_path / "artifacts/experiments/risk_v2/deployment_review.json", {"eligible": False})
    with pytest.raises(RuntimeError, match="guardrails"):
        promote(tmp_path)
    assert not (tmp_path / "artifacts/model").exists()
