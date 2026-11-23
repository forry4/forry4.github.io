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
| `lockstep.js` | co-op: the two seats' controls, tick by tick |
| `BossRush.jsx` | the menu, the boards, the solo run page |
| `Coop.jsx` | the co-op room (shared `WaitingRoom`) and the co-op run page |
| `api.py` / `coop.py` | runs, clock, boards, films / the co-op rooms and the input relay |

## CO-OP (owner's ask, 2026-11-22)

Two players, two browsers, one fight. **The bosses have `COOP_BOSS_HP` (2x) health, and
every attack aimed at "the player" is aimed at each living hero** (`targets(st)`,
`aimsAt(st, e)` in `sim.js`). One hero down does not end the fight; both do. A fallen hero
comes back for the next boss on the recovery margin, like any carried HP.

- **The sim holds two heroes by SWAPPING them onto the state.** The rules read the hero as
  `st.p` / `st.stats` / a few more keys (`HERO_KEYS`); in co-op each hero's own copies live
  in `st.heroes[i]` and `useHero(st, i)` puts that hero on `st` while it acts, moves, fires
  or is hit. Between ticks hero 0 is on `st` and every record is current, so `heroView(st,
  i)` is all the renderer needs. Solo (`partner` absent from `createSim`) runs the exact
  one-hero code path — the refactor was checked against the old sim's fingerprints over
  every boss and character, both phases and the kill.
- **What is NOT doubled, on purpose.** An enemy walks toward, and its facing follows, the
  NEAREST living hero (`nearestHero`), so the Warden's gavel and chains still come from his
  front (the other player can work his back). The Schism's bank sweep takes ONE bank, each
  living hero's in turn: sweeping both banks would leave nowhere to stand.
- **CONFIRMED TICKS AND PREDICTION.** Both browsers run the same fight and send each
  input on the tick it was sampled. The renderer steps ahead with the local input
  and the partner's last held controls, up to the connection's prediction window.
  Late inputs can rebuild that tail from the last confirmed fight. Only ticks with
  both rows drive the clock, the recording and the outcome. Missing rows can be requested again. Every
  `FP_EVERY` ticks each browser sends a hash of `fingerprint(st)`; a mismatch ends the run
  "out of step". Each stage starts after both browsers have installed their input listeners.
  They flush their last input rows and agree on the terminal tick and fingerprint before
  moving on. A dropped or reloaded seat ends the fight for both. Players can start again
  from the room, or the host can free an offline partner's seat.
- **THEREFORE `sim.js` MUST BE BIT-IDENTICAL IN EVERY BROWSER.** No `Math.sin`, `cos`,
  `atan2`, `hypot`, `exp`, `pow` — engines differ in the last bit — use `dsin`/`dcos`,
  `rotate` and `Math.sqrt`. Solo got away with a few (a replay re-runs in the browser that
  recorded it); co-op is two browsers, possibly two engines. Both seats must also run the
  same BUILD: `coop.py` refuses to start a run for two different `build` ids.
- **The host reports, like a solo player.** The host waits for each room's entry request
  before posting its clear. The server relays the next stage or the saved time to both
  players. Co-op runs
  are `mode='coop'` rows with a second seat (`player_name2`/`character2`/`player_id2`), on a
  board of their own; the co-op board's five best keep films whichever characters played.
- There is no pause in co-op: Esc opens the menu over a fight that keeps going. Either
  player may start the next run (Play again, hold R) once the host has started the first.

## Gates

The Crypt Trio is public and solo only. Older clients do not list it.
The Orrery rotates its corner emitters and orbits the center in phase two.
The Glassweaver uses crossing walls of shots with marked gaps. Its second curtain sweeps diagonally in phase two.
The Null Cantor fires echoes through past player positions while aiming fresh fans.
Its phase-two echoes fire in reverse order.

- `webapp/test/unit/bossRushCoop.test.mjs` — two heroes, 2x HP, targeted attacks on both
  and only the living, seal on both, down-not-dead, determinism.
- `webapp/test/unit/bossRushLockstep.test.mjs` — the buffer, and two lockstepped fights
  over a jittery link staying identical.
- `bossrush/tests/test_coop.py` — seats bound to their proof, one run for the pair, the
  relay, the co-op board.
- `screens.mjs` → `bossRushCoop` — two browser contexts through three bosses by invite link.
