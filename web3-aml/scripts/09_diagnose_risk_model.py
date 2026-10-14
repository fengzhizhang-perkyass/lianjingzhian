import _bootstrap
from src.train.diagnostics import diagnose


if __name__ == "__main__":
    result = diagnose()
    for mode, model in result["models"].items():
        val = model["phases"].get("val")
        if val:
            metrics = val["heads"]["fused"]["calibrated"]
            print(f"{mode}: validation logit AP={metrics['logit_ap']:.4f}, "
                  f"Brier={metrics['brier_score']:.4f}, ECE={metrics['ece']:.4f}")
    print("Saved: artifacts/metrics/risk_diagnostics/")
