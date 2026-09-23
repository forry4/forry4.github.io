"""A deploy that comes up on the sqlite FALLBACK must fail, not go green.

core/db.py runs a Turso selftest at boot and, on any failure, falls back to local
sqlite so the site stays UP. From outside that is indistinguishable from a healthy
deploy: /health answers, its `db` ping succeeds (sqlite answers too), and the
commit matches. Meanwhile every account and game written from then on lives on
Render's ephemeral disk and is gone at the next restart. A Python upgrade is the
obvious way to trip it — libsql is a native wheel — and it cannot be tested
locally (there is no Windows cp314 libsql wheel).

So /health reports `db_backend`, and deploy-render.yml's verify step refuses
anything but "turso". These tests run THAT step's actual script, extracted from
the workflow, against a faked /health — asserting the text would pass a gate
that was reachable but wired to the wrong branch.
"""
import json
import re
import subprocess
import time
from pathlib import Path

import pytest

from core import build_info, db

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-render.yml"
SHA = "0123456789abcdef0123456789abcdef01234567"


def _verify_script() -> str:
    text = WORKFLOW.read_text(encoding="utf-8")
    # The workflow has more than one Python heredoc; the verify step's reads HEALTH_URL.
    bodies = [b for b in re.findall(r"python3 - <<'PY'\n(.*?)\n\s*PY\n", text, re.S)
              if 'os.environ["HEALTH_URL"]' in b]
    assert len(bodies) == 1, "can't find the /health verify step's script in deploy-render.yml"
    lines = bodies[0].splitlines()
    indent = min(len(l) - len(l.lstrip()) for l in lines if l.strip())
    return "\n".join(l[indent:] for l in lines)


def _run_gate(monkeypatch, health: dict) -> int:
    monkeypatch.setenv("HEALTH_URL", "https://example.invalid/health")
    monkeypatch.setenv("WANT_SHA", SHA)
    monkeypatch.setenv("T0", "100")
    monkeypatch.setenv("TIMEOUT_SECONDS", "60")
    monkeypatch.setattr(subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, json.dumps(health), ""))
    monkeypatch.setattr(time, "sleep", lambda s: pytest.fail("the gate waited on a decided state"))
    with pytest.raises(SystemExit) as exc:
        exec(compile(_verify_script(), "deploy-render.yml:verify", "exec"), {"__name__": "__main__"})
    return exc.value.code


def test_live_commit_on_turso_passes(monkeypatch):
    assert _run_gate(monkeypatch, {"commit": SHA, "started_at": 200, "db_backend": "turso"}) == 0


@pytest.mark.parametrize("backend", ["sqlite", None])
def test_live_commit_off_turso_fails_at_once(monkeypatch, backend):
    health = {"commit": SHA, "started_at": 200}
    if backend:
        health["db_backend"] = backend
    assert _run_gate(monkeypatch, health) == 1


def test_start_time_fallback_is_held_to_turso_too(monkeypatch):
    # RENDER_GIT_COMMIT unset: the weaker path must not be a way around the check.
    health = {"commit": "unknown", "started_at": 200, "db_backend": "sqlite"}
    assert _run_gate(monkeypatch, health) == 1


def test_health_reports_the_backend_this_process_writes_to(monkeypatch):
    for flag, name in ((True, "turso"), (False, "sqlite")):
        monkeypatch.setattr(db, "_USE_TURSO", flag)
        assert db.backend() == name
        assert build_info.build_info()["db_backend"] == name
