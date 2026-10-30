# 模块一：地址风险评分——当前实现记录

记录日期：2026-10-11。当前版本：**V2.0 有向邻域对比证据融合**。
本文件记录已经完成并部署的实现，作为后续开发、比赛材料和模块验收的入口。

## 1. 模块定位与当前结论

系统主线为：**地址风险评分 → 资金关系追踪 → 可解释报告**。
本模块负责根据公开数据评估地址风险，输出综合风险分、等级、单类诊断分和评分依据。
路径搜索属于第二个模块；报告生成属于第三个模块。本轮已经完成与二者的接口联调。

当前架构准确称为：**三类证据特征构建 + 一个联合 LightGBM 主模型**。
三类证据为行为画像、方向邻域偏离、有向结构角色。它们属于特征通道，不是三种不同模型。
另外训练三个 LightGBM 单类诊断模型，供界面展示和分析对照；综合分由联合模型直接读取 171 维特征计算。

## 2. 实际使用哪些模型

| 模型 | 类型 | 输入 | 输出与用途 | 是否产生最终综合分 |
|---|---|---|---|---|
| 行为诊断模型 | LightGBM | 51 维行为特征 | 行为单独评分 | 否 |
| 偏离诊断模型 | LightGBM | 102 维上下游标准化偏离 | 邻域偏离单独评分 | 否 |
| 结构诊断模型 | LightGBM | 18 维有向结构统计 | 结构单独评分 | 否 |
| **联合主模型** | **LightGBM** | **全部 171 维特征** | **综合风险** | **是** |

因此，当前评分方案中有 **1 个主模型 + 3 个辅助诊断模型，共 4 个 LightGBM**。
三个诊断分不输入主模型，不执行诊断概率平均、投票或 Gate 融合。
特征构建阶段没有独立的神经编码器；当前主方案不使用 MLP、GraphSAGE 或 Gated Fusion。
这些历史方法仍保存为对照和备份。

## 3. 结构与运行流程

```text
地址特征 ──处理与标准化──┬─ 行为画像 51 维 ─────────────┐
                        └─ 与上下游比较 ─ 偏离 102 维 ─┤
有向关系图 ─────────────┬─ 提供上下游邻居               ├─ 拼接 171 维
                        └─ 有向结构角色 18 维 ─────────┘
                                                           ↓
                                                    联合 LightGBM
                                                    ↙           ↘
                                    类别权重校正与温度校准       联合 TreeSHAP
                                              ↓                   ↓
                                         综合分与等级       特征及三组贡献
                                              └─────────┬─────────┘
                                                        ↓
                                              风险表与结构化证据
                                                        ↓
                                              关系追踪与解释报告

各组特征另外输入各自的诊断 LightGBM → 诊断分 → 辅助展示
```

可直接查看的 Mermaid 图：[RISK_SCORING_FLOWCHART.md](RISK_SCORING_FLOWCHART.md)。
标签仅用于监督训练和离线评估，不输入在线特征构建、图风险证据或追踪评分。

## 4. 三类特征如何构建

### 4.1 行为画像：51 维

使用数据集已有的地址交易统计，保留能够核实的特征含义。
对数值做 signed log1p，缺失值填补和标准化参数只由对应训练节点拟合，标准化值裁剪到 ±8。
原有 55 项数值字段中移除四项绝对区块高度字段：

- `first_block_appeared_in`
- `last_block_appeared_in`
- `first_sent_block`
- `first_received_block`

输出 51 维。职责是描述地址自身行为，为邻域差异和结构模式提供个体语境。
这是处理后的统计特征，不是 MLP embedding。没有核实的字段保留原名，不编造交易语义。

### 4.2 方向邻域偏离：102 维

保留 `A → B` 原始方向：上游为指向目标的邻居，下游为目标指向的邻居。
分别对上下游计算每项已变换行为特征的邻居均值与总体标准差：

```text
z(v,方向,特征) = clip((本地址特征 - 邻居均值) / max(邻居标准差, 0.5), -8, 8)
```

上游 51 维 + 下游 51 维 = 102 维。没有某方向邻居时，该方向偏离记为零。
标准差下限防止少量或相同邻居造成极端偏离；图算子去重关系并移除自环。
职责是保留地址与上下游的相对差异，并区分发送侧和接收侧环境。
偏离值本身不表示非法，需要联合模型学习其行为和结构语境。
代码：[neighborhood_statistics.py](../src/model/neighborhood_statistics.py)。

### 4.3 有向结构角色：18 维

仅由关系图构建，不读取地址风险或标签。
包括入出度、邻居数、方向平衡、双向邻居比例、上下游连接度、孤立标志、上下游起点/终点比例以及正反向二步游走统计。
二步游走剔除立即返回起点的关系。具体 18 项名称由源码 `STRUCTURE_NAMES` 定义。
职责是描述汇入、分出和连接角色，为相似行为补充不同的结构语境；这些统计不代表实际金额流量。
代码：[directed_structure.py](../src/model/directed_structure.py)。

## 5. 数据与划分

| 项目 | 当前数值 |
|---|---:|
| 数据集 | Elliptic++ Actors |
| 地址节点 | 822,942 |
| 去重有向边 | 2,784,344 |
| 原始数值特征 | 55 |
| 已知标签节点 | 265,354 |
| illicit 节点 | 14,266 |
| unknown 节点 | 557,588 |
| 已知 train / validation / test | 170,404 / 38,514 / 56,436 |
| train / validation / test 时间截止 | 34 / 41 / 49 |
| 测试 illicit | 2,548 |

标签统一为 licit=0、illicit=1、unknown=-1；unknown 不进入监督损失，允许进入特征邻域和推理。
训练、开发验证及最终验证图过滤触及相应未来节点的边；测试与全量部署使用完整快照图。
生命周期汇总特征仍存在历史可见性限制，不能称为完整历史时点重建。

数据指纹：`7c6072a04003949ef91a42ff112428766b15f929fcd24be4abb21008d88043b7`。

## 6. 训练、选择与校准

最终选择配方 `standardized_deviation_fusion`，树预算 `compact`，部署种子 42。
参数配置在 [evidence_tree_experiments.yaml](../config/evidence_tree_experiments.yaml)。

| 参数 | 当前值 |
|---|---:|
| 最大树轮数 | 600 |
| 实际主模型轮数 | 101 |
| 学习率 | 0.04 |
| 叶子数 | 15 |
| L2 正则 | 2.0 |
| 最小叶样本数 | 40 |
| AP 早停耐心 | 15 |
| 类别权重 | balanced |
| 训练正类权重 | 17.2680102916 |
| 主模型温度 T | 0.9169176822 |
| 验证选择的分类阈值 | 0.2795115632 |

第四轮按三段验证 AP 加权选择方案：早期开发 22/28 权重 0.2，晚期开发 28/34 权重 0.2，最近验证 34/41 权重 0.6。
最近验证也用于早停、校准和分类阈值选择，其指标有选择偏差。
此协议与前两轮只用训练区间内部开发段的协议不同，比较时保留说明。

综合评分流程：

```text
校正 logit = 联合树原始 margin - log(训练正类权重)
综合风险 = 100 × sigmoid(校正 logit / T)
```

三个诊断模型也各自执行类别权重校正与验证温度校准。
风险等级边界：LOW <30、MEDIUM 30～<60、HIGH 60～<80、CRITICAL ≥80。
评估分类阈值约 27.95 分；等级边界与追踪候选阈值具有不同用途。

## 7. 当前效果与证据收益

来源：[findings.json](../artifacts/experiments/evidence_tree_v1/findings.json)。

| 指标 | 当前主模型 |
|---|---:|
| AP（项目 `pr_auc` 字段） | 0.5429 |
| F1 | 0.5520 |
| Precision | 0.8665 |
| Recall | 0.4050 |
| ROC-AUC | 0.8804 |
| Brier | 0.0298 |

AP 使用 average precision，不是梯形积分的 PR 曲线面积。
混淆矩阵 `[[53729, 159], [1516, 1032]]`；仍有 1,516 个测试 illicit 未在评估阈值下告警。

严格移除消融采用相同 compact 预算和划分，重新训练与校准：

| 方案 | AP | F1 | Recall |
|---|---:|---:|---:|
| 完整联合模型 | 0.5429 | 0.5520 | 0.4050 |
| 去行为画像 | 0.4799 | 0.4965 | 0.3921 |
| 去邻域偏离 | 0.2829 | 0.2825 | 0.1790 |
| 去有向结构 | 0.5114 | 0.5263 | 0.3862 |
| 去边方向并重算图特征 | 0.3445 | 0.3331 | 0.2520 |

以上检验的是三类输入与方向的额外收益，不是三个异构模型互补的实验。
单类诊断对照 AP：行为 0.2229、标准化偏离 0.1879、结构 0.3292。
偏离单独弱，但结合个体行为和结构语境后有效。另有“方向邻居均值”对照 AP 0.4823，它不等同于当前偏离组。

| 已知标签测试复核预算 | 命中 illicit | 命中率 |
|---|---:|---:|
| Top-100 | 100/100 | 100% |
| Top-500 | 488/500 | 97.60% |
| Top-1% | 545/565 | 96.46% |
| Top-5% | 1232/2822 | 43.66% |

这些不是整体准确率，不能推断 unknown 人群的真实命中率。
历史 GraphSAGE 三种子平均 AP 0.3223，原双线路 0.3089，旧三专家组合 0.3642。
当前 compact 树无随机子采样，不同种子输出相同；它是一个确定性结果，不能算三次独立重复验证。

## 8. 已完成的实验探索

| 阶段 | 尝试与决定 | 保存目录 |
|---|---|---|
| 第一轮 | 消除重复图专家，比较纯结构与角色分工；开发选择未稳定超过旧组合 | `roles_v1` |
| 第二轮 | 有向一/二跳、无方向传播、残差、beta 多频滤波；有向特征表现较好，滤波未稳定保持优势 | `graph_signals_v1` |
| 第三轮 | 单类点式网络、三路 Gate、拼接网络；Gate 无开发优势，未进入最终测试 | `multievidence_v1` |
| 第四轮 | 4 类联合特征配方、3 个树预算、三段验证；选择标准化偏离联合树 | `evidence_tree_v1` |
| 严格消融 | 同预算重训去行为、去偏离、去结构、去方向，以及偏离单组模型 | `evidence_tree_v1_ablation` |

未采用的实验也保留，不删去不利结果。完整比较与配置见 [重构说明](RISK_SCORING_REDESIGN.md)。
参考 SGC、SIGN 的传播预计算，Dir-GNN 的方向区分，以及 BWGNN、CARE-GNN 对邻域异常的研究；具体复现范围、官方链接及未复现部分均在重构说明中记录。
LightGBM、标准化偏离、TreeSHAP 等已有方法明确归属。项目亮点是任务适配、证据职责和闭环集成。

## 9. 可解释性已经实现什么

对实际联合树使用原生 TreeSHAP；按三个特征组汇总正负贡献，同时展示每组 Top-5 特征。

```text
模型基准 + 行为贡献 + 偏离贡献 + 结构贡献 = 联合树原始 margin
```

加和残差超过 1e-5 时拒绝输出。随后核对类别权重校正与温度校准，瀑布图展示计算过程。
输出包括原始行为值、模型输入值、方向、特征贡献、三组贡献、校准参数、版本和 revision。
结构/偏离没有对应的“本地址原始交易值”时该字段为空，不填造数值。
贡献与绝对贡献占比属于模型归因，不代表因果关系或融合权重。
代码：[evidence_scoring.py](../src/inference/evidence_scoring.py)。

## 10. 接口与兼容字段

| 位置 | 当前含义 |
|---|---|
| `risk.overall_score` | 校准后的联合风险 |
| `risk.risk_level` | 风险等级 |
| `risk.behavior_score` | 行为单独诊断分 |
| `risk.graph_score` | 沿用历史字段名，当前表示邻域偏离诊断分 |
| `risk.behavior_weight` / `risk.graph_weight` | 当前为 null，无 Gate |
| `scoring_analysis.route_scores` | behavior / context / structure 三个诊断分 |
| `scoring_analysis.groups` | 三组职责、贡献与绝对贡献占比 |
| `scoring_analysis.evidence` | 三组特征证据 |
| `scoring_analysis.base_value` / `raw_margin` | 树基准与实际原始输出 |
| `scoring_analysis.corrected_logit` / `temperature` | 校正输出与温度 |
| `scoring_analysis.additivity_residual` | 归因加和残差 |

风险表另有 `structure_score`、`overall_raw_score`、`risk_rank`。`overall_raw_score` 已执行类别权重校正，但尚未温度校准。
源码变量 `context` 是历史通用名称；当前部署配方中对应标准化偏离，不应解释为邻居均值模型。
Evidence JSON 保留兼容接口并增加 `scoring_analysis`；旧 `investigation_analysis` 不进入当前报告。
真实案例文件：[分析 JSON](../artifacts/reports/1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS_analysis.json)、[Evidence JSON](../artifacts/reports/1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS_evidence.json)。

## 11. 工程部署与关键目录

全部 822,942 地址已离线评分；171 维全量特征保存为 mmap 可读取的缓存。
在线仅查风险表、执行单地址 TreeSHAP、计算图证据及调用后续追踪与报告，不现场训练或全图推理。
模型、验证校准、输入变换、特征缓存、诊断模型与风险表均有哈希绑定，拒绝混用产物。

| 路径 | 用途 |
|---|---|
| `config/scoring.yaml` | 当前部署名称、版本、批量与解释参数 |
| `config/evidence_tree_experiments.yaml` | 树预算、配方和选择规则 |
| `config/evidence_tree_ablation.yaml` | 严格消融配置 |
| `artifacts/experiments/evidence_tree_v1/final/seed_42/standardized_deviation_fusion__compact/` | 联合模型与验证/测试结果 |
| 同一 `seed_42` 下 `behavior_only__compact/`、`structure_only__compact/` | 行为与结构诊断模型 |
| `artifacts/experiments/evidence_tree_v1_ablation/context_z_only/` | 偏离诊断模型 |
| `artifacts/evidence_scoring/` | 171 维输入缓存、评分副本、部署元数据 |
| `artifacts/risk_scores/` | 在线使用的当前风险表和图统计 |
| `artifacts/experiments/evidence_tree_v1/previous_demo/` | 切换前的风险表、案例、路径和报告备份 |
| `src/inference/precompute_evidence_scores.py` | 预计算与安装 |
| `src/inference/risk_predictor.py` | 查表与哈希检查 |
| `src/inference/analysis_service.py` | 分析、证据、追踪联调 |
| `src/ui/evidence_scoring.py` | 评分、队列、评估展示 |

当前评分 revision：`6460ec5d1ccd1ffd4d2ea54297018b0794008add93fa530c8d2942339b17f14e`。

## 12. 已接入的页面与后续模块

- 总览：当前模型、数据规模和测试指标。
- 地址风险：联合风险、三个诊断仪表、职责、组贡献、特征证据和评分瀑布图。
- 优先队列：直接按当前综合风险排序，支持跳转到地址证据。
- 模型评估：主模型指标、单类对照、严格移除、PR/ROC 和混淆矩阵；历史模型仍保留。
- 关系追踪：当前综合风险指导有向 Beam Search，默认扩展阈值 30。
- 报告：Evidence JSON 与模板/LLM 接口接收当前三组证据、联合归因和路径。

默认未知高风险示例 `1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS`：风险 72.7625，4 条真实路径，最深 3 跳。
路径可以含前缀；已知高风险示例当前通常只有一跳，低风险可以无保留路径。
此地址标签 unknown，不称为确认非法。当前追踪仍是关系链，不做金额级归因。

## 13. 验收记录

最近一次完整自动测试：**60 passed，2 skipped**。两个跳过项属于旧调查层，其缓存 revision 与当前模型不同。
`pip check` 无依赖冲突。真实数据 Demo 验收覆盖全量评分、九个案例、归因加和、原始路径边及模板报告。
浏览器检查评分、追踪、报告和评估；桌面 1440px，窄屏 375px 四页没有页面横向溢出。

记录：[离线验收](../artifacts/metrics/demo_acceptance.json)、[界面验收](../artifacts/metrics/ui_acceptance_v2.json)。
截图：[评分](screenshots/evidence_scoring.jpg)、[追踪](screenshots/evidence_tracing.jpg)、[报告](screenshots/evidence_report.jpg)、[评估](screenshots/evidence_evaluation.jpg)。
本文件是当前验收结果的记录；修改模型、数据或实现之后应重新验收。

## 14. 当前产物的复用与复现

在 `E:\网安比赛\web3-aml` 执行。本机 Python 为 `..\.venv\Scripts\python.exe`。
已有冻结训练产物时，重建部署与案例：

```powershell
..\.venv\Scripts\python.exe scripts/21_precompute_evidence_scores.py
..\.venv\Scripts\python.exe scripts/22_report_risk_redesign.py
..\.venv\Scripts\python.exe scripts/07_build_demo_cases.py
..\.venv\Scripts\python.exe scripts/08_validate_demo.py
..\.venv\Scripts\python.exe -m pytest -q -rs
.\run_demo.ps1
```

完整四轮实验使用脚本 16–20，前置历史模型、缓存和步骤见 [重构说明](RISK_SCORING_REDESIGN.md)。
这不是无前置依赖的从零训练承诺。完成结果可复用；改冻结参数应使用新实验名称。
旧脚本 06 与 `run_pipeline.ps1` 会生成历史评分，运行后须按当前部署步骤恢复模型并重新验收。

## 15. 当前限制与后续事项

- 同一公开测试集此前已被查看，本轮是重复基准实验，不是外部盲测。
- 生命周期统计和快照关系不能还原历史时点信息；不宣传为实时早期检测。
- unknown 的真实命中率、外部泛化和校准效果尚未验证。
- 确定性树不提供三次独立重复证据；尚无独立外部图评估。
- 真实 LLM API 未配置，当前模板报告和失败回退已验收，真实网络调用未验收。
- 当前算法适用于已有数据集地址，无实时 RPC 接入或金额级资金污染归属。
- 三个诊断模型只承担辅助说明，主模型性能对应的是联合特征决策。

进一步优化可在独立数据/时间划分、外部校准及真实 API 联调上验证；这些尚未作为本模块完成项。

## 16. 比赛表述

推荐名称：**方向感知的多视角特征融合评分**，或沿用当前部署名“有向邻域对比证据融合”。

> 构建地址行为、上下游相对偏离、有向结构三类特征，通过一个轻量联合模型输出风险。单组诊断帮助理解证据，TreeSHAP 解释实际联合决策。移除实验验证三类特征和边方向的额外价值，综合风险进一步指导关系追踪和解释报告。

不把当前方案称为“三种模型融合”，不把诊断分当作融合权重，也不把公开方法轻量复现宣称为原创算法。

相关入口：[结构图](RISK_SCORING_FLOWCHART.md)、[完整实验与论文](RISK_SCORING_REDESIGN.md)、[演示指南](DEMO_GUIDE.md)、[评估边界](EVALUATION_PROTOCOL.md)。
