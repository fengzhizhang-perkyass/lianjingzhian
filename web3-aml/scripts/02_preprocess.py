import argparse
import _bootstrap
from src.data.preprocess import preprocess

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Prepare the full dataset or an explicitly marked real-data pilot.")
    parser.add_argument("--max-nodes", type=int, default=None)
    preprocess(max_nodes=parser.parse_args().max_nodes)
