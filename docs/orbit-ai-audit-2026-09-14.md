# Orbit AI audit — 2026-09-14

> **Correction, added when experiment #1 was attempted.** This report is kept as the
> dated record of what the audit concluded, but its #1 rests on a premise that was
> measured and found false, so do not act on that section as written. Measured over
> all 189 logs: exactly 40 carry card identities and **all 40 are Secret Agents
> tables** — 0 are expansion-free, and 32 have one of the ten expansion cards in the
> opening deal. The whole corpus yields **46 expansion-free main actions**, not the
> 100 this report's first measurement asks for, so "use verified base-game positions"
> is not satisfiable from this corpus. Re-scraping does not rescue it either: the
> harvester measured 88 of every 100 BGA Zenith tables running the expansion, which is
> why its Secret Agents filter was removed.
>
> The ten cards were therefore implemented (flag-gated, never served) as a
> prerequisite, and the replay built on top: the forced setup reproduces both opening
> hands on 40 of 40 tables, and the co-walk replays 2 of the 13 undo-free tables end
> to end with the logged winner. See `games/orbit/AGENTS.md` and
> `games/orbit/tools/bga_replay.py` for the current state; the sections below are
> unedited otherwise.


**Recommendation: pause the existing value-only self-play league. Use the archived expert games to teach a cheap action policy, and use Forrest's games to measure and repair strategic development and complete-turn planning.** Keep alpha-beta as the current baseline. A larger network, another blind generation, or a small search-speed optimization is a lower priority than establishing that the bot can learn the strategies it currently loses to.

Audit base: freshly fetched `origin/main`, `8ea07b997378b892677f2d755ebc3fbe81156f3e`, in branch `codex/orbit-ai-audit-20260914`. This report combines source inspection, existing raw arena reports, a read-only production database query, and fresh inspection of the local Zenith corpus. It does not claim a new strength arena or a trained replacement.

## What the human games establish

I retrieved 49 matching Forrest-vs-bot saves, then separated tiers, ladder generations, unfinished games, and abandoned games. An abandoned game awards the bot a winner field without a capture victory; counting it as a competitive win overstates strength.

Among **14 generation-2 Expert games that reached a capture victory, Forrest won 12 and the bot won 2**. The human wins include seven Democratic victories and five Absolute victories: the weakness spans collecting different planets and concentrating on one planet.

Nine of those games completed after the alpha-beta rollout commit's timestamp, 2026-09-13 15:56:18 UTC: **eight human wins, one bot win**. Three other post-commit finished saves were abandons. This is a descriptive sample, not a controlled measurement of alpha-beta: saves do not record the exact browser artifact, worker count, search depth, or fallback status used for each move. At audit time, the live site's version reported the audited commit; its WASM matched the worktree byte-for-byte and its worker matched after line-ending normalization.

All 28 seat histories in the 14 competitive games reconstructed their saved latest observation exactly. The following comparison uses the nine post-commit competitive games and excludes mulligans and effect sub-decisions:

| Main action | Bot: 174 actions | Forrest: 174 actions | Archived corpus: 1,751 aligned actions |
|---|---:|---:|---:|
| Recruit | 108 (62.1%) | 117 (67.2%) | 1,235 (70.5%) |
| Leader | 53 (30.5%) | 19 (10.9%) | 103 (5.9%) |
| Technology | 13 (7.5%) | 38 (21.8%) | 413 (23.6%) |

The corpus has different players, deals, and some expansion games. Its frequencies are **diagnostic comparisons, not target percentages for a bot to copy**. Nevertheless, the same development deficit appears against both sources. Across the nine local games, the bot ended with an average **1.67 technology levels versus Forrest's 5.78**.

Concrete examples:

- **9DGYD:** the bot never took Technology in 24 main actions. It lost to three Mars captures holding 30 Credits and 6 Zenithium, with all technology tracks at zero. Forrest took five Technology actions and finished at level 2 on all three tracks.
- **FYHSU:** the bot spent 10 of 24 main actions on Leader and only one on Technology. Forrest took five Technology actions and won by three Mars captures. Final technology levels summed to 1 for the bot and 6 for Forrest.
- **MSCB0:** a shorter concentration win: three Terra captures by turn 22. The bot used six Leader actions and five Recruits, with no Technology action.
- **B9S2S:** a different-planets win at turn 38. The bot finished with two captured discs and three total technology levels; Forrest had four different discs and six levels.

These observations support **underdevelopment and poor resource conversion as a failure class**. They do not prove every Leader action was wrong or that increasing one technology coefficient fixes it. A useful next benchmark must inspect available alternatives and when the strategic divergence begins, rather than only the final losing turn.

## The biggest new finding: useful expert data already exists

The source is **Board Game Arena's Zenith corpus**, at `C:/Users/Forrest/Zenith_corpus`. The earlier notes generalized the limitations of spectator logs to the entire corpus. That conclusion is false for the archived subset.

Fresh inventory:

- 189 downloaded logs: 51 in the archived-game manifest and 138 in the live index.
- 71 logs contain `gameover`.
- **40 complete archived logs contain `newCards` with actual card identities for both seats.**
- Private `gameStateChange` records include opening `hand_ids` and main-action `cards_id` plus `moves` menus.
- A conservative alignment probe produced **1,751 main actions across all 40 games**. Every chosen card/action matched its preceding private menu, and every hand card ID in those menus was already known from the event stream.

The probe buffers a main action until its end-of-turn `setHandSize`, clears unfinished actions on `undo`, and omits terminal actions that have no refill. This is a coverage result, not full public-state reconstruction or engine legality parity. The recorded menu's cost/availability semantics still need verification before it becomes a training mask.

Of the 1,751 aligned actions, **1,155 have no Secret Agent in the acting hand**. That does not make their whole positions expansion-free: an earlier expansion card may have changed the board or the opposing hand. For the first pilot, use verified base-game positions, or mask and explicitly represent unsupported context; never silently treat an expansion game as the base game.

The scraper enumerated top-ranked players' histories. Its manifest preserved player names, game outcome/rank, and end time, **but discarded the fetched Elo**. A game involving a top player is not proof that both seats qualify. Restore/verify seat-strength provenance before calling every demonstration expert, and keep both winning and losing games from qualified demonstrators. The manifest's `ranks` field is finishing position, not ladder strength.

This dataset is small enough for a quick pilot and rich enough that the old "no hands" objection should no longer block it. No new scraping is necessary to test whether imitation helps.

## Why the training campaign has been slow

The campaign built substantial useful infrastructure: a fast native engine, observation boundaries, rules/parity tests, neural inference, data generation, and paired arenas. However, improvements in infrastructure, value-prediction loss, and within-family win rate were too often treated as progress toward a strong opponent.

The main historical failures are already documented in `ai-research-log.md`:

1. Early per-simulation hidden-world resampling prevented most nodes from being revisited. This was effectively shallow root sampling despite a large simulation count. Coherent trees later delivered a real gain.
2. The original Rust leaf dropped most of the Python evaluator. Repairing the port alone was neutral; repairing it together with the tree enabled progress.
3. The trainer updated on one game's correlated rows at a time. It has since gained cross-game batches.
4. Eight-pair checkpoint scans used different deal sets for different epochs. Selection largely measured noise. Shared deals, wider scans, and head-to-head acceptance now improve this.
5. Parent-relative neural gains did not establish gains against the stronger fixed anchor. The famous g004 `0.8125` was against its previous checkpoint, not Expert.
6. Tiny exploratory screens led to expensive confirmations and repeated narrative reversals. Shared-checkout changes, overlapping jobs, and incomplete-report handling also consumed substantial time.

Representative existing results, with the opponent named:

| Comparison | Paired score | 95% interval | Pairs |
|---|---:|---:|---:|
| Coherent heuristic PUCT vs earlier resampling PUCT | 0.6094 | [0.550, 0.669] | 128 |
| Overnight neural value + policy vs heuristic PUCT Expert | 0.2812 | [0.211, 0.359] | 64 |
| League g004 vs heuristic PUCT Expert | 0.4375 | [0.352, 0.523] | 64 |
| Heuristic leaf + learned policy vs heuristic PUCT Expert | 0.4922 | [0.414, 0.570] | 64 |
| Four-world alpha-beta vs coherent PUCT Expert | 0.6172 | [0.5312, 0.7031] | 64 |
| Pending-choice search vs ranker follow-ups, both alpha-beta | 0.5781 | [0.4922, 0.6641] | 64 |

The final two rows were checked against raw local pool reports. The pending-choice extension was running in the separate AI worktree during this audit; its last complete pooled result remained 64 pairs. It has not established a passing result yet. The comparison also uses the victory-aware ranker in both arms, so it is not an unqualified comparison against today's exact shipped player.

## Current code still has important mismatches

**The ordinary league's "expert" is now an outdated benchmark.** `value_generate.rs:272` invokes PUCT for the Expert teacher. `neural_league.py:_arena_command` adds `--opponent-expert` but never the alpha-beta opponent flag. Thus a new ordinary league run would still generate and evaluate against the previous architecture, although the live Expert uses alpha-beta. Pin benchmark identity to algorithm, settings, and artifact hash; do not let a tier name stand in for them.

The data generator supports opening visit sampling and policy-target recording, but the ordinary league does not pass `--sample-plies` or `--record-policy`, nor does it expose policy-loss training. Those improvements were tested in separate manual runs; their existence is not evidence that the standard league uses them.

**The served search executes only part of its plan.** The current observation omits the remaining pending queue, and `State::from_observation` refuses pending states. The WASM alpha-beta export falls back to the ranker there. In the nine recent human games, **160 of 343 non-forced bot decisions (46.6%) were pending choices** and therefore crossed this refusal boundary in the current implementation. This is structural eligibility, not recorded runtime telemetry. The initial search can reason through a future effect chain in its sampled world, but its chosen continuation is not carried through subsequent live choices.

The shipped `AbConfig` also has `quiescence: false`. Search depth counts individual choices, not completed turns. A reported depth of eight can include several choices by the same player and can end halfway through an effect. Pending reconstruction, execution of the searched continuation, and turn-boundary evaluation are related but distinct problems and should be measured separately.

**The leaf deserves a targeted test on the newly observed development failures.** `state_value_raw` values each technology level at 0.018 and each Credit at 0.025, irrespective of the particular board's next rewards. It has no direct own-column development term; its card term is own hand cost minus the opponent's public column costs. Search can discover some benefits through future actions, so this is not proof of a bug. It is a concrete reason to test whether the planner sees the value of discounts, transfers, and technology thresholds on human positions. This is more specific than an unrestricted weight search.

**One pooling defect remains:** `pool_arena_reports.py:pair_scores` scores a terminal draw as a loss. A two-game draw control returns `[0.0]` instead of `[0.5]`. The eight raw pools checked for the alpha-beta and pending-search results above contained no uncensored draws, so this does not change those cited scores. Fix it before relying on the helper for future results.

## The next experiments, ordered by time to useful evidence

| Priority | Experiment | Cheap first measurement | Decision it answers |
|---|---|---|---|
| 1 | Build a small expert demonstration dataset from the 40 rich archives | Validate 100 diverse decisions end-to-end, including costs, board sides, ownership, and undo; then process the verified subset | Can we learn strategies better than our own weak teachers demonstrate? |
| 2 | Train a compact action classifier/ranker on that dataset | Whole-game holdout: legal-action accuracy, loss, and error classes versus the existing ranker; compare learning curves at 10/20/40 games | Does expert supervision give an immediately useful policy signal? |
| 3 | Turn the 14 reconstructed human games into a fixed diagnostic set | Replay 50–100 varied decisions, emphasizing early development and the turns before tactical losses; report alternatives and complete-turn consequences | Which common mistakes can a candidate actually correct? |
| 4 | Complete-turn planning and pending-choice consistency | Use those same positions to compare current search, searched follow-ups, and turn-boundary leaf evaluation independently | Does the bot execute coherent plans and correctly value multi-step investments? |
| 5 | Repair information handling only if the diagnostic set points there | On identical positions/worlds, separate true-hand advantage, future-draw knowledge, world-vote disagreement, and continuation inconsistency | Is the next limiting factor sampling variance, unjustified foresight, or the evaluator? |

For the policy pilot, start with a small action scorer or the existing policy head; the aim is a cheap proof of learning, not an architecture campaign. Use the acting seat's contemporaneous information only. Opposing hands and future draws may validate a replay but must not enter model inputs. Split by whole game and, where feasible, player; many correlated positions from 40 games are still only 40 independent trajectories.

After the offline pilot, test the learned policy **both directly and as a limited influence on root choices**, then as move ordering with the heuristic leaf retained. Better move ordering alone may only buy speed and cannot correct a systematically bad objective. Keep a no-learning control, and evaluate actual playing strength before interpreting imitation accuracy as a win.

Use cheap position tests to reject no-ops or obvious regressions. A 250ms paired screen can then reject a large loser, with all eight boards represented. The old budget ladder supports that shortcut for its tested neural-vs-PUCT comparison, not universally for a new planner. Recheck finalists at the actual alpha-beta browser budget and worker count, on fresh paired seeds. A small screen cannot resolve a three-point gain.

Treat the existing pending-search run as an already funded experiment; do not duplicate it. A marginal positive result may justify incremental improvement, but it cannot plausibly account for all the human development deficit by itself.

These stages should cost **an initial data/diagnostic implementation session, short model fits, and only then arena time**. Exact wall time depends on replay coverage and available CPU; the extraction probes themselves completed in seconds once written. Avoid another overnight generation before seeing whether a cheap model can improve on the old ranker on held-out expert choices.

## Longer-term direction

The strongest direction is **expert demonstrations → competent policy → search improvement → targeted self-play**, preserving expert and human-counterexample anchors. Search should generate better alternatives in positions where humans expose a weakness, and learning should generalize those alternatives. That is the useful structure of [Expert Iteration](https://arxiv.org/abs/1705.08439), rather than requiring an initially weak value network to discover and evaluate good strategy simultaneously. Its results in another game motivate the experiment; they do not guarantee success in Orbit.

Keep the current heuristic value baseline until a replacement wins a component-controlled comparison. Eventually, expert outcomes and search-improved targets may support a residual value model or a better continuation policy; twelve weak-teacher generations do not establish that all learned evaluation is futile.

Likewise, retire unconditional statements that "hidden information is small" or "throughput is dead." The old saturation result applies to the old PUCT configuration. The later alpha-beta comparison was 0.9609 against PUCT with perfect information and only 0.5625 with one sampled world. That motivates diagnosing information handling, but does not isolate strategy fusion from sampling, future-draw knowledge, or observation-boundary differences. Nor does adding more sampled worlds remove strategy fusion: [Long et al.'s PIMC analysis](https://webdocs.cs.ualberta.ca/~nathanst/papers/pimc.pdf) distinguishes this structural problem from sampling error. Start with measured counterexamples before building ISMCTS, a recurrent belief model, or a full imperfect-information solver.

## Evidence and reproducibility

Fresh local analysis is under `games/orbit/ai/runs/audit-20260914/` in this worktree:

- `fetch_games.py`: bound, read-only Turso query; official Orbit decode boundary; room/auth metadata excluded from saved evidence.
- `analyze_games.py` and `decision-analysis.json`: action/technology summaries, pre-move leaf readings, and 28/28 history reconstruction checks.
- `corpus_hands.py`, `corpus-hands.json`, `corpus_decisions.py`, `corpus-decisions.json`: rich-log inventory and chronological menu alignment.
- `corpus_audit.py` and `corpus-summary.json`: whole-corpus event inventory.
- `live-artifacts.json`: public served-artifact hashes; worker equality additionally checked after CRLF normalization.

These scratch files are gitignored; private game snapshots were not added to the tracked report. Existing arena evidence remains in the original checkout's `games/orbit/ai/runs/` and the separate `forrestm_projects-orbit-ai` worktree. Those are local artifacts, not evidence that a future clean clone can reproduce without the inputs. The report's code locations refer to the pinned audit commit.
