"""Investigation queues and model disagreement, with explicit address drill-down."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.ui.runtime import get_service
from src.utils.io import ROOT, read_json

EXPERTS = {"graphsage": "GraphSAGE 专家", "dual_view": "双线路专家", "topology_tree": "拓扑增强树专家"}
STATUS_COLORS = {"共识告警": "#B91C1C", "模型分歧": "#B45309", "待复核": "#1E40AF", "一致未告警": "#475569"}


def open_address(address):
    st.session_state["active_address"] = address
    st.session_state["address_input"] = address
    st.session_state["page"] = "地址风险分析"
    st.session_state.pop("trace", None)
    st.session_state.pop("report", None)


def render_address_panel(analysis):
    info = analysis.get("investigation_analysis")
    if not info:
        return
    with st.container(border=True):
        st.subheader("调查优先级与专家诊断")
        c1, c2, c3 = st.columns(3)
        c1.metric("调查优先级", f"{info['priority_score']:.2f}")
        c2.metric("专家意见", info["review_status"])
        votes = sum(info["expert_scores"][k] >= info["warning_thresholds"][k] for k in EXPERTS)
        c3.metric("专家告警", f"{votes} / 3")
        expert_table = pd.DataFrame([{"专家": EXPERTS[key], "分数": value,
                                     "告警阈值": info["warning_thresholds"][key],
                                     "意见": "告警" if value >= info["warning_thresholds"][key] else "未告警",
                                     "排序融合权重": info["expert_weights"][key]}
                                    for key, value in info["expert_scores"].items()])
        st.dataframe(expert_table.style.format({"分数": "{:.2f}", "告警阈值": "{:.2f}", "排序融合权重": "{:.0%}"}),
                     hide_index=True, width="stretch")
        st.caption("调查优先级安排复核顺序，综合风险分保留原双线路结果。专家阈值分别在验证集选择；模型分歧不是预测错误概率。")
        evidence = pd.DataFrame(info.get("topology_evidence", []))
        if not evidence.empty:
            st.markdown("**拓扑树专家为什么这样判断**")
            fig = go.Figure(go.Bar(x=evidence.contribution, y=evidence.feature, orientation="h",
                                  marker_color=["#B91C1C" if value >= 0 else "#1E40AF" for value in evidence.contribution]))
            fig.update_layout(height=260, margin=dict(l=15, r=15, t=10, b=35),
                              xaxis_title="TreeSHAP 对树专家原始输出的贡献", yaxis=dict(autorange="reversed"))
            st.plotly_chart(fig, width="stretch")
            st.dataframe(evidence[["feature", "model_input_value", "contribution"]].rename(
                columns={"feature": "特征", "model_input_value": "模型输入值", "contribution": "TreeSHAP 贡献"}),
                hide_index=True, width="stretch")
            st.caption("正值提高树专家输出，负值降低输出。此处解释树专家，不能视为整个组合的因果贡献。")


def render():
    st.title("调查优先队列")
    st.write("从高分地址进入分析，也可以从模型分歧和排序上调进入调查。每个候选都能继续查看证据、关系路径与报告。")
    service = get_service()
    if service.predictor.metadata.get('model_kind') == 'evidence_tree':
        from src.ui.evidence_scoring import render_queue
        render_queue(service)
        return
    index = service.investigation
    if index is None:
        st.info("调查队列尚未准备，先运行 scripts/13_experiment_investigation.py 和 scripts/14_precompute_investigation.py。")
        if service.investigation_error:
            st.warning(service.investigation_error)
        return
    table = index.table
    columns = st.columns(4)
    for column, status in zip(columns, STATUS_COLORS):
        column.metric(status, f"{(table.review_status == status).sum():,}")
    st.caption("告警一致性按各专家自己的验证集阈值判断。“一致未告警”不表示地址已被证实正常。")
    queue = st.radio("排查策略", ["优先排查", "分歧复核", "排序上调"], horizontal=True, key="investigation_strategy")
    settings = index.metadata["diagnostics"]
    limit = st.slider("展示候选数", min_value=10, max_value=500, value=settings["queue_size"], step=10)
    if queue == "分歧复核":
        selected = table[table.review_status == "模型分歧"].sort_values("priority_score", ascending=False).head(limit)
        st.write("这些地址的专家告警意见不一致，先检查具体分歧和证据。")
    elif queue == "排序上调":
        selected = table[(table.rank_gain > 0) & (table.priority_rank <= settings["uplift_queue_size"])].sort_values("rank_gain", ascending=False).head(limit)
        st.write("这些地址在组合排序中较原双线路排序前移，可作为补充排查入口。")
    else:
        selected = table.sort_values("priority_score", ascending=False).head(limit)
    shown = selected[["address_id", "priority_rank", "priority_score", "base_risk_score", "review_status", "warning_expert_count", "rank_gain"]]
    shown = shown.rename(columns={"address_id": "地址", "priority_rank": "调查排名", "priority_score": "调查优先级",
                                  "base_risk_score": "原双线路风险分", "review_status": "专家意见",
                                  "warning_expert_count": "告警专家数", "rank_gain": "排名前移"})
    st.dataframe(shown.style.format({"调查优先级": "{:.2f}", "原双线路风险分": "{:.2f}"}), hide_index=True, width="stretch")
    st.download_button("下载当前调查队列 CSV", shown.to_csv(index=False).encode("utf-8-sig"), "investigation_queue.csv", "text/csv")
    if not selected.empty:
        target = st.selectbox("选择候选地址", selected.address_id.tolist(), key=f"queue_address_{queue}")
        st.button("查看该地址的风险与证据", on_click=open_address, args=(target,), type="primary")
    st.subheader("专家分歧地图")
    st.caption("横轴为调查优先级，纵轴为专家分数极差。分数极差描述模型输出差异，不是置信区间。")
    sample = table.sample(min(len(table), settings["plot_sample_size"]), random_state=index.metadata["seed"])
    sample = pd.concat([sample, selected]).drop_duplicates("address_id")
    fig = go.Figure()
    symbols = dict(zip(STATUS_COLORS, ["diamond", "x", "square", "circle"]))
    for status, color in STATUS_COLORS.items():
        rows = sample[sample.review_status == status]
        fig.add_trace(go.Scattergl(x=rows.priority_score, y=rows.expert_disagreement, mode="markers", name=status,
                                  marker=dict(color=color, symbol=symbols[status], size=7, opacity=.65),
                                  customdata=rows[["address_id", "warning_expert_count"]].to_numpy(),
                                  hovertemplate="%{customdata[0]}<br>优先级 %{x:.2f}<br>分数极差 %{y:.2f}<br>告警专家 %{customdata[1]}<extra>"+status+"</extra>"))
    fig.update_layout(height=400, margin=dict(l=10, r=10, t=10, b=25), xaxis_title="调查优先级",
                      yaxis_title="专家分数极差", xaxis=dict(range=[0, 100]), yaxis=dict(range=[0, 100]),
                      legend=dict(orientation="h"))
    st.plotly_chart(fig, width="stretch")
    st.caption(f"地图展示固定抽样及当前候选，共 {len(sample):,} 个地址；上方表格可查完整候选值。全量队列不使用真实标签。")
