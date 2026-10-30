/* Real local BTC/ETH group APIs and browser interactions. No LLM calls or model changes. */
const { chromium } = require('/Users/luyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.env.WEB3AML_URL || 'http://127.0.0.1:8001', out = path.resolve(__dirname, '../artifacts/v4_frontend_check');
fs.mkdirSync(out, { recursive: true });
(async () => {
 const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
 const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } }), page = await context.newPage();
 page.setDefaultTimeout(60000);
 const checks = [], errors = [], requests = [], responses = [];
 page.on('pageerror', error => errors.push(error.message));
 page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) requests.push({ method: request.method(), url: request.url() }); });
 page.on('response', response => { if (response.status() >= 400 && new URL(response.url()).pathname.startsWith('/api/')) responses.push({ status: response.status(), url: response.url() }); });
 const pass = (name, details = {}) => { checks.push({ name, ...details }); console.log('PASS', name); };
 const snapshot = () => page.evaluate(async () => (await import('/assets/js/groups.js')).groupsSnapshot());
 const network = () => page.evaluate(async () => (await import('/assets/js/relation-network.js')).networkSnapshot());
 const waitIdle = () => page.waitForFunction(() => !document.querySelector('#associated-groups-panel').hidden && document.querySelector('#associated-groups-panel').getAttribute('aria-busy') === 'false');
 async function loadAddress(dataset, address, noPaths = false) {
  await page.goto(base + '/workspace/risk?dataset=' + dataset);
  await page.waitForFunction(() => document.querySelector('#service-state').textContent.includes('已就绪'));
  await page.locator('#address-input').fill(address); await page.locator('#analyze-button').click();
  await page.waitForFunction(expected => document.querySelector('#dataset-active-address').textContent === expected, address);
  await page.locator('.module-link[data-module="trace"]').click();
  if (noPaths) await page.locator('#risk-threshold').fill('100');
  await page.locator('#trace-button').click();
  await page.waitForFunction(() => document.querySelector('#trace-chart').dataset.networkReady === 'true' && !document.querySelector('#trace-button').disabled);
 }
 async function clickGroup(id, collapse = false) {
  await page.locator(`[${collapse ? 'data-group-collapse' : 'data-group-view'}="${id}"]`).click(); await waitIdle();
  const message = await page.locator('#group-error').innerText(); assert.equal(message, '');
 }
 async function detail(traceId, dataset, groupId, pathId) {
  let offset = 0, nodes = [], edges = [];
  while (true) {
   const r = await context.request.get(`${base}/api/traces/${traceId}/groups/${groupId}?dataset_id=${dataset}&offset=${offset}&limit=500${pathId ? '&path_id=' + encodeURIComponent(pathId) : ''}`); assert.equal(r.status(), 200); const data = await r.json();
   nodes.push(...data.nodes); edges.push(...data.edges); if (data.complete) return { nodes, edges, summary: data.summary }; offset = data.next_offset;
  }
 }
 try {
  const cases = [
   { dataset: 'bitcoin', address: '16h96wAYUgaPEHoYFJwZNcbcVBffno2PMQ', group: 'dense_d3038bced982b188ca8d' },
   { dataset: 'ethereum', address: '0x096c39ab4fa36ca74a36fe1f4767ff487762f0aa', group: 'dense_459c328ce9edcb4013d1' },
   { dataset: 'bitcoin', address: '12A6GH9vPBqvTMyLkfFWzEUXwx3xAu92Mt', group: 'dense_81c86a085a88325bac0c', overlap: 'dense_de48f9365095164f79d3' },
   { dataset: 'bitcoin', address: '16h96wAYUgaPEHoYFJwZNcbcVBffno2PMQ', group: 'dense_d3038bced982b188ca8d', noPaths: true }
  ];
  for (const item of cases) {
   await loadAddress(item.dataset, item.address, item.noPaths);
   assert.equal(await page.locator('#associated-groups-panel').isVisible(), false); assert.equal(await page.locator('[data-node-move]').count(), 0);
   const original = await page.evaluate(async () => JSON.stringify((await import('/assets/js/state.js')).state.trace.result));
   const beforePosts = requests.filter(r => r.method === 'POST' && new URL(r.url).pathname === '/api/traces').length;
   await page.locator('#network-discover-groups').click(); await waitIdle();
   let s = await snapshot(); assert.ok(s.group_ids.includes(item.group)); assert.equal(s.collapsed, null);
   await clickGroup(item.group); s = await snapshot(); const n = await network();
   const record = await page.evaluate(async () => (await import('/assets/js/state.js')).state.trace);
   if (item.noPaths) { assert.equal(record.result.top_paths.length, 0); pass('真实无合格路径时仍可按起点发现并展开群组，不依赖path_id'); }
   const pathId = record.result.top_paths[Number(await page.locator('#path-select').inputValue())]?.path_id;
   const full = await detail(record.trace_id, item.dataset, item.group, pathId);
   const byId = new Map(n.nodes.map(node => [node.id, node]));
   const missingNodes = full.nodes.filter(node => !byId.has(node.address_id));
   if (missingNodes.length) console.log('MISSING', JSON.stringify({ count: missingNodes.length, samples: missingNodes.slice(0, 3), graph_nodes: n.nodes.length, full_nodes: full.nodes.length, now_nodes: (await network()).nodes.length }));
   full.nodes.forEach(node => { assert.ok(byId.has(node.address_id)); assert.equal(byId.get(node.address_id).risk, node.risk_score); assert.equal(byId.get(node.address_id).in_group, true); });
   const edges = new Set(n.edges.flatMap(edge => edge.original_edges.map(e => JSON.stringify(e)))); full.edges.forEach(edge => assert.ok(edges.has(JSON.stringify([edge.src, edge.dst]))));
   assert.equal(s.loaded.find(g => g.id === item.group).nodes, full.nodes.length); assert.ok(n.extra_nodes >= 0);
   pass(item.dataset + ' 真实群组完整加载、冻结分数及内部边联动高亮', { address: item.address, nodes: full.nodes.length, edges: full.edges.length, extra_nodes: n.extra_nodes });
   const positions = Object.fromEntries(n.nodes.map(node => [node.id, node.position]));
   await clickGroup(item.group, true); s = await snapshot(); let collapsed = s.graph.nodes.filter(node => node.is_group); assert.equal(collapsed.length, 1); assert.equal(collapsed[0].contains_seed, true); assert.equal(s.collapsed, item.group);
   assert.equal(s.graph.nodes.length, n.nodes.length - full.nodes.length + 1);
   await page.locator('#trace-chart').scrollIntoViewIfNeeded();
   await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
   collapsed = (await network()).nodes.filter(node => node.is_group);
   const rect = await page.locator('#trace-chart').boundingBox(), center = collapsed[0].rendered;
   await page.mouse.click(rect.x + center.x, rect.y + center.y); await page.waitForFunction(() => !document.querySelector('#trace-chart').dataset.groupAggregated);
   const expanded = await network(); assert.equal(expanded.nodes.length, n.nodes.length); assert.equal(expanded.edges.length, n.edges.length);
   expanded.nodes.forEach(node => assert.deepEqual(node.position, positions[node.id]));
   pass(item.dataset + ' 手动唯一聚合、包含起点标记、点击节点展开及坐标还原', { group: item.group });
   if (item.overlap) {
    await clickGroup(item.group, true); await clickGroup(item.overlap, true); s = await snapshot(); assert.equal(s.collapsed, item.overlap); assert.equal(s.graph.nodes.filter(node => node.is_group).length, 1); assert.ok(!s.graph.nodes.some(node => node.id === 'group-view:' + item.group));
    await clickGroup(item.overlap, true); assert.equal((await snapshot()).collapsed, null);
    assert.ok(requests.some(r => r.url.includes('/groups/' + item.group) && new URL(r.url).searchParams.get('offset') === '500'));
    pass('真实501成员群组跨页无截断，重叠群组切换自动还原前组', { loaded: s.loaded });
   }
   assert.equal(await page.evaluate(async () => JSON.stringify((await import('/assets/js/state.js')).state.trace.result)), original);
   assert.equal(requests.filter(r => r.method === 'POST' && new URL(r.url).pathname === '/api/traces').length, beforePosts);
   await page.locator('#group-clear-highlight').click(); const cleared = await network(); assert.equal(cleared.selected_group, null); assert.equal(cleared.collapsed_group, null); assert.equal(cleared.nodes.filter(node => node.in_group).length, 0); assert.equal(cleared.edges.filter(edge => edge.in_group).length, 0);
   pass(item.dataset + ' 发现／展开／聚合不重新追踪、不改原始trace证据，清除高亮后节点与边状态归零');
   await page.screenshot({ path: path.join(out, `${item.dataset}-${item.overlap ? 'large-overlap' : item.noPaths ? 'seed-no-path' : 'group'}.png`), fullPage: true });
  }
  for (const width of [375, 768, 1440]) {
   await page.setViewportSize({ width, height: 1050 });
   await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
   for (let alignment = 0; alignment < 2; alignment++) {
    await page.evaluate(() => { const bar = document.querySelector('#network-controls'), header = document.querySelector('.workspace-header'); window.scrollTo({ top: scrollY + bar.getBoundingClientRect().top - header.getBoundingClientRect().bottom - 16, behavior: 'instant' }); });
    await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))));
   }
   const boxes = await Promise.all(['#network-fit', '#network-reset', '#network-discover-groups', '#network-node-select'].map(id => page.locator(id).boundingBox()));
   assert.ok(boxes.every(Boolean)); assert.ok(boxes[0].x < boxes[1].x && boxes[1].x < boxes[2].x); assert.ok(boxes[3].y >= boxes[0].y);
   const header = await page.locator('.workspace-header').boundingBox(); assert.ok(boxes.every(box => box.y >= header.y + header.height && box.y + box.height <= 1050), JSON.stringify({ width, boxes, header }));
   assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
   await page.screenshot({ path: path.join(out, `toolbar-${width}.png`) });
  }
  pass('375／768／1440工具栏顺序正确、响应式铺满、无整页横向溢出');
  // New path should clear the old overlay, then match groups for its own context.
  if (await page.locator('#path-select option').count() > 1) {
   const current = await page.locator('#path-select').inputValue(), next = current === '0' ? '1' : '0';
   await page.locator('#path-select').selectOption(next); await waitIdle(); assert.equal((await snapshot()).selected, null); assert.equal((await snapshot()).graph.collapsed_group, null);
   pass('切换路径自动更新群组列表并解除旧聚合／高亮');
  }
  // Client-only cache boundary fixture: temporary view IDs, no fabricated chain edges or API requests.
  const cacheGroup = (await snapshot()).group_ids[0]; await clickGroup(cacheGroup, true);
  await page.evaluate(async () => {
   const { state } = await import('/assets/js/state.js'), g = await import('/assets/js/groups.js'), n = await import('/assets/js/relation-network.js');
   const record = state.trace;
   for (let i = 0; i < 13; i++) { g.clearGroupContext(); const path = { path_id: 'ui_cache_boundary_' + i, nodes: [record.result.seed_address], hop_count: 0 }; n.renderNetwork(record, path); g.setGroupContext(record, path); }
   g.clearGroupContext(); n.renderNetwork(record); g.setGroupContext(record);
  });
  await page.waitForFunction(() => document.querySelector('#trace-chart').dataset.networkReady === 'true');
  const evicted = await snapshot(); assert.equal(evicted.revealed, false); assert.equal(evicted.selected, null); assert.equal(evicted.collapsed, null); assert.equal(evicted.graph.collapsed_group, null); assert.equal(evicted.graph.extra_nodes, 0);
  pass('前端缓存边界：13个临时视图后被驱逐的群组状态不会在关系图中残留');
  // Explicit UI status fixtures, isolated from real index / model results.
  const fakePath = '**/api/traces/*/groups?**';
  await page.route(fakePath, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dataset_id: 'bitcoin', enabled: false, status: 'no_index', groups: [] }) }));
  await page.locator('#network-discover-groups').click(); await waitIdle(); assert.match(await page.locator('#group-state').innerText(), /暂不可用/);
  await page.unroute(fakePath);
  await page.route(fakePath, route => route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dataset_id: 'bitcoin', enabled: true, status: 'ready', groups: [] }) }));
  await page.locator('#network-discover-groups').click(); await waitIdle(); assert.match(await page.locator('#group-state').innerText(), /未匹配到/); await page.unroute(fakePath);
  pass('前端独立状态模拟：无匹配群组与索引不可用显示不同提示，原图仍可查看');
  let release, started, finished; const gate = new Promise(resolve => { release = resolve; }), began = new Promise(resolve => { started = resolve; }), ended = new Promise(resolve => { finished = resolve; });
  await page.route(fakePath, async route => { started(); await gate; try { await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ dataset_id: 'bitcoin', enabled: true, status: 'ready', groups: [] }) }); } catch {} finally { finished(); } });
  await page.locator('#network-discover-groups').click(); await began; await page.locator('#dataset-select').selectOption('ethereum'); release(); await ended;
  assert.equal(await page.locator('#associated-groups-panel').isVisible(), false); assert.equal(await snapshot(), null); await page.unroute(fakePath);
  pass('前端延迟响应模拟：群组请求中切换数据集，旧响应不能污染新对象');
  assert.deepEqual(errors, []); assert.deepEqual(responses, []);
  fs.writeFileSync(path.join(out, 'results.json'), JSON.stringify({ scope: 'Real local BTC and scored-only ETH groups including 501-member pagination and no-path seed; explicitly labelled client-only cache/empty/unavailable/delayed-response fixtures. No LLM calls.', checks, errors, responses, requests }, null, 2));
 } catch (error) {
  await page.screenshot({ path: path.join(out, 'failure.png'), fullPage: true });
  fs.writeFileSync(path.join(out, 'failure.json'), JSON.stringify({ message: error.stack, snapshot: await snapshot(), checks, errors, responses, requests }, null, 2)); throw error;
 } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
