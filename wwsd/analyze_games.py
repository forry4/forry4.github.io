"""Analyse a wwsd game-log export (⤓ Logs button -> wwsd_games_*.json) and, optionally, extract a
racer BENCHMARK for improving variant N.

The browser logger records, per game: every ply's engine-space board (both seats), the bot's search
output on its turns (value + full visit distribution), and the final outcome. This tool:

  1. Filters to legitimate 2-player COMPLETED games (drops forfeits/timeouts via the `completed` flag:
     a real Splendor game ends only when the winner reaches win_points).
  2. Reports the record, loss/close-win breakdown, behavioural aggregates (pts/card efficiency, nobles,
     reserve conversion), a MISEVALUATION scan (bot->bot value drops with board-change attribution), and
     the value-head calibration / overconfidence-loss dissection.
  3. With --benchmark OUT.json, emits the hard-position set: every bot-turn position from the LOSSES and
     CLOSE games, tagged with the bot's recorded value and the eventual outcome label — the honest
     racer benchmark + value-debias data self-play can't generate. Each position carries the engine-space
     board so any net can be re-scored on it (via an engine.from_game_dict adapter in the az stack).

Usage:
  python wwsd/analyze_games.py wwsd_games_161_2026-07-01.json
  python wwsd/analyze_games.py EXPORT.json --benchmark racer_benchmark.json --close 2
"""
from __future__ import annotations
import argparse, json, pathlib, statistics as st
from collections import Counter

# ── optional engine card tables (only for human-readable card descriptions; analysis works without) ──
def load_cards():
    try:
        import re, ast
        rs = (pathlib.Path(__file__).resolve().parent.parent / "spender-core/src/cards.rs").read_text()
        arr = lambda n: ast.literal_eval(re.search(n + r"[^=]*=\s*(\[.*?\]);", rs, re.S).group(1))
        return dict(COST=arr(r"const COST:"), BONUS=arr(r"const BONUS:"), PTS=arr(r"const PTS:"))
    except Exception:
        return None

def keep(g):
    """A legitimate 2-player scored game; sets _wp/_completed. Robust to old-version records."""
    fs = g.get("finalScores")
    if not fs or len(fs) < 2 or g.get("mySeat") not in (0, 1):
        return False
    wp = g.get("winPoints", 15)
    top = max(fs[0]["points"], fs[1]["points"])
    g["_wp"] = wp
    g["_completed"] = g.get("completed", top >= wp)   # derive for pre-0.9.24 records
    return True

def bot_plies(g):
    m = g["mySeat"]
    return [p for p in g["plies"] if p.get("mover") == m and "search" in p]

def outcome(g):
    m = g["mySeat"]; fs = g["finalScores"]
    return fs[m]["points"], fs[1 - m]["points"], fs[m]["points"] - fs[1 - m]["points"]

def eff(g, seat):
    c = g["finalScores"][seat]["cards"]
    return g["finalScores"][seat]["points"] / c if c else 0.0

def board_ms(dump):
    return Counter(c for c in dump["board"] if c >= 0)

def reserves_made(g):
    return sum(1 for p in bot_plies(g) if "Reserve" in (p["search"].get("rec") or ""))

def unused_reserves(g):
    return len(g["plies"][-1]["dump"]["reserved"][g["mySeat"]])

def report(games):
    comp = [g for g in games if g["_completed"]]
    inc = [g for g in games if not g["_completed"]]
    ic = Counter(g["result"] for g in inc)
    print(f"TOTAL scored 2p games: {len(games)}   COMPLETED(legit): {len(comp)}   "
          f"forfeit/abandon dropped: {len(inc)} (opp-forfeit wins {ic.get('win',0)}, bot-forfeit losses {ic.get('loss',0)}, ties {ic.get('tie',0)})")

    W = [g for g in comp if g["result"] == "win"]
    L = [g for g in comp if g["result"] == "loss"]
    T = [g for g in comp if g["result"] == "tie"]
    print(f"\nRECORD: {len(W)}W-{len(L)}L-{len(T)}T  winrate {len(W)/max(1,len(comp)):.3f}")
    margins = [outcome(g)[2] for g in comp]
    print(f"margin(bot-opp): mean {st.mean(margins):+.2f} median {st.median(margins):+.0f} range [{min(margins)},{max(margins)}]")

    def agg(grp, name):
        if not grp:
            print(f"  {name}: (none)"); return
        print(f"  {name} (n={len(grp)}): pts/card bot {st.mean([eff(g,g['mySeat']) for g in grp]):.2f} "
              f"opp {st.mean([eff(g,1-g['mySeat']) for g in grp]):.2f} | cards {st.mean([g['finalScores'][g['mySeat']]['cards'] for g in grp]):.1f} | "
              f"nobles bot {st.mean([len(g['finalScores'][g['mySeat']]['nobles']) for g in grp]):.2f} opp {st.mean([len(g['finalScores'][1-g['mySeat']]['nobles']) for g in grp]):.2f} | "
              f"reserves made {st.mean([reserves_made(g) for g in grp]):.1f} unused@end {st.mean([unused_reserves(g) for g in grp]):.2f}")
    print("\nBEHAVIOURAL AGGREGATES:")
    agg(W, "WINS"); agg(L, "LOSSES")

    # reserve conversion
    def conv(grp):
        made = sum(reserves_made(g) for g in grp); un = sum(unused_reserves(g) for g in grp)
        return made, made - un
    for nm, grp in [("WINS", W), ("LOSSES", L)]:
        m, b = conv(grp)
        print(f"  {nm}: reserves made {m} converted {b} ({100*b/max(1,m):.0f}%) stranded {m-b}")

    # misevaluation scan
    steps = pure = bigdrop = bigpure = 0
    for g in comp:
        bp = bot_plies(g)
        for i in range(len(bp) - 1):
            d = bp[i+1]["search"]["value"] - bp[i]["search"]["value"]
            unchanged = board_ms(bp[i]["dump"]) == board_ms(bp[i+1]["dump"])
            steps += 1
            if d <= -0.30: bigdrop += 1
            if unchanged and d <= -0.20: pure += 1
            if unchanged and d <= -0.30: bigpure += 1
    print(f"\nMISEVAL SCAN: {steps} bot->bot value steps | drops<=-0.30: {bigdrop} "
          f"(pure, board UNCHANGED: {bigpure}) | pure drops<=-0.20: {pure}")

    # overconfidence + calibration
    over = [g for g in L if (lambda h: h and max(p["search"]["value"] for p in h) >= 0.40)(bot_plies(g)[len(bot_plies(g))//2:])]
    print(f"OVERCONFIDENCE: {len(over)}/{len(L)} losses rated bot value >= +0.40 in the 2nd half then LOST")
    pw = pt = nl = nt = 0
    for g in comp:
        r = 1 if g["result"] == "win" else (-1 if g["result"] == "loss" else 0)
        for p in bot_plies(g):
            v = p["search"]["value"]
            if v > 0.15: pt += 1; pw += (r > 0)
            elif v < -0.15: nt += 1; nl += (r < 0)
    print(f"CALIBRATION: value>+0.15 -> won {pw}/{pt} ({pw/max(1,pt):.2f}); value<-0.15 -> lost {nl}/{nt} ({nl/max(1,nt):.2f})")
    return comp, W, L, T

def build_benchmark(comp, close_margin):
    """Positions from LOSSES + CLOSE games -> value-debias / racer benchmark."""
    L = [g for g in comp if g["result"] == "loss"]
    closeG = [g for g in comp if g["result"] != "loss" and abs(outcome(g)[2]) <= close_margin]
    sel = L + closeG
    out_games = []
    n_pos = n_hard = 0
    for g in sel:
        label = 1 if g["result"] == "win" else (-1 if g["result"] == "loss" else 0)
        positions = []
        for p in bot_plies(g):
            v = p["search"]["value"]
            # hard = the value head is confidently WRONG about the eventual outcome
            hard = (label < 0 and v >= 0.35) or (label > 0 and v <= -0.35)
            positions.append(dict(ply=p["ply"], value=v, rec=p["search"].get("rec"),
                                  rec_pct=p["search"].get("rec_pct"), sims=p["search"].get("sims"),
                                  label=label, hard=hard, dump=p["dump"]))
            n_pos += 1; n_hard += hard
        out_games.append(dict(gameId=g["gameId"], opp=g["names"][1 - g["mySeat"]], mySeat=g["mySeat"],
                              winPoints=g["_wp"], result=g["result"], margin=outcome(g)[2],
                              finalScores=g["finalScores"], n_positions=len(positions), positions=positions))
    return dict(schema="wwsd-racer-benchmark/1",
                note="Bot-turn positions from real human LOSSES + CLOSE games. dump = wwsd engine-space State "
                     "(remapped card ids; feed via engine.from_game_dict adapter). value=bot's recorded search "
                     "value; label=eventual outcome from bot POV (+1/-1/0); hard=value head confidently wrong.",
                n_games=len(out_games), n_positions=n_pos, n_hard=n_hard, games=out_games)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export")
    ap.add_argument("--benchmark", metavar="OUT.json", help="also write the racer benchmark set")
    ap.add_argument("--close", type=int, default=2, help="close-game margin threshold (default 2)")
    a = ap.parse_args()
    D = json.load(open(a.export, encoding="utf-8"))["games"]
    games = [g for g in D if keep(g)]
    comp, W, L, T = report(games)
    if a.benchmark:
        bm = build_benchmark(comp, a.close)
        json.dump(bm, open(a.benchmark, "w"), separators=(",", ":"))
        sz = pathlib.Path(a.benchmark).stat().st_size
        print(f"\nBENCHMARK -> {a.benchmark}: {bm['n_games']} games, {bm['n_positions']} bot-turn positions "
              f"({bm['n_hard']} 'hard' = value head confidently wrong), {sz/1e6:.1f} MB")

if __name__ == "__main__":
    main()
