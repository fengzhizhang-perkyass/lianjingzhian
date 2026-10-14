import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.ui.runtime import get_analysis
from src.ui.widgets import gauge, COLORS
from src.ui.investigation import render_address_panel


def render(address):
    st.title("地址风险分析")
    st.code(address, language=None)
    with st.spinner("正在整理行为与图结构证据…"):
        result = get_analysis(address)
    risk = result["risk"]
    st.markdown(f"**风险等级：{risk['risk_level']}** · 综合风险分以验证集校准后的融合输出为准。")
    if result.get('scoring_analysis'):
        from src.ui.evidence_scoring import render_address
        render_address(result)
        render_graph(result['graph_evidence'])
        with st.expander('查看原始解释 JSON'):
            st.json(result)
        return
    for column, title, field in zip(st.columns(3), ["综合风险", "行为分支风险", "图分支风险"],
                                   ["overall_score", "behavior_score", "graph_score"]):
        with column:
            gauge(title, risk[field], COLORS[risk["risk_level"]] if field == "overall_score" else "#1E40AF")
    with st.container(border=True):
        st.subheader("自适应融合系数")
        c1, c2 = st.columns(2)
        c1.metric("行为分支", f"{risk['behavior_weight']:.1%}")
        c2.metric("图分支", f"{risk['graph_weight']:.1%}")
        st.caption("系数控制两个 embedding 的融合，不等于因果贡献比例；分支分数未经独立概率校准。")
    render_address_panel(result)
    st.subheader("行为特征证据")
    behavior = pd.DataFrame(result["behavior_evidence"])
    fig = go.Figure(go.Bar(x=behavior["contribution"], y=behavior["feature"], orientation="h",
                           marker_color=["#B91C1C" if v >= 0 else "#1E40AF" for v in behavior["contribution"]]))
    fig.update_layout(height=290, xaxis_title="对行为分支 logit 的 Integrated Gradients 归因", yaxis=dict(autorange="reversed"),
                      margin=dict(l=20, r=20, t=10, b=40), paper_bgcolor="rgba(0,0,0,0)")
    st.plotly_chart(fig, width="stretch")
    st.dataframe(behavior[["feature", "feature_value", "contribution", "direction"]], hide_index=True, width="stretch")
    st.caption("正值提高行为分支输出，负值降低输出；未映射的字段保留官方原始名称。")
    render_graph(result['graph_evidence'])
    with st.expander("查看原始解释 JSON"):
        st.json(result)


def render_graph(graph):
    st.subheader("风险关联统计")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("出度 / 入度", f"{graph['out_degree']} / {graph['in_degree']}")
    c2.metric("一跳邻居", str(graph["one_hop_neighbor_count"]))
    c3.metric("邻居平均风险", f"{graph['one_hop_avg_risk']:.2f}")
    c4.metric("高风险邻居比例", f"{graph['one_hop_high_risk_ratio']:.1%}")
    st.dataframe(pd.DataFrame([{"二跳采样节点": graph["two_hop_sample_count"],
                               "二跳平均风险": graph["two_hop_avg_risk"],
                               "二跳高风险比例": graph["two_hop_high_risk_ratio"]}]), hide_index=True)
