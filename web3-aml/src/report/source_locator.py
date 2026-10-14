"""Targeted raw CSV snapshot locators; no fabricated transaction identifiers."""
from pathlib import Path
import struct
from src.utils.io import read_json
from src.report.fact_catalog import digest


class SourceIndex:
    def __init__(self,data):
        self.data=data

    @classmethod
    def load(cls,root,path,fingerprint):
        source=root/path
        if not source.exists(): return None
        data=read_json(source)
        if data['dataset_fingerprint']!=fingerprint: return None
        signature=data.pop('index_hash')
        if digest(data)!=signature: raise ValueError('Raw source index integrity mismatch')
        data['index_hash']=signature
        for metadata in data['source_files'].values():
            file=(root/metadata['file']).resolve()
            if not file.is_relative_to(root.resolve()): raise ValueError('Raw locator must stay in project')
            info=file.stat()
            if info.st_size!=metadata['size'] or info.st_mtime_ns!=metadata['mtime_ns']:
                return None
        return cls(data)

    def feature(self,address,column,value):
        record=self.data['addresses'].get(address)
        if record is None or column not in record['fields']: return None
        raw=record['fields'][column]
        if value is not None:
            try:
                processed=struct.unpack('f',struct.pack('f',float(raw)))[0]
            except (ValueError,OverflowError): return None
            if processed!=value: return None
        return {'kind':'raw_csv_feature','file':self.data['source_files']['features']['file'],
            'file_sha256':self.data['source_files']['features']['sha256'],
            'record_number':record['record_number'],'physical_line_start':record['physical_line_start'],
            'physical_line_end':record['physical_line_end'],'column':column,'raw_value':raw,
            'address_id':address,'selection_policy':self.data['selection_policy'],
            'duplicate_records_for_address':record['duplicate_count'],'index_hash':self.data['index_hash']}

    def edges(self,edges):
        result=[]
        for src,dst in edges:
            record=self.data['edges'].get(src+'\t'+dst)
            if record is None: continue
            result.append({'kind':'raw_csv_relation','file':self.data['source_files']['edges']['file'],
                'file_sha256':self.data['source_files']['edges']['sha256'],
                'src':src,'dst':dst,**record,'index_hash':self.data['index_hash']})
        return result
