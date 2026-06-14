# Castles of Crimson

A new game in the **Forrest Games** collection. **Status: in development — not yet playable.**

This folder is a placeholder scaffold. The site's home menu (the "Forrest Games"
landing page, rendered by `games/spender/Spender.jsx`) lists Castles of Crimson
as a selectable tile that currently shows a "Coming Soon" screen.

## Folder name

The display name is *Castles of Crimson*; the directory is `castles_of_crimson`
(lowercase, underscores) to match `games/spender/` and to remain importable as a
Python package (`games.castles_of_crimson.*`) if a backend is added later.

## Planned layout (mirrors `games/spender/`)

```
games/castles_of_crimson/
  main.py            # FastAPI + WebSocket backend (to be added)
  CastlesOfCrimson.jsx   # React frontend (to be added)
  webapp/            # Vite wrapper (to be added)
  ai/                # AI / training tooling (to be added)
  tests/
```

For now there is no code here — just this README so git tracks the folder.
