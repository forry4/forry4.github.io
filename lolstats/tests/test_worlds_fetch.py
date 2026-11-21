"""worlds.py's fetch against a Liquipedia that refuses: a transient refusal (429/5xx, an
API `ratelimited`) is waited out, anything else fails at once and SAYS what came back,
and on a runner that reason becomes a public annotation. 2026-11-16's weekly run died on
its first request with nothing but "exit code 1" in the annotations."""
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


def test_a_429_is_waited_out_for_as_long_as_retry_after_says(monkeypatch):
    seen = _serve(monkeypatch, [_http(429, retry_after=90), OK])
    waits = []
    assert worlds.get({"action": "parse", "page": "p"}, sleep=waits.append) == OK
    assert waits == [90] and len(seen) == 2


def test_a_wait_never_breaks_the_one_request_per_30s_rule(monkeypatch):
    _serve(monkeypatch, [_http(503, retry_after=1), OK])
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
    seen = _serve(monkeypatch, [_http(429)] * worlds.TRIES)
    with pytest.raises(SystemExit, match=f"HTTP 429 .*after {worlds.TRIES} tries"):
        worlds.get({"action": "parse", "page": "p"}, sleep=lambda s: None)
    assert len(seen) == worlds.TRIES


def test_on_a_runner_the_reason_is_an_annotation():
    # Through the script's own entry point: an unset year is the cheapest failure that
    # reaches it without the network.
    r = subprocess.run([sys.executable, "-I", os.path.join(TOOLS, "worlds.py"), "fetch", "1999"],
                       capture_output=True, text=True, env={**os.environ, "GITHUB_ACTIONS": "true"})
    assert r.returncode == 1
    assert "::error title=worlds.py fetch::[1999]: no SEEDS/PAGES yet" in r.stdout
