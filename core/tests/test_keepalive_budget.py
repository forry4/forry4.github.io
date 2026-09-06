"""The keepalive warm window is a BUDGET, and blowing it takes the site down.

Render's free tier grants **750 instance-hours per calendar month per workspace**,
shared across every free service, and exhausting them SUSPENDS the service until
the next month. A month is ~730 hours, so "just keep it warm all the time" spends
essentially the entire allowance — and takes the backend fully offline for the rest
of the month the moment a second free service exists, or the moment a long month
and a restart or two push it over.

That makes the warm window the one number in the keepalive that fails EXPENSIVELY
and SILENTLY in the widening direction: a wider window looks strictly better right
up until the service is suspended, and nothing in the workflow, the Worker or the
app reports it. The narrowing direction is self-reporting — the morning is cold and
a player says so — which is how this whole area came to be looked at.

Two pingers, two schedulers, one target. They must also agree on WHICH backend they
are warming: a URL changed in one and not the other leaves a workflow that is green
while warming nothing, which is the same silence the dead cron band had.

Read as TEXT, never imported: `core/` may not depend on a feature and that holds for
its tests, and neither of these files is Python at all.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "keepalive-worker" / "src" / "index.js"
WRANGLER = ROOT / "keepalive-worker" / "wrangler.jsonc"
WORKFLOW = ROOT / ".github" / "workflows" / "keepalive.yml"

# 750 is the hard cap. Hold the window to a level that leaves room for the month's
# restarts, deploys and the odd manual wake, rather than betting on the arithmetic
# being exactly right.
RENDER_FREE_HOURS_PER_MONTH = 750
MAX_BUDGETED_HOURS = 640
LONGEST_MONTH_DAYS = 31


def _const(name: str) -> int:
    m = re.search(rf"^const {name} = (\d+);", WORKER.read_text(encoding="utf-8"), re.M)
    assert m, f"{name} is gone from {WORKER.name} — the budget guard cannot read it"
    return int(m.group(1))


def _warm_hours_per_day() -> int:
    start, end = _const("WARM_FROM_UTC_HOUR"), _const("WARM_UNTIL_UTC_HOUR")
    # The window wraps midnight (13:00 -> 06:59), which is the whole reason the
    # Worker tests `h >= start || h < end` rather than a plain range.
    return sum(1 for h in range(24) if (h >= start or h < end))


def test_the_warm_window_stays_inside_renders_free_instance_hours():
    per_day = _warm_hours_per_day()
    per_month = per_day * LONGEST_MONTH_DAYS
    assert per_month <= MAX_BUDGETED_HOURS, (
        f"the Worker warms {per_day}h/day = {per_month}h in a {LONGEST_MONTH_DAYS}-day "
        f"month, over the {MAX_BUDGETED_HOURS}h budget and closing on Render's hard "
        f"{RENDER_FREE_HOURS_PER_MONTH}h cap. Past the cap the backend is SUSPENDED for "
        f"the rest of the month — a cold morning is the cheaper failure. Narrow the "
        f"window, do not raise this number."
    )
    # ...and it has to actually cover the play window, or the guard above is
    # satisfied by warming nothing at all.
    assert per_day >= 14, f"only {per_day}h/day — that does not cover 7am-10pm local"


def test_both_pingers_warm_the_same_backend():
    url_re = re.compile(r"https://[a-z0-9.\-]*onrender\.com/health")
    worker = set(url_re.findall(WORKER.read_text(encoding="utf-8")))
    workflow = set(url_re.findall(WORKFLOW.read_text(encoding="utf-8")))
    assert worker, "the Worker pings no onrender.com/health URL at all"
    assert workflow, "the workflow pings no onrender.com/health URL at all"
    assert worker == workflow, (
        f"the Cloudflare Worker warms {sorted(worker)} and the GitHub workflow warms "
        f"{sorted(workflow)}. One of them is keeping a backend nobody uses warm, and "
        f"neither reports it."
    )


def test_the_worker_still_has_a_cron_trigger():
    # Without this the Worker deploys perfectly and simply never runs — the exact
    # shape of the GitHub outage it was added to cover for.
    src = WRANGLER.read_text(encoding="utf-8")
    crons = re.search(r'"crons"\s*:\s*\[(.*?)\]', src, re.S)
    assert crons and re.search(r'"[\d*/, \-]+"', crons.group(1)), (
        "keepalive-worker/wrangler.jsonc declares no cron trigger"
    )
