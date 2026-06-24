"""Reconstruct a finished Spender game from its persisted data and re-score every
turn with the variant-S position evaluator (v_state).

Why this exists
---------------
A persisted game keeps only the FINAL state plus an id-only move log. The deck is
shuffled in place and popped during play with no seed stored, so the 12-card board
at each past turn — the biggest input to the S evaluator — is otherwise lost. The
fix (see main._capture_setup) snapshots the dealt initial board / deck-order /
nobles once at game creation into game["setup"]. With that snapshot + the move log
(which now also records discards), a game is fully replayable: rebuild the initial
game dict, re-apply the logged moves, and at every turn convert to an AZ engine
State and call v_state.value / v_state.components.

Inputs
------
- A /games/{id}/full admin dump: {"game": {...}, "players": {...}, "ai_variant": ...}
- A raw persisted state_json row: {"game": {...}, ...}
- A bare game dict (has "order" / "setup" at the top level)
all expose the game dict; load_game() finds it.

Limitations
-----------
- v_state is 2-player only, so evaluation requires exactly two seats.
- A game created before the setup snapshot (old games / LBBMRC) has no
  game["setup"] and cannot be reconstructed — load is fine, evaluate raises.

CLI
---
    python -m games.spender.ai.az.replay dump.json [--seat ai|mover|0|1]
                                                   [--csv out.csv] [--json out.json]
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
from typing import Any, Iterator

from games.spender import main as M


class ReplayError(Exception):
    """The game cannot be reconstructed (missing setup, unknown move, deck desync)."""


# ─── id -> full card / noble dict (the log stores ids only) ───────────────────

_CATALOG: dict | None = None


def _catalog() -> dict:
    global _CATALOG
    if _CATALOG is None:
        _CATALOG = M.card_catalog()
    return _CATALOG


def card_from_id(cid: str) -> dict:
    c = _catalog()[cid]
    return {"id": cid, "level": c["level"], "points": c["points"],
            "bonus": c["bonus"], "cost": dict(c["cost"])}


_NOBLE_BY_ID = {n["id"]: n for n in M.ALL_NOBLES}


def noble_from_id(nid: str) -> dict:
    n = _NOBLE_BY_ID[nid]
    return {"id": n["id"], "points": n["points"], "req": dict(n["req"])}


# ─── initial state from the setup snapshot ────────────────────────────────────

def initial_from_setup(setup: dict, order: list[str], win_points: int = 15,
                       ai_player: str | None = None) -> dict:
    """Rebuild the game dict as it was right after the deal (before any move) from
    the ids-only setup snapshot. The starting bank is derived from the seat count
    (main._bank_for), exactly as the create paths set it."""
    decks = {lk: [card_from_id(cid) for cid in setup["decks"][lk]] for lk in setup["decks"]}
    board = {lk: [(card_from_id(cid) if cid else None) for cid in setup["board"][lk]]
             for lk in setup["board"]}
    nobles = [noble_from_id(nid) for nid in setup["nobles"]]
    g: dict = {
        "bank": M._bank_for(len(order)),
        "decks": decks,
        "board": board,
        "nobles": nobles,
        "players": {pid: {"tokens": M.empty_gems(), "purchased": [], "reserved": [], "nobles": []}
                    for pid in order},
        "order": list(order),
        "turn": order[0],
        "phase": "playing",
        "winner": None,
        "moves": [],
        "win_points": int(win_points),
    }
    if ai_player:
        g["ai_player"] = ai_player
    return g


# ─── applying a single logged move (effect only; turn logic is reused below) ───

PRIMARY = {"take_gems", "buy", "reserve"}   # one per turn; the rest (discard/noble) trail it


def _apply_buy(g: dict, ps: dict, card_id: str) -> None:
    bonuses = M.bonuses_from(ps["purchased"])
    card = None
    src: tuple | None = None
    for lk in ("L1", "L2", "L3"):
        for i, c in enumerate(g["board"][lk]):
            if c and c["id"] == card_id:
                card, src = c, ("board", lk, i)
                break
        if card:
            break
    if card is None:
        for i, c in enumerate(ps["reserved"]):
            if c["id"] == card_id:
                card, src = c, ("reserved", i)
                break
    if card is None or src is None:
        raise ReplayError(f"buy: card {card_id!r} not on board or in reserve")
    # Payment is deterministic (colored first, gold for the shortfall) — main's own rule.
    spend = M.calc_spend(card["cost"], ps["tokens"], bonuses)
    for c, n in spend.items():
        ps["tokens"][c] = ps["tokens"].get(c, 0) - n
        g["bank"][c] = g["bank"].get(c, 0) + n
    ps["purchased"].append(card)
    if src[0] == "board":
        lk, i = src[1], src[2]
        g["board"][lk][i] = g["decks"][lk].pop() if g["decks"][lk] else None
    else:
        ps["reserved"].pop(src[1])


def _apply_reserve(g: dict, ps: dict, mv: dict) -> None:
    card_id = mv.get("card_id")
    from_deck = bool(mv.get("from_deck"))
    deck_level = mv.get("deck_level")
    card = None
    # A visible board reserve (card_id present, not flagged from_deck).
    if card_id and not from_deck:
        for lk in ("L1", "L2", "L3"):
            for i, c in enumerate(g["board"][lk]):
                if c and c["id"] == card_id:
                    card = c
                    g["board"][lk][i] = g["decks"][lk].pop() if g["decks"][lk] else None
                    break
            if card:
                break
    # A blind deck-top reserve: main logs card_id + from_deck=True; the AZ bridge
    # logs deck_level only. Both mean "pop the top of that level's deck".
    if card is None:
        lk = f"L{deck_level}" if deck_level else (card_id.split("-")[0] if card_id else None)
        if not lk or not g["decks"].get(lk):
            raise ReplayError(f"reserve: cannot resolve {mv!r}")
        card = g["decks"][lk].pop()
        card["from_deck"] = True
        if card_id and card["id"] != card_id:   # deck desync -> the replay is wrong
            raise ReplayError(f"reserve: deck-top {card['id']!r} != logged {card_id!r} (deck desync)")
    ps["reserved"].append(card)
    if g["bank"].get("gold", 0) > 0:   # a reserve always grabs a gold if one is available
        g["bank"]["gold"] -= 1
        ps["tokens"]["gold"] = ps["tokens"].get("gold", 0) + 1


def _apply_noble(g: dict, ps: dict, noble_id: str) -> None:
    noble = next((n for n in g["nobles"] if n["id"] == noble_id), None)
    if noble is None:
        raise ReplayError(f"noble {noble_id!r} not available to claim")
    ps["nobles"].append(noble)
    g["nobles"] = [x for x in g["nobles"] if x["id"] != noble_id]


def apply_logged_move(g: dict, mv: dict) -> None:
    """Apply one logged move's EFFECT in place (tokens / bank / cards / nobles).
    Turn advancement is handled by the caller via main._finish_turn at turn end."""
    pid = mv["pid"]
    ps = g["players"][pid]
    t = mv["type"]
    if t == "take_gems":
        for c in mv.get("colors", []):
            g["bank"][c] = g["bank"].get(c, 0) - 1
            ps["tokens"][c] = ps["tokens"].get(c, 0) + 1
    elif t == "discard":
        c = mv["color"]
        ps["tokens"][c] = ps["tokens"].get(c, 0) - 1
        g["bank"][c] = g["bank"].get(c, 0) + 1
    elif t == "buy":
        _apply_buy(g, ps, mv["card_id"])
    elif t == "reserve":
        _apply_reserve(g, ps, mv)
    elif t in ("noble", "pick_noble"):
        _apply_noble(g, ps, mv["noble_id"])
    else:
        raise ReplayError(f"unknown logged move type {t!r}")


# ─── turn-by-turn replay ──────────────────────────────────────────────────────

def chronological_moves(game: dict) -> list[dict]:
    """game['moves'] is stored newest-first; return it oldest-first."""
    return list(reversed(game.get("moves", [])))


def turn_snapshots(g0: dict, chrono: list[dict]) -> Iterator[tuple[int, str, dict | None, dict]]:
    """Walk the chronological move log, applying each turn (one primary move + its
    trailing discard/noble sub-moves) and yielding the position at the START of each
    turn, then the final position. Yields (turn_index, mover_pid, primary_move, game)
    where `game` is a deepcopy safe to convert/eval and `primary_move` is the move the
    mover is about to make (None for the final snapshot). g0 is mutated."""
    g = g0
    i = 0
    turn = 0
    n = len(chrono)
    while i < n:
        mover = chrono[i]["pid"]
        primary = chrono[i]
        yield (turn, mover, primary, copy.deepcopy(g))
        apply_logged_move(g, chrono[i])
        i += 1
        while i < n and chrono[i]["type"] not in PRIMARY and chrono[i]["pid"] == mover:
            apply_logged_move(g, chrono[i])
            i += 1
        M._finish_turn(g, mover)
        turn += 1
    yield (turn, g["turn"], None, copy.deepcopy(g))


def reconstruct(game: dict) -> tuple[dict, list[dict]]:
    """(initial game dict, chronological moves) for a persisted game with a setup snapshot."""
    setup = game.get("setup")
    if not setup:
        raise ReplayError("game has no 'setup' snapshot (created before replay support) "
                          "— deck order is unrecoverable, cannot reconstruct")
    g0 = initial_from_setup(setup, game["order"], game.get("win_points", 15), game.get("ai_player"))
    return g0, chronological_moves(game)


# ─── evaluation with v_state ──────────────────────────────────────────────────

_COMPONENT_KEYS = ("points", "engine", "progress", "noble", "econ")


def evaluate(game: dict, seat: str = "ai") -> list[dict]:
    """Reconstruct the game and return one record per turn (plus the final position).
    `seat` fixes whose perspective the value is reported from:
      'ai'    -> the AI player's seat (falls back to seat 0 if no ai_player) [default]
      'mover' -> the player about to move at that turn (a zig-zag curve)
      '0'/'1' -> a fixed seat index
    Each record: turn, mover, seat, terminal, points{pid:int}, value, move, components{}."""
    from games.spender.ai.az import engine as E, v_state

    order = game["order"]
    if len(order) != 2:
        raise ReplayError(f"v_state evaluation is 2-player only (game has {len(order)} seats)")

    if seat == "ai":
        ai = game.get("ai_player")
        fixed: int | None = order.index(ai) if ai in order else 0
    elif seat == "mover":
        fixed = None
    elif seat in ("0", "1"):
        fixed = int(seat)
    else:
        raise ReplayError(f"bad --seat {seat!r} (use ai|mover|0|1)")

    g0, chrono = reconstruct(game)
    records: list[dict] = []
    for turn, mover, primary, g in turn_snapshots(g0, chrono):
        s = E.from_game_dict(g)
        seat_i = fixed if fixed is not None else order.index(mover)
        terminal = g.get("phase") == "over"
        rec: dict[str, Any] = {
            "turn": turn,
            "mover": mover,
            "seat": seat_i,
            "terminal": terminal,
            "points": {pid: M._calc_points(g["players"][pid]) for pid in order},
            "value": v_state.value(s, seat_i),
            "move": _describe(primary) if primary else None,
        }
        if not terminal:
            comps = v_state.components(s, seat_i)
            rec["components"] = {k: comps[f"{k}_me"] for k in _COMPONENT_KEYS}
            rec["components"]["stand_me"] = comps["stand_me"]
            rec["components"]["stand_opp"] = comps["stand_opp"]
        records.append(rec)
    return records


def _describe(mv: dict) -> str:
    t = mv.get("type")
    if t == "take_gems":
        cols = mv.get("colors") or []
        return "take " + ("+".join(cols) if cols else "nothing")
    if t == "buy":
        return f"buy {mv.get('card_id')}"
    if t == "reserve":
        tag = " (deck)" if mv.get("from_deck") or mv.get("deck_level") else ""
        return f"reserve {mv.get('card_id') or 'L' + str(mv.get('deck_level'))}{tag}"
    return t or "?"


# ─── loading + CLI ────────────────────────────────────────────────────────────

def load_game(path: str) -> tuple[dict, dict]:
    """Return (game_dict, meta) from a JSON file. Accepts a /games/{id}/full dump, a
    raw persisted state_json, or a bare game dict. meta carries players/ai_variant if present."""
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    game = data.get("game", data) if isinstance(data, dict) else None
    if not isinstance(game, dict) or "order" not in game:
        raise ReplayError(f"{path}: no game dict found (expected a /full dump, state_json, or game dict)")
    meta = {"players": data.get("players") if isinstance(data, dict) else None,
            "ai_variant": data.get("ai_variant") if isinstance(data, dict) else None}
    return game, meta


def _print_table(records: list[dict], game: dict, meta: dict) -> None:
    order = game["order"]
    names = (meta.get("players") or {})
    label = {pid: names.get(pid, pid) for pid in order}
    seat_i = records[0]["seat"] if records else 0
    who = label.get(order[seat_i], order[seat_i]) if records and records[0].get("seat") is not None else "?"
    av = meta.get("ai_variant")
    print(f"order: {' vs '.join(label[p] for p in order)}"
          + (f"   ai_variant={av}" if av else "")
          + f"   win_points={game.get('win_points', 15)}")
    print(f"value reported from seat {seat_i} ({who})'s perspective; range [-1, 1]\n")
    head = f"{'turn':>4}  {'mover':<10} {'pts':>9}  {'value':>7}  {'move':<22} components(pts/eng/prog/nob/econ)"
    print(head)
    print("-" * len(head))
    for r in records:
        pts = "/".join(str(r["points"][p]) for p in order)
        comp = ""
        if r.get("components"):
            c = r["components"]
            comp = " ".join(f"{c[k]:+.2f}" for k in _COMPONENT_KEYS)
        mover = label.get(r["mover"], r["mover"])
        tag = "  [final]" if r["terminal"] else ""
        print(f"{r['turn']:>4}  {mover:<10} {pts:>9}  {r['value']:+.3f}  "
              f"{(r['move'] or '—'):<22} {comp}{tag}")


def main_cli(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Replay a finished Spender game and re-score it with variant S.")
    ap.add_argument("file", help="JSON: a /games/{id}/full dump, a state_json row, or a bare game dict")
    ap.add_argument("--seat", default="ai", help="perspective for the value: ai|mover|0|1 (default ai)")
    ap.add_argument("--csv", help="write per-turn records to this CSV file")
    ap.add_argument("--json", dest="json_out", help="write per-turn records to this JSON file")
    ap.add_argument("--quiet", action="store_true", help="don't print the table")
    args = ap.parse_args(argv)

    try:
        game, meta = load_game(args.file)
        records = evaluate(game, seat=args.seat)
    except ReplayError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2

    if not args.quiet:
        _print_table(records, game, meta)
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as f:
            json.dump(records, f, indent=2)
        print(f"\nwrote {len(records)} records -> {args.json_out}", file=sys.stderr)
    if args.csv:
        _write_csv(records, game, args.csv)
        print(f"wrote {len(records)} rows -> {args.csv}", file=sys.stderr)
    return 0


def _write_csv(records: list[dict], game: dict, path: str) -> None:
    import csv
    order = game["order"]
    cols = (["turn", "mover", "seat", "terminal", "value", "move"]
            + [f"pts_{p}" for p in order]
            + [f"c_{k}" for k in _COMPONENT_KEYS] + ["c_stand_me", "c_stand_opp"])
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(cols)
        for r in records:
            comps = r.get("components") or {}
            w.writerow([r["turn"], r["mover"], r["seat"], int(r["terminal"]),
                        f"{r['value']:.6f}", r["move"] or ""]
                       + [r["points"][p] for p in order]
                       + [f"{comps.get(k, ''):.6f}" if k in comps else "" for k in _COMPONENT_KEYS]
                       + [f"{comps.get('stand_me', ''):.6f}" if "stand_me" in comps else "",
                          f"{comps.get('stand_opp', ''):.6f}" if "stand_opp" in comps else ""])


if __name__ == "__main__":
    raise SystemExit(main_cli())
