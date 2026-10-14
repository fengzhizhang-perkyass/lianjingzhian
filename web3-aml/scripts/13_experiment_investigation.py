import argparse
import _bootstrap
from src.train.investigation_experiments import run

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Test topology expert and review priority without changing the base risk model.")
    parser.add_argument("--stage", choices=["development", "all"], default="all")
    args = parser.parse_args()
    result = run(stage=args.stage)
    print({key: value for key, value in result.items() if key != "comparison"})
