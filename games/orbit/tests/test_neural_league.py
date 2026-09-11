"""Cheap regression checks for the resumable neural league controls."""

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from games.orbit.tools.neural_league import (
    _accepted_head_to_head,
    _arena_command,
    _cheap_screens_justify_acceptance,
    _arena_summary,
    _checkpoint_candidates,
    _confirmation_ladder,
    _confirmation_stage_passed,
    _default_proxy_game_workers,
    _select_checkpoint,
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
        search_leaf="state-value",
        search_determinization_period=1,
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
    assert profile["id"] == "proxy-250-150-100-w2-g1-state-value-det1"
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


# --- 2026-09-11 audit: the selection statistics, not the plumbing -------------
# The tests above check that commands are BUILT correctly. These check that the
# selection RULES are correct, which is what the twelve-generation stall was
# about: an eight-pair argmax over per-epoch deal sets manufactures ~0.75
# winners from identical checkpoints.


def _scan_entry(epoch, score, *, lower=None, pairs=32):
    return {"epoch": str(epoch), "checkpoint": f"/models/epoch-{epoch}.pt",
            "timed": {"pair_score": score, "pair_ci95": [lower if lower is not None else score - 0.1,
                                                          score + 0.1],
                       "complete_pairs": pairs}}


def test_checkpoint_scan_declines_to_pick_when_it_cannot_separate(tmp_path):
    # Two epochs three points apart is noise at any affordable width. The scan
    # must fall back to the deterministic last epoch rather than bank the max.
    scan = [_scan_entry(5, 0.52), _scan_entry(6, 0.55)]
    last = tmp_path / "epoch-6.pt"
    chosen, selection = _select_checkpoint(scan, last, margin=0.08)
    assert chosen == last.resolve()
    assert selection["kind"] == "last-epoch"
    assert selection["resolvable"] is False
    assert selection["separation"] == pytest.approx(0.03)


def test_checkpoint_scan_picks_a_clearly_separated_epoch(tmp_path):
    scan = [_scan_entry(5, 0.42), _scan_entry(6, 0.71)]
    chosen, selection = _select_checkpoint(scan, tmp_path / "epoch-6.pt", margin=0.08)
    assert chosen == Path("/models/epoch-6.pt")
    assert selection["kind"] == "scan-argmax"
    assert selection["resolvable"] is True
    assert selection["runner_up_epoch"] == "5"


def test_checkpoint_scan_runs_every_epoch_on_one_crn_pool(tmp_path, monkeypatch):
    # The pre-audit pool name embedded the epoch, and `game_seed` hashes the
    # pool, so each epoch played different deals. Guard the shared pool
    # directly: this is the defect, and it is invisible in any score.
    args = _args(tmp_path)
    pools = set()
    for epoch in ("1", "2", "3"):
        command = _arena_command(args, tmp_path / f"epoch-{epoch}.pt",
                                 tmp_path / f"{epoch}.json", pairs=32,
                                 pool="development-neural-league-g001-checkpoint-scan",
                                 timed=True)
        pools.add(command[command.index("--pool") + 1])
    assert len(pools) == 1, "every epoch checkpoint must be scanned on the same deals"


def test_head_to_head_needs_a_resolvable_win_not_a_point_estimate():
    # 0.58 with an interval straddling 0.5 is the shape of every rejected
    # generation in the log; it must not move the incumbent.
    straddles = {"pair_score": 0.58, "pair_ci95": [0.47, 0.69], "censored": 0,
                 "pairs": 128, "complete_pairs": 128}
    assert not _accepted_head_to_head(straddles, lower=0.5)
    clears = {"pair_score": 0.58, "pair_ci95": [0.53, 0.63], "censored": 0,
              "pairs": 128, "complete_pairs": 128}
    assert _accepted_head_to_head(clears, lower=0.5)


def test_head_to_head_rejects_censored_or_short_pools():
    censored = {"pair_score": 0.7, "pair_ci95": [0.6, 0.8], "censored": 2,
                "pairs": 128, "complete_pairs": 126}
    assert not _accepted_head_to_head(censored, lower=0.5)
    short = {"pair_score": 0.7, "pair_ci95": [0.6, 0.8], "censored": 0,
             "pairs": 128, "complete_pairs": 120}
    assert not _accepted_head_to_head(short, lower=0.5)
    assert not _accepted_head_to_head(None, lower=0.5)


def test_cheap_screens_can_veto_but_never_accept(tmp_path):
    args = _args(tmp_path)
    args.timed_trigger = 0.62
    args.accept_screen_floor = 0.45
    args.always_accept_arena = False
    weak = {"pair_score": 0.30}
    strong = {"pair_score": 0.90}
    # A timed screen below the floor vetoes the expensive arena...
    assert not _cheap_screens_justify_acceptance(strong, weak, args)
    # ...and a strong screen only BUYS the arena; acceptance is decided by
    # `_accepted_head_to_head`, which the screens cannot reach.
    assert _cheap_screens_justify_acceptance(weak, strong, args)


def test_arena_reports_carry_the_variance_that_sizes_the_next_screen():
    from games.orbit.ai.selfplay import ArenaResult

    result = ArenaResult(candidate="c", opponent="o", games=64, pairs=32, wins=20,
                         losses=12, draws=0, censored=0, score_sum=20.0,
                         pair_scores=[1.0, 0.5, 0.0, 0.5] * 8, by_board={})
    payload = result.as_dict()
    assert payload["pair_sd"] > 0
    assert payload["pair_se"] == pytest.approx(payload["pair_sd"] / 32 ** 0.5)
    # The audit's headline: a few hundred pairs for a few points, so an
    # eight-pair screen is a coin flip and the report should say so.
    assert payload["pairs_needed_for_0.03"] > payload["pairs_needed_for_0.05"] > 8


def test_single_pair_reports_do_not_divide_by_zero():
    from games.orbit.ai.selfplay import ArenaResult

    payload = ArenaResult(candidate="c", opponent="o", games=2, pairs=1, wins=1,
                          losses=1, draws=0, censored=0, score_sum=1.0,
                          pair_scores=[0.5], by_board={}).as_dict()
    assert payload["pair_sd"] == 0.0
    assert payload["pair_se"] == 0.0
    assert payload["pairs_needed_for_0.03"] == 0


def test_agreement_ceiling_skips_the_arena_for_a_no_op_candidate():
    from games.orbit.tools.policy_diff import worth_an_arena

    twin = {"complete": True, "agree_pct_where_more_than_one_legal_move": 100.0}
    assert not worth_an_arena(twin, ceiling=97.0)
    # The measured incumbent-vs-candidate figure on a self-play trajectory.
    real = {"complete": True, "agree_pct_where_more_than_one_legal_move": 60.7}
    assert worth_an_arena(real, ceiling=97.0)


def test_a_broken_agreement_probe_never_silently_skips_the_arena():
    from games.orbit.tools.policy_diff import worth_an_arena

    # A skip is a decision not to measure. It must require evidence, so an
    # incomplete probe falls through to running the arena.
    assert worth_an_arena({"complete": False, "errors": ["boom"],
                           "agree_pct_where_more_than_one_legal_move": 100.0},
                          ceiling=97.0)


def test_the_search_regime_is_part_of_the_evaluation_identity(tmp_path):
    # Changing the leaf or the determinization changes what every score was
    # measured AGAINST, because the incumbent and the frozen Expert are both
    # searches. Two regimes must not share a profile id, or a resumed campaign
    # compares a candidate beaten by the new Expert with one beaten by the old.
    baseline = _evaluation_profile(_args(tmp_path))
    coherent = _args(tmp_path)
    coherent.search_determinization_period = 0
    other_leaf = _args(tmp_path)
    other_leaf.search_leaf = "capture-progress-only"
    ids = {baseline["id"], _evaluation_profile(coherent)["id"],
           _evaluation_profile(other_leaf)["id"]}
    assert len(ids) == 3, f"regimes collapsed to the same identity: {ids}"
    assert _evaluation_profile(coherent)["id"].endswith("-coherent")


def test_arena_commands_declare_the_regime_rather_than_inheriting_it(tmp_path):
    # A binary default is not a record. Every arena must say which search it ran,
    # on BOTH seats, so an artifact is interpretable without knowing which commit
    # built the binary.
    args = _args(tmp_path)
    args.search_determinization_period = 0
    command = _arena_command(args, tmp_path / "c.pt", tmp_path / "r.json",
                             pairs=8, pool="development-x", timed=True)
    for flag in ("--leaf", "--opponent-leaf",
                 "--determinization-period", "--opponent-determinization-period"):
        assert flag in command, f"{flag} missing from the arena command"
    assert command[command.index("--determinization-period") + 1] == "0"
    assert command[command.index("--opponent-determinization-period") + 1] == "0"
