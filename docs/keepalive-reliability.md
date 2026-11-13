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

Over the six days to 2026-11-13, GitHub's holds covered 58% of the 13:00-06:59
UTC window (0% for UTC 14-16) and, because some firings arrive hours late, spent
about 2.5 hours a day warming OUTSIDE it. The window is Render's instance-hour
budget (750 h/month, shared; see `core/tests/test_keepalive_budget.py`), so:

- A run that starts outside 13:00-06:59 UTC exits successfully at once, pings
  nothing, and says so in the job summary (`Skipped: started HH:MM UTC ...`).
- A hold that started inside the window stops at 07:00 UTC; its summary says the
  hold was cut. A recovery still in progress at 07:00 stops without a verdict.
- `keepalive.py`'s window constants must equal the Worker's; a test reads both.

## The Cloudflare Worker must exist, and today it does not

On 2026-11-13 `https://forrestgames-keepalive.forry4.workers.dev/` answered
HTTP 404 (Cloudflare error 1042): the Worker had never been deployed, so the
second scheduler the design depends on was absent and nothing reported it.

The watchdog job now runs `keepalive.py --check-worker "$WORKER_URL"` after its
health check (even if that failed). It passes only when the Worker answers as its
`fetch` handler does: HTTP 200 with JSON carrying a boolean `warming` field
(inside the window the handler warms the backend first, so the probe allows
190s). **The step is red, correctly, until the owner deploys the Worker.** Either:

    npx wrangler deploy --config keepalive-worker/wrangler.jsonc

from a machine signed in to the owner's Cloudflare account, or run the
`Deploy keepalive Worker` workflow (`deploy-keepalive-worker.yml`, manual only)
after adding a `CLOUDFLARE_API_TOKEN` secret with Workers edit permission (plus
`CLOUDFLARE_ACCOUNT_ID` if the token sees more than one account). Without the
secret that workflow skips green and says so. It verifies the deploy with the
same probe.

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
by #850. It also covers a 503 followed by a one-minute wake, persistent failure
after earlier success, invalid health bodies, the full 90-minute cadence using
a fake clock, and recovery fitting inside both job timeouts.

The live one-shot check returned healthy in 0.7 seconds on 2026-09-15 UTC.
The window and Worker checks are covered in the same file, including the
boundary minutes 06:59, 07:00, 12:59 and 13:00 and Cloudflare's 404 body.
The existing keepalive budget tests still protect the warming window and target.
