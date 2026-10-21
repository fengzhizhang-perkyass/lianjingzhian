# 链境智安：下载与启动

本次同步包含最新版宣传首页、四模块分析工作台、Python 接口、LLM 报告修复，以及本机已补齐的处理后数据、模型和风险评分表。页面维护说明见 [README_WEB.md](README_WEB.md)。原 README.md 保留原算法与训练流程说明，以便与原运行包校验基线一致。

## 1. 获取完整项目和大文件

先安装 [Git LFS](https://git-lfs.com/)，再运行：

```bash
git lfs install
git clone https://github.com/fengzhizhang-perkyass/wangan.git
cd wangan
git lfs pull
cd web3-aml
```

已经克隆过仓库的队友可以在仓库目录运行 `git pull`，再运行 `git lfs pull`。请先保存自己的未提交修改。大文件下载完成后，`data/processed/` 和 `artifacts/` 中的运行数据应为真实文件；若文件只有几行文字并以 `version https://git-lfs.github.com/spec/v1` 开头，说明尚未下载 LFS 内容。网页“Download ZIP”对 LFS 文件的处理取决于仓库设置，推荐使用上述克隆方式。

三个体积较大的数据文件以 `runtime-data/runtime-*.part` 压缩分卷交付，约 779 MB 原始内容压缩为约 303 MB。`python run_web.py` 首次启动时会自动还原到原来的 `data/processed/` 与 `artifacts/` 路径，并核对每个分卷、压缩包和还原文件的 SHA256。分卷不是需要手工逐一解压的独立 ZIP；不要改名或只下载其中几份。已有完整且匹配的数据时会直接复用。

## 2. 准备 Python 环境

推荐 Python 3.11。使用已有环境，或创建独立环境：

```bash
conda create -n web3aml python=3.11
conda activate web3aml
python -m pip install -r requirements-web.txt
```

当前网页推理不需要安装历史神经网络训练环境，也不需要 Node 或 npm。本机原环境仍可直接使用 `/opt/anaconda3/envs/web3aml/bin/python`。macOS 上若 LightGBM 提示缺少 `libomp`，需安装系统 OpenMP 运行库。

## 3. 启动新版网页

在 `web3-aml` 目录运行：

```bash
python run_web.py
```

等待 `Application startup complete` 后打开 <http://127.0.0.1:8000/>。宣传首页点击“开始分析”进入工作台，模块依次为调查优先队列、地址风险分析、关系链追踪、AI 分析报告。端口占用时使用 `python run_web.py --port 8001`。

## 4. 启用真实 LLM 报告

将 `.env.example` 复制为 `.env`，填写自己的 `LLM_API_KEY` 后重启服务。其他示例配置与本次实测一致。密钥不上传仓库；未配置时系统仍可生成结构化证据模板报告。

新版网页默认允许输出 32768 token，请求超时为 90 秒。点击再次生成后，成功的新报告会清除旧失败提示。单次网络请求不自动重试。修复经过 99 项事实真实报告与浏览器重试验证，详见 `artifacts/llm_recheck/检查说明.md`。

## 5. 核对与测试

```bash
python scripts/prepare_runtime_data.py
python scripts/34_check_runtime.py
python -m pip install pytest httpx
python -m pytest tests/test_web_reporting.py tests/test_audited_reporting.py tests/test_web_api.py -q
```

准备运行数据后，`34_check_runtime.py` 核对原运行包的 174 个文件并运行示例，不调用外部 LLM。后一个命令是本轮通过的 48 项回归。历史 Streamlit 入口仍可用 `python -m streamlit run app.py` 启动。

如果没有先启动过新版网页，运行旧 Streamlit、接口测试或原运行包检查前，先执行一次：

```bash
python scripts/prepare_runtime_data.py
```

分卷还原新增 4 项校验测试，运行 `python -m pytest tests/test_runtime_data.py -q`。维护者更换这三个源数据文件后，应先准备匹配的模型与清单，再执行 `python scripts/package_runtime_data.py` 重建压缩分卷；普通使用者不需要执行打包脚本。

本次上传排除了 `.env`、虚拟环境、安装包缓存、运行备份及每次操作产生的报告/会话文件。首次生成时，系统会自动在 `artifacts/reports/`、`artifacts/traces/` 和 `artifacts/web_runs/` 保存结果。原始训练 CSV 本机没有提供，当前演示使用已处理的数据与已训练模型；若需重新训练，请按原 README.md 下载公开原始数据。
