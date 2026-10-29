# LoL Stats — Claude Context

A **frontend-only** page in the home menu's Extras (`/lolstats`), with two tabs. No
backend, no auth: it fetches static JSON and computes everything in the browser.

- **Worlds seeds** (`/lolstats`) — every regional seed's game and series record at
  Worlds 2020–2025, a seed-vs-region matrix and a region-vs-region matrix.
- **Champions** (`/lolstats/champions`, `#<Champion>` opens one) — every champion's
  pick, ban, presence and win rate by year and region, and for one champion its best
  and worst partners ("with": same team) and matchups ("into": ANY enemy champion,
  not just the lane opponent — the owner's choice).

| File | What it is |
|---|---|
| `LolStats.jsx` | the page; props are just `{ onExit }` |
| `LolStats.css` | `?inline`-imported stylesheet, `.lol`-prefixed, on the site's tokens |
| `derive.js` | **all the logic, pure so `node --test` reaches it** — seed tallies, the champion table/line/partners, search |
| `tools/harvest.py` | Oracle's Elixir yearly CSVs → `tools/cache/oe/<year>.csv` (gitignored, ~80–110MB each) |
| `tools/make_data.py` | those CSVs → `webapp/public/data/lol-champs-<year>.json` + `lol-champs-index.json` |
| `tools/worlds.py` | Liquipedia's Worlds brackets → `webapp/public/data/lol-worlds.json`; holds the hand-written SEEDS table |

## Two sources, and why

**Champions = Oracle's Elixir** (one CSV per year in a public Google Drive folder;
`harvest.py` resolves file ids from the folder listing because they change on
re-upload). **Seeds = Liquipedia**, because Oracle's Elixir has no Play-In/main-event
marker on Worlds games. Leaguepedia, the obvious third source, answers scripts with a
rate-limit error (cargo API) and a Cloudflare challenge (pages) — tried 2026-10-20 and
again 2026-10-28.

Where they overlap they are held to each other:
`webapp/test/unit/lolstats.test.mjs` asserts each year's Oracle's Elixir Worlds game
count equals Liquipedia's bracket total (114/121/127/110/106/84 for 2020–2025).

## Oracle's Elixir files the Worlds QUALIFIERS under Worlds

Its `WLDs` league includes the LCK and LPL Regional Finals (weeks before Worlds) and
2023's BDS-vs-Golden Guardians Qualifying Series — 26–28 extra "Worlds" games a year
in 2022–2024, found only because the counts disagreed with Liquipedia. `make_data.py`
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

- **The current year:** "Run workflow" on `lol-stats-refresh.yml` (re-downloads, rebuilds,
  commits, dispatches the Pages deploy). Or locally:
  `python -I lolstats/tools/harvest.py 2026 && python -I lolstats/tools/make_data.py 2026`.
- **A finished Worlds (seeds tab):** add the year to `SEEDS` and `PAGES` in `worlds.py`
  and to `SEED_YEARS` in `derive.js`, then `python -I lolstats/tools/worlds.py fetch`
  (~9 min — Liquipedia's parse API allows one request per 30s) and `... build`. The build
  fails on any team without a seed or any seeded team without a match. From 2022 on the
  match pages carry `{{ApiMap}}` instead of scores, so the tool reads RENDERED pages.

## Tests

`webapp/test/unit/lolstats.test.mjs` (the logic on the real payloads: cross-source
counts, each year's champion, partner symmetry, tables that add up) and the `lolStats`
block in `webapp/test/screens.mjs` (both tabs at 1280 and 390px, numbers checked against
`derive.js`, search → hash → Back, a deep link with an apostrophe). The search box and
the list filter are in `formControlZoom`; the Read row in `offlineRead`.
