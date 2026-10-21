/* Additional real Chrome checks: recovery, large results, touch and metadata. */
const { chromium } = require(process.env.PLAYWRIGHT_MODULE || 'playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.WEB3AML_URL || 'http://127.0.0.1:8000';
const output = process.env.WEB3AML_CHECK_OUTPUT || path.resolve(__dirname, '../artifacts/web_network_check');
fs.mkdirSync(output, { recursive: true });

(async () => {
  const browser = await chromium.launch({ ...(process.env.CHROME_PATH ? { executablePath: process.env.CHROME_PATH } : {}), headless: true });
  const results = [], errors = [];
  const check = (name, data = {}) => { results.push({ name, status: 'passed', ...data }); console.log('PASS', name); };
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 }, acceptDownloads: true });
  context.on('page', page => page.on('pageerror', e => errors.push(e.message)));
  const page = await context.newPage();
  page.setDefaultTimeout(45000);
  const calls = [];
  page.on('request', r => { if (r.url().includes('/api/')) calls.push(r.url()); });
  const snapshot = target => target.evaluate(async () => (await import('/assets/js/relation-network.js')).networkSnapshot());
  const ready = target => target.locator('#trace-chart[data-network-ready="true"]').waitFor();
  const go = (target, module) => target.locator(`[data-module="${module}"]`).click();
  const run = async target => {
    const response = target.waitForResponse(r => r.url().endsWith('/api/traces') && r.status() === 200);
    await target.locator('#trace-button').click();
    return (await response).json();
  };
  const example = async target => {
    const response = target.waitForResponse(r => r.url().includes('/api/risk?') && r.status() === 200);
    await target.getByRole('button', { name: '未知标签高风险示例', exact: true }).click();
    await response;
  };
  try {
    await page.goto(base + '/#background');
    await page.waitForFunction(() => document.querySelector('.landing-nav [aria-current]')?.textContent === '项目背景');
    const top = await page.locator('#background').evaluate(e => e.getBoundingClientRect().top);
    const bottom = await page.locator('.landing-header').evaluate(e => e.getBoundingClientRect().bottom);
    assert.ok(top >= bottom && top < bottom + 40);
    await page.locator('.landing-nav a[href="/#path"]').click();
    await page.goBack();
    await page.waitForURL('**/#background');
    await page.waitForFunction(() => document.querySelector('.landing-nav [aria-current]')?.textContent === '项目背景');
    check('新增锚点直达、固定导航偏移与浏览器后退');

    await page.locator('.landing-header [data-start-analysis]').click();
    await go(page, 'risk');
    await example(page);
    await go(page, 'trace');
    await page.route('**/vendor/cytoscape.min.js', route => route.abort());
    const original = await run(page);
    await page.locator('#network-retry').waitFor();
    assert.ok(await page.locator('#path-table tbody tr').count() > 0);
    await go(page, 'report');
    await page.locator('#report-mode').selectOption('template');
    const reportResponse = page.waitForResponse(r => r.url().endsWith('/api/reports') && r.status() === 200);
    await page.locator('#report-button').click();
    const report = await (await reportResponse).json();
    assert.equal(report.report.audit.unresolved_final_claims, 0);
    await go(page, 'trace');
    await page.locator('#network-retry').waitFor();
    await page.unroute('**/vendor/cytoscape.min.js');
    const callsBefore = calls.length;
    await page.locator('#network-retry').click();
    await ready(page);
    assert.equal(calls.length, callsBefore);
    assert.equal((await snapshot(page)).trace_id, original.trace_id);
    await page.locator('#path-select').selectOption('0');
    const wantedEdges = original.result.top_paths[0].nodes.slice(1).map((id,i)=>[original.result.top_paths[0].nodes[i],id]);
    assert.deepEqual((await snapshot(page)).edges.filter(e=>e.highlighted).map(e=>[e.source,e.target]).sort(), wantedEdges.sort());
    check('关系图加载失败不阻断路径与报告，重试不重复分析');

    await page.locator('#trace-chart').scrollIntoViewIfNeeded();
    const box = await page.locator('#trace-chart').boundingBox();
    const beforePan = await snapshot(page);
    await page.mouse.move(box.x + 18, box.y + 18);
    await page.mouse.down();
    await page.mouse.move(box.x + 63, box.y + 42, { steps: 10 });
    await page.mouse.up();
    const panned = await snapshot(page);
    assert.ok(Math.hypot(panned.pan.x-beforePan.pan.x,panned.pan.y-beforePan.pan.y)>10);
    assert.deepEqual(panned.nodes.map(n=>n.position), beforePan.nodes.map(n=>n.position));
    await page.mouse.wheel(0, -180);
    await page.waitForFunction(async zoom => (await import('/assets/js/relation-network.js')).networkSnapshot().zoom !== zoom, panned.zoom);
    assert.equal(calls.length, callsBefore);
    check('空白区域拖动画布与滚轮缩放，不改节点坐标或请求业务接口');

    await go(page, 'risk');
    const stressRisk = page.waitForResponse(r=>r.url().includes('/api/risk?')&&r.status()===200);
    await page.locator('#address-input').fill('1GX28yLjVWux7ws4UQ9FB4MnLH4UKTPK2z');
    await page.locator('#analyze-button').click();
    await stressRisk;
    await go(page, 'trace');
    await page.locator('#trace-mode').selectOption('long');
    await page.locator('[name="beam_width"]').fill('20');
    await page.locator('[name="top_paths"]').fill('30');
    await page.locator('.settings-advanced>summary').click();
    await page.locator('[name="edge_budget"]').fill('10000');
    const expanded = await run(page);
    await ready(page);
    const graph = await snapshot(page);
    assert.equal(expanded.result.config.top_paths, 30);
    assert.equal(expanded.result.config.max_depth, 32);
    assert.equal(graph.nodes.length, expanded.result.subgraph.nodes.length);
    assert.ok(graph.nodes.every(n=>Number.isFinite(n.position.x)&&Number.isFinite(n.position.y)));
    assert.ok(graph.nodes.every(n=>n.rendered.x>=0&&n.rendered.x<=graph.width&&n.rendered.y>=0&&n.rendered.y<=graph.height));
    await page.locator('.graph-workspace').screenshot({ path: path.join(output, 'expanded-network.png') });
    const [download] = await Promise.all([page.waitForEvent('download'), page.locator('#trace-download').click()]);
    await download.saveAs(path.join(output, 'expanded-trace.json'));
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(output, 'expanded-trace.json'))), expanded.result);
    check('最大保留路径数与长链参数下完整绘图，下载保留原始结果', { nodes: graph.nodes.length, edges: graph.edges.length, paths: expanded.result.top_paths.length });

    for (const details of await page.locator('#trace-results details').all()) await details.evaluate(el=>el.open=true);
    assert.doesNotMatch(await page.locator('#trace-json').textContent(), /budgeted_relation_tracer_v|evidence_tree_v|model_version|"method"|"protocol"/);
    await go(page, 'report');
    await page.locator('#report-button').click();
    await page.locator('#report-results').waitFor({ state: 'visible' });
    for (const details of await page.locator('#report-results details').all()) await details.evaluate(el=>el.open=true);
    for (const selector of ['#audit-json','#evidence-json','#claims-json','#evidence-content']) {
      assert.doesNotMatch(await page.locator(selector).textContent(), /evidence_tree_v\d|report_claims_v\d|budgeted_relation_tracer_v\d|"model_version"|EvidenceTree[^\n]*V\d/);
    }
    check('展开的评分、搜索、证据与核验摘要不显示内部迭代版本');

    const mobileContext = await browser.newContext({ viewport: { width: 375, height: 850 }, isMobile: true, hasTouch: true });
    mobileContext.on('page', p => p.on('pageerror', e => errors.push(e.message)));
    const mobile = await mobileContext.newPage();
    mobile.setDefaultTimeout(45000);
    await mobile.goto(base + '/workspace/risk');
    await example(mobile);
    await go(mobile, 'trace');
    await run(mobile); await ready(mobile);
    await mobile.locator('#trace-chart').scrollIntoViewIfNeeded();
    const bounds = await mobile.locator('#trace-chart').boundingBox();
    const beforeTouch = await snapshot(mobile), seed = beforeTouch.nodes.find(n=>n.seed);
    const cdp = await mobileContext.newCDPSession(mobile);
    const point = { x: bounds.x+seed.rendered.x, y: bounds.y+seed.rendered.y };
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchStart', touchPoints: [point] });
    for (let i=1; i<=10; i++) await cdp.send('Input.dispatchTouchEvent', { type: 'touchMove', touchPoints: [{ x: point.x + i*5, y: point.y - i*3 }] });
    await cdp.send('Input.dispatchTouchEvent', { type: 'touchEnd', touchPoints: [] });
    const touched = await snapshot(mobile), moved = touched.nodes.find(n=>n.seed);
    assert.ok(Math.hypot(moved.position.x-seed.position.x,moved.position.y-seed.position.y)>10);
    await mobile.locator('[data-node-move="left"]').tap();
    assert.ok((await snapshot(mobile)).nodes.find(n=>n.seed).position.x < moved.position.x);
    assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await mobile.locator('.graph-workspace').screenshot({ path: path.join(output, 'network-touch.png') });
    await mobile.setViewportSize({ width: 850, height: 375 });
    assert.ok(await mobile.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
    await mobileContext.close();
    check('手机真实触摸拖动、替代按钮与横竖屏布局');

    assert.deepEqual(errors, []);
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify({ status: 'passed', url: base, results, page_errors: errors }, null, 2));
    console.log(JSON.stringify({ status: 'passed', checks: results.length }));
  } catch (error) {
    fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({ results, errors, error: String(error) }, null, 2));
    await page.screenshot({ path: path.join(output, 'failure.png') });
    throw error;
  } finally { await browser.close(); }
})().catch(e => { console.error(e); process.exitCode = 1; });
