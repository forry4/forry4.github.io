"""Warm the backend and fail only on an observed, unrecovered health failure.

Process start time does not identify why Render restarted a free instance. Keep
it in the diagnostics; it cannot prove that a player encountered a cold start.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
import subprocess
import time

RECOVERY_SECONDS = 240
ATTEMPT_SECONDS = 80  # Outlast Render's roughly one-minute cold start.
RETRY_SECONDS = 8
PING_INTERVAL_SECONDS = 240


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


def run(url, *, hold_seconds=0, clock=time.monotonic, sleep=time.sleep,
        fetch=probe, log=print, summary_path=None):
    end = clock() + hold_seconds
    checks, recoveries, health, error = 0, 0, None, None
    try:
        while True:
            health, attempts = recover(url, fetch=fetch, clock=clock, sleep=sleep, log=log)
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
        if summary_path:
            with Path(summary_path).open("a", encoding="utf-8") as out:
                out.write("## Backend keepalive\n\n")
                out.write(f"- Result: {'unrecovered health failure' if error else 'healthy'}\n")
                out.write(f"- Successful checks: {checks}; checks requiring retries: {recoveries}\n")
                if health:
                    started = health.get("started_at")
                    if isinstance(started, (int, float)) and 0 < started < 253402300800:
                        boot = dt.datetime.fromtimestamp(started, dt.timezone.utc).isoformat()
                        out.write(f"- Reported process start: {boot}\n")
                    out.write("- Process start time is diagnostic; it does not establish downtime or its cause.\n")
                    out.write(f"- Last health response: `{json.dumps(health)}`\n")
                if error:
                    out.write(f"- {error}\n")
    return 1 if error else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--hold-seconds", type=int, default=0)
    args = parser.parse_args()
    if args.hold_seconds < 0:
        parser.error("--hold-seconds must be non-negative")
    raise SystemExit(run(os.environ["HEALTH_URL"], hold_seconds=args.hold_seconds,
                         summary_path=os.environ.get("GITHUB_STEP_SUMMARY")))
