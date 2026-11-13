"""Crash reports from the browser — a page that throws for a player reaches the owner.

`ErrorAlertMiddleware` sees every 5xx the server answers, but nothing saw a page that
threw in someone's browser: the root error boundary drew its screen and the bug went
nowhere. `shared/crashReport.js` now POSTs a short report from the error boundaries and
from `window` `error` / `unhandledrejection`, and this route raises it as an owner alert
of kind `client-error`, through the same `core.alerts.alert` as everything else (the
Site health panel + the ntfy/webhook push).

What the route is careful about, because it is unauthenticated and its body is written
by whoever calls it:
  * EVERY FIELD IS CAPPED, and capped by TRUNCATION rather than refusal — the client
    trims too, but a report that 422s for one long line is a lost report.
  * RATE-LIMITED per IP and site-wide, so a loop on one page or a script hammering the
    route cannot flood the table (it keeps the last 500) or the owner's phone.
  * ONE BUG ON ONE PAGE IS ONE ALERT WITH A COUNT: the dedup key is the build, the
    SCREEN (the first path segment, so every room of a game is one key) and the first
    line of the message. Repeats inside the cooldown are folded and counted by
    `core.alerts`, so the next push says "+N more".
  * NOTHING THAT IDENTIFIES A PLAYER: no IP, no user id, no account name is stored; the
    User-Agent is reduced to a coarse "Safari on iOS". The route keeps only the path
    (never a query string or hash), and anything shaped like a token in the message or
    stack is redacted before it is logged or stored.
"""
from __future__ import annotations

import re
from typing import Annotated

from fastapi import HTTPException, Request
from pydantic import BaseModel, BeforeValidator, ConfigDict

from core import alerts
from core.ratelimit import SlidingWindowLimiter

KIND = "client-error"

BUILD_MAX = 40
ROUTE_MAX = 200
MESSAGE_MAX = 500
STACK_MAX = 2000
SOURCE_MAX = 16
STACK_LINES = 8              # how much of the stack reaches the alert
FIRST_LINE_MAX = 120         # the part of the message that keys the dedup

PER_IP_MAX, PER_IP_WINDOW = 10, 600       # one tab in a crash loop, at most
SITE_MAX, SITE_WINDOW = 200, 3600         # many tabs, or many addresses
_ip_limiter = SlidingWindowLimiter(PER_IP_MAX, PER_IP_WINDOW)
_site_limiter = SlidingWindowLimiter(SITE_MAX, SITE_WINDOW)

SOURCES = {"boundary", "error", "rejection"}

# Known non-bugs, dropped here as well as in the client (an old cached bundle, or a
# caller that is not our reporter, gets the same filter).
_IGNORED = re.compile(r"ResizeObserver loop|Failed to fetch dynamically imported module|"
                      r"Importing a module script failed|error loading dynamically imported module",
                      re.I)


def _capped(n: int):
    return BeforeValidator(lambda v: "" if v is None else str(v)[:n])


class ClientErrorIn(BaseModel):
    model_config = ConfigDict(extra="ignore")
    build: Annotated[str, _capped(BUILD_MAX)] = ""
    route: Annotated[str, _capped(ROUTE_MAX)] = ""
    message: Annotated[str, _capped(MESSAGE_MAX)] = ""
    stack: Annotated[str, _capped(STACK_MAX)] = ""
    source: Annotated[str, _capped(SOURCE_MAX)] = ""


# ── scrubbing ────────────────────────────────────────────────────────────────
# `name=value` / `name: value` only — "Unexpected token '<'" is a common honest message.
_SECRET_NAMED = re.compile(r"(?i)\b(session_token|token|password|secret)"
                           r"([\"']?\s*[:=]\s*[\"']?)[^\s\"'&,;)]+")
_BEARER = re.compile(r"(?i)\b(bearer\s+)[^\s\"'&,;)]+")
_URL_QUERY = re.compile(r"(https?://[^\s?#()]+)[?#][^\s()]*")
_LONG_RUN = re.compile(r"[A-Za-z0-9_\-]{32,}")      # session tokens are token_urlsafe(32)


def scrub(text: str) -> str:
    text = _SECRET_NAMED.sub(lambda m: f"{m.group(1)}{m.group(2)}[redacted]", text)
    text = _BEARER.sub(lambda m: f"{m.group(1)}[redacted]", text)
    text = _URL_QUERY.sub(r"\1", text)
    return _LONG_RUN.sub("[redacted]", text)


def clean_route(route: str) -> str:
    path = re.split(r"[?#]", route or "", maxsplit=1)[0]
    path = re.sub(r"[^A-Za-z0-9/_.\-]", "", path)
    return ("/" + path.lstrip("/"))[:ROUTE_MAX]


def screen_of(route: str) -> str:
    """The first path segment: every room of a game is one screen."""
    seg = [s for s in route.split("/") if s]
    return "/" + seg[0].lower() if seg else "/"


def browser_of(ua: str | None) -> str:
    ua = ua or ""
    if re.search(r"iPhone|iPad|iPod", ua):
        os_ = "iOS"
    elif "Android" in ua:
        os_ = "Android"
    elif "Windows" in ua:
        os_ = "Windows"
    elif "Macintosh" in ua or "Mac OS X" in ua:
        os_ = "Mac"
    elif "Linux" in ua or "CrOS" in ua:
        os_ = "Linux"
    else:
        os_ = "unknown OS"
    if "Edg/" in ua or "EdgiOS" in ua:
        b = "Edge"
    elif "Firefox/" in ua or "FxiOS" in ua:
        b = "Firefox"
    elif "Chrome/" in ua or "CriOS" in ua:
        b = "Chrome"
    elif "Safari/" in ua:
        b = "Safari"
    else:
        b = "a browser"
    return f"{b} on {os_}"


def first_line(message: str) -> str:
    for line in (message or "").splitlines():
        if line.strip():
            return line.strip()[:FIRST_LINE_MAX]
    return "(no message)"


def dedup_key(build: str, route: str, message: str) -> str:
    return f"{KIND}:{build[:12] or '?'}:{screen_of(route)}:{first_line(message)}"


def _client_ip(request: Request) -> str:
    # Same rule as core.rooms.client_ip: Render's proxy APPENDS the real peer.
    xff = request.headers.get("x-forwarded-for") if request is not None else None
    if xff:
        parts = [p.strip() for p in xff.split(",") if p.strip()]
        if parts:
            return parts[-1]
    client = getattr(request, "client", None)
    return getattr(client, "host", None) or "unknown"


def report(payload: ClientErrorIn, request: Request) -> dict:
    ip = _client_ip(request)
    if _ip_limiter.exceeded(ip) or _site_limiter.exceeded("site"):
        raise HTTPException(status_code=429, detail="too many reports")
    _ip_limiter.record(ip)
    _site_limiter.record("site")

    message = scrub(payload.message)
    if not message.strip() or _IGNORED.search(message):
        return {"ok": True, "queued": False}
    build = re.sub(r"[^A-Za-z0-9._\-]", "", payload.build)[:BUILD_MAX] or "?"
    route = clean_route(payload.route)
    source = payload.source if payload.source in SOURCES else "other"
    stack = "\n".join(line.rstrip() for line in scrub(payload.stack).splitlines()
                      if line.strip())
    stack = "\n".join(stack.splitlines()[:STACK_LINES])
    head = first_line(message)
    text = (f"{head} — on {route} (build {build[:7]}, {source}, "
            f"{browser_of(request.headers.get('user-agent') if request is not None else None)})")
    if stack:
        text += "\n" + stack
    queued = alerts.alert(KIND, text, key=dedup_key(build, route, message), severity="warn")
    return {"ok": True, "queued": queued}


def reset() -> None:
    """Forget the rate-limit state (tests)."""
    _ip_limiter.reset()
    _site_limiter.reset()
