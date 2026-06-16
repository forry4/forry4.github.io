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
from games.spender.main import router as spender_router
from books.api import setup_books

LOG = logging.getLogger("app")

app = FastAPI(title="Forrest Games API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Spender's HTTP + WebSocket routes (auth, games, /ws, /health) at the site root.
app.include_router(spender_router)

# Books — public read + owner write. Deps are injected (from core) so books never
# imports a game module (no cycle).
setup_books(app, get_db_conn, get_user_by_session)

# Castles of Crimson — its self-contained sub-app mounted under /coc. Defensive:
# a CoC import error must NOT take down the core backend (an earlier unconditional
# import once crashed prod when the package was absent — reverted in fc6a2fa).
try:
    from games.castles_of_crimson.main import coc_app
    app.mount("/coc", coc_app)
    LOG.info("mounted Castles of Crimson at /coc")
except Exception as _coc_err:  # pragma: no cover - optional package
    LOG.warning("Castles of Crimson not mounted: %s", _coc_err)
