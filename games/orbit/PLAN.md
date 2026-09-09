# Orbit — an eighth game

## Goal

Add **Orbit**, a faithful 1v1 implementation of *Zenith* (2025), as the next game on
Forrest Games. The first release supports:

- two human players in a private/open room;
- one human against a server-side opponent that chooses legal moves at random;
- the complete 1v1 rules, all 90 Agent cards, the technology board, planet tracks,
  bonus tokens, leader badge, mulligan, and all three victory conditions;
- saved games, reconnects, history, rules, responsive play, and the same auth/security
  guarantees as the other seven games.

The 2v2 team game, offline play, and a strong AI are explicitly out of scope. The random
opponent is a playable vertical slice and a rules soak; a superhuman search tier comes
later, after the engine reproduces real games.

This plan was created on branch `Orbit`, based on synced `main` commit `50110820`.

### Implementation status — 2026-09-04

Stages 0–3 are implemented on `Orbit`: the reviewed 90-card corpus, both faces
of all three technology strips, the complete bonus inventory, pure rules
engine, random opponent, room/persistence/security layer, responsive browser
game, shared shell integration, and rules UI are all present. The release gates
now include a real browser action at desktop and phone widths, plus a reusable
2,000-game seeded soak.

Stage 5 remains intentionally open until the user supplies additional BGA
replays. Production-restart persistence and the Pages deployment fallback are
post-merge deployment checks; local save/load, reconnect, direct-route, and
production-build behavior are covered now.

---

## Source of truth and what is already known

Primary sources:

- [official English rulebook](https://drive.google.com/file/d/13k7wpT_lOpascDWiC6jwOdcAv2Ddy9wm/view)
- [90-card Agent sheet](https://docs.google.com/spreadsheets/d/1k7N7xzTTVZkcQaV84Adz8ikM7aYK7U0WwIoZAi_DM_I/edit?gid=1477254853#gid=1477254853)
- the supplied BGA starting-position screenshot
- later: user-supplied BGA replays, used as an implementation oracle rather than as the
  initial rules source

The card sheet currently exports as exactly **90 uniquely named Agents**: 18 each for
Mercury, Venus, Earth/Terra, Mars, and Jupiter, with printed costs from 1–10. It contains
planet, cost, name, and effect text. More than half of the cards contain a choice,
condition, variable amount, or selectable target, so the engine needs a real persisted
decision system; a pile of one-off message handlers will not be reliable enough.

The following 1v1 contract is settled by the rules:

- Each player starts with 12 Credits, 1 Zenithium, and 4 cards. The second player gains
  one Terra influence before play.
- Before the first turn, each player may discard 0–4 cards and draw back to four. Hands
  remain secret.
- A turn plays exactly one card as one of three actions: recruit it on its planet,
  discard it to develop its faction technology, or discard it to take the matching
  faction's Leader action.
- Recruited Agents cost their printed amount minus the number of cards already in that
  player's matching planet column, to a minimum of zero. Their effects resolve from left
  to right after the card enters the column, so the new card can itself be targeted.
- Every recruited Agent grants one influence on its own planet in addition to its printed
  effects.
- Mobilize adds the top deck card to its matching column without resolving its effects.
  Exile removes the topmost card of a column. Transfer moves the opponent's topmost card
  to the corresponding friendly column without resolving it.
- The three technology tracks cost 1/2/3/4/5 Zenithium to reach levels 1–5. Advancing a
  track resolves the new level and every lower level, top to bottom. First arrival at the
  level-two token and completing all three technologies at levels 1, 2, or 3 award their
  specified bonuses in the published order.
- Robot Leader: take/upgrade the badge and gain 1 Zenithium. Human Leader: take/upgrade
  the badge and gain 3 Credits. Animod Leader: take/upgrade the badge and Mobilize 2.
  Silver raises hand size to 5; gold raises it to 6.
- Each planet's influence disc begins in the middle. Moving it into a player's control
  zone captures it. The first capture on that planet also awards its face-up bonus token;
  that board token is never replaced. A captured disc returns to the middle at the end of
  the active player's turn, and excess influence after the capture is lost.
- The game ends immediately when a player owns 3 discs from one planet, 4 discs from four
  different planets, or any 5 discs.
- At turn end, draw to the current badge hand limit, without discarding if already over
  it; reset captured planet discs; then pass the turn. Empty Agent and face-down bonus
  piles are rebuilt from their respective discards.
- Effects that cannot be applied are ignored. An effect can grant influence to the
  opponent, including a capture and its bonus; the engine must therefore check victory
  and bonus ownership after every influence step, not only after the active player's
  effects.

### Source-lock gate before rules completion

The supplied material is enough to scaffold the package and implement the base turn, but
four static-data gaps must be closed before calling the engine faithful:

1. **Agent factions are absent from the sheet.** Names make many factions look inferable,
   but inference is not a source. Capture the Human/Robot/Animod icon for every card from
   an authoritative card face or an augmented sheet.
2. **Technology boards need a mechanical transcription.** Record every legal 1v1 board
   configuration, level effect, ordering rule, and row-completion bonus. The supplied
   screenshot establishes the S.U.N. starting layout, not the full configuration corpus.
3. **Bonus tokens need an inventory.** Record every face, effect, and multiplicity for the
   planet/technology setup pile and the face-down draw pile.
4. **Ambiguous sheet wording needs card-face review.** Examples include effects with an
   omitted target or amount (`C1X1N`, `HUXL3Y`, `Gilgamesch`), broad wording such as
   `Magellan`'s “each column,” and repeat/partial-choice wording such as `Lady Moore`.
   Preserve a short source note for every resolved ambiguity.

Normalize the internal planet id to `terra`; accept the sheet's `Earth` only at import.
Do not commit publisher art, logos, or scans. Commit mechanical data and draw an original
Orbit interface with CSS/SVG primitives, as Rag Tag already does.

---

## Package and integration shape

Create a self-contained feature package mounted at `/orbit`, with table `orbit_games`,
mode id `orbit`, and CSS namespace `.orbit`.

| File | Responsibility |
|---|---|
| `games/orbit/engine.py` | Pure setup, legality, action application, effects, victory, and redaction |
| `games/orbit/effects.py` | Closed declarative effect/condition/target vocabulary and validation |
| `games/orbit/cards.py` | Generated and committed Agent definitions |
| `games/orbit/boards.py` | Generated and committed technology/bonus-token definitions |
| `games/orbit/bot.py` | Reproducible random legal opponent |
| `games/orbit/persist.py` | At-rest-only compaction/expansion |
| `games/orbit/main.py` | FastAPI sub-app, rooms, REST, WebSocket, persistence, bot scheduling |
| `games/orbit/rules.jsx` | Orbit-specific copy for the shared `RulesModal` |
| `games/orbit/Orbit.jsx` | Lobby, waiting room, game, result, review, and decisions |
| `games/orbit/Orbit.css` | Responsive game surface; shared lobby rules remain shared |
| `games/orbit/data/*.json` | Reviewed mechanical source data with provenance notes |
| `games/orbit/tools/extract_bga.py` | Extracts the public mechanical reference without publisher artwork |
| `games/orbit/tools/audit_reference.py` | Audits card/faction/board/token counts and compact BGA op coverage |
| `games/orbit/tools/soak.py` | Runs reproducible random full-game legality/invariant soaks |
| `games/orbit/tools/bga_*.py` | Later replay normalization and parity runners |
| `games/orbit/tests/` | Engine, data, bot, persistence, redaction, server, WebSocket, and parity tests |
| `games/orbit/AGENTS.md` | Per-game invariants and settled rulings once implementation starts |

Wire the package through every roster that intentionally fails when a new game is only
half-added:

- defensively mount `orbit_app` in `app.py`;
- append Orbit to `shared/catalog.js`, `shared/accents.js`, `shared/emblems.jsx`, and
  `shared/router.js`;
- lazy-load and mount `Orbit.jsx` in the site shell;
- add `games/orbit/tests` to the single `pytest.ini` suite;
- add `/orbit` to route, shell, rules-modal, accent, lobby, phone-layout, and play-flow
  coverage in `webapp/test/screens.mjs`;
- include Orbit in the non-gating lobby screenshot/probe harnesses.

Do not add Orbit to the offline hub in v1. The original single-opponent launch had no
difficulty picker; the current lobby exposes Easy, Normal and Hard tiers.

---

## Pure engine design

The engine owns every rule. The server validates browser and bot actions through the same
`apply_move` entry point; the React client only renders a recipient-specific view and
sends choices.

Public API:

```python
new_game(seats, seed=None, board_config="sun") -> dict
legal_moves(game, seat) -> list[dict]
apply_move(game, pid, move) -> None
player_view(game, viewer_pid) -> dict
seat_of(game, pid) -> int
is_over(game) -> bool
```

### State model

Keep the live dict verbose and JSON-safe. Card copies need stable instance ids because a
specific top card moves among a hand, column, deck, and discard.

```python
{
  "version": 1,
  "phase": "mulligan" | "play" | "over",
  "seats": [pid0, pid1],
  "first_seat": 0,
  "turn": 0,
  "players": [
    {
      "credits": 12,
      "zenithium": 1,
      "hand": [instance_id, ...],
      "columns": {planet: [instance_id, ...]},
      "technology": {"human": 0, "robot": 0, "animod": 0},
      "leader": 0,
      "captured": [planet, ...]
    },
    ...
  ],
  "instances": [{"card": card_id}, ...],
  "agent_deck": [instance_id, ...],
  "agent_discard": [instance_id, ...],
  "influence": {planet: -3..3 | None},
  "captured_this_turn": [planet, ...],
  "planet_bonus": {planet: token_id | None},
  "technology_bonus": {faction: token_id | None},
  "bonus_deck": [token_id, ...],
  "bonus_discard": [token_id, ...],
  "board_config": "sun",
  "pending_pid": None | pid,
  "pending_kind": None | str,
  "pending": None | {"stack": [...], "choice": {...}},
  "log": [...],
  "rng_state": [...],
  "winner": None | pid
}
```

The exact influence encoding may use `-4..4`; the invariant is more important than the
number: middle, three approach spaces per side, and the two terminal control zones must
be representable without treating a captured disc as still on the track.

Mulligans are simultaneous and private. Store each submission in state and begin play
only when both seats have submitted; never reveal which specific cards the opponent
returned.

### Effect interpreter

Compile source data into a closed operation vocabulary rather than matching prose at
runtime. The minimum families are:

- resources: gain, spend, give to opponent, and steal Credits/Zenithium;
- influence: gain/give on a fixed or chosen planet, return a disc to the middle, resolve
  capture/bonus/victory immediately;
- cards: draw, discard from hand, Mobilize, Exile, Transfer, inspect topmost columns;
- leader: acquire, upgrade directly to gold, give up, and predicates for badge state;
- technology: develop fixed/chosen/lowest track, reductions/free advances, cascade level
  effects, first-to-level-two token, and completed-row bonus;
- composition: ordered sequence, optional payment, either/or, choose target, repeat,
  threshold table, per matching object, `if`, and bounded partial selection;
- predicates/counts: leader ownership, resources, technology levels, column size/cost,
  planets represented, dominated/middle/opponent-side tracks, and neighboring planets.

Every op has a schema and validator. Truly exceptional effects use a named `fx` registry;
tests assert that data-side names and registered handlers agree in both directions, with
an empty `UNIMPLEMENTED_FX` before release.

Effects resolve left to right through a persisted continuation stack. If the next op
requires a human choice, write `pending_pid`, `pending_kind`, the legal options, and the
remaining continuation into the game dict. A reconnect must resume exactly that choice.
“Cannot apply” must be encoded per operation: skip, choose fewer, or require an exact
payment are distinct rules and may not be guessed by the frontend.

### Turn transaction

1. Validate that the acting player owns the turn and has no unresolved decision.
2. Play one hand card as `recruit`, `develop`, or `leader`.
3. Apply the action cost and enqueue its effects.
4. Resolve until complete, pausing only on persisted choices.
5. After every influence step, handle captures, bonus ownership, and immediate victory.
6. When the action and all continuations finish, draw to the badge hand limit, reset every
   disc captured during the turn, and advance the turn.

Use one seeded RNG stored in state for deals, Agent reshuffles, and bonus-token reshuffles.
No undo stack is planned. Keep the move/event log bounded; BGA parity tooling should use a
separate replay fixture, not an ever-growing live-state history.

---

## Server, security, and persistence

Start from the current shared room-server pattern, with Rag Tag as the useful random-bot
reference and the alternating-turn games as the lifecycle reference.

- `ROOMS` remains under one `asyncio.Lock`; database writes use the existing background
  write-executor shape.
- A socket is never registered before create/join/reconnect proves seat ownership. Every
  mutating message is gated on that authenticated seat.
- `mk_room_state` calls `engine.player_view` for each recipient. Opponent hand contents,
  Agent deck order, face-down bonus order, mulligan selection, private pending options,
  and room reconnect credentials must never appear in the wrong serialized payload.
- Public state includes resources, badge level, technology, influence tracks, captured
  discs, public columns, discard information allowed by the rules, hand counts, and the
  public action log.
- Use `shared/useAutoReconnect.js`: reconnect forever with backoff and retry on visibility
  changes. Reconnect also re-drives the bot scheduler.
- Persist pending continuations and RNG state. `persist.py` may pack all RNG copies and
  compact repeated card instances, but only at `_encode_state`/`_decode_state`; never
  mutate the live or wire format for storage savings.
- Implement open/active/history lists with `core.rooms.HISTORY_LIMIT`, retention cleanup,
  SELECT-then-DELETE cancellation, stale-socket protection, and the same dual SQLite/Turso
  wrapper as every other game.

### Random opponent

`bot.py` chooses only from `engine.legal_moves`. Seed it from the server's stable position
key so every failing soak can be reproduced. Choose a top-level action first and then its
required targets, rather than sampling a fully expanded Cartesian product that would
accidentally favor cards with more target combinations.

Run selection outside `ROOM_LOCK`, then re-lock, compare a position key that includes the
pending continuation, and revalidate the move before applying it. Add a short response
floor so an instant reply is legible to the player. The bot handles mulligan and every
pending choice; it never bypasses the engine.

---

## Frontend

Use the shared lobby, create modal, rules modal, header, history paging, and reconnect
hook. The create modal offers **Friend** or **Computer**, with Easy, Normal and Hard
computer tiers. Easy is random, Normal is the original public ranker, and Hard is the
effect-aware browser policy with a validated server fallback.

The supplied starting-position screenshot is the layout reference, not an art source:

- technology board on one side;
- five colored planet tracks as the central shared board;
- 1v1 diplomacy/Leader actions on the other side;
- opposing player panels around the board, with the local hand and action controls in the
  local rail.

Build an original Orbit visual system with CSS/SVG shapes and the site palette. Agent
faces render from mechanical data: name, planet, faction, cost, and structured effect
icons/text. Do not ship Zenith/BGA logos, illustrations, scans, or screenshot crops.

The interface must make the three uses of a selected card explicit and show the resulting
cost before confirmation. All engine choices use one decision tray with disabled/impossible
targets removed. Multi-step effects animate from the public event log, but the next input
is never blocked on animation completion at the server.

Responsive gates should cover at least 390×844, 834×1112, 1280×800, 1440×900, and a wide
desktop. On a phone, prioritize the five planet tracks and the active decision; technology,
diplomacy, and player tableaux may collapse into reachable panels, but no legal target may
become off-screen or hover-only. The board must not scroll sideways accidentally.

---

## Delivery sequence

### Stage 0 — lock the mechanical corpus

- [ ] Normalize the 90 sheet rows into reviewed JSON with stable ids.
- [ ] Add faction to every Agent from an authoritative source.
- [ ] Transcribe and independently review all technology configurations and bonus tokens.
- [ ] Resolve every ambiguous effect against a card face/ruling and record provenance.
- [ ] Implement `import_data.py --check`; generated modules must be byte-for-byte current.
- [ ] Add structural tests: 90 unique Agents, 18 per planet, valid faction/cost/op/target,
      complete board/token inventories, and no unimplemented effect names.

Scaffolding can begin in parallel with this audit, but Stage 1 cannot be declared faithful
until this gate is green.

### Stage 1 — pure rules engine

- [ ] Setup, seeded deal, second-player Terra influence, and simultaneous mulligans.
- [ ] Recruit/develop/leader actions, costs, hand limits, and turn completion.
- [ ] Influence movement, capture/reset, bonus tokens, and all victory conditions.
- [ ] Technology cascades and row bonuses in exact order.
- [ ] Closed effect interpreter plus persisted decisions; implement all 90 Agents.
- [ ] Deterministic random-play soak from setup to victory with conservation/invariant
      assertions after every move.

### Stage 2 — rooms, persistence, and random AI

- [ ] `orbit_app`, SQLite/Turso table, room lists, history, cancel, review, and retention.
- [ ] Friend create/join/start/reconnect/abandon flow with bound seat identity.
- [ ] Per-recipient redaction tested against a real in-progress serialized room.
- [ ] Save/load round trips during mulligan, a nested pending effect, a deck reshuffle, and
      a captured-disc turn.
- [ ] Random bot legality, reproducibility, stale-result rejection, reconnect restart, and
      complete-game soaks.

### Stage 3 — browser game

- [ ] Shared Orbit lobby, rules, waiting room, invite/deep-link, active/history rows.
- [ ] Responsive board and player tableaux with full public state.
- [ ] Private hand, three action modes, price preview, target/choice tray, event narration,
      and result/review screens.
- [ ] Shell catalogue/accent/emblem/router/lazy-chunk integration.
- [ ] Browser coverage for route mount, rules, friend room, random-AI game, reconnect, one
      representative multi-step card, victory, lobby columns, phone reachability, and no
      leaked private DOM text.

### Stage 4 — fidelity and ship gate

- [ ] Rules-example fixtures and one focused test per effect family and unusual card.
- [ ] Full `pytest`, `npm run smoke`, and `npm run screens` green.
- [ ] Seeded full games produce no illegal state, stalled pending choice, or resource/card
      loss across thousands of playouts.
- [ ] Cold-load `/orbit` and `/orbit/<ROOM>` through the production Pages fallback.
- [ ] Verify persistence through a backend restart/redeploy before announcing release.

### Stage 5 — BGA parity, when replays arrive

Keep raw replay captures outside the repository. Add a normalizer that emits compact,
reviewable fixtures containing initial seating/setup, deck/draw facts needed to reproduce
the game, each submitted action/choice, and public checkpoints.

Run increasingly diagnostic gates:

1. action stream parses and every recorded action is legal;
2. turn/hand/resource/technology/leader/column checkpoints agree;
3. influence positions, captures, bonus awards, and winner agree after every effect;
4. full game reaches the same winner on the same turn.

Report already-reproducing games separately from failures and stop comparison at the first
divergence. A winner-only match is a weak signal; the first per-effect mismatch is the
useful one. Once a replay settles a rules ambiguity, add the smallest permanent engine
test and document the ruling in `games/orbit/AGENTS.md`.

### Later — superhuman opponent

Only after replay parity is clean, define a compact observation/action contract and build
an offline equal-time benchmark. Preserve determinization of hidden hands/deck order,
leave browser worker cores free, validate every served move through the Python engine,
and degrade per decision to a legal server move. The random bot remains the fallback and
baseline rather than being deleted.

---

## Definition of done for the first release

Orbit is ready when two humans can finish a rules-correct game, a human can finish one
against the random bot, a reload or socket drop cannot lose or expose state, every static
component and Agent is source-verified, seeded soaks always terminate legally, and the
entire repository gate remains green. BGA replay parity is designed in from day one but is
not a blocker until the replay corpus is available; any later mismatch becomes a release
regression test before it becomes a patch.
