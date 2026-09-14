#!/usr/bin/env bash
# DOES THE v3 LEAF PAY, NOW THAT THE LEAF RUNS ON EVERY DECISION?
#
# DERIVED FROM leaf-v2.sh, not retyped. Budget, workers, K, the arena
# invocation and the pool namespaces are that file's; what changes is the leaf,
# the chain flags, the sample size and the control budget.
#
# WHY RE-ASK A QUESTION THAT WASHED. v2 read 0.4766 [0.3984, 0.5625] over 64
# pairs and is not shipping. But it was measured while the leaf was consulted on
# only 55% of decisions -- the Expert refused every position inside a pending
# chain and handed it to the 1-ply ranker. `search-pending` closed that
# (0.5781 [0.5104, 0.6458] over 96 pairs, gate accepted), so the leaf now runs
# on 45% more decisions than when v2 was judged. The leaf's quality matters more
# than it did, which is exactly why v3 was deferred behind the chain work rather
# than run alongside it.
#
# BOTH ARMS CARRY --search-pending, and that is the point rather than a detail.
# The baseline is the bot we intend to serve, not the one we used to serve, so
# this measures the leaf and only the leaf.
#
# v3 vs THE SHIPPED LEAF, not vs v2. `search.rs` keeps v2 "as the control arm
# for StateValueV3", which is the right frame for isolating the distance
# discount v3 adds. It is the wrong frame for a SHIP decision: what matters is
# whether v3 beats what players actually run, which is `state-value`. That is
# also what leaf-v2.sh compared against, so the two runs stay commensurable.
#
# TWO METHOD CHANGES, both paid for on 2026-09-13/14:
#
#   * THE SAMPLE SIZE IS PRE-REGISTERED AT 96 PAIRS. `search-pending` was
#     designed for 64, read at 64, and extended to 96 after a near-miss -- a
#     defensible extension, but an interim look that inflates type-I error and
#     has to be declared forever after. Deciding the size in advance costs about
#     two hours of box time and buys an interval that means what it says. There
#     is NO extension rule here: 96 pairs, read once, whatever it says.
#   * THE CONTROL RUNS AT THE POOLS' BUDGET. Every control in this campaign ran
#     at 600ms or 250ms while its pools ran at 3000ms, so the +/-0.15 skew gate
#     was calibrated on a quieter instrument than the one producing verdicts --
#     at 250ms identical players read EXACTLY 0.5000 with sd 0, because the
#     search is still deterministic there. A control that cheap cannot speak to
#     the configuration it is vouching for.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/leaf-v3
BUDGET=3000; MAIN=1800; FOLLOWUP=1200; WORKERS=4; K=4
export PATH="$HOME/.cargo/bin:$PATH"
mkdir -p "$OUT"

# Reports carry the rules fingerprint inside ``arena``.  A pool produced by a
# previous checkout must never be accepted merely because its search settings
# match: the parity fixes change the reachable state graph and therefore the
# meaning of a win.  Keep the expected value beside the pinned commit so a
# resumed campaign cannot silently pool old-rule results with new-rule ones.
RULES_AT_START="$(python -c 'from games.orbit.ai.state import rules_fingerprint; print(rules_fingerprint())')"

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
  and d.get('leaf')=='state-value-v3'
  and d.get('opponent_leaf')=='state-value'
  and d.get('search_pending') is True
  and d.get('opponent_search_pending') is True
  and d.get('arena',{}).get('rules')==sys.argv[5]) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$K" "$RULES_AT_START" 2>/dev/null
}

claim_box "leaf-v3" 600 || { say "ABORT: could not claim the box"; exit 1; }

# THE TREE MUST NOT MOVE UNDER THE RUN, AND BOTH FLAGS MUST PARSE BEFORE THE
# BOX IS SPENT. On 2026-09-13 the shared worktree was switched to main four
# minutes before a pool finished; the next three pools invoked main's arena,
# died in three seconds each on an unrecognised flag, and the script printed a
# confident verdict off the one pool that survived.
HEAD_AT_START="$(git rev-parse HEAD)"
say "pinned to $(git rev-parse --short HEAD) on $(git rev-parse --abbrev-ref HEAD)"
ARENA_HELP="$(python -m games.orbit.tools.native_search_arena --help 2>&1)"
printf '%s' "$ARENA_HELP" | grep -q -- '--search-pending'   || { say "ABORT: this tree's arena does not accept --search-pending"; exit 1; }
printf '%s' "$ARENA_HELP" | grep -q -- 'state-value-v3'   || { say "ABORT: this tree's arena does not offer the v3 leaf"; exit 1; }

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# CONTROL: both arms the SHIPPED leaf, both alpha-beta. Identical players, so it
# must read ~0.5. This is the check that catches a `--leaf` flag that never
# reaches the alpha-beta seat -- which it did not until today, and would have
# made this whole comparison read 0.5 while looking like a real null.
say "--- control: both arms the shipped leaf must read ~0.5 ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/control.json" \
  --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
  --pool development-leaf-v3-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" --search-pending --opponent-search-pending \
  > /dev/null 2> "$OUT/control.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/control.json'))
s = d['arena']['pair_score']
print(f'  identical players read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.15 else 1)
" || { say "ABORT: the control is skewed; the comparison would be meaningless"; exit 1; }

# A SECOND CONTROL, and this one is the important one: the v2 flag must actually
# CHANGE the player. A leaf wired only into the MCTS while both arms run
# alpha-beta would read a clean 0.5 and be indistinguishable from "the new leaf
# is exactly as good". Same deals, same everything, v2 on one side: if this also
# reads 0.5000 exactly, the flag is not reaching the search.
say "--- wiring check: v3 must not read EXACTLY the control ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/wiring.json" \
  --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
  --pool development-leaf-v3-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" --search-pending --opponent-search-pending --leaf state-value-v3 \
  > /dev/null 2> "$OUT/wiring.err"
python -c "
import json, sys
a = json.load(open(r'$OUT/control.json'))['arena']['pair_score']
b = json.load(open(r'$OUT/wiring.json'))['arena']['pair_score']
print(f'  shipped-vs-shipped {a:.4f}, v3-vs-shipped {b:.4f} on the SAME deals')
if abs(a - b) < 1e-9:
    print('  THE FLAG IS NOT REACHING THE SEARCH -- identical to the last decimal')
    sys.exit(1)
" || { say "ABORT: --leaf does not reach the alpha-beta seat"; exit 1; }

for i in 1 2 3 4 5 6; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  now="$(git rev-parse HEAD)"
  if [ "$now" != "$HEAD_AT_START" ]; then
    say "ABORT: the tree moved under the run ($HEAD_AT_START -> $now)"
    say "       pools already written stay valid; this run is INCOMPLETE"
    date > "$OUT/leaf-v3-done.marker"
    exit 1
  fi
  say "=== pool $i: v3 leaf vs the shipped leaf, both alpha-beta K=$K ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --alphabeta --opponent-alphabeta --ab-worlds "$K" --search-pending --opponent-search-pending --leaf state-value-v3 \
    > /dev/null 2> "$OUT/pool-$i.err"
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
  say "RUN INCOMPLETE: $complete of 6 pools produced a usable report."
  say "       Refusing to print a verdict. A pooled number off a partial run"
  say "       reads exactly like a finished measurement -- see the pool-N.err files."
  date > "$OUT/leaf-v3-done.marker"
  exit 1
fi

say "=== does the victory-aware leaf beat the shipped one? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 96 --output "$OUT/pooled.json"
python -c "
import json, pathlib
d = json.loads(pathlib.Path(r'$OUT/pooled.json').read_text())
low, high = d['bootstrap_ci95']
print()
print(f\"v3 leaf vs the shipped leaf, both alpha-beta PIMC K=$K at serving shape:\")
print(f\"  {d['pair_score']:.4f}  [{low:.4f}, {high:.4f}]  over {d['pairs']} pairs\")
print()
if low > 0.5:
    print('THE LEAF FIX WINS. Extend to 128 pairs, then it is a wasm rebuild and')
    print('a Python port for the parity gate before it ships.')
elif high < 0.5:
    print('THE LEAF FIX LOSES. The threat pricing is right in isolation, so what')
    print('costs more is the other half: v2 discounts EARLY influence quadratically')
    print('and board presence is evidently worth more than that. Keep the squash,')
    print('retry the victory term with a gentler distance discount.')
else:
    print('Not separated at 64 pairs. The campaign pool spread on an IDENTICAL')
    print('comparison is 0.34 wide, so extend before concluding either way.')
"  2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/leaf-v3-done.marker"
say "=== finished ==="
