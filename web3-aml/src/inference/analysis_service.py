from pathlib import Path
import pandas as pd
from src.inference.risk_predictor import RiskPredictor
from src.tracing.graph_loader import DirectedGraph
from src.tracing.beam_search import RiskGuidedTracer
from src.explain.graph_evidence import GraphEvidence
from src.explain.behavior_explainer import BehaviorExplainer
from src.report.evidence_builder import build_evidence
from src.report.llm_reporter import LLMReporter
from src.utils.io import ROOT, load_config, read_json, save_json, artifact_key


class AnalysisService:
    def __init__(self, root: Path = ROOT):
        self.root = root
        self.predictor = RiskPredictor(root)
        self.metadata = read_json(root / "data/processed/metadata.json")
        self.metadata["risk_revision"] = self.predictor.metadata.get("risk_revision", "legacy")
        self.metadata['model_kind'] = self.predictor.metadata.get('model_kind', 'dual_view')
        self._evidence_tree = None
        self.investigation, self.investigation_error, self._topology = None, None, None
        if self.metadata['model_kind'] != 'evidence_tree' and (root / "artifacts/investigation/metadata.json").exists():
            from src.inference.investigation import InvestigationIndex
            try:
                self.investigation = InvestigationIndex(root, self.metadata["risk_revision"])
                self.metadata["investigation_revision"] = self.investigation.metadata["revision"]
            except (RuntimeError, OSError, KeyError) as error:
                self.investigation_error = str(error)
        self.graph = DirectedGraph.load(root)
        self.risks = self.predictor.table.set_index("address_id")["overall_risk_score"].to_dict()
        config = load_config("model.yaml", root)
        self.graph_evidence = GraphEvidence(self.graph, self.risks,
            config["explanation"]["two_hop_sample_size"], config["training"]["seed"], config["risk_level"]["medium"])
        statistics = None
        cached = root / "artifacts/risk_scores/graph_statistics.parquet"
        cached_meta = root / "artifacts/risk_scores/graph_statistics_metadata.json"
        if cached.exists() and cached_meta.exists():
            cache_metadata = read_json(cached_meta)
            if (cache_metadata["dataset_fingerprint"] == self.metadata["fingerprint"]
                    and cache_metadata.get("risk_revision", "legacy") == self.metadata["risk_revision"]):
                statistics = pd.read_parquet(cached, columns=["address_id", "one_hop_avg_risk"]).set_index("address_id").to_dict(orient="index")
        tracing = load_config('tracing.yaml',root)
        if tracing.get('method') == 'budgeted':
            from src.tracing.budgeted_tracer import BudgetedRelationTracer
            from src.tracing.anchor_index import RiskAnchorIndex
            provenance = {'dataset_fingerprint':self.metadata['fingerprint'],
                          'risk_revision':self.metadata['risk_revision']}
            index = RiskAnchorIndex.load(self.graph,root/tracing['anchor_index_path'],provenance,
                                         tracing['risk_threshold'],tracing['max_depth'])
            self.tracer = BudgetedRelationTracer(self.graph,self.risks,tracing,statistics,provenance,index)
        else:
            self.tracer = RiskGuidedTracer(self.graph,self.risks,tracing,statistics)
        self._behavior = None

    def analyze(self, address):
        risk = self.predictor.lookup(address)
        if self.metadata['model_kind'] == 'evidence_tree':
            from src.inference.evidence_scoring import EvidenceScoringExplainer
            if self._evidence_tree is None:
                self._evidence_tree = EvidenceScoringExplainer(self.root, self.predictor.metadata)
            row = self.predictor.by_address.loc[risk['address_id']]
            route_scores = {'behavior': float(row.behavior_score), 'context': float(row.graph_score),
                            'structure': float(row.structure_score)}
            scoring = self._evidence_tree.explain(risk['node_idx'], route_scores, config_top_k(self.root))
            return {**risk, 'scoring_analysis': scoring, 'behavior_evidence': scoring['evidence']['behavior'],
                    'graph_evidence': self.graph_evidence.explain(risk['address_id'])}
        if self._behavior is None:
            self._behavior = BehaviorExplainer(self.root)
        result = {**risk, "behavior_evidence": self._behavior.explain(risk["node_idx"]),
                  "graph_evidence": self.graph_evidence.explain(risk["address_id"])}
        if self.investigation is not None:
            from src.explain.topology_explainer import TopologyTreeExplainer
            if self._topology is None:
                self._topology = TopologyTreeExplainer(self.root, self.investigation.metadata)
            row = self.investigation.lookup(risk["address_id"])
            result["investigation_analysis"] = {
                "priority_score": float(row["priority_score"]), "review_status": row["review_status"],
                "expert_disagreement": float(row["expert_disagreement"]),
                "expert_scores": {"graphsage": float(row["graphsage_expert_score"]),
                                  "dual_view": float(row["dual_view_expert_score"]),
                                  "topology_tree": float(row["topology_tree_expert_score"])},
                "expert_weights": dict(zip(self.investigation.metadata["experts"], self.investigation.metadata["weights"])),
                "warning_thresholds": self.investigation.metadata["warning_thresholds"],
                "topology_evidence": self._topology.explain(risk["node_idx"], config_top_k(self.root)),
                "revision": self.investigation.metadata["revision"],
            }
        return result

    def trace(self, address, overrides=None):
        overrides = dict(overrides or {})
        fallback = None
        if self.tracer.config.get('method') == 'budgeted':
            index = self.tracer.anchor_index
            if (overrides.get('risk_threshold',self.tracer.config['risk_threshold']) != index.metadata['threshold']
                    or overrides.get('max_depth',self.tracer.config['max_depth']) > index.metadata['max_depth']):
                overrides['anchor_index_enabled'] = False
                fallback = '参数超出离线索引范围，使用同预算在线连接见证搜索。'
        result = self.tracer.trace(self.predictor.resolve(address), overrides)
        if fallback:
            result['anchor_index_fallback_reason'] = fallback
        for node in result["subgraph"]["nodes"]:
            node["risk_level"] = self.predictor.by_address.loc[node["address_id"], "risk_level"]
        self.tracer.save(result, self.root)
        return result

    def evidence(self, analysis, trace):
        return build_evidence(analysis, analysis["behavior_evidence"], analysis["graph_evidence"], trace, self.metadata)

    def report(self, evidence):
        report = LLMReporter(self.root).generate(evidence,graph=self.graph,risk_scores=self.risks)
        key = artifact_key(evidence["target"]["address_id"])
        save_json(self.root / "artifacts/reports" / f"{key}_evidence.json", evidence)
        folder = self.root / "artifacts/reports"
        (folder / f"{key}.md").write_text(report["markdown"], encoding="utf-8")
        return report


def config_top_k(root):
    return load_config("model.yaml", root)["explanation"]["top_k"]
