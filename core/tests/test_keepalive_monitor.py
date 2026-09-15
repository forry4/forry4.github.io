"""Keepalive must recover transient outages without turning old restarts into failures."""
import importlib.util
import json
from pathlib import Path
import re
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("keepalive_monitor", ROOT / ".github/scripts/keepalive.py")
monitor = importlib.util.module_from_spec(spec)
spec.loader.exec_module(monitor)

# The exact healthy response that watchdog #850 rejected four hours after boot.
HEALTH = {"status": "ok", "service": "spender", "db": True,
          "commit": "8ea07b997378b892677f2d755ebc3fbe81156f3e", "started_at": 1789404895}


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_historical_restart_is_not_an_outage(tmp_path):
    clock, logs = Clock(), []
    summary = tmp_path / "summary.md"
    code = monitor.run("local", fetch=lambda *_: HEALTH, clock=clock, sleep=clock.sleep,
                       log=logs.append, summary_path=summary)
    assert code == 0
    assert not any("::error::" in line for line in logs)
    assert "2026-09-14T16:54:55+00:00" in summary.read_text()
    assert "Result: healthy" in summary.read_text()


def test_a_503_followed_by_a_held_cold_start_recovers():
    clock, logs, timeouts = Clock(), [], []

    def fetch(url, timeout):
        timeouts.append(timeout)
        if len(timeouts) == 1:
            raise subprocess.CalledProcessError(22, "curl")
        clock.sleep(60)  # The old short pinger would abort this wake.
        return HEALTH

    health, attempts = monitor.recover("local", fetch=fetch, clock=clock, sleep=clock.sleep, log=logs.append)
    assert health == HEALTH and attempts == 2
    assert timeouts == [80, 80]
    assert any("::warning::Backend recovered" in line for line in logs)


def test_persistent_failure_is_bounded_and_fails_even_after_an_earlier_success(tmp_path):
    clock, calls, logs = Clock(), [], []

    def fetch(url, timeout):
        calls.append(timeout)
        if len(calls) == 1:
            return HEALTH
        clock.sleep(timeout)
        raise subprocess.TimeoutExpired("curl", timeout)

    summary = tmp_path / "summary.md"
    code = monitor.run("local", hold_seconds=5400, fetch=fetch, clock=clock,
                       sleep=clock.sleep, log=logs.append, summary_path=summary)
    assert code == 1
    assert clock.now == monitor.PING_INTERVAL_SECONDS + monitor.RECOVERY_SECONDS
    assert calls[-1] < monitor.ATTEMPT_SECONDS  # Last attempt respects the remaining budget.
    assert any("::error::Backend did not recover" in line for line in logs)
    assert "Result: unrecovered health failure" in summary.read_text()


def test_healthy_hold_keeps_the_four_minute_cadence():
    clock, times = Clock(), []

    def fetch(*_):
        times.append(clock())
        return HEALTH

    assert monitor.run("local", hold_seconds=5400, fetch=fetch, clock=clock,
                       sleep=clock.sleep, log=lambda _: None) == 0
    assert times == list(range(0, 5400, 240))
    assert clock.now == 5400


@pytest.mark.parametrize("body", ["<html>starting</html>", "[]", '{"status":"error"}'])
def test_http_200_without_a_healthy_json_response_is_rejected(monkeypatch, body):
    monkeypatch.setattr(monitor.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, body))
    with pytest.raises(ValueError):
        monitor.probe("local", 80)


def test_database_hiccup_keeps_the_endpoints_reachability_contract(monkeypatch):
    health = {**HEALTH, "db": False}
    monkeypatch.setattr(monitor.subprocess, "run", lambda *a, **kw: subprocess.CompletedProcess(a, 0, json.dumps(health)))
    assert monitor.probe("local", 80) == health


def test_curl_and_process_both_have_bounded_timeouts(monkeypatch):
    def command(args, **kwargs):
        assert args[args.index("--max-time") + 1] == "17"
        assert kwargs["timeout"] == 18 and kwargs["check"] is True
        assert "--fail" in args
        return subprocess.CompletedProcess(args, 0, json.dumps(HEALTH))

    monkeypatch.setattr(monitor.subprocess, "run", command)
    assert monitor.probe("local", 17) == HEALTH


def test_recovery_finishes_before_both_github_job_timeouts():
    workflow = (ROOT / ".github/workflows/keepalive.yml").read_text()
    ping, watchdog = workflow.split("  warm-window-watchdog:")
    hold = int(re.search(r"--hold-seconds (\d+)", ping)[1])
    for job, work in [(ping, hold), (watchdog, 0)]:
        limit = int(re.search(r"timeout-minutes: (\d+)", job)[1]) * 60
        assert work + monitor.RECOVERY_SECONDS + 30 < limit  # checkout/exit margin
