import argparse
import _bootstrap
from src.train.train import train_model

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Train dual view and the two standalone ablations.")
    parser.add_argument("--mode", choices=["all", "behavior", "graphsage", "dual_view"], default="all")
    parser.add_argument("--epochs", type=int, default=None)
    args = parser.parse_args()
    for mode in (["behavior", "graphsage", "dual_view"] if args.mode == "all" else [args.mode]):
        train_model(mode=mode, epochs=args.epochs)
