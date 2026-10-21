# 链境智安：宣传首页与分析工作台

完整名称：**链境智安——基于多维证据融合的链上反洗钱与可解释研判系统**。

2026-10-20 按《改进方案.md》拆分为宣传首页和独立分析工作台，随后按《改进方案v2.md》补充项目背景并改造关系网络交互。继续使用 HTML、CSS、JavaScript 与原有 Python HTTP 服务，算法、数据、模型和 Streamlit 入口保留。仓库及 Python 包内部仍沿用 web3-aml 名称。

## 启动

本机环境已经安装所需依赖。双击本目录的 `启动新版前端.command`，或运行：

```bash
cd /Users/luyu/Desktop/竞赛/网安/web3-aml
/opt/anaconda3/envs/web3aml/bin/python run_web.py
```

打开 [宣传首页](http://127.0.0.1:8000/)，点击“开始分析”进入 [分析工作台](http://127.0.0.1:8000/workspace)。页面和接口由同一服务提供，无需 Node、npm 或外网 CDN；不要双击 `frontend/index.html` 打开。

若迁移到其他电脑，先准备匹配的 processed 与 artifacts，在 Python 3.11 环境安装：

```bash
python -m pip install -r requirements-web.txt
python run_web.py
```

端口占用可使用 `python run_web.py --port 8001`。终端按 Ctrl+C 停止。启动时会加载整图与索引，等待终端显示 `Application startup complete` 后访问。初期使用一个进程，以免重复加载大数据。

原版仍可通过同一环境运行 `python -m streamlit run app.py`，一般使用 8501 端口，供结果对照。

## 前端新手从哪些文件开始

| 想修改什么 | 文件 |
| --- | --- |
| 宣传页、工作台、导航、标题与表单结构 | `frontend/index.html` |
| 现有业务布局与颜色 | `frontend/styles.css` |
| 两页布局、艺术字、技术流程、报告样张、工作台导航与位置条 | `frontend/pages.css` |
| 参考项目原有的首屏与导航样式 | `frontend/reference.css`，追加修改优先放 styles.css |
| 粒子与连线背景 | `frontend/js/background.js` |
| 两页路由、返回恢复、模块切换与位置条 | `frontend/js/router.js` |
| 宣传页锚点定位与滚动高亮 | `frontend/js/navigation.js` |
| 宣传页初始化 | `frontend/js/landing.js` |
| 调查优先队列、分页、选择地址 | `frontend/js/views/queue.js` |
| 风险评分与模型评估展示 | `frontend/js/views/risk.js` |
| 设置、关系图、路径明细 | `frontend/js/views/tracing.js` |
| 关系网络自然布局、拖动、缩放与恢复 | `frontend/js/relation-network.js` |
| 对外模型名称及技术摘要 | `frontend/js/display-metadata.js` |
| 项目背景数据与政策文案 | `frontend/content/project-background.json`；修改后运行 `python scripts/render_background.py` |
| 报告、声明与证据定位 | `frontend/js/views/evidence.js` |
| 页面启动与业务代码延迟加载 | `frontend/js/app.js` |
| 业务按钮、请求与跨模块联动 | `frontend/js/workspace.js` |
| 站内共享页面状态与分析状态 | `frontend/js/state.js` |
| 宣传报告样张的可核对来源 | `frontend/content/report-preview.json` |
| 网页向 Python 请求结果 | `frontend/js/api.js` |
| 图形绘制和高亮 | `frontend/js/charts.js` |

`api/` 是新增 Python 适配层。只调整页面展示时，不需要修改模型、原始特征或搜索算法。代码没有使用 Tailwind 或 React/Vue。

## 两页结构与使用

宣传页顶部为“首页—项目背景—技术路径—证据融合”，保留动态首屏、科技感口号与优势展示。证据融合区是取自真实报告的静态样张，没有点击证据的演示操作；首页不发起业务请求，也不加载大型图表库。首屏网络是前景与背景的视觉表达。

工作台导航顺序固定为：

1. **调查优先队列**：风险等级统计、候选列表、分页、每页数量、核查地址与 CSV 下载。
2. **地址风险分析**：地址/节点 ID、三组示例、综合风险、三类诊断与归因、特征表、加性核对、关联统计。模型评估详情与实验对照已从新版网页移除。
3. **关系链追踪**：快速/长链、六项参数、长链样例、可拖动的自然关系网络、路径选择、逐跳风险、连接见证、预算与 JSON 下载。
4. **AI分析报告**：报告生成、来源、六段声明、证据定位、核验记录、Markdown/TXT/Evidence JSON/ZIP 下载、模拟故障与修复。

一次只显示一个模块，当前模块可向下滚动，顶部导航固定。导航下方细条表示当前模块位置（25/50/75/100%），不是任务计算完成度。现有表单、评分图表与报告内部排布保留，关系主图新增整理节点的工具。

第一次点击“开始分析”进入队列；队列选择地址进入风险分析，“继续关系追踪”切换至追踪模块。导航本身不重新评分、搜索或生成报告。队列首次进入自动查询，之后切换可恢复分页。

在同一页面运行期间，点击“返回首页”或品牌标识回到宣传页，再从任何“开始分析”入口进入，会恢复上次模块、输入草稿、评分、追踪参数、路径、报告和证据选择。采用前端路由共享内存状态，不重新加载整份页面；不使用跨会话持久化。刷新/关闭后恢复不属于本轮范围。

可直接访问 `/workspace/queue`、`/workspace/risk`、`/workspace/trace`、`/workspace/report`。首次直接访问没有上次结果时显示正常空状态。

确认载入新地址仍会清除旧路径、报告与证据选择；修改追踪参数使旧报告失效，重新运行后才能生成新报告。原 `analysis_id`、`trace_id`、`report_id` 绑定服务端快照的逻辑保留，过期请求不能覆盖新地址。

## 数据与外部能力

数据是静态快照，评分和路径搜索口径沿用原 Python 服务。综合分不是三类诊断分平均；路径排序分不是洗钱概率，方向边不是有金额和时间的逐笔交易。

报告“自动”模式沿用原服务配置与回退逻辑；可手动选“结构化证据模板”。密钥只在服务端使用 `.env` 或环境变量配置，不返回浏览器。页面改版时的回归验证采用模板及明确标注的模拟修复；2026-10-20 又单独完成了真实 LLM 的前端调用验证，详见下节。

当前没有原始 CSV，报告保留固定 Evidence 字段、特征与关系路径定位，原始 CSV 物理行号入口如实提示不可用。完整审计包保留原文件格式与 SHA256 校验口径。

## 从 GitHub 获取完整运行数据

下载与跨平台启动步骤见 [GITHUB_运行说明.md](GITHUB_运行说明.md)。模型及运行数据使用 Git LFS，克隆后需完成 `git lfs pull`。其中三个大文件以 `runtime-data/` 下的 19 个压缩分卷交付，约 779 MB 压缩为约 303 MB；新版网页启动时由 `api/runtime_data.py` 自动还原并验证 SHA256，原数据内容、路径与 174 文件基线保持一致。已有正确数据时直接复用，不覆盖不匹配的自有文件。

未启动新版网页时，先运行 `python scripts/prepare_runtime_data.py` 再使用旧 Streamlit、命令行校验或接口测试。维护者可用 `python scripts/package_runtime_data.py` 重建分卷，日常使用无需执行。

## 使用 LLM 生成报告

本机已在项目根目录的 `.env` 配置 DeepSeek 官方接口，模型名为 `deepseek-flash`。该文件权限为 600，已被 `.gitignore` 排除；不要将密钥填进 HTML、JavaScript 或提交到仓库。更改配置后需重启 Python 服务。

使用步骤：在“调查优先队列”选择一个地址，或在“地址风险分析”查询地址 → 切换“AI分析报告” → 保留“自动选择报告来源” → 点击“生成分析报告”。尚未运行关系链追踪时，系统会先按默认参数追踪，再调用 LLM；已有追踪结果则直接复用。成功后来源显示“LLM 组织声明 · 协议事实已核验”。

LLM 根据固定证据选择并组织报告声明；分数、地址与路径等事实仍由程序回填、核验。接口异常时保留原有备用模板机制，页面会显示实际来源与回退原因。选择“结构化证据模板”会跳过外部 LLM 调用。

2026-10-20 已通过真实 Chrome 页面完成一次自动模式生成：1 次外部调用、约 15.3 秒、52 条声明、核心事实覆盖率 100%，候选错误、局部模板替换和未解决声明均为 0。证据定位、Markdown 和审计包下载正常。该时间为此次实测结果，实际耗时随网络、接口负载和证据数量变化。

验证记录：`artifacts/llm_live_check/result.json`；生成样本：`artifacts/llm_live_check/report.md`；审计包：`artifacts/llm_live_check/audit-bundle.zip`。此次真实调用记录与此前的前端改版验收记录分别保存。

### 2026-10-21：报告截断与重试提示修复

本次复现的失败由输出上限引起：接口正常返回，但用尽原来的 8192 token，返回 `finish_reason=length`，内容不完整，程序按原协议改用证据模板。这不等同于密钥或接口不可用。原先“LLM请求或候选结构失败”的通用提示也可能由网络、超时、认证、返回 JSON 无法解析等情况触发，不能单凭这句话判断原因。

新版网页通过 `api/reporting.py` 使用 32768 token 输出上限和 90 秒请求超时；可在服务端设置 `LLM_MAX_TOKENS`（1–65536）与 `LLM_TIMEOUT_SECONDS`（1–90）后重启。原 `config/llm.yaml` 和旧 Streamlit 入口保持原样。单次请求仍不自动重试网络故障；报告结构核验不通过时的受限修复属于另一条流程。

新生成的模板报告会区分“输出截断”“响应超时”“连接失败”“密钥验证失败”“格式要求”等原因，并在审计记录中保存安全错误代码与本次限制参数，不记录异常中的密钥内容。旧报告保留生成时的提示，读取历史报告不会改写它。

每次点击“生成分析报告”都会生成独立报告。重试等待期间隐藏旧报告与旧提示；新报告成功后清除旧回退提示。如果本次 HTTP 请求失败，会恢复上一份报告，并明确说明保留了旧结果。候选结构修复后出现的“候选含未通过声明”是当次核验过程记录，与上一次请求失败提示不同。

实际验证：原失败记录的同一地址、分析与追踪输入，99 项事实完全一致（证据生成时间更新），修复后一次真实 LLM 调用生成 99 条声明，约 29.9 秒，输出 11765 token，核心事实覆盖率 100%，无需模板替换。正式入口 8000 的 Chrome 检查采用第一次失败提示注入、第二次真实 LLM 成功的方式，确认等待时隐藏、成功后清除，以及 HTTP 失败后恢复旧报告。48 项后端测试通过；审计下载包的 6 项文件哈希全部通过。

检查说明与详细证据：`artifacts/llm_recheck/检查说明.md`、`diagnosis-original.json`、`fixed-99-facts.json`、`retry-browser.json`；测试代码：`tests/test_web_reporting.py`。

## 结果保存与版本

新增结果存于 `artifacts/web_runs/`，使用独立编号且不会被同地址下一次运行覆盖。原业务服务仍可能保存原地址命名文件，新接口不将这些“最新文件”用作历史下载；涉及旧服务的调用串行协调。结果版本包含数据、模型、追踪与报告版本，跨版本生成报告会被拒绝。更换数据或配置后应重启服务。

现有 `runtime_manifest.json` 是原运行包的 174 文件基线，新增前端和适配层不通过篡改旧哈希获得通过。原 `scripts/34_check_runtime.py --ui` 可继续核对；新接口与浏览器需要额外检查。

## 验证方式

```bash
python -m pytest tests/test_web_api.py -q
python scripts/34_check_runtime.py --ui
```

浏览器检查脚本为 `scripts/check_web_ui.cjs`，需要本机 Playwright 与 Chrome。支持 `PLAYWRIGHT_MODULE`、`CHROME_PATH`、`WEB3AML_URL`、`WEB3AML_CHECK_OUTPUT` 环境变量；默认采用此次本机可用路径。不属于运行网页的必要依赖。

## 视觉来源

`reference.css` 从本地 DongWuZhengQuan 首屏/导航样式提取；背景粒子实现也参考其 `setupHeroNetwork`。沿用 #060814、#4E65F5、#61D8FF、#EDF2F8、几何切角和深浅分区。首屏新增实心艺术字、冰蓝渐变与切片细节，宣传文案和流程改为链境智安的实际能力。响应式规则重新编写，不继承原参考页面的小屏溢出。

`frontend/vendor/plotly.min.js` 来自当前 Python Plotly 安装附带的官方 Plotly.js 分发文件，版本与版权信息保留在文件开头。字体使用本机系统字体，科技化标题由 CSS 实现。背景可暂停、屏幕外停止、尊重减少动态效果；真实图表不播放装饰性实时资金流动画。

## 2026-10-20 验收与备份

此前两页改版验收：18 项接口回归、37 项真实 Chrome 浏览器检查及原六页 Streamlit 检查通过；九个示例和 32 跳案例保留。记录在 `artifacts/metrics/web_frontend_acceptance.json`，截图和下载检查文件位于 `artifacts/web_ui_check/`。

原前端与适配入口备份在 `.runtime-backups/landing-workspace-20261020-125707/`，不包含未改动的图表库大文件。原算法、模型与数据运行包继续按 `runtime_manifest.json` 校验。

## 项目背景与关系网络的维护

宣传区块为静态 HTML，数据与三张政策卡片在 `frontend/content/project-background.json` 集中维护。修改 JSON 后，在项目目录执行 `python scripts/render_background.py` 更新页面；启动网页时不需要执行构建命令。正文来源核验见上级目录《改进方案v2.md》，宣传页不展示来源链接。

关系追踪主图使用本地 Cytoscape.js 与内置 CoSE 布局。拖动节点后位置保持，空白处可拖动画布，滚轮可缩放；也可用「选择节点」与方向按钮整理位置。图形区域获得焦点后，方向键移动选中的节点。「重置布局」恢复初始排布，「适应视图」保留节点位置并调整视野。

路径切换、模块切换与站内返回均保留布局和视野；屏幕尺寸改变时重新适配视野以显示完整图形。新追踪结果使用独立布局。节点拖动不重新分析，不改变评分、路径或报告证据；下载 JSON 保留原始数据。组件加载失败时可点击重试，路径与报告功能仍可使用。

新版网页不展示产品版本或模型迭代编号，统一显示「LightGBM 联合风险模型」。网页展开区显示面向用户的摘要，原始证据与审计下载继续保留真实内部元数据。

`frontend/vendor/cytoscape.min.js` 固定为 Cytoscape.js 3.33.1，采用 MIT 许可证，获取来源与 SHA256 记录在 `cytoscape.source.json`，许可证在 `cytoscape.LICENSE`。组件仅在需要显示关系网络时加载，宣传页不加载它。评分和报告证据图继续使用 Plotly。

本轮新增检查：`scripts/check_network_ui.cjs`，检查组件失败恢复、更多路径、节点数据、原始 JSON 下载与真实手机触摸。与主浏览器脚本使用相同的 `WEB3AML_URL` 和 `WEB3AML_CHECK_OUTPUT` 配置。

## 本轮改进验收记录

正式入口 `http://127.0.0.1:8000/` 的 42 项主页面回归、6 项网络专项检查通过，浏览器无页面异常；18 项接口回归及原六页 Streamlit 检查通过，九个示例和 32 跳案例保留。原运行包 174 个文件哈希均保持一致。

真实 LLM 自动模式重新验证通过：1 次调用、约 15 秒、52 条声明全部通过核验，未发生修复或局部模板替换。结果在 `artifacts/web_llm_v2_check/`。页面、网络专项截图和下载分别在 `artifacts/web_ui_v2_check/`、`artifacts/web_network_check/`；汇总记录是 `artifacts/metrics/web_frontend_v2_acceptance.json`。

改动前备份为 `.runtime-backups/background-network-20261020-204344/`，不包含密钥文件。新数据文案、模型展示名与关系图组件分别有独立维护入口，详见上表。
