"""worlds.py over Leaguepedia's MatchSchedule rows: what a row means (stage, pending,
events that are not Worlds), how a refresh asks (one query per year, settled years from the
cache), when a scheduled run is due, and the exit codes the workflow branches on. The
network is stubbed; polite.py has its own tests for how a request is made."""
import importlib.util
import json
import os
import subprocess
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")
spec = importlib.util.spec_from_file_location("worlds", os.path.join(TOOLS, "worlds.py"))
worlds = importlib.util.module_from_spec(spec)
spec.loader.exec_module(worlds)


def row(event, tab, t1="Gen.G", t2="T1", s1="3", s2="1", winner="1", mid="M1"):
    return {"OverviewPage": f"2026 Season World Championship/{event}", "Tab": tab, "Team1": t1,
            "Team2": t2, "Team1Score": s1, "Team2Score": s2, "Winner": winner,
            "DateTime UTC": "2026-11-14 19:00:00", "BestOf": "5", "MatchId": mid, "FF": ""}


@pytest.fixture
def cache(tmp_path, monkeypatch):
    monkeypatch.setattr(worlds, "CACHE", str(tmp_path))

    def put(y, rows):
        with open(worlds.cache_path(y), "w", encoding="utf-8") as f:
            json.dump(rows, f)
    return put


@pytest.mark.parametrize("y,event,tab,want", [
    (2026, "Play-In", "Round 2", "Play-In"),
    (2026, "Main Event", "Round 3", "Swiss"),
    (2022, "Main Event", "Day 4", "Groups"),
    (2026, "Main Event", "Quarterfinals", "Knockout"),
    (2020, "Main Event", "Finals", "Knockout"),
    (2023, "Main Event", "Tiebreakers", "Swiss"),
])
def test_each_round_lands_on_the_stage_the_payload_has_always_used(y, event, tab, want):
    assert worlds.stage(y, event, tab) == want


def test_an_undecided_series_is_pending_and_the_qualifying_series_is_not_worlds(cache):
    cache(2026, [row("Main Event", "Finals"),
                 row("Main Event", "Semifinals", t2="TBD", s1="", s2="", winner="", mid="M2"),
                 row("Qualifying Series", "Round 1", mid="M3")])
    got = worlds.matches(2026)
    assert got[0] == dict(t1="Gen.G", t2="T1", s=["3", "1"], ts="M1", st="Knockout")
    assert got[1] == dict(pending=True) and len(got) == 2


@pytest.mark.parametrize("bad", [row("Last Chance Qualifier", "Round 1"), row("Main Event", "Wildcard Day")])
def test_an_event_or_round_nobody_mapped_fails_rather_than_being_guessed(cache, bad):
    cache(2026, [bad])
    with pytest.raises(SystemExit, match="unknown"):
        worlds.matches(2026)


class FakeClient:
    def __init__(self, answers):
        self.answers, self.asked = answers, []

    def json(self, url, params=None, mediawiki=False):
        self.asked.append(params)
        assert mediawiki and url == worlds.API
        return {"cargoquery": [{"title": r} for r in self.answers.pop(0)]}


def test_a_refresh_asks_once_for_the_current_year_and_reuses_the_settled_ones(cache):
    for y in worlds.SEEDS:
        if y != 2026:
            cache(y, [row("Main Event", "Finals")])
    c = FakeClient([[row("Main Event", "Finals")]])
    worlds.fetch({2026}, client=c)
    assert len(c.asked) == 1 and '"2026 Season World Championship/%"' in c.asked[0]["where"]


def test_a_full_year_is_paged_rather_than_cut_at_cargos_500(cache):
    c = FakeClient([[row("Main Event", "Round 1", mid=f"A{i}") for i in range(500)],
                    [row("Main Event", "Finals", mid="B")]])
    rows = worlds.query(c, 2026)
    assert len(rows) == 501 and [p["offset"] for p in c.asked] == ["0", "500"]


def _payload(complete, years):
    return {"complete": complete, "matches": [{"y": y} for y in years]}


def test_a_scheduled_run_stops_once_the_year_is_complete():
    assert not worlds.due("schedule", 2026, _payload([2025, 2026], [2025, 2026]))
    assert worlds.due("schedule", 2026, _payload([2025], [2025, 2026]))   # still being played
    assert worlds.due("workflow_dispatch", 2026, _payload([2026], [2026]))   # by hand: always


def test_a_year_with_no_matches_yet_is_not_complete():
    # build() puts a year with nothing pending in `complete` even before its first match
    # is in, which must not switch the refresh off before Worlds has begun.
    assert worlds.due("schedule", 2026, _payload([2025, 2026], [2025]))


def _run(args, stub=""):
    script = f"""
import io, sys, runpy, email.message, urllib.error, urllib.request
sys.argv = ["worlds.py", *{args!r}]
{stub}
runpy.run_path({os.path.join(TOOLS, "worlds.py")!r}, run_name="__main__")
"""
    return subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                          env={**os.environ, "GITHUB_ACTIONS": "true"})


def test_a_block_exits_tempfail_through_the_entry_point(tmp_path):
    # The workflow branches on the EXIT CODE, so that is what must be pinned. The stub
    # also points the cache at an empty folder, so no real file is written.
    r = _run(["fetch", "2026"], stub=f"""
def fake(req, timeout=None):
    raise urllib.error.HTTPError(req.full_url, 429, "Too Many Requests", email.message.Message(),
                                 io.BytesIO(b"<title>Rate Limited</title>"))
urllib.request.urlopen = fake
import os; os.environ["UNUSED"] = {str(tmp_path)!r}""")
    assert r.returncode == worlds.EX_TEMPFAIL == 75, r.stderr
    assert "429" in r.stderr and "::error" not in r.stdout   # the workflow decides red or not
    assert "::notice title=worlds.py: stopping for today::" in r.stdout and "429" in r.stdout


def test_on_a_runner_a_failure_is_an_annotation():
    # An unset year is the cheapest failure that reaches the entry point without a network.
    r = _run(["fetch", "1999"])
    assert r.returncode == 1
    assert "::error title=worlds.py fetch::[1999]: no SEEDS yet" in r.stdout


def test_the_workflow_runs_daily_and_goes_red_on_the_last_day_only():
    wf = open(os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows",
                           "lol-worlds.yml"), encoding="utf-8").read()
    assert 'cron: "31 9 * 10,11 *"' in wf
    assert '"$(date -u +%m%d)" != 1130' in wf
    assert 'worlds.py due "$(date -u +%Y)"' in wf
