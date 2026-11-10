// Requires: npm i playwright-core (any recent version) and Google Chrome installed. Run from a folder with that node_modules:
//   node tools/command_center_check.mjs <patched site folder>
// Headless check of the patched Command Center: password sign-in with Supabase Auth and the API simulated.
// Usage: node check.mjs <patched site folder>
import { chromium } from 'playwright-core';
import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';

const dir = process.argv[2];
const PORT = 8765;
const SB = 'https://ghzecqhfbtgrhbibqicp.supabase.co';
const CORS = { 'access-control-allow-origin': '*', 'access-control-allow-headers': '*', 'access-control-allow-methods': '*' };

const srv = http.createServer((req, res) => {
  let p = req.url.split('?')[0].split('#')[0];
  if (p === '/') p = '/index.html';
  const f = path.join(dir, p);
  if (fs.existsSync(f) && fs.statSync(f).isFile()) {
    res.writeHead(200, { 'content-type': p.endsWith('.html') ? 'text/html; charset=utf-8' : 'application/octet-stream' });
    fs.createReadStream(f).pipe(res);
  } else { res.writeHead(404); res.end('not found'); }
});
await new Promise(r => srv.listen(PORT, '127.0.0.1', r));

const b64 = o => Buffer.from(JSON.stringify(o)).toString('base64url');
const now = Math.floor(Date.now() / 1000);
const jwt = b64({ alg: 'HS256', typ: 'JWT' }) + '.' + b64({ sub: 'u1', email: 'staff@example.com', aud: 'authenticated', role: 'authenticated', iat: now, exp: now + 3600 }) + '.sig';
const user = { id: 'u1', aud: 'authenticated', role: 'authenticated', email: 'staff@example.com', app_metadata: { provider: 'email', providers: ['email'] }, user_metadata: {}, identities: [], created_at: new Date().toISOString(), updated_at: new Date().toISOString() };
const session = { access_token: jwt, token_type: 'bearer', expires_in: 3600, expires_at: now + 3600, refresh_token: 'r1', user };

const browser = await chromium.launch({ channel: 'chrome', headless: true });
const page = await (await browser.newContext()).newPage();
const errors = [];
page.on('pageerror', e => errors.push('pageerror: ' + e.message));
page.on('console', m => { if (m.type() === 'error') errors.push('console: ' + m.text()); });

const pwCalls = []; let otpCalls = 0; let meAuth = null;
await page.route(SB + '/**', route => {
  const req = route.request(); const u = req.url();
  if (req.method() === 'OPTIONS') return route.fulfill({ status: 204, headers: CORS });
  if (u.includes('/auth/v1/token') && u.includes('grant_type=password')) { pwCalls.push(JSON.parse(req.postData() || '{}')); return route.fulfill({ status: 200, contentType: 'application/json', headers: CORS, body: JSON.stringify(session) }); }
  if (u.includes('/auth/v1/otp')) { otpCalls++; return route.fulfill({ status: 200, contentType: 'application/json', headers: CORS, body: '{}' }); }
  if (u.includes('/auth/v1/logout')) return route.fulfill({ status: 204, headers: CORS });
  if (u.includes('/auth/v1/user')) return route.fulfill({ status: 200, contentType: 'application/json', headers: CORS, body: JSON.stringify(user) });
  return route.fulfill({ status: 404, contentType: 'application/json', headers: CORS, body: '{}' });
});
await page.route(`http://127.0.0.1:${PORT}/api/me`, route => { meAuth = route.request().headers()['authorization'] || null; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ email: 'staff@example.com', role: 'admin', mfa_required: false }) }); });
let todayAuth = null; const recordCalls = [];
await page.route(`http://127.0.0.1:${PORT}/api/today`, route => { todayAuth = route.request().headers()['authorization'] || null; return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ date: '2026-11-09', mine: { deals_overdue: 1, deals_due_today: 2, activities_overdue: 3, activities_due_today: 4, open_deals: 5 }, all: { deals_overdue: 6, deals_due_today: 7, activities_overdue: 8, activities_due_today: 9, open_deals: 10 }, deals: [], activities: [] }) }); });
for (const p of ['properties', 'prospects', 'residents', 'conflict-log']) await page.route(`http://127.0.0.1:${PORT}/api/${p}`, route => { recordCalls.push(p); return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }); });

const adminShown = () => page.waitForFunction(() => /\(admin\)/.test((document.querySelector('#gwWho') || {}).textContent || ''), null, { timeout: 10000 });

await page.goto(`http://127.0.0.1:${PORT}/#data`);
await page.waitForTimeout(800);
const fresh = await page.textContent('#gwWho');
await page.fill('#apiUrl', `http://127.0.0.1:${PORT}`); await page.dispatchEvent('#apiUrl', 'change');
await page.fill('#sbKey', 'sb_publishable_test'); await page.dispatchEvent('#sbKey', 'change');
await page.waitForTimeout(400);
const keyed = await page.textContent('#gwWho');
await page.fill('#gwEmail', 'staff@example.com');
await page.fill('#gwPass', 'correct horse battery');
await page.press('#gwPass', 'Enter');
await adminShown();
const afterSignIn = await page.textContent('#gwWho');
const passFieldAfter = await page.inputValue('#gwPass');
await page.reload(); await page.waitForTimeout(800); await adminShown();
const afterReload = await page.textContent('#gwWho');
// Counts only (2026-11-09): the Today button must call /api/today with the bearer token and never the record endpoints.
// page.evaluate below runs the page's own CC.sync in the headless browser (Playwright API, not JS eval of untrusted input).
const pullButtonGone = (await page.$$('button[onclick="CC.sync(\'pull\')"]')).length === 0;
await page.evaluate(() => window.CC.sync('today'));
await page.waitForFunction(() => /Today \(2026-11-09\)/.test((document.querySelector('#gwToday') || {}).textContent || ''), null, { timeout: 10000 });
const todayText = await page.textContent('#gwToday');
const todayLink = await page.$eval('#gwToday a', a => a.getAttribute('href'));
console.log('step: signed in and reload OK; forcing sign-out click past #ccLock'); await page.$eval('#gwSignOut', b => b.click()); await page.waitForTimeout(2000);
const afterSignOut = await page.textContent('#gwWho');

console.log(JSON.stringify({ fresh, keyed, afterSignIn, passFieldAfter, afterReload, pullButtonGone, todayText, todayLink, todayAuthPrefix: todayAuth && todayAuth.slice(0, 14), recordCalls, afterSignOut, pwCalls: pwCalls.map(c => ({ email: c.email, password: c.password })), otpCalls, meAuthPrefix: meAuth && meAuth.slice(0, 14), errors }, null, 1));
await browser.close(); srv.close();
