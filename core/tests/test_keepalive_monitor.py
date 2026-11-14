"""The keepalive watchdog must recover transient outages without turning old restarts
into failures, and must spend no instance hours outside the Worker's warm window."""
import datetime as dt
import functools
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


def utc(hour, minute=0):
    return dt.datetime(2026, 11, 13, hour, minute, tzinfo=dt.timezone.utc)


FROM, UNTIL = monitor.WARM_FROM_UTC_HOUR, monitor.WARM_UNTIL_UTC_HOUR
# Mid-window, hours before it closes: the window plays no part in these.
IN_WINDOW = utc(15)
run = functools.partial(monitor.run, now=lambda: IN_WINDOW)


class Clock:
    now = 0

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


def test_historical_restart_is_not_an_outage(tmp_path):
    clock, logs = Clock(), []
    summary = tmp_path / "summary.md"
    code = run("local", fetch=lambda *_: HEALTH, clock=clock, sleep=clock.sleep,
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


def test_persistent_failure_is_bounded_and_fails(tmp_path):
    clock, calls, logs = Clock(), [], []

    def fetch(url, timeout):
        calls.append(timeout)
        clock.sleep(timeout)
        raise subprocess.TimeoutExpired("curl", timeout)

    summary = tmp_path / "summary.md"
    code = run("local", fetch=fetch, clock=clock,
                       sleep=clock.sleep, log=logs.append, summary_path=summary)
    assert code == 1
    assert clock.now == monitor.RECOVERY_SECONDS
    assert calls[-1] < monitor.ATTEMPT_SECONDS  # Last attempt respects the remaining budget.
    assert any("::error::Backend did not recover" in line for line in logs)
    assert "Result: unrecovered health failure" in summary.read_text()


def test_a_healthy_check_pings_once_and_returns():
    clock, times = Clock(), []
    assert run("local", fetch=lambda *_: times.append(clock()) or HEALTH, clock=clock,
               sleep=clock.sleep, log=lambda _: None) == 0
    assert times == [0] and clock.now == 0


def test_there_is_no_hold_any_more():
    # The Worker warms; the workflow only checks. A hold creeping back would spend
    # GitHub minutes duplicating the Worker from a scheduler that drops half its runs.
    workflow = (ROOT / ".github/workflows/keepalive.yml").read_text()
    assert "--hold-seconds" not in workflow and "hold_seconds" not in (ROOT / ".github/scripts/keepalive.py").read_text()
    assert len(re.findall(r"- cron:", workflow)) == 2


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


def test_recovery_and_the_worker_probe_finish_before_the_job_timeout():
    workflow = (ROOT / ".github/workflows/keepalive.yml").read_text()
    watchdog = workflow.split("  warm-window-watchdog:")[1]
    # The watchdog also waits out the Worker probe (which warms before it answers).
    limit = int(re.search(r"timeout-minutes: (\d+)", watchdog)[1]) * 60
    assert monitor.WORKER_PROBE_SECONDS + 5 + monitor.RECOVERY_SECONDS + 30 < limit


# ── the warm window ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("hour,minute", [(UNTIL, 0), (UNTIL, 30), (FROM - 1, 59)])
def test_a_late_firing_outside_the_window_pings_nothing_and_passes(tmp_path, hour, minute):
    clock, logs, calls = Clock(), [], []
    summary = tmp_path / "summary.md"
    code = monitor.run("local", fetch=lambda *a: calls.append(a) or HEALTH,
                       clock=clock, sleep=clock.sleep, log=logs.append,
                       summary_path=summary, now=lambda: utc(hour, minute))
    assert code == 0 and calls == [] and clock.now == 0
    text = summary.read_text()
    assert f"started {hour:02d}:{minute:02d} UTC" in text
    assert f"outside the {FROM:02d}:00-{UNTIL - 1:02d}:59 UTC" in text
    assert any(line.startswith("::notice::Skipped") for line in logs)


@pytest.mark.parametrize("hour,minute", [(FROM, 0), (UNTIL - 1, 59), (23, 59), (0, 0)])
def test_every_minute_inside_the_window_checks(hour, minute):
    calls = []
    code = monitor.run("local", fetch=lambda *a: calls.append(a) or HEALTH, clock=Clock(),
                       sleep=lambda _: None, log=lambda _: None, now=lambda: utc(hour, minute))
    assert code == 0 and len(calls) == 1


def test_the_window_closing_mid_recovery_stops_without_a_verdict():
    clock, logs = Clock(), []

    def fetch(url, timeout):
        clock.sleep(timeout)
        raise subprocess.TimeoutExpired("curl", timeout)

    code = monitor.run("local", fetch=fetch, clock=clock, sleep=clock.sleep,
                       log=logs.append, now=lambda: utc(UNTIL - 1, 58))
    assert code == 0 and clock.now == 120  # never past the window's close
    assert not any("::error::" in line for line in logs)


def test_the_window_is_the_one_just_under_the_cap():
    # 11:00-09:59 UTC: asleep only for 10:00-10:59 (3-4am PDT / 2-3am PST).
    assert (FROM, UNTIL) == (11, 10)


def test_the_window_matches_the_workers():
    worker = (ROOT / "keepalive-worker/src/index.js").read_text(encoding="utf-8")
    for name in ("WARM_FROM_UTC_HOUR", "WARM_UNTIL_UTC_HOUR"):
        assert int(re.search(rf"^const {name} = (\d+);", worker, re.M)[1]) == getattr(monitor, name), (
            f"{name} differs between keepalive.py and the Worker: the two pingers would warm "
            f"different windows, and the budget test reads only the Worker's"
        )


# ── the Cloudflare Worker must exist ─────────────────────────────────────────

WORKER_URL = "https://forrestgames-keepalive.forry4.workers.dev/"


def _curl_answers(monkeypatch, stdout, returncode=0):
    seen = {}

    def command(args, **kwargs):
        seen["args"], seen["kwargs"] = args, kwargs
        return subprocess.CompletedProcess(args, returncode, stdout)

    monkeypatch.setattr(monitor.subprocess, "run", command)
    return seen


@pytest.mark.parametrize("answer", [{"warming": False, "utcHour": 9},
                                    {"warming": True, "ok": True, "log": []}])
def test_a_deployed_worker_passes_in_or_out_of_the_window(monkeypatch, tmp_path, answer):
    seen = _curl_answers(monkeypatch, json.dumps(answer) + "\n200")
    summary = tmp_path / "s.md"
    assert monitor.check_worker(WORKER_URL, log=lambda _: None, summary_path=summary) == 0
    assert seen["kwargs"]["timeout"] > monitor.WORKER_PROBE_SECONDS  # bounded
    assert f"warming={answer['warming']}" in summary.read_text()


@pytest.mark.parametrize("stdout,code,got", [
    ("error code: 1042\n404", 0, "HTTP 404"),            # 2026-11-13: never deployed
    ("<html>hello</html>\n200", 0, "HTTP 200"),          # something else on the route
    ('{"status":"ok"}\n200', 0, "HTTP 200"),            # JSON, but not the Worker's
    ("", 28, "curl exit 28"),                             # timed out
])
def test_anything_but_the_workers_answer_fails_loudly(monkeypatch, tmp_path, stdout, code, got):
    _curl_answers(monkeypatch, stdout, code)
    logs, summary = [], tmp_path / "s.md"
    assert monitor.check_worker(WORKER_URL, log=logs.append, summary_path=summary) == 1
    error = next(line for line in logs if line.startswith("::error::"))
    assert got in error and WORKER_URL in error
    # It must say how to fix it, with the exact command the Worker's config documents.
    assert monitor.WORKER_DEPLOY_COMMAND in error
    wrangler = (ROOT / "keepalive-worker/wrangler.jsonc").read_text(encoding="utf-8")
    assert monitor.WORKER_DEPLOY_COMMAND in wrangler
    assert "docs/keepalive-reliability.md" in error and "## Keepalive Worker" in summary.read_text()


def test_the_watchdog_probes_the_worker_even_after_a_health_failure():
    workflow = (ROOT / ".github/workflows/keepalive.yml").read_text()
    watchdog = workflow.split("  warm-window-watchdog:")[1]
    step = watchdog[watchdog.index("--check-worker") - 400:]
    assert '--check-worker "$WORKER_URL"' in watchdog and "!cancelled()" in step
    assert f"WORKER_URL: {WORKER_URL}" in workflow
    assert "forrestgames-keepalive" in (ROOT / "keepalive-worker/wrangler.jsonc").read_text()


def test_the_worker_deploy_workflow_is_manual_and_skips_without_a_token():
    import yaml
    path = ROOT / ".github/workflows/deploy-keepalive-worker.yml"
    wf = yaml.safe_load(path.read_text(encoding="utf-8"))
    triggers = wf.get("on", wf.get(True))  # YAML 1.1 reads a bare `on` as True
    assert set(triggers) == {"workflow_dispatch"}, "deploying the Worker is by hand only"
    steps = wf["jobs"]["deploy"]["steps"]
    gate = steps[0]
    assert 'if [ -z "$CLOUDFLARE_API_TOKEN" ]' in gate["run"] and "deploy=false" in gate["run"]
    assert all(st.get("if") == "steps.gate.outputs.deploy == 'true'" for st in steps[1:])
    assert any("keepalive-worker/wrangler.jsonc" in st.get("run", "") for st in steps)
    assert any("--check-worker" in st.get("run", "") for st in steps)
