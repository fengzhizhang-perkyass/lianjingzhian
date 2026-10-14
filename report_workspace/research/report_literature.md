# 模块三相关工作与参考文献核实

核实日期：2026-10-13。采用 academic-search 技能，直接核对 ACL Anthology 与 NeurIPS 官方论文页的标题、作者、出版信息及摘要；未下载 PDF，未查询引用数。本记录面向竞赛报告相关工作章节，不构成这些方法的复现实验。项目适配依据为 `web3-aml/docs/MODULE_03_EXPLAINABLE_REPORT.md` 与 `web3-aml/docs/DEEPSEEK_CONNECTION.md`。

## 1. ALCE：带引用生成与引用支持评价

**书目信息 [M3-1]**：Tianyu Gao, Howard Yen, Jiatong Yu, Danqi Chen. **Enabling Large Language Models to Generate Text with Citations**. *Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (EMNLP 2023)*, 2023: 6465–6488. DOI: [10.18653/v1/2023.emnlp-main.398](https://doi.org/10.18653/v1/2023.emnlp-main.398)。[官方论文页](https://aclanthology.org/2023.emnlp-main.398/)。

**相关工作与区别（可直接引用）**：ALCE面向带引用的问答生成，联合考察流畅性、正确性与引用质量，强调回答应获得检索证据支持。本项目借鉴引用支持的评价思路，将引用对象限定为固定AML事实目录，核对声明类型、地址主体与单位，并定位到具体字段或路径段。这是面向审计场景的协议适配，不能据此宣称完成通用自然语言蕴含判断，也不能直接沿用ALCE的基准结果。

## 2. RARR：归因检查与保留原意的修订

**书目信息 [M3-2]**：Luyu Gao, Zhuyun Dai, Panupong Pasupat, Anthony Chen, Arun Tejasvi Chaganty, Yicheng Fan, Vincent Zhao, Ni Lao, Hongrae Lee, Da-Cheng Juan, Kelvin Guu. **RARR: Researching and Revising What Language Models Say, Using Language Models**. *Proceedings of the 61st Annual Meeting of the Association for Computational Linguistics (Volume 1: Long Papers) (ACL 2023)*, 2023: 16477–16508. DOI: [10.18653/v1/2023.acl-long.910](https://doi.org/10.18653/v1/2023.acl-long.910)。[官方论文页](https://aclanthology.org/2023.acl-long.910/)。

**相关工作与区别（可直接引用）**：RARR为既有生成文本查找外部支持，并修订缺乏依据的内容，同时尽量保留原文。本项目借鉴检查后修订与有效内容保留的思路，以封闭Evidence和规则错误反馈替代开放网页研究，只允许在失败位置进行至多一轮修复，之后局部模板回退并留存审计记录。该实现不允许修改源证据；模拟修复通过只能证明流程约束有效，不能代表真实模型的修复成功率。

## 3. RAG：检索增强生成的基础方法

**书目信息 [M3-3]**：Patrick Lewis, Ethan Perez, Aleksandra Piktus, Fabio Petroni, Vladimir Karpukhin, Naman Goyal, Heinrich Küttler, Mike Lewis, Wen-tau Yih, Tim Rocktäschel, Sebastian Riedel, Douwe Kiela. **Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks**. *Advances in Neural Information Processing Systems 33 (NeurIPS 2020)*, 2020: 9459–9474. [NeurIPS官方论文页](https://proceedings.neurips.cc/paper/2020/hash/6b493230205f780e1bc26945df7481e5-Abstract.html)。该官方页面未列 DOI，本记录不补造 DOI。

**相关工作与区别（可直接引用）**：RAG将预训练生成模型与可检索的非参数知识结合，通过检索相关文本支持知识密集型任务。本项目同样强调生成应依赖外部依据，但输入来自风险模型和追踪算法的冻结事实快照，未实现原论文的稠密检索与联合训练。程序控制事实目录和数值回填，大模型负责组织声明，因此适合表述为证据约束报告生成，不能仅因提供Evidence就声称复现经典RAG。

## 4. FEVER：声明判断与证据定位

**书目信息 [M3-4]**：James Thorne, Andreas Vlachos, Christos Christodoulopoulos, Arpit Mittal. **FEVER: a Large-scale Dataset for Fact Extraction and VERification**. *Proceedings of the 2018 Conference of the North American Chapter of the Association for Computational Linguistics: Human Language Technologies, Volume 1 (Long Papers) (NAACL-HLT 2018)*, 2018: 809–819. DOI: [10.18653/v1/N18-1074](https://doi.org/10.18653/v1/N18-1074)。[官方论文页](https://aclanthology.org/N18-1074/)。

**相关工作与区别（可直接引用）**：FEVER围绕维基百科声明构建支持、反驳和证据不足三类判断，并为可判断声明提供证据句，突出判断与证据定位的联合要求。本项目将这种可核查思路用于AML报告，把声明绑定到事实ID及源字段，必要时定位原始特征记录或有向关系段。其校验依赖预注册类型和受限表达，不是对开放域文本进行真假分类，更不将模型风险认定为犯罪事实。

## 5. FActScore：按细粒度事实评价长文本

**书目信息 [M3-5]**：Sewon Min, Kalpesh Krishna, Xinxi Lyu, Mike Lewis, Wen-tau Yih, Pang Koh, Mohit Iyyer, Luke Zettlemoyer, Hannaneh Hajishirzi. **FActScore: Fine-grained Atomic Evaluation of Factual Precision in Long Form Text Generation**. *Proceedings of the 2023 Conference on Empirical Methods in Natural Language Processing (EMNLP 2023)*, 2023: 12076–12100. DOI: [10.18653/v1/2023.emnlp-main.741](https://doi.org/10.18653/v1/2023.emnlp-main.741)。[官方论文页](https://aclanthology.org/2023.emnlp-main.741/)。作者姓名沿用当前ACL官方元数据，其中列作Pang Koh。

**相关工作与区别（可直接引用）**：FActScore将长文本拆分为原子事实，计算获得可靠知识源支持的事实比例，避免整篇二元判断掩盖局部错误。本项目同样逐条处理声明，但声明引用的是程序预先组织的复合事实，评价以类型、主体、单位一致性和协议必选事实覆盖为主。该覆盖率含系统规则，分母也不同，不能称为FActScore、事实真实性概率或全部输入信息的召回率。

## 综合定位建议

可用于报告的表述：**本项目参考检索增强生成、带引用生成和生成后修订等研究，将其适配为面向AML分析的受约束声明协议：以冻结事实目录限定生成范围，以类型、主体、单位和来源一致性核验声明，通过有限局部修复、确定性渲染及证据位置回溯形成可审核的报告流程。贡献在于领域任务适配与工程闭环，不主张对上述通用方法的学术首创。**

| 本项目机制 | 可论证的价值 | 必须保留的边界 |
|---|---|---|
| 固定事实目录、源值回填 | 限制事实表达空间，防止模型改写数值与地址 | 无法证明输入模型风险本身正确；不能证明任意自然语言语义 |
| 类型、主体、单位校验 | 拦截路径分冒充地址风险、引用主体错配等协议错误 | 来源真实或引用存在，不自动意味着任意解释正确 |
| 至多一次局部修复 | 限制修订位置，保护已通过声明，失败可回退 | 受最终声明数量上限约束；模拟修复不是自然输出修复率 |
| 事实ID、JSON Pointer、源记录/路径段定位 | 读者可复查声明引用位置与原值 | SHA256只用于本地快照一致性；不是签名、司法证据链或不可篡改存证 |

## 报告实验口径核对

- 正式故障实验是12个变体×10类人为注入故障：旧规则拒绝24/120，新协议拒绝120/120；新协议另有12/12正确协议样例通过。两种表达空间不同，不能改写为“自然幻觉率下降80%”。
- 120/120模拟修复通过、1200/1200已通过声明保留，验证的是合规修复接收和保留机制，不能声称真实大模型修复成功率100%。
- DeepSeek首次验收含1次小连接请求和同一个地址的2次报告请求；两份报告各52条声明首轮通过，无修复请求。这是单地址通路验收，不是2个独立地址样本，也不是总体自然幻觉率或跨模型对照实验。
- 本记录按官方摘要界定各论文方法，不借用其原始benchmark数值证明本系统效果；无须把这些相关工作全部描述为本系统实现的组成部分。

## 核实来源与输出

- 每项书目信息均由相应官方页面的citation元数据核实，相关工作描述由该页摘要核实。
- 核实范围：标题、完整作者列表、年份、正式venue、页码、官方URL；ACL四篇另核实DOI。
- 结构化元数据另存 `report_literature_metadata.json`，按academic-search标准字段记录；引用数与全文状态未调查，分别为null和unknown。未下载全文，也未进行引用计量或系统综述。
