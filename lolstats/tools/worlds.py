"""Worlds results for LoL Stats' Seeds tab, from Liquipedia.

    python -I lolstats/tools/worlds.py fetch    # ~9 min: renders each stage page (Liquipedia's parse limit is 1 per 30s)
    python -I lolstats/tools/worlds.py build    # cache -> webapp/public/data/lol-worlds.json

WHY LIQUIPEDIA AND NOT ORACLE'S ELIXIR: the seeds tab splits Play-In from the main
event, and Oracle's Elixir carries no stage marker on Worlds games (it also files the
regional qualifiers under Worlds; make_data.py has to strip them). Leaguepedia's API
answers this harvester with a rate-limit error and its pages with a Cloudflare
challenge, so Liquipedia it is.

WHY RENDERED HTML: from 2022 on, Liquipedia's match pages hold `{{ApiMap|matchid=...}}`
in place of each game, filled from Riot's API at render time, so the wikitext has no
scores. `action=parse` renders a whole stage page; each match's popup carries both team
names, the series score and the start time (used to tell a double round-robin's two
meetings apart). A page with ONE match (2025's Play-In, T1 vs IG) renders without the
popup wrapper, hence the fallback in `matches`.

The SEEDS table is hand-written from each year's Qualification page (Liquipedia lists
the qualifying path, not the seed). Every rendered team must resolve to a seed, and
every seeded team must appear in a match, or the build fails.
"""
import collections
import glob
import gzip
import html as H
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "lolstats", "tools", "cache", "worlds")
OUT = os.path.join(ROOT, "webapp", "public", "data", "lol-worlds.json")
API = "https://liquipedia.net/leagueoflegends/api.php"
UA = "ForrestGames-LoLStats/1.0 (+https://forry4.github.io; Worlds seed records)"

PAGES = ["2020/Play-In", "2020/Group_Stage", "2020/Bracket_Stage",
         "2021/Play-In", "2021/Group_Stage", "2021/Knockout_Stage",
         "2022/Play-In", "2022/Group_Stage", "2022/Knockout_Stage",
         "2023/Play-In", "2023/Swiss_Stage", "2023/Knockout_Stage",
         "2024/Play-In", "2024/Swiss_Stage", "2024/Knockout_Stage",
         "2025/Play-In", "2025/Swiss_Stage", "2025/Knockout_Stage"]
STAGE = {"Play-In": "Play-In", "Group_Stage": "Groups", "Swiss_Stage": "Swiss",
         "Bracket_Stage": "Knockout", "Knockout_Stage": "Knockout"}

# (league, seed, [the name Liquipedia renders, then any alias]). LTA (2025) took the
# LCS's slots and LCP (2025) the PCS's; the page groups them so. 2023's Team BDS were
# LEC #4 through the Worlds Qualifying Series, which is not counted as Worlds.
SEEDS = {
    2020: [("LPL", 1, ["Top Esports"]), ("LPL", 2, ["JD Gaming"]), ("LPL", 3, ["Suning"]), ("LPL", 4, ["LGD Gaming"]),
           ("LCK", 1, ["DAMWON Gaming"]), ("LCK", 2, ["DRX"]), ("LCK", 3, ["Gen.G Esports", "Gen.G"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["Rogue"]), ("LEC", 4, ["MAD Lions"]),
           ("LCS", 1, ["TSM"]), ("LCS", 2, ["FlyQuest"]), ("LCS", 3, ["Team Liquid"]),
           ("PCS", 1, ["Machi Esports"]), ("PCS", 2, ["PSG Talon"]),
           ("CBLOL", 1, ["INTZ"]), ("LCO", 1, ["Legacy Esports"]), ("LLA", 1, ["Rainbow7"]),
           ("TCL", 1, ["SuperMassive Esports", "SuperMassive eSports"]),
           ("LCL", 1, ["Unicorns Of Love", "Unicorns of Love"]), ("LJL", 1, ["V3 Esports"])],
    2021: [("LCK", 1, ["DWG KIA", "DAMWON Gaming"]), ("LCK", 2, ["Gen.G Esports", "Gen.G"]), ("LCK", 3, ["T1"]),
           ("LCK", 4, ["Hanwha Life Esports"]),
           ("LPL", 1, ["EDward Gaming"]), ("LPL", 2, ["FunPlus Phoenix"]), ("LPL", 3, ["Royal Never Give Up"]),
           ("LPL", 4, ["LNG Esports"]),
           ("LEC", 1, ["MAD Lions"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["Rogue"]),
           ("LCS", 1, ["100 Thieves"]), ("LCS", 2, ["Team Liquid"]), ("LCS", 3, ["Cloud9"]),
           ("PCS", 1, ["PSG Talon"]), ("PCS", 2, ["Beyond Gaming"]),
           ("LJL", 1, ["DetonatioN FocusMe", "Detonation FocusMe"]), ("TCL", 1, ["Galatasaray Esports"]),
           ("LLA", 1, ["Infinity Esports", "Infinity"]), ("LCO", 1, ["Peace"]),
           ("CBLOL", 1, ["RED Canids", "RED Kalunga"]), ("LCL", 1, ["Unicorns Of Love", "Unicorns of Love"])],
    2022: [("LPL", 1, ["JD Gaming"]), ("LPL", 2, ["Top Esports"]), ("LPL", 3, ["EDward Gaming"]),
           ("LPL", 4, ["Royal Never Give Up"]),
           ("LCK", 1, ["Gen.G Esports", "Gen.G"]), ("LCK", 2, ["T1"]), ("LCK", 3, ["DWG KIA", "DAMWON Gaming"]),
           ("LCK", 4, ["DRX"]),
           ("LEC", 1, ["Rogue"]), ("LEC", 2, ["G2 Esports"]), ("LEC", 3, ["Fnatic"]), ("LEC", 4, ["MAD Lions"]),
           ("LCS", 1, ["Cloud9"]), ("LCS", 2, ["100 Thieves"]), ("LCS", 3, ["Evil Geniuses"]),
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
           ("LLA", 1, ["Rainbow7"]), ("CBLOL", 1, ["LOUD"]), ("LJL", 1, ["DetonatioN FocusMe", "Detonation FocusMe"])],
    2024: [("LCK", 1, ["Hanwha Life Esports"]), ("LCK", 2, ["Gen.G Esports", "Gen.G"]), ("LCK", 3, ["Dplus KIA", "Dplus"]),
           ("LCK", 4, ["T1"]),
           ("LPL", 1, ["Bilibili Gaming"]), ("LPL", 2, ["Top Esports"]), ("LPL", 3, ["LNG Esports"]),
           ("LPL", 4, ["Weibo Gaming"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Fnatic"]), ("LEC", 3, ["MAD Lions KOI", "MAD Lions"]),
           ("LCS", 1, ["FlyQuest"]), ("LCS", 2, ["Team Liquid"]), ("LCS", 3, ["100 Thieves"]),
           ("PCS", 1, ["PSG Talon"]), ("PCS", 2, ["SoftBank HAWKS gaming", "Fukuoka SoftBank HAWKS Gaming"]),
           ("VCS", 1, ["GAM Esports"]), ("VCS", 2, ["Vikings Esports"]),
           ("LLA", 1, ["Rainbow7"]), ("CBLOL", 1, ["paiN Gaming"])],
    2025: [("LCK", 1, ["Gen.G Esports", "Gen.G"]), ("LCK", 2, ["Hanwha Life Esports"]), ("LCK", 3, ["KT Rolster"]),
           ("LCK", 4, ["T1"]),
           ("LPL", 1, ["Bilibili Gaming"]), ("LPL", 2, ["Anyone's Legend"]), ("LPL", 3, ["Top Esports"]),
           ("LPL", 4, ["Invictus Gaming"]),
           ("LEC", 1, ["G2 Esports"]), ("LEC", 2, ["Movistar KOI", "MAD Lions KOI"]), ("LEC", 3, ["Fnatic"]),
           ("LTA", 1, ["FlyQuest"]), ("LTA", 2, ["Vivo Keyd Stars", "Keyd Stars"]), ("LTA", 3, ["100 Thieves"]),
           ("LCP", 1, ["CTBC Flying Oyster"]), ("LCP", 2, ["Team Secret Whales", "Secret Whales"]),
           ("LCP", 3, ["PSG Talon"])],
}
REGION = {"LCK": "LCK", "LPL": "LPL", "LEC": "LEC", "LCS": "LCS/LTA", "LTA": "LCS/LTA",
          "PCS": "PCS/LCP", "LCP": "PCS/LCP", "VCS": "VCS"}
# Teams from outside a major region that held a major region's seed: 2025's LTA #2 is
# Brazilian. The page's "Majors only" view leaves their games out.
NON_MAJOR_TEAMS = ["Vivo Keyd Stars"]


def get(params):
    url = API + "?" + urllib.parse.urlencode({**params, "format": "json"})
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
    with urllib.request.urlopen(req, timeout=120) as r:
        b = r.read()
        if r.headers.get("Content-Encoding") == "gzip":
            b = gzip.decompress(b)
    return json.loads(b)


def fetch():
    os.makedirs(CACHE, exist_ok=True)
    for i, page in enumerate(PAGES):
        if i:
            time.sleep(31)   # Liquipedia's API terms: one parse request per 30 seconds
        d = get({"action": "parse", "page": f"World_Championship/{page}", "prop": "text"})
        if "parse" not in d:
            raise SystemExit(f"{page}: {d.get('error')}")
        dest = os.path.join(CACHE, page.replace("/", "_") + ".json")
        with open(dest, "w", encoding="utf-8") as f:
            json.dump(d, f)
        print(f"{page}: {os.path.getsize(dest) // 1000} KB", flush=True)


def matches(path):
    with open(path, encoding="utf-8") as f:
        h = json.load(f)["parse"]["text"]["*"]
    out = []
    chunks = h.split("brkts-match-info-popup")[1:] if "brkts-match-info-popup" in h else [h]
    for chunk in chunks:
        hi = chunk.find('class="match-info-header"')
        if hi < 0:
            continue
        ts = re.search(r'data-timestamp="(\d+)"', chunk[:hi])
        body = chunk[hi:hi + 20000]
        names = re.findall(r'<div class="team-name">(?:<a[^>]*>)?([^<]+)', body)
        sc = re.search(r'scoreholder-upper">(.*?</span>)</span>', body, re.S)
        if not sc or len(names) < 2:
            continue
        scores = re.findall(r'scoreholder-score[^"]*">([^<]*)<', sc.group(1))
        out.append(dict(t1=H.unescape(names[0]).strip(), t2=H.unescape(names[1]).strip(), s=scores,
                        ts=int(ts.group(1)) if ts else None))
    return out


def build():
    lookup = {}
    for y, rows in SEEDS.items():
        for lg, s, names in rows:
            for n in names:
                lookup[(y, n.lower())] = (lg, s, names[0])
    seen, out, unknown = set(), [], collections.Counter()
    for page in PAGES:
        y, stage = int(page[:4]), STAGE[page[5:]]
        path = os.path.join(CACHE, page.replace("/", "_") + ".json")
        for m in matches(path):
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
                out.append(dict(y=y, st=stage, a=ra[2], al=ra[0], ar=REGION.get(ra[0], "Wildcard"), aseed=ra[1], ag=a,
                                b=rb[2], bl=rb[0], br=REGION.get(rb[0], "Wildcard"), bseed=rb[1], bg=b))
    if unknown:
        raise SystemExit(f"teams with no seed: {dict(unknown)}")
    present = {(m["y"], m["a"]) for m in out} | {(m["y"], m["b"]) for m in out}
    missing = [(y, n[0]) for y, rows in SEEDS.items() for _, _, n in rows if (y, n[0]) not in present]
    if missing:
        raise SystemExit(f"seeded teams with no match: {missing}")
    with open(OUT, "w", encoding="utf-8") as f:
        json.dump({"source": "Liquipedia", "nonMajorTeams": NON_MAJOR_TEAMS, "matches": out}, f,
                  ensure_ascii=False, separators=(",", ":"))
    games = collections.Counter()
    for m in out:
        games[m["y"]] += m["ag"] + m["bg"]
    print(f"{len(out)} series, games per year {dict(sorted(games.items()))} -> {OUT}")


if __name__ == "__main__":
    {"fetch": fetch, "build": build}[sys.argv[1] if len(sys.argv) > 1 else "build"]()
