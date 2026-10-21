import { $, escape, number, levelName } from './dom.js';

let libraryPromise, active, generation = 0, bound = false;
const colors = { LOW: '#8599BD', MEDIUM: '#E7B759', HIGH: '#F29661', CRITICAL: '#FF7088' };
const visible = () => {
  const rect = $('#trace-chart').getBoundingClientRect();
  return rect.width > 0 && rect.height > 0;
};

function library() {
  if (window.cytoscape) return Promise.resolve(window.cytoscape);
  libraryPromise ||= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = '/assets/vendor/cytoscape.min.js';
    script.onload = () => window.cytoscape ? resolve(window.cytoscape) : reject(new Error('关系图组件加载失败'));
    script.onerror = () => { script.remove(); reject(new Error('关系图组件加载失败')); };
    document.head.append(script);
  }).catch(error => { libraryPromise = null; throw error; });
  return libraryPromise;
}

function showInfo(node) {
  if (!node?.length) return;
  const data = node.data();
  $('#network-node-info').hidden = false;
  $('#network-node-info').innerHTML = `<span>${data.isSeed ? '分析起点' : escape(levelName(data.level))} · 原始风险 ${number(data.risk)}</span><code>${escape(data.id)}</code>`;
}

function choose(id) {
  const cy = active?.cy, node = cy?.getElementById(id);
  if (!node?.length) return;
  active.selected = id;
  cy.nodes().removeClass('inspected');
  node.addClass('inspected');
  $('#network-node-select').value = id;
  showInfo(node);
}

function move(direction) {
  const cy = active?.cy, node = cy?.getElementById(active.selected);
  if (!node?.length) return;
  const offsets = { left: [-1, 0], up: [0, -1], down: [0, 1], right: [1, 0] };
  const [dx, dy] = offsets[direction], step = 24 / cy.zoom();
  node.position({ x: node.position('x') + dx * step, y: node.position('y') + dy * step });
}

function highlight() {
  const cy = active?.cy;
  if (!cy) return;
  const nodes = new Set(active.path?.nodes || []);
  const edges = new Set((active.path?.nodes || []).slice(1).map((id, i) => JSON.stringify([active.path.nodes[i], id])));
  cy.batch(() => {
    cy.nodes().forEach(node => node.toggleClass('on-path', nodes.has(node.id())));
    cy.edges().forEach(edge => edge.toggleClass('on-path', edges.has(JSON.stringify([edge.data('source'), edge.data('target')]))));
  });
}

function rememberView(item) {
  item.viewport = { zoom: item.cy.zoom(), pan: { ...item.cy.pan() } };
  const rect = $('#trace-chart').getBoundingClientRect();
  item.size = { width: rect.width, height: rect.height };
}

function fit() {
  if (!active?.cy || !visible()) return;
  active.adjusting = true;
  active.cy.resize();
  active.cy.fit(undefined, innerWidth < 520 ? 32 : 48);
  rememberView(active);
  active.adjusting = false;
}

function bind() {
  if (bound) return;
  bound = true;
  $('#network-node-select').addEventListener('change', event => choose(event.target.value));
  document.querySelectorAll('[data-node-move]').forEach(button => button.addEventListener('click', () => move(button.dataset.nodeMove)));
  $('#network-fit').addEventListener('click', fit);
  $('#network-reset').addEventListener('click', () => {
    if (!active?.cy) return;
    active.cy.nodes().positions(node => ({ ...active.initial[node.id()] }));
    fit();
  });
  $('#trace-chart').addEventListener('keydown', event => {
    const direction = { ArrowLeft: 'left', ArrowRight: 'right', ArrowUp: 'up', ArrowDown: 'down' }[event.key];
    if (direction && event.target === $('#trace-chart') && active?.cy) { event.preventDefault(); move(direction); }
  });
  const refresh = () => {
    if (!active) return;
    if (!visible()) { active.wasHidden = true; active.cy?.stop(); return; }
    if (!active.cy) { ensure(); return; }
    const rect = $('#trace-chart').getBoundingClientRect();
    const changed = active.size && (Math.abs(rect.width-active.size.width)>1 || Math.abs(rect.height-active.size.height)>1);
    const viewport = active.viewport || { zoom: active.cy.zoom(), pan: { ...active.cy.pan() } };
    active.adjusting = true;
    active.cy.resize();
    if (changed) active.cy.fit(undefined, innerWidth < 520 ? 32 : 48);
    else active.cy.viewport(viewport);
    rememberView(active);
    active.wasHidden = false;
    active.adjusting = false;
  };
  new ResizeObserver(refresh).observe($('#trace-chart'));
  window.addEventListener('routechange', refresh);
  window.addEventListener('pagevisibilitychange', refresh);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) refresh(); });
}

async function ensure() {
  if (!active || active.cy || active.loading || !visible()) return;
  const item = active, token = generation, container = $('#trace-chart');
  item.loading = true;
  container.dataset.networkReady = 'loading';
  container.innerHTML = '<div class="graph-empty"><h3>正在展开关系网络…</h3><p>整理节点间距与关联方向</p></div>';
  try {
    const cytoscape = await library();
    if (token !== generation || active !== item || !visible()) return;
    container.replaceChildren();
    const nodes = item.record.result.subgraph.nodes;
    const edgeKeys = new Set();
    const elements = nodes.map((node, i) => ({
      data: { id: node.address_id, risk: node.risk_score, level: node.risk_level,
        isSeed: node.address_id === item.record.result.seed_address,
        label: node.address_id === item.record.result.seed_address ? '分析起点' : node.address_id.slice(0, 6) + '…',
        color: colors[node.risk_level] || colors.LOW,
        size: node.address_id === item.record.result.seed_address ? 36 : 17 + node.risk_score * .11 },
      position: { x: Math.cos(i * 2.39996) * 35 * Math.sqrt(i), y: Math.sin(i * 2.39996) * 35 * Math.sqrt(i) }
    }));
    for (const edge of item.record.result.subgraph.edges) {
      const key = JSON.stringify([edge.src, edge.dst]);
      if (edgeKeys.has(key)) continue;
      edgeKeys.add(key);
      elements.push({ data: { id: 'edge:' + edgeKeys.size, source: edge.src, target: edge.dst } });
    }
    const cy = cytoscape({ container, elements, layout: { name: 'preset' },
      minZoom: .04, maxZoom: 4, wheelSensitivity: .2, autoungrabify: false,
      boxSelectionEnabled: false, selectionType: 'single',
      style: [
        { selector: 'node', style: { 'background-color': 'data(color)', width: 'data(size)', height: 'data(size)',
          label: nodes.length > 100 ? '' : 'data(label)', color: '#C8D5EC', 'font-size': 11,
          'font-family': 'PingFang SC, Microsoft YaHei, sans-serif', 'text-valign': 'bottom', 'text-margin-y': 9,
          'text-background-color': '#10172C', 'text-background-opacity': .85, 'text-background-padding': '2px',
          'border-color': '#BCCBE2', 'border-width': 1, 'overlay-opacity': 0 } },
        { selector: 'node[?isSeed]', style: { shape: 'diamond', 'background-color': '#61D8FF', label: '分析起点', 'border-color': '#B1EDFF', 'border-width': 2 } },
        { selector: 'edge', style: { width: 1.4, 'line-color': '#657A9E', 'target-arrow-color': '#657A9E', 'target-arrow-shape': 'triangle', 'arrow-scale': .8, 'curve-style': 'bezier', opacity: .55 } },
        { selector: 'edge.on-path', style: { width: 2.6, 'line-color': '#61D8FF', 'target-arrow-color': '#61D8FF', opacity: 1, 'z-index': 5 } },
        { selector: 'node.on-path', style: { 'border-color': '#A9E8FF', 'border-width': 2 } },
        { selector: 'node.inspected', style: { 'border-color': '#FFFFFF', 'border-width': 3, label: 'data(label)', 'font-weight': 'bold' } }
      ] });
    item.cy = cy;
    cy.on('pan zoom', () => {
      if (item.adjusting || item.wasHidden || !visible()) return;
      const rect = container.getBoundingClientRect();
      if (item.size && Math.abs(rect.width-item.size.width)<1 && Math.abs(rect.height-item.size.height)<1) rememberView(item);
    });
    cy.on('tap', 'node', event => choose(event.target.id()));
    cy.on('mouseover', 'node', event => showInfo(event.target));
    cy.on('mouseout', 'node', () => showInfo(cy.getElementById(item.selected)));
    cy.on('grab', 'node', event => choose(event.target.id()));
    // Layout once; later drag, path selection and resize never re-run physics.
    const layout = cy.layout({ name: 'cose', animate: false, randomize: false, fit: false,
      nodeDimensionsIncludeLabels: true, nodeRepulsion: () => 9000, idealEdgeLength: () => 100,
      edgeElasticity: () => 90, gravity: .45, componentSpacing: 90, numIter: 1000 });
    layout.run();
    if (token !== generation) { cy.destroy(); return; }
    item.initial = Object.fromEntries(cy.nodes().map(node => [node.id(), { ...node.position() }]));
    $('#network-node-select').innerHTML = nodes.map(node => `<option value="${escape(node.address_id)}">${node.address_id === item.record.result.seed_address ? '起点 · ' : ''}${escape(node.address_id)}</option>`).join('');
    $('#network-controls').hidden = false;
    choose(item.record.result.seed_address);
    highlight();
    fit();
    container.dataset.networkReady = 'true';
  } catch {
    if (token !== generation) return;
    item.cy?.destroy(); item.cy = null;
    container.dataset.networkReady = 'error';
    container.innerHTML = '<div class="graph-empty"><h3>关系图暂未加载</h3><p>路径明细和报告仍可查看，请重试图形组件。</p><button type="button" class="network-button" id="network-retry">重新加载关系图</button></div>';
    $('#network-retry').addEventListener('click', ensure);
  } finally { item.loading = false; }
}

export function renderNetwork(record, path = null) {
  bind();
  if (active?.record.trace_id !== record.trace_id) {
    clearNetwork();
    active = { record, path, selected: record.result.seed_address, cy: null, initial: null, loading: false };
    $('#trace-chart').dataset.networkTrace = record.trace_id;
  } else active.path = path;
  if (active.cy) highlight();
  else ensure();
}

export function clearNetwork() {
  generation++;
  active?.cy?.destroy();
  active = null;
  const container = $('#trace-chart');
  container.replaceChildren();
  delete container.dataset.networkTrace;
  delete container.dataset.networkReady;
  $('#network-controls').hidden = true;
  $('#network-node-info').hidden = true;
}

// Read-only diagnostic snapshot for browser interaction verification.
export function networkSnapshot() {
  if (!active?.cy) return null;
  const cy = active.cy;
  const rect = $('#trace-chart').getBoundingClientRect();
  return { trace_id: active.record.trace_id, zoom: cy.zoom(), pan: { ...cy.pan() }, width: rect.width, height: rect.height,
    nodes: cy.nodes().map(node => ({ id: node.id(), position: { ...node.position() }, rendered: { ...node.renderedPosition() }, risk: node.data('risk'), level: node.data('level'), seed: node.data('isSeed') })),
    edges: cy.edges().map(edge => ({ source: edge.data('source'), target: edge.data('target'), highlighted: edge.hasClass('on-path') })) };
}
