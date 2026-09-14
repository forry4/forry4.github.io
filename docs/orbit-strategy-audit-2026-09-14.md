# Orbit strategic audit — 2026-09-14

The rules/parity branch is now merged into local `main` as `35727dd0`. This
audit uses the 40 rich, parity-verified BGA tables exported by
`bga_policy_probe extract`. They contain 4,092 decisions, of which 1,791 are
main actions (`recruit`, `technology`, or `leader`) after removing mulligans and
effect sub-decisions.

The corpus is useful, but it is not a broad population sample. All 40 rich
tables include the same account, `Fonnonnn`; that player won 38 of the 40.
The comparisons below therefore describe a strong player's successful and
unsuccessful games, not a consensus strategy for all top players. They are
cheap hypotheses to test against fresh deals.

## Signals worth testing

**The opening mulligan is more aggressive.** Winning seats discarded an average
of 2.15 cards versus 1.50 for the losing seats. The winner discarded more in 25
of the 40 paired games, compared with 10 games where the loser discarded more.
The current serving ranker rewards discarding low-cost cards; the demonstrations
discarded a higher average-cost set (3.64 versus 3.08), so a cost-only mulligan
rule is pointed in the wrong direction.

**Development happens early, then turns into board tempo.** In the first four
main actions, 27 of 40 winners took at least one Technology action, versus 18 of
40 losers. Among those early positions where Technology was legal, winners chose
it 37/126 times (29.4%) and losers 22/145 times (15.2%). By the first six main
actions the split was 34 versus 30 games, so the difference is timing rather
than a simple recommendation to develop forever.

The sequence after that investment is also different. After a Technology
action, the next main action was Recruit in 144/194 winner transitions (74.2%)
and 132/209 loser transitions (63.2%). The winning pattern is therefore
“take a useful early development step, then convert it into Agents,” rather
than repeatedly choosing Technology whenever it is available.

**Leader is a situational action.** Winners used Leader for 44/905 main actions
(4.9%); losers used it for 59/886 (6.7%). In the first four actions it was
23/160 (14.4%) for winners and 27/160 (16.9%) for losers. This is a weak but
consistent signal: repeated Leader actions appear to be a fallback when the
player is not converting cards and technology into a race position.

**The current ranker misses the timing signal.** On positions whose entire
legal main-action set is base-game, its chosen move was the demonstrated move
23.3% of the time for winners and 18.4% for losers (top-three coverage was
53.0% and 52.1%). In the fully base-card subset of the first four actions it
ranked Recruit first in 99/99 winner positions and 101/105 loser positions, so
its action prior is effectively “buy a card” and has almost no opening
Technology gate.

## What this means for the next bot experiment

Do not replace Expert with a direct imitation policy. The existing whole-table
probe gives the learned guide a modest held-out top-one advantage over the
serving ranker, but its 32-pair fresh-deal screen was 0.516 [0.422, 0.609],
which is compatible with no strength gain.

The next cheap experiment should keep the current alpha-beta search and leaf
value, and change only the root ordering or first-action prior:

1. Add an opening policy candidate that scores mulligans by hand structure and
   card conversion potential, not card cost alone.
2. Add a bounded early-Technology feature: when a legal technology action
   creates a useful track threshold, prefer it during the first four main
   actions, then sharply reduce that bonus after the setup is paid for.
3. Penalize repeated Leader actions unless the card's faction effect or the
   hand-limit change creates a concrete immediate conversion.
4. Measure those candidates first on the fixed BGA decision set and then in a
   cheap eight-board paired fresh-deal screen. Only a candidate that improves
   both should receive the real browser-budget arena.

This preserves the search's tactical control while testing the strategic
failure mode directly. If the small candidates do not move fresh-deal strength,
the next investigation should be complete-turn planning and pending-choice
consistency, not another network-size or value-weight sweep.

The reproducible extractor is
`games/orbit/tools/bga_policy_probe.py`; the summary command is
`python -m games.orbit.tools.bga_strategy_audit --episodes <episodes.jsonl> --out <report.json>`.
The raw episodes remain local and are not committed.
