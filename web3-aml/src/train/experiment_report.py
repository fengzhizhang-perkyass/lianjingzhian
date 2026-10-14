"""Competition-ready summaries derived exclusively from saved experiments."""
from pathlib import Path

import numpy as np
import pandas as pd

from src.utils.io import ROOT, read_json, save_json


def write_experiment_report(root: Path = ROOT, name="risk_v2"):
    folder = root / "artifacts/experiments" / name
    final = read_json(folder / "final_summary.json")
    selection = read_json(folder / "selection.json")
    manifest = read_json(folder / "manifest.json")
    comparison = pd.read_csv(folder / "final_comparison.csv")
    metrics = ["precision", "recall", "f1", "pr_auc", "roc_auc"]
    grouped = comparison.groupby("candidate", sort=False)[metrics].agg(["mean", "std"])
    learned = comparison[comparison.candidate == "dual_view"].set_index("seed")
    gains = {}
    for baseline in ("graphsage", "fixed_fusion", "behavior"):
        reference = comparison[comparison.candidate == baseline].set_index("seed")
        differences = learned["pr_auc"] - reference["pr_auc"]
        gains[baseline] = {"mean_ap_difference": float(differences.mean()),
                           "std_ap_difference": float(differences.std(ddof=1)),
                           "seeds_with_positive_ap_gain": int((differences > 0).sum()),
                           "paired_seeds": len(differences)}
    save_json(folder / "fusion_gains.json", gains)
    historical = read_json(folder / "historical_baseline.json")
    rows = []
    for candidate in grouped.index:
        row = [candidate]
        for metric in metrics:
            mean, std = grouped.loc[candidate, (metric, "mean")], grouped.loc[candidate, (metric, "std")]
            row.append(f"{mean:.4f} ± {std:.4f}" if np.isfinite(std) else f"{mean:.4f}（单次）")
        rows.append("| " + " | ".join(row) + " |")
    reviewed = []
    for candidate in grouped.index:
        # Representatives are picked by validation AP, never by test outcomes.
        item = comparison[comparison.candidate == candidate].sort_values("validation_ap", ascending=False).iloc[0]
        result = read_json(folder / item.run_id / "test.json")
        for budget, counts in result["review"].items():
            reviewed.append({"model": candidate, "seed": int(item.seed), "budget": budget, **counts})
    pd.DataFrame(reviewed).to_csv(folder / "review_budget_comparison.csv", index=False)
    all_reviewed = []
    for _, item in comparison.iterrows():
        result = read_json(folder / item.run_id / "test.json")
        for budget, counts in result["review"].items():
            all_reviewed.append({"model": item.candidate, "seed": int(item.seed), "budget": budget, **counts})
    all_reviewed = pd.DataFrame(all_reviewed)
    all_reviewed.to_csv(folder / "review_budget_all_seeds.csv", index=False)
    all_reviewed.groupby(["model", "budget"])[["precision", "recall"]].agg(["mean", "std"]).to_csv(folder / "review_budget_mean_std.csv")
    chosen = final["production_candidate"]
    deploy_ok = final["promotion_guardrails_passed"]
    save_json(folder / "deployment_review.json", {
        "eligible": deploy_ok, "production_candidate": chosen,
        "rule": "predeclared AP/F1 guardrails against the previously deployed benchmark; fusion gains reported separately",
        "fusion_gains": gains,
    })
    lines = ["# 双线路风险评分优化结果", "", f"实验：`{name}`。数据指纹：`{manifest['dataset_fingerprint']}`。", "",
             "## 冻结的方案", "", f"- 输入方案：`{selection['features']['name']}`。",
             f"- 损失：`{selection['loss']}`。", f"- 融合：`{selection['fusion']['name']}`。",
             "- 开发选择只使用原训练区间内的两个时间划分。",
             f"- 固定随机种子：{manifest['experiment']['final_seeds']}。",
             f"- 代表融合模型：seed {chosen['seed']}，按验证 AP 选择。", "",
             "加权 BCE 导出时按训练集权重恢复赔率，再在验证集做温度校准；LightGBM 同样处理类别权重偏移。", "",
             "## 最终测试对比", "", "| 方法 | Precision | Recall | F1 | AP | ROC-AUC |",
             "|---|---:|---:|---:|---:|---:|", *rows, "",
             "神经网络为三个种子的均值 ± 样本标准差；LightGBM 为一次运行。AP 使用 Average Precision。", "",
             "## 融合消融", "", "| 对照 | 融合平均 AP 差值 | 差值标准差 | 融合胜出种子数 |",
             "|---|---:|---:|---:|"]
    for baseline, values in gains.items():
        lines.append(f"| {baseline} | {values['mean_ap_difference']:+.4f} | {values['std_ap_difference']:.4f} | "
                     f"{values['seeds_with_positive_ap_gain']}/{values['paired_seeds']} |")
    lines += ["", "固定融合模型独立训练，使用与学习 Gate 相同的输入、损失、归一化、训练预算和种子。",
              "三次运行反映随机种子波动，不能替代独立数据集验证或统计显著性检验。", "",
              "## 此前基线", "", "| 方法 | 此前测试 F1 | 此前测试 AP |", "|---|---:|---:|"]
    for model, values in historical.items():
        lines.append(f"| {model} | {values['f1']:.4f} | {values['pr_auc']:.4f} |")
    lines += ["", "## 人工复核与资源", "",
              "代表种子均按验证 AP 选择。下面仅统计测试集已知标签地址：", "",
              "| 方法 | 代表种子 | Top-100 命中率 | Top-1% 命中率 |", "|---|---:|---:|---:|"]
    representative_review = pd.DataFrame(reviewed)
    for candidate in grouped.index:
        subset = representative_review[representative_review.model == candidate].set_index("budget")
        lines.append(f"| {candidate} | {int(subset.iloc[0]['seed'])} | {subset.loc['top_100', 'precision']:.1%} | "
                     f"{subset.loc['top_0.01_fraction', 'precision']:.1%} |")
    lines += ["", "Top-100 是一个小规模优先队列；其命中率不是整体准确率。",
              "`review_budget_all_seeds.csv` 和 `review_budget_mean_std.csv` 同时提供所有种子结果，避免只看代表种子。", "",
              "`review_budget_comparison.csv` 保存 Top-100、Top-500、Top-1%、Top-5% 命中率和召回率。",
              "仅针对测试集已知标签地址，不代表未知标签地址真实命中率。",
              "`final_comparison.csv` 保存模型参数量、checkpoint 字节数和 CPU 测试节点推理时间；",
              "推理计时包括采样和模型计算，已完成输入变换，不包括文件加载、特征变换和 Web 渲染。", "",
              "## 上线审查", "", f"满足当前上线审查规则：**{'是' if deploy_ok else '否'}**。",
              "代表种子、架构和输入方案没有根据测试结果重新选择。", "",
              "## 评估边界", "",
              "- 原测试集此前已被查看，本轮属于同一基准上的重复评估，不是全新外部测试。",
              "- 原验证集同时用于早停、校准、阈值及代表种子选择，验证成绩存在选择偏差。",
              "- 生命周期聚合特征不能还原历史时点可见信息，实验是静态快照风险识别。",
              "- 分支风险头尚未分别校准；Gate 是表示融合系数。",
              "- 未满足上线规则时，保留现有 Demo，不挑另一个测试成绩更高的种子替代。", ""]
    (folder / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    write_figures(folder, comparison)
    return {"report": str(folder / "REPORT.md"), "deployment_eligible": deploy_ok, "fusion_gains": gains}


def write_figures(folder, comparison):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = ["lightgbm", "behavior", "graphsage", "fixed_fusion", "dual_view"]
    names = ["LightGBM", "Behavior MLP", "GraphSAGE", "Fixed 50/50", "Gated Dual-View"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    for ax, metric in zip(axes, ["f1", "recall", "pr_auc"]):
        grouped = comparison.groupby("candidate")[metric].agg(["mean", "std"]).reindex(order)
        ax.bar(names, grouped["mean"], yerr=grouped["std"].fillna(0), capsize=4,
               color=["#94A3B8", "#60A5FA", "#2563EB", "#A78BFA", "#059669"])
        ax.set_title({"f1": "F1", "recall": "Recall", "pr_auc": "Average Precision"}[metric])
        ax.set_ylim(0, 1)
        ax.tick_params(axis="x", rotation=40)
        ax.grid(axis="y", alpha=.2)
    fig.suptitle("Temporal test: neural models 3 seeds (mean +/- SD); LightGBM 1 run")
    fig.tight_layout()
    fig.savefig(folder / "final_comparison.png", dpi=200)
    plt.close(fig)
