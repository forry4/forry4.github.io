#!/usr/bin/env bash
# DOES SEARCHING THE OPPONENT BEAT NOT SEARCHING IT?
#
# Orbit's search has never been adversarial. It builds nodes for the searching
# seat ONLY, and answers every opponent decision with an external call to the
# 1-ply `serving::choose_move` ranker -- optimising a line against a fixed
# environment policy that plays greedily, at a cost of 43% of search time.
#
# Duel had the same defect in a different flavour (select() was MAX-MAX,
# modelling the opponent as cooperating) and its minimax fix was worth 0.62 at
# c=1.0 and 0.67 at c=0.3.
#
# Both arms here are the HAND-WRITTEN leaf with no network anywhere, because
# this is a search-structure question and a neural leaf would only add variance
# and cost. Both are coherent, which is a PREREQUISITE rather than a control:
# under per-simulation determinization every opponent node is fresh, so the
# descent breaks at the first one and the opponent half is never revisited.
# Measured in a unit test as 49 nodes against 49 -- exactly no difference. That
# is also why the league could never have found this: it ran per-simulation.
#
# So the ONLY difference between the arms is `--minimax` on the candidate.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/minimax-vs-expert
NATIVE=games/orbit/ai/runs/target-native/release
BUDGET=3000; MAIN=1800; FOLLOWUP=1200; WORKERS=4
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
  and d.get('budget_ms')==int(sys.argv[2]) and d.get('workers')==int(sys.argv[3])
  and d.get('minimax') is True and d.get('opponent_minimax') is False) else 1)" \
  "$1" "$BUDGET" "$WORKERS" 2>/dev/null
}

say "=== extension: waiting for pools 1-4 to finish ==="
waited=0
while arena_running; do
  sleep 60
  waited=$((waited + 1))
  [ "$waited" -ge 180 ] && { say "ABORT: an arena is still running after three hours"; exit 1; }
done
sleep 30
say "box free after ${waited}m"

say "binary already rebuilt by the first four pools; skipping"
# Harness sanity already passed at exactly 0.5000 on this binary.

# --- The comparison ----------------------------------------------------------
for i in 1 2 3 4 5 6 7 8; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i starting ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-minimax-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --minimax > /dev/null 2> "$OUT/pool-$i.err"
  if usable "$report"; then
    python -c "import json,sys;d=json.load(open(sys.argv[1]));a=d['arena'];print('pool',sys.argv[2],'score',round(a['pair_score'],4),a['pair_ci95'],'secs',round(d['seconds']))" "$report" "$i"
    python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
      --accept-pairs 128 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "running estimate: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "pool $i produced no usable report -- see pool-$i.err"
  fi
done

say "=== pooled result ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 128 --output "$OUT/pooled.json"
date > "$OUT/minimax-done.marker"
say "=== minimax screen finished ==="
