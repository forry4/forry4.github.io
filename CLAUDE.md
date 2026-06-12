# Spender Project — Claude Context

## Critical rule
**NEVER add `Co-Authored-By: Claude` (or any Anthropic attribution) to commit messages.** The user has explicitly prohibited this.

---

## Project layout

```
games/spender/
  main.py          # FastAPI + WebSocket backend (Python)
  Spender.jsx      # React 18 frontend (single file)
  users.db         # SQLite — users + games tables
  webapp/          # Vite wrapper that imports Spender.jsx
    main.jsx
    index.html
    vite.config.js
  tests/
    test_game_logic.py
docs/              # GitHub Pages static site (Vite production build output)
  index.html
  assets/          # Hashed JS bundles (e.g. index-XXXXXXXX.js)
```

### Serving
- Backend: `uvicorn games.spender.main:app --reload` (port 8000)
- Dev frontend: `cd games/spender/webapp && npm run dev` (port 5173, proxies /ws to 8000)
- Production: GitHub Pages serves `docs/`. Build with `npm run build` in `webapp/`, copy output to `docs/`, update `docs/index.html` script src to new hashed bundle name.

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI, asyncio, SQLite (via `sqlite3`), `asyncio.create_task` + `loop.run_in_executor` for async AI |
| Frontend | React 18, plain JS (no TypeScript), Vite, single-file component (`Spender.jsx`) |
| AI | MCTS with `_MCTSNode` class (`__slots__`), 5-second time limit, runs in thread pool |
| Auth | JWT-less: session tokens stored in `users` table, reconnect tokens per-player per-room |

---

## Backend architecture (main.py)

### In-memory state
`ROOMS: dict[str, dict]` — keyed by room_id. Each room:
```python
{
  "players": {pid: name},
  "sockets": {pid: WebSocket},
  "status": "open" | "playing" | "over",
  "host": pid,
  "game": { ... },   # None until started
  "meta": {pid: {"token": str, ...}},
}
```

### DB persistence
- `save_game(room_id)` — upserts room to `games` table (called after every state change, outside lock)
- `load_game_to_memory(room_id)` — called on WS connect if room not in ROOMS; loads from DB

### Lock
`ROOM_LOCK = asyncio.Lock()` — all ROOMS mutations happen under this lock.

### Async AI turn flow
1. Human's move is processed under lock, `_post_turn` called (just syncs status now).
2. After `broadcast_room`, `asyncio.create_task(_schedule_ai_turn(room_id))` is fired.
3. `_schedule_ai_turn`:
   - Acquires lock → snapshots game → releases lock
   - Runs `_mcts_choose_move` in thread pool (`loop.run_in_executor(None, ...)`) — 5 seconds
   - Acquires lock again → verifies turn/phase haven't changed → applies AI move → releases lock
   - Calls `save_game` and `broadcast_room` outside lock
4. This means the UI updates immediately after the human moves, then again after the AI thinks.

### `_schedule_ai_turn` is safe to call any time
It guards internally: returns immediately if not AI's turn, game not found, or phase not "playing".
Called from: move handler, create action (vs_ai), both reconnect handlers.

### AI pipeline
- `_mcts_choose_move(game, ai_pid, time_limit=5.0)` — tree MCTS with `_MCTSNode`
- `_MCTSNode` uses `__slots__`, UCB1 child selection (negates exploit for opponent nodes), iterative backprop
- `_fast_rollout_move` — rollout policy: buy > reserve high-value > take gems
- `_ai_score_card` — heuristic with deficit-weighted accessibility multiplier
- `_sim_rollout` — max 25 turns, rich position evaluator (`pts + buyable*0.5 + noble_proximity*0.3`)

### Move handler error hierarchy
```python
if not r:                          → "game not started"
elif r.get("status") == "over":    → "game is over"
elif r.get("status") != "playing": → "game not started"
else:
    if g.get("phase") == "over":   → "game is over"
    elif g.get("turn") != pid:     → "not your turn"
```

---

## Frontend architecture (Spender.jsx)

### Screen flow
`"auth"` → `"browser"` → `"waiting"` (2-player) | `"game"` (vs-AI goes directly)

### Key derived state (hoisted ABOVE all useEffect hooks — required to avoid TDZ)
```javascript
const game = roomData?.game;
const me = game?.players?.[myId];
const myTurn = game?.turn === myId && game?.phase === "playing";
const myBonuses = me ? bonusesFrom(me.purchased) : emptyGems();
const aiThinking = game?.ai_player && game?.turn === game?.ai_player && game?.phase === "playing";
```
**These must stay before all `useEffect` hooks** — they appear in dep arrays and must be initialized first or Firefox throws a TDZ ReferenceError in production builds.

### WebSocket URL
`WS_BASE` is derived from `window.location`: `wss://host/ws` in prod, `ws://localhost:8000/ws` in dev.

### Reconnect tokens
Stored in `localStorage` as `spender_token_${roomId}_${myId}`. Sent on reconnect as `{action: "reconnect", token}`.

---

## Design decisions (do not relitigate)

- **Noble path commitment rejected**: User explicitly does NOT want the AI to commit to noble paths. Nobles are situational. The `_ai_score_card` noble proximity bonus stays, but there is no "noble target" locking.
- **`_schedule_ai_turn` unconditional call is fine**: Its internal guards make it a no-op when conditions aren't met. Calling it after reconnect is intentional (unsticks games after socket drops).
- **No Co-Authored-By in commits**: User explicitly prohibited this.
- **`save_game` is synchronous** (SQLite ~1ms write), called outside ROOM_LOCK.
- **Thread pool for MCTS**: `loop.run_in_executor(None, ...)` — no dedicated executor needed; default thread pool is fine for single vs-AI game.

---

## Known bugs / fixes applied this session

| Bug | Fix |
|-----|-----|
| TDZ `ReferenceError` in Firefox prod build | Moved derived game state (`game`, `me`, `myTurn`, etc.) before all `useEffect` hooks in Spender.jsx |
| AI blocking UI for 5s (human + AI moves batched) | Replaced sync `_post_turn` AI call with async `_schedule_ai_turn` task |
| "Game Not Started" when game was actually over | Split status check: `== "over"` → "game is over" before generic "not started" |
| Game stuck after socket drop during AI think | `_schedule_ai_turn` now called in both reconnect handlers |

---

## Build + deploy steps (production)
```bash
cd games/spender/webapp
npm run build
# Copy dist/* to docs/ and docs/assets/
# Update docs/index.html script src to new hashed bundle filename
cd ../../../
git add docs/
git commit -m "build: update webapp bundle"
git push
```
