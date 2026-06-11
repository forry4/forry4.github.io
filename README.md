# Spender

Spender is a small FastAPI backend that implements a Splendor-like board game using WebSockets. This repository includes the backend server and a minimal browser client you can host with GitHub Pages.

Repository layout
- `Spender/` - Python package containing the FastAPI app and game logic
- `docs/` - static client (`index.html`) suitable for GitHub Pages
- `Procfile` and `render.yaml` - deployment helpers (repo root)
- `.github/workflows/` - CI for running tests on push

Quick start (development)

1. Create and activate a Python virtual environment (PowerShell example):

```powershell
cd 'C:\Users\Forrest\forrestm_projects\Spender'
python -m venv .venv
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process -Force
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

2. Start the server from the repository parent so package imports resolve:

```powershell
cd 'C:\Users\Forrest\forrestm_projects'
python -m uvicorn games.spender.app:app --reload --host 127.0.0.1 --port 8000
```

3. Check health:

```
http://127.0.0.1:8000/health
```

Minimal browser client

Open `docs/index.html` in a browser (or host the `docs/` folder with GitHub Pages). Provide the backend WebSocket base URL (for example `ws://127.0.0.1:8000`) and use the UI to create/join a game. The client logs messages and sends simple game actions over the WebSocket.

Deploying the backend (Render)

1. Push this repository to GitHub.
2. On Render, create a new Web Service and connect your GitHub repo.
3. Set the build command to:

```
pip install -r Spender/requirements.txt
```

4. Set the start command to:

```
python -m uvicorn games.spender.app:app --host 0.0.0.0 --port $PORT
```

After deployment you'll have a public HTTPS URL; use `wss://<your-host>` as the backend WebSocket URL in the client.

CI and tests

Run tests locally with:

```
python -m pytest
```

The repository includes a GitHub Actions workflow that runs tests on push.

Security and production notes

- Restrict CORS to only the frontend domains before making the service public.
- Add short-lived join tokens or simple auth to prevent unauthenticated room joins.
- Use Redis (or another durable store) if you need persistence across restarts or multiple backend instances.
- Consider rate-limiting and request validation for public deployments.

Where to edit the client URL

The `docs/index.html` client has an input labeled "Backend WebSocket base URL" — update that to point at your deployed backend (use `wss://` for production over HTTPS).

Questions or next steps

- I removed the duplicate `Procfile` and `render.yaml` files that were inside `Spender/` and consolidated README material here.
- If you'd like, I can also add a Dockerfile at the repo root, wire the docs client to automatically detect the backend when deployed, or add templated environment configs for Render.
