# LoL Stats — Claude Context

A **frontend-only** page in the home menu's Extras (`/lolstats`), with two tabs. No
backend, no auth: it fetches static JSON and computes everything in the browser.

- **Worlds seeds** (`/lolstats`) — every regional seed's game and series record at
  Worlds 2020–2026, a seed-vs-region matrix and a region-vs-region matrix.
- **Champions** (`/lolstats/champions`, `#<Champion>` opens one) — every champion's
  pick, ban, presence and win rate by year and region (with an "At least N games"
  minimum, default Any, which keeps the ban-only champions), and for one champion its best
  and worst partners ("with": same team) and matchups ("into": ANY enemy champion,
  not just the lane opponent — the owner's choice).
  ONE table (`PairTable`) holds both: every champion that shared a game with it,
  same-team and enemy-team records side by side. Best/Worst with/into are its Sort
  presets (it opens on Best with, top 10 of Show 10/20/All); the "At least" minimum
  applies to the SIDE being sorted (`derive.sortPairs`), so under an enemy-team sort a
  champion only ever met as a teammate drops out even at Any; a search shows its
  champion whatever the sample. (It was four lists plus a table until 2026-10-31 —
  the same numbers twice.)

| File | What it is |
|---|---|
| `LolStats.jsx` | the page; props are just `{ onExit }` |
| `LolStats.css` | `?inline`-imported stylesheet, `.lol`-prefixed, on the site's tokens |
| `derive.js` | **all the logic, pure so `node --test` reaches it** — seed tallies, the champion table/line/partners, search |
| `tools/harvest.py` | Oracle's Elixir yearly CSVs → `tools/cache/oe/<year>.csv` (gitignored, ~80–110MB each) |
| `tools/make_data.py` | those CSVs → `webapp/public/data/lol-champs-<year>.json` + `lol-champs-index.json` |
| `tools/worlds.py` | Leaguepedia's Worlds series (Cargo `MatchSchedule`) → `webapp/public/data/lol-worlds.json`; holds the hand-written SEEDS table |
| `tools/polite.py` | **the one way both harvesters ask a site for anything** — spacing, backoff within a budget, a bare 429 treated as a block, exit 75 to try another day |

## Two sources, and why

**Champions = Oracle's Elixir** (one CSV per year in a public Google Drive folder;
`harvest.py` resolves file ids from the folder listing because they change on
re-upload). **Seeds = Leaguepedia** (since 2026-11-21), because Oracle's Elixir has no
Play-In/main-event marker on Worlds games. Its Cargo table `MatchSchedule` gives each series'
event (`<year> Season World Championship/Play-In` or `/Main Event`), round (`Tab`), scores,
winner and time, and ONE query returns a year. Leaguepedia was passed over in October as
"answers scripts with a rate-limit error"; measured 2026-11-21, that is its anonymous limit
at a few seconds apart (it refused the 5th and 6th of six queries 3s apart) while seven
queries 10s apart all passed. Liquipedia, the source until then, read three RENDERED pages
a year and IP-blocked shared runner IPs (below), so the switch was held to its payload:
all 453 series of 2020–2025 came back identical (stage, teams, seeds, both scores), the
only difference being Worlds 2026's final, which Liquipedia's last good run had not seen.
The payload names its source (`source`, `sourceUrl`) and the Seeds tab's credit line reads
them, so a data-only refresh can never credit the wrong site.

Where they overlap they are held to each other:
`webapp/test/unit/lolstats.test.mjs` asserts each year's Oracle's Elixir Worlds game
count equals the bracket total (114/121/127/110/106/84 for 2020–2025).

## Oracle's Elixir files the Worlds QUALIFIERS under Worlds

Its `WLDs` league includes the LCK and LPL Regional Finals (weeks before Worlds) and
2023's BDS-vs-Golden Guardians Qualifying Series — 26–28 extra "Worlds" games a year
in 2022–2024, found only because the counts disagreed with the bracket source. `make_data.py`
cuts at each year's first Play-In day (`WORLDS_START`): an earlier `WLDs` game between
two teams of one major league goes back to that league as postseason, any other is
dropped. **A new year with Worlds games and no `WORLDS_START` entry fails the build**
— add the date when 2027's Play-In starts.

## Which games count (the owner's call, 2026-10-28)

LCK, LPL, LEC, LCS regular season + playoffs, and Riot's internationals — Worlds (Play-In
included), MSI, First Stand, 2020's Mid-Season Cup — every game, minor-region teams
included. **2025: LTA North only** (the LTA merged NA and Brazil), plus cross-conference
`LTA` games where both teams were LTA North. **Not counted:** the Esports World Cup
(third-party; 2026's is ~460 games with a large lower-tier field), the smaller
invitationals (ASI, DCGI, AC, CCWS), showmatches. The phase filter (Regular season /
Playoffs) applies to league games only; internationals follow the Intl region chip.

The seeds tab defaults to **Main event, Majors only, G2 separate** — the owner asked for
each in turn. "Majors only" drops every series with a non-major team, and also 2025's
LTA #2 Vivo Keyd Stars (Brazilian; `NON_MAJOR_TEAMS` in `worlds.py`).

## Payload shape

Each `lol-champs-<year>.json` is the year's games in a positional layout (documented at
the top of `make_data.py`): league/patch/team/champion are indexes into the file's own
lists, so **indexes differ between years** — `decodeYear` turns them back into names, and
everything downstream keys on names. ~470KB per year (~155KB gzipped); the page loads the
shown year, and every year once a champion is open (the By year table).

Gold diff at 15 is missing for ~40% of 2024 games (LPL data is partial); it is averaged
over the games that have it and the tile says how many.

## Refreshing

- **Champion stats:** `lol-stats-refresh.yml` runs on the 15th, January to November
  (the current year; January's also rebuilds the year before, and skips a new year
  Oracle's Elixir has not posted yet). "Run workflow" rebuilds any years named. Locally:
  `python -I lolstats/tools/harvest.py 2026 && python -I lolstats/tools/make_data.py 2026`.
  **It retries every day from the 16th to the 28th, and Google Drive's download quota is
  why.** Drive caps how often one file is downloaded per day and answers past it with a 200
  HTML page titled "Quota exceeded" (2026-11-15, the morning after the Worlds final, for
  every URL form and User-Agent). `harvest.py` exits **75** for that page and no other; the
  workflow stays green on 75 while a later retry is scheduled, and only the 28th's run (or
  one by hand) goes red. Three tries (15th/17th/20th) all met the quota in November 2026, so
  the retries are daily and fire at 08:07 UTC, just after midnight Pacific.
  `tools/refresh_due.py` skips a retry once any year's `built` is on or after the 15th, so a
  good month still costs one download. `lolstats/tests/test_refresh.py` pins both halves and
  the cron.
- **Worlds seeds:** `lol-worlds.yml` runs DAILY in October and November, makes ONE
  Leaguepedia query (the current year; `worlds.py fetch <year>`, settled years from the
  cache), and `worlds.py due <year>` makes a run a no-op once that year is in `complete`
  with its matches. A series counts once it names a `Winner`, so a live Bo5 at 1-1 or an
  undrawn "TBD" slot waits for a later run; a year with matches still to play may have
  seeds that have not played yet, and `lol-worlds.json`'s `complete` lists the years that
  are done. Events and rounds are a CLOSED list (`EVENTS`, `NOT_WORLDS`, `TAB`): a new
  format fails the build and names itself rather than being filed under a guessed stage.
- **How both harvesters ask: `tools/polite.py`.** A named User-Agent and gzip; one request
  at a time with a floor between them (Leaguepedia 10s, Drive 2s); MediaWiki's `maxlag=5`;
  exponential backoff with jitter on a 5xx, a dropped connection or the API's own
  `ratelimited`/`maxlag`, honoring Retry-After, inside a fixed time budget per run. **A bare
  HTTP 429 is a BLOCK and is never retried** — Liquipedia's "Rate Limited" page lifts by
  CAPTCHA or time and names "a shared IP address that was rate limited by someone else",
  which is what a GitHub runner has (2026-11-16 met it on the first request; a home
  connection drew it 16 pages into a full fetch on 2026-11-21, and four tries over six
  minutes all met it). A block or a spent budget is `TryLater` → exit **75** plus a public
  `::notice::` naming why; the workflows stay green on 75 while a later day remains (a new
  runner, a new IP) and go red only on the last scheduled day. `lolstats/tests/test_polite.py`
  pins the client, `test_worlds_fetch.py` the rows, the gate and the exit codes.
- **ONE HAND STEP A YEAR, once the field is known (late September):** add the year to
  `SEEDS` in `worlds.py` and to `SEED_YEARS` in `derive.js`. Until then the daily job fails
  and names what to write. Seeds come from the year's Worlds Qualification page (it lists
  qualifying paths, not seeds); the build reports every team name it cannot resolve, and
  Leaguepedia's own spellings (`Rogue (European Team)`, `Movistar R7`, `LØS`) go in as
  aliases after the display name, so the payload's names never change with the source.
- **The two sources disagree while the newest year is played** (Leaguepedia daily,
  Oracle's Elixir monthly), so `lolstats.test.mjs` holds the newest year to `oe <= lp`
  once the bracket is whole and to nothing before, and every older year to equality.

## Tests

`webapp/test/unit/lolstats.test.mjs` (the logic on the real payloads: cross-source
counts, each year's champion, partner symmetry, tables that add up) and the `lolStats`
block in `webapp/test/screens.mjs` (both tabs at 1280 and 390px, numbers checked against
`derive.js`, search → hash → Back, a deep link with an apostrophe). The search box and
the list filter are in `formControlZoom`; the Read row in `offlineRead`.
