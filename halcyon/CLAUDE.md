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
| `content.py` | base items, enchantments, slot sizes, enemy XP and the level table — **greybox placeholders**, except the id rules at its top |
| `dungeon.py` | the Shallows: room templates stitched left-to-right, enemies, heal orbs and every drop PRE-ROLLED (design §18.2) |
| `api.py` | `setup_halcyon` — guest mint, state, characters (with starter gear), runs, run events, move/discard/fuse. Plain `def` routes |
| `sim.js` | the fight: PURE, deterministic, fixed 60 Hz (design §18.5). No DOM, no clock, no Math.random/sin/cos/atan2 |
| `render.js` | Canvas 2D drawing of the sim's state (and the town's) in the art doc's color roles; never changes it |
| `town.js` | the walkable town: a plaza, its stations (vault, forge, one portal per realm in `REALMS`), `stepTown` |
| `client.js` | who is asking (Bearer or the guest pair) and the run's event QUEUE |
| `HalcyonRift.jsx` / `.css` | one screen: the stage (town or dungeon, with the vault / forge / discard panels over it) and the side panel (roster, equipment, inventory) |

Tests: `tests/` (store, dungeon, routes, the sim fixtures' freshness),
`webapp/test/unit/halcyonSim.test.mjs` + `halcyonTown.test.mjs` + `halcyonClient.test.mjs`
(node), and `halcyonPlay` in `webapp/test/screens.mjs` (guest → Ranger → walk to the
vault → drag the bow in and back → the no-scroll sizes → walk to the portal → Shallows →
drag the vest off mid-run → recall → reload, the vest still off).

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

## The screen (owner's asks, 2026-11-18)

- **It never scrolls, at any window size.** The root is the window's height with
  overflow hidden; `--slot` (an inventory square) and `--vslot` (a vault square) are
  derived from the window in `HalcyonRift.css`, and that formula's constant pays for
  the side panel's fixed rows — **a new row in the side panel must be paid for there**.
  `halcyonPlay` measures page scroll, side-panel overflow and the open vault at
  1440x900, 1024x600, 1920x1080 and 390x844.
- **The town is a place, not a menu.** WASD walks it, E uses what you stand at (the
  stage's `data-near` names it, which is what the harness walks by). The whole plaza is
  always in view (the town's tile size fits the map to the stage). Walking away from the
  vault or the forge closes it. Coming out of a run puts you just in front of the portal
  you took — out of its reach, so E does not send you straight back in.
- **The inventory is always on screen**, in town and in a run. During a run it shows
  what you picked up (gold-ringed, "picked up this run") before the server has minted
  it.
- **Gear changes mid-run (owner's ask, 2026-11-18).** In a run the equipment and bag
  are the page's own model (`runControl` in `HalcyonRift.jsx`), owned outside React
  so the fight's loop can ask it synchronously which slot a pickup goes to. A move
  there is a run EVENT (`{type:"move", item|drop, to:[kind, slot]}`), queued behind
  the fight's reports, so it always lands after the pickup that minted the item; a
  picked-up item is named by its DROP (`store._apply_one` resolves it within THIS run
  only, tested). The fight takes the new equipment as an input on its next tick
  (`input.gear` → `sim.setGear`), so a replay swaps on the same tick; a swap never
  heals (HP, the recovery limit and MP only come down to a smaller maximum — else a
  +HP ring off-and-on would be a heal). The vault, the forge and the bin stay in town.
  The run's model is shown until the town's refresh lands, and a slot button blurs
  after use so Space and Enter stay the fight's.
- **Items move by native HTML drag and drop**, click one then click where it goes, a
  DOUBLE CLICK (bag → the slot it fits, swapping; equipment or vault → the first empty
  bag slot) or the NUMBER KEYS 1-8 (the first eight bag slots carry the number; the key
  puts that item on). All four work in town and in a run. The equipment slots an item
  cannot go in dim while it is dragged; the server still decides every move. The bin
  asks before it discards.
- **The forge is a pick, not a drop target** (owner's ask: dragging into it "felt
  janky"). At the forge a click PICKS an item in the bag or equipment — it stays where
  it is, ringed in the accent — two at most, then Fuse. It says why two will not fuse
  (item, tier or slot count). Leaving the forge drops the picks.
- **Two STANDARD weapon types per class, plus uniques** (owner's calls, 2026-11-18). The
  Ranger's are the shortbow (twin fanned arrows, fast, range 5) and the longbow (one
  heavy slow arrow that pierces two, range 7 — the longest). The repeater (a three-bolt
  burst, range 6) is a rare UNIQUE drop. **A base's kind belongs to the base**:
  `store.init_schema` brings existing items into line with `content.py` (kind, and
  tier 1 for a unique), so an item minted before a base changed kind follows it (tested).
- **A unique is named, not tiered.** It always drops at tier 1, its slot is a gold face
  with a ★ where the tier number goes, its name has no "· T1", and its tooltip is lit
  gold. "Picked up this run" is a dashed ring, so it never reads as a unique. The first
  unique weapon is the Tidecaller: three arrows in a wide fan that glance off a wall
  once (`bounce`, `sim.wallHit`).
- **Every number a player reads is flat** (owner's ask: "stop with all the
  percentages"). Attack and Dexterity are POINTS; each is worth 1/`STAT_SCALE` (25) more
  damage or shots a second. Damage per arrow, the points and every enchantment are whole
  numbers — an enchantment's value is `sim.enchantValue(id, q)` off `ENCHANT_FLAT`, so the
  store still keeps only quality. The side panel's stats row (HP, MP, ATT, DEX, DEF, DMG,
  RATE, RNG) is `statsFor` of what is on, so it is what the fight will use. Points apply
  after the loop over gear, so gear order cannot change a number (tested).
- **HP and MP bars sit in the side panel**, under the character and above the stats,
  in town and in a run. HP is three parts: red what you have, light gray what
  regeneration can bring back (up to the recovery limit), dark gray what only a heal
  can. The bars repaint from the live sim each frame and touch the DOM only when a
  number changes (`Vitals`), so the fight never re-renders the page. The dungeon's
  canvas HUD draws HP the same way.
- **The town can be shot in** with the fight's own code (`sim.playerFire`, `wallHit`):
  the equipped weapon, the volley ability, two practice posts that float each hit's
  damage above them and show what the last three seconds came to a second below them.

## Levels and XP (2026-11-18, owner's calls on design §10.1 / §13.1)

- **XP comes from kills, plus a bonus for completing a dungeon**, and **recall keeps
  it** — so does a closed tab. Death takes the character, level and all.
- **The server credits it from its own dungeon.** `dungeon.generate` writes each
  enemy's `xp` (`content.ENEMY_XP`) and the dungeon's `complete_xp` into the dungeon
  it stores; `store._apply_one` adds them on an accepted `kill` / `complete`. XP is
  written as each kill lands, which is why a recall keeps it with no extra rule. An
  `xp` field on an event is ignored (tested).
- **One level table, shipped as data.** `content.LEVEL_XP[n]` is the XP to BE level
  n + 1 (20 levels, each step ~30% bigger, a Shallows clear ~140 XP against 120 for
  level 2). `/halcyon/state` sends it as `levels`; the sim and the page read that,
  never a copy. The sim's unit tests DO carry a copy, held to the real one by
  `tests/test_sim_fixtures.py`.
- **A level gives a little to the base numbers** (`sim.PER_LEVEL`: +6 HP, +4 MP,
  +3% damage, +0.3 defense per level), separate from the per-dungeon stat rewards
  and their caps (§10.2, not built). It applies MID-RUN: the sim levels on the XP
  it sees, raises HP, the recovery limit and MP by what the level added, and emits a
  `level` event marked `local` (the page shows it; the server works the level out
  itself). If the two ever disagree — a refused kill — the server's number is the
  one the town shows.

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

Per-dungeon stat progress (§10.2 — no dungeon but the Shallows exists yet), dropping an
item on the dungeon floor (the store takes `drop_item`/`pickup_item`; the page sends
neither), touch controls
(the dungeon is keyboard + mouse), the minimum-time plausibility checks (design §18.3),
the input-log upload (§18.6), and hiding the drop table (above).
