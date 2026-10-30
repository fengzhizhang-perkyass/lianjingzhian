"""Real frozen-data group validation and paired on/off search measurements."""
from __future__ import annotations
import gc
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:sys.path.insert(0,str(ROOT))
from api.datasets.base import DatasetService
from src.utils.io import file_sha256,save_json


def measures(result):
    paths=result['top_paths']
    edges={tuple(e) for p in paths for e in zip(p['nodes'],p['nodes'][1:])}
    return {'path_count':len(paths),'unique_edges':len(edges),
            'checks':result['search_budget']['actual_edge_inspections'],
            'elapsed_ms':result['search_budget']['elapsed_ms'],
            'group_evidence_count':len(result['suspicious_groups'])}


def verify_dataset(dataset_id):
    folder=ROOT/'artifacts/datasets'/dataset_id/'current'
    score_sha=file_sha256(folder/'risk_scores.parquet')
    service=DatasetService(ROOT,dataset_id,folder)
    assert service.group_index is not None,service.group_index_error
    index=service.group_index
    index.validate_contents(service.risks)
    group=sorted(index.groups.values(),key=lambda g:(-g['group_score'],g['group_id']))[0]
    seed=sorted(group['member_addresses'],key=lambda a:(-service.graph.degrees(a)[0],-service.risks[a],a))[0]
    trace=service.trace(seed)
    assert service.related_groups(trace)['groups']
    collected_nodes,collected_edges=[],[]
    offset=0
    while True:
        page=service.group_detail(trace,group['group_id'],offset=offset,limit=3)
        collected_nodes+=page['nodes'];collected_edges+=page['edges']
        if page['complete']:break
        offset=page['next_offset']
    assert [n['address_id'] for n in collected_nodes]==group['member_addresses']
    assert [[e['src'],e['dst']] for e in collected_edges]==group['internal_edges']
    assert all(n['is_scored'] and n['risk_score']==service.risks[n['address_id']] for n in collected_nodes)
    assert all(e['evidence'] for e in collected_edges)
    ordinary=[str(service.queue.iloc[round(i*(len(service.queue)-1)/11)].address_id) for i in range(12)]
    dense=sorted(index.memberships,key=lambda a:(-service.risks[a],a))
    dense=[dense[round(i*(len(dense)-1)/11)] for i in range(12)]
    pairs=[]
    for sample_name,seeds in [('queue_quantiles',ordinary),('group_member_quantiles',dense)]:
        for budget in (100,2000):
            for address in seeds:
                before=service.trace(address,{'edge_budget':budget,'dense_group_enabled':False})
                after=service.trace(address,{'edge_budget':budget,'dense_group_enabled':True})
                for result in (before,after):
                    assert result['search_budget']['actual_edge_inspections']<=budget
                    for path in result['top_paths']:
                        assert len(path['nodes'])==len(set(path['nodes']))
                        assert path['node_risks']==[service.risks[a] for a in path['nodes']]
                        assert all(b in service.graph.iter_out_neighbors(a) for a,b in zip(path['nodes'],path['nodes'][1:]))
                pairs.append({'sample':sample_name,'seed':address,'budget':budget,
                              'off':measures(before),'on':measures(after)})
    summaries=[]
    for sample in ('queue_quantiles','group_member_quantiles'):
        for budget in (100,2000):
            rows=[r for r in pairs if r['sample']==sample and r['budget']==budget]
            totals={mode:{key:sum(r[mode][key] for r in rows)
                          for key in ('path_count','unique_edges','checks','elapsed_ms')}
                    for mode in ('off','on')}
            base=totals['off']['checks']
            summaries.append({'sample':sample,'budget':budget,'n':len(rows),**totals,
                              'check_reduction_fraction':(base-totals['on']['checks'])/base if base else 0})
    assert score_sha==file_sha256(folder/'risk_scores.parquet')
    report={'dataset_id':dataset_id,'status':'passed','revision':index.metadata['revision'],
            'scope':service.trace_scope,'group_count':len(index.groups),
            'member_addresses':len(index.memberships),'score_sha256':score_sha,
            'risk_scores_unchanged':True,'sample_seed':seed,'sample_group_id':group['group_id'],
            'sample_group_members':group['member_count'],'sample_group_edges':group['edge_count'],
            'full_pagination_verified':True,'group_contents_verified':True,
            'paired_comparison':summaries,'paired_rows':pairs,
            'measurement_scope':'Local in-process tracing after assets/index load. No labels. Not API or rendering latency.'}
    del service,index
    gc.collect()
    return report


def main():
    results=[]
    for dataset in ('bitcoin','ethereum'):
        result=verify_dataset(dataset);results.append(result)
        print(json.dumps({k:v for k,v in result.items() if k!='paired_rows'},ensure_ascii=False),flush=True)
    path=ROOT/'artifacts/v4_groups_backend_verification.json'
    save_json(path,{'status':'passed','datasets':results})
    return 0


if __name__=='__main__':raise SystemExit(main())
