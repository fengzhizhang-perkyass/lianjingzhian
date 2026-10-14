"""Non-redundant evidence routes: development, freeze, final comparison."""
import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.train.role_experiments import RoleExperiment

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--stage", choices=["development", "final", "all"], default="all")
    args = parser.parse_args()
    experiment = RoleExperiment()
    print(experiment.development() if args.stage == "development" else experiment.final())
