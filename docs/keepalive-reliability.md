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

The cron schedule, concurrency policy, and warming window are unchanged. These
changes correct failure reporting and bound recovery; they do not guarantee that
GitHub will deliver a scheduled run. The independent Cloudflare Worker remains
configured separately, with its deployed state still requiring account access
to verify.

## Validation

`core/tests/test_keepalive_monitor.py` replays the exact health payload rejected
by #850. It also covers a 503 followed by a one-minute wake, persistent failure
after earlier success, invalid health bodies, the full 90-minute cadence using
a fake clock, and recovery fitting inside both job timeouts.

The live one-shot check returned healthy in 0.7 seconds on 2026-09-15 UTC.
The existing keepalive budget tests still protect the warming window and target.
