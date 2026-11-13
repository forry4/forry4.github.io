"""The browser crash-report route (/ops/client-error, core/client_errors.py).

Called directly with a stand-in request, like the other route tests here: the repo
has no httpx, so no TestClient. Alerts land in the conftest's per-test `alerts._sink`.
"""
import inspect
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException

from core import alerts, client_errors as ce, monitor

CHROME_WIN = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36")
SAFARI_IOS = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_1 like Mac OS X) AppleWebKit/605.1.15 "
              "(KHTML, like Gecko) Version/18.1 Mobile/15E148 Safari/604.1")


def _req(ip="1.2.3.4", ua=CHROME_WIN, xff=None):
    headers = {"user-agent": ua}
    if xff:
        headers["x-forwarded-for"] = xff
    return SimpleNamespace(headers=headers, client=SimpleNamespace(host=ip))


def _send(req=None, **kw):
    body = {"build": "abc1234def", "route": "/coc/ABCDEF", "source": "boundary",
            "message": "TypeError: Cannot read properties of undefined (reading 'x')",
            "stack": "TypeError: boom\n    at Board (https://forry4.github.io/assets/CoC-a1b2.js:1:2)", **kw}
    return ce.report(ce.ClientErrorIn(**body), req or _req())


def test_a_report_raises_one_client_error_alert():
    assert _send() == {"ok": True, "queued": True}
    assert len(alerts._sink) == 1
    a = alerts._sink[0]
    assert a["kind"] == "client-error" and a["severity"] == "warn"
    head, _, stack = a["message"].partition("\n")
    assert head == ("TypeError: Cannot read properties of undefined (reading 'x') — on /coc/ABCDEF "
                    "(build abc1234, boundary, Chrome on Windows)")
    assert "at Board" in stack


def test_one_bug_on_one_screen_is_one_alert_with_a_count():
    _send(route="/coc/AAAAAA")
    _send(route="/coc/BBBBBB")                 # another room of the same game: same key
    _send(route="/coc", message="TypeError: Cannot read properties of undefined (reading 'x')\nmore")
    assert len(alerts._sink) == 1
    _send(route="/duel/AAAAAA")                # another screen
    _send(message="RangeError: other")         # another bug
    _send(build="fff0000")                     # another build
    assert len(alerts._sink) == 4
    assert ce.dedup_key("abc1234def", "/coc/ABCDEF", "TypeError: x\n  at y") == \
        "client-error:abc1234def:/coc:TypeError: x"


def test_every_field_is_capped_by_truncation_not_refusal():
    huge = "x" * 50_000
    body = ce.ClientErrorIn(build=huge, route=huge, message=huge, stack=huge, source=huge)
    assert len(body.build) == ce.BUILD_MAX and len(body.route) == ce.ROUTE_MAX
    assert len(body.message) == ce.MESSAGE_MAX and len(body.stack) == ce.STACK_MAX
    assert len(body.source) == ce.SOURCE_MAX
    # Wrong types and unknown fields are absorbed, never a 422.
    odd = ce.ClientErrorIn(build=7, message=None, token="secret", user_id="u1")
    assert odd.build == "7" and odd.message == "" and not hasattr(odd, "token")
    _send(message="Error: " + "y" * 2000, stack="\n".join(f"at f{i} (x.js:1:1)" for i in range(200)))
    msg = alerts._sink[0]["message"]
    assert len(msg) <= 1000
    assert msg.count("\n") <= ce.STACK_LINES


def test_the_rate_limit_is_per_ip_and_site_wide():
    for i in range(ce.PER_IP_MAX):
        _send(message=f"Error: {i}")
    with pytest.raises(HTTPException) as e:
        _send(message="Error: one too many")
    assert e.value.status_code == 429
    _send(_req(ip="5.6.7.8"), message="Error: another address")   # not this one's budget
    # The LAST X-Forwarded-For hop is the peer (Render appends it); a spoofed left one is ignored.
    with pytest.raises(HTTPException):
        _send(_req(ip="10.0.0.1", xff="9.9.9.9, 1.2.3.4"))
    ce.reset()
    for i in range(ce.SITE_MAX):
        _send(_req(ip=f"10.{i // 250}.{i % 250}.1"), message=f"Error: {i}")
    with pytest.raises(HTTPException) as e:
        _send(_req(ip="172.16.0.1"))
    assert e.value.status_code == 429


def test_no_token_or_query_string_reaches_the_alert():
    tok = "Zq3" * 15
    _send(route=f"/coc/ABCDEF?token={tok}#x",
          message=f"Error: fetch /auth/session?token={tok} failed, session_token={tok}",
          stack=f"at a (https://x.onrender.com/me?token={tok}:1:1)\nAuthorization: Bearer {tok}")
    msg = alerts._sink[0]["message"]
    assert tok not in msg and "onrender.com/me)" in msg   # the URL keeps its path, never its query
    assert "on /coc/ABCDEF (" in msg
    # …while an honest message that merely says "token" is left alone.
    assert ce.scrub("SyntaxError: Unexpected token '<'") == "SyntaxError: Unexpected token '<'"


def test_known_non_bugs_and_empty_reports_raise_nothing():
    for m in ("ResizeObserver loop completed with undelivered notifications.",
              "TypeError: Failed to fetch dynamically imported module: https://x/a.js",
              "TypeError: Importing a module script failed.", "   "):
        assert _send(message=m) == {"ok": True, "queued": False}
    assert alerts._sink == []


def test_source_and_browser_are_coarse_labels():
    _send(_req(ua=SAFARI_IOS), source="<script>")
    assert "(build abc1234, other, Safari on iOS)" in alerts._sink[0]["message"]
    assert ce.browser_of(None) == "a browser on unknown OS"


def test_the_route_is_registered_unauthenticated_and_off_the_event_loop():
    app = FastAPI()
    monitor.setup_site_health(app, {}.get)
    route = next(r for r in app.routes if getattr(r, "path", "") == "/ops/client-error")
    assert route.methods == {"POST"}
    assert not inspect.iscoroutinefunction(route.endpoint)
    assert not route.dependant.dependencies          # no owner/session gate
