#!/usr/bin/env bash
# IS ORBIT'S SEARCH SATURATED? Does doubling simulations buy anything at all?
#
# This is the question that decides where the campaign goes next, and it has
# never been asked at serving shape.
#
# Minimax nearly DOUBLES throughput -- 32,760 simulations per decision against
# the ranker's 16,737, because it replaces the external 1-ply opponent call
# (43% of search time) with in-tree node selection -- and it also makes the
# search adversarial for the first time. Two improvements at once. It moved the
# score by about +0.05.
#
# There are two readings and they point opposite ways:
#
#   * If doubling simulations is WORTH something, then minimax's 2x should have
#     shown up, and something about minimax is cancelling its own gain -- most
#     likely that the budget is now split across BOTH players' nodes, so our own
#     decisions are no better informed than before.
#   * If doubling simulations is worth NOTHING -- if Orbit's MCTS saturates well
#     below serving's ~10,900 -- then throughput is a dead axis entirely, the
#     +0.05 is minimax's soundness contribution alone, and the remaining lever
#     is DEPTH rather than width. That is the alpha-beta thesis, confirmed by
#     its own evidence rather than by analogy to other games.
#
# So: the shipped Expert against ITSELF, identical in every respect except that
# one side gets twice the simulations. FIXED simulations, not equal time --
# deterministic, load-independent, and it isolates the axis exactly. It can
# therefore also run four games at once (4 workers x 4 game workers = the
# sixteen-thread cap) without distorting anything, unlike an equal-time arena.
#
# 2,724 per worker across a four-worker pool is 10,896 simulations per decision,
# which is what the heuristic Expert actually achieves at serving shape; the
# opponent's 1,362 is exactly half. So this brackets the real operating point
# rather than probing somewhere cheaper.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/saturation
MINIMAX=games/orbit/ai/runs/minimax-vs-expert
WORKERS=4
HIGH=2724
LOW=1362
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
  and d.get('fixed_simulations')==int(sys.argv[2])
  and d.get('fixed_opponent_simulations')==int(sys.argv[3])) else 1)" \
  "$1" "$HIGH" "$LOW" 2>/dev/null
}

# The minimax extension's eighth pool is the real "the box is yours" signal.
minimax_finished() {
  python -c "import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(1)
sys.exit(0 if (d.get('complete') is True and d.get('arena')) else 1)" \
  "$MINIMAX/pool-8.json" 2>/dev/null
}

# --- WAITING FOR THE BOX -----------------------------------------------------
# A bare "no neural_arena right now" is NOT idle. The extension runs eight pools
# back to back and the gap between two of them -- python start-up plus the
# pooling step -- is ten to fifteen seconds, which a 60-second poll lands inside
# roughly a quarter of the time per gap. Three gaps remain, so a naive check had
# better-than-even odds of firing this probe ON TOP of an equal-time arena, and
# an equal-time arena under contention does not slow down: it silently starves
# each decision of simulations. That is precisely the failure that cost this
# campaign a 70-minute run already.
#
# So the gate is: the extension's LAST pool is on disk, or the box has been
# genuinely quiet for ten consecutive minutes (the fallback if it aborts).
say "=== waiting for the box ==="
waited=0
idle=0
while :; do
  if minimax_finished; then say "minimax pool 8 is on disk; the box is ours"; break; fi
  if arena_running; then idle=0; else idle=$((idle + 1)); fi
  [ "$idle" -ge 10 ] && { say "no arena for ten consecutive minutes; proceeding"; break; }
  sleep 60
  waited=$((waited + 1))
  [ "$waited" -ge 300 ] && { say "ABORT: still busy after five hours"; exit 1; }
done

# One last confirmation after a pause -- a pool that started in the last few
# seconds would not have shown up above.
sleep 45
if arena_running; then
  say "an arena appeared during the settle; falling back to strict idle wait"
  idle=0
  while :; do
    if arena_running; then idle=0; else idle=$((idle + 1)); fi
    [ "$idle" -ge 10 ] && break
    sleep 60
    waited=$((waited + 1))
    [ "$waited" -ge 300 ] && { say "ABORT: still busy after five hours"; exit 1; }
  done
fi
say "box free after ${waited}m"

# Control FIRST. Equal simulations on both sides is the same player twice, so it
# must read ~0.5; if it does not, the asymmetric result means nothing. This is
# the one arena shape that CAN be exactly deterministic, so a skew here would be
# a real defect rather than variance.
say "control: equal simulations on both sides must read ~0.5"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/control.json" \
  --pairs 32 --simulations "$HIGH" --opponent-simulations "$HIGH" \
  --pool development-saturation-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 4 \
  --determinization-period 0 --opponent-determinization-period 0 \
  > /dev/null 2> "$OUT/control.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/control.json'))
s = d['arena']['pair_score']
print(f'  equal simulations read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.12 else 1)
" || { say "ABORT: the control is skewed; the comparison would be meaningless"; exit 1; }

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  say "=== pool $i: ${HIGH} vs ${LOW} per worker ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --simulations "$HIGH" --opponent-simulations "$LOW" \
    --pool "development-saturation-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 4 \
    --determinization-period 0 --opponent-determinization-period 0 \
    > /dev/null 2> "$OUT/pool-$i.err"
  if usable "$report"; then
    python -c "import json,sys;d=json.load(open(sys.argv[1]));a=d['arena'];print('pool',sys.argv[2],'score',round(a['pair_score'],4),a['pair_ci95'],'secs',round(d['seconds']))" "$report" "$i"
  else
    say "pool $i produced no usable report -- see pool-$i.err"
  fi
done

say "=== does twice the search win? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"
python -c "
import json
d = json.load(open(r'$OUT/pooled.json'))
low, high = d['bootstrap_ci95']
print()
if high < 0.55:
    print('SATURATED: doubling the search buys nothing. Throughput is a dead axis,')
    print('and the remaining lever is DEPTH, not width.')
elif low > 0.5:
    print('NOT saturated: more simulations genuinely win, so minimax cancelling its')
    print('own 2x is the thing to explain.')
else:
    print('Not separated at 64 pairs; extend before drawing anything from it.')
"
date > "$OUT/saturation-done.marker"
say "=== saturation probe finished ==="
