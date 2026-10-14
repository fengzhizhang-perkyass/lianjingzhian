"""A hop-index view keeps long real paths readable without implying time order."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st


def render_path_detail(trace):
    paths = trace['top_paths']
    if not paths:
        return
    st.subheader('逐跳关系证据')
    longest = max(range(len(paths)), key=lambda i: paths[i]['hop_count'])
    chosen = st.selectbox('选择要核查的路径', range(len(paths)), index=longest,
        format_func=lambda i: f"路径 {paths[i]['rank']} · {paths[i]['hop_count']} 跳",
        key='path_detail_'+trace['seed_address']+'_'+trace.get('provenance',{}).get('config_hash','legacy'))
    path = paths[chosen]
    threshold = trace['config']['risk_threshold']
    hops = list(range(len(path['nodes'])))
    roles = ['起点' if i == 0 else '低分连接' if score < threshold else '风险锚点'
             for i, score in enumerate(path['node_risks'])]
    for column, label, value in zip(st.columns(3), ['路径跳数','路径地址数','低分连接节点'],
        [path['hop_count'], len(path['nodes']), len(path.get('bridge_nodes',[]))]):
        column.metric(label, value)
    figure = go.Figure(go.Scatter(x=hops,y=path['node_risks'],mode='lines+markers',
        line=dict(color='#1E40AF',width=2),marker=dict(size=8),
        customdata=[[a,r] for a,r in zip(path['nodes'],roles)],
        hovertemplate='第 %{x} 跳<br>%{customdata[0]}<br>风险 %{y:.2f}<br>%{customdata[1]}<extra></extra>'))
    figure.add_hline(y=threshold,line_dash='dash',line_color='#B45309',
                     annotation_text=f'锚点门槛 {threshold}')
    figure.update_layout(height=300,margin=dict(l=15,r=20,t=35,b=20),
        xaxis=dict(title='关系跳数（不是交易时间）',dtick=max(1,path['hop_count']//8)),
        yaxis=dict(title='原始地址风险',range=[0,100]),showlegend=False,
        paper_bgcolor='#FFFFFF',plot_bgcolor='#FFFFFF',font_color='#172554')
    st.plotly_chart(figure,width='stretch')
    st.caption('连线表示路径相邻关系，风险分保持原值；曲线不代表金额流动或交易时序。')
    with st.expander('逐跳核对完整地址与方向'):
        st.dataframe(pd.DataFrame({'跳数':hops,'地址':path['nodes'],
            '原始风险分':path['node_risks'],'角色':roles}),hide_index=True,width='stretch')
        st.caption('证据编号：'+path.get('evidence_id','legacy'))
