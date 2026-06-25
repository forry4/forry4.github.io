"""Terminal solver for a generated puzzle — the de-risking harness.

  --auto         replay the canonical solution and assert it wins (sanity check)
  (default)      interactive: you pick the hero moves; a wrong move restarts the puzzle,
                 exactly like the scripted serving model.

ASCII-only output (Windows console is cp1252).

  cd <puzzle-worktree> && python -m games.spender.puzzle.play_cli /tmp/puz/puzzle_000.json
"""
from __future__ import annotations

import argparse

from games.spender.ai.az import actions as A
from games.spender.ai.az import engine as E
from . import schema

_ABBR = "wbgrk"
_COLORS6 = list("wbgrk") + ["+"]   # +  = gold


def _card(ci: int) -> str:
    cost = E.COST[ci]
    cs = ",".join(f"{_ABBR[c]}{cost[c]}" for c in range(5) if cost[c])
    return f"{E.CARD_NAME[ci]} P{E.PTS[ci]} +{_ABBR[E.BONUS[ci]]} [{cs}]"


def _tok(t) -> str:
    return " ".join(f"{_COLORS6[c]}{t[c]}" for c in range(6) if t[c]) or "-"


def render(s: E.State, hero: int) -> str:
    opp = 1 - hero
    L = []
    L.append(f"--- TARGET {s.win_points} pts | "
             f"{'FINAL ROUND' if s.final_trigger >= 0 else 'play'} ---")
    for who, seat in (("YOU", hero), ("OPP", opp)):
        bon = " ".join(f"{_ABBR[c]}{s.bonuses[seat][c]}" for c in range(5))
        rsv = ", ".join(_card(ci) for ci in s.reserved[seat]) or "-"
        L.append(f"{who}: {s.points[seat]} pts | tokens[{_tok(s.tokens[seat])}] | "
                 f"bonus[{bon}] | reserved: {rsv}")
    L.append(f"bank: {_tok(s.bank)}")
    nobs = ", ".join(f"{E.NOBLE_NAME[ni]}(+{E.NOBLE_PTS[ni]} "
                     + "".join(f"{_ABBR[c]}{E.NOBLE_REQ[ni][c]}" for c in range(5) if E.NOBLE_REQ[ni][c])
                     + ")" for ni in s.nobles if ni >= 0)
    L.append(f"nobles: {nobs or '-'}")
    L.append("board:")
    for lvl in range(3):
        row = [f"#{slot%4}:{_card(s.board[slot])}" if s.board[slot] >= 0 else f"#{slot%4}:--"
               for slot in range(lvl * 4, lvl * 4 + 4)]
        L.append(f"  L{lvl+1}  " + "   ".join(row))
    return "\n".join(L)


def _auto(puzzle: dict) -> bool:
    s = E.from_game_dict(puzzle["position"])
    hero = puzzle["hero_seat"]
    for st in puzzle["steps"]:
        tag = "YOU" if st["is_hero"] else "opp"
        print(f"  [{tag}] {st['action_name']}")
        E.apply(s, st["action"])
    won = s.phase == E.OVER and s.winner == hero
    print(f"\nresult: phase={s.phase} winner={s.winner} hero={hero} -> "
          f"{'WIN' if won else 'NOT A WIN'}")
    print(f"final score  YOU {s.points[hero]}  OPP {s.points[1-hero]}")
    return won


def _interactive(puzzle: dict) -> None:
    hero = puzzle["hero_seat"]
    steps = puzzle["steps"]
    attempts = 0
    while True:
        attempts += 1
        s = E.from_game_dict(puzzle["position"])
        i = 0
        failed = False
        print(f"\n========== ATTEMPT {attempts} ==========")
        while i < len(steps):
            st = steps[i]
            if not st["is_hero"]:
                print(f"\n[opponent S] {st['action_name']}")
                E.apply(s, st["action"])
                i += 1
                continue
            print("\n" + render(s, hero))
            legal = E.legal_actions(s)
            print("your legal moves:")
            for j, a in enumerate(legal):
                print(f"   {j:2d}) {A.action_name(a)}")
            raw = input("pick #> ").strip()
            if not raw.isdigit() or int(raw) >= len(legal):
                print("  (invalid)")
                continue
            chosen = legal[int(raw)]
            if chosen == st["action"]:
                print(f"  [OK] {A.action_name(chosen)}")
                E.apply(s, chosen)
                i += 1
            else:
                print(f"  [X] {A.action_name(chosen)} is not the solution. Start over.")
                failed = True
                break
        if not failed:
            print("\n" + render(s, hero))
            print(f"\n*** SOLVED in {attempts} attempt(s)! "
                  f"YOU {s.points[hero]} - OPP {s.points[1-hero]} ***")
            return


def main():
    ap = argparse.ArgumentParser(description="Play / verify a Spender puzzle.")
    ap.add_argument("path")
    ap.add_argument("--auto", action="store_true", help="replay the solution and check it wins")
    args = ap.parse_args()
    puzzle = schema.load(args.path)
    hero = puzzle["hero_seat"]
    nh = sum(1 for st in puzzle["steps"] if st["is_hero"])
    print(f"puzzle: hero=seat{hero} target={puzzle['win_points']} K={puzzle['K']} "
          f"unique={puzzle['unique']} opp={puzzle['opponent']} | "
          f"{nh} hero moves to find\n")
    print(render(E.from_game_dict(puzzle["position"]), hero))
    print()
    if args.auto:
        _auto(puzzle)
    else:
        _interactive(puzzle)


if __name__ == "__main__":
    main()
