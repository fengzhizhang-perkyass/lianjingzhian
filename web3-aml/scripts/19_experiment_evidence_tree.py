import argparse
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from src.train.evidence_tree_experiments import EvidenceTreeExperiment

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--stage', choices=['selection', 'final', 'all'], default='all')
    args = parser.parse_args()
    experiment = EvidenceTreeExperiment()
    print(experiment.selection() if args.stage == 'selection' else experiment.final())
