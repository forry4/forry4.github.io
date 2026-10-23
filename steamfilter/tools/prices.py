"""Today's prices, and any sale running, for every game in the Steam Filter payload.

Both stores are read for the US:

  Steam   `IStoreBrowseService/GetItems` (no key, 100 games a request) with
          `include_all_purchase_options`: each game's best purchase option, its
          discount and the moment that discount ends.
  Switch  nintendo.com's own store search (Algolia, with the search-only key the
          site hands every browser): the eShop price, the sale price and the sale's
          start and end, for every game the payload marks as on Switch (`sw`). It is
          matched by `enrich.norm_title`, the same fold that set `sw`. A Switch 2
          version or "Nintendo Switch 2 Edition" counts as the same game.

Prices move daily and a sale ends mid-week, while the review harvest runs every
month or two, so prices live in their own file, refreshed by their own workflow
(`steam-prices.yml`). The page shows a sale only inside its start..end window, so a
stale file shows an ended sale at its regular price rather than a price that is gone.

Writes webapp/public/data/steam-prices.json:

    {"priced": "2026-10-23T17:42Z", "region": "US",
     "games": {"<app id>": {"s": [999], "w": [624, 2499, <end>, <start>], "w2": 1}}}

`s` is Steam and `w` the eShop, in cents: `[price]`, or `[sale, regular, end]` for a
sale (Unix seconds; the eShop adds its start). Steam names no start, and a discount
with no end date is `[sale, regular]`. `w2` is 1 when a Switch 2 version is sold.
A game with no price in a store has no key for it.

    python steamfilter/tools/prices.py
"""
import argparse, datetime, json, os, sys, time, urllib.parse

try:                       # imported as steamfilter.tools.prices (the tests)
    from . import enrich
    from .scan_steam import fetch, log, PAYLOAD
except ImportError:        # run as a script from the workflow
    import enrich
    from scan_steam import fetch, log, PAYLOAD

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "..", "webapp", "public", "data", "steam-prices.json")

GET_ITEMS = enrich.GET_ITEMS
BATCH = enrich.BATCH
ALGOLIA = "https://U3B6GR4UA3-dsn.algolia.net/1/indexes/*/queries"
ALGOLIA_HEADERS = {"X-Algolia-Application-Id": "U3B6GR4UA3",
                   "X-Algolia-API-Key": "a29c6927638bfd8cee23993e51e721c9",
                   "Content-Type": "application/json"}
ESHOP_INDEX = "store_game_en_us"
QUERIES = 50               # Algolia refuses a multi-query request much over this
# The share of games each store must price before the file is trusted. Measured
# 2026-10-23: Steam priced 8,556 of 8,567 (the rest are delisted) and the US eShop
# 1,970 of 1,992 `sw` games (the rest are listed without a price, or not sold in the US).
MIN_STEAM = 0.95
MIN_SWITCH = 0.85

Rejected = enrich.Rejected


# ── Steam ─────────────────────────────────────────────────────────────────

def steam_price(item):
    """`[price]` or `[sale, regular, end]` in cents, or None when it cannot be bought."""
    if item.get("is_free"):
        return [0]
    o = item.get("best_purchase_option") or {}
    if "final_price_in_cents" not in o:
        return None
    final = int(o["final_price_in_cents"])
    regular = int(o.get("original_price_in_cents") or 0)
    if regular <= final or o.get("price_cannot_be_displayed_as_discount"):
        return [final]
    # Stacked discounts each carry an end; the price moves when the first one lapses.
    ends = [int(d["discount_end_date"]) for d in o.get("active_discounts") or []
            if d.get("discount_end_date")]
    return [final, regular, min(ends)] if ends else [final, regular]


def steam_prices(fetch, log, appids, pause=0.5):
    out = {}
    for k in range(0, len(appids), BATCH):
        q = {"ids": [{"appid": a} for a in appids[k:k + BATCH]],
             "context": {"language": "english", "country_code": "US", "steam_realm": 1},
             "data_request": {"include_all_purchase_options": True}}
        url = GET_ITEMS.format(q=urllib.parse.quote(json.dumps(q, separators=(",", ":"))))
        for it in fetch(url, enrich.validate_items):
            a = it.get("appid") or it.get("id")
            p = steam_price(it) if a is not None else None
            if p is not None:
                out[int(a)] = p
        if (k // BATCH) % 20 == 19:
            log(f"steam: {min(k + BATCH, len(appids)):,}/{len(appids):,} games")
        time.sleep(pause)
    log(f"steam: priced {len(out):,} of {len(appids):,} games, "
        f"{sum(len(p) > 1 for p in out.values()):,} on sale")
    if len(out) < MIN_STEAM * len(appids):
        raise SystemExit(f"Steam priced only {len(out)} of {len(appids)} games — refusing a thin answer")
    return out


# ── the eShop ─────────────────────────────────────────────────────────────

def stamp(iso):
    """Unix seconds from the eShop's "2026-10-29T23:59:59Z", or None."""
    if not iso:
        return None
    return int(datetime.datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp())


def eshop_price(hit):
    """`[price]` or `[sale, regular, end, start]` in cents, or None (DLC, or a listing
    that cannot be bought — the store keeps a priceless twin of some games). DLC is
    `dlcType: "Individual"`; a "ROM Bundle" is a game sold with its DLC — DOOM Eternal's
    base listing is one."""
    if hit.get("dlcType") == "Individual":
        return None
    d = hit.get("eshopDetails") or {}
    if d.get("regularPrice") is None:
        return None
    regular = round(d["regularPrice"] * 100)
    end = stamp(d.get("discountPriceEnd"))
    if d.get("discountPrice") is None or not end:
        return [regular]
    sale = round(d["discountPrice"] * 100)
    if sale >= regular:
        return [regular]
    return [sale, regular, end, stamp(d.get("discountPriceStart")) or 0]


def validate_queries(n):
    def check(body):
        try:
            res = json.loads(body)["results"]
            assert len(res) == n and all(isinstance(r["hits"], list) for r in res)
        except (ValueError, KeyError, TypeError, AssertionError):
            raise Rejected("eshop: unexpected shape " + repr(body.lstrip()[:80]))
        return res
    return check


def switch_prices(fetch, log, games, canaries=None):
    """{app id: {"w": price, "w2": 1?}} for the games marked `sw`."""
    games = [g for g in games if g.get("sw")]
    out = {}
    for k in range(0, len(games), QUERIES):
        chunk = games[k:k + QUERIES]
        # Searched by the folded title: the full one lets an edition name rank every
        # other "Game of the Year Edition" above the game ("Batman: Arkham Asylum
        # Game of the Year Edition" found Borderlands and Badland, and not Batman).
        body = json.dumps({"requests": [{"indexName": ESHOP_INDEX, "params": urllib.parse.urlencode({
            "query": enrich.norm_title(g["n"]), "hitsPerPage": 10,
            "attributesToRetrieve": "title,platform,eshopDetails,dlcType"})} for g in chunk]})
        res = fetch(ALGOLIA, validate_queries(len(chunk)), data=body.encode(), headers=ALGOLIA_HEADERS)
        for g, r in zip(chunk, res):
            key = enrich.norm_title(g["n"])
            found = [(p, h) for h in r["hits"] if enrich.norm_title(h.get("title") or "") == key
                     for p in [eshop_price(h)] if p is not None]
            if not found:
                continue
            # A game sold as several listings (Switch, Switch 2, Deluxe Edition) is shown
            # at the cheapest of them today.
            p = min((p for p, _ in found), key=lambda p: (p[0], len(p) == 1))
            out[g["id"]] = {"w": p}
            if any(h.get("platform") == "Nintendo Switch 2" for _, h in found):
                out[g["id"]]["w2"] = 1
        time.sleep(0.2)
    log(f"switch: priced {len(out):,} of {len(games):,} Switch games, "
        f"{sum(len(v['w']) > 1 for v in out.values()):,} on sale")
    if len(out) < MIN_SWITCH * len(games):
        raise SystemExit(f"the eShop priced only {len(out)} of {len(games)} Switch games — "
                         "refusing a thin answer")
    names = {g["n"]: g["id"] for g in games}
    missing = [c for c in (enrich.CANARIES if canaries is None else canaries)
               if names.get(c) not in out]
    if missing:
        raise SystemExit(f"the eShop gave no price for {missing}, which are all sold there")
    return out


# ── the file ──────────────────────────────────────────────────────────────

def merge(steam, switch):
    rows = {}
    for a, p in steam.items():
        rows.setdefault(str(a), {})["s"] = p
    for a, v in switch.items():
        rows.setdefault(str(a), {}).update(v)
    return rows


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=OUT)
    a = ap.parse_args(argv)
    games = json.load(open(PAYLOAD, encoding="utf-8")).get("games") or []
    if not games:
        raise SystemExit("prices need a harvested payload; run the full harvest first")
    rows = merge(steam_prices(fetch, log, [g["id"] for g in games]), switch_prices(fetch, log, games))
    # Nothing moved: leave the file (and its timestamp) alone, so the workflow has
    # nothing to commit and no deploy to fire.
    if os.path.exists(a.out):
        try:
            if json.load(open(a.out, encoding="utf-8")).get("games") == rows:
                log("prices: unchanged")
                return
        except ValueError:
            pass
    now = datetime.datetime.now(datetime.timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    with open(a.out, "w", encoding="utf-8") as f:
        json.dump({"priced": now, "region": "US", "games": rows}, f, separators=(",", ":"))
    log(f"{len(rows):,} games priced -> {a.out} ({os.path.getsize(a.out):,} bytes)")


if __name__ == "__main__":
    sys.exit(main())
