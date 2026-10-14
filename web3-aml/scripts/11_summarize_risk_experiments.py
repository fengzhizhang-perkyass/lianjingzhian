import argparse
import _bootstrap
from src.train.experiment_report import write_experiment_report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Summarize frozen risk experiments without changing the Demo.")
    parser.add_argument("--name", default="risk_v2")
    args = parser.parse_args()
    print(write_experiment_report(name=args.name))
