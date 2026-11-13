"""/health reports how long the process took to start, split by phase.

A Render cold start is measured on prod's fractional CPU, not guessed from a
laptop, so the split has to be right and has to survive into the payload."""
import asyncio
import sys

import pytest

from core import build_info, monitor


@pytest.fixture
def boot(monkeypatch):
    marks = {}
    monkeypatch.setattr(build_info, "_BOOT", marks)
    monkeypatch.setattr(build_info, "_PROCESS_START", 100.0)
    return marks


def test_the_split_adds_up(boot):
    build_info.mark("app_import_started", 101.5)
    build_info.mark("app_imported", 109.0)
    build_info.mark("serving", 109.25)
    assert build_info.boot_timing() == {
        "interpreter_s": 1.5, "import_s": 7.5, "startup_s": 0.25, "total_s": 9.25,
        "process_start": 100.0,
    }


def test_the_first_mark_wins(boot):
    build_info.mark("serving", 5.0)
    build_info.mark("serving", 9.0)
    assert boot["serving"] == 5.0


def test_a_missing_mark_drops_only_its_phases(boot, monkeypatch):
    monkeypatch.setattr(build_info, "_PROCESS_START", None)
    build_info.mark("app_import_started", 1.0)
    build_info.mark("app_imported", 3.0)
    assert build_info.boot_timing() == {"import_s": 2.0}


def test_health_carries_the_boot_block(boot):
    build_info.mark("app_import_started", 101.0)
    build_info.mark("app_imported", 102.0)
    assert build_info.build_info()["boot"]["import_s"] == 1.0


def test_the_first_asgi_call_marks_serving(boot, monkeypatch):
    monkeypatch.setattr(monitor, "_armed", False)
    monkeypatch.setattr(monitor, "arm", lambda: None)  # no threads from a test

    async def app(scope, receive, send):
        return None

    asyncio.run(monitor.ErrorAlertMiddleware(app)({"type": "lifespan"}, None, None))
    assert "serving" in boot


def test_importing_app_marks_both_ends_of_the_import():
    import app  # noqa: F401 - the composition root stamps its own import phase
    assert {"app_import_started", "app_imported"} <= set(build_info._BOOT)
    assert build_info._BOOT["app_imported"] >= build_info._BOOT["app_import_started"]


def test_process_start_is_read_where_proc_exists():
    # prod and CI are Linux, so the branch that matters runs in CI.
    start = build_info.process_start_time()
    if sys.platform.startswith("linux"):
        assert start is not None and start <= build_info.STARTED_AT + 1
    else:
        assert start is None
