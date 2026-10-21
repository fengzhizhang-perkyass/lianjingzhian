# 测试方案与评估结果

本项目从地址评分、关系检索、报告核验和网页联动四个层面验证完整研判流程。

## 数据与环境

采用 Elliptic++ Actors 数据。清洗后包含 822,942 个地址、2,784,344 条有向关系；已知标签地址 265,354 个，未知标签 557,588 个。已知标签按时间划分为 170,404 / 38,514 / 56,436 个训练、验证、测试地址，测试集中非法标签地址 2,548 个。未知标签不进入监督损失。

已验证 CPU 环境为 Ryzen 7 5800H、Windows 64 位、Python 3.11.2。当前网页建议 Python 3.11 和 16 GB 内存，读取已训练模型、全量风险表与图索引完成在线演示。

## 模块一：已知标签测试集

| 评价项 | 结果 |
|---|---:|
| Top-100 命中 | 100/100 |
| Top-500 命中 | 488/500（97.60%） |
| Top-1% 命中 | 545/565（96.46%） |
| Precision | 86.65% |
| ROC-AUC | 0.8804 |

Top-K 表示按综合分排序后，前 K 个已知标签测试候选中的非法标签命中数量。模型与校准在训练、验证流程中确定；测试使用公开数据快照。原始完整指标保存在当前模型的 `test.json`。

## 模块二：固定起点评估与长链案例

在同一组 72 个评估起点上比较原 Beam 与风险锚点引导方法。累计预测锚点从 5 增至 23，唯一关系边从 5 增至 59；分别衡量风险锚点发现和关系覆盖。

另选三个可展示案例进行长链核查：每例均为 32 跳、33 个不同地址，全部路径边与原始有向图逐一核对。案例结果保存在 `artifacts/tracing/long_path_cases.json`。快速模式和长链模式分别验证预算约束、环路检查、参数边界及路径导出。

## 模块三：受控故障与正确样例

构造 120 个类型、主体或事实内容错误的声明，核验协议全部拦截；12 个正确协议用例通过。120 次模拟局部修复保留了 1,200 条已通过声明。另以真实 Evidence 和真实大模型报告验证声明渲染、事实覆盖、来源导航及审计 ZIP。

人为注入测试评估错误识别能力，模拟修复测试评估局部更新行为。网页实测与故障测试分开记录，便于核对。

## 网页与工程测试

检查宣传页、四模块路由、队列分页、地址切换、评分归因、可拖动网络、32 跳追踪、报告生成、证据导航及全部下载。覆盖桌面、平板和手机宽度，并检查返回恢复、晚到请求、断线重连和空结果。

```bash
python scripts/prepare_runtime_data.py
python scripts/34_check_runtime.py
python -m pip install pytest httpx
python -m pytest tests/test_web_api.py tests/test_web_reporting.py tests/test_audited_reporting.py tests/test_runtime_data.py -q
```

浏览器检查为 `scripts/check_web_ui.cjs`、`scripts/check_network_ui.cjs`，具体环境配置见 [网页说明](../README_WEB.md)。核心自检使用模板报告，无需外部 LLM。运行清单对数据、模型及所需文件进行大小与 SHA-256 核对。

## 主要结果位置

| 内容 | 路径 |
|---|---|
| 当前模型测试结果 | `artifacts/experiments/evidence_tree_v1/final/seed_42/standardized_deviation_fusion__compact/test.json` |
| 对照与消融 | `artifacts/experiments/evidence_tree_v1/final_comparison.csv`、`evidence_tree_v1_ablation/comparison.csv` |
| 演示地址 | `artifacts/demo_cases.json` |
| 长链案例 | `artifacts/tracing/long_path_cases.json` |
| 功能验收 | `artifacts/metrics/` |
| 当前网页截图 | `docs/screenshots/` |
