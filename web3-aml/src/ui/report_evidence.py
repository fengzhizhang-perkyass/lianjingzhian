"""Statement-to-source navigation with precise path/node/bridge highlighting."""
import io
import json
import zipfile
import hashlib
import pandas as pd
import streamlit as st
from src.report.claim_schema import SECTIONS
from src.report.template_reporter import HEADINGS
from src.ui.widgets import relation_graph


def select_evidence(key,label):
    st.session_state[key]=label


def evidence_view(fact,snapshot):
    st.markdown('**'+fact['label']+'**')
    kinds={'address_model_risk':'模型地址风险','diagnostic_score':'单组诊断分','feature_attribution':'模型特征归因',
           'graph_observation':'图结构观察','relation_path':'关系路径','path_node_risk':'路径节点风险',
           'bridge_reason':'低分连接理由','search_boundary':'搜索范围','review_recommendation':'复核建议','limitation':'能力边界'}
    units={'score_0_100':'风险分（0–100）','joint_tree_margin':'联合模型原始输出贡献','behavior_head_margin':'行为模型原始输出贡献',
           'count':'计数','ratio_0_1':'比例（0–1）','directed_relations':'有向地址关系','search_checks':'关系检查次数','policy':'系统复核规则'}
    st.caption(kinds[fact['fact_type']]+' · '+units[fact['unit']])
    st.json(fact['subject'],expanded=True)
    if fact['source_pointers']:
        for pointer in fact['source_pointers']: st.code(pointer,language=None)
    else:
        st.info('这是系统复核/能力边界规则，不是链上事实。')
    locator=fact['display_locator']
    if locator['view'] in ('path','bridge'):
        path=snapshot['trace_analysis']['top_paths'][locator['path_index']]
        hop=locator.get('hop')
        selected_edges=None
        selected_nodes=[]
        if locator['view']=='bridge':
            witness=path['bridge_witnesses'][locator['witness_index']]
            selected_edges=witness['edges'];selected_nodes=witness['bridge_nodes']+[witness['anchor_node']]
        elif hop is not None:
            selected_nodes=[path['nodes'][hop]]
            selected_edges=[edge for i,edge in enumerate(zip(path['nodes'],path['nodes'][1:])) if i in (hop-1,hop)]
        nodes=[]
        for i,(a,score) in enumerate(zip(path['nodes'],path['node_risks'])):
            level='LOW' if score<30 else 'MEDIUM' if score<60 else 'HIGH' if score<80 else 'CRITICAL'
            nodes.append({'address_id':a,'risk_score':score,'risk_level':level,'is_seed':i==0})
        trace={'seed_address':path['nodes'][0],'top_paths':[path],
            'subgraph':{'nodes':nodes,'edges':[{'src':a,'dst':b} for a,b in zip(path['nodes'],path['nodes'][1:])]}}
        relation_graph(trace,highlighted_edges=selected_edges,highlighted_nodes=selected_nodes)
        st.dataframe(pd.DataFrame({'跳数':range(len(path['nodes'])),'地址':path['nodes'],
            '原始风险':path['node_risks'],'当前定位':[i in locator.get('hops',[]) or i==hop for i in range(len(path['nodes']))]}),
            hide_index=True,width='stretch')
        st.caption('来源路径：'+path.get('path_id','legacy')+' · '+path.get('evidence_id','legacy'))
    elif locator['view']=='feature':
        st.dataframe(pd.DataFrame([fact['value']]),hide_index=True,width='stretch')
        st.caption(f"特征组 {locator['group']}，证据表第 {locator['row']} 行（从零计数）。")
    else:
        st.json(fact['value'],expanded=True)
    with st.expander('源值、版本与派生依据'):
        st.json({'source_values':fact['source_values'],'source_version':fact['source_version'],
                 'derivation':fact['derivation'],'fact_id':fact['fact_id']})
    with st.expander('原始CSV记录定位'):
        locations=fact.get('raw_source_locations',[])
        if locations:
            st.json(locations)
            st.caption('记录序号与物理行范围实际测量；关系记录不等于独立逐笔交易。哈希用于快照一致性核对。')
        else:
            st.info('该证据没有已索引的直接原始CSV记录；模型分数或派生特征仍可定位到固定Evidence字段。')


def bundle_zip(report):
    data=io.BytesIO()
    files={}
    with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,key in [('evidence.json','evidence_snapshot'),('fact_catalog.json','fact_catalog'),
            ('claims_raw.json','candidates'),('claims_validated.json','claims_document'),('audit.json','audit')]:
            files[name]=json.dumps(report[key],ensure_ascii=False,indent=2,allow_nan=False).encode('utf-8')
        files['report.md']=report['markdown'].encode('utf-8')
        for name,content in files.items():archive.writestr(name,content)
        manifest={'report_id':report['report_id'],'evidence_hash':report['audit']['evidence_hash'],
            'file_sha256':{name:hashlib.sha256(content).hexdigest() for name,content in files.items()},
            'integrity_scope':'unsigned local consistency manifest'}
        archive.writestr('manifest.json',json.dumps(manifest,ensure_ascii=False,indent=2))
    return data.getvalue()


def report_statements(report,selection_key):
    for section,heading in zip(SECTIONS,HEADINGS):
        st.subheader(heading)
        rows=[s for s in report['statements'] if s['section']==section]
        if not rows: st.info('当前证据不足：没有可用的已核验事实。')
        for statement in rows:
            text_column,button_column=st.columns([.84,.16])
            text_column.markdown(statement['text'])
            button_column.button(statement['citation_label'],key=report['report_id']+'_'+statement['claim']['claim_id'],
                help='定位此声明对应的证据',on_click=select_evidence,args=(selection_key,statement['citation_label']))


def report_evidence_panel(report,selection_key):
    st.subheader('证据定位')
    labels={s['citation_label']:s for s in report['statements']}
    facts=report['fact_catalog']['facts']
    chosen=st.selectbox('定位报告证据',list(labels),key=selection_key,
        format_func=lambda label:label+' · '+facts[labels[label]['claim']['fact_ids'][0]]['label'])
    statement=labels[chosen];fact=facts[statement['claim']['fact_ids'][0]]
    states={'passed':'已通过','template':'模板核验','repaired':'修复后通过','local_fallback':'局部模板替换','coverage_added':'补充核心事实'}
    st.caption(f"声明 {statement['claim']['claim_id']} · {states[statement['status']]}")
    evidence_view(fact,report['evidence_snapshot'])


def render(report):
    st.markdown('## Web3 AML 风险分析报告')
    audit=report['audit']
    for column,label,value in zip(st.columns(4),['输出声明','候选问题','修复声明','核心事实覆盖'],
        [audit['final_statement_count'],audit['candidate_error_count'],audit['repaired_count'],
         f"{audit['covered_required_facts']} / {audit['required_fact_count']}"]):
        column.metric(label,value)
    st.caption('核验范围是受约束声明协议；覆盖量不是报告可信概率。政策规则与链上证据分别标明。')
    statements=report['statements']; facts=report['fact_catalog']['facts']
    selection_key='report_evidence_'+report['report_id']
    st.session_state.setdefault(selection_key,statements[0]['citation_label'])
    left,right=st.columns([1.2,1],gap='large')
    with left:
        with st.container(height=700,border=True,key='report_text_'+report['report_id']):
            report_statements(report,selection_key)
    with right:
        with st.container(height=700,border=True,key='evidence_panel_'+report['report_id']+'_'+st.session_state[selection_key]):
            report_evidence_panel(report,selection_key)
    with st.expander('候选问题与修复记录'):
        st.json(report['audit'])
        st.json(report['candidates'])
    with st.expander('固定输入快照与结构化输出'):
        st.caption('报告编号：'+report['report_id'])
        st.code(report['audit']['evidence_hash'],language=None)
        st.json(report['claims_document'])
        st.json(report['evidence_snapshot'])
    st.download_button('下载完整审计包',bundle_zip(report),report['report_id']+'.zip','application/zip')


def render_fault_demo(report,service):
    with st.expander('核验机制演示（故障注入与模拟修复）'):
        st.info('以下候选由程序人为注入，修复响应使用模拟API，不是实际LLM的自然输出。')
        options={'path_score_as_risk':'路径分冒充地址风险','invented_amount':'编造中文金额','subject_swap':'地址主体错配'}
        available=list(options)
        if not report['evidence_snapshot']['trace_analysis'].get('top_paths'):available.remove('path_score_as_risk')
        if report['evidence_snapshot']['risk_analysis'].get('overall_score') is None:return
        selected=st.selectbox('选择故障类型',available,format_func=options.get)
        key='fault_demo_'+report['report_id']
        if st.button('运行核验演示'):
            from src.report.fault_demo import generate_fault_demo
            st.session_state[key]=generate_fault_demo(service.root,report,selected,service.graph,service.risks)
        demo=st.session_state.get(key)
        if not demo:return
        audit=demo['audit'];context=demo['demonstration']
        st.warning(context['injected_description'])
        for column,label,value in zip(st.columns(3),['旧引用校验','新协议拒绝','修复后保留正确声明'],
            ['接受此错误' if context['legacy_accepted'] else '拒绝此错误',
             '已拦截',
             f"{audit['initial_passed_preserved']} / {audit['initial_passed_count']}"]):
            column.metric(label,value)
        st.caption('拒绝原因：'+audit['candidate_errors'][0]['error_code'])
        before,after=st.columns(2)
        with before:
            st.markdown('**注入候选**');st.json(context['injected_claim'])
        with after:
            st.markdown('**通过复验的修复声明**');st.json(context['corrected_claim'])
        st.caption(f"受限模拟调用 {audit['api_calls']} 次，修复 {audit['repaired_count']} 条；原报告和源Evidence保持不变。")
        st.download_button('下载故障演示审计包',bundle_zip(demo),demo['report_id']+'.zip','application/zip')
