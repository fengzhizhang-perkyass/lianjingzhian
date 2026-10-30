"""Explicitly regenerate and replay demonstration paths under active versions.

No model training/inference or label lookup is performed. Existing preparers use
frozen predicted-risk ordering and actual search output; this step then replays
every advertised case instead of merely replacing its version annotation.
"""
from __future__ import annotations
import argparse
import gc
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))

from api.datasets.base import DatasetService
from src.utils.io import file_sha256,save_json


def refresh_examples(root, dataset_id):
    root=Path(root)
    folder=root/'artifacts/datasets'/dataset_id/'current'
    scores_before=file_sha256(folder/'risk_scores.parquet')
    service=DatasetService(root,dataset_id,folder)
    if dataset_id=='bitcoin':
        from scripts.prepare_bitcoin_examples_v3 import prepare_bitcoin_examples
        result=prepare_bitcoin_examples(root,service=service)
    elif dataset_id=='ethereum':
        from api.datasets.ethereum import prepare_trace_examples
        result=prepare_trace_examples(service)
    else:
        raise ValueError('Unknown dataset')
    cases=result['cases']
    # Even a version-matched cache is checked by actually replaying the search.
    for case in cases:
        if case['versions']!=service.versions:
            raise ValueError('Demonstration was not prepared for the active versions')
        replay=service.trace(case['address_id'],dict(case['trace_config']))
        matches=[path for path in replay['top_paths'] if path['nodes']==case['nodes']]
        if not matches or case['hops']!=len(case['nodes'])-1:
            raise ValueError('Advertised demonstration is not returned by the active search')
        for src,dst in zip(case['nodes'],case['nodes'][1:]):
            if dst not in service.graph.iter_out_neighbors(src):
                raise ValueError('Demonstration contains an edge absent from the active graph')
        if any(address not in service.risks for address in case['nodes']):
            raise ValueError('Demonstration contains an unscored address')
        if replay['config']['top_paths']!=service.tracer.config['top_paths']:
            raise ValueError('Demonstration does not use the default returned-path count')
    if file_sha256(folder/'risk_scores.parquet')!=scores_before:
        raise RuntimeError('Frozen scores changed while refreshing examples')
    destination=(service.trace_folder if dataset_id=='ethereum' else service.folder)/'long_cases.json'
    summary={'dataset_id':dataset_id,'status':result['status'],
             'replayed_cases':len(cases),'hops':[case['hops'] for case in cases],
             'versions':dict(service.versions),'risk_scores_unchanged':True,
             'case_file':str(destination),'case_sha256':file_sha256(destination),
             'training_performed':False,'labels_opened':False}
    del service
    gc.collect()
    return summary


def main(argv=None):
    parser=argparse.ArgumentParser(description='显式刷新并真实重放双链长链示例，不重训、不改评分')
    parser.add_argument('--dataset',choices=('all','bitcoin','ethereum'),default='all')
    args=parser.parse_args(argv)
    results=[]
    for dataset in (('bitcoin','ethereum') if args.dataset=='all' else (args.dataset,)):
        result=refresh_examples(ROOT,dataset);results.append(result)
        print(json.dumps(result,ensure_ascii=False),flush=True)
    save_json(ROOT/'artifacts/v4_example_refresh.json',{'status':'passed','datasets':results})
    return 0


if __name__=='__main__':raise SystemExit(main())
