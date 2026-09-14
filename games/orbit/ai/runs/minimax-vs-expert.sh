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

say "=== waiting for the box (up to 3h) ==="
waited=0
while arena_running; do
  sleep 60
  waited=$((waited + 1))
  [ "$waited" -ge 180 ] && { say "ABORT: an arena is still running after three hours"; exit 1; }
done
sleep 30
say "box free after ${waited}m"

say "rebuilding (the running binary predates the minimax knob)"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bin neural_arena --bin value_generate --bin bridge --bin policy_diff \
  > "$OUT/rebuild.log" 2>&1
[ $? -ne 0 ] && { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# --- Harness sanity: the two arms with minimax OFF are the SAME PLAYER --------
# `heuristic` is the no-network leaf and `--opponent-expert` is that same search,
# so with identical controls this must read ~0.5. If it does not, the harness is
# biased and nothing measured with it means anything. Fixed simulations so the
# result is deterministic rather than a time-slice lottery.
say "harness sanity: identical players must read ~0.5"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/sanity.json" \
  --pairs 16 --simulations 64 --pool development-minimax-sanity \
  --opponent-expert --via-observation --workers 2 --game-workers 2 \
  --determinization-period 0 --opponent-determinization-period 0 \
  > /dev/null 2> "$OUT/sanity.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/sanity.json'))
score = d['arena']['pair_score']
print(f'  identical players read {score:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
if abs(score - 0.5) > 0.15:
    print('  HARNESS IS BIASED -- not running the comparison')
    sys.exit(1)
" || { say "ABORT: harness sanity failed"; exit 1; }

# --- The comparison ----------------------------------------------------------
for i in 1 2 3 4; do
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
      --accept-pairs 64 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "running estimate: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "pool $i produced no usable report -- see pool-$i.err"
  fi
done

say "=== pooled result ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"
date > "$OUT/minimax-done.marker"
say "=== minimax screen finished ==="
