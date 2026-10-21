# 项目目录导航

仓库根目录提供项目展示，`web3-aml/` 是运行目录。运行入口为 `run_web.py`，网页地址为 **http://127.0.0.1:8000/**。

| 目录 / 文件 | 作用 |
|---|---|
| `frontend/` | 宣传首页、四模块工作台、页面状态和关系网络交互 |
| `api/` | FastAPI 接口、分析快照、报告适配与下载 |
| `src/data/` | 数据清洗、ID 映射和图构建 |
| `src/model/` | 方向邻域偏离、有向结构等特征构造；比较模型 |
| `src/train/` | 训练、实验、消融与评估 |
| `src/inference/` | 当前模型全量预计算、风险查询、TreeSHAP 分析服务 |
| `src/tracing/` | 风险锚点索引、预算搜索、连接见证、覆盖选路 |
| `src/report/` | Evidence、事实目录、声明协议、核验、修复、来源与审计 |
| `src/ui/`、`app.py` | Streamlit 辅助分析与模型评估界面 |
| `config/` | 数据、模型、追踪与报告配置 |
| `data/processed/` | 地址映射、节点特征、标签、图邻接与划分 |
| `artifacts/evidence_scoring/` | 171 维联合特征、模型元数据和全量风险分 |
| `artifacts/risk_scores/` | 在线风险查询表与图统计 |
| `artifacts/experiments/` | 当前模型文件、验证结果、对照与消融表 |
| `artifacts/tracing/` | 风险锚点可达索引和长链案例 |
| `artifacts/metrics/` | 评估数据及功能验收记录 |
| `runtime-data/` | 19 个大型数据分卷及还原清单 |
| `runtime_manifest.json` | 当前运行文件的大小、哈希及数据版本 |
| `scripts/` | 数据准备、训练、预计算、实验、自检与浏览器回归 |
| `tests/` | 算法、数据、证据协议与网页接口测试 |
| `docs/screenshots/` | 当前网页实际运行截图 |
| `requirements-web.txt` | 网页服务与当前模型推理依赖 |
| `requirements.txt`、`setup.ps1` | 训练与比较模型环境 |

## 评审阅读顺序

1. [系统说明](../README.md)：整体能力与代表性结果。
2. [比赛演示](DEMO_GUIDE.md)：与新版前端一致的操作顺序。
3. [创新对应](THREE_MODULE_INNOVATION_ALIGNMENT.md)：痛点、设计与验证。
4. [模块一](MODULE_01_ADDRESS_RISK_SCORING.md)、[模块二](MODULE_02_RELATION_TRACING.md)、[模块三](MODULE_03_EXPLAINABLE_REPORT.md)：实现原理和接口。
5. [测试说明](EVALUATION_PROTOCOL.md)：样本、指标和复现入口。

## 运行结果保存

用户生成的路径、报告和编号快照分别写入 `artifacts/traces/`、`artifacts/reports/`、`artifacts/web_runs/`。这些目录按实际操作自动生成。网页截图与测试临时输出也写入 `artifacts/`，不作为固定运行数据提交。
