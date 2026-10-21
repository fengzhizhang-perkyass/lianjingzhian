# 链境智安

**基于多维证据融合的链上反洗钱与可解释研判系统**

链境智安面向链上风险研判，把地址识别、关系追踪和证据报告串成一条可操作的分析流程。系统在 **822,942 个地址、2,784,344 条有向关系**上提供查询，通过轻量联合模型发现重点地址，沿关系网络展开追踪，再生成可定位依据的分析报告。

![链境智安宣传首页](web3-aml/docs/screenshots/home.png)

## 从哪里开始

| 评审关注 | 阅读入口 |
|---|---|
| 如何打开系统 | [下载与启动](web3-aml/GITHUB_运行说明.md) |
| 如何演示完整流程 | [比赛演示指南](web3-aml/docs/DEMO_GUIDE.md) |
| 三个模块如何协同 | [系统说明与实验结果](web3-aml/README.md) |
| 创新与研究痛点 | [三个模块的创新对应](web3-aml/docs/THREE_MODULE_INNOVATION_ALIGNMENT.md) |
| 源码如何组织 | [项目目录导航](web3-aml/docs/DIRECTORY_GUIDE.md) |

## 三项核心能力

1. **多维证据融合风险评分**：行为画像、上下游偏离、有向结构角色共 171 维特征，由 LightGBM 联合评分；TreeSHAP 展开每类证据的实际贡献。
2. **风险锚点引导的关系追踪**：结合可达见证、搜索预算和覆盖选路，保留连接关键对象的关系片段；快速筛查与最长 32 跳长链核查一键切换。
3. **可核验的解释报告**：结构化事实约束报告声明，逐条核验类型、主体与单位，支持证据定位、局部修复和审计材料下载。

## 页面与演示

宣传首页点击“开始分析”进入独立工作台，依次操作 **调查优先队列 → 地址风险分析 → 关系链追踪 → AI分析报告**。队列负责发现重点，后三个页面分别承载三个核心模块；地址、路径与报告在同一分析上下文中联动。

![新版关系链追踪工作台](web3-aml/docs/screenshots/tracing.png)

页面实拍：[调查优先队列](web3-aml/docs/screenshots/queue.png) · [地址风险分析](web3-aml/docs/screenshots/risk.png) · [AI分析报告](web3-aml/docs/screenshots/report.png)

## 代表性结果

| 测试项目 | 结果 |
|---|---:|
| 已知标签测试集 Top-100 命中 | 100/100 |
| 已知标签测试集 Top-500 命中 | 488/500（97.60%） |
| 地址评分 ROC-AUC | 0.8804 |
| 72 个评估起点累计预测锚点，较原 Beam | 5 → 23（4.6 倍） |
| 同组评估的唯一关系边 | 5 → 59（11.8 倍） |
| 精选长链展示 | 3 个案例均达 32 跳，逐边核对 |
| 人为故障测试 | 120 个错误声明全部拦截 |

实验配置、样本范围及数据来源见 [测试说明](web3-aml/docs/EVALUATION_PROTOCOL.md)。

## 快速启动

安装 Git LFS 和 Python 3.11 后：

```bash
git lfs install
git clone https://github.com/fengzhizhang-perkyass/lianjingzhian.git
cd lianjingzhian
git lfs pull
cd web3-aml
python -m venv .venv
```

Windows PowerShell：

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-web.txt
.\.venv\Scripts\python.exe run_web.py
```

macOS / Linux：

```bash
.venv/bin/python -m pip install -r requirements-web.txt
.venv/bin/python run_web.py
```

打开 **http://127.0.0.1:8000/**。首次启动自动还原分卷数据；运行模型、风险表和索引已随仓库提供，演示阶段直接查询。接入大模型的方法见 [运行说明](web3-aml/GITHUB_运行说明.md#大模型报告)。

## 项目结构

```text
lianjingzhian/
├── README.md               项目入口与展示
└── web3-aml/
    ├── frontend/           宣传首页与四模块工作台
    ├── api/                FastAPI 接口与分析结果管理
    ├── src/                评分、追踪、报告及训练源码
    ├── config/             算法与服务配置
    ├── data/processed/     地址映射和图数据
    ├── artifacts/          已训练模型、风险表、索引与测试结果
    ├── runtime-data/       大型运行数据分卷
    ├── scripts/            数据准备、实验与自检
    ├── tests/              算法及接口测试
    └── docs/               设计、演示、测试说明与页面截图
```

数据采用 [Elliptic++ Actors](https://github.com/git-disl/EllipticPlusPlus)；前端图形使用 Plotly.js 与 Cytoscape.js，组件版权与许可保留于分发文件中。
