"""The keepalive warm window is a BUDGET, and blowing it takes the site down.

Render's free tier grants **750 instance-hours per calendar month per workspace**,
shared across every free service, and exhausting them SUSPENDS the service until
the next month. With ONE free service a 31-day month can only ever run 744h, so the
window is set JUST UNDER the cap (2026-11-14, the owner's call): 23 hours a day,
asleep for the quietest hour. What this guards is the modelled spend — the warm
hours, plus Render's 15-minute idle tail after each window close — staying under a
ceiling that leaves room for what the model cannot see (deploy overlaps, a wake in
the quiet hour). Widening to 24/7 fails here on purpose: it leaves no margin at all.

That makes the warm window the one number in the keepalive that fails EXPENSIVELY
and SILENTLY in the widening direction: nothing in the Worker or the app reports a
suspended service until it is suspended. If a SECOND free service is ever added to
the Render workspace, this budget no longer holds and the window must narrow.

The Worker is the warmer and the GitHub workflow its watchdog; they must agree on
WHICH backend: a URL changed in one and not the other leaves a watchdog that is
green while checking a backend nobody warms.

Read as TEXT, never imported: `core/` may not depend on a feature and that holds for
its tests, and neither of these files is Python at all.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKER = ROOT / "keepalive-worker" / "src" / "index.js"
WRANGLER = ROOT / "keepalive-worker" / "wrangler.jsonc"
WORKFLOW = ROOT / ".github" / "workflows" / "keepalive.yml"

# 750 is the hard cap; the modelled spend must leave ~25h of it for what the model
# does not count (deploy overlaps, a visitor waking the box in the quiet hour).
RENDER_FREE_HOURS_PER_MONTH = 750
MAX_BUDGETED_HOURS = 725
LONGEST_MONTH_DAYS = 31
# Render keeps an idle free instance up ~15 minutes after its last request.
IDLE_TAIL_HOURS = 0.25


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
    # One window close a day, each followed by the idle tail (none if never closed).
    tail = IDLE_TAIL_HOURS if per_day < 24 else 0
    per_month = (per_day + tail) * LONGEST_MONTH_DAYS
    assert per_month <= MAX_BUDGETED_HOURS, (
        f"the Worker warms {per_day}h/day = ~{per_month:.0f}h in a {LONGEST_MONTH_DAYS}-day "
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
