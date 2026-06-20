# Forrest Games

A small collection of board games and site features, built as one full-stack app
and hosted at **https://forry4.github.io/**. A single FastAPI backend serves every
game and feature; a single React frontend — a shell that mounts each feature —
is the site.

## What's inside

### Games
- **Spender** — a Splendor-like game of gem trading and prestige. Two players,
  human-vs-human or human-vs-AI, racing to 15 points (Classic) or 21 (Long). The
  AI is the deep part of the project: hand-built heuristics, a determinized-search
  variant (a whole-position evaluator + PUCT), and an offline AlphaZero stack.
  *Live.*
- **Castles of Crimson** — a faithful digital port of the duchy-building
  dice-and-tile euro game. Two players, human-vs-human or vs a determinized-MCTS
  bot (Normal / Hard). *Live.*
- **Where Wolf?** — a One Night Werewolf-style social-deduction party game for
  3–10 humans, with a server-driven timed "night conductor" and per-player hidden
  information. *In development* (backend landed; not yet wired into the home menu).

### Site features
- **Books** — a public ranking of favourite books, plus reading suggestions that
  any signed-in user can submit.
- **WWSD** ("What Would Steve Do") — a standalone move-advisor for a friend's
  external Splendor site, deployed as its own service (see [`wwsd/`](wwsd/)).

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, asyncio, WebSockets; SQLite for dev, Turso/libSQL for persistent prod |
| Frontend | React 18, Vite 6, single-file components, one shared shell |
| AI | MCTS, determinized PUCT, hand-built heuristics, AlphaZero (PyTorch offline → NumPy inference in prod) |
| Auth | session tokens + per-room reconnect tokens, PBKDF2 passwords, in-process rate limiting |
| Hosting | GitHub Pages (frontend), Render (backend), Cloudflare Worker (staging) |

## Repository layout

```
app.py            # composition root: FastAPI app, CORS + security headers, wires every feature
core/             # shared backend platform — DB (sqlite/Turso), auth, rate limiting, config
games/
  spender/        # Spender server + game logic + the AI stack (ai/, ai/az/)
  castles_of_crimson/
  wherewolf/
books/            # Books site feature
shared/           # shared frontend theme
webapp/           # Vite + React build; the shell that mounts every feature
wwsd/             # standalone Splendor move-advisor (separate service)
docs/             # GitHub Pages output — BUILT BY CI, do not hand-edit
Procfile, render.yaml, requirements-lock.txt   # deploy config
```

The backend is layered so features never depend on each other: `core/` (bottom) →
features (`games.*`, `books`) → `app.py` (the composition root that wires them).

## Local development

Backend — serves the whole site (every game and feature) from the composition root:

```bash
pip install -r games/spender/requirements.txt
python -m uvicorn app:app --reload --port 8000
# health check: http://127.0.0.1:8000/health
```

Frontend — Vite dev server, proxies WebSockets to the backend on :8000:

```bash
cd webapp
npm install
npm run dev
```

Tests:

```bash
python -m pytest            # backend: game engines, AI, core/auth, ...
cd webapp && npm run smoke  # frontend: builds + headless-loads, fails on a blank page
```

## Deployment

- **Frontend** → GitHub Pages at https://forry4.github.io/. CI
  (`.github/workflows/deploy-pages.yml`) builds `webapp/`, runs the smoke test, and
  commits the result to `docs/` on every push to `main` that touches the frontend.
  Never hand-build or commit `docs/`.
- **Backend** → Render (one web service hosts every game and feature); auto-deploys
  on push to `main`. WWSD runs as a second Render service.
- **Staging** → a Cloudflare Worker mirrors the frontend from the `staging` branch
  (reusing the prod backend) so UI changes can be tested on a real URL before they
  ship.

## More

[`CLAUDE.md`](CLAUDE.md) is the detailed engineering log — architecture decisions,
the AI research, and the hard-won "do not regress" notes for each subsystem.
