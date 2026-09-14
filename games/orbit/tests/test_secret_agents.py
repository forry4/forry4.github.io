"""The Secret Agents mini-expansion.

WHY IT EXISTS AT ALL: every archived BGA table that carries card identities is a
Secret Agents table -- 0 of 40 are expansion-free, and 32 of them have one of
these ten cards in the opening deal. Without them a replay of a real game stalls
before its first decision, so the expansion is a prerequisite for using the
corpus at all, not a feature.

WHAT THESE TESTS ARE FOR: the soak in ``test_expansion_games_never_break_state``
proves only that nothing crashes and nothing leaks. Seven of the ten programs
reuse a base-game primitive and three are new, and a wrong-but-legal program
crashes nothing -- so every card gets its own assertion on the NUMBERS it moves.
"""

from __future__ import annotations

import random

from games.orbit import engine as E
from games.orbit.cards import ALL_CARDS, CARDS, EXPANSION_CARDS

from .test_engine import finish_mulligan, resolve_randomly


def _armed(card_id, *, seed=5, sides=None):
    """A mulliganed expansion game with ``card_id`` in the mover's hand.

    Swaps the card in rather than dealing for it, the way ``test_engine`` does,
    so conservation still holds and the test does not depend on a lucky deal.
    """

    game = E.new_game(["A", "B"], seed=seed, secret_agents=True,
                      configuration=sides or {"robot": 1, "human": 1, "animod": 1})
    finish_mulligan(game)
    pid = game["turn_pid"]
    hand = game["players"][pid]["hand"]
    if card_id not in hand:
        displaced = hand[0]
        hand[0] = card_id
        game["agent_deck"][game["agent_deck"].index(card_id)] = displaced
    return game, pid, game["players"][pid]


def _recruit(game, pid, card_id):
    assert E.apply_move(game, pid, {"action": "recruit", "card_id": card_id})[0]


def _sign(game, pid):
    """Influence is signed from ``order[0]``'s perspective."""

    return 1 if pid == game["order"][0] else -1


# ── the pool ────────────────────────────────────────────────────────────────

def test_expansion_is_ten_cards_and_off_by_default():
    assert len(EXPANSION_CARDS) == 10
    assert sorted(EXPANSION_CARDS) == [119, 120, 219, 220, 319, 320, 419, 420, 519, 520]
    assert not set(EXPANSION_CARDS) & set(CARDS)
    assert len(ALL_CARDS) == 100

    base = E.new_game(["A", "B"], seed=1)
    assert base["expansion"] is False
    assert sorted(E.deck_composition(base)) == sorted(CARDS)
    held = list(base["agent_deck"]) + [c for p in base["players"].values() for c in p["hand"]]
    assert not set(held) & set(EXPANSION_CARDS)

    game = E.new_game(["A", "B"], seed=1, secret_agents=True)
    assert game["expansion"] is True
    assert sorted(E.deck_composition(game)) == sorted(ALL_CARDS)
    held = list(game["agent_deck"]) + [c for p in game["players"].values() for c in p["hand"]]
    assert sorted(held) == sorted(ALL_CARDS)


def test_a_save_written_before_the_expansion_still_validates():
    """``expansion`` is absent from every existing row, and absent means base."""

    game = E.new_game(["A", "B"], seed=4)
    del game["expansion"]
    assert sorted(E.deck_composition(game)) == sorted(CARDS)
    E.validate_state(game)


# ── the seven that reuse a base-game primitive ──────────────────────────────

def test_119_raises_both_players_to_eight_credits_and_never_lowers():
    """S1mm0ns: "The 2 players go up to 8 Credits" -- a floor, not a set."""

    game, pid, player = _armed(119)
    other = game["players"][E._opponent(game, pid)]
    player["credits"], other["credits"] = 2, 20
    _recruit(game, pid, 119)
    resolve_randomly(game)
    assert player["credits"] == 8          # 119 costs 0, so the floor is exact
    assert other["credits"] == 20          # already above it: untouched
    E.validate_state(game)


def test_419_raises_both_players_to_two_zenithium():
    game, pid, player = _armed(419)
    other = game["players"][E._opponent(game, pid)]
    player["zenithium"], other["zenithium"] = 0, 5
    _recruit(game, pid, 419)
    resolve_randomly(game)
    assert player["zenithium"] == 2
    assert other["zenithium"] == 5
    E.validate_state(game)


def test_219_only_offers_tracks_on_the_opponents_side():
    """Dandy Müller's ``1,7,1`` is card 312's second half at amount 1."""

    game, pid, _ = _armed(219)
    sign = _sign(game, pid)
    # Put mercury on our side and jupiter on theirs; venus/mars/terra stay neutral.
    game["influence"].update({"mercury": sign, "venus": 0, "terra": 0,
                              "mars": 0, "jupiter": -sign})
    # The universal +1 for the card's own planet has a FIXED planet, so the drain
    # resolves it without asking and stops on this card's actual choice.
    _recruit(game, pid, 219)
    assert game["pending"]["queue"][0]["type"] == "influence"
    offered = {m["planet"] for m in E.legal_moves(game, game["pending_pid"])
               if m.get("planet")}
    assert offered == {"jupiter"}, offered
    resolve_randomly(game)
    E.validate_state(game)


def test_319_develops_a_lowest_track_and_charges_for_it():
    """Célestin Petit is card 214's ``lowest`` develop at full price (rule 9,4,0)."""

    game, pid, player = _armed(319)
    player["technology"] = {"robot": 0, "human": 3, "animod": 2}
    player["zenithium"] = 6
    _recruit(game, pid, 319)
    resolve_randomly(game)
    assert player["technology"]["robot"] == 1, player["technology"]
    assert player["technology"]["human"] == 3 and player["technology"]["animod"] == 2
    assert player["zenithium"] == 5, "a level-1 development costs 1 Zenithium"
    E.validate_state(game)


def test_320_offers_exactly_two_pairs_and_moves_both_of_the_chosen_one():
    game, pid, _ = _armed(320)
    sign = _sign(game, pid)
    game["influence"].update({p: 0 for p in game["influence"]})
    _recruit(game, pid, 320)
    assert game["pending"]["queue"][0]["type"] == "choose_branch"
    moves = E.legal_moves(game, game["pending_pid"])
    assert len(moves) == 2, moves
    assert E.apply_move(game, game["pending_pid"], moves[1])[0]   # Mars and Jupiter
    resolve_randomly(game)
    assert game["influence"]["mars"] == sign
    assert game["influence"]["jupiter"] == sign
    assert game["influence"]["mercury"] == 0 and game["influence"]["venus"] == 0
    E.validate_state(game)


def test_519_discards_the_whole_hand_and_pays_five_credits():
    game, pid, player = _armed(519)
    player["credits"] = 0
    rest = [card for card in player["hand"] if card != 519]
    assert rest, "the test needs cards to discard"
    _recruit(game, pid, 519)
    resolve_randomly(game)
    # The turn ends and the hand refills, so assert on where the OLD cards went.
    assert all(card in game["agent_discard"] for card in rest), (rest, game["agent_discard"])
    assert not set(rest) & set(player["hand"])
    assert player["credits"] == 5
    E.validate_state(game)


def test_420_gives_the_opponent_influence_off_mars_then_takes_two_and_the_gold_badge():
    """W1ll1s: ``1,-4,-2`` is card 402's give-to-opponent at amount 2."""

    game, pid, _ = _armed(420)
    opponent = E._opponent(game, pid)
    game["influence"].update({p: 0 for p in game["influence"]})
    game["leader"] = {"owner": None, "level": 0}
    _recruit(game, pid, 420)
    # First sub-decision: the gift, which may not land on Mars.
    task = game["pending"]["queue"][0]
    assert task["type"] == "influence" and task["target"] == "opponent"
    offered = {m["planet"] for m in E.legal_moves(game, game["pending_pid"])
               if m.get("planet")}
    assert "mars" not in offered, offered
    resolve_randomly(game)
    assert game["leader"]["owner"] == pid and game["leader"]["level"] == 2
    moved = {p: v for p, v in game["influence"].items() if v}
    assert any(v * _sign(game, opponent) > 0 for v in moved.values()), moved
    E.validate_state(game)


# ── the three that needed new vocabulary ────────────────────────────────────

def test_120_reads_the_OPPONENTS_badge_not_ours():
    """Princess Uxmal's ``31,1,1`` is byte-identical to technology 29's."""

    game, pid, _ = _armed(120)
    opponent = E._opponent(game, pid)

    # Ours: the conditional half is skipped.
    game["leader"] = {"owner": pid, "level": 1}
    _recruit(game, pid, 120)
    resolve_randomly(game)
    assert not game.get("pending")

    # Theirs: two adjacent planets move.
    game, pid, _ = _armed(120, seed=6)
    opponent = E._opponent(game, pid)
    game["leader"] = {"owner": opponent, "level": 1}
    game["influence"].update({p: 0 for p in game["influence"]})
    _recruit(game, pid, 120)
    assert any(t["type"] == "two_adjacent" for t in game["pending"]["queue"]), \
        game["pending"]["queue"]
    resolve_randomly(game)
    sign = _sign(game, pid)
    gained = [p for p, v in game["influence"].items() if v * sign > 0]
    assert len(gained) >= 2, game["influence"]
    E.validate_state(game)


def test_220_reads_the_OPPONENTS_credits():
    game, pid, _ = _armed(220)
    other = game["players"][E._opponent(game, pid)]
    sign = _sign(game, pid)

    other["credits"] = 14                       # one short of the 15 threshold
    game["influence"].update({p: 0 for p in game["influence"]})
    _recruit(game, pid, 220)
    resolve_randomly(game)
    poor = sum(abs(v) for v in game["influence"].values())

    game, pid, _ = _armed(220, seed=6)
    other = game["players"][E._opponent(game, pid)]
    other["credits"] = 15
    game["influence"].update({p: 0 for p in game["influence"]})
    _recruit(game, pid, 220)
    resolve_randomly(game)
    rich = sum(abs(v) for v in game["influence"].values())
    assert rich == poor + 1, (poor, rich)
    E.validate_state(game)


def test_520_reads_the_OPPONENTS_zenithium_and_uses_a_different_track():
    game, pid, _ = _armed(520)
    other = game["players"][E._opponent(game, pid)]

    other["zenithium"] = 2                      # below the threshold
    game["influence"].update({p: 0 for p in game["influence"]})
    _recruit(game, pid, 520)
    resolve_randomly(game)
    poor = {p for p, v in game["influence"].items() if v}

    game, pid, _ = _armed(520, seed=6)
    other = game["players"][E._opponent(game, pid)]
    other["zenithium"] = 3
    game["influence"].update({p: 0 for p in game["influence"]})
    _recruit(game, pid, 520)
    resolve_randomly(game)
    rich = {p for p, v in game["influence"].items() if v}
    assert len(rich) == len(poor) + 1, (poor, rich)
    E.validate_state(game)


def test_raise_to_is_a_floor_for_both_seats_at_once():
    """The one genuinely new primitive, isolated from any card."""

    game = E.new_game(["A", "B"], seed=9, secret_agents=True)
    finish_mulligan(game)
    first, second = game["order"]
    game["players"][first]["credits"] = 1
    game["players"][second]["credits"] = 30
    E._begin_resolution(
        game, first, [{"type": "raise_to", "resource": "credits", "amount": 8}], "test")
    assert game["players"][first]["credits"] == 8
    assert game["players"][second]["credits"] == 30


# ── the net ─────────────────────────────────────────────────────────────────

def test_expansion_games_never_break_state():
    """Random full games with per-move validation, reaching all ten cards.

    The recruit counts are asserted because ``recruit`` is the ONLY action that
    resolves a card's effect -- a soak that only ever spent these cards on Leader
    or Technology would pass without running a single new program.
    """

    recruited = {card_id: 0 for card_id in EXPANSION_CARDS}
    for seed in range(60):
        rng = random.Random(seed * 7919 + 3)
        game = E.new_game(["A", "B"], seed=seed, configuration="random",
                          secret_agents=True)
        for _ in range(2000):
            if E.is_over(game):
                break
            pid = (game["pending_pid"] if game.get("pending")
                   else next(p for p in game["players"] if p not in game["mulligan_done"])
                   if game["phase"] == "mulligan" else game["turn_pid"])
            moves = E.legal_moves(game, pid)
            assert moves, f"seed {seed} stalled"
            move = rng.choice(moves)
            if move["action"] == "recruit" and int(move.get("card_id", 0)) in recruited:
                recruited[int(move["card_id"])] += 1
            assert E.apply_move(game, pid, move)[0]
            E.validate_state(game)
        else:
            raise AssertionError(f"seed {seed} never ended")
    assert all(recruited.values()), recruited
