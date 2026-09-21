from __future__ import annotations

import copy
import random

from games.orbit import engine as E
from games.orbit.cards import BONUS_POOL, CARDS, FACTIONS, PLANETS, TECHNOLOGIES


def finish_mulligan(game):
    for pid in list(game["players"]):
        assert E.apply_move(game, pid, {"action": "mulligan", "card_ids": []})[0]


def resolve_randomly(game, seed=1, cap=500):
    rng = random.Random(seed)
    for _ in range(cap):
        if not game.get("pending") or E.is_over(game):
            return
        pid = game["pending_pid"]
        moves = E.legal_moves(game, pid)
        assert moves
        assert E.apply_move(game, pid, rng.choice(moves))[0]
    raise AssertionError("effect resolution did not terminate")


def test_reference_is_complete():
    assert len(CARDS) == 90
    assert len(TECHNOLOGIES) == 30
    assert len(BONUS_POOL) == 16
    for planet in PLANETS:
        for faction in FACTIONS:
            assert sum(c["planet"] == planet and c["faction"] == faction for c in CARDS.values()) == 6


def test_setup_and_mulligan_contract():
    game = E.new_game(["A", "B"], seed=8)
    assert game["phase"] == "mulligan"
    assert game["board_sides"] == {"robot": 1, "human": 1, "animod": 1}
    assert {len(p["hand"]) for p in game["players"].values()} == {4}
    assert all(p["credits"] == 12 and p["zenithium"] == 1 for p in game["players"].values())
    assert game["influence"]["terra"] == -1
    assert len([v for v in game["planet_bonus"].values() if v]) == 5
    assert len([v for v in game["technology_bonus"].values() if v]) == 3
    first = game["order"][0]
    replaced = list(game["players"][first]["hand"][:2])
    assert E.apply_move(game, first, {"action": "mulligan", "card_ids": sorted(replaced)})[0]
    other = game["order"][1]
    assert E.apply_move(game, other, {"action": "mulligan", "card_ids": []})[0]
    assert game["phase"] == "play" and game["turn_pid"] == first
    E.validate_state(game)


def test_recruit_discount_base_influence_and_effect():
    game = E.new_game(["A", "B"], seed=2)
    finish_mulligan(game)
    pid = game["turn_pid"]
    # Cresus: Venus, cost 1, +6 Credits after the universal Venus influence.
    card_id = 209
    old = game["players"][pid]["hand"][0]
    game["players"][pid]["hand"][0] = card_id
    game["agent_deck"][game["agent_deck"].index(card_id)] = old
    assert E.apply_move(game, pid, {"action": "recruit", "card_id": card_id})[0]
    assert game["players"][pid]["credits"] == 17
    direction = 1 if pid == game["order"][0] else -1
    assert game["influence"]["venus"] == direction
    E.validate_state(game)


def test_technology_cascades_level_two_bonus_then_level_one():
    game = E.new_game(["A", "B"], seed=11, configuration={"robot": 1, "human": 1, "animod": 1})
    finish_mulligan(game)
    pid = game["turn_pid"]
    player = game["players"][pid]
    player["technology"]["robot"] = 1
    player["zenithium"] = 10
    token = game["technology_bonus"]["robot"]
    card_id = next((cid for cid in player["hand"] if CARDS[cid]["faction"] == "robot"), None)
    if card_id is None:
        card_id = next(c["id"] for c in CARDS.values() if c["faction"] == "robot")
        displaced = player["hand"][0]
        player["hand"][0] = card_id
        game["agent_deck"][game["agent_deck"].index(card_id)] = displaced
    assert E.apply_move(game, pid, {"action": "technology", "card_id": card_id})[0]
    resolve_randomly(game)
    assert player["technology"]["robot"] == 2
    assert game["technology_bonus"]["robot"] is None
    assert token in game["bonus_discard"]
    assert game["leader"]["owner"] == pid
    E.validate_state(game)


def test_capture_bonus_and_all_three_victory_conditions():
    for captures in (
        ["mars", "mars"],
        ["mercury", "venus", "terra"],
        ["mercury", "mercury", "venus", "terra"],
    ):
        game = E.new_game(["A", "B"], seed=17)
        finish_mulligan(game)
        pid = game["turn_pid"]
        game["players"][pid]["captured"] = captures
        target = "mars" if captures[0] == "mars" else ("jupiter" if len(set(captures)) >= 3 else "venus")
        game["influence"][target] = 3
        game["planet_bonus"][target] = None
        E._gain_influence(game, pid, target, 1)
        assert E.is_over(game) and E.winner(game) == pid


def test_all_planets_technology_resolves_from_jupiter_back_to_mercury(monkeypatch):
    game = E.new_game(["A", "B"], seed=19, secret_agents=True)
    game["order"] = ["A", "B"]
    game["phase"] = "play"
    game["turn_pid"] = "A"
    game["pending"] = {
        "source": "test",
        "queue": [{"type": "all_planets", "amount": 1, "actor": "A"}],
        "context": {},
    }
    seen = []
    monkeypatch.setattr(E, "_gain_influence",
                        lambda _game, _pid, planet, _amount:
                        seen.append(planet) or [])
    E._drain_pending(game)
    assert seen == list(reversed(E.PLANETS))


def test_capture_bonus_can_wait_behind_the_remaining_cascade():
    game = E.new_game(["A", "B"], seed=23, secret_agents=True)
    game["order"] = ["A", "B"]
    game["phase"] = "play"
    game["turn_pid"] = "B"
    game["influence"]["mercury"] = -3
    game["planet_bonus"]["mercury"] = 3
    first = {"type": "influence", "amount": 1, "target": "self", "actor": "B"}
    adjacent = {"type": "adjacent_three", "center": 1, "neighbor": 1, "actor": "B"}
    game["pending"] = {
        "source": "test",
        "queue": [first, adjacent,
                  {"type": "steal", "resource": "credits", "amount": 3, "actor": "B"}],
        "context": {},
    }
    E._apply_task_choice(game, first, {"action": "choose", "planet": "mercury"})
    queue = game["pending"]["queue"]
    assert queue[0]["type"] == "adjacent_three"
    assert queue[-1].get("_bonus") is True


def test_hidden_information_is_redacted_from_a_real_pending_game():
    game = E.new_game(["A", "B"], seed=4)
    finish_mulligan(game)
    me = game["turn_pid"]
    other = E._opponent(game, me)
    view = E.player_view(game, me)
    assert "agent_deck" not in view and "bonus_deck" not in view and "rng_state" not in view
    assert all(card.get("hidden") for card in view["players"][other]["hand"])
    assert all("name" in card for card in view["players"][me]["hand"])


def test_exile_tier_is_mandatory_when_a_threshold_is_available():
    game = E.new_game(["A", "B"], seed=4)
    finish_mulligan(game)
    pid = game["turn_pid"]
    game["players"][pid]["columns"]["mercury"] = [101, 102, 103, 104]
    game["pending_pid"] = pid
    game["pending"] = {
        "source": "test",
        "queue": [{"type": "exile_tier", "actor": pid, "planet": "mercury", "reward": "zenithium"}],
        "context": {},
    }
    moves = E.legal_moves(game, pid)
    assert {move["tier"] for move in moves} == {2, 4}


def test_seeded_random_soak_plays_complete_games():
    for seed in range(25):
        rng = random.Random(seed * 97)
        game = E.new_game(["A", "B"], seed=seed, configuration="random")
        for _ in range(1000):
            if E.is_over(game):
                break
            if game["phase"] == "mulligan":
                pid = next(p for p in game["players"] if p not in game["mulligan_done"])
            else:
                pid = game["pending_pid"] if game.get("pending") else game["turn_pid"]
            moves = E.legal_moves(game, pid)
            assert moves
            assert E.apply_move(game, pid, rng.choice(moves))[0]
            E.validate_state(game)
        assert E.is_over(game)


def test_illegal_move_is_atomic():
    game = E.new_game(["A", "B"], seed=2)
    before = copy.deepcopy(game)
    assert E.apply_move(game, "A", {"action": "recruit", "card_id": 999}) == (False, "Illegal move")
    assert game == before


# ── The display log ──────────────────────────────────────────────────────────
# THE LOG IS THE ONLY NARRATION IN THE GAME, and a client that renders it is not
# proof it says anything: the old one wrote a line per card play and left every
# disc, Credit, token and stolen Agent to be inferred from a board that had
# already changed.  These tests hold it to "nothing happens silently".

def _log_text(entry):
    if "parts" not in entry:
        return entry.get("message", "")
    return "".join(p if isinstance(p, str) else p.get("v", "") for p in entry["parts"])


def _tokens(entry, key):
    return [p[key] for p in entry.get("parts", []) if isinstance(p, dict) and key in p]


def _material(game):
    """Everything a player can see change on the table."""

    return {
        "influence": dict(game["influence"]),
        "leader": dict(game["leader"]),
        "planet_bonus": dict(game["planet_bonus"]),
        "technology_bonus": dict(game["technology_bonus"]),
        "players": {
            pid: {
                "credits": p["credits"],
                "zenithium": p["zenithium"],
                "hand": len(p["hand"]),
                "captured": list(p["captured"]),
                "technology": dict(p["technology"]),
                "columns": {k: list(v) for k, v in p["columns"].items()},
            }
            for pid, p in game["players"].items()
        },
    }


def _random_game_steps(seed, cap=800):
    """Play a random game, yielding (game, before, after, entries_written).

    The entries are COLLECTED FROM ``_log``, never sliced off ``game["log"]``:
    a long game hits ``LOG_CAP`` and the eviction shifts every index, which made
    a first cut of this read an empty slice and "prove" that a badge had moved
    with nothing written down.
    """

    game = E.new_game(["A", "B"], names={"A": "Ada", "B": "Bo"}, seed=seed)
    rng = random.Random(seed * 31 + 5)
    written = []
    original = E._log

    def recording(g, *parts, **data):
        written.append(list(parts))
        return original(g, *parts, **data)

    E._log = recording
    try:
        for _ in range(cap):
            if E.is_over(game):
                return
            if game["phase"] == "mulligan":
                pid = next(p for p in game["players"] if p not in game["mulligan_done"])
            else:
                pid = game["pending_pid"] if game.get("pending") else game["turn_pid"]
            moves = E.legal_moves(game, pid)
            assert moves
            before = _material(game)
            written.clear()
            assert E.apply_move(game, pid, rng.choice(moves))[0]
            yield game, before, _material(game), [{"parts": p} for p in written]
    finally:
        E._log = original


def test_every_material_change_is_written_down():
    """No disc, Credit, token, badge or Agent moves without a line naming it.

    The categories are checked SEPARATELY on purpose: "some entry was appended"
    passes on a turn that logged the card play and silently moved four discs,
    which is exactly the log this replaced.
    """

    seen = {k: 0 for k in ("influence", "credits", "zenithium", "captured",
                           "leader", "technology", "columns", "bonus", "hand")}
    for seed in range(12):
        for game, before, after, fresh in _random_game_steps(seed):
            text = " ".join(_log_text(entry) for entry in fresh)
            planets = {p for entry in fresh for p in _tokens(entry, "p")}
            factions = {p["f"] for entry in fresh for p in entry.get("parts", [])
                        if isinstance(p, dict) and "f" in p}
            cards = {c for entry in fresh for c in _tokens(entry, "c")}
            bonuses = {b for entry in fresh for b in _tokens(entry, "b")}

            for planet in PLANETS:
                if before["influence"][planet] != after["influence"][planet]:
                    seen["influence"] += 1
                    assert planet in planets, f"{planet} disc moved unlogged: {text}"
            if before["leader"] != after["leader"]:
                seen["leader"] += 1
                assert "Leader badge" in text, f"badge moved unlogged: {text}"
            for slot in list(before["planet_bonus"]) + list(before["technology_bonus"]):
                key = "planet_bonus" if slot in before["planet_bonus"] else "technology_bonus"
                if before[key][slot] != after[key][slot]:
                    seen["bonus"] += 1
                    assert bonuses, f"a bonus token left {slot} unlogged: {text}"
            for pid, name in (("A", "Ada"), ("B", "Bo")):
                was, now = before["players"][pid], after["players"][pid]
                if was["credits"] != now["credits"]:
                    seen["credits"] += 1
                    assert "Credit" in text and name in text, f"{name} Credits unlogged: {text}"
                if was["zenithium"] != now["zenithium"]:
                    seen["zenithium"] += 1
                    assert "Zenithium" in text and name in text, f"{name} Zenithium unlogged: {text}"
                if was["captured"] != now["captured"]:
                    seen["captured"] += 1
                    assert "CAPTURES" in text, f"{name} capture unlogged: {text}"
                if was["technology"] != now["technology"]:
                    seen["technology"] += 1
                    changed = {f for f in FACTIONS if was["technology"][f] != now["technology"][f]}
                    assert changed <= factions, f"{name} technology unlogged: {text}"
                if was["columns"] != now["columns"]:
                    seen["columns"] += 1
                    assert cards, f"{name} column changed with no Agent named: {text}"
                if was["hand"] != now["hand"]:
                    seen["hand"] += 1
                    assert name in text, f"{name} hand size changed unlogged: {text}"
    # Non-vacuous: every category must actually have been exercised.
    assert all(seen.values()), seen


def test_the_log_never_names_a_card_nobody_can_see():
    """A named Agent must be public AT THE MOMENT THE LINE IS WRITTEN.

    The log is broadcast to both seats unredacted, so naming a card still in a
    hand or in the deck would hand over hidden information.  Checked inside
    ``_log`` rather than after the move: a reshuffle later in the same action
    can legitimately pull a just-discarded Agent back into the hidden deck.
    """

    named = 0
    original = E._log

    def checked(game, *parts, **data):
        nonlocal named
        for part in parts:
            if not isinstance(part, dict) or "c" not in part:
                continue
            named += 1
            public = set(game["agent_discard"])
            for player in game["players"].values():
                for column in player["columns"].values():
                    public.update(column)
            assert part["c"] in public, f"log named hidden Agent {part['c']}: {parts}"
        return original(game, *parts, **data)

    E._log = checked
    try:
        for seed in range(6):
            for _ in _random_game_steps(seed):
                pass
    finally:
        E._log = original
    assert named > 50, f"fixture must actually name Agents, saw {named}"


def test_a_planet_runs_out_of_discs_after_four_captures():
    """The box holds four discs per planet, so a fifth capture has nothing to take.

    This is a COMPONENT COUNT rather than a sentence of rules text -- no published rules
    say what happens when a planet empties, because it is treated as not arising. It
    arises: playing 600 random games, four wanted a fifth disc from one planet, and in all
    four the winning capture was that impossible one (a 2-2 split empties the planet, and
    the capture that would break the tie has nothing left to take).

    The corpus agrees and is the reason this is implemented rather than merely suspected:
    across 189 archived BGA games the most any planet ever yielded is exactly FOUR. A
    distribution that stops dead on the physical limit is what a hard cap looks like.
    """
    game = E.new_game(["a", "b"], seed=3)
    finish_mulligan(game)
    planet = PLANETS[0]
    assert E._discs_left(game, planet) == E.DISCS_PER_PLANET == 4

    for taken in range(1, 5):
        game["influence"][planet] = 0
        E._capture(game, "a" if taken % 2 else "b", planet)
        assert E._discs_left(game, planet) == 4 - taken
        assert game["influence"][planet] is None
        # the end-of-turn refill puts a fresh disc out only while one remains
        for p in list(game["captured_this_turn"]):
            if game["influence"][p] is None and E._discs_left(game, p) > 0:
                game["influence"][p] = 0
        game["captured_this_turn"] = []

    assert E._discs_left(game, planet) == 0
    assert game["influence"][planet] is None, "the fifth disc does not exist"
    # ...and influence aimed at an empty planet is wasted rather than crashing or capturing
    assert E._gain_influence(game, "a", planet, 3) == []
    assert game["influence"][planet] is None


def test_the_disc_count_survives_a_save_made_before_it_was_tracked():
    # Expand/contract: an older game has no `discs` map. Reconstruct it from what has
    # already been taken rather than handing the planet a full four again.
    game = E.new_game(["a", "b"], seed=3)
    finish_mulligan(game)
    planet = PLANETS[0]
    game["influence"][planet] = 0
    E._capture(game, "a", planet)
    game["influence"][planet] = 0
    E._capture(game, "b", planet)
    del game["discs"]
    assert E._discs_left(game, planet) == 2, "derived from the captures, not reset to 4"
