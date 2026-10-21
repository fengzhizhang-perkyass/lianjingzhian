# Web3 AML 风险分析报告

## 1. 地址风险概述

- 地址 1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS 的综合模型风险为 72.76 / 100，等级 HIGH。这是模型预测。 [E01](#evidence-e01)
- 行为画像单组诊断分为 15.93 / 100，用于解释证据职责，综合评分由联合模型产生。 [E02](#evidence-e02)
- 方向邻域偏离单组诊断分为 7.64 / 100，用于解释证据职责，综合评分由联合模型产生。 [E03](#evidence-e03)
- 有向结构角色单组诊断分为 32.40 / 100，用于解释证据职责，综合评分由联合模型产生。 [E04](#evidence-e04)

## 2. 行为风险证据

- fees\_as\_share\_max：原始值 0.0003，联合模型 TreeSHAP贡献 0.7187；贡献解释模型原始输出。 [E05](#evidence-e05)
- BTC 交易总量：原始值 0.7800，联合模型 TreeSHAP贡献 0.2445；贡献解释模型原始输出。 [E06](#evidence-e06)
- 手续费最小值：原始值 0.0003，联合模型 TreeSHAP贡献 0.1695；贡献解释模型原始输出。 [E07](#evidence-e07)
- fees\_as\_share\_total：原始值 0.0005，联合模型 TreeSHAP贡献 0.1595；贡献解释模型原始输出。 [E08](#evidence-e08)
- transacted\_w\_address\_total：原始值 2.0000，联合模型 TreeSHAP贡献 0.0789；贡献解释模型原始输出。 [E09](#evidence-e09)

## 3. 图结构风险证据

- 下游标准化偏离 · fees\_as\_share\_total：模型输入值 -3.1424，联合模型 TreeSHAP贡献 0.7435；贡献解释模型原始输出。 [E10](#evidence-e10)
- 上游标准化偏离 · 手续费总额：模型输入值 0.0441，联合模型 TreeSHAP贡献 0.5490；贡献解释模型原始输出。 [E11](#evidence-e11)
- 下游标准化偏离 · BTC 接收总量：模型输入值 -1.8533，联合模型 TreeSHAP贡献 0.5336；贡献解释模型原始输出。 [E12](#evidence-e12)
- 下游标准化偏离 · BTC 交易量均值：模型输入值 0.5312，联合模型 TreeSHAP贡献 0.4662；贡献解释模型原始输出。 [E13](#evidence-e13)
- 上游标准化偏离 · 手续费最小值：模型输入值 -0.0075，联合模型 TreeSHAP贡献 0.3105；贡献解释模型原始输出。 [E14](#evidence-e14)
- mean\_upstream\_log\_out\_degree：模型输入值 1.0986，联合模型 TreeSHAP贡献 0.6478；贡献解释模型原始输出。 [E15](#evidence-e15)
- 出度对数：模型输入值 0.6931，联合模型 TreeSHAP贡献 0.2874；贡献解释模型原始输出。 [E16](#evidence-e16)
- 下游平均连接度对数：模型输入值 2.3979，联合模型 TreeSHAP贡献 0.0875；贡献解释模型原始输出。 [E17](#evidence-e17)
- mean\_downstream\_log\_out\_degree：模型输入值 1.7918，联合模型 TreeSHAP贡献 0.0504；贡献解释模型原始输出。 [E18](#evidence-e18)
- log\_forward\_two\_step\_walks：模型输入值 1.7918，联合模型 TreeSHAP贡献 -0.0490；贡献解释模型原始输出。 [E19](#evidence-e19)
- 出度为 1，描述图结构关联。 [E20](#evidence-e20)
- 入度为 1，描述图结构关联。 [E21](#evidence-e21)
- 一跳邻居平均风险为 21.77，描述图结构关联。 [E22](#evidence-e22)
- 一跳高风险邻居比例为 0.0000，描述图结构关联。 [E23](#evidence-e23)

## 4. 可疑关联路径

- 关系路径 1：1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS → 15C4iGjiERw2ZwaTrhsRmsgSFBydKjPoQd → 15QVSV49vfyFUxvsXS6ajV9GNStQaJa2Kj → 15oPbAGPBxWEytCbc9X7e4yPkqLADhenrR，共 3 跳、4 个不同地址；搜索排序分 0.4450。路径表示有向关联，排序分用于候选排序。 路径来源编号 trace\_95a5ff9637e1c536a616eeb3。 [E24](#evidence-e24)
- 关系路径 2：1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS → 15C4iGjiERw2ZwaTrhsRmsgSFBydKjPoQd → 14rFnEeajgrkUGN6BAcxQnTL1GENjgXR96 → 1J4zJzYPKJmBiRJfEFcQNjNtsjfhbnpNnM → 1FHp5TXDu9goiGFzcHTwomedWxkjJyjnLn，共 4 跳、5 个不同地址；搜索排序分 0.3791。路径表示有向关联，排序分用于候选排序。 路径来源编号 trace\_9fe617a587ac57ad1bde026a。 [E25](#evidence-e25)
- 低分连接从 14rFnEeajgrkUGN6BAcxQnTL1GENjgXR96 开始，共 1 个连续低分节点；存在到 1J4zJzYPKJmBiRJfEFcQNjNtsjfhbnpNnM 的完整有向连接见证。 首个低分节点风险 16.10，锚点原始风险 61.02；节点原始评分保持不变。 [E26](#evidence-e26)
- 关系路径 3：1EVmeeBuxj5jzUitfAjAiSYZwM6A6owyFS → 15C4iGjiERw2ZwaTrhsRmsgSFBydKjPoQd → 182tnCCD9p7PmpH74PmCZqp9t6nKHt3pkk，共 2 跳、3 个不同地址；搜索排序分 0.3638。路径表示有向关联，排序分用于候选排序。 路径来源编号 trace\_87fa363c32bf78c15235fd5a。 [E27](#evidence-e27)
- 在线关系检查上限 2000，实际检查 11；停止原因 MAX\_DEPTH\_REACHED。这是搜索范围记录。 [E28](#evidence-e28)

## 5. 综合研判

- 建议结合模型评分、模型归因、图结构与关系路径进行人工复核。 [E29](#evidence-e29)

## 6. 风险提示与系统局限

- 地址风险是模型预测，不能作为犯罪认定或真实身份结论。 [E30](#evidence-e30)
- 路径表示地址有向关系，不能据此认定同一笔资金连续流动、交易金额或逐笔时间。 [E31](#evidence-e31)
- 搜索受深度与预算限制，未展示关系不代表该关系不存在。 [E32](#evidence-e32)
- 模型归因解释相应模型原始输出，贡献不具有因果含义；单组评分用于诊断。 [E33](#evidence-e33)
- 校准依赖已知标签验证集，不能保证未知标签地址的概率校准。 [E34](#evidence-e34)
- 公开数据可能缺少或包含未知标签；地址生命周期汇总特征不等同历史时点实时预测。 [E35](#evidence-e35)

## 证据定位索引

### evidence-e01

E01 · E_468f276343e68cf2 · `/risk_analysis/overall_score`、`/risk_analysis/risk_level`

### evidence-e02

E02 · E_abf54fcd7b0bef2f · `/scoring_analysis/route_scores/behavior`

### evidence-e03

E03 · E_ca0e028cdaffdc36 · `/scoring_analysis/route_scores/context`

### evidence-e04

E04 · E_7cac4288d5da10a2 · `/scoring_analysis/route_scores/structure`

### evidence-e05

E05 · E_c150fbf33bacc872 · `/scoring_analysis/evidence/behavior/0`

### evidence-e06

E06 · E_39f2d87e11ea3819 · `/scoring_analysis/evidence/behavior/1`

### evidence-e07

E07 · E_b99868876a7833e0 · `/scoring_analysis/evidence/behavior/2`

### evidence-e08

E08 · E_a8b6b1633ef67ec4 · `/scoring_analysis/evidence/behavior/3`

### evidence-e09

E09 · E_844e73073da62f25 · `/scoring_analysis/evidence/behavior/4`

### evidence-e10

E10 · E_2ea7a8eaee6d6e82 · `/scoring_analysis/evidence/context/0`

### evidence-e11

E11 · E_8cf73de924043500 · `/scoring_analysis/evidence/context/1`

### evidence-e12

E12 · E_823e02068bac372d · `/scoring_analysis/evidence/context/2`

### evidence-e13

E13 · E_9fb8ae518478e31f · `/scoring_analysis/evidence/context/3`

### evidence-e14

E14 · E_95aeffac8ef0b9be · `/scoring_analysis/evidence/context/4`

### evidence-e15

E15 · E_21e36d7be1a654a4 · `/scoring_analysis/evidence/structure/0`

### evidence-e16

E16 · E_62836f2fd00a4e09 · `/scoring_analysis/evidence/structure/1`

### evidence-e17

E17 · E_1deeaf518ed98454 · `/scoring_analysis/evidence/structure/2`

### evidence-e18

E18 · E_95a362054da98e29 · `/scoring_analysis/evidence/structure/3`

### evidence-e19

E19 · E_f4e35aa0174c2664 · `/scoring_analysis/evidence/structure/4`

### evidence-e20

E20 · E_342c79f4b8bdaed1 · `/graph_evidence/out_degree`

### evidence-e21

E21 · E_d17ef097255421bf · `/graph_evidence/in_degree`

### evidence-e22

E22 · E_8b5671d30bfe161d · `/graph_evidence/one_hop_avg_risk`

### evidence-e23

E23 · E_fa218eb0d41876f7 · `/graph_evidence/one_hop_high_risk_ratio`

### evidence-e24

E24 · E_22cea3fdbe661691 · `/trace_analysis/top_paths/0`

### evidence-e25

E25 · E_dd05824239657e4d · `/trace_analysis/top_paths/1`

### evidence-e26

E26 · E_a8fc39a49935d0ab · `/trace_analysis/top_paths/1/bridge_witnesses/0`、`/trace_analysis/top_paths/1/node_risks/1`、`/trace_analysis/top_paths/1/node_risks/2`、`/trace_analysis/top_paths/1/node_risks/3`

### evidence-e27

E27 · E_76b0eb67bfaea4c3 · `/trace_analysis/top_paths/2`

### evidence-e28

E28 · E_6416d0f7083c1fdb · `/trace_analysis/search_budget`

### evidence-e29

E29 · E_efe943ab71ca5966 · 系统边界规则：human_review

### evidence-e30

E30 · E_c7a95ea1498c18e6 · 系统边界规则：model_boundary

### evidence-e31

E31 · E_13821e79c8dc25e7 · 系统边界规则：relation_boundary

### evidence-e32

E32 · E_3778b68dcea22ed6 · 系统边界规则：search_boundary

### evidence-e33

E33 · E_418e2f27940b3dfc · 系统边界规则：attribution_boundary

### evidence-e34

E34 · E_88f3bb8b6cb07e96 · 系统边界规则：calibration_boundary

### evidence-e35

E35 · E_29df98b6bddcd3d4 · 系统边界规则：snapshot_boundary

