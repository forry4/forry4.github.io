"""Root pytest conftest — keep the shared engine deck globals isolated across the suite.

`wwsd/app.py` installs the friend's deck into the SHARED engine globals
(`games.spender.ai.serving.engine.COST/PTS/BONUS/...`) via `analyze.prepare()` **at import time**
(deliberate for the process-isolated wwsd Render service). But pytest imports every test module
during COLLECTION before running any test, so importing `wwsd.app` to collect `test_wwsd.py`
rewrites the deck for the whole session — which silently broke 45 spender tests (replay/review/
valuation) that run with the real deck. Importing wwsd must not corrupt the rest of the suite.

This conftest loads before any test module, so it snapshots the REAL deck first, then:
  - restores it after collection (before the run phase) — undoes the import-time override, and
  - restores it after every test — undoes any in-test `prepare()`/`analyze()` call (wwsd tests),
keeping the override scoped to the code that intends it, in any test order.
"""
from games.spender.ai.serving import engine as E
import pytest

_ENGINE_DECK_ATTRS = (
    "COST", "PTS", "BONUS", "LEVEL_OF", "CARD_NAME", "CARD_ID_BY_NAME",
    "NOBLE_REQ", "NOBLE_PTS", "WIN_POINTS",
)
# Captured at conftest import — before any test module (incl. wwsd) is collected.
_REAL_DECK = {a: getattr(E, a) for a in _ENGINE_DECK_ATTRS if hasattr(E, a)}

# Safe to import (analyze.py never overrides at import — only prepare() does); we reset its
# idempotency flag so a wwsd test's prepare()/analyze() re-installs the friend's deck after a restore.
# Optional: a build/test context without wwsd still gets the deck restore.
try:
    from wwsd import analyze as _wwsd_analyze  # noqa: E402
except Exception:
    _wwsd_analyze = None


def _restore_deck():
    for a, v in _REAL_DECK.items():
        setattr(E, a, v)
    if _wwsd_analyze is not None:
        _wwsd_analyze._PREPARED = False


def pytest_collection_finish(session):
    # Collection has imported every test module (wwsd.app's import-time override included);
    # restore the real deck before the run phase begins.
    _restore_deck()


@pytest.fixture(autouse=True)
def _restore_engine_deck():
    yield
    _restore_deck()


@pytest.fixture(autouse=True)
def _isolate_site_alerts_and_caps():
    """Owner alerts go to a per-test list, never a database or a phone, and the
    SITE-WIDE abuse caps start empty for every test. The per-IP caps were always
    reset by the modules that drive them, but the site-wide ones (accounts per hour,
    tables per hour and public-list reads from the one "unknown" test peer) are shared by every test a
    worker runs, so without this a long worker trips them part-way through."""
    import sys
    from core import alerts
    alerts.reset()
    alerts._sink = []
    rooms = sys.modules.get("core.rooms")
    if rooms is not None:
        rooms._room_create_limiter.reset()
        rooms._public_list_limiter.reset()
    spender = sys.modules.get("games.spender.main")
    if spender is not None:
        spender._register_site_limiter.reset()
        spender._register_ip_day_limiter.reset()
    yield
    alerts._sink = None
