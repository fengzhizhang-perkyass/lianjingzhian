from datetime import datetime, timezone
import math
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, model_validator


class RiskAnalysis(BaseModel):
    overall_score: float | None = Field(default=None, ge=0, le=100)
    risk_level: Literal["LOW", "MEDIUM", "HIGH", "CRITICAL", "UNAVAILABLE"] = "UNAVAILABLE"
    behavior_score: float | None = Field(default=None, ge=0, le=100)
    graph_score: float | None = Field(default=None, ge=0, le=100)
    behavior_weight: float | None = Field(default=None, ge=0, le=1)
    graph_weight: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def weights_sum_to_one(self):
        if self.behavior_weight is not None and self.graph_weight is not None:
            if not math.isclose(self.behavior_weight+self.graph_weight, 1, abs_tol=1e-5):
                raise ValueError("Fusion weights must sum to one.")
        return self


class BehaviorEvidence(BaseModel):
    feature: str
    value: float | None = None
    contribution: float | None = None
    attribution_target: str = "behavior_head_logit"
    baseline: str | None = None
    direction: str | None = None
    convergence_delta: float | None = None


class Evidence(BaseModel):
    model_config = ConfigDict(extra="forbid")
    meta: dict
    target: dict
    risk_analysis: RiskAnalysis
    behavior_evidence: list[BehaviorEvidence]
    graph_evidence: dict
    trace_analysis: dict
    investigation_analysis: dict | None = None
    scoring_analysis: dict | None = None
    limitations: list[str]


LIMITATIONS = [
    "风险评分是模型输出，不是法律结论，也不代表地址所有者一定参与洗钱。",
    "当前追踪沿地址关系边扩展，不执行精确金额级资金污染归属。",
    "数据可能存在未知或不完整标签；在线证据不使用真实标签作为判断依据。",
    "Gate 展示的是模型融合系数，不能直接解释为因果贡献或特征归因比例。",
    "图分支同时利用节点特征与邻域关系；两条分支不是完全独立的信息来源。",
    "行为和图分支分数未经独立校准；综合风险分使用验证集温度校准。",
    "地址特征可能汇总完整生命周期；时间划分结果不能视为历史时点实时预测效果。",
]


def build_evidence(risk_analysis=None, behavior_evidence=None, graph_evidence=None,
                   trace_result=None, metadata=None):
    risk_analysis, trace_result, metadata = risk_analysis or {}, trace_result or {}, metadata or {}
    behavior = []
    for item in behavior_evidence or []:
        behavior.append({"feature": item["feature"], "value": item.get("value", item.get("feature_value")),
                         "contribution": item.get("contribution"),
                         "attribution_target": item.get("attribution_target", "behavior_head_logit"),
                         "baseline": item.get("baseline"), "direction": item.get("direction"),
                         "convergence_delta": item.get("convergence_delta")})
    trace = {"max_depth": trace_result.get("config", {}).get("max_depth"),
             "config": trace_result.get("config", {}),
             **trace_result.get("statistics", {}), "top_paths": trace_result.get("top_paths", [])}
    target_address = risk_analysis.get('address_id')
    if target_address and trace_result.get('seed_address') and target_address != trace_result['seed_address']:
        raise ValueError('Trace Seed does not match analyzed address')
    provenance = trace_result.get('provenance', {})
    for source, expected in (('risk_revision', metadata.get('risk_revision')),
                             ('dataset_fingerprint', metadata.get('fingerprint'))):
        if expected is not None and provenance.get(source) is not None and provenance[source] != expected:
            raise ValueError(f'Trace {source} does not match evidence metadata revision')
    for field in ('method','provenance','search_budget','selection_analysis','seed_relevance','reason_summary','anchor_reachability'):
        if field in trace_result:
            trace[field] = trace_result[field]
    limitations = list(LIMITATIONS)
    if 'search_budget' in trace_result:
        limitations.extend([
            '路径优先级、Seed 关联分和地址风险含义不同；低分桥接不改变中间地址的原始风险。',
            '追踪受到深度、边访问预算和候选配额限制；未展示不代表不存在关联路径。',
            '关系路径缺少逐笔金额和时间证据，不能据此认定连续资金流或污染比例。',
        ])
    if metadata.get("scope") == "real_data_pilot":
        limitations.append("当前使用真实数据采样子图；评分、指标和路径不能代表全量地址关系网络。")
    result = Evidence(meta={"dataset": metadata.get("dataset", "Elliptic++"),
                            "analysis_type": "automated AML risk analysis",
                            "generated_at": datetime.now(timezone.utc).isoformat(),
                            "scope": metadata.get("scope", "unspecified"),
                            "dataset_fingerprint": metadata.get("fingerprint"),
                            "risk_revision": metadata.get("risk_revision", "legacy")},
                      target={"address_id": risk_analysis.get("address_id", trace_result.get("seed_address", "UNAVAILABLE"))},
                      risk_analysis=RiskAnalysis(**risk_analysis.get("risk", {})),
                      behavior_evidence=behavior, graph_evidence=graph_evidence or {},
                      trace_analysis=trace, limitations=limitations)
    result = result.model_dump(mode="json")
    scoring = risk_analysis.get('scoring_analysis')
    if scoring:
        values = list(scoring['route_scores'].values())
        if any(not math.isfinite(float(v)) or not 0 <= float(v) <= 100 for v in values):
            raise ValueError('Invalid evidence route score')
        result['scoring_analysis'] = scoring
        result['meta']['model_kind'] = 'evidence_tree'
        result['meta']['scoring_revision'] = scoring['revision']
        result['limitations'] = [line for line in result['limitations'] if not any(word in line for word in ['Gate', '图分支同时', '未经独立校准'])]
        result['limitations'].extend([
            '综合评分由三类特征联合决策；单类证据模型分数用于诊断，不是综合分的概率平均输入。',
            'TreeSHAP 可加和地解释联合树模型原始输出；贡献占比用于展示模型归因，不具有因果含义。',
            '方向邻域偏离是地址与邻居行为的比较；三类证据具有明确职责，但不是完全独立的数据来源。',
            '综合与单类分数均在已知标签验证集校准，不能保证 unknown 人群的概率校准。',
        ])
    else:
        result.pop('scoring_analysis', None)
    investigation = risk_analysis.get("investigation_analysis")
    if investigation:
        # Keep the original schema unchanged when the optional overlay is unavailable.
        for field in ("priority_score", "expert_disagreement"):
            value = float(investigation[field])
            if not math.isfinite(value) or not 0 <= value <= 100:
                raise ValueError("Invalid investigation score.")
        if any(not math.isfinite(float(v)) or not 0 <= float(v) <= 100 for v in investigation["expert_scores"].values()):
            raise ValueError("Invalid expert score.")
        result["investigation_analysis"] = investigation
        result["meta"]["investigation_revision"] = investigation["revision"]
        result["limitations"].append("调查优先级用于安排复核顺序；专家分歧不是错误概率，各专家告警阈值在验证集分别选择。")
        result["limitations"].append("TreeSHAP 解释拓扑树专家的原始输出，不是融合排序分的因果归因。")
    else:
        result.pop("investigation_analysis", None)
    import json
    json.dumps(result, allow_nan=False)
    return result
