# Spender Project — Claude Context

## Critical rule
**NEVER add `Co-Authored-By: Claude` (or any Anthropic attribution) to commit messages.** The user has explicitly prohibited this.

---

## Project layout

All Spender code/data lives under `games/spender/`. Root-level files (`Procfile`,
`render.yaml`, `docs/`, `requirements-lock.txt`) are repo-level deploy/Pages
orchestration and stay at root (they're structurally pinned there and will
orchestrate future games too). **Cross-cutting backend infrastructure (the DB
connection + the user/session/admin auth layer) lives in the top-level `core/`
package, NOT under `games/spender/`** — it was extracted out of
`games/spender/main.py` so features depend on `core`, not on a game (see
"`core/` — shared backend platform" below).

```
games/spender/
  main.py          # Spender server + MCTS AI logic; exposes `router` (APIRouter), not the app
  app.py           # deploy-entrypoint shim → re-exports the top-level composition-root app
  Spender.jsx      # React 18 frontend (single file)
  users.db         # SQLite — users + games tables
  Dockerfile, requirements.txt
  ai/              # ── all AI data + training tooling ──
    train.py       # OFFLINE self-play trainer (evolve/TD/value/tournament/coevolve)
    strategist.py  # scripted benchmark opponent
    weights.json   # deployed learned weights (variant A); loaded by main at import
    weights.tactics.json / weights.tactics_c.json   # variant B / C weight sets
    weights.targeting.json                          # playtest variant
    value_model.json                                # learned value-leaf model
    weights.coevolved.json                          # coevolve harvest (0.600 vs A)
    weights.c2.json                                 # C2 variant (noble_scarcity=2.5, pos_noble_scarcity=0.5); 0.583 vs B
    play_A_volume.ps1 / play_B_tactics.ps1 / play_B_targeting.ps1  # local launch scripts
    az/            # ── AlphaZero stack (offline training; serving via az_model.npz) ──
      engine.py    # fast compact-state simulator (rule-parity with main.py)
      actions.py   # 70-action space, masks, dict-move bridge (both directions)
      features.py / net.py / mcts.py / selfplay.py / train_az.py
      arena.py     # AZ vs heuristic tournaments;  bench.py  # throughput
      export.py / infer_np.py   # .pt -> .npz -> pure-numpy production inference
      checkpoints/ # gitignored: az_best.pt, az_last.pt, buffer.pkl, az_model.npz
  tests/
    test_game_logic.py
    test_train.py    # offline trainer: harness, evolve/TD phases, weight I/O
    test_az_engine.py   # az engine: 200-game differential parity vs main.py + edge cases
    test_az_actions.py  # masks, features, MCTS smoke, arena bridge, variant-Z serving
app.py             # ── composition root (REPO ROOT): FastAPI app + middleware + feature wiring ──
core/              # ── shared backend platform (imported by spender, coc, books) ──
  db.py            # dual sqlite/Turso connection wrapper (_Conn/_Cursor/_Row) + get_db_conn + init_core_schema
  auth.py          # users/sessions/passwords, admin + SITE_OWNER identity, reconnect tokens
  tests/test_db_auth.py   # wrapper + password + admin unit tests (in-memory sqlite, no server)
webapp/            # ── Vite + React build (REPO ROOT, neutral — not under games/spender/) ──
  main.jsx         # mounts games/spender/Spender.jsx (the shell, which routes to all features)
  index.html / vite.config.js / package.json
docs/              # GitHub Pages static site (Vite production build output) — REPO ROOT
  index.html
  assets/          # Hashed JS bundles (e.g. index-XXXXXXXX.js)
```

**`main.py` loads its AI data from `ai/`** via `_AI_DIR` (`weights*.json`,
`value_model.json`). The trainer is `python -m games.spender.ai.train` and writes
into `games/spender/ai/` by default.

### Serving
- Backend: `uvicorn games.spender.main:app --reload` (port 8000)
- Dev frontend: `cd webapp && npm run dev` (port 5173, proxies /ws to 8000) — repo-root, neutral
- Production: GitHub Pages serves `docs/`, which is **built and committed by CI** (`deploy-pages.yml`) on every push to `games/spender/**`. **Never hand-build/commit `docs/`** — commit source only and let CI deploy (see "Build + deploy steps" below).

---

## Castles of Crimson (second game)

`Castles of Crimson` is the **second game** in the Forrest Games collection — a
faithful digital port of the duchy-building dice-and-tile euro game (full base
game: 6 hex-tile types, 8 buildings, 26 unique monasteries, goods/ships, area
scoring, 5 phases × 5 rounds, bonus tiles, workers, central black depot, full
end-game scoring). 2-player only (human-vs-human or human-vs-bot).

```
games/castles_of_crimson/
  board.py     # the ONE standard duchy: radius-3 hexagon (37 spaces), axial (q,r),
               #   computed ADJACENCY + REGIONS (same-color connected components, size 1-8)
  tiles.py     # tile/supply data, AREA_SCORE/PHASE_BONUS, 8 buildings, 26 monastery meta
  effects.py   # (reserved) data-driven effect dispatch — currently effects live in engine.py
  engine.py    # PURE rules engine (no web deps): new_game/legal_moves/apply_move/
               #   final_scores/winner/is_over + all placement effects + lifecycle
  bot.py       # trivial random-legal-move opponent (choose / play_turn); rollout policy + fallback
  ai.py        # STRONG opponent: determinized MCTS + heuristic eval (Normal / Hard)
  ai_selfplay.py  # offline arena (hard vs normal vs random) — validation/tuning, no server/DB
  main.py      # FastAPI sub-app `coc_app` (rooms/WS/REST/persistence); thin — delegates rules to engine
  CastlesOfCrimson.jsx   # self-contained React component the shell mounts at screen "coc"
  tests/       # pytest, 102 tests (board invariants, placement, scoring, lifecycle,
               #   effects, one-per-monastery, endgame, random-vs-random smoke)
```

### Engine contract (the single source of truth for server, bot, tests, future AI)
- `new_game(player_ids, names=None, seed=None) -> game` — deterministic given seed.
- `legal_moves(game, pid) -> [move]` — covers normal die-actions AND pending sub-decisions.
- `apply_move(game, pid, move) -> (ok, err)` — validates + mutates in place; ALL scoring/
  replenish/phase-turn lifecycle/pending logic lives here.
- `is_over` / `final_scores` / `winner`.
- **RNG is persisted in `game["rng_state"]`** (getstate as JSON-safe lists) so per-phase depot
  replenishment + dice rolls stay reproducible across save/load. The game dict is JSON-safe
  (no sets anywhere — town_buildings/livestock_types/monastery_effects are lists).
- **Pending sub-decisions are real game-state keys** (`pending_pid`/`pending_kind`/`pending`),
  mirroring Spender's hard-won lesson, so they survive reconnect and are server-enforced.
  Kinds: `extra_action` (castle), `ship_choose_depot`, `ship_adjacent_depot` (monastery 5's
  optional second depot), `building_take_choice`, `warehouse_sell`, `townhall_place`. Every kind
  also accepts `skip_pending` (the bot/engine never deadlock).
- Move types: `take_hex`/`place_tile`/`sell_goods`/`take_workers`/`buy_black`/`adjust_die`/
  `discard_storage` (free; only legal when storage is full, to make room per the rulebook)/
  `end_turn`/`monastery6_take` + the pending resolvers above.
- **Rulebook-fidelity invariants** (audited against the base-game PDF): starting workers are
  seat-dependent (start player 1, next 2 — set in `new_game`, NOT a flat `START_WORKERS`); the
  hex supply is the exact **164-tile** base-game count (124 colored + 40 black, fixed/not tunable
  — see `tiles.build_supply` docstring); the black depot refills **4** tiles/phase
  (`BLACK_FILL_2P`). Starting castles never score; monastery 5 lets you *choose* the adjacent
  depot. These are locked by tests — don't "simplify" them away.
- **Deliberate house variant — fixed depot layout** (overrides the rulebook's random
  replenishment): each numbered depot is refilled every phase with exactly **two** hex tiles of
  fixed TYPES per `tiles.DEPOT_PLAN` (1: ship+building, 2: castle+monastery, 3: pasture+building,
  4: ship+building, 5: mine+monastery, 6: pasture+building). `_replenish_depots` draws those types
  from the shuffled supply via `_draw_type` (so the specific building/monastery/animal still varies
  by seed). The supply (124 colored) comfortably covers 5 phases × 12 = 60 typed draws. Locked by
  `test_depots_follow_fixed_plan` / `test_depots_refilled_each_phase`.

### AI opponent (`ai.py`) — determinized MCTS, two levels (Normal / Hard)
The real bot. Pure Python, no new prod deps; reuses the engine contract.
- **Determinized UCT** over `legal_moves`/`apply_move`. The ONLY hidden info is the *undrawn*
  supply order + future dice (`supply`/`black_supply`/`goods_supply` + `rng_state`); everything
  else is public. `_determinize` (per iteration) **canonicalizes** the undrawn pools (sort by tile
  id) then shuffles + reseeds the RNG, so the search provably can't depend on the hidden order
  (`test_move_invariant_under_supply_reshuffle`). Depots/duchies are left TRUE (visible). Bounded
  in-tree horizon (`_MAX_TREE_DEPTH`) → truncated rollout → **heuristic leaf eval `_value`** (the
  strength lever: realized `final_scores`-style score + weighted potential — mine income, area/
  color-completion proximity, monastery effects, empties penalty; weights in `WEIGHTS`).
- **Perf (was the hard part)**: two hot-path fixes give ~430 it/s in pure Python — (1) engine
  `_snapshot_turn` early-returns when `game["_skip_undo"]` is set (the AI sets it on clones; avoids
  a full `copy.deepcopy` on every simulated turn — the dominant cost), (2) `ai._clone_game` is an
  explicit shallow clone that SHARES immutable tile dicts + the wholesale-replaced `rng_state` and
  drops the move log (~120× faster than deepcopy). **Tiles are never mutated in place** — this
  invariant is what makes sharing safe; don't break it.
- **Difficulty** (`ai.DIFFICULTY`): per-decision budgets. `hard` = bigger time/iters, greedy.
  `normal` = small budget + visit-count **temperature** sampling (beatable blunders). Measured:
  **hard ≫ normal ≫ random** (hard 4/4 vs random by ~80-pt margins; hard 6/6 vs normal, 100 vs 39
  avg). Tune via `ai_selfplay.arena`; final calibration is a human playtest.
- **Serving**: `main._schedule_bot_turn` snapshots under `ROOM_LOCK` → plans the **whole bot turn**
  in a thread pool (`ai.play_turn_plan` via `run_in_executor`, mirrors Spender's `_schedule_ai_turn`)
  → re-locks → applies the move sequence → a trivial-`bot` finisher guarantees the turn ends (no
  deadlock). Room carries `ai_difficulty` (`_valid_difficulty`, default `hard`); frontend lobby has
  a Normal/Hard "vs Bot" pair sending `ai_difficulty`. The module import is aliased
  `from . import ai as coc_ai` because `ai` is a local var for the bot pid in `main.py`.

### Server (`coc_app`, mounted under `/coc`)
- `games/spender/main.py` mounts it at its **tail** with a **defensive try/except** (an earlier
  unconditional import was reverted in `fc6a2fa` because it crashed prod when the package wasn't
  committed; the wrapper means the core backend never goes down if the package is absent).
  WS = `/coc/ws/{room}/{player}`, REST = `/coc/...`, health = `/coc/health`, `/coc/board`
  serves the static layout to the frontend.
- Mirrors Spender's patterns: in-memory `ROOMS` under `ROOM_LOCK`, `save_game`/`load_game_to_memory`,
  `broadcast_room`, `mk_room_state`, stale-socket disconnect guard, async opponent scheduler.
- **Shared site identity**: imports the auth/DB helpers **directly at the top** from the `core`
  package (`from core.db import get_db_conn`, `from core.auth import gen_token, get_user_by_session,
  validate_reconnect_token, mark_reconnect_token_used`). These used to be lazy imports from
  `games.spender.main` to dodge an import-time circular dep; the `core` extraction removed the cycle
  (core depends on no game), so the lazy shims are gone. Persists rooms in its **own `coc_games`
  table** in the shared site DB; reuses the `reconnect_tokens` table (created by `core.init_core_schema`).

### Frontend (`CastlesOfCrimson.jsx`)
- Self-contained component the shell (`Spender.jsx`) mounts when `screen === "coc"`, passed
  `{ myId, authUser, onExit }`. Owns its own WebSocket + lobby + game screens.
- Namespaced localStorage (`coc_roomId`, `coc_token_{roomId}_{pid}`) so it never collides with
  Spender. WS/HTTP bases derive `/coc` from `VITE_WS_URL`.
- **Visual simplifications (user-requested)**: SVG hex duchy with plain single-color tiles (no
  icons) except **monasteries show their number**; empty spaces show their required die number;
  VP is a plain per-player counter; only your board is shown with a **View Opponent** peek button.
- **Depot ghost outlines (memory aid)**: because each numbered depot refills with the same two
  TYPES every phase (`tiles.DEPOT_PLAN`), a taken hex leaves a faint **colored hex outline** in its
  planned slot so the player remembers what goes where next phase. Driven by `DEPOT_PLAN_COLORS` +
  `depotGhostColors(d, hexes)` (planned-minus-present multiset) in the JSX; `.coc-tile-ghost` is a
  full-color clip-path hex with an inset `::after` filled `var(--surface2)` (the depot bg), leaving
  only a rim. Ghosts are inert (no click) and the central **black depot** (no fixed plan) is left
  untouched. `DEPOT_PLAN_COLORS`/`COLOR_TYPE_LABEL` are hardcoded mirrors of the backend plan.
- **Pending modals** render by `game.pending_kind` in `PendingModal` — one block per kind
  (`ship_choose_depot`, `ship_adjacent_depot`, `building_take_choice`, `warehouse_sell`,
  `townhall_place`, `extra_action`); each has a Skip. A new engine pending kind needs a matching
  block here or the human has no way to resolve it.
- **Discard button**: shown in the action row only when storage is full (`me.storage.length >= 3`)
  and disabled until a storage tile is selected — sends `discard_storage` to free a key space
  (mirrors the engine rule that the move is legal only when full).

### Deploy / branch notes
- Both workflow path filters now watch `games/castles_of_crimson/**` (pages = whole folder so the
  bundled `.jsx` rebuilds; render = `**/*.py`). The Dockerfile already `COPY . /app`s the package.
- **LIVE as of 2026-06-16.** `coc-game` was merged to `main` (PR #1) and the game is deployed:
  the **Castles of Crimson** home card is `status: "ready"` (shows **Play**), GitHub Pages serves
  the CoC-bundled frontend, and the backend mounts `coc_app` at `/coc` (`GET /coc/health` → ok).
  The merge brought `coc-game` (which was 48 commits behind) current with `main` — the only manual
  conflict resolutions were the two deploy workflows (path-filter unions), `Spender.jsx` (kept main's
  Books/variant-H additions + re-added the CoC import/entry/mount, dropped the old "Coming Soon"
  placeholder), and the `az_model.npz` binary (took main's). Validated by the full suite (433 passed)
  + a scripted vs-bot smoke (hard/normal to completion, no deadlock).
- **Frontend is feature-complete**: lobby board pickers, per-player board rendering, the setup-phase
  castle-selection UI (`setupPhase`/`setupMine`; clicking a glowing burgundy space during
  `game.phase === "setup"` sends `place_starting_castle`), and the depot ghost outlines (above).
- **Deploy flow (per user preference — see memory):** land changes on `main` directly, don't hand
  over a PR. `gh` is not installed and `main` is checked out in the `forrestm_projects-ai` worktree,
  so from the primary worktree: branch off `origin/main`, make the change, then
  `git push origin <branch>:main` (fast-forwards `origin/main`); CI rebuilds `docs/` + redeploys.

---

## Books (site feature — not a game)

A standalone site page for ranking favorite books + collecting reading suggestions
from other users. **Deliberately NOT under `games/` or `spender/`** — it lives in
its own top-level package so it's neither a game nor part of Spender.

```
books/
  __init__.py
  api.py            # FastAPI routes + SQLite logic (pure functions + thin handlers)
  Books.jsx         # self-contained React page the shell mounts at screen "books"
  tests/test_books.py   # 14 tests, in-memory DB (no server / no real users.db)
shared/
  theme.js          # baseCss — the site's shared design system (see below)
```

### Backend (`books/api.py`)
- Tables in the **shared `users.db`**: `books` (ranking), `books_meta` (owner claim),
  `book_suggestions` (per-user). Created by `init_books_db` via injected `get_db_conn`.
- Routes: `GET/PUT /books` (public read; owner-only write — full-list replace, blanks
  skipped, rating clamped 1–5, `sort_order` recomputed per-rating from incoming order)
  and `GET/PUT /books/suggestions` (each logged-in user manages their own up to
  `MAX_SUGGESTIONS=10` ranked picks + a why-read-it blurb; the **owner** `GET` also
  returns everyone's, grouped by suggester; 10-cap enforced server-side).
- **Wired into Spender's app**, not its own sub-app: `main.py` does
  `from books.api import setup_books; setup_books(app, get_db_conn, get_user_by_session)`.
  Deps are **injected** so `books` never imports `main` (no cycle). The absolute import
  is safe because `books` is a **sibling top-level package of `games/`** — repo root is
  on `sys.path` wherever `games.spender.app` loads (Procfile `python -m uvicorn`,
  Dockerfile `COPY . /app` + WORKDIR /app, pytest from root).
- Pure functions (`fetch_books`/`replace_books`/`fetch_user_suggestions`/
  `replace_user_suggestions`/`can_user_edit`/`is_owner`) take a sqlite conn → unit-tested
  against `:memory:` with no web server.

### Site-owner identity (reusable, in `main.py`)
- `site_owner_name()` / `is_site_owner(user)` read the **`SITE_OWNER` env var** (a
  *username*; read at call time). This is the **site-wide** owner check — books is the
  first consumer, but it's intended for any future owner/admin feature.
- `SITE_OWNER` **is set on Render** (to the owner's username). `books/api.py` reads the
  same `SITE_OWNER` key. If unset, books falls back to **first-authenticated-saver
  claims ownership** (stored in `books_meta.owner_id`) — convenient for local dev.
  `is_owner` is strict (unclaimed → nobody); `can_user_edit` treats unclaimed as
  editable-by-any-auth-user (so the first save can claim).

### Frontend (`books/Books.jsx`)
- Mounted by the shell (`Spender.jsx`) on `screen === "books"`; reached from a "📚 Books"
  link on the home menu (separate from the games grid). Props `{ authUser, onExit }`.
- Public ranking view (sections per star tier 5→1, ordered within) + owner edit mode
  (drag-reorder within a tier, rating picker, manual add). Suggestions section: owner
  sees all (grouped by suggester); other logged-in users get their own up-to-10 editor;
  logged-out users see a "log in to suggest" prompt.
- **Open Library** search-to-add (`<BookSearch>`, reused by both editors): keyless,
  CORS-enabled, queried client-side; picking a result auto-fills title/author/cover;
  covers from `covers.openlibrary.org` (`?default=false` so misses fall back to 📖).

### Shared theme (`shared/theme.js`)
- `baseCss` is the **single source of truth** for the site design: Cinzel/Crimson Pro
  font `@import`, `:root` color tokens, base `body`/`.app`, and `.btn`/`.input`
  primitives. Both `Spender.jsx` and `Books.jsx` import it and prepend it to their own
  CSS (`<style>{baseCss + screenCss}</style>`); the `@import` must stay first, so
  baseCss always leads. Extracting it left Spender's rendered CSS byte-identical (the
  primitives just moved out of Spender.jsx into the shared file).

### Deploy / branch notes
- Work lives on the **`feat/books`** branch (off `main`, isolated in worktree
  `forrestm_projects-books`). Pages workflow watches `books/**` + `shared/**`; Render
  watches `books/**`. `COPY . /app` already ships the new top-level dirs.
- **CLAUDE.md is no longer gitignored**

### Persistence — Turso/libSQL (production DB) — SITE-WIDE, not just Books
**The Render free plan has an ephemeral filesystem**: the SQLite `users.db` (which
holds users, games, coc_games, books, book_suggestions) is recreated **empty on
every deploy and every cold-start after the free service idles**. So accounts,
games, AND book rankings did not persist across restarts. Books made this pressing
(its whole point is a persistent ranking), but it affects the whole site.

Fix (now in **`core/db.py`** — extracted out of `games/spender/main.py`):
`get_db_conn()` is a **dual backend** behind a tiny driver-agnostic wrapper:
- **Local sqlite3** (default) — dev + the test suite + the prod *fallback*.
- **Turso / libSQL remote** — used when **`TURSO_DATABASE_URL`** (and
  `TURSO_AUTH_TOKEN`) env vars are set, so data persists off the ephemeral disk.
- `_Conn`/`_Cursor`/`_Row` wrap either driver so rows work by BOTH index (`row[0]`)
  and column name (`row["id"]`) — the existing queries are unchanged. `executemany`
  is implemented as a loop (libsql may lack a native one).
- A **boot-time `_turso_selftest()`** connects + round-trips a row through the
  wrapper; **any failure logs a warning and falls back to local sqlite** (site stays
  up, just non-persistent) — it never crashes boot. Watch the log for
  `Turso/libsql verified` vs `falling back to LOCAL sqlite`.
- `libsql` is in `requirements.txt` but **imported lazily** only when Turso is
  configured. **`libsql` has no wheel for Python 3.14** (local dev) and can't build
  without Rust — but **prod Docker is Python 3.11** (wheels exist), so it's
  install-and-run there. **Consequence: the Turso path cannot be tested locally on
  this machine** — validate it via Render logs + a live login that survives a
  redeploy. The sqlite path (identical wrapper) IS locally tested.
- **Setup the user must do** (one-time): create a free Turso DB + auth token
  (`turso db create` / `turso db tokens create`, or dashboard), then add
  `TURSO_DATABASE_URL` (the `libsql://...turso.io` URL) and `TURSO_AUTH_TOKEN` as
  Render env vars. Until then prod silently uses ephemeral sqlite (zero behavior
  change). `SITE_OWNER` is unaffected (it's env-based, not stored).

---

## `core/` — shared backend platform (DB + auth)

The **top-level `core/` package** holds the cross-cutting backend infrastructure
that every site feature needs. It was **extracted out of `games/spender/main.py`**
(Phase 1 of the architecture cleanup) so features depend on a neutral platform
layer instead of reaching into a game module. **`core` imports nothing from
`games`/`books`** — it is the bottom layer, which is what removed the circular
imports the old arrangement required.

- **`core/db.py`** — the dual **sqlite/Turso** connection: `_Row`/`_Cursor`/`_Conn`
  wrapper, `_turso_selftest`, `get_db_conn`, and **`init_core_schema(conn)`** (creates
  the cross-cutting `users` / `admins` / `reconnect_tokens` tables). `DB_PATH`
  defaults to the legacy `games/spender/users.db` for backward-compat (override with
  `SITE_DB_PATH`); in prod Turso is used and this path is only the fallback.
- **`core/auth.py`** — `gen_token`, `hash_password`/`verify_password` (PBKDF2 + legacy),
  `create_user`, `authenticate_user`, `get_user_by_session`, the SITE_OWNER/admin
  identity helpers (`site_owner_name`, `grant_admin`, `is_admin_id`, `is_site_owner`),
  and the reconnect-token helpers (`create`/`validate`/`mark_used`). Imports
  `get_db_conn` from `core.db`.
- **Game retention** (`core/db.py`): `cleanup_stale_games(table)` deletes stale rows
  from a games table (`games` / `coc_games` — same shape) by **last activity
  (`updated_at`)**: an **all-guest** game (no player id present in `users`) after **24h**,
  a game with **any registered player** after **30d** (so a registered user's history
  survives even a game played with a guest). `maybe_cleanup_games(table)` is the throttled
  wrapper (≤1×/hour/table/process). Wired in BOTH games: `cleanup_stale_games(...)` once at
  module import (cold-start) + `maybe_cleanup_games(...)` at the top of each `list_open_games`
  (so it also runs during long-awake periods — Render's free tier has no cron). Tests:
  `core/tests/test_game_retention.py`.
- **Who imports it now**: `games/spender/main.py` (`from core.db import …`,
  `from core.auth import …`; its `init_db()` calls `init_core_schema` then creates only
  the Spender-owned `games` table), `games/castles_of_crimson/main.py` (directly at the
  top — the old lazy shims are gone), and Books (via the injected `get_db_conn`/
  `get_user_by_session` `setup_books` still receives — main passes the core functions).
- **Tests**: `core/tests/test_db_auth.py` (wrapper + password + admin + `init_core_schema`,
  in-memory sqlite). CI runs `core/tests/` first; Render watches `core/**/*.py`.
- **Not yet done** (later phases): the frontend shell extraction (the site shell still
  lives inside `Spender.jsx`), and DRYing the duplicated room-server scaffolding (Phase 3).

### Composition root — top-level `app.py` (Phase 2, done)
The FastAPI **`app` and the feature wiring no longer live in a game module.** The
top-level **`app.py`** is the composition root: it creates `app = FastAPI(...)`,
applies CORS middleware, `include_router`s Spender's routes, `setup_books(...)`,
and mounts Castles of Crimson at `/coc` (same defensive try/except as before).
- `games/spender/main.py` now exposes **`router = APIRouter()`** (all its routes use
  `@router.…`, including the single `/ws/{room}/{player}` websocket) instead of owning
  the app. It still runs `init_db()` at import.
- **Layering**: `core/` (bottom) → features (`games.spender`, `games.castles_of_crimson`,
  `books`) → `app.py` (top). The composition root depends on features; features don't
  depend on it. `core` depends on neither.
- **Deploy entrypoint is unchanged**: `games/spender/app.py` is a thin shim doing
  `from app import app` (absolute import of the top-level module — repo root is on
  sys.path), so Procfile/Dockerfile/render.yaml keep targeting `games.spender.app:app`.
  Render also watches the new top-level `app.py`.

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

### WS disconnect cleanup — stale-socket guard
The `finally` block in `ws_room_player` only removes a socket and potentially the room if `r["sockets"].get(pid) is websocket` (the exact WS object for this handler). This prevents a reconnect race: when WS1→WS2, WS2 registers its socket first; without the guard, WS1's finally would remove WS2 and delete the room, causing "game not started" on the next move or a waiting-screen flash if the reconnect response was built after deletion.

### AI pipeline
- `_mcts_choose_move(game, ai_pid, time_limit=5.0, max_iters=None)` — tree MCTS with `_MCTSNode`. Stops at whichever of `time_limit` (wall-clock, prod) or `max_iters` (iteration count, training) is hit first.
- `_MCTSNode` uses `__slots__`, UCB1 child selection (negates exploit for opponent nodes), iterative backprop
- `_fast_rollout_move` — rollout policy: buy > reserve high-value > take gems
- `_ai_score_card` — heuristic with deficit-weighted accessibility multiplier
- `_sim_rollout` — max 25 turns, linear position evaluator (`pos_points*pts + pos_buyable*buyable + pos_noble*noble_proximity + pos_bonus_count*bonus_count`)

### AI weights (`WEIGHTS` / `weights.json`)
All heuristic magic-numbers live in `DEFAULT_WEIGHTS` (a module-level dict); the live values are in the global `WEIGHTS`. `load_weights()` runs **at import**: it merges `weights.json` (if present, in the package dir) over the defaults — unknown keys ignored, missing keys keep defaults, malformed/missing file falls back silently. **Defaults equal the original hand-tuned constants, so production play is byte-identical unless a `weights.json` is deployed.** Two weight groups:
- **Card-scoring** (`point_urgency_mult`, `bonus_l1/l2/l3`, `bonus_reserved`, `bonus_urgency_decay`, `noble_card`, `access_base`, `access_urgency`, `rollout_reserve_threshold`) — drive `_ai_score_card` + rollout policy (how the AI *picks moves*).
- **Position-eval** (`pos_points`, `pos_buyable`, `pos_noble`, `pos_bonus_count`) — drive `_sim_rollout`'s truncation evaluator (how the AI *evaluates positions*).

### Self-play training (`train.py`, offline only)
`train.py` plays the AI against itself headlessly (~290 greedy games/s) to learn `WEIGHTS`, then writes `weights.json`. It imports `main`'s game logic directly; it never starts the server or touches `users.db`. It swaps the global `main.WEIGHTS` to each mover's weights before its decision.
- **Phase 1 — `evolve`**: population of card-scoring weight vectors plays a round-robin self-play tournament; mutate + select by win rate. Tunes the move policy.
- **Phase 2 — `td`**: TD(λ) with eligibility traces learns the linear position-eval weights toward the realised point margin from self-play trajectories. (TD(0) was tried first and **diverged** on the highly-correlated consecutive board states — `pos_points` collapsed, error rose — so λ-traces + feature scaling are used; λ→1 recovers Monte Carlo.)
- **`all`** runs both in sequence; **`validate`** plays learned-vs-default with real MCTS and reports the learned side's score (only deploy `weights.json` if >0.5).
```bash
python -m games.spender.ai.train all --generations 20 --pop 12 --games-per-pair 12 \
    --td-games 3000 --validate-games 40 --out games/spender/ai/weights.json
```

### Deployed weights (current)
A trained `weights.json` **is currently deployed** (the backend loads it at startup). It beat the original hand-tuned defaults **0.725 vs 0.275** over 40 MCTS validation games (150 iters/move, seats swapped). Notable shifts the AI learned:
- `bonus_l1` 0.2→0.63 (values cheap L1 engine-building more), `bonus_reserved` 0.5→0.01 (stopped valuing bonuses toward reserved cards), `access_urgency` 0.4→0 (dropped late-game distance penalty), `rollout_reserve_threshold` 5.0→8.8 (much more selective about reserving).
- `pos_noble` 0.3→2.19 (noble proximity is ~7× more predictive of final margin than hand-tuned), `pos_bonus_count` 0→0.91.

To **revert to the original AI**, delete `games/spender/ai/weights.json` — `load_weights()` falls back to `DEFAULT_WEIGHTS` with zero behaviour change. Caveats: validation ran at 150 MCTS iters/move, not production's 5-second budget; evolve fitness plateaued at 0.674 by gen 4 (search converged early — larger pop / higher `sigma` to explore further).

### Stage 1: learned value leaf evaluation (`value_model.json`)
NNUE-style: when a `value_model.json` is present, MCTS evaluates leaf nodes with a learned logistic value model (`_value_estimate`/`_value_logit`, **pure-Python inference** — no production ML dependency) instead of a greedy rollout. Absent → rollout, byte-identical. `_value_features` is a 10-feature `order[0]`-minus-`order[1]` diff + turn indicator. `load_value_model` rejects a model whose feature count ≠ `VALUE_FEATURES` (falls back to rollout). Trained offline by `train.py value` (numpy) on exploratory self-play; a **linear** model is deployed.
- **Validated**: value-leaf beats rollout **0.533 vs 0.467** on equal *wall-time* (cheaper eval → more MCTS iterations). At equal *iters* it loses — its advantage is speed, so always A/B by **time** (`--time`), not iters.
- Playtest toggles: `SPENDER_VALUE_MODEL=none uvicorn …` forces rollout; `SPENDER_WEIGHTS=…` swaps weight sets.

### AlphaZero stack (`ai/az/`) — the current strength roadmap
Approved plan: fast engine → AlphaZero self-play → tournament eval → serve as
variant **Z**. 2-player only. Key facts:
- **engine.py** is a compact int-state simulator with **proven rule parity**:
  200 random games stepped through both engines with state compared after every
  move (`test_az_engine.py`). Card/noble data is imported from `main.py`, never
  duplicated. ~100k moves/s/core (pure Python; Rust port not needed).
  Gold DOES count toward the 10-token cap. Discard/noble-choice are real
  decision phases (the policy learns them). `to_game_dict`/`from_game_dict`
  convert to/from the incumbent dict format.
- **mcts.py**: PUCT, hidden info via per-simulation determinization (unseen =
  decks + opponent blind reserves, reshuffled within level). Turns don't
  strictly alternate, so backups credit edges by acting-player identity.
- **train_az.py**: self-play → train → gate (promote at >=0.55) → auto-export
  `.npz`. Resumable (`--resume`). Trains on the user's RTX 4050 (torch cu128,
  Python 3.14). `selfplay.run_games` is the single batched driver for both
  self-play and net-vs-net gating.
  - **`--iters` is an absolute total**, not "N more": on resume the loop runs
    `range(start_iter, args.iters)`. To add 70 iters after a 30-iter run:
    `--resume --iters 100`.
  - **Exploration / reward knobs** (added after the degenerate-equilibrium
    diagnosis below): `--reward-shaping` (0..1), `--shaping-scale`,
    `--temperature`, `--temp-moves`, `--dirichlet-eps`. Self-play log prints
    `winpts` (winner's avg points/game) + `combined` — the scoreboard that
    makes the 0-0 collapse visible.
  - **Parallel self-play** (`--workers N`, default 1): fans games across N CPU
    processes via `selfplay.run_games_parallel` (each worker does CPU numpy
    inference off a `.npz` snapshot of the current net; GPU stays free for the
    training step). The gate parallelizes too. `--workers 1` keeps the old
    single-process torch path. ~4.8x self-play throughput at 10 workers on the
    12-core laptop (~700s -> ~160s/iter self-play); ~3-4x end-to-end.
    - **CRITICAL — single-thread BLAS/OMP.** `train_az.py` sets
      `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB_*_NUM_THREADS=1` at the very TOP (before
      numpy/torch import) so spawned workers inherit it. Without this, every
      worker's BLAS spins one thread per core -> 10 workers x 12 threads thrash
      the box (observed: 30+ min hang producing zero output). GPU training in
      the parent is unaffected (CUDA, not BLAS). Do not remove this block.
- **watch_game.py**: prints a human-readable play-by-play of one
  AZ-vs-heuristic game (board, both players' state, AZ's top MCTS visit
  distribution, the move taken). The diagnostic that surfaced the equilibrium
  bug. `python -m games.spender.ai.az.watch_game --az <npz> --opp C2 --seed N`.
  (Keep output ASCII-only — Windows console is cp1252; no box-draw/arrow glyphs.)
- **Serving**: `main.py` loads `ai/az_model.npz` if present → variant "Z"
  (numpy-only PUCT via `infer_np.py`, same 5s thread-pool path). No file → Z
  falls back to A; zero behavior change. `SPENDER_AZ_MODEL=none` disables.
  Production deps gained only `numpy`; torch stays out of prod.
  **`az_model.npz` is currently deployed** (exported from iter-177 best checkpoint,
  p=0.90, 113 promotions, sims=512). Variant Z is live on the website. Export process:
  `ckpt = torch.load('az_best.pt', map_location='cpu'); net.load_state_dict(ckpt['best']); export_npz(net, 'az_model.npz')`.
  Render auto-deploys on push to `ai/az_model.npz` (wired in `deploy-render.yml`).
  Can export mid-training safely (training writes `az_best.pt`; export reads it and
  writes `az_model.npz` — separate files, no interference).
- **arena.py**: AZ vs heuristic tournaments (heuristic plays via dict
  conversion + its own `_mcts_choose_move`; sub-decisions replicate
  `_ai_discard_one`/`_ai_pick_noble`). Wilson CIs. Deploy gate: >=0.70 vs B
  and C2 at production budgets + human playtest.

### AZ — the degenerate-equilibrium bug and the reward-shaping fix (June 2026)
**This is the most important AZ finding so far. Do not relitigate.**

The first AZ run (`checkpoints/`, 58 iters, pure terminal win/loss reward)
trained healthily by its own gate (candidate-vs-best score rising, promote→dip→
recover) but **lost ~0.0 vs C2** in the arena at every checkpoint measured:
| Checkpoint | AZ vs C2 (60g) | notes |
|------------|----------------|-------|
| Iter 13    | 0.017          | 300 sims |
| Iter 28    | 0.050          | 300 sims |
| Iter 40    | 0.017          | 300 sims; **also 0.000 at 1000 sims** |
| Iter 54    | 0.017          | 300 sims (best gate score 0.683) |

More search did NOT help (1000 sims = 0.000) → the **policy**, not search depth,
was the problem. `watch_game.py` on iter-40 vs C2 (seed 42) showed why: **AZ
scored 0 points the entire game**, bought 7 cards (all 0-point L1), hoarded
tokens and discarded them ~15×, and opened by reserving two 7-cost L3 cards it
could never afford. C2 scored 16, bought 26 cards, claimed a noble.

**Root cause — a degenerate self-play equilibrium.** Both self-play players share
one net. Early nets rarely score, so games end 0-0 and the winner is decided by
the **fewest-cards tiebreak**. That makes "buy as little as possible" the
self-play-optimal strategy — the exact opposite of what beats a scoring
opponent. The net faithfully optimized the tiebreak. This explains all three
symptoms: healthy gate scores (it got better at the tiebreak vs itself), zero
arena wins (vs a scorer the tiebreak never triggers), and no benefit from more
sims (searching harder for the wrong objective). It is the same blind-spot class
as the documented "self-play is blind to tactics the opponent never demonstrates."

**Fix (shipped in `selfplay.py` / `train_az.py`):**
1. **Reward shaping** (`--reward-shaping`, default 0): value target blends
   terminal win/loss with `tanh(point_margin / shaping_scale)` per mover
   perspective. A 0-0 game becomes a true neutral instead of rewarding the
   buy-nothing tiebreak winner; actually scoring is what gets rewarded. Verified:
   shaping=0 → value targets take 2 distinct values (±1); shaping=0.5 → 28
   graded values in [-1,1].
2. **More exploration**: `--temp-moves` 10→20, `--dirichlet-eps` 0.25→0.35, so
   the net stumbles into point-card buys often enough to learn they're good.
3. **`winpts` scoreboard** in the self-play log makes the equilibrium visible:
   ~0 = degenerate; climbing toward 12–16 = the net is learning to score.

**Validation run** (fresh, NOT resumed — old net/buffer are attractors toward the
broken strategy; new dir `checkpoints_shaped/`):
```bash
python -m games.spender.ai.az.train_az --iters 60 --games 400 --sims 128 \
  --parallel 128 --gate-games 60 --gate-threshold 0.55 \
  --reward-shaping 0.5 --shaping-scale 6.0 --temperature 1.0 --temp-moves 20 \
  --dirichlet-eps 0.35 --out games/spender/ai/az/checkpoints_shaped
```
Iter 0 (random-net baseline): winpts 15.7. The verdict is whether iters 1–5 HOLD
winpts high (fix works) vs collapse toward 0 (the old run would have collapsed
here). **Do not ship az_model.npz until arena shows >=0.70 vs B and C2.**

### AZ league — training vs opponents, not just self (the strength lever)
Pure self-play hit a hard ceiling vs the heuristics: arena AZ-vs-C2 was **0.033
at iter 9 and 0.025 at iter 27** — FLAT across 18 iters of shaped self-play,
even though the self-gate score kept rising (the net got better at beating its
own clones in a strategy space that doesn't overlap C2's). This is the
documented "self-play is blind to a style the opponent never demonstrates."
**Cure = play against the real targets.** (`league.py` + `--league` in train_az.)

- **`league.py`**: `play_recorded_game(net_eval, opponent_fn, ...)` plays one
  game where the training net searches+records ONLY its own moves (shaped value
  targets, same as selfplay) while the opponent moves via a callback. Opponents:
  heuristic A/B/C2 (`arena._heuristic_action`, incumbent MCTS in dict format) or
  a frozen past-AZ checkpoint (`_az_opponent_action`, greedy PUCT on its npz).
  We record only the net's moves — learning to BEAT opponents, not imitate them.
  These games are NOT batchable (opponent isn't the net), so they run
  one-at-a-time inside pool workers via `run_league_games`, which also returns
  per-opponent net win rate — the live progress-toward-goal signal.
- **`--league`** (needs `--workers>1`): each iter mixes `--self-frac` self-play
  (batched) + `--heur-frac` split across `--heur-variants` + `--league-frac` vs
  sampled past-AZ checkpoints from `out/league_pool/` (snapshotted on each
  promotion, capped at `--pool-size`). Empty pool folds the past-fraction into
  self. Reward shaping is doubly important here: the net loses most early games,
  so the margin term ("lost by 2" vs "lost by 15") is what provides the climb
  gradient. Deployed mix (user-approved broad): self .4 / heur .4 (A,B,C2) /
  past .2, `opp_iters=120`.
- **League gate**: candidate vs best on the SAME heuristic set, greedy
  (`_league_gate`), promote if cand >= best (ties promote early while both lose
  to C2). Replaces the self-gate, which was exactly the misleading metric (it
  rose while real strength stayed flat). The `[iter] league:` log line prints
  `net-vs: A .. B .. C2 ..` — watch C2 climb off ~0.
- **Launch** (resumes from the shaped iter-27 net):
  ```bash
  python -m games.spender.ai.az.train_az --iters 80 --games 400 --sims 128 \
    --workers 10 --gate-games 60 --gate-sims 96 --reward-shaping 0.5 \
    --temperature 1.0 --temp-moves 20 --dirichlet-eps 0.35 \
    --league --self-frac 0.4 --heur-frac 0.4 --league-frac 0.2 \
    --heur-variants A,B,C2 --opp-iters 120 --opp-sims 96 --pool-size 6 \
    --out games/spender/ai/az/checkpoints_shaped --resume
  ```

### AZ open risk — single-strategy collapse (raised by the user, valid)
Even with scoring fixed, pure self-play can tunnel on ONE plan (e.g. wide-L1 →
nobles) and never learn that rushing efficient high-point L2/L3 cards beats it on
many boards — because both shared-net players adopt the same plan, the
counterexample is never generated, and the value head mis-evaluates the unplayed
line (so search can't rescue it; garbage value → garbage search). The user's own
strategy model says the right plan is **board-conditional**, and the features
encode the board, so the net CAN represent "rush here, go wide there" — it just
needs to SEE both resolve. **Planned mitigation = opponent diversity (a league):**
train/gate against a sampled pool of {past AZ checkpoints + heuristic A/B/C2},
not only the current best. This is the real reason to keep the heuristic-in-loop
idea (it was deferred for breaking the 0-0 equilibrium, where shaping subsumes
it, but it is the primary cure for strategic diversity). Build after scoring is
confirmed stable.

### AZ — the fitness-valley wall and the adaptive curriculum (June 2026)
**Reward shaping was NOT the bottleneck — don't relitigate it.** Both the league
(tanh) and a linear-shaping rerun left the net FLAT at ~4 pts / −12 margin vs C2
across 10–27 iters (margin probe: net scores ~4, C2 ~16, win rate ~0). Linear
shaping gives a ~6× stronger per-point gradient (verified) yet moved nothing.

**Root cause — a fitness valley, not a weak gradient.** Against a *fast* opponent
(C2 reaches 15 in ~16 plies), the loss-minimizing play is to grab a few quick
points (~4) — a local optimum. WINNING requires building an engine (cheap
0-point cards early) that only pays off later — but C2 ends the game before the
payoff, so margin-minimization *punishes* the very investment winning needs. The
winning strategy sits across a valley from the loss-minimizing one; gradient
won't cross it. Evidence the net CAN play well given time: it scores 15+ in
self-play (80–120-ply games) — it just builds engines ~5× too slowly and never
faces a beatable racer to learn tempo from.

**Probes that found the curriculum axis** (current net vs opponent, 30g):
- vs **random**: net **wins 0.87** (scores 14) — beats non-racers easily.
- vs heuristic at **any** `opp_iters` (even 1): **0.00–0.20** — every competent
  eval RACES (opp ~16 pts) regardless of search depth. So `opp_iters` is a
  *cliff*, not a ramp — wrong curriculum axis.
- **eps-mixed opponent** (heuristic move w.p. `p`, else random) gives a SMOOTH
  ramp: net win rate 0.80 / 0.70 / 0.47 / 0.20 / 0.07 at p = 0 / .25 / .5 / .75 / 1.
  `p` is a **tempo** knob — the right axis.

**Adaptive curriculum** (`--curriculum` in train_az, `eps` kind in league.py):
the heuristic fraction faces an eps-opponent at difficulty `p`; after each iter
`p` auto-climbs if the net's win rate vs the current level ≥ `--curr-target`
(0.55), drops if it falls behind — keeping the net at its winnable frontier. Goal:
ride `p` → 1.0 (full racer) with the net still winning, which means it learned to
race. `p` persists in checkpoints. Log line: `[iter] league: p=X.XX … net-vs:
cur Y.YY`. Launched resuming the v3 net (competent at low p) with a CLEARED
buffer (so the value head drops its "always lose" pessimism). Watch `p` climb;
a stall = the tempo wall it can't yet cross.

**`p` adapts from the GREEDY GATE score, not the generation win rate.** Early on
the generation `net-vs cur` (~0.38) ran far below the gate's greedy score (0.667
at the same p) because self-play exploration (temp + Dirichlet) depresses
play — using it to drive `p` kept the curriculum stuck artificially low. So the
adapt step moved to *after* the gate, using the promoted/best net's greedy gate
win rate (`_curriculum_gate`): `p += --curr-step` if ability ≥ target+0.05,
`-=` if ≤ target−0.10, deadband holds. With this, `p` climbed 0.35→0.40→0.45→0.50.
End condition (beat full racer greedily ≥0.55) aligns with the deploy arena gate.

**Search depth is the quality lever (`--sims`).** Bumped 128→384 (`--gate-sims`
96→192), user OK with ~3× slower iters. Rationale: the net distills the MCTS
visit distribution, so shallow search = weak policy targets; deeper search also
finds the efficient racing lines the net otherwise never sees (directly attacks
the tempo problem) AND makes the curriculum games themselves better-played. Try a
bigger net (the MLP is only ~600k params) ONLY if sims plateaus — capacity before
data/search quality just overfits. **sims bumped 384→512** after plateau at p=0.80
— confirmed working, frontier moved to p=0.85 then p=0.90. **sims bumped again
512→768** (gate-sims 256, opp-sims 128) after plateau at p=0.90 for ~18 iters
with gate scores stuck at 0.53–0.58 — watching whether frontier moves to p=0.95.

**gate-games bumped 60→120** (SE ±0.065 → ±0.046) after variance was causing
artificial p drops: a single unlucky 26/60 gate ended a 14-iter p=0.90 streak.
With 120 games the net held p=0.90 for 18+ consecutive iters cleanly before the
sims bump.

Current run: `checkpoints_v3`, at iter ~196, p=0.95, sims=768, --iters 300.
sims=768 pushed frontier to p=0.95 by iter 191 (best=0.617) and the net is
**holding p=0.95** for the first time (5 consecutive iters 192–196, gate scores
0.40–0.52). `az_model.npz` deployed at iter 177 (113 promotions). Next milestone:
gate score ≥0.60 at p=0.95 → push to p=1.0 → arena vs B/C2 → ship if ≥0.70.

**Human playtest finding (iter 177 net):** the net **over-reserves** — reserving
frequently and often reserving cards that don't make strategic sense. Root cause:
(1) self-play doesn't punish tempo loss from bad reserves because both players do
it; (2) gold token over-valuation in the value head biases toward reserving;
(3) shallow search doesn't see the downstream cost of a wasted turn. Sims bump
directly attacks (3). (1) and (2) require structural fixes:
- **Better features** (planned for next retrain — incompatible with current weights,
  requires fresh start): three high-value additions:
  1. **Effective cost** per card (raw cost minus player's current bonuses, per color).
     The net can technically derive this from existing features but has to learn
     the subtraction internally; explicit = much easier to use.
  2. **Engine value** per card — pre-computed scalar: this card's bonus color ×
     sum of cost-reduction it provides to every other visible card, weighted by
     those cards' point value. This is a *cross-card interaction* an MLP cannot
     easily discover on its own from a flat feature vector (requires reasoning
     across multiple cards simultaneously). Pre-computing it as a feature is a
     genuine win — directly addresses "which card is worth reserving/buying."
  3. **Turns-to-afford** per card — cost gap per color ÷ estimated gems/turn.
     Addresses reserve *frequency* (tempo awareness), not just card selection.
     "This card needs 4 more red gems; I'm collecting ~1/turn → 4 turns away"
     directly distinguishes smart reserves from wasteful ones.
  Noble-progress per card (how many noble requirements this satisfies) is also
  worth adding but partially encoded already.
  **Do NOT add these features mid-run** — input dimension change invalidates all
  current weights. Schedule for a fresh retrain after the current run finishes.
- **Harder opponents**: C2 races but doesn't punish bad reserves as severely as a
  human. The net needs to face opponents that end the game before wasteful reserves
  pay off.
- **Sims ceiling**: more search helps up to a point, but if the value head
  fundamentally misvalues tempo, MCTS just finds better moves within a flawed
  strategy. The remaining lever after sims is value function quality + features.

**Checkpoint system and branching (how to experiment safely):**
- Training saves to `checkpoints_v3/`: `az_best.pt` (best promoted net — dict with
  `best` weights, `iter`, `promotions`, `curr_p`), `az_last.pt` (latest candidate),
  `buffer.pkl` (300k-position replay buffer). All gitignored.
- **Fully resumable**: stop anytime, restart with `--resume` — picks up exact iter,
  p value, and buffer. Can pause indefinitely.
- **Branching for a feature experiment**:
  1. Stop current run.
  2. Copy `checkpoints_v3/` → `checkpoints_v3_backup/` to preserve the original.
  3. Modify `features.py` (new features change input dimension → old weights incompatible).
  4. Start a **fresh** run in a new dir (e.g. `checkpoints_v4_features/`) — no `--resume`.
  5. If new net wins arena → ship; if worse → delete branch, `--resume` from backup.
  - The branch is a genuine fresh start — the 196+ iters of learned weights cannot
    carry over to a new input dimension. Trade-off: known-good current net vs
    untested feature-enriched net that starts from zero.
  - **Decision point**: finish current run first, evaluate iter-300 net strength,
    then decide if a feature-enriched retrain is worth losing the current weights.

### Heuristic-tuning campaign results (June 2026 — superseded by AZ stack)
- Ablation (40g, 120 iters, seed 777): `noble_scarcity=1.5` → 0.688 vs B was
  the only strong feature; `pos_noble_scarcity` 0.588; `lose_prevention` 0.525;
  `efficiency_weight`/`bonus_target_pts`/`gold_reserve` all hurt.
- Sweep grid (seed 42): best combo `noble_scarcity=2.5 + pos_noble_scarcity=0.5`
  → 0.675 screening, but **0.583 on the fresh-seed 60-game confirm** —
  regression to the mean; the gain is real but ~0.58-0.65 true, NOT 0.70.
  Candidate file: `ai/weights.c2_candidate.json` (uncommitted).
- Coevolve (6 gens, real MCTS): `lose_prevention`/`gold_reserve` selected out
  to 0.0; best individual validated 0.600 vs A → `ai/weights.coevolved.json`.
- Conclusion: weight-space tuning over the existing features saturates around
  0.6 vs B. This is why the AZ rewrite exists.

### Hard-won conclusions — DO NOT relitigate
These cost many self-play/training cycles to establish:
- **Eval-weight tuning is saturated.** One gain (0.725 vs original), nothing since. The first run captured it.
- **Evaluation quality is NOT the bottleneck.** Static-eval accuracy plateaus ~0.65 *regardless of model class or features*: an **MLP** (more capacity) and **Stage 1c richer features** (per-colour bonuses/tokens, reachability/threat) both gave the same ~0.64–0.66 and were reverted. The missing information (future deck draws, deep lines) isn't in any static snapshot — it needs **lookahead**. **The remaining lever is SEARCH, not evaluation.**
- **Self-play is blind to blocking/contested tactics** — its opponent never threatens coherently, so denial never pays off and those features (`contested_weight`, `block_urgency_gate`) train toward off. A scripted `strategist.py` opponent is competent (~greedy strength) but **MCTS saturates it 12–0**, so it can't measure improvements above current strength either. **The only reliable judge of the human-exploitable weakness is a human playtest.**
- **Next lever = search**: (1) audit `_get_all_moves` pruning (winning lines may never be enumerated), (2) tree reuse between moves + UCB sweep, (3) AlphaZero-style policy head + real exploration (the eventual cure for tactics, biggest build).

### Move handler error hierarchy
```python
if not r:                          → "game not started"
elif r.get("status") == "over":    → "game is over"
elif r.get("status") != "playing": → "game not started"
else:
    if g.get("phase") == "over":   → "game is over"
    elif g.get("turn") != pid:     → "not your turn"
    # per-turn pending-action guards (move must resolve these first):
    elif g.get("pending_noble_pid")   == pid and type != "pick_noble": → "must choose a noble first"
    elif g.get("pending_discard_pid") == pid and type != "discard":    → "must discard down to 10 gems first"
```

**Pending-action state lives in the `game` dict** (not transient message fields), so it survives saves/reconnects and is enforced server-side: `pending_noble_pid` (multi-noble choice) and `pending_discard_pid` (over-10 gems). Both are set when the condition arises and cleared when resolved. The frontend derives `needsNobleChoice`/`needsDiscard` from these game-state keys — a stray `room_update` can't clear an unmet requirement.

**Discard undo**: any action that overfills past 10 gems (`take_gems`/`reserve`) first deep-copies the pre-action game into `g["pre_discard_snapshot"]` (only persisted when it actually overfills). The discard modal offers "↩ Undo turn" → `move type: "undo_discard"`, which restores `r["game"]` from the snapshot (reverting the take/reserve **and** any partial discards) and re-opens the player's turn. The snapshot is popped when the discard completes normally, and (like `pending_discard_pid`) it's part of saved game state so undo survives a reconnect.

---

## Frontend architecture (Spender.jsx)

### Screen flow
`"auth"` → `"browser"` → `"waiting"` (2-player) | `"game"` (vs-AI goes directly)

### Message handlers that transition screen
`inGame(status)` = status is `"playing"` **or** `"over"` (a finished game stays on the game screen so the winner/review UI shows; only a not-yet-started game goes to `"waiting"`).
- `"created"`: → `"game"` if `inGame`, else `"waiting"`
- `"joined"`: → `"game"` if `inGame`, else `"waiting"` (mirrors `"reconnected"`)
- `"reconnected"`: → `"game"` if `inGame`, else `"waiting"`
- `"room_update"`: → `"game"` only if `inGame` AND screen is not already `"game"`

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

### Identity
For a logged-in user `myId === user.id` (account id = `gen_token(10)`); a guest
gets a random `uid()` in `localStorage.spender_myId`. The room player id (`pid`)
sent in the WS path IS `myId`, so a created game's `player1_id`/`host_id` equals
the creator's `myId` (= account id when logged in). `normalize_room` uppercases.

### Lobby UI (June 2026)
- **AI opponent picker** is a floating dropdown (`.ai-picker`, `position:absolute`
  in a `.ai-picker-wrap`), NOT inline — inline reveal shifted the whole page.
  One "Play vs AI ▾" toggle reveals A/B/C/C2/Z; picking one closes it.
- **Matchup display**: game cards show `player1_name vs player2_name` (AI shows as
  `AI (X)`); backend `list_user_games` returns both names + `you_are_p1`.
- **Cancel own open game**: open games where `g.host_id === myId` show Cancel
  (you only Join *others'* games). `list_open_games` returns `host_id`.
- **`.action-bar` has `min-height:62px`** so the turn badge row doesn't shrink
  when the contextual button (Take Gems / Buy) is absent.
- **Reserve = click a card then the gold coin** (bidirectional: gold-first arms
  `reserveArmed`, then click a card). No Reserve button. The gold token in the
  bank lights/pulses (`.reserve-ready`) when a card is selected and a slot is free.
- **Deck cards**: sized to match dealt cards (88px wide, min-height 120px). Level
  numeral (III/II/I) appears inside the deck outline above "DECK". No "Level I/II/III"
  panel titles — they were removed to reduce vertical space.
- **Move log**: clicking a buy/reserve row opens a card inspect modal (shows
  `<CardView />` + Close; no description text). Backend logs full card data (`id`,
  `cost`, `points`, `bonus`, `level`) on every buy/reserve so the frontend can
  reconstruct it. Clickable condition: `mv.card?.cost`.
- **Loading screen**: 250ms fast-path — AbortController fetch with 250ms timeout;
  if server responds in time → skip loading screen entirely; if not → show spinner
  + progress polling. `showLoading` state gates the spinner so a blank flash never
  appears on fast connections.

### Cancel / session-expiry gotcha (do not regress)
`POST /games/{id}/cancel` authorizes by a live session **OR** the host's
`player_id` (open games are public waiting rooms; `host_id` is already in
`/games`). This is deliberate: `get_user_by_session` rejects *expired* tokens, so
a session-only check made cancel fail silently after expiry (and the same expiry
quietly empties "Your Games"). The frontend `handleCancel` only clears the
`spender_roomId` resume pointer + reconnect token **after the server confirms the
delete** (`data.ok`); on failure it toasts the reason. Never clear local resume
state before confirming the delete.

---

## Design decisions (do not relitigate)

- **Noble path commitment rejected (but scarcity-gated)**: The AI must never *lock* onto a specific noble target. BUT per the user's strategy model, noble value is not flat — it scales **inversely with board efficiency**. When L2/L3 has efficient high-point cards to race, nobles are noise; when the board is poor in such cards, the only way to afford the inefficient L2/L3 cards is a wide pile of L1 bonuses, and breadth delivers nobles for free. So `noble_card` / `pos_noble` are modulated by `_board_scarcity` (high when few efficient targets exist) via the `noble_scarcity` / `pos_noble_scarcity` weights — this is contextual weighting, NOT target locking.

### Strategy model (informs AI feature design)
From a strong human player; drives the structural features (not just weights — self-play can only re-weight features that already exist, so these are encoded as new structure then tuned):
1. **Backward planning from efficient targets**: identify cost-effective high-point L2/L3 cards (points-per-gem: 5/8, 4/7, 3/6 are good deals), then value L1 bonuses by whether they advance *those specific targets* — not generic gem demand. (`_card_efficiency`, `bonus_target_pts`, `efficiency_weight`.)
2. **Scarcity → nobles** (see design note above): few efficient targets ⇒ go wide on L1 ⇒ nobles come along. (`_board_scarcity`, `noble_scarcity`, `pos_noble_scarcity`.)
3. **Contested-card value**: a card good for both you AND the opponent is worth more (acquisition + denial). (`_opp_reach`, `contested_weight` — boosts a point card's value by how close the opponent is to it.)
4. **Endgame denial**: reserve a card the opponent is one buy from (e.g. they have 4 white bonuses + 3 white tokens and a 7-white L3 is on the board). The rollout policy (`_fast_rollout_move`) now blocks too — gated by `block_urgency_gate` (default 1.1 = off; training lowers it) — so MCTS can finally *value* denial lines instead of never simulating them.
- **`_schedule_ai_turn` unconditional call is fine**: Its internal guards make it a no-op when conditions aren't met. Calling it after reconnect is intentional (unsticks games after socket drops).
- **No Co-Authored-By in commits**: User explicitly prohibited this.
- **`save_game` is synchronous** (SQLite ~1ms write), called outside ROOM_LOCK.
- **Thread pool for MCTS**: `loop.run_in_executor(None, ...)` — no dedicated executor needed; default thread pool is fine for single vs-AI game.
- **AI weights default to the original hand-tuned constants**: `DEFAULT_WEIGHTS` reproduces pre-training behaviour exactly. A `weights.json` is opt-in; do not commit one unless `train.py validate` shows it beats the defaults (>0.5) with real MCTS.
- **`train.py` is offline-only**: it imports game logic from `main` but must never start the server, open WebSockets, or write `users.db`. Self-play swaps the global `main.WEIGHTS` per mover — safe because training is single-threaded.
- **TD uses λ-traces, not TD(0)**: pure one-step bootstrapping diverged on this game's correlated states; don't "simplify" it back to TD(0).

---

## Known bugs / fixes applied this session

| Bug | Fix |
|-----|-----|
| TDZ `ReferenceError` in Firefox prod build | Moved derived game state (`game`, `me`, `myTurn`, etc.) before all `useEffect` hooks in Spender.jsx |
| AI blocking UI for 5s (human + AI moves batched) | Replaced sync `_post_turn` AI call with async `_schedule_ai_turn` task |
| "Game Not Started" when game was actually over | Split status check: `== "over"` → "game is over" before generic "not started" |
| Game stuck after socket drop during AI think | `_schedule_ai_turn` now called in both reconnect handlers |
| "Game Not Started" toast + waiting screen flash on reconnect | Race: WS1→WS2 reconnect, WS1 `finally` removed WS2's socket and deleted the room. Fixed with `r["sockets"].get(pid) is websocket` guard in `finally`. Also fixed `"joined"` handler to check `msg.room?.status` before setting screen (was always going to `"waiting"`). |
| Room-code (waiting) screen popped up over the end-game review | `created`/`joined`/`reconnected` sent any non-`"playing"` status to `"waiting"`; a finished game is `"over"`, so a reconnect after game end bounced the user off the review screen. Now an `inGame(status)` helper treats `"playing"` **and** `"over"` as the game screen; the winner/review UI lives there gated by the `reviewing` flag, so reconnects no longer kick out. |
| Reserve at 10 gems → 11 gems, no discard prompt, AI turn skipped, replay with 11 | Discard requirement was transient (one-shot `needs_discard` message field, **no** server guard); a later `room_update` reset the frontend modal and let the player move again. Fixed by making discard real game state like nobles: backend sets/clears `g["pending_discard_pid"]` on the three over-10 paths (take_gems/discard/reserve) and **rejects any non-`discard` move** while it's set (guard beside the `pending_noble_pid` one). Frontend `needsDiscard`/`needsNobleChoice` are now **derived** from `game.pending_discard_pid`/`game.pending_noble_pid` (not message fields), so they survive reconnects/saves and can't be cleared by a stray broadcast. |
| Review board missing claimed nobles | Noble row rendered only `game.nobles` (unclaimed), so nobles a player won vanished from the board. In review (`phase === "over"`) the row now also shows each player's claimed nobles, dimmed + labeled with the claimer (`★ name`), reconstructing the full original board. |
| Move log rows not clickable for buy/reserve | Backend only logged `{color, points}` — no `cost`/`id`, so frontend `mv.card?.id` was always null. Fixed: backend now logs full card dict on all 4 buy/reserve paths; frontend checks `mv.card?.cost`. |
| Move log border flash on new entry | `.log-entry:last-child{border-bottom:none}` rule meant adding a new entry at top changed the last-child, briefly revealing a border. Fixed: removed per-entry `border-bottom`; use sibling combinator `.log-entry+.log-entry{border-top:...}` so no element's border changes on prepend. |
| Hover on log row showed horizontal scrollbar | `margin:0 -4px` on hover exceeded container width. Fixed: removed negative margin; added `overflow-x:hidden` to `.move-log`. |
| Variant Z showed "AI (A)" in UI | Two-step failure: (1) `deploy-render.yml` didn't trigger on `az_model.npz` push, (2) accidental CoC import (`games.castles_of_crimson.main`) committed via stash/pop caused Render deploy to fail. Fixed: added `az_model.npz` to deploy-render.yml trigger paths; removed CoC import block (replaced with TODO comment). |

---

## Build + deploy steps (production)

**`docs/` is CI-owned — NEVER build or commit it by hand.** The
`.github/workflows/deploy-pages.yml` Action fires on every push touching
`games/spender/**`: it `rm -rf docs/`, rebuilds the webapp from source (with
`VITE_WS_URL=wss://splendid-nelz.onrender.com/ws` baked in), and commits/pushes
`deploy: update GitHub Pages from Vite build [skip ci]`. So a hand-built `docs/`
bundle is (a) overwritten by CI within ~1 min anyway, (b) the *sole cause* of
the recurring push-rejected → rebase → minified-bundle conflict loop, and (c) a
latent wrong-WS-URL bug (local builds don't set `VITE_WS_URL`).

**Frontend deploy = commit source only:**
```bash
# edit games/spender/Spender.jsx (do NOT npm run build, do NOT git add docs/)
git pull --rebase origin main      # if behind; always clean since you never touch docs/
git add games/spender/Spender.jsx
git commit -m "feat(ui): ..."
git push                           # CI rebuilds docs/ + deploys (~1-2 min)
```
The two deploy workflows: **deploy-pages.yml** (frontend → GitHub Pages `docs/`)
and **deploy-render.yml** (backend → Render). Backend (`main.py` etc.) also
deploys on push to main. `npm run build` locally is only for *verifying a build
compiles* — discard the `dist/`, never copy it into `docs/`.
