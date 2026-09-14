#!/usr/bin/env bash
# TWO SEARCH FIXES ON TOP OF THE LEAF FIX, MEASURED TOGETHER THEN APART.
#
# THE HORIZON BUG, which is the one worth the box time. An Orbit turn is not one
# ply: effects queue sub-decisions, and **39.6% of all decision points sit
# inside a pending chain** (6,598 decisions over 40 games). So two times in five
# a search that stops at its depth limit is scoring a HALF-FINISHED TURN -- an
# effect granted but its cost unpaid, a capture queued but not applied. The
# evaluator was never meant to read those, and more depth does not fix it,
# because the horizon simply lands in a different half-finished turn. The
# standard answer is not to stop in the middle of one.
#
# THE THROUGHPUT FIX. Every node built a JSON observation and read ~30
# string-keyed fields back out of it; in a depth-first search most nodes are
# leaves, so that round trip was a large share of total cost. The leaf now reads
# `State` directly. It is held to the observation leaf to 1e-9 over 400+ real
# positions, so it CANNOT change a move -- only how many nodes fit in the
# budget. That matters because node rate is depth and depth is score: the
# serving ladder put K=4 at depth 7.69 on 0.6172 against K=8 at depth 7.00 on
# 0.5625.
#
# WHY TOGETHER FIRST. Box time is the binding constraint -- each arm is about
# three hours -- and these two are independent in mechanism but both act through
# the same channel (what the search sees at its horizon). The campaign's own
# lesson argues for decomposing: minimax delivered two changes at once and its
# +0.04 could not be attributed. So this runs the PAIR first, and decomposes
# ONLY if the pair is worth attributing. A pair that washes needs no decomposition.
#
# THE BASELINE IS v2-ALONE, not the shipped Expert, so this isolates the SEARCH
# changes from the leaf change measured separately. Both arms therefore carry
# the v2 leaf.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/search-fixes
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
  and d.get('leaf')=='state-value-v2' and d.get('opponent_leaf')=='state-value-v2'
  and d.get('ab_quiescence') is True) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$K" 2>/dev/null
}

claim_box "search-fixes" 600 || { say "ABORT: could not claim the box"; exit 1; }

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# THE NON-VACUITY CHECK, which matters more here than a mirror control. The
# quiescence flag is per-seat and reaches the search through three layers; if it
# silently failed to arrive, both arms would be identical players and the run
# would report an honest-looking 0.5. So: one short arena, and the candidate
# must report a nonzero extension count.
say "--- does quiescence actually fire? ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/fires.json" \
  --pairs 8 --budget-ms 600 --main-action-ms 360 --followup-ms 240 \
  --pool development-search-fixes-fires --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" \
  --leaf state-value-v2 --opponent-leaf state-value-v2 --ab-quiescence \
  > /dev/null 2> "$OUT/fires.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/fires.json'))
if not d.get('ab_quiescence'):
    print('  the report does not even record the flag'); sys.exit(1)
print(f\"  recorded in the report: ab_quiescence={d['ab_quiescence']}, \"
      f\"leaf={d['leaf']}, opponent_leaf={d['opponent_leaf']}\")
print(f\"  score on the short arena: {d['arena']['pair_score']:.4f}\")
" || { say "ABORT: the quiescence flag is not reaching the arena"; exit 1; }

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i: quiescence + fast leaf vs v2 alone, both alpha-beta K=$K ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --alphabeta --opponent-alphabeta --ab-worlds "$K" \
    --leaf state-value-v2 --opponent-leaf state-value-v2 --ab-quiescence \
    > /dev/null 2> "$OUT/pool-$i.err"
  if usable "$report"; then
    python -c "
import json, sys
d = json.load(open(sys.argv[1]))
a = d['arena']
games = d['games']
depth = sum(sum(g.get('ab_depth_by_seat', [0, 0])) for g in games)
searches = sum(sum(g.get('ab_searches_by_seat', [0, 0])) for g in games)
nodes = sum(sum(g.get('ab_nodes_by_seat', [0, 0])) for g in games)
print('  pool', sys.argv[2], 'score', round(a['pair_score'], 4), a['pair_ci95'],
      '| mean depth', round(depth / searches, 2) if searches else 0,
      '| nodes/search', round(nodes / searches) if searches else 0,
      '| secs', round(d['seconds']))
" "$report" "$i"
    python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
      --accept-pairs 64 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "  running: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "  pool $i produced no usable report -- see $OUT/pool-$i.err"
  fi
done

say "=== are the search fixes worth anything on top of the leaf fix? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"
python -c "
import json, pathlib
d = json.loads(pathlib.Path(r'$OUT/pooled.json').read_text())
low, high = d['bootstrap_ci95']
print()
print('quiescence + the JSON-free leaf, against the same search WITHOUT them')
print('(both arms carry the v2 leaf, both alpha-beta PIMC K=$K at serving shape):')
print(f\"  {d['pair_score']:.4f}  [{low:.4f}, {high:.4f}]  over {d['pairs']} pairs\")
print()
if low > 0.5:
    print('WORTH IT. Now DECOMPOSE before shipping: the throughput fix cannot')
    print('change a move (it is value-identical to 1e-9), so anything here that')
    print('is not depth is the horizon fix -- run quiescence alone to attribute')
    print('it, exactly as minimax should have been.')
elif high < 0.5:
    print('WORSE. The likelier culprit is quiescence rather than the speedup,')
    print('which cannot change a move: extending only on pending chains biases')
    print('the search toward lines that HAPPEN to end mid-turn, and an uneven')
    print('horizon can be worse than a uniformly wrong one.')
else:
    print('Not separated at 64 pairs, so there is nothing here worth')
    print('decomposing yet. Extend before drawing anything from it.')
"  2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/search-fixes-done.marker"
say "=== finished ==="
