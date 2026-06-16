"""Deploy entrypoint — re-exports the composition-root app.

The real FastAPI app (middleware + feature wiring + the /coc mount) lives in the
top-level ``app`` module (the composition root). This shim keeps the historical
entrypoint path working unchanged:

    python -m uvicorn games.spender.app:app --host 0.0.0.0 --port 8000

so Procfile / Dockerfile / render.yaml need no edits. (`app` here is the top-level
module, an absolute import — repo root is on sys.path wherever this loads.)
"""
from app import app

# Deploy entrypoint: this file is watched by deploy-render.yml, so a no-op edit
# here is a convenient way to trigger a Render redeploy.
__all__ = ["app"]
