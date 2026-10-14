# Web3 轻量化反洗钱智能分析系统
## Agent Implementation Specification / 可直接执行的项目实现说明

> **用途**：本文件面向后续开发 Agent、代码 Agent 或团队成员。阅读完本文件后，应能够在不依赖额外口头说明的情况下，直接开始搭建、训练、测试和演示项目。
>
> **项目定位**：这是一个面向比赛展示的、强调完成度和可解释性的轻量化 Web3 反洗钱（AML）智能分析系统。项目不追求复刻大型商业 AML 平台，也不追求最复杂的学术模型，而是要形成一个**可运行、可演示、可量化评估、可解释、模块闭环完整**的原型系统。
>
> **总原则**：优先保证端到端可运行，其次保证效果，再考虑模型复杂度。不要为了“创新”牺牲可复现性。

---

# 1. 项目目标

系统需要完成四个核心任务：

1. **地址风险评分**
   - 使用公开区块链 AML 数据集。
   - 对地址/节点输出 `0~100` 的风险评分。
   - 主模型采用“双线路风险评分”：地址行为特征 + 图结构特征。
   - 同时给出行为风险、图结构风险和综合风险。

2. **风险引导的可疑资金/交易关系链追踪**
   - 从输入地址作为 Seed 出发。
   - 沿有向地址关系图向下游扩展。
   - 不使用无约束 BFS，而使用 Risk-Guided Beam Search。
   - 优先保留风险高、关系更值得继续分析的路径。
   - 第一版定义为“可疑交易关系链追踪”，不是严格金额级资金污染追踪。

3. **证据组织与可解释分析**
   - 将地址风险、行为证据、图结构证据、可疑路径统一整理为结构化 JSON。
   - LLM 不能直接判断“是否洗钱”，只能基于结构化证据生成解释报告。

4. **可视化 Web 演示**
   - 使用 Streamlit。
   - 支持输入地址/节点 ID。
   - 展示风险仪表、双线路风险、可解释证据、可疑路径图和 LLM 报告。
   - 必须具备稳定的比赛 Demo 流程。

---

# 2. 项目一句话描述

> 本系统基于公开区块链反洗钱数据，构建“地址风险识别—风险引导路径追踪—结构化证据融合—大模型可解释报告”的完整分析闭环，实现对高风险地址及其关联交易路径的轻量化智能分析。

---

# 3. 总体架构

```text
                    ┌───────────────────────┐
                    │   Elliptic++ Dataset  │
                    └───────────┬───────────┘
                                │
                    数据清洗 / ID 映射 / 图构建
                                │
                ┌───────────────┴────────────────┐
                │                                │
                ▼                                ▼
       Address Feature Table              Directed Graph
                │                                │
                ▼                                │
    ┌──────────────────────┐                     │
    │  双线路地址风险评分   │                     │
    │                      │                     │
    │ Behavior MLP         │                     │
    │ GraphSAGE            │                     │
    │ Gated Fusion         │                     │
    └──────────┬───────────┘                     │
               │                                 │
               ▼                                 │
     Address Risk Score Table                    │
               │                                 │
               └──────────────┬──────────────────┘
                              ▼
                  Risk-Guided Beam Search
                              │
                              ▼
                 Suspicious Relation Paths
                              │
             ┌────────────────┴────────────────┐
             │                                 │
             ▼                                 ▼
     Behavior/Graph Evidence              Path Evidence
             │                                 │
             └────────────────┬────────────────┘
                              ▼
                    Evidence Builder
                              │
                              ▼
                    Structured JSON
                              │
                              ▼
                  Evidence-Grounded LLM
                              │
                              ▼
                  Explainable AML Report
                              │
                              ▼
                      Streamlit UI
```

---

# 4. 技术选型

| 功能 | 技术 |
|---|---|
| 数据处理 | Python、Pandas、NumPy |
| 主风险模型 | PyTorch + PyTorch Geometric |
| 行为分支 | MLP |
| 图结构分支 | GraphSAGE |
| 融合 | Gated Fusion |
| 类别不平衡 | Focal Loss |
| 最终风险概率 | Temperature Scaling |
| 行为解释 | Captum Integrated Gradients |
| 图指标 | NetworkX / 自定义统计 |
| 追踪 | 邻接表/NetworkX + Beam Search |
| Baseline | LightGBM |
| 报告生成 | OpenAI-Compatible LLM API |
| Web 前端 | Streamlit |
| 图可视化 | Plotly 或 PyVis |
| 配置 | YAML |
| 缓存 | CSV / Parquet / Pickle / Torch PT |

推荐 Python 版本：**3.10 或 3.11**。

---

# 5. 数据集

## 5.1 默认数据集：Elliptic++

优先使用 **Elliptic++ Actors Dataset**。

官方仓库：

```text
https://github.com/git-disl/EllipticPlusPlus
```

第一版只依赖三类信息：

```text
地址特征表
地址标签表
地址-地址边表
```

项目内部统一路径：

```text
data/raw/
├── wallets_features.csv
├── wallets_classes.csv
└── AddrAddr_edgelist.csv
```

如果实际文件名不同，不修改业务代码，而在：

```text
config/data.yaml
```

中适配。

示例：

```yaml
dataset:
  name: ellipticpp
  features_file: data/raw/wallets_features.csv
  labels_file: data/raw/wallets_classes.csv
  edges_file: data/raw/AddrAddr_edgelist.csv

columns:
  address_id: address
  label: class
  src: src
  dst: dst
  timestep: timestep
```

开发第一步必须运行 `inspect_dataset.py`，打印列名、Shape、标签分布，然后完成字段适配。

---

# 6. 标签定义

统一映射：

```text
licit   -> 0
illicit -> 1
unknown -> -1
```

规则：

- `licit` 与 `illicit` 用于监督训练。
- `unknown` 不进入训练损失。
- `unknown` 允许进入推理阶段。
- 不得把 unknown 当作 licit。

风险等级：

```text
0 <= score < 30      -> LOW
30 <= score < 60     -> MEDIUM
60 <= score < 80     -> HIGH
80 <= score <= 100   -> CRITICAL
```

配置：

```yaml
risk_level:
  low: 30
  medium: 60
  high: 80
```

---

# 7. 数据预处理模块

文件：

```text
src/data/preprocess.py
```

职责：

1. 读取 feature / label / edge 文件。
2. 检查重复地址。
3. 处理缺失值。
4. 数值特征标准化。
5. 构造统一 node index。
6. 保存地址 ID 与 node index 双向映射。
7. 构造图模型 `edge_index`。
8. 构造追踪模块有向邻接表。
9. 划分训练、验证、测试集。
10. 保存处理产物。

输出：

```text
data/processed/
├── features.npy
├── labels.npy
├── edge_index.pt
├── train_mask.npy
├── val_mask.npy
├── test_mask.npy
├── address_to_idx.json
├── idx_to_address.json
├── outgoing_neighbors.pkl
├── incoming_neighbors.pkl
└── scaler.pkl
```

---

# 8. 图的两种视图

## 8.1 模型图 G_model

用于 GraphSAGE。

原始有向边：

```text
A -> B
```

转换为消息传播双向边：

```text
A -> B
B -> A
```

即：

```python
edge_index_model = to_undirected(edge_index)
```

## 8.2 追踪图 G_trace

必须保留原始方向：

```text
A -> B
```

只沿 downstream/outgoing 方向追踪。

结论：

```text
G_model = bidirectional message-passing graph
G_trace = original directed relation graph
```

---

# 9. 数据划分

优先采用时间划分。

如果数据中存在 timestep：

```text
按 timestep 从早到晚排序
前 70% timestep -> train
中间 15%        -> validation
最后 15%        -> test
```

如果没有 timestep，则：

```text
Stratified 70/15/15
```

仅对已知标签节点划分。

固定随机种子：

```yaml
seed: 42
```

---

# 10. 模块一：双线路地址风险评分

模块名：

> Dual-View Address Risk Scorer

组成：

```text
Behavior Encoder
Graph Encoder
Gated Fusion
Risk Heads
Calibration
```

---

# 11. 行为分支 Behavior Encoder

输入：

```text
x_v ∈ R^F
```

网络：

```text
F
↓
Linear(F, 128)
↓
ReLU
↓
Dropout(0.2)
↓
Linear(128, 64)
↓
ReLU
↓
Behavior Embedding h_b
```

文件：

```text
src/model/behavior_encoder.py
```

接口：

```python
class BehaviorEncoder(nn.Module):
    def __init__(self, input_dim, hidden_dim=128, out_dim=64):
        ...

    def forward(self, x):
        return h_behavior
```

---

# 12. 图结构分支 GraphSAGE

文件：

```text
src/model/graph_encoder.py
```

第一版两层 GraphSAGE：

```text
Input Features F
↓
SAGEConv(F, 128)
↓
ReLU
↓
Dropout(0.2)
↓
SAGEConv(128, 64)
↓
Graph Embedding h_g
```

使用 PyG `NeighborLoader`。

默认：

```yaml
graphsage:
  num_neighbors: [15, 10]
  batch_size: 1024
  hidden_dim: 128
  out_dim: 64
  dropout: 0.2
```

低显存：

```text
batch_size = 256
num_neighbors = [10, 5]
```

---

# 13. Gated Fusion

输入：

```text
h_behavior ∈ R^64
h_graph    ∈ R^64
```

门控：

```math
g_v = sigmoid(W_g [h_b || h_g] + b_g)
```

第一版用标量 gate。

融合：

```math
h_v = g_v * h_b + (1 - g_v) * h_g
```

解释：

```text
g_v 越大 -> 更依赖行为分支
g_v 越小 -> 更依赖图结构分支
```

前端展示：

```text
Behavior Importance = g_v
Graph Importance = 1 - g_v
```

---

# 14. 三个 Risk Head

需要三个 Head：

```text
Behavior Head:
h_b -> Linear(64, 1)

Graph Head:
h_g -> Linear(64, 1)

Fusion Head:
h_fused -> Linear(64, 1)
```

输出：

```text
behavior_score
graph_score
overall_raw_score
```

综合风险以 fused 为准。

---

# 15. 损失函数

使用 Focal Loss。

总损失：

```math
L = L_fused + 0.2 L_behavior + 0.2 L_graph
```

默认：

```yaml
focal_loss:
  alpha: 0.75
  gamma: 2.0
```

训练不稳定时允许回退：

```text
BCEWithLogitsLoss(pos_weight=...)
```

---

# 16. 训练参数

```yaml
training:
  seed: 42
  epochs: 50
  learning_rate: 0.001
  weight_decay: 0.0001
  early_stop_patience: 8
  monitor: pr_auc
```

保存：

```text
best_model.pt
training_history.json
metrics.json
```

---

# 17. 风险概率校准

validation set 上训练 Temperature Scaling 参数 T：

```math
p_calibrated = sigmoid(z_fused / T)
```

最终：

```math
risk_score = 100 * p_calibrated
```

产物：

```text
artifacts/model/
├── dual_view_model.pt
├── temperature.json
└── model_config.json
```

---

# 18. Baseline：LightGBM

必须保留。

文件：

```text
src/baseline/lightgbm_baseline.py
```

作用：

- 对比实验。
- 备用模型。
- 验证预处理。

至少输出：

```text
Precision
Recall
F1
ROC-AUC
PR-AUC
```

最终比较：

```text
LightGBM
Behavior MLP
GraphSAGE
Dual-View
```

---

# 19. 模型评价指标

主要展示：

```text
Precision
Recall
F1
PR-AUC
ROC-AUC
```

可选：

```text
Balanced Accuracy
Brier Score
ECE
```

比赛页至少展示：

```text
F1
Recall
PR-AUC
```

并生成：

```text
Confusion Matrix
PR Curve
ROC Curve
```

---

# 20. 批量离线风险预测

提供：

```text
scripts/precompute_risk_scores.py
```

输出：

```text
artifacts/risk_scores/risk_scores.parquet
```

字段：

```text
address_id
node_idx
behavior_score
graph_score
overall_raw_score
overall_risk_score
risk_level
behavior_weight
graph_weight
```

比赛现场直接查表，不重新对全图推理。

---

# 21. 行为解释

主模型使用 Captum Integrated Gradients。

文件：

```text
src/explain/behavior_explainer.py
```

输出 Top-K：

```json
[
  {
    "feature": "feature_12",
    "value": 2.41,
    "attribution": 0.184
  }
]
```

默认：

```text
top_k = 5
```

若有真实特征语义，配置：

```text
config/feature_names.yaml
```

若数据集特征匿名，不得编造含义。

---

# 22. 图结构解释

文件：

```text
src/explain/graph_evidence.py
```

计算：

```text
out_degree
in_degree
1-hop neighbor count
1-hop average risk
1-hop high-risk neighbor count
1-hop high-risk ratio
2-hop sampled average risk
2-hop sampled high-risk ratio
```

示例：

```json
{
  "out_degree": 18,
  "in_degree": 6,
  "one_hop_neighbor_count": 21,
  "one_hop_avg_risk": 72.4,
  "one_hop_high_risk_count": 13,
  "one_hop_high_risk_ratio": 0.619,
  "two_hop_avg_risk": 67.1,
  "two_hop_high_risk_ratio": 0.534
}
```

在线解释不得用 Ground Truth 标签。

---

# 23. 模块一标准输出

```json
{
  "address_id": "A",
  "risk": {
    "overall_score": 92.6,
    "risk_level": "CRITICAL",
    "behavior_score": 87.3,
    "graph_score": 95.8,
    "behavior_weight": 0.41,
    "graph_weight": 0.59
  },
  "behavior_evidence": [
    {
      "feature": "F12",
      "feature_value": 2.41,
      "contribution": 0.184
    }
  ],
  "graph_evidence": {
    "out_degree": 18,
    "in_degree": 6,
    "one_hop_avg_risk": 72.4,
    "one_hop_high_risk_ratio": 0.619
  }
}
```

---

# 24. 模块二：风险引导关系链追踪

模块名：

> Risk-Guided Relation Tracer

第一版准确描述：

> 基于地址交易关系图，对高风险关联地址和可疑交易关系链进行优先级追踪。

输入：

```text
Seed Address
Directed Graph
Precomputed Risk Scores
Tracing Config
```

---

# 25. Beam Search

不用 BFS。

每层只保留 Top-K 候选路径。

默认参数：

```yaml
tracing:
  max_depth: 4
  beam_width: 5
  risk_threshold: 50
  max_neighbors_per_node: 50
  top_paths: 10
  cycle_check: true
```

Demo 推荐：

```text
max_depth = 3 或 4
beam_width = 5
```

---

# 26. 节点扩展分数

V1 不依赖金额。

```math
ExpandScore(v)
=
0.75 * Risk(v)
+
0.15 * NeighborRisk(v)
+
0.10 * DegreePenalty(v)
```

其中：

```text
Risk(v)
= overall_risk_score / 100
```

```text
NeighborRisk(v)
= v 的一跳邻居平均风险 / 100
```

DegreePenalty：

```math
DegreePenalty(v)
=
1 - clip(
    log(1 + degree(v)) / log(1 + degree_p99),
    0,
    1
)
```

它只用于搜索排序，不代表高 degree 一定正常。

---

# 27. 路径分数

路径：

```text
A -> B -> C -> D
```

定义：

```math
PathScore
=
mean(
  ExpandScore(B),
  ExpandScore(C),
  ExpandScore(D)
)
```

长度衰减：

```math
FinalPathScore
=
PathScore * exp(-0.03 * (hop_count - 1))
```

---

# 28. Beam Search 伪代码

```python
def trace(seed, graph, risk_table, config):
    beam = [Path(nodes=[seed], score=1.0)]
    completed = []

    for depth in range(config.max_depth):
        candidates = []

        for path in beam:
            current = path.nodes[-1]
            neighbors = graph.out_neighbors(current)

            neighbors = limit_neighbors(
                neighbors,
                max_count=config.max_neighbors_per_node
            )

            for v in neighbors:
                if config.cycle_check and v in path.nodes:
                    continue

                if risk_table[v] < config.risk_threshold:
                    continue

                expand_score = calc_expand_score(v)
                new_path = path.extend(v, expand_score)
                candidates.append(new_path)

        if not candidates:
            break

        candidates = sort_by_path_score(candidates)
        beam = candidates[:config.beam_width]
        completed.extend(beam)

    return top_k(completed, config.top_paths)
```

---

# 29. 邻居限制

节点下游过多时：

```text
按 Risk Score 降序
取前 max_neighbors_per_node
```

默认：

```text
50
```

---

# 30. 停止条件

任一满足即停止：

```text
达到 max_depth
无下游节点
候选 risk < risk_threshold
节点已在当前路径
候选分支未进入 Beam Top-K
```

---

# 31. 追踪输出

```json
{
  "seed_address": "A",
  "config": {
    "max_depth": 4,
    "beam_width": 5,
    "risk_threshold": 50
  },
  "statistics": {
    "visited_nodes": 53,
    "candidate_nodes": 118,
    "high_risk_nodes": 12,
    "pruned_nodes": 65,
    "max_reached_depth": 4
  },
  "top_paths": [
    {
      "rank": 1,
      "nodes": ["A", "C", "E", "H"],
      "node_risks": [92.6, 91.2, 88.3, 93.1],
      "path_score": 0.913
    }
  ]
}
```

---

# 32. 可视化追踪子图

输出：

```text
Seed
+
Top-K paths 中节点
+
对应有向边
```

保存：

```text
artifacts/traces/{address_id}.json
```

节点：

```text
address_id
risk_score
risk_level
is_seed
```

边：

```text
src
dst
path_rank
```

---

# 33. 模块三：Evidence Builder

文件：

```text
src/report/evidence_builder.py
```

输入：

```text
Risk Analysis
Behavior Evidence
Graph Evidence
Trace Result
```

输出固定 JSON。

---

# 34. Evidence JSON Schema

```json
{
  "meta": {
    "dataset": "Elliptic++",
    "analysis_type": "automated AML risk analysis",
    "generated_at": "ISO-8601 time"
  },

  "target": {
    "address_id": "A"
  },

  "risk_analysis": {
    "overall_score": 92.6,
    "risk_level": "CRITICAL",
    "behavior_score": 87.3,
    "graph_score": 95.8,
    "behavior_weight": 0.41,
    "graph_weight": 0.59
  },

  "behavior_evidence": [
    {
      "feature": "F12",
      "value": 2.41,
      "contribution": 0.184
    }
  ],

  "graph_evidence": {
    "out_degree": 18,
    "in_degree": 6,
    "one_hop_avg_risk": 72.4,
    "one_hop_high_risk_ratio": 0.619,
    "two_hop_avg_risk": 67.1
  },

  "trace_analysis": {
    "max_depth": 4,
    "visited_nodes": 53,
    "high_risk_nodes": 12,
    "top_paths": [
      {
        "nodes": ["A", "C", "E", "H"],
        "node_risks": [92.6, 91.2, 88.3, 93.1],
        "path_score": 0.913
      }
    ]
  },

  "limitations": [
    "Risk scores are model outputs, not legal conclusions.",
    "The current tracer follows address relations and does not perform exact amount-level taint attribution.",
    "The dataset may contain incomplete or unknown labels."
  ]
}
```

---

# 35. 模块四：LLM 报告

模块：

> Evidence-Grounded AML Report Generator

文件：

```text
src/report/llm_reporter.py
```

LLM 只做：

```text
结构化证据 -> 自然语言说明
```

禁止：

```text
重新计算风险
修改风险分数
发明交易
猜真实身份
断言犯罪事实
```

---

# 36. System Prompt

```text
你是一名 Web3 反洗钱分析报告助手。

你只能依据用户提供的结构化 Evidence JSON 生成报告。

严格遵守以下规则：
1. 不得编造 Evidence JSON 中不存在的地址、分数、路径、交易或身份。
2. 不得将模型风险评分表述为法律结论。
3. 不得声称某地址所有者一定参与洗钱。
4. 如果证据不足，应明确写出“当前证据不足”。
5. 必须区分“模型预测”“图结构关联”“路径分析”和“事实标签”。
6. 所有数字必须来自 Evidence JSON。
7. 报告应面向分析人员，语言专业、简洁、可审核。
```

User Prompt：

```text
请根据以下 Evidence JSON 生成 Web3 AML 风险分析报告。

报告固定包含：

1. 地址风险概述
2. 行为风险证据
3. 图结构风险证据
4. 可疑关联路径
5. 综合研判
6. 风险提示与系统局限

Evidence JSON:
{evidence_json}
```

---

# 37. LLM 配置

```yaml
llm:
  enabled: true
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}
  temperature: 0.2
  timeout: 60
```

环境变量：

```text
LLM_BASE_URL=
LLM_API_KEY=
LLM_MODEL=
```

必须同时实现：

```text
TemplateReporter
LLMReporter
```

API 失败时使用模板报告。

---

# 38. Streamlit UI

入口：

```text
app.py
```

至少 5 个页面：

```text
1. 系统总览
2. 地址风险分析
3. 关系链追踪
4. AI 分析报告
5. 模型评估
```

---

# 39. 系统总览页

展示：

```text
Dataset: Elliptic++
Known labeled nodes
Unknown nodes
Graph edges
Model version
Model test F1
Model PR-AUC
```

附系统架构图。

---

# 40. 地址风险页

输入：

```text
Address / Node ID
```

展示：

```text
Overall Risk Gauge
Behavior Risk Gauge
Graph Risk Gauge
Risk Level
Fusion Weights
Top Behavior Evidence
Graph Evidence
```

推荐：

```text
综合风险：92.6
CRITICAL

Behavior Risk：87.3
Graph Risk：95.8

Behavior Weight：41%
Graph Weight：59%
```

---

# 41. 关系链追踪页

参数：

```text
Max Depth
Beam Width
Risk Threshold
Top Paths
```

默认：

```text
4
5
50
10
```

展示：

```text
可疑关系图
Top-K Paths
追踪统计
```

节点：

```text
颜色 = 风险等级
大小 = risk_score 或 degree
Seed 特别高亮
```

---

# 42. AI 报告页

按钮：

```text
[生成 AML 分析报告]
```

支持：

```text
下载 Markdown
下载 TXT
```

PDF 非 V1 硬要求。

---

# 43. 模型评估页

展示：

```text
LightGBM
Behavior MLP
GraphSAGE
Dual-View
```

指标：

```text
Precision
Recall
F1
PR-AUC
ROC-AUC
```

图：

```text
PR Curve
ROC Curve
Confusion Matrix
```

---

# 44. 项目目录结构

```text
web3-aml/
│
├── README.md
├── requirements.txt
├── app.py
│
├── config/
│   ├── data.yaml
│   ├── model.yaml
│   ├── tracing.yaml
│   ├── feature_names.yaml
│   └── llm.yaml
│
├── data/
│   ├── raw/
│   └── processed/
│
├── artifacts/
│   ├── model/
│   ├── metrics/
│   ├── risk_scores/
│   ├── traces/
│   └── reports/
│
├── src/
│   ├── data/
│   │   ├── inspect_dataset.py
│   │   └── preprocess.py
│   ├── model/
│   │   ├── behavior_encoder.py
│   │   ├── graph_encoder.py
│   │   ├── fusion.py
│   │   ├── dual_view_model.py
│   │   ├── focal_loss.py
│   │   └── calibration.py
│   ├── baseline/
│   │   └── lightgbm_baseline.py
│   ├── train/
│   │   ├── train.py
│   │   └── evaluate.py
│   ├── inference/
│   │   ├── risk_predictor.py
│   │   └── precompute_scores.py
│   ├── explain/
│   │   ├── behavior_explainer.py
│   │   └── graph_evidence.py
│   ├── tracing/
│   │   ├── graph_loader.py
│   │   ├── path_scorer.py
│   │   └── beam_search.py
│   ├── report/
│   │   ├── evidence_builder.py
│   │   ├── llm_reporter.py
│   │   └── template_reporter.py
│   └── utils/
│       ├── seed.py
│       ├── io.py
│       └── logging.py
│
├── scripts/
│   ├── 01_inspect_data.py
│   ├── 02_preprocess.py
│   ├── 03_train_baseline.py
│   ├── 04_train_dual_view.py
│   ├── 05_evaluate.py
│   ├── 06_precompute_scores.py
│   └── 07_build_demo_cases.py
│
└── tests/
    ├── test_preprocess.py
    ├── test_model.py
    ├── test_tracing.py
    └── test_evidence_builder.py
```

---

# 45. requirements.txt

```text
numpy
pandas
scikit-learn
lightgbm
torch
torch-geometric
networkx
captum
pyyaml
joblib
pyarrow
streamlit
plotly
pyvis
pydantic
openai
python-dotenv
matplotlib
```

---

# 46. 推荐运行顺序

```bash
python scripts/01_inspect_data.py
python scripts/02_preprocess.py
python scripts/03_train_baseline.py
python scripts/04_train_dual_view.py
python scripts/05_evaluate.py
python scripts/06_precompute_scores.py
python scripts/07_build_demo_cases.py
streamlit run app.py
```

README 必须保证上述流程可执行。

---

# 47. Demo Cases

生成：

```text
artifacts/demo_cases.json
```

至少：

```text
3 个 test illicit
3 个 test licit
3 个 unknown 高风险地址
```

示例：

```json
{
  "high_risk_known": ["A", "B", "C"],
  "low_risk_known": ["D", "E", "F"],
  "high_risk_unknown": ["G", "H", "I"]
}
```

UI 提供：

```text
[加载高风险示例]
[加载低风险示例]
[加载未知高风险示例]
```

---

# 48. 比赛 Demo 固定流程

```text
1. 选择预置高风险地址
2. 展示综合风险
3. 展示 Behavior / Graph 双线路结果
4. 展示融合权重
5. 展示行为证据
6. 展示图结构证据
7. 点击“关系链追踪”
8. 展示 Top-3 可疑路径
9. 图中高亮最高风险路径
10. 点击“生成 AI 报告”
11. 展示 Evidence-Grounded 报告
12. 打开模型评估页展示模型效果
```

---

# 49. 工程原则

## 49.1 训练与在线演示分离

离线：

```text
Train
Evaluate
Precompute Risk Scores
Build Demo Cases
```

在线：

```text
Lookup Risk
Compute Evidence
Run Beam Search
Call LLM
Render UI
```

## 49.2 所有耗时步骤缓存

缓存：

```text
processed features
graph
risk scores
graph metrics
demo traces
```

Streamlit 使用：

```python
@st.cache_resource
@st.cache_data
```

## 49.3 LLM 必须有 fallback

```text
LLM 失败
↓
Template Report
```

---

# 50. 测试要求

## 数据测试

验证：

```text
节点数 > 0
边数 > 0
feature shape 正确
known label 数 > 0
unknown 不进入 train mask
```

## 模型测试

小图上验证：

```text
forward shape
risk ∈ [0,1]
gate ∈ [0,1]
```

## Tracing 测试

构造：

```text
A -> B -> D
A -> C -> E
```

让 B/D 高风险，C/E 低风险。

预期：

```text
Beam Search 优先 A-B-D
```

并验证：

```text
cycle check
max_depth
threshold
```

## Evidence Builder

验证：

```text
字段齐全
缺失字段不崩溃
报告数字均能追溯到 JSON
```

---

# 51. Definition of Done

项目只有同时满足这些条件才算完成：

## 数据

- 能自动读取公开数据。
- 能构造 features、labels、模型图、追踪图。
- 能保存处理结果。

## 风险模型

- LightGBM Baseline 可训练。
- Dual-View 模型可训练。
- 能保存最佳模型。
- 能输出测试指标。
- 能预计算全部地址 Risk Score。

## 可解释性

- 地址能输出 Behavior Evidence。
- 地址能输出 Graph Evidence。
- 能展示两个分支和融合权重。

## 追踪

- 能输入 Seed。
- 能在有向图上运行 Beam Search。
- 能输出 Top-K path。
- 能输出统计。
- 能生成可视化子图。

## 报告

- 能构造 Evidence JSON。
- 能调用 LLM 生成报告。
- API 失败时能使用模板报告。

## 前端

- Streamlit 可完整运行。
- 5 个页面功能可用。
- 一键 Demo Case 可用。

---

# 52. 比赛可讲的项目亮点

## 双视角风险感知

```text
地址自身行为
+
地址交易关系
```

## 自适应风险融合

Gate 自动学习：

```text
行为证据 vs 图结构证据
```

## 风险驱动路径追踪

不是：

```text
所有路径都追
```

而是：

```text
优先追高风险路径
```

## 模型与 LLM 解耦

```text
模型产生风险
算法产生路径
证据模块组织事实
LLM 负责解释
```

## 完整分析闭环

```text
风险识别
→ 关系追踪
→ 证据组织
→ 可解释报告
→ 可视化
```

---

# 53. V1 明确不做

第一版不实现：

```text
实时链上 RPC 抓取
跨链 Bridge 关联
DEX Token Swap 语义解析
Mixer 专项识别
真实身份去匿名
KYC 接入
精确金额级 Taint Propagation
复杂 HGT
Temporal Transformer
多 Agent 协同
```

这些作为 Future Work。

---

# 54. V2 可扩展

V1 完成后可增加：

```text
金额级边权
时间衰减
Temporal GraphSAGE
真实链上 RPC
Bridge Association
Token Swap
服务地址识别
异构图
跨链追踪
```

追踪接口预留：

```python
edge_features = {
    "amount_score": None,
    "time_score": None
}
```

---

# 55. Agent 开发优先级

```text
P0 数据读入和预处理
↓
P1 LightGBM Baseline
↓
P2 Behavior MLP
↓
P3 GraphSAGE
↓
P4 Gated Fusion 主模型
↓
P5 模型评估
↓
P6 全量风险预计算
↓
P7 行为 / 图证据
↓
P8 Beam Search
↓
P9 Evidence Builder
↓
P10 Template Report
↓
P11 LLM Report
↓
P12 Streamlit
↓
P13 Demo Cases
↓
P14 测试、优化、答辩素材
```

---

# 56. 每阶段验收点

## P0

输出：

```text
num_nodes
num_edges
num_features
licit_count
illicit_count
unknown_count
```

## P1

得到 LightGBM F1 / PR-AUC。

## P2

Behavior MLP 可完整训练。

## P3

GraphSAGE 采样训练稳定。

## P4

能返回：

```text
behavior_score
graph_score
overall_score
gate
```

## P5

生成对比表。

## P6

生成：

```text
risk_scores.parquet
```

## P7

测试地址可返回 explanation JSON。

## P8

Seed 可返回 Top-K paths。

## P9

Evidence Builder 固定 Schema。

## P10

无 LLM 时生成报告。

## P11

LLM 报告成功。

## P12

Streamlit 可操作。

## P13

比赛案例一键加载。

---

# 57. 配置文件建议

`config/model.yaml`

```yaml
model:
  behavior_hidden: 128
  embedding_dim: 64
  graph_hidden: 128
  dropout: 0.2

graphsage:
  num_neighbors: [15, 10]
  batch_size: 1024

training:
  seed: 42
  epochs: 50
  learning_rate: 0.001
  weight_decay: 0.0001
  early_stop_patience: 8

focal_loss:
  alpha: 0.75
  gamma: 2.0
```

`config/tracing.yaml`

```yaml
max_depth: 4
beam_width: 5
risk_threshold: 50
max_neighbors_per_node: 50
top_paths: 10
cycle_check: true

score_weight:
  risk: 0.75
  neighbor_risk: 0.15
  degree_penalty: 0.10
```

---

# 58. 日志

统一 Python logging。

记录：

```text
数据加载
训练 epoch
validation metric
best checkpoint
risk precompute
beam search 参数
LLM 请求失败
fallback 触发
```

日志目录：

```text
logs/
├── preprocess.log
├── train.log
├── inference.log
└── app.log
```

---

# 59. README 必须包含

```text
项目简介
系统架构图
功能截图
环境要求
数据下载说明
安装步骤
训练步骤
运行步骤
目录结构
模型说明
Beam Search 说明
LLM 配置
Demo 地址
指标结果
局限性
```

---

# 60. 常见问题处理

## 显存不足

降低：

```text
batch_size
num_neighbors
hidden_dim
```

## GraphSAGE 太慢

降低 NeighborLoader 采样规模，先小数据调通。

## 模型全部预测 licit

检查：

```text
Focal Loss
label mapping
train mask
class imbalance
learning rate
```

## Beam Search 太慢

降低：

```text
max_depth
beam_width
max_neighbors_per_node
```

并使用预计算风险表。

## LLM 编造

必须使用：

```text
严格 System Prompt
Evidence JSON
temperature = 0.2
```

## Streamlit 卡顿

页面加载时不得训练。

只读取：

```text
model artifact
risk_scores
cached graph
```

---

# 61. 最终输入输出

## 输入

至少：

```text
Address / Node ID
```

可选：

```text
Max Depth
Beam Width
Risk Threshold
```

## 输出

必须同时提供：

```text
综合风险分
风险等级
行为风险分
图结构风险分
融合权重
行为证据
图结构证据
Top-K 可疑关系路径
风险关系图
追踪统计
LLM AML 报告
```

---

# 62. 最终系统逻辑

```text
公开 AML 数据
    ↓
地址行为与交易图建模
    ↓
双视角风险评分
    ↓
风险分数指导路径搜索
    ↓
生成高风险关系链
    ↓
融合行为、图结构和路径证据
    ↓
LLM 生成受证据约束的 AML 报告
    ↓
可视化给分析人员
```

---

# 63. Agent 执行要求

1. 不要重新设计总体技术路线。
2. 不要擅自增加复杂模型。
3. 优先实现 V1。
4. 每完成一个阶段必须运行测试。
5. 所有参数放配置文件。
6. 所有中间产物可保存、可复用。
7. 模型训练与在线 Demo 分离。
8. 数据字段差异通过 Adapter 解决，不修改总体接口。
9. 第一目标是端到端闭环运行。
10. 任何“创新”不能破坏稳定性和可复现性。

---

# 64. 最终验收演示

如果下面流程成功，V1 完成：

```text
启动 Streamlit
↓
选择一个高风险 Demo 地址
↓
显示：
综合风险 / 风险等级
Behavior Risk
Graph Risk
融合权重
↓
展示行为和图结构证据
↓
点击关系链追踪
↓
展示 Top-3 可疑路径和关系图
↓
点击生成报告
↓
输出结构化 AML 风险分析
↓
切换模型评估页面
↓
展示 Dual-View 与 LightGBM 等模型对比
```

---

# 65. 当前版本最终技术方案

```text
Dataset:
Elliptic++

Risk Detection:
Behavior MLP
+
GraphSAGE
+
Gated Fusion
+
Focal Loss
+
Temperature Scaling

Explainability:
Integrated Gradients
+
Graph Risk Statistics

Tracing:
Directed Graph
+
Risk-Guided Beam Search

Evidence:
Structured JSON Builder

LLM:
Evidence-Grounded Report Generator
+
Template Fallback

Frontend:
Streamlit
+
Plotly/PyVis

Baseline:
LightGBM
```

**除非 V1 已经完成，否则不要继续增加复杂组件。**
