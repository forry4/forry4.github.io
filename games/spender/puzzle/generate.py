"""Puzzle generator — harvest late-game positions, keep the ones that are a UNIQUE
forced win for the side to move AND that the obvious (greedy) move does NOT solve.

Pipeline:
  1. harvest — play eps-randomized H3-vs-H3 games; snapshot positions where the side
     to move is CLOSE to the win but hasn't triggered the final round (varied, "messy"
     endgames where a precise line is needed).
  2. screen  — for each, run the forced-win solver. Keep iff a forced win exists, the
     line is unique at every hero decision, and H3-greedy does NOT already win.
  3. emit    — build the scripted puzzle file (embedded snapshots) and save.

`--opponent h3` (default) screens fast to prove the machine; `--opponent s` uses
variant S (the deployed target) — slower, the real puzzles. Screening with H3 first
then re-verifying survivors with S is the cheap path (see --reverify-s).

Run from the puzzle worktree (python -m runs the CWD's code):
  cd <puzzle-worktree> && python -m games.spender.puzzle.generate --games 200 --out /tmp/puz
"""
from __future__ import annotations

import argparse
import os
import random

from games.spender.ai.az import actions as _A
from games.spender.ai.az import engine as E
from . import schema, solver


def difficulty_of(s: E.State, hero: int, sol) -> str:
    """A meaningful difficulty from how NON-OBVIOUS the winning first move is.
    (Depth/K isn't an axis: K>=3 strict-unique puzzles are ~never satisfiable.)
      Easy   — greedy H3 would already play the winning first move (the rest is the trap).
      Tricky — the winning first move is a buy/take greedy wouldn't pick.
      Hard   — the winning first move is a *reserve* (the sneakiest setup).
    """
    canonical = sol.line[0][1]
    if solver.H3.choose_action(s, hero) == canonical:
        return "Easy"
    return "Hard" if _A.action_to_move(s, canonical).get("type") == "reserve" else "Tricky"


def harvest(n_games: int, win_points: int, eps: float, rng: random.Random,
            near_lo: int, near_hi: int, max_positions: int, opp_near: int = 0) -> list:
    """Play eps-randomized H3 self-play; return (state, hero) candidates where the
    side to move has points in [win_points-near_hi, win_points-near_lo] and the final
    round hasn't triggered. With opp_near>0, ALSO require the opponent within opp_near
    points of the win — i.e. a real RACE, where a wasted hero move actually loses
    (concentrates the rare strict 3-move puzzles)."""
    opp = solver.h3_opponent()
    seen = set()
    out = []
    for _ in range(n_games):
        s = E.new_game(rng, win_points=win_points)
        for _ in range(solver._RECURSION_CAP):
            if s.phase == E.OVER:
                break
            if (s.phase == E.PLAY and s.final_trigger < 0
                    and win_points - near_hi <= s.points[s.turn] <= win_points - near_lo
                    and (opp_near <= 0 or s.points[1 - s.turn] >= win_points - opp_near)):
                k = solver.state_key(s)
                if k not in seen:
                    seen.add(k)
                    out.append((s.clone(), s.turn))
                    if len(out) >= max_positions:
                        return out
            # eps-random move to vary the endgames; else greedy
            a = (rng.choice(E.legal_actions(s)) if rng.random() < eps else opp(s))
            E.apply(s, a)
    return out


def screen(positions: list, K: int, opp, opp_name: str, verbose: bool = False,
           require_exact: bool = False, require_strict: bool = False,
           require_fair: bool = False, out_dir: str = "") -> list:
    """Return built puzzles for positions that are unique forced wins the greedy line
    does not solve. With require_exact, also demand NO forced win in fewer than K moves
    (a true K-mover). With require_strict, also demand EVERY deviation loses — at each
    hero step the only non-losing move is the canonical one ("play these or lose").
    Writes each puzzle to out_dir as it's found (incremental)."""
    puzzles = []
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    for i, (s, hero) in enumerate(positions):
        if verbose and i and i % 200 == 0:
            print(f"  ...screened {i}/{len(positions)} ({len(puzzles)} found)", flush=True)
        if solver.is_trivial(s, hero, K, opp):
            continue                                   # obvious move already wins
        if require_exact and K > 1 and solver.solve(s, hero, K - 1, opp) is not None:
            continue                                   # a shorter forced win exists
        if require_fair:
            fair, sol = solver.refill_fair(s, hero, K, opp)   # unique AND deck-invariant
            if not fair:
                continue
        else:
            sol = solver.solve(s, hero, K, opp)
            if sol is None or not sol.unique:
                continue
        if require_strict and not solver.every_deviation_loses(s, hero, sol.line, opp):
            continue                                   # some deviation doesn't lose
        meta = {
            "source": "h3_selfplay_eps",
            "difficulty": difficulty_of(s, hero, sol),
            "strict": require_strict,
            "hero_points_start": s.points[hero],
            "opp_points_start": s.points[1 - hero],
            "solution_len_hero": sum(1 for st in sol.line if st[0] == hero),
            "opp_calls": sol.opp_calls,
        }
        puz = schema.build_puzzle(s, sol, opponent=opp_name, meta=meta)
        puzzles.append(puz)
        if out_dir:
            schema.save(puz, os.path.join(out_dir, f"puzzle_{len(puzzles):03d}.json"))
        if verbose:
            print(f"  [{i}] {'STRICT ' if require_strict else ''}PUZZLE: hero {hero} "
                  f"{s.points[hero]}pts -> win in {meta['solution_len_hero']} moves "
                  f"(opp_calls={sol.opp_calls})", flush=True)
    return puzzles


def main():
    ap = argparse.ArgumentParser(description="Generate Spender endgame puzzles.")
    ap.add_argument("--games", type=int, default=150, help="self-play games to harvest from")
    ap.add_argument("--max-positions", type=int, default=400, help="cap on harvested positions")
    ap.add_argument("--win-points", type=int, default=15)
    ap.add_argument("--K", type=int, default=2, help="hero turns allowed to force the win")
    ap.add_argument("--near-lo", type=int, default=1)
    ap.add_argument("--near-hi", type=int, default=7, help="harvest hero points in [WP-hi, WP-lo]")
    ap.add_argument("--eps", type=float, default=0.2, help="random-move rate while harvesting")
    ap.add_argument("--opp-near", type=int, default=0,
                    help="also require the opponent within N pts of the win (a race; 0=off)")
    ap.add_argument("--opponent", choices=["h3", "s"], default="h3")
    ap.add_argument("--s-sims", type=int, default=160, help="S sims/move when --opponent s")
    ap.add_argument("--seed", type=int, default=12345)
    ap.add_argument("--out", default="", help="dir to write puzzle_*.json (else just report)")
    ap.add_argument("--limit", type=int, default=0, help="stop after N puzzles (0 = all)")
    ap.add_argument("--require-exact", action="store_true",
                    help="require NO forced win in fewer than K moves (a true K-mover)")
    ap.add_argument("--strict", action="store_true",
                    help="require EVERY deviation to lose (the only non-losing line is the answer)")
    ap.add_argument("--refill-fair", action="store_true",
                    help="reject puzzles whose solution depends on hidden card reveals (deck-invariant)")
    args = ap.parse_args()

    rng = random.Random(args.seed)
    opp = (solver.s_opponent(sims=args.s_sims) if args.opponent == "s" else solver.h3_opponent())
    opp_name = "S" if args.opponent == "s" else "H3"

    print(f"harvesting from {args.games} games (eps={args.eps}, "
          f"near=[{args.win_points - args.near_hi},{args.win_points - args.near_lo}])...")
    positions = harvest(args.games, args.win_points, args.eps, rng,
                        args.near_lo, args.near_hi, args.max_positions, opp_near=args.opp_near)
    print(f"  {len(positions)} candidate positions")

    flags = (", exact" if args.require_exact else "") + (", strict" if args.strict else "") \
        + (", fair" if args.refill_fair else "")
    print(f"screening vs {opp_name} (K={args.K}{flags})...")
    puzzles = screen(positions, args.K, opp, opp_name, verbose=True,
                     require_exact=args.require_exact, require_strict=args.strict,
                     require_fair=args.refill_fair, out_dir=args.out)
    print(f"  {len(puzzles)} puzzles "
          f"({100*len(puzzles)/max(1,len(positions)):.1f}% of candidates)"
          + (f" — written to {args.out}" if args.out else ""))


if __name__ == "__main__":
    main()
