import argparse
import _bootstrap
from src.train.promote_risk_model import promote


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Install only a frozen, guardrail-passing risk candidate.")
    parser.add_argument("--name", default="risk_v2")
    args = parser.parse_args()
    print(promote(name=args.name))
