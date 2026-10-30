/* Two real current-object -> template report -> group fact source viewers. No LLM calls. */
const { chromium } = require('/Users/luyu/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const assert = require('node:assert/strict'), fs = require('node:fs'), path = require('node:path');
const base = process.env.WEB3AML_URL || 'http://127.0.0.1:8000', out = path.resolve(__dirname, '../artifacts/v4_frontend_check');
fs.mkdirSync(out, { recursive: true });
(async () => {
 const browser = await chromium.launch({ executablePath: '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome', headless: true });
 const context = await browser.newContext({ viewport: { width: 1440, height: 1100 } }), page = await context.newPage();
 page.setDefaultTimeout(120000); const checks = [], errors = [], requests = [];
 page.on('pageerror', error => errors.push(error.message));
 page.on('request', request => { if (new URL(request.url()).pathname.startsWith('/api/')) requests.push({ method: request.method(), url: request.url(), body: request.postData() ? JSON.parse(request.postData()) : undefined }); });
 const pass = (name, details) => { checks.push({ name, ...details }); console.log('PASS', name); };
 try {
  for (const item of [{ dataset: 'bitcoin', address: '12A6GH9vPBqvTMyLkfFWzEUXwx3xAu92Mt', group: 'dense_81c86a085a88325bac0c' }, { dataset: 'ethereum', address: '0x096c39ab4fa36ca74a36fe1f4767ff487762f0aa', group: 'dense_459c328ce9edcb4013d1' }]) {
   await page.goto(base + '/workspace/risk?dataset=' + item.dataset); await page.waitForFunction(() => document.querySelector('#service-state').textContent.includes('已就绪'));
   await page.locator('#address-input').fill(item.address); await page.locator('#analyze-button').click(); await page.waitForFunction(address => document.querySelector('#dataset-active-address').textContent === address, item.address);
   await page.locator('.module-link[data-module="report"]').click(); assert.equal(await page.locator('#report-address-input').inputValue(), item.address);
   assert.equal(await page.locator('#associated-groups-panel').isVisible(), false);
   await page.locator('#report-mode').selectOption('template'); await page.locator('#direct-report-button').click();
   await page.waitForFunction(() => !document.querySelector('#report-results').hidden && !document.querySelector('#direct-report-button').disabled);
   const record = await page.evaluate(async () => (await import('/assets/js/state.js')).state.report), report = record.report;
   assert.equal(report.source, 'template'); assert.equal(report.audit.api_calls, 0);
   const groupEntry = Object.entries(report.fact_catalog.facts).find(([, fact]) => fact.fact_type === 'dense_group' && fact.value.group_id === item.group); assert.ok(groupEntry);
   const statement = report.statements.find(s => s.claim.fact_ids.includes(groupEntry[0])); assert.ok(statement);
   await page.locator(`button[data-evidence="${statement.citation_label}"]`).click(); await page.locator('#fact-group-members').waitFor();
   const full = report.evidence_snapshot.dense_group_analysis.groups[groupEntry[1].display_locator.group_index], members = full.members, edges = full.group.internal_edges;
   await page.locator('#fact-group-members > summary').click(); await page.waitForFunction(count => document.querySelectorAll('#fact-group-member-table tbody tr').length === count, members.length);
   assert.equal(await page.locator('#fact-group-member-table tbody tr').first().locator('td').first().innerText(), members[0].address_id);
   assert.equal(await page.locator('#fact-group-member-table tbody tr').last().locator('td').first().innerText(), members.at(-1).address_id);
   await page.locator('#fact-group-edges > summary').click(); await page.waitForFunction(count => document.querySelectorAll('#fact-group-edge-table tbody tr').length === count, edges.length);
   assert.match(await page.locator('#fact-data').innerText(), /群组结构分/); assert.ok(members.every(member => member.is_scored === true && Number.isFinite(member.risk_score)));
   assert.ok(requests.filter(r => r.method === 'POST' && new URL(r.url).pathname === '/api/reports/from-address').every(r => r.body.mode === 'template'));
   pass(item.dataset + ' 当前对象预填、未点击发现即自动报告、群组引用定位和完整成员／内部边表', { report_id: record.report_id, group_id: item.group, members: members.length, edges: edges.length, api_calls: report.audit.api_calls });
   await page.locator('#evidence-content').scrollIntoViewIfNeeded(); await page.screenshot({ path: path.join(out, `${item.dataset}-report-group-evidence.png`), fullPage: true });
  }
  assert.deepEqual(errors, []); fs.writeFileSync(path.join(out, 'report-ui-results.json'), JSON.stringify({ scope: 'Real production local BTC / scored-only ETH data, template report mode, no prior discovery action and no LLM calls', checks, errors, requests }, null, 2));
 } catch (error) { await page.screenshot({ path: path.join(out, 'report-ui-failure.png'), fullPage: true }); fs.writeFileSync(path.join(out, 'report-ui-failure.json'), JSON.stringify({ message: error.stack, checks, errors, requests }, null, 2)); throw error; }
 finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
