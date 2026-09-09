// Experimental artifact benchmark; never opens a live game or changes shipped assets.
import { chromium } from 'playwright';
import http from 'node:http';
import fs from 'node:fs/promises';
import path from 'node:path';

const [wasmDir, fixturePath, outputPath] = process.argv.slice(2);
if (!outputPath) throw new Error('Usage: node test/orbit-neural-bench.mjs WASM_DIR FIXTURE_JSON REPORT_JSON');
const routes = new Map([
  ['/orbit_core.js', [path.resolve(wasmDir, 'orbit_core.js'), 'text/javascript']],
  ['/orbit_core_bg.wasm', [path.resolve(wasmDir, 'orbit_core_bg.wasm'), 'application/wasm']],
  ['/fixture.json', [path.resolve(fixturePath), 'application/json']],
]);
const server = http.createServer(async (req, res) => {
  if (req.url === '/') { res.end('<!doctype html><title>Orbit neural benchmark</title>'); return; }
  const route = routes.get(req.url);
  if (!route) { res.writeHead(404).end(); return; }
  try { res.setHeader('Content-Type', route[1]); res.end(await fs.readFile(route[0])); }
  catch { res.writeHead(500).end(); }
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const browser = await chromium.launch({headless:true});
try {
  const page = await browser.newPage();
  await page.goto(`http://127.0.0.1:${server.address().port}/`);
  const report = await page.evaluate(async () => {
    const base = location.origin;
    const workerSource = `
      import init, {orbit_neural_load_json, orbit_neural_value_json} from '${base}/orbit_core.js';
      onmessage = async () => {
        try {
          const cold = performance.now();
          const fixture = await (await fetch('${base}/fixture.json')).json();
          await init();
          const loaded = JSON.parse(orbit_neural_load_json(JSON.stringify(fixture.model)));
          if (!loaded.loaded) throw new Error(JSON.stringify(loaded));
          const coldMs = performance.now()-cold;
          let maxError=0; const times=[];
          for (let repeat=0;repeat<3;repeat++) for (const f of fixture.fixtures) {
            const start=performance.now();
            const result=JSON.parse(orbit_neural_value_json(JSON.stringify(f.observation)));
            const elapsed=performance.now()-start;
            if (result.error) throw new Error(result.error);
            const error=Math.abs(result.logit-f.logit);
            if (!(error<=1e-4)) throw new Error('WASM parity failure '+error);
            maxError=Math.max(maxError,error);
            if (repeat) times.push(elapsed);
          }
          postMessage({coldMs,times,maxError,fixtures:fixture.fixtures.length});
        } catch(e) { postMessage({error:String(e)}); }
      };
    `;
    const url=URL.createObjectURL(new Blob([workerSource],{type:'text/javascript'}));
    const results=[];
    const maxWorkers=Math.max(1,Math.min(navigator.hardwareConcurrency-1,4));
    for (const count of [...new Set([1,maxWorkers])]) {
      const started=performance.now();
      const runs=await Promise.all(Array.from({length:count},()=>new Promise((resolve,reject)=>{
        const w=new Worker(url,{type:'module'});
        const timeout=setTimeout(()=>{w.terminate();reject(new Error('worker timeout'));},60000);
        w.onmessage=({data})=>{clearTimeout(timeout);w.terminate();data.error?reject(new Error(data.error)):resolve(data);};
        w.onerror=e=>{clearTimeout(timeout);w.terminate();reject(new Error(e.message));};
        w.postMessage({});
      })));
      const times=runs.flatMap(r=>r.times).sort((a,b)=>a-b);
      results.push({workers:count,p50Ms:times[Math.floor(times.length*.5)],p95Ms:times[Math.floor(times.length*.95)],
        maxLogitError:Math.max(...runs.map(r=>r.maxError)),coldMs:Math.max(...runs.map(r=>r.coldMs)),
        wallMs:performance.now()-started,measuredEvaluations:times.length});
    }
    URL.revokeObjectURL(url);
    return {hardwareConcurrency:navigator.hardwareConcurrency,results,
      scope:'Headless Chromium workers, full observation-to-value; development fixtures; no search/strength claim'};
  });
  await fs.writeFile(outputPath, JSON.stringify(report,null,2));
  console.log(JSON.stringify(report,null,2));
} finally { await browser.close(); await new Promise(resolve=>server.close(resolve)); }
