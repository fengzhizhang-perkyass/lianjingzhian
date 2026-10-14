"""Reproducible competition evidence, including controls and unfavorable results."""
import numpy as np
import pandas as pd
from src.train.investigation_experiments import InvestigationExperiment
from src.utils.io import ROOT, read_json, save_json

NAMES = {"graphsage": "GraphSAGE", "dual_view": "Dual-View", "topology_tree": "Topology tree", "review_priority": "Review priority"}


def write_report(root=ROOT):
    experiment = InvestigationExperiment(root)
    raw_control = experiment.raw_tree_ablation()
    final = read_json(experiment.folder / "final_summary.json")
    comparison = pd.read_csv(experiment.folder / "final_comparison.csv")
    grouped = comparison.groupby("candidate", sort=False)[["pr_auc", "f1", "precision", "recall"]].agg(["mean", "std"])
    grouped.to_csv(experiment.folder / "mean_std.csv")
    seed = final["representative_seed"]
    reference = comparison[comparison.candidate == "graphsage"].set_index("seed")
    priority = comparison[comparison.candidate == "review_priority"].set_index("seed")
    difference = priority.pr_auc-reference.pr_auc
    reviewed, all_reviewed = [], []
    for _, row in comparison.iterrows():
        result = read_json(experiment.folder / f"final/seed_{int(row.seed)}/{row.candidate}_test.json")
        for budget, counts in result["review"].items():
            all_reviewed.append({"candidate": row.candidate, "seed": int(row.seed), "budget": budget, **counts})
            if int(row.seed) == seed:
                reviewed.append({"candidate": row.candidate, "budget": budget, **counts})
    pd.DataFrame(all_reviewed).to_csv(experiment.folder / "review_all_seeds.csv", index=False)
    pd.DataFrame(reviewed).to_csv(experiment.folder / "review_representative.csv", index=False)
    metrics = {"representative_seed": seed,
               "ap_gain_vs_graph_mean": float(difference.mean()), "ap_gain_vs_graph_sd": float(difference.std(ddof=1)),
               "ap_wins_vs_graph": int((difference > 0).sum()), "paired_seeds": len(difference),
               "f1_wins_vs_graph": int((priority.f1 > reference.f1).sum()),
               "raw_tree_ap": raw_control["pr_auc"], "topology_tree_ap": float(grouped.loc["topology_tree", ("pr_auc", "mean")]),
               "selected_weights": final["selection"]["weights"], "expert_names": final["selection"]["experts"]}
    current = np.load(experiment.folder / f"final/seed_{seed}/test_predictions.npz")
    old = np.load(experiment.source / f"final/dual_view/seed_{seed}/test_predictions.npz")
    if not np.array_equal(current["node_idx"], old["node_idx"]):
        raise ValueError("Complementarity diagnostic must use aligned test predictions.")
    labels = experiment.labels[current["node_idx"]]
    new_top = set(np.argsort(-current["probability"], kind="stable")[:500].tolist())
    old_top = set(np.argsort(-old["fused_logits"], kind="stable")[:500].tolist())
    gained = sum(int(labels[i]) for i in new_top-old_top)
    lost = sum(int(labels[i]) for i in old_top-new_top)
    metrics["top500_complementarity"] = {"budget": 500, "new_illicit_in_queue": gained,
                                         "old_illicit_out_of_queue": lost, "net_illicit_gain": gained-lost,
                                         "shared_addresses": len(new_top & old_top)}
    save_json(experiment.folder / "findings.json", metrics)
    lines = ["# 调查增强实验：拓扑专家、共识排序与分歧复核", "",
             "这是一层可操作的调查决策设计：保留原模型风险，另行安排复核优先级，",
             "展示专家告警共识和分歧，并用 TreeSHAP 解释拓扑专家。",
             "工程组合具有比赛展示价值，不宣称这些通用技术首次被提出。", "",
             "## 已冻结的实验", "",
             "- 开发：只使用原训练区间内的 1–22 / 23–28 与 1–28 / 29–34 两组时间划分。",
             "- 拓扑：入度、出度、邻居数、方向平衡、双向邻居比例、上下游平均连接度和孤立标志，共八项。",
             "- 训练 / 开发验证：拓扑只保留截止时间之前节点的关系；不输入标签或未来节点边。",
             "- 组合：GraphSAGE / Dual-View / 拓扑树，各自恢复加权赔率并验证集温度校准。",
             f"- 15 组权重按平均开发 AP 选择，冻结为 {final['selection']['weights']}；测试结果不参与选择。",
             f"- 最终复核优先级代表种子为 {seed}，按验证 AP 在最终测试读入前确定。", "",
             "## 测试对比", "", "| 方法 | AP 均值 ± SD | F1 均值 ± SD | Recall 均值 |", "|---|---:|---:|---:|"]
    for name in grouped.index:
        line = grouped.loc[name]
        lines.append(f"| {NAMES[name]} | {line[('pr_auc','mean')]:.4f} ± {line[('pr_auc','std')]:.4f} | "
                     f"{line[('f1','mean')]:.4f} ± {line[('f1','std')]:.4f} | {line[('recall','mean')]:.4f} |")
    lines += ["", "三次组合改变神经专家种子；树模型未开启随机子采样，三个树专家输出相同，不能声称获得三份独立树模型验证。",
              f"组合相对对应 GraphSAGE 的 AP 在 {metrics['ap_wins_vs_graph']}/3 个种子中提高，平均差值 {difference.mean():+.4f}。",
              "这是同一数据集上的种子敏感性检查，不能当作统计显著性或外部泛化证明。", "",
              "## 拓扑消融", "",
              f"匹配 LightGBM 训练预算、预处理、早停和划分的纯行为树 AP：{raw_control['pr_auc']:.4f}；",
              f"加入八项拓扑后的树 AP：{metrics['topology_tree_ap']:.4f}。对照在冻结主方案后独立计算，未用于重选方案。",
              "拓扑树本身仍未超过 GraphSAGE；收益来自互补组合，不能宣称树模型全面最优。", "",
              "## 人工复核预算", "",
              f"以下是同种子 {seed} 对照；旧报告中的 GraphSAGE 代表种子 44 不应混同。",
              "已知标签测试地址 56,436 个，其中 illicit 2,548 个。", "",
              "| 方法 | Top-100 命中率 | Top-500 命中率 | Top-1% 命中率 | Top-5% 命中率 |",
              "|---|---:|---:|---:|---:|"]
    reviews = pd.DataFrame(reviewed)
    for name in grouped.index:
        subset = reviews[reviews.candidate == name].set_index("budget")
        rates = [subset.loc[budget, "precision"] for budget in ("top_100", "top_500", "top_0.01_fraction", "top_0.05_fraction")]
        lines.append("| "+NAMES[name]+" | "+" | ".join(f"{v:.1%}" for v in rates)+" |")
    lines += ["", f"相较同种子 Dual-View 的 Top-500，新增命中 {gained} 个 illicit 标签地址、移出 {lost} 个，净增加 {gained-lost} 个。",
              "这描述固定预算下的队列互补，不等于全量 unknown 的新增犯罪发现。",
              "完整种子及召回率见 `review_all_seeds.csv`。命中率不是整体准确率，不能外推到 unknown 地址。", "",
              "## 演示设计", "",
              "1. 调查优先队列：优先排查、分歧复核、排序上调三种入口，支持导出和地址跳转。",
              "2. 专家分歧地图：优先级与分数极差的固定抽样地图，辅以可读表格。",
              "3. 地址诊断：显示三个独立专家分数、各自告警阈值、告警意见、权重和 TreeSHAP。",
              "4. 调查闭环：地址 → 行为 / 图证据 → 有向路径 → Evidence JSON → 六部分报告。",
              "5. 在线队列、解释和追踪不读取 Ground Truth；标签只用于离线评价。", "",
              "## 边界与适用范围", "",
              "- 旧测试集已被查看，本轮是重复基准评估；不是全新盲测。",
              "- 生命周期特征属于静态快照，不能宣传为历史时点早期检测。",
              "- 校准在已知标签验证集拟合；unknown 人群和后续时间段的概率校准尚未保证。",
              "- 专家分歧不等于预测错误；分数极差不是置信区间。“一致未告警”不证明正常。",
              "- TreeSHAP 解释树专家原始输出，不是组合排序的因果贡献。",
              "- 全量预计算与已知标签测试批次的邻居采样上下文不同，不能用 Demo 队列表冒充测试预测。",
              "- 原风险分与关系追踪仍使用 V1.1；调查优先级单独用于安排排查顺序。", ""]
    (experiment.folder / "REPORT.md").write_text("\n".join(lines), encoding="utf-8")
    write_figure(experiment.folder, grouped, reviews)
    return metrics


def write_figure(folder, grouped, reviews):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    order = list(NAMES)
    colors = ["#2563EB", "#7C3AED", "#D97706", "#059669"]
    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    for ax, metric, title in zip(axes[:2], ["pr_auc", "f1"], ["Average Precision", "F1"]):
        means = grouped.reindex(order)[(metric, "mean")]
        sd = grouped.reindex(order)[(metric, "std")]
        ax.bar([NAMES[n] for n in order], means, yerr=sd, capsize=4, color=colors)
        ax.set_ylim(0, .5)
        ax.set_title(title+" (mean +/- SD)")
        ax.tick_params(axis="x", rotation=25)
        ax.grid(axis="y", alpha=.2)
    for name, color in zip(order, colors):
        subset = reviews[reviews.candidate == name].set_index("budget")
        budgets = ["top_100", "top_500", "top_0.01_fraction", "top_0.05_fraction"]
        axes[2].plot(["100", "500", "565 (1%)", "2822 (5%)"], [subset.loc[b, "precision"] for b in budgets],
                     "o-", label=NAMES[name], color=color)
    axes[2].set(title="Review precision: validation-selected seed", xlabel="Reviewed known-label test addresses", ylim=(0, 1.05))
    axes[2].legend(fontsize=8)
    axes[2].grid(alpha=.2)
    fig.suptitle("Temporal test snapshot: topology expert + review-priority ensemble")
    fig.tight_layout()
    fig.savefig(folder / "comparison.png", dpi=200)
    plt.close(fig)
