import pytest

from bossrush import api


@pytest.fixture(autouse=True)
def no_time_floor(monkeypatch):
    """These tests clear bosses in fake seconds, as the render gate does with its
    BOSS_RUSH_MIN_CLEAR_SCALE=0. The floor's own tests (test_time_floor.py) set it back."""
    monkeypatch.setattr(api, "MIN_CLEAR_SCALE", 0.0)
