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
