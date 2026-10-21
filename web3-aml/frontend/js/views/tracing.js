import {
  $,
  escape,
  number,
  table,
  json
} from '../dom.js';
import {
  plot,
  pathFigure,
  clearPlot,
  clearPlots
} from '../charts.js';
import { renderNetwork, clearNetwork } from '../relation-network.js';
import { displaySummary } from '../display-metadata.js';
export function traceParameters() {
  return Object.fromEntries([...new FormData($('#trace-form')).entries()].map(([key, value]) => [key, Number(
    value)]));
}
export function setTraceDefaults(meta, long = false) {
  const defaults = {
    ...meta.defaults,
    ...(long ? meta.defaults.long_path_profile : {})
  };
  for (const [key, value] of Object.entries(defaults)) {
    const input = $(`[name="${key}"]`, $('#trace-form'));
    if (input) input.value = value;
  }
  $('#depth-output').textContent = defaults.max_depth + ' 跳';
  $('#mode-help').textContent = long ? '扩大连接跨度以核查远距离关联；完整到达风险锚点才保留。' : '从起点沿下游关系寻找风险锚点。';
}
export function resetTrace() {
  clearNetwork();
  clearPlots('#trace-results');
  $('#trace-chart').innerHTML =
    '<div class="graph-empty"><span aria-hidden="true">◇ ─ ◇ ─ ◇</span><h3>让关联路径浮现</h3><p>设置参数后运行关系追踪。</p></div>';
  $('#trace-results').hidden = true;
  $('#trace-stale').hidden = true;
  $('#graph-state').textContent = '等待追踪';
  $('#trace-version').textContent = '';
  $('#trace-error').textContent = '';
}
export function renderTrace(record) {
  const trace = record.result;
  $('#trace-mode').value = record.mode;
  for (const [key, value] of Object.entries(trace.config)) {
    const input = $(`[name="${key}"]`, $('#trace-form'));
    if (input) input.value = value;
  }
  $('#depth-output').textContent = trace.config.max_depth + ' 跳';
  $('#mode-help').textContent = record.mode === 'long' ? '扩大连接跨度以核查远距离关联；完整到达风险锚点才保留。' : '从起点沿下游关系寻找风险锚点。';
  $('#trace-results').hidden = false;
  $('#trace-stale').hidden = true;
  $('#graph-state').textContent = trace.top_paths.length + ' 条路径';
  $('#trace-version').textContent = '结果 ' + record.trace_id.slice(-8);
  const s = trace.statistics;
  $('#trace-statistics').innerHTML = [
    ['保留节点', s.visited_nodes],
    ['扫描候选', s.candidate_nodes],
    ['高风险节点', s.high_risk_nodes],
    ['到达深度', s.max_reached_depth]
  ].map(([label, value]) => `<div><strong>${escape(value)}</strong><span>${label}</span></div>`).join('');
  const budget = trace.search_budget,
    selection = trace.selection_analysis;
  $('#trace-budget').textContent = (budget ?
    `唯一关系边 ${selection.unique_edges} · 实际检查 ${budget.actual_edge_inspections} / ${budget.configured_limit} · 折叠重复前缀 ${selection.prefix_folding.length}。` :
    '') + ' 扫描候选与保留节点统计范围不同。' + (trace.anchor_index_fallback_reason || '');
  $('#trace-download').href = `/api/traces/${record.trace_id}/export`;
  $('#path-select').innerHTML = trace.top_paths.map((p, i) =>
    `<option value="${i}">路径 ${p.rank} · ${p.hop_count} 跳 · 排序分 ${number(p.path_score,4)}</option>`).join(
    '');
  table('#paths-table', [{
    label: '排名',
    key: 'rank'
  }, {
    label: '跳数',
    key: 'hop_count'
  }, {
    label: '搜索排序分',
    render: r => number(r.path_score, 4)
  }, {
    label: '关系路径',
    render: r => escape(r.nodes.join(' → '))
  }], trace.top_paths);
  json('#trace-json', trace);
  if (!trace.top_paths.length) {
    renderNetwork(record);
    $('#path-select').disabled = true;
    clearPlot('#path-chart');
    $('#path-table').textContent = '在当前搜索范围内未找到符合条件的关系路径。';
    $('#bridge-details').replaceChildren();
  } else {
    $('#path-select').disabled = false;
    const longest = trace.top_paths.reduce((best, path, i) => path.hop_count > trace.top_paths[best]
      .hop_count ? i : best, 0);
    $('#path-select').value = String(longest);
    selectPath(record, longest);
  }
}
export function selectPath(record, index) {
  const trace = record.result,
    path = trace.top_paths[index];
  if (!path) return;
  renderNetwork(record, path);
  plot('#path-chart', pathFigure(path, trace.config.risk_threshold));
  table('#path-table', [{
    label: '跳数',
    key: 'hop'
  }, {
    label: '完整地址',
    key: 'address',
    mono: true
  }, {
    label: '原始风险',
    render: r => number(r.risk)
  }, {
    label: '路径角色',
    key: 'role'
  }], path.nodes.map((address, i) => ({
    hop: i,
    address,
    risk: path.node_risks[i],
    role: i === 0 ? '起点' : path.node_risks[i] < trace.config.risk_threshold ? '低分连接' : '风险锚点'
  })));
  $('#bridge-details').innerHTML =
    `<p class="muted">路径编号 ${escape(path.path_id||'—')} · 证据编号 ${escape(path.evidence_id||'—')}。路径分是搜索优先级，不是洗钱概率；连线不是金额流动或交易时序。</p>` +
    (path.bridge_witnesses || []).map(w =>
      `<details><summary>低分连接见证 · ${w.bridge_nodes.length} 个连接节点</summary><p class="muted">${escape(w.edges.length?[w.edges[0][0],...w.edges.map(e=>e[1])].join(' → '):'无关系边')}</p><pre>${escape(JSON.stringify(displaySummary(w),null,2))}</pre></details>`
    ).join('');
}
