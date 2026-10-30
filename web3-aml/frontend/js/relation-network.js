import { $, escape, number, levelName, riskScoreHTML } from './dom.js';
import { buildNetworkModel, relationKey, groupNodeId } from './network-model.js';
import { datasetContext } from './state.js';

let libraryPromise, active, generation = 0, bound = false;
const colors = { LOW: '#2DD4BF', MEDIUM: '#E7B759', HIGH: '#F29661', CRITICAL: '#FF7088' };
const savedViews = new Map();
const contextKey = (record, path) => [record.dataset_id || record.versions?.dataset_id || 'bitcoin', record.trace_id, path?.path_id || 'seed'].join(':');
const visible = () => { const rect = $('#trace-chart').getBoundingClientRect(); return rect.width > 0 && rect.height > 0; };

function library() {
  if (window.cytoscape) return Promise.resolve(window.cytoscape);
  libraryPromise ||= new Promise((resolve, reject) => {
    const script = document.createElement('script'); script.src = '/assets/vendor/cytoscape.min.js';
    script.onload = () => window.cytoscape ? resolve(window.cytoscape) : reject(new Error('关系图组件加载失败'));
    script.onerror = () => { script.remove(); reject(new Error('关系图组件加载失败')); };
    document.head.append(script);
  }).catch(error => { libraryPromise = null; throw error; });
  return libraryPromise;
}
function showInfo(node) {
  if (!node?.length) return;
  const data = node.data(), info = $('#network-node-info'); info.hidden = false;
  if (data.isGroup) {
    info.innerHTML = `<strong>${escape(data.title || '关联群组')} · ${data.member_count}个地址</strong><span>${data.edge_count} 条内部真实关系${data.containsSeed ? ' · 包含分析起点' : ''} · 点击群组节点展开</span><small>群组节点用于收拢展示，不是钱包地址。</small>`;
    return;
  }
  info.innerHTML = `<span>${data.isSeed ? '分析起点 · ' : ''}${escape(levelName(data.level))} · 综合风险 ${riskScoreHTML(data.risk)}</span><code>${escape(data.id)}</code>`;
  if (data.group_ids?.length) info.insertAdjacentHTML('beforeend', `<small>属于 ${data.group_ids.length} 个已加载关联群组</small>`);
  const observations = (active?.model?.allEdges || []).filter(e => e.src === data.id || e.dst === data.id).flatMap(e => e.evidence || []).filter(e => e.tx_hash).slice(0, 2);
  if (observations.length) info.insertAdjacentHTML('beforeend', `<details class="node-observations"><summary>真实关联交易摘录</summary>${observations.map(e => `<p>${escape(e.value_eth ?? '—')} ETH · ${escape(e.timestamp_utc || '—')}<br><code>${escape(e.tx_hash)}</code></p>`).join('')}</details>`);
}
function choose(id) {
  if (!active?.cy) return;
  if (!active.cy.getElementById(id).length && active.collapsedId && active.loadedGroups.get(active.collapsedId)?.nodes.some(n => n.address_id === id)) expandNetworkGroup();
  const node = active.cy.getElementById(id); if (!node.length) return;
  active.selected = id; active.cy.nodes().removeClass('inspected'); node.addClass('inspected');
  if (!node.data('isGroup')) $('#network-node-select').value = id;
  showInfo(node);
}
function highlight() {
  const cy = active?.cy; if (!cy) return;
  const pathNodes = new Set(active.path?.nodes || []);
  const pathEdges = new Set((active.path?.nodes || []).slice(1).map((id, i) => relationKey(active.path.nodes[i], id)));
  cy.batch(() => {
    cy.nodes().forEach(node => { node.toggleClass('on-path', pathNodes.has(node.id())); node.toggleClass('in-group', !!node.data('inGroup')); node.toggleClass('group-dim', !!active.selectedGroupId && !node.data('inGroup')); });
    cy.edges().forEach(edge => {
      edge.toggleClass('on-path', !edge.data('isAggregate') && edge.data('original_edges').some(e => pathEdges.has(relationKey(e.src, e.dst))));
      edge.toggleClass('in-group', !!edge.data('inGroup')); edge.toggleClass('group-dim', !!active.selectedGroupId && !edge.data('inGroup') && !edge.data('isAggregate'));
    });
  });
}
function rememberView(item) {
  item.viewport = { zoom: item.cy.zoom(), pan: { ...item.cy.pan() } };
  const rect = $('#trace-chart').getBoundingClientRect(); item.size = { width: rect.width, height: rect.height };
}
function rememberPositions(item) {
  if (!item.cy) return;
  item.cy.nodes().forEach(node => { item.positions[node.id()] = { ...node.position() }; });
}
function fit() {
  if (!active?.cy || !visible()) return;
  active.adjusting = true; active.cy.resize(); active.cy.fit(undefined, innerWidth < 520 ? 32 : 48); rememberView(active); active.adjusting = false;
}
function elements(item) {
  const model = buildNetworkModel(item.record, item.loadedGroups, item.selectedGroupId, item.collapsedId); item.model = model;
  const anchor = item.positions[item.record.result.seed_address] || { x: 0, y: 0 };
  const result = model.nodes.map((node, i) => {
    let position = item.positions[node.id];
    if (!position && node.isGroup) {
      const known = node.members.map(id => item.positions[id]).filter(Boolean);
      position = known.length ? { x: known.reduce((v, p) => v + p.x, 0) / known.length, y: known.reduce((v, p) => v + p.y, 0) / known.length } : anchor;
    }
    position ||= { x: anchor.x + Math.cos(i * 2.39996) * 45 * Math.sqrt(i + 1), y: anchor.y + Math.sin(i * 2.39996) * 45 * Math.sqrt(i + 1) };
    item.positions[node.id] = { ...position }; item.initial[node.id] ||= { ...position };
    return { data: { ...node, title: node.isGroup ? node.label : undefined, risk: node.risk_score, level: node.risk_level,
      label: node.isGroup ? `${node.label}\n${node.member_count}个地址${node.containsSeed ? ' · 含起点' : ''}` : node.isSeed ? '分析起点' : node.id.slice(0, 6) + '…',
      color: node.isGroup ? '#4B3D71' : colors[node.risk_level] || colors.LOW,
      size: node.isGroup ? 66 : node.isSeed ? 36 : 17 + node.risk_score * .11 }, position };
  });
  model.edges.forEach(edge => result.push({ data: { ...edge, label: edge.isAggregate ? `${edge.count}条关系` : '' } }));
  return result;
}
function updatePicker() {
  if (!active?.model) return;
  $('#network-node-select').innerHTML = active.model.allNodes.map(n => `<option value="${escape(n.address_id)}">${n.address_id === active.record.result.seed_address ? '起点 · ' : ''}${escape(n.address_id)}</option>`).join('');
  const scope = $('#network-group-scope');
  scope.hidden = !active.loadedGroups.size;
  scope.textContent = `原追踪图 ${active.record.result.subgraph.nodes.length} 个地址 · 群组补充 ${active.model.extra_nodes} 个地址、${active.model.extra_edges} 条真实关系${active.collapsedId ? ' · 当前已聚合1个群组' : ''}`;
  $('#trace-chart').dataset.groupAggregated = active.collapsedId || '';
  $('#trace-chart').dataset.selectedGroup = active.selectedGroupId || '';
}
function rebuild() {
  if (!active?.cy) return;
  rememberPositions(active); const next = elements(active);
  active.cy.batch(() => { active.cy.elements().remove(); active.cy.add(next); });
  active.cy.style().selector('node[!isGroup]').style('label', active.model.nodes.length > 100 ? '' : 'data(label)').selector('node.inspected').style('label', 'data(label)').update();
  updatePicker(); highlight();
  choose(active.cy.getElementById(active.selected).length ? active.selected : active.collapsedId ? groupNodeId(active.collapsedId) : active.record.result.seed_address);
}
function bind() {
  if (bound) return; bound = true;
  $('#network-node-select').addEventListener('change', event => choose(event.target.value));
  $('#network-fit').addEventListener('click', fit);
  $('#network-reset').addEventListener('click', () => {
    if (!active?.cy) return;
    active.cy.nodes().positions(node => ({ ...active.initial[node.id()] })); rememberPositions(active); fit();
  });
  $('#trace-chart').addEventListener('keydown', event => {
    const node = active?.cy?.getElementById(active.selected);
    if ((event.key === 'Enter' || event.key === ' ') && event.target === $('#trace-chart') && node?.data('isGroup')) { event.preventDefault(); expandNetworkGroup(); return; }
    const offsets = { ArrowLeft: [-1, 0], ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowRight: [1, 0] }, d = offsets[event.key];
    if (d && event.target === $('#trace-chart') && node?.length) { event.preventDefault(); node.position({ x: node.position('x') + d[0] * 24 / active.cy.zoom(), y: node.position('y') + d[1] * 24 / active.cy.zoom() }); }
  });
  const refresh = () => {
    if (!active) return;
    if (!visible()) { active.wasHidden = true; active.cy?.stop(); return; }
    if (!active.cy) { ensure(); return; }
    const rect = $('#trace-chart').getBoundingClientRect(), changed = active.size && (Math.abs(rect.width - active.size.width) > 1 || Math.abs(rect.height - active.size.height) > 1);
    const viewport = active.viewport || { zoom: active.cy.zoom(), pan: { ...active.cy.pan() } };
    active.adjusting = true; active.cy.resize();
    if (changed) active.cy.fit(undefined, innerWidth < 520 ? 32 : 48); else active.cy.viewport(viewport);
    rememberView(active); active.adjusting = false; active.wasHidden = false;
  };
  new ResizeObserver(refresh).observe($('#trace-chart'));
  // Group actions can move focus between the panel and a scrolled canvas.
  // Refresh the renderer's hit-test coordinates after scrolling, without fitting again.
  let scrollFrame = null;
  window.addEventListener('scroll', () => {
    if (scrollFrame !== null) return;
    scrollFrame = requestAnimationFrame(() => { scrollFrame = null; if (active?.cy && visible()) active.cy.resize(); });
  }, { passive: true });
  window.addEventListener('routechange', refresh); window.addEventListener('pagevisibilitychange', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}
async function ensure() {
  if (!active || active.cy || active.loading || !visible()) return;
  const item = active, token = generation, container = $('#trace-chart'); item.loading = true;
  container.dataset.networkReady = 'loading';
  container.innerHTML = '<div class="graph-empty"><h3>正在展开关系网络…</h3><p>整理节点间距与关联方向</p></div>';
  try {
    const cytoscape = await library(); if (token !== generation || active !== item || !visible()) return;
    container.replaceChildren();
    const cy = cytoscape({ container, elements: elements(item), layout: { name: 'preset' }, minZoom: .01, maxZoom: 4, wheelSensitivity: .2,
      autoungrabify: false, boxSelectionEnabled: false, selectionType: 'single',
      style: [
        { selector: 'node', style: { 'background-color': 'data(color)', width: 'data(size)', height: 'data(size)', label: item.model.nodes.length > 100 ? '' : 'data(label)', color: '#C8D5EC', 'font-size': 11, 'font-family': 'PingFang SC, Microsoft YaHei, sans-serif', 'text-valign': 'bottom', 'text-margin-y': 9, 'text-background-color': '#10172C', 'text-background-opacity': .85, 'text-background-padding': '2px', 'border-color': '#BCCBE2', 'border-width': 1, 'overlay-opacity': 0 } },
        { selector: 'node[?isSeed]', style: { shape: 'diamond', 'background-color': '#61D8FF', label: '分析起点', 'border-color': '#B1EDFF', 'border-width': 2 } },
        { selector: 'edge', style: { width: 1.4, 'line-color': '#657A9E', 'target-arrow-color': '#657A9E', 'target-arrow-shape': 'triangle', 'arrow-scale': .8, 'curve-style': 'bezier', opacity: .55 } },
        { selector: 'edge.on-path', style: { width: 2.6, 'line-color': '#61D8FF', 'target-arrow-color': '#61D8FF', opacity: 1, 'z-index': 5 } },
        { selector: 'node.on-path', style: { 'border-color': '#A9E8FF', 'border-width': 2 } },
        { selector: 'node.in-group', style: { 'border-color': '#C5ACFF', 'border-width': 4, 'border-style': 'double', 'z-index': 6 } },
        { selector: 'edge.in-group', style: { 'line-color': '#C5ACFF', 'target-arrow-color': '#C5ACFF', width: 2.5, opacity: .95, 'z-index': 6 } },
        { selector: '.group-dim', style: { opacity: .22 } },
        { selector: 'node[?isGroup]', style: { shape: 'round-hexagon', 'background-color': '#4B3D71', 'border-color': '#C5ACFF', 'border-width': 3, label: 'data(label)', 'text-wrap': 'wrap', 'font-size': 12, color: '#F1E9FF', 'text-valign': 'center', 'text-margin-y': 0, 'text-background-opacity': 0, 'text-max-width': 150 } },
        { selector: 'edge[?isAggregate]', style: { 'line-style': 'dashed', 'line-color': '#B89AEF', 'target-arrow-color': '#B89AEF', label: 'data(label)', 'font-size': 10, color: '#E0D2F8', 'text-background-color': '#152039', 'text-background-opacity': .9, 'text-background-padding': '3px', opacity: .85 } },
        { selector: 'node.inspected', style: { 'border-color': '#FFFFFF', 'border-width': 3, label: 'data(label)', 'font-weight': 'bold', opacity: 1 } }
      ] });
    item.cy = cy;
    cy.on('pan zoom', () => { if (!item.adjusting && !item.wasHidden && visible()) rememberView(item); });
    cy.on('tap', 'node', event => { if (event.target.data('isGroup')) expandNetworkGroup(); else choose(event.target.id()); });
    cy.on('mouseover', 'node', event => showInfo(event.target));
    cy.on('mouseout', 'node', () => showInfo(cy.getElementById(item.selected)));
    cy.on('grab', 'node', event => choose(event.target.id()));
    cy.on('tap', 'edge[?isAggregate]', event => {
      const originals = event.target.data('original_edges'); $('#network-node-info').hidden = false;
      $('#network-node-info').innerHTML = `<strong>${originals.length}条真实关系的展示汇总</strong><small>虚线用于整理画布，不是新增交易或路径跳数。</small><details open><summary>查看原始方向关系</summary>${originals.map(e => `<code>${escape(e.src)} → ${escape(e.dst)}</code>`).join('')}</details>`;
    });
    if (!item.saved) {
      const layout = cy.layout({ name: 'cose', animate: false, randomize: false, fit: false, nodeDimensionsIncludeLabels: true,
        nodeRepulsion: () => 9000, idealEdgeLength: () => 100, edgeElasticity: () => 90, gravity: .45, componentSpacing: 90, numIter: 1000 }); layout.run();
      rememberPositions(item); item.initial = { ...item.positions };
    }
    if (token !== generation) { cy.destroy(); return; }
    updatePicker(); $('#network-controls').hidden = false;
    choose(cy.getElementById(item.selected).length ? item.selected : item.collapsedId ? groupNodeId(item.collapsedId) : item.record.result.seed_address); highlight();
    if (item.viewport) { cy.resize(); cy.viewport(item.viewport); rememberView(item); } else fit();
    container.dataset.networkReady = 'true';
  } catch (error) {
    if (token !== generation) return;
    item.cy?.destroy(); item.cy = null; container.dataset.networkReady = 'error';
    container.innerHTML = '<div class="graph-empty"><h3>关系图暂未加载</h3><p>路径明细和报告仍可查看，请重试图形组件。</p><button type="button" class="network-button" id="network-retry">重新加载关系图</button></div>';
    $('#network-retry').addEventListener('click', ensure);
  } finally { item.loading = false; }
}
export function renderNetwork(record, path = null) {
  bind(); const key = contextKey(record, path);
  if (active?.key !== key) {
    const carried = active?.record.trace_id === record.trace_id ? { ...active.positions } : {};
    clearNetwork(); const saved = savedViews.get(key);
    const groupView = datasetContext(record.dataset_id || record.versions?.dataset_id || 'bitcoin').groupViews.get(key);
    active = { key, record, path, selected: saved?.selected || record.result.seed_address, cy: null, loading: false,
      initial: { ...saved?.initial }, positions: { ...carried, ...saved?.positions }, viewport: saved?.viewport,
      loadedGroups: new Map(groupView?.details || []), selectedGroupId: groupView?.selected || null, collapsedId: groupView?.collapsed || null, saved };
    $('#trace-chart').dataset.networkTrace = record.trace_id;
  } else active.path = path;
  if (active.cy) highlight(); else ensure();
}
export function clearNetwork() {
  generation++;
  if (active) {
    rememberPositions(active);
    savedViews.set(active.key, { positions: { ...active.positions }, initial: { ...active.initial }, selected: active.selected,
      viewport: active.cy ? { zoom: active.cy.zoom(), pan: { ...active.cy.pan() } } : active.viewport });
    if (savedViews.size > 24) savedViews.delete(savedViews.keys().next().value);
  }
  active?.cy?.destroy(); active = null;
  const container = $('#trace-chart'); container.replaceChildren();
  for (const name of ['networkTrace', 'networkReady', 'groupAggregated', 'selectedGroup']) delete container.dataset[name];
  $('#network-controls').hidden = true; $('#network-node-info').hidden = true; $('#network-group-scope').hidden = true;
}
export async function loadNetworkGroup(detail) {
  if (!active) return;
  const group = { ...detail, nodes: detail.nodes.map(n => ({ ...n })), edges: detail.edges.map(e => ({ ...e })) };
  const candidate = new Map(active.loadedGroups); candidate.set(group.group_id, group);
  buildNetworkModel(active.record, candidate, group.group_id, null); // Validate atomically before changing the visible graph.
  if (active.collapsedId) expandNetworkGroup();
  active.loadedGroups = candidate; active.selectedGroupId = group.group_id; rebuild();
  await ensure(); fit();
}
export function collapseNetworkGroup(groupId) {
  if (!active?.loadedGroups.has(groupId)) return false;
  if (active.collapsedId === groupId) { expandNetworkGroup(); return false; }
  if (active.collapsedId) expandNetworkGroup();
  rememberPositions(active); active.collapseViewport = active.cy ? { zoom: active.cy.zoom(), pan: { ...active.cy.pan() } } : null;
  active.collapsedId = groupId; active.selectedGroupId = groupId; rebuild(); fit();
  window.dispatchEvent(new CustomEvent('networkgroupchange', { detail: { key: active.key, collapsed: groupId } })); return true;
}
export function expandNetworkGroup() {
  if (!active?.collapsedId) return;
  const previous = active.collapsedId; active.collapsedId = null; rebuild();
  if (active.collapseViewport && active.cy) { active.cy.viewport(active.collapseViewport); rememberView(active); }
  window.dispatchEvent(new CustomEvent('networkgroupchange', { detail: { key: active.key, collapsed: null, expanded: previous } }));
}
export function clearGroupHighlight() { if (!active) return; if (active.collapsedId) expandNetworkGroup(); active.selectedGroupId = null; rebuild(); }
export function networkSnapshot() {
  if (!active?.cy) return null;
  const cy = active.cy, rect = $('#trace-chart').getBoundingClientRect();
  return { trace_id: active.record.trace_id, context_key: active.key, zoom: cy.zoom(), pan: { ...cy.pan() }, width: rect.width, height: rect.height,
    selected_group: active.selectedGroupId, collapsed_group: active.collapsedId, extra_nodes: active.model.extra_nodes, extra_edges: active.model.extra_edges,
    nodes: cy.nodes().map(node => ({ id: node.id(), position: { ...node.position() }, rendered: { ...node.renderedPosition() }, risk: node.data('risk'), level: node.data('level'), seed: node.data('isSeed'), is_group: !!node.data('isGroup'), contains_seed: !!node.data('containsSeed'), member_count: node.data('member_count'), in_group: node.hasClass('in-group'), unscored: false, color: node.data('color') })),
    edges: cy.edges().map(edge => ({ source: edge.data('source'), target: edge.data('target'), highlighted: edge.hasClass('on-path'), in_group: edge.hasClass('in-group'), aggregate: !!edge.data('isAggregate'), original_edges: edge.data('original_edges').map(e => [e.src, e.dst]) })) };
}
