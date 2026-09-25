"""Tests for the in-memory sliding-window rate limiter (core.ratelimit).

`now` is injected so the window behavior is deterministic without sleeping.
"""
from core.ratelimit import SlidingWindowLimiter


def test_allows_up_to_limit_then_blocks():
    lim = SlidingWindowLimiter(max_hits=3, window_seconds=100)
    t = 1000.0
    for _ in range(3):
        assert lim.exceeded("k", now=t) is False
        lim.record("k", now=t)
    assert lim.exceeded("k", now=t) is True  # 4th would exceed


def test_window_slides_so_old_hits_expire():
    lim = SlidingWindowLimiter(max_hits=2, window_seconds=10)
    lim.record("k", now=100.0)
    lim.record("k", now=101.0)
    assert lim.exceeded("k", now=101.0) is True
    # Once both hits fall outside the 10s window, the key is allowed again.
    assert lim.exceeded("k", now=112.0) is False


def test_keys_are_independent():
    lim = SlidingWindowLimiter(max_hits=1, window_seconds=100)
    lim.record("a", now=1.0)
    assert lim.exceeded("a", now=1.0) is True
    assert lim.exceeded("b", now=1.0) is False


def test_reset_clears_one_key_and_all():
    lim = SlidingWindowLimiter(max_hits=1, window_seconds=100)
    lim.record("a", now=5.0)
    lim.record("b", now=5.0)
    assert lim.exceeded("a", now=5.0) and lim.exceeded("b", now=5.0)
    lim.reset("a")
    assert lim.exceeded("a", now=5.0) is False
    assert lim.exceeded("b", now=5.0) is True
    lim.reset()
    assert lim.exceeded("b", now=5.0) is False


def test_public_lists_are_throttled_per_address(monkeypatch):
    """Spender's and CoC's `/games/active` are public and decode up to 100 saved
    games per call; one address in a loop is refused once over budget, and a
    different address is not affected."""
    from types import SimpleNamespace
    from core import rooms
    from games.castles_of_crimson import main as coc
    from games.spender import main as spender

    monkeypatch.setattr(rooms, "_public_list_limiter", SlidingWindowLimiter(max_hits=3, window_seconds=60))
    for mod, route in ((spender, "get_active_games"), (coc, "games_active")):
        rooms._public_list_limiter.reset()
        monkeypatch.setattr(mod, "list_active_games", lambda: [{"id": "G"}])
        req = lambda ip: SimpleNamespace(headers={}, client=SimpleNamespace(host=ip))
        answers = [getattr(mod, route)(req("9.9.9.9")) for _ in range(4)]
        assert [a["ok"] for a in answers] == [True, True, True, False]
        assert answers[-1]["games"] == []
        assert getattr(mod, route)(req("8.8.8.8"))["ok"] is True
