"""Run a resumable observation-only Orbit value-network league.

Each generation harvests fresh fixed-simulation games against the frozen
current Expert, Hard v2, exploratory and targeted specialist policies, then
fine-tunes the best neural parent while retaining foundation and current-parent
anchors. Candidates are screened through the same rebuilt-observation/root-worker
arena used by the browser, but the development profile is a calibrated fast
proxy rather than the full browser turn budget.
The tool records every command, manifest, checkpoint and paired confidence
interval; it never changes the serving roster automatically.

The long-run strength claim is deliberately narrow: a candidate is promotion
ready only after a fresh 512-pair proxy gate has a score and paired bootstrap
lower bound of at least 0.75, with no censoring, followed by a complete
serving-shaped compatibility check. A separate release step can then wire the
checkpoint and shift the four displayed difficulty labels.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time
from typing import Any

from ..ai.state import SCHEMA_VERSION, rules_fingerprint


REPO_ROOT = Path(__file__).resolve().parents[3]
# Campaign artifacts live under the game, like every other game's AI data
# (`games/spender/ai/offline/...`). They used to be ~40 `.orbit-*` directories in
# the REPO ROOT holding 5.8 GB, most of it dead cargo build output.
ORBIT_RUNS = REPO_ROOT / "games" / "orbit" / "ai" / "runs"
DEFAULT_PARENT = ORBIT_RUNS / "value-fit-indexed-v3" / "epoch-004.pt"
DEFAULT_ANCHOR = ORBIT_RUNS / "value-train-native-v2"
_PORTABLE_BINARY_ROOT = REPO_ROOT / "rust-cores" / "orbit-core" / "target" / "release"
_NATIVE_BINARY_ROOT = ORBIT_RUNS / "target-native" / "release"
# Prefer the isolated CPU-native build for an offline local campaign when it
# exists, while keeping a fresh checkout's portable release path as the
# fallback.  The WASM/browser build never uses these defaults.
DEFAULT_VALUE_BINARY = (_NATIVE_BINARY_ROOT / "value_generate.exe"
                        if (_NATIVE_BINARY_ROOT / "value_generate.exe").is_file()
                        else _PORTABLE_BINARY_ROOT / "value_generate.exe")
DEFAULT_ARENA_BINARY = (_NATIVE_BINARY_ROOT / "neural_arena.exe"
                        if (_NATIVE_BINARY_ROOT / "neural_arena.exe").is_file()
                        else _PORTABLE_BINARY_ROOT / "neural_arena.exe")
DEFAULT_POLICY_DIFF_BINARY = (_NATIVE_BINARY_ROOT / "policy_diff.exe"
                              if (_NATIVE_BINARY_ROOT / "policy_diff.exe").is_file()
                              else _PORTABLE_BINARY_ROOT / "policy_diff.exe")
STATE_VERSION = 1
TARGET_SCORE = 0.75
TARGET_LOWER = 0.75
# The browser contract is intentionally expensive (5 s/turn), but using that
# profile for every development candidate makes a league effectively
# intractable.  The proxy profile is a measured, equal-time search regime used
# for ranking and high-N statistics; a small serving-shaped check is reserved
# for a candidate that clears the proxy gate.
DEFAULT_PROXY_BUDGET_MS = 250
DEFAULT_PROXY_MAIN_ACTION_MS = 150
DEFAULT_PROXY_FOLLOWUP_MS = 100
DEFAULT_SERVING_BUDGET_MS = 5000
DEFAULT_SERVING_MAIN_ACTION_MS = 3000
DEFAULT_SERVING_FOLLOWUP_MS = 2000
DEFAULT_SERVING_WORKERS = 4


def _default_proxy_game_workers(proxy_workers: int = DEFAULT_SERVING_WORKERS) -> int:
    """Fill the offline host with independent arenas at the proxy root width.

    ``proxy_workers`` is the number of independent root trees *inside one
    game*.  A second level of parallelism runs unrelated paired games at the
    same time.  Keeping the product bounded makes this an explicit native
    thread budget rather than the old accidental one-game-at-a-time design.
    """

    host = max(1, os.cpu_count() or 1)
    return max(1, min(16, host // max(1, int(proxy_workers))))
# Keep the family counts fixed so every generated block has identical
# board/seat coverage.  A soft racer is the curriculum rung: the research log
# found that a full-speed racer can put a learner on the wrong side of a
# fitness valley, while a small random mixture gives it a smooth tempo ramp.
TRAIN_FAMILY_LIST = ("expert", "hard-v2", "exploratory-v2", "random", "racer-soft", "developer", "denier")
DEV_FAMILY_LIST = ("hard-v2", "exploratory-v2", "random", "racer", "developer", "denier")
TRAIN_FAMILIES = ",".join(TRAIN_FAMILY_LIST)
DEV_FAMILIES = ",".join(DEV_FAMILY_LIST)


def _absolute(path: Path) -> Path:
    return path if path.is_absolute() else (REPO_ROOT / path).resolve()


def _write_json(path: Path, value: dict[str, Any]) -> None:
    """Write a small campaign record without exposing half a state file."""

    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object in {path}")
    return value


def _run(command: list[str], *, log_path: Path, label: str) -> None:
    """Run one campaign command while teeing bounded human-readable output."""

    log_path.parent.mkdir(parents=True, exist_ok=True)
    print(json.dumps({"start": label, "command": command}), flush=True)
    started = time.perf_counter()
    with log_path.open("a", encoding="utf-8", newline="\n") as log:
        log.write(json.dumps({"start": label, "command": command}) + "\n")
        process = subprocess.Popen(
            command,
            cwd=str(REPO_ROOT),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert process.stdout is not None
        for line in process.stdout:
            log.write(line)
            log.flush()
            print(f"[{label}] {line.rstrip()}", flush=True)
        return_code = process.wait()
    elapsed = time.perf_counter() - started
    if return_code:
        raise RuntimeError(f"{label} failed with exit code {return_code}; see {log_path}")
    print(json.dumps({"complete": label, "seconds": round(elapsed, 2)}), flush=True)


def _latest_checkpoint(directory: Path) -> Path:
    checkpoints = _checkpoint_candidates(directory)
    if not checkpoints:
        raise FileNotFoundError(f"No epoch checkpoint in {directory}")
    return checkpoints[-1].resolve()


def _checkpoint_candidates(directory: Path) -> list[Path]:
    """Return epoch checkpoints in numeric training order.

    Lexicographic ordering makes ``epoch-10.pt`` precede ``epoch-2.pt`` and,
    more importantly, hides the fact that an earlier checkpoint can be a
    stronger policy than the final one.  Keep this ordering in one helper so
    training, checkpoint scans and tests agree about which epochs exist.
    """

    def key(path: Path) -> tuple[int, int | str]:
        try:
            return (0, int(path.stem.split("-", 1)[1]))
        except (IndexError, ValueError):
            return (1, path.name)

    return sorted(directory.glob("epoch-*.pt"), key=key)


def _arena_summary(path: Path) -> dict[str, Any]:
    report = _read_json(path)
    arena = report.get("arena")
    if not isinstance(arena, dict):
        raise ValueError(f"Arena report has no folded result: {path}")
    if not report.get("complete"):
        raise ValueError(f"Arena report is incomplete: {path}")
    return {
        "score": float(arena.get("score", 0.5)),
        "pair_score": float(arena.get("pair_score", 0.5)),
        "pair_ci95": list(arena.get("pair_ci95", [0.5, 0.5])),
        # Carried so a reader can tell a resolvable result from a coin flip
        # without re-deriving the variance.  Older reports predate these keys.
        "pair_sd": float(arena.get("pair_sd", 0.0)),
        "pair_se": float(arena.get("pair_se", 0.0)),
        "pairs_needed_for_0.03": int(arena.get("pairs_needed_for_0.03", 0)),
        "pairs": int(arena.get("pairs", 0)),
        "complete_pairs": int(arena.get("complete_pairs", 0)),
        "wins": int(arena.get("wins", 0)),
        "losses": int(arena.get("losses", 0)),
        "draws": int(arena.get("draws", 0)),
        "censored": int(arena.get("censored", 0)),
        "mirror_passed": bool(report.get("mirror_passed", False)),
        "by_board": arena.get("by_board", {}),
        "report": str(path.resolve()),
    }


def _new_state(args: argparse.Namespace, root: Path) -> dict[str, Any]:
    parent = _absolute(args.parent)
    anchor = _absolute(args.anchor_data)
    if not parent.is_file():
        raise FileNotFoundError(f"Initial parent checkpoint not found: {parent}")
    if not (anchor / "manifest.json").is_file():
        raise FileNotFoundError(f"Anchor dataset manifest not found: {anchor}")
    return {
        "version": STATE_VERSION,
        "rules": rules_fingerprint(),
        "schema": SCHEMA_VERSION,
        "campaign_seed": int(args.seed),
        "target": {
            "score": TARGET_SCORE,
            "paired_lower_ci95": TARGET_LOWER,
            "description": "fast calibrated equal-time proxy plus a rare serving-shaped check versus frozen current Expert",
        },
        "incumbent": {
            "id": "current-expert-frozen",
            "kind": "heuristic-information-set-puct",
            "checkpoint": None,
            "roster_before": ["easy", "normal", "hard", "expert"],
            "roster_after": ["normal", "hard", "expert", "champion"],
            "transition": "delete easy; shift normal->easy, hard->normal, expert->hard, champion->expert",
        },
        "best": {
            "checkpoint": str(parent),
            "fixed_score": None,
            "timed_score": None,
            "evaluation_id": None,
            "generation": 0,
        },
        "anchor_data": str(anchor),
        "champion_anchors": [],
        "training_sources": [],
        "generations": [],
        "promotion": {"status": "not-tested", "checkpoint": None, "report": None},
        "baseline_profiles": {},
        "artifacts_root": str(root.resolve()),
    }


def _load_or_create(args: argparse.Namespace, root: Path) -> tuple[Path, dict[str, Any]]:
    state_path = root / "state.json"
    if state_path.exists():
        state = _read_json(state_path)
        if state.get("version") != STATE_VERSION or state.get("rules") != rules_fingerprint() or int(state.get("schema", -1)) != SCHEMA_VERSION:
            raise ValueError("League state version/rules/schema mismatch")
        # These fields were added after the first resumable runner.  Keep old
        # state files resumable while making the stronger controls mandatory
        # for every new generation.
        state.setdefault("champion_anchors", [])
        state.setdefault("training_sources", [])
        state.setdefault("baseline_profiles", {})
        state.setdefault("best", {}).setdefault("evaluation_id", None)
        return state_path, state
    state = _new_state(args, root)
    _write_json(state_path, state)
    return state_path, state


def _arena_command(
    args: argparse.Namespace,
    checkpoint: Path,
    report: Path,
    *,
    pairs: int,
    pool: str,
    timed: bool,
    serving: bool = False,
    opponent: Path | str | None = None,
    simulations: int | None = None,
    workers_override: int | None = None,
    game_workers_override: int | None = None,
) -> list[str]:
    if serving:
        arena_workers = int(getattr(args, "serving_workers", DEFAULT_SERVING_WORKERS))
        arena_game_workers = 1
    elif timed:
        # The proxy keeps the serving root ensemble (normally four trees) but
        # fills the native host with unrelated games.  This is the key
        # throughput distinction from the browser: game-level parallelism is
        # free for a paired offline arena and does not change a game's search.
        arena_workers = int(getattr(args, "proxy_workers",
                                    getattr(args, "workers", 1)))
        arena_game_workers = int(getattr(args, "proxy_game_workers",
                                         getattr(args, "game_workers", 1)))
    else:
        arena_workers = int(getattr(args, "workers", 1))
        arena_game_workers = int(getattr(args, "fixed_game_workers", 1))
    if workers_override is not None:
        arena_workers = int(workers_override)
    if game_workers_override is not None:
        arena_game_workers = int(game_workers_override)
    command = [
        sys.executable,
        "-m",
        "games.orbit.tools.native_search_arena",
        str(checkpoint),
        str(report),
        "--pairs",
        str(pairs),
        "--workers",
        str(arena_workers),
        "--via-observation",
        "--pool",
        pool,
        "--binary",
        str(_absolute(args.arena_binary)),
        "--model-stride",
        str(args.model_stride),
        "--model-weight",
        str(args.model_weight),
        "--model-temperature",
        str(args.model_temperature),
        "--leaf",
        str(getattr(args, "search_leaf", "state-value")),
        "--opponent-leaf",
        str(getattr(args, "search_leaf", "state-value")),
        "--determinization-period",
        str(getattr(args, "search_determinization_period", 1)),
        "--opponent-determinization-period",
        str(getattr(args, "search_determinization_period", 1)),
    ]
    if arena_game_workers > 1:
        command.extend(["--game-workers", str(arena_game_workers)])
    if opponent is None or opponent == "expert":
        command.append("--opponent-expert")
    else:
        command.extend(["--opponent", str(opponent)])
    if timed:
        if serving:
            budget = int(getattr(args, "serving_budget_ms", DEFAULT_SERVING_BUDGET_MS))
            main = int(getattr(args, "serving_main_action_ms", DEFAULT_SERVING_MAIN_ACTION_MS))
            followup = int(getattr(args, "serving_followup_ms", DEFAULT_SERVING_FOLLOWUP_MS))
        else:
            budget = int(getattr(args, "timed_budget_ms", DEFAULT_PROXY_BUDGET_MS))
            main = int(getattr(args, "timed_main_action_ms", DEFAULT_PROXY_MAIN_ACTION_MS))
            followup = int(getattr(args, "timed_followup_ms", DEFAULT_PROXY_FOLLOWUP_MS))
        command.extend(["--budget-ms", str(budget), "--main-action-ms", str(main),
                        "--followup-ms", str(followup)])
    else:
        command.extend(["--budget-ms", "250", "--simulations",
                        str(args.screen_simulations if simulations is None else simulations)])
    return command


def _evaluation_profile(args: argparse.Namespace) -> dict[str, Any]:
    """Describe the search regime used for this campaign's proxy gates.

    Reports from different budgets or worker counts are not interchangeable.
    Keeping the profile in state makes a resumed campaign refuse to compare a
    new fast proxy with the old 3.5-second probe by accident.
    """

    budget = int(getattr(args, "timed_budget_ms", DEFAULT_PROXY_BUDGET_MS))
    main = int(getattr(args, "timed_main_action_ms", DEFAULT_PROXY_MAIN_ACTION_MS))
    followup = int(getattr(args, "timed_followup_ms", DEFAULT_PROXY_FOLLOWUP_MS))
    workers = int(getattr(args, "proxy_workers",
                          getattr(args, "workers", 1)))
    game_workers = int(getattr(args, "proxy_game_workers",
                               getattr(args, "game_workers", 1)))
    # The SEARCH regime belongs in the identity too, not just the budget. The
    # incumbent and the frozen Expert are both searches, so changing the leaf or
    # the determinization changes what every recorded score was measured
    # AGAINST. This bit was missing on 2026-09-11 when the leaf was corrected
    # from capture-progress-only to the full state-value port: a wash in
    # strength, but not the same opponent, and nothing in the profile said so.
    leaf = str(getattr(args, "search_leaf", "state-value"))
    period = int(getattr(args, "search_determinization_period", 1))
    regime = "coherent" if period == 0 else f"det{period}"
    return {
        "id": f"proxy-{budget}-{main}-{followup}-w{workers}-g{game_workers}-{leaf}-{regime}",
        "kind": "fast-equal-time-proxy",
        "budget_ms": budget,
        "main_action_ms": main,
        "followup_ms": followup,
        "workers": workers,
        "game_workers": game_workers,
        "leaf": leaf,
        "determinization_period": period,
        "serving_check": {
            "budget_ms": int(getattr(args, "serving_budget_ms", DEFAULT_SERVING_BUDGET_MS)),
            "main_action_ms": int(getattr(args, "serving_main_action_ms", DEFAULT_SERVING_MAIN_ACTION_MS)),
            "followup_ms": int(getattr(args, "serving_followup_ms", DEFAULT_SERVING_FOLLOWUP_MS)),
            "workers": int(getattr(args, "serving_workers", DEFAULT_SERVING_WORKERS)),
            "game_workers": 1,
        },
    }


def _profile_id(args: argparse.Namespace) -> str:
    return str(_evaluation_profile(args)["id"])


def _baseline_profile(state: dict[str, Any], args: argparse.Namespace) -> dict[str, Any]:
    profiles = state.setdefault("baseline_profiles", {})
    profile = _evaluation_profile(args)
    return profiles.setdefault(profile["id"], {"profile": profile})


def _checkpoint_tag(checkpoint: Path) -> str:
    """Stable short tag for baseline artifacts tied to one checkpoint file."""

    stat = checkpoint.stat()
    payload = f"{checkpoint.resolve()}:{stat.st_size}:{stat.st_mtime_ns}".encode()
    return hashlib.sha256(payload).hexdigest()[:12]


def _ensure_baseline(args: argparse.Namespace, state_path: Path, state: dict[str, Any], root: Path) -> None:
    existing = _baseline_profile(state, args)
    profile_id = _profile_id(args)
    state["evaluation"] = _evaluation_profile(args)
    parent = Path(state["best"]["checkpoint"]).resolve()
    parent_key = str(parent)
    # A resumable campaign can change its incumbent after the first baseline
    # was measured.  Never reuse scores or reports tied to the old checkpoint;
    # that makes later selection compare a candidate with the wrong parent.
    if existing.get("checkpoint") != parent_key:
        existing.clear()
        existing.update({"profile": _evaluation_profile(args), "checkpoint": parent_key})
    if existing.get("mirror"):
        return
    baseline_dir = root / "baseline" / profile_id
    baseline_dir.mkdir(parents=True, exist_ok=True)
    checkpoint_tag = _checkpoint_tag(parent)
    mirror_report = baseline_dir / f"parent-self-fixed-{checkpoint_tag}.json"
    if not mirror_report.exists():
        _run(
            _arena_command(args, parent, mirror_report, pairs=args.mirror_pairs,
                           pool="development-neural-league-baseline-mirror", timed=False,
                           opponent=parent, simulations=args.mirror_simulations,
                           workers_override=args.screen_workers,
                           game_workers_override=args.screen_game_workers),
            log_path=baseline_dir / "arena.log",
            label="baseline-mirror",
        )
    mirror = _arena_summary(mirror_report)
    if not mirror.get("mirror_passed", False):
        raise RuntimeError("Baseline neural self-gate failed; inspect the mirror report")
    baseline_report = baseline_dir / f"parent-vs-current-expert-fixed-{checkpoint_tag}.json"
    if not existing.get("fixed") and not baseline_report.exists():
        _run(
            _arena_command(args, parent, baseline_report, pairs=args.screen_pairs,
                           pool="development-neural-league-baseline-fixed", timed=False,
                           workers_override=args.screen_workers,
                           game_workers_override=args.screen_game_workers),
            log_path=baseline_dir / "arena.log",
            label="baseline-fixed",
        )
    fixed = existing.get("fixed") or _arena_summary(baseline_report)
    existing.update({"profile": _evaluation_profile(args), "mirror": mirror, "fixed": fixed,
                     "checkpoint": str(parent)})
    # A legacy state may contain scores from a different worker/budget profile.
    # Do not let those scores become the incumbent comparison for this run.
    if state["best"].get("checkpoint") == parent_key:
        state["best"]["fixed_score"] = fixed["pair_score"]
        state["best"]["timed_score"] = None
        state["best"]["evaluation_id"] = profile_id
    _write_json(state_path, state)
    if args.baseline_timed:
        _ensure_timed_baseline(args, state_path, state, root)


def _ensure_timed_baseline(args: argparse.Namespace, state_path: Path, state: dict[str, Any], root: Path) -> dict[str, Any]:
    """Lazily measure the fast proxy baseline when a candidate earns it."""

    baseline = _baseline_profile(state, args)
    if baseline.get("timed"):
        return baseline["timed"]
    profile_id = _profile_id(args)
    baseline_dir = root / "baseline" / profile_id
    baseline_dir.mkdir(parents=True, exist_ok=True)
    parent = Path(state["best"]["checkpoint"])
    timed_report = baseline_dir / f"parent-vs-current-expert-timed-{_checkpoint_tag(parent)}.json"
    if not timed_report.exists():
        _run(
            _arena_command(args, parent, timed_report, pairs=args.timed_pairs,
                           pool=f"development-neural-league-{profile_id}-baseline-timed", timed=True),
            log_path=baseline_dir / "arena.log",
            label="baseline-timed",
        )
    timed = _arena_summary(timed_report)
    baseline["timed"] = timed
    baseline["profile"] = _evaluation_profile(args)
    if (state["best"].get("evaluation_id") == profile_id
            and state["best"].get("checkpoint") == str(parent.resolve())):
        state["best"]["timed_score"] = timed["pair_score"]
    _write_json(state_path, state)
    return timed


def _training_sources(state: dict[str, Any], *, window: int) -> list[Path]:
    anchor = Path(state["anchor_data"]).resolve()
    history = [Path(value).resolve() for value in state.get("training_sources", [])]
    champion = [Path(value).resolve() for value in state.get("champion_anchors", [])]
    recent = champion[-max(0, window):] + history[-max(0, window):]
    result = [anchor]
    for source in recent:
        if source != anchor and source not in result:
            result.append(source)
    return result


def _confirmation_ladder(args: argparse.Namespace) -> tuple[int, ...]:
    """Return the pre-registered fresh timed confirmation rungs.

    The first rungs are directional filters only.  They must never be used as
    a promotion claim; the final rung is the configured high-N gate.  Keeping
    this helper tolerant of older ``Namespace`` objects makes saved campaign
    runners and focused tests continue to work while the CLI gains the ladder.
    """

    final = int(getattr(args, "confirm_pairs", 512))
    raw = getattr(args, "confirm_ladder", None)
    if raw is None:
        values = [final]
    elif isinstance(raw, str):
        values = [int(part.strip()) for part in raw.split(",") if part.strip()]
    else:
        values = [int(value) for value in raw]
    values = sorted(set(values))
    if final not in values:
        values.append(final)
        values.sort()
    if not values or values[-1] != final:
        raise ValueError("confirmation ladder must end at --confirm-pairs")
    if any(value < 8 or value % 8 for value in values):
        raise ValueError("confirmation ladder values must be positive multiples of eight")
    return tuple(values)


def _select_checkpoint(scan: list[dict[str, Any]], last: Path, *,
                       margin: float) -> tuple[Path, dict[str, Any]]:
    """Pick an epoch from a CRN-paired scan, or decline to pick.

    Taking the argmax of a noisy scan is a winner's curse: the selected epoch's
    score is biased upward by roughly ``E[max of k draws]``, which at an
    eight-pair standard error is most of the way from 0.5 to the campaign's own
    0.75 target.  The fix is not only more pairs (though the scan is now paired
    on one deal set, which is what makes the comparison sensitive at all) but
    admitting when the scan cannot separate its top two.  When the best epoch
    does not beat the runner-up by ``margin``, the LAST epoch is used: it is the
    deterministic no-information default and carries no selection bias.
    """

    if not scan:
        return last.resolve(), {"kind": "last-epoch", "reason": "empty scan"}

    def rank(item: dict[str, Any]) -> tuple[float, float, int]:
        timed = item["timed"]
        return (float(timed["pair_score"]),
                float(timed.get("pair_ci95", [0.0])[0]),
                int(item["epoch"]) if str(item["epoch"]).isdigit() else -1)

    ordered = sorted(scan, key=rank, reverse=True)
    best = ordered[0]
    separation = float(best["timed"]["pair_score"]) - (
        float(ordered[1]["timed"]["pair_score"]) if len(ordered) > 1 else 0.0)
    resolvable = len(ordered) < 2 or separation >= margin
    selection = {
        "kind": "scan-argmax" if resolvable else "last-epoch",
        "best_epoch": best["epoch"],
        "best_score": float(best["timed"]["pair_score"]),
        "runner_up_epoch": ordered[1]["epoch"] if len(ordered) > 1 else None,
        "separation": separation,
        "required_margin": margin,
        "resolvable": resolvable,
        "scan_pairs": int(best["timed"].get("complete_pairs", 0)),
        "crn_paired": True,
    }
    if resolvable:
        return Path(best["checkpoint"]), selection
    selection["fell_back_to"] = str(last.resolve())
    return last.resolve(), selection


def _cheap_screens_justify_acceptance(fixed: dict[str, Any], timed: dict[str, Any] | None,
                                      args: argparse.Namespace) -> bool:
    """Gate the expensive head-to-head arena on the cheap screens.

    The accept arena is the campaign's most expensive routine measurement, so a
    learner that is visibly worse should not buy one.  The screens are only
    allowed to VETO here; they never accept anything on their own, which is the
    asymmetry the audit asked for.
    """

    if getattr(args, "always_accept_arena", False):
        return True
    if timed is not None:
        return timed["pair_score"] >= args.accept_screen_floor
    return fixed["pair_score"] >= args.timed_trigger


def _accepted_head_to_head(summary: dict[str, Any] | None, *, lower: float) -> bool:
    """Accept a candidate only on a resolvable head-to-head win.

    The pre-2026-09-11 rule compared the candidate's score against the Expert
    with the incumbent's score against the Expert, each measured on its own
    eight-pair pool.  The difference of two such numbers has roughly sqrt(2)
    times an already-useless standard error, so the ``best`` pointer performed a
    random walk and in practice never moved.  Playing the two directly on shared
    CRN deals removes the third party and most of the variance; requiring the
    paired lower bound to clear ``lower`` removes the coin flip.
    """

    if summary is None:
        return False
    if summary["censored"] or summary["complete_pairs"] < summary["pairs"]:
        return False
    return float(summary["pair_ci95"][0]) > lower


def _confirmation_stage_passed(summary: dict[str, Any], *, pairs: int,
                               final_pairs: int, stage_trigger: float) -> bool:
    """Decide whether a non-final confirmation rung is worth extending.

    This is deliberately conservative and directional: an intermediate rung
    may stop an obviously weak candidate, but it can never mark promotion.
    Requiring the bootstrap interval to reach the target keeps a noisy point
    estimate from buying a full 512-pair run when the candidate is already
    implausible.  The final rung is checked separately against the registered
    75% score/lower-bound target.
    """

    if summary["censored"] or summary["complete_pairs"] != pairs:
        return False
    if pairs >= final_pairs:
        return True
    interval = summary.get("pair_ci95", [0.0, 0.0])
    return summary["pair_score"] >= stage_trigger and float(interval[1]) >= TARGET_SCORE


def _run_generation(args: argparse.Namespace, state_path: Path, state: dict[str, Any], generation: int, root: Path) -> bool:
    tag = f"g{generation:03d}"
    profile_id = _profile_id(args)
    generation_root = root / tag
    train_dir = generation_root / f"train-search-league-{tag}-v1"
    champion_anchor_dir = generation_root / f"train-search-champion-anchor-{tag}-v1"
    dev_dir = generation_root / f"development-search-league-{tag}-v1"
    model_dir = generation_root / "model"
    logs = generation_root / "logs"
    evaluation_root = generation_root / "evaluation" / profile_id
    evaluation_root.mkdir(parents=True, exist_ok=True)
    candidate_report = evaluation_root / "candidate-fixed.json"
    timed_report = evaluation_root / "candidate-timed.json"
    parent = Path(state["best"]["checkpoint"]).resolve()

    # The current parent is the stable anti-drift anchor.  The original
    # Hard-v2 corpus remains a foundation, but replaying only that old anchor
    # lets a fine-tune forget the strategy it is meant to improve.  The model
    # sees only observation-derived leaves; the checkpoint is not a hidden
    # feature and the generation remains a legal search teacher.
    if not (champion_anchor_dir / "manifest.json").exists():
        _run([
            sys.executable, "-m", "games.orbit.tools.native_value_data", str(champion_anchor_dir),
            "--games", str(args.anchor_games), "--namespace", f"train-search-champion-anchor-{tag}-v1",
            "--checkpoint", str(parent), "--primary", "neural-0", "--opponents", "neural-0",
            "--simulations", str(args.teacher_simulations), "--threads", str(args.threads),
            "--model-stride", str(args.model_stride), "--model-weight", str(args.model_weight),
            "--model-temperature", str(args.model_temperature),
            "--leaf", str(args.search_leaf),
            "--determinization-period", str(args.search_determinization_period),
            "--binary", str(_absolute(args.value_binary)),
        ], log_path=logs / "champion-anchor.log", label=f"{tag}-champion-anchor")
    if not (train_dir / "manifest.json").exists():
        train_data_command = [
            sys.executable, "-m", "games.orbit.tools.native_value_data", str(train_dir),
            "--games", str(args.train_games), "--namespace", f"train-search-league-{tag}-v1",
            "--opponents", str(getattr(args, "train_opponents", TRAIN_FAMILIES)),
            "--simulations", str(args.teacher_simulations), "--threads", str(args.threads),
            "--model-stride", str(args.model_stride), "--model-weight", str(args.model_weight),
            "--model-temperature", str(args.model_temperature),
            "--leaf", str(args.search_leaf),
            "--determinization-period", str(args.search_determinization_period),
            "--binary", str(_absolute(args.value_binary)),
        ]
        train_primary = str(getattr(args, "train_primary", "neural-0"))
        if train_primary.startswith("neural-"):
            train_data_command.extend(["--checkpoint", str(parent), "--primary", train_primary])
        else:
            train_data_command.extend(["--primary", train_primary])
        _run(train_data_command, log_path=logs / "train-data.log", label=f"{tag}-train-data")
    if not (dev_dir / "manifest.json").exists():
        _run([
            sys.executable, "-m", "games.orbit.tools.native_value_data", str(dev_dir),
            "--games", str(args.dev_games), "--namespace", f"development-search-league-{tag}-v1",
            "--primary", "expert", "--opponents", DEV_FAMILIES,
            "--simulations", str(args.teacher_simulations), "--threads", str(args.threads),
            "--model-stride", str(args.model_stride), "--model-weight", str(args.model_weight),
            "--model-temperature", str(args.model_temperature),
            "--leaf", str(args.search_leaf),
            "--determinization-period", str(args.search_determinization_period),
            "--binary", str(_absolute(args.value_binary)),
        ], log_path=logs / "development-data.log", label=f"{tag}-development-data")

    if not model_dir.exists() or not list(model_dir.glob("epoch-*.pt")):
        command = [
            sys.executable, "-m", "games.orbit.tools.value_campaign", "train",
            str(train_dir), str(dev_dir), str(model_dir), "--epochs", str(args.epochs),
            "--device", args.device, "--resume", str(parent), "--allow-data-change",
            "--per-seat", str(args.per_seat), "--root-value-beta", str(args.root_value_beta),
            "--batch-rows", str(args.batch_rows),
        ]
        if getattr(args, "fused_adam", False):
            command.append("--fused-adam")
        # Keep the foundation, this parent's self-play anchor and a bounded
        # recent window.  De-duplicate paths while preserving source order so
        # the checkpoint metadata explains the actual mixture.
        sources = [Path(state["anchor_data"]).resolve(), champion_anchor_dir.resolve(),
                   *_training_sources(state, window=args.history_window)]
        seen_sources: set[Path] = set()
        for source in sources:
            source = source.resolve()
            if source in seen_sources:
                continue
            seen_sources.add(source)
            command.extend(["--extra-data", str(source)])
        _run(command, log_path=logs / "training.log", label=f"{tag}-train")
    # Do not assume the last gradient step is the strongest policy.  Orbit's
    # held-out value loss has repeatedly disagreed with equal-time strength,
    # and the Expert-primary probe made the failure concrete: epoch 7 beat
    # epoch 8 at serving speed even though epoch 8 had the better development
    # loss.  A short timed scan costs seconds per epoch and prevents a later
    # checkpoint from silently replacing a stronger earlier one.
    checkpoint_scan: list[dict[str, Any]] = []
    checkpoint_candidates = _checkpoint_candidates(model_dir)
    if not checkpoint_candidates:
        raise FileNotFoundError(f"No epoch checkpoint in {model_dir}")
    scan_pairs = int(getattr(args, "checkpoint_scan_pairs", 0))
    checkpoint_selection: dict[str, Any] = {"kind": "last-epoch"}
    if scan_pairs:
        _ensure_timed_baseline(args, state_path, state, root)
        scan_root = evaluation_root / "checkpoint-scan"
        scan_root.mkdir(parents=True, exist_ok=True)
        # ONE pool for every epoch, so the scan is common-random-number PAIRED
        # across checkpoints.  Before 2026-09-11 the pool name embedded the
        # epoch, and `game_seed` hashes the pool name, so every epoch played a
        # DIFFERENT deal set and the argmax below was over independent noise:
        # max-of-eight at an eight-pair standard error returns ~0.66-0.75 from
        # checkpoints of identical strength, which is precisely the
        # g009/g010/g011 pattern.  Same deals means the epochs can actually be
        # ranked against each other.
        scan_pool = f"development-neural-league-{tag}-checkpoint-scan"
        window = int(getattr(args, "checkpoint_scan_epochs", 0) or len(checkpoint_candidates))
        scanned = checkpoint_candidates[-window:]
        for candidate in scanned:
            epoch = candidate.stem.split("-", 1)[-1]
            scan_report = scan_root / f"epoch-{epoch}-timed.json"
            if not scan_report.exists():
                _run(
                    _arena_command(
                        args,
                        candidate,
                        scan_report,
                        pairs=scan_pairs,
                        pool=scan_pool,
                        timed=True,
                    ),
                    log_path=logs / "arena.log",
                    label=f"{tag}-checkpoint-{epoch}-timed",
                )
            summary = _arena_summary(scan_report)
            checkpoint_scan.append({
                "epoch": epoch,
                "checkpoint": str(candidate.resolve()),
                "timed": summary,
            })
        checkpoint, checkpoint_selection = _select_checkpoint(
            checkpoint_scan, scanned[-1], margin=args.checkpoint_scan_margin)
    else:
        checkpoint = checkpoint_candidates[-1].resolve()

    if not candidate_report.exists():
        _run(
            _arena_command(args, checkpoint, candidate_report, pairs=args.screen_pairs,
                           pool=f"development-neural-league-{tag}-fixed", timed=False,
                           workers_override=args.screen_workers,
                           game_workers_override=args.screen_game_workers),
            log_path=logs / "arena.log",
            label=f"{tag}-fixed",
        )
    fixed = _arena_summary(candidate_report)

    # A fixed-simulation no-learning control catches model/export/search
    # asymmetries before a candidate is allowed to influence selection.
    mirror_report = evaluation_root / "candidate-self-fixed.json"
    if not mirror_report.exists():
        _run(
            _arena_command(args, checkpoint, mirror_report, pairs=args.mirror_pairs,
                           pool=f"development-neural-league-{tag}-mirror", timed=False,
                           opponent=checkpoint, simulations=args.mirror_simulations,
                           workers_override=args.screen_workers,
                           game_workers_override=args.screen_game_workers),
            log_path=logs / "arena.log", label=f"{tag}-mirror",
        )
    mirror = _arena_summary(mirror_report)
    if not mirror.get("mirror_passed", False):
        raise RuntimeError(f"{tag} neural self-gate failed; inspect {mirror_report}")

    # The parent comparison is the cheap near-peer panel.  A win over the
    # frozen Expert can otherwise be a matchup or winner's-curse artifact.
    peer_report = evaluation_root / "candidate-vs-parent-fixed.json"
    if not peer_report.exists():
        _run(
            _arena_command(args, checkpoint, peer_report, pairs=args.peer_pairs,
                           pool=f"development-neural-league-{tag}-peer", timed=False,
                           opponent=parent,
                           workers_override=args.screen_workers,
                           game_workers_override=args.screen_game_workers),
            log_path=logs / "arena.log", label=f"{tag}-peer",
        )
    peer = _arena_summary(peer_report)

    # Timed screens are deliberately gated by the cheap fixed result.  This is
    # the biggest campaign throughput win: weak learners do not spend hours in
    # equal-time arenas.  The timed screen is the calibrated fast proxy; the
    # actual browser profile is reserved for the rare promotion check.
    timed = None
    if fixed["pair_score"] >= args.timed_trigger or args.always_timed:
        _ensure_timed_baseline(args, state_path, state, root)
        if not timed_report.exists():
            _run(
                _arena_command(args, checkpoint, timed_report, pairs=args.timed_pairs,
                               pool=f"development-neural-league-{tag}-timed", timed=True),
                log_path=logs / "arena.log", label=f"{tag}-timed",
            )
        timed = _arena_summary(timed_report)

    # THE ACCUMULATION GATE.  The candidate plays the incumbent directly on
    # shared CRN deals at the serving-shaped proxy, and is accepted only when
    # the paired lower bound clears `--accept-lower`.  This is a different
    # decision from the release gate (`TARGET_SCORE` versus the frozen Expert),
    # and keeping them separate is the point: holding every generation to 0.75
    # is why twelve of them all fine-tuned the same parent.  The cheap fixed
    # screen still gates whether this expensive arena runs at all.
    # Before buying the arena, ask whether there is anything in it to see. Two
    # checkpoints that play the same moves produce the same games, and no width
    # separates them; this costs seconds against the arena's hour.
    policy_diff = None
    if args.agreement_games and checkpoint.resolve() != parent.resolve():
        diff_report = evaluation_root / "candidate-vs-incumbent-agreement.json"
        if not diff_report.exists():
            _run(
                [sys.executable, "-m", "games.orbit.tools.policy_diff",
                 str(parent), str(checkpoint),
                 "--games", str(args.agreement_games),
                 "--simulations", str(args.screen_simulations),
                 "--agreement-ceiling", str(args.agreement_ceiling),
                 "--binary", str(_absolute(args.policy_diff_binary)),
                 "--output", str(diff_report)],
                log_path=logs / "arena.log", label=f"{tag}-agreement",
            )
        policy_diff = _read_json(diff_report)

    head_to_head = None
    if (policy_diff is None or policy_diff.get("worth_an_arena", True)) \
            and _cheap_screens_justify_acceptance(fixed, timed, args):
        accept_report = evaluation_root / "candidate-vs-incumbent-timed.json"
        if not accept_report.exists():
            _run(
                _arena_command(args, checkpoint, accept_report, pairs=args.accept_pairs,
                               pool=f"development-neural-league-{tag}-accept", timed=True,
                               opponent=parent),
                log_path=logs / "arena.log", label=f"{tag}-accept",
            )
        head_to_head = _arena_summary(accept_report)

    state["champion_anchors"].append(str(champion_anchor_dir.resolve()))
    state["training_sources"].append(str(train_dir.resolve()))
    selection = (head_to_head or timed or fixed)["pair_score"]
    selection_kind = ("head-to-head" if head_to_head is not None
                      else "timed" if timed is not None else "fixed")
    best_selection = args.accept_lower
    accepted = (_accepted_head_to_head(head_to_head, lower=args.accept_lower)
                and peer["pair_score"] >= args.peer_floor)
    if accepted:
        state["best"] = {
            "checkpoint": str(checkpoint),
            "fixed_score": fixed["pair_score"],
            "timed_score": timed["pair_score"] if timed is not None else state["best"].get("timed_score"),
            "evaluation_id": profile_id,
            "generation": generation,
        }
    record = {
        "generation": generation,
        "parent": str(parent),
        "checkpoint": str(checkpoint),
        "checkpoint_scan": checkpoint_scan,
        "train_data": str(train_dir.resolve()),
        "champion_anchor": str(champion_anchor_dir.resolve()),
        "development_data": str(dev_dir.resolve()),
        "training_policy": {
            "primary": str(getattr(args, "train_primary", "neural-0")),
            "opponents": str(getattr(args, "train_opponents", TRAIN_FAMILIES)),
        },
        "fixed": fixed,
        "mirror": mirror,
        "near_peer": peer,
        "timed": timed,
        "head_to_head": head_to_head,
        "policy_diff": policy_diff,
        "checkpoint_selection": checkpoint_selection,
        "evaluation": _evaluation_profile(args),
        "evaluation_id": profile_id,
        "selection": {"kind": selection_kind, "score": selection,
                      "accept_lower": best_selection,
                      "near_peer_floor": args.peer_floor},
        "accepted_as_best": accepted,
        # The two bars are different decisions and are recorded as such: the
        # accumulation bar moves the incumbent, the release bar swaps the
        # serving tiers.  See AI_PLAN.md "The target is split into two numbers".
        "bars": {
            "accumulation": {"kind": "head-to-head vs incumbent",
                             "pairs": args.accept_pairs,
                             "paired_lower_ci95": args.accept_lower},
            "release": {"kind": "vs frozen current Expert",
                        "score": TARGET_SCORE, "paired_lower_ci95": TARGET_LOWER},
        },
    }
    state["generations"].append(record)
    # Keep the state useful even when a later command is interrupted.  The
    # generation is complete only after this write, so rerunning resumes from
    # its checkpoint and does not silently lose its measurements.
    _write_json(state_path, state)
    return accepted


def _maybe_confirm(args: argparse.Namespace, state_path: Path, state: dict[str, Any], root: Path) -> bool:
    if state.get("promotion", {}).get("status") == "passed":
        return True
    if not state.get("generations"):
        return False
    # Re-read every promising checkpoint on a fresh confirmation namespace,
    # rather than trusting the last noisy screen.  The Spender campaign found
    # that in-loop winners frequently regressed when re-gated at high N.
    profile_id = _profile_id(args)
    candidates = [item for item in state["generations"]
                  if item.get("evaluation_id") == profile_id
                  and item.get("accepted_as_best")
                  and float(item.get("near_peer", {}).get("pair_score", 0.0)) >= float(args.peer_floor)
                  and item.get("timed")
                  and item["timed"]["pair_score"] >= args.confirm_trigger]
    if not candidates:
        return False
    candidates.sort(key=lambda item: (item["timed"]["pair_score"], int(item["generation"])), reverse=True)
    attempts = []
    for latest in candidates:
        checkpoint = Path(latest["checkpoint"])
        confirm_dir = root / f"g{int(latest['generation']):03d}" / "confirmation" / profile_id
        confirm_dir.mkdir(parents=True, exist_ok=True)
        generation_attempt = {
            "generation": int(latest["generation"]),
            "checkpoint": str(checkpoint),
            "stages": [],
            "passed": False,
        }
        ladder = _confirmation_ladder(args)
        stage_trigger = float(getattr(args, "confirm_stage_trigger", 0.60))
        for pairs in ladder:
            report_path = confirm_dir / f"expert-confirm-{pairs}.json"
            if not report_path.exists():
                _run(
                    _arena_command(
                        args,
                        checkpoint,
                        report_path,
                        pairs=pairs,
                        pool=f"development-neural-league-g{int(latest['generation']):03d}-confirm-{pairs}",
                        timed=True,
                    ),
                    log_path=confirm_dir / "arena.log",
                    label=f"g{int(latest['generation']):03d}-confirm-{pairs}",
                )
            summary = _arena_summary(report_path)
            final = pairs == ladder[-1]
            fast_passed = (
                summary["censored"] == 0
                and summary["score"] >= TARGET_SCORE
                and summary["pair_ci95"][0] >= TARGET_LOWER
                and summary["complete_pairs"] == pairs
            ) if final else False
            stage_ok = fast_passed if final else _confirmation_stage_passed(
                summary,
                pairs=pairs,
                final_pairs=ladder[-1],
                stage_trigger=stage_trigger,
            )
            generation_attempt["stages"].append({
                "pairs": pairs,
                "summary": summary,
                "stage_trigger": None if final else stage_trigger,
                "stage_passed": stage_ok,
                "final": final,
            })
            if not stage_ok:
                break
            if final:
                # The fast proxy is the statistical gate.  Only a rare
                # serving-shaped sample is allowed to turn that into a
                # promotion claim; this is intentionally absent from every
                # ordinary generation screen.
                serving_pairs = int(getattr(args, "serving_check_pairs", 16))
                serving_floor = float(getattr(args, "serving_check_floor", 0.60))
                serving = None
                serving_ok = False
                if serving_pairs > 0:
                    serving_report = confirm_dir / f"expert-serving-check-{serving_pairs}.json"
                    if not serving_report.exists():
                        _run(
                            _arena_command(
                                args,
                                checkpoint,
                                serving_report,
                                pairs=serving_pairs,
                                pool=f"development-neural-league-g{int(latest['generation']):03d}-serving-check",
                                timed=True,
                                serving=True,
                            ),
                            log_path=confirm_dir / "arena.log",
                            label=f"g{int(latest['generation']):03d}-serving-check",
                        )
                    serving = _arena_summary(serving_report)
                    serving_ok = (
                        serving["censored"] == 0
                        and serving["complete_pairs"] == serving_pairs
                        and serving["score"] >= serving_floor
                    )
                generation_attempt["serving_check"] = {
                    "summary": serving,
                    "pairs": serving_pairs,
                    "floor": serving_floor,
                    "passed": serving_ok,
                    "profile": _evaluation_profile(args)["serving_check"],
                }
                generation_attempt["passed"] = serving_ok
                break
        attempts.append(generation_attempt)
        if generation_attempt["passed"]:
            break
    winner = next((item for item in attempts if item["passed"]), None)
    latest_attempt = attempts[-1] if attempts else None
    latest_stage = (latest_attempt.get("stages", [])[-1]
                    if latest_attempt and latest_attempt.get("stages") else None)
    state["promotion"] = {
        "status": "passed" if winner else "inconclusive",
        "checkpoint": winner["checkpoint"] if winner else None,
        "report": ({"proxy": winner["stages"][-1]["summary"],
                    "serving_check": winner.get("serving_check")}
                   if winner and winner.get("stages") else
                   (latest_stage["summary"] if latest_stage else None)),
        "attempts": attempts,
        "generation": int(winner["generation"] if winner else latest_attempt["generation"]),
        "evaluation": _evaluation_profile(args),
        "roster_transition": state["incumbent"]["transition"],
    }
    _write_json(state_path, state)
    return bool(winner)


def run(args: argparse.Namespace) -> dict[str, Any]:
    root = _absolute(args.root)
    root.mkdir(parents=True, exist_ok=True)
    state_path, state = _load_or_create(args, root)
    if int(args.iterations) < 1:
        raise ValueError("iterations must be positive")
    _ensure_baseline(args, state_path, state, root)
    lock = root / ".run.lock"
    try:
        descriptor = os.open(str(lock), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
    except FileExistsError as error:
        raise RuntimeError(f"League already appears to be running: {lock}") from error
    try:
        _write_json(state_path, state)
        first_generation = 1 + max((int(item.get("generation", 0)) for item in state.get("generations", [])), default=0)
        for generation in range(first_generation, first_generation + int(args.iterations)):
            if state.get("promotion", {}).get("status") == "passed":
                break
            _run_generation(args, state_path, state, generation, root)
            _maybe_confirm(args, state_path, state, root)
        return state
    finally:
        os.close(descriptor)
        try:
            lock.unlink()
        except FileNotFoundError:
            pass


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ORBIT_RUNS / "neural-league")
    parser.add_argument("--parent", type=Path, default=DEFAULT_PARENT)
    parser.add_argument("--anchor-data", type=Path, default=DEFAULT_ANCHOR)
    parser.add_argument("--value-binary", type=Path, default=DEFAULT_VALUE_BINARY)
    parser.add_argument("--arena-binary", type=Path, default=DEFAULT_ARENA_BINARY)
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260909)
    parser.add_argument("--train-games", type=int, default=448)
    parser.add_argument("--anchor-games", type=int, default=448,
                        help="Current-parent self-play anchor games (multiple of 16)")
    parser.add_argument("--dev-games", type=int, default=192)
    parser.add_argument("--teacher-simulations", type=int, default=64)
    parser.add_argument("--train-primary", default="neural-0",
                        help="Primary policy for fresh league data (neural-0 or a named specialist)")
    parser.add_argument("--train-opponents", default=TRAIN_FAMILIES,
                        help="Comma-separated opponent families for fresh league data")
    parser.add_argument("--screen-simulations", type=int, default=32,
                        help="Cheap fixed-simulation filter depth; never a promotion claim")
    parser.add_argument("--mirror-simulations", type=int, default=24,
                        help="Fixed simulations for exact self-gates (cheap by design)")
    parser.add_argument("--model-stride", type=int, default=1)
    parser.add_argument("--model-weight", type=float, default=1.0)
    parser.add_argument("--model-temperature", type=float, default=2.0)
    parser.add_argument("--threads", type=int, default=max(1, min((os.cpu_count() or 1) - 1, 16)),
                        help="Native value-data workers; leaves one host thread free, up to sixteen")
    parser.add_argument("--workers", type=int,
                        default=max(1, min((os.cpu_count() or 1) - 1, 16)),
                        help="Offline native root-parallel workers (up to sixteen; independent of browser pool cap)")
    parser.add_argument("--screen-workers", type=int, default=1,
                        help="Root trees per cheap fixed-simulation screen (one is sufficient for a filter)")
    parser.add_argument("--screen-game-workers", type=int, default=None,
                        help="Independent fixed-screen games in flight; defaults to filling the host for --screen-workers")
    parser.add_argument("--proxy-workers", type=int, default=DEFAULT_SERVING_WORKERS,
                        help="Root trees per game for the fast proxy (defaults to the four-tree serving shape)")
    parser.add_argument("--proxy-game-workers", type=int, default=None,
                        help="Independent proxy games in flight; defaults to filling the host for --proxy-workers")
    parser.add_argument("--timed-budget-ms", type=int, default=DEFAULT_PROXY_BUDGET_MS,
                        help="Fast equal-time proxy budget used for generation screens and confirmation")
    parser.add_argument("--timed-main-action-ms", type=int, default=DEFAULT_PROXY_MAIN_ACTION_MS)
    parser.add_argument("--timed-followup-ms", type=int, default=DEFAULT_PROXY_FOLLOWUP_MS)
    parser.add_argument("--serving-workers", type=int, default=DEFAULT_SERVING_WORKERS,
                        help="Worker count for the rare serving-shaped promotion check")
    parser.add_argument("--serving-budget-ms", type=int, default=DEFAULT_SERVING_BUDGET_MS,
                        help="Actual browser total turn budget for the rare promotion check")
    parser.add_argument("--serving-main-action-ms", type=int, default=DEFAULT_SERVING_MAIN_ACTION_MS)
    parser.add_argument("--serving-followup-ms", type=int, default=DEFAULT_SERVING_FOLLOWUP_MS)
    parser.add_argument("--serving-check-pairs", type=int, default=16,
                        help="Rare serving-shaped pairs after the fast 512-pair gate; zero leaves promotion unconfirmed")
    parser.add_argument("--serving-check-floor", type=float, default=0.60,
                        help="Minimum point score for the rare serving-shaped compatibility check")
    parser.add_argument("--screen-pairs", type=int, default=16)
    parser.add_argument("--timed-pairs", type=int, default=8)
    parser.add_argument("--checkpoint-scan-pairs", type=int, default=32,
                        help="Timed pairs per epoch checkpoint on ONE shared CRN pool; "
                             "zero disables checkpoint selection. Eight was the pre-audit "
                             "default and could not separate any two epochs")
    parser.add_argument("--checkpoint-scan-epochs", type=int, default=3,
                        help="Scan only the newest N epoch checkpoints; zero scans all")
    parser.add_argument("--checkpoint-scan-margin", type=float, default=0.08,
                        help="Paired margin the best epoch must beat the runner-up by; "
                             "below it the scan declines to pick and the last epoch is used")
    parser.add_argument("--mirror-pairs", type=int, default=8)
    parser.add_argument("--peer-pairs", type=int, default=8)
    parser.add_argument("--accept-pairs", type=int, default=128,
                        help="Head-to-head candidate-vs-incumbent pairs; this is the "
                             "accumulation bar that moves the incumbent")
    parser.add_argument("--accept-lower", type=float, default=0.50,
                        help="Paired 95%% lower bound the head-to-head must clear to accept")
    parser.add_argument("--accept-screen-floor", type=float, default=0.45,
                        help="Timed screen floor below which the head-to-head is not bought")
    parser.add_argument("--always-accept-arena", action="store_true",
                        help="Always buy the head-to-head arena (slow diagnostic mode)")
    parser.add_argument("--agreement-games", type=int, default=8,
                        help="Self-play games for the candidate-vs-incumbent move-agreement "
                             "pre-check; zero disables it")
    parser.add_argument("--agreement-ceiling", type=float, default=97.0,
                        help="Agreement percentage above which the candidate is treated as "
                             "a no-op and no arena is bought")
    parser.add_argument("--policy-diff-binary", type=Path,
                        default=DEFAULT_POLICY_DIFF_BINARY)
    parser.add_argument("--confirm-pairs", type=int, default=512)
    parser.add_argument("--confirm-ladder", default="32,128,512",
                        help="Fresh timed confirmation rungs, ending at --confirm-pairs")
    parser.add_argument("--confirm-trigger", type=float, default=0.68)
    parser.add_argument("--confirm-stage-trigger", type=float, default=0.60,
                        help="Directional score floor for non-final confirmation rungs")
    parser.add_argument("--timed-trigger", type=float, default=0.62,
                        help="Run the fast timed proxy once fixed score reaches this threshold")
    parser.add_argument("--peer-floor", type=float, default=0.50,
                        help="Minimum candidate-vs-parent score for selection")
    parser.add_argument("--always-timed", action="store_true",
                        help="Run timed screens for every candidate (slow diagnostic mode)")
    parser.add_argument("--baseline-timed", action="store_true",
                        help="Measure the fast proxy baseline before any candidate earns it")
    parser.add_argument("--epochs", type=int, default=2)
    parser.add_argument("--fused-adam", action="store_true",
                        help="Use fused FP32 AdamW; requires a separate strength A/B before campaign adoption")
    parser.add_argument("--search-leaf", choices=("state-value", "capture-progress-only"),
                        default="state-value",
                        help="Leaf evaluator for BOTH seats of every arena and for the "
                             "teacher; part of the evaluation profile id")
    parser.add_argument("--search-determinization-period", type=int, default=0,
                        help="Simulations per determinization for every arena and the "
                             "teacher; 0 is coherent. Part of the evaluation profile id, "
                             "because it changes what a score was measured against")
    parser.add_argument("--per-seat", type=int, default=8)
    parser.add_argument("--batch-rows", type=int, default=256,
                        help="Rows per optimizer update, shuffled across games. Zero is the "
                             "historical one-update-per-game behaviour, whose every batch was "
                             "a single game's sixteen perfectly correlated rows")
    parser.add_argument("--root-value-beta", type=float, default=0.25,
                        help="Blend searched root values into new rows (0 keeps outcome-only control)")
    parser.add_argument("--history-window", type=int, default=4)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cuda")
    args = parser.parse_args()
    if args.screen_game_workers is None:
        args.screen_game_workers = _default_proxy_game_workers(args.screen_workers)
    if args.proxy_game_workers is None:
        args.proxy_game_workers = _default_proxy_game_workers(args.proxy_workers)
    for name in ("screen_pairs", "timed_pairs", "mirror_pairs", "peer_pairs", "confirm_pairs",
                 "accept_pairs"):
        value = int(getattr(args, name))
        if value < 8 or value % 8:
            parser.error(f"--{name.replace('_', '-')} must be a positive multiple of eight")
    if args.checkpoint_scan_pairs < 0 or args.checkpoint_scan_pairs % 8:
        parser.error("--checkpoint-scan-pairs must be zero or a multiple of eight")
    if args.search_determinization_period < 0:
        parser.error("--search-determinization-period must be zero or positive")
    if args.checkpoint_scan_epochs < 0:
        parser.error("--checkpoint-scan-epochs must be zero or positive")
    if not 0.0 <= args.checkpoint_scan_margin <= 1.0:
        parser.error("--checkpoint-scan-margin must be between 0 and 1")
    if not 0.5 <= args.accept_lower < 1.0:
        parser.error("--accept-lower must be at least 0.5 and below 1")
    if not 0.0 <= args.accept_screen_floor <= 1.0:
        parser.error("--accept-screen-floor must be between 0 and 1")
    try:
        args.confirm_ladder = _confirmation_ladder(args)
    except (TypeError, ValueError) as error:
        parser.error(str(error))
    train_block = 16 * len(TRAIN_FAMILY_LIST)
    dev_block = 16 * len(DEV_FAMILY_LIST)
    if args.train_games < train_block or args.train_games % train_block:
        parser.error(f"--train-games must be a multiple of {train_block} (balanced training opponent families)")
    if args.dev_games < dev_block or args.dev_games % dev_block:
        parser.error(f"--dev-games must be a multiple of {dev_block} (balanced development opponent families)")
    if args.anchor_games < 16 or args.anchor_games % 16:
        parser.error("--anchor-games must be a positive multiple of 16")
    if (args.threads < 1 or args.threads > 16 or args.workers < 1 or args.workers > 16
            or args.screen_workers < 1 or args.screen_workers > 16
            or args.screen_game_workers < 1 or args.screen_game_workers > 16
            or args.screen_workers * args.screen_game_workers > 16
            or args.proxy_workers < 1 or args.proxy_workers > 16
            or args.proxy_game_workers < 1 or args.proxy_game_workers > 16
            or args.proxy_workers * args.proxy_game_workers > 16
            or args.serving_workers < 1 or args.serving_workers > 16):
        parser.error("native worker counts must be in 1..16 and screen/proxy worker products must be <=16")
    for name in ("timed_budget_ms", "timed_main_action_ms", "timed_followup_ms",
                 "serving_budget_ms", "serving_main_action_ms", "serving_followup_ms"):
        if int(getattr(args, name)) < 1:
            parser.error(f"--{name.replace('_', '-')} must be positive")
    if args.timed_main_action_ms > args.timed_budget_ms or args.timed_followup_ms > args.timed_budget_ms:
        parser.error("fast proxy action budgets must be within --timed-budget-ms")
    if args.serving_main_action_ms > args.serving_budget_ms or args.serving_followup_ms > args.serving_budget_ms:
        parser.error("serving action budgets must be within --serving-budget-ms")
    if args.serving_check_pairs < 0 or (args.serving_check_pairs and args.serving_check_pairs % 8):
        parser.error("--serving-check-pairs must be zero or a multiple of eight")
    if args.epochs < 1 or args.per_seat < 1 or args.teacher_simulations < 1 or args.screen_simulations < 1 or args.mirror_simulations < 1:
        parser.error("training and simulation counts must be positive")
    if args.model_stride < 1 or not 0.0 <= args.model_weight <= 1.0 or args.model_temperature <= 0:
        parser.error("--model-stride must be positive, --model-weight must be between 0 and 1, and --model-temperature positive")
    if not 0.0 <= args.root_value_beta <= 1.0:
        parser.error("--root-value-beta must be between 0 and 1")
    if not 0.5 <= args.confirm_trigger <= 1.0:
        parser.error("--confirm-trigger must be between 0.5 and 1")
    if not 0.5 <= args.confirm_stage_trigger <= 1.0:
        parser.error("--confirm-stage-trigger must be between 0.5 and 1")
    if not 0.5 <= args.timed_trigger <= 1.0:
        parser.error("--timed-trigger must be between 0.5 and 1")
    if not 0.0 <= args.serving_check_floor <= 1.0:
        parser.error("--serving-check-floor must be between 0 and 1")
    if not 0.0 <= args.peer_floor <= 1.0:
        parser.error("--peer-floor must be between 0 and 1")
    result = run(args)
    print(json.dumps({
        "best": result.get("best"),
        "generations": len(result.get("generations", [])),
        "promotion": result.get("promotion"),
        "state": str((_absolute(args.root) / "state.json").resolve()),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
