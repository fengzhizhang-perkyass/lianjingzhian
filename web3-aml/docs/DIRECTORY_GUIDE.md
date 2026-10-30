# 目录导航

业务模块按责任拆分。编号脚本负责串联流程，算法代码放在 `src/`，UI 页面放在 `src/ui/`。

模块一记录入口：[MODULE_01_ADDRESS_RISK_SCORING.md](MODULE_01_ADDRESS_RISK_SCORING.md)。其中集中记录当前模型、特征、接口、产物、实验和验收；完整实验说明与结构图由该入口链接。

跨模块逻辑：[THREE_MODULE_INNOVATION_ALIGNMENT.md](THREE_MODULE_INNOVATION_ALIGNMENT.md)。模块二当前实现：[MODULE_02_RELATION_TRACING.md](MODULE_02_RELATION_TRACING.md)；[初始计划](MODULE_02_RELATION_TRACING_PLAN.md) 保留历史候选。

```text
web3-aml/
├── README.md                 使用与复现入口
├── app.py                    Streamlit 启动入口，只负责导航
├── requirements.txt          可安装的依赖约束
├── requirements-lock.txt     本机验证版本，训练后生成
├── setup.ps1                 Windows 环境安装
├── run_demo.ps1              Windows 启动演示
├── .env.example              LLM 配置示例；密钥写入 .env
├── config/                   可修改的参数、字段与特征名称映射
├── docs/                     目录说明、评估边界、比赛演示步骤
├── scripts/                  00–08 基础流程；09–15 历史优化；16–22 评分；23–26 追踪
│   └── run_pipeline.ps1       一键离线流程与阶段测试
├── src/
│   ├── data/                 真实数据检查与预处理
│   ├── baseline/             LightGBM 对照实验
│   ├── model/                有向传播、偏离与结构；历史 MLP、GraphSAGE、Gate
│   ├── train/                训练、验证、测试指标和曲线
│   ├── inference/            风险预计算、在线查表和分析服务
│   ├── explain/              行为归因、邻域风险证据
│   ├── tracing/              锚点索引、预算、桥接、覆盖选择；保留旧 Beam
│   ├── report/               Evidence Schema、模板、LLM 校验
│   ├── ui/                   六个页面与共享组件，含调查优先队列
│   └── utils/                配置、IO、种子与日志
├── tests/                    各模块的边界与端到端验证
├── data/
│   ├── raw/                  官方 CSV 与下载校验清单
│   └── processed/            特征、标签、图、映射、划分和 scaler
├── artifacts/
│   ├── model/                模型、校准参数、训练历史
│   ├── metrics/              数据检查、模型指标、曲线与对照表
│   ├── risk_scores/          所有当前子图节点的风险表、图统计
│   ├── evidence_scoring/     当前 171 维特征、评分和部署元数据
│   ├── investigation/        历史调查层缓存；当前版本不加载
│   ├── experiments/          冻结实验、消融、完整对比与历史备份
│   ├── traces/               追踪结果（安全地址作为文件名，特殊输入用哈希）
│   ├── tracing/              当前锚点数组、来源/哈希、部署验收
│   ├── reporting/            当前案例的原始CSV来源定位索引
│   ├── reports/              地址报告与独立report编号审计目录
│   └── demo_cases.json       三类、每类至少三个真实数据案例
└── logs/                     preprocess / train / inference / app 日志
```

## 日常改动位置

| 需求 | 文件位置 |
|---|---|
| 数据列名 / 标签编码 | `config/data.yaml` |
| 显存、采样量、训练轮数 | `config/model.yaml` |
| 搜索深度、Beam 宽度、风险阈值 | `config/tracing.yaml` |
| 追踪实验与组件对照 | `config/tracing_experiments.yaml` |
| 查当前追踪效果与完整对比 | `artifacts/experiments/tracing_v2_release_stable/REPORT.md` |
| 已核实的特征中文名 | `config/feature_names.yaml` |
| LLM 连接 | `.env` 和 `config/llm.yaml` |
| 声明协议、修复/长度限额、来源索引 | `config/reporting.yaml` |
| 模块三实验范围 | `config/report_experiments.yaml` |
| 当前报告故障、模拟修复与真实快照实验 | `artifacts/experiments/report_v3_release_stable/REPORT.md` |
| 某页布局 | `src/ui/` 内的对应页面 |
| 查当前模型效果 | `artifacts/experiments/evidence_tree_v1/REPORT.md` |
| 查严格消融 | `artifacts/experiments/evidence_tree_v1_ablation/` |
| 评分后端 | `config/scoring.yaml` |
| 当前树参数与选择协议 | `config/evidence_tree_experiments.yaml` |
| 查双线路模型诊断 | `artifacts/metrics/risk_diagnostics/` |
| 调整诊断范围与统计阈值 | `config/diagnostics.yaml` |
| 调整风险优化实验 | `config/risk_experiments.yaml` |
| 查优化、消融和多种子结果 | `artifacts/experiments/risk_v2/` |
| 调整调查层参数 | `config/investigation.yaml` |
| 查调查层实验与对照 | `artifacts/experiments/investigation_v1/` |
| 查比赛亮点与新的演示流程 | `docs/RISK_SCORING_REDESIGN.md`、`docs/DEMO_GUIDE.md` |
| 查数据规模、子图标记和划分 | `data/processed/metadata.json` |

`data/`、`artifacts/`、`logs/` 是生成结果，不混入源码。脚本可重复运行；切换全量 / 子图后，应顺序重新训练、预计算并生成案例，防止不同图的产物混用。

## 当前重构脚本

| 编号 | 职责 | 实验目录 |
|---|---|---|
| 16 | 消除重复图专家、比较证据职责 | `roles_v1` |
| 17 | 有向传播、多尺度与 beta 滤波 | `graph_signals_v1` |
| 18 | 三路 Gate / 拼接点式网络 | `multievidence_v1` |
| 19 | 三段验证选择联合树 | `evidence_tree_v1` |
| 20 | 同预算移除与去方向对照 | `evidence_tree_v1_ablation` |
| 21 | 全量评分与当前后端安装 | `artifacts/evidence_scoring` |
| 22 | 汇总、历史比较与科学图表 | `evidence_tree_v1/REPORT.md` |
| 23 | 当前保存路径的前缀/重复诊断及构造阈值检查 | `tracing_v2_planning/baseline_diagnosis.json` |
| 24 | 机制图、分层 Seed、开发/冻结评估、19 个对照 | `tracing_v2_release_stable` |
| 25 | 冻结方案、构建索引、版本核对、备份与部署 | `artifacts/tracing` |
| 26 | 追踪报告、描述区间、可导出的 PNG/SVG 图 | `tracing_v2_release_stable/REPORT.md` |
| 27 | 4/8/16/32跳与连接跨度对照、真实长链样例及逐边核对 | `tracing_long_paths_v2/REPORT.md` |
| 28 | 安装64跳可达索引和长链案例，保留4跳默认模式 | `artifacts/tracing/long_path_cases.json` |
| 29 | 模块三历史引用校验基线诊断、顶会论文元数据核实 | `report_v3_planning` |
| 30 | 声明协议故障对照、模拟局部修复、10个真实案例审计包 | `report_v3_release_stable/REPORT.md` |
| 31 | 当前案例的原始CSV记录索引、重复选择与处理特征核对 | `artifacts/reporting/source_index.json` |
| 32 | 小请求连接探测，可选一个真实AML报告；模板回退不算成功 | `artifacts/metrics/llm_connection_acceptance.json` |

模块三当前实现见 `docs/MODULE_03_EXPLAINABLE_REPORT.md`；`MODULE_03_EXPLAINABLE_REPORT_PLAN.md`保留历史设计。独立审计包存放`artifacts/reports/report_*/`，原地址报告入口仍兼容。

旧脚本 06、`run_pipeline.ps1` 为 V1；当前部署用 21 后接 07、08，前置训练见重构说明。
`artifacts/metrics/comparison.csv`、`artifacts/investigation` 与调查说明为历史对照。
