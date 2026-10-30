import { riskScoreHTML, riskLevelsHTML, $, escape, number, levelName, table, json, metric } from '../dom.js';
import { plot, basicFigure, clearPlots } from '../charts.js';
import { publicText } from '../display-metadata.js';

const responsibilities={behavior:'描述地址自身的交易规模、频率和活跃习惯。',context:'描述地址与关联地址之间的行为差异。',structure:'描述资金收支方向、汇聚分散情况及关联交易属性。'};
const labels={behavior:'交易行为画像',context:'邻域行为偏离',structure:'资金流转特征'};
const signed=x=>(x>=0?'+':'')+number(x,4);
function contributionFigure(groups,title='模型原始输出贡献') {
  const f=basicFigure([{type:'bar',orientation:'h',x:groups.map(x=>x.contribution),y:groups.map(x=>publicText(x.label)),marker:{color:groups.map(x=>x.contribution>=0?'#C45263':'#3979B7')}}]);
  f.layout.height=270;f.layout.xaxis={title:{text:title}};f.layout.yaxis={autorange:'reversed',automargin:true};return f;
}
function featurePanels(target, groups, evidence, prefix, branchLabel='当前模型') {
  $(target).innerHTML=groups.map((g,i)=>`<details class="detail-panel"><summary>${escape(publicText(g.label))}证据 <span>${escape(branchLabel)}的真实特征值与贡献</span></summary><div id="${prefix}-chart-${i}" class="plot"></div><div id="${prefix}-table-${i}" class="table-scroll"></div></details>`).join('');
  groups.forEach((g,i)=>{
    const items=evidence?.[g.key]||[];
    table(`#${prefix}-table-${i}`,[{label:'特征',render:r=>escape(publicText(r.feature))},{label:'原始值',render:r=>number(r.feature_value,5)},{label:'模型输入值',render:r=>number(r.model_input_value,5)},{label:'原始输出贡献',render:r=>number(r.contribution,5)}],items);
    const f=basicFigure([{x:items.map(x=>x.contribution),y:items.map(x=>publicText(x.feature)),orientation:'h',type:'bar',marker:{color:items.map(x=>x.contribution>=0?'#C45263':'#3979B7')}}]);
    f.layout.yaxis={autorange:'reversed',automargin:true};f.layout.xaxis={title:{text:branchLabel+'原始输出贡献（logit）'}};f.layout.height=Math.max(260,items.length*45+90);
    plot(`#${prefix}-chart-${i}`,f);
  });
}
function waterfall(scoring,groups) {
  const f=basicFigure([{type:'waterfall',x:['模型基准',...groups.map(g=>publicText(g.label)),'模型原始输出'],y:[scoring.base_value,...groups.map(g=>g.contribution),0],measure:['absolute',...groups.map(()=> 'relative'),'total'],increasing:{marker:{color:'#C45263'}},decreasing:{marker:{color:'#3979B7'}}}]);
  f.layout.xaxis={automargin:true};f.layout.yaxis={title:{text:'原始输出（logit）'}};return f;
}
export function renderRisk(record) {
  const a=record.analysis,s=a.scoring_analysis,r=a.risk,dual=s.kind==='dual_view';
  clearPlots('#risk-results');
  $('#risk-empty').hidden=true;$('#risk-results').hidden=false;
  $('#overall-score').innerHTML=riskScoreHTML(r.overall_score);
  $('#risk-level-guide').innerHTML=riskLevelsHTML();
  $('#risk-level').textContent=levelName(r.risk_level);$('#risk-level').className='risk-badge '+r.risk_level;
  $('#risk-marker').style.left=`${Math.max(0,Math.min(100,r.overall_score))}%`;
  $('#risk-model').textContent=dual?'SA-DCF · 结构–属性双视图协同融合':'多维证据风险识别';
  $('#contribution-target').textContent=dual?'联合分支的真实归因':'三类证据的真实归因';
  const groups=(s.groups||[]).map(g=>({...g,label:dual?publicText(g.label):(labels[g.key]||publicText(g.label))}));
  plot('#contribution-chart',contributionFigure(groups,dual?'联合分支原始输出贡献（logit）':'模型原始输出贡献（logit）'));
  plot('#waterfall-chart',waterfall(s,groups));
  $('#calibration-note').textContent=dual?'此图解释联合模型的原始输出；最终综合风险按已核验的评分流程给出。特征贡献不是最终概率的增量。':`基准与各组贡献共同重建模型原始输出，再转换为风险分。加性核对误差 ${number(s.additivity_residual,10)}；各组不是独立风险评分。`;
  $('#ethereum-views').hidden=!dual;
  if(!dual){
    $('#route-scores').innerHTML=groups.map(g=>`<article class="route-item"><header><h3>${escape(g.label)}</h3><strong>${signed(g.contribution)}</strong></header><span class="contribution">对模型原始输出的贡献</span><p>${escape(responsibilities[g.key]||g.responsibility||'')}</p></article>`).join('');
    $('#ethereum-views').replaceChildren();
    featurePanels('#feature-groups',groups,s.evidence,'btc-feature');
  } else {
    const branches=s.branches||[],summary=s.structure_summary||{},graph=a.graph_evidence||{};
    $('#route-scores').innerHTML=`<article class="route-item"><header><h3>交易属性画像</h3><strong>56维</strong></header><p>收支规模、交易节奏、活跃习惯与交易对手统计。</p></article><article class="route-item"><header><h3>交易结构表征</h3><strong>${escape(summary.dimensions||32)}维</strong></header><p>有向交易关系、金额与交互次数共同形成账户上下文。</p></article><article class="route-item"><header><h3>双视图融合结果</h3><strong>协同研判</strong></header><p>结构与属性证据共同形成综合风险判断。</p></article>`;
    $('#ethereum-views').innerHTML=`<article class="panel structure-summary"><div class="panel-heading"><h3>当前地址的交易结构</h3><span>真实观察记录</span></div><div class="metric-row">${[['转出关联',graph.out_degree],['转入关联',graph.in_degree],['观测交易数',summary.observed_transaction_count],['交易对手数',summary.observed_counterparty_count],['结构表示维度',summary.dimensions||32]].map(([l,v])=>metric(l,number(v,0))).join('')}</div><p>图结构编码器学习交易对手、交互方向、金额和次数的上下文，将中心账户表示为32维潜在特征。</p>${summary.counterparty_preview?.length?`<details class="observed-peers"><summary>查看真实观测交易对手摘录</summary><div class="peer-addresses">${summary.counterparty_preview.map(peer=>`<code>${escape(typeof peer==='string'?peer:peer.address_id||peer.address)}</code>`).join('')}</div><p class="muted">摘录来自观测关系图，不是注意力权重或节点归因。</p></details>`:''}</article><div id="branch-explanations"></div>`;
    $('#feature-groups').replaceChildren();
    $('#branch-explanations').innerHTML=branches.map((b,i)=>`<details class="detail-panel branch-explanation"><summary>${b.key==='attribute'?'属性分支':'联合分支'}的真实解释 <span>原始输出贡献，加性核对误差 ${number(b.additivity_residual,10)}</span></summary><div id="branch-groups-${i}" class="plot"></div><div id="branch-features-${i}"></div></details>`).join('');
    branches.forEach((b,i)=>{plot(`#branch-groups-${i}`,contributionFigure(b.groups||[],(b.key==='attribute'?'属性分支':'联合分支')+'原始输出贡献（logit）'));featurePanels(`#branch-features-${i}`,b.groups||[],b.evidence,`eth-branch-${i}`,b.key==='attribute'?'属性分支':'联合分支');});
  }
  const graph=a.graph_evidence||{};
  $('#graph-statistics').innerHTML=[['出度',graph.out_degree],['入度',graph.in_degree],['已评分邻居平均风险',graph.one_hop_avg_risk],['高风险邻居比例',graph.one_hop_high_risk_ratio]].map(([l,v])=>metric(l,number(v))).join('');
  json('#analysis-json',a);
}
