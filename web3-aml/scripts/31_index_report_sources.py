"""Offline targeted source records for current-version report/demo addresses.

CSV record numbers and physical line spans are measured separately. Address
selection reproduces stable latest-timestep/last-row preprocessing. A raw edge
record establishes a relation only, not a unique transfer or amount attribution.
"""
try:
    import _bootstrap
except ModuleNotFoundError:
    from scripts import _bootstrap
import csv
import math
from pathlib import Path
import numpy as np
from src.utils.io import ROOT,read_json,load_config,save_json,file_sha256
from src.report.fact_catalog import digest


def build_index(root,addresses,edges):
    config=load_config('data.yaml',root)
    columns=config['columns']; files=config['dataset']; policy=config['preprocessing']['duplicate_policy']
    if policy!='latest_timestep': raise ValueError('Current raw locator supports latest_timestep only')
    address_rows={}; edge_rows={}; counts={}; source_files={}
    source=root/files['features_file']
    with source.open('r',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream);reader.fieldnames;previous=reader.line_num
        for i,row in enumerate(reader,1):
            start=previous+1;previous=reader.line_num
            address=row[columns['address_id']]
            if address not in addresses: continue
            counts[address]=counts.get(address,0)+1
            try: timestep=float(row[columns['timestep']])
            except ValueError: timestep=math.nan
            priority=math.inf if math.isnan(timestep) else timestep
            old=address_rows.get(address)
            if old is None or (priority,i)>tuple(old['selection_key']):
                address_rows[address]={'record_number':i,'physical_line_start':start,
                    'physical_line_end':reader.line_num,'fields':row,'selection_key':[priority,i]}
    # Infinity is selection-only state, never written to JSON.
    for address,row in address_rows.items():
        row.pop('selection_key');row['duplicate_count']=counts[address]
    print('Selected latest raw feature records:',len(address_rows),flush=True)
    source=root/files['edges_file']
    with source.open('r',encoding='utf-8-sig',newline='') as stream:
        reader=csv.DictReader(stream);reader.fieldnames;previous=reader.line_num
        for i,row in enumerate(reader,1):
            start=previous+1;previous=reader.line_num
            pair=(row[columns['src']],row[columns['dst']])
            if pair not in edges: continue
            key='\t'.join(pair)
            if key not in edge_rows:
                edge_rows[key]={'record_number':i,'physical_line_start':start,'physical_line_end':reader.line_num,
                                'duplicate_relation_records':0}
            edge_rows[key]['duplicate_relation_records']+=1
    for name,field in [('features','features_file'),('edges','edges_file')]:
        file=root/files[field];stat=file.stat()
        source_files[name]={'file':files[field],'size':stat.st_size,'mtime_ns':stat.st_mtime_ns,'sha256':file_sha256(file)}
    return {'dataset_fingerprint':read_json(root/'data/processed/metadata.json')['fingerprint'],
        'selection_policy':'latest timestep, missing timestep sorts last, stable raw order tie selects last',
        'source_files':source_files,'addresses':address_rows,'edges':edge_rows,
        'scope':'targeted recorded report addresses/edges; not complete graph index; unsigned local snapshots'}


def main():
    active=read_json(ROOT/'artifacts/risk_scores/metadata.json')
    addresses=set();edges=set()
    for file in (ROOT/'artifacts/reports').glob('*_evidence.json'):
        evidence=read_json(file)
        if evidence['meta'].get('dataset_fingerprint')!=active['dataset_fingerprint'] or evidence['meta'].get('risk_revision')!=active['risk_revision']:continue
        addresses.add(evidence['target']['address_id'])
        for path in evidence['trace_analysis'].get('top_paths',[]):
            addresses.update(path['nodes']);edges.update(zip(path['nodes'],path['nodes'][1:]))
    for sample in read_json(ROOT/'artifacts/experiments/tracing_long_paths_v2/selected_demo_traces.json'):
        if sample['method']!='long_connectors32': continue
        for path in sample['result']['top_paths']:
            addresses.update(path['nodes']);edges.update(zip(path['nodes'],path['nodes'][1:]))
    index=build_index(ROOT,addresses,edges)
    # Check raw CSV selection against the actual float32 processed table.
    mapping=read_json(ROOT/'data/processed/address_to_idx.json')
    features=read_json(ROOT/'data/processed/feature_names.json')
    raw=np.load(ROOT/'data/processed/raw_features.npy',mmap_mode='r')
    checked=0
    for address,row in index['addresses'].items():
        values=np.array([float(row['fields'][name]) if row['fields'][name] else np.nan for name in features],dtype=np.float32)
        values[~np.isfinite(values)]=np.nan
        assert np.array_equal(values,raw[mapping[address]],equal_nan=True),address
        checked+=1
    assert len(index['edges'])==len(edges)
    index['verified_processed_feature_rows']=checked
    index['index_hash']=digest(index)
    save_json(ROOT/load_config('reporting.yaml')['source_index_path'],index)
    print('Verified source index:',checked,'feature rows,',len(index['edges']),'directed relation pairs',flush=True)


if __name__=='__main__': main()
