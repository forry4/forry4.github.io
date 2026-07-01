"""Reconstruct each mover's ACTION from the per-ply board diffs in a wwsd game-log export, to build an
imitation dataset of the OPPONENTS' moves (the human racers who beat N). The logger stores both seats'
engine-space board every ply, so diffing consecutive plies recovers the move the mover made:
  - BUY  (purchased grew): unambiguous — which card, from board (buy_board slot) or hand (buy_reserved).
  - RESERVE (reserved grew): unambiguous — board slot (reserve_board) or deck (reserve_deck level).
  - TAKE (tokens changed, no card): from the net token delta; a discard (over-10) can under-count the raw
    take, so those are FLAGGED (the net-effect action is still recorded).
  - PASS (nothing changed).
Emits (state_before, action) pairs split by seat, and reports reconstruction coverage + the opponents'
move/efficiency profile (the clone target) + a data-sufficiency estimate.

Usage: python wwsd/reconstruct_moves.py EXPORT.json [--out moves.jsonl]
"""
from __future__ import annotations
import argparse, json, pathlib, re, ast
from collections import Counter

G = ["white", "blue", "green", "red", "black"]
C3 = [[a, b, c] for a in range(5) for b in range(a+1, 5) for c in range(b+1, 5)]   # 10, lexicographic
C2 = [[a, b] for a in range(5) for b in range(a+1, 5)]                              # 10, lexicographic

def load_pts():
    try:
        rs = (pathlib.Path(__file__).resolve().parent.parent / "spender-core/src/cards.rs").read_text()
        return ast.literal_eval(re.search(r"const PTS:[^=]*=\s*(\[.*?\]);", rs, re.S).group(1))
    except Exception:
        return None
PTS = load_pts()
def level_of(ci): return 1 if ci < 40 else 2 if ci < 70 else 3

def reconstruct(b0, b1, m):
    """Return (action_index|None, kind, desc, flags) for mover m's move from board b0 -> b1."""
    p0, p1 = b0["purchased"][m], b1["purchased"][m]
    r0, r1 = b0["reserved"][m], b1["reserved"][m]
    noble = len(b1["nobles_won"][m]) > len(b0["nobles_won"][m])
    fl = {"noble": noble}
    if len(p1) > len(p0):                                   # BUY
        new = (Counter(p1) - Counter(p0)).most_common(1)[0][0]
        if new in b0["board"]:
            slot = b0["board"].index(new); return 46 + slot, "buy_board", f"buy_board s{slot} {_c(new)}", fl
        if new in r0:
            i = r0.index(new); return 58 + i, "buy_reserved", f"buy_reserved #{i} {_c(new)}", fl
        return None, "buy_?", "buy (source unknown)", {**fl, "ambiguous": True}
    if len(r1) > len(r0):                                   # RESERVE
        new = (Counter(r1) - Counter(r0)).most_common(1)[0][0]
        if new in b0["board"]:
            slot = b0["board"].index(new); return 31 + slot, "reserve_board", f"reserve_board s{slot} {_c(new)}", fl
        lv = level_of(new); return 43 + (lv - 1), "reserve_deck", f"reserve_deck L{lv}", fl
    # TAKE / PASS — net token delta on colours (gold only comes from reserve)
    d = [b1["tokens"][m][c] - b0["tokens"][m][c] for c in range(5)]
    pos = [(c, d[c]) for c in range(5) if d[c] > 0]
    discard = any(x < 0 for x in d) or sum(b0["tokens"][m]) >= 8   # possible over-10 discard this turn
    if not pos:
        if any(d) or b1["tokens"][m][5] != b0["tokens"][m][5]:
            return None, "take_?", "token change unmatched", {**fl, "ambiguous": True}
        return 30, "pass", "pass", fl
    if len(pos) == 1:
        c, v = pos[0]
        if v == 2: return 25 + c, "take2_same", f"take2_same {G[c]}", {**fl, "maybe_discard": discard}
        if v == 1: return 20 + c, "take1", f"take1 {G[c]}", {**fl, "maybe_discard": discard}
        return None, "take_?", f"take +{v}{G[c]}", {**fl, "ambiguous": True}
    if len(pos) == 2 and all(v == 1 for _, v in pos):
        cs = sorted(c for c, _ in pos); return 10 + C2.index(cs), "take2_diff", f"take2 {G[cs[0]]},{G[cs[1]]}", {**fl, "maybe_discard": discard}
    if len(pos) == 3 and all(v == 1 for _, v in pos):
        cs = sorted(c for c, _ in pos); return C3.index(cs), "take3", "take3 " + ",".join(G[c] for c in cs), {**fl, "maybe_discard": discard}
    return None, "take_?", f"take {pos}", {**fl, "ambiguous": True}

def _c(ci): return f"L{level_of(ci)}#{ci}({PTS[ci] if PTS else '?'}p)"

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("export"); ap.add_argument("--out", help="write (state,action) jsonl for imitation")
    a = ap.parse_args()
    D = json.load(open(a.export, encoding="utf-8"))["games"]
    out = open(a.out, "w", encoding="utf-8") if a.out else None
    tot = clean = amb = 0
    kinds = Counter(); opp_kinds = Counter(); opp_buy_pts = []; opp_loss_buy_pts = []
    n_opp = 0
    for g in D:
        fs = g.get("finalScores"); mys = g.get("mySeat")
        if not g.get("plies") or mys not in (0, 1): continue
        wp = g.get("winPoints", 15)
        completed = g.get("completed", bool(fs) and len(fs) >= 2 and max(fs[0]["points"], fs[1]["points"]) >= wp)
        if not completed: continue
        n_lost = g.get("result") == "loss"
        pl = [p for p in g["plies"] if "dump" in p]
        for i in range(len(pl) - 1):
            b0, b1 = pl[i]["dump"], pl[i + 1]["dump"]
            m = pl[i].get("mover")
            if m not in (0, 1): continue
            act, kind, desc, fl = reconstruct(b0, b1, m)
            tot += 1; kinds[kind] += 1
            is_opp = (m != mys)
            if act is None or fl.get("ambiguous"): amb += 1
            else: clean += 1
            if is_opp:
                n_opp += 1; opp_kinds[kind] += 1
                if kind in ("buy_board", "buy_reserved") and PTS:
                    new = (Counter(b1["purchased"][m]) - Counter(b0["purchased"][m])).most_common(1)[0][0]
                    opp_buy_pts.append(PTS[new])
                    if n_lost: opp_loss_buy_pts.append(PTS[new])
            if out and is_opp and act is not None and not fl.get("ambiguous"):
                out.write(json.dumps({"game": g.get("gameId"), "ply": pl[i].get("ply"), "seat": m,
                                      "in_loss": n_lost, "action": act, "kind": kind, "dump": b0}) + "\n")
    if out: out.close()
    print(f"moves reconstructed: {tot} | clean {clean} ({100*clean/max(1,tot):.1f}%) | ambiguous {amb} ({100*amb/max(1,tot):.1f}%)")
    print("all-mover kinds:", dict(kinds.most_common()))
    print(f"\nOPPONENT (clone-target) moves: {n_opp}")
    print("  opp kinds:", dict(opp_kinds.most_common()))
    if opp_buy_pts:
        import statistics as st
        buys = len(opp_buy_pts); zero = sum(1 for p in opp_buy_pts if p == 0)
        print(f"  opp buys: {buys} | avg pts/card {st.mean(opp_buy_pts):.2f} | 0-pt cards {100*zero/buys:.0f}% | point-cards (>=1pt) {100*(buys-zero)/buys:.0f}%")
        if opp_loss_buy_pts:
            b2 = len(opp_loss_buy_pts); z2 = sum(1 for p in opp_loss_buy_pts if p == 0)
            print(f"  opp buys IN N's LOSSES (the strong racers): {b2} | avg pts/card {st.mean(opp_loss_buy_pts):.2f} | point-cards {100*(b2-z2)/b2:.0f}%")
    clean_opp = sum(v for k, v in opp_kinds.items() if not k.endswith("_?"))
    print(f"\nimitation-ready opponent moves (clean): ~{clean_opp}")
    print(f"  behavioral cloning wants ~10-30k for a decent policy -> at ~{clean_opp/max(1,len(D)):.0f} clean opp moves/game, need ~{int(15000/max(1,clean_opp/max(1,len(D))))}-{int(30000/max(1,clean_opp/max(1,len(D))))} games total")
    if a.out: print(f"\nwrote imitation (state,action) pairs -> {a.out}")

if __name__ == "__main__":
    main()
