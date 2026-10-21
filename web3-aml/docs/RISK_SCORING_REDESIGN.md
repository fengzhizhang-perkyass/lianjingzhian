# 评分模型实现与复现

当前方案为“有向邻域对比证据融合”：51 维行为画像、102 维方向邻域偏离与 18 维结构角色，共 171 维输入联合 LightGBM。模块职责与流程见 [模块一设计](MODULE_01_ADDRESS_RISK_SCORING.md)。

## 实现思路

行为特征刻画地址自身，方向偏离分别比较上游与下游的特征分布，结构特征描述入度、出度、互惠及两步角色。联合树学习三类证据的交互关系，经类别权重校正和验证温度校准输出风险。TreeSHAP 在实际模型上计算贡献，并核对贡献与原始输出的加和。

当前网页展示模型名称为“LightGBM 联合风险模型”。单类模型提供诊断；核心风险由一个联合模型输出。

## 数据准备

官方数据：[EllipticPlusPlus](https://github.com/git-disl/EllipticPlusPlus)。原始输入为 `wallets_features.csv`、`wallets_classes.csv` 和 `AddrAddr_edgelist.csv`，列名适配在 `config/data.yaml`。

```bash
python scripts/00_download_data.py
python scripts/01_inspect_data.py
python scripts/02_preprocess.py
```

已提供运行数据时可直接使用网页。训练实验使用 `requirements.txt` 及 `setup.ps1` 配置相应环境。

## 实验与预计算

```bash
python scripts/16_experiment_roles.py
python scripts/17_experiment_graph_signals.py
python scripts/18_experiment_multievidence.py
python scripts/19_experiment_evidence_tree.py
python scripts/20_ablate_evidence_tree.py
python scripts/21_precompute_evidence_scores.py
python scripts/22_report_risk_redesign.py
python scripts/07_build_demo_cases.py
python scripts/08_validate_demo.py
```

脚本按依赖先生成角色、图信号与对应特征缓存，再执行多证据比较和联合树实验。运行前可通过 `--help` 查看阶段参数；实验设置集中在 `config/*experiments.yaml`，已发布模型与验证材料在 `artifacts/experiments/`。预计算会更新全量风险表，随后需按 [模块二](MODULE_02_RELATION_TRACING.md) 的配置部署匹配的锚点索引并重建演示案例。

完整风险表、特征缓存和模型元数据以数据指纹与源文件哈希绑定。在线服务通过 `AnalysisService` 加载当前模型，单地址查询无需重新训练。

## 技术来源与项目设计

- 数据与金融取证场景：Elmougy & Liu, KDD 2023，[论文](https://doi.org/10.1145/3580305.3599803)。
- 联合树学习：Ke et al., LightGBM, NeurIPS 2017，[论文](https://proceedings.neurips.cc/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)。
- 加性归因：Lundberg et al., Nature Machine Intelligence 2020，[论文](https://doi.org/10.1038/s42256-019-0138-9)。

本项目将方向差异证据、结构角色和实际联合归因整合到评分模块，并将其输出衔接风险锚点追踪与声明级核验报告。相关测试、样本与结果见 [测试说明](EVALUATION_PROTOCOL.md)。
