"""Is this LoL Stats refresh run due? Prints `due=true|false` to $GITHUB_OUTPUT.

The monthly refresh runs on the 15th and retries daily through the 28th, because Google
Drive caps downloads of a file per day (see harvest.py, EX_TEMPFAIL). A retry is only
due while the month has no build from the 15th on: a payload's `built` is the date it
was rebuilt, and the index lists every year's. A run by hand, or the 15th itself, is
always due.

    EVENT=schedule python -I lolstats/tools/refresh_due.py
"""
import datetime
import json
import os
import sys

INDEX = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                     "..", "..", "webapp", "public", "data", "lol-champs-index.json")
FIRST_DAY = 15   # the cron's first day; the retries come after it
LAST_DAY = 28    # the cron's last day: the only scheduled run that goes red on the quota


def due(event, today, index):
    if event != "schedule" or today.day <= FIRST_DAY:
        return True
    since = today.replace(day=FIRST_DAY).isoformat()
    built = [y.get("built") or "" for y in index.get("years") or []]
    return not any(b >= since for b in built)


def main():
    try:
        with open(INDEX, encoding="utf-8") as f:
            index = json.load(f)
    except FileNotFoundError:
        index = {}
    ok = due(os.environ.get("EVENT", ""), datetime.datetime.now(datetime.timezone.utc).date(), index)
    print("due" if ok else f"already refreshed since the {FIRST_DAY}th; nothing to do")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as f:
            f.write(f"due={'true' if ok else 'false'}\n")


if __name__ == "__main__":
    sys.exit(main())
