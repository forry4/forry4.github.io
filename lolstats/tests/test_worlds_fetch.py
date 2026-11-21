"""worlds.py against a Liquipedia that refuses. A 429 is an IP BLOCK (its page says so,
lifted by CAPTCHA or time), so it exits TEMPFAIL at once for the workflow to try another
day on another runner; a 5xx or the API's own `ratelimited` is waited out; anything else
fails at once and SAYS what came back, and on a runner that reason is a public annotation.
2026-11-16's weekly run died on its first request with only "exit code 1" to read."""
import email.message
import importlib.util
import io
import json
import os
import subprocess
import sys
import urllib.error

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
spec = importlib.util.spec_from_file_location("worlds", os.path.join(TOOLS, "worlds.py"))
worlds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worlds)

OK = {"parse": {"text": {"*": "<div></div>"}}}


class R(io.BytesIO):
    headers = email.message.Message()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def _http(code, retry_after=None, body=b"Too Many Requests"):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(worlds.API, code, "refused", h, io.BytesIO(body))


def _serve(monkeypatch, answers):
    """urlopen answers each request with the next item: an exception to raise, or a dict."""
    seen = []

    def fake(req, timeout=None):
        seen.append(req.full_url)
        a = answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return R(json.dumps(a).encode())

    monkeypatch.setattr(worlds.urllib.request, "urlopen", fake)
    return seen


def test_a_429_is_a_block_and_is_never_retried(monkeypatch):
    # Retrying a blocked IP for minutes only hammers the block (measured 2026-11-21: four
    # tries over six minutes, all 429).
    seen = _serve(monkeypatch, [_http(429, body=b"<title>Rate Limited - Liquipedia</title>"), OK])
    waits = []
    with pytest.raises(worlds.Blocked, match="HTTP 429"):
        worlds.get({"action": "parse", "page": "p"}, sleep=waits.append)
    assert waits == [] and len(seen) == 1


def test_a_5xx_is_waited_out_for_as_long_as_retry_after_says(monkeypatch):
    seen = _serve(monkeypatch, [_http(503, retry_after=90), OK])
    waits = []
    assert worlds.get({"action": "parse", "page": "p"}, sleep=waits.append) == OK
    assert waits == [90] and len(seen) == 2


def test_a_wait_never_breaks_the_one_request_per_30s_rule(monkeypatch):
    _serve(monkeypatch, [_http(502, retry_after=1), OK])
    waits = []
    worlds.get({"action": "parse", "page": "p"}, sleep=waits.append)
    assert waits == [31]


def test_an_api_ratelimit_is_retried_too(monkeypatch):
    _serve(monkeypatch, [{"error": {"code": "ratelimited", "info": "slow down"}}, OK])
    waits = []
    assert worlds.get({"action": "parse", "page": "p"}, sleep=waits.append) == OK
    assert waits == [60]


def test_a_refusal_that_will_not_pass_fails_at_once_and_names_itself(monkeypatch):
    seen = _serve(monkeypatch, [_http(403, body=b"Forbidden by Cloudflare")])
    with pytest.raises(SystemExit, match=r"HTTP 403 .*Forbidden by Cloudflare"):
        worlds.get({"action": "parse", "page": "p"}, sleep=lambda s: None)
    assert len(seen) == 1


def test_a_transient_refusal_still_fails_once_the_tries_run_out(monkeypatch):
    seen = _serve(monkeypatch, [_http(503)] * worlds.TRIES)
    with pytest.raises(SystemExit, match=f"HTTP 503 .*after {worlds.TRIES} tries"):
        worlds.get({"action": "parse", "page": "p"}, sleep=lambda s: None)
    assert len(seen) == worlds.TRIES


def test_on_a_runner_the_reason_is_an_annotation():
    # Through the script's own entry point: an unset year is the cheapest failure that
    # reaches it without the network.
    r = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "worlds.py"), "fetch", "1999"],
                       capture_output=True, text=True, env={**os.environ, "GITHUB_ACTIONS": "true"})
    assert r.returncode == 1
    assert "::error title=worlds.py fetch::[1999]: no SEEDS/PAGES yet" in r.stdout


def test_a_block_exits_tempfail_through_the_entry_point():
    # The workflow branches on the EXIT CODE, so that is what must be pinned.
    script = f"""
import io, sys, runpy, email.message, urllib.error, urllib.request
sys.argv = ["worlds.py", "fetch", "2026"]
def fake(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", email.message.Message(),
                                 io.BytesIO(b"<title>Rate Limited - Liquipedia</title>"))
urllib.request.urlopen = fake
runpy.run_path({os.path.join(TOOLS, "worlds.py")!r}, run_name="__main__")
"""
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                       env={**os.environ, "GITHUB_ACTIONS": "true"})
    assert r.returncode == worlds.EX_TEMPFAIL == 75, r.stderr
    assert "HTTP 429" in r.stderr and "::error" not in r.stdout   # the workflow decides red or not


def _payload(complete, years):
    return {"complete": complete, "matches": [{"y": y} for y in years]}


def test_a_scheduled_run_stops_once_the_year_is_complete():
    assert not worlds.due("schedule", 2026, _payload([2025, 2026], [2025, 2026]))
    assert worlds.due("schedule", 2026, _payload([2025], [2025, 2026]))   # still being played
    assert worlds.due("workflow_dispatch", 2026, _payload([2026], [2026]))   # by hand: always


def test_a_year_with_no_matches_yet_is_not_complete():
    # build() puts a year with nothing pending in `complete` even before its first match
    # is in, which must not switch the refresh off before Worlds has begun.
    assert worlds.due("schedule", 2026, _payload([2025, 2026], [2025]))


def test_the_workflow_runs_daily_and_goes_red_on_the_last_day_only():
    wf = open(os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows",
                           "lol-worlds.yml"), encoding="utf-8").read()
    assert 'cron: "31 9 * 10,11 *"' in wf
    assert '"$(date -u +%m%d)" != 1130' in wf
    assert 'worlds.py due "$(date -u +%Y)"' in wf
