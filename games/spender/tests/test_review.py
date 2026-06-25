"""Tests for the review-snapshot helpers behind GET /games/{id}/review
(main._build_review_snapshots / _review_view).

We build a realistic finished game with the persisted log format (ids only, setup
snapshot, discards + nobles logged) by playing a random game in the AZ engine, then
assert the helpers turn it into a per-turn list of renderable board states.
"""
import random

from games.spender import main as M
from games.spender.ai.az import engine as E
from games.spender.ai.az import actions as A

PIDS = ("p0", "p1")


def _setup_from(s0: E.State) -> dict:
    g0 = E.to_game_dict(s0, PIDS)
    return {
        "board": {lk: [c["id"] if c else None for c in g0["board"][lk]] for lk in g0["board"]},
        "decks": {lk: [c["id"] for c in g0["decks"][lk]] for lk in g0["decks"]},
        "nobles": [n["id"] for n in g0["nobles"]],
    }


def _build_finished_game(seed: int) -> dict:
    """Play a random game to completion (or step cap) and return a game dict shaped like a
    persisted /full dump game: order + setup + win_points + ai_player + newest-first moves."""
    rng = random.Random(seed)
    s = E.new_game(rng)
    setup = _setup_from(s)
    moves: list[dict] = []
    decision_seat = s.turn
    last_completed = 0
    for _ in range(800):
        if s.phase == E.OVER:
            break
        seat = s.turn
        pid = PIDS[seat]
        legal = [a for a in E.legal_actions(s) if a != E.A_PASS]
        if not legal:
            break
        a = rng.choice(legal)
        is_noble = a >= E.A_NOBLE
        is_deck_reserve = E.A_RES_DECK <= a < E.A_BUY_BOARD
        won_before = len(s.nobles_won[seat])
        if is_noble:
            E.apply(s, a)
        elif is_deck_reserve:
            E.apply(s, a)
            ci = s.reserved[seat][-1]
            moves.append({"pid": pid, "type": "reserve", "card_id": E.CARD_NAME[ci], "from_deck": True})
        else:
            mv = dict(A.action_to_move(s, a))
            mv["pid"] = pid
            moves.append(mv)
            E.apply(s, a)
        for ni in s.nobles_won[seat][won_before:]:
            moves.append({"pid": pid, "type": "noble", "noble_id": E.NOBLE_NAME[ni], "pts": E.NOBLE_PTS[ni]})
        if s.phase == E.OVER:
            last_completed = len(moves)
            break
        if s.phase == E.PLAY and s.turn != decision_seat:
            last_completed = len(moves)
            decision_seat = s.turn
    chrono = moves[:last_completed]
    # A real persisted game carries the full FINAL state plus setup + newest-first moves.
    g = E.to_game_dict(s, PIDS)
    g["win_points"] = 15
    g["ai_player"] = "p1"
    g["setup"] = setup
    g["moves"] = list(reversed(chrono))
    return g


def test_review_snapshots_are_renderable_boards():
    game = _build_finished_game(123)
    snaps = M._build_review_snapshots(game, "p0")
    assert snaps is not None and len(snaps) >= 2
    for snap in snaps:
        assert {"turn", "mover", "move", "game"} <= set(snap)
        g = snap["game"]
        # each snapshot is a full, client-renderable game dict
        assert set(g["order"]) == set(PIDS)
        assert set(g["board"]) == {"L1", "L2", "L3"}
        assert all(pid in g["players"] for pid in PIDS)
        assert "bank" in g and "nobles" in g
        assert "setup" not in g          # static replay blob stripped off the wire
    # turn indices are 0,1,2,... contiguous; only the final snapshot has move=None
    assert [s["turn"] for s in snaps] == list(range(len(snaps)))
    assert snaps[-1]["move"] is None
    assert all(s["move"] is not None for s in snaps[:-1])


def test_review_snapshots_none_without_setup():
    game = _build_finished_game(7)
    game.pop("setup")
    assert M._build_review_snapshots(game, "p0") is None


def test_review_view_strips_setup_and_keeps_board():
    game = _build_finished_game(42)
    view = M._review_view(game, "p0")
    assert "setup" not in view
    assert view["order"] == list(PIDS)
    assert "board" in view and "players" in view


def test_review_blind_reserve_hidden_from_other_player():
    """A mid-game snapshot must redact an opponent's deck-top (blind) reserve from the
    reviewer — they never saw the card identity live, and the over-state reveal only
    applies to the final position."""
    game = {
        "order": list(PIDS),
        "turn": "p0",
        "phase": "playing",
        "bank": M.empty_gems(),
        "board": {"L1": [], "L2": [], "L3": []},
        "decks": {"L1": [], "L2": [], "L3": []},
        "nobles": [],
        "players": {
            "p0": {"tokens": M.empty_gems(), "purchased": [], "reserved": [], "nobles": []},
            "p1": {"tokens": M.empty_gems(), "purchased": [],
                   "reserved": [{"id": "L2-3", "level": 2, "points": 1, "bonus": "red",
                                 "cost": {"white": 2}, "from_deck": True}],
                   "nobles": []},
        },
        "moves": [{"pid": "p1", "type": "reserve", "card_id": "L2-3", "from_deck": True}],
    }
    view = M._review_view(game, "p0")
    hidden = view["players"]["p1"]["reserved"][0]
    assert hidden.get("hidden") is True
    assert "cost" not in hidden          # identity scrubbed
    # the reviewer still sees their own things fully
    assert view["players"]["p0"]["reserved"] == []
