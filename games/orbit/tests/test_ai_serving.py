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


def test_shipped_model_and_wasm_assets_match_the_python_manifest():
    root = Path(__file__).resolve().parents[3]
    asset = json.loads((root / "webapp/public/wasm/orbit-model.json").read_text(encoding="utf-8"))
    expected = serving.serving_manifest()
    for key in ("abi_version", "model_version", "encoder", "schema", "rules"):
        assert asset[key] == expected[key]
    assert len(asset["cards"]) == len(CARDS) == 90
    for card_id, card in CARDS.items():
        assert asset["cards"][str(card_id)] == {
            "cost": card["cost"], "planet": card["planet"], "faction": card["faction"]}
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
