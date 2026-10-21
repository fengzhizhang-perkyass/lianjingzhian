# 前端交接与运行说明

本补充包供已拿到 `data/processed` 的同学使用。它包含当前版本的代码、配置、运行所需 artifacts，以及自检脚本；不包含 processed、原始 CSV、Python 虚拟环境或 API 密钥。无需重新下载数据或训练模型。

## 1 解压位置

先解压补充包，以解压出来的 `web3-aml` 为运行目录。将已经收到的 processed 文件夹放到这里：

```text
web3-aml/
├── app.py
├── src/
├── config/
├── artifacts/
├── data/
│   └── processed/
│       ├── metadata.json
│       ├── raw_features.npy
│       ├── address_to_idx.json
│       ├── idx_to_address.json
│       ├── outgoing_neighbors.pkl
│       ├── incoming_neighbors.pkl
│       └── feature_names.json
├── scripts/34_check_runtime.py
└── runtime_manifest.json
```

processed 可以包含其他已发文件。常见放错路径是 `processed/processed/metadata.json`，正确路径应当是 `data/processed/metadata.json`。

如果合并到已收到的源码，请同时覆盖本包的 src、config、app.py 和启动脚本，保证代码与模型版本一致。推荐直接使用本包中的运行目录，避免加载旧的缓存和配置。

## 2 安装与启动

推荐 Python 3.11，Windows PowerShell 在 `web3-aml` 目录执行：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_runtime.ps1
.\.venv\Scripts\python.exe scripts/34_check_runtime.py
powershell -ExecutionPolicy Bypass -File .\run_demo.ps1
```

然后打开 `http://localhost:8501`。第一次自检要读取全量地址与图，请等待完成。若提示缺少文件或哈希不匹配，按输出检查文件位置与版本。

其他系统也可手动安装：

```bash
python3.11 -m venv .venv
# 激活虚拟环境后
python -m pip install -r requirements-runtime.txt
python scripts/34_check_runtime.py
python -m streamlit run app.py
```

前端运行使用 `requirements-runtime.txt`。旧的 `setup.ps1` 面向训练，会额外安装 PyTorch、PyG 和采样库。本包当前运行路线不需要这些训练依赖；保留的历史模型指标只用于读取展示。

如需自动检查全部界面：`python scripts/34_check_runtime.py --ui`。该自检强制使用模板报告，不调用付费接口。

## 3 三个模块怎么连通

目前前端是 Streamlit，后端能力通过 Python 服务调用；当前工程没有单独的 HTTP API 服务。

```python
from src.inference.analysis_service import AnalysisService

service = AnalysisService()  # 每个服务进程初始化一次，复用图和风险表
address = service.predictor.resolve("输入地址或节点 ID")
analysis = service.analyze(address)
trace = service.trace(address)
evidence = service.evidence(analysis, trace)
report = service.report(evidence)
```

修改现有 Streamlit 页面时，页面位于 `src/ui`；使用 `src/ui/runtime.py` 中的 `get_service()` 与 `get_analysis()` 复用缓存。

若另写 Vue/React 前端，需要在 Python 服务外包装 HTTP 接口。浏览器不能直接导入 AnalysisService 或加载 pickle 模型。建议接口职责如下，以下为待封装约定，当前未实现：

| 建议接口 | Python 能力 | 返回重点 |
|---|---|---|
| GET /api/demo-cases | 读取 artifacts/demo_cases.json | 已知高风险、低风险、未知高风险示例 |
| GET /api/addresses/{id}/risk | service.analyze(id) | risk、scoring_analysis、behavior_evidence、graph_evidence |
| POST /api/trace | service.trace(id, overrides) | top_paths、subgraph、statistics、search_budget |
| POST /api/report | 服务端以同一地址生成 analysis、trace、evidence，再调用 service.report | markdown、source、audit、statements、fact_catalog |

模型只对当前数据集中已有的 822942 个地址提供查询；不存在的地址应提示“数据集未收录”。风险分、关系路径与报告应使用同一个地址和版本。

当前主模型为单个联合 LightGBM，输入行为画像、方向邻域偏离、有向结构角色。不要按早期 README 中的神经网络双线路说明修改当前输入输出。

## 4 artifacts 为什么原来有约 21 GB

artifacts 保存训练和运行产生的文件，不是一个单独模型：

| 内容 | 用途 | 前端是否需要 |
|---|---|---|
| experiments 下的大量 cache、各轮候选结果 | 多轮研究实验、时间窗口特征和消融缓存 | 大部分不需要 |
| experiments 下当前模型文件、validation、test、selection | 当前模型解释、版本校验和评估 | 需要，已精确挑选 |
| evidence_scoring/features.npy | 全部地址的 171 维联合特征，供单地址 TreeSHAP 解释 | 需要 |
| risk_scores | 全量预计算风险和图统计 | 需要 |
| tracing/anchor_index | 风险锚点可达索引，支持低分连接和长链模式 | 需要 |
| metrics、少量比较表 | 总览与模型评估页面 | 需要 |
| reports、traces 历史记录 | 既有报告与追踪缓存 | 无需随包，新查询会生成 |
| investigation | 旧模型的历史调查增强层 | 当前主模型不用 |

所以不能直接删除整个 experiments：当前主模型元数据还引用其中几个文件。本包保留原来的相对路径、模型和版本哈希，去掉了批量实验缓存。

`runtime_manifest.json` 列出补充包文件及已有 processed 必需文件的 SHA-256，自检可检查传输是否缺失或版本不一致。

## 5 大模型和来源定位

不配置密钥即可跑完整的风险评分、追踪、结构化证据与模板报告。若使用真实大模型，复制 `.env.example` 为 `.env`，由使用者在自己电脑填写密钥及账号支持的模型名。API 密钥保留在 Python 服务端；不要放进前端 JavaScript 或发进代码仓库。

本次补充包不携带原始 CSV。报告仍可定位 Evidence 字段、特征归因和路径段；原始 CSV 行号定位在缺少原文件时自动停用，不伪造原始来源。若之后需要演示 CSV 物理行号定位，需要另行提供匹配的原始 CSV 和来源索引。

模型训练、实验复现仍应使用完整原工程。本包用于前端开发、当前全量数据查询与联调。
