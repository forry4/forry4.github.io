# Halcyon Rift — Claude Context

A browser top-down projectile action RPG with character permadeath and an account
vault. **The design is in `docs/`** — read [`halcyon-rift-game-design.md`](../docs/halcyon-rift-game-design.md)
first (§18 networking, §20 persistence, §20a its place on the site), then the two art
docs. This file is the code's half.

## Where it stands (2026-11-18)

A playable **greybox**: colored shapes on the real architecture. Admin-only on the
menu; `/halcyon` works for anyone who has the link (guests included).

| File | What it is |
|---|---|
| `store.py` | characters, items, vault, runs: the schema and every operation (design §20.2) |
| `content.py` | base items, enchantments, slot sizes — **greybox placeholders**, except the id rules at its top |
| `dungeon.py` | the Shallows: room templates stitched left-to-right, enemies, heal orbs and every drop PRE-ROLLED (design §18.2) |
| `api.py` | `setup_halcyon` — guest mint, state, characters (with starter gear), runs, run events, move/discard/fuse. Plain `def` routes |
| `sim.js` | the fight: PURE, deterministic, fixed 60 Hz (design §18.5). No DOM, no clock, no Math.random/sin/cos/atan2 |
| `render.js` | Canvas 2D drawing of the sim's state in the art doc's color roles; never changes it |
| `client.js` | who is asking (Bearer or the guest pair) and the run's event QUEUE |
| `HalcyonRift.jsx` / `.css` | the town (roster, equipment, inventory, vault, fuse, discard) and the dungeon stage |

Tests: `tests/` (store, dungeon, routes, the sim fixtures' freshness),
`webapp/test/unit/halcyonSim.test.mjs` + `halcyonClient.test.mjs` (node), and
`halcyonPlay` in `webapp/test/screens.mjs` (guest → Ranger → Shallows → recall → reload).

## The browser half's rules (do not regress)

- **The sim is deterministic or it is nothing.** Same dungeon + gear + inputs = the
  same run, tick for tick (a unit test compares fingerprints every tick). Randomness is
  the seeded mulberry32 inside the state; timers are integer ticks; angles go through
  `dsin`/`dcos` (exact IEEE arithmetic). `Math.sqrt`, `round`, `floor`, `imul` are fine.
  `x ** 2` is not used — write `x * x`.
- **The client names what it DID.** A pickup event carries a drop id and the inventory
  slot it went to; the server mints what IT rolled for that drop. The sim tags events
  the server has no use for `local` (a heal — the server keeps no HP), and the page
  never sends them (the store would record them as refused).
- **The queue is written before it is sent, and only `client.js` writes it.** A
  report is numbered and saved to localStorage, then flushed every 3s and at once on
  recall/death/clear and on `pagehide`. `pendingRun()` means "has undelivered
  reports", NOT "has a queue": a run that reported nothing must not block the next one
  (it did — the first live test found it). A 409/401 on flush drops the queue (the
  server cannot know that run); a network failure keeps it.
- **Leaving is a key press.** The portal opens 3 tiles from where the boss fell and
  needs E. It used to open ON the boss and complete on contact — the boss's loot bag is
  in the same spot, so walking to the loot ended the run with loot left on the floor
  (found by the first full clear through the page).
- **Draw only the tiles on screen, every frame — never bake the whole dungeon.** The
  first greybox pre-rendered the map to one canvas at device pixels (~20,500×2,800 on a
  150% display), past the GPU's texture limit, and copied it every frame: reported as
  "super laggy", measured 33ms p50 / 50ms p99 at 1440p. `drawMap` walks the visible tile
  range instead (16.7/16.8 at 2560×1600@2 with a GPU). Moving things are drawn
  INTERPOLATED between the last two ticks (`at(obj)`, `alpha = acc/STEP_MS`), so a
  120/144 Hz screen does not show 60 Hz steps; the sim never sees the interpolation, and
  aim goes through the camera the player last SAW. A headless benchmark rasterizes on
  the CPU unless launched with `--enable-gpu --use-angle=d3d11 --ignore-gpu-blocklist`.
- **A hidden tab gets no frames, so the fight pauses.** That is intended (a solo game);
  closing the tab is a recall. DEV builds expose `window.__halcyon` = `{ st, drive,
  advance(n) }` so a script can play a whole run through the real page without frames;
  `import.meta.env.DEV` strips it from production.
- **Guest headers must be in the root CORS `allow_headers`** (`app.py`). Missing, every
  guest request is "Failed to fetch" at the preflight — `test_api.py` holds it.
- **The dungeon payload carries the drop table** (what each enemy will drop). Fine for a
  greybox; a player can read it in devtools and skip enemies with bad drops. Closing it
  means revealing a drop only in the reply to its kill event.

## A catalog game built like an Extra (design §20a)

`shared/catalog.js` has it (`adminOnly`), with an accent (rift lavender, `#9d8ff2`) and
an emblem. Its code lives HERE, not in `games/`, so the `games/*`-globbed table-game
gates do not apply. The two catalog-keyed gates carry written, self-policing
exemptions: `NOT_TABLE_GAMES` in `shared/tests/test_profile_results.py` and
`NOT_A_LOBBY` in `webapp/test/screens.mjs`. It is wired like Box Puzzles: `app.py`,
`pytest.ini`, `deploy-pages.yml` (`halcyon/**`), `deploy-render.yml` (`halcyon/*.py`),
`.githooks/pre-push`, `affected.mjs`, a lazy route in `Spender.jsx` inside a
`ScreenBoundary`, `SCREENS`, and the kit/backend-wake/off-loop gates' directory lists.
**A feature missing from `deploy-render.yml` never deploys, and nothing goes red.**

## The store's rules (do not regress)

- **One transaction per operation, rolled back by closing without commit.** `_tx`
  commits on success and on any exception closes the connection uncommitted — that
  rolls back on sqlite and on Turso (`_HranaConn.close`). `core/db.py`'s wrapper has no
  `rollback()` and no `rowcount`; nothing here needs either. The two injected-failure
  tests fail if `_tx` ever commits on the way out of an exception.
- **The duplication guard is a UNIQUE index** (`origin_run_id, origin_drop_id`), not
  just the "already picked" check — a test writes a second mint directly and expects
  `IntegrityError`.
- **A client names what it DID, never what it GOT.** Pickup events carry a drop id;
  the item comes from the run's stored dungeon. Extra fields on an event are ignored
  (tested).
- **Run events are numbered per run and idempotent.** At-or-below `last_seq` is
  skipped, a gap stops the batch, and a refused event is RECORDED and the sequence moves
  past it (a client re-sending a refused event forever would deliver nothing after it).
  A closed run accepts nothing — a late death report for a run already closed as a
  recall is ignored.
- **Validate fully, then write.** `_apply_one` and `_move_with_swap` check both
  directions of a swap before the first UPDATE, so a refusal never leaves half an event.
  Swaps go through `loc='limbo'` because the slot indexes are checked per statement.
- **Concurrency is the per-owner lock** (one uvicorn process; a fixed stripe pool, so
  guest ids never grow a dict) plus optional `expected_version` on town operations.
- **Items store enchantment roll QUALITY (0–1), not numbers**, so rebalancing is a
  `content.py` edit. Base and enchantment ids are never reused or deleted — only retired.
- **Destroyed items are tombstones** with a reason (`death`/`fusion`/`discard`/
  `run_end`); a pruned GUEST is deleted outright.

## Not built yet (deliberately)

XP and stat progress (numbers come from the greybox), changing gear mid-run (the store
takes `move`/`drop_item`/`pickup_item` events; the page sends none yet), touch controls
(the dungeon is keyboard + mouse), the minimum-time plausibility checks (design §18.3),
the input-log upload (§18.6), and hiding the drop table (above).
