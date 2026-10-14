"""Only source-derived values and registered sentence forms reach the report."""
import html
import re
from src.report.claim_schema import SECTIONS
from src.report.template_reporter import HEADINGS


def safe(value):
    text = html.escape(str(value),quote=False)
    return re.sub(r'([\\`*_{}\[\]()#+!|])',r'\\\1',text).replace('\n',' ')


def number(value,digits=2):
    return f'{value:.{digits}f}' if isinstance(value,float) else str(value)


def render_fact(fact,config):
    v,s,t = fact['value'],fact['subject'],fact['fact_type']
    d = config['score_digits']
    if t=='address_model_risk':
        return f"地址 {safe(s['address_id'])} 的综合模型风险为 {number(v['score'],d)} / 100，等级 {safe(v['risk_level'])}。这是模型预测。"
    if t=='diagnostic_score':
        return f"{safe(fact['label'])}单组诊断分为 {number(v,d)} / 100，用于解释证据职责，综合评分由联合模型产生。"
    if t=='feature_attribution':
        raw = v.get('feature_value',v.get('value'))
        model_input = v.get('model_input_value')
        value_text = f"原始值 {number(raw,config['attribution_digits'])}" if raw is not None else (
            f"模型输入值 {number(model_input,config['attribution_digits'])}" if model_input is not None else '特征原值未提供')
        method = '联合模型 TreeSHAP' if fact['unit']=='joint_tree_margin' else '行为模型归因'
        return f"{safe(s['feature'])}：{value_text}，{method}贡献 {number(v['contribution'],config['attribution_digits'])}；贡献解释模型原始输出。"
    if t=='graph_observation':
        value = number(v,4 if fact['unit']=='ratio_0_1' else d)
        return f"{safe(fact['label'])}为 {value}，描述图结构关联。"
    if t=='relation_path':
        nodes = v['nodes']
        if len(nodes)<=config['max_path_addresses_in_sentence']:
            sequence = ' → '.join(safe(a) for a in nodes)
        else:
            sequence = safe(nodes[0])+' → … → '+safe(nodes[-1])+'（完整地址见对应证据）'
        return (f"关系路径 {v['rank']}：{sequence}，共 {v['hop_count']} 跳、{len(nodes)} 个不同地址；"
                f"搜索排序分 {number(v['path_score'],4)}。路径表示有向关联，排序分用于候选排序。"
                + (f" 路径来源编号 {safe(v['evidence_id'])}。" if v.get('evidence_id') else ''))
    if t=='path_node_risk':
        return f"路径第 {s['hop']} 跳地址 {safe(v['address_id'])} 的原始风险为 {number(v['score'],d)} / 100。"
    if t=='bridge_reason':
        w = v['witness']; nodes=w['bridge_nodes']; first=nodes[0]; anchor=w['anchor_node']
        return (f"低分连接从 {safe(first)} 开始，共 {len(nodes)} 个连续低分节点；存在到 {safe(anchor)} 的完整有向连接见证。"
                f" 首个低分节点风险 {number(v['risks'][first],d)}，锚点原始风险 {number(v['risks'][anchor],d)}；节点原始评分保持不变。")
    if t=='search_boundary':
        return (f"在线关系检查上限 {v['configured_limit']}，实际检查 {v['actual_edge_inspections']}；"
                f"停止原因 {safe(v['stop_reason'])}。这是搜索范围记录。")
    if t in ('review_recommendation','limitation'):
        return safe(v)
    raise ValueError('Unsupported factual sentence type')


def render_report(records,catalog,config):
    catalog.verify()
    paragraphs = {s:[] for s in SECTIONS}
    statements = []
    for record in records:
        claim = record['claim']; fact = catalog.facts[claim['fact_ids'][0]]
        text = render_fact(fact,config)
        label = f'E{len(statements)+1:02d}'
        item = {**record,'text':text,'citation_label':label,
                'source_pointers':fact['source_pointers'],'display_locator':fact['display_locator']}
        statements.append(item)
        paragraphs[record['section']].append(f'- {text} [{label}](#evidence-{label.lower()})')
    for s in SECTIONS:
        if not paragraphs[s]: paragraphs[s].append('当前证据不足：该部分没有可用的已核验事实。')
    markdown = '# Web3 AML 风险分析报告\n\n'+'\n\n'.join(
        f'## {i+1}. {heading}\n\n'+'\n'.join(paragraphs[s]) for i,(s,heading) in enumerate(zip(SECTIONS,HEADINGS)))
    markdown += '\n\n## 证据定位索引\n\n'
    for statement in statements:
        label=statement['citation_label']; fact=catalog.facts[statement['claim']['fact_ids'][0]]
        pointers='、'.join('`'+p+'`' for p in fact['source_pointers']) or '系统边界规则：'+fact['policy_key']
        markdown += f'### evidence-{label.lower()}\n\n{label} · {fact["fact_id"]} · {pointers}\n\n'
    return markdown,statements
