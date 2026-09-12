// Gate for the Expert tier's wasm search, run in a real browser worker.
//
// The native arena proves the ALGORITHM; this proves the shipped ARTIFACT --
// that `orbit_search_move_json` exists in the committed wasm, answers inside a
// worker (where the Expert tier actually runs), returns a legal move, really
// searches rather than falling through to the ranker, and refuses a pending
// chain instead of inventing one. `Date.now()` is the wasm clock, so a search
// that never advanced its budget would show up here as zero simulations.
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';

const [wasmDir, fixturePath] = process.argv.slice(2);
if (!fixturePath) throw new Error('Usage: node test/orbit-expert-search.mjs WASM_DIR FIXTURE_JSON');
const routes = new Map([
  ['/orbit_core.js', [path.resolve(wasmDir, 'orbit_core.js'), 'text/javascript']],
  ['/orbit_core_bg.wasm', [path.resolve(wasmDir, 'orbit_core_bg.wasm'), 'application/wasm']],
  ['/fixture.json', [path.resolve(fixturePath), 'application/json']],
]);
const server = http.createServer(async (req, res) => {
  if (req.url === '/') { res.end('<!doctype html><title>Orbit expert search</title>'); return; }
  const route = routes.get(req.url);
  if (!route) { res.writeHead(404).end(); return; }
  try { res.setHeader('Content-Type', route[1]); res.end(await fs.readFile(route[0])); }
  catch { res.writeHead(500).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({ headless: true });
let failures = [];
try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const report = await page.evaluate(async () => {
    const base = location.origin;
    const workerSource = `
      import init, {orbit_search_move_json} from '${base}/orbit_core.js';
      onmessage = async () => {
        try {
          await init();
          const fixture = await (await fetch('${base}/fixture.json')).json();
          const results = [];
          for (let index = 0; index < fixture.positions.length; index += 1) {
            const item = fixture.positions[index];
            const started = performance.now();
            // Hard and Expert differ ONLY in this argument, so the gate runs
            // both: 1 resamples the hidden world every simulation, 0 holds one
            // coherent world for the whole call.
            const raw = orbit_search_move_json(
              JSON.stringify(item.observation), JSON.stringify(item.legal_moves),
              JSON.stringify({}), item.budget_ms, 12345, 1);
            const coherentStarted = performance.now();
            const coherentRaw = orbit_search_move_json(
              JSON.stringify(item.observation), JSON.stringify(item.legal_moves),
              JSON.stringify({}), item.budget_ms, 12345, 0);
            // Identity is the INDEX, not the label: two seats can legitimately
            // share a label (both mulligan on turn 0), and matching by label
            // silently checked one position against another's legal list.
            results.push({ index, label: item.label, elapsed: coherentStarted-started,
                           answer: JSON.parse(raw), coherent: JSON.parse(coherentRaw),
                           coherentElapsed: performance.now()-coherentStarted,
                           legal: item.legal_moves.length });
          }
          postMessage({ results });
        } catch (error) { postMessage({ error: String(error && error.stack || error) }); }
      };`;
    const url = URL.createObjectURL(new Blob([workerSource], { type: 'text/javascript' }));
    const worker = new Worker(url, { type: 'module' });
    const answer = await new Promise((resolve) => {
      worker.onmessage = (event) => resolve(event.data);
      worker.onerror = (event) => resolve({ error: String(event.message || event) });
      worker.postMessage('go');
    });
    worker.terminate();
    return answer;
  });
  if (report.error) throw new Error(`worker failed: ${report.error}`);
  const key = (move) => JSON.stringify(Object.keys(move).sort().map((k) => [k, move[k]]));
  const fixture = JSON.parse(await fs.readFile(path.resolve(fixturePath), 'utf8'));
  for (const result of report.results) {
    const where = `${result.label}#${result.index}`;
    const item = fixture.positions[result.index];
    const answer = result.answer;
    const allowed = new Set(item.legal_moves.map(key));
    if (answer.error) { failures.push(`${where}: ${answer.error}`); continue; }
    if (!answer.move || !allowed.has(key(answer.move))) {
      failures.push(`${where}: returned a move outside the legal list`); continue;
    }
    if (item.expect === 'search') {
      if (answer.fell_back) failures.push(`${where}: fell back to the ranker instead of searching`);
      else if (!(answer.simulations > 0)) failures.push(`${where}: reported ${answer.simulations} simulations`);
      else if (!Array.isArray(answer.stats) || !answer.stats.length) failures.push(`${where}: no root visits to sum across the pool`);
      else if (result.elapsed > item.budget_ms * 3 + 500) failures.push(`${where}: took ${Math.round(result.elapsed)}ms against a ${item.budget_ms}ms budget`);
      else {
        // The coherent world is the whole point of the Expert tier, so assert
        // the MECHANISM, not just that it ran. Holding one world lets a node be
        // reached twice; resampling every simulation means almost none is, so
        // the per-simulation arm expands close to one new node per simulation
        // and the coherent arm must expand meaningfully fewer.
        const co = result.coherent;
        const perSimNodes = answer.nodes / Math.max(1, answer.simulations);
        const coherentNodes = co.nodes / Math.max(1, co.simulations);
        if (co.error || !co.move || !allowed.has(key(co.move))) {
          failures.push(`${where}: coherent search returned ${co.error || 'an illegal move'}`);
        } else if (co.fell_back || !(co.simulations > 0)) {
          failures.push(`${where}: coherent search fell back instead of searching`);
        } else if (!(coherentNodes < perSimNodes)) {
          failures.push(`${where}: coherent built no more tree than per-simulation `
            + `(${coherentNodes.toFixed(2)} vs ${perSimNodes.toFixed(2)} new nodes/simulation)`);
        } else {
          console.log(`  ok  ${where}: ${answer.simulations} sims in ${Math.round(result.elapsed)}ms`
            + ` | new nodes/sim per-sim ${perSimNodes.toFixed(2)} -> coherent ${coherentNodes.toFixed(2)}`);
        }
      }
    }
    if (item.expect === 'fallback') {
      if (!answer.fell_back) failures.push(`${where}: searched a position it cannot reconstruct`);
      else console.log(`  ok  ${where}: refused and ranked (${answer.reason})`);
    }
  }
} finally { await browser.close(); server.close(); }
if (failures.length) { console.error('Orbit expert search FAILED:'); for (const f of failures) console.error(`  - ${f}`); process.exit(1); }
console.log('Orbit expert search: ok');
