"""Tests for the AZ action helpers, feature encoding, and MCTS plumbing.

The MCTS smoke test uses a uniform fake evaluator so it runs without torch;
net round-trip tests are skipped when torch isn't installed.
"""
import random

import numpy as np
import pytest

from games.spender.ai.az import actions as A
from games.spender.ai.az import engine as E
from games.spender.ai.az import features as F
from games.spender.ai.az import mcts as M


def _fresh(seed=3):
    return E.new_game(random.Random(seed))


# ─── actions ──────────────────────────────────────────────────────────────────

def test_legal_mask_matches_legal_actions():
    s = _fresh()
    mask = A.legal_mask(s)
    legal = set(E.legal_actions(s))
    assert len(mask) == E.N_ACTIONS
    assert {a for a, ok in enumerate(mask) if ok} == legal


def test_action_names_cover_space():
    names = {A.action_name(a) for a in range(E.N_ACTIONS)}
    assert len(names) == E.N_ACTIONS  # all distinct


def test_action_to_move_matches_incumbent_format():
    s = _fresh()
    for a in E.legal_actions(s):
        mv = A.action_to_move(s, a)
        assert mv["type"] in ("take_gems", "reserve", "buy", "discard", "pick_noble")
        if mv["type"] == "take_gems":
            assert all(c in A.COLOR_NAMES for c in mv["colors"])


def test_move_to_action_round_trip():
    rng = random.Random(5)
    s = E.new_game(rng)
    # walk a random game; round-trip every legal action at every state
    for _ in range(200):
        if s.phase == E.OVER:
            break
        for a in E.legal_actions(s):
            assert A.move_to_action(s, A.action_to_move(s, a)) == a
        acts = E.legal_actions(s)
        E.apply(s, rng.choice(acts))


def test_arena_bridge_plays_full_game():
    from games.spender import main as inc
    from games.spender.ai.az import arena

    rng = random.Random(17)
    score = arena.play_game(_uniform_eval, 0, dict(inc.DEFAULT_WEIGHTS),
                            az_sims=16, opp_iters=10, rng=rng)
    assert score in (0.0, 0.5, 1.0)


# ─── features ─────────────────────────────────────────────────────────────────

def test_encode_shape_and_range():
    s = _fresh()
    x = F.encode(s)
    assert x.shape == (F.N_FEATURES,)
    assert np.isfinite(x).all()
    assert x.min() >= 0.0 and x.max() <= 1.5


def test_encode_is_perspective_relative():
    s = _fresh()
    s.points[0] = 7
    x0 = F.encode(s)
    s.turn = 1
    x1 = F.encode(s)
    # "my points" slot moves: seat 0's 7 points appear in the me-block for x0
    # and in the opp-block for x1.
    assert not np.array_equal(x0, x1)


def test_encode_hides_opponent_blind_reserves():
    s = _fresh()
    s.reserved[1].append(s.decks[2].pop())
    s.reserved_blind[1].append(True)
    s.turn = 0
    x = F.encode(s)
    # the opp reserved slot encodes present+blind+level but no cost signature
    opp_resv_off = 12 * 12 + F._PLAYER_F + 6 + 5 + 2  # opp block, first resv slot
    slot = x[opp_resv_off:opp_resv_off + F._RESV_F]
    assert slot[0] == 1.0          # present
    assert slot[12] == 1.0         # blind
    assert slot[1:7].sum() == 0.0  # cost hidden
    assert slot[13:16].sum() == 1.0  # level known


def test_encode_during_discard_and_noble_phases():
    s = _fresh()
    s.tokens[0][:] = [3, 3, 3, 2, 0, 0]
    E.apply(s, E.A_TAKE1 + 4)  # 12th token -> discard phase
    assert s.phase == E.DISCARD
    x = F.encode(s)
    phase_off = F.N_FEATURES - 9
    assert x[phase_off + E.DISCARD] == 1.0


# ─── determinization ──────────────────────────────────────────────────────────

def test_determinize_preserves_public_info():
    rng = random.Random(7)
    s = _fresh()
    s.reserved[1].append(s.decks[1].pop())
    s.reserved_blind[1].append(True)
    s.reserved[0].append(s.decks[0].pop())
    s.reserved_blind[0].append(True)
    d = M.determinize(s, perspective=0, rng=rng)
    assert d.board == s.board
    assert d.bank == s.bank
    assert d.reserved[0] == s.reserved[0]          # my blind reserve known to me
    assert len(d.reserved[1]) == len(s.reserved[1])
    # opp blind reserve stays the same level
    assert E.LEVEL_OF[d.reserved[1][0]] == E.LEVEL_OF[s.reserved[1][0]]
    # per-level card multiset conserved across deck + opp blind reserves
    for lvl in range(3):
        before = sorted(list(s.decks[lvl]) +
                        [ci for ci, bl in zip(s.reserved[1], s.reserved_blind[1])
                         if bl and E.LEVEL_OF[ci] - 1 == lvl])
        after = sorted(list(d.decks[lvl]) +
                       [ci for ci, bl in zip(d.reserved[1], d.reserved_blind[1])
                        if bl and E.LEVEL_OF[ci] - 1 == lvl])
        assert before == after


# ─── MCTS smoke (uniform evaluator, no torch) ─────────────────────────────────

def _uniform_eval(feats, masks):
    p = masks.astype(np.float64)
    p /= p.sum(axis=1, keepdims=True)
    return p, np.zeros(len(feats))


def test_mcts_full_selfplay_game_with_uniform_net():
    rng = random.Random(11)
    s = E.new_game(rng)
    for ply in range(400):
        if s.phase == E.OVER:
            break
        search = M.Search(s, rng, add_noise=True)
        visits = search.run(_uniform_eval, 50)
        legal = set(E.legal_actions(s))
        assert all(n == 0 for a, n in enumerate(visits) if a not in legal)
        assert sum(visits) > 0
        a = M.pick_action(visits, rng, temperature=1.0 if ply < 10 else 0.0)
        assert a in legal
        E.apply(s, a)
    assert s.phase == E.OVER
    assert s.winner in (0, 1, E.WIN_DRAW)


def test_mcts_finds_forced_winning_buy():
    """Last move of the game (opponent already triggered the final round at 15
    points): only buying the reserved 5-pointer wins. The search must
    concentrate its visits on that buy."""
    rng = random.Random(13)
    s = _fresh()
    s.points[0] = 11
    s.points[1] = 15
    s.final_trigger = 1  # game resolves right after seat 0's action
    five_pt = next(ci for ci in range(70, 90) if E.PTS[ci] == 5)
    for lvl in range(3):
        if five_pt in s.decks[lvl]:
            s.decks[lvl].remove(five_pt)
    s.reserved[0].append(five_pt)
    s.reserved_blind[0].append(False)
    s.tokens[0][:] = [7, 7, 7, 7, 7, 5]
    search = M.Search(s, rng, add_noise=False)
    visits = search.run(_uniform_eval, 300)
    buy_a = E.A_BUY_RESV + 0
    assert visits[buy_a] == max(visits)
    assert visits[buy_a] > 150  # majority of simulations on the only win


# ─── net round-trip (torch optional) ──────────────────────────────────────────

def test_net_forward_and_evaluator():
    torch = pytest.importorskip("torch")
    from games.spender.ai.az import net as N

    net = N.SpenderNet()
    s = _fresh()
    x = F.encode(s)[None, :]
    mask = np.array(A.legal_mask(s))[None, :]
    evaluate = N.make_evaluator(net)
    p, v = evaluate(x, mask)
    assert p.shape == (1, E.N_ACTIONS)
    assert abs(p[0].sum() - 1.0) < 1e-5
    assert p[0][~mask[0]].sum() == 0.0
    assert -1.0 <= v[0] <= 1.0
