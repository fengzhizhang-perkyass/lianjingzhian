import { displaySummary } from './display-metadata.js';
export const $ = (selector, root = document) => root.querySelector(selector);
export const $$ = (selector, root = document) => [...root.querySelectorAll(selector)];
export const escape = value => String(value ?? '').replace(/[&<>"']/g, char => ({
  '&': '&amp;',
  '<': '&lt;',
  '>': '&gt;',
  '"': '&quot;',
  "'": '&#39;'
} [char]));
export const number = (value, digits = 2) => value === null || value === undefined ? '—' : Number(value)
  .toLocaleString('zh-CN', {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits
  });
export const riskScore = value => {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const score = Number(value);
  return score < 100 && score.toFixed(2) === '100.00' ? '>99.99' : number(score);
};
export const preciseRiskScore = value => value === null || value === undefined ? '—' : String(Number(value));
export function riskScoreHTML(value) {
  if (value === null || value === undefined || !Number.isFinite(Number(value))) return '—';
  const exact = preciseRiskScore(value), label = riskScore(value);
  return `<details class="risk-score-detail"><summary title="精确风险分：${escape(exact)} / 100" aria-label="风险分 ${escape(label)}，查看精确分数"><span>${escape(label)}</span></summary><span class="risk-score-exact">精确风险分：<b>${escape(exact)}</b> / 100<br><small>风险等级按实际分数划分。</small></span></details>`;
}
export const riskLevelRanges = [
  ['LOW', '低风险', '0 ≤ 分数 < 30'], ['MEDIUM', '中风险', '30 ≤ 分数 < 60'],
  ['HIGH', '高风险', '60 ≤ 分数 < 80'], ['CRITICAL', '极高风险', '80 ≤ 分数 ≤ 100']
];
export const riskLevelsHTML = () => `<details class="risk-level-guide"><summary>风险等级说明</summary><div>${riskLevelRanges.map(([level,label,range])=>`<span><b class="risk-badge ${level}">${label}</b><span>${escape(range)}</span></span>`).join('')}<small>等级按未四舍五入的实际综合风险分判定。</small></div></details>`;
if (typeof document !== 'undefined') document.addEventListener('click', event => {
  document.querySelectorAll('.risk-score-detail[open]').forEach(detail => {
    if (!detail.contains(event.target)) detail.open = false;
  });
});
export const levelName = level => ({
  LOW: '低风险',
  MEDIUM: '中风险',
  HIGH: '高风险',
  CRITICAL: '极高风险',
  UNSCORED: '未评分',
  UNAVAILABLE: '未评分'
} [level] || level);
export function json(target, value) {
  $(target).textContent = JSON.stringify(displaySummary(value), null, 2);
}
export function table(target, columns, rows) {
  const el = typeof target === 'string' ? $(target) : target;
  el.innerHTML = rows.length ?
    `<table><thead><tr>${columns.map(c=>`<th scope="col">${escape(c.label)}</th>`).join('')}</tr></thead><tbody>${rows.map((row,index)=>`<tr>${columns.map(c=>`<td class="${c.mono?'address-cell':''}">${c.render ? c.render(row,index) : escape(row[c.key])}</td>`).join('')}</tr>`).join('')}</tbody></table>` :
    '<p class="muted">当前没有可展示的记录。</p>';
}
let toastTimer;
export function toast(message) {
  if (document.body.dataset.page !== 'workspace') return;
  $('#toast').textContent = message;
  $('#toast').hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => $('#toast').hidden = true, 3500);
}
export function busy(button, loading, label) {
  button.disabled = loading;
  button.setAttribute('aria-busy', String(loading));
  if (label) button.textContent = label;
}
export const metric = (label, value) =>
  `<div class="mini-metric"><strong>${escape(value)}</strong><span>${escape(label)}</span></div>`;
