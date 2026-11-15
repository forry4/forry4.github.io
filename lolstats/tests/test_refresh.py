"""The monthly refresh's two failure-shaped cases: Drive's download quota, and a retry
day that has nothing left to do. The download itself needs the network; what can go
wrong offline is telling the quota page from the CSV and from any other refusal, and
deciding whether a retry is due."""
import datetime
import importlib.util
import os
import subprocess
import sys

import pytest

TOOLS = os.path.join(os.path.dirname(__file__), "..", "tools")


def _load(name):
    spec = importlib.util.spec_from_file_location(name, os.path.join(TOOLS, f"{name}.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


harvest = _load("harvest")
refresh_due = _load("refresh_due")

# The first bytes Drive sent on 2026-11-15 for the 2026 file.
QUOTA_PAGE = (b'<!DOCTYPE html><html><head><title>Google Drive - Quota exceeded</title>'
              b'<meta http-equiv="content-type" content="text/html; charset=utf-8"/>')


def test_the_csv_header_passes():
    harvest.check_head(2026, b"gameid,datacompleteness,url,league,year,split")


def test_the_quota_page_is_its_own_failure():
    with pytest.raises(harvest.QuotaExceeded, match="quota"):
        harvest.check_head(2026, QUOTA_PAGE)


def test_any_other_page_is_still_a_hard_failure():
    # A sign-in wall or a moved file must not be mistaken for a quota that resets.
    with pytest.raises(SystemExit, match="did not return the CSV"):
        harvest.check_head(2026, b"<!DOCTYPE html><html><head><title>Sign in</title>")


def test_the_quota_exits_tempfail_and_leaves_no_part_file(tmp_path, monkeypatch):
    # Through the script's own entry point, with the network stubbed: the workflow
    # branches on the EXIT CODE, so that is what must be pinned.
    script = f"""
import io, sys, runpy, urllib.request
sys.argv = ["harvest.py", "2026"]
class R(io.BytesIO):
    def __enter__(self): return self
    def __exit__(self, *a): pass
def fake(req, timeout=None):
    if "embeddedfolderview" in req.full_url:
        return R(b'<a href="https://drive.google.com/file/d/ABC/view"><div class="flip-entry-title">2026_LoL_esports_match_data_from_OraclesElixir.csv</div></a>')
    return R({QUOTA_PAGE!r})
urllib.request.urlopen = fake
runpy.run_path({os.path.join(TOOLS, "harvest.py")!r}, run_name="__main__")
"""
    r = subprocess.run([sys.executable, "-c", script], capture_output=True, text=True,
                       env={**os.environ, "LOL_OE_CACHE": str(tmp_path)})
    assert r.returncode == harvest.EX_TEMPFAIL == 75, r.stderr
    assert os.listdir(tmp_path) == []


def _idx(*built):
    return {"years": [{"year": 2020 + i, "built": b} for i, b in enumerate(built)]}


NOV = lambda d: datetime.date(2026, 11, d)


def test_the_15th_and_any_run_by_hand_are_always_due():
    done = _idx("2026-11-15")
    assert refresh_due.due("schedule", NOV(15), done)
    assert refresh_due.due("workflow_dispatch", NOV(20), done)


@pytest.mark.parametrize("day", [17, 20])
def test_a_retry_runs_while_the_month_has_no_build(day):
    assert refresh_due.due("schedule", NOV(day), _idx("2026-10-28", "2026-10-28"))


@pytest.mark.parametrize("built", ["2026-11-15", "2026-11-17"])
def test_a_retry_is_skipped_once_the_month_has_landed(built):
    assert not refresh_due.due("schedule", NOV(20), _idx("2026-10-28", built))


def test_a_build_by_hand_before_the_15th_does_not_count():
    # A by-hand rebuild on the 10th is not this month's scheduled refresh.
    assert refresh_due.due("schedule", NOV(17), _idx("2026-11-10"))


def test_the_cron_and_the_retry_days_agree():
    wf = open(os.path.join(os.path.dirname(__file__), "..", "..", ".github", "workflows",
                           "lol-stats-refresh.yml"), encoding="utf-8").read()
    assert f'cron: "23 10 {refresh_due.FIRST_DAY},17,20 1-11 *"' in wf
    # The last retry is the only scheduled run that may go red on the quota.
    assert '"$(date -u +%-d)" -lt 20' in wf
