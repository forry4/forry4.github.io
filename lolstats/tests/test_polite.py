"""polite.py, the one way LoL Stats' harvesters ask a site for anything: spaced requests,
backoff inside a budget, a bare 429 treated as a block (never retried), and every refusal
named. The clock and the sleeps are injected, so nothing here waits or touches a network."""
import email.message
import importlib.util
import io
import json
import os
import urllib.error

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
spec = importlib.util.spec_from_file_location("polite", os.path.join(TOOLS, "polite.py"))
polite = importlib.util.module_from_spec(spec)
spec.loader.exec_module(polite)

URL = "https://example.test/api.php"
OK = {"cargoquery": []}


class R(io.BytesIO):
    headers = email.message.Message()

    def __enter__(self):
        return self

    def __exit__(self, *a):
        pass


def http(code, retry_after=None, body=b"nope"):
    h = email.message.Message()
    if retry_after is not None:
        h["Retry-After"] = str(retry_after)
    return urllib.error.HTTPError(URL, code, "refused", h, io.BytesIO(body))


class Clock:
    """A fake clock that sleeping advances, so spacing is measurable."""

    def __init__(self):
        self.t, self.slept = 0.0, []

    def sleep(self, s):
        self.slept.append(round(s, 3))
        self.t += s

    def now(self):
        return self.t


def client(clock, **kw):
    kw = {"min_interval": 10, "budget": 600, "base": 60, **kw}
    return polite.Client("Site", sleep=clock.sleep, clock=clock.now, rand=lambda: 0.0, **kw)


@pytest.fixture
def serve(monkeypatch):
    def install(answers):
        seen = []

        def fake(req, timeout=None):
            seen.append(req)
            a = answers.pop(0)
            if isinstance(a, Exception):
                raise a
            return R(json.dumps(a).encode())

        monkeypatch.setattr(polite.urllib.request, "urlopen", fake)
        return seen
    return install


def test_requests_name_the_project_and_ask_for_gzip(serve):
    seen = serve([OK])
    client(Clock()).json(URL, {"action": "cargoquery"}, mediawiki=True)
    h = {k.lower(): v for k, v in seen[0].header_items()}
    assert "forry4.github.io" in h["user-agent"] and h["accept-encoding"] == "gzip"
    assert "maxlag=5" in seen[0].full_url and "format=json" in seen[0].full_url


def test_requests_are_spaced_however_fast_the_caller_loops(serve):
    serve([OK, OK, OK])
    clock = Clock()
    c = client(clock)
    for _ in range(3):
        c.json(URL)
    assert clock.slept == [10, 10]


def test_a_bare_429_is_a_block_and_is_never_retried(serve):
    # Liquipedia's "Rate Limited" page (2026-11-21): retrying a blocked IP renews the block.
    seen = serve([http(429, body=b"<title>Rate Limited</title>"), OK])
    clock = Clock()
    with pytest.raises(polite.TryLater, match="429 with no Retry-After"):
        client(clock).json(URL)
    assert len(seen) == 1 and clock.slept == []


def test_a_429_that_says_how_long_is_waited_out(serve):
    serve([http(429, retry_after=90), OK])
    clock = Clock()
    assert client(clock).json(URL) == OK
    assert clock.slept == [90]


def test_a_5xx_backs_off_exponentially(serve):
    serve([http(503), http(502), OK])
    clock = Clock()
    client(clock).json(URL)
    assert clock.slept == [60, 120]


def test_the_api_ratelimit_arrives_as_a_200_and_is_backed_off_too(serve):
    serve([{"error": {"code": "ratelimited", "info": "slow down"}}, OK])
    clock = Clock()
    assert client(clock).json(URL, mediawiki=True) == OK
    assert clock.slept == [60]


def test_a_rate_limit_that_outlasts_the_budget_stops_for_the_day(serve):
    limited = {"error": {"code": "ratelimited", "info": "slow down"}}
    seen = serve([limited] * 10)
    clock = Clock()
    with pytest.raises(polite.TryLater, match="stopping for today"):
        client(clock, budget=200).json(URL, mediawiki=True)
    assert clock.slept == [60, 120] and len(seen) == 3   # 60 + 120 fit; 240 more would not


def test_jitter_keeps_two_runs_out_of_step(serve):
    serve([http(503), OK])
    clock = Clock()
    polite.Client("Site", min_interval=10, budget=600, base=60, sleep=clock.sleep, clock=clock.now,
                  rand=lambda: 1.0).json(URL)
    assert clock.slept == [75]   # 60 * (1 + 0.25)


def test_a_refusal_that_waiting_will_not_fix_fails_at_once_and_names_itself(serve):
    seen = serve([http(403, body=b"Forbidden"), OK])
    with pytest.raises(polite.Refused, match="HTTP 403 .*Forbidden"):
        client(Clock()).json(URL)
    assert len(seen) == 1


def test_an_unknown_api_error_is_a_refusal_not_a_retry(serve):
    serve([{"error": {"code": "badquery", "info": "no such field"}}])
    with pytest.raises(polite.Refused, match="badquery"):
        client(Clock()).json(URL, mediawiki=True)
