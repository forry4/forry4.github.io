// Play an Expert game against the REAL backend and report what the bot does.
//
// The wasm search is healthy at its budget and the server loop is bounded, so a
// bot that never moves is an interaction bug between them. This drives the real
// protocol and prints every console error, every ai_search the room arms, and
// every ai_move the client answers with, so the stall is visible rather than
// inferred.
import { chromium } from 'playwright';
import { spawn, spawnSync } from 'node:child_process';
import path from 'node:path';
import http from 'node:http';

const repo = path.resolve(process.cwd(), '..');
const API = 8000, PORT = 5173;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const alive = (port) => new Promise((res) => {
  const req = http.get({ host: '127.0.0.1', port, path: '/health', timeout: 1500 }, (r) => { r.resume(); res(true); });
  req.on('error', () => res(false)); req.on('timeout', () => { req.destroy(); res(false); });
});

const children = [];
const stop = () => { for (const c of children) { try { spawnSync('taskkill', ['/pid', String(c.pid), '/T', '/F'], { stdio: 'ignore' }); } catch {} } };
process.on('exit', stop);

const api = spawn('python', ['-m', 'uvicorn', 'app:app', '--port', String(API)], { cwd: repo, stdio: ['ignore', 'ignore', 'inherit'], shell: true });
children.push(api);
const web = spawn('npx', ['vite', 'preview', '--port', String(PORT)], { cwd: path.join(repo, 'webapp'), stdio: ['ignore', 'ignore', 'inherit'], shell: true });
children.push(web);
const serving = (port) => new Promise((res) => {
  const req = http.get({ host: 'localhost', port, path: '/', timeout: 1500 }, (r) => { r.resume(); res(true); });
  req.on('error', () => res(false)); req.on('timeout', () => { req.destroy(); res(false); });
});
for (let i = 0; i < 60 && !(await alive(API)); i++) await wait(1000);
console.log('backend up:', await alive(API));
for (let i = 0; i < 60 && !(await serving(PORT)); i++) await wait(1000);
console.log('frontend up:', await serving(PORT));

const browser = await chromium.launch({ headless: true });
const page = await browser.newPage();
page.on('console', (m) => { if (m.type() === 'error' || m.type() === 'warning') console.log(`  [${m.type()}]`, m.text().slice(0, 300)); });
page.on('pageerror', (e) => console.log('  [pageerror]', String(e).slice(0, 400)));

const armed = [], answered = [];
await page.addInitScript(() => {
  window.__orbit = { armed: [], answered: [] };
  const OrigWS = window.WebSocket;
  window.WebSocket = function (...args) {
    const ws = new OrigWS(...args);
    ws.addEventListener('message', (e) => {
      try {
        const d = JSON.parse(e.data);
        const r = d?.room;
        if (r) window.__orbit.last = { difficulty: r.ai_difficulty, vs_ai: r.vs_ai, ai: r.ai_player,
          turn: r.game?.turn_pid, pend: r.game?.pending_pid, phase: r.game?.phase, armed: !!r.ai_search };
        const s = r?.ai_search;
        if (s) window.__orbit.armed.push({ decision: s.decision, tier: s.tier, budget_ms: s.budget_ms, at: Date.now() });
      } catch {}
    });
    const send = ws.send.bind(ws);
    ws.send = (data) => {
      try { const d = JSON.parse(data); if (d.action === 'ai_move') window.__orbit.answered.push({ decision: d.decision, at: Date.now() }); } catch {}
      return send(data);
    };
    return ws;
  };
});

await page.addInitScript(() => localStorage.setItem('spender_user',
  JSON.stringify({ id: 'expert-probe', name: 'Prober', guest: true })));
await page.goto(`http://localhost:${PORT}/orbit`, { waitUntil: 'networkidle' });
await page.waitForSelector('.orbit .lby-create-row', { timeout: 30000 });
await page.locator('.lby-cta').click();
await page.waitForSelector('.cm-panel', { timeout: 10000 });
await page.locator('.cm-seg-btn', { hasText: 'VS AI' }).click();
await page.locator('.cm-seg-btn', { hasText: 'Expert' }).click();
await page.locator('.cm-create').click();
console.log('created an Expert room');
// The opening mulligan is simultaneous: until the human submits, the bot is
// legitimately waiting and nothing is armed.
await page.waitForSelector('.or-mulligan', { timeout: 30000 });
await page.locator('.or-mulligan .or-primary').click({ timeout: 10000 });
console.log('human mulligan submitted');
// Play one human action so the bot actually gets a turn -- until then it is
// correctly idle and nothing is armed.
await page.waitForSelector('.or-hand-zone .or-agent.playable', { timeout: 30000 });
await page.locator('.or-hand-zone .or-agent.playable').first().click();
const recruit = page.locator('.or-action-bar button:not(:disabled)', { hasText: 'Recruit' });
const action = (await recruit.count().catch(() => 0)) ? recruit.first()
  : page.locator('.or-action-bar button:not(:disabled)').first();
await action.click({ timeout: 10000 });
console.log('human action played — the bot now owes a move');

for (let i = 0; i < 24; i++) {
  await wait(5000);
  const st = await page.evaluate(() => ({
    ...window.__orbit,
    backend: window.__orbitBackend || null,
    text: (document.querySelector('.or-status') || document.querySelector('.orbit'))?.innerText?.slice(0, 120) || '',
  }));
  console.log(`t+${(i + 1) * 5}s armed=${st.armed.length} answered=${st.answered.length} room=${JSON.stringify(st.last || null)} lastArmed=${JSON.stringify(st.armed.at(-1) || null)}`);
  if (st.answered.length >= 2) { console.log('bot answered at least twice — not stuck'); break; }
}
const final = await page.evaluate(() => window.__orbit);
console.log('ARMED   :', JSON.stringify(final.armed.slice(0, 8)));
console.log('ANSWERED:', JSON.stringify(final.answered.slice(0, 8)));
await browser.close();
stop();
process.exit(0);
