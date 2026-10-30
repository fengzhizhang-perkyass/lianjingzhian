"""Frozen graph groups enter reports automatically as verifiable structure facts."""
import copy
import json

import pytest

from test_budgeted_tracing import make_graph
from test_dataset_reporting_v3 import service_inputs, llm_document, generator
from src.report.claim_validator import validate_document
from src.report.dataset_reporting import (
    DatasetFactCatalog, build_dataset_evidence, generate_dataset_report,
)
from src.tracing.dense_group_index import DenseGroupIndex
from src.utils.io import load_config


def group_inputs(root, dataset_id='ethereum'):
    service, analysis, trace = service_inputs(root, dataset_id)
    service.risks['U'] = 4.
    edges = [(src, dst) for src in service.risks for dst in service.risks if src != dst]
    service.graph = make_graph(edges, service.risks, service.graph.metadata)
    service.versions['trace_scope'] = dataset_id + '_scored_addresses_only'
    service.metadata['trace_scope'] = service.versions['trace_scope']
    trace['trace_scope'] = service.versions['trace_scope']
    trace['top_paths'][0]['node_risks'] = [service.risks[a] for a in trace['top_paths'][0]['nodes']]
    trace['subgraph'] = {
        'nodes': [{'address_id': a, 'risk_score': risk, 'is_scored': True}
                  for a, risk in service.risks.items()],
        'edges': [{'src': src, 'dst': dst} for src, dst in edges],
    }
    settings = load_config('tracing.yaml')['dense_group_build']
    service.group_index = DenseGroupIndex.build(service.graph, service.risks, settings, service.versions)
    assert len(service.group_index.groups) == 1
    revision = service.group_index.metadata['revision']
    service.versions['dense_group_revision'] = revision
    trace['dense_group_guidance'] = {'enabled': True, 'status': 'ready', 'revision': revision}
    trace['suspicious_groups'] = []  # Discovery has not been clicked; use active index.
    return service, analysis, trace


@pytest.mark.parametrize('dataset_id', ['bitcoin', 'ethereum'])
def test_dense_groups_are_automatic_frozen_and_rendered_without_discovery(tmp_path, dataset_id):
    service, analysis, trace = group_inputs(tmp_path, dataset_id)
    original_risks = copy.deepcopy(service.risks)
    evidence = build_dataset_evidence(service, analysis, trace)
    snapshot = evidence['dense_group_analysis']
    assert snapshot['enabled'] and len(snapshot['groups']) == snapshot['reported_group_count'] == 1
    assert snapshot['groups'][0]['relevance']['seed_is_member']
    assert snapshot['groups'][0]['relevance']['path_members'][0]['members_on_path'] == ['A', 'U', 'C']
    assert all(member['is_scored'] for member in snapshot['groups'][0]['members'])
    report = generate_dataset_report(service, evidence, mode='template')
    assert '关联群组 01' in report['markdown'] and '内部真实有向关系' in report['markdown']
    assert '结构分用于安排关系搜索' in report['markdown']
    assert '融合权重' not in '\n'.join(s['text'] for s in report['statements'] if s['claim']['claim_type'] == 'dense_group')
    assert report['audit']['dense_groups_checked']
    assert report['audit']['dense_group_revision'] == service.group_index.metadata['revision']
    assert report['audit']['available_dense_group_count'] == 1
    facts = list(report['fact_catalog']['facts'].values())
    group = next(f for f in facts if f['fact_type'] == 'dense_group')
    assert group['required'] and group['unit'] == 'structural_group'
    assert group['display_locator']['view'] == 'dense_group'
    assert group['raw_source_locations'][0]['source_type'] == 'dense_group_index'
    assert all('/dense_group_analysis/' in pointer for pointer in group['source_pointers'])
    assert service.risks == original_risks
    service.group_index.groups[next(iter(service.group_index.groups))]['mean_risk'] = 0.
    assert report['evidence_snapshot'] == evidence


@pytest.mark.parametrize('tamper', [
    'member_score', 'unscored_member', 'member_level', 'fake_edge', 'wrong_density',
    'wrong_structure_score', 'foreign_dataset', 'foreign_risk_revision', 'foreign_graph_revision',
    'wrong_scope', 'wrong_revision', 'wrong_path_members', 'wrong_reported_count', 'source_record',
])
def test_report_group_tampering_is_rejected(tmp_path, tamper):
    service, analysis, trace = group_inputs(tmp_path)
    evidence = build_dataset_evidence(service, analysis, trace)
    bad = copy.deepcopy(evidence)
    snapshot = bad['dense_group_analysis']
    record = snapshot['groups'][0]
    if tamper == 'member_score': record['members'][0]['risk_score'] += 1
    elif tamper == 'unscored_member': record['members'][0]['is_scored'] = False
    elif tamper == 'member_level': record['members'][0]['risk_level'] = 'LOW'
    elif tamper == 'fake_edge': record['group']['internal_edges'][0] = ['A', 'A']
    elif tamper == 'wrong_density': record['group']['topology_density'] = .8
    elif tamper == 'wrong_structure_score': record['group']['group_score'] = 100.
    elif tamper.startswith('foreign_'):
        key = {'foreign_dataset': 'dataset_id', 'foreign_risk_revision': 'risk_revision',
               'foreign_graph_revision': 'graph_revision'}[tamper]
        snapshot['metadata'][key] = 'foreign'
    elif tamper == 'wrong_scope': snapshot['metadata']['trace_scope'] = 'full_unscored_graph'
    elif tamper == 'wrong_revision': snapshot['revision'] = 'other_index'
    elif tamper == 'wrong_path_members': record['relevance']['path_members'][0]['members_on_path'] = ['C']
    elif tamper == 'wrong_reported_count': snapshot['reported_group_count'] = 0
    elif tamper == 'source_record': record['group']['discovery_anchor'] = 'not_original_anchor'
    with pytest.raises(ValueError):
        DatasetFactCatalog(bad, load_config('reporting.yaml'), service.graph, service.risks,
                           service.group_index)


def test_group_real_graph_and_frozen_risks_are_required(tmp_path):
    service, analysis, trace = group_inputs(tmp_path)
    evidence = build_dataset_evidence(service, analysis, trace)
    graph = make_graph([('A', 'U'), ('U', 'C')], service.risks, service.graph.metadata)
    with pytest.raises(ValueError, match='edge'):
        DatasetFactCatalog(evidence, load_config('reporting.yaml'), graph, service.risks)
    with pytest.raises(ValueError):
        DatasetFactCatalog(evidence, load_config('reporting.yaml'), service.graph, None)


@pytest.mark.parametrize('field', ['topology_density', 'dense_objective', 'mean_risk', 'max_risk', 'group_score'])
def test_group_statistics_are_recomputed_without_an_active_index_argument(tmp_path, field):
    service, analysis, trace = group_inputs(tmp_path)
    bad = build_dataset_evidence(service, analysis, trace)
    bad['dense_group_analysis']['groups'][0]['group'][field] += .01
    with pytest.raises(ValueError, match='statistic'):
        DatasetFactCatalog(bad, load_config('reporting.yaml'), service.graph, service.risks)


def test_source_metadata_cannot_be_relabelled_while_keeping_the_revision(tmp_path):
    service, analysis, trace = group_inputs(tmp_path)
    bad = build_dataset_evidence(service, analysis, trace)
    bad['dense_group_analysis']['metadata']['algorithm'] = 'made_up_algorithm'
    with pytest.raises(ValueError, match='metadata'):
        DatasetFactCatalog(bad, load_config('reporting.yaml'), service.graph, service.risks, service.group_index)


@pytest.mark.parametrize('with_active_index', [True, False])
@pytest.mark.parametrize('status', ['ready', 'disabled'])
def test_active_group_evidence_cannot_be_deleted_by_toggling_both_enabled_flags(tmp_path, with_active_index, status):
    service, analysis, trace = group_inputs(tmp_path)
    bad = build_dataset_evidence(service, analysis, trace)
    bad['dense_group_analysis'].update(enabled=False, metadata=None, groups=[], reported_group_count=0, status=status)
    bad['trace_analysis']['dense_group_guidance'].update(enabled=False, status=status)
    bad['trace_analysis']['suspicious_groups'] = []
    for path in bad['trace_analysis']['top_paths']:
        path['dense_group_evidence'] = []
    with pytest.raises(ValueError, match='active dense group index'):
        DatasetFactCatalog(bad, load_config('reporting.yaml'), service.graph, service.risks,
                           service.group_index if with_active_index else None)


def test_enabled_state_must_match_the_actual_trace_config(tmp_path):
    service, analysis, trace = group_inputs(tmp_path)
    bad = build_dataset_evidence(service, analysis, trace)
    bad['trace_analysis']['config']['dense_group_enabled'] = False
    with pytest.raises(ValueError, match='configuration'):
        DatasetFactCatalog(bad, load_config('reporting.yaml'), service.graph, service.risks, service.group_index)


@pytest.mark.parametrize('status', ['disabled', 'missing', 'invalid', 'unavailable'])
def test_legitimate_nonready_index_reports_remain_usable(tmp_path, status):
    service, analysis, trace = group_inputs(tmp_path)
    service.group_index = None
    service.versions['dense_group_revision'] = status
    trace['config']['dense_group_enabled'] = False
    trace['dense_group_guidance'] = {'enabled': False, 'status': status, 'revision': status}
    evidence = build_dataset_evidence(service, analysis, trace)
    report = generate_dataset_report(service, evidence, mode='template')
    assert not report['audit']['dense_groups_checked']
    assert report['audit']['dense_group_revision'] == status
    assert report['audit']['available_dense_group_count'] == 0
    assert '本次群组索引未启用或暂不可用' in report['markdown']


def test_missing_index_rejects_claimed_group_evidence_but_fallback_report_is_normal(tmp_path):
    service, analysis, trace = group_inputs(tmp_path)
    service.group_index = None
    with pytest.raises(ValueError, match='active frozen index'):
        build_dataset_evidence(service, analysis, trace)
    service.versions['dense_group_revision'] = 'unavailable:fixture'
    trace['dense_group_guidance'] = {'enabled': False, 'status': 'unavailable',
                                   'revision': service.versions['dense_group_revision']}
    evidence = build_dataset_evidence(service, analysis, trace)
    assert evidence['dense_group_analysis']['groups'] == []
    report = generate_dataset_report(service, evidence, mode='template')
    assert not report['audit']['dense_groups_checked']
    assert '本次群组索引未启用或暂不可用' in report['markdown']
    assert not any(f['fact_type'] == 'dense_group' for f in report['fact_catalog']['facts'].values())
    assert report['audit']['unresolved_final_claims'] == 0


def test_valid_index_without_relevant_groups_does_not_invent_evidence(tmp_path):
    service, analysis, trace = group_inputs(tmp_path)
    config = load_config('tracing.yaml')['dense_group_build']
    config['min_group_nodes'] = 4
    service.group_index = DenseGroupIndex.build(service.graph, service.risks, config,
        {key: value for key, value in service.versions.items() if key != 'dense_group_revision'})
    service.versions['dense_group_revision'] = service.group_index.metadata['revision']
    trace['dense_group_guidance']['revision'] = service.versions['dense_group_revision']
    evidence = build_dataset_evidence(service, analysis, trace)
    report = generate_dataset_report(service, evidence, mode='template')
    assert report['audit']['dense_groups_checked']
    assert report['audit']['available_dense_group_count'] == 0
    assert '未匹配到符合索引条件的关联群组' in report['markdown']
    assert not any(f['fact_type'] == 'dense_group' for f in report['fact_catalog']['facts'].values())


def test_llm_uses_typed_group_facts_and_forged_subject_is_rejected(tmp_path):
    service, analysis, trace = group_inputs(tmp_path)
    evidence = build_dataset_evidence(service, analysis, trace)
    settings = {**load_config('reporting.yaml'), 'persist_audit': False}
    catalog = DatasetFactCatalog(evidence, settings, service.graph, service.risks, service.group_index)
    document = llm_document(catalog)
    reporter, calls = generator(tmp_path, settings, [document])
    reporter.dense_group_index = service.group_index
    report = reporter.generate(evidence, service.graph, service.risks)
    assert report['source'] == 'llm' and len(calls) == 1
    assert any(s['claim']['claim_type'] == 'dense_group' for s in report['statements'])
    assert report['audit']['required_fact_coverage'] == 1
    forged = copy.deepcopy(document)
    claim = next(c for section in forged['sections'] for c in section['claims'] if c['claim_type'] == 'dense_group')
    claim['subject']['group_id'] = 'invented_group'
    assert any(error['error_code'] == 'SUBJECT_MISMATCH'
               for error in validate_document(forged, catalog, settings)['errors'])
    assert len(json.dumps(report['fact_catalog'], ensure_ascii=False)) < settings['max_prompt_chars']
