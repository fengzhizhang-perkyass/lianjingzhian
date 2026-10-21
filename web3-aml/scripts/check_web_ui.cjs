/* Real Chrome regression for the promotional site and four-module workspace. */
const {
  chromium
} = require(process.env.PLAYWRIGHT_MODULE ||
  '/Users/luyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const base = process.env.WEB3AML_URL || 'http://127.0.0.1:8000';
const output = process.env.WEB3AML_CHECK_OUTPUT || path.resolve(__dirname, '../artifacts/web_ui_check');
fs.mkdirSync(output, {
  recursive: true
});

(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROME_PATH ||
      '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome',
    headless: true
  });
  const context = await browser.newContext({
    viewport: {
      width: 1440,
      height: 1000
    },
    acceptDownloads: true
  });
  const errors = [],
    results = [],
    requests = [];
  context.on('page', page => page.on('pageerror', error => errors.push(error.message)));
  const page = await context.newPage();
  page.setDefaultTimeout(60000);
  page.on('request', request => requests.push({
    url: request.url(),
    method: request.method()
  }));
  const apiCount = () => requests.filter(r => r.url.includes('/api/')).length;
  const mutations = () => requests.filter(r => r.method === 'POST').length;
  const check = (name, detail = {}) => {
    results.push({
      name,
      status: 'passed',
      ...detail
    });
    console.log('PASS', name);
  };
  const visible = selector => page.locator(selector).waitFor({
    state: 'visible'
  });
  async function go(module) {
    await page.locator(`[data-module="${module}"]`).click();
    await page.waitForURL('**/workspace/' + module);
    await visible(`[data-module-panel="${module}"]`);
    assert.equal(await page.locator('[data-module-panel]:visible').count(), 1);
  }
  async function anchor(id) {
    await page.locator(`.landing-nav a[href="/#${id}"]`).click();
    await page.waitForFunction(key => {
      if (key === 'home') return scrollY < 2;
      const top = document.getElementById(key).getBoundingClientRect().top,
        header = document.querySelector('.landing-header').getBoundingClientRect().bottom;
      return top >= header - 2 && top < header + 35;
    }, id);
  }
  async function screenshot(name, selector = null) {
    await (selector ? page.locator(selector) : page).screenshot({
      path: path.join(output, name + '.png')
    });
  }
  async function checkWidth() {
    return page.evaluate(() => ({
      viewport: innerWidth,
      document: document.documentElement.scrollWidth
    }));
  }
  try {
    const meta = await (await context.request.get(base + '/api/meta')).json();
    await page.goto(base);
    await visible('#hero-title');
    await page.waitForTimeout(250);
    assert.deepEqual(await page.locator('.landing-nav a').allTextContents(), ['首页', '项目背景', '技术路径', '证据融合']);
    assert.equal(await page.locator('#workspace-view').isVisible(), false);
    assert.match(await page.locator('#landing-view').innerText(), /基于多维证据融合的链上反洗钱与可解释研判系统/);
    assert.equal(apiCount(), 0);
    assert.equal(requests.some(r => /plotly|cytoscape|workspace\.js/.test(r.url)), false);
    check('宣传首页品牌、四导航与业务延迟加载');
    const text = await page.locator('#landing-view').innerText();
    assert.doesNotMatch(text, /非实时|快照|模板|回退|局限|未就绪|未验证|免责声明|正在连接/);
    assert.equal(await page.locator('#landing-view input,#landing-view select').count(), 0);
    check('宣传页仅呈现优势，没有业务表单或防御性文案');
    const pixels = await page.locator('#hero-network').evaluate(c => c.toDataURL());
    await page.waitForTimeout(180);
    assert.notEqual(pixels, await page.locator('#hero-network').evaluate(c => c.toDataURL()));
    await page.locator('#motion-toggle').evaluate(b => b.click());
    const paused = await page.locator('#hero-network').evaluate(c => c.toDataURL());
    await page.waitForTimeout(160);
    assert.equal(paused, await page.locator('#hero-network').evaluate(c => c.toDataURL()));
    await page.locator('#motion-toggle').evaluate(b => b.click());
    await screenshot('home-desktop');
    check('科技感动态首屏与背景暂停恢复');
    const calls = apiCount();
    await anchor('background');
    assert.equal(await page.locator('.background-stat').count(), 2);
    assert.equal(await page.locator('.policy-card').count(), 3);
    assert.equal(await page.locator('#background a').count(), 1);
    assert.match(await page.locator('#background').innerText(), /1540\+.*亿美元/s);
    assert.match(await page.locator('#background').innerText(), /上海/);
    assert.doesNotMatch(await page.locator('#background').innerText(), /香港|稳定币条例|阅读全文|免责声明/);
    await screenshot('background-desktop');
    check('项目背景数据、三张内地政策卡片与无外链展示');
    await anchor('path');
    assert.equal(await page.locator('.landing-nav a[aria-current]').innerText(), '技术路径');
    await screenshot('technology-desktop');
    await anchor('evidence');
    await screenshot('evidence-desktop');
    await anchor('home');
    assert.equal(apiCount(), calls);
    check('四锚点定位、高亮与固定导航偏移');
    const preview = await (await context.request.get(base + '/assets/content/report-preview.json'))
  .json();
    const frozen = await (await context.request.get(base + '/api/reports/' + preview.source_report_id))
      .json();
    assert.equal(preview.score, frozen.report.evidence_snapshot.risk_analysis.overall_score);
    assert.equal(preview.evidence_hash, frozen.report.audit.evidence_hash);
    assert.equal(await page.locator('.preview-paper button,.preview-paper a').count(), 0);
    assert.match(await page.locator('.preview-score').innerText(), new RegExp(preview.score.toFixed(2)));
    check('静态报告样张来自真实证据，编号只作展示');

    await page.emulateMedia({
      reducedMotion: 'reduce'
    });
    await page.locator('.landing-header [data-start-analysis]').click();
    await page.waitForURL('**/workspace/queue');
    await page.locator('#queue-table tbody tr').first().waitFor();
    assert.equal(await page.locator('[data-module-panel]:visible').count(), 1);
    assert.equal(await page.locator('#module-position').evaluate(e => e.style.width), '25%');
    assert.equal(mutations(), 0);
    check('首次进入调查优先队列，只显示当前模块');
    const stopped = await page.locator('#hero-network').evaluate(c => c.toDataURL());
    await page.waitForTimeout(150);
    assert.equal(stopped, await page.locator('#hero-network').evaluate(c => c.toDataURL()));
    check('进入工作台后宣传背景停止');
    assert.deepEqual(await page.locator('.module-link b').allTextContents(), ['调查优先队列', '地址风险分析', '关系链追踪',
      'AI分析报告'
    ]);
    const navCalls = apiCount();
    for (const [module, width] of [
        ['risk', '50%'],
        ['trace', '75%'],
        ['report', '100%'],
        ['queue', '25%']
      ]) {
      await go(module);
      assert.equal(await page.locator('#module-position').evaluate(e => e.style.width), width);
    }
    assert.equal(apiCount(), navCalls);
    check('四模块顺序、位置条与切换不重新计算');
    await page.locator('#queue-limit').selectOption('10');
    await page.waitForFunction(() => document.querySelectorAll('#queue-table tbody tr').length === 10);
    const first = await page.locator('#queue-table tbody tr').first().innerText();
    await page.locator('#queue-next').click();
    await page.waitForFunction(() => document.querySelector('#queue-page').textContent.startsWith('11'));
    const next = await page.locator('#queue-table tbody tr').first().innerText();
    assert.notEqual(first, next);
    const [csv] = await Promise.all([page.waitForEvent('download'), page.locator('#queue-download')
    .click()]);
    await csv.saveAs(path.join(output, 'risk_queue.csv'));
    await screenshot('queue-desktop');
    check('队列分页、候选与当前 CSV 下载');
    const queuePage = await page.locator('#queue-page').innerText();
    await go('risk');
    await go('queue');
    assert.equal(await page.locator('#queue-page').innerText(), queuePage);
    check('队列分页状态在模块切换后保留');
    const selected = page.waitForResponse(r => r.url().includes('/api/risk?') && r.status() === 200);
    await page.locator('[data-queue-index]').first().click();
    const selectedRecord = await (await selected).json();
    await page.waitForURL('**/workspace/risk');
    await visible('#risk-results');
    assert.equal(await page.locator('.active-address').first().innerText(), selectedRecord.address_id);
    check('队列选中地址自动进入风险分析');
    const riskResponse = page.waitForResponse(r => r.url().includes('/api/risk?') && r.status() === 200);
    await page.getByRole('button', {
      name: '未知标签高风险示例',
      exact: true
    }).click();
    const analysis = await (await riskResponse).json();
    await visible('#risk-results');
    assert.equal(await page.locator('#overall-score').innerText(), analysis.analysis.risk.overall_score
      .toFixed(2));
    await page.evaluate(() => scrollTo(0, 0));
    await screenshot('risk-desktop');
    check('真实风险、三类诊断与原有评分排布', {
      score: analysis.analysis.risk.overall_score
    });
    await page.locator('#address-input').fill('尚未提交的地址草稿');
    await go('trace');
    await go('risk');
    assert.equal(await page.locator('#address-input').inputValue(), '尚未提交的地址草稿');
    assert.equal(await page.locator('#overall-score').innerText(), analysis.analysis.risk.overall_score
      .toFixed(2));
    check('切换模块保留输入草稿及已确认地址结果');
    await page.locator('#feature-groups details').first().locator('summary').click();
    assert.equal(await page.locator('#features-behavior tbody tr').count(), analysis.analysis
      .scoring_analysis.evidence.behavior.length);
    await page.locator('#risk-results>details').first().locator('summary').click();
    await page.locator('#waterfall-chart').scrollIntoViewIfNeeded();
    await visible('#waterfall-chart.js-plotly-plot');
    check('特征表与评分核对图保留');
    assert.equal(await page.locator('#evaluation-details').count(), 0);
    assert.equal(requests.some(r => /\/api\/evaluation/.test(r.url)), false);
    assert.equal(await page.locator('#risk-model').innerText(), 'LightGBM 联合风险模型');
    assert.equal(await page.locator('#workspace-model').innerText(), 'LightGBM 联合风险模型');
    assert.doesNotMatch(await page.locator('#analysis-json').textContent(), /model_version|evidence_tree_v|EvidenceTree|experiment/);
    check('评估区与初始化已移除，模型名称不展示迭代版本');
    await page.locator('#risk-results .section-action a').click();
    await page.waitForURL('**/workspace/trace');
    assert.equal(await page.locator('#trace-results').isVisible(), false);
    check('继续关系追踪按钮切换模块，不自动搜索');
    const traceResponse = page.waitForResponse(r => r.url().endsWith('/api/traces') && r.status() ===
    200);
    await page.locator('#trace-button').click();
    const traced = await (await traceResponse).json();
    await visible('#trace-results');
    await page.locator('#path-select').selectOption(String(traced.result.top_paths.length - 1));
    assert.equal(await page.locator('#path-table tbody tr').count(), traced.result.top_paths.at(-1).nodes
      .length);
    await page.locator('#trace-chart[data-network-ready="true"]').waitFor();
    const graphState = () => page.evaluate(async () => (await import('/assets/js/relation-network.js')).networkSnapshot());
    const originalGraph = await graphState();
    assert.equal(originalGraph.trace_id, traced.trace_id);
    assert.deepEqual(originalGraph.nodes.map(n => n.id).sort(), traced.result.subgraph.nodes.map(n => n.address_id).sort());
    assert.deepEqual(originalGraph.edges.map(e => [e.source,e.target]).sort(), traced.result.subgraph.edges.map(e => [e.src,e.dst]).sort());
    for (const node of originalGraph.nodes) {
      const expected = traced.result.subgraph.nodes.find(n => n.address_id === node.id);
      assert.equal(node.risk, expected.risk_score);
      assert.equal(node.level, expected.risk_level);
    }
    await page.locator('#trace-chart').scrollIntoViewIfNeeded();
    const box = await page.locator('#trace-chart').boundingBox();
    const beforeDrag = await graphState();
    const seed = beforeDrag.nodes.find(n => n.seed);
    const graphCalls = apiCount();
    await page.mouse.move(box.x + seed.rendered.x, box.y + seed.rendered.y);
    await page.mouse.down();
    await page.mouse.move(box.x + seed.rendered.x + 65, box.y + seed.rendered.y + 40, { steps: 14 });
    await page.mouse.up();
    await page.waitForFunction(async id => {
      const g = (await import('/assets/js/relation-network.js')).networkSnapshot();
      return g && document.querySelector('#network-node-select').value === id;
    }, seed.id);
    const dragged = await graphState();
    const changed = dragged.nodes.find(n => n.id === seed.id);
    assert.ok(Math.hypot(changed.position.x-seed.position.x,changed.position.y-seed.position.y)>15, 'Actual pointer drag must move the node.');
    await page.waitForTimeout(180);
    assert.deepEqual((await graphState()).nodes.map(n=>n.position), dragged.nodes.map(n=>n.position));
    assert.equal(apiCount(), graphCalls);
    check('真实节点拖动、松开保持、风险与有向边数据一致');
    await page.locator('#path-select').selectOption('0');
    assert.deepEqual((await graphState()).nodes.map(n=>n.position), dragged.nodes.map(n=>n.position));
    assert.equal((await graphState()).zoom, dragged.zoom);
    assert.deepEqual((await graphState()).pan, dragged.pan);
    await page.locator('#path-select').selectOption(String(traced.result.top_paths.length - 1));
    await go('risk'); await go('trace');
    assert.deepEqual((await graphState()).nodes.map(n=>n.position), dragged.nodes.map(n=>n.position));
    assert.equal((await graphState()).zoom, dragged.zoom);
    assert.deepEqual((await graphState()).pan, dragged.pan);
    await page.locator('.workspace-home').click();
    await page.locator('.landing-header [data-start-analysis]').click();
    await page.waitForURL('**/workspace/trace');
    assert.deepEqual((await graphState()).nodes.map(n=>n.position), dragged.nodes.map(n=>n.position));
    assert.deepEqual((await graphState()).pan, dragged.pan);
    check('路径切换、模块切换与返回首页后恢复节点位置和视野');
    await page.locator('[data-node-move="right"]').click();
    const nudged = await graphState();
    assert.ok(nudged.nodes.find(n=>n.id===seed.id).position.x > changed.position.x);
    await page.locator('#trace-chart').focus();
    await page.keyboard.press('ArrowDown');
    assert.ok((await graphState()).nodes.find(n=>n.id===seed.id).position.y > changed.position.y);
    await page.locator('#network-fit').click();
    const fitted = await graphState();
    assert.deepEqual(fitted.nodes.map(n=>n.position), nudged.nodes.map(n=>n.id===seed.id ? ({...n.position, y:n.position.y+24/nudged.zoom}) : n.position));
    await page.locator('#network-reset').click();
    assert.deepEqual((await graphState()).nodes.map(n=>n.position), originalGraph.nodes.map(n=>n.position));
    assert.equal(apiCount(), graphCalls);
    check('方向按钮、键盘整理、适应视图与重置不触发业务计算');
    const [traceFile] = await Promise.all([page.waitForEvent('download'), page.locator('#trace-download')
      .click()
    ]);
    await traceFile.saveAs(path.join(output, 'trace.json'));
    await page.evaluate(() => scrollTo(0, 0));
    await screenshot('trace-desktop');
    check('真实方向图、逐跳明细、路径选择与 JSON 下载');
    const pathChoice = await page.locator('#path-select').inputValue(),
      traceId = traced.trace_id;
    await go('risk');
    await go('trace');
    assert.equal(await page.locator('#path-select').inputValue(), pathChoice);
    assert.match(await page.locator('#trace-download').getAttribute('href'), new RegExp(traceId));
    check('图表隐藏后恢复路径和追踪结果');
    await go('report');
    await page.locator('#report-mode').selectOption('template');
    const reportResponse = page.waitForResponse(r => r.url().endsWith('/api/reports') && r.status() ===
      200);
    await page.locator('#report-button').click();
    const record = await (await reportResponse).json();
    await visible('#report-results');
    assert.equal(record.trace_id, traced.trace_id);
    assert.equal(record.report.source, 'template');
    assert.equal(await page.locator('.citation').count(), record.report.statements.length);
    check('同一评分与追踪生成完整模板报告');
    let evidenceLabel;
    for (const kind of ['feature_attribution', 'relation_path', 'bridge_reason']) {
      const s = record.report.statements.find(s => record.report.fact_catalog.facts[s.claim.fact_ids[0]]
        .fact_type === kind);
      assert.ok(s);
      await page.locator(`[data-evidence="${s.citation_label}"]`).click();
      assert.equal(await page.locator('#evidence-content h4').innerText(), record.report.fact_catalog
        .facts[s.claim.fact_ids[0]].label);
      evidenceLabel = s.citation_label;
    }
    for (const format of ['md', 'txt', 'evidence']) {
      const [file] = await Promise.all([page.waitForEvent('download'), page.locator(
        `#report-downloads a[href$="format=${format}"]`).click()]);
      await file.saveAs(path.join(output, 'report-' + format + (format === 'evidence' ? '.json' : '.' +
        format)));
    }
    const [zip] = await Promise.all([page.waitForEvent('download'), page.getByRole('link', {
      name: '完整审计包',
      exact: false
    }).click()]);
    await zip.saveAs(path.join(output, 'audit-bundle.zip'));
    check('声明定位与全部报告下载保留');
    await page.locator('.workspace-home').click();
    await visible('#landing-view');
    assert.equal(await page.locator('#toast').isVisible(), false);
    const beforeResume = apiCount();
    await page.locator('.landing-header [data-start-analysis]').click();
    await page.waitForURL('**/workspace/report');
    assert.equal(await page.locator('#report-id').innerText(), record.report_id);
    assert.equal(await page.locator('#evidence-select').inputValue(), evidenceLabel);
    assert.equal(apiCount(), beforeResume);
    await page.locator('.report-columns').scrollIntoViewIfNeeded();
    await screenshot('report-desktop');
    check('返回宣传页再进入，恢复模块、报告与所选证据且不重算');
    await page.goBack();
    await visible('#landing-view');
    await page.goForward();
    await page.waitForURL('**/workspace/report');
    assert.equal(await page.locator('#report-id').innerText(), record.report_id);
    check('浏览器前进后退保留工作台状态');
    await page.getByText('核验机制演示：故障注入与模拟修复', {
      exact: true
    }).click();
    await page.locator('#fault-button').click();
    await page.locator('#fault-result .notice').waitFor();
    assert.match(await page.locator('#fault-result').innerText(), /模拟演示/);
    check('模拟故障注入与修复仍可使用');
    await go('trace');
    await page.locator('[name="beam_width"]').fill('6');
    assert.equal(await page.locator('#report-results').isVisible(), false);
    assert.equal(await page.locator('#trace-stale').isVisible(), true);
    assert.equal(await page.locator('#report-button').isDisabled(), true);
    check('参数变化继续使旧报告失效');
    await page.locator('.long-case>summary').click();
    await page.locator('#load-long-case').click();
    await page.waitForFunction(() => document.querySelector('#trace-mode').value === 'long' && !document
      .querySelector('#trace-button').disabled);
    await page.locator('#trace-button').click();
    await page.waitForFunction(() => !document.querySelector('#trace-button').disabled && document
      .querySelector('#trace-statistics').innerText.includes('32'));
    check('真实 32 跳长链仍可运行');
    await page.locator('#trace-chart[data-network-ready="true"]').waitFor();
    const longGraph = await graphState();
    assert.ok(longGraph.nodes.length >= 33);
    assert.ok(longGraph.nodes.every(n=>Number.isFinite(n.position.x)&&Number.isFinite(n.position.y)));
    assert.ok(longGraph.nodes.every(n=>n.rendered.x>=0&&n.rendered.x<=longGraph.width&&n.rendered.y>=0&&n.rendered.y<=longGraph.height), 'All long-path nodes must be inside the fitted viewport.');
    await page.locator('.graph-workspace').screenshot({path:path.join(output,'long-network.png')});
    check('32 跳结果以自然网络完整显示');
    await go('risk');
    await page.getByRole('button', {
      name: '低风险示例',
      exact: true
    }).click();
    await page.waitForFunction(() => !document.querySelector('#risk-results').hidden && document
      .querySelector('#risk-level').textContent.includes('LOW'));
    assert.equal(await page.locator('#trace-results').isVisible(), false);
    assert.equal(await page.locator('#report-results').isVisible(), false);
    check('新地址清除旧路径与报告');
    await go('report');
    const autoResponse = page.waitForResponse(r => r.url().endsWith('/api/reports') && r.status() ===
    200);
    await page.locator('#report-button').click();
    const auto = await (await autoResponse).json();
    await visible('#report-results');
    assert.ok(auto.generated_trace);
    await go('trace');
    assert.equal(await page.locator('#max-depth').inputValue(), String(auto.generated_trace.result.config
      .max_depth));
    assert.equal(await page.locator('#trace-mode').inputValue(), 'quick');
    check('未追踪生成报告时补全默认追踪并同步设置');
    await go('risk');
    let delayed = false;
    await page.route('**/api/risk?*', async route => {
      if (!delayed && decodeURIComponent(route.request().url()).includes(meta.examples
          .high_risk_known[0])) {
        delayed = true;
        const response = await route.fetch();
        await new Promise(r => setTimeout(r, 500));
        try {
          await route.fulfill({
            response
          });
        } catch {}
      } else await route.continue();
    });
    await page.getByRole('button', {
      name: '已知高风险示例',
      exact: true
    }).click();
    await page.getByRole('button', {
      name: '低风险示例',
      exact: true
    }).click();
    await page.waitForFunction(() => !document.querySelector('#risk-results').hidden && document
      .querySelector('#risk-level').textContent.includes('LOW'));
    await page.waitForTimeout(700);
    assert.equal(await page.locator('.active-address').first().innerText(), meta.examples.low_risk_known[
      0]);
    await page.unroute('**/api/risk?*');
    check('旧评分晚返回不能覆盖新地址');
    let fetchedResolve, releaseResolve;
    const fetched = new Promise(r => fetchedResolve = r),
      release = new Promise(r => releaseResolve = r);
    await page.route('**/api/reports', async route => {
      const response = await route.fetch();
      fetchedResolve();
      await release;
      await route.fulfill({
        response
      });
    });
    await go('report');
    const late = page.waitForResponse(r => r.url().endsWith('/api/reports') && r.status() === 200);
    await page.locator('#report-button').click();
    await fetched;
    await go('risk');
    await page.getByRole('button', {
      name: '未知标签高风险示例',
      exact: true
    }).click();
    await visible('#risk-results');
    releaseResolve();
    await late;
    await page.waitForTimeout(80);
    assert.equal(await page.locator('#report-results').isVisible(), false);
    await page.unroute('**/api/reports');
    check('旧报告晚返回不能覆盖新地址');
    await page.locator('#address-input').fill('ADDRESS_NOT_IN_SNAPSHOT');
    await page.locator('#address-form').evaluate(form => form.requestSubmit());
    await page.waitForFunction(() => document.querySelector('#address-error').textContent && !document
      .querySelector('#analyze-button').disabled);
    assert.equal(await page.locator('#risk-results').isVisible(), false);
    check('错误地址保留明确错误与重试入口');
    await page.getByRole('button', {
      name: '低风险示例',
      exact: true
    }).click();
    await visible('#risk-results');
    await go('trace');
    await page.locator('[name="risk_threshold"]').fill('100');
    await page.locator('#max-depth').focus();
    await page.keyboard.press('Home');
    await page.locator('#trace-button').click();
    await page.waitForFunction(() => !document.querySelector('#trace-button').disabled && document
      .querySelector('#graph-state').textContent === '0 条路径');
    assert.match(await page.locator('#path-table').innerText(), /未找到/);
    await go('report');
    await page.locator('#report-button').click();
    await visible('#report-results');
    assert.equal(await page.locator('#fault-kind option[value="path_score_as_risk"]').evaluate(o => o
      .disabled), true);
    check('空路径、对应报告与故障选项仍正确');
    await go('trace');
    await page.locator('#trace-chart[data-network-ready="true"]').waitFor();
    const emptyGraph = await graphState();
    assert.equal(emptyGraph.nodes.length, 1);
    assert.equal(emptyGraph.edges.length, 0);
    await go('report');
    const responsive = [];
    for (const width of [375, 768, 1024, 1440]) {
      await page.setViewportSize({
        width,
        height: 950
      });
      await page.locator('.workspace-home').click();
      await page.waitForTimeout(100);
      let sizes = await checkWidth();
      assert.ok(sizes.document <= width + 1, JSON.stringify(sizes));
      await anchor('background');
      sizes = await checkWidth();
      assert.ok(sizes.document <= width + 1);
      await screenshot('background-' + width);
      await anchor('path');
      sizes = await checkWidth();
      assert.ok(sizes.document <= width + 1);
      await anchor('evidence');
      sizes = await checkWidth();
      assert.ok(sizes.document <= width + 1);
      await page.locator('.landing-header [data-start-analysis]').click();
      await page.waitForURL('**/workspace/report');
      sizes = await checkWidth();
      assert.ok(sizes.document <= width + 1, JSON.stringify(sizes));
      const bounds = await page.locator('.module-link').evaluateAll(links => links.map(a => ({
        left: a.getBoundingClientRect().left,
        right: a.getBoundingClientRect().right
      })));
      assert.ok(bounds.every(a => a.left >= 0 && a.right <= width));
      await go('trace');
      await page.locator('#trace-chart[data-network-ready="true"]').waitFor();
      assert.ok((await checkWidth()).document <= width + 1);
      const resizedGraph = await graphState();
      assert.ok(resizedGraph.nodes.every(n=>n.rendered.x>=0&&n.rendered.x<=resizedGraph.width&&n.rendered.y>=0&&n.rendered.y<=resizedGraph.height), 'Resize must fit the actual node view.');
      await page.locator('[data-node-move="left"]').click();
      await page.locator('.graph-workspace').screenshot({path:path.join(output,'network-' + width + '.png')});
      await go('report');
      responsive.push(sizes);
      if (width === 375) {
        await screenshot('report-mobile');
        await go('queue');
        await screenshot('queue-mobile');
        await go('report');
      }
    }
    check('四种宽度下两页与完整四项导航均不溢出', {
      responsive
    });
    await page.setViewportSize({
      width: 375,
      height: 950
    });
    await page.locator('.workspace-home').click();
    await anchor('home');
    await screenshot('home-mobile');
    const still = await page.locator('#hero-network').evaluate(c => c.toDataURL());
    await page.waitForTimeout(150);
    assert.equal(still, await page.locator('#hero-network').evaluate(c => c.toDataURL()));
    check('减少动态效果模式仍可使用两页');
    await page.locator('.landing-header [data-start-analysis]').click();
    await page.waitForURL('**/workspace/report');
    await page.locator('[data-evidence]').first().click();
    await page.locator('#evidence-select').waitFor({
      state: 'visible'
    });
    assert.ok((await checkWidth()).document <= 375);
    await page.locator('#return-statement').click();
    assert.equal(await page.locator('[data-evidence]').first().evaluate(e => document.activeElement ===
      e), true);
    check('手机证据定位与返回声明保留');
    const direct = await context.newPage();
    direct.setDefaultTimeout(60000);
    await direct.goto(base + '/workspace/trace');
    await direct.locator('#service-state').getByText('本地服务已就绪', {
      exact: true
    }).waitFor();
    assert.equal(await direct.locator('[data-module-panel]:visible').getAttribute('data-module-panel'),
      'trace');
    assert.equal(await direct.locator('#trace-button').isDisabled(), true);
    await direct.close();
    check('直接访问工作台路径正常启动为空状态');
    const offline = await context.newPage();
    offline.setDefaultTimeout(60000);
    await offline.route('**/api/meta', route => route.abort());
    await offline.goto(base + '/workspace/queue');
    await offline.getByText('服务未就绪', {
      exact: true
    }).waitFor();
    assert.equal(await offline.locator('#reconnect').isVisible(), true);
    await offline.unroute('**/api/meta');
    await offline.locator('#reconnect').click();
    await offline.getByText('本地服务已就绪', {
      exact: true
    }).waitFor();
    await offline.locator('.workspace-home').click();
    await offline.locator('.landing-nav').waitFor({
      state: 'visible'
    });
    await offline.close();
    check('工作台断线恢复不影响宣传页');
    await page.goto(base + '/#path');
    await page.waitForFunction(() => document.querySelector('.landing-nav [aria-current]')
      ?.textContent === '技术路径');
    const y = await page.locator('#path').evaluate(e => e.getBoundingClientRect().top);
    assert.ok(y >= 120 && y < 160, String(y));
    await page.keyboard.press('Tab');
    assert.ok(['A', 'BUTTON'].includes(await page.evaluate(() => document.activeElement.tagName)));
    check('宣传锚点直达与键盘导航');
    assert.deepEqual(errors, []);
    const report = {
      status: 'passed',
      version: 'background_draggable_network',
      url: base,
      results,
      page_errors: errors,
      external_llm_called: false
    };
    fs.writeFileSync(path.join(output, 'result.json'), JSON.stringify(report, null, 2));
    for (const name of ['failure.json', 'failure.png']) {
      const file = path.join(output, name);
      if (fs.existsSync(file)) fs.unlinkSync(file);
    }
    console.log(JSON.stringify({
      status: 'passed',
      checks: results.length,
      output
    }));
  } catch (error) {
    fs.writeFileSync(path.join(output, 'failure.json'), JSON.stringify({
      results,
      page_errors: errors,
      error: String(error)
    }, null, 2));
    await page.screenshot({
      path: path.join(output, 'failure.png')
    });
    throw error;
  } finally {
    await browser.close();
  }
})().catch(error => {
  console.error(error);
  process.exit(1)
});
