#!/usr/bin/env bash
# Is the neural line behind, or was tonight's model just small?
#
# The overnight policy model lost to the shipped heuristic Expert 0.2812 over 64
# pairs. That model is ONE 8-epoch run on 1536 games -- sized to validate a
# pipeline overnight, not to be strong -- so it cannot answer whether a NEURAL
# leaf can beat the hand-written one. It only says that this one does not.
#
# The league's own incumbent can. `state.json` records
# g004/model/epoch-006.pt at fixed_score 0.75 and timed_score 0.8125, under the
# evaluation profile `proxy-250-150-100-w4-g3` -- a 250 ms turn, which is about
# a twentieth of serving's compute, screened at 8 pairs (+/-0.21). The
# 2026-09-11 audit flagged that the proxy's ordering against serving shape was
# never established.
#
# So this measures the campaign's best artifact at the shape players actually
# get: equal time, 3000 ms split 1800/1200, four workers, both seats coherent.
# It answers two questions with one run -- whether a campaign-scale neural model
# beats the shipped Expert, and whether the league's headline 0.81 survives a
# real budget.
#
# No policy prior: g004 predates the policy head and carries none.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/league-g004-vs-expert
CANDIDATE=games/orbit/ai/runs/neural-league-v2/g004/model/epoch-006.pt
BUDGET=3000; MAIN=1800; FOLLOWUP=1200; WORKERS=4; WEIGHT=0.0
mkdir -p "$OUT"

say() { echo "[$(date '+%H:%M:%S')] $*"; }

# Completeness AND shape, because a killed run leaves a report that is
# non-empty, reads "complete": false, and would otherwise be skipped forever.
usable() {
  python -c "import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: sys.exit(1)
sys.exit(0 if (d.get('complete') is True and d.get('arena')
  and d.get('budget_ms')==int(sys.argv[2]) and d.get('workers')==int(sys.argv[3])
  and abs(float(d.get('policy_prior_weight', -1)) - float(sys.argv[4])) < 1e-9
  and float(d.get('opponent_policy_prior_weight', -1)) == 0.0) else 1)" \
  "$1" "$BUDGET" "$WORKERS" "$WEIGHT" 2>/dev/null
}

say "=== learned-prior screen, equal time at serving shape ==="
# Each arm's checkpoints are chosen by development log-loss, the same way the
# league selects, rather than by taking the last epoch.
say "candidate $CANDIDATE (league incumbent, no policy head)"
say "opponent  the SHIPPED heuristic-leaf Expert"

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i starting ==="
  python -m games.orbit.tools.native_search_arena "$CANDIDATE" "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-league-g004-vs-expert-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --policy-prior-weight "$WEIGHT" > /dev/null 2>&1
  if usable "$report"; then
    python -c "import json,sys;d=json.load(open(sys.argv[1]));a=d['arena'];print('pool',sys.argv[2],'score',round(a['pair_score'],4),a['pair_ci95'],'wins',a['wins'],'losses',a['losses'],'secs',round(d['seconds']))" "$report" "$i"
    python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
      --accept-pairs 64 --output "$OUT/pooled.json" > /dev/null 2>&1
    say "running estimate: $(python -c "import json;d=json.load(open(r'$OUT/pooled.json'));print(d['pair_score'],d['bootstrap_ci95'],'over',d['pairs'],'pairs')" 2>/dev/null)"
  else
    say "pool $i produced no usable report"
  fi
done

say "=== pooled result ==="
python -m games.orbit.tools.pool_arena_reports "$OUT"/pool-[0-9].json \
  --accept-pairs 64 --output "$OUT/pooled.json"

# What the prior actually COST, which the score alone cannot show.
say "=== per-seat throughput: what the extra forward per node cost ==="
python -m games.orbit.tools.calibrate_fixed_sims "$OUT"/pool-[0-9].json 2>&1 | tail -20
date > "$OUT/prior-screen-done.marker"
say "=== prior screen finished ==="
