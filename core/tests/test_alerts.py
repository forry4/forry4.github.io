"""Owner alerts (core/alerts.py): dedup, delivery, and the never-raise contract.

The root conftest points `alerts._sink` at a list for every test, so nothing here
touches a real database or a real phone unless a test deliberately switches the
sink off and stubs the database and the HTTP post itself.
"""
import json
import sqlite3

import pytest

from core import alerts
from core.db import _Conn


def test_an_alert_is_recorded_with_its_kind_and_severity():
    assert alerts.alert("storage", "nearly full", severity="critical") is True
    [a] = alerts._sink
    assert (a["kind"], a["severity"], a["message"], a["folded"]) == ("storage", "critical", "nearly full", 0)


def test_repeats_inside_the_cooldown_are_folded_and_counted(monkeypatch):
    clock = [1000.0]
    monkeypatch.setattr(alerts.time, "time", lambda: clock[0])
    assert alerts.alert("flood", "one", cooldown=60)
    assert not alerts.alert("flood", "two", cooldown=60)
    assert not alerts.alert("flood", "three", cooldown=60)
    assert alerts.alert("other", "a different key is not folded", cooldown=60)
    clock[0] += 61
    assert alerts.alert("flood", "four", cooldown=60)
    assert [(a["message"], a["folded"]) for a in alerts._sink] == [
        ("one", 0), ("a different key is not folded", 0), ("four", 2)]


def test_an_explicit_key_separates_alerts_of_one_kind():
    assert alerts.alert("lobby-flood", "a", key="create:1.1.1.1")
    assert alerts.alert("lobby-flood", "b", key="create:2.2.2.2")
    assert not alerts.alert("lobby-flood", "c", key="create:1.1.1.1")


def test_an_unknown_severity_becomes_warn_and_long_messages_are_capped():
    alerts.alert("x", "m" * 5000, severity="apocalyptic")
    assert alerts._sink[0]["severity"] == "warn" and len(alerts._sink[0]["message"]) == alerts._MSG_MAX


def test_alert_never_raises(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("dedup exploded")
    monkeypatch.setattr(alerts, "_admit", boom)
    assert alerts.alert("x", "y") is False


# ── delivery ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def delivered(tmp_path, monkeypatch):
    """Switch the test sink off and capture the real delivery path: a real sqlite
    file for the table, and every HTTP post recorded instead of sent."""
    db = str(tmp_path / "alerts.db")
    import core.db
    monkeypatch.setattr(core.db, "get_db_conn", lambda: _Conn(sqlite3.connect(db, check_same_thread=False)))
    posts = []
    monkeypatch.setattr(alerts, "_post", lambda url, data, headers: posts.append((url, data, headers)))
    for var in ("ALERT_NTFY_TOPIC", "ALERT_WEBHOOK_URL", "ALERT_EMAIL", "ALERT_NTFY_TOKEN", "ALERT_NTFY_SERVER"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setattr(alerts, "_sink", None)

    def conn():
        return _Conn(sqlite3.connect(db, check_same_thread=False))
    return posts, conn


def test_with_no_channel_an_alert_is_still_stored(delivered):
    posts, conn = delivered
    assert alerts.channels() == []
    alerts.alert("storage", "80% full")
    assert alerts.drain()
    c = conn()
    [row] = alerts.recent(c)
    assert (row["kind"], row["message"], row["acked"]) == ("storage", "80% full", False)
    assert alerts.unacked(c) == 1
    alerts.ack_all(c)
    assert alerts.unacked(c) == 0
    c.close()
    assert posts == []


def test_ntfy_and_webhook_both_receive_it(delivered, monkeypatch):
    posts, _ = delivered
    monkeypatch.setenv("ALERT_NTFY_TOPIC", "fg-secret-topic")
    monkeypatch.setenv("ALERT_EMAIL", "me@example.com")
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.test/hook")
    assert alerts.channels() == ["ntfy", "webhook"]
    alerts.alert("owner-login", "someone is guessing your password", severity="critical")
    assert alerts.drain()
    (nurl, nbody, nh), (wurl, wbody, wh) = posts
    assert nurl == "https://ntfy.sh/fg-secret-topic"
    assert nbody.decode() == "someone is guessing your password"
    assert nh["Priority"] == "5" and nh["Email"] == "me@example.com" and "owner-login" in nh["Title"]
    nh["Title"].encode("latin-1")   # HTTP headers must be latin-1
    assert wurl == "https://discord.test/hook"
    payload = json.loads(wbody)
    assert "someone is guessing your password" in payload["content"] and payload["text"]


def test_one_channel_failing_does_not_stop_the_other(delivered, monkeypatch):
    posts, conn = delivered
    monkeypatch.setenv("ALERT_NTFY_TOPIC", "t")
    monkeypatch.setenv("ALERT_WEBHOOK_URL", "https://discord.test/hook")

    def flaky(url, data, headers):
        if "ntfy" in url:
            raise OSError("ntfy is down")
        posts.append(url)
    monkeypatch.setattr(alerts, "_post", flaky)
    alerts.alert("x", "y")
    assert alerts.drain()
    assert posts == ["https://discord.test/hook"]
    c = conn()
    assert len(alerts.recent(c)) == 1
    c.close()


def test_the_folded_count_reaches_the_phone(delivered, monkeypatch):
    posts, _ = delivered
    monkeypatch.setenv("ALERT_NTFY_TOPIC", "t")
    clock = [0.0]
    monkeypatch.setattr(alerts.time, "time", lambda: clock[0])
    alerts.alert("flood", "first", cooldown=10)
    for _ in range(4):
        alerts.alert("flood", "again", cooldown=10)
    clock[0] = 11
    alerts.alert("flood", "later", cooldown=10)
    assert alerts.drain()
    assert posts[-1][1].decode() == "later\n(+4 more like this since the last alert)"


def test_the_table_keeps_only_recent_rows(delivered, monkeypatch):
    _, conn = delivered
    monkeypatch.setattr(alerts, "KEEP_ROWS", 3)
    for i in range(6):
        alerts.alert("x", f"n{i}", key=f"k{i}")
    assert alerts.drain()
    c = conn()
    assert [r["message"] for r in alerts.recent(c)] == ["n5", "n4", "n3"]
    c.close()
