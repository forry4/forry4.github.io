"""Phase 5 serving boundary and live browser-AI safety gates."""

from __future__ import annotations

import asyncio
import copy
import json
from pathlib import Path

import pytest

from games.orbit import engine
from games.orbit.ai import serving
from games.orbit.ai.state import observation
from games.orbit.cards import CARDS
from games.orbit import main as m


class _FakeWS:
    def __init__(self):
        self.sent = []

    async def send_text(self, text):
        self.sent.append(json.loads(text))


@pytest.fixture(autouse=True)
def _isolate(monkeypatch):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    m.ROOMS.clear()
    m.ROOM_LOCK = asyncio.Lock()
    monkeypatch.setattr(m, "save_game", lambda *_a, **_k: None)
    monkeypatch.setattr(m, "_ensure_room_loaded", lambda rid: m.ROOMS.get(rid))
    yield
    loop.close()


def _game(seed=3):
    return engine.new_game(["human", "bot"], seed=seed)


def _room(seed=3):
    game = _game(seed)
    return {
        "players": {"human": "Human", "bot": "Bot"},
        "sockets": {},
        "status": "playing",
        "host": "human",
        "game": game,
        "meta": {},
        "vs_ai": True,
        "ai_player": "bot",
        "ai_difficulty": "hard",
        "seat_histories": m._new_live_histories(game),
        "ai_memory": {},
        "ai_budget_remaining_ms": m.CLIENT_AI_TURN_BUDGET_MS,
        "ai_turn_started_at": 100.0,
        "ai_decisions_this_turn": 0,
        "client_ai": False,
        "_ai_search": None,
        "_ai_pending_move": None,
        "_ai_pending_sent_at": None,
        "_bot_running": True,
    }


def test_bot_decisions_leave_time_for_board_feedback():
    assert m.BOT_FLOOR_SECONDS == pytest.approx(1.00)


def test_serving_manifest_and_choice_are_versioned_and_legal():
    game = _game()
    obs = observation(game, "human")
    legal = engine.legal_moves(game, "human")
    result = serving.choose_move(obs, legal, None, 5000, 17)
    assert result.move in legal
    assert result.diagnostics["abi_version"] == serving.SERVING_ABI_VERSION
    assert result.diagnostics["model_version"] == serving.MODEL_VERSION
    assert result.diagnostics["rules"] == serving.rules_fingerprint()
    assert serving.validate_manifest(serving.serving_manifest())["rules"] == serving.rules_fingerprint()


def test_easy_normal_and_hard_tiers_are_valid_and_legal():
    game = _game(19)
    obs = observation(game, "human")
    legal = engine.legal_moves(game, "human")
    assert m._valid_difficulty("random") == "easy"
    assert [m._valid_difficulty(value) for value in ("easy", "normal", "hard", "expert")] == [
        "easy", "normal", "hard", "expert"]
    assert serving.choose_normal_move(obs, legal, 23) in legal
    assert m._bot_move_sync(game, "human", 23, "easy") in legal
    assert m._bot_move_sync(game, "human", 23, "normal") in legal
    assert m._bot_move_sync(game, "human", 23, "hard") in legal
    # Expert searches in the browser; the SERVER's fallback for it is the Hard
    # ranker, because the fallback exists to answer fast and legally.
    assert m._bot_move_sync(game, "human", 23, "expert") in legal
    assert m._bot_move_sync(game, "human", 23, "expert") == m._bot_move_sync(game, "human", 23, "hard")


def test_arming_a_browser_turn_carries_the_tier_and_its_split_budget():
    """Actually ARM a decision for each browser tier.

    Nothing exercised `_client_bot_turn`'s arming path, so `"tier": difficulty`
    -- a name that lives in a different function -- raised NameError on every
    browser AI turn and shipped. The bot armed nothing, answered nothing, and
    sat on "Thinking..." forever, for Hard as much as Expert. Every other test
    here builds `_ai_search` by hand, which is exactly how a hand-built fixture
    can agree with a request the server can no longer construct.
    """

    async def arm(difficulty):
        room = _room()
        room["ai_difficulty"] = difficulty
        room["client_ai"] = True
        m.ROOMS["armed-room"] = room
        task = asyncio.ensure_future(m._client_bot_turn("armed-room"))
        try:
            # A DEADLINE, not an iteration count: a count's real budget depends on the
            # sleep's granularity (15ms on Windows vs ~1ms on Linux) and on how fast the
            # machine runs the bot, so the same count was patient here and short on a
            # loaded CI runner (the 2026-08-07 deploy block). It only pays when broken.
            deadline = asyncio.get_running_loop().time() + 60.0
            while asyncio.get_running_loop().time() < deadline:
                if room.get("_ai_search"):
                    return dict(room["_ai_search"])
                await asyncio.sleep(0.05)
            return None
        finally:
            task.cancel()
            m.ROOMS.pop("armed-room", None)

    loop = asyncio.get_event_loop()
    for difficulty in m.CLIENT_AI_TIERS:
        armed = loop.run_until_complete(arm(difficulty))
        assert armed is not None, f"{difficulty} never armed a request"
        assert armed["tier"] == difficulty
        # The worker searches THIS decision's slice, not the whole turn.
        assert armed["budget_ms"] == m.CLIENT_AI_MAIN_ACTION_MS
        assert armed["remaining_turn_budget"] == m.CLIENT_AI_TURN_BUDGET_MS
        assert armed["legal_moves"] and armed["observation"]["seat"] in (0, 1)


def test_each_tier_serves_the_bot_the_shifted_ladder_promises():
    """Pin the tier -> bot mapping after the 2026-09-11 shift.

    The whole suite passed while this mapping moved a rung, so nothing covered
    it. Easy is now the public-information ranker and the random opponent is off
    the product ladder entirely; both search tiers fall back to the effect-aware
    ranker server-side, because the search lives in the browser and the server
    owes a fast validated answer rather than a second search on the event loop.
    """
    game = _game(5)
    for pid in list(game["order"]):
        m.engine.apply_move(game, pid, {"action": "mulligan", "card_ids": []})
    pid = game["turn_pid"]
    served = {tier: m._bot_move_sync(copy.deepcopy(game), pid, 11, tier)
              for tier in m.AI_DIFFICULTIES}
    public = m.bot.choose_normal_fallback_move(copy.deepcopy(game), pid, 11)
    effect = m.bot.choose_fallback_move(copy.deepcopy(game), pid, 11)
    assert served["easy"] == public
    for tier in ("normal", "hard", "expert"):
        assert served[tier] == effect, f"{tier} served the wrong bot"
    # Non-vacuous only if the two rankers actually disagree on this position;
    # otherwise the assertions above would hold for any wiring at all.
    assert public != effect, "fixture cannot tell the two rankers apart"


def test_a_room_saved_before_the_shift_keeps_the_bot_it_started_against():
    """Rooms persist a tier NAME, and every name moved one rung stronger.

    Read literally, a game in progress would silently face a stronger opponent
    than the one it was started against. Rooms saved since the shift carry
    `ai_tier_generation`; anything without it is pre-shift and maps back.
    """
    for before, after in (("expert", "hard"), ("hard", "normal"),
                          ("normal", "easy"), ("easy", "easy")):
        assert m._loaded_difficulty({"ai_difficulty": before}) == after
    for tier in m.AI_DIFFICULTIES:
        stamped = {"ai_difficulty": tier, "ai_tier_generation": m.AI_TIER_GENERATION}
        assert m._loaded_difficulty(stamped) == tier
    # The remap is only safe because saving stamps the generation; without that
    # write every room would be demoted one rung on its next load, forever. The
    # persisted dict is built inline in `save_game`, so this reads the source.
    source = (Path(__file__).resolve().parents[1] / "main.py").read_text(encoding="utf-8")
    assert '"ai_tier_generation": AI_TIER_GENERATION,' in source, "saving no longer stamps the ladder"


def test_both_browser_tiers_search_and_only_expert_holds_one_world():
    """The worker must serve TWO searches, differing only in determinization.

    Hard resamples the hidden hand every simulation; Expert holds one coherent
    world for the whole call, which is the change that restores the tree. The
    worker is a shipped artifact rather than an import, so this reads it as text.
    """
    worker = (Path(__file__).resolve().parents[3] / "webapp/public/wasm/orbit-worker.js").read_text(encoding="utf-8")
    assert 'message.tier === "expert" ? 0 : 1' in worker, "the tier no longer picks a determinization period"
    assert '(message.tier === "expert" || message.tier === "hard")' in worker, "Hard must search too"
    assert m.CLIENT_AI_DETERMINIZATION == {"hard": 1, "expert": 0}
    assert set(m.CLIENT_AI_DETERMINIZATION) == set(m.CLIENT_AI_TIERS)


def test_an_unknown_tier_from_a_newer_bundle_clamps_up_not_down():
    """A newer client must never be silently handed the random bot.

    Pages and Render deploy independently, so a bundle offering a tier this build
    has not got is a normal release window, not corruption. Loading a persisted
    room keeps the old reading: there, an unknown tier is a RETIRED one.
    """
    assert m.AI_DIFFICULTIES[-1] == "expert", "the roster is ordered weakest to strongest"
    assert m._requested_difficulty("some-future-tier") == m.AI_DIFFICULTIES[-1]
    assert m._requested_difficulty("expert") == "expert"
    assert m._requested_difficulty("easy") == "easy"
    assert m._requested_difficulty("random") == "easy"
    assert m._requested_difficulty(None) == m.DEFAULT_DIFFICULTY
    # Persisted rooms keep coercing DOWN; an unknown tier there is retired.
    assert m._valid_difficulty("some-future-tier") == m.DEFAULT_DIFFICULTY


def test_expert_is_a_browser_tier_carrying_its_own_per_decision_allowance():
    """Expert reaches the worker as a tier, with the turn already split.

    The worker searches ``budget_ms``, not the whole-turn remainder: without the
    split the turn's first decision would spend everything and every follow-up
    would run zero simulations.
    """
    assert "expert" in m.CLIENT_AI_TIERS and "hard" in m.CLIENT_AI_TIERS
    assert m.CLIENT_AI_MAIN_ACTION_MS < m.CLIENT_AI_TURN_BUDGET_MS
    assert m.CLIENT_AI_FOLLOWUP_RESERVE_MS == m.CLIENT_AI_TURN_BUDGET_MS - m.CLIENT_AI_MAIN_ACTION_MS
    # The create modal must offer exactly the tiers the server accepts.
    picker = Path(__file__).resolve().parents[1] / "Orbit.jsx"
    source = picker.read_text(encoding="utf-8")
    # The picker's list lives in shared/botTiers.js (the profile page names tiers too).
    assert "import { ORBIT_AI_TIER_OPTIONS }" in source, "Orbit.jsx no longer renders the shared tier list"
    tiers = (Path(__file__).resolve().parents[3] / "shared" / "botTiers.js").read_text(encoding="utf-8")
    offered = tiers.split("const ORBIT_AI_TIER_OPTIONS")[1].split("\n];")[0]
    for tier in m.AI_DIFFICULTIES:
        assert f'value: "{tier}"' in offered, f"{tier} is accepted but not offered"
    for tier in m.CLIENT_AI_TIERS:
        assert f'"{tier}"' in source.split("const CLIENT_AI_TIERS")[1][:120], (
            f"{tier} is a browser tier but the client never arms a pool for it")


def test_hard_ties_are_stable_for_parallel_browser_workers():
    game = _game(11)
    obs = observation(game, "human")
    legal = engine.legal_moves(game, "human")
    choices = [serving.choose_move(obs, legal, None, 5000, seed).move
               for seed in (1, 2, 3, 4)]
    assert choices and all(choice == choices[0] for choice in choices)


def test_shipped_model_and_wasm_assets_match_the_python_manifest():
    root = Path(__file__).resolve().parents[3]
    asset = json.loads((root / "webapp/public/wasm/orbit-model.json").read_text(encoding="utf-8"))
    expected = serving.serving_manifest()
    for key in ("abi_version", "model_version", "encoder", "schema", "rules"):
        assert asset[key] == expected[key]
    # THE ENVELOPE IS NOT THE MODEL. Checking only the version fields let the shipped
    # asset drift from Python for real: between `ac097edf` and `fca6be36` the browser
    # served `choice_capture: 2.0` while Python had moved to 1.0, so the Expert ranked
    # every capture at double weight in the one place a player actually meets it. The
    # envelope matched the whole time, because the weights were never compared.
    assert asset["policy"] == serving.POLICY_WEIGHTS
    assert len(asset["cards"]) == len(CARDS) == 90
    for card_id, card in CARDS.items():
        assert asset["cards"][str(card_id)] == {
            "cost": card["cost"], "planet": card["planet"], "faction": card["faction"]}
    assert len(asset["card_effects"]) == len(CARDS) == 90
    assert asset["policy"]["effect"] > 0
    assert asset["bonus_policy_values"]["3"] == 4.0
    assert (root / "webapp/public/wasm/orbit-worker.js").is_file()
    assert (root / "webapp/public/wasm/orbit_core.js").is_file()
    assert (root / "webapp/public/wasm/orbit_core_bg.wasm").stat().st_size > 0


def test_serving_reuses_only_a_matching_legal_branch_and_bounds_memory():
    game = _game(5)
    obs = observation(game, "human")
    legal = engine.legal_moves(game, "human")
    first = serving.choose_move(obs, legal, None, 100, 1)
    second = serving.choose_move(obs, legal, first.memory, 0, 2)
    assert second.move == first.move
    assert second.diagnostics["reused_branch"]
    altered = [move for move in legal if move != first.move]
    if altered:
        altered_obs = copy.deepcopy(obs)
        altered_obs["legal_moves"] = altered
        third = serving.choose_move(altered_obs, altered, first.memory, 0, 3)
        assert third.move in altered
        assert not third.diagnostics["reused_branch"]
    huge = {"version": serving.SERVING_ABI_VERSION,
            "branches": {str(i): {"move": {"action": "x"} } for i in range(1000)},
            "history": {"events": [{"x": "y" * 1000} for _ in range(100)]}}
    bounded = serving.normalise_memory(huge)
    assert len(json.dumps(bounded)) <= serving.MAX_MEMORY_BYTES
    assert len(bounded["branches"]) <= serving.MAX_BRANCHES


def test_armed_request_is_scoped_and_contains_no_hidden_game_keys():
    room = _room()
    m.ROOMS["r1"] = room
    game = room["game"]
    legal = engine.legal_moves(game, "bot")
    obs = observation(game, "bot")
    room["client_ai"] = True
    room["_ai_search"] = {
        "protocol": m.CLIENT_AI_WIRE,
        "decision": 1,
        "position": serving.position_key(obs, legal),
        "seat": "bot",
        "schema": serving.SCHEMA_VERSION,
        "encoder": serving.ENCODER_VERSION,
        "rules": serving.rules_fingerprint(),
        "observation": obs,
        "legal_moves": copy.deepcopy(legal),
        "memory": serving.normalise_memory(None),
        "model_version": serving.MODEL_VERSION,
        "sent_at": 101.0,
    }
    human = json.dumps(m.mk_room_state("r1", viewer_pid="human"))
    bot = json.dumps(m.mk_room_state("r1", viewer_pid="bot"))
    assert '"ai_search"' in human
    assert '"ai_search"' not in bot
    assert '"agent_deck":' not in human
    assert '"bonus_deck":' not in human
    assert '"rng_state":' not in human
    assert '"seat_histories"' not in human


def test_ready_requires_current_worker_metadata_and_rejects_old_or_wrong_seat():
    room = _room()
    m.ROOMS["r1"] = room
    ws = _FakeWS()
    loop = asyncio.get_event_loop()
    loop.run_until_complete(m._handle_client_ai_ready(ws, "r1", "human", {}))
    assert not room["client_ai"]
    loop.run_until_complete(m._handle_client_ai_ready(ws, "r1", "human", {
        "wire": m.CLIENT_AI_WIRE,
        "model_version": m.CLIENT_AI_MODEL_VERSION,
        "schema": m.CLIENT_AI_SCHEMA,
        "encoder": m.CLIENT_AI_ENCODER,
        "rules": m.CLIENT_AI_RULES,
    }))
    assert room["client_ai"]
    room["client_ai"] = False
    loop.run_until_complete(m._handle_client_ai_ready(ws, "r1", "bot", {
        "wire": m.CLIENT_AI_WIRE,
        "model_version": m.CLIENT_AI_MODEL_VERSION,
        "schema": m.CLIENT_AI_SCHEMA,
        "encoder": m.CLIENT_AI_ENCODER,
        "rules": m.CLIENT_AI_RULES,
    }))
    assert not room["client_ai"]


def test_stale_and_illegal_replies_leave_the_request_armed():
    room = _room()
    m.ROOMS["r1"] = room
    game = room["game"]
    legal = engine.legal_moves(game, "bot")
    obs = observation(game, "bot")
    room["client_ai"] = True
    room["_ai_search"] = {
        "decision": 4,
        "position": serving.position_key(obs, legal),
        "sent_at": 100.0,
    }
    ws = _FakeWS()
    loop = asyncio.get_event_loop()
    base = {"protocol": m.CLIENT_AI_WIRE, "decision": 4,
            "position": room["_ai_search"]["position"]}
    loop.run_until_complete(m._handle_ai_move(ws, "r1", "human",
                                              {**base, "decision": 3,
                                               "move": legal[0]}))
    assert room["_ai_search"] is not None
    loop.run_until_complete(m._handle_ai_move(ws, "r1", "human",
                                              {**base, "move": {"bad": True}}))
    assert room["_ai_search"] is not None
    loop.run_until_complete(m._handle_ai_move(ws, "r1", "human",
                                              {**base, "move": legal[0]}))
    assert room["_ai_search"] is None
    assert room["_ai_pending_move"] == legal[0]
    assert room["_ai_pending_sent_at"] == 100.0


def test_reply_with_old_position_is_invalidated_after_a_simultaneous_move():
    room = _room()
    m.ROOMS["r1"] = room
    room["client_ai"] = True
    legal = engine.legal_moves(room["game"], "bot")
    obs = observation(room["game"], "bot")
    room["_ai_search"] = {
        "decision": 5,
        "position": serving.position_key(obs, legal),
        "sent_at": 100.0,
    }
    # Opening mulligan decisions are simultaneous; a human can change the
    # public `mulligan_done` state while the browser is thinking.
    human_move = engine.legal_moves(room["game"], "human")[0]
    assert m._apply_live_move(room, "human", human_move)[0]
    ws = _FakeWS()
    asyncio.get_event_loop().run_until_complete(m._handle_ai_move(
        ws, "r1", "human", {
            "protocol": m.CLIENT_AI_WIRE, "decision": 5,
            "position": room["_ai_search"]["position"], "move": legal[0],
        }))
    assert room["_ai_search"] is None
    assert room["_ai_pending_move"] is None


def test_socket_release_disarms_browser_ai_but_stale_handler_cannot():
    room = _room()
    m.ROOMS["r1"] = room
    live, stale = _FakeWS(), _FakeWS()
    room["sockets"]["human"] = live
    room["client_ai"] = True
    room["_ai_search"] = {"decision": 1}
    m._release_orbit_socket("r1", "human", stale)
    assert room["client_ai"]
    assert room["_ai_search"] == {"decision": 1}
    m._release_orbit_socket("r1", "human", live)
    assert not room["client_ai"]
    assert room["_ai_search"] is None


def test_persisted_budget_and_legacy_history_restore_safely(monkeypatch):
    room = _room()
    room["ai_budget_remaining_ms"] = 1234
    room["ai_decisions_this_turn"] = 2
    room["seat_histories"] = {"legacy": {"private": "hidden"}}
    state = {
        "players": room["players"], "host": room["host"], "status": room["status"],
        "game": room["game"], "meta": room["meta"], "vs_ai": True,
        "ai_player": "bot", "ai_difficulty": "hard",
        "seat_histories": {}, "ai_memory": {},
        "ai_turn_started_at": 100.0, "ai_budget_remaining_ms": 1234,
        "ai_decisions_this_turn": 2, "configuration": "sun",
    }
    monkeypatch.setattr(m, "load_game_state", lambda _rid: copy.deepcopy(state))
    assert m.load_game_to_memory("r1")
    restored = m.ROOMS["r1"]
    assert restored["ai_budget_remaining_ms"] == 1234
    assert restored["ai_decisions_this_turn"] == 2
    assert set(restored["seat_histories"]) == set(room["game"]["order"])
    assert "private" not in json.dumps(restored["seat_histories"])


def test_corrupt_history_with_a_hidden_field_is_discarded(monkeypatch):
    room = _room()
    histories = m._new_live_histories(room["game"])
    histories["human"]["events"].append({
        "actor": 0,
        "changes": {},
        "own_action": {"action": "mulligan", "secret_hand": [999]},
    })
    state = {
        "players": room["players"], "host": room["host"], "status": room["status"],
        "game": room["game"], "meta": room["meta"], "vs_ai": True,
        "ai_player": "bot", "ai_difficulty": "hard", "seat_histories": histories,
        "ai_memory": {}, "configuration": "sun",
    }
    monkeypatch.setattr(m, "load_game_state", lambda _rid: copy.deepcopy(state))
    assert m.load_game_to_memory("r2")
    restored = m.ROOMS["r2"]["seat_histories"]
    assert all("secret_hand" not in json.dumps(history) for history in restored.values())
    assert restored["human"]["events"] == []
