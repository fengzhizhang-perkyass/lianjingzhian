import numpy as np
import pytest
from src.model.topology_features import topology_features, NAMES
from src.inference.investigation import blend_probabilities, simplex_weights, diagnose_experts


def test_topology_is_directed_deduplicated_and_excludes_future():
    edges = np.array([[0, 0, 1, 1, 1, 2], [1, 1, 0, 2, 1, 3]])
    times = np.array([1, 2, 4, 5])
    features = topology_features(edges, 4, times, cutoff=2)
    assert features.shape == (4, len(NAMES))
    assert features[0, 0] == pytest.approx(np.log(2))
    assert features[0, 1] == pytest.approx(np.log(2))
    assert features[0, 4] == 1
    assert features[2, -1] == 1 and features[2, :3].sum() == 0
    full = topology_features(edges, 4)
    assert full[1, 1] == pytest.approx(np.log(3))
    assert full[1, 3] == pytest.approx(1/3)


def test_convex_blend_preserves_bounds_and_rejects_bad_inputs():
    p = np.array([[0.1, 0.9], [0.8, 0.2]])
    assert np.allclose(blend_probabilities(p, [0.25, 0.75]), [.7, .35])
    with pytest.raises(ValueError):
        blend_probabilities(p, [-1, 2])
    with pytest.raises(ValueError):
        blend_probabilities(p, [0.2, 0.2])
    assert len(simplex_weights(3, .25)) == 15


def test_high_low_conflict_is_distinct_from_consensus():
    result = diagnose_experts([[90, 80, 70], [5, 12, 20], [95, 10, 65], [40, 50, 55]])
    assert result["review_status"].tolist() == ["共识告警", "一致未告警", "模型分歧", "待复核"]
    assert result["expert_disagreement"][2] == 85
    assert result["warning_expert_count"].tolist() == [3, 0, 2, 0]


def test_each_expert_uses_its_own_validation_alert_threshold():
    result = diagnose_experts([[70, 80, 20], [70, 80, 10]], [60, 60, 16])
    assert result["review_status"].tolist() == ["共识告警", "模型分歧"]


def test_investigation_evidence_survives_into_template_and_rejects_bad_scores():
    from src.report.evidence_builder import build_evidence
    from src.report.template_reporter import TemplateReporter
    overlay = {"priority_score": 71.2, "expert_disagreement": 40, "review_status": "模型分歧",
               "expert_scores": {"graphsage": 90, "dual_view": 70, "topology_tree": 50},
               "topology_evidence": [], "revision": "test"}
    evidence = build_evidence({"address_id": "A", "investigation_analysis": overlay})
    text = TemplateReporter().generate(evidence)["markdown"]
    assert "71.20" in text and "模型分歧" in text
    assert evidence["meta"]["investigation_revision"] == "test"
    overlay["priority_score"] = 101
    with pytest.raises(ValueError):
        build_evidence({"investigation_analysis": overlay})


def test_live_tree_explanation_adds_to_raw_margin_when_available():
    from src.utils.io import ROOT, read_json
    from src.explain.topology_explainer import TopologyTreeExplainer
    path = ROOT / "artifacts/investigation/metadata.json"
    if not path.exists():
        pytest.skip("Real tree expert not prepared")
    if read_json(path)["risk_revision"] != read_json(ROOT / "artifacts/risk_scores/metadata.json").get("risk_revision"):
        pytest.skip("Explanation overlay belongs to a previous base model")
    evidence = TopologyTreeExplainer(ROOT, read_json(path)).explain(0)
    assert len(evidence) == 5
    assert all(abs(item["additivity_residual"]) < 1e-5 for item in evidence)


def test_stale_priority_cannot_be_mixed_with_new_base_risk(tmp_path):
    from src.utils.io import save_json
    from src.inference.investigation import InvestigationIndex
    save_json(tmp_path / "artifacts/investigation/metadata.json", {"risk_revision": "old"})
    with pytest.raises(RuntimeError, match="stale"):
        InvestigationIndex(tmp_path, "new")
