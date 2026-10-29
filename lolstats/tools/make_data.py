"""Oracle's Elixir CSVs -> the Champions tab's payload.

Writes webapp/public/data/lol-champs-<year>.json for each cached year, plus
lol-champs-index.json (which years exist, how many games each, and the newest game's
date). The page does every aggregation in the browser, so each file is just the year's
games in a compact positional form (see GAME LAYOUT below).

    python -I lolstats/tools/make_data.py            # every year in tools/cache/oe
    python -I lolstats/tools/make_data.py 2026       # rebuild just these (the index is rebuilt from all files)

WHICH GAMES COUNT (the owner's call, 2026-10-28): the four major regions' regular
seasons and playoffs, and Riot's international events.
  - LCK, LPL, LEC, LCS. In 2025 the LCS was replaced by the LTA, which merged North
    America with Brazil; only LTA North counts, plus the cross-conference "LTA" games
    in which BOTH teams are North American (the LTA N roster of that year).
  - Worlds (WLDs, Play-In included), MSI, First Stand (FST) and 2020's Mid-Season Cup
    (MSC, held instead of MSI) -- every game, including those against minor-region teams.
  - NOT the Esports World Cup (EWC: third-party, and its 2026 edition is ~460 games with
    a large lower-tier field), nor the smaller invitationals (ASI, DCGI, AC, CCWS) or
    showmatches.

GAME LAYOUT: [league, playoffs, patch, blueTeam, redTeam, winner,
              10 champions (blue top/jng/mid/bot/sup, then red),
              10 bans (blue 1-5, then red; -1 = none),
              50 stats (per player in the same order: kills, deaths, assists,
                        damage per minute, gold diff at 15 or -99999 when missing)]
league/patch/team/champion are indexes into the file's lists; winner is 0 blue, 1 red.
"""
import csv
import datetime
import glob
import json
import os
import re
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CACHE = os.path.join(ROOT, "lolstats", "tools", "cache", "oe")
OUT = os.path.join(ROOT, "webapp", "public", "data")

MAJOR = ["LCK", "LPL", "LEC", "LCS", "LTA N"]
INTERNATIONAL = ["WLDs", "MSI", "FST", "MSC"]
LEAGUES = MAJOR + ["LTA"] + INTERNATIONAL       # the order of the file's `leagues` list
POSITIONS = ["top", "jng", "mid", "bot", "sup"]
NO_GD = -99999

# Oracle's Elixir files the LCK and LPL Regional Finals (the Worlds qualifiers, weeks
# before the event) and 2023's LEC-vs-LCS Qualifying Series under "WLDs" too. Each
# year's first Play-In day separates them: an earlier "WLDs" game whose two teams both
# played in one major league that year goes back to that league as postseason; any
# other (the cross-region qualifier) is dropped. Measured against Liquipedia's brackets,
# this leaves exactly 114/121/127/110/106/84 Worlds games for 2020-2025.
# A year with Worlds games and no entry here fails the build -- add its date.
WORLDS_START = {2020: "2020-09-25", 2021: "2021-10-05", 2022: "2022-09-29", 2023: "2023-10-10",
                2024: "2024-09-25", 2025: "2025-10-14", 2026: "2026-10-15"}

# A league that parses to almost nothing means the CSV changed shape, not that the
# league stopped playing; fail the build rather than ship a hollow year. These are
# floors for a FULL year; the current year is held to a fraction of them.
FLOOR = {"LCK": 300, "LPL": 400, "LEC": 150, "LCS": 120, "LTA N": 120, "WLDs": 60}


def num(s, cast=float):
    return cast(float(s)) if s not in ("", None) else None


def build(year):
    path = os.path.join(CACHE, f"{year}.csv")
    csv.field_size_limit(1 << 30)
    rows = {}
    with open(path, encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f):
            if r["league"] in LEAGUES:
                rows.setdefault(r["gameid"], []).append(r)

    lta_north = {r["teamname"] for g in rows.values() for r in g if r["league"] == "LTA N"}
    roster = {}
    for g in rows.values():
        if g[0]["league"] in MAJOR:
            roster.setdefault(g[0]["league"], set()).update(r["teamname"] for r in g)
    if any(g[0]["league"] == "WLDs" for g in rows.values()) and year not in WORLDS_START:
        raise SystemExit(f"{year}: Worlds games but no WORLDS_START date; add the first Play-In day")
    champs, teams, patches = set(), set(), set()
    games, skipped, requalified = [], {}, {}
    for gid, g in rows.items():
        league = g[0]["league"]
        team_rows = {r["side"]: r for r in g if r["position"] == "team"}
        if league == "WLDs" and g[0]["date"][:10] < WORLDS_START[year]:
            pair = {r["teamname"] for r in team_rows.values()}
            home = next((lg for lg, ts in roster.items() if pair <= ts), None)
            requalified[home or "dropped"] = requalified.get(home or "dropped", 0) + 1
            if not home:
                continue
            league = home
            for r in team_rows.values():
                r["playoffs"] = "1"
        players = {(r["side"], r["position"]): r for r in g if r["position"] in POSITIONS}
        if len(team_rows) != 2 or len(players) != 10 or any(not p["champion"] for p in players.values()):
            skipped[league] = skipped.get(league, 0) + 1
            continue
        # Tournament draft never repeats a champion; two 2020 Mid-Season Cup games are
        # recorded with the same champion on both teams, so the record is wrong somewhere.
        if len({p["champion"] for p in players.values()}) != 10:
            skipped[f"{league} (repeated champion)"] = skipped.get(f"{league} (repeated champion)", 0) + 1
            continue
        if league == "LTA" and not {team_rows["Blue"]["teamname"], team_rows["Red"]["teamname"]} <= lta_north:
            continue
        games.append((gid, league, team_rows, players))
        champs.update(p["champion"] for p in players.values())
        teams.update(t["teamname"] for t in team_rows.values())
        patches.add(g[0]["patch"])
        for t in team_rows.values():
            champs.update(t[f"ban{i}"] for i in range(1, 6) if t[f"ban{i}"])

    champs, teams = sorted(champs), sorted(teams)
    patches = sorted(patches, key=lambda p: [int(x) if x.isdigit() else 0 for x in re.split(r"\D+", p or "0")])
    ci = {c: i for i, c in enumerate(champs)}
    ti = {t: i for i, t in enumerate(teams)}
    pi = {p: i for i, p in enumerate(patches)}
    li = {l: i for i, l in enumerate(LEAGUES)}

    out, per_league, last = [], {}, ""
    for gid, league, team_rows, players in sorted(games, key=lambda x: (x[3][("Blue", "top")]["date"], x[0])):
        blue, red = team_rows["Blue"], team_rows["Red"]
        order = [(s, p) for s in ("Blue", "Red") for p in POSITIONS]
        rec = [li[league], int(blue["playoffs"] or 0), pi[blue["patch"]], ti[blue["teamname"]], ti[red["teamname"]],
               0 if blue["result"] == "1" else 1]
        rec += [ci[players[k]["champion"]] for k in order]
        rec += [ci[t[f"ban{i}"]] if t[f"ban{i}"] else -1 for t in (blue, red) for i in range(1, 6)]
        for k in order:
            p = players[k]
            gd = num(p["golddiffat15"], int)
            rec += [num(p["kills"], int) or 0, num(p["deaths"], int) or 0, num(p["assists"], int) or 0,
                    num(p["dpm"], round) or 0, NO_GD if gd is None else gd]
        out.append(rec)
        per_league[league] = per_league.get(league, 0) + 1
        last = max(last, blue["date"][:10])

    current = year == datetime.date.today().year
    for lg, floor in FLOOR.items():
        have = per_league.get(lg, 0)
        if lg == "LCS" and year == 2025 or lg == "LTA N" and year != 2025:
            continue
        need = floor // 3 if current else floor
        if have < need:
            raise SystemExit(f"{year}: only {have} {lg} games (floor {need}); the CSV may have changed shape")
    if sum(skipped.values()) > 0.02 * len(out):
        raise SystemExit(f"{year}: skipped {skipped} incomplete games, more than 2% of {len(out)}")

    payload = {"year": year, "built": datetime.date.today().isoformat(), "last": last,
               "leagues": LEAGUES, "patches": patches, "teams": teams, "champs": champs, "games": out}
    os.makedirs(OUT, exist_ok=True)
    dest = os.path.join(OUT, f"lol-champs-{year}.json")
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, separators=(",", ":"))
    print(f"{year}: {len(out)} games {dict(sorted(per_league.items()))}, skipped {skipped}, "
          f"qualifiers filed as Worlds {requalified}, "
          f"{len(champs)} champions, {os.path.getsize(dest) / 1e3:.0f} KB")


def index():
    years = []
    for p in sorted(glob.glob(os.path.join(OUT, "lol-champs-[0-9][0-9][0-9][0-9].json"))):
        with open(p, encoding="utf-8") as f:
            d = json.load(f)
        years.append({"year": d["year"], "games": len(d["games"]), "last": d["last"], "built": d["built"]})
    with open(os.path.join(OUT, "lol-champs-index.json"), "w", encoding="utf-8") as f:
        json.dump({"years": years}, f, separators=(",", ":"))


def main(argv):
    years = [int(a) for a in argv] or sorted(int(os.path.basename(p)[:4]) for p in glob.glob(os.path.join(CACHE, "*.csv")))
    if not years:
        raise SystemExit("no CSVs in tools/cache/oe; run harvest.py first")
    for y in years:
        build(y)
    index()


if __name__ == "__main__":
    main(sys.argv[1:])
