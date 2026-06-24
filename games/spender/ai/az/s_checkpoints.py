"""Past-S checkpoints: snapshot/restore the full tunable config that DEFINES variant S.

S has no weight file -- its "weights" are module-level constants spread across vsearch / v_state /
heuristic3 / valuation3. A checkpoint is a JSON snapshot of every STRATEGY constant, so a saved S
can be replayed EXACTLY as an opponent (apply its config before each of its moves -- the same
per-turn config swap config_selfgate uses) regardless of how the live module defaults drift later.

Two uses:
  - a same-strength, style-diverse RPS panel (today's S vs its past selves) -- a far sharper guard
    than the weak H3/H3N/H3R panel (S dominates the heuristics either way);
  - progress tracking (is this week's S actually stronger than last month's?).

The checkpoint is PER-MODULE so duplicate names across modules (e.g. NOBLE_TURN_W in both v_state
and valuation3) are captured/applied unambiguously. Pure serving/infra params (SIMS, SERVE_*, hard
caps) are intentionally EXCLUDED: a checkpoint captures STRATEGY, and offline gates pass sims
explicitly. Checkpoints are SMALL JSON and committed (unlike the gitignored AZ weight files).

CLI:
  python -m games.spender.ai.az.s_checkpoints save <name> [--note "..."]
  python -m games.spender.ai.az.s_checkpoints list
  python -m games.spender.ai.az.s_checkpoints show <name>
"""
from __future__ import annotations

import argparse
import ast
import copy
import datetime
import json
import os
import re
import subprocess

from . import heuristic3 as H3
from . import v_state
from . import valuation3 as V3
from . import vsearch

CKPT_DIR = os.path.join(os.path.dirname(__file__), "s_checkpoints")

# Every module-level constant that DEFINES S's play, per module. A NEW strategy knob must be added
# here or it won't be captured (snapshot() raises if a listed key goes missing, catching renames).
SNAPSHOT_KEYS = {
    "v_state": [
        "W_POINTS", "W_ENGINE_STK", "W_PROGRESS", "W_NOBLE", "W_ECON", "SCALE", "WIN_CONVEX",
        "NOBLE_TURN_W", "NOBLE_MULTI_W", "PROGRESS_TOPK", "PROGRESS_DECAY", "TURNS_REF",
        "ENGINE_DR_EXP", "ECON_HOARD", "ECON_GOLD", "BLIND_RESERVE_CONST", "RESERVE_PENALTY",
        "ENDGAME_TIEBREAK_W", "ENDGAME_TIE_ZONE", "ENDGAME_TIE_GAP",
    ],
    "vsearch": [
        "C_PUCT", "BACKUP_LAMBDA", "POLICY_TEMP", "RESERVE_PRIOR_W", "TAKE_PRIOR_W",
        "PRIOR_UNIFORM", "H3_PICK_W", "ENDGAME_NEAR", "ENDGAME_SIM_MULT", "ENDGAME_SERVE_TIME",
        "LEAF_MODE",
    ],
    "heuristic3": [
        "W_TEMPO", "W_GEM", "W_GOLD", "W_SHORTFALL", "TEMPO_TURNS_SCALE", "TEMPO_TURNS_T0",
        "NOBLE_SCALE", "NOBLE_SCARCITY", "STAGE_K", "STAGE_FLOOR", "STAGE_BLEND",
        "STAGE_CARD_OPP_W", "STAGE_PTS_OPP_W", "ENG_DECAY", "W_ENGINE", "CAP9_BUY_ABOVE",
        "CAP8_BUY_ABOVE", "GOLD_TIEBREAK", "USE_RESERVE", "USE_SPECULATIVE_RESERVE", "RESERVE_GAP",
        "WIN_RESERVE_MAX_TEMPO", "USE_TAKE2", "TAKE2_MIN_STEEP", "USE_OPP_SNIPE",
        "SNIPE_REQUIRE_OPP_TOP", "USE_DENY2", "USE_FINISH_RESERVE",
    ],
    "valuation3": [
        "GEM_DIST_W", "TURNS_FLOOR", "TURNS_MODE", "PLANNER_DECK_RATE", "PLANNER_MAX_STEPS",
        "PLANNER_SCALE", "RESERVE_TURN_ADJ", "GOLD_BANK_CAP", "ENG_DIV", "ENG_FLOOR", "ENG_DECK_W",
        "DECK_STAGE_TILT", "DECK_STAGE_T0", "DECK_BONUS_DISCOUNT", "ENG_WEIGHT_MODE",
        "ENG_TEMPO_SCALE", "ENG_RECURSE_W", "NOBLE_CLOSE_FLOOR", "NOBLE_TIME_GATE", "NOBLE_TURN_W",
        "EFF_REF", "USE_POTENTIAL_ENGINE", "POT_ENGINE_W", "POT_REACH_W", "REACH_DIV",
        "BUILD_FLOOR_W", "ENG_FIXEDPOINT", "ENG_FP_ITERS", "REACH_STEEP", "USE_TTA_GREEDY",
        "RESERVED_ENGINE_W",
    ],
}

_MODS = {"v_state": v_state, "vsearch": vsearch, "heuristic3": H3, "valuation3": V3}


def snapshot() -> dict:
    """Read the live module values for every SNAPSHOT_KEY -> per-module config dict."""
    out = {}
    for mod_name, keys in SNAPSHOT_KEYS.items():
        mod = _MODS[mod_name]
        d = {}
        for k in keys:
            if not hasattr(mod, k):
                raise SystemExit(f"snapshot: {mod_name}.{k} missing -- update SNAPSHOT_KEYS")
            d[k] = getattr(mod, k)
        out[mod_name] = d
    return out


def apply_config(cfg: dict) -> None:
    """Apply a per-module config dict (a checkpoint's 'config' field) to the live modules."""
    for mod_name, d in cfg.items():
        mod = _MODS.get(mod_name)
        if mod is None:
            continue
        for k, v in d.items():
            setattr(mod, k, v)


def _git_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=os.path.dirname(__file__), text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def save(name: str, note: str = "") -> str:
    os.makedirs(CKPT_DIR, exist_ok=True)
    path = os.path.join(CKPT_DIR, f"{name}.json")
    payload = {
        "name": name,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "git": _git_commit(),
        "note": note,
        "config": snapshot(),
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def load(name: str) -> dict:
    """Load a checkpoint by name (or path). Returns the full payload (config under ['config'])."""
    path = name if os.path.isfile(name) else os.path.join(CKPT_DIR, f"{name}.json")
    with open(path) as f:
        return json.load(f)


def load_config(name: str) -> dict:
    """Just the per-module config dict, ready for apply_config()."""
    return load(name)["config"]


def available() -> list:
    if not os.path.isdir(CKPT_DIR):
        return []
    return sorted(f[:-5] for f in os.listdir(CKPT_DIR) if f.endswith(".json"))


_FILES = {"v_state": "v_state.py", "vsearch": "vsearch.py",
          "heuristic3": "heuristic3.py", "valuation3": "valuation3.py"}
_REL = "games/spender/ai/az"


def _strip_comment(rhs: str) -> str:
    """Drop a trailing # comment, ignoring # inside string literals."""
    in_str = None
    for i, ch in enumerate(rhs):
        if in_str:
            if ch == in_str:
                in_str = None
        elif ch in "\"'":
            in_str = ch
        elif ch == "#":
            return rhs[:i]
    return rhs


def _parse_consts(text: str, keys) -> dict:
    """Pull `KEY = <literal>` assignments out of raw source for the given keys (literal_eval'd)."""
    out = {}
    for k in keys:
        m = re.search(rf"^{k}\s*(?::[^=\n]+)?=\s*(.+)$", text, re.M)
        if not m:
            continue
        try:
            out[k] = ast.literal_eval(_strip_comment(m.group(1)).strip())
        except Exception:
            pass  # expression / non-literal: leave it to fall back to today's default
    return out


def _git_show(commit: str, relpath: str) -> str:
    return subprocess.check_output(
        ["git", "show", f"{commit}:{_REL}/{relpath}"],
        cwd=os.path.dirname(__file__), text=True, stderr=subprocess.DEVNULL)


def reconstruct(commit: str, name: str, note: str = "") -> str:
    """Build a checkpoint = TODAY's full config overlaid with `commit`'s constant VALUES.

    Faithful to that commit's STRATEGY where the keys existed; keys that didn't exist yet keep
    today's default (those were new features, default/off historically). The CODE is today's --
    this is 'old weights on current code' (a reproducible STYLE), not a bit-exact resurrection.
    Files absent at `commit` (e.g. S not born yet) are skipped, keeping that module at today's config.
    """
    cfg = copy.deepcopy(snapshot())
    found = 0
    missing_files = []
    for mod_name, relpath in _FILES.items():
        try:
            text = _git_show(commit, relpath)
        except subprocess.CalledProcessError:
            missing_files.append(relpath)
            continue
        for k, v in _parse_consts(text, SNAPSHOT_KEYS[mod_name]).items():
            cfg[mod_name][k] = v
            found += 1
    os.makedirs(CKPT_DIR, exist_ok=True)
    path = os.path.join(CKPT_DIR, f"{name}.json")
    payload = {
        "name": name,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "git": commit,
        "reconstructed_from": commit,
        "note": note + (f"  [files absent at {commit}: {missing_files}]" if missing_files else ""),
        "config": cfg,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def derive(name: str, overrides_spec: str, note: str = "") -> str:
    """Build a checkpoint = TODAY's config with flat KEY=VAL;... overrides (every module that has it)."""
    cfg = copy.deepcopy(snapshot())
    for tok in overrides_spec.split(";"):
        tok = tok.strip()
        if not tok:
            continue
        k, v = tok.split("=")
        try:
            f = float(v)
            val = int(f) if (f.is_integer() and "." not in v) else f
        except ValueError:
            val = v
        placed = False
        for d in cfg.values():
            if k in d:
                d[k] = val
                placed = True
        if not placed:
            raise SystemExit(f"override key '{k}' not in any module's snapshot")
    os.makedirs(CKPT_DIR, exist_ok=True)
    path = os.path.join(CKPT_DIR, f"{name}.json")
    payload = {
        "name": name,
        "created": datetime.datetime.now().isoformat(timespec="seconds"),
        "git": _git_commit(),
        "note": note,
        "config": cfg,
    }
    with open(path, "w") as f:
        json.dump(payload, f, indent=2)
    return path


def diff_from_live(cfg: dict) -> dict:
    """{'<mod>.<key>': (checkpoint_value, live_value)} for keys that differ from the live modules."""
    live = snapshot()
    out = {}
    for m, d in cfg.items():
        for k, v in d.items():
            lv = live.get(m, {}).get(k)
            if lv != v:
                out[f"{m}.{k}"] = (v, lv)
    return out


def main():
    ap = argparse.ArgumentParser(description="Save/list/show past-S strategy checkpoints.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_save = sub.add_parser("save", help="snapshot the live S config to a named checkpoint")
    p_save.add_argument("name")
    p_save.add_argument("--note", default="")
    sub.add_parser("list", help="list saved checkpoints")
    p_show = sub.add_parser("show", help="print a checkpoint's metadata + diff from the live config")
    p_show.add_argument("name")
    p_rec = sub.add_parser("reconstruct", help="build a checkpoint from a past commit's constants")
    p_rec.add_argument("commit")
    p_rec.add_argument("name")
    p_rec.add_argument("--note", default="")
    p_der = sub.add_parser("derive", help="build a checkpoint = today's config + KEY=VAL;... overrides")
    p_der.add_argument("name")
    p_der.add_argument("--set", required=True, dest="overrides")
    p_der.add_argument("--note", default="")
    args = ap.parse_args()

    if args.cmd == "save":
        path = save(args.name, args.note)
        n = sum(len(d) for d in snapshot().values())
        print(f"saved {n} constants -> {path}")
    elif args.cmd == "list":
        names = available()
        if not names:
            print(f"(no checkpoints in {CKPT_DIR})")
        for nm in names:
            p = load(nm)
            print(f"  {nm:<28} {p.get('created','?'):<20} git:{p.get('git','?'):<10} {p.get('note','')}")
    elif args.cmd == "reconstruct":
        path = reconstruct(args.commit, args.name, args.note)
        d = diff_from_live(load(args.name)["config"])
        print(f"reconstructed {args.name} from {args.commit} -> {path}")
        print(f"  {len(d)} constants differ from today:")
        for k, (cv, lv) in sorted(d.items()):
            print(f"    {k:<34} {cv!r:<12} (today {lv!r})")
    elif args.cmd == "derive":
        path = derive(args.name, args.overrides, args.note)
        print(f"derived {args.name} -> {path}")
    elif args.cmd == "show":
        p = load(args.name)
        print(f"name:    {p['name']}")
        print(f"created: {p.get('created','?')}")
        print(f"git:     {p.get('git','?')}")
        print(f"note:    {p.get('note','')}")
        d = diff_from_live(p["config"])
        if not d:
            print("diff vs live: (identical)")
        else:
            print(f"diff vs live ({len(d)} keys):")
            for k, (cv, lv) in sorted(d.items()):
                print(f"  {k:<34} checkpoint={cv!r:<12} live={lv!r}")


if __name__ == "__main__":
    main()
