# 模块一、模块二相关文献核实

核实日期：2026-10-13。范围：8 篇核心原论文；10 个精确检索 query，随后直接打开官方页面、读取 Crossref DOI 元数据。使用 academic-search 技能；本任务为主任务已分派的独立文献核实子任务。未查询引用数、未下载 PDF，未宣称全文复现。

本地依据：`web3-aml/docs/MODULE_01_ADDRESS_RISK_SCORING.md`、`MODULE_02_RELATION_TRACING.md`、`RISK_SCORING_REDESIGN.md`。以下“本项目实现”据这些实现记录归纳，本次未重新审计源码或重跑实验。

## 一、结构化书目简表

| 编号 | 原论文标题 | 作者 | 年份、正式发表位置 | DOI / 官方来源 | 本次阅读层级 |
|---|---|---|---|---|---|
| R1 | Demystifying Fraudulent Transactions and Illicit Nodes in the Bitcoin Network for Financial Forensics | Youssef Elmougy; Ling Liu | 2023，29th ACM SIGKDD，3979–3990 | DOI [10.1145/3580305.3599803](https://doi.org/10.1145/3580305.3599803)；[arXiv 2306.06108](https://arxiv.org/abs/2306.06108)；[Crossref](https://api.crossref.org/works/10.1145/3580305.3599803) | 官方摘要与 DOI 元数据 |
| R2 | Inductive Representation Learning on Large Graphs | Will Hamilton（arXiv 作 William L. Hamilton）; Zhitao Ying; Jure Leskovec | 2017，Advances in Neural Information Processing Systems 30 | [官方论文页](https://proceedings.neurips.cc/paper/2017/hash/5dd9db5e033da9c6fb5ba83c7a7ebea9-Abstract.html)；arXiv 1706.02216；本次未核得会议 DOI，不补造 | 官方摘要与作者、venue |
| R3 | LightGBM: A Highly Efficient Gradient Boosting Decision Tree | Guolin Ke; Qi Meng; Thomas Finley; Taifeng Wang; Wei Chen; Weidong Ma; Qiwei Ye; Tie-Yan Liu | 2017，Advances in Neural Information Processing Systems 30 | [官方论文页](https://proceedings.neurips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)；本次未核得会议 DOI，不补造 | 官方摘要与作者、venue |
| R4 | From local explanations to global understanding with explainable AI for trees | Scott M. Lundberg; Gabriel Erion; Hugh Chen; Alex DeGrave; Jordan M. Prutkin; Bala Nair; Ronit Katz; Jonathan Himmelfarb; Nisha Bansal; Su-In Lee | 2020，Nature Machine Intelligence 2，56–67 | DOI [10.1038/s42256-019-0138-9](https://doi.org/10.1038/s42256-019-0138-9)；[出版社页面](https://www.nature.com/articles/s42256-019-0138-9) | 出版社摘要、作者、出版日期及代码说明 |
| R5 | Edge Directionality Improves Learning on Heterophilic Graphs | Emanuele Rossi; Bertrand Charpentier; Francesco Di Giovanni; Fabrizio Frasca; Stephan Günnemann; Michael M. Bronstein | 2024，Proceedings of the Second Learning on Graphs Conference，PMLR 231，25:1–25:27；会议举办于 2023 | [正式 PMLR 页](https://proceedings.mlr.press/v231/rossi24a.html)；[卷页](https://proceedings.mlr.press/v231/)；arXiv 2305.10498 | 官方摘要与 BibTeX |
| R6 | TRacer: Scalable Graph-Based Transaction Tracing for Account-Based Blockchain Trading Systems | Zhiying Wu; Jieli Liu; Jiajing Wu; Zibin Zheng; Ting Chen | 2023，IEEE Transactions on Information Forensics and Security 18，2609–2621 | DOI [10.1109/TIFS.2023.3266162](https://doi.org/10.1109/TIFS.2023.3266162)；[Crossref](https://api.crossref.org/works/10.1109/TIFS.2023.3266162)；[arXiv HTML](https://arxiv.org/html/2201.05757) | 正式版 DOI 元数据；早期预印本摘要、引言及方法定位段落 |
| R7 | The use of MMR, diversity-based reranking for reordering documents and producing summaries | Jaime Carbonell; Jade Goldstein | 1998，21st ACM SIGIR，335–336 | DOI [10.1145/290941.291025](https://doi.org/10.1145/290941.291025) | ACM 元数据；页面无摘要，本次没有阅读全文 |
| R8 | Cost-effective outbreak detection in networks | Jure Leskovec; Andreas Krause; Carlos Guestrin; Christos Faloutsos; Jeanne VanBriesen; Natalie Glance | 2007，13th ACM SIGKDD，420–429 | DOI [10.1145/1281192.1281239](https://doi.org/10.1145/1281192.1281239)；[Crossref](https://api.crossref.org/works/10.1145/1281192.1281239)；[作者公开论文入口](https://cs.stanford.edu/people/jure/pubs/detect-techRept.pdf) | DOI 元数据、作者原文检索摘要；没有阅读全文 |

所有条目 `citation_count=null`、`download_status=not_requested`。没有开展 OA 全文可得性审计，统一 `full_text_status=unknown`；这不表示没有开放版本。表中提供的原文入口不等于本次已下载或全文读完。

## 二、方法关联、真实适配与限制

| 文献 | 原工作方法 / 可支撑的背景 | 当前项目真正使用的部分 | 不能声称的内容 |
|---|---|---|---|
| R1 Elliptic++ | 从交易扩展到地址等多种图视图，支持非法交易与非法地址识别 | 使用 Actors 地址特征、标签及 AddrAddr 有向关系；unknown 不入监督损失 | 不复现所有图任务；不能把地址关系链等同于逐笔金额流；摘要中的 56 个字段、1.27M temporal interactions 与当前处理后的 55 个数值字段、2,784,344 条地址边不是同一统计口径 |
| R2 GraphSAGE | 采样并聚合局部邻居特征，学习可用于新节点的表征函数 | 历史双线路方案中的两层 GraphSAGE，以及保存的对照实验 | 当前部署主模型已非 GraphSAGE；原论文引用、社交和蛋白图实验不能证明本项目的 AML 泛化、实时早期检测或优越性 |
| R3 LightGBM | 高效梯度提升树框架；论文提出 GOSS 和 EFB | 当前联合树读取 171 维；另有三个单类诊断树，诊断分不参与 Gate 或投票 | 使用 LightGBM 包不等于当前配置启用了 GOSS；原论文加速比不可移植到本系统；算法本体不属本项目原创 |
| R4 TreeSHAP | 树模型的高效 Shapley 归因、交互解释与局部解释聚合 | Native TreeSHAP 对实际联合树作 margin 分解，再按行为、方向偏离和结构三组汇总；额外展示类别权重校正及温度变换 | SHAP 不证明犯罪因果；原 margin 加法分解不意味着校准概率可由各特征概率直接相加；不能用诊断树归因代替联合树归因 |
| R5 Dir-GNN | 入边、出边分别聚合，强调异配图中保留方向的价值 | 分别计算上下游均值、标准差与标准化偏离，配合 18 项有向结构特征，再用联合树学习 | 不是完整 Dir-GNN；标准化偏离公式并非该论文所给算法；不继承其表达能力证明或基准优势 |
| R6 TRacer | 将账户型链交易追踪转为图搜索，利用 PPR 类相关性及局部图结果；包含金额、时间和多关系语义 | 早期有向无权 local push 对照借鉴其思路；当前默认关闭 PPR，改为风险锚点逆向可达索引与受预算限制的真实连接见证 | 当前不是 TRacer 复现；Bitcoin Actors 静态关系图无法直接复现账户链金额、时间、Swap 语义；锚点索引不是 TRacer 原算法 |
| R7 MMR | 在候选相关性与结果冗余之间做重排权衡 | 使用路径分、新增风险加权覆盖和最大有向边 Jaccard 重叠选择展示路径，并折叠严格前缀 | 原任务是文档检索/摘要，本项目相似度与效用自行定义；不宣称复现原实验，或由 MMR 自动获得全局最优保证 |
| R8 预算覆盖 | 在有限资源下选网络监测点，重视新增覆盖及效用收益；原工作包含次模优化背景 | 借鉴边际新增证据思想，衡量路径带来的唯一节点、边与预测风险覆盖 | 当前是受 Beam、路径可达性和多重约束影响的组合启发式，未证明次模性；不得引用原近似界作为本系统理论保证 |

### 锚点可达性的引用边界

当前“沿 incoming 边从风险目标做多源逆向 BFS，保存距离和 next-hop”属于标准图可达性/最短路机制的任务适配。本次核实的文献中，没有一篇可被准确称为这一完整项目机制的原论文。R6 支撑的是“追踪作为图搜索与局部审查”的背景，R7/R8 支撑的是冗余控制与覆盖选择的动机。不要将“风险锚点”与模型无关解释论文 Anchors 混淆；也不要将逆向 BFS 本身包装成新的可达算法。

## 三、可用于中文相关工作的段落

**[R1 数据与任务背景]** Elmougy 和 Liu 提出的 Elliptic++ 将比特币反欺诈分析由交易节点扩展至地址等多种关系视图，为非法地址识别提供公开数据基础。本系统选取 Actors 特征、标签及地址关系构建分析闭环，未复现原论文全部图任务。由于当前边表缺少完整逐笔金额和时间，输出限定为地址关系线索，不能解释成精确资金污染归属。[来源](https://arxiv.org/abs/2306.06108)

**[R2 图表征对照]** Hamilton 等提出 GraphSAGE，通过采样和聚合局部邻居特征学习节点表示函数，使表征可迁移到未见节点。项目历史方案以两层 GraphSAGE 提供图分支，并保留其对照结果；当前部署则采用离线有向特征与联合树。原论文在其他领域的归纳学习结果并不证明本系统具备实时链上泛化能力，比较结论仍需依据本地统一评估协议。[来源](https://proceedings.neurips.cc/paper/2017/hash/5dd9db5e033da9c6fb5ba83c7a7ebea9-Abstract.html)

**[R3 轻量联合评分]** Ke 等提出 LightGBM，以梯度提升树及高效训练技术处理大规模特征数据。本系统将行为画像、方向邻域偏离和有向结构共 171 维特征输入联合 LightGBM，再执行类别权重校正与温度校准。三个单类诊断分仅辅助展示，不参与概率投票。项目贡献在图特征适配及证据闭环，不能将树算法或原论文的加速比例表述为本项目创新与实测结果。[来源](https://proceedings.neurips.cc/paper_files/paper/2017/hash/6449f44a102fde848669bdd9eb6b76fa-Abstract.html)

**[R4 评分可解释性]** Lundberg 等研究树模型的高效 Shapley 归因，并通过局部解释理解模型整体行为。本系统对实际联合树计算 TreeSHAP，将特征贡献归入行为、偏离和结构三组，核对其与原始 margin 的加法关系，再展示后续校准。该方法解释模型怎样形成预测，不构成现实因果或违法证据；校准概率也不能直接按原始贡献逐项相加。[来源](https://www.nature.com/articles/s42256-019-0138-9)

**[R5 方向邻域对比]** Rossi 等的 Dir-GNN 分别处理入边和出边，说明边方向在异配图学习中具有价值。受此启发，本系统保留上下游语境，以本地址相对邻域均值和标准差的偏离描述差异，并加入有向结构统计。当前实现使用联合树而非完整 Dir-GNN；其标准化偏离公式属于项目适配，效果应由方向消融验证，不能继承原论文的表达能力或性能结论。[来源](https://proceedings.mlr.press/v231/rossi24a.html)

**[R6 风险引导追踪]** Wu 等提出 TRacer，将账户型区块链交易追踪建模为图搜索，利用个性化 PageRank 类相关性定位可审查的局部结果。本项目参考这一思路开展无权传播对照，最终默认采用预测风险锚点的可达见证和预算搜索。该适配未复现原方法的金额、时间及代币语义，因此返回的是真实有向关联路径，不能宣称还原资金流或继承 TRacer 的理论保证。[来源](https://arxiv.org/html/2201.05757)

**[R7 路径冗余控制]** Carbonell 和 Goldstein 的 MMR 为相关性与结果冗余之间的重排权衡提供经典思路。本系统将选择对象由文档改为可疑关系路径，在路径分之外考虑新增证据，并以有向边集合的重叠衡量冗余，折叠严格前缀。该机制旨在减少有限展示预算中的重复线索，属于任务适配；它不保证全局最优，也不能把相似路径的减少解释为发现更多真实洗钱事件。[来源](https://doi.org/10.1145/290941.291025)

**[R8 有限预算下的覆盖]** Leskovec 等研究网络中的低成本暴发检测，在监测资源有限时根据新增效用选择节点，为覆盖导向的决策提供方法背景。本项目借鉴边际覆盖思想，优先保留增加唯一节点和有向边证据的路径，但同时受到 Beam、深度及真实连接约束。因当前目标与约束未经次模性证明，报告仅讨论实测覆盖和开销，不套用原论文的近似保证或全局最优结论。[来源](https://doi.org/10.1145/1281192.1281239)

## 四、应在比赛报告中明确的核实结论

1. **当前主模型与初始 AGENTS 设计不同。** 当前实现文档记载的是“51 维行为＋102 维方向偏离＋18 维结构→联合 LightGBM”，而非正在部署的“双神经分支＋Gate”。GraphSAGE、MLP、Gate 应放在历史设计或对照中。
2. **Dir-GNN 年份区分会议与论文集。** 会议于 2023 年举办；正式 PMLR BibTeX 年份是 2024。推荐写“LoG 2023，PMLR 2024”，不要标 NeurIPS。
3. **TRacer 两个版本不可混用作者。** 正式 TIFS 2023 版有 5 位作者，含 Ting Chen；所读 arXiv v3（2022）有 4 位作者。HTML 头部残留 ACM conference、占位 DOI 等模板文本，不是正式出版证据；以 Crossref 正式 DOI 元数据为准。
4. **Elliptic++ 数据口径须自行说明。** 摘要的 56 features、1.27M temporal interactions 与本地 55 数值字段、地址边数量不同，不能拿两者直接证明数据缺失或实现错误。报告的运行规模应来自实际数据检查结果。
5. **默认锚点阈值是 30。** 它包含 MEDIUM 及以上模型预测节点，不能将所有“风险锚点”统一写成 HIGH，也不能将低于阈值节点称为已知正常。
6. **没有论文直接证明完整新组合。** 标准化邻域偏离、逆向 BFS 见证、预算 Beam 和覆盖重排的集成可作为项目设计贡献，但不能写成学术首创、完整复现 Dir-GNN/TRacer 或拥有未经证明的理论界。
7. **效果结论仅以本项目实际对照为准。** 实现文档承认宽松搜索/BFS 在部分覆盖指标更高，当前方案不全面胜出；亦不能把论文作者各自基准的性能转写为本系统结果。
8. 本次精读范围有限：R1–R5 主要是摘要和元数据，R6 额外读取预印本部分正文，R7/R8 未阅读全文。以上段落为相关工作概要与适配边界，不是逐篇复现报告。

