# Anime Filter — Claude Context

A **frontend-only** sibling of BGG Filter and Steam Filter: the top 500 anime by
MyAnimeList, AniList and Kitsu combined, with a show's seasons averaged into one row,
filtered client-side by genre, tag, year, format, demographic and **English dub**. No
backend, no auth — one static JSON.

| File | What it is |
|---|---|
| `AnimeFilter.jsx` | the whole page; props `{ onExit }` |
| `derive.js` | the page's logic (combined score, filters, season rows), unit-tested by `webapp/test/unit/animefilter.test.mjs` |
| `AnimeFilter.css` | `?inline`-imported, `.anf`-prefixed (started as a copy of Steam Filter's) |
| `tools/harvest.py` | **the harvester** — AniList, MAL (its own pages), Kitsu, the cross-site id map, the dub list → `results_all.json` |
| `tools/make_data.py` | `results_all.json` → `webapp/public/data/anime-filter.json` — grouping, averaging, the combined score, the top 500 |
| `tests/` | `make_data` on a hand-built harvest; `harvest`'s parsers and response guards |

## The data is GENERATED — harvested on a runner, not here

**The dev container cannot reach any of the rating sites** (AniList, Jikan, MAL, Kitsu,
Anime-Planet and AniDB all draw a proxy 403; only GitHub is allowed). So
`.github/workflows/anime-harvest.yml` (quarterly on the 10th of Jan/Apr/Jul/Oct, and "Run
workflow") runs `harvest.py` on a runner —
~25 min cold (most of it MAL at one page per 2s), ~2 min off a warm cache — and and **force-pushes the raw `results_all.json.gz` to the `anime-harvest` branch**;
with `publish` on (the default, and always on a scheduled run) it also runs `make_data.py`,
commits the payload to `main` and dispatches the Pages deploy. `make_data.py` refuses a list
under 500 shows or with any site's coverage below 90% of the current file's (`--force`). To re-tune the list without asking the sites again:

```bash
git fetch origin anime-harvest
git show origin/anime-harvest:results_all.json.gz | gunzip > animefilter/tools/results_all.json
python animefilter/tools/make_data.py
```

Every answer is validated before it is cached (`v_anilist`/`v_jikan`/`v_kitsu` raise
`Reject`, which retries and never caches — BGG's cached-challenge-page lesson), and the
cache is saved by the workflow even on failure, so a re-run resumes. The harvest fails if a
canary (FMA:B, Attack on Titan, Steins;Gate, Frieren) is missing from any site, or Kitsu
covers under 80% of entries.

**Which hosts answer a GitHub runner is not which hosts work from a browser** — the
workflow's `probe_only` input prints DNS, v4/v6 status codes and sample markup for each
site without harvesting. What the 2026-11-03 probes found, each of which cost a red run:
- **Jikan (`api.jikan.moe`) does not answer runners at all**, v4 or v6 (connect timeout →
  `Errno 101`). Do not go back to it; MAL is read from `myanimelist.net` itself.
- **`kitsu.app` answers runners with a Cloudflare 403; `kitsu.io` serves the same API.**
- **Kitsu is JSON:API and returns 406 to `Accept: application/json`** — it must be
  `application/vnd.api+json`.
- Runners have no IPv6 route, so `harvest.py` sorts IPv4 addresses first.

## Sources

- **AniList** (GraphQL) — score, popularity, English/romaji titles, genres, tags, start
  date, and the **SEQUEL/PREQUEL edges that define a show**. The universe is its
  score-ranked list over a popularity floor, plus MAL's top list (fetched onto AniList by
  `idMal_in`), plus the transitive sequel/prequel closure of both — a show is averaged
  over ALL its seasons, including the ones too weak to chart alone.
- **MyAnimeList, from its own pages** — `topanime.php` (50 rows a page: id, rank, score,
  members) down to a 7.0 score, then `anime/<id>` for every held entry off that list
  (score, voters, members, rank, English title). Only the parsed fields are cached.
  MAL's API wants a registered client id. `parse_top`/`parse_anime` are pinned to real
  markup in `tests/test_harvest.py`; a throttle page raises `Reject`.
- **Kitsu** — `averageRating` (0–100) and its votes (the sum of `ratingFrequencies`).
  Matched through **manami-project/anime-offline-database** (a GitHub release: the
  cross-site id map), falling back to Kitsu's own `mappings` endpoint.
- **MAL-Dubs** (`dubInfo.json`) — MAL ids with an English dub, plus an `incomplete` list
  (dub still being produced).
- Not used: Anime-Planet and AniDB have no open API (AniDB needs a registered client;
  Anime-Planet is Cloudflare-fronted HTML).

## How a row is made (`make_data.py`)

1. **Entries**: AniList TV / TV short / ONA / movie entries (specials, OVAs, music and
   unreleased entries never count). A site's score counts only over a vote floor
   (`FLOOR`: 5,000 MAL members — the top list prints no voter count —, 1,000 AniList list
   adds, 100 Kitsu ratings).
2. **Shows**: union-find over SEQUEL/PREQUEL edges between entries, **passing through
   specials and OVAs** (`BRIDGE_FORMATS`), which join but are never listed — without
   them Gintama's final film, Monogatari's Off & Monster season, Euphonium 3 and Mushishi's
   second series each sat alone, because their chain runs through a special. The harvest
   follows those edges too. `SPLIT` cuts the chains AniList draws between genuinely
   different series: the four Fate/stay night adaptations hanging off Fate/Zero, Initial
   D → MF Ghost, End of Evangelion → the Rebuild films, GitS SAC → SAC_2045, Touch → MIX
   (both reached only through a special), and three prequel spin-offs. **Following bridges
   joins more than it should, so after a harvest that changes the closure, diff the show
   list against the shipped one** — that is how the last two were found. **To
   find the next one**, list groups whose seasons' titles don't share the show's first
   word, or whose years span 15+ — that scan found every split above.
3. **Site score** = the plain mean of the show's seasons on that site — each season counts
   once whatever its length or vote count. A show is **named and dated by its first
   season** (earliest start date), less a "Season 1" / "S1" / "1st Stage" suffix; a show
   no site gives an English title is named from `ENGLISH` (three as of 2026-11; Major,
   Touch, City Hunter… are already English). The demographic is AniList's Demographic-
   category tag, not MAL's (MAL's pages aren't read for it). Genres are the union over seasons; tags are AniList's
   non-spoiler tags whose rank, averaged over all seasons, reaches `TAG_RANK`.
4. **Combined score**: each site's show score as a z-score over the shows it rates, the
   available z-scores averaged, the result put back on MAL's scale (`mean + z·sd`). The
   header's `scale` carries each site's `[mean, sd]`, so the page recomputes it when a
   site is switched off. Raw averaging was rejected because Kitsu's curve is compressed
   and MAL's long-tailed — a raw mean lets the site with the widest spread decide.
5. **Listed**: shows whose most-watched season has `MIN_MEMBERS`+ MAL members, rated on
   two or more sites; the top `TOP` (500) by combined score.

**Dub**: per season 2 (dubbed), 1 (dub incomplete), 0 (none known); per show 2 when
every season is 2, 1 when any season has one, else 0. The page's filter is Any / Has a
dub (≥1) / Fully dubbed (2).

`compare` in the header (for the page's notes) counts how many distinct shows MAL's
top 100 single entries come from — the clutter the averaging removes.

## Payload

Header: `collected`, `top`, `min_members`, `floors`, `scale`, `genres` / `tags` (rosters,
most common first), `compare`, `shows`. A show: `{id (AniList id of the first season), n
(English title), r (romaji), y, f (TV/ONA/Movie), c (country), dm, st, g, t, dub, m, a, k
(per-site show scores on 0–10), mv (MAL members), rk, p: [season…]}`; a season: `{id, mal,
n, y, f, e, m, a, k, mr (MAL rank), d (dub)}`.

## Wiring

The BGG Filter five (`bggfilter/CLAUDE.md`) — `MODES`, the Extras tile (`onAnimeFilter`),
`Spender.jsx`'s lazy chunk / screen branch / both screen maps, `screens.mjs` `SCREENS`, both
deploy path filters — plus the offline hub's Read row and reading pack, `offlineRead`'s
row list and `formControlZoom`'s walk in `screens.mjs`, and `affected.mjs`.
