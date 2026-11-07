# IMDb Filter — Claude Context

A **frontend-only** sibling of BGG, Steam and Anime Filter: every film, TV film, series and
mini-series on IMDb with 10,000+ votes, ranked by IMDb's own Top 250 weighted rating and
filtered client-side by kind, genre (required or excluded), year, runtime, rating and votes,
with one search over titles, directors and cast. No backend, no auth — one static JSON.

| File | What it is |
|---|---|
| `ImdbFilter.jsx` | the whole page; props `{ onExit }` |
| `derive.js` | the page's logic (rows, weighted rating, filters, cell formats), unit-tested by `webapp/test/unit/imdbfilter.test.mjs` |
| `ImdbFilter.css` | `?inline`-imported, `.imf`-prefixed (started as a copy of Anime Filter's) |
| `tools/harvest.py` | **the harvester** — streams IMDb's six dataset files → `results_all.json` |
| `tools/make_data.py` | `results_all.json` → `webapp/public/data/imdb-filter.json` — floor, interning, the guard |
| `tests/` | both tools on hand-written `.tsv.gz` files |

## The data is GENERATED — harvested on a runner, not here

**The source is IMDb's non-commercial datasets** (`datasets.imdbws.com`, documented at
developer.imdb.com/non-commercial-datasets) — static gzipped TSVs refreshed daily, so there
is no API, no key, no rate limit and nothing to scrape. Their terms are personal and
non-commercial use **with an attribution line, which the page's Source note carries**
("Information courtesy of IMDb … Used with permission.") — keep it.

**The dev container cannot reach `datasets.imdbws.com`** (proxy 403, like every rating site),
so `.github/workflows/imdb-harvest.yml` runs on a runner: monthly on the 20th, and on "Run
workflow" (`probe_only` prints each file's status, size and date). The raw harvest is
force-pushed to the `imdb-harvest` branch; with `publish` on (always on a schedule)
`make_data.py` rebuilds the payload, commits it to the run's branch and, on main, dispatches
the Pages deploy. To re-tune without a runner:

```bash
git fetch origin imdb-harvest
git show origin/imdb-harvest:results_all.json.gz | gunzip > imdbfilter/tools/results_all.json
python imdbfilter/tools/make_data.py
```

**Every file is STREAMED and filtered, never saved** — `title.principals` alone is tens of
millions of rows. `keyed()` tests the row's first field against the kept set BEFORE splitting
the line, which is most of the speed. The harvest keeps titles over `HARVEST_FLOOR` (5,000),
below the listing `FLOOR` (10,000), so the floor can be moved off one harvest.

**Guards, because the failure mode is a 200 OK with less in it:** each file's header is
checked against `HEADERS` before a row is read (a reordered column would otherwise be read as
the wrong field in silence); five canaries (Shawshank, The Godfather, Breaking Bad, Game of
Thrones, Band of Brothers) and `MIN_TITLES` must be present; under 2% of referenced people
may lack a name. `make_data.py` refuses a payload whose titles, cast-carrying rows, directed
films or episode-counted series fall below 90% of the current file's (`--force`).

## What a row carries

- **Kinds**: `movie` → `f`, `tvMovie` → `t`, `tvSeries` → `s`, `tvMiniSeries` → `m`. Shorts,
  episodes, specials, video games and `isAdult` titles never enter.
- **Directors only for films.** A series' `title.crew` lists every episode's directors, which
  is noise; a series shows its seasons (distinct numbered seasons in `title.episode`), its
  episode count (every episode row, numbered or not) and one episode's runtime instead.
- **Cast** is the first four `actor`/`actress`/`self` rows of `title.principals` by ordering.
- **Names are interned** in the header's `names` and referenced by index; ids ship as
  integers (`tt0111161` → `111161`) and `ttid()` pads them back to seven digits.

## The weighted rating

Not stored — `derive.js` computes `(v·R + m·C) / (v + m)` from the header's `bayes`
(`m` = 25,000, IMDb's long-standing Top 250 value; `C` = the mean rating of the listed
titles). It is the default sort; `Rating` sorts by IMDb's raw average. Same reasoning as
BGG's derived F average: one formula, in one place.

## Payload

Header: `collected`, `floor`, `count`, `bayes {m, c}`, `kinds` (count per code), `genres`
(roster, most common first), `names`, `titles`. A title: `{i, n (primary title), o (original
title, only when it differs), k, y, ye (series end year), rt (minutes), r, v, g [genre idx],
d [name idx], c [name idx], se, ep}` — absent fields are left out, not zeroed.

## Wiring

The Anime Filter set (`animefilter/CLAUDE.md`): `MODES`, the Extras tile (`onImdbFilter`),
`Spender.jsx`'s lazy chunk / screen branch / both screen maps, `screens.mjs` `SCREENS`, both
deploy path filters — plus the offline hub's Read row and reading pack, `offlineRead`'s row
list and `formControlZoom`'s walk in `screens.mjs`, `affected.mjs`, `pytest.ini`.
