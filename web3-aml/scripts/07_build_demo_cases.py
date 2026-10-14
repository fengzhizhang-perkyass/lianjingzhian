import _bootstrap
import numpy as np
import pandas as pd
from src.inference.analysis_service import AnalysisService
from src.explain.graph_evidence import precompute_graph_statistics
from src.report.template_reporter import TemplateReporter
from src.utils.io import ROOT, save_json, artifact_key, load_config


def build_demo_cases():
    service = AnalysisService()
    config = load_config("model.yaml")
    count = config["demo"]["cases_per_group"]
    high_threshold = config["risk_level"]["medium"]
    stats = precompute_graph_statistics(service.graph, service.predictor.table, threshold=high_threshold)
    service.tracer.graph_statistics = stats.set_index("address_id")[["one_hop_avg_risk"]].to_dict(orient="index")
    table = service.predictor.table.copy()
    y = np.load(ROOT / "data/processed/labels.npy")
    test = np.load(ROOT / "data/processed/test_mask.npy")
    table["label"] = y[table["node_idx"].to_numpy()]
    table["is_test"] = test[table["node_idx"].to_numpy()]
    table["out_degree"] = table["address_id"].map(lambda a: service.graph.degrees(a)[0])
    high = table[(table["label"] == 1) & table["is_test"] & (table["overall_risk_score"] >= high_threshold)].sort_values("overall_risk_score", ascending=False)
    low = table[(table["label"] == 0) & table["is_test"] & (table["overall_risk_score"] < config["risk_level"]["low"])].sort_values("overall_risk_score")
    unknown = table[(table["label"] == -1) & (table["overall_risk_score"] >= high_threshold)].sort_values("overall_risk_score", ascending=False)
    # Demo case selection is separate from test evaluation: no retraining/tuning uses these labels.
    def path_ready(candidates):
        connected = candidates[candidates['out_degree'] > 0].copy()
        threshold = service.tracer.config['risk_threshold']
        connected['eligible_downstream'] = connected.address_id.map(
            lambda address: sum(service.risks[neighbor] >= threshold for neighbor in service.graph.out_neighbors(address) if neighbor != address))
        searchable = connected[connected.eligible_downstream > 0].sort_values(
            ['eligible_downstream', 'overall_risk_score'], ascending=False, kind='stable')
        results = []
        for address in searchable.head(config['demo']['path_candidate_limit']).address_id:
            trace = service.tracer.trace(address)
            results.append({'address_id': address, 'paths': len(trace['top_paths']),
                            'depth': trace['statistics']['max_reached_depth']})
            if sum(item['paths'] >= config['demo']['preferred_min_paths'] and item['depth'] >= 2 for item in results) >= count:
                break
        if results:
            order = pd.DataFrame(results).sort_values(['paths', 'depth'], ascending=False, kind='stable').address_id.tolist()
            ready = candidates.set_index('address_id').loc[order].reset_index()
            return pd.concat([ready, connected, candidates]).drop_duplicates('address_id')
        return pd.concat([connected, candidates]).drop_duplicates('address_id')
    high = path_ready(high)
    unknown = path_ready(unknown)
    if min(len(high), len(low), len(unknown)) < count:
        raise RuntimeError("Insufficient genuine demo cases. Train longer/increase pilot size; do not fabricate scores or labels.")
    cases = {"high_risk_known": high.head(count)["address_id"].tolist(),
             "low_risk_known": low.head(count)["address_id"].tolist(),
             "high_risk_unknown": unknown.head(count)["address_id"].tolist()}
    save_json(ROOT / "artifacts/demo_cases.json", cases)
    for address in sum(cases.values(), []):
        analysis = service.analyze(address)
        trace = service.trace(address)
        evidence = service.evidence(analysis, trace)
        key = artifact_key(address)
        save_json(ROOT / "artifacts/reports" / f"{key}_evidence.json", evidence)
        save_json(ROOT / "artifacts/reports" / f"{key}_analysis.json", analysis)
        (ROOT / "artifacts/reports" / f"{key}.md").write_text(TemplateReporter().generate(evidence)["markdown"], encoding="utf-8")
    print(cases)
    return cases


if __name__ == "__main__":
    build_demo_cases()
