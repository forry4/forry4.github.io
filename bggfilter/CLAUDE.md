# BGG Filter — Claude Context

A **frontend-only** feature: a filterable table of BoardGameGeek's ranked games, reached from
the home menu next to Spender Puzzles and Books. No backend, no room server, no auth — it
fetches one static JSON and does everything client-side.

| File | What it is |
|---|---|
| `BggFilter.jsx` | the whole feature; props are just `{ onExit }` |
| `BggFilter.css` | `?inline`-imported stylesheet, `.bgf`-prefixed |
| `tools/scan_bgg.py` | **the harvester** — hits BGG, writes `results_all.json` |
| `tools/make_data.py` | `results_all.json` → `webapp/public/data/bgg-filter.json` (the shipped payload) |

## The data is GENERATED — do not hand-edit the JSON

`webapp/public/data/bgg-filter.json` (17,515 games, ~2.5MB / ~650KB gzipped) is a build artifact.
Regenerate with `python bggfilter/tools/scan_bgg.py && python bggfilter/tools/make_data.py`.
The intermediate `results_all.json` is **not** committed; only the trimmed payload is.

**It is fetched, not imported.** At ~2.5MB, bundling it would put the whole dataset in the lazy
chunk for everyone who opens the page. The chunk is ~18KB and the data arrives separately,
CDN-cached like any other asset in `webapp/public/`.

## Harvesting lessons (paid for once — do not relearn)

- **BGG's XML API is closed.** It returns 401 and needs a registered application (a week+ of
  approval). Everything here uses the endpoints the BGG *website* calls: the advanced search
  page, `geekitempoll.php?action=view` (to find a game's poll id), `geekpoll.php?action=results`
  (the vote matrix), and `api.geekdo.com/api/dynamicinfo` (exact weight + rating stats).
- **BGG 403s Python's TLS fingerprint**, so every request shells out to `curl`.
- **The advanced search hard-caps at 50 pages (5,000 rows)** whatever the filter, so the
  universe is enumerated in **weight bands** and de-duplicated by id. At the 100-rating floor
  the fixed half-point bands overrun that cap, so `collect_band` **probes page 50 first and
  halves the band if rows still reach it**, recursively. A capped band loses its tail in
  silence — the same failure mode as the cached challenge pages below, with no error to read.
- **Cloudflare answers a burst with a 200-OK "Just a moment..." challenge page.** The first run
  cached those as if they were data and three whole weight bands came back "empty" — every game
  over 3.5 weight vanished with nothing to indicate it. `reject()` in `scan_bgg.py` validates
  every response *before* it is cached (challenge signatures, HTML where JSON was expected,
  implausibly short pages) and retries. **Never cache an unvalidated response.**
- **That challenge is RATE-triggered, not a block** — roughly one request in four draws it and
  the next one seconds later goes straight through. The backoff is therefore short and linear
  (3s, 6s, … capped at 30s, ten tries), not the original quadratic 5/20/45/80s: at the 100-rating
  floor the harvest is ~50k requests, and sleeping minutes off each challenge cost far more wall
  time than the fetching did.
- **Unranked entries are dropped.** BGG excludes alternate editions and big boxes from its
  ranking, so their Geek ratings are not comparable and they duplicate games already listed.

## The three rating columns

`Geek rating` is BGG's bayesian rating (a pile of dummy votes at ~5.5 drags a thinly-rated game
towards the mean), `Average` is the raw mean of what people actually scored it, and **`F average`
between them is simply their midpoint** — derived in `derive()`, never stored in the payload, and
sortable like any other column. The two ends disagree in opposite directions on exactly the games
this tool is for: the Geek rating punishes a well-liked game with few votes, the raw average lets a
few dozen devotees crown one. Nothing else reads `g.f`.

## Reading the percentages

The poll lets each voter mark every player count Best / Recommended / Not Recommended
**independently**, so the shares across counts do not sum to 100%. Per count the UI shows
`best% / (best+recommended)%`, both over the voters who expressed an opinion about *that*
count — the same denominator BGG displays. A count with no votes reads `-1` internally so it
fails every threshold above zero while still rendering as "no votes".

**Poll size has no column of its own** — one number per row could only describe the biggest of the
three polls, while it is the count-by-count denominator that decides whether *that* bar means
anything. Each cell instead carries its own total: under 100 votes the percentage prints amber, and
the vote count is the cell's `title`. The panel's summary line still counts rows by `pt`, the
poll-wide voter total, which is why the payload keeps it.

**A 60% bar means different things at different counts**, and it is the MIDDLE count that is
harsh: votes at three spread onto its neighbours, while two and four sit at the ends of the usual
range and collect concentrated ones. Under the panel's default dials, Best ≥80% holds for 476
games at two players, 193 at four — and 45 at three. (An older note here claimed Best-at-4 was the
far harsher filter, at 17 games against 792. It does not hold on the harvested data at any
threshold; four is consistently the easier of the two ends after two.) Poll size matters too —
100% off 40 voters is not 97% off 1,500 — so a count polled under 100 times is flagged amber.

## Wiring (the five places a new screen must be registered)

`shared/router.js` `MODES` · `shared/HomeScreen.jsx` (the `onBggFilter` button) ·
`games/spender/Spender.jsx` (**three** spots: the `lazyChunk`, the `screen === "bggfilter"`
branch, **and both `SCREEN_FOR_MODE` / `MODE_FOR_SCREEN`** — missing the maps compiles, renders
a working home button, and then the route simply never mounts) · `webapp/test/screens.mjs`
`SCREENS` · and **both deploy path filters** (`.github/workflows/deploy-pages.yml` and
`.githooks/pre-push`) — a top-level directory absent from those never triggers a deploy.
