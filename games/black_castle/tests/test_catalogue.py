"""Hold the generated card catalogue, and the engine's ops, to the printed game.

`catalogue.py` is GENERATED from `data/base_catalogue.json` by `tools/build_catalogue.py`.
Two things have to stay true for that to be worth anything, and each has a test here:

* the checked-in file must be what the generator currently produces (otherwise a hand edit
  silently becomes the catalogue), and
* every op the generator can emit must be one the engine actually implements (otherwise a
  card resolves to nothing at all, which no amount of play would make obvious).

The catalogue replaced placeholder data on 2026-09-20. Before that, stewards and diplomats
were built in loops keyed on `i % 3` with invented effects -- the port ran fine and played
a different game.
"""
from __future__ import annotations

import json
import os

from games.black_castle import cards, catalogue, engine
from games.black_castle.tools import build_catalogue

_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_the_checked_in_catalogue_is_what_the_generator_produces():
    # A hand edit to catalogue.py is not merely lost on the next run, it is caught here.
    assert build_catalogue.main(["--check"]) == 0


def test_every_op_the_data_can_carry_is_one_the_engine_implements():
    # The failure this prevents is silent: an unimplemented op falls off the end of
    # `_apply_effects` and the card does nothing, which looks exactly like a card that
    # was supposed to do nothing.
    source = open(os.path.join(_PKG, "engine.py"), encoding="utf-8").read()
    for op in build_catalogue.OPS:
        assert f'op == "{op}"' in source or f'"{op}"' in source, op

    # Scoped to the GENERATED cards. The Daimyo's Favor cards are still ours -- they
    # appear nowhere in the corpus, because BGA only ships one once a courtier reaches
    # the third floor -- so they still speak the older hand-written vocabulary.
    generated = (catalogue.STEWARDS + catalogue.DIPLOMATS + catalogue.DECREE_CARDS
                 + catalogue.STARTING_RESOURCE_CARDS + catalogue.STARTING_ACTION_CARDS)
    used = {e["op"] for card in generated
            for e in (card.get("light") or []) + (card.get("dark") or [])}
    used |= {card["lantern"]["op"] for card in generated if card.get("lantern")}
    assert used <= set(build_catalogue.OPS), sorted(used - set(build_catalogue.OPS))
    assert not (used & set(build_catalogue.TILE_ONLY_OPS)), "tile grammar on a card"
    # And the placeholder daimyo are the ONLY cards still outside it, so this stops
    # being a blanket exemption the moment anything else drifts.
    everywhere = {e["op"] for card in cards.ALL_CARDS.values()
                  for e in (card.get("light") or []) + (card.get("dark") or [])}
    assert everywhere - set(build_catalogue.OPS) <= {"influence", "move", "lantern"}


def test_the_catalogue_lands_on_the_printed_counts():
    assert len(catalogue.STEWARDS) == 15
    assert len(catalogue.DIPLOMATS) == 12
    assert len(catalogue.DECREE_CARDS) == 3
    # NINE starting resource cards, three backed with each of pearl / iron / food. This
    # read 8 until 2026-09-20 because the 20-log corpus never turned up typeArg 3 -- the
    # same "the data does not show it, so it is not there" mistake that once deleted the
    # 2-player dice rule.
    assert len(catalogue.STARTING_RESOURCE_CARDS) == 9
    backs = sorted(c["back"] for c in catalogue.STARTING_RESOURCE_CARDS)
    assert backs == ["food"] * 3 + ["iron"] * 3 + ["pearl"] * 3
    # THREE starting action cards, one per worker -- not the six we used to generate.
    assert len(catalogue.STARTING_ACTION_CARDS) == 3
    workers = sorted(e["worker"] for c in catalogue.STARTING_ACTION_CARDS
                     for e in c["light"] if e["op"] == "worker_action")
    assert workers == ["courtiers", "gardeners", "warriors"]
    assert cards.CARD_COUNTS["starting_resource"] == 9
    assert cards.CARD_COUNTS["starting_action"] == 3


def test_a_decree_is_a_lantern_reward_and_nothing_else():
    # All three carry no action block at all, which is also why the printed
    # `Gain <icon> Decree Card` texts name exactly coin, seal and vp.
    icons = sorted(c["lantern"]["op"] for c in catalogue.DECREE_CARDS)
    assert icons == ["gain"] * 3
    assert all(not c["blocks"] for c in catalogue.DECREE_CARDS)


def test_the_diamond_cards_are_the_cards_own_and_not_a_second_list():
    assert cards.DIAMOND_STEWARDS == (1, 3, 6, 8, 11, 14)
    assert cards.DIAMOND_DIPLOMATS == (1, 9, 12)
    assert sum(1 for c in catalogue.STEWARDS if c["diamond"]) == 6
    assert sum(1 for c in catalogue.DIPLOMATS if c["diamond"]) == 3


def test_every_block_records_which_rows_it_covers():
    # The castle die-colour rule selects a ROW, so this field is what that rule will read.
    # It is carried now so the rule can land without re-deriving the catalogue.
    rows = {"top", "middle", "bottom"}
    for card in catalogue.STEWARDS + catalogue.DIPLOMATS:
        assert card["blocks"], card["id"]
        for block in card["blocks"]:
            assert block["type"] in ("light", "dark"), card["id"]
            assert block["position"], card["id"]
            assert set(block["position"]) <= rows, card["id"]


def test_a_card_that_grants_any_resource_asks_instead_of_picking_one():
    # Ten of the sixty-eight cards say "gain a resource" without naming it. Resolving
    # that silently -- always food, say -- is the kind of divergence that never surfaces
    # as an error, so the generator keeps it as "any" and the engine must ASK.
    anyone = [c for c in cards.ALL_CARDS.values()
              for e in (c.get("light") or []) + (c.get("dark") or [])
              if e.get("op") == "gain" and e.get("resource") == "any"]
    assert anyone, "the catalogue should carry unnamed-resource gains"

    game = engine.new_game(["a", "b"], seed=3)
    pid = game["draft_queue"][0]
    engine._apply_effects(game, pid, [{"op": "gain", "resource": "any", "amount": 2}],
                          source="test")
    assert len(game["choice_queue"]) == 2, "two units means two separate picks"
    assert engine._promote_choice(game, pid)
    assert game["pending"]["kind"] == "choose_resource"

    before = dict(engine._player(game, pid)["resources"])
    moves = engine.legal_moves(game, pid)
    assert {m["resource"] for m in moves} == set(cards.RESOURCES)
    ok, err = engine.apply_move(game, pid, {"type": "choose_resource", "resource": "pearl"})
    assert ok, err
    assert engine._player(game, pid)["resources"]["pearl"] == before["pearl"] + 1
    # ...and the second pick is offered straight after, rather than being lost.
    assert game["pending"]["kind"] == "choose_resource"
    assert len(game["choice_queue"]) == 1


def test_the_draft_stays_open_until_a_granted_resource_is_chosen():
    # draft_queue is reversed(turn_order), so the LAST seat to draft is turn_order[0] --
    # the player about to take turn 1. Closing the draft over their unresolved choice
    # left it pending into the play phase and then handed them an `end_turn` for a turn
    # they had not taken.
    game = engine.new_game(["a", "b", "c"], seed=7)
    saw_choice = False
    for _ in range(40):
        if game["phase"] != "draft":
            break
        pending = game.get("pending") or {}
        if pending.get("kind") == "choose_resource":
            saw_choice = True
            assert game["phase"] == "draft", "the draft must not close over an owed pick"
            ok, err = engine.apply_move(
                game, pending["pid"], {"type": "choose_resource", "resource": "iron"})
            assert ok, err
            continue
        ok, err = engine.apply_move(game, game["draft_queue"][0],
                                    {"type": "draft", "index": 0})
        assert ok, err
    assert saw_choice, "seed 7 deals a card that grants an unnamed resource"
    assert game["phase"] == "play"
    assert not game.get("choice_queue")
    # The first turn is a real turn, not an `end_turn` left over from the draft.
    assert game["pending"] is None or game["pending"].get("kind") != "end_turn"


def test_a_worker_action_pays_the_currency_its_card_names():
    # A castle card charges SEALS to repeat a worker action; a yard tile charges COINS.
    # Both arrive as the same `qty` beside an icon, so a cost that lost its currency
    # would bill a tile's 3 coins to the seal track.
    game = engine.new_game(["a", "b"], seed=5)
    while game["phase"] == "draft":
        pending = game.get("pending") or {}
        if pending.get("kind") == "choose_resource":
            engine.apply_move(game, pending["pid"],
                              {"type": "choose_resource", "resource": "food"})
            continue
        engine.apply_move(game, game["draft_queue"][0], {"type": "draft", "index": 0})
    pid = game["turn_pid"]
    p = engine._player(game, pid)
    p["seals"], p["coins"] = 3, 9
    p["workers"]["warriors"]["domain"] = 2

    engine._apply_effects(game, pid, [{"op": "worker_action", "worker": "warriors",
                                       "cost": {"seals": 1}}], source="test")
    assert (p["seals"], p["coins"]) == (2, 9), "a seal price comes off the seals"
    engine._apply_effects(game, pid, [{"op": "worker_action", "worker": "warriors",
                                       "cost": {"coins": 3}}], source="test")
    assert (p["seals"], p["coins"]) == (2, 6), "a coin price comes off the coins"


def test_the_generator_refuses_a_template_it_has_no_op_for():
    # The whole contract: an unknown effect stops the build instead of being dropped.
    try:
        build_catalogue.translate({"description": "Summon a dragon", "args": {}}, "nowhere")
    except SystemExit as exc:
        assert "Summon a dragon" in str(exc) and "nowhere" in str(exc)
    else:
        raise AssertionError("an unknown template must stop the build")


def test_the_source_json_and_the_module_describe_the_same_cards():
    raw = json.load(open(os.path.join(_PKG, "data", "base_catalogue.json"), encoding="utf-8"))
    stewards = sum(1 for d in raw.values()
                   if d.get("kind") == "card" and d.get("type") == "steward")
    assert stewards == len(catalogue.STEWARDS)
    assert len(raw) == 68
