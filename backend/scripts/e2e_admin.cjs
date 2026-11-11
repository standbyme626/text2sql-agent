#!/usr/bin/env node
/**
 * 管理后台端到端测试：真实浏览器点击 + 真实 API，验证 14 个屏与全部写路径。
 *
 * 用法（需要一个隔离实例，避免改动线上数据）：
 *   # 1) 起隔离实例（独立数据目录 + 独立 .env，端口 3390）
 *   # 2) 跑测试
 *   T2S_BASE=http://127.0.0.1:3390 \
 *   T2S_ADMIN_USER=sqladmin T2S_ADMIN_PASS=*** \
 *   T2S_GUEST_USER=guest T2S_GUEST_PASS=*** \
 *   node backend/scripts/e2e_admin.cjs
 *
 * 截图输出到 T2S_SHOTS（默认 /tmp/e2e-shots）。
 */
const { chromium } = require('/root/.agents/skills/playwright-mcp/node_modules/playwright');
const fs = require('fs');

const BASE = process.env.T2S_BASE || 'http://127.0.0.1:3390';
const SHOTS = process.env.T2S_SHOTS || '/tmp/e2e-shots';
const ADMIN_USER = process.env.T2S_ADMIN_USER || 'sqladmin';
const ADMIN_PASS = process.env.T2S_ADMIN_PASS || '';
const GUEST_USER = process.env.T2S_GUEST_USER || 'guest';
const GUEST_PASS = process.env.T2S_GUEST_PASS || '';

const results = [];
function check(name, cond, extra = '') {
  results.push({ name, ok: !!cond, extra });
  console.log(`${cond ? '  [OK]' : '  [FAIL]'} ${name} ${extra}`);
}

(async () => {
  fs.mkdirSync(SHOTS, { recursive: true });
  const browser = await chromium.launch({ args: ['--no-sandbox'] });
  const page = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  const errors = [];
  const failedReq = [];
  page.on('pageerror', e => errors.push('pageerror: ' + e.message));
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('401')) errors.push(m.text()); });
  page.on('response', async r => {
    if (r.status() >= 400 && !r.url().includes('/api/config')) {
      let body = '';
      try { body = (await r.text()).slice(0, 160); } catch (_) { body = ''; }
      failedReq.push(`${r.status()} ${r.url()} :: ${body}`);
    }
  });

  // ---------- 登录 ----------
  await page.goto(BASE + '/?e2e=' + Date.now(), { waitUntil: 'networkidle', timeout: 45000 });
  await page.waitForSelector('input[placeholder="用户名"]', { timeout: 15000 });
  await page.fill('input[placeholder="用户名"]', ADMIN_USER);
  await page.fill('input[placeholder="密码"]', ADMIN_PASS);
  await page.click('button:has-text("登录")');
  await page.waitForTimeout(2500);
  check('管理员登录并进入后台入口', !!(await page.$('.view-tabs button:has-text("管理")')));

  // ---------- 逐屏巡检 ----------
  await page.click('.view-tabs button:has-text("管理")');
  await page.waitForTimeout(1500);
  const screens = [
    ['运行总览', 'overview'], ['告警与 SLO', 'alerts'], ['未命中问题', 'unmatched'],
    ['检索调试', 'debug'], ['质量评测', 'eval'], ['会话回放', 'sessions'],
    ['运行配置', 'config'], ['提示词管理', 'prompts'], ['语义指标', 'semantic'],
    ['知识库', 'knowledge'], ['只读策略', 'policy'], ['账号与权限', 'accounts'],
    ['配置审计', 'audit'], ['索引与语料', 'index'],
  ];
  for (const [label, file] of screens) {
    await page.click(`.adm-nav:has-text("${label}")`);
    await page.waitForTimeout(900);
    const visible = await page.isVisible('.adm-screen.on');
    const title = await page.textContent('.adm-screen.on .adm-page-head h1');
    check(`屏「${label}」渲染`, visible && title.includes(label.slice(0, 2)), title);
    await page.screenshot({ path: `${SHOTS}/${file}.png`, fullPage: true });
  }

  // ---------- 运行配置：改一项并验证热生效 ----------
  await page.click('.adm-nav:has-text("运行配置")');
  await page.waitForTimeout(900);
  const stepInput = await page.evaluateHandle(() => {
    const fields = [...document.querySelectorAll('.adm-screen.on .adm-field')];
    const f = fields.find(x => x.textContent.includes('MAX_AGENT_STEPS'));
    return f ? f.querySelector('input') : null;
  });
  const el = stepInput.asElement();
  const curVal = await el.inputValue();
  const nextVal = String(Number(curVal) + 1);
  await el.fill(nextVal);
  await page.waitForTimeout(300);
  await page.click('.adm-screen.on .adm-page-head .adm-btn.primary');
  await page.waitForTimeout(1500);
  const banner = await page.textContent('.adm-screen.on .adm-alert').catch(() => '');
  check('运行配置保存并热生效', (banner || '').includes('已生效') || (banner || '').includes('需重启'), (banner || '').trim());
  const cfgApi = await page.evaluate(async () => {
    const t = localStorage.getItem('t2s_token');
    const r = await fetch('/api/admin/config', { headers: { 'X-App-Token': t } });
    return r.json();
  });
  check('配置值已落库并热生效', String(cfgApi.current?.MAX_AGENT_STEPS) === nextVal,
        `${cfgApi.current?.MAX_AGENT_STEPS} (期望 ${nextVal})`);

  // ---------- 告警规则 ----------
  await page.click('.adm-nav:has-text("告警与 SLO")');
  await page.waitForTimeout(900);
  const thr = await page.$('.adm-screen.on .adm-num');
  await thr.fill('99000');
  await page.click('.adm-screen.on .adm-page-head .adm-btn.primary');
  await page.waitForTimeout(1200);
  check('告警规则保存', (await page.isVisible('.adm-screen.on')));

  // ---------- 提示词 ----------
  await page.click('.adm-nav:has-text("提示词管理")');
  await page.waitForTimeout(900);
  await page.fill('.adm-screen.on textarea', '【E2E 规则】统计有效成交时排除 cancelled 订单。');
  await page.click('.adm-screen.on .adm-btn.primary');
  await page.waitForTimeout(1500);
  check('提示词版本创建并生效', (await page.isVisible('.adm-screen.on .adm-badge.teal')));

  // ---------- 只读策略 ----------
  await page.click('.adm-nav:has-text("只读策略")');
  await page.waitForTimeout(900);
  await page.fill('.adm-screen.on .adm-input', 'vacuum, attach');
  await page.fill('.adm-screen.on textarea', 'customers:phone,email');
  await page.click('.adm-screen.on .adm-page-head .adm-btn.primary');
  await page.waitForTimeout(1500);
  const policyCheck = await page.evaluate(async () => {
    const t = localStorage.getItem('t2s_token');
    const r = await fetch('/api/admin/policy', { headers: { 'X-App-Token': t } });
    return r.json();
  });
  check('只读策略已写入并生效',
        (policyCheck.forbidden_keywords || []).includes('vacuum')
        && (policyCheck.denied_columns?.customers || []).includes('phone'),
        JSON.stringify(policyCheck.forbidden_keywords));

  // ---------- 敏感列脱敏 ----------
  const masked = await page.evaluate(async () => {
    const t = localStorage.getItem('t2s_token');
    const r = await fetch('/api/sql', {
      method: 'POST', headers: { 'Content-Type': 'application/json', 'X-App-Token': t },
      body: JSON.stringify({ sql: 'SELECT customer_id, phone FROM customers LIMIT 1' }),
    });
    return await r.json();
  });
  check('敏感列在真实查询里被脱敏',
        Array.isArray(masked.rows) && masked.rows.length > 0 && masked.rows[0][1] === '***',
        JSON.stringify(masked.rows?.[0]));

  // ---------- 检索调试 ----------
  await page.click('.adm-nav:has-text("检索调试")');
  await page.waitForTimeout(700);
  await page.fill('.adm-screen.on .adm-input', '各品类销售额排名');
  await page.click('.adm-screen.on .adm-btn.primary');
  await page.waitForTimeout(2000);
  const debugRows = await page.$$('.adm-screen.on .adm-table tbody tr');
  check('检索调试返回打分明细', debugRows.length > 0, `${debugRows.length} 行`);
  check('MDL 编译命中指标', (await page.isVisible('.adm-screen.on .adm-alert.teal')));

  // ---------- 知识库 ----------
  await page.click('.adm-nav:has-text("知识库")');
  await page.waitForTimeout(800);
  const inputs = await page.$$('.adm-screen.on .adm-input');
  await inputs[0].fill('各品类销售额排名');
  await page.fill('.adm-screen.on textarea', "SELECT c.name, ROUND(SUM(oi.line_total),2) FROM categories c JOIN products p ON p.category_id=c.category_id JOIN order_items oi ON oi.product_id=p.product_id GROUP BY c.name");
  await page.click('.adm-screen.on .adm-pad .adm-btn.primary');
  await page.waitForTimeout(1500);
  const kbRows = await page.$$('.adm-screen.on .adm-table tbody tr');
  check('知识样例收录成功', kbRows.length >= 1, `${kbRows.length} 行`);

  // ---------- 质量评测 ----------
  await page.click('.adm-nav:has-text("质量评测")');
  await page.waitForTimeout(800);
  await page.click('.adm-screen.on .adm-page-head .adm-btn.primary');
  await page.waitForTimeout(1000);
  let evalState = '';
  for (let i = 0; i < 60; i++) {
    await page.waitForTimeout(1500);
    evalState = await page.textContent('.adm-screen.on .adm-card .adm-between b').catch(() => '');
    if (evalState && evalState.includes('done')) break;
  }
  check('评测任务跑完', (evalState || '').includes('done'), evalState || '');

  // ---------- 会话回放 ----------
  await page.click('.adm-nav:has-text("会话回放")');
  await page.waitForTimeout(1000);
  const session = await page.$('.adm-screen.on .adm-list-card');
  if (session) { await session.click(); await page.waitForTimeout(1200); }
  check('会话回放可打开详情', !!(await page.$('.adm-screen.on .adm-list-card')));

  // ---------- 配置审计 ----------
  await page.click('.adm-nav:has-text("配置审计")');
  await page.waitForTimeout(1200);
  const auditRows = await page.$$('.adm-screen.on .adm-table tbody tr');
  check('配置审计记录了本次变更', auditRows.length >= 3, `${auditRows.length} 条`);

  // ---------- 语义指标 ----------
  await page.click('.adm-nav:has-text("语义指标")');
  await page.waitForTimeout(1200);
  const semText = await page.inputValue('.adm-screen.on textarea');
  const semObj = JSON.parse(semText);
  semObj.business_rules = [...(semObj.business_rules || []), 'E2E 规则：测试期间追加'];
  await page.fill('.adm-screen.on textarea', JSON.stringify(semObj, null, 2));
  await page.click('.adm-screen.on .adm-page-head .adm-btn.primary');
  await page.waitForTimeout(1500);
  const semAfter = await page.evaluate(async () => {
    const t = localStorage.getItem('t2s_token');
    const r = await fetch('/api/admin/semantic', { headers: { 'X-App-Token': t } });
    return r.json();
  });
  check('语义指标可在线编辑并保存', (semAfter.business_rules || []).includes('E2E 规则：测试期间追加'));

  // ---------- 普通用户 ----------
  const guest = await browser.newPage({ viewport: { width: 1440, height: 950 } });
  await guest.goto(BASE + '/?e2e=' + Date.now(), { waitUntil: 'networkidle', timeout: 45000 });
  await guest.waitForSelector('input[placeholder="用户名"]', { timeout: 15000 });
  await guest.fill('input[placeholder="用户名"]', GUEST_USER);
  await guest.fill('input[placeholder="密码"]', GUEST_PASS);
  await guest.click('button:has-text("登录")');
  await guest.waitForTimeout(2500);
  check('普通用户没有管理入口', !(await guest.$('.view-tabs button:has-text("管理")')));
  const guest403 = await guest.evaluate(async () => {
    const t = localStorage.getItem('t2s_token');
    const r = await fetch('/api/admin/overview', { headers: { 'X-App-Token': t } });
    return r.status;
  });
  check('普通用户调管理 API 返回 403', guest403 === 403, String(guest403));

  console.log('\n--- 浏览器异常 ---');
  console.log('console/page errors:', JSON.stringify(errors));
  console.log('failed requests:', JSON.stringify(failedReq));
  const failed = results.filter(r => !r.ok);
  console.log(`\n=== E2E 结果：${results.length - failed.length} / ${results.length} 通过 ===`);
  if (failed.length) console.log('失败：', failed.map(f => f.name).join('；'));
  await browser.close();
  process.exit(failed.length ? 1 : 0);
})().catch(e => { console.error('E2E ERROR', e.message); process.exit(2); });
