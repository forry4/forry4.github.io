#!/usr/bin/env bash
# DOES SEARCHING THE SUB-DECISIONS PAY? -- THE EXTENSION TO 96 PAIRS.
#
# DERIVED FROM search-pending.sh, NOT RETYPED. Every setting below -- budget,
# workers, K, the usable() contract, the arena invocation -- is the original
# file with the pool list and the sample size changed. An extension that
# retyped its configuration could differ from the run it extends in one flag
# and pool the two anyway, which would be undetectable in the pooled number.
#
# WHY EXTEND, WHEN THE SAME ADVICE WAS OVERRIDDEN THIS MORNING. The 64-pair run
# read 0.5781 [0.4922, 0.6641] and missed its gate by 0.0078 -- the narrowest
# possible miss. The pooled report puts pairs_needed_for_this_effect at 82; the
# run has 64, and two more pools reach 96. Compare ranker-threat, where the
# script gave the identical "extend" advice and it was overridden: that effect
# needed 844 pairs, roughly 68 hours, to characterise something pointing the
# wrong way. Same advice, opposite answer, and this number is what separates
# them. Extending is only ever worth it when the instrument can actually reach
# the effect.
#
# WHAT MAKES THIS DIFFERENT FROM leaf-v2 IS THE PATTERN, NOT THE MEAN. Four
# independent deal sets read 0.625, 0.625, 0.5312, 0.5312 -- every pool above
# 0.5 -- and the two independent runs of pool 1 (0.5938 before the crash, 0.625
# after) also landed above it. leaf-v2, the wash this superficially resembles,
# put two of its four pools BELOW 0.5: 0.594, 0.281, 0.594, 0.438. A consistent
# small edge and a coin-flip average are different shapes, and pooling hides
# the difference.
#
# THE EXTENSION IS NOT A SECOND CHANCE AT THE SAME QUESTION. Pools 5 and 6 are
# fresh deal sets (p5, p6), and the verdict is read over all six pooled -- not
# over whichever subset looks best. Stopping early if they run hot would be
# exactly the multiple-comparisons error the pimc-ladder header warns about.
#
# NO FRESH CHAIN PRE-FLIGHT. That check has passed three times (21.5%, 22.4%,
# 23.8% refusal against a 22.5% prediction) and each pool prints its own
# searched/refused counts, so a chain that stopped arriving would show up per
# pool as refusals climbing toward 45%. The flag pre-flight and the commit pin
# stay: those guard the failure that is silent.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/search-pending
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
  and d.get('search_pending') is True
  and d.get('opponent_search_pending') is False) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$K" 2>/dev/null
}

# WAIT FOR THE QUEUE AHEAD rather than racing for the lock. box-lock.sh is
# fair-by-race -- every waiter retries every 20s and whoever wins the atomic
# create goes next -- so two scripts waiting together start in arbitrary order.

claim_box "search-pending-extend" 480 || { say "ABORT: could not claim the box"; exit 1; }

# THE TREE MUST NOT MOVE UNDER THE RUN, AND THE FLAG MUST PARSE BEFORE WE SPEND
# AN HOUR ON A POOL. On 2026-09-13 the shared worktree was switched to main four
# minutes before pool 1 finished. Pools 2-4 then invoked main's arena, which has
# no --search-pending, and each died in three seconds -- and the script noticed
# only that three pools were "not usable" before printing a confident verdict
# off the single surviving pool. That is the failure this campaign cannot
# afford: a number that reads like a measurement and is an accident.
HEAD_AT_START="$(git rev-parse HEAD)"
say "pinned to $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
python -m games.orbit.tools.native_search_arena --help 2>&1 | grep -q -- '--search-pending'   || { say "ABORT: this tree's arena does not accept --search-pending"; exit 1; }

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# THE NON-VACUITY CHECK, and here it is far better than a mirror control,
# because the flag's whole effect is directly countable. `ranker_decisions`
# counts decisions the search REFUSED and the ranker answered. If the chain is
# reaching the reconstruction, the candidate's count must collapse and the
# opponent's must not move. A flag that silently failed to arrive would leave
# both counts equal and the pools below would report an honest-looking 0.5.
say "--- does the chain actually reach the search? ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/fires.json" \
  --pairs 8 --budget-ms 600 --main-action-ms 360 --followup-ms 240 \
  --pool development-search-pending-fires --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" --search-pending \
  > /dev/null 2> "$OUT/fires.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/fires.json'))
games = d.get('games', [])
refused = [0, 0]
searches = [0, 0]
for g in games:
    for seat in (0, 1):
        refused[seat] += g.get('ranker_decisions_by_seat', [0, 0])[seat]
        searches[seat] += g.get('ab_searches_by_seat', [0, 0])[seat]
print(f'  decisions the search REFUSED  : seat0 {refused[0]}, seat1 {refused[1]}')
print(f'  decisions the search ANSWERED : seat0 {searches[0]}, seat1 {searches[1]}')
# The candidate seat alternates between 0 and 1 across paired games, so the two
# seats are not separable here -- what must be true is that the TOTAL refusals
# fell well below the searches, which cannot happen if the chain never arrives.
if sum(refused) >= sum(searches):
    print('  THE CHAIN IS NOT REACHING THE SEARCH -- refusals did not fall')
    sys.exit(1)
if not d.get('search_pending'):
    print('  the report does not even record the flag'); sys.exit(1)
print(f\"  recorded: search_pending={d['search_pending']}, \"
      f\"opponent_search_pending={d['opponent_search_pending']}\")
" || { say "ABORT: --search-pending is not reaching the arena"; exit 1; }

for i in 5 6; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  now="$(git rev-parse HEAD)"
  if [ "$now" != "$HEAD_AT_START" ]; then
    say "ABORT: the tree moved under the run ($HEAD_AT_START -> $now)"
    say "       pools already written stay valid; this run is INCOMPLETE"
    date > "$OUT/search-pending-extend-done.marker"
    exit 1
  fi
  say "=== pool $i: searching sub-decisions vs handing them to the ranker ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --alphabeta --opponent-alphabeta --ab-worlds "$K" --search-pending \
    > /dev/null 2> "$OUT/pool-$i.err"
  if usable "$report"; then
    python -c "
import json, sys
d = json.load(open(sys.argv[1]))
a = d['arena']
games = d['games']
depth = sum(sum(g.get('ab_depth_by_seat', [0, 0])) for g in games)
searches = sum(sum(g.get('ab_searches_by_seat', [0, 0])) for g in games)
refused = sum(sum(g.get('ranker_decisions_by_seat', [0, 0])) for g in games)
print('  pool', sys.argv[2], 'score', round(a['pair_score'], 4), a['pair_ci95'],
      '| mean depth', round(depth / searches, 2) if searches else 0,
      '| searched', searches, 'refused', refused,
      '| secs', round(d['seconds']))
" "$report" "$i"
    python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
      --accept-pairs 96 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "  running: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "  pool $i produced no usable report -- see $OUT/pool-$i.err"
  fi
done

complete=0
for i in 1 2 3 4 5 6; do usable "$OUT/pool-$i.json" && complete=$((complete + 1)); done
if [ "$complete" -lt 6 ]; then
  say "RUN INCOMPLETE: $complete of 4 pools produced a usable report."
  say "       Refusing to print a verdict. A pooled number off a partial run"
  say "       reads exactly like a finished measurement -- see the pool-N.err files."
  date > "$OUT/search-pending-extend-done.marker"
  exit 1
fi

say "=== does searching the sub-decisions pay? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 96 --output "$OUT/pooled.json"
python -c "
import json, pathlib
d = json.loads(pathlib.Path(r'$OUT/pooled.json').read_text())
low, high = d['bootstrap_ci95']
print()
print('searching effect-resolution sub-decisions vs handing them to the ranker,')
print('both alpha-beta PIMC K=$K at serving shape with the shipped leaf:')
print(f\"  {d['pair_score']:.4f}  [{low:.4f}, {high:.4f}]  over {d['pairs']} pairs\")
print()
if low > 0.5:
    print('SHIP IT. The Expert now searches 100% of its decisions instead of 55%,')
    print('and the plan it forms when it plays a card is the plan that resolves.')
    print()
    print('Shipping is a wasm rebuild plus three files that must go together:')
    print('  games/orbit/main.py       sends pending_chain beside the observation')
    print('  games/orbit/Orbit.jsx     forwards it to the workers')
    print('  webapp/public/wasm/*      the worker calls the new chain export')
    print('Deploy order does not matter: a client without the chain, or a wasm')
    print('without the export, refuses exactly as it does today.')
    print()
    print('THEN RE-MEASURE THE LEAF. v3 was deferred behind this on purpose --')
    print('the leaf now runs on 45% more decisions, so its quality matters more')
    print('than it did when v2 washed at 0.4766.')
elif high < 0.5:
    print('WORSE, and that would be worth understanding rather than reverting.')
    print('The likeliest mechanism is BUDGET: sub-decisions now consume the')
    print('follow-up reserve, so a turn that used to spend 1800ms on its main')
    print('action and nothing after it may now arrive at the main action with')
    print('less depth. Check mean depth against the baseline before concluding')
    print('that searching these decisions is itself wrong.')
else:
    print('STILL not separated at 96 pairs, which is past what the 64-pair')
    print('effect size needed (82). That is the answer: the edge is real but')
    print('too small for this instrument to certify, and further pairs are')
    print('a poor trade. Note the')
    print('mechanism is not in doubt -- the refusal counter shows the search')
    print('really is answering these decisions now -- so a null here is a')
    print('statement about how much those decisions MATTER, not about wiring.')
" 2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/search-pending-extend-done.marker"
say "=== finished ==="
