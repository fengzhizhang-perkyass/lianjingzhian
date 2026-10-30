# V3 implementation contract (2026-10-30)

This is an implementation coordination contract for `/Users/luyu/Desktop/竞赛/网安/改进方案v3.md`. The plan and latest human requirements govern. No retraining or test-threshold selection. Preserve frozen models and old production artifacts; build new runtime releases separately.

## Ownership

- Root: `api/main.py`, `api/runtime.py`, `api/store.py`, `api/datasets/{base,bitcoin,registry}.py`, common tracing, presenters, launch/runtime packaging, BTC release preparation, integration tests.
- Frontend agent: `frontend/**`, frontend browser verification script(s). No backend modifications.
- Ethereum agent: `api/datasets/ethereum.py`, `scripts/prepare_ethereum_v3.py`, Ethereum-specific preparation helpers/tests and `artifacts/datasets/ethereum/**`.
- Reporting agent: `src/report/**`, `api/reporting.py`, reporting-specific tests. No main/runtime/frontend changes.

## Dataset and API contract

Dataset IDs: `bitcoin`, `ethereum`. All new UI requests carry `dataset_id`. Existing URL routes remain. User-facing system name: 链境智安——面向虚拟资产洗钱风险的智能识别与可信研判系统. Navigation: 优先序列调查 / 地址风险识别 / 多跳关联追踪 / 可信研判生成. No visible LightGBM or product version badges. Marketing background remains byte-identical; slogan remains unchanged. ETH public method SA-DCF, full name as in the plan.

- `GET /api/datasets` -> `{datasets:[{dataset_id,label,ready,description}],default_dataset_id:'bitcoin'}`.
- `GET /api/meta?dataset_id=...` preserves old meta keys `versions,dataset,model,defaults,examples,long_cases,capabilities,risk_counts`; adds `dataset_id,dataset_label,display_groups`. `model.display_name` is public-safe. `examples` retains lists under `high_risk_known,low_risk_known,high_risk_unknown` when available; optional empty list. Do not label examples as known ground truth unless supported.
- `GET /api/queue?dataset_id=...&limit=100&offset=0` -> `{dataset_id,total,offset,limit,rows:[{address_id,risk_rank,overall_risk_score,risk_level}]}`. Legacy diagnostic columns optional; never fabricate. Export same scope.
- `GET /api/risk?dataset_id=...&address=...` -> `{analysis_id,dataset_id,address_id,versions,analysis,charts}`. `analysis` described below.
- `POST /api/traces` body `{dataset_id,analysis_id,params,mode:'quick'|'long'}` -> old trace envelope plus dataset_id, `result` described below.
- `POST /api/reports` body `{dataset_id,analysis_id,trace_id?,mode:'auto'|'template'}` -> report envelope `{report_id,dataset_id,analysis_id,trace_id,address_id,versions,report,generated_trace?}`.
- `POST /api/reports/from-address` body `{dataset_id,address,mode:'auto'|'template'}` validates membership synchronously (404 before LLM), then -> HTTP202 `{job_id,dataset_id,address_id,status:'queued',stage:'queued'}`.
- `GET /api/jobs/{job_id}?dataset_id=...` -> `{job_id,dataset_id,address_id,status:'queued'|'running'|'completed'|'failed'|'interrupted',stage:'queued'|'risk'|'trace'|'generation'|'validation'|'completed'|'failed',message,result?,error?}`. Completed `result` is the full report envelope and `analysis`/`trace` envelopes for cross-module reuse. Do not show invented progress percentages.
- Snapshot GET/export/bundle endpoints preserve old shape and verify dataset when supplied. Mismatched dataset or versions ->409; unknown address ->404 `{detail,code:'not_found',dataset_id}`. Unknown dataset ->422.

## Common analysis wire shape

```
analysis = {
 address_id,node_idx,dataset_id,
 risk:{overall_score:0..100,risk_level:'LOW'|'MEDIUM'|'HIGH'|'CRITICAL'},
 scoring_analysis:{kind:'grouped_tree'|'dual_view',model_name:public_safe,
   groups:[{key,label,responsibility,contribution,absolute_contribution_share}],
   evidence:{group_key:[{feature,raw_feature,feature_value,model_input_value,
      contribution,direction,attribution_target}]},
   base_value,raw_margin,corrected_logit,temperature:1,additivity_residual,
   route_scores:{},revision,
   branches?:[{key:'attribute'|'joint',label,probability,weight,
       weighted_probability,raw_margin,base_value,groups,evidence,additivity_residual}],
   fusion?:{probability,weights:{attribute:0.6,joint:0.4},method:'weighted_probability'},
   structure_summary?:{dimensions:32, ...actual observed context facts}
 },
 behavior_evidence:[...actual feature evidence],
 graph_evidence:{...actual graph degrees/available risk statistics}
}
```

BTC group keys behavior/context/structure with labels 交易行为画像 / 邻域行为偏离 / 资金流转特征. All1783 columns must be mapped exactly once. Added1460 transaction pooled attributes display under funds-flow, regardless of old stored schema group. Native TreeSHAP raw-margin units; no invented independent risk scores.

ETH UI blocks 交易属性画像 / 交易结构表征 / 双视图融合结果. `scoring_analysis.groups/evidence/base_value/raw_margin` may mirror the joint branch for generic displays but must clearly be labeled joint-branch raw-margin explanations, not final-fusion SHAP. Two actual probabilities weighted .6/.4 produce the final score. Both branch trees include attributes (joint has additional32 embeddings). Do not combine raw-logit SHAP across nonlinear branches as final probability attribution.

## Trace shape

Preserve existing `{seed_address,config,top_paths,subgraph,statistics,search_budget,...}`; top_paths include `nodes,node_risks,path_score,bridge_witnesses`. Unknown risk entries are JSON null, never zero. Graph nodes `{address_id,risk_score:null|number,risk_level:'UNSCORED'|existinglevels,is_scored:boolean}`. Unscored nodes can connect paths but never anchors. Node details can show real relation evidence; unscored cannot independently analyze/report. Preserve edge direction and source witness records. UI colors: UNSCORED gray #94A3B8 with dashed/hollow styling, LOW teal #2DD4BF; other existing levels. Unknown label is not unscored.

## Dataset adapter base contract

Root creates `api/datasets/base.py:DatasetService`. Constructor `(root, dataset_id, folder)` loads prepared assets and initializes common fields/methods. Subclass Ethereum constructor prepares assets then calls super; subclass implements `analyze(address)`.

Prepared folder `artifacts/datasets/{dataset_id}/current/` contains:
- `manifest.json`: `{dataset_id,label,fingerprint,risk_revision,feature_revision,graph_revision,model_display_name,model_threshold,feature_count,scored_addresses,graph_nodes,graph_edges,source_hashes, ...}`.
- `risk_scores.parquet`: `address_id` string, `node_idx` int (index into graph; ETH may exceed score-row index), `overall_risk_score` float0..100, `risk_level`; ETH additional `attribute_probability,joint_probability`.
- `address_to_idx.json`, `idx_to_address.json`, `outgoing_neighbors.pkl`, `incoming_neighbors.pkl`: full graph, including unscored peers; node mapping bijective and consistent. Root graph loader can use a supplied folder.
- Optional `graph_statistics.parquet` true neighbor risk stats using scored neighbors only, counts of coverage/unscored.
- ETH `features.npy` 56width, `embeddings.npy`32width aligned to score rows, `feature_names.json`; use score-row lookup separate from full graph node_idx.
- ETH `edge_evidence.sqlite`: store directed src/dst and real original CSV/row/transaction witness; expose `edge_evidence(src,dst,limit=...)` on service. Keep exact units, source identifiers vs true tx hashes separate. Do not double-count same transaction across files.

Base provides root,dataset_id,folder,metadata,versions,graph,risks,predictor (`table,by_address,by_index,resolve,lookup`),tracer and common `trace`, `meta`, `evidence` (calls reporting agent function). `resolve` only accepts scored addresses; normalized ETH lowercase. Base metadata includes dataset/fingerprint/risk_revision. Tracer is root responsibility and supports partial risk coverage.

## Reporting interface

Reporting agent adds `src/report/dataset_reporting.py`:
- `build_dataset_evidence(service, analysis, trace)` returns evidence dict with current dataset/model provenance, actual groups/branches and graph witnesses; compatible report UI schema where possible.
- `generate_dataset_report(service,evidence,mode='auto',progress=None)` returns report shape consumed by existing `frontend/js/views/evidence.js`: `{report_id,source,markdown,claims,rendered_claims,sections,fact_catalog,evidence_snapshot,audit,candidates,...}`. Agent may adapt frontend via contract/message if needed (no editing frontend).
- Preserve actual claim/fact validation, evidence navigation, bundle export and template fallback. Real LLM configured in existing server .env; never read/print secrets. Success after a failed retry must not show template fallback notice. Do not present old gate, three independent experts, weight/temperature corrections as facts of new models.
- ROOT orchestrator calls progress('generation') and reporting should call progress('validation') at actual validation phase if possible.
- All new evidence/claims scoped to dataset/address/revisions. Unscored null is not a risk number. No fabricated amounts, timestamps, 32 named latent rules or causal feature claims.

## Verification

No writes outside authorized local workspace. Remote files only `/data/luyu/web3aml`; no training needed. Verify source hashes, native model output equality, SHAP additivity, score+graph identity, real frontend interaction, and at least one real LLM report per dataset after deterministic tests pass. Preserve raw frozen evaluation records. Report any genuine blockers via prompt input, while continuing independent work.
