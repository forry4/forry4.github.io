"""Parity + rule tests for the AZ fast engine (games/spender/ai/az/engine.py).

The differential test drives random games through BOTH engines — the new
compact-state engine and the incumbent main._sim_apply_move — asserting
identical canonical state after every move. Sub-phase decisions (discards,
multi-noble picks) are auto-resolved by the incumbent; the driver mirrors its
choices into the new engine so trajectories stay identical.

Deck-top (blind) reserves are excluded from the differential run because
_sim_apply_move never implemented them (only the human WS handler does); they
get dedicated unit tests instead, matched to the handler's semantics.
"""
import random

import pytest

from games.spender import main
from games.spender.ai.az import engine as E
from games.spender.ai.az import actions as A

PIDS = ("p0", "p1")


# ─── Canonical projections ────────────────────────────────────────────────────

def proj_old(g: dict) -> dict:
    players = []
    for pid in g["order"]:
        ps = g["players"][pid]
        bon = main.bonuses_from(ps["purchased"])
        players.append({
            "tokens": [ps["tokens"].get(c, 0) for c in main.GEM_COLORS] + [ps["tokens"].get("gold", 0)],
            "bonuses": [bon.get(c, 0) for c in main.GEM_COLORS],
            "points": main._calc_points(ps),
            "purchased_n": len(ps["purchased"]),
            "reserved": sorted(c["id"] for c in ps["reserved"]),
            "nobles": sorted(n["id"] for n in ps["nobles"]),
        })
    w = g.get("winner")
    return {
        "bank": [g["bank"].get(c, 0) for c in main.GEM_COLORS] + [g["bank"].get("gold", 0)],
        "players": players,
        "board": [c["id"] if c else None
                  for lk in ("L1", "L2", "L3") for c in g["board"][lk]],
        "decks": [[c["id"] for c in g["decks"][lk]] for lk in ("L1", "L2", "L3")],
        "turn": g["turn"],
        "over": g.get("phase") == "over",
        "winner": sorted(w) if isinstance(w, list) else w,
    }


def proj_new(s: E.State) -> dict:
    players = []
    for seat in (0, 1):
        players.append({
            "tokens": s.tokens[seat][:],
            "bonuses": s.bonuses[seat][:],
            "points": s.points[seat],
            "purchased_n": s.purchased_n[seat],
            "reserved": sorted(E.CARD_NAME[ci] for ci in s.reserved[seat]),
            "nobles": sorted(E.NOBLE_NAME[ni] for ni in s.nobles_won[seat]),
        })
    if s.winner == E.WIN_DRAW:
        winner = sorted(PIDS)
    elif s.winner in (0, 1):
        winner = PIDS[s.winner]
    else:
        winner = None
    return {
        "bank": s.bank[:],
        "players": players,
        "board": [E.CARD_NAME[ci] if ci >= 0 else None for ci in s.board],
        "decks": [[E.CARD_NAME[ci] for ci in s.decks[lvl]] for lvl in range(3)],
        "turn": PIDS[s.turn],
        "over": s.phase == E.OVER,
        "winner": winner,
    }


# ─── Differential test ────────────────────────────────────────────────────────

def _mirror_subphases(s: E.State, old: dict, seat: int,
                      old_tokens_before: dict, old_nobles_before: list) -> None:
    """After applying the same main-phase move to both engines, replay the
    incumbent's auto-resolved discards / noble pick into the new engine."""
    pid = PIDS[seat]
    ps = old["players"][pid]
    if s.phase == E.DISCARD:
        # Incumbent already discarded down to <=10; mirror the exact colors.
        for i, cname in enumerate(A.COLOR_NAMES):
            extra = s.tokens[seat][i] - ps["tokens"].get(cname, 0)
            for _ in range(extra):
                assert (E.A_DISCARD + i) in E.legal_actions(s)
                E.apply(s, E.A_DISCARD + i)
        assert s.phase != E.DISCARD, "discard mirroring did not resolve the phase"
    if s.phase == E.NOBLE:
        before = {n["id"] for n in old_nobles_before}
        gained = [n["id"] for n in ps["nobles"] if n["id"] not in before]
        assert len(gained) == 1
        slot_action = next(
            E.A_NOBLE + k for k, slot in enumerate(s.pending_nobles)
            if E.NOBLE_NAME[s.nobles[slot]] == gained[0]
        )
        E.apply(s, slot_action)


@pytest.mark.parametrize("seed", range(20))
def test_differential_random_games(seed):
    """10 random games per seed batch x 20 seeds = 200 full games."""
    rng = random.Random(seed)
    for g_i in range(10):
        s = E.new_game(rng)
        old = E.to_game_dict(s, PIDS)
        assert proj_old(old) == proj_new(s)

        for _ply in range(600):
            if s.phase == E.OVER:
                break
            seat = s.turn
            pid = PIDS[seat]
            acts = [a for a in E.legal_actions(s)
                    if not (E.A_RES_DECK <= a < E.A_BUY_BOARD)]  # no blind reserves
            a = rng.choice(acts)
            mv = A.action_to_move(s, a)

            ps_old = old["players"][pid]
            tokens_before = dict(ps_old["tokens"])
            nobles_before = list(ps_old["nobles"])

            main._sim_apply_move(old, pid, mv)
            E.apply(s, a)
            _mirror_subphases(s, old, seat, tokens_before, nobles_before)

            assert proj_old(old) == proj_new(s), \
                f"divergence at ply {_ply} (seed={seed}, game={g_i}, action={A.action_name(a)})"

        assert (s.phase == E.OVER) == (old.get("phase") == "over")


# ─── Targeted rule unit tests ─────────────────────────────────────────────────

def _fresh(seed=1):
    return E.new_game(random.Random(seed))


def test_gold_counts_toward_token_cap():
    s = _fresh()
    s.tokens[0][:] = [2, 2, 2, 2, 1, 1]  # 10 total incl. gold
    assert sum(s.tokens[0]) == 10
    a = E.A_RES_BOARD + 0
    assert a in E.legal_actions(s)
    E.apply(s, a)  # reserve grants a gold -> 11 -> discard phase
    assert s.phase == E.DISCARD
    assert s.turn == 0  # turn not advanced until discard resolves
    legal = E.legal_actions(s)
    assert E.A_DISCARD + 5 in legal  # gold itself is discardable
    E.apply(s, E.A_DISCARD + 0)
    assert s.phase == E.PLAY and s.turn == 1  # back to 10 -> turn finished


def test_take2_same_needs_bank_of_4():
    s = _fresh()
    s.bank[0] = 3
    legal = E.legal_actions(s)
    assert E.A_TAKE2S + 0 not in legal
    assert E.A_TAKE1 + 0 in legal
    s.bank[0] = 4
    assert E.A_TAKE2S + 0 in E.legal_actions(s)


def test_take_color_requires_bank():
    s = _fresh()
    s.bank[2] = 0
    for a in E.legal_actions(s):
        if a < E.A_PASS:
            mv = A.action_to_move(s, a)
            assert "green" not in mv["colors"]


def test_final_round_equal_turns_trigger_seat0():
    s = _fresh()
    s.points[0] = 15
    E.apply(s, E.legal_actions(s)[0])  # seat 0 acts, hits trigger
    assert s.final_trigger == 0
    assert s.phase != E.OVER  # seat 1 still gets a turn
    assert s.turn == 1
    E.apply(s, [a for a in E.legal_actions(s) if a < E.A_PASS][0])
    assert s.phase == E.OVER


def test_final_round_trigger_seat1_ends_immediately():
    s = _fresh()
    s.turn = 1
    s.points[1] = 15
    E.apply(s, [a for a in E.legal_actions(s) if a < E.A_PASS][0])
    assert s.final_trigger == 1
    assert s.phase == E.OVER  # seat 0 already had an equal number of turns


def test_winner_tiebreak_fewest_purchased_then_draw():
    s = _fresh()
    s.points[:] = [15, 15]
    s.purchased_n[:] = [5, 7]
    E._resolve_winner(s)
    assert s.winner == 0
    s2 = _fresh()
    s2.points[:] = [15, 15]
    s2.purchased_n[:] = [6, 6]
    E._resolve_winner(s2)
    assert s2.winner == E.WIN_DRAW


def test_deck_exhaustion_leaves_empty_slot():
    s = _fresh()
    s.decks[2].clear()
    target = E.A_BUY_BOARD + 8  # an L3 slot
    ci = s.board[8]
    s.tokens[0][:] = [7, 7, 7, 7, 7, 5]  # afford anything
    s.bank[5] = 0
    assert target in E.legal_actions(s)
    E.apply(s, target)
    assert s.board[8] == -1
    assert s.purchased_n[0] == 1
    assert s.bonuses[0][E.BONUS[ci]] == 1
    assert E.A_RES_DECK + 2 not in E.legal_actions(s)  # empty deck: no blind reserve


def test_reserve_without_bank_gold_grants_none():
    s = _fresh()
    s.bank[5] = 0
    E.apply(s, E.A_RES_BOARD + 4)
    assert s.tokens[0][5] == 0
    assert len(s.reserved[0]) == 1
    assert s.turn == 1


def test_blind_deck_reserve_pops_deck_top_and_flags():
    s = _fresh()
    top = s.decks[1][-1]
    E.apply(s, E.A_RES_DECK + 1)
    assert s.reserved[0] == [top]
    assert s.reserved_blind[0] == [True]
    assert s.tokens[0][5] == 1  # gold granted


def test_reserve_cap_3():
    s = _fresh()
    s.reserved[0].extend([0, 1, 2])
    s.reserved_blind[0].extend([False] * 3)
    legal = E.legal_actions(s)
    assert all(not (E.A_RES_BOARD <= a < E.A_BUY_BOARD) for a in legal)


def _nobles_requiring_white():
    """Noble ids that need white (BONUS color 0), highest white-req first.
    Derived from NOBLE_REQ so these tests don't hardcode the card data."""
    nids = [nid for nid in range(E.N_NOBLES) if E.NOBLE_REQ[nid][0] > 0]
    return sorted(nids, key=lambda n: -E.NOBLE_REQ[n][0])


def test_multi_noble_enters_choice_phase():
    s = _fresh()
    # Two nobles with the SAME white requirement: seat 0 set one white short of
    # both, so a single white-bonus buy makes both claimable at once.
    whites = _nobles_requiring_white()
    n_a = whites[0]
    n_b = next(n for n in whites[1:] if E.NOBLE_REQ[n][0] == E.NOBLE_REQ[n_a][0])
    s.nobles = [n_a, n_b, -1]
    ra, rb = E.NOBLE_REQ[n_a], E.NOBLE_REQ[n_b]
    bonuses = [max(ra[i], rb[i]) for i in range(5)]
    bonuses[0] -= 1  # one white short of both
    s.bonuses[0][:] = bonuses
    slot = next(i for i, ci in enumerate(s.board) if ci >= 0 and E.BONUS[ci] == 0)
    s.tokens[0][:] = [7, 7, 7, 7, 7, 5]
    E.apply(s, E.A_BUY_BOARD + slot)
    assert s.phase == E.NOBLE
    assert len(s.pending_nobles) == 2
    assert s.turn == 0
    pts_before = s.points[0]
    E.apply(s, E.A_NOBLE + 0)
    assert s.points[0] == pts_before + 3
    assert len(s.nobles_won[0]) == 1
    assert s.phase in (E.PLAY, E.OVER) and (s.phase == E.OVER or s.turn == 1)
    # The unchosen noble is still on the board
    assert sum(1 for ni in s.nobles if ni >= 0) == 1


def test_single_noble_autoclaims():
    s = _fresh()
    n_a = _nobles_requiring_white()[0]
    s.nobles = [n_a, -1, -1]
    bonuses = list(E.NOBLE_REQ[n_a])
    bonuses[0] -= 1  # one white short of the only noble
    s.bonuses[0][:] = bonuses
    slot = next(i for i, ci in enumerate(s.board) if ci >= 0 and E.BONUS[ci] == 0)
    s.tokens[0][:] = [7, 7, 7, 7, 7, 5]
    E.apply(s, E.A_BUY_BOARD + slot)
    assert s.phase != E.NOBLE
    assert s.nobles_won[0] == [n_a]
    assert s.nobles[0] == -1


def test_buy_spends_colored_then_gold_and_returns_to_bank():
    s = _fresh()
    # Find a board card and give exact tokens with a gold deficit of 1.
    slot, ci = next((i, ci) for i, ci in enumerate(s.board)
                    if ci >= 0 and sum(E.COST[ci]) >= 3)
    cost = E.COST[ci]
    toks = [max(0, cost[i] - 1) if cost[i] > 0 else 0 for i in range(5)]
    deficit = sum(1 for i in range(5) if cost[i] > 0)
    s.tokens[0][:] = toks + [deficit]
    bank_before = s.bank[:]
    E.apply(s, E.A_BUY_BOARD + slot)
    assert s.tokens[0] == [0, 0, 0, 0, 0, 0]
    for i in range(5):
        assert s.bank[i] == bank_before[i] + toks[i]
    assert s.bank[5] == bank_before[5] + deficit


def test_win_points_21_engine():
    """21-point mode: win_points carried by new_game/clone/dict round-trip; final round
    triggers at >=21 (not 16-20); defaults to 15 (incl. old saves without the key)."""
    s = E.new_game(random.Random(1), win_points=21)
    assert s.win_points == 21
    assert s.clone().win_points == 21
    g = E.to_game_dict(s)
    assert g["win_points"] == 21
    assert E.from_game_dict(g).win_points == 21
    g_old = {k: v for k, v in g.items() if k != "win_points"}  # pre-feature save
    assert E.from_game_dict(g_old).win_points == 15
    assert E.new_game(random.Random(1)).win_points == 15
    s.points[0] = 18
    s.final_trigger = -1
    E._finish_turn(s, 0)
    assert s.final_trigger == -1, "must not trigger at 18/21"
    s.points[0] = 21
    s.final_trigger = -1
    s.turn = 0
    E._finish_turn(s, 0)
    assert s.final_trigger == 0, "must trigger at 21/21"
