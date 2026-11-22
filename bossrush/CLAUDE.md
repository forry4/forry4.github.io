# Boss Rush — Claude Context

A three-boss speedrun on Halcyon Rift's greybox fight. The fight is `sim.js`, a pure,
deterministic simulation that runs in the browser; the server (`api.py`) deals the arenas,
owns the clock and keeps the boards. Solo runs start with `POST /bossrush/runs`; co-op runs
are opened by the co-op room socket (`coop.py`).

| File | What it owns |
|---|---|
| `sim.js` | the fight: one tick of 1/60 s, `step(state, input)`, every boss |
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
- **LOCKSTEP, not a server sim.** Both browsers run the same fight; each sends only its
  controls, `delay` ticks ahead (`coop.py input_delay`, from both round trips), and a tick
  is stepped only once both seats' rows are in. The fight waits rather than guesses. Every
  `FP_EVERY` ticks each browser sends a hash of `fingerprint(st)`; a mismatch ends the run
  "out of step". A reconnect cannot rejoin a fight (there is no catch-up), so a dropped or
  reloaded seat ends it for both and they start again from the room.
- **THEREFORE `sim.js` MUST BE BIT-IDENTICAL IN EVERY BROWSER.** No `Math.sin`, `cos`,
  `atan2`, `hypot`, `exp`, `pow` — engines differ in the last bit — use `dsin`/`dcos`,
  `rotate` and `Math.sqrt`. Solo got away with a few (a replay re-runs in the browser that
  recorded it); co-op is two browsers, possibly two engines. Both seats must also run the
  same BUILD: `coop.py` refuses to start a run for two different `build` ids.
- **The host reports, like a solo player.** The host posts each room's entry and clear,
  then sends `stage` and the server moves both fights on (a page moves on only once its own
  fight is at the portal too). Both post the LAST clear, so both learn the time. Co-op runs
  are `mode='coop'` rows with a second seat (`player_name2`/`character2`/`player_id2`), on a
  board of their own; the co-op board's five best keep films whichever characters played.
- There is no pause in co-op: Esc opens the menu over a fight that keeps going. Either
  player may start the next run (Play again, hold R) once the host has started the first.

## Gates

- `webapp/test/unit/bossRushCoop.test.mjs` — two heroes, 2x HP, targeted attacks on both
  and only the living, seal on both, down-not-dead, determinism.
- `webapp/test/unit/bossRushLockstep.test.mjs` — the buffer, and two lockstepped fights
  over a jittery link staying identical.
- `bossrush/tests/test_coop.py` — seats bound to their proof, one run for the pair, the
  relay, the co-op board.
- `screens.mjs` → `bossRushCoop` — two browser contexts through three bosses by invite link.
