"""Convenience re-export for the FastAPI app.

This allows running the server with a short import path:

    python -m uvicorn games.spender.app:app --host 0.0.0.0 --port 8000

"""
from .main import app

# Deploy entrypoint: this file is watched by deploy-render.yml, so a no-op edit
# here is a convenient way to trigger a Render redeploy.
__all__ = ["app"]
