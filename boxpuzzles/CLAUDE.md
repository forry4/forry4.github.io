# Box Puzzles — Claude Context

Solo puzzle boxes in the style of Blue Prince's Mora Jai boxes: a 3x3 grid of coloured
tiles and four corner buttons. A box opens when all four corner tiles show their buttons'
colours and each button has been pressed. An Extras tile on the home menu (not a game
card: it has no lobby, rooms or bot), at `/boxpuzzles` and `/boxpuzzles/<n>`.

| File | What it is |
|---|---|
| `engine.py` / `engine.js` | the rules, twice — server replay / browser play |
| `puzzles.json` | the 71 boxes, **GENERATED**, shipped in the lazy chunk |
| `minimums.json` | id -> fewest presses, **GENERATED, server-only** |
| `api.py` | the leaderboard: `setup_box_puzzles` (Books/Notes injected-deps pattern) |
| `BoxPuzzles.jsx` / `.css` | the page (picker + box + leaderboard) |
| `sound.js` | the sounds, synthesised with Web Audio (no files) + the per-device mute |
| `tools/import_bank.py` | source JSON -> `puzzles.json` + `minimums.json` |
| `tools/gen_parity_fixtures.mjs` | the reference simulator's WASM -> `tests/fixtures/parity.json` |

## The rules are a PORT, held to the reference — not to a reading of it

The source is chandler.io's Mora Jai simulator (its puzzle JSON and its rules WASM, which
is embedded base64 in the page bundle and driven directly by the fixture generator).
Both engines are tested against the reference's own answers: `engine.py` by
`tests/test_engine.py`, `engine.js` by the `boxPuzzles` block in `webapp/test/screens.mjs`.
That block also posts a solve to the real backend, so a drift between the two engines
fails as a refused solve.

- **The blue quirks decide four boxes.** When Blue borrows White it toggles BLUE<->gray
  (whites untouched); when it borrows Red, black turns BLUE. Generally: in the White and
  Red rules, "white"/"red" means the PRESSED tile's colour. The simulator's prose only
  says "with some quirks"; this was measured.
- **Orange takes a unique plurality**, not a strict majority (2 of 4 with no tie counts).
- **A lit button goes dark as soon as its corner stops matching**, so "open" is exactly
  "all four corners match, then the buttons". The server therefore checks a solve from
  the TILE PRESSES alone.
- **The first fuzz of these rules was vacuous** — a weak LCG kept five colours out of the
  centre, so it read all-green while the blue quirks were wrong. The generator now BUILDS
  coverage for every (pressed, centre) pair, and a test fails if a regenerated fixture
  loses one.

## The leaderboard

- **Score = tile presses since the last reset**, and the only reset is a corner button
  pressed while its corner does not match. Corner presses are free. There is no Undo or
  Reset button (owner's call — the wrong corner already resets).
- **The page carries no prose** (owner's call, 2026-10-05): no instructions, empty states,
  status lines or explanations — not even of the blue. A box's count turns into its result
  when it opens. `screens.mjs` fails on any `<p>` in the page.
- **The leaderboard is always there and starts CLOSED** (owner's call): the scores are a
  spoiler — a low best tells you how short the line is. It is folded to its title on every
  box and opens itself when you open the box. Empty and open, it shows a dash.
- One row per player per box, their best; a tie with your own best keeps the earlier
  time, so ties on the board go to whoever got there first. Signed-in accounts post;
  anyone can read.
- **The minimum is the server's secret.** `minimums.json` never reaches the browser (a
  test reads every `.js`/`.jsx` here for it), and `optimal` is only ever set on the
  caller's OWN row — that row is drawn blue, for them alone. A reader can see the best
  score but not whether it is the minimum. The picker's order (easiest first) is the
  only thing the bank says about difficulty.
- Box ids are the board itself (`<tiles>-<targets>`), so re-sorting the bank renumbers
  boxes without orphaning a leaderboard row.

## Regenerating

```
python -m boxpuzzles.tools.import_bank <morajai.json from the simulator page>
node boxpuzzles/tools/gen_parity_fixtures.mjs <the simulator's morajai-bundle.min.*.js>
```
Only the source's `puzzles` list (the 71 boxes from the game) is imported; its
`puzzles_challenge` list is the simulator author's own designs and is left out. Names
are dropped: boxes are numbered by difficulty and not tied to the game.

## Wiring (places a change of route/name must touch)

`shared/router.js` `MODES` · `shared/HomeScreen.jsx` (Extras tile + icon) ·
`games/spender/Spender.jsx` (`lazyChunk`, the `screen === "boxpuzzles"` branch, both
mode maps) · `webapp/test/screens.mjs` (`SCREENS` + the `boxPuzzles` block in lane B) ·
`app.py` · `pytest.ini` · `core/tests/test_routes_off_event_loop.py` · the path filters in
`deploy-pages.yml`, `deploy-render.yml` (the `.py` files AND the two JSON files api.py
loads) and `.githooks/pre-push`.

## Sounds

Synthesised, not sampled (`sound.js`): a woody thock per tile, a latch click + bell per
lit corner (rising E-G-B-D with each button lit), a dull falling thunk on a reset, and
a latch + four-note chime on opening. The AudioContext is made on the first sound —
always inside a click/key handler, which is what iOS requires. **The master bus is a
tanh soft clipper, NOT a DynamicsCompressor**: Chrome's compressor crushed the 70ms
clicks to ~1/4 of their level (measured by rendering each sound offline). Levels were
balanced by the same offline render: every sound ~-25 dB RMS, the opening ~-22, peaks
<= 0.54. The mute toggle (header) is localStorage `boxpuzzles.muted`; `screens.mjs`
counts oscillators to prove a press sounds unmuted and stays silent muted.

## Portrait only on a phone

An ordinary browser tab cannot lock orientation (the Screen Orientation lock needs an
installed or fullscreen app, and iOS Safari has none), so `usePortrait` in the JSX
counter-rotates the page on a phone held sideways (landscape + coarse pointer + height
<= 540px): the root goes `position:fixed`, is sized to the portrait box, rotated -90deg
for screen angle 90 (turned counter-clockwise) or +90deg for 270, and scrolls itself.
The real lock is also requested, for where it is allowed. Media queries still see the
LANDSCAPE width, so the phone tier's rules are repeated under `.bx-rot`. `screens.mjs`
checks the rotation, that all nine tiles are on screen, and that a tap lands.
