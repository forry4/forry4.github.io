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
- **Cancel must NOT use `cur.rowcount` (libsql 500 gotcha — DO NOT regress).** `delete_open_game`
  uses a **SELECT-then-DELETE** existence check, not `cursor.rowcount`: the driver-agnostic
  `core.db` wrapper doesn't expose `rowcount` on the libsql/**Turso** backend (it raised), so the
  rowcount form **500'd the cancel endpoint in production** (the frontend's `r.json()` then choked on
  the plain-text "Internal Server Error" body → "Could not cancel"). This is the same fix Spender's
  `delete_open_game` already had; CoC just hadn't gotten it. Any new libsql write that needs an
  affected-row count must use SELECT-then-DELETE/UPDATE, never `rowcount`.

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
- **No white frame (mounted-bare gotcha):** the shell early-returns `<CastlesOfCrimson/>` WITHOUT
  Spender's `baseCss`, and CoC's reset only targets `.coc *` descendants — never `body`. So the
  browser-default `body{margin:8px}` over an unstyled (white) body showed as a frame around the dark
  page. Fix: CoC's own `<style>` resets `html,body{margin:0;padding:0;background:#120c0d}` (scoped to
  while CoC is mounted, so no cross-screen effect). If you ever wrap CoC in `.app`/baseCss, this is
  moot — but don't drop the body reset while it's mounted bare.
- **Lobby mirrors Spender (Open Games / Active Games — NO "Your Games"):** three sections —
  (1) a localStorage **fallback "Active Games" card** (`coc_roomId`/`coc_token_*`) for guests (who
  have no `/games/mine`), guarded so it never renders when the game is already listed, while games
  load, or when the real Active Games section shows (no duplicate header); (2) **Open Games** (all
  open games; **your own** open lobby shows **Return + Cancel**, others show **Join**); (3) **Active
  Games** = `myGames.filter(status==="playing")` with matchup + Your Turn/Their Turn badge + Resume.
  The old "Your Games" section listed all your non-over games, so an open lobby appeared in BOTH it
  and Open Games — splitting open(→Open Games)/playing(→Active Games) makes a game live in exactly
  one place. Section CSS: `.coc-section-hd`/`.coc-muted`/`.coc-turn-badge`/`.coc-their-badge`/
  `.coc-spinner`; `timeAgo()` is a module-level helper. Backend already returns
  `you_are_p1`/`your_turn`/`created_at`/`updated_at`/`host_*`.
- **Bot's default board is board 1** (`oppBoard` default `"1"`, was `"2"`) so a fresh vs-bot game
  doesn't preselect a different board than the player's.

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
  (reorder within a tier, rating picker, manual add). Suggestions section: owner
  sees all (grouped by suggester); other logged-in users get their own up-to-10 editor;
  logged-out users see a "log in to suggest" prompt.
- **Two-column layout** (`.bk-columns` grid, capped 1160px, top-aligned): bookshelf left,
  suggestions in a 360px right column. Collapses to ONE stacked column below 920px (the
  `.bk-section` top-border separator is restored there). The `>` child combinator scopes
  the column overrides to the top-level `.bk-list`/`.bk-section` (NOT the nested `.bk-list`
  inside the suggestion editor).
- **Reorder UX (don't regress):** each edit row has **▲/▼ buttons** that move a book within
  its star tier (and a suggestion within its flat list), disabled at the tier/list ends —
  these exist because native HTML5 drag-and-drop **doesn't work on touch** and is fiddly on
  desktop. Drag is the secondary path: **only the ⠿ handle is `draggable`** (so the row's
  text inputs stay selectable — making the whole row draggable fought with editing), the row
  is the drop target and highlights (`.bk-dragover`). **`makeDrop` inserts AFTER the target
  when dragging downward** (source index < target), BEFORE when upward — otherwise a downward
  drop re-inserts before the target, which is where the source already was, so nothing
  visibly moved (the original asymmetric "drag up works, drag down doesn't" bug).
- **Open Library** search-to-add (`<BookSearch>`, reused by both editors): keyless,
  CORS-enabled, queried client-side; picking a result auto-fills title/author/cover.
  **The fetch is capped at 12s** (a guard timer aborts the AbortController) — Open Library is
  flaky (observed 7-10s connects) and has no timeout of its own, so a hung request would
  otherwise stick on "Searching…" forever. A real timeout/network failure shows a recoverable
  message; a supersede-abort (newer keystroke) is distinguished so it doesn't flash an error.
- **Covers are cached as inline `data:` URIs** (`inlineCover`, applied to ranking + suggestions
  on **save**): `covers.openlibrary.org` serves through **two 302 redirects** (→ archive.org)
  with only a **3-hour** cache, so covers re-fetch slowly every few hours. CORS is open
  (`ACAO *`), so on save the browser fetches each remote cover once, **downscales** it
  (128×192, JPEG q0.82) via canvas, and stores a self-contained data URI in `cover_url` — it
  then renders instantly from the list payload with no external request. Any fetch/CORS/decode
  failure falls back to keeping the original URL (graceful). **Existing books need one
  Edit→Save to backfill**; new adds bake in on the next save. (Inline data URIs are ideal for a
  shelf of dozens; at hundreds, a cacheable backend image endpoint would scale better.)

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

## WWSD ("What Would Steve Do") — variant-S advisor for a FRIEND's external Splendor site

`wwsd/` (top-level package) is a standalone tool that recommends a move for a Splendor position taken
from a **friend's external site** — mattle's "spendee" (`spendee.mattle.online`, a **Meteor** app),
NOT the user's own Spender game. A browser **bookmarklet** on the friend's page reads the live game
state out of the Meteor client cache (`Meteor.connection._mongo_livedata_collections['games'].find()
.fetch()` — a request-free LOCAL read of already-synced Minimongo), POSTs it to a public endpoint,
and renders variant **S**'s move (+ position eval) in an injected overlay panel.

### Deployed as a SECOND Render service (process isolation is the whole point)
- Its own Render web service **`wwsd`** → `https://wwsd.onrender.com`, a **separate process** from
  the game backend `spender-backend`. **Why separate:** `wwsd.analyze` rewrites the shared
  `games.spender.ai.az.engine` deck globals (`COST/PTS/BONUS/NOBLE_REQ/WIN_POINTS`) to the friend's
  deck; the live game backend's own AI (`_az/_h2/_h3_choose_move`) reads those SAME globals inside a
  thread-pool compute that does NOT hold `ROOM_LOCK`, so sharing a process would corrupt live game
  moves. The override runs in `analyze.prepare()` (called at `app.py` startup; lazy in `analyze()`),
  **never at import** — a stray `import wwsd` can't corrupt anything.
- Defined in `render.yaml` as a 2nd `web` service: SAME repo/`Dockerfile` (`COPY . /app` ships
  `wwsd/`), only the **dockerCommand** differs (`uvicorn wwsd.app:app`). Env: `WWSD_SECRET`
  (`sync:false`, set in the dashboard — NOT in the repo), `WWSD_ORIGIN`, `WWSD_TIME`,
  `SPENDER_AZ_MODEL=none` (skip the numpy AZ load — unused here). Created manually in the Render
  dashboard (or via blueprint sync).
- **Variant S is already on `main`** (`vsearch`/`v_state`/`mcts` `leaf_state`/`heuristic3`/
  `valuation3`/`engine`), so wwsd just `import`s the az modules — **no vendoring**. Built in a
  dedicated `forrestm_projects-wwsd` worktree off `origin/main`, pushed to `main` (auto-deploys).

### The deck (`wwsd/wwsd_defs.json`)
The friend's 90-card + 10-noble deck, **extracted from THEIR site's client** (their Meteor module
`games/spendee/imports/api/utils/constants.js`, read via the browser console — no server request).
It's the canonical Splendor deck in the SAME colour order as ours (identity matches **89/90**; our
Spender deck deviates on one card). `analyze.override_engine()` rebuilds the engine's card/noble
tables from THEIRS so S analyses their EXACT game (their card index = our engine card id; 0-39 L1 /
40-69 L2 / 70-89 L3). Validated against a finished-game dump (90-card partition + token conservation
+ noble satisfaction).

### Files + API
- `wwsd/analyze.py` — `analyze(doc, time_limit)` (a dumped `{games:[...]}` doc → engine State →
  variant S → structured dict); `to_state`, `override_engine`/`prepare`, and `_search_with_eval`
  (runs the search, then reads the root value + per-edge Q **without** modifying `vsearch`).
  - **Win-points auto-detect (Classic 15 / Long 21).** `_detect_target(game, data)` reads
    `settings.targetScore` (spendee stores it as a STRING, e.g. `"15"`/`"21"`; falls back to
    `data.targetScore`, then 15) and `analyze` threads it BOTH ways: `set_target(t)` aligns the
    engine GLOBAL `E.WIN_POINTS` (non-S leaves + getattr fallbacks) AND `to_state(data, target)`
    sets the **per-state `s.win_points`** — which is authoritative, since the engine win check
    (`_finish_turn`) and the whole S stack (`v_state._points_term` convex zone, `heuristic3`,
    `valuation3`) read `s.win_points` per-state. **`to_state` MUST set it** or the search
    AttributeErrors mid-rollout (the State is built via `__new__`, so every slot is set by hand).
    21-pt games are analysed correctly (right victory zone), just with the 15-pt `turns_table`
    horizon (best-effort, see Caveats).
- `wwsd/app.py` — FastAPI: `POST /move` (gated by header `X-WWSD-Secret` via `hmac.compare_digest`;
  small self-contained per-IP sliding-window rate limit; CORS pinned to `WWSD_ORIGIN`; honours a
  `?t=<seconds>` think-time override **clamped 1-60s** to stay under Cloudflare's ~100s ceiling),
  `GET /health`, `GET /` (the bookmarklet generator/tester page).
- `wwsd/bookmarklet.py` — the overlay bookmarklet (config vars `SECS`/`SVC`/`KEY` hoisted to the
  FRONT for easy editing) + `build_bookmarklet()` + the `GET /` page (builds the bookmarklet
  CLIENT-side, so the secret never reaches the server).
- `wwsd/tests/test_wwsd.py` — deck-rebuild correctness, `analyze` on real dumps, secret/json guards,
  `?t=` clamp, bookmarklet generation, eval fields (`python -m pytest wwsd/tests -q`).
- **`analyze` response**: `recommendation` + `rec_eval`; `alternatives[]` (pct + text + `eval`);
  `eval` = S's POST-search **position** value (root `sum(W)/sum(N)`, [-1,1] from the side to move);
  `sims`, `budget`, `turn_name`, `target`. Per-move evals are the MCTS **edge Q** (searched → noisy
  at low sims; higher `SECS` steadies them). A static-`v_state`-after-each-move alternative was
  discussed (stable but shallow + needs refill-averaging for buy/reserve) — not implemented.

### Caveats
Render free tier: ~30-50s cold start; slow shared CPU → far FEWER sims than local (~hundreds at a few
seconds vs ~4,600 on a dev box). **Sims, not seconds, is the strength currency** — bump `WWSD_TIME`
or the bookmarklet's `SECS` (`?t=`) to climb toward the local strength (capped by `vsearch`'s
`SERVE_MAX_SIMS`). For full local strength without the wait, a tunnel (Tailscale Funnel / Cloudflare)
or a cheap dedicated-core VPS beats the free tier. `turns_table.json` (H3-vs-H2-measured, 15-pt) feeds
S's leaf eval → 15-pt games exact, 21-pt approximate.

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
- **`core/auth.py`** — `gen_token` (**CSPRNG via `secrets`** — see Security hardening),
  `hash_password`/`verify_password` (PBKDF2 + legacy), `create_user`, `authenticate_user`,
  `get_user_by_session`, `validate_credentials` (registration input rules), the SITE_OWNER/admin
  identity helpers (`site_owner_name`, `grant_admin`, `is_admin_id`, `is_site_owner`), and the
  reconnect-token helpers (`create`/`validate`/`mark_used` + `cleanup_reconnect_tokens`/
  `maybe_cleanup_reconnect_tokens`). Imports `get_db_conn` from `core.db`.
- **`core/ratelimit.py`** — `SlidingWindowLimiter` (in-memory per-process abuse throttle; used by the
  auth routes). **`core/config.py`** — `cors_allowed_origins()` (env-driven CORS allowlist, no
  web-framework deps so both `app.py` and the CoC sub-app share it).
- **Auth correctness (hard-won, June 2026 — DO NOT regress):**
  - **`is_admin` is computed the SAME way on every path** — `is_admin_id(conn, id)` (a plain
    `SELECT 1 FROM admins WHERE user_id=?`) OR a live `SITE_OWNER` username match. `get_user_by_session`
    previously used a **correlated subquery** `(SELECT 1 FROM admins WHERE user_id=users.id)` that read
    **NULL on the prod libsql driver** (works on sqlite, so invisible in tests): a refreshed session
    reported the owner as non-admin while login (via `is_admin_id`) said admin → the admin UI vanished
    on every reload until re-login. **Never use a correlated subquery here; reuse `is_admin_id`.**
  - **Usernames are unique, CASE-INSENSITIVELY.** `users.name` has **no UNIQUE column constraint**, so
    `create_user` checks `WHERE name=? COLLATE NOCASE` before inserting (the old `except
    sqlite3.IntegrityError` guard never fired — no constraint to violate, and libsql wouldn't raise that
    type anyway — so duplicate "Forrestm" rows slipped in). `init_core_schema` builds a NOCASE unique
    index **`idx_users_name_ci`** (dropping the earlier case-sensitive `idx_users_name`), tolerant of
    pre-existing dups so boot never fails. `authenticate_user` looks up NOCASE too, so login matches
    registration regardless of case.
- **Security hardening (June 2026 — DO NOT regress):**
  - **Tokens use a CSPRNG.** `gen_token` uses `secrets.choice`, NOT `random.choices` — it mints
    session tokens, account ids, reconnect tokens, AND password salts, and `random`'s Mersenne Twister
    is reconstructable from observed output (predict-the-next-token). Never revert it to `random`.
  - **Registration input validation.** `validate_credentials(name, password)` returns a human message
    or `None`: username **1–12 chars, `[A-Za-z0-9]` only**; password **1–16 chars**. Enforced at
    `/auth/register` ONLY — login stays permissive so pre-existing accounts still sign in (with a guard:
    reject name>64 / password>128 *unhashed*, a PBKDF2-on-huge-input DoS guard). Frontend input
    `maxLength` mirrors it (register 12/16; login 64/128, so legacy passwords stay typeable).
  - **Auth rate limiting** (`core/ratelimit.py` — in-memory, per-process; OK because the Procfile runs
    a SINGLE uvicorn process). `/auth/login`: 20/5min per IP + 10 **failures**/15min per username (the
    per-username streak resets on success, so multi-device logins aren't locked out). `/auth/register`:
    10/hour per IP. Client IP from `X-Forwarded-For` first hop (Render proxy), socket peer otherwise.
    Over-limit returns `{ok:False, message}` at **HTTP 200** (NOT 429) so the existing frontend error UI
    shows it. Residual: XFF is client-spoofable to rotate the per-IP key — the per-username failure
    limiter is the real brute-force defense.
  - **Session token in the `Authorization: Bearer` header, not the URL.** `bearer_token` (FastAPI
    dependency in `games/spender/main.py`) reads `Authorization: Bearer <tok>` with a `?token=` query
    **fallback** (so cached clients don't break mid-deploy). Applied to every session-token route in
    Spender, Books (injected into `setup_books` as `token_resolver` so books still imports no game), and
    CoC (a LOCAL `_bearer_token` copy — keeps CoC independent of Spender). The WS path is unchanged: it
    uses room-meta / reconnect tokens in the message BODY, never the URL. Frontends send the header
    (Spender 3 fetches, Books 4, CoC 2). Goal: keep the secret out of access/proxy logs + browser history.
  - **Reconnect-token cleanup.** `cleanup_reconnect_tokens()` deletes used/expired rows;
    `maybe_cleanup_reconnect_tokens()` throttles to ≤1/h/process and runs opportunistically inside
    `create_reconnect_token` (short-lived single-use tokens were accumulating forever).
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
- **Tests**: `core/tests/test_db_auth.py` (wrapper + password + admin + `init_core_schema` +
  `gen_token`/`validate_credentials`/reconnect-token cleanup) and `core/tests/test_ratelimit.py`
  (sliding-window limiter, `now` injected so it's deterministic), in-memory sqlite. CI runs
  `core/tests/` first; Render watches `core/**/*.py`.
- **Frontend** (partial, by design): the Vite build was relocated to a neutral top-level
  `webapp/` (no longer under `games/spender/`). The deeper **stateful shell/game split of
  `Spender.jsx` was deliberately SKIPPED** — it's a re-architecture of shared `screen` state
  + the mount-time WS auto-resume on a test-free, auto-deploying, TDZ-prone component, for
  purity only (the real coupling — CoC/Books reaching into Spender — was the backend, already
  fixed). Don't attempt it without a strong reason + local playtest gate.
- **Not yet done**: DRYing the duplicated room-server scaffolding (`ROOMS`/`ROOM_LOCK`/
  `broadcast_room`/`save_game`/`mk_room_state`/`_schedule_*_turn` are copy-mirrored in Spender
  and CoC `main.py`) into a shared `core` helper — Phase 3, defer until game #3.

### Composition root — top-level `app.py` (Phase 2, done)
The FastAPI **`app` and the feature wiring no longer live in a game module.** The
top-level **`app.py`** is the composition root: it creates `app = FastAPI(...)`,
applies CORS + security-headers middleware (see below), `include_router`s Spender's routes,
`setup_books(...)`, and mounts Castles of Crimson at `/coc` (same defensive try/except as before).
- `games/spender/main.py` now exposes **`router = APIRouter()`** (all its routes use
  `@router.…`, including the single `/ws/{room}/{player}` websocket) instead of owning
  the app. It still runs `init_db()` at import.
- **Layering**: `core/` (bottom) → features (`games.spender`, `games.castles_of_crimson`,
  `books`) → `app.py` (top). The composition root depends on features; features don't
  depend on it. `core` depends on neither.
- **CORS + security headers** (`app.py` + `core/config.py`): CORS is **pinned** to
  `cors_allowed_origins()` — the site's own frontends are ALWAYS allowed: `https://forry4.github.io`
  (GitHub Pages USER site served at the root `https://forry4.github.io/`, so the Vite `base` is `/`),
  the **Cloudflare staging mirror** `https://webprojectsstaging.forry4.workers.dev` (it reuses this same
  backend over HTTP), plus localhost dev. **`CORS_ALLOWED_ORIGINS`** (comma-separated) ADDS extra origins
  (e.g. a future custom domain) — it **merges with, no longer replaces, the defaults** (do not regress:
  the old replace-semantics meant setting the env var silently locked out the staging mirror, so its
  browser fetches got no `Access-Control-Allow-Origin` → the loading screen hung at 90% on `/games`;
  staging is frontend-only on the prod backend, so this is the ONLY way it can call the API). Methods
  GET/POST/PUT/OPTIONS, headers Authorization/Content-Type, **no credentials** (token auth, not cookies
  — so `*`-origin was never a credential leak, but pinning is hygiene). `SecurityHeadersMiddleware`
  (pure-ASGI, in `app.py`) adds `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`,
  `Referrer-Policy`, `Strict-Transport-Security` (HSTS), `Permissions-Policy` to EVERY response —
  **including the mounted `/coc` sub-app**, because the parent ASGI middleware threads `send` down into
  the mount. CoC's own CORS is aligned to the same list (the parent overrides it when mounted, but it
  matters if CoC runs standalone). **No CSP on the API** — it serves JSON (CSP guards HTML, which is
  GitHub Pages' job) and a strict policy would break FastAPI's `/docs` Swagger UI; a frontend `<meta>`
  CSP is a deferred follow-up.
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
- **`ai_variant` is persisted** in the saved room state and restored on load. Without it, a vs-AI game
  reconnected after a redeploy (which wipes in-memory `ROOMS`) lost the room-level variant: the move
  scheduler fell back to variant **"A"** (wrong bot) and `mk_room_state` dropped `ai_variant` +
  `ai_card_values` (so the admin value-overlay button disappeared, working only on a fresh game).
  `load_game_to_memory` has a **back-compat fallback** recovering the variant from the AI player's
  `"AI (X)"` display name for games saved before the field was persisted.

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

### Variant H2 (`ai/az/heuristic2.py` + `valuation2.py`) — the `take_value` heuristic (DEPLOYED)
A from-scratch greedy heuristic, **served as website variant "H2"**, separate from variant H.
**Full write-up: `games/spender/ai/az/H2.md` — read it before touching H2.**
- **Model:** `take_value = (engine_value + point_value) / (1 + total_cost)`. cost = `W_TEMPO·tempo +
  W_GEM·gem + W_GOLD·gold` (all post-bonus); points are game-STAGE-scaled (engine early → points late,
  + `ENG_DECAY` fades engine as cards accumulate); `engine_value` includes a forward-looking
  undealt-deck-demand term. 1-ply greedy, same serving path as H.
- **Deployed config (committed on main; beats H ~0.69 greedy):** `heuristic2` W_TEMPO 0.5 / W_GEM 0.2 /
  W_GOLD 0.4 / NOBLE_SCALE 3.0 / STAGE_K 8 / STAGE_FLOOR 0.25 / ENG_DECAY 0.3; `valuation2` ENG_DECK_W 3.5
  / ENG_DIV 8 / ENG_FLOOR 0.2 / NOBLE_CLOSE_FLOOR 0.2 / GOLD_BANK_CAP 2. The big levers were ENG_DECK_W↑
  + NOBLE_SCALE↑ (~+0.06); ENG_DECAY +0.011; cost weights saturated.
- **Tooling (offline; restore modules after):** `h2_tune.py` (CRN A/B; `--opp H` vs heuristic H, `--opp h2`
  = self-gate vs the CURRENT committed H2 — far more sensitive once H2 ≫ H) and `h2_autotune.py`
  (autonomous coordinate-descent campaign, NO human input: screen → validate on disjoint holdout vs self
  AND vs H → adopt → re-screen; prints a vetted config, never edits source).
- **Tuning methodology — DO NOT regress:** CRN (same seeds across configs) is for the *comparison*; the
  final estimate MUST come from FRESH **disjoint** holdout seeds (tuning-set optimism shrank gains ~⅔).
  **Seed-spacing bug:** `h2_tune` uses deck seed `base_seed+i` over N games, so two base seeds must be
  spaced **≥ N apart** to be independent (seeds 1–3 apart share ~1598/1600 games → fake "agreement").
  Self-gate tuning needs a **self-exploit guard**: adopt only if the change ALSO doesn't regress vs H — a
  change can beat *this* config via rock-paper-scissors yet be weaker vs the external yardstick.
- **Tested & REJECTED — parked default-OFF behind flags in `heuristic2.py` (do not relitigate):**
  `USE_TAKE2` (take-2-of-a-color): naive form made bad moves (−0.03), reserved-only form ~neutral (fires
  0.27% — winning reserves are gold-necessary, the opposite of take-2's full-bank need). `W_SHORTFALL`
  (bank-aware gold shortfall in cost): cuts a 14.9%→11.6% "stall on an un-completable card" rate, +0.006
  lean but sub-significant. `NOBLE_SCARCITY` (scarcity-gated nobles): INERT — `board_scarcity`≈0 on 98%
  of boards (real Splendor boards almost always offer an efficient L2/L3 deal). `USE_OPP_SNIPE` (pivot off
  a card the opponent will buy): wash/negative — contention is a documented 1-ply greedy wash. **All four
  are good NET-feature candidates, not greedy levers** (see FEATURES_V4.md + `.claude-plans` H2 feature doc).
- **On-card AI-values overlay is now ADMIN-ONLY (default OFF):** the per-card T/E/P/C box (H2) / single
  value (H) only renders for `authUser.is_admin`, behind a "Show/Hide AI values" toggle in the game
  action bar (AI games only; persisted in `localStorage.spender_show_ai_vals`). Frontend gating in
  `Spender.jsx` — the data is still in the WS payload (non-sensitive AI valuations), just not shown to
  non-admins; a backend per-recipient gate was deemed not worth it for this non-sensitive overlay.

### Variant H3 (`ai/az/heuristic3.py` + `valuation3.py`) — turns-remaining engine horizon (DEPLOYED)
A sandbox fork of H2, **served as website variant "H3"** (a playable opponent + a per-card potential overlay,
wired in `main.py`). Same 1-ply greedy `choose_action`/`components` contract; it reframes H2's value model around
a **potential vs take** distinction and a **turns-remaining horizon**. Permanent invariants live in
`games/spender/tests/test_h3_valuation.py` (9 tests) — keep them green.

**Model** (`components`): `take = (engine_term + point) / (1 + cost)`
- `cost = W_TEMPO·tempo + W_GEM·gem + W_GOLD·gold` (post-bonus; one currency used everywhere).
- `point = PTS + NOBLE_SCALE·noble_progress + noble_completion` — **NOT stage-scaled** (full value always; H2's
  point-staging, `ENG_DECAY`, and the per-card tempo-discount were all REMOVED).
- `engine_term = W_ENGINE · max(0, turns_remaining − tempo) · engine_value(ci)` — engine value × the turns it
  will COMPOUND. A card you can't finish before the game ends contributes ~0 engine. This horizon replaces
  stage/eng_decay (`W_ENGINE` is the engine-vs-points balance knob).
- `engine_value(ci) = Σ over OTHER cards cj still needing ci's bonus color of _delta_take(cj)` (+ reserved
  premium + deck-demand term); `_delta_take(cj) = potential(cj) · [1/(1+cost') − 1/(1+cost)]` — the take-value
  uplift ci's +1 gives cj; the `1/(1+cost)` convexity auto-weights a near-affordable discount (2→1) over a far
  one (6→5), no extra knob.
- `potential(cj) = (PTS + POT_ENGINE_W·eng_base) · (1 + POT_REACH_W·reachability)` — worth as a DESTINATION,
  distinct from take_value (a far high-point card has high potential but ~0 take, which is exactly why its
  *builders* earn engine value while chasing it now is bad). `eng_base` = the legacy level-0 engine value (cached).
- `turns_remaining`: estimated future main-turns from `turns_table.json` (a MEASURED `(cards, points, gems) →
  avg turns-left` table from H3-vs-H2 games; rebuild with `h3_measure_turns.py`), **min over both players** (the
  leader sets the clock). NN-filled, gems weighted 0.25× a card. Absent file → flat fallback.

**Noble time-gate** (`NOBLE_TIME_GATE=True`, `NOBLE_TURN_W=1.0`) — the one structural fix that paid: a 0-pt card
advancing a far/late noble used to contribute a flat ~0.5 (no time awareness). Now `noble_progress` is smoothly
discounted by completability — `× eff/(eff + NOBLE_TURN_W·deficit)`, `eff = max(0, turns_remaining − tempo(ci))`
(turns left AFTER acquiring the card), `deficit` = bonuses still needed. Smooth fade toward 0, **no hard cliff**
(turns_remaining is an estimate). **~+0.02 vs H2** (the biggest recent greedy gain; `NOBLE_TURN_W` peaks at 1.0).

**Deferred idea — time-gate the raw card POINTS too (not done; noted on request):** `noble_progress` and the
engine term are both gated by buy-in-time feasibility (`max(0, T − tempo)`), but the raw `E.PTS[ci]` term in
`components` is NOT — so late-game `_choose_take` can still collect gems toward a high-point card it can't finish
before the game ends (the same blind spot the noble gate fixed, applied to a card's own points). The fix would be a
**clamped step** `min(1, max(0, (T − tempo)/M))` on `E.PTS[ci]` — distinct from the engine's *linear* ramp (points
are a ONE-TIME grab, so extra spare turns don't multiply them) and from the noble *deficit* fade. NOT double-counting
the `(1+cost)` denominator (that's time-blind). Likely a NARROW win at best — the engine term already zeroes an
unfinishable card's engine contribution, so only the points leak remains. A/B it behind a `POINT_TIME_GATE` flag if
revisited; expect it could be a wash (like the TURNS_FLOOR test was).

**Baked config**: `W_TEMPO=0.1, W_GEM=0.3, W_GOLD=0.4, NOBLE_SCALE=5.0, NOBLE_CLOSE_FLOOR=0.3, POT_ENGINE_W=0.5,
W_ENGINE=0.15, NOBLE_TIME_GATE on / NOBLE_TURN_W=1.0, POT_REACH_W=0 (OFF), BUILD_FLOOR_W=0 (OFF)`. Strength: **~0.54
vs H2, ~0.76 vs H** greedy (edges the old stage model; beats the external yardstick H by more than H2 does). To
recover exact-H2 for A/B: `USE_POTENTIAL_ENGINE=False` + `W_GEM=0.2`.

**Noble-weight campaign (June 2026) — `NOBLE_SCALE` 3.0→5.0 is the only gain, and it's small.** A broad campaign
(curves on noble closeness/engine distance; game-stage scaling of points/nobles/cost-weights; victory-proximity;
quadratic/exponent engine-distance reshapes) was run against the **H2 racer family** — `H2R` (rusher, `NOBLE_SCALE
×0.4`) and `H2N` (noble-heavy, `×2.0`), ported from `feat/az-v4-features` as `_AggrH2` wrappers in `h3_vs_h2.py`
(kept as **test infra**; H2N dropped from the metric as too weak/circular). Verdict on a **10-seed-base CRN
confirm** (the single-seed batches inflated badly): `NOBLE_SCALE=5.0` = **+0.0073 avg(H2,H2R)** (won 7–8/10 seeds
vs each racer), neutral vs H — shipped. **Everything else washed or hurt** on confirm: STAGE-scaling was robustly
**−0.02**; `NOBLE_CLOSE_EXP` (convex closeness), `VICT_PROX_W`, all engine-distance curves ≤ flat. This re-confirms
the **static greedy eval is saturated** — re-weighting can't beat ~+1pp; the remaining lever is search/net (see the
recursion/depth+1 direction noted for "at some point"). Campaign scratch (`h3_camp.py`/`h3_final.py`/`camp_*.out`)
was removed; the H2N/H2R wrappers + `h3_autotune` plumbing stay.

**Tuning findings — DO NOT relitigate** (validated on disjoint seeds, N≥3000):
- **The engine balance is a flat RIDGE.** `W_ENGINE` and `POT_ENGINE_W` both scale the engine term (pe sits
  inside potential → engine_value, which W_ENGINE multiplies), so they trade off — tune W_ENGINE *jointly* with
  pe, never in isolation. Optimal band `W_ENGINE 0.15–0.20 × pe 0.25–0.5`, all ~0.54; outside (we≤0.1 / ≥0.3,
  or we=0.2+pe=0.5) is worse. vs-H2 is **flat ~0.54** across the band — no sharp peak.
- **Reachability (`POT_REACH_W`) doesn't pay** in greedy — win-rate wash-to-negative across the full `we×pe×pr`
  grid (≥0.4 clearly hurts). The reworked formula (cost-reduction-weighted, affordable-gated, value-per-cost
  builders) is *correct and unit-tested*, but it's a NET-feature candidate, not a greedy lever. Left OFF.
- **`BUILD_FLOOR_W` hurts** (over-invests in builders for far targets it never finishes). OFF.
- **Sharpening the take denominator (`take = num/(C0+cost)`, C0<1) is the strongest REJECT measured.** Tested
  C0 = 0.7 / 0.5 / 0.3 to "make cost matter more" (motivated by an expensive L2 1-pointer edging a cheaper L1
  on turn 1): cratered **−0.025 / −0.060 / −0.122 avg(H2,H2R), 0/10 seeds, monotonic**, also negative vs H. The
  `+1` constant is **load-bearing** — making cost bite harder makes H3 too cheap-greedy and it under-builds toward
  point/engine cards. The take *numerator* should win those ties; a near-tie favoring the point-bearing card is
  correct, not a bug. (Confirms again: cost-side reshapes don't pay; the static greedy eval is saturated.)
- **`W_GEM=0.3` (vs H2's 0.2) is coupled to the engine** — neutral with the engine off; only helps with the
  turns-remaining engine on.
- **Greedy H3-vs-H2 saturates ~0.54** regardless of potential/reachability weights — same ceiling as H2's
  weight-tuning. Remaining lever is search/net. The exception that paid was the noble time-gate (structure, not
  a re-weight) — look for structural fixes, not more weight-tuning.

**Tooling** (offline; all parallel via multiprocessing — pure-Python games, BLAS is NOT a factor): `h3_vs_h2.py`
(H3-vs-H/H2 arena, `--set`/`--opp`), `h3_eval.py` (named-config A/B), `h3_autotune.py` (coordinate descent,
screen→disjoint-holdout), `h3_measure_turns.py` (rebuild `turns_table.json`), `h3_sanity.py` (interactive value
probes), `h3_stage_sweep.py`. **Methodology: a UNIQUE output file per run** (two runs writing the same `>` file
interleave and corrupt — happened once); confirm gains on DISJOINT seeds; re-measure `turns_table.json` after big
model changes (it's mildly self-referential). `h3_*.out`/`h3_best.json` are gitignored scratch.
- **Serving + overlay specifics:** `_h3_choose_move` (1-ply `choose_action`) + `_h3_card_values` are wired
  into `_ai_variant_valid` + `mk_room_state` + the move scheduler (same path as H/H2; `mk_room_state`
  includes `ai_card_values` only for in-progress H/H2/H3 games). The admin overlay shows H2's T/E/P/C
  **plus a 5th `Po` (potential)** — gated in `Spender.jsx` by `aiValue.pot != null`, leaving H2's 4-value
  box unchanged. (Aside: an `az_vs_h2.py` arena measured H2/H3 **beating the deployed AZ net
  `az_model.npz` ~0.75 @ 300 sims** — the greedy heuristics currently out-play variant Z.)

### Variant S (`ai/az/v_state.py` + `vsearch.py`) — V(state) whole-position eval + determinized PUCT (STRONGEST; DEPLOYED June 2026)
The first variant to pair the strong H-family judgment with **real search** (the documented #1 remaining
lever). **Strongest variant yet:** panel avg **0.758** — vs greedy **H3 0.733**, H2 0.729, H2N 0.808, H2R
0.762 (N=120, sims=160) — beating greedy H3, which itself beats the deployed AZ net Z ~0.75. Served as
website variant **"S"**.
- **`v_state.py` — the position evaluator (the new piece).** The H-family scores ACTIONS (`take_value` of
  acquiring a card); `v_state.value(s, seat)` scores a whole POSITION:
  `V = tanh((STAND(me) − STAND(opp)) / SCALE)` in [−1,1]. `STAND(seat)` = weighted sum of five terms, each
  REUSING H3 primitives: realized points (+ convex near-win kicker); **engine_stock** (held bonuses' forward
  value, deck-demand-weighted × turns-remaining horizon); **progress** (top-k `take_value` of reachable
  targets); **noble_stand** (closest completable noble, time-gated); **econ** (useful gold − hoard penalty,
  aimed at the AZ-net over-reserve weakness). Scoring the opponent with the IDENTICAL function and
  subtracting makes **denial fall out of the search backup for free** (no `contested_weight` knob — the
  structural cure for the self-play denial blind spot). Opp blind reserves are an expected CONSTANT in static
  V (mirrors `features.encode`), concretized by determinization inside search. Public `value`/`components`
  build the Valuation; internal helpers read `val.s` (one source of truth).
- **`vsearch.py` — determinized PUCT, V leaf, H3 policy prior.** Reuses `az/mcts.Search` UNCHANGED for the
  hard parts (ISMCTS determinization of hidden info; correct non-alternating-turn backups) via a minimal
  `leaf_state=True` mode (hands the leaf State to the evaluator instead of `features.encode`). Leaf VALUE =
  `v_state.value_with` (NOT a rollout). Policy PRIOR = softmax over H3 per-action scores (buys/reserves by
  `take_value`, takes by the NORMALIZED need-vector) + an **H3-greedy-pick anchor** (`H3_PICK_W`). Serving
  uses a wall-clock budget (`SERVE_TIME=4.5s`); offline A/B uses fixed `sims`.
- **Serving:** `_s_choose_move` in `main.py` (mirrors `_h3_choose_move`/`_az_choose_move`) wired into
  `_ai_variant_valid` ("S") + `_schedule_ai_turn` + `mk_room_state` (reuses the H3 `_h3_card_values` overlay);
  `Spender.jsx` lobby picker includes "S".
- **DO NOT relitigate (findings):**
  - **Static value-leaf ≫ rollout leaf** (`h3l_probe.py`: static 0.58 panel vs rollout **0.28**, ~10× slower).
    Confirms "value-leaf beats rollout" — V is the judge, never a playout.
  - **Single-sample determinization is noisy** (the crude `h3_lookahead.py` 1-ply); PUCT AVERAGING over many
    determinized sims is the fix.
  - **The policy prior MUST be scale-normalized.** First cut used the raw need-vector (~5–45) for takes vs
    `take_value` (~1–3) for buys → softmax put ~all mass on taking gems → the bot bought nothing, lost
    **0/16**. Normalizing the take score + the H3-pick anchor → 0.69+ instantly (same class as the AZ
    buy-nothing collapse).
  - **Search is the lever, empirically:** greedy H3 ≈0.5 vs panel → V+search **0.73**. The static eval alone
    saturates ~0.65 (the plateau); the gain is from SEARCH.
- **Hardening — DO NOT regress (`valuation3`):** `Valuation` captures a `(ply, phase, turn)` fingerprint at
  construction; a single inlined `assert` in `estimated_turns_remaining` (the one method every scoring path
  hits; `-O`-strippable) catches a Valuation reused after its state mutated — the lookahead/distillation
  footgun `val = Valuation(s); apply(s, a); val.<query>()` (silently mixes post-apply live state with
  pre-apply caches). The vestigial `s` param was DROPPED from `heuristic3.components`/`take_value` + all
  callers (never used; the state is `val.s`); `v_state` helpers read `val.s`.
- **Perf (behavior-preserving; profile: ~84% of search time is the V leaf):** `_cost_scalar` rewritten as one
  inlined loop (no `b(c)` closure / genexprs) = **2.75× less work**; `_delta_take` memoized per-Valuation
  (`_dt_cache`, ~**78% hit**) = 4.5× fewer `_cost_scalar` calls; `heuristic3.choose_action` accepts an
  optional `val=` and the H3-prior anchor in `vsearch` passes the leaf's Valuation (no 2nd build — 2/sim →
  1/sim — and the anchor's `take_value` sweep hits the warm cache: `_cost_scalar` 298K → 200K, a modest
  ~5–7% on top). Net ~**2–2.6× more sims/move** in timed serving; offline fixed-sims play is BYTE-IDENTICAL
  (exact-value tests in `test_h3_valuation.py` + `test_vsearch.py` gate it). The fingerprint catches
  turn-ending AND phase-transition mutations. **Profiling note:** measure throughput on a QUIET box —
  `vsearch_profile.py`'s clean sims/s is corrupted by a busy autotuner; the contention-independent truth is
  the cProfile call counts (builds/sim, `_cost_scalar` calls).
- **Tooling** (offline, parallel): `vsearch_camp.py` (panel A/B, CRN, Wilson CIs), `vsearch_autotune.py`
  (coordinate descent, **MAXIMIN objective over {H3,H2,H2N,H2R}** — maximize the WORST matchup, mean only as a
  tie-break (`MEAN_EPS`), with larger screen/holdout N since the min is a noisier statistic. Switched FROM
  panel-mean after the mean run found ZERO adoptions on the disjoint holdout — i.e. the hand-set V weights are
  already near-optimal, confirming "weight-tuning saturates"; vs-H3 (~0.635 @ sims=120) is the lone weakness
  maximin targets), `v_state_eval.py` (sign(V) win-prediction discrimination vs the ~0.65 plateau),
  `vsearch_profile.py` (clean wall-clock + cProfile), `h3l_probe.py` (the static-vs-rollout probe). Tests:
  `games/spender/tests/test_vsearch.py`.
- **THREE-WAY diagnostic (RUN, June 2026) → Path C favored.** `v_state_eval.py --teacher S` plays S-vs-S
  (search-driven) and at every PLAY snapshot records {static V, search-backed root value `sum(W)/sum(N)`,
  eventual outcome} from the mover's perspective, then compares each eval's AUC/Brier vs outcome. The
  decisive question was whether the search-over-leaf advantage GROWS with depth. It does — sweep at
  sims=128/384/768 (240 S-vs-S games each, ~13k snapshots):
  | sims | V_static AUC | V_search AUC | dAUC | agree corr |
  |------|------|------|------|------|
  | 128 | 0.642 | 0.680 | +0.038 | 0.822 |
  | 384 | 0.688 | 0.737 | +0.049 | 0.811 |
  | 768 | 0.645 | 0.700 | +0.055 | 0.789 |
  Three concordant trends: **dAUC grows, Brier gap widens, agreement falls** as search deepens — deeper search
  increasingly diverges from AND outperforms the leaf. The leaf AUC ~0.64 sits exactly on the documented
  static plateau (re-confirmed now against STRONG S-vs-S labels, not H3-level) → **re-weighting V is dead**.
  Only the WITHIN-row paired dAUC is a clean comparison (each sims row plays a different game set, so absolute
  AUCs wobble); all three deltas move the same way → trust the trend. Verdict: **Path C (distill V+search →
  numpy net → deeper search) is the lever.** **Do NOT re-tune V on self-play OUTCOMES as the objective** — a
  mirror match is ~0.5 (no gradient) and reintroduces single-strategy-collapse / denial-blind risks; the
  style-diverse MAXIMIN panel stays the arbiter. (For the framing/decomposition that designed this test —
  static-V-vs-outcome = "biased leaf?" vs static-V-vs-searchV = "needs depth?", and why you need the outcome
  as a third anchor since searchV inherits the leaf's bias — see git history of this section.)
- **Take-pruning of dominated gem-takes — TESTED & REJECTED (wash; do not relitigate).** The engine offers
  take-2-different / take-1 even when a superset take-3 is available; under the token cap these are weakly
  dominated. A search-local prune (`legal_fn` hook on `Search` + a `_search_legal` that drops them when total
  tokens ≤7) was sound in theory but **panel A/B was an exact wash (0.8104 = 0.8104)**, with a noise-level
  per-opp wobble that if anything nudged the worst matchup (vs-H3) down. Reason: the **policy prior already
  soft-prunes** them (low `take_value`/need → ~0 prior → ~0 visits), so explicit pruning frees no sims.
  Reverted. (At 8/9 tokens take-fewer is genuinely distinct anyway; the equivalence "take-3 then discard the
  just-taken gem ≡ take-2D" holds only in the search's model, and serving executes that discard via greedy H3,
  not search — a separate reason not to lean on it.)
- **Mixmax / pessimistic backup — TESTED & REJECTED (do not relitigate; June 2026).** The user's intuition
  "assume the opponent plays at least somewhat well" → blend each edge's diluted mean Q with the best reply
  one ply down (`mcts.Search(backup_lambda=L)`, `vsearch.BACKUP_LAMBDA`, parked default-0 = byte-identical;
  the best-reply Q is averaged over determinizations so it pessimizes over DECISIONS not deck luck — correct
  ISMCTS). **Self-gate vs FROZEN today's-S (paired CRN, the sharp instrument) showed a clean MONOTONIC
  degradation:** lam=0.15/0.3/0.5 → 0.481/0.463/0.383 on the same seed base (lam=0.5 ~4 SE below 0.5). A lone
  fresh-seed 0.520 for lam=0.15 contradicted its own 0.481 screen (regression-to-mean noise ~0.5); the panel
  +0.046-min is the documented weak/noisy discriminator (~1.2 SE, different game set) — not ship-grade. The
  negative slope matches the **maximization bias** (the max is over noisy 1-visit grandchildren → over-estimates
  the opponent's best reply → over-pessimism that grows with lam). A min-visit guard on the max could debias it
  but was not pursued (the naive monotonic-negative result + the strong prior make a small-lam rescue unlikely).
  Confirms again: the static eval is **already used near-optimally by the plain averaging backup** — re-shaping
  *how* the leaf is aggregated in PUCT washes, same as re-shaping the leaf itself. Tooling: `backup_lambda_ab.py`
  (focused self-gate: screen → fresh disjoint-seed → panel RPS guard for the one knob).
- **Path C (distill V+search → numpy net) PROTOTYPED & the bottleneck PINNED to FEATURES, not arch (June
  2026).** Tooling: `vsearch_distill.py` (harvest `(features, V_static, V_search, outcome)` from S-vs-S +
  ridge/MLP distill, with a `--enriched` mode + `--cache`), `attn_distill.py` (card-set attention pre-check on
  the cache). Findings, all measured on ~33k S-vs-S snapshots @ sims=384 (leaf AUC ~0.69, search target ~0.74):
  - **Cheap-feature distillation STALLS.** ridge/MLP/**card-attention** all cap **AUC ~0.65–0.67** predicting
    V_search — *below* the leaf, far below the search target. Not validated.
  - **It's a FEATURE-information bottleneck, not architecture.** Targeting V_static, models REPRODUCE the leaf
    at **corr ~0.91** yet still cap AUC ~0.66; the ceiling is the SAME (~0.66) whether the target is V_search or
    V_static → the limit is what the 305 encoder *contains*. **Attention ≈ linear** here (no arch advantage)
    because neither has the inputs: the encoder omits the leaf's derived terms — **turns-remaining horizon,
    deck composition/per-color demand, engine/reachability/potential**. This is the truer cause of variant Z's
    plateau: Z trained on these same lossy features → capped ~0.65 *before architecture mattered*. (Bug noted:
    the attention pre-check first looked negative because per-card tokens lacked the mover's bonuses — fixed by
    injecting them; still capped, confirming features not arch.)
  - **Redirect → ENRICH THE ENCODER** (the #1 pre-retrain adjustment). Feed the net the leaf's own derived
    terms (base 305 + per-board-card H3 `(take,engine,point,cost)` + `v_state` component breakdown + turns).
    Costs ~leaf-level compute (so NOT the Path-C "100× cheaper for deeper search" bet — the retrain chases
    STRENGTH, not speed). **Pre-check RESULT (RUN, `--enriched`, same 600-game/sims384 harvest): enrichment
    UNBLOCKS it — direction validated.** On THIS test set (leaf 0.670, search target 0.717): ridge **0.694**,
    MLP 0.681 — both now ABOVE the leaf (on base features NOTHING beat it), capturing **51% of the search-vs-leaf
    gap**; ridge's fit to V_search jumped corr 0.76→0.85. So a *learnable* eval can beat the hand-leaf once the
    features carry its terms. Caveats: magnitude is modest (+0.024 linear; the other ~49% of the gap is pure
    lookahead no static eval recovers — search on the better leaf reclaims it), and the harness MLP is still
    undertrained (< ridge — a regularization/early-stop issue, NOT capacity), so the true NET ceiling is likely
    higher, and the per-card-terms-in-attention-tokens test (not yet run on enriched) should push further.
    Verdict: **retrain green light, with bounded-but-real upside.**
  - **The retrain decision (locked direction):** if green, it's an AlphaZero retrain with (a) **enriched
    encoder** [feature set must be locked BEFORE start — input-dim change = full restart], (b) **card-set
    attention** value+policy heads, (c) **bootstrap by distilling S's (V_search value, MCTS visit-policy)** so
    self-play starts competent — NOT from-scratch (every from-scratch/flat-feature net LOST to the heuristics).
    Reuse the built shaping/league/curriculum. Verify a numpy-export path for attention before committing, and
    consider a C/Cython engine first (self-play game-gen is the wall-clock sink). `distill_cache*.npz` are
    gitignored scratch.
- **DEPLOYED + MAXIMIN-TUNED (June 2026):** shipped to `main` (variant S = `da18bab`; maximin config =
  `31bbfbd`). The maximin `vsearch_autotune` pass-0 adopted exactly two knobs — **`W_ENGINE_STK` 0.8→0.4**
  (`v_state.py`) and **`C_PUCT` 2.0→1.5** (`vsearch.py`) — confirmed on DISJOINT fresh seeds (N=360, sims=120):
  worst-matchup **min 0.664→0.750**, mean 0.729→0.777, every panel matchup up; validated at higher sims via the
  panel-vs-sims speedcurve (min 0.812 / vs-H3 0.875 at sims=800). The bigger lever was `C_PUCT` (a SEARCH knob,
  not a leaf weight) — consistent with "search is the lever." We stopped the autotuner after pass 0 (a watcher
  tree-killed it at the first `[p1]`); pass-1+ gains are marginal. Speedcurve also showed raw-sims strength
  still climbing but with **diminishing returns** by 400–800 sims (S@hi-vs-S@lo adjacent doublings ~0.5–0.59;
  8× span 0.73) → speed micro-opts give modest gains; leaf quality is the bigger lever.
- **Behavioral audit + self-gate campaign (June 2026):**
  - **Over-reserve — TESTED & REJECTED (don't relitigate).** `blunder_finder.py` found S reserves ~4.3×
    greedy H3 (12.6% of moves vs 2.9%, ~56% never bought) — an EVAL bias (a deep search AMPLIFIES it → the
    leaf over-values reserving, not a shallow-search artifact). BUT the **human playtest** verdict was
    "reserves mostly GOOD, only slightly excessive," and a new `v_state.RESERVE_PENALTY` knob (default 0 =
    byte-identical) at 0.3 **HURT the worst matchup** (vs-H3 min 0.785→0.745) for no avg gain → the reserves
    are tactically useful (denial/securing vs the racing H3); "wasted at game-end" ≠ a blunder. **Keep
    `RESERVE_PENALTY=0`.** The self-gate later re-rejected it independently (screened ≤0.50 vs frozen-S).
    Lesson: win-rate-vs-a-beatable-panel is blind to behavioral biases, and so is self-play *mirror* (both
    sides share them) — only a behavioral audit vs a non-sharing reference (H3) + a human caught it, and you
    need the fix-knob to EXIST and an *asymmetric* comparison that varies that axis to tune it.
  - **Policy head — ruled out.** `policy_precheck.py`: the H3 policy prior already matches the search's
    top move ~86% (the learned net underperformed it, undertrained) → little room. Low priority.
  - **Self-gate autotuner `vsearch_selfgate.py` (tune vs a STRONG opponent) — paid off.** Candidate config
    vs FROZEN today's-S (NOT the weak panel), **paired CRN**: each board is played both first-player ways
    with `vsearch._RNG` reset, so `cand==frozen` scores EXACTLY 0.5 (unbiased + race-free; `engine.new_game`
    always makes seat 0 first, so the pairing is what balances first-player). Found **`W_PROGRESS` 1.5→2.5**
    that the maximin run (judged on the beatable panel's MIN) had missed: vs-frozen **+0.024** (fresh N=200)
    AND panel avg 0.766→0.797 / **min 0.741→0.778 (+0.037)**, RPS-clean (objectively stronger). Confirms the
    user's thesis: weak-panel tuning saturates; a strong equal opponent sharpens the gradient. All other
    knobs (incl. RESERVE_PENALTY) held. **SHIPPED (on main):** the sims=400 panel confirm HELD — avg
    0.8125→0.8262, **min not worse** (H3 .770→.772; only H2N −.013, within ±.029 noise) — so `v_state.py`
    now has `W_PROGRESS=2.5` deployed (variant S). Tuned at sims=160, confirmed it transfers up to 400.
  - **Turns-remaining estimator — TESTED, NO CHANGE (don't relitigate).** Hypothesis: `turns_table.json` (the
    horizon, measured from H3-vs-H2) is mis-calibrated for the far-stronger S, inflating the horizon-gated
    terms (`_engine_stock`/`_noble_stand`/noble time-gate) and feeding the over-reserve. **Both fixes failed.**
    (1) Re-measuring the table from **S-vs-S** play (`s_measure_turns.py`, 320 games @ sims=128) gives a table
    essentially IDENTICAL to the H3 one: count-weighted mean(S − H3) = **−0.020 turns**, and even the start
    cell (0,0,0) matches (26.35 vs 26.28). The table keys on the **game STATE** (cards/points/gems), which
    already encodes progress, so turns-to-finish from a fixed state is ~play-quality-invariant — a stronger
    player REACHES good states sooner but the trajectory FROM a state is the same (so the docstring's
    "self-referential" caveat is genuinely mild). (2) A board-CONDITIONAL greedy **turns-to-win planner**
    (`valuation3._planner_turns_seat`, behind `TURNS_MODE`, default off) is a WORSE turns predictor (corr
    0.946 vs the table's 0.981; MAE 2.21 vs 1.30) AND makes S weaker in the A/B (`turns_ab.py`): **0.469 vs
    frozen-S**, panel avg 0.720 vs 0.783. Board composition barely moves turns-left once points-needed is
    known. **Keep `TURNS_MODE="table"`.** The planner/`table_s` machinery is parked default-off (byte-identical).
    `s_measure_turns.py` (also reusable for the 21-point turns re-measure) + `turns_ab.py` are committed tooling;
    `turns_table_s.json` + the `.out` logs are gitignored scratch. (3) The KEY-lossiness follow-up (the user's
    sharper point — the key is RESERVE-BLIND, and H3 barely reserves while S reserves constantly): `turns_feat_diag.py`
    confirms reserved-count carries **real** omitted signal — holding a reserve correlates with ~**−0.72 turns**
    left (monotonic residual −0.35/−0.86/−1.40 at 1/2/3+ reserves) — so the table genuinely over-estimates the
    horizon in S's reserve-heavy states (your hypothesis was directionally CORRECT). BUT correcting it
    (`valuation3.RESERVE_TURN_ADJ`, subtract turns/reserve, default 0) is a **WASH for PLAY**: vs frozen-S the
    head-to-head is 0.527/0.510/0.517 at adj 0.4/0.7/1.0 (all CIs cross 0.50) and the panel is non-monotonic
    (noise). It doesn't convert because the horizon scales only the SECONDARY engine/noble standing terms;
    points/progress dominate move-choice, so a sub-turn horizon shift barely moves it (aggregate dR²=+0.0024).
    **Gold weighting is NOT supported either** — controlling for reserves, gold advances you LESS per token than
    a colored gem (coef −0.20 vs −0.41); its raw effect was just reserve-correlation. **Keep `RESERVE_TURN_ADJ=0`.**
    Net lesson: R² gain ≠ strength; the turns horizon is not a strength lever for S (3 independent washes).
  - **Net retrain / learnable-leaf path — EXHAUSTED, beats nothing (DO NOT relitigate).** A pre-retrain
    derisking sweep (offline scripts: `distill_features.py`/`distill_fit.py`/`leaf_ab.py`, `bootstrap_harvest.py`/
    `bootstrap_train.py`/`net_vs_s.py`, `policy_arch_test.py`) tested every lever a learned net could give S.
    **Six converging negatives:** (a) **leaf-swap** — an enriched ridge leaf distilled toward V_search (held-out
    AUC 0.718 vs the static leaf's 0.670) made S only **0.534** vs frozen-S (n.s.), panel wash → a sharper static
    leaf does NOT convert through search. (b) **base-feature bootstrap** — a net distilled from S (value+policy)
    scored **0.042** vs S (near-uniform policy CE 2.67). (c) **enriched bootstrap** — value sharp (MSE 0.027),
    policy lifted to 0.52 top-1 but still **0.315** vs S. (d) **structured/per-card policy head** — 0.554 top-1 ≈
    flat 0.535, both ≪ the H3 prior's **0.86**. The wall is NOT features or architecture: **S's search move ≈
    H3's greedy move 86%, and predicting it essentially requires recomputing H3** — any net is a lossy
    approximation (~0.55). So the best static policy IS the H3 prior, which **S already uses**; "H3 prior + net
    value" just rebuilds ≈ S. Combined with "better value doesn't convert," **no net configuration beats S.**
    The only untested path is self-play discovering a >H3 policy from the 0.315 enriched bootstrap, but the net
    represents policies at ~0.55 fidelity and base-feature self-play already capped sub-S (variant Z) → low odds,
    not pursued. **Conclusion: S is at the ceiling of the heuristic+search approach; the learnable-net path can't
    surpass it.** (Reusable byproduct kept on main: `league.py`/`train_az.py` now accept **`S` as a league/gate
    opponent** via `--heur-variants S` + `--opp-s-sims`; `vsearch.LEAF_MODE`/`net.SpenderNet(in_features=)` are
    byte-identical-default. `*cache*.npz`/`leaf_model.npz`/`checkpoints_bootstrap*` are gitignored scratch.)
- **21-point "Long" mode — LIVE + specialized.** Per-game `win_points` (default 15) is wired through the
  engine, production rules (`main._win_points`), and the AI stack (v_state convex zone, `victory_closeness`,
  heuristic3 win-checks all read `s.win_points`); the lobby has a **Classic 15 / Long 21** toggle threading
  `win_points` into `create`. **Any picked AI auto-adapts to 21** (no separate variant needed). Shipped 836ad6d
  (Phase 1) + 567e5d8 (toggle); byte-identical for Classic.
  - **Lobby UX follow-ups (June 2026):** the toggle was reworked to a segmented `.length-toggle`/`.len-btn`
    whose selected state changes ONLY background+color (fixed border/padding) — the old `.mode-toggle`
    swapped `btn-outline`↔`btn-gold` whose borders differ, which **shifted the page on select**. The toggle
    now ALSO **filters the Open Games list** to the selected length (`openGames.filter(g => (g.win_points||15)
    === winPoints)`; `list_open_games` parses `win_points` out of `state_json` and returns it). In-game, a
    "**Target: N**" label sits above the hint (`.hint-col` wraps target+hint in the desktop actions-panel; an
    inline `.target-label` in the mobile action-bar), reading `game.win_points || 15`. Create button is just
    "+ Create Game" (length comes from the toggle).
  - **The genuine specialization is STRUCTURAL (done):** (1) the convex near-win zone auto-shifts to the last 5
    of `win_points` (→16 at 21); (2) **`turns_table_21.json`** — a 21-point-MEASURED horizon table, auto-loaded
    by valuation3 when `s.win_points==21` (the 15-table under-counts the 21 horizon by ~3.8 turns — a real
    structural gap, unlike the player-strength recalibration which was a wash). S-at-21 beats the heuristic
    panel ~0.76 (H3 .70 / H2 .82 / H2N .70 / H2R .81).
  - **Weight retune — NO honest change (don't relitigate).** The self-gate at `--win-points 21` (vs frozen-S-at-21)
    adopted `W_ENGINE_STK 0.4→0.2` on the reused per-knob holdout (0.529), but it **failed the fresh disjoint-seed
    re-measurement (0.4979, below 0.50) AND the RPS guard** (worse vs H3) → a holdout artifact, not adopted.
    Everything else screened-high-but-failed-holdout (W_ECON 0.637, W_POINTS 0.575, W_PROGRESS 2.0). So
    **`vsearch_s21.json` is empty** → S21 = S's 15-weights + the structural 21-adaptations. Serving:
    `_s_choose_move` applies any S21 overrides under `_S21_LOCK` only on `win_points==21` (empty config = no-op,
    byte-identical). Harnesses gained `--win-points` (`s_measure_turns`/`vsearch_camp`/`vsearch_selfgate`).
- **Open / next:** the 15-pt **pessimistic-backup / search-aggregation** experiment (changes how the eval is
  *used* in PUCT, the proven-to-matter lever, vs eval quality which the leaf-swap showed doesn't convert) is the
  most promising untapped 15-pt strength idea. Parked: "search owns DISCARD/NOBLE + a discard prior" (low gain).

### Hard-won conclusions — DO NOT relitigate
These cost many self-play/training cycles to establish:
- **Eval-weight tuning is saturated.** One gain (0.725 vs original), nothing since. The first run captured it.
- **Evaluation quality is NOT the bottleneck.** Static-eval accuracy plateaus ~0.65 *regardless of model class or features*: an **MLP** (more capacity) and **Stage 1c richer features** (per-colour bonuses/tokens, reachability/threat) both gave the same ~0.64–0.66 and were reverted. The missing information (future deck draws, deep lines) isn't in any static snapshot — it needs **lookahead**. **The remaining lever is SEARCH, not evaluation.**
- **Self-play is blind to blocking/contested tactics** — its opponent never threatens coherently, so denial never pays off and those features (`contested_weight`, `block_urgency_gate`) train toward off. A scripted `strategist.py` opponent is competent (~greedy strength) but **MCTS saturates it 12–0**, so it can't measure improvements above current strength either. **The only reliable judge of the human-exploitable weakness is a human playtest.**
- **Next lever = search**: (1) audit `_get_all_moves` pruning (winning lines may never be enumerated), (2) tree reuse between moves + UCB sweep, (3) AlphaZero-style policy head + real exploration (the eventual cure for tactics, biggest build). **UPDATE (June 2026): the search lever is realized by variant S** — `v_state` V(state) + determinized PUCT on the H3 eval — at **0.733 vs greedy H3 / 0.758 panel**, confirming search (not eval) was the bottleneck. See "Variant S" above.

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
`WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws"` — **baked in at
build time** (NOT derived from `window.location`). `HTTP_BASE` is derived from it.
This is why a separate front-end host (e.g. the Cloudflare staging build) can point
at the prod backend just by setting `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws`
(see "Staging environment" below).

### Reconnect tokens
Stored in `localStorage` as `spender_token_${roomId}_${myId}`. Sent on reconnect as `{action: "reconnect", token}`.

### Identity
For a logged-in user `myId === user.id` (account id = `gen_token(10)`); a guest
gets a random `uid()` in `localStorage.spender_myId`. The room player id (`pid`)
sent in the WS path IS `myId`, so a created game's `player1_id`/`host_id` equals
the creator's `myId` (= account id when logged in). `normalize_room` uppercases.

### Session validation on load (stale-token fix)
The frontend restores its "logged in" state from `localStorage` (`spender_user`),
but a stored `session_token` can be silently dead — it expires after 7 days, and
there's **one token per user**, so a login on another browser/device supersedes the
old one. A dead token downgrades every authenticated request to anonymous while the
UI still shows you logged in (e.g. the Books "Edit ranking" button vanishes for the
admin until a re-login). Fix: the loading effect validates the token **before
routing**. **`GET /auth/session?token=`** (thin wrapper over `core.auth.get_user_by_session`)
returns `{ok:false}` for a definitively-dead token → the app clears the stale login
and routes to the auth screen; `{ok:true,user}` → stays logged in and refreshes the
cached identity (name/is_admin). A network error/timeout NEVER logs you out (a blip
must not), validation runs only after the backend is confirmed reachable, and it
degrades safely if `/auth/session` isn't deployed yet (404 → stay logged in).

### Lobby UI (June 2026)
- **AI opponent picker** is a floating dropdown (`.ai-picker`, `position:absolute`
  in a `.ai-picker-wrap`), NOT inline — inline reveal shifted the whole page.
  One "Play vs AI ▾" toggle reveals A/B/C/C2/Z; picking one closes it.
- **Matchup display**: game cards show `player1_name vs player2_name` (AI shows as
  `AI (X)`); backend `list_user_games` returns both names + `you_are_p1`.
- **Cancel own open game**: open games where `g.host_id === myId` show Cancel
  (you only Join *others'* games). `list_open_games` returns `host_id`.
- **In-progress section is ALWAYS "Active Games", never "Resume".** Two sections —
  **Open Games** (`/games`; your own open lobby shows Return + Cancel) and **Active
  Games** (`myGames.filter(status==="playing")`). The localStorage fallback card
  (saved `spender_roomId`, shown to guests with no `/games/mine`) is ALSO titled
  "Active Games" and guarded (`!inLists && !browserLoading && !hasActiveGames`) so it
  never co-renders with the real Active Games section (no duplicate header). There is
  no "Resume" *section* heading anymore — only the per-card **Resume** *button*.
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

### Tab-back + cancelled-join fixes (June 2026; do not regress)
- **Tab-back only rejoins ACTIVE games.** The visibilitychange reconnect (iOS kills backgrounded
  WS) now also guards `screenRef.current === "game"` — without it, tabbing back while in the
  lobby/waiting re-opened a stale waiting room (the "dumped into waiting" report).
- **Joining a cancelled game is rejected.** On WS connect the handler `ROOMS.setdefault`s a fresh
  empty room for ANY id (needed so the creator can then `create`). After a host cancels (room
  popped from ROOMS + deleted from DB), a second client connecting to that id fabricated a
  **phantom hostless room**, and `join` then succeeded into it → neither player was host →
  un-startable (the bug the user hit). Fix: the `join` action rejects when
  `not r.get("host") or r.get("game") is None` ("this game is no longer available"); the frontend
  error handler clears the stale resume pointer and `fetchGames` to drop the dead game. Verified
  e2e (create→cancel→join-rejected).

### Lobby Open/Active split + Resume card (June 2026; do not regress)
- **The lobby is split into "Open Games" (top) + "Active Games" (below), with NO overlap.** "Open
  Games" (from `list_open_games` — ALL `status='open'` lobbies) is the SOLE home for not-yet-started
  lobbies: the owner (`g.host_id === myId`) gets **Return** (`handleContinue`, re-enter to start once
  someone joins) **+ Cancel**; everyone else gets **Join**. "Active Games" filters `myGames` (from
  `list_user_games`, which returns the user's `status != 'over'` games) to **`status === "playing"`
  only**. Before the split, a user's own open lobby showed in BOTH lists (because `list_user_games`
  also returns open games) — that's the overlap this removed. Active Games is intentionally NOT
  length-filtered (you want all your in-progress games); **Open Games IS** filtered by the Classic 15 /
  Long 21 toggle (`openGames.filter(g => (g.win_points||15) === winPoints)`). Frontend-only — the
  backend endpoints were already returning `status` per game.
- **The Resume card no longer flashes on Back-to-Menu.** The `Resume` fallback IIFE (shows a saved
  `spender_roomId`+token that isn't in your fetched lists) is gated on **`!browserLoading`** AND hidden
  when the saved id is in **`openGames` OR `myGames`** (not just `myGames`). Without the `browserLoading`
  gate it flashed right after creating a game: Back-to-Menu re-rendered the browser with STALE lists
  before `fetchGames` resolved → Resume appeared → vanished once the new game landed in Open Games. The
  `openGames` check also removes a **guest-side duplicate** (guests have an empty `myGames` because
  `/games/mine` is logged-in-only, so a guest's own open lobby lives only in `openGames`).
- **In-game "Target: X" label** (`.target-label`) is `font-size:1.05rem` (bumped 50% from `.7rem`),
  shared by the desktop `.hint-col` and the mobile action-bar placements.

### Responsive game layout (June 2026 — the big UI overhaul; do not regress)
The game screen has THREE layouts driven by width; all CSS lives in the one `css`
string in `Spender.jsx`. **The base styles are the small/compact foundation; the
DESKTOP look is added in `@media(min-width:901px)`** (an inversion worth knowing —
editing base affects phone/tablet, not desktop):
- **Desktop (`@media(min-width:901px)`)**: `.app.game-screen{height:100vh;overflow:hidden}`
  locks the screen to the window (no page scroll). `.game` is a 2-col grid
  `1fr 560px` (board | sidebar) that **needs an explicit definite height**
  (`flex:none; height:calc(100vh - 48px)`) **AND `grid-template-rows:minmax(0,1fr)`** —
  both, and it took 3 tries to learn why. `flex:1` yields a `flex-basis:0%` that is NOT
  a definite height the grid `fr`/`minmax` can resolve against, so the row grows to its
  tallest content (the recent-moves list) and pushes past the screen; the explicit
  height + `minmax(0,…)` bounds the row to the viewport. **The SAME bound must be
  repeated on the inner `.game-sidebar` grid** (`grid-template-rows:minmax(0,1fr)`) —
  bounding only the outer `.game` left the sidebar's own auto row growing to the moves,
  so the log was CLIPPED, not scrolled (the "EXACT SAME ISSUE" recurrence). **Belt-and-
  suspenders:** the move log ALSO carries an explicit `max-height:calc(100vh - 140px)`,
  so it bounds + scrolls even if the nested-grid height chain ever fails to propagate.
  `.game-main` is a 3-col / 2-row grid
  `grid-template-columns:auto 1fr 132px; grid-template-rows:auto 1fr`: row 1 =
  nobles box (horizontal, `data`-less) + an **actions box** (turn hint + Take/Buy/✕,
  right-aligned); row 2 = the **levels** (`grid-column:1/3`, `1fr` so the 3 card rows
  spread flush to the bottom via `justify-content:space-between`); the **gem bank** is
  a vertical column (`grid-column:3; grid-row:1/span 2`) with the gold/wild token
  FIRST (top). The **sidebar** is itself a 2-col grid (players left | recent moves
  far-right), both `grid-row:1` full-height — player boxes `flex:1` (top & bottom
  halves), the move log `flex:1; min-height:0` so it **scrolls internally** instead of
  growing the page. Card size is driven by `--card-w/--card-h` (≈144×185) set on
  `.game-main`.
- **Tablet (`@media(max-width:900px)`)**: single column; Take/Buy/✕ move beside the
  nobles (`.board-actions`).
- **Phone (`@media(max-width:600px)`)**: board-first order; the nav scrolls (not
  fixed); player panels collapse to a one-line `cards | gems` summary that taps to
  expand reserved cards; the move log shows the most-recent entry + a tap-to-expand;
  L3/L2/L1 merge into one box.
- **Card sizing is fully CSS-driven** — `CardView`/empty slots set NO inline width;
  `.card`/`.card-slot`/`.deck-pile` use `var(--card-w/--card-h)`, and
  `.level-row>*{flex:1 1 0;max-width:var(--card-w)}` makes a full level (deck + 4
  cards) shrink to fit any column width.
- **CSS-grid "staircase" gotcha (hit TWICE — board + sidebar):** if DOM order places
  a later element in an EARLIER column (descending columns), grid's *sparse* auto-flow
  refuses to backtrack and drops it to a new row → a diagonal staircase. **Fix: pin
  every grid child to an explicit `grid-row`.** Relatedly, `grid-row:1/-1` needs an
  explicit `grid-template-rows` or `-1` collapses to line 1 (item spans only row 1).

### Player box + nobles details (desktop; do not regress)
- **Indicator sizing uses `zoom`, not font/padding math.** The desktop player box scales
  its indicators with `zoom` (scales box + text + the inline gem dots together, WITH
  reflow — unlike `transform:scale`, which overlaps neighbors): gem pills (`.token-pill`)
  and card/bonus pills (`.bonus-pill`) `zoom:1.2`, the "N gems" total (`.gem-total`)
  `zoom:1.2`, reserved cards (`.player-reserved .card`) `zoom:1.1` + `width:89px` (the
  sidebar does NOT inherit `--card-w`, so reserved cards fall back to 88px — set width
  explicitly). Per-px width nudges ride on top via horizontal padding (e.g.
  `.bonus-pill{padding:3px 9.5px}`). `zoom` is supported in current Firefox (126+) and
  Chromium. **Remember the zoom factor when a request says "+1px"** — the on-screen delta
  is `px × zoom`.
- **0 gems must not shift the bonus pills.** The "N gems" total ALWAYS renders (even
  "0 gems"), and `.player-tokens` has a `min-height` reserving the empty token row — but
  with `align-items:flex-start` so that `min-height` does NOT stretch the pills taller
  (the row is `display:flex`; default `align-items:stretch` made the pills grow — a
  regression the user caught immediately).
- **Nobles are square + fixed-position.** Desktop `.noble` is `width:120px;aspect-ratio:1`
  (exactly square); requirement markers (`.noble-req-dot`) are rounded SQUARES
  (`border-radius:2px`), reading as cards not gems. **Claiming a noble never moves the
  others**: the row renders the FULL original set in a stable id-sorted order
  (`game.nobles` ∪ every player's claimed `nobles`, sorted by id), and a claimed noble
  shows as a **blank slot** (`.noble.noble-empty`, dashed placeholder) in its fixed
  position during play (dimmed + claimer's name only in the end-game review). The backend
  removes claimed nobles from `game["nobles"]` (so positions would otherwise compact/
  shift) — this position-preserving reconstruction is frontend-only.

### Action animations — flying gems + cards (`.fly-layer` / `flyers`)
A single `useEffect([game])` diff (mirrors the `prevBankRef`/`flashGems` pattern)
drives all move animations, so it covers EVERY player incl. the AI with no per-handler
hooks. It snapshots each player's **tokens + purchased ids** and the **board slot ids**;
on the next state it computes deltas and, **only when the move log advanced by exactly
one** (burst guard for load/reconnect), spawns absolutely-positioned flyers in a fixed
`.fly-layer` overlay:
- gem gained (delta>0) → fly bank→player, shrink (take / reserve-gold);
- gem spent (delta<0) → fly player→bank, grow (buy / discard);
- a player's `purchased` grew → fly a card-shaped flyer from the board slot it came
  from to the buyer's box, shrink.
Positions are measured at runtime via `getBoundingClientRect()` on `data-color`
(bank tokens), `data-pid` (player boxes), and `data-pos` (board card slots — the slot
persists after the buy because it's replenished). One `@keyframes fly` (translate +
scale via per-flyer `--dx/--dy/--s0/--s1` inline vars); flyers are removed by a
timeout. Keep these three `data-*` attributes when touching the bank/players/board.

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
`.github/workflows/deploy-pages.yml` Action fires on every push touching the
frontend (`webapp/**`, `games/spender/**`, `games/castles_of_crimson/**`,
`books/**`, `shared/**`): it `rm -rf docs/`, rebuilds the **top-level `webapp/`**
(relocated there from `games/spender/webapp/` — neutral, not owned by a game) from
source (with `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws` baked in), and
commits/pushes `deploy: update GitHub Pages from Vite build [skip ci]`. So a hand-built `docs/`
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

### Staging environment (Cloudflare — test frontend changes live before prod)
A live staging site mirrors the front end so UI changes (esp. mobile/desktop layout)
can be tested on a real URL before shipping to prod:
- **URL:** https://webprojectsstaging.forry4.workers.dev/ — a **Cloudflare Worker**
  (`name: webprojectsstaging`) that auto-rebuilds on every push to the **`staging`**
  git branch. Build config (Cloudflare dashboard): root `webapp`, build `npm run build`,
  output `dist`; env `VITE_BASE=/`, `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws`,
  `NODE_VERSION=20`. It **reuses the prod backend** (no separate Render service / DB),
  so only FRONTEND changes are testable and any test games/accounts hit the real DB
  (use vs-AI games to stay private).
- **Enabling code (now on main):** `webapp/vite.config.js` reads `base` from
  `VITE_BASE` (default `/` — the GitHub Pages user site serves at the root); Vite was upgraded **5→6**
  (Cloudflare auto-config requires ≥6); `webapp/wrangler.jsonc`
  (`name: webprojectsstaging`, `assets: ./dist`, SPA) drives the Worker deploy and is
  ignored by GitHub Pages.
- **Workflow:** work in a `staging` worktree → `git push` → test at the workers.dev
  URL → to ship, integrate with main: `git rebase origin/main` (UI vs backend work
  usually touch disjoint files), `git push origin staging:main` (fast-forward), then
  `git push -f origin staging` to resync. CI then rebuilds `docs/` + redeploys prod.
- The local↔Cloudflare bundle **hashes differ** (different build envs), so verify a
  deploy by the served CSS/markers, not the filename.
- **Fastest iteration loop = local vite dev pointed at the prod backend** (the
  Cloudflare deploy is ~30–45s/change; HMR is instant). From `webapp/`:
  `VITE_BASE=/ VITE_WS_URL=wss://splendid-nelz.onrender.com/ws npm run dev` — open the
  printed `localhost:<port>` (vite bumps the port if 5173 is taken, e.g. 5174), log in,
  and **resume your real game from the account-based games list** (so the long-move
  board is there to test layout). Edits hot-reload into that tab. Gotcha hit once: a
  stale 302-redirecting server on :5173 sent the user to prod — confirm the exact port
  vite printed.

### Frontend smoke test (`npm run smoke`) — catch blank-page regressions
`webapp/test/smoke.mjs` (Playwright) builds the app, serves it with `vite preview`,
loads it in a headless browser, and FAILS if `#root` doesn't render or any uncaught
page error fires. This catches the nasty class where **the bundle compiles but
throws at runtime → a blank white page**. The bug that motivated it: a CSS comment
in the `css` template literal contained backticks (`` `.game` ``); a backtick inside
a JS template literal terminates it, so the rest parsed as a stray tagged-template
(`str.game\`…\`` → "…is not a function" at load). **NEVER put a backtick inside the
`css` string** (the css const spans ~`Spender.jsx:69–515`; only its two delimiters
may be backticks).
- **Run `npm run smoke` (in `webapp/`) before pushing** — esp. to the `staging`
  branch, since Cloudflare does NOT run it. Locally it uses the system Edge channel
  (no browser download); in CI it uses bundled chromium.
- It **gates the prod deploy**: `deploy-pages.yml` runs `npx playwright install
  --with-deps chromium` + `npm run smoke` BEFORE the real build, so a blank-page
  build can't reach GitHub Pages. (It runs before the WS-URL build so its throwaway
  build doesn't become the deployed artifact.)
