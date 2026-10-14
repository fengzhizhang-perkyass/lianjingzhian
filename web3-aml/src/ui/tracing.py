import json
import pandas as pd
import streamlit as st
from src.ui.runtime import get_service
from src.ui.widgets import relation_graph
from src.ui.path_detail import render_path_detail
from src.utils.io import ROOT, read_json


def clear_result():
    st.session_state.pop('trace', None)
    st.session_state.pop('report', None)


def open_long_case(address):
    st.session_state['active_address'] = address
    st.session_state['address_input'] = address
    st.session_state['trace_mode'] = '长链关联核查'
    clear_result()


def render(address):
    st.title("可疑关系链追踪")
    st.code(address, language=None)
    service = get_service()
    defaults = dict(service.tracer.config)
    advanced = defaults.get('method') == 'budgeted'
    st.write("沿真实下游关系寻找风险锚点，保留有见证的低分连接，优先展示新增关系证据。" if advanced else
             "沿下游有向关系扩展，按地址风险、邻域风险和度数惩罚筛选候选路径。")
    long_profile = defaults.get('long_path_profile')
    if long_profile:
        mode = st.radio('追踪模式',['快速风险筛查','长链关联核查'],horizontal=True,
                        key='trace_mode',on_change=clear_result)
        if mode == '长链关联核查':
            defaults.update(long_profile)
            st.info('扩大连接跨度以核查远距离关联。完整到达风险锚点才保留；长链可能包含大量低分地址，不等于洗钱资金链。')
        case_file = ROOT/defaults['long_path_cases']
        if case_file.exists():
            registry = read_json(case_file)
            if (registry['provenance'] == service.tracer.provenance
                    and registry['tracing_revision'] == service.tracer.revision):
                with st.expander('真实长链样例'):
                    cases = {c['address_id']:c for c in registry['cases']}
                    target = st.selectbox('选择关系样例',list(cases),
                        format_func=lambda a:f"{cases[a]['hops']} 跳 · {a}")
                    case = cases[target]
                    st.caption(f"起点风险 {case['seed_score']:.2f}，终点风险 {case['endpoint_score']:.2f}。样例经过挑选，不代表总体追踪效果。")
                    st.button('加载长链样例',on_click=open_long_case,args=(target,))
    with st.form("trace_parameters"):
        c1, c2, c3, c4 = st.columns(4)
        depth = c1.slider("最大深度", 1, 32 if long_profile else 8, defaults['max_depth'],
                          key='trace_depth_'+str(defaults['max_depth']))
        width = c2.slider("Beam 宽度", 1, 20, defaults['beam_width'])
        threshold = c3.slider("风险锚点门槛" if advanced else "最低候选风险", 0, 100, defaults['risk_threshold'])
        count = c4.slider("保留路径数", 1, 30, defaults['top_paths'])
        extra = {}
        if advanced:
            with st.expander('搜索预算与连接范围'):
                limit = st.number_input('关系检查上限',min_value=100,max_value=10000,value=defaults['edge_budget'],step=100,
                    help='邻居遍历、连接见证和可选关联传播共享这个在线检查预算。')
                bridge = st.slider('最多连续低分连接节点',1,31 if long_profile else 3,defaults['max_bridge_nodes'],
                    key='trace_bridge_'+str(defaults['max_bridge_nodes']),
                    help='只有找到真实风险锚点才能保留；节点原始风险分不会提高。')
                extra = {'edge_budget':int(limit),'max_bridge_nodes':bridge}
        run = st.form_submit_button("运行关系链追踪", type="primary")
    if run:
        with st.spinner("正在搜索可疑下游关系…"):
            st.session_state["trace"] = get_service().trace(address,
                {"max_depth": depth, "beam_width": width, "risk_threshold": threshold, "top_paths": count,**extra})
        st.session_state.pop("report", None)
    trace = st.session_state.get("trace")
    if not trace or trace["seed_address"] != address:
        st.info("设置搜索参数后点击“运行关系链追踪”。没有路径时，可降低风险阈值或选择其他示例。")
        return
    statistics = trace["statistics"]
    for column, label, field in zip(st.columns(4), ["保留节点", "扫描候选" if advanced else "候选节点", "高风险节点", "到达深度"],
                                   ["visited_nodes", "candidate_nodes", "high_risk_nodes", "max_reached_depth"]):
        column.metric(label, statistics[field])
    if trace.get('search_budget'):
        budget = trace['search_budget']
        selection = trace['selection_analysis']
        for column,label,value in zip(st.columns(3),['唯一关系边','关系检查次数','折叠重复前缀'],
            [selection['unique_edges'],f"{budget['actual_edge_inspections']} / {budget['configured_limit']}",len(selection['prefix_folding'])]):
            column.metric(label,value)
        if trace.get('anchor_index_fallback_reason'):
            st.info(trace['anchor_index_fallback_reason'])
        st.caption('扫描候选统计邻接扫描发现的地址；保留节点还包含离线见证展开的地址，两者统计范围不同。')
    render_path_detail(trace)
    relation_graph(trace)
    st.subheader("Top-K 可疑路径")
    if not trace["top_paths"]:
        st.warning("当前配置下没有符合条件的下游路径。")
    else:
        st.dataframe(pd.DataFrame([{"排名": p["rank"], "关系路径": " → ".join(p["nodes"]),
                                    "跳数": p["hop_count"], "搜索排序分": p["path_score"]} for p in trace["top_paths"]]),
                     hide_index=True, width="stretch")
        for path in trace["top_paths"][:3]:
            with st.expander(f"路径 {path['rank']} · {path['hop_count']} 跳 · {path['path_score']:.4f}"):
                roles = ['起点' if i == 0 else '低分连接' if a in path.get('bridge_nodes',[]) else '风险锚点'
                         for i,a in enumerate(path['nodes'])]
                st.dataframe(pd.DataFrame({"地址": path["nodes"], "风险分": path["node_risks"],'路径角色':roles}), hide_index=True)
                if path.get('evidence_id'):
                    st.caption(f"路径证据：{path['evidence_id']}")
                for witness in path.get('bridge_witnesses',[]):
                    st.write('连接见证：'+' → '.join([witness['edges'][0][0]]+[edge[1] for edge in witness['edges']]))
    st.caption("路径分是搜索优先级，不是洗钱概率。保留节点、候选节点及剪枝节点按唯一地址计数。")
    st.download_button("下载追踪 JSON", json.dumps(trace, ensure_ascii=False, indent=2), "trace.json", "application/json")
