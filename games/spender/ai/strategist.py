"""A scripted 'strategist' opponent — an OFFLINE benchmark / training adversary.

This is NOT the production AI. Its purpose is to play *coherently and
threateningly* the way a strong human does, because our self-play opponent never
does — which is exactly why self-play has been blind to the value of blocking and
target commitment. The strategist gives us:

  1. A non-self-play **benchmark**: measure the real AI against an opponent that
     actually executes a plan and blocks (so denial/target-play finally matter).
  2. A future self-play **adversary** for Stage 2 (policy + exploration), where
     tactics like blocking can only be learned against something that threatens.

Strategy encoded (from the project's strong-player notes):
  - Identify cost-effective high-point L2/L3 cards (points-per-gem) as targets.
  - Build the bonus colours those targets need via cheap L1 cards.
  - Take gems directed at the current target, not smeared across the board.
  - Buy point cards when affordable; commit to the best target otherwise.
  - Late game, reserve a card the opponent is one buy away from, to deny it.
"""
from __future__ import annotations

from games.spender import main

GEMS = main.GEM_COLORS


def _affordable(game: dict, pid: str) -> list[dict]:
    ps = game["players"][pid]
    bonuses = main.bonuses_from(ps["purchased"])
    out = [c for lk in ("L3", "L2", "L1") for c in (game["board"].get(lk) or [])
           if c and main.can_afford(c["cost"], ps["tokens"], bonuses)]
    out += [c for c in ps["reserved"] if main.can_afford(c["cost"], ps["tokens"], bonuses)]
    return out


def _raw_deficit(card: dict, ps: dict, bonuses: dict) -> int:
    return sum(
        max(0, max(0, cost - bonuses.get(col, 0)) - ps["tokens"].get(col, 0))
        for col, cost in card["cost"].items() if col in GEMS
    )


def _best_target(game: dict, pid: str) -> dict | None:
    """Most attractive high-point L2/L3 (or reserved) card to race toward: high
    points and efficiency, lightly penalised by how far away it currently is."""
    ps = game["players"][pid]
    bonuses = main.bonuses_from(ps["purchased"])
    best, best_key = None, -1e9
    for lk in ("L3", "L2"):
        for c in (game["board"].get(lk) or []):
            if not c or c["points"] < 3:
                continue
            deficit = _raw_deficit(c, ps, bonuses)
            if deficit > 8:
                continue
            key = c["points"] + main._card_efficiency(c) * 2.0 - deficit * 0.3
            if key > best_key:
                best, best_key = c, key
    for c in ps["reserved"]:
        if c["points"] >= 3:
            key = c["points"] + main._card_efficiency(c) * 2.0
            if key > best_key:
                best, best_key = c, key
    return best


def _take_toward(game: dict, pid: str, target: dict) -> dict | None:
    """Take up to 3 gems directed at the target's remaining cost (double-take a
    dominant colour when the bank allows)."""
    ps = game["players"][pid]
    bonuses = main.bonuses_from(ps["purchased"])
    max_take = min(3, 10 - sum(ps["tokens"].values()))
    if max_take <= 0:
        return None
    deficits = {}
    for col, cost in target["cost"].items():
        if col in GEMS:
            need = max(0, max(0, cost - bonuses.get(col, 0)) - ps["tokens"].get(col, 0))
            if need > 0 and game["bank"].get(col, 0) > 0:
                deficits[col] = need
    if not deficits:
        return None
    cols = sorted(deficits, key=lambda c: -deficits[c])
    top = cols[0]
    if deficits[top] >= 2 and max_take >= 2 and game["bank"].get(top, 0) >= 4:
        return {"type": "take_gems", "colors": [top, top]}
    return {"type": "take_gems", "colors": cols[:max_take]}


def _take_general(game: dict, pid: str) -> dict | None:
    """Fallback: take the gems most demanded by the board's point cards."""
    ps = game["players"][pid]
    bonuses = main.bonuses_from(ps["purchased"])
    max_take = min(3, 10 - sum(ps["tokens"].values()))
    if max_take <= 0:
        return None
    need = {c: 0.0 for c in GEMS}
    for lk in ("L1", "L2", "L3"):
        for c in (game["board"].get(lk) or []):
            if not c:
                continue
            for col, cost in c["cost"].items():
                if col in need:
                    eff = max(0, cost - bonuses.get(col, 0))
                    need[col] += max(0, eff - ps["tokens"].get(col, 0)) * (c["points"] + 1)
    cols = sorted([c for c in GEMS if game["bank"].get(c, 0) > 0], key=lambda c: -need[c])
    return {"type": "take_gems", "colors": cols[:max_take]} if cols else None


def strategist_move(game: dict, pid: str) -> dict:
    """Return the strategist's move for `pid` in the given state."""
    ps = game["players"][pid]
    bonuses = main.bonuses_from(ps["purchased"])
    order = game["order"]
    opp_pid = next((p for p in order if p != pid), None)
    urgency = main._game_urgency(game)

    # 1. Buy a worthwhile point card if affordable (prefer points, then efficiency).
    affordable = _affordable(game, pid)
    point_buys = [c for c in affordable if c["points"] > 0]
    if point_buys:
        best = max(point_buys, key=lambda c: (c["points"], main._card_efficiency(c)))
        if best["points"] >= 2 or urgency > 0.5:
            return {"type": "buy", "card_id": best["id"]}

    # 2. Deny: in the mid/late game reserve a card the opponent is ~one buy from.
    if opp_pid and urgency >= 0.4 and len(ps["reserved"]) < 3:
        block = main._ai_find_block(game, pid, opp_pid, max(urgency, 0.6))
        if block and block["id"] not in {c["id"] for c in ps["reserved"]}:
            return {"type": "reserve", "card_id": block["id"]}

    # 3. Commit to a target and build toward it.
    target = _best_target(game, pid)
    if target:
        needed = {col for col, cost in target["cost"].items()
                  if col in GEMS and bonuses.get(col, 0) < cost}
        # 3a. Buy a cheap L1 card whose bonus is a colour the target still needs.
        best_l1, best_l1_key = None, -1.0
        for c in (game["board"].get("L1") or []):
            if c and c.get("bonus") in needed and main.can_afford(c["cost"], ps["tokens"], bonuses):
                key = main._card_efficiency(c) + (0.5 if c["points"] > 0 else 0.0)
                if key > best_l1_key:
                    best_l1, best_l1_key = c, key
        if best_l1:
            return {"type": "buy", "card_id": best_l1["id"]}
        # 3b. Otherwise take gems toward the target.
        mv = _take_toward(game, pid, target)
        if mv:
            return mv

    # 4. Fallbacks: grab any affordable card, else take the most-demanded gems.
    if affordable:
        return {"type": "buy", "card_id": affordable[0]["id"]}
    return _take_general(game, pid) or {"type": "take_gems", "colors": []}
