# 压缩运行数据

本目录的 `runtime-*.part` 是同一个 ZIP 的连续分卷，由 Git LFS 管理。请完成 `git lfs pull`，不要改名、单独解压或遗漏分卷。

新版网页 `python run_web.py` 会自动还原并核对原文件。使用旧 Streamlit 或命令行校验前，可先运行：

```bash
python scripts/prepare_runtime_data.py
```

清单 `manifest.json` 保存每个分卷、整个压缩包以及三个原文件的大小与 SHA256。还原结果保持原数据内容和路径：

- `artifacts/evidence_scoring/features.npy`
- `artifacts/risk_scores/graph_statistics.parquet`
- `data/processed/raw_features.npy`

分卷还原不调用外部 API，也不改变模型或评分。存在不匹配的原文件时会报错，保留原文件供使用者检查。维护者仅在更新上述数据后运行 `python scripts/package_runtime_data.py` 重建分卷。
