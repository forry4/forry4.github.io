#!/usr/bin/env bash
# HOW MUCH STRONGER IS THE BOT THAN IT WAS, MEASURED RATHER THAN INFERRED?
#
# The campaign's two real gains were measured against DIFFERENT opponents, which
# is correct practice -- each was judged against the best thing available at the
# time -- but it makes the compound easy to misread:
#
#   coherent determinization   0.6094  vs the PER-SIMULATION search (historical)
#   PIMC alpha-beta K=4        0.6172  vs the COHERENT search (the new baseline)
#
# So they are sequential, not a repeat: the opponent got stronger in between.
# Converting to Elo, where gains add and pair scores do not, gives ~77 + ~83 =
# ~160 Elo, which predicts about 0.72 for PIMC alpha-beta against the original
# search.
#
# THAT PREDICTION ASSUMES TRANSITIVITY, and this campaign has been burned by
# exactly that class of assumption before -- a relative metric improving while
# the absolute anchor stayed flat is what sent three hours into a phantom
# "budget curves cross" mechanism. Transitivity is especially suspect here
# because the three players differ in KIND: two MCTS variants that differ only
# in when they resample, against a depth-first searcher. Nothing guarantees
# their strengths line up on one axis.
#
# It is one arena run to measure instead of infer, so measure.
#
# The deals are the SAME pool namespaces as every other determinized arm, so
# this is paired with them and deal variance drops out of the comparison.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/pimc-vs-historical
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
  and d.get('alphabeta') is True
  and d.get('ab_worlds')==int(sys.argv[4])
  and d.get('opponent_determinization_period')==1) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$K" 2>/dev/null
}

claim_box "pimc-vs-historical" 600 || { say "ABORT: could not claim the box"; exit 1; }

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# CONTROL: the historical per-simulation search against itself. Fixed
# simulations, so it is deterministic and load-independent and must read exactly
# 0.5. The per-simulation opponent path has not carried a control since the
# coherence work replaced it, and an un-controlled baseline is how a compound
# number goes wrong quietly.
say "--- control: identical PER-SIMULATION players must read ~0.5 ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/control.json" \
  --pairs 16 --simulations 256 --pool development-historical-control \
  --opponent-expert --via-observation --workers "$WORKERS" --game-workers 1 \
  --determinization-period 1 --opponent-determinization-period 1 \
  > /dev/null 2> "$OUT/control.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/control.json'))
s = d['arena']['pair_score']
print(f'  identical players read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.12 else 1)
" || { say "ABORT: the per-simulation control is skewed"; exit 1; }

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i: PIMC alpha-beta K=$K vs the HISTORICAL per-simulation search ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 1 \
    --alphabeta --ab-worlds "$K" > /dev/null 2> "$OUT/pool-$i.err"
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
  else
    say "  pool $i produced no usable report -- see $OUT/pool-$i.err"
  fi
done

say "=== how much stronger is the bot than it was? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"
python -c "
import json, math, pathlib

def elo(p):
    p = min(max(p, 1e-6), 1 - 1e-6)
    return 400.0 * math.log10(p / (1 - p))

d = json.loads(pathlib.Path(r'$OUT/pooled.json').read_text())
measured = d['pair_score']
low, high = d['bootstrap_ci95']

print()
print('PIMC alpha-beta K=$K vs the ORIGINAL per-simulation search,')
print('serving shape, equal time, 3000ms turn, four workers per seat:')
print()
print(f'  measured   {measured:.4f}  [{low:.4f}, {high:.4f}]  over {d[\"pairs\"]} pairs')
print(f'  predicted  ~0.72   (adding 0.6094 and 0.6172 as Elo, assuming transitivity)')
print()
print(f'  measured Elo advantage over the original search: {elo(measured):+.0f}')
print()
if low > 0.5:
    print('The two gains DO compound: the bot is measurably stronger than the')
    print('search this campaign started with, by an amount the sequential')
    print('measurements implied.')
    if abs(measured - 0.72) > 0.08:
        direction = 'LESS' if measured < 0.72 else 'MORE'
        print()
        print(f'But it compounds {direction} than Elo addition predicted, so')
        print('transitivity does NOT hold cleanly across these three players --')
        print('worth remembering before adding any future pair of gains.')
else:
    print('The gains do NOT compound as the sequential measurements implied.')
    print('Each was real against its own opponent, but strength here is not one')
    print('axis: two MCTS variants and a depth-first searcher do not order')
    print('transitively. Report the pairwise numbers, never the sum.')
" 2>&1 | tee "$OUT/compound.txt"
date > "$OUT/historical-done.marker"
say "=== finished ==="
