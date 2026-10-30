"""Dataset-scoped evidence, native-model facts and audited report generation.

Model predictions and explanations are inputs, never inferred from labels here.
The LLM still only chooses schema-constrained factual claims. All displayed
numbers and prose forms are rendered by the program from frozen sources.
"""
from __future__ import annotations

import copy
from datetime import datetime, timezone
import math
from pathlib import Path
import re
from decimal import Decimal, ROUND_HALF_UP, localcontext

from api.reporting import WebReportGenerator, failure_code
from src.report.claim_renderer import number, render_fact, safe
from src.report.claim_schema import SECTIONS
from src.report.fact_catalog import FactCatalog, GRAPH_FIELDS, digest
from src.report.report_audit import save_bundle


PUBLIC_METHODS = {
    'bitcoin': '多维证据风险识别',
    'ethereum': 'SA-DCF 结构–属性双视图协同融合模型',
}
DATASET_LABELS = {'bitcoin': '比特币', 'ethereum': '以太坊钓鱼地址'}
LEVELS = {'LOW': '低风险', 'MEDIUM': '中风险', 'HIGH': '高风险',
          'CRITICAL': '极高风险', 'UNSCORED': '未评分', 'UNAVAILABLE': '不可用'}
HEADINGS = ('地址风险概述', '交易属性与模型证据', '交易结构与归因证据',
            '多跳关联路径', '综合研判', '研判依据与使用范围')
SCORED_TRACE_SCOPE = 'ethereum_scored_addresses_only'
LEVEL_INTERVALS = {'LOW': '0≤分数<30', 'MEDIUM': '30≤分数<60',
                   'HIGH': '60≤分数<80', 'CRITICAL': '80≤分数≤100'}
POLICIES = {
    'human_review': '建议结合地址评分、关键特征、交易结构和路径见证进行人工复核。',
    'model_boundary': '风险分是当前模型对数据集中地址的预测，不是犯罪认定或真实身份结论。',
    'relation_boundary': '关系路径描述观测到的有向连接；没有逐跳资金连续性验证时，不将其认定为同一笔资金的连续流动。',
    'search_boundary': '搜索受深度和关系检查预算限制，未展示某条路径不表示该路径不存在。',
    'attribution_boundary': '特征与分组归因解释相应模型的原始输出，不是因果贡献或独立风险概率。',
    'snapshot_boundary': '本报告基于当前固定数据快照和模型，未查询数据集之外的实时链上信息。',
    'unscored_boundary': '未评分交易对手只提供关系连接，不将其当作零风险，也不将其作为风险锚点。',
    'source_name_boundary': '源文件与目录名称只用于记录定位，不将其中的类别词当作地址标签或风险判断证据。',
}


def _copy(value):
    """Convert trusted numerical containers to plain, finite JSON values."""
    if isinstance(value, dict):
        return {str(k): _copy(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_copy(v) for v in value]
    if hasattr(value, 'tolist'):
        return _copy(value.tolist())
    if hasattr(value, 'item'):
        return _copy(value.item())
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError('Evidence contains a nonfinite number')
    return copy.deepcopy(value)


def _same(actual, expected, message, tolerance=1e-8):
    FactCatalog._number(actual, 'raw_margin')
    FactCatalog._number(expected, 'raw_margin')
    if not math.isclose(actual, expected, rel_tol=0, abs_tol=tolerance):
        raise ValueError(message)


def _sigmoid(value):
    return 1 / (1 + math.exp(-value)) if value >= 0 else math.exp(value) / (1 + math.exp(value))


def risk_score_text(value):
    """Format risk scores only; source facts always retain their exact numbers."""
    FactCatalog._number(value, 'score_0_100')
    rounded = Decimal(str(value)).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
    if value < 100 and rounded == Decimal('100.00'):
        return '>99.99'
    return format(rounded, '.2f')


def _risk_level(value):
    FactCatalog._number(value, 'score_0_100')
    return 'LOW' if value < 30 else 'MEDIUM' if value < 60 else 'HIGH' if value < 80 else 'CRITICAL'


def _trace_scope(evidence):
    meta = evidence.get('meta', {})
    return meta.get('trace_scope', meta.get('versions', {}).get('trace_scope'))


def _check_scored_trace(trace, graph, risk_scores, expected_scope):
    if expected_scope != SCORED_TRACE_SCOPE:
        return
    scopes = [trace.get('trace_scope'), trace.get('provenance', {}).get('trace_scope')]
    if not any(scope is not None for scope in scopes) or any(
            scope is not None and scope != expected_scope for scope in scopes):
        raise ValueError('Trace scope differs from the scored-address release')
    if risk_scores is None:
        raise ValueError('Scored-address trace requires a verified risk table')
    subgraph = trace.get('subgraph')
    if not isinstance(subgraph, dict) or not isinstance(subgraph.get('nodes'), list) or not isinstance(subgraph.get('edges'), list):
        raise ValueError('Scored-address trace requires its actual returned subgraph')
    for node in subgraph['nodes']:
        address = node.get('address_id')
        if address not in risk_scores or node.get('is_scored') is not True or node.get('risk_score') is None:
            raise ValueError('Scored-address trace contains an unscored node')
        _same(node['risk_score'], risk_scores[address], 'Trace node risk differs from the current table')
    for edge in subgraph['edges']:
        src, dst = edge.get('src'), edge.get('dst')
        if src not in risk_scores or dst not in risk_scores:
            raise ValueError('Scored-address trace edge has an unscored endpoint')
        if graph is not None and dst not in graph.out_neighbors(src):
            raise ValueError('Trace edge absent from the scored directed graph')
    for path in trace.get('top_paths', []):
        if any(address not in risk_scores for address in path['nodes']) or any(
                value is None for value in path['node_risks']):
            raise ValueError('Scored-address path contains an unscored node')


def _check_edge_record(record,src,dst,dataset_id):
    if not isinstance(record,dict) or record.get('src')!=src or record.get('dst')!=dst:
        raise ValueError('Transaction witness does not match the directed relation')
    if record.get('dataset_id',dataset_id)!=dataset_id:
        raise ValueError('Transaction witness belongs to a different dataset')
    if record.get('tx_hash') is not None and not re.fullmatch(r'0x[0-9a-fA-F]{64}',record['tx_hash']):
        raise ValueError('Transaction witness requires an actual chain transaction hash')
    if record.get('value_wei') is not None:
        if not isinstance(record['value_wei'],str) or not re.fullmatch(r'[0-9]+',record['value_wei']):
            raise ValueError('Transaction value must preserve exact integer Wei')
        if record.get('value_eth') is not None:
            if not isinstance(record['value_eth'],str) or not re.fullmatch(r'[0-9]+(?:\.[0-9]+)?',record['value_eth']):
                raise ValueError('Transaction ETH value must preserve exact decimal text')
            with localcontext() as context:
                context.prec=max(100,len(record['value_wei'])+len(record['value_eth'])+20)
                if Decimal(record['value_eth'])!=Decimal(record['value_wei'])/Decimal(10**18):
                    raise ValueError('Transaction amount unit conversion mismatch')
            if record.get('unit')!='ETH':
                raise ValueError('Ethereum transaction amount has an invalid unit')
    if record.get('block_timestamp') is not None:
        FactCatalog._number(record['block_timestamp'],'count')


def _check_explanation(scoring, final_probability, dataset_id):
    if scoring.get('route_scores'):
        raise ValueError('New dataset models cannot use legacy independent diagnostic scores')

    def check_tree(tree):
        base, margin = tree.get('base_value'), tree.get('raw_margin')
        groups = tree.get('groups', [])
        if base is None or margin is None or not groups:
            raise ValueError('Native explanation requires base, margin and complete groups')
        for group in groups:
            FactCatalog._number(group['contribution'], 'raw_margin')
        _same(base + sum(g['contribution'] for g in groups), margin,
              'Native group contributions do not reconstruct the raw margin', 1e-5)
        if 'additivity_residual' in tree:
            FactCatalog._number(tree['additivity_residual'], 'raw_margin')
            if abs(tree['additivity_residual']) > 1e-5:
                raise ValueError('Native attribution residual exceeds its contract')

    if dataset_id == 'bitcoin':
        if scoring.get('kind') != 'grouped_tree':
            raise ValueError('Bitcoin report requires grouped native-tree evidence')
        check_tree(scoring)
        _same(_sigmoid(scoring['raw_margin']), final_probability,
              'Bitcoin raw margin differs from the frozen risk probability', 2e-6)
        keys = [g['key'] for g in scoring['groups']]
        if len(keys) != 3 or set(keys) != {'behavior', 'context', 'structure'}:
            raise ValueError('Bitcoin evidence must cover the three registered groups')
    else:
        if scoring.get('kind') != 'dual_view':
            raise ValueError('Ethereum report requires actual dual-view evidence')
        branches = scoring.get('branches', [])
        if len(branches) != 2 or {b['key'] for b in branches} != {'attribute', 'joint'}:
            raise ValueError('Dual-view evidence must contain exactly two native branches')
        weights = {'attribute': .6, 'joint': .4}
        total = 0.
        for branch in branches:
            check_tree(branch)
            probability = branch['probability']
            FactCatalog._number(probability, 'ratio_0_1')
            _same(branch['weight'], weights[branch['key']], 'Frozen fusion weight changed')
            _same(_sigmoid(branch['raw_margin']), probability,
                  'Branch raw margin differs from its native probability', 2e-6)
            if 'weighted_probability' in branch:
                _same(branch['weighted_probability'], probability * branch['weight'],
                      'Weighted branch output is inconsistent')
            total += branch['weight'] * probability
        fusion = scoring.get('fusion', {})
        if fusion.get('method') != 'weighted_probability' or fusion.get('weights') != weights:
            raise ValueError('Unsupported or modified dual-view fusion')
        _same(fusion['probability'], total, 'Fusion result differs from its branches', 2e-7)
        _same(final_probability, total, 'Frozen risk differs from the fusion result', 2e-6)


def _check_probability_chain(scoring, risk, dataset_id, versions=None, calibration_source=None):
    """Check native output, the frozen postprocessor and current risk separately."""
    raw = (_sigmoid(scoring['raw_margin']) if dataset_id == 'bitcoin'
           else scoring.get('fusion', {}).get('probability'))
    FactCatalog._number(raw, 'ratio_0_1')
    _check_explanation(scoring, raw, dataset_id)
    if 'raw_probability' in risk:
        _same(risk['raw_probability'], raw, 'Raw probability differs from the native output', 2e-6)
    descriptor = risk.get('calibration', scoring.get('calibration'))
    if risk.get('calibration') is not None and scoring.get('calibration') is not None:
        first, second = risk['calibration'], scoring['calibration']
        if not isinstance(first, dict) or not isinstance(second, dict):
            raise ValueError('Calibration descriptor must be an object')
        numeric = {'raw_probability', 'calibrated_probability'}
        if {k: v for k, v in first.items() if k not in numeric} != {
                k: v for k, v in second.items() if k not in numeric}:
            raise ValueError('Risk and scoring calibration descriptors differ')
        for field in numeric:
            if (field in first) != (field in second):
                raise ValueError('Risk and scoring calibration descriptor fields differ')
            if field in first:
                _same(first[field], second[field], 'Risk and scoring calibration probabilities differ', 1e-12)
    expected_revision = (versions or {}).get('calibration_revision')
    if descriptor is None:
        if expected_revision is not None:
            raise ValueError('Current release requires its calibration descriptor')
        calibrated = raw
    else:
        if not isinstance(descriptor, dict):
            raise ValueError('Calibration descriptor must be an object')
        if descriptor.get('dataset_id', dataset_id) != dataset_id:
            raise ValueError('Calibration descriptor belongs to a different dataset')
        from src.probability_calibration import apply_calibration_descriptor
        if expected_revision is not None and descriptor.get('revision') != expected_revision:
            raise ValueError('Calibration descriptor belongs to a different revision')
        if calibration_source is not None:
            for field in ('mode', 'status', 'revision', 'parameters', 'model_signature'):
                if descriptor.get(field) != calibration_source.get(field):
                    raise ValueError('Calibration descriptor differs from the frozen source: ' + field)
        calibrated = float(apply_calibration_descriptor(raw, descriptor))
        if 'raw_probability' in descriptor:
            _same(descriptor['raw_probability'], raw, 'Calibration input differs from native probability', 2e-6)
        if 'calibrated_probability' in descriptor:
            _same(descriptor['calibrated_probability'], calibrated, 'Calibration result differs from its mapping', 2e-6)
    if 'calibrated_probability' in risk:
        _same(risk['calibrated_probability'], calibrated, 'Current probability differs from calibration', 2e-6)
    _same(risk['overall_score'] / 100, calibrated,
          'Final risk does not match the native/calibration probability chain', 2e-6)
    if risk.get('risk_level') != _risk_level(risk['overall_score']):
        raise ValueError('Risk level does not match the unrounded current score')
    return raw, calibrated


def _dense_group_relevance(group, trace):
    """Report groups concern the seed and the same first three reported paths."""
    members = set(group['member_addresses'])
    paths = []
    for i, path in enumerate(trace.get('top_paths', [])[:3]):
        touched = [address for address in path['nodes'] if address in members]
        if touched:
            paths.append({'path_id': path.get('path_id') or 'path_' + digest(path['nodes'])[:16],
                          'path_index': i, 'members_on_path': touched})
    return {'seed_is_member': trace['seed_address'] in members, 'path_members': paths}


def _build_dense_group_analysis(service, trace):
    """Snapshot frozen index evidence without a frontend discovery prerequisite."""
    guidance = trace.get('dense_group_guidance') or {}
    index = getattr(service, 'group_index', None)
    versions = getattr(service, 'versions', {})
    revision = versions.get('dense_group_revision')
    enabled = guidance.get('enabled', False)
    if type(enabled) is not bool:
        raise ValueError('Dense group enabled state must be boolean')
    if not enabled:
        if trace.get('suspicious_groups') or any(path.get('dense_group_evidence')
                                               for path in trace.get('top_paths', [])):
            raise ValueError('Disabled dense group index cannot supply group evidence')
        return {'enabled': False, 'status': guidance.get('status', 'disabled'),
                'revision': revision, 'metadata': None, 'groups': [],
                'reported_group_count': 0, 'semantics': 'search_prior_only_no_risk_rewrite'}
    if index is None:
        raise ValueError('Enabled report group evidence requires the active frozen index')
    metadata = _copy(index.metadata)
    if revision is None:
        revision = metadata.get('revision')
    if metadata.get('revision') != revision or guidance.get('revision') != revision:
        raise ValueError('Report dense group index revision mismatch')
    relevant = set(index.memberships.get(trace['seed_address'], ()))
    for path in trace.get('top_paths', [])[:3]:
        for address in path['nodes']:
            relevant.update(index.memberships.get(address, ()))
    groups = []
    for group_id in sorted(relevant, key=lambda key: (-index.groups[key]['group_score'], key)):
        group = _copy(index.groups[group_id])
        members = [{'address_id': address, 'risk_score': service.risks[address],
                    'risk_level': _risk_level(service.risks[address]), 'is_scored': True}
                   for address in group['member_addresses']]
        groups.append({'group': group, 'members': members,
                       'relevance': _dense_group_relevance(group, trace)})
    snapshot = {'enabled': True, 'status': guidance.get('status', 'ready'),
                'revision': revision, 'metadata': metadata, 'groups': groups,
                'reported_group_count': min(len(groups), 5),
                'semantics': 'search_prior_only_no_risk_rewrite'}
    return snapshot


def _check_dense_group_analysis(evidence, graph, risk_scores, dense_group_index=None):
    """Recompute structural evidence against the real graph and frozen scores."""
    snapshot = evidence.get('dense_group_analysis')
    if snapshot is None:
        meta = evidence.get('meta', {})
        revision = meta.get('dense_group_revision', meta.get('versions', {}).get('dense_group_revision'))
        if (dense_group_index is not None or re.fullmatch(r'[a-f0-9]{64}', revision or '')
                or evidence.get('trace_analysis', {}).get('dense_group_guidance', {}).get('enabled')):
            raise ValueError('Enabled group guidance requires its frozen report evidence')
        return
    trace, meta = evidence['trace_analysis'], evidence['meta']
    guidance = trace.get('dense_group_guidance') or {}
    if snapshot.get('semantics') != 'search_prior_only_no_risk_rewrite':
        raise ValueError('Group evidence cannot rewrite frozen address risks')
    if (type(snapshot.get('enabled')) is not bool or type(guidance.get('enabled', False)) is not bool
            or snapshot['enabled'] != guidance.get('enabled', False)):
        raise ValueError('Report dense group enabled state mismatch')
    records = snapshot.get('groups')
    if not isinstance(records, list):
        raise ValueError('Dense group report evidence must be a list')
    count = snapshot.get('reported_group_count')
    FactCatalog._number(count, 'count')
    if count != min(len(records), 5):
        raise ValueError('Reported dense group count mismatch')
    expected_revision = meta.get('dense_group_revision', meta.get('versions', {}).get('dense_group_revision'))
    if expected_revision is not None and snapshot.get('revision') != expected_revision:
        raise ValueError('Report dense group revision differs from the release')
    if guidance and guidance.get('revision') != snapshot.get('revision'):
        raise ValueError('Trace and report dense group revision mismatch')
    if expected_revision is not None and trace.get('provenance', {}).get('dense_group_revision') != expected_revision:
        raise ValueError('Trace dense group revision differs from the release')
    status = snapshot.get('status')
    if status != guidance.get('status', 'ready' if snapshot['enabled'] else 'disabled'):
        raise ValueError('Trace and report dense group status mismatch')
    config_enabled = trace.get('config', {}).get('dense_group_enabled')
    if config_enabled is not None and (type(config_enabled) is not bool or config_enabled != snapshot['enabled']):
        raise ValueError('Trace configuration and report dense group state mismatch')
    if not snapshot['enabled']:
        if (dense_group_index is not None or re.fullmatch(r'[a-f0-9]{64}', snapshot.get('revision') or '')
                or status not in {'disabled', 'missing', 'invalid', 'unavailable'}):
            raise ValueError('An active dense group index cannot be omitted from report evidence')
        if records or count or snapshot.get('metadata') is not None or trace.get('suspicious_groups') or any(
                path.get('dense_group_evidence') for path in trace.get('top_paths', [])):
            raise ValueError('Disabled dense group evidence must remain empty')
        return
    if status != 'ready':
        raise ValueError('Enabled dense group evidence requires a ready index')
    if graph is None or risk_scores is None:
        raise ValueError('Dense group facts require the actual directed graph and frozen risks')
    metadata = snapshot.get('metadata')
    if not isinstance(metadata, dict) or metadata.get('revision') != snapshot.get('revision'):
        raise ValueError('Report dense group metadata revision mismatch')
    if guidance.get('revision') != snapshot['revision'] or trace.get('provenance', {}).get('dense_group_revision') != snapshot['revision']:
        raise ValueError('Trace and report dense group revision mismatch')
    for key in ('dataset_id', 'dataset_fingerprint', 'risk_revision', 'graph_revision',
                'calibration_revision', 'trace_scope'):
        expected = meta.get(key, meta.get('versions', {}).get(key))
        if expected is not None and (metadata.get(key) != expected
                or metadata.get('provenance', {}).get(key) != expected):
            raise ValueError('Dense group index source mismatch: ' + key)
    if metadata.get('mode') != 'topology_only':
        raise ValueError('Unsupported dense group evidence mode')
    if dense_group_index is not None and dense_group_index.metadata != metadata:
        raise ValueError('Group report metadata differs from the frozen active index')
    groups, memberships = {}, {}
    previous_key = None
    for record in records:
        group, members = record.get('group'), record.get('members')
        if not isinstance(group, dict) or not isinstance(members, list):
            raise ValueError('Invalid dense group record')
        group_id = group.get('group_id')
        if not isinstance(group_id, str) or group_id in groups or group.get('mode') != 'topology_only':
            raise ValueError('Invalid or duplicate dense group identity')
        for field in ('member_count', 'edge_count', 'anchor_count'):
            FactCatalog._number(group[field], 'count')
        for field in ('mean_risk', 'max_risk', 'group_score'):
            FactCatalog._number(group[field], 'score_0_100')
        FactCatalog._number(group['topology_density'], 'ratio_0_1')
        FactCatalog._number(group['dense_objective'], 'raw_margin')
        if [member.get('address_id') for member in members] != group.get('member_addresses'):
            raise ValueError('Dense group member snapshots mismatch')
        for member in members:
            address = member['address_id']
            if address not in risk_scores or member.get('is_scored') is not True:
                raise ValueError('Dense group contains an unscored or unknown address')
            _same(member.get('risk_score'), risk_scores[address], 'Dense group member differs from frozen risk table')
            if member.get('risk_level') != _risk_level(risk_scores[address]):
                raise ValueError('Dense group member risk level mismatch')
            memberships.setdefault(address, []).append(group_id)
        relevance = _dense_group_relevance(group, trace)
        if record.get('relevance') != relevance or not (relevance['seed_is_member'] or relevance['path_members']):
            raise ValueError('Dense group is not related to the reported address or paths')
        key = (-group['group_score'], group_id)
        if previous_key is not None and key < previous_key:
            raise ValueError('Dense group evidence ordering mismatch')
        previous_key = key
        if dense_group_index is not None and dense_group_index.groups.get(group_id) != group:
            raise ValueError('Dense group record differs from the frozen active index')
        groups[group_id] = group
    # Reuse exactly the index's own member, role, edge, score and density checks.
    # Only the subset counts change; the original source metadata remains intact
    # in the evidence snapshot and is never rewritten by this verification.
    from src.tracing.dense_group_index import DenseGroupIndex
    subset_metadata = {**metadata, 'group_count': len(groups), 'member_address_count': len(memberships)}
    DenseGroupIndex(graph, groups, memberships, subset_metadata).validate_contents(risk_scores)
    if dense_group_index is not None:
        expected_ids = set(dense_group_index.memberships.get(trace['seed_address'], ()))
        for path in trace.get('top_paths', [])[:3]:
            for address in path['nodes']:
                expected_ids.update(dense_group_index.memberships.get(address, ()))
        if set(groups) != expected_ids:
            raise ValueError('Report dropped or added related dense group evidence')


def build_dataset_evidence(service, analysis, trace):
    """Bind one real analysis and trace to the current dataset/release."""
    dataset_id = service.dataset_id
    if dataset_id not in PUBLIC_METHODS:
        raise ValueError('Unsupported report dataset')
    analysis, trace = _copy(analysis), _copy(trace)
    if analysis.get('dataset_id') != dataset_id:
        raise ValueError('Analysis dataset does not match the report service')
    if trace.get('dataset_id', dataset_id) != dataset_id:
        raise ValueError('Trace dataset does not match the report service')
    address = analysis['address_id']
    if trace.get('seed_address') != address:
        raise ValueError('Trace seed does not match the analyzed address')
    if address not in service.risks:
        raise ValueError('Report target is not a scored address')
    risk = analysis['risk']
    _same(risk['overall_score'], service.risks[address], 'Target risk differs from the frozen table')
    scoring = analysis['scoring_analysis']
    versions = _copy(getattr(service, 'versions', {}))
    metadata = _copy(service.metadata)
    calibration = getattr(service, 'calibration', None)
    calibration_source = (_copy(calibration.describe()) if calibration is not None
                          else metadata.get('calibration'))
    _check_probability_chain(scoring, risk, dataset_id, versions, calibration_source)
    fingerprint = versions.get('dataset_fingerprint', metadata.get('fingerprint'))
    risk_revision = versions.get('risk_revision', metadata.get('risk_revision'))
    provenance = trace.get('provenance', {})
    for key, expected in [('dataset_id', dataset_id), ('dataset_fingerprint', fingerprint),
                          ('risk_revision', risk_revision),
                          ('graph_revision', versions.get('graph_revision')),
                          ('calibration_revision', versions.get('calibration_revision')),
                          ('trace_scope', versions.get('trace_scope')),
                          ('dense_group_revision', versions.get('dense_group_revision'))]:
        if expected is not None and provenance.get(key) != expected:
            raise ValueError('Report trace source version mismatch: ' + key)
    expected_scope = versions.get('trace_scope', metadata.get('trace_scope'))
    _check_scored_trace(trace, service.graph, service.risks, expected_scope)
    if scoring.get('revision') is not None and scoring['revision'] != risk_revision:
        raise ValueError('Scoring explanation belongs to a different model revision')
    edge_witnesses = []
    seen = set()
    edge_lookup = getattr(service, 'edge_evidence', None)
    if callable(edge_lookup):
        for path in trace.get('top_paths', [])[:5]:
            for src, dst in zip(path['nodes'], path['nodes'][1:]):
                if (src, dst) in seen:
                    continue
                seen.add((src, dst))
                records = edge_lookup(src, dst, limit=3)
                if isinstance(records, dict):
                    records = records.get('records', [records])
                for record in records or []:
                    _check_edge_record(record,src,dst,dataset_id)
                edge_witnesses.append({'src': src, 'dst': dst, 'records': _copy(records or [])})
    evidence = {
        'meta': {'dataset_id': dataset_id, 'dataset': DATASET_LABELS[dataset_id],
                 'model_display_name': PUBLIC_METHODS[dataset_id],
                 'generated_at': datetime.now(timezone.utc).isoformat(),
                 'dataset_fingerprint': fingerprint, 'risk_revision': risk_revision,
                 'feature_revision': versions.get('feature_revision', metadata.get('feature_revision')),
                 'graph_revision': versions.get('graph_revision', metadata.get('graph_revision')),
                 'source_graph_revision': metadata.get('source_graph_revision'),
                 'trace_scope': expected_scope,
                 'calibration_revision': versions.get('calibration_revision'),
                 'dense_group_revision': versions.get('dense_group_revision'),
                 'calibration': _copy(calibration_source),
                 'versions': versions, 'scope': metadata.get('scope', 'fixed_dataset_snapshot'),
                 'feature_count': metadata.get('feature_count'),
                 'model_threshold': metadata.get('model_threshold'),
                 'release_source_hashes': metadata.get('source_hashes', {})},
        'target': {'address_id': address, 'node_idx': analysis.get('node_idx'), 'dataset_id': dataset_id},
        'risk_analysis': risk,
        'scoring_analysis': scoring,
        'behavior_evidence': analysis.get('behavior_evidence', []),
        'graph_evidence': analysis.get('graph_evidence', {}),
        'trace_analysis': trace,
        'edge_witnesses': edge_witnesses,
        'limitations': list(POLICIES.values()),
    }
    evidence['dense_group_analysis'] = _build_dense_group_analysis(service, trace)
    _check_dense_group_analysis(evidence, service.graph, service.risks, getattr(service, 'group_index', None))
    return evidence


class DatasetFactCatalog(FactCatalog):
    """Typed facts that preserve null-risk connectors and branch semantics."""
    def __init__(self, evidence, config, graph=None, risk_scores=None, dense_group_index=None):
        self.evidence = _copy(evidence)
        self.evidence_hash = digest(self.evidence)
        self.config = dict(config)
        self.source_index = None
        self.facts = {}
        meta = self.evidence.get('meta', {})
        self.provenance = {key: meta.get(key) for key in (
            'dataset_id', 'dataset_fingerprint', 'risk_revision', 'feature_revision', 'graph_revision',
            'calibration_revision', 'trace_scope', 'dense_group_revision')}
        self.provenance['tracing_revision'] = self.evidence.get('trace_analysis', {}).get('provenance', {}).get('tracing_revision')
        self.graph_checked = graph is not None
        self.risks_checked = risk_scores is not None
        if meta.get('dataset_id') not in PUBLIC_METHODS:
            raise ValueError('Missing or invalid dataset identity')
        if self.evidence['target'].get('dataset_id') != meta['dataset_id']:
            raise ValueError('Evidence target dataset mismatch')
        if graph is not None and graph.metadata.get('fingerprint') and graph.metadata['fingerprint'] != meta['dataset_fingerprint']:
            raise ValueError('Graph and evidence fingerprint mismatch')
        _check_scored_trace(self.evidence['trace_analysis'], graph, risk_scores, _trace_scope(self.evidence))
        _check_dense_group_analysis(self.evidence, graph, risk_scores, dense_group_index)
        self._build_dataset(graph, risk_scores)
        self.catalog_hash = digest(self.facts)

    def _build_dataset(self, graph, risk_scores):
        e = self.evidence
        dataset_id = e['meta']['dataset_id']
        address = e['target']['address_id']
        subject = {'dataset_id': dataset_id, 'address_id': address}
        score = e['risk_analysis']['overall_score']
        self._number(score, 'score_0_100')
        if risk_scores is not None:
            if address not in risk_scores:
                raise ValueError('Target missing from frozen risk table')
            _same(score, risk_scores[address], 'Target risk differs from frozen risk table')
        self._add('dataset_summary', 'overview', ['/meta/dataset', '/meta/model_display_name'],
                  subject, 'description', '数据集与识别方法', {'view': 'dataset'}, True,
                  {'dataset': e['meta']['dataset'], 'method': e['meta']['model_display_name']})
        self._add('address_model_risk', 'overview', ['/risk_analysis/overall_score', '/risk_analysis/risk_level'],
                  subject, 'score_0_100', '综合模型风险', {'view': 'address_risk'}, True,
                  {'score': score, 'risk_level': e['risk_analysis']['risk_level']})
        scoring = e['scoring_analysis']
        _check_probability_chain(scoring, e['risk_analysis'], dataset_id,
                                 e['meta'].get('versions'), e['meta'].get('calibration'))
        if dataset_id == 'bitcoin':
            self._tree_facts(scoring, '/scoring_analysis', subject, 'joint')
        else:
            for i, branch in enumerate(scoring['branches']):
                self._tree_facts(branch, f'/scoring_analysis/branches/{i}', subject, branch['key'])
                self._add('branch_prediction', 'overview', [f'/scoring_analysis/branches/{i}/probability',
                          f'/scoring_analysis/branches/{i}/weight'],
                          {**subject, 'branch': branch['key']}, 'weighted_probability',
                          '属性分类分支' if branch['key']=='attribute' else '结构–属性联合分类分支',
                          {'view':'fusion', 'branch':branch['key']}, True,
                          {'probability':branch['probability'], 'weight':branch['weight'],
                           'weighted_probability':branch['probability']*branch['weight']})
            self._add('fusion_calculation', 'assessment', ['/scoring_analysis/fusion'], subject,
                      'weighted_probability', '双视图融合结果', {'view':'fusion'}, True)
            summary = scoring.get('structure_summary', {})
            if summary.get('dimensions') is not None:
                self._number(summary['dimensions'], 'count')
                self._add('graph_observation', 'graph', ['/scoring_analysis/structure_summary/dimensions'],
                          subject, 'count', '学习得到的图结构表征维度', {'view':'structure'}, False)
        extra_graph_fields = {
            'one_hop_scored_count':('已评分一跳邻居数','count'),
            'one_hop_unscored_count':('未评分一跳邻居数','count'),
            'one_hop_risk_coverage':('一跳邻居评分覆盖率','ratio_0_1'),
        }
        for field, (label, unit) in {**GRAPH_FIELDS, **extra_graph_fields}.items():
            if _trace_scope(e) == SCORED_TRACE_SCOPE and field == 'one_hop_unscored_count':
                # Full observed context remains in the evidence snapshot. It is
                # not a public claim about the scored-only tracing view.
                continue
            value = e.get('graph_evidence', {}).get(field)
            if value is None:
                continue
            self._number(value, unit)
            self._add('graph_observation','graph',[f'/graph_evidence/{field}'],subject,unit,label,
                      {'view':'graph_stat','field':field},field in ('out_degree','in_degree','one_hop_unscored_count'))
        self._trace_facts(graph, risk_scores, subject, score)
        self._dense_group_facts(subject)
        for name, text in POLICIES.items():
            if name == 'unscored_boundary' and (dataset_id != 'ethereum' or _trace_scope(e) == SCORED_TRACE_SCOPE):
                continue
            self._add('review_recommendation' if name=='human_review' else 'limitation',
                      'assessment' if name=='human_review' else 'limitations',[],subject,'policy',
                      '复核建议' if name=='human_review' else '使用范围说明',
                      {'view':'policy','policy_key':name},True,value=text,policy_key=name)

    def _dense_group_facts(self, subject):
        snapshot = self.evidence.get('dense_group_analysis')
        if snapshot is None:
            return
        records = snapshot['groups']
        self._add('dense_group_coverage', 'graph', ['/dense_group_analysis/reported_group_count',
                  '/dense_group_analysis/enabled', '/dense_group_analysis/status'],
                  subject, 'count', '关联群组与报告范围', {'view': 'dense_group_coverage'}, True,
                  {'available_groups': len(records), 'reported_groups': snapshot['reported_group_count'],
                   'enabled': snapshot['enabled'], 'status': snapshot['status']},
                  derived='Count seed and first-three-path groups; report up to five, preserve complete evidence')
        for i, record in enumerate(records[:snapshot['reported_group_count']]):
            group, relevance = record['group'], record['relevance']
            prefix = f'/dense_group_analysis/groups/{i}'
            values = {key: group[key] for key in ('group_id', 'group_score', 'topology_density',
                'member_count', 'edge_count', 'anchor_count', 'mean_risk', 'max_risk')}
            values.update(source_count=len(group['source_members']), target_count=len(group['target_members']),
                          relevance=_copy(relevance), group_number=i+1)
            pointers = [f'{prefix}/group/{key}' for key in ('group_id', 'group_score', 'topology_density',
                        'member_count', 'edge_count', 'anchor_count', 'mean_risk', 'max_risk')]
            pointers += [f'{prefix}/relevance', '/dense_group_analysis/metadata/revision']
            self._add('dense_group', 'graph', pointers, {**subject, 'group_id': group['group_id']},
                      'structural_group', f'关联群组 {i+1:02d}',
                      {'view': 'dense_group', 'group_index': i, 'group_id': group['group_id']}, True,
                      values, derived='Verified bipartite topology and frozen-risk summary; search prior only')
            fact = next(reversed(self.facts.values()))
            fact['capabilities'] = ['directed_relations', 'structural_group_evidence']
            fact['raw_source_locations'] = [{'source_type': 'dense_group_index',
                'group_id': group['group_id'], 'source_revision': snapshot['revision'],
                'evidence_pointer': prefix, 'algorithm': snapshot['metadata'].get('algorithm')}]

    def _tree_facts(self, tree, prefix, subject, branch):
        for i, group in enumerate(tree['groups']):
            group_subject = {**subject,'branch':branch,'group':group['key']}
            self._add('group_attribution', 'behavior' if group['key'] in ('behavior','attribute','attributes') else 'graph',
                      [f'{prefix}/groups/{i}'],group_subject,'joint_tree_margin',
                      str(group['label']),{'view':'group','group':group['key'],'branch':branch},True,
                      {'label':group['label'],'contribution':group['contribution'],
                       'branch':branch,'attribution_target':f'{branch}_raw_margin'})
        for group, features in tree.get('evidence', {}).items():
            for i, item in enumerate(features[:min(self.config['feature_top_k'], 3)]):
                if item.get('contribution') is None:
                    continue
                self._number(item['contribution'],'raw_margin')
                for key in ('feature_value','model_input_value'):
                    if item.get(key) is not None:
                        self._number(item[key],'raw_margin')
                section = 'behavior' if group in ('behavior','attribute','attributes') else 'graph'
                self._add('feature_attribution',section,[f'{prefix}/evidence/{group}/{i}'],
                          {**subject,'group':group,'branch':branch,'feature_index':i,'feature':item.get('feature','未命名特征')},
                          'joint_tree_margin',str(item.get('feature','模型输入特征')),
                          {'view':'feature','group':group,'row':i,'branch':branch},i==0)

    def _trace_facts(self, graph, risk_scores, subject, score):
        trace = self.evidence['trace_analysis']
        if trace.get('seed_address') != subject['address_id']:
            raise ValueError('Trace seed mismatch')
        for key in ('dataset_id','dataset_fingerprint','risk_revision','graph_revision',
                    'calibration_revision','trace_scope'):
            actual = trace.get('provenance',{}).get(key)
            expected = self.provenance.get(key)
            if expected is not None and actual != expected:
                raise ValueError('Trace source version mismatch')
        all_paths = trace.get('top_paths', [])
        shown = min(len(all_paths), 3)
        self._add('path_coverage','paths',['/trace_analysis/top_paths'],subject,'count',
                  '候选路径与报告范围',{'view':'path_coverage'},True,
                  {'available_paths':len(all_paths),'reported_paths':shown},
                  derived='Count available paths; report first three while preserving the full evidence snapshot')
        source_by_edge = {(x['src'],x['dst']):x['records'] for x in self.evidence.get('edge_witnesses',[])}
        for i, path in enumerate(all_paths):
            nodes, scores = path['nodes'], path['node_risks']
            if (not nodes or nodes[0] != subject['address_id'] or len(nodes) != len(set(nodes))
                    or len(nodes) != len(scores) or path['hop_count'] != len(nodes)-1):
                raise ValueError('Invalid relation path subjects or hop count')
            _same(scores[0], score,'Path seed risk differs from the analyzed address')
            for a, value in zip(nodes,scores):
                if value is None:
                    if risk_scores is not None and a in risk_scores:
                        raise ValueError('Scored path node was incorrectly marked unscored')
                else:
                    self._number(value,'score_0_100')
                    if risk_scores is not None:
                        if a not in risk_scores:
                            raise ValueError('Unscored path node has a fabricated risk')
                        _same(value,risk_scores[a],'Path risk differs from frozen risk table')
            self._number(path['path_score'],'ratio_0_1')
            if graph is not None:
                for src,dst in zip(nodes,nodes[1:]):
                    if dst not in graph.out_neighbors(src):
                        raise ValueError('Path edge absent from directed graph')
            threshold=trace.get('config',{}).get('risk_threshold')
            for witness in path.get('bridge_witnesses',[]):
                edges=witness.get('edges',[])
                if not edges or any(tuple(edge) not in set(zip(nodes,nodes[1:])) for edge in edges):
                    raise ValueError('Bridge witness edge absent from path')
                chain=[edges[0][0]]+[edge[1] for edge in edges]
                if any(edges[k][1] != edges[k+1][0] for k in range(len(edges)-1)):
                    raise ValueError('Disconnected bridge witness')
                if chain[1:-1] != witness.get('bridge_nodes') or chain[-1] != witness.get('anchor_node'):
                    raise ValueError('Bridge witness subject mismatch')
                indices=[nodes.index(a) for a in chain]
                if indices != list(range(indices[0],indices[0]+len(indices))):
                    raise ValueError('Bridge witness positions mismatch')
                if scores[indices[-1]] is None:
                    raise ValueError('Unscored node cannot be a risk anchor')
                if threshold is not None and (any(scores[k] is not None and scores[k]>=threshold for k in indices[1:-1])
                                              or scores[indices[-1]]<threshold):
                    raise ValueError('Bridge anchor/connector risk mismatch')
            if i >= shown:
                continue
            path_id=path.get('path_id') or 'path_'+digest(nodes)[:16]
            path_subject={**subject,'path_id':path_id,'path_index':i}
            self._add('relation_path','paths',[f'/trace_analysis/top_paths/{i}'],path_subject,
                      'directed_relations','有向关系路径',{'view':'path','path_index':i,'path_id':path_id},True)
            fact=next(reversed(self.facts.values()))
            fact['raw_source_locations']=[copy.deepcopy(record) for edge in zip(nodes,nodes[1:]) for record in source_by_edge.get(edge,[])]
            if subject['dataset_id']=='ethereum':
                for witness_index,witness_entry in enumerate(self.evidence.get('edge_witnesses',[])):
                    if (witness_entry['src'],witness_entry['dst']) not in set(zip(nodes,nodes[1:])):
                        continue
                    for record_index,record in enumerate(witness_entry['records'][:1]):
                        _check_edge_record(record,witness_entry['src'],witness_entry['dst'],subject['dataset_id'])
                        if record.get('value_eth') is None or record.get('tx_hash') is None:
                            continue
                        # One actual transaction observation per reported path keeps
                        # the prompt bounded; complete witnesses remain in the snapshot.
                        self._add('transaction_observation','paths',
                                  [f'/edge_witnesses/{witness_index}/records/{record_index}'],
                                  {**path_subject,'src':witness_entry['src'],'dst':witness_entry['dst'],
                                   'tx_hash':record['tx_hash']},'transaction_record','观测交易记录',
                                  {'view':'transaction','path_index':i,'path_id':path_id},True)
                        next(reversed(self.facts.values()))['raw_source_locations']=copy.deepcopy(record.get('raw_source_locations',[]))
                    break
            chosen=list(range(len(nodes))) if len(nodes)<=6 else [0,1,len(nodes)-2,len(nodes)-1]
            for j in chosen:
                value=scores[j]
                self._add('path_node_risk' if value is not None else 'path_node_unscored','paths',
                          [f'/trace_analysis/top_paths/{i}/node_risks/{j}',f'/trace_analysis/top_paths/{i}/nodes/{j}'],
                          {'dataset_id':subject['dataset_id'],'address_id':nodes[j],'path_id':path_id,'path_index':i,'hop':j},
                          'score_0_100' if value is not None else 'unscored','路径节点风险' if value is not None else '未评分连接节点',
                          {'view':'path','path_index':i,'path_id':path_id,'hop':j},False,
                          {'address_id':nodes[j],'score':value})
            for j,witness in enumerate(path.get('bridge_witnesses',[])[:3]):
                chain=[witness['edges'][0][0]]+[edge[1] for edge in witness['edges']]
                indices=[nodes.index(a) for a in chain]
                self._add('bridge_reason','paths',[f'/trace_analysis/top_paths/{i}/bridge_witnesses/{j}']+
                          [f'/trace_analysis/top_paths/{i}/node_risks/{k}' for k in indices],
                          {**path_subject,'witness_index':j},'directed_relations',
                          '低风险连接见证' if _trace_scope(self.evidence) == SCORED_TRACE_SCOPE else '低风险／未评分连接见证',
                          {'view':'bridge','path_index':i,'path_id':path_id,'witness_index':j,'hops':indices},True,
                          {'witness':witness,'risks':dict(zip(chain,[scores[k] for k in indices]))},
                          derived='Join source witness with frozen path positions, preserving unscored nulls')
                next(reversed(self.facts.values()))['raw_source_locations']=[copy.deepcopy(record) for edge in map(tuple,witness['edges']) for record in source_by_edge.get(edge,[])]
        if trace.get('search_budget'):
            b=trace['search_budget']
            for name in ('configured_limit','actual_edge_inspections'):
                self._number(b[name],'count')
            if not 0<=b['actual_edge_inspections']<=b['configured_limit']:
                raise ValueError('Search budget inconsistent')
            self._add('search_boundary','paths',['/trace_analysis/search_budget'],subject,'search_checks',
                      '搜索范围记录',{'view':'search_budget'},True)


def _render_dataset_fact(fact, config):
    value,subject,kind=fact['value'],fact['subject'],fact['fact_type']
    if kind=='dataset_summary':
        return f"本次分析使用{safe(value['dataset'])}固定数据集，识别方法为{safe(value['method'])}。"
    if kind=='address_model_risk':
        return (f"地址 {safe(subject['address_id'])} 的综合风险为 {risk_score_text(value['score'])} / 100，"
                f"等级为{safe(LEVELS.get(value['risk_level'],value['risk_level']))}"
                f"（{LEVEL_INTERVALS[value['risk_level']]}，按未四舍五入分数判定）。")
    if kind=='group_attribution':
        branch=('地址风险模型' if subject.get('dataset_id')=='bitcoin' else
                {'attribute':'属性分类分支','joint':'联合分类分支'}.get(value['branch'],'当前模型'))
        direction='推高' if value['contribution']>0 else '降低' if value['contribution']<0 else '未改变'
        return f"{safe(value['label'])}证据组对{branch}原始输出的贡献为 {number(value['contribution'],config['attribution_digits'])}，方向为{direction}模型判断。"
    if kind=='branch_prediction':
        return f"{safe(fact['label'])}为SA-DCF提供相应视图的判断依据，与另一视图协同参与综合研判。"
    if kind=='fusion_calculation':
        return 'SA-DCF结合交易属性与关系结构形成模型判断，综合风险以本报告的当前评分及核验证据为准。'
    if kind=='dense_group_coverage':
        if not value['enabled']:
            return '本次群组索引未启用或暂不可用，报告未纳入群组证据；地址评分及既有路径证据仍按原始来源核验。'
        if not value['available_groups']:
            return '当前地址及本报告涉及路径未匹配到符合索引条件的关联群组；未匹配不表示附近不存在其他密集关系。'
        return (f"本次地址及报告路径关联 {value['available_groups']} 个索引群组，"
                f"正文选取其中 {value['reported_groups']} 个说明；完整群组记录保留在审计证据中。")
    if kind=='dense_group':
        relevance = value['relevance']
        touched = set(address for path in relevance['path_members'] for address in path['members_on_path'])
        seed = '当前分析地址属于该群组；' if relevance['seed_is_member'] else ''
        return (f"关联群组 {value['group_number']:02d} 包含 {value['member_count']} 个地址、"
                f"{value['edge_count']} 条内部真实有向关系，转出／转入角色数为 "
                f"{value['source_count']}／{value['target_count']}，拓扑密度为 "
                f"{number(value['topology_density'], 4)}，结构分为 {number(value['group_score'], 2)} / 100。"
                f"{seed}本报告 {len(relevance['path_members'])} 条路径涉及其中 {len(touched)} 个成员。"
                '该结构分用于安排关系搜索，不替代成员地址风险，也不单独证明共同控制或违法行为。')
    if kind=='path_coverage':
        return f"本次搜索返回 {value['available_paths']} 条候选路径，正文列出前 {value['reported_paths']} 条；其余候选保留在完整追踪证据中。"
    if kind=='path_node_unscored':
        return f"路径第 {subject['hop']} 跳地址 {safe(value['address_id'])} 未纳入当前评分集合，作为关系连接展示，不赋予风险分。"
    if kind=='transaction_observation':
        timestamp=(f"，区块时间戳为 {value['block_timestamp']}（UTC秒）" if value.get('block_timestamp') is not None else '')
        return (f"观测交易 {safe(value['tx_hash'])}：{safe(value['src'])} → {safe(value['dst'])}，"
                f"记录金额为 {safe(value['value_eth'])} ETH{timestamp}；该记录作为关系见证，不单独证明整条路径的资金连续性。")
    if kind=='bridge_reason':
        w=value['witness'];connectors=w['bridge_nodes'];unknown=sum(value['risks'].get(a) is None for a in connectors)
        detail = f'，其中 {unknown} 个未评分' if unknown else ''
        description = '连续连接节点' if unknown else '连续低风险连接节点'
        return (f"路径包含 {len(connectors)} 个{description}{detail}；"
                f"存在到风险锚点 {safe(w['anchor_node'])} 的完整有向连接见证，锚点当前风险为 {risk_score_text(value['risks'][w['anchor_node']])} / 100。")
    if kind=='path_node_risk':
        return f"路径第 {subject['hop']} 跳地址 {safe(value['address_id'])} 的当前风险为 {risk_score_text(value['score'])} / 100。"
    if kind=='graph_observation' and fact['unit']=='score_0_100':
        return f"{safe(fact['label'])}为 {risk_score_text(value)}，描述图结构关联。"
    if kind=='feature_attribution':
        raw=value.get('feature_value');model=value.get('model_input_value')
        text=f"特征值 {number(raw,config['attribution_digits'])}" if raw is not None else f"模型输入值 {number(model,config['attribution_digits'])}" if model is not None else '输入值未提供'
        branch=('地址风险模型' if subject.get('dataset_id')=='bitcoin' else
                {'attribute':'属性分类分支','joint':'联合分类分支'}.get(subject.get('branch'),'对应模型'))
        return f"{safe(subject['feature'])}：{text}，对{branch}原始输出的贡献为 {number(value['contribution'],config['attribution_digits'])}。"
    return render_fact(fact,config)


def render_dataset_report(records,catalog,config):
    catalog.verify()
    paragraphs={section:[] for section in SECTIONS};statements=[]
    for record in records:
        claim=record['claim'];fact=catalog.facts[claim['fact_ids'][0]]
        text=_render_dataset_fact(fact,config);label=f'E{len(statements)+1:02d}'
        item={**record,'text':text,'citation_label':label,'source_pointers':fact['source_pointers'],
              'display_locator':fact['display_locator']}
        statements.append(item)
        paragraphs[record['section']].append(f'- {text} [{label}](#evidence-{label.lower()})')
    for section in SECTIONS:
        if not paragraphs[section]:
            paragraphs[section].append('当前没有该部分的可用已核验事实。')
    markdown='# 链境智安可信研判报告\n\n'+'\n\n'.join(
        f'## {i+1}. {heading}\n\n'+'\n'.join(paragraphs[section])
        for i,(section,heading) in enumerate(zip(SECTIONS,HEADINGS)))
    markdown+='\n\n## 证据定位索引\n\n'
    for statement in statements:
        fact=catalog.facts[statement['claim']['fact_ids'][0]];label=statement['citation_label']
        pointers='、'.join('`'+p+'`' for p in fact['source_pointers']) or '系统复核规则：'+str(fact['policy_key'])
        markdown+=f'### evidence-{label.lower()}\n\n{label} · {fact["fact_id"]} · {pointers}\n\n'
    return markdown,statements


class DatasetReportGenerator(WebReportGenerator):
    def __init__(self,*args,progress=None,dense_group_index=None,**kwargs):
        self.progress=progress
        self.dense_group_index=dense_group_index
        super().__init__(*args,**kwargs)

    def _catalog(self,evidence,graph,risk_scores):
        return DatasetFactCatalog(evidence,self.reporting,graph,risk_scores,self.dense_group_index)

    def _prompt(self,catalog):
        messages=super()._prompt(catalog)
        messages[0]['content'] += ('\n来源文件名、目录、source_file和source_row只用于证据定位。'
            '即使路径含phisher、normal等类别词，也不得据此推断目标地址标签、真实身份或恶意事实；'
            '风险判断只能引用登记的模型输出、特征与交易观察事实。'
            '\n融合参数只保留在审计事实中；公开正文不枚举组合系数或计算算式。'
            '\n关联群组仅是已核验拓扑与冻结风险形成的结构证据和搜索先验；'
            '不能将群组结构分称为恶意概率，不能从成员联系推断共同控制、违法团伙或连续资金流。'
            '按既有声明协议选择事实，所有公开文字由程序渲染，不自行补充文案。')
        return messages

    def _render(self,records,catalog):
        return render_dataset_report(records,catalog,self.reporting)

    def _validation_started(self):
        if self.progress is not None:
            self.progress('validation')

    def _request(self,messages):
        # A transient request failure may be retried once, before template fallback.
        # Auth/permission/invalid-request failures do not benefit from repetition.
        for attempt in range(2):
            self.client_request_attempts += 1
            if self.progress is not None:
                self.progress('generation')
            try:
                return super()._request(messages)
            except Exception as exc:
                if attempt or failure_code(exc) not in {'timeout','connection','provider_error','rate_limit'}:
                    raise

    def generate(self,evidence,graph=None,risk_scores=None):
        self.client_request_attempts=0
        report=super().generate(evidence,graph=graph,risk_scores=risk_scores)
        report['dataset_id']=evidence['meta']['dataset_id']
        report['audit']['dataset_id']=evidence['meta']['dataset_id']
        report['audit']['candidate_request_count']=report['audit']['api_calls']
        report['audit']['client_request_attempts']=self.client_request_attempts
        report['audit']['api_calls']=self.client_request_attempts
        report['audit']['registered_path_count']=min(len(evidence['trace_analysis'].get('top_paths',[])),3)
        report['audit']['available_path_count']=len(evidence['trace_analysis'].get('top_paths',[]))
        raw_locations=[location for fact in report['fact_catalog']['facts'].values()
                       for location in fact.get('raw_source_locations',[])]
        locations=len(raw_locations)
        edge_locations=sum(location.get('source_type')!='dense_group_index' for location in raw_locations)
        report['audit']['raw_csv_locations']='registered_edge_witnesses' if edge_locations else 'unavailable'
        report['audit']['raw_source_location_count']=locations
        report['audit']['calibration_revision']=evidence['meta'].get('calibration_revision')
        report['audit']['trace_scope']=evidence['meta'].get('trace_scope')
        group_evidence=evidence.get('dense_group_analysis') or {}
        report['audit']['dense_group_revision']=group_evidence.get('revision')
        report['audit']['dense_groups_checked']=bool(group_evidence.get('enabled'))
        report['audit']['available_dense_group_count']=len(group_evidence.get('groups',[]))
        report['audit']['reported_dense_group_count']=group_evidence.get('reported_group_count',0)
        report['audit']['dense_group_semantics']='search_prior_only_no_risk_rewrite'
        report['audit']['native_calibration_probability_chain_checked']=True
        report['audit']['public_display']={'risk_score_rule':'rounded_100_guard_exact_sources_preserved',
            'fusion_parameters':'audit_only','risk_level_intervals':dict(LEVEL_INTERVALS)}
        if report['source']=='llm' and report['audit']['local_fallback_count']==0:
            report['fallback_reason']=None
        return report


def generate_dataset_report(service,evidence,mode='auto',progress=None):
    if mode not in ('auto','template'):
        raise ValueError('Unsupported report source mode')
    if evidence['meta']['dataset_id']!=service.dataset_id:
        raise ValueError('Report evidence belongs to a different dataset')
    kwargs={'progress':progress,'dense_group_index':getattr(service,'group_index',None)}
    if mode=='template':
        kwargs['config']={'enabled':False}
    generator=DatasetReportGenerator(service.root,**kwargs)
    # Persist once after adding dataset diagnostics; no legacy latest-by-address writes.
    generator.persist=False
    report=generator.generate(evidence,graph=service.graph,risk_scores=service.risks)
    report['audit']['requested_mode']=mode
    if mode=='template':
        # A deliberate template choice is not a provider/configuration failure.
        report['fallback_reason']=None
    report['bundle_path']=save_bundle(service.root,report)
    return report


def generate_dataset_fault_demo(service,original_report,kind):
    """Run the retained authored-error showcase using only a simulated client."""
    if kind not in ('path_score_as_risk','invented_amount','subject_swap'):
        raise ValueError('Unsupported demonstration fault')
    evidence=original_report['evidence_snapshot']
    if evidence.get('meta',{}).get('dataset_id')!=service.dataset_id:
        raise ValueError('Demonstration report belongs to a different dataset')
    versions=getattr(service,'versions',{})
    for field in ('dataset_fingerprint','risk_revision','feature_revision','graph_revision',
                  'calibration_revision','trace_scope','dense_group_revision'):
        if versions.get(field) is not None and evidence['meta'].get(field)!=versions[field]:
            raise ValueError('Demonstration report belongs to a different release')
    if kind=='path_score_as_risk' and not evidence['trace_analysis'].get('top_paths'):
        raise ValueError('当前报告没有关系路径，不能演示路径排序分错误')
    from src.report.fault_demo import generate_fault_demo
    return generate_fault_demo(service.root,original_report,kind,service.graph,service.risks,
                               source_label='simulation')
