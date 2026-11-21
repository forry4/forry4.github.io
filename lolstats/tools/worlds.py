"""Worlds results for LoL Stats' Seeds tab, from Leaguepedia (lol.fandom.com).

    python -I lolstats/tools/worlds.py fetch        # every year: one Cargo query each, ~10s apart
    python -I lolstats/tools/worlds.py fetch 2026   # just that year, plus any year not in the cache
    python -I lolstats/tools/worlds.py build        # cache -> webapp/public/data/lol-worlds.json
    EVENT=schedule python -I lolstats/tools/worlds.py due 2026   # the workflow's gate: is 2026 still being played?

WHY LEAGUEPEDIA: the seeds tab splits Play-In from the main event, and Oracle's Elixir
carries no stage marker on Worlds games (it also files the regional qualifiers under
Worlds; make_data.py has to strip them). Leaguepedia's Cargo tables do: `MatchSchedule`
has one row per series with its event (`.../Play-In`, `.../Main Event`), its round
(`Tab`), both scores, the winner and the start time. ONE query returns a whole year.
Until 2026-11-21 this read Liquipedia's RENDERED stage pages (three per year, 31s apart,
HTML parsed for scores), and Liquipedia IP-blocks shared runner IPs with HTTP 429 (a
"Rate Limited" page lifted by CAPTCHA): it failed the 2026-11-16 refresh on its first
request, and blocked the dev box during the diagnosis. The switch was held to the old
payload series by series (docs/deploy-reliability-log.md, 2026-11-21).

HOW IT ASKS (polite.py): one query at a time, at least 10s apart, maxlag=5, a named
User-Agent, backoff on the API's `ratelimited` within a time budget, then exit 75 for the
next day's run. Settled years are kept in the cache, so a refresh makes ONE request.

The SEEDS table is hand-written from each year's Qualification page (Leaguepedia and
Liquipedia both list the qualifying path, not the seed). Every team in a series must
resolve to a seed, and every seeded team must appear in a series, or the build fails.
"""
import collections
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I leaves the script dir off
import polite   # noqa: E402

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "lolstats", "tools", "cache", "worlds")
OUT = os.path.join(ROOT, "webapp", "public", "data", "lol-worlds.json")
API = "https://lol.fandom.com/api.php"
SOURCE = "Leaguepedia"
EX_TEMPFAIL = polite.EX_TEMPFAIL

# A year's series live under "<year> Season World Championship/<event>". Play-In and Main
# Event are Worlds; 2023's Qualifying Series sent Team BDS in as LEC #4 and is not counted.
# Any other event fails the build, so a new format is looked at rather than guessed.
EVENTS = {"Play-In", "Main Event"}
NOT_WORLDS = {"Qualifying Series"}
KNOCKOUT_TABS = {"Quarterfinals", "Semifinals", "Finals"}
# Every round name 2020-2026 used (the Play-In's knockout rounds included: Elimination,
# Qualification, 2023's Qualifiers, 2025's single "Play-In" match).
TAB = re.compile(r"^(Round \d+|Day \d+|Week \d+|Tiebreakers?|Quarterfinals|Semifinals|Finals"
                 r"|Elimination Round|Qualification Round|Qualifiers|Play-In)$")
FIELDS = "OverviewPage,Tab,Team1,Team2,Team1Score,Team2Score,Winner,DateTime_UTC,BestOf,MatchId,FF"


def stage(y, event, tab):
    """The payload's stage label, as the Liquipedia pages were named: Play-In, then the
    main event's Groups (to 2022) or Swiss (from 2023), then its Knockout bracket."""
    if event == "Play-In":
        return "Play-In"
    if tab in KNOCKOUT_TABS:
        return "Knockout"
    return "Swiss" if y >= 2023 else "Groups"


def source_url():
    return f"https://lol.fandom.com/wiki/{max(SEEDS)}_Season_World_Championship"


# (league, seed, [the display name, then any alias Leaguepedia or Liquipedia uses]). LTA (2025) took the
# LCS's slots and LCP (2025) the PCS's; the page groups them so. 2023's Team BDS were
# LEC #4 through the Worlds Qualifying Series, which is not counted as Worlds.
SEEDS = {
    2020: [("LPL", 1, ["Top Esports"]), ("LPL", 2, ["JD Gaming"]), ("LPL", 3, ["Suning"]), ("LPL", 4, ["LGD Gaming"]),
           ("LCK", 1, ["DAMWON Gaming"]), ("LCK", 2, ["DRX"]), ("LCK", 3, ["Gen.G Esports", "Gen.G"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["Rogue", "Rogue (European Team)"]), ("LEC", 4, ["MAD Lions"]),
           ("LCS", 1, ["TSM"]), ("LCS", 2, ["FlyQuest"]), ("LCS", 3, ["Team Liquid"]),
           ("PCS", 1, ["Machi Esports"]), ("PCS", 2, ["PSG Talon"]),
           ("CBLOL", 1, ["INTZ"]), ("LCO", 1, ["Legacy Esports"]), ("LLA", 1, ["Rainbow7", "Movistar R7"]),
           ("TCL", 1, ["SuperMassive Esports", "SuperMassive eSports", "Papara SuperMassive"]),
           ("LCL", 1, ["Unicorns Of Love", "Unicorns of Love", "Unicorns of Love.CIS"]), ("LJL", 1, ["V3 Esports"])],
    2021: [("LCK", 1, ["DWG KIA", "DAMWON Gaming"]), ("LCK", 2, ["Gen.G Esports", "Gen.G"]), ("LCK", 3, ["T1"]),
           ("LCK", 4, ["Hanwha Life Esports"]),
           ("LPL", 1, ["EDward Gaming"]), ("LPL", 2, ["FunPlus Phoenix"]), ("LPL", 3, ["Royal Never Give Up"]),
           ("LPL", 4, ["LNG Esports"]),
           ("LEC", 1, ["MAD Lions"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["Rogue", "Rogue (European Team)"]),
           ("LCS", 1, ["100 Thieves"]), ("LCS", 2, ["Team Liquid"]), ("LCS", 3, ["Cloud9"]),
           ("PCS", 1, ["PSG Talon"]), ("PCS", 2, ["Beyond Gaming"]),
           ("LJL", 1, ["DetonatioN FocusMe", "Detonation FocusMe"]), ("TCL", 1, ["Galatasaray Esports"]),
           ("LLA", 1, ["Infinity Esports", "Infinity"]), ("LCO", 1, ["Peace", "PEACE (Oceanic Team)"]),
           ("CBLOL", 1, ["RED Canids", "RED Kalunga"]), ("LCL", 1, ["Unicorns Of Love", "Unicorns of Love", "Unicorns of Love.CIS"])],
    2022: [("LPL", 1, ["JD Gaming"]), ("LPL", 2, ["Top Esports"]), ("LPL", 3, ["EDward Gaming"]),
           ("LPL", 4, ["Royal Never Give Up"]),
           ("LCK", 1, ["Gen.G Esports", "Gen.G"]), ("LCK", 2, ["T1"]), ("LCK", 3, ["DWG KIA", "DAMWON Gaming"]),
           ("LCK", 4, ["DRX"]),
           ("LEC", 1, ["Rogue", "Rogue (European Team)"]), ("LEC", 2, ["G2 Esports"]), ("LEC", 3, ["Fnatic"]), ("LEC", 4, ["MAD Lions"]),
           ("LCS", 1, ["Cloud9"]), ("LCS", 2, ["100 Thieves"]), ("LCS", 3, ["Evil Geniuses", "Evil Geniuses.NA"]),
           ("PCS", 1, ["CTBC Flying Oyster"]), ("PCS", 2, ["Beyond Gaming"]),
           ("VCS", 1, ["GAM Esports"]), ("VCS", 2, ["Saigon Buffalo"]),
           ("LJL", 1, ["DetonatioN FocusMe", "Detonation FocusMe"]),
           ("LCO", 1, ["Chiefs Esports Club", "Chief Esports Club"]),
           ("TCL", 1, ["İstanbul Wildcats", "Istanbul Wildcats"]), ("LLA", 1, ["Isurus"]), ("CBLOL", 1, ["LOUD"])],
    2023: [("LPL", 1, ["JD Gaming"]), ("LPL", 2, ["Bilibili Gaming"]), ("LPL", 3, ["LNG Esports"]),
           ("LPL", 4, ["Weibo Gaming"]),
           ("LCK", 1, ["Gen.G Esports", "Gen.G"]), ("LCK", 2, ["T1"]), ("LCK", 3, ["KT Rolster"]),
           ("LCK", 4, ["Dplus KIA", "Dplus"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["MAD Lions"]), ("LEC", 4, ["Team BDS"]),
           ("LCS", 1, ["NRG"]), ("LCS", 2, ["Cloud9"]), ("LCS", 3, ["Team Liquid"]),
           ("PCS", 1, ["PSG Talon"]), ("PCS", 2, ["CTBC Flying Oyster"]),
           ("VCS", 1, ["GAM Esports"]), ("VCS", 2, ["Team Whales"]),
           ("LLA", 1, ["Rainbow7", "Movistar R7"]), ("CBLOL", 1, ["LOUD"]), ("LJL", 1, ["DetonatioN FocusMe", "Detonation FocusMe"])],
    2024: [("LCK", 1, ["Hanwha Life Esports"]), ("LCK", 2, ["Gen.G Esports", "Gen.G"]), ("LCK", 3, ["Dplus KIA", "Dplus"]),
           ("LCK", 4, ["T1"]),
           ("LPL", 1, ["Bilibili Gaming"]), ("LPL", 2, ["Top Esports"]), ("LPL", 3, ["LNG Esports"]),
           ("LPL", 4, ["Weibo Gaming"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["MAD Lions KOI", "MAD Lions"]),
           ("LCS", 1, ["FlyQuest"]), ("LCS", 2, ["Team Liquid"]), ("LCS", 3, ["100 Thieves"]),
           ("PCS", 1, ["PSG Talon"]), ("PCS", 2, ["SoftBank HAWKS gaming", "Fukuoka SoftBank HAWKS Gaming"]),
           ("VCS", 1, ["GAM Esports"]), ("VCS", 2, ["Vikings Esports", "Vikings Esports (2023 Vietnamese Team)"]),
           ("LLA", 1, ["Rainbow7", "Movistar R7"]), ("CBLOL", 1, ["paiN Gaming"])],
    2025: [("LCK", 1, ["Gen.G Esports", "Gen.G"]), ("LCK", 2, ["Hanwha Life Esports"]), ("LCK", 3, ["KT Rolster"]),
           ("LCK", 4, ["T1"]),
           ("LPL", 1, ["Bilibili Gaming"]), ("LPL", 2, ["Anyone's Legend"]), ("LPL", 3, ["Top Esports"]),
           ("LPL", 4, ["Invictus Gaming"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Movistar KOI", "MAD Lions KOI"]), ("LEC", 3, ["Fnatic"]),
           ("LTA", 1, ["FlyQuest"]), ("LTA", 2, ["Vivo Keyd Stars", "Keyd Stars"]), ("LTA", 3, ["100 Thieves"]),
           ("LCP", 1, ["CTBC Flying Oyster"]), ("LCP", 2, ["Team Secret Whales", "Secret Whales"]),
           ("LCP", 3, ["PSG Talon"])],
    # The LTA split back into the LCS and CBLOL for 2026, and Worlds grew to 19 teams.
    2026: [("LCK", 1, ["Gen.G Esports", "Gen.G"]), ("LCK", 2, ["Hanwha Life Esports"]), ("LCK", 3, ["T1"]),
           ("LCK", 4, ["Dplus KIA", "Dplus"]),
           ("LPL", 1, ["Anyone's Legend"]), ("LPL", 2, ["Bilibili Gaming"]), ("LPL", 3, ["Top Esports"]),
           ("LPL", 4, ["Invictus Gaming"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Movistar KOI", "MAD Lions KOI"]), ("LEC", 3, ["Karmine Corp"]),
           ("LCS", 1, ["Team Liquid"]), ("LCS", 2, ["LYON", "Lyon", "LYON (2024 American Team)"]), ("LCS", 3, ["Cloud9"]),
           ("LCP", 1, ["Team Secret Whales", "Secret Whales"]), ("LCP", 2, ["CTBC Flying Oyster"]),
           ("LCP", 3, ["MVK Esports"]),
           ("CBLOL", 1, ["LOS", "LØS"]), ("CBLOL", 2, ["FURIA"])],
}
REGION = {"LCK": "LCK", "LPL": "LPL", "LEC": "LEC", "LCS": "LCS/LTA", "LTA": "LCS/LTA",
          "PCS": "PCS/LCP", "LCP": "PCS/LCP", "VCS": "VCS"}
# Teams from outside a major region that held a major region's seed: 2025's LTA #2 is
# Brazilian. The page's "Majors only" view leaves their games out.
NON_MAJOR_TEAMS = ["Vivo Keyd Stars"]


def due(event, year, payload):
    """Is a scheduled refresh due? Not once `year` is in the payload's `complete` with its
    matches in it: the bracket is played out, and every further run would only spend
    another site's requests to learn nothing. A run by hand always is."""
    if event != "schedule":
        return True
    return not (year in (payload.get("complete") or [])
                and any(m.get("y") == year for m in payload.get("matches") or []))


def cache_path(y):
    return os.path.join(CACHE, f"lp-{y}.json")


def query(client, y):
    """Every MatchSchedule row of year `y`'s Worlds, paged 500 at a time (Cargo's cap)."""
    rows, offset = [], 0
    while True:
        d = client.json(API, {"action": "cargoquery", "tables": "MatchSchedule", "fields": FIELDS,
                              "where": f'OverviewPage LIKE "{y} Season World Championship/%"',
                              "order_by": "DateTime_UTC,MatchId", "limit": "500",
                              "offset": str(offset)}, mediawiki=True)
        page = [r["title"] for r in d.get("cargoquery") or []]
        rows += page
        if len(page) < 500:
            return rows
        offset += 500


def fetch(years=(), client=None):
    """Queries every year of `years` (all of them when none are named), and any other year
    the cache does not have yet, so a daily refresh asks Leaguepedia once."""
    os.makedirs(CACHE, exist_ok=True)
    client = client or polite.Client(SOURCE, min_interval=10, budget=900, base=60)
    want = [y for y in sorted(SEEDS) if not years or y in years or not os.path.exists(cache_path(y))]
    for y in want:
        rows = query(client, y)
        if not rows:
            raise SystemExit(f"{y}: Leaguepedia has no Worlds series for this year (is the event named "
                             f"'{y} Season World Championship/...'?)")
        with open(cache_path(y), "w", encoding="utf-8") as f:
            json.dump(rows, f)
        print(f"{y}: {len(rows)} series", flush=True)


def matches(y):
    """The year's series from the cache: decided ones as dicts, undecided as pending."""
    with open(cache_path(y), encoding="utf-8") as f:
        rows = json.load(f)
    out = []
    for r in rows:
        event = r["OverviewPage"].split("/", 1)[1] if "/" in r["OverviewPage"] else ""
        if event in NOT_WORLDS:
            continue
        if event not in EVENTS:
            raise SystemExit(f"{y}: unknown event {r['OverviewPage']!r}; add it to EVENTS or NOT_WORLDS")
        tab = r.get("Tab") or ""
        if not TAB.match(tab):
            raise SystemExit(f"{y}: unknown round {tab!r} in {r['OverviewPage']!r}; map it in stage()")
        # A decided series names its winner. A live one (a Bo5 at 1-1) and an undrawn one
        # ("TBD") do not, and wait for a later refresh.
        if r.get("Winner") not in ("1", "2"):
            out.append(dict(pending=True))
            continue
        out.append(dict(t1=r["Team1"].strip(), t2=r["Team2"].strip(), s=[r["Team1Score"], r["Team2Score"]],
                        ts=r.get("MatchId") or r.get("DateTime UTC"), st=stage(y, event, tab)))
    return out


def build():
    lookup = {}
    for y, rows in SEEDS.items():
        for lg, s, names in rows:
            for n in names:
                lookup[(y, n.lower())] = (lg, s, names[0])
    seen, out, unknown, pending = set(), [], collections.Counter(), collections.Counter()
    for y in sorted(SEEDS):
        page = f"{y} Worlds"
        for m in matches(y):
            if m.get("pending"):
                pending[y] += 1
                continue
            if len(m["s"]) != 2 or not all(x.isdigit() for x in m["s"]):
                raise SystemExit(f"{page}: unreadable score {m}")
            a, b = (int(x) for x in m["s"])
            if a + b == 0:
                raise SystemExit(f"{page}: unplayed match {m}")
            key = (y, m["ts"], frozenset((m["t1"], m["t2"])))
            if key in seen:
                continue
            seen.add(key)
            ra, rb = lookup.get((y, m["t1"].lower())), lookup.get((y, m["t2"].lower()))
            for t, r in ((m["t1"], ra), (m["t2"], rb)):
                if not r:
                    unknown[(y, t)] += 1
            if ra and rb:
                out.append(dict(y=y, st=m["st"], a=ra[2], al=ra[0], ar=REGION.get(ra[0], "Wildcard"), aseed=ra[1], ag=a,
                                b=rb[2], bl=rb[0], br=REGION.get(rb[0], "Wildcard"), bseed=rb[1], bg=b))
    if unknown:
        raise SystemExit(f"teams with no seed: {dict(unknown)}")
    present = {(m["y"], m["a"]) for m in out} | {(m["y"], m["b"]) for m in out}
    # A Worlds still being played may have a seed that has not played yet (the Swiss
    # teams sit out the Play-In); a finished one may not.
    missing = [(y, n[0]) for y, rows in SEEDS.items() for _, _, n in rows
               if (y, n[0]) not in present and not pending[y]]
    if missing:
        raise SystemExit(f"seeded teams with no match: {missing}")
    complete = sorted(y for y in SEEDS if not pending[y])
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"source": SOURCE, "sourceUrl": source_url(), "nonMajorTeams": NON_MAJOR_TEAMS, "complete": complete,
                   "matches": out}, f, ensure_ascii=False, separators=(",", ":"))
    games = collections.Counter()
    for m in out:
        games[m["y"]] += m["ag"] + m["bg"]
    print(f"{len(out)} series, games per year {dict(sorted(games.items()))}, "
          f"still to play {dict(sorted(pending.items()))} -> {OUT}")


def annotate(cmd, message):
    """On a runner, the reason as a GitHub annotation. The Actions log needs a sign-in to
    read even on a public repo; annotations do not, and the pipeline alert links the run."""
    if os.environ.get("GITHUB_ACTIONS") == "true":
        text = str(message).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::error title=worlds.py {cmd}::{text}", flush=True)


def main(argv):
    cmd, years = (argv[0] if argv else "build"), {int(a) for a in argv[1:]}
    # The daily refresh names the current year, so a Worlds nobody has set up yet
    # fails here with what to do, rather than refreshing nothing in silence.
    unset = sorted(y for y in years if y not in SEEDS)
    if unset:
        raise SystemExit(f"{unset}: no SEEDS yet. Write them from the year's Worlds Qualification page "
                         "(Leaguepedia or Liquipedia), and add the year to SEED_YEARS in derive.js")
    if cmd == "due":
        # The workflow's gate: due=true|false to $GITHUB_OUTPUT, off the payload it took.
        try:
            with open(OUT, encoding="utf-8") as f:
                payload = json.load(f)
        except FileNotFoundError:
            payload = {}
        ok = all(due(os.environ.get("EVENT", ""), y, payload) for y in years)
        print("due" if ok else f"{sorted(years)} already complete; nothing to do")
        out = os.environ.get("GITHUB_OUTPUT")
        if out:
            with open(out, "a", encoding="utf-8") as f:
                f.write(f"due={'true' if ok else 'false'}\n")
        return
    fetch(years) if cmd == "fetch" else build()


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except polite.TryLater as e:
        print(e, file=sys.stderr)
        polite.notice("worlds.py: stopping for today", e)
        sys.exit(EX_TEMPFAIL)
    except SystemExit as e:
        if isinstance(e.code, str):
            annotate(sys.argv[1] if len(sys.argv) > 1 else "build", e.code)
        raise
    except Exception as e:
        annotate(sys.argv[1] if len(sys.argv) > 1 else "build", f"{type(e).__name__}: {e}")
        raise
