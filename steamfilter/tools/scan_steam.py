"""Full Steam harvest for the Steam Filter page.

Two passes, both over endpoints the Steam STORE itself calls (no API key):

  1. /search/results/?infinite=1&json=1&category1=998   every game on the store,
     100 rows a page: app id, title, release date and the review tooltip
     ("94% of the 1,234 user reviews ..."). That tooltip is only a PREFILTER —
     it may count every language, and the page is about English reviews.
  2. /appreviews/<id>?json=1&language=english&num_per_page=0   the exact English
     totals for every candidate the prefilter kept.

Only games whose ENGLISH reviews are at least MIN_POSITIVE positive, with at
least MIN_REVIEWS English reviews, are kept. The prefilter is deliberately
looser than both (PREFILTER_PCT) so a game whose English score beats its
all-language one is not dropped before it is asked.

Writes results_all.json beside this file; make_data.py trims it into the
shipped payload.

    python steamfilter/tools/scan_steam.py [--min-reviews 50] [--workers 4]
"""
import argparse, datetime, html, json, os, re, sys, threading, time
import urllib.error, urllib.request
from concurrent.futures import ThreadPoolExecutor

try:                       # imported as steamfilter.tools.scan_steam (the tests)
    from . import enrich
except ImportError:        # run as a script from the workflow
    import enrich

HERE = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(HERE, "cache")
OUT = os.path.join(HERE, "results_all.json")
PAYLOAD = os.path.join(HERE, "..", "..", "webapp", "public", "data", "steam-filter.json")

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")
PAGE = 100
MIN_REVIEWS = 50
MIN_POSITIVE = 0.90
# The search tooltip's share may be all-language; English can run higher than it
# (a review bomb in one language drags the blend), so prefilter well below 90.
PREFILTER_PCT = 80

SEARCH = ("https://store.steampowered.com/search/results/?query=&start={start}&count={count}"
          "&dynamic_data=&sort_by=Released_DESC&category1=998&infinite=1&json=1"
          "&l=english&cc=us&ignore_preferences=1&ndl=1")
REVIEWS = ("https://store.steampowered.com/appreviews/{id}?json=1&language=english"
           "&purchase_type=all&review_type=all&filter=all&num_per_page=0")

_print_lock = threading.Lock()


def log(*a):
    with _print_lock:
        print(*a, flush=True)


# ── fetching ──────────────────────────────────────────────────────────────

Rejected = enrich.Rejected   # one class, so fetch() retries the enrich validators too


def validate_search(body):
    """The parsed search page, or raise. A response must prove itself before it
    is used: an HTML error page or an empty 200 must never read as 'no games'."""
    try:
        j = json.loads(body)
    except ValueError:
        raise Rejected("search: not json " + repr(body.lstrip()[:60]))
    if not isinstance(j, dict) or j.get("success") != 1 or "results_html" not in j:
        raise Rejected("search: unexpected shape " + repr(str(j)[:120]))
    return j


def validate_reviews(body):
    try:
        j = json.loads(body)
    except ValueError:
        raise Rejected("reviews: not json " + repr(body.lstrip()[:60]))
    q = j.get("query_summary") if isinstance(j, dict) else None
    if j.get("success") != 1 or not isinstance(q, dict) or "total_reviews" not in q:
        raise Rejected("reviews: unexpected shape " + repr(str(j)[:120]))
    return j


def fetch(url, check, tries=10, data=None, headers=None):
    """GET url (POST `data` when given), validate with `check`, retry. 429 and 5xx back
    off harder than a malformed body: Steam's store rate-limits per IP and recovers in
    tens of seconds."""
    last = None
    for a in range(tries):
        try:
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": UA, "Accept-Language": "en-US,en;q=0.9",
                "Accept": "application/json,text/javascript,*/*;q=0.8", **(headers or {})})
            with urllib.request.urlopen(req, timeout=45) as r:
                body = r.read().decode("utf-8", "replace")
            return check(body)
        except urllib.error.HTTPError as e:
            last = e
            wait = min(30 * (a + 1), 120) if e.code in (429, 500, 502, 503, 504) else 3 * (a + 1)
        except (urllib.error.URLError, TimeoutError, OSError, Rejected) as e:
            last = e
            wait = min(3 * (a + 1), 30)
        time.sleep(wait)
    raise RuntimeError(f"gave up on {url}: {last}")


# ── parsing the search page ───────────────────────────────────────────────

ROW = re.compile(r'<a\b[^>]*class="[^"]*\bsearch_result_row\b[^"]*"[^>]*>.*?</a>', re.S)
APPID = re.compile(r'\bdata-ds-appid="(\d+)"')
TITLE = re.compile(r'<span class="title">(.*?)</span>', re.S)
RELEASED = re.compile(r'<div class="[^"]*\bsearch_released\b[^"]*">(.*?)</div>', re.S)
TOOLTIP = re.compile(r'class="[^"]*\bsearch_review_summary\b[^"]*"[^>]*data-tooltip-html="([^"]*)"'
                     r'|data-tooltip-html="([^"]*)"[^>]*class="[^"]*\bsearch_review_summary\b')
SHARE = re.compile(r"(\d{1,3})% of the ([\d,]+) user reviews")
YEAR = re.compile(r"\b(19[7-9]\d|20\d\d)\b")


def year_of(released):
    """The year in a store date ("26 Feb, 2016", "Feb 26, 2016", "Q1 2027"), or None
    ("Coming soon", "To be announced")."""
    m = YEAR.findall(released or "")
    return int(m[-1]) if m else None


def parse_search(results_html):
    """Every row on one search page as (row_count, [game dicts]).

    Bundles and packages have no single app id (data-ds-packageid / bundleid, or a
    comma-joined appid list) and are counted but skipped. A game with fewer than
    ten reviews has no tooltip; it reads pct/count None."""
    rows = ROW.findall(results_html)
    games = []
    for row in rows:
        m = APPID.search(row)
        if not m or "data-ds-packageid" in row or "data-ds-bundleid" in row:
            continue
        t = TITLE.search(row)
        r = RELEASED.search(row)
        tip = TOOLTIP.search(row)
        pct = count = None
        if tip:
            s = SHARE.search(html.unescape(tip.group(1) or tip.group(2)))
            if s:
                pct, count = int(s.group(1)), int(s.group(2).replace(",", ""))
        released = html.unescape(re.sub(r"<[^>]+>", "", r.group(1))).strip() if r else ""
        games.append({
            "id": int(m.group(1)),
            "n": html.unescape(t.group(1)).strip() if t else "",
            "y": year_of(released),
            "pct": pct, "count": count,
        })
    return len(rows), games


def is_candidate(g, min_reviews):
    return g["count"] is not None and g["count"] >= min_reviews and g["pct"] >= PREFILTER_PCT


def keep(pos, total, min_reviews):
    """The page's whole admission rule, in one place."""
    return total >= min_reviews and pos >= MIN_POSITIVE * total


# ── the two passes ────────────────────────────────────────────────────────

def cached_fetch(path, fresh_hours, url, check):
    """fetch(), but reuse a validated answer saved within `fresh_hours`. Every
    answer is written as soon as it arrives, so a run that is killed (the
    workflow's step timeout) resumes where it stopped instead of from zero."""
    if os.path.exists(path) and time.time() - os.path.getmtime(path) < fresh_hours * 3600:
        try:
            return check(open(path, encoding="utf-8").read())
        except Rejected:
            pass
    j = fetch(url, check)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(j, f)
    return j


def harvest_search(workers, fresh_hours):
    page_path = lambda start: os.path.join(CACHE, "search", f"{start}.json")
    first = fetch(SEARCH.format(start=0, count=PAGE), validate_search)   # always fresh: it sets the total
    total = int(first.get("total_count") or 0)
    if total < 1000:
        raise SystemExit(f"search reports only {total} games — refusing a truncated universe")
    log(f"search: {total:,} games on the store")
    starts = list(range(PAGE, total, PAGE))
    pages = {0: first}

    def one(start):
        pages[start] = cached_fetch(page_path(start), fresh_hours,
                                    SEARCH.format(start=start, count=PAGE), validate_search)
        if len(pages) % 50 == 0:
            log(f"search: {len(pages):,}/{len(starts) + 1:,} pages")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, starts))

    seen_rows, by_id = 0, {}
    for start in sorted(pages):
        n, games = parse_search(pages[start].get("results_html") or "")
        seen_rows += n
        for g in games:
            by_id.setdefault(g["id"], g)
    # A page that quietly came back short loses its rows in silence — the BGG
    # harvest's most expensive lesson. Releases land mid-harvest and shift offsets
    # by a handful, so allow a sliver, not a page.
    if seen_rows < total * 0.98:
        raise SystemExit(f"search returned {seen_rows:,} rows of {total:,} — paging was cut short")
    log(f"search: {seen_rows:,} rows, {len(by_id):,} distinct apps")
    return total, by_id


def harvest_reviews(cands, workers, fresh_hours):
    done = [0]

    def one(g):
        j = cached_fetch(os.path.join(CACHE, "reviews", f"{g['id']}.json"), fresh_hours,
                         REVIEWS.format(id=g["id"]), validate_reviews)
        q = j["query_summary"]
        g["pos"], g["tot"] = int(q.get("total_positive") or 0), int(q.get("total_reviews") or 0)
        done[0] += 1
        if done[0] % 250 == 0:
            log(f"reviews: {done[0]:,}/{len(cands):,}")

    with ThreadPoolExecutor(workers) as ex:
        list(ex.map(one, cands))


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--min-reviews", type=int, default=MIN_REVIEWS)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--fresh-hours", type=float, default=48,
                    help="reuse a cached review count younger than this (resumes a crashed run)")
    ap.add_argument("--enrich", action="store_true",
                    help="only (re)apply categories + Switch to the shipped payload; no Steam requests")
    a = ap.parse_args(argv)

    if a.enrich:
        cur = json.load(open(PAYLOAD, encoding="utf-8"))
        if not cur.get("games"):
            raise SystemExit("--enrich needs a harvested payload; run the full harvest first")
        games = [{k: g[k] for k in ("n", "id", "y", "p", "t")} for g in cur["games"]]
        enrich.enrich(games, fetch, log)
        write(cur["collected"], cur.get("min_reviews", a.min_reviews), games,
              store_total=None, candidates=None)
        return

    total, by_id = harvest_search(a.workers, a.fresh_hours)
    cands = [g for g in by_id.values() if is_candidate(g, a.min_reviews)]
    log(f"prefilter: {len(cands):,} candidates ({a.min_reviews}+ reviews, {PREFILTER_PCT}%+ on the store)")
    harvest_reviews(cands, a.workers, a.fresh_hours)

    games = [{"n": g["n"], "id": g["id"], "y": g["y"], "p": g["pos"], "t": g["tot"]}
             for g in cands if keep(g["pos"], g["tot"], a.min_reviews)]
    enrich.enrich(games, fetch, log)
    write(datetime.date.today().isoformat(), a.min_reviews, games,
          store_total=total, candidates=len(cands))


def write(collected, min_reviews, games, store_total, candidates):
    cats = [{"id": c["id"], "label": c["label"]} for c in enrich.load_categories()]
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"collected": collected, "enriched": datetime.date.today().isoformat(),
                   "store_total": store_total, "candidates": candidates,
                   "min_reviews": min_reviews, "min_positive": MIN_POSITIVE,
                   "categories": cats, "games": games}, f, ensure_ascii=False)
    log(f"{len(games):,} games -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
