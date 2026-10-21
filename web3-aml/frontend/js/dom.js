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
export const levelName = level => ({
  LOW: '低风险',
  MEDIUM: '中风险',
  HIGH: '高风险',
  CRITICAL: '极高风险'
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
