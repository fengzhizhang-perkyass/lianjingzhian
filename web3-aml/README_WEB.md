# 链境智安：宣传首页与双数据集分析工作台

**链境智安——面向虚拟资产洗钱风险的智能识别与可信研判系统**。

前端沿用 HTML、CSS、JavaScript 和本地 Python HTTP 服务。宣传页保留动态首屏、锚点导航与“洞见链上风险，让研判有据可循”的口号；点击“开始分析”进入独立工作台。无需 Node、npm 或外部 CDN。请通过 HTTP 地址访问，不要双击 `frontend/index.html`。

## 当前交付状态

本次 v4 在 v3.1 双数据集冻结运行包基础上接入关联群组发现、群组引导追踪和群组报告证据，不训练新模型，不修改原实验测试划分或按测试标签调整阈值。网页不展示产品版本号。

- **关联群组**：比特币当前索引有59个群组、覆盖4077个成员地址；以太坊有6个群组、覆盖40个成员地址，均只使用当前已评分地址的真实有向关系。后台默认利用有效索引安排搜索；前台点击“发现关联群组”后才显示当前起点／所选路径相关群组。支持完整成员分批加载、高亮、手动唯一聚合与展开，原追踪结果不因画布操作改变。群组证据自动进入可信研判，无须先点击发现。

- **以太坊**：当前追踪使用 **103,171 个已评分地址、3,228 条真实有向关系**组成的专用子图。原始 497,340 个节点、746,306 条关系及交易见证数据库继续保留，用于冻结模型的观测上下文和来源核查。新图是原图的真实诱导子图，不通过删除中间地址拼接新边；两个模型分支全部地址的运行概率与冻结预测一致。当前核验见 `artifacts/v31_graph_verification/verification.json`，原始运行包核验见 `artifacts/datasets/ethereum/current/verification.json`。
- **比特币**：冻结的 1,783 维输入已取回并通过全文件 SHA256 校验；64 条冻结样本的模型概率最大误差为 0。已生成 822,942 个地址的分数及 2,784,344 条有向关系，统一准备器已通过；按当前真实结果重新准备的三条长链示例分别为 31、31、5 跳。核验记录见 [运行清单](artifacts/datasets/bitcoin/current/manifest.json)、[输入传回校验](model_upgrade/transaction_evidence/cache_v3_frozen/transfer_verification.json) 与 [长链示例](artifacts/datasets/bitcoin/current/long_cases.json)。

双链概率校准已完成数据用途审计：现有独立校准及检验数据不足，用户已决定本轮暂缓校准，保持 `identity`，原始概率与实际风险分数不变。状态为 `needs_data`，不能表述成“概率已校准”或“已证明概率可靠”。说明见 `artifacts/v31_checks/概率校准数据审计.md`，源数据用途和散列见 `artifacts/calibration/{bitcoin,ethereum}/current/audit.json`。

此前 v3 的 134 项回归、真实 LLM 及浏览器记录仍保留在 `artifacts/v3_acceptance.json`，属于历史验收。v3.1 的当前图、评分显示、报告复用及浏览器验收应使用本轮独立记录，不能沿用历史通过结论。当前真实图与原生模型全量核验见 `artifacts/v31_graph_verification/verification.json`。 本轮最终回归214项通过，真实双链浏览器12组及独立前端交互12组通过；两条链各完成一次真实LLM报告。逐项证据见 `artifacts/v31_acceptance.json`，说明见项目上级目录《系统改造v3.1验收说明.md》。

`--verify-only` 检查清单与文件是否匹配，不代表已完成所有业务、浏览器或 LLM 验收。网页不展示产品版本号、实验编号或内部模型文件名；审计下载继续保存真实来源和内部修订信息。

v4独立记录位于 `artifacts/v4_upgrade/`、`artifacts/v4_groups_backend_verification.json`、`artifacts/v4_example_refresh.json`及 `artifacts/v4_frontend_check/`；完整说明见 [模块二群组接入](docs/MODULE_02_DENSE_GROUPS.md)。此前v3／v3.1记录属于历史版本，不能代替此次验收。

## 首次准备与启动

在 Python 3.11 环境中安装依赖。本机可用环境为 `/opt/anaconda3/envs/web3aml`：

```bash
cd /Users/luyu/Desktop/竞赛/网安/web3-aml
/opt/anaconda3/envs/web3aml/bin/python -m pip install -r requirements-web.txt
```

从 GitHub 获取项目时，先按 `GITHUB_运行说明.md` 下载完整模型与数据，包括 Git LFS 文件；仅有代码或 LFS 指针无法运行。保留原运行数据的离线还原步骤：

```bash
python scripts/prepare_runtime_data.py
```

V3 还需要对应的双链模型、冻结输入与运行包，旧单链补充包不能代替这些新增资产。比特币准备器优先使用 `model_upgrade/transaction_evidence/cache_v3_frozen/features.npy` 和同目录 `schema.json`；当前输入为 822,942 × 1,783，文件 SHA256 为 `a2ed1c8b29d1fd6a55725b2746bf9f61ab09dec766767e51aac35fed324fb232`。请保留这份已核验缓存，不需要为日常启动重新生成特征。

当前本地模型和数据齐备后，评分、解释与追踪均在本机运行，**不需要连接 SSH 服务器或使用 GPU**。独立报告的 `auto` 模式会使用服务端配置的外部 LLM 接口；`template` 模式不调用外部 LLM。本次冻结输入取回为只读下载，未使用 GPU 或重新训练。

随后在终端**先审计校准数据，再显式准备**双数据集运行包。审计脚本仅核对既有用途及无标签分数分布，不训练模型、不拟合校准器、不打开测试标签数组。准备步骤复用冻结模型、输入和预测；首次准备会读取大特征、原始交易 CSV 和构建关系见证，请预留足够磁盘空间与时间：

```bash
# 首次准备或迁移后，记录校准数据用途和当前identity状态
python scripts/audit_probability_calibration.py

# 显式准备并校验双链运行包、当前范围的图与索引
python scripts/prepare_v3_runtime.py

# 也可独立准备某一数据集
python scripts/prepare_v3_runtime.py --dataset ethereum
python scripts/prepare_v3_runtime.py --dataset bitcoin
```

准备成功后，原始运行包位于 `artifacts/datasets/{bitcoin,ethereum}/current/`，以太坊已评分地址追踪图位于 `ethereum/current/trace_scored/`，比特币当前索引位于 `bitcoin/current/anchor_index_v31/<当前风险修订>/`。原索引与原图不被覆盖。脚本核验各自清单、校准审计、追踪范围、映射和索引修订。已有正确产物直接复用；哈希或修订不符则报错，不静默改写冻结模型或选择另一条链。

准备时也会重新核对长链演示：使用当前冻结分数、追踪范围、长链参数和默认路径返回数量实际搜索，再记录真实跳数与完整修订；不会继承旧示例的长度承诺。当前以太坊真实示例为 5／4／4 跳；旧全图示例仍保存为历史来源。若当前搜索没有返回两跳及以上路径，示例列表如实为空，不编造演示结果。点击示例仅加载地址和参数，仍需点击追踪按钮运行。

准备器默认额外校验清单列出的全部源文件 SHA256。重复检查可以只读校验已有产物：

```bash
# 包含源文件的完整校验，不构建、不修改运行包
python scripts/prepare_v3_runtime.py --verify-only

# 只校验运行包文件，不全量重读大 CSV/源特征
python scripts/prepare_v3_runtime.py --verify-only --runtime-only

# 只检查以太坊
python scripts/prepare_v3_runtime.py --dataset ethereum --verify-only
```

全部选定数据集通过时退出码为 0，任一失败时为 1；输出标明 `dataset_id` 与 `asset_checks_passed`。单链失败不会伪装成另一链的成功。

### 关联群组索引的显式准备

现有双链运行包齐备后，执行以下命令只准备群组索引并按当前版本真实刷新长链示例，不重训或改写冻结评分：

```bash
python scripts/prepare_v3_runtime.py --groups-only

# 只读核验两条链的群组索引，不构建、不改写
python scripts/prepare_v3_runtime.py --groups-only --verify-only

# 仅因追踪或报告源码版本更新而刷新演示缓存时
python scripts/refresh_trace_examples_v4.py --dataset all
```

索引保存在 `artifacts/datasets/<dataset_id>/current/dense_groups/<revision>/`，`active.json`指向活动修订。索引绑定评分、图、追踪范围、校准身份、算法和配置。首次迁移需要显式执行准备命令；普通网页请求不构建全图索引。修改算法或构建参数后需要重新准备并重启服务。

索引缺失或失效时，服务明确关闭群组引导并回退原有追踪；群组面板提示暂不可用，报告不编造群组。旧的锚点索引与基础运行包仍是普通追踪所需资产。

**双链准备与校验完成后**再启动：

```bash
/opt/anaconda3/envs/web3aml/bin/python run_web.py
```

打开 [宣传首页](http://127.0.0.1:8000/) 或 [分析工作台](http://127.0.0.1:8000/workspace)。端口冲突时使用 `python run_web.py --port 8001`；按 Ctrl+C 停止。初期使用一个进程，避免重复加载大型图与索引。

启动会校验原运行包、校准审计及当前追踪图和索引。网页服务不负责重训模型；缺少已准备运行包或索引时，应返回终端执行准备命令，不能等待网页请求替你构建大型资产。出现缺文件、LFS 指针、SHA256/文件大小不一致或冻结概率不一致时，应补齐对应输入并重新核验，不应通过删除清单条目绕过检查。

## 页面与模块

宣传页导航为“首页—项目背景—技术路径—证据融合”。项目背景继续使用原有内容；技术路径同步新系统流程，证据融合展示报告样张。宣传页不加载业务图和大型数据。

工作台顶部固定导航，一次只显示一个模块，模块内部可纵向滚动：

| 模块 | 主要内容 |
| --- | --- |
| **优先序列调查** | 全局选择比特币或以太坊，查看风险排序、等级统计、分页列表并导出当前队列范围 |
| **地址风险识别** | 查询当前数据集中已有地址，查看真实风险分数、对应解释、特征与关系统计 |
| **多跳关联追踪** | 快速/长链追踪、参数与预算、真实有向关系、可拖动节点、逐跳路径和交易见证 |
| **可信研判生成** | 一个可编辑地址框及一个生成按钮；自动填入当前对象，优先复用有效评分／路径，缺少或失效步骤自动补齐 |

数据集选择作用于四个模块；切换后请求与结果始终属于当前数据集，同页会话内按数据集隔离并恢复地址、模块、追踪和报告状态。刷新或关闭页面后的状态持久化不属于此轮交付。导航切换本身不重新生成报告。

只支持当前数据集可评分集合中已有的地址。输入不存在的地址时返回明确错误；不会接入公网临时查询或为任意新地址编造特征。以太坊追踪只搜索已评分地址及它们之间原本存在的真实有向边，完整观测图的其它地址不会进入搜索、桥接、图展示或当前报告路径。没有合格路径时如实显示空结果。

图中的**低风险为青绿色**，低风险但已评分的地址仍可以作为真实路径中间点；图例、节点详情及图统计不再展示“未评分”。切换路径、模块和拖动节点不改变模型结果或证据。

风险等级按未四舍五入的实际综合风险分判定：**低风险 0≤分数<30，中风险 30≤分数<60，高风险 60≤分数<80，极高风险 80≤分数≤100**。评分卡、队列及图例提供统一说明；搜索中的“风险锚点门槛”是可调搜索条件，不等同于极高风险阈值。

实际不足100、但普通两位小数会显示成100的风险分，公开显示为 **`>99.99`**，详情保留精确值；CSV、JSON和审计证据继续保存原始数值。这个显示规则不修改概率、排序、风险等级或特征值。

保留 `/workspace/queue`、`/workspace/risk`、`/workspace/trace`、`/workspace/report` 路由。顶部位置条表示当前模块位置，不代表任务计算完成百分比。“模型评估详情”不再对外展示。

## 双数据集的识别与解释

### 比特币：1,783 维输入

使用冻结的 B3 模型及其对应 1,783 维输入。页面显示名称为“多维证据风险识别”，展示三个解释组：

- **交易行为画像**：地址自身的交易规模、频率和活跃习惯。
- **邻域行为偏离**：地址与关联地址之间的行为差异。
- **资金流转特征**：资金收支方向、汇聚分散情况及关联交易属性。

每个输入特征仅归入一个组，新增交易聚合特征归入资金流转特征。解释来自当前真实模型的 TreeSHAP，贡献单位为模型原始输出，不是三个独立风险概率，也不是三个诊断分取平均。

### 以太坊：结构–属性双视图协同融合模型（SA-DCF）

面向公开以太坊钓鱼/恶意地址数据快照，显示“交易属性画像—交易结构表征—双视图融合结果”。使用 56 维交易属性及冻结编码器的 32 维结构表示；保留真实模型及既定融合配方。风险识别页已删除“从两路判断，到最终风险”过程卡片、公开融合系数和“未评分交易对手”统计项。

两路分别保留自身真实解释及加性核对；不能将两路原始输出上的 SHAP 相加后冒充最终融合概率的 SHAP。结构部分保留原观测上下文的真实交易数、交易对手及结构表示摘要，交易对手列表不声称是注意力权重。这些冻结模型上下文与范围更小的追踪子图分别管理，不能因页面不展示某项统计而删改训练输入。

以太坊关系图保留真实交易方向；见证提供真实交易哈希、源 CSV 与记录位置，金额使用精确 Wei/ETH 字符串，同一交易出现在多个 CSV 不会重复计入金额。当前图反映数据快照中的已观测交易，不表示完整链历史。

## 可信研判与 LLM

“可信研判生成”使用一个可编辑地址输入框及一个主生成按钮：有“当前对象”时自动填入该地址，没有时留空。用户修改输入后以输入框目标为准；从队列某行进入时以该行地址为明确目标，不被旧对象覆盖。其它模块明确选择新对象时同步输入，普通重渲染不反复覆盖正在编辑的草稿。

同地址、同数据集且修订与参数匹配时复用评分和追踪；缺少步骤自动补齐，参数变更或口径过期时重做失效步骤。有效追踪保留用户参数；尚无设置时才使用默认值。复用的是分析证据，点击生成仍产生本次报告。进度展示实际阶段或复用状态，不填写估算百分比；地址不存在时不会调用外部 LLM。

“自动”模式使用服务端 `.env` 或环境变量中的既有接口配置；“结构化证据模板”跳过外部调用。密钥不进入 HTML、JavaScript、审计包或 Git，修改服务端配置后重启。具体配置项以服务端报告配置为准。

LLM 负责组织已有证据，地址、风险分数、路径与交易等事实由程序约束和核验。请求或候选结构失败时显示本次实际回退来源；再次成功生成的新报告不保留旧报告的回退提示。网络故障后保留旧报告时，界面应明确说明保留的是旧结果。

报告可下载 Markdown、TXT、Evidence JSON 与 ZIP 审计包。新报告公开正文不枚举融合权重，审计证据仍保留真实分支输出、融合参数、原概率及当前校准状态并完整核验。证据定位保留真实模型／数据修订和源位置；历史报告保持原内容及散列，不为改文案原地重写审计原件。

## 主要接口

新页面请求始终携带 `dataset_id=bitcoin|ethereum`，旧接口默认比特币；新独立报告入口必须明确数据集。

| 接口 | 用途 |
| --- | --- |
| `GET /api/datasets` | 查看数据集列表与准备状态 |
| `GET /api/meta?dataset_id=ethereum` | 获取对应说明、默认配置与真实示例 |
| `GET /api/queue?dataset_id=ethereum&limit=100&offset=0` | 查询对应风险队列 |
| `GET /api/risk?dataset_id=ethereum&address=...` | 分析当前数据集的地址 |
| `POST /api/traces` | 使用同数据集的 `analysis_id` 追踪 |
| `POST /api/reports` | 使用同数据集的分析/追踪快照生成报告 |
| `POST /api/reports/from-address` | 提交独立地址报告任务，返回 HTTP 202 与 `job_id` |
| `GET /api/jobs/{job_id}?dataset_id=ethereum` | 查询实际任务阶段及最终完整结果 |

独立报告请求体示例（将地址替换为当前集合的实际地址）：

```json
{"dataset_id":"ethereum","address":"0x...","mode":"template"}
```

同一入口可选传 `reuse_analysis_id`、`reuse_trace_id`、`trace_mode`（`quick`／`long`）与 `trace_params`。服务端会核对数据集、目标地址、风险／校准／图范围／报告修订及参数；不匹配时不会错误复用。`trace_params`只接受现有允许的追踪参数，不能传入客户端风险分或任意图内容。

`mode` 可为 `auto` 或 `template`。未知地址返回 404；跨数据集或过期修订快照冲突返回 409；数据集参数错误返回 422；运行数据不可用返回明确的准备错误。下载与历史快照同样校验数据集和修订，避免串用两条链的结果。

## 前端从哪些文件改起

| 想修改什么 | 文件 |
| --- | --- |
| 页面、导航、标题与表单结构 | `frontend/index.html` |
| 业务布局、颜色、两页排版、艺术字 | `frontend/styles.css`、`frontend/pages.css` |
| 参考首屏与导航样式 | `frontend/reference.css` |
| 粒子连线动态背景 | `frontend/js/background.js` |
| 宣传页滚动导航与初始化 | `frontend/js/navigation.js`、`frontend/js/landing.js` |
| 两页路由与模块位置条 | `frontend/js/router.js` |
| 数据集上下文、输入、按钮和跨模块联动 | `frontend/js/workspace.js`、`frontend/js/state.js` |
| 四个业务模块的渲染 | `frontend/js/views/queue.js`、`risk.js`、`tracing.js`、`evidence.js` |
| 关系网络布局、拖动和缩放 | `frontend/js/relation-network.js` |
| 群组发现、分页加载与查看状态 | `frontend/js/groups.js` |
| 群组聚合和原始关系的纯展示转换 | `frontend/js/network-model.js` |
| 页面公开名称和元数据过滤 | `frontend/js/display-metadata.js` |
| 网页请求 Python 接口 | `frontend/js/api.js` |
| 通用图表 | `frontend/js/charts.js` |
| 项目背景文案 | `frontend/content/project-background.json`；修改后运行 `python scripts/render_background.py` |
| 宣传报告样张来源 | `frontend/content/report-preview.json` |

`api/datasets/` 提供双数据集适配，`api/runtime_v3.py` 负责任务与快照，`src/report/dataset_reporting.py` 提供双链证据报告。只改展示时不需要修改模型、原始输入或搜索算法。

## 数据、验证与维护

冻结模型及原始实验记录保留在原目录；新增运行包单独存于 `artifacts/datasets/`，分析与报告快照存于 `artifacts/web_runs/`。更换冻结数据或配置后重新准备、校验并重启服务，不能混用旧快照。

文件校验与业务测试分开进行。以太坊的精确金额、真实来源、冻结概率、分支解释、原全图保留及当前已评分追踪范围可用以下命令复核：

```bash
python -m pytest tests/test_ethereum_v3.py tests/test_v31_scored_graph.py -q

# 全量核对103171行映射／原生概率、全部3228条追踪边及源资产散列
# 不创建Runtime，不调用LLM，不打开标签数组
python scripts/verify_scored_graph_v31.py
```

浏览器检查需要服务已正常启动，以及本机 Playwright/Chrome；它们不是运行网页的必需依赖。新增双链验收记录应独立保存，不能把此前单链网页、旧 Streamlit 或旧 LLM 的通过记录当成本次双链验收。

原 Streamlit 可按其原数据与依赖运行 `python -m streamlit run app.py`，属于保留的旧入口，不等同于本 README 中的双数据集工作台。

视觉参考来自 DongWuZhengQuan 的首屏、导航和粒子网络；科技化标题使用 CSS，图表使用本地 Plotly，关系图使用本地 Cytoscape.js。背景支持暂停与减少动态效果；真实图表不叠加装饰性实时资金流动画。第三方许可证和来源记录保留在 `frontend/vendor/`。

### 开发备注：冻结输入与跨平台重构

ARM 与 x86 环境重新执行浮点特征变换时，部分 float32 运算可能产生末位差异；个别值若跨越树的分裂阈值，模型概率也可能变化。因此正式运行优先复用已核验的 `cache_v3_frozen` 输入，不能仅以形状相同或平均误差很小代替冻结字节一致性。开发重构应单独输出候选缓存，先核验完整 SHA256、冻结样本输入和模型概率，再决定是否形成新运行修订。此说明仅用于维护，不进入产品页面。
