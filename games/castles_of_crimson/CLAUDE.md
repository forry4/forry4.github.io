# Castles of Crimson (Castles of Burgundy port) — package notes

2–4 player faithful port (human-vs-human seats 2–4; vs-bot games stay 2p). Mounted at `/coc`. LIVE on
prod. **Now a 4-animal CoB port** (chicken added; monastery 6 = spend 1 silver → 2 workers; boards 2/4 =
2019 layouts). See the root `CLAUDE.md` for the room-server invariants and deploy.

---

## Engine contract (`engine.py` — single source of truth for server, bot, tests, AI)

- `new_game(player_ids, names=None, seed=None)` — deterministic given seed.
- `legal_moves(game, pid)` — normal die-actions AND pending sub-decisions.
- `apply_move(game, pid, move) → (ok, err)` — validates + mutates in place; ALL scoring / replenish /
  phase-turn lifecycle / pending logic lives here.
- `is_over` / `final_scores` / `winner`.
- **RNG persisted in `game["rng_state"]`** (JSON-safe lists) so per-phase depot replenishment + dice stay
  reproducible across save/load. The whole game dict is JSON-safe (no sets).
- **Pending sub-decisions are game-state keys** (`pending_pid`/`pending_kind`/`pending`), server-enforced
  and reconnect-safe. Kinds: `extra_action`, `ship_choose_depot`, `ship_adjacent_depot`,
  `building_take_choice`, `warehouse_sell`, `townhall_place`, `goods_pick` — each also accepts
  `skip_pending` (bot/engine never deadlock). A new pending kind needs a matching frontend `PendingModal`
  block or the human can't resolve it.
- Move types: `take_hex`/`place_tile`/`sell_goods`/`take_workers`/`buy_black`/`adjust_die`/
  `discard_storage`/`end_turn`/`monastery6_take` + the pending resolvers.
- **Rulebook-fidelity invariants locked by tests** (do not "simplify" away): seat-dependent starting
  workers; the exact base-game hex supply; black depot refills 2×players per phase (4/6/8 for 2/3/4p via
  `tiles.black_fill`; `BLACK_FILL_2P`=4 is legacy-2p-only); starting castles never score; monastery 5
  *chooses* the adjacent depot.
- **House variant — fixed depot layout** (`tiles.DEPOT_PLAN`): each numbered depot refills each phase with
  two hex tiles of fixed TYPES (the specific building/monastery still varies by seed). Locked by tests.
- **Shadow VP ledger** (`region_vp`/`color_vp`/`livestock_vp`) is telemetry OUTSIDE the canonical
  projection — for AI aux training only; don't fold it into `proj`/parity.
- **`turn_undo` stores a log POSITION, not the log.** `_snapshot_turn` excludes `moves` and keeps
  `moves_seq` (a monotonic count of records logged); undo rewinds by dropping the records added
  since. It has to be a counter and not a length because `_log` PREPENDS and caps by evicting the
  tail — at the 2000 cap the length stops moving and a length delta would restore nothing. The
  snapshot is persisted with the game, so the old full copy was half the stored blob.

---

## At-rest compaction (`persist.py`)

`state_json` is compacted on the way into the DB and expanded on the way out — **`_encode_state` /
`_decode_state` in `main.py` are the only codec call sites, and every read must funnel through them.**
Tiles become `[id_number, shape_index]` against a per-blob shape table, and `rng_state`'s 625 Mersenne
words pack into base64. Measured on 5 played-out games: **-56% raw dict, -41% stored** (on top of the
shared zlib layer in `core/rooms.py`).

- **It is a persistence boundary ONLY.** The live dict, the wire, the engine, the bot and the Rust
  parity fixtures all still see full tile objects. That is deliberate — the tile `id` is load-bearing
  in both directions (engine moves address a tile by `tile_id`; the frontend's flyer animation tracks
  a tile across locations by its id), so compacting the live dict would be a wire break for a disk win.
- **Tile locations are enumerated by hand, not walked generically** — a "looks like a tile" walk would
  also run over `rng_state`'s int list and `track`'s pid lists, where a false positive is a corrupt
  save. `tests/test_persist.py` asserts the list still covers every tile in a played game; that check
  is what found `moves[].tile`, which reading `new_game` misses.
- **Two counter-intuitive findings — do not relitigate:**
  1. **Measure after zlib, not before.** `rng_state` is 8% of the raw dict but 22% of the compressed
     one (incompressible noise surrounded by ~8x-compressible JSON).
  2. **Transform BOTH copies of a key or neither.** The game and its `turn_undo` hold near-identical
     `rng_state`s and zlib was already collapsing the second. Packing only the live copy destroyed
     that dedup and made the blob *bigger* than not packing at all (-37% → -17% in the A/B).

---

## AI tiers — lobby Easy / Hard / Expert

| Tier | What it is | Where it runs | Lever |
|---|---|---|---|
| **Easy** | server determinized-MCTS bot at its strong config (`ai.play_turn_plan`) | server thread pool | sims/time budget |
| **Hard** | the first netval champion net (`coc_pv_model_hard.bin`) | **client WASM** (`coc-core`, netval leaf) | which net bin |
| **Expert** | the r2 champion **fine-tuned on the BGA expert corpus** (`coc_pv_model.bin`) | **client WASM** (netval leaf, ~20k sims) | which net bin |

- **netval leaf** = net policy prior + a short priority rollout + the net VALUE head at truncation
  (`NETVAL_ROLLOUT_STEPS=30`, `NETVAL_C_PUCT=1.0`). CoC is a delayed-payoff game, so a 0-step static leaf
  undervalues in-flight turns — the short rollout is why netval works (see research log). This is the
  OPPOSITE of Spender/Duel, where a static leaf wins; the repo has opposite precedents on purpose.
- **Serving mirrors Spender:** per-decision `ai_search` (compact state, undrawn pools sorted) → client
  searches → `ai_move`; watchdog `CLIENT_AI_TIMEOUT=8s` → falls back to the server hard bot.
- **Model upgrade = no wasm rebuild:** `python rust-cores/coc-core/tools/pv_json_to_bin.py <winner.json>
  webapp/public/wasm/coc_pv_model.bin` + push. The net blob is fetched (browser-cached), not embedded.
- Campaign status, ceiling verdicts, and the BGA-mining line: `docs/ai-research-log.md`. Every
  "exhausted" verdict there is CONDITIONAL on the current net + its frozen encoder — re-run the probes
  if the net materially changes.

---

## Frontend (`CastlesOfCrimson.jsx`) — durable facts

- Self-contained; mounted at `screen === "coc"`; namespaced localStorage (`coc_*`); WS/HTTP derive `/coc`.
- **2–4 players + 3-column game screen** (`.coc-game-cols` grid `board | your duchy | opponent duchy` at
  ≥1280px): a 2p game shows the board + BOTH duchies at once; **3–4p games add opponent peek tabs**
  (`.coc-opp-tab` + `viewOppId`) to switch which opponent duchy is shown. Player count is host-chosen
  (create-modal 2/3/4 selector + a **Same board** toggle → backend `max_players`/`same_board`); depots, the
  2-col black depot, and the turn-order track all scale to N, and the board height is measured + pinned so
  it never grows with content. Layout math (depot pinning, black-depot clearance, storage zoom-to-fit) is
  in the research log.
- **"burgundy" is the DATA KEY, "crimson" is the display name — do NOT rename the key** (it's persisted in
  saved games AND generated into the Rust parity tables). Only the display maps burgundy→crimson.
- **Depot ghost outlines** (memory aid): a taken hex leaves a faint colored hex rim in its planned slot.
  Uniform rim = fill + an inner hex shrunk by a true perpendicular offset (correct only because tiles are a
  fixed 70×81, uniformly zoomed).
- **Monastery benefit icons**: each of the 26 monasteries shows a pictogram (`MONASTERY_ICON`); goods are
  barrel-shaped; the color-bonus chip is the shared `BonusTileBadge`.
- **Mounted bare (no baseCss)**: CoC resets `html,body{margin:0;…;background:#120c0d}` scoped to while it's
  mounted; its reset only targets `.coc *`. Append shared-kit CSS AFTER the `.coc *` reset so the reset
  can't zero its padding.
- **Board-column `zoom`** (`.coc-board-hex` zoom .85 @≥1280 / 1 @≥1600): percentages inside a zoomed
  element already resolve in zoomed units — `width:100%` fills; `width:calc(100%/zoom)` double-compensates.
- **The board's height floor is a height taken from the viewport's WIDTH (`38vw`), so it is bounded on
  BOTH axes or the game screen grows a scrollbar for room nothing asked for.** Two bounds, both in
  `max(min(38vw, 684px, var(--coc-board-cap)), var(--coc-board-minh))`: `684px` is 38% of the wrap's
  1800px max-width — past 1800 the board column stops getting WIDER, so `38vw` only stretched the depot
  ring vertically into empty gaps (at 2560 it asked 973px to hold the same 619px-wide ring it draws at
  1800) — and `--coc-board-cap` is the height this window actually has left, measured in the layout
  effect. The chrome it subtracts is MEASURED (`wrap - cols` rects), not totalled by hand: the hand
  total was 6px short, which is exactly the scrollbar it exists to avoid. Same lesson in the column
  sync — the log's 130px floor gives way to 60px before the PAGE scrolls, because those rows scroll
  internally anyway. `--coc-board-minh` beats both through the `max()`, so a ring that genuinely needs
  the height still gets it and the page scrolls, correctly (a 4p ring wants ~935px). Regression-gated
  in `screens.mjs`'s `offlineCoc` at 2560x1600/2560x1000/1920x1080/1707x948 — the last is a 2560x1600
  panel at 150% OS scaling, i.e. the size a user reports as "2560x1600".
- **Mobile media-query ordering**: mobile `@media` blocks sit BEFORE the base rules, so every mobile
  override must be higher-specificity (`.coc `-prefixed) or a later base rule wins.

---

## Serving & reliability (do not regress)

- `main.py` mounts `coc_app` at its tail behind try/except; imports auth/DB directly from `core`.
- **Auto-reconnect is load-bearing** — a vs-bot turn is re-driven only when the client reconnects, so a
  Render cold-start / iOS backgrounding that drops the socket froze the bot's turn until manual refresh.
  `useSocket` has a backoff reconnect loop (reconnects with the **`reconnect` action, not `join`**) +
  a `visibilitychange` nudge + a `socketReady()` guard (don't abort a still-CONNECTING cold-start socket).
- **Building-placement highlight** reproduces `_building_town_ok` client-side (one building type per
  same-color region unless you own monastery effect 1) so the legal-glow matches what the click accepts.
- **The WASM worker pool must not take every core** — `hc<=4 ? hc-1 : min(hc-2, 8)`. CoC shipped without
  this for months and pegged every core on a 4-core machine.
- **`turn_undo` is in `mk_room_state`'s `_HIDE` list and must stay there.** It is a whole-game snapshot,
  so it carries its own copies of `supply`/`black_supply`/`goods_supply`/`rng_state` and shipping it
  defeated the redaction of all four — measured at 100 ordered supply tiles (the exact future depot
  refills) plus `rng_state` (every future die for BOTH players) reaching the client on a mid-game
  broadcast. Same leak class as the 2026-07 audit, which fixed the top-level keys and missed the nested
  copy. The frontend never reads it — the Undo button derives from client-side `actedThisTurn`.
  `tests/test_token_scope.py` now searches the whole SERIALIZED payload of a REAL in-progress game,
  because the older synthetic-dict test could only ever prove the top level was clean.

---

## Tests

`tests/` (~319: board invariants, placement, scoring, lifecycle, one-per-monastery, endgame) +
`test_client_ai.py` + `test_ws_auth.py`. **Python↔Rust differential parity** — regen fixtures via
`gen_engine_fixtures.py`, then `cargo test --release --features bridge` in `rust-cores/coc-core`.

---

## Offline vs-AI mode (`offline.js` + the shell's `/offline` hub)

CoC is playable **fully offline** (installed PWA, airplane mode): the browser is authoritative —
the save is the SAVE ENVELOPE `{state, ids}` (full-fidelity Rust State incl. ordered pools + rng,
serde via `coc-core/src/dump.rs`, PLUS the tile-id LEDGER) in IndexedDB, and every step is a
stateless call into the engine already in `coc_core_bg.wasm`. Hard/Expert only (the wasm tiers).

- **The tile-id ledger** (`coc-core/src/gamedict.rs`) exists because Rust State deliberately has
  no tile identity while the JSX addresses moves by `tile_id` and tracks flyers by stable ids:
  it mirrors every VISIBLE container, ids follow tile codes between containers on each apply
  (code-matched reconciliation; identical-code swaps are harmless), supply emergences mint fresh
  ids ("oh"/"ob" prefixes carry blackness — a black market shares a colored market's code).
- **Render = the WIRE dict** (engine dict minus `_HIDE`), emitted by `gamedict::to_game_dict`
  with `bonus_vp` (a shadow field on PlayerState, outside the parity projection like `region_vp`)
  recovering `claimed_bonus`. Parity-gated by `tests/gamedict_parity.rs` against the REAL Python
  wire over random games (one shared canonicalizer for ids/order/provenance — its header lists
  what's erased and why each is safe), plus a `to_proj` round-trip gate and an offline-apply soak.
  Fixtures: `tools/gen_gamedict_fixtures.py` — the wire snapshot MUST be deepcopied (a shallow
  copy serializes every record as the final position; caught exactly that way).
- **Search input stays redacted**: `ai_search.state` is `gamedict::to_proj` (pools SORTED, no rng)
  — the offline AI can't read hidden state the client physically holds, same strength as online.
- **The driver** (`offline.js`) mirrors `_client_bot_turn`: per-decision loop, single-legal moves
  apply directly (paced ~1s), else it arms `ai_search` and the component's EXISTING search loop
  plays the decision, sinking the compact move back through the driver (validated in wasm against
  `legal_actions_full` — NOT the search-pruned set). Human moves go engine-dict → compact (tile_id
  resolved via the ledger) → micro chain. Log events are diff-synthesized in Rust per apply
  (rolls, phase ends, area completions, bonus tiles, livestock, track, mine income); log-side
  bookkeeping (`t` stamps, undo snapshot AS A COPY — same rationale as Spender offline) is
  driver-side. `vp_breakdown` degrades to empty offline (it replays the server log).
- **Component forks** (`CastlesOfCrimson.jsx`): the `offline` prop mounts a record with no socket;
  `mv` + the `ai_move` sink fork into the driver; `inLiveGame`/deep-entry/popstate gate on it; the
  shell owns `/offline/<id>`. **roomData must be published BEFORE the screen flips to "game"** —
  the game render assumes `game` exists (the online flow sets both from one message; violating it
  blanked the screen with a TDZ-style crash, caught by the screens scenario).
- **Engine worker** = the same `coc-worker.js` with `?engine=1` (skips the model fetch, so engine
  calls work offline even with no model cached; search pool workers load models as always). The
  hub's offline download precaches the coc wasm + BOTH model bins and warms the `/coc/boards`
  localStorage cache (the game screen hard-gates on it and the SW can't serve localStorage).
