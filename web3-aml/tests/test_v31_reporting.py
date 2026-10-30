"""V3.1 public prose stays concise while precise model evidence remains auditable."""
import copy
import json
import math
from types import SimpleNamespace

import pytest

from src.probability_calibration import apply_calibration_descriptor
from src.report.dataset_reporting import (
    DatasetFactCatalog, SCORED_TRACE_SCOPE, build_dataset_evidence,
    generate_dataset_report, risk_score_text,
)
from src.utils.io import load_config
from test_dataset_reporting_v3 import generator, llm_document, service_inputs


def scored_inputs(root, score=None):
    service, analysis, trace = service_inputs(root)
    service.risks['U'] = 4.
    service.versions['trace_scope'] = SCORED_TRACE_SCOPE
    service.metadata['trace_scope'] = SCORED_TRACE_SCOPE
    trace['provenance'] = dict(service.versions)
    trace['trace_scope'] = SCORED_TRACE_SCOPE
    trace['top_paths'][0]['node_risks'][1] = 4.
    trace['subgraph'] = {
        'nodes': [{'address_id': a, 'is_scored': True, 'risk_score': service.risks[a]}
                  for a in ('A', 'U', 'C')],
        'edges': [{'src': 'A', 'dst': 'U'}, {'src': 'U', 'dst': 'C'}],
    }
    if score is not None:
        probability = score / 100
        for branch in analysis['scoring_analysis']['branches']:
            margin = math.log(probability / (1 - probability))
            branch.update(probability=probability, raw_margin=margin,
                          base_value=margin-sum(g['contribution'] for g in branch['groups']),
                          weighted_probability=branch['weight'] * probability)
        analysis['scoring_analysis']['fusion']['probability'] = probability
        analysis['risk'].update(overall_score=score, risk_level='CRITICAL' if score >= 80 else
                                'HIGH' if score >= 60 else 'MEDIUM' if score >= 30 else 'LOW')
        service.risks['A'] = score
        trace['top_paths'][0]['node_risks'][0] = score
        trace['subgraph']['nodes'][0]['risk_score'] = score
    return service, analysis, trace


@pytest.mark.parametrize('score, expected', [
    (0., '0.00'), (29.999, '30.00'), (30., '30.00'), (60., '60.00'), (80., '80.00'),
    (83.991589, '83.99'), (99.9949, '99.99'), (99.995, '>99.99'),
    (99.99934414491265, '>99.99'), (100., '100.00'),
])
def test_risk_display_guards_rounding_only(score, expected):
    assert risk_score_text(score) == expected


@pytest.mark.parametrize('score', [True, -1., 100.1, float('nan'), float('inf')])
def test_risk_display_rejects_invalid_inputs(score):
    with pytest.raises(ValueError):
        risk_score_text(score)


def test_template_hides_fusion_weights_but_preserves_full_audit(tmp_path):
    service, analysis, trace = scored_inputs(tmp_path, 99.99934414491265)
    for branch in analysis['scoring_analysis']['branches']:
        for features in branch['evidence'].values():
            features[0]['feature_value'] = .6
    evidence = build_dataset_evidence(service, analysis, trace)
    report = generate_dataset_report(service, evidence, 'template')
    text = report['markdown']
    assert '>99.99 / 100' in text and '80≤分数≤100' in text
    assert '融合权重' not in text and '按0.6' not in text and '按0.4' not in text
    assert '加权风险分' not in text and '60%' not in text and '40%' not in text
    assert '特征值 0.6000' in text  # Do not strip unrelated source numbers.
    assert '未评分' not in text
    snapshot = report['evidence_snapshot']
    assert snapshot['risk_analysis']['overall_score'] == 99.99934414491265
    assert snapshot['scoring_analysis']['fusion']['weights'] == {'attribute': .6, 'joint': .4}
    assert snapshot['graph_evidence']['one_hop_unscored_count'] == 1
    facts = list(report['fact_catalog']['facts'].values())
    branch_facts = [f for f in facts if f['fact_type'] == 'branch_prediction']
    assert [f['value']['weight'] for f in branch_facts] == [.6, .4]
    assert report['audit']['unresolved_final_claims'] == 0
    assert report['audit']['required_fact_coverage'] == 1
    assert report['audit']['public_display']['fusion_parameters'] == 'audit_only'


def test_llm_claim_selection_uses_identical_public_renderer(tmp_path):
    service, analysis, trace = scored_inputs(tmp_path)
    settings = {**load_config('reporting.yaml'), 'persist_audit': False}
    evidence = build_dataset_evidence(service, analysis, trace)
    catalog = DatasetFactCatalog(evidence, settings, service.graph, service.risks)
    reporter, calls = generator(tmp_path, settings, [llm_document(catalog)])
    report = reporter.generate(evidence, service.graph, service.risks)
    assert report['source'] == 'llm' and len(calls) == 1
    assert all('融合权重' not in s['text'] and '按0.6' not in s['text'] for s in report['statements'])
    assert '融合参数只保留在审计事实中' in calls[0]['messages'][0]['content']
    assert report['audit']['unresolved_final_claims'] == 0


@pytest.mark.parametrize('tamper', ['scope', 'scope_provenance', 'node', 'path', 'edge', 'graph_revision'])
def test_scored_trace_rejects_scope_or_membership_tampering(tmp_path, tamper):
    service, analysis, trace = scored_inputs(tmp_path)
    if tamper == 'scope': trace['trace_scope'] = 'full_observed_graph'
    if tamper == 'scope_provenance': trace['provenance']['trace_scope'] = 'full_observed_graph'
    if tamper == 'node': trace['subgraph']['nodes'][1].update(risk_score=None, is_scored=False)
    if tamper == 'path': trace['top_paths'][0]['node_risks'][1] = None
    if tamper == 'edge': trace['subgraph']['edges'][0]['dst'] = 'C'  # No original A→C edge.
    if tamper == 'graph_revision': trace['provenance']['graph_revision'] = 'old_graph'
    with pytest.raises(ValueError):
        build_dataset_evidence(service, analysis, trace)


def calibrated_inputs(root, dataset_id, mode='temperature'):
    service, analysis, trace = (scored_inputs(root) if dataset_id == 'ethereum'
                                 else service_inputs(root, dataset_id))
    raw = analysis['risk']['overall_score'] / 100
    descriptor = {'dataset_id': dataset_id, 'mode': mode, 'status': 'enabled', 'revision': 'cal_revision',
                  'parameters': {'temperature': 2.} if mode == 'temperature' else
                                {'slope': .7, 'intercept': -.2}}
    p = apply_calibration_descriptor(raw, descriptor)
    descriptor.update(raw_probability=raw, calibrated_probability=p)
    service.versions['calibration_revision'] = descriptor['revision']
    service.metadata['calibration'] = {k: copy.deepcopy(v) for k, v in descriptor.items()
                                       if k not in ('raw_probability', 'calibrated_probability')}
    analysis['risk'].update(raw_probability=raw, calibrated_probability=p,
                            overall_score=100*p, calibration=copy.deepcopy(descriptor),
                            risk_level='CRITICAL' if p >= .8 else 'HIGH' if p >= .6 else
                                       'MEDIUM' if p >= .3 else 'LOW')
    analysis['scoring_analysis']['calibration'] = copy.deepcopy(descriptor)
    service.risks['A'] = p * 100
    trace['provenance'] = dict(service.versions)
    trace['top_paths'][0]['node_risks'][0] = p * 100
    if 'subgraph' in trace: trace['subgraph']['nodes'][0]['risk_score'] = p * 100
    return service, analysis, trace


@pytest.mark.parametrize('dataset_id', ['bitcoin', 'ethereum'])
@pytest.mark.parametrize('mode', ['temperature', 'sigmoid'])
def test_native_calibration_final_chain_is_verified(tmp_path, dataset_id, mode):
    service, analysis, trace = calibrated_inputs(tmp_path, dataset_id, mode)
    report = generate_dataset_report(service, build_dataset_evidence(service, analysis, trace), 'template')
    snapshot = report['evidence_snapshot']
    assert snapshot['risk_analysis']['raw_probability'] != snapshot['risk_analysis']['calibrated_probability']
    assert snapshot['meta']['calibration_revision'] == 'cal_revision'
    assert report['audit']['unresolved_final_claims'] == 0
    assert report['audit']['required_fact_coverage'] == 1


@pytest.mark.parametrize('tamper', ['raw', 'result', 'parameters', 'revision', 'level',
                                   'descriptor_mismatch', 'missing_descriptor', 'dataset'])
def test_calibration_or_grade_tampering_is_rejected(tmp_path, tamper):
    service, analysis, trace = calibrated_inputs(tmp_path, 'ethereum')
    if tamper == 'raw': analysis['risk']['raw_probability'] = .1
    if tamper == 'result': analysis['risk']['calibrated_probability'] = .1
    if tamper == 'parameters':
        for d in (analysis['risk']['calibration'], analysis['scoring_analysis']['calibration']):
            d['parameters']['temperature'] = 3.
    if tamper == 'revision':
        for d in (analysis['risk']['calibration'], analysis['scoring_analysis']['calibration']):
            d['revision'] = 'old_calibration'
    if tamper == 'level': analysis['risk']['risk_level'] = 'CRITICAL'
    if tamper == 'descriptor_mismatch': analysis['scoring_analysis']['calibration']['status'] = 'needs_data'
    if tamper == 'missing_descriptor':
        del analysis['risk']['calibration']
        del analysis['scoring_analysis']['calibration']
    if tamper == 'dataset':
        for d in (analysis['risk']['calibration'], analysis['scoring_analysis']['calibration']):
            d['dataset_id'] = 'bitcoin'
    with pytest.raises(ValueError):
        build_dataset_evidence(service, analysis, trace)


def test_native_and_table_probability_ulp_difference_is_accepted(tmp_path):
    service, analysis, trace = calibrated_inputs(tmp_path, 'bitcoin')
    import numpy as np
    for field in ('raw_probability', 'calibrated_probability'):
        value = analysis['scoring_analysis']['calibration'][field]
        analysis['scoring_analysis']['calibration'][field] = float(np.nextafter(value, 1.))
    evidence = build_dataset_evidence(service, analysis, trace)
    assert evidence['risk_analysis']['overall_score'] == analysis['risk']['overall_score']


@pytest.mark.parametrize('score, level', [(29.999, 'LOW'), (30., 'MEDIUM'),
                                        (59.999, 'MEDIUM'), (60., 'HIGH'),
                                        (79.999, 'HIGH'), (80., 'CRITICAL')])
def test_grade_uses_exact_score_not_display_rounding(tmp_path, score, level):
    service, analysis, trace = scored_inputs(tmp_path, score)
    assert analysis['risk']['risk_level'] == level
    report = generate_dataset_report(service, build_dataset_evidence(service, analysis, trace), 'template')
    fact = next(f for f in report['fact_catalog']['facts'].values() if f['fact_type'] == 'address_model_risk')
    assert fact['value']['risk_level'] == level and fact['value']['score'] == score
