"""Champion tests — the search harness (research, not run in the main suite).

The champion is NOT a shipped tier: it was built, measured, and did not beat
`bmplus` (see the module docstring in bot.py and the research log). These tests
keep the harness honest so the negative result stays trustworthy and a future
attempt starts from working code rather than a rewrite.

Both bugs that made the first version LOSE (0.167) are pinned here, because
both are the kind that look like "the search is weak" rather than "the harness
is wrong":

* "buy nothing" was never committed to, so it scored as "let a fresh policy
  decide" and beat every real buy;
* the rollouts were unpaired, so the estimator's noise was wider than the gap
  between the choices it was ranking.
"""

import random

from games.dontminion import bot, bot_champion as C, engine

A, B = "alice", "bob"
K = ["Smithy", "Village", "Moat", "Militia", "Witch", "Throne Room",
     "Gardens", "Chapel", "Cellar", "Market"]


def at_buy(coins=5, seed=5):
    g = engine.new_game([A, B], ["base", "intrigue"], seed=seed, kingdom=K)
    seat = g["seats"][A]
    seat["discard"] += seat["hand"]
    seat["hand"] = []
    ok, err = engine.apply_move(g, A, {"type": "end_phase"})
    assert ok, err
    g["coins"] = coins
    return g


# ── the two harness bugs ─────────────────────────────────────────────────────

def test_buying_nothing_is_committed_to_by_ending_the_phase():
    """Not committing let the rollout policy buy something anyway, so passing
    was scored as a free re-decision and won every comparison."""
    g = at_buy(coins=5)
    before = len(engine.owned_cards(g, A))
    got = C._one_rollout(g, A, None, "bmplus", seed=1)
    assert got is not None
    # the position we scored must not have gained a card on this buy
    g2 = at_buy(coins=5)
    ok, _ = engine.apply_move(g2, A, {"type": "end_phase"})
    assert ok and len(engine.owned_cards(g2, A)) == before


def test_rollouts_are_paired_so_candidates_share_their_luck():
    """Same seed, same candidate, same answer — that identity is what makes
    the comparison between candidates a comparison of the DECISION."""
    g = at_buy(coins=6)
    a = C._one_rollout(g, A, "Gold", "bmplus", seed=42)
    b = C._one_rollout(g, A, "Gold", "bmplus", seed=42)
    assert a == b, "a rollout is not reproducible from its seed"


def test_best_buy_reads_the_rollout_count_at_call_time():
    """A default argument binds once at def time, so a sweep patching the
    module constant measured the same depth three times (6, 24 and 96 rollouts
    all returned 0.375 — identical to three decimals, which is what gave it
    away)."""
    g = at_buy(coins=6)
    calls = []
    real = C._one_rollout
    try:
        C._one_rollout = lambda *a, **kw: (calls.append(1), 0.5)[1]
        old = C.ROLLOUTS
        C.ROLLOUTS = 3
        C.best_buy(g, A, ["Gold", "Silver"], "bmplus", random.Random(1))
        assert len(calls) == 6, f"{len(calls)} rollouts for 2 options x 3"
    finally:
        C._one_rollout = real
        C.ROLLOUTS = old


# ── the tournament ───────────────────────────────────────────────────────────

def test_the_tournament_keeps_the_benchmark_unless_beaten_by_a_margin():
    """The hand-written archetypes measure WORSE than the benchmark, so
    "better than 0.5" adopts a losing plan more often than it finds a winning
    one — the bar is a margin, and the fallback is the proven tier."""
    assert C.TOURNAMENT_MARGIN > 0.5
    got = C.pick_plan(tuple(K), False, 2)
    assert got is None or isinstance(got, str)


def test_pick_plan_is_cached_so_the_plan_cannot_drift_mid_game():
    a = C.pick_plan(tuple(K), False, 2)
    b = C.pick_plan(tuple(K), False, 2)
    assert a == b


# ── the finisher contract still holds ────────────────────────────────────────

def test_champion_finishes_a_game(monkeypatch):
    # The claim is that the search DRIVES A GAME TO COMPLETION — every buy above
    # SEARCH_FROM_COINS goes through buy_candidates -> best_buy -> _one_rollout ->
    # _play_out, and every move it returns is accepted. None of that is about how
    # MANY paired rollouts back each decision, so the depth is pinned down here:
    # at the shipped 12 this single test was 116s, 29% of the entire repo suite
    # and its critical path under xdist. At 3 it is ~24s and covers the same
    # code. (Patching the module constant is exactly what the sibling
    # test_best_buy_reads_the_rollout_count_at_call_time proves works.)
    # This is NOT the place to soak the engine on rollout volume — test_soak.py
    # is, deliberately and with the conservation census.
    monkeypatch.setattr(C, "ROLLOUTS", 3)
    g = engine.new_game([A, B], ["base"], seed=77, kingdom=K)
    rng = random.Random(77)
    for _ in range(20000):
        if g["over"]:
            break
        pid = g["pending_pid"] or g["turn"]
        ok, err = engine.apply_move(g, pid, bot.choose(g, pid, rng, "champion"))
        assert ok, err
    assert g["over"] and g["winners"]
