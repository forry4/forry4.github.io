#!/usr/bin/env bash
# WHERE DOES A SCREENING BUDGET START TELLING THE TRUTH?
#
# The same checkpoint, g004/epoch-006, against the same shipped heuristic
# Expert, reads 0.8125 at the league's 250 ms proxy and 0.4375 at serving shape
# (64 pairs, 95% CI [0.352, 0.523]). A 0.375 swing from the budget alone.
#
# The mechanism is the repo's documented leaf-speed trap: budget decides whether
# LEAF QUALITY or SEARCH DEPTH dominates. A neural leaf is expensive but better
# per simulation, so at 250 ms -- where neither side searches deep -- leaf
# quality wins; by 3000 ms the heuristic Expert is doing ~10,900 simulations per
# decision and depth compensates for its weaker leaf. The two strength-versus-
# simulations curves cross somewhere in between, and the proxy sat on the wrong
# side of the crossing.
#
# That makes the budget a VALIDITY parameter, not a precision one, and it cannot
# be chosen by intuition. This measures the crossing instead: the identical
# comparison at 250 / 500 / 1000 / 2000 ms, 64 pairs each, against the 3000 ms
# run already on disk. The output is the minimum budget whose ORDERING matches
# serving -- a defensible screening floor that licenses every future cheap
# screen, instead of forcing everything to full serving cost.
#
# Two choices worth stating:
#
# * Every rung keeps the 60/40 main/follow-up split, so 250 reproduces the
#   league's own `proxy-250-150-100-w4-g3` profile exactly on that axis.
# * Every rung REUSES THE SAME POOL NAMESPACES as the 3000 ms run, so each
#   budget plays identical deals. The rung-to-rung comparison is then paired and
#   deal variance drops out of it -- which matters because 64 pairs resolves
#   only about +/-0.12 unpaired.
#
# The league profile used three game workers (12 threads on a 12-logical box).
# This uses one, like every other measurement in this campaign, because an
# equal-time arena does not slow under contention -- it silently starves each
# decision of simulations. Some of the original 0.81 may itself be that effect.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
ROOT=games/orbit/ai/runs/budget-ladder
CANDIDATE=games/orbit/ai/runs/neural-league-v2/g004/model/epoch-006.pt
WORKERS=4
mkdir -p "$ROOT"

say() { echo "[$(date '+%H:%M:%S')] $*"; }

usable() {
  python -c "import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(1)
sys.exit(0 if (d.get('complete') is True and d.get('arena')
  and d.get('budget_ms')==int(sys.argv[2]) and d.get('workers')==int(sys.argv[3])) else 1)" \
  "$1" "$2" "$WORKERS" 2>/dev/null
}

say "=== budget ladder: g004 vs the shipped Expert at five budgets ==="

for budget in 250 500 1000 2000; do
  main=$((budget * 6 / 10))
  followup=$((budget - main))
  out="$ROOT/b$budget"
  mkdir -p "$out"
  say "--- ${budget}ms turn (${main} main / ${followup} follow-up) ---"
  for i in 1 2 3 4; do
    report="$out/pool-$i.json"
    if usable "$report" "$budget"; then say "  pool $i already complete"; continue; fi
    python -m games.orbit.tools.native_search_arena "$CANDIDATE" "$report" \
      --pairs 16 --budget-ms "$budget" --main-action-ms "$main" --followup-ms "$followup" \
      --pool "development-league-g004-vs-expert-p$i" --opponent-expert --via-observation \
      --workers "$WORKERS" --game-workers 1 \
      --determinization-period 0 --opponent-determinization-period 0 > /dev/null 2>&1
    if usable "$report" "$budget"; then
      python -c "import json,sys;d=json.load(open(sys.argv[1]));a=d['arena'];print('  pool',sys.argv[2],'score',round(a['pair_score'],4),'secs',round(d['seconds']))" "$report" "$i"
    else
      say "  pool $i produced no usable report"
    fi
  done
  python -m games.orbit.tools.pool_arena_reports "$out"/pool-[0-9].json \
    --accept-pairs 64 --output "$out/pooled.json" > /dev/null 2>&1
  say "  ${budget}ms => $(python -c "import json;d=json.load(open(r'$out/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
done

say "=== the curve ==="
python -c "
import json, pathlib
root = pathlib.Path(r'$ROOT')
rows = []
for budget in (250, 500, 1000, 2000):
    path = root / f'b{budget}' / 'pooled.json'
    if path.exists():
        d = json.loads(path.read_text())
        rows.append((budget, d['pair_score'], d['bootstrap_ci95'], d['pairs']))
serving = pathlib.Path(r'games/orbit/ai/runs/league-g004-vs-expert/pooled.json')
if serving.exists():
    d = json.loads(serving.read_text())
    rows.append((3000, d['pair_score'], d['bootstrap_ci95'], d['pairs']))
print(f\"{'budget':>8}  {'score':>7}  {'95% CI':>18}  pairs  verdict\")
for budget, score, ci, pairs in rows:
    verdict = 'candidate ahead' if ci[0] > 0.5 else ('Expert ahead' if ci[1] < 0.5 else 'not separated')
    print(f'{budget:>6}ms  {score:>7.4f}  [{ci[0]:.4f}, {ci[1]:.4f}]  {pairs:>5}  {verdict}')
print()
print('The screening floor is the lowest budget whose verdict matches 3000ms.')
" 2>&1 | tee "$ROOT/curve.txt"
date > "$ROOT/ladder-done.marker"
say "=== ladder finished ==="
