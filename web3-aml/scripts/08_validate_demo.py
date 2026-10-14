"""Offline acceptance checks on real saved model/data artifacts; no live API call."""
import _bootstrap
import numpy as np
from src.inference.analysis_service import AnalysisService
from src.report.template_reporter import TemplateReporter
from src.utils.io import ROOT, read_json, save_json, load_config


def validate_demo():
    service = AnalysisService()
    cases = read_json(ROOT / "artifacts/demo_cases.json")
    y = np.load(ROOT / "data/processed/labels.npy")
    test = np.load(ROOT / "data/processed/test_mask.npy")
    high_threshold = load_config("model.yaml")["risk_level"]["medium"]
    comparison = read_json(ROOT / "artifacts/metrics/comparison.json")
    assert set(comparison) == {"lightgbm", "behavior", "graphsage", "dual_view"}
    assert all(result["dataset_fingerprint"] == service.metadata["fingerprint"] for result in comparison.values())
    table = service.predictor.table
    assert len(table) == service.metadata["num_nodes"]
    assert table["overall_risk_score"].between(0, 100).all()
    if service.metadata.get('model_kind') != 'evidence_tree':
        assert np.allclose(table["behavior_weight"]+table["graph_weight"], 1)
    investigation_summary = None
    if service.investigation is not None:
        priorities = service.investigation.table
        assert len(priorities) == len(table)
        assert priorities.priority_score.between(0, 100).all()
        assert "label" not in priorities.columns
        assert priorities.node_idx.is_unique and priorities.address_id.is_unique
        investigation_summary = {"revision": service.investigation.metadata["revision"],
                                 "num_addresses": len(priorities),
                                 "statuses": priorities.review_status.value_counts().to_dict()}
    summaries = []
    for group, addresses in cases.items():
        assert len(addresses) >= 3
        for address in addresses:
            risk = service.predictor.lookup(address)
            idx = risk["node_idx"]
            if group == "high_risk_known":
                assert test[idx] and y[idx] == 1
                assert risk["risk"]["overall_score"] >= high_threshold
            elif group == "low_risk_known":
                assert test[idx] and y[idx] == 0
            else:
                assert y[idx] == -1 and risk["risk"]["overall_score"] >= high_threshold
            analysis = service.analyze(address)
            if service.metadata.get('model_kind') == 'evidence_tree':
                assert abs(analysis['scoring_analysis']['additivity_residual']) < 1e-5
            trace = service.trace(address)
            if 'search_budget' in trace:
                assert trace['provenance']['risk_revision'] == service.metadata['risk_revision']
                assert trace['provenance']['dataset_fingerprint'] == service.metadata['fingerprint']
                assert trace['search_budget']['actual_edge_inspections'] <= trace['search_budget']['configured_limit']
                assert sum(trace['search_budget']['stage_edge_inspections'].values()) == trace['search_budget']['actual_edge_inspections']
            for path in trace["top_paths"]:
                assert len(path["nodes"]) == len(set(path["nodes"]))
                assert path['hop_count'] <= trace['config']['max_depth']
                assert path['node_risks'] == [float(service.risks[a]) for a in path['nodes']]
                for witness in path.get('bridge_witnesses',[]):
                    real_path_edges = set(zip(path['nodes'],path['nodes'][1:]))
                    assert all(tuple(edge) in real_path_edges for edge in witness['edges'])
                    assert service.risks[witness['anchor_node']] >= trace['config']['risk_threshold']
                for src, dst in zip(path["nodes"], path["nodes"][1:]):
                    assert dst in service.graph.out_neighbors(src)
            evidence = service.evidence(analysis, trace)
            assert "label" not in evidence["risk_analysis"]
            if service.investigation is not None:
                assert evidence["meta"]["investigation_revision"] == service.investigation.metadata["revision"]
                assert all(abs(item["additivity_residual"]) < 1e-5 for item in evidence["investigation_analysis"]["topology_evidence"])
            report = TemplateReporter().generate(evidence)
            assert address in report["markdown"] and report["source"] == "template"
            summaries.append({"group": group, "address": address, "risk": risk["risk"]["overall_score"],
                              "paths": len(trace["top_paths"]), "max_depth": trace["statistics"]["max_reached_depth"]})
    result = {"status": "passed", "scope": service.metadata["scope"],
              "risk_revision": service.metadata["risk_revision"],
              'tracing_method':service.tracer.config.get('method','legacy'),
              'tracing_revision':getattr(service.tracer,'revision',None),
              "model_version": service.predictor.metadata.get('model_version', comparison["dual_view"].get("model_version", "V1")),
              "num_addresses_scored": len(table),
              "historical_baseline_count": len(comparison), "active_model_kind": service.metadata.get('model_kind', 'dual_view'),
              "cases": summaries, "live_llm_tested": False,
              "investigation": investigation_summary}
    if service.metadata.get('model_kind') == 'evidence_tree':
        primary = next(item for item in summaries if item['group'] == 'high_risk_unknown')
        assert primary['paths'] >= load_config('model.yaml')['demo']['preferred_min_paths']
        assert primary['max_depth'] >= 2
        result['primary_demo'] = primary
        result['tracing_risk_threshold'] = service.tracer.config['risk_threshold']
    save_json(ROOT / "artifacts/metrics/demo_acceptance.json", result)
    print(result)
    return result


if __name__ == "__main__":
    validate_demo()
