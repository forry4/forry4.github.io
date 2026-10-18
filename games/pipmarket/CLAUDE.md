# Pip Market — implementation notes

An original 2–4 player dice auction, mounted at `/pipmarket`. Buy vertical pairs from a
sliding market, build them into a board that may span at most 6×6, then score straight
lines whose length is at least their face value. Three rounds; final score is points plus
money. The design (and the numbers behind it) came out of a Monte-Carlo simulation run
before the game was built — see "The bot" below.

| File | Role |
|---|---|
| `engine.py` | the rules authority: deal, moves, scoring, round flow, `player_view` |
| `bot.py` | the one opponent tier (`normal`) |
| `main.py` | rooms / WS / persistence / bot scheduler (Black Castle's shape, 2–4 seats) |
| `persist.py` | the at-rest boundary (a marker only — nothing worth packing yet) |
| `PipMarket.jsx` / `PipMarket.css` | lobby, create modal, waiting room, the table |
| `rules.jsx` | the How-to-play words |

## Rules decisions the engine pins

- **Market**: one set per player plus one, five vertical pairs each (30 / 40 / 50 dice).
  A column's price is its INDEX + 1, so buying one slides everything to its right one step
  cheaper. Later rounds deal the rerolled dice round-robin as pairs; an odd die sits alone.
- **Money**: last seat starts on 12, each earlier seat one less. Cap 18; taking money is
  refused at 18 (you must buy). A line pays +1, +5 at 15+, and SETS money to 18 at 30+.
- **Placement**: a pair stays together, may be rotated, must touch the board after the
  first, and the dice may never span more than 6 rows or 6 columns. There is no fixed grid:
  boards are stored NORMALISED (min row = min col = 0) and a move's cells are given in that
  frame, negative coordinates allowed. A pair with no legal placement cannot be bought.
- **Turn skipping**: a player with no legal action (18 money and nothing placeable) is
  skipped; if nobody can act, the leftover market dice go to the cup and scoring starts.
- **Scoring**: a straight unbroken run of one face, length ≥ face, any sub-run; the board
  must stay connected after removal. Players alternate one line at a time starting with the
  LAST BUYER; passing is permanent for the round; a player with nothing to score is passed
  automatically. 1s are offered one at a time (a run of 1s scored together is dominated).
- **Round end**: scored dice go to `cup`, are rerolled and dealt back; the last buyer opens
  the next round. A round where nobody scored ends the game. Ties are shared wins.

## Things that are load-bearing

- **Every die has a stable `id`** that survives market → board → cup → market. The client's
  flight animation keys on it, so never re-mint ids on a reroll; only the face changes.
- **No RNG state is persisted.** The deal and each round's reroll draw from
  `Random(f"{seed}:deal")` / `Random(f"{seed}:roll:{round}")`. `seed` is the only hidden
  field and `player_view` drops it — knowing it would reveal every future roll.
- **`player_view` computes the options for whoever is to act** (`options.columns` /
  `options.lines`), so the client never re-derives connectivity. The client DOES mirror the
  placement geometry (`placementsFor`) to light target cells; the server re-validates.
- **The bot scheduler sleeps `BOT_THINK` (0.85s) before each move** so every flight can be
  watched. Tests patch it to 0 and patch `asyncio.create_task` so they drive the scheduler
  explicitly.

## The bot (`bot.py`)

The heuristic from the design simulation: a board's value per straight line is the points +
money of runs already long enough, plus discounted POTENTIAL for short runs that still have
room (within the 6-span) to reach their face length, scaled by `(len/face)^2`. Buying is
"value gained minus price"; taking money is worth 2. Potential shrinks with the market in
round 3. Scoring is an exhaustive search over removal orders (points + money) and the bot
plays the first line, re-planning each turn. Ties draw from `core.rooms.bot_seed`.

Simulation results it was tuned against (2,000 games per arm, floating 6×6 span):
first player wins 50.0% vs 47.5% at 11/12 starting money (49.2 vs 49.0 at 10/12);
a "hold short lines for 15+" variant beat it 51.5–46.2, so holding is viable but not
dominant; 15+ lines appear in ~62% of games and 30+ in ~20%; rounds 2 and 3 average only
11 and 6 market dice — the known open design question.

## Frontend

- **Dice fly.** `useDiceFlight` snapshots every `[data-die]` rect in the RENDER body when
  `event_seq` changes (the last moment the old DOM exists), and after commit `flyDice` puts a
  clone in the fixed `.pm-fx` layer for each die that moved and animates it from the old rect
  to the new one with the Web Animations API. The real die is hidden with `opacity`, never
  `visibility` — a pip's own `visibility:visible` shows through a hidden parent. A die whose
  face changed (a reroll) spins and swaps its face mid-flight. Reduced motion skips it all.
- **Only a new `event_seq` animates**; reconnects and duplicate broadcasts repaint in place.
  Popups (+points, ±money) and banners (Market closed, Round N) are read off the log entries
  newer than the last seq seen.
- **Boards draw in a fixed 8×8 frame** (6 cells of dice + 2 of reach); the visible window is
  computed from the dice, so a growing board recentres and the flight layer animates it.
- **Below 1180px the action panel is a fixed bottom bar** — in the stacked layout it would
  otherwise sit under every board.
- The shared kit owns the lobby, create modal, waiting room, rules modal and menu; this
  sheet starts at `.pm-*`. `pipMarketPlay` in `webapp/test/screens.mjs` is the render gate.
