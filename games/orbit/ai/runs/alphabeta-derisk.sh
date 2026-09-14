#!/usr/bin/env bash
# DOES DEPTH BEAT WIDTH IN ORBIT?
#
# WIDTH IS DEAD, measured three ways this session:
#   * coherent determinization won by descending DEEPER on FEWER simulations
#   * minimax bought 1.96x the simulations AND the first adversarial opponent
#     model, together worth +0.04 (0.5430 / 128 pairs, CI [0.4766, 0.6094])
#   * the saturation probe doubled the simulations at the real operating point
#     -- 10,896 per decision against 5,448 -- and got 0.4609 (CI [0.4062,
#     0.5156]), with 51 of 64 pairs splitting outright
#
# Orbit's profile says the same from the other side: branching ~6.7 mean / 18
# max, a strong hand-written evaluator, a perfect-information cheat of only
# 0.6094, and draws that are `deck.pop()` so chance is consulted only on a
# reshuffle. That is the Chess/Othello profile where alpha-beta dominated for
# forty years, not the Go profile where MCTS won because branching was enormous
# and no good evaluator existed.
#
# A TRAP THIS SCRIPT EXISTS TO AVOID. The MCTS ALWAYS resamples hidden
# information from the seat's observation -- `sample()` rebuilds the opponent's
# hand and the deck order every determinization, so handing it a privileged
# state changes NOTHING. A first attempt at this comparison gave alpha-beta the
# true world and the MCTS a resampled one and read 16-0. That was the
# hidden-information cheat (worth 0.6094 on its own), not depth.
# `--perfect-information` turns resampling off for BOTH seats, and its control
# below must read ~0.5 or the arm means nothing.
#
# TWO ARMS, because they answer different questions:
#   A. PERFECT INFORMATION -- isolates the architecture. No beliefs, no strategy
#      fusion, no resampling: purely depth-first against MCTS at equal CPU.
#   B. DETERMINIZED (--via-observation) -- the SERVING-relevant question. Both
#      seats rebuild one world from their own observation, which is the shipped
#      coherent regime, and alpha-beta inherits its strategy fusion.
# A is the cleaner instrument; B is the one that decides whether anything ships.
#
# ONE THREAD PER SEAT, which is NOT serving shape. Serving runs a four-worker
# root-summed ensemble; alpha-beta is a single deterministic tree, so an
# ensemble of it is the same search summed with itself -- the arena refuses the
# combination rather than quietly measuring one thread against four. This is
# therefore the honest per-CPU comparison, and "can alpha-beta use four threads"
# (it parallelises far worse than root-summed MCTS) is a real cost to weigh only
# if it wins here.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/alphabeta-derisk
BUDGET=3000; MAIN=1800; FOLLOWUP=1200
export PATH="$HOME/.cargo/bin:$PATH"
mkdir -p "$OUT/perfect" "$OUT/determinized"

say() { echo "[$(date '+%H:%M:%S')] $*"; }

arena_running() {
  powershell.exe -NoProfile -Command \
    "if (Get-Process -Name neural_arena -ErrorAction SilentlyContinue) { 'yes' } else { 'no' }" \
    2>/dev/null | tr -d '\r' | grep -q yes
}

# The resume guard checks the SHAPE, not merely that a file exists: a killed run
# leaves a zero-game stub that `[ -s ]` happily calls complete.
usable() {
  python -c "import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(1)
want_perfect = sys.argv[3] == 'perfect'
sys.exit(0 if (d.get('complete') is True and d.get('arena')
  and d.get('budget_ms')==int(sys.argv[2])
  and d.get('alphabeta') is True and d.get('opponent_alphabeta') is False
  and d.get('perfect_information') is want_perfect
  and d.get('via_observation') is (not want_perfect)) else 1)" \
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

say "rebuilding (the running binary predates the alpha-beta knob)"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bin neural_arena --bin value_generate --bin bridge --bin policy_diff --bin ab_probe \
  > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# ---------------------------------------------------------------------------
# arm <name> <extra flag>
# ---------------------------------------------------------------------------
arm() {
  # Separate statements, NOT one `local a=.. b=$a`: bash expands every word in
  # a local command BEFORE performing any of its assignments, so a reference to
  # an earlier name in the same statement is unbound. Under `set -u` that is a
  # fatal error, which is the good outcome -- without it `dir` would silently
  # have been "$OUT/" and both arms would have overwritten each other.
  local name="$1"
  local flag="$2"
  local dir="$OUT/$name"

  # CONTROL FIRST, in the arm's own regime. Identical players must read ~0.5;
  # fixed simulations make it exactly deterministic, so a skew is a defect
  # rather than variance. This is the check that catches a flag which quietly
  # breaks the MCTS and hands alpha-beta a walkover.
  say "--- $name control: identical MCTS players must read ~0.5 ---"
  python -m games.orbit.tools.native_search_arena heuristic "$dir/control.json" \
    --pairs 16 --simulations 256 --pool "development-ab-control-$name" \
    --opponent-expert --workers 1 --game-workers 4 \
    --determinization-period 0 --opponent-determinization-period 0 \
    $flag > /dev/null 2> "$dir/control.err"
  python -c "
import json, sys
d = json.load(open(r'$dir/control.json'))
s = d['arena']['pair_score']
print(f'  identical players read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.12 else 1)
" || { say "ABORT: the $name control is skewed; that arm would be meaningless"; return 1; }

  for i in 1 2 3 4; do
    local report="$dir/pool-$i.json"
    if usable "$report" "$name"; then say "  pool $i already complete"; continue; fi
    [ -e "$report" ] && say "  pool $i: discarding an unusable report and re-running"
    say "--- $name pool $i: alpha-beta vs the MCTS Expert, equal time ---"
    python -m games.orbit.tools.native_search_arena heuristic "$report" \
      --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
      --pool "development-ab-$name-p$i" --opponent-expert \
      --workers 1 --game-workers 4 \
      --determinization-period 0 --opponent-determinization-period 0 \
      $flag --alphabeta > /dev/null 2> "$dir/pool-$i.err"
    if usable "$report" "$name"; then
      python -c "
import json, sys
d = json.load(open(sys.argv[1]))
a = d['arena']
games = d['games']
# What depth did alpha-beta reach in a REAL game, not in the probe? A depth that
# collapses under arena load would explain a loss without saying anything about
# depth as a lever.
depth = sum(sum(g.get('ab_depth_by_seat', [0, 0])) for g in games)
searches = sum(sum(g.get('ab_searches_by_seat', [0, 0])) for g in games)
nodes = sum(sum(g.get('ab_nodes_by_seat', [0, 0])) for g in games)
print('  pool', sys.argv[2], 'score', round(a['pair_score'], 4), a['pair_ci95'],
      '| mean depth', round(depth / searches, 2) if searches else 0,
      '| nodes/search', round(nodes / searches) if searches else 0,
      '| secs', round(d['seconds']))
" "$report" "$i"
    else
      say "  pool $i produced no usable report -- see $dir/pool-$i.err"
    fi
  done

  python -m games.orbit.tools.pool_arena_reports "$dir"/pool-[0-9].json \
    --accept-pairs 64 --output "$dir/pooled.json" > /dev/null 2>&1
  say "  $name => $(python -c "import json;d=json.load(open(r'$dir/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
}

arm perfect "--perfect-information"
arm determinized "--via-observation"

say "=== does depth beat width? ==="
python -c "
import json, pathlib
root = pathlib.Path(r'$OUT')
rows = []
for name, what in (('perfect', 'perfect information (architecture, isolated)'),
                   ('determinized', 'determinized (the serving-relevant question)')):
    path = root / name / 'pooled.json'
    if path.exists():
        d = json.loads(path.read_text())
        rows.append((name, what, d['pair_score'], d['bootstrap_ci95'], d['pairs']))

print()
print('alpha-beta vs the MCTS Expert, equal time, one thread each:')
print()
for name, what, score, ci, pairs in rows:
    print(f'  {score:.4f}  [{ci[0]:.4f}, {ci[1]:.4f}]  over {pairs:>3} pairs   {what}')
print()

verdict = {name: (score, ci) for name, _, score, ci, _ in rows}
det = verdict.get('determinized')
perf = verdict.get('perfect')
if det and det[1][0] > 0.5:
    print('DEPTH WINS WHERE IT COUNTS. Alpha-beta beats the MCTS at equal CPU in')
    print('the determinized regime, which is the one that ships. Next: settle the')
    print('thread question honestly (serving runs four root-summed workers and')
    print('alpha-beta does not parallelise that way), then PIMC over K worlds.')
elif perf and perf[1][0] > 0.5 and det and det[1][1] < 0.55:
    print('DEPTH WINS ONLY WITH PERFECT INFORMATION. The architecture is sound but')
    print('strategy fusion eats the gain -- alpha-beta commits hard to one world.')
    print('That is an argument for PIMC over K worlds rather than against depth,')
    print('and K is then the whole experiment.')
elif perf and perf[1][1] < 0.45:
    print('DEPTH LOSES IN THE REGIME MOST FAVOURABLE TO IT. Hidden information only')
    print('ever costs a searcher, so determinizing cannot rescue this. Close the')
    print('alpha-beta thesis for Orbit and do not relitigate it per-idea.')
else:
    print('Not separated. The measured pool spread on an IDENTICAL comparison this')
    print('campaign was 0.34 wide, so do not read a single pool; extend first.')
" 2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/derisk-done.marker"
say "=== de-risk finished ==="
