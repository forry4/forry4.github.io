# Keep backend warm: recovery determines success

## The recurring failures

In [run #850](https://github.com/forry4/forry4.github.io/actions/runs/34896541406),
the watchdog received a healthy JSON response at 21:03:06 UTC. It nevertheless
failed because `started_at` was 16:54:55 UTC, after its 14:00 opening threshold.
The companion ping job returned HTTP 200 throughout its 90-minute run.

The earlier [run #836](https://github.com/forry4/forry4.github.io/actions/runs/34788715286)
failed because the morning cron band had not fired; its companion ping job also
returned HTTP 200 throughout.

Neither condition establishes a current keepalive failure. GitHub documents
[delayed and dropped scheduled jobs](https://docs.github.com/en/actions/how-tos/troubleshoot-workflows#scheduled-workflows-running-at-unexpected-times).
Render documents that it can [restart a free service at any time](https://render.com/docs/free#other-limitations).
A process boot time cannot distinguish a deploy, platform restart, crash, or
idle wake, or establish what latency a player experienced.

## Current behavior

Both jobs use `.github/scripts/keepalive.py`:

- Success requires an HTTP success response containing `status: ok`.
- A request can stay open for 80 seconds to complete a normal cold start.
- Transient failures are retried for up to four minutes. Recovery is reported as
  a warning and succeeds; an unrecovered failure exits nonzero.
- The long job keeps its 90-minute hold and four-minute cadence. It now also
  fails on an unrecovered outage after earlier successful checks, which the old
  shell loop could report as success.
- Every job writes its outcome, recovery counts, last health response, and boot
  timestamp to the Actions summary. Boot time is diagnostic only.
- The `/health` endpoint intentionally tolerates database hiccups. This monitor
  follows that existing reachability contract and records its `db` field.

The cron schedule and concurrency policy are unchanged. These changes correct
failure reporting and bound recovery; they do not guarantee that GitHub will
deliver a scheduled run.

## The warm window is enforced in the script (2026-11-13)

Over the six days to 2026-11-13, GitHub's holds covered 58% of the then
13:00-06:59 UTC window (0% for UTC 14-16) and, because some firings arrive hours
late, spent about 2.5 hours a day warming OUTSIDE it. The window is Render's
instance-hour budget, so a run that starts outside it exits green at once and
pings nothing, and a recovery still in progress when it closes stops without a
verdict. `keepalive.py`'s window constants must equal the Worker's; a test reads
both.

## The Cloudflare Worker must exist

On 2026-11-13 `https://forrestgames-keepalive.forry4.workers.dev/` answered
HTTP 404 (Cloudflare error 1042): the Worker had never been deployed, and nothing
reported it. The owner deployed it the same day. The watchdog now runs
`keepalive.py --check-worker "$WORKER_URL"` after its health check (even if that
failed), and passes only when the Worker answers as its `fetch` handler does:
HTTP 200 with JSON carrying a boolean `warming` field (inside the window the
handler warms the backend first, so the probe allows 190s). To (re)deploy:

    npx wrangler deploy --config keepalive-worker/wrangler.jsonc

from a machine signed in to the owner's Cloudflare account, or run
`deploy-keepalive-worker.yml` (manual) with a `CLOUDFLARE_API_TOKEN` secret.

## One warmer, one watchdog; the window just under the cap (2026-11-14)

With the Worker live, GitHub's ~20 daily 90-minute holds only duplicated it, from
a scheduler that drops over half its firings. They were removed: `keepalive.yml`
is a watchdog that runs twice a day (05:47 and 17:47 UTC), checks `/health` and
the Worker, and is on `pipeline-alerts.yml` so a failure is pushed to the owner.
The trade accepted: a Worker that stops is noticed at the next run, up to ~12h.

The window was widened, at the owner's request, to just under Render's 750
instance-hour cap: **11:00-09:59 UTC**, asleep only 10:00-10:59 UTC (3-4am PDT,
2-3am PST). With one free service a 31-day month is at most 744h; the model is
23h x 31 = 713h plus a 15-minute idle tail a day, about 721h, under the test's
725h ceiling (`core/tests/test_keepalive_budget.py`). A second free service in
the workspace would break this.

## A cold start is also our own boot

`/health` carries a `boot` block (`core/build_info.py`): `interpreter_s` (process
start to the top of `app.py`), `import_s` (our modules), `startup_s` (to the first
ASGI call, uvicorn's lifespan startup) and `total_s`. Render's own scheduling and
image pull happen before the process exists and are not in it.

Measured on prod (each a fresh deploy boot on Render's free instance):

| Commit | interpreter_s | import_s | startup_s | total_s |
|---|---|---|---|---|
| `49a0397c` (before) | 1.36 | 12.11 | 0.19 | 13.66 |
| `cdfa23e9` (after)  | 1.06 | 4.20  | 0.20 | 5.46  |

What changed: the Dockerfile precompiles the stdlib and `/app` (the official
image strips the stdlib's `.pyc`, `.dockerignore` drops ours, and a woken
instance keeps nothing it wrote), and the puzzle bank and the retired variant-Z
net load on first use, behind a lock (the net was the only thing importing numpy
at boot). `games/spender/tests/test_lazy_boot.py` holds the second half.

Not changed: the four `weights*.json` files, `value_model.json` and the S21
config are small and serve the live S bot's first move, so they still load at
import. A laptop reads 2-5s for the same import; size against prod.

## Validation

`core/tests/test_keepalive_monitor.py` replays the exact health payload rejected
by #850. It also covers a 503 followed by a one-minute wake, persistent failure,
invalid health bodies, a single check per run (and no hold creeping back), the
window's boundary minutes, a recovery cut by the window closing, and Cloudflare's
404 body for a missing Worker. `test_keepalive_budget.py` holds the window under
the cap and both files at the same backend.
