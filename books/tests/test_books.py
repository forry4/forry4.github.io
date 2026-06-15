"""Unit tests for the books feature (books/api.py).

These exercise the pure functions against an in-memory SQLite connection, so no
web server or real users.db is touched. Owner gating via SITE_OWNER is tested by
monkeypatching the environment.
"""
import sqlite3

import pytest

from books import api as B


@pytest.fixture()
def conn():
    c = sqlite3.connect(":memory:")
    B.init_books_db(c)
    yield c
    c.close()


ALICE = {"id": "u_alice", "name": "alice"}
BOB = {"id": "u_bob", "name": "bob"}


def _sample():
    return [
        {"title": "Dune", "author": "Herbert", "rating": 5, "note": "peak"},
        {"title": "Hyperion", "author": "Simmons", "rating": 5},
        {"title": "Foundation", "author": "Asimov", "rating": 4},
    ]


def test_unclaimed_permissions(conn):
    # anonymous can never edit; any authenticated user can edit an unclaimed list
    assert B.can_user_edit(conn, None) is False
    assert B.can_user_edit(conn, ALICE) is True
    assert B.can_user_edit(conn, BOB) is True


def test_first_save_claims_ownership(conn):
    ok, err = B.replace_books(conn, ALICE, _sample())
    assert ok and err is None
    # now alice owns it; bob is locked out
    assert B.can_user_edit(conn, ALICE) is True
    assert B.can_user_edit(conn, BOB) is False
    ok2, err2 = B.replace_books(conn, BOB, _sample())
    assert ok2 is False and err2 == "not the owner"


def test_anonymous_cannot_write(conn):
    ok, err = B.replace_books(conn, None, _sample())
    assert ok is False and err == "unauthenticated"


def test_grouping_and_within_rating_order(conn):
    B.replace_books(conn, ALICE, _sample())
    rows = B.fetch_books(conn)
    # rating 5 group comes first, in submitted order
    fives = [r for r in rows if r["rating"] == 5]
    assert [r["title"] for r in fives] == ["Dune", "Hyperion"]
    assert [r["sort_order"] for r in fives] == [0, 1]
    assert rows[0]["rating"] == 5 and rows[-1]["rating"] == 4


def test_blank_titles_skipped_and_rating_clamped(conn):
    items = [
        {"title": "   ", "rating": 3},
        {"title": "Snow Crash", "rating": 99},
        {"title": "Neuromancer", "rating": 0},
    ]
    B.replace_books(conn, ALICE, items)
    rows = B.fetch_books(conn)
    titles = {r["title"]: r["rating"] for r in rows}
    assert "   " not in titles  # blank skipped
    assert titles["Snow Crash"] == 5  # clamped high
    assert titles["Neuromancer"] == 1  # clamped low


def test_replace_is_wholesale(conn):
    B.replace_books(conn, ALICE, _sample())
    B.replace_books(conn, ALICE, [{"title": "Only One", "rating": 3}])
    rows = B.fetch_books(conn)
    assert [r["title"] for r in rows] == ["Only One"]


def test_env_owner_override(conn, monkeypatch):
    monkeypatch.setenv("SITE_OWNER", "alice")
    # alice matches the env username -> can edit even before any claim
    assert B.can_user_edit(conn, ALICE) is True
    assert B.can_user_edit(conn, BOB) is False
    ok, err = B.replace_books(conn, BOB, _sample())
    assert ok is False and err == "not the owner"
    ok2, err2 = B.replace_books(conn, ALICE, _sample())
    assert ok2 is True and err2 is None


# ── suggestions ──────────────────────────────────────────────────────────────
def test_is_owner_strict(conn, monkeypatch):
    # unclaimed list: nobody is the owner (unlike can_user_edit)
    assert B.is_owner(conn, ALICE) is False
    B.replace_books(conn, ALICE, _sample())  # alice claims by saving
    assert B.is_owner(conn, ALICE) is True
    assert B.is_owner(conn, BOB) is False
    assert B.is_owner(conn, None) is False


def test_suggestions_require_auth(conn):
    ok, err = B.replace_user_suggestions(conn, None, [{"title": "X"}])
    assert ok is False and err == "unauthenticated"


def test_suggestions_per_user_and_order(conn):
    B.replace_user_suggestions(conn, BOB, [
        {"title": "Blindsight", "author": "Watts", "blurb": "you'll love it"},
        {"title": "The Road", "author": "McCarthy"},
    ])
    mine = B.fetch_user_suggestions(conn, BOB["id"])
    assert [s["title"] for s in mine] == ["Blindsight", "The Road"]
    assert mine[0]["sort_order"] == 0 and mine[1]["sort_order"] == 1
    assert mine[0]["blurb"] == "you'll love it"
    assert mine[0]["user_name"] == "bob"


def test_suggestions_isolated_between_users(conn):
    B.replace_user_suggestions(conn, ALICE, [{"title": "A1"}])
    B.replace_user_suggestions(conn, BOB, [{"title": "B1"}, {"title": "B2"}])
    # rewriting bob's list does not touch alice's
    B.replace_user_suggestions(conn, BOB, [{"title": "B-new"}])
    assert [s["title"] for s in B.fetch_user_suggestions(conn, ALICE["id"])] == ["A1"]
    assert [s["title"] for s in B.fetch_user_suggestions(conn, BOB["id"])] == ["B-new"]


def test_suggestions_capped_at_max(conn):
    items = [{"title": f"Book {i}"} for i in range(25)]
    B.replace_user_suggestions(conn, ALICE, items)
    mine = B.fetch_user_suggestions(conn, ALICE["id"])
    assert len(mine) == B.MAX_SUGGESTIONS


def test_fetch_all_suggestions_for_owner(conn):
    B.replace_user_suggestions(conn, ALICE, [{"title": "A1"}])
    B.replace_user_suggestions(conn, BOB, [{"title": "B1"}, {"title": "B2"}])
    everything = B.fetch_all_suggestions(conn)
    assert len(everything) == 3
    by_user = {s["user_name"] for s in everything}
    assert by_user == {"alice", "bob"}


def test_suggestion_blank_titles_skipped(conn):
    B.replace_user_suggestions(conn, ALICE, [{"title": "  "}, {"title": "Real"}])
    mine = B.fetch_user_suggestions(conn, ALICE["id"])
    assert [s["title"] for s in mine] == ["Real"]
