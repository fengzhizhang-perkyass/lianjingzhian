import { displaySummary } from '../display-metadata.js';
import {
  $,
  $$,
  escape,
  number,
  table,
  json,
  metric
} from '../dom.js';
import {
  plot,
  evidencePathFigure,
  clearPlot,
  clearPlots
} from '../charts.js';
const sections = ['overview', 'behavior', 'graph', 'paths', 'assessment', 'limitations'];
const headings = ['地址风险概述', '行为风险证据', '图结构风险证据', '可疑关联路径', '综合研判', '风险提示与系统局限'];
const kinds = {
  address_model_risk: '模型地址风险',
  diagnostic_score: '单组诊断分',
  feature_attribution: '模型特征归因',
  graph_observation: '图结构观察',
  relation_path: '关系路径',
  path_node_risk: '路径节点风险',
  bridge_reason: '低分连接理由',
  search_boundary: '搜索范围',
  review_recommendation: '复核建议',
  limitation: '能力边界'
};
const units = {
  score_0_100: '风险分（0–100）',
  joint_tree_margin: '联合模型原始输出贡献',
  behavior_head_margin: '行为模型原始输出贡献',
  count: '计数',
  ratio_0_1: '比例（0–1）',
  directed_relations: '有向地址关系',
  search_checks: '关系检查次数',
  policy: '系统复核规则'
};
const statuses = {
  passed: '已通过',
  template: '模板核验',
  repaired: '修复后通过',
  local_fallback: '局部模板替换',
  coverage_added: '补充核心事实'
};
let currentRecord = null,
  selectedLabel = null;

function statementText(text) {
  return escape(text.replace(/\\([\\`*_{}\[\]()#+!|])/g, '$1').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
    .replace(/&amp;/g, '&'));
}
export function resetReport() {
  currentRecord = null;
  clearPlots('#evidence-content');
  $('#report-results').hidden = true;
  $('#report-empty').hidden = false;
  $('#report-error').textContent = '';
  $('#report-status').textContent = '';
  $('#fault-result').replaceChildren();
  $('#evidence-content').replaceChildren();
  $('#report-statements').replaceChildren();
}
export function renderReport(record) {
  currentRecord = record;
  const report = record.report;
  $('#report-empty').hidden = true;
  $('#report-results').hidden = false;
  $('#report-source').textContent = report.source === 'llm' ? 'LLM 组织声明 · 协议事实已核验' : '结构化证据模板 · 协议事实已核验';
  $('#report-id').textContent = record.report_id;
  $('#report-fallback').hidden = !report.fallback_reason;
  $('#report-fallback').textContent = report.fallback_reason || '';
  const audit = report.audit;
  $('#audit-metrics').innerHTML = [
    ['输出声明', audit.final_statement_count],
    ['候选问题', audit.candidate_error_count],
    ['修复声明', audit.repaired_count],
    ['核心事实覆盖', `${audit.covered_required_facts} / ${audit.required_fact_count}`]
  ].map(([label, value]) => `<div><strong>${escape(value)}</strong><span>${label}</span></div>`).join('');
  $('#report-statements').innerHTML = sections.map((section, i) =>
    `<section class="report-section"><h3>${i+1}. ${headings[i]}</h3>${report.statements.filter(s=>s.section===section).map(statement=>`<div class="claim-row" id="statement-${statement.citation_label}"><p>${statementText(statement.text)}</p><button class="citation" data-evidence="${statement.citation_label}" aria-label="${statement.citation_label}：定位声明证据" aria-pressed="false">${statement.citation_label}</button></div>`).join('')||'<p class="muted">当前证据不足：没有可用的已核验事实。</p>'}</section>`
  ).join('');
  $('#evidence-select').innerHTML = report.statements.map(statement =>
    `<option value="${statement.citation_label}">${statement.citation_label} · ${escape(report.fact_catalog.facts[statement.claim.fact_ids[0]].label)}</option>`
  ).join('');
  $$('[data-evidence]').forEach(button => button.addEventListener('click', () => {
    selectEvidence(button.dataset.evidence);
    if (innerWidth <= 800) {
      $('.evidence-panel').scrollIntoView({
        behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth',
        block: 'start'
      });
      $('#evidence-select').focus({
        preventScroll: true
      });
    }
  }));
  const base = '/api/reports/' + record.report_id;
  $('#report-downloads').innerHTML = [
    ['下载 Markdown', base + '/export?format=md'],
    ['下载 TXT', base + '/export?format=txt'],
    ['Evidence JSON', base + '/export?format=evidence'],
    ['完整审计包', base + '/bundle']
  ].map(([name, url]) =>
    `<a class="secondary" href="${url}" download>${name} <span aria-hidden="true">↓</span></a>`).join('');
  json('#audit-json', report.audit);
  json('#evidence-json', report.evidence_snapshot);
  json('#claims-json', report.claims_document);
  $('#fault-result').replaceChildren();
  const unavailable = !report.evidence_snapshot.trace_analysis.top_paths.length;
  $('#fault-kind option[value="path_score_as_risk"]').disabled = unavailable;
  if (unavailable && $('#fault-kind').value === 'path_score_as_risk') $('#fault-kind').value =
    'invented_amount';
  selectEvidence(report.statements[0]?.citation_label);
}
export function selectEvidence(label) {
  if (!currentRecord || !label) return;
  selectedLabel = label;
  const report = currentRecord.report,
    statement = report.statements.find(s => s.citation_label === label);
  if (!statement) return;
  const fact = report.fact_catalog.facts[statement.claim.fact_ids[0]],
    locator = fact.display_locator;
  $('#evidence-select').value = label;
  $$('[data-evidence]').forEach(button => {
    const active = button.dataset.evidence === label;
    button.setAttribute('aria-pressed', String(active));
    button.closest('.claim-row').classList.toggle('selected', active);
  });
  const container = $('#evidence-content');
  $$('.plot', container).forEach(clearPlot);
  container.innerHTML =
    `<p class="fact-label">${escape(label)} · ${escape(statuses[statement.status]||statement.status)}</p><h4>${escape(fact.label)}</h4><p class="muted">${escape(kinds[fact.fact_type])} · ${escape(units[fact.unit])}</p><pre>${escape(JSON.stringify(fact.subject,null,2))}</pre><div id="fact-data"></div><div class="source-pointers">${fact.source_pointers.map(p=>`<code class="source-pointer">${escape(p)}</code>`).join('')||'<p class="muted">系统复核/能力边界规则，不是链上事实。</p>'}</div><details><summary>源值与派生依据</summary><pre>${escape(JSON.stringify(displaySummary({source_values:fact.source_values,derivation:fact.derivation,fact_id:fact.fact_id}),null,2))}</pre></details><details><summary>原始 CSV 记录定位</summary>${fact.raw_source_locations?.length?`<pre>${escape(JSON.stringify(fact.raw_source_locations,null,2))}</pre><p class="muted">记录序号与物理行范围实际测量；关系记录不等于独立逐笔交易。</p>`:'<p class="muted">当前没有可用的直接原始 CSV 记录定位；仍可核对上方固定 Evidence 字段、特征与关系路径。</p>'}</details>`;
  if (locator.view === 'path' || locator.view === 'bridge') {
    const path = report.evidence_snapshot.trace_analysis.top_paths[locator.path_index];
    let edges = null,
      nodes = [];
    const hop = locator.hop;
    if (locator.view === 'bridge') {
      const witness = path.bridge_witnesses[locator.witness_index];
      edges = witness.edges;
      nodes = [...witness.bridge_nodes, witness.anchor_node];
    } else if (hop !== undefined) {
      nodes = [path.nodes[hop]];
      edges = path.nodes.slice(1).map((a, i) => [path.nodes[i], a]).filter((_, i) => i === hop - 1 || i ===
        hop);
    }
    $('#fact-data').innerHTML =
      '<div id="fact-path-chart" class="plot"></div><div id="fact-path-table" class="table-scroll"></div><p id="fact-path-id" class="muted"></p>';
    plot('#fact-path-chart', evidencePathFigure(path, edges, nodes));
    table('#fact-path-table', [{
      label: '跳数',
      key: 'hop'
    }, {
      label: '地址',
      key: 'address',
      mono: true
    }, {
      label: '原始风险',
      render: r => number(r.risk)
    }, {
      label: '当前定位',
      render: r => r.selected ? '← 当前证据' : ''
    }], path.nodes.map((address, i) => ({
      hop: i,
      address,
      risk: path.node_risks[i],
      selected: i === hop || (locator.hops || []).includes(i) || nodes.includes(address)
    })));
    $('#fact-path-id').textContent = `路径 ${path.path_id||'—'} · 证据 ${path.evidence_id||'—'}`;
  } else if (locator.view === 'feature') {
    $('#fact-data').innerHTML = '<div id="fact-feature" class="table-scroll"></div>';
    table('#fact-feature', Object.keys(fact.value).map(key => ({
      label: key,
      key,
      render: r => escape(typeof r[key] === 'number' ? number(r[key], 5) : r[key])
    })), [fact.value]);
  } else {
    $('#fact-data').innerHTML = typeof fact.value === 'number' ?
      `<div class="fact-value"><strong>${number(fact.value,4)}</strong><div>${escape(units[fact.unit])}</div></div>` :
      `<pre>${escape(typeof fact.value==='string'?fact.value:JSON.stringify(fact.value,null,2))}</pre>`;
  }
}
export function returnToStatement() {
  if (!selectedLabel) return;
  const row = $('#statement-' + selectedLabel);
  row?.scrollIntoView({
    behavior: 'instant',
    block: 'center'
  });
  $('button', row)?.focus({
    preventScroll: true
  });
}
export function renderFault(record) {
  const report = record.report,
    context = report.demonstration,
    audit = report.audit;
  $('#fault-result').innerHTML =
    `<p class="notice">模拟演示：${escape(context.injected_description)}</p><div class="metric-row">${metric('旧引用校验',context.legacy_accepted?'接受':'拒绝')}${metric('新协议拒绝',audit.candidate_error_count+' 条')}${metric('修复后保留',audit.initial_passed_preserved+' 条')}${metric('模拟调用',audit.api_calls+' 次')}</div><p>拒绝原因：${escape(audit.candidate_errors[0]?.error_code||'—')}</p><details><summary>注入声明与修复结果</summary><pre>${escape(JSON.stringify(displaySummary(context),null,2))}</pre><pre>${escape(JSON.stringify(displaySummary(audit),null,2))}</pre></details><a class="secondary" href="/api/reports/${record.report_id}/bundle" download>下载故障演示审计包</a>`;
}
