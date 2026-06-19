"""Site-wide configuration helpers (env-driven, no web-framework deps).

Lives in core so both the composition root (app.py) and the mounted sub-apps
(e.g. Castles of Crimson) can share one definition without importing each other.
"""
import os

# Origins allowed to call the API from a browser. The production frontend is
# GitHub Pages at https://forry4.github.io/WebProjects/ (origin = scheme+host, no
# path), plus the local Vite dev server and backend for development. Override in
# any environment with CORS_ALLOWED_ORIGINS (comma-separated) — e.g. to add a
# custom domain later — without a code change.
DEFAULT_ALLOWED_ORIGINS = [
    "https://forry4.github.io",   # GitHub Pages (production)
    "http://localhost:5173",      # Vite dev server
    "http://127.0.0.1:5173",
    "http://localhost:8000",      # local backend (direct calls / docs)
]


def cors_allowed_origins() -> list[str]:
    """The CORS allowlist: CORS_ALLOWED_ORIGINS (comma-separated) if set, else the
    built-in defaults."""
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    if raw:
        return [o.strip() for o in raw.split(",") if o.strip()]
    return list(DEFAULT_ALLOWED_ORIGINS)
