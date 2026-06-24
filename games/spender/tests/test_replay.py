"""Tests for offline game reconstruction (games/spender/ai/az/replay.py) and the
main.py changes that make it possible (the setup snapshot + discard logging).

The core test is differential: play random 2-player games in the AZ engine, emit the
move log in main.py's EXACT persisted format (ids only; every noble claim — including
the single auto-claims the engine resolves silently — logged as type "noble"; deck-top
reserves logged with card_id + from_deck, as the human handler does), then reconstruct
from the setup snapshot alone and assert the replayed state matches the engine's own
state at the start of every turn. The deck order (the thing the snapshot exists to
preserve) is compared EXACTLY, so any draw/refill desync fails the test.
"""
import random

import pytest

from games.spender import main as M
from games.spender.ai.az import engine as E
from games.spender.ai.az import actions as A
from games.spender.ai.az import replay as R

PIDS = ("p0", "p1")


# ─── canonical State projection (ignore board-slot / reserved / noble ORDER) ──

def _canon(s: E.State) -> dict:
    return {
        "bank": list(s.bank),
        "turn": s.turn,
        "phase": s.phase,
        "tokens": [list(s.tokens[0]), list(s.tokens[1])],
        "bonuses": [list(s.bonuses[0]), list(s.bonuses[1])],
        "points": list(s.points),
        "purchased_n": list(s.purchased_n),
        "purchased": [sorted(s.purchased[0]), sorted(s.purchased[1])],
        "reserved": [sorted(zip(s.reserved[0], s.reserved_blind[0])),
                     sorted(zip(s.reserved[1], s.reserved_blind[1]))],
        "nobles_won": [sorted(s.nobles_won[0]), sorted(s.nobles_won[1])],
        "board": sorted(ci for ci in s.board if ci >= 0),
        "decks": [list(s.decks[0]), list(s.decks[1]), list(s.decks[2])],  # EXACT order
        "nobles": sorted(ni for ni in s.nobles if ni >= 0),
        "final_trigger": s.final_trigger,
        "winner": s.winner,
        "win_points": s.win_points,
    }


def _setup_from(s0: E.State) -> dict:
    """The ids-only snapshot main._capture_setup writes, derived from an initial State."""
    g0 = E.to_game_dict(s0, PIDS)
    return {
        "board": {lk: [c["id"] if c else None for c in g0["board"][lk]] for lk in g0["board"]},
        "decks": {lk: [c["id"] for c in g0["decks"][lk]] for lk in g0["decks"]},
        "nobles": [n["id"] for n in g0["nobles"]],
    }


def _play_and_log(rng: random.Random, max_steps: int = 800):
    """Play one random game; return (setup, chrono_moves, boundaries) where boundaries is
    a list of (mover_seat, State clone, n_moves_done) at the start of every turn (and the
    terminal state). Moves are emitted in main.py's persisted log format."""
    s = E.new_game(rng)
    setup = _setup_from(s)
    moves: list[dict] = []
    boundaries = [(s.turn, s.clone(), 0)]
    decision_seat = s.turn

    for _ in range(max_steps):
        if s.phase == E.OVER:
            break
        seat = s.turn
        pid = PIDS[seat]
        legal = [a for a in E.legal_actions(s) if a != E.A_PASS]  # main has no 'pass'
        if not legal:
            break
        a = rng.choice(legal)
        is_noble = a >= E.A_NOBLE
        is_deck_reserve = E.A_RES_DECK <= a < E.A_BUY_BOARD
        won_before = len(s.nobles_won[seat])

        if is_noble:
            E.apply(s, a)               # claim resolved -> logged as "noble" via the diff below
        elif is_deck_reserve:
            E.apply(s, a)
            ci = s.reserved[seat][-1]   # the just-reserved deck-top card
            moves.append({"pid": pid, "type": "reserve",
                          "card_id": E.CARD_NAME[ci], "from_deck": True})
        else:
            mv = dict(A.action_to_move(s, a))
            mv["pid"] = pid
            moves.append(mv)
            E.apply(s, a)

        # main logs EVERY noble claim (single auto-claims + multi picks) as type "noble".
        for ni in s.nobles_won[seat][won_before:]:
            moves.append({"pid": pid, "type": "noble",
                          "noble_id": E.NOBLE_NAME[ni], "pts": E.NOBLE_PTS[ni]})

        if s.phase == E.OVER:
            boundaries.append((s.turn, s.clone(), len(moves)))
            break
        if s.phase == E.PLAY and s.turn != decision_seat:
            boundaries.append((s.turn, s.clone(), len(moves)))
            decision_seat = s.turn

    chrono = moves[: boundaries[-1][2]]   # only fully-completed turns
    return setup, chrono, boundaries


@pytest.mark.parametrize("seed", range(20))
def test_replay_matches_engine(seed):
    """3 random games per seed x 20 seeds = 60 full games; every turn's reconstructed
    state must equal the engine's, deck order included."""
    rng = random.Random(seed)
    for _g in range(3):
        setup, chrono, boundaries = _play_and_log(rng)
        g0 = R.initial_from_setup(setup, list(PIDS), win_points=15)
        snaps = list(R.turn_snapshots(g0, chrono))

        assert len(snaps) == len(boundaries), \
            f"snapshot count {len(snaps)} != boundary count {len(boundaries)} (seed={seed})"

        for (turn, mover, _primary, g), (bseat, bstate, _n) in zip(snaps, boundaries):
            assert mover == PIDS[bseat], f"mover mismatch at turn {turn} (seed={seed})"
            got = _canon(E.from_game_dict(g))
            want = _canon(bstate)
            assert got == want, (
                f"state divergence at turn {turn} (seed={seed}); "
                f"decks_match={got['decks'] == want['decks']}, "
                f"board_match={got['board'] == want['board']}, "
                f"points {got['points']} vs {want['points']}")


def test_replay_at_least_one_game_finishes():
    """Sanity: across a handful of seeds, the random driver reaches a real OVER terminal
    (so the terminal-state branch + winner reconstruction are actually exercised)."""
    finished = 0
    for seed in range(10):
        _setup, _chrono, boundaries = _play_and_log(random.Random(seed))
        if boundaries[-1][1].phase == E.OVER:
            finished += 1
    assert finished >= 1


def test_evaluate_produces_v_state_curve():
    """End-to-end: a reconstructed game evaluates to one S-value record per turn with the
    five components, from a fixed seat, in [-1, 1]."""
    setup, chrono, _b = _play_and_log(random.Random(123))
    # Mimic a persisted /full dump game dict.
    game = {"order": list(PIDS), "win_points": 15, "ai_player": "p1", "setup": setup,
            "moves": list(reversed(chrono))}   # stored newest-first
    records = R.evaluate(game, seat="ai")
    assert len(records) >= 2
    for r in records:
        assert -1.0 <= r["value"] <= 1.0
        assert r["seat"] == 1   # ai_player p1
        assert set(r["points"]) == set(PIDS)
        if not r["terminal"]:
            assert set(r["components"]) >= {"points", "engine", "progress", "noble", "econ"}


def test_evaluate_requires_setup_and_two_players():
    with pytest.raises(R.ReplayError):
        R.evaluate({"order": list(PIDS), "moves": []})           # no setup
    with pytest.raises(R.ReplayError):
        R.evaluate({"order": ["a", "b", "c"], "setup": {}, "moves": []})  # 3 players


# ─── direct guards on the main.py changes ─────────────────────────────────────

def test_capture_setup_shape():
    s = E.new_game(random.Random(7))
    g = E.to_game_dict(s, PIDS)
    M._capture_setup(g)
    setup = g["setup"]
    assert set(setup) == {"board", "decks", "nobles"}
    assert set(setup["board"]) == {"L1", "L2", "L3"} and len(setup["board"]["L1"]) == 4
    # ids only — no nested dicts
    assert all(isinstance(cid, str) for row in setup["board"].values() for cid in row if cid)
    assert all(isinstance(cid, str) for lst in setup["decks"].values() for cid in lst)
    assert all(isinstance(nid, str) for nid in setup["nobles"])
    # nothing was popped off the live decks/board by snapshotting
    assert [c["id"] for c in g["decks"]["L1"]] == setup["decks"]["L1"]


def test_setup_kept_in_game_dict_but_stripped_from_wire():
    """save_game persists room['game'] verbatim (so setup is stored + reaches the /full dump),
    but mk_room_state must NOT broadcast the static setup blob to clients."""
    s = E.new_game(random.Random(11))
    g = E.to_game_dict(s, PIDS)
    M._capture_setup(g)
    rid = "TESTROOM_REPLAY"
    M.ROOMS[rid] = {"players": {"p0": "A", "p1": "B"}, "host": "p0",
                    "status": "playing", "game": g, "meta": {}}
    try:
        view = M.mk_room_state(rid, viewer_pid="p0")
        assert "setup" not in view["game"]           # off the wire
        assert "setup" in M.ROOMS[rid]["game"]        # still in the live dict (what save_game stores)
    finally:
        M.ROOMS.pop(rid, None)


def test_ai_discard_one_returns_color():
    s = E.new_game(random.Random(3))
    g = E.to_game_dict(s, PIDS)
    g["players"]["p0"]["tokens"] = {"white": 1, "blue": 0, "green": 0, "red": 0, "black": 0, "gold": 0}
    before = sum(g["players"]["p0"]["tokens"].values())
    color = M._ai_discard_one(g, "p0")
    assert color == "white"
    assert sum(g["players"]["p0"]["tokens"].values()) == before - 1
    # holds nothing -> returns None, no crash
    assert M._ai_discard_one(g, "p0") is None
