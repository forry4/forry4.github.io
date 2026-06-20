"""Site-wide configuration helpers (env-driven, no web-framework deps).

Lives in core so both the composition root (app.py) and the mounted sub-apps
(e.g. Castles of Crimson) can share one definition without importing each other.
"""
import os

# Origins allowed to call the API from a browser. The production frontend is
# GitHub Pages at https://forry4.github.io/WebProjects/ (origin = scheme+host, no
# path); the Cloudflare staging mirror (webprojectsstaging.forry4.workers.dev)
# reuses this same backend, so it must be allowed too; plus the local Vite dev
# server and backend for development. CORS_ALLOWED_ORIGINS (comma-separated) ADDS
# extra origins (e.g. a future custom domain) without a code change.
DEFAULT_ALLOWED_ORIGINS = [
    "https://forry4.github.io",                          # GitHub Pages (production)
    "https://webprojectsstaging.forry4.workers.dev",     # Cloudflare staging mirror
    "http://localhost:5173",      # Vite dev server
    "http://127.0.0.1:5173",
    "http://localhost:8000",      # local backend (direct calls / docs)
]


def cors_allowed_origins() -> list[str]:
    """The CORS allowlist. The site's own frontends (GitHub Pages prod + the
    Cloudflare staging mirror) and local dev are ALWAYS allowed; any origins in
    CORS_ALLOWED_ORIGINS (comma-separated) are ADDED on top. Merging rather than
    replacing means setting the env var can never accidentally lock out the prod or
    staging frontend (the old replace-semantics footgun)."""
    origins = list(DEFAULT_ALLOWED_ORIGINS)
    raw = os.environ.get("CORS_ALLOWED_ORIGINS")
    if raw:
        for o in (s.strip() for s in raw.split(",")):
            if o and o not in origins:
                origins.append(o)
    return origins
