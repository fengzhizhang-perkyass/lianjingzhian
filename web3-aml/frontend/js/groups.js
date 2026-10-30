import { $, escape, number } from './dom.js';
import { request } from './api.js';
import { state, datasetContext } from './state.js';
import { loadNetworkGroup, collapseNetworkGroup, expandNetworkGroup, clearGroupHighlight, networkSnapshot } from './relation-network.js';

let active = null, serial = 0, bound = false;
const keyFor = (record, path) => [record.dataset_id || record.versions?.dataset_id || state.datasetId, record.trace_id, path?.path_id || 'seed'].join(':');
const available = data => data?.enabled === true && !['no_index', 'invalid_index', 'unavailable', 'disabled'].includes(data.status);
function valid(item, token) { return active === item && item.token === token && state.datasetId === item.datasetId && datasetContext(item.datasetId).trace?.trace_id === item.record.trace_id; }
function bind() {
  if (bound) return; bound = true;
  $('#network-discover-groups').addEventListener('click', discoverGroups);
  $('#group-clear-highlight').addEventListener('click', () => { if (!active) return; active.view.selected = null; active.view.collapsed = null; clearGroupHighlight(); render(); });
  $('#group-retry').addEventListener('click', () => discoverGroups());
  $('#group-list').addEventListener('click', event => {
    const button = event.target.closest('[data-group-view],[data-group-collapse]'); if (!button || !active || active.view.loading || active.view.detailLoading) return;
    const id = button.dataset.groupView || button.dataset.groupCollapse;
    showGroup(id, button.hasAttribute('data-group-collapse'));
  });
  window.addEventListener('networkgroupchange', event => {
    if (!active || event.detail.key !== active.key) return;
    active.view.collapsed = event.detail.collapsed; render();
  });
}
export function setGroupContext(record, path = null) {
  bind(); const datasetId = record.dataset_id || record.versions?.dataset_id || state.datasetId, key = keyFor(record, path);
  if (active?.key === key) { updateGroupControls(); return; }
  const keepPanel = active?.record.trace_id === record.trace_id && active.view.revealed;
  if (active) { active.controller.abort(); active.view.loading = false; active.view.detailLoading = null; }
  const context = datasetContext(datasetId); let view = context.groupViews.get(key);
  if (!view) { view = { revealed: false, loading: false, detailLoading: null, result: null, error: '', progress: '', selected: null, collapsed: null, details: new Map() }; context.groupViews.set(key, view); }
  if (context.groupViews.size > 12) context.groupViews.delete(context.groupViews.keys().next().value);
  active = { key, datasetId, record, path, view, controller: new AbortController(), token: ++serial };
  $('#network-discover-groups').disabled = false; render();
  if (keepPanel && !view.revealed) discoverGroups();
}
export function clearGroupContext() {
  if (active) { active.controller.abort(); active.view.loading = false; active.view.detailLoading = null; }
  active = null; serial++;
  const panel = $('#associated-groups-panel'); if (panel) panel.hidden = true;
  const discover = $('#network-discover-groups'); if (discover) { discover.disabled = true; discover.textContent = '发现关联群组'; discover.setAttribute('aria-expanded', 'false'); }
}
export function updateGroupControls() {
  const c = datasetContext(state.datasetId), busy = !active || c.loadingAddress || c.loadingTrace || c.loadingReport || active.view.loading || !!active.view.detailLoading;
  $('#network-discover-groups').disabled = !!busy;
  $('#network-discover-groups').textContent = active?.view.loading ? '正在匹配群组…' : '发现关联群组';
  $('#network-discover-groups').setAttribute('aria-expanded', String(!!active?.view.revealed));
  $('#associated-groups-panel').setAttribute('aria-busy', String(!!active && (active.view.loading || !!active.view.detailLoading)));
  $('#group-list').querySelectorAll('button').forEach(button => { button.disabled = !!busy; });
}
function render() {
  if (!active) return;
  const { view } = active; $('#associated-groups-panel').hidden = !view.revealed;
  const groups = view.result?.groups || [];
  $('#group-context').textContent = active.path ? `围绕当前地址与路径 ${active.path.rank || ''} · ${active.path.hop_count} 跳` : '围绕当前分析地址';
  $('#group-state').textContent = view.loading ? '正在匹配当前关系…' : view.error ? '本次查看未完成' : view.result && !available(view.result) ? '群组功能暂不可用，现有追踪结果仍可查看。' : groups.length ? `匹配到 ${groups.length} 个关联群组` : '当前地址及所选路径未匹配到符合条件的关联群组。';
  $('#group-error').textContent = view.error;
  $('#group-progress').textContent = view.progress;
  $('#group-progress').hidden = !view.progress;
  $('#group-retry').hidden = !view.error;
  $('#group-clear-highlight').hidden = !view.selected;
  $('#group-list').innerHTML = groups.map((group, index) => {
    const id = group.group_id, selected = view.selected === id, collapsed = view.collapsed === id, loaded = view.details.get(id);
    const members = group.members_on_path || [], seed = !!group.shared_with_seed || !!group.seed_is_member;
    const relevance = [seed ? '包含分析起点' : '', members.length ? `当前路径涉及 ${members.length} 个成员` : ''].filter(Boolean).join(' · ') || '与当前关系关联';
    return `<article class="associated-group-card${selected ? ' selected' : ''}" data-group-id="${escape(id)}"><button type="button" class="group-card-main" data-group-view="${escape(id)}" aria-pressed="${selected}" aria-label="查看并高亮关联群组${index + 1}"><span class="group-card-title"><span>关联群组 ${String(index + 1).padStart(2, '0')}</span><span class="group-view-status">${view.detailLoading === id ? '正在加载…' : collapsed ? '已聚合' : selected ? '已高亮' : '查看关系 ↗'}</span></span><span class="group-card-metrics"><span><strong>${number(group.group_score, 2)}</strong><small>群组结构分</small></span><span><strong>${number(group.topology_density * 100, 1)}<em>%</em></strong><small>拓扑密度</small></span><span><strong>${escape(group.member_count)}</strong><small>成员地址</small></span><span><strong>${escape(group.edge_count)}</strong><small>内部关系</small></span></span><span class="group-relevance">${escape(relevance)}</span></button><div class="group-card-footer"><span>${loaded ? `已加载 ${loaded.nodes.length}/${group.member_count} 个成员 · ${loaded.edges.length}/${group.edge_count} 条关系` : '按需加载完整成员与内部真实关系'}</span><button type="button" class="group-collapse-button" data-group-collapse="${escape(id)}" aria-pressed="${collapsed}">${collapsed ? '展开成员' : '聚合群组'}</button></div><details class="group-evidence-id"><summary>查看群组证据编号</summary><code>${escape(id)}</code></details></article>`;
  }).join('');
  updateGroupControls();
}
export async function discoverGroups() {
  if (!active || active.view.loading || active.view.detailLoading) return;
  const item = active, token = item.token, { view } = item; view.revealed = true; view.loading = true; view.error = ''; view.progress = ''; render();
  try {
    const query = item.path?.path_id ? '?path_id=' + encodeURIComponent(item.path.path_id) : '';
    const data = await request(`/traces/${encodeURIComponent(item.record.trace_id)}/groups${query}`, { datasetId: item.datasetId, signal: item.controller.signal });
    if (!valid(item, token)) return;
    if (data.dataset_id && data.dataset_id !== item.datasetId) throw new Error('群组结果属于另一数据集，请重新追踪。');
    view.result = data;
    if (!available(data)) { view.selected = null; view.collapsed = null; clearGroupHighlight(); }
  } catch (error) { if (valid(item, token)) view.error = error.message; }
  finally { if (valid(item, token)) { view.loading = false; render(); } }
}
async function fetchCompleteGroup(item, id) {
  const nodes = new Map(), edges = new Map(); let offset = 0, revision = item.view.result?.revision, summary;
  while (true) {
    const token = item.token, query = new URLSearchParams({ offset: String(offset), limit: '500' });
    if (item.path?.path_id) query.set('path_id', item.path.path_id);
    const page = await request(`/traces/${encodeURIComponent(item.record.trace_id)}/groups/${encodeURIComponent(id)}?${query}`, { datasetId: item.datasetId, signal: item.controller.signal });
    if (!valid(item, token)) return null;
    if (page.dataset_id && page.dataset_id !== item.datasetId || page.group_id !== id || revision && page.revision !== revision) throw new Error('群组索引已变化，请重新追踪后查看。');
    revision ||= page.revision; summary = page.summary;
    for (const node of page.nodes || page.members || []) {
      if (!Number.isFinite(node.risk_score) || node.is_scored === false) throw new Error('群组成员与当前评分范围不匹配，请重新追踪。');
      nodes.set(node.address_id, node);
    }
    for (const edge of page.edges || page.internal_edges || []) edges.set(JSON.stringify([edge.src, edge.dst]), edge);
    const pagination = page.pagination || page, totalNodes = page.total_nodes ?? pagination.total_members, totalEdges = page.total_edges ?? pagination.total_edges;
    item.view.progress = `正在加载完整群组：${nodes.size}/${totalNodes ?? '—'} 个成员 · ${edges.size}/${totalEdges ?? '—'} 条关系`; render();
    const complete = pagination.complete === true || pagination.has_more === false;
    if (complete) {
      if (Number.isInteger(totalNodes) && nodes.size !== totalNodes || Number.isInteger(totalEdges) && edges.size !== totalEdges) throw new Error('群组数据未完整加载，请重试。');
      return { group_id: id, revision, summary: summary || item.view.result.groups.find(g => g.group_id === id), nodes: [...nodes.values()], edges: [...edges.values()], label: '关联群组 ' + String(item.view.result.groups.findIndex(g => g.group_id === id) + 1).padStart(2, '0') };
    }
    const next = pagination.next_offset;
    if (!Number.isInteger(next) || next <= offset) throw new Error('群组分页状态无效，请重试。'); offset = next;
  }
}
async function showGroup(id, toggleCollapse = false) {
  if (!active) return;
  const item = active, token = item.token, { view } = item; view.detailLoading = id; view.error = ''; view.progress = ''; render();
  try {
    if (toggleCollapse && view.collapsed === id) { expandNetworkGroup(); view.collapsed = null; return; }
    let detail = view.details.get(id);
    if (!detail) { detail = await fetchCompleteGroup(item, id); if (!detail || !valid(item, token)) return; }
    await loadNetworkGroup(detail); if (!valid(item, token)) return;
    view.details.set(id, detail); view.selected = id; view.collapsed = null;
    if (toggleCollapse) { collapseNetworkGroup(id); view.collapsed = id; }
    view.progress = `已完整加载 ${detail.nodes.length} 个成员与 ${detail.edges.length} 条内部真实关系。`;
  } catch (error) { if (valid(item, token)) { view.error = error.message; view.progress = ''; } }
  finally { if (valid(item, token)) { view.detailLoading = null; render(); } }
}
// Read-only diagnostic snapshot; used by browser acceptance checks.
export function groupsSnapshot() {
  if (!active) return null;
  return { key: active.key, revealed: active.view.revealed, loading: active.view.loading || !!active.view.detailLoading, status: active.view.result?.status,
    group_ids: (active.view.result?.groups || []).map(g => g.group_id), selected: active.view.selected, collapsed: active.view.collapsed,
    loaded: [...active.view.details].map(([id, detail]) => ({ id, nodes: detail.nodes.length, edges: detail.edges.length })), graph: networkSnapshot() };
}
