"""Composition root — the real FastAPI app for the whole site.

This is the TOP layer: it creates the FastAPI app, applies middleware, and wires
together the feature packages. It depends on the features; the features do not
depend on it. Nothing here is owned by a single game — that was the point of
extracting it out of ``games/spender/main.py`` (which now only exposes a router).

Layering (bottom → top):
    core/ (db + auth)  →  features (games.spender, games.castles_of_crimson, books)  →  app.py

The deploy entrypoint ``games/spender/app.py`` re-exports the ``app`` defined here,
so Procfile/Dockerfile/render.yaml keep their historical ``games.spender.app:app``
target unchanged.
"""
import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from core.db import get_db_conn
from core.auth import get_user_by_session
from core.config import cors_allowed_origins
from games.spender.main import router as spender_router, bearer_token
from books.api import setup_books

LOG = logging.getLogger("app")


class SecurityHeadersMiddleware:
    """Pure-ASGI middleware that adds hardening headers to every HTTP response.
    Implemented at the ASGI layer (not BaseHTTPMiddleware) so it threads `send`
    down into the mounted /coc sub-app — its responses get the headers too — and
    cleanly ignores WebSocket scopes. Only sets a header if not already present."""

    # Security-relevant response headers. No Content-Security-Policy here: the API
    # serves JSON (CSP guards HTML documents — that belongs on the GitHub Pages
    # frontend) and a strict policy would break FastAPI's /docs (Swagger UI).
    _HEADERS = {
        "x-content-type-options": "nosniff",
        "x-frame-options": "DENY",
        "referrer-policy": "strict-origin-when-cross-origin",
        "strict-transport-security": "max-age=63072000; includeSubDomains",
        "permissions-policy": "geolocation=(), microphone=(), camera=()",
    }

    def __init__(self, app):
        self.app = app
        self._encoded = [(k.encode(), v.encode()) for k, v in self._HEADERS.items()]

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        async def send_wrapper(message):
            if message["type"] == "http.response.start":
                headers = message.setdefault("headers", [])
                present = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in self._encoded if k not in present)
            await send(message)

        await self.app(scope, receive, send_wrapper)


app = FastAPI(title="Forrest Games API")

# CORS: pinned to the known frontend origins (not "*"). Auth is token-based (no
# cookies), so credentials stay off. Only the headers/methods the frontend uses
# are allowed. Covers /coc too — the parent CORS layer wraps the mounted sub-app.
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_allowed_origins(),
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-Room-Token"],
)
app.add_middleware(SecurityHeadersMiddleware)

# Spender's HTTP + WebSocket routes (auth, games, /ws, /health) at the site root.
app.include_router(spender_router)

# Books — public read + owner write. Deps are injected (from core) so books never
# imports a game module (no cycle). bearer_token lets Books accept the same
# Authorization: Bearer header (with ?token= fallback) as the Spender routes.
setup_books(app, get_db_conn, get_user_by_session, bearer_token)

# Puzzle mode — static, scripted Spender endgame puzzles. Public read-only content
# (the bank is committed JSON with embedded snapshots); no DB/auth/engine at serve
# time. Defensive: an import error must not take down the rest of the backend.
# (Bank: 6 generated + 3 affordability-chain Ladders + Red Ladder + N-verified Gold Reserve.)
try:
    from games.spender.puzzle.serve import setup_puzzles
    setup_puzzles(app)
    LOG.info("wired Puzzle mode routes (/puzzles)")
except Exception as _puz_err:  # pragma: no cover - optional package
    LOG.warning("Puzzle mode not wired: %s", _puz_err)

# Castles of Crimson — its self-contained sub-app mounted under /coc. Defensive:
# a CoC import error must NOT take down the core backend (an earlier unconditional
# import once crashed prod when the package was absent — reverted in fc6a2fa).
try:
    from games.castles_of_crimson.main import coc_app
    app.mount("/coc", coc_app)
    LOG.info("mounted Castles of Crimson at /coc")
except Exception as _coc_err:  # pragma: no cover - optional package
    LOG.warning("Castles of Crimson not mounted: %s", _coc_err)

# Where Wolf? — its self-contained sub-app mounted under /werewolf. Same defensive
# guard: an import error here must not take down the rest of the backend.
try:
    from games.wherewolf.main import werewolf_app
    app.mount("/werewolf", werewolf_app)
    LOG.info("mounted Where Wolf? at /werewolf")
except Exception as _ww_err:  # pragma: no cover - optional package
    LOG.warning("Where Wolf? not mounted: %s", _ww_err)

# Spender Duel — its self-contained sub-app mounted under /duel. Same defensive
# guard: an import error here must not take down the rest of the backend.
try:
    from games.spender_duel.main import duel_app
    app.mount("/duel", duel_app)
    LOG.info("mounted Spender Duel at /duel")
except Exception as _duel_err:  # pragma: no cover - optional package
    LOG.warning("Spender Duel not mounted: %s", _duel_err)

# Dontminion — its self-contained sub-app mounted under /dontminion. Same
# defensive guard: an import error here must not take down the rest of the backend.
try:
    from games.dontminion.main import dontminion_app
    app.mount("/dontminion", dontminion_app)
    LOG.info("mounted Dontminion at /dontminion")
except Exception as _dm_err:  # pragma: no cover - optional package
    LOG.warning("Dontminion not mounted: %s", _dm_err)

# Dissonance — its self-contained sub-app mounted under /dissonance. Same defensive
# guard: an import error here must not take down the rest of the backend.
try:
    from games.dissonance.main import dissonance_app
    app.mount("/dissonance", dissonance_app)
    LOG.info("mounted Dissonance at /dissonance")
except Exception as _ot_err:  # pragma: no cover - optional package
    LOG.warning("Dissonance not mounted: %s", _ot_err)

# Rag Tag — its self-contained sub-app mounted under /ragtag. Same defensive
# guard: an import error here must not take down the rest of the backend.
try:
    from games.rag_tag.main import ragtag_app
    app.mount("/ragtag", ragtag_app)
    LOG.info("mounted Rag Tag at /ragtag")
except Exception as _rt_err:  # pragma: no cover - optional package
    LOG.warning("Rag Tag not mounted: %s", _rt_err)

# Orbit — faithful 1v1 Zenith with a random server opponent for the first
# release. Keep the defensive mount: one optional game must never take down the
# shared backend.
try:
    from games.orbit.main import orbit_app
    app.mount("/orbit", orbit_app)
    LOG.info("mounted Orbit at /orbit")
except Exception as _orbit_err:  # pragma: no cover - optional package
    LOG.warning("Orbit not mounted: %s", _orbit_err)

# Black Castle — base-game Himeji worker placement, mounted separately so its
# room protocol and persistence remain isolated from the shared site shell.
try:
    from games.black_castle.main import blackcastle_app
    app.mount("/blackcastle", blackcastle_app)
    LOG.info("mounted Black Castle at /blackcastle")
except Exception as _blackcastle_err:  # pragma: no cover - optional package
    LOG.warning("Black Castle not mounted: %s", _blackcastle_err)

# Pinch — two-player ring-and-marker abstract strategy, mounted separately so
# its room protocol and persistence remain isolated from every other game.
try:
    from games.pinch.main import pinch_app
    app.mount("/pinch", pinch_app)
    LOG.info("mounted Pinch at /pinch")
except Exception as _pinch_err:  # pragma: no cover - optional package
    LOG.warning("Pinch not mounted: %s", _pinch_err)

# SecretNames — the two-player cooperative word game (Codenames: Duet). Same
# defensive mount: one optional game must never take down the shared backend.
try:
    from games.secretnames.main import secretnames_app
    app.mount("/secretnames", secretnames_app)
    LOG.info("mounted SecretNames at /secretnames")
except Exception as _secretnames_err:  # pragma: no cover - optional package
    LOG.warning("SecretNames not mounted: %s", _secretnames_err)
