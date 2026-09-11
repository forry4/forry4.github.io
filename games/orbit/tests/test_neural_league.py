"""Cheap regression checks for the resumable neural league controls."""

import json
from pathlib import Path
from types import SimpleNamespace

from games.orbit.tools.neural_league import (
    _arena_command,
    _arena_summary,
    _checkpoint_candidates,
    _confirmation_ladder,
    _confirmation_stage_passed,
    _default_proxy_game_workers,
    _evaluation_profile,
    _new_state,
    _training_sources,
)


def _args(tmp_path: Path):
    return SimpleNamespace(
        parent=tmp_path / "parent.pt",
        anchor_data=tmp_path / "foundation",
        seed=17,
        arena_binary=tmp_path / "arena.exe",
        workers=2,
        model_stride=1,
        model_weight=1.0,
        model_temperature=2.0,
        screen_simulations=24,
    )


def test_league_sources_keep_foundation_and_recent_parent_anchors(tmp_path):
    state = {
        "anchor_data": str(tmp_path / "foundation"),
        "champion_anchors": [str(tmp_path / f"anchor-{i}") for i in range(5)],
        "training_sources": [str(tmp_path / f"train-{i}") for i in range(5)],
    }
    sources = _training_sources(state, window=2)
    assert sources[0] == (tmp_path / "foundation").resolve()
    assert sources[1:] == [
        (tmp_path / "anchor-3").resolve(),
        (tmp_path / "anchor-4").resolve(),
        (tmp_path / "train-3").resolve(),
        (tmp_path / "train-4").resolve(),
    ]


def test_checkpoint_candidates_use_numeric_epoch_order(tmp_path):
    for name in ("epoch-10.pt", "epoch-2.pt", "epoch-1.pt"):
        (tmp_path / name).write_bytes(b"checkpoint")
    assert [path.name for path in _checkpoint_candidates(tmp_path)] == [
        "epoch-1.pt", "epoch-2.pt", "epoch-10.pt"
    ]


def test_arena_command_selects_expert_or_near_peer(tmp_path):
    args = _args(tmp_path)
    expert = _arena_command(args, tmp_path / "candidate.pt", tmp_path / "expert.json",
                            pairs=8, pool="development-expert", timed=False)
    peer = _arena_command(args, tmp_path / "candidate.pt", tmp_path / "peer.json",
                          pairs=8, pool="development-peer", timed=False,
                          opponent=tmp_path / "parent.pt")
    assert "--opponent-expert" in expert
    assert "--opponent-expert" not in peer
    assert peer[peer.index("--opponent") + 1] == str(tmp_path / "parent.pt")


def test_arena_command_separates_fast_proxy_and_serving_shape(tmp_path):
    args = _args(tmp_path)
    fast = _arena_command(args, tmp_path / "candidate.pt", tmp_path / "fast.json",
                           pairs=8, pool="development-fast", timed=True)
    serving = _arena_command(args, tmp_path / "candidate.pt", tmp_path / "serving.json",
                             pairs=8, pool="development-serving", timed=True, serving=True)
    assert fast[fast.index("--budget-ms") + 1] == "250"
    assert fast[fast.index("--workers") + 1] == "2"
    assert serving[serving.index("--budget-ms") + 1] == "5000"
    assert serving[serving.index("--workers") + 1] == "4"


def test_proxy_command_can_fill_host_with_independent_games(tmp_path):
    args = _args(tmp_path)
    args.proxy_workers = 4
    args.proxy_game_workers = 3
    command = _arena_command(args, tmp_path / "candidate.pt", tmp_path / "fast.json",
                             pairs=8, pool="development-fast-batch", timed=True)
    assert command[command.index("--workers") + 1] == "4"
    assert command[command.index("--game-workers") + 1] == "3"


def test_proxy_game_worker_default_respects_root_width():
    assert _default_proxy_game_workers(1) >= _default_proxy_game_workers(4)
    assert _default_proxy_game_workers(4) >= 1


def test_evaluation_profile_identifies_budget_and_worker_regime(tmp_path):
    profile = _evaluation_profile(_args(tmp_path))
    assert profile["id"] == "proxy-250-150-100-w2-g1"
    assert profile["serving_check"] == {
        "budget_ms": 5000,
        "main_action_ms": 3000,
        "followup_ms": 2000,
        "workers": 4,
        "game_workers": 1,
    }


def test_arena_summary_retains_mirror_result(tmp_path):
    report = tmp_path / "mirror.json"
    report.write_text(json.dumps({
        "complete": True,
        "mirror_passed": True,
        "arena": {"score": 0.5, "pair_score": 0.5, "pair_ci95": [0.5, 0.5],
                   "pairs": 8, "complete_pairs": 8, "wins": 8, "losses": 8,
                   "draws": 0, "censored": 0, "by_board": {}},
    }), encoding="utf-8")
    assert _arena_summary(report)["mirror_passed"] is True


def test_new_state_records_the_requested_roster_transition(tmp_path):
    args = _args(tmp_path)
    args.parent.write_bytes(b"checkpoint")
    args.anchor_data.mkdir()
    (args.anchor_data / "manifest.json").write_text("{}", encoding="utf-8")
    state = _new_state(args, tmp_path / "campaign")
    assert state["target"] == {"score": 0.75, "paired_lower_ci95": 0.75,
                                "description": "fast calibrated equal-time proxy plus a rare serving-shaped check versus frozen current Expert"}
    assert state["incumbent"]["roster_after"] == ["normal", "hard", "expert", "champion"]
    assert state["champion_anchors"] == []


def test_confirmation_ladder_is_ordered_and_ends_at_final_pairs():
    args = SimpleNamespace(confirm_pairs=512, confirm_ladder="32,128,512")
    assert _confirmation_ladder(args) == (32, 128, 512)


def test_intermediate_confirmation_is_directional_only():
    summary = {
        "censored": 0,
        "complete_pairs": 32,
        "pair_score": 0.625,
        "pair_ci95": [0.5, 0.75],
    }
    assert _confirmation_stage_passed(summary, pairs=32, final_pairs=512,
                                      stage_trigger=0.60)
    summary["pair_ci95"] = [0.4375, 0.6875]
    assert not _confirmation_stage_passed(summary, pairs=32, final_pairs=512,
                                          stage_trigger=0.60)
