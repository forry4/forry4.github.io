"""What code is actually running — so a deploy can be VERIFIED, not assumed.

The Render deploy job used to go green when the webhook returned 200, i.e. when
Render *accepted* the request. It said nothing about whether the image built, or
whether the new process came up. A failed Docker build (the Cython parity gate in
the Dockerfile is designed to fail one) or a boot crash left prod silently on the
old code behind a green tick, and nothing served could answer "is my commit live?".

`/health` now reports both of these, and CI polls until it sees the commit it just
pushed:

  commit     - best effort. Render sets RENDER_GIT_COMMIT on repo-backed services;
               a plain `docker build` can bake GIT_COMMIT instead. "unknown" if
               neither is present.
  started_at - unix seconds, captured at import. Always available, so it is the
               FALLBACK gate: a value newer than the moment the deploy was fired
               proves a fresh process booted.

Why both: `commit` is exact but depends on the platform setting an env var, and
`started_at` alone can false-positive — Render's free tier spins down when idle, so
a cold start during the deploy window boots a NEW process still running the OLD
image. Prefer `commit`; fall back to `started_at` and say so loudly.
"""
from __future__ import annotations

import os
import time

# Captured once, at import — i.e. when this process booted.
STARTED_AT = int(time.time())

# ── boot timing ─────────────────────────────────────────────────────────────
# How long a COLD START spends inside our own process, so it can be measured on
# prod's fractional CPU rather than guessed from a laptop. Three marks, each a
# wall-clock time, first write wins:
#   app_import_started  top of app.py (the composition root), before its imports
#   app_imported        bottom of app.py: every feature imported and wired
#   serving             the first ASGI call (uvicorn's lifespan startup), which
#                       uvicorn makes just before it binds the port
# plus the process's own start time, read from /proc where it exists. The split:
#   interpreter_s  process start -> app_import_started (CPython + uvicorn + site)
#   import_s       app_import_started -> app_imported   (OUR modules — the lever)
#   startup_s      app_imported -> serving              (lifespan, monitor arming)
#   total_s        process start -> serving
# Render's wake ALSO spends time we cannot see from inside (scheduling the
# instance, pulling the image); that is the gap between an external request's
# latency and total_s.
_BOOT: dict[str, float] = {}


def mark(name: str, at: float | None = None) -> None:
    """Record a boot milestone once. Later calls are no-ops, so a hot path may
    call it unconditionally."""
    if name not in _BOOT:
        _BOOT[name] = time.time() if at is None else at


def process_start_time() -> float | None:
    """Wall-clock start of THIS process, from /proc (Linux, i.e. prod). None
    elsewhere: a Windows dev box reports the in-process split without it."""
    try:
        with open("/proc/self/stat", encoding="ascii") as f:
            # comm (field 2) may contain spaces; everything after its ')' is fixed.
            fields = f.read().rsplit(")", 1)[1].split()
        start_ticks = int(fields[19])  # field 22 overall: starttime, in clock ticks
        with open("/proc/stat", encoding="ascii") as f:
            btime = next(int(line.split()[1]) for line in f if line.startswith("btime "))
        return btime + start_ticks / os.sysconf("SC_CLK_TCK")
    except (OSError, ValueError, IndexError, StopIteration, AttributeError):
        return None


_PROCESS_START = process_start_time()


def boot_timing() -> dict:
    """The boot split, in seconds rounded to ms. A phase whose marks are missing
    is simply absent (e.g. no `serving` when the app is called without uvicorn)."""
    b, start = _BOOT, _PROCESS_START

    def span(a, z):
        return round(z - a, 3) if a is not None and z is not None else None

    out = {
        "interpreter_s": span(start, b.get("app_import_started")),
        "import_s": span(b.get("app_import_started"), b.get("app_imported")),
        "startup_s": span(b.get("app_imported"), b.get("serving")),
        "total_s": span(start, b.get("serving")),
    }
    if start is not None:
        out["process_start"] = round(start, 3)
    return {k: v for k, v in out.items() if v is not None}

# In priority order. RENDER_GIT_COMMIT is Render's own; GIT_COMMIT/SOURCE_COMMIT
# cover a hand-run `docker build --build-arg`.
_COMMIT_VARS = ("RENDER_GIT_COMMIT", "GIT_COMMIT", "SOURCE_COMMIT")


def commit() -> str:
    """Full commit SHA of the running code, or "unknown"."""
    for var in _COMMIT_VARS:
        val = (os.environ.get(var) or "").strip()
        if val:
            return val
    return "unknown"


def build_info() -> dict:
    """The block every service's /health merges in.

    `db_backend` is here for the same reason `commit` is: it is a fact about the
    running process that a deploy must be able to VERIFY. See core.db.backend."""
    from core import db  # lazy: keep this module importable without the DB layer
    return {"commit": commit(), "started_at": STARTED_AT, "db_backend": db.backend(),
            "boot": boot_timing()}
