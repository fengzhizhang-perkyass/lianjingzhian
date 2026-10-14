import argparse
import _bootstrap
from src.train.risk_experiments import RiskExperiment


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Chronological, resumable risk-model experiments.")
    parser.add_argument("--stage", choices=["development", "fusion_fold", "final_train", "final"], default="development")
    parser.add_argument("--candidate", choices=["behavior", "graphsage", "dual_view", "fixed_fusion"])
    parser.add_argument("--fold")
    args = parser.parse_args()
    experiment = RiskExperiment()
    if args.stage == "fusion_fold":
        if not args.fold:
            parser.error("--fold is required for fusion_fold")
        result = experiment.train_fusion_fold(args.fold)
    elif args.stage == "final_train":
        if not args.candidate:
            parser.error("--candidate is required for final_train")
        result = experiment.train_final_candidate(args.candidate)
    else:
        result = experiment.development() if args.stage == "development" else experiment.final()
    print(result)
