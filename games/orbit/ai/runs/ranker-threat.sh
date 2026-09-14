#!/usr/bin/env bash
# DOES THE VICTORY-AWARE RANKER MAKE THE EXPERT STRONGER?
#
# WHY THE RANKER IS WORTH BOX TIME AT ALL, when it is "only a prior". It is not
# only a prior here. `State::from_observation` refuses any position with a
# pending chain, so the served Expert hands every effect-resolution choice to
# the 1-ply ranker instead of searching it -- and that is **45.0% of all
# decisions with a real choice** (10,537 of 23,394 over 300 games). The search
# never sees them.
#
# WHAT WAS WRONG WITH IT. The ranker scored a planet at `choice * position`,
# where `position` is the seat's OWN signed progress. So a planet the opponent
# led by two scored 0.4 * -2 = -0.8 and ranked BELOW every neutral planet. It
# was not merely blind to the opponent's victory condition -- it was REPELLED by
# it, in proportion to the danger, most strongly at the moment of greatest
# danger. One line down, `choice_capture` paid a flat 2.0 for ANY capture, so a
# worthless capture of its own outranked blocking one that ended the game.
#
# THE TACTICAL FIX IS NOT IN DOUBT; the strength gain is. Measured PAIRED over
# 300 games -- both rankers scored on the SAME positions, so the distribution
# cannot move under the treatment -- in the 97 positions where blocking a
# game-ending capture was legal and the seat had no win of its own:
#
#     old ranker played elsewhere : 97 of 97   (100.0%)
#     new ranker played elsewhere :  0 of 97   (  0.0%)
#
# That is a complete fix of one decisive blunder class. It is NOT a strength
# measurement, and this campaign has been burned by exactly that inference: the
# v2 leaf priced a game-losing threat correctly in isolation, reproduced the
# playtest report exactly, and then measured 0.4766 over 64 pairs. A tactic the
# search would have found anyway is worth nothing. The difference here is that
# the search does NOT get to find these -- they are in the 45% it refuses -- but
# that is an argument, and arguments are what arenas are for.
#
# BOTH ARMS ARE THE SHIPPED EXPERT: alpha-beta PIMC K=4 at serving shape, the
# SHIPPED leaf (v2 washed at 0.4766 and is not in this comparison). The only
# difference is which ranker answers the decisions the search refuses, and
# orders the moves in the ones it does not.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/ranker-threat
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
  and d.get('ranker_v1') is False
  and d.get('opponent_ranker_v1') is True) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$K" 2>/dev/null
}

claim_box "ranker-threat" 480 || { say "ABORT: could not claim the box"; exit 1; }

say "rebuilding every binary"
RUSTFLAGS='-C target-cpu=native' cargo build --release --locked --features chunked-dot \
  --manifest-path rust-cores/orbit-core/Cargo.toml --target-dir games/orbit/ai/runs/target-native \
  --bins > "$OUT/rebuild.log" 2>&1 || { say "ABORT: rebuild failed, see rebuild.log"; exit 1; }

# CONTROL: both seats on the OLD ranker. Identical players, so ~0.5. This is
# what catches a `--ranker-v1` flag that never reaches the seat -- the exact
# failure `--leaf` had until 2026-09-13, which would have made the whole
# comparison an honest-looking null.
say "--- control: both arms the old ranker must read ~0.5 ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/control.json" \
  --pairs 16 --budget-ms 600 --main-action-ms 360 --followup-ms 240 \
  --pool development-ranker-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" \
  --ranker-v1 --opponent-ranker-v1 \
  > /dev/null 2> "$OUT/control.err"
python -c "
import json, sys
d = json.load(open(r'$OUT/control.json'))
s = d['arena']['pair_score']
print(f'  identical players read {s:.4f} over {d[\"arena\"][\"pairs\"]} pairs')
sys.exit(0 if abs(s - 0.5) <= 0.15 else 1)
" || { say "ABORT: the control is skewed; the comparison would be meaningless"; exit 1; }

# WIRING CHECK, and it is the one that matters. Same deals, same everything,
# the NEW ranker on one side only. If this reads EXACTLY the control, the flag
# is not reaching the seat and every pool below would be measuring nothing.
say "--- wiring check: the new ranker must not read EXACTLY the control ---"
python -m games.orbit.tools.native_search_arena heuristic "$OUT/wiring.json" \
  --pairs 16 --budget-ms 600 --main-action-ms 360 --followup-ms 240 \
  --pool development-ranker-control --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --opponent-alphabeta --ab-worlds "$K" \
  --opponent-ranker-v1 \
  > /dev/null 2> "$OUT/wiring.err"
python -c "
import json, sys
a = json.load(open(r'$OUT/control.json'))['arena']['pair_score']
b = json.load(open(r'$OUT/wiring.json'))['arena']['pair_score']
print(f'  old-vs-old {a:.4f}, new-vs-old {b:.4f} on the SAME deals')
if abs(a - b) < 1e-9:
    print('  THE FLAG IS NOT REACHING THE SEAT -- identical to the last decimal')
    sys.exit(1)
" || { say "ABORT: --ranker-v1 does not reach the seat"; exit 1; }

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i: victory-aware ranker vs the shipped one, both alpha-beta K=$K ==="
  python -m games.orbit.tools.native_search_arena heuristic "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-ab-determinized-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --alphabeta --opponent-alphabeta --ab-worlds "$K" \
    --opponent-ranker-v1 \
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
      --accept-pairs 64 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "  running: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "  pool $i produced no usable report -- see $OUT/pool-$i.err"
  fi
done

say "=== does fixing the ranker make the Expert stronger? ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"
python -c "
import json, pathlib
d = json.loads(pathlib.Path(r'$OUT/pooled.json').read_text())
low, high = d['bootstrap_ci95']
print()
print('victory-aware ranker vs the shipped one, both alpha-beta PIMC K=$K at')
print('serving shape with the shipped leaf:')
print(f\"  {d['pair_score']:.4f}  [{low:.4f}, {high:.4f}]  over {d['pairs']} pairs\")
print()
if low > 0.5:
    print('SHIP IT. The blunder fix converts. This is the first gain of the')
    print('campaign that is NOT a search change, and it is one because the')
    print('ranker is not acting as a prior -- it is answering 45% of the')
    print('decisions outright.')
    print()
    print('Shipping is three files plus the asset: serving.rs, ai/serving.py and')
    print('orbit-worker.js all carry the policy, plus orbit-model.json which')
    print('holds the weights the JS fallback reads. Rebuild the wasm.')
elif high < 0.5:
    print('WORSE, which would be a real finding rather than a null. The blunder')
    print('fix is not in question -- 97 of 97 to 0 of 97, paired. So if this')
    print('loses, contesting is being OVER-valued: the denial term at 0.8 may be')
    print('pulling the bot off its own development to chase threats that the')
    print('opponent was never going to convert. Retry at a lower THREAT weight')
    print('before abandoning it.')
else:
    print('Not separated at 64 pairs. The campaign pool spread on an IDENTICAL')
    print('comparison is 0.34 wide, so extend to 128 before concluding. Note')
    print('that the blunder class this fixes is RARE -- 97 positions in 300')
    print('games, about one every three games -- so even a real gain may need')
    print('more pairs than a search change would.')
" 2>&1 | tee "$OUT/verdict.txt"
date > "$OUT/ranker-done.marker"
say "=== finished ==="
