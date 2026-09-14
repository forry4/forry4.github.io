#!/usr/bin/env bash
# DOES THE VICTORY-AWARE LEAF BEAT THE ONE WE JUST SHIPPED?
#
# From a PLAYTEST, not an arena: the bot ignored an opponent two steps up a
# planet that was their fastest path to victory. Reproduced at the leaf and it
# is two separate defects, both structural rather than a matter of weights:
#
# 1. THE INFLUENCE TERM IS VICTORY-BLIND. Advancing a disc to the brink scores
#    an identical -0.4178 whether that capture ENDS THE GAME or is worthless.
#    Orbit has three victory conditions -- three of one planet, four different,
#    five in all -- so the same disc can be decisive or nearly meaningless, and
#    the leaf never looked.
# 2. `tanh` DESTROYS DISCRIMINATION WHERE THE GAME IS DECIDED. Its derivative at
#    |x|=1.45 is 0.20, so in a lopsided position -- precisely where threats
#    matter -- the same threat moved the leaf 0.12 against 0.40 in a quiet one.
#
# Together they had the sign backwards: the game-LOSING threat was priced at
# 0.31x the harmless one. v2 prices it at 3.92x.
#
# WHY THIS IS NOT "EVAL TUNING", which this campaign has twice found saturated:
# no weight was retuned. A missing FEATURE INTERACTION was added (proximity x
# what the capture is worth) and a squash that was discarding the signal was
# rescaled. The saturated verdict was about replacing `state_value` with a
# learned evaluator and about re-weighting its existing terms; neither covers a
# term that was never there.
#
# AND IT MIGHT STILL LOSE. v2 values EARLY influence pushing far less --
# -0.0369 against -0.3951 for a disc halfway up a planet with nothing banked --
# because the discount is now quadratic in distance. That is a large behavioural
# change in the opposite direction to the fix, and board presence early may be
# worth more than the model says. Hence an arena rather than a conviction.
#
# BOTH ARMS ARE ALPHA-BETA PIMC K=4 AT SERVING SHAPE, so the ONLY difference is
# the leaf. The opponent is exactly what now ships.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/leaf-v2
BUDGET=3000; MAIN=1800; FOLLOWUP=1200; WORKERS=4; K=4
export PATH="$HOME/.cargo/bin:$PATH"
mkdir -p "$OUT"

say() { echo "[$(date '+%H:%M:%S')] $*"; }

usable() {
  python -c "import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(1)
sys.exit(0 if (d.get('complete') is True and d.get('arena')
  and d.get('budget_ms')==int(sys.argv[2])
  and d.get('workers')==int(sys.argv[3])
  and d.get('alphabeta') is True and d.get('opponent_alphabeta') is True
  and d.get('ab_worlds')==int(sys.argv[4])
  and d.get('leaf')=='state-value-v2'
  and d.get('opponent_leaf')=='state-value') else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$K" 2>/dev/null
}

claim_box "leaf-v2" 600 || { say "ABORT: could not claim the box"; exit 1; }

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# CONTROL: both arms the SHIPPED leaf, both alpha-beta. Identical players, so it
# must read ~0.5. This is the check that catches a `--leaf` flag that never
# reaches the alpha-beta seat -- which it did not until today, and would have
# made this whole comparison read 0.5 while looking like a real null.
say "--- control: both arms the shipped leaf must read ~0.5 ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/control.json" \
  --pairs 16 --budget-ms 600 --main-action-ms 360 --followup-ms 240 \
  --pool development-leaf-v2-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" \
  > /dev/null 2> "$OUT/control.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/control.json'))
s = d['arena']['pair_score']
print(f'  identical players read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.15 else 1)
" || { say "ABORT: the control is skewed; the comparison would be meaningless"; exit 1; }

# A SECOND CONTROL, and this one is the important one: the v2 flag must actually
# CHANGE the player. A leaf wired only into the MCTS while both arms run
# alpha-beta would read a clean 0.5 and be indistinguishable from "the new leaf
# is exactly as good". Same deals, same everything, v2 on one side: if this also
# reads 0.5000 exactly, the flag is not reaching the search.
say "--- wiring check: v2 must not read EXACTLY the control ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/wiring.json" \
  --pairs 16 --budget-ms 600 --main-action-ms 360 --followup-ms 240 \
  --pool development-leaf-v2-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" --leaf state-value-v2 \
  > /dev/null 2> "$OUT/wiring.err"
python -c "
import json, sys
a = json.load(open(r'$OUT/control.json'))['arena']['pair_score']
b = json.load(open(r'$OUT/wiring.json'))['arena']['pair_score']
print(f'  shipped-vs-shipped {a:.4f}, v2-vs-shipped {b:.4f} on the SAME deals')
if abs(a - b) < 1e-9:
    print('  THE FLAG IS NOT REACHING THE SEARCH -- identical to the last decimal')
    sys.exit(1)
" || { say "ABORT: --leaf does not reach the alpha-beta seat"; exit 1; }

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i: v2 leaf vs the shipped leaf, both alpha-beta K=$K ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --alphabeta --opponent-alphabeta --ab-worlds "$K" --leaf state-value-v2 \
    > /dev/null 2> "$OUT/pool-$i.err"
  if usable "$report"; then
    python -c "
import json, sys
d = json.load(open(sys.argv[1]))
a = d['arena']
games = d['games']
depth = sum(sum(g.get('ab_depth_by_seat', [0, 0])) for g in games)
searches = sum(sum(g.get('ab_searches_by_seat', [0, 0])) for g in games)
print('  pool', sys.argv[2], 'score', round(a['pair_score'], 4), a['pair_ci95'],
      '| mean depth', round(depth / searches, 2) if searches else 0,
      '| secs', round(d['seconds']))
" "$report" "$i"
    python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
      --accept-pairs 64 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "  running: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "  pool $i produced no usable report -- see $OUT/pool-$i.err"
  fi
done

say "=== does the victory-aware leaf beat the shipped one? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"
python -c "
import json, pathlib
d = json.loads(pathlib.Path(r'$OUT/pooled.json').read_text())
low, high = d['bootstrap_ci95']
print()
print(f\"v2 leaf vs the shipped leaf, both alpha-beta PIMC K=$K at serving shape:\")
print(f\"  {d['pair_score']:.4f}  [{low:.4f}, {high:.4f}]  over {d['pairs']} pairs\")
print()
if low > 0.5:
    print('THE LEAF FIX WINS. Extend to 128 pairs, then it is a wasm rebuild and')
    print('a Python port for the parity gate before it ships.')
elif high < 0.5:
    print('THE LEAF FIX LOSES. The threat pricing is right in isolation, so what')
    print('costs more is the other half: v2 discounts EARLY influence quadratically')
    print('and board presence is evidently worth more than that. Keep the squash,')
    print('retry the victory term with a gentler distance discount.')
else:
    print('Not separated at 64 pairs. The campaign pool spread on an IDENTICAL')
    print('comparison is 0.34 wide, so extend before concluding either way.')
"  2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/leaf-v2-done.marker"
say "=== finished ==="
