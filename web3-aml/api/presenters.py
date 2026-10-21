"""Pure Plotly presenters. No Streamlit imports and no model calculations."""
import json
import networkx as nx
import plotly.graph_objects as go

BLUE, RED = '#4E65F5', '#B91C1C'
COLORS = {'LOW': '#657794', 'MEDIUM': '#B45309', 'HIGH': '#C2410C', 'CRITICAL': '#B91C1C'}


def figure_json(fig, height=320, dark=False):
    fig.update_layout(height=height, autosize=True, font=dict(family='PingFang SC, Microsoft YaHei, sans-serif', color='#BBC8E2' if dark else '#334155', size=12),
                      paper_bgcolor='#10172C' if dark else '#FFFFFF', plot_bgcolor='#10172C' if dark else '#FFFFFF',
                      margin=dict(l=30, r=24, t=42, b=46), colorway=[BLUE, '#61D8FF', RED, '#B45309', '#7569FF'],
                      hoverlabel=dict(font_size=13))
    return json.loads(fig.to_json())


def scoring_charts(scoring):
    groups = scoring['groups']
    bars = go.Figure(go.Bar(x=[g['contribution'] for g in groups], y=[g['label'] for g in groups], orientation='h',
                           marker_color=[RED if g['contribution'] >= 0 else BLUE for g in groups]))
    bars.update_layout(yaxis=dict(autorange='reversed'), xaxis_title='TreeSHAP 对联合模型原始输出的贡献')
    correction = scoring['corrected_logit'] - scoring['raw_margin']
    values = [scoring['base_value'], *[g['contribution'] for g in groups], correction, 0]
    waterfall = go.Figure(go.Waterfall(x=['模型基准', *[g['label'] for g in groups], '类别权重校正', '校准前 logit'],
        y=values, measure=['absolute', 'relative', 'relative', 'relative', 'relative', 'total'],
        increasing=dict(marker=dict(color=RED)), decreasing=dict(marker=dict(color=BLUE)), connector=dict(line=dict(color='#94A3B8'))))
    return {'contribution': figure_json(bars, 260), 'waterfall': figure_json(waterfall, 340)}


def relation_chart(trace):
    graph = nx.DiGraph()
    for node in trace['subgraph']['nodes']:
        graph.add_node(node['address_id'], **node)
    for edge in trace['subgraph']['edges']:
        graph.add_edge(edge['src'], edge['dst'])
    best = trace['top_paths'][0]['nodes'] if trace['top_paths'] else []
    if len(trace['top_paths']) == 1 and len(best) > 8:
        positions = {a: (i % 6 if i // 6 % 2 == 0 else 5 - i % 6, -(i // 6)) for i, a in enumerate(best)}
        for address in graph:
            positions.setdefault(address, (0, 0))
    else:
        positions = nx.spring_layout(graph, seed=42)
    figure = go.Figure()
    edge_keys, arrows = [], []
    for src, dst in graph.edges:
        x0, y0 = map(float, positions[src]); x1, y1 = map(float, positions[dst])
        figure.add_trace(go.Scatter(x=[x0, x1], y=[y0, y1], mode='lines', hoverinfo='skip', showlegend=False,
                                    line=dict(color='#536584', width=1.5)))
        edge_keys.append([src, dst])
        arrows.append(dict(x=x0+(x1-x0)*.78, y=y0+(y1-y0)*.78, ax=x0+(x1-x0)*.55, ay=y0+(y1-y0)*.55,
            xref='x', yref='y', axref='x', ayref='y', showarrow=True, arrowhead=3, arrowsize=1, arrowwidth=1.5, arrowcolor='#536584'))
    for level, color in COLORS.items():
        nodes = [a for a in graph if graph.nodes[a].get('risk_level') == level and a != trace['seed_address']]
        if nodes:
            figure.add_trace(go.Scatter(x=[float(positions[a][0]) for a in nodes], y=[float(positions[a][1]) for a in nodes],
                mode='markers+text', name={'LOW':'低风险', 'MEDIUM':'中风险', 'HIGH':'高风险', 'CRITICAL':'极高风险'}[level],
                text=[str(best.index(a))+'跳' if a in best and len(best)>8 else a[:6]+'…' for a in nodes], textposition='top center',
                customdata=[[a, graph.nodes[a]['risk_score']] for a in nodes],
                hovertemplate='%{customdata[0]}<br>原始风险 %{customdata[1]:.2f}<extra></extra>',
                marker=dict(size=[14+graph.nodes[a]['risk_score']*.14 for a in nodes], color=color, line=dict(color='#AAB4CA', width=1.5))))
    seed = trace['seed_address']
    if seed in positions:
        figure.add_trace(go.Scatter(x=[float(positions[seed][0])], y=[float(positions[seed][1])], mode='markers+text',
            name='分析起点', text=['起点'], textposition='bottom center', customdata=[[seed, graph.nodes[seed]['risk_score']]],
            hovertemplate='%{customdata[0]}<br>风险 %{customdata[1]:.2f}<extra>起点</extra>', marker=dict(size=30, symbol='diamond', color='#61D8FF')))
    figure.update_layout(annotations=arrows, xaxis=dict(visible=False), yaxis=dict(visible=False), showlegend=True,
                         legend=dict(orientation='h', y=-.02), uirevision=trace.get('seed_address'))
    return {'figure': figure_json(figure, 530, True), 'edge_keys': edge_keys}
