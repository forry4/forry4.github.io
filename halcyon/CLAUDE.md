# Halcyon Rift — Claude Context

A browser top-down projectile action RPG with character permadeath and an account
vault. **The design is in `docs/`** — read [`halcyon-rift-game-design.md`](../docs/halcyon-rift-game-design.md)
first (§18 networking, §20 persistence, §20a its place on the site), then the two art
docs. This file is the code's half.

## Where it stands (2026-11-18)

A playable **greybox**: colored shapes on the real architecture. Public on the menu
since 2026-11-18; guests play without an account.

| File | What it is |
|---|---|
| `store.py` | characters, items, vault, runs: the schema and every operation (design §20.2) |
| `content.py` | base items, enchantments, slot sizes, enemy XP and the level table — **greybox placeholders**, except the id rules at its top |
| `dungeon.py` | the Shallows: room templates stitched left-to-right, enemies, heal orbs and every drop PRE-ROLLED (design §18.2) |
| `api.py` | `setup_halcyon` — guest mint, state, characters (with starter gear), runs, run events, move/discard/fuse/reroll/salvage. Plain `def` routes |
| `sim.js` | the fight: PURE, deterministic, fixed 60 Hz (design §18.5). No DOM, no clock, no Math.random/sin/cos/atan2 |
| `render.js` | Canvas 2D drawing of the sim's state (and the town's) in the art doc's color roles; never changes it |
| `town.js` | the walkable town: a plaza, its stations (vault, forge, Dream Rift gate, one portal per realm in `REALMS`), `stepTown` |
| `client.js` | who is asking (Bearer or the guest pair) and the run's event QUEUE |
| `HalcyonRift.jsx` / `.css` | one screen: the stage (town or dungeon, with the vault / forge / discard panels over it) and the side panel (equipment, inventory); before both, the main menu |

Tests: `tests/` (store, dungeon, routes, class/practice/time rules, the sim fixtures' freshness),
`webapp/test/unit/halcyonSim.test.mjs` + `halcyonTown.test.mjs` + `halcyonClient.test.mjs`
(node), and `halcyonPlay` in `webapp/test/screens.mjs` (guest → character menu → Ranger → walk to the
vault → drag the bow in and back → the no-scroll sizes → walk to the portal → Shallows →
drag the vest off mid-run → put it on the ground and take it back → recall → reload, the vest still off).

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
  what you picked up before the server has minted it. A found item is NOT marked
  (owner's call, 2026-11-18: it was a dashed ring and read as noise).
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
  it is, ringed in the accent — one on the Reroll tab, two on Fuse. Leaving the forge
  drops the picks. See "The forge, RotMG-style" for what it does.
- **Two STANDARD weapon types per class, plus uniques** (owner's calls, 2026-11-18). The
  Ranger's are the shortbow (twin fanned arrows, fast, range 5) and the longbow (one
  heavy slow arrow, range 7); Paladin has the short-range
  mace and greatsword; Diviner has the wand and the range-8 starstaff; Ninja the shuriken
  and kunai. Each class's ability is in "One ability per class" below. The repeater
  (a three-bolt burst, range 6) is a rare UNIQUE drop. **A base's kind belongs to the base**:
  `store.init_schema` brings existing items into line with `content.py` (kind, and
  its tier is kept), so an item minted before a base changed kind follows it (tested).
- **A unique is TIERED like everything else (owner's call, 2026-11-19; it used to be
  tier 1 for good).** `dungeon._unique_tier` rolls its tier from its boss's own quality
  table (depth lift included) less the unique row, on its OWN stream so every other roll
  in the dungeon is unchanged. Its slot is a gold face with ★ and the tier, its name
  reads "Tidecaller · T4" like any item, and its tooltip is lit gold. The Kingfisher's
  Eye's Attack grows with tier like a band; unique weapons use the weapon ladder. The
  first unique weapon is the Tidecaller: three arrows in a wide fan that glance off a
  wall once (`bounce`, `sim.wallHit`).
- **Every number a player reads is flat** (owner's ask: "stop with all the
  percentages"). Attack and Dexterity are POINTS; each is worth 1/`STAT_SCALE` (25) more
  damage or shots a second. Damage per arrow, the points and every enchantment are whole
  numbers — an enchantment's value is `sim.enchantValue(id, q)` off `ENCHANT_FLAT`, so the
  store still keeps only quality. HP/MP regeneration is the one intentional exception: it
  is tunable to one decimal place and displayed as `/s`. The side panel's stats row (ATT,
  DEX, DEF, AP — damage, rate and range are the WEAPON's, in its tooltip) is `statsFor` of what is on, so it is what the fight
  will use. Points apply after the loop over gear, so gear order cannot change a number
  (tested). Base MP regeneration is 2.5/s; the Ranger's Volley starts at 8 damage per arrow.
- **HP and MP bars sit in the side panel**, under the character and above the stats,
  in town and in a run. HP is three parts: red what you have, light gray what
  regeneration can bring back (up to the recovery limit), dark gray what only a heal
  can. The bars repaint from the live sim each frame and touch the DOM only when a
  number changes (`Vitals`), so the fight never re-renders the page. The dungeon's
  canvas HUD draws HP the same way.
- **The town can be shot in** with the fight's own code (`sim.playerFire`, `wallHit`):
  the equipped weapon, the volley ability, two practice posts that float each hit's
  damage above them and show what the last three seconds came to a second below them.
- **The Dream Rift gate** opens a menu of the available dungeons. Practice runs use the
  real combat but grant no loot, XP, stats or item changes; death returns to town without
  killing the character, and `drop_item` is refused by both the page and the store.
- **Every rift has a deterministic timer.** It freezes on the boss-kill tick, not when the
  player reaches or leaves the portal. The store keeps the five fastest personal times per
  owner and dungeon; these are convenience data, not a competitive leaderboard.

## Levels and XP (2026-11-18, owner's calls on design §10.1 / §13.1)

- **XP comes from kills, plus a bonus for CLEARING a dungeon — paid when the boss
  dies, not at the portal** (owner's ask, 2026-11-18), and **recall keeps it** — so
  does a closed tab, and so does a recall straight after the boss. Death takes the
  character, level and all. The sim pushes a `cleared` event (`local`, never sent;
  the page shows the "cleared! +N XP" banner off it); the server adds `complete_xp`
  on the boss's `kill`, and `complete` only checks the boss is dead.
- **The server credits it from its own dungeon.** `dungeon.generate` writes each
  enemy's `xp` (`content.ENEMY_XP`) and the dungeon's `complete_xp` into the dungeon
  it stores; `store._apply_one` adds them on an accepted `kill` (the boss's carries the clear). XP is
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

`shared/catalog.js` has it — PUBLIC on the menu since 2026-11-18 (it was `adminOnly`
while it was a greybox; the guest/run/event limits in `api.py` and the idle-guest
prune are what make that safe) — with an accent (rift lavender, `#9d8ff2`) and
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
- **Dream runs are disposable.** `hr_runs.practice=1` prevents XP/loot/stat changes,
  refuses item drops, and skips the character/item destruction path on death or completion.
- **Boss times are personal only.** `hr_rift_times` keeps five fastest valid integer tick
  claims per owner and dungeon and labels each as normal or practice. It is not a proof
  boundary; competitive times would require a future replay/plausibility design.

## Not built yet (deliberately)

Per-dungeon stat progress (§10.2 — no dungeon but the Shallows exists yet), competitive
time validation, touch controls (the dungeon is keyboard + mouse), minimum-time
plausibility checks (design §18.3), input-log upload (§18.6), hiding the drop table
(above), and art assets are not built yet.

## The main menu, keys and waking (2026-11-18)
- **The page opens on a main menu** (`.hr-menu`): one card per character slot — a
  character's card (level, XP bar, weapon) enters the town as it; an empty one makes a
  new Ranger and enters with it. **A death returns you there**, with a notification
  saying so; a recall stays in town. Back in town goes to the menu, Back on the
  menu leaves the game. The side panel no longer has a roster. A new Ranger starts
  with the LONGBOW (`api.STARTER`).
- **Keys:** F recall, T auto-fire (in town and in a run), E interact (use a station,
  take the first item in reach, leave by the portal), G take everything in reach, Space
  ability, 1–8 equip from the bag.
- **Enemies wake by ROOM again, and the room LOCKS** (superseded the trigger-range
  waking on 2026-11-18 — see "Locked rooms and going deeper" below).
- **The Shallows are harder than at first**: chaser 55 HP, shooter 48, radial 95, boss
  1150, and each combat template has two more enemies.

## Snappy items, and what the side panel shows (2026-11-18)
- **A town move lands on the page in the same frame** (`townMove` in
  `HalcyonRift.jsx`): the item and whatever it swaps with change places at once, each
  one `version` on — the store bumps both by exactly one (`_set_place`), so the next
  move of a quick series names the version the server will find. Requests go one at
  a time on `moveChain`, in order; when the last has answered, the page reads
  `/halcyon/state` back (unless another move was made meanwhile), so a refusal shows
  its reason and the read-back puts things back. Moves never set `busy`; `act`
  (discard, fuse, runs) waits for the chain first. Run moves were always local.
  `halcyonPlay` holds the move route back 1.5s and still sees the swap at once.
- **Range is the weapon's, not the Ranger's**: it is in the weapon's tooltip, not in
  the stats (ATT DEX DEF AP). Every tooltip number is its own line.
- **Regeneration a second is on the HP and MP bars.** The town has NO bonus regen: MP
  refills at the gear's `mpRegen`, and a gear change only clamps it.
- **XP shows as it is earned**: in a run the level and XP bar are read off the sim
  each frame (`LiveHero`), so the boss kill (which carries the clear) moves the bar
  then, and nothing arrives on the way back — the end-of-run notification has no "+XP", and
  `endRun` keeps the run's XP on screen until the server's copy lands.

## Putting items down (2026-11-18)
- **In a run an item can go on the ground**: drag it onto the bin's place (it reads
  "Drop an item here (or on the stage) to leave it on the ground" in a run) or onto the
  stage. It lands at the Ranger's feet (`st.floor`, `{key, x, y}` — the sim only keeps
  WHERE; the page's `runControl.floor` keeps WHAT), and E takes it back into the first
  free bag slot. The page reports `drop_item` / `pickup_item`, naming the item by its
  drop if it was picked up this run (the store already accepted both). Whatever is
  still on the floor when the run ends is gone (the store destroys `ground` items at
  run end).
- **In town there is a floor too** (2026-11-18): the place `("floor", char_id)`, stored as
  `ground` under the run id `town:<char_id>` (`store.TOWN_FLOOR`). `move_item` puts an item
  there (never a locked one) and picks it up again (`_town_item(..., floor=True)` — only a move
  touches it; discard and fuse do not). `_clear_town_floor` destroys it (`destroyed_reason
  'left'`) in `start_run`, `open_character` and `leave_town` (the page's main-menu exit). The
  server keeps no position: the page's `floorAt` remembers where each was put down, and the
  town's `st.floor` / `st.nearFloor` draw it and let E take it before any station. The bin no
  longer discards (the discard route is still there, unused by the page). The Drop key (X)
  drops the item under the pointer in town or a run.

## Loot, the forge, modifiers, AP and notifications (2026-11-18, owner's asks)
- **Heals drop from enemies, never lie in rooms.** The templates have no `H` markers;
  `dungeon.generate` gives each non-boss enemy a `HEAL_CHANCE` (3.5%) heal, written as
  a pickup with an `enemy` field (~0.9 a rift, `test_dungeon`). The sim keeps those off
  the floor (`healsBy`) and `kill()` drops one where its carrier died.
- **Uniques drop only from the boss** (`UNIQUE_LOOT` by class, the "unique" row of the
  boss's quality table — see "Loot tables"); a bag holds at most `BAG_MAX` (8).
- **Rift modifiers** (`content.RIFT_MODS`: eight now — see "Locked rooms and going deeper"). E at a portal
  opens its panel; E again (or Enter the rift) goes in with what is picked. The run
  POST carries `mods`; `generate` validates them, writes `mods` + `scale` into the
  dungeon, and each modifier is one RARITY point that adds weight to the better rows
  of the quality tables — **never the drop count or the slot count** (owner's rule,
  tested). The sim reads `dungeon.scale` (enemy HP, enemy damage, enemy move and shot
  speed). The panel's numbers are `/halcyon/state`'s `odds.loot` (`content.loot_odds`,
  computed from the same tables at 0..8 modifiers, never typed twice).
- **AP (ability power) is a stat**, as Attack is the weapon's: `ability_power`
  enchants add points, `PER_LEVEL.ap` 1; `abilityPower = 1 + ap/STAT_SCALE` multiplies
  each ability's own lever (see "One ability per class": never a duration or a guard). An ability item's tooltip says
  what it does at the character's current AP (`abilityLines`). Base HP regen is 0.5/s
  (was 1.0); the `hp_regen` enchant rolls 0.2–1.2.
- **What is in reach shows as slots in the stage's bottom right** (`.hr-loot`): every
  bag drop and put-down item within `REACH`, click one to take it (queued, one a tick,
  through the same `take` / `lift` inputs E uses), or Take all / G. Hovering a bag on
  the canvas lists its contents (`.hr-bag-tip`). The canvas keeps only the portal
  prompt. A hidden pane gets almost no frames, so the panel updates only when it draws.
- **Sort** (beside Inventory): weapons, armor, abilities, rings; uniques first, then
  tier and slots. In town it works out the swaps on a local copy (each move one version
  on, as `townMove`) and sends them in order through `sendMoves`; in a run it is run
  moves. `halcyonPlay` drags the vest to slot 6 in a run and sorts it back.
- **Notifications, not banners**: `notify(text, tone)` puts a line in the top left
  (`Notices`), fading after 6s; "Log N" opens every one of this page load's messages.
  It replaced the result panel (its OK button), the error box (`setError` once the page
  is up becomes a notification), the Cleared/Recalled/Fallen banners and the canvas
  notes (pickups, levels, auto-fire). The floating damage numbers stay on the canvas.
- **The camera follows the player from the first frame** (`camera(..., follow=true)`):
  it used to sit on the start until the player walked off it.

## One ability per class (2026-11-18, owner's calls)
- **ONE standard ability per class, and NO cooldown** (owner's call, 2026-11-19, reversing
  the 2026-11-18 cooldowns): MP is the only limit, as design §7 says. Recasting the
  Paladin's field while it is up refreshes it. The HUD shows "Ready" or the MP cost.
- **Ranger — Volley Quiver**: the arrow fan. AP raises its damage.
- **Paladin — Stillness Orb** (moved from the Diviner): a field that slows ENEMY SHOTS
  inside it (not enemies), 5s. **AP widens it (`slowRadius`) and never lengthens it.**
  It also BURNS (2026-11-19): every `SLOW_PULSE` (30) ticks, every enemy inside takes
  `abilityDmg` (`SLOW_DAMAGE` 6, tier- and AP-scaled) — `slowPulse`, shared with the
  town's posts. Slight on purpose: ~12 a second at tier 1.
- **Diviner — Star Tome**: a star falls where you aim (clamped to 8 tiles), lands after 36
  ticks, hits everything within 1.5 tiles. AP raises its damage. `landStarfalls` is shared
  with the town, where it hits the posts.
- **Ninja — Mirror Charm** (new class; shuriken and kunai, Shadow Garb armor): for 1s the
  next hit is ignored, then 0.5s untouchable, and the next volley does `counterMult` x
  (2 x abilityPower). **AP scales the damage, NEVER the guard** — the owner does not want a
  late-game character to be invincible. A second counter before attacking does not stack;
  a counter that catches nothing still costs its MP.
- **The Grounding Aegis shield is retired, not deleted** — kept in the sim for a future
  class. Its content row is `retired`, and `init_schema` turns any into a Stillness Orb
  (and a Diviner's equipped Stillness Orb into a Star Tome).
- **Rings: two of the same base are fine; two of the same UNIQUE are not**, whatever their
  enchantment slots (`_check_fits`).

## The engine: stays in the browser (2026-11-18, owner's call)
- **Halcyon is a browser game on the site, and stays one.** The deterministic JavaScript sim
  (`sim.js`, shared with `town.js`) and the Python server are kept. When the look outgrows raw
  canvas (sprite art, animation, particles, shaders), swap ONLY the drawing — `render.js` — to
  PixiJS; if the sim ever gets slow, move just that hot part to Rust→WASM like the AI cores.
- **Keep `render.js` a pure "draw this state" layer** (it reads the sim, never changes it), so
  that swap stays a renderer swap and the sim, server and tests do not move.
- Godot and a Rust engine were weighed and declined: Godot's web export is heavy and would sit
  apart from the site's login, lobby and gates; Rust buys speed, not looks. Only shipping
  OUTSIDE the browser (Steam, app stores) would reopen this — and then Godot is the answer.

## Feel and loot pass (2026-11-18, owner's asks)
- **Chasers shoot too**: inside 3.5 tiles, a 14-tick telegraph, then one slow bolt that
  dies at its range (`ENEMY.chaser.shot`; own cooldown `e.scd`, in the fingerprint).
- **The Ninja throws slower and harder** (shuriken 20 dmg at 2.4/s, kunai 42 at 1.2/s —
  about the same damage a second) so the countered shot can be aimed. **A countered shot is
  drawn apart**: gold-white core at twice the size, a halo and a long gold trail; the player
  wears a gold ring while the next shot is countered.
- **Drops**: one enemy never drops the same base twice (a unique the boss already gave turns
  into a standard item). The boss's better odds are in "Loot tables" below.
- **The Dream Rift is a portal** (owner's call, 2026-11-18): not solid, `hw`/`hh` 0, reached
  from its centre like a realm's. (It was briefly solid as a disc with `rad`; `inStation` and
  `distanceTo` still read `rad` for any future round station.)
- **Coming back from a clear says nothing**; the in-run "cleared!" note carries the time.
- **Tooltip**: the item's own stats, then a rule, then ONE ROW A SLOT (◆ enchantment, ◇ empty
  slot). No "x of y enchantment slots" line.
- **No banner in play.** The site's `LobbyHeader` shows only on the main menu (and while
  loading). **Escape** closes what is open (tooltip, panel, question), else toggles the GAME
  MENU (`GameMenu`): Resume, the keys (they moved here from the line under the stage), Main
  menu — in a run, Recall and Recall-to-main-menu. **Nothing pauses under it** (owner's
  call): the fight goes on and the keys still work. The ☰ Menu button opens it with a
  mouse. `--slot`/`--vslot` were given the banner's room back (414→361, 330→250).

## Loot tables (2026-11-18, owner's ask: "rethink how to do loot drop tables")
- **Every random outcome is ONE roll on ONE weighted table that names every result,
  "nothing" included** (Diablo II's NoDrop row) — `content.DROP_COUNT`, `content.QUALITY`,
  `dungeon.SLOT_ODDS`, the class base tables. **Never a cascade of independent checks**
  ("10% unique, else 20% tier 3, else …"): each later check only sees what the earlier ones
  left, so its real rate is below what is written and the last row soaks up the rest.
  With one weighted roll a row's chance is exactly weight / total, and
  `test_drops_come_at_the_rates_the_tables_say` holds the generator to that (4 standard
  errors, at 0 and 3 modifiers). (Fusion's slot odds are the same table from a floor up —
  `content.fuse_slot_odds`, sent to the page as `odds.fuse_slots`.)
- **An enemy's loot is: how many (DROP_COUNT by enemy type), then for each item its quality
  (QUALITY: t1-t4 or unique), then its base, then its slots.** Ordinary enemies drop 0 or 1
  (20-35%) at T1 70 / T2 25 / T3 5. **The boss is a better table, not a jackpot** (owner):
  ONE item guaranteed, 30% a second and 10% a third (1.5 on average); T1 40 / T2 35 /
  T3 15 / T4 2 / unique 8 per item, so about 12% of bosses give a unique.
  Enchantment slots on a drop (owner's cumulative table: 1+ 50%, 2+ 18.75%, 3+ 4.69%,
  4 0.59%): 0 50% / 1 31.25% / 2 14.06% / 3 4.10% / 4 0.59% — `dungeon.SLOT_ODDS`, in 2048ths. Same slot odds
  for every source.
- **Each modifier is ONE LOOT BONUS, +15% (`content.LOOT_PER_MODIFIER`), and each level
  past the first another +10% (`LOOT_PER_LEVEL`)** (owner's calls 2026-11-19, "rarity for
  us is the number of enchantment slots"). The panels say only "Loot +N%" and "XP +N%",
  worked out on the page from the server's `loot_rule` — no odds, by the owner's wish.
  The bonus moves four things: QUANTITY, LINEARLY (`content.drop_count`: an ordinary
  enemy's 17% and a boss's 1.7-item mean are each (1+bonus) times base, so every
  modifier adds the same amount; a boss's extra comes as whole extra items plus one at
  the remainder's chance), SLOTS (an n-slot result weighs (1+bonus)^n more,
  `dungeon.slot_odds`, so the fourth slot gains most), TIERS (each `QUALITY` row's own
  `per` weight) and UNIQUES (the boss's chance is 1+bonus times its base, the unique
  row solved at each bonus, `content._unique_weight`). Every ordinary enemy drops at
  17% (a Splinter 8%: its Splitter spawns two), every boss 45/40/15 for 1/2/3 items.

## Locked rooms and going deeper (2026-11-18, owner's calls; design §14.1a, §14.6, §14.7)
- **Purely linear, and every room locks.** `sim.sealRoom`: the player ALL the way inside
  a room (`p.x - p.r > x0 && p.x + p.r < x1`) that still has enemies seals it — both
  doorways (`st.doorCols`, rows `doorY-1..doorY+1`, from `dungeon.rooms` + `door_y`)
  read as `"="` in `tileAt`, solid to feet and shots — and every enemy in it wakes at
  once. The last kill opens it (`roomLeft` is counted down in `kill`). Before a room is
  entered its doorways are a VEIL (`"|"`: walkable, shot-solid) and its enemies are
  IMMUNE (`!e.active` skips bullets and stars), so nothing is fought through a door.
  The boss arena is a room like any other. The tiles themselves never change: doors
  are a property of `tileAt`, so the renderer draws them from the same state.
- **One modifier pool of eight** for the town panel and the portal deeper, each worded
  for ordinary enemies and the boss alike, each one rarity point, no difficulty costs,
  no anti-combo rules. `dungeon.mod_scale` folds them into `dungeon.scale`: `hp`,
  `dmg`, `speed`, `shot` (enemy shot radius, Bulky), `cadence` (attack cooldown
  multiplier, Frenzied — every enemy cooldown goes through `sim.cadence`), `ward` /
  `ward_boss` (Warded: hits ignored per enemy, drawn as pips; `sim.hurtEnemy` spends
  them), `volatile` (a ring of shots where an enemy falls, queued in `st.rings` and
  fired AFTER the boss-death bullet clear). Swarming is the generator's: extra enemies
  from a SEPARATE rng (`:swarm<level>`) so the rest of the dungeon is unchanged.
- **Going deeper.** `generate(..., level=n)`: level 1 is byte-identical to before
  (fixtures unchanged but for new keys); deeper levels have `DEEP_ROOMS` combat rooms,
  health ×(1 + `LEVEL_HP`·(n-1)), ids prefixed `L<n>-`, their own seed. `offers` (three
  modifiers the run lacks, from `:offers<n>`, none at `MAX_LEVEL`) ride on every level.
  The boss's death opens `st.portal` (home) and `st.deeper`; E on `st.deeper` only
  emits a local `deeper` event — the PAGE shows the pick-one overlay, flushes the
  queue, calls `POST /halcyon/runs/{id}/descend {mod, from_level}`, and replaces
  `run.dungeon` (carrying HP, recovery limit, MP, XP and the bag; the floor is left).
  `store.descend` checks the boss is in `killed` and the mod was offered, MERGES the new
  level's enemies and drops into the stored dungeon (so drop ids stay unique per run
  and late events still validate), and answers a repeat of a descent that already
  happened with the same level. The time record is level 1's only; each level's boss
  pays its own clear bonus on the kill.
- Tests: `test_dungeon.py` (levels, offers, swarming), `test_store.py` (descend rules,
  merged drops, the floor left behind), `test_api.py` (the route end to end),
  `halcyonSim.test.mjs` (seal/veil/immunity/open, the boss arena, Warded, Volatile,
  Bulky, Frenzied, the two portals). Screens covers the eight-modifier panel; the
  descent itself is unit-tested and was checked by hand in a dev build.

## The death screen (2026-11-18, owner's ask)
- A death no longer drops straight to the main menu: `endRun` sets `fallen` and the page
  renders `DeathScreen` in place of everything (Escape does nothing; its one button goes
  on — the main menu, or the town after a Dream Rift). It shows what killed you, the
  run (rift, level, modifiers, time, kills, damage taken) and the equipment and bag that
  were lost, as locked `Slot`s with the normal tooltips.
- **What killed you comes from the sim**: every enemy shot carries `src`
  ("shooter:bolt", "boss:nova", "radial:burst" for a Volatile ring…, set through
  `st.src` at each attack), a chaser's charge passes "chaser:touch", and `hurtPlayer`
  keeps the last hit that landed in `st.lastHit`. `causeOf` turns it into words. A new
  enemy or attack needs a name in `ENEMY_NAMES` / `ATTACK_NAMES`.
- The run's kills, damage and time are counted on `ctl` (`kills`, `taken`,
  `ticksDone` across levels), not on a sim, because going deeper replaces the sim.

## The QOL pass (2026-11-18, design §19.1)
- **Settings live on the device** (`halcyon.prefs.v1`): `ACTIONS` in `HalcyonRift.jsx` is the one list of rebindable keys; both loops ask `actionOf(code)` / `dirOf(code)`, never a hard-coded `KeyE`. Escape, the arrows and 1–8 are fixed. The interface size sets the ROOT font size while the page is mounted (every size here is rem), and `--slot` subtracts `22.6rem`, not px, so the side panel still fits.
- **Item compare is side by side**, and every stat list (`STAT_WORDS`, `ENCHANT_ORDER`, `sortedEnchants`) uses one order. A new stat goes into both lists at the same position.
- **Lock** (`hr_items.locked`, `set_lock`): not a move, so no version bump; discard, fuse and a run's `drop_item` refuse it; Sort plans around it (`sortPlan`).
- **The graveyard** is `hr_characters.death_summary`, written by the `death` event BEFORE `_close_run` destroys the gear. The page's fields (cause, tallies) are bounded and only describe; the items and the rift are the server's.
- **The healing potion** is `input.potion` with `p.potionCd` (in the fingerprint); enemy damage numbers are drawing-only (`damageNumbers` with `foe`).
- **The run summary never opens on its own**: a clear's or recall's line in the log gets `report` when the run ends, and only a click opens it.

## Keys, Boss Rush, and the second QOL round (2026-11-18, owner's asks; design §13.4, §14.7a, §19.1)
- **Keys are items** (`content.BASE_ITEMS`, `kind: "key"`, slot family `key`, which fits no
  equipment slot; `fuse` refuses them). `dungeon.generate` adds them to the BOSS's drops from
  `content.KEY_DROPS` on a SEPARATE stream (`<dungeon>:<seed>:keys<level>`), so every other drop
  a seed makes is unchanged; the loot-rate tests skip keys.
- **`start_run` spends keys in its own transaction** and returns their ids (`spent`) so the page
  can take them out of the bag before the run's item copy is made: a Dream Key for
  `practice=True`, a Boss Rush key for a dungeon with `boss_rush`. Only the character's BAG
  counts (`_carried_key`), unlocked first. Practice + Boss Rush is refused.
- **Boss Rush** is `generate(..., boss_rush=True)`: no combat rooms at any level (entrance +
  boss). It is stored in the run's dungeon; `descend` passes it to `make` (only when set, so an
  older `make` without the argument still works) and refuses a next level that dropped it.
  `_record_time` skips it. On the page it rides in the `mods` state as the pseudo-id
  `boss_rush`, split out in `enter`.
- **No contact damage**: the chaser's touch is gone (`ENEMY.chaser.touch` removed). The
  potion heals to `recoveryLimit` and no further, never moving `p.low`.
- **Auto-fire** is `livePrefs.current.auto`, flipped by `toggleAuto()`; both loops read it
  live. It lasts the VISIT (town and every run) but is never read back from storage, so a
  fresh load starts with it off (owner, 2026-11-19). `setPrefs` builds from `livePrefs.current`, not React's copy,
  so a settings change never puts back an old auto-fire value.
- **A run's modifiers** are `runModRows(run)`: drawn under the minimap (`draw`'s `mods`) and
  listed with their wording in the game menu.

## The boss's mortar, no cooldowns, locking mid-run (2026-11-19, owner's asks)
- **Cover is for a moment, not for good** (`sim.MORTAR`, `bossMortar`, `stepMortars`). The
  boss keeps `e.hidden`, the ticks the player has been out of its sight (`inSight`: no
  `shotSolid` tile on the line between them). Past `after` (1s) it lobs a shell at where
  the player stands every `every` ticks (Frenzied shortens it): a red ring that fills for
  `delay` ticks, `dmg` on landing, then BURNING GROUND for `burn` (5s) that hurts
  `burnDmg` every `burnEvery` ticks, so the same spot behind the same pillar cannot be
  gone back to. In sight it lobs nothing. The boss's fall puts out its shells and fires.
  Sources `boss:mortar` / `boss:fire` for the death screen. Crumbling pillars were
  considered and deferred (owner's call).
- **No ability cooldown** — see "One ability per class" above. The Paladin's field burns.
- **An item found THIS run can be locked mid-run**: it has no id on the server until its
  pickup lands, so the lock rides the run's events as `{"type": "lock", "drop", "locked"}`
  (`store._apply_one`), naming the drop as a move does. Items from town still use
  `POST /halcyon/items/{id}/lock`, which works mid-run too.

## Fourth round (2026-11-19, owner's asks)
- **Tier 0 is starter gear** (`content.TIERS` now starts at 0; `api.STARTERS` are all
  tier 0). Nothing drops at it, so a new character's first finds are upgrades.
  `sim.tierScale` uses `tier ?? 1` (a `|| 1` would read 0 as 1) — 0.8x — and tier 0
  never SUBTRACTS max HP (armor's HP bonus is `max(0, tier - 1)`). Weapons no longer use
  it (see "Weapons follow the range").
- **EVERY item grows with its tier, abilities included** (owner's ask: "a t5 ability
  should have higher base effectiveness than a t2"). Damage abilities scale `abilityDmg`;
  the rest scale through `abilityTier` (the tier's 0.8–1.8 scale) — the Stillness Orb's
  reach, the Mirror Charm's multiplier (it was AP-only, so T2 and T5 read the same) and
  the shield's time — with AP on top. `halcyonSim.test.mjs` walks every standard base
  item from T0 to T5 and fails one that does not rise.
- **Modifiers pay XP**: `dungeon.MOD_XP` (+10% of the level's whole XP per modifier).
  Enemy XP rounds DOWN and the clear bonus takes the remainder, so the total is exact
  and the clear bonus never shrinks.
- **Heal orbs are taken by walking over them** (no E; there was never a prompt). An orb
  is left alone when it would do nothing (full HP and a full recovery limit).
- **Which class can use an item is said**: the tooltip says "Paladin only" / "Any class",
  in red when the open character cannot use it, and a refused equip names the class
  (`whyNot`) instead of "does not go there".
- **No "Right-click to lock" on the death screen or graveyard**: the hint follows whether
  the slot can lock (`tip.canLock`).

## The Fracture — the second rift (2026-11-19, owner's pick; design §14.4a)
- **A dungeon is a SPEC in `dungeon.DUNGEONS`**: its room templates (`combat`,
  `boss_room`), enemy `weights`, `quality` (the enemy and boss loot-table names in
  `content.QUALITY`), `boss_kind`, `boss_xp` and names. A new rift is a spec plus its
  enemies in `sim.js`/`render.js` and a palette in `render.PALETTES`, keyed by
  `st.dungeonId`. The town's portals are `town.REALMS`.
- **Torn floor**: `x` in a template is void. It blocks walking (`walkSolid`) but not
  shots (`shotSolid`), so it is cover from bodies, not from bullets.
- **Cracks**: digits `1`/`2`/`3` in a template are crack tiles, grouped, and the generator
  lists them as `cracks: [{room, group, tiles}]`. They cycle on `sim.CRACK` (warn, open,
  close; groups staggered) ONLY while their room is sealed. An open crack reads `x`
  from `tileAt`. Opening under the player throws them to the nearest clear spot and
  hurts (`rift:crack`); an enemy is moved clear without harm. A template must stay
  crossable with any one group open (`test_dungeon.py`), and no spawn or doorway may
  sit on a crack.
- **Enemies**: Shard (a turning cross), Splitter (an aimed pair, then splits), Splinter
  (a small fast spitter), Flicker (marks a spot, blinks there, fires a ring of eight).
  A marked destination lives in `e.toX/toY`, NEVER `aimX/aimY` (the Tidewarden's fan
  telegraph reads those). The Flicker picks no spot on a crack, and if a crack opens
  where it is about to land it lands on the nearest clear ground.
- **Splinters are pre-rolled**: each Splitter has two enemies with `parent` set. They
  start `dormant` (out of play, not drawn, not sealing), the parent's kill releases them
  at its body, and the room stays sealed until they fall. The store REFUSES a splinter
  kill before its parent's, so no client can credit one early.
- **The Breach** keeps `type: "boss"`; `e.form = dungeon.boss_kind` picks its step
  (`breachStep`) and its HP (`sim.BOSS_HP`, 1950). Nothing it fires TURNS (the spiral is
  the Tidewarden's; owner's note): FAULT lines (`sim.FAULT`) are marked from its body —
  a Y aimed at the player, an X in phase 2, two waves — then tear into a still wall of
  shots, each line stopped at the first pillar or wall (the mark is drawn to that same
  length); SHATTER shards (`sim.SHATTER`) fly slow and burst into rings; TEARS are an
  aimed line, fast to slow. Rests are short. At
  half health its cracks run at double speed (`st.fastRoom`) and it blinks between four
  anchors around its home. It lobs the mortar like every boss.
- **Harder, with better loot**: `fracture_enemy` drops T2–T4, `fracture_boss` T3–T5 plus
  the unique (`quality_table` solves the unique weight for any table with a unique row).
  `/halcyon/state` gives each dungeon its own `loot` entry per modifier count (the panel
  reads only its `loot_bonus` and `xp_bonus`).
- Fixtures: `halcyon-dungeon-fracture-a.json` (seed `fracture-a`) beside the Shallows'
  pair, held to the generator by `test_sim_fixtures.py`. The rules are
  `webapp/test/unit/halcyonFracture.test.mjs`.

## Quieter notices, and Equippable in the vault (2026-11-19, owner's asks)
- **A recall says "Recalled to town." and nothing else** — no list of what came back.
- **Picking an item up is silent unless it is a unique** (town floor, run floor and drops
  alike); a unique still gets its gold line.
- **The vault's Equippable chip** shows only what the open character could put on (a worn
  slot, and its class or any class). It combines with the type chips and the search.

## Progression: three to start, depth for the rest, tiers to 10 (2026-11-19, owner's calls)
- **A run starts with at most `content.START_MODS` (3) modifiers**; each level deeper adds
  one (up to 7 at level 5). The store refuses more at level 1; the panel greys the rest
  once three are on. Going deeper is the only way past three.
- **Depth pays what modifiers cannot**: +10% loot a level, and every standard drop's tier
  is LIFTED one per level past the first (`content.DEPTH_TIER`, capped at `MAX_TIER`
  10; `quality_table(source, rarity, level)` merges rows that land on one tier). Tiers
  6-10 come only from depth; the Fracture's boss has a rare T6 row so its level-5 boss
  can reach T10. `content.TIERS` is 0-10; `render.TIER_COLORS` names all eleven.
- **Abilities run off one table, `sim.ABILITY` (owner's numbers, 2026-11-19).** Every
  ability costs 30 MP at T0 and 5 more a tier (`abilityCost`, 80 at T10). Effects:
  Volley 55 damage in all (+10 a tier, shared by its 7 arrows), Starfall 45 (+10), the
  Stillness field 2.0 tiles (+10% a tier, 4.0 at T10) burning 6 a pulse (+20% a tier), the
  Mirror counter x2.0 (+0.4 a tier, x6 at T10). Each step was checked to be worth at
  least as much PER MP as the one below it (`the ability table` unit test), so a higher
  tier is never the worse buy.
- **The counter is the one ability with a cooldown: a flat 6s, and no refund.** Its catch
  window (1s) and guard do not grow with tier. Without the cooldown a cheap T0 bought the
  most invulnerability per MP; with it, how much you are protected is fixed and the tier
  buys damage. 6s keeps early MP and regen meaningful (a 12s cooldown would have made them
  pointless at T0). `p.abilityCd` is in the fingerprint; the HUD shows the seconds left.
  `effectScale` (12% a tier) now drives only the retired Grounding Aegis.
- **The Fracture opens per CHARACTER, once it has felled the Shallows' boss in a real run**
  (`content.REQUIRES`; `store._cleared` reads the boss id with `json_extract` and the small
  state, never the whole dungeon; a Dream Rift does not count). The store refuses the run
  (Dream Rifts too) and `owner_view` lists each living character's `cleared`; the portal
  panel says what opens it.
- **The Stillness field lasts 4s** (`SLOW_DURATION`); full uptime at T0 needs 7.5 MP/s, past early gear.

## Weapons follow the range (2026-11-19, owner's calls)
- **A weapon's `dmg` is its TIER-0 damage, and each tier adds a fifth of it, flat**
  (`sim.weaponDmgAt`): tier 10 is 3x tier 0 and every tier is a different number. Each
  `dmg` is a multiple of 5 so the step is whole. Later upgrades mean less, by choice.
- **Damage a second follows the range**: one target, every shot landing, tier 1 is about
  `55 x sqrt(5 / range)`: mace 72 (3 tiles), greatsword 59, shortbow 60, shuriken 55,
  wand 50, kunai 47, longbow 45, starstaff 42 (8). The shortbow gets +10% (both arrows
  land only up close), the kunai -5% (the fastest shot). `rate` was nudged to meet it.
  The uniques (Repeater, Tidecaller) sit off the curve on purpose.
- **No base weapon pierces** (the longbow, greatsword and shuriken did); the Kingfisher's
  Eye is the one source. The unit test `weapon damage follows the range` holds all of it.

## Armor is shared by type (2026-11-19, owner's calls)
- **Two LIGHT armors (Ranger, Diviner) and two HEAVY (Paladin, Ninja)**, so a build can
  choose; abilities stay one per class. `cls` may be a TUPLE (`content.usable_by`, the
  store's equip check, and `classOk`/`classWords` in `HalcyonRift.jsx`, which name both
  classes: "Ranger or Diviner only"). No item converts: the four armors kept their ids.
- **The pair stays close** (owner: "don't make the stats that dramatically different").
  Every armor gives Defense and HP; the two of a type are 1 Defense apart and lean a
  little: Leather Vest Def 1+t, HP +10/tier above 1, MP +5/t; Seer Robes Def t, HP +5,
  MP +12/t, regen +0.5; Plate Def 2+t, HP +15; Shadow Garb Def 1+t, HP +10, Dex
  1+floor(t/2). Held by the unit test `the two armors of a type stay close`.
- **A class's armor share of its loot (22) is split 11/11** between its two armors.

## The unique roster (2026-11-19, owner's list)
- **Fifteen more uniques**: rings for anyone (Ember Loop, Miser's Coil, Leechstone, Glass
  Ring, beside the Kingfisher's Eye); two unique armors per type (light: Windrunner's
  Cloak, Mantle of the Full Moon; heavy: Thornplate, Duskmail); and per class the Gale
  Quiver (Ranger), Oathhammer + Anchor Orb (Paladin), Comet Rod + Codex of Echoes
  (Diviner), Ricochet Chakram + Echo Charm (Ninja). Every number is `sim.UNIQUE`; the
  effects are flags `statsFor` sets (`burn`, `costCut`, `leech`, `moveMult`, `fullMoon`,
  `thorns`, `dusk`, `gale`, `anchored`, `echo`, `echoRing`) and weapon fields (`splash`,
  `comet`, `ret`) copied onto each shot.
- **`dungeon.UNIQUE_LOOT` is derived**: each class gets the five rings, its armor type's
  two and its own, all weight 1. The boss's unique CHANCE is unchanged, so each one is
  rarer than the three were. `test_every_unique_drops_for_a_class_that_can_wear_it`.
- **The town runs them too** (`cometBurst`, `turnBack` and the burn are shared; the
  cloak's speed reads `st.stats.moveMult`); the Oathhammer's splash does not, because
  the posts stand apart. The Anchor Orb's field sits at `st.slowAt`, which the pulse, the
  shot slowing and the drawing all read (null = round the player).
- **Nothing here adds invulnerability**: the Echo Charm keeps the counter's window,
  guard and 6s cooldown; it only adds blades. `halcyonUniques.test.mjs` drives each one
  through the real sim, and fails any base with no name or a duplicate abbreviation.
- **Each unique has ONE home dungeon** (owner's ask, 2026-11-19: an incentive to run a
  specific rift for a specific unique). `content.UNIQUE_HOME` names it and sets `home` on
  the base; `dungeon._item` keeps only uniques at home in the dungeon being generated.
  Every class has uniques in both dungeons, and each armor type has one in each. The
  tooltip says "Found in The Shallows". `test_every_unique_has_one_home_dungeon...`.
- **The Dream Key drops 25% of the time per boss** (was 10%; owner's ask, 2026-11-19).

## The forge, RotMG-style (2026-11-19, owner's calls)
Modeled on RotMG's enchanting, minus its percentages, dust colors and artifacts.
- **Rarity is still the slot count** (`content.SLOT_ODDS`, moved from dungeon.py so
  fusion reads the same table). **Each line has a LEVEL I-IV**: the quarter of its
  stored quality (`content.line_level`, `sim.lineLevel`), so items from before levels
  kept their exact numbers. A new roll picks the level by `LINE_LEVEL_WEIGHTS`
  (35/28/22/15: IV ~2.3x rarer than I) and then a spot in that quarter — from ONE draw
  (`content.line_q`), so no stream after it moved. A stat never appears twice on an
  item (the store refuses it). **Values are flat and do not grow with tier** (owner):
  strong on a level-1 character, solid on a level-20. `mp_regen` tops out at +1.5 (was
  2.5: base regen is 2.5, so four lines more than quadrupled casting).
- **SPECIAL LINES** (`content.ENCHANTS` `special`, `sim.SPECIAL`): tradeoffs — Fury
  (+Attack, -3 Defense), Glass Mind (+AP, -20 HP), Fleetfoot (+Dexterity, -15 HP) — and
  triggers — Kindling (a cast sets the next 3 volleys burning), Second Wind (MP back on
  a kill, once a second), Bulwark (+Defense for 2s after a hit, every 4s). They are only
  ever DROPPED, from depth 3 down: `SPECIAL_CHANCE` per slot 0.1% / 0.3% / 0.8% at
  depth 3 / 4 / 5 — measured ~1 per 210 / 80 / 21 level clears ("extremely extremely
  rare" at 3, still rare at 5). Their own stream per drop (`dungeon._specials`), so
  every other roll is unchanged (tested). A reroll or fusion never makes one.
- **SHARDS** are the one currency, the OWNER's (`hr_owners.shards`). Each kill in a
  real run adds `SHARDS_PER_KILL` (boss `SHARDS_PER_BOSS`) x (1 + the loot bonus) to
  the RUN (`state.shards`), banked by `_close_run` on a recall, a clear or a sweep; a
  death loses them and a Dream Rift pays none. **Break down** (`store.salvage`) turns
  an item into `content.salvage_value(tier, slots)` shards.
- **Reroll** (`store.reroll`, `POST /halcyon/items/{id}/reroll {keep}`): every line not
  kept is rerolled into a REGULAR line the item does not hold. Price
  `content.reroll_cost` = (8 + 2·tier + 6·slots) x 2^kept. A special line is always
  kept and counts. Unique EFFECTS live on the base, never on a line, so no reroll can
  touch one. The page works the same price out from `/halcyon/state` `odds.reroll`.
- **Fusion** (`store.fuse`): two of the SAME BASE, any tier and slots. The result has
  at least the FEWER slots, more by the slot table from that floor up
  (`content.fuse_slot_odds`: 0 -> 50% for 1+, 1 -> 37.5% for 2+, 2 -> 25% for 3+,
  3 -> 12.5% for 4), the higher tier and fresh regular lines; the page warns when an
  input carries a special line. The old 4%/20% `FUSE_SLOT_GAIN` is gone.
- Tests: `test_store.py` (reroll, locks, salvage, fusion floors and odds, shards banked
  / lost), `test_dungeon.py` (level weights, special odds by depth, their own stream),
  `webapp/test/unit/halcyonSpecialLines.test.mjs` (every special line in the sim).

## The Ashen Breach — the third rift (2026-11-19, owner's pick)
- **Opens after the Fracture** (`content.REQUIRES["ashen"]`), per character like the
  Fracture. Loot: `ashen_enemy` T3–T5, `ashen_boss` T4–T7 plus the unique (weight 8).
  Clear bonus 100 XP, boss 60. **The Fracture's boss is NAMED the Schism now** (the word
  "breach" went to this rift); its `boss_kind` stays `"breach"`, which old saves and the
  sim read — rename display names only.
- **The rooms burn: `sim.CREEP`.** A spec's `hazard: "creep"` reaches the dungeon (only
  when set, so older dungeons are byte-identical). Ten seconds after a COMBAT room seals,
  its outermost ring of tiles catches, then one ring every 4s (the next flickers for its
  last second), until about three tiles are left across the narrow way (`creepMax`).
  A ring is `min(distance to each of the room's four sides)`; the room's top and bottom
  rows are `st.roomY`, found from the tiles. It hurts like the mortar's fire
  (`rift:fire`) and `st.creep` goes null when the room clears. `creepAt(st, x, y)` is
  the one reader (2 burning, 1 warning) for the burn and the renderer.
- **Enemies**: Cinder (a fast chaser that drops `cinder:fire` every 12 ticks), Kiln
  (stands still and lobs a firebomb at where you stand — a mortar entry with its own
  `dmg`, `burn`, `d` (delay, for the fill), `src` and `fire`), Smolder (does NOTHING until
  hit — `lit` — then flares, charges and bursts into a mortar where it is, and dies;
  the burst is a kill the server credits). Shooters are mixed in.
- **The Pyre** (`pyreStep`, 2800 HP): rings of 16 shots, and CROSSES of fire — a + then
  an x of shells centred on the player (`flameCross`, each arm stopped by a wall). At
  half health its arena burns in (`st.creep` with `bossEvery`) and its two Kilns come in.
  **The Kilns are generated with it, marked `summon`, NOT `parent`**: dormant until then,
  killed with it if it falls first, and the store takes their kills in any order (a
  `parent` kill is refused before its parent's).
- **Player-owned fire: `st.embers`** (`{x, y, r, until, dmg}`), drawn pale blue so it never
  reads as the enemies' orange. `emberPulse` hurts each target once per `EMBER.every`
  ticks by the hottest ember it stands in; it never hurts the player. Shared with the
  town's posts, as are `trailEmber`, `flareLand` and `burstStuck`.
- **The nine uniques** (all home `ashen`): Phoenix Feather (a killing hit leaves 1 HP once
  a LEVEL — `p.phoenixUsed` is not carried deeper — with a 1s guard and fire round you),
  Ash Sigil (an enemy dying while burning — `burnUntil` or `scorched` from an ember —
  blasts its neighbours), Banked Coal (+1 Attack per 1.5s unhit, to a cap; `p.hitAt`),
  Emberweave (a trail of embers while moving), Cinderguard (fireproof, + Defense while
  `p.inFire`), Flare Bow (every 4th volley, `p.volleys`, is a flare that lands as an
  ember), Censer (a field that burns 2x and slows to 75% — `st.slowF`), Meteor Tome (the
  star leaves a crater ember), Ember Kunai (sticks — `st.stuck` — and bursts 1s later
  for 60%). Every new piece of state is in `fingerprint`.
- **The town**: the Dream Rift moved to (7, 9.6) so stepping out of the first of three
  portals does not land in its reach. Rules: `webapp/test/unit/halcyonAshen.test.mjs`;
  fixture `halcyon-dungeon-ashen-a.json`.

## Art: the loader, the slots and the gallery (2026-11-19, owner's plan step 2)
- **`halcyon/art.js` is the one place art is named.** `SLOTS` lists every picture the
  renderer can ask for (four classes, every enemy and boss kind, the plain shots, five tile
  parts per rift and the town) with its frame size in ART pixels — a tile is `ART_PX` (16)
  wide, so a picture is drawn at `px / 16` screen pixels per art pixel. `MANIFEST` lists
  the pictures that EXIST, one line per file in `webapp/public/art/halcyon/` (not
  `public/halcyon/`: a static folder named like the `/halcyon` route would sit on it).
- **Nothing waits for art.** Every draw in `render.js` asks `drawSprite`/`drawTile` first
  and draws its greybox shape when the answer is false — no line in the manifest, still
  loading, or failed. So art lands one picture at a time and an empty manifest is the
  greybox exactly. A sheet is frames across and facings down (`FACINGS`: down, side, up);
  facing left mirrors the side row. Only the PLAIN shots take a picture so far; the shaped
  ones (flare, star, blade, shard, power) keep their shapes until they get slots.
- **`/halcyon?art` on the dev server is the gallery** (`ArtGallery.jsx`; the production
  build drops it with the `import.meta.env.DEV` branch). It draws every slot on each rift's
  floor through the game's own draw functions, at a chosen tile size and facing, and takes
  a dropped generated image for any slot: the flat `#00FF00` background keyed out, cropped,
  shrunk to the slot (characters to a chosen height, bosses twice that), edges made fully
  in or out, optionally three facings side by side. A preview lives in that tab only.
- **The gate:** `webapp/test/unit/halcyonArt.test.mjs` derives the roster from `sim.js`
  (every enemy type, boss kind and class must have a slot) and holds `MANIFEST` to the
  files with `checkManifest` (unknown slot, missing file, a sheet the wrong size).
  Still to add with the first real art: a color-role check (a picture using a color
  reserved for another job).
