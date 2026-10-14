"""Program-owned typed facts, RFC 6901 locators and frozen source snapshots."""
import copy
import hashlib
import json
import math
import re


def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def resolve_pointer(document, pointer):
    if pointer == '':
        return document
    if not isinstance(pointer,str) or not pointer.startswith('/'):
        raise ValueError('JSON Pointer must start with /')
    current = document
    for token in pointer[1:].split('/'):
        if re.search(r'~(?![01])',token):
            raise ValueError('Invalid JSON Pointer escape')
        token = token.replace('~1','/').replace('~0','~')
        if isinstance(current,list):
            if not re.fullmatch(r'0|[1-9][0-9]*',token):
                raise ValueError('Array index must be a nonnegative canonical integer')
            current = current[int(token)]
        elif isinstance(current,dict):
            current = current[token]
        else:
            raise ValueError('Cannot descend into scalar')
    return current


GRAPH_FIELDS = {
    'out_degree':('出度','count'),'in_degree':('入度','count'),
    'one_hop_neighbor_count':('一跳邻居数','count'),
    'one_hop_avg_risk':('一跳邻居平均风险','score_0_100'),
    'one_hop_high_risk_count':('一跳高风险邻居数','count'),
    'one_hop_high_risk_ratio':('一跳高风险邻居比例','ratio_0_1'),
    'two_hop_avg_risk':('二跳采样平均风险','score_0_100'),
    'two_hop_high_risk_ratio':('二跳采样高风险比例','ratio_0_1'),
    'two_hop_sample_count':('二跳采样节点数','count')}
POLICIES = {
    'human_review': '建议结合模型评分、模型归因、图结构与关系路径进行人工复核。',
    'model_boundary': '地址风险是模型预测，不能作为犯罪认定或真实身份结论。',
    'relation_boundary': '路径表示地址有向关系，不能据此认定同一笔资金连续流动、交易金额或逐笔时间。',
    'search_boundary': '搜索受深度与预算限制，未展示关系不代表该关系不存在。',
    'attribution_boundary': '模型归因解释相应模型原始输出，贡献不具有因果含义；单组评分用于诊断。',
    'calibration_boundary': '校准依赖已知标签验证集，不能保证未知标签地址的概率校准。',
    'snapshot_boundary': '公开数据可能缺少或包含未知标签；地址生命周期汇总特征不等同历史时点实时预测。'}


class FactCatalog:
    def __init__(self,evidence,config,graph=None,risk_scores=None,source_index=None):
        self.evidence = copy.deepcopy(evidence)
        self.evidence_hash = digest(self.evidence)
        self.config = dict(config)
        self.source_index=source_index
        self.facts = {}
        self.provenance = {k:self.evidence.get('meta',{}).get(k) for k in
            ('dataset_fingerprint','risk_revision','scoring_revision')}
        self.provenance['tracing_revision'] = self.evidence.get('trace_analysis',{}).get('provenance',{}).get('tracing_revision')
        self.graph_checked = graph is not None
        self.risks_checked = risk_scores is not None
        if graph is not None and graph.metadata.get('fingerprint') and self.provenance['dataset_fingerprint']!=graph.metadata['fingerprint']:
            raise ValueError('Graph and evidence fingerprint mismatch')
        self._build(graph,risk_scores)
        self.catalog_hash = digest(self.facts)

    def _add(self,kind,section,pointers,subject,unit,label,locator,required=False,
             value=None,policy_key=None,derived=None):
        sources = {p:copy.deepcopy(resolve_pointer(self.evidence,p)) for p in pointers}
        if value is None:
            value = next(iter(sources.values())) if len(sources)==1 else copy.deepcopy(sources)
        if len(self.facts) >= self.config['max_facts']:
            raise ValueError('Fact catalog exceeds configured limit')
        key = digest([self.provenance,kind,pointers,subject,value,policy_key])[:16]
        fact = {'fact_id':'E_'+key,'fact_type':kind,'section':section,
            'subject':copy.deepcopy(subject),'unit':unit,'label':label,'value':copy.deepcopy(value),
            'source_pointers':pointers,'source_values':sources,'source_version':copy.deepcopy(self.provenance),
            'display_locator':locator,'required':required,'policy_key':policy_key,'derivation':derived,
            'capabilities':['model_prediction'] if kind in ('address_model_risk','path_node_risk','diagnostic_score')
                else ['directed_relations'] if kind in ('relation_path','bridge_reason')
                else ['model_attribution'] if kind=='feature_attribution' else ['descriptive_evidence']}
        fact['raw_source_locations']=[]
        if self.source_index is not None:
            if kind=='feature_attribution' and subject.get('group')=='behavior':
                column=value.get('raw_feature',value.get('feature'))
                location=self.source_index.feature(subject['address_id'],column,value.get('feature_value',value.get('value')))
                if location: fact['raw_source_locations'].append(location)
            elif kind=='relation_path':
                fact['raw_source_locations']=self.source_index.edges(list(zip(value['nodes'],value['nodes'][1:])))
            elif kind=='bridge_reason':
                fact['raw_source_locations']=self.source_index.edges(value['witness']['edges'])
        self.facts[fact['fact_id']] = fact

    def _build(self,graph,risk_scores):
        e = self.evidence
        target = e.get('target',{}).get('address_id','UNAVAILABLE')
        subject = {'address_id':target}
        risk = e.get('risk_analysis',{})
        score = risk.get('overall_score')
        if score is not None:
            self._number(score,'score_0_100')
            if risk_scores is not None and (target not in risk_scores or score!=risk_scores[target]):
                raise ValueError('Target risk differs from frozen risk table')
            pointers = ['/risk_analysis/overall_score']
            if risk.get('risk_level') is not None: pointers.append('/risk_analysis/risk_level')
            self._add('address_model_risk','overview',pointers,subject,'score_0_100','综合模型风险',
                {'view':'address_risk','field':'overall_score'},True,
                {'score':score,'risk_level':risk.get('risk_level','UNAVAILABLE')})
        scoring = e.get('scoring_analysis') or {}
        for group,value in scoring.get('route_scores',{}).items():
            if group not in ('behavior','context','structure'): continue
            self._number(value,'score_0_100')
            self._add('diagnostic_score','overview',[f'/scoring_analysis/route_scores/{group}'],
                {**subject,'group':group},'score_0_100',{'behavior':'行为画像','context':'方向邻域偏离','structure':'有向结构角色'}[group],
                {'view':'address_risk','group':group},True)
        if scoring:
            groups = scoring.get('evidence',{})
            for group,features in groups.items():
                if group not in ('behavior','context','structure'): continue
                for i,item in enumerate(features[:self.config['feature_top_k']]):
                    if item.get('contribution') is None: continue
                    self._number(item['contribution'],'raw_margin')
                    self._add('feature_attribution','behavior' if group=='behavior' else 'graph',
                        [f'/scoring_analysis/evidence/{group}/{i}'],
                        {**subject,'group':group,'feature_index':i,'feature':item.get('feature','unknown')},
                        'joint_tree_margin','联合模型特征归因',
                        {'view':'feature','group':group,'row':i},i==0)
        else:
            for i,item in enumerate(e.get('behavior_evidence',[])[:self.config['feature_top_k']]):
                if item.get('contribution') is None: continue
                self._number(item['contribution'],'raw_margin')
                self._add('feature_attribution','behavior',[f'/behavior_evidence/{i}'],
                    {**subject,'group':'behavior','feature_index':i,'feature':item.get('feature','unknown')},
                    'behavior_head_margin','行为模型归因',{'view':'feature','group':'behavior','row':i},i==0)
        for name,(label,unit) in GRAPH_FIELDS.items():
            value = e.get('graph_evidence',{}).get(name)
            if value is None: continue
            self._number(value,unit)
            self._add('graph_observation','graph',[f'/graph_evidence/{name}'],subject,unit,label,
                {'view':'graph_stat','field':name},name in ('out_degree','in_degree','one_hop_avg_risk','one_hop_high_risk_ratio'))
        trace = e.get('trace_analysis',{})
        provenance = trace.get('provenance',{})
        for key,expected in [('risk_revision',self.provenance['risk_revision']),
                             ('dataset_fingerprint',self.provenance['dataset_fingerprint'])]:
            if expected is not None and provenance.get(key) is not None and expected!=provenance[key]:
                raise ValueError('Source version mismatch')
        for i,path in enumerate(trace.get('top_paths',[])):
            nodes,scores = path['nodes'],path['node_risks']
            if not nodes or nodes[0]!=target or len(nodes)!=len(set(nodes)) or len(nodes)!=len(scores):
                raise ValueError('Invalid relation path subjects')
            if path['hop_count'] != len(nodes)-1:
                raise ValueError('Path hop count mismatch')
            if score is not None and scores[0]!=score:
                raise ValueError('Path Seed risk differs from analyzed address risk')
            for value in scores: self._number(value,'score_0_100')
            if risk_scores is not None and any(a not in risk_scores or value!=risk_scores[a] for a,value in zip(nodes,scores)):
                raise ValueError('Path risk differs from frozen risk table')
            self._number(path['path_score'],'ratio_0_1')
            if graph is not None:
                for a,b in zip(nodes,nodes[1:]):
                    if b not in graph.out_neighbors(a): raise ValueError('Path edge absent from directed graph')
            path_id = path.get('path_id') or 'path_'+digest(nodes)[:16]
            path_subject = {'address_id':target,'path_id':path_id,'path_index':i}
            self._add('relation_path','paths',[f'/trace_analysis/top_paths/{i}'],path_subject,
                'directed_relations','有向关系路径',{'view':'path','path_index':i,'path_id':path_id},True)
            for j,(address,value) in enumerate(zip(nodes,scores)):
                self._add('path_node_risk','paths',[f'/trace_analysis/top_paths/{i}/node_risks/{j}',
                    f'/trace_analysis/top_paths/{i}/nodes/{j}'],
                    {'address_id':address,'path_id':path_id,'path_index':i,'hop':j},'score_0_100','路径节点原始风险',
                    {'view':'path','path_index':i,'path_id':path_id,'hop':j},False,{'address_id':address,'score':value})
            for j,witness in enumerate(path.get('bridge_witnesses',[])):
                edges = witness.get('edges',[])
                if not edges or any(tuple(edge) not in set(zip(nodes,nodes[1:])) for edge in edges):
                    raise ValueError('Bridge witness edge absent from path')
                chain = [edges[0][0]]+[edge[1] for edge in edges]
                if any(edges[k][1]!=edges[k+1][0] for k in range(len(edges)-1)):
                    raise ValueError('Disconnected bridge witness')
                if chain[1:-1] != witness.get('bridge_nodes') or chain[-1]!=witness.get('anchor_node'):
                    raise ValueError('Bridge witness subject mismatch')
                indices = [nodes.index(a) for a in chain]
                if indices!=list(range(indices[0],indices[0]+len(indices))) or witness.get('bridge_node')!=chain[1]:
                    raise ValueError('Bridge witness positions mismatch')
                threshold = trace.get('config',{}).get('risk_threshold')
                if threshold is not None and (any(scores[k]>=threshold for k in indices[1:-1]) or scores[indices[-1]]<threshold):
                    raise ValueError('Bridge anchor/connector risk mismatch')
                pointers = ([f'/trace_analysis/top_paths/{i}/bridge_witnesses/{j}']+
                    [f'/trace_analysis/top_paths/{i}/node_risks/{k}' for k in indices])
                self._add('bridge_reason','paths',pointers,{**path_subject,'witness_index':j},'directed_relations','低分连接见证',
                    {'view':'bridge','path_index':i,'path_id':path_id,'witness_index':j,'hops':indices},True,
                    {'witness':witness,'risks':dict(zip(chain,[scores[k] for k in indices]))},
                    derived='join witness nodes with frozen path risk positions')
        if trace.get('search_budget'):
            budget = trace['search_budget']
            if not 0 <= budget['actual_edge_inspections'] <= budget['configured_limit']:
                raise ValueError('Search budget inconsistent')
            self._add('search_boundary','paths',['/trace_analysis/search_budget'],subject,'search_checks','搜索边界',
                {'view':'search_budget'},True)
        for name,text in POLICIES.items():
            self._add('review_recommendation' if name=='human_review' else 'limitation',
                'assessment' if name=='human_review' else 'limitations',[],subject,'policy',name,
                {'view':'policy','policy_key':name},True,value=text,policy_key=name)

    @staticmethod
    def _number(value,unit):
        if isinstance(value,bool) or not isinstance(value,(float,int)) or not math.isfinite(value):
            raise ValueError('Fact must be a finite numeric value')
        if unit=='count' and (value<0 or int(value)!=value): raise ValueError('Invalid count')
        if unit=='score_0_100' and not 0<=value<=100: raise ValueError('Invalid score')
        if unit=='ratio_0_1' and not 0<=value<=1: raise ValueError('Invalid ratio')

    def verify(self):
        if digest(self.evidence)!=self.evidence_hash or digest(self.facts)!=self.catalog_hash:
            raise ValueError('Evidence/catalog integrity mismatch')
        for fact in self.facts.values():
            if any(resolve_pointer(self.evidence,p)!=v for p,v in fact['source_values'].items()):
                raise ValueError('Fact source mismatch')

    def wire(self):
        return {'schema_version':'fact_catalog_v1','evidence_hash':self.evidence_hash,
                'catalog_hash':self.catalog_hash,'provenance':copy.deepcopy(self.provenance),
                'relation_graph_checked':self.graph_checked,'facts':copy.deepcopy(self.facts)}
