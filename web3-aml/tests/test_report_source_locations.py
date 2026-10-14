import copy
import json
import struct
from pathlib import Path
import pytest
import yaml
from scripts._bootstrap import ROOT
from scripts import _bootstrap
from importlib import import_module
from src.report.fact_catalog import digest,FactCatalog
from src.report.source_locator import SourceIndex
from src.report.evidence_builder import build_evidence
from src.utils.io import load_config

build_index=import_module('scripts.31_index_report_sources').build_index


def workspace(tmp_path):
    (tmp_path/'config').mkdir();(tmp_path/'data/raw').mkdir(parents=True);(tmp_path/'data/processed').mkdir()
    cfg=load_config('data.yaml')
    (tmp_path/'config/data.yaml').write_text(yaml.safe_dump(cfg),encoding='utf-8')
    (tmp_path/'data/processed/metadata.json').write_text(json.dumps({'fingerprint':'g'}))
    (tmp_path/'data/raw/wallets_features.csv').write_text('address,Time step,F,note\nA,1,1.1,"first\ncontinued"\nA,2,2.2,last\nA,2,3.3,tie\n',encoding='utf-8')
    (tmp_path/'data/raw/AddrAddr_edgelist.csv').write_text('input_address,output_address\nA,B\nA,B\nB,C\n',encoding='utf-8')
    return tmp_path


def test_latest_record_tie_and_csv_physical_lines_are_real(tmp_path):
    root=workspace(tmp_path)
    index=build_index(root,{'A'},{('A','B'),('B','C')})
    row=index['addresses']['A']
    assert row['record_number']==3 and row['physical_line_start']==5
    assert row['fields']['F']=='3.3' and row['duplicate_count']==3
    assert index['edges']['A\tB']['record_number']==1
    assert index['edges']['A\tB']['physical_line_start']==2
    assert index['edges']['A\tB']['duplicate_relation_records']==2


def test_missing_timestep_matches_pandas_sort_last_and_multiline_span(tmp_path):
    root=workspace(tmp_path)
    file=root/'data/raw/wallets_features.csv'
    file.write_text('address,Time step,F,note\nA,,1.1,"first\ncontinued"\nA,2,2.2,last\n',encoding='utf-8')
    row=build_index(root,{'A'},set())['addresses']['A']
    assert row['record_number']==1 and row['physical_line_start']==2 and row['physical_line_end']==3


def test_source_index_detects_modified_registry_and_changed_raw_file(tmp_path):
    root=workspace(tmp_path);data=build_index(root,{'A'},{('A','B')});data['index_hash']=digest(data)
    file=root/'index.json';file.write_text(json.dumps(data))
    source=SourceIndex.load(root,'index.json','g')
    assert source.feature('A','F',struct.unpack('f',struct.pack('f',3.3))[0])
    assert source.feature('A','F',9) is None
    assert SourceIndex.load(root,'index.json','other') is None
    tampered=copy.deepcopy(data);tampered['addresses']['A']['record_number']=999
    file.write_text(json.dumps(tampered))
    with pytest.raises(ValueError,match='integrity'):SourceIndex.load(root,'index.json','g')
    file.write_text(json.dumps(data))
    raw=root/'data/raw/wallets_features.csv';raw.write_text(raw.read_text()+'A,3,4.4,new\n')
    assert SourceIndex.load(root,'index.json','g') is None


def test_target_path_and_frozen_table_score_mismatch_are_rejected():
    e=build_evidence({'address_id':'A','risk':{'overall_score':72.0}},trace_result={'seed_address':'A',
        'top_paths':[{'rank':1,'nodes':['A','B'],'node_risks':[70,50],'hop_count':1,'path_score':.3}]})
    with pytest.raises(ValueError,match='Seed risk'):FactCatalog(e,load_config('reporting.yaml'))
    e['trace_analysis']['top_paths'][0]['node_risks'][0]=72
    with pytest.raises(ValueError,match='frozen risk'):FactCatalog(e,load_config('reporting.yaml'),risk_scores={'A':72,'B':51})
