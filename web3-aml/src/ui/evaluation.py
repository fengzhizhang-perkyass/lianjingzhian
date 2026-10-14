import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.utils.io import ROOT, read_json
from src.ui.runtime import get_service

NAMES = {"lightgbm": "LightGBM", "behavior": "Behavior MLP", "graphsage": "GraphSAGE", "dual_view": "Dual-View"}


def render_investigation_results():
    index = get_service().investigation
    if index is None:
        return
    folder = ROOT / "artifacts/experiments" / index.metadata["experiment"]
    if not (folder / "findings.json").exists():
        return
    findings = read_json(folder / "findings.json")
    seed = findings["representative_seed"]
    candidate = read_json(folder / f"final/seed_{seed}/review_priority_test.json")
    st.subheader("调查排序：异构专家互补实验")
    st.write("拓扑增强树、GraphSAGE 和双线路模型分别给出意见，再形成独立的调查优先级。")
    c1, c2, c3 = st.columns(3)
    c1.metric("代表模型测试 AP", f"{candidate['pr_auc']:.3f}")
    c2.metric("Top-500 命中率", f"{candidate['review']['top_500']['precision']:.1%}")
    c3.metric("Top-1% 命中率", f"{candidate['review']['top_0.01_fraction']['precision']:.1%}")
    st.caption(f"代表种子 {seed} 按验证 AP 选择。预算指标仅覆盖已知标签测试地址，不能作为整体准确率或 unknown 命中率。")
    from src.train.investigation_report import NAMES as names
    experiments = pd.read_csv(folder / "final_comparison.csv")
    means = experiments.groupby("candidate", sort=False)[["pr_auc", "f1", "recall"]].mean()
    means.index = [names[key] for key in means.index]
    st.dataframe(means.style.format("{:.4f}"), width="stretch")
    st.caption("上表为三个神经专家种子的平均结果；拓扑树未开启随机子采样，各次树输出相同。")
    fig = go.Figure()
    for name in experiments.candidate.unique():
        subset = experiments[experiments.candidate == name]
        fig.add_trace(go.Bar(name=names[name], x=[f"种子 {int(s)}" for s in subset.seed], y=subset.pr_auc))
    fig.update_layout(barmode="group", height=320, yaxis=dict(range=[0, .5], title="测试 AP"), legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    st.write(f"与同种子 GraphSAGE 比较，AP 在 {findings['ap_wins_vs_graph']}/{findings['paired_seeds']} 次中提高；平均差值 {findings['ap_gain_vs_graph_mean']:+.4f}。")
    complementarity = findings.get("top500_complementarity")
    if complementarity:
        st.write(f"在相同的 500 地址复核预算下，相比原双线路队列净增加 {complementarity['net_illicit_gain']} 个 illicit 标签命中。")
    with st.expander("实验设计、完整对比与复现边界"):
        st.write(f"开发选择的固定权重：GraphSAGE / Dual-View / 拓扑树 = {findings['selected_weights']}。")
        st.write(f"匹配预算的纯行为树 AP {findings['raw_tree_ap']:.4f}，拓扑增强树 AP {findings['topology_tree_ap']:.4f}。")
        st.dataframe(experiments, hide_index=True, width="stretch")
        st.caption("权重在原训练区间内的两个开发时间段选择；测试集此前已被查看，属于重复基准评估，未构成外部泛化或统计显著性证明。")
        st.download_button("下载完整调查实验报告", (folder / "REPORT.md").read_text(encoding="utf-8"), "investigation_report.md", "text/markdown")
    st.divider()


def render():
    st.title("模型评估")
    service = get_service()
    if service.predictor.metadata.get('model_kind') == 'evidence_tree':
        from src.ui.evidence_scoring import render_evaluation
        render_evaluation(service)
    render_investigation_results()
    st.subheader("原风险模型对比")
    st.write("同一数据划分上的独立模型对比；阈值在验证集选择，测试指标由保存的预测结果计算。")
    comparison = read_json(ROOT / "artifacts/metrics/comparison.json")
    table = pd.DataFrame(comparison).T
    table.index = [NAMES.get(i, i) for i in table.index]
    st.dataframe(table[["precision", "recall", "f1", "pr_auc", "roc_auc"]].astype(float).style.format("{:.4f}"), width="stretch")
    fig = go.Figure()
    for metric in ("f1", "recall", "pr_auc"):
        fig.add_trace(go.Bar(name=metric.upper(), x=table.index, y=table[metric]))
    fig.update_layout(barmode="group", height=350, yaxis=dict(range=[0, 1], title="测试指标"),
                      legend=dict(orientation="h"), margin=dict(t=20, b=20))
    st.plotly_chart(fig, width="stretch")
    left, right = st.columns(2)
    pr, roc = go.Figure(), go.Figure()
    for model in comparison:
        results = read_json(ROOT / "artifacts/metrics" / f"{model}.json")
        pr.add_trace(go.Scatter(x=results["pr_curve"]["recall"], y=results["pr_curve"]["precision"], name=NAMES[model], mode="lines"))
        roc.add_trace(go.Scatter(x=results["roc_curve"]["fpr"], y=results["roc_curve"]["tpr"], name=NAMES[model], mode="lines"))
    pr.update_layout(title="Precision–Recall", xaxis_title="Recall", yaxis_title="Precision", height=400)
    roc.update_layout(title="ROC", xaxis_title="False Positive Rate", yaxis_title="True Positive Rate", height=400)
    left.plotly_chart(pr, width="stretch")
    right.plotly_chart(roc, width="stretch")
    selected = st.selectbox("混淆矩阵模型", list(NAMES), format_func=NAMES.get, index=3)
    result = read_json(ROOT / "artifacts/metrics" / f"{selected}.json")
    matrix = go.Figure(go.Heatmap(z=result["confusion_matrix"], x=["预测 licit", "预测 illicit"],
                                  y=["真实 licit", "真实 illicit"], colorscale="Blues", texttemplate="%{z}"))
    matrix.update_layout(height=350)
    st.plotly_chart(matrix, width="stretch")
    st.caption(f"分类阈值：{result['threshold']:.4f} · 测试节点：{result['num_test_nodes']:,}。"
               "分类阈值与界面固定的风险等级阈值用途不同。")
