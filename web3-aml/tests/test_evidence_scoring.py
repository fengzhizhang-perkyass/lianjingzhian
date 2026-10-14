import numpy as np
import pytest
from src.utils.io import ROOT, read_json


def active_tree():
    path = ROOT / 'artifacts/risk_scores/metadata.json'
    if not path.exists() or read_json(path).get('model_kind') != 'evidence_tree':
        pytest.skip('Evidence tree not activated')
    return read_json(path)


def test_online_joint_attributions_reconstruct_exact_test_and_demo_scores():
    metadata = active_tree()
    from src.inference.risk_predictor import RiskPredictor
    from src.inference.evidence_scoring import EvidenceScoringExplainer
    from src.model.calibration import calibrated_probability
    predictor = RiskPredictor()
    explainer = EvidenceScoringExplainer(ROOT, metadata)
    values = np.load(ROOT / metadata['metrics_path'].replace('test.json', 'test_predictions.npz'))
    ids = values['node_idx'][:3]
    for idx in ids:
        row = predictor.by_index.loc[idx]
        scoring = explainer.explain(int(idx), {'behavior': float(row.behavior_score), 'context': float(row.graph_score), 'structure': float(row.structure_score)})
        assert abs(scoring['additivity_residual']) < 1e-5
        assert scoring['base_value']+sum(g['contribution'] for g in scoring['groups']) == pytest.approx(scoring['raw_margin'])
        probability = calibrated_probability([scoring['corrected_logit']], scoring['temperature'])[0]
        assert probability*100 == pytest.approx(row.overall_risk_score, abs=1e-8)
        original = values['probability'][np.flatnonzero(values['node_idx'] == idx)[0]]
        assert probability == pytest.approx(original, abs=1e-8)
        assert predictor.lookup(str(int(idx)))['risk']['behavior_weight'] is None


def test_actual_joint_evidence_reaches_report_without_gate_or_legacy_experts():
    active_tree()
    from src.inference.analysis_service import AnalysisService
    from src.report.template_reporter import TemplateReporter
    service = AnalysisService()
    address = read_json(ROOT / 'artifacts/demo_cases.json')['high_risk_known'][0]
    analysis = service.analyze(address)
    evidence = service.evidence(analysis, service.trace(address))
    report = TemplateReporter().generate(evidence)['markdown']
    assert '方向邻域偏离' in report and '有向结构角色' in report
    assert 'GraphSAGE 专家' not in report and '行为融合系数' not in report
    assert 'scoring_analysis' in evidence and 'investigation_analysis' not in evidence
    assert not any('Gate' in line for line in evidence['limitations'])
