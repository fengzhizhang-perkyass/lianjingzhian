"""Real two-view Ethereum scoring and evidence over the frozen runtime release."""
from __future__ import annotations

from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
import json
import sqlite3

import joblib
import lightgbm as lgb
import numpy as np

from api.datasets.base import DatasetService
from api.datasets.ethereum_assets import digest, write_json


_SCALARS = {
    'out_fraction':('转出交易比例','比例'),
    'value_out_in_ratio':('转出／转入金额比','倍'),
    'peer_reciprocity':('双向交易对手比例','比例'),
    'same_peer_repeat_fraction':('重复交易对手交互比例','比例'),
    'peer_entropy':('交易对手分布熵','nat'),
    'max_peer_fraction':('最大交易对手占比','比例'),
    'active_days':('活跃天数','天'),
    'events_per_active_day':('每个活跃日交易次数','次／天'),
}
_STAT = {'sum':'总和','mean':'均值','std':'标准差','min':'最小值','max':'最大值','median':'中位数'}


def feature_description(name):
    if name in _SCALARS:
        return _SCALARS[name]
    for prefix,label in [('all_','全部交易'),('in_','转入交易'),('out_','转出交易')]:
        if not name.startswith(prefix):
            continue
        tail=name[len(prefix):]
        if tail=='count':return label+'次数','次'
        if tail=='unique_peers':return label+'独立交易对手数','个'
        if tail=='zero_fraction':return label+'零金额比例','比例'
        if tail.startswith('eth_'):return label+'金额'+_STAT[tail[4:]],'ETH'
        if tail.startswith('gap_hours_'):return label+'间隔'+_STAT[tail[10:]],'小时'
        if tail=='span_hours':return label+'活跃跨度','小时'
    if name.startswith('gas_gwei_'):
        return 'Gas价格'+_STAT[name[9:]],'Gwei'
    if name.startswith('gas_'):
        return 'Gas数量'+_STAT[name[4:]],'gas'
    return name,'模型输入值'


def wei_to_eth(value):
    """Exact decimal conversion, independent of Decimal context precision."""
    digits=str(value)
    if not digits.isdigit():
        raise ValueError('Wei amount must be a nonnegative integer string')
    digits=digits.zfill(19)
    return (digits[:-18]+'.'+digits[-18:]).rstrip('0').rstrip('.') or '0'


class EthereumService(DatasetService):
    def __init__(self, root):
        root=Path(root).resolve()
        folder=root/'artifacts/datasets/ethereum/current'
        if not (folder/'manifest.json').is_file():
            raise FileNotFoundError(
                '以太坊运行包尚未准备。请先运行 '
                'python scripts/prepare_v3_runtime.py --dataset ethereum，'
                '完成后再启动网页服务。')
        # Verify the prepared numeric inputs, graph and true evidence DB at load time.
        manifest=json.loads((folder/'manifest.json').read_text())
        for name,record in manifest['runtime_assets'].items():
            p=folder/name
            if digest(p)!=record['sha256']:
                raise ValueError('Ethereum runtime asset hash mismatch: '+name)
        for relative in manifest['model_paths'].values():
            if digest(root/relative)!=manifest['source_hashes'][relative]:
                raise ValueError('Ethereum model hash mismatch: '+relative)
        super().__init__(root,'ethereum',folder)
        self._x=np.load(folder/'features.npy',mmap_mode='r',allow_pickle=False)
        self._embedding=np.load(folder/'embeddings.npy',mmap_mode='r',allow_pickle=False)
        self._addresses=np.load(folder/'addresses.npy',allow_pickle=False)
        self._feature_names=json.loads((folder/'feature_names.json').read_text())
        self._score_row={str(a):i for i,a in enumerate(self._addresses)}
        if list(map(str,self._addresses))!=list(self.predictor.table.address_id):
            raise ValueError('Ethereum feature rows do not align with score rows')
        if self._x.shape!=(len(self._addresses),56) or self._embedding.shape!=(len(self._addresses),32):
            raise ValueError('Ethereum attribute or structural feature width mismatch')
        attribute=joblib.load(root/manifest['model_paths']['attribute'])
        joint_payload=joblib.load(root/manifest['model_paths']['joint'])
        joint=joint_payload['model']
        if joint_payload['feature_mode']!='behavior_and_embedding':
            raise ValueError('Wrong Ethereum joint feature mode')
        if not isinstance(attribute,lgb.LGBMClassifier) or not isinstance(joint,lgb.LGBMClassifier):
            raise ValueError('Ethereum branches must be the actual trusted fitted classifiers')
        self._attribute=attribute.booster_
        self._joint=joint.booster_
        if self._attribute.num_feature()!=56 or self._joint.num_feature()!=88:
            raise ValueError('Ethereum branch models and feature dimensions differ')

    def _connection(self):
        return sqlite3.connect('file:'+str(self.folder/'edge_evidence.sqlite')+'?mode=ro',uri=True)

    def edge_evidence(self, src, dst, limit=3):
        limit=max(1,min(int(limit),20))
        with closing(self._connection()) as conn:
            rows=conn.execute('SELECT tx_hash,src,dst,value_wei,block_timestamp,gas,gas_price_wei '
                'FROM transactions WHERE src=? AND dst=? ORDER BY block_timestamp DESC,tx_hash LIMIT ?',
                (str(src).lower(),str(dst).lower(),limit)).fetchall()
            result=[]
            for tx,source,target,value,timestamp,gas,price in rows:
                locations=[{'source_file':p,'source_row':int(line),'source_sha256':sha,
                    'record_semantics':'CSV record position; header counted'}
                    for p,line,sha in conn.execute('SELECT f.path,o.source_row,f.sha256 FROM observations o '
                        'JOIN source_files f ON f.source_id=o.source_id WHERE o.tx_hash=? '
                        'ORDER BY o.source_id,o.source_row LIMIT 8',(tx,))]
                result.append({'dataset_id':'ethereum','src':source,'dst':target,
                    'tx_hash':tx,'value_wei':value,'value_eth':wei_to_eth(value),'unit':'ETH',
                    'raw_value':value,'raw_unit':'Wei','block_timestamp':int(timestamp),
                    'timestamp_utc':datetime.fromtimestamp(timestamp,timezone.utc).isoformat(),
                    'gas':gas,'gas_price_wei':price,'relation_exists':True,
                    'source_file':locations[0]['source_file'] if locations else None,
                    'source_row':locations[0]['source_row'] if locations else None,
                    'raw_source_locations':locations,
                    'source_type':'observed_ethereum_transaction',
                    'graph_revision':self.metadata['graph_revision']})
            return result

    def _branch(self, key, values, weight, top_k=5):
        model=self._attribute if key=='attribute' else self._joint
        values=np.ascontiguousarray(values,dtype=np.float32).reshape(1,-1)
        probability=float(model.predict(values,num_threads=1)[0])
        margin=float(model.predict(values,raw_score=True,num_threads=1)[0])
        contributions=np.asarray(model.predict(values,pred_contrib=True,num_threads=1)[0],dtype=np.float64)
        residual=float(contributions.sum()-margin)
        if not np.isfinite(contributions).all() or abs(residual)>1e-5:
            raise RuntimeError('Ethereum branch attribution does not reconstruct raw margin')
        definitions=[('attribute','交易属性画像','由收支、交易节奏、交易对手及交易成本等56维真实属性构成',list(range(56)))]
        if key=='joint':
            definitions.append(('structure','交易结构表征','图编码器输出的32维潜在结构表示',list(range(56,88))))
        total_abs=float(np.abs(contributions[:-1]).sum())
        groups,evidence=[],{}
        for group,label,responsibility,indices in definitions:
            groups.append({'key':group,'label':label,'responsibility':responsibility,
                'contribution':float(contributions[indices].sum()),
                'absolute_contribution_share':float(np.abs(contributions[indices]).sum()/max(total_abs,1e-15))})
            items=[]
            for i in sorted(indices,key=lambda n:-abs(contributions[n]))[:top_k]:
                if i<56:
                    raw=self._feature_names[i]
                    feature,unit=feature_description(raw)
                else:
                    raw=f'structure_embedding_{i-56:02d}'
                    feature,unit=f'结构表示维度{i-55:02d}（潜在特征）','潜在表示值'
                items.append({'feature':feature,'raw_feature':raw,'feature_value':float(values[0,i]),
                    'model_input_value':float(values[0,i]),'unit':unit,'contribution':float(contributions[i]),
                    'direction':'increases_joint_margin' if contributions[i]>=0 else 'decreases_joint_margin',
                    'attribution_target':key+'_tree_raw_margin','branch_key':key,
                    'additivity_residual':residual})
            evidence[group]=items
        return {'key':key,'label':'属性分类分支' if key=='attribute' else '结构–属性联合分支',
            'probability':probability,'weight':weight,'weighted_probability':weight*probability,
            'raw_margin':margin,'base_value':float(contributions[-1]),'groups':groups,'evidence':evidence,
            'additivity_residual':residual,'attribution_target':key+'_tree_raw_margin',
            'feature_count':values.shape[1]}

    def analyze(self, address):
        lookup=self.predictor.lookup(address)
        address=lookup['address_id']
        row=self._score_row[address]
        x=np.asarray(self._x[row],dtype=np.float32)
        embedding=np.asarray(self._embedding[row],dtype=np.float32)
        attribute=self._branch('attribute',x,.6)
        joint=self._branch('joint',np.concatenate([x,embedding]),.4)
        probability=.6*attribute['probability']+.4*joint['probability']
        cached=self.predictor.by_address.loc[address]
        if (abs(attribute['probability']-float(cached.attribute_probability))>1e-12
                or abs(joint['probability']-float(cached.joint_probability))>1e-12
                or abs(probability-lookup['risk']['raw_probability'])>1e-12):
            raise RuntimeError('Live Ethereum model output differs from frozen risk release')
        summary=self.graph_summary(address)
        peers=self.source_graph.neighbors(address)
        structure={'dimensions':32,'max_sequence_length':32,
            'observed_transaction_count':int(x[self._feature_names.index('all_count')]),
            'observed_counterparty_count':len(peers),'out_degree':summary['out_degree'],
            'in_degree':summary['in_degree'],'scored_counterparties':summary['one_hop_scored_count'],
            'unscored_counterparties':summary['one_hop_unscored_count'],
            'embedding_l2_norm':float(np.linalg.norm(embedding.astype(np.float64))),
            'counterparty_preview':peers[:8],
            'preview_scope':'Observed graph counterparties; not an attention attribution or the full encoder input',
            'description':'账户与交易方向、金额、次数等信息形成32维潜在结构表示'}
        scoring={'kind':'dual_view','model_name':self.metadata['model_display_name'],
            'groups':joint['groups'],'evidence':joint['evidence'],
            'base_value':joint['base_value'],'raw_margin':joint['raw_margin'],
            'corrected_logit':joint['raw_margin'],'temperature':1.0,
            'additivity_residual':joint['additivity_residual'],'route_scores':{},
            'revision':self.metadata['risk_revision'],'branches':[attribute,joint],
            'calibration':self.calibration.describe(probability),
            'fusion':{'method':'weighted_probability','weights':{'attribute':.6,'joint':.4},
                'probability':probability,'reconstruction_error':probability-lookup['risk']['raw_probability']},
            'structure_summary':structure,
            'attribution_target':'joint_tree_raw_margin',
            'attribution_note':'分支贡献解释各自的原始输出；最终综合风险由结构与属性协同形成，并采用当前有效的概率处理。分支贡献不能相加为最终概率SHAP。'}
        return {**lookup,'model_display_name':self.metadata['model_display_name'],
            'scoring_analysis':scoring,'behavior_evidence':attribute['evidence']['attribute'],
            'graph_evidence':summary}


def prepare_trace_examples(service, max_candidates=300):
    """Select reproducible, actual graph witnesses; never use address labels."""
    path=service.trace_folder/'long_cases.json'
    provenance={'dataset_id':service.dataset_id,'graph_revision':service.metadata['graph_revision'],
        'risk_revision':service.metadata['risk_revision'],'tracing_revision':service.tracer.revision,
        'trace_scope':service.trace_scope,'calibration_revision':service.calibration.revision}
    overrides={**service.tracer.config.get('long_path_profile',{}),
        'edge_budget':int(service.tracer.config['edge_budget']),
        'top_paths':int(service.tracer.config['top_paths'])}
    if path.exists():
        previous=json.loads(path.read_text())
        if (all(previous.get(k)==v for k,v in provenance.items())
                and previous.get('versions')==service.versions
                and all(c.get('trace_config')==overrides for c in previous.get('cases',[]))):
            return previous
    long_cases,short_cases=[],[]
    checked=0
    for address in service.queue.address_id:
        if service.graph.degrees(address)[0]<1:
            continue
        checked+=1
        trace=service.tracer.trace(address,overrides)
        paths=[p for p in trace['top_paths'] if p['hop_count']>=2 and all(a in service.risks for a in p['nodes'])]
        if paths:
            best=max(paths,key=lambda p:len(p['nodes']))
            case={'address_id':address,'hops':len(best['nodes'])-1,'nodes':best['nodes'],
                'method':'actual existing graph and frozen model scores; no label selection',
                'trace_config':dict(overrides),'trace_scope':service.trace_scope,
                'versions':dict(service.versions)}
            if case['hops']>=4:
                long_cases.append(case)
            elif len(short_cases)<3:
                short_cases.append(case)
        if len(long_cases)>=3 or checked>=max_candidates:
            break
    result={**provenance,'cases':long_cases or short_cases,
        'selection':'Frozen predicted-risk order and actual directed paths; no risk labels opened',
        'candidates_traced':checked,'versions':dict(service.versions),
        'status':'prepared' if long_cases or short_cases else 'no_eligible_scored_path_found'}
    write_json(path,result)
    return result
