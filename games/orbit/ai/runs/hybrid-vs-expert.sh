#!/usr/bin/env bash
# THE HYBRID: keep the strong half of the Expert, replace the weak half.
#
# Twelve generations of learned VALUE head never cleared the hand-written
# `state_value` leaf -- g004 reads 0.4375 against it at serving shape, and flat
# across a 12x budget range. That leaf is 213 lines of tuned domain knowledge,
# and eval tuning is the documented saturated lever in three sibling campaigns.
#
# But the PRIOR is the frozen part, and the 2026-09-11 audit measured it
# deciding 50.5% of moves outright. A learned prior beat it 0.6641 within the
# neural family. So this keeps the hand-written leaf and swaps only the prior.
#
# Why it should work where the value head did not: a policy head trains on the
# search's VISIT DISTRIBUTION, so it distills the Expert's SEARCH into the
# Expert's PRIOR. That is AlphaZero's improvement operator. The value head was
# only ever distilling OUTCOMES, which is imitation rather than improvement --
# it cannot exceed its teacher, and it never did.
#
# `--model-weight 0` makes the leaf purely hand-written. The search now SKIPS
# the model forward entirely at zero weight instead of computing it and
# multiplying by zero; verified value-preserving against the previous binary
# (identical deterministic results, 2.35x faster), which is what makes this
# measurable at equal TIME rather than handicapped by a wasted forward.
#
# Deals are the SAME pool namespaces as the full-neural run, so this is paired
# against it: same model, same opponent, same deals, and the ONLY difference is
# which evaluator scores the leaf. Full-neural read 0.2812.
set -u
REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../../.." && pwd)"
cd "$REPO" || exit 1
OUT=games/orbit/ai/runs/hybrid-vs-expert
CANDIDATE=games/orbit/ai/runs/policy-v1/model-policy/epoch-004.pt
BUDGET=3000; MAIN=1800; FOLLOWUP=1200; WORKERS=4; WEIGHT=1.0
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
say "candidate: HAND-WRITTEN state_value leaf + LEARNED prior (model-weight 0)"
say "opponent  the SHIPPED heuristic-leaf Expert"

for i in 1 2 3 4; do
  report="$OUT/pool-$i.json"
  if usable "$report"; then say "pool $i already complete"; continue; fi
  [ -e "$report" ] && say "pool $i: discarding an unusable report and re-running"
  say "=== pool $i starting ==="
  python -m games.orbit.tools.native_search_arena "$CANDIDATE" "$report" \
    --pairs 16 --budget-ms "$BUDGET" --main-action-ms "$MAIN" --followup-ms "$FOLLOWUP" \
    --pool "development-policy-vs-expert-p$i" --opponent-expert --via-observation \
    --workers "$WORKERS" --game-workers 1 \
    --determinization-period 0 --opponent-determinization-period 0 \
    --policy-prior-weight "$WEIGHT" --model-weight 0.0 > /dev/null 2> "$OUT/pool-$i.err"
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
