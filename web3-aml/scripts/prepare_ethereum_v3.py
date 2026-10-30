"""Prepare the frozen Ethereum workbench release; no training or evaluation."""
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from api.datasets.ethereum_assets import prepare_ethereum_release

if __name__=='__main__':
    prepare_ethereum_release(ROOT)
    from api.datasets.ethereum import EthereumService, prepare_trace_examples
    service=EthereumService(ROOT)
    examples=prepare_trace_examples(service)
    print('Ethereum real trace examples:',len(examples['cases']))
