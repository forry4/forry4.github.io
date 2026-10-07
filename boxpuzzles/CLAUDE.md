# Box Puzzles — Claude Context

Solo puzzle boxes in the style of Blue Prince's Mora Jai boxes: a 3x3 grid of coloured
tiles and four corner buttons. A box opens when all four corner tiles show their buttons'
colours and each button has been pressed. An Extras tile on the home menu (not a game
card: it has no lobby, rooms or bot), at `/boxpuzzles`, `/boxpuzzles/<n>` and
`/boxpuzzles/daily` (the daily box — see its own section; its rules differ).

| File | What it is |
|---|---|
| `engine.py` / `engine.js` | the rules, twice — server replay / browser play |
| `puzzles.json` | the 71 boxes, **GENERATED**, shipped in the lazy chunk |
| `minimums.json` | id -> fewest presses, **GENERATED, server-only** |
| `api.py` | the leaderboard: `setup_box_puzzles` (Books/Notes injected-deps pattern) + the daily routes |
| `daily.py` | the daily box: Pacific day clock, generator, `box_daily` + `box_daily_attempts` + `box_daily_best`, attempt and retry rules |
| `BoxPuzzles.jsx` / `.css` | the page (picker + box + leaderboard) |
| `rules.jsx` | the Rules panel's words (owner-approved; see "no prose" below) |
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
  the TILE PRESSES alone. (The page now lights the buttons itself — see Auto-light.)
- **The first fuzz of these rules was vacuous** — a weak LCG kept five colours out of the
  centre, so it read all-green while the blue quirks were wrong. The generator now BUILDS
  coverage for every (pressed, centre) pair, and a test fails if a regenerated fixture
  loses one.

## Auto-light and auto-open (owner's calls, 2026-10-07)

**A corner button is lit exactly while its corner matches** — nobody presses a button to
light it. It lights (with its climbing note) when a tile press makes its corner match and
goes dark when one breaks it. **When the fourth corner matches, the box opens by itself**
450ms later, through the same handler a tap uses, and tile presses are ignored from the
match on. The only thing a button press still does is **reset, on an unlit button**; a tap
on a lit one does nothing. Scores and the server's checks are untouched (tile presses only;
buttons were always free).
- **It lives in the JSX (`autoLit` / `pressTileAuto` / `pressButtonAuto` / `useAutoOpen`),
  not in `engine.js`**: engine.js's `pressTileInBox` / `pressButtonInBox` are held
  press-for-press to the reference simulator, where buttons are pressed by hand, so they
  are unchanged and the page derives `lit` from the tiles after each of them.
- Every play surface uses it: numbered boxes, the daily's first attempt and retries,
  yesterday-for-fun. `screens.mjs` checks the lit buttons against engine.js at every press
  of a real line, that a lit tap does nothing and an unlit one resets, that the box opens
  itself, and that a tile press in the opening beat is ignored. Its `play` helpers press
  tiles only and wait for the open box.

## The leaderboard

- **Score = tile presses since the last reset**, and the only reset is a corner button
  pressed while its corner does not match. Corner presses are free. There is no Undo or
  Reset button (owner's call — the wrong corner already resets).
- **The page carries no prose** (owner's call, 2026-10-05): no instructions, empty states,
  status lines or explanations. A box's count turns into its result when it opens.
  `screens.mjs` fails on any `<p>` in the page. **The one place words live is the Rules
  panel** (owner's call, 2026-10-06): the header's book button opens the shared
  `RulesModal` with `rules.jsx` — the goal, what each color does, daily mode, nothing
  more. Its wording was approved line by line; White and Red say "this tile's color" so
  they read true when Blue borrows them, and Blue is just "uses the center tile's
  ability". American spelling. **A box is SOLVED, never "opened"** (owner's call,
  2026-10-07: "nothing is being opened") — in the rules and anything else a player reads
  or hears; `screens.mjs` fails the rules panel on the word. (Code names like `opened`
  and the `.open` class are internal and stay.) The header's old solved counter (n / 71) is gone.
- **A box is never saved mid-solve** (owner's call): a reload, or leaving the box,
  starts it again from its first board. Only finished results are stored. (The DAILY
  box is the one exception, by design — below.)
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

## The daily box (owner's design, 2026-10-05)

One new box a day, **ONE attempt**, and **a reset does not clear the count** — it is a
race for the fewest presses in a single try. Everything about it is `daily.py` and the
four `/boxpuzzles/daily*` routes; the numbered boxes' rules above are untouched.

- **The day turns at midnight US Pacific, daylight saving included.** Computed by hand
  (`pacific_offset`), not `zoneinfo`: neither the Windows dev boxes nor the slim prod
  image ship a tz database. Tested at both 2026 transitions.
- **Generated by the SERVER with real randomness and stored in `box_daily`; never
  committed, never in the bundle.** The repo is PUBLIC (so is `minimums.json` — "server
  only" means out of the bundle, not secret from GitHub), so a committed list or a
  date-seeded generator would publish tomorrow's box and its minimum. Only today's box
  is handed out, without its minimum; a finished day's minimum and a shortest line are
  revealed (owner's call) on yesterday's view. **Yesterday is the one place blue marks
  OTHER players' rows** — every row that reached the minimum, and the minimum itself.
  That is intended (owner's call, 2026-10-05: "that one is already done"); everywhere
  else blue is drawn only on your own row.
- **The generator explores first, then picks the target** — random tiles alone fail
  (64% can't reach any one-colour target; most of the rest open in 3–6). It keeps a
  board only if its minimum is the day's drawn depth (uniform 8–15, owner's range),
  graying out ANY one colour changes that minimum (no decoration), and it has at most
  200 shortest lines (the real bank's 8–15 boxes have a median of 28), and **no trope**:
  one repeated motif (1–4 presses, 3+ times) may cover at most half of every shortest
  line — length is not difficulty (chandler.io's solution-space analysis: long boxes are
  mostly one trick repeated). A corner-greedy-player filter was measured and NOT added:
  it could not fire (see `daily.py`'s docstring for both measurements). Targets are one
  colour or a symmetric pair (diagonal / top-bottom / left-right; every mixed target in
  the real bank is diagonal). Measured: every depth 8–15 hits exactly in 0–20s locally.
- **Who generates:** a daemon filler keeps tomorrow and the day after ready, started by
  the first `/boxpuzzles/daily` request and waiting 10 min before its first pass (a fresh
  process — a deploy, the render gate — should not spend its first minutes on it). It
  cannot live in `core.monitor`'s hourly tick: core may not import a feature. A request
  that finds today missing generates it on the spot under an 8s budget (closest good
  depth after that). `INSERT OR IGNORE` + a process lock, so racers agree.
- **The attempt is a list of SEGMENTS (the presses between resets)** and only GROWS:
  a save must keep the stored earlier segments and extend the stored last one, and an
  opened box is final (a retried identical final post answers the same; anything else
  is 409). That one rule is both "progress is saved" and "no rewinding". The server
  replays the LAST segment from the first board to check an opening; the score is
  every press in every segment. Signed-in attempts live on the server (another browser
  resumes them); a guest's lives in localStorage and posts nowhere.
- **Ties go to whoever finished first** (owner's call). **Today's scores reach no one
  who has not opened today's box** (owner's call: no hints of any kind). The page keeps
  the leaderboard locked and never asks for it, and the SERVER refuses today's board
  (403) unless the caller has opened the box: a signed-in player's solved attempt is on
  record; a guest's is not, so the page sends the opening line (`?line=`) and the server
  replays it — anyone holding such a line has the answer already. Past days are public.
- **Then retries, on a second board** (owner's call, 2026-10-06: "a way to retry the
  daily after you've completed it so you can try for the optimal solve"). Once the one
  attempt has opened the box, **Play again** starts a retry under the NUMBERED boxes'
  rules — a reset clears its count, nothing is saved mid-solve — and its opening posts
  to `POST /boxpuzzles/daily/retry` (the presses since its last reset, replayed; 403
  until the attempt is open, so retries are never practice for the race). The two
  boards are tabs on the daily's leaderboard: **First Attempt** (`box_daily_attempts`, the
  race) and **Best Attempt** (`box_daily_best`, each player's fewest; a tie with yourself
  keeps the earlier time). The attempt seeds Best Attempt with its score, and
  `init_daily_db` backfills attempts opened before Best Attempt existed. The board payload
  keeps First Attempt at the top level and adds Best Attempt under `best`, so a cached page
  still reads it. Today's minimum stays secret on both: blue only on your own row, so
  a retry turning blue is how you learn you found the optimal line. A guest's retries
  post nowhere.
- **Yesterday's box can be PLAYED FOR FUN** (owner's call, 2026-10-06): Play on
  yesterday's view makes it playable under the numbered boxes' rules (a reset clears the
  count), entirely in the page — nothing is posted or saved, and no board changes. Its
  boards are closed and its minimum is public, so opening it in the minimum draws blue.
- An attempt still open at midnight is lost: the server refuses a save for a day that
  is over (409), and the page loads the new box.
- `screens.mjs` `boxDaily` plays today's real box (the harness solves it with engine.js),
  across a reset, a reload and a second browser, retries it for Best Attempt (guest and
  signed in), and drives yesterday's view against a
  STUBBED day (the gate's database has no yesterday).
- **Local `screens` reuse `games/spender/users.db`**, so after ~20 runs box 1's top 20 is
  all earlier gate accounts tied at the minimum, and `boxPuzzles`' "another viewer sees
  the row" fails locally. CI's database is fresh. Delete the local rows, don't loosen it.

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

Synthesised, not sampled (`sound.js`). **The kit is the owner's pick from an audition
page of six (2026-10-05): "Felt", with "Brass Latch"'s tile.** A two-stage switch click
per tile; a warm marimba note per lit corner, climbing C-D-E-G with each button lit; two
marimba notes falling G-C on a reset; a rolled C-major chord over a low C on opening.
The felt notes send into a short feedback echo ("the room"). The primitives were
ported from the audition page as heard, so do not re-tune them by ear in code. The AudioContext is made on the first sound —
always inside a click/key handler, which is what iOS requires. **The master bus is a
tanh soft clipper, NOT a DynamicsCompressor**: Chrome's compressor crushed the 70ms
clicks to ~1/4 of their level (measured by rendering each sound offline). Levels were
balanced by the same offline render: tile ~-27 dB RMS, corner/reset ~-25, the opening
~-21, peaks <= 0.66. The mute toggle (header) is localStorage `boxpuzzles.muted`; `screens.mjs`
counts synthesised voices (oscillators + noise sources) to prove a press sounds unmuted and stays silent muted.

**The iPhone audio session is a forced trade, decided by the owner (2026-10-05).**
Safari gives a page no session that both plays through the ring/silent switch AND
mixes with other audio. "playback" (tried first, after "I don't hear sound on mobile")
plays through the switch but PAUSES the player's audiobook or music — reported within
the hour. So `sound.js` sets `navigator.audioSession.type = "ambient"` (Safari 17+):
the sounds mix over other audio, and the silent switch mutes them, as it does for native
iPhone games. Do not go back to "playback". A one-sample silent buffer is also started
inside the gesture that creates the context (the classic iOS unlock). `screens.mjs`
stands in an `audioSession` object and asserts it is "ambient".

## Portrait only on a phone

An ordinary browser tab cannot lock orientation (the Screen Orientation lock needs an
installed or fullscreen app, and iOS Safari has none), so `usePortrait` in the JSX
counter-rotates the page on a phone held sideways (landscape + coarse pointer + height
<= 540px): the root goes `position:fixed`, is sized to the portrait box, rotated -90deg
for screen angle 90 (turned counter-clockwise) or +90deg for 270, and scrolls itself.
The real lock is also requested, for where it is allowed. Media queries still see the
LANDSCAPE width, so the phone tier's rules are repeated under `.bx-rot`. `screens.mjs`
checks the rotation, that all nine tiles are on screen, and that a tap lands.
