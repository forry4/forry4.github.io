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
- Production: GitHub Pages serves the **`gh-pages` branch** (since 2026-06-24; was `main`/`docs`), which CI (`deploy-pages.yml`) **builds + force-pushes** on every frontend push to `main`. **Never hand-build/commit the bundle** — commit source only and let CI deploy. CI no longer commits to `main` (that was the local-main drift source); `docs/` is now vestigial. See "Build + deploy steps" below.

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
  `git push origin <branch>:main` (fast-forwards `origin/main`); CI builds + publishes to the `gh-pages` branch + redeploys.

---

## Where Wolf? (third game)

`Where Wolf?` is the **third game** — a faithful **One Night Ultimate Werewolf** clone (real-time
social-deduction party game, **3–10 players, one device each**). Built in the `forrestm_projects-wherewolf`
worktree on the **`wherewolf`** branch. Same architecture as CoC: pure `engine.py` + thin FastAPI sub-app
`main.py` (mounted at `/werewolf`) + a self-contained `WhereWolf.jsx`. See memory
[[wherewolf-game-status]] for the live deploy state.

```
games/wherewolf/
  roles.py     # deck data: DECK_COUNTS, TOKEN_LETTERS, TEAMS/team_of, NIGHT_ORDER/STEP_ROLE/
               #   ACTION_STEPS/INFO_STEPS, recommended_deck(n) + validate_deck(deck,n), NARRATION
  engine.py    # PURE rules: new_game(deck=)/apply_move/resolve_votes/player_view/is_over/winner +
               #   the night-action handlers and the multi-death win logic
  main.py      # FastAPI sub-app `werewolf_app`; ROOMS/ROOM_LOCK; WS /werewolf/ws/{room}/{player};
               #   the async NIGHT CONDUCTOR; own `werewolf_games` table
  WhereWolf.jsx  # self-contained React component the shell mounts at screen "werewolf"
  tests/       # pytest, 67 tests (deck validation incl. partial in-progress decks, every night action,
               #   the win-condition matrix, the player_view redaction matrix, multi-deck smoke)
```

### Engine model (the single source of truth)
- **`dealt_role` is the role you PERFORM all night (immutable); `card` is your FINAL role
  (swappable).** Swaps (robber/troublemaker/drunk) only ever move `card`/`center`, never `dealt_role`.
  Whatever card sits in front of you when night ends IS your final role (possibly unknown to you).
  The WIN uses FINAL cards. **Self-target is rejected for robber/seer AND the troublemaker** — the
  troublemaker swaps two OTHER players (it once wrongly allowed itself; a stale test had frozen the bug).
- **`player_view(game, pid)` is the hidden-information boundary** — a per-recipient redaction. A
  client is only ever sent the cards it may see in the current phase/step (everything else is
  literally `None` in the payload, so a snooping client can't read a hidden card). `dealt_role` is
  only ever sent for the recipient's OWN seat. The visibility matrix (do not regress): OVER → all;
  DEALING → own; NIGHT own only for robber (new card) + insomniac (own current card); werewolves see
  each other; **minion sees the wolves but wolves do NOT see the minion (asymmetric)**; masons see
  each other; seer sees the peeked player/center; **drunk sees NOTHING of its own (blind swap)**;
  lone wolf's center peek is private. Tests in `tests/test_view.py` + `test_night.py`.
- JSON-safe + reconnect-safe (RNG persisted in `rng_state` as lists; no sets — `wolf_pids`/`mason_pids`/
  `minion_pids`/`deaths`/`winners` are LISTS). The whole `game` dict is persisted.

### Roles + win logic (official ONUW — DEPLOYED)
All roles **except the Doppelgänger** (deferred — its copy-a-role dual-timing is a separate larger
effort; it stays in the deck data but is excluded from the picker + `validate_deck`). Wake order:
werewolves (lone wolf may peek 1 center card) → minion → masons → seer → robber → troublemaker →
drunk (blind-swaps own card with a center card) → insomniac (views own card). Hunter/tanner/villager
have no night action. Teams: village {villager,seer,robber,troublemaker,drunk,insomniac,mason,hunter},
werewolf {werewolf,minion}, **tanner** (own — wins only by dying).
- **Voting is MULTI-DEATH** (`resolve_votes`): the player(s) with the most votes die; a tie for most
  → ALL tied die; if **nobody gets ≥2 votes, no one dies**. **Hunter:** a dead hunter also kills the
  player they voted for (transitive, cycle-guarded).
- **Win (the load-bearing care points — DO NOT regress):** ≥1 **werewolf card** dies → village wins;
  else werewolf-in-play + none died → wolves win; no werewolf in play → village wins iff nobody died.
  **Killing the MINION is NOT a werewolf death** (most error-prone line). **A tanner death with no
  werewolf death SUPPRESSES the wolf-team win** (only the tanner wins). **Minion** wins with the wolf
  team, AND in a no-werewolf-in-play game (with a minion present) wins if any non-minion dies.
  "Werewolf in play" counts a PLAYER's final card only (center wolves don't count). Produces
  `deaths`/`winners`/`winning_teams`/`headline` (+ legacy `winner`/`revealed_pid`). Matrix in
  `tests/test_win.py`.

### Night conductor (`main.py`) — data-driven, fixed windows (NO Events)
`_run_night` iterates `roles.NIGHT_ORDER` keyed on **deck presence** (`game["deck"]`): every role IN
THE DECK is announced — *even one entirely in the center* — so silence can't leak which roles are
out (the announcer calls every role in the game). Each step is a **FIXED-DURATION window** (action
~15s / info ~6s): `set_step` + narrate + `sleep(window)`; player actions arrive via the normal move
handler during the window (validated against `night_step`) and the actor sees their result for the
remainder. **No early-advance and no per-step `asyncio.Event`** (uniform timing → leak-free; the
v1 Event mechanism was removed). Restart recovery (NIGHT→DAY fast-forward) unchanged.
- **Lone-wolf no-leak (DO NOT regress):** the werewolves step ALWAYS uses the action window and ALWAYS
  narrates the conditional lone-wolf line (*"If you are the only werewolf, you may look at a card in the
  center."*). Earlier it only did so when there was actually ONE wolf — leaking (by timing AND narration)
  that the game had a single werewolf, which is supposed to be secret. Now a 1-wolf and a 2-wolf game
  look/sound identical; the lone wolf just peeks a center card during the window, nobody else does.

### Host role picker — `set_roles` (lobby-only, host-only)
Before dealing, the host picks the deck (a multiset of role names) in the waiting room. WS action
`set_roles {deck}` → **`roles.validate_deck(deck, len(players), partial=True)`** (copy caps
`≤3 villagers / ≤2 werewolves / ≤2 masons / 1 each single` + player range + no doppelganger, but
**NOT** the exact-count check — `partial` skips only that) → stored on `room["deck"]` (persisted) →
broadcast (public — the upcoming token row). **`partial=True` is what lets the host's IN-PROGRESS
selection broadcast live** as they tap +/−; the exact `players+3` count is enforced only at deal
(`_handle_start`, which re-validates fully and silently falls back to `recommended_deck(n)` if the
deck went stale or was never set). Frontend: host gets a +/- picker (live "selected X / need
players+3" counter + Recommended button); **non-hosts see EXACTLY `room.deck`** — no recommended
fallback, so they see nothing until the host picks (not a misleading minimum) and see over-/under-full
selections as-is. The "3-10" player-range message (was "3..10"). Deal & Start is gated on
`deckCount === players+3`. Hovering a role (host rows + non-host chips) shows what it does (`roleDesc`).

### Frontend (`WhereWolf.jsx`) — do not regress
Self-contained component (`{myId, authUser, onExit}`); namespaced localStorage
(`werewolf_roomId`/`werewolf_token_*`/`werewolf_narrate`); WS/HTTP bases derive `/werewolf` from
`VITE_WS_URL`; imports `baseCss`. Circle seating (each client at 6 o'clock); the 3 center cards + the
public token row in the middle; SVG vote-arrows on the day phase (computed from seat angles — unit
viewBox `preserveAspectRatio:none`, no DOM measuring); a 3-min day countdown.
- **Responsive seat/center cards (`cardVars(n, isMobile)` → inline `--pcw/--pch/--pcf`):** seat cards
  scale DOWN as the table fills (76×98 at ≤7 players → 56×76 at 10) so up to 10 still ring the circle;
  a separate smaller mobile tier. **Long role names wrap on the cards** (`cardLabel`): the 12-char names
  (Troublemaker/Doppelganger) take a HARD `<br>` (a soft `<wbr>` is not honored inside a flex item in
  every browser — it overflowed on desktop), the borderline ones a soft `<wbr>` + `overflow-wrap:anywhere`.
- **Mobile layout (`@media(max-width:600px)` + `useIsMobile`) — DO NOT regress:** the table reshapes into
  a TALL ellipse filling the screen (`.ww-table-wrap`/`.ww-table` flex to fill, `aspect-ratio:auto`) so
  **YOU sit at the very bottom and everyone else rings the edges**, cards auto-shrink to fit 10. (Was a
  small centred square that left the bottom of a phone empty and overlapped cards.)
- **Token info / role tooltips:** the in-game token row renders from the public `game.deck` (role keys,
  not just letters) so hover (desktop) / tap (mobile) shows the role + what it does (`roleDesc`) — and the
  shared "T" letter (Tanner vs Troublemaker) is correctly disambiguated.
- **Self-vote → a loop arrow** (`selfLoopPath`) curling back to the voter's own card (red for you, gold
  for others), drawn alongside the straight cross-vote arrows.
- **Narration:** browser `SpeechSynthesis` TTS + an always-on caption banner. Server broadcasts
  `{type:"narrate", text, key}`; the client speaks it. Per-device 🔊/🔇 toggle (default ON for host).
- **Reconnect/rejoin hardening (do not regress):** auto-reconnect when the socket drops while in a
  room (bounded retries) + a manual "⟳ Reconnecting…" button; "Your Games"/Resume rejoin paths;
  leaving keeps you a room member + the resume pointer so "back out and rejoin" works and the host
  stays host; auto-resume/reconnect failures recover **silently** (no "invalid token" flash); a join
  that hits a transient "no such room" retries once. A finished game (`phase==="over"`) **clears the
  resume pointer** so it's gone (not resumable/listed) without kicking anyone off the results screen.
- **CSS gotcha:** the `css` template literal must contain NO backtick (the documented blank-page
  smoke-test footgun, shared with Spender/CoC).

### Deploy — LIVE on production as of 2026-06-21
The game **is launched to prod**: the Where Wolf? home card is `status:"ready"` on `main`, so prod
users can play it (commit `7efcb84`). `app.py` mounts `/werewolf` with the same defensive try/except
as CoC. How it was launched (and the lessons, DO NOT regress):
- **Backend** (`engine.py`/`roles.py`/`main.py`) had already been on **`main`**/prod (dormant — no
  home card) so `/werewolf` served the logic; the staging Cloudflare site (frontend) talked to that
  prod backend, which is why the backend had to ship first (staging shares the prod backend).
- **Launched by a SELECTIVE add, NOT a `staging→main` push.** Brought only the wherewolf FRONTEND
  forward onto `main` (`games/wherewolf/WhereWolf.jsx` + the Spender.jsx card hooks: import / `GAMES`
  entry / `screen==="werewolf"` route). A blind `staging→main` push was **unsafe** because `staging`
  had diverged: it was *behind* `main` on the wherewolf backend (lacked the troublemaker + lone-wolf
  fixes, host-picker backend) so a force-push would have **reverted** them. main's wherewolf backend
  is a strict superset of staging's, and the staging site already ran staging's `WhereWolf.jsx`
  against the prod backend, so the launch pairing was pre-validated. (See the staging-divergence
  warning in "Staging environment" below for the selective-deploy recipe.)
- **Historical note (pre-launch):** the frontend lived staging-only while the card was kept off
  `main`; `staging` gets force-resynced by other frontend work (which once wiped the wherewolf card),
  so the rule was to re-apply onto the current `origin/staging` tip + `npm run smoke` + push.
- **Testing gotcha:** distinct local players need distinct browser storage — two same-browser
  incognito windows SHARE localStorage → same `spender_myId` → they collapse into one identity. Use
  different browsers/profiles/devices.

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
    or `None`: username **1–16 chars, `[A-Za-z0-9]` only**; password **1–16 chars**. Enforced at
    `/auth/register` ONLY — login stays permissive so pre-existing accounts still sign in (with a guard:
    reject name>64 / password>128 *unhashed*, a PBKDF2-on-huge-input DoS guard). Frontend input
    `maxLength` mirrors it (register 16/16; login 64/128, so legacy passwords stay typeable).
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
- **Overlay follows WHOEVER'S TURN IT IS (June 2026, `82120c8`):** `mk_room_state` computes
  `ai_card_values` from `game["turn"]`'s seat (not always the AI's) and sends `ai_values_pid`. So on
  YOUR turn the box shows what each card is worth to YOU ("what should I take" — tinted **green**,
  tooltip "Your values"; your own reserved cards get values too), and on the AI's turn it shows the
  AI's perspective (**gold**, "AI's values"). The `_s/_h3/_h2/_v4_card_values(game, seat_pid)` helpers
  take the perspective seat (param renamed `ai_pid`→`seat_pid`); reserved cards follow that seat
  (so blind opponent reserves never leak — they're redacted and keyed by a non-real id anyway).
  Frontend (`Spender.jsx`): `valsMine = roomData.ai_values_pid === myId` drives a `.mine` tint on the
  `.ai-vals`/`.ai-val` box; the **Show/Hide AI values** toggle moved OUT of `.actions-panel-top` INTO
  the actions buttons box (desktop `.actions-panel-btns` + mobile `.board-actions-btns`) via
  `renderAiValsToggle()`, **far-left** (`.ai-vals-toggle{margin-right:auto}`) and styled like the Take
  button (`btn btn-gold`), rendered on EITHER turn so the overlay is toggleable any time.
- **Admin-button login bug fixed (same commit):** `handleAuth` rebuilt the user object as
  `{id, name, session_token}`, **dropping `is_admin`** from the `/auth/login`/`/auth/register` response,
  so the admin-gated overlay button only appeared after a page reload (the on-load `/auth/session` path
  at `Spender.jsx` repopulates `is_admin`). `handleAuth` now preserves `is_admin: !!data.user.is_admin`,
  matching the on-load path — admin features light up immediately on login, no reload.

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

**Baked config**: `W_TEMPO=0.1, W_GEM=0.3, W_GOLD=0.4, NOBLE_SCALE=3.0, NOBLE_CLOSE_FLOOR=0.3, POT_ENGINE_W=0.5,
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
- **Cross-worktree import gotcha — `python -m` runs the CWD's code, NOT `PYTHONPATH`'s (DO NOT regress).**
  `python -m games.spender.ai.az.<tool>` puts the **current working directory's** worktree FIRST on
  `sys.path`; `PYTHONPATH=<other-worktree>` does **not** override CWD for `-m`. So launching a self-gate /
  arena / autotune from the **primary (main) worktree** silently runs **main's** `v_state`/`config_selfgate`/
  etc. — NOT your experiment branch's. The candidate's `--set`/config `setattr`s then land on a module
  lacking the new code (no error), and `config_selfgate`'s `[frozen]` dict / `_PROBE_KEYS` silently **omit
  the new knob** (that absence is the tell). **ALWAYS `cd <experiment-worktree> &&` before `python -m`** (cwd
  wins), and sanity-check that `[frozen]` contains your new knob before trusting the run. (A plain
  `python path/to/script.py` is fine — `sys.path[0]` is the script's own dir, then `PYTHONPATH`.) This cost a
  wasted `W_RESERVE_SLOTS` self-gate that ran main's code with the knob absent from `[frozen]`.
- **Serving + overlay specifics:** `_h3_choose_move` (1-ply `choose_action`) + `_h3_card_values` are wired
  into `_ai_variant_valid` + `mk_room_state` + the move scheduler (same path as H/H2; `mk_room_state`
  includes `ai_card_values` only for in-progress H/H2/H3/S games, **now from whoever's-turn-it-is's seat**
  — see the "Overlay follows WHOEVER'S TURN IT IS" bullet under Variant H2). The admin overlay shows H2's T/E/P/C
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
- **Perf round 2 — deployed sims-starvation diagnosed + leaf sped ~1.76× (June 2026).** Production
  serving logs (`vsearch._run_search_timed` now logs `[S] serving search: N sims in Ts (sims/s)` per move)
  showed **Render's free CPU runs ~330–450 sims/move at ~85 sims/s in the decisive midgame — ~10–11× FEWER
  than local's ~4,300 @ ~950 sims/s** (only trivial near-terminal moves spike, where most sims hit OVER
  cheaply). So the deployed S a strong human beats is badly sims-starved, NOT algorithmically weaker — and
  per the speedcurve strength climbs with sims, so the lever is leaf SPEED (no UX cost; the user declined
  raising `SERVE_TIME`). Profiling the leaf found redundant recomputation, all fixed BYTE-IDENTICAL (gated by
  the exact-value tests, 254 pass): (1) `valuation3._steps` replaces the `sorted(positives)==[1,1,1,1]` test
  in `tempo`/`_reduces_tempo` with `max==1 and count_positive==4` — killed **100% of the ~592k sorts/move**
  (the #1 self-time; +24%); (2) `_color_deficits` append-loop → walrus comprehension (drops ~1.2M appends);
  (3) `noble_progress`/`noble_completion_pts` memoized by **`(bcol, seat)`** (the 3-noble loop depends only on
  the bonus COLOR, not the card — only `noble_progress`'s time-gate `eff/(eff+W·deficit)` combine stays
  per-card via `_noble_terms`); (4) `_w_card` memoized by `(cj, bcol, seat)` (`_rtempo_cache`) — the engine
  loop recomputed `_reduces_tempo` identically for every ci sharing a color (213k→96k). Net **891 → ~1,570
  clean sims/s (1.76×)**; so deployed midgame ~380 → ~670 sims/move. A follow-up memoized **`tempo(ci,seat)`**
  (pure in (ci,seat), recomputed ~197k×/move across the noble/cost paths — caching it also kills the
  `_color_deficits`/`_steps` it spawned) and **`_cost_scalar`** by (ci,seat,extra_bcol): paired A/B ~1545 →
  ~1636 (**+6%, →1.84× cumulative**, byte-identical). That exhausted pure-Python (rounds gave +24/+24/+6% —
  tapering); the remaining hotspots are already-memoized core work + interpreter overhead → next lever is
  compilation (round 3).
- **Perf round 3 — Cython "pure-Python mode" hot leaf (~1.27× more, single source; June 2026).** The
  remaining leaf time is raw CPython interpreter overhead on the numeric loops (no redundancy left to cache).
  Compiled it with Cython — but in **pure-Python mode, NOT a separate `.pyx`** (the deliberate architecture
  choice): the hot functions in `valuation3.py` (`_cost_scalar`/`_color_deficits`/`_steps`/`_reduces_tempo`)
  carry `cython.*` type annotations that are **inert under CPython** (`from __future__ import annotations`
  makes them strings; nothing is evaluated, and `import cython` is guarded → no runtime dep) and become a
  **typed C extension when Cython compiles the module**. ONE source of truth — no duplicated logic, no parity
  test to maintain (a separate `.pyx` was prototyped first — 8.7× on `cost_scalar`, 1.25× end-to-end — then
  discarded for the single-source pure-mode form, which matched it). **Serving = the compiled `valuation3.so`
  shadows the `.py`** (extension > source in import priority); **local dev / any box without a C compiler runs
  the `.py` unchanged** (byte-identical fallback).
  - **Build wiring (`games/spender/Dockerfile`):** the *builder* stage `pip install cython` + `cythonize -i -3
    games/spender/ai/az/valuation3.py`; the slim *runtime* `COPY --from=builder` the `.so` in next to the
    `.py`, then a **build GATE** — `RUN python -m pytest test_h3_valuation test_vsearch` against the COMPILED
    module — so a Cython miscompile fails the image build and can never reach prod (a failed build just leaves
    the previous image serving; the site can't break from this). Shared by the wwsd service too (same
    Dockerfile). `.gitignore`/`.dockerignore` keep the generated `.c`/`.so`/`build/` out of git + context.
  - **Validated in a `python:3.11` container (= prod):** compiled **2114 vs uncompiled 1666 clean sims/s
    (~1.27×)**, 24 exact-value tests pass compiled. Cumulative session ≈ **2.3×** (1.84 × 1.27); Render midgame
    ~380 → ~870 sims/move.
  - **Build env reality:** the dev box (Windows / Python 3.14) has **no C compiler**, so this is built +
    validated in Docker (`python:3.11`, matches prod). There is **no runtime kill-switch** anymore (pure-mode
    has no `if _FV` branch — it's compiled or not at build time); the byte-identical guarantee is the
    build-gate tests, not a flag.
  - **The ceiling — DO NOT relitigate the deeper Cython without a strong reason.** Pure-mode annotations got
    ~most of what this code can give: the whole module compiling is the baseline gain, typed loops add the
    rest. Going to the targeted **2–3×** would need (a) making `Valuation` a **`@cython.cclass`** (cdef
    methods/typed attrs) to kill the now-dominant **method-dispatch + dict-cache** overhead — a big, risky
    rewrite of a 1,000-line cached class — AND (b) Cythonizing `mcts.py`/`engine.py`, because **~15–25% of
    per-sim time (determinize / `_select` / `clone` / `legal_actions`) lives OUTSIDE `valuation3`** — a hard
    ceiling on any leaf-only effort. Judged poor effort/risk/reward vs the 2.3× already banked + diminishing
    sim-returns; **stopped at the leaf.** **(SUPERSEDED IN PART — see Perf round 4: the deeper typed-C-array
    rewrite of the `engine_value` CHAIN (short of the full cclass) WAS done on branch `cython-perf`,
    byte-identical, ~1.85–2.74×. The `@cython.cclass` Valuation + mcts/engine port is still deferred.)**
- **Perf round 4 — typed-C-array rewrite of the `engine_value` chain (branch `cython-perf`, NOT merged; June 2026).**
  Round 3's pure-mode annotations only typed loop COUNTERS — the DATA (`s.bonuses[seat]`, `E.COST[ci]`) stayed
  PyObject lists/tuples, so a naive recompile of the deeper chain was **~1.0× (measured 13.1 vs 12.7 s/game)**.
  The win needs the data in **C arrays** + collapsing the per-card scoring so it crosses the Python boundary ONCE
  per call instead of thousands of times. Done in the SAME single-source pure-mode `.py` (composes with round 3):
  - **Module-level C tables** `COST_C[90][5]`/`BONUS_C[90]`/`PTS_C[90]` filled at import inside `if cython.compiled`
    (gotcha: Cython REVERSES array dims — `cython.int[5][90]` emits C `int[90][5]`; declaring it un-flipped is a
    silent OOB write). **cdef helpers** `_steps_c`/`_reduces_tempo_c`/`_cost_scalar_c`/`_color_deficits_c`/`_eng_base_c`
    (`int*`/`double` C signatures, no PyObject) carry the leaf math.
  - **`_engine_value_h3_c`** inlines the WHOLE H3 `engine_value`
    (delta_take→potential→eng_base→w_card→reduces_tempo→cost_scalar) in C over C arrays with **NO sub-call caches** —
    recompute is byte-identical because every memoized helper is a deterministic pure function. Also converted: the
    `components` cost vector (`tempo`/`gem_cost`/`gold_cost`), the per-Valuation `deck_color_demand` `__init__` loop,
    and `noble_progress` (`_noble_progress_c`).
  - **Every C path is gated `cython.compiled and ci < 90`** so the unchanged Python path still serves the
    synthetic-card unit tests (which append cards past the 90-deck) and any non-deployed flag config; nobles read the
    **LIVE `E.NOBLE_REQ`** (tests replace it) not a frozen table; tuning constants are read **LIVE per call** (NOT
    frozen into C globals) so the offline autotuners can still sweep them.
  - **GOTCHA — a genexpr in the same function scope as a `cython.declare(C-array)` breaks Cython codegen**
    (`GeneratorExpressionScope` error): the C-path functions are genexpr-free (pure fallbacks rewritten without
    `sum(... for ...)`); int/int closeness divisions forced to double via `1.0 *`.
  - **Results — byte-identical (60-game S self-play differential parity char-identical + 32 unit tests, compiled AND
    pure):** engine_value alone **1.49×**, +cost vector **1.85×**, +init/noble **2.74×** (cumulative). The ratio is
    LOAD-dependent (the local box's 11-core tuning job fluctuated): the **compiled path is contention-STABLE at
    ~2.66 s/game** while pure swings 4.9–7.3 — so ~1.85× on an idle box, ~2.74× on a busy one, and compiled is far
    more robust to a loaded CPU (the Render shared-core scenario).
  - **Built + validated LOCALLY** (the dev box now has MSVC + cython 3.2.5; Python 3.14 →
    `valuation3.cp314-win_amd64.pyd`) AND in a **`python:3.11` Docker build** matching prod (cython==3.2.5 manylinux
    wheel, cythonize under cp311+gcc → `COST_C[90][5]` identical, the line-39 gate `32 passed` on the cp311 `.so`).
    **No Dockerfile change beyond pinning** `cython==3.2.5` (the builder already `cythonize`s `valuation3.py` + gates
    on `test_h3_valuation`/`test_vsearch`, so this ships automatically). To fold into `heuristics`/main the
    engine_value chain is unchanged between branches, so it applies cleanly. **Still deferred:** the `@cython.cclass`
    Valuation + Cythonizing `mcts.py`/`engine.py` (the ~15–25% per-sim time OUTSIDE valuation3 — the hard ceiling
    on any leaf-only effort).
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
- **Search exploration breadth — TESTED & REJECTED (wash; do not relitigate; June 2026).** Hypothesis
  (from a human who still beats S): "S never CONSIDERS the move that beats me" → widen the policy prior so
  PUCT visits moves H3 dislikes. Two mechanisms, both parked default-off byte-identical: `vsearch.PRIOR_UNIFORM`
  (mix uniform mass: `P=(1-u)*softmax + u/n`, the REAL floor) and `POLICY_TEMP`↑ (flatten the H3 prior).
  **Discovery: the existing `PRIOR_BASE=0.1` is a VESTIGIAL no-op** — it's added to EVERY action's score so it
  cancels in the softmax (softmax is shift-invariant). Self-gate vs frozen-S at sims=200: `PRIOR_UNIFORM`
  0.1/0.25 screened 0.546/0.538 but 0.1 fell to **0.494 on FRESH disjoint seeds** (regression to mean),
  `POLICY_TEMP=1.0` = 0.496, panel a slight wash. **No gain because `mcts._select`'s `_EPS_PRIOR=1e-3` floor +
  PUCT's `sqrt(N)/(1+n)` term ALREADY make every legal move get visited** — dark moves are NOT starved; S sees
  them, evaluates them, and correctly doesn't prefer them at the depth it searches. So the human-exploitable
  gap is **eval-depth/search-budget, not exploration breadth** (and widening breadth at the LOW sims the
  deployed Render CPU runs would only spread the budget thinner). Re-confirms the two remaining live levers:
  search DEPTH (needs a faster leaf/engine → more sims) and the production sim budget. Tooling:
  `config_selfgate.py` (generic config-vs-frozen self-gate, screen → fresh → panel guard).
- **Search-efficiency / "fewer sims needed" (sharper prior) — REAL low-sims effect, but NOT shippable; do
  not relitigate (June 2026).** Idea: a sharper prior concentrates visits faster, so the deployed sims-starved
  S plays better at a fixed (small) budget. Self-gate vs frozen-S **at sims=80** (below the original
  sims=120–160 tuning regime) found **`C_PUCT=1.0` (less exploration) beats the current 1.5**: fresh-seed
  0.531 (consistent with its 0.563 screen) AND panel **+0.025 min, up on all four matchups** (RPS-clean) — a
  genuine, non-artifact win that confirms the principle (when sims are scarce, commit faster). `POLICY_TEMP=0.5`
  (0.49) and `H3_PICK_W=2.5` (0.44) failed even at 80 — it's specifically PUCT exploration, not prior shape.
  **But it's a LOW-SIMS-ONLY win below the deployed operating point:** the maximin tuning already found
  `C_PUCT=1.5` optimal at sims=120–160 and transferring to 400, so there's a **crossover ~80–160**, and the
  deployed box runs ~380 midgame sims (more after Cython) — well above it. Shipping `1.0` globally would help
  only rare very-low-sim moves and HURT the typical midgame → net neutral-to-negative for deployed. The only
  way to capture it is a **sim-budget-conditional `C_PUCT`** (sims unknown until after the search, box speed
  varies — too fiddly for a sub-significant edge). **Verdict: keep `C_PUCT=1.5`; search-efficiency tuning
  saturates at the operating point too.** Transposition caching was dismissed un-tested (determinization
  reshuffles boards per sim → near-zero exact-state hit rate in Splendor's wide state space). Tooling:
  `config_selfgate.py --sims N`.
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
- **Endgame & multi-noble experiments (June 2026) — default-off knobs, committed LOCALLY (`2c27b14`,
  `2da6e4d`), NOT pushed; under test.** Three structural ideas (a human still beats S in their own games),
  each byte-identical at its default and unit-tested (`test_vsearch.py`):
  - **Gap A — `v_state.ENDGAME_TIEBREAK_W` (tiebreak awareness)**: a CROSS-seat leaf term (added in the value
    diff `value_with`/`components`, NOT per-seat STAND) that — gated to near-win + near-tie + differing card
    counts — nudges toward the pts→fewest-cards tiebreak. **DEAD:** wash at sims=160 (0.500/0.502), wash→NEGATIVE
    at sims=500 (0.02=0.500, 0.06=0.465). As predicted: the leaf tiebreak only helps when search MISSES
    terminals, which happens LESS at higher sims (a true terminal already returns the engine's exact
    tiebreak-aware win/loss). Reject. Don't relitigate.
  - **Gap B — `vsearch.ENDGAME_SIM_MULT` / `ENDGAME_SERVE_TIME` (deeper final-round search)**: spend more
    search once `final_trigger>=0` or a seat is within `ENDGAME_NEAR=3` of the win (offline sim multiplier /
    longer serving wall-clock; `_is_endgame`). **Faint wash:** ~0.51-0.53 screen (160 and 500), never clears
    the +0.02 holdout bar, no panel gain. The endgame is too few moves + already near sim-saturation to pay.
  - **Multi-noble — `v_state.NOBLE_MULTI_W`** (the USER's idea): `_noble_stand` counted only the single best
    noble (max over 3); W>0 adds `W*(sum of the OTHER nobles' time-gated standings)` so a position advancing
    2-3 nobles outscores one advancing 1. (Per-card `valuation3.noble_progress` ALREADY rewards multi-noble
    cards via its n-normalized sum; this is its POSITION-eval counterpart, the real gap.) **Implemented +
    unit-tested, NOT YET RUN** (queued behind the sims=500 autotune; don't oversubscribe cores). **Strong
    real-game evidence (a 15-10 loss to a human):** S piled red4/black4 (enough for its one noble n6, +1 spare
    each) but left blue at 2 → finished EXACTLY one blue short of a 2nd noble (n9 = g3/b3/r3), while the human
    balanced w3 b3 g3 r3 and claimed TWO nobles (6 vs 3 = the game's whole margin). The max-over-nobles leaf
    gave S no gradient to balance. **Most promising of the three** — test sims=160 screen → sims=500 confirm.
  - Tooling: `vsearch_selfgate` gained the endgame + `NOBLE_MULTI_W` knobs (finer search-knob grids) + a
    `--knobs` subset filter (full set intact for future full tunes); `config_selfgate._PROBE_KEYS` pins them.
- **sims=500 self-gate autotune (endgame + search knobs) — IN PROGRESS.** Run at the PROD operating point —
  the user flagged that sims=160 tuning may not transfer to prod's ~600 (valid: the documented C_PUCT crossover).
  Screen 240 g/candidate, holdout 600 (CI ±0.04). Interim findings (stable): **`C_PUCT=1.5` confirmed optimal
  at sims=500 — NO crossover above 160** (every alt screens <0.5; the 1.0-best crossover is below ~120 only);
  tiebreak dead; sim-mult faint wash; one **borderline `H3_PICK_W` 1.5→2.0 adoption (holdout 0.524, barely over
  the +0.02 bar; its screen was 0.467 → screen↔holdout inconsistency ⇒ likely noise, and sharper-prior is the
  documented don't-survive family)** pending the final fresh-seed + panel RPS arbiter.
- **Open / next:** finish the sims=500 autotune (treat the H3_PICK_W adoption skeptically — confirm or reject
  via fresh + panel); then run `NOBLE_MULTI_W`. The proven lever remains search DEPTH (sims throughput), not
  eval re-weighting (re-confirmed: every endgame/search re-weight washed at the prod operating point). Parked:
  "search owns DISCARD/NOBLE + a discard prior" (low gain).

### Session (late June 2026) — metric directive, NOBLE_SCALE 3.5, Cython rewrite (ON MAIN), weakness audit

**TUNING METRIC DIRECTIVE (user instruction — SUPERSEDES the MAXIMIN {H3,H2,H2N,H2R} panel described above).**
Judge AI tuning ONLY by **S vs frozen-S** (the self-gate; primary), with **H3 / H3N / H3R** as a strong secondary
sanity panel. **NEVER report or weight H2 / H2N / H2R again** — too weak; weighting them gave misleading verdicts
(e.g. the lower-`NOBLE_SCALE` "wash" was an H2N artifact). H3N = `_AggrH3(2.0)` (noble-heavy), H3R = `_AggrH3(0.4)`
(rusher), built fixed-base off the committed `NOBLE_SCALE` so they don't drift with the candidate;
`config_selfgate.PANEL=["H3","H3N","H3R"]`. These opponents + the rejected-experiment flags below are currently
**UNCOMMITTED on the `heuristics` worktree** (pending a selective finalize), not yet on main. Mirror in memory
`spender-tuning-metric-s-selfgate`.

**NOBLE_SCALE 5.0 -> 3.5 -> 3.0 — SHIPPED (3.5 on `15717fe`; 3.0 on current commit).** Lower-noble S-vs-frozen-S sweep (sims=400, N=350) was a
wash on the self-gate (3.5 fresh 0.516; all values' CIs straddle 0.5); shipped on the user's call (faint-positive
self-gate + H3 +0.025). Affects BOTH H3 and S. COUNTERINTUITIVE H3-panel trade: lower noble HELPS vs a noble-player
(H3N +0.068) and HURTS vs a racer (H3R -0.050) — a racer leaves S's nobles UNCONTESTED, so nobles are an edge vs
racers; the change is matchup-lopsided, not a clean gain. (Supersedes the "3.0->5.0" note above.)

**Cython `engine_value` rewrite — ON MAIN (`f82cc79`, ~1.85-2.74x).** `valuation3.py`'s engine_value chain
(`engine_value`/`_delta_take`/`_cost_scalar` + cost/deficit primitives) is typed-Cython on C int arrays (static
`E.COST/BONUS/PTS` -> module C arrays; per-state bonuses/tokens extracted per call). **Single-source, runs three
ways** (verified): pure Python with cython ABSENT (an `ImportError` shim no-ops the type/decorator constructs;
C-array blocks gated on `cython.compiled`), pure Python with cython installed, and the compiled `.so`/`.pyd` (fast).
The **Dockerfile multi-stage-compiles it** (builder `cythonize` -> `.so`; slim runtime carries only the `.so`; build
FAILS on miscompile, so a bad compile can't reach prod) — so merging the `.py` is enough; prod builds its own Linux
`.so`. Gated byte-identical by the exact-value tests + a differential-parity check. PyPy was tried + REJECTED (slower
+ not bit-parity — numpy in the search hot path goes via cpyext). To prototype eval ideas, hack the readable
pre-Cython `valuation3.py` from git history, then re-Cythonize only the winner.

**Rejected this session (DO NOT relitigate — all judged by S-vs-frozen-S; flags default-off / byte-identical,
uncommitted on `heuristics`):** endgame tiebreak (`ENDGAME_TIEBREAK_W`) + deeper-final-round sims
(`ENDGAME_SIM_MULT`) = noise; the sims=500 autotune's `H3_PICK_W`/`POLICY_TEMP` adopts = noise ratchet (0.480 fresh);
multi-noble position term (`NOBLE_MULTI_W`) = inert; per-card overlap reward (`NOBLE_COUNT_W`) = behaviorally ==
pure magnitude; supply-aware noble gate (`SUPPLY_PENALTY`) = cuts a late-buy "blunder" rate ~11% but washes
win-rate. Re-confirms eval re-weighting is saturated UP **and** DOWN; the lever is search / eval-class, not weights.

**Weakness audit (7 user wins vs S over 4 days, queried straight from the Turso prod DB).** S wins the large
majority vs the user; the losses share ONE dominant cause — **S races too slow / inefficiently**: ~0.75 pts/card
(avg 16 cards, ~12 of them 0-point, ~12 pts) vs the human's ~1.16 (efficient point-cards); the user reaches the win
first in 6/7. Secondary: over-reserve (4/7 end with an unbought 3+pt L3) and a horizon-1 **endgame-denial blind
spot** (1/7, game `IYGWJQ` — `_deny`/`_opp_best_buy` only catch a NEXT-TURN opponent win, missing a 2-turn
reserve-then-buy threat). This cluster is **human-exploitable but tuning-resistant** — S beats the synthetic racers
(81.5% vs H3R) *because* they don't punish it, which is why every weight experiment washed while the human keeps
winning. **QUEUED fix:** a 2-turn endgame-denial horizon (extend `_opp_best_buy`/`_deny`/`_secure_win`; `IYGWJQ` is
the regression test). The deeper "race efficiently" fix is the documented hard lever (search / net).

**Querying the prod DB directly:** Turso creds (`TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`, Render-only) live in a
local gitignored file `C:\Users\Forrest\.spender_turso`; query via `curl` POST to `<https-host>/v2/pipeline` (the
libSQL HTTP API) — no libsql Python wheel needed. Note `list_user_games` excludes `status='over'`, so finished
games aren't listable via the API — query the DB directly for them.

### Session (June 23 2026, `evaluations` worktree — SHIPPED to main with the k6 push, June 24)
**Tuning metric HARDENED + harness trimmed.** Judge AI tuning by **S-vs-frozen-S ONLY** — the H3/H3N/H3R panel is now **opt-in** behind `config_selfgate --panel` (default = sanity + screen + fresh holdout, nothing else; never run the panel unless explicitly asked). `--sanity-n` (default 10 PAIRS = 20 games): frozen-vs-frozen is *deterministically* 0.5 under paired CRN, so a handful confirms the harness is unbiased — don't spend the full `--n` on it. Ported the `_AggrH3` H3N/H3R opponents (were uncommitted on `heuristics`) into the evaluations `h3_vs_h2.py` + `vsearch_camp.py` `OPP` so `--panel` doesn't `KeyError`.

**#4 — seat-aware / bonus-discounted deck demand (`valuation3.DECK_BONUS_DISCOUNT`) — ADOPTED (default True).** `engine_value`'s deck term was seat-BLIND (raw undealt-deck color cost, same for all players). Now seat-AWARE (`_deck_demand_seat`): per undealt card subtract the seat's bonuses (`max(0, cost[c]-bonus[c])`), **normalized by the RAW deck total** — so a color you've fully covered → ~0, the OTHER colors keep their TRUE value, and overall magnitude legitimately SHRINKS as your engine fills in. WON: **fresh 0.5425 vs frozen-S (SHIP)**. The first cut RENORMALIZED (÷ discounted total → sum 1) and LOST (fresh 0.4775): **DO NOT renormalize a bonus-discount** — it inflates the un-built colors (fabricated demand); let magnitude drop, compensate via `ENG_DECK_W` if needed. Only the TOP-LEVEL deck term is seat-aware; `eng_base` (legacy level-0, inside `potential`/`_delta_take`) STILL uses the seat-blind `deck_color_demand` — matches the validated Python path.

**Dev-box Cython + the #4 monolith fix.** Compiled `valuation3` on the dev box (cython 3.2.5 / Py3.14 → `valuation3.cp314-win_amd64.pyd`) so the offline gates run the compiled leaf, not pure Python. **The `.pyd` SHADOWS the `.py` — recompile (`cythonize -i -3 games/spender/ai/az/valuation3.py`) after EVERY `valuation3` edit or workers silently use STALE code** (verify byte-identical via the build-gate tests + a differential `engine_value` signature hash). **Extended the C monolith `_engine_value_h3_c` to handle #4** (it was gated `not DECK_BONUS_DISCOUNT`, routing #4 to the slow Python path). FOOTGUN: the monolith fed ONE `dcd` vector into BOTH the inner `_eng_base_c` AND the top-level deck term; a naive single-vector swap to seat-aware broke byte-identity (**0.077 error**) because `eng_base` must stay seat-blind. Fix = TWO vectors — `dcd` (seat-blind → `_eng_base_c`) + `dcd_top` (seat-aware → the top-level `ev += dcd_top[bcol]*deck_w` only). Byte-identical confirmed (sig match + max-diff 0.000 + 32 tests).

**REJECTED this session (all S-vs-frozen-S; flags default-off / byte-identical):**
- **`heuristic3.TEMPO_TURNS_SCALE`** (late-game tempo-weight scaling off measured turns_remaining): WASH (fresh 0.5012). Time is already carried by the `compound_turns` engine horizon; re-penalizing tempo in the cost denominator is redundant.
- **Progress breadth — PARTLY SUPERSEDED, see the June 24 "k6" block below.** `v_state` gained `PROGRESS_TOPK`/`PROGRESS_DECAY` (cascade-weighted progress over the top-K take_values; `W_PROGRESS` now a probe key) — `_progress` was a top-2 mean, blind to ~10 reachable cards. The cascade "winner" (top-5, W=3.4, fresh 0.5275) was a **CONFOUND**: the true magnitude-match for flat top-5 is **W=2.92, not 3.4** (measured take_value means: top-2 ≈1.93, top-5 ≈1.65, top-8 ≈1.48), so it ran ~16% extra progress weight. At TRULY matched magnitude, **k=8 WASHED** (flat W=3.26 fresh 0.5038) — so breadth *at matched magnitude* is NOT a lever, and *pure* magnitude (top-2 + W∈{2.7,2.9}) also went sub-0.5. **The June-24 follow-up found the real effect is the INTERACTION** — breadth (K≈4–6) AND over-magnitude (~1.16–1.3×) *together* give ~+4pp; neither alone does. (Magnitude-compensation is MULTIPLICATIVE: progress contribution = `W_PROGRESS × mean(top-k)`; match the PRODUCT — `W = 2.5 × baseline_mean / new_mean` — not the mean.)
- Built-but-unrun: `valuation3.DECK_STAGE_TILT`/`DECK_STAGE_T0` (level-realization tilt of the deck term — the "L1 over-counted, never shifts to L3" idea) and an asymmetric-progress idea (top-1 for the side-to-move, top-2 for the waiter — bakes denial/tempo into the leaf).

**Game-replay limitation (found analyzing a real loss — LBBMRC, lost 14–20 to S: led on points but ignored the noble race; S swept 3 nobles).** Per-turn `v_state` CANNOT be reconstructed for EXISTING games: the saved game stores only the FINAL board/deck + an id-only move log — NOT per-turn board snapshots NOR the initial deck order/seed — and `progress` needs the board each turn. **To make FUTURE games replayable** (and re-scorable under any eval variant): in `main.py` store an initial `setup` snapshot (shuffled deck order + board + nobles) at game creation (`_deal_board` mutates `decks` in place; no seed is saved), AND **log `discard` moves** (the human `discard` path + `_ai_discard_one` aren't logged → token counts drift on replay). Then replay = rebuild from `setup` → re-apply the log → `from_game_dict` → `v_state.value` per ply. NOT yet implemented.

**Ops — gates kept dying with exit 127 = OOM.** Root cause: an ORPHAN PILEUP — a failed `mp.Pool` run leaves worker processes alive that eat RAM → the next gate OOMs → more orphans (vicious cycle). **Reap `C:\Python314\python.exe` procs before each gate.** Run gates with **`SPENDER_AZ_MODEL=none`** (the self-gate uses S/H3, NOT variant Z — skips the per-worker `az_model.npz` load, a big memory saver). The box is ~16GB but often <1GB free (VS Code + Firefox) and **CPU-bound at ~10 of 12 cores** (more workers don't help). **Don't edit `az/` modules while a gate runs** (Windows `mp` spawn re-imports → BrokenPipe crash). Remaining speed levers (diminishing — leaf already compiled): naive-cythonize `mcts.py`+`engine.py` (~10–15%), then `@cython.cclass` Valuation (~1.3–1.4×, large rewrite); past that, a bigger box (CPU-bound).

### Session (June 24 2026) — k6 progress adoption + past-S checkpoints (SHIPPED to main)
**k6 — `v_state` PROGRESS_TOPK 2→6 + W_PROGRESS 2.5→3.54 — ADOPTED + DEPLOYED.** This REVERSES the
June-23 "breadth is not a lever" conclusion: breadth IS a small lever, but **only paired with an
over-matched magnitude** — the INTERACTION the prior session missed by testing each axis alone. An
overnight K×magnitude grid (sims=500) then a **fresh disjoint-seed confirmation** found a coherent
ridge peaking at **K≈4–6, magnitude ~1.16–1.3×M0**: k4@1.30× and k6@1.16× both held ~0.54 across
seed bases; k3 (too little breadth) and k5@1.30× (too much magnitude) fell off. `PROGRESS_DECAY`
stayed **1.0** (plain mean) — the cascade/decay shape was a confound, not the lever. Evidence (all
S-vs-frozen-S unless noted): self-gate **0.543 / 0.545 / 0.531 across THREE disjoint seed bases**
(pooled ~0.540, the third-seed pullback says the true effect is the LOW end, ~+4pp); **H3/H3N/H3R RPS
panel PASS** (worst matchup +0.018, no exploitation — slight −0.017 vs racer H3R, +0.033 vs noble
H3N, the documented progress-helps-vs-noble pattern); **past-selves panel ≥0.5 vs all** (0.579 vs
frozen, 0.591 vs s_original, 0.574 vs s_pre_progress, **0.500 vs s_noble_heavy**, avg 0.561 — never
loses to a style, worst case a tie vs the noble-lean). A real, robust, SMALL gain — eval-weight
tuning remains otherwise saturated; this snuck through as a structure (breadth)×magnitude combo.

**Past-S checkpoint system — NEW offline tooling (`s_checkpoints.py` + `s_vs_checkpoints.py`).** S has
no weight file; its "weights" are module constants. A **checkpoint** = a JSON snapshot of all **90
strategy constants, PER-MODULE** (so dup names like `NOBLE_TURN_W` in both v_state & valuation3 are
unambiguous) across v_state/vsearch/heuristic3/valuation3; serving/infra (`SIMS`/`SERVE_*`/caps) are
excluded. Small, **committed** JSON in `games/spender/ai/az/s_checkpoints/` (NOT gitignored, unlike AZ
weights); each stamps git commit + timestamp.
- **`s_checkpoints.py`**: `snapshot`/`save`/`load`/`apply_config` + **`reconstruct <commit>`** (overlay
  a past commit's constant values on today's full snapshot — keys absent then keep today's default) +
  **`derive --set K=V`** (today + targeted overrides) + CLI (`save`/`list`/`show`/`reconstruct`/`derive`).
- **KEY semantic (do not misread):** a checkpoint reproduces "that era's WEIGHTS on TODAY's code" — a
  reproducible **STYLE**, NOT a bit-exact old S. So every newer feature (#4, the Cython leaf, structural
  fixes) is present and ON in all past selves; they differ only in the weight LEVERS that existed and
  were set differently. Intentional: we want strong, same-strength, style-DIVERSE sparring partners
  (resurrecting old code would just give a weaker S). Confirmed e.g. `s_original` carries pre-maximin
  `W_ENGINE_STK=0.8`/`C_PUCT=2.0` but `DECK_BONUS_DISCOUNT=True` (too new to exist at da18bab).
- **`s_vs_checkpoints.py`**: panel-of-past-selves runner — protagonist (live ± `--set`) vs a set of
  checkpoints via the **per-turn config swap** (the ONLY safe way to run S-vs-S with two configs sharing
  module globals: re-assert each side's full config before its move). Paired CRN, parallel. Validated:
  `live vs its-own-checkpoint = 0.5000 EXACTLY`.
- **Purpose + CAVEAT:** a same-strength, diverse **RPS guard** the H3 panel can't be (S beats the
  heuristics ~80% regardless, so 75-vs-80 is saturated) + a progress tracker. It does **NOT** probe a
  brand-new knob's OWN axis (every checkpoint has `PROGRESS_TOPK=2` — topk is newer than every commit),
  so it tests a candidate vs diverse *other-lever* styles, not vs topk variety; k6's real validation was
  the self-gate + H3 panel, the past-selves run a bonus robustness check. **Value compounds — save a
  checkpoint on every adoption.** 5 committed: `s_2026-06-24` (pre-k6 baseline), `s_2026-06-24_k6`
  (ADOPTED/deployed), `s_original` (da18bab), `s_pre_progress` (fb813cf^), `s_noble_heavy` (today+NOBLE 5.0).

**Forward direction the user raised: build the panel from S-strength diverse opponents** (past-S
checkpoints + future "S-rusher"/"S-nobler" derived variants), and consider an **"S-lite" playable tier**
(depth-2 or tiny-sim search) as a strong-but-instant opponent given the heuristics are too weak and the
deployed S is sims-starved on Render's 0.1 CPU.

### Session (June 24 2026) — over-reserve deep-dive + game-loss trace-back (DIAGNOSIS, nothing shipped)
Investigated one real game a strong human WON vs deployed S (`YINAIM`, dumped from Turso). Three durable
conclusions; DO NOT relitigate:
- **Over-reserve "fix" — TWO mechanisms TESTED & REJECTED (neither converts through search).** Symptom:
  S over-reserves, filling all 3 slots with cards it never converts → at YINAIM turn 50 it had 3/3
  reserves and could NOT reserve-deny the human's winning L3-6 (a public, affordable board card). Built
  on a local **`reserve-slots` worktree branch (default-off, byte-identical, NOT merged):** (1)
  `v_state.W_RESERVE_SLOTS` — a position-leaf free-slot **optionality** term (concave `O(eff_free)`,
  `eff_free = 3 − Σ deadness(held reserves)`; deadness from **`valuation3.tempo`** = the STEEPEST
  single-color remaining need so 6-of-a-color reads far / 2+2+2 near — a raw gem-SUM misses steepness;
  NEAR_T=1/FAR_T=6 turns; horizon-faded; symmetric). (2) `vsearch.RESERVE_DISCOUNT_W` — discounts a
  reserve ACTION's prior by `deadness(card) × load` (far reserves already held) so the 1st speculative
  reserve is free and the cost escalates as you stack far ones. **Both wash:** W_RESERVE_SLOTS self-gate
  ≈0.5 and the move never flips even at high W; `RESERVE_DISCOUNT_W=8` self-gate **0.455** (sims=500,
  n=100) and even a ~90% prior cut does NOT flip the reserve move. **Why: the reserve's Q (denial +
  acquisition of a 4-pt L3) is genuinely high — a modified static leaf OR prior can't beat it through
  search** (re-confirms the documented "doesn't convert through search" wall). Also the self-gate MIRROR
  is structurally blind to a slot-lock cost (both copies over-reserve; neither races to exploit the
  other's full slots — only a human/exploiter would). Knobs parked default-off on the branch as
  NET-feature candidates; not merged. (NB H3 itself has `USE_SPECULATIVE_RESERVE=False` — the
  over-reserving is the SEARCH PRIOR's `RESERVE_PRIOR_W*take_value`, not H3 greedy.)
- **MCTS mean-backup is blind to a sharp 1-ply opponent threat until more sims / the opponent commits
  (quantified).** YINAIM's winning L3-6 was public + affordable + exactly 1 ply ahead, yet S's searched
  value the turn before was **+0.033 at 600 sims, −0.552 at 3000 sims** (true ≈ −0.45). Not hidden-info
  / not horizon — the root value is a visit-weighted MEAN that dilutes the single sharp reply among the
  opponent's explored weaker replies; depth (or the opponent actually playing it next ply) converges it.
  Reinforces the rejected mixmax/`BACKUP_LAMBDA` and that **search THROUGHPUT (faster leaf → more sims)
  is the lever, not a backup tweak.**
- **Trace-back self-play diagnostic → real games are lost in the EARLY-MIDGAME, not at the visible late
  symptom.** Reusable diagnostic (scratch `trace.py`, built on `replay.py`): for each historical turn T,
  play N self-play games (both seats frozen-S, remaining deck reshuffled per game) from that position to
  the end, record seat-0 win-rate, walk T back to where it was last ~0.5. **Validated unbiased** (fresh
  `new_game` seat-0 = 0.53 first-player edge; 5/5 distinct lines from a position = real variance, not one
  deterministic game — so the win-rate is meaningful, addressing the "they play the same game every time"
  worry). On YINAIM (N=80, sims=256): S started **even/slightly-favored** (turn 0 = 0.53), held ~0.5
  through **turn 8**, then slid **0.48 → 0.16 over turns 9–14** (early-midgame engine race), bleeding from
  there to the turn-50 corpse. **No single blunder — a gradual out-building.** The over-reserve /
  slot-lock / can't-deny-L3-6 at turn 50 were all DOWNSTREAM symptoms of a position already lost ~13 plies
  earlier. **Conclusion: the lever is early-midgame DEVELOPMENT TEMPO (build a faster/more-efficient
  engine) — not reserves, denial, or the endgame.** That's the hard eval/search lever, not a knob.

### Variant S — Rust→WASM client-side serving (the sims-throughput rewrite; DEPLOYED June 2026)
The proven #1 lever is **sims/move**, and deployed S was sims-starved on Render's 0.1 shared CPU
(~380/move). So variant S's **entire search core was rewritten in Rust → compiled to WASM → runs in
the PLAYER'S browser** (their real CPU, root-parallel across cores), for ~100× more sims, free. Full
detail + resumption state: memory **`spender-rust-search-rewrite.md`**. Don't relitigate the parity
methodology or the saturation findings without reading it.
- **Crate `spender-core/`** (top-level, ON MAIN since `80d4f67`; built in the `forrestm_projects-rust`
  worktree / branch `rust-search`). Pure-Rust port of `engine`/`valuation3`/`heuristic3`/`v_state`/
  `vsearch`/`mcts`/`turns` + `cards` (generated by `tools/gen_cards.py`) + `actions` (action→move-dict
  bridge). `src/wasm.rs` = the `#[cfg(target_arch="wasm32")]` entry points; `src/bin/{bench,move_server,
  simgate}.rs` = offline tooling. **Validated:** engine bit-exact (15.4k steps), v_state leaf 1e-9,
  policy `choose_action` exact (800 cases), move bridge exact (7019), and **Rust-S vs Python-S = 0.5025
  ± 0.069 over 200 games** (the search plays equivalently). `cargo test` (10 suites) + `tools/gen_*_
  fixtures.py` regenerate the differential fixtures (gitignored). **Cross-worktree: always `cd
  forrestm_projects-rust` before `cargo`/`wasm-pack`; rustup is at `~/.cargo/bin` (prepend to PATH).**
- **Throughput:** native ~68k sims/s, WASM-in-V8 ~55k (after the perf round below) vs Render ~85-200.
  WASM ≈ native. So a browser worker does ~250k sims/move at the 4.5s budget; ~4× that aggregated across
  the root-parallel pool.
- **Serving = client-side, server stays authoritative (gated, zero-regression).** Backend (`main.py`,
  behind a per-room **`client_ai`** flag): on the AI's turn `mk_room_state` ships **`ai_search`**
  `{state, seat, sims, ply}` (the AI-perspective compact state via `_compact_state_dict`); WS actions
  **`client_ai_ready`** (arms the room) + **`ai_move {move}`** (validates the move is LEGAL via
  `actions.move_to_action`∈`legal_actions`, then `_run_ai_turn` — which does the cheap discard/noble
  FINISH server-side); `_schedule_ai_turn` waits `CLIENT_AI_TIMEOUT`=6s for the client, else computes
  the FALLBACK itself. Absent a WASM client it's byte-identical to before. Only variant **S** is ported
  (other variants stay server-side). Frontend (`Spender.jsx`): a pool of module Web Workers
  (`webapp/public/wasm/s-worker.js` + the wasm-pack `--target web` glue + `.wasm`, all in
  `webapp/public/wasm/`), root-parallel — each worker runs an independent determinized search (distinct
  seed), the main thread SUMS root visit vectors → argmax → `action_to_move_for` → submits `ai_move`.
  Graceful fallback (no module-worker / wasm load fail → never arms → server computes). **Trust:**
  client-side AI is sound for vs-AI (tampering only weakens the player's OWN opponent).
- **Time-budgeted + sims-capped.** Each worker searches a **4.5s** wall-clock budget OR a **per-worker
  sims cap** (`CLIENT_AI_MAX_SIMS=100000` in Spender.jsx → `search_visits_timed(…, max_sims, …)`),
  whichever first. The cap **bounds browser-tab memory** (~1 node/sim; 4×250k-node trees ≈ 1.4GB was a
  mobile-OOM risk → cap → ~580MB) and makes fast devices snappy (~2s). **The cap is BROWSER-ONLY** — it
  lives in Spender.jsx→worker→the wasm `search_visits_timed`; the offline bins (`bench`/`simgate`/
  `move_server`) call `vsearch::choose_action(…, sims, …)` with the explicit, UNCAPPED sim count. Pool
  size = `min(navigator.hardwareConcurrency, 4)`.
- **PERF: per-Valuation leaf memoization ~2.6-3× sims/s (DO NOT remove).** Profiling (`SP_NOLEAF`/
  `SP_NOVALUE`/`SP_NOPOLICY` env probes in the vsearch eval) showed **the V leaf is ~95% of search time**
  (machinery ~2.3µs/sim). The Rust port had OMITTED the Python's memoization, so the cross-card
  `engine_value` chain recomputed O(cards²)×. Added per-`Valuation` caches (byte-identical — store/return
  the exact f64; all parity tests pass): `eng_base`/`cost_scalar`/`delta_take`/`engine_value`/`tempo`/
  seat-aware `deck_demand_seat` + `heuristic::components`, + a thread-local `turns` memo + fixed-array
  MCTS Node. `deck_demand_seat` (an O(deck) loop recomputed ~16×/leaf) was the single biggest win. After
  this the leaf is balanced (value ~3.7µs, policy ~4.4µs) with NO dominant chunk — **caching as a speed
  lever is EXHAUSTED at ~3×; SIMD won't vectorize the 5-element per-color loops.**
- **Deploy flow:** `cd forrestm_projects-rust/spender-core && wasm-pack build --target web --release
  --no-typescript`, `cp pkg/spender_core.js pkg/spender_core_bg.wasm ../webapp/public/wasm/`; the wasm +
  `s-worker.js` + `Spender.jsx` are FRONTEND files → push to `main` → gh-pages (smoke-gated). A `main.py`
  change deploys to Render (its path filter); **`spender-core/**` is in NEITHER CI path filter** (no
  deploy from the crate). Backend-before-frontend ordering when both change (else a new client hits an
  old backend → transient "unknown action"). **LIVE + user-confirmed working on forry4.github.io.**

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
- **Move log = id-only + a static catalog (June 2026; `e4beb19`).** `_log_move` stores only
  `card_id` per buy/reserve (+ `noble_id` on noble claims), NOT the full card dict — entries are now
  ~one short string, so the **50-cap was raised to 500** and `game["moves"]` holds the WHOLE game (and
  every `room_update` WS payload shrank). Resolve ids via `main.card_catalog()` (deterministic
  id→{level,points,bonus,cost} for all 90 cards; the deck is fixed). Frontend: a `cardsById` useMemo
  built from visible state (board + both players' purchased/reserved) resolves the log ids — complete by
  construction (a logged card is always somewhere in the live state). **Backward-compatible**: old saved
  games carry verbose `mv.card`, new ones `mv.card_id`; `renderMove` reads `mv.card || cardsById[mv.card_id]`.
  Clickable condition is now that-resolved-card. **Blind-reserve redaction strips `card_id` too** (the id
  alone reveals the hidden card via the catalog).
- **Admin game-dump endpoint `GET /games/{id}/full`** (admin-gated): returns the complete persisted game
  (final state + full id-only move log) + a `card_catalog`, a self-contained dump for offline analysis
  (prefers the live in-memory copy, falls back to the DB row). Prod data lives in Turso (no local access),
  so the workflow is a browser console snippet that reads `spender_roomId`+`spender_user.session_token`
  from localStorage, fetches the endpoint, and downloads the JSON (clipboard `copy()`/chat-paste choke on
  the ~20-30KB blob → download-to-file + Read is the reliable path). Used to analyse real vs-S games.
- **Game reconstruction + per-turn S re-scoring (`games/spender/ai/az/replay.py`; June 2026).** A finished
  game can be replayed move-by-move offline and re-scored with variant S at every turn. Two additive,
  default-safe captures made this possible (without them the per-turn board — S's biggest eval input — was
  unrecoverable, because the deck is shuffled in place and popped with NO seed stored):
  1. **`main._capture_setup(g)`** snapshots the dealt **initial board / deck-order / nobles (ids only)** into
     `g["setup"]`, called in BOTH create paths (vs-AI + multiplayer start) right after the nobles are dealt.
     ids-only → compact; resolved via `card_catalog()`. **Kept off the wire** — `mk_room_state` strips
     `setup` from the broadcast (static, client-unused, ~75 ids), but `save_game` persists it and the `/full`
     dump serves it. (No new info leak: `game["decks"]` — the remaining draw order — is already broadcast.)
  2. **Discards are now logged** (`_log_move(... "discard", color=...)`): the human handler logs on COMMIT
     (an `undo_discard` restores the pre-take snapshot, so the entries correctly vanish), and the AI path
     logs each `_ai_discard_one` — which now **returns the discarded colour** (the MCTS-sim applier ignores
     it). The primary `take_gems`/`reserve` is logged BEFORE its discard loop so the newest-first log
     reverses to correct chronological order. (Buys never overfill; payment/spends stay derivable.)
  - **`replay.py`** rebuilds the initial game dict from `setup`, re-applies the logged moves (payment via
    `calc_spend`; turn advancement reuses `main._finish_turn`; nobles applied straight from the log, single
    auto-claims included), converts each turn-start to an AZ `State` via `engine.from_game_dict`, and emits
    `v_state.value` + the 5-component breakdown. CLI:
    `python -m games.spender.ai.az.replay dump.json [--seat ai|mover|0|1] [--csv out] [--json out]` (loads a
    `/full` dump, a `state_json` row, or a bare game dict). **2-player only** (v_state is). A game created
    BEFORE the snapshot (LBBMRC, all pre-deploy prod games) has no `setup` → `evaluate` raises a clear error;
    only the points+noble proxy is available for those. Every game created after deploy is fully replayable.
  - **Test** `games/spender/tests/test_replay.py`: a **differential round-trip** — play random AZ games, emit
    the log in main's EXACT persisted format (synthesizing the silent single-noble auto-claims + deck-reserve
    `card_id`/`from_deck`), reconstruct from `setup` alone, assert the replayed state matches the engine at
    every turn with **deck order compared exactly** (60 games) + direct guards on each `main.py` change.
- **In-game review + turn-by-turn replay (the game-review feature; June 2026).** Every game in the lobby
  **History** column has a **Review** button (right of the score) that opens a READ-ONLY review of that game
  where you can rewind to any turn. Builds directly on `replay.py` (above).
  - **Backend — `GET /games/{id}/review`** (`main.py`; session-gated AND restricted to a player who was in
    the game — `viewer in game["order"]`). Returns `final` (the end board, redacted-from-the-viewer +
    `setup`-stripped via `_review_view`) + `snapshots` (one renderable game dict per turn, from
    `replay.reconstruct` → `replay.turn_snapshots`, each redacted via `_review_view`). `snapshots` is **null**
    for a game created before the `setup` snapshot (review still shows the final board, just no turn nav) or on
    any reconstruction glitch — `_build_review_snapshots` swallows `ReplayError`/anything. Loads in-memory
    first, else the DB row (mirrors `/full`). **Player-count-agnostic** (only `replay.evaluate`/v_state is
    2-player; reconstruction isn't), so multiplayer games review too. Does NOT need numpy/AZ. Test
    `games/spender/tests/test_review.py` (pure helpers + an endpoint e2e is in scratchpad, not committed).
  - **Frontend — read-only replay mode (`Spender.jsx`).** `enterReview(id)` does an HTTP fetch (NO WebSocket;
    synthesizes `roomData` from `final`) for a History entry; the end-game "Review Board & Log" button also
    calls `enterReview(roomId)` (the `haveLive` path keeps the live socket, just adds snapshots). State
    `reviewing`/`replaySnapshots`/`replayTurn` is declared **BEFORE the derived `game` block** (TDZ — same
    hard rule as the other derived state). `liveGame = roomData.game`; the **BOARD** renders
    `replaySnapshots[replayTurn].game` (or liveGame), but the **move log + `cardsById` stay sourced from
    liveGame** so every turn stays clickable and logged cards resolve even on an early board.
  - **Read-only is enforced, do not regress:** `myTurn`/`aiThinking`/`needsDiscard`/`needsNobleChoice` are all
    gated `!reviewing`, and the fly/flash `useEffect`s early-return on `reviewing` (no spurious animations
    while rewinding). Nav chrome uses **`reviewChrome = reviewing || liveGame.phase==="over"`** (the LIVE
    game's phase, NOT the rewound snapshot's) so a historical `"playing"` snapshot can't leak the live
    Abandon/Menu chrome. The visibility/tab-back reconnect is also gated `!reviewing` (a History review has no
    socket to reconnect).
  - **Snapshot semantics (the load-bearing index rule): `snapshots[idx]` is the board AFTER move `idx-1`** —
    idx 0 = the initial board (before anyone moved), idx N = the final position. The log (newest-first) renders:
    an **unclickable** `🏆 X won the game` label at the top (derived from `game.winner`; ties → "A & B tied"),
    each **move row** jumping to `goToTurn(turnIdx + 1)` (the board AFTER that move) and highlighting **only its
    PRIMARY row** (`take_gems`/`buy`/`reserve`) so a buy-plus-noble turn lights ONE row, and a clickable
    `▶ Game started` at the bottom → `goToTurn(0)` (the initial board). The action-bar banner
    (`renderReplayBar`) describes the move that PRODUCED the shown board (`snapshots[idx-1]`): `Game start` /
    `Turn k / N · {mover} · {move}` / `Final position`, with Prev/Next/Latest.
- **Loading screen**: 250ms fast-path — AbortController fetch with 250ms timeout;
  if server responds in time → skip loading screen entirely; if not → show spinner
  + progress polling. `showLoading` state gates the spinner so a blank flash never
  appears on fast connections.

### Multiplayer (2-4 players), History & 3-column lobby (June 2026 — LIVE on prod)
- **Spender seats 2-4 humans** (AI games stay 2-player). The engine was already
  player-count-agnostic (`game["order"]` + modular `_advance_turn` + single-winner
  `_resolve_winner` with the points/fewest-cards tiebreak); the additions are setup +
  plumbing: `MAX_PLAYERS=4`; `_bank_for(n)` scales the gem bank to standard Splendor
  (**4/5/7** per colour for 2/3/4p, gold always 5) at START; nobles already `players+1`.
  `join` accepts up to 4 for **OPEN, non-AI lobbies only** (rejects joining an AI game or
  an already-started game). The host starts when **≥2** present (the existing `start`
  flow). DB gained nullable **`player3/4_id`+`player3/4_name`** columns (in CREATE for
  fresh DBs + a tolerant ALTER for the prod table); `save_game` / `list_user_games` /
  `list_active_games` handle all four seats. Tests in `test_game_logic.py`
  (`_bank_for`, nobles, 4-seat turn cycle, single winner among 4, final-round around all
  seats). Dormant-safe: the backend shipped to prod first, invisible until the frontend.
- **History** — `GET /games/history` → `list_user_history(user_id)`: your FINISHED games
  (`status='over'`, any of the 4 seats), newest first, each with per-player final scores
  (`_calc_points`), a winner flag, `is_you`, and `you_won`. Session-gated (like
  `/games/mine`). Frontend renders **"Won/Lost vs <opponent(s)>  your-their"** (no
  repeated username; "their" = the top opponent's score for 3-4p). Retained 30d for a
  registered player (guest-only 24h), per `cleanup_stale_games`.
- **3-column lobby** (`.lobby-grid` = `grid-template-columns:1fr 1fr 340px`): **Open
  Games | Active Games | History**, each its OWN column so a long History never pushes
  Active down. **Explicit `grid-row` on EVERY item is REQUIRED (do not regress):** the
  DOM order is Open, History, Active, so column-only placement makes the sparse auto-flow
  cursor (past col 3 after History) wrap Active to row 2 ("pushed down"). Each column's
  `.game-cards` is **capped to the viewport and scrolls internally like the move log**
  (`max-height:calc(100vh - 230px);overflow-y:auto;scrollbar-gutter:stable`) — desktop
  3-col only. Collapses to 2-col <1280px (History spans row 2), 1-col <780px. **Active
  Games ALWAYS renders** (with a "No games in progress." empty-state) so the middle
  column never gaps.
- **Open Games** show the lobby size **`x/4`** (`list_open_games` returns `player_count`
  + `max_players`). **Active Games** list each player **one-per-line** (`.matchup`,
  you first then `vs <opp>` per line). The Classic/Long + Create + vs-AI button row is
  **centered** (`.browser-create{justify-content:center}`); the refresh button is a
  **fixed 30×30** box so the ↻↔spinner swap doesn't resize/shift it.
- **Full-width banner (flush, do not regress):** the lobby header lives OUTSIDE the
  centered max-width `.browser` (a direct child of `.app`) so its border spans the
  screen — three sections, **back left / game name centered / user right** (left+right
  `flex:1`, title `flex:0`). Same for CoC (`.coc-top-lobby` moved outside `.coc-wrap`).
- **Home-exit button reads "← Back"** everywhere (Spender / CoC / Where Wolf? / Books);
  in-game "← Menu" / "Back to lobby" buttons are unchanged (they navigate within a game).

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
**The DESKTOP portion below is SUPERSEDED by the June 25 2026 proportional rewrite (next
section): the fixed `1fr 560px` grid, the `132px` bank, the `≈144×185` cards, and the
max-height breakpoints described here are GONE — desktop now scales from one `--card-h`
anchor. The TABLET/PHONE parts (`max-width:900px` / `600px`) still apply unchanged.**
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
- **Tablet/phone (`@media(max-width:900px)`)**: single column; the nobles and an
  **actions box** sit side by side as TWO SEPARATE boxes — `.nobles-panel.panel` goes
  transparent (just a flex row), `.nobles-row` gets its own tight box hugging ONLY the
  nobles, and `.board-actions` is the box to its right holding the win-points **Target**
  label (`Target: 15/21`; `justify-content:flex-start` pins it to the TOP so it doesn't
  shift up when the Take/Buy/✕ buttons appear below it) + the controls. The hint is
  dropped here (no room beside the nobles); the box is only rendered while
  `game.phase !== "over"`. **Cascade gotcha (do not regress):** the mobile rules use
  higher-specificity selectors (`.nobles-panel .board-actions`, `.nobles-panel.panel`)
  because the unconditional base `.board-actions{display:none}` / `.panel{…}` rules
  appear LATER in the stylesheet — at equal specificity they'd win, and
  `.board-actions{display:none}` had been hiding the actions box on mobile ENTIRELY.
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

### Proportional desktop layout rewrite + searched-eval / review overlay (June 25 2026 — do not regress)
The desktop game layout was rewritten to be fully PROPORTIONAL (supersedes the desktop part
of "Responsive game layout" above), and the admin S position-eval overlay gained a SEARCHED
value + now works in game review. All frontend in `Spender.jsx`; backend in `main.py` /
`ai/az/vsearch.py`. Live on staging AND prod.

**Proportional desktop (`@media(min-width:901px)`):**
- **One anchor drives everything: `--card-h:clamp(104px, 17vh, 205px)` on `.game`**, with
  `--card-w:calc(var(--card-h)*0.778)` (the prod 144:185 card aspect). EVERY desktop
  dimension is a `calc()` ratio of `--card-h` (ratios = old-full-size-px / 185), so the
  whole board scales as ONE unit and looks identical at 1280×720 / 1920×1080 / 2560×1600
  (clamp only floors/caps on extremes). This REPLACED the old fixed `1fr 560px` grid +
  `132px` bank + `≈144×185` cards + FIVE max-height breakpoints that STEPPED the board in
  discrete jumps (so it looked different per resolution).
- Grids: `.game` = `minmax(0,1fr) clamp(440px,32vw,560px)` (board | sidebar); `.game-main`
  = cols `auto 1fr calc(var(--card-h)*0.714)` (nobles | cards | vertical bank), rows
  `auto 1fr`; sidebar = `1.6fr 1fr` (players | log). The definite-height + `minmax(0,1fr)`
  chain on `.game` AND `.game-sidebar` (+ the move-log `max-height` belt) from the old
  section STILL applies — keep it (same clipping footgun).
- **Per-level card boxes:** each level row is wrapped in a `.level-panel` (a `.panel`,
  `flex:1`) so the three levels are individually boxed AND fill the column height; `.levels`
  packs them at the TOP with a fixed proportional gap (`justify-content:flex-start`), so
  spare viewport height becomes whitespace BELOW — NOT bigger inter-level gaps (uniform gaps
  were a hard request). Board cards hold a strict 0.778 aspect via a container query on
  `.level-row` (`container-type:size`, `width:min(slot, 100cqh*0.72)`) — true contain, no
  overflow. **Gotcha (do not regress): container-query units (`cqw`) on the RESERVED cards
  blew up the flex-basis circularly** (309px-wide cards); reserved cards use a plain
  `flex:0 0 calc((100% - …)/3)` + `--card-h`-relative content + `width:100%` on
  `.player-reserved`/`.reserved-row`, NOT a container query.
- **Player pills (the hard rules the user enforced):** gems (`.token-pill`) AND card
  indicators (`.bonus-pill`) are each fixed at **1/6 of the row** (`flex:0 1 calc((100% -
  …)/6)`) so a full set of 6 fills the row edge-to-edge; capsule-shaped
  (`border-radius:999px`), prod-shaped but BIGGER (height + dot/count, NOT just wider); the
  "N gems" total (`.gem-total`) is centered between the two rows. **Reserved cards are fixed
  1/3 of the row** (3 fill it, fewer left-aligned NOT stretched), 0.778 aspect, cost/pts/
  color sized to match the board cards' ratio.
- **Eval pill top-right:** the S position-eval pill (`.ai-pos-eval-row`, rendered by
  `renderAiEval` — split out of `renderAiValsToggle`, which is now just the Hide/Vals
  button) is `position:absolute` at the top-right of the actions box (the box is
  `position:relative`: `.actions-panel` desktop / `.nobles-panel .board-actions` mobile) so
  it never displaces the Target / buttons / hint. "Show vals" button label is just "Vals".
- **Layout-verify harness** (`webapp/_harness.mjs`, gitignored scratch — NOT committed): a
  Playwright script that extracts `baseCss` + the game `css` from the two backtick template
  literals, builds a MOCK game DOM (must include the `.level-panel` wrapper or per-level
  boxing/gaps measure wrong — a real bug this caught), renders at the target viewports, and
  measures + screenshots proportions / row-fit. The fast way to verify a layout change
  without a live game; row-fit must be measured by element CENTER, not `top` (buttons of
  different heights on one row have different tops). `npm run smoke` still gates blank-page
  / CLS on every push (run it in `webapp/` before pushing).

**Admin S overlay — searched eval + game review (`main.py` / `vsearch.py`):**
- The admin position-eval pill shows BOTH **`leaf`** (static `v_state.value`) AND **`srch`**
  (S's PUCT search ROOT value `sum(W)/sum(N)`, side-to-move perspective). `vsearch` gained
  `_root_value(search)`, `choose_action_value(s, seat, …)→(action, root_value|None)`, and
  `searched_value(…)`.
- The searched value costs NOTHING extra on the AI's turn and is fresh on yours: (1) the
  AI's move already searches → `_s_choose_move` uses `choose_action_value` and stores the
  root value; (2) on the HUMAN's turn `_schedule_s_searched_eval` runs a fresh `SERVE_TIME`
  (~4.5s) async search in the thread pool (guarded ONCE-per-ply via a `_s_eval_running`
  marker) and broadcasts. Both stamp `game["s_searched"]={value, ply}`; `mk_room_state` only
  emits `ai_position_eval_searched` when `s_searched["ply"] == len(game["moves"])` (a stale
  eval is never shown — the ply fingerprint validates the position). `s_searched` / `setup`
  / `_s_eval_running` are stripped from the broadcast game view.
- **Vals work in game review:** `_compute_overlay(game, persp, variant)` was EXTRACTED (per-
  card values + the static `ai_position_eval`, dispatching H/H2/H3/S; `{}` on exception) and
  is reused by BOTH `mk_room_state` (live) and `_build_review_snapshots` (per PLAYING past
  snapshot, computed from THAT turn's mover's seat) — so rewinding a finished AI game shows
  each turn's per-card values + static eval. STATIC only (no per-snapshot search → `srch` is
  hidden in review; one search per snapshot would be far too slow). Frontend:
  `aiCardValues` / `aiValuesPid` / `aiPositionEval` are derived state (hoisted above hooks,
  TDZ rule) that read the rewound snapshot when `reviewing`, else live `roomData`; the Vals
  toggle no longer hides on a finished game (so it shows while rewound to a playing turn).

### Session (June 25 2026) — tap-to-ping, "waiting for you" tab alert, reserved-card + actions-box sizing (SHIPPED to main; do not regress)
Four small Spender UI changes, all frontend-only except the ping relay (one backend WS action). Built in the
`forrestm_projects-sound` worktree (branch `sound`), pushed straight to `main`. The `sound` worktree is the
standing scratchpad for these one-off UI fixes.
- **Tap-to-ping a player (chime for you + them).** Clicking ANOTHER player's box (`.player-panel.pingable`,
  gated `!isMe && !reviewing`) plays a short rising two-tone WebAudio chime locally and sends
  `{action:"ping", target: pid}`. **Backend (`main.py` WS loop): the `ping` action relays
  `{type:"ping", from: pid}` to ONLY the target player's socket** (`tws = ROOMS[room]["sockets"][target]`,
  guarded `target != pid`); the clicker already played locally, so there's no echo-back. **VERIFIED with a
  4-client integration test: a ping reaches only the tapped player + the clicker — the other 2-3 players hear
  NOTHING** (do not "broadcast to the room" — that would leak to everyone). `playPing()` is a module-level
  helper (one lazily-created shared `AudioContext`, no audio asset) used by both the click handler and the
  `msg.type==="ping"` message branch.
- **"Someone's waiting for you" tab indicator (permission-free).** A `useEffect([myTurn, pinged])` gated on the
  Page Visibility API: while the tab is HIDDEN and (it's your turn OR a ping arrived), it FLASHES
  `document.title` between `Forrest Games` and `🔔 Your turn!` / `👋 Someone's waiting!` (~1.1s) and swaps the
  favicon to **`webapp/public/favicon-alert.svg`** (the tree + a red badge). Cleared the instant you return
  (`visibilitychange`→visible restores title/favicon + clears `pinged`). New `pinged` state set only when a ping
  arrives AND `document.hidden` (so a stale ping doesn't fire later). NO Notifications API (no permission prompt,
  by user choice). Spender-only so far; CoC/Where Wolf? would need the same small addition.
- **Reserved-card content sized via container query (cqw), NOT `--card-h`.** The reserved-card cost/points/color
  were sized off `--card-h` assuming a reserved card was ~0.58× a board card; it's actually ~0.8-1.0× (and the
  ratio drifts with the sidebar/`--card-h` clamps), so the text rendered ~half-size. Fix: `.player-reserved .card`
  is now `container-type:inline-size` and its content (`.card-points`/`.card-bonus`/`.cost-gem`/`.cost-num`/
  `.card-cost` gap/`.card-header` margin) uses **cqw** so each reserved card is a faithful MINI board card
  (content = same fraction of the card as on the board cards, ≈ board's `--card-h` multiple ÷ 0.72). **GOTCHA
  (do not regress): cqw on the card's OWN padding resolves against an ANCESTOR container/viewport, not itself —
  so the card's padding STAYS `--card-h`-based; only DESCENDANTS use cqw.** Verified within ±2.7% across
  resolutions by a headless measurement harness.
- **Slimmer actions box (the 3-4p layout-shift fix).** The Take/✕ buttons were too wide and, in 3-4p lobbies
  (the wider nobles row squeezes the actions `1fr` column), forced that grid track wider and shoved the
  board/sidebar around. (1) **Removed the ✕/cancel button entirely** from `renderActionButtons` (all states) —
  clicking a selected gem or card again already toggles it off (`handleGemClick` / the card `onClick`), so it was
  redundant. (2) Tightened the Take/Buy horizontal padding (`.actions-panel-btns .btn` `0.162→0.08 × --card-h`).
  (3) **`min-width:0` on `.actions-panel` + `.actions-panel-btns` (and `max-width:100%` on the button) is the
  structural guarantee** the box can never grow its own grid track — a grid item defaults to `min-width:auto`
  (=min-content), which is what let a wide button expand the `1fr` track; `min-width:0` makes the track purely
  space-derived. Verified: with `min-width:0` the grid width is STABLE regardless of button width (the old code
  overflowed its container by ~220px with a wide button). The `.action-bar-spacer ✕` (in the legacy
  `visibility:hidden` action-bar paths) is a height placeholder, not a real button — left alone.
- **Minimal actions-box hint (the follow-up height fix).** Even after the width fix, the hint (`getHint()` →
  `.action-hint`) was still bloating the box: the verbose per-action guidance (e.g. *"Take gems, or click a card
  then the gold coin to reserve"*, *"Reserve armed — …"*) wrapped to several lines in the squeezed 3-4p column,
  growing the actions row (row 1) and shrinking the card board (row 2). Per the user, **`getHint()` now returns
  ONLY `Waiting for {name}…` (opponent's turn) and `""` on YOUR turn** — the Take/Buy buttons, the card
  affordability highlight, and the discard/noble modals already convey everything else (the per-action hints were
  deliberately dropped). On your turn the empty hint collapses to 0 height, so the box is just Target + buttons.
  The desktop `.actions-panel .action-hint` is **`white-space:normal` + `overflow-wrap:anywhere`** so the short
  waiting text WRAPS to the next line for a long name (no ellipsis — show the full name) while `overflow-wrap:
  anywhere` breaks a long unbroken name so it still can't force the column wider (keeps the width guarantee); a
  2-3 line wrap of that short string stays within the nobles' height, so it doesn't regrow the actions row.

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

**The build is CI-owned and published to the `gh-pages` branch — NEVER build or commit it by hand.**
As of **2026-06-24** the Pages source is **`gh-pages` / root** (repo Settings → Pages), NOT the
old `main` / `/docs`. The `.github/workflows/deploy-pages.yml` Action fires on every push to `main`
touching the frontend (`webapp/**`, `games/spender/**`, `games/castles_of_crimson/**`,
`games/wherewolf/**`, `books/**`, `shared/**`): it builds the **top-level `webapp/`** (with
`VITE_WS_URL=wss://splendid-nelz.onrender.com/ws` baked in) and **force-pushes `webapp/dist/` to the
`gh-pages` branch** (single-commit, `.nojekyll`). It does **NOT commit anything to `main`** — the old
"`rm -rf docs/` + commit `docs/` to main `[skip ci]`" step was removed because those deploy commits
advanced `origin/main` on every frontend push and were a constant source of local-`main` drift (and
the push-rejected → rebase → minified-bundle conflict loop). A push to `gh-pages` does NOT re-trigger
the workflow (it only watches `main`), so there's no deploy loop and no `[skip ci]` needed.

**`docs/` is now VESTIGIAL** — kept on `main` only as a rollback safety net (flip Pages source back to
`main` / `/docs` to revert). Once the gh-pages flow is trusted, `git rm -r docs/` it (+ gitignore).

**Frontend deploy = commit source only:**
```bash
# edit games/spender/Spender.jsx (do NOT npm run build, do NOT touch docs/)
git sync-main                      # ff the main worktree to origin/main first (global alias)
git add games/spender/Spender.jsx
git commit -m "feat(ui): ..."
git push                           # CI builds + publishes to gh-pages (~2-3 min)
```
The two deploy workflows: **deploy-pages.yml** (frontend → builds + publishes to the `gh-pages`
branch → GitHub Pages) and **deploy-render.yml** (backend → Render). Backend (`main.py` etc.) also
deploys on push to main. `npm run build` locally is only for *verifying a build compiles* — discard
the `dist/`, never copy it into `docs/`.

**`git sync-main` (global alias)** ff's the primary main worktree to `origin/main` from anywhere
(`git -C "<main-worktree>" fetch origin && merge --ff-only origin/main`). Local `main` carries no
unique commits, so it's always a clean ff — but it drifts because feature branches push straight to
`main` from sibling worktrees. When branching, branch off `origin/main` after a `fetch`, not stale
local `main`.

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
  `git push -f origin staging` to resync. CI then builds + publishes to `gh-pages` + redeploys prod.
- **⚠️ `staging` has DIVERGED — NEVER blind-push `staging:main` (do not regress).**
  As of 2026-06-21 `staging` is a long-lived branch that is **behind `main` on the
  backend** (it lacks main's wherewolf engine/role fixes, Spender move-log/card-catalog,
  S-variant perf, etc.) AND has historically **carried the Where Wolf? home card**. So
  `git push origin staging:main` would be a non-fast-forward whose force **wipes main's
  backend history** (and could re-introduce or revert game state unexpectedly). **To ship
  staging frontend selectively** (the method used for the CoC overhaul + active-games +
  Spender mobile actions-box + the Where Wolf? launch): branch off `origin/main`;
  wholesale-take any file where main is unchanged since the merge-base (e.g.
  `git checkout origin/staging -- games/castles_of_crimson/CastlesOfCrimson.jsx`, or just
  `games/wherewolf/WhereWolf.jsx` for the wherewolf launch); for files both sides changed
  (`Spender.jsx`) 3-way merge them (`git merge-file -p ours base theirs`, base =
  `git merge-base`) and re-add/strip only the intended blocks; `npm run smoke`; push the
  branch → `main`. Verify with `grep` on the shipped file + the built bundle size.
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

### Frontend smoke test (`npm run smoke`) — catch blank-page AND layout-shift regressions
`webapp/test/smoke.mjs` (Playwright) builds the app, serves it with `vite preview`,
loads it in a headless browser, and FAILS if `#root` doesn't render, any uncaught
page error fires, **or the page shifts its layout on load past a budget** (Cumulative
Layout Shift). This catches two classes: (1) **the bundle compiles but throws at
runtime → a blank white page**; (2) **content/fonts/styles arriving after first paint →
the "snaps into place" reflow** (a `layout-shift` PerformanceObserver accumulates CLS;
budget `0.1` — current load ~0.008). The bug that motivated it: a CSS comment
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

### No-layout-shift architecture (June 2026 — do not regress)
We kept hitting reload "snaps into place" reflows; the structural fixes (so it stops
being whack-a-mole):
- **Self-hosted fonts.** Cinzel + Crimson Pro are served from `webapp/public/fonts/`
  (latin-subset **variable** woff2 — one file per family covers all weights; 3 files
  incl. italic), `@font-face` in `shared/theme.js` baseCss (+ a copy in CoC, which
  renders bare without baseCss; the browser dedupes by src url). The Google-Fonts
  `<link>`/`@import` are GONE. The two main files are **preloaded** in `index.html`
  (`<link rel="preload" as="font" crossorigin>` — crossorigin required even same-origin).
- **Render gate.** The loading effect (`Spender.jsx`) calls **`document.fonts.load(...)`**
  for Cinzel 400/600/700 + Crimson 400 and AWAITS them (capped 1.5s) before routing to
  a real screen, so the first paint already uses the web fonts — no swap. `document.fonts.ready`
  ALONE is insufficient (the blank loading screen renders no text, so nothing triggers
  the load; `.load()` triggers + awaits it). On reload (cached) it resolves instantly.
- **`font-display:optional`** on every face: if a font isn't ready in its tiny window it
  uses the fallback for that load and NEVER swaps (no late reflow). Belt-and-suspenders:
  **metric-matched fallbacks** — `'Cinzel Fallback'`/`'Crimson Fallback'` = `local('Georgia')`
  with `size-adjust` from MEASURED width ratios (Cinzel 1.118× Georgia → 111.8%, Crimson
  0.879× → 87.9%), wired into every font stack (`'Cinzel','Cinzel Fallback',serif`), so an
  unloaded font occupies the same space.
- **Inline dark bg** in `index.html` (`html,body{background:#0f0e0c}`) avoids a white flash
  before the JS-injected CSS loads (the `--bg` token only exists in baseCss).
- **Reserve space for stateful elements** (fixed button/icon sizes, `scrollbar-gutter:stable`,
  `min-height` on swap-y rows) — and the **CLS smoke gate** (above) catches any new shift.
- Known longer-term option (not done): the CSS-in-JS `<style>{baseCss+css}</style>` injects
  styles at render; a static `<link>` stylesheet would make them render-blocking/earlier, but
  it conflicts with the self-contained single-`.jsx` game pattern, so it was deferred.
