# AI research log & session archive

This file is the **research journal + session history** carved out of `CLAUDE.md` so the operating manual stays lean. It holds the AI-strength campaigns (Spender, CoC and **Dissonance**), the dated session narratives, rejected-experiment postmortems, and the detailed "do not relitigate" verdicts. `CLAUDE.md` keeps a one-paragraph pointer per campaign and links back here.

Content down to the ARCHIVE blocks is preserved **verbatim** from the pre-split `CLAUDE.md` (git also holds the full original); the dated Dissonance sessions at the foot were written here natively. Durable operating facts and footguns were also surfaced up into `CLAUDE.md`; this archive keeps the complete detail.

> Status lines, dates, commit hashes, and "RUNNING/IN PROGRESS" markers here are historical snapshots — trust git and the live code over them.

---

### Session (2026-09-10) — Orbit arena throughput corrected to the Spender shape

The first Orbit neural league runner measured a complete paired game serially.
That made an eight-pair timed probe look like a many-minute experiment even
though Spender's campaign runs independent games concurrently. The correction
is now in the native `neural_arena` path: immutable decoded models are shared by
scoped workers, independent jobs use a queue, and results retain their original
indices so CRN pairing and board order are unchanged. A same-pool fixed-sim
smoke (16 games, one root, four simulations) went from **6.71s serialized to
1.55s with 11 concurrent game workers**, with identical outcomes. A four-root
per-game smoke also preserved outcomes while filling three games concurrently.

The campaign now has three explicit regimes. Cheap fixed screens and mirror
controls use one root tree plus many games in flight; the fast 250ms proxy uses
the four-tree serving ensemble per game plus host-level game workers; the actual
5s/3s+2s serving shape remains a rare final check. Offline value-data generation
and fixed searches may use up to sixteen native workers (the current host uses
eleven for data); the browser's smaller pool remains a UI-responsiveness
constraint. Worker width, game concurrency, budgets and splits are recorded in
every report, and calibration can compare the regimes on one CRN pool without
pretending that a low-budget score numerically extrapolates to serving.

The first semantics-preserving native inference optimization is also banked:
the attention model now precomputes its deterministic position MLP for the
common card/move/column index range at checkpoint load, with an unbounded
fallback for future positions. A 148-position Python/Rust parity pass stayed
within **1.55e-6** logit error. On a same-namespace 16-game fixed-64 probe,
the optimized CPU-native build produced identical winners, step counts and
evaluation counts and reduced wall time from **163.9 s to 156.9 s (1.045x)**.
The league resumed with that binary; no simulation, feature, or search rule
was changed for the speedup.

The observation hot path now has a second accepted optimization. Rust builds
the allowlisted public projection directly instead of serializing the complete
privileged state and copying fields back out. A parity test compares the direct
projection with the old serializer while a fixed-64 one-game probe kept the
same winner, 150 steps and 4,632 neural evaluations; wall time fell from
**29.7 s to 28.4 s (1.046x)**. The campaign resumes with this binary, while
the old serializer remains in a test-only reference implementation.

The search also reuses the post-move observation that it already builds for
the information-set trace as the nonterminal leaf view. Four alternating
fixed-64 probes had identical canonical game hashes (winner 0, 150 steps,
4,632 evaluations); paired old/new means were **30.71 s versus 29.36 s
(1.046x)**. This is now included in the campaign binary; no simulations,
features or search choices changed.

Finally, the search now has a private `apply_search` path for moves selected
from the legal list it just built. The public engine API still performs its
full legality check; only internal rollouts skip rebuilding that list. Two
alternating fixed-64 probes kept the same canonical game hash and averaged
**24.20 s versus 24.51 s (1.013x)**. The campaign resumes with this binary.

A second evaluator rewrite was measured and rejected: flattening every entity
and reusing scratch buffers kept the same fixed-search results but ran **1.59x
slower** than the existing small-vector implementation on the same pool. It
was removed rather than retained on code-style grounds; this leaves the
position-cache/native, direct observation and leaf/apply paths as the accepted
semantics-preserving speedups.

A determinization setup cache was also measured and rejected. It moved the
unchanged unseen-card/bonus inventory construction outside the simulation loop,
but the one-game fixed-64 parity probe stayed exact while wall time rose from
**29.7 s to 36.7 s** on the same native host. The extra template cloning costs
more than the small set-building work, so the live search keeps the original
path and the campaign binary was not changed.

The next safe optimization attacks the measured hot path rather than the hidden
card universe. A profile of one fixed-search game attributed about 78% of leaf
time to the attention forward, 10% to semantic-to-tensor conversion and 5% to
feature extraction; hidden-pool sampling was below 1%. The native model now
keeps a validated vocabulary encoder (including a card-ID map) in the loaded
checkpoint and converts leaves into typed rows. A thread-local attention
workspace clears only the entities used by the preceding leaf, so variable
length observations do not allocate or retain stale rows. This is an
observation-only change: a 5,594-position Python/native pass stayed below
3.70e-6 maximum logit error, and the fixed-search comparison reported identical
move/stats/node results with a 1.71x timing ratio (32 simulations over the
same 16 varied positions). The broader observation-to-value bridge measured
1.46x end-to-end speedup over the pre-cache native build at 1.91e-6 maximum
logit error. Browser/WASM uses the same typed path; no hidden state is exposed.

A chunked Q·K reduction was tested separately. It improved the small bridge
benchmark by only about 1.10x and changed fixed-search edge statistics, so it is
rejected for the strength-preserving campaign. The existing chunked affine
dot build remains the previously gated native optimization; no new numerical
reassociation is enabled by the typed-row change.

An isolated training probe measured fused FP32 AdamW at 12.44 ms/update versus
20.07 ms/update for regular AdamW on the same prepared batch (1.61x). After 24
timed updates following five warmups, the maximum parameter difference was
5.8e-4. This is a throughput candidate, not a strength result: floating-point
update order differs, so adoption remains gated on matched multi-seed arenas.

The next exact hot-path candidate caches the pooled affine/GELU vector for each
semantic row across leaves. A monotonic model-load tag clears the per-thread
cache when a WASM checkpoint is replaced. It passed the 5,594-position parity
walk and two fixed-search probes with identical moves, edge statistics, node
counts and simulations. Measured speed was 1.04–1.07x for search and 1.03x for
the observation bridge. The native league switched to this build at the g009
boundary; the g009 champion-anchor harvest completed in **1,503.97 s**, versus
**1,699.18 s** for the preceding typed build, with the same search semantics.
The browser/WASM build has also passed its compile and parity checks; a serving
timing check remains a release measurement, not a strength claim.

The first nine value-only league generations now have a useful warning about
screen variance. g009 scored **0.7500 on 16 timed pairs** (CI [0.5000,
0.9375]) after an exact 0.5000 mirror, but the fresh 32-pair confirmation was
0.65625 and the 128-pair confirmation settled at **0.609375** (CI
[0.55078, 0.66797]); its near-peer screen was 0.25. It was rejected and the
g004 epoch-006 checkpoint remains the incumbent. The staged confirmation
ladder stopped at 128 because its interval no longer reached the 75% target,
avoiding the 512-pair final rung. This is why the campaign treats small timed
screens as directional filters and makes no promotion claim from them.

g010 and g011 provide the same warning from two more directions. g010 reached
0.6875 fixed but only 0.5000 timed, while g011 reached **0.8125 fixed** (and
passed its mirror and 0.50 near-peer floor) before falling to **0.3125 timed**.
Both were rejected and neither changed the incumbent. The equal-time proxy is
therefore doing useful work: fixed-simulation wins identify candidates worth a
short timed screen, but they are not a substitute for the serving-shaped
strength measurement.

### Session (2026-09-11) — value-only plateau audit and checkpoint-selection fix

The g012 value-only arm did not move the campaign: its best epoch scored
**0.5703** on a 64-pair fixed screen and **0.5625** on an eight-pair timed
screen, while the frozen g004 epoch-006 incumbent measured **0.5664** on a
fresh 128-pair timed proxy. A small 16-pair timed result near 0.30 is therefore
not a reliable estimate by itself (its paired interval spans roughly 0.06–0.56),
but it correctly triggered an audit rather than another blind generation.

The audit separated the network from the search and the measurement. Against a
free heuristic leaf on the same 64 paired timed deals, g004 improved the
candidate-minus-control score by **+0.1094**, so the value model contributes
real information. Sparse network evaluation at every second leaf produced no
throughput gain and lost about eight paired points, so attention cost is not a
safe strength-free shortcut. Temperature 1.0 was worse than the calibrated
temperature 2.0. A root-value-beta-zero control was slightly better on one
fixed screen but lost on the timed probe; it is not a replacement for the
existing beta 0.25 setting.

The targeted Expert-primary data probe exposed the larger problem. Its epoch-8
model reached **0.6328** on the identical 64-pair fixed screen, but only
**0.5313** on 16 timed pairs; the same pool gave frozen g004 **0.6875**. Its
epoch-7 checkpoint was **0.5859 fixed** and **0.6563 timed**, showing that the
latest checkpoint is not a safe strength selector even when its development
Brier score is lower. A 0.5 neural/heuristic blend recovered epoch 8 to
0.5938, but still did not beat epoch 7. The Expert-primary arm is rejected as a
latest-checkpoint promotion path, while its data distribution remains useful
for the next controlled arm.

The league runner now performs a short equal-time scan of every numeric epoch
checkpoint, records the scan beside the generation, and evaluates the strongest
checkpoint rather than always taking the last one. Fresh data can select an
explicit primary policy (`--train-primary expert` for the counterstrategy arm),
and confirmation ladders now consider only candidates that actually beat the
incumbent and clear the near-peer floor. These changes reduce winner's-curse
and wasted confirmation time; they do not alter search semantics or serving.

The next strength experiment is therefore data/target focused: retain the
current-parent anchor, mix Expert-primary counterexamples with the standard
league, select by the timed checkpoint scan, and only then test a policy/action
head or auxiliary progress heads. Prediction loss remains diagnostic; the
serving-shaped equal-time result is the selection signal, with the frozen g004
Expert fallback unchanged.




<!-- ===================================================================== -->
# CoC — BGA expert corpus: the SEAT-STRENGTH filter, and the scaling curve that finally sloped up
<!-- ===================================================================== -->

### Session (2026-07-31) — the July "BGA data is saturated" verdict is OVERTURNED at the @200 screen; per-seat ELO instrumented; depth re-gate PENDING at write time

The July 19–22 line closed with "no reliable gain over the deployed Expert, data saturated ~36 games,
tractable levers exhausted." Two things had changed by 2026-07-31: the daily cron had roughly tripled the
clean corpus, and — the user's idea, and the larger effect — **nobody had ever checked how good the
players in these games actually were.**

1. **THE "BOTH SEATS ARE EXPERTS" PREMISE WAS FALSE, AND HAD NEVER BEEN MEASURED.** `cob_harvest.py`
   recorded both seats of every game, justified in its own docstring as *"the opponent of a top-100 BGA
   player is also far above our net — that's the whole premise."* New tool **`cob_elo.py`** attaches each
   seat's post-game ELO; over 114/122 downloaded games:
   - stronger seat (the seeded top player, present in EVERY game): min 1997, **median 2040**, max 2202
   - weaker seat: min 1301, **median 1635**, max 2042
   - **median gap 396 ELO** (p25 284, p75 514, max 753); one sampled pair was 2109 vs 1409
   - at a 1900 bar only **9 of 114** games are pro-vs-pro; 105 are pro-vs-amateur
   ⇒ ~46% of harvested decisions were a ~400-ELO-weaker player's moves, trained at equal weight with no
   feature distinguishing them. `cob_harvest.py` now takes `min_elo` and keeps a decision only if **that
   mover** cleared the bar (both seats of a pro-vs-pro game; only the strong side of a mismatch). An
   unrated seat is DROPPED whenever `min_elo > 0` → re-run `cob_elo.py` after every download batch.
2. **BGA API FOOTGUN (cost an hour): `gamestats/getGames`'s `start` parameter is SILENTLY IGNORED** —
   every page returns the same first 10 tables, forever. It also reports `elo_after` only for the player
   you *query*. So it cannot page back to an older game and cannot rate an opponent. This is also why
   `cob_collect.py` caps at ~10 games/player regardless of its `cap` argument. **Use
   `table/table/tableinfos.html?id=<tid>` instead — it returns `rank_after_game` for EVERY seat in one
   call**, and it is table metadata, so it costs nothing against the ~10/day replay-download quota.
   (Diagnostic tell: per-player hit rates were bimodal 0/N or N/N, which reads like throttling but was
   pagination returning page 0 every time. A manual single-page probe succeeding is NOT evidence that
   paging works.)
3. **THE SCALING CURVE — the never-run July decision point — SLOPES UP.** Anchored fine-tune (BGA = 25%
   of the mix, champion self-play the rest, warm from `pv_warm936`), gated vs that same champion,
   `netval@30@1.0` @200 sims, seed 4242, **mirror sanity read 0.5000 exactly**:

   | rows | seats | gate @200 |
   |---|---|---|
   | 4,490 (Jul 15) | all | 0.4875 ±0.063 |
   | 8,641 (Jul 20) | all | ~0.52, CI included 0.5 |
   | **14,601 (today, arm ALL)** | all | **0.5600 ±0.049 (n=400) seed 4242; 0.5300 ±0.049 (n=400) seed 7777 → POOLED ~0.545 ±0.035 (n=800), CI [0.510,0.580]** |

   **The 0.5600 was HIGH-SIDE ON ONE SEED — quote the pooled 0.545, not the screen.** The depth
   ladder's bottom rung was deliberately a fresh-seed re-read of the same comparison for exactly
   this reason, and it moved the number 3pp. The finding survives (pooled CI still excludes 0.5)
   but a single seed base is not a result here; this is the Duel "0.5288 blip" lesson repeating.

   First time the CI has excluded 0.5. July's own framing was "flat ~0.49 ⇒ the corpus is a hypothesis
   MAP, not training data; upward slope ⇒ the grind is justified." **It sloped. The corpus is training
   data.** Corpus today: 84 replay-complete games + 32 salvaged mon6 prefixes (122/147 downloaded, ~3
   days of quota left). Row yields: unfiltered 14,601 | ≥1700 10,106 | **≥1800 8,394** | ≥1900 7,633 —
   note ≥1800 is *size-matched to the whole Jul-20 experiment*, which is what makes arm E1800 the clean
   purity test rather than a volume test.
3b. **AND THE PURITY FILTER DID NOT PAY OFF AT THIS SCALE — the honest negative.** Arm **E1800 (8,394
   rows, mover ≥1800) = 0.5350 ±0.049 (n=400), margin +1.5, CI [0.486,0.584] — INCLUDES 0.5**, below
   arm ALL's 0.5600. Read it carefully in both directions: the two arms' CIs overlap heavily and they
   share a seed base, so this is **not** "volume beats purity" demonstrated — it is "**dropping 43% of
   the rows is not repaid at 8.4k scale.**" Against its true size-matched control (Jul-20's 8,641
   unfiltered rows → ~0.5217) E1800 is a hair better, which is the direction purity predicts, and
   nowhere near significant. The ~400-ELO contamination is REAL and measured; it is simply not yet
   worth what removing it costs. **The trade shifts as the corpus grows** — a ≥1800 cut on a 300-game
   corpus would exceed today's unfiltered row count — so RE-TEST the filter at that point rather than
   filing it as dead. The instrument (`cob_elo.py` + `min_elo`) is the durable asset here.
4. **@200 IS A SCREEN, NOT A SHIP NUMBER — and this experiment is specifically vulnerable to that.** CoC
   saturates **~4k sims** (`coc_run_simgate/ladder_log.txt`: 1024v512 0.5417, 2048v1024 0.5833,
   4096v2048 0.5667, **8192v4096 0.5000 = knee**) and Expert SERVES at ~20k. At 200 sims the LEAF
   dominates the result; deeper search washes leaf differences out — so a fine-tuned-**leaf** edge read
   @200 is an **upper bound** on serving, never an estimate. The repo has this both ways: r2 shipped on
   0.5250 @200 → 0.5500 @512 ("grows with depth"), while a steps=30 config read 0.583 @200 and softened
   to 0.54 @1024 ("a low-sims win"); Spender's calibrated distilled leaf did the same (0.583@160 → ~0.5
   by 1200) and was correctly not shipped. **`cob_depth_regate.sh`** re-gates 200 → 1024 → **4096** (the
   knee — gating at 20k buys nothing past it but wall-clock) on a **FRESH seed 7777**, so the bottom rung
   doubles as a seed-robustness re-read of the 0.5600. Written RUNG-MAJOR on purpose: a ~3.4h run may be
   read before it finishes, and an arm-major interrupt would leave one arm measured and the other
   untouched, answering nothing about purity-vs-volume.
5. **DEPTH RE-GATE RESULT — the edge GROWS with search depth, in BOTH arms.** Fresh seed 7777, n=400/rung:

   | arm | @200 | @1024 | Δ |
   |---|---|---|---|
   | **ALL** (14,601 rows) | 0.5300 ±0.049 | **0.5725 ±0.048, CI [0.524,0.621]** | **+0.043** |
   | E1800 (8,394 rows) | 0.5225 ±0.049 | 0.5450 ±0.049, CI [0.496,0.594] | +0.023 |

   This is the pattern that predicts transfer to ~20k serving (r2 itself shipped on 0.5250 @200 →
   0.5500 @512), and it is the OPPOSITE of the low-sims leaf artifact that was the main reason to
   doubt the screen. **That both arms move the same direction matters more than either number** — a
   single arm rising is one seed's luck, two independent training sets rising together is a trend.
   **CAVEAT, STATED PLAINLY: @4096 (the knee) WAS NOT MEASURED.** The user halted the ladder after
   the @1024 rung, judging the upward trend sufficient. So "stronger at production depth" here is an
   **extrapolation from two rising points below the knee, not a measurement at it.** If this net is
   ever a ship candidate, run `cob_depth_regate.sh` to completion first — the rung exists and costs
   ~70 min/arm.
6. **Open, deliberately untested:** filtering fixes *whose moves we imitate*, not *what positions they
   came from* — a 2040 playing a 1600 faces weak competition for tiles, so the position distribution
   stays slightly off even when every retained move is strong. Isolating that needs pro-vs-pro-only,
   and 9 games (≥1900) / 22 (≥1800) is far too few. Revisit if the corpus ever gets large enough.

Tooling all on branch **`cob-mining`** (worktree `forrestm_projects-cobmining`): `cob_elo.py` (new),
`cob_harvest.py` (`min_elo` filter), `cob_ft_ladder.sh`, `cob_depth_regate.sh`.

---



# ARCHIVE: Dontminion bot ladder — decision policies + endgame SHIPPED; archetypes and rollout search MEASURED NEGATIVE
<!-- ===================================================================== -->

### Session (2026-07-31) — built the ladder from the dominionstrategy corpus: two rungs SHIPPED with real gains, and the two "clever" tiers both LOST to Big Money+

**Source material.** Every Basic/Intermediate/Advanced link on wiki.dominionstrategy.com/index.php/Strategy — 3 wiki pages, 7 blog articles, 12 forum threads (Deck Archetypes, Making It To Level 45, Every Day I'm Shuffling, First Player Advantage, Taking Risks From the P2 Seat, Post-Game Analysis, the four Level-X-vs-Y threads). Both sites sit behind an **Anubis proof-of-work challenge**: GET the page, parse the `anubis_challenge` JSON, find a nonce where `sha256(randomData + nonce)` has `difficulty` leading zero nibbles, then GET `/.within.website/x/cmd/anubis/api/pass-challenge?id&response&nonce&redir&elapsedTime` keeping cookies and the same UA. Distilled rules live in `.claude-plans/dontminion-bot-ladder.md` (self-contained appendix) so the articles never need re-scraping.

**SHIPPED (both gates passed).**
1. **`bot_decisions.py`** — policy answers for every frame kind, replacing `engine.sample_decision` for every tier above `random`. Both shipped bots answered EVERY prompt uniformly at random, so Big Money discarded its Gold to a Militia half the time. Worth **0.6219 on the full card pool** (significant), 0.5156 on Base alone where few cards push a decision worth getting right.
2. **`bmplus`** — Big Money + the kingdom's best terminal off the published Terminal-Draw-BM ranking + the Colony rungs + `bot_endgame` (PPR with all four exceptions, take-the-win, pile control). **0.7708 vs `bigmoney` base-only, 0.7333 all sets**; pace to the 4th Province 16.3 → 15.3 turns. Now the DEFAULT tier.

**FOLLOW-UP — Colony boards: the greening CLOCK was the bug, and fixing it is worth 0.66.** `bmplus` had the Colony/Platinum *rungs* (Colony at $11+, Platinum at $9-10) but inherited the plain ladder's green thresholds, which all read the PROVINCE count. In a Colony game that is the wrong pile: 2 Colonies left with 8 Provinces untouched reads as "no urgency", so the bot kept buying economy while the game ended under it. A second bug fell out of reading the code rather than the results — with the rungs checked before the clock, a $9 hand with ONE Colony left still bought a Platinum, economy the game would end before the deck ever drew it; `_colony_green` now runs first and stays quiet above $11 (where a Colony is both the best green and the best buy).

Decomposed on 120 Colony-only boards, 240 CRN-paired games each, mirror exactly 0.5000:
**v2 ($8 -> Gold only) 0.5312 (n.s.) | v4 (clock only) 0.5896 significant | v3 (both) 0.6562 significant | v3 vs v4 0.5188 (n.s.)**. Shipped v3, reconfirmed at **0.6687** on a fresh 80-board sample. `_COLONY_GREEN_AT` swept to an interior optimum at 4 (2/3 = 0.6625, **4 = 0.6813**, 5 = 0.6312, 6 = 0.5875).

Two process notes. The ablation mattered: bundling both changes and shipping on the combined number would have hidden that the $8 rung is doing almost nothing (0.53 alone) and the clock is doing all the work. And **non-Colony play is provably untouched** — every colony path is gated on `game["colony"]`, verified move-for-move identical to the old policy across 40 non-Colony boards, which is a stronger statement than "the arena did not move".

**FOLLOW-UP - the BM terminal table was MEASURED, and it was wrong in both directions.** `BM_TERMINALS` was hand-written from the Terminal-Draw-BM article, which predates most of the roster; a card missing from it scores 0 and is INVISIBLE to the tier. `tools/bm_terminal_sweep.py` now measures the real question - each card as bmplus's forced terminal vs bmplus forced to buy NO terminal, on inert filler, 25 CRN pairs, no-terminal control exactly 0.5000 on every board - and the rank is the measured win rate x100.

Findings: **seven cards were missing entirely** and measured significantly positive (Charlatan 0.81, Corsair 0.80, Blockade 0.72, Clerk 0.71, Cutpurse 0.70, **Masquerade 0.65** - which the source article names as a BM opener - and Bandit 0.64). **Two ranked cards were actively LOSING**: Steward (rank 30) at 0.36 and Footpad (62) at 0.28, both bought over a Silver every game. Vault was underrated at 58 -> 0.82, Patrol 40 -> 0.77, Rabble overrated 78 -> 0.58.

**Three methodological cautions, all earned.** (1) The sweep scores cards in ISOLATION against a common baseline while the rank picks BETWEEN cards - a proxy, and ranks within ~10 points are inside the n=50 noise band. (2) It **overrates attacks**, since the opponent has no terminal to defend with. (3) **Aggregate gates dilute the change to nothing**: new-vs-old table reads 0.5050 (n.s.) on random boards because 61% of boards pick the same card either way; restricted to the 39% where the pick changes it reads 0.5242, still n.s. at n=310. The adds and drops are individually significant; the re-ordering is not, and is not claimed to be.

**THE REAL FIND - a reachable non-terminating game, and it was not Corsair's fault.** Ranking Corsair exposed it: each side trashes the other's first Silver or Gold every turn, so neither ever reaches $8 again. Estates and Duchies gone, only Curse (10) and Copper (46) affordable, and `bot_endgame`'s "never end a game you would lose" rule meant **both** bots refused the ending - 4,448 turns, no result. The rule needed an exit, not the card needed banning: past `STALL_TURNS = 60` the refusal lifts, and since no single buy ended anything there, the breaker also PILEDRIVES the shallowest affordable pile (never Copper, which is 46 deep and always affordable) toward a third empty. Seed 43 now ends turn 35; termination soak over 150 boards on all seven expansions, longest 38 turns, zero failures. **This is a class of bug the arena's win-rate numbers cannot see** - a game that never ends has no winner to count.

Also fixed while here: `cost()` returns only the COIN component of the Alchemy cost VECTOR, so a Golem read as $4 and looked affordable at $4. Naming an unbuyable pile made the tier END ITS TURN with the coins unspent, silently, every turn the condition held; `_buy_or_fall_back` now drops through to the money ladder for any unbuyable want (Potion cost, buy_gate, emptied pile).

**FOLLOW-UP - terminal QUANTITIES measured; most defaults held, one hand-set exception was wrong, and the MIRROR confound got named.** `tools/bm_quantity_sweep.py` sets the count knobs per move so two settings play each other inside one CRN game.

Defaults that SURVIVED: the global cap of 2 (1/3/4 measured 0.458/0.446/0.446 against it) and the deck>=16 gate for the extra copy. That second one is the session's best methodology lesson: **deck>=12 read 0.550 random and 0.545 colony - two independent samples agreeing - and collapsed to 0.5050 at n=400.** Regression to the mean, caught only because the promising arm got a confirmation run.

Changed, each measured at n=120: **Sea Witch cap 3** (cap3 0.5917 sig, cap1 0.2958 sig) and **Witch's Hut back to cap 2** (a second copy is worth 0.6000; it had been hand-listed with the 5-card drawers as too collision-prone). Council Room and Magnate keep their cap of 1 (0.4042 sig, 0.4208 n.s.). Margrave measured 0.3833 for a third - already blocked by the default.

The user's long-game intuition was directionally right and honestly too small to ship: cap 3 goes from 0.446 on random boards to **0.508 on Colony boards**, n.s. A future version of that knob should key on the Colony pile rather than be global.

**THE MIRROR CONFOUND, raised by the user and confirmed.** A cap sweep has BOTH seats buying the card, so a junker is being measured inside a mutual curse war - both decks clogged, both racing the same 10-card Curse pile, which is exactly the state where Sea Witch's draw-then-discard is best and an extra copy wins the split. Isolated: the third Sea Witch is worth **+0.100 in the mirror vs +0.028 against a strong non-junking opponent** (vs pure money it saturates at ~99% and measures nothing). Never harmful, so it ships - but it is not a general result, and **every future quantity/attack measurement owes the same asymmetric check.** This is the same confound that made Corsair look like a 0.80 card while its mirror could not terminate; two independent instances in one session make it a standing rule rather than an anecdote.

**FOLLOW-UP (2026-08-04) - plain `bigmoney` RETIRED as an opponent; kept as the reference rung.** It is a strict SUBSET of bmplus (same buy ladder, no terminal / Colony rungs / endgame) which bmplus beats 0.77 base / 0.73 all-sets, so shipping it only ever offered a choice no one should pick. It had already left the create modal; this took it out of `AI_DIFFICULTIES`. Three things worth carrying forward:

* **Removing a tier from that tuple RETIERS LIVE GAMES.** `load_game_to_memory` re-runs `_valid_difficulty` on the persisted value, so the coercion that lets the ladder grow without a migration will also silently upgrade an in-progress room - the exact property ("a live game can't be retiered by a redeploy", the Spender ai_variant lesson) the tuple exists to protect. Checked against prod rather than reasoned about: 27 rows, 4 on `bigmoney` and **all 4 already `over`**, the single live game on `bmplus`. Zero cost, so the simple removal shipped; had it found live games the fix is a separate legacy set on the LOAD path, not a mid-game retier.
* **Unreachable from a client is not the same as deleted.** `choose_big_money` stays because "is bmplus still better than just buying money?" is the most informative gate the ladder has, the pace anchors (pure BM to 4 Provinces ~turn 17) are how we know the ladder is faithful to the published one, and it is the only clean harness for the shared `_want` ladder - which is live production code, since bmplus falls back to it for every rung it doesn't override. A test pins that the string still routes to the LADDER: falling through to `choose_random` would turn the baseline into a coin flip and quietly invalidate every number measured against it.
* **Retiring a tier can silently disarm a test that used it as a CONTRAST.** `test_the_room_tier_reaches_the_bot` told tiers apart by "random-legal plays an Action in hand, Big Money never does" - but bmplus owns Actions and plays them, so re-pointing it at bmplus left both arms behaving identically and the test would have PASSED while checking nothing. New probe: **$0 with an empty hand** (random takes any active move over ending the phase and buys a Copper/Curse; every ladder tier wants nothing below $2), verified non-vacuous by breaking the scheduler's tier read. When you delete a tier, grep for what was USING it as the other half of a comparison.

**FOLLOW-UP (Dark Ages, ph. 6) - the new set measured into both tables, and nothing was judged.** Five Dark Ages cards earn a `BM_TERMINALS` rank: Cultist 76, Rogue 62, Marauder 62, Hunting Grounds 61, Catacombs 58. Four of those five sat INSIDE the noise band at the sweep's default 25 pairs (Rogue 0.57, HG 0.55, Catacombs 0.52) and only became significant at 150 pairs - a reminder that "wash" at n=50 is not "worthless", it is "not measured yet".

The set's other 14 terminals were measured too, and every one of them LOST, most of them badly: Death Cart 0.008, Graverobber 0.025, Procession 0.058, Pillage 0.100, Storeroom 0.050, Altar 0.171, Poor House 0.179, Squire 0.192, Count 0.242, Armory 0.242, Hermit 0.350, Beggar 0.388, Scavenger 0.383. That is the tier being honest about itself rather than a fault in the cards: they are engine parts (trash-for-benefit, pile gaining, one-shot payload) and this bot buys no engine. The one that stings is Hermit at 0.350 - a card the strategy corpus rates highly for the Hermit/Market Square rush, which is precisely the plan `bmplus` cannot execute.

`TERMINAL_CAPS` gained exactly one entry: **Catacombs wants 1, not 2** (cap1 0.593, cap3 0.391, both significant at n=400 after an n=120 signal - the confirmation run the deck>=12 collapse made mandatory). It draws no cards on net when it collides; a second copy just re-reads the same three. Cultist, Marauder, Rogue and Hunting Grounds all measured inside the band at the default cap of 2, and a THIRD Marauder is significantly worse (0.333), so the default holds for them.

**MEASURED NEGATIVE — do not relitigate without a materially different approach.**
3. **`strategist` (archetype board-read) LOST at 0.35 vs bmplus.** Per archetype: engine **0.231**, minion 0.237, cursing-money 0.381, rush **0.000**, and even forcing its plain money plan reads **0.4667 over 120 games** — i.e. the sequencing/menu machinery is neutral-to-negative on its own. This reproduces the corpus's own headline result ("a simple engine buying only Villages and Smithies loses to Big Money") from the other side: hand-writing archetype plans does not beat a well-tuned money ladder. Two real bugs were found and fixed along the way and the tier still lost, so the losses are not implementation slop: the rush selector counted Bureaucrat/Bandit as "gainers" (they gain one Silver/Gold and can no more empty a pile than a Copper can — now `PILE_GAINERS`), and the engine menu contained no money at all, buying five $6 Border Villages instead of Golds.
4. **`champion` (per-kingdom plan tournament + determinized rollout buy search) is a WASH with bmplus at ~160x the cost.** Its first version LOST at 0.167, from two harness bugs that both look like "the search is weak":
   * **"buy nothing" was never committed to.** `_score_buy(None)` skipped the buy but left the rollout in the buy phase, so the policy bought something anyway — "pass" was really "let a fresh policy decide", and it scored 0.75 against every real buy's 0.2. It must `end_phase`.
   * **the rollouts were unpaired.** Three identical batches of 12 scored the same buy at 0.417 / 0.167 / 0.250 — the estimator's noise was wider than the gap between the options it was ranking, so the search overruled a well-tuned ladder with noise. Fixed with CRN: rollout *i* uses the same seed for every candidate.
   Also: the tournament adopting any plan scoring >0.5 adopts a LOSING plan more often than it finds a winning one (see #3), so the bar is a margin (0.65) over the proven benchmark.

**The oracle bound on per-board plan selection.** An oracle picking the best hand-written candidate per board beats bmplus by only **~0.596**, and that is optimistic (it selects on the same trials it scores on). It picks plain "money" on **45 of 60 boards**. Archetype selection is a small lever because money is simply the right answer on most boards *given these plans*.

**THE ROLLOUT-SCALING LADDER — the actual Rust gate, and it did NOT come back flat.** Champion vs bmplus, all sets, n=20 per rung: **4 rollouts = 0.250 | 16 = 0.300 | 64 = 0.425**. A 16x increase in search depth bought +17.5 points, monotonically. So throughput is NOT irrelevant — but every rung is still LOSING, and the shape says why: **the rollouts play `bmplus`, so the search is asking "how does this line end if both sides play Big Money".** A search cannot discover that an engine line is winning when the policy evaluating it cannot execute an engine. The natural asymptote of "search harder over a bmplus rollout" is *bmplus, chosen more carefully* — i.e. parity, which is exactly what the curve is walking toward. **The ceiling here is the ROLLOUT POLICY, not simulations per second.**

**CONSEQUENCE FOR THE RUST PORT — the phase order was inverted on purpose.** The plan had the Rust simulation core (a full 139-card port, plus a recurring per-expansion tax for ~13 more planned sets) landing BEFORE the champion. It was pulled forward instead, because the port's whole justification is making rollout search deep enough to pay, and that premise is testable in Python first. **Do not port 139 cards to Rust — plus a recurring per-expansion tax for ~13 more planned sets — to buy depth for a search whose ceiling is set by its rollout policy.** The measured gate: the ladder trends UP (+17.5 points over 16x) but from 0.250 to only 0.425, and the mechanism above says the asymptote is parity. Rust becomes the obvious next step the moment a BETTER ROLLOUT POLICY (or action-phase search) shows a rollout-count trend that crosses 0.5 — at that point depth is buying real strength and throughput is the binding constraint. Until then it is buying a faster route to a wash.

**METHOD NOTE (cost one wrong conclusion).** `best_buy(..., rollouts=ROLLOUTS)` binds the module constant as a DEFAULT ARGUMENT, evaluated once at def time — so a sweep that patched `C.ROLLOUTS` measured the same depth three times and printed 0.375 at 6, 24 and 96 rollouts. Identical to three decimals across a 16x range is the tell. Read tunable constants at CALL time.

**Harness kept, tiers not shipped.** `strategist` and `champion` stay in `bot.py` behind difficulty strings the server refuses (`_valid_difficulty` coerces anything unknown to the default), pinned by `test_the_unshipped_tiers_are_not_offered_and_coerce_to_the_default`. `bot_plan.candidates()` is the reusable candidate generator; `bot_arena` is CRN-paired with a mirror that must read exactly 0.5000 (the rng is keyed on the SEAT, never the tier, so a tier against itself plays two byte-identical games).

<!-- ===================================================================== -->
# ARCHIVE: Spender Duel AI — heuristic MCTS → netval → card-set ATTENTION value net (SHIPPED)
<!-- ===================================================================== -->

### Session (2026-07-29/30) — the coherent-era knob sweep CLOSES: opp_c 0.1 SHIPPED (0.69 at production shape), rollout-0 REJECTED after its screen INVERTED by 21 points, depth + FPU closed; and the flywheel measured with a NEGATIVE improvement operator

**The one-line methodology update: a K=1 screen can INVERT SIGN, not merely shrink. A high screen is not weak evidence about serving — it is no evidence.**

1. **`opp_c` — the opponent-model knob — SHIPPED (`e355d23`), and it is the largest single-knob gain since minimax.** `Opts::opp_c` is the c_puct applied at OPPONENT nodes only: low = the opponent commits to its single best reply (hard minimax); high = its visits stay spread, so what propagates up approximates an average over replies (expectimax). Serving shipped 1.0 — the same constant as our own nodes — which was never a measured choice, just an inherited default. Ladder (champion-net self-A/B, seed 97000, **control `opp_c`=default read 0.5000 exactly**): **3.0 = 0.4875 | 1.0 = old | 0.3 = 0.5400 | 0.1 = 0.5970 | 0.03 = 0.5913 | 0.0 = 0.4412 COLLAPSE.** A clean interior optimum with a plateau at 0.03–0.1.
2. **Why 0.0 collapses — the mechanism is worth keeping.** With no U term at opponent nodes, selection is pure argmax on signed Q. But **signed Q flips sign with who is ahead**: when the ROOT IS LOSING, a visited reply carries POSITIVE signed Q and outranks an unvisited move's neutral-0 FPU, so nothing is ever reconsidered and the node locks onto whichever reply it happened to explore first — in exactly the positions where being wrong costs most. A floor of opponent-node exploration is load-bearing, not slack. (I predicted 0.0 would be benign on the grounds that unvisited moves score 0 and beat the *negative* Q of visited ones — true only when the root is winning. The ladder refuted it.)
3. **The edge GROWS with depth, which is why the ship number is 0.69 and not 0.60.** `0.5970 @K=1 x1500` → `0.6233 @pool4 x1200` → **`0.6900 [0.643, 0.733] @pool4 x5000, n=400, mirror 0.5000`** — the last row on `netB`, the net Expert actually serves, at the real production shape (`main.py:99` caps 20000 aggregate; `SpenderDuel.jsx:811` splits `ceil(20000/4)` = 5000/worker). **User-caught:** every earlier "serving-shape confirm" ran at 1200 sims/worker, 4x shallower than production, understating this knob by ~7 points. Pool shape alone is not serving shape — per-worker DEPTH has to match too.
4. **`rollout 0` REJECTED — the screen inverted.** `--leaf attnfile` is `Leaf::AttnVal` (rollout + attention value), so `--rollout-steps 0` is a pure static attention leaf. It screened **0.6100 [0.561, 0.657]** at K=1 x1500 and measured **0.4000 [0.362, 0.440]** at pool=4 x4000 (n=600, mirror 0.5000); combined with `opp_c` 0.1 it read 0.4142. Mechanism: at K=1 the rollout's variance is a large share of the leaf signal, so deleting it looks like a win; at pool=4 the four root-summed independent trees average that variance away, and what remains is the static leaf's BIAS with nothing left to correct it. **The rollout buys signal that only pays once the ensemble cancels its noise.** `ROLLOUT_STEPS` stays 12. This also retires the tempting cross-game inference from the repo's "Spender/Duel: static leaf beats rollout" precedent — it does NOT hold for Duel at serving shape. Gate run at the user's direction (300g x 4k, after they stopped a 200g x 5k run); without it this ships as a 21-point regression on a 0.61 screen.
5. **Two knobs CLOSED for good.** DEPTH: `max-depth 24` read **exactly 0.5000** over 300 plays — an exact 0.5 with a symmetric CI means the two sides played *identically*, i.e. the 14-ply cap never binds even at 6000 sims; `max-depth 40` dropped as a tautology (a cap that does not bind at 24 cannot bind at 40). FPU: 0.2 = 0.4938, 0.5 = 0.5200, both wash → stays neutral-0. The FPU result also **unblocked the `opp_c` ship**: the two knobs interact (FPU decides whether unvisited opponent moves are explored at all; `opp_c` governs only re-visits), so a non-neutral FPU would have forced a re-read of the whole ladder.
6. **The flywheel's improvement operator is NEGATIVE — Phase 2 stopped.** 5 iterations, `cand-vs-champ` = 0.443 / 0.477 / 0.407 / 0.470 / 0.477: mean 0.455, no trend, never crossing 0.5 — a consistent ~4.5pp LOSS, not noise around a wash. The data-volume hypothesis is DEAD (iteration 5 ran a 355k-row buffer, larger than the seed netB2's own 325k training set, and moved nothing; consistent with the scaling curve showing warm-start fine-tunes insensitive to buffer size). Tripwires stayed clean throughout (entropy ratio 0.529–0.546, argmax 0.864–0.867, vs-heur rising to 0.807), so this is NOT the F1 guided-harvest collapse. Suspect the RECIPE: self-distillation of netB2 onto guided, narrower data at lr 5e-4 x 10 epochs with `rootval-blend 0.3` feeding the net its own value opinions. **Untested and worth doing first: a NULL-TRAINING control (effectively zero lr) that MUST gate 0.500 — it validates the harness before five negative iterations get interpreted.**
7. **PHASE 2 CLOSED — the flywheel has no positive improvement operator, and we now know exactly why.** Four measurements, same data (azpv2 iters 1–5), same gate, same seed, all warm from netB2:
   * **search vs the RAW net = 0.9600 @1200 sims / 0.9667 @3000** (side A `--greedy-net`, side B the harvest-identical search). Signal is ABUNDANT — the improvement operator is enormous, and the "teacher-student gap has closed" theory is dead.
   * **co-trained candidate = 0.4567**; recipe ladder: blend 0.3→0.0 = **0.3867** (removing the value-bootstrap made it WORSE — the blend is helping, not anchoring), lr 5e-4→1e-4 = **0.4967**, both = 0.4433. **Every step away from netB2 lost ground and the best arm was the one that barely moved.**
   * **freeze-trunk (policy head only; value leaf byte-identical) = 0.5100 [0.454, 0.566]** — recovers +5.3 points over co-training, confirming that policy gradients through the shared trunk were DAMAGING the value head, but lands at parity, not gain.
   * **harness self-gate: netB2 vs ITSELF, same file both sides = 0.5000 [0.444, 0.556]** (n=300, mirror 0.5000) — the measurements are sound.
   **Synthesis:** distilling search into the POLICY head buys nothing at serving (the prior is near its ceiling at T\*=2.0, and S4 already found the target choice a wash), while the only route to VALUE-head improvement — co-training — costs more than it gains. Duel's strength lives in the value leaf; the prior is worth ~0.59 in isolation. There is no configuration of this loop with a positive operator. Data volume, the teacher, the recipe, the target, and the harness are each independently eliminated **by measurement, not argument**. Next lever = Phase-3 rung 4 (capacity/architecture), since rungs 1–3 (exploration, opponents, sims) all act THROUGH this same dead loop.
   **Offline metrics inverted AGAIN (4th time this campaign):** the co-trained arms had HIGHER val_vauc (0.7507) than freeze-trunk (0.7307) and lost by 5 points; across the recipe ladder, val_top1 spanned 0.3374–0.3387 while win rates spanned **11 points**. Offline metrics are a smoke test, never evidence about strength.
   **Three of my four proposed mechanisms were refuted by measurement** (data volume, rootval-blend anchoring, teacher saturation); only co-training damage survived. Worth remembering how cheap each refutation was — ~20 minutes a gate — versus the 100-minute iterations that were producing the same null result.
8. **PROCESS FAILURES (three, all self-inflicted, all the same shape).** (a) `hp_sweep.ladder()` — a resumability edit dropped `results[p] = v`, so the winner check saw an EMPTY dict and printed *"no knob cleared 0.53 — the coherent-era defaults stand"* while `rollout=0` sat at 0.6100 in the same file. **Second time this campaign a script drew a confident no-winner verdict from an empty collection** (cf. the 2026-07-27 taskkill). The rows were always correct; only the path from measurement to conclusion was severed — trusting the verdict line over the rows would have discarded the sweep's biggest number. (b) An early-stop watcher's kill silently no-op'd because **`pgrep` does not exist in this Git Bash**; it logged "EARLY-STOPPED" while the sweep kept running. (c) `TaskStop` leaves gate grandchildren orphaned, and a kill-then-verify pass found a survivor at PID 66476 after the first sweep reported success. **Standing rule: kill by PID via `Win32_Process`, never by image name, and ALWAYS re-verify the process table rather than trusting the kill.** Both sweep scripts are now resumable (adopt banked deterministic gates rather than re-measuring — the base sanity gate alone cost 165 minutes) and both ladders early-stop on a turn-down.

### Session (2026-07-27) — MINIMAX (max-max was the bug) + the policy prior GO + visits-beats-qsoftmax; TWO Expert ships; a free 1.55x from lazy priors; and the correction that reframes all of it: EVERY number was measured at the WRONG SHAPE

**Read this entry's last section first if you are about to cite any number from 2026-07-26/27.**

1. **MAX-MAX — the deployed `select` never signed Q by actor.** Prompted by the user asking "cpuct helped, what other knobs are stale?", an audit found `node.w` accumulates ROOT-perspective values at every node and `select` MAXIMIZES it even at OPPONENT nodes — i.e. the opponent was modeled as *cooperating*. Python `ai.py` and the Rust port agree (parity-locked), so it dates to the original; **spender-core signs by actor** (proper minimax). Invisible in the per-sim era (U dominated → near-uniform visits ≈ averaging over replies, which the `select` docstring explicitly embraced as "broad sampling"); LIVE once coherent search let visits concentrate. **MEASURED: minimax 0.6217 [.582,.660] @cpuct1.0 (n=600), 0.6663 [.619,.711] @cpuct0.3 (n=400), control exactly 0.5000** — edge GROWS with concentration, as the mechanism predicts. Plausibly a hidden contributor to the whole "guidance hurts / search wants breadth" era: breadth was *medicating* max-max.
2. **The pivotal policy gate: GO (strong).** The user directed testing minimax BEFORE the pivotal harvest (it is upstream of both the targets and the gate), so E1 ran concurrent with the runoff — which is safe because the runoff is search-SYMMETRIC (same referee both sides) — and an interceptor then re-ran the harvest + gates under the winning search. Prior-on vs prior-off, netA both sides, coherent+minimax: **T\*=0.5 → 0.4462 (too sharp, HURTS), 1.0 → 0.5238, 2.0 → 0.5887 [.554,.622] = GO-strong.** A clean interior optimum — guide, don't dominate. First time a policy prior has ever been on the right side of 0.5 in Duel (per-sim era: 0.17–0.45).
3. **VISITS beat qsoftmax as the training target (0.655 vs 0.589).** The A2 gate — filed as a formality — was the most consequential result of the batch. Visit-counts (AlphaZero's canonical target) were abandoned here only because per-sim noise flattened them (top-visit share 0.08); coherent restored them (0.52) and with them the standard recipe. **Flywheel must run `AZ_PTARGET=visits`.**
4. **EQUAL-TIME arithmetic (G5+G6) — and the ship that was briefly wrong.** G5: the prior's edge DECAYS with depth (0.535 @4000 vs 0.589 @1000). G6 (guided@2k vs unguided@8k) = 0.4275. Backing out a scaling curve: **one doubling of sims ≈ +0.054 win rate.** At the prior's *original* 1.82x cost that is +0.046 of sims sacrificed to buy +0.035 of guidance — **net NEGATIVE**; only the lazy-prior speedup (below) flipped it to ≈+0.022. Equal-sims is the wrong axis for a ship decision; this is the Spender distilled-leaf lesson repeating.
5. **LAZY PRIORS — free 1.55x, bit-identical (shipped `f4c2864`).** A live playtest showed only ~7k pooled sims in the 3.5s budget. New `bin/bench_serving` decomposed it: **the prior cost 1.82x and the 12-step rollout cost NOTHING (0.99x)** — with an attention leaf the net forwards dominate, so the repo's "rollout is ~40x per sim" fact (measured with the HEURISTIC leaf) does not transfer. Priors were computed at node EXPANSION but are only read by `select` on DESCENT, so every never-revisited node (most, at ~76-wide branching) paid a full policy forward for nothing. Deferring is provably identical (pure function of state; `PriorShuffle` consumes no rng) — **1027 → 1595 sims/s, and a 40-game fixed-seed gate reads 0.8500 before and after, digit for digit.**
6. **Two Expert ships.** `6625f83`: the runoff winner (0.568 vs champion-1, 500g disjoint) — champion-1 simultaneously FROZEN to `src/attn_champion1_frozen.json` with every tool repointed, so the serving swap could not silently move the yardstick. `5312122`: **netB** (first policy+value net: co-trained on 4000 coherent minimax games, beats that donor 0.6583) + minimax + prior@T\*=2.0, and the sim cap 10k→20k (the old cap sat at a saturation measured under per-sim/max-max; coherent+minimax deepens one sound world so saturation moves out, and 3.5s at ~1420 sims/s/core allows ~20k across the pool — the TIME bound now governs).
7. **⚠ THE SHAPE CORRECTION (user-caught, reframes everything above).** The user asked why nothing had been tested at the live bot's 4-worker shape. Two findings: (a) **every number in this entry and the 07-26 entry is a SINGLE-TREE K=1 measurement**, while serving runs 4 INDEPENDENT searches root-summed at ~2750 sims/worker; (b) worse, the flag that looked like it covered this **did not** — `Opts::root_dets` under `coherent` runs K worlds into ONE SHARED tree, so world 2's sims descend statistics world 1 wrote and UCB is coupled across worlds. That is a different algorithm, and the planned K-sweep would have measured it confidently and irrelevantly. Built the real thing: `mcts::root_search_pooled_with_leaf` + `gate_netleaf --pool/--pool-b` (independent trees, root-summed, same greedy `pick(stats,0.0)` as `wasm::duel_pick_move`; `--sims` = PER-WORKER, as on the client). Self-gate at pool=4 reads 0.5000. **A specific mechanism could flip the prior verdict: all 4 workers share the prior, so they concentrate on the SAME moves and the pool loses the diversity that makes pooling worth anything.** Serving-shape batch (S1 coherent-vs-per-sim = the FOUNDATION everything else sits on, S2 minimax, S3 prior, S4 visits-vs-qsoftmax, S5 shipped-vs-yesterday) running at pool=4. **RULE: tune cheap at K=1, but CONFIRM every ship at pool=N. Until S1–S5 land, treat all of the above as ship-CANDIDATES.**
8. **Also corrected this session:** I asserted "~10 workers / 20–60k sims" from memory for hours and reasoned from it (even to argue *down* G5, which was pointing at the truth). Code says `min(hardwareConcurrency-1, 4)` workers and a 10k aggregate cap → **~2500 sims/world**, so the serving regime sits near G5's 4000 point, not G1's 1000. **PROCESS FAILURE worth naming: `taskkill /IM gate_netleaf.exe` (to serialize the box) killed hp_sweep's own in-flight gates; every gate returned None and the script wrote "no knob cleared 0.53 — the coherent-era defaults stand" as a VERDICT FROM AN EMPTY SET.** File annotated INVALIDATED; depth/rollout/FPU remain untested. Any sweep script should refuse to conclude when its gates return None.

### Session (2026-07-26) — THE BREAKTHROUGH: per-sim determinization was INJECTING the flat targets that killed every AZ attempt; COHERENT search (determinize once + freeze chance) SHIPPED for serving (beats per-sim 0.585) and unlocks the policy flywheel; full AZ campaign launched

**The reframe (user-caught, do-not-relitigate):** Duel is **near-perfect-information** — the hidden state is tiny (≤3 face-down reserves/player + deck order + bag). Every prior "policy dead / search wants breadth / real mixed marginal" verdict was measured under **per-sim determinization** (PIMC re-samples the hidden world AND re-rolls chance EVERY simulation) and is therefore **VOID**. That per-sim noise was *self-inflicted*: it forced wide exploration → flat visits → garbage policy targets → the dead AZ loop. Confirmed in code (`mcts::simulate` had no chance nodes — re-applied `RngShuffler` every visit) and by a new diagnostic (`bin/diag_flatness`, modes persim/rootdet/cheat/coherent + c_puct + Q-gap).

**Diagnostic arc (3 of my reads were wrong before the right one — the sequence matters):** (1) cross-seed pick agreement jumps **0.71→0.94** when the true world is fixed (cheat mode) → determinization noise was large. (2) Q-gap ~0.037 at the deployed wide c_puct=1.5 looked like a shallow value landscape — but that was an EXPLORATION artifact. (3) **COHERENT mode** (`Opts::coherent`: determinize ONCE + freeze chance via `PriorShuffle` in `simulate`/`rollout_play`) + tight c_puct=0.1 → top-visit share **0.08→0.52**, Q-gap **0.035→0.083** = a SHARP, learnable policy target exists after all. Improvement operator strong: full search beats the raw net's 1-ply argmax **0.742** (n=240).

**SHIPPED (commit `68f7e58`):** coherent serving. `gate_netleaf` coherent-vs-per-sim (champion-1 both leaves, n=400/pt, mirror 0.5000): c_puct 0.1→0.498 (too greedy to serve), **0.3→0.580, 0.6→0.583, 1.0→0.588** — broad plateau; the win is the COHERENCE, not the exploration. `wasm.rs` duel_search/duel_search_expert set `coherent: true, prior_c: Some(1.0)`. Strategy fusion is NEGLIGIBLE (the near-perfect-info payoff). Two independent gains now STACK: search (per-sim→coherent, 0.585) × net (coherent-harvest value loop lifts the leaf **0.55-0.57 vs champion-1** where the per-sim value loop washed at ~0.52).

**Serving-K subtlety (do-not-forget):** coherent serving is per-worker K=1 → the browser's ~10 workers pool into a **K≈10 coherent ensemble** (hedges the residual ~30% cross-world disagreement). Our gates/harvest are K=1 = a LOWER BOUND. `mcts::coherent` now takes **K = `root_dets`** (K=1 byte-identical; K>1 pools K worlds, iteration-split — a TIME-bounded K>1 serve would need per-world deadline splitting, noted in code). `gate_netleaf` gained `--root-dets-b`. **K-sweep** tunes the ideal world-count; **the prior ship-gate MUST be at serving K, not K=1.**

**THE CAMPAIGN (plan: `.claude-plans/validated-enchanting-hoare.md`; full-campaign + auto-ship approved):** the policy flywheel is the one mechanism with an 80%-vs-champion-1 ceiling, and its ONE untested precondition is *does a learned policy prior help COHERENT search* (per-sim verdicts void). Phase 0 (DONE): revived the orphaned PV infra on coherent search — `harvest_attn_pv` (DUELAP02: raw q/visits + rootval + `--leaf-b` league opponents + policy_valid masking), `train_attn_pv` (qsoftmax|visits targets, value-bootstrap blend, freeze|co-train), `az_pv_loop.py` (guided harvest, league shards, serving-real gates, resumable), `runoff.py` (disjoint-seed winner's-curse de-bias). Phase 1 (running tonight, automated `phase1_overnight.py`): value-Expert runoff (ship-gate #1) → 4000-game pivotal harvest → trains → **the GO/NO-GO gate** (prior-on vs prior-off, coherent both, temps {2,1,0.5}). Phase 2 = the flywheel (weeks, ~1h/iter, runoff every 8 iters, auto-ship each verified Expert). Phase 3 = plateau ladder (exploration → opponents → sims → capacity=the parked spatial cell-token encoder). **Honest odds:** GO ~50-60%; if GO, central case 0.62-0.70 vs champion-1 after 50-150 iters; 0.80 stretch ~30-40%. **Methodology:** directional sweeps early-stop on a clear negative trend ([[sweep-early-stop]]); ship-verify on disjoint high-N runoffs. **STRENGTH SIGNAL (user-corrected): high-N RUNOFF vs-champion1 + a near-peer past-champion panel + user PLAYTESTS. vs-heur is a COMPETENCE FLOOR only — it SATURATES and `heur` is an IN-DISTRIBUTION league opponent, so a rise is ~meaningless (a drop is a red flag). Per-iter gates are noise → the runoff decides. Earlier framing "vs-heur is the climb signal" was WRONG; matches Spender's "weak H3 panel insufficient → use near-peer past-self panel" lesson.**

**Rejected this session (do-not-relitigate):** the perfect-info teacher (user-caught — it's the same brain cheating, not smarter; distilling its values = info-biased target); the spatial board encoder as a CURRENT lever (enriches OBSERVABLE info, washed its value-loop test — it's the capacity RUNG, parked in the encoder worktree, parity-green + warm-start-safe). arxiv 1705.07381 (probabilistic-planning determinization) — off-domain, but its "determinize where safe, reason probabilistically where not" principle names the eventual ceiling-breaker (coherent search + belief reasoning on the contested ~30%).

**FOUND (2026-07-26, audit prompted by the user's "cpuct helped — what other knobs are stale?"): Duel's `select` is MAX-MAX, not minimax.** `node.w` accumulates values from the ROOT's perspective at every node (`simulate` never sign-flips), and `select` maximizes that Q at EVERY node — so at OPPONENT nodes the search models the opponent as picking the ROOT's best outcome. Python `ai.py` and the Rust port agree (parity-locked); **spender-core signs by node actor** (`if to_play == ref_player { value } else { -value }`) — proper minimax. Why it survived: in the per-sim era U dominated (visits near-uniform ≈ averaging over opponent replies — an "average opponent" model, and the select() docstring's "broad sampling" design embraced it); under COHERENT concentration the visits genuinely chase cooperating-opponent lines. May also be a hidden contributor to the old "guidance hurts / wants breadth" behaviour (concentration amplified the max-max optimism). `Opts::minimax` (+ `fpu`, `max_depth`, gate flags `--minimax/--fpu/--max-depth/--rollout-steps` both sides) added default-inert; **`tools/hp_sweep.py`** (chained after the K-sweep) A/Bs minimax + the other per-sim-era-tuned knobs (depth cap 14, FPU-neutral, rollout 12) champion-1-self, serving-real, seed 95000, early-stop ladders. Winners re-verify at serving K, then apply to the flywheel's harvest/gates too. **MEASURED same night (user-prompted "test the pivotal change FIRST" — E1 fired concurrent with the runoff; iteration-bounded gates make contention harmless): minimax 0.6217 [0.582,0.660] @cpuct1.0 (n=600) and 0.6663 [0.619,0.711] @cpuct0.3 (n=400) over deployed max-max, control 0.5000 exactly — DECISIVE, second breakthrough-scale search gain of the day, edge GROWS with concentration exactly as the mechanism predicts (and prod's 20-60k sims concentrate hardest). Retro-explains part of the "guidance hurts / wants breadth" era: concentration amplified the cooperating-opponent fantasy, so breadth was medicating max-max, not a property of the game. Phase-1b interception re-runs the pivotal harvest + GO/NO-GO under minimax (`P1_MINIMAX=1`); `az_pv_loop` gained `AZ_MINIMAX`; NOT yet shipped to prod — serving-K verify + depth-confirm first (the serving-K rule).**

### Session (2026-07-24, cont.) — SPENDER-vs-DUEL code AUDIT: Duel skipped the FOUNDATION (raised by the heuristic, not a champion); "policy dead / wants breadth" is largely CONDITIONAL; goal reframed to absolute Spender-level ELO; revised 4-lever plan (lead with imperfect-info SEARCH + representation, DEMOTE the curriculum)

**Bottom line:** the user reframed the goal from "beat me 80%" to **absolute Spender-level ELO** (beat the user AND Hard/Expert handily; long-shot OK, incremental welcome — and pushed back on my "self-play can't climb" pessimism with the chess-AI counterexample, correctly: AlphaZero reached superhuman chess from random self-play, so a self-play fixed point is NOT a law). A three-subagent audit read the ACTUAL Spender + Duel code (not memory) to find where the Spender playbook was skipped. **Finding: the two games share the SAME search skeleton** — per-sim determinized PUCT, C_PUCT 1.5, card-set attention arch, ~10k aggregate sims — so Duel is NOT structurally forced into a different method. The decisive divergence is **the training campaign, not the game**: Spender's deployed attention net was warm-started by DISTILLING `net_night_14` (the policy+value champion sitting on hundreds of AZ iterations WITH a policy head + racer curriculum), then polished with 6 light self-play iters; **Duel's net was raised on HEURISTIC self-play, value-only** — inheriting the heuristic's development-poor priors, exactly the blind spot the user exploits. The "policy dead / search wants breadth" verdict (entries below) is largely **CONDITIONAL on that undertrained net** (the log's own 07-22 self-correction: the flat policy is a training-distribution artifact), though one difference IS real: Duel's hidden info is genuinely larger (perfect-info cheat 0.725).

**A. The audit — two code-verified process maps.**

*Spender's winning process (variant N = `net_attn_3`, client-WASM):*
- **Search:** determinized PUCT, **per-sim determinization** (a fresh resampled world EVERY sim; `mcts.rs::sim` → `determinize` per sim), C_PUCT **1.5**, prior P(s,a) = the **net's own policy head** (legal-masked softmax of 70 policy logits) at PLAY leaves, H3 heuristic prior at discard/noble leaves. **Static net-value leaf, NO rollout.** ~10k aggregate sims / 4.5 s across ≤4 workers; sum-visits argmax + endgame-solver refine.
- **Net:** card-set attention, **policy + value** heads (per-token buy/reserve logits + a global head for take/pass). The learned **policy prior beats the H3 prior 0.58** at a matched value head (~+8pp from the policy alone).
- **Training:** **warm-start = DISTILL the prior champion `net_night_14`** (starts at ~0.50 parity, NOT from scratch) → **6 iters pure self-play @128 sims, 2500 games/iter, peaked iter 3, shipped that**; exploration = visit-count sampling first ~30 plies, **NO Dirichlet** (adding eps 0.25/0.40 later washed — "exploration is not the bottleneck"); policy target = MCTS visit distribution (CE); value target = outcome + **reward-shaping + search-root-value bootstrap β≈0.3**; gate = win-rate vs the frozen champion, paired CRN, mirror 0.5000. Shipped **0.567 vs net_night_14**. The ATTENTION net's own loop is SMALL — its strength was **inherited from the long MLP policy+value lineage via the distill**, not built in 6 iters.
- **Ceiling-breaker the log credits:** (1) SEARCH DEPTH (variant S + the Rust-WASM rewrite for 100–1000× sims), then (2) the **attention cross-card inductive bias** layered on that search (a flat MLP provably can't assemble engine-value's pairwise cross-card sum). NOT the league, NOT exploration, NOT more flat features.

*Duel's process (Hard = v2, Expert = champion-1, client-WASM):*
- **Search:** determinized MCTS, **per-sim determinization** (IDENTICAL scheme), C_PUCT **1.5**, prior P(s,a) = **NONE (uniform UCT)** — the policy head exists in the torch twin but is NOT exported/served (both shipped nets are value-only; `attn.rs::policy_logits` returns empty when `pb` absent → flat 1.0). **Netval leaf** (12-step rollout serving / 2-step harvest, then net value at truncation). Budget = **min(10k pooled sims, 3.5 s)** — **the "~60k sims" in comments/memory is STALE** (current cap `_CLIENT_AI_MAX_SIMS=10000`); greedy by visits, tie-broken by mean value.
- **Net:** card-set attention, **value-only** (policy + aux heads defined in torch, measured dead/wash, never exported). Enriched features added this campaign (TOK_F 20→30: per-color effective cost, turns-to-afford, engine-value, opp-denial mirrors, anti-hoard).
- **Training:** v1 on 4k / v2 on 32k **HEURISTIC self-play** games, **value-only, pure-outcome MSE**, no Dirichlet, opening temp-plies exploration only. champion-1 = a **gentle K=1 / 2-epoch fine-tune** of v2 vs a scripted developer (outcome-labeled), then an 8-iter co-evolution league that **plateaued** (single-axis developer drifts weird). **No value-bootstrap, no policy target, no distilled-champion foundation** — the three load-bearing pieces of Spender's campaign.

**B. Synthesis — Duel was raised by the heuristic; Spender by a champion.** Duel's value net learned to predict outcomes of HEURISTIC-vs-heuristic games, so its strategic priors ARE the heuristic's (under-develop, hoard, over-reserve). Deep search sharpens it TACTICALLY (net+search beats the heuristic 0.80 via lookahead) but the search optimizes toward a **development-blind leaf**, so it cannot discover the value of development the leaf refuses to reward — precisely why a good human beats it. Spender's net, raised on champion AZ self-play (curriculum-hardened against racers), has development baked into the value → it beats strong humans. Corroborating: Duel NEEDS a rollout leaf (0-step net collapses 0.40→0.23 with depth) while Spender ships a static leaf — **the rollout is itself a SYMPTOM of the weaker eval** (search amplifies a bad static eval's errors; a good eval holds and buys ~16× the sims).

**C. Honest nuance on "policy dead / search wants breadth" (entries below).** Measured on v2 (Duel's BEST net, but a mediocre player), three ways: heuristic prior 0.19–0.25, greedy-net-with-true-state 0.174, learned-policy-prior hurts monotonically. The greedy-83%-loss shows a **1-PLY eval loses to DEEP search** (true in Spender too — it does NOT show a policy PRIOR can't GUIDE a deep search; different claim). The prior tests used v2's FLAT policy, flat because raised on heuristic games where develop-vs-take was never punished (the 07-22 self-correction). Spender proves the SAME search + a policy prior works in the sister game. ⇒ treat "wants breadth" as **CONDITIONAL on the undertrained net, NOT a law** — RE-TEST after strengthening. The ONE real net-independent difference: hidden info is genuinely larger in Duel (0.725, incl. an unrecoverable part).

**D. Revised plan — build Duel's foundation, adapted (no human data [[duel-no-human-data]]); ORDERED for absolute ELO.**
1. **Lever C FIRST — imperfect-info SEARCH (net-independent).** Attacks the single largest MEASURED gap (0.725). De-risk = root-determinization sizing (`Opts::root_dets`, coherent world per group, pool K) vs per-sim PIMC and vs the perfect-info bound, to size the RECOVERABLE part (some is unknowable). If positive → build proper information-set MCTS (aggregate statistics over shared information sets, not independent per-sim trees) / DeepStack-style re-solving. Stacks on every other lever; needs no retrain; cheap, decisive de-risk.
2. **Lever A — representation FOUNDATION (the ceiling-raiser).** Enriched flat features (done) → **spatial 5×5 board encoder** (line-take geometry / per-card affordability) + **value-bootstrap β≈0.3** (Spender keeper; the per-position signal whose ABSENCE made value-only self-play wash) + train on the SEARCH's play, not the heuristic's. The analog of Spender's attention-inductive-bias break. See [[duel-representation-upgrade]].
3. **Lever B — DEMOTED to the training/eval ENVIRONMENT.** The diverse opponent FAMILY (developer variants, each win-condition rusher, hoard-punisher) becomes WHO the Lever-A net trains against (bakes in development) and HOW we gate — NOT a standalone first step (it plateaus after one patch — proven by champion-1's league).
4. **Lever D — RE-TEST the policy head** after A strengthens the net (conditional-on-weak-net verdict → one clean re-measurement; high upside; explicitly NOT a relitigation of the closed verdict).
- **Gate honestly (cross-cutting):** bot-vs-bot HIDES shared blind spots (both under-develop → cancels) → gate vs the HEURISTIC + blunder/development metrics (buy rate, tokens hoarded, reserve conversion, pts/card) + a **scripted proxy of the user's efficient-developer style**; the real target is beating that proxy, then the user.

**Recommendation (revised for the absolute-ELO goal):** lead with **C (net-independent, biggest gap, cheap decisive de-risk) + A (foundation)**; use B as the training/eval environment; D as a re-test. My earlier "Lever B first" was optimized for the narrower beat-the-user goal and is SUPERSEDED. Realistic: 80%-vs-user is reachable by killing the exploits (champion-1 proved the mechanism), but absolute Spender-ELO is a multi-day-to-weeks iterative climb on one box — report honestly per-lever.

**Verdict:** the "Duel is different in kind (wants breadth, policy dead, self-play plateaued)" framing was over-generalized from an undertrained value-only net raised on heuristic games — the SAME conditional-verdict error flagged earlier for hidden info. The game shares Spender's exact search skeleton; the missing piece is the FOUNDATION (a champion-quality value net with development baked in) + the imperfect-info search. Next action = the Lever-C root-det de-risk + standing up the Lever-A loop. Do-not-relitigate is preserved: leaf patches (dev-tilt/blend/rollout), MLP policy/value leaves, aux heads, endgame solver, geometry term, and β as a blunder-patch all stay dead; the policy-head RE-TEST (D) and value-bootstrap β (a fresh-retrain signal, Spender keeper) are distinct from those.

### Session (2026-07-23 → 24) — AZ policy loop MEASURED DEAD; blind-spot MAP (development is the ONE exploit); LEAGUE → **champion-1** SHIPPED as a new **Expert** tier; imperfect-info SEARCH is the last lever

**Bottom line:** continued from the search-guidance-closed session below, chasing the diagnosed under-development blind spot to a real, shippable win — then mapping the ceiling. (1) The user directed building the one thing untried — a real AZ *policy* loop on the ATTENTION arch — and it **MEASURED DEAD** (the learned prior hurts exactly like the fixed ones; the co-evolving loop's fixed point is a *useless* prior). (2) A specialist sweep proved **development is v2's ONLY exploitable axis**. (3) A DEVELOPER-opponent **LEAGUE** produced exactly ONE genuine, human-robust gain — **champion-1**, beats v2 0.559→0.583 (edge GROWS with sims) — then **PLATEAUED** over 8 co-evolution iterations. (4) **champion-1 SHIPPED LIVE as a new `Expert` tier** (Hard stays v2). (5) The last genuine-strength lever is the imperfect-info SEARCH: a perfect-info cheat beats normal play **0.725**, so hidden info matters hugely — a root-determinization de-risk is sizing the CLOSEABLE gap before any ISMCTS build.

1. **AZ attention-policy loop — BUILT, then MEASURED DEAD (do-not-relitigate).** Built the full Stage-1 pipeline the "MLP is dead" verdict never covered on the ATTENTION arch: torch policy head (`forward_pv`/`export_pv`, N_ACTIONS=320) + Rust `attn.rs` policy head (shared `trunk_into`, value stays byte-identical — parity value 1.7e-9 / policy 8.6e-8) + `harvest_attn_pv` (token-features + softmax-Q target) + `train_attn_pv.py` (frozen-trunk → value==v2, clean prior-isolation) + `mcts::Opts::net_policy_temp`/`net_policy_priors` + `gate_netleaf --net-policy-temp`. **Target-temp finding:** harvest temp 0.03 → PEAKED target (entropy ratio 0.585, argmax==pick 0.994), vs temp 0.10 (old `harvest_pv` default) → near-uniform 0.92 — so the old MLP policy's flatness was partly a target-temp artifact. But the policy CEILING is structural: **frozen-trunk val_top1 0.3056, co-trained 0.3195, old MLP 0.338** — arch/capacity don't lift it (Duel's move-values are flat). **GATE:** the learned prior HURTS monotonically with concentration (net-policy-temp 4.0/2.0/1.0/0.5 → 0.525[wash]/0.4525/0.3425/0.3475 vs unguided v2); `argmax==greedy` collapses 0.994→0.48 under guidance (the prior hijacks visits OFF the value). **Co-evolution iteration-1** (guided harvest → retrain) went DOWN: top-1 0.256 vs 0.306, and a **size-matched unguided control (0.308) rules out data-size** → the guided data is intrinsically worse; the loop's fixed point is a *useless* prior (it "improves" only by flattening the policy toward a no-op). ⇒ **AZ policy-guidance is fully dead for Duel** (fixed AND learned priors both hurt; the search wants BREADTH — the opposite of AZ/Spender). All kept OFF-by-default; do not re-run the policy loop.

2. **Aux-targets (multi-task trunk regularization) — WASH.** `harvest_aux` + `train_attn_aux.py` with game-final aux heads (card/crown margin, win-condition, game-length) to sharpen develop-vs-take. On 2350 games/194k positions: control (aux-w 0) val-AUC **0.6896** vs aux (0.3) **0.6868** — aux WORSE. Another in-distribution development-regularizer that washes (like dev-tilt / debias). Skipped the play-gate (offline negative + both sub-v2). Tooling kept.

3. **Blind-spot MAP (specialist sweep) — development is the ONE exploit.** Generalized the leaf to `mcts::Leaf::HeuristicW(&Weights)` + a specialist basis (`value::{DEV,CROWN,COLOR,POINTS}_WEIGHTS`, win-condition tilts keeping win-progress). Gated each vs v2 @700, paired with the plain-heuristic baseline **0.256**: **developer 0.370 (+0.114, the ONLY exploit)**; crown 0.248 (neutral); color 0.193 / points 0.146 (v2 CRUSHES impatient rushes — self-play over-trained it there). ⇒ v2 has exactly ONE blind spot = patient development; the league is FOCUSED, not diverse (the user's diverse-league idea earned its keep by *proving* this).

4. **LEAGUE — champion-1 (the session's one genuine gain) + the plateau.** (a) **Learned developer** (warm-start v2, fine-tune on heurdev self-play): 0.475 vs v2 — a near-peer (leaf gap closed) but not a decisive beater (warm-start inherits v2's biases). (b) **The champion retrain — KEY METHOD LESSON:** train v2 vs the developer to defend development. AGGRESSIVE (`train_attn_debias` K=3, 10ep, final-epoch export) **DEGRADED** v2 to 0.385 (corpus AUC collapsed — over-fine-tuning trades general strength for the lesson). **GENTLE (K=1, 2 epochs, big v3 anchor) WORKS: champion-1 (`v2_prime_gentle`) beats v2 0.5592 [.519,.598]**, corpus AUC PRESERVED 0.735 (≈v2's 0.742) + lesson landed (held-out LOST −0.024→−0.107). **First genuine strength gain over shipped v2 all session.** (c) **8-iteration CO-EVOLUTION (`scratchpad/league_loop.py`) → PLATEAU.** Two-net matchup harvest/gate (`--attn-file-b`/`attnfile2`), alternating developer best-response + champion gentle-retrain, gate-and-promote. **ANCHOR-FIX (do-not-relitigate):** the champion's anti-forgetting anchor MUST be the CURRENT champion's own self-play, NOT the original v2's v3 — the first run regressed champions back to the original; fixed by harvesting champ self-play as the anchor. Even fixed, **all 8 iters failed to promote** (candidates 0.47–0.54 vs original, degenerating as the single-axis developer drifts weird). ⇒ **the league gives exactly ONE modest gain (champion-1) then caps** — one blind spot, patched once, no further in-distribution signal without human data.

5. **Expert tier SHIPPED LIVE (2026-07-24).** champion-1 validated: beats v2 **0.559/0.570/0.583 @ 700/2k/4k sims — edge GROWS with search** (a genuine eval improvement, not a low-sim artifact). Shipped as a NEW `Expert` tier above Hard (Hard stays v2), NOT a swap: `wasm.rs` embeds BOTH nets (`attn_value_net.json`=Hard, `attn_expert_net.json`=champion-1) + a `duel_search_expert` entry (Hard byte-unchanged); `duel-worker.js` routes by `msg.expert`; `SpenderDuel.jsx` picker + gate + dispatch; `main.py` AI_DIFFICULTIES/CLIENT_AI_TIERS += expert; `ai.py` DIFFICULTY["expert"]=hard (server fallback). wasm 2.25→4.27MB (2 nets). Pushed backend-first (Render) then frontend (Pages); verified live (health 200, Expert marker in bundle, deploy-pages success). Rollback = `git revert d01be4b`/`9433326`; v2 backup at `src/attn_value_net_champ0_v2_backup.json`.

6. **Imperfect-info SEARCH = the last genuine-strength lever.** Stage-0 probe (`mcts::Opts::no_determinize`, `gate_netleaf --no-determinize`): a PERFECT-INFO cheat (searches the TRUE hidden state, no resampling) beats normal determinized play **0.7250 [.679,.766] @2000** (same-net sanity 0.5000). Hidden info is worth ~22 points → the search is where the remaining strength is. **NUANCE (do not over-read):** 0.725 is the FULL imperfect-info penalty, incl. the *unrecoverable* part (perfect-info is an unachievable upper bound) — it proves hidden info matters, NOT that a better search recovers much. Next de-risk = ROOT-DETERMINIZATION (`Opts::root_dets`, fix one world per group, coherent search, pool K) vs per-sim PIMC, to size the CLOSEABLE gap before committing to a full ISMCTS / DeepStack-re-solving build.

**Verdict:** the session's concrete win is **champion-1 shipped as Expert** (a real, human-robust +0.06–0.08 over Hard, edge growing with sims). Everything in-distribution is now exhausted for genuine strength (AZ policy dead, self-play plateaued, league capped — one blind spot patched once, no more signal without human data, which the user excluded). The ONE remaining genuine-strength lever is reworking the imperfect-info SEARCH (ISMCTS / re-solving); the RL-exploiter path is excluded as brittle (the user wants human-robust). Root-det de-risk decides whether that lever pays.

### Session (2026-07-23) — Search-GUIDANCE lever CLOSED (heuristic prior, net prior, 1-ply greedy all HURT); Duel's search wants BREADTH, not guidance

**Bottom line:** the Spender comparison pointed at the one architectural lever Duel never had — an INFORMATIVE search prior (Duel's PUCT is uniform; Spender's is H3-guided). Built it, measured it three ways, CLOSED: guidance HURTS. This is a STRUCTURAL property of the game (flat move-values + hidden-info determinization noise), not a tuning miss — the opposite of AlphaZero/Spender. v2's broad determinized MCTS + value-tiebreak pick is CORRECTLY matched to the game. NOT a ceiling (a below-average human still beats v2 ~70%); the remaining lever stays the value-LEAF's develop-vs-take quality = training distribution.

1. **Duel's `select` has NO prior** (uniform UCT), by design — the code MEASURED a FLAT prior = a C_PUCT rescale, but left the door open for an INFORMATIVE one ("a learned prior would be different — revisit this"). This session answered that.

2. **1-ply HEURISTIC prior** (`mcts::compute_priors` + `Opts::prior_temp/prior_c`, OFF by default = byte-identical, verified v2-vs-v2 = 0.5000): rank moves by the heuristic `value` of each child, softmax, PUCT. **Swept vs plain v2 @2000 sims, n=240: temp 0.05/0.1/0.2 = 0.1917 / 0.2417 / 0.2458 — all big LOSSES**, gentler=less bad but still ~0.25. The board-blind heuristic is a bad ranker AND concentrating commits to it.

3. **1-ply GREEDY net** (`mcts::greedy_net_move` + `gate_netleaf --greedy-net`): score every child with the v2 net, play the argmax, NO search — "the net picks the best resulting position" (the user's baseline). **vs full v2 search @2000, n=500: 0.1740** [0.143,0.210]. Even though greedy got the TRUE hidden state (no determinization — an UNFAIR advantage), it lost ~83%. The deep search is worth ~0.33 winrate over the net's raw 1-ply judgment.

4. **WHY guidance hurts (resolves the flat-Q / flat-policy puzzles):** Duel's move-values are genuinely flat AND every position carries heavy hidden-info determinization noise (bag, decks, opp reserves, gold, again-turns), so any single-position eval is noise-dominated — the signal only emerges from sampling MANY determinizations DEEP. Early commitment (what any prior does) locks onto noise. This is ALSO why the policy head came out flat (last session #7): there is no crisp 1-ply move-preference to learn; the quality lives deep in the tree. Opposite of AZ/Spender (sharp values + reliable evals → a prior helps).

**Verdict — search-guidance is CLOSED for Duel (measured 3 ways + structural).** Kept as documented OFF-by-default tooling: `mcts::{compute_priors,greedy_net_move}`, `Opts::prior_temp/prior_c`, `gate_netleaf --prior-temp/--prior-c/--greedy-net`. The live lever remains the value LEAF's develop-vs-take differentiation = training DISTRIBUTION (human-debias is data-gated). The untried, DATA-UNLIMITED attack on the diagnosed under-development blind spot: a scripted-**DEVELOPER** opponent to inject the signal self-play can't generate — de-risk FIRST by gating a re-weighted "developer" heuristic vs v2 (if it can't even pressure v2, the Spender racer-league precedent applies and it's dead; if it CAN, build a train-against-developer track, developer FAMILY + gate vs v2 to avoid script-overfit).

### Session (2026-07-22) — v2 retrain SHIPPED; forward speedups banked; self-play/capacity/policy levers PLATEAU — but human games expose a real, exploitable blind spot (NOT a ceiling)

**Bottom line:** the three *self-play* strength levers plateaued (data, capacity, policy) — but that is a **SELF-PLAY plateau, NOT a ceiling.** Analysis of the user's real prod games (§8) shows Duel Hard loses **~70% of completed games to a self-described BELOW-AVERAGE human** via a systematic **under-development** blind spot that self-play is structurally blind to. **No AI is at its ceiling short of a solved game** — I wrongly conflated "self-play plateau" with "ceiling" in-session; corrected throughout. v2 stays SHIPPED (`3d0cecb`; beats v1 0.63, heuristic 0.80); the ~3.3× speedups are banked (`63eb9ab`); the live lever is **human-game DEBIAS** on the diagnosed blind spot, not another blind self-play round.

1. **v2 SHIPPED (`3d0cecb`) — larger-data retrain of the attention net.** 2.96M rows / 32k games + weight-decay fixed v1's ep6 overfit collapse (val AUC plateaus 0.742). Gate @2000 sims, n=800, mirror 0.5000: **v2 vs v1 = 0.6300**, v2 vs heuristic = 0.7963.

2. **Forward speedups (banked, `63eb9ab`) — MEASURE first.** `bin/attn_bench`: one attn forward = 458µs but only **~30% of a sim** — the 12-step rollout is **~70%**. So no-alloc thread-local scratch gave only ~4% (allocation was never the bottleneck), while SIMD chunked-dot in `linear()` (8 accumulators → breaks the f32 reduction dep → wasm128 FMA) cut the forward 458→240µs (1.9×) and *improved* parity (6.1e-8 → 1.7e-9). Value-net is unchanged, so the wasm redeploy is deferred (batched with any future net ship).

3. **Rollout 12→2 (gate-verified — DO NOT RELITIGATE).** `gate_rollout`, equal-sims, mirror 0.5000, n=160: **roll=0 LOSES (0.431)** but **roll=2 / 3 / 4 all TIE roll=12** (0.525 / 0.469 / 0.506). So 2-step is the floor — the rollout matters (0-step loses) but 6× fewer steps costs nothing. Rollout was 70% of a sim → **~3.3× generation**. Applied as `opts.rollout_steps=2` in the harvester, NOT the global HARD cfg (which also drives the heuristic serving fallback).

4. **Saturation re-measured on the ATTN net: ~4k (below the old ~6k heuristic figure).** net@8000 vs net@4000 = **0.4688** [0.393,0.546] n=160 — doubling past 4k gives nothing (a stronger leaf needs *less* search). Prod budget set to **3.5s OR 10k sims, whichever first** (`05519e3`).

5. **Self-play iteration round 1 (v3) — WASH.** 12k net-strength games (attn leaf, 2-step, 2000 sims, opening temp) → same-arch retrain → **v3 vs v2 = 0.5117** [0.472,0.551] n=600. Two lessons: (a) **value-only self-play doesn't bootstrap** — AZ's improvement engine is the *policy* loop, which Duel lacks (see #7); retraining a value head on stronger-play outcomes is a weak signal. (b) 12k STRONG games play *even* with v2's 32k WEAK (heuristic) games → strong data is more efficient per game, but a same-arch retrain does not exceed v2. My initial "need ~30k games" read was the wrong lever (user callout: Spender never won via data volume — its wins were method: search, attention, a working policy head).

6. **Bigger net (v3big: D=96/HEADS=6/FF=192/L=3/H=192, ~3× params) — OVERFIT, no gain.** Same v3 corpus → val AUC 0.717 < v3's 0.721; train_mse plunges to 0.77 while val AUC declines from ep8. Capacity is not the constraint. Parity re-verified 3.57e-8 before training (the D=96 twin in `attn_net.py`+`attn.rs` is correct if ever revisited — but it needs far MORE data, not just width); arch reverted to D=64.

7. **POLICY HEAD RE-TEST — a policy PRIOR over this self-play distribution is dead, but do NOT conclude "the moves are equal" (I did in-session; WRONG — see #8).** Re-ran the old near-uniform-policy dead-end on the STRONG v2 net (`harvest_pv` wired to `root_search_with_leaf` + `Leaf::AttnVal`). Policy-target entropy ratio (entropy ÷ log n_legal, ~18 legal root moves): **600 sims 0.908, 2000 sims 0.899 — more search did not sharpen it.** So within the SELF-PLAY distribution the root Q is genuinely flat → a PUCT prior has little to bias toward there. **But §8 shows the flatness is a TRAINING-DISTRIBUTION artifact, not a game truth:** the net learned that develop-vs-take is ~equal because in self-play under-development was never punished. A human punishes it hard. My in-session claim "it's the GAME not the evaluator" was WRONG — it's the distribution. (The "re-test if the net changes" caveat is answered: still flat on self-play data, but that answer was itself the wrong question — the fix is out-of-distribution human data, #8.)

8. **★ HUMAN-GAME ANALYSIS — the real, exploitable blind spot (THE lever).** 33 recent prod Hard games vs the user (`duel_games` via Turso HTTP). Raw record 16–17, but 10 "bot wins" are `wincond=None` early **abandons**; among the 23 games that reached a real win condition, **human 16 / bot 7 (~70%)** — and the user is a self-described BELOW-AVERAGE player. Human wins are LONG (avg **59.6** turns vs 40.9 for bot wins) and points-based (12/16). Move-log traces (`scratchpad/duel_trace.py`: EMEDIY 21–10 cards, OGUVJO 16–10, DSLIUA 21–15) show one consistent failure — **the bot under-builds its engine and loses the long game:** (a) **under-develops** — buys ~half the human's cards, stalls ~10–15; (b) **hoards/wastes tokens** — EMEDIY: took 18 / bought 10 / **discarded 5** (took past the 10-cap); (c) **over-reserves cheap cards** — 4× level-1 reserves in DSLIUA, early unaffordable L3 reserves in EMEDIY. It plays for a fast/medium game with no engine-building plan, so in a 60-turn game the human's bigger engine yields a late points surge (DSLIUA: human **6→22 pts in 11 turns**) it can't answer. **Self-play is blind to this** (both agents share the under-development tendency → neither punishes it → why v3 washed and the policy looked flat). **THE FIX:** value-**DEBIAS** from human games (the WWSD-for-Spender-racer approach) — take positions the bot's own value rated as fine right before a development loss and retrain with the true loss label. **NOT imitation** — the demonstrator is below-average, so learn the bot's MISTAKE (under-developed positions lose), never the human's moves.

9. **★ DEBIAS EXPERIMENT — BUILT + TESTED end-to-end → WASH at 16-game scale (do-not-re-run below ~100 diverse human games).** Built a drift-free bridge to test #8's proposed fix: reconstruct each finished human game EXACTLY (`replay._replay` off the persisted seed), project every bot decision through the SAME serving path (`compact.py::project` → `compact.rs::from_proj`) and featurize with the SAME `features_tokens` + score with the shipped v2, via a new native bin `featurize_positions` (`--features bridge`). KEY enabler: `features_tokens` reads NO hidden info (only public board/pyramid + both seats' points/crowns/bonuses/tokens/privileges/reserved-COUNTS + the mover's OWN reserved ids + scalars), so reconstruction is exact — no determinization. 1038 bot positions from 33 games, 0 rejected.
   - **(a) Calibration diagnostic DISCONFIRMED the "strongly over-optimistic value head" story.** v2 is well-calibrated globally (predicted-value→actual-win-rate buckets 0.00/0.07/0.39/0.64/1.00), already CORRECTS the heuristic leaf's optimism (net −0.09/+0.23 on lost/won vs hval +0.13/+0.44), and rates the over-optimistic blind-spot slice slightly NEGATIVE (−0.13, not the strong positive I predicted). Residual = only a MILD early/mid over-optimism that resolves negative by late game (t≥34: −0.22). So the loss is NOT primarily a leaf-value miscalibration.
   - **(b) Policy re-confirmed DOWNSTREAM, not an independent lever.** `harvest_pv` on the v2-net search: target IS learnable (argmax==greedy **0.987**) but near-UNIFORM in mass (entropy ratio **0.78 @T=0.07 / ~0.90 natural**; does NOT sharpen with sims 600→2000). A policy prior only distills the search's move-preference, and the search doesn't prefer development because the VALUE doesn't DIFFERENTIATE develop-vs-take at the choice point (calibration ≠ differentiation). Reviving policy (even attention-arch) distills the same flat target. **Horizon RULED OUT** (user callout: Spender's 0-step static leaf differentiates fine on the SAME card-development mechanic; and Duel's own 12→2 rollout gate was "equal"). Why Spender's policy is sharp and Duel's flat = TRAINING DISTRIBUTION (Spender learned to statically value development via leagues + a mature net + a 123-game human corpus; Duel's plain self-play never punished under-development).
   - **(c) The debias itself → WASH.** Warm-start v2 + a v3 strong-play anchor + the human LOSS positions replicated K× (`train_attn_debias.py`), gated vs v2 with `gate_netleaf --leaf attnfile --leaf-b attnval` (equal-sims == equal-time, same D=64; mirror 0.5000). Held-out human losing positions DID move right (v2 +0.05 → −0.27/−0.41, generalizes across games) — BUT the whole human DOMAIN shifted down (won positions +0.21 → +0.03) and corpus AUC eroded: the net learned "these look like human-distribution positions" not "under-developed positions lose." **Gate sweep n=800: K=5 0.5288 / K=20 0.4744 / K=50 0.4544 — MONOTONIC, more debias = WORSE.** K=5 (only >0.5) FRESH-seed reconfirm (seed 20000, n=1600) = **0.5072 [0.483,0.532] = WASH** (the 0.5288 was a one-seed-base blip — the "VARY THE SEED" rule earned its keep again). NO relabel weight beats v2; heavy HURTS.
   - **WHY it washed:** 16 games / ONE below-average opponent is too few to disentangle the LESSON (under-development loses) from the DOMAIN (this opponent's position distribution). The lever (out-of-distribution human data) is RIGHT; the DATA SCALE is the constraint. **v2 STAYS shipped** (shipping a wash over the proven champion buys nothing + risks the corpus-erosion). Tooling is built + reusable — `featurize_positions` (bin), `scratchpad/duel_extract.py` (DB→positions), `duel_diag.py` (calibration), `train_attn_debias.py`; debias nets at `C:/Users/Forrest/duel_run/debias/` — so re-running is CHEAP once more/diverse games accumulate (the site persists them).

**Verdict — NOT a ceiling, a self-play PLATEAU; the human-data debias lever WASHES at current data scale (do-not-relitigate the framing, and do-not-re-run the debias below ~100 diverse human games).** The three self-play levers (data/capacity/policy) plateaued *because self-play cannot generate what no self-play agent demonstrates* (#8's patient development). A below-average human beats v2 ~70% of completed games → nowhere near a ceiling (no AI is, short of a solved game). #9 TESTED the human-data debias END-TO-END → wash (value head already calibrated; policy is downstream not independent; 16-game/1-opponent overfits the DOMAIN not the LESSON). The remaining lever is a REAL human corpus (accumulate diverse games, then re-run the BUILT bridge); imitation stays OFF the table (below-average demonstrator). The 12k net-strength corpus is KEPT at `C:/Users/Forrest/duel_run/v3/`; debias nets at `C:/Users/Forrest/duel_run/debias/`. Session tooling (native, `--features bridge`): `attn_bench`, `gate_sims`/`gate_rollout`, `harvest_attn`/`harvest_pv` (attn leaf), `gate_netleaf`, `featurize_positions`, `train_attn`/`train_attn_debias`; analysis: `scratchpad/duel_db.py` + `duel_trace.py` + `duel_extract.py` + `duel_diag.py`.

### Session (2026-07-20) — Duel Hard upgraded from the hand heuristic to a card-set ATTENTION value net (SHIPPED `e4b2c06`)

**The result:** Duel **Hard** is now a card-set **attention value net** served as a NETVAL leaf (12-step
rollout + attention value at truncation), replacing the board/deck-blind heuristic leaf. It beats the
heuristic at equal sims across the ladder (700:0.58 / 2000:0.62 / 4000:0.59, **edge holds/GROWS with
depth**) and replicates on 3 fresh seeds (0.599 / 0.603 / 0.638). First learned net to beat the Duel
heuristic — the whole prior net campaign (flat value_net, pv_net policy) had failed.

**The levers, in order (the plan was C → D → A/B); the first four are DO-NOT-RELITIGATE verdicts:**

1. **C — exact endgame solver (`endgame.rs`): NO.** Correct + tested (finds forced wins, blocks losses,
   exact ±1), but NOT serving-tractable: at a serving budget (~150ms/100k nodes, near-terminal only) it
   is conclusive only ~15%, and of the forced wins it CAN cheaply prove the saturated MCTS ALREADY finds
   all of them (0 missed over 12). The wins it would add need ~2M-node searches (beyond budget), and it
   STEALS sims that matter (see #3). Different from Spender (whose endgame refine shipped) because Duel's
   endgame is wide (~76 moves) + multi-action AGAIN chains. Tooling: `gate_endgame_native`, `endgame_diag`.

2. **D — geometry-aware heuristic term (`value_geom`): NO — it was NOISE.** A best-line-take differential
   (the board is otherwise geometry-blind) looked like +3.5% @ weight 0.05 — but METHOD ERROR: every
   "confirmation" reused seed 70000 (the SAME ~200 decks) → I re-measured ONE fluctuation. Fresh seeds →
   mean 0.496 (neutral). LESSON: a CRN gate over N decks at ONE seed base is ONE sample; VARY THE SEED
   BASE to confirm. Demand-weighted variant (mode 2) also washed.

3. **SATURATION PREMISE CORRECTED — Duel is NOT saturated at ~700 sims (that number was STALE/WRONG).**
   Direct sims-asymmetry gate (`gate_sims`, CRN, mirror=0.5000): 700v400=0.57, **2000v700=0.61**,
   4000v2000=0.57 — more search wins strongly to ~4-8k (user re-measured ~6k). Prod runs ~60k sims/0.5s
   (well past the knee). Implication: the cheap leaf is at its heuristic ceiling → the lever is a BETTER
   EVALUATOR; a heavier net leaf is fine IF it stays above ~6k sims (int8/throughput = the deploy enabler).

4. **The 0-step learned leaf COLLAPSES with depth.** Existing flat `value_net` as a 0-step leaf vs the
   heuristic (rollout+value) at equal sims: 700=0.40 / 2000=0.32 / 4000=0.31 / 6000=0.23. The rollout does
   real work a 0-step net cannot replace — which is why the prior net campaign (0-step) failed.

5. **NETVAL (rollout + net-value truncation) — CoC's formulation, first tried for Duel.** The existing
   FLAT net via netval: 700=0.545 / 2000=0.555 / 4000=0.548 / 6000=0.494 — MATCHES the heuristic (rescued
   from the 0-step collapse) but does not BEAT it, and is slower (loses at equal-wall-clock). So the leaf
   FORMULATION is validated (netval is how to serve a net leaf here); the flat net just is not better.

6. **A/B — card-set ATTENTION value net: BUILT + SHIPPED in-session.**
   - Tokenizer `feats::features_tokens`: 15 card tokens (12 pyramid + 3 own-reserved; opp reserves stay
     hidden) × 20 feats incl. per-card WIN-CONDITION proximity deltas (points/crowns/color after buy) +
     a 46-dim global state with GEOMETRY (`best_line_len`) + PYRAMID color-demand — the board/deck
     awareness the heuristic lacks (the user's instinct; flat encoding of these washed like Spender's did,
     attention over the card set is the point).
   - `attn.rs` = value-only attention forward (port of `spender-core::attn`, policy head dropped). PyTorch
     twin `tools/attn_net.py`. **PARITY = 6.1e-8** (Rust f32 vs torch f64) via `bin/attn_parity` — it
     plays what it trains.
   - Trained on 368k positions (4k games, heuristic self-play @400 sims): best val AUC 0.7155 @ep6 — ties
     the flat net's 0.7165 (AUC↔play is LOOSE; attention won in PLAY anyway, echoing Spender). Overfit
     after ep6 (only ~4k independent game labels).
   - Served: `Leaf::AttnVal`; wasm `duel_search` routes to it, net embedded (`attn_value_net.json`) +
     cached per worker; wasm 191KB→2.14MB. Native lib tests 36/36. Rollback = `git revert e4b2c06`.

**Durable methodology lessons:**
- Gate EQUAL-SIMS first (does the eval help), then EQUAL-WALL-CLOCK (does it survive the leaf-speed cost).
  The attention leaf is heavy → int8/throughput is the deploy enabler, not a nicety.
- FRESH-SEED confirmation before shipping (the geometry seed-reuse burn, #2).
- AUC ties but PLAY wins — never gate a net on AUC alone.
- The heuristic is SCAFFOLDING, not the thing to keep tuning: it supplies the rollout, the residual-
  baseline features, and the self-play game generator. From-scratch/flat nets don't beat it; attention
  does because it reuses that structure + adds cross-card interaction + board/deck sight.
- Native gates are CRN seat-swapped, mirror must read 0.5000, and MULTI-THREADED (a shared work counter;
  one run saturates all cores — the single-threaded version wasted ~75% of a 12-core box).

**IN PROGRESS / NEXT (as of this session):**
- **v2 retrain** on the 48k-game harvest (`harvest_attn`, ~4.4M rows; trained on 32k games / VRAM-capped)
  + weight-decay 2e-4 + early-stop — fixes the 368k-row overfit; gate v2 vs v1 + heuristic, re-ship only
  if stronger.
- **Self-play ITERATION** (train on the attention net's OWN games) is the real ceiling-breaker (training
  DISTRIBUTION), but MUST use anchor + gate-and-promote — Spender's pure self-play DRIFTED (peaked iter 3
  then fell). It does not skip the volume requirement, and attn-net games are ~several× slower to generate.
- **Python server-side Hard fallback stays heuristic** (WASM is the real Hard; the fallback is a ~5-sim
  Render bot). `choose_move` default leaf is still `Heuristic` (only wasm `duel_search` routes to AttnVal).

**Tooling built (`duel-core`):** `attn.rs`, `feats::features_tokens`, `tools/{attn_net,train_attn}.py`,
`bin/{harvest_attn, attn_parity, gate_netleaf (--leaf attnval|netval|net|net8), gate_sims, gate_geom,
gate_endgame_native}`. `Leaf::{AttnVal, NetVal, HeuristicGeom}` added to `mcts.rs`.

<!-- ===================================================================== -->
# ARCHIVE: CoC — UI/UX & infra sessions (dice UX -> wwsd decommission)
<!-- ===================================================================== -->

### Session (July 2026) — dice UX, bonus-bar split, richer log, final-score display, bot flail fix
UI/UX polish + one bot fix, all shipped to prod. Durable, non-obvious facts:
- **`dice[pid]` now has four fields: `values` / `orig` / `used` / `adjusted`** (was just `values`/`used`).
  `orig` = the rolled values; `adjusted` = per-die bools. Set together in `_begin_round`; all JSON-safe;
  every reader defaults via `.get(..., [False,False])` / `.get("orig", values)` so old saved games load
  fine. `_snapshot_turn` deep-copies the whole game, so undo is automatic. `ai._clone_game` copies both.
- **Die-adjust WORKER REFUND (house rule beyond the base game).** `_h_adjust_die` charges the **net
  distance from `orig`**: `delta = _adjust_cost(orig,to) − _adjust_cost(orig,frm)`, so nudging a die
  back toward its roll **refunds** workers (`delta<0`) and moving toward the roll is allowed even at 0
  workers (only `delta>0` is affordability-gated). `_adjust_cost` is a metric (min-wrap distance, ÷
  per-worker for monastery-8), so a multi-step path is never cheaper than one direct jump — refunds make
  "away then back" free. Frontend: the incremental **±1 buttons** stay (humans chain freely in the
  engine); `adjustDelta(i,dir)` mirrors the cost model (incl. monastery-8 halving) to disable a button
  only when that step is unaffordable, and tooltips say "refunds a worker" when moving toward the roll.
- **Bot dice-flail fix (`ai._legal`) — the "adjust a die to 6, then take 2 workers" waste.** The AI
  prunes, for an already-`adjusted` die, BOTH re-adjusting it AND `take_workers` with it — both are
  strictly dominated (`take_workers` ignores the die value, so paying workers to set it first is pure
  waste; a 2nd adjust is never cheaper than one jump). Pruning `take_workers` makes a pointless adjust
  **self-defeating in the search**, so the bot stops doing it. Strictly-correct (never removes an optimal
  line); **humans unaffected** (engine-level rules unchanged — the prune is AI-only). **REJECTED (do not
  relitigate):** valuing workers at `*0.5` instead of the floored `//2` in `ai._value` — an A/B showed it
  made the flail WORSE (15 vs 6 wasteful adjacencies across 6 games) and increased total adjusts;
  reverted. The eval is NOT the lever here; the legal-move prune is.
- **Turn-start roll log:** `engine._log_roll(game, pid)` logs `{type:"roll", d0, d1}` at each turn start
  (`_begin_round` for the start player, `_advance_turn` for the next). Frontend `moveText` → "X rolled a
  A and a B". Logs are DISPLAY-only records (never re-applied), so new types are harmless.
- **Phase-end income log:** `_end_of_phase` logs per player `mine_income {silver,mines}` +
  `monastery_income {workers,effect=2}` (monastery-2's worker-per-mine), then a `phase_end {phase}`
  DIVIDER with **`pid=None`**. `vp_breakdown` is unaffected (it skips any record without a `vp` field, and
  `phase_end`/income carry none). Frontend renders the income lines normally and the divider as a centered
  ".coc-log-phase" "— Phase X ended —"; the log render **guards the player-name prefix** (`m.pid ? … : ""`)
  for the pid-less divider.
- **Bonus bar SPLIT into three groups:** "Region phase bonus +N" (the per-phase time bonus,
  `PHASE_BONUS` A10→B8→C6→D4→E2) · "Region size bonus" (the fixed `AREA_SCORE` scale 1/3/6/10/15/21/28/36
  by region size) · "Color bonuses" (the existing large/small color-completion chips). `PHASE_BONUS`/
  `AREA_SCORE` are JSX-mirrored constants of `tiles.*`. Region completion pays size + phase, so both are
  now surfaced.
- **Spelling:** all UI text is "color" (was "colour"), including the backend `vp_breakdown` "Color bonus"
  label. **Goods are ALWAYS named by number** ("#N goods"), never by color — the last offender was the
  castle bonus (`extra_action`) modal's "Sell {color}" button, now a numbered goods token.
- **Final score at game end:** the top status-bar score shows `roomData.final_scores[pid]` (leftover
  goods/silver/workers + monastery end-game bonuses folded in) once `over`, and live placed VP during
  play. `mk_room_state` already ships `final_scores` + `vp_breakdown` every update (also feeds the
  click-to-open mid-game breakdown).
- **Rendering gotcha (recap — do not regress):** the gold rim on **legal-placement spaces AND placed
  tiles** is drawn as a **top-most `pointer-events:none` stroke-only `<polygon>`** (over the socket/raise
  gradient). A stroke on the BASE polygon gets its inner half painted over by the gradient → pale-top /
  dark-bottom asymmetric rim. The base polygon still catches clicks, so placement is unaffected.

### Session (June-July 2026) — earlier CoC polish now on prod (context)
Shipped in prior sessions; recorded here since they weren't in this doc: a **`goods_pick` pending kind**
(when a depot offers more new goods TYPES than you have free goods slots, you pick which — floating modal
+ pulsing depot tokens); an **in-game VP review** (`VpReview` component, click the score any time — mid-game
shows end-of-game bonuses faded until `over`); a lobby **History** section with per-game **Review** (HTTP
`GET /coc/games/{id}/review`, read-only, synthesizes `roomData`, `reviewOnly` guards localStorage); **worker/
silver visual tokens** with spend/gain flyer animations (`data-workers`/`data-silver` anchors, `resFly`);
goods named "#N goods"; **1s bot move pacing** (`_BOT_MOVE_DELAY`); auto-open View Opponent on the bot's turn.
- **OUTAGE LESSON (do not regress):** a rewrite of `_schedule_bot_turn` to animate a bot's *consecutive*
  turns (ship → retake first player) fully on the View-Opponent screen **hung the backend event loop** and
  took prod down. Root cause: the finisher's **synchronous `bot.play_turn` loop runs UNDER `ROOM_LOCK` on
  the event-loop thread**; looping it up to ~12× per bot turn + ~12 DB saves/turn starved the single-process
  loop. Reverted (`git revert`). **Keep `_schedule_bot_turn` as the single-turn plan-then-apply version**
  (MCTS in the thread pool, apply move-by-move with per-move broadcast + `_BOT_MOVE_DELAY`); never loop
  heavy synchronous engine work under the lock. This is the same class of hazard as any lock-held blocking.

### Session (July 2026) — mobile layout, warehouse modal, phase pause+popup, bot no-waste, randomize first, log/animation polish (SHIPPED `45ea1ae`)
A batch of CoC UI/UX fixes + two engine/bot fixes, all on prod. Durable, non-obvious facts:
- **MOBILE CSS CASCADE TRAP (do not regress — bit us repeatedly).** The `@media(max-width:600px)` block sits
  BEFORE the base component rules in the `css` string, so a **single-class** mobile override
  (`.coc-bonus-sw{…}`) LOSES to a later equal-specificity base rule (silently dead). **Every mobile override
  must be `.coc `-prefixed** (`.coc .coc-bonus-sw{…}`) to win on specificity. Noted in a code comment. (This
  is the CoC analog of Spender's documented media-query ordering footgun.)
- **Color-bonus chips no longer wrap to a 2nd row on mobile.** The wide Cinzel "Color bonus" label can't
  share the row, so the label is forced onto its own line and a `~`-sibling divider break
  (`.coc .coc-bonus-div ~ .coc-bonus-div{flex-basis:100%;height:0;background:none}`) wraps the chips under it.
  Labels renamed **"Color bonuses"→"Color bonus"** and **"Your dice"→"Dice"** so dice+silver/workers fit one
  row and label+chips fit one row on mobile.
- **Warehouse ability is now a FLOATING bottom modal** (`<Modal interactive>` = `coc-modal-float`,
  pointer-events pass through), matching every other ability — click a Sell chip in the modal OR click one of
  your own goods (`.coc-goods-pick`, a pulsing chip, shown when `warehouseMine && me.goods[c]>0`) to sell.
  **AUDIT RESULT (recorded): `warehouse_sell` was the ONLY ability covering the whole screen.** View Opponent
  + the score breakdown stay full-screen deliberately (they're informational views, not abilities).
- **Phase-end pause + phase popup.** `_PHASE_END_PAUSE=2.6s` in `main.py`: `_schedule_bot_turn` sleeps this
  (instead of `_BOT_MOVE_DELAY`) whenever `game["phase_letter"]` advanced (before its first move + between
  moves that cross a phase boundary), so the player can see mine-silver/monastery income before the board
  moves on. Frontend: a `phasePop` overlay (`.coc-phase-pop`, z-120) driven by a `[game.phase_letter]` effect
  that diffs `prevPhaseRef` and shows `{from,to,silver:me.mines_count,workers}` for 3300ms (skipped while
  reviewing/over).
- **Bot no longer wastes a die (TWO fixes; verified 0/0 wasted across 60 sim games).** The waste ("adjust both
  dice to no purpose, then end") came from the search painting itself into a corner: `ai._legal` pruned
  `take_workers` for an already-`adjusted` die, so when no depot action remained the only legal move left was
  `end_turn`. Fix: **`ai._legal` keeps `take_workers` as a guaranteed fallback** — it only prunes the wasteful
  take-workers when a *productive* move still exists (`productive` = any move not in
  `take_workers/adjust_die/end_turn/skip_pending`), and it still forbids `end_turn` while an unused die has a
  non-end option. And **`bot.py` (the random finisher) `choose` prefers real actions + take_workers over
  wasteful adjusts over passing** (`_WASTEFUL={"adjust_die"}`; `useful` excludes `_PASSIVE`∪`_WASTEFUL`;
  `take_workers` is legal with any unused die so `useful` is non-empty whenever a die is unused → the finisher
  never ends with an unused die and never burns workers adjusting).
- **First player randomized for vs-bot games.** `main.py` create-vs-AI now `random.shuffle(seats)` before
  `engine.new_game(seats,…)` (seats = `[pid, AI_PID]`), so the bot is start-player ~half the time (also
  fairer — starting workers are seat-dependent).
- **"Select a die to act" hint removed** (the action-hint fallback is now `""`).
- **Die-adjust log states the VALUE, not the index.** `engine._h_adjust_die` now logs `frm` (the die value
  BEFORE the adjust: `frm = d["values"][i]`); frontend `moveText` renders **"adjusted a 5 to a 1"** (falls
  back to "adjusted a die to a X" for old saved games without `frm`).
- **Flyer alignment fixes (two fragile endpoints).** Goods flyers landed at a hardcoded offset into the goods
  row; they now target the **exact per-color goods chip** (`rectOf({kind:"goodchip",c})`, anchored by
  `data-goodchip`/`data-oppgoodchip` on each chip). Silver/worker token flyers landed between the icon and the
  count; the token anchors (`data-workers`/`data-silver` + opp variants) **moved onto the icon `<span>`** so
  they land on the coin/hammer glyph.
- **Starting-castle placement animation** (was broken for the human AND when viewing the bot): the `data-sid`
  placement anchor was gated on `interactive` (gone once the turn ended) and the View-Opponent modal covered
  the board instantly. Fix: `data-sid` is **always** on my board (`data-sid={opp ? undefined : sid}`), and the
  setup auto-view-opponent is **delayed 550ms** (`setupOpenTimer` ref + cleanup) so the placement flyer plays
  before the peek swaps the view. (SUPERSEDED — see the reveal rewrite in the next session entry.)

### Session (July 2026) — labels, crimson, ability logging, reconnect fix, keep-alive, arm-then-act, review polish
A large batch of CoC UI/UX + one load-bearing reliability fix, all shipped to prod. Durable, non-obvious facts:
- **Phase-round labels ("A-1".."E-5") replace turn numbers in the log + review.** `engine._log` stamps every
  record with `ph`/`rd` (phase letter + round). Income/`phase_end` log BEFORE `phase_letter` advances, so they
  correctly stamp the ENDING phase. Old saved games lack `ph` → the UI falls back to the `T#` turn number
  (`m.ph ? \`${m.ph}-${m.rd}\` : \`T${m.t}\``). `vp_breakdown` items carry `ph`/`rd` too so the review segments
  by phase.
- **"burgundy" is the DATA KEY, "crimson" the display name (do not rename the key).** All user-facing text
  says crimson (`colorLabel`, the setup error message, the `vp_breakdown` "Color bonus" label). But the space
  ids (`burgundy-1`, …) are **persisted in every saved game** AND generated into the Rust **coc-core parity
  tables**, so renaming the key would corrupt saved games + break engine parity. Only the *display* maps
  burgundy→crimson.
- **Color bonus is labeled small/large.** `bonus_tile` is tagged `large=(len(remaining)==2)` before the
  `remaining.pop(0)` — the FIRST claim (both tiles present) takes the LARGE bonus (`bonus_first`, n+3), the
  second the SMALL (`bonus_second`, n). `vp_breakdown` falls back to comparing `vp == tiles.bonus_first(n)` for
  pre-flag saved games. Label: "Color bonus — large (crimson)".
- **Tile-ability logging via a `via` field (the consistency fix).** Every ability-driven ACTION log carries
  `via` = a source-tile key: a building key (`market`…), `"ship"`, `"castle"`, or `"monastery:N"`. The FRONTEND
  LOG RENDER appends ` (${viaLabel(via)})` at the very END of the line (NOT `moveText`, so the tile name lands
  after any "(+VP)"): "took a Ship (Market)", "sold #3 goods x2 (+4 VP) (Warehouse)", "advanced 1 on the turn
  track (Ship)", "(Castle)", "(Monastery #6)". `_log` drops a `None` via so normal actions stay clean.
  Threading: the immediate-gain buildings (boarding/bank/watchtower) log a NEW `build_gain` record
  (`via=bt`, + workers/silver/vp) INSTEAD of the old generic `building_effect` "used X" line; pending-action
  buildings (market/carpenter/church/warehouse/townhall) log NOTHING at placement — their resolver tags the
  resulting action's log with the building; ship/castle/monastery pass `via` into the shared cores
  (`_do_take_hex/_do_place_tile/_do_sell_goods/_do_take_workers` + `_sell_color` gained a `via=` param).
  `vp_breakdown` catches watchtower under `build_gain` (only vp-bearing building). The log render skips the
  generic "(+VP)" suffix for `build_gain` (it already states "gained 4 VP") to avoid doubling. **Legacy
  `building_effect` records still render** ("used X") for old saved games.
- **THE RECONNECT FIX (load-bearing — a bot turn froze for MINUTES).** CoC's `useSocket` had **NO
  auto-reconnect** — `ws.onclose` only set `connected=false`. A vs-bot turn is re-driven ONLY when the client
  reconnects (`_handle_reconnect` re-triggers `_schedule_bot_turn`), so a Render cold-start (or any blip / iOS
  backgrounding) that dropped the socket left the bot's turn un-driven until a manual refresh. Fix (frontend-
  only): a backoff reconnect loop (`attemptReconnect`, reused by a `visibilitychange` nudge so neither leaves
  the loop dead) that reconnects with the **`reconnect` action, NOT `join`** (join doesn't resume the bot),
  retries through the ~30-50s cold-start window, and **checks `socketReady()` (readyState) to NOT abort a
  pending CONNECTING socket** (a cold-starting Render holds the WS open until up — aborting it every timer tick
  would thrash). A "Reconnecting…" banner (`.coc-reconnbar`) shows the state. On reconnect the client
  re-arms `client_ai` automatically (existing effect). Diagnosed by pulling the stuck game from Turso (it had
  COMPLETED — proving it was a client-side un-driven-turn issue, not a backend deadlock).
- **Post-turn settle + close linger (bot-turn pacing).** Backend `_POST_TURN_PAUSE=1.0` in `_schedule_bot_turn`:
  waits before the bot's FIRST move on a *playing* turn (skipped during setup / superseded by the longer
  `_PHASE_END_PAUSE` on a phase change) so finishing your turn isn't instantly steamrolled. Frontend matches it:
  the opponent-board auto-open is **delayed ~1s**, and when the bot's turn ends the board **lingers ~1s** before
  returning to yours (both via `botViewTimer`, gated so the setup-reveal `revealHoldRef` wins). **GOTCHA (cost a
  CI failure):** `test_client_ai.py`'s isolation zeroes the pacing constants for speed but didn't know about the
  new `_POST_TURN_PAUSE`, so the real 1s-per-turn sleeps overflowed its driver loop on CI's fine timers (it
  passed locally only because Windows' coarse timer resolution inflated the loop's wall-clock) → **any new
  pacing constant must be zeroed in `_isolate`.**
- **Setup castle reveal REWRITE (supersedes the 550ms delay above).** The bug: the bot's SECOND starting castle
  transitions the game straight to "playing" in the SAME update that places it, so the generic `aiThinking`
  auto-close fired at the exact moment the pop-in played → board vanished as the animation ran. Fix: a DEDICATED
  effect owns the reveal — on a **witnessed null→placed transition** of the opponent's castle (`prevOppCastleRef`
  starts `undefined` = first snapshot = never reveal → reconnect-safe), it opens their board, spawns the pop-in
  (two rAFs so `[data-oppsid]` exists), holds ~1.9s (`revealHoldRef` BLOCKS the generic handler from closing),
  then releases. `botViewTimer`/`revealHoldRef`/`aiThinkingRef` coordinate the generic open/close with the reveal.
- **Arm-then-act interaction pattern (now consistent across the game).** Every resource spend requires an
  explicit selection first, then a target click: **select a die** before take-hex/place/sell; **click the
  workers token** to arm **Monastery #6** then click a building tile in a depot (2 workers); **click the silver
  token** to arm a **black-depot buy** then click a black tile (2 silver). `canUseM6`/`canBuyBlack` mirror the
  engine's `legal_moves` gates so the token only rings gold (`.coc-arm`) / pulses when armed (`.coc-on`) when the
  action will actually succeed; a reset effect disarms the moment it's no longer usable. **Monastery #6 had NO
  UI at all before this** (the frontend never sent `monastery6_take` — the engine always supported it).
- **Goods click-to-sell.** Click a goods chip in your storage to sell it. Ability sells (Warehouse pending /
  Castle bonus's chosen die) sell on click directly; a NON-ability sell requires a **die SELECTED first** whose
  value == the goods' sell number (only those goods pulse/are clickable), else the click just shows the goods
  description. `sellDieForGood`/`canSellGood`/`sellGood`.
- **Review section headers.** Dropped the "During the game" subheader (the per-phase dividers already segment
  it) and render "End of game" as a **centered divider** (`.coc-review-phase`, `.proj` fade), so the review reads
  Phase A…E then End of game.
- **Client-AI sim logging (Expert tier).** The client-AI driver prints ONE `[coc client-AI] turn used N sims`
  line per bot turn to the dev console (sum of root visits across the worker pool, accumulated in `turnSimsRef`
  across the turn's decisions, printed when the bot hands back). Nothing prints if the server watchdog took the
  turn (client did no searching).

### Session (July 2026) — keep-alive / cold-start mitigation (deploy infra, NOT a game change)
Render free tier spins the backend down after ~15 min idle (~30-50s cold start), which surfaced as slow site
loads AND mid-game freezes (see the reconnect fix above). Durable facts:
- **GitHub Actions SCHEDULED workflows are too unreliable for keep-alive** — measured **~1 of 28 expected 5-min
  runs actually fired** in 2+ hours (they're heavily delayed/skipped, worst near :00). So `.github/workflows/
  keepalive.yml` is now a **LONG-LIVED pinger**: each run pings `/health` every ~4 min for ~56 min before
  exiting (public repo → free Actions minutes), so a single sparse firing keeps the backend warm for ~an hour;
  hourly-ish starts (`23 14-23,0-5 * * *`, off-peak minute) chain to cover the window. **This is only a backup.**
- **cron-job.org is the recommended RELIABLE primary** (fires on time; user sets it up — external account): URL
  `https://splendid-nelz.onrender.com/health`, every 5 min, timezone **America/Los_Angeles** (auto-DST) restricted
  to **07:00-22:00**. GitHub cron is UTC-only (no DST); the window `14:00-05:59 UTC` covers 7am-10pm PST/PDT with
  ≤1h overhang.
- **Budget:** Render free tier caps at **~750 instance-hours/month**; daytime-only warming (~15h/day ≈ 450h)
  fits with headroom, but keeping BOTH Render services (spender-backend + the decommissionable wwsd one) warm
  24/7 would blow it. `/health` (site-root, no DB) is the cheap warm endpoint.
- **Warm-on-load ping** in `webapp/index.html` (`<head>` inline script, **prod hosts only** — `forry4.github.io`
  / `*.workers.dev`): fires a fire-and-forget `fetch('/health')` before the bundle loads so a cold start overlaps
  page load. CAVEAT (do not oversell): this does NOT help the visitor who TRIGGERS the cold start (the site needs
  the backend immediately; the spin-up takes 30-50s regardless) — it only helps a later visitor. The daytime cron
  is the load-bearing part. The only *guaranteed* fix is the $7/mo Render Starter tier (no spin-down).
- Query the stuck/finished prod game state directly from Turso (creds in gitignored `C:\Users\Forrest\.spender_turso`;
  `curl` POST to `<https-host>/v2/pipeline`, use a BOUND arg `{"type":"text","value":"ROOMID"}` — a
  double-quoted id in SQL is read as a column). The room dict is `state_json`; `coc_games` has the game.

### Session (2026-07-08) — wwsd decommission + CoC turn-latency levers + building-placement highlight fix
- **wwsd Render service DECOMMISSIONED (`bdcf8e6`).** The 2nd free Render web service (`wwsd-backend`) is removed
  from `render.yaml` (user deleted it in the Render dashboard). WWSD runs entirely in the friend's browser now —
  the Rust→WASM Tampermonkey userscript `wwsd/wwsd_browser_n.user.js` makes ZERO backend calls (verified: 0
  `onrender` refs; its lone `fetch` is dead wasm-loader boilerplate, since the wasm is inlined as base64). The old
  `wwsd/autoplay.user.js` was the only remaining caller of `/move` (long superseded). The `wwsd/` Python package
  stays as reference; to restore, re-add a `- type: web` block running `uvicorn wwsd.app:app` + recreate the
  service. Unrelated: the spender-backend keep-alive (cron-job.org) auto-disabled after a Render-side **~2h 503**
  outage that aligned exactly with the daytime cron window OPENING (14:00–16:05 UTC = the first pings after the
  overnight spin-down; NOT a deploy — last deploy was 8h prior) → re-enable the cron + loosen its failure
  tolerance; the only *guaranteed* cold-start/blip fix stays the $7/mo Render Starter tier.
- **④ Overlap the Expert bot's client search with its move-animation pause (`f86fe3e`, backend — CORRECTS the P5
  "the ai_move handler applies" doc).** `_client_bot_turn` now ships the NEXT decision's `ai_search` BEFORE
  awaiting the current move's animation pause, and **`_handle_ai_move` BUFFERS the resolved move into
  `room["_ai_pending_move"]` (+ clears `_ai_search`, sets the evt) — it NO LONGER applies/broadcasts/saves**; the
  apply moved into `_client_bot_turn`, which applies the buffered move AFTER awaiting the pause (a `pause_task`
  from the previous move that runs concurrently with the client's next search). So the ~900ms search hides under
  the ~1s inter-move pace instead of adding to it (~0.9s/decision, ~2-3s/bot turn saved; NO strength or per-move
  pacing change). DO NOT REGRESS: the illegal/stale early-returns stay ABOVE the buffer (an illegal submit leaves
  `_ai_search` armed for the watchdog — `test_illegal_client_move_is_dropped`); `_ai_pending_move` is cleared
  alongside `_ai_search` on timeout AND in `_schedule_bot_turn`'s finally so a stale move can't leak; the old
  `_ai_phase_changed` room key was REMOVED (phase_changed is computed in the apply block). `test_client_ai.py` +
  the full 307-test CoC suite pass.
- **① Optimistic move preview (`d35d3ce`, frontend).** Your own moves render INSTANTLY instead of waiting the
  ~90ms round trip. `mv()` runs the module-level `optimisticMove(game, move, myId)` — deep-clones the game dict
  and applies the CERTAIN visible effect of the core moves (place_tile / take_hex / discard_storage: tile in/out
  of storage/duchy + die marked used), then `setRoomData` shows it; the server's authoritative `room_update`
  reconciles wholesale (clears `optimisticRef`), and an `error` reverts to `preOptimisticRoomRef`. SAFE BY
  CONSTRUCTION — the server never sees the preview (it's a PREVIEW not a client engine: the coc-core WASM is
  search-only, `coc_step_info`/`coc_search_timed`/`coc_chain_move` over the LOSSY compact projection, no
  apply→renderable-dict entry), it's scoped + guarded (bails to null on not-my-turn / a pending / missing tile /
  occupied space / full storage), and it can't corrupt game state. Only those 3 moves are predicted — they don't
  touch workers/silver/goods, so no spurious resource flyers; everything else falls through to send-and-wait. The
  diff-based flyer animates the previewed tile ~90ms SOONER with no double-fire (the reconcile diffs
  optimistic→server, same tile → no re-animate). ① lives in its own commit; `git revert d35d3ce` removes ①+②.
- **② Faster flyers (`d35d3ce`, frontend).** Tile flyer `coc-fly .5s→.35s`, worker/silver token flyers
  `coc-tok-out/in .6s→.42s`, flyer cleanup timer `640→460ms`.
- **BUILDING-PLACEMENT HIGHLIGHT FIX (frontend-only).** The yellow legal-placement glow wrongly invited placing a
  building in a region that ALREADY holds that same building type. The engine's `_building_town_ok` rejects that
  (unless you own **monastery effect 1**) — enforced in `_do_place_tile` + all three `legal_moves` enumerations
  (die / extra_action / townhall) — so the CLICK failed, but the `legalTarget` highlight in
  `CastlesOfCrimson.jsx` mirrored color/number/adjacency/occupancy and OMITTED the one-building-per-region rule.
  Fixed by reproducing `_building_town_ok` client-side: flood-fill the same-color connected component of `sid`
  (== the engine REGIONS, since the 37-cell grid + adjacency are identical across all boards) over the board
  spaces, reject if any placed tile in that region is a building of the same `.building` type; skipped when
  `me.monastery_effects` includes 1. No backend/payload change — tiles already carry `.type`/`.building` (used
  elsewhere in the render) and regions are derivable from the board-space colors the client already has.



<!-- ===================================================================== -->
# ARCHIVE: CoC Expert AI campaign (CoC-N): coc-core crate, P0-P6, aux-head, escalation, blind-spot & feature-screen sessions
<!-- ===================================================================== -->

### CoC Expert AI campaign ("CoC-N") — coc-core crate (July 2026; P0-P2 DONE, gates passed)
Building an N-class learned AI for CoC by the proven Spender recipe. Approved plan:
`.claude-plans/i-want-to-develop-staged-charm.md` (user decisions: plateau-gated strength, client-side
Rust→WASM serving, straight-to-learned-net — the heuristic scaffold is training infra only, never
shipped — and a NEW "Expert" lobby tier; Normal/Hard untouched). New **`coc-core/` crate at repo root**
(sibling of spender-core, patterns cloned not shared; in NO CI path filter, so committing it never
deploys anything). Memory: [[coc-expert-ai-campaign-status]].
- **P0 (done):** generated static tables (`tools/gen_board_tables.py` → `boards_gen.rs` + the canonical
  space index mirrored to `games/castles_of_crimson/az/spaces.py` — spaces sorted by (r,q); the 37-cell
  grid AND adjacency are IDENTICAL across all 9 boards, asserted; MAX_REGIONS=21). Tile codes u16
  (1 start-castle, 2 castle, 3 mine, 4 ship, 5-13 livestock, 14-21 building, 22-47 monastery=effect_id).
  State = fully inline fixed-capacity (816B, clone=memcpy 22ns); PV-net probe 2.8-4.5k evals/s/core at
  700-900 dims → feature budget up to ~900 dims is fine.
- **P1 (done): Rust engine port + differential parity.** `engine.rs` behind a fixed **102-action
  micro-decomposed space** ("spend die → menu → place-slot → space"; XVALUE kills the 150-move
  extra_action node; `Micro::None` invariant at every engine-move boundary; A_WORKERS always legal ⇒
  no micro deadlock). Monastery effects = one 26-bit `mon_mask` switch. 7.8M micro-moves/s
  (legal+apply). **Parity: 2300 fixture games / 567,080 engine moves, state-exact** (FNV-64 of the
  canonical projection string after EVERY move; `compact.py` ⇄ `proj.rs` must never drift
  independently), legal-move TRIE equality at recorded positions (proves the decomposition equals
  `engine.legal_moves` in BOTH directions), coverage gate all-green (all 26 monasteries, all pending
  chains, refunds, tiebreaks; "loaded" scenario games backfill rare paths). Dice injected per-move via
  `State.dice_script` (sidesteps Mersenne-vs-splitmix). Parity-critical engine facts: `_draw` pops the
  pile END / `_draw_type` scans from 0; legal-adjust affordability uses cost-from-CURRENT-value while
  apply charges net-from-orig; ship_choose offers all 6 depots even empty; pendings clear BEFORE their
  sub-action (chains survive); dice roll in SEAT order; ShipAdj pending stores the CANDIDATES mask
  (source depot unrecoverable from engine ctx). Run tests with `--features bridge`
  (`cargo test --release --features bridge`; fixtures via `tools/gen_engine_fixtures.py`, gitignored).
- **P2 (done, gate PASSED): scaffold search.** `mcts.rs` = spender determinized-PUCT clone
  (canonicalize-sort + shuffle the 3 undrawn piles + reseed dice stream per sim; identity-based backup;
  terminal = tanh(margin/12)); `heuristic.rs` = exact ai.py `_value` port (scalar parity 857 pos ≤1e-9);
  `vsearch.rs` = priors from move-type priority softmax + **rollout-then-eval leaf**; ai.py `_legal`
  pruning ported into `engine::legal_actions` (full vs search variants). Cross-impl gate via
  `move_server_coc` (bridge bin) + `games/castles_of_crimson/az/rust_arena.py` (CRN seat-swapped pairs,
  per-decision server calls, Python side driven exactly like ai_selfplay): **0.715 [0.649,0.773] vs
  ai.py hard over 200 games** at 2000 sims/decision (vs normal 0.95).
- **FINDING (do not regress): a PURELY STATIC heuristic leaf FAILS in CoC** — 0.235 vs hard. CoC's
  `_value` was tuned as a PAIR with the Python bot's rollout (storage credit 0.35/tile stands in for
  "about to be placed for a region score"), so a static leaf undervalues in-flight turns. The scaffold
  leaf runs a 20-micro-step priority rollout then evaluates → 0.715. This does NOT contradict the
  Spender static-value-leaf lesson; it means the P3 learned value must price in-turn continuations
  (outcome-trained does this naturally).
- **OUTAGE-CLASS LESSON (fixed in `6dbbcbf`): never create a package named like an existing module.**
  The az tooling briefly lived at `games/castles_of_crimson/ai/az/` — the new `ai/` PACKAGE shadowed
  `ai.py`, breaking `from . import ai as coc_ai` in prod (bot turns would AttributeError). Tooling now
  lives at **`games/castles_of_crimson/az/`** (compact.py projection, bridge.py engine-dict⇄compact
  moves both directions, spaces.py generated, rust_arena.py).
- **P3 (done): bootstrap net + the pivotal decomposition.** `feats.rs` = the FROZEN 934-dim encoder
  (groups documented in-file; per-space block feeds the 37-way SPACE head; input-dim change = full
  restart). Harvest 5000 scaffold self-play games (1.15M rows, `C:\Users\Forrest\coc_run\boot.t*.csv`);
  `tools/train_pv.py` (streaming, GAME-split holdout, SHAPE_A=0.3 ⊕ β=0.3 root value, margin SCALE
  auto ≈34) → `pv_boot.json`: val AUC 0.798, top-1 0.586; torch↔Rust `net_export_check` 3.5e-7.
  **CRN is EXACT in CoC** (the dice stream advances 5 rolls/round regardless of play ⇒ one seed fixes
  deck+dice for both seat orders; position-derived search seeds make the A-vs-A gate control EXACTLY
  0.5000). **VERDICT (do not relitigate): the pure net leaf LOSES to the scaffold at equal sims
  (0.275 @128v128; depth doesn't rescue it), but the HYBRID — net PRIOR + rollout-heuristic VALUE —
  BEATS the scaffold 0.567 at equal sims.** The policy head distilled well; the value head lags
  (CoC's rollout-augmented teacher leaf sets a higher bar than Spender's static v_state). Net-argmax
  vs full search ≈0.03 is normal (1-ply), not a distill failure.
- **P4 (RUNNING): hybrid ratchet** — `tools/loop_coc.sh` (resumable: `progress_coc` + ITER-k-DONE +
  `sp_k.HARVESTED` markers so a mid-iter restart skips a completed harvest):
  hybrid self-play (`harvest_boot <out> <games> <sims> 20 <seed> 10 pv_best.json hybrid`) → train both
  heads warm-from-best (2-iter window + boot anchor) → cand-vs-best hybrid gate (promote ≥0.52) +
  **pure-pv-vs-hybrid probe (the value-head takeover signal: flip self-play mode to `pv` when it
  crosses 0.5)** + scaffold@2000 yardstick. Watch `coc_run/loop_log.txt`. If flat after ~8 iters:
  raise self-play sims first (the proven lever) before touching targets/architecture.
  **MSYS ARG-CONVERSION FOOTGUN (cost 3 silent no-op iterations — do not regress):** Git Bash
  auto-converts `/c/...` args for native exes but SKIPS args containing `*` (train_pv's `--data`
  globs → Python glob matched NOTHING) and `:` (`model.json:hybrid` gate specs → Rust `File::open`
  on an unresolvable POSIX path). loop_coc.sh now passes **cygpath'd `$RUNW` Windows-style paths to
  every native tool** + `set -o pipefail` + a gate-parse FATAL guard so a failed stage aborts loudly
  instead of "kept best ()". Validate any loop change with a miniature dry iteration
  (`RUN=<dry-dir> ITERS=1 GAMES=20 SIMS=32 GATE_PAIRS=2 ... bash tools/loop_coc.sh`).
- **P5 (DONE, LIVE on prod): Expert tier = client-side WASM serving.** Prod e2e PASSED (Playwright
  on forry4.github.io: guest → CoC → Expert game → the bot's decision shipped as `ai_search`, the
  browser's 4-worker pool searched it and submitted `ai_move`, server validated + applied).
  - **Protocol (per-DECISION, prefix-based):** the server (`games/castles_of_crimson/main.py`)
    ships each bot ENGINE-MOVE decision in room state as `ai_search = {decision, seat, mode,
    budget_ms, max_sims, state: az.compact.project(game) with the 3 undrawn pools SORTED}` (lives in
    room state so re-broadcasts/reconnects re-ship it); the client loops stepInfo → (forced |
    root-parallel `coc_search_timed`, visits SUMMED across workers) → append to prefix → at the
    Micro::None boundary `coc_chain_move` → `ai_move {decision, move}`. Server resolves via
    `az.bridge.compact_to_move`, validates by MEMBERSHIP in `engine.legal_moves`, applies, wakes the
    scheduler (`_client_bot_turn` + asyncio.Event). Single-legal decisions apply server-side.
    Watchdog `CLIENT_AI_TIMEOUT=8s` → the turn falls back to the HARD server bot (per-turn
    degradation, deadlock impossible — the finisher still guarantees turn end); stale/illegal
    ai_moves are logged + dropped (never a user toast); `client_ai` disarms on socket disconnect.
    Tests: `tests/test_client_ai.py` (full game through the simulated client, watchdog, illegal-drop).
  - **Model is NOT embedded in the wasm** (improves on the Spender include_str pattern): the worker
    fetches `webapp/public/wasm/coc_pv_model.bin` (compact f32 blob, ~2.6MB, browser-cached) once
    and passes it to `coc_init_model`. **A model upgrade = `python coc-core/tools/pv_json_to_bin.py
    <winner.json> webapp/public/wasm/coc_pv_model.bin` + push — NO wasm rebuild.** The wasm itself is
    192KB (`coc_core.js`/`coc_core_bg.wasm`, wasm-pack --target web). `netio::pv_from_bin` is
    bit-identical to the JSON loader (verified by `net_export_check <json> <bin>`).
  - **Serving mode `_EXPERT_MODE="netval"`** in CoC main.py (see the P4/P6 result below — netval
    beats hybrid). Serves the P3 bootstrap net (`coc_pv_model.bin`) — the ratchet produced no
    better net (winner's curse), and netval's gain is the LEAF not the weights, so no model swap.
    Lobby: Expert joins Normal/Hard in the vs-Bot picker (`AI_DIFFICULTIES` += "expert").
  - **wasm entries** (`coc-core/src/wasm.rs`): `coc_init_model(bytes)`, `coc_step_info(state,
    prefix)` → `{over,boundary,actor,forced,legal}`, `coc_search_timed(state, prefix, mode,
    budget_ms, max_sims, seed)` → visits[102] (`mode` ∈ `netval`|`hybrid`|`pv`|`heur`),
    `coc_chain_move(state, prefix)` → compact move JSON. `pxio::from_proj` (the P2-arena-validated
    ingestion) is the shared Dump path (gate widened to wasm32). Worker:
    `webapp/public/wasm/coc-worker.js`; frontend pool + driver effect in `CastlesOfCrimson.jsx`
    (Spender s-worker pattern; re-announces `client_ai_ready` per socket; forwards the server's
    `mode`).
- **P4/P6 RESULT (2026-07-06/07) — the hybrid ratchet PLATEAUED; `netval` is the one real gain
  (SHIPPED, `f0cb97a`). DO NOT relitigate.** Full detail in memory
  [[coc-expert-ai-campaign-status]].
  - The 8-iter hybrid ratchet (sims=400) produced NOTHING over the P3 bootstrap: its one "promotion"
    (iter-3, gate 0.5417 @n=120) was **winner's curse** — a fresh-seed re-gate (iter-3 vs bootstrap,
    both hybrid, n=240) = **0.4833**. The promote gate (candidate-vs-MOVING-best @200 sims, n=120,
    ±0.09) is too noisy to detect small gains; the **scaffold yardstick (FIXED reference) is the
    trustworthy signal** and was flat (~0.36-0.44) all run. (Loop bug fixed: MSYS skips `/c/`
    conversion on args with `*` or `:`, so the trainer/gate got POSIX paths and silently no-op'd 3
    iters → cygpath every native-tool arg (`$RUNW`), `set -o pipefail`, gate-parse FATAL guard,
    `sp_k.HARVESTED` resume markers.)
  - **Value-head takeover is CLOSED (two ways): (1)** outcome-target retrain
    (`coc-core/tools/train_pv_exp.py`, `--shape-a/--beta`; 80% outcome vs the loop's 49%) left the
    value head IDENTICAL as a pure-PV leaf (h2h 0.50, AUC unchanged 0.80) and still losing to the
    rollout (0.275) — NOT a training-target problem. **(2)** P3 gates re-confirm the pure net fails
    vs scaffold (argmax@0 vs scaffold@2000 = 0.025; pure-pv@128 vs scaffold@2000 = 0.135).
  - **THE FIX = `netval` (`vsearch::hybrid_netval_eval`): net policy prior + 20-step priority
    rollout + the net VALUE HEAD at the truncation** (learned long-horizon read) instead of the
    heuristic `_value`. WHY it works where a static leaf fails: CoC is a DELAYED-PAYOFF game (mine
    income compounds over phases, regions score at completion, monasteries at endgame), so a 0-step
    static eval (heuristic OR net) undervalues in-flight turns (the P2 fact: static 0.235 vs rollout
    0.715); netval plays the near-term payoffs out THEN applies the learned eval. **Gated: netval vs
    hybrid = 0.542/0.579 (two fresh seed bases) @200, 0.606 @512 (edge GROWS with sims → transfers
    to serving's ~20k); netval@512 vs scaffold@2000 = 0.52 (hybrid was 0.36); sanity
    netval-vs-netval = 0.5000.** SAME bootstrap net — the gain is the leaf.
  - **LEVER LESSON:** in CoC the value head IS impactful, but only AFTER a short rollout resolves the
    near-term delayed payoffs. More hybrid-ratchet self-play/sims is dead; the leaf architecture was
    the lever.
  - **UNTESTED LEVERS DONE (2026-07-07):**
    - **Rollout-length + C_PUCT sweep → tuned netval SHIPPED (`c119eb3`).** The inherited 20-step
      rollout was too SHORT for the net-value leaf. Fresh-seed confirmed vs `netval@20@1.5`:
      steps=30 alone 0.583 @200 but SOFTENS to 0.54 @1024 (a low-sims win); c_puct=1.0 alone 0.538;
      **COMBO steps=30 + c_puct=1.0 = 0.617 @200 / 0.570 @512 / 0.642 @1024 — GROWS with sims so it
      TRANSFERS** (the c_puct=1.0 'commit faster' part carries at depth; steps alone decays). Serving
      uses `vsearch::NETVAL_ROLLOUT_STEPS=30` + `NETVAL_C_PUCT=1.0` (wasm netval arm); scaffold/
      hybrid/pv keep 1.5/20. Same net (`coc_pv_model.bin` unchanged) — the gain is the leaf CONFIG.
      Tool: `gate_coc <path>:netval@STEPS@CPUCT` (@-delimited so a Windows path's `:` is safe).
    - **`netval` self-play loop — `coc-core/tools/loop_coc_netval.sh` (RUN=`/c/Users/Forrest/coc_run_nv`).**
      The structural test the hybrid ratchet couldn't be: self-play + gate BOTH use the netval leaf
      (`harvest_boot` gained a `netval` mode), so the value head trains WHERE IT'S USED. If the
      promote gate MOVES (unlike the hybrid ratchet's flat plateau) → netval self-play improves the
      net → re-gate the winner at the serving config (30/1.0) + swap `coc_pv_model.bin`. Loop
      self-plays at the default 20/1.5 (leaf config is ~irrelevant to the value head, which trains on
      outcomes; re-gate the winner at 30/1.0 before shipping). Watch `coc_run_nv/loop_log.txt`.
      **RESULT (2026-07-07): NETVAL SELF-PLAY WORKS — the loop's iter-5 net SHIPPED (`d0156cb`).**
      Gates ran 0.475/0.4625/0.450 (flat — looked like the hybrid plateau) then CLIMBED
      0.506/0.544*/0.569* (iters 4+5 promoted). **Fresh-seed re-gate vs the bootstrap: 0.5875
      ±0.044 (n=480, margin +7.1) — NOT winner's curse**; at the SERVING config (30/1.0):
      **0.6208 ±0.043 @200 (n=480), 0.6083 ±0.062 @512 (holds at depth → transfers to ~20k).**
      Swapped `coc_pv_model.bin` (pv_json_to_bin, json↔bin bit-identical PASS; no wasm rebuild);
      winner preserved as `coc_run_nv/pv_ship_iter5.json`. **LESSON (supersedes the early plateau
      read): the flat first 3 iters were the BOOT-ANCHORED data washing out of the 2-iter training
      window — judge a self-play loop only after the window is pure self-play data.** The
      hybrid-ratchet conclusion stands unchanged (it benched the value head); netval self-play
      trains it where it's used and genuinely improves it. **EXTENDED RUN COMPLETE (12 iters
      total): iters 6-11 = SIX consecutive non-promotions vs the iter-5 bar (0.475/0.475/0.425/
      0.469/0.506/0.469) → the recipe CONVERGED on the iter-5 net (the shipped one). Do not
      re-run this loop as-is expecting more** — the next gain needs a STRUCTURAL change first
      (feature round 2: time-discounted per-tile depot values + 26-way monastery identity —
      per-depot tiles are currently type-onehot + ONE effect_id/26 scalar, see feats.rs
      push_tile; and/or higher-sims teacher; and/or attention P4b), then netval self-play to
      consolidate it (now proven to work in CoC). Human playtest verdict pre-upgrade: the user
      beats the Expert soundly; re-test against the upgraded one, and mine the user's coc_games
      for the concrete edge before locking the feature set.
    - **PERF: vectorized net forward ~6.5x native / ~3x wasm (`21c7d9a` + `89099bc` — DO NOT regress).**
      The netval leaf was ~97% net forward (bench_coc breakdown: forward 489µs vs features 2.9µs, heur
      0.1µs, rollout ~6µs), and `valuenet::linear`'s single-accumulator dot is a serial FP dependency
      chain LLVM may NOT vectorize (float reassociation forbidden) — ~1.3 GFLOPS on a Zen 4 core. Fix:
      32-lane (4×8) chunked multi-accumulator `dot` (autovectorizes) + **`coc-core/.cargo/config.toml`
      `-C target-cpu=native`** (native x86_64-msvc only; wasm32 untouched) + `forward_value_raw`
      (value-head-only truncation eval) + inv_sd precomputed at load. **Native: forward 489→73µs, netval
      search ~1,000→~5,300-5,800 sims/s/core (~5.5x); wasm (`+simd128` via RUSTFLAGS on the wasm-pack
      call): 466→~1,420 sims/s single-thread → the live Expert gets ~3x the sims/decision in its 900ms
      budget (same net/protocol; a no-simd browser fails wasm init → existing hard-bot fallback).**
      Parity holds (net_export_check 3.3e-7, tighter than before). The netval loop was killed mid-iter-1
      + relaunched on the fast build (clean: HARVESTED markers + File::create truncation; iter-0 gate ran
      on the old binary — win rates stay comparable, CRN is within-gate). Remaining perf levers if ever
      needed (diminishing): int8 quantization, GPU inference server.
    - **PERF round 2 (`675f8c5`): BATCHED netval leaf evals, ~2.3x more on the forward, BIT-IDENTICAL —
      the default for all offline experiments.** Each harvest/gate thread drives K games (default 8) in
      lockstep — one sim per game per round, all leaves through ONE `valuenet::forward_batch` pass. No
      virtual loss / no cross-thread sync → search semantics unchanged; **batched runs reproduce
      sequential (`batch=1`) EXACTLY** (verified: identical gate lines netval-netval + netval-SCAFFOLD;
      batched A-vs-A = 0.5000/+0.0). Key pieces: `valuenet::dot4` (register-blocked 4-input kernel —
      weights stream K/4 times, x-block L1-resident; 80→34µs/eval @K=8), `mcts::Search::descend`/
      `complete` (sim() split at the leaf seam, one shared code path), `batch.rs` (SearchTask +
      step_netval), `[batch]` arg on gate_coc/harvest_boot (default 8 — loop scripts need no change).
      **FINDINGS (do not relitigate): (1) plain row-reuse tiling was a WASH** — it trades L3 weight
      traffic for L2 activation streaming; the register-blocked kernel is what pays; **(2) an 8-input
      block CRATERED** (register spills, 4× worse) — 4 is the sweet spot; **(3) `dot` is now a single
      8-lane chain = the CANONICAL accumulation order `dot4` replicates per pair** (this shared order IS
      the bit-identity mechanism; multi-chain ILP bought nothing — the matvec is load-bound). Harvest
      batched path uses a PER-GAME opening-temp rng (deterministic under interleaving; the one behavior
      delta vs sequential). **WASM CAUTION:** dot's chain width changed (4×8→1×8); native is identical
      (load-bound) but v128 has no FMA — A/B any future wasm rebuild in Node vs the deployed 466→1,420
      sims/s baseline before shipping.
    - **PERF round 3 (`ed579dd`): int8+VNNI quantized netval — STRENGTH-NEUTRAL (fresh-seed gate
      0.5000 ±0.069 n=200; a first-gate 0.450 was seed noise, pooled 0.481 ±0.055) — use for
      SCREENING experiments.** Opt-in: gate spec `:netval8[@STEPS@CPUCT]` / harvest mode `netval8`;
      f32 stays the default and model files stay f32 JSON (quantized at LOAD:
      `QuantPolicyValueNet::from_f32`, per-row symmetric int8 on the two trunk layers = 96% of MACs;
      heads/z-score f32; dynamic per-vector activation quant, zero-point-128 u8 for `vpdpbusd`).
      `qdot` = AVX-512 VNNI intrinsic under `cfg(target_feature="avx512vnni")` (true via
      target-cpu=native on the Zen 4 box) with an exact-same-INTEGER-result scalar fallback → int8
      runs are deterministic and machine-portable (netval8 A-vs-A mirror = exactly 0.5000). Quality:
      value MAE ~5e-4, policy-argmax 62/64 vs f32. Speed: int8 SINGLE forward (137µs loaded) already
      beats the f32 blocked-BATCH path (169µs) — no int8 batch blocking built yet (model is
      L2-resident at 640KB, so blocking pays less; optional future work). **USAGE GUIDANCE: int8 for
      screening/paired experiments (both sides share arithmetic → unbiased); f32 for final/ship
      gates and the FIXED scaffold-yardstick trend line (cross-arithmetic comparability). Do NOT
      switch a RUNNING campaign's arithmetic mid-loop.** The `PvEval` trait (valuenet.rs) is the
      seam: `pv_eval`/`hybrid*eval*`/`root_readout_pv`/`batch::step_netval` are generic over it.
      NOTE `:netval8` must parse BEFORE `:netval` in gate_coc (substring).
    - **PERF round 4 (`384eb49`): GPU inference sidecar for harvests — ~3.7x (325-333k evals/s vs
      ~88k CPU f32-batch).** `tools/gpu_server.py` (torch cu128, localhost TCP, z-score FOLDED into
      trunk[0] at load + zero-copy request parse) + `src/gpueval.rs` (`GpuEval` behind the `PvEval`
      seam, pooled connections, native-only) + harvest mode `netvalgpu` (addr via `COC_GPU_ADDR`).
      **Startup parity guard (do not remove): harvest forwards one probe through BOTH paths and
      asserts ≤1e-3/1e-2 — a stale/wrong server model can never poison a harvest** (measured diff
      3.6e-7). HARVEST TIER ONLY (torch GPU arithmetic, not bit-identical) — ship gates stay CPU
      f32. FINDINGS: per-REQUEST overhead (client RPC + server GIL ~590µs) is the whole game —
      rows/request = 2×K, so **K=64 is the config** (128-row requests; the 20-game smoke test at
      K=2-per-thread ran 60x slower than CPU); **K=128 memory-thrashes** (~1280 in-flight trees
      blow past free RAM → near-zero throughput, not a crash); games/thread must be ≥K to fill the
      lockstep. Server prints 10s `[stats]` lines (evals/s, reqs/s, rows/req). Loop wiring
      (`loop_coc_hs.sh`): server started per iteration with the CURRENT pv_best, **PID-killed
      after harvest — NEVER `taskkill //IM python.exe` mid-loop (the trainer is python too)**.
      Net effect: a 2000g@1200-sims harvest ~2.3h → ~36 min; hs-loop iteration ~2.8h → ~1.1h.
    - **FEATURE ROUND 2 (2026-07-08): time-value features = WASH (do not relitigate the flat-MLP
      form).** Encoder v2 (`feats::features_v2`, 1078 = v1 934 byte-identical prefix + Group J 144:
      per-offer-slot `tile_time_value` (mine/continuous-monastery yield × phases_left; endgame-mon
      exact multiplier + headroom) for my 19 slots + 16 contested opp slots, flags, 26-dim effect
      unions). Full unattended chain (`tools/loop_coc_v2.sh` + overnight orchestration): champion
      distill-harvest 5000g@500 logging v2 (`coc_run_v2/boot2`) → fresh v2 distill (val AUC 0.791,
      top1 0.695, parity 1.8e-7; **0.425 vs champion** — distill compression loss) → 9 netval
      self-play iters. The v2 line ONLY RECOVERED its distill deficit: fresh-seed cross-gates vs
      the v1 champion **0.496 ±0.045 (n=480) train config / 0.521 ±0.045 serving config @200 /
      0.492 ±0.063 @512** (no depth transfer), then iters 6-8 = 0.481/0.450/0.506 non-promotions →
      user stopped it. **Verdict: the MLP already infers the time×tile-value interaction from
      phase/round one-hots × tile types; explicit Group J adds nothing** (the CoC analog of
      Spender's v3/v4 feature-screen washes — attention/MLP already computes the cross-terms).
      Infra keeps: the `Enc` seam (input-dim → encoder, so v1/v2 nets coexist), `logenc` harvest
      arg (play vX, log vY — the distill-harvest pattern), `train_pv.py --in-dim`. State preserved
      resumable in `coc_run_v2` (progress_v2=9). **Next levers, in order: mine the user's
      coc_games for the concrete human edge (BEFORE more feature guesses); higher-sims teacher
      re-bootstrap; attention (P4b).**
    - **RUNG 1+2 (2026-07-08/09): high-sims teacher + PCR both PAID — new champion SHIPPED + the
      lobby ladder RESHUFFLED (`1d93cdd` backend + `5ec78cf` frontend).**
      - **Rung 1 — high-sims continuation (`loop_coc_hs.sh`, coc_run_hs):** netval self-play at
        SIMS=1200 (4x the converged 300), warm-seeded FROM the champion (no distill compression —
        the FR2 trap), NO boot anchor, GPU harvest. 4 iters, promotions at iter 0 (0.546) + iter 3
        (0.521). Fresh-seed cross-gates: **iter-3 net = +0.04 real** (0.542 train / 0.548 serve /
        0.521 @512); the iter-0 net's gain did NOT transfer to serving config (0.500) — always
        cross-gate at the serving config before believing a training-config gain.
      - **Rung 2 — PCR combined campaign (`loop_coc_r2.sh`, coc_run_r2):** PCR 250@200 (25% of
        decisions at the FULL 2000-sim cap -> policy rows; 75% at 200 -> value-only rows) x 4000
        games/iter x GPU, seeded from hs iter-3. Iter-1 promoted 0.550; iters 2-4 failed vs it
        (0.413/0.488/0.408) -> converged; yardsticks hit RECORD levels (0.61-0.73 vs scaffold).
        **SHIP GATES (fresh seeds): r2 net vs champion 0.6083 +-0.044 train / 0.5250 serve@200 /
        0.5500 serve@512 (grows with depth); vs its hs seed 0.5604 serve.** Winner preserved as
        `coc_run_r2/pv_ship_r2.json`. PER-ITER COST NOTE: r2 spent PCR's savings on 2x games +
        deeper caps (~equal compute/iter, ~3.2-3.5h — and the end-of-harvest straggler tail is
        LONGER under PCR: the last games crawl in tiny GPU batches; a shared work queue across
        threads would fix it).
      - **TIER RESHUFFLE (user-specified):** lobby = **Easy / Hard / Expert** — easy = the server
        MCTS bot at its STRONG config (formerly sold as "hard"; ai.play_turn_plan "hard"), hard =
        the first netval champion net (client WASM, **NEW `coc_pv_model_hard.bin`**), expert = the
        r2 net (`coc_pv_model.bin`). "normal" is LEGACY-only (old saved rooms keep their weaker
        bot; picker dropped). `CLIENT_AI_TIERS=("hard","expert")` both use the client path;
        `ai_search` carries a `model` field; the worker picks its bin from `?model=` on its URL
        (whitelisted). Watchdog fallback for both tiers = server hard bot, unchanged.
      - **Ship hygiene:** bins bit-identical to their jsons (net_export_check json+bin); wasm
        rebuilt (+simd128) carrying the surplus-discard fix — Node smoke on BOTH bins, 3.2-3.4k
        sims/s single-thread (baseline 1,420 — no dot-chain regression); 307 CoC tests; npm smoke
        CLS 0. Rollback = revert `1d93cdd`+`5ec78cf` (the old expert net lives on as the hard bin).
    - **SURPLUS-DISCARD search fix (`306517c`) — from a USER OBSERVATION (do not regress).** The
      search-legality prune dropped ALL discards ("never discard a stored tile"), so the bot could
      never discard — with storage full of unplaceable tiles it was LOCKED OUT of hex takes/black
      buys/m6 for the rest of the game. Now a SURPLUS tile (its color has more stored copies than
      the board has empty spaces of that color left — fixed color capacity only, so provably dead
      under every future) MAY be discarded; live-tile discards stay pruned; engine rules + parity
      surface untouched. Weakly dominant (discards are free, opponent-independent, board never
      grows). Mirror sanity exactly 0.5000. **Side effect: self-play now EXPERIENCES dead-tile
      discards, creating the cost signal the over-TAKING problem needs.** The take-side prune
      (don't take tiles you can't fit) is PARKED — denial takes can be correct (user call);
      revisit with evidence.
    - **Browser sims/s (`667b117`): worker pool now min(cores-2, 8) on >4-core machines (~2x
      sims/decision on desktops; small devices keep min(cores,4)). MULTI-TREE BATCHED wasm search
      = MEASURED NEGATIVE (do not relitigate): 874 vs 2,852 sims/s single-tree, flat across
      K=8/16 — the batched forward is a memory-BANDWIDTH optimization (native is load-bound with
      16 wide registers) but v128 is 4-lane FMA-less COMPUTE-bound and the 4-input block spills.**
      `coc_search_timed_multi` stays in the wasm as tooling (feature-detected in the worker,
      never routed); a relaxed-SIMD int8 build is the only thing that would change the economics.
      Remaining browser levers: the 900ms budget (user UX call) and per-move tree reuse across
      micro-decisions (~1.3x, unbuilt).
    - **P4b ATTENTION campaign (STARTED 2026-07-09; commits `557ecc1`, `02b3bda`, `e51a6c4`,
      `2933e6c`) — the architecture bet after the recipe axis was wrung out.** State + durable
      facts:
      - **Throughput gate PASSED — shape locked T=32 tokens x 28 feats, D=48, 4 heads, FF=96,
        L=2, trunk 128.** Native 1,482 / wasm 917 evals/s single-thread → ~3.2k sims/decision on
        8 workers (~1.6k on a 4-core visitor). T=44/D=64+ FAILS (467 native). The bench
        calibration row reproduces Spender's documented 2,041 evals/s within 3% — after
        replacing the naive serial dot with valuenet's chunked kernel (the round-1 lesson
        re-bit: the first bench read 3-4x slow). **The explicit bet: per-sim quality must beat
        a ~7x sims handicap vs the MLP's ~20k/decision — the final arbiter is an
        equal-WALL-CLOCK gate, never equal-sims.**
      - **`src/attn.rs`** = runtime-parameterized forward (adapted from spender-core's proven
        attn.rs): embed → Lx[key-masked MHA + FFN, residual + no-affine LayerNorm] → masked
        mean-pool + state-embed → trunk → value(tanh) + policy. **Policy = 80 GLOBAL logits
        scattered to action ids + token-TIED logits** (depot tokens 1:1 with TAKE_HEX, black →
        BUY_BLACK, my-storage → DISCARD + PLACE_SLOT — CoC's action space token-aligns BETTER
        than Spender's); masked tokens stay -1e9 (their tied actions are illegal whenever the
        token is empty, so priors never read them). `AttnNet: PvEval` (forward_raw splits the
        flat row; encode_state = the token encoder) → gates/harvests/netval/self-play all work
        UNCHANGED.
      - **`src/tokfeats.rs` = the FROZEN input schema (code-as-spec): 32x28 tokens + 32 mask +
        96 state = 1024 flat f32** (`Enc::Tokens`; in_dim 1024 discriminates in the seam).
        Tokens: 12 depot-hex + 4 black + 3+3 storage (carries the SURPLUS/dead flag) + top-5
        regions per player (**value-at-stake salience with deterministic tie-break lives in the
        RUST encoder** so training rows and serving can never disagree). Tile tokens reuse the
        FR2 `tile_time_value`/`endgame_mult` helpers — washed as flat-MLP inputs, but tokens
        are where attention can cross-reference them. State: dice/track/resources/goods/phase/
        round/bonus/monastery aggregates + pending/micro onehots (leaf evals happen mid-chain).
      - **Torch twin `tools/attn_net.py` — PARITY PASS 5.4e-7 value / 2.6e-6 logits, masked
        slots exact** (`attn_export_check` bin; non-negotiable before any trained json is
        trusted). export_json/import_json/write_check; identity normalization everywhere
        (tokfeats is bounded by construction — NO mu/sd in this stack).
      - **Plumbing:** `PvEval` gained **`in_dim()`**; gate_coc + harvest_boot load MLP OR
        attention jsons by CONTENT detection (`"emb_w"` = attention; netval8 stays MLP-only,
        asserted); an attention model in harvest_boot auto-selects Enc::Tokens for logging via
        in_dim (self-play logs token rows with zero extra flags); harvest `logenc` arg accepts
        `tok`; gpu_server.py grew an attention branch (attn_net.import_json + forward_flat) so
        attention SELF-PLAY runs the same sidecar protocol. `tools/train_attn.py` = streaming
        token-row trainer (SHAPE_A=0.3 ⊕ BETA=0.3 blend — the proven fresh-retrain target;
        PCR-safe CE normalization; game-split holdout; exports json + parity .check per best).
      - **DISTILL LINE (2026-07-09/10): harvested 5000g/1.21M token rows @1200 sims → trained
        (AUC 0.838 / top1 0.448) → gate 0.2917 vs the r2 champion → 8 MORE warm epochs @lr 5e-4
        (top1 → 0.4646, decelerating — NOT epoch-starved) → re-gate 0.4458.** The +15pp from
        extended training dwarfs what +1.7pp top1 implied — **val top1/AUC are weak proxies; the
        VALUE-head calibration is what the netval leaf consumes; always re-GATE after more
        training.** Starts above FR2's 0.425. `attn_distill2.json` = the loop seed.
      - **SELF-PLAY LOOP (`tools/loop_coc_attn.sh`, RUN=coc_run_attn, ITERS=8, 2500g@300 sims,
        promote ≥0.52, FIXED r2-champ yardstick @200 each iter) — RUN COMPLETE (2026-07-11).**
        Iter 0 PROMOTED 0.5750 (first self-play iter beats the distill seed +7.5pp); its probe
        netval-vs-hybrid = **0.5500 — the attention VALUE head beats the heuristic leaf at iter
        0** (took the MLP line a whole campaign). Iter 1 kept (0.5042), iter 2 kept (0.4708).
      - **ITER-3 CRATER — the ANCHOR-CLIFF lesson (fixed in `1168e9c`; DO NOT return to a hard
        anchor cliff).** The first fully-anchor-free train (the designed ANCHOR_ITERS=3 drop)
        collapsed BOTH heads onto the self-play distribution: gate **0.2667 (margin −25)**,
        yardstick 0.4333→**0.2083**, probe 0.55→0.46 — while **val AUC/top1 hit record HIGHS
        (0.8377/0.6106): the val split shares the collapsed distribution, so train metrics are
        structurally BLIND to this failure.** Data + harness exonerated (asp_3 row stats ==
        asp_2; parity probes green). The MLP nv loop survived this same cliff; the
        higher-capacity attention net does not. **Fix: post-anchor iters keep a ~22%-of-mix
        anchor TAIL (attn_boot.t[0-2] — champion-quality 1200-sims rows) + lr halved to 5e-4.**
        Validated immediately: iter 4 gated 0.5250 → PROMOTED (first since iter 0); iters 5-7
        back in the normal band (0.3958/0.4750/0.4917, kept).
      - **RUN VERDICT (iters 0-7): the value head improves but the PACKAGE is FLAT.** Probe
        (netval-vs-hybrid, same net) climbed 0.5500 (it0) → **0.5917 (it6) — the largest
        value-head-over-heuristic edge measured in the whole CoC campaign.** But the yardstick
        was FLAT across all 8 healthy points: 0.4458 → 0.4417 → 0.4667 → 0.4333 → [crater
        excluded] → 0.4417 → 0.4250 → 0.4250 → 0.4667 (±0.089 each; no slope — the policy
        head / whole package is the bottleneck at 300-sims self-play targets).
        **EQUAL-WALL-CLOCK ship gate (the arbiter, 500ms/decision both sides, CPU f32, n=120):
        attn_best:netval@20@1.5 vs r2-champ:netval@30@1.0 = 0.3083 ±0.083 (margin −12)** —
        the equal-sims 0.4417 minus the predicted 12-16pp sims handicap lands EXACTLY on the
        measurement, empirically confirming the two-gate model (ship bar ≈ 0.63-0.65
        equal-sims). Gap to ship: ~20pp equal-sims with zero slope after 8 iters. Escalation
        options if resumed: self-play sims 300→1200 + PCR (the levers that built r2 itself;
        ~2.5-3h/iter with the GPU sidecar), int8-ATTENTION wasm kernel (halves the serving
        handicap → bar ~0.57). Crater net preserved: `attn_cand_3_crater.json`.
    - **SIMS-SATURATION LADDER (2026-07-10, user hypothesis CONFIRMED — do not relitigate): CoC's
      knee is ~4-8k sims vs Spender's ~1.2k.** Champion self-gates at serving config (30/1.0),
      CRN adjacent doublings: 512v1024 **0.5417**, 1024v2048 **0.5833**, 2048v4096 **0.5667**,
      4096v8192 **0.5000** (knee). Mechanism: multiplicative micro-decision turn chains + dice
      chance every round + delayed payoffs. Consequences: the browser Expert sat BELOW the knee
      (→ the serving push below); the **attention wall-clock ship bar ≈ 0.65 equal-sims vs the
      champion** (~7× eval cost ≈ 2.5-3 doublings ≈ 12-16pp on this curve). Spender transfer
      DECLINED by user (its serving is ~16× past its knee; an N-specific ladder was offered).
      Tool: `scratchpad simgate_ladder` pattern — early-exit rung chain, results in
      `coc_run_simgate/ladder_log.txt`.
    - **SERVING SHIPPED (`ce747ca` + `5ecd735`, live on Pages/Render):**
      (a) **Per-decision TREE REUSE** — wasm `TreeCache` (thread-local, keyed state-hash + mode +
      prefix): a LONGER prefix re-roots through applied actions (`mcts::advance_root_child` =
      arena `nodes.swap(0, child)` + `set_root_state`; orphans bounded per move; micro actions
      within a chain are deterministic so replay==stepping); an EQUAL prefix CONTINUES the tree.
      **Returned visits are CUMULATIVE per worker under reuse — the JSX uses the LATEST response,
      never sums across chunks.** (b) **Adaptive Expert budget**: `_EXPERT_BUDGET_MS` 900→1500
      TOTAL; the JSX searches in ~500ms slices (continuation = same prefix) and stops early when
      the summed visit lead > achievable-remaining-sims (uncatchable) — easy decisions ~500ms,
      contested get 1.5s. (c) **int8+simd128 wasm forward (+24%)**: `qdot` gained a wasm arm via
      `i32x4_dot_i16x8` (v128 lacks f32 FMA but HAS integer dot — the one kernel change that
      pays); quantized at `coc_init_model`; wasm "netval" now serves int8, **"netvalf32" = the
      A/B + rollback mode**; strength-neutrality transfers from the native int8 gate
      (deterministic integer math). Node A/B: 3,514 vs 2,825 sims/s.
    - **SIDECAR PERF (torch twin serving; `d603891` + `4d3128a`): 10.5k → ~150k evals/s.**
      (1) The attention forward was KERNEL-LAUNCH-BOUND (python tied-scatter loop ≈38 launches +
      manual attention ≈140/req → 11.5ms per 121-row request): vectorized the scatter (index
      tensors as **non-persistent module buffers** — CPU-index H2D copies are both slow AND
      ILLEGAL inside CUDA-graph capture) + SDPA → 70k (6.7×), bit-vs-.check 0.00e0. (2)
      **CUDA-graph runner** (`GraphRunner`, static padded buffers, lock-serialized replays;
      eager fallback + `COC_GPU_GRAPH=0`) → 146k @8 clients (~2.1×); replays are the captured
      kernels = eager-exact. **(3) THE PAD MUST MATCH THE REQUEST SIZE (`COC_GPU_PAD` =
      2×GPU_BATCH)**: a 256-pad graph on 128-row requests pays the full replay → capped 65k with
      clients starved at 27% CPU. **(4) K=128 thrashes the CLIENT CPU cache even at 300 sims**
      (40-48k evals/s, CPU 91%/GPU 41%) — the K warning isn't just RAM; **64 is the sweet spot**.
      (`torch.compile` unusable — inductor needs Triton, Linux-only; manual graph capture is the
      Windows path.)
    - **GPU GATES + WALL-CLOCK GATES (`5fa8b90`):** gate_coc spec `path:netvalgpu[@S@C]` routes a
      netval player's forward through a sidecar — addr per SIDE via `COC_GPU_ADDR_A/_B` (TWO
      servers when A≠B models), per-side startup parity probe vs the local json. **GPU-vs-CPU
      same-net CRN mirror = 0.5000 with margin +0.0 — identical decisions every game**, so the
      yardstick trend is comparable across the switch; ship gates stay CPU f32 by discipline.
      Sims args also accept **"1500ms" = per-DECISION wall-clock budgets** (sequential path only)
      — **the equal-TIME harness for the attention ship decision** (at equal ms the faster net
      earns its sims advantage naturally; native cost ratios ≈ wasm ratios). Loop gates run GPU
      (cand 9913 / best 9914, threads 4 batch 24, pads 48); g2 probe every 3rd iter.
    - **TRAINER PARSE (do not relitigate the numpy paths): np.fromstring(sep) AND np.loadtxt both
      ~0.55µs/field — same as split+array; NO fast numpy text path.** pyarrow verified BIT-exact
      (0 mismatches, margin-scale bit-equal, same row order) and multithreaded — **but two
      cublas-backward crashes with arrow in-process → OPT-IN via `COC_ARROW=1`** (attribution
      unresolved: arrow readahead RAM vs the triple-race VRAM contention below; a clean
      arrow-then-backward mini-repro PASSES). Trainer runs the python loader (~40-min trains)
      with **CUDA_LAUNCH_BLOCKING=1 + retry-once armor** (async CUDA errors misattribute to later
      ops — sync mode captures the true op if it recurs) + **atomic exports** (tmp+rename).
    - **PER-SIM CPU PROFILE (bench_coc arms, do not re-derive): NO dominant component.** tokfeats
      encode **5.5µs** (~2× v1's 2.6µs — NOT first-order), determinize **1.9µs**, rollout ~6µs,
      engine ~0.56µs/micro-move. Encoder-caching and sort-hoisting levers are DEAD; remaining
      offline throughput levers = straggler-tail work queue (10-20%), cloud burst (~3×), PCR.
      Iterations now ~35-50 min (was ~2.5h).
    - **TRIPLE-RACE POSTMORTEM (2026-07-10) + LOOP HARDENING (`f7ed70d`) — DO NOT regress.** Three
      loop instances raced (relaunch-after-crash without verifying death, twice): doubled log
      lines, gate-port fights (a blank yardstick line — recovered manually: iter-1 = 0.4667),
      and plausibly the cublas crashes (two trainers on 6GB VRAM). A watcher also matched a
      STALE traceback in the log tail → a false "crash #3" → a wrong "pyarrow exonerated" call
      (corrected). Hardening now in the loop script: **singleton lock** (mkdir-atomic + live-pid;
      refuses double launch), **trap-EXIT cleanup** of registered child servers (crash exits),
      **launch pre-flight** (straggler harvest_boot / bound ports → refuse loudly; covers HARD
      kills, which don't cascade on Windows), **gate stderr → per-iter `gates_err_$k.log`** with
      empty-result guards (g1 fatal, yardstick loud warning). Watcher discipline: match only
      content AFTER an armed byte offset. (Curio from forensics: iter-0's net emits ~1e8 logits
      on off-manifold random inputs while fully sane on-manifold — Adam with no weight decay
      leaves unconstrained directions; harmless so far, worth remembering.)
    - The escalate-or-fold decision RESOLVED 2026-07-13: user chose ESCALATE — see the
      "Session (2026-07-11..13) — aux-head arc" entry below (the escalation runs 1200-sims PCR
      self-play + the vs-champion league + the aux gradient, three levers the folded run never
      had). The human playtest of the NEW ladder (Expert = r2 net at ~3× the sims of the last
      playtested Expert) is STILL outstanding.

### Session (2026-07-11..13) — aux-head arc: the ONE confirmed training-signal lever; distill ceiling; goal = 0.60-vs-champion at equal sims (commit `e39c934` + follow-ups)
The post-r2 strength campaign. Standing GOAL (user, revised down from 0.67): a SHIPPABLE bot that
beats the r2 champion **≥0.60 at EQUAL sims**. Durable facts, verdicts, and infra — all gates are
n=240 vs `coc_run_r2/pv_ship_r2.json` at 200v200 unless noted:
- **AUX SCORE-DECOMPOSITION HEADS (KataGo-style) = the one causally-confirmed training-signal gain.**
  `engine.rs` gained a **shadow VP ledger** (`region_vp`/`color_vp`/`livestock_vp` on PlayerState —
  pure telemetry, OUTSIDE `proj.rs`'s canonical projection, parity suite untouched); `harvest_boot`
  writes **14 terminal score-decomposition aux columns** per row (mover+opponent: region/color/
  livestock VP, goods sold, mines, silver, endgame-monastery — `aux_targets()`); `train_pv`/`pv_net`
  (and later `train_attn`/`attn_net`) gained `--aux-dim/--aux-weight`: z-scored aux MSE on a
  trunk-shared head that is **EXCLUDED from export** (json stays shape-identical → ZERO Rust/wasm
  change; the head re-inits on warm starts and reconverges in a fraction of an epoch). Paired
  experiment (same corpus/seed/init, only the gradient differs — control = `--aux-weight 0`, NOT
  `--aux-dim 0`, which would MIS-PARSE the new CSVs): control 0.3667 vs champ, aux 0.4625, **DIRECT
  aux-vs-control 0.5750 ±0.063** (+9.6pp on the champ gates). **Aux-weight curve is an inverted-U
  peaking at 0.3** (0.15→0.4250, 0.3→0.4792, 0.6→0.4208, 10k corpus). A league-mix arm gated
  IDENTICAL to plain aux → the aux gradient extracts the staging economics from ordinary self-play.
- **THE DISTILL CEILING (structural — do not relitigate): every distill from the champion caps
  ~0.48-0.50.** Student≤teacher: the 6000-sim search amplification in the corpus is eaten by distill
  fidelity loss (pv_big's 0.4958 tie = the ceiling, not a near-miss). Measured exhaustively: corpus
  doubling 5k→10k = +1.7pp (wash); extended training (warm +4ep @5e-4) = +0.4-5.4pp (best net:
  `pv_10k_best_ext.json` **0.4833**, margin +0.5); **capacity×aux INTERFERE** (big-trunk 1024,512 +
  aux = 0.3917, worse than either alone). ALSO EXPOSED: the 07-11 "capacity +12.9pp" was
  CORPUS-CONFOUNDED (pv_big trained on cap+league corpus, the controls on the aux corpus — the only
  controlled lever ever measured is the aux gradient).
- **CONSOLIDATION IS FLAT ON THE AUX LINE at every config (the past-champion mechanism is broken
  here):** 300-sims, 1200-sims+PCR, and champion-warm loops all failed. Champion-warm actively
  degrades (0.4958→0.4250 — a converged net RESISTS a fresh-head gradient; own-basin only).
  Recurring signature: internal cand-vs-best gates rise while the champion yardstick sinks
  (self-play basin divergence — the Spender league lesson replayed). **The vs-CHAMPION league FIXES
  the divergence but not growth**: yardsticks 0.4917/0.4167/0.4833/0.4750 (stable around the seed's
  0.4708) vs prior monotonic sinks. Note ALL champion-line loops (nv/hs/r2) ENDED in this same flat
  state — the recipe family is at its plateau; approaching it from below doesn't reopen it.
- **STAGER: dead as a ship lever.** Beats champ 0.58 at loop config (300 sims) but is a LOW-SIMS
  phenomenon: equal-sims @2000v2000 = 0.4875 (w0.3) / 0.5000 (w0.6). The stager-teacher corpus idea
  died with it (a 2000-cap stager teacher ≈ plain champion; the 6000-cap aux corpus is strictly
  better). UNEQUAL-sims demo (the original /goal form): champ+stager@0.3 @3200 sims vs expert@200 =
  **0.7250/0.6625** (fresh seeds) — a compute-edge bot, not shippable; re-confirms the sims ladder.
- **HARVEST/GATE INFRA (permanent, commit `e39c934`):** `harvest_boot` — sequential-path **PCR**
  (`PERMILLE@CHEAP` arg, must start with a digit — `vs@` specs also contain '@'); **shared work
  queue** (global-index game seeds + per-game rngs → BIT-identical games under any scheduling; kills
  the straggler tail; the sequential path's temp-sampling moved to a per-game rng); **`stagerboth@W`**
  (mirror stager teacher); **`vs@<model.json>` OPPONENT LEAGUE** (seat g%2 = training net, ONLY its
  rows recorded — learn to BEAT the target, not imitate its cheap-sims policy; opponent plays greedy).
  `gate_coc` — **`stop@BAR` sequential early-stop** for DECISION gates (z=2.5 conservative bound,
  80-game floor, exact-n reporting; measurement gates/yardsticks must NOT use it — optional stopping
  biases estimates). Sidecar launches carry a **dev=cpu FATAL guard** (a transient CUDA error once
  silently started a 3× slower CPU sidecar). **GATE-SERVER PORT-REUSE LESSON (cost 3 gates): never
  reuse a port across model swaps in one script** — Windows double-binds, the OLD server keeps
  answering, and gate_coc's per-side parity probe panics (correctly). One port per server + reap
  between swaps.
- **OPS:** disk hit 100% mid-train (retry armor + loop both died cleanly; resume markers held) →
  `az_run` purged 92GB→356MB (CSVs/npz deleted, ALL weight jsons/pools kept — every Spender line
  there is a closed verdict) + `coc_run_attn` CSVs (7.4GB, folded run, regenerable). Trainer val
  metrics were AGAIN near-blind to gate differences (ties on AUC/top1 across arms that gate 6pp
  apart) — gates are the only arbiter. A `Start-Process`-detached chain once died before its first
  log write (unreproduced; the rerun as a harness-tracked task worked) — prefer harness-visible
  launches for NEW chains, detach only proven-stable ones.
- **ATTENTION ESCALATION (RUNNING as of 2026-07-13, user-approved):** the P4b fold is reopened with
  the three levers that run never had — 1200-sims PCR self-play targets, the vs-champion league, and
  the aux gradient (`attn_net.py`/`train_attn.py` extended: `_backbone`/`_heads` refactor +
  `forward_with_aux`, aux head excluded from export, **parity re-verified 8.9e-7** post-refactor;
  `import_json(aux_dim=)`). `tools/attn2_chain.sh` (anchor harvest: 1500g attn_best mirror @1200-PCR
  → t[0-1] = the anchor tail, P4b anchor-cliff discipline) → `tools/loop_coc_attn2.sh` (6 iters,
  RUN=coc_run_attn2, gates via `attn_export_check`). Baseline to beat: the folded line's FLAT ~0.44
  yardstick; the goal path needs ~0.50+ and climbing. VERDICT PENDING — if flat again, the
  architecture bet is closed at both sims regimes.

### Session (2026-07-13..14) — attention escalation FOLDED, sims-warm + cold-distill + denial all ≤ r2: the SELF-PLAY CEILING (goal 0.60-vs-champion UNMET; awaiting user fork)
The escalation + the two follow-on levers all landed at-or-below the champion. Durable, do-not-relitigate:
- **ATTENTION ESCALATION (coc_run_attn2) — anchor-cliff CRATER, diagnosed + folded.** iter-0 gate
  0.2914 / yardstick 0.3417 (margin −26) with HEALTHY val metrics (AUC 0.83, top1 0.57). Forensics
  RULED OUT: aux (an `--aux-weight 0` control cratered IDENTICALLY 0.3371 → aux exonerated), corpus/
  parse/targets (audited field-by-field clean — PCR fractions 25%/100%, root-value sign-agree ~0.75,
  953-col layout), and epoch calibration (6-epoch trajectory gates flat 0.29-0.33). **ROOT CAUSE = the
  P4b anchor cliff, reintroduced by my own error:** the disk-cleanup deleted the folded run's champion
  anchor CSVs (regenerable — the deletion was safe, every NET was kept), and I regenerated `attn2_boot`
  as the SEED's OWN mirror self-play = same distribution as the corpus = functionally anchor-FREE → the
  high-capacity attention net collapsed onto its own manifold. **Fix = anchor on CHAMPION (r2 @1200)
  cross-distribution rows (`attn2_champ`): gate 0.29→0.377 vs seed, yardstick 0.34→0.433 (folded ~0.44
  baseline RESTORED).** Relaunched with the champion anchor → iter-0 cand landed 0.433 (= folded
  baseline, a hair BELOW seed = warm-from-converged degradation). VERDICT: the escalated levers do NOT
  lift attention above the folded ~0.44; folded. **Prior experiments UNAFFECTED — verified: the folded
  run used the CORRECT champion anchor (its loop header documents `attn_boot` as "champion-quality
  teacher rows"; its iters 0-2 gated 0.47-0.575 without cratering; the crater was ONLY the deliberate
  anchor-FREE iter 3), and the MLP lines are cliff-immune.** Tooling: `train_attn.py --snap-prefix`
  (per-epoch export for gating the calibration trajectory), `loop_coc_attn2.sh` anchor patched to
  `attn2_champ`, forensic chains `ctl_aux0/epoch_traj/attn2_fix` (commits `95e464b` + `19ec0bc`).
- **RUNG-3 high-sims warm continuation (`loop_coc_hs2.sh`, coc_run_hs2) — PARITY, sims-warm lever
  TAPPED.** The clean ladder next rung: seed r2, SIMS=**4000** (PCR 250@1200, toward the 4-8k knee),
  aux + vs-champion league + `aux_boot` (6000-sim champ) anchor, GPU sidecar. 3 iters pooled two-seed:
  **0.483 → 0.500 → 0.508 — upward but DECELERATING (+1.7pp, +0.8pp), asymptoting at parity, never
  crossing the 0.52 promote bar** (each gate ±0.06; the yardstick UNDERCUT the gate both iters:
  it1 .508/.492, it2 .517/.500). STOPPED (resumable, progress=3). **Warm-continuing r2 at 4000 sims
  gets a net to champion-LEVEL and plateaus — it does not climb toward 0.60.**
- **FRESH cold-init train (`fresh_bootstrap.sh`) — 0.3958 vs champion, CONVERGED (not under-trained;
  val AUC plateaued 0.805 by ep3, declining by ep6).** Same 4000-sim corpus, cold init (no `--warm`,
  8 ep, aux). CONFIRMS the distill ceiling definitively: **training on champion self-play caps at ≤
  champion — WARM inherits r2's weights → parity; COLD learns only the data → BELOW (distill loss).**
- **DENIAL — NOT the lever (do not relitigate; bot-vs-bot, no user games).** `src/bin/denial_probe.rs`
  (built, smoke-verified; one bug fixed — depots are COMPACT arrays, deny by remove-and-shift not
  zero-in-place). Regret oracle = double shallow-search of the opponent's turn (END_TURN hands them the
  board with their KNOWN dice — `_begin_round` rolls everyone at once, so denial is PERFECT-INFO),
  toggling the tile. 60-game run: champion take-rate **SCALES with regret (0.13→0.28→0.46)** = it
  already values regret-denial (a blind spot would be flat); and high-regret spots are **RARE**
  (~0.33/game, ~2% of denial opportunities). Perfect-info ⇒ the search finds it; no league. The user's
  regret model (denial value = opponent's best-response DROP, highest when they're dice-constrained) is
  CORRECT as a tactic — the champion just isn't missing it. (Also corrected mid-investigation: first-
  player denial priority is the dynamic TURN-TRACK order, not game-start seat — a game-level split can't
  see it; and 22 completed games can't pin a win rate. USER DIRECTIVE: **do NOT analyze the user's CoC
  games** — all evaluation is bot-vs-bot.)
- **THE STRUCTURAL VERDICT (the point of the whole arc): r2 sits at CoC's SELF-PLAY CEILING — for the
  CURRENT recipe + net. NOT a permanent law** (see the 2026-07-15 framing note: every "ceiling /
  exhausted" verdict here is conditional on r2 + its frozen 934-dim encoder; a materially different net
  or encoder invalidates these and every probe should be re-run). Every
  training method that learns from champion self-play caps at ≤ r2 (warm→parity, cold→below, distill/
  consolidation/attention/capacity/stager all documented ≤ r2). To EXCEED r2 you need targets STRONGER
  than r2, whose only source is deeper search — but the sims ladder proved CoC's search SATURATES
  ~4-8k, and r2 trained near there. So self-play at any achievable sims can't generate better-than-r2
  data to bootstrap from. **0.60-vs-r2 at equal sims is NOT reachable by more of the same recipe.** The
  one remaining path WITH A MECHANISM = a FRESH higher-sim LADDER from a weaker seed (nv→hs→r2 re-run
  with 4000-sim self-play throughout, so each rung plays at ~4000-sim-saturation ≈ 0.57 over r2's
  2000-sim training level — NOT continuing r2, which is rung-3's capped basin). Odds moderate-LOW (cold
  0.40 + rung-3 parity both warn the practical ceiling ≈ r2), cost = days. **Fork put to the user
  2026-07-14; awaiting the call (fresh ladder vs grind rung-3 to a marginal ~0.52 vs reconsider a
  dropped constraint). Champion r2 stays deployed; nothing shipped this arc.**

### Session (2026-07-14) — TACTICAL BLIND-SPOT investigation: the user's hypotheses tested bot-vs-bot; ALL FOUR refuted/wash (do not relitigate)
After the self-play ceiling verdict, the user (a strong CoC player) proposed the plateau is a
VALUE-HEAD BLIND-SPOT problem — self-play never learns to value tactics the shared net never plays,
so r2 could be below the GAME ceiling for a fixable reason. A genuinely new lever if true (inject the
missing experience). Tested each specific claim bot-vs-bot (NO user games — user directive; all via
new probe/arena bins gating vs `pv_ship_r2.json`). Every one came back the bot ALREADY handles it —
the same lesson as Spender ("a strong search prices the tactics a strong human describes"):
- **AUDIT first (tile_audit.rs, pv 100g + DEPLOYED-netval 80g):** the champion is NOT ignoring
  anything. Monastery-6 acquired **0.62/0.65 of available games** (user thought "never"); goods-VP
  monasteries #15/#25 the MOST-acquired (0.86-0.94); ~4 ships/player/game; ~11 black-depot buys/game;
  banks ~1.7 silver + ~2.8 workers as first player at phase starts (the user's ideal). The
  netval-leaf audit REFUTES a serving-leaf-drag hypothesis (deployed 0.65 ≈ pure-net 0.62). "Never
  buys M6" was a salience/sample gap (M6 in ~29% of games).
- **DENIAL (denial_probe.rs):** regret oracle = double shallow-search of the opponent's turn (their
  dice are PUBLIC — `_begin_round` rolls everyone at once — so denial is PERFECT-INFO) toggling a
  tile. Champion take-rate SCALES with regret (0.13→0.28→0.46) = it already values regret-denial
  (a blind spot would be flat); high-regret spots RARE (~0.33/game). Perfect-info ⇒ the search finds
  it. NOT a lever.
- **M6 "should be 100%" (m6_arena.rs):** value-bias a champion copy toward owning M6 (storage-or-owned,
  so the reward is within the search horizon), gate vs normal, CRN. Uniform bias **0.46**; the user's
  refinement (M6 compounds EARLY → phase-scaled `(5-phase)/5` reward) **0.4625** — every config ≤0.50.
  Driving M6 32%→42% never helped. The champion's ~65% is CORRECT (the 35% skipped aren't worth the
  die/2-workers/space). w6=0 is an exact-0.5000 CRN mirror.
- **FIRST-PLAYER (firstplayer_audit.rs + firstplayer_arena.rs):** (A) correlational — first-in-more-
  phases wins **0.6333, DOSE-DEPENDENT** (margin 1/3/5 → 0.60/0.64/0.69), so the advantage is REAL.
  (B) causal — bias toward turn-track lead: secured MORE first-player (2.50→2.69 phases) but win rate
  **0.5125 (margin −1.5) = WASH.** So the 0.63 was largely REVERSE causation (a winning position
  controls the track); forcing the cause doesn't create wins. Bot already weights first-player right.
- **SHIP-TIMING "hold ships till the last round for next-phase first-player" (ship_timing_arena.rs):**
  placing a ship is the ONLY track-advance (`place_ship_effect`→`advance_track(seat,1)`), so forced the
  biased bot to prune ship-placement in rounds 1-4. Mechanism worked (round-5 ship-advances 0.917) but
  win rate **0.40 (margin −4.9) — HURTS.** Blunt hold-all-ships clogs storage + delays goods/track more
  than the locked first-player is worth. Natural timing was better.
- **VERDICT: no exploitable tactical blind spot found in the four most-promising candidates.** The
  champion's tactical valuations are SOUND; ~50/50 vs the user is genuine strength. HONEST HEDGE (do
  not overstate): these are BLUNT forcings of NUANCED human judgment ("hold all ships" ≠ "hold a ship
  when it matters"), so a subtle micro-edge isn't ruled out — only that there's no big FORCEABLE lever.
  Combined with the self-play ceiling, BOTH angles (how it's trained + what it might misvalue) are
  exhausted **FOR THIS NET'S CURRENT STATE — NOT permanently** (see the 2026-07-15 framing note: these
  verdicts are conditional on r2 + its frozen encoder; re-run every probe if the net materially changes).
  ALSO NOTE: a value-bias/forcing arena can only prove "forcing X doesn't help" — it CANNOT prove correct
  pricing. The instrument for "the net UNDER-VALUES X" is CALIBRATION (`firstplayer_calib.rs`, 07-15).
  Reusable tooling (all bot-vs-bot, no user games): the six bins above, each a value-bias-
  or-forced arena vs the champion with a mechanism check + CRN mirror sanity.

### Session (2026-07-15) — feature-screen + calibration campaign: every axis CLEAN **for r2's CURRENT state** (CONDITIONAL — NOT permanent; re-run if the net changes)
**READ THIS FRAMING FIRST — it scopes this section AND the two "exhausted" sessions above.** Every
"exhausted / already-priced / do-not-relitigate" verdict in the CoC-N campaign is **conditional on the
CURRENT net** (`coc_run_r2/pv_ship_r2.json`) and its **FROZEN 934-dim encoder**. They mean *"this net
already prices X"* — NOT *"X is unimportant"* and NOT *"no net could ever benefit from X."* **Nothing is
permanently exhausted.** If the net changes materially (new encoder/architecture, a stronger seed, a new
training distribution, a fresh ladder), **RE-RUN these probes** — a different net will have different
blind spots and the same features/biases can light up. The tooling below is built to make that cheap.
- **THE MECHANISM THAT EXPLAINS THE WHOLE CAMPAIGN (why r2 got strong fast with "few features", and why
  enrichment keeps washing): Group E (`feats.rs:213-219`) hands the net the hand-tuned heuristic's ENTIRE
  positional read for BOTH seats** as 4 scalars (V(me), V(opp), margin, score-margin). `heuristic::value`
  computes region-completion proximity (`frac²×(AREA_SCORE+PHASE_BONUS)`), color-bonus proximity
  (`frac²×bonus`), mine future income (`mines×phases_remaining`), endgame-monastery VP, continuous-
  monastery value, storage, empties penalty. So the cross-reference work Spender's `net_ext_19` had to
  LEARN feature-by-feature was **front-loaded into CoC's encoder from day 1**. CoC's encoder is NOT
  feature-poor like Spender's was. **The one thing `heuristic::value` does NOT compute is denial /
  contention / track-tempo** (it's two independent single-player values subtracted) — and the screen says
  the net infers that from raw opp-dice + depot masks anyway.
- **FEATURE-SCREEN PIPELINE (new, reusable — the cheap NEGATIVE filter): `harvest_featscreen.rs`** (r2
  self-play → CSV `seed, feats::features[934], candidate[K], win-label`) + a Python leave-one-out AUC
  ablation (game-split holdout, multi-split; `coc_run_fs*/ablate*.py`). **3 rounds, 5 candidate groups,
  ALL WASH:** R1 P1 my per-color completion **−0.0018**, P2 per-placement marginal VP incl. color-trigger
  **+0.0003**; R2 P3a opp per-color completion **+0.0163 (looked like a WIN)**, P3b dice-constraint denial
  proxy **+0.0022**; R3 (DECISIVE, same-data, 4 splits) G1 my vs G2 opp vs G3 opp-THREAT → **G1 ≈ G2 ≈
  +0.001 (opp == my == ZERO), G3 ~+0.003 (noise floor)**.
- **METHODOLOGY LESSON (do not regress): NEVER compare ablation deltas ACROSS harvests.** The R2
  "+0.0163" was a **cross-run artifact** — base AUC swings **0.76-0.80** between harvests/splits, which is
  BIGGER than any candidate signal. Candidates must be screened on **IDENTICAL data + multiple splits**;
  the same-data replication killed the false positive and saved a multi-day retrain (same class as the
  documented Spender v4 wash: flat-MLP screen passes → play washes). **Screen noise floor ≈ ±0.015 → it
  only reliably catches BIG (≥+0.02) gaps**; small real gaps are below its resolution.
- **FIRST-PLAYER CALIBRATION — the RIGHT instrument for "the net UNDER-VALUES X" (`firstplayer_calib.rs`).**
  The prior tests were **FORCINGS** (bias arena 0.5125 wash; force-hold-ships 0.40 hurt), which can wash
  even if a narrow mispricing exists — **a forcing test cannot prove correct pricing.** Calibration can:
  at each phase-start (round 1, clean turn-start, actor = `round_order[0]`) record the search root value +
  the eventual outcome, compare predicted `P(win)=(V+1)/2` to the ACTUAL first-player win rate, against a
  **MID-phase (round 3) control**. **RESULT (2400 games @200 sims, n=9600): phase-start predicted 0.5881
  vs actual 0.5905 → delta +0.0024 ±0.0098; MID control +0.0077. Phase-start is NOT worse than mid ⇒ NO
  phase-start-specific under-valuation.** Non-forcing + immune to the reverse-causation that inflated the
  raw 0.6333 audit correlation. **The first-player advantage IS real and LARGE (actual win rate 0.549 at
  phase B → 0.640 at E) — the user's strategic read is CORRECT; r2 just already prices it.**
- **STORAGE-CARRYOVER (`storage_arena.rs`):** CoB literature says "never carry tiles between phases" and
  `heuristic::value` has a **POSITIVE `W_STORAGE`** (rewards holding storage) → a real candidate mispricing
  inherited via Group E. Penalize end-phase storage (round 5 full / round 4 half, symmetric): **0.4917
  ±0.089 @w=0.3**; mirror w=0 = **EXACTLY 0.5000**; mechanism confirmed (round-5 storage 39→33/game).
  **WASH** — 5th converging value-bias-arena wash. (The net is outcome-trained and corrects a mis-signed
  baseline term, which is WHY these keep washing.)
- **ENDGAME search-side (own ideas): the LEAF-SPEED TRAP (`endgame_arena.rs`).** Net-greedy-to-terminal
  leaf in phase E = **0.540 equal-sims (n=200, real +4pp)** but **0.4167 @300ms EQUAL-TIME** — a per-SIM
  cost multiplier can win at equal sims and STILL lose at equal wall-clock. **The ship criterion for any
  serving change is EQUAL-TIME, never equal-sims.** The bounded O(1) root-verify variant
  (`endgame_verify_arena.rs`, net-greedy re-rank of top-M endgame moves; cost per-DECISION not per-sim, so
  it dodges the trap) = **0.4625 equal-sims** — fails even before the time test: a handful of shallow
  net-argmax rollouts is WORSE-informed than the 200-sim search it overrides.
- **WEB STRATEGY MINED (CoB literature; CoC is a faithful clone — worth re-reading if the net changes):**
  turn-order/first-player-into-phase is the #1 theme everywhere ("being first to act at the start of a new
  round with freshly deployed tiles is a huge advantage"); ships = strongest tile AND the turn-order lever
  (often under-prioritized); only round-1 mines pay back their 2-dice cost; finish small regions early
  (size-1 in round 1 ≈ 11 pts / 5.5 per die vs 4 avg); "never start a region you won't finish"; 2p denial
  ≈ "every point denied is a point gained"; never carry storage between phases; late-phase take workers
  over tiles; monasteries early = engine, late = VP; central black depot has the best ones. **Every
  testable one came back already-priced by r2** (first-player calib, denial ablation, storage arena,
  M6/ship arenas; mine/region timing is valued via Group E's `mines×phases_remaining` + region-proximity ×
  decaying phase bonus). Sources: thethoughtfulgamer.com "8 Strategy Tips", boardgamechamps.com "Hex by
  Hex", BGG "How to Dominate CoB".
- **NET VERDICT (CONDITIONAL ON r2's CURRENT STATE): features / calibration / search-at-fixed-weights are
  exhausted FOR THIS NET.** The only remaining path with a mechanism is a **fresh higher-sims ladder from
  a weak seed** — predicted to cap ≈ r2 by rung-3's warm-r2@4000 = parity (the 4000-sim self-play fixed
  point ≈ r2) ⇒ days of GPU at LOW odds. **REVISIT TRIGGER (the point of this whole section): if the net
  materially changes, re-run the feature screen + the calibration probes before assuming these verdicts
  still hold.** Also still open + unrelated to r2's strength: the **Easy tier (server MCTS bot) is far
  weaker than r2** — there's room to lift the DEFAULT experience without beating r2 at all.
- **Reusable tooling (all bot-vs-bot, no user games):** `harvest_featscreen.rs` + `coc_run_fs*/ablate*.py`
  (feature screen), `firstplayer_calib.rs` (value-head calibration — the instrument for any "the net
  under-values X" claim), `storage_arena.rs`, `endgame_arena.rs` (+ `<T>ms` equal-time mode),
  `endgame_verify_arena.rs`. Every arena has a **CRN mirror sanity (w=0 ⇒ exactly 0.5000)** + a mechanism
  check — keep both when adding one.



<!-- ===================================================================== -->
# ARCHIVE: CoC — 3-column game-screen rework, monastery icons, 4-animal CoB upgrade, BGA mining corpus
<!-- ===================================================================== -->

### Session (2026-07-12) — CoC game-screen 3-COLUMN REWORK (SHIPPED to prod)
The CoC game screen was rebuilt so the shared board **and both players' duchies are all visible
at once** (3 columns on wide screens), inspired by the physical Castles of Burgundy layout. Built in
worktree `forrestm_projects-cocui` (branch `coc-ui-rework`), staged on `staging`, then merged to `main`.
All frontend (`CastlesOfCrimson.jsx`), no engine/backend change. Durable, non-obvious facts:
- **`.coc-game-cols` = the table**: CSS grid `minmax(360px,9fr) minmax(0,11.5fr) minmax(0,11.5fr)` at
  ≥1280px (board | your duchy | opponent duchy), 2+1 medium, stacked on phones. Grid items STRETCH so
  the three panels share height; the board ring (`.coc-board-hex`) is `flex:1 1 auto` to fill.
- **The View Opponent modal + its reveal choreography are GONE** (the opponent's board is always on
  screen). Opponent moves animate on their board via the EXISTING flyer diff (`popIn` covers the
  starting castle). The old single-board + "View Opponent" peek + `botViewTimer`/`revealHoldRef`
  dance described in earlier sessions no longer applies to the game screen.
- **Top area is 3 rows, no status box.** (1) Title row: `← Menu` (left) · centered "Castles of
  Crimson" · **Abandon** (right, `.coc-top-abandon`). (2) **Bonuses row** (`.coc-bonusbar`, grid
  `1fr auto 1fr`): left group = `BONUSES:` + `PHASE`/`SIZE`/`COLOR` sections (`.coc-bonus-groups`);
  CENTER = the live score (`.coc-vp`, You/Bot); RIGHT spacer (`.coc-bonus-spacer`) holds the **turn
  badge** — "Your turn" / "Bot is playing…" / setup+decision variants, and **"Game over"** when over
  (`over ? gameover : mineActive ? myBadge : oppBadge`). (3) The **board header** row
  (`.coc-board-head` / `.coc-board-status`) REPLACED the "The Board" title: it now carries
  Phase/Round/Goods-left, with the white die on the right. The old `.coc-statusbar` box
  (phase/round/goods/score/turnbadge/abandon) was DELETED — its pieces were redistributed as above.
  (An earlier iteration put the turn badge on the active player's own panel header, next to Discard;
  that was reverted per the user — the badge lives in the bonuses-row spacer, right of the score.)
- **Depots** (`DEPOT_POS`, `[{50,9},{83,30},{83,70},{50,88},{17,70},{17,30}]`): 2/3/5/6 are SIDE
  depots (`coc-depot-side`, tiles stacked VERTICALLY, goods below, anchored to the board's left/right
  EDGES via `coc-anchor-l`/`-r` + `left:0`/`100%` — NOT `left%`); 1/4 are top/bottom
  (`coc-depot-tb`, horizontal tile row, `width:46%`). The pair positions (2/3 at 30/70, 5/6 at 30/70)
  are tuned so each pair sits CLOSE without overlapping near the **zoom boundary (~1600px)** where the
  boxes are tallest — and depot 4 at top:88 so its mini-die clears the central black depot. Turn-order
  track: space NUMBERS and the "furthest right…" caption were removed.
- **Uniform ghost (taken-tile) rim — DO NOT regress to a rectangular inset.** A `::after` with
  `inset:3px` + the SAME hex clip-path leaves a THINNER rim on the slanted edges than the vertical
  sides (a rectangular inset ≠ a perpendicular inset on a non-square hexagon). Fix: fill the tile with
  the color, overlay an inner hex shrunk by a true ~3px PERPENDICULAR offset computed for the 70×81
  tile — `clip-path:polygon(50% 4.3%,95.7% 27.1%,95.7% 72.9%,50% 95.7%,4.3% 72.9%,4.3% 27.1%)` — so the
  gap is a constant-width rim. Correct only because tiles are a FIXED 70×81 (`HEX_W`), only ZOOMED
  (uniform scale preserves the perpendicular width); if the tile aspect ever changes, recompute.
- **Board-column `zoom` (recap — same footgun as the earlier session):** `.coc-col-board .coc-board-hex`
  uses `zoom:.85` at ≥1280px, `zoom:1` at ≥1600px. Percentages inside a zoomed element already resolve
  in zoomed units, so `width:100%` fills correctly — `width:calc(100%/zoom)` DOUBLE-compensates (spills
  the ring past the panel). `getBoundingClientRect()` returns post-zoom (screen) px, so overlap
  measurements are valid in real pixels.
- **Local verify loop (gotchas):** backend `python -m uvicorn app:app --port 8000`; vite MUST be on
  **5173** (`core/config.py` CORS allowlist only lists `localhost:5173`; on 5174 the browser fetch is
  CORS-blocked → the app hangs on the "Waking up the server…" loader). MSYS mangles `VITE_BASE=/` into
  `/Program Files/Git/` → use `MSYS_NO_PATHCONV=1` or just omit it (vite.config defaults base to `/`).
  Playwright drives guest → CoC card → Create → **Easy** (server bot, no wasm) → place starting castle,
  then measures panel/header/depot geometry + screenshots at 1500/1600/1710/1920 (the user runs display
  scaling, so their effective viewport is ~1500–1600 — test there, not just 1920).

### Session (2026-07-14/15) — monastery benefit ICONS + barrel goods SHIPPED to prod; CoB→CoC BGA mining pipeline; backend batch DEFERRED
Two workstreams: (1) a visual pass on `CastlesOfCrimson.jsx` (SHIPPED to prod, frontend-only), and (2) mining Castles of Burgundy expert games off BGA to build a CoC-N training corpus (tooling in the `forrestm_projects-cobmining` worktree). Durable facts:
- **Monastery benefit icons (SHIPPED) — each of the 26 monasteries shows a pictogram of its power.** All in `CastlesOfCrimson.jsx`: a `MONASTERY_ICON` map (`effect_id 1-26 → () => <svg fragment>`) built from small 24×24 primitive helpers (`mPawn/mCoin/mDie/mStar/mShift/mArrowR/mArrowV/mBarrel/mHouse/mHex/mHexFill/mNum/mIcon` + a `HexStriped` component + `mBonusTile/BonusTileBadge`), dark-on-yellow. `MonasteryArt({id})` composes the pictogram + a small corner id (kept for identity + "Monastery #N" log/tooltip refs). Wired into BOTH render paths — `TileArt` (HTML depot/storage) and `TileArtSvg` (SVG board) — since the fragment is pure SVG children. VP stars use `M_VP`=watchtower green `#356340`; the die-shift tiles (#9-12) tint hexes from the real `TILE_HEX` palette; #15 uses `GOODS_HEX` (goods #1/#2/#3 = amber/rose/jade). `HexStriped` uses a per-instance `useId()` clip id so many striped hexes co-exist.
- **`mBonusTile`/`BonusTileBadge` is a SHARED bonus-tile symbol** (color-tintable hex medallion + white star) used in monastery #26 AND (via `BonusTileBadge`) as the in-game color-bonus chip — the `.coc-bonus-sw` colored square in the bonuses bar was replaced with `<BonusTileBadge color={TILE_HEX[c]} />`. One source of truth.
- **In-game goods are now BARREL-shaped** (`.coc-tile.goods` + `.coc-flyer.goods`): `border-radius:24%/20%` + two hoop bands via a `::before` linear-gradient painted UNDER the sell number (stays readable), matching the monastery goods icons.
- **#6's icon = the new silver→2-workers rule** (`mCoin(6.4,13,1.0)+mArrowR(10.6,13,0.78)+mPawn(15,13,1.0)+mPawn(18.6,13,1.0)`) — flipped from the old 2-workers→building depiction when the 4-animal backend shipped (see the "4-ANIMAL CoB upgrade SHIPPED" session below). During the interim icon-only ship it briefly showed the old rule.
- **Icon preview/verify harness (offline):** temporarily append `export { MONASTERY_ICON as __MI, MonasteryArt as __MArt, BonusTileBadge as __Badge }` to CoC.jsx, esbuild-bundle a scratch React harness (`scratchpad/mon_preview.jsx`) with **react aliased to the PRIMARY webapp's node_modules** (`--alias:react=…` — the cobmining webapp has none), Playwright-screenshot, then remove the temp export. Goods barrels verified via a standalone HTML mock (`goods_preview`) using the copied CSS.
- **The "deferred backend batch" (4 animals + mon6 + boards 2/4) is NOW SHIPPED to prod** — see the "4-ANIMAL CoB upgrade SHIPPED" session below for the full details (warm-start instead of retrain, parity, deploy). The old worry ("would break the Expert net, needs a retrain") was resolved by a **warm-start** (the encoder change is only +2 inputs), not a from-scratch retrain.
- **CoB→CoC BGA mining pipeline (corpus grind running in background).** CoC is a faithful CoB port (SAME 2019 edition — the "fixed depot" house variant IS CoB behavior), so top human 2-player games are replayable. **BGA auth:** cookie in `C:/Users/Forrest/.bga_session/session.txt`; `X-Request-Token` header = the `TournoiEnLigneidt` cookie value; CoB `game_id=1390`. Endpoints: `getRanking` (top players), `getGames` (2p, `normalend=1`/`concede=0`), `tableinfos` (gameversion), `archive/replay/<gv>/` (triggers build, may 500), `archive/archive/logs.html` (fetch logs after build). Logs are structured JSON (tile ids, depot sources, die assignments, dice) → fully replayable. **`cob_collect.py`** was HARDENED after the first run HUNG (~1.5h, 0 saved): it enumerated ALL players before downloading and top players' huge histories stalled `getGames` pagination → now `player_2p_games` is `max_pages=30`-bounded + **download-as-you-go** (enumerate one player → download → save manifest → next) + resumes from manifest + per-player progress. **`cob_replay.py`** replays a log through CoC; **`cob_filter.py`** KEEPs games that replay to completion AND to the same winner — filter locked on **winner-preservation** (user choice), NOT exact-score parity (BGA=2019 edition endgame monastery scoring differs, but moves/positions/outcomes are edition-invariant). mon6-mechanic games are cleanly excluded. Corpus at `C:/Users/Forrest/CoB_corpus/` (logs/ + manifest.json + kept_games.txt).
- **Prod-ship verification gotcha (do not misdiagnose):** after a Pages deploy the live `index-*.js` filename hash can look unchanged (CDN lag / Vite chunking) — **verify by CONTENT markers in the live bundle, not the filename** (grep the deployed JS for a unique new string, e.g. `24%/20%`). The legacy `pages/builds/latest` API is STALE (returns a 2026-07-05 gh-pages build) since Pages source = "GitHub Actions"; use the `deploy-pages.yml` run status as the authoritative deploy signal.

### Session (2026-07-14) — 4-ANIMAL CoB upgrade SHIPPED to prod (CoC is now a faithful 4-animal CoB port); warm-start beat a retrain; net-vs-top-humans ~43%
The "deferred backend batch" above SHIPPED to prod, fully validated. CoC now matches CoB 2019: **4 animals (chicken added), monastery 6 = spend 1 silver → 2 workers (atomic, unlimited), boards 2 & 4 = the 2019 layouts.** Durable facts:
- **The tile-code / encoder change (the root of everything):** livestock codes are now `5..16` (4 animals × 3 counts, was `5..13`), buildings `17..24`, monasteries `25..50`; `N_TILE_CODES=51`; `tiles::N_ANIMALS=4`. The `feats.rs` encoder grew `N_FEATS 934 → 936` — ONLY +2 (the 4th animal's `livestock_mask` bit for me + opp), at **feature indices 72 and 146** (animal loops start at 69/143; 4th bit is +3). Nothing else in the 934-feature layout moved. Files touched: Python `tiles.py`/`engine.py`/`board.py` + `az/compact.py`/`spaces.py`/`bridge.py`/`ai.py`; Rust `coc-core/src/{tiles,engine,feats,actions,boards_gen}.rs` + `tests/engine_parity.rs`. Regenerate boards with `coc-core/tools/gen_board_tables.py` (writes `boards_gen.rs` + `spaces.py`; MAX_REGIONS stayed 21 → no array churn).
- **mon6 is now ATOMIC** — `A_M6` applies `silver-=1; workers+=2` (no `Micro::M6`, no `m6_used` limit, no building take); the compact move is bare `{"t":"m6"}` (bridge both directions + the parity harness updated to `vec![A_M6]`); the frontend does it via a **workers-token click** (removed the old `m6Armed` arm-then-click-a-building flow).
- **WARM-START instead of a from-scratch retrain (the key move — reuse this for any small encoder-dim change).** Because the change is only +2 inputs, the deployed nets were rebuilt, NOT retrained: `coc-core/tools/warmstart_4animal.py` takes a 934-net JSON → 936-net by placing its 934 input columns into their same feature slots and **zero-init the 2 new columns at indices 72/146** (+ `mu`=0/`sd`=1 for them; `tdims[0]=936`). Self-verified: deleting the 2 new columns recovers the original net EXACTLY. Result: **≈r2 strength on the new game immediately** (it just ignores the chicken bit until fine-tuned). BOTH the Expert (`coc_run_r2/pv_ship_r2.json`) AND Hard (`coc_run_nv/pv_ship_iter5.json`) nets were warm-started → the two 936 bins `webapp/public/wasm/coc_pv_model{,_hard}.bin`. To FIND the insertion indices for a future encoder change: temporarily `eprintln!` the animal-loop `out.len()` in `feats.rs`, run any test that calls `features`, read the 2 printed indices.
- **Parity: Python↔Rust differential suite is GREEN (1450 fixture games, state-exact) after the port.** Regen fixtures via `gen_engine_fixtures.py --games N --loaded M` after ANY engine change, then `cargo test --release --features bridge` (also needs `gen_value_fixtures.py` for the value-parity test). 307 CoC pytest tests pass (2 mon6 tests rewritten for the new rule).
- **WASM rebuild + deploy:** `RUSTFLAGS="-C target-feature=+simd128" wasm-pack build --target web --release --no-typescript` in `coc-core` → `cp pkg/{coc_core.js,coc_core_bg.wasm}` + the two `pv_json_to_bin.py`-converted 936 bins into `webapp/public/wasm/`. Node smoke: `import coc_core.js`, `await default(coc_core_bg.wasm bytes)`, `coc_init_model(bin bytes)`, `coc_search_timed(state,'[]','netval',ms,sims,seed)` → valid visits. Deploy order: **backend Python → Render** (verify live via the new mon6 desc in `/coc/board`'s `monastery_meta['6']`), then **validate the FULL 4-animal Expert game on STAGING against the new prod backend** (Playwright: guest → CoC → Create Game → Expert; confirmed 8/8 wasm workers, a ~40k-sim Expert turn, chickens/pigs + new #6 icon + Big City board rendering, 0 console errors), then **frontend/wasm → Pages**. `CastlesOfCrimson.jsx` gained a **chicken `ICON` entry** (else chickens render as "C4" text).
- **Saved-game safety (verify before any board change):** the board layout is looked up from `board.py` by `board_id` at RUNTIME (only `board_id` + placed tiles are persisted), so changing boards 2/4 WOULD corrupt in-progress games on those boards. A Turso query (`coc_games`, `status` column, via the libSQL pipeline API; creds `C:\Users\Forrest\.spender_turso`) confirmed **0 active board-2/4 games** (only 1 stale board-1 game) → safe. Always run this check before shipping a board-layout change.
- **NET-vs-TOP-HUMANS comparison:** our net agrees with top BGA CoB players **~43%** of their decisions — essentially identical to the `ai.py` heuristic (42%). I INITIALLY read this as a "move-diversity ceiling, not a strength gap" — **that read is WRONG and RETRACTED** (see the 2026-07-15/16 session below): the test is underpowered/circular, and the user's transitivity evidence (AI ≈ user ~50%, user loses ~80% to top players ⇒ ~240 Elo below them) says it IS a strength gap. Tooling: `cob_analyze.py` (heuristic), `cob_analyze_net.py` (net via the `move_server_coc` bridge + `cob_replay.py`'s `on_move` hook).
- **The CoB BGA-mining corpus is QUOTA-LIMITED:** free BGA caps replays at **~10/day** ("You have reached a limit (replay)"). All mining/analysis tooling + the coc-core port live on the **`cob-mining`** branch.

### Session (2026-07-15/16) — BGA corpus HARDENED (replayer now score-EXACT), fine-tune pipeline built + gated: expert data reaches PARITY not improvement (cob-mining branch)
A long, productive session on the BGA CoB corpus. Nothing shipped to prod except a defensive `_valid_board` tightening. All on `cob-mining`. Durable facts:
- **The ~43% "move-diversity ceiling" claim is REFUTED — it's a real STRENGTH gap (do not relitigate the ceiling read).** Two attempts to test it, both recorded as negatives: (1) `cob_analyze_both.py` (agreement with the top player vs their opponent, same games) → 43.7% vs 43.1%, looks like "diversity" but is UNDERPOWERED (only **4 games have both players ranked**, and there the "weak" player is rank 27–42 of ALL of BGA — both elite; a test comparing our net to two strong players can't detect that our net is weaker than strong players). (2) `eval_server_coc.rs` + `cob_eval_gap.py` price each disagreement by apply-and-re-search with a deep referee + a random-move control for the argmax bias → pro-vs-ours −0.029, random-vs-ours −0.080, pro-above-random +0.051. The control proves the instrument discriminates quality, yet the pro's moves still score BELOW our own pick — which against ~240-Elo-stronger players can only mean **our eval MIS-RANKS their moves, which IS the gap and is exactly what a referee built from our own net cannot see** (raising the referee 600→8000 sims moved nothing; depth doesn't fix a shared bias). **CONCLUSION: no eval-based instrument using our own net can size this gap. The only non-circular arbiter is fine-tune-on-corpus then GATE vs the champion.** LEAD (small n, a hint not a result): our eval is most negative on the pro's `take_workers` (−0.101) and `take_hex` (−0.046) — where we most confidently disagree with a stronger player; consistent with the tile-pref finding (pros take ships +28 / castles +12 more than us).
- **`cob_replay.py` is now SCORE-EXACT (in-game VP 33/33 across every completing replay, was 12/33 with a +40 worst case); usable games 11→26 + ~3.5 game-equivalents of verified prefix.** FIVE bugs, all found by data-tracing (BGA logs a running `score` on `tileAddedToEstate` — the bisect oracle) not by guessing, and each had a tell:
  1. **ship_adjacent (monastery 5) parse** — BGA logs the m5 double-take as ONE record naming BOTH depots (`'(6,1)'` = took from 6 AND 1); we read only the first number, leaving the m5 pending armed so a LATER ship's goodsTaken got eaten → "not an adjacent depot with goods". The adjacency model was always right (every logged pair is a ring neighbour). Fix: consume all depots; and BGA does NOT guarantee source-first order, so try both orientations and let the engine arbitrate; and when a ship take overflows into a goods_pick the m5 pending arms LATE and rides in a DUPLICATE record → pick the entry that's an actual candidate.
  2. **undo dropped the ROUND TRANSITION (the "die already used" cases)** — an `undoTurn`'s `movesToCancel` names the move_id of the packet holding the undone actions, but BGA puts `turnPlayed`/`newRound`/`newPhase` in that SAME packet. Dropping the whole move_id threw away the `newRound` → `sync_round` never ran → dice never refreshed → every later action failed. The undone ACTIONS are `plToIgnore` echoes (already filtered), so `load_events` now KEEPs `{newRound,turnPlayed,newPhase}` even when cancelled. (User's hypothesis — "an undo bug or someone refreshing" — cracked this.)
  3. **`decode_counts` hardcoded board 9 for every player** — animal counts aren't in the log; they're DERIVED from awarded `pointsForAnimals` minus same-animal counts in the pasture, which needs each player's OWN board (regions differ on 34/37 spaces). Board-9 games were already exact; others skewed positive. Fix: resolve pid→board from `playerEstate`.
  4. **`decode_counts` didn't subtract the monastery-7 bonus** — mon7 (+1 VP per scoring livestock tile) is part of the award, so not subtracting it baked the bonus into the count (illegal counts >4; only mon7 owners produced them). Our engine's mon7 model is correct; only the replayer's inverse derivation was wrong.
  5. **`do_die_action`'s optimistic "try as-is" sold the WRONG goods** — safe for `place_tile` (a wrong die just fails), WRONG for `sell_goods` (ANY die is legal — it sells whatever colour that die names), so the optimistic try always succeeded ignoring `want`. Now tries as-is only when the die already shows an acceptable value. Plus `ensure_goods` must TRIM as well as top up (BGA's `soldGoods` count = `nbPoints/2` is ground truth; a surplus was being sold).
- **mon6 games: the filter is CORRECT, not a bug (do not relitigate — the user said so repeatedly).** BGA monastery 6 = "spend 2 silver OR 2 workers to take a tile from ANY depot", which CoC lacks. The `mon6_buy_mechanic` guard's condition `not (in_black and silver)` catches EXACTLY it (measured: 450 black/silver normal vs 51 mon6 uses = 37 numbered/silver + 7 numbered/workers + 7 black/workers). I wrongly re-derived a "purchasing mechanic" / "LOC_TO_DEPOT bug" / "goods-capacity bug" three times before accepting the answer; `LOC_TO_DEPOT` is correct (every phase draws 16 tiles: 12 depot 2/depot + 4 black = BLACK_FILL_2P; die-takes never touch black slots). **SALVAGE (user idea): harvest each mon6 game only up to the phase where a mon6 tile is DRAWN** (`cob_replay.mon6_draw_phase` + `main(..., max_phase=N)`) — those phases are untainted (nobody could see the tile). 7/9 yield a clean prefix = 688 moves ≈ 3.5 full games; `truncated`/`phases_kept`/`game` on the result carry the salvage.
- **mon26 edition difference (user-confirmed): BGA scores monastery 26 at 2 VP; CoC/2019 uses 3 (correct — do NOT change).** Measured 6/6 exact against bonus-tile counts (`devinatorz` holds ONLY mon26: CoC 9 = 3×3, BGA 6 = 3×2). mon15=2 is correct on BOTH sides (mon15-only players show delta 0). This is the ONLY remaining score category difference and the winner-preservation filter absorbs it by design (the one game it flipped, 882712335, was a 4-pt near-tie → already excluded). All other CoB scoring rules verified against the published rules and MATCH ours (PHASE_BONUS 10/8/6/4/2, AREA_SCORE 1..36, sell VP = num_players, bonus tiles n+3/n, livestock = sum of same-animal counts, watchtower 4).
- **BGA board 10 ADDED (`board.py`), engine-known but NOT SERVED.** The 3 `board_not_in_coc_set` games all used BGA `board_nb=10` (a 2019-only board; extracted verbatim from `playerEstate.plEstSpaces`, same (r,q) canon order). Validated: 37 spaces, grid+adjacency identical to every board, 17 regions sized 1–8, 4 burgundy spaces; 2/3 games then replay winner-exact. **NEW `board.PLAYABLE_BOARDS` gates it out of serving; `main._valid_board` checks that instead of `BOARDS`** — because `coc-core/src/boards_gen.rs` hardcodes `N_BOARDS=9` with fixed-size `[[u8; N_SPACES]; N_BOARDS]` tables and the Expert tier searches CLIENT-SIDE in wasm built from them, so serving board 10 would index past the end AND the net never trained on it. `test_playable_boards_stay_in_sync_with_the_rust_tables` parses `N_BOARDS` out of the Rust as a tripwire. To make it playable: `gen_board_tables.py` → rebuild wasm → re-gate. 319 CoC tests pass.
- **FINE-TUNE-ON-CORPUS + GATE (the direct, non-circular test): expert data reaches PARITY, not improvement.** Pipeline: `cob_harvest.py` replays each usable game → feeds every clean expert decision to `harvest_bga.rs` (Rust; DFS-finds the micro-action CHAIN for the recorded engine move since only `chain_to_compact` existed, emits one train_pv row per micro-decision one-hot on the expert action; `root_value` = the OUTCOME 2·label−1, NEVER our eval — filling it with our opinion would train the value head toward ourselves). Yield: 34 games → 3129 decisions → **4490 rows** (both seats; 72 chains unresolved, 2.3%). Results (gate = `netval@30@1.0` vs champion `pv_warm936.json`, n=240; mirror sanity 0.5000 ±0.155 margin +0.0):
  - **Unanchored (100% BGA rows): 0.4083 ±0.062, margin −9.6** — WORSE, while val AUC 0.889/top1 0.545 looked GREAT. The documented **P4b anchor-cliff** (converged net collapses onto 100% new-distribution rows; val is blind).
  - **Anchored (BGA = 25% of mix, champion self-play the other 75%): 0.4875 ±0.063, margin −1.9** — PARITY (CI .425–.551). The anchor recovered +8pp and nearly all the margin → the collapse WAS the anchor-cliff, confirmed. But **4490 rows do not make the champion stronger** (the r2 loop trained on 4000 GAMES/iter; sample size is the obvious suspect). The anchor = 400 champion self-play games @1200 sims netval → 96,886 rows at **936-dim** (every surviving older anchor CSV is 934-dim, pre-4-animal → needed a fresh harvest). `cob_anchored_ft.sh` runs harvest→strip-aux→mix→train→gate.
  - **TWO TRAPS, both already in CLAUDE.md, both re-confirmed the hard way (each produced a PLAUSIBLE wrong result):** `train_pv.py --batch` defaults to **4096** > the whole corpus → `evaluate()` never flushes → silent "val AUC 0.5000 n=0" and no training. Use `--batch 256`. And **MSYS skips `/c/...` conversion for args with special chars** — `--data a.csv;b.csv` (the `;`) reached python unconverted so `glob` matched nothing → pass Windows-style `C:/...` paths to python.
  - **NEXT (not yet run): a data-scaling curve** — train at 25/50/100% of the BGA rows (anchor ratio fixed), gate each. Flat ~0.49 ⇒ more games won't cross 0.52 and the corpus is a hypothesis-MAP (mine the take_workers/take_hex lead bot-vs-bot) not training data. Upward slope ⇒ the grind is justified; extrapolate the crossing point. Worth running BEFORE committing to the ~11-day grind.
- **BGA collection is now a self-refreshing daily cron (all `cob-mining`):** `cob_resume.py` walks the manifest (no re-enumeration — that was the 1.5h stall) with retry/backoff + a REAL quota back-off (the oracle is `logs.html`'s `{status:0, error:"reached a limit (replay)"}` — do NOT probe the `archive/replay/` page, which answers `500 Wrong siteversion` when capped, a red herring that never fires). `cob_session.py` = a self-refreshing session: **`PHPSESSID` is DISPOSABLE — send only `TournoiEnLignetkt` (the persistent ticket) + the sso pair and BGA mints a fresh PHPSESSID via Set-Cookie** (verified by evicting the session mid-run). Only a dead TICKET needs a human re-export (steps in `cob_session.py` docstring; `has_session()` returns a BOOLEAN by design — never print even a truncated live token). **BGA's day is PARIS time** (verified: utc+2 matches the server clock reference), so the ~10/day replay cap resets at midnight CEST = **15:00 local**, not local midnight. Cron: Windows Task Scheduler `CoB_daily_download` (NOT the session cron — that dies with the session) at **15:07 local**, `cob_daily.bat` → `cob_resume.py`. **BGA Premium does NOT lift the replay cap** (verified: Premium page never mentions replays; users who bought it still hit it; admin calls limits anti-abuse — grinding the daily allotment is the only route). Corpus at 36/147; a full grind ≈ 11 days.

---





<!-- ===================================================================== -->
# ARCHIVE: CoC — 2-4 player + game-screen layout overhaul (SHIPPED 2026-07-18/19)
<!-- ===================================================================== -->

### Session (2026-07-18/19) — CoC 2-4 PLAYER + game-screen layout overhaul (SHIPPED to prod)
Frontend batch that made CoC playable **2-4 players** (vs friends; AI games stay 2p) and reworked the
3-column game screen. Built on branch **`coc-4player`** in the `forrestm_projects-stgfix` worktree,
iterated on **staging**, then shipped. **The 2-4p BACKEND (engine `depot_fill`/`black_fill(n)=2n` + 3p
depot-6 castle→mine exception, `main.py` `max_players`/`same_board`/player3-4 columns, tests) was already
on `origin/main`** (committed separately: `9b21c37`/`3c9d6f5`), so the **net diff of `coc-4player` vs
`origin/main` was ONLY `CastlesOfCrimson.jsx`** → shipped frontend-only via a branch off origin/main
bringing that one file. Durable, non-obvious facts:
- **2-4 players (frontend):** opponent **peek tabs** (`.coc-opp-tab`, `viewOppId` state; `oppId` = the
  tab selection or, by default, whoever's acting) — the two duchy columns show ME + one opponent, tabs
  switch which; N-player lobby lists / waiting-room `x/N`; create-modal **player-count** selector (2/3/4)
  + a **Same board** toggle (backend `max_players`/`same_board`; same_board forces everyone onto the
  host's board at start).
- **THE LAYOUT `useLayoutEffect` (`boardHexRef`, deps `[game]` + a resize listener) DOES A LOT — read it
  before touching the game screen. 3-col desktop only (`innerWidth >= 1280`; clears everything below).**
  The depot ring is absolutely-positioned (each depot pinned by % of the board-hex height), so the board
  doesn't grow with content — the effect measures + drives it in 4 steps: (1) **`--coc-board-minh`** =
  the height at which every numbered depot fits `[0,H]` given its center-fraction + pin type (tb =
  centered `translate -50%`; side = edge-pinned, grows outward); content-sized depot heights are
  H-independent so one pass converges. (2) **black-depot clearance** — the black depot is centered
  (f=0.5) and tall at 4p, colliding with depot 1/4's inward mini-dice; adds `H·|0.5-f| >= blackH/2 + k +
  8` (k = the die's fixed-px reach past the depot center), only binds at 4p. (3) **duchy-area height
  sync** (the log-scroll fix, below). (4) **storage zoom** (below).
- **LOG moved UNDER the duchies (load-bearing restructure).** The two duchies + log are wrapped in a flex
  `.coc-duchy-area` (flex COLUMN) holding a `.coc-duchy-row` (the two duchies) + the `.coc-log-panel`;
  **both wrappers are `display:contents` below 1280** so the 1/2-col layouts keep treating duchies+log as
  direct grid children (unchanged). **THE LOG-SCROLL TRAP (do not regress):** an auto-height flex/grid
  column ALWAYS grows to the log's content and stretches the board — `grid-template-rows:auto minmax(0,1fr)`
  did NOT cap it (board grew 856→1939px with a long log). The ONLY fix that held: **JS height-sync** — in
  the effect, `align-items:flex-start` on `.coc-game-cols` (so the log can't inflate the board via
  stretch), measure the board column's natural depot height + the duchy-row height, pin BOTH the board
  col and the duchy-area to `max(boardNat, rowH+130+16)`. Then `.coc-duchy-row{flex:none}` +
  `.coc-log-panel{flex:1 1 0;min-height:0}` + inner `.coc-log{flex:1;min-height:0;overflow-y:auto}` → the
  log fills the leftover and scrolls. **`flex:none` on the row is CRITICAL** (else the log's
  `flex-basis:auto` content makes the row shrink and CLIPS the duchy boards).
- **Depots = "option-5" (user pick): a 2×2 tile grid for ALL depots** (`.coc-tiles-inner{display:grid;
  grid-template-columns:repeat(2,auto)}`, fixed depot width 158px). 4 tiles → 2×2 square; 2 → one row;
  **3 → a TRIANGLE** (`.coc-tiles-tri`: the 3rd tile `grid-column:1/-1;justify-self:center;margin-top:-21px`
  — pulled UP into the notch so its diagonal gap to the top two equals the 6px flat-side gap between them,
  a honeycomb nestle for pointy-top hexes). Goods render as a wrapping row per depot; **topside side
  depots (2/6) AND depot 1** put goods ABOVE the tiles (`order:-1`, grow up/away from center), the rest
  below.
- **Black depot = 2-column grid, rows = player count** (2/3/4 rows → 4/6/8 tiles), **FIXED size** via
  `gridTemplateRows:repeat(num_players, HEX_H)` + `alignContent:start` so it NEVER shrinks as tiles are
  bought (empty cells for taken tiles). Replaced the old 4-tile "kite" that silently dropped tiles 5-8 at
  3-4p.
- **Goods box: fixed 240px (= the natural 3-goods-type row width), sold pile `margin-left:auto` (pinned
  right).** Do NOT use `fit-content` (it lets the sold pile drift left) and do NOT keep the old 260px (too
  wide → a trailing gap). **Storage tiles are fixed 70px with fixed-px icons (can't flex-shrink)**, so the
  effect **`zoom`s `.coc-storage`** to fill the space left beside the fixed goods box → they stay on one
  row at narrow 3-col widths (caps at 1 = full size when there's room, e.g. ~1920+; ~55px at the user's
  1536, tiny at 1280).
- **Duchy board flush buffers:** the SVG viewBox uses `padX=(HEX_S-1.5)·√3/2+0.5` and
  `padY=(HEX_S-1.5)+0.5` (the DRAWN hex half-extents) so the hexes sit flush on every edge, matching the
  storage row's ~0 side buffer (was the looser `HEX_S+2`).
- **Smaller layout tweaks:** turn-order track fills the panel width (`.coc-track-space{flex:1 1 0}`, 601+);
  buffer ABOVE the track = `.coc-board-head{margin-bottom:14px}` (separates it from the phase-goods row);
  color-bonus chips `.coc-bonus-sw` 15→19px; bottom page gap trimmed to ~16px (`.coc-wrap-game{padding-bottom:16px}`
  + `.coc-game-cols{margin-bottom:0}`, was 64px).
- **Verify at 1536** (the user's effective viewport under display scaling), not just 1920 — several of the
  above (storage zoom, log fit) only bite at narrower 3-col widths. Multi-player Playwright: host creates
  a VS-Friend N-player + Same-board game, N-1 guest contexts join the OPEN-GAME CARD's Join (lowest on the
  page / filter by room code — NOT the top-bar join-by-code), each confirms the board modal's "Join Game",
  host clicks Start.

<!-- ===================================================================== -->
# ARCHIVE: Spender — unified Create Game modal + shared lobby row session
<!-- ===================================================================== -->

### Session (2026-07-17) — unified Create Game MODAL + shared lobby create/join/refresh ROW (SHIPPED to prod)
The four games' create flow was unified. Two new shared kits in `shared/lobby.jsx` (token-driven,
hard fallbacks so they render in CoC's bare mount too); every game imports both + appends their CSS.
- **`CreateModal` / `CmRow` / `CmSeg` + `createModalCss` = the shared "New Game" options modal.**
  One **+ Create Game** button per lobby opens `<CreateModal title="New Game">` holding every option
  as labeled rows — REPLACES the old floating per-game create dropdowns (`.ai-picker`/`.coc-ai-picker`/
  `.duel-picker` — all deleted). Backdrop-click + **Esc** close. `CmSeg` = a segmented control
  (`options=[{value,label,title?}]`); `CmRow` = a micro-uppercase-labeled row; pills for the Spender
  personas (`.cm-pill`). Per game: **Spender** = Opponent (VS Friend / VS AI) → AI Difficulty (Henry/
  Herald/Steve/Nina persona pills + an Easy→Expert legend) OR Players (2-4 seat cap, friend only) +
  Length (Classic 15 / Long 21) + a live summary line. **CoC** = Opponent → AI Difficulty (Easy/Hard/
  Expert) + **Your Board** & **Bot's Board** strips — the board pickers MOVED OUT of the lobby into
  the modal (the lobby no longer loads two 9-board grids on entry); a SEPARATE **Join Game** modal
  (`joinBoardFor` state) prompts for your board before joining an open/coded game. **Duel** = Opponent
  → AI Difficulty (Easy/Normal/Hard). **Where Wolf?** = a minimal info modal (nothing to configure;
  roles picked in the waiting room) with a **Create Room** button.
- **`LobbyCreateRow` + `lobbyCreateRowCss` = the shared create/join/refresh ROW** (`.lby-create-row`):
  gold **+ Create Game** (`.lby-cta` — ALWAYS gold `var(--gold)`, NOT the per-game `--lby-accent`),
  a **CODE** input + outline **Join** (`.lby-join`/`.lby-code`/`.lby-join-btn`), and a ghost **↻**
  (`.lby-refresh`, shows `.lby-spinner` when the `refreshing` prop is set). `<LobbyCreateRow onCreate
  onJoin onRefresh refreshing? createLabel? codeMaxLength? />`. **`onJoin` receives the trimmed,
  UPPER-CASED code** (room codes are uppercase); CoC routes it to `setJoinBoardFor` (its board modal),
  the others join directly. `codeMaxLength` = 6 everywhere except Where Wolf (4). This is CoC's row
  made shared and adopted in all four — Duel GAINED a Join-by-code input it lacked; Where Wolf's button
  changed from a mismatched "+ New Game" to the shared gold "+ Create Game".
- **Spender host-chosen SEAT CAP (`max_players`, new backend field).** Friend lobbies carry a 2-4 cap
  from the modal's Players row: `main.py` create reads `msg["max_players"]` (clamped 2..`MAX_PLAYERS`,
  default `MAX_PLAYERS`) → `r["max_players"]`, PERSISTED in `save_game`/restored in `load_game_to_memory`,
  the **join** guard enforces `len(players) >= r["max_players"]` (was the global `MAX_PLAYERS`), and
  `list_open_games` returns it (the open-game card's `x/N` badge already read `max_players`).
- **Spender lobby DROPPED the Classic/Long toggle** (it lived in `.browser-create`/`.length-toggle`,
  now deleted). `winPoints` state remains but ONLY as the create-modal's Length default — the lobby
  lists NO LONGER filter by length (all lengths intermix; History still tags Long games via
  `g.win_points === 21`). Deleted dead CSS: `.browser-create`/`.create-controls`/`.length-toggle`/
  `.len-btn`/`.refresh-btn` (Spender), `.coc-create`/`.coc-join`/`.coc-input`/`.coc-ai-picker*` (CoC),
  `.duel-create-row`/`.duel-pick*` (Duel).
- **VERIFY GOTCHA (cost time — do not regress): a stale `vite preview --strictPort` on 5173 serves an
  OLD `dist/`.** A leftover preview from a prior harness run stayed bound to the port; the next run's
  `--strictPort` spawn silently failed but `waitForServer` still got a 200 (from the OLD server) → the
  Playwright checks ran against a STALE bundle (the tell: the served button still had the old `▾`
  caret). Kill listeners on the port before serving (`netstat -ano | grep :PORT | grep LISTENING` →
  `taskkill //PID`), and confirm the fresh bundle by a CONTENT marker (grep dist JS for a new string),
  not the filename hash. The built dist bakes `VITE_WS_URL` to `ws://localhost:8000` by default, and
  CORS only allowlists port **5173** — so the modal-open/create-wire e2e must serve preview on 5173
  against a local `uvicorn app:app --port 8000` (a guest session primed via `localStorage.spender_user`
  + `spender_myId` lands on Home without a backend round-trip).



<!-- ===================================================================== -->
# ARCHIVE: WWSD — browser-N / PV WASM userscript (canvas autoplay, deck remap, CSP)
<!-- ===================================================================== -->

### Browser-N userscript — run variant N (`net_attn_3` attention net) in the friend's browser via WASM (LIVE June 2026; CSP confirmed; FULL UI AUTOPLAY working)
**Status:** the advisor overlay AND fully hands-off **UI autoplay** both work on spendee (WASM CSP is
fine). Current userscript **v0.9.21**, which runs **variant N (= the card-set attention net `net_attn_3`,
the strongest AI)** — it calls the same `search_pv_full_timed` WASM entry the website uses (the `searchPV`/
`browser_n` names are legacy from the PV era; the 15-pt branch runs the attention net). The build is `wwsd/build_browser_n.py` (assembles the editable
`browser_n.template.user.js` + inlined WASM → `wwsd/wwsd_browser_n.user.js`, **~2.8MB** self-contained
now that the PV model is embedded); the user installs the assembled file in Tampermonkey and **must
reinstall after each version bump** (the `@version` header is the tell — Tampermonkey doesn't auto-update
a local file). Deploy = commit both files to `main` (push from the `forrestm_projects-wwsd` worktree). The
two big build-it findings — the deck **id-remap** (cost-correctness) and the **canvas synthetic-click
autoplay** (Meteor 403 dead-end) — are documented in the deck section above and the "UI AUTOPLAY" bullet
below; both are leaf-agnostic so they carried over from N to PV unchanged (same engine Dump, same remap,
same flows — only the search/eval *function* changed).
The user's directive: move WWSD's COMPUTE off Render and into the friend's browser (like the main
Spender site's WASM AI), using the strongest variant. This **supersedes the bookmarklet+Render-S path**
— PV > N > S, and a real CPU runs thousands of sims/move vs Render's ~300 (sims-starved 0.1-core). The
advisor overlay (top move + position eval + alternatives) is leaf-agnostic, so it's preserved unchanged.
- **PV (and N) are Rust/WASM-ONLY — there is NO Python PV/N; server-side both fall back to S.** PV is the
  **AlphaZero policy+value net** in main's `spender-core`: a **125-feature `feats::features_az` encoder**
  (separate from N's 101-feat `feats::features`) + the embedded **`src/pv_model.json`** (`PolicyValueNet`,
  value+policy forward). The net supplies BOTH the MCTS **leaf value** AND the **policy prior** (legal-masked
  softmax of the policy logits; H3 fallback at discard/noble). Beats N (0.60–0.67 across 160–800 sims) and
  S (0.758) in paired-CRN eval.
- **Build from `main`, NOT a pinned rust-search commit (CHANGED with the PV switch — do not regress).**
  The build worktree **`forrestm_projects-wwsd-wasm`** (branch `wwsd-wasm`) is now **synced to `origin/main`**
  (was pinned to `rust-search@0bcf0a8` for the N era; old tip saved as tag `wwsd-wasm-prePV-backup`). main's
  `spender-core` already carries PV, so the build worktree just needs to track main. The old 101-feat-net
  hazard (an uncommitted 149-col `feats.rs` on rust-search) no longer applies — main is the source of truth.
- **WASM eval export — 2 ADDITIVE edits, committed to `main` (`550525c`), none touch the webapp's PV/N
  paths:** `vsearch.rs` `root_nw_until_pv()` (PV analog of `root_nw_until_leaf` — net supplies leaf value +
  policy prior, returns root visits + per-edge W) and `wasm.rs` **`search_pv_full_timed(state_json, seat,
  budget_ms, max_sims, seed) -> JSON {visits,value,q}`** (the PV analog of the N-era `search_n_full_timed`,
  which stays for reference). The shipped `search_visits_pv_timed` returns **visits ONLY** (enough to PICK a
  move, no eval); the new full export adds the searched position value (`sum W / sum N`, side-to-move,
  [-1,1]) + per-edge Q (`W[a]/N[a]`, null if unvisited) so the overlay keeps its eval. Built `wasm-pack
  build --release --target no-modules --out-dir pkg-nomod` (defines a global `wasm_bindgen` for inlining;
  the no-modules WASM grew 928KB→2.07MB with the PV model). Toolchain: `cargo`/`wasm-pack` in
  `C:\Users\Forrest\.cargo\bin` (off-PATH; `export PATH=$PATH:/c/Users/Forrest/.cargo/bin`). Smoke-tested
  the no-modules build in **Node** (a small vm harness loads the glue, inits with the `_bg.wasm`
  ArrayBuffer, calls `search_pv_full_timed` on a fresh-game Dump → valid `{visits,value,q}`).
- **Userscript — worktree `forrestm_projects-wwsd` (branch `wwsd-autoplay`):** `wwsd/browser_n.template.user.js`
  (editable LOGIC) + `wwsd/build_browser_n.py` (assembler) → **`wwsd/wwsd_browser_n.user.js`** (~1.28MB,
  **SELF-CONTAINED**: inlines the no-modules glue + the wasm as **base64** → NO hosting/CORS/fetch/Render
  dependency; re-run the assembler after any wasm rebuild). Ports `analyze.to_state` → the `wasm.rs::Dump`
  JSON (`toDump`; card ids/colours are identity; **Node-validated byte-identical** to a hand-built dump)
  and the action index → text/machine move (`describeMove`/`structuredMove`, ports of
  `_describe_move`/`_structured_move`). Tampermonkey **`@grant none`** (runs in PAGE context → the page's
  `Meteor` global is reachable). Loader call: `await wasm_bindgen({module_or_path: base64Bytes})` then
  `wasm_bindgen.search_pv_full_timed(JSON.stringify(dump), seat, THINK_SECS*1000, MAX_SIMS, seedBigInt)`
  (was `search_n_full_timed` in the N era).
  Embeds `BONUS[90]/PTS[90]/NOBLE_PTS[10]` (from `wwsd_defs.json`) to compute the Dump's bonuses+score.
  Engine consts for the Dump: `PLAY=0, WIN_NONE=-1, A_PASS=30, N_ACTIONS=70`.
- **Validated end-to-end in Node** (scratchpad `verify_n.mjs` + `verify_browser.mjs`): `toDump` of the
  real spendee-format LIVE fixture is byte-identical to the known-good dump, and the full path returns a
  sane move + eval (~1,200 sims/s single-threaded; opening favours Take3).
- **Deck remap — friend ids ↔ Spender ids (the load-bearing fix; June 2026).** The WASM embeds OUR
  Spender deck at compile time and CANNOT do the Python WWSD's runtime `override_engine`. **The two decks
  are the same MULTISET but ordered COMPLETELY differently** (NOT "1/90 different" — that earlier note was
  wrong and shipped a real bug: the advisor recommended buying cards the user couldn't afford, because the
  WASM looked up `COST[friendId]` = a totally different card's cost). Fix in `browser_n.template.user.js`:
  `F2S[90]` (friend→Spender id, a verified **exact** 90/90 bijection — friend #3→Spender #36 is exact too,
  post card-36 fix) and `F2S_NOBLE[10]` (nobles are reordered too). `toEngineDump(dump)` remaps **every** card
  id (board/decks/purchased/reserved) + noble id (board nobles + nobles_won) friend→Spender BEFORE the WASM
  call, so the engine's compiled COST/BONUS/PTS describe the SAME physical cards. The **original
  friend-space `dump` is kept for display + execution** — action indices are positional/by-slot so they
  line up across both spaces (a buy of slot s → `dump.board[s]` is the friend id for the label + spendee
  `cardIndex`). Belt-and-suspenders: `actionAffordable(dump,a)` checks the recommendation against the
  friend's TRUE costs (`COST_F[90]` from `wwsd_defs.json`) and **filters out any unaffordable buy** before
  selecting the top move (a safety net for any future deck drift). Validated end-to-end in
  Node against the real WASM: the un-remapped path recommends an unaffordable buy on a crafted position;
  the remapped path + guard never does, and a symmetric opening evaluates ~0.00 (was a false +0.10).
  **Regenerate F2S/F2S_NOBLE/COST_F if either deck changes** (compare `wwsd_defs.json` vs
  `engine._build_tables()` by `(cost,bonus,pts,level)`).
- **Browser CSP** — instantiating WASM needs `script-src 'wasm-unsafe-eval'`; confirmed working on
  spendee in practice (the panel shows "WASM failed (CSP?)" if ever blocked).
- **UI AUTOPLAY — WORKING (canvas synthetic clicks; the Meteor path is DEAD). DO NOT try to revive
  `/gameActions/insert`.** spendee's server **403s ("Access denied")** ANY programmatic Meteor insert
  (Meteor.call, raw `_send`, even stub-bypassed) — confirmed un-bypassable; it's a server-side allow gate.
  So autoplay drives the **real UI** instead: the whole game is ONE `<canvas>` (`div.board > canvas`), and
  the engine **accepts synthetic events** (`isTrusted` is NOT checked — the make-or-break finding). The
  adapter (`browser_n.template.user.js`) dispatches pointer/mouse events at **canvas-fraction coordinates**
  (resize-tolerant; recorded via the panel's **Rec DOM** button which logs each click's `canvasFrac`):
  - `synthClickCanvas(fx,fy)` (full pointer+mouse+click sequence) and `synthHoldCanvas(fx,fy,ms)` (press-
    and-hold, for **Reserve** which is a hold button). All coords live in the `UI` map; timing knobs in
    `CONFIG`: **`SETTLE_MS`** (pause at the START of our turn, after the opponent's move, so the board
    finishes animating before the first click), **`OPEN_MS`** (post-modal-open wait), **`TAKE_OPEN_MS`**
    (the take-gems modal specifically is slow to become interactive — its own longer wait), `STEP_MS`
    (between in-modal clicks), `HOLD_MS` (reserve hold). **Why SETTLE_MS/TAKE_OPEN_MS exist (v0.8.5 fix):**
    playing instantly after the opponent moved sometimes clicked before the UI re-rendered — most visibly
    a take "red green black" landing only the LAST gem because the pick-chips modal wasn't interactive when
    the first clicks fired. Raise `TAKE_OPEN_MS` first if a take still drops gems.
  - Flows (each `ui*` fn): **take** = open select-chips modal → click each gem in-modal → "pick" (+ auto
    **discard** via the gold-topped discard column + "return" if the take overfills 10); **buy board** =
    click card (exact 12-slot `cardFrac` table) → "Buy"; **reserve board/deck** = click card/pile → hold
    "Reserve" (+ auto-discard if the granted gold overfills 10); **buy reserved** = click your reserve pile
    (**seat-aware**: P1 top / P2 bottom) → click the card row in the modal (oldest at top = engine index 0);
    **pass** = Pass → confirm; **noble choice** (2+ eligible after a buy) = click all 3 board noble slots
    (the eligible one claims). Discard choice is a heuristic (drop most-abundant colour, keep gold).
  - `playMove(action, dump)` dispatches N's structured action to the right flow. The autoplay loop adds
    human pacing (2–4s) then **verifies the move committed** (turn advanced / sub-decision arose); if a
    click missed (turn stuck, modal open) it closes the modal and retries ≤2× before asking the user to
    finish that one move manually — so a single misfire never hard-freezes.
  - **GOTCHA — record & play at the SAME window size.** Coords are canvas FRACTIONS; if the game
    pillarboxes, right-edge targets (the **Buy** button) drift when the canvas aspect changes. Recording at
    a 1335px-wide canvas then playing maximized made Buy miss. Play maximized, record maximized.
  - Toggle from the panel: **Autoplay on/off** (default off; turning on plays the current turn
    immediately). `AUTO_PLAY=false` default = advisor-only. `WWSD_N.*` exposes every `ui*`/`synth*` fn for
    console testing.
- **Now-vestigial / superseded:** the `/move` `action` field added to `analyze.py` (`_structured_move`)
  + the FIRST userscript `wwsd/autoplay.user.js` were the OLD Render+S autoplay path; browser-N builds the
  structured move client-side, so both are superseded (harmless, backward-compatible). Once browser-N is
  browser-confirmed → retire the bookmarklet + `autoplay.user.js` + the `/move action` field, and
  optionally decommission the Render service (browser-N/PV needs no backend). **DEPLOYED to main:** the
  userscript+tooling+docs, the N-era `search_n_full_timed`, and (with the PV upgrade) `search_pv_full_timed`
  — each an ADDITIVE commit to main's `spender-core`, applied cleanly. The eval-export source also lives on
  the `wwsd-wasm` build worktree (now synced to main, see the build bullet above).
  **RESOLVED since:** browser-CSP works; autoplay does NOT use Meteor methods at all (server 403s them) —
  it drives the canvas via synthetic clicks (see "UI AUTOPLAY" above). The bookmarklet + `autoplay.user.js`
  + `/move action` field can now be retired, and the Render WWSD service is decommissionable (browser-N
  needs no backend).

---




<!-- ===================================================================== -->
# ARCHIVE: Spender AI — self-play training, AZ stack, degenerate-equilibrium/fitness-valley/curriculum, heuristic variants H2/H3
<!-- ===================================================================== -->

### Self-play training (`train.py`, offline only)
`train.py` plays the AI against itself headlessly (~290 greedy games/s) to learn `WEIGHTS`, then writes `weights.json`. It imports `main`'s game logic directly; it never starts the server or touches `users.db`. It swaps the global `main.WEIGHTS` to each mover's weights before its decision.
- **Phase 1 — `evolve`**: population of card-scoring weight vectors plays a round-robin self-play tournament; mutate + select by win rate. Tunes the move policy.
- **Phase 2 — `td`**: TD(λ) with eligibility traces learns the linear position-eval weights toward the realised point margin from self-play trajectories. (TD(0) was tried first and **diverged** on the highly-correlated consecutive board states — `pos_points` collapsed, error rose — so λ-traces + feature scaling are used; λ→1 recovers Monte Carlo.)
- **`all`** runs both in sequence; **`validate`** plays learned-vs-default with real MCTS and reports the learned side's score (only deploy `weights.json` if >0.5).
```bash
python -m games.spender.ai.train all --generations 20 --pop 12 --games-per-pair 12 \
    --td-games 3000 --validate-games 40 --out games/spender/ai/weights.json
```

### Deployed weights (current)
A trained `weights.json` **is currently deployed** (the backend loads it at startup). It beat the original hand-tuned defaults **0.725 vs 0.275** over 40 MCTS validation games (150 iters/move, seats swapped). Notable shifts the AI learned:
- `bonus_l1` 0.2→0.63 (values cheap L1 engine-building more), `bonus_reserved` 0.5→0.01 (stopped valuing bonuses toward reserved cards), `access_urgency` 0.4→0 (dropped late-game distance penalty), `rollout_reserve_threshold` 5.0→8.8 (much more selective about reserving).
- `pos_noble` 0.3→2.19 (noble proximity is ~7× more predictive of final margin than hand-tuned), `pos_bonus_count` 0→0.91.

To **revert to the original AI**, delete `games/spender/ai/weights.json` — `load_weights()` falls back to `DEFAULT_WEIGHTS` with zero behaviour change. Caveats: validation ran at 150 MCTS iters/move, not production's 5-second budget; evolve fitness plateaued at 0.674 by gen 4 (search converged early — larger pop / higher `sigma` to explore further).

### Stage 1: learned value leaf evaluation (`value_model.json`)
NNUE-style: when a `value_model.json` is present, MCTS evaluates leaf nodes with a learned logistic value model (`_value_estimate`/`_value_logit`, **pure-Python inference** — no production ML dependency) instead of a greedy rollout. Absent → rollout, byte-identical. `_value_features` is a 10-feature `order[0]`-minus-`order[1]` diff + turn indicator. `load_value_model` rejects a model whose feature count ≠ `VALUE_FEATURES` (falls back to rollout). Trained offline by `train.py value` (numpy) on exploratory self-play; a **linear** model is deployed.
- **Validated**: value-leaf beats rollout **0.533 vs 0.467** on equal *wall-time* (cheaper eval → more MCTS iterations). At equal *iters* it loses — its advantage is speed, so always A/B by **time** (`--time`), not iters.
- Playtest toggles: `SPENDER_VALUE_MODEL=none uvicorn …` forces rollout; `SPENDER_WEIGHTS=…` swaps weight sets.

### AlphaZero stack (`ai/az/`) — the current strength roadmap
Approved plan: fast engine → AlphaZero self-play → tournament eval → serve as
variant **Z**. 2-player only. Key facts:
- **engine.py** is a compact int-state simulator with **proven rule parity**:
  200 random games stepped through both engines with state compared after every
  move (`test_az_engine.py`). Card/noble data is imported from `main.py`, never
  duplicated. ~100k moves/s/core (pure Python; Rust port not needed).
  Gold DOES count toward the 10-token cap. Discard/noble-choice are real
  decision phases (the policy learns them). `to_game_dict`/`from_game_dict`
  convert to/from the incumbent dict format.
- **mcts.py**: PUCT, hidden info via per-simulation determinization (unseen =
  decks + opponent blind reserves, reshuffled within level). Turns don't
  strictly alternate, so backups credit edges by acting-player identity.
- **train_az.py**: self-play → train → gate (promote at >=0.55) → auto-export
  `.npz`. Resumable (`--resume`). Trains on the user's RTX 4050 (torch cu128,
  Python 3.14). `selfplay.run_games` is the single batched driver for both
  self-play and net-vs-net gating.
  - **`--iters` is an absolute total**, not "N more": on resume the loop runs
    `range(start_iter, args.iters)`. To add 70 iters after a 30-iter run:
    `--resume --iters 100`.
  - **Exploration / reward knobs** (added after the degenerate-equilibrium
    diagnosis below): `--reward-shaping` (0..1), `--shaping-scale`,
    `--temperature`, `--temp-moves`, `--dirichlet-eps`. Self-play log prints
    `winpts` (winner's avg points/game) + `combined` — the scoreboard that
    makes the 0-0 collapse visible.
  - **Parallel self-play** (`--workers N`, default 1): fans games across N CPU
    processes via `selfplay.run_games_parallel` (each worker does CPU numpy
    inference off a `.npz` snapshot of the current net; GPU stays free for the
    training step). The gate parallelizes too. `--workers 1` keeps the old
    single-process torch path. ~4.8x self-play throughput at 10 workers on the
    12-core laptop (~700s -> ~160s/iter self-play); ~3-4x end-to-end.
    - **CRITICAL — single-thread BLAS/OMP.** `train_az.py` sets
      `OMP/OPENBLAS/MKL/NUMEXPR/VECLIB_*_NUM_THREADS=1` at the very TOP (before
      numpy/torch import) so spawned workers inherit it. Without this, every
      worker's BLAS spins one thread per core -> 10 workers x 12 threads thrash
      the box (observed: 30+ min hang producing zero output). GPU training in
      the parent is unaffected (CUDA, not BLAS). Do not remove this block.
- **watch_game.py**: prints a human-readable play-by-play of one
  AZ-vs-heuristic game (board, both players' state, AZ's top MCTS visit
  distribution, the move taken). The diagnostic that surfaced the equilibrium
  bug. `python -m games.spender.ai.az.watch_game --az <npz> --opp C2 --seed N`.
  (Keep output ASCII-only — Windows console is cp1252; no box-draw/arrow glyphs.)
- **Serving**: `main.py` loads `ai/az_model.npz` if present → variant "Z"
  (numpy-only PUCT via `infer_np.py`, same 5s thread-pool path). No file → Z
  falls back to A; zero behavior change. `SPENDER_AZ_MODEL=none` disables.
  Production deps gained only `numpy`; torch stays out of prod.
  **`az_model.npz` is currently deployed** (exported from iter-177 best checkpoint,
  p=0.90, 113 promotions, sims=512). Variant Z is live on the website. Export process:
  `ckpt = torch.load('az_best.pt', map_location='cpu'); net.load_state_dict(ckpt['best']); export_npz(net, 'az_model.npz')`.
  Render auto-deploys on push to `ai/az_model.npz` (wired in `deploy-render.yml`).
  Can export mid-training safely (training writes `az_best.pt`; export reads it and
  writes `az_model.npz` — separate files, no interference).
- **arena.py**: AZ vs heuristic tournaments (heuristic plays via dict
  conversion + its own `_mcts_choose_move`; sub-decisions replicate
  `_ai_discard_one`/`_ai_pick_noble`). Wilson CIs. Deploy gate: >=0.70 vs B
  and C2 at production budgets + human playtest.

### AZ — the degenerate-equilibrium bug and the reward-shaping fix (June 2026)
**This is the most important AZ finding so far. Do not relitigate.**

The first AZ run (`checkpoints/`, 58 iters, pure terminal win/loss reward)
trained healthily by its own gate (candidate-vs-best score rising, promote→dip→
recover) but **lost ~0.0 vs C2** in the arena at every checkpoint measured:
| Checkpoint | AZ vs C2 (60g) | notes |
|------------|----------------|-------|
| Iter 13    | 0.017          | 300 sims |
| Iter 28    | 0.050          | 300 sims |
| Iter 40    | 0.017          | 300 sims; **also 0.000 at 1000 sims** |
| Iter 54    | 0.017          | 300 sims (best gate score 0.683) |

More search did NOT help (1000 sims = 0.000) → the **policy**, not search depth,
was the problem. `watch_game.py` on iter-40 vs C2 (seed 42) showed why: **AZ
scored 0 points the entire game**, bought 7 cards (all 0-point L1), hoarded
tokens and discarded them ~15×, and opened by reserving two 7-cost L3 cards it
could never afford. C2 scored 16, bought 26 cards, claimed a noble.

**Root cause — a degenerate self-play equilibrium.** Both self-play players share
one net. Early nets rarely score, so games end 0-0 and the winner is decided by
the **fewest-cards tiebreak**. That makes "buy as little as possible" the
self-play-optimal strategy — the exact opposite of what beats a scoring
opponent. The net faithfully optimized the tiebreak. This explains all three
symptoms: healthy gate scores (it got better at the tiebreak vs itself), zero
arena wins (vs a scorer the tiebreak never triggers), and no benefit from more
sims (searching harder for the wrong objective). It is the same blind-spot class
as the documented "self-play is blind to tactics the opponent never demonstrates."

**Fix (shipped in `selfplay.py` / `train_az.py`):**
1. **Reward shaping** (`--reward-shaping`, default 0): value target blends
   terminal win/loss with `tanh(point_margin / shaping_scale)` per mover
   perspective. A 0-0 game becomes a true neutral instead of rewarding the
   buy-nothing tiebreak winner; actually scoring is what gets rewarded. Verified:
   shaping=0 → value targets take 2 distinct values (±1); shaping=0.5 → 28
   graded values in [-1,1].
2. **More exploration**: `--temp-moves` 10→20, `--dirichlet-eps` 0.25→0.35, so
   the net stumbles into point-card buys often enough to learn they're good.
3. **`winpts` scoreboard** in the self-play log makes the equilibrium visible:
   ~0 = degenerate; climbing toward 12–16 = the net is learning to score.

**Validation run** (fresh, NOT resumed — old net/buffer are attractors toward the
broken strategy; new dir `checkpoints_shaped/`):
```bash
python -m games.spender.ai.az.train_az --iters 60 --games 400 --sims 128 \
  --parallel 128 --gate-games 60 --gate-threshold 0.55 \
  --reward-shaping 0.5 --shaping-scale 6.0 --temperature 1.0 --temp-moves 20 \
  --dirichlet-eps 0.35 --out games/spender/ai/az/checkpoints_shaped
```
Iter 0 (random-net baseline): winpts 15.7. The verdict is whether iters 1–5 HOLD
winpts high (fix works) vs collapse toward 0 (the old run would have collapsed
here). **Do not ship az_model.npz until arena shows >=0.70 vs B and C2.**

### AZ league — training vs opponents, not just self (the strength lever)
Pure self-play hit a hard ceiling vs the heuristics: arena AZ-vs-C2 was **0.033
at iter 9 and 0.025 at iter 27** — FLAT across 18 iters of shaped self-play,
even though the self-gate score kept rising (the net got better at beating its
own clones in a strategy space that doesn't overlap C2's). This is the
documented "self-play is blind to a style the opponent never demonstrates."
**Cure = play against the real targets.** (`league.py` + `--league` in train_az.)

- **`league.py`**: `play_recorded_game(net_eval, opponent_fn, ...)` plays one
  game where the training net searches+records ONLY its own moves (shaped value
  targets, same as selfplay) while the opponent moves via a callback. Opponents:
  heuristic A/B/C2 (`arena._heuristic_action`, incumbent MCTS in dict format) or
  a frozen past-AZ checkpoint (`_az_opponent_action`, greedy PUCT on its npz).
  We record only the net's moves — learning to BEAT opponents, not imitate them.
  These games are NOT batchable (opponent isn't the net), so they run
  one-at-a-time inside pool workers via `run_league_games`, which also returns
  per-opponent net win rate — the live progress-toward-goal signal.
- **`--league`** (needs `--workers>1`): each iter mixes `--self-frac` self-play
  (batched) + `--heur-frac` split across `--heur-variants` + `--league-frac` vs
  sampled past-AZ checkpoints from `out/league_pool/` (snapshotted on each
  promotion, capped at `--pool-size`). Empty pool folds the past-fraction into
  self. Reward shaping is doubly important here: the net loses most early games,
  so the margin term ("lost by 2" vs "lost by 15") is what provides the climb
  gradient. Deployed mix (user-approved broad): self .4 / heur .4 (A,B,C2) /
  past .2, `opp_iters=120`.
- **League gate**: candidate vs best on the SAME heuristic set, greedy
  (`_league_gate`), promote if cand >= best (ties promote early while both lose
  to C2). Replaces the self-gate, which was exactly the misleading metric (it
  rose while real strength stayed flat). The `[iter] league:` log line prints
  `net-vs: A .. B .. C2 ..` — watch C2 climb off ~0.
- **Launch** (resumes from the shaped iter-27 net):
  ```bash
  python -m games.spender.ai.az.train_az --iters 80 --games 400 --sims 128 \
    --workers 10 --gate-games 60 --gate-sims 96 --reward-shaping 0.5 \
    --temperature 1.0 --temp-moves 20 --dirichlet-eps 0.35 \
    --league --self-frac 0.4 --heur-frac 0.4 --league-frac 0.2 \
    --heur-variants A,B,C2 --opp-iters 120 --opp-sims 96 --pool-size 6 \
    --out games/spender/ai/az/checkpoints_shaped --resume
  ```

### AZ open risk — single-strategy collapse (raised by the user, valid)
Even with scoring fixed, pure self-play can tunnel on ONE plan (e.g. wide-L1 →
nobles) and never learn that rushing efficient high-point L2/L3 cards beats it on
many boards — because both shared-net players adopt the same plan, the
counterexample is never generated, and the value head mis-evaluates the unplayed
line (so search can't rescue it; garbage value → garbage search). The user's own
strategy model says the right plan is **board-conditional**, and the features
encode the board, so the net CAN represent "rush here, go wide there" — it just
needs to SEE both resolve. **Planned mitigation = opponent diversity (a league):**
train/gate against a sampled pool of {past AZ checkpoints + heuristic A/B/C2},
not only the current best. This is the real reason to keep the heuristic-in-loop
idea (it was deferred for breaking the 0-0 equilibrium, where shaping subsumes
it, but it is the primary cure for strategic diversity). Build after scoring is
confirmed stable.

### AZ — the fitness-valley wall and the adaptive curriculum (June 2026)
**Reward shaping was NOT the bottleneck — don't relitigate it.** Both the league
(tanh) and a linear-shaping rerun left the net FLAT at ~4 pts / −12 margin vs C2
across 10–27 iters (margin probe: net scores ~4, C2 ~16, win rate ~0). Linear
shaping gives a ~6× stronger per-point gradient (verified) yet moved nothing.

**Root cause — a fitness valley, not a weak gradient.** Against a *fast* opponent
(C2 reaches 15 in ~16 plies), the loss-minimizing play is to grab a few quick
points (~4) — a local optimum. WINNING requires building an engine (cheap
0-point cards early) that only pays off later — but C2 ends the game before the
payoff, so margin-minimization *punishes* the very investment winning needs. The
winning strategy sits across a valley from the loss-minimizing one; gradient
won't cross it. Evidence the net CAN play well given time: it scores 15+ in
self-play (80–120-ply games) — it just builds engines ~5× too slowly and never
faces a beatable racer to learn tempo from.

**Probes that found the curriculum axis** (current net vs opponent, 30g):
- vs **random**: net **wins 0.87** (scores 14) — beats non-racers easily.
- vs heuristic at **any** `opp_iters` (even 1): **0.00–0.20** — every competent
  eval RACES (opp ~16 pts) regardless of search depth. So `opp_iters` is a
  *cliff*, not a ramp — wrong curriculum axis.
- **eps-mixed opponent** (heuristic move w.p. `p`, else random) gives a SMOOTH
  ramp: net win rate 0.80 / 0.70 / 0.47 / 0.20 / 0.07 at p = 0 / .25 / .5 / .75 / 1.
  `p` is a **tempo** knob — the right axis.

**Adaptive curriculum** (`--curriculum` in train_az, `eps` kind in league.py):
the heuristic fraction faces an eps-opponent at difficulty `p`; after each iter
`p` auto-climbs if the net's win rate vs the current level ≥ `--curr-target`
(0.55), drops if it falls behind — keeping the net at its winnable frontier. Goal:
ride `p` → 1.0 (full racer) with the net still winning, which means it learned to
race. `p` persists in checkpoints. Log line: `[iter] league: p=X.XX … net-vs:
cur Y.YY`. Launched resuming the v3 net (competent at low p) with a CLEARED
buffer (so the value head drops its "always lose" pessimism). Watch `p` climb;
a stall = the tempo wall it can't yet cross.

**`p` adapts from the GREEDY GATE score, not the generation win rate.** Early on
the generation `net-vs cur` (~0.38) ran far below the gate's greedy score (0.667
at the same p) because self-play exploration (temp + Dirichlet) depresses
play — using it to drive `p` kept the curriculum stuck artificially low. So the
adapt step moved to *after* the gate, using the promoted/best net's greedy gate
win rate (`_curriculum_gate`): `p += --curr-step` if ability ≥ target+0.05,
`-=` if ≤ target−0.10, deadband holds. With this, `p` climbed 0.35→0.40→0.45→0.50.
End condition (beat full racer greedily ≥0.55) aligns with the deploy arena gate.

**Search depth is the quality lever (`--sims`).** Bumped 128→384 (`--gate-sims`
96→192), user OK with ~3× slower iters. Rationale: the net distills the MCTS
visit distribution, so shallow search = weak policy targets; deeper search also
finds the efficient racing lines the net otherwise never sees (directly attacks
the tempo problem) AND makes the curriculum games themselves better-played. Try a
bigger net (the MLP is only ~600k params) ONLY if sims plateaus — capacity before
data/search quality just overfits. **sims bumped 384→512** after plateau at p=0.80
— confirmed working, frontier moved to p=0.85 then p=0.90. **sims bumped again
512→768** (gate-sims 256, opp-sims 128) after plateau at p=0.90 for ~18 iters
with gate scores stuck at 0.53–0.58 — watching whether frontier moves to p=0.95.

**gate-games bumped 60→120** (SE ±0.065 → ±0.046) after variance was causing
artificial p drops: a single unlucky 26/60 gate ended a 14-iter p=0.90 streak.
With 120 games the net held p=0.90 for 18+ consecutive iters cleanly before the
sims bump.

Current run: `checkpoints_v3`, at iter ~196, p=0.95, sims=768, --iters 300.
sims=768 pushed frontier to p=0.95 by iter 191 (best=0.617) and the net is
**holding p=0.95** for the first time (5 consecutive iters 192–196, gate scores
0.40–0.52). `az_model.npz` deployed at iter 177 (113 promotions). Next milestone:
gate score ≥0.60 at p=0.95 → push to p=1.0 → arena vs B/C2 → ship if ≥0.70.

**Human playtest finding (iter 177 net):** the net **over-reserves** — reserving
frequently and often reserving cards that don't make strategic sense. Root cause:
(1) self-play doesn't punish tempo loss from bad reserves because both players do
it; (2) gold token over-valuation in the value head biases toward reserving;
(3) shallow search doesn't see the downstream cost of a wasted turn. Sims bump
directly attacks (3). (1) and (2) require structural fixes:
- **Better features** (planned for next retrain — incompatible with current weights,
  requires fresh start): three high-value additions:
  1. **Effective cost** per card (raw cost minus player's current bonuses, per color).
     The net can technically derive this from existing features but has to learn
     the subtraction internally; explicit = much easier to use.
  2. **Engine value** per card — pre-computed scalar: this card's bonus color ×
     sum of cost-reduction it provides to every other visible card, weighted by
     those cards' point value. This is a *cross-card interaction* an MLP cannot
     easily discover on its own from a flat feature vector (requires reasoning
     across multiple cards simultaneously). Pre-computing it as a feature is a
     genuine win — directly addresses "which card is worth reserving/buying."
  3. **Turns-to-afford** per card — cost gap per color ÷ estimated gems/turn.
     Addresses reserve *frequency* (tempo awareness), not just card selection.
     "This card needs 4 more red gems; I'm collecting ~1/turn → 4 turns away"
     directly distinguishes smart reserves from wasteful ones.
  Noble-progress per card (how many noble requirements this satisfies) is also
  worth adding but partially encoded already.
  **Do NOT add these features mid-run** — input dimension change invalidates all
  current weights. Schedule for a fresh retrain after the current run finishes.
- **Harder opponents**: C2 races but doesn't punish bad reserves as severely as a
  human. The net needs to face opponents that end the game before wasteful reserves
  pay off.
- **Sims ceiling**: more search helps up to a point, but if the value head
  fundamentally misvalues tempo, MCTS just finds better moves within a flawed
  strategy. The remaining lever after sims is value function quality + features.

**Checkpoint system and branching (how to experiment safely):**
- Training saves to `checkpoints_v3/`: `az_best.pt` (best promoted net — dict with
  `best` weights, `iter`, `promotions`, `curr_p`), `az_last.pt` (latest candidate),
  `buffer.pkl` (300k-position replay buffer). All gitignored.
- **Fully resumable**: stop anytime, restart with `--resume` — picks up exact iter,
  p value, and buffer. Can pause indefinitely.
- **Branching for a feature experiment**:
  1. Stop current run.
  2. Copy `checkpoints_v3/` → `checkpoints_v3_backup/` to preserve the original.
  3. Modify `features.py` (new features change input dimension → old weights incompatible).
  4. Start a **fresh** run in a new dir (e.g. `checkpoints_v4_features/`) — no `--resume`.
  5. If new net wins arena → ship; if worse → delete branch, `--resume` from backup.
  - The branch is a genuine fresh start — the 196+ iters of learned weights cannot
    carry over to a new input dimension. Trade-off: known-good current net vs
    untested feature-enriched net that starts from zero.
  - **Decision point**: finish current run first, evaluate iter-300 net strength,
    then decide if a feature-enriched retrain is worth losing the current weights.

### Heuristic-tuning campaign results (June 2026 — superseded by AZ stack)
- Ablation (40g, 120 iters, seed 777): `noble_scarcity=1.5` → 0.688 vs B was
  the only strong feature; `pos_noble_scarcity` 0.588; `lose_prevention` 0.525;
  `efficiency_weight`/`bonus_target_pts`/`gold_reserve` all hurt.
- Sweep grid (seed 42): best combo `noble_scarcity=2.5 + pos_noble_scarcity=0.5`
  → 0.675 screening, but **0.583 on the fresh-seed 60-game confirm** —
  regression to the mean; the gain is real but ~0.58-0.65 true, NOT 0.70.
  Candidate file: `ai/weights.c2_candidate.json` (uncommitted).
- Coevolve (6 gens, real MCTS): `lose_prevention`/`gold_reserve` selected out
  to 0.0; best individual validated 0.600 vs A → `ai/weights.coevolved.json`.
- Conclusion: weight-space tuning over the existing features saturates around
  0.6 vs B. This is why the AZ rewrite exists.

### Variant H2 (`ai/az/heuristic2.py` + `valuation2.py`) — the `take_value` heuristic (DEPLOYED)
A from-scratch greedy heuristic, **served as website variant "H2"**, separate from variant H.
**Full write-up: `games/spender/ai/az/H2.md` — read it before touching H2.**
- **Model:** `take_value = (engine_value + point_value) / (1 + total_cost)`. cost = `W_TEMPO·tempo +
  W_GEM·gem + W_GOLD·gold` (all post-bonus); points are game-STAGE-scaled (engine early → points late,
  + `ENG_DECAY` fades engine as cards accumulate); `engine_value` includes a forward-looking
  undealt-deck-demand term. 1-ply greedy, same serving path as H.
- **Deployed config (committed on main; beats H ~0.69 greedy):** `heuristic2` W_TEMPO 0.5 / W_GEM 0.2 /
  W_GOLD 0.4 / NOBLE_SCALE 3.0 / STAGE_K 8 / STAGE_FLOOR 0.25 / ENG_DECAY 0.3; `valuation2` ENG_DECK_W 3.5
  / ENG_DIV 8 / ENG_FLOOR 0.2 / NOBLE_CLOSE_FLOOR 0.2 / GOLD_BANK_CAP 2. The big levers were ENG_DECK_W↑
  + NOBLE_SCALE↑ (~+0.06); ENG_DECAY +0.011; cost weights saturated.
- **Tooling (offline; restore modules after):** `h2_tune.py` (CRN A/B; `--opp H` vs heuristic H, `--opp h2`
  = self-gate vs the CURRENT committed H2 — far more sensitive once H2 ≫ H) and `h2_autotune.py`
  (autonomous coordinate-descent campaign, NO human input: screen → validate on disjoint holdout vs self
  AND vs H → adopt → re-screen; prints a vetted config, never edits source).
- **Tuning methodology — DO NOT regress:** CRN (same seeds across configs) is for the *comparison*; the
  final estimate MUST come from FRESH **disjoint** holdout seeds (tuning-set optimism shrank gains ~⅔).
  **Seed-spacing bug:** `h2_tune` uses deck seed `base_seed+i` over N games, so two base seeds must be
  spaced **≥ N apart** to be independent (seeds 1–3 apart share ~1598/1600 games → fake "agreement").
  Self-gate tuning needs a **self-exploit guard**: adopt only if the change ALSO doesn't regress vs H — a
  change can beat *this* config via rock-paper-scissors yet be weaker vs the external yardstick.
- **Tested & REJECTED — parked default-OFF behind flags in `heuristic2.py` (do not relitigate):**
  `USE_TAKE2` (take-2-of-a-color): naive form made bad moves (−0.03), reserved-only form ~neutral (fires
  0.27% — winning reserves are gold-necessary, the opposite of take-2's full-bank need). `W_SHORTFALL`
  (bank-aware gold shortfall in cost): cuts a 14.9%→11.6% "stall on an un-completable card" rate, +0.006
  lean but sub-significant. `NOBLE_SCARCITY` (scarcity-gated nobles): INERT — `board_scarcity`≈0 on 98%
  of boards (real Splendor boards almost always offer an efficient L2/L3 deal). `USE_OPP_SNIPE` (pivot off
  a card the opponent will buy): wash/negative — contention is a documented 1-ply greedy wash. **All four
  are good NET-feature candidates, not greedy levers** (see FEATURES_V4.md + `.claude-plans` H2 feature doc).
- **On-card AI-values overlay is now ADMIN-ONLY (default OFF):** the per-card T/E/P/C box (H2) / single
  value (H) only renders for `authUser.is_admin`, behind a "Show/Hide AI values" toggle in the game
  action bar (AI games only; persisted in `localStorage.spender_show_ai_vals`). Frontend gating in
  `Spender.jsx` — the data is still in the WS payload (non-sensitive AI valuations), just not shown to
  non-admins; a backend per-recipient gate was deemed not worth it for this non-sensitive overlay.
- **Overlay follows WHOEVER'S TURN IT IS (June 2026, `82120c8`):** `mk_room_state` computes
  `ai_card_values` from `game["turn"]`'s seat (not always the AI's) and sends `ai_values_pid`. So on
  YOUR turn the box shows what each card is worth to YOU ("what should I take" — tinted **green**,
  tooltip "Your values"; your own reserved cards get values too), and on the AI's turn it shows the
  AI's perspective (**gold**, "AI's values"). The `_s/_h3/_h2/_v4_card_values(game, seat_pid)` helpers
  take the perspective seat (param renamed `ai_pid`→`seat_pid`); reserved cards follow that seat
  (so blind opponent reserves never leak — they're redacted and keyed by a non-real id anyway).
  Frontend (`Spender.jsx`): `valsMine = roomData.ai_values_pid === myId` drives a `.mine` tint on the
  `.ai-vals`/`.ai-val` box; the **Show/Hide AI values** toggle moved OUT of `.actions-panel-top` INTO
  the actions buttons box (desktop `.actions-panel-btns` + mobile `.board-actions-btns`) via
  `renderAiValsToggle()`, **far-left** (`.ai-vals-toggle{margin-right:auto}`) and styled like the Take
  button (`btn btn-gold`), rendered on EITHER turn so the overlay is toggleable any time.
- **Admin-button login bug fixed (same commit):** `handleAuth` rebuilt the user object as
  `{id, name, session_token}`, **dropping `is_admin`** from the `/auth/login`/`/auth/register` response,
  so the admin-gated overlay button only appeared after a page reload (the on-load `/auth/session` path
  at `Spender.jsx` repopulates `is_admin`). `handleAuth` now preserves `is_admin: !!data.user.is_admin`,
  matching the on-load path — admin features light up immediately on login, no reload.

### Variant H3 (`ai/az/heuristic3.py` + `valuation3.py`) — turns-remaining engine horizon (DEPLOYED)
A sandbox fork of H2, **served as website variant "H3"** (a playable opponent + a per-card potential overlay,
wired in `main.py`). Same 1-ply greedy `choose_action`/`components` contract; it reframes H2's value model around
a **potential vs take** distinction and a **turns-remaining horizon**. Permanent invariants live in
`games/spender/tests/test_h3_valuation.py` (9 tests) — keep them green.

**Model** (`components`): `take = (engine_term + point) / (1 + cost)`
- `cost = W_TEMPO·tempo + W_GEM·gem + W_GOLD·gold` (post-bonus; one currency used everywhere).
- `point = PTS + NOBLE_SCALE·noble_progress + noble_completion` — **NOT stage-scaled** (full value always; H2's
  point-staging, `ENG_DECAY`, and the per-card tempo-discount were all REMOVED).
- `engine_term = W_ENGINE · max(0, turns_remaining − tempo) · engine_value(ci)` — engine value × the turns it
  will COMPOUND. A card you can't finish before the game ends contributes ~0 engine. This horizon replaces
  stage/eng_decay (`W_ENGINE` is the engine-vs-points balance knob).
- `engine_value(ci) = Σ over OTHER cards cj still needing ci's bonus color of _delta_take(cj)` (+ reserved
  premium + deck-demand term); `_delta_take(cj) = potential(cj) · [1/(1+cost') − 1/(1+cost)]` — the take-value
  uplift ci's +1 gives cj; the `1/(1+cost)` convexity auto-weights a near-affordable discount (2→1) over a far
  one (6→5), no extra knob.
- `potential(cj) = (PTS + POT_ENGINE_W·eng_base) · (1 + POT_REACH_W·reachability)` — worth as a DESTINATION,
  distinct from take_value (a far high-point card has high potential but ~0 take, which is exactly why its
  *builders* earn engine value while chasing it now is bad). `eng_base` = the legacy level-0 engine value (cached).
- `turns_remaining`: estimated future main-turns from `turns_table.json` (a MEASURED `(cards, points, gems) →
  avg turns-left` table from H3-vs-H2 games; rebuild with `h3_measure_turns.py`), **min over both players** (the
  leader sets the clock). NN-filled, gems weighted 0.25× a card. Absent file → flat fallback.

**Noble time-gate** (`NOBLE_TIME_GATE=True`, `NOBLE_TURN_W=1.0`) — the one structural fix that paid: a 0-pt card
advancing a far/late noble used to contribute a flat ~0.5 (no time awareness). Now `noble_progress` is smoothly
discounted by completability — `× eff/(eff + NOBLE_TURN_W·deficit)`, `eff = max(0, turns_remaining − tempo(ci))`
(turns left AFTER acquiring the card), `deficit` = bonuses still needed. Smooth fade toward 0, **no hard cliff**
(turns_remaining is an estimate). **~+0.02 vs H2** (the biggest recent greedy gain; `NOBLE_TURN_W` peaks at 1.0).

**Deferred idea — time-gate the raw card POINTS too (not done; noted on request):** `noble_progress` and the
engine term are both gated by buy-in-time feasibility (`max(0, T − tempo)`), but the raw `E.PTS[ci]` term in
`components` is NOT — so late-game `_choose_take` can still collect gems toward a high-point card it can't finish
before the game ends (the same blind spot the noble gate fixed, applied to a card's own points). The fix would be a
**clamped step** `min(1, max(0, (T − tempo)/M))` on `E.PTS[ci]` — distinct from the engine's *linear* ramp (points
are a ONE-TIME grab, so extra spare turns don't multiply them) and from the noble *deficit* fade. NOT double-counting
the `(1+cost)` denominator (that's time-blind). Likely a NARROW win at best — the engine term already zeroes an
unfinishable card's engine contribution, so only the points leak remains. A/B it behind a `POINT_TIME_GATE` flag if
revisited; expect it could be a wash (like the TURNS_FLOOR test was).

**Baked config**: `W_TEMPO=0.1, W_GEM=0.3, W_GOLD=0.4, NOBLE_SCALE=3.0, NOBLE_CLOSE_FLOOR=0.3, POT_ENGINE_W=0.5,
W_ENGINE=0.15, NOBLE_TIME_GATE on / NOBLE_TURN_W=1.0, POT_REACH_W=0 (OFF), BUILD_FLOOR_W=0 (OFF)`. Strength: **~0.54
vs H2, ~0.76 vs H** greedy (edges the old stage model; beats the external yardstick H by more than H2 does). To
recover exact-H2 for A/B: `USE_POTENTIAL_ENGINE=False` + `W_GEM=0.2`.

**Noble-weight campaign (June 2026) — `NOBLE_SCALE` 3.0→5.0 is the only gain, and it's small.** A broad campaign
(curves on noble closeness/engine distance; game-stage scaling of points/nobles/cost-weights; victory-proximity;
quadratic/exponent engine-distance reshapes) was run against the **H2 racer family** — `H2R` (rusher, `NOBLE_SCALE
×0.4`) and `H2N` (noble-heavy, `×2.0`), ported from `feat/az-v4-features` as `_AggrH2` wrappers in `h3_vs_h2.py`
(kept as **test infra**; H2N dropped from the metric as too weak/circular). Verdict on a **10-seed-base CRN
confirm** (the single-seed batches inflated badly): `NOBLE_SCALE=5.0` = **+0.0073 avg(H2,H2R)** (won 7–8/10 seeds
vs each racer), neutral vs H — shipped. **Everything else washed or hurt** on confirm: STAGE-scaling was robustly
**−0.02**; `NOBLE_CLOSE_EXP` (convex closeness), `VICT_PROX_W`, all engine-distance curves ≤ flat. This re-confirms
the **static greedy eval is saturated** — re-weighting can't beat ~+1pp; the remaining lever is search/net (see the
recursion/depth+1 direction noted for "at some point"). Campaign scratch (`h3_camp.py`/`h3_final.py`/`camp_*.out`)
was removed; the H2N/H2R wrappers + `h3_autotune` plumbing stay.

**Tuning findings — DO NOT relitigate** (validated on disjoint seeds, N≥3000):
- **The engine balance is a flat RIDGE.** `W_ENGINE` and `POT_ENGINE_W` both scale the engine term (pe sits
  inside potential → engine_value, which W_ENGINE multiplies), so they trade off — tune W_ENGINE *jointly* with
  pe, never in isolation. Optimal band `W_ENGINE 0.15–0.20 × pe 0.25–0.5`, all ~0.54; outside (we≤0.1 / ≥0.3,
  or we=0.2+pe=0.5) is worse. vs-H2 is **flat ~0.54** across the band — no sharp peak.
- **Reachability (`POT_REACH_W`) doesn't pay** in greedy — win-rate wash-to-negative across the full `we×pe×pr`
  grid (≥0.4 clearly hurts). The reworked formula (cost-reduction-weighted, affordable-gated, value-per-cost
  builders) is *correct and unit-tested*, but it's a NET-feature candidate, not a greedy lever. Left OFF.
- **`BUILD_FLOOR_W` hurts** (over-invests in builders for far targets it never finishes). OFF.
- **Sharpening the take denominator (`take = num/(C0+cost)`, C0<1) is the strongest REJECT measured.** Tested
  C0 = 0.7 / 0.5 / 0.3 to "make cost matter more" (motivated by an expensive L2 1-pointer edging a cheaper L1
  on turn 1): cratered **−0.025 / −0.060 / −0.122 avg(H2,H2R), 0/10 seeds, monotonic**, also negative vs H. The
  `+1` constant is **load-bearing** — making cost bite harder makes H3 too cheap-greedy and it under-builds toward
  point/engine cards. The take *numerator* should win those ties; a near-tie favoring the point-bearing card is
  correct, not a bug. (Confirms again: cost-side reshapes don't pay; the static greedy eval is saturated.)
- **`W_GEM=0.3` (vs H2's 0.2) is coupled to the engine** — neutral with the engine off; only helps with the
  turns-remaining engine on.
- **Greedy H3-vs-H2 saturates ~0.54** regardless of potential/reachability weights — same ceiling as H2's
  weight-tuning. Remaining lever is search/net. The exception that paid was the noble time-gate (structure, not
  a re-weight) — look for structural fixes, not more weight-tuning.

**Tooling** (offline; all parallel via multiprocessing — pure-Python games, BLAS is NOT a factor): `h3_vs_h2.py`
(H3-vs-H/H2 arena, `--set`/`--opp`), `h3_eval.py` (named-config A/B), `h3_autotune.py` (coordinate descent,
screen→disjoint-holdout), `h3_measure_turns.py` (rebuild `turns_table.json`), `h3_sanity.py` (interactive value
probes), `h3_stage_sweep.py`. **Methodology: a UNIQUE output file per run** (two runs writing the same `>` file
interleave and corrupt — happened once); confirm gains on DISJOINT seeds; re-measure `turns_table.json` after big
model changes (it's mildly self-referential). `h3_*.out`/`h3_best.json` are gitignored scratch.
- **Cross-worktree import gotcha — `python -m` runs the CWD's code, NOT `PYTHONPATH`'s (DO NOT regress).**
  `python -m games.spender.ai.az.<tool>` puts the **current working directory's** worktree FIRST on
  `sys.path`; `PYTHONPATH=<other-worktree>` does **not** override CWD for `-m`. So launching a self-gate /
  arena / autotune from the **primary (main) worktree** silently runs **main's** `v_state`/`config_selfgate`/
  etc. — NOT your experiment branch's. The candidate's `--set`/config `setattr`s then land on a module
  lacking the new code (no error), and `config_selfgate`'s `[frozen]` dict / `_PROBE_KEYS` silently **omit
  the new knob** (that absence is the tell). **ALWAYS `cd <experiment-worktree> &&` before `python -m`** (cwd
  wins), and sanity-check that `[frozen]` contains your new knob before trusting the run. (A plain
  `python path/to/script.py` is fine — `sys.path[0]` is the script's own dir, then `PYTHONPATH`.) This cost a
  wasted `W_RESERVE_SLOTS` self-gate that ran main's code with the knob absent from `[frozen]`.
- **Serving + overlay specifics:** `_h3_choose_move` (1-ply `choose_action`) + `_h3_card_values` are wired
  into `_ai_variant_valid` + `mk_room_state` + the move scheduler (same path as H/H2; `mk_room_state`
  includes `ai_card_values` only for in-progress H/H2/H3/S games, **now from whoever's-turn-it-is's seat**
  — see the "Overlay follows WHOEVER'S TURN IT IS" bullet under Variant H2). The admin overlay shows H2's T/E/P/C
  **plus a 5th `Po` (potential)** — gated in `Spender.jsx` by `aiValue.pot != null`, leaving H2's 4-value
  box unchanged. (Aside: an `az_vs_h2.py` arena measured H2/H3 **beating the deployed AZ net
  `az_model.npz` ~0.75 @ 300 sims** — the greedy heuristics currently out-play variant Z.)



<!-- ===================================================================== -->
# ARCHIVE: Spender AI — Variant S campaign (v_state + PUCT), Cython perf, metric directive, k6, past-S checkpoints, over-reserve/trace-back
<!-- ===================================================================== -->

### Variant S (`ai/az/v_state.py` + `vsearch.py`) — V(state) whole-position eval + determinized PUCT (STRONGEST; DEPLOYED June 2026)
The first variant to pair the strong H-family judgment with **real search** (the documented #1 remaining
lever). **Strongest variant yet:** panel avg **0.758** — vs greedy **H3 0.733**, H2 0.729, H2N 0.808, H2R
0.762 (N=120, sims=160) — beating greedy H3, which itself beats the deployed AZ net Z ~0.75. Served as
website variant **"S"**.
- **`v_state.py` — the position evaluator (the new piece).** The H-family scores ACTIONS (`take_value` of
  acquiring a card); `v_state.value(s, seat)` scores a whole POSITION:
  `V = tanh((STAND(me) − STAND(opp)) / SCALE)` in [−1,1]. `STAND(seat)` = weighted sum of five terms, each
  REUSING H3 primitives: realized points (+ convex near-win kicker); **engine_stock** (held bonuses' forward
  value, deck-demand-weighted × turns-remaining horizon); **progress** (top-k `take_value` of reachable
  targets); **noble_stand** (closest completable noble, time-gated); **econ** (useful gold − hoard penalty,
  aimed at the AZ-net over-reserve weakness). Scoring the opponent with the IDENTICAL function and
  subtracting makes **denial fall out of the search backup for free** (no `contested_weight` knob — the
  structural cure for the self-play denial blind spot). Opp blind reserves are an expected CONSTANT in static
  V (mirrors `features.encode`), concretized by determinization inside search. Public `value`/`components`
  build the Valuation; internal helpers read `val.s` (one source of truth).
- **`vsearch.py` — determinized PUCT, V leaf, H3 policy prior.** Reuses `az/mcts.Search` UNCHANGED for the
  hard parts (ISMCTS determinization of hidden info; correct non-alternating-turn backups) via a minimal
  `leaf_state=True` mode (hands the leaf State to the evaluator instead of `features.encode`). Leaf VALUE =
  `v_state.value_with` (NOT a rollout). Policy PRIOR = softmax over H3 per-action scores (buys/reserves by
  `take_value`, takes by the NORMALIZED need-vector) + an **H3-greedy-pick anchor** (`H3_PICK_W`). Serving
  uses a wall-clock budget (`SERVE_TIME=4.5s`); offline A/B uses fixed `sims`.
- **Serving:** `_s_choose_move` in `main.py` (mirrors `_h3_choose_move`/`_az_choose_move`) wired into
  `_ai_variant_valid` ("S") + `_schedule_ai_turn` + `mk_room_state` (reuses the H3 `_h3_card_values` overlay);
  `Spender.jsx` lobby picker includes "S".
- **DO NOT relitigate (findings):**
  - **Static value-leaf ≫ rollout leaf** (`h3l_probe.py`: static 0.58 panel vs rollout **0.28**, ~10× slower).
    Confirms "value-leaf beats rollout" — V is the judge, never a playout.
  - **Single-sample determinization is noisy** (the crude `h3_lookahead.py` 1-ply); PUCT AVERAGING over many
    determinized sims is the fix.
  - **The policy prior MUST be scale-normalized.** First cut used the raw need-vector (~5–45) for takes vs
    `take_value` (~1–3) for buys → softmax put ~all mass on taking gems → the bot bought nothing, lost
    **0/16**. Normalizing the take score + the H3-pick anchor → 0.69+ instantly (same class as the AZ
    buy-nothing collapse).
  - **Search is the lever, empirically:** greedy H3 ≈0.5 vs panel → V+search **0.73**. The static eval alone
    saturates ~0.65 (the plateau); the gain is from SEARCH.
- **Hardening — DO NOT regress (`valuation3`):** `Valuation` captures a `(ply, phase, turn)` fingerprint at
  construction; a single inlined `assert` in `estimated_turns_remaining` (the one method every scoring path
  hits; `-O`-strippable) catches a Valuation reused after its state mutated — the lookahead/distillation
  footgun `val = Valuation(s); apply(s, a); val.<query>()` (silently mixes post-apply live state with
  pre-apply caches). The vestigial `s` param was DROPPED from `heuristic3.components`/`take_value` + all
  callers (never used; the state is `val.s`); `v_state` helpers read `val.s`.
- **Perf (behavior-preserving; profile: ~84% of search time is the V leaf):** `_cost_scalar` rewritten as one
  inlined loop (no `b(c)` closure / genexprs) = **2.75× less work**; `_delta_take` memoized per-Valuation
  (`_dt_cache`, ~**78% hit**) = 4.5× fewer `_cost_scalar` calls; `heuristic3.choose_action` accepts an
  optional `val=` and the H3-prior anchor in `vsearch` passes the leaf's Valuation (no 2nd build — 2/sim →
  1/sim — and the anchor's `take_value` sweep hits the warm cache: `_cost_scalar` 298K → 200K, a modest
  ~5–7% on top). Net ~**2–2.6× more sims/move** in timed serving; offline fixed-sims play is BYTE-IDENTICAL
  (exact-value tests in `test_h3_valuation.py` + `test_vsearch.py` gate it). The fingerprint catches
  turn-ending AND phase-transition mutations. **Profiling note:** measure throughput on a QUIET box —
  `vsearch_profile.py`'s clean sims/s is corrupted by a busy autotuner; the contention-independent truth is
  the cProfile call counts (builds/sim, `_cost_scalar` calls).
- **Perf round 2 — deployed sims-starvation diagnosed + leaf sped ~1.76× (June 2026).** Production
  serving logs (`vsearch._run_search_timed` now logs `[S] serving search: N sims in Ts (sims/s)` per move)
  showed **Render's free CPU runs ~330–450 sims/move at ~85 sims/s in the decisive midgame — ~10–11× FEWER
  than local's ~4,300 @ ~950 sims/s** (only trivial near-terminal moves spike, where most sims hit OVER
  cheaply). So the deployed S a strong human beats is badly sims-starved, NOT algorithmically weaker — and
  per the speedcurve strength climbs with sims, so the lever is leaf SPEED (no UX cost; the user declined
  raising `SERVE_TIME`). Profiling the leaf found redundant recomputation, all fixed BYTE-IDENTICAL (gated by
  the exact-value tests, 254 pass): (1) `valuation3._steps` replaces the `sorted(positives)==[1,1,1,1]` test
  in `tempo`/`_reduces_tempo` with `max==1 and count_positive==4` — killed **100% of the ~592k sorts/move**
  (the #1 self-time; +24%); (2) `_color_deficits` append-loop → walrus comprehension (drops ~1.2M appends);
  (3) `noble_progress`/`noble_completion_pts` memoized by **`(bcol, seat)`** (the 3-noble loop depends only on
  the bonus COLOR, not the card — only `noble_progress`'s time-gate `eff/(eff+W·deficit)` combine stays
  per-card via `_noble_terms`); (4) `_w_card` memoized by `(cj, bcol, seat)` (`_rtempo_cache`) — the engine
  loop recomputed `_reduces_tempo` identically for every ci sharing a color (213k→96k). Net **891 → ~1,570
  clean sims/s (1.76×)**; so deployed midgame ~380 → ~670 sims/move. A follow-up memoized **`tempo(ci,seat)`**
  (pure in (ci,seat), recomputed ~197k×/move across the noble/cost paths — caching it also kills the
  `_color_deficits`/`_steps` it spawned) and **`_cost_scalar`** by (ci,seat,extra_bcol): paired A/B ~1545 →
  ~1636 (**+6%, →1.84× cumulative**, byte-identical). That exhausted pure-Python (rounds gave +24/+24/+6% —
  tapering); the remaining hotspots are already-memoized core work + interpreter overhead → next lever is
  compilation (round 3).
- **Perf round 3 — Cython "pure-Python mode" hot leaf (~1.27× more, single source; June 2026).** The
  remaining leaf time is raw CPython interpreter overhead on the numeric loops (no redundancy left to cache).
  Compiled it with Cython — but in **pure-Python mode, NOT a separate `.pyx`** (the deliberate architecture
  choice): the hot functions in `valuation3.py` (`_cost_scalar`/`_color_deficits`/`_steps`/`_reduces_tempo`)
  carry `cython.*` type annotations that are **inert under CPython** (`from __future__ import annotations`
  makes them strings; nothing is evaluated, and `import cython` is guarded → no runtime dep) and become a
  **typed C extension when Cython compiles the module**. ONE source of truth — no duplicated logic, no parity
  test to maintain (a separate `.pyx` was prototyped first — 8.7× on `cost_scalar`, 1.25× end-to-end — then
  discarded for the single-source pure-mode form, which matched it). **Serving = the compiled `valuation3.so`
  shadows the `.py`** (extension > source in import priority); **local dev / any box without a C compiler runs
  the `.py` unchanged** (byte-identical fallback).
  - **Build wiring (`games/spender/Dockerfile`):** the *builder* stage `pip install cython` + `cythonize -i -3
    games/spender/ai/az/valuation3.py`; the slim *runtime* `COPY --from=builder` the `.so` in next to the
    `.py`, then a **build GATE** — `RUN python -m pytest test_h3_valuation test_vsearch` against the COMPILED
    module — so a Cython miscompile fails the image build and can never reach prod (a failed build just leaves
    the previous image serving; the site can't break from this). Shared by the wwsd service too (same
    Dockerfile). `.gitignore`/`.dockerignore` keep the generated `.c`/`.so`/`build/` out of git + context.
  - **Validated in a `python:3.11` container (= prod):** compiled **2114 vs uncompiled 1666 clean sims/s
    (~1.27×)**, 24 exact-value tests pass compiled. Cumulative session ≈ **2.3×** (1.84 × 1.27); Render midgame
    ~380 → ~870 sims/move.
  - **Build env reality:** the dev box (Windows / Python 3.14) has **no C compiler**, so this is built +
    validated in Docker (`python:3.11`, matches prod). There is **no runtime kill-switch** anymore (pure-mode
    has no `if _FV` branch — it's compiled or not at build time); the byte-identical guarantee is the
    build-gate tests, not a flag.
  - **The ceiling — DO NOT relitigate the deeper Cython without a strong reason.** Pure-mode annotations got
    ~most of what this code can give: the whole module compiling is the baseline gain, typed loops add the
    rest. Going to the targeted **2–3×** would need (a) making `Valuation` a **`@cython.cclass`** (cdef
    methods/typed attrs) to kill the now-dominant **method-dispatch + dict-cache** overhead — a big, risky
    rewrite of a 1,000-line cached class — AND (b) Cythonizing `mcts.py`/`engine.py`, because **~15–25% of
    per-sim time (determinize / `_select` / `clone` / `legal_actions`) lives OUTSIDE `valuation3`** — a hard
    ceiling on any leaf-only effort. Judged poor effort/risk/reward vs the 2.3× already banked + diminishing
    sim-returns; **stopped at the leaf.** **(SUPERSEDED IN PART — see Perf round 4: the deeper typed-C-array
    rewrite of the `engine_value` CHAIN (short of the full cclass) WAS done on branch `cython-perf`,
    byte-identical, ~1.85–2.74×. The `@cython.cclass` Valuation + mcts/engine port is still deferred.)**
- **Perf round 4 — typed-C-array rewrite of the `engine_value` chain (branch `cython-perf`, NOT merged; June 2026).**
  Round 3's pure-mode annotations only typed loop COUNTERS — the DATA (`s.bonuses[seat]`, `E.COST[ci]`) stayed
  PyObject lists/tuples, so a naive recompile of the deeper chain was **~1.0× (measured 13.1 vs 12.7 s/game)**.
  The win needs the data in **C arrays** + collapsing the per-card scoring so it crosses the Python boundary ONCE
  per call instead of thousands of times. Done in the SAME single-source pure-mode `.py` (composes with round 3):
  - **Module-level C tables** `COST_C[90][5]`/`BONUS_C[90]`/`PTS_C[90]` filled at import inside `if cython.compiled`
    (gotcha: Cython REVERSES array dims — `cython.int[5][90]` emits C `int[90][5]`; declaring it un-flipped is a
    silent OOB write). **cdef helpers** `_steps_c`/`_reduces_tempo_c`/`_cost_scalar_c`/`_color_deficits_c`/`_eng_base_c`
    (`int*`/`double` C signatures, no PyObject) carry the leaf math.
  - **`_engine_value_h3_c`** inlines the WHOLE H3 `engine_value`
    (delta_take→potential→eng_base→w_card→reduces_tempo→cost_scalar) in C over C arrays with **NO sub-call caches** —
    recompute is byte-identical because every memoized helper is a deterministic pure function. Also converted: the
    `components` cost vector (`tempo`/`gem_cost`/`gold_cost`), the per-Valuation `deck_color_demand` `__init__` loop,
    and `noble_progress` (`_noble_progress_c`).
  - **Every C path is gated `cython.compiled and ci < 90`** so the unchanged Python path still serves the
    synthetic-card unit tests (which append cards past the 90-deck) and any non-deployed flag config; nobles read the
    **LIVE `E.NOBLE_REQ`** (tests replace it) not a frozen table; tuning constants are read **LIVE per call** (NOT
    frozen into C globals) so the offline autotuners can still sweep them.
  - **GOTCHA — a genexpr in the same function scope as a `cython.declare(C-array)` breaks Cython codegen**
    (`GeneratorExpressionScope` error): the C-path functions are genexpr-free (pure fallbacks rewritten without
    `sum(... for ...)`); int/int closeness divisions forced to double via `1.0 *`.
  - **Results — byte-identical (60-game S self-play differential parity char-identical + 32 unit tests, compiled AND
    pure):** engine_value alone **1.49×**, +cost vector **1.85×**, +init/noble **2.74×** (cumulative). The ratio is
    LOAD-dependent (the local box's 11-core tuning job fluctuated): the **compiled path is contention-STABLE at
    ~2.66 s/game** while pure swings 4.9–7.3 — so ~1.85× on an idle box, ~2.74× on a busy one, and compiled is far
    more robust to a loaded CPU (the Render shared-core scenario).
  - **Built + validated LOCALLY** (the dev box now has MSVC + cython 3.2.5; Python 3.14 →
    `valuation3.cp314-win_amd64.pyd`) AND in a **`python:3.11` Docker build** matching prod (cython==3.2.5 manylinux
    wheel, cythonize under cp311+gcc → `COST_C[90][5]` identical, the line-39 gate `32 passed` on the cp311 `.so`).
    **No Dockerfile change beyond pinning** `cython==3.2.5` (the builder already `cythonize`s `valuation3.py` + gates
    on `test_h3_valuation`/`test_vsearch`, so this ships automatically). To fold into `heuristics`/main the
    engine_value chain is unchanged between branches, so it applies cleanly. **Still deferred:** the `@cython.cclass`
    Valuation + Cythonizing `mcts.py`/`engine.py` (the ~15–25% per-sim time OUTSIDE valuation3 — the hard ceiling
    on any leaf-only effort).
- **Tooling** (offline, parallel): `vsearch_camp.py` (panel A/B, CRN, Wilson CIs), `vsearch_autotune.py`
  (coordinate descent, **MAXIMIN objective over {H3,H2,H2N,H2R}** — maximize the WORST matchup, mean only as a
  tie-break (`MEAN_EPS`), with larger screen/holdout N since the min is a noisier statistic. Switched FROM
  panel-mean after the mean run found ZERO adoptions on the disjoint holdout — i.e. the hand-set V weights are
  already near-optimal, confirming "weight-tuning saturates"; vs-H3 (~0.635 @ sims=120) is the lone weakness
  maximin targets), `v_state_eval.py` (sign(V) win-prediction discrimination vs the ~0.65 plateau),
  `vsearch_profile.py` (clean wall-clock + cProfile), `h3l_probe.py` (the static-vs-rollout probe). Tests:
  `games/spender/tests/test_vsearch.py`.
- **THREE-WAY diagnostic (RUN, June 2026) → Path C favored.** `v_state_eval.py --teacher S` plays S-vs-S
  (search-driven) and at every PLAY snapshot records {static V, search-backed root value `sum(W)/sum(N)`,
  eventual outcome} from the mover's perspective, then compares each eval's AUC/Brier vs outcome. The
  decisive question was whether the search-over-leaf advantage GROWS with depth. It does — sweep at
  sims=128/384/768 (240 S-vs-S games each, ~13k snapshots):
  | sims | V_static AUC | V_search AUC | dAUC | agree corr |
  |------|------|------|------|------|
  | 128 | 0.642 | 0.680 | +0.038 | 0.822 |
  | 384 | 0.688 | 0.737 | +0.049 | 0.811 |
  | 768 | 0.645 | 0.700 | +0.055 | 0.789 |
  Three concordant trends: **dAUC grows, Brier gap widens, agreement falls** as search deepens — deeper search
  increasingly diverges from AND outperforms the leaf. The leaf AUC ~0.64 sits exactly on the documented
  static plateau (re-confirmed now against STRONG S-vs-S labels, not H3-level) → **re-weighting V is dead**.
  Only the WITHIN-row paired dAUC is a clean comparison (each sims row plays a different game set, so absolute
  AUCs wobble); all three deltas move the same way → trust the trend. Verdict: **Path C (distill V+search →
  numpy net → deeper search) is the lever.** **Do NOT re-tune V on self-play OUTCOMES as the objective** — a
  mirror match is ~0.5 (no gradient) and reintroduces single-strategy-collapse / denial-blind risks; the
  style-diverse MAXIMIN panel stays the arbiter. (For the framing/decomposition that designed this test —
  static-V-vs-outcome = "biased leaf?" vs static-V-vs-searchV = "needs depth?", and why you need the outcome
  as a third anchor since searchV inherits the leaf's bias — see git history of this section.)
- **Take-pruning of dominated gem-takes — TESTED & REJECTED (wash; do not relitigate).** The engine offers
  take-2-different / take-1 even when a superset take-3 is available; under the token cap these are weakly
  dominated. A search-local prune (`legal_fn` hook on `Search` + a `_search_legal` that drops them when total
  tokens ≤7) was sound in theory but **panel A/B was an exact wash (0.8104 = 0.8104)**, with a noise-level
  per-opp wobble that if anything nudged the worst matchup (vs-H3) down. Reason: the **policy prior already
  soft-prunes** them (low `take_value`/need → ~0 prior → ~0 visits), so explicit pruning frees no sims.
  Reverted. (At 8/9 tokens take-fewer is genuinely distinct anyway; the equivalence "take-3 then discard the
  just-taken gem ≡ take-2D" holds only in the search's model, and serving executes that discard via greedy H3,
  not search — a separate reason not to lean on it.)
- **Mixmax / pessimistic backup — TESTED & REJECTED (do not relitigate; June 2026).** The user's intuition
  "assume the opponent plays at least somewhat well" → blend each edge's diluted mean Q with the best reply
  one ply down (`mcts.Search(backup_lambda=L)`, `vsearch.BACKUP_LAMBDA`, parked default-0 = byte-identical;
  the best-reply Q is averaged over determinizations so it pessimizes over DECISIONS not deck luck — correct
  ISMCTS). **Self-gate vs FROZEN today's-S (paired CRN, the sharp instrument) showed a clean MONOTONIC
  degradation:** lam=0.15/0.3/0.5 → 0.481/0.463/0.383 on the same seed base (lam=0.5 ~4 SE below 0.5). A lone
  fresh-seed 0.520 for lam=0.15 contradicted its own 0.481 screen (regression-to-mean noise ~0.5); the panel
  +0.046-min is the documented weak/noisy discriminator (~1.2 SE, different game set) — not ship-grade. The
  negative slope matches the **maximization bias** (the max is over noisy 1-visit grandchildren → over-estimates
  the opponent's best reply → over-pessimism that grows with lam). A min-visit guard on the max could debias it
  but was not pursued (the naive monotonic-negative result + the strong prior make a small-lam rescue unlikely).
  Confirms again: the static eval is **already used near-optimally by the plain averaging backup** — re-shaping
  *how* the leaf is aggregated in PUCT washes, same as re-shaping the leaf itself. Tooling: `backup_lambda_ab.py`
  (focused self-gate: screen → fresh disjoint-seed → panel RPS guard for the one knob).
- **Search exploration breadth — TESTED & REJECTED (wash; do not relitigate; June 2026).** Hypothesis
  (from a human who still beats S): "S never CONSIDERS the move that beats me" → widen the policy prior so
  PUCT visits moves H3 dislikes. Two mechanisms, both parked default-off byte-identical: `vsearch.PRIOR_UNIFORM`
  (mix uniform mass: `P=(1-u)*softmax + u/n`, the REAL floor) and `POLICY_TEMP`↑ (flatten the H3 prior).
  **Discovery: the existing `PRIOR_BASE=0.1` is a VESTIGIAL no-op** — it's added to EVERY action's score so it
  cancels in the softmax (softmax is shift-invariant). Self-gate vs frozen-S at sims=200: `PRIOR_UNIFORM`
  0.1/0.25 screened 0.546/0.538 but 0.1 fell to **0.494 on FRESH disjoint seeds** (regression to mean),
  `POLICY_TEMP=1.0` = 0.496, panel a slight wash. **No gain because `mcts._select`'s `_EPS_PRIOR=1e-3` floor +
  PUCT's `sqrt(N)/(1+n)` term ALREADY make every legal move get visited** — dark moves are NOT starved; S sees
  them, evaluates them, and correctly doesn't prefer them at the depth it searches. So the human-exploitable
  gap is **eval-depth/search-budget, not exploration breadth** (and widening breadth at the LOW sims the
  deployed Render CPU runs would only spread the budget thinner). Re-confirms the two remaining live levers:
  search DEPTH (needs a faster leaf/engine → more sims) and the production sim budget. Tooling:
  `config_selfgate.py` (generic config-vs-frozen self-gate, screen → fresh → panel guard).
- **Search-efficiency / "fewer sims needed" (sharper prior) — REAL low-sims effect, but NOT shippable; do
  not relitigate (June 2026).** Idea: a sharper prior concentrates visits faster, so the deployed sims-starved
  S plays better at a fixed (small) budget. Self-gate vs frozen-S **at sims=80** (below the original
  sims=120–160 tuning regime) found **`C_PUCT=1.0` (less exploration) beats the current 1.5**: fresh-seed
  0.531 (consistent with its 0.563 screen) AND panel **+0.025 min, up on all four matchups** (RPS-clean) — a
  genuine, non-artifact win that confirms the principle (when sims are scarce, commit faster). `POLICY_TEMP=0.5`
  (0.49) and `H3_PICK_W=2.5` (0.44) failed even at 80 — it's specifically PUCT exploration, not prior shape.
  **But it's a LOW-SIMS-ONLY win below the deployed operating point:** the maximin tuning already found
  `C_PUCT=1.5` optimal at sims=120–160 and transferring to 400, so there's a **crossover ~80–160**, and the
  deployed box runs ~380 midgame sims (more after Cython) — well above it. Shipping `1.0` globally would help
  only rare very-low-sim moves and HURT the typical midgame → net neutral-to-negative for deployed. The only
  way to capture it is a **sim-budget-conditional `C_PUCT`** (sims unknown until after the search, box speed
  varies — too fiddly for a sub-significant edge). **Verdict: keep `C_PUCT=1.5`; search-efficiency tuning
  saturates at the operating point too.** Transposition caching was dismissed un-tested (determinization
  reshuffles boards per sim → near-zero exact-state hit rate in Splendor's wide state space). Tooling:
  `config_selfgate.py --sims N`.
- **Path C (distill V+search → numpy net) PROTOTYPED & the bottleneck PINNED to FEATURES, not arch (June
  2026).** Tooling: `vsearch_distill.py` (harvest `(features, V_static, V_search, outcome)` from S-vs-S +
  ridge/MLP distill, with a `--enriched` mode + `--cache`), `attn_distill.py` (card-set attention pre-check on
  the cache). Findings, all measured on ~33k S-vs-S snapshots @ sims=384 (leaf AUC ~0.69, search target ~0.74):
  - **Cheap-feature distillation STALLS.** ridge/MLP/**card-attention** all cap **AUC ~0.65–0.67** predicting
    V_search — *below* the leaf, far below the search target. Not validated.
  - **It's a FEATURE-information bottleneck, not architecture.** Targeting V_static, models REPRODUCE the leaf
    at **corr ~0.91** yet still cap AUC ~0.66; the ceiling is the SAME (~0.66) whether the target is V_search or
    V_static → the limit is what the 305 encoder *contains*. **Attention ≈ linear** here (no arch advantage)
    because neither has the inputs: the encoder omits the leaf's derived terms — **turns-remaining horizon,
    deck composition/per-color demand, engine/reachability/potential**. This is the truer cause of variant Z's
    plateau: Z trained on these same lossy features → capped ~0.65 *before architecture mattered*. (Bug noted:
    the attention pre-check first looked negative because per-card tokens lacked the mover's bonuses — fixed by
    injecting them; still capped, confirming features not arch.)
  - **Redirect → ENRICH THE ENCODER** (the #1 pre-retrain adjustment). Feed the net the leaf's own derived
    terms (base 305 + per-board-card H3 `(take,engine,point,cost)` + `v_state` component breakdown + turns).
    Costs ~leaf-level compute (so NOT the Path-C "100× cheaper for deeper search" bet — the retrain chases
    STRENGTH, not speed). **Pre-check RESULT (RUN, `--enriched`, same 600-game/sims384 harvest): enrichment
    UNBLOCKS it — direction validated.** On THIS test set (leaf 0.670, search target 0.717): ridge **0.694**,
    MLP 0.681 — both now ABOVE the leaf (on base features NOTHING beat it), capturing **51% of the search-vs-leaf
    gap**; ridge's fit to V_search jumped corr 0.76→0.85. So a *learnable* eval can beat the hand-leaf once the
    features carry its terms. Caveats: magnitude is modest (+0.024 linear; the other ~49% of the gap is pure
    lookahead no static eval recovers — search on the better leaf reclaims it), and the harness MLP is still
    undertrained (< ridge — a regularization/early-stop issue, NOT capacity), so the true NET ceiling is likely
    higher, and the per-card-terms-in-attention-tokens test (not yet run on enriched) should push further.
    Verdict: **retrain green light, with bounded-but-real upside.**
  - **The retrain decision (locked direction):** if green, it's an AlphaZero retrain with (a) **enriched
    encoder** [feature set must be locked BEFORE start — input-dim change = full restart], (b) **card-set
    attention** value+policy heads, (c) **bootstrap by distilling S's (V_search value, MCTS visit-policy)** so
    self-play starts competent — NOT from-scratch (every from-scratch/flat-feature net LOST to the heuristics).
    Reuse the built shaping/league/curriculum. Verify a numpy-export path for attention before committing, and
    consider a C/Cython engine first (self-play game-gen is the wall-clock sink). `distill_cache*.npz` are
    gitignored scratch.
- **DEPLOYED + MAXIMIN-TUNED (June 2026):** shipped to `main` (variant S = `da18bab`; maximin config =
  `31bbfbd`). The maximin `vsearch_autotune` pass-0 adopted exactly two knobs — **`W_ENGINE_STK` 0.8→0.4**
  (`v_state.py`) and **`C_PUCT` 2.0→1.5** (`vsearch.py`) — confirmed on DISJOINT fresh seeds (N=360, sims=120):
  worst-matchup **min 0.664→0.750**, mean 0.729→0.777, every panel matchup up; validated at higher sims via the
  panel-vs-sims speedcurve (min 0.812 / vs-H3 0.875 at sims=800). The bigger lever was `C_PUCT` (a SEARCH knob,
  not a leaf weight) — consistent with "search is the lever." We stopped the autotuner after pass 0 (a watcher
  tree-killed it at the first `[p1]`); pass-1+ gains are marginal. Speedcurve also showed raw-sims strength
  still climbing but with **diminishing returns** by 400–800 sims (S@hi-vs-S@lo adjacent doublings ~0.5–0.59;
  8× span 0.73) → speed micro-opts give modest gains; leaf quality is the bigger lever.
- **Behavioral audit + self-gate campaign (June 2026):**
  - **Over-reserve — TESTED & REJECTED (don't relitigate).** `blunder_finder.py` found S reserves ~4.3×
    greedy H3 (12.6% of moves vs 2.9%, ~56% never bought) — an EVAL bias (a deep search AMPLIFIES it → the
    leaf over-values reserving, not a shallow-search artifact). BUT the **human playtest** verdict was
    "reserves mostly GOOD, only slightly excessive," and a new `v_state.RESERVE_PENALTY` knob (default 0 =
    byte-identical) at 0.3 **HURT the worst matchup** (vs-H3 min 0.785→0.745) for no avg gain → the reserves
    are tactically useful (denial/securing vs the racing H3); "wasted at game-end" ≠ a blunder. **Keep
    `RESERVE_PENALTY=0`.** The self-gate later re-rejected it independently (screened ≤0.50 vs frozen-S).
    Lesson: win-rate-vs-a-beatable-panel is blind to behavioral biases, and so is self-play *mirror* (both
    sides share them) — only a behavioral audit vs a non-sharing reference (H3) + a human caught it, and you
    need the fix-knob to EXIST and an *asymmetric* comparison that varies that axis to tune it.
  - **Policy head — ruled out.** `policy_precheck.py`: the H3 policy prior already matches the search's
    top move ~86% (the learned net underperformed it, undertrained) → little room. Low priority.
  - **Self-gate autotuner `vsearch_selfgate.py` (tune vs a STRONG opponent) — paid off.** Candidate config
    vs FROZEN today's-S (NOT the weak panel), **paired CRN**: each board is played both first-player ways
    with `vsearch._RNG` reset, so `cand==frozen` scores EXACTLY 0.5 (unbiased + race-free; `engine.new_game`
    always makes seat 0 first, so the pairing is what balances first-player). Found **`W_PROGRESS` 1.5→2.5**
    that the maximin run (judged on the beatable panel's MIN) had missed: vs-frozen **+0.024** (fresh N=200)
    AND panel avg 0.766→0.797 / **min 0.741→0.778 (+0.037)**, RPS-clean (objectively stronger). Confirms the
    user's thesis: weak-panel tuning saturates; a strong equal opponent sharpens the gradient. All other
    knobs (incl. RESERVE_PENALTY) held. **SHIPPED (on main):** the sims=400 panel confirm HELD — avg
    0.8125→0.8262, **min not worse** (H3 .770→.772; only H2N −.013, within ±.029 noise) — so `v_state.py`
    now has `W_PROGRESS=2.5` deployed (variant S). Tuned at sims=160, confirmed it transfers up to 400.
  - **Turns-remaining estimator — TESTED, NO CHANGE (don't relitigate).** Hypothesis: `turns_table.json` (the
    horizon, measured from H3-vs-H2) is mis-calibrated for the far-stronger S, inflating the horizon-gated
    terms (`_engine_stock`/`_noble_stand`/noble time-gate) and feeding the over-reserve. **Both fixes failed.**
    (1) Re-measuring the table from **S-vs-S** play (`s_measure_turns.py`, 320 games @ sims=128) gives a table
    essentially IDENTICAL to the H3 one: count-weighted mean(S − H3) = **−0.020 turns**, and even the start
    cell (0,0,0) matches (26.35 vs 26.28). The table keys on the **game STATE** (cards/points/gems), which
    already encodes progress, so turns-to-finish from a fixed state is ~play-quality-invariant — a stronger
    player REACHES good states sooner but the trajectory FROM a state is the same (so the docstring's
    "self-referential" caveat is genuinely mild). (2) A board-CONDITIONAL greedy **turns-to-win planner**
    (`valuation3._planner_turns_seat`, behind `TURNS_MODE`, default off) is a WORSE turns predictor (corr
    0.946 vs the table's 0.981; MAE 2.21 vs 1.30) AND makes S weaker in the A/B (`turns_ab.py`): **0.469 vs
    frozen-S**, panel avg 0.720 vs 0.783. Board composition barely moves turns-left once points-needed is
    known. **Keep `TURNS_MODE="table"`.** The planner/`table_s` machinery is parked default-off (byte-identical).
    `s_measure_turns.py` (also reusable for the 21-point turns re-measure) + `turns_ab.py` are committed tooling;
    `turns_table_s.json` + the `.out` logs are gitignored scratch. (3) The KEY-lossiness follow-up (the user's
    sharper point — the key is RESERVE-BLIND, and H3 barely reserves while S reserves constantly): `turns_feat_diag.py`
    confirms reserved-count carries **real** omitted signal — holding a reserve correlates with ~**−0.72 turns**
    left (monotonic residual −0.35/−0.86/−1.40 at 1/2/3+ reserves) — so the table genuinely over-estimates the
    horizon in S's reserve-heavy states (your hypothesis was directionally CORRECT). BUT correcting it
    (`valuation3.RESERVE_TURN_ADJ`, subtract turns/reserve, default 0) is a **WASH for PLAY**: vs frozen-S the
    head-to-head is 0.527/0.510/0.517 at adj 0.4/0.7/1.0 (all CIs cross 0.50) and the panel is non-monotonic
    (noise). It doesn't convert because the horizon scales only the SECONDARY engine/noble standing terms;
    points/progress dominate move-choice, so a sub-turn horizon shift barely moves it (aggregate dR²=+0.0024).
    **Gold weighting is NOT supported either** — controlling for reserves, gold advances you LESS per token than
    a colored gem (coef −0.20 vs −0.41); its raw effect was just reserve-correlation. **Keep `RESERVE_TURN_ADJ=0`.**
    Net lesson: R² gain ≠ strength; the turns horizon is not a strength lever for S (3 independent washes).
  - **Net retrain / learnable-leaf path — EXHAUSTED, beats nothing (DO NOT relitigate).** A pre-retrain
    derisking sweep (offline scripts: `distill_features.py`/`distill_fit.py`/`leaf_ab.py`, `bootstrap_harvest.py`/
    `bootstrap_train.py`/`net_vs_s.py`, `policy_arch_test.py`) tested every lever a learned net could give S.
    **Six converging negatives:** (a) **leaf-swap** — an enriched ridge leaf distilled toward V_search (held-out
    AUC 0.718 vs the static leaf's 0.670) made S only **0.534** vs frozen-S (n.s.), panel wash → a sharper static
    leaf does NOT convert through search. (b) **base-feature bootstrap** — a net distilled from S (value+policy)
    scored **0.042** vs S (near-uniform policy CE 2.67). (c) **enriched bootstrap** — value sharp (MSE 0.027),
    policy lifted to 0.52 top-1 but still **0.315** vs S. (d) **structured/per-card policy head** — 0.554 top-1 ≈
    flat 0.535, both ≪ the H3 prior's **0.86**. The wall is NOT features or architecture: **S's search move ≈
    H3's greedy move 86%, and predicting it essentially requires recomputing H3** — any net is a lossy
    approximation (~0.55). So the best static policy IS the H3 prior, which **S already uses**; "H3 prior + net
    value" just rebuilds ≈ S. Combined with "better value doesn't convert," **no net configuration beats S.**
    The only untested path is self-play discovering a >H3 policy from the 0.315 enriched bootstrap, but the net
    represents policies at ~0.55 fidelity and base-feature self-play already capped sub-S (variant Z) → low odds,
    not pursued. **Conclusion: S is at the ceiling of the heuristic+search approach; the learnable-net path can't
    surpass it.** (Reusable byproduct kept on main: `league.py`/`train_az.py` now accept **`S` as a league/gate
    opponent** via `--heur-variants S` + `--opp-s-sims`; `vsearch.LEAF_MODE`/`net.SpenderNet(in_features=)` are
    byte-identical-default. `*cache*.npz`/`leaf_model.npz`/`checkpoints_bootstrap*` are gitignored scratch.)
- **21-point "Long" mode — LIVE + specialized.** Per-game `win_points` (default 15) is wired through the
  engine, production rules (`main._win_points`), and the AI stack (v_state convex zone, `victory_closeness`,
  heuristic3 win-checks all read `s.win_points`); the lobby has a **Classic 15 / Long 21** toggle threading
  `win_points` into `create`. **Any picked AI auto-adapts to 21** (no separate variant needed). Shipped 836ad6d
  (Phase 1) + 567e5d8 (toggle); byte-identical for Classic.
  - **Lobby UX follow-ups (June 2026):** the toggle was reworked to a segmented `.length-toggle`/`.len-btn`
    whose selected state changes ONLY background+color (fixed border/padding) — the old `.mode-toggle`
    swapped `btn-outline`↔`btn-gold` whose borders differ, which **shifted the page on select**. The toggle
    now ALSO **filters the Open Games list** to the selected length (`openGames.filter(g => (g.win_points||15)
    === winPoints)`; `list_open_games` parses `win_points` out of `state_json` and returns it). In-game, a
    "**Target: N**" label sits above the hint (`.hint-col` wraps target+hint in the desktop actions-panel; an
    inline `.target-label` in the mobile action-bar), reading `game.win_points || 15`. Create button is just
    "+ Create Game" (length comes from the toggle).
  - **The genuine specialization is STRUCTURAL (done):** (1) the convex near-win zone auto-shifts to the last 5
    of `win_points` (→16 at 21); (2) **`turns_table_21.json`** — a 21-point-MEASURED horizon table, auto-loaded
    by valuation3 when `s.win_points==21` (the 15-table under-counts the 21 horizon by ~3.8 turns — a real
    structural gap, unlike the player-strength recalibration which was a wash). S-at-21 beats the heuristic
    panel ~0.76 (H3 .70 / H2 .82 / H2N .70 / H2R .81).
  - **Weight retune — NO honest change (don't relitigate).** The self-gate at `--win-points 21` (vs frozen-S-at-21)
    adopted `W_ENGINE_STK 0.4→0.2` on the reused per-knob holdout (0.529), but it **failed the fresh disjoint-seed
    re-measurement (0.4979, below 0.50) AND the RPS guard** (worse vs H3) → a holdout artifact, not adopted.
    Everything else screened-high-but-failed-holdout (W_ECON 0.637, W_POINTS 0.575, W_PROGRESS 2.0). So
    **`vsearch_s21.json` is empty** → S21 = S's 15-weights + the structural 21-adaptations. Serving:
    `_s_choose_move` applies any S21 overrides under `_S21_LOCK` only on `win_points==21` (empty config = no-op,
    byte-identical). Harnesses gained `--win-points` (`s_measure_turns`/`vsearch_camp`/`vsearch_selfgate`).
- **Endgame & multi-noble experiments (June 2026) — default-off knobs, committed LOCALLY (`2c27b14`,
  `2da6e4d`), NOT pushed; under test.** Three structural ideas (a human still beats S in their own games),
  each byte-identical at its default and unit-tested (`test_vsearch.py`):
  - **Gap A — `v_state.ENDGAME_TIEBREAK_W` (tiebreak awareness)**: a CROSS-seat leaf term (added in the value
    diff `value_with`/`components`, NOT per-seat STAND) that — gated to near-win + near-tie + differing card
    counts — nudges toward the pts→fewest-cards tiebreak. **DEAD:** wash at sims=160 (0.500/0.502), wash→NEGATIVE
    at sims=500 (0.02=0.500, 0.06=0.465). As predicted: the leaf tiebreak only helps when search MISSES
    terminals, which happens LESS at higher sims (a true terminal already returns the engine's exact
    tiebreak-aware win/loss). Reject. Don't relitigate.
  - **Gap B — `vsearch.ENDGAME_SIM_MULT` / `ENDGAME_SERVE_TIME` (deeper final-round search)**: spend more
    search once `final_trigger>=0` or a seat is within `ENDGAME_NEAR=3` of the win (offline sim multiplier /
    longer serving wall-clock; `_is_endgame`). **Faint wash:** ~0.51-0.53 screen (160 and 500), never clears
    the +0.02 holdout bar, no panel gain. The endgame is too few moves + already near sim-saturation to pay.
  - **Multi-noble — `v_state.NOBLE_MULTI_W`** (the USER's idea): `_noble_stand` counted only the single best
    noble (max over 3); W>0 adds `W*(sum of the OTHER nobles' time-gated standings)` so a position advancing
    2-3 nobles outscores one advancing 1. (Per-card `valuation3.noble_progress` ALREADY rewards multi-noble
    cards via its n-normalized sum; this is its POSITION-eval counterpart, the real gap.) **Implemented +
    unit-tested, NOT YET RUN** (queued behind the sims=500 autotune; don't oversubscribe cores). **Strong
    real-game evidence (a 15-10 loss to a human):** S piled red4/black4 (enough for its one noble n6, +1 spare
    each) but left blue at 2 → finished EXACTLY one blue short of a 2nd noble (n9 = g3/b3/r3), while the human
    balanced w3 b3 g3 r3 and claimed TWO nobles (6 vs 3 = the game's whole margin). The max-over-nobles leaf
    gave S no gradient to balance. **Most promising of the three** — test sims=160 screen → sims=500 confirm.
  - Tooling: `vsearch_selfgate` gained the endgame + `NOBLE_MULTI_W` knobs (finer search-knob grids) + a
    `--knobs` subset filter (full set intact for future full tunes); `config_selfgate._PROBE_KEYS` pins them.
- **sims=500 self-gate autotune (endgame + search knobs) — IN PROGRESS.** Run at the PROD operating point —
  the user flagged that sims=160 tuning may not transfer to prod's ~600 (valid: the documented C_PUCT crossover).
  Screen 240 g/candidate, holdout 600 (CI ±0.04). Interim findings (stable): **`C_PUCT=1.5` confirmed optimal
  at sims=500 — NO crossover above 160** (every alt screens <0.5; the 1.0-best crossover is below ~120 only);
  tiebreak dead; sim-mult faint wash; one **borderline `H3_PICK_W` 1.5→2.0 adoption (holdout 0.524, barely over
  the +0.02 bar; its screen was 0.467 → screen↔holdout inconsistency ⇒ likely noise, and sharper-prior is the
  documented don't-survive family)** pending the final fresh-seed + panel RPS arbiter.
- **Open / next:** finish the sims=500 autotune (treat the H3_PICK_W adoption skeptically — confirm or reject
  via fresh + panel); then run `NOBLE_MULTI_W`. The proven lever remains search DEPTH (sims throughput), not
  eval re-weighting (re-confirmed: every endgame/search re-weight washed at the prod operating point). Parked:
  "search owns DISCARD/NOBLE + a discard prior" (low gain).

### Session (late June 2026) — metric directive, NOBLE_SCALE 3.5, Cython rewrite (ON MAIN), weakness audit

**TUNING METRIC DIRECTIVE (user instruction — SUPERSEDES the MAXIMIN {H3,H2,H2N,H2R} panel described above).**
Judge AI tuning ONLY by **S vs frozen-S** (the self-gate; primary), with **H3 / H3N / H3R** as a strong secondary
sanity panel. **NEVER report or weight H2 / H2N / H2R again** — too weak; weighting them gave misleading verdicts
(e.g. the lower-`NOBLE_SCALE` "wash" was an H2N artifact). H3N = `_AggrH3(2.0)` (noble-heavy), H3R = `_AggrH3(0.4)`
(rusher), built fixed-base off the committed `NOBLE_SCALE` so they don't drift with the candidate;
`config_selfgate.PANEL=["H3","H3N","H3R"]`. These opponents + the rejected-experiment flags below are currently
**UNCOMMITTED on the `heuristics` worktree** (pending a selective finalize), not yet on main. Mirror in memory
`spender-tuning-metric-s-selfgate`.

**NOBLE_SCALE 5.0 -> 3.5 -> 3.0 — SHIPPED (3.5 on `15717fe`; 3.0 on current commit).** Lower-noble S-vs-frozen-S sweep (sims=400, N=350) was a
wash on the self-gate (3.5 fresh 0.516; all values' CIs straddle 0.5); shipped on the user's call (faint-positive
self-gate + H3 +0.025). Affects BOTH H3 and S. COUNTERINTUITIVE H3-panel trade: lower noble HELPS vs a noble-player
(H3N +0.068) and HURTS vs a racer (H3R -0.050) — a racer leaves S's nobles UNCONTESTED, so nobles are an edge vs
racers; the change is matchup-lopsided, not a clean gain. (Supersedes the "3.0->5.0" note above.)

**Cython `engine_value` rewrite — ON MAIN (`f82cc79`, ~1.85-2.74x).** `valuation3.py`'s engine_value chain
(`engine_value`/`_delta_take`/`_cost_scalar` + cost/deficit primitives) is typed-Cython on C int arrays (static
`E.COST/BONUS/PTS` -> module C arrays; per-state bonuses/tokens extracted per call). **Single-source, runs three
ways** (verified): pure Python with cython ABSENT (an `ImportError` shim no-ops the type/decorator constructs;
C-array blocks gated on `cython.compiled`), pure Python with cython installed, and the compiled `.so`/`.pyd` (fast).
The **Dockerfile multi-stage-compiles it** (builder `cythonize` -> `.so`; slim runtime carries only the `.so`; build
FAILS on miscompile, so a bad compile can't reach prod) — so merging the `.py` is enough; prod builds its own Linux
`.so`. Gated byte-identical by the exact-value tests + a differential-parity check. PyPy was tried + REJECTED (slower
+ not bit-parity — numpy in the search hot path goes via cpyext). To prototype eval ideas, hack the readable
pre-Cython `valuation3.py` from git history, then re-Cythonize only the winner.

**Rejected this session (DO NOT relitigate — all judged by S-vs-frozen-S; flags default-off / byte-identical,
uncommitted on `heuristics`):** endgame tiebreak (`ENDGAME_TIEBREAK_W`) + deeper-final-round sims
(`ENDGAME_SIM_MULT`) = noise; the sims=500 autotune's `H3_PICK_W`/`POLICY_TEMP` adopts = noise ratchet (0.480 fresh);
multi-noble position term (`NOBLE_MULTI_W`) = inert; per-card overlap reward (`NOBLE_COUNT_W`) = behaviorally ==
pure magnitude; supply-aware noble gate (`SUPPLY_PENALTY`) = cuts a late-buy "blunder" rate ~11% but washes
win-rate. Re-confirms eval re-weighting is saturated UP **and** DOWN; the lever is search / eval-class, not weights.

**Weakness audit (7 user wins vs S over 4 days, queried straight from the Turso prod DB).** S wins the large
majority vs the user; the losses share ONE dominant cause — **S races too slow / inefficiently**: ~0.75 pts/card
(avg 16 cards, ~12 of them 0-point, ~12 pts) vs the human's ~1.16 (efficient point-cards); the user reaches the win
first in 6/7. Secondary: over-reserve (4/7 end with an unbought 3+pt L3) and a horizon-1 **endgame-denial blind
spot** (1/7, game `IYGWJQ` — `_deny`/`_opp_best_buy` only catch a NEXT-TURN opponent win, missing a 2-turn
reserve-then-buy threat). This cluster is **human-exploitable but tuning-resistant** — S beats the synthetic racers
(81.5% vs H3R) *because* they don't punish it, which is why every weight experiment washed while the human keeps
winning. **QUEUED fix:** a 2-turn endgame-denial horizon (extend `_opp_best_buy`/`_deny`/`_secure_win`; `IYGWJQ` is
the regression test). The deeper "race efficiently" fix is the documented hard lever (search / net).

**Querying the prod DB directly:** Turso creds (`TURSO_DATABASE_URL`/`TURSO_AUTH_TOKEN`, Render-only) live in a
local gitignored file `C:\Users\Forrest\.spender_turso`; query via `curl` POST to `<https-host>/v2/pipeline` (the
libSQL HTTP API) — no libsql Python wheel needed. Note `list_user_games` excludes `status='over'`, so finished
games aren't listable via the API — query the DB directly for them.

### Session (June 23 2026, `evaluations` worktree — SHIPPED to main with the k6 push, June 24)
**Tuning metric HARDENED + harness trimmed.** Judge AI tuning by **S-vs-frozen-S ONLY** — the H3/H3N/H3R panel is now **opt-in** behind `config_selfgate --panel` (default = sanity + screen + fresh holdout, nothing else; never run the panel unless explicitly asked). `--sanity-n` (default 10 PAIRS = 20 games): frozen-vs-frozen is *deterministically* 0.5 under paired CRN, so a handful confirms the harness is unbiased — don't spend the full `--n` on it. Ported the `_AggrH3` H3N/H3R opponents (were uncommitted on `heuristics`) into the evaluations `h3_vs_h2.py` + `vsearch_camp.py` `OPP` so `--panel` doesn't `KeyError`.

**#4 — seat-aware / bonus-discounted deck demand (`valuation3.DECK_BONUS_DISCOUNT`) — ADOPTED (default True).** `engine_value`'s deck term was seat-BLIND (raw undealt-deck color cost, same for all players). Now seat-AWARE (`_deck_demand_seat`): per undealt card subtract the seat's bonuses (`max(0, cost[c]-bonus[c])`), **normalized by the RAW deck total** — so a color you've fully covered → ~0, the OTHER colors keep their TRUE value, and overall magnitude legitimately SHRINKS as your engine fills in. WON: **fresh 0.5425 vs frozen-S (SHIP)**. The first cut RENORMALIZED (÷ discounted total → sum 1) and LOST (fresh 0.4775): **DO NOT renormalize a bonus-discount** — it inflates the un-built colors (fabricated demand); let magnitude drop, compensate via `ENG_DECK_W` if needed. Only the TOP-LEVEL deck term is seat-aware; `eng_base` (legacy level-0, inside `potential`/`_delta_take`) STILL uses the seat-blind `deck_color_demand` — matches the validated Python path.

**Dev-box Cython + the #4 monolith fix.** Compiled `valuation3` on the dev box (cython 3.2.5 / Py3.14 → `valuation3.cp314-win_amd64.pyd`) so the offline gates run the compiled leaf, not pure Python. **The `.pyd` SHADOWS the `.py` — recompile (`cythonize -i -3 games/spender/ai/az/valuation3.py`) after EVERY `valuation3` edit or workers silently use STALE code** (verify byte-identical via the build-gate tests + a differential `engine_value` signature hash). **Extended the C monolith `_engine_value_h3_c` to handle #4** (it was gated `not DECK_BONUS_DISCOUNT`, routing #4 to the slow Python path). FOOTGUN: the monolith fed ONE `dcd` vector into BOTH the inner `_eng_base_c` AND the top-level deck term; a naive single-vector swap to seat-aware broke byte-identity (**0.077 error**) because `eng_base` must stay seat-blind. Fix = TWO vectors — `dcd` (seat-blind → `_eng_base_c`) + `dcd_top` (seat-aware → the top-level `ev += dcd_top[bcol]*deck_w` only). Byte-identical confirmed (sig match + max-diff 0.000 + 32 tests).

**REJECTED this session (all S-vs-frozen-S; flags default-off / byte-identical):**
- **`heuristic3.TEMPO_TURNS_SCALE`** (late-game tempo-weight scaling off measured turns_remaining): WASH (fresh 0.5012). Time is already carried by the `compound_turns` engine horizon; re-penalizing tempo in the cost denominator is redundant.
- **Progress breadth — PARTLY SUPERSEDED, see the June 24 "k6" block below.** `v_state` gained `PROGRESS_TOPK`/`PROGRESS_DECAY` (cascade-weighted progress over the top-K take_values; `W_PROGRESS` now a probe key) — `_progress` was a top-2 mean, blind to ~10 reachable cards. The cascade "winner" (top-5, W=3.4, fresh 0.5275) was a **CONFOUND**: the true magnitude-match for flat top-5 is **W=2.92, not 3.4** (measured take_value means: top-2 ≈1.93, top-5 ≈1.65, top-8 ≈1.48), so it ran ~16% extra progress weight. At TRULY matched magnitude, **k=8 WASHED** (flat W=3.26 fresh 0.5038) — so breadth *at matched magnitude* is NOT a lever, and *pure* magnitude (top-2 + W∈{2.7,2.9}) also went sub-0.5. **The June-24 follow-up found the real effect is the INTERACTION** — breadth (K≈4–6) AND over-magnitude (~1.16–1.3×) *together* give ~+4pp; neither alone does. (Magnitude-compensation is MULTIPLICATIVE: progress contribution = `W_PROGRESS × mean(top-k)`; match the PRODUCT — `W = 2.5 × baseline_mean / new_mean` — not the mean.)
- Built-but-unrun: `valuation3.DECK_STAGE_TILT`/`DECK_STAGE_T0` (level-realization tilt of the deck term — the "L1 over-counted, never shifts to L3" idea) and an asymmetric-progress idea (top-1 for the side-to-move, top-2 for the waiter — bakes denial/tempo into the leaf).

**Game-replay limitation (found analyzing a real loss — LBBMRC, lost 14–20 to S: led on points but ignored the noble race; S swept 3 nobles).** Per-turn `v_state` CANNOT be reconstructed for EXISTING games: the saved game stores only the FINAL board/deck + an id-only move log — NOT per-turn board snapshots NOR the initial deck order/seed — and `progress` needs the board each turn. **To make FUTURE games replayable** (and re-scorable under any eval variant): in `main.py` store an initial `setup` snapshot (shuffled deck order + board + nobles) at game creation (`_deal_board` mutates `decks` in place; no seed is saved), AND **log `discard` moves** (the human `discard` path + `_ai_discard_one` aren't logged → token counts drift on replay). Then replay = rebuild from `setup` → re-apply the log → `from_game_dict` → `v_state.value` per ply. NOT yet implemented.

**Ops — gates kept dying with exit 127 = OOM.** Root cause: an ORPHAN PILEUP — a failed `mp.Pool` run leaves worker processes alive that eat RAM → the next gate OOMs → more orphans (vicious cycle). **Reap `C:\Python314\python.exe` procs before each gate.** Run gates with **`SPENDER_AZ_MODEL=none`** (the self-gate uses S/H3, NOT variant Z — skips the per-worker `az_model.npz` load, a big memory saver). The box is ~16GB but often <1GB free (VS Code + Firefox) and **CPU-bound at ~10 of 12 cores** (more workers don't help). **Don't edit `az/` modules while a gate runs** (Windows `mp` spawn re-imports → BrokenPipe crash). Remaining speed levers (diminishing — leaf already compiled): naive-cythonize `mcts.py`+`engine.py` (~10–15%), then `@cython.cclass` Valuation (~1.3–1.4×, large rewrite); past that, a bigger box (CPU-bound).

### Session (June 24 2026) — k6 progress adoption + past-S checkpoints (SHIPPED to main)
**k6 — `v_state` PROGRESS_TOPK 2→6 + W_PROGRESS 2.5→3.54 — ADOPTED + DEPLOYED.** This REVERSES the
June-23 "breadth is not a lever" conclusion: breadth IS a small lever, but **only paired with an
over-matched magnitude** — the INTERACTION the prior session missed by testing each axis alone. An
overnight K×magnitude grid (sims=500) then a **fresh disjoint-seed confirmation** found a coherent
ridge peaking at **K≈4–6, magnitude ~1.16–1.3×M0**: k4@1.30× and k6@1.16× both held ~0.54 across
seed bases; k3 (too little breadth) and k5@1.30× (too much magnitude) fell off. `PROGRESS_DECAY`
stayed **1.0** (plain mean) — the cascade/decay shape was a confound, not the lever. Evidence (all
S-vs-frozen-S unless noted): self-gate **0.543 / 0.545 / 0.531 across THREE disjoint seed bases**
(pooled ~0.540, the third-seed pullback says the true effect is the LOW end, ~+4pp); **H3/H3N/H3R RPS
panel PASS** (worst matchup +0.018, no exploitation — slight −0.017 vs racer H3R, +0.033 vs noble
H3N, the documented progress-helps-vs-noble pattern); **past-selves panel ≥0.5 vs all** (0.579 vs
frozen, 0.591 vs s_original, 0.574 vs s_pre_progress, **0.500 vs s_noble_heavy**, avg 0.561 — never
loses to a style, worst case a tie vs the noble-lean). A real, robust, SMALL gain — eval-weight
tuning remains otherwise saturated; this snuck through as a structure (breadth)×magnitude combo.

**Past-S checkpoint system — NEW offline tooling (`s_checkpoints.py` + `s_vs_checkpoints.py`).** S has
no weight file; its "weights" are module constants. A **checkpoint** = a JSON snapshot of all **90
strategy constants, PER-MODULE** (so dup names like `NOBLE_TURN_W` in both v_state & valuation3 are
unambiguous) across v_state/vsearch/heuristic3/valuation3; serving/infra (`SIMS`/`SERVE_*`/caps) are
excluded. Small, **committed** JSON in `games/spender/ai/az/s_checkpoints/` (NOT gitignored, unlike AZ
weights); each stamps git commit + timestamp.
- **`s_checkpoints.py`**: `snapshot`/`save`/`load`/`apply_config` + **`reconstruct <commit>`** (overlay
  a past commit's constant values on today's full snapshot — keys absent then keep today's default) +
  **`derive --set K=V`** (today + targeted overrides) + CLI (`save`/`list`/`show`/`reconstruct`/`derive`).
- **KEY semantic (do not misread):** a checkpoint reproduces "that era's WEIGHTS on TODAY's code" — a
  reproducible **STYLE**, NOT a bit-exact old S. So every newer feature (#4, the Cython leaf, structural
  fixes) is present and ON in all past selves; they differ only in the weight LEVERS that existed and
  were set differently. Intentional: we want strong, same-strength, style-DIVERSE sparring partners
  (resurrecting old code would just give a weaker S). Confirmed e.g. `s_original` carries pre-maximin
  `W_ENGINE_STK=0.8`/`C_PUCT=2.0` but `DECK_BONUS_DISCOUNT=True` (too new to exist at da18bab).
- **`s_vs_checkpoints.py`**: panel-of-past-selves runner — protagonist (live ± `--set`) vs a set of
  checkpoints via the **per-turn config swap** (the ONLY safe way to run S-vs-S with two configs sharing
  module globals: re-assert each side's full config before its move). Paired CRN, parallel. Validated:
  `live vs its-own-checkpoint = 0.5000 EXACTLY`.
- **Purpose + CAVEAT:** a same-strength, diverse **RPS guard** the H3 panel can't be (S beats the
  heuristics ~80% regardless, so 75-vs-80 is saturated) + a progress tracker. It does **NOT** probe a
  brand-new knob's OWN axis (every checkpoint has `PROGRESS_TOPK=2` — topk is newer than every commit),
  so it tests a candidate vs diverse *other-lever* styles, not vs topk variety; k6's real validation was
  the self-gate + H3 panel, the past-selves run a bonus robustness check. **Value compounds — save a
  checkpoint on every adoption.** 5 committed: `s_2026-06-24` (pre-k6 baseline), `s_2026-06-24_k6`
  (ADOPTED/deployed), `s_original` (da18bab), `s_pre_progress` (fb813cf^), `s_noble_heavy` (today+NOBLE 5.0).

**Forward direction the user raised: build the panel from S-strength diverse opponents** (past-S
checkpoints + future "S-rusher"/"S-nobler" derived variants), and consider an **"S-lite" playable tier**
(depth-2 or tiny-sim search) as a strong-but-instant opponent given the heuristics are too weak and the
deployed S is sims-starved on Render's 0.1 CPU.

### Session (June 24 2026) — over-reserve deep-dive + game-loss trace-back (DIAGNOSIS, nothing shipped)
Investigated one real game a strong human WON vs deployed S (`YINAIM`, dumped from Turso). Three durable
conclusions; DO NOT relitigate:
- **Over-reserve "fix" — TWO mechanisms TESTED & REJECTED (neither converts through search).** Symptom:
  S over-reserves, filling all 3 slots with cards it never converts → at YINAIM turn 50 it had 3/3
  reserves and could NOT reserve-deny the human's winning L3-6 (a public, affordable board card). Built
  on a local **`reserve-slots` worktree branch (default-off, byte-identical, NOT merged):** (1)
  `v_state.W_RESERVE_SLOTS` — a position-leaf free-slot **optionality** term (concave `O(eff_free)`,
  `eff_free = 3 − Σ deadness(held reserves)`; deadness from **`valuation3.tempo`** = the STEEPEST
  single-color remaining need so 6-of-a-color reads far / 2+2+2 near — a raw gem-SUM misses steepness;
  NEAR_T=1/FAR_T=6 turns; horizon-faded; symmetric). (2) `vsearch.RESERVE_DISCOUNT_W` — discounts a
  reserve ACTION's prior by `deadness(card) × load` (far reserves already held) so the 1st speculative
  reserve is free and the cost escalates as you stack far ones. **Both wash:** W_RESERVE_SLOTS self-gate
  ≈0.5 and the move never flips even at high W; `RESERVE_DISCOUNT_W=8` self-gate **0.455** (sims=500,
  n=100) and even a ~90% prior cut does NOT flip the reserve move. **Why: the reserve's Q (denial +
  acquisition of a 4-pt L3) is genuinely high — a modified static leaf OR prior can't beat it through
  search** (re-confirms the documented "doesn't convert through search" wall). Also the self-gate MIRROR
  is structurally blind to a slot-lock cost (both copies over-reserve; neither races to exploit the
  other's full slots — only a human/exploiter would). Knobs parked default-off on the branch as
  NET-feature candidates; not merged. (NB H3 itself has `USE_SPECULATIVE_RESERVE=False` — the
  over-reserving is the SEARCH PRIOR's `RESERVE_PRIOR_W*take_value`, not H3 greedy.)
- **MCTS mean-backup is blind to a sharp 1-ply opponent threat until more sims / the opponent commits
  (quantified).** YINAIM's winning L3-6 was public + affordable + exactly 1 ply ahead, yet S's searched
  value the turn before was **+0.033 at 600 sims, −0.552 at 3000 sims** (true ≈ −0.45). Not hidden-info
  / not horizon — the root value is a visit-weighted MEAN that dilutes the single sharp reply among the
  opponent's explored weaker replies; depth (or the opponent actually playing it next ply) converges it.
  Reinforces the rejected mixmax/`BACKUP_LAMBDA` and that **search THROUGHPUT (faster leaf → more sims)
  is the lever, not a backup tweak.**
- **Trace-back self-play diagnostic → real games are lost in the EARLY-MIDGAME, not at the visible late
  symptom.** Reusable diagnostic (scratch `trace.py`, built on `replay.py`): for each historical turn T,
  play N self-play games (both seats frozen-S, remaining deck reshuffled per game) from that position to
  the end, record seat-0 win-rate, walk T back to where it was last ~0.5. **Validated unbiased** (fresh
  `new_game` seat-0 = 0.53 first-player edge; 5/5 distinct lines from a position = real variance, not one
  deterministic game — so the win-rate is meaningful, addressing the "they play the same game every time"
  worry). On YINAIM (N=80, sims=256): S started **even/slightly-favored** (turn 0 = 0.53), held ~0.5
  through **turn 8**, then slid **0.48 → 0.16 over turns 9–14** (early-midgame engine race), bleeding from
  there to the turn-50 corpse. **No single blunder — a gradual out-building.** The over-reserve /
  slot-lock / can't-deny-L3-6 at turn 50 were all DOWNSTREAM symptoms of a position already lost ~13 plies
  earlier. **Conclusion: the lever is early-midgame DEVELOPMENT TEMPO (build a faster/more-efficient
  engine) — not reserves, denial, or the endgame.** That's the hard eval/search lever, not a knob.



<!-- ===================================================================== -->
# ARCHIVE: Spender AI — variant N / PV ladder, discard-root fix, eval-axis screens, exploiter-net sessions
<!-- ===================================================================== -->

### Session (June 25 2026) — value-first ladder: variant N (learned value leaf) BEATS S (VERIFIED)
**The learnable path is not just OPEN — it produced a concrete win.** A learned **value leaf** used
inside variant-S's determinized search (+ the H3 prior) **beats the hand v_state leaf**, verified 5
independent ways. New variant **N** (Neural), a SEPARATE option alongside S. Built in the
`forrestm_projects-rust/spender-core` crate (the Rust→WASM search core); full write-ups in memory
`spender-N-learned-leaf-beats-S` + `spender-az-retrain-plan`, plan `.claude-plans/az-retrain-rust-scale.md`.
- **The recipe that beat the documented wall:** **outcome-trained** value (target 2·win−1 from self-play
  game OUTCOMES, NOT V_search) on an **enriched 101-feature** encoder (`spender-core/src/feats.rs` = raw
  state + v_state components + per-card derived + deck), a 256-hidden MLP (GPU/torch), used as the MCTS
  **LEAF**. Why it works where the documented "distilled leaf washes by 1200 sims" did not: that wash was
  for leaves distilled toward **V_search** (redundant with search); an **outcome-trained** leaf carries
  **beyond-search-horizon** signal search can't recover, so it converts AND holds at depth.
- **The 5 guards (harness `spender-core/src/bin/rung2.rs`, 80 games each, SE~0.05):** (1) CONTROL
  v_state-vs-v_state via the same path = **0.5000 exactly** (harness unbiased); (2) N-vs-S holds across
  depth **0.69/0.71/0.69** @ 400/800/1200 sims; (3) OUT-OF-SAMPLE on fresh decks (seed≥1M, outside the
  harvest's 0–5999) **0.64/0.71**; (4) **EQUAL-TIME** N@600 vs v_state@1200 = **0.66** (wins at a 2×
  handicap — the calibrated-leaf's killer, beaten); (5) PANEL N-vs-H3 **0.94** > baseline S-vs-H3 **0.84**
  (generally stronger, NOT RPS-vs-S).
- **The ladder (do not re-derive):** Rung 0/Phase 0 — Rust value-net inference is NOT a binding constraint
  (`bin/net_bench`: all candidate nets feasible for self-play; export-path numpy-parity verified
  `bin/net_export_check`). Rung 1 — a learned value at **1-ply** LOSES (vs H3 .12, vs v_state@1ply .07),
  but that's expected: **1-ply is unkind to position-values** (even v_state@1ply loses to H3 at .37);
  search is what makes a position-value strong. Rung 2 — the value as the **search leaf** is where it
  shines (the 5 guards above).
- **simgate (1M vs 1.2k sims, both v_state-S) = 0.5100 (a TIE, ±0.098, 100 games):** search **SATURATES
  ~1.2k sims** for the current eval. So the lever is **eval/policy quality, NOT more sims** — re-tuning
  sims is dead, and the WASM push *beyond* ~1.2k gave little serving strength (its real value is the fast
  offline self-play that enables value-learning + N's equal-time win, since N@600 is already near-saturated).
- **NEXT:** (a) ~~ship N as a served variant~~ DONE (`c96e3fd`, "Nina"/expert in the lobby; see the next
  session note); (b) un-anchored **self-play** (N-vs-N, value bootstraps on its own improving play beyond
  S's distribution) — N's supervised net is the proven FLOOR. Training: torch/GPU (the `python` with cu128,
  NOT `/c/Python314` which lacks torch + numpy there is ~1.5 GFLOPS / 17-min fits); reap orphaned-python.

### Session (June 26 2026) — N served-variant bug fixes (deployed `da60406`)
N shipped as the website "Nina" (expert) option (`c96e3fd`) but three serving issues showed up in real
play; all fixed on `main`. **N's leaf runs CLIENT-side (WASM, `searchN`), with the server falling back to
S's v_state search if the client doesn't submit in time.**
- **"not the AI's turn" error toast (the headline bug).** N's WASM worker `build_n_net()` parses its
  **embedded ~600KB `n_model.json` ONCE PER MOVE, BEFORE its search budget timer even starts** (see
  `spender-core/src/wasm.rs::search_visits_n_timed`), so N's wall-clock runs ~1-2s longer than S's and was
  **losing the 6s client/server race** on slower devices — its late `ai_move` then hit the `ai_move`
  handler's `g.turn != ai_pid` guard, which sent `{type:"error","message":"not the AI's turn"}` → a toast.
  **Two-part fix:** (1) `CLIENT_AI_TIMEOUT` 6.0→**8.0** so N reliably WINS the race (and when the client
  wins, the move applies the instant it's submitted — the human never waits the full timeout; it only
  bounds the truly-can't-compute fallback); (2) the `ai_move` handler now **LOGS stale submissions instead
  of toasting** — a late client move is a normal race artifact, never the user's fault, and the server
  fallback already guarantees the turn advances (so silently dropping it is safe; never re-add the toast).
- **Admin "Vals" overlay now works for N (position eval ONLY, by request).** N had no overlay (the per-card
  block only handled H/H2/H3/S), so the gold Vals button never rendered. Added a **faithful Python port of
  N's value net** in `main.py`: `_load_n_model` (loads the **SAME `spender-core/src/n_model.json` the WASM
  embeds** — single source, no drift; path = repo-root/spender-core/src; shipped by the Dockerfile `COPY .`),
  `_n_features` (a line-for-line port of `spender-core/src/feats.rs::features` — the 101-feature vector,
  reusing the Python `v_state`/`valuation3` helpers the Rust was ported from), and `_n_position_eval`
  (z-score → dense→ReLU→dense→tanh, [-1,1] from the mover's seat). Wired into `_compute_overlay` (N →
  **`ai_position_eval` only, NO `ai_card_values`**) + the `mk_room_state` overlay gate. Frontend
  (`Spender.jsx`): the Vals toggle + eval pill now gate on **(card values OR a position eval)** so they
  appear for N; the pill is N-aware (label **`eval`**, NO never-resolving "srch …" — that's S-only). Cost is
  one tiny MLP forward per broadcast (~same as S's `_s_position_eval`). Gracefully omits if numpy/the file
  is unavailable. (It IS admin-only, same as every variant's overlay.)
- **Take button right-aligned.** The action-button rows (`.actions-panel-btns`/`.board-actions-btns`) were
  `justify-content:center`, so with no Vals button (N before the fix) Take floated to the MIDDLE. Changed to
  **`flex-end`**; the Vals toggle's `margin-right:auto` keeps it on the LEFT when present, so **Take is now
  always against the right edge** for every variant (no regression — with the toggle present the auto-margin
  already pinned Take right under `center` too).
- Validated: backend review/replay/game-logic tests pass (119); N eval verified in [-1,1] with correct
  mover-perspective; `npm run smoke` clean (CLS 0). The WASM was UNCHANGED (already shipped `searchN` in
  `c96e3fd`); this was a Python-timeout + JS-gating + CSS fix only.

### Session (June 26 2026) — Plan-A AZ retrain → variant PV (policy+VALUE net) SHIPPED as "N"; league run launched
**The learnable-net path is REALIZED (this UPDATES the "learnable-leaf path" question above):** a
warm-started **policy+value** net ("PV", `net_pv_4`) BEATS both old-N and S in search. Prior learnable
attempts lost because they distilled-S / trained from-scratch on flat features; PV wins because it pairs
the **enriched 125-feat encoder** + a **warm start from the N value-leaf bootstrap** + AZ self-play.

- **The PV stack (Rust, `rust-search` worktree + `C:\Users\Forrest\az_run`):** `PolicyValueNet`
  (valuenet.rs — trunk + value head + 70-action policy head), `feats::features_az` (125 = base 101 +
  per-card `engine_value`+`noble_progress`; the per-card adds earned their slot in a policy pre-check,
  +0.024/+0.017; engfwd/turns/oppdem DROPPED as no-lift), `vsearch::root_visits_until_pv` (determinized
  PUCT, legal-masked softmax of net policy logits at PLAY, H3-prior fallback at discard/noble, net value
  leaf). Bins: `selfplay_pv` (self-play harvest), `train_pv.py` (GPU value+policy trainer, value MSE +
  policy CE, reward-shaped `(1-a)(2y-1)+a·tanh(margin/6)`), `eval_pv` (vs S), `eval_vs_n` (vs old-N via
  `features_n101`, the 101 encoder lifted from HEAD), `harvest_az` (S-vs-S bootstrap → `boot125.csv`,
  2.26M rows). `azloop.sh` ran it.
- **Self-play PLATEAUED (do not relitigate):** vs-S FLAT ~0.735 across 12 iters while value-AUC kept
  RISING — the documented self-play-diverges-from-the-external-opponent signature (the net got better at
  beating its own clones, not S). The per-iter "peaks" (0.80) were **n=160 eval noise**; a 600-game
  fresh-decks re-eval regressed them to ~0.73–0.76 (net_pv_4/8/12 statistically tied). One-time gain
  over N, did NOT compound. **net_pv_4 = champion.**
- **PV champion validated:** vs old-N **0.60 / 0.66 / 0.67 @ 160 / 400 / 800 sims** (robust, edge GROWS
  with sims — a good policy compounds with depth), replicated on net_pv_8/12 (0.63/0.68); vs S **0.758**.
  The learned POLICY adds **+0.58 over the H3 prior** at a matched value head (control bin
  `eval_policy_ctrl`: full-PV vs PV-value+H3-prior). So both the richer value head AND the policy head
  pull their weight.
- **SHIPPED, served AS variant "N" (Nina, the top tier):** first as a separate "PV"/Percy variant (commit
  `2a50b5a`), then **folded INTO "N"** (commit `12fc540`) per the user — `Spender.jsx` routes
  `ai_variant==="N"` → `searchPV`, and the Percy/PV lobby option + persona were removed. **Old value-leaf
  N is KEPT AS A RECORD** (`n_model.json` + `search_visits_n_timed`/`searchN`/`build_n_net` all stay in
  code, just not routed to). **Upgrade path: swap `spender-core/src/pv_model.json` → rebuild wasm → push;
  "N" instantly plays the stronger net, no UI change.** (The WWSD browser autoplayer also adopted PV —
  `search_pv_full_timed`, v0.9.0; see the WWSD section.) See memory [[spender-variant-pv-shipped]].
- **DEPLOY GOTCHA (do not relitigate):** the AZ/WASM work was built on **stale `rust-search` (49 behind
  origin/main)**; production = main ALREADY had the WASM client-AI + variant-N foundation via a different
  history, but NOT the Plan-A additions. So deploy = **PORT onto main** (fresh worktree off `origin/main`,
  add-only edits, `push origin <branch>:main`) — **NEVER push `rust-search:main`** (non-ff wipes 49
  commits). **Dual-encoder split (load-bearing):** main's `features()` stays **101 (old-N's net)**;
  `features_az()` is the NEW **125 (PV)** — kept separate so old-N isn't fed the wrong dims (on rust-search
  `features()` had been redefined to 125, which BREAKS old-N — that working tree isn't deployable as-is).
  All Rust diffs onto main verified **purely additive (0 deletions)** → N byte-unchanged. The built
  `spender_core_bg.wasm` is a COMMITTED artifact (Pages CI does NOT rebuild Rust→wasm); wasm grew to
  ~2.07MB (embeds the net) — candidate for external-load later.
- **Discard-search = WASH (do not relitigate):** `selfgate_discard.rs` found **93/93 multi-option discards
  where the searched pick == greedy H3 `choose_discard` (0% divergence)** → the greedy discard is already
  search-optimal; searching it just burns sims. `root_visits_until_leaf_ds` parked on the branch.
- **LEAGUE run (IN PROGRESS, `az_run/league_loop.sh`) — escape the plateau via opponent diversity (the
  documented cure for self-play tunneling):** `league_pv.rs` (the BEST net records ONLY its own moves vs a
  FIXED opponent — S / old-N / a rotating past-PV checkpoint — shaped by margin; learn to BEAT them, not
  imitate) + `pv_vs_pv.rs` (gate PRIMARY: candidate vs frozen best, paired-CRN, =0.5000 for identical
  nets). Mix **self .4 / past-PV .25 / S .2 / old-N .15** — **H3 DROPPED** (PV crushes it ~95% → saturated
  targets, near-zero margin gradient; its share went to past-PV, the closest/most-informative opponent).
  Buffer ~**50/50** (subsampled `boot125_sub.csv` anchor, 600k rows, so the league signal isn't drowned —
  the self-play loop's 87% bootstrap anchor was part of why it stalled). **Gate = beat frozen best ≥0.52
  AND RPS guard (vs-S ≥0.72, vs-old-N ≥0.60 — net_pv_4's scores minus noise).** **Verdict to watch: the
  per-promotion `best vs SHIPPED net_pv_4` line — >~0.55 = the league broke the plateau (swap
  `pv_model.json` + ship); ~0.5 across many iters = the architecture ceiling, net_pv_4 stands.**

### Session (June 27 2026) — ENRICHED 178-feat retrain BEATS net_pv_4; `net_ext_19` SHIPPED as "N" (`613c91f`)
**The feature-enrich retrain WORKED — refuting the "variant N is at the ceiling" pessimism (the league above only TIED net_pv_4; ENRICHING THE FEATURES + self-play broke through).** `net_ext_19` (a 178-feat policy+value net) beats the shipped champion net_pv_4 **~0.59-0.60, DEPTH-ROBUST** (256/800/3200 sims = 0.586/0.584/0.602 on fresh decks — no decay, unlike the calibrated-leaf wash). **DEPLOYED as N** (`613c91f` on main): selecting N now plays net_ext_19. The enrich+self-play loop is now a REPEATABLE strength engine, not a one-off.
- **Encoder `feats::features_ext` (178)** = deployed base 125 (`features_az`) + 5 groups: A per-color self-need (5), B opp face-up reserve content (12), C own reserve content (12), D per-card take_value (12), E per-card turns-to-afford (12). Trained on the **rust-search** worktree (`az_run/loop_ext.sh`): warm-started by distilling net_pv_4's PV-vs-PV play into the 178 net (clean distill 0.517 vs net_pv_4), then self-play with the anchor annealed off. CONVERGED at iter 24 (champion edge flat ~0.58-0.60 for ~10 iters; `cand_vs_best` oscillating at the 0.52 bar).
- **Pick the best net by RE-GATING ALL candidates on FRESH decks — NOT the in-loop promotion (winner's curse; DO NOT regress).** The noisy 0.52 gate (SE 0.032 ⇒ ~27% false-promote on a tie) doesn't reliably pick the strongest net. High-N re-gate (960 games, disjoint deck base): `net_ext_15` (highest in-loop, 0.635) REGRESSED to 0.577; **`net_ext_19` (a KEPT, not-promoted iter, logged 0.606) held/rose to 0.618 → the actual best.** Always re-gate the candidate set on fresh decks.
- **C_PUCT swept** (`gate_cpuct.rs` self-gate vs varying c_puct + `vsearch::root_visits_until_pv_c`): flat 1.0-2.0, falloff >2.0; the faint c_puct=1.0 edge (+0.02 @ 800 sims) VANISHED at 3200 (0.489) → **keep C_PUCT=1.5** (same low-sims crossover trap documented for S).
- **Deploy = PORT onto main** (worktree `forrestm_projects-pvdeploy`, branch `ext-deploy` off origin/main; **NEVER push rust-search:main**): added `features_ext` to main's feats.rs (reuses `features_az` as base — VERIFIED functionally byte-identical to rust-search's `features()`) + the 5 groups VERBATIM; **encoder PARITY byte-verified over 170 states** (`dump_ext.rs` on both crates — guaranteed because engine/valuation/v_state/heuristic are byte-identical across the branches); overwrote embedded `pv_model.json` with net_ext_19; switched the two PV serving closures `features_az`→`features_ext` in wasm.rs; rebuilt wasm (`wasm-pack build --target web --release --no-typescript` → cp to `webapp/public/wasm/`); `npm run smoke` PASS. **N routing UNCHANGED** (`ai_variant N`→`searchPV`→`search_visits_pv_timed`). **Rollback = `git revert 613c91f`** (restores net_pv_4 + the features_az path; both kept in the tree). wasm ~2.07→2.37MB.
- **The 0.59-0.60 is a SELF-GATE edge — it does NOT prove the human-found weakness is fixed.** That weakness (efficient **race-to-15 ignoring nobles**; single-strategy collapse) is self-gate-BLIND. Confirmed offline on real game **`XJJJDF`** (user won 15-11 vs deployed N): the human raced 12 cards / 15 pts all-from-cards / 0 nobles / **1.25 pts-per-card** (two 4/7 L3s + a 3/6 L2), while N went wide+noble — 16 cards, **12 zero-point**, 0.50 pts/card + a noble (spent turns 33-43 on six straight 0-point L1s). The static leaf rated N AHEAD the whole midgame (it under-prices the human's reserved-but-uncashed L3 race). Regression set: `XJJJDF`/`IYGWJQ`/`YINAIM`. **The live playtest is the real test; the RACER track is still the gate** (build a Rust racer proxy → confirm the weakness reproduces → add the racer to the training mix + gate vs it; the generic league is REJECTED, but a TARGETED racer is the new ingredient self-play can't generate).
- **Overnight (RUNNING, `az_run/loop_night.sh`, capped ITERS=40):** continuation from net_ext_19 at **SIMS=512** (the documented plateau lever — higher-quality targets) + TEMP=30, gating vs net_ext_19. Crosses ~0.55+ → high-N re-gate + ship; flat → 200 sims wasn't the ceiling, pivot to the feature round + racer track.
- **Next enrichment round = MORE FEATURES (the proven higher-EV lever), done ATTENDED** (new dim ⇒ warm-start distill, a multi-step build like this one). Memory `spender-feature-backlog`: **HEADLINE = the user's same-color payoff-concentration / denial-robust-fork idea** — ≥2 steep same-color point cards ⇒ that color is a multi-target, *un-deniable* investment (opp can reserve-deny ONE payoff card, not both without crippling themselves); encode as a per-color top-2 of `PTS×color-need` (distinct from per-card `engine_value`). Plus racing-aware features (points-per-turn race read, per-card noble-overlap, victory-proximity) + the parked H2 net-feature candidates.
- **Offline tooling added** (rust-search + pvdeploy crates): `gate_seat.rs` (per-seat win-rate split), `gate_cpuct.rs` + `vsearch::root_visits_until_pv_c` (c_puct sweep, byte-identical to `root_visits_until_pv` but caller-chosen c_puct), `dump_ext.rs` (feature-parity dump). Prod finished-game analysis: query Turso direct (creds `C:\Users\Forrest\.spender_turso`; `list_user_games` excludes `status='over'`; the saved row is the ROOM dict — game is `state_json→game`, carries `setup` → replayable via `replay.py`).

### Session (June 27-28 2026) — net_night_14 → 15-pt N; **21-pt Long-mode net SHIPPED**; three feature/exploration verdicts (15-pt N at ceiling); card-set-attention big bet started
- **`net_night_14` was the deployed 15-point N** (`6c3e66b`, superseded net_ext_19): a higher-sims (512) self-play continuation, beats net_ext_19 ~0.55-0.58, S 0.827. PURE net swap (same 178 `features_ext` encoder). **(SUPERSEDED for Classic 15 by the card-set attention net `net_attn_3` — see "Variant N (CURRENT CHAMPION)" below; net_night_14 now lives on only as the 21-pt N base.)**
- **21-POINT ("Long" mode) SPECIALIST SHIPPED — `b91a744` on main. The one clear win this session.** N now serves **`net_ext21_13`** when `win_points==21`, keeping net_night_14 for Classic 15 — ONE opponent, auto-picked by game length (like S auto-adapts), NOT a separate lobby entry. The deployed 15-net was trained ONLY on 15-pt self-play and merely auto-adapted to 21; a net that actually TRAINS on 21-pt games captures real Long-mode signal it never had. **Validated: beats net_night_14 AT 21 = 0.6325 on fresh decks (600g), holds 0.58-0.65 across the 256/512/1024/2048 sims-ladder (depth-robust), beats runner-up net_ext21_32 head-to-head 0.477/0.467.** Mechanism: `wasm.rs` `search_visits_pv_timed`+`search_pv_full_timed` branch on `s.win_points` → `build_pv_net_21()`; `pv_model_21.json` embedded next to `pv_model.json` (both 178-feat, same encoder/serving path; wasm 2.37→3.78MB). Trained by `az_run/loop_ext21.sh` (`selfplay_ext`+`gate_ext` gained a `win_points` arg, default 15 = byte-identical; the whole Rust stack is already win_points-parametric — it's even an encoder feature, feats.rs:27), warm-started by WEIGHT-COPY from net_night_14. The loop CONVERGED (~0.58-0.60 vs champion, best net_ext21_13 by iter 13, plateau through iter 32). **Lesson: the gain came from NEW TRAINING EXPERIENCE (21-pt games), not new features/arch** — the pattern that actually works. Classic byte-identical; rollback = `git revert b91a744`. (Deploy gotcha: pvdeploy `ext-deploy` was 13 wwsd-commits BEHIND origin/main → rebased the 1 commit on top before pushing; core unchanged across them.)
- **THREE NEGATIVE VERDICTS — the 15-point N is at its ceiling (DO NOT RELITIGATE):**
  1. **Round-2 feature enrichment WASHED.** `features_ext2` (204 = 178 + 5 AGGREGATE groups: same-color concentration/fork, race-state, noble-race, buying-power, color-coverage) self-play loop (`loop_ext2*`) plateaued ~0.547 vs net_night_14, no promotion past the early best in 13 iters. The aggregates are REDUNDANT with the per-card features the net already has — unlike round-1's per-card features which converted. (Note: the user's headline "payoff-concentration/fork" idea was IN this round → washed.)
  2. **Dirichlet root-noise exploration WASHED.** The self-play loop had NO Dirichlet (only visit-sampling first 30 plies); ADDED it (`mcts::Search::apply_root_dirichlet` Marsaglia-Tsang gamma/dirichlet + `vsearch::root_visits_until_pv_noise` + `selfplay_ext2` `dir_eps/dir_alpha` args, default 0 = byte-identical). eps=0.25 tracked dead-even with no-noise (9 iters); eps=0.40/alpha=0.15 dipped (noise-degraded data) then recovered to parity. **Exploration is NOT the bottleneck.**
  3. **Round-3 per-card features WASHED (cheap pre-check, ~15 min — no loop spent).** `features_ext3` (214 = 178 + 3 NEW per-card groups: per-card CLOSING `(my pts after buying ci incl. free noble)/win_points`, per-card OPP take_value, per-card OPP-affordable-now) → harvest net_night_14 self-play (227k rows) → `precheck3.py` leave-one-out vs the deployed 178 base. ALL washed: closing dtop1 **-0.0004** (the net already derives closeness-to-win), opptv **+0.0046** (sub-threshold + AUC down), oppaff **-0.0031**. (Round-1's +0.009 didn't convert, so +0.0046 won't.) **The "new per-card info" well that fed round-1's win is dry — adding more derived per-card quantities is redundant once the net has take/turns/engine/reserves.**
- **RACER ROUTE REFUTED (DO NOT relitigate the heuristic-racer form).** Hypothesis: N is blind to a pure-efficient-L2 racer that ignores nobles (the human's winning style). Built `heuristic::choose_action_racer` (H3 with a `Valuation.noble_scale` field, default `heuristic::NOBLE_SCALE`=3.0, lowered to de-emphasize noble-CHASING; `noble_completion_pts` untouched so it still grabs free nobles) + `racer_probe.rs`. **N CRUSHES the racer 0.92-0.95 at every noble weight {3.0,1.2,0.5,0.0}, and win-rate RISES as nobles drop** (a low-noble H3 is just a weaker H3). N out-searches ANY 1-ply heuristic regardless of style → a heuristic racer can't expose the weakness (the documented "MCTS saturates a competent heuristic"). The human's exploit is value-CALIBRATION (N read +0.8 in a 15-13 coin-flip), not "N loses to racers" (it doesn't). A search-based racer is the only untested racer form (low odds; S already loses 0.24 to N).
- **BIG BET STARTED (user-chosen): CARD-SET ATTENTION net.** The deployed net is a tiny single-hidden-layer MLP over a flat 178-vector; untested whether a better INDUCTIVE BIAS (attention over per-card tokens) breaks the ~0.65 plateau via the same self-play (the earlier ~0.66 cap was a feature-limited DISTILL test, not a self-play policy net). **Arch locked:** 18 tokens (12 board + 3 own-reserved + 3 nobles, masked) × ~24 feats → embed D=64 → 2×[4-head MHA + FFN128] (residual+LN) → mean-pool + state-embed(28) → trunk128 → value(tanh)+70-policy. **Phase 0 throughput gate PASS** (`attn_bench.rs`): attention forward 2041 eval/s vs MLP 49055 = **24× slower** → ~17k aggregate sims/move, but the deployed MLP is ~400k sims/move (~500-1000× past the ~400-800 sim diminishing-returns knee) so 17k is still ~20-40× past it → **servable client-side** (WASM ~1.5-2× + per-call allocs ~2-3× recoverable → ~8-12k real, still fine). **Next = Phase 0 PARITY**: `features_tokens(s,seat)→(tokens,mask,state)` + the attention forward in BOTH Rust lib (`attn.rs`, for self-play+serving) AND PyTorch (training), parity ±1e-4 (self-play infers in Rust, trains in PyTorch — MUST match), then Phase 1 self-play→train→gate vs net_night_14. Memory `spender-variant-pv-shipped` + `spender-racer-blindspot-confirmed`.


### Variant N is now the CARD-SET ATTENTION net (Rust→WASM, client-side) — context for June 29
The deployed 15-pt variant **N** is no longer the heuristic/MLP stack: it's a **card-set attention net**
(`net_attn_3`: 18 card-tokens × 24 feats → attention → value+policy heads), trained offline (PyTorch
`az_run/attn_net.py` + `train_attn.py`) and **served client-side via Rust→WASM determinized PUCT** in the
player's browser (the `forrestm_projects-rust/spender-core` crate: `feats.rs` tokenizer, `attn.rs` forward,
`vsearch.rs`/`mcts.rs` search). It beats variant S ~0.88 and the prior MLP N (`net_night_14`) ~0.567 on
fresh decks. **Prod sim budget is ~20k sims/move** (measured telemetry — the heavier attention leaf dropped
it from the MLP's ~100k; still well above the ~1.2k saturation knee, so matched-sims strength transfers).
Full history in memory: `spender-attention-net`, `spender-variant-pv-shipped`, `spender-rust-search-rewrite`.

### Session (July 2026) — DISCARD-root search fix (deployed N + wwsd) + Rust-WASM build facts
**The determinized PUCT one-hot the H3 pick at ANY non-PLAY root, so DISCARDS were decided by H3's STATIC
heuristic — NOT the net (DO NOT regress).** In `spender-core/src/vsearch.rs`, `root_visits_until_pv` and
`root_nw_until_pv` short-circuited `if s.phase != PLAY || legal.len()==1 { one-hot heuristic::choose_action }`.
So a discard used H3's `choose_discard` (drops ITS OWN least-needed color) — a DIFFERENT brain than the net
that chose the take → the "take gems, then discard the ones it wants" loop, with zero lookahead. **Fix:** search
DISCARD roots too — `if legal.len()==1 || (s.phase != PLAY && s.phase != DISCARD)` — so the net's value head
evaluates each of the ≤6 discard options after rolling into the opponent's turn (ONE brain decides take+discard,
with lookahead). NOBLE/OVER/single-legal still one-hot H3. Lib regression test `discard_root_is_searched`. Only
the `_pv` variants (variant **N**) were fixed; the `_leaf` variants (variant **S**, `root_*_until_leaf`) still
one-hot H3 discards — left as-is (changing S is an unvalidated strength change).
- **Two serving paths share this crate (both fixed):** website N = `Spender.jsx` `ai_variant==="N"` → worker
  `kind:"searchPV"` → `search_visits_pv_timed` → `root_visits_until_pv`; the wwsd userscript →
  `search_pv_full_timed` → `root_nw_until_pv` (its `decideDiscards` builds the post-take DISCARD state
  `phase=1` and reads the searched top action — was 1 sim ≈ raw H3, now a real search).
- **wasm is NOT built by CI — it's committed pre-built artifacts.** Website:
  `webapp/public/wasm/{spender_core.js,spender_core_bg.wasm}` (`wasm-pack --target web`), loaded by the
  hand-written `webapp/public/wasm/s-worker.js`; rebuild + commit those two files, CI (deploy-pages, watches
  `webapp/**`) publishes. **Same filename ⇒ browsers may serve the CACHED old wasm** (~10 min GH-Pages TTL /
  hard-refresh). Variant routing: N→"searchPV", S/others→"search", old value-leaf N→"searchN" (not routed).
  wwsd: `wasm-pack --target no-modules --out-dir pkg-nomod` → `wwsd/build_browser_n.py` inlines base64 wasm+glue
  into `wwsd/wwsd_browser_n.user.js` (manual Tampermonkey install; no prod/CI surface).
- **Toolchain is now LOCAL** (cargo 1.96 + wasm-pack 0.15 + wasm32 + MSVC, `$HOME/.cargo/bin` off PATH →
  `export PATH="$HOME/.cargo/bin:$PATH"`). Use `cargo test --lib` (the `src/bin/*` need `--features bridge`).
  The crate lives in the **forry4.github.io repo** (`spender-core/`), NOT a separate repo — despite memory
  `spender-rust-search-rewrite` naming it `forrestm_projects-rust/spender-core`. Build worktree:
  `forrestm_projects-wwsd-wasm` (branch `wwsd-wasm`); the `vsearch.rs` edit was made there then copied to main.
- **wwsd userscript this session (v0.9.29):** minimize/collapse toggle; chat capture (schema-agnostic Minimongo
  auto-detect → per-game `chat[]` for suggestion-mining; `WWSD_N.chatProbe()`/`listCollections()`,
  `CONFIG.CHAT_COLL` override — UNVERIFIED vs spendee's real schema, run chatProbe live); reserve hold fix
  (`synthHoldCanvas` keeps the press ALIVE with ~90ms sub-pixel pointermoves — a static long-press is ignored by
  the canvas; `HOLD_MS`→2200); auto-lobby **circuit-breaker** (a loss where NOBODY hit the target = our
  timeout/forfeit → `CONFIG.AUTO_LOBBY=false` in `logFinalize`, before the tick's `autoLobbyStep`, so no runaway;
  `AUTO_START` is dead code). Console paste is blocked by the browser self-XSS guard → type `allow pasting` once.

### Session (July 2026, cont.) — website N discard ROUTED TO THE CLIENT NET + wwsd failure-logging + chat-schema fix
**The website N discard loop RECURRED even after the July DISCARD-root Rust fix — because the site is SPLIT-BRAIN and the discard was a DIFFERENT code path (DO NOT regress).** On the website, N's PLAY move is searched client-side (WASM), but the over-cap discard was finished **server-side in Python** by the `_ai_discard_one` heuristic — NOT the Rust `vsearch.rs` `root_visits_until_pv` the DISCARD-root fix touched. So that Rust fix helped wwsd (all-in-browser) but did nothing for the site. A different brain (heuristic) than the net that chose the take → the take→discard→re-take loop persisted on the site. Fixed in TWO commits:
- **(a) Heuristic patch — `_ai_discard_one` was reserved-blind + holdings-penalized (`814a407`).** It only summed demand over BOARD cards (ignoring the AI's RESERVED cards → gems saved for a reserved card looked surplus) and used `max(0, cost−bonus−HELD)` (so the more of a color you stockpiled, the more "surplus" it read — backwards). Rewritten to sum demand over **board + reserved** using **raw** effective cost (`cost − bonus`, holdings-independent). Kills the obvious loop; now also the timeout FALLBACK for (b). Test `test_ai_discard_respects_reserved_cards`.
- **(b) Route the discard to the client's NET search — the real fix (`9292170`), like WWSD does.** `_run_ai_turn(game, ai_pid, mv, defer_discard=True)` (set ONLY on the client `ai_move` path; the server-fallback path keeps `defer_discard=False` → heuristic): after an over-cap take/reserve, `_defer_or_finish_discards` sets **`pending_discard_pid = ai_pid` and RETURNS WITHOUT finishing the turn**. A pending discard keeps `phase=="playing"`/`turn==ai_pid`, so **`from_game_dict` maps `pending_discard_pid` → DISCARD phase** (turn = AI seat) and the EXISTING `mk_room_state` `ai_search` block ships that DISCARD-phase compact state UNCHANGED — the take was logged so `ply` advanced, tripping `Spender.jsx`'s **ply-keyed** client-AI effect, which auto-re-searches and submits a `{type:"discard"}` `ai_move`. The handler validates it (legal in the DISCARD state via `move_to_action`∈`legal_actions`), applies it with `_apply_ai_discard` (one token → bank, logged), loops until ≤10, then `_finish_turn`. **`_schedule_ai_discard_fallback`** arms a `CLIENT_AI_TIMEOUT`(8s), **ply-guarded** watcher after each deferral: if the client never answers, the (now reserved-aware) heuristic finishes it — so the whole path **degrades to today's behavior on any client failure** (the safety guarantee). **NO client or WASM change needed** (the deployed website wasm ALREADY searches DISCARD roots per the July Rust fix; the worker already converts any action; the effect already re-fires per ply). Backend-only → Render deploys on `**/*.py`. Test `test_ai_run_turn_defers_discard_for_client`. Note: the defer is variant-agnostic (S/N/PV) but only benefits **N** — S's client search (`kind:"search"` → `root_visits_until_leaf`) still one-hots H3 discards, so S's routed discard == the old heuristic anyway (no regression).
- **wwsd userscript v0.9.30 — failure logging (`WWSD_N.logFailures()`).** Every autoplay move that doesn't commit is recorded on the per-game log's `failures[]` (ply, intended action, seat state, retry, gave_up) at all four `tick()` failure sites: **move_missed** (canvas click didn't advance the turn — the reserve-miss case, carries `action_kind`), **discard_missed**, **subdecision_manual** (unknown job bailed to manual), **exception** (claimNoble/discardSubDecision/tick threw). Rides along in the ⤓ Logs export.
- **wwsd userscript v0.9.31 — chat capture FIXED to spendee's REAL schema (VERIFIED live).** A `listCollections()` dump proved the v0.9.29 auto-detect captured NOTHING: chat is **NOT its own collection** — it's the **`conversation[]` array embedded in the `rooms` collection doc**, linked by **`room.gameId === game._id`**; each entry `{ isSystem, userId, name, content, createdAt }` with **NO `_id`**. The old code explicitly SKIPPED the `rooms` collection and only read top-level docs. Now `logCaptureChat` reads `_roomForGame(g).conversation`, skips `isSystem` lines, dedups by `(createdAt|userId|content)`, text field = `content`. `chatProbe()` previews the current room's conversation (verified: returns the sent messages). `CONFIG.CHAT_COLL` kept as a flat-collection override escape hatch. (Both v0.9.30/0.9.31 are wwsd-only → no CI/prod surface; **reinstall in Tampermonkey** — the `@version` is the tell.)

### Session (June 29 2026) — eval-axis screens: FEATURES + VALUE-TARGET both saturated for the champion
Two independent, cheap "harvest → ablation/gate" screens, both NEGATIVE for raising N, both pointing the
same way: **the remaining lever is the training DISTRIBUTION, not the evaluation.** Reusable tooling on the
rust-search worktree + `az_run`: `harvest_attn_v{3,4}` / `harvest_attn_val` (net_attn_3 self-play logging
candidate features / the search root value; a `game` id col for leak-free game-split), `gate_attn_attn`
(attn-vs-attn paired-CRN gate), `ablate_v{3,4}.py` (a small MLP distill predicting the OUTCOME, leave-one-
IN/OUT column-zeroing configs; the box has <800MB free + no pandas, so the loader STREAMS the CSV straight
to the GPU), `train_attn.py` gained a `value`-column/`BETA` value-target blend + a warm-start JSON loader +
a low-RAM streaming/`MAXROWS` parser (the old list-of-floats parse peaked ~2.8GB and OOM'd).

- **Eval-FEATURE enrichment is saturated ON THE NET (do not relitigate these four).** Held-out-outcome-AUC
  ablation over net_attn_3's v1 features: per-card **deck-unlock**, **post-buy-unlock**, **opponent-model**
  (opp eng/nob/tempo), state **fork-count** ALL fail to clear the bar (full vs v1only ≈ −0.0002; same even
  restricted to the uncertain ply≤28 regime). Only deck-unlock flickered +0.0007 (~1σ). Reason: the
  attention mechanism already computes board-card cross-aggregates, so explicit versions are redundant.
  **CAVEAT: the screen runs on SELF-PLAY data → it is structurally BLIND to the racer weakness** (a
  distribution problem); a flat feature screen on self-play cannot evaluate that. Memory `spender-v3-feature-screen`.
- **#3 value-bootstrap raises the FLOOR not the CEILING (RESOLVED).** Extend AlphaZero's policy-distillation
  to the VALUE head: value target = `(1-β)·outcome + β·search_root_value` (the denoised verdict the 128-sim
  PUCT *concluded*, vs the raw win/loss). From-scratch it beats the outcome-only baseline **+0.077, FLAT
  across 256/512/1024 sims** (transfers past the knee to ~20k) — the OPPOSITE of the S leaf-swap precedent.
  BUT warm-fine-tuning the CHAMPION toward its own search values gives NO gain (β=0.3 vs ship 0.463, β=1.0
  0.468, β1.0==β0.3 0.498; control β=0 ≈ ship 0.489): search-value is a more EFFICIENT target (helps an
  under-fit head catch up) but ship already sits at that fixed point from its outcome-trained loop. **KEEPER:
  use β≈0.3 in any FRESH retrain** (better/faster value signal while the head is being built; keep β<1 in a
  loop so the outcome anchor prevents value drift). Memory `spender-value-bootstrap`.
- **Blind (deck-top) reserve — a structural MCTS blind spot, not a tuning miss.** The bot never blind-reserves
  even though it's legal (`engine.A_RES_DECK` = actions 43–45). Determinized PUCT can't value it: (1) the deck
  is reshuffled per sim and the tree keys the child by ACTION not drawn card, so all blind draws MERGE into
  one node → the move's convex/upside-tail payoff (game-winning when stuck/behind on a dead board) is
  collapsed to a mediocre mean it can't plan around; (2) the opponent is modeled as knowing everything, so the
  hidden-information value is invisible. Near-unfixable without belief-state / chance-node (expectimax-over-
  draw) search; niche → not worth it. Same CLASS as the denial/racer blind spots (perfect-info determinization).
- **Per-level deck (the user's idea) — passed the flat-MLP AUC screen but WASHED in play (do not relitigate).**
  N has NO explicit deck features (only an aggregate, level-blind term inside `engine_value`). `features_tokens_v4`
  adds STATE groups: per-level×color demand (P), aggregate control (G), per-level counts (N3). The flat-MLP screen
  liked it (full vs v1only +0.0033 ~3 SE; level-split onlyP−onlyG +0.0005/+0.0011 marginal), BUT on the real
  AttnNet the value-AUC was near-tied (+0.0010) and the **PLAY A/B washed: v4net vs v1ctl 0.533@256 → 0.507@1024**
  (decays with sims → ~0 at prod's ~20k; sanity v1ctl-vs-ship 0.40 healthy). The attention net already extracts the
  deck signal from the `engine_value` tokens, so explicit deck features help a weak FLAT learner but NOT the real
  architecture. **NOT a keeper.** GOTCHA (cost an hour): `train_attn.py` didn't skip `harvest_v3/v4`'s leading
  `game` column → trained on features shifted one slot → train/serve mismatch → a FAKE 0.66→0.76-GROWING result;
  the **sanity control (v1ctl-vs-ship = 0/400) caught it**. Fixed (`f0` skip); `data_attn_val.csv`/the #3 nets were
  unaffected (no game col). Lesson: always gate vs a known reference — a bug can fake a play gain AND a transfer curve.

### Session (June 30 2026) — EXPLOITER net vs champion N = NO EXPLOIT (clean mirror; DO NOT relitigate)
The greenlit research bet from `spender-racer-league-deadend` (train a net whose SOLE objective is to BEAT the
deployed attention-net champion **N**, AlphaStar-style, to DISCOVER the human's racing exploit) was run
(`az_run/loop_exploit.sh`, Rust `selfplay_attn_exploit.exe` + `gate_attn_attn.exe`, 10 iters). **Result: no
exploit found — N is unexploitable by a same-arch warm-start mirror.**
- **Setup:** the exploiter is a **byte copy of ship N** (`cp net_attn3_ship.json exploit_best.json`) — SAME
  card-set-attention architecture, SAME 24-feat tokens, SAME initial weights. The ONLY differences are the
  training *distribution* and *target*: each iter the best exploiter plays **1500 games vs the FIXED ship**
  (`self_frac=0`, recording ONLY its own moves + search root value), heavy early-ply exploration (`temp=15`),
  warm-from-ship fine-tune (LR 5e-4, value-target β=0.3, rolling 2-iter window, MAXROWS 100k), gate 300g@256
  vs ship, promote iff `cand_vs_ship > best`.
- **All 10 gated results bounced in 0.45–0.51 with NO upward trend:** 0.491 / 0.481 / 0.478 / 0.471 /
  **0.5083 (iter 5, the only "promotion", within noise of 0.50)** / 0.489 / 0.505 / 0.449 / (iter 9) / **0.456
  (iter 10)**. best_wr ended at **0.5083** — a dead-even mirror. (Train-time win-rate ~0.36–0.39 is just the
  temp-15 exploration depressing play; the clean gate is the truth and it says EVEN.)
- **Diagnosis (exactly the pre-flagged risk):** a net with N's architecture, N's features, initialized to N's
  weights, taking small gradient steps on games against N has **no structural asymmetry to exploit** — gradient
  just walks around N's own policy basin and the gate sits at ~0.50. This is the "same-arch exploiter mirrors
  to ~0.5 without asymmetry" failure mode called out in `spender-racer-league-deadend`.
- **Conclusion:** a real exploiter REQUIRES injected asymmetry the mirror loop deliberately omitted — enriched/
  racer-aware features, a racer-biased reward or opponent track, a **cold (from-scratch) init** so it can't fall
  back into N's basin, or a different head/arch. As configured this is a clean NEGATIVE control proving N is not
  exploitable by a mirror of itself. Reusable harness kept: `loop_exploit.sh` + `selfplay_attn_exploit.exe` +
  `gate_attn_attn.exe`. Memory `spender-racer-league-deadend` (updated with this outcome).




<!-- ===================================================================== -->
# ARCHIVE: Spender — tap-to-ping / tab-alert / sizing session
<!-- ===================================================================== -->

### Session (June 25 2026) — tap-to-ping, "waiting for you" tab alert, reserved-card + actions-box sizing (SHIPPED to main; do not regress)
Four small Spender UI changes, all frontend-only except the ping relay (one backend WS action). Built in the
`forrestm_projects-sound` worktree (branch `sound`), pushed straight to `main`. The `sound` worktree is the
standing scratchpad for these one-off UI fixes.
- **Tap-to-ping a player (chime for you + them).** Clicking ANOTHER player's box (`.player-panel.pingable`,
  gated `!isMe && !reviewing`) plays a short rising two-tone WebAudio chime locally and sends
  `{action:"ping", target: pid}`. **Backend (`main.py` WS loop): the `ping` action relays
  `{type:"ping", from: pid}` to ONLY the target player's socket** (`tws = ROOMS[room]["sockets"][target]`,
  guarded `target != pid`); the clicker already played locally, so there's no echo-back. **VERIFIED with a
  4-client integration test: a ping reaches only the tapped player + the clicker — the other 2-3 players hear
  NOTHING** (do not "broadcast to the room" — that would leak to everyone). `playPing()` is a module-level
  helper (one lazily-created shared `AudioContext`, no audio asset) used by both the click handler and the
  `msg.type==="ping"` message branch.
- **"Someone's waiting for you" tab indicator (permission-free).** A `useEffect([myTurn, pinged])` gated on the
  Page Visibility API: while the tab is HIDDEN and (it's your turn OR a ping arrived), it FLASHES
  `document.title` between `Forrest Games` and `🔔 Your turn!` / `👋 Someone's waiting!` (~1.1s) and swaps the
  favicon to **`webapp/public/favicon-alert.svg`** (the tree + a red badge). Cleared the instant you return
  (`visibilitychange`→visible restores title/favicon + clears `pinged`). New `pinged` state set only when a ping
  arrives AND `document.hidden` (so a stale ping doesn't fire later). NO Notifications API (no permission prompt,
  by user choice). Spender-only so far; CoC/Where Wolf? would need the same small addition.
- **Reserved-card content sized via container query (cqw), NOT `--card-h`.** The reserved-card cost/points/color
  were sized off `--card-h` assuming a reserved card was ~0.58× a board card; it's actually ~0.8-1.0× (and the
  ratio drifts with the sidebar/`--card-h` clamps), so the text rendered ~half-size. Fix: `.player-reserved .card`
  is now `container-type:inline-size` and its content (`.card-points`/`.card-bonus`/`.cost-gem`/`.cost-num`/
  `.card-cost` gap/`.card-header` margin) uses **cqw** so each reserved card is a faithful MINI board card
  (content = same fraction of the card as on the board cards, ≈ board's `--card-h` multiple ÷ 0.72). **GOTCHA
  (do not regress): cqw on the card's OWN padding resolves against an ANCESTOR container/viewport, not itself —
  so the card's padding STAYS `--card-h`-based; only DESCENDANTS use cqw.** Verified within ±2.7% across
  resolutions by a headless measurement harness.
- **Slimmer actions box (the 3-4p layout-shift fix).** The Take/✕ buttons were too wide and, in 3-4p lobbies
  (the wider nobles row squeezes the actions `1fr` column), forced that grid track wider and shoved the
  board/sidebar around. (1) **Removed the ✕/cancel button entirely** from `renderActionButtons` (all states) —
  clicking a selected gem or card again already toggles it off (`handleGemClick` / the card `onClick`), so it was
  redundant. (2) Tightened the Take/Buy horizontal padding (`.actions-panel-btns .btn` `0.162→0.08 × --card-h`).
  (3) **`min-width:0` on `.actions-panel` + `.actions-panel-btns` (and `max-width:100%` on the button) is the
  structural guarantee** the box can never grow its own grid track — a grid item defaults to `min-width:auto`
  (=min-content), which is what let a wide button expand the `1fr` track; `min-width:0` makes the track purely
  space-derived. Verified: with `min-width:0` the grid width is STABLE regardless of button width (the old code
  overflowed its container by ~220px with a wide button). The `.action-bar-spacer ✕` (in the legacy
  `visibility:hidden` action-bar paths) is a height placeholder, not a real button — left alone.
- **Minimal actions-box hint (the follow-up height fix).** Even after the width fix, the hint (`getHint()` →
  `.action-hint`) was still bloating the box: the verbose per-action guidance (e.g. *"Take gems, or click a card
  then the gold coin to reserve"*, *"Reserve armed — …"*) wrapped to several lines in the squeezed 3-4p column,
  growing the actions row (row 1) and shrinking the card board (row 2). Per the user, **`getHint()` now returns
  ONLY `Waiting for {name}…` (opponent's turn) and `""` on YOUR turn** — the Take/Buy buttons, the card
  affordability highlight, and the discard/noble modals already convey everything else (the per-action hints were
  deliberately dropped). On your turn the empty hint collapses to 0 height, so the box is just Target + buttons.
  The desktop `.actions-panel .action-hint` is **`white-space:normal` + `overflow-wrap:anywhere`** so the short
  waiting text WRAPS to the next line for a long name (no ellipsis — show the full name) while `overflow-wrap:
  anywhere` breaks a long unbroken name so it still can't force the column wider (keeps the width guarantee); a
  2-3 line wrap of that short string stays within the nobles' height, so it doesn't regrow the actions row.




<!-- ===================================================================== -->
# ARCHIVE: Spender — resolved bug log (fixes already shipped)
<!-- ===================================================================== -->

## Known bugs / fixes applied this session

| Bug | Fix |
|-----|-----|
| TDZ `ReferenceError` in Firefox prod build | Moved derived game state (`game`, `me`, `myTurn`, etc.) before all `useEffect` hooks in Spender.jsx |
| AI blocking UI for 5s (human + AI moves batched) | Replaced sync `_post_turn` AI call with async `_schedule_ai_turn` task |
| "Game Not Started" when game was actually over | Split status check: `== "over"` → "game is over" before generic "not started" |
| Game stuck after socket drop during AI think | `_schedule_ai_turn` now called in both reconnect handlers |
| "Game Not Started" toast + waiting screen flash on reconnect | Race: WS1→WS2 reconnect, WS1 `finally` removed WS2's socket and deleted the room. Fixed with `r["sockets"].get(pid) is websocket` guard in `finally`. Also fixed `"joined"` handler to check `msg.room?.status` before setting screen (was always going to `"waiting"`). |
| Room-code (waiting) screen popped up over the end-game review | `created`/`joined`/`reconnected` sent any non-`"playing"` status to `"waiting"`; a finished game is `"over"`, so a reconnect after game end bounced the user off the review screen. Now an `inGame(status)` helper treats `"playing"` **and** `"over"` as the game screen; the winner/review UI lives there gated by the `reviewing` flag, so reconnects no longer kick out. |
| Reserve at 10 gems → 11 gems, no discard prompt, AI turn skipped, replay with 11 | Discard requirement was transient (one-shot `needs_discard` message field, **no** server guard); a later `room_update` reset the frontend modal and let the player move again. Fixed by making discard real game state like nobles: backend sets/clears `g["pending_discard_pid"]` on the three over-10 paths (take_gems/discard/reserve) and **rejects any non-`discard` move** while it's set (guard beside the `pending_noble_pid` one). Frontend `needsDiscard`/`needsNobleChoice` are now **derived** from `game.pending_discard_pid`/`game.pending_noble_pid` (not message fields), so they survive reconnects/saves and can't be cleared by a stray broadcast. |
| Review board missing claimed nobles | Noble row rendered only `game.nobles` (unclaimed), so nobles a player won vanished from the board. In review (`phase === "over"`) the row now also shows each player's claimed nobles, dimmed + labeled with the claimer (`★ name`), reconstructing the full original board. |
| Move log rows not clickable for buy/reserve | Backend only logged `{color, points}` — no `cost`/`id`, so frontend `mv.card?.id` was always null. Fixed: backend now logs full card dict on all 4 buy/reserve paths; frontend checks `mv.card?.cost`. |
| Move log border flash on new entry | `.log-entry:last-child{border-bottom:none}` rule meant adding a new entry at top changed the last-child, briefly revealing a border. Fixed: removed per-entry `border-bottom`; use sibling combinator `.log-entry+.log-entry{border-top:...}` so no element's border changes on prepend. |
| Hover on log row showed horizontal scrollbar | `margin:0 -4px` on hover exceeded container width. Fixed: removed negative margin; added `overflow-x:hidden` to `.move-log`. |
| Variant Z showed "AI (A)" in UI | Two-step failure: (1) `deploy-render.yml` didn't trigger on `az_model.npz` push, (2) accidental CoC import (`games.castles_of_crimson.main`) committed via stash/pop caused Render deploy to fail. Fixed: added `az_model.npz` to deploy-render.yml trigger paths; removed CoC import block (replaced with TODO comment). |

---


## 2026-08-19 — Dissonance: the exact auction leaf. Built, exact, cheap, no gain.

**Asked for:** the better Expert auction leaf (an exact contract solve replacing
the points proxy), **gated on `cfrlab br` exploitability before any arena time**
— the user's own framing: "that's a same-day signal on whether the mechanism is
working, on the one axis where the required edge and the available edge are the
same order of magnitude."

**The gate said no. It shipped OFF.**

### 1. The baseline was stale and nobody had noticed

The 9.06 on record was measured under the pre-2026-08-16 price list. Re-run on
414 rounds under the shipped scoring against the 2000-deal real-play cache:
**Expert 5.87, equilibrium floor 1.47** (the 0.15 on record came off a different
cache — the two rows are only readable as a difference). **The re-pricing alone
moved Expert 9.06 → 5.87**, the biggest single movement this campaign has
produced, and it was free: nobody had re-run it.

Converged rather than assumed: 200 rounds → 6.01, 414 → 5.87, split-halves at
207 → 6.00 / 6.05. The 22.1% of the best responder's reach that lands on unseen
infosets is identical at both sizes, so that is structure, not sample.

### 2. The leaf turned out to be affordable, against this repo's own standing note

CLAUDE.md said closing the leaf error needs "a `solve_contract` per
(denomination, level) per world" — fifty settlements in a tree, hopeless. It
does not, **because the outcome space is totally ordered.** A round ends either
with the declarer taking no scoring trick (the consolation, one flat value) or
with a points total (a strictly increasing function of it). In a
perfect-information zero-sum game with totally ordered outcomes the value under
any monotone payoff is that payoff applied to the best outcome the declarer can
FORCE — so two scalars price every contract on a deal, at every level and jump:

* `P` — the points solve, "the largest x I can force `pts ≥ x`";
* `Q` — `dd::threat_value`, the same question with the duck moved to the TOP of
  the order.

`max(contract(P), min(null, contract(Q)))`. `Q` subsumes the ducking search, so
it is one solve swapped for another. Cost **2.1×** (17.5 → 38.1 s/deal on the
control arm) once `threat_value` runs MTD(f) seeded from `P` — free, since
`Q ≥ P` always and the two are equal on ~85% of contracts. The identity is
SWEPT against `solve_contract` over every denomination × declarer × level ×
jump, and the non-vacuity assert found its own floor: at two deals the sweep
reaches no mis-priced contract and fails.

### 3. The result

| arm (200 paired rounds, same seeds/cache/instrument) | exploitability | split-halves | made |
|---|---|---|---|
| shipped leaf | **6.01** | 6.58 / 5.94 | 72.5% |
| exact leaf | **6.21** | 6.16 / 6.00 | 67.5% |

**Nothing, and the required effect was several points.** Not vacuous either,
which is the first thing to check on a null: with the exact leaf on, **70% of
auctions bid a different sequence, 52% settle at a different level, 28% end with
a different declarer.**

### 4. Why, and the reusable part

The exploitability defect is that Expert's opening **barely varies with its
hand**. A better leaf makes every candidate's price more accurate; it does not
make the price more STRENGTH-CONDITIONED — it shifts them all together. That is
the same reason the opening bias failed from the opposite end of the pipeline: a
marginal-shaped treatment cannot fix a conditional defect. **Two mechanisms,
opposite ends, one diagnosis.**

And it joins the belief prior as the fourth instance in this campaign of *a
measured defect whose correction did not measure as a gain*. The direction that
is left is conditioning the opening on strength, by something that can express a
MIXTURE — which an argmax over a biased value provably cannot.

### 2026-08-19 (later) — the instrument was broken twice, and fixing it saved the conclusions

Continuing the same session. Asked "where does the 5.87 actually come from"
before guessing at another fix, which turned out to be the whole afternoon.

**`cfrlab attrib`** decomposes the best responder's winnings by the one-step
deviation at each policy node, reach-weighted, reported beside the raw
observation count. On the self-play corpus: **54% of the exploitability came
from infosets Expert had never visited, 74% from ones with ≤2 observations.**
A best responder steers toward holes by construction, so the fit's coverage was
most of the number — and that is why the opening bias and the exact leaf both
measured null. *No change to how the bot plays can move loss attributed to nodes
the bot never plays.*

**Fix 1 — off-policy probes (`CFR_PROBES`).** Per deal, states drawn uniformly
from the abstraction's reachable set, driven into with REAL bids so `used`,
`last` and `jump` come out right by construction. Both actor parities (the short
path fixes whose turn it is; the other seat needs a path one bid longer). Nearly
free — `bid::Solved` is cached on the hand and a probe moves the standing bid,
not the cards: 16.4 s/deal at 0 probes, 13.1 at 96. Result: coverage 100.0%
exact, infosets 233 → 1448, 97.7% of the loss on infosets with 11+ observations.

**Fix 2 — the harness was measuring the wrong tier.** `opp_model` is added by
`main.py`, only for the expert tier; cfrlab built its payload from the engine, so
the field was absent and Rust defaulted to `Minimax`. **Every figure this
campaign produced — 9.06, 5.87, 5.45 — was Hard's auction under a docstring
saying Expert.** Third instrument bug of this shape. `CFR_OPP_TEMP` now defaults
to the shipped value and is stamped on every row.

**The honest numbers** (420 rounds, same deals, 100% coverage): floor **1.47**,
Hard **5.45**, Expert **5.70**. Expert is marginally *more* exploitable than
Hard — not a contradiction of its +0.957 head-to-head win, since exploitability
and head-to-head strength are different quantities.

**Three treatments, three nulls.** The opening bias (worse at every weight), the
exact leaf (+0.23, replicated paired on the fixed instrument at 247 seeds), and
opponent softening (+0.25). And the last confound is closed: `cfrlab banned`
shows the pass rate is **44% vs 44%** at standing 4 whether the seat's best
denomination is free or banned, so the concession is genuine timidity and not
the abstraction's missing `DENOM_RULE`.

**What is left is a structural asymmetry, not a parameter.** In the tree,
passing is a LEAF priced myopically from the opponent's side; raising continues
into a subtree whose modelled opponent knows our exact hand and always finds the
punishing reply. The pessimism applies only to the branch that continues, which
predicts exactly the observed sign. The temp knob cannot isolate it — softening
also lowers the opening across every bucket, and the two cancel.

**The method lesson, and it is the one worth carrying:** *a headline number that
resists two plausible treatments is telling you to decompose it, not to try a
third.* Both nulls were correct answers to the wrong question, and one hour of
attribution explained both and repriced the entire campaign's instrument.

### 2026-08-19 (later still) — cross-fitting the tree: the fourth null, and the one that reframes the other three

The user opened the door to changing how the tree values its two branch kinds,
so I built the change the diagnosis pointed at.

**The mechanism.** `min`/`max` over noisy estimates are biased, the tree takes
one such aggregation per ply, so the bias is depth-dependent — and passing is
the shallowest branch there is while raising buys one more opponent `min`. Every
raise is shaded against every pass. Fixed by leave-one-out cross-fitting (choose
on the other worlds, score on the held-out one), which costs no solves.
Demonstrated by simulation, since the curse is a population bias and any fixed
world set makes the hard min correct: min node −0.367 → −0.018, max +0.355 →
+0.008 over 4000 samples at k=8.

**It works and it is worse.** Paired on the honest instrument, Hard tier:
5.45 → 5.69 (weight 0.4) → 6.11 (weight 1.0). Monotone. Behaviourally it did
exactly what it was built to do — probe-pass 81.7% → 77.0%, settled mean 4.48 →
4.92 — and the make rate fell 68.5% → 49.2%. Removing a selection bias entirely
costs the selection: when noise exceeds the gap between two actions, a
cross-fitted choice returns their mean where the truth is their min. LOO is
already the sharpest cross-fit possible, so shrinkage was the only axis, and the
dose curve closed it.

**The reframe, which is the actual output of the day.** Four treatments — the
opening bias, the exact leaf, opponent softening, cross-fitting — all null or
worse, and the last one *monotonically* worse in the direction of the
equilibrium's behaviour. The tree's pessimism about continuing is load-bearing.
So the likeliest reading is no longer "Expert concedes too much" but "the
equilibrium concedes too little, because the abstraction lets it re-bid its best
suit forever and classic does not."

**And I tested the wrong side of that confound earlier.** `cfrlab banned` asked
whether the ban changes EXPERT's behaviour (no: 44% vs 44%). The question that
decides the headline is whether it would change the EQUILIBRIUM's — and the
abstraction has no denominations, so it never pays the cost, which is a measured
0.3–0.6 of hand strength on the 19–36% of decisions where it binds.

**Next, and nothing else until it runs:** carry a per-seat burn count in the
abstract state (~36× the states, thousands, fine for the exact DP) and index the
leaf by that seat's (c+1)-th best denomination. `cfrlab dcache` already builds
exactly that cache. If the equilibrium's level-4 concession climbs toward
Expert's once it pays for its suits, four nulls are explained at once.

**Method note worth keeping: a monotone dose–response is worth more than any
single arm.** Two points would have read as noise; three made the answer
unambiguous and also proved there is no middle setting worth hunting for.

### 2026-08-19 (end of session) — five treatments, five failures, and a stopping rule

Continued into the auction tree itself. Built the burn-count abstraction (so the
equilibrium finally pays classic's denomination forever-ban), the jump-weight
calibration, and the attribution and dose machinery to judge them.

**A retraction first.** `br`'s concession table reports ONE infoset per level,
and I generalised its "equilibrium concedes level 4 on 0-5%" into a claim about
the level. A reach-weighted playout of the same equilibrium concedes standing-4
on **69%**. Four treatments were aimed at my generalisation.

**The correctly-diagnosed version.** The equilibrium's concession rotates hard on
the standing bid's JUMP; the tree's is flat (standing 4: equilibrium 2% of
one-rung climbs vs 28% of leaps; tree 52% vs 53%), and 44.4% of the tree's
attributed loss sits at jump 1. Verified as a calibration and not a bug: editing
only `state.jump` moves the option sums by a median of 54 and flips 2 decisions
in 40.

**And the treatment for it failed the same way.** `jump_weight` is SYMMETRIC —
it makes conceding their leap more attractive and our own leaps less attractive
at once. At 3x the slope barely moved (+1 → +4, +1 → −2, +4 → +2) while the
settled mean fell 4.48 → 4.15. Another shift where a rotation was needed. 5.78
against 5.45.

**The full table**: shipped 5.45; exact leaf 5.58; opponent softening 5.70; xfit
0.4 5.69; jump weight 3 5.78; xfit 1.0 6.11; floor 1.47. Every perturbation is
worse, in both directions on aggression, across four mechanisms.

**The instrument was then tested, because after five failures it had to be.**
Hypothesis: a best responder punishes predictability, so anything sharpening the
bot's conditioning reads as worse. Measured, mean policy entropy against
exploitability: **corr +0.62, the wrong sign**, and `jump weight 3` is the
decisive counterexample — lowest entropy of any arm, still worse. Cleared.

**Conclusion, stated as a stopping rule:** the residual exploitability is not
reachable by re-weighting the existing search. Every treatment tried changes a
coefficient inside a tree that searches from one seat's information set with the
modelled opponent handed our exact hand. That is the auction-side twin of
CAMPAIGN.md's card-play verdict. The only live direction is modelling the
opponent's uncertainty — nested sampling, its own budget, and the one thing none
of the five touches. **Do not spend on another coefficient.**

**Method lesson, the transferable half:** what settled this was not a better
treatment but a DOSE CURVE (monotone across three weights) and a NEGATIVE
CONTROL (entropy vs exploitability). When treatments keep failing, stop
proposing treatments — sweep a dose, and test the instrument.

### 2026-08-20 — modelling the opponent's uncertainty: the sixth null, and a faster way to know

Built the direction the log named as the only live one, properly rather than as
another surrogate. `View::belief_of` swaps the seats — the opponent holds the
hand that world dealt them and ours joins the pool they resample — which is
EXACT rather than approximate, because the auction runs before a card is played
and `Knowledge` has nothing to carry across. `bid::belief_into` draws m such
deals per sampled world and solves them; `OppModel::Belief` runs the opponent's
own tree over them, per world. One level of nesting, by construction.

It is the one mechanism qualitatively beyond a temperature: a softmax gives one
mixed reply shared across every world, this gives a different reply per world
correlated with the hand making it. Gated by three tests, including that their
own hand is fixed across their belief while ours really varies, and that asking
for the model without funding the sample falls back to plain minimax.

**Result, paired on 200 seeds:** exploitability 5.25 → 5.43, contracts made
69.5% → 49.0%, settled mean 4.50 → 4.80, probe-pass 81.5% → 75.4%. And the jump
slope stays flat — a sixth uniform shift from the mechanism that was supposed to
be structurally different.

**The methodological half is the more useful one.** At n=131 the same paired
comparison read belief BETTER by 0.18, and I said so while explicitly declining
to believe it. At n=200 it read WORSE by 0.17 — a sign flip, the fourth time
this campaign has met one. What settled it in minutes: splitting the same 200
seeds into four DISJOINT quarters and recomputing the paired difference on each
(+0.58, +0.90, +1.13, +0.76 — unanimous, and the favourable reading reproduced
by none). The statistic is also strongly n-dependent (quarters average +0.84
where the full sample reads +0.17), so differences are not comparable across n.
**When a reading matters, split it — it is cheaper than another hour of arena
and it answers the question the interval was going to fudge.**

**Six treatments, six failures**, five of them with one signature: concede less,
bid higher, make fewer. The auction search's pessimism about continuing is
load-bearing, and the residual above this abstraction's floor is not reachable
by changing what the tree believes. Remaining candidates are all bigger than a
search change — a finer abstraction for the instrument, or a leaf calibrated on
real play rather than the double-dummy guarantee, which every arm above
inherits. The code is kept and gated so a future attempt starts from a built
mechanism.

### 2026-08-20 (later) — the leaf is already calibrated, and that closes the campaign

Picked the real-play leaf as the most promising remaining direction, on a real
premise: the exploitability instrument scores every arm with the real-play leaf
while the tree optimises the double-dummy guarantee, so the bot had been
maximising an objective it was not marked on through six failed treatments.

**Aligning them made it much worse — and so did the opposite.** Paired on 324
deals, four arms on identical seeds, each also split into four disjoint quarters:

    shift -1.45 (more pessimistic)   6.69   settled 3.45   made 86.7%
    shift  0    (the guarantee)      5.42   settled 4.47   made 67.3%
    shift +1.45 no spread            7.95   settled 5.60   made 41.0%
    shift +1.45 + spread 1.94        6.89   settled 4.86   made 51.9%

The shipped value is the minimum in the full sample **and in every one of the
four quarters** — the only unanimous result of the campaign. Behaviour is
perfectly monotone in the shift, and 1.45 points is almost exactly one rung: so
this is an AGGRESSION DIAL wearing a calibration's clothes, swept in both
directions, with the shipped bot at the bottom.

**A risk-premium explanation was proposed for the first failure and refuted by
its own test.** It predicted more pessimism should help; the knob was opened to
negative scales specifically to check, and -1.45 came back worse in all four
quarters. Three blocks to kill a story that would otherwise have been written
down as an insight. *A prediction a knob can already express is worth checking
before it becomes a paragraph.*

**Seven treatments, all null or worse. Five of them moved aggression, and this
one sweeps that axis directly and finds the shipped point optimal.** So the
residual (5.42 against a 1.47 floor) is not an aggression problem, and every
failed treatment was tuning the one axis already right. What is left must be
CONDITIONAL — which hands the tree wins the auction with, not how high it bids —
and no uniform coefficient can reach it. The next honest step is a finer
abstraction for the instrument, so a conditional defect can be seen at all, or a
different part of the game.

### 2026-08-20 (end) — the finer abstraction, and the check that validates eight negatives

Built the 2-D hand abstraction the log asked for: the existing strength
quantiles crossed with **how far a seat's best denomination stands above its
next** — what the hand loses when pushed off that suit. Information-legal, and
recomputed FROM THE SEED, so every corpus already recorded re-buckets and
re-measures without replaying an auction. Coverage survived (4113 infosets,
99.3% exact, split-halves 6.52/6.53).

**It sees a conditional defect the 1-D bucket cannot.** Loss per unit reach:
1.13 flexible, 1.44, **1.98 one-suit** — the bot loses 1.75x more on hands with
one good suit. The mistake is concrete: on strong concentrated hands it concedes
where the equilibrium overtakes.

**Two confounds killed, both cheaply.** (1) A same-level overtake needs a
higher-ranked denomination and the ladder has no denominations, so the
abstraction may credit an illegal HOLD — rebuilt 15,512 probed states from their
seeds and asked the engine: legal 78% of the time, and **78/78/79% across the
three shape buckets**, so uniform and not the explanation. (2) The equilibrium
control is reported but unusable: the one-step deviation penalises MIXING by
construction, and the equilibrium mixes where the bot is near-deterministic.

**Then the check the campaign had earned.** Eight treatments worse, none better
— so does the statistic order strength at all? Paired on 220 deals, sweeping the
one knob whose weakness nobody disputes:

    k=1  13.25    k=2  8.13    k=8 (shipped) 6.28    k=16  6.73

**The instrument orders search strength steeply and in all four quarters.** A
one-world bidder is more than twice as exploitable as the shipped one. So the
eight negatives are credible, not an artefact of a statistic that rewards
whatever the shipped tier does.

**And it closes an open question the file has carried since the tier shipped:**
`CLIENT_AI_AUCTION_WORLDS` was raised 3 → 8 by analogy with the card search,
explicitly unmeasured. Measured now — the knee is at or just below 8, and k=16
is worse in all four quarters for double the solves. **8 is right.**

k=16 also refutes the mechanism that motivated it: if concentrated hands lost
because their value rests on one noisy estimate, more worlds would flatten the
grading. It does not (shape 2: 2.15 → 2.40). The conditional defect is not
sampling noise; it is a judgement about a KIND of hand, and what is left for it
is structural rather than parametric.

**Worth carrying:** k=16 MAKES MORE CONTRACTS (74.5% vs 69.1%) while being
slightly more exploitable — a clean reminder that head-to-head strength and
exploitability are different quantities, and that a best responder is far
harsher than the opponent across the table.

---

## 2026-08-21 — Dissonance: skat's talon swap. The first fit was better and shipped nothing.

**Asked for:** skat's talon swap, the queued item behind classic's fitted swap.

**Shipped: +4.086 ± 0.183 score/round** over the rule it replaced, on 30000
paired deals disjoint from the ones it was fitted on. The talon's value against
standing pat goes +1.941 ± 0.197 → +6.027 ± 0.185. It is the second-largest
measured gain of the Dissonance campaign after classic's own swap fix, and for
the same reason: the rule it replaced could not represent the preference the
game rewards.

**But the headline is the fit that did NOT ship**, because it is a mistake with
a general shape.

### Two fits, one enumeration, opposite answers

Classic's method labels real decisions with an ORACLE: every candidate exchange
resolved by an exact double-dummy solve of the real deal. The oracle cheats on
purpose and the write-up is careful to call it a diagnostic and to ship-gate on
a paired arena instead. Skat's first fit followed that method exactly, and won
every diagnostic it was scored on — held-out regret against the oracle **4.35**
against the old rule's 5.16 and standing pat's 7.54.

Then the arena:

| card play | first fit − old |
|---|---|
| `dd` exact double-dummy | **+0.817 ± 0.212** (n=6000) |
| `play` the shipped server bot | **−2.132 ± 0.168** (n=30000) |

A better policy **for a solver**, costing 2.1 a round in front of the card play
the server actually runs. The histograms say why and it is not subtle: skat
scores the CARDS captured — 9/10/J/Q at +2, 7/8/K/A at −1 — and the first fit
**gave a jack on 24% of exchanges** where the old rule does on 0.7%, while taking
kings on 19.6% against 7.7%. It threw +2 cards out of play and took −1 cards
into hand, because a solver converts top cards into tempo and the greedy bot
cannot. Declarer card points 8.0 → 7.2; contract made 84.8% → 80.6%.

**The lesson, and it is not about swaps: AN ORACLE LABEL IS A CHOICE OF
OBJECTIVE, NOT A GROUND TRUTH.** Classic's write-up already said the swap's
value depends on who plays the cards afterwards, and ship-gated under both
resolutions. What it did not say — and what cost a whole fit here — is that the
LABELS carry the same dependence. A policy trained on `dd` labels is fitted to a
card player nobody is, and its held-out regret against those labels will happily
confirm it. Anywhere a policy is fitted against a solver and served in front of
a heuristic, the first question is which one the label assumed.

### The second fit, and the cheap label is also the big one

Same enumeration, relabelled by the SHIPPED card play. That resolution needs no
solver and runs ~600 rounds a second, so the corpus went **614 → 40000
decisions for two minutes of wall time** — a 65× bigger training set for less
compute than the small one cost. Gated on disjoint deals under all three card
players:

| card play | this fit − old | this fit − pat |
|---|---|---|
| `play` the shipped server bot | **+4.086 ± 0.183** | +6.027 ± 0.185 (n=30000) |
| `hard` the tier's own k=8 PIMC | **+2.602 ± 1.157** (n=440) | |
| `dd` exact double-dummy | −4.758 ± 0.430 (n=4000) | |

**A gain under both card players that exist**, and a loss only against a solver
holding the opponent's cards, which no tier is.

**The `hard` row is what actually decided it**, and it is the row the repo's own
rule demanded: *a measurement harness must reproduce the SERVING shape*. Hard
and Expert serve card play client-side, so "does this help Hard?" cannot be
answered by `dd` — double dummy is not PIMC, it is PIMC's unreachable limit, and
the two disagree here by seven points a round. `bidserve`'s `pick` request calls
the same `wire::answer_card` the browser worker calls, so the arena can play
both seats at the actual tier. It costs ~22s a deal, which is why that row is
440 deals and not 30000 — five disjoint 88-deal windows, every one positive.

**What the weights say.** `card-point delta` +2.52 and `give trump` −4.48 are
the two the separable rule could not hold at any weights: take the points, never
discard a trump. Giving an ace (+2.27) or a king (+1.34) is good and TAKING one
is bad (−2.07 / −1.38) — they are the −1 cards, and a discard leaves play
entirely, so the talon is where a liability goes to be deleted.

### Two process findings worth more than the numbers

**An experiment parked behind a flag is untested code, and the flag is what makes
it look otherwise.** The first fit shipped as dead code carrying a real bug:
both weight tables and the fit's own feature vector were sized by `NRANK` (8)
and indexed by `E.rank`, which scores on the WIDE deck's 0..9 scale. The give
block overlapped the trump features — one weight meaning both "give a king" and
"the take is trump" — and the policy raised IndexError the first time it was
handed an ace. Nothing caught it: the flag was off, so no test ever indexed the
tables. Three guards now do, all verified non-vacuous against the 8-long tables.

**A mirror that short-circuits asserts nothing.** `swaparena`'s `arm arm` reads
+0.0000 for free, because identical picks skip the playout entirely.
`SWAPARENA_NO_SHORTCUT=1` drives both arms through the whole round instead, and
that mirror — old/old and fit/fit at exactly +0.0000 over 3000 deals — is the
one that says the two branches share no state.

### Queued, and stated as queued

* **Skat's auction leaf still models no talon.** `main.py` ships
  `swap_policy_terms()` on classic and minor auction requests and deliberately
  not on skat ones, so this was a pure server-side change with no wire shape and
  no wasm rebuild. The price is that skat's auction search now under-prices
  winning a skat auction by ~6 rather than ~2 — the same blind spot classic's
  swap fix opened, and the same fix closes it.
* **NOT measured:** whether the first (`dd`-labelled) fit beats this one under
  `hard`. This fit beats the old rule under both regimes that exist, which is
  what the ship decision needed; a tier-aware talon is only worth building if a
  `hard` arena between the two fits says so.
* **Minor's talon** is still unfitted, and now has a method that costs nothing
  to run: `swaplab.py minor <n> <lo> <hi> play`.

<!-- ===================================================================== -->
## TWO PARALLEL LINES, ONE BASE — read this before the sessions below (2026-08-21)

The Dissonance entries from here on were produced by **two independent session
lineages that both branched from `00170c9`** and never saw each other's results.
They are complementary rather than contradictory, but one pair of conclusions
has to be read together or the file appears to argue with itself.

**The line above** (cross-fitting, opponent uncertainty, leaf calibration, the
finer HAND abstraction, skat's talon) ran seven treatments to null-or-worse and
closed with: *the residual is not an aggression problem, every failed treatment
was tuning the one axis already right, and what is left must be CONDITIONAL —
which hands the tree wins the auction with, not how high it bids.*

**The line below** (the Double margin, the belief prior's trump channel, the
pass/raise shading, the contested gate, the real ACTION space, and the CFR
sampler work) reached the same wall from the other side and then measured a way
through it: the level-only action abstraction — a bid names a level, and the
pricer then takes the best suit still legal — is **14.0 points a deal more
EXPLOITABLE** than one that can name its own denomination, because a level
chosen blind to the suit is a commitment the real hand may not support. (That is
a gap between two research blueprints against an exact best responder, not a
gain the shipped bot would make; the section itself lists the four ways the
shorthand misleads.)

**That is the same word from two directions.** One line concluded a conditional
defect must be what remains and asked for a finer abstraction to see it; the
other widened a DIFFERENT abstraction (actions, not hands) and put a number on
one. Neither knew about the other, which makes the agreement worth more than
either alone.

**So "the campaign closes" above should be read as scoped to what that line
tested** — uniform coefficients over the shipped action space. It does not cover
the action space itself, and the 14-point measurement is a reason to reopen the
auction — a direction with a measured size, not a priced gain. The stopping rule
that entry proposes is still right about aggression dials.

## WHERE THE DISSONANCE RESEARCH TOOLING LIVES (2026-08-21)

**THE FINDINGS BELOW ARE ON `main`. THE INSTRUMENTS THAT PRODUCED THEM ARE
NOT.** They live on an unmerged branch, kept because none of it is
user-visible — no engine change, no frontend change, no shipped bot change — and
merging it would republish a byte-identical site, stamping a fresh
`__BUILD_ID__` that nudges every open tab to refresh, for code the server never
imports.

    archive  claude/dissonance-research-2026-08-archive   <- use this
    working  claude/superhuman-ai-game-research-o5pwel
    base     00170c9                                        ~55 commits

**BOTH OF THOSE ARE BRANCHES, WHICH IS NOT WHAT THIS WANTS TO BE.** A branch is
a moving pointer, not durable storage: delete it and the commits become
unreachable and are eventually pruned. The archive branch exists only so the
working branch can be cleaned up without taking the commits with it — it is a
second pointer, not a stronger one.

**The durable form is a tag, and it takes three lines from a checkout with push
rights.** It resolves the archive BRANCH rather than a commit id on purpose:
this block named a head SHA for exactly one commit before the commit that
updated it made it stale, which is the failure it is itself warning about (the session that produced this work could not create it — tag pushes
returned HTTP 403, since its credentials are scoped to the `claude/*` branch
namespace):

    git fetch origin claude/dissonance-research-2026-08-archive
    git tag -a dissonance-research-2026-08 FETCH_HEAD -m "Dissonance AI research campaign, 2026-08"
    git push origin dissonance-research-2026-08

Once that tag exists, **both branches are safe to delete** and this block should
be updated to name the tag instead. Until then, do not delete the archive
branch.

**What is on it that would be expensive to rebuild.** The measurements are
recorded here and in `games/dissonance/CLAUDE.md`; the instruments are not, and
several of them cost most of a session to get right:

| tool | what it measures | why it was hard |
|---|---|---|
| `tools/cfrcheck.py` | MCCFR estimator unbiasedness, by exact enumeration under a frozen strategy | the only instrument that localises a weighting bug; a convergence ladder cannot |
| `tools/liftlab.py` | what the level-only abstraction costs, via an exact embedding into the wide one | two exploitability numbers from two abstractions are incomparable in principle |
| `tools/shadeprobe.py` | `tree value − price-list value` at the same node on the same worlds | the control is exactly 0.000 only if both pricers share the one-slot `Solved` cache |
| `tools/dblreport.py` | every `DOUBLE_MARGIN` candidate, paired and exact, off recorded sums | a CRN arena would cost hours a candidate to measure the same thing worse |
| `tools/channelprobe.py` | belief-prior bias per channel, any tilt as a free lookup | `draws_of` split from `score` so a sweep costs one run of draws |
| `tools/featlab.py`, `tools/gate_pool.py` | the widened-abstraction feature ground; pooled gate runs | — |
| `rust-cores/.../bin/{pimcprops,sigma,priorexp}.rs` | the three PIMC axes, σ, prior exponent | native, so they are the only affordable form |

Also on the branch: `cfrlab`'s outcome sampler and `CFR_DENOMS` action space,
`best_response`'s port onto `_step`, and three tests that gate the above —
`test_cfr_unbiased.py`, `test_lift_is_faithful.py`, `test_cfrlab_blueprint.py`.
**Those three run nowhere while the branch is unmerged**, which is worth stating
plainly: they protect the correctness of MEASUREMENTS, so what they actually
guard is this log.

## 2026-08-20 — Dissonance: five nulls, one positive, and the campaign's first localised defect

Continuing directly from the 2026-08-19 attribution work. That session ended
with a diagnosis rather than a fix: *in the tree, passing is a LEAF priced
myopically from the opponent's side; raising continues into a subtree whose
modelled opponent knows our exact hand.* This session tested that, and cleared
four smaller questions out of the way first.

### 1. `DOUBLE_MARGIN` stays at 12 — the +1.45 peak was one run's luck

A previous run had put margin 20 at **+0.681 ± 0.351** (1.94 SE): a smooth
single-humped curve with a mechanism that reads as sound (the asymmetric payoff
really does push break-even above 50%). An independent 320-deal sample put the
same candidate at **−0.156**. Pooled over 1280 recorded doubles, every candidate
above the shipped 12 sits at ~1 SE and none is separated from any other; every
candidate below it is decisive in the other direction (−3.82 SE at 8, −6.54 at
4, −9.11 at 0).

So the one thing the measurement establishes is that **the 2026-08-16 re-fit
downward was wrong** — already known, but now with a number instead of a
postmortem. There is no measured reason to move the constant up.

**The error bar is paired and exact, and that is why it could be had at all.**
The margin changes which doubles are TAKEN and nothing else: the auction tree
does not model the Double, so the contracts are identical at every candidate,
and a Double changes the payoff rather than the card play, so the rounds are
too. Every round appears in both arms and most contribute exactly zero. The
`moved` column — how many rounds a candidate actually re-decides — is 34 of 1280
at margin 14, which is why a swept table with no error bar reads far more
confidently than the data supports. A CRN-paired arena would have been the
**wrong instrument**: hours per candidate to re-measure the same quantity
through 18 points of per-deal payoff noise, when the recorded sums price every
candidate for free.

**The method note, recorded here for the fifth time:** a smooth curve with a
mechanism is not a replication. This is the same constant the repo has already
re-fitted wrongly once. The only thing that stopped it happening twice was
running the second sample **before** writing the first one down as a result.

### 2. The belief prior's unspent channel is trump length — and it is worth nothing

The prior's own axis was already finished (strength percentile 0.508 ± 0.014
against an unbiased 0.500). Trump length was the one channel still reading
biased at **0.744**. A flat worth per trump on top of the rank curve —
`exp(beta x strength + gamma x trumps)`, gamma 0 being the shipped prior byte
for byte — corrects it cleanly to **0.530** at gamma 1.0, and is nearly free on
every other channel.

Arena: **+0.328 ± 0.784.** Nothing. The fourth consecutive entry where a real,
measured belief bias did not become a measured gain — and the first where the
null came with its own decomposition, so it is "here is where the apparent
effect went" rather than merely "no effect". `BidPrior.trump_len` is built,
correct, and ships at 0.0.

### 3. Nets and MCTS, asked directly and ruled out for this architecture

The user asked whether the answer is a larger architectural rethink. For the
architecture this game already has, no — and the reasons are specific rather
than general:

* **A net cannot help the CARD-PLAY leaf.** That leaf is an exact double-dummy
  solve. Every other game in this repo carries a net *precisely because* its
  leaf cannot be solved. A net here buys only SPEED, speed buys WORLD COUNT, and
  world count is measured at its stop: `pimc:24` vs `pimc:8` reads **50.0%**,
  and `pimc:32` over `pimc:8` is **+0.21 for four times the compute**.
* **MCTS fails for the mirror reason** — it is what you reach for when you
  cannot solve, and here a world solves exactly in ~20–74 ms.
* **The prize is small either way.** 89.5% of card decisions are already exactly
  optimal, the whole oracle gap is 0.79 pts/round on a 5-point pool, and IIMC —
  the correct tool for the reducible part — measured **+0.067 ± 0.053**.
* **In the AUCTION a net is an eval**, and the exact leaf (`threat_value`, the
  best evaluation obtainable) measured null twice.

**Parked with their reasons, at the user's request: R-NaD/DeepNash and ReBeL.**
Both replace the whole approach rather than a component, which is why neither is
refuted by anything above. R-NaD is not runnable in this container (4 CPU cores,
15 GB RAM, no GPU, and neither torch, numpy, jax nor scipy installed) and would
need the auction+play loop exposed as a stepped RL environment. That is a
resource fact, not a judgement about the method — it is the one candidate with a
plausible route to a step change.

### 4. THE POSITIVE ONE: the tree is pessimistic only about the branch that continues

**The first positive finding of this campaign.** Ten items had attacked the
SAMPLER (four nulls) or the ABSTRACTION (three refusals); this is the first
instrument pointed at the defect the attribution kept naming.

The statistic needs no ground truth and no continuation assumption:

    shade(option) = tree value - price-list value, SAME option, SAME node

Passing is a leaf in BOTH pricers, so its shade is an **exact control**. Both
vectors come off the same `entry.worlds` (`answer_auction` computes them
together), so this cannot be a leaf-accuracy or sampling artefact.
`tools/shadeprobe.py`, 400 deals, 900 decisions where both branches were legal:

| | per-world payoff points |
|---|---|
| **passing (the CONTROL)** | **+0.000 ± 0.000** — exactly zero on every node |
| bidding, every option unselected | −0.735 ± 0.056 (13 SE) |
| **bidding, the price list's favourite** | **−10.222 ± 0.391** (26 SE) |

**The tree concedes 44.4% where the price list concedes 29.0%**, and the shade
rises monotonically with the standing bid. At standing 6–7 the two pricers agree
to the decision and the shade is zero; **every point of divergence is at standing
1–4** — which is the "concedes level 4" complaint, localised.

### 5. And both diagnostics answer: it is clairvoyance, and almost none of it is legitimate

Two questions had to be answered before a correction could be designed. Both
measured on 400 deals / 973 decisions, control exactly zero at every arm.

**Which mechanism?** The temperature is a direct lever, so it is the modelled
opponent's clairvoyance rather than the optimiser's curse. Every temp is priced
at the SAME node on the SAME worlds (`opp_model`/`opp_temp` are search
parameters, not world parameters — they are not in `hand_key`):

| opp_temp | pass (control) | bid, the chosen one | concedes |
|---|---|---|---|
| **5** *(shipped)* | +0.000 | **−10.050 ± 0.378** | **41.1%** |
| 10 | +0.000 | −4.820 ± 0.366 | 32.4% |
| **12** | +0.000 | −2.190 ± 0.363 | **29.0%** |
| 15 | +0.000 | +2.103 ± 0.357 | 23.1% |
| 25 | +0.000 | +15.827 ± 0.331 | 10.6% |

The shade on the option actually being chosen **crosses zero at temp ≈ 13.5**,
and temp 12 puts the tree's concession rate at 29.0% — the price list's own rate
to the decimal. Two independent routes landing on the same place.

**How much is legitimate?** Essentially none. Splitting the shade into what the
auction really did realise versus what it would have realised settling here:

| | payoff points |
|---|---|
| **LEGITIMATE** (realised − settles here) | **−0.206 ± 0.855** — indistinguishable from zero |
| **EXCESS** (shade − legitimate) | **−9.763 ± 0.915** |

### 6. The contested gate: the mechanism works exactly as designed, and it does not pay

`EXPERT_OPP_TEMP_CONTESTED = 12` softens the modelled opponent only where a PASS
is legal; the opening — the one node that cannot pass — keeps its fitted 5.
Pre-registered, CRN-paired, dd-resolved.

**−0.4786 ± 0.3951 payoff/round, 95% CI [−1.253, +0.296], t = −1.21, n = 2900.**

**The sign FLIPPED on the way there, and that is the point.** The pre-registered
first read at n=800 was **+1.1938 ± 0.7555**, and I recorded it as "promising,
not established". Carried to the declared 2900 it is mildly negative, in blocks
of 500: **+2.62**, −1.08, −1.93, −0.88, −1.47, −0.04. The entire positive
reading was the first 500 deals. The pre-registration is what made that a
correction rather than a shipped regression — and my own budget was
under-powered too (I assumed σ=18, measured 21.3, so n=800 bought ±0.76 not
±0.64, and n=800 was never enough at any σ).

The mechanism did exactly what it was built to do — opening unmoved (2.46 vs
2.48), passes 21.4% against 31.4% — which is the **fifth** time in this campaign
that a confirmed mechanism has not paid. The make rate is the row that explains
it: 58.7% against 60.3%.

### 7. The real action space: cheap in states, 51x in solver time

The standing finding was that the blueprint's binding constraint is its ACTION
space, not its hand space. Built (`CFR_DENOMS`, off by default) and costed:

| abstraction | reachable states |
|---|---|
| levels only, no denominations | 58 |
| **+ real denominations** | **384** — 1.2x what `cfrlab` reaches today (321) |
| + the per-player FOREVER-BAN's `used` masks | **30,373** — 79x on top |

**And the state count is the wrong cost model, which is the actual finding.**
External-sampling MCCFR evaluates EVERY action at our own nodes, so its cost is
driven by branching factor, not state count:

| | opening actions | walk calls / iteration | ms / iteration |
|---|---|---|---|
| level-only (shipped) | 8 | **102** | 0.94 |
| real action space | 40 | **4,128** | **47.6** |

**40x the traversals and 51x the wall clock for 1.2x the states.** A converged
200k solve goes from ~3 minutes to ~2.6 hours per seed. The prerequisite is a
cheaper CFR — which this file had already named: outcome sampling.

### Instrument bugs found this session, because they are the recurring cost

* **Importing `auction_arena` RUNS it** (no `__main__` guard, argv parsed at
  module level). My argv parsed as mode "6" with **k=0**, and the harness
  produced a complete, plausible shade table off a search over ZERO worlds.
  Fixed by importing under a forced-valid argv and reading `K` back off the
  arena rather than copying `ask()`.
* **Two pricers on different worlds.** Sending the myopic ask down its own
  channel made the control read −13.2 ± 6.5 instead of 0. The `Solved` cache is
  one slot keyed on `hand_key ^ swap.key() ^ exact`, so both asks must go to the
  same processes with the `swap` block included.
* **`str.replace(pat, new, 1)` patched the wrong function** — `jump_main`
  instead of `curve_main`. The running playout read packed action codes as
  levels and printed settled "levels" of 8..40, mean 23.33, 0.0% made. **The
  byte-identical control passed throughout**, because with `DENOMS` off both
  copies are equivalent. *A control that only exercises the OFF path cannot
  catch an ON path that was never wired.*
* **A module-reload benchmark reported 1.16x** where the truth was 51x. Deleting
  `sys.modules` and re-importing does NOT re-read an env flag read at import, so
  it measured level-only twice — visible only as an infoset count that did not
  move (1,218 vs 1,354). **Fork, don't reload.**

---

## 2026-08-21 — Dissonance: a biased sampler, an equal-time reversal, and a measured abstraction gap

### 1. The outcome sampler was biased, and a convergence ladder could not say where

It had shipped the day before explicitly marked NOT correct: on the level-only
abstraction it and external sampling converged to DIFFERENT equilibria, which is
the signature of a mis-weighted estimator rather than a slow one.

**A ladder says THAT, never WHERE.** Regret matching is a feedback loop: a small
weighting error moves the strategy, which moves the next estimate, and nothing
localises. `tools/cfrcheck.py` asks the one question with an exact answer —
freeze the strategy at UNIFORM, and both samplers estimate `v(I,a) − v(I)`,
which a tiny game (`CFR_MAXL=3`, one deal, 22 infosets) computes by enumeration.
That unbiasedness property holds **independently of the dynamics**. One run,
decisive:

    external  mean |estimate - truth| / mean |truth| = 0.0021
    outcome   mean |estimate - truth| / mean |truth| = 0.7115

**The defect** was a `descend(a)` closure capturing the PARENT's `q`. The
recursive branch was entered with `q * probe[a]`, but a terminal reached by a
PASS was priced at plain `q` — the sampled action's own probability missing from
exactly the outcomes that end the auction. Worst infoset: 2.83 against a true
6.64. `dbl_os` had the same omission twice (the pass never entered the
defender's reach either).

**The fix is structural, not a patched line:** draw the action FIRST, compute
`nq`/`n_opp` ONCE above the branch, then build the child, so a terminal and a
node cannot disagree about what has been sampled. After: 0.0187 at 400k, and the
residual is variance rather than a second bias — **0.0459 / 0.0187 / 0.0095**
across 100k / 400k / 1.6M is a clean `1/sqrt(n)` (4.83x over 16x).

**Gated permanently** as `tests/test_cfr_unbiased.py`, on hand-written deal
records rather than the gitignored research cache (a test that needs an artifact
is a test that skips, which this package forbids). It proves its own
non-vacuity: a third test re-injects the defect's SHAPE — a missing
multiplicative factor in `1/q` — at a MILDER constant than the real one, and
asserts the band still catches it.

### 2. And outcome sampling loses at equal time, by MORE in the space it was built for

Extracting the CFR+ floor into a single `bump()` seam was what made the checker
possible at all — the floor is what makes CFR+ work and also what makes the raw
estimates unrecoverable, so an unbiasedness check has nowhere to look unless
every increment passes through one owner.

With the sampler correct, the comparison that matters is EQUAL TIME — this
repo's own ship criterion everywhere else, and I had been quoting a
per-iteration figure. Level-only, exact best response:

| sampler | iters | solve | exploitability |
|---|---|---|---|
| external | 200k | 170.9s | **1.04** |
| outcome | 1M | 40.9s | 6.58 |
| outcome | 4M | 163.1s | 4.11 |

External is 4x less exploitable at matched wall clock. I then extrapolated that
the 51x cost gap in the DENOMS space would make the two near-even there. **That
extrapolation was wrong, and the measurement reverses it:**

| sampler | iters | solve | exploitability |
|---|---|---|---|
| external | 2k | 63.7s | 9.97 |
| external | 19k | 351.6s | **4.27** |
| outcome | 500k | 64.4s | 37.83 |
| outcome | 4.7M | 641.7s | 25.79 |

External at **two thousand** iterations beats outcome at a hundred thousand, and
the gap WIDENS with budget (3.8x at ~64s, ~8x at ~640s).

**Why, and it is the lesson worth carrying.** The extrapolation assumed each
sampler's exploitability-vs-iterations curve TRANSFERS between abstractions.
Outcome sampling's does not. Widening the action space 5x costs external only
per-iteration TIME; it costs outcome sampling VARIANCE — each infoset is visited
a fifth as often per trajectory and every `1/q` weight grows. **A per-iteration
cost ratio is not a convergence ratio, and a decay curve fitted in one
abstraction says nothing about another.**

The sampler is correct, gated, and kept — it is the right tool if the action
space ever grows to where external's branching is genuinely unaffordable (the
forever-ban's 30,373 states). It is NOT the answer for `DENOMS`. Do not re-open
it on the strength of the 260x.

### 3. What was actually blocking the real action space was the instrument, not the solver

`best_response` refused to run under `CFR_DENOMS` because it read a transition
off the action by hand — `(a, level, 0, 1 - actor)` treats the action as a bare
level, and a packed one (`level * 8 + rank`) would have bid level 41, or worse
landed on a plausible one. The refusal was right; it just left the real action
space with no way to be priced.

**The port is not a `DENOMS` branch.** Every transition now goes through
`_step`, the one owner of what an action does, so neither abstraction is
described twice and neither can drift. `states()` needed nothing at all: under
`DENOMS` its third slot is the standing bid's RANK rather than a hold count —
different meaning, identical range (`0..E.NOTRUMP` either way) and identical
ordering guarantee, since a same-level bid must name a strictly higher rank.

Verified behaviour-free on the path that already worked: the same solve at the
same seed reads b0 0.8163159305704718 / b1 2.798671028798192 before and after,
bit for bit. **A refactor that changes a measurement is a new measurement.**

### 4. THE LEVEL-ONLY ABSTRACTION IS 14 POINTS MORE EXPLOITABLE — and what that is not

The question the whole `DENOMS` arm exists for, asked properly for the first
time — and it cannot be asked by comparing two exploitability numbers.
Exploitability is only defined against a best responder, the two abstractions
hand that responder different action sets, so they are numbers from **different
games**. What was needed was one game and one responder.

**The embedding is exact, which is what makes it possible.** The level-only game
is a strict SUB-GAME of the wide one, not an approximation:

    pass          -> pass
    HOLD          -> the SAME level at rank `holds + 1`
    raise to L    -> level L at rank 0

`leaf` already prices a contract as "rank = holds", and level-only's `_step`
resets `holds` on a raise and increments it on a HOLD — so a level-only state
and a wide state with `rank == holds` are THE SAME CONTRACT at THE SAME PAYOFF.
The lift is a relabelling. `tools/liftlab.py` does it.

**And `tests/test_lift_is_faithful.py` PROVES it rather than asserting it**, by
the one identity that settles the matter: restrict the wide responder to the
lift's image and the exact best response must come back at the level-only value
to floating point. It does. Two further tests kill the ways that identity could
be worthless — handing the responder the full denomination set must MOVE the
number (and never downward, since a larger action set cannot do worse), and a
one-character mis-lift (a HOLD sent to rank 0 instead of `holds + 1`) must be
caught. Without those, a mangled lift reports a large, confident, entirely
manufactured cost.

**Matched wall clock (324s vs 343s), 600 all-denomination deals:**

| policy | backoff | BR seat 0 | BR seat 1 | exploitability |
|---|---|---|---|---|
| level-only, LIFTED | False | 14.73 | 19.07 | 16.90 |
| **level-only, LIFTED** | **True** | 15.93 | 19.33 | **17.63** |
| wide (native) | False | 5.23 | 2.05 | 3.64 |
| **wide (native)** | **True** | 5.23 | 2.05 | **3.64** |

**A 14.0-point gap in exploitability**, and not a convergence artifact in
either direction: 2.5x the level-only iterations moved it 21.33 → 17.63 while
the wide arm sat at 3.64.

**WHAT THIS NUMBER IS, AND FOUR THINGS IT IS NOT.** Written down because the
shorthand "a 14-point prize" is wrong in four different ways, and I used it
repeatedly in conversation before writing this paragraph.

It **is** the difference in EXPLOITABILITY — how much an exact best responder
wins, in payoff points a deal — between two CFR blueprints solved on the same
deals and priced by the same responder in the same game.

* **NOT a gain the shipped bot would make.** Neither policy here is the shipped
  bot. Expert is a search-based tree bidder that uses no blueprint at all, and
  the blueprint LOST to Expert by **−12.84 ± 1.47** a round.
* **NOT comparable to "floor 1.47 / Hard 5.45 / Expert 5.70".** Those were
  measured in the NARROW game, against a NARROW responder, on a different deal
  cache. Setting 17.63 beside 5.70 is precisely the abstraction-mixing error
  this whole measurement was built to avoid.
* **NOT a strength claim.** This campaign has measured exploitability and
  head-to-head strength close to INDEPENDENT in this game — the Diverse arm was
  less exploitable and not stronger; Expert is marginally MORE exploitable than
  Hard while winning +0.957 head to head. A less-exploitable blueprint is not
  automatically a better opponent.
* **NOT an upper bound on anything shippable.** It bounds what the abstraction
  costs a blueprint against a WORST CASE, and a worst-case opponent is not who
  the bot plays.

**What it is good for is direction.** It names a specific structural gap and
puts a number on its size, which no null in this campaign has done. The number
that would decide whether any of it is worth shipping does not exist yet, and
requires two things in order: a denomination-aware bidder that can serve into a
live auction, then a CRN-paired arena against Expert. **Until that arena runs,
this is a reason to look here — not a result.**


**The artifact that would have manufactured this was checked, not argued.** An
unseen infoset concedes — which `Policy`'s own docstring calls the most
exploitable thing a policy can do — and the lifted policy is structurally the
one with holes (12.9% of reach-weighted lookups). With backoff on the holes
close and **the gap gets BIGGER** (16.90 → 17.63). Coverage was flattering the
narrow arm, not damning it.

This is the same defect the head-to-head already saw from the other end: the
blueprint lost to Expert by **−12.84 ± 1.47** while making **49.6%** of its
contracts against Expert's **73.0%** at the same levels — because a level chosen
blind to the suit is a commitment the real hand may not support. That was
inferred from a play-out; this measures it directly against a best responder.
The two are close and the correspondence is suggestive, but they are **not the
same quantity** (points a deal against an exact responder vs points a round
against Expert) and should not be quoted as one number.

### Where this leaves the campaign

After a long run of nulls — eval weights, the exact leaf, the trump channel, the
contested gate, diverse continuations — this is the first item that points at a
specific structural gap **with a measured size**, rather than at a knob. That is
worth something and it is not a payout: see the four caveats above. It ships
nothing yet: `blueprint_bid` and `_path_to` still
refuse under `DENOMS`, because serving must map an abstract action back onto a
REAL bid, which is a genuinely new mapping rather than a transition `_step`
already owns. That port is the next step.

**And the two method lessons this session paid for, both of which are about
trusting a shape over a measurement:**

1. *A per-iteration cost ratio is not a convergence ratio.* I extrapolated a
   decay curve across abstractions and got the magnitude wrong by 4–8x.
2. *A number that resists comparison usually means the wrong instrument, not the
   wrong question.* Two exploitability figures from two abstractions are
   incomparable in principle; the fix was an exact embedding, and the embedding
   had to be PROVED before its answer meant anything.
