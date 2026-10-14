import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.train.graph_signal_experiments import GraphSignalExperiment

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['development', 'final', 'all'], default='all')
    args = parser.parse_args()
    experiment = GraphSignalExperiment()
    print(experiment.development() if args.stage == 'development' else experiment.final())
