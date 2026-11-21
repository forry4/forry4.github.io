"""Download Oracle's Elixir match data for LoL Stats' Champions tab.

Oracle's Elixir publishes one CSV per year (every pro game, one row per player and
one per team) in a public Google Drive folder. This resolves each year's file id from
the folder listing (the ids change when a file is re-uploaded, so they are not
hard-coded) and streams the CSV to tools/cache/oe/<year>.csv (gitignored, ~80-110MB
each). make_data.py reads them from there.

    python -I lolstats/tools/harvest.py              # 2020 through the current year
    python -I lolstats/tools/harvest.py 2026         # just the given years
    python -I lolstats/tools/harvest.py --skip-missing 2026 2027   # a year not posted yet is skipped
"""
import datetime
import html
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))   # -I leaves the script dir off
import polite   # noqa: E402

FOLDER = "1gLSw0RLjBbtaNy0dgnGQDAZOHIgCe-HH"
FIRST_YEAR = 2020
CACHE = os.environ.get("LOL_OE_CACHE") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "cache", "oe")

# Drive caps how often one file may be downloaded in a day and answers past the cap with
# a 200 HTML page titled "Quota exceeded". It is not a fault of ours or of the file: the
# cap resets on its own, so it exits TEMPFAIL (sysexits' 75) and the workflow retries on
# a later day. Measured 2026-11-15, the morning after the Worlds final: every request for
# the 2026 file, whatever the URL form or User-Agent, got the quota page.
EX_TEMPFAIL = polite.EX_TEMPFAIL
# Two requests a run (the listing, then the file), so the spacing never binds; the budget
# covers a Drive 5xx or a dropped connection. The quota page is a 200 and is check_head's.
CLIENT = polite.Client("Google Drive", min_interval=2, budget=300, base=30)


class QuotaExceeded(Exception):
    pass


def check_head(year, head):
    """The first bytes of a download, or raise. Only the CSV's own header passes."""
    if head.startswith(b"gameid,"):
        return
    if b"Quota exceeded" in head:
        raise QuotaExceeded(f"{year}: Google Drive's daily download quota for this file is used up")
    raise SystemExit(f"{year}: Drive did not return the CSV (got {head[:40]!r})")


def get(url):
    return CLIENT.open(url)


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
    with get(f"https://drive.usercontent.google.com/download?id={fid}&export=download&confirm=t") as r:
        head = r.read(512)   # enough to reach the quota page's <title>
        check_head(year, head)   # before the .part exists, so a refusal leaves nothing behind
        with open(tmp, "wb") as f:
            f.write(head)
            while chunk := r.read(1 << 20):
                f.write(chunk)
    os.replace(tmp, dest)
    print(f"{year}: {os.path.getsize(dest) / 1e6:.1f} MB -> {dest}")


def main(argv):
    skip = "--skip-missing" in argv
    years = [int(a) for a in argv if a != "--skip-missing"] or list(range(FIRST_YEAR, datetime.date.today().year + 1))
    ids = file_ids()
    for y in years:
        if y not in ids:
            # A new year's file appears with its first games; January asks before then.
            if skip:
                print(f"{y}: not posted yet, skipped")
                continue
            raise SystemExit(f"{y}: no file in the Oracle's Elixir folder")
        download(y, ids[y])


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except QuotaExceeded as e:
        print(f"{e}; it resets on its own, try again later", file=sys.stderr)
        sys.exit(EX_TEMPFAIL)
    except polite.TryLater as e:
        print(e, file=sys.stderr)
        polite.notice("harvest.py: stopping for today", e)
        sys.exit(EX_TEMPFAIL)
