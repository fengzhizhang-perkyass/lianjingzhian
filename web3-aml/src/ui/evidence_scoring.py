"""Three accountable evidence groups inside the existing address and evaluation pages."""
import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from src.utils.io import ROOT, read_json
from src.ui.widgets import gauge, COLORS


def render_address(analysis):
    scoring, risk = analysis['scoring_analysis'], analysis['risk']
    st.caption(scoring['model_name']+' · 行为画像 → 方向邻域偏离 → 有向结构角色 → 联合风险评分')
    scores = scoring['route_scores']
    for column, label, value in zip(st.columns(4), ['综合风险', '行为画像单独评分', '邻域偏离单独评分', '结构角色单独评分'],
                                    [risk['overall_score'], scores['behavior'], scores['context'], scores['structure']]):
        with column:
            gauge(label, value, COLORS[risk['risk_level']] if label == '综合风险' else '#1E40AF')
    st.caption('单类评分用于诊断。综合模型融合三类特征，由树的联合规则作出判断。')
    st.subheader('三类证据各自负责什么')
    table = pd.DataFrame([{'证据线路': group['label'], '职责': group['responsibility'],
                           '联合输出贡献': group['contribution']} for group in scoring['groups']])
    st.dataframe(table.style.format({'联合输出贡献': '{:+.4f}'}), hide_index=True, width='stretch')
    fig = go.Figure(go.Bar(x=[group['contribution'] for group in scoring['groups']],
                          y=[group['label'] for group in scoring['groups']], orientation='h',
                          marker_color=['#B91C1C' if group['contribution'] >= 0 else '#1E40AF' for group in scoring['groups']]))
    fig.update_layout(height=220, xaxis_title='TreeSHAP 对联合模型原始输出的贡献', yaxis=dict(autorange='reversed'),
                      margin=dict(l=10, r=10, t=10, b=35))
    st.plotly_chart(fig, width='stretch')
    st.caption('正值提高联合模型输出，负值降低输出。三组贡献加上模型基准值可还原原始输出；它们是模型归因，不是因果贡献或融合权重。')
    with st.expander('核对评分：从证据到模型输出'):
        correction = scoring['corrected_logit']-scoring['raw_margin']
        waterfall = go.Figure(go.Waterfall(
            x=['模型基准', *[group['label'] for group in scoring['groups']], '类别权重校正', '校准前 logit'],
            measure=['absolute', 'relative', 'relative', 'relative', 'relative', 'total'],
            y=[scoring['base_value'], *[group['contribution'] for group in scoring['groups']], correction, 0],
            text=[f'{v:+.3f}' for v in [scoring['base_value'], *[group['contribution'] for group in scoring['groups']], correction, scoring['corrected_logit']]],
            textposition='outside', connector=dict(line=dict(color='#94A3B8')),
            increasing=dict(marker=dict(color='#B91C1C')), decreasing=dict(marker=dict(color='#1E40AF'))))
        waterfall.update_layout(height=340, yaxis_title='模型输出 / logit', margin=dict(t=30, b=25))
        st.plotly_chart(waterfall, width='stretch')
        st.caption(f"温度参数 {scoring['temperature']:.4f}；综合风险 = 100 × sigmoid(校准前 logit / 温度)。特征贡献针对当前模型输出。")
    for group in scoring['groups']:
        st.subheader(group['label']+'证据')
        items = scoring['evidence'][group['key']]
        frame = pd.DataFrame(items)
        if frame.empty:
            st.info('当前证据不足。'); continue
        fig = go.Figure(go.Bar(x=frame.contribution, y=frame.feature, orientation='h',
                              marker_color=['#B91C1C' if v >= 0 else '#1E40AF' for v in frame.contribution]))
        fig.update_layout(height=260, yaxis=dict(autorange='reversed'), xaxis_title='联合模型 TreeSHAP 贡献',
                          margin=dict(l=10, r=10, t=10, b=35))
        st.plotly_chart(fig, width='stretch')
        st.dataframe(frame[['feature', 'feature_value', 'model_input_value', 'contribution']].rename(columns={
            'feature': '特征', 'feature_value': '地址原始值', 'model_input_value': '模型输入值', 'contribution': '贡献'}),
            hide_index=True, width='stretch')
    st.caption('邻域偏离使用上游、下游均值和标准差；无该方向邻居时偏离记为零。输入来自静态地址关系快照，不读取真实标签。')


def render_queue(service):
    table = service.predictor.table
    st.write('按当前综合风险排序，选择地址后继续查看三类证据、关系路径和可解释报告。')
    columns = st.columns(4)
    for col, level in zip(columns, ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW']):
        col.metric(level, f'{(table.risk_level == level).sum():,}')
    limit = st.slider('展示候选数', 10, 500, 100, step=10)
    selected = table.sort_values('overall_risk_score', ascending=False).head(limit)
    shown = selected[['address_id', 'risk_rank', 'overall_risk_score', 'risk_level', 'behavior_score', 'graph_score', 'structure_score']].rename(columns={
        'address_id': '地址', 'risk_rank': '风险排名', 'overall_risk_score': '综合风险', 'risk_level': '等级',
        'behavior_score': '行为单独评分', 'graph_score': '偏离单独评分', 'structure_score': '结构单独评分'})
    st.dataframe(shown, hide_index=True, width='stretch')
    st.download_button('下载当前风险队列 CSV', shown.to_csv(index=False).encode('utf-8-sig'), 'risk_queue.csv', 'text/csv')
    from src.ui.investigation import open_address
    target = st.selectbox('选择候选地址', selected.address_id.tolist(), key='evidence_queue_address')
    st.button('查看该地址的风险与证据', on_click=open_address, args=(target,), type='primary')
    st.caption('全量队列不使用真实标签；已知标签测试集的命中率不能外推到 unknown 地址。')


def render_evaluation(service):
    metadata = service.predictor.metadata
    result = read_json(ROOT / metadata['metrics_path'])
    st.subheader(metadata['model_name']+' · 当前主模型')
    for col, label, value in zip(st.columns(4), ['AP', 'F1', 'Recall', 'Top-500 命中率'],
                                [result['pr_auc'], result['f1'], result['recall'], result['review']['top_500']['precision']]):
        col.metric(label, f'{value:.4f}' if label != 'Top-500 命中率' else f'{value:.1%}')
    st.write('三路证据融合特征。模型参数、特征方案和阈值在验证阶段选择，树模型不再依赖 GraphSAGE 或在线邻居采样。')
    experiment = ROOT / 'artifacts/experiments' / metadata['experiment']
    comparison = pd.read_csv(experiment / 'final_comparison.csv')
    names = {'standardized_deviation_fusion': '完整证据融合', 'behavior_only': '只有行为画像',
             'context_only': '只有方向邻域均值', 'structure_only': '只有有向结构'}
    ablation = pd.read_csv(ROOT / 'artifacts/experiments/evidence_tree_v1_ablation/comparison.csv')
    names.update({'context_z_only': '只有邻域偏离', 'without_behavior': '去掉行为画像', 'without_context': '去掉邻域偏离',
                  'without_structure': '去掉有向结构', 'direction_removed': '去掉边方向'})
    main = comparison[comparison.seed == metadata['seed']][['candidate', 'pr_auc', 'f1', 'recall']]
    display = pd.concat([main, ablation[['candidate', 'pr_auc', 'f1', 'recall']]], ignore_index=True)
    display['candidate'] = display.candidate.map(names)
    st.subheader('每类证据的实际收益')
    st.dataframe(display.rename(columns={'candidate': '方法'}).style.format({'pr_auc': '{:.4f}', 'f1': '{:.4f}', 'recall': '{:.4f}'}),
                 hide_index=True, width='stretch')
    fig = go.Figure(go.Bar(x=display.candidate, y=display.pr_auc, marker_color='#1E40AF'))
    fig.update_layout(height=350, yaxis_title='测试 AP', xaxis_tickangle=-25, margin=dict(t=10, b=25))
    st.plotly_chart(fig, width='stretch')
    st.caption('当前 compact 树未启用随机子采样，42/43/44 输出一致；这是一个确定性结果，不能声称三次独立重复验证。')
    st.subheader('当前主模型曲线与分类结果')
    left, right = st.columns(2)
    pr = go.Figure(go.Scatter(x=result['pr_curve']['recall'], y=result['pr_curve']['precision'], mode='lines', name='当前主模型'))
    roc = go.Figure(go.Scatter(x=result['roc_curve']['fpr'], y=result['roc_curve']['tpr'], mode='lines', name='当前主模型'))
    pr.update_layout(title='Precision–Recall', xaxis_title='Recall', yaxis_title='Precision', height=340)
    roc.update_layout(title='ROC', xaxis_title='False Positive Rate', yaxis_title='True Positive Rate', height=340)
    left.plotly_chart(pr, width='stretch')
    right.plotly_chart(roc, width='stretch')
    matrix = go.Figure(go.Heatmap(z=result['confusion_matrix'], x=['预测 licit', '预测 illicit'],
                                  y=['真实 licit', '真实 illicit'], colorscale='Blues', texttemplate='%{z}'))
    matrix.update_layout(title='当前主模型混淆矩阵', height=300)
    st.plotly_chart(matrix, width='stretch')
    st.caption(f"验证选择阈值 {result['threshold']:.4f}；Precision {result['precision']:.4f}；ROC-AUC {result['roc_auc']:.4f}。风险等级与追踪扩展阈值另有用途。")
    with st.expander('完整实验、参考论文与比赛讲解'):
        path = ROOT / 'docs/RISK_SCORING_REDESIGN.md'
        if path.exists():
            st.download_button('下载风险评分设计与实验文档', path.read_text(encoding='utf-8'), 'risk_scoring_design.md', 'text/markdown')
        st.caption('测试集此前已被查看，本轮是重复基准评估；地址特征属于生命周期快照，尚未完成外部数据泛化验证。')
    st.divider()
