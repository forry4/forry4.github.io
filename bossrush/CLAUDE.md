# Boss Rush — Claude Context

A three-boss speedrun on Halcyon Rift's greybox fight. The fight is `sim.js`, a pure,
deterministic simulation that runs in the browser; the server (`api.py`) deals the arenas,
owns the clock and keeps the boards. Solo runs start with `POST /bossrush/runs`; co-op runs
are opened by the co-op room socket (`coop.py`).

| File | What it owns |
|---|---|
| `sim.js` | the fight: one tick of 1/60 s, `step(state, input)`, every boss |
| `crypt.js` | the Crypt Trio's attack schedules, telegraphs, and area hits |
| `render.js` | drawing a state (live, replay and film alike) |
| `replay.js` / `film.js` | a run rebuilt from its controls / a run kept as its frames (the boards' replays) |
| `lockstep.js` | co-op: each seat's controls, tick by tick |
| `BossRush.jsx` | the menu, the boards, the solo run page |
| `Coop.jsx` | the co-op room (shared `WaitingRoom`) and the co-op run page |
| `api.py` / `coop.py` | runs, clock, boards, films / the co-op rooms and the input relay |

## CO-OP (owner's ask, 2026-11-22)

Rift and Crypt support two to four players. Each additional player adds 130% of solo
boss HP, for 2.3x, 3.6x, or 4.9x total. Aimed attacks choose one living hero and attack
counts and schedules match solo. The Schism sweeps the closest living hero's bank. Lantern
keeps its two-player rules. The fight ends when everyone is down, and a fallen hero
comes back for the next boss on the recovery margin.

- **The sim holds party members by SWAPPING them onto the state.** The rules read the hero as
  `st.p` / `st.stats` / a few more keys (`HERO_KEYS`); in co-op each hero's own copies live
  in `st.heroes[i]` and `useHero(st, i)` puts that hero on `st` while it acts, moves, fires
  or is hit. Between ticks hero 0 is on `st` and every record is current, so `heroView(st,
  i)` is all the renderer needs. Solo (`partner` absent from `createSim`) runs the exact
  one-hero code path — the refactor was checked against the old sim's fingerprints over
  every boss and character, both phases and the kill.
- **What is NOT doubled, on purpose.** An enemy walks toward, and its facing follows, the
  NEAREST living hero (`nearestHero`), so the Warden's gavel and chains still come from his
  front (the other player can work his back). The Schism's warning locks in one bank for
  the sweep. Legacy pair replays preserve the previous rotation.
- **CONFIRMED TICKS AND PREDICTION.** Every browser runs the same fight and sends each
  input on the tick it was sampled. The renderer steps ahead with the local input
  and each peer's last held controls, up to the connection's prediction window.
  Late inputs can rebuild that tail from the last confirmed fight. Only ticks with
  all seats' rows drive the clock, the recording and the outcome. Missing rows can be requested from their seat. Every
  `FP_EVERY` ticks each browser sends a hash of `fingerprint(st)`; a mismatch ends the run
  "out of step". Each stage starts after all browsers have installed their input listeners.
  They flush their last input rows and agree on the terminal tick and fingerprint before
  moving on.
- **A DROPPED SEAT CAN COME BACK (2026-11-28).** The server keeps every input row it
  relays (per stage and seat, as compact JSON, `coop.py _remember`). A seat whose socket
  closes mid-fight is AWAY for `GRACE_S` (30 s): the others are told (`away`), stop their
  stall timeout and wait. A browser that rejoins in that time, by reconnecting or by
  reloading, gets `resume` with every stored row. `resume.js restoreRun` replays the
  bosses already beaten (rebuilding the recording and the HP carried forward), and the
  encounter fast-forwards the current boss through the stored rows and samples on from
  the first row it never sent. A resume is only offered when every live peer holds
  exactly the stored rows: a seat whose rows were relayed past a gap, or a run past
  `RESUME_MAX_BYTES`, still ends the fight. Past the grace period the run ends ("left").
  Players can start again from the room, or the host can free an offline seat (a
  browser that cannot prove its seat is told to ask for that, `SEAT_HELD`).
- **A hidden tab keeps the fight moving.** It has no animation frames, so a timer
  (`HIDDEN_TICK_MS`) keeps confirming and sending its rows, with neutral input (the hero
  stands still). The others are told (`hidden`) and wait without timing out.
- **Sends never wait.** Every socket has its own outbound queue and writer task
  (`_open_outbox`), so neither the room lock nor the input relay waits on a slow or
  half-dead connection (a 3 s send timeout under the one lock used to hold up every room).
  A socket that stops reading is closed after `OUT_QUEUE_MAX` queued messages. A run carries the occupied lobby
  slots in simulation order so a gap in the lobby slots does not create a phantom player.
- **THEREFORE `sim.js` MUST BE BIT-IDENTICAL IN EVERY BROWSER.** No `Math.sin`, `cos`,
  `atan2`, `hypot`, `exp`, `pow` — engines differ in the last bit — use `dsin`/`dcos`,
  `rotate` and `Math.sqrt`. Solo got away with a few (a replay re-runs in the browser that
  recorded it); co-op spans multiple browsers and possibly multiple engines. All seats
  must run the same build. Protocol 3 rooms retain the legacy two-seat game.
- **The host reports, like a solo player.** The host waits for each room's entry request
  before posting its clear. The server relays the next stage and saved time to everyone.
  Co-op runs share their own board, whose five best keep films. The board and personal
  filters include every member of the party.
- There is no pause in co-op: Esc opens the menu over a fight that keeps going. Any member
  may start the next run (Play again, hold R) once the host has started the first.

## The look of the pages (owner's ask, 2026-11-26)

The menu, the run header and the pause / result panels take the arena's materials
(`BossRush.css`, "THE DUNGEON LOOK"): a panel is a plain stone slab in a pixel frame
whose corners step in, drawn by offset box-shadows; a hero you pick sits in a carved slot
(`--br-slot-frame` turns gold); the page is the floor's tile grid; shadows are hard; the
shade over a fight is a dither. `KeyHints` shows the controls as key caps and `RunTrail`
(common.jsx) the run's bosses on the result panel. **The owner then chose, from a
side-by-side of options:** no bricks behind any text (they made it hard to read), the
boss-set cards as they were before (rounded, lighter, dark rounded boss boxes), and the
site's own buttons (a pixel button style was tried and rejected). Do not bring those back.

## Frame time (2026-11-27)

Measured on the owner's laptop (Intel graphics, 240 Hz, 2550x1385 canvas): a plain
full-screen canvas misses 0% of frames there, so whatever the fight misses is ours.
Three costs were the fight's, each per frame over the whole screen, and none of them may
come back:
- **The floor copy uses `imageSmoothingQuality = "low"`** (render.js): "high" on that
  stretch was 28.7% of frames missed; "low" looks the same.
- **The vignette is painted once per size and only its outer band is copied**
  (juice.js `edgeLayer`): recomputing the radial gradient over the screen each frame
  was ~5% missed on its own.
- **The arena's shade is baked into the floor** (`ARENA_SHADE`, and the backdrop is
  pre-shaded `#181d1d`), not laid over the screen each frame.
Together: the Pyre went from ~4-6% missed to ~0.1-1.3%. The next cost is the large
additive light under the boss (`drawBossLight`); cutting it changes the look, so it is
the owner's call. It no longer breathes (owner, 2026-11-27: "no need for that"), and
the owner then OK'd shrinking the glows ("the game should run on low-end laptops"): the
boss's light pool is 2.6 boss radii (was 4.2), a shot's halo `SHOT_GLOW` 1.8 shot radii
(was 2.6), and the vignette is clear to 70% of the half-diagonal (was 55%). Phase-two
Orrery on the owner's laptop, plain canvas at 0.0-0.1%: 4.6-4.7% missed before, 0.0%
after, twice each. Keep new glows to the same budget: fill area is what costs here.
**The hit flash** (the red ring over the dark one) was ~5% of frames missed while it
showed against ~0.5% otherwise, and the first hit also stalled to paint its image. Both
vignette images are now painted on the fight's first frame, and the red ring is thin
(clear to 85%, was 62%). Tried and dropped: one combined quarter-size image per flash
strength, stretched — it read worse on the real screen outside hits than the plain
full-size copy did.
**Ruled out, do not retry:** garbage collection (in a phase-two Orrery trace, 5 of
375 missed frames overlapped a GC and none a long task: the misses are the GPU's), and
**adaptive frame pacing** (drawing every 2nd refresh when frames miss): skipping a draw
shifts the browser's own frame timing, the pacer reads that as more misses and keeps
slowing itself; on the real screen it went from 0.4-0.8% hitches to 21-38%. Frames before and after were compared pixel for pixel: at most 5/255
apart (6 in the red hit flash), from rounding. Measure with the GPU cool: after ~40
back-to-back runs the same laptop missed 3.4% on the plain canvas.

## Load times (2026-11-26)

- **Between bosses nothing waits on the server.** Entering a portal queues that fight's
  clear behind the run's other clock calls (`syncClock`'s `pending`, paths in order) and
  opens the next rift at once; the next entry queues behind the clear, so the server
  still times each fight from entry to clear. Only the LAST clear is awaited, because it
  returns the time. A failed send stays at the head of the queue and goes again with the
  next one. `bossRushPlay` drops the first clear and holds its retry until Boss 2 is up.
- **`request()` retries** a dropped connection or a 502/503/504 three times (0.4, 1.2,
  3 s) before the player sees an error (the browser's own words for it are "Failed to
  fetch"). Every route is safe to send twice. `bossRushCoop` fails a clear four times to
  reach the co-op retry path.
- **The arena texture is baked ahead.** A bake is ~100 ms of drawing (more on a phone), so
  `prebakeArena` paints the next arena a few rows per frame while the hero walks to the
  portal, and the first frame that needs it finishes what is left. A sim's `tiles` IS its
  dungeon's array, which is how the next fight's sim finds that bake. The sliced bake is
  pixel-identical to a whole one (checked on all nine arenas).
- **The sound engine is made on the menu's first press** (~100 ms to create), and Start run
  sends its request before the sound, so neither delays the run opening.

## Sounds (owner's picks, 2026-11-26)

`sound.js`: synthesised with Web Audio, no files, as Box Puzzles does (read its
CLAUDE.md "Sounds" before changing the context, the iPhone "ambient" session or the
tanh master bus). The kit is the owner's pick from the "Boss Rush Sounds" audition
artifact, ported as heard: do not re-tune by ear. The big-attack warning was offered
and NOT picked, so telegraphs are silent; the run-start horn and the boss's death
wail were cut after the owner played them, and every sound but the two portal ones
plays at 60% of its auditioned level (`LEVEL`, 2026-11-26).
- **Render-only.** `createHearing()` makes one watcher per fight; the run page calls
  `hear(st, hero)` once per drawn frame and it compares VALUES with the last frame
  (fire and ability cooldowns jumping up, the hurt timer, a new foe damage number, a
  boss's phase, the portal appearing). `sim.js` is untouched, so co-op stays
  bit-identical, and nothing compares objects: co-op draws a predicted copy that can
  be rebuilt between frames.
- The run's beats (portal entered, ended, set cleared) play off the run
  page's `status`; the menu's off their clicks.
- The context is made only inside a press (`primeSound` on keydown / pointerdown, and
  every menu sound); a sound asked for from an animation frame before then is dropped.
- The speaker toggle (`MuteToggle`, common.jsx) is in the run header and beside
  Start run; localStorage `bossrush.muted`. `bossRushPlay` counts voices: a pick
  sounds, it is silent muted, and a whole run makes at least twenty.

## Gates

The Crypt Trio is public in solo and co-op. The set listing requires `crypt=true`
to show it and `crypt_coop=true` to advertise co-op support.
The Orrery's corner emitters rotate every beat in both phases; in phase two it also orbits the center.
Its rails are one width (radius 0.51) in both phases, and its spoke rings are full, none left out:
10 shots in phase one, 12 in phase two (owner, 2026-11-26).
The Glassweaver uses crossing walls of shots with marked gaps. Its second curtain sweeps diagonally in phase two.
When it drops to half, any wall still on its warning is called off (`beginCryptTransition`), so the last
phase-one curtain cannot still be crossing the room when phase two opens with its own (owner, 2026-11-26).
The Null Cantor fires echoes through past player positions while aiming fresh fans.
Its phase-two echoes fire in reverse order.

- `webapp/test/unit/bossRushCoop.test.mjs` — HP multipliers, Crypt attack-count parity,
  targeting, seal on both, down-not-dead, determinism.
- `webapp/test/unit/bossRushLockstep.test.mjs` — the buffer, and two lockstepped fights
  over a jittery link staying identical.
- `webapp/test/unit/bossRushResume.test.mjs` — a rejoin rebuilds the beaten bosses and the
  current one exactly from the kept rows; short rows are refused, not guessed.
- `screens.mjs` → `bossRushCoopRejoin` — a dropped connection waits and rejoins, a reload
  rebuilds the run, a hidden tab is announced; one time and an exact replay after all three.
- `bossrush/tests/test_coop.py` — seats bound to their proof, one run for the pair, the
  relay, the co-op board.
- `screens.mjs` → `bossRushCoop` — two browser contexts through three bosses by invite link.
