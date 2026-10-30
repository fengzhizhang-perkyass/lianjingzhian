"""Same frozen feature arithmetic with buffered directional writes on macOS.

The original builder writes small strided slices into a 5.9GB mmap. Buffer one
direction in ordinary RAM and copy whole row blocks, avoiding repeated mmap page
copies. No numerical reduction/order changes, no labels and no model fitting.
The full output MUST match the pre-existing remote byte hash before serving.
"""
from pathlib import Path
import sys
import time
import json
import argparse
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from model_upgrade.transaction_evidence import build_features as original

frozen_pool = original.pool_direction


def buffered_pool(tx, a, t, total, sink, chunk=16):
    started = time.monotonic()
    buffer = np.zeros(sink.shape, dtype=np.float32)
    degree = frozen_pool(tx, a, t, total, buffer, chunk)
    print(json.dumps({'stage': 'direction_arithmetic_complete', 'seconds': time.monotonic()-started}), flush=True)
    for begin in range(0, len(sink), 4096):
        sink[begin:begin+4096] = buffer[begin:begin+4096]
    print(json.dumps({'stage': 'direction_buffer_written', 'seconds': time.monotonic()-started}), flush=True)
    return degree


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', default='model_upgrade/transaction_evidence/cache_v3_buffered')
    args = parser.parse_args()
    original.pool_direction = buffered_pool
    sys.argv = [sys.argv[0], '--output', args.output]
    original.main()
    from src.utils.io import file_sha256, save_json
    folder = ROOT/args.output
    actual = file_sha256(folder/'features.npy')
    expected = 'a2ed1c8b29d1fd6a55725b2746bf9f61ab09dec766767e51aac35fed324fb232'
    if actual != expected:
        raise RuntimeError('Buffered output differs from frozen bytes: '+actual)
    save_json(folder/'buffered_verification.json', {
        'feature_sha256':actual,'matches_frozen_full_cache':True,
        'numerical_algorithm_sha256':file_sha256(Path(original.__file__)),
        'write_optimization_sha256':file_sha256(Path(__file__)),
        'labels_loaded':False,'model_training_performed':False,
        'change':'directional RAM buffer then row-block copy; original numerical pool called unchanged'})
