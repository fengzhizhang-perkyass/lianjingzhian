HEADINGS = ["地址风险概述", "行为风险证据", "图结构风险证据", "可疑关联路径", "综合研判", "风险提示与系统局限"]


def number(value, digits=2):
    return "当前证据不足" if value is None else f"{value:.{digits}f}"


class TemplateReporter:
    def generate(self, evidence):
        risk = evidence["risk_analysis"]
        address = evidence["target"]["address_id"]
        sections = [f"分析地址：`{address}`。综合模型风险分 **{number(risk['overall_score'])}**，风险等级 **{risk['risk_level']}**。"
                    f"行为分支分数 {number(risk['behavior_score'])}，图分支分数 {number(risk['graph_score'])}。"
                    f"行为融合系数 {number(risk['behavior_weight'])}，图融合系数 {number(risk['graph_weight'])}。"]
        scoring = evidence.get('scoring_analysis')
        if scoring:
            routes = scoring['route_scores']
            sections[0] = (f"分析地址：`{address}`。综合模型风险分 **{number(risk['overall_score'])}**，风险等级 **{risk['risk_level']}**。"
                           f"模型为“{scoring['model_name']}”。行为画像单独评分 {number(routes['behavior'])}，"
                           f"方向邻域偏离单独评分 {number(routes['context'])}，有向结构角色单独评分 {number(routes['structure'])}。"
                           '联合模型输入三类特征，单类评分用于诊断。')
        behavior = evidence["behavior_evidence"]
        sections.append("\n".join(f"- `{item['feature']}`：原始值 {number(item['value'])}，行为 logit 的 IG 归因 {number(item['contribution'], 4)}"
                                    f"（{'提高' if (item['contribution'] or 0) >= 0 else '降低'}行为分支输出）。"
                                    for item in behavior) or "当前证据不足：没有可用的行为归因。")
        graph = evidence["graph_evidence"]
        sections.append(f"出度 {graph.get('out_degree', '未知')}，入度 {graph.get('in_degree', '未知')}；"
                        f"一跳邻居平均风险 {number(graph.get('one_hop_avg_risk'))}，"
                        f"高风险邻居比例 {number(graph.get('one_hop_high_risk_ratio'))}。"
                        f"二跳采样平均风险 {number(graph.get('two_hop_avg_risk'))}。"
                        "这些指标描述图结构关联，不证明共同控制或资金归属。")
        paths = evidence["trace_analysis"].get("top_paths", [])
        sections.append("\n".join(f"- 路径 {item['rank']}：{' → '.join('`'+str(a)+'`' for a in item['nodes'])}；"
                                    f"搜索排序分 {number(item['path_score'], 4)}。" for item in paths)
                        or "当前证据不足：当前搜索配置下没有保留可疑下游路径。")
        trace = evidence['trace_analysis']
        if trace.get('search_budget'):
            budget = trace['search_budget']
            sections[-1] += (f"\n\n边访问预算 {budget['configured_limit']}，实际检查 {budget['actual_edge_inspections']}；"
                             f"停止原因 `{budget['stop_reason']}`。")
            for path in paths:
                sections[-1] += f"\n- 路径证据 `{path['evidence_id']}`，字段 `trace_analysis.top_paths.{path['rank']-1}`。"
                for witness in path.get('bridge_witnesses',[]):
                    sections[-1] += (f"\n  低分中间连接 `{witness['bridge_node']}` 因存在真实下游关系至 "
                        f"`{witness['anchor_node']}` 被保留；完整连接段包含 {len(witness.get('bridge_nodes',[witness['bridge_node']]))} 个低分节点，原始地址风险不变。")
        sections.append("建议结合模型预测、行为归因、图结构关联与搜索路径进行人工复核。"
                        "路径分数用于候选排序，不是洗钱概率。当前证据不足以认定犯罪事实或地址所有者身份。")
        investigation = evidence.get("investigation_analysis")
        if investigation:
            experts = investigation["expert_scores"]
            sections[-1] += (f"\n\n调查优先级 {number(investigation['priority_score'])}，复核状态为“{investigation['review_status']}”。"
                            f"独立 GraphSAGE 专家分数 {number(experts['graphsage'])}，双线路专家 {number(experts['dual_view'])}，"
                            f"拓扑增强树专家 {number(experts['topology_tree'])}。"
                            "专家依据各自验证集告警阈值形成共识或分歧；分歧不等于预测错误。")
            sections[-1] += "\n\n拓扑树专家的主要证据：\n"+"\n".join(
                f"- `{item['feature']}`：模型输入值 {number(item['model_input_value'], 4)}，TreeSHAP 贡献 {number(item['contribution'], 4)}。"
                for item in investigation.get("topology_evidence", []))
        sections.append("\n".join("- "+item for item in evidence["limitations"]))
        if scoring:
            sections[1] = '\n'.join(f"- `{item['feature']}`：原始值 {number(item['feature_value'])}，联合模型 TreeSHAP 贡献 {number(item['contribution'], 4)}。"
                                    for item in scoring['evidence']['behavior']) or '当前证据不足。'
            for group in ['context', 'structure']:
                sections[2] += '\n\n'+('方向邻域偏离' if group == 'context' else '有向结构角色')+'证据：\n'+'\n'.join(
                    f"- `{item['feature']}`：模型输入 {number(item['model_input_value'], 4)}，联合模型 TreeSHAP 贡献 {number(item['contribution'], 4)}。"
                    for item in scoring['evidence'][group])
            sections[4] += '\n\n三类证据对联合树原始输出的贡献：\n'+'\n'.join(
                f"- {group['label']}：{number(group['contribution'], 4)}。" for group in scoring['groups'])
        report = "# Web3 AML 风险分析报告\n\n" + "\n\n".join(f"## {i+1}. {heading}\n\n{section}" for i, (heading, section) in enumerate(zip(HEADINGS, sections)))
        return {"markdown": report, "source": "template", "fallback_reason": None}
