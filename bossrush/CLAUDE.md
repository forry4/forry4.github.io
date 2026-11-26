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
  moving on. A dropped or reloaded seat ends the party's fight. Players can start again
  from the room, or the host can free an offline seat. A run carries the occupied lobby
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
- `bossrush/tests/test_coop.py` — seats bound to their proof, one run for the pair, the
  relay, the co-op board.
- `screens.mjs` → `bossRushCoop` — two browser contexts through three bosses by invite link.
