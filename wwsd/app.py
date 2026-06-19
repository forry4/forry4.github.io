"""WWSD service — a small FastAPI app that runs Splendor variant S on a posted game position.

Runs as a SEPARATE Render service (process-isolated from the live game backend): importing this
module installs the friend's deck into the shared engine globals via `analyze.prepare()`, which
would corrupt the main game's AI if they shared a process. The live backend never imports this.
See render.yaml (`wwsd-backend`) and the plan in .claude-plans/.

Env: WWSD_SECRET (required), WWSD_ORIGIN (default spendee), WWSD_TIME (search budget seconds),
WWSD_RATE_MAX / WWSD_RATE_WINDOW (per-IP rate limit).
"""
from __future__ import annotations
import hmac
import json
import os
import time
from collections import defaultdict, deque

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse

from wwsd import analyze as W
from wwsd.bookmarklet import page_html

SECRET = os.environ.get("WWSD_SECRET", "")
ORIGIN = os.environ.get("WWSD_ORIGIN", "https://spendee.mattle.online")
TIME_BUDGET = float(os.environ.get("WWSD_TIME", "3.5"))      # default budget; a per-request ?t= overrides it
TIME_MIN = float(os.environ.get("WWSD_TIME_MIN", "1"))       # ?t= clamp floor
TIME_MAX = float(os.environ.get("WWSD_TIME_MAX", "60"))      # ?t= ceiling (stay under Cloudflare's ~100s timeout)
RATE_MAX = int(os.environ.get("WWSD_RATE_MAX", "20"))         # requests per window per IP
RATE_WINDOW = float(os.environ.get("WWSD_RATE_WINDOW", "60"))

if not SECRET:
    raise RuntimeError("WWSD_SECRET env var is required (the bookmarklet's shared secret)")
W.prepare()                                                  # install the friend's deck once, in THIS process

app = FastAPI(title="WWSD")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[ORIGIN],
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "X-WWSD-Secret"],
)

_hits: dict[str, deque] = defaultdict(deque)


def _rate_ok(ip: str) -> bool:
    now = time.time()
    q = _hits[ip]
    while q and now - q[0] > RATE_WINDOW:
        q.popleft()
    if len(q) >= RATE_MAX:
        return False
    q.append(now)
    return True


def _client_ip(req: Request) -> str:
    xff = req.headers.get("x-forwarded-for")
    return xff.split(",")[0].strip() if xff else (req.client.host if req.client else "?")


def _budget(t_param) -> float:
    """Resolve the per-request think-time from the ?t= query param, clamped to [MIN, MAX]."""
    if t_param is None:
        return TIME_BUDGET
    try:
        return max(TIME_MIN, min(TIME_MAX, float(t_param)))
    except (TypeError, ValueError):
        return TIME_BUDGET


def process_move(raw_body: bytes, secret_header: str, ip: str, t_param=None):
    """Pure handler (no HTTP types) -> (status_code, body_dict). Unit-testable without a server."""
    if not hmac.compare_digest(secret_header or "", SECRET):
        return 401, {"ok": False, "message": "bad or missing secret"}
    if not _rate_ok(ip):
        return 429, {"ok": False, "message": "rate limited — slow down"}
    try:
        doc = json.loads(raw_body)
    except Exception as e:
        return 400, {"ok": False, "message": f"bad json: {e}"}
    try:
        budget = _budget(t_param)
        result = W.analyze(doc, time_limit=budget)
        if isinstance(result, dict):
            result.setdefault("budget", round(budget, 1))
        return 200, result
    except Exception as e:
        return 500, {"ok": False, "message": f"analyze error: {e}"}


@app.get("/health")
def health():
    return {"ok": True}


@app.get("/", response_class=HTMLResponse)
def index():
    return page_html()


@app.post("/move")
async def move(req: Request):
    code, body = process_move(await req.body(), req.headers.get("X-WWSD-Secret", ""),
                              _client_ip(req), req.query_params.get("t"))
    return JSONResponse(body, status_code=code)
