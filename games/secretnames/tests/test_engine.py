"""The SecretNames rules, including all 26 cases the specification requires.

Every test below builds its position by WRITING THE KEY CARD, not by hunting a
seed that happens to produce the state it wants. That is deliberate and is the
repo's zero-state-reachability rule applied before it can bite: a "find a seed
where the guesser's next word is an assassin" helper either loops or bails, and
a bail is a green tick over a test that proved nothing.

`_rigged` therefore takes an explicit pair layout and asserts it is a LEGAL key
card on the way past, so a test cannot quietly exercise a board the real game
could never deal.
"""
from __future__ import annotations

import random

import pytest

from games.secretnames import engine as E
from games.secretnames.words import BOARD_SIZE

A, B = 0, 1


def _fresh(seed: int = 5, turns: int = E.DEFAULT_TURNS) -> dict:
    return E.new_game(["pa", "pb"], {"pa": "Ann", "pb": "Bo"},
                      rng=random.Random(seed), turns=turns)


def _assert_legal_key(keys) -> None:
    for side in keys:
        assert side.count(E.AGENT) == 9
        assert side.count(E.ASSASSIN) == 3
        assert side.count(E.BYSTANDER) == 13
    assert len(E.agent_positions(keys)) == E.TOTAL_AGENTS
    assert sum(1 for i in range(BOARD_SIZE)
               if keys[0][i] == E.AGENT and keys[1][i] == E.AGENT) == 3


def _rigged(pairs: list[tuple[str, str]], *, clue_giver: int = A,
            turns: int = E.DEFAULT_TURNS) -> dict:
    """A game on a hand-written key card.

    `pairs` is 25 (sideA, sideB) tuples in board order. It must be a legal key,
    which is asserted here rather than hoped for — a rigged board that could not
    be dealt tests a game nobody plays.
    """
    assert len(pairs) == BOARD_SIZE
    game = _fresh(turns=turns)
    game["keys"] = [[p[0] for p in pairs], [p[1] for p in pairs]]
    _assert_legal_key(game["keys"])
    game["clue_giver"] = clue_giver
    game["phase"] = "clue"
    game["found"] = []
    game["bystanders"] = [[], []]
    game["clues"] = []
    game["log"] = []
    return game


def _canonical_pairs() -> list[tuple[str, str]]:
    """The published composition laid out in a fixed, readable order.

    Positions 0-2   agent/agent        (the three shared agents)
    Positions 3-7   agent/bystander    (seat A's private agents)
    Positions 8-12  bystander/agent    (seat B's private agents)
    Position  13    agent/assassin
    Position  14    assassin/agent
    Position  15    assassin/assassin
    Position  16    assassin/bystander
    Position  17    bystander/assassin
    Positions 18-24 bystander/bystander
    """
    out: list[tuple[str, str]] = []
    for pair, count in E.KEY_COMPOSITION:
        out.extend([pair] * count)
    return out


def _clue(game, seat=None, word="OCEAN", number=2):
    seat = game["clue_giver"] if seat is None else seat
    ok, err = E.apply_move(game, game["seats"][seat],
                           {"type": "clue", "word": word, "number": number})
    assert ok, err
    return ok


def _guess(game, seat, pos):
    return E.apply_move(game, game["seats"][seat], {"type": "guess", "pos": pos})


# ── 1-3: the key card ────────────────────────────────────────────────────────
@pytest.mark.parametrize("seed", range(40))
def test_a_generated_key_has_nine_agents_three_assassins_and_thirteen_bystanders(seed):
    _assert_legal_key(E.make_key_card(random.Random(seed)))


@pytest.mark.parametrize("seed", range(40))
def test_the_union_of_both_sides_is_exactly_fifteen_agents(seed):
    keys = E.make_key_card(random.Random(seed))
    assert len(E.agent_positions(keys)) == 15


@pytest.mark.parametrize("seed", range(40))
def test_exactly_three_agent_positions_are_shared(seed):
    keys = E.make_key_card(random.Random(seed))
    assert sum(1 for i in range(BOARD_SIZE)
               if keys[0][i] == E.AGENT and keys[1][i] == E.AGENT) == 3


def test_every_generated_key_is_a_different_board_but_the_composition_never_moves():
    """A generator that returned one fixed key would pass every check above."""
    keys = [tuple(E.make_key_card(random.Random(s))[0]) for s in range(30)]
    assert len(set(keys)) > 20


# ── 4-5: which key resolves a guess ──────────────────────────────────────────
def test_player_a_guess_resolves_against_key_b():
    game = _rigged(_canonical_pairs(), clue_giver=B)
    # Position 8 is (bystander, agent): an agent for seat B's side, which is the
    # side that answers seat A's guesses.
    assert game["keys"][A][8] == E.BYSTANDER and game["keys"][B][8] == E.AGENT
    _clue(game, B)
    ok, err = _guess(game, A, 8)
    assert ok, err
    assert 8 in game["found"], "seat A's guess was answered by seat A's own key"


def test_player_b_guess_resolves_against_key_a():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    assert game["keys"][A][3] == E.AGENT and game["keys"][B][3] == E.BYSTANDER
    _clue(game, A)
    ok, err = _guess(game, B, 3)
    assert ok, err
    assert 3 in game["found"]


def test_resolve_role_is_the_only_inversion_and_it_points_at_the_other_seat():
    game = _rigged(_canonical_pairs())
    for pos in range(BOARD_SIZE):
        assert E.resolve_role(game, A, pos) == game["keys"][B][pos]
        assert E.resolve_role(game, B, pos) == game["keys"][A][pos]


# ── 6-8: correct guesses keep the turn ───────────────────────────────────────
def test_a_correct_agent_guess_does_not_end_the_turn():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    _guess(game, B, 0)
    assert game["phase"] == "guess"
    assert game["clue_giver"] == A
    assert game["turns_remaining"] == E.DEFAULT_TURNS


def test_several_correct_guesses_may_happen_in_one_turn_and_cost_one_token():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A, number=1)
    # Seat A's agents (their key) are 0,1,2 (shared), 3-7 (private) and 13.
    for pos in (0, 1, 2, 3, 4, 5):
        ok, err = _guess(game, B, pos)
        assert ok, err
        assert game["phase"] == "guess"
    assert game["guesses_this_turn"] == 6
    assert game["turns_remaining"] == E.DEFAULT_TURNS
    E.apply_move(game, game["seats"][B], {"type": "end_turn"})
    assert game["turns_remaining"] == E.DEFAULT_TURNS - 1


def test_the_clue_number_does_not_cap_the_guess_count():
    """There is no `number + 1` rule in Duet, which is the single most commonly
    imported mistake from the base game."""
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A, number=1)
    for pos in (0, 1, 2, 3, 4, 5, 6, 7):
        ok, err = _guess(game, B, pos)
        assert ok, err
    assert game["guesses_this_turn"] == 8
    assert game["phase"] == "guess"


# ── 9-11: bystanders ─────────────────────────────────────────────────────────
def test_a_bystander_ends_the_ordinary_turn():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    _guess(game, B, 0)
    ok, err = _guess(game, B, 18)          # bystander/bystander
    assert ok, err
    assert game["phase"] == "clue"
    assert game["clue"] is None
    assert game["clue_giver"] == B


def test_a_normal_turn_costs_exactly_one_token_however_it_ends():
    for ender in ("bystander", "stop"):
        game = _rigged(_canonical_pairs(), clue_giver=A)
        _clue(game, A)
        _guess(game, B, 0)
        _guess(game, B, 1)
        if ender == "bystander":
            _guess(game, B, 18)
        else:
            E.apply_move(game, game["seats"][B], {"type": "end_turn"})
        assert game["turns_remaining"] == E.DEFAULT_TURNS - 1, ender


def test_a_bystander_for_one_player_stays_available_to_the_other():
    """Position 8 is a bystander from seat A's side and an AGENT from seat B's,
    so seat B hitting it must not remove it from seat A's board."""
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    _guess(game, B, 0)
    ok, err = _guess(game, B, 8)           # bystander on key A, which answers B
    assert ok, err
    assert 8 in game["bystanders"][B]
    assert 8 not in game["found"]
    # Now seat B clues and seat A guesses the same position — it is an agent.
    _clue(game, B)
    ok, err = _guess(game, A, 8)
    assert ok, err
    assert 8 in game["found"]


def test_a_found_agent_cannot_be_guessed_again_by_either_player():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    _guess(game, B, 0)
    assert _guess(game, B, 0) == (False, "that agent is already found")
    E.apply_move(game, game["seats"][B], {"type": "end_turn"})
    _clue(game, B)
    assert _guess(game, A, 0) == (False, "that agent is already found")


# ── 13-14: the two endings ───────────────────────────────────────────────────
def test_an_assassin_loses_immediately():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    # Position 14 is (assassin, agent): an assassin on key A, which answers B.
    ok, err = _guess(game, B, 14)
    assert ok, err
    assert game["phase"] == "lost"
    assert game["loss_reason"] == "assassin"
    assert game["fatal_pos"] == 14
    assert E.is_over(game)
    assert E.apply_move(game, game["seats"][A], {"type": "clue", "word": "X", "number": 1}) \
        == (False, "the game is over")


def test_the_fifteenth_unique_agent_wins_immediately_without_spending_a_token():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    agents = E.agent_positions(game["keys"])
    game["found"] = agents[:-1]
    last = agents[-1]
    giver = A if game["keys"][A][last] == E.AGENT else B
    game["clue_giver"] = giver
    _clue(game, giver)
    before = game["turns_remaining"]
    ok, err = _guess(game, 1 - giver, last)
    assert ok, err
    assert game["phase"] == "won"
    assert game["turns_remaining"] == before


def test_finishing_all_nine_agents_on_one_side_does_not_win():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    game["found"] = [i for i in range(BOARD_SIZE) if game["keys"][A][i] == E.AGENT]
    assert len(game["found"]) == 9
    assert not E.all_found(game)
    assert game["phase"] == "clue"
    assert not E.is_over(game)


# ── 16-18: who clues, and stopping ───────────────────────────────────────────
def test_a_player_whose_side_is_complete_gives_no_more_clues():
    game = _rigged(_canonical_pairs(), clue_giver=B)
    # Every agent on seat A's key found except the one seat B is about to take,
    # so the turn ends with side A exhausted.
    a_agents = [i for i in range(BOARD_SIZE) if game["keys"][A][i] == E.AGENT]
    game["found"] = a_agents[:-1]
    last_a = a_agents[-1]
    assert game["keys"][B][last_a] in (E.AGENT, E.BYSTANDER, E.ASSASSIN)
    _clue(game, B)
    # Seat A guesses, answered by key B. Take a plain B-side agent first, then
    # end the turn — side A completes when `last_a` is taken, so do that one.
    game["found"].append(last_a)
    _guess(game, A, 8)                      # bystander/agent -> agent for A
    E.apply_move(game, game["seats"][A], {"type": "end_turn"})
    assert E.can_clue(game, A) is False
    assert game["clue_giver"] == B, "the exhausted side was handed the clue anyway"


def test_end_turn_is_refused_before_the_first_guess_and_allowed_after_one():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    assert E.apply_move(game, game["seats"][B], {"type": "end_turn"}) \
        == (False, "make at least one guess first")
    _guess(game, B, 0)
    ok, err = E.apply_move(game, game["seats"][B], {"type": "end_turn"})
    assert ok, err
    assert game["turns_remaining"] == E.DEFAULT_TURNS - 1


def test_only_the_guesser_may_guess_or_end_the_turn():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    assert _guess(game, A, 0) == (False, "it is not your turn to guess")
    assert E.apply_move(game, game["seats"][A], {"type": "end_turn"}) \
        == (False, "only the guesser can end the turn")


# ── 19-24: sudden death ──────────────────────────────────────────────────────
def _to_sudden_death(turns: int = 1) -> dict:
    """Burn the last token the ordinary way, so the transition is the real one."""
    game = _rigged(_canonical_pairs(), clue_giver=A, turns=9)
    game["turns_remaining"] = turns
    _clue(game, A)
    _guess(game, B, 0)
    E.apply_move(game, game["seats"][B], {"type": "end_turn"})
    return game


def test_spending_the_last_token_enters_sudden_death_rather_than_losing():
    game = _to_sudden_death()
    assert game["phase"] == "sudden_death"
    assert game["loss_reason"] is None
    assert not E.is_over(game)


def test_no_new_clue_is_accepted_during_sudden_death():
    game = _to_sudden_death()
    assert E.apply_move(game, game["seats"][A],
                        {"type": "clue", "word": "OCEAN", "number": 2}) \
        == (False, "not waiting for a clue")
    assert E.apply_move(game, game["seats"][B],
                        {"type": "clue", "word": "OCEAN", "number": 2}) \
        == (False, "not waiting for a clue")


def test_either_player_may_guess_in_sudden_death_and_a_correct_one_continues():
    game = _to_sudden_death()
    ok, err = _guess(game, B, 1)            # agent/agent
    assert ok, err
    assert game["phase"] == "sudden_death"
    ok, err = _guess(game, A, 8)            # agent on key B, answering seat A
    assert ok, err
    assert game["phase"] == "sudden_death"
    assert {1, 8} <= set(game["found"])


def test_a_sudden_death_bystander_loses_immediately():
    game = _to_sudden_death()
    ok, err = _guess(game, B, 18)
    assert ok, err
    assert game["phase"] == "lost"
    assert game["loss_reason"] == "sudden_death_mistake"


def test_a_sudden_death_assassin_loses_immediately():
    game = _to_sudden_death()
    ok, err = _guess(game, B, 14)
    assert ok, err
    assert game["phase"] == "lost"
    assert game["loss_reason"] == "assassin"


def test_finding_the_last_agent_in_sudden_death_wins():
    game = _to_sudden_death()
    agents = E.agent_positions(game["keys"])
    last = next(p for p in agents if p not in game["found"])
    game["found"] = [p for p in agents if p != last]
    guesser = B if game["keys"][A][last] == E.AGENT else A
    ok, err = _guess(game, guesser, last)
    assert ok, err
    assert game["phase"] == "won"


# ── 25: passing ──────────────────────────────────────────────────────────────
def test_passing_permanently_removes_that_player_from_clue_giving():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    before = game["turns_remaining"]
    ok, err = E.apply_move(game, game["seats"][A], {"type": "pass"})
    assert ok, err
    assert game["passed"] == [True, False]
    assert game["clue_giver"] == B, "passing hands the CURRENT turn over"
    assert game["turns_remaining"] == before, "a pass is not a turn"
    # ...and it survives a full turn cycle: B clues, A guesses, A ends the turn,
    # and the clue comes back to B rather than alternating to the passed seat.
    _clue(game, B)
    _guess(game, A, 8)
    E.apply_move(game, game["seats"][A], {"type": "end_turn"})
    assert game["clue_giver"] == B
    assert E.apply_move(game, game["seats"][A],
                        {"type": "clue", "word": "X", "number": 1}) \
        == (False, "you are not the clue-giver this turn")


def test_both_players_unable_to_clue_enters_sudden_death_with_tokens_left():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    E.apply_move(game, game["seats"][A], {"type": "pass"})
    ok, err = E.apply_move(game, game["seats"][B], {"type": "pass"})
    assert ok, err
    assert game["phase"] == "sudden_death"
    assert game["turns_remaining"] == E.DEFAULT_TURNS


def test_a_player_cannot_pass_twice_or_out_of_turn():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    assert E.apply_move(game, game["seats"][B], {"type": "pass"}) \
        == (False, "you are not the clue-giver this turn")
    E.apply_move(game, game["seats"][A], {"type": "pass"})
    assert E.apply_move(game, game["seats"][A], {"type": "pass"}) \
        == (False, "you are not the clue-giver this turn")


# ── 26: the private key never reaches the wrong client ───────────────────────
def test_a_player_view_carries_only_that_players_key():
    game = _fresh()
    for pid, seat in (("pa", A), ("pb", B)):
        view = E.player_view(game, pid)
        assert view["key"] == game["keys"][seat]
        assert "keys" not in view
        assert view["reveal"] is None
        other = game["keys"][1 - seat]
        # The other side must not appear anywhere in the payload, in any shape.
        assert other not in [v for v in view.values() if isinstance(v, list)]


def test_the_view_never_reports_the_other_seats_remaining_agents():
    game = _fresh()
    view = E.player_view(game, "pa")
    assert view["your_agents_left"] == 9
    assert "their_agents_left" not in view
    # `exhausted` is a boolean at zero, which §17 makes public; it must not be
    # a count and it must not be true while agents remain.
    assert view["exhausted"] == [False, False]


def test_a_spectator_gets_no_key_at_all():
    game = _fresh()
    view = E.player_view(game, "nobody")
    assert view["you"] is None and view["key"] is None
    assert view["your_agents_left"] is None


def test_both_keys_are_revealed_only_once_the_game_is_over():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    assert E.player_view(game, "pa")["reveal"] is None
    _clue(game, A)
    _guess(game, B, 14)                      # assassin
    view = E.player_view(game, "pa")
    assert view["reveal"] == [game["keys"][0], game["keys"][1]]
    assert view["fatal_pos"] == 14


# ── Clue legality (the mechanical half only — §7) ────────────────────────────
def test_a_clue_may_not_be_a_word_still_showing_on_the_board():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    on_board = game["words"][20]
    assert E.apply_move(game, game["seats"][A],
                        {"type": "clue", "word": on_board.lower(), "number": 1}) \
        == (False, "that word is still on the board")


def test_a_covered_board_word_becomes_a_legal_clue():
    """Only UNCOVERED words are off limits — a found agent is no longer on the
    board, so its word is available like any other."""
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    _guess(game, B, 0)
    E.apply_move(game, game["seats"][B], {"type": "end_turn"})
    ok, err = E.apply_move(game, game["seats"][B],
                           {"type": "clue", "word": game["words"][0], "number": 1})
    assert ok, err


@pytest.mark.parametrize("word,ok", [
    ("OCEAN", True), ("Loch-Ness", True), ("NEW YORK", True), ("O.K.", True),
    ("", False), ("   ", False), ("one two three", False), ("a" * 25, False),
    ("!!", False), ("<script>", False),
])
def test_only_mechanical_clue_shapes_are_enforced(word, ok):
    game = _rigged(_canonical_pairs(), clue_giver=A)
    got, _ = E.apply_move(game, game["seats"][A],
                          {"type": "clue", "word": word, "number": 1})
    assert got is ok, word


@pytest.mark.parametrize("number,ok", [(0, True), (9, True), (-1, False),
                                       (10, False), ("two", False), (None, False)])
def test_the_clue_number_range_including_a_zero_clue(number, ok):
    game = _rigged(_canonical_pairs(), clue_giver=A)
    got, _ = E.apply_move(game, game["seats"][A],
                          {"type": "clue", "word": "TREE", "number": number})
    assert got is ok, number


def test_a_zero_clue_changes_nothing_mechanically():
    """'tree: 0' means "stay away from tree" and is otherwise an ordinary clue —
    the guesser may still guess, and those guesses resolve normally."""
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A, word="TREE", number=0)
    assert game["phase"] == "guess"
    ok, err = _guess(game, B, 0)
    assert ok, err
    assert game["phase"] == "guess"


# ── Action validation and hygiene ────────────────────────────────────────────
def test_a_stranger_can_do_nothing():
    game = _rigged(_canonical_pairs(), clue_giver=A)
    for move in ({"type": "clue", "word": "X", "number": 1}, {"type": "guess", "pos": 0},
                 {"type": "end_turn"}, {"type": "pass"}):
        assert E.apply_move(game, "mallory", move) == (False, "not a player in this game")


@pytest.mark.parametrize("pos", [-1, 25, 999, "3.5", None, "x"])
def test_an_out_of_range_position_is_refused(pos):
    game = _rigged(_canonical_pairs(), clue_giver=A)
    _clue(game, A)
    ok, _ = _guess(game, B, pos)
    assert ok is False


def test_an_unknown_action_is_refused():
    game = _rigged(_canonical_pairs())
    assert E.apply_move(game, "pa", {"type": "teleport"}) == (False, "unknown action")
    assert E.apply_move(game, "pa", {}) == (False, "unknown action")


def test_new_game_requires_exactly_two_seats():
    for seats in ([], ["a"], ["a", "b", "c"]):
        with pytest.raises(ValueError):
            E.new_game(seats, rng=random.Random(1))


def test_an_unknown_turn_count_falls_back_to_the_standard_nine():
    assert _fresh(turns=7)["turns_max"] == 9
    assert _fresh(turns=11)["turns_max"] == 11


def test_the_game_dict_is_json_safe_and_holds_no_sets():
    import json
    game = _fresh()
    _clue(game)
    blob = json.dumps(game)
    assert json.loads(blob) == game


def test_abandoning_ends_the_run_without_a_winner():
    game = _fresh()
    E.abandon(game, "pa")
    assert game["phase"] == "lost" and game["loss_reason"] == "abandoned"
    assert "winner" not in game


# ── The no-RNG invariant ─────────────────────────────────────────────────────
def test_nothing_after_the_deal_draws_randomness(monkeypatch):
    """The engine persists no `rng_state` because it needs none. A future draw
    added anywhere past `new_game` must fail here rather than silently making
    saved games non-reproducible across a reload."""
    game = _rigged(_canonical_pairs(), clue_giver=A)

    def boom(*_a, **_k):                     # pragma: no cover - the trap
        raise AssertionError("the engine drew randomness after the deal")

    for name in ("random", "randrange", "randint", "choice", "shuffle", "sample"):
        monkeypatch.setattr(random, name, boom)

    _clue(game, A)
    _guess(game, B, 0)
    _guess(game, B, 18)                      # bystander -> end of turn
    _clue(game, B)
    _guess(game, A, 8)
    E.apply_move(game, game["seats"][A], {"type": "end_turn"})
    E.apply_move(game, game["seats"][B], {"type": "pass"})
    assert "rng_state" not in game


def test_a_full_random_game_always_terminates_in_a_legal_end_state():
    """A blind walk over every legal action from 200 real deals. It is not a
    strength check — it is the only thing that exercises the turn machine
    against boards this file did not hand-write, and it asserts the invariant
    that matters: the game always reaches won/lost and never leaves the phase
    machine in a state with no legal move."""
    for seed in range(200):
        rng = random.Random(seed)
        game = E.new_game(["pa", "pb"], rng=random.Random(seed * 7 + 1))
        for _ in range(4000):
            if E.is_over(game):
                break
            phase = game["phase"]
            if phase == "clue":
                seat = game["clue_giver"]
                if rng.random() < 0.04:
                    E.apply_move(game, game["seats"][seat], {"type": "pass"})
                else:
                    ok, err = E.apply_move(game, game["seats"][seat],
                                           {"type": "clue", "word": "CLUE", "number": 2})
                    assert ok, err
            else:
                seat = E.guesser(game) if phase == "guess" else rng.randrange(2)
                free = [i for i in range(BOARD_SIZE) if i not in set(game["found"])]
                if phase == "guess" and game["guesses_this_turn"] >= 1 and rng.random() < 0.3:
                    ok, err = E.apply_move(game, game["seats"][seat], {"type": "end_turn"})
                    assert ok, err
                    continue
                ok, err = E.apply_move(game, game["seats"][seat],
                                       {"type": "guess", "pos": rng.choice(free)})
                assert ok, err
        assert E.is_over(game), f"seed {seed} never finished"
        if game["phase"] == "won":
            assert len(game["found"]) == 15
        else:
            assert game["loss_reason"] in ("assassin", "sudden_death_mistake")
