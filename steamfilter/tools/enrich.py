"""Categories and Nintendo Switch availability for the Steam Filter payload.

Neither comes from the review harvest, and both are cheap, so they can be
re-applied to an existing payload in minutes (`scan_steam.py --enrich`) without
re-collecting a single review.

  Categories — categories.json groups Steam user tags ("Roguelike / Roguelite" is
    Roguelike + Roguelite + Action Roguelike + ...). Membership comes from
    SteamSpy's per-tag lists (`api.php?request=tag&tag=<name>`): ONE request
    per tag returns every app carrying it, where Steam itself would need a page
    per game. A game is in a group if it carries ANY of the group's tags.

  Switch — Nintendo's EU eShop search index lists every Switch / Switch 2 game.
    It shares no id with Steam, so a game counts as "on Switch" when its title
    matches after `norm_title` (case, accents, trademark marks, punctuation and
    edition suffixes folded away). A title match can miss a renamed port; it
    rarely produces a false one.
"""
import json, os, re, time, unicodedata, urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
CATEGORIES = os.path.join(HERE, "categories.json")

STEAMSPY_TAG = "https://steamspy.com/api.php?request=tag&tag={tag}"
NINTENDO = ("https://searching.nintendo-europe.com/en/select?q=*"
            "&fq=type:GAME%20AND%20system_type:nintendoswitch*"
            "&fl=title&wt=json&rows={rows}&start={start}")


def load_categories():
    return json.load(open(CATEGORIES, encoding="utf-8"))


# ── categories ────────────────────────────────────────────────────────────

class Rejected(Exception):
    pass


def validate_steamspy(body):
    try:
        j = json.loads(body)
    except ValueError:
        raise Rejected("steamspy: not json " + repr(body.lstrip()[:60]))
    if not isinstance(j, dict):
        raise Rejected("steamspy: unexpected shape")
    return j


def category_members(fetch, log, cats=None):
    """{group id: set(app ids)}. SteamSpy asks for one request a second."""
    cats = cats or load_categories()
    tags = sorted({t for c in cats for t in c["tags"]})
    by_tag = {}
    for tag in tags:
        j = fetch(STEAMSPY_TAG.format(tag=urllib.parse.quote_plus(tag)), validate_steamspy)
        by_tag[tag] = {int(k) for k in j if str(k).isdigit()}
        log(f"tag {tag!r}: {len(by_tag[tag]):,} apps")
        time.sleep(1.1)
    # A misspelt tag name answers with an empty list, not an error, so it would
    # silently shrink its group. Say which ones; fail only a group left empty.
    empty = [t for t in tags if not by_tag[t]]
    if empty:
        log(f"WARNING: no apps for tag(s) {empty} — check the spelling in categories.json")
    out = {}
    for c in cats:
        out[c["id"]] = set().union(*(by_tag[t] for t in c["tags"]))
        if not out[c["id"]]:
            raise SystemExit(f"category {c['id']!r} matched no app at all — refusing a silent hole")
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


def switch_titles(fetch, log, rows=2000):
    keys, start, total = set(), 0, None
    while total is None or start < total:
        r = fetch(NINTENDO.format(rows=rows, start=start), validate_nintendo)["response"]
        total = int(r["numFound"])
        for d in r["docs"]:
            k = norm_title(d.get("title") or "")
            if k:
                keys.add(k)
        if not r["docs"]:
            break
        start += rows
    if total < 5000 or len(keys) < 5000:
        raise SystemExit(f"Nintendo's index listed {total} Switch games ({len(keys)} titles) — "
                         "too few to be the whole catalogue")
    log(f"switch: {total:,} eShop games, {len(keys):,} distinct titles")
    return keys


def enrich(games, fetch, log):
    """Adds `c` (category ids) and `sw` (1 when on Switch) to each game in place."""
    members = category_members(fetch, log)
    titles = switch_titles(fetch, log)
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
