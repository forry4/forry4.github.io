// Keeps the Render free-tier backend warm — the SECOND, INDEPENDENT scheduler.
//
// WHY THIS EXISTS. `.github/workflows/keepalive.yml` was the sole mechanism, and the
// thing that broke was not the ping, it was the SCHEDULER: GitHub drops over half of
// all scheduled firings, and whole hour-bands go dead for weeks at a time (UTC 13 and
// 14 — which held every pre-7am warm-up — fired zero times between 2026-08-27 and
// 09-06, and a push that re-registered the cron did not revive them). Measured warm
// coverage over that window was 39%, with the box cold every morning from 06:00 local
// until 09:00-10:00. No amount of re-arranging crons inside one unreliable scheduler
// fixes that, so this adds a different one. The two are complementary, not redundant:
//
//   Cloudflare (here)  — fires reliably every 5 min, so the backend never reaches the
//                        15-minute idle timeout and never spins down in the first place.
//   GitHub Actions     — holds a retrying curl open for ~90 min, which is what actually
//                        completes a wake once the box IS cold. Its firings are
//                        unreliable, but recovery only has to work occasionally.
//
// Free-plan facts this is built around (Workers Free): cron triggers are supported, the
// minimum interval is 1 minute, you get 3 triggers per Worker, and the CPU limit is 10ms
// per invocation. 10ms is CPU, not wall-clock — awaiting `fetch` is I/O and does not
// count — so holding a connection open for a cold start is fine here. One trigger is
// used; 288 invocations/day is negligible against the 100k/day request allowance.
//
// ⚠ THE WINDOW IS A BUDGET, NOT A PREFERENCE — DO NOT MAKE THIS 24/7. Render's free
// tier grants 750 INSTANCE-HOURS PER MONTH per workspace, shared across every free
// service, and blowing through them SUSPENDS the service until the next month. A month
// is ~730 hours, so keeping the backend up around the clock spends essentially the whole
// allowance and takes the site down outright if there is ever a second free service in
// the workspace. Warming 13:00-06:59 UTC is ~18h/day ≈ 547h/month, which covers
// 06:00-23:59 local in summer (PDT) and 05:00-22:59 in winter (PST) and leaves real
// margin. Widening this trades a cold morning for a dead month.

const HEALTH_URL = "https://splendid-nelz.onrender.com/health";

// Warm from 13:00 UTC through 06:59 UTC. See the instance-hour budget above before
// touching these. Local = UTC-7 (PDT) / UTC-8 (PST).
const WARM_FROM_UTC_HOUR = 13;
const WARM_UNTIL_UTC_HOUR = 7;   // exclusive

const inWarmWindow = (d) => {
  const h = d.getUTCHours();
  return h >= WARM_FROM_UTC_HOUR || h < WARM_UNTIL_UTC_HOUR;
};

// One held, retrying wake. The 30s pinger this project used before (cron-job.org) could
// not outlast Render's ~50s spin-up: it disconnected mid-wake, which ABORTS the spin-up
// rather than merely failing — Render logged nothing for two hours and the instance
// never booted. So each attempt is given longer than a cold start takes, and a failure
// is retried rather than left for the next tick.
async function warm(reason) {
  const log = [];
  for (let attempt = 1; attempt <= 3; attempt++) {
    const started = Date.now();
    try {
      const res = await fetch(HEALTH_URL, {
        signal: AbortSignal.timeout(55_000),
        cf: { cacheTtl: 0, cacheEverything: false },
        headers: { "user-agent": "forrestgames-keepalive/1 (+cloudflare-worker)" },
      });
      const ms = Date.now() - started;
      log.push(`attempt ${attempt}: HTTP ${res.status} in ${ms}ms`);
      // A 200 means the box is up and serving; nothing further to do this tick.
      if (res.ok) return { ok: true, reason, log };
    } catch (err) {
      log.push(`attempt ${attempt}: ${err.name || "error"} after ${Date.now() - started}ms`);
    }
    // Render answers 503 while it spins up. Give it room rather than hammering.
    if (attempt < 3) await new Promise((r) => setTimeout(r, 5_000));
  }
  return { ok: false, reason, log };
}

export default {
  // The cron entry point. `waitUntil` is what lets the wake outlive the handler
  // returning — without it the runtime may cancel the in-flight fetch, which is the
  // same mid-wake disconnect that made the old pinger worse than nothing.
  async scheduled(event, env, ctx) {
    if (!inWarmWindow(new Date(event.scheduledTime))) return;
    ctx.waitUntil(warm("cron").then((r) => console.log(JSON.stringify(r))));
  },

  // Hitting the Worker's URL reports what it would do and forces one wake. This exists
  // so the thing can be VERIFIED rather than assumed — the same reason /health carries
  // the deployed commit. `?force=1` warms even outside the window.
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    const now = new Date();
    const open = inWarmWindow(now);
    if (!open && url.searchParams.get("force") !== "1") {
      return Response.json({
        warming: false,
        utcHour: now.getUTCHours(),
        window: `${WARM_FROM_UTC_HOUR}:00-${WARM_UNTIL_UTC_HOUR}:00 UTC`,
        note: "outside the warm window; add ?force=1 to ping anyway",
      });
    }
    return Response.json({ warming: true, ...(await warm("manual")) });
  },
};
