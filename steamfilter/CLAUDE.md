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
| `tools/enrich.py` | categories (Steam store tags) + Nintendo Switch availability (eShop title match) |
| `tools/categories.json` | the category groups — label + the Steam tags each one ORs together |
| `tools/prices.py` | US Steam + eShop prices and running sales → `webapp/public/data/steam-prices.json` |
| `prices.js` | the page's price logic (sale window, sort keys), unit-tested by `webapp/test/unit/steamPrices.test.mjs` |
| `tests/test_scan_steam.py` | the parse + admission rule, off canned store markup |
| `tests/test_enrich.py` | title folding, tag unions, eShop paging + the truncation guards |
| `tests/test_prices.py` | both stores' price parsing, listing choice, batching + the thin-answer guards |

The slider pointer handling is shared with BGG Filter via `shared/rangePointer.js`.

## The data is GENERATED — and harvested by a workflow

`.github/workflows/steam-harvest.yml` (manual "Run workflow") runs both tools on a GitHub
runner, commits the payload to `main` and dispatches `deploy-pages.yml` (a `GITHUB_TOKEN`
push triggers no workflow on its own). Locally:
`python steamfilter/tools/scan_steam.py && python steamfilter/tools/make_data.py`.
Until the first harvest the committed payload has `"games": []` and the page says so.

Payload rows are `{n, id, y, p, t[, c, sw]}` — name, app id, release year (or null),
positive and total English reviews, category ids and `sw: 1` when on Switch. The header
carries `categories` (`[{id, label}]`) so the page needs no copy of `categories.json`.
Nothing derived from the reviews is stored.

## Categories and Switch (`tools/enrich.py`)

Applied to every kept game at the end of a full harvest, or ALONE to the shipped payload by
the workflow's `mode: enrich` (`scan_steam.py --enrich`, ~2 min: ~90 tag requests, no reviews) —
so a change to `categories.json` never needs the 7-hour review harvest.
- **Categories** are groups of Steam user tags (OR within a group); the page ANDs the groups
  a reader picks. Each game's tags come from Steam's keyless store API
  `IStoreBrowseService/GetItems` (100 games a request, `include_tag_count: 20`), names from
  `store.steampowered.com/tagdata/populartags/english`. An unknown tag name is logged; a group
  with no known tag or no member FAILS the run, as does fewer than 90% of games coming back
  with tags. **SteamSpy's `request=tag` lists are NOT usable** — on 2026-10-19 they answered
  "Puzzle" 0 apps, "Roguelike" 70, "Roguelite" 0, and the empty-group guard is what kept that
  from shipping.
- **Switch** is a title match against Nintendo's EU eShop index (`searching.nintendo-europe.com`,
  `system_type:nintendoswitch*`, so Switch 2 too). There is no shared id; `norm_title` folds
  case, accents, ™/®, punctuation and edition suffixes ("- Nintendo Switch Edition",
  "Definitive Edition"). A port renamed for Switch is missed; false matches are rare. The run
  fails if the index lists under 5,000 games, or if any of `CANARIES` (Hades, Balatro,
  Terraria, …) is absent, or if it read under 98% of `numFound`. **The index silently caps a
  page at ~1,000 docs whatever `rows` asks**, so `start` steps by the docs that came back,
  never by `rows`: stepping by 2,000 read half the catalogue (19,912 entries → 9,947 titles,
  and Hades, Balatro, Slay the Spire and Terraria read "not on Switch"); by 10,000, a tenth.

## Prices (`tools/prices.py`) — their own file, their own workflow

Prices move daily and a sale ends mid-week, while the review harvest runs every month or
two, so they ship as `steam-prices.json`, written by `.github/workflows/steam-prices.yml`
(08:17 + 17:43 UTC daily, and "Run workflow"; ~2 min). `prices.py` leaves the file untouched
when nothing moved, so a quiet run commits nothing and fires no deploy. The page fetches it
beside the payload and works without it (every price reads "—").
- **Steam** — the same `IStoreBrowseService/GetItems` as the tags, with
  `include_all_purchase_options`: `best_purchase_option` gives the price, the discount and
  `active_discounts[].discount_end_date`. Steam gives no START.
- **Switch** — nintendo.com's own store search (Algolia app `U3B6GR4UA3`, the search-only
  key the site ships to every browser; index `store_game_en_us`), 50 queries a request,
  only for `sw` games, **searched by the FOLDED title** — the full one let "Game of the Year
  Edition" rank every other GOTY above Batman. A hit must `norm_title`-match; the cheapest
  listing today wins (Switch, Switch 2 and Deluxe listings of one game all match), and `w2`
  records that a Switch 2 version is sold. `eshopDetails` carries the sale's start AND end.
  **DLC is `dlcType: "Individual"` only** — a "ROM Bundle" is a game sold with its DLC, and
  DOOM Eternal's base listing is one. Some games have a priceless twin listing; skip it.
- **The page shows a sale only inside its window** (`priceNow` in `prices.js`), so a file a
  day old shows an ended sale at its regular price, never a price that is gone.
- Guards: Steam must price 95% of the payload, the eShop 85% of `sw` games and every
  `enrich.CANARIES` title. Measured 2026-10-23: 8,556/8,567 and 1,970/1,992.

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
