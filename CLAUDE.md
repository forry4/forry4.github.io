# Forrest Games — Claude Context

A seven-game multiplayer board-game website (+ a Books feature) sharing one backend, auth
layer, and frontend shell. Real-time play over WebSockets, server-authoritative game state,
and per-game AI opponents that range from simple heuristics to client-side neural nets
compiled to WASM.

**This file is the cross-cutting operating manual** — what applies no matter which part you touch.
Per-area detail lives in a `CLAUDE.md` next to the code, loaded when you read files there:

| File | Covers |
|---|---|
| [`games/spender/CLAUDE.md`](games/spender/CLAUDE.md) | Spender engine/backend, the AI variant zoo, Puzzle mode, and `Spender.jsx` (also the site shell) |
| [`games/castles_of_crimson/CLAUDE.md`](games/castles_of_crimson/CLAUDE.md) | CoC engine contract, AI tiers, frontend layout maths |
| [`games/wherewolf/CLAUDE.md`](games/wherewolf/CLAUDE.md) | WW roles, redaction matrix, night conductor |
| [`games/spender_duel/CLAUDE.md`](games/spender_duel/CLAUDE.md) | Duel engine, hidden info, and the current coherent/minimax search |
| [`games/dontminion/CLAUDE.md`](games/dontminion/CLAUDE.md) | Dontminion (Dominion) frame-stack engine, the frozen effects API, multi-bot server, decision-prompt frontend |
| [`games/dissonance/CLAUDE.md`](games/dissonance/CLAUDE.md) | Dissonance — parity trick-taking rules, the Rust reference + parity gate, auction/scoring calibration, the five modes (classic / skat / minor / dummy / quartet), and the browser-served Hard tier |
| [`games/rag_tag/CLAUDE.md`](games/rag_tag/CLAUDE.md) | Rag Tag (Tag Team) — the simultaneous turn resolution, the generated fighter data and where it came from, the two-pass declaration |
| [`shared/CLAUDE.md`](shared/CLAUDE.md) | Shared frontend kits + URL routing |
| [`books/CLAUDE.md`](books/CLAUDE.md) | The Books feature |
| [`bggfilter/CLAUDE.md`](bggfilter/CLAUDE.md) | BGG Filter — the BoardGameGeek harvest + the frontend-only filter page |
| [`docs/ai-research-log.md`](docs/ai-research-log.md) | **AI campaign history, dated sessions, rejected-experiment postmortems.** When something here says "see the research log," that's the blow-by-blow + "do not relitigate" detail. |

---

## Tech stack

| Layer | Tech |
|-------|------|
| Backend | FastAPI + asyncio, one uvicorn process; SQLite locally / **Turso (libSQL)** in prod |
| Realtime | WebSockets (one per room+player); in-memory `ROOMS` under a single `asyncio.Lock` |
| Frontend | React 18, plain JS (no TypeScript), Vite 6, one self-contained `.jsx` per game |
| AI | determinized MCTS / PUCT; heuristics; learned nets served **client-side via Rust→WASM** |
| Deploy | Backend → Render; Frontend → GitHub Pages (Actions pipeline); Cloudflare staging mirror |

- **Server is authoritative for all game state.** Clients render and send moves; the server
  validates every move through the engine. Client-side AI is safe because tampering only weakens
  the tamperer's own opponent (the move is still validated server-side before it's applied).
- **Games**: Spender (Splendor), Castles of Crimson (Castles of Burgundy), Where Wolf? (One Night
  Ultimate Werewolf), Spender Duel (Splendor Duel), Dontminion (Dominion — Base, Intrigue,
  Seaside, Prosperity, Hinterlands and Cornucopia & Guilds in 2E, plus Alchemy, Dark
  Ages, Adventures, Empires, Renaissance and Menagerie; 368 cards + 114 LANDSCAPE cards
  (53 Events, 21 Landmarks, 20 Projects and 20 Ways) + 5 Artifacts, more sets landing
  per phase).
  Rag Tag (Tag Team — 2 players, 12 fighters, 120 cards; both players reveal and resolve
  at the same time, and the deck is never shuffled).
  Plus **Books** (a ranking/suggestions page) and **WWSD** (a browser autoplayer for a friend's
  external Splendor site).

### Run it locally
- Backend: `python -m uvicorn app:app --reload --port 8000` (the composition-root app at repo root).
  Spender is a `router` included by the root `app` (no separate Spender server); the deploy shim
  `games/spender/app.py` just re-exports the root `app`.
- Frontend: `cd webapp && VITE_BASE=/ VITE_WS_URL=wss://splendid-nelz.onrender.com/ws npm run dev`
  — HMR against the **prod backend** is the fastest loop (resume a real game from your account).
  For a fully local stack point `VITE_WS_URL` at `ws://localhost:8000/ws`.
- **Vite MUST run on port 5173** — `core/config.py` CORS only allowlists `localhost:5173`; on 5174
  the browser fetch is CORS-blocked and the app hangs on the loader.
- Smoke gate before pushing frontend: `cd webapp && npm run smoke` (see Testing — it is weaker than
  it looks).
- Distinct local players need **distinct browser storage** — two incognito windows in the same
  browser share `localStorage` → same `spender_myId` → they collapse into one identity. Use
  different browsers/profiles.

---

## Repo layout

```
app.py                 # COMPOSITION ROOT: FastAPI app + CORS/security middleware + feature wiring
core/                  # SHARED BACKEND PLATFORM (imported by every feature; imports no game)
  db.py                #   dual sqlite/Turso conn wrapper + get_db_conn + init_core_schema + retention
  auth.py              #   users/sessions/passwords, admin + SITE_OWNER identity, reconnect tokens
  ratelimit.py         #   SlidingWindowLimiter (auth + WebSocket abuse throttle)
  config.py            #   cors_allowed_origins()
  rooms.py             #   shared room-server primitives + the state_json codec
                       #   (encode/decode_state, pack/unpack_rng) — all seven games use it
  build_info.py        #   commit + started_at for /health, so a deploy can be VERIFIED not assumed
games/
  spender/             # Spender (Splendor) — main.py exposes `router` (APIRouter), + ai/ stack
                       #   engine.py = the rules (single source of truth); cards.py = static card data
                       #   persist.py = at-rest compaction of the state_json blob (save/load only)
  castles_of_crimson/  # CoC — engine.py + ai.py + main.py (coc_app @ /coc) + CastlesOfCrimson.jsx
                       #   persist.py = at-rest compaction of the state_json blob (save/load only)
  wherewolf/           # Where Wolf? — engine.py + main.py (werewolf_app @ /werewolf) + WhereWolf.jsx
  spender_duel/        # Spender Duel — engine.py + ai.py + main.py (duel_app @ /duel) + SpenderDuel.jsx
  dontminion/          # Dontminion (Dominion) — engine.py + ONE effects_<set>.py per expansion +
                       #   main.py (dontminion_app @ /dontminion) + Dontminion.jsx; expansion
                       #   picker, 2-4p, multi-bot rooms. tools/replay_prod_saves.py is the
                       #   migration gate. EXPANSIONS.md is the phase roadmap + debt ledger
  rag_tag/             # Rag Tag (Tag Team) — 2p SIMULTANEOUS auto battler. 12 fighters,
                       #   120 cards, decks that are never shuffled. fighters.py is
                       #   GENERATED from data/*.json by tools/import_bga.py; effects.py
                       #   is the closed op vocabulary that data is held to
  dissonance/          # Dissonance — 2p parity trick-taking. engine.py is a PORT of
                       #   rust-cores/dissonance-core (the solver-validated reference);
                       #   tests/test_rust_parity.py is the drift gate. FIVE modes
                       #   over the shared card play, picked per room
                       #   (`mode: classic|skat|minor|dummy|quartet` — minor
                       #   re-prices even tricks to +1; skat scores the CARDS
                       #   captured, 9/10/J/Q +2 and 7/8/K/A −1; dummy deals a
                       #   THIRD hand whoever leads plays, 3 seats x 13 cards off
                       #   a WIDE 40-card deck, 13 tricks of three; QUARTET deals
                       #   FOUR hands off the full 52, two per player, 9 tricks
                       #   of four, and scores the three cards each own hand is
                       #   left holding) — see its CLAUDE.md
books/                 # Books feature (wired into the app, not a sub-app)
bggfilter/             # BGG Filter — frontend-only; tools/ harvests BGG, the payload ships
                       #   as webapp/public/data/bgg-filter.json (GENERATED, ~1MB, fetched not bundled)
shared/                # theme.js (baseCss), lobby.jsx, splendor.jsx, router.js — cross-game frontend kits
                       #   + AuthScreen.jsx / HomeScreen.jsx — site-SHELL screens, here for the
                       #   dependency direction (games -> shared, never back)
webapp/                # Vite + React build (neutral, repo-root) — main.jsx mounts Spender.jsx (the shell)
  test/                #   smoke.mjs (blank-page/CLS gate) + screens.mjs (real render gate)
wwsd/                  # "What Would Steve Do" — browser autoplayer for a friend's external site
rust-cores/            # Per-game Rust→WASM search crates (client-side serving). NOT the Python core/.
  spender-core/        #   Spender variant S/N search core
  coc-core/            #   CoC Expert (netval) search core
  duel-core/           #   Duel attention-net search core
  dissonance-core/       #   Dissonance rules reference + PIMC/double-dummy Hard tier
docs/                  # GitHub Pages build output + ai-research-log.md
```

**Naming caution:** `core/` (top-level, singular) is the **Python** backend platform every feature
imports. `rust-cores/*-core/` are **Rust→WASM** crates, one per game — build artifacts, imported by
nothing in Python. They are per-game siblings (like `games/*`), not part of `core/`.

**Layering:** `core/` (bottom, depends on nothing) → features (games, books) → `app.py` (top). The
composition root depends on features; features depend only on `core`. This is the extraction that
removed the old circular imports — **never reintroduce a `games.*` import into `core/`.** Each game is
a thin FastAPI sub-app (`rooms`/WS/REST/persistence) that delegates all rules to its pure `engine.py`.
Root-level `render.yaml`/`docs/` stay at root (the Docker image is built from `games/spender/Dockerfile`
per `render.yaml`).

---

## Shared backend platform (`core/`)

- **`core/db.py`** — `get_db_conn()` is a dual backend behind a driver-agnostic wrapper
  (`_Conn`/`_Cursor`/`_Row` — rows work by index AND column name). Local **sqlite3** by default;
  **Turso/libSQL** when `TURSO_DATABASE_URL`+`TURSO_AUTH_TOKEN` are set. A boot-time `_turso_selftest()`
  round-trips a row and **falls back to local sqlite on any failure** (site stays up, just
  non-persistent). `init_core_schema(conn)` creates `users`/`admins`/`reconnect_tokens`.
  `cleanup_stale_games(table)` / `maybe_cleanup_games(table)` handle retention (all-guest game 24h,
  any-registered-player 30d, and a never-started `status='open'` lobby 48h regardless of who hosts
  it — a waiting room nobody joined has nothing to resume and otherwise outlives the game version
  it was created under).
- **`core/auth.py`** — sessions/passwords (PBKDF2 + legacy), `create_user`/`authenticate_user`/
  `get_user_by_session`, `validate_credentials` (register: name 1–16 `[A-Za-z0-9]`, password 1–16),
  SITE_OWNER/admin helpers, reconnect-token create/validate/mark-used + throttled cleanup.
- **`core/config.py`** — `cors_allowed_origins()` **merges** `CORS_ALLOWED_ORIGINS` env with the always-on
  defaults (Pages `forry4.github.io`, the Cloudflare staging worker, localhost). Do NOT make it
  replace-semantics — that once silently locked out the staging mirror.
- **`app.py`** creates `app = FastAPI()`, applies CORS + a pure-ASGI `SecurityHeadersMiddleware`
  (threaded into the mounted sub-apps too), `include_router`s Spender's `router`, `setup_books(...)`,
  `setup_puzzles(...)`, and mounts CoC/WW/Duel each behind a **defensive try/except** (so the core
  backend never goes down if a game package is absent). No CSP on the API (it serves JSON).

**Persistence:** Render's free filesystem is ephemeral, so prod uses Turso. **Turso is LIVE and verified
on Render — prod IS persistent; don't tell the user to set it up.** The libsql path **cannot be tested
locally** (no wheel for Python 3.14 on this box; prod Docker is 3.11) — validate it via Render logs + a
login that survives a redeploy. The sqlite path (identical wrapper) IS locally tested.

### Auth correctness & security (hard-won — do not regress)
- **WS SEAT IDENTITY IS BOUND IN ALL SEVEN GAMES.** The `player` path segment is client-supplied and
  every pid is broadcast in the public players map, so a socket must PROVE it owns its pid before it
  can act as that seat or receive that seat's view. `authed` flips true only via create / join-as-a-new-
  seat / join-with-a-matching-`session_token` / reconnect-with-the-room-token / auth_reconnect; every
  mutating action is gated on it. Frontends send `session_token` on join. Tests: each game's
  `tests/test_ws_auth.py`.
- **NEVER register a socket in `room["sockets"]` before that handshake.** Spender used to, at connect
  time, and `broadcast_room` rebuilds state PER RECIPIENT keyed on the socket's pid — so merely opening
  a socket claiming a victim's pid and sending NOTHING returned that seat's blind reserves AND its
  `reconnect_tokens` entry, which replays as `{"action":"reconnect"}` for a full takeover. It also
  displaced the victim's live socket. (The follow-on trap: that registration was also what made the room
  get cleaned up, so removing it leaked an empty `ROOMS` shell per connect — `core.rooms.release_socket`
  now collects phantom rooms independently of socket ownership.)
- **Any new broadcast field must be per-field redacted** — "an honest client ignores it" is NOT security.
  A 2026-07 audit found 3 of 4 games shipping raw hidden ordered state (Spender `decks`, WW `deck`, CoC
  supplies + `rng_state`).
- **`is_admin` is computed the same way on every path** — `is_admin_id(conn, id)` (plain SELECT) or a
  live `SITE_OWNER` username match. NEVER a correlated subquery — it reads NULL on the libsql driver
  (works on sqlite → invisible in tests), which made the owner lose admin on every session refresh.
- **Usernames are unique case-insensitively** — `users.name` has no UNIQUE constraint, so `create_user`
  checks `WHERE name=? COLLATE NOCASE` and `init_core_schema` builds `idx_users_name_ci`. Login too.
- **Tokens use a CSPRNG** (`secrets`, not `random`) — session/account/reconnect tokens AND password salts.
- **Auth rate-limited** (in-memory, per-process — OK because one uvicorn process): login 20/5min per IP +
  10 failures/15min per username (resets on success); register 10/hr per IP. Over-limit returns HTTP 200
  `{ok:False, message}` so the existing error UI shows it.
- **Session token in `Authorization: Bearer`**, not the URL (with a `?token=` fallback for cached
  clients). WS uses room-meta/reconnect tokens in the message body, never the URL.

---

## Shared room-server pattern (mirrored in every game's `main.py`)

Each game's `main.py` builds the same scaffolding: in-memory `ROOMS: dict[str, dict]` under a single
`ROOM_LOCK`, `save_game`/`load_game_to_memory`, `broadcast_room`, `mk_room_state`, a stale-socket
disconnect guard, and an async opponent scheduler.

```python
ROOMS[room_id] = {
  "players": {pid: name}, "sockets": {pid: WebSocket},
  "status": "open"|"playing"|"over", "host": pid,
  "game": {...} | None, "meta": {pid: {"token": str, ...}},
}
```

**The generic half lives in `core/rooms.py`** (all seven games use it, aliased to their historical
private names): `normalize_room`, `gen_room_token`, `db_conn`, `ensure_room_loaded`, `send_json`,
`delete_open_game(table, host_col, ...)`, and `release_socket` (the stale-socket guard + phantom-room
collection; per-game policy stays explicit as the `disarm_client_ai` / `drop_empty_open_only` flags).
Extracting it was not tidiness: the same hidden-info broadcast leak had to be found and fixed THREE
times because three copies of `mk_room_state` each leaked differently.

**Still duplicated (~25 functions, the obvious next extraction):** `save_game`, `load_game_to_memory`,
`_persist_row` and the `list_open_games`/`list_user_games`/`list_user_history`/`list_active_games`
family. Same shape in every game, differing only in table name and columns — though not every game
has every member: `save_game`/`load_game_to_memory`/`list_open_games` are all seven, `list_user_history`
is six (Where Wolf? has no History), `list_active_games` only Spender and CoC. **They drift exactly
as you would expect** — back when four games had one, the `list_user_history` row caps were
independently 20/30/30/30 until 2026-08-05; all six now bind `core.rooms.HISTORY_LIMIT` (see the
lobby History note below).

**THE HOW-TO-PLAY MODAL IS SHARED — `RulesModal` in `shared/lobby.jsx`, reached from a Rules button
in every lobby's create row (right of ↻).** Chrome only: each game's WORDS live in its own
`games/<game>/rules.jsx`. The panel is capped to the viewport and `.rl-body` is the ONLY scroller
(`min-height:0` is load-bearing — a flex item won't shrink below its content, so without it the panel
grows past `max-height`, nothing scrolls, and the close button sits below the fold). On phones the
create row scrolls SIDEWAYS rather than wrapping — with five controls it stops fitting at ~430px —
via `justify-content:safe center`, because plain `center` pushes the overflow off the unreachable
LEFT edge. `screens.mjs` drives all seven lobbies: the button is optional on the component, so a game
that forgets to pass `onRules` renders a perfectly fine lobby with no way into the rules.

**THE LOBBY IS ONE SHARED LAYOUT — `shared/lobby.jsx` + its CSS, used by all seven games.**
The column grid (`.lby-cols`), the card list (`.lby-list`), the rows (`.lby-card*`), the section
headers (`LobbySectionHd`), the empty states (`.lby-empty`), the turn pills (`TurnBadge`) and the
phone tab bar (`LobbyTabs`) all live there. **Spender was the last hold-out and was converted
2026-08-05**: the kit had been extracted FROM Spender for the other four, and Spender itself was
never moved onto it, so it carried a parallel `.game-card*` / `.section-hd` / `.empty-state` /
`.your-turn-badge` vocabulary — four rules byte-identical to the shared ones, five differing by a
pixel or 0.02rem, and only three real differences (the card hover, the muted note, the section-header
baseline). Converging also deleted CoC's dead pre-kit `.coc-card*` vocabulary and two of the three
shipped spin keyframes.
- **One responsive ladder, in the shared sheet**: 3 columns ≥1041px, 2 columns 761–1040 (History
  spanning below), 1 column + the tab bar ≤760. It replaced four hand-tuned copies that collapsed at
  1280/1040/—/980 and 780/760/720/640, which left **dead bands** where a lobby was one column with
  the tab bar still hidden — every section stacked full-length (Duel 721–1120px, Dontminion 641–980).
- **`.lby-cols` pins BOTH grid axes at every tier**, so a lobby's layout no longer depends on the
  order its JSX happens to render in. Spender needed that anyway (its DOM is Open, History, Active,
  so column-only placement wrapped Active to row 2 and it read as "pushed down"); making it the
  shared behaviour means no game has to remember.
- **A game's CSS must not set `display`/`grid-template-columns`/`gap` on its own lobby-grid class.**
  Six of the seven sheets are concatenated AFTER the shared one, so a base rule there out-orders the
  shared MEDIA rules and pins the lobby to three columns on a phone. CoC is the exception (its sheet
  comes first), which is exactly the kind of asymmetry that makes this worth stating rather than
  discovering. Per-game tuning goes through `--lby-list-max`, which works from either side.
- Where Wolf? keeps its own 2-column grid (it has no History column) but uses `.lby-list` like
  everyone else.

**A GAME CARD ROW IS THE KIT'S, DOWN TO THE ROW'S ANATOMY — three things a new game gets for free
and cannot get wrong by writing nothing** (all three enforced by `shared/tests/test_lobby_kit.py`,
because each was a per-game decision that looked reasonable in its own file):
- **The create button says `+ Create Game` in every lobby.** `createLabel` is a prop with that
  default and two games had themed it (`+ Create Fight`, `+ Create Orbit`) to match their own
  vocabulary. It is the same control in the same corner on eight pages; theme the rows, the empty
  states and the create modal instead.
- **The actions rail is a GRID: buttons top-right, the turn pill UNDERNEATH them.** `.lby-card` is
  `align-items:flex-start` so Resume hangs from the row's top edge (centred, it slid halfway down
  the moment a row went to two lines). The pill's placement is `order`/`grid-row` in the SHARED
  sheet, not DOM order — every game emits the pill before its buttons, and `column-reverse` would
  have flipped the two-button Open rows (Cancel above Return) in passing. Flex was tried first and
  is wrong for a measurable reason: a wrapping flex container is sized by its UNWRAPPED max-content,
  so the rail kept reserving 207px for a 90px stack and still dropped below the title in a narrow
  column. **A game sheet must not set `display`/`flex-direction`/`grid-*` on `.lby-card-actions`** —
  six of seven sheets are concatenated after the shared one, so it silently wins.
- **An Active row names YOUR seat, via `LobbyMatchup`** — one seat per line, `(you)` on yours. Five
  lobbies printed the opponent alone (their Active list is `/games/mine`, so "naming yourself is
  noise"); Spender and CoC, whose Active columns are PUBLIC, always showed the full matchup. Two
  treatments of one row, decided by which endpoint a game happened to have. Where Wolf? is the one
  exemption and it is in the test: its `/games/mine` carries no names at all.

**The lobby History list pages, and the cap is ONE number seen from two ends.**
`core.rooms.HISTORY_LIMIT` (50) is the SQL row cap in every game's `list_user_history`;
`HISTORY_MAX` in `shared/lobby.jsx` is where `useProgressiveList` stops revealing. They must be equal
and `core/tests/test_history_limit.py` asserts it by reading the JSX as TEXT (core may not import a
feature, and that holds for its tests). The list shows `HISTORY_PAGE` (10) rows and reveals another
page when the reader scrolls the end into view — via a **SENTINEL + IntersectionObserver, not a scroll
handler**, because what actually scrolls changes with the tier (the column's own `.lby-list` at the
3-column tier, the page below it, and a third thing again once the phone tab bar takes over), and an
element clipped by an ancestor's `overflow` is correctly reported as not intersecting. Where Wolf? has
no History at all — it never had one.
**Deploy needs no expand/contract**: an old cached bundle renders all 50 at once, a new bundle against
the old server just runs out of pages sooner. Browser coverage is one `screens.mjs` block driving
Dontminion against a STUBBED `/games/history` of 55 rows (the hook is shared, so covering it once
covers the logic; each game's wiring is one line).

**Load-bearing invariants across all seven games:**
- **Pending sub-decisions are real game-state keys**, not transient message fields — so they survive
  saves/reconnects and are server-enforced (Spender `pending_noble_pid`/`pending_discard_pid`; CoC and
  Duel `pending_pid`/`pending_kind`/`pending`; Dontminion the same pair mirroring the top frame of its
  `pending` stack; WW `night_step`; Dissonance carries no sub-decision — its `phase` is the whole story).
  A stray `room_update` can't clear an unmet requirement.
- **The game dict is JSON-safe** (no sets anywhere; RNG persisted as lists in `rng_state`) → reconnect-
  and save/load-safe. **Persist the RNG only if something actually draws later** — WW spends all of
  its randomness in the deal, so its `rng_state` was 625 words nothing read and **89.5% of the row**
  (incompressible, so it survived zlib untouched while everything around it shrank ~8x). It is now
  not persisted, guarded by a test that plays a full game with the stdlib RNG booby-trapped.
- **An undo snapshot must store a POSITION in the move log, never a copy of it.** `save_game` persists
  the snapshot with the game, so a copied log is written twice on every save and the duplication grows
  all game — it was measured at half the stored blob in CoC and 487KB→150KB in Dontminion. All three
  games that have undo now store an offset (Dontminion `_log_len`, Duel `_log_len`, CoC `moves_seq`).
  **A length only works if the log strictly APPENDS**: CoC's prepends and caps by evicting the tail, so
  at the cap its length stops moving and a length delta silently restores nothing — it needs a
  monotonic counter. Check which shape a log has before copying the pattern across.
- **At-rest compaction is a PERSISTENCE BOUNDARY, never a change to the live dict.** Each game has a
  `persist.py` with `compact_state`/`expand_state`, and **`_encode_state`/`_decode_state` in its
  `main.py` are the only codec sites — every read must funnel through them** (offline tools included:
  Spender's `ai/serving/replay.py` and Dontminion's `tools/replay_prod_saves.py` both expand). The
  live dict, the wire, the engines, the bots and the Rust parity fixtures all keep the verbose shape.
  Blobs carry a `_c` marker, so pre-compaction rows load untouched and need no migration.
- **`rng_state` is the sleeper cost, and you must pack EVERY copy in a blob or none.** 625 words of
  Mersenne noise is incompressible, so it survives the ~8x zlib around it and dominates the row
  (27–34% of a Dontminion blob, ~59% of a Duel one counting the snapshot copy, 90% of a WW one).
  `core.rooms.pack_rng` halves it. But a game and its undo snapshot(s) hold near-identical states
  that zlib was already deduping — packing only the live copy destroys that dedup and the row comes
  out **+49.5% BIGGER than doing nothing** (measured on Duel). Reach every snapshot: Duel
  `turn_undo`, Dontminion all 30 `undo_stack` entries, CoC `turn_undo`.
- **Measure compaction AFTER zlib, and beware marginal costs.** Removing one key at a time
  under-reports anything that has a near-duplicate elsewhere (Duel's `rng_state` marginal reads 1.8%;
  the pair is ~59%). Use a cumulative strip-down to see what is really in a blob.
- **…but a stored RATIO is a measurement, not an invariant — never assert on it tightly.** Its
  denominator is the compressor, not the codec: the same CoC blobs read 0.660 at zlib level 1 and
  0.755 at level 6, and **Python 3.14 ships zlib-ng** rather than stock zlib. All four games'
  `test_compaction_actually_shrinks_the_blob` guards were written against CI's zlib; CoC's sat 0.005
  under its threshold, so it passed CI and was red on every dev box, and Dontminion's/Duel's margins
  were smaller than that swing. A size guard needs a DETERMINISTIC axis (raw bytes) for the tight
  bound, with the stored bound left loose — and the real no-op detection belongs in a STRUCTURAL
  test (CoC `test_every_tile_in_the_game_is_reached`, Duel/Dontminion's packed-snapshot tests),
  which no compressor can move.
- **Move logs are already as small as they get — do not relitigate this per game.** They are the
  biggest single item in CoC (33%), Duel (28%) and Dontminion (58–67%) rows, but they are hugely
  repetitive and zlib handles it: Dontminion card-names→indices was raw 104,863→93,436 but stored
  only −2.8%; CoC pid→seat-index was −0.5%. Capping instead trades scrollback history (CoC) or breaks
  seed+log reconstruction (Duel `replay.py`) — a product decision, not a compaction one.
- **Anything that nests a whole-game snapshot defeats per-field wire redaction.** CoC's `turn_undo`
  carried its own copies of the four hidden keys (`supply`/`black_supply`/`goods_supply`/`rng_state`)
  and shipped the ordered supply + `rng_state` to every client despite the top-level redaction being
  correct — the 2026-07 audit fixed the top level and missed the nested copy (`turn_undo` is itself
  the fifth `_HIDE` entry today). A redaction test built on a synthetic game dict cannot catch this;
  assert against the whole SERIALIZED payload of a REAL in-progress game.
- **AI turns run in a thread pool, never under `ROOM_LOCK`.** `_schedule_*_turn` snapshots under the lock
  → releases → runs the search via `loop.run_in_executor` → re-locks → re-validates turn/phase hasn't
  changed → applies → saves + broadcasts outside the lock. **OUTAGE LESSON (do not regress): never loop
  heavy synchronous engine work under `ROOM_LOCK` on the event-loop thread** — a CoC rewrite that did
  ~12 sync bot turns + ~12 DB saves under the lock hung the loop and took prod down.
- **A dropped socket must RETRY, or "Reconnecting…" is just a word.** Four of the six
  socket games rendered that label off `!connected` and did nothing about it, so a blip
  left the game frozen until the player reloaded — and in a vs-bot room it is worse than a
  stale view, because the bot's turn is only re-driven when a client reconnects
  (`_handle_reconnect` re-triggers the scheduler), so the BOT stops too. The retry must use
  the `reconnect` action (not `join`), back off (2s, 4s, … capped at 8s) and never give up —
  a Render cold start alone is 30–50s — and must also fire on `visibilitychange`, because
  iOS kills a backgrounded socket WITHOUT firing `onclose`, leaving `connected` a stale
  `true` that no backoff loop will ever notice. One implementation:
  **`shared/useAutoReconnect.js`**, extracted from CoC (which had it inline) and wired into
  Rag Tag. **Duel, Dontminion and Dissonance still have the gap.**
- **Stale-socket disconnect guard**: the WS `finally` only removes a socket / deletes a room if
  `r["sockets"].get(pid) is websocket` (the exact object for this handler) — prevents a reconnect race
  (WS1→WS2) from deleting the live room.
- **Cancel/delete must use SELECT-then-DELETE, not `cur.rowcount`** — the libsql wrapper doesn't expose
  `rowcount` (it raised → 500'd the cancel endpoint in prod).
- `_schedule_*_turn` is safe to call any time (internal guards no-op when it's not the AI's turn / not
  playing) — deliberately called after reconnect to unstick socket-dropped games.

---

## Cross-game AI facts (do not relitigate — per-game tiers in each package's `CLAUDE.md`)

- **A client-WASM worker pool must NEVER take every core.** The search is CPU-bound; a pool that pegs
  all of them starves the browser's main/compositor/raster threads and the animations stutter while the
  AI thinks. Each game sizes its own pool by hand, so the rule has to be re-applied every time: Spender,
  Duel and Dissonance all `max(1, min(hc-1, 4))`, CoC `hc<=4 ? max(1, hc-1) : min(hc-2, 8)`. Spender had
  it; **Duel and CoC shipped without it for months.** Only bites at ≤4 cores (the caps dominate above
  that) — and the `max(1, …)` is load-bearing, not decoration: a bare `min(hc-1, 4)` on a single-core
  phone asks for a pool of ZERO workers, which is the server bot wearing the Hard label. All four
  clamp today; keep the clamp when adding the fifth.
- **Determinization is a correctness requirement, not a strength knob** — the AI holds the real game
  dict server-side, so it must resample everything it can't legally see (decks, opponent blind reserves,
  future dice), canonicalizing each pool before reshuffling so the search provably can't read hidden order.
- **Scoring BOTH seats with the same eval and subtracting makes denial fall out of the search for free**
  — no "contested-card" knob (Spender `v_state`, Duel `_standing`, CoC via `heuristic::value`).
- **A resource must not out-score what it converts into** (privileges/gold/reserves vs their sink) — the
  documented buy-nothing / hoard-forever collapse.
- **Break MCTS visit ties by mean value, not first index** — Splendor/Duel have no turn limit, so a
  plain `max(visits)` bot takes tokens forever and the game never ends.
- **Static-vs-rollout leaf is game-specific and MEASURED, never assumed:** Spender/Duel → static leaf
  beats rollout (A/B by equal *time*); CoC → a short rollout is needed (delayed payoffs). The repo has
  opposite precedents on purpose. Note the cost side doesn't transfer either — rollout is ~free behind
  Duel's attention leaf but expensive behind a heuristic one.
- **The strength lever is SEARCH (sims throughput and search *soundness*), not eval re-weighting** —
  every eval-weight and eval-feature tuning campaign saturated. Duel's 2026-07-26 coherent-search and
  minimax fixes are the current proof that soundness bugs can hide under noise for a whole campaign.
- **A client-served tier degrades PER DECISION, never per game.** The server arms one decision, waits
  out a watchdog, and plays it itself if the browser does not answer — an unarmed client, a stale reply,
  an illegal move and a closed tab are all the same path. The armed request lives in ROOM STATE so every
  re-broadcast and reconnect re-ships it, and the opt-in is cleared when the socket drops
  (`release_socket(disarm_client_ai=True)`) so a room never waits on a tab that is gone. Duel, CoC and
  Dissonance all run this shape; **the move is re-validated against the engine on arrival**, which is the
  whole reason a client-side AI is safe.
- **THE CREATE MODAL'S DIFFICULTY DEFAULT IS THE TIER THAT PLAYER LAST PLAYED, in every game with a
  bot** — `useLastDifficulty` in `shared/lobby.jsx`, keyed per game and per identity, written where
  the vs-AI game is CREATED (not from the picker's `onChange`) and validated against the tiers the
  picker currently offers. A new game with an AI opts in with one line;
  `shared/tests/test_ai_difficulty_memory.py` derives its roster from the tree and fails the one
  that doesn't, because forgetting compiles and renders a perfectly normal-looking picker.
- **Benchmark offline only** (per-game `ai_selfplay` / arena / gate bins) — never in a serving path.
  Judge with CRN paired arenas + a mirror sanity that must read exactly 0.5000; the ship criterion is
  EQUAL-TIME, not equal-sims.
- **A measurement harness must reproduce the SERVING shape.** Duel serves a 4-worker root-summed
  ensemble; a whole campaign of single-tree numbers had to be re-confirmed at `--pool 4`.

---

## Testing

- **The suite is defined ONCE** in `pytest.ini` `testpaths`; both CI workflows run a bare `pytest`.
  They used to carry two hand-maintained path lists that drifted (Duel's tests ran only at deploy).
- **The suite runs PARALLEL by default (`addopts = -n auto`) — 6m41s → ~1m04s, and `pytest-xdist` is
  a required dependency, not an optional one.** Two things were wrong, and they are different
  problems worth telling apart:
  1. **It was pure CPU pinned to one core** — 6m41s wall against 6m23s user, three cores idle.
     `-n auto` alone was ~3x and needed no test changes (every DB test already takes a `tmp_path`
     or `:memory:`; the WS connect throttle is per-PROCESS, so workers split that budget instead of
     contending for it; the root conftest's deck restore was already order-independent). `-n0`
     turns it off for `--pdb` or live output.
  2. **Two tests were 46% of the whole suite**, and under `-n auto` the longest one is the wall
     clock — so a parallel suite makes the slowest single test the thing worth measuring, which is
     what turned these up. Both were accidental cost, not coverage:
     - `test_soak.py::_fingerprint` re-`json.dumps`ed the WHOLE game dict per move, and the LOG
       grows: on the King's Court chunk that is 12k entries and a 1MB dump re-serialised 6000
       times — **88s of the test's 112s inside `json.iterencode`, against 21s of actual engine**
       (70.5s → 5.3s). The log is append-only, so its identity is `(length, last entry)`, and
       every entry is still round-tripped once for JSON-safety.
     - `test_bot_champion.py::test_champion_finishes_a_game` ran the research tier at its shipped
       12 paired rollouts per candidate buy — 116s to assert *a game finishes* (116s → 24s at 3).
  **The lesson to carry, not the numbers: profile the slowest test before assuming it is doing
  real work.** Neither of these was covering anything at the cost it charged, and a serial suite
  hid both in the aggregate.
- **Rules/engine unit tests are the most valuable to protect** — each game has them (per-package
  `CLAUDE.md` lists what each covers), plus `core/tests/` (db/auth/ratelimit/retention, in-memory
  sqlite) and Books `tests/` (17, in-memory DB).
- **ZERO STATE-REACHABILITY skips, repo-wide — keep it there** (`pytest.skip` / `skipif` / `xfail`). A
  test that can't reach the state it means to exercise must FAIL, not opt out: a skip is a green tick
  over a test that proved nothing, and the failure it hides looks like a pass in CI. All three that
  existed were real holes — a guessed frame option id that skipped when the guess missed (it swallowed
  a live engine regression during a fix), a hardcoded `range(13)` parametrize whose skip only guarded
  the roster SHRINKING (the next expansion's kingdoms would have gone unsoaked in silence — derive the
  count from the data instead), and a "no seed produced the position" bail. For a SAMPLED choice,
  assert every branch rather than only the interesting one.
  **This rule said "ZERO conditional skips" and was simply FALSE — there were two, and the wording is
  what let them sit.** Worth stating because the rule's whole value is that a reader can trust it: once
  it is inaccurate, someone grepping `skipif` finds hits and cannot tell sanctioned from drift, so the
  rule stops being enforceable by reading. Both were `importorskip`, and they were different problems:
  - `test_train.py`'s `importorskip("numpy")` was **vacuous** — numpy is a hard requirement imported
    unconditionally by five serving modules, so a numpy-less checkout dies at collection and the guard
    could never fire. **Deleted.** A guard that cannot fire is worse than none: it documents an
    optionality that doesn't exist.
  - `test_az_actions.py`'s `importorskip("torch")` is **kept, deliberately, and is the one carve-out**:
    an OPTIONAL-DEPENDENCY guard over code that does not ship. It covers `SpenderNet` in
    `ai/offline/net.py` — the AZ/variant-Z *training* stack, imported only by `train_az`/`arena`/
    `az_vs_h2`/`bootstrap_train`. Variant Z is retired, and the path that still serves it to old saves
    is numpy (`infer_np` + `az_model.npz`), never torch; `ai/offline/` is never imported by the server
    and is deliberately outside the deploy path filter. **Verified 2026-08-07 by installing torch and
    running it: it PASSES** (the file goes 13+1skip → 14, the suite → 3273/0), so it is not hiding a
    regression. Making it run in CI costs a torch install — 4.6GB from PyPI (CUDA build), a few hundred
    MB for the CPU wheel — against a suite that now runs in ~50-80s, to cover code that cannot reach
    prod. **And it must NEVER go in `games/spender/requirements.txt`**, which is the SERVER's
    requirements: the Dockerfile installs that file into the prod image.
  The distinction to carry: a skip over code that SHIPS is a hole; a skip over an optional dep for
  non-shipping research code is a cost decision. If you add a second carve-out, add it here — an
  unlisted `skipif` is drift by definition.
  **The rule is now MECHANICALLY ENFORCED — `core/tests/test_no_conditional_skips.py`**, because a
  rule whose only enforcement is prose is enforced only by whoever re-reads it, and this one had
  already drifted to prove it. It walks every module `pytest.ini` collects (122 today) and fails on
  any `skip`/`importorskip`/`xfail` call or `skip`/`skipif`/`xfail` mark outside its `SANCTIONED`
  map, so **a new carve-out must be added in TWO places — that map and this rule.** Two things about
  it are load-bearing and are the local versions of lessons already paid for elsewhere: it parses the
  **AST, not text** (the regex version of the `lost_track` guard scanned a 6-line window and comments
  pushed two real sites out of it — and here two modules DISCUSS `pytest.skip()` in prose, which a
  text search would flag), and its roster is **derived from `testpaths`** rather than hand-written,
  since a hardcoded list only guards the tree SHRINKING and a new test package would join unguarded —
  the `range(13)` bug's exact shape. A second test asserts the sanctioned skip is still *found*, so a
  broken walk or a stale row fails instead of quietly passing. Verified non-vacuous against all four
  skip forms plus a comment-only mention.
- **CI runs `core/tests/` first; Render deploy is gated on tests.** Frontend deploy is gated by
  `npm run smoke` AND `npm run screens`.
- **`npm run smoke` NEVER RENDERS A GAME — don't mistake it for render coverage.** The shell pings the
  backend before it routes, and smoke has no backend, so all three of its routes sit on the loading
  screen. It genuinely catches a blank page, a bundle that throws at load, and layout shift. That is all.
- **`npm run screens` is the real render gate** (`webapp/test/screens.mjs`): boots the actual backend,
  builds, serves on **5173** (load-bearing — `core/config.py` only allowlists that port for CORS;
  anywhere else the fetch is blocked and the app hangs on the loader), seeds a guest identity, and
  asserts each game route mounts ITS OWN markup (`.duel`/`.coc`/`.ww`/`.bk-app`), fetches its lazy
  chunk, and logs no page errors. Proven to work by injecting a mount-time throw into WhereWolf:
  **smoke PASSED, screens FAILED** with the exact TypeError. It builds first on purpose — a failed
  build leaves the previous working `dist/` in place, which once made a broken change look green.
- **`screens` runs its ~20 blocks in TWO LANES, and a new block MUST be listed in one** (`laneA`/`laneB`
  at the foot of the file; 116s → ~60s for the same 202 checks). The split is not arbitrary and is not
  "parallelise everything": a client-WASM pool takes `max(1, min(hc-1, 4))` workers, so **lane A holds
  every block that arms a pool (Dissonance Hard + the FOUR offline blocks) plus the two that measure
  frame-level TIMING** (skat's panel recorder; the beat block's per-trick dwells, which want ≥550ms out
  of a 700ms hold) — two searching blocks at once oversubscribe a 4-core box. Lane A's ORDER matters
  too: the offline blocks run first so the beat block lands in the tail with the machine nearly to
  itself (measured shortest dwell 691–699ms of 700, i.e. the margin is intact). Lane B holds the
  DOM/geometry blocks, which assert settled layout rather than elapsed time. **Forgetting to list a
  block compiles, runs and PASSES with that block never executing** — a green tick over coverage that
  did not happen — so the harness derives the roster from its own source and fails on any orphan
  (verified non-vacuous by dropping one). If the beat block ever turns flaky, move `dmCardFace` into
  lane A before touching any threshold. Output is buffered per block and flushed as one group with its
  wall time, because two lanes logging line-by-line interleave into noise.
- **`screens` runs the backend with `GAMES_DEAL_SEED` set, so its deals are REPRODUCIBLE — and that
  was the single largest cause of failed Pages deploys.** Of the 15 failures in the 500 runs to
  2026-08-28, 11 were this gate, and the ones that were the HARNESS rather than the product were one
  bug wearing four hats: *an assertion that holds on SOME deals*, written green locally and drawn red
  in CI. Four of them went red→green with the application code **byte-identical** — `807155f` (piles
  sampled after a round that ended early), `d1bdc1e` (the Double prompt only fires when the bot wins
  the auction — "real, just rare"), `408bf9e` (a price row that populates depending on which seat
  opened) and `8726c31a` (a regex that collided with the one fighter whose honest output looked like
  the bug). `core.rooms.deal_rng` makes a deal a pure function of who is at the table and
  `core.rooms.bot_seed` does the same for each bot decision — **both halves are needed**: pinning the
  deal alone still branches at the first bot choice, which is exactly what `d1bdc1e` was. The key is
  the sorted player ids, never the room id (generated) and never a global counter (the two LANES hand
  one out in interleaving order, so the same block would draw a different hand every run). Wired into
  Dissonance and Rag Tag, which account for all 11; any other game is one line at its `_start_new_game`.
  **How far that reaches differs by game, and the difference is the SIMULTANEITY, not the seeding.**
  Dissonance is turn-based, so its positions advance deterministically and a seeded run replays whole.
  Rag Tag is simultaneous, so `_position_key` legitimately includes WHO HAS ALREADY SUBMITTED (it has
  to — that is the stale-move guard) and whether the bot is scheduled before or after the human's
  submission lands still moves its seed: the DEAL is pinned, the bot's draft picks are not. Do not
  "fix" that by keying the bot seed on something staler; the guard needs the live position. It is why
  the Rag Tag block's checks are written to hold for ANY fighter, and why the two that cannot be are
  steered and asserted rather than sampled (below).
  **UNSET IN PRODUCTION**, where the unset path is the expression each caller used before — a bot that
  answers every identical position identically is one you can learn by rote, and a seat that could pin
  the deal in a hidden-info game would know the deal. `core/tests/test_deal_rng.py` guards both
  directions.
- **A seeded deal makes a CONDITIONAL check permanently vacuous instead of eventually covered, so it
  has to be steered and then ASSERTED.** Rag Tag's board-panel block has two checks that only fire if
  the drafted four include a ring (Joan) or Characters (the Fey Folk); the random draft used to reach
  them eventually, and pinning the deal parked one at zero for good. The harness now DRAFTS for them
  and fails if either count is zero — steering you cannot trust without the assertion, which was
  verified non-vacuous by dropping the preference and watching it go red. Check the same thing before
  seeding any other game's block: what was "sampled over many runs" becomes "fixed forever".
- **…but "red on a commit that cannot have caused it" is NOT automatically a seeding problem — check
  whether the gate is reporting a REAL bug it merely reaches intermittently.** Pages run #779
  (2026-09-05) went red on `dmCardFace`'s "nothing overflows" against a commit touching only Orbit
  files, which is the exact signature the seeding lesson above describes, and Dontminion's kingdom is
  indeed one of the last unseeded deals. Seeding it would have been the wrong fix twice over: it would
  have hidden a live product bug, and it would have broken `dmInfoModal`, whose re-deal loop needs the
  deal to actually vary (it re-deals up to 8 times for a board with both a landscape and an Artifact
  bearer, and FAILS rather than skipping). The real cause was `FitBodyText`'s ResizeObserver guard
  being **width-only while its fit criterion is a HEIGHT test** — its box is `flex:1` between the name
  and the foot, so `FitText` resizing the NAME changes the body's height with its width untouched, the
  refit is skipped, and the rules text is left spilling out of the card for good. Measured on a real
  board: 17 boxes changed height, 0 changed width, **0 re-fitted**, 8 piles overflowing.
  **`settleFits` is structurally blind to this** — a fitter that wrongly declines to refit is
  indistinguishable from one that has converged, so the font size is stable and the text overflows
  anyway. That is the transferable half: a settle-until-stable helper proves the page STOPPED, never
  that it is RIGHT, so a "did it settle" gate needs a companion that drives the input the resize path
  never varies on its own (here: change the names, hold every width, assert the bodies re-fit).
- **The gates hand their build to each other: `SCREENS_REUSE_BUILD=1` (set by CI and `.githooks/pre-push`)
  lets `screens` reuse the bundle `smoke` just built** — the same `vite build` was running twice. It is
  **verified, not trusted**: `runBuild()` rebuilds anyway unless `dist/` is newer than every source file
  under `webapp`/`games`/`shared`/`books`, so the build-first invariant survives a stale flag, a bailed
  smoke run, or an edit made between the two gates. Never replace that check with the flag alone.
- **The six non-shell games + Books are CODE-SPLIT** (`React.lazy` in Spender.jsx) — Spender itself is
  the shell, so it is not lazy. The entry chunk is ~310KB instead of ~600KB. Adding a game screen means
  a `lazy()` + `<Suspense>` branch, and a `SCREENS` entry in `webapp/test/screens.mjs`.
- **The WS throttle is process-global and keyed on client IP** (`core.rooms`, 60 connects/min,
  300 msgs/min). Test fake sockets all report `"unknown"`, so they share ONE budget: any test module
  driving `ws_room_player` MUST reset `_rooms._ws_connect_limiter` per test, or the suite eventually
  throttles itself and the failures look like anything but a rate limit (measured: 90 of 150
  in-process connects rejected without the reset).
- **Rust parity:** CoC — regen fixtures via **BOTH** `gen_engine_fixtures.py` (→ `games.jsonl`, feeds
  `python_fixture_replay`) **and** `gen_value_fixtures.py` (→ `values.jsonl`, feeds
  `heuristic_value_parity`), then `cargo test --release --features bridge`. The fixtures are
  **gitignored**, so on a fresh clone the gate fails with a `FAILED` that looks like a parity break and
  is really just a missing file — read the panic, it names the generator. Run the tools with
  `PYTHONPATH=<repo root>`. Spender — `cargo test --lib` (`src/bin/*` need `--features bridge`);
  Duel — `cargo test --lib` (37 lib tests); Dissonance — `cargo test --release --features bridge`
  (fixtures committed — and the ONE crate whose gate CI also runs, via `rust-dissonance.yml`, after
  its engine suite silently stopped compiling for a whole release).

---

## Footguns (grouped — the expensive-to-relearn traps)

**Shell / MSYS / worktrees**
- **Git Bash auto-converts `/c/...` args for native exes but SKIPS args containing `*`, `:`, or `;`** — so
  globs, `path:spec` gate args, and `a.csv;b.csv` reach the exe unconverted → silent no-op. Pass
  Windows-style `C:/...` paths (cygpath) to native tools.
- **`python -m pkg.mod` runs the CWD's worktree code, not `PYTHONPATH`'s** — always `cd <worktree>` before
  `python -m` / `cargo` / `wasm-pack` / `cythonize`. rustup is at `~/.cargo/bin` (off PATH → prepend it).

**Frontend / CSS**
- **CSS lives in real `.css` files, imported with `?inline`** (`games/*/X.css`, `shared/*.css`) — the
  string is still injected by each component's own `<style>` tag, only while mounted, so CoC's bare
  mount and its `html,body` reset are unaffected. This RETIRED the repo's most expensive footgun: CSS
  used to be a `const css = ` \` … \` template literal, where one stray backtick terminated the literal,
  reparsed the rest of the file as a tagged template, and blanked the page — it shipped a blank deploy
  twice. **Do not move CSS back into a JS literal.** The smoke test's backtick guard is kept as a net.
  `build.cssMinify` is deliberately **false**: keeping the emitted CSS byte-identical made the move
  provably behaviour-free (worth ~45KB if you ever turn it on deliberately, with a visual check).
- **Media-query cascade ordering**: mobile `@media` blocks sit BEFORE the base rules, so a single-class
  mobile override loses to a later equal-specificity base rule. Every mobile override must be
  higher-specificity (e.g. `.coc `-prefixed).
- Shared-kit CSS with `var(--token, fallback)` must be appended AFTER a game's `* {margin:0;padding:0}`
  reset (CoC's bare mount) or the reset zeros its padding.

**Backend / DB**
- **libsql has no `cur.rowcount`** → use SELECT-then-DELETE/UPDATE for any affected-row count (it 500'd
  the cancel endpoint).
- **Turso can't be tested locally** (no libsql wheel on Python 3.14) — validate via Render logs + a login
  surviving a redeploy.
- Never use a correlated subquery for `is_admin` (NULL on libsql); usernames are unique NOCASE.

**Cython (Spender `valuation3`)**
- **A compiled `valuation3.pyd`/`.so` SHADOWS the `.py`** — recompile (`cythonize -i -3 …/valuation3.py`)
  after ANY edit or workers silently run stale code. Prod builds its own Linux `.so` in the Dockerfile
  (build FAILS on miscompile, so a bad compile can't reach prod).

**Deploy verification**
- **Verify a Pages deploy by a CONTENT marker in the live bundle, not the filename hash** (CDN lag / Vite
  chunking can keep the hash looking unchanged). The `deploy-pages.yml` run status is authoritative.
- **A stale `vite preview --port 5173` process serves an OLD `dist/`** — kill listeners on the port before
  serving, confirm the fresh bundle by a content marker.
- **Never blind-push `staging:main`** — `staging` has DIVERGED (behind main on backends). A force-push
  would wipe main's backend history. To ship staging frontend, branch off `origin/main` and selectively
  take/merge only the intended files.

---

## Build + deploy

**The build is CI-owned — NEVER build or commit the frontend bundle by hand.** Pages source = "GitHub
Actions" (since 2026-07-05). `.github/workflows/deploy-pages.yml` fires on every push to `main` touching
the frontend (`webapp/**`, each game's dir, `shared/**`, `books/**`): a `build` job builds `webapp/`
(bakes `VITE_WS_URL=wss://splendid-nelz.onrender.com/ws`), runs the smoke gate, uploads via
`upload-pages-artifact`; a `deploy` job publishes via `deploy-pages`. It commits/pushes nothing. If deploy
flakes, re-run the workflow's `deploy` job. `gh-pages` branch + `docs/` are kept only as rollback nets.
**The deploy step's auto-retry WAITS 30s first, and that wait is the point of it.** Run 717
(2026-08-17) flaked at 18:34:45, retried at 18:34:46 and failed again at 18:34:48 — both attempts
inside three seconds, which is the same dice re-rolled within the same second rather than a second
chance, and it is the only Pages-backend failure that ever reached a red run. Do not "tidy" the sleep
away. (Deploy-side flakes are rare: 2 of 15 failures in 500 runs, and the other one, run 317, was the
run reporting failure after a retry that SUCCEEDED — fixed same-day by `continue-on-error`.)

```bash
git sync-main                 # ff the primary main worktree to origin/main (global alias)
# edit source only — do NOT npm run build, do NOT touch docs/ or gh-pages
git add <files> && git commit -m "..."
git push                      # deploy-pages.yml builds + publishes (~2-3 min)
```

- **Pre-push gate (opt-in, once per clone): `git config core.hooksPath .githooks`.**
  `.githooks/pre-push` runs the deploy workflows' own checks before a push that updates `main`
  lands: the Python suite for any non-docs change (matching `python-app.yml`, which has no path
  filter — and the suite reads `.jsx`/`.css` as text, so frontend edits genuinely can fail it),
  plus `smoke` + `screens` when the push can change the bundle (~80s for the pair — see Testing:
  screens runs in two lanes and reuses smoke's build; the `deploy-pages.yml` filter:
  `webapp/**`/`games/**`/`shared/**`/`books/**` minus `*.md` and Python `tests/` dirs). Pushes to
  other branches and docs-only pushes run nothing. `git push --no-verify` or `SKIP_GATES=1` skips
  it once; `GATES_DRY_RUN=1` prints what would run. It exists because nearly every red run in the
  2026-08-06/07 launch ledger was a gate that would have failed locally in about a minute. Caveat:
  `core.hooksPath` redirects ALL hooks to `.githooks/`, so personal hooks in `.git/hooks` stop
  firing — move them in if you have any.

- **Backend deploys to Render on push to main — but NOT on `**/*.py`.** `deploy-render.yml` carries a
  hand-curated path list, one entry per game, and **a game that is mounted in `app.py` but missing
  from that list is served in prod off whatever code an unrelated deploy happened to carry.** Orbit
  shipped without its entry and was found on 2026-09-05 running a build from the previous day with
  22 commits since — a rewrite of its server-authoritative `engine.py` passed every gate and would
  never have reached the server. **The symptom is silence, not a red run**, because no workflow fires
  at all. Adding a game to `app.py` means adding it here in the same push; the file also triggers on
  itself, so a fix to the list can actually land. The deploy job **verifies itself**: it
  polls `/health` until it reports the pushed commit and FAILS if that never happens.
- **The deploy hook returning 200 is NOT a successful deploy** (this cost a real gap): it only means
  Render accepted the request. A failed Docker build — the Dockerfile's Cython parity gate is *designed*
  to fail one — or a boot crash used to leave prod silently on the old code behind a green tick.
  `core/build_info.py` puts `commit` + `started_at` in every `/health`, and `deploy-render.yml` polls
  for the pushed SHA (falling back to "a process booted after we fired the hook", with a loud warning,
  if `RENDER_GIT_COMMIT` isn't set). A timeout means the build failed — check Render's logs; nothing was
  rolled back, prod is still serving the previous build.
- **Deploy preference (user):** land changes on `main` directly — don't hand over a PR (`gh` isn't
  installed; branch off `origin/main`, push `<branch>:main` to fast-forward).
- **COUPLED backend+frontend changes: use expand/contract, don't guess an order.** One push fires both
  workflows in parallel, and Pages caches the bundle ~10 min on top of that, so *some* client always
  runs the old frontend against the new backend. The old "ship backend first" rule only covers one
  direction — when the BACKEND adds a requirement the FRONTEND must satisfy, backend-first is wrong (the
  seat-binding release: a cached bundle omitted `session_token` on join, so re-entering your own seat
  answered "seat already taken"). Instead, in three pushes:
    1. **expand** — backend accepts BOTH the old and new shapes;
    2. ship the frontend that sends the new shape;
    3. **contract** — remove the compatibility path.
  Order-independent, zero broken window. The exception is a change whose whole point is to STOP
  accepting the old shape (closing a security hole): there the compat window *is* the vulnerability.
- **Stale-tab nudge**: the build stamps `__BUILD_ID__` into the bundle and emits a matching
  `version.json`; `shared/update-nudge.js` re-checks it on tab-focus and offers a Refresh.
- **WASM is a committed artifact** — CI does not rebuild Rust. Build with `wasm-pack build --target web
  --release --no-typescript`, copy `pkg/*.{js,_bg.wasm}` into `webapp/public/wasm/`, commit. **Same
  filename ⇒ browsers may serve the cached old wasm** (~10 min Pages TTL / hard-refresh). The crates are
  in **neither deploy path filter**, so committing one never deploys anything on its own
  (`rust-cores/dissonance-core/**` does trigger `rust-dissonance.yml` — a test job that deploys
  nothing). CoC is the
  exception where a *model* swap needs no rebuild (the `.bin` is fetched); Spender and Duel embed nets.
- **Render keep-alive** (free tier spins down ~15min idle, ~30-50s cold start): **TWO pingers on TWO
  providers, and the split is the design.** `keepalive-worker/` is a Cloudflare Worker cron firing
  every 5 min — reliable, so the box should never reach the 15-minute idle timeout at all;
  `keepalive.yml` (GitHub Actions) runs long-lived (~90min) jobs HOLDING the connection open and
  retrying through the spin-up 503s (`curl --retry-all-errors` + long `--max-time`, like a browser),
  which is what completes a wake (~7s) once the box IS cold. **Key lesson (do not regress):** a SHORT
  30s pinger is worse than nothing — it disconnects mid-spin-up and ABORTS the wake, which was the
  actual cause of the 7-9am outages (not "GitHub fired late").
  **The SECOND lesson, and the reason there are two providers: the ping was never the weak part — the
  SCHEDULER was.** GitHub drops over half of all scheduled firings and whole hour-bands go dead for
  weeks; UTC 13 and 14, which held every pre-7am warm-up, fired ZERO times from 2026-08-27 to 09-06,
  a re-registration push did not revive them, and measured warm coverage was **39%** with the box cold
  every morning 06:00-~09:30 local. Redundancy inside one scheduler cannot fix that, which is what the
  three "INDEPENDENT" attempts (all inside 13:00-14:59) proved by failing together.
- ⚠ **The warm window is an INSTANCE-HOUR BUDGET, not a preference — never make it 24/7.** Render's
  free tier gives **750 instance-hours/month per workspace, shared across every free service**, and
  exhausting them SUSPENDS the service until the next month. A month is ~730h, so round-the-clock
  warming spends the whole allowance and takes the site down outright if a second free service exists.
  Both pingers therefore warm ~13:00-06:59 UTC (~18h/day ≈ 548h/month); overlapping them costs nothing
  extra (hours are counted on the service being up, not on who woke it), but widening either does.
  `core/tests/test_keepalive_budget.py` guards it, and also pins that both pingers point at the SAME
  backend URL — a URL changed in one and not the other is a green workflow warming nothing.
- **The $7/mo Starter tier remains the only *guaranteed* fix**, and is explicitly declined (user
  directive, 2026-09-06). Don't propose it again; propose another free scheduler instead.
- **Staging** (Cloudflare Worker `webprojectsstaging.forry4.workers.dev`, tracks the `staging` branch,
  reuses the prod backend) — test frontend/layout changes on a real URL first. Local↔Cloudflare bundle
  hashes differ; verify by served content. Use vs-AI games so test data stays private.

### Querying the prod DB directly
Turso creds live in gitignored `C:\Users\Forrest\.spender_turso`; query via `curl` POST to the libSQL
HTTP `/v2/pipeline` (no libsql wheel needed — use a BOUND arg for an id; a double-quoted SQL id is read
as a column). Note `list_user_games` excludes `status='over'` — query the DB directly for finished games.

---

## Design decisions & hard-won conclusions (do not relitigate)

**Product/design**
- Noble-path commitment is rejected — the AI must never LOCK onto a noble target; noble value is instead
  scaled inversely with board efficiency (few efficient L2/L3 targets ⇒ go wide on L1 ⇒ nobles come free).
- **Strategy model** (from a strong human, informs AI feature design): backward-plan from cost-effective
  high-point targets (5/8, 4/7, 3/6 deals); scarcity → nobles; contested cards are worth more
  (acquisition + denial); endgame denial (reserve a card the opponent is one buy from).

**AI strength (the campaigns)**
- **Eval-weight tuning is saturated** — one gain (learned weights 0.725 vs original), nothing since.
  Static eval accuracy plateaus ~0.65 regardless of model class or features; the missing info (future
  draws, deep lines) needs LOOKAHEAD, not a better static eval.
- **Search was the bottleneck, and it's been realized** — Spender variant S then variant N each broke the
  plateau via search + better inductive bias; CoC's r2 net serves via netval search; Duel's coherent +
  minimax fixes did it again in 2026-07. The remaining lever after search saturates is the training
  DISTRIBUTION.
- **Self-play is blind to tactics the opponent never demonstrates** (denial/racing/development) — a
  documented blind-spot class. Every "ceiling" or "exhausted" verdict in the research log is CONDITIONAL
  on the net + encoder that produced it — **re-run the probes if the net materially changes.**
- **The AZ degenerate-equilibrium fix** (reward shaping so a 0-0 tiebreak game becomes neutral, not a
  buy-nothing reward) is the most important single AZ finding.

---

*Full AI campaign history, dated sessions, and rejected-experiment postmortems:*
[`docs/ai-research-log.md`](docs/ai-research-log.md).
