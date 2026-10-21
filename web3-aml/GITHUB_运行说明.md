# 链境智安 · 下载与启动

源码仓库：**https://github.com/fengzhizhang-perkyass/lianjingzhian**

## 获取项目

准备 Git、[Git LFS](https://git-lfs.com/) 与 Python 3.11。模型和运行数据随仓库交付，首次克隆后下载 LFS 内容：

```bash
git lfs install
git clone https://github.com/fengzhizhang-perkyass/lianjingzhian.git
cd lianjingzhian
git lfs pull
cd web3-aml
```

已有仓库可先保存本地修改，再执行 `git pull`、`git lfs pull`。`runtime-data/` 中的 19 个分卷由启动程序自动合并、还原和校验，保留完整文件名即可。已经准备好的数据会直接复用。

## 安装依赖

推荐 16 GB 内存，CPU 即可运行当前评分、追踪与报告。

Windows PowerShell：

```powershell
powershell -ExecutionPolicy Bypass -File .\setup_runtime.ps1
powershell -ExecutionPolicy Bypass -File .\run_web.ps1
```

macOS / Linux：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-web.txt
.venv/bin/python run_web.py
```

已有 Python 环境可直接安装 `requirements-web.txt` 并运行 `python run_web.py`。macOS 若提示缺少 OpenMP，先安装 `libomp`。

## 打开系统

等待终端显示 `Application startup complete`，访问 **http://127.0.0.1:8000/**。

1. 宣传首页介绍项目背景、技术路径和证据融合。
2. 点击“开始分析”，进入调查优先队列。
3. 选择地址，依次进行风险分析、关系追踪和报告生成。

端口占用时运行 `python run_web.py --port 8001`。关闭服务使用 Ctrl+C。详细操作与讲解见 [演示指南](docs/DEMO_GUIDE.md)。

## 大模型报告

复制 `.env.example` 为 `.env`，按实际账号配置：

```dotenv
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=填写自己的API密钥
LLM_MODEL=deepseek-flash
```

重启服务后，在“AI分析报告”保留“自动选择报告来源”，点击“生成分析报告”。报告页面显示本次生成来源、声明核验结果与证据入口。无需外部接口时，选择“结构化证据模板”。

网页默认输出上限 32768 token、请求超时 90 秒。通过环境变量 `LLM_MAX_TOKENS`、`LLM_TIMEOUT_SECONDS` 可调整；API Key 保存在本机服务端的 `.env`。

## 自检

```bash
python scripts/prepare_runtime_data.py
python scripts/34_check_runtime.py
python -m pip install pytest httpx
python -m pytest tests/test_web_api.py tests/test_web_reporting.py tests/test_audited_reporting.py tests/test_runtime_data.py -q
```

自检覆盖运行文件、九个演示地址、TreeSHAP 加和、路径真实边、32 跳案例与结构化报告，报告自检使用模板。更多测试入口见 [测试说明](docs/EVALUATION_PROTOCOL.md)。

## 常见启动问题

| 提示 | 处理 |
|---|---|
| 数据文件只有几行 LFS 描述文字 | 在仓库根目录执行 `git lfs pull` |
| 缺少分卷或数据校验失败 | 确认 LFS 下载完成，再运行 `python scripts/prepare_runtime_data.py` |
| 找不到 FastAPI 等模块 | 使用启动服务的同一个 Python 安装 `requirements-web.txt` |
| 模型或索引版本不一致 | 使用同一版本的源码、数据与模型，重新拉取完整仓库 |
| 报告接口暂不可用 | 检查服务端配置，或选择结构化证据模板继续演示 |

运行后生成的路径、报告与审计记录保存在 `artifacts/traces/`、`artifacts/reports/`、`artifacts/web_runs/`。
