"""Checks on exact transaction evidence and the frozen Ethereum service.

These checks do not fit models, index labels, or reevaluate benchmark metrics.
"""
import csv
from decimal import Decimal, localcontext
import hashlib
import json
from pathlib import Path
import sqlite3
from types import SimpleNamespace

import numpy as np
import pytest

from api.datasets.ethereum import EthereumService, feature_description, wei_to_eth
from scripts.prepare_v3_runtime import (
    COMMON_ASSETS, EXTRA_ASSETS, ReleaseVerificationError, verify_release,
)
from scripts.prepare_bitcoin_examples_v3 import prepare_bitcoin_examples

ROOT=Path(__file__).resolve().parents[1]
RELEASE=ROOT/'artifacts/datasets/ethereum/current'


def test_missing_release_never_builds_from_a_service_request(tmp_path):
    with pytest.raises(FileNotFoundError, match='prepare_v3_runtime.py'):
        EthereumService(tmp_path)
    assert not (tmp_path/'artifacts').exists()


def _tiny_release(root, dataset_id):
    folder=root/'artifacts/datasets'/dataset_id/'current'
    folder.mkdir(parents=True)
    manifest={'dataset_id':dataset_id, **{
        key:'frozen_revision' for key in
        ['fingerprint','risk_revision','feature_revision','graph_revision']}}
    records={}
    for name in sorted(COMMON_ASSETS|EXTRA_ASSETS[dataset_id]):
        data=('fixture:'+name).encode()
        (folder/name).write_bytes(data)
        sha=hashlib.sha256(data).hexdigest()
        records[name]=sha if dataset_id=='bitcoin' else {'bytes':len(data),'sha256':sha}
    field='runtime_hashes' if dataset_id=='bitcoin' else 'runtime_assets'
    manifest[field]=records
    (root/'source.bin').write_bytes(b'frozen input')
    manifest['source_hashes']={'source.bin':hashlib.sha256(b'frozen input').hexdigest()}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    return folder,manifest,field


@pytest.mark.parametrize('dataset_id',['bitcoin','ethereum'])
def test_verifier_supports_each_manifest_schema_without_mutating(tmp_path,dataset_id):
    folder,manifest,field=_tiny_release(tmp_path,dataset_id)
    before=(folder/'manifest.json').read_bytes()
    result=verify_release(tmp_path,dataset_id,check_sources=True)
    assert result['asset_checks_passed'] and result['source_files_checked']==1
    assert result['runtime_files_checked']==len(manifest[field])
    assert (folder/'manifest.json').read_bytes()==before
    (folder/'risk_scores.parquet').write_bytes(b'tampered')
    with pytest.raises(ReleaseVerificationError,match='不符'):
        verify_release(tmp_path,dataset_id)


def test_verifier_checks_sources_and_rejects_missing_manifest_entries(tmp_path):
    folder,manifest,field=_tiny_release(tmp_path,'ethereum')
    (tmp_path/'source.bin').write_bytes(b'changed')
    assert verify_release(tmp_path,'ethereum')['asset_checks_passed']
    with pytest.raises(ReleaseVerificationError,match='SHA256'):
        verify_release(tmp_path,'ethereum',check_sources=True)
    del manifest[field]['embeddings.npy']
    (folder/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ReleaseVerificationError,match='必需文件'):
        verify_release(tmp_path,'ethereum')


def test_verifier_rejects_source_path_escape_and_wrong_chain_identity(tmp_path):
    folder,manifest,field=_tiny_release(tmp_path,'bitcoin')
    manifest['source_hashes']={'../outside.bin':'0'*64}
    (folder/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ReleaseVerificationError,match='越界'):
        verify_release(tmp_path,'bitcoin',check_sources=True)
    manifest['dataset_id']='ethereum'
    (folder/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ReleaseVerificationError,match='身份不匹配'):
        verify_release(tmp_path,'bitcoin')


def test_bitcoin_examples_recompute_hops_and_bind_default_parameters(tmp_path):
    old=tmp_path/'artifacts/tracing/long_path_cases.json'
    old.parent.mkdir(parents=True)
    old.write_text(json.dumps({'cases':[{'address_id':'seed','hops':32,'seed_score':99}]}))
    old_bytes=old.read_bytes()
    folder=tmp_path/'artifacts/datasets/bitcoin/current'
    folder.mkdir(parents=True)
    calls=[]
    def trace(address,params):
        calls.append((address,params))
        return {'top_paths':[{'nodes':[address,'b','c','anchor'],'hop_count':3,'path_score':.75}]}
    service=SimpleNamespace(dataset_id='bitcoin',folder=folder,
        versions={'risk_revision':'new-risk','graph_revision':'current-graph'},
        metadata={'risk_revision':'new-risk','graph_revision':'current-graph'},
        tracer=SimpleNamespace(revision='trace-current',config={
            'long_path_profile':{'max_depth':32,'max_bridge_nodes':31},
            'edge_budget':2000,'top_paths':10}),
        predictor=SimpleNamespace(resolve=lambda a:a),
        queue=SimpleNamespace(address_id=['seed']),trace=trace)
    result=prepare_bitcoin_examples(tmp_path,service=service)
    assert result['cases'][0]['hops']==3
    assert result['cases'][0]['trace_config']==calls[0][1]
    assert result['cases'][0]['trace_config']['top_paths']==10
    assert result['versions']==service.versions
    assert 'seed_score' not in result['cases'][0]
    assert old.read_bytes()==old_bytes
    assert prepare_bitcoin_examples(tmp_path,service=service)==result
    assert len(calls)==1
    service.versions['risk_revision']='next-risk'
    service.metadata['risk_revision']='next-risk'
    updated=prepare_bitcoin_examples(tmp_path,service=service)
    assert len(calls)==2 and updated['risk_revision']=='next-risk'


def test_bitcoin_examples_do_not_invent_a_long_path(tmp_path):
    folder=tmp_path/'artifacts/datasets/bitcoin/current'
    folder.mkdir(parents=True)
    service=SimpleNamespace(dataset_id='bitcoin',folder=folder,versions={},
        metadata={'risk_revision':'risk','graph_revision':'graph'},
        tracer=SimpleNamespace(revision='trace',config={'edge_budget':2000,'top_paths':10}),
        predictor=SimpleNamespace(resolve=lambda a:a),queue=SimpleNamespace(address_id=['seed']),
        trace=lambda address,params:{'top_paths':[{'nodes':[address,'anchor'],'hop_count':1,'path_score':1}]})
    result=prepare_bitcoin_examples(tmp_path,service=service)
    assert result['cases']==[]
    assert result['status']=='no_returned_path_with_at_least_two_hops'


@pytest.fixture(scope='module')
def service():
    if not (RELEASE/'manifest.json').exists():
        pytest.skip('Run scripts/prepare_ethereum_v3.py to prepare real frozen Ethereum assets')
    return EthereumService(ROOT)


@pytest.mark.parametrize('wei',[
    '0','1','1000000000000000000','1000000000000000001',
    '100000000000000000000000000000000000000000000000000001',
])
def test_exact_wei_conversion(wei):
    with localcontext() as c:
        c.prec=100
        assert Decimal(wei_to_eth(wei))*Decimal(10)**18==Decimal(wei)


def test_all_56_features_have_readable_names():
    names=json.loads((ROOT/'data/external/ethereum/processed/feature_names.json').read_text())
    assert len(names)==56
    for name in names:
        label,unit=feature_description(name)
        assert label!=name and unit


def test_native_branch_fusion_and_separate_shap(service):
    for index in [0,len(service.queue)//2,len(service.queue)-1]:
        address=str(service.queue.iloc[index].address_id)
        analysis=service.analyze(address)
        scoring=analysis['scoring_analysis']
        assert scoring['kind']=='dual_view'
        a,j=scoring['branches']
        assert [a['feature_count'],j['feature_count']]==[56,88]
        assert a['attribution_target']!=j['attribution_target']
        assert abs(.6*a['probability']+.4*j['probability']-analysis['risk']['raw_probability'])<1e-12
        assert abs(analysis['risk']['calibrated_probability']-analysis['risk']['overall_score']/100)<1e-12
        assert scoring['attribution_target']=='joint_tree_raw_margin'
        for branch in [a,j]:
            assert abs(branch['base_value']+sum(g['contribution'] for g in branch['groups'])-branch['raw_margin'])<1e-5
            assert abs(branch['additivity_residual'])<1e-5
        assert analysis['risk']['overall_score']==float(service.predictor.by_address.loc[address].overall_risk_score)


def test_membership_is_scored_set_not_entire_graph(service):
    unknown=next(a for a in service.source_graph.address_to_idx if a not in service.risks)
    assert unknown not in service.graph.address_to_idx
    assert set(service.graph.address_to_idx)==set(service.risks)
    with pytest.raises(KeyError,match='可分析地址集合'):
        service.analyze(unknown)
    valid=str(service.queue.iloc[0].address_id)
    assert service.predictor.resolve(valid.upper())==valid
    assert service.predictor.resolve(str(int(service.predictor.by_address.loc[valid,'node_idx'])))==valid
    with pytest.raises(KeyError):service.analyze('0x'+'z'*40)


def test_historical_unscored_bridge_remains_in_source_but_not_active_trace(service):
    before=(RELEASE/'long_cases.json').read_bytes()
    cases=json.loads((RELEASE/'long_cases.json').read_text())['cases']
    assert cases
    case=next(c for c in cases if c['unscored_connection_nodes'])
    for address in case['unscored_connection_nodes']:
        assert address in service.source_graph.address_to_idx
        assert address not in service.risks and address not in service.graph.address_to_idx
    assert all(b in service.source_graph.out_neighbors(a) for a,b in zip(case['nodes'],case['nodes'][1:]))
    trace=service.trace(case['address_id'],case['trace_config'])
    assert trace['trace_scope']=='ethereum_scored_addresses_only'
    assert all(a in service.risks for p in trace['top_paths'] for a in p['nodes'])
    for p in trace['top_paths']:
        assert p['nodes'][-1] in service.risks
        assert service.risks[p['nodes'][-1]]>=trace['config']['risk_threshold']
        assert p['node_risks']==[service.risks[a] for a in p['nodes']]
    assert all(n['is_scored'] and n['risk_score'] is not None for n in trace['subgraph']['nodes'])
    for edge in trace['subgraph']['edges']:
        assert service.graph.address_to_idx[edge['dst']] in service.graph.outgoing[service.graph.address_to_idx[edge['src']]]
        assert edge['evidence']
        assert edge['dst'] in service.source_graph.out_neighbors(edge['src'])
    assert (RELEASE/'long_cases.json').read_bytes()==before


def test_long_case_label_is_returned_by_default_long_profile(service):
    meta=service.meta()
    assert meta['long_cases']
    case=meta['long_cases'][0]
    assert case['hops']>=2
    assert case['trace_scope']=='ethereum_scored_addresses_only'
    assert case['versions']==meta['versions']
    trace=service.trace(case['address_id'],case['trace_config'])
    assert trace['config']['top_paths']==meta['defaults']['top_paths']
    assert any(path['nodes']==case['nodes'] and len(path['nodes'])-1==case['hops']
        for path in trace['top_paths'])


def test_source_witness_points_to_original_transaction(service):
    with sqlite3.connect(RELEASE/'edge_evidence.sqlite') as conn:
        source_id,line,tx,source_file=conn.execute('SELECT o.source_id,o.source_row,o.tx_hash,f.path '
            'FROM observations o JOIN source_files f ON f.source_id=o.source_id '
            'ORDER BY o.source_id,o.source_row LIMIT 1').fetchone()
        src,dst=conn.execute('SELECT src,dst FROM transactions WHERE tx_hash=?',(tx,)).fetchone()
    source=ROOT/source_file
    with source.open() as stream:
        reader=csv.reader(stream)
        for _ in range(line):
            original=next(reader)
    assert original[0].lower()==tx
    assert original[5].lower()==src and original[6].lower()==dst
    witnesses=service.edge_evidence(src,dst,limit=20)
    actual=next(w for w in witnesses if w['tx_hash']==tx)
    assert actual['raw_value']==actual['value_wei']==str(int(Decimal(original[7])))
    assert actual['raw_unit']=='Wei' and actual['unit']=='ETH'
    assert actual['block_timestamp']==int(original[11])
    assert any(l['source_file']==source_file and l['source_row']==line for l in actual['raw_source_locations'])


def test_graph_observations_match_input_snapshot(service):
    assert service.manifest['scored_addresses']==103171
    assert service.manifest['account_transaction_observations']==1844436
    assert service.manifest['graph_nodes']>service.manifest['scored_addresses']
    assert service.manifest['unscored_graph_nodes']==len(service.source_graph.address_to_idx)-len(service.risks)
    assert len(service.graph.address_to_idx)==len(service.risks)==service.metadata['graph_nodes']
    assert service.metadata['graph_edges']==3228
    assert service.manifest['native_verification']['attribute']['all_address_probability_max_error']==0
    assert service.manifest['native_verification']['joint']['all_address_probability_max_error']==0
    assert service.manifest['labels_opened'] is False
    assert service.manifest['training_performed'] is False
    assert service.manifest['test_evaluation_performed'] is False
