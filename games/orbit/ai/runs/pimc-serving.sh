#!/usr/bin/env bash
# DOES PIMC ALPHA-BETA BEAT THE EXPERT AT THE SHAPE THAT ACTUALLY SHIPS?
#
# Everything measured so far gave each seat ONE thread, which is not what a
# player gets. `ORBIT_AI_WORKER_CAP` is 4 (Orbit.jsx:29), so the browser hands
# every client with five or more threads a FOUR-worker root-summed ensemble, and
# the shipped Expert's own 0.6094 was measured in that shape.
#
# THE REASON THIS IS THE RIGHT NEXT RUN, and it reverses a caution recorded
# earlier in this session. A single alpha-beta tree parallelises badly, which
# was logged as a real cost against the architecture. PIMC does not have that
# problem: the K worlds are INDEPENDENT searches, exactly the shape of the
# root-summed MCTS ensemble. So four workers let four worlds take the WHOLE turn
# budget each instead of a quarter each.
#
# That matters because the serial ladder showed the trade precisely -- score
# rising with K while depth fell with it:
#
#   K    score                 depth
#   1   0.5625 [0.4688,0.6484]  8.18   not separated
#   2   0.6250 [0.5312,0.7109]  7.27   ahead
#   4   0.6562 [0.5703,0.7422]  6.51   ahead
#   8   0.6562 [0.5703,0.7422]  5.79   ahead
#
# Four lanes should buy the top of that curve without paying the depth: K=4 at
# roughly K=1's depth. If the curve's rise was about WORLDS, this reads above
# 0.6562; if it was really about something else, it will not, and that is worth
# knowing before any of it is believed.
#
# BOTH SEATS GET FOUR WORKERS. The alpha-beta seat spends them as PIMC lanes,
# the MCTS seat as its usual root ensemble. `--game-workers 1` keeps the total
# at four threads, because an equal-time arena does not slow under contention --
# it silently starves each decision of simulations, and that has already cost
# this campaign one 70-minute run.
#
# K=4 IS RUN FIRST and K=8 second, deliberately: K=4 is the serving candidate
# (one world per worker), and each arm is about three hours, so an interruption
# still leaves the primary answer on disk.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/pimc-serving
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
  and d.get('budget_ms')==int(sys.argv[2])
  and d.get('workers')==int(sys.argv[3])
  and d.get('alphabeta') is True and d.get('opponent_alphabeta') is False
  and d.get('via_observation') is True
  and d.get('ab_worlds')==int(sys.argv[4])) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$2" 2>/dev/null
}

say "=== waiting for the box ==="
waited=0
idle=0
while :; do
  if arena_running; then idle=0; else idle=$((idle + 1)); fi
  [ "$idle" -ge 5 ] && break
  sleep 60
  waited=$((waited + 1))
  [ "$waited" -ge 420 ] && { say "ABORT: still busy after seven hours"; exit 1; }
done
say "box free after ${waited}m"

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# CONTROL, in the serving shape. Identical MCTS players at four workers must
# read ~0.5; fixed simulations make it exactly deterministic, so a skew here
# would be a defect in the pooled path rather than variance. The four-worker
# path has never carried a control of its own in this campaign.
say "--- control: identical four-worker MCTS players must read ~0.5 ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/control.json" \
  --pairs 16 --simulations 256 --pool development-pimc-serving-control \
  --opponent-expert --via-observation --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  > /dev/null 2> "$OUT/control.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/control.json'))
s = d['arena']['pair_score']
print(f'  identical players read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.12 else 1)
" || { say "ABORT: the serving-shape control is skewed"; exit 1; }

for k in 4 8; do
  dir="$OUT/k$k"
  mkdir -p "$dir"
  say "=== K=$k across $WORKERS lanes, ${BUDGET}ms turn ==="
  for i in 1 2 3 4; do
    report="$dir/pool-$i.json"
    if usable "$report" "$k"; then say "  pool $i already complete"; continue; fi
    [ -e "$report" ] && say "  pool $i: discarding an unusable report and re-running"
    python -m games.orbit.tools.native_search_arena heuristic "$report" \
      --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
      --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
      --workers "$WORKERS" --game-workers 1 \
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
      python -m games.orbit.tools.pool_arena_reports "$dir"/pool-[0-9].json \
        --accept-pairs 64 --output "$dir/pooled.json" > /dev/null 2>&1
      say "  running: $(python -c "import json;d=json.load(open(r'$dir/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
    else
      say "  pool $i produced no usable report -- see $dir/pool-$i.err"
    fi
  done
done

say "=== serving shape: does PIMC alpha-beta beat the Expert? ==="
python -c "
import json, pathlib
root = pathlib.Path(r'$OUT')
rows = []
for k in (4, 8):
    path = root / f'k{k}' / 'pooled.json'
    if path.exists():
        d = json.loads(path.read_text())
        total = count = 0
        for i in (1, 2, 3, 4):
            p = root / f'k{k}' / f'pool-{i}.json'
            if p.exists():
                for g in json.loads(p.read_text()).get('games', []):
                    total += sum(g.get('ab_depth_by_seat', [0, 0]))
                    count += sum(g.get('ab_searches_by_seat', [0, 0]))
        rows.append((k, d['pair_score'], d['bootstrap_ci95'], d['pairs'],
                     total / count if count else 0.0))

print()
print('PIMC alpha-beta vs the shipped MCTS Expert, SERVING SHAPE')
print('(four workers per seat, 3000ms turn, determinized, 64 CRN pairs):')
print()
print(f\"{'K':>3}  {'score':>7}  {'95% CI':>20}  {'depth':>6}  pairs  verdict\")
for k, score, ci, pairs, depth in rows:
    verdict = 'ahead' if ci[0] > 0.5 else ('behind' if ci[1] < 0.5 else 'not separated')
    print(f'{k:>3}  {score:>7.4f}  [{ci[0]:.4f}, {ci[1]:.4f}]  {depth:>6.2f}  {pairs:>5}  {verdict}')
print()
print('for reference, one thread per seat:   K=4 0.6562 [0.5703, 0.7422] at depth 6.51')
print('the best result this campaign had:    coherent determinization 0.6094 [0.550, 0.669]')
print()
ahead = [r for r in rows if r[2][0] > 0.5]
if ahead:
    best = max(ahead, key=lambda r: r[1])
    print(f'K={best[0]} is ahead of the shipped Expert at serving shape: {best[1]:.4f}.')
    print()
    print('WHAT IS STILL REQUIRED BEFORE THIS SHIPS, none of it optional:')
    print('  1. Confirm at 128+ pairs. Two values of K were tried here and four')
    print('     across the serial ladder, and the campaign pool spread on an')
    print('     IDENTICAL comparison is 0.34 wide.')
    print('  2. A wasm build and a real browser measurement. Every number above')
    print('     is native; the client runs wasm in a worker, where the clock is')
    print('     Date.now() and deliberately coarsened.')
    print('  3. The player-facing decision is the user\\'s, not this scripts.')
else:
    print('Not ahead at serving shape. The one-thread result does not carry over,')
    print('and the difference between the two shapes is the thing to explain')
    print('before any more box time goes into this.')
" 2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/serving-done.marker"
say "=== serving-shape run finished ==="
