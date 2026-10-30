"""Explicit local CPU construction of topology-only groups on frozen releases."""
from __future__ import annotations

import argparse
import gc
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.io import file_sha256, save_json, load_config
from src.tracing.dense_group_index import DenseGroupIndex
from api.datasets.base import DatasetService


def build_for_dataset(root, dataset_id, *, force=False):
    root = Path(root)
    folder = root/'artifacts/datasets'/dataset_id/'current'
    before = file_sha256(folder/'risk_scores.parquet')
    # Base service only: no neural/tree model loading, training, inference or labels.
    service = DatasetService(root, dataset_id, folder)
    if service.group_index is not None and not force:
        return {'dataset_id':dataset_id, 'status':'reused',
                **service.group_index.metadata, 'risk_scores_unchanged':True}
    config = load_config('tracing.yaml', root)['dense_group_build']
    provenance = dict(service.tracer.provenance)
    print(json.dumps({'dataset_id':dataset_id,'status':'building','nodes':len(service.risks),
                      'max_anchors':config['max_anchors']},ensure_ascii=False),flush=True)
    index = DenseGroupIndex.build(service.graph, service.risks, config, provenance)
    index.validate_contents(service.risks)
    destination = folder/'dense_groups'/index.metadata['revision']
    index.save(destination)
    # Re-read exactly what will be served, including every edge and frozen statistic.
    verified = DenseGroupIndex.load(service.graph, destination, provenance, service.risks)
    if before != file_sha256(folder/'risk_scores.parquet'):
        raise RuntimeError('Frozen risk file changed during group construction')
    temporary = folder/'dense_groups/active.json.tmp'
    save_json(temporary, {'revision':verified.metadata['revision']})
    temporary.replace(folder/'dense_groups/active.json')
    result = {'dataset_id':dataset_id,'status':'built',**verified.metadata,
              'risk_scores_unchanged':True,'folder':str(destination)}
    del service, index, verified
    gc.collect()
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description='离线构建双链关联群组；不训练、不修改冻结风险分')
    parser.add_argument('--dataset', choices=('all','bitcoin','ethereum'), default='all')
    parser.add_argument('--force', action='store_true')
    args = parser.parse_args(argv)
    for dataset in (('bitcoin','ethereum') if args.dataset=='all' else (args.dataset,)):
        print(json.dumps(build_for_dataset(ROOT,dataset,force=args.force),ensure_ascii=False),flush=True)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
