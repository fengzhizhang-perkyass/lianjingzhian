"""Common graph, queue and trace service; risk scores may cover a graph subset."""
from pathlib import Path
import json
import math
import pickle
import threading
import re

import numpy as np
import pandas as pd

from src.tracing.graph_loader import DirectedGraph
from src.tracing.anchor_index import RiskAnchorIndex
from src.tracing.budgeted_tracer import BudgetedRelationTracer
from src.tracing.dense_group_index import DenseGroupIndex
from src.utils.io import load_config, read_json, file_sha256
from api.datasets.scored_graph import (
    TRACE_SCOPE, effective_risk_revision, load_graph, verify_scored_trace_graph,
)


LEVELS = ('LOW', 'MEDIUM', 'HIGH', 'CRITICAL')


def risk_level(score):
    return LEVELS[0 if score < 30 else 1 if score < 60 else 2 if score < 80 else 3]


def load_dense_groups(folder, graph, risks, provenance, config):
    """Load an optional, explicitly built index; never build during a request."""
    if not config.get('dense_group_enabled', True):
        return None, 'disabled', None
    try:
        pointer = read_json(Path(folder)/'dense_groups/active.json')
        revision = pointer['revision']
        if not isinstance(revision, str) or not re.fullmatch(r'[a-f0-9]{64}', revision):
            raise ValueError('Invalid dense group revision')
        index = DenseGroupIndex.load(graph, Path(folder)/'dense_groups'/revision, provenance, risks)
        if index.metadata['revision'] != revision:
            raise ValueError('Active dense group revision differs')
        if index.metadata['build_config'] != config['dense_group_build']:
            raise ValueError('Dense group construction settings have changed')
        return index, 'ready', None
    except FileNotFoundError as exc:
        return None, 'missing', str(exc)
    except (OSError, ValueError, KeyError, TypeError, AttributeError, IndexError) as exc:
        return None, 'invalid', str(exc)


class DatasetPredictor:
    def __init__(self, table, dataset_id, metadata):
        self.table = table
        self.dataset_id, self.metadata = dataset_id, metadata
        self.by_address = table.set_index('address_id', drop=False)
        self.by_index = table.set_index('node_idx', drop=False)
        if not self.by_address.index.is_unique or not self.by_index.index.is_unique:
            raise ValueError('Address and graph node indices must be unique')

    def resolve(self, value):
        value = str(value).strip()
        if self.dataset_id == 'ethereum':
            value = value.lower()
        if value in self.by_address.index:
            return value
        if value.isdigit() and int(value) in self.by_index.index:
            return str(self.by_index.loc[int(value), 'address_id'])
        label = '比特币' if self.dataset_id == 'bitcoin' else '以太坊'
        raise KeyError(f'该地址不存在于当前{label}可分析地址集合中，请检查输入或切换数据集后重试。')

    def lookup(self, value):
        address = self.resolve(value)
        row = self.by_address.loc[address]
        raw = float(row.get('raw_probability', row.overall_risk_score/100))
        current = float(row.get('calibrated_probability', row.overall_risk_score/100))
        result = {'overall_score': float(row.overall_risk_score), 'risk_level': str(row.risk_level),
                  'raw_probability': raw, 'calibrated_probability': current,
                  'calibration': {**self.metadata.get('calibration', {}),
                                  'raw_probability': raw, 'calibrated_probability': current}}
        return {'address_id': address, 'node_idx': int(row.node_idx),
                'dataset_id': self.dataset_id, 'risk': result}


class DatasetService:
    def __init__(self, root, dataset_id, folder):
        self.root, self.dataset_id, self.folder = Path(root), dataset_id, Path(folder)
        self.manifest = read_json(self.folder/'manifest.json')
        if self.manifest['dataset_id'] != dataset_id:
            raise ValueError('Release belongs to another dataset')
        for name, expected in self.manifest.get('runtime_hashes', {}).items():
            if file_sha256(self.folder/name) != expected:
                raise ValueError('Runtime release hash mismatch: '+name)
        self.metadata = {**self.manifest, 'dataset': self.manifest['label'],
                         'scope': 'frozen_observed_dataset', 'model_kind': dataset_id+'_v3'}
        from src.probability_calibration import load_calibration
        self.calibration = load_calibration(self.root, dataset_id, self.manifest)
        self.metadata['calibration'] = self.calibration.describe()
        self.metadata['frozen_risk_revision'] = self.manifest['risk_revision']
        self.metadata['risk_revision'] = effective_risk_revision(
            self.manifest['risk_revision'], self.calibration.revision)
        table = pd.read_parquet(self.folder/'risk_scores.parquet')
        table['address_id'] = table.address_id.astype(str)
        if len(table) != self.manifest['scored_addresses']:
            raise ValueError('Risk release row count mismatch')
        scores = table.overall_risk_score.to_numpy()
        if not np.isfinite(scores).all() or (scores < 0).any() or (scores > 100).any():
            raise ValueError('Risk scores must be finite within [0,100]')
        table['raw_probability'] = table.overall_risk_score.to_numpy(dtype=np.float64)/100
        table['calibrated_probability'] = self.calibration.apply(table.raw_probability.to_numpy())
        if self.calibration.describe()['mode'] != 'identity':
            table['overall_risk_score'] = table.calibrated_probability*100
        table['risk_level'] = [risk_level(float(value)) for value in table.overall_risk_score]
        scores = table.overall_risk_score.to_numpy()
        self.predictor = DatasetPredictor(table, dataset_id, self.metadata)
        self.risks = dict(zip(table.address_id, map(float, scores)))
        self.queue = table.sort_values(['overall_risk_score', 'address_id'], ascending=[False, True]).copy()
        self.queue['risk_rank'] = np.arange(1, len(table)+1)
        self.source_graph = load_graph(self.folder, self.metadata)
        if len(self.source_graph.address_to_idx) != self.manifest['graph_nodes']:
            raise ValueError('Graph release node count mismatch')
        if not set(self.risks).issubset(self.source_graph.address_to_idx):
            raise ValueError('Risk addresses are absent from graph')
        if any(int(row.node_idx) != self.source_graph.address_to_idx[row.address_id] for row in table.itertuples()):
            raise ValueError('Risk and graph address order mismatch')
        self.metadata['source_graph_revision'] = self.manifest['graph_revision']
        self.metadata['source_graph_nodes'] = self.manifest['graph_nodes']
        self.metadata['source_graph_edges'] = self.manifest['graph_edges']
        self.graph, self.trace_folder = self.source_graph, self.folder
        if dataset_id == 'ethereum':
            self.trace_folder = self.folder/'trace_scored'
            trace_manifest = verify_scored_trace_graph(
                self.trace_folder, source_manifest=self.manifest,
                calibration_revision=self.calibration.revision)
            if trace_manifest['risk_revision'] != self.metadata['risk_revision']:
                raise ValueError('Scored tracing risk revision differs from active probability pipeline')
            self.metadata.update({key: trace_manifest[key] for key in
                                  ('graph_revision', 'graph_nodes', 'graph_edges', 'trace_scope')})
            self.graph = load_graph(self.trace_folder, self.metadata)
            if set(self.graph.address_to_idx) != set(self.risks):
                raise ValueError('Scored tracing graph and risk addresses differ')
            maps = read_json(self.trace_folder/'node_mappings.json')
            for score_row, row in enumerate(table.itertuples()):
                if (maps['source_node_idx_by_address'].get(row.address_id) != int(row.node_idx)
                        or maps['score_row_by_address'].get(row.address_id) != score_row
                        or maps['trace_node_idx_by_address'].get(row.address_id) != self.graph.address_to_idx[row.address_id]):
                    raise ValueError('Scored tracing source, feature and node mapping mismatch')
        else:
            self.metadata['trace_scope'] = (dataset_id+'_scored_addresses_only'
                if set(self.risks) == set(self.graph.address_to_idx) else dataset_id+'_observed_directed_relations')
        self.trace_graph = self.graph
        self.trace_scope = self.metadata['trace_scope']
        # The source manifest retains the original full-graph coverage facts;
        # they are not statistics of the active scored-only tracing graph.
        if self.trace_scope == TRACE_SCOPE:
            self.metadata.pop('unscored_graph_nodes', None)
        config = dict(load_config('tracing.yaml', self.root))
        config['allow_unscored_nodes'] = self.trace_scope != TRACE_SCOPE
        config['show_observed_context'] = True
        provenance = {'dataset_id': dataset_id, 'dataset_fingerprint': self.metadata['fingerprint'],
                      'risk_revision': self.metadata['risk_revision'],
                      'graph_revision': self.metadata['graph_revision'],
                      'trace_scope': self.trace_scope,
                      'calibration_revision': self.calibration.revision}
        index_folder = (self.trace_folder/'anchor_index' if dataset_id == 'ethereum' else
                        self.folder/'anchor_index_v31'/self.metadata['risk_revision'][:16])
        try:
            index = RiskAnchorIndex.load(self.graph, index_folder, provenance, config['risk_threshold'], 64)
        except (FileNotFoundError, ValueError, KeyError):
            raise FileNotFoundError('追踪索引与当前范围或风险修订不匹配，请先显式准备运行包。') from None
        statistics = None
        if (self.trace_folder/'graph_statistics.parquet').exists():
            frame = pd.read_parquet(self.trace_folder/'graph_statistics.parquet')
            frame = frame.astype(object).where(pd.notna(frame), None)
            statistics = frame.set_index('address_id').to_dict(orient='index')
        self.group_index, self.group_status, self.group_index_error = load_dense_groups(
            self.folder, self.graph, self.risks, provenance, config)
        self.dense_group_revision = (self.group_index.metadata['revision'] if self.group_index is not None
                                     else self.group_status)
        self.metadata['dense_group_revision'] = self.dense_group_revision
        self.metadata['dense_group_status'] = self.group_status
        self.tracer = BudgetedRelationTracer(self.graph, self.risks, config, statistics, provenance,
                                             index, self.group_index, self.group_status)
        from src.report.report_audit import reporting_revision
        self.versions = {'dataset_id': dataset_id, 'dataset_fingerprint': self.metadata['fingerprint'],
                         'risk_revision': self.metadata['risk_revision'],
                         'feature_revision': self.metadata['feature_revision'],
                         'graph_revision': self.metadata['graph_revision'],
                         'trace_scope': self.trace_scope,
                         'calibration_revision': self.calibration.revision,
                         'tracing_revision': self.tracer.revision,
                         'dense_group_revision': self.dense_group_revision,
                         'reporting_revision': reporting_revision()}
        self.lock = threading.RLock()

    def meta(self):
        from src.report.audited_reporter import AuditedReportGenerator
        reporter = AuditedReportGenerator(self.root)
        high = self.queue.head(100)
        # Examples are selected by predictions/connectivity, never true labels.
        active_high = [a for a in high.address_id if self.graph.degrees(a)[0] > 0][:6]
        high_examples = (active_high + list(high.address_id))[:6]
        low_examples = list(self.queue.tail(3).address_id)
        cases_path = self.trace_folder/'long_cases.json'
        cases = read_json(cases_path).get('cases', []) if cases_path.exists() else []
        labels = (['交易行为画像', '邻域行为偏离', '资金流转特征'] if self.dataset_id == 'bitcoin'
                  else ['交易属性画像', '交易结构表征', '双视图融合结果'])
        defaults = {k: v for k, v in self.tracer.config.items()
                    if k not in ('anchor_index_path', 'long_path_cases', 'profile', 'protocol')}
        return {'ready': True, 'dataset_id': self.dataset_id, 'dataset_label': self.manifest['label'],
                'versions': self.versions, 'dataset': self.metadata,
                'model': {'display_name': self.manifest['model_display_name'],
                          'model_name': self.manifest['model_display_name']},
                'defaults': defaults, 'display_groups': labels,
                'examples': {'high_risk_known': high_examples[:3], 'low_risk_known': low_examples,
                             'high_risk_unknown': high_examples[3:6] or high_examples[:3]},
                'long_cases': cases,
                'dense_groups': {'enabled': self.group_index is not None,
                                 'status': self.group_status, 'revision': self.dense_group_revision,
                                 'group_count': len(self.group_index.groups) if self.group_index else 0},
                'capabilities': {'llm_configured': bool(reporter.config.get('enabled') and reporter.config.get('api_key')),
                                 'raw_csv': True, 'template_report': True, 'snapshot_only': True,
                                 'direct_report': True, 'partial_risk_graph': len(self.risks) < len(self.graph.address_to_idx)},
                'risk_counts': {key: int((self.predictor.table.risk_level == key).sum()) for key in LEVELS}}

    def queue_page(self, limit, offset):
        return {'dataset_id': self.dataset_id, 'total': len(self.queue), 'offset': offset, 'limit': limit,
                'rows': self.queue.iloc[offset:offset+limit][['address_id', 'risk_rank', 'overall_risk_score', 'risk_level']].to_dict('records')}

    def graph_summary(self, address):
        # Risk/model context remains the full observed graph even when tracing
        # intentionally uses an induced, scored-only graph.
        graph = getattr(self, 'source_graph', self.graph)
        neighbors = graph.neighbors(address)
        known = [self.risks[a] for a in neighbors if a in self.risks]
        first = neighbors[:200]
        two = sorted({a for b in first for a in graph.neighbors(b)[:200]}-set(neighbors)-{address})[:200]
        known_two = [self.risks[a] for a in two if a in self.risks]
        out_degree, in_degree = graph.degrees(address)
        return {'out_degree': out_degree, 'in_degree': in_degree,
                'one_hop_neighbor_count': len(neighbors), 'one_hop_scored_count': len(known),
                'one_hop_unscored_count': len(neighbors)-len(known),
                'one_hop_avg_risk': float(np.mean(known)) if known else None,
                'one_hop_high_risk_count': sum(r >= 60 for r in known),
                'one_hop_high_risk_ratio': sum(r >= 60 for r in known)/len(known) if known else None,
                'two_hop_avg_risk': float(np.mean(known_two)) if known_two else None,
                'two_hop_high_risk_ratio': sum(r >= 60 for r in known_two)/len(known_two) if known_two else None,
                'two_hop_sample_count': len(two), 'two_hop_scored_count': len(known_two),
                'neighbor_view': 'unique observed neighbors; risk statistics use scored nodes only',
                'two_hop_sampling': 'bounded deterministic neighbor sample', 'high_risk_threshold': 60}

    def trace(self, address, overrides=None):
        address = self.predictor.resolve(address)
        overrides = dict(overrides or {})
        if (overrides.get('risk_threshold', self.tracer.config['risk_threshold']) != self.tracer.anchor_index.metadata['threshold']
                or overrides.get('max_depth', self.tracer.config['max_depth']) > 64):
            overrides['anchor_index_enabled'] = False
        result = self.tracer.trace(address, overrides)
        result['dataset_id'] = self.dataset_id
        result['trace_scope'] = self.trace_scope
        result['source_graph_revision'] = self.metadata['source_graph_revision']
        result['calibration_revision'] = self.calibration.revision
        if self.trace_scope == TRACE_SCOPE:
            if any(not node['is_scored'] or node['address_id'] not in self.risks
                   for node in result['subgraph']['nodes']):
                raise RuntimeError('Scored-address tracing returned a node outside the risk cohort')
            result['statistics'].pop('unscored_nodes', None)
            result['selection_analysis'].pop('unscored_nodes_excluding_seed', None)
        for node in result['subgraph']['nodes']:
            node['risk_level'] = risk_level(node['risk_score']) if node['is_scored'] else 'UNSCORED'
        for path in result['top_paths']:
            path['source_references']['graph'] = self.dataset_id+'_observed_directed_relations'
        for edge in result['subgraph']['edges']:
            edge['evidence'] = self.edge_evidence(edge['src'], edge['dst'], limit=2)
        return result

    def edge_evidence(self, src, dst, limit=3):
        exists = (src in self.graph.address_to_idx and dst in self.graph.address_to_idx
                  and self.graph.address_to_idx[dst] in self.graph.outgoing.get(self.graph.address_to_idx[src], []))
        if not exists:
            return []
        return [{'src': src, 'dst': dst, 'relation_exists': True, 'dataset_id': self.dataset_id,
                 'source_type': 'processed_directed_relation', 'graph_revision': self.metadata['graph_revision'],
                 'src_node_idx': self.graph.address_to_idx[src], 'dst_node_idx': self.graph.address_to_idx[dst],
                 'amount': None, 'timestamp': None}]

    def _group_context(self, trace):
        if trace.get('dataset_id') != self.dataset_id or trace.get('seed_address') not in self.risks:
            raise ValueError('Group lookup belongs to another dataset or address')
        for key in ('dataset_id','dataset_fingerprint','risk_revision','graph_revision',
                    'trace_scope','calibration_revision','dense_group_revision'):
            if trace.get('provenance', {}).get(key) != self.versions.get(key):
                raise ValueError('Group lookup source version mismatch: '+key)

    def related_groups(self, trace, path_id=None):
        """Read seed and one saved path's groups without performing a new search."""
        self._group_context(trace)
        seed = trace['seed_address']
        nodes = [seed]
        if path_id is not None:
            path = next((p for p in trace['top_paths'] if p['path_id'] == path_id), None)
            if path is None:
                raise KeyError('该路径不属于当前追踪结果。')
            nodes = path['nodes']
        groups = self.group_index.path_evidence(seed, nodes) if self.group_index else []
        return {'dataset_id':self.dataset_id,'seed_address':seed,'path_id':path_id,
                'enabled':self.group_index is not None,'status':self.group_status,
                'revision':self.dense_group_revision,'groups':groups}

    def group_detail(self, trace, group_id, offset=0, limit=500, path_id=None):
        """Return a complete pageable group, restricted to an actual trace context."""
        self._group_context(trace)
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 2000:
            raise ValueError('Invalid dense group page bounds')
        allowed = {g['group_id'] for g in self.related_groups(trace, path_id)['groups']}
        if path_id is None:
            for path in trace['top_paths']:
                allowed.update(g['group_id'] for g in self.related_groups(trace, path['path_id'])['groups'])
        if self.group_index is None or group_id not in allowed:
            raise KeyError('该群组不属于当前地址或追踪路径。')
        group = self.group_index.groups[group_id]
        members, internal = group['member_addresses'], group['internal_edges']
        total = max(len(members), len(internal))
        nodes = [{'address_id':a,'risk_score':float(self.risks[a]),
                  'risk_level':risk_level(self.risks[a]),'is_scored':True}
                 for a in members[offset:offset+limit]]
        edges = []
        for src, dst in internal[offset:offset+limit]:
            if dst not in self.graph.iter_out_neighbors(src):
                raise ValueError('Dense group edge is absent from active graph')
            edges.append({'src':src,'dst':dst,'evidence':self.edge_evidence(src,dst,limit=2)})
        context_nodes = ([trace['seed_address']] if path_id is None else
                         next(p['nodes'] for p in trace['top_paths'] if p['path_id'] == path_id))
        summary = self.group_index._summary(group, [a for a in context_nodes if a in members],
                                            trace['seed_address'] in members)
        has_more = offset + limit < total
        return {'dataset_id':self.dataset_id,'group_id':group_id,'revision':self.dense_group_revision,
                'status':'ready','summary':summary,'nodes':nodes,'edges':edges,
                'offset':offset,'limit':limit,'total_nodes':len(members),'total_edges':len(internal),
                'next_offset':offset+limit if has_more else None,'has_more':has_more,'complete':not has_more}

    def evidence(self, analysis, trace):
        from src.report.dataset_reporting import build_dataset_evidence
        return build_dataset_evidence(self, analysis, trace)
