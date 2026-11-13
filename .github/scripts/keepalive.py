"""Warm the backend and fail only on an observed, unrecovered health failure.

Process start time does not identify why Render restarted a free instance. Keep
it in the diagnostics; it cannot prove that a player encountered a cold start.

THE WARM WINDOW IS A BUDGET (13:00-06:59 UTC; see keepalive-worker/src/index.js
and core/tests/test_keepalive_budget.py). GitHub delivers some scheduled runs
hours late, so a run can START outside the window, and a 90-minute hold that
started at 06:30 would run to 08:00. Measured over six days to 2026-11-13 that
was ~2.5 hours a day of instance hours spent outside the window. So this script
does nothing when it starts outside the window, and a hold stops when the
window closes.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

# Must equal the Worker's WARM_FROM_UTC_HOUR / WARM_UNTIL_UTC_HOUR (a test reads both).
WARM_FROM_UTC_HOUR = 13
WARM_UNTIL_UTC_HOUR = 7   # exclusive

RECOVERY_SECONDS = 240
ATTEMPT_SECONDS = 80  # Outlast Render's roughly one-minute cold start.
RETRY_SECONDS = 8
PING_INTERVAL_SECONDS = 240
# The Worker's fetch handler warms the backend before answering when the window is
# open: three attempts of up to 55s with 5s pauses. Outlast that.
WORKER_PROBE_SECONDS = 190
WORKER_DEPLOY_COMMAND = "npx wrangler deploy --config keepalive-worker/wrangler.jsonc"


def in_warm_window(at):
    """`at` is an aware UTC datetime. The window wraps midnight."""
    return at.hour >= WARM_FROM_UTC_HOUR or at.hour < WARM_UNTIL_UTC_HOUR


def seconds_until_window_closes(at):
    """Seconds from `at` (inside the window) to the next WARM_UNTIL_UTC_HOUR:00 UTC."""
    close = at.replace(hour=WARM_UNTIL_UTC_HOUR, minute=0, second=0, microsecond=0)
    if close <= at:
        close += dt.timedelta(days=1)
    return (close - at).total_seconds()


def _utc_now():
    return dt.datetime.now(dt.timezone.utc)


def probe(url, timeout):
    # Bound both curl and its subprocess: retries must fit inside the job timeout.
    result = subprocess.run(
        ["curl", "--silent", "--show-error", "--fail", "--max-time", str(timeout), url],
        capture_output=True, text=True, timeout=timeout + 1, check=True,
    )
    health = json.loads(result.stdout)
    if not isinstance(health, dict) or health.get("status") != "ok":
        raise ValueError("/health did not report status=ok")
    # The endpoint deliberately tolerates DB hiccups; keepalive follows its
    # reachability contract. Record db/commit/started_at without gating on them.
    return health


def recover(url, *, budget=RECOVERY_SECONDS, fetch=probe,
            clock=time.monotonic, sleep=time.sleep, log=print):
    started = clock()
    deadline = started + budget
    attempts = 0
    last = "no response"
    while clock() < deadline:
        attempts += 1
        try:
            health = fetch(url, min(ATTEMPT_SECONDS, deadline - clock()))
            elapsed = clock() - started
            log(f"Healthy after {attempts} attempt(s), {elapsed:.1f}s: {json.dumps(health)}")
            if attempts > 1 or elapsed >= 30:
                log(f"::warning::Backend recovered after {attempts} attempt(s), {elapsed:.1f}s.")
            return health, attempts
        except (OSError, ValueError, subprocess.SubprocessError) as exc:
            # No response body or request headers: error diagnostics stay bounded.
            last = type(exc).__name__
            log(f"Attempt {attempts}: {last}; holding/retrying within the recovery window.")
        remaining = deadline - clock()
        if remaining > 0:
            sleep(min(RETRY_SECONDS, remaining))
    raise RuntimeError(f"Backend did not recover within {budget}s ({attempts} attempts; last: {last}).")


def check_worker(url, *, timeout=WORKER_PROBE_SECONDS, log=print, summary_path=None):
    """Is the Cloudflare keepalive Worker deployed? Its `fetch` handler always
    answers JSON with a boolean `warming` field (keepalive-worker/src/index.js),
    inside the window or out. Anything else - Cloudflare's 404 / error 1042 for a
    Worker that was never deployed, an HTML page, a timeout - fails, because the
    second scheduler being absent is otherwise silent: GitHub's holds alone covered
    58% of the window over the six days to 2026-11-13."""
    got = None
    try:
        result = subprocess.run(
            ["curl", "--silent", "--show-error", "--max-time", str(timeout),
             "--write-out", "\n%{http_code}", url],
            capture_output=True, text=True, timeout=timeout + 5, check=False,
        )
        body, _, code = result.stdout.rpartition("\n")
        got = f"HTTP {code or '?'}" if result.returncode == 0 else f"curl exit {result.returncode}"
        answer = json.loads(body) if result.returncode == 0 and code == "200" else None
        ok = isinstance(answer, dict) and isinstance(answer.get("warming"), bool)
        if ok:
            got = f"HTTP 200, warming={answer['warming']}"
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        ok, got = False, got or type(exc).__name__
    if ok:
        message = f"Keepalive Worker answered at {url} ({got})."
        log(message)
    else:
        message = (
            f"The keepalive Worker at {url} did not answer as its fetch handler does "
            f"(JSON with a `warming` field); got {got}. Until it is deployed the backend "
            f"has ONE unreliable scheduler (GitHub) and mornings go cold. This stays red "
            f"until the owner deploys it, which needs their Cloudflare login: "
            f"`{WORKER_DEPLOY_COMMAND}`, or the 'Deploy keepalive Worker' workflow with "
            f"a CLOUDFLARE_API_TOKEN secret. See docs/keepalive-reliability.md."
        )
        log(f"::error::{message}")
    if summary_path:
        with Path(summary_path).open("a", encoding="utf-8") as out:
            out.write(f"## Keepalive Worker\n\n- {message}\n")
    return 0 if ok else 1


def _window_label():
    return f"{WARM_FROM_UTC_HOUR:02d}:00-{WARM_UNTIL_UTC_HOUR - 1:02d}:59 UTC"


def run(url, *, hold_seconds=0, clock=time.monotonic, sleep=time.sleep,
        fetch=probe, log=print, summary_path=None, now=_utc_now):
    started_at = now()

    def summarize(lines):
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as out:
                out.write("## Backend keepalive\n\n")
                out.writelines(f"- {line}\n" for line in lines)

    if not in_warm_window(started_at):
        # A late GitHub delivery. Exit at once and green: a ping now would wake the
        # box (or keep it up) on instance hours the budget does not have.
        why = (f"Skipped: started {started_at:%H:%M} UTC, outside the {_window_label()} "
               f"warm window (GitHub delivered this scheduled run late). Nothing was "
               f"pinged; the window is an instance-hour budget.")
        log(f"::notice::{why}")
        summarize([why])
        return 0

    window_left = seconds_until_window_closes(started_at)
    window_end = clock() + window_left
    hold = min(hold_seconds, window_left)
    end = clock() + hold
    notes = []
    if hold < hold_seconds:
        notes.append(f"Hold cut from {hold_seconds}s to {int(hold)}s: the warm window "
                     f"closes at {WARM_UNTIL_UTC_HOUR:02d}:00 UTC.")
    checks, recoveries, health, error = 0, 0, None, None
    try:
        while True:
            budget = min(RECOVERY_SECONDS, window_end - clock())
            try:
                health, attempts = recover(url, budget=budget, fetch=fetch, clock=clock,
                                           sleep=sleep, log=log)
            except RuntimeError:
                if budget < RECOVERY_SECONDS:
                    # The window closed mid-recovery: stop warming, as at any other
                    # window end. Not an outage verdict either way.
                    notes.append("The warm window closed during a recovery; stopped "
                                 "without a verdict.")
                    log(f"::warning::{notes[-1]}")
                    break
                raise
            checks += 1
            recoveries += attempts > 1
            remaining = end - clock()
            if remaining <= 0:
                break
            sleep(min(PING_INTERVAL_SECONDS, remaining))
            if clock() >= end:
                break
    except RuntimeError as exc:
        error = str(exc)
        log(f"::error::{error}")
    finally:
        lines = [f"Result: {'unrecovered health failure' if error else 'healthy'}",
                 f"Successful checks: {checks}; checks requiring retries: {recoveries}",
                 *notes]
        if health:
            started = health.get("started_at")
            if isinstance(started, (int, float)) and 0 < started < 253402300800:
                boot = dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat()
                lines.append(f"Reported process start: {boot}")
            lines.append("Process start time is diagnostic; it does not establish downtime or its cause.")
            lines.append(f"Last health response: `{json.dumps(health)}`")
        if error:
            lines.append(error)
        summarize(lines)
    return 1 if error else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-seconds", type=int, default=0)
    parser.add_argument("--check-worker", metavar="URL",
                        help="probe the Cloudflare keepalive Worker instead of /health")
    args = parser.parse_args()
    if args.hold_seconds < 0:
        parser.error("--hold-seconds must be non-negative")
    if args.check_worker:
        raise SystemExit(check_worker(args.check_worker,
                                      summary_path=os.environ.get("GITHUB_STEP_SUMMARY")))
    raise SystemExit(run(os.environ["HEALTH_URL"], hold_seconds=args.hold_seconds,
                         summary_path=os.environ.get("GITHUB_STEP_SUMMARY")))
