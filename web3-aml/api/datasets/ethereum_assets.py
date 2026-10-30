"""Prepare the frozen Ethereum runtime without fitting models or opening labels.

The model-address cohort and the wider relation graph are intentionally distinct.
Source CSVs are streamed; real transaction hashes and CSV record positions are
retained instead of using the internal pandas hashes from the training pipeline.
"""
from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import pickle
import sqlite3
import time
import zipfile
import zlib

import joblib
import numpy as np
import pandas as pd

RECIPE = 'ethereum_frozen_sadcf_runtime_v1'
HEADER = 'hash,nonce,block_hash,block_number,transaction_index,from_address,to_address,value,gas,gas_price,input,block_timestamp,max_fee_per_gas,max_priority_fee_per_gas,transaction_type'.split(',')
MODEL_FOLDER = Path('model_upgrade/ethereum/artifacts')
DATA_FOLDER = Path('data/external/ethereum')
SOURCE_FILES = [
    ('normal_eoa_transaction_in_slice_1000K.csv', 'to_address', 'normal_trans.zip'),
    ('normal_eoa_transaction_out_slice_1000K.csv', 'from_address', 'normal_trans.zip'),
    ('phisher_transaction_in.csv', 'to_address', 'phish_trans.zip'),
    ('phisher_transaction_out.csv', 'from_address', 'phish_trans.zip'),
]


def write_json(path, value):
    path = Path(path)
    temp = path.with_name(path.name+'.partial')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    os.replace(temp, path)


def digest(path, *, crc=False):
    h, c = hashlib.sha256(), 0
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8*1024*1024), b''):
            h.update(block)
            if crc:
                c = zlib.crc32(block, c)
    return (h.hexdigest(), c & 0xffffffff) if crc else h.hexdigest()


def stable_hash(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False).encode()).hexdigest()


def risk_level(score):
    return 'LOW' if score < 30 else 'MEDIUM' if score < 60 else 'HIGH' if score < 80 else 'CRITICAL'


def source_checks(root, folder):
    """Verify archives and raw CRC; cache by file identity only in this build dir."""
    records = {}
    previous_file = folder/'source_checks.json'
    previous = json.loads(previous_file.read_text()) if previous_file.exists() else {}
    expected = json.loads((root/DATA_FOLDER/'bert4eth_verified_sources.json').read_text())
    for archive, key in [('normal_trans.zip','normal_trans'), ('phish_trans.zip','phish_trans')]:
        p = root/DATA_FOLDER/archive
        ident = {'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
        old = previous.get(str(p.relative_to(root)),{})
        sha = old.get('sha256') if old.get('identity') == ident else digest(p)
        if sha != expected[key]['sha256']:
            raise ValueError('Ethereum source archive differs from verified download: '+archive)
        records[str(p.relative_to(root))] = {'sha256':sha,'identity':ident}
    for name, central, archive in SOURCE_FILES:
        p = root/DATA_FOLDER/'raw'/name
        ident = {'bytes':p.stat().st_size,'mtime_ns':p.stat().st_mtime_ns}
        with zipfile.ZipFile(root/DATA_FOLDER/archive) as z:
            member = next(i for i in z.infolist() if Path(i.filename).name == name)
        old = previous.get(str(p.relative_to(root)),{})
        if old.get('identity') == ident:
            sha, crc = old['sha256'], old['crc32']
        else:
            sha, crc = digest(p, crc=True)
        if p.stat().st_size != member.file_size or crc != member.CRC:
            raise ValueError('Ethereum extracted CSV does not match author archive: '+name)
        records[str(p.relative_to(root))] = {'sha256':sha,'crc32':crc,'identity':ident,
            'archive':str(DATA_FOLDER/archive),'central_column':central}
        print(json.dumps({'stage':'source_verified','file':name,'bytes':p.stat().st_size}),flush=True)
        write_json(previous_file,{**previous,**records})
    write_json(previous_file,records)
    return records


def exact_integer(value):
    try:
        d = Decimal(str(value))
        if not d.is_finite() or d < 0 or d != d.to_integral_value():
            return None
        return str(int(d))
    except (InvalidOperation, ValueError, OverflowError):
        return None


def _build_transactions(root, folder, addresses, checks):
    path = folder/'edge_evidence.sqlite'
    conn = sqlite3.connect(path)
    conn.executescript('''
        PRAGMA journal_mode=DELETE;
        PRAGMA synchronous=NORMAL;
        PRAGMA temp_store=MEMORY;
        PRAGMA cache_size=-98304;
        CREATE TABLE IF NOT EXISTS source_files (
          source_id INTEGER PRIMARY KEY, path TEXT UNIQUE, sha256 TEXT NOT NULL,
          central_column TEXT NOT NULL, header_rows INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS transactions (
          tx_hash TEXT PRIMARY KEY, src TEXT NOT NULL, dst TEXT NOT NULL,
          value_wei TEXT NOT NULL, block_timestamp INTEGER NOT NULL,
          gas TEXT, gas_price_wei TEXT);
        CREATE TABLE IF NOT EXISTS observations (
          center TEXT NOT NULL, tx_hash TEXT NOT NULL, source_id INTEGER NOT NULL,
          source_row INTEGER NOT NULL, UNIQUE(source_id,source_row));
        CREATE TABLE IF NOT EXISTS completed_sources (source_id INTEGER PRIMARY KEY);
    ''')
    address_set = set(map(str,addresses))
    totals = {}
    for source_id,(name,central,_) in enumerate(SOURCE_FILES,1):
        p = root/DATA_FOLDER/'raw'/name
        relative = str(p.relative_to(root))
        with p.open() as stream:
            header = stream.readline().startswith('hash,')
        conn.execute('INSERT OR IGNORE INTO source_files VALUES (?,?,?,?,?)',
            (source_id,relative,checks[relative]['sha256'],central,int(header)))
        if conn.execute('SELECT 1 FROM completed_sources WHERE source_id=?',(source_id,)).fetchone():
            print(json.dumps({'stage':'source_reused','file':name}),flush=True)
            continue
        usecols = ['hash','from_address','to_address','value','block_timestamp','gas','gas_price']
        reader = pd.read_csv(p,header=0 if header else None,names=None if header else HEADER,
            usecols=usecols,dtype=str,chunksize=100000,keep_default_na=False)
        selected_rows, invalid_rows, scanned = 0,0,0
        for chunk in reader:
            scanned += len(chunk)
            centers = chunk[central].str.lower()
            chunk = chunk.loc[centers.isin(address_set)].copy()
            if not len(chunk):
                continue
            chunk['_source_row'] = chunk.index+1+int(header)
            for k in ['hash','from_address','to_address']:
                chunk[k] = chunk[k].str.lower()
            valid = (chunk['hash'].str.fullmatch(r'0x[0-9a-f]{64}') &
                chunk['from_address'].str.fullmatch(r'0x[0-9a-f]{40}') &
                chunk['to_address'].str.fullmatch(r'0x[0-9a-f]{40}'))
            invalid_rows += int((~valid).sum())
            chunk = chunk.loc[valid]
            transactions, observations = [],[]
            for row in chunk[['hash','from_address','to_address','value','block_timestamp','gas','gas_price','_source_row']].itertuples(index=False,name=None):
                tx,src,dst,value,timestamp,gas,price,line = row
                value, timestamp = exact_integer(value), exact_integer(timestamp)
                if value is None or timestamp is None:
                    invalid_rows += 1
                    continue
                transactions.append((tx,src,dst,value,int(timestamp),exact_integer(gas),exact_integer(price)))
                observations.append((src if central=='from_address' else dst,tx,source_id,int(line)))
            conn.executemany('INSERT OR IGNORE INTO transactions VALUES (?,?,?,?,?,?,?)',transactions)
            conn.executemany('INSERT OR IGNORE INTO observations VALUES (?,?,?,?)',observations)
            conn.commit()
            selected_rows += len(observations)
            if scanned % 500000 == 0:
                print(json.dumps({'stage':'streaming','file':name,'scanned':scanned,'selected':selected_rows}),flush=True)
        conn.execute('INSERT INTO completed_sources VALUES (?)',(source_id,))
        conn.commit()
        totals[name] = {'scanned':scanned,'selected_rows':selected_rows,'invalid_rows':invalid_rows}
        write_json(folder/'stream_summary.json',totals)
        print(json.dumps({'stage':'source_completed','file':name,**totals[name]}),flush=True)
    print(json.dumps({'stage':'indexing_transactions'}),flush=True)
    conn.executescript('''
        CREATE INDEX IF NOT EXISTS tx_edge ON transactions(src,dst,block_timestamp);
        CREATE INDEX IF NOT EXISTS tx_destination ON transactions(dst,src);
        CREATE INDEX IF NOT EXISTS obs_tx ON observations(tx_hash);
        CREATE INDEX IF NOT EXISTS obs_center_tx ON observations(center,tx_hash);
    ''')
    conn.commit()
    return conn


def _build_graph(folder, conn, addresses, probabilities):
    # Preserve model row ordering for the scored centers; append other graph nodes.
    mapping = {str(a):i for i,a in enumerate(addresses)}
    ordered = list(map(str,addresses))
    for (a,) in conn.execute('SELECT src FROM transactions UNION SELECT dst FROM transactions ORDER BY 1'):
        if a not in mapping:
            mapping[a] = len(ordered)
            ordered.append(a)
    outgoing,incoming = defaultdict(list),defaultdict(list)
    edges = 0
    for src,dst in conn.execute('SELECT src,dst FROM transactions GROUP BY src,dst ORDER BY src,dst'):
        si,di = mapping[src],mapping[dst]
        outgoing[si].append(di)
        incoming[di].append(si)
        edges += 1
    for name,values in [('outgoing_neighbors.pkl',outgoing),('incoming_neighbors.pkl',incoming)]:
        with (folder/name).open('wb') as stream:
            pickle.dump(dict(values),stream,protocol=4)
    write_json(folder/'address_to_idx.json',mapping)
    write_json(folder/'idx_to_address.json',{str(i):a for i,a in enumerate(ordered)})
    print(json.dumps({'stage':'graph_ready','nodes':len(ordered),'edges':edges,'unscored':len(ordered)-len(addresses)}),flush=True)
    stats = []
    # Stats on every graph node support bridge scoring without imputing missing risk.
    known = len(addresses)
    risks = np.asarray(probabilities,dtype=np.float64)*100
    for i,a in enumerate(ordered):
        neighbors = set(outgoing.get(i,())) | set(incoming.get(i,()))
        neighbors.discard(i)
        scored = [n for n in neighbors if n < known]
        vals = risks[scored]
        stats.append((a,len(outgoing.get(i,())),len(incoming.get(i,())),len(neighbors),len(scored),
            len(neighbors)-len(scored),float(vals.mean()) if len(vals) else None,
            int(np.sum(vals >= 60)),float(np.mean(vals >= 60)) if len(vals) else None))
    pd.DataFrame(stats,columns=['address_id','out_degree','in_degree','one_hop_neighbor_count',
        'one_hop_scored_count','one_hop_unscored_count','one_hop_avg_risk',
        'one_hop_high_risk_count','one_hop_high_risk_ratio']).to_parquet(folder/'graph_statistics.parquet',index=False)
    unique_transactions = conn.execute('SELECT COUNT(*) FROM transactions').fetchone()[0]
    observations = conn.execute('SELECT COUNT(*) FROM (SELECT center,tx_hash FROM observations GROUP BY center,tx_hash)').fetchone()[0]
    return mapping, {'graph_nodes':len(ordered),'graph_edges':edges,
        'unscored_graph_nodes':len(ordered)-len(addresses),'unique_transactions':unique_transactions,
        'account_transaction_observations':observations}


def prepare_ethereum_release(root, *, progress=True):
    root = Path(root).resolve()
    parent = root/'artifacts/datasets/ethereum'
    final,build = parent/'current',parent/'.building'
    if (final/'manifest.json').exists():
        manifest = json.loads((final/'manifest.json').read_text())
        if manifest.get('recipe') != RECIPE:
            raise ValueError('Existing Ethereum release is a different recipe; preserve it.')
        for name,record in manifest['runtime_assets'].items():
            p=final/name
            if not p.is_file() or p.stat().st_size != record['bytes']:
                raise ValueError('Ethereum runtime asset missing or incomplete: '+name)
        return final
    build.mkdir(parents=True,exist_ok=True)
    started = time.perf_counter()
    source_hashes = {}
    selection_path = root/MODEL_FOLDER/'selection.json'
    selection = json.loads(selection_path.read_text())
    frozen_evaluation = json.loads((root/MODEL_FOLDER/'test_evaluation.json').read_text())
    if digest(selection_path) != frozen_evaluation['selection_file_sha256']:
        raise ValueError('Frozen Ethereum selection changed')
    recipe = selection['selected']['recipe']
    assert recipe == [{'name':'lightgbm_regularized','weight':.6},
        {'name':'igt4eth_light_behavior_and_embedding_tree','weight':.4}]
    dataset_path = root/DATA_FOLDER/'processed/dataset.npz'
    if digest(dataset_path) != selection['dataset_sha256']:
        raise ValueError('Ethereum model dataset changed after selection')
    source_hashes[str(dataset_path.relative_to(root))] = selection['dataset_sha256']
    source_hashes[str(selection_path.relative_to(root))] = digest(selection_path)
    # Access only X and addresses. Never deserialize/access y or test labels here.
    with np.load(dataset_path,allow_pickle=False) as dataset:
        X = np.asarray(dataset['X'],dtype=np.float32)
        addresses = dataset['addresses'].astype(str)
    assert X.shape==(103171,56) and len(set(addresses))==len(addresses)
    feature_names = json.loads((root/DATA_FOLDER/'processed/feature_names.json').read_text())
    assert len(feature_names)==56
    probability_arrays = {}
    for name in ['lightgbm_regularized','igt4eth_light_behavior_and_embedding_tree','igt4eth_light']:
        path = root/MODEL_FOLDER/(name+'_predictions.npz')
        expected = selection['prediction_sha256'][name]
        if digest(path)!=expected:
            raise ValueError('Frozen Ethereum predictions changed: '+name)
        source_hashes[str(path.relative_to(root))] = expected
        with np.load(path,allow_pickle=False) as d:
            probability_arrays[name] = d['probability'].copy()
            if name=='igt4eth_light':
                embeddings = d['embedding'].astype(np.float32)
    assert embeddings.shape==(len(addresses),32)
    probability = .6*probability_arrays['lightgbm_regularized']+.4*probability_arrays['igt4eth_light_behavior_and_embedding_tree']
    final_predictions_path=root/MODEL_FOLDER/'final_predictions.npz'
    with np.load(final_predictions_path,allow_pickle=False) as d:
        assert np.array_equal(addresses,d['addresses'])
        assert np.array_equal(probability,d['probability'])
    source_hashes[str(final_predictions_path.relative_to(root))]=digest(final_predictions_path)
    model_paths = {'attribute':str(MODEL_FOLDER/'lightgbm_regularized.joblib'),
        'joint':str(MODEL_FOLDER/'igt4eth_light_behavior_and_embedding_tree.joblib'),
        'encoder':str(MODEL_FOLDER/'igt4eth_light.pt')}
    inventory=json.loads((root/'model_upgrade/report_inventory/frozen_test_inventory.json').read_text())
    pinned_models={str(Path(m['path']).relative_to(root)):m['sha256'] for m in inventory['ethereum']['model_assets']}
    for relative in model_paths.values():
        sha=digest(root/relative)
        if sha!=pinned_models[relative]:
            raise ValueError('Frozen Ethereum model changed: '+relative)
        source_hashes[relative]=sha
    attribute=joblib.load(root/model_paths['attribute'])
    joint=joblib.load(root/model_paths['joint'])['model']
    jointX=np.concatenate([X,embeddings],axis=1)
    errors={}
    for key,model,features,name in [('attribute',attribute,X,'lightgbm_regularized'),
            ('joint',joint,jointX,'igt4eth_light_behavior_and_embedding_tree')]:
        pred=model.booster_.predict(features,num_threads=2)
        error=float(np.max(np.abs(pred-probability_arrays[name])))
        if error>1e-12:
            raise ValueError('Native Ethereum probability differs from frozen prediction: '+key)
        fixture=features[np.linspace(0,len(features)-1,128,dtype=int)]
        shap=model.booster_.predict(fixture,pred_contrib=True,num_threads=2)
        margin=model.booster_.predict(fixture,raw_score=True,num_threads=2)
        residual=float(np.max(np.abs(shap.sum(axis=1)-margin)))
        if residual>1e-5:
            raise ValueError('Ethereum branch TreeSHAP is not additive: '+key)
        errors[key]={'all_address_probability_max_error':error,'128_row_shap_margin_max_residual':residual}
    np.save(build/'features.npy',X,allow_pickle=False)
    np.save(build/'embeddings.npy',embeddings,allow_pickle=False)
    np.save(build/'addresses.npy',addresses,allow_pickle=False)
    write_json(build/'feature_names.json',feature_names)
    write_json(build/'input_snapshot.json',{'recipe':RECIPE,'source_hashes':source_hashes,'model_paths':model_paths})
    checks=source_checks(root,build)
    source_hashes.update({k:v['sha256'] for k,v in checks.items()})
    conn=_build_transactions(root,build,addresses,checks)
    mapping,graph_counts=_build_graph(build,conn,addresses,probability)
    conn.close()
    risk_table=pd.DataFrame({'address_id':addresses,'node_idx':[mapping[str(a)] for a in addresses],
        'overall_risk_score':probability*100,'risk_level':[risk_level(v*100) for v in probability],
        'attribute_probability':probability_arrays['lightgbm_regularized'],
        'joint_probability':probability_arrays['igt4eth_light_behavior_and_embedding_tree']})
    ranked=risk_table.sort_values(['overall_risk_score','address_id'],ascending=[False,True]).index
    rank=np.empty(len(risk_table),dtype=np.int64);rank[ranked]=np.arange(1,len(rank)+1)
    risk_table['risk_rank']=rank
    risk_table.to_parquet(build/'risk_scores.parquet',index=False)
    graph_revision=stable_hash({'recipe':RECIPE,'raw_sources':{k:v['sha256'] for k,v in checks.items()},**graph_counts})
    risk_revision=stable_hash({'models':{k:source_hashes[v] for k,v in model_paths.items()},
        'predictions':selection['prediction_sha256'],'recipe':recipe,'threshold':selection['selected']['validation']['threshold']})
    runtime_assets={}
    for p in sorted(build.iterdir()):
        if p.is_file() and p.suffix not in ['.partial'] and p.name!='manifest.json':
            runtime_assets[p.name]={'bytes':p.stat().st_size,'sha256':digest(p)}
    metadata=json.loads((root/DATA_FOLDER/'processed/metadata.json').read_text())
    manifest={'recipe':RECIPE,'dataset_id':'ethereum','dataset':'Ethereum phishing address dataset','label':'以太坊',
        'description':'真实以太坊钓鱼与背景地址数据快照','fingerprint':stable_hash({'dataset':selection['dataset_sha256'],'graph_revision':graph_revision}),
        'risk_revision':risk_revision,'feature_revision':stable_hash({'X':selection['dataset_sha256'],'embedding':selection['prediction_sha256']['igt4eth_light']}),
        'graph_revision':graph_revision,'model_display_name':'结构–属性双视图协同融合模型（SA-DCF）',
        'model_threshold':selection['selected']['validation']['threshold'],'feature_count':56,'joint_feature_count':88,
        'embedding_dimensions':32,'weights':{'attribute':.6,'joint':.4},'scored_addresses':len(addresses),
        'model_paths':model_paths,'source_hashes':source_hashes,'runtime_assets':runtime_assets,
        'native_verification':errors,'graph_evidence_scope':'Observed transactions incident to the scored centers; not complete chain history',
        'scope':'observed_snapshot','task':'Ethereum phishing address detection','split':metadata['split'],
        'labels_opened':False,'training_performed':False,'test_evaluation_performed':False,
        'prepared_seconds':time.perf_counter()-started,**graph_counts}
    write_json(build/'manifest.json',manifest)
    if final.exists():
        raise RuntimeError('Refusing to overwrite an existing release directory')
    build.rename(final)
    print(json.dumps({'stage':'completed','folder':str(final),'seconds':manifest['prepared_seconds'],**graph_counts,'native_verification':errors}),flush=True)
    return final
