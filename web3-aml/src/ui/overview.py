import pandas as pd
import streamlit as st
from src.utils.io import ROOT, read_json
from src.ui.runtime import get_service


def render():
    metadata = get_service().metadata
    st.title("Web3 反洗钱分析工作台")
    st.write("从地址风险到可疑关系路径，将模型结果组织为可复核的分析证据。")
    columns = st.columns(4)
    for column, title, value in zip(columns, ["地址节点", "已知标签", "未知标签", "有向关系边"],
        [metadata["num_nodes"], metadata["licit_count"]+metadata["illicit_count"], metadata["unknown_count"], metadata["num_edges"]]):
        column.metric(title, f"{value:,}")
    comparison = read_json(ROOT / "artifacts/metrics/comparison.json")
    active_metadata = get_service().predictor.metadata
    if active_metadata.get('model_kind') == 'evidence_tree':
        result = read_json(ROOT / active_metadata['metrics_path'])
        with st.container(border=True):
            st.subheader(active_metadata['model_name'])
            for col, label, value in zip(st.columns(4), ['测试 AP', '测试 F1', '测试 Recall', 'Top-500 命中率'],
                                        [result['pr_auc'], result['f1'], result['recall'], result['review']['top_500']['precision']]):
                col.metric(label, f'{value:.3f}' if label != 'Top-500 命中率' else f'{value:.1%}')
            st.write('行为画像识别地址自身模式，方向邻域偏离比较上下游行为，有向结构角色补充汇入与分出模式。三类特征联合评分，TreeSHAP 解释实际决策。')
            st.caption('预算指标只针对已知标签测试地址；完整消融和历史对照见模型评估页。')
    index = get_service().investigation
    investigation = ROOT / "artifacts/experiments" / (index.metadata["experiment"] if index is not None else "investigation_v1")
    if index is not None and (investigation / "findings.json").exists():
        findings = read_json(investigation / "findings.json")
        seed = findings["representative_seed"]
        scores = read_json(investigation / f"final/seed_{seed}/review_priority_test.json")
        with st.container(border=True):
            st.subheader("调查增强：从风险分到复核决策")
            c1, c2, c3 = st.columns(3)
            c1.metric("调查排序测试 AP", f"{scores['pr_auc']:.3f}")
            c2.metric("Top-500 命中率", f"{scores['review']['top_500']['precision']:.1%}")
            c3.metric("专家诊断", "共识 / 分歧")
            st.write("进入“调查优先队列”，按优先级、分歧或排序上调选择地址，再查看专家证据、关系路径与报告。")
            st.caption("预算命中率仅针对已知标签测试地址；全量调查队列不使用真实标签。完整结果在模型评估页。")
    dual = comparison["dual_view"]
    with st.expander('历史 Dual-View 对照', expanded=active_metadata.get('model_kind') != 'evidence_tree'):
        st.subheader("Dual-View 模型表现")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("测试 F1", f"{dual['f1']:.3f}")
        c2.metric("测试 Recall", f"{dual['recall']:.3f}")
        c3.metric("测试 PR-AUC", f"{dual['pr_auc']:.3f}")
        c4.metric("模型版本", dual.get("model_version", "V1"))
        st.caption("阈值与温度参数仅在验证集选择；测试集用于最终评估。")
    st.subheader("完整分析流程")
    st.graphviz_chart('digraph { rankdir=LR; node [shape=box, style="rounded,filled", fillcolor="#EFF6FF", color="#1E40AF", fontname="Microsoft YaHei"]; "Elliptic++" -> "地址风险评分" -> "资金关系追踪" -> "可解释报告"; }')
    left, right = st.columns(2)
    with left, st.container(border=True):
        st.subheader("开始一次地址分析")
        st.write("在左侧选择高风险、低风险或未知高风险示例，或输入数据集内的地址 / 节点 ID。")
        st.write("依次查看风险与证据、运行关系链追踪，再生成分析报告。")
    with right, st.container(border=True):
        st.subheader("分析边界")
        st.write("评分用于筛选复核对象；路径表示地址关系关联。系统不输出犯罪认定、真实身份或精确金额归属。")
        st.caption(f"数据集：{metadata['dataset']} · 划分：{metadata['split']['method']} · 随机种子：{get_service().predictor.metadata['seed']}")
