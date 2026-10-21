# 大模型报告接入

链境智安通过 OpenAI-compatible Chat Completions 接口调用大模型。模型负责组织声明，固定事实由程序回填和核验。推荐使用支持 JSON object 输出的服务。

## 配置

在项目目录复制 `.env.example` 为 `.env`，填写账号实际支持的接口与模型：

```dotenv
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=填写自己的API密钥
LLM_MODEL=deepseek-flash
```

重启 `python run_web.py`，在“AI分析报告”选择“自动选择报告来源”并生成。页面显示本次来源和核验记录。选择“结构化证据模板”可直接生成同协议报告。

## 网页调用参数

新版网页由 `api/reporting.py` 管理请求参数，默认输出上限 32768 token、超时 90 秒；环境变量 `LLM_MAX_TOKENS`、`LLM_TIMEOUT_SECONDS` 可调整。服务端读取 API Key，浏览器接收报告结果。

已有真实接口验收包含两次各 52 条声明的报告，并验证特征定位、连接见证与审计包。新版网页还完成 99 项事实的较长报告调用验证。报告及接口协议回归使用 `tests/test_web_reporting.py`、`tests/test_audited_reporting.py`。

## 可选连接检查

```bash
python scripts/32_check_llm_connection.py
python scripts/32_check_llm_connection.py --report
```

以上命令会调用配置的外部接口。日常自动化自检使用结构化证据模板；报告核验与证据定位见 [模块三设计](MODULE_03_EXPLAINABLE_REPORT.md)。
