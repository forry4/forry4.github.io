# Steam Filter — Claude Context

BGG Filter's sibling over Steam: a **frontend-only** filterable table of every game on the
Steam store whose **English** reviews are **90% or more positive**, with at least 50 English
reviews. No backend — it fetches one static JSON and does everything client-side.

| File | What it is |
|---|---|
| `SteamFilter.jsx` | the whole feature; props are just `{ onExit }` |
| `SteamFilter.css` | `?inline`-imported stylesheet, `.stf`-prefixed (started as a copy of BGG's) |
| `tools/scan_steam.py` | **the harvester** — store search, then English review totals per candidate |
| `tools/make_data.py` | `results_all.json` → `webapp/public/data/steam-filter.json` (the shipped payload) |
| `tests/test_scan_steam.py` | the parse + admission rule, off canned store markup |

The slider pointer handling is shared with BGG Filter via `shared/rangePointer.js`.

## The data is GENERATED — and harvested by a workflow

`.github/workflows/steam-harvest.yml` (manual "Run workflow") runs both tools on a GitHub
runner, commits the payload to `main` and dispatches `deploy-pages.yml` (a `GITHUB_TOKEN`
push triggers no workflow on its own). Locally:
`python steamfilter/tools/scan_steam.py && python steamfilter/tools/make_data.py`.
Until the first harvest the committed payload has `"games": []` and the page says so.

Payload rows are `{n, id, y, p, t}` — name, app id, release year (or null), positive and
total English reviews. Nothing derived is stored.

## Harvest shape

1. `store.steampowered.com/search/results/?infinite=1&json=1&category1=998` — every game,
   100 rows a page. Each row's review tooltip ("94% of the 1,234 user reviews…") is only a
   **prefilter**: it may blend languages, so it is applied at **80%**, well under the real
   rule, so a game whose English share beats its blended one is still asked. Bundles and
   packages (no single `data-ds-appid`) are counted but skipped. **The harvest fails if the
   rows returned fall >2% short of `total_count`** — BGG's lesson that a short page loses
   its tail in silence.
2. `store.steampowered.com/appreviews/<id>?json=1&language=english&purchase_type=all&num_per_page=0`
   — the exact English `total_positive` / `total_reviews`. `purchase_type=all` counts key
   activations too; the default off-topic (review-bomb) filter stays on.

**The harvest is resumable.** Every search page and review answer is cached under
`tools/cache/` as it arrives and reused for `--fresh-hours` (48). The workflow restores that
cache, gives the Harvest STEP its own timeout (so the job outlives it) and saves the cache with
`if: always()` — a run that times out or fails starts the next round itself (up to 3), which reuses every
answer already collected. Measured 2026-10-15: search ~68 min for 132k games, then ~60
review lookups a minute (Steam throttles) for ~22k candidates — about two rounds in all.

Every response is validated before use (`validate_search` / `validate_reviews`); 429/5xx back
off 30s+ per try. The admission rule is `keep()` — one function, pinned by the tests.

## The three rating columns

Mirror BGG Filter's Geek / F / Average trio, derived in `derive()`:
- **Positive** (`a`) — raw English positive share.
- **Rating** (`r`) — SteamDB's formula, `a − (a − ½)·2^−log10(n+1)`: the share pulled toward
  50% by an amount that shrinks with the review count (100% of 60 → ~85.5; 97% of 100k → ~95.5).
  The count-aware analogue of the Geek rating.
- **F score** (`f`) — their midpoint, exactly as BGG's F average. Default sort.

## Wiring

Same five places as BGG Filter (see `bggfilter/CLAUDE.md`), plus the offline hub: the
`steamfilter` Read row and the reading pack in `Spender.jsx`, and `offlineRead`'s expected row
list in `screens.mjs`.
