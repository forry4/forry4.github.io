"""Download Oracle's Elixir match data for LoL Stats' Champions tab.

Oracle's Elixir publishes one CSV per year (every pro game, one row per player and
one per team) in a public Google Drive folder. This resolves each year's file id from
the folder listing (the ids change when a file is re-uploaded, so they are not
hard-coded) and streams the CSV to tools/cache/oe/<year>.csv (gitignored, ~80-110MB
each). make_data.py reads them from there.

    python -I lolstats/tools/harvest.py              # 2020 through the current year
    python -I lolstats/tools/harvest.py 2026         # just the given years
"""
import datetime
import html
import os
import re
import sys
import urllib.request

FOLDER = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
FIRST_YEAR = 2020
CACHE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "oe")
UA = "ForrestGames-LoLStats/1.0 (+https://forry4.github.io)"


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    return urllib.request.urlopen(req, timeout=120)


def file_ids():
    page = get(f"https://drive.google.com/embeddedfolderview?id={FOLDER}").read().decode("utf-8")
    out = {}
    for m in re.finditer(r'file/d/([A-Za-z0-9_-]+)/view[^>]*>.*?flip-entry-title">([^<]+)<', page, re.S):
        name = html.unescape(m.group(2))
        y = re.match(r"(\d{4})_LoL_esports_match_data_from_OraclesElixir\.csv$", name)
        if y:
            out[int(y.group(1))] = m.group(1)
    if not out:
        raise SystemExit("the Drive folder listing had no match-data files; its markup may have changed")
    return out


def download(year, fid):
    os.makedirs(CACHE, exist_ok=True)
    dest = os.path.join(CACHE, f"{year}.csv")
    tmp = dest + ".part"
    with get(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t") as r, open(tmp, "wb") as f:
        head = r.read(64)
        if not head.startswith(b"gameid,"):
            raise SystemExit(f"{year}: Drive did not return the CSV (got {head[:40]!r})")
        f.write(head)
        while chunk := r.read(1 << 20):
            f.write(chunk)
    os.replace(tmp, dest)
    print(f"{year}: {os.path.getsize(dest) / 1e6:.1f} MB -> {dest}")


def main(argv):
    years = [int(a) for a in argv] or list(range(FIRST_YEAR, datetime.date.today().year + 1))
    ids = file_ids()
    for y in years:
        if y not in ids:
            raise SystemExit(f"{y}: no file in the Oracle's Elixir folder")
        download(y, ids[y])


if __name__ == "__main__":
    main(sys.argv[1:])
