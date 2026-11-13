# Spender (Splendor) — package notes

The original game and the site shell. Backend is a `router` included by the root `app` (no separate
Spender server); `games/spender/app.py` is a deploy shim re-exporting the root `app`.
See the root `CLAUDE.md` for the layering rule, room-server invariants, and deploy.

---

## Rules — `engine.py` (the single source of truth)

`apply_move(game, pid, mv) -> (ok, err, effects)`, mirroring CoC/WW/Duel. Mutates in place, returns
`(False, "reason", {})` untouched on an illegal move, and reports sub-decisions via
`effects["discard_pid"]` / `effects["noble_choice_pid"]`. Imports only the `cards` leaf — no FastAPI,
no DB, no rooms. **Historically these rules lived INLINE in the WS handler and nothing tested them**
(the suite covered helpers + the MCTS simulator, and the parity chain tied the AZ engine and the Rust
port to each other, never to the live path). `tests/test_engine_rules.py` drives this module.

**Card data + the pure cost maths live in the leaf `cards.py`** — imported by both the engine and the
AI stack, so `ai/serving/*` no longer reaches up into the web module for it.

**Move handler error hierarchy** (order matters — enforced in `engine.apply_move`, except the first
three which are ROOM-level and stay in `main.py`'s WS handler):
```
not game        → "game not started"        (room-level, main.py)
status "over"   → "game is over"            (room-level, main.py)
status not playing → "game not started"     (room-level, main.py)
phase "over"    → "game is over"
turn != pid     → "not your turn"
pending_noble_pid == pid & type != pick_noble  → "must choose a noble first"
pending_discard_pid == pid & type not in (discard, undo_discard) → "must discard down to 10 gems first"
```

---

## Backend (`main.py` → `router`)

- Rooms/WS/persistence/AI dispatch + the original MCTS bot live here; rules are `engine.py`, card data
  is `cards.py`, and `ai/` holds all AI data + the AZ/heuristic stacks.
- **At-rest compaction (`persist.py`)** — `state_json` is compacted going into the DB and expanded
  coming out; **`_encode_state`/`_decode_state` in `main.py` are the only codec sites and every read
  must funnel through them** (7 read paths do). Cards and nobles are stored as bare ids and rebuilt
  from `cards.card_catalog()` / `ALL_NOBLES`, which the move log and `setup` snapshot always did and
  the live `board`/`decks`/`nobles`/`purchased`/`reserved` never did. **-65% stored** (1,858 → 662),
  raw 11,219 → 4,355. Two things keep it honest: a card is replaced by its id **only when it
  round-trips exactly**, because `_apply_reserve` stamps `from_deck` on a blind deck reserve and a
  naive encode would drop it; and the card locations are enumerated by hand, because `moves` and
  `setup` already hold bare id STRINGS and a generic walk would "decode" those into card objects and
  corrupt the log. `pre_discard_snapshot` is a whole second copy of the game and is compacted too.
  `ai/serving/replay.py` calls `expand_state` so a dumped row still loads offline.
- **Retired AI variants (Z, H) live in `ai/serving/legacy_variants.py`** — retired means no lobby
  offers them, NOT dead: `ai_variant` is persisted, so an old saved game must still get a real move on
  its next AI turn. That is also why they are in `ai/serving/` and not `ai/offline/` (which the server
  never imports). Weight variants A/B/C/C2 are pure data (`weights*.json`) fed to `_mcts_choose_move`.
- **The undo snapshot is taken ONLY when the action actually overfills** (`_snapshot_if_overfilling`).
  It used to be an unconditional `deepcopy` on every `take_gems`/`reserve` — which was ~97% of the
  move's cost, so the common path is now ~30× faster (0.35ms → 0.011ms). The prediction is EXACT, not
  heuristic: tokens are integers, a take adds one per gem, a reserve adds one gold only if the bank
  still has one. `_settle_or_discard` ASSERTS a snapshot exists whenever it parks a discard, and a
  fuzz test drives random legal games through that assert — a wrong prediction would strand a player
  mid-turn with a dead Undo button, so it fails loudly rather than silently.
- **Pending state in the game dict** (`pending_noble_pid`, `pending_discard_pid`) is set when the
  condition arises, cleared when resolved, and rejects any other move meanwhile. Frontend derives
  `needsNobleChoice`/`needsDiscard` from these keys (not message fields).
- **Discard undo**: an action overfilling past 10 gems deep-copies the pre-action game into
  `g["pre_discard_snapshot"]`; the modal's "↩ Undo turn" (`undo_discard`) restores it. Popped on normal
  completion; part of saved state so undo survives reconnect.
- **`ai_variant` is persisted** and restored on load (with a back-compat recovery from the `"AI (X)"`
  display name) — else a redeploy silently downgrades a vs-AI game to variant A.
- **Client-net discard routing (split-brain fix, do not regress):** on the website, N's PLAY move is
  searched client-side but an over-cap discard was historically finished by the server `_ai_discard_one`
  heuristic — a DIFFERENT brain than the net → the take→discard→re-take loop. Fix: `_run_ai_turn(...,
  defer_discard=True)` (client path only) sets `pending_discard_pid` and RETURNS without finishing; the
  existing `mk_room_state` `ai_search` block ships the DISCARD-phase state, the ply-keyed client effect
  re-searches and submits a `discard` `ai_move`. `_schedule_ai_discard_fallback` (ply-guarded, 15s) lets
  the reserved-aware heuristic finish on any client failure. Only benefits N (S one-hots H3 discards).
- **Move log is id-only + a static catalog** (`card_catalog()` resolves id→card; deck is fixed), cap 500
  → the whole game logs. Blind-reserve redaction strips `card_id` (the id reveals the card via the catalog).
- **Game reconstruction / review** (`ai/serving/replay.py`): `_capture_setup(g)` snapshots the dealt board +
  deck order + nobles into `g["setup"]` at creation (stripped from the wire, persisted), and discards are
  logged — together these make a finished game replayable move-by-move and re-scorable. `GET
  /games/{id}/review` (player-only) returns per-turn snapshots; the frontend renders a read-only rewind.
  Games created before `setup` shipped show only the final board.

---

## AI tiers — what actually changes

Lobby exposes persona pills mapping Easy→Expert. Internally there's a variant zoo; the ones that matter:

| Tier / variant | What it is | Where it runs | Lever |
|---|---|---|---|
| **N** (Expert / "Nina") | card-set **attention** net (`net_attn_3`) in determinized PUCT | **client-side WASM** (`spender-core`), ~20k sims/move; server-S fallback | the net; a 21-pt game auto-swaps to a 21-pt-trained net |
| **S** (strong search) | `v_state` V(state) leaf + determinized PUCT + H3 policy prior | client-WASM or server thread pool | sims budget (proven #1 lever); Cython-compiled leaf |
| H / H2 / H3 | 1-ply greedy heuristics (`take_value` / turns-horizon) | server | eval weights only |
| A / B / C2 / Z | MCTS with heuristic weight sets / older AZ numpy net | server | weights / net |

- **Serving:** on the AI's turn the server ships `ai_search` (the AI-perspective compact state) in room
  state; the browser worker pool searches and submits `ai_move`; the server validates it's in
  `legal_actions` and applies it. `CLIENT_AI_TIMEOUT` (15s; raised for N's heavier WASM worker) → server
  computes the fallback. Discard/noble finishes are routed to the client net too (`defer_discard`) so ONE
  brain decides take+discard. Absent a WASM client it's byte-identical to server play.
- **21-pt "Long" mode** is a per-game `win_points`; any picked AI auto-adapts, and N/S have 21-pt
  specializations (a 21-trained net; a `turns_table_21.json` horizon).

---

## AI stack (`ai/`)

Organized into three clearly-separated subpackages (the old 70-file `ai/az/` dump was split so the
deployed brain is legible and offline probes can't trigger a backend deploy):
- **`ai/serving/`** — the deployed brain `main.py` imports at runtime: `engine`, `actions`,
  `heuristic{,2,3}`, `valuation{,2,3}` (`valuation3` = the Cython hot leaf), `v_state`, `vsearch`,
  `mcts`, `infer_np`, `replay`, `distill_features`, `features` + the `turns_table*.json` data. Along
  with `ai/models/`, this is a `deploy-render.yml` path-filter trigger (`ai/offline/` is deliberately
  NOT). `valuation3` reads its `turns_table*.json` and (experimental) `leaf_model.npz`/`vsearch_s21.json`
  from this dir via `dirname(__file__)`.
- **`ai/offline/`** — the research toolkit (never imported by the server; imports the serving stack via
  `from ..serving import …`): the AZ training stack (`train_az`/`selfplay`/`league`/`net*`), the
  `h2_*`/`h3_*`/`s_*`/`vsearch_*` campaigns, `arena`/`bench`/probes/distill/bootstrap, `s_checkpoints/`,
  and the `FEATURES_V4.md`/`H2.md` campaign notes. Editing anything here does NOT redeploy the backend.
- **`ai/models/`** — the committed model artifacts loaded at import by `main.py`: `weights*.json`
  (variants A/B/C/C2/tactics/targeting), `az_model.npz` (variant Z), `value_model.json`.

The current deployed Expert is variant **N** (attention net, client-WASM). The learned weights, the
AlphaZero stack (variant Z), heuristics H/H2/H3, variant S, and the whole strength campaign that produced
them are documented in `docs/ai-research-log.md`. Offline tooling entry: `python -m games.spender.ai.train`
(writes `ai/models/weights.json`); the many benches live in `ai/offline/`.

**Cython footgun:** a compiled `valuation3.pyd`/`.so` SHADOWS the `.py` — recompile
(`cythonize -i -3 …/valuation3.py`) after ANY edit or workers silently run stale code. Verify
byte-identity via the build-gate tests + the `engine_value` signature hash. Prod builds its own Linux
`.so` in the Dockerfile (build FAILS on miscompile, so a bad compile can't reach prod).

**Rust→WASM serving core (`rust-cores/spender-core/`) — durable architecture:** a pure-Rust port of the
engine + `v_state`/`heuristic3`/`vsearch`/`mcts` + `feats` (attention tokenizer) + the action↔move-dict
bridge, compiled with `wasm-pack --target web`. Validated bit-exact against Python (engine, leaf, policy,
move bridge; Rust-S ≈ Python-S at 0.50). Deploy = `cd rust-cores/spender-core && wasm-pack build --target
web --release --no-typescript` → `cp pkg/spender_core.{js,_bg.wasm} ../../webapp/public/wasm/` → commit
those two files (CI does NOT rebuild Rust; the wasm is a committed artifact) → push. **Same wasm filename
⇒ browsers may serve the cached old wasm** (~10 min Pages TTL / hard-refresh). The crate is in **neither**
CI path filter, so committing it never deploys anything on its own.
The four embedded nets (`n_model`/`pv_model`/`pv_model_21`/`attn_model`) ship as the **bincode of the
JSON's parsed f32s** (`include_bytes!` of `src/*.bin` — ~3x smaller wasm, bit-identical weights; see
`src/models.rs`); the `.json` stays committed as the training-side source. **A net swap = replace the
JSON + `cargo run --release --features bridge --bin gen_net_bins` + rebuild** — the models.rs stale-bin
test fails until the bins are regenerated, so a stale bin can't ship inside a green build.

---

## Puzzle mode (`puzzle/` — LIVE on prod)

The player is dropped into one position and must find the single move N most favours. Reached from the
home-menu 🧩 button; backend is static (no serve-time AI).
- **Two `kind`s:** `win` (scripted forced-win, multi-move — kept but NOT surfaced live) and `advantage`
  (the shipped single-move "only-move" puzzles). The frontend filters to `advantage`.
- **A puzzle = a position where ONE move's N eval beats every other by a margin IN RANGE** (buy/reserve
  `[0.25,0.50]`, take `[0.25,0.60]`). The upper bound rejects obvious blowouts. The eval of a move = apply
  it + re-search the child, **averaged over K=8 independent determinization seeds**. Answers must not force
  a discard/noble sub-step.
- **Serving** (`serve.py`, `setup_puzzles` in `app.py`): `GET /puzzles` (listing incl. `answer_type`) +
  `GET /puzzles/{id}` (embedded per-step snapshots + every move's N eval). Frontend draws by a weighted
  type mix (`PUZ_TYPE_WEIGHTS` 60% buy / 15% take / 25% reserve), tracks a `spender_puzzle_seen` set,
  shows a category-only hint popup; the exact move is behind Answer.

### Hard-won puzzle findings (do not relitigate — full detail in the research log)
- **Multi-move "hold the advantage" chains don't exist in Splendor** (positions branch too much) — only
  single-move puzzles are viable.
- **You can't select puzzles from the self-play search's per-move numbers** — PUCT starves alternatives
  (1–5 visits → their Q is noise); you MUST re-search each alternative to prove the gap. Generation is
  inherently slow.
- **A single search's VALUE is noise-dominated for open positions** (seed spread ~0.42) — average K
  independent searches. Take-gems answers are the noisy ones; buy/reserve stable.
- The `n_eval_server` returns `value=0.0` for DISCARD/NOBLE-phase roots — expand hero sub-decisions to
  PLAY/OVER leaves (max-of-means) before certifying a gap.
- N's real play is fine (~20k sims, picks by visit count) — this was puzzle-tooling noise only.
- **Candidate LEDGER** (`puzzle/candidates/candidate_ledger.jsonl.gz`) persists every verified position's
  K=8 move-evals so a threshold change is a pure re-filter (`rebuild_from_ledger`), zero recompute.

---

## Offline vs-AI mode (`offline.js` + the `/offline` route)

Spender is playable **fully offline** (airplane mode, installed PWA): the BROWSER is authoritative —
the saved game is the compact-state JSON (the same Dump shape the search consumes), and every step is
a stateless JSON→JSON call into the Rust engine already in `spender_core_bg.wasm`. Purely local by
design: no server row, no history, no sync. Games vs the client-WASM tiers only (S/N).

- **Rust side** (`rust-cores/spender-core`): `src/dump.rs` (State ⇄ Dump JSON, both directions) and
  `src/gamedict.rs` (State → the incumbent render game-dict, WITH the server's per-viewer
  blind-reserve redaction), exposed as four stateless wasm exports — `new_game_json` /
  `legal_moves_json` (→ `[{action,move}]`) / `apply_action_json` (validates membership; sub-decisions
  resolve inside the 70-action space) / `game_dict_json`. **Parity-gated**: `tests/gamedict_parity.rs`
  compares against Python `to_game_dict` + the real `main._redact_blind_reserves` per sampled ply
  (fixtures: `tools/gen_gamedict_fixtures.py`, run with the repo root on PYTHONPATH); `tests/new_game.rs`
  gates the deal by INVARIANTS (partition/bank/nobles + a playout soak), deliberately not Python-seed
  parity. These lib modules are `bridge`-feature-gated like the serde bins → `cargo test --features bridge`.
- **Driver** (`games/spender/offline.js`): owns the IndexedDB record (`shared/offline-db.js`, DB
  `forrest-offline`) — `{id: LOCAL…, dump, mySeat, aiVariant, winPoints, moves, status, undo, seed}` —
  and mirrors main.py: legality by legal-moves match (never raw apply), newest-first log cap 500,
  pre-take/reserve undo snapshot restored on `undo_discard` (persisted, survives reload), AI noble
  auto-pick (the `_run_ai_turn` behavior — the search never sees NOBLE roots), AI discard re-dispatch
  (the defer_discard flow). It runs the engine in its OWN lazy module worker (the hub needs engine
  calls before any search pool exists; one extra instance, idles during search).
  **The undo snapshot deliberately COPIES the move log**, diverging from the root CLAUDE.md
  "store a position, not a copy" rule: this log PREPENDS and caps — exactly the shape where that
  rule's own caveat says a length delta silently restores nothing (the CoC trap; a counter would
  work but buys nothing here) — and the copy is transient (cleared when the turn completes) and
  bounded (≤500 tiny entries in ONE overwritten IDB record), so the server-side every-save
  blob-growth rationale doesn't apply. Do not "align" it.
- **Shell** (`Spender.jsx`): `/offline` = hub (create/resume/delete + the offline-asset download),
  `/offline/<LOCALID>` = a save; the game screen renders a puzzle-mode-style synthesized `roomData`
  whose `ai_search` is built locally, so the EXISTING worker-pool dispatch plays the AI unchanged —
  the one `ai_move` send has an offline fork into the driver. The boot never waits for the backend on
  any route now (root `CLAUDE.md`, "THE FIRST SCREEN NEVER WAITS FOR THE SERVER"); `/offline` also
  skips the background session check, and the waking notice carries the "Use offline" door. `offlineRef` guards the visibility reconnect exactly like `puzzlingRef`.
- **Service worker**: source moved to `webapp/sw.js`, emitted by `vite.config.js` with a
  `__BUILD_ID__`-stamped cache name (each deploy's `activate` drops the old cache). The hub's
  "Download for offline" sends `PRECACHE_OFFLINE` → the SW `cache:"reload"`-fetches the wasm trio +
  fonts (bypassing the ~10-min Pages TTL for the copy that serves offline); runtime policy for
  `/wasm/*` stays network-first. **The search pool only has its wasm after that download or a prior
  vs-S/N game** — the screens harness waits for the pool-ready console line before cutting the network
  for exactly this reason.
- **Coverage**: the `screens.mjs` offline scenario is the first browser coverage of the client-WASM AI
  path anywhere — hub → create → `context.setOffline(true)` → human move through the local engine →
  **AI reply from the pool while offline** → IndexedDB resume after reload.

---

## Frontend (`Spender.jsx` — also the site shell)

`webapp/main.jsx` mounts `Spender.jsx`, which is both the site shell (home menu, auth, routing to every
game/Books/Puzzles) and Spender's own game UI.

**Shell/game split — PARTIALLY DONE, and parked deliberately.** The auth screen and home menu live
in `shared/` (`AuthScreen.jsx`, `HomeScreen.jsx`), outside the Spender package, along with the site's
game catalogue. **They are in `shared/` for the DEPENDENCY DIRECTION, not for semantics** — `shared/`
otherwise means cross-game kits. They briefly sat in `webapp/shell/`, which is where they belong once
the shell is really lifted out (`main.jsx` -> `Shell.jsx` -> `games/*`), but until then that made
`games/spender` import from `webapp/` while `webapp/main.jsx` imports `games/spender` — a
directory-level cycle. One-way (`games -> shared`) beats a cycle waiting on a refactor. AuthScreen owns
its own six form-state hooks and reports back through a single `onAuthenticated(user)`; the shell keeps
identity. Note the asymmetry it preserves: a REGISTERED user is written to `localStorage`, a GUEST is
not (guests keep the anonymous id they already had, so a game started before signing in stays theirs) —
`npm run screens` asserts exactly that.
**Still to invert:** `screen`, `myId`, `authUser` and `toast` remain in `SpenderApp`, and ~38
routing-machinery references (`screenRef`/`applyPopRoute`/`enterRoute`/`deepRoom`) are still entangled
there. Finishing it means the shell takes those over AND Spender takes over its own room segment, the
way CoC/WW/Duel already do.

**Adding a 5th game does NOT require finishing it** — the `{ myId, authUser, onExit }` peer contract
already works four times. A new game is ~8 edits: 4 in `Spender.jsx` (lazy import, the two
SCREEN_FOR_MODE/MODE_FOR_SCREEN entries, a render branch), 2 in `shared/HomeScreen.jsx` (catalogue +
emblem), 1 in `webapp/test/screens.mjs` (a SCREENS entry), 1 mount block in `app.py`. Doing the split
LATER costs only those 4 lines moving with the rest, so a new game is a weak reason to do it now.

**The real forcing function is the shell needing to change INDEPENDENTLY of Spender** (its own
auth/nav/layout work, conditional mounting, two people working in parallel) — not another game.

**Before attempting it, extend `npm run screens`:** review/replay (~30 refs), the discard and noble
sub-decisions, and the client-WASM AI path (`ai_search`/`client_ai` — how the strongest AI serves) all
have ZERO browser coverage today, and the split rewrites routing right next to them. Note also that a
smaller, purely mechanical step (splitting `screen`) still shipped two regressions including broken
invite links.

### Screen flow & derived state
- `"auth"` → `"browser"` → `"waiting"` (2-player) | `"game"` (vs-AI goes straight to game).
- `inGame(status)` = `"playing"` OR `"over"` (a finished game stays on the game screen for the review UI).
- **Derived game state (`game`, `me`, `myTurn`, `aiThinking`, review flags) MUST be hoisted ABOVE all
  `useEffect` hooks** — they appear in dep arrays; a later declaration throws a TDZ ReferenceError in
  Firefox production builds. This is a recurring, load-bearing rule.
- **`WS_BASE = import.meta.env.VITE_WS_URL` is baked in at build time** (not from `window.location`) — so
  a separate frontend host (Cloudflare staging) points at the prod backend just by setting `VITE_WS_URL`.
- Reconnect tokens in `localStorage` as `spender_token_${roomId}_${myId}`; sent as `{action:"reconnect",
  token}`. Identity: logged-in `myId === user.id`; guest gets a random `spender_myId`.
- **Session validation on load**: `GET /auth/session?token=` runs before routing — a definitively-dead
  token (expired / superseded by a login elsewhere) clears the stale login; a network error NEVER logs you
  out.

### Lobby & multiplayer (2–4 players)
- Spender seats 2–4 humans (AI games stay 2-player); the engine is player-count-agnostic. `_bank_for(n)`
  scales the gem bank at start; nobles are `players+1`. DB has `player3/4_*` columns.
- 3-column lobby (**Open Games | Active Games | History**) — **all of it is the shared kit now**
  (`.lby-cols` / `.lby-list` / `.lby-card*` / `LobbySectionHd` / `TurnBadge` / `LobbyTabs`), converted
  2026-08-05. Spender's own `.game-card*` / `.section-hd` / `.empty-state` / `.your-turn-badge`
  vocabulary is GONE; `.lobby-grid` and `.browser-section` survive only as margin hooks, and
  `.lby-card-title.matchup` is the one real Spender-specific override left (Active Games puts one
  player per line, against the shared title's nowrap). The explicit `grid-row` pinning this lobby
  needed — its DOM order is Open, History, Active, so column-only placement wrapped Active to row 2 —
  now lives in `.lby-cols` and applies to every game. Open Games is filtered by the Classic/Long toggle; Active is not.
- Open lobbies live ONLY in Open Games (owner sees Return+Cancel, others Join); Active = `myGames` filtered
  to `status==="playing"`. A game lives in exactly one section.
- **Cancel authorizes by live session OR the host's `player_id`** (open games are public; a session-only
  check failed silently after token expiry). Clear the local resume pointer only AFTER the server confirms
  the delete.
- **Joining a cancelled game is rejected** (`not r.get("host") or r.get("game") is None`) — the WS
  `setdefault` fabricated a phantom hostless room otherwise. Tab-back reconnect is gated to
  `screenRef.current === "game"` (else it re-opened a stale waiting room).

### Layout (do not regress the footguns)
- Desktop is **proportional off one anchor** — `--card-h:clamp(104px,17vh,205px)` on `.game`, every
  desktop dimension a `calc()` ratio of it (replaced 5 stepped max-height breakpoints). Base styles are
  the phone/compact foundation; the desktop look is added in `@media(min-width:901px)`.
- **CSS-grid "staircase"**: a later DOM element placed in an earlier column makes sparse auto-flow drop it
  to a new row → diagonal staircase. Fix: pin every grid child to an explicit `grid-row`. (`grid-row:1/-1`
  needs an explicit `grid-template-rows` or `-1` collapses to line 1.)
- The `.game`/`.game-sidebar` grids need BOTH a definite height AND `grid-template-rows:minmax(0,1fr)`,
  and the move log carries a belt-and-suspenders `max-height`, or content pushes past the viewport / the
  log clips instead of scrolling.
- **`zoom` (not transform:scale)** for player-box indicators (scales box+text+inline dots WITH reflow);
  remember the zoom factor when a request says "+1px" (on-screen delta is `px × zoom`).
- **Container-query `cqw` resolves against an ANCESTOR container, not the element itself** — reserved-card
  padding stays `--card-h`-based; only descendants use `cqw`.
- **Nobles never shift on claim**: the row renders the full id-sorted set; a claimed noble shows as a blank
  slot in its fixed position (frontend reconstruction — the backend removes it from `game["nobles"]`).
- **Action animations** (`.fly-layer`): one `useEffect([game])` diffs tokens/purchased/board-slot ids and
  spawns flyers — covers every player incl. the AI. Keep the `data-color`/`data-pid`/`data-pos` anchors.
- **Ping**: tapping another player's box plays a chime locally + sends `{action:"ping", target}`; the
  backend relays `{type:"ping", from}` to **ONLY the target's socket** (never broadcast — verified it
  reaches only the tapped player + clicker). Tab-hidden + your-turn/ping flashes the title + swaps favicon.

### No-layout-shift architecture (do not regress)
Self-hosted Cinzel/Crimson fonts (`webapp/public/fonts/`, `@font-face` in baseCss, preloaded in
`index.html`); the loading effect `await document.fonts.load(...)` (capped 1.5s) BEFORE routing so first
paint uses web fonts; `font-display:optional` + metric-matched `local('Georgia')` fallbacks (measured
`size-adjust`) so an unloaded font never swaps. Inline dark `background` in `index.html` (the `--bg` token
only exists in baseCss). The **CLS smoke gate** catches new shifts.

**EVERY face needs BOTH a preload and a line in the `waitFonts()` gate — including italics.**
`font-display:optional` gives a face ~100ms from first paint; miss it and that face is dropped for
the WHOLE page load (it does not swap in when it lands), so the text renders in the metric-matched
Georgia fallback — identical widths, visibly HEAVIER strokes — until a reload warms the cache. The
italic Crimson Pro face was neither preloaded nor in the gate for months: measured on prod it began
loading AT first paint and finished 6–264ms after it on every profile (warm, cold, throttled), so
every hint, empty state and log line on the site rendered in Georgia italic on a first visit. **No
runtime check could see it** — CLS stays 0 by design (that's what `size-adjust` is for) and the page
throws nothing; it only shows up in the resource-timing-vs-FCP comparison. `smoke.mjs`'s
**font-preload guard** now derives the face list from `theme.base-css.css` and fails if any
`.woff2` lacks a preload.
