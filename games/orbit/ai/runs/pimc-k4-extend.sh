#!/usr/bin/env bash
# HOW MANY WORLDS SHOULD ALPHA-BETA VOTE OVER?
#
# The de-risk (2026-09-13) measured alpha-beta against the MCTS Expert at
# serving budget, one thread per seat, 64 CRN pairs each:
#
#   perfect information   0.9609  [0.9219, 0.9922]
#   determinized, K=1     0.5625  [0.4688, 0.6484]
#
# The architecture is overwhelmingly better and BELIEFS EAT ALMOST ALL OF IT.
# That gap is strategy fusion: a minimax over one sampled world plays as though
# it knows the opponent's hand, so it commits to lines that only work in that
# world. An MCTS over one world is softer -- its values are means over many
# simulations -- which is why the same trade costs it far less.
#
# PIMC is the standard answer and it is what Dissonance already serves for this
# class of game: sample K worlds, search each, vote. It is a REAL TRADE rather
# than a free win, because each world gets budget/K and depth falls as K rises.
# K=1 at serving budget reached mean depth 8.2; K=8 will be far shallower. The
# ladder is the experiment.
#
# K=1 IS NOT RE-RUN. The de-risk measured it at 64 pairs in exactly this
# configuration -- same budget, same one-thread shape, same pool namespaces --
# so re-running it would spend 45 minutes to re-measure a known number. It is
# read from disk and printed in the ladder.
#
# A NOTE ON READING THE WINNER. Three values of K are tried and the best will be
# picked out; that is three chances to clear 0.5 by luck, and the campaign's
# measured pool spread on an IDENTICAL comparison was 0.34 wide. Whichever K
# wins here needs CONFIRMING at a larger sample before it means anything. The
# ladder's job is to find the shape of the curve, not to certify a ship.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/pimc-ladder
DERISK=games/orbit/ai/runs/alphabeta-derisk
BUDGET=3000; MAIN=1800; FOLLOWUP=1200
export PATH="$HOME/.cargo/bin:$PATH"
mkdir -p "$OUT"

say() { echo "[$(date '+%H:%M:%S')] $*"; }

arena_running() {
  powershell.exe -NoProfile -Command \
    "if (Get-Process -Name neural_arena -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }" \
    2>/dev/null | tr -d '\r' | grep -q yes
}

usable() {
  python -c "import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(1)
sys.exit(0 if (d.get('complete') is True and d.get('arena')
  and d.get('budget_ms')==int(sys.argv[2])
  and d.get('alphabeta') is True and d.get('opponent_alphabeta') is False
  and d.get('via_observation') is True
  and d.get('ab_worlds')==int(sys.argv[3])) else 1)" \
  "$1" "$BUDGET" "$2" 2>/dev/null
}

say "=== waiting for the box ==="
waited=0
idle=0
while :; do
  if arena_running; then idle=0; else idle=$((idle + 1)); fi
  [ "$idle" -ge 5 ] && break
  sleep 60
  waited=$((waited + 1))
  [ "$waited" -ge 300 ] && { say "ABORT: still busy after five hours"; exit 1; }
done
say "box free after ${waited}m"

say "rebuilding every binary (a Controls field added mid-session broke value_generate once)"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

for k in 4; do
  dir="$OUT/k$k"
  mkdir -p "$dir"
  say "=== K=$k: ${BUDGET}ms split across $k worlds ==="
  for i in 5 6 7 8; do
    report="$dir/pool-$i.json"
    if usable "$report" "$k"; then say "  pool $i already complete"; continue; fi
    [ -e "$report" ] && say "  pool $i: discarding an unusable report and re-running"
    # The SAME pool namespaces as the de-risk, so every K plays identical deals
    # and the rung-to-rung comparison is paired -- deal variance drops out of
    # it, which matters because 64 pairs resolves only about +/-0.12 unpaired.
    python -m games.orbit.tools.native_search_arena heuristic "$report" \
      --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
      --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
      --workers 1 --game-workers 4 \
      --determinization-period 0 --opponent-determinization-period 0 \
      --alphabeta --ab-worlds "$k" > /dev/null 2> "$dir/pool-$i.err"
    if usable "$report" "$k"; then
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
      say "  pool $i produced no usable report -- see $dir/pool-$i.err"
    fi
  done
  python -m games.orbit.tools.pool_arena_reports "$dir"/pool-[0-9].json \
    --accept-pairs 128 --output "$dir/pooled.json" > /dev/null 2>&1
  say "  K=$k => $(python -c "import json;d=json.load(open(r'$dir/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
done

say "=== K=4 at 128 pairs ==="
python -m games.orbit.tools.pool_arena_reports "$OUT/k4"/pool-[0-9].json   --accept-pairs 128 --output "$OUT/k4/pooled-128.json"
date > "$OUT/k4-extend-done.marker"
say "=== K=4 extension finished ==="
