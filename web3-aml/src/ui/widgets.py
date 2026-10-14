import networkx as nx
import plotly.graph_objects as go
import streamlit as st

COLORS = {"LOW": "#047857", "MEDIUM": "#B45309", "HIGH": "#C2410C", "CRITICAL": "#B91C1C"}


def gauge(title, value, color="#1E40AF"):
    fig = go.Figure(go.Indicator(mode="gauge+number", value=value,
        number={"suffix": " / 100", "font": {"size": 28, "color": "#172554"}},
        title={"text": title, "font": {"size": 16}},
        gauge={"axis": {"range": [0, 100]}, "bar": {"color": color},
               "steps": [{"range": [0, 30], "color": "#D1FAE5"}, {"range": [30, 60], "color": "#FEF3C7"},
                         {"range": [60, 80], "color": "#FFEDD5"}, {"range": [80, 100], "color": "#FEE2E2"}]}))
    fig.update_layout(height=240, margin=dict(l=24, r=24, t=50, b=16), paper_bgcolor="rgba(0,0,0,0)", font_color="#172554")
    st.plotly_chart(fig, width="stretch", config={"displayModeBar": False})


def relation_graph(trace, highlighted_edges=None, highlighted_nodes=None):
    graph = nx.DiGraph()
    for node in trace["subgraph"]["nodes"]:
        graph.add_node(node["address_id"], **node)
    for edge in trace["subgraph"]["edges"]:
        graph.add_edge(edge["src"], edge["dst"])
    best = trace["top_paths"][0]["nodes"] if trace["top_paths"] else []
    ordered_chain = len(trace['top_paths']) == 1 and len(best) > 8
    if ordered_chain:
        # A snake layout preserves every hop while keeping a long simple path
        # readable. Hover/table retains full addresses; hop number is not time.
        positions = {a: ((i % 6 if (i // 6) % 2 == 0 else 5-i % 6), -(i // 6))
                     for i,a in enumerate(best)}
    else:
        positions = nx.spring_layout(graph, seed=42)
    best_edges = set(zip(best, best[1:])) if highlighted_edges is None else set(map(tuple,highlighted_edges))
    highlighted_nodes = set(highlighted_nodes or [])
    figure = go.Figure()
    annotations = []
    for src, dst in graph.edges:
        x0, y0 = positions[src]
        x1, y1 = positions[dst]
        highlighted = (src, dst) in best_edges
        color = "#1E40AF" if highlighted else "#94A3B8"
        figure.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode="lines", hoverinfo="skip", showlegend=False,
                                    line=dict(color=color, width=3 if highlighted else 1.3)))
        annotations.append(dict(x=x0+(x1-x0)*.78, y=y0+(y1-y0)*.78, ax=x0+(x1-x0)*.55, ay=y0+(y1-y0)*.55,
            xref="x", yref="y", axref="x", ayref="y", showarrow=True, arrowhead=3, arrowsize=1.2, arrowwidth=2, arrowcolor=color))
    for level in ("LOW", "MEDIUM", "HIGH", "CRITICAL"):
        nodes = [a for a in graph if graph.nodes[a].get("risk_level") == level and not graph.nodes[a]["is_seed"]]
        if not nodes:
            continue
        figure.add_trace(go.Scatter(x=[positions[a][0] for a in nodes], y=[positions[a][1] for a in nodes],
            mode="markers+text", name=level,
            text=[f'{best.index(a)}跳' if ordered_chain else a[:7]+"…" for a in nodes], textposition="top center",
            customdata=[[a, graph.nodes[a]["risk_score"]] for a in nodes],
            hovertemplate="%{customdata[0]}<br>风险 %{customdata[1]:.2f}<extra>"+level+"</extra>",
            marker=dict(size=[14+graph.nodes[a]["risk_score"]*.14 for a in nodes], color=COLORS[level],
                        line=dict(color=['#1E40AF' if a in highlighted_nodes else 'white' for a in nodes],
                                  width=[4 if a in highlighted_nodes else 2 for a in nodes]))))
    seed = trace["seed_address"]
    figure.add_trace(go.Scatter(x=[positions[seed][0]], y=[positions[seed][1]], mode="markers+text", name="Seed",
        text=["SEED"], textposition="bottom center", customdata=[[seed, graph.nodes[seed]["risk_score"]]],
        hovertemplate="%{customdata[0]}<br>风险 %{customdata[1]:.2f}<extra>Seed</extra>",
        marker=dict(size=34, symbol="diamond", color="#1E40AF", line=dict(color="white", width=3))))
    figure.update_layout(height=500, margin=dict(l=20, r=20, t=30, b=20), annotations=annotations,
        xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=True,
        paper_bgcolor="#FFFFFF", plot_bgcolor="#FFFFFF", font_color="#172554")
    st.plotly_chart(figure, width="stretch")
    st.caption("箭头表示原始地址关系方向；蓝色边高亮当前核查的证据关系。完整地址可在对应路径表核对。" if highlighted_edges is not None else
               "箭头表示原始地址关系方向；蓝色边高亮搜索排序第一的路径。下方路径表提供完整地址。")
