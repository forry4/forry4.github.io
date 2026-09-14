#!/usr/bin/env bash
# RE-RUN THE ONE POOL THAT WAS MEASURED UNDER CONTENTION.
#
# On 2026-09-13 two run scripts were waiting for the box at the same time, both
# observed it genuinely idle, and both started:
#
#   K=4 extension: "box free after 12m"  at 05:12:29
#   serving run:   "box free after  4m"  at 05:12:12
#
# The consecutive-idle gate cannot prevent that -- nothing either script
# observes distinguishes "idle" from "idle and about to be taken". `box-lock.sh`
# is the actual fix (an atomic, stale-safe lock); this repairs the data.
#
# WHAT IS AND IS NOT CONTAMINATED, decided by what each measurement depends on:
#
# * The serving CONTROL is FINE and is not re-run. It is a fixed-SIMULATION
#   arena, which is deterministic and load-independent by construction -- that
#   is precisely why controls in this campaign use fixed simulations. It read
#   exactly 0.5000.
# * K=4 POOL 1 is contaminated and is re-run. It is equal-TIME, and an
#   equal-time arena does not slow under contention: it silently gets less work
#   done per decision. The evidence is direct -- alpha-beta's mean depth was
#   7.51 in that pool, against 6.21 in the extension pools sharing the box, and
#   the uncontended pools of the serial ladder held 6.51 with tight spread.
# * Pools 2-4 start after 05:55 and run alone, so they are clean.
#
# The extension's own pools 5-8 are a subtler case and are NOT re-run here. Both
# seats of a given game share one arena process and take turns, so contention
# starves both players in that game roughly equally: it moves the operating
# point rather than biasing the comparison. Their depth (6.21 against 6.51) says
# they were measured at a slightly smaller effective budget, which is worth
# recording next to the number and is not worth another 45 minutes.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
. games/orbit/ai/runs/box-lock.sh
OUT=games/orbit/ai/runs/pimc-serving
BUDGET=3000; MAIN=1800; FOLLOWUP=1200; WORKERS=4; K=4
export PATH="$HOME/.cargo/bin:$PATH"

say() { echo "[$(date '+%H:%M:%S')] $*"; }

# WAIT ON THE QUEUE AHEAD, NOT JUST ON THE LOCK. The first attempt at this run
# died on 2026-09-13 at 12:39 with "the box was held for over 120 minutes",
# having measured nothing: the 120-minute claim limit was sized for the queue as
# it stood when the script was written, and by the time it ran a four-pool A/B
# was legitimately holding the lock for ~2.5 hours. The lock behaved correctly.
# That is the SILENCE BUG box-lock.sh's own header warns about -- an abort that
# looks like a decision and is really a timeout -- so the limit now has to cover
# the whole queue, not one run.
#
# The markers are waited on EXPLICITLY rather than left to the lock, because the
# lock is fair-by-race: every waiter retries every 20s and whoever wins the
# noclobber write goes next. This repair re-runs one contaminated pool of an
# already-concluded measurement and search-fixes is a live A/B, so letting the
# race decide would sometimes put 45 minutes of the cheap thing in front of the
# expensive one.
say "waiting for the runs ahead of this one"
waited=0
while [ ! -f games/orbit/ai/runs/search-fixes/search-fixes-done.marker ]; do
  sleep 60
  waited=$((waited + 1))
  [ "$waited" -ge 600 ] && { say "ABORT: search-fixes never finished"; exit 1; }
done
say "the queue ahead is clear"

claim_box "pimc-serving-repair" 480 || { say "ABORT: could not claim the box"; exit 1; }

report="$OUT/k$K/pool-1.json"
contaminated="$OUT/k$K/pool-1.contended.json"
if [ -f "$report" ]; then
  # KEPT, not deleted. The contended measurement is evidence about what
  # contention costs, and this campaign has already lost one run's worth of
  # that evidence by cleaning up after itself.
  mv -f "$report" "$contaminated"
  say "kept the contended pool 1 as $(basename "$contaminated")"
fi

say "re-running K=$K pool 1 with the box locked"
python -m games.orbit.tools.native_search_arena heuristic "$report" \
  --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
  --pool "development-ab-determinized-p1" --opponent-expert --via-observation \
  --workers "$WORKERS" --game-workers 1 \
  --determinization-period 0 --opponent-determinization-period 0 \
  --alphabeta --ab-worlds "$K" > /dev/null 2> "$OUT/k$K/pool-1.err"

python -c "
import json, pathlib

def depth_of(path):
    d = json.loads(pathlib.Path(path).read_text())
    total = count = 0
    for g in d.get('games', []):
        total += sum(g.get('ab_depth_by_seat', [0, 0]))
        count += sum(g.get('ab_searches_by_seat', [0, 0]))
    return d['arena']['pair_score'], (total / count if count else 0.0), d['seconds']

fresh = depth_of(r'$report')
print()
print('K=$K pool 1, same deals, same settings, box locked:')
print(f'  contended : score {depth_of(r\"$contaminated\")[0]:.4f}  depth {depth_of(r\"$contaminated\")[1]:.2f}')
print(f'  clean     : score {fresh[0]:.4f}  depth {fresh[1]:.2f}')
print()
print('The depth difference is what contention actually costs an equal-time arena.')
"

python -m games.orbit.tools.pool_arena_reports "$OUT/k$K"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/k$K/pooled.json"
say "K=$K repaired => $(python -c "import json;d=json.load(open(r'$OUT/k$K/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
date > "$OUT/repair-done.marker"
say "=== repair finished ==="
