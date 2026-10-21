import {
  $,
  $$,
  escape,
  number,
  levelName,
  table,
  json,
  metric
} from '../dom.js';
import {
  plot,
  basicFigure
} from '../charts.js';
import { modelDisplayName } from '../display-metadata.js';

export function renderRisk(record) {
  const analysis = record.analysis,
    scoring = analysis.scoring_analysis,
    risk = analysis.risk;
  $('#risk-empty').hidden = true;
  $('#risk-results').hidden = false;
  $('#overall-score').textContent = number(risk.overall_score);
  $('#risk-level').textContent = levelName(risk.risk_level) + ' · ' + risk.risk_level;
  $('#risk-level').className = 'risk-badge ' + risk.risk_level;
  $('#risk-marker').style.left = `${risk.overall_score}%`;
  $('#risk-model').textContent = modelDisplayName;
  plot('#contribution-chart', record.charts.contribution);
  plot('#waterfall-chart', record.charts.waterfall);
  $('#calibration-note').textContent =
    `温度参数 ${number(scoring.temperature,4)}；综合风险 = 100 × sigmoid(校准前 logit / 温度)。加性核对残差 ${scoring.additivity_residual}。三类诊断分不参与简单平均。`;
  $('#route-scores').innerHTML = scoring.groups.map(group =>
    `<article class="route-item"><header><h3>${escape(group.label)}</h3><strong>${number(scoring.route_scores[group.key])}</strong></header><span class="contribution">单类诊断 · 联合输出贡献 ${group.contribution>=0?'+':''}${number(group.contribution,4)}</span><p>${escape(group.responsibility)}</p></article>`
  ).join('');
  $('#feature-groups').innerHTML = scoring.groups.map(group =>
    `<details class="detail-panel"><summary>${escape(group.label)}证据 <span>查看特征值与对联合模型的贡献</span></summary><div id="features-chart-${group.key}" class="plot"></div><div id="features-${group.key}" class="table-scroll"></div></details>`
  ).join('');
  for (const group of scoring.groups) {
    const items = scoring.evidence[group.key];
    table('#features-' + group.key, [{
      label: '特征',
      key: 'feature'
    }, {
      label: '地址原始值',
      render: r => number(r.feature_value, 5)
    }, {
      label: '模型输入值',
      render: r => number(r.model_input_value, 5)
    }, {
      label: '联合输出贡献',
      render: r => number(r.contribution, 5)
    }], items);
    const fig = basicFigure([{
      x: items.map(i => i.contribution),
      y: items.map(i => i.feature),
      orientation: 'h',
      type: 'bar',
      marker: {
        color: items.map(i => i.contribution >= 0 ? '#B91C1C' : '#4E65F5')
      }
    }]);
    fig.layout.yaxis = {
      autorange: 'reversed',
      automargin: true
    };
    fig.layout.xaxis = {
      title: {
        text: '联合模型 TreeSHAP 贡献'
      }
    };
    plot('#features-chart-' + group.key, fig);
  }
  const graph = analysis.graph_evidence;
  $('#graph-statistics').innerHTML = [
    ['出度', graph.out_degree],
    ['入度', graph.in_degree],
    ['一跳平均风险', graph.one_hop_avg_risk],
    ['高风险邻居比例', graph.one_hop_high_risk_ratio]
  ].map(([label, value]) => metric(label, number(value))).join('');
  json('#analysis-json', analysis);
}
