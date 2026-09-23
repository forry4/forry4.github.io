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
    return {"commit": commit(), "started_at": STARTED_AT, "db_backend": db.backend()}
