"""Account creation and sign-in: the site-wide caps and the owner's alerts.

The per-IP limits predate these; what is new is that registration is also capped
SITE-WIDE (many addresses defeat a per-IP limit), and that a burst of accounts,
a locked-out name, and above all failed passwords on the OWNER's account each
reach the owner. The account functions are stubbed so nothing here touches a
real users.db.
"""
import asyncio
from types import SimpleNamespace

import pytest

from core import alerts
from games.spender import main as m


def _req(ip):
    return SimpleNamespace(headers={"x-forwarded-for": ip}, client=SimpleNamespace(host=ip))


@pytest.fixture(autouse=True)
def _stub_accounts(monkeypatch):
    for lim in (m._register_ip_limiter, m._register_ip_day_limiter, m._register_site_limiter,
                m._login_ip_limiter, m._login_user_limiter):
        lim.reset()
    monkeypatch.setattr(m, "create_user", lambda name, pw: {"id": f"id-{name}", "name": name})
    monkeypatch.setattr(m, "authenticate_user", lambda name, pw: (
        {"id": f"id-{name}", "name": name, "session_token": "t", "is_admin": False}
        if pw == "right" else None))
    yield


def register(name, ip="5.5.5.5"):
    return asyncio.run(m.auth_register(m.RegisterBody(name=name, password="right"), _req(ip)))


def login(name, pw, ip="6.6.6.6"):
    return asyncio.run(m.auth_login(m.LoginBody(name=name, password=pw), _req(ip)))


def test_a_burst_of_accounts_alerts_then_the_site_cap_refuses(monkeypatch):
    monkeypatch.setattr(m, "REGISTER_ALERT_PER_HOUR", 3)
    monkeypatch.setattr(m._register_site_limiter, "max_hits", 5)
    for i in range(5):
        assert register(f"u{i}", ip=f"10.0.0.{i}")["ok"]          # five different addresses
    refused = register("u5", ip="10.0.0.99")
    assert not refused["ok"] and "busy" in refused["message"]
    kinds = [(a["kind"], a["severity"]) for a in alerts._sink]
    assert kinds == [("account-flood", "warn"), ("account-flood", "critical")]


def test_a_taken_name_does_not_count_toward_the_site_cap(monkeypatch):
    monkeypatch.setattr(m, "create_user", lambda name, pw: None)
    for i in range(3):
        assert not register(f"taken{i}", ip=f"10.1.0.{i}")["ok"]
    assert m._register_site_limiter.count("site") == 0


def test_one_address_is_also_capped_per_day(monkeypatch):
    monkeypatch.setattr(m._register_ip_limiter, "max_hits", 100)   # take the hourly cap out of it
    for i in range(20):
        assert register(f"d{i}")["ok"]
    assert not register("d20")["ok"]
    assert alerts._sink[-1]["kind"] == "account-flood"


def test_failed_passwords_on_the_owners_account_are_critical(monkeypatch):
    monkeypatch.setenv("SITE_OWNER", "Forrest")
    for _ in range(m.OWNER_FAILED_LOGIN_ALERT - 1):
        login("forrest", "wrong")
    assert alerts._sink == []
    login("FORREST", "wrong")                                       # same name, any case
    [a] = alerts._sink
    assert a["kind"] == "owner-login" and a["severity"] == "critical" and "6.6.6.6" in a["message"]


def test_failed_passwords_on_someone_else_alert_only_at_lockout(monkeypatch):
    monkeypatch.setenv("SITE_OWNER", "Forrest")
    for _ in range(10):
        login("alice", "wrong")
    assert alerts._sink == []
    assert not login("alice", "right")["ok"]                        # locked, even with the password
    [a] = alerts._sink
    assert a["kind"] == "login-lockout" and a["severity"] == "warn"
