"""Categories and Nintendo Switch availability for the Steam Filter payload.

Neither comes from the review harvest, and both are cheap, so they can be
re-applied to an existing payload in minutes (`scan_steam.py --enrich`) without
re-collecting a single review.

  Categories — categories.json groups Steam user tags ("Roguelike / Roguelite" is
    Roguelike + Roguelite + Action Roguelike + ...); a game is in a group if it
    carries ANY of the group's tags. Each game's tags come from Steam's own
    store API, `IStoreBrowseService/GetItems` (no key; 100 games a request, up
    to 20 tags each), and tag names from the store's `tagdata/populartags`.
    (SteamSpy's per-tag lists were tried first and came back near empty —
    "Puzzle" 0 apps, "Roguelike" 70 — on 2026-10-19.)

  Switch — Nintendo's EU eShop search index lists every Switch / Switch 2 game.
    It shares no id with Steam, so a game counts as "on Switch" when its title
    matches after `norm_title` (case, accents, trademark marks, punctuation and
    edition suffixes folded away). A title match can miss a renamed port; it
    rarely produces a false one.
"""
import json, os, re, time, unicodedata, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CATEGORIES = os.path.join(HERE, "categories.json")

TAG_NAMES = "https://store.steampowered.com/tagdata/populartags/english"
GET_ITEMS = "https://api.steampowered.com/IStoreBrowseService/GetItems/v1/?input_json={q}"
BATCH = 100
NINTENDO = ("https://searching.nintendo-europe.com/en/select?q=*"
            "&fq=type:GAME%20AND%20system_type:nintendoswitch*"
            "&fl=title&sort=sorting_title%20asc&wt=json&rows={rows}&start={start}")
# Games that have long been on the eShop under exactly their Steam title. If the
# catalogue read misses any of them, the read is broken (it happened: a silently
# capped page size read half the index — 19,912 entries, 9,947 titles, and Hades,
# Balatro and Terraria all missing), so fail rather than un-Switch them.
CANARIES = ["Hades", "Balatro", "Terraria", "Stardew Valley", "Hollow Knight",
            "Slay the Spire", "Celeste", "Dead Cells"]


def load_categories():
    return json.load(open(CATEGORIES, encoding="utf-8"))


# ── categories ────────────────────────────────────────────────────────────

class Rejected(Exception):
    pass


def validate_tag_names(body):
    try:
        j = json.loads(body)
        names = {str(t["name"]): int(t["tagid"]) for t in j}
    except (ValueError, KeyError, TypeError):
        raise Rejected("tag names: unexpected shape " + repr(body.lstrip()[:80]))
    if len(names) < 200:
        raise Rejected(f"tag names: only {len(names)} tags")
    return names


def validate_items(body):
    try:
        items = json.loads(body)["response"].get("store_items", [])
        list(items)
    except (ValueError, KeyError, TypeError, AttributeError):
        raise Rejected("GetItems: unexpected shape " + repr(body.lstrip()[:80]))
    return items


def app_tags(fetch, log, appids):
    """{appid: set(tag ids)} straight from Steam, BATCH games a request."""
    out = {}
    for k in range(0, len(appids), BATCH):
        q = {"ids": [{"appid": a} for a in appids[k:k + BATCH]],
             "context": {"language": "english", "country_code": "US", "steam_realm": 1},
             "data_request": {"include_tag_count": 20}}
        url = GET_ITEMS.format(q=urllib.parse.quote(json.dumps(q, separators=(",", ":"))))
        for it in fetch(url, validate_items):
            a = it.get("appid") or it.get("id")
            if a is None:
                continue
            ids = set(it.get("tagids") or [])
            ids |= {t["tagid"] for t in it.get("tags") or [] if "tagid" in t}
            out[int(a)] = {int(t) for t in ids}
        if (k // BATCH) % 20 == 19:
            log(f"tags: {min(k + BATCH, len(appids)):,}/{len(appids):,} games")
        time.sleep(0.5)
    return out


def category_members(fetch, log, appids, cats=None):
    """{group id: set(app ids)} for the given apps."""
    cats = cats or load_categories()
    names = fetch(TAG_NAMES, validate_tag_names)
    # A misspelt tag name would silently shrink its group, so name every one that
    # Steam does not know, and fail a group that is left with no tag at all.
    unknown = sorted({t for c in cats for t in c["tags"] if t not in names})
    if unknown:
        log(f"WARNING: Steam has no tag named {unknown} — check categories.json")
    tags = app_tags(fetch, log, appids)
    tagged = sum(1 for a in appids if tags.get(a))
    log(f"tags: {tagged:,} of {len(appids):,} games came back with tags")
    if tagged < 0.9 * len(appids):
        raise SystemExit(f"only {tagged} of {len(appids)} games have tags — refusing a thin answer")
    out = {}
    for c in cats:
        want = {names[t] for t in c["tags"] if t in names}
        if not want:
            raise SystemExit(f"category {c['id']!r} has no known tag — refusing a silent hole")
        out[c["id"]] = {a for a in appids if tags.get(a, set()) & want}
        if not out[c["id"]]:
            raise SystemExit(f"category {c['id']!r} matched no game at all — refusing a silent hole")
    return out


# ── Nintendo Switch ───────────────────────────────────────────────────────

# Applied after punctuation is folded to spaces, so "Director's Cut" is "directors cut".
EDITION = re.compile(
    r"\s+(?:(?:for\s+)?nintendo\s+switch(?:\s+edition)?|switch\s+edition|remastered|directors\s+cut|"
    r"(?:definitive|complete|deluxe|ultimate|enhanced|special|anniversary|game\s+of\s+the\s+year|"
    r"goty|digital|standard|gold|collectors)\s+edition)$")


def norm_title(title):
    """A title folded so the same game reads the same on Steam and the eShop:
    "Hollow Knight: Voidheart Edition" stays itself, but "Dead Cells™",
    "DEAD CELLS" and "Dead Cells - Nintendo Switch Edition" all read "dead cells"."""
    s = re.sub(r"[™®©℠]", "", title or "")   # before NFKD, which spells ™ out as "TM"
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    s = s.lower().replace("&", " and ")
    s = s.replace("'", "").replace("\u2019", "")
    s = " " + re.sub(r"[^a-z0-9]+", " ", s).strip()
    for _ in range(3):   # "… remastered - nintendo switch edition" sheds both
        s = EDITION.sub("", s)
    return s.strip()


def validate_nintendo(body):
    try:
        j = json.loads(body)
        r = j["response"]
        int(r["numFound"]), list(r["docs"])
    except (ValueError, KeyError, TypeError):
        raise Rejected("nintendo: unexpected shape " + repr(body.lstrip()[:80]))
    return j


def switch_titles(fetch, log, rows=1000, canaries=None):
    # The index CAPS a page at ~1,000 docs whatever `rows` asks for, and says nothing:
    # stepping `start` by `rows` skipped the rest of every page (rows=2000 read half the
    # catalogue, rows=10000 a tenth). Step by what actually came back, and count it.
    keys, start, total, read = set(), 0, None, 0
    while total is None or start < total:
        r = fetch(NINTENDO.format(rows=rows, start=start), validate_nintendo)["response"]
        total = int(r["numFound"])
        for d in r["docs"]:
            k = norm_title(d.get("title") or "")
            if k:
                keys.add(k)
        if not r["docs"]:
            break
        start += len(r["docs"])
        read += len(r["docs"])
    if read < 0.98 * total:
        raise SystemExit(f"read {read:,} of the {total:,} eShop entries — paging was cut short")
    if total < 5000 or len(keys) < 5000:
        raise SystemExit(f"Nintendo's index listed {total} Switch games ({len(keys)} titles) — "
                         "too few to be the whole catalogue")
    log(f"switch: read {read:,} of {total:,} eShop entries, {len(keys):,} distinct titles")
    missing = [c for c in (CANARIES if canaries is None else canaries) if norm_title(c) not in keys]
    if missing:
        raise SystemExit(f"the eShop read is missing {missing}, which are all on Switch — "
                         "refusing a catalogue with holes in it")
    return keys


def enrich(games, fetch, log):
    """Adds `c` (category ids) and `sw` (1 when on Switch) to each game in place."""
    titles = switch_titles(fetch, log)      # one or two requests: fail fast
    members = category_members(fetch, log, [g["id"] for g in games])
    on_switch = 0
    for g in games:
        g["c"] = [cid for cid, ids in members.items() if g["id"] in ids]
        if norm_title(g["n"]) in titles:
            g["sw"] = 1
            on_switch += 1
        else:
            g.pop("sw", None)
    counts = {cid: sum(cid in g["c"] for g in games) for cid in members}
    log(f"enrich: {on_switch:,} of {len(games):,} games on Switch; per category {counts}")
    return games
