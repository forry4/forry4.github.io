# Dissonance — Claude context

> **The AI-research sections below reference tools that are not on `main`** —
> `tools/cfrlab.py`'s solver arms, `cfrcheck`, `liftlab`, `shadeprobe`,
> `dblreport`, `channelprobe`, `featlab` and three Rust bins. They are on branch
> **`claude/dissonance-research-2026-08-archive`**, unmerged on purpose: nothing on it is user-visible. See the head of
> [`docs/ai-research-log.md`](../../docs/ai-research-log.md) for the inventory,
> what each one measures, and the one command that turns that branch into a
> proper tag.

Sixth game. Two-player trick-taking where **taking tricks is not simply good**:
even-numbered tricks score **+2** to whoever wins them, odd-numbered ones
**−1**. Six positive against seven negative, so both players' totals always sum
to exactly **+5** — sweeping all thirteen tricks scores 5, while taking exactly
the six even ones scores 12. The game is about *which* tricks you win.
(FOUR modes: classic, skat — a second auction, and since 2026-08-09 a second
CURRENCY, since skat scores the CARDS captured rather than the trick parity —
**minor**, where even tricks pay **+1** and the pool is **−1**, and since
2026-08-10 **dummy**, a three-seat game between two players off a 40-card deck.
Each has its own section below.)

**Renamed from Oddtrick (2026-08-07)** — the working name is gone from the route
(`/dissonance`), the `MODES` entry, the home card, the package, the Rust crate,
the `.dis-*` CSS prefix and the table. Two things still carry the old name ON
PURPOSE, and a third resolved itself exactly as this section predicted:

* **`odd_pick_card` / `odd_pick_bid` / `odd_best_card` / `odd_pool`** are the
  wasm EXPORT names,
  baked into the artifact's export table. The Rust source keeps them for the
  same reason: source and artifact have to agree, and renaming one without
  rebuilding the other breaks the Hard tier at runtime with an import error.
  Rename them in `src/wasm.rs`, the glue and the worker in ONE commit that also
  ships a fresh `wasm-pack` build, or not at all.
* ~~**`"./oddtrick_bg.js"`**, the wasm's declared import-module key~~ — RESOLVED
  as predicted. It is length-prefixed inside the binary and matched against the
  glue's own object key, never against a filename, so it could only move at a
  rebuild; the Hard auction shipped one and it now reads `"./dissonance_bg.js"`.
  Anything rebuilding this artifact must ship the glue and the `.wasm` from the
  SAME `wasm-pack` run — they are a matched ABI pair, and a mixed pair fails at
  `init()`, which the client-AI path degrades silently from.
* **`main.LEGACY_TABLE`** — prod rows live in `oddtrick_games`, so
  `dissonance_init_db` ADOPTS that table via `ALTER TABLE ... RENAME TO` before
  its own `CREATE TABLE IF NOT EXISTS` can mint an empty one beside it. Guarded
  on old-present-and-new-absent, so it fires once, no-ops on a fresh checkout,
  and never overwrites a live table with a stale one. `tests/test_table_rename.py`
  pins all four cases; the libsql path is untestable locally as always.

There is no `/oddtrick` redirect and no localStorage fallback (deliberate, per
the rename brief): old invite links no longer resolve, and anyone mid-game gets
a fresh reconnect token — they rejoin by room code.

## The reference implementation is Rust, not this Python

`rust-cores/dissonance-core` is the solver-validated source of truth for the
rules. `engine.py` is a hand port of `state.rs`, and **`tests/test_rust_parity.py`
replays 400 fixtures generated there and demands identical results** — two
implementations of the same rules drift silently otherwise.

The fixtures are **committed** (they feed pytest, which CI runs). Regenerate
after any rules change — the default Rust build is now the 32-card v2 game;
the original 28-card game is behind the `rank7` feature:

```
cd rust-cores/dissonance-core
cargo run --release --bin gen_fixtures 400 > ../../games/dissonance/tests/fixtures/play.jsonl
```

That crate also holds the design campaign (`CAMPAIGN.md`) — every scoring rule
below was chosen from measurement, and the negative results are recorded so
nobody re-spends on them.

## Minor mode — the third mode, and the first to touch the trick VALUES (2026-08-09; skat's card scoring, below, was the second and went further)

`mode: "minor"` — even tricks pay **+1** instead of +2 (odd tricks stay −1),
over the CLASSIC auction shape. Same room-flag machinery as skat: one table,
one route, chosen in the create modal, badged on lobby cards. Unlike skat it
changes no phase — a minor round is classic's phase machine (swap, Double and
all) in a different currency.

**Everything follows from the one number, and the map of what it drags along
is `EVEN_TRICK_VALUE`'s docstring.** The pool goes NEGATIVE (6×1 − 7 = −1):
winning every trick scores −1, par is −0.5, and a perfect declarer tops out at
6 — so the ladder compresses to **1..6** (`MINOR_MAX_LEVEL`, asserted derived
from the parity, never typed beside it).

**The re-anchored prices, and why (all measured in
`tools/minor_calibration.py`, bot self-play, 400-600 rounds/config):**
* **make N² + 1/overtrick, set base N** — classic's shapes, unchanged. NOT
  the ±10 flat stake, though (2026-08-11): `FLAT_MAKE_BONUS`/`FLAT_SET_PENALTY`
  are per-mode dicts reading 0 here, because a flat 10 on payoffs a quarter of
  classic's size would drown the contract; if minor wants a stake it needs its
  own calibrated dose.
* **set rate 2, not classic's 5 (`MINOR_SHORT_PENALTY`)** — payoffs run about
  a quarter of classic's (ceiling 36 vs 144) while shortfalls keep the same
  magnitude (median ~2 in both sweeps), so the classic rate made the set the
  biggest number on the table: two-thirds of rounds ended in a set paying ~11
  against makes of 1–6, i.e. "whoever had to open loses". 2 tracks the
  ceiling ratio. The Double applies unchanged, but minor keeps its own flat 2
  a point when doubled -- classic doubles its per-point rate (2026-08-16),
  minor does not, and the shortfall ramp is retired in both.
* **Null 6 (`MINOR_NULL_MAKE`)** — the relationship classic's 12 had (before
  the stake re-anchored classic's Null to 20; minor carries no stake):
  exactly a made level-1's CEILING under the overtrick bonus (1 + 5). The
  cliff this buys is proportionally bigger than classic's (minor makes rarely
  reach their ceiling) — a declarer who bought cheap has an even stronger
  licence to duck. Deliberate, same as classic's documented stance; the rate
  it produces under searching tiers is unmeasured (`skatlab`-class question).
* **match to 25 (`MATCH_TARGET`)** — buys ~7 self-play rounds against
  classic's ~6 under the identical harness. NOT 100 rescaled by feel.

**The mode is structurally DECLARER-HOSTILE, and that is the design, priced:**
even level 1 asks the declarer to beat par by 1.5 points and makes only ~45%
under greedy play (searching tiers do better); level 2 ≈ classic level 5 in
margin terms, because each even trick swung moves the differential by 2 rather
than classic's 4. The server bot's map (`bot._MINOR_LEVEL_NEEDS`) is therefore
COMPRESSED — level 2 fires around p96 of hand strength, 4+ effectively never —
and its settled distribution is ~87% level 1. Rungs 3–6 are sacrifice space,
the role classic's unused 7–12 play. An open question a `skatlab`-class sweep
should answer: with sub-50% make rates, does Hard-vs-Hard converge on "Double
every contract"? (Break-even is around a 45-50% set rate.)

**How the value reaches every consumer — one runtime number, three surfaces:**
* **Python**: `trick_value(t, even)` + `trick_value_in(g, t)`;
  `payoff_terms`/`_terms_for` take the real mode; `pool_for`,
  `max_level_for`. `view_for` ships **`even_val`**; `_deal_snapshot` carries
  **`even`** (the DD review must replay the round's own parity);
  `persist._pack_deal` passes it through generically.
* **Rust**: `State.even` (runtime, default 2). `State::play` scores with it,
  `State::pool()` replaces POOL on every serving-path diff→points conversion
  (`bid.rs`), `dd::key_of` mixes it into the TT key (two parities of one card
  layout are different positions), and — the subtle one — **the MTD(f)
  bounds/parity tables are per-`Dd` state (`ensure_even`), because the
  ladder's stride-2 parity trick is DIFFERENT under minor** (every trick
  swings odd) and classic tables step the ladder right past reachable values.
  `wire.rs` reads `even_val` (view) / `even` (deal), optional, default 2.
  Gates: `solver_matches_brute_force` sweeps the parity like it sweeps Grand;
  fixtures — `play.jsonl` (1 in 4 minor), `views.jsonl` (a minor game),
  `payoff.jsonl` (minor contracts, doubled and not), `auction.jsonl` (minor
  nodes; its `rules.mode` is **"classic"** — the SHAPE — with `max_level` 6,
  so the legality mirror needed no third arm).
* **Expert/Hard auction**: free ride. `auction_payoff_options` and
  `auction_search_payload` are already data; the classic swap-policy weights
  now ride on minor auctions too (`!= "skat"` in main.py — fitted on +2,
  an approximation; minor's own swaplab run is queued with skat's).

**THE STALE-WASM GATE IS A THREE-PART HANDSHAKE, and it exists because an old
artifact reading a minor view would silently search the WRONG GAME** (it
ignores `even_val`, scores +2, returns legal-but-misvalued moves — the exact
shape of the `shown` outage, with nothing red anywhere). Fail-closed:
1. the wasm exports **`odd_wire()` = 2**; the worker probes for the export
   and refuses minor payloads on an artifact without it (per-decision error →
   server bot, the ordinary degradation);
2. the page reports the pool's weakest `wire` in **`client_ai_ready`**;
3. the server refuses to arm a MINOR room for `wire < 2`
   (`_handle_client_ai_ready`) — so an old cached bundle that never sends the
   field plays the server bot, honestly labelled by nothing happening.
Classic and skat rooms accept any vintage, as before. `test_minor.py` pins
the server half; the worker half is the export-table probe.

**Frontend**: trick labels print the VALUE off the wire (`evenVal(game)` /
`view.trick_value`), never a hardcoded "+2" — three sites carried the literal.
`shortRate`/`nullMake` are mode-picked off `/catalog` (which now serves
`even_value`, `pools`, `max_levels`, `minor_null_make`, `minor_short_penalty`,
`match_targets`). The "Doubled · set pays" row had said "+ 4 each" since
before the 4→5 move and the ramp — it now renders rate+ramp from the catalog.
`screens.mjs` drives the create-modal segment to a dealt minor room inside
the `dissonanceSkat` block (same lane, no new roster entry): the marker is
the 1..6 ladder or the "+1 trick" Null price, per who opened.

## Skat scores the CARDS, not the trick number (2026-08-09)

Skat mode's rounds are scored in a different currency from classic/minor: a
completed trick pays its winner the SUM OF ITS TWO CARDS — **9/10/J/Q are +2
each, 7/8/K/A are −1 each** (`CARD_VALUES`) — so a trick is worth **−2, +1 or
+4**, and the trick-number parity means nothing in this mode. 16 cards at +2
against 16 at −1 put the deck at **+16**; six cards sit out, so a round's pool
is `played_pool(g)` = 16 − the out-cards' worth — **deal-dependent (4..22,
measured mean ~14.5)**, never a constant. The design tension the values buy:
the ranks that WIN tricks (K, A) are −1 liabilities — the second player ducks
a 7 under your ace and hands you a −2 trick — while the +2 cards sit in the
middle where they rarely win a trick on their own. The auction, the ladder,
the announcements, Null and all the payoff arithmetic are unchanged; only what
"trick points" MEANS moved.

**How the flag reaches every consumer — the `even_val` pattern, one wire rung
further:**
* **Python**: `card_points` / `uses_card_points` / `played_pool`;
  `apply_play` dispatches on the mode; **`etricks` generalises for free** — a
  "scoring trick" is one with positive value in either currency, which is
  exactly what the Null consolation means (a declarer may freely win −2
  tricks). `view_for` ships **`card_pts`** (+ `card_values` for the board's
  corner chips); `_deal_snapshot` carries **`cards`** — explicit and
  DEFAULT-FALSE on the wire, so a skat round banked before the change reviews
  under the parity it was played at, for free. `pool_for("skat")` returns
  **None** on purpose — a caller assuming a constant must fail loudly.
* **Rust**: `State.cards` (runtime, like `even`). `State::play` sums the two
  cards; `State::pool()` computes pts-banked + in-play worth (correct from any
  position); `completed_trick_value` is the one place both currencies meet and
  is what `nsearch`/`tsearch` read for "scoring trick". **Three solver
  invariants had to move, all in `dd.rs`, all gated by
  `solver_matches_brute_force`'s new card arm:** (1) the MTD(f) ladder's
  stride-2 parity trick DOES NOT EXIST here (−2/+1/+4 mix both parities → step
  by 1); (2) the static bounds are ±4 a trick (`build_bounds_cards`, loose but
  sound); (3) the equivalence collapse may only merge rank-adjacent cards of
  EQUAL WORTH — the 8/9 and Q/K boundaries change every trick they land in,
  and an unguarded merge is a silently wrong VALUE, not a crash. `dd::key_of`
  mixes the flag (bit 42) and `bid::hand_key` mixes it too — same argument as
  the contract-table bug, one cache further out. `tests/engine.rs` also gates
  the per-trick recount and `null_no_even_makeable` against naive recursions
  under cards.
* **The wire is rung 3.** `odd_wire()` = 3; the worker now reads the export's
  VALUE (after init — a wasm-bindgen export throws before the module loads)
  and refuses any payload whose `card_pts`/`cards` it cannot honour; the
  server refuses to arm a SKAT room for `wire < 3`
  (`_handle_client_ai_ready`), exactly minor's three-part handshake at the
  next rung. Classic rooms still accept any vintage. **The artifact was
  rebuilt and committed with this change** (glue + wasm from one `wasm-pack`
  run, export table unchanged); a stale cached wasm degrades skat Hard/Expert
  rooms to the server bot honestly, per decision.
* **Fixtures**: `play.jsonl` — 1 in 4 fixtures card-scored (`"cards":true`),
  with coverage tests on the Python side so a regenerate that dropped them
  fails; `views.jsonl` / `payoff.jsonl` (rows −12..24 for skat — card totals
  range far past the parity pool) / `auction.jsonl` all regenerated.
* **Frontend**: the board gets `.dis-cardpts` and every card renders a
  corner worth-chip that CSS shows only there (colour + glyph, never colour
  alone); the trick line shows the held trick's real value and, mid-trick,
  the led card's "so far"; Null copy reads `nullCond(game)` ("no positive
  trick"); the skat result maths line now prints `short_rate` off the row —
  it had a literal 4 that survived the 4→5 move unnoticed.

**The bots were re-anchored, measured in `tools/skat_calibration.py`** (bot
self-play, 400 rounds, same harness as `minor_calibration`): the play policy's
card branch scores the exact one-trick delta when following (bank the sum /
shed the sum) and leads low keeping +2s back — mirrored in `policy.rs` and
`bot.policy_score` as ever. Bidding runs a card-currency rank curve
(`_SKAT_RANK_VALUE`; best-denomination strength p50 ~14.8, p90 ~16.4) into its
own level map (`_SKAT_LEVEL_NEEDS`), calibrated to: settled levels 2–6
(30/31/22/12/4%), **made 85%** (classic's same-harness figure: 82%), median
overtricks 6, mean winning payoff ~20 → implied match length ~5.0 rounds
against classic's 6.2 on the identical harness. `_KONTRA_TARGET`/`_KONTRA_
STRENGTH` were re-anchored to the new scale but remain GUESSES, as before.
**The old skat match-length medians ("median 11 to 100") describe the parity
game and are stale**; the skatlab-class sweeps queued against skat (talon
policy, announcement rates, Kontra) now also predate the currency and must be
run on it. `skatlab` itself deals `cards = true` and converts through
`State::pool()` since this change, but `skat.rs`'s lab `Decl::payoff` still
pays a flat stake (no overtrick term) — the lab lags the engine there, as it
already did.

## DUMMY mode — a third hand, played by the declarer (2026-08-10)

The fourth mode, and the answer to card scoring measuring as "random, no
control". The diagnosis, which the shelved must-head experiment sharpened: in
a two-hand trick the player NOT taking the trick chooses its payload — you win
with an ace, they slide a 7 under it, and the trick pays −2. Commanding a
SECOND HAND is the direct fix, because it makes you the author of two of a
trick's three cards.

**The shape.** THREE seats of THIRTEEN (7 in hand + three 2-card piles, the
same holding every other mode deals), ONE card out, THIRTEEN tricks of three
cards, card scoring, CLASSIC's auction. Seats 0 and 1 are the players; **seat 2
is the dummy**.
* **Its hand is face up from the deal, to both players.** Shared information
  advantages neither bidder and turns the auction into a judgement about "my
  hand plus that one" against "theirs plus that one".
* **Its outer pile bottoms are hidden from everyone, the declarer included** —
  a fully open dummy makes the endgame a double-dummy problem for both seats.
  The dummy is OPEN, not SOLVED.
* **WHOEVER LEADS THE TRICK PLAYS IT** (`DUMMY_COMMAND = "leader"`, since
  2026-08-10). The first rule gave it to the declarer for the whole round and
  that OVERSHOT, measured: two of three hands plus the lead banked them **69%
  of the pool** before they decided anything. Command now follows the lead, so
  the third hand is a prize fought over rather than a gift — and it carries
  this game's own tension, since winning a trick can cost points and still be
  worth it for the command it buys. Measured: the declarer's share falls
  **0.69 → 0.57** and contracts made fall 73% → 61%. The whole rule lives in
  `side_of`, which `playing_seat`, the trick winner and the next leader all
  derive from.
* **It plays SECOND, always, and never leads** — a trick it takes passes the
  lead to the declarer. Three reasons in order: its card is information in the
  middle of the trick both players react to; the third seat is therefore
  always the real player who did not lead, so the duck-or-take decision stays
  a human one every trick; and it gives the declarer a new move — lead low,
  drop the dummy's +2 on it, and dare the defender to take a fat trick.
* **NO FOLLOW-SUIT** (2026-08-10), the only mode without it, and MEASURED
  against the classic prior rather than in spite of it. The FOLLOWERS were the
  seats with nothing to decide — 2.27 legal cards against a leader's 4.11 —
  and free discard levels that to 4.11 / 4.11 / 4.10, with forced plies
  falling **33% → 13%** and hand-predicts-points doubling **+0.11 → +0.21**
  (classic's own choices-per-decision is 4.07, so this lands exactly there).
  The collapse the classic prior warns of does NOT happen here: the leader
  keeps the lead on 55% of tricks under follow-suit and 50% without it, so
  unwanted tricks do not simply fall to whoever led — because under CARD
  scoring a trick's worth is chosen by the other two seats rather than fixed
  by its number, which is exactly the premise the prior rests on and does not
  hold in this mode. Ducking out does not become free either (Null 3% → 1%).
  Ruffs rise 0.37 → 0.57 a trick, so the denomination you name matters more.
* **No talon.** Two out-cards cannot support showing three, and the declarer's
  prize is the dummy. That also removes skat's Hand/Sharp/Open, which are all
  announcements ABOUT the talon.

**THE WIDE DECK — 40 cards, and the eight new ones are ids 32..39 (2026-08-10).**
Three seats of thirteen is 39 cards and the deck holds 32, so dummy deals the
base 32 plus a **5 and a 6 in each suit**. It went to thirteen because ten was
the mode's biggest remaining problem: at 4 in hand + 6 in piles a seat was 60%
ON RAILS with 2.89 legal cards at a decision and a third of all plies forced
outright, against classic's 46% and 4.07 (`tools/agency_probe.py`). It now
reads **5.59 choices and 9% forced, above classic**, and all three positions
read the same (5.60 / 5.61 / 5.57) — the third seat is not carrying the mean.

* **The layout is the id space, not `suit * 10 + rank`, and that is the whole
  decision.** Renumbering is the obvious way to widen a deck and it would have
  voided every saved classic/skat/minor game, every committed Rust parity
  fixture and the committed wasm artifact, since a card id means a card. Bolting
  the new ranks onto the END keeps every existing id and — the bigger win —
  keeps `suit(c)` and `rank(c)` TOTAL functions of the id. A per-mode
  `suit * nrank + rank` would make a card id mean different cards in different
  modes, and all ~30 call sites across `engine.py`, `bot.py` and the JSX would
  need a mode threaded through them to stay correct.
* **The cost, and it is real: `rank()` no longer returns the id's low bits.** It
  returns a STRENGTH index 0..9 (0 = the 5, 9 = the ace) in every mode, so
  `RANK_NAMES`, `CARD_VALUES` and every rank curve are indexed by strength,
  `beats` is still a plain `>`, and the base deck simply never produces a 0 or
  1. **`E.card_of(suit, rank)` is the inverse and the only correct way to write
  a card down** — `s * NRANK + r` is wrong for the wide deck and wrong for the
  base deck too if `r` came out of `rank()` or `TEN_RANK`. That is not
  hypothetical: it silently turned `TEN_RANK` into a queen and broke five Grand
  tests on the first run.
* **The two new ranks are worth ZERO, and each of the three reasons was
  measured before it was chosen** (`tools/dummy_matrix.py`):
  - the deck total stays **+16** — 4 × (0+0−1−1+2+2+2+2−1−1) — so a wider deck
    does not silently re-scale the ladder the level map keys on;
  - **it breaks the mod-3 granularity.** Every value used to be 2 mod 3, so
    three of them always summed to a multiple of 3: every dummy total was a
    multiple of 3, contracts of 7, 8 and 9 were literally the same contract and
    two thirds of the ladder was duplicate rungs. Reachable totals now run
    every integer from −7 to 18 and the gcd is 1. `dummy_auction_design.py`
    COMPUTES that gcd rather than printing a hardcoded 3, which is how the old
    claim would have survived the fix;
  - it gives the mode a genuinely **safe discard**, which is what free discard
    wants to feed on — a card that neither wins a trick you want to lose nor
    costs the taker anything.
* **`card_values` on the wire is SLICED to the deck the room deals** — eight
  entries in a 32-card room, ten in a dummy room — so a bundle cached from
  before the wide deck goes on indexing skat's table with `c % 8` and labelling
  every corner chip correctly. The client takes its offset from the LENGTH
  (`RANKS.length - t.length`), which needed no new field and no version bump.
  `bot.swap_policy_terms` slices the same way for the opposite reason: Rust's
  `SwapPolicy` indexes by its own 0..7 rank, so ten entries would price a 7 as
  a 5 client-side. (Dummy has no talon, so the rows are unreachable there.)
* **A dummy round dealt BEFORE this is DELETED on load, not migrated and not
  voided.** A round in progress plays from its own hands, so a ten-card round
  resumed under the thirteen-card layout runs fine to trick 10 and then jams
  with no legal move — a hung room with nothing red anywhere, not an error.
  `engine.deal_is_current` counts the union of hands / piles / out / played
  against `deck_size` and `load_game_to_memory` drops any row that fails it.
  Unlike the pre-v2 guard beside it, this had a live population: dummy shipped
  the same day.
  - **VOIDING IT IN PLACE WAS THE FIRST ATTEMPT AND WAS WORSE THAN IT SOUNDS.**
    It closed the round in memory (`phase="over"`, no result) and left the row
    saying `playing`, so the game sat in the player's Active list forever,
    re-voiding on every open — and the lobby's cancel is scoped to
    `status='open'` rows, so there was no way to be rid of it. It also blanked
    the BOARD: the result panel reads `res.made` as the first property it
    touches, so a closed round with no result threw
    `TypeError: null is not an object`. Nothing about such a round is
    recoverable — it cannot be played, continued or scored — so the row served
    nobody.
  - **The delete is safe because the predicate is EXACT, and that is the whole
    argument for making it a delete.** Every card sits in exactly one of hands
    / piles / out / played at every moment (`expand_state` rebuilds `played`
    from `history`, so it is never merely absent), so the union IS the deck and
    `deal_is_current` is arithmetic rather than a heuristic. A predicate that
    could be WRONG must never drive an irreversible delete —
    `test_a_playable_save_is_never_deleted_by_the_unplayable_guard` walks whole
    rounds in all four modes asserting it at every ply, because one that is
    right at the deal and wrong at trick 9 would destroy live games.
  - **THE LOBBY IS WHERE IT ACTUALLY GETS DROPPED, and the first delete missed
    that.** `load_game_to_memory` only runs when someone OPENS a room, so a
    game nobody clicks sat in Active exactly as before — the delete was there
    and the symptom was unchanged. `list_user_games` drops it too, and free:
    that function already decodes every row's `state_json` to work out whose
    turn it is.
  - **`_unplayable` is ONE predicate read by both paths**, because two copies
    of "can this be played" drift and the first symptom is a game that vanishes
    from one and not the other. It **fails safe on absence of evidence**:
    `list_user_games` hands over `{}` for a row whose blob will not decode, and
    treating "I cannot tell" as unplayable would turn one transient decode
    error into destroyed games — so a dict with no deal in it is left alone,
    and a test pins that an undecodable row SURVIVES.
  - The tests drive the SEAM, not the predicate: a predicate that passes says
    nothing about whether anything calls it. The result panel keeps its
    no-result branch as a NET, since the cost is a dozen lines and the failure
    it prevents is the entire screen.
* **Rust is untouched and stays that way.** `client_searchable("dummy")` is
  False, so the core never sees a wide-deck game; the parity fixtures, the
  `views.jsonl` wire fixtures and the committed wasm all describe the 32-card
  game and are still exactly right about it. `persist._pack_hist`'s card field
  is six bits, so ids up to 63 fit — the wide deck needed no format version.

**THE AUCTION IS A DECISION NOW, and the fix was the deal, not the ladder.**
Everything the old measurements said about it has moved:

| | ten cards a seat | thirteen |
|---|---|---|
| declarer's share of the pool | 0.69 → 0.57 (leader command) | **0.48** |
| corr(visible hand → points taken) | +0.06 → +0.15 | **+0.145** |
| forced-level EV at level 1 → the top | +10.4 → **+58.2 at 9** (bid the top) | **+7.2 → peak +21.4 at 6 → −8.0 at 12** |
| granularity of a trick | 3 | **1** |
| choices at a decision / plies forced | 2.89 / 33% (2.27 following) | **5.59 / 9%** |

The shipped 1..12 ladder therefore needs no re-pricing at all: it has a real
interior peak and a real punishment at the top, which is what
`dummy_auction_design.py` was written to look for and never found before.

**`_DUMMY_LEVEL_NEEDS` and `MATCH_TARGET["dummy"]` were BOTH re-anchored, and
the first attempt at each is the lesson.** A level map is a set of quantiles on
a distribution and does not survive the distribution moving: against thirteen-
card hands every one of the old 18.4–23.9 thresholds was cleared, so **100% of
contracts settled at level 12 and 13% were made**. Re-placed at 23.0–30.6
against the measured spread (p50 27.2, p90 29.0), self-play now settles
**2–10, mode 6 (2/5/15/21/28/19/6/3/2%), 74% made** — against classic's 82% and
skat's 85%, and with the mode sitting exactly on the EV peak. `MATCH_TARGET`
fell **400 → 200**: the declarer's collapse from ~12 of a 15-point pool to 7.7
of 15.6 took the mean winning round from ~61 to ~34, and 400 would now buy
nearly twelve rounds where classic's 100 buys ~6.2. 200 buys ~5.9.

**A NEW MODE rather than a change to skat, deliberately.** Skat keeps its
solver, its parity fixtures and its DD review column, and the two can be
judged side by side. The cost is that the modes now differ in SEAT COUNT,
which is why `layout_for` exists rather than the numbers being spread around.

**POSITION IS NOT SEAT, and conflating them is the mode's central trap.**
`to_play` returns a POSITION (0, 1, or the dummy's 2); `playing_seat` /
`turn_seat` return the PLAYER who acts for it, which for the dummy is the
declarer. `side_of` maps a position to the player it scores for. Everything
downstream reads the right one: `legal_moves` takes a SEAT (so every existing
caller is unchanged and a bare position returns [] rather than a wrong
answer), `history` records a POSITION (which hand a card came from is what a
replay and the board need), and the frontend compares against `turn_seat` —
comparing `to_play` told the declarer it was not their move on a third of the
plies they actually have to make.

**THE AUCTION WAS A LOTTERY AT TEN CARDS A SEAT, and the record is kept
because it is what the wide deck was bought to fix** (measured in
`tools/dummy_auction_design.py` and `tools/dummy_matrix.py`; the current
figures are in the wide-deck section above):
* the points a declarer took correlated **+0.07** with the hand they could see
  — and **+0.06** with a CHEATING count of the cards really in their two hands,
  so no honest estimator could do better and no pricing of the rungs helped;
* every card was −1 or +2 and both are 2 mod 3, so **three** of them always
  summed to a multiple of 3 (two do not: −2/+1/+4). Every total was a multiple
  of 3, so contracts of 7, 8 and 9 were **literally the same contract** and two
  thirds of the ladder was duplicate rungs;
* make pays N² against a set's N + 5×short, so at levels 9–12 the reward was
  quadratic against linear risk — forced-level EV ran +10.4 at level 1 to
  **+58.2 at level 9**, i.e. there was no such thing as bidding too high.

`DUMMY_COMMAND = "leader"` fixed the SHARE and was orthogonal to all of that
(it moved the correlation only +0.07 → +0.15). **The measured lever on
predictability was whether card VALUE is aligned with trick-winning POWER**,
over five tables: the shipped anti-aligned one read +0.07, a monotonic aligned
one (−1,−1,0,1,2,3,4,5) read **+0.39**, and a table spread WIDE but still
anti-aligned read **−0.18** — so it is alignment, not spread.

**That lever was NOT the one pulled, and the reason is worth keeping.** The
anti-alignment is the mode's whole premise — the cards that win tricks are the
ones that cost points — so an aligned table buys predictability by deleting the
game. What the wide deck did instead was give the players more CARDS (13, so
46% on rails instead of 60%) and one genuinely inert rank, and the correlation
came up to **+0.145** on its own with the premise intact. A design lever
measured strong is not thereby the right lever.

**THE BOT'S FIRST TRAP IS OVERTAKING ITS OWN DUMMY**, and the policy is
written against sides rather than positions to avoid it: if the declarer's
card is already winning, a dummy card that beats it wins nothing and only
spends a better card. `policy_score`'s card branch folds the trick so far,
asks whether the current winner is on ITS OWN side, and weights a
not-yet-final card lower (0.3 against 0.5) because the defender can still take
it off you — which is exactly the dummy's dilemma at position two.

**HARD AND EXPERT DO NOT RUN HERE, and that is enforced twice.** The Rust core
is two-seat to its bones (`State.hand` is `[Mask; 2]`, the solver alternates
between two players, the wire reader partitions a two-hand pool), so a
three-seat search is its own project. `engine.client_searchable` says so;
`_handle_client_ai_ready` refuses to arm a dummy room at all, and `/catalog`
ships `searchable_modes` so the create modal need not offer a tier that cannot
run. Without both, an armed client would answer with a card for the wrong hand,
the engine would refuse it, and the room would play the server bot at full
speed while the label said Hard — the failure this repo has paid for twice.

**Two consequences worth knowing:** a dummy round banks **no review snapshot**
(the DD column is an exact solve, and nothing can price three hands), and its
**history stays verbose at rest** — the packer has one bit of seat and a
position needs two, so `persist._packable_hist` asks the DATA and leaves
3-seat histories alone, which `expand_state` already discriminates by shape.
Versioning the format instead would have risked every stored row to save bytes
on a mode that has none.

**Coverage is Python-only and that is the whole risk.** The parity fixtures
are two-seat, so `tests/test_dummy.py` (20 tests) is the only thing standing
behind this card play AND behind the wide deck: the deal partition (asserted
against `deck_size`, never a literal), every base id proving it did not move,
the eight new cards being a 5 and a 6 per suit that every 7 beats, their zero
worth and the deck total not moving, the trick gcd being 1, the sliced wire
table, dummy-second/never-leads over whole rounds, the declarer acting for it
and the defender never being able to, a dummy trick scoring for the declarer
and handing it the lead, the pool conserved, free discard, the redaction (its
hand open, its outer bottoms shut, the opponent's hand still hidden), and the
persistence round trip. `screens.mjs` drives the create modal to a dealt dummy
room and asserts the third seat renders face-up with its own piles, that a
trick really reaches three cards, and that **a 5 or a 6 renders as itself** —
a client still decoding ids as `suit*8 + rank` would draw the eight new cards
with a blank glyph and an undefined rank rather than throwing.

## QUARTET mode — four hands, two players, and a second currency (2026-08-21)

The fifth mode, and the first four-hand one. Seats 0 and 1 are the players'
OWN hands, 2 and 3 the hands OPPOSITE them, so a player commands `p` and
`p + 2` and **`side_of` is a plain `pos % 2`** — nothing is contested the way
`DUMMY_COMMAND` contests dummy's third hand.

**The shape.** TWELVE cards a hand, FOUR out, **NINE tricks of four**, no
piles. Every hand therefore ends holding three it never played, and an OWN
hand's three score their card value into the total the contract is bid
against. Classic's auction plus a backing rule, plus one new phase.

**EVERY NUMBER IN THAT SENTENCE WAS MEASURED BEFORE THE MODE WAS WRITTEN**
(`tools/quartet_agency.py`, `quartet_keeps.py`, `quartet_auction.py`,
`quartet_ladder.py`). The order the findings arrived in matters, because two of
them overturned the one before:

* **The pile split was the wrong question.** The probe was built to fit it, and
  every 13/10 arm starved the dummy seats regardless — 2.59 legal cards at 4+3
  piles and only **3.08 with no piles at all**, against the 2.89 that sent
  dummy mode back to be re-dealt. Burial moves a seat by 0.5; its CARD COUNT
  moves it far more. A 10-card hand playing ten tricks is down to one forced
  card at trick 10 while a 13-card hand still holds four.
* **…so the deal wanted to be four EQUAL hands, and that arm is dead on an axis
  the agency probe cannot see.** Four hands of 13 is all 52 cards with NOTHING
  out — and with nothing out the two players PARTITION the deck, so each knows
  the other's holding exactly by complement. Measured as bits of uncertainty
  about which cards the opponent holds: **0.0, against classic's 14.7.** The
  finesse survives (23.3 bits remain about how their cards are SPLIT between
  their two hands, which is the only thing a finesse asks) but every statement
  a player could make about their own holding is already known — so a backed
  bid conveys nothing and the auction has no content.
  **An out-pile is not a talon to cut a prize from. It is the game's entire
  permanent hidden-information budget.**
* **12/12/12/12, four out, NINE tricks is the deal.** 4.31 choices a decision
  and 16% forced, both better than classic's 4.02 / 22%; 14.3 bits of secrecy,
  within half a bit of classic's 14.7; and three cards kept a hand, which the
  ten-trick version would have cut to two. Nine reading better than ten is not
  a rounding artefact — a round's last trick is its most constrained, so
  stopping a trick earlier drops the worst ply from every hand.

**THE KEEPS ARE THE SECOND CURRENCY, and they are a decision rather than a
formality — measured, because the failure mode was real.** The best three cards
in a twelve-card hand are worth **+5.49** with a ceiling of +6 that 80% of
hands can reach, so if a player could simply keep their best three then everyone
scores +6 every round, the variance is zero and the mechanic is decoration.
What stops that is follow-suit: greedy protection reaches **+4.41** against a
random +0.91, so it costs 1.08 points and **denies the ceiling in 55.6% of
rounds**. Both policies are non-attacking, so that is a FLOOR — an opponent who
leads the suits your +2 cards live in drives it further, and that is the
mechanic's interactive half.

* **Only an OWN hand's three score.** The best six across a player's two hands
  is +11.64 against a random +1.84 — a 9.8-point skill band against a trick
  range of −5..+8, i.e. three quarters of the round decided off the table. One
  hand's three is 4.6, about a third.
* **The dummies still keep three and they score nothing.** Dealing them nine so
  they play out exactly (12/9/12/9) was measured and is worse — 2.88 choices,
  24% forced, dummy mode's failure mark. The dead keeps are better read as an
  ASYMMETRY than a wart: an own hand is under squeeze pressure and hoards,
  while a dummy has nothing to protect and spends freely to attack.
* **The keeps do NOT enter `pts`.** `pts` stays the TRICK total in every mode,
  so "pts sums to the pool over a completed round" holds unconditionally and
  every existing test asserts it flat rather than behind a mode test. `_finish`
  adds the two together once, where the contract is settled (`keeps_for`).

**THE BACKED BID — the substitute for bridge's partner conventions, which a
two-player game cannot have.** A denomination may only be named by a bidder
holding **`QUARTET_BACKING` = 6** or more of it across their two hands, so every
bid is a PROVABLE statement and the opponent can count against it: the
information is enforced by legality rather than agreed between partners.
No-trump is always legal, which stops a hand being unbiddable and makes an NT
bid usefully ambiguous (real strength, or no suit at all) rather than a tell.

Six is a two-sided fit over 20k deals, and it is exactly the mean suit length
across a player's 24 cards, so the rule states in one sentence:

| K | mean legal suits | none | exactly 1 | 2+ | proves |
|---|---|---|---|---|---|
| 5 | 3.33 | 0.0% | 0.0% | 100% | 0.47 b |
| **6** | **2.50** | **0.0%** | **1.9%** | **98%** | **0.81 b** |
| 7 | 1.49 | 6.4% | 38.1% | 56% | 1.17 b |
| 8 | 0.66 | 44.8% | 44.0% | 11% | 1.53 b |

Too low and every denomination is legal, so the bid proves nothing; too high
and the bidder had no choice, so it proves a lot and decides nothing. Raise it
to 7 if bids measure uninformative in play — it is one constant and
`quartet_auction.py` re-fits it.

**AND THE BID LIST IS PRIVATE NOW, WHICH IT NEVER HAD TO BE BEFORE.**
`view_for` shipped `auction_options` to BOTH seats, harmless while legality
depended only on public state (the standing bid, the spent denominations).
Under backing it depends on the bidder's 24 private cards, so **the defender
could read straight off their own pad which suits their opponent holds six
of** — the exact information a bid is supposed to cost something to reveal.
The list goes only to the seat on turn; nobody can bid out of turn, and the
frontend already gates the pad on `myTurn` with a `{bids: []}` fallback, so no
expand/contract window was needed. Found by reading a real `created` payload,
not by a test, which is why there is now a test.

**THE COMMIT PHASE — stage two of a two-stage auction.** Stage one competes on
level and denomination; `commit` is where the declarer DECLARES two things, and
both are declarations rather than contests, which is why they sit after the
bidding rather than inside it:

* **which of their two hands leads.** The only decision in the auction that
  needs two hands to exist. Play goes round the table, so the leading side
  plays FIRST and THIRD while the other plays SECOND and FOURTH — and fourth is
  the informed seat, with the whole trick already down. **Leading costs
  position**, which in a game where winning a trick can lose you points is a
  genuine liability rather than the plain advantage it is elsewhere. Whichever
  of a player's seats wins a trick leads the next, so this sets the parity the
  round re-phases around.
* **one optional card swapped between their own two hands.** The declarer's
  prize, and it replaces the talon — quartet's four out-cards are pure secrecy
  that nobody ever sees, so the prize has to come from somewhere else. Worth
  something real because the two hands sit in different seats. Both-or-neither:
  a lone `take` is refused rather than treated as a half-swap.

**THE LADDER IS FITTED AND ITS PEAK IS INTERIOR** (`tools/quartet_ladder.py`).
Settles 1..10 with the mode at **6** and **78% made** (classic 82%, dummy 74%),
busiest rung 27% — inside the "no level above 40%" constraint. Forced-level EV
climbs +6.81 at the floor to **+27.41 at level 8** and falls away to +1.45 at
the ceiling, so there is a real punishment for overbidding. **Dummy mode's first
ladder failed exactly this check** and settled 100% of contracts on the top
rung. `MATCH_TARGET` is 140, bootstrapped to a median of 8 rounds (p10–p90
5–11), which is classic's profile to the round.

* **Watch the sign when re-tuning `_QUARTET_LEVEL_NEEDS`**: a threshold is the
  strength a level DEMANDS, so RAISING it lowers the settled mode. The first
  re-fit chased the EV peak upward and moved the mode the wrong way (6 → 5).
* **Declarer EV is positive at every rung and that is not a defect** — this is
  a symmetric zero-sum game, both seats have EV 0 by construction, and the
  column only says what winning the auction is worth in that regime.

**THE MIRROR MUST READ 0.0000 AND TWICE IT DID NOT.** `_split` puts a whole
round on the winner and zero on the loser, so **a score row is not zero-sum**:
the first paired arena scored the same seat in both seatings (+16.41) and the
second added two score rows instead of differencing them (+15.75, which is just
the mean absolute transfer). Both looked like a strong policy. The signed
difference, averaged over both seatings, is the only correct pairing — and the
bot's real margin over random-legal is **+27.37 a round**.

**THE FULL DECK — 52 cards, and the 2/3/4 are ids 40..51.** The deck has now
been widened twice and the rule that made both safe is APPENDING: block A (the
5 and 6) at 32..39, block B (the 2, 3 and 4) at 40..51, so no id that ever
shipped changed meaning. The obvious generalisation — one contiguous
`NCARD + suit * 5 + k` — would have renumbered the 5 and the 6 into the 2 and
the 3, and **`deal_is_current` could NOT have caught it**: a renumbered dummy
save still holds forty distinct ids and still counts right against `deck_size`,
so every card would silently have changed rank. The invariant the blocks buy,
which every deck function leans on: **a deck of N cards is exactly `range(N)`
AND exactly the top N/4 ranks**, true at 32, 40 and 52.

**HARD AND EXPERT DO NOT RUN HERE**, enforced the same two ways dummy is: the
Rust core is two-seat to its bones, `client_searchable("quartet")` is False, and
`/catalog`'s `searchable_modes` keeps the create modal from offering a tier that
cannot run. A quartet round banks no DD review column for the same reason.

**Coverage is Python-only plus one browser block, and that is the whole risk.**
`tests/test_quartet.py` (32 tests) and two integration tests are what stand
behind this; the parity fixtures are two-seat and never see it. The redaction
test asserts against the whole SERIALIZED payload of a real mid-round game and
was verified non-vacuous by injecting a leak into `view_for`.

**THE RENDER GATE EARNED ITS KEEP HERE.** `trickList` sliced history into
tricks with `const w = game.dummy ? 3 : 2` — under a comment claiming the width
came off the wire, which it did not. Quartet's four-card tricks were sliced into
pairs, so the completed-trick hold showed two of four cards, the Last trick
panel was wrong and every trick's parity value was computed for the wrong trick
NUMBER. All of it rendered perfectly and nothing threw; `npm run screens` is
what caught it. The width is now `game.piles?.length`, which carries one entry
per POSITION in every mode and needs no mode test at all.

## Must head the trick — MEASURED, THEN SHELVED THE SAME DAY (2026-08-10)

**`MUST_HEAD` is off in every mode.** The implementation is kept whole and the
gates still drive it through the flag (the `_score_is_settled` idiom), because
the rule works and the measurement below is the only reason it is not on. The
dummy above is what was tried instead. When it was on: when you CAN follow
suit and hold a card that BEATS the lead, you must play one. Ducking under a winner is legal only when you cannot beat it at all.
Ruffing is untouched: void in the suit you may still play anything and are
never forced to trump — must-head filters the FOLLOW set alone.

**Its own per-mode dict (`MUST_HEAD`), deliberately NOT folded into
`uses_card_points`.** A legality rule and a scoring rule are different things,
this one is an experiment, and one line turns it off — including the wire
requirement below, which is derived rather than pinned.

**WHAT IT IS WORTH IS ONE TRICK SHAPE, and that is measured, not asserted.**
Enumerating every shape, the rule changes the outcome of exactly one:

| lead | they hold | without | with |
|---|---|---|---|
| **K** | 9, A | 9 → **+1 to the leader** | A → **−2 to them** |
| K | 7, A | 7 → −2 to leader | A → −2 to them |
| 9 | 8, K | K → +1 to them | K → +1 to them (unchanged) |
| 7 | 8, K | K → −2 to them | unchanged |
| A | 7, Q | 7 → −2 to leader | unchanged |

So the whole mechanic is **lead a king, force the ace** — a three-point swing
that turns the deck's two dead cards (K and A, both −1) into a duel, and makes
a bare ace a real exposure. It does NOT fix the complaint that prompted it
("you win with an ace and they slide a 7 under it"): nothing beats an ace, so
must-head never fires there. Know that before spending more on this direction.

**HOW OFTEN IT BINDS — and the gap that matters:**
* random play: 7.4% of plies · **the shipped greedy policy: 6.2% of follows**
* **a leader who CHOSE to could bind on 34.4% of tricks** (counterfactual over
  real rounds: at each lead, does any legal lead narrow the follower?).

The 5.5x gap is the whole story: it is a lever the bot was not pulling, not an
inert rule. Leading LOW — the card policy's default — is precisely the lead
that can never bind, since every follow beats it. The searching tiers get the
lever for free (an exact solver over the real legality); the greedy tier had
to be taught, so `policy_score`'s card-lead branch now scores the EXTRACTION
LEAD: a liability card whose every unplayed beater is also a liability, read
off `played` plus this seat's own holding (honest counting, decays to nothing
once the ace is gone, weight 1.6). That took binding 6.2% → **9.7%**, and both
seats wield it, so the declarer's make rate lands back on **85%** — the same
figure card scoring measured without the rule, so `_SKAT_LEVEL_NEEDS` needed
no re-anchoring. Mean winning payoff 20.1 → 20.6.

**Caveat worth keeping:** of the follows it binds, ~85% leave the follower no
choice at all, so what the rule mostly does is move a decision from the
FOLLOW to the LEAD. That is the intended direction (the lead is where control
was missing) but it is a transfer, not an addition.

**The inference it buys, and why it is not optional.** Following without
beating proves the seat could reach no higher card of that suit — so none is
in hand, and hands only shrink, so the ceiling is permanent.
`Knowledge::hand_cap` records it (hand-written `Default`: `NRANK - 1` is "no
constraint", and a derived zero would assert both players hold nothing above
the deck's lowest rank), `determinize` keeps capped cards out of the hand and
lets them fall into the covered pile slots — the same "piles launder voids"
property the module note already describes — and `wire.rs` mirrors it from
history. Without it the searcher spends its worlds on deals the opponent has
already disproved, silently.

**Rung 4 on the wire, and it is a HARDER rung than 2 and 3.** Those carried
scoring fields, so an artifact missing them returned legal-but-misvalued
moves. This one carries LEGALITY: an artifact without it answers with cards
the room refuses, `_validated_bot_move` drops them, and the room plays the
server bot at full speed while still saying Hard. `odd_wire()` is 4, the
worker refuses any payload whose `must_head`/`head` it cannot honour, and
`_handle_client_ai_ready` computes what a room NEEDS from its own rules
(`must_head_mode` → 4, else card scoring → 3) rather than pinning a literal.
The artifact was rebuilt and committed with the change.

Gates: `must_head_forces_a_winner_when_one_can_follow` and
`a_must_head_ceiling_is_inferred_and_respected_by_the_determinizer` (Rust),
`beats_mask_agrees_with_beats_over_the_whole_card_space` (the mask form drives
the filter and sits on the hot path, so it is swept exhaustively), the
brute-force solver's card arm now runs the shipped cards+head combination, and
`play.jsonl` carries `head` on its card fixtures with a NON-VACUITY test —
must-head bound on 192 of 2600 fixture plies, so a legality break really would
surface as an illegal move rather than passing unnoticed.

## Two auctions, one game (skat mode, 2026-08-07)

**`mode` is a ROOM FLAG, not a second game** — one `dissonance_games` table, one
route, one lobby, chosen in the create modal (`CmSeg`) and shown as a badge on
lobby cards. The deal, the piles, the talon, follow-suit, the parity, the
redaction machinery and every `_start_play`-onwards path are **shared verbatim**;
`apply_move` dispatches on `g["mode"]` and both paths converge on `_start_play`.
The design argument is `rust-cores/dissonance-core/SKAT_MODE.md`.

Classic is described below; this section is only what skat mode adds.

* **Bid a number, name the game later.** `value = base × level`, bases
  **♦2 ♥2 ♠3 ♣3 Grand4 NT5** — priced by COLOUR. The ladder is
  `SKAT_VALUES`, **derived from the bases**, and served via `/catalog`
  (`skat_bases`, `skat_values`) so the client holds no copy.
  **`SKAT_BASE` is indexed by DENOMINATION and is SPARSE**: index 5 is
  `NULL_DENOM` and carries a base of 0, the marker for "not on the ladder".
  Iterate `SKAT_DENOMS`, never `range(len(SKAT_BASE))` — and the client filters
  `base > 0` for the same reason (`levelsFor`), because a 0 divides to Infinity
  and only failed to render by accident.
* **Collisions are the point.** 12 = ♦6 = ♥6 = ♠4 = ♣4 = Grand3, so a bid names
  a price, never a shape. The frontend *shows* this (`.dis-clears`) rather than
  explaining it.
* **The colour pricing replaced a four-tier table (D2 H3 S4 C5 NT6), 2026-08-07,
  and it is a deliberate partial reversal.** The original argument still holds
  where it is load-bearing: the suits are *measured* symmetric (settled-
  denomination evenness 0.943), and the prices exist to manufacture an asymmetry
  the game does not otherwise have. Four tiers was too much of it — a hand
  equally playable in hearts and spades was priced a whole rung apart for a
  reason no player could name, and the cheap suits swallowed the auction. Two
  tiers keep the convention where it earns its keep and hand the within-colour
  choice back to the cards.
  - **The ladder loses nothing anyone bids.** Every multiple of 6 at or below 36
    is already a multiple of 2 or 3, so dropping base 6 removes only 42, 54, 66
    and 72: the rungs are IDENTICAL through 40, the ceiling falls 72 → 60, and
    the count goes 36 → 28 (32 once Grand's base 4 is added). 7 is still the
    only hole below ten. `test_skat.py`
    asserts the ends off `min`/`max(SKAT_BASE)` rather than as literals, which
    is exactly what let the ceiling move without a hand-edit.
  - **Null's flat 20 got relatively dearer to duck under**: still 13 rungs below
    it, but 13-of-32 rather than 13-of-36, against a ceiling that fell by a
    sixth. "A cheap contract is a licence to duck" is already the intended
    shape; this nudges it. Retuning is engine-side alone (the Hard tier reads
    `payoff_terms`), so it can wait for a measurement rather than a guess.
* **GRAND (2026-08-07) — the four 10s are trump and belong to NO suit**, Skat's
  jack rule on the ten. Skat mode only: classic *ranks* denominations rather
  than pricing them, and Grand has no natural rank slot in `C<D<H<S<NT` because
  it is defined by what it costs. Base 4, between the blacks and no-trump —
  with four trumps (~0.75 of them out of play on an average deal) it is
  no-trump with a handful of wild cards, not a suit game with a long trump.
  - **The SECOND ten played wins.** They are all tens, so there is nothing to
    rank them by, and any imposed order (Skat's ♣>♠>♥>♦ or otherwise) is one
    more rule a player cannot read off the cards. So leading a ten is a way to
    LOSE a trick on purpose — which, with seven of thirteen tricks at −1, is a
    tool and not a penalty. It also makes all four tens fully interchangeable,
    which the solver's equivalence collapse depends on.
  - **`GRAND = 6`, NOT 5.** 5 is `NULL_DENOM`, the marker on games saved before
    Null stopped being a bid; reusing it would silently re-read one of those as
    a Grand contract — different trump, different follow-suit. The value is
    never arithmetic, so the gap costs nothing but the sparse `SKAT_BASE`.
  - **`esuit(card, trump)` IS THE WHOLE FEATURE, and it is expressed once.**
    Suit membership stops being `card // NRANK` while Grand is trump, which is
    the deepest shared invariant in both implementations. Everything derives
    from that one function: `beats`, `legal_moves`, `Knowledge::hand_void`
    (**five classes, not four** — a trump void is a real fact, and a `[bool; 4]`
    would have dropped it silently while the determinizer kept dealing tens into
    a hand that had proved it held none), the determinizer's partition,
    `dd.rs`'s equivalence collapse (`follow_mask`, because under Grand a suit
    LOSES its ten so its 9 and J become adjacent — reading the raw suit mask
    would refuse a collapse that is legal, and would collapse two tens against a
    suit that is not theirs), `policy.rs`, and `wire.rs`'s void inference.
  - **It is the identity under every other contract, and both suites assert that
    over the WHOLE card space** rather than sampling it (`test_every_other_
    contract_plays_exactly_as_it_did_before_grand_existed`,
    `no_other_contract_moved_when_grand_arrived`). `esuit` sits on the solver's
    hottest path; a regression there is a different game, not a worse bot.
  - **The fixtures cover it or it is not covered.** `gen_fixtures` samples trump
    over `DENOMS` (so ~1 play fixture in 6 is Grand and the Python port replays
    it), `solver_matches_brute_force` sweeps `DENOMS` and asserts it reached
    Grand, and `gen_view_fixtures.py` appends a FORCED Grand game — the bot
    picks a denomination on hand strength and can go whole runs without choosing
    Grand, which would leave the wire reader's Grand path covered by nothing
    while the file still looked comprehensive.
* **Phases:** `auction` (numeric) → `talon` → `declare` → `kontra` → [`re`] →
  `play`. `talon` splits into `look` / `hand` / `swap` because **declining to
  look is what Hand means** — the declarer who plays Hand never sees `shown`
  either, in the engine *and* in `view_for`, or Hand would be a free multiplier.
* **Overtricks pay 1 each, flat.** `stake + 1 × (pts − target)` on a make — the
  same `OVER_BONUS` classic uses, and deliberately NOT run through `mult` or the
  doubling. See the overtrick section above.
* **Announcements add, they don't multiply**: `mult = 1 + hand + sharp + open`.
  Sharp promises `level + SHARP_BONUS` (2); Open rides on Sharp. Kontra ×2 /
  Re ×4 on top. A multiplier rather
  than a flat bonus because classic's campaign measured a flat +1 *raising* the
  floor cluster — it is proportionally biggest on the smallest contracts.
* **Open is the only path by which one seat legitimately sees the other's hand.**
  `view_for` ships `opp_hand` only when the contract is Open and the phase is
  `play`/`over`, and only to the defender.
* **Both players may pass; both passing redeals.** Safe here and not in classic:
  classic's opener is *forced* to name a contract, so passing would be strictly
  better than a bad one. Here a pass hands the opponent the talon and the lead at
  *their* price. `_redeal` mutates `g` **in place** — the room server, the bot
  scheduler and every open socket hold that exact object.

### Skat mode: things that are not what the spec says
* **The ladder is DERIVED, and SKAT_MODE.md's hand enumeration of it was wrong
  twice** — it counted 43 rungs and listed a 7. `base × level` is the rule and 7
  is a multiple of no base, so the real ladder is **32 rungs from 2 to 60 with
  one hole at 7**. `test_skat.py` asserts against the *generator* and pins the
  hole so nobody "fixes" it back; it also reads the ends off `min`/`max(
  SKAT_BASE)` rather than as literals, which is what let the colour re-pricing
  move the ceiling without anyone hand-editing a number.
* **"Overbid loses automatically" cannot fire, and is deliberately not
  implemented.** The level is the declarer's free 1..12 choice and NT×12 is the
  top rung, so every legal bid is declarable (`test_every_legal_bid_is_
  declarable`). Stretching is punished *structurally* instead — a big number
  forces you up the level ladder into a contract you can't make, and past 20 it
  make. Writing the rule anyway would be an untestable branch, which
  the repo's zero-skips policy is the same argument against.
* **The bot's skat thresholds are guesses, not measurements.** `skat_ceiling` is
  the real arithmetic (max over denominations of `base × the level that
  denomination is worth`), but `_KONTRA_TARGET` / `_KONTRA_STRENGTH` are placed
  by hand, and the bot never announces Hand/Sharp/Open and never Res.
  SKAT_MODE.md's open questions — announcement rates, overbid frequency, the
  Kontra threshold, and whether the mode beats classic on the
  settled-contract distribution — are a **`skatlab` self-play sweep that has not
  been run**. None of them are answered by shipping this.

## Rules as shipped (v2, 2026-08-07)

**32-card deck** (7–A ×4). 13 cards each: **7 in hand + three 2-card piles**.
Only a pile's top is playable; the card under it becomes playable *and public*
when uncovered. The **middle** pile's bottom is dealt face-up to both; the
outer two are hidden from everyone **including the owner**. **Six** cards sit
out, revealed at the end.

(**Dummy mode deals 40** — the same 32 plus a 5 and a 6 in each suit, at ids
32..39 — because three seats of thirteen do not come out of 32. Same 7 + three
piles per seat, one card out. `deck_size(mode)` is the only place that varies;
see the wide-deck section under DUMMY mode above for why the ids were appended
rather than the deck renumbered.)

**Auction.** Denominations are **ranked C < D < H < S < NT**. Opener
names level 1–12 and a denomination, committing to score at least that many
points. Responses overtake at the **same level in a higher-ranked
denomination**, or **raise by any amount** (classic since 2026-08-13 — minor
and dummy keep the old +1/+2 cap). Per-player no-repeat (`DENOM_RULE` is **"used"** in every mode — the two
relaxations measured on 2026-08-13 were experiments and NEITHER SHIPPED;
see below). The opener may not pass.
Big raises are priced rather than forbidden: see the JUMP BONUS section
below.

**The talon.** The auction winner is shown **3 of the 6** out-cards (fixed at
the deal) and may swap ONE into hand, discarding a hand card face-down — never
a pile card. The defender learns *that* a swap happened, never which cards.

**Play.** Declarer leads trick 1. Follow-suit is
mandatory **and a pile top counts as a card you hold**. May ruff when void,
never forced to. Winner leads next.

**Scoring** (contract only; trick points are the yardstick *and* the margin —
and in skat mode "trick points" means CARD points, per the section above):
make → **N² + the flat 4 stake, + 1 per trick point past N**; set → defender
scores **2N + 2, + 5 × shortfall, + 6 × the final bid's level jump (classic
only — see the JUMP BONUS section)** (the flat stakes — see the bullet below —
are classic-only, and are +4/+2 since the 2026-08-16 re-price; the original
dose was a symmetric ±10). **NULL OVERRIDES A SET**: a declarer who won **no +2
trick all round** scores a flat **20** (both modes; classic moved 12 → 20 with
the stake — sets got fatter, so the escape was re-anchored just under a made
level-1's ceiling) instead, whatever they
declared. **Every round runs all thirteen tricks** — see the overtrick section.

### Why these numbers, in one line each

* **32 cards / 6 out** — the hidden-information sweep's efficient point: 74%
  of the secrecy available at ANY width, and the curve saturates hard past it
  (marginal value per dead card 0.065 → 0.029 → 0.007).
* **ranked denominations** — the first change that ever SPREAD the settled
  distribution instead of translating its spike (level-4 hole 6.7% → 14.2%,
  replicated on both decks). Openers name where it is CHEAP, not where they
  are strong (best-denom openings 45% → 31%), which is the hidden-info point.
* **Null is not a bid (2026-08-07)** — and every measurement of it as one said
  the same thing. At rung 3 it was overtaken away in 100% of auctions; at 8
  nobody makes it; raising the price SUPPRESSES it (a 33%-make gamble is only
  worth taking while losing is cheap); all 18 observed contracts arrived by
  OVERTAKE, none by opening. As a purchase it was either free or dead. It is a
  **consolation** now, live under every contract at once — which is what the
  "sacrifice valve" reading always wanted, at no auction cost.
* **the swap** — makes winning the auction worth something beyond the
  contract, adds real overbid risk, and the discard is a bluffable signal.
* **maxraise 2 — SUPERSEDED IN CLASSIC (2026-08-13) by the jump bonus; minor
  and dummy still run it.** The original measurement stands for what it was: a
  cap of exactly 2 relocates the punishment-landing pile from level 2 to level
  3, which is where the distribution had a hole, and a cap of 3 empties level
  3 again — the spike *translates*, it never spreads. Classic now prices big
  raises instead of forbidding them (see the JUMP BONUS section), which was
  the product call: the cap read as arbitrary and other games don't have one.
* **declarer leads** — the opening lead was measured at **+0.93 pts**, the
  strongest single lever on contract height — and the reason Null is a
  DECLARER'S consolation (its make rate defending is ~0%).
* **N² make / linear set** — the make/set RATIO is what lifts bidding. Matched
  curves cancel: N² on both left the floor cluster identically at 42.7%.
* **set base N, not N−1 (2026-08-07; the base is `2N + 2` since the 2026-08-16 re-price — `SET_LEVEL_RATE` 2 and `FLAT_SET_PENALTY` 2, and the argument below is about the +1 that got it off N−1)** — a product decision, not a measurement,
  and it is one number in one place (`_terms_for`'s classic `set_base`). At the
  floor the old base contributed *nothing*: breaking a level-1 contract paid the
  defender by the margin alone, and ~42% of openings sit at level 1. It adds
  exactly 1 to every set in the mode, so it can never reorder two set results —
  what it moves is set-vs-make and set-vs-Null, both by one. **Everything
  downstream follows for free**: `payoff_terms` ships to the Hard tier, so the
  bot re-priced itself with no bot code at all, and the only files that had to
  change with it are the ones holding a SECOND copy — `payoff.jsonl`
  (regenerate: `PYTHONPATH=. python -m games.dissonance.tools.gen_payoff_fixtures`),
  the Rust harnesses that hand-build classic terms (`bid.rs`'s test `opt`,
  `cmatch.rs`, `abench.rs`), and the two places that print the arithmetic to a
  human (the result panel's maths line, `rules.jsx`). Skat is untouched: its set
  base is the STAKE, so there was no N−1 in it to add to.
* **the flat stake (2026-08-11, classic only) — MEASURED AT ±10, SHIPPING AT +4 MAKE / +2 SET** since the 2026-08-16 re-price folded most of the set side into `SET_LEVEL_RATE = 2`; the symmetry argument below is what the dial is FOR and it survives the dose, but every absolute number in this bullet was measured at ±10 — `FLAT_MAKE_BONUS` /
  `FLAT_SET_PENALTY`, per-mode dicts; +10 on the made base AND +10 to the
  defender on a set, inside the Double like the bases they ride. Symmetry is
  the design: a make-only bonus adds `F·p(make)` to holding any contract (an
  aggression dial — the measured +4/+6/+10 ladder monotonically raised
  sacrifices, pushed settles HIGHER and bled the make rate to 39%), where the
  symmetric stake adds `F·(2p−1)`, positive only past a 50% make — "hold what
  you believe in". Measured at ±10 (400 paired deals, Expert-vs-Expert k=8,
  DD-resolved): make rate 59.8% vs 58.5% baseline, mean settled 4.58 vs 4.59
  (the economy stands still), while the SHAPE moved — 2-opens 5.8% → 14.2%,
  the 1→3 funnel 65% → 55%, the settled level-4 crater 8.2% → 15.5%,
  made-at-level 6/7 up 9–12pts. The lab overrides per arm via `DIS_FLAT_MAKE`/
  `DIS_FLAT_SET` (env, only when present — the engine default is no longer 0).
  Second copies that moved with it: `payoff.jsonl` (regenerated), `cmatch.rs`
  `contract_for` / `abench.rs` (the bins that claim the shipped scoring),
  `rules.jsx`, and the result panel now reads `make_value`/`set_base` OFF THE
  ROW rather than recomputing N².
* **short 5** (`CLASSIC_SHORT_PENALTY`; 4 until 2026-08-08) — the sacrifice dial. Doubling it roughly halves sacrifice bids. A DOUBLED shortfall is its own rate, `DOUBLED_SHORT_PENALTY` = 10 — see the Double section.
* **per-player denominations — KEPT.** Two relaxations were measured on
  2026-08-13 and NEITHER was adopted: "standing" (nobody bids the standing
  suit twice in a row) and "own" (no seat repeats its OWN last suit). They
  live in `DENOM_RULE` as measurement arms only, driven by the arena's
  `DIS_DENOM_RULE`. Their profiles are recorded below; the shipped rule is
  the original forever-ban, which is also what the 1000-deal-per-arm jump
  sweep was measured under.

## THE JUMP BONUS — classic dropped the raise cap and prices the leap instead (2026-08-13)

Classic's `MAX_RAISE` is gone: an overtake may raise by ANY amount up to the
ceiling. What replaced it is a scoring rule, **`JUMP_SET_BONUS` — 6 in classic since the
2026-08-16 re-price, 3 when this section was written**: **if the FINAL bid of
the auction raised the level — a jump of j over the bid it overtook — the
defender scores an extra `6 × j` on a set.** THE
OPENING BID COUNTS, as a raise over level 0 (**v2, same day**): open at 6 and
get set and the defender collects +36 on top; open at 1 and it costs 6.
(**CORRECTED 2026-08-19.** This section — the one that DEFINES the rule — still
said 3 three days after `a317bb1` changed it to 6, while `rules.jsx` had been
updated and was telling players the right number. A constant stated in the
section that defines it is the one place a reader trusts without checking.) A
same-level overtake in a higher denomination is a jump of 0 — the only
jump-free way to buy a contract. The intent: keep the auction climbing in
small steps (every rung gives the opponent a decision) by making the leap
legal but expensive, instead of a cap other games don't have.

**v1 exempted the opening, and 500 rounds of self-play said why that fails**
(the profile below is v1's, kept as the comparison): with no cap to hide
under, underbidding lost its point, Expert opened AT VALUE (mean 4.31,
unimodal at 5–6) and passed — 47% one-bid auctions, 1.77 bids/auction.
Charging the opening its whole level is what makes starting low the cheap
line for the OPENER too.

**A v2 consequence, pinned in `test_double.py`
(`test_a_jumped_contracts_double_out_wins_its_risk_at_low_levels`): an
open-and-pass contract at levels 2–4 carries enough doubled jump bonus that
doubling its NEAR-MISS out-pays the made-contract risk** — the near-miss-
stays-cheap property now holds only for jump-free contracts. A leap does not
just fatten the set; it invites the Double. Deliberate, but it re-prices the
Double's odds table for jumped contracts.

**Where each piece lives — the `payoff_terms` discipline, one rung deeper:**
* `apply_bid` records `a["jump"]` (real game state; `.get(..., 0)` on every
  read so an old save prices as the old rule). `_finish` puts `jump` on the
  result row; `view_for` ships it in the auction block.
* **The bonus rides INSIDE `set_base`** (`_terms_for(..., jump=)`), beside the
  flat set stake — so the Double doubles it, Null still overrides it (a
  consolation owes no set price), the result panel's maths line still sums,
  the DD review and the arena's resolver price it with no new code, and the
  Hard tier's option list carries it with **zero Rust changes** (each classic
  candidate is priced as its own final bid: `jump = lvl − standing`).
* **The Expert tree is the one place it could not ride as data.** The terms
  rows are keyed by SETTLEMENT and a jump is a property of the PATH, so the
  rate crosses the wire as a rule (`rules.jump_set_bonus`, optional, default
  0), `AucState` carries `jump` (part of the memo key — two nodes differing
  only in how their standing bid arrived are worth different amounts), and
  `settled`/`opp_myopic` do the one add at the leaf. The payload's `state`
  also ships the STANDING bid's jump, since a pass settles on it.
  `rules.max_raise` now ships `raise_cap_for(mode)` — classic's own ceiling,
  so `min(top, level + max_raise)` never binds there and an old wasm still
  reads a plain number. Minor/dummy ship 2 and a 0 rate: unchanged games.
* Fixtures: `auction.jsonl` regenerated (uncapped classic legality + the new
  rules/state fields), `payoff.jsonl` regenerated with REAL jumped auctions,
  doubled and not, so `payoff_parity` pins the fold. The wasm artifact was
  rebuilt and committed with the change (glue byte-identical — same
  wasm-bindgen — so the pair stayed matched). A cached older wasm prices sets
  without the bonus and with the cap: legal moves, slightly wrong values, the
  ordinary cached-bundle window.
* Gates: `test_the_final_bids_jump_is_recorded_and_pays_the_defender_on_a_set`,
  `test_a_jumpless_auction_scores_exactly_as_before`,
  `test_minor_mode_keeps_the_raise_cap`, the payload-field tests in
  `test_expert.py`, and Rust
  `the_settling_bids_jump_fattens_the_set_and_only_the_set`.
* The server bot needed nothing: `choose_bid` overtakes at the cheapest rung
  in its best denomination, which never jumps. Easy/Normal don't price the
  bonus — they are heuristics and it only fattens a set they were already
  trying to avoid.
* The study's instrument is `tools/jump_report.py` over `auction_arena.py`
  checkpoints (the settled event now carries the round's dd payoff and the
  auction's level sequence — flip 0 only, since a mirror's flips are
  identical).

**THE 500-ROUND EXPERT PROFILE UNDER v2 + THE "OWN" RULE (2026-08-13,
MEASURED, NOT SHIPPED; same harness):** bids/auction **2.10** (67.4% contested,
28.2% opener re-entry), overtakes 1.10/auction — same-level overtakes fall to
26.5% of them (the standing rule's ping-pong mostly gone) while jumps ≥2
rise to 37.0%, sizes fattening (+3:69 vs the standing run's 56); openings
mean 3.07 (23.4% at 1); settled mean 4.69 (2.2/6.4/9.8/17.6/33.8/25.8/4.4%);
made **58.4%** / set 38.4 / Null 3.2; Doubles 26.0% (doubled avg **−18.1**,
the most defender-favourable of the variants; defender's doubled set avg
55.4); sacrifices 25.0% (avg −20.4). Against the standing rule it trades
~0.5 bids/auction and 11 points of re-entry for cleaner shape: no lateral
suit ping-pong, raising the opponent's suit legal, and the restriction is
one a player can hold in their head ("not the suit I just bid").
Interaction volume sits at v2-alone's level; the standing rule remains the
most interactive variant measured.

**THE 500-ROUND EXPERT PROFILE UNDER v2 + THE STANDING-SUIT RULE (2026-08-13,
MEASURED, NOT SHIPPED; same harness):** bids/auction **2.60** (72.6%
contested, 39.0% opener re-entry, tail to TEN bids), overtakes 1.60/auction
with same-level overtakes the biggest class (42.2% — repeatable suit
ping-pong at one level is the new cheap rung) and jumps ≥2 down to 21.2% of
overtakes; openings mean 3.06 (25.6% at 1); settled mean 4.68
(2.4/7/8.2/18.2/34.4/26.4/3.4%); made **60.6%** / set 35.2 / Null 4.2, and
per-level make degrades smoothly (95% at 3 → 41% at 7); Doubles 22.8%
(doubled avg −13.0, defender's doubled set avg 52.5); sacrifices **31.2%**
of rounds (avg −15.6, a third of them doubled) — the watch item, since
unlimited suit returns make denial wars cheap to conduct; charged final rise
0/+1 in 53.6% of rounds. Measured by `tools/jump_report.py` over 500
arena checkpoints, mirror exactly +0.0000.

**SHIPPED AT 3 (2026-08-14)** after the 1000-deal-per-arm sweep below.

**THE OPENER MAY PASS — an experiment, OFF as shipped (`OPENER_MAY_PASS`,
2026-08-14).** Classic has always forced the opening bid, and the campaign's
reason stands on its own terms: a free pass is strictly better than a bad
contract, so the floor cluster becomes a pass-out. The jump bonus makes that
worth re-testing, since a cheap opening is now a PRICED commitment rather
than a free option. With the flag on, nothing standing behaves exactly as
skat's open pass — the first hands the deal over, the second throws the hand
in and `_redeal`s the same opener — so no new machinery was needed beyond
three fixes the flag exposed:
* **`_redeal` hardcoded `mode="skat"`**, a latent bug that would have
  re-dealt a classic room as a skat one. It reads `mode_of(g)` now.
* **`apply_pass`/`apply_move` take an optional `rng`**, forwarded to the
  redeal only. Production omits it (fresh entropy, unchanged); a PAIRED
  arena must pass one, or the two flips of a deal draw different
  replacements and the pairing silently breaks — the mirror stops reading
  +0.0000, which is exactly how this was caught before any numbers were
  taken.
* **`rules.opener_may_pass` on the wire** (optional, default false), with
  `legal_bids`/`step` mirroring it; `Step::Redeal` already priced a
  pass-out at 0 for skat and needed no change.
Measured via `DIS_OPENER_PASS=1`; `jump_report.py` reports opener-pass and
pass-out rates per ATTEMPTED auction (a thrown-in hand is re-dealt and bid
again, so attempts = rounds + pass-outs).

**THE JUMP RATE IS A WEAK DIAL BETWEEN 2 AND 4 — measured at 1000 DEALS PER
ARM, 2026-08-13** (`DIS_JUMP_SET`, v2-alone setup, deal-paired across arms,
mirrors exactly +0.0000). The structure — charging the opening at all — did
the work; the rate only fine-tunes. Across 2 / 3 / 4:
* **monotonic, and the reason to have a dial at all**: mean opening 3.21 /
  3.09 / 3.05, settled mean 4.89 / 4.72 / 4.71, settled-at-6 30.9 / 27.6 /
  25.1%, doubled-round EV −9.8 / **−4.9** / −14.6.
* **flat inside noise**: bids/auction 2.23 / 2.22 / 2.31, contested 69.4 /
  68.8 / 71.7%, made 54.6 / 57.5 / 57.3%, Doubles 21.8 / 22.6 / 22.6%,
  sacrifices 26.9 / 25.4 / 27.2%, jump share of overtakes 33.3 / 31.8 /
  30.4%.
* **3 stays.** It has the flattest settled distribution (effective levels
  5.36 vs 5.06/5.24), the highest make rate, the lowest sacrifice rate and
  the only doubling EV near fair. The 500-deal read of this sweep had 3j's
  make rate at 60.0% and 2j's settled-6 at 30.0%; doubling the sample moved
  those to 57.5% and 30.9% while every ordering above held.

**THE v2-ALONE PROFILE WAS RE-CONFIRMED AT 500 ROUNDS (2026-08-13; 300 fresh
deals via the arena's `DIS_DENOM_RULE=used` arm pooled with the original
200):** every headline held within a couple of points — bids/auction 2.15 →
2.19, contested 65.0 → 68.8%, openings mean 3.04 → 3.07 (still flat:
21.6/20.2/18.8/17.8/13.8/6.6/1.2, max share 21.6% — the flattest opening
distribution of any variant), settled mean 4.55 → 4.63
(2.4/7.4/11/19.6/28.8/25.6/5/0.2), sacrifice 25.0 → 25.4%, overtake mix
static (same-level 29.7 → 29.8%, jumps ≥2 32.8 → 31.5%). The two that moved
most, both inside 2σ of a 200-sample: made 65.0 → 60.0% and Doubles 26.5 →
24.2% (doubled avg −7.5 → −5.5). The 200-round numbers below are kept as the
original record; treat the pooled figures as the profile.

**THE 200-ROUND EXPERT PROFILE UNDER v2 ALONE (2026-08-13; opening charged,
denomination forever-ban still on; same harness as v1's below):** bids/auction 1.77 → **2.15**, contested 52.8 →
**65.0%**, opener re-enters 16.8 → **29.0%**; openings mean **3.04**, spread
1–4 (19.5/21.5/22.5/17/13/5/1.5%); settled mean **4.55**, the smoothest
distribution any variant produced (3/7.5/12.5/21/27.5/22/6/0.5%); made
**65.0%** / set 31.5 / Null 3.5, with per-level make degrading smoothly to
~50% at the top (the chronic self-play overbidding largely corrected — the
climb past the make point now costs jump bonus too); Doubles 26.5% (doubled
avg −7.5, defender's doubled set avg 54.7); sacrifices 25.0%; +1 is the most
common overtake (37.6% of 1.15/auction) and the charged final rise is live
in ~85% of rounds. ~~The residual limiter on auction length is the
denomination forever-ban — a climb burns a suit per rung — which is what
`DENOM_RULE` "standing" addresses.~~ **THAT CLAIM IS REFUTED (2026-08-16):**
the suit-priced ladder measurement shows a same-level overtake costs MORE
difficulty than a level raise (1.13 points against 1.00) while paying the same,
so the rungs the forever-ban withholds are rungs nobody wants. Relaxing
`DENOM_RULE` does not lengthen auctions. See "THE SUIT-PRICED LADDER —
RESOLVED".

**THE 500-ROUND EXPERT PROFILE UNDER v1 OF THE RULE (2026-08-13; opening
exempt from the jump; k=8 one tree, talon model, dd-resolved, mirror exactly
+0.0000)** — v1 is superseded by v2 above, and this profile is WHY; recorded
because the 2026-08-11 profile (the comparison baseline below) taught that
these numbers evaporate otherwise:
* **The cap play is gone and openings moved UP**: opens-at-1 30.1% → 12.2%,
  mean opening 3.53 → 4.31, now unimodal at 5–6 (48.8% combined). With no cap,
  a low opening no longer holds the reply down — so underbidding lost its
  point, and the opener names value instead. Settled mean 4.63 → 5.28; the
  old settled spike at 3 (25%, the cap line) dissolved to 2.6%.
* **Auctions run 1.77 bids** (47.2% one-bid, 52.8% contested, 16.8% see the
  opener re-enter). Interaction concentrates on LOW openings: opens ≤3 draw
  1.3–1.7 overtakes/auction where opens ≥5 draw 0.3–0.5 — a low opening is
  now an invitation, not a cap.
* **The bonus binds**: only 15.8% of rounds settle on a final bid that jumped
  ≥2 (the ones the bonus charges), jump share of overtakes falls 63.6% →
  2.5% across opening levels 1→6, and 32.0% of all overtakes are jumps
  (sizes +2:52 +3:34 +4:23 +5:13 +6:1 over 500 auctions).
* **Outcomes**: made 45.0% / set 49.4% / Null 5.6% (was 56.8/38.8/4.5).
  Doubles taken 19.2% (was 27.2%), and doubled rounds average −15.3 for the
  declarer (defender's avg doubled set pays 52.4). Sacrifices 23.2% of
  rounds, averaging −19.8. The old profile's open question stands, sharper:
  settled 5–6 make only 43.8%/35.6%, so self-play still overbids the make
  point — whether the payoff asymmetry rewards it is unmeasured.

## A BID IS PRICED BEFORE IT IS MADE (2026-08-17)

Two rows in the classic auction panel, both `BidWorth`: what the STANDING
contract is worth, under the one-line headline, and what the SELECTED bid would
be worth, under the Bid button — the price sits where the decision is taken.
Both read `makes N · down for N`.

* **`down` is the CHEAPEST way to lose it** — the set base plus a single point
  short — because how far short you finish is not knowable at bid time, and the
  number grows with the shortfall. The copy read "down FROM" for exactly two
  hours to signal that floor and was changed to **"down FOR"** on request: it
  parallels "makes", which reads better beside it. So the row states a FLOOR in
  the voice of a fixed price — a deliberate trade of precision for symmetry, and
  the thing to know if it ever reads as a promise.
* **The jump is measured from the STANDING level**, which is what the set bonus
  actually charges for, so leaping shows its own cost: at level 5 it reads
  "down for 23" climbing a rung and "down for 47" opening straight there.
* **Priced off the LEVEL alone**, so it fills in the moment a rung is picked
  rather than waiting for a denomination — the suit changes who can outrank the
  bid, never what it pays.
* **Every term comes off `/catalog`** (`set_level_rate`, `linear_make_bonus`,
  `flat_make_bonus`, `flat_set_penalty`, `jump_set_bonus`,
  `classic_short_penalty`, and the Double's `double_make_mult` /
  `double_base_mult` / `double_jump_mult` / `jump_doubled` /
  `doubled_short_penalty` / `double_ramp`), never a literal in the JSX — the
  same `payoff_terms` discipline the bot rides on, one surface further out.
  `tests/test_bid_worth.py` holds the arithmetic to `_terms_for`'s own answer
  across every level and four jump sizes, undoubled AND doubled, and asserts
  the client reads each term off the catalog rather than hardcoding it.
* **The rows RESERVE their height** (`min-height` on `.dis-worth`) and carry no
  placeholder text, for the same reason `ContractLine` does: the keypad
  underneath must not move when the first bid lands.

**AND ITS BROWSER GATE MUST NOT DEPEND ON WHO OPENED, which cost a deploy.**
The standing-contract row only carries text once a bid has landed, so the first
check sampled it at one instant and passed locally and failed in CI — where the
harness's own seat opened, so nothing stood. The render gate is a REQUIRED job,
so Build/Upload/Deploy were skipped and the frontend simply never shipped: green
locally, red in CI, and the only symptom is the user not seeing the change. The
check now reads the BID PICKER's row instead (`disBidCheaply` returns what it
saw), which fills from local state on every bid the harness makes and is
therefore seat-independent; the auction block keeps only claims true whoever
opened — the height reserve, and "whatever it shows is a price".

## THE CLIENT HAS ONE PRICE LIST — `pricing.js` (2026-08-18)

`contractPrices(catalog, mode)` + `payoffFor` are the whole client-side mirror
of `_terms_for` / `payoff`. Everything that states a number about scoring goes
through it: the auction's two `BidWorth` rows, the Kontra prompt's now/doubled
table, the contract box's "makes" and "set pays", the result panel's maths line,
and the paper scorecard below.

**It was extracted because the second copy had already gone wrong.** `rules.jsx`
was updated with the 2026-08-16 re-price and again with the Double's move to
base ×1 / jump ×2 the next day; the BOARD was not, and by 2026-08-17 three of
its surfaces were priced by hand against a list the game no longer charged —
the Kontra prompt still doubling the set base and ramping the shortfall, the
contract box the same, the result panel printing `(N + stake) × 2`. Nothing
failed, because nothing is scored from them: the server prices every settled
round itself, so a wrong number here pays out correctly and only LIES to the
player while they decide.

* **Two fallbacks, and they answer different questions.** An absent MODE means
  the plain ×2 (`_terms_for` reads the dials with `.get(mode, doubling)`); an
  absent CATALOG means render what classic ships. Collapsing them into one `??`
  turns classic's base ×1 back into a ×2 the moment the fetch fails.
* **The result panel's set line decomposes only what it can PROVE.** It prices
  the same contract through the mirror and compares against the row's own
  `set_base`; if they disagree — a round scored under an older price list, no
  catalog — it prints the base whole rather than a decomposition that lies.
* **`test_bid_worth.py` is the gate** and it now also asserts the NEGATIVE:
  neither `Dissonance.jsx` nor `scorecard.jsx` may read a scoring term off the
  catalog directly. A screen that starts multiplying a level by itself is a
  second price list, which is the thing that just cost three surfaces.

## DISSONANCE PLAYS OFFLINE — the browser referees its own room (2026-08-18)

The fourth game to get an offline vs-AI mode, and the first whose ENGINE had to
be written for it. Spender, CoC and Duel each carry a full `engine.rs` in their
crate already, because their searches simulate whole games; this crate models
CARD PLAY only (`state.rs`), since that is all the solver ever needed. The
auction, the talon swap, the Double and the per-seat redaction lived in Python
alone — fine for a refereed room, useless on a plane.

**The four pieces, and where each one lives:**

| piece | where | why there |
|---|---|---|
| the rules | `rust-cores/dissonance-core/src/classic.rs` | one referee, gated against Python |
| the prices | `games/dissonance/pricing.js` | already the client's one mirror of `_terms_for`/`payoff` |
| the room | `games/dissonance/offline.js` | IndexedDB saves + the per-decision bot loop |
| the AI | the existing wasm search | it was already client-side; this needed nothing |

* **`classic.rs` NEVER SCORES, and that split is the design.** When the
  thirteenth trick lands it sets `phase: "over"` and leaves `result` null; the
  driver prices the round and banks the match through `pricing.js`. Composing
  the price list a third time — in the language furthest from the tests — is
  the drift `payoff_terms` exists to prevent, and a wrong number there PAYS OUT
  SILENTLY, which is the worst place to be wrong and the least likely to be
  noticed.
* **It works on `serde_json::Value`, not a struct.** The frontend renders
  `view_for`'s output and the save IS the game dict, so the JSON shape is the
  contract; a struct with derived serde would put a second spelling of thirty
  keys between the port and the thing it must match, and every mismatch would
  surface as a board that renders slightly wrong rather than a type error. It
  runs once per move, never in a search loop.
* **Card COMPARISON is not re-implemented** — `state::beats` and `cards::esuit`
  are the solver's own, so "what beats what" keeps its single owner, Grand
  included.
* **CLASSIC ONLY, refused at the door.** Minor is this machine at another trick
  value (nearly free, not done); skat is a second auction, a declinable talon, a
  declaration, announcements and Kontra/Re; **dummy is impossible here** — the
  crate is two-seat to its bones, the same reason `client_searchable` already
  refuses it online. `any_other_mode_is_refused_at_the_door` pins it.
* **HARD, not Expert.** Expert's edge is the auction TREE, which needs
  `auction.search` — the priced settlement table `auction_search_payload`
  builds. The driver does not ship it, so an "Expert" offline room would
  silently BE Hard: the exact label-says-Hard-plays-Normal failure this repo has
  paid for twice. The hub offers Hard and says so.
* **The talon model is not shipped either** (`auction.swap`, the fitted swap
  weights). It is optional on the wire, so the leaf prices each world's deal AS
  DEALT — worth about −1.5 points of auction accuracy against the online tier.
  Stated because it is a measured cost, not an unknown.

**THE GATE IS 120 RECORDED ROUNDS, REPLAYED MOVE BY MOVE**
(`tools/gen_classic_fixtures.py` → `tests/fixtures/classic.jsonl` →
`rust-cores/dissonance-core/tests/classic.rs`, which CI already runs via
`rust-dissonance.yml`). Both seats' views are compared after every single move.
* **Digest per step, full views on both ends.** Recording every view whole came
  to 72KB a round — 8.6MB, twenty-odd times the largest fixture here. The
  per-step check is FNV-1a over the canonical JSON; the two full views are what
  makes a failure diagnosable AND are the canonicalisation control, since a
  Python/Rust formatting difference would otherwise hide as thirty identical
  digest misses.
* **Verified non-vacuous by injecting two regressions**: a flipped trick parity
  (caught at round 0 step 7) and a same-level overtake into a lower-ranked
  denomination (caught by the full-view control, which named the field).
* `test_classic_parity.py` asks the CORPUS what it contains — a same-level
  overtake, a seat out of denominations, both halves of the swap and the
  Double — because a gate is only as good as the states it replays, and a
  corpus is exactly the thing that quietly stops covering something.

**THE ARMED REQUEST IS THE SERVER'S, FIELD FOR FIELD, AND THE ONE I LEFT OUT
COST AN AFTERNOON.** The driver arms `ai_search` exactly as `main.py` does so
the component's pool effect needs no offline branch at all. The first version
shipped `{options}` alone; `wire.rs` also needs **`phase`** and **`declarer`** —
whoever would be DECLARING under those options, which at the Double is NOT the
seat being asked. Without them every worker errored, the main thread's filter
dropped them without a word, and the round sat in the auction forever. Same
silent shape as the online bug that section already records.

**…AND THE PHASE THE SERVER KEEPS FOR ITSELF FROZE EVERY ROUND THE BOT DECLARED
(fixed 2026-09-26).** Online, the talon and the SWAP never reach the browser —
`CLIENT_AI_PHASES` leaves them out and the server bot plays them. The offline loop
had no such line: it armed the bot's swap as a plain search, the pool answered
"play card N", the referee refused a card play in the swap phase, and nothing
re-armed — a board with no button to press. It surfaced as a "flaky"
`offlineDissonance` (Pages, `edd28958`) only because an offline deal is random
and the bot declares on some of them. Now: the bot STANDS PAT offline
(`onlyMove`, always legal), and any refused bot answer plays
`applyOfflineBotFallback` — the offline analog of the server finishing a decision
the browser could not — so a refusal costs a move, never the round. The gate
FORCES the case (it passes until the bot declares, up to four deals, and asserts
the trick). **Open: the fitted swap** — worth ~+1.5 to a declarer; the arithmetic
already exists as `bid::SwapPolicy::choose` in the Rust core, but the worker does
not expose it and the weights reach the browser only on an armed online auction.

**A note on the browser gate, because it looks like a softened claim and is
not.** `offlineDissonance` flips the network off only once the search pool has
loaded. localhost runs no service worker, so a page taken offline before its
workers have fetched the worker file and the 300KB wasm can never load them —
the bot then answers nothing, which is a property of the HARNESS, not the
feature (in the product the hub's Download button has already cached both).
Everything after the flip — the referee, the search, the trick fold, the save
and a reload — runs with nothing answering.

**The wasm grew 66.8 → 117.7 kB gzipped (+51 kB)** for `serde_json`'s
serialiser and the referee. It is fetched only when a room arms a searching
tier, which is exactly the audience for offline play, and the download entry in
the hub is ~350 KB — the smallest of the four, because here the AI and the
referee are the same artifact.

## THE PAPER SCORECARD — for a game played with real cards (2026-08-18)

A lobby modal (`scorecard.jsx`, the `extra` slot of the shared create row,
beside Rules) that keeps score for a CLASSIC game played away from the site.
Two names, then per round: the declarer, the contract, the final jump, Kontra,
and the declarer's trick points — and it prices the round, spells the
arithmetic out the way the result panel does, and runs the match to
`MATCH_TARGET`.

* **It is the only screen that COMPUTES a payout** rather than quoting one the
  server settled, which is exactly why it goes through `pricing.js` and why the
  test file grew a `payoffFor`-vs-`engine.payoff` arm.
* **NULL NEEDS ITS OWN TOGGLE, and this is not a UI preference.** The points do
  not settle it: 0 points is "no scoring trick at all" (the consolation, 20 to
  the declarer) or "one even trick and two odd ones" (a set, paid to the
  defender). So the toggle appears exactly where it is reachable — a total at or
  below zero — and never above it.
* **The level and denomination pads are the BOARD's own** (`.dis-bidgrid` /
  `.dis-denoms`): a card kept beside a live game should be entered on the keys
  it is played with.
* **`localStorage` only.** A real-life match runs an hour and the tab gets
  closed; none of it is worth a room or an account. Round rows store the SCORES
  they were computed with, so a card in progress cannot silently re-price under
  its players.
* **The shared kit gained one optional `extra` node** in `LobbyCreateRow`, and
  the button wears `.lby-extra` rather than `.lby-rules` — the render gate
  counts Rules buttons by that class, and a second one wearing it reads there as
  a duplicate. Covered by `screens.mjs`'s `dissonanceScorecard` block, which
  EVALUATES the arithmetic the panel printed and requires it to equal the score
  banked, so the check carries no price list of its own.

### …AND IT IS IN THE OFFLINE HUB TOO, because that is the only screen you can REACH with nothing answering (2026-08-18)

The card was already network-free — `localStorage` plus `pricing.js`, with
`catalog` optional and the shipped classic list as its fallback — so the thing
standing between it and a table with no signal was never the arithmetic. It was
the DOOR: the Dissonance lobby sits behind the boot ping, so with no connection
you never get past the loading screen. `/offline` is the one route the boot gate
skips, so the card is opened from there as well as from the lobby.

* **The import is EAGER, in the shell, and that is the whole point.** A
  `React.lazy` chunk is only in the service worker's cache once it has been
  FETCHED, so a card meant for a signal-less table would be missing exactly when
  it is wanted — and it would fail silently, as a spinner. The entry chunk is
  fetched on every load and cache-first in `sw.js`, so riding along in it is what
  makes the promise true. Measured cost: entry **350.19 → 374.26 kB raw, 106.77
  → 115.01 kB gzip (+8.2 kB)**, and the Dissonance chunk *fell* 235.13 → 229.84
  since the card left it.
* **THE CARD NOW CARRIES ITS OWN CHROME** — `bidpad.css` (the board's bid keys
  and the suit inks, which the card borrows) and `scorecard.css` (the `.dsc-*`
  rules), both split out of `Dissonance.css`. The board composes them too, so
  opening the card from inside a room injects them twice, identically: one copy
  on disk, nothing to drift. Appending them after `Dissonance.css` is safe
  rather than lucky — every other rule mentioning those selectors is strictly
  more specific (`.dis .dis-bidgrid button` in a phone `@media`, the two
  `.dis-game .dis-table > .dis-auction` blocks, `.dis-denoms button small`,
  `.dis-result`/`.dis-clear .dis-suit-*`), so source order decides none of them.
  A new EQUAL-specificity rule for a bid key belongs in `bidpad.css`.
* **The gate blocks the API origin and then opens the card**, which is the claim
  rather than "the modal renders": `page.route("http://localhost:8000/**", abort)`,
  then `/offline`, then Open. It also MEASURES that the card is dressed — the
  pad's fifth-width key and its 9px radius — because a DOM-only check passes just
  as happily over an unstyled card, and unstyled is exactly what a missing
  stylesheet looks like.

## The round-end panel says POINTS or SCORE, never both as "scored" (2026-08-09)

The round has two quantities that are both "how much", and the panel used one
verb for both. They are now fixed vocabulary, in the classic/minor result
panel and in `rules.jsx`:

* **points** = TRICK points, the currency the contract is measured in;
* **score** = what the round pays onto the scoreboard.

So a made round reads *"Alice bid 4♠ and took 3 extra points"* over
`(4 × 4) + 3 = 19 to Alice`, and a set one *"…finished 2 points short"* over
`4 + (5 × 2) = 14 to Bob`.

* **The formula is COLOUR-KEYED to the sentence and deliberately NOT
  simplified.** The contract level is plain full-strength text, trick points
  are blue, the score is the panel's green (`.dis-n-lvl` / `.dis-n-pts` /
  `.dis-n-score`), so the `3` in "took 3 extra points" and the `+ 3` it turns
  into are visibly one number. The old line reduced through an intermediate
  (`4 × 4 = 16 + 3 = 19`); the shape is now constant — `+ 0` on a contract
  brought home exactly included, because a formula whose SHAPE moves with its
  values has to be re-parsed every round.
* **A DOUBLE IS REPORTED AS THE DIFFERENCE IT MADE (2026-08-09)** — "Doubling
  earned Alice 55 — 110 instead of 55", not "the set base went 9 → 20". The old
  line narrated an internal term rather than the bet the player had just
  watched, and quoted `level - 1` for the undoubled base: the **pre-2026-08
  N−1 rule**, a number the game had not charged in months. `_finish` now puts
  `undoubled` on the row — this same round re-scored through `payoff` with the
  bet taken off — so the comparison is the engine's arithmetic, not a second
  copy in JS. Two properties make the panel's magnitude comparison sound and
  both are asserted: a Double can never flip WHO won (it scales both ends and
  the ramp only adds), and it can only raise the stake it was placed on.
* **A DOUBLE MULTIPLIES THE OVERTRICK RATE TOO, and the old line dropped it**:
  it printed `4 × 4 × 2 = 32 + 3 = 38`, which does not add up, because the tail
  only ever showed the raw points while the payoff charged `over_bonus × over`.
  Doubling now rides inside the term it multiplies.
* **Twice a hardcoded rate has outlived the number it copied.** `+ 4 × short`
  survived the 4 → 5 move in BOTH the skat maths line and the side panel, each
  printing a sum that did not reach the score displayed beside it — the score
  was right, only the story about it was wrong, so nothing failed.
  `_finish_skat` now puts `short_rate` on its row (classic already did) and
  both lines read it. **`test_the_result_row_carries_every_term_its_own_score_
  needs` is the gate**: it plays real rounds in all three modes, forces the
  Double so the ramped branch is reached, and re-adds the row's own terms to
  demand they reproduce its score. Verified non-vacuous by putting the stale 4
  back — it fails.

## Double — classic's defender bet, priced for the SACRIFICE (2026-08-07)

A `double` phase between the classic swap and trick 1, the DEFENDER to act.
`g["doubled"]`, `classic_doubling`, `apply_double`.

**IT BETS ON THE LEAP AND THE SHORTFALL (candidate B', shipped 2026-08-17)**,
which is the two things a SACRIFICE actually has. The fixed stake does not
double, so doubling a cheap jump-free contract is no longer nearly free:

    made   N^2 + 4   ->  2 (N^2 + 4)    (the overtrick rate doubles with it)
    set     2N + 2   ->  2N + 2         (`DOUBLE_BASE_MULT` = 1 — UNCHANGED)
      + 6j the final leap  ->  x2       (`DOUBLE_JUMP_MULT`)
      + 5 a point short    ->  10       (`DOUBLED_SHORT_PENALTY`)
    Null        20   ->  20             (the one exception)

**IT WAS BRIEFLY UNIFORM (2026-08-16, one day)** — everything x2 except Null,
the same shape as skat's Kontra — and the paragraphs below that read as though
that is the rule are that day's. What they establish still holds where it is
about the SHAPE (a doubled round having no house edge, Null never scaling); what
they say about a doubled SET is one price list out of date. See the formula
sweep below for how B' was chosen and what it costs.

| shape | doubled shortfall | reward vs shortfall | break-even L1 |
|---|---|---|---|
| `DOUBLE_RAMP = 1` | 6, 7, 8, 9 per point | quadratic | 0.44 |
| flat 5 both ways | 5 per point | **BLIND** | 0.56 |
| `DOUBLED_SHORT_PENALTY = 6` | 6 per point | linear | 0.45 |
| **= 10 (shipped)** | **10 per point** | **= the undoubled round** | **0.26** |

**Under the uniform Double that break-even column WAS the contract's own
make/set ratio** — 0.26 / 0.33 / 0.42 / 0.50 / 0.57 / 0.62 for levels 1-6 — with
no house edge either way, which is what made "everything x2" statable in four
words. **Base x1 deliberately gives that up**: the defender's winnings now come
only from the leap and the shortfall, so break-even RISES on a jump-free
contract and the bet is priced for the sacrifice rather than for the miss. The
grid is asserted term by term instead of as one multiplier —
`test_the_double_scales_each_term_by_its_own_multiplier`,
`test_a_set_contract_pays_2N_and_its_own_per_point_rate`,
`test_the_break_even_odds_are_what_the_bot_policy_rests_on`.

**THE CONSEQUENCE TO KNOW, because it reads as a bug and is not one:** at levels
1-3 doubling pays even against a 1-point near-miss, because `L^2 + 4` is smaller
than `2L + 2 + 5` down there — being set already costs more than making pays.
That is the make curve being quadratic off a base of 4 against a linear set base,
not the Double being lopsided. The crossover is
exactly `L^2 + Fm > (SL x L + Fs) + short`, i.e. L > 3, and
`test_where_a_near_miss_double_stops_paying` derives it from the price list rather
than pinning 4.

**MEASURED AGAINST THE COMPLAINT THAT PROMPTED IT** ("the bots never double even
for sacrifices"), 192 dd-resolved Expert self-play rounds per arm at
`DOUBLE_MARGIN = 20`, same harness, adjacent deal windows:

| doubled shortfall | dbl% | on FAIL | on MADE | disc | defender gain | declarer EV |
|---|---|---|---|---|---|---|
| 6 a point | 15.6% | 21.4% | 13.2% | +8.2 | **−2.11** | +11.79 |
| **10 a point (uniform)** | **41.7%** | **68.4%** | **24.1%** | **+44.3** | **+6.16** | **−6.19** |

**It fixed the thing it was aimed at, and by more than the rate suggests.** The
bots were doubling 15.6% -- not "never" -- but those doubles were EV-NEGATIVE and
barely discriminating. Uniform doubling flips the sign (−2.11 → +6.16 a round for
the defender) and takes discrimination from +8.2 to +44.3, with 68.4% of failed
contracts doubled against 24.1% of made ones. So the earlier diagnosis -- that
this was a threshold fault rather than a pricing one -- was WRONG: the reward
really was too small for the search to find the bet.

**TWO THINGS TO WATCH, both product decisions rather than bugs:**
* **41.7% is a lot**, against a set rate of 39.6% -- the defender is doubling
  nearly everything that fails, plus some. The earlier campaign called 59% "far
  too much", though that was when doubling LOST money; it now pays.
* **Declaring got markedly less attractive**: the declarer's mean payoff moved
  +11.79 → −6.19 across the same arms, an 18-point swing, and the set rate itself
  rose 29.2% → 39.6% (the auction search prices the double branch, so a scarier
  Double feeds back into the bidding). At n=192 that second figure carries ±7pp
  and should be re-measured before anything is built on it.

**IF 41.7% READS AS TOO LOOSE IN PLAYTEST, THE FIX IS FREE AND IS NOT A SCORING
CHANGE.** The same recorded run prices every threshold: `DOUBLE_MARGIN` 32 gives
24.0% doubling at discrimination +34.4 and gain +5.73, and 36 gives 20.8% at
+35.2 and +5.99 -- most of the benefit at half the rate. Re-run
`tools/dblsweep.py --live 20` over `dsh10/` to see the full column.

### REDUCING THE *OPTIMAL* DOUBLING RATE — THE FORMULA SWEEP (2026-08-16)

The uniform Double doubles 41.7% of contracts in bot self-play, and the honest way
to thin that is to make doubling correct less often rather than to handicap the
search with `main.DOUBLE_MARGIN` (which suppresses a bet the search has correctly
found, and leaves a HUMAN opponent doubling at the old rate anyway).

**The dials, and the one ratio they all move.** `DOUBLE_MAKE_MULT`,
`DOUBLE_BASE_MULT`, `DOUBLE_JUMP_MULT`, `DOUBLED_SHORT_PENALTY` — all per-mode,
all shipping as DATA out of `_terms_for`, so none needs a wire field or a Rust
edit. What they control:

    p* = risk / (win + risk)                  the odds the defender needs
    risk = (make_mult - 1) x make
    win  = (base_mult - 1) x stake  +  (jump_mult - 1) x 6j
           + (short_mult - 1) x short x (points short)

**EQUILIBRIUM doubling rate per candidate** (`cfrlab curvedbl`, real-play cache,
2000 deals, 200k CFR+ iterations each — the equilibrium is the right instrument
here because "optimal rate" is the question):

| candidate | base | jump | **DBL taken** | **of those SET** | loss | settled max | bids |
|---|---|---|---|---|---|---|---|
| **A uniform x2 (shipped)** | 2 | 2 | **30%** | 36% | 0.51 | 41 (L4) | 2.70 |
| **B base x1** | 1 | 1 | **17%** | **55%** | 0.65 | 50 (L5) | 3.16 |
| B' base x1, jump x2 | 1 | 2 | 28% | 46% | **0.50** | 42 (L5) | 3.10 |
| C make x3 | 2 | 2 | 27% | 37% | 0.52 | 41 (L4) | 2.71 |
| F jump x1 (`JUMP_DOUBLED=False`) | 2 | 1 | 26% | 42% | 0.58 | 47 (L5) | 2.65 |

**ONLY `DOUBLE_BASE_MULT = 1` ACTUALLY MOVES THE RATE.** Everything else clusters
at 26-30% against the shipped 30%; B alone reaches 17%, and it simultaneously has
the best PRECISION by a wide margin (55% of its doubles land on a set, against
36%). It doubles less AND better, which is the combination worth having.

**Why the others fail, and it is the same reason each time:** the defender's
winnings are dominated by the doubled fixed stake, which is large exactly where
the make base is small. Raising the make multiplier (C) adds risk but leaves that
term alone, so low-level doubling stays cheap. Taking the jump out (F) trims a
term most contracts barely carry. `base_mult = 1` removes the dominant term
directly: the defender's winnings then come ONLY from the shortfall, so the Double
stops being a bet that the contract MISSES and becomes a bet on HOW BADLY — which
is the sacrifice-vs-near-miss discrimination the retired ramp existed to buy,
obtained from a multiplier instead of an escalator.

**THREE COSTS OF B, none of them hidden:**
* **It kills the jump INVITATION.** Measured, a jumped level-2/3/4 contract goes
  from inviting the Double (win 23/31/39 against risk 8/13/20) to protected (win
  5). The jump PRICE survives untouched -- `6j` is still in the undoubled base --
  so leaping still hands the defender a fatter set; what goes is the Double's
  extra leverage on it, which is arguably a double-count. `DOUBLE_JUMP_MULT = 2`
  (candidate B') buys the invitation back, but at 28% it gives up nearly all of
  the rate reduction, so the two cannot both be had from these dials.
* **The worst distribution match of the five** (loss 0.65 against 0.50-0.58), and
  a settled distribution 50% concentrated at level 5 -- against the standing "no
  level above 40%" preference. A is already marginally over at 41%, but B is
  clearly over.
* **It raises bids/auction 2.70 -> 3.16**, which is a bonus against the separate
  goal of longer auctions, but is a live change to the auction and not just to the
  Double.

**B' SHIPPED THE NEXT DAY (2026-08-17): `DOUBLE_BASE_MULT = 1`,
`DOUBLE_JUMP_MULT = 2`,** i.e. the leap and the shortfall double and the fixed
stake does not. Re-measured at two CFR+ seeds on the same 2000-deal cache, its
doubles land on a SET 46-47% of the time against uniform's 36%, at 27-28%
against 30-31% and a marginally better distribution match (loss 0.49-0.50 vs
0.51-0.54) — a PRECISION change rather than a rate change. Plain B (jump x1)
reaches 17% but spikes the settled distribution to 50% at level 5 and throws the
jump invitation away, so the rate reduction and the invitation could not both be
had from these dials and the invitation won. `main.DOUBLE_MARGIN` was re-fitted
20 → 12 with it, off a 192-round recording made at live margin 0 (the sweep can
only price upward from the margin a run was recorded under).

**The tables below are PRE-2026-08-16 measurements** that chose the ramp. Their
SHAPE arguments stand -- ordinary failures come up a median of 2 short with 48%
by exactly 1, sacrifices a median of 4, and that is still why the reward has to
track the shortfall -- but every absolute EV in them was computed under a
different price list and a different doubling rule.

**The ±10 stake re-priced this bet (2026-08-11), in the sacrifice's favour:**
the doubled stake pays the defender 20 more on a set while the risk only grew
10, so doubling a median sacrifice (4 short at level 6) moved from knife-edge
(−0.13 EV) to genuinely paying (+14.3), and the break-even curve's top
compressed 0.93 → 0.85. The tables below are the PRE-STAKE measurements that
chose the ramp; their shape argument stands, their absolute EVs do not.

**Kontra is symmetric and so is this now (2026-08-16)** — but the thing to keep
hold of survives the change, for a reason that was never about symmetry:
DECLINING IS NOT WORTH ZERO — it is worth the undoubled contract, which is a live
payoff either way. So `auction_payoff_options`
prices BOTH branches as their own options, each carrying its own move, and the
Hard tier picks the better. Skat's Kontra can ship one option and decide on its
sign precisely because its doubling cancels out of the comparison.

**MEASURED, and the first measurement was of the WRONG SCENARIO.** Doubling
risks N² and, flat, wins only N — so break-even climbed 50/67/75/80/83/86%
across levels 1-6 while contracts bid NORMALLY fail only 4/9/18/24/37/56%
(2500 self-play rounds). Against ordinary bidding no level was a profitable
Double, and that is what an initial measurement said, full stop.

**It is not for ordinary bidding.** The mechanic is for the SACRIFICE: a player
about to concede a big made contract overtakes at a level they cannot reach,
purely to deny it — 6♣ over 5♠, because 25 points is worse than being set. And
sacrificing PAYS at every level (gain over conceding +3.3 / +5.7 / +9.1 / +13.0
at levels 3-6), so it is a default response, not a desperation move.

**THE RAMP IS WHAT MADE THE MECHANIC WORK, and the reason is one line of data:**

| when a contract is set | median shortfall | short by exactly 1 |
|---|---|---|
| ordinary bidding | 2 | **48%** |
| sacrifice | 4 | 13% |

Scaling the doubled base by N taxes the LEVEL, which both cases share. Ramping
taxes the SHORTFALL, which only a sacrifice has. Measured EV of doubling:

| scheme | ordinary lvl 6 | sac @5 | sac @6 | worst round | sacrifice RATE |
|---|---|---|---|---|---|
| 2N flat (first ship) | −13.82 | −1.63 | −0.24 | 48 | 36% → 36% |
| 3N flat | −10.62 | +1.86 | +4.41 | 54 | 36% → 36% |
| **2N +1 ramp (SHIPPED)** | **−11.70** | **+4.56** | **+9.20** | **93** | **36% → 23%** |
| 2N +2 ramp | −9.58 | +10.75 | +18.64 | 138 | 36% → 7% |

`2N +1` was chosen because it turns Double on exactly at level 4 and above,
which is where sacrificing becomes clearly profitable, and TAXES the play rather
than removing it: a level-6 sacrifice still nets the sacrificer ≈+2.6 over
conceding. `2N +2` drives the rate to 7%, i.e. it deletes a strategic option.
The tail matters too — a match runs to 100, and `+2` allows a single round of
138.

**Opening aggression does not move at all** (1.82 under every scheme): Double
answers a SETTLED contract, and the opener acts before any of that is known.
What moves is the END of the auction — settled level 6.20 → 6.08 → 5.89 as the
sacrifice-overbidding it was made of gets taxed away.

**Do not re-measure this against self-play alone**: the shipped bots did not
sacrifice at all until the pass was priced, so a sweep can only ever produce the
first row.

### THE SEARCHING TIERS' DOUBLE WAS PRICED FROM THE WRONG SIDE (found + fixed 2026-08-14)

**`auction.declarer` names who would be DECLARING under the options, and
`double` was missing from the list of phases that answer "the opponent".** It
read `g["auction"]["declarer"] if phase in ("kontra", "re") else seat`, and at
the double phase the acting seat is the DEFENDER while the options describe the
declarer's settled contract. `wire::answer_auction` derives TWO things from that
one field — which side the determinized worlds are solved for (the declarer
LEADS trick 1) and the SIGN the answer comes back with — so the tier solved the
wrong position and then returned it declarer-signed and un-negated. The
defender's argmax picked the branch best for the DECLARER.

* **It failed in this tier's signature way**: two legal options, a plausible
  number on each, nothing red, and a room that says Hard. The only visible
  symptom was a Double taken about as often on contracts that made as on ones
  that failed — which reads like a hard judgement call, not a bug.
* **MEASURED against exact ground truth** (`tools/dblprobe.py`, 150 real rounds
  driven to the double phase, each branch resolved by an exact double-dummy
  solve of the REAL deal): the shipped search found **2 of the 13** contracts
  that deserved a Double and doubled **16.8% of contracts that MADE against
  15.4% of contracts that FAILED** — no discrimination at all. Naming the real
  declarer takes it to **9 of 13** (69.2% of failures) with false alarms
  unchanged at 23, and agreement with truth 77.3% → 82.0%.
* **THE FIX IS SERVER-SIDE AND REACHES A CACHED WASM**, which is why it needs no
  expand/contract: the artifact derives both the solve's side and the sign from
  this field, so an older bundle starts pricing the Double correctly the moment
  the server stops lying to it.
* Gated by `test_client_ai.test_a_settled_contract_names_its_real_declarer_not_
  the_seat_being_asked`, written over ALL THREE settled-contract phases rather
  than the one that broke — kontra and re were always right, and the next phase
  of this shape should not have to rediscover the rule. Verified non-vacuous
  against the old tuple.

**...and the Double is now priced by an EXACT CONTRACT SOLVE** (`bid::price_
exact`, routed on `auction.phase == "double"` — a field the server has shipped
since the auction search and nothing read, so this needed no wire change). Every
other auction decision chooses between ~50 candidate CONTRACTS and can only
afford the points proxy; the Double chooses between two STAKES on one settled
contract, so the exact answer costs `2 x k` solves. Scoped to `double`:
skat's `kontra`/`re` are the identical shape and a one-word change, but skat is
separately unmeasured; `declare` is not settled and must keep the proxy.

* **The proxy and the exact solve DISAGREE on single worlds** (swept over levels
  2-8 in `wire::exact_double`; at level 4 alone they agree on every deal, which
  is a fact about level 4 and not about the pricers) — but summed over the 8
  sampled worlds the two got the same SIGN on all 150 probe rounds and flipped
  **zero decisions**. The magnitudes move a lot; the argmax does not.
* So on the probe's distribution the declarer-side bug was the whole effect, and
  what binds at this decision is the defender's genuine uncertainty about the
  declarer's 7 unseen hand cards — not leaf accuracy. Read the arena numbers
  before spending anything more here.

### THE DOUBLE'S TWO KNOBS, TURNED ON 2026-08-14 (`bid_prior` + `double_margin`)

Fixing the side (above) made the search DISCRIMINATE (+7.8pt → +49.2pt) and made
it double far too much: 59% of contracts, against a set rate of 38%. Four
500-deal arms, all `expertt` self-play, k=8, dd-resolved:

| arm | | dbl% | discrimination | defender gain/round |
|---|---|---|---|---|
| A/B | side fixed, uniform sampling | 59.0% | +48.7 | **−0.53** |
| C | + jump outside the ×2 | 53.8% | +50.5 | −1.38 |
| **D** | **+ belief prior** | 54.4% | **+54.5** | **+0.68** |

**1. THE AUCTION IS EVIDENCE, AND THE SAMPLER WAS THROWING IT AWAY.**
`determinize` resamples the declarer's unseen cards UNIFORMLY — but they WON an
auction. Measured (`tools/beliefprobe.py`, 400 rounds at the double phase, 200
resamples each): the declarer's real holding sits at the **0.765 percentile** of
the uniform resample, above its median in **87.5%** of rounds, and the gap GROWS
with the bid (0.706 at level 3 → 0.850 at 6). Every world the searcher looked at
handed the declarer a weaker hand than they held, so contracts looked likelier
to fail than they were. This is poker's **range** problem.
* The fix is importance sampling — draw 24 candidates, weight `exp(tilt ×
  strength)`, keep one in proportion (`bid::BidPrior`). **`bot._BID_TILT` is a
  FLAT 0.35**, and the per-level map it replaced is a lesson worth keeping:
  fitted against SERVER-BOT auctions the bias rises with the level (0.706 at 3
  → 0.850 at 6), because that bot maps strength onto a level monotonically.
  **Expert does not bid that way** — it opens low to cap, sacrifices, and picks
  levels off exact solves — and against it the bias is FLAT (0.742 / 0.708 /
  0.707 at levels 4/5/6, 163 positions recorded mid-arena via `ARENA_DEALS=1`
  and re-fitted with `beliefprobe --from-arena=`). The rising map therefore
  OVER-corrected exactly where contracts settle, reading 0.357 at level 5 and
  0.383 at 6 — the sample came out biased the other way, which makes a defender
  double too LITTLE and compounds with `DOUBLE_MARGIN`. Pooled it read 0.421;
  flat 0.35 reads **0.496**. Same shape as `_DUMMY_LEVEL_NEEDS`' lesson one
  level up: **which bot did the bidding IS the distribution.**
* **It moved the CALIBRATION, which is the claim**: the mis-calibrated middle
  band (edge 10–20/world, 85 rounds) really made 50.6% — a coin flip against a
  ~40% break-even — and under the prior it makes **39.1%**, i.e. break-even.
* **A tilt of 0 or one try is uniform sampling BYTE FOR BYTE** (same RNG draws,
  asserted) — a control that is merely similar confounds the A/B.
* **Only the CURVE crosses the wire, not `hand_strength`.** The likelihood is a
  modelling choice, not a rule: it must ORDER two holdings the way a bidder
  would, not reproduce the bidder. So no second copy of the suit-length terms
  and no parity fixture to hold two copies to one answer.
* **CLASSIC ONLY.** The tilt map is a set of quantiles on classic's level
  distribution, and a level map does not survive the distribution moving — the
  lesson `_DUMMY_LEVEL_NEEDS` already paid for.

**2. `DOUBLE_MARGIN` (classic), charged to the doubled branch before the
argmax.** Taking the better of two estimates is a SELECTION, and the winner is
partly whichever one's noise favoured it. The search's confidence is well
ORDERED but mis-calibrated: edge 0–5/world really made **65.4%**.
* **Swept OFFLINE off ONE run**: the arena records the search's own two sums at
  every double, and the decision is `(on − off)/k > margin`, so a recorded pair
  prices every threshold exactly (`tools/dblsweep.py`). The `swaplab` method —
  label the decisions once, evaluate any policy for free — instead of a
  50-minute run per value.
* **20 was where two independent routes agreed UNDER THE OLD PRICES**: where the
  calibration curve crossed break-even AND where the swept gain peaked. Effect
  then: gain/round **−0.53 → +2.25**, precision 60.0% → 72.5%, rate **59.0% →
  31.7%**. With the prior as well, **30.1% and +3.02**.
* **20 STILL STANDS. A 2026-08-16 attempt to re-fit it to 4 was WRONG and was
  shipped for about two hours before being reverted — see the section below.**
  The re-fit read `dblsweep.py`'s margin column as absolute when it is a DELTA
  on the live margin, so the "20 is a bug" row was really margin 40. Measured on
  322 recorded doubles under the new prices, 20 doubles **26.1%** at
  discrimination **+30.4** and defender gain **+2.00/round** — healthy.
* Per-mode, because the units are payoff points and minor's run a quarter the
  size. Minor's own sweep has not been run; 0 is exactly today.

**MEASURED AT LAST: +1.289 +- 0.767 payoff/round, CI [+0.522, +2.056]**, 500
CRN-paired dd-resolved deals, `expertt` (both knobs) against **`expertot`** —
the same tier with the old Double. Self-play mirrors read exactly +0.0000 by
construction, so an asymmetric arm is the only way to ask this at all; an `o`
in an expert tier's suffix is that arm, and it deliberately KEEPS the
declarer-side fix and the exact contract solve, so the number is the two KNOBS
and nothing else. For scale it sits beside the auction tree's own +1.19 +- 0.32.
* **Quote the pooled figure, never a shard.** The four read +2.42 / +0.68 /
  +0.12 / +1.93 — a spread that would have supported any story at n=125.
**ATTRIBUTED, AND IT IS ALL THE MARGIN** (250 paired deals per arm, each against
`expertot`; `DIS_DBL_MARGIN=0` and `DIS_BID_PRIOR=0` isolate one knob each):

| arm | payoff/round | verdict |
|---|---|---|
| both knobs (n=500) | +1.289 +- 0.767 | clear of zero |
| **prior ALONE** | **+0.161 +- 0.623** | **spans zero** |
| **margin ALONE** | **+1.889 +- 1.032** | clear of zero |

**AND THE MECHANISM IS WHY REFINING THE PRIOR CANNOT HELP — this is the part to
keep.** The prior does exactly what it claims: it drags the mis-calibrated
middle band onto break-even (contracts at edge 10-20/world really made 50.6%
without it and 37.5% with it) and lifts discrimination +48.7 -> +56.8. **But the
optimal margin is 20, which discards every decision below edge 20 — and above
20 the two calibrations are identical (29.0% vs 28.6%).** The prior fixes
precisely the rounds the margin has already decided not to double. They are two
treatments for one disease and the margin gets there first.
* Swept both ways offline (`SWEEP_TIER` filters the asymmetric arm to one
  tier): both curves peak at **margin 20** with the same peak — defender gain
  +2.25 without the prior, +2.34 with it. The prior reaches it from a lower
  double rate (19.8% vs 31.7%) at slightly better precision, and no higher.
* So **conditioning the prior harder (on the auction SEQUENCE, or on the tier's
  own pricer as the likelihood) is dead**: both sharpen the estimate in the
  0-20 edge band, and those decisions are not doubled at the shipped margin.
* **THE BELIEF THREAD IS CLOSED, and it is worth saying loudly because the
  mechanism is compelling enough to be retried.** The bias is real and large
  (0.765 percentile, 0.704 against Expert, still 0.617 at trick 11); correcting
  it genuinely centres the sample (0.704 -> 0.521); and it converts to
  **+0.161 +- 0.623 at the Double** and **+0.617 +- 2.522 in card play**.
  A MEASURED BIAS DID NOT IMPLY A MEASURED GAIN, by two independent
  instruments — the third route this repo has found to CAMPAIGN.md's verdict
  that PIMC's residual error is strategy fusion, which no better world
  distribution can fix.
* Caveat on the sample: the prior-on sweep is n=101 against the off-curve's
  n=483, and its top two edge buckets hold 14 and 6 rounds. What makes the
  reading safe is that a completely different instrument (the paired arena)
  agrees.

* **The split between the two knobs is NOT yet attributed** (`DIS_DBL_MARGIN=0`
  and `DIS_BID_PRIOR=0` each isolate one against `expertot`). Until it is, do
  not spend on refining the prior: this file already records two mechanisms
  that were real and did not pay.

**THE CARD-PLAY PRIOR IS UNRESOLVED — do not read it as a win OR a loss.**
Extending the belief prior to the 13 card decisions is on the branch and
UNSHIPPED. `tools/priorlab.py` measures it per DECISION (regret against a
double-dummy oracle, paired on the identical position, the oracle paid for only
when the two variants disagree): over **298 disagreements, +0.617 +- 2.522**,
better on 18.5% and worse on 20.1%. The per-trick shape is +2.42 / −2.07 /
+2.24 over tricks 1-4 / 5-8 / 9-13, which no mechanism yet explains.
* **A METHOD NOTE, paid for twice in one night.** At n=59 this read **−1.44 +-
  7.54** and was called as "clearly not the win" — the sign then FLIPPED at
  n=298. An interval spanning zero is not a direction, and this is the third
  time this file has had to record that lesson.
* The bias it corrects is real and large all round (`tools/decayprobe.py`: the
  declarer's remaining holding at the 0.769 percentile at trick 1, still 0.617
  at trick 11). **A measured bias did not imply a measured gain**, which is the
  finding worth keeping — consistent with CAMPAIGN.md's verdict that PIMC's
  residual error is strategy fusion, which no better world distribution fixes.

**THE TILT, RE-FIT ON THE FULL 500:** bias 0.704, best single tilt **0.30 →
0.521**. Shipped 0.35 lands at 0.462 — past centre but inside the flat part of
the curve, so it stays.

**RUNNING ANYTHING LONG IN THIS CONTAINER: FOREGROUND ONLY.** Background
processes die within ~2 minutes of a turn ending, `setsid`/`nohup`
notwithstanding — the sandbox goes with the turn. Four separate relaunches made
essentially no progress; five ~9-minute FOREGROUND blocks finished 250 deals and
100 rounds. Checkpoint per unit (`ARENA_CKPT`, `PRIORLAB_CKPT`) and the kill at
each block's end costs nothing.

**AN ORACLE'S FLOOR IS NOT A REAL DEFENDER'S FLOOR** — worth stating, because the
first reading of these numbers got it wrong. Doubling always pays more on a set,
so a defender who KNEW the outcome would double every failing contract (38%
here). That does not bound a real one: skipping a kill you cannot identify is
cheaper than doubling a contract that makes, so a well-calibrated defender
doubles LESS than the oracle rate. 20–30% was reachable all along, and by the
THRESHOLD rather than by re-pricing.

**`JUMP_DOUBLED=0` IS NOT PART OF THIS AND STAYS OFF.** It measured worse for the
defender (−1.38 vs −0.53 at margin 0) because a doubled set pays less. Its case
is the TAIL — median doubled set 55 → 50, worst observed 98 → 86 — and the
declarer's EV (+9.06 vs +8.21). That is a product judgement about swing size,
now decoupled from the rate question the threshold answers.

* **The server tier declines every Double**, because it cannot TELL the two
  apart. The obvious signal is the defender's own holding and it does not
  work: the set rate is 38-43% within normal play at EVERY strength gate and
  78% within sacrifices at every gate. A gate at strength 11 fires on 58% of
  sacrifices and 6% of genuine high contracts, which only pays if sacrifices
  are half as common as real contracts. They are not.
* **The Hard tier decides by search, and this is the point.** What separates a
  sacrifice from a real contract is whether the target is REACHABLE, which is a
  solve rather than a rank sum. It gets both branches priced and takes the one
  worst for the declarer, so it doubles precisely when the contract is dead.
  Needed NO Rust change and no wasm rebuild — `contract_from_json` and
  `options_from_json` already read every term generically, which is the return
  on shipping the scoring as numbers instead of as a second copy of the rules.
* **The Null escape is real**: 9-10% of sacrificing declarers duck to the flat
  12, which Double does not touch. Already counted in the EV above.

**Inserting a phase is not free**, and this is the shape of the cost: 160 tests
went red at once, essentially all of them drivers that walked swap -> play in
one step. The one REAL bug among them was `view_for`'s `sees_shown`, which read
`phase in ("swap", "play")` — so the classic declarer lost sight of the talon
for exactly one phase, and the Hard tier would have been handed a different
out-of-play set for the Double than for the opening lead immediately after it.

## The bots do not cheat — and this is TESTED, not asserted (2026-08-07)

Every bot is handed the WHOLE game dict. `bot.act(g, seat)` and `_ask_the_client`
both take `g`, because the server owns the state and there is nowhere else for it
to come from — so **nothing structural stops a bot reading the opponent's hand;
only the code does.** `tests/test_bot_fairness.py` is what says it still holds.

**The method is INVARIANCE, not grep.** Re-deal every card the seat cannot see,
back into the same slots, and demand the identical answer — a bot that peeked at
any of them would have to change its mind about at least one rewrite. It catches
a peek through any number of helper layers, which `grep hands[1 - seat]` does
not. Driven over whole games in BOTH modes, so it covers the auction, the talon,
the declaration, Kontra and all thirteen tricks. Two of the eight tests guard the
guard — a planted cheat must FAIL them, or a reshuffle that quietly did nothing
would report a clean bill of health.

What a seat is entitled to: its own hand; every pile TOP; the MIDDLE pile's
bottom (dealt face up); `shown` if it earned it; the public record. Hidden: the
opponent's hand, **both** seats' OUTER pile bottoms, and the unshown talon.

* **IT FOUND A REAL ONE.** `bot.hand_strength` valued a hand as
  `playable() + every pile bottom it owned` — but only the middle bottom is face
  up, so the server bot (Easy/Normal) bid knowing **two cards the rules never
  gave it**, in both auctions and in the talon swap. Not opponent knowledge, so
  it never played a card it could not have played; it simply rated its own hand
  more accurately than the human across the table could rate theirs. Fixed by
  counting the two unknowns at `_UNKNOWN_RANK_VALUE`, the deck mean — dropping
  them outright would under-rate every hand by two cards and silently re-tune
  every threshold in `_level_for`. Measured effect on 150 rounds/mode: classic's
  settled level fell 4.13 → 3.77 and contracts made rose 75% → 79%; skat barely
  moved (4.02 → 3.99, 64% → 63%).
* **The Hard tier was already clean, by construction.** The armed request ships
  `engine.view_for(g, seat)` — the same builder that feeds a human seat, so there
  is no second projection to keep in step — and `wire.rs` reads a seat's own
  outer bottoms as `UNKNOWN` and **fails closed**: if `pool` does not partition
  into exactly `opp_hand_n + hidden_slots + n_out_hidden` it returns None and the
  decision goes back to the server bot rather than searching a lie. The wire test
  `a_seats_own_covered_outer_bottoms_are_hidden_from_it_too` pins the asymmetry
  on that side too, and checks the resampling is real rather than a constant.
* **The wire test asserts on the SERIALISED payload**, not field by field — the
  failure this repo has already paid for is something that nests a whole-game
  snapshot, which defeats per-field redaction while every field check passes.
  Scanning the blob for card numbers cannot work at all: a card id and a trick
  count are both small integers.
* **THE MIRROR IMAGE IS REAL AND IS THE COST OF A CLIENT-SERVED TIER.** In a
  vs-AI room on Hard, the armed request carries the BOT's view to the human's
  browser, because the human's browser is what runs the search. So the human
  *can* read the bot's hand out of devtools. `_handle_client_ai_ready` refuses to
  arm unless the room really is vs-AI on a client tier, which is what keeps it
  away from a human OPPONENT — but the bot's own opponent necessarily holds it.
  The repo-wide framing ("tampering only weakens the tamperer's own opponent") is
  about MOVE quality and does not cover information leakage in a hidden-info
  game. Moving Hard server-side is the only fix, and Render's free tier
  (~0.1 CPU) is why it is client-served in the first place.

## A game is a MATCH of rounds (2026-08-07)

`MATCH_TARGET` — **200 in classic, 100 in skat**. A round is one deal; a game is rounds
played onto a running total until one side reaches the target. **Re-measure if
the bases or the payoff arithmetic move** — the target is a product decision,
but the round count it buys is not a guess, and skat was a median of 8 to the
same 100 before its bases were re-priced by colour.

**THAT WARNING CAME DUE (2026-08-17): classic MOVED 150 → 200.** The 150 was
fitted on 2026-08-11 to hold a match at ~9 rounds, but the 2026-08-16 re-pricing
and the Double's re-shaping took the mean absolute round transfer to **~41**, so
150 had quietly drifted to buying a median of **six** rounds. Re-measured by
bootstrapping 4000 matches off 192 recorded self-play rounds under the shipped
scoring:

| target | median rounds | p10–p90 |
|---|---|---|
| 100 | 4 | 2–6 |
| 150 | 6 | 3–9 (what it had drifted to) |
| **200** | **8** | **5–11** (shipped) |
| 250 | 10 | 7–14 |

200 restores roughly the length 150 was chosen to buy. **Note the old note's
bracketing doses now read BACKWARDS** — it said "200 stretches to 13" because a
round paid far less then, which is exactly the drift this entry is about. Skat's
median 11 (6–18) predates the overtrick bonus and is still un-re-run.

A per-mode DICT, because the modes score on different
scales and nothing requires them to agree: a classic round pays level² + the
flat 10 stake (up to 154, flat 20 for Null), a skat one base × level × the
announcements (up to 60, flat 20).

**WHY:** one deal can simply be bad, and the auction is the only lever either
player has against it. Over a match the deals average out and what is left is
the bidding judgement, which is the part worth playing.

* **`phase == "over"` still means the ROUND is over — `is_over()` now means the
  MATCH is.** That split is the whole feature and it is load-bearing in
  `main.py`: `_sync_status_from_game` and `_bot_should_act` both read `is_over`,
  so between rounds the room stays `playing`, keeps its sockets, and stays out
  of the finished-games list. `round_over()` is the other half.
* **`may_act(g, pid)`, not `turn_pid(g) == pid`.** Between rounds the round is
  scored and NO seat is on turn, yet either player may deal the next one — a
  question the single-seat turn model cannot express. It lives in the engine
  rather than as a special case in the move handler.
* **`next_round` carries the round it was pressed on.** Both players clicking at
  the same moment is the normal case, not an error either should see; without
  the token the second click either reads as "the round is still being played"
  or — far worse — deals a third round over the top of the second. A mismatched
  token is a silent no-op, the same idempotency discipline as the client-AI
  decision counter.
* **The opener alternates every round, and is DERIVED from the round number**
  (`opener_for_round`), never flipped from whatever the last deal used. Not
  every deal is a round: a skat hand both players pass out is thrown in and
  dealt again, and a redeal that flipped the opener knocked the alternation out
  of phase, so which seat opened round 4 depended on how many hands got passed
  out along the way. `_redeal` therefore keeps the SAME opener — it used to
  flip, on the reasoning that passing out of a bad seat should not be free, but
  the replacement deal is fresh cards so there was no bad seat left to escape.
  A match saved before `first_opener` existed recovers its phase from where the
  alternation actually is rather than restarting at seat 0.
* **What the opener alternation is FOR is the BIDDING, not the lead** — the
  DECLARER leads to trick 1 (`_start_play`), whoever opened. The opener names a
  contract into no information at all, and in classic mode may not pass.
* **A skat pass-out redeals WITHOUT counting as a round.** `_redeal` carries the
  match through untouched, `round` included — a deal nobody played is not a
  round.
* **Walking out ends the MATCH.** `abandon_result` banks the forfeit and then
  closes the match regardless of the target: there is nobody left to play the
  rest of it.
* **…and it LOSES it, at any standing (2026-08-11).** Every reader used to name
  the winner by comparing the two `match_scores`, so a player who quit while
  ahead was told "You win the match" and the lobby filed it under Won — quit
  while up and you kept the win. One contract's forfeit does not close a
  match-sized gap, so this was not a rounding case. The outcome is now SHIPPED,
  not derived: `_match_result_keys(g, forfeited_by=...)` writes `match_winner`
  (a seat, or −1 for a draw, which only a played-out match can be) and both
  readers use it. **The scores stay honest** — the forfeit is banked and nothing
  is invented, so the row still shows who was ahead; it just does not call them
  the winner. Both readers keep a `??`/`is not None` fallback to the score
  comparison, which is right for a row saved before the field existed and for a
  one-round game with no match at all.
* **The final standing is written onto the RESULT ROW** (`match_scores`,
  `match_target`, `match_over`, `round`), not left only in `g["match"]`. The
  lobby history reads a stored result and never the live game.
* **…and the lobby History row must READ it (fixed 2026-08-07).** It shipped
  reporting `result["scores"]` — the score of the DEAL that happened to end the
  match — so a match taken 100–84 listed as "Won 9–0" and one lost by the
  opponent crossing the line listed a loss on a round the reader could not tell
  apart from the whole game. The keys were on the row from the day matches
  shipped; nothing read them. Now: `match_scores` (falling back to `scores`, so
  a genuinely one-round save is still right), plus `rounds`/`target` so the meta
  line says "12 rounds to 100" instead of narrating the last deal's contract —
  which is one deal in ten and read as the headline. The contract line is kept
  for the one-round case, where it *is* the whole game. `tests/test_history.py`
  drives real played-out matches through a temp sqlite file, because a
  hand-built result row only pins the shape the test itself wrote.
  A match can also end LEVEL (a forfeit closes it regardless of the target), so
  the row has a third state — the shared kit's `tie` class, which CoC and
  Dontminion already use.
* **The match keeps a SCORECARD, `match["rounds"]`** — one line per round
  banked: the contract, the declarer's trick points against what they promised,
  and the round's scores. The side panel's "Match to 100" box renders it under
  the running total (`MatchCard`), because a total says who is ahead and nothing
  about how: which rounds were bought cheaply, who has been declaring, whether
  the gap is one big set or six small ones.
  - **Every line is DERIVED from the result row, in `_bank_round`.** The three
    finishers (`_finish`, `_finish_skat`, `abandon_result`) now build their
    result dict FIRST and hand it over, so the scorecard cannot disagree with
    the panel that narrates the same round — re-reading made/null/target off the
    board would have been a second copy of the scoring, which is what
    `payoff_terms` exists to prevent.
  - **A DOUBLED ROUND SAYS SO ON ITS LINE (2026-08-09)** — `doubling` on the
    row, rendered as a gold `×2` / `×4` chip after the contract. Without it a
    doubled round sat in the box as an ordinary line with a surprising number
    beside it, which is precisely the row a reader wants explained. It carries
    the MULTIPLIER rather than either mode's word for the bet, so classic's
    Double and skat's Kontra-then-Re land in one field and the box needs no
    idea which auction the room ran; it is read off `res` (skat already had
    `doubling`, classic has `doubled`), so no rule is re-derived here. Absent
    on a round banked before it shipped, which reads as undoubled — correctly.
    Gated by `test_the_scorecard_line_says_a_round_was_doubled` and the skat
    Kontra/Re case beside it, both verified non-vacuous.
  - **`rounds` is `setdefault`ed, never created in `new_game`** — same reason
    `match_of` exists. A match already in progress when this shipped has no
    scorecard and must go on banking rounds rather than KeyError; its earlier
    rounds are simply gone, and there is nowhere to recover them from.
  - A pass-out redeal adds no line, because it is not a round.
  - It rides in `view_for`'s `match` (wholly public, like the totals) and
    through `persist.py` untouched. ~8 small keys x a median of ten rounds.
* **A SCORECARD ROW OPENS THE ROUND'S STORY (2026-08-11; board-shaped
  2026-08-12)** — click or right-click (contextmenu, which is also what a
  long-press fires) lays the round out face up, **in the board's own shape**:
  a felt on the left (opponent's hand-then-piles across the table, your
  piles-then-hand nearest you, the dummy between, the out-of-play cards in
  the middle where the trick lives, piles drawn with the board's buried-card
  peek), and a right column carrying the bidding and the settled contract —
  the live board's own split. Everything renders from the line's own banked
  data — `deal` (the snapshot, now taken in EVERY mode: dummy banks its three
  hands too, and the DD column refuses non-2-hand deals by COUNT rather than
  by mode) plus `reveal` (`_round_summary`: the auction log, `shown_at_deal`,
  the swap pair, `looked`, skat's announcements). The Double/Kontra/Re lines
  are synthesized from the row's `doubling`, the field the ×2 chip already
  trusts. Public by the same argument as `deal`: all of it is in the
  over-phase view already; the line just outlives that view. The redaction
  gate is `test_round_reveal.py` — banked lines only, a mid-round view never
  carries the current round's hands, forfeits bank neither deal nor reveal.
  Browser-gated in `screens.mjs`: 32 cards face up, shown+took = 3, closes.
* **THE DOUBLE LIVES IN THE CONTRACT DISPLAYS, NOT ACROSS THE SCREEN
  (2026-08-12).** The 2026-08-11 full-board ×2/×4 flash (`.dis-dblflash`) was
  removed on request — it covered the board at the exact moment the declarer
  wants to read their own lead. The bet's standing evidence is gold in three
  agreeing places: the felt's contract chip (`.dis-chip-mult.dbl`), a
  `.dis-dblrow` banner at the head of the side panel's Contract box, and the
  scorecard's ×2 chip — the same colour in all three, so the live round and
  its banked line agree about what the bet looks like.
* **PLAY'S TEXT SITS BESIDE THE CARDS ON A WIDE DESKTOP (2026-08-12), and
  the card budget follows.** The trick counter, the contract chip and the
  turn bar — everything the play middle says that is not a card — are one
  `.dis-playside` block: in flow under the trick on small screens, pinned to
  the ≥1200px rail (the auction/report treatment) on a wide desktop. With
  the middle holding nothing but the trick's own cards, `--dis-reserve-in`
  drops to **14rem at ≥1200px for ALL phases** (auction, play, report — the
  three rules share the number so the cards never change size, the property
  the gate asserts; growth tops out at +14.7% against the old 17.5rem on the
  tightest height-bound screens). 761–1199px keeps 17.5rem with the playside
  in flow. **The budget is keyed on `:has(> .dis-playside)`, not `ph-play`**:
  the completed-trick hold keeps the board up after the phase has flipped to
  `over`, and a phase-keyed budget shrank the cards for exactly that beat.
  `screens.mjs` asserts the playside sits beside the hand row's right edge.
* **THE PILE PEEK BELONGS IN THE DIVISOR, NOT THE RESERVE (2026-08-13), and
  that one line is why 1080p boards were 6-12% small.** The height budget is
  `(table height − reserve) / divisor`, and the reserve was carrying the two
  pile peeks — which are `0.24 × cw`, i.e. they GROW with the number being
  solved for. A fixed rem therefore has to be sized for the TALLEST display in
  its tier, so a 1080p board paid a 1600p board's peeks: **measured 66px of
  felt left unused at 1920x1080, 101 at 1600x900, 148 at 1366x768**. Moving
  them into `--dis-vden` (`5 × 1.4 + 2 × 0.24 = 7.48`) makes the budget exact
  at every height, and the reserve keeps only the genuinely fixed furniture
  (~97px = 6.2rem: two name rows and their gaps, the trick caption, the
  table's own row gaps). Cards: 1920x1080 **108 → 115**, 1600x900 84 → 91,
  2560x1440 159 → 162, 2560x1600 181 → 182. 1366x768 does not move — it is
  WIDTH-bound, which is the honest answer there.
  - **The rail and the flanks are the same budget seen from two ends.** The
    ≥1800px rail comment claimed its growth "costs the cards nothing at these
    widths"; measured at 1920x1080 the width term with a 23rem rail was 112.6px
    against a height term of 112.5 — dead even, so the rail was eating cards.
    The fix was NOT to narrow the rail (worth 2.4px of card and a visibly
    smaller panel) but to gate the FLANKS' own widening on height: a 1080p
    board keeps 17rem side columns, hands the middle 96px, and the width term
    goes back above the height term where that comment assumes it. The felt's
    type bump and its reserve ride the same gate, since they are what the
    bigger reserve pays for.
  - **A 1080p board cannot reach a 1600p board's card size and no budget can
    change that**: five card rows at 1.4 plus ~97px of furniture in ~940px of
    table is 115px, where 1600px of screen buys 182. The auction LOOKS like it
    has room because it shows four card rows and reserves five — that fifth is
    the trick, and equalising the phases is the property the gate asserts.
  - **DUMMY WAS CLIPPING ITS NEAR HAND AND NOBODY HAD MEASURED IT.** Same
    error one seat worse, plus a `--dis-rows` of 6 against a board that shows
    SEVEN card rows in play (three seats of hand + piles, plus the trick):
    measured **278px past the box at 2560x1600** and 118 at 1920x1080, with
    `.dis-game` clipping — so the whole near hand row was off the bottom of
    the screen in every dummy round at the resolution the mode was built on.
    Its budget is now one block (`--dis-vden: 10.52`, reserve 9.3/9.9/10.3rem)
    shared by all three railed phases, so a dummy board also stops resizing
    between the auction and play — it ran a 14rem reserve at the auction
    against 25 in play, a 106px card becoming an 80px one as the round
    started. Cards 152 → 125 at 2560x1600, and now they all fit.
  - **What is left over on a small window is the documented FLOOR, unchanged**:
    at 1280x720 and 1000x700 the cards sit at `3.4rem` and the board runs past
    its box on purpose (the panel gives way instead) — verified as pre-existing
    rather than introduced here.
* **A save with no `match` key is a single round and still ends at its own
  end.** `match_of()` is the only reader of `g["match"]` for exactly that
  reason — a game already in progress when this shipped must not crash and must
  not silently acquire a target it was never being played to.
* **`next_round` clears `room["_ai_search"]`.** A new deal makes any armed
  search a question about a game that no longer exists; the answer would be
  re-validated and thrown out, but the ARMING must not survive the deal.
* **The bot never deals for you.** `turn_pid` is None between rounds, so the
  scheduler finds nothing to do and the result panel stays up until a human
  presses Next round. `test_the_bot_never_deals_the_next_round_by_itself`.

## Every trick point past your contract is worth 1 (2026-08-07)

`OVER_BONUS = {"classic": 1, "skat": 1}` — a per-mode dict like `MATCH_TARGET`,
and like that one it currently reads the same in both while the modes score on
different scales. A made contract pays **N² + 1 × (pts − N)** in classic and
**stake + 1 × (pts − target)** in skat. Set is untouched; Null is untouched.

* **It ships through `payoff_terms` as an `over` term**, so `_finish` and the
  Hard tier's solver get it from one place — **change it and the bot follows with
  no bot code at all.** `dd::Contract.over` was already there as a *penalty* from
  the auction lab's burst experiments; it is now SIGNED (a bonus, negative for a
  penalty) so the sign convention matches the server's, and `forced_floor` passes
  −1. On the wire it is OPTIONAL, defaulting to flat, because a browser can hold
  a cached wasm older than the server.
* **FLAT, not scaled by skat's announcements or Kontra** — the `SKAT_NULL_VALUE`
  argument. Hand/Sharp/Open are promises about the CONTRACT, and running a
  per-point bonus through a ×4 would make one overtrick worth more than the rungs
  the ladder is built from.
* **It narrows the Null cliff, which was measured and deliberate.** "A cheap
  contract is a licence to duck" was priced against FLAT payouts: a made classic
  level-1 now runs 1 → up to 12 against Null's 12, and a skat stake of 6 runs
  6 → 15 against 20. Narrowed, not removed — and it is the number most worth
  re-running in `skatlab`, since the measurement behind it no longer describes
  the game.
* **`contract_score` now DELEGATES to `payoff`.** It held its own copy of the
  classic make/set rule, was reachable from the tests only, and would have gone
  on paying flat — a test agreeing with itself.

### The early end is SHELVED, not deleted

`_score_is_settled` stopped a round the moment the score could no longer change.
Its "cannot fail → stop" branch rested *entirely* on a made contract paying a
flat amount; with overtricks every remaining trick moves the score, so **every
round now runs all thirteen tricks.**

The predicate is kept whole and **gated on the TERMS, not on the mode** — put a
0 back in `OVER_BONUS` for a mode and the early end returns for that mode alone,
with no other edit. `test_no_round_ends_before_the_thirteenth_trick` drives both
halves (bonus on: never settles; bonus off via `monkeypatch.setitem`: the old
rule exactly, last-trick guard included), so the branch stays live and tested
rather than rotting into something that no longer compiles against the state
around it. `test_a_round_that_would_have_stopped_early_now_plays_on_for_the_bonus`
finds the seeds that used to stop and asserts they now run to thirteen — the same
deal both ways, so the difference is the rule and not the cards.

What the shelved rule said, kept because it was measured rather than assumed:
cannot-fail stopped, cannot-**make** played on (the defender is paid
`N + 4 × shortfall`, so every remaining trick still moves the shortfall);
Null got no early exit of its own; and it never stopped with ONE trick left,
because that beat is where the shortfall and the Null consolation are both still
live.

**`result.ended_early` is now always false, and the key stays.** The result panel
still reads it (`scored()` prints "at least N", because a stopped round's trick
TOTAL was not final even though its score was) — a stored result from before the
bonus can still carry it, and the shelf could put it back.

**`pts` sums to POOL only over a COMPLETED round** — still the correct way to
state it, and now unconditionally true. The four tests and one fixture generator
that learned it the hard way assert it flat rather than behind an `if`: a round
that ended early would be a real regression and must not read as the other half
of a legitimate pair.

**The Rust parity harness names a `MAX_LEVEL` contract on purpose, and it stays
that way.** The reference always plays all thirteen tricks, so `_game_from` has
to describe a contract that can never settle early — at its old level of 1 the
early end fired most of the way through most deals and every fixture's final
points diverged. MAX_LEVEL works because one player's ceiling is sweeping the six
+2 tricks; `test_rust_parity` asserts that relationship rather than assuming it.
The overtrick bonus makes this redundant *today* (nothing settles early any more)
— keep it, because it is the shelf's insurance: flipping `OVER_BONUS` back to 0
would otherwise silently truncate every fixture replay again.

## `shown` is the OUT-OF-PLAY SET, not a record of what was shown

Two questions, two fields, and collapsing them breaks the Hard tier silently.

* **`shown`** — the out-of-play cards this seat can place. A swap REWRITES it,
  so it keeps matching `out`: the taken card leaves, the discard takes its slot.
  This is what goes on the wire, what the in-round talon panel shows (a holding
  to count from), and what the client-side searcher reads.
* **`shown_at_deal`** — the three cards the declarer was actually shown, fixed
  at the deal and never rewritten. Only the round-end reveal reads it.
* **`swap_take` / `swap_give`** — which cards moved, **redacted until the round
  is over**: the defender learns THAT a swap happened and nothing more, which is
  the entire point of the discard going face-down.

**`out` IS AN ORDERED ROW, AND ITS ORDER IS A FACT ABOUT THE ROUND (2026-08-13).**
The three the declarer is shown are its first `N_SHOWN` (`test_engine` pins it),
and `apply_swap` replaces the taken card **in its slot**, so the discard ends up
exactly where the card it paid for used to be. Two readers were throwing that
away and both looked fine in isolation:
* **`_deal_snapshot` sorted it** (`sorted(g["out"])`), so the round's story laid
  the talon out by card id — an order the round never had. It is `list(...)` now.
  Nothing downstream read it positionally (the DD review takes it as a set for
  its integrity check, `persist` packs it as a sequence), so the order is free.
* **the report's talon grouped by CARD, not by SLOT.** It put "the three the
  declarer saw" on the declarer's side by testing membership in `shown_at_deal`
  — but after a swap the taken card is not in the talon at all and the discard
  is not in `shown_at_deal`, so the row came out **2 + 4** with the discard
  adrift among the cards nobody saw. The group is `shown_at_deal` with the take
  substituted by the give, which is precisely what the engine did to `out`. The
  discard takes the swap's own dashed badge rather than the shown ring: it is in
  the talon, in the right slot, and was never shown to anyone.
`test_round_reveal` pins both (the swap case and a DRIVEN stand-pat — the
shipped swap policy swaps in all 40 seeds the sampling test walks, so waiting
for a stand-pat round waits forever), and both fail against the old `sorted`.

**THE WIRE'S `shown` IS NOT OURS TO REDEFINE.**
`rust-cores/dissonance-core/src/wire.rs` treats every card in `view["shown"]` as
out of play and does exact card-count arithmetic on it — the unseen pool must
partition into the opponent's hand, the covered pile bottoms and the unplaced
out-cards, or `view_from_json` returns None. That contract is frozen by the
COMMITTED wasm, which cannot be rebuilt without `wasm-pack`, so changing what
the field means requires a rebuild in the same commit or it is simply a break.

Making `shown` the historical record put the taken card — by then in the
declarer's HAND — into the searcher's out-of-play set. The arithmetic stopped
balancing on every decision after a swap, all four workers returned "not a
searchable position", and the main thread's `good` filter dropped them without a
word. **The room played on at full speed, still labelled Hard, on the server
bot.** No exception, no console error, nothing red — and because it only bites
after a swap, it passed locally and went red in CI.

`test_every_card_the_wire_calls_shown_is_really_out_of_play` is the guard: it
walks a whole played round, both seats, and asserts `view["shown"] ⊆ out`. It
fails on 25 of 25 seeds against the broken version, because the bot swaps in
nearly every game — which is also why whether the HARNESS or the BOT won the
auction decided whether the browser gate passed.

The reveal's other half: it said "was shown" even for a skat **Hand** game,
where declining to look IS the announcement and the declarer never saw the talon
at all. The frontend gates that line on `sawTalon` (`!isSkat || game.looked`).

## Do not relitigate

* **EVERY BUTTON ON THIS BOARD IS THE GREEN, and `.btn` alone is not a button**
  (2026-08-07). `.btn` in the shared kit is GEOMETRY ONLY — padding, radius,
  font, `border:none`, and deliberately no background or colour, because the
  paint comes from a variant. This file carried **nine** bare `className="btn"`
  buttons and was the only file in the repo that did, so Bid / Start / Swap /
  Look / Next round / Back to lobby rendered as the browser's DEFAULT button
  face — measured `rgba(239,239,239,.3)` on `rgba(16,16,16,.3)`, a white chip
  with grey text on a dark green board. They are `.dis-gobtn` now (solid
  accent), and `.dis-annbtn` — a `#6fa8d8` blue borrowed from nothing, on a
  board with no other blue — is an accent OUTLINE, one step down from the solid.
  - **Gold was the wrong fix even though it is the kit's primary.** The lobby,
    the board, the selected bid and the turn badge are all `--accent`; gold is
    Spender's colour arriving through the same fallback that already dressed
    this game's lobby in the wrong accent once.
  - **`--accent-hi` and `--ink` are tokens now**, not hex literals repeated in
    eight places, so the go button, the bid toggles and the announcement outline
    agree by construction.
  - **Kontra stays red** (`#b8434f`, white text) and that is deliberate: it is
    the defender's one moment of leverage and reads as a threat, the same role
    the kit gives `btn-danger`. It is not an oversight to "fix".
  - Guarded by `shared/tests/test_btn_has_a_variant.py`, repo-wide, because this
    failed SILENTLY — nothing throws, the button works, and `smoke`, `screens`
    and the whole Python suite all ask whether a thing renders, never what
    colour it came out. Verified against the old file: it names all nine.
* **No card is ever dimmed** (2026-08-07). Every face-up card renders
  identically, playable or not; legality lives in the `play` affordance and is
  enforced server-side. Two earlier versions of this failed differently and both
  are recorded in the stylesheet: `opacity` let a pile's buried card show
  straight through its top so the two read as one smeared card, and the
  `filter: brightness()` that replaced it fixed the transparency while keeping
  the real problem — a hand that read as two different kinds of card.
  `screens.mjs` now guards the absence (no `dim` class, no reduced opacity, no
  filter), sampled MID-round: the check it replaced ran after the game was over,
  when every pile is exhausted, so it read all-zeroes on every run and could
  never pass.
* **The side panel's order is TALON → match → contract → last trick → points**
  (2026-08-07). The talon is the only panel there you play *from* rather than
  read after the fact — three cards you know are out of play is a holding to
  count from — so it sits at the top of the column, above the standing. It was
  fourth, under Last trick, which put the thing you paid the auction to see
  below two panels that only report. The phone rules drop Contract and Points
  (both duplicated elsewhere) and stack the rest, so the order carries there
  too.
* **Optional follow-suit is rejected.** With negative odd tricks it makes every
  odd trick fall deterministically to whoever leads it — 7 of 13 tricks lose
  all decision content.
* **The SERVER bot does not chase the Null consolation; the Hard tier does.**
  A declarer whose contract has gone wrong ought to switch to ducking every +2
  trick — but "has gone wrong" is a lookahead judgement, and Easy/Normal are one
  trick deep (reading it off the current total instead would throw away
  contracts they were still winning). Hard got it by searching the payoff
  instead of the points; that is the fix, and it is not portable to a policy
  with no search.
* **NULL AT A FLAT 12 (skat 20) DOMINATES A LOW CONTRACT, and this is measured,
  not speculative.** Classic levels 1–3 pay 1/4/9, all below 12; in skat, 13 of
  the 28 ladder rungs pay under 20 at ×1. So a declarer who bought cheaply has
  no reason to play for their contract at all — and the floor cluster puts ~42%
  of openings at level 1. The contract-aware Hard tier exploits it on sight
  (6–7 Nulls per 40 rounds against the points searcher's 0). **Flat is a
  DECISION, taken 2026-08-07 with this measurement in hand** — a cheap contract
  is now a licence to duck, and that is the intended shape of the escape hatch.
  Revisiting it costs no bot work: the search reads `payoff_terms`, so scaling
  Null or capping it below what it replaces is an engine-side change alone.
  - **THE OVERTRICK BONUS (same day) NARROWED THIS, and the measurement above
    was taken on FLAT payouts.** A made contract is now worth its stake plus
    every point past the target, and the declarer's ceiling is 12: classic
    level 1 runs 1 → up to 12 against Null's 12, and a skat stake of 6 runs
    6 → 15 against 20. The cliff is smaller and the Null rate should have
    fallen with it. **Nobody has re-run it.** The rate is a `skatlab` sweep and
    the same one the match-length medians want; until it exists, treat "6–7
    Nulls per 40 rounds" as describing a game that no longer ships.
* **The bot scheduler's staleness guard is `_position_key`, and EVERY
  state-advancing action must appear in it.** Two schedulers can be in flight at
  once (`_handle_move` starts one, so does every reconnect), and the guard used
  to be `(phase, trick, len(history), len(auction.log))` — which skat mode broke
  twice over: `look` changes none of those (the duplicate re-sent it and was
  rejected as illegal), and a redeal resets all of them to their opening values
  (so a thrown-in hand reads as "nothing moved"). `redeals`, `looked` and
  `swapped` are in the key for exactly those two reasons.
* **Easy tier used to `KeyError` on its first bid.** Its blunder branch fired in
  *every* non-play phase and read `opt["levels"]`, a key the v2 auction stopped
  returning; the scheduler logged and abandoned the room. It is now scoped to
  the two phases where a careless choice is still a *legal* one.
* **v1 saves are voided on load, not migrated.** A 28-card save's card indices
  mean different cards under `suit = c // 8`; the prod table was verified
  EMPTY when v2 shipped, so the guard in `load_game_to_memory` is for
  completeness.
* **No `rng_state` is persisted.** All randomness is spent in the deal and
  nothing draws later, so storing one would be ~600 words nothing reads (the
  Where Wolf? lesson). This also sidesteps the "pack every copy or none" trap.
* **Card play strength is understood.** Determinizations saturate at k=8; the
  cheating oracle beats PIMC by 0.79 pts/round and most of that is irreducible
  hidden information. Opponent-consistency resampling, Vote/Quantile
  aggregators and an IIMC blend were all measured and all washed — see
  `CAMPAIGN.md` before spending on any of them.
* **The floor cluster was structural, not a scoring problem.** ~42% of openings
  sat at level 1 under *every* scoring configuration tried. It is caused by the
  opener being forced to bid with nowhere to put a weak hand; only unlimited
  jump overtakes (42.7% → 2.7%) or letting the opener pass (→ 0%) moved it, and
  both cost the maneuvering game. Shipped config keeps forced opening.

## The completed-trick beat (frontend, and it is timing — nothing else can see it)

A finished trick stays face up for `TRICK_HOLD_MS` (700) before it moves to the
Last trick panel, because the server clears `led` the instant the second card
lands. Three things about it are load-bearing, all three MEASURED in a browser
against a live backend (`screens.mjs`, "Dissonance's completed-trick beat"):

* **The hold covers `over`, not just `play`.** The thirteenth trick, and any
  trick that settles the score, ends the game in the SAME message that completes
  the trick, so a hold gated on `phase === "play"` skipped the one trick a player
  most wants to see: measured 700ms on every other trick and **0ms on the last**,
  swapped straight for the result panel. `wasPlaying` keeps that to a game that
  ended under you — opening a finished room from the lobby must not replay its
  last trick at you first.
* **The hold BLOCKS play** (`canPlay = myTurn && !heldTrick`). A trick takes
  ~600ms at full tilt against the 450ms bot floor, so a player who answered
  inside the hold was leading the next trick behind a screen still showing the
  last one: their card sat invisible, the opponent's reply landed in the same
  window, and two finished tricks ran together with a **single 18ms frame**
  between them. Nothing is swallowed — a card with no click handler also loses
  its `.play` affordance, so the hand visibly stops offering itself.
* **The trick line is about the trick you are LOOKING at.** `game.trick` has
  already moved on during a hold, so reading it there labelled the two cards
  with the next trick's number and the next trick's ±value.

The gate plays a whole game at full tilt and asserts every dwell; it reads
695–700ms on all thirteen tricks. A polling loop from Node cannot see a state
that lasts one frame, so it samples per `requestAnimationFrame` in the page.

## The board screen — pinned to the viewport, three columns wide (2026-08-10)

Nothing on a game screen may be below the fold: at any normal resolution the
whole board is visible and **there is no page scrollbar to have**. `.dis-game`
is `100dvh`, a flex column, `overflow: hidden`; the table takes what the header
leaves and is a `container-type: size` box, so the card budget reads the table's
**real height** (`100cqh`) rather than guessing from the window. Seats keep their
card-derived height; the variable-height panels (`.dis-auction`, `.dis-result`)
take the slack and scroll **inside themselves**, so a miscalculation shows up as
a scrollbar on one panel and never as a hand clipped off the bottom. Below 761px
wide or 600px tall the page scrolls instead — that is the honest answer for a
phone and for a window too short to fit a board plus an auction panel at any card
size.

**THE PHONE BUDGET IS THE FAN, AND THE STRIP IS WHAT PAYS (2026-08-13).** A phone
board is WIDTH-bound, and seven cards fill the width whatever their size, so
`row = 6 × strip + cw` — a bigger card is exactly a narrower visible strip, and
the only floor that matters is the 44px touch target. At 30% overlap the strip
measured 51px, i.e. 7px of slack nobody was using; **42% (`--dis-slots: 4.7`)
takes the card 66 → 75px with the strip still ~49.** The two numbers are a PAIR
(`slots = 7 − 6 × overlap`, plus ~0.2 because the term divides the TABLE's width
while the row is laid out inside the hand's, which is narrower by the seat's
padding — at exactly `7 − 6 × 0.42` the row came out 10px wide and the hand
WRAPPED, which on a phone is three cards on a second line rather than a fan).
Three other things had to move with it, and each was a place the phone paid for
its cards:
* **the auction's hard `--dis-cw: 54px` under 820px tall is GONE.** It made a
  small phone's cards smaller at the one moment a player is counting them, and
  it was buying a one-screen fit that measurement says never happened — a phone
  board plus its stacked side panels runs ~400px past the viewport in the
  auction and ~600 in play. A phone's card size is now one number in every
  phase, the property the desktop budget already holds itself to.
* **the bidding box keeps its height (`flex: 0 0 auto`) instead of being the
  item that gives.** It was `flex: 1 1 auto; min-height: 0; overflow-y: auto`,
  so bigger cards squeezed it into a nested scroller — 58px of hidden bid keys,
  inside a page that scrolls anyway, which is the worst of both (you cannot tell
  which box a phone flick will move).
* **…and then the auction table had to stop being a PIN.** It was
  `height: calc(100dvh − var(--dis-hdr))`, which is only safe while something
  inside is allowed to give: with the panel refusing, the fixed height had
  nowhere to put the extra and the near seat's fanned hand drew 13px past the
  felt and over the panel beneath it, its own z-index painting it on top. The
  base phone rule's `min-height` is the same number and already fills the
  screen; the table now grows the ~50px instead.
* `--dis-reserve` (the `100dvh` formula this tier uses) came 27 → 22rem, and the
  dummy's 29 → 24, for the same reason: it was reserving for a one-screen fit
  that does not happen, and the only thing it actually did was cap the cards
  below what the fan's width term already allowed. Dummy is height-bound on a
  phone, so that is the number deciding its card size: 45px → ~55.

`.dis-main` is a grid, and **every tier places all three items by hand**. The DOM
order is board → `.dis-side-info` → `.dis-side-match`, which is what a phone
stacks and a screen reader hears; the desktop grid overrides it:

| width | shape |
|---|---|
| ≤760 | one column, everything stacked, the page scrolls |
| 761–1199 | felt left, info panel over match panel in one right-hand column |
| ≥1200 | **match left, felt centre, info right** |

Four things there are load-bearing and were each paid for:

* **`align-items: stretch`, not the base `start`.** A size container with no
  definite height reports `100cqh: 0`, which drove the card budget negative and
  collapsed the board to a 31px sliver.
* **The felt FILLS its column (`width: 100%`).** It briefly sized itself to its
  seven cards instead — but the cards are height-capped on any normal desktop, so
  hugging them left the surplus width as bare *page*, not table: black where the
  user wanted green. The flanking panel columns take most of that width for
  content now; the rest belongs to the felt.
* **…and that width must stay DEFINITE.** The same 31px sliver has now appeared
  twice: once from `margin-inline: auto` beating `justify-self: stretch`, once
  from a malformed comment above the declaration silently dropping it. A size
  container has no contents to fall back on. `screens.mjs` asserts the felt is
  ≥45% of the grid, which catches both.
* **`:has(> .dis-side-match)` gates the three-column tier.** The match panel is
  conditional (a game saved before matches existed has none), and reserving a
  column for an absent element re-creates the empty flank.
* **Each flank has one panel that takes the slack** — the scorecard on the left,
  the trick history on the right — so the columns are full rather than a stack
  of panels with bare page under them. That is also why the wide tier shows all
  thirteen tricks instead of a five-row window.

**The auction and the round-end report sit BESIDE the cards** (≥1200px), in a
rail inside `.dis-table` — the seats auto-place down column 1, the panel
is pinned to column 2 spanning the explicit grid, and `.dis-3seat` is the only
thing that has to know the row count. **The rail is EXACTLY 17rem in every
railed phase (2026-08-12), the playside's width — not its original
minmax(17rem, 24rem)**: the card-width budget subtracts one rail width, so a
rail that could grow let the height budget size cards wider than their column
and the hand wrapped 5+2 at 1366×768 — and a per-phase rail width would break
the cards-identical-across-phases property below whenever width binds. The
panel's innards adapt to the column instead (skat's ladder at five columns
with the PANEL as the single scroller — a nested ladder scroller half-clipped
its own last row; the "would need" caption on its own line so six chips fit
one centered row; the level grid is centered FLEX at fifth-width keys, because
a responder's short legal set hugged the left edge of a 5-column grid beside
dead tracks, and `screens.mjs` asserts the fifth-width form). They used to be a row *between* the seats,
which cost twice: the card budget paid for them (`--dis-rows: 4` against a `30rem`
reserve, versus play's 5 against 17.5rem), so **the board visibly redrew smaller
for the auction and again for the report** — at the one moment you want to
compare it with what you just played — and the report, the tallest thing this
screen ever shows, scrolled inside itself while a third of the felt sat empty.
In the rail both go away: the seats keep the PLAY budget at every phase, and the
report has a full-height column to be tall in. `min-height: 0` on the panel is
what keeps it out of the row sizing — an auto track otherwise sizes to a spanning
item's min-content, and the report would be setting the seats' heights.
`screens.mjs` asserts the card width is **identical at the auction, in play and
at the report**, which is the claim that matters and the one nothing else sees.

**The parity modes' bid ladder tops out at 10** (`PARITY_MAX_LEVEL`), and that is
a product cap, not an arithmetic one: 11 and 12 are reachable (six even tricks
plus one odd, and a clean sweep) but never bid, and twelve buttons is not a shape
— ten is two rows of five. **Skat is deliberately untouched**: its levels
multiply a base rather than promise points, so `SKAT_VALUES`, `skat_declarable`
and `apply_declare` all keep reading `MAX_LEVEL` (12) and its 32-rung ladder is
unmoved. Three things had to move with it, and each is the kind that fails
confusingly: `test_rust_parity`'s synthetic contract took `max_level_for` and now
takes the **parity ceiling** (it exists to stop `_score_is_settled` firing, and
the two stopped being the same number); `gen_auction_fixtures` named `MAX_LEVEL`
for its ceiling states, so the states it generates stopped being ceiling states;
and `wire.rs` asserted classic nodes at `level >= 11`, which is now unreachable
and would have failed as "the fixtures are thin". All three are ceiling-relative
now. The Expert auction search needed nothing — it already reads `max_level` off
the wire, which is why minor worked the same way.

**The trick line is STACKED under the cards, in flow** (`.dis-trickcards` +
`.dis-trickinfo`). It used to be one row with the line absolutely positioned at
`bottom: -4px` — a 4px offset against a ~14px name label — so "Trick 5 of 13 ·
−1" drew straight through the "who played this" name under a card. Reserving a
padding band for it did **not** fix it: on a short screen the cards sit at their
`3.4rem` floor, so the board is deliberately over budget and this row is what
shrinks — and flex content overflows a shrunken box right back through the band.
Stacked in flow, a squeeze cannot make two rows overlap. `screens.mjs` measures
the two rects, because nothing else can see it.

The Contract panel carries the **bidding** and the Points panel the **round's
trick history** (`BidLog` / `TrickHistory`, both off one `trickList(game)`
derivation shared with the Last-trick panel). The bid log used to live inside the
auction panel, so it vanished the moment the auction ended — which is when
"what did they bid to get here" is asked most. Those two panels used to be
`display: none` on a phone as duplicates of the contract chip and the seat rows;
they are not duplicates any more, so the phone shows them.

`poolNote(game)` replaced a hardcoded "Always adds up to +5." — classic's parity
and nobody else's. It is derived from the wire (`tricks`, `even_val`), so minor
reads −1 and the next parity mode is correct without an edit; card scoring has no
constant to state (its pool is a property of the deal) and gets its own sentence.

## Layout

| file | what |
|---|---|
| `engine.py` | the rules + per-seat redaction (`view_for`). JSON-safe dict. |
| `bot.py` | Easy/Normal server bot; `policy_score` is a port of `policy.rs`. |
| `persist.py` | at-rest compaction boundary — drops `played` (derivable), packs `history` triples into ints. |
| `main.py` | `dissonance_app` @ `/dissonance`, on `core.rooms` primitives. |
| `Dissonance.jsx` / `.css` | frontend; CSS via `?inline`, never a JS literal. |

Cards render as **rank + suit glyph in CSS** — there are no image assets and
none are needed. Suits differ by glyph as well as colour, so red/black is never
the only signal.

## Wiring points (there are five, and one is easy to miss)

1. `shared/router.js` → `MODES`
2. `games/spender/Spender.jsx` → `lazyChunk` + `<Suspense>` branch
3. **`games/spender/Spender.jsx` → `SCREEN_FOR_MODE` *and* `MODE_FOR_SCREEN`** —
   missing these is why the chunk was never fetched; the route resolved to no
   screen at all and the `screens` gate caught it.
4. `shared/HomeScreen.jsx` → card + icon
5. `webapp/test/screens.mjs` → `SCREENS` entry, marker `.dis` (and any new
   interaction block must also be listed in a LANE at the foot of that file —
   forgetting compiles, runs and passes with the block never executing)

`LobbyHeader`'s `user` prop takes a **node**, not the auth object — passing
`authUser` raw throws React error #31 and blanks the screen.

## Tests (560)

`test_minor.py` (24) minor mode end to end — the ±1 parity and the −1 pool,
the derived 1..6 ladder, the re-anchored prices (Null 6, set rate 2, the
Double's arithmetic), Null-replaces-set, the result row naming its mode and
prices, `even_val` on the view / `even` on the deal snapshot surviving
persist, minor-priced auction options and the Expert payload's
classic-shape-with-minor-ceiling, the bot inside the ladder, and the
three-part stale-wasm gate's server half (a minor room arms only a `wire: 2`
client; classic/skat accept any vintage) ·
`test_engine.py` rules (including the match SCORECARD: one line per banked
round, derived from the result row, none for a pass-out, and a match that
predates it gaining one without crashing) · `test_history.py` (5) the lobby
History row — the MATCH standing rather than the last deal's, the rounds/target
line, both seats reading the same match from their own side, a forfeit, and a
pre-match save still read as one round · `test_rust_parity.py` the drift gate ·
`test_bot_fairness.py` (14) the bots see only their own seat, by INVARIANCE
over re-dealt hidden cards, plus EXACTLY what an auction decision may consult ·
`test_double.py` (52) classic's Double: the doubled arithmetic, the phase, and
the measured reason the server tier declines while the search does not ·
`test_ws_auth.py` seat-identity binding + whole-payload redaction ·
`test_integration.py` create → auction → 13 tricks → scored result → the NEXT
round → the match, vs human and vs bot, in **both modes** (its vs-bot pair covers
the case most likely to strand: only the human can deal the next round, and the
bot has to pick its own turn back up once they do) · `test_skat.py` (74) the skat
phase machine: the derived ladder, the redeal, talon/Hand secrecy, declaration
validity, the announcement table, Kontra/Re, the Open reveal, a `state_json`
round-trip, and **Grand** (the tens as a fifth suit, second-ten-wins, the
NULL_DENOM collision, a whole round through the real phase machine, and the
whole-card-space assertion that no other contract moved), and the **overtrick
bonus** (the make boundary, the flat-through-the-multipliers rule, and that no
trick is ever skipped) · `test_client_ai.py` (12) the Hard tier's protocol: the armed
request, the re-validation, the stale drop, the watchdog, and the picker/server
tier agreement · `test_bid_worth.py` (3) the auction panel's price
row: `/catalog` serves every term the price is built from, the client reads
them off the catalog instead of hardcoding them, and the panel's arithmetic
matches `_terms_for` at every level and four jump sizes ·
`test_expert.py` (16) what the server ships so the browser can
SEARCH the auction: the payload is the auction verbatim, every settlement it
prices is `_terms_for`'s own answer, every option the server offers has a row to
settle on, unreachable rows are pruned, and only an EXPERT room carries the
block at all.

Rust side, `cargo test --features bridge` runs `wire::fixture_replay` (the
wire-reader gate above) plus `tests/engine.rs`, the 16-test mirror of
`test_engine.py`. Three of those are Grand's: the fifth-suit rules, the
whole-card-space no-regression sweep, and a trump void surviving the
determinizer. `solver_matches_brute_force` also sweeps `DENOMS` now and asserts
it reached Grand — the equivalence collapse is the one place a Grand bug would
show up only as a slightly wrong VALUE, which nothing else would notice.

**RUN IT — and since 2026-08-07 so does CI: `.github/workflows/
rust-dissonance.yml` runs this exact gate on every push touching the crate or
the committed fixtures** (it deploys nothing — the wasm artifact stays a
by-hand `wasm-pack` step). The workflow exists because a broken Rust test
target is invisible here in a way a Python one never is — nothing goes red,
the suite simply stops existing — and this crate had already been bitten
twice. `tests/engine.rs` had not COMPILED since the deck-width
campaign (`2a8957b`) took masks from 32 to 64 bits: it kept a `let mut covered
= 0u32`, which stopped type-checking against `Mask`, and the whole target — all
13 tests — silently dropped out of every run for the entire v2 release. Behind
it sat a second stale assertion (`v.len() == 28`, "26 dealt + 2 out of play")
that had been wrong since the deck went to 32 and had never once been executed.

Both are now DERIVED from `NCARD` / `NDEALT` / `NOUT` rather than written as
literals, so they hold under the `rank7` / `rank9` / `rank10` builds too — which
is not a hypothetical, since a literal 28 is wrong under three of the four and
`rank7` is exactly the 28-card game the pre-sweep numbers were measured on.

The second bite was the GATE itself: `[profile.release] panic = "abort"`
(there for the wasm artifact) made `cargo test --release` fail its FIRST run
from every clean checkout — the cdylib's abort flavour and the test targets'
forced unwind collide in one build graph — and pass on the re-run once cached
unwind artifacts exist, which is exactly the friction that stops a by-hand
gate being run at all. Removed 2026-08-07; the Cargo.toml note carries the
measurement (the shipped wasm does not change).

Browser side, `webapp/test/screens.mjs` drives the skat **create-modal segment**
through to a dealt room and a first bid — a mounted screen says nothing about
whether a new room flag can actually be created (the Renaissance lesson) — plays
a **whole Hard game** and counts `client_ai_ready` / `ai_move` on the socket
(every failure in the Worker→wasm→fetch chain degrades to the server bot, so a
game that plays out perfectly is exactly what the fallback looks like), and
measures the **completed-trick beat** described above. It also reads the match
**scorecard** off the rendered panel — cells, not a substring — and asserts
round 1's line survives the next deal: the panel is fed by `match.rounds` off
the wire, so a field that never shipped and a panel that renders nothing look
identical from the outside.

## The Hard tier — an exact solver, in the player's browser (2026-08-07)

`easy` / `normal` / **`hard`** / **`expert`**. Hard's CARD PLAY is
`dissonance-core`'s `PimcBot` compiled to WASM and run client-side; Expert is
that plus a search over the AUCTION (its own section below).

**WHAT THE BROWSER ACTUALLY BUYS — measured 2026-08-07 on the v2 rules, since
the old "69.8% behind `pimc:8`" figure predates the 32-card deck, Grand and the
payoff-aware search.** CRN-paired `bin/arena`, 120 paired deals, mirror reading
exactly 0.0000; edge in trick points per round to the stronger side, on a pool
where both players' totals always sum to 5:

| | vs `greedy` | doubling buys |
|---|---|---|
| `pimc:1` | **+0.04 ± 0.11** | — |
| `pimc:2` | +0.46 ± 0.11 | +0.42 |
| `pimc:4` | +0.90 ± 0.12 | +0.44 |
| `pimc:8` *(shipped cap)* | **+1.10 ± 0.10** | +0.20 |
| `pimc:16` | +1.20 ± 0.10 | +0.10 |

and search against search: `pimc:8` over `pimc:2` is +0.58 ± 0.10, `pimc:32`
over `pimc:8` only **+0.21 ± 0.08** for four times the compute.

Three things follow, and they are the answer to "is client-side worth it":

* **`greedy` IS what the server plays.** When the browser does not answer,
  `_bot_move_sync` falls through to `bot.act` — the same one-trick-deep policy
  Normal uses (`GreedyBot` is `policy_best`, which `bot.choose_card` ports).
  There is no server-side search at any tier, so **Hard without a browser is
  Normal**, and the whole +1.10 is what the client buys.
* **One world of exact solving is worth NOTHING** (+0.04 ± 0.11 — inside the
  error bar of the heuristic). The strength is in AVERAGING OVER UNCERTAINTY,
  not in the double-dummy solve, so a server that could afford one world per
  decision would gain nothing at all for the trouble.
* **Past the shipped cap a faster machine buys very little.** 8 → 32 worlds is
  four times the compute for +0.21, so a fast desktop is not meaningfully
  stronger than a slow laptop here — the CAP binds, not the CPU (except at ≤4
  cores, where the worker pool itself shrinks).

**This is CARD PLAY only.** ~~The auction's compute→strength curve is still
unmeasured; its cap is a separate `CLIENT_AI_AUCTION_WORLDS` (3) and nothing
says whether that sits at the knee the way 8 does here.~~ **MEASURED 2026-08-20,
AND 8 IS THE RIGHT CAP.** Against the equilibrium instrument, paired on 220
deals: exploitability **13.25 at k=1, 8.13 at k=2, 6.28 at the shipped k=8, and
6.73 at k=16** — the knee is at or just below 8 and doubling the solves buys
nothing. The same sweep is what VALIDATES that instrument (a knowably weaker
bidder must read worse, and one world reads twice as exploitable, in all four
disjoint quarters). See "THE INSTRUMENT IS VALIDATED" below.

* **Why client-side, and why it could never be otherwise.** The search is an
  EXACT double-dummy solve per sampled deal: `bin/bench` times one full solve at
  ~74ms natively and the wasm measures **~70ms per world at trick 1**, collapsing
  to ~0 by trick 7. Render's free tier is ~0.1 CPU with five games on one uvicorn
  process. The player's own cores are the only place this fits.
* **It searches the CONTRACT PAYOFF, not the trick points (2026-08-07).** Points
  are the game's yardstick, not its score: a points solver cannot see what a
  declarer past their target actually gains (1 a point since the overtrick
  bonus, and nothing at all before it — the payoff says which, the solver does
  not assume), that every point of a defender's shortfall is worth four, or —
  since Null became a consolation —
  that a declarer who has taken no +2 trick is one ducked trick from scoring
  instead of being set. That last one is a CLIFF in the payoff at a single bit
  of state, which is why `State` carries `escored` (not derivable from `pts`: a
  total of −1 is one +2 trick and three −1s just as easily as one −1 alone).
  Ducking for Null and defending against it both fall straight out of the
  minimax; neither is a special case.
  - **The terms are SHIPPED, not reimplemented.** `_ai_search` carries
    `engine.payoff_terms` — the same function `_finish` scores with — so the
    only thing written twice is the arithmetic turning terms into a number, and
    `wire::payoff_parity` holds that to a fixture of the engine's own answers.
    A consequence worth knowing: **change the Null value or the curves and the
    bot follows with no code change at all.**
  - **Measured** (`bin/cmatch`, paired, mirror reads exactly 0.000): **+0.55**
    payoff/round at level 4 and **+1.25** at level 1, positive in BOTH roles,
    and it finds Nulls the points search never does (6–7 vs 0 in 40 rounds).
    n=80, so treat the magnitudes as indicative. **The first run of this read
    +4.05 and was wrong** — the harness seeded bots by identity rather than by
    seat, so swapping tiers swapped their RNG streams too. The mirror caught it;
    that is what the mirror is for.
  - **The browser gate counts ARMED decisions, not an absolute number of
    answers.** The server arms a decision only where the bot has a CHOICE —
    under mandatory follow-suit most plays are forced and it applies those
    itself — so how many arrive is a property of the DEAL. An absolute threshold
    failed on deals with more forced moves while the tier worked perfectly, and
    read exactly like the tier being broken. `screens.mjs` reads the count off
    the WebSocket frames and asserts every armed decision came back.
  - Costs **1.79x** a points solve (`csearch` has no MTD(f) and must play to
    trick 13), so ~125ms per world at trick 1 against ~70ms.
* **The strength knob is the WORLD COUNT and nothing else.** Sampling saturates
  at k≈8 (CAMPAIGN.md), so the server caps the pooled total at 8 and the worker's
  millisecond budget only exists so a slow phone still answers.
* **Pooling sums per-move VALUES, indexed by `State::legal`** — a pure function
  of the position, so index *i* is the same card in every worker and in the pick.
  Sums over disjoint world samples add, so the pooled answer is exactly what one
  worker with the combined `k` would compute. The pick rule (highest total, ties
  to the earliest legal move) lives in `odd_best_card`, NOT in the worker's JS —
  a copy that drifted would be a different bot with the same name.
* **Pool size is `max(1, min(hc-1, 4))`** — the never-take-every-core rule. Two
  other games shipped without it for months.
* **Only card play goes to the browser.** An auction decision is `eval_hand`:
  ten exact solves per sampled world against card play's one, i.e. multiple
  seconds for a bid. Hard is a card-play tier until that is measured. (It has
  been, twice over: the Hard AUCTION and then Expert's tree, both below.)
* **Nothing is trusted.** The card arrives over the human's own socket and is
  re-validated against `legal_moves` for the BOT's seat; a refusal is treated
  exactly like silence. A tampered client can only weaken its own opponent.
* **Degradation is per-DECISION, so a browser can never stall a room**: an
  unarmed client, a timeout (`CLIENT_AI_TIMEOUT`), a stale reply and an illegal
  card all fall through to the server bot for that one decision. The armed
  request lives in ROOM STATE (`_ai_search`), so every re-broadcast and every
  reconnect re-ships it; `release_socket(disarm_client_ai=True)` clears the
  opt-in when the tab goes, and a reconnecting client re-arms itself.
* **The staleness key is a monotonic counter, not the ply.** Every play happens
  to append exactly one history entry today, but nothing ENFORCES that, and two
  decisions sharing a key make a late reply indistinguishable from a fresh one.
* **The wire reader is a SECOND parity surface** (`src/wire.rs`), and it fails
  silently: a reader that mis-sizes the hidden pool, drops a suit void or
  mistakes which pile bottom is public still returns a legal card, just a worse
  one — a room that says Hard while playing below it, with nothing red anywhere.
  Hence `views.jsonl` (committed, both seats, both modes, every ply of four
  games, from `tools/gen_view_fixtures.py`) and the `wire::fixture_replay` tests.
  It reads `view_for` itself rather than a second projection, so the redaction
  boundary the server already rests on is the one the bot searches.
* **Rebuilding the artifact**: `wasm-pack build --target web --release
  --no-typescript` in `rust-cores/dissonance-core`, then copy `pkg/dissonance.js` +
  `pkg/dissonance_bg.wasm` into `webapp/public/wasm/` and COMMIT them. CI does not
  build Rust and the crate is in neither deploy path filter, so committing one
  never deploys anything on its own. Same filename ⇒ browsers may serve the
  cached old wasm (~10 min Pages TTL).

## The Hard AUCTION (2026-08-07)

`bid.rs`, served over the same protocol as the card play. The old bot scored a
hand by summing a rank curve and mapping it onto a level through hand-placed
thresholds — guesses, driving four decisions at once. This samples deals and
SOLVES each one in every denomination (most the declarer can guarantee, plus
"could they duck to Null in this trump"), then prices every option the server
says is legal. No thresholds.

* **The server owns the options AND their moves.** `engine.auction_payoff_options`
  returns each legal action priced by `payoff_terms`' own arithmetic, each
  carrying the move it stands for, so the browser ranks an index and sends back
  a move it was handed. Four move shapes across two auction modes, and no rule
  about any of them crosses the wire. `_validated_bot_move` re-runs whatever
  comes back through the ENGINE on a throwaway copy — a client-side allowlist
  would have been the second copy of the rules all over again.
* **The talon and the swap stay server-side ON PURPOSE.** They are decisions
  about INFORMATION: what declining to look is worth depends on a game that has
  not been named yet, so there is no contract for the solver to price them
  against.
* **PERFORMANCE — a world costs a different amount here**, and getting that
  wrong is what the first wired version did. A card decision solves the deal
  once (74ms native); an auction decision solves it in every denomination
  (417ms). Inheriting the card tier's 8-world cap put **7.5–9.2s** on a bid,
  past the point where the watchdog took decisions back (6 of 8 answered). It
  now runs **~1.0s for the first decision of a hand and ~0 for every one after
  it, 14 of 14 answered** — but note that the "~0 for the rest" only became true
  with the `covered` mask below; before it, the cache hit inside a round and
  missed across them, so a whole auction paid its opening price on every turn:
  - **A separate `CLIENT_AI_AUCTION_WORLDS` (3).** The estimate is a whole-hand
    question and much less noisy than a mid-play one; the design lab's own
    sweeps ran at k=4.
  - **The solve is CACHED on what the seat HOLDS** (`hand_key`). An auction asks
    the same question of the same cards every round — five or six in classic,
    more up a skat ladder — and only the option list changes, which is
    arithmetic. The talon swap changes the hand and so invalidates it by
    construction. This is the big one.
  - **…and the denominations asked about are a QUERY against that entry, never
    part of its identity.** The option list does not merely change, it SHRINKS:
    a classic seat cannot re-bid a denomination it has named, so the set its
    options span runs 5, 4, 3, 2 down its own four turns, and skat's runs
    5, 4, 3, 2, 1 as the rungs price denominations out. With that set in the
    key every one of those steps MISSED and re-solved denominations already in
    hand — the cache only ever hit inside a round. `Solved` now carries the
    sampled deals plus a `covered` mask: a subset is a hit, a superset solves
    only the difference **on the same deals** (a fresh sample would make the
    choice between denominations noise). Measured over a whole classic auction,
    **18,435k nodes → 7,220k, −61%**, and every turn after the first is free.
  - **MTD(f) seeds each denomination from the last** (−6%, exact). The same hand
    is worth a similar amount in hearts and spades, so the first solve pays for
    the other four. `solve_root` had done this between sibling moves since the
    campaign.
  - **Seeding ACROSS WORLDS is worth nothing — do not relitigate.** The obvious
    next step (carry each denomination's value into the same denomination of the
    next world, since a different lie of the unseen cards should move the value
    less than a different trump does) measures 8,634k → 8,685k nodes: no change.
    It first read −14% on a bench that solved the SAME deal three times, where
    the carried seed was already exactly right; the fix is that the worlds must
    be really determinized. `bin/abench`.
  - **A BIGGER TT IS SLOWER — do not relitigate.** 2^19 and 2^20 each cut nodes
    (2.55M → 2.43M → 2.38M) and each ran SLOWER in wall clock (423 → 472 → 491
    ms/world): cache locality dominates at this size. 2^18 stays.
  - **THE FAN-OUT IS ALREADY OPTIMAL — splitting it finer cannot help.** The
    pool gives each worker its own world, so four workers buy four worlds for
    one world's wall clock with no idle time. Splitting by denomination instead
    (each worker owning some trumps across shared worlds) was measured and is
    WORSE at equal quality: total work is unchanged and worlds are near-equal
    cost, so the balance being optimised was never the problem. What is left is
    total work — which is what the cache above attacks.
  - **MEASURE THIS IN NODES, NOT MILLISECONDS.** `Dd::nodes` is exact and
    proportional to time; wall clock on a dev box swings ~2.5x on byte-identical
    work, which is more than any of the effects above.
* **The approximation, stated:** `solve` gives what a declarer can guarantee
  with both sides playing for POINTS, which is not either side playing for the
  contract. Pricing every candidate exactly needs a `solve_contract` per
  (denomination, level) per world against ~50 options; the points solve is the
  proxy and the payoff arithmetic is exact on top. `auction.rs` has made the
  same trade since the design campaign.
* **PASSING IS PRICED (2026-08-08), and it was the tier's biggest blind spot.**
  It used to be valued at zero, so the bot passed rather than buy a contract
  that priced negative. That makes a SACRIFICE unreachable by construction — a
  sacrifice is a contract that prices negative, bought because passing prices
  worse — and it also bought contracts it should have declined whenever the
  opponent's standing contract was worse for them than a bad one is for us.
  `engine.pass_options` now ships the pass as a priced option like any other:
  the STANDING contract, priced from the opponent's side, flagged `opp: True`.
  - **`opp` means SOLVE THE OTHER SIDE, not flip the sign.** The declarer LEADS
    to trick 1 (worth ~0.93 points), so swapping who declares changes the
    POSITION, not the perspective. `World` carries `opp_pts`/`opp_duck` from
    their own `solve_world` pass, `Solved` tracks a second `covered_opp` mask,
    and `price` negates the result because every option in the list is signed
    for the seat being asked.
  - **Cost is one extra solve per world**, for the standing denomination only —
    not double, because our own side already solves up to five.
  - **A skat pass-out is `redeal: True`, priced flat at 0** — a fresh deal
    neither seat has seen — and needs no solve. Priced rather than omitted so
    `pass` is always in the list when it is legal.
  - **A skat pass prices EVERY game the standing number buys them**, because the
    winner has not named one yet; the search takes the worst for us, which is
    the same as assuming they declare well.
  - **MEASURED: +0.7175 points per round** over 400 paired rounds, `bin/bidlab
    solve nosac` — `NoSac` is exactly the old restriction ("refuse to overtake
    unless expecting to make it"). The sacrifice-capable bidder sacrificed 4.2%
    of rounds. Caveat: that harness runs the design campaign's `auction.rs` on
    the pre-2026-08-07 scoring (set base N-1, doubling off), so read the sign
    and the magnitude, not the third decimal.
  - The classic opener must bid, so there is no pass option at all there.
  - **Back-compat is by omission**: `opp`/`redeal` are optional and default
    false, so a cached wasm older than the server prices every option as one it
    could buy itself and falls back to the old "value <= 0 means pass" rule the
    client still carries for exactly that window.

* **A REJECTED OPTION EMPTIES THE WHOLE LIST, and that silenced the skat tier
  entirely (found + fixed 2026-08-08).** `options_from_json` returns
  `Vec::new()` on any malformed entry — deliberately, since a partial list would
  be scored positionally against the wrong moves — and its denomination guard
  was `(0..=4)`. **Grand is denomination 6**, and `skat_declarable` offers Grand
  at every rung, so EVERY skat auction and declare decision came back empty, the
  client answered nothing, and the room played out on the server bot while still
  saying Hard. Silent, deal-independent, and live from the Grand release until
  this fix. The guard is now `DENOMS.contains`, and
  `every_denomination_the_server_can_offer_survives_the_option_reader` walks the
  whole roster so the next denomination cannot repeat it.

## THE LADDER MOVED UP A RUNG (2026-08-14): Hard is the tree, Expert softens the opponent

`SEARCH_AUCTION_TIERS` is now `("hard", "expert")`. The auction tree was
Expert's defining feature and measured **+1.19 ± 0.32** over the worlds-matched
price list, so it became HARD. What Hard used to be — `bid::price`, the myopic
option list — is no longer any tier's auction; it survives as the pricing for
`declare`/`kontra`/`re`/`double` (no reply after them, so it is already exactly
right there) and as the tie-break inside the tree.

**EXPERT'S EDGE IS NOW THE OPPONENT MODEL, and it is one line of aggregation.**
Both halves of this crate independently diagnosed the same flaw — here, "the
modelled opponent knows our hand"; in CAMPAIGN.md, "standard PIMC is pessimistic
in a specific way: its opponent sees our hand". The tree searches from OUR
information set, so its sampled worlds all contain our real holding and a MIN
node picks the reply that punishes *that* hand. A real opponent must reply
against their own uncertainty and cannot. **This is not an information leak** —
the bot is handed `view_for` and `test_bot_fairness.py` pins it by invariance;
the clairvoyance is only inside the modelled opponent's choice.

`OppModel::Soft(temp)` prices the consequence rather than modelling their
information set (still "not built yet", and a much bigger program): a MIN node
becomes a softmax over their replies at `temp` per-world payoff points, so they
strongly prefer better answers but miss the punishing one when it is barely
better. `EXPERT_OPP_TEMP = 5`.

* **MEASURED +0.957 ± 0.454, 95% CI [+0.07, +1.85]**, 1550 CRN-paired
  dd-resolved deals vs the same tree without it — three disjoint samples,
  +1.07 (n=150), +1.02 (n=900), +0.82 (n=500). Comparable to the tree's own
  gain over the price list.
* **`temp = 0` IS the old tree**, in Rust and end to end (the arena's null
  control reads exactly +0.0000) — which is what made the A/B unconfoundable,
  the discipline CAMPAIGN.md's IIMC blend used (`lambda = 0` reproduces
  `pimc:8`).
* **It costs no solves.** A MIN node already evaluates every child to take the
  min and `bid::Solved` is cached per hand, so the tier is the same work in the
  same time. That is why it could ship on a ~2σ result: there is no latency
  argument on the other side.
* Swept 2 / 5 / 12 at n=150 (−0.36 / +1.07 / +0.99). 2 is too cold to move
  anything; 5 and 12 are indistinguishable at that n, so read this as
  "somewhere around 5–12", not a tuned optimum.
* **A METHOD NOTE PAID FOR IN THIS RUN:** a running total at n=432 read −0.21
  and was called as "heading for a wash"; the completed sample said +1.02.
  Interim totals on a σ≈18 quantity are not evidence — only completed,
  pre-declared samples are. This is the same trap the Expert-vs-Hard campaign
  recorded from the other direction (+1.71 at n=300, −0.28 at n=2250).

## EXPERT — the auction as a game tree (2026-08-08)

A fourth tier: `easy` / `normal` / `hard` / **`expert`**. Expert is Hard in
every respect except one — its AUCTION decisions are a minimax over the bidding
tree (`rust-cores/dissonance-core/src/auc_search.rs`) instead of a price list.

**WHY, precisely.** Hard prices each option as "if I end up declaring THIS
contract, what does it pay". Pricing the pass told it what CONCEDING costs; it
still has no model of the opponent's REPLY, so two things are unreachable:

* **underbidding to CAP an auction.** `MAX_RAISE` is 2, so opening at 1 holds
  the responder to level 3 on their turn. Opening at 1 on a hand worth 4 prices
  as ~1 point, so the myopic search never picks it — even when capping them at 3
  is the whole play. (This is exactly the line the design brief described: *"if
  you have a terrible hand, you can open at the 1 level and pass when they bid
  3, limiting how much they can score."*)
* **judging a RE-ENTRY.** Measured on shipped Hard: of 43 classic rounds that
  opened at level 1, only 30% passed when overtaken.

**IT COSTS NO EXTRA SOLVES OF ITS OWN.** The expensive half is `bid::Solved`,
already cached per hand; every leaf here is arithmetic. What it *does* ask for
is more DENOMINATIONS — whatever either seat could still bid, on both sides,
rather than Hard's own five plus the opponent's one — so the first decision of a
hand roughly doubles and every one after it is free. Measured natively at k=3,
one process, classic: **0.81s → 1.56s for the first decision, ~0 for the rest**;
skat 1.11s → 2.66s. In a browser that is spread over the worker pool (one world
each rather than three), so it lands around 0.5s / 0.9s against a 12s watchdog.

**WHAT CROSSES THE WIRE IS DATA, NOT RULES — with exactly ONE exception, and it
is gated.** `engine.auction_search_payload` ships three things on the armed
request as `auction.search`: where the bidding stands, the legality knobs, and a
priced row per settlement still reachable, each built by `_terms_for`. So the
SCORING is not duplicated at all, the same discipline `payoff_terms` established
for card play — change a payoff and Expert follows with no bot code.
- **The auction's LEGALITY is mirrored**, because it is a function of the node
  the SEARCH is standing on and the server is not standing there. `legal_bids`
  therefore reimplements `auction_options`, and
  `wire::auction_legality::the_tree_offers_exactly_the_bids_the_engine_calls_legal`
  replays `tests/fixtures/auction.jsonl` (299 real auction nodes across both
  modes, from `tools/gen_auction_fixtures.py`) and demands the same set at every
  one. Drift here is silent in the usual way: a tree that believes one extra bid
  is legal prefers a line the room refuses, `_validated_bot_move` throws the
  answer away, and the room plays the server bot while still saying Expert.
- A second test asserts the FIXTURE still reaches the states worth covering —
  the classic opener (the only node where passing is illegal), the ceiling where
  the raise cap stops binding, spent denominations, and a skat node mid-pass-out.
  A regenerate that quietly stopped reaching them would pass the first test
  while covering nothing.

**THE PROTOCOL DOES NOT MOVE.** Expert rides in on `odd_pick_bid`, returns the
same per-option vector indexed by the server's own option list, pools across
workers by addition and hands back a move the server handed it. So the frontend
needed one line (the tier id) and a cached wasm older than the server just
prices the Hard way — the cached-bundle window degrades to Hard, not to nothing.
`wire::answer_auction` is the one body both the browser entry and `bin/bidserve`
call; the harness used to reproduce `odd_pick_bid` and with two search modes
that is one copy too many.

**TIES ARE THE COMMON CASE, AND THE INDEX IS A TERRIBLE WAY TO BREAK THEM.**
This was the first version's real bug and it is worth keeping hold of, because
the search looked like it was working. Whenever the opponent has a reply that
equalises whatever we open with, every one of our openings has the SAME minimax
value — on 25 classic deals the top four openings were exactly tied on 4 of the
first 6, and taking the earliest index opened at level 1 in **13 of 25** against
Hard's 1 of 25. That is not the search capping an auction, it is the search
having no opinion and the enumeration order answering for it. So Hard's price is
the tie-break (`tree + 1e-5 * myopic`): among lines the opponent equalises,
prefer the one that pays best if they do not. Agreement with Hard on the opening
went 4/25 → 11/25, and Expert still opens at level 1 in 9 of 25 — which is the
capping play, arrived at deliberately.
- The weight is safe rather than tuned: both halves are sums of integer payoffs,
  so a genuine tree difference is ≥1 per worker while the price is bounded by a
  few thousand, leaving the tie-break two orders of magnitude below the smallest
  real difference, pool included. It can order ties and nothing else.

**THE WORLD COUNT WAS THE LEVER (2026-08-08, the Phase-3 campaign).** Every
opponent-model idea lost or washed; more worlds won. All CRN-paired, dd-resolved,
classic, ~600 deals per row unless said:

| experiment | result |
|---|---|
| expert minimax k=3 vs hard k=3 | −0.28 ± 0.33 (n=2250) |
| expert MYOPIC-OPPONENT k=3 vs hard k=3 | **−0.62 ± 0.50** — best-responding to a model is brittle to the same leaf noise the tree already has; code kept behind the optional `opp_model` wire field, default `minimax`, for future sweeps |
| expert k=8 (one tree) vs hard k=3 | **+1.36 ± 0.48, CI [+0.43, +2.29]** |
| hard k=8 vs hard k=3 | +0.86 ± 0.49 — most of the k=8 gain is the worlds |
| expert POOLED 4×2 vs deployed hard | **+0.14 ± 0.45 — the pooling trap.** Four 2-world trees summed are NOT one 8-world tree; the tree is nonlinear in its worlds and quarter-sample trees are noise-dominated. Caught at the serving-shape gate, before shipping |
| expert ONE tree k=8 vs hard 4×1 | +0.40 ± 0.45 — hard's deployed shape was really k=4 all along (`perWorker = ceil(3/4) = 1` across four workers), which absorbed most of the +1.36 |
| **the shipped pairing**: expert one-tree k=8 vs hard pooled 4×2 (=k8) | +0.26 ± 0.42 at n=600, pre-talon — unresolved then, superseded by the row below |
| **the shipped pairing, RE-MEASURED with the talon model in the leaf (n=1600)** | **+1.19 ± 0.32, CI [+0.57, +1.81]** — the tree's marginal over worlds-matched Hard, finally clear of zero. A better leaf helped the TREE more than the pricer, which is the campaign's story closing: the tree composes leaf values through max/min chains, so leaf error hurt it most and leaf accuracy pays it most |

### EXPERT vs EXPERT — the full profile (2026-08-11, 800 paired deals)

The tier playing ITSELF at the serving shape (classic, k=8 one tree,
`resolve=dd`), via `auction_arena.py expert expert` over two disjoint 400-deal
windows, pooled by `tools/style_report.py`. **Strength is not measurable here** —
the mirror reads exactly `+0.0000` by construction — this is behaviour only.
Recorded because the detail kept evaporating: the counters were always
collected, the shard logs are gitignored, and only prose ever reached this file,
so "what does Expert actually do" cost a fresh hour-long run every time.

**Every raw count reads DOUBLE** (each deal is played twice with the seats
swapped, and identical policies give identical auctions). Percentages are
unaffected; the independent sample is 800.

| opening level | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| share | **30.1%** | 6.0% | 10.8% | 13.6% | **19.2%** | 14.5% | 5.4% | 0.4% |

| settled level | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| share | 4.8% | 3.6% | **25.0%** | 8.1% | 19.2% | **27.9%** | 10.6% | 0.8% |
| made | 92.1% | 89.7% | **95.5%** | 61.5% | 50.0% | 30.0% | 21.2% | 0% |
| set | 2.6% | 0% | 3.0% | 32.3% | 44.8% | **64.1%** | 75.3% | 100% |
| Null | 5.3% | 10.3% | 1.5% | 6.2% | 5.2% | 5.8% | 3.5% | 0% |

Opening mean 3.53 / median 4, settled mean 4.63 / median 5 — **and the mean is
close to meaningless on the opening, which is sharply BIMODAL**: it opens at 1,
or it opens for real at 5–6. Level 2 is nearly empty (6.0%), which is what says
the low opening is a deliberate cap play rather than general timidity. The
settled distribution is the same shape shifted: the level-1 mass becomes a spike
at **3**, exactly where `MAX_RAISE` puts it.

Open → settled (row %, upper-triangular by construction): a level-1 opening
settles at **3 in 71%** of rounds and stays at 1 in only 16%; a level-6 opening
is contested 22% of the time. **36.1% of rounds open ≤2 and 60.6% of those
settle at exactly 3.**

Decisions: forced opening 33.8%, positively-priced bid 20.6%, **sacrifice 11.7%
of all decisions = 17.7% of FREE choices**, pass 33.8% (one forced open and one
pass per auction, by rule). **Doubles taken 27.2% of opportunities.** Outcomes
overall: made 56.8%, set 38.8%, Null 4.5%.

**DOUBLING THE SAMPLE MOVED ALMOST NOTHING**, which is the reason to trust the
shape: over the first 400 vs the pooled 800, opens-at-1 30.2→30.1%, opens ≤2
36.0→36.1%, sacrifice 18.4→17.7%, Double 26.0→27.2%, made 58.5→56.8%. The two
that drifted both moved AWAY from the benign reading — level-6 make 34.2→30.0%
and cap conversion 56.2→60.6% — so the overbidding below is slightly worse than
the half-sample said, not better.

* **The single most common settlement is level 6 — 28% of contracts — and 64% of
  those are SET.** Two Experts bid each other well past the making point; the
  cliff is at 4 and level 5 sits on exactly 50.0% made over 308 contracts.
  Whether that is correct (the payoff asymmetry may reward it) or a shared blind
  spot was UNRESOLVED and that run could not tell them apart — **it is resolved
  now: it is a blind spot, and the CFR solve below says which one.**
* **The level cap at 10 is confirmed irrelevant to this profile**: nothing
  settled above 8 and only 0.4% of openings reached 8, so the 2026-08-11 cap
  removed rungs that self-play never used.
* **The who-declares counter is unusable in a mirror and is not reported.**
  `traject` marks a round `kept` when the opener's TIER equals the declarer's,
  which with one tier on both seats is always true — it reads 100% and means
  nothing. The open→settled matrix carries the honest version of the question.

**What shipped from it:** `CLIENT_AI_AUCTION_WORLDS` 3 → **8** for every auction
tier (Hard's pricing is linear in the worlds, so the pooled 4×2 computes exactly
the measured single k=8: +0.86 for ~850ms a bid), and Expert's auction runs the
same k=8 as **ONE TREE IN ONE WORKER** (`solo` dispatch in `Dissonance.jsx`,
~3.4s for the first decision of a hand, ~0 after — and note the OLD deployed
Expert was four ONE-world trees summed, the deepest point of the pooling trap).
The tree's marginal over worlds-matched Hard is **+1.19 ± 0.32 (CI [+0.57,
+1.81], 1600 paired deals, both tiers with the talon model)** — the queued
resolution run, completed 2026-08-09. The same run's bidding profile (collected
in-arena, exact-play outcome labels): Expert opens BIMODALLY — 30% at level 1,
the cap line, plus a 5–6 mass, against Hard's unimodal 3–5 — declares fewer
contracts at higher levels (1409 at mean 5.67 vs Hard's 1791 at 4.79),
sacrifices slightly less (13% vs 16% of decisions), Doubles the opponent more
(25% vs 16.5% of opportunities), and its DEFENCE carries much of the edge: it
holds Hard's level-5/6 contracts to 33%/24% made while making its own at
48%/38%.

`tools/auction_arena.py`
(the harness lives with the code and drives `bin/bidserve`, i.e. the same
`wire::answer_auction` the browser calls). **Since 2026-08-08 the arena resolves
by exact double-dummy of the real deal (`resolve=dd`, the default)** — per-deal
σ 15.8 → 11.5, no greedy-play bias, mirror still exactly +0.0000. Two additions
measured USELESS for expert-vs-hard and kept for cheaper comparisons: the
conditional-on-differing mean (the tiers bid differently on **93%** of deals,
so there is nothing to condition away) and the opener-quality control variate
(β ≈ +0.05, no σ reduction). ±0.15 still needs ~5900 paired deals; the loop got
~2× faster, not 5×. CRN-paired: every deal played twice
with the tiers swapped, greedy card play and the server's talon on BOTH sides so
the auction is the only difference; the mirror `hard`-vs-`hard` reads exactly
**+0.0000**.

| classic, expert − hard | payoff/round | n (paired deals) |
|---|---|---|
| deals 0–299 | +1.71 ± 0.94 | 300 |
| deals 300–749 | −0.68 ± 0.74 | 450 |
| deals 750–2249 | −0.56 ± 0.41 | 1500 |
| **pooled** | **−0.28 ± 0.33**, 95% CI **[−0.93, +0.38]** | **2250** |

Per-deal σ is 15.8 even after pairing, so the first 300 deals on their own said
**+1.71 and I reported that** — it was a partial run. At 2250 the interval
excludes anything better than +0.38: Expert is not stronger than Hard, and there
is no longer room for it to be meaningfully so. Skat is separately unmeasured
(−3.50 ± 3.70 at n=90 resolves nothing).

**AND YET IT BIDS COMPLETELY DIFFERENTLY, which is why the wash is a ceiling and
not a bug.** `tools/auction_style.py`, self-play, 320 classic deals, identical
cards for both tiers:

| | Hard | Expert |
|---|---|---|
| opens at level 1 | 11% | **32%** |
| mean opening level | 3.63 | 3.33 |
| **passes when overtaken** | 41% | **77%** |
| **the cap line** (open ≤2, then pass) | 8% | **26%** |
| …settling at | mean 3.35 | **mean 2.95** |
| settled level | mean 4.71 | 4.22 |
| settled at 3 | 11% | **25%** |
| contract made | 50% | **63%** |

It plays the open-low-and-pass line 3.3x as often as Hard and the cap HOLDS —
67 of its 83 such auctions settle at exactly 3. And it opens lighter for real,
not because it was dealt worse: paired on the same hand it opens lower 43% of
the time (same 32%, higher 25%, mean −0.30 levels), and the gap survives
bucketing by what the hand is worth on Hard's own yardstick, widening on the
best hands (−0.21 / −0.25 / −0.33 / −0.23 / −0.47 across quintiles).

**WHERE IT GIVES THE GAIN BACK, measured.** In 10% of rounds Expert opens ≤2 and
the opponent simply PASSES — leaving it declaring at level 1 or 2 on hands Hard
priced at a mean of +8.4, which it then makes 93% of the time. A made level-1
pays `1 + (pts − 1)`, i.e. exactly the trick points, where a level-4 taking the
same tricks pays `16 + over`. **Hard does this zero times in 320 deals.**

**WHY LOOKAHEAD LOSES HERE — four mechanisms, and none of them is the search.**
1. **The modelled opponent knows our hand.** The tree runs from OUR information
   set: our cards are fixed across every sampled world, only theirs vary, so at
   every MIN node they choose knowing our exact holding. They never overbid into
   our strength and always find the punishing reply — against which aggression
   genuinely is worthless, so the search shades everything down. The 10% giveaway
   above is that assumption meeting an opponent that does not punish.
2. **Minimax best-responds to a minimaxer, and it faces Hard**, which bids
   myopically. The mismatch costs more the more plies you commit to it.
3. **The optimiser's curse compounds with depth.** The leaf is a noisy estimate
   over 3 sampled worlds; Hard takes ONE max over ~50 of them, Expert takes
   max/min repeatedly down the tree, so our branches are shaded down and theirs
   up at every level.
4. **Ties** — the acute form of (1), already found and patched; see below.

**THE TALON IS IN THE LEAF NOW (2026-08-09), and it measured exactly what the
theory said it should.** `bid::solve_world` used to build its `State` from the
deal AS DEALT — the lead modelled explicitly (~0.93), the swap not at all — so
once the swap fix made a classic swap worth **+1.500 ± 0.208**, every
declarable contract was under-priced by about that much, a one-directional
lean toward conceding. Now each determinized world samples 3 of its 6
out-cards as that world's talon (stored with the deal in `Solved.shown`, never
re-drawn — the cache fills denominations incrementally and a moving talon
would put between-denomination noise right back), and whoever declares gets
the fitted chooser's exchange applied as one hand edit before the solve, per
denomination, both sides of the pass.
- **Measured: talon model on-vs-off is +1.54 ± 0.51, CI [+0.54, +2.54]** (600
  paired deals, dd-resolved, deployed shapes) — the campaign's second result
  to exclude zero, and the size matches the swap's own value almost exactly.
- **The weights cross the wire** (`bot.swap_policy_terms` → `auction.swap` on
  every classic auction request, both tiers → `bid::SwapPolicy`), so a re-fit
  server-side moves the leaf with no Rust change. Only the FEATURE arithmetic
  lives twice, and `tests/fixtures/swap_policy.jsonl` (476 decisions, both
  branches engineered to appear) holds the two copies to one answer.
  Optional on the wire: an older wasm ignores it and prices the deal as dealt.
- **A harness lesson found on the way:** bidserve's one-slot `Solved` cache is
  evicted by cross-phase asks (a double ask keys differently), which is
  harmless in serving but broke the arena's mirror when a deal is replayed —
  the second flip re-solved fresh worlds. The arena now routes non-auction
  asks to their own process; mirrors read exactly 0.0000 again.

## The classic swap policy is FITTED, and the old one was backwards (2026-08-08)

`bot.choose_swap`'s classic branch. The old rule looked like a 3×7 search but
`gain = worth(t) − worth(h)` is separable, so it was exactly "take the highest
card shown, throw the lowest card held" — and `_RANK_VALUE` is strictly
increasing, so it could not represent any other preference. Backwards by
construction in a game where 7 of 13 tricks are penalties and low cards are how
you force them onto the opponent (the play policy's own "lead low" branch
depends on the cards it discarded). Measured: **−0.477 ± 0.226 score/round
against standing pat**, firing in 64% of rounds.

**The method, reusable for any talon question** (`tools/swaplab.py`):
1. **An oracle labels real decisions.** Drive real rounds to the swap, resolve
   every candidate exchange (3 shown × 7 held, plus pat) by an exact
   double-dummy solve of the real deal — `bidserve`'s `resolve` request. The
   oracle cheats (full information) on purpose: it is a diagnostic bound, not a
   ship gate.
2. **The dataset evaluates any policy for free** — every candidate's exact
   value is recorded, so a proposed policy's regret is a lookup, not a run.
3. **Fit interpretable, information-legal features** (rank one-hots, trumpness,
   resulting suit shape) by ridge on `value − pat`; hold out a second sweep.
4. **Ship-gate on the paired arena over the real information set**, under BOTH
   resolutions — the swap's value depends on who plays the cards afterwards
   (the old policy was +1.6 vs pat under exact play and −0.48 under greedy).

**What the oracle knows that the old rule did not:** its take-histogram is
**U-shaped** — it takes 7s (36) almost as often as Aces (52) and dips through
the middle ranks; it discards Kings when shape wants it (20 of 300); it stands
pat in 35% of decisions (old policy: 4%); and its edge concentrates at high
levels (L5 −4.9, L6 −22 policy loss), where a wrong swap flips make→set at
quadratic stakes.

**Shipped numbers** (constants and derivation documented at `_SWAP_TAKE_W` in
`bot.py`): held-out regret vs the oracle **1.92** against the old policy's
2.50; greedy-playout paired arena over 3000 deals **+1.500 ± 0.208 vs pat,
+1.976 ± 0.194 vs the old policy** — the shipped function itself, not a copy.
A fitted level-scaled stand-pat bar was tried and dropped: it cancels out of
the argmax and measured no better held-out (2.03 vs 1.92). The remaining ~1.9
regret against the oracle is deal-specific combinatorics (make/set boundary,
the Null threat) that no information-legal linear feature set sees — closing
it means solving, which the server cannot afford and the user declined to
client-serve.

**Skat's talon got its own run and its own fit** (2026-08-21) — never these
weights. See the next section.

**THREE APPROXIMATIONS, stated because they are the difference between this and
an exact answer.**
1. **The leaf is `bid.rs`'s** — what a declarer can guarantee with both sides
   playing for POINTS. Same proxy Hard uses, same reason. **Its exact error is
   now measured (2026-08-08, after the contract-table fix): the ONLY gap is the
   adaptive Null threat.** Over 900 (deal, contract) pairs: `payoff(solve,
   duck)` equals `solve_contract` in 93.3%; every nonzero gap is POSITIVE
   (exact ≥ served, +6.5 conditional, worst +27), sits in the same ~7% of
   (deal, denom, declarer) combos at every level, and the guaranteed-duck
   subset gaps exactly 0. The mechanism: a declarer who cannot GUARANTEE
   ducking can still leverage the threat of it — the defender cannot always
   prevent the Null and hold the points down at once — and
   `max(contract, null·duck)` only credits the guarantee. One-sided toward
   UNDER-valuing declaring, i.e. the same direction as Expert's other leaks.
2. **The opponent is modelled against OUR sample**, so their branch is chosen
   knowing our hand exactly. Inherent to searching from one seat's information
   set. It is however LESS strategy-fusion than per-world minimax would be: the
   leaf sums over worlds *before* the min/max, so the opponent has to commit to
   one bid across the whole sample.
3. **Classic's Double is not modelled.** The tree stops when the auction
   settles; the defender's bet is priced on its own turn, by Hard's pricing,
   which is exactly right for a decision with no reply after it.

**Expert is deliberately identical to Hard everywhere else.** `declare`,
`kontra`, `re` and `double` have no reply after them, so a tree over them would
be one node deep — `SEARCH_AUCTION_TIERS` is a separate, smaller list than
`CLIENT_AI_TIERS` for exactly that reason.

**The browser gate drives EXPERT, not Hard, and that is strictly more coverage
for the same minutes** — Expert is Hard plus the auction on the same request and
the same wasm export. It also asserts an AUCTION answer specifically (they log
an option count; card answers log a card), because a tier whose auction search
failed and whose card search worked answers most of the game and otherwise reads
green. That is the exact shape of the Grand outage.

## Skat's talon is fitted too, and the FIRST fit was better and shipped nothing (2026-08-21)

`bot.choose_swap`'s skat branch. **+4.086 ± 0.183 score/round** over the rule it
replaced, on 30000 deals disjoint from the ones it was fitted on — the talon's
value against standing pat goes +1.941 ± 0.197 → **+6.027 ± 0.185**, so winning
a skat auction is worth roughly three times what it was.

The old rule was the same separable `worth(take) − worth(give)` classic ran
until 2026-08-08: a 3×7 "search" whose gain is separable, so it could only ever
mean "take the highest card shown, throw the lowest card held".

**The first fit is the finding.** Trained the way classic's was — an ORACLE
labels 614 real decisions, every candidate resolved by an exact double-dummy
solve of the real deal — it won every diagnostic it was scored on: held-out
regret against that oracle **4.35** against the old rule's 5.16 and standing
pat's 7.54. Then the paired arena said:

| card play | first fit − old |
|---|---|
| `dd` exact double-dummy | **+0.817 ± 0.212** (n=6000) |
| `play` the shipped server bot | **−2.132 ± 0.168** (n=30000) |

It was a better policy **for a solver** and cost 2.1 a round in front of the
card play the server actually runs. Skat scores the CARDS captured — 9/10/J/Q
at +2 and 7/8/K/A at −1 — and the histograms show it directly: the first fit
**gave a jack on 24% of exchanges** (the old rule 0.7%) and took kings on 19.6%
(7.7%). It threw +2 cards out of play and took −1 cards into hand, because a
solver converts top cards into tempo and the greedy bot cannot. Declarer card
points 8.0 → 7.2, contract made 84.8% → 80.6%.

**The lesson, and it generalises past the swap: an oracle label is a choice of
objective, not a ground truth.** Classic's write-up already said the swap's
value depends on who plays the cards afterwards and ship-gated under both
resolutions; what it did not say is that the *labels* carry the same dependence,
so a fit trained on `dd` labels is fitted to a card player nobody is. Anywhere
a policy is fitted against a solver and served in front of a heuristic, ask
which one the label assumed.

**The second fit** is the same enumeration relabelled by the SHIPPED card play
(`swaplab.py skat <n> <lo> <hi> play`). That resolution needs no solver and runs
~600 rounds a second, so the corpus went 614 → **40000 decisions** for two
minutes of wall time — the cheap label is also the big one. Gated on disjoint
deals, under all three card players:

| card play | this fit − old | this fit − pat |
|---|---|---|
| `play` the shipped server bot | **+4.086 ± 0.183** | +6.027 ± 0.185 (n=30000) |
| `hard` the tier's own k=8 PIMC | **+2.602 ± 1.157** (n=440) | |
| `dd` exact double-dummy | −4.758 ± 0.430 (n=4000) | |

**A gain under both card players that exist**, and a loss only against a solver
holding the opponent's cards, which no tier is. The `hard` row is the one that
decided it: five disjoint 88-deal windows, every one positive, driven through
`bidserve`'s `pick` — the same `wire::answer_card` the browser worker calls — so
it is the tier's card play and not a proxy for it. It is slow (~22s a deal, both
seats searching) and that is why it is 440 deals and not 30000.

**What the weights say** (`_SK_TAKE_W` in `bot.py`): `card-point delta` +2.52
and `give trump` −4.48 are the two the separable rule could not hold at any
weights — take the points, never discard a trump. Giving an ace (+2.27) or a
king (+1.34) is good and TAKING one is bad (−2.07 / −1.38): they are the −1
cards, and a discard leaves play entirely, so the talon is where a liability
goes to be deleted. `take suit len` +2.11 is a preference about the HAND rather
than either card. The fitted bar came back at +0.04 — no bar at all — so it
stands pat on ~1% of decisions where the `dd` oracle stood pat on 23%; under the
shipped card play an exchange is nearly always worth making.

**THE INSTRUMENT — `tools/swaparena.py`, and `tools/talon.py` under it.** Two
talon policies paired on the same deals. It needs no CRN trick: a deal is driven
ONCE to the talon and the snapshot branched per arm, so a deal where both arms
pick the same exchange contributes an exact 0 rather than noise, and the arms
are two policies for ONE seat rather than two tiers in two seats, so there is
nothing for a seat swap to cancel. Both arms are the SHIPPED `choose_swap` under
two settings of `DIS_SKAT_SWAP_OLD`; a copy of the policy in the harness
measures the copy.
* **The mirror needs teeth here.** `arm arm` reads +0.0000 for free, because
  identical picks short-circuit without playing a card — so the usual mirror
  check asserts nothing about the playout. `SWAPARENA_NO_SHORTCUT=1` removes the
  short-circuit and drives both arms through the whole round; old/old and
  fit/fit read exactly +0.0000 under it.
* **`talon.py` exists because two tools have to mean the same thing by `play`
  and by `dd`.** `swaplab` labels, `skat_swapfit` fits, `swaparena` gates — and
  the whole finding above is that those two resolutions differ by ~3 points a
  round on the same exchanges, inside which half a point of accidental drift
  between two copies of "play" would have been invisible.

**A BUG THAT SHIPPED AS DEAD CODE, worth stating because of how it hid.** Both
weight tables and the fit's own feature vector were sized by `NRANK` (8) and
indexed by `E.rank`, which scores on the WIDE deck's 0..9 scale. The give block
overlapped the trump features — one weight meaning both "give a king" and "the
take is trump" — and the policy raised IndexError the first time it saw an ace.
Nothing caught it because the policy was behind an off-by-default flag and no
test turned it on. **An experiment parked behind a flag is untested code, and
the flag is what makes it look otherwise.** Three guards now cover it, all
verified non-vacuous against the 8-long tables (`tests/test_swap_policy.py`).

**AND IT WIDENS THE AUCTION SEARCH'S TALON BLIND SPOT — queued, not done.**
`main.py` ships `swap_policy_terms()` on a classic or minor auction request and
deliberately not on a skat one, so this is a pure server-side change with no
wire shape and no wasm rebuild behind it. The price is that skat's auction leaf
builds its State from the deal as dealt and now under-prices winning a skat
auction by ~6 rather than ~2 — the same blind spot classic's fix opened and
closed. Skat's fix is the same shape: slice these rows to the base deck, ship
them as `auction.swap`, and drop the `mode_of(g) != "skat"` guard.

**NOT MEASURED, stated so nobody reads it as measured:** whether the FIRST
(`dd`-labelled) fit beats this one under `hard`. It beats the old rule under
`dd` and loses to it under `play`; this fit beats the old rule under both `hard`
and `play`, which is what the ship decision needed, and a tier-aware talon is
only worth building if a `hard` arena between the two fits says so.

## The DD column — an exact double-dummy replay of every round (2026-08-08)
The match scorecard (`MatchCard`, in the side panel's "Match to N" box) carries
a fifth column, **DD**: what double dummy would have scored — the same deal,
the same contract, the card play redone from trick 1 by two players who see
all 32 cards. Hover the header for the full sentence. Beating it means the
hidden cards broke your way; trailing it is the cost of playing honestly in
the dark. (It began life as a right-click modal and was deliberately folded
into the box itself — always visible, no gesture to discover, less code.)

* **`odd_review` is the fifth wasm export**, and it is NOT `odd_pick_card` with
  a fully-specified view — that obvious implementation cannot work twice over.
  A `View` is an information set: it carries a pool the searcher SAMPLES from,
  so even a payload naming every card gets reshuffled; and `view_from_json`
  rejects it first anyway (`hidden_slots` counts covered outer piles by
  `n == 2`, not by whether the bottom is known, so a filled-in bottom breaks
  the partition check — which is *right*, for its own job). A finished round
  has no uncertainty left, so `wire.rs::deal_from_json` is a different reader:
  one exact `solve_contract`, no determinization, no seed. Same answer every
  time — which is what lets the column be labelled a FACT about the round
  rather than a bot's opinion, and the tests pin exactly that (including
  against a TT warmed on another deal, the state the export actually runs in).
* **The value is the round's PAYOFF, signed for the declarer** — rendered in
  the Score column's own vocabulary (`+` what you'd have taken, `−` what it
  would have cost). It is deliberately NOT a "DD pts" (`p/target`) figure:
  the payoff-optimal line's trick points are not unique (payoff-equal lines
  differ in points), and deriving points back out of a payoff in JS would be
  a second copy of the scoring — the drift `payoff_terms` exists to prevent.
* **The data is `engine._deal_snapshot`, taken at `_start_play`** — it must be
  snapshotted, not reconstructed: by round end `history` says which card each
  seat played but never WHERE from (hand and pile-top plays are the same
  entry), so the hand/pile split that defines the position is gone. After the
  talon swap on purpose: the review prices the hand that was PLAYED.
* **Redaction**: `g["deal"]` holds BOTH hands and never leaves the server. The
  reviewable copy is written only in `_round_summary` at bank time, when the
  round is finished and wholly public — the same reason `match` rides the wire
  at all. An abandoned round banks NO deal (nothing to review, and it is the
  one path that banks mid-play with cards still live). The test asserts on the
  SERIALISED payload, per the nested-snapshot lesson.
* **The solves run client-side in ONE on-demand worker** (`kind: "review"` in
  dissonance-worker.js, driven by `useDdReviews`), created lazily when a
  banked round has no cached answer and torn down when the batch is done —
  the column renders at every tier and in human-vs-human rooms, so it cannot
  lean on Hard's pool being armed. Results are cached for the life of the tab
  (`REVIEW_CACHE`): the deal is immutable and the solve exact, so a result
  can never go stale. The hook's dependency is the rounds COUNT, not the
  array — a fresh array arrives on every broadcast, but a banked round never
  changes.
* **At rest the snapshot is packed** (`persist._pack_deal`): the partition is
  fixed (7+7 hands, 3×2 piles each, 6 out), so the 32 card ids flatten into a
  32-char string (`_CARD_ALPHA`), and `terms` packs STRUCTURALLY — sorted keys
  joined into one string plus a values list, so persist.py still knows nothing
  about what `payoff_terms` produces. Measured after zlib: +135% verbose →
  +55-86% packed, ~46-52 bytes/round against the permutation's ~20-byte
  entropy floor. Rows written before the string encoding still load (the
  unpacker discriminates on shape); an unrecognisable deal fails OPEN to
  verbose, since an unreadable save is worse than an unshrunk one.

## THE PAR TABLE — the same deal solved in every denomination, both sides (2026-08-13)

Under the DD figure in the round's story: a row per denomination, a column per
player, each cell the **trick points that player could have taken as declarer**
plus an **N** when they could have ducked every scoring trick. The points ARE
the contract — a level is a promise of that many points — so a cell is the
highest level that player could have bid there and made.

* **IT NEEDED NO NEW WASM EXPORT, AND THAT IS THE WHOLE DESIGN.** The artifact
  is a committed `wasm-pack` build and `odd_review` prices a CONTRACT, so each
  question is asked by naming a contract whose payoff IS the answer
  (`PAR_TERMS` in `Dissonance.jsx`):
  - **points** — `target 0, make 0, over 1, set_base 0, short 1`. Above the
    target that pays `0 + 1 × (pts − 0)`, below it `−(0 + 1 × (0 − pts))` — the
    same number, so the payoff is the IDENTITY on the declarer's points at
    every leaf and the minimax over it is the points minimax. **No `null`
    key**: a consolation is a cliff at one bit of state, not a point count, and
    it would make the answer something else entirely.
  - **the duck** — every ordinary leaf worth 0 and the consolation worth 1, so
    the value is 1 exactly when the declarer can force taking no scoring trick.
    That is `Dd::null_no_even_makeable`, which nothing exports.
* **Both are GATED IN RUST, because the claim is about the solver and nothing
  on the JS side can see it**: `wire::review::the_par_contract_is_exactly_a_
  double_dummy_points_solve` checks the synthetic contract against `Dd::solve`
  and `State::pool` (so it holds under every mode's scoring rather than against
  a second copy of the arithmetic), and `..._the_par_null_probe_is_exactly_the_
  ducking_search` against `nsearch`. Both assert the wire's own
  `contract_from_json` produces the contract they test, and both check
  NON-VACUITY — a guaranteed duck is RARE from a fresh deal, so its cases are
  found with the cheap boolean search first and only then priced with the
  expensive one (a sweep hoping to stumble on one costs minutes).
* **The row is two POSITIONS, not one number negated.** The declarer leads to
  trick 1 — measured at +0.93 points — so each cell re-solves with `leader` set
  to whoever is declaring and `trump` swapped to that denomination.
* **20 solves a round, over a pool of `max(1, min(hc − 2, 2))`** — the
  never-take-every-core rule, applied to a search that runs while a player is
  reading a modal. Points first, then the Null probes: the numbers are what a
  reader is waiting for. Measured 3.6s and 4.8s on two real deals; cells fill
  as they land and the set is cached (`PAR_CACHE`) only once COMPLETE, so a
  modal closed mid-solve re-asks rather than caching half a table.
* **Each column's best denomination is lit only once that whole column has
  landed** — a running maximum over a half-filled table moves as it fills and
  would decorate the wrong row on the way.
* Gated in `screens.mjs` beside the DD figure: every cell resolves to a number
  (the whole chain fails by staying on its placeholder, which reads as a table
  still thinking), the played contract is ringed exactly once in its own
  denomination's row, and both columns light a best.

## CFR OVER THE AUCTION — Expert's bid barely knows its own hand (2026-08-15)

`tools/cfrlab.py`. **The finding: `hand_strength` predicts the outcome strongly
and moves Expert's bid by less than one rung.** Across the eight strength
buckets the declarer's make rate runs **35.7% → 79.7%** while the settled level
runs **4.54 → 5.36**. The equilibrium's answer to the same deals runs 3.89 →
5.01 — also a shallow slope, but it wins the auction with the RIGHT hands: the
weakest bucket ends up declaring **1.2%** of contracts under equilibrium against
**7.1%** under Expert, and the strongest **25%** against **15%**. So the error is
not "Expert bids too high", which is where the self-play profile pointed; it is
**who ends up holding the contract**, and that is a defender-side failure as much
as a declarer-side one.

**WHY A SOLVE AND NOT ANOTHER ARENA.** The 800-round self-play profile above
recorded 28% of contracts settling at level 6 with 64% of those set, and could
not say whether that was the payoff asymmetry paying off or a shared blind spot
— **a mirror cannot diagnose itself, because both seats carry every bias.** This
is the poker toolkit (abstraction + CFR) applied to the one part of Dissonance
small enough to take it: the card play is far too big to abstract usefully, the
auction is a handful of bids over a ten-rung ladder, and its leaves can be
priced by the exact solver that already exists. That asymmetry is the whole
reason this was tractable.

**THE HEADLINE, on the same 394 deals with the same resolver and the same
scoring, undoubled on both sides** — the only thing that varies is who bids:

| | settled mean | made | declarer EV |
|---|---|---|---|
| Expert (shipped, k=8) | 4.70 | **59.4% ±4.8** | +6.24 |
| Abstract equilibrium | 4.67 | **72.0%** | +15.60 |

Equal aggression, 12.6pp apart on making it. Expert's per-rung selection against
the level's UNCONDITIONAL make rate — which is the yardstick, since landing on it
means the bidding added nothing — is **+15pp at level 3, +29 at 6, +31 at 7, and
−2 and +4 at levels 4 and 5**. Those two rungs carry 47% of its contracts and it
selects them at chance.

**THREE ABSTRACTIONS, and two of them cut against the finding rather than for
it.** (1) The hand is a quantile bucket of `bot.hand_strength` over the seat's
best denomination — information-legal by construction, never the solve, which
depends on the opponent's cards. (2) The auction is a level ladder: denomination
is abstracted away, so neither classic's `DENOM_RULE="used"` forever-ban nor the
same-level overtake exists, making the abstract game strictly MORE permissive —
**this is the honest limitation, since some of Expert's dispersion may be forced
by having burned its best suit, which the ladder cannot see.** (3) The leaf is
the points solve plus payoff arithmetic, i.e. exactly the approximation the
shipped tier already makes (93.3% agreement with `solve_contract`).

**The control arm resolves the deal AFTER the swap and the equilibrium's leaf
does not** — classic's swap phase upgrades one declarer card, so Expert's
contracts are scored on a slightly better hand than the equilibrium's are. That
biases the make rate in EXPERT's favour and it still loses by 12.6pp, so the gap
is a floor rather than an estimate. Checked rather than assumed, because the
opposite sign would have invalidated the whole comparison.

**Neither "declarer EV" column is a score.** These are two self-play regimes of a
symmetric zero-sum game — every seat has EV 0 by construction, and the number
only says how much winning the auction is worth in that regime. So the shapes
differing stayed an observation until it was priced, below.

### EXPLOITABILITY — 9.06 points a deal against a floor of 0.15

**BOTH NUMBERS IN THIS HEADING ARE SUPERSEDED — see "THE EXACT AUCTION LEAF"
below. Under the shipped (post-2026-08-16) price list and the real-play deal
cache, Expert reads 5.87 against a floor of 1.47.** The re-pricing alone did
that; the 9.06 was taken against the prices the game charged in mid-August and
was never re-run when they moved. Everything about the METHOD in this section
stands, and so does the DIAGNOSIS below (the opening ramping with strength where
the equilibrium's does not). Only the two magnitudes are stale, and the lesson
is the one this file already states about `DOUBLE_MARGIN`: **a constant — or a
measurement — in payoff units is silently re-scaled by a re-pricing.**

`cfrlab br`. Every Expert auction decision is logged as `(bucket, standing level,
prev level, holds, action)`, fitted as a policy over the abstraction's own
infosets, and an EXACT best response is computed against it. This is the
poker-standard measure and it is what turns the tables above into a number a
shipping decision can use.

| policy | BR as seat 0 | BR as seat 1 | exploitability |
|---|---|---|---|
| CFR equilibrium | +1.81 | −1.51 | **0.15** |
| Expert (413 rounds, 1311 decisions) | +9.33 | +8.79 | **9.06** |

Exploitability is `(BR0 + BR1)/2` — the game's value is not 0 by seat, because
the opener is FORCED to bid, and averaging the two cancels that positional term.
**Read the two rows as a difference and never the Expert row alone**: the CFR row
is the floor this abstraction reaches, not zero, being an average strategy over
finite iterations against a bucketed hand.

**Where the 9 points are** — the opening, and it is not a subtle effect:

| bucket | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| equilibrium opens at | 2.98 | 3.09 | 4.00 | 4.00 | 3.99 | 3.79 | 4.00 | 5.00 |
| **Expert** opens at | 1.38 | 1.65 | 2.60 | 2.47 | 2.78 | 4.04 | 4.46 | 4.48 |

**Expert ramps its opening monotonically with strength; the equilibrium does
not.** The equilibrium opens near 4 almost regardless — 3 at the very bottom, 5
only at the very top — while Expert opens 1.38 on its weakest hands and 4.48 on
its strongest. That is treating the opening as a STRENGTH SIGNAL, and in a
competitive auction it is exactly backwards: the opening is a claim on the
contract, and opening low on a weak hand both announces the weakness and invites
the opponent to buy the contract cheap. It is the mechanism behind the weakest
bucket declaring 7.1% of contracts against the equilibrium's 1.2%.

Two smaller cells, same table: Expert **concedes level 4** at 50% from bucket 3
and 17% from bucket 4, where the equilibrium concedes ~0% from bucket 2 up; and
Expert **contests level 6**, taking it 38% of the time at bucket 6 and 29% at
bucket 7, where the equilibrium passes at ~100% from every bucket — consistent
with the ladder table, where a level-6 contract is worth −14.52 even climbed.

**Three checks, because an exploitability number is easy to manufacture.**
* **The instrument is sharp**: against a UNIFORM random policy it reads 31.43,
  against the solved equilibrium 0.15. It is responding to the policy, not to
  the tree.
* **It is not a sample size.** A best responder steers TOWARDS whatever the fit
  does not cover, so an unseen infoset is the most exploitable thing there is —
  the first cut treated a miss as conceding and read **13.20 at 88 rounds**.
  Misses now BACK OFF along `prev`, then `holds`, then the bucket, and every
  lookup is renormalised over the legal set (a pooled distribution otherwise
  puts mass on a HOLD that is illegal at the cap, and vanishing mass reads as
  extra exploitability). At 413 rounds nothing is unseen, and **split-half fits
  read 10.09 and 9.24 against the full fit's 9.06** — converging from above, so
  the residual inflation is under a point.
* **The coverage figure that matters is reach-weighted**, not "what fraction of
  infosets did Expert visit". 17.2% of the best responder's own reach lands on an
  exactly-fitted infoset, 50.2% on one pooled over `holds`.

**THE ABSTRACTION HAD TO GROW A `HOLD` ACTION, and this is the trap worth
remembering.** A plain level ladder cannot express a same-level overtake in a
higher-ranked denomination — and **28.6% of Expert's decisions are exactly
that**. The first cut mapped them to "+1 rung", silently rewriting more than a
quarter of the behaviour it was fitting. `HOLD` is now its own action with the
consecutive count in the state; the bound is EXACT rather than a guess, since an
overtake needs a strictly higher rank out of 5 denominations. **The lesson is
that the abstraction's coverage of the thing being fitted is itself a
measurement** — the `flat` counter stays in the harness as that check.

Adding `HOLD` also killed the first best-response implementation, which
enumerated HISTORIES (255 without it, 65k with). It is now a DP over STATES —
`(level, prev, holds, actor)`, about 400 of them, children before parents — which
is exact because the history beyond that tuple changes nothing that follows it,
and runs in 0.8s.

### THE JUMP RATE AS A DESIGN KNOB — it buys discrimination, not evenness

`cfrlab jump RATE ITERS [SEED]`. If the equilibrium's answer is "open near 4
almost regardless", that is a flat auction however well a bot plays it — so the
question is whether the SCORING moves it. The jump bonus is the natural
candidate: it rides inside the set base, `-(N + 10 + rate × j + 5s)`, so its
expected cost is `P(set) × rate × j` and it is already strength-conditioned — a
weak hand goes down more often and pays it more often.

**No new deals are needed.** `pts` and `duck` are properties of the DEAL, not of
the scoring, so the whole 2000-deal cache re-prices under any terms. Sweeping a
scoring rule costs four CFR solves on four cores, not another control arm.

Two seeds per rate, because the first pass read a peak at 4 that turned out to be
sampling noise:

| rate | spread | discrimination | settled | made |
|---|---|---|---|---|
| 0 | 0.34 | +1.05 | 4.96 | 64.8% |
| **3 (shipped)** | **0.41** | **+1.8** | **4.67** | **72.9%** |
| 4 | 0.48 | +3.4 | 4.52 | 75.8% |
| 5 | 0.52 | +3.4 | 4.38 | 79.2% |
| 6 | 0.55 | +3.6 | 4.32 | 80.9% |
| 8 | 0.52 | +3.10 | 4.19 | 82.8% |
| 10 | 0.39 | +2.98 | 4.12 | 82.4% |

*spread* is the normalised entropy of the opening distribution; *discrimination*
is how far the opening moves from the weakest bucket to the strongest. **They are
different knobs and the distinction is the whole finding** — an auction can be
perfectly spread and carry no information, if the spread is randomisation rather
than strength.

* **The discrimination gain is all at 3 → 4** (+1.8 → +3.4) and then SATURATES:
  4, 5 and 6 are indistinguishable across seeds. Reading the single-seed numbers
  (+3.78 / +3.31 / +3.50) as a peak at 4 was noise, and the seed replication is
  the only reason that did not become a recommendation.
* Spread keeps climbing to 6 and then COLLAPSES: by 10 the distribution is a
  50/50 `1:49 4:49`, which is less even, not more.
* The cost is monotone and real: **the make rate climbs 72.9% → 79.2% at 5j**.
  Contracts get safe, which drains the play and undercuts the Double, whose
  whole premise is that contracts fail often enough to bet against.

**IT DOES NOT MAKE THE OPENING EVEN, AND CANNOT.** At every rate the
distribution stays BIMODAL — even at 6j it is `1:22 2:10 4:56 5:12`, and the mode
at 4 never drops below 56%. The jump term moves weight from 4 down to 1; it never
fills in 2, 3, 5 or 6. The reason is structural and the ladder table above says
it outright: **levels 1–3 make 95.7% / 90.4% / 80.0% and pay the declarer +12.71
/ +12.32 / +10.39.** They are near-free money, so the auction can never rest
there — whatever the jump term costs, the opponent simply takes the contract. The
jump rate makes HIGH openings expensive; it does nothing to make MIDDLE ones
attractive. A genuinely spread opening needs the low rungs to stop being a
giveaway, which is the make/set curve (`N² + 10` against a near-linear set base),
not the jump term.

### THE MAKE/SET CURVE — the ±10 flat stake is what pins the opening to 4

`cfrlab curve p=…,Fm=…,Fs=…,short=…,jump=…`. The jump sweep said a spread
opening needs the low rungs to stop being a giveaway, which is the make/set
curve. This sweeps it, and **the answer is one arm, verified over three seeds**:

| scoring | open spread | discrim | settled mean | made | opening |
|---|---|---|---|---|---|
| **shipped** `p=2, Fm=10, Fs=10` | 0.37 | +2.02 | 4.67 | 72.8% | `1:8 2:2 4:76 5:13` |
| **`Fm=0, Fs=0`** | **0.58 / 0.58 / 0.54** | **+3.8** | **4.63** | **73.5%** | `1:26 2:5 4:50 5:18` |
| `p=1.9, Fm=0, Fs=10` | 0.73 | +3.50 | 4.17 | 85.3% | `1:23 2:11 3:16 4:37 5:12` |
| `p=2.5, Fm=0, Fs=10` | 0.64 | +3.04 | 5.40 | 33.9% | `1:17 2:9 3:7 4:15 5:52` |

**Deleting both flat stakes buys +55% opening spread and +88% discrimination at
LITERALLY NO COST to the settled economy** — mean 4.67 → 4.63, make rate 72.8% →
73.5%, settled distribution `4:33 5:66` → `4:29 5:66`. It is a pure shape change,
and it is a *deletion of two constants* rather than a new term.

**The mechanism is the unconditional declarer-EV curve**, printed beside every
row and the only column here that is a mechanism rather than a summary:

```
shipped     EV  +13 +12 +10  +4  -9 -26 -43 -59   monotone: every hand wants
                                                   the lowest rung, so the
                                                   auction has ONE crossing
Fm=0,Fs=0   EV   +4  +4  +4  +1  -7 -21 -35 -50   flat over 1-4: several rungs
                                                   are viable openings
```

The reason is arithmetic. The made base runs 11 → 74 over levels 1..8, a factor
of 6.7, while the make PROBABILITY falls 95.7% → 2.3%, a factor of 42 — nothing
about a 6.7x reward against a 42x risk can be flat. **The flat +10 is what
compresses the reward ratio**: without it the base runs 1 → 64, a factor of 64,
which is the same order as the risk.

**The frontier, because opening spread and make rate are in tension.** Pushing
past `Fm=0,Fs=0` does buy more spread — `p=1.9` gives the sweep's prettiest
opening at 0.73, genuinely filling in level 3 — but it drops the settled level to
4.17 and takes the make rate to **85.3%**, i.e. contracts almost never fail and
the play loses its tension. In the other direction `p=2.5` puts an interior peak
in the EV curve (`+3 +5 +8 +8 -0`) and the auction climbs past it to settle at
5.40 with only **33.9%** making. `Fm=0,Fs=0` is the one point on the frontier
that moves the opening without moving anything else.

**Even this does not make the opening EVEN**, and no arm in the sweep does at an
acceptable make rate. `1:26 2:5 4:50 5:18` is two humps with more weight on the
low one, not a flat distribution — levels 3 and 6+ stay near zero. What the
change actually buys is DISCRIMINATION: the opening moves +3.8 rungs from the
weakest bucket to the strongest, against +2.0 today. That is the opening carrying
information about the hand, which is the thing worth having; an even distribution
for its own sake would be randomisation.

**THIS CONTRADICTS A SHIPPED CHANGE, and the disagreement is the point.** The
symmetric ±10 flat stake shipped 2026-08-11 on 400 paired Expert-vs-Expert deals
per arm, and was credited there with moving the SHAPE (2-opens 5.8% → 14.2%, the
settled level-4 crater filled). The equilibrium says the same constant is what
pins the opening at 4. **Both can be true**: that measurement judged shape by
Expert's behaviour, and Expert is the bidder this campaign has since measured at
9.06 points of exploitability, whose opening ramps monotonically with strength
exactly where the equilibrium's does not. A mirror's verdict on a design knob
inherits the mirror's blind spot. **Re-run any design arm that was judged only
by Expert self-play before treating it as settled.**

### SEARCHING THE SCORING FOR A TARGET PROFILE (2026-08-15) — and the ceiling

The brief: openings spread across all levels and decaying at the top, settled
contracts spread with a hump over 3-6. Encoded as `TARGET_OPEN` / `TARGET_SETTLE`
in `cfrlab.py` and scored by total-variation distance, so the sweep is SEARCHED
rather than eyeballed. Three stages — an EV-curve grid (276k scorings, free,
since `pts`/`duck` do not depend on the scoring), hand-picked probes, and a
random search once the probes stopped beating each other.

**Best found, loss 0.96 → 0.54:**

```
p=2.4, A=0.5, Fm=5, B=0, Fs=10, short=1, jump=5
  make = 0.5 x L^2.4 + 5      (6 / 19 / 79 at levels 1 / 4 / 8)
  set  = 10 + 5 x jump        (NO level term at all)
  open    1:28 2:25 3:18 4:26 5:3        target 22 19 17 14 11 8 6 3
  settled 1:5 2:5 3:7 4:12 5:48 6:16 7:5 target  4  9 18 23 22 15 6 3
  made 53.5%
```

Three of the four knobs that moved it are the ones the brief pointed at.
**Dropping the level term from the set base entirely** (`B=0`) — going down at 7
costs the same base as at 3, and only the shortfall separates them. **`short` 5
→ 1**, which is what actually makes the top of the ladder survivable, since
`short x (target − pts)` is quadratic-ish in the level (bid 7, make 3, and you
are four short on a base that also grew). **`jump` 3 → 5**, which does the job it
was designed for once the rest stops fighting it: openings decay to 3% by level
5 while the ladder stays climbable.

**THE OPENING IS ESSENTIALLY SOLVED; THE SETTLED DISTRIBUTION HAS A CEILING, AND
IT IS NOT IN THE SCORING.** Achievable points (best denomination, exact play)
measure **mean 4.03, sd 1.92** — so at `target = level` **one rung of the ladder
is 0.52 standard deviations**, and the make probability falls 80% → 63% → 42% →
23% across levels 3-6. An auction rests where the contract is worth about nothing
to the marginal hand, so a settled distribution spread over four rungs needs
EV ≈ 0 at all four *simultaneously* — which needs level 6 to pay ~13x level 3.
Solving that gives a make exponent near 3.7, and **it was tested**: it does
flatten the EV curve (`+2 +2 +4 +8 +8 -2 -20 -44`) but the crossing just RELOCATES
to 6-7 and the mode goes with it (settled mean 6.86, **10.1% making**). Flattening
the curve moves the mode; it does not widen it. Every one of ~60 scorings tried
put 45-60% of contracts on a single rung.

**The width is a property of the CARDS, not the payoffs** — 13 tricks and parity
scoring give that 1.92 sd, and no payoff rule can make the ladder finer than the
distribution it is measuring.

**THE UNRESOLVED DIRECTION, and it is the only one left with a mechanism:** make
the LADDER finer instead of the payoffs steeper — `target = 1 + (L−1) x tscale`,
so a rung is a smaller step in difficulty. First cut at 12 rungs and `tscale=0.6`
gave the **best opening in the whole campaign (loss 0.27-0.37 against 0.46
shipped), spread across eight rungs**. The settled distribution could not be
resolved: the tree is `2^MAXL`, so 12 rungs is ~16x the work of 8, 25k iterations
time out and 2k is pure noise — the "50% settle at 12" it prints is an unconverged
uniform policy racing up a long ladder, not a result. **Do not read the 12-rung
settled numbers as a finding either way.** Converging it needs a cheaper CFR
(outcome sampling) or a real compute budget.

**One experiment bug worth keeping, because it looked exactly like a result.**
The first finer-ladder run scored `make`/`set` off the raw RUNG while the target
came from `tscale` — so level 11 paid more than twice level 5 for a contract one
point harder, and the auction raced to the top (settled 10.2 of 12, 15% making).
That reads as "a finer ladder fails". It does not: **when the ladder is finer the
payoff has to track the TARGET, not the rung**, and the fix is one line.

### THE LOSS STATISTIC HAS A ±0.11 ERROR BAR, AND IT WAS NEVER MEASURED

**The most important correction in this campaign.** The scoring search ranked
~70 configs by a total-variation loss and reported differences of 0.05 without
ever asking what the statistic's noise was. Measured at last, by running ONE
scoring on four DISJOINT 500-deal subsets of the same cache:

```
loss = 0.68, 0.74, 0.74, 0.61     sd 0.054, so ±0.11 at two sigma
```

**Every ranking narrower than ~0.11 in the notes above is not a result.** That
includes "overtricks at 0 is worse" (0.59 vs 0.54), "the denomination price
multiplier is worse" (0.63 vs 0.54) and the jump-rate fine ordering. They are
untested, not refuted. The `made%` column swings 46-57% across the same subsets,
so per-config make rates are equally soft.

**What survives.** Shipped against the best found, PAIRED on each of the four
subsets: `1.08/1.19/0.99/1.16` against `0.68/0.74/0.74/0.61` — **+0.41 ± 0.11,
same sign on all four**. The headline gap is real; the fine structure inside it
is not.

The statistic is also SAMPLE-BIASED, not just noisy: the same scoring reads 0.54
on 2000 deals and 0.69 on 500. Compare configs only at equal deal counts, and
only paired on the same deals.

**How this surfaced, which is the reusable part.** The suit-priced ladder test
built a new 600-deal cache and came in at 0.74 against the old cache's 0.65 for
identical scoring. Chasing that gap ruled out, in order: solver state leaking
across denominations (0 of 24 pairs disagreed), the two caches' marginals (pts
mean 4.05 vs 4.04, sd 1.91 vs 1.89, P(make) curves within 1%), their joints
(corr(strength, points) +0.689 vs +0.642; corr between seats −0.658 vs −0.669),
the list-vs-int leaf path (**byte-identical output on the same deals**), and CFR
seed variance (tight: ±0.03 within a cache). Nothing was wrong. **The deal
sample was the whole effect**, and it had been invisible because every earlier
comparison happened to reuse one cache.

### MORE BIDS PER AUCTION IS NOT A SCORING QUESTION (2026-08-16)

**Asked directly — "how could we get more bids per auction?" — and the answer is
that the payoff curve cannot deliver it.** Four `cfrlab curve` arms on the
real-play cache (`cfr_real2.ckpt`, 2000 deals, 200k CFR+ iterations each):

| arm | loss | bids/auc | opening 1..5 | settled | made |
|---|---|---|---|---|---|
| `C=0` (shipped) | 0.69 | **3.49** | 34 28 13 14 10 | 5/5/5/8/**52**/23/2 | 69.8% |
| `C=1` | 0.76 | **3.44** | 22 24 19 23 11 | 2/2/4/7/31/**49**/3 | 62.2% |
| `C=2` | 1.16 | **3.46** | 16 19 21 26 17 | –/2/4/7/14/**63**/8 | 56.5% |
| `tscale=0.5` | 2.02 | **3.26** | 25 27 13 7 2 (8:25) | 3/3/4/2/**8:85** | 84.7% |

**bids/auction moves 3.26–3.49 across price curves that relocate the settled
mode from L5 to L6 to L8.** It is the one statistic in the table that will not
move. Read the arms as deltas only — the abstraction drops `DENOM_RULE`, so its
absolute 3.49 is not comparable to shipped Expert's 1.94.

**THE REASON IS ALREADY IN THIS REPO, in `denom_main`'s docstring, and it is
worth promoting because it is a general result:** every payoff rule scales the
per-rung fall in `P(make)` and the per-hand spread by the SAME `(make + set)`
factor, so **no payoff rule can move their RATIO** — and auction length depends
on that ratio, not on the prices. Rescaling payoffs rescales both seats'
valuations together; it changes WHERE they stop, not HOW MANY rungs they walk.
The four arms above are that invariance measured.

**The linear make term (`LINEAR_MAKE_BONUS`, the `C` knob) is refuted twice
over** and should not be revisited as a way to lengthen auctions: bids flat at
3.44, AND it breaks the "no level above 40%" constraint outright — L6 goes 23% →
**49%** at `C=1` and **63%** at `C=2`, with the make rate falling 69.8% → 62.2%
→ 56.5%. Raising the make reward makes the TOP of the ladder more attractive, so
the auction's destination rises; the path to it does not lengthen. `tscale`
(a finer ladder) is worse still — 85% settle on the top rung.

**THE ONE MECHANISM THAT ESCAPES THE INVARIANCE** is putting more rungs inside a
single step of DIFFICULTY, which changes the denominator directly. The five
ranked denominations may already be exactly that: a same-level overtake means
playing a genuinely WORSE suit, so it is harder than the standing contract and
easier than the next level. If that holds the ladder is ~5x finer than
`target = level` suggests, and what stops players walking it is
`DENOM_RULE = "used"` — the per-player forever-ban.

**THE `DENOM_RULE` QUESTION WENT BACK AND FORTH TWICE IN ONE DAY AND IS NOW
SETTLED BY MEASUREMENT — relaxing it does NOT lengthen auctions.** First it was
dismissed (nobody nears the five-bid ceiling), then that dismissal was retracted
(the ban bites on a seat's SECOND bid, where the marginal contests are, and the
abstraction that drops the ban bids more). The retraction's reasoning about WHEN
the ban bites is correct and its conclusion is still wrong, because it never
asked what the withheld rungs are WORTH: measured, a same-level overtake costs
1.13 points of difficulty against a level's 1.00 and pays the same, so it is
strictly a bad deal. The ban withholds rungs nobody wants. See "THE SUIT-PRICED
LADDER — RESOLVED" below for the paired 2000-deal arms.

**STATUS: the decisive test is the one already flagged INCONCLUSIVE below** —
`cfrlab dcache`, the suit-priced ladder, which prices a same-level overtake as a
genuinely worse contract instead of merely a dearer one. It needs the
all-denomination cache at 2000 deals (600 today, ~1 hour of solving) to be
compared paired and at equal size. Until then, whether more bids/auction is
reachable at all is OPEN — and the honest prior is that shipped 1.94 is close to
structural for this ladder.

### THE SUIT-PRICED LADDER — RESOLVED 2026-08-16, AND THE HYPOTHESIS IS REFUTED

`cfrlab dcache` builds a cache with `pts`/`duck` for ALL FIVE denominations per
seat, ordered by the seat's own `hand_strength` (never by the solved result,
which would be a cheater's ladder). `leaf` then indexes by `holds`, so a
same-level overtake selects a genuinely WORSE contract rather than merely a
dearer one — the flaw that made the earlier `dmult` probe uninformative.

**The cache is now 2000 deals** (600 + 1400, ~70 min of solving over four
shards), which is what this section previously said an answer required. The flat
CONTROL is derived from the same rows by repeating the best denomination, so the
two arms are paired on identical cards by construction — and where the real-play
`eps` is used it is drawn with the same seed sequence in both, so they are paired
on the noise too.

| ladder | leaf | **bids/auction** | settled | made |
|---|---|---|---|---|
| flat (overtake costs no difficulty) | double-dummy | 2.43 | 4:61 5:35 | 79.5% |
| **suit-priced** | double-dummy | **1.61** | 4:60 5:37 | 79.1% |
| flat | real-play | 3.67 | 5:35 6:44 | 64.8% |
| **suit-priced** | real-play | **2.71** | 5:32 6:45 | 64.0% |

**THE HYPOTHESIS IS REFUTED, and in the direction opposite to the guess.** The
idea was that five ranked denominations interleave four extra DIFFICULTY rungs
between every pair of levels, making the ladder ~5x finer and the auction
correspondingly longer. Pricing them honestly makes the auction **SHORTER** —
−0.82 bids double-dummy, −0.96 with real play, consistent across both regimes and
paired on the same deals.

**The mechanism, measured directly on the cache**: stepping down one
denomination costs **1.13 points** of achievable target (sd 1.60, n=4000), while
one LEVEL of the ladder costs 1.00. So a same-level overtake is *harder* than
raising a level — and it pays the SAME, because the level did not change. It is
strictly a bad deal, so the equilibrium declines it. Denominations are not
granularity; they are a penalty on overtaking.

**THEREFORE RELAXING `DENOM_RULE` WILL NOT LENGTHEN AUCTIONS**, and the
"residual limiter on auction length" framing elsewhere in this file is wrong.
The extra same-level rungs the forever-ban withholds are rungs nobody wants. This
also retracts a same-day correction that talked itself into the opposite view —
the ban does bite on a seat's second bid, but what it withholds is worthless, so
the bite costs nothing. Two reversals on one question in one day; the measurement
is the only thing here worth trusting.

**THE BIGGEST DRIVER OF AUCTION LENGTH IS NOT IN THE RULES AT ALL.** Real-play
noise adds **+1.10** bids (1.61 → 2.71 suit-priced, 2.43 → 3.67 flat) — larger
than any scoring knob and larger than the ladder's own structure. Uncertainty is
what makes a seat willing to contest. Any future attempt at longer auctions
should start there rather than in the price list.

**WHERE SHIPPED EXPERT SITS.** The most realistic cell — suit-priced, real
play — is **2.71** against Expert's measured **1.94**, so Expert under-contests
by ~0.8 bids and the headroom is a BOT gap, not a rules gap. **But 2.71 is an
UPPER BOUND**: the abstraction still drops `DENOM_RULE`, and this section's own
result is that structural penalties on overtaking cost ~0.9 bids, so the true
equilibrium with the forever-ban could plausibly sit at or below 1.94. Do not
quote 2.71 as a target without closing that gap.

### MEASURED: THE REAL LADDER IS 16% LOOSER, AND THE TUNING WAS AGAINST THE WRONG GAME

`cfrlab playnoise`. Impose a contract at each level on the cached deals, play it
out with the SHIPPED search on both seats, compare to the double-dummy answer.
794 rounds:

| bid | makes (double-dummy) | makes (real play) | gap |
|---|---|---|---|
| 3 | 80.5% | **88.5%** | +8.0 |
| 4 | 61.5% | **78.5%** | +17.0 |
| 5 | 41.5% | **57.5%** | +16.0 |
| 6 | 22.2% | **39.7%** | +17.5 |

**One rung costs 19.4 points of make-chance double-dummy and 16.3 in real play —
the ladder is 16% looser than every number above it in this file.** Two separate
effects: contracts make ~17 points more often (double-dummy assumes a PERFECT
DEFENDER, and a real one leaks tricks — the mean deviation is **+0.95 points**),
and the slope is gentler. The play noise measures **sd 1.94, as large as the
entire hand-quality spread of 1.92**, so what actually happens at the table has
**42% wider spread** than the solver's guaranteed value.

**AND THE CONCLUSION FLIPS.** Re-solving with a leaf built from the 794 measured
deviations instead of the double-dummy value:

| scoring | loss | opening | settled | made |
|---|---|---|---|---|
| **shipped**, real-play leaf | 0.73 (open **0.22**) | `1:32 2:20 3:17 4:3 5:23 6:5` | `5:18 6:66 7:6` | 63.8% |
| best-found, real-play leaf | 1.26 | `3:17 4:29 5:43` | `7:47 8:41` | 31.9% |
| shipped, double-dummy leaf | 0.96 (open 0.46) | `1:8 2:2 4:76 5:13` | `4:33 5:66` | 72.8% |
| best-found, double-dummy leaf | 0.54 | `1:28 2:25 3:18 4:26` | `4:12 5:48 6:16` | 53.5% |

**The shipped scoring already produces the best opening spread of the whole
campaign (0.22) once the leaf is realistic** — the "openings pile on level 4"
problem is substantially an artefact of pricing the auction with a perfect
defender. And the scoring tuned against the double-dummy leaf is much WORSE in
real play (1.26), settling at 7-8 with only 32% making: it was calibrated to
compensate for a leaf that understates make rates by 17 points, so it
over-corrects once that understatement is removed.

**What the real problem turns out to be:** under real play contracts settle too
HIGH (mean 5.47, 66% at level 6), not openings too narrow. That is a different
target for the next round of tuning, and every scoring conclusion in the two
sections above needs re-deriving against this leaf before being trusted.

**Caveats, and the first is load-bearing.** The real-play cache applies a sampled
deviation to EACH SEAT INDEPENDENTLY, but the two seats' outcomes are strongly
anti-correlated (measured −0.658 on the double-dummy values) — one side's leaked
trick is the other's gain. Independent sampling therefore overstates the joint
variance, and the settled-level numbers above are softer than the opening ones
because of it. The deviations were also measured with the declarer as the opener
at a forced contract over levels 3-6 only. And the ±0.11 error bar still applies
to every loss in the table.

### THE CANDIDATE SCORING, searched against the real-play leaf, whole numbers only

The re-run after the leaf was fixed. Two constraints that were not there before:
the leaf carries the measured play deviation, and **every constant is an integer**
(a scoring rule is read at a table; `0.5 x L^2.4` is not a rule anyone can hold
in their head). The previous best-found arm does not survive either change, which
is the correct outcome — it was fitted to a leaf that understates make rates by
17 points.

```
make      L^2 + 5              6  9 14 21 30 41 54 69   (overtricks pay NOTHING)
set base  2L + 12 + 7 x jump   climbed: -25 -27 -29 -31 at levels 3-6
                               opened:  -39 -48 -57 -66
short     1 per point          (shipped: 5)
```

Against shipped, PAIRED on four disjoint 500-deal real-play subsets:

| | sub0 | sub1 | sub2 | sub3 | mean |
|---|---|---|---|---|---|
| shipped | 0.98 | 0.85 | 0.84 | 1.07 | 0.94 |
| **candidate** | 0.56 | 0.55 | 0.57 | 0.68 | **0.59** |

**+0.34 ± 0.06, same sign on all four** — comfortably outside the ±0.11 error
bar, and this time measured the way the error-bar section says to measure.

| | opening | settled | mean | made |
|---|---|---|---|---|
| shipped | `1:39 2:7 3:2 5:35 6:15` | `5:31 6:55 7:7` | 5.51 | 59.4% |
| **candidate** | `1:33 2:20 3:20 4:26 5:2` | `1:5 2:4 3:8 4:16 5:39 6:27` | 4.65 | 72.8% |

It fixes the problem the real-play leaf exposed: **contracts no longer pile on
level 6** (55% → 27%) and the settled mean comes down 5.51 → 4.65. Openings
spread across 1-4 instead of splitting between 1 and 5-6.

**Three changes do the work, and each maps to a stated design intent.**
Overtricks stop paying, so a strong hand can no longer sit on a cheap contract
and farm extras — it has to bid what it can make. Falling short costs 1 rather
than 5, which is what makes the upper rungs reachable at all (`short x (target −
pts)` is quadratic-ish in the level). And **the jump penalty more than doubles,
3 → 7**, which is the term that keeps high OPENINGS rare while leaving the ladder
climbable a rung at a time — exactly what the jump rule was designed for.

**BIDS PER AUCTION — the stat that was missing, and it carries a regression.**
Mean auction length is unchanged (2.73 shipped, 2.71 candidate) but the shape is
not:

| bids | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 |
|---|---|---|---|---|---|---|---|---|
| shipped | 23% | 38% | 13% | 11% | 6% | 5% | 3% | — |
| candidate | **33%** | 33% | 11% | 7% | 4% | 4% | 6% | 2% |

**One-bid auctions rise 23% → 33%** — a third of auctions would be the opener
naming a contract and the opponent conceding at once. A mean auction length that
does not move can hide that entirely, which is why the distribution is the thing
to report and the mean is not.

**THE LINEAR MAKE TERM FIXES THE ONE-BID REGRESSION, and buys it with level 6.**
`C` adds `C x level` to the made base, mirroring the linear term the set base
already carries. In EV terms it is a HIGH-contract subsidy — the opposite tilt to
the flat bonus and the overtrick rate — so it makes climbing worth doing:

| arm | make | over | jump | 1-bid | mean bids | opening | settled |
|---|---|---|---|---|---|---|---|
| A | `L^2 + 5` | 0 | 7 | **33%** | 2.71 | 0.23 | **0.28** |
| B | `L^2 + 1L` | 1 | 7 | 32% | 2.97 | 0.33 | 0.29 |
| C | `L^2 + 2L + 2` | 1 | 5 | **17%** | 3.71 | **0.17** | 0.50 |
| D | `L^2 + 2L + 5` | 1 | 7 | **13%** | 4.03 | 0.33 | 0.53 |

C's opening spread (0.17) is the best measured anywhere in this campaign, and D
more than halves the one-bid rate. Both settle ~65% on level 6.

**Three couplings worth carrying, all measured here:**
* **Overtricks BLUR the levels.** With `over = 1` a contract that takes 7 tricks
  pays nearly the same bid at 3 as at 5, so the rung chosen matters less and the
  auction converges — level 4 hollows to 3-5% in every `over=1` arm at C=0.
* **The flat make bonus and the overtrick rate are the SAME KIND of term** — both
  are low-contract subsidies in EV (`Fm=5` is worth `0.88 x 5` at level 3 against
  `0.40 x 5` at level 6), so they trade off directly and can be tuned as one.
* **`C` and `B` fight each other.** Raising the set base to stop C pushing
  contracts to 6 just undoes what C bought: bids fall back to 2.4 and level 5
  balloons to 72-79%. They are the same axis with opposite signs, so pick one.

**Scaling is the third way to keep overtricks small.** A trick is worth 1 and
cannot be scaled, so multiplying every OTHER term makes an overtrick
proportionally smaller: at 3x (`3L^2 + 15` make, `6L + 36 + 21j` set, short 3)
with `over = 1` the loss is 0.57 against A's 0.51 — most of A's shape, with every
trick still counting.

**NOTE ON THE LOSS COLUMN FOR C AND D.** It penalises level 6 heavily because
`TARGET_SETTLE` encodes the ORIGINAL brief (a hump over 3-6). If settling at 6 is
acceptable, that target is wrong for the question being asked and C/D are being
marked down for hitting a spec that has since changed — re-run the search with a
revised `TARGET_SETTLE` rather than reading their 0.68/0.76 as worse.

**FINAL TARGET (2026-08-15): level 6 acceptable, no rung above 40%, and a
COMMON LEVEL-1 OPENING IS FINE.** The last of those retired `TARGET_OPEN`'s
linear decay, which wanted 22% at the floor and was penalising the ~38% every arm
produces -- effort spent fighting a shape nobody objected to, and it competed
directly with the settled distribution, which is what actually matters.

**SUPERSEDED — see "the whole scoring search ran without the Double" below. The
candidate here was fitted on a tree missing the Double; the arm re-fitted WITH it
is `Fs = 10`, and its numbers are in that section.**

**THE CANDIDATE (no-Double tree):**

```
DECLARER scores, made      L^2 + L + 2   ->  4  8 14 22 32 44 58 74
                                             +1 per overtrick
DEFENDER scores, set       2L + 12 + 6j  ->  climbed 20 22 24 26 28 30 32 34
                                             opened  20 28 36 44 52 60 68 76
                                             +1 per point short (shipped: 5)

settled  1:5 2:4 3:2 4:15 5:35 6:38      max 38%, under the cap
opening  1:39 2:18 3:5 4:35 5:2
bids     3.04 (23% one-bid)   made 69.0%   loss 0.61
```

Verified across four disjoint 500-deal real-play subsets: 0.77 / 0.67 / 0.53 /
0.76, mean 0.68 sd 0.096 — consistent, and the usual small-sample bias against
the 0.61 read on the full 2000-deal cache. **Caveat on the cap: the maximum is
38% on the full cache but ranges 33-46% across the subsets**, so the cap is met
in expectation rather than robustly.

Every constant is an integer, and both sides now carry the same shape --
quadratic + linear + flat on the make, linear + flat on the set.

**STATED AS WHAT EACH SIDE SCORES, not as a signed payoff.** `_split` gives the
whole amount to exactly one seat and zero to the other, so a set is the DEFENDER
banking `2L + 12 + 6j` plus a point per point short -- it is never a deduction
from the declarer, and nobody's score goes negative. The solver works on
`declarer - defender`, so the two framings are the same arithmetic, but writing
the set side as a negative number invites reading it as a penalty the declarer
pays out of their own total, which is not the game.

**Earlier revision, kept for the reasoning:**
`_SETTLE8` becomes `[.03 .06 .13 .20 .24 .20 .10 .04]` and `_tv` gains an
explicit `CAP = 0.40` penalty at weight 2 — a total-variation distance alone
trades one 50% spike against small errors spread elsewhere and can score them
equal, so the spike has to be priced separately. The search was also constrained
to `jump ∈ {5, 6}` and `over ≥ 1`.

**Best under the revised target:** `L^2 + 1L` make, +1/overtrick, `2L + 12 + 5j`
set, −1/pt short.

```
settled  1:6 2:3 3:3 4:14 5:40 6:35     max 40%, exactly at the cap
opening  1:38 2:10 3:8 4:34 5:10
bids     2.98 (26% one-bid)             made 70.1%
```

**THE JUMP RATE IS NOT WHAT DRIVES LEVEL-1 OPENINGS — measured, and it was the
working hypothesis.** Holding the rest fixed and sweeping only the jump: 7 → 40%,
6 → 39%, 5 → 38%. Three points, one point of movement. What DOES move it is the
linear make term plus a flat bonus (`C=2, Fm=2` takes level-1 openings to **21%**,
the best measured) — but that combination pushes 64% of contracts onto level 6
and breaks the cap. **The two constraints are in tension in every arm measured:
nothing achieves both a settled maximum under 40% and level-1 openings near 22%.**

**The likely reason is structural, and it points at a RULE rather than a price.**
The opener is FORCED to bid (`OPENER_MAY_PASS` is False in classic), so a hand
with nothing bids the floor — that is not a value bid, it is a pass wearing a
bid's clothing. With 8 strength buckets the bottom three are 37.5% of hands, and
the measured level-1 opening rate is **38%**. That correspondence is suggestive
rather than proven, but it predicts that no scoring change will fix this and that
`OPENER_MAY_PASS = True` would — the flag already exists in the engine and is the
next thing to test.

**Two things it does NOT achieve, stated plainly.** Nothing opens above level 4
(the target wants 17% at 6-8), and the settled hump still sits at 5-6 rather than
3-6 (`3:8 4:16` against a target of `3:18 4:23`). And the make rate RISES, 59.4%
→ 72.8%: cheap sets and no overtrick income make the whole ladder safer, which is
a real trade against the Double's premise and would need `DOUBLE_MARGIN`
re-swept.

### THE EQUILIBRIUM DOUBLING RATE (2026-08-15) — 32% shipped, 11% candidate

`cfrlab curvedbl` adds the Double to the solved auction: the seat that concedes
then chooses whether to double, both bases doubling as they do in the engine.

| scoring | doubles taken | of those, set |
|---|---|---|
| shipped | **32%** | 49% |
| candidate (`L^2+L+2` / `2L+12+6j` / short 1) | **11%** | 54% |

**The candidate cuts the correct doubling rate to a third of shipped, and out of
the 20-30% band this campaign set as the design target.** That is a genuine cost
of the candidate scoring and it belongs beside the settled distribution when
judging it — a scoring that quietly retires the Double has changed the game more
than its distribution tables show.

**A RETRACTED CLAIM, and how it was caught.** This section first read "the Double
is not an equilibrium action" on a measured 0% rate under BOTH scorings, with a
theory attached: whoever concedes has revealed they expect the contract to stand,
so doubling is never right. **That was wrong.** The 0% came from the counting
block being spliced into `jump_main`'s playout while its counter and its report
line lived in `curve_main` — so it incremented nothing and printed a clean,
plausible zero. The solver had learned the Double correctly all along: 653
infosets carry positive regret for doubling and the sacrifice infosets read
`P(double) = 1.000`.

It was caught by the obvious question the wrong answer invited — *"so there are
no sacrifices? Because sacrifices should be doubled"* — and the check that
followed found **7 reached defender infosets with a negative declarer
expectation, carrying 5.1% of all settled contracts.** A zero that survives a
plausible story is still a zero worth interrogating; the story is what made it
survive.

**This is the SECOND silent-zero in this file's campaign.** The other was
`g.get("points", [0, 0])` against an engine key of `pts`, which made every played
round score 0 and read as "real play never makes anything". Both were defaults
standing in for a value that never arrived, and both produced a number too
tidy to question. **When a measurement comes back exactly 0 or exactly 100%,
verify the counter fired before believing the result.**

**What still holds about tuning it.** `DOUBLE_MARGIN` is a threshold on the
SEARCH's edge estimate, not an equilibrium quantity — the equilibrium says how
often doubling is correct, not how much noise the margin must reject. So the
margin still has to be re-fitted against the actual bot playing the new scoring
(`dblsweep.py` over a recorded arena run, pricing every threshold offline), and
that remains blocked on putting the candidate scoring in the engine. The
equilibrium rate is the target the fitted margin should be checked against: 11%
under the candidate, against 27.2% measured for shipped Expert.

### THE WHOLE SCORING SEARCH RAN WITHOUT THE DOUBLE IN THE TREE

Found while sweeping `short` against the doubling rate, and it is the larger
finding. **Adding the Double changes the settled distribution substantially** --
it is a real branch of the game with real payoffs, and every distribution in the
sections above was solved without it:

| | settled | max | made |
|---|---|---|---|
| candidate, no Double | `1:5 2:4 3:2 4:15 5:35 6:38` | **38%** | 69.0% |
| candidate, Double in tree | `1:5 2:5 3:8 4:9 5:55 6:18` | **55%** | 73.6% |
| shipped, no Double | `5:30 6:63` | 63% | 57.7% |
| shipped, Double in tree | `3:8 4:15 5:60 6:9` | 60% | 73.5% |

**The candidate's headline result — a settled maximum of 38%, under the 40% cap —
does not survive the Double.** With it the mass concentrates on level 5 at 55%.
The shipped scoring moves too (its pile shifts from level 6 to level 5). Every
scoring comparison in this file was therefore made on a tree missing a branch
both sides use, and **the search should be re-run with `curvedbl` before any of
its rankings are trusted**.

**IT DID NOT SHIP — the Double invariant breaks at levels 2-3.** Attempting the
push turned up a design regression the loss function never looked at.
`test_doubling_still_risks_more_than_it_wins_on_a_near_miss` asserts that on the
COMMON failure (one point short) a made contract still risks more than the double
wins, i.e. `make(L) > set_base(L) + ramp`:

| bid | 1 | 2 | 3 | 4 | 5 | 6 |
|---|---|---|---|---|---|---|
| candidate risk / reward | 4 / 13 | **8 / 15** | **14 / 17** | 22 / 19 | 32 / 21 | 44 / 23 |
| shipped risk / reward | 11 / 12 | 14 / 13 | 19 / 14 | 26 / 15 | 35 / 16 | 46 / 17 |

**Under the candidate, doubling a level-2 or level-3 contract is free money** --
shipped holds the line from level 2 up, and the candidate breaks it. Those rungs
carry 11% of settled contracts, which is the same size as the whole measured
doubling rate, so **the "11% doubled" figure is probably mostly degenerate
auto-doubles rather than reads.**

The cause is an asymmetry introduced by the re-pricing: the made base's flat term
went 10 -> 2 while the set base's stayed at 10, so at low levels the set base
dwarfs the make (4 against 12 at level 1). And the fix costs the win: the
property needs `L^2 + L + Fm > 2L + Fs + 1` from L=2, which wants `Fm >= 10` or
`Fs <= 2` -- and BOTH were measured to pile 61-70% of contracts onto level 6.
**The candidate's settled spread is partly bought by the same lopsided flats that
break the Double**, so the two cannot be had together by tuning these constants.

What DID land is the refactor, with every value unchanged: `LINEAR_MAKE_BONUS`
(0), `SET_LEVEL_RATE` (1) and `CLASSIC_SHORT_PENALTY` (5, split from skat's so
the two can move independently). The scoring change is now one edit per constant
whenever the Double question is answered, and the tests were rewritten to derive
both bases from the constants rather than hardcode them -- so the next re-pricing
lands as five lines, not forty-one failures.

### RECALIBRATING EXPERT FOR THE SHIPPED SCORING (2026-08-16)

The re-pricing landed; Expert was fitted against the old economics. First piece
done, and it moved a long way.

**The equilibrium's opening under the NEW scoring, CFR+ at 120k, four seeds:**

| bucket | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| new scoring | 1.59 | 1.99 | 2.05 | 3.00 | 2.45 | 3.06 | 2.68 | **4.54** |
| old scoring | 2.25 | 2.71 | 3.26 | 3.86 | 3.41 | 3.76 | 3.82 | 4.87 |

**Buckets 0-6 now all open between 1.6 and 3.1 and only the top bucket leaps** —
where the old curve ran 2.25 → 4.84 across the whole range. That is the doubled
jump penalty doing its designed job: leaping to 5 costs the defender 42 on a set
against 18 for walking there, so the equilibrium opens low and CLIMBS. `bot.py`'s
`_OPEN_TARGET` is re-fitted; the cuts are unchanged, being strength octiles of
the deal cache and independent of the scoring.

**THE BIAS COULD NOT MIX — FIXED.** The equilibrium's per-bucket opening is a
MIXTURE: bucket 0 plays **53% level 1 and 38% level 2**. A quadratic pull toward
its mean of 1.59 is a POINT target that simply picks the nearer rung, so level-1
openings vanished entirely (18% → 0% in the arena) — not what the equilibrium
does, and in an imperfect-information game the mixing is frequently the point.

The fix is not sampling (which would override the search's per-deal opinion) but
**biasing by the equilibrium's LOG PROBABILITY per level**, normalised so its
favourite rung costs nothing. Rungs it mixes over stay cheap, rungs it never
plays are dear, and the search still chooses within that shape. The full
`_OPEN_DIST` table replaces `_OPEN_TARGET`, with a 0.02 floor so an abandoned
rung is expensive rather than impossible — the search sees the actual deal and
the table does not.

Measured: level-1 openings return at **27%**, and the per-bucket bias reads 0.00
at every rung the equilibrium favours (bucket 0: L1 0.00, L2 −0.34, L3 −2.03;
bucket 7: L5 0.00, L4 −0.05, L1 −3.14). The mixture's shape survives.

**THE PAYOFF IS STILL UNMEASURED.** Arena under the shipped scoring: the
quadratic version read −7.30 ± 8.92 over 22 paired deals; the log-prob version
reads −2.36 ± 7.14 at w=0.5 and +0.18 ± 13.93 at w=2.0 over 11 deals each. Every
one of those CIs is several times its own estimate. **None of them is a result**,
and the weight remains unswept in any meaningful sense. The bias stays OFF by
default.

The blocker is arithmetic, not design: per-deal sigma is ~15.8 even CRN-paired
and dd-resolved, the arena manages ~10 paired deals per 500s at k=8 and does not
parallelise past two shards, so ±1.5 on ONE weight is ~20 hours. A three-weight
sweep is a multi-day unattended job, not an interactive one.

**What is left to recalibrate**, in the order it matters:
* `DOUBLE_MARGIN` (20) was fitted against the old economics. **CHECKED
  2026-08-16 against 322 recorded doubles under the new prices, and it is FINE
  where it is** — 26.1% doubling, discrimination +30.4, defender gain +2.00. A
  re-fit to 4 was attempted, shipped, and reverted the same day; the section
  below is the postmortem. This entry's own closing clause — that the margin is
  a threshold on the SEARCH's edge estimate and needs `dblsweep.py` rather than
  arithmetic — was right, and was still not enough, because the sweep itself was
  misread.
* ~~The opening bias needs a weight sweep AND the mixing question answered.~~
  **CLOSED 2026-08-16: the mixing question is answered and it kills the arm.** A
  log-probability bias over an ARGMAX cannot express a mixture, so no weight
  reaches the target — measured at w=1/2.5/5, every one made both bids/auction
  and the opening distribution WORSE. **Do not run the weight sweep.** Section
  below.
* `hand_strength` itself is unexamined against the new economics — and so is
  `_CLASSIC_LEVEL_NEEDS`, the strength→level map that picks the opening bid for
  the NON-search tiers, which is the only one of its four siblings with no
  calibration provenance at all. See the payoff-unit audit below.
* `EXPERT_OPP_TEMP` was checked and needs nothing — same units as the margin,
  but a scale parameter rather than a tail threshold. Audit below.

### `DOUBLE_MARGIN`, 2026-08-16: A RE-FIT THAT WAS WRONG, SHIPPED, AND REVERTED

**Outcome first: 20 stands.** A re-fit to 4 was argued, shipped to main, ran in
prod for about two hours, and was reverted when the follow-up measurement
contradicted it. Everything below is the postmortem, kept in full because the
failure was in the INSTRUMENT and it read as a clean result twice.

**THE BUG: `dblsweep.py`'s margin column is a DELTA, not an absolute.** The
arena records the search's two sums at each double, and `wire.rs` applies the
margin by `sums[esc] += margin * deals.len()` BEFORE returning them. So the
recorded sums already carry whatever `DOUBLE_MARGIN` was live during that run,
and a threshold swept over them lands at `live + delta`. The sweep was run over
data recorded while 20 was live and read as absolute, so:
* its column `4` was really margin **24**, and that is what got shipped as `4`;
* its column `20` — the "4.6% doubling at +0.2 discrimination" row that
  supposedly condemned the shipped value — was really margin **40**. Of course a
  margin of 40 rejects everything. **20 was never measured at all.**

**THE CHECK THAT PINS IT, and that should have been run first: column 0 of a
sweep must reproduce the directly measured doubling rate of its own dataset.**
It does, and that is what exposed this:

| dataset | live margin | measured doubled | sweep column 0 |
|---|---|---|---|
| `dbl.jsonl` (n=132) | 20 | **22.7%** | 23.1% |
| `prof` (n=336) | 4 | **49.4%** | 47.2% |

Two datasets recorded at different live margins now agree once both are read as
absolute (margin 20 reads 23.1% and 26.1%). `dblsweep.py` now **requires
`--live` and refuses to run without it**, prints the column as absolute, and
says which row reproduces the recording run.

**What shipping `4` actually did:** doubled **49.4%** of contracts against
22.7% under 20, with an equilibrium that wants ~15% — most of the way back to
the 59% the knob was introduced to fix.

**20 ON THE NEW PRICES, measured properly** (322 recorded doubles, absolute
margins, larger and cleaner than the sample that started this):

| margin | dbl% | on FAIL | on MADE | disc | defender gain |
|---|---|---|---|---|---|
| 4 | 47.2% | 79.6% | 30.8% | +48.8 | +2.29 |
| 8 | 41.6% | 74.1% | 25.2% | +48.8 | **+2.85** |
| 12 | 35.4% | 64.8% | 20.6% | +44.3 | +2.73 |
| **20 (shipped)** | **26.1%** | **46.3%** | **15.9%** | **+30.4** | **+2.00** |
| 24 | 19.3% | 35.2% | 11.2% | +24.0 | +1.83 |
| 28 | 14.9% | 24.1% | 10.3% | +13.8 | +1.16 |

**NOT SETTLED, and deliberately not acted on.** Margins 6–12 discriminate better
and pay the defender more than 20 does, which is plausible on its face — the
belief prior arrived after 20 was fitted and does some of the same work. But
that reading rests on the **payoff** columns, which are the noisy ones, and it
wants a doubling rate three times the equilibrium's. After two wrong answers in
one day from re-reading this table, moving the value needs a paired arena.

**THE LESSONS, and the second one is the expensive one:**
1. A constant in payoff units is silently re-tuned by a re-pricing. Still true,
   still worth the audit (next section) — it is just not what happened here.
2. **A measurement instrument can carry the state of the system it measures.**
   `dblsweep`'s whole selling point is that one run prices every threshold
   offline; what made that false is that the run's own margin is baked into
   what it recorded. **Before trusting a swept table, check that the row
   corresponding to the live setting reproduces the run's observed behaviour.**
   That check is one line, it is exact, and it would have caught this instantly.
3. Corollary on process: the first re-fit was reported with careful error bars
   on the right columns and an explicit note that the payoff columns were too
   noisy to choose. All of that was true and none of it helped, because the
   axis itself was mislabelled. **Calibrate the instrument against a known
   point before quoting precision.**

`tools/dblsweep.py` now lives in the repo (this file referenced it for two
sections while it existed only in a scratchpad). Its constants come off
`engine.py` rather than being typed in — the previous copy hardcoded `10, 5, 1,
3`, which the re-pricing had moved three of, plus a level RATE the literals could
not express at all. It also read only `events[0]` of each checkpoint line for
its first month, silently **halving every sample it ever reported** — a line
holds a deal's two flips. Both flips are read now.

### THE PAYOFF-UNIT CONSTANT AUDIT (2026-08-16) — STILL WORTH HAVING

**Read this one knowing the section above was retracted.** The audit was
triggered by a finding that turned out to be an instrument bug, and it was run
against `EXPERT_OPP_TEMP` by a route (`pricescale.py`, a band check on measured
scale ratios) that does NOT depend on the retracted claim. Its conclusion —
that the temperature is in band and needs nothing — survives; what does not
survive is the framing that `DOUBLE_MARGIN` had been broken by the same force.

Every constant that could be scale-coupled was swept. The rule it produced is
still the useful part, with the `DOUBLE_MARGIN` example struck:

> **A THRESHOLD sitting in the TAIL of a distribution is more exposed to a
> re-pricing than a SCALE PARAMETER applied across the BULK, which degrades only
> proportionally.** So audit tail thresholds first. (The original version of this
> rule cited `DOUBLE_MARGIN` as a threshold the re-pricing had destroyed. It had
> not — that was the instrument bug. The rule is kept as a PRIOR about where to
> look, not as a claim backed by that example.)

| constant | units | verdict |
|---|---|---|
| `DOUBLE_MARGIN` | per-world payoff pts | fine at 20 — see the postmortem above |
| `EXPERT_OPP_TEMP` | per-world payoff pts | **coupled, measured, STILL IN BAND** |
| `auction.rs` `LOW=-30`, `set_base=1_000_000` | trick totals / sentinel | not tuning constants; sentinels dominate at any scale these prices reach |
| `_KONTRA_TARGET` 9, `_KONTRA_STRENGTH` 12.5 | skat CARD points | different currency; skat's prices did not move |
| `_BID_TILT`, `_SWAP_*` | strength / trick units | not payoff-coupled |
| `_MINOR_*`, `SKAT_NULL_VALUE`, `SHARP_BONUS` | their own currencies | untouched by the classic re-price |

**`EXPERT_OPP_TEMP = 5.0` is a genuine sibling and it is worth knowing why it
survived.** The softmin computes `exp(-(v/k)/temp)`, so `temp` divides a
per-world payoff exactly as the margin is compared against one — the crate's own
comment says "in per-world payoff points". But it is a scale parameter over the
bulk, and the bulk barely moved: the payoff sd ratio is **0.907**, the make/set
gap ratio **0.725**. Rescaling the original fitted band by those gives **4.5–10.9**
or **3.6–8.7**, and **5.0 is inside both**. The shipped value did not leave the
band it was fitted in, so there is nothing to change. (That original fit was
itself loose — "somewhere around 5–12" from a 3-point sweep at n=150 — so a
re-fit would be measuring noise unless the sweep is rebuilt, which is not worth
arena hours against a constant that is not out of band.)

**AND A GAP FOUND WHILE SWEEPING, unrelated to payoff units:
`_CLASSIC_LEVEL_NEEDS = ((6, 15.0), (5, 12.5), (4, 10.5), (3, 8.5), (2, 6.5))`
carries NO calibration provenance** — while all three of its siblings
(`_MINOR_LEVEL_NEEDS`, `_SKAT_LEVEL_NEEDS`, `_DUMMY_LEVEL_NEEDS`) have headers
naming the calibration tool and the date. It is the strength→level map that
picks the **opening bid for the non-search tiers**, and the re-pricing campaign
never touched it (the "recalibrate Expert" work was about the search, which does
not use this map). Measured over 4000 fresh deals, it opens:

| | L1 | L2 | L3 | L4 | L5 | L6 |
|---|---|---|---|---|---|---|
| heuristic tiers today | 4.5% | 15.0% | 29.2% | 28.2% | 19.0% | 4.0% |
| CFR+ equilibrium | 32% | 20% | 15% | 12% | 9% | 6% |

**This is a flag, not a verdict, and the difference must not be over-read.** The
equilibrium is an abstraction and a DIRECTION rather than a table to ship (the
standing caution above), and the settled distribution is still level-5-heavy
under the new prices, so opening at 3–4 and climbing is not obviously wrong. What
IS established is narrow and sufficient to act on later: this constant is
uncalibrated, its siblings are not, and nobody has looked at it since the prices
moved. It belongs with `hand_strength` on the recalibration list, not ahead of it.

### THE OPENING BIAS — MEASURED 2026-08-16 AND IT DOES NOT WORK. STAYS OFF.

**Verdict first: the mechanism cannot do what it was built to do, and no weight
fixes it.** The old note here said it needed "a weight sweep AND the mixing
question answered". The mixing question is now answered and it is fatal, so the
weight sweep — the ~20-hour job — should NOT be run.

**A log-probability bias plus an ARGMAX cannot express a mixture.** The bias adds
`w x (log p[level] - log p_best)` per option and the search then takes an argmax
over `value + bias`. Argmax of a biased value is still a POINT choice. Within a
strength bucket the bot therefore picks ONE level, and the only thing that
produces a spread of openings across hands in that bucket is hand-to-hand
variation in the search value — which is exactly what a larger `w` overwhelms.
So turning the bias up does not converge on the target distribution, it
COLLAPSES each bucket onto its modal level. To hit a distribution you need to
SAMPLE (softmax over the biased values), not to bias an argmax.

**Measured**, 4 arms, ~120 auctions each, self-play `experttb`, `play`-resolved
(auction statistics are resolution-independent; validated by counting bids two
ways on the dd data — from the `settled` field and from `decision` kinds — both
give exactly 1.94):

| w | bids/auction | 1-bid | opening L1..L6 | TV from equilibrium |
|---|---|---|---|---|
| **0 (shipped)** | **2.19 ±0.18** | 26.5% | 24 24 22 12 12 6 | **10.4** |
| 1 | 1.93 ±0.17 | 38.3% | 27 17 10 25 17 5 | 18.0 |
| 2.5 | 1.96 ±0.21 | 43.6% | 35 11 4 31 11 9 | 30.1 |
| 5 | 1.88 ±0.18 | 43.9% | 25 14 23 19 19 0 | 12.6 |

* **It never helps on either axis.** Every weight LOWERS bids/auction and every
  weight moves the opening distribution FURTHER from the equilibrium. The
  per-arm CIs on bids/auction overlap, but the direction is consistent across
  three independent weights.
* **The collapse is visible in the shape.** At w=2.5 the distribution is
  BIMODAL — L1 35% and L4 31% with a hole at L3 (4%, against 22% unbiased).
  That is the predicted signature and it is far outside sampling noise.

**AND THE PREMISE WAS PARTLY WRONG.** Shipped Expert's opening MARGINAL is
already close to the equilibrium's (TV 10.4). The exploitability defect was
never that the marginal is wrong — it is that opening level does not vary enough
WITH HAND STRENGTH (0.82 rungs across a range where the make rate runs 36%→80%).
That is a CONDITIONAL defect, and a bias steered by a marginal-shaped target
cannot fix it. Any successor must be judged conditionally — correlation of
opening level with strength — not by distribution distance.

**Do not confuse the two reference distributions**, which this campaign did once:
`TARGET_OPEN` `[32 20 15 12 9 6 4 2]` is the DESIGN ASPIRATION the scoring
search was fitted against; the CFR+ equilibrium's actual marginal is
`[26 24 21 20 9 1 0 0]` (the average of `_OPEN_DIST` over its equal-mass
octiles). The second is what the bias steers toward and the right yardstick for
the bot; the first is a statement about the SCORING.

**HARNESS BUG FOUND WHILE SETTING THIS UP, and it invalidates earlier numbers.**
The bias arm was armed by a trailing `o` on the tier name — but `old_double` is
tested as `"o" in tier[len("expert"):]`, which `expertto` also satisfies. So the
bias arm silently ran the OLD Double as well: two changes wide, with the bias
credited for whatever the Double lost. **Every `expertto` figure recorded before
2026-08-16 is bias + old-Double pooled** (they were all non-results with CIs
several times their estimate, so nothing was concluded from them). The bias
suffix is now `b`; `o` keeps its original meaning. This is the exact failure the
adjacent `t`-stripping comment warns about, committed one suffix later.

The description below is the mechanism as built, kept for whoever revisits it.

The bot arm the exploitability finding asked for. **Off unless `DIS_OPEN_BIAS`
sets a weight**, so shipped behaviour is byte-identical (`open_bias_terms`
returns None at weight 0, asserted in the suite's own run).

* **`bot.open_bias_terms`** maps the seat's best-denomination `hand_strength`
  through octile cuts to the CFR+ equilibrium's opening level, and returns a
  per-option nudge `-w x (level - target)^2`. Quadratic on purpose: a linear
  penalty shifts every option equally and the argmax ignores it.
* **`wire.rs` reads `open_bias`** the same way it already reads `double_margin` —
  a per-option term the SERVER computes and the search adds, so no rule moves
  into Rust. Wrong length or absent, nothing is charged, so an older server gets
  the unbiased search.
* Cuts `7.82 8.92 9.82 10.62 11.43 12.32 13.43`, targets `2.25 2.71 3.26 3.63
  3.63 3.76 3.82 4.84` (the equilibrium's one inversion pooled — it was inside
  the per-seed sd).
* Arena arm is a trailing `o` on the tier name.

**MIRROR READS EXACTLY +0.0000 ± 0.0000** over 10 paired deals — the first thing
to run after touching the arena, and it passes.

**The mechanism fires, measured on 22 paired deals:**

| | mean open | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| `expertt` (no bias) | 3.82 | **14%** | 27% | 5% | 9% | 18% | 18% | 9% |
| `expertto` (bias) | 4.00 | **0%** | 18% | 23% | 18% | 27% | 9% | 5% |

Level-1 openings go 14% → 0% and the distribution concentrates on 3-5, which is
exactly what the bias was built to do. **18 of 22 auctions differed**, so the arm
has plenty of measurement power per deal.

**THE PAYOFF IS NOT MEASURED: +0.43 ± 6.60 over 22 paired deals.** Per-deal sigma
is ~15.8 even CRN-paired and dd-resolved, so ±1.5 needs ~400 deals. The arena
runs ~10 paired deals per 500s at k=8 with two shards (each shard spawns its own
`bidserve` per tier per seat, so four shards oversubscribe four cores and finish
nothing) — call it 20+ hours of arena for a shippable number. **Do not read the
+0.43 as a positive result; it is a plumbing check that happened to have a sign.**

**One bug worth keeping.** The tier suffixes are `t` for the talon model and `o`
for the bias, and `"expertto".endswith("t")` is False — so the unstripped check
silently dropped the talon from the bias arm and would have made the comparison
two changes wide, reading as the bias doing something it did not. The `o` is
stripped before the `t` is tested.

### FIXED: CFR+ AND LINEAR AVERAGING (2026-08-16)

The convergence problem below is solved, and solving it changed several answers.

Vanilla CFR averages every iteration equally, so the average strategy carries all
the early ones when it was still uniform. Two standard changes: **cumulative
regrets floored at 0 (regret matching+), and iteration `t` contributing to the
average with weight `t`.** Four lines, at four sites (`walk` and `dbl_node`, both
the regret and the strategy update).

**The convergence check is the test.** Same scoring, same deals, iterations only:

| iterations | 30k | 60k | 120k | 200k |
|---|---|---|---|---|
| vanilla | 0.63 | 0.54 | 0.67 | **0.88** |
| **CFR+** | **0.66** | **0.66** | **0.66** | — |

Flat across a 4x range where vanilla swung 0.34. Seed spread at 120k is **0.62
mean, sd 0.035** over four seeds, and the components that used to drift are now
steady across seeds: settled `6:` 46/44/44/44, doubling 17/16/17/16%, bids
3.71/3.66/3.59/3.72. **A difference under ~0.15 is still not a result** once the
±0.11 deal-sample bar is added, but that is a usable instrument where the old one
was not.

**TWO EARLIER ANSWERS WERE WRONG AND ARE CORRECTED HERE.**

*The doubling rate.* Vanilla measured 7% for this scoring; CFR+ measures **16-17%,
stable across seeds**. So the "11% candidate against 32% shipped" comparison is
unconverged and should not be used — the Double numbers all need re-measuring.

*The bucket-5 anomaly is GONE, and it was an artifact.* Vanilla put bucket 5 two
rungs below its neighbours in every seed, which is why the bot gate was blocked
as "unexplained". Under CFR+ the opening by strength bucket reads:

| bucket | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| CFR+ | 2.25 | 2.71 | 3.26 | 3.86 | 3.41 | **3.76** | 3.82 | 4.84 |
| vanilla | 1.39 | 1.62 | 3.64 | 4.04 | 4.72 | **2.76** | 4.26 | 4.87 |

Bucket 5 now sits ABOVE bucket 4, where it belongs. The residual wobble (3.86 at
bucket 3 against 3.41 at 4) is inside the per-seed sd of 0.14-0.30 — noise, not
the structural two-rung dip that vanilla produced consistently. **The lesson: a
result that reproduces across seeds is not thereby correct. Four seeds agreed on
the anomaly because they shared the same lagging estimator, not because the
anomaly was real.**

**And the diagnosis it unblocks is cleaner than before.** The equilibrium ramps
2.25 -> 4.84 across the strength range; Expert ramps 1.38 -> 4.48. The gap is
mostly at the WEAK end — Expert opens at the floor with hands the equilibrium
opens at 2.25 — rather than a uniform flattening. That is monotone, explained,
and safe to build a gate from.

### (SUPERSEDED by the CFR+ fix above) THE EQUILIBRIUM'S OPENING TABLE IS NOT SAFE TO COPY INTO THE BOT (2026-08-16)

The plan was to lift the equilibrium's per-bucket opening under the shipped
scoring + real-play leaf + Double, and gate Expert's opening with it. Two things
stopped it, and the second is unresolved.

**1. The solve is not converged at 200k.** Same scoring, same deals, iterations
only:

| iterations | 30k | 60k | 120k | 200k |
|---|---|---|---|---|
| loss | 0.63 | 0.54 | 0.67 | 0.88 |
| level-1 openings | 27% | 35% | 42% | 49% |

The settled half is stable (`6:` 46/44/45/43); the OPENING is what drifts,
monotonically, and is still moving where the runs stop. **So every ranking in the
sections above mixes 60k search numbers with 200k verification numbers and is
unsound** — that gap is 3x the ±0.11 deal-sample error bar. The much-quoted 0.54
and the 0.88 are the SAME scoring at different iteration counts, not two results.

**2. Bucket 5 opens LOWER than bucket 4, in every seed.** Mean opening by the
opener's strength bucket, four seeds:

| bucket | 0 | 1 | 2 | 3 | 4 | **5** | 6 | 7 |
|---|---|---|---|---|---|---|---|---|
| opens at | 1.39 | 1.62 | 3.64 | 4.04 | 4.72 | **2.76** | 4.26 | 4.87 |

Not a bucketing artifact — the buckets are cleanly monotone in what the hands can
actually take (mean points 1.79 / 2.72 / 3.36 / 3.92 / 4.40 / **4.85** / 5.22 /
5.92, P(take 5+) 3.8% → 88.2%). So a hand measurably stronger than bucket 4 opens
two rungs lower, reproducibly. It may be a genuine pooling/trap equilibrium of
the abstraction, which would be exactly the kind of thing that works against an
equilibrium opponent and fails against Expert or a human. **It is unexplained,
and an unexplained non-monotonicity is not something to compile into a shipped
bot.**

**What the finding still supports.** The exploitability finding stands (its
MAGNITUDE was re-measured at 5.87 under the shipped prices, 2026-08-19) — it is
a best-response computation, not a distribution score, so none of the above
touches it — and so does its diagnosis: Expert's opening moves 0.82 rungs across
a strength range over which its make rate runs 36% → 80%. Using the equilibrium
as a DIRECTION (a monotone strength→level mapping) is defensible; copying its
table is not. The arena is the judge either way.

**And the build cost is not small**: Expert's opening comes from the client
search, so gating it means a term in the shipped auction payload, a `bid.rs`
change, a wasm rebuild and regenerated fixtures. That is not work to start on an
unconverged, partly-unexplained policy source. **Fix the convergence first** —
the opening distribution needs to stop moving before anything is read off it.

### RE-SEARCHED WITH THE DOUBLE INVARIANT ENFORCED — the gain shrinks to real size

`double_violations()` is the shipped test moved upstream of the search: on the
common one-short failure, doubling wins `set_base + ramp` and risks `make`, so
`make(L) > set_base(L) + ramp` must hold from L=2. It is pure arithmetic on the
constants, so a violating scoring is rejected before any CFR time is spent — and
`Fs` is now SAMPLED inside the constraint rather than rejected after it, because
rejection killed 98% of draws (8 of 400 survived) and that is a lottery, not a
search.

**Best scoring that keeps the Double honest:**

```
make   L^2 + 8            9 12 17 24 33 44 57 72     +1 per overtrick
set    2L + 6 x jump      climbed 8 10 12 14 16 18 20 22   NO flat term
short  5 (unchanged)

loss 0.88   against shipped's 1.06 on the same tree
settled  1:6 2:3 3:2 4:14 5:32 6:43     max 43%
opening  1:49 2:15 3:7 4:27 5:2
bids 3.44 (18% one-bid)   made 66.5%   DBL 7% taken, 59% of those set
```

**The structural lesson: the set base must carry NO flat term.** A flat stake is
what made doubling free at low levels — at level 2 the old candidate paid the
defender 14 for a contract worth 8. Dropping it and steepening the level
coefficient to `2L` keeps the low rungs cheap to break (8, 10) while the top
still costs 22, which is what the invariant needs.

**And the honest size of the prize: 1.06 -> 0.88, not 1.06 -> 0.49.** The 0.49
arm broke the Double, and roughly half the apparent improvement was coming from
that. The settled maximum is 43%, still over the 40% cap, and openings pile 49%
on level 1.

**A THIRD SILENT BUG, same shape as the other two.** Splitting
`CLASSIC_SHORT_PENALTY` out of `SHORT_PENALTY` in the engine left the lab's
`short` knob patching skat's constant, so every sweep after the split silently
ran at the shipped 5 whatever it was told. Caught because two specs differing
only in `short` printed BYTE-IDENTICAL rows. The other two were `g.get("points",
[0,0])` against a key of `pts`, and a counter spliced into the wrong function.
**All three were a value that never arrived, and all three produced numbers too
tidy to question.** Identical output from different inputs is the cheapest
possible check and it is not run by default — run it whenever a knob is added or
a constant is split.

**RE-FITTED ON THE CORRECT TREE — and it beats everything measured either way.**
One constant moves from the earlier candidate, `Fs` 12 -> 10:

```
DECLARER scores, made      L^2 + L + 2   ->  4  8 14 22 32 44 58 74
                                             +1 per overtrick
DEFENDER scores, set       2L + 10 + 6j  ->  climbed 18 20 22 24 26 28 30 32
                                             opened  18 26 34 42 50 58 66 74
                                             +1 per point short
Double doubles both bases, as it already does.

loss     0.49   (best of the campaign, and on the tree the game actually has)
settled  1:5 2:5 3:6 4:15 5:32 6:37       max 37%, under the cap
opening  1:31 2:21 3:10 4:34 5:4
bids     3.22 (25% one-bid)
made     71.3%      DBL 11% taken, 59% of those set
```

Verified across four disjoint 500-deal real-play subsets: **0.48 / 0.48 / 0.63 /
0.60, mean 0.55 sd 0.068** — the usual small-sample bias against the 0.49 on the
full cache, and consistent.

Six live settled levels with the maximum at 37%, against shipped's two levels
carrying 93%. **The doubling rate is 11%, still short of the 20-30% band** — the
set-base sweep shows that band is reachable at `Fs = 4` but only by piling 61% of
contracts onto level 6, so the two goals trade directly and this arm chooses the
distribution.

**Two sweeps, and the first refuted its own hypothesis.** `short` was the obvious
lever for the doubling rate -- cheap sets, less to punish -- and it does the
opposite:

| short | 1 | 2 | 3 | 4 | 5 |
|---|---|---|---|---|---|
| doubles taken | 11% | 11% | 12% | 9% | **7%** |
| made | 73.6% | 75.8% | 76.8% | 77.5% | 78.7% |

Raising it LOWERS doubling and RAISES the make rate, both against prediction: a
harsher shortfall makes declarers bid conservatively, which produces easier
contracts and fewer sacrifices to punish.

The set base is the real lever, because it prices the sacrifice itself:

| `Fs` | 12 | 8 | 4 | 8 with `B=1` |
|---|---|---|---|---|
| doubles taken | 11% | 11% | **15%** | **16%** |
| made | 73.6% | 69.5% | 63.1% | 62.0% |
| loss (Double in tree) | 0.82 | **0.65** | 1.35 | 1.21 |

`Fs = 8` scores better with the Double in the tree (0.65) than the candidate does
(0.82) -- another sign the candidate was fitted to the wrong tree. Pushing lower
buys doubling and a lower make rate but piles 57-61% onto level 6.

### EVERYTHING HERE IS DOUBLE-DUMMY, AND THAT FLATTERS THE COARSENESS

`pts` is what a declarer can guarantee seeing all 40 cards. Real play is noisier,
and noise WIDENS the achieved-points distribution, which flattens P(make) per
rung — i.e. the real ladder is looser than these numbers make it look. Quantified
by convolving the measured distribution with noise of scale sigma:

| sigma | sd(pts) | per-rung cost in P(make) |
|---|---|---|
| 0 (double-dummy) | 1.92 | 17.6 pts |
| 1.0 | 2.18 | 16.0 pts |
| 2.0 | 2.77 | 13.1 pts |

So the effect is real but modest: sigma would have to approach the entire
hand-quality spread to change the picture. **Sigma is measurable** — compare
double-dummy `pts` against what the shipped PIMC search actually achieves on the
same deal and contract — and it has not been measured. Until it is, read every
"the ladder is too coarse" statement here as an upper bound on the coarseness.

**MEASURED 2026-08-19 — AND THE "NOT MEASURED" ABOVE WAS ALREADY STALE WHEN
WRITTEN.** Two things, and the first is a documentation fault. `cfrlab playnoise`
had measured this three sections up ("THE REAL LADDER IS 16% LOOSER"), reading
sd **1.94** and a mean deviation of **+0.95** for the declarer at an imposed
contract. This section asked for it as though nobody had. Both numbers stand;
what follows is an INDEPENDENT second instrument, `dissonance-core/bin/sigma`,
measuring a deliberately different quantity — symmetric points play with no
imposed contract, both seats on the shipped `pimc:8`, every deal played in all
five denominations and BOTH lead directions.

| | double-dummy | real play |
|---|---|---|
| seat 0 points, sd | 2.053 | 2.447 |
| **sigma** (real minus double-dummy) | — | **sd 1.586**, mean +0.013 ± 0.041 |
| landed exactly on the solver's value | — | 28.4% |
| per-rung cost in P(make), live range | 13.3 pts | 12.3 pts (**7.7% looser**) |

**Sigma replicates**: 1.590 on a 240-deal single-lead run and 1.586 on this
150-deal paired one. So does the looseness, 7.9% and 7.7%.

**THE CONVOLUTION OVERSTATES THE LOOSENING BY ABOUT 2.4x, which is the point of
having measured it.** Interpolating the table above to the measured sigma of
1.59 predicts a per-rung cost of ~14.3 against 17.6 at sigma 0 — i.e. ~19%
looser. Measured: **7.7%.** The model assumed the noise is additive, symmetric
and independent of the position; it is none of those (`playnoise` already
measured the two seats' outcomes at −0.658 correlated). So "read every 'too
coarse' statement as an upper bound" was the right instruction and the bound is
loose by a factor of roughly two.

**AND THE OPENING LEAD IS WORTH A THIRD LESS THAN THE NUMBER THAT JUSTIFIED IT.**
Solving and playing the same shuffle with each seat leading in turn, 750 pairs:

| | paired swing |
|---|---|
| double-dummy | **+0.992 ± 0.031** pts |
| real play | **+0.673 ± 0.072** pts |

The double-dummy figure reproduces this file's own **+0.93** to inside its error
bar, which is what validates the harness — and settles that the +0.93 is the
PAIRED SWING rather than a one-sided edge over par, a factor of two this file
never stated. Under real play it falls to +0.673, a drop of 0.319 ± 0.079 (4
SE). **"The opening lead was measured at +0.93 pts, the strongest single lever
on contract height" is a double-dummy number, and about a third of it is play
the shipped tier does not find.** That bears on `declarer leads` and on the
Null-defending asymmetry, both of which are argued from it.

**What shipping a rate change would entail** — **and it HAS since shipped: 3 → 6
in `a317bb1`, the same commit that re-priced make and set. Read this list as the
checklist that was followed, not as pending work** (it is a scoring change, so it
is not a one-constant edit): `JUMP_SET_BONUS` in `engine.py`, the mirrored constant
and the committed parity fixtures in `rust-cores/dissonance-core`, the rules copy
in `rules.jsx`, Expert's own calibration (it was fitted against 3j), and a re-run
of the `DOUBLE_MARGIN` sweep — the margin of 20 was fitted against a 72.9% make
rate and would be sitting on a different distribution at 79.2%.

**WHAT THIS IS NOT.** The exploitability figure (9.06 then, **5.87 under the
shipped prices**) is measured inside the abstraction, **not a
head-to-head margin against Expert** — a best responder is a far harsher opponent
than Expert is, and the abstraction drops `DENOM_RULE`, which makes the responder
freer than a real exploiter could be. The equilibrium's policy table is a
DIRECTION, not a table to ship. The shipping path is: implement the direction
(open near 4 rather than ramping; do not concede 4; do not contest 6), then
measure it the way everything else here is measured — CRN-paired auction arena,
equal time, mirror reading exactly 0.5000.

**Cost shapes, for whoever runs it next.** The equilibrium arm is ~0.5s a deal
(three double-dummy solves) and the CFR itself is free — 2000 deals and 200k
external-sampling iterations inside one block. The control arm is **~25s a deal**
because it runs the real k=8 search at every auction node, which is the point: a
control on a cheaper search would be measuring the search rather than the bidder.
It is sharded four ways over four cores to ~5.4s a deal, each shard on its own
checkpoint, and the reporter reads every shard — **a per-shard summary is a
quarter of the sample and reads exactly like the whole thing.**

**The bug this nearly shipped a conclusion on:** the leaf originally priced every
contract with `jump=level`. Classic's set base was `(N + 10 + 3j) × D` when this
was written and is `(2N + 2 + 6j) × D` today, so that
charges the maximum jump penalty on a climb that earned none — it taxes exactly
the deep auctions the harness exists to judge, in the direction that manufactures
the answer "the equilibrium bids lower than Expert". Fixed to `level - prev`
(and `prev = 0` gives the v2 opening rule for free); the settled mean moved
4.47 → 4.67 and the make rate 77.1% → 72.0%.

### THE EXPLOITABILITY INSTRUMENT WAS MEASURING THE CORPUS, AND IT WAS MEASURING THE WRONG TIER (2026-08-19)

Two independent faults in the same measurement, found by decomposing a number
this campaign had already acted on twice. **Both are fixed; the headline
survives, its provenance does not, and two nulls it produced are now suspect.**

**FAULT 1 — 74% of the exploitability sat on infosets with two observations or
fewer, and 54% on ones Expert had never visited at all.** `cfrlab attrib`
decomposes the best responder's winnings by the one-step deviation: at every
node the policy acts on, what would it have saved by playing its best single
action there, everything downstream held at the responder's own values.
Reach-weighted, one choice per infoset (a per-deal minimum would be a cheater's
alternative), reported beside the raw observation count. On the 414-round
self-play corpus:

| observations behind the infoset | share of the loss |
|---|---|
| **unseen (backed off)** | **53.6%** |
| 1-2 | 20.2% |
| 3-5 | 11.5% |
| 6-10 | 9.7% |
| 11+ | 5.1% |

Half of it landed at standing level 7, where the fitted "policy" read a crisp
`pass:50% hold:50%` off one observation or zero. **A best responder steers
TOWARDS the holes by construction**, so the fit's own coverage was most of the
number.

* **THIS RETRACTS A CLAIM THIS FILE MADE TWICE — "at 413 rounds nothing is
  unseen".** The coverage line was printed all along and said only 16.1% of the
  responder's reach lands on an EXACTLY fitted infoset; it was read as though
  the 22.1% marked UNSEEN was the whole problem. A distribution pooled over
  `prev` or `holds` is just as much a fabrication as a missing one — it is the
  harness's average, not Expert's behaviour.
* **And it explains both of the nulls recorded above.** The opening bias and the
  exact leaf could not have moved this number, because it was dominated by nodes
  Expert never plays. No change to how Expert plays reaches them.

**THE FIX IS OFF-POLICY COVERAGE (`CFR_PROBES`).** Per deal, N states drawn
uniformly from the abstraction's own reachable set; a REAL auction is driven
into each with real bids — so `used`, `last` and `jump` come out right by
construction rather than from a second copy of the auction's bookkeeping — and
Expert is asked what it does there. Uniform rather than reach-weighted
deliberately: a corpus weighted by the current fit would be measuring the fit,
which is the complaint.
* **Both actor parities are built.** The shortest path's LENGTH fixes whose turn
  it is, so the other seat's version of the same state needs a path one bid
  longer (an earlier, lower opening). A probe that only built the short path
  would leave half the state space unvisited — the very defect it exists to fix,
  one level down. Measured: usable probes per 16 sampled went 3.7 -> 6.7.
* **It is very nearly FREE**, which is the only reason it is affordable:
  `bid::Solved` is cached on the HAND and a probe moves the standing bid rather
  than the cards, so every probe after the first on a seat is arithmetic over
  worlds already solved. Measured **16.4 s/deal at 0 probes, 13.1 at 96**
  (~70 usable) — inside the noise, for a corpus ~20x larger.
* Result at 420 rounds: **100.0% exact lookups along the responder's reach**,
  no backoff and nothing unseen; infosets 233 -> 1448; **97.7% of the loss now
  sits on infosets with 11+ observations.** `CFR_PROBES=0` reproduces the old
  corpus exactly, so every checkpoint written before this stays readable.

**FAULT 2 — the harness has been measuring HARD's auction while its docstring
said Expert.** `engine.auction_search_payload` ships the auction's shape and its
prices; **`opp_model` is added by `main.py`, and only for the expert tier.**
cfrlab built its payload straight from the engine, so the field was absent, and
`wire::auc_rules_from_json` maps absent to `OppModel::Minimax`. Expert's ONLY
difference from Hard is that one field. **So 9.06, 5.87 and the first 5.45 all
describe Hard.** `CFR_OPP_TEMP` now defaults to `main.EXPERT_OPP_TEMP`, is
STAMPED on every recorded row, and every reader prints the corpus's tier and
shouts if a corpus pools two.

**Third instrument bug of this exact shape** — after the `expertto` suffix
collision (an arm that silently ran two changes wide) and `dblsweep`'s
live-margin delta (a column read as absolute). The pattern to watch for: **a
harness that rebuilds a payload the server assembles in more than one place will
silently ship the default for whatever it forgot.**

**THE HONEST NUMBERS, 420 rounds each, same deals, same instrument, 100%
coverage:**

| tier | BR seat 0 | BR seat 1 | exploitability | split-halves |
|---|---|---|---|---|
| CFR+ equilibrium (the floor) | +1.75 | +1.19 | **1.47** | — |
| **Hard** (`opp_temp` 0, plain minimax) | +6.19 | +4.70 | **5.45** | 5.60 / 5.50 |
| **Expert** (`opp_temp` 5, shipped) | +6.20 | +5.21 | **5.70** | 5.80 / 5.73 |

**Expert is marginally MORE exploitable than Hard, and that is not a
contradiction of its measured +0.957 ± 0.454 head-to-head win over the same
tree.** Exploitability and head-to-head strength are different quantities: a
policy that exploits a particular opponent better can be easier for a best
responder to punish. Worth stating because the two numbers will otherwise read
as a conflict. The softening does move behaviour in the predicted direction —
Expert concedes level 4 at 31-43% against Hard's 30-62% — but it also opens
lower across every bucket (1.09 vs 1.33 at the floor), and the net is a wash.

**THE ONE HUGE DIVERGENCE SURVIVES BOTH TIERS AND IS NOW WELL-OBSERVED: the
equilibrium essentially NEVER concedes level 4 (0-5% from every bucket) and both
tiers concede it 31-67%.** The attribution says the same thing over and over,
now at 97.8% on infosets with 11+ observations: **wants `bid 5` or `bid 6`, does
`pass:59% hold:30%`**, at standing 3-5, from middle and strong buckets alike.
That is exactly the failure the crate documents for a tree whose modelled
opponent is handed our hand — contesting looks worthless, so the search shades
everything down — and softening it at temp 5 is measurably not enough.

### THE EXACT AUCTION LEAF — BUILT, EXACT, CHEAP, AND IT DOES NOT MOVE EXPLOITABILITY (2026-08-19)

**Verdict first: the mechanism is real and correct, the gate says do not spend
arena time on it, and it ships OFF (`DIS_EXACT_LEAF`).** This is the fourth
entry in this file to record a measured defect whose correction did not measure
as a gain — see the belief thread's "A MEASURED BIAS DID NOT IMPLY A MEASURED
GAIN", which this now joins by a third independent instrument.

**THE BASELINE HAD TO BE RE-MEASURED FIRST, AND IT MOVED A LONG WAY.** The 9.06
on record was taken under the PRE-2026-08-16 price list, so it is not a valid
"before" for anything measured today. Re-run on 414 rounds under the shipped
scoring, against the same 2000-deal real-play cache:

| policy | BR as seat 0 | BR as seat 1 | exploitability |
|---|---|---|---|
| CFR+ equilibrium | +1.75 | +1.19 | **1.47** |
| Expert (414 rounds, 1247 decisions) | +6.20 | +5.54 | **5.87** |

**Read the two rows as a difference, always** — the floor is 1.47 here, not the
0.15 on record, because that figure came off a different deal cache. **The
re-pricing itself took Expert from 9.06 to 5.87**, which is the single largest
movement anything in this campaign has produced, and nobody had measured it.
Converged: 200 rounds read 6.01, 414 reads 5.87, and the 207-round split-halves
read 6.00 and 6.05. What does NOT converge is coverage — 22.1% of the best
responder's reach lands on infosets Expert never visits, at 200 rounds and at
414 alike, so that is structural rather than a sample size.

**THE DEFECT THE LEAF FIXES IS REAL AND WAS ALREADY MEASURED.** The search
prices a candidate as `max(contract(P), null if the duck is GUARANTEED)` — the
better of two SEPARATELY guaranteed plans. A real defence has to stop both at
once and often cannot, so the shipped leaf under-prices declaring: over 900
(deal, contract) pairs it agrees with an exact `solve_contract` 93.3% of the
time and **every one of the gaps is positive**.

**AND IT IS AFFORDABLE, WHICH THIS FILE HAD SAID IT WAS NOT.** The standing note
was that closing it needs "a `solve_contract` per (denomination, level) per
world" against a tree reaching fifty settlements. It does not, **because the
outcome space is totally ordered**: a round ends either with the declarer taking
no scoring trick — worth the consolation, one flat value — or with a points
total, worth a strictly increasing function of it (`Contract::payoff` is
monotone on both branches). In a perfect-information zero-sum game with totally
ordered outcomes, the value under any monotone payoff is that payoff applied to
the best outcome the declarer can FORCE. So **two scalars price every contract
on a deal, at every level and every jump**:

* `P` — the points solve: the largest `x` with "I can force `pts >= x`";
* `Q` — `dd::threat_value`: the largest `x` with "I can force `pts >= x` OR no
  scoring trick", i.e. the same question with the duck moved to the TOP of the
  order;

folded by `Option_::payoff_exact` as `max(contract(P), min(null, contract(Q)))`.
The two branches are the two forcible upward-closed sets, and the `min` is the
defence picking whichever half of the threat hurts us more.

* **`Q` SUBSUMES `null_no_even_makeable`** — a guaranteed duck is exactly `Q` at
  the sentinel — so this is one solve swapped for another, not a second bolted on.
* **The identity is SWEPT, not argued.**
  `the_threat_value_prices_every_contract_exactly` checks `payoff_exact(P, Q)`
  against `solve_contract` over whole deals x every denomination x both
  declarers x five levels x two jump sizes, and asserts the gap against the
  shipped leaf is never negative. 60 of 360 contracts (16.7%) are mis-priced by
  the shipped leaf, worst **+60**. **Three deals is the FLOOR, not a round
  number**: at two the sweep reaches no mis-priced contract at all and the
  non-vacuity assert fails, which is how that floor was found.
* **Cost 2.1x**, measured on `cfrlab`'s control arm: 17.5 -> 51.8 s/deal
  full-window, 38.1 once `threat_value` runs MTD(f) **seeded from the points
  solve** — free evidence, since `Q >= P` always and the two are equal on ~85%
  of contracts, so the seed is usually the answer.

**THE GATE, ON THE SAME 200 SEEDS, SAME CACHE, SAME INSTRUMENT:**

| arm | exploitability | split-halves | settled mean | made | 
|---|---|---|---|---|
| shipped leaf | **6.01** | 6.58 / 5.94 | 4.52 | 72.5% |
| **exact leaf** | **6.21** | 6.16 / 6.00 | 4.51 | 67.5% |

**No movement, and certainly nothing heading for the 1.47 floor.** The required
effect was several points; the observed one is +0.20 in the wrong direction,
well inside a split-half spread of 5.94-6.58. Per the gate this was built
under, **no arena time is warranted.**

**...BUT THIS NULL WAS TAKEN ON THE BROKEN INSTRUMENT AND IS PENDING A RE-RUN.**
Both arms above were fitted on the SELF-PLAY-ONLY corpus, which the section
above shows was 54% fabricated infosets — and a leaf change moves what Expert
does, which by construction cannot move loss attributed to nodes Expert never
visits. So the null is un-diagnostic rather than wrong: it may simply have been
measured on the part of the number that no bot change can touch. **RE-RUN AND IT HOLDS** -- paired at 247
seeds on the probed corpus, 5.35 myopic against 5.58 exact, the same +0.2 in the
same direction. See the section below; "the exact leaf does nothing" is settled.

**AND THE MEASUREMENT IS NOT VACUOUS, which is the first thing to check on a
null.** With the exact leaf on, **70% of auctions bid a different sequence, 52%
settle at a different level and 28% end with a different declarer**. The bidder
really moved; its exploitability did not. The make rate falling 72.5% -> 67.5%
is the predicted direction and not a bug — every correction is positive, so
declaring is priced up and the bot declares more.

**WHY IT PLAUSIBLY CANNOT HELP, and this is the part to carry.** The
exploitability defect this campaign measured is that Expert's opening **barely
varies with its hand** (1.38 -> 4.48 across buckets whose make rate runs 36% ->
80%, against an equilibrium ramping 2.25 -> 4.84). A better leaf makes every
candidate's price more accurate, but it does not make the price more
STRENGTH-CONDITIONED — it shifts all of them in the same direction. That is the
same reason the opening bias failed from the other end: a marginal-shaped
treatment cannot fix a conditional defect. **Two mechanisms, opposite ends of the
pipeline, same diagnosis.**

**WHAT IS LEFT STANDING, and it is not nothing.** `threat_value` is committed,
gated and correct, and it is one env var away from being the leaf. So any FUTURE
experiment whose result could turn on leaf accuracy can be run with it on
honestly, and the "the leaf is a proxy" caveat that qualifies half the
measurements in this file can now be removed from any of them by re-running the
arm. It is deliberately not shipped: the exploitability gate says no gain, and
2.1x would put Expert's first decision of a hand at ~7s of a 12s watchdog.

### AND THE NULL REPLICATES ON THE FIXED INSTRUMENT (2026-08-19)

Re-run with `CFR_PROBES=96`, Hard tier both arms, **paired on the same 247
seeds** and read at 100% exact coverage:

| leaf | exploitability |
|---|---|
| points proxy (shipped) | **5.35** |
| exact (`DIS_EXACT_LEAF`) | **5.58** |

Same direction and nearly the same size as the broken-instrument reading
(+0.20). **So the exact leaf's null is real and not an artefact of the corpus**
— the mechanism is exact, cheap and correct, and it does not reduce
exploitability. That conclusion is now settled on an instrument that deserves
the word.

### THE FOREVER-BAN IS NOT WHAT MAKES THE TREE CONCEDE — the last confound, closed (2026-08-19)

The one divergence surviving every arm is that the equilibrium essentially never
concedes level 4 while both tiers concede it 31-67%. **Before spending anything
on that, the obvious alternative reading had to be killed:** the abstraction has
no denominations, so it lets a seat raise in its best suit every time, where
classic bans a suit that seat has already named. "The equilibrium raises and
Expert concedes" could just be a freedom the real bot does not have — this
file's own standing caveat about the abstraction.

`cfrlab banned` measures it at exactly the nodes the attribution blames, over
9,032 probed decisions. **The pass rate split on whether the seat's best
denomination is still legal:**

| standing | best free: n | passes | best banned: n | passes |
|---|---|---|---|---|
| 3 | 453 | 29% | 213 | 30% |
| **4** | **654** | **44%** | **322** | **44%** |
| 5 | 823 | 65% | 415 | 74% |
| 6 | 972 | 91% | 536 | 91% |

**Identical.** At the level that carries the argument it is 44% against 44%.
The ban binds less than one would guess anyway (the best denomination is still
free on 64-81% of decisions, costing 0.3-0.6 of `hand_strength` when it is not),
and where it does bind it does not change what the tree does. **So the
concession is genuine timidity, not a constrained option set**, and the
abstraction's one documented liberty is not the explanation.

**WHERE THAT LEAVES THE CAMPAIGN.** The defect is now real, well-observed
(97.8% of the loss on infosets with 11+ observations), not a coverage artefact,
not an abstraction artefact, and not fixed by either of the two mechanisms
tried:

| treatment | result |
|---|---|
| opening bias (marginal-shaped) | worse on every weight; argmax cannot express a mixture |
| exact leaf (accuracy) | +0.23, replicated on both instruments |
| opponent softening at temp 5 (Expert) | +0.25 against Hard's minimax |

**THE STRUCTURAL ASYMMETRY THAT IS LEFT, and it is the hypothesis worth testing
next.** In the tree, PASSING is a leaf — priced once, myopically, as the
standing contract from the opponent's side — while RAISING continues into a
subtree whose modelled opponent is handed our exact hand and always finds the
punishing reply. **The pessimism is applied only to the branch that continues.**
That is not a leaf-accuracy problem (measured: no) and not a marginal-shape
problem (measured: no); it is an asymmetry between how the two kinds of branch
are valued, and it predicts exactly the observed sign — concede too often, at
every strength.

The temp knob is the wrong instrument for it: softening reduces the pessimism on
the continuation but ALSO makes the bot open lower across every bucket, and the
two cancelled. A test that isolates the asymmetry has to leave the opening
alone.

### THE TREE'S PESSIMISM ABOUT CONTINUING IS LOAD-BEARING, NOT A DEFECT (2026-08-19)

**The fourth treatment, the most carefully aimed one, and the most informative
failure. `xfit` ships at 0.**

**THE MECHANISM IS REAL AND IS IN THE TREE.** `min` and `max` over noisy
estimates are biased — the winner is partly whichever estimate's noise favoured
it — so a min reads LOW and a max reads HIGH. The crate already recorded that
"the optimiser's curse compounds with depth"; what it had not recorded is the
consequence. **The bias is DEPTH-DEPENDENT, and the auction's two branch kinds
have different depths**: PASSING settles immediately, RAISING buys one more
opponent `min` before anything settles. So every raise is shaded down against
every pass, at every strength — which is exactly the shape of the measured
divergence.

Demonstrated by simulation rather than asserted (the curse is a POPULATION bias:
over any fixed world set the hard min is simply correct, and it is only wrong
relative to the distribution those worlds are sampled from). Two options of
equal true value differing only by per-world noise, 4000 samples at k=8:
**min node hard −0.367 against cross-fit −0.018; max node +0.355 against +0.008.**

**THE CORRECTION WORKS, IN THE DIRECTION PREDICTED, AND MAKES THE BOT WORSE.**
Leave-one-out cross-fitting — choose on the other worlds, score on the held-out
one — costs no solves. Measured on the honest instrument, Hard tier, paired:

| `xfit` | settled mean | made | probe-pass | **exploitability** |
|---|---|---|---|---|
| 0 (shipped) | 4.48 | **68.5%** | 81.7% | **5.45** |
| 0.4 | — | — | — | **5.69** |
| 1.0 | 4.92 | **49.2%** | 77.0% | **6.11** |

It concedes less and bids higher, exactly as designed — and its contracts stop
coming home. **Monotone in the dose**, which is far stronger evidence than any
single arm: there is no weight at which this helps, and the curve says so
without anyone having to guess a middle value.

* **Why full correction cannot be the answer, and no better scheme fixes it:
  REMOVING A SELECTION BIAS ENTIRELY COSTS THE SELECTION.** When sampling noise
  exceeds the gap between two actions, a cross-fitted choice cannot tell them
  apart and returns roughly their MEAN where the truth is their MIN.
  Leave-one-out is already the SHARPEST cross-fit available (it selects on k−1
  worlds); a coarser fold corrects *harder*, not softer. So shrinkage was the
  only axis left, and the dose curve closed it.
* `xfit = 0` is the tree that has always run, bit for bit — the shrink line is
  never reached — so the A/B is unconfounded. A unit test pins that the weight
  is a WEIGHT (half of it is half the correction, zero is none), because this
  campaign has already shipped a "weight" that was really a flag.

**WHAT THIS ACTUALLY TELLS US, and it is a retraction of my own reading.** The
tree's pessimism about continuing is not a bug to be removed: correcting it
makes the bot overbid and collapses the make rate. Combined with three other
nulls, the honest conclusion is that **the divergence from the equilibrium is
probably not Expert's defect at all — it is the equilibrium's freedom.**

**AND `cfrlab banned` TESTED THE WRONG SIDE OF THAT.** It asked whether the
denomination forever-ban changes what EXPERT does (it does not: 44% against
44%). The question that decides the headline is the other one — **whether the
ban would change what the EQUILIBRIUM does** — and the abstraction cannot
answer it, because it has no denominations at all and so never pays the ban's
cost. That cost is real and measured: 0.3–0.6 of `hand_strength` on the 19–36%
of decisions where it binds. A bidder that must climb using progressively worse
suits *should* concede more than one that may re-bid its best every time.

**THE DECISIVE TEST, and it is bounded work in the lab alone.** Put the ban into
the abstraction: carry a per-seat BURN COUNT in the state (0..5 each, so ~36x
the states — thousands, which the exact DP handles), and index the leaf by that
seat's (c+1)-th best denomination. **The machinery already exists** —
`cfrlab dcache` builds exactly that cache, `pts`/`duck` for all five
denominations per seat ordered by the seat's own `hand_strength`, and it was
built for the suit-priced ladder study. If the equilibrium's concession rate at
level 4 climbs toward Expert's once it has to pay for its suits, the entire
"Expert concedes too much" finding dissolves and four nulls are explained at
once. **Nothing else should be spent on the auction bot until that is run.**

### THE DEFECT, FOUND AT LAST: THE TREE DOES NOT CONDITION ITS CONCESSION ON THE JUMP (2026-08-19)

**And the first thing this section has to do is retract a reading of mine that
four treatments were built on.**

**THE MISREADING.** `br`'s table reports the concession rate at ONE infoset per
level — standing `L`, reached from `L-1`, no holds. Read there, the equilibrium
concedes level 4 on 0-5% of decisions and both shipped tiers on 31-67%. I
generalised that to "the equilibrium essentially never concedes level 4". **A
reach-weighted playout of the same equilibrium concedes standing-4 on 69% of
decisions.** The cell was real; it was not representative of the level, and the
generalisation was mine, not the table's.

**WHAT SURVIVES IS SHARPER AND IS THE ACTUAL DEFECT.** The equilibrium's
concession is strongly conditioned on HOW THE STANDING BID GOT THERE — which is
exactly what the jump bonus prices, since a contract climbed one rung carries
`3 x 1` on a set and the same level OPENED carries `3 x 4`. `cfrlab jumpcond`,
both sides on the same 2000-deal cache:

| standing | EQUILIBRIUM | SHIPPED TREE |
|---|---|---|
| 3 | climb **7%** -> leap **16%** (**+9**) | 38% -> 39% (**+1**) |
| 4 | climb **2%** -> leap **28%** (**+26**) | 52% -> 53% (**+1**) |
| 5 | climb **13%** -> leap **71%** (**+58**) | 72% -> 75% (**+4**) |
| 6 | climb 83% -> leap 92% (+9) | 93% -> 94% (+1) |

**The equilibrium rotates on the jump axis; the tree is flat.** And the
attribution agrees about where that costs: **44.4% of the one-step loss sits at
jump 1**, at 1.78 loss per unit of reach against 0.94-1.06 everywhere else. The
money is in cheaply-climbed contracts the tree hands over.

**IT IS A CALIBRATION, NOT A BUG — checked rather than assumed.** The tree does
read the field: holding the deal, the seat, the hand, the standing level and the
option list fixed and editing ONLY `search.state.jump`, the option sums move by
a median of 54 and the decision flips on **2 of 40** deals, in the right
direction (a leap is conceded). So `step`'s `n.jump = level - s.level` and
`Search::with_jump` are both correct and the term reaches the argmax; it is
simply worth about a fifth of what the equilibrium acts as though it is worth.

**AND THIS EXPLAINS ALL FOUR FAILED TREATMENTS AT ONCE.** The opening bias, the
exact leaf, opponent softening and cross-fitting are every one of them a
UNIFORM SHIFT — they move what the tree thinks of continuing, equally at every
jump. The defect is a ROTATION about the jump axis: concede LESS on a cheap
climb and MORE on a leap. A shift cannot produce a rotation at any dose, which
is why cross-fitting moved the concession rate 81.7% -> 77.0% *uniformly* and
made the bot monotonically worse — it removed concessions where conceding was
right along with where it was wrong.

**THE FOREVER-BAN IS NOT THE EXPLANATION EITHER, and that is now measured from
the side that matters.** `cfrlab burn` models classic's per-player denomination
ban inside the abstraction — a burn count per seat in the state and in the
infoset, the contract indexed by it against the all-denomination cache, and a
seat that has named all five reduced to passing. Solved twice on the same 600
deals, same iterations, same RNG stream:

| | ladder (no ban) | + forever-ban |
|---|---|---|
| bids / auction | 1.80 | 1.68 |
| settled mean | 4.37 | 4.36 |
| contracts made | 74.3% | 72.8% |
| concedes standing-4 | **69%** | **72%** |
| concedes standing-3 | 17% | 39% |

So paying for its suits makes the equilibrium concede *slightly more*, and
nothing like enough to close a gap that was never as wide as I read it. The
earlier `cfrlab banned` result (the ban does not change what EXPERT does, 44%
against 44%) now has its counterpart: it does not much change what the
EQUILIBRIUM does either. **The abstraction's one liberty is priced and it is
small.** Worth having as a permanent arm regardless, since every future
comparison against this equilibrium inherits the question.

### FIVE TREATMENTS, FIVE FAILURES: THE SHIPPED TREE IS A LOCAL OPTIMUM ON THIS AXIS (2026-08-19)

**The conclusion of the day, and it is a stopping rule.** Every perturbation of
the auction search measured against the honest instrument makes it MORE
exploitable, in both directions on aggression and on four different mechanisms:

| treatment | what it changes | exploitability |
|---|---|---|
| **shipped** (Hard tree) | — | **5.45** |
| opening bias | the opening's marginal shape | worse at every weight |
| exact leaf | leaf ACCURACY (`payoff_exact`) | 5.58 (paired, 247) |
| opponent softening (`temp 5`) | the opponent's aggregation | 5.70 |
| jump weight 3 | what the jump term is worth | 5.78 |
| cross-fit 0.4 / 1.0 | the selection bias, both node kinds | 5.69 / **6.11** |
| *(the floor this abstraction reaches)* | | *1.47* |

**AND THE INSTRUMENT IS NOT THE EXPLANATION — checked, because after five
failures it had to be.** The obvious worry is that a best responder punishes
PREDICTABILITY, and inside an 8-bucket abstraction the only thing making a
search bot look "mixed" at an infoset is variation between deals sharing a
bucket — so anything that sharpens the bot's conditioning on the STATE would
read as more exploitable whether or not it played better. Measured, the mean
policy entropy per arm against its exploitability: **corr +0.62 over five arms,
which is the WRONG SIGN for that story** (more mixing reading as more
exploitable), and the decisive case is `jump weight 3` — the **lowest** entropy
of any arm (0.408 against the shipped 0.436) and still worse at 5.78. Predictability
is not what is being measured.

**WHY THE JUMP WEIGHT COULD NOT ROTATE EITHER, which is the last mechanism to
fall and the most instructive.** The diagnosis was right and well-attributed:
the equilibrium's concession rotates hard on the standing bid's jump and the
tree's is flat (44.4% of the tree's attributed loss sits at jump 1). But
`jump_weight` is **SYMMETRIC** — it makes conceding THEIR leap more attractive
and OUR OWN leaps less attractive, in the same breath. Measured at 3x, the slope
barely moved (level 3 +1 → +4, level 4 +1 → **−2**, level 5 +4 → +2) while the
settled mean fell 4.48 → 4.15 and the make rate rose 68.3% → 73.1%. **It shifted
again.** Rotating would need the weight applied only where the tree prices the
OPPONENT's standing contract and not its own prospective bids — which is no
longer a calibration of a scoring term but a thumb on the scale, and on this
evidence would very likely shift something else instead.

**WHAT THIS IS AND IS NOT.** It is not "the tree is optimal" — it sits 3.98
points above this abstraction's own floor. It is that **the residual is not
reachable by re-weighting the existing search**, which is what all five
treatments are. Every one of them changes a COEFFICIENT inside a tree that
searches from one seat's information set with the modelled opponent handed our
exact hand. That is the same verdict `CAMPAIGN.md` reached for card play from
the other end — "PIMC's residual error is strategy fusion, which no better world
distribution can fix" — and it now has an auction-side twin.

**SO THE ONLY LIVE DIRECTION IS THE ONE ALREADY IN "Not built yet": modelling
the opponent's UNCERTAINTY** — a search whose MIN nodes choose against worlds
drawn from the OPPONENT's information set rather than from ours. It is a much
bigger program (nested sampling, its own solve budget) and it is the one thing
none of these five touches. **Do not spend on another coefficient.**

**THE METHOD LESSON, which is the transferable half.** The campaign spent four
treatments on a defect I had generalised out of a single unrepresentative table
cell, and the fifth on the correctly-diagnosed version of it. What finally
settled the question was not a better treatment but a DOSE CURVE (cross-fitting,
monotone across three weights) and a NEGATIVE CONTROL (policy entropy against
exploitability). **When treatments keep failing, stop proposing treatments:
sweep a dose, and test the instrument.**

### THE OPPONENT'S OWN UNCERTAINTY — BUILT, MEASURED, AND IT IS THE SIXTH NULL (2026-08-20)

**The direction this file named as "the only live one", built properly rather
than as another surrogate — and it does not pay. `DIS_BELIEF_W` ships at 0.**

**WHAT IT IS.** Every other opponent model here answers "how sharply does the
opponent punish the hand we actually hold" — `Minimax` perfectly, `Soft` with a
temperature, `Myopic` with a price list. All three share one flaw: the sample
they choose against contains OUR REAL CARDS in every world, so the modelled
opponent is clairvoyant however the aggregation is softened. This replaces the
aggregation with a second SEARCH. Per sampled world, the opponent runs the same
tree over deals drawn from THEIR information set in that world — they know the
hand that world dealt them, ours is resampled — so their reply varies with their
own holding and is blind to ours. **That is qualitatively beyond a temperature**,
which can only give one mixed reply shared across every world.

**The construction is EXACT, not an approximation, and only because the auction
runs before a card is played.** `View::belief_of` is this view with the seats
swapped: they hold the world's hand, we join the pool they resample.
`Knowledge` is inference from played cards, so before trick 1 there is none to
carry across — the debug assert says so rather than the docstring alone.
Nesting is ONE level: `belief_into` never fills the inner entries' own belief,
so the modelled opponent models US as clairvoyant. The regress is infinite and
that is the honest place to cut it.

**MEASURED, paired on 200 seeds, Hard tier, 99.9% exact coverage:**

| | settled mean | made | probe-pass | exploitability |
|---|---|---|---|---|
| baseline | 4.50 | **69.5%** | 81.5% | **5.25** |
| belief (m=4) | 4.80 | **49.0%** | 75.4% | **5.43** |

**AND THE SIGN FLIPPED ON THE WAY, which is the part worth keeping.** At n=131
the same paired comparison read belief BETTER by 0.18 and I reported it as the
first improvement in six treatments — correctly caveated, and correctly not
believed. At n=200 it reads belief WORSE by 0.17. Splitting the same 200 seeds
into four disjoint quarters and recomputing the paired difference on each:
**+0.58, +0.90, +1.13, +0.76** — every quarter agrees that belief is worse, and
the favourable n=131 reading is reproduced by none of them. **This file has now
recorded the "an interval spanning zero is not a direction" lesson four times;
this is the first where a DISJOINT-SUBSET check settled it in minutes rather
than another hour of arena.**

* **The statistic is strongly n-dependent and differences are NOT comparable
  across n**: the quarters average +0.84 where the full sample reads +0.17. Same
  shape as the loss statistic's documented sample bias (0.54 on 2000 deals, 0.69
  on 500). Compare arms only at equal n, paired on the same deals — and when a
  reading matters, split it.
* **The behavioural cost is unambiguous even where the exploitability is not.**
  Contracts made fall **69.5% → 49.0%**. The bot concedes less (probe-pass 81.5%
  → 75.4%, and standing-3 concessions 38% → 19%) and bids higher (settled mean
  4.50 → 4.80) — and makes far fewer of them. No exploitability wobble of ±0.2
  buys that back.
* **And it STILL does not rotate.** The jump slope stays flat (level 4: +2 → −0;
  level 5: +4 → +2) — a sixth uniform shift, from the one mechanism that was
  supposed to be structurally different.

**SO THE STOPPING RULE STANDS AND IS NOW STRONGER.** Six treatments — the
opening bias, the exact leaf, opponent softening, cross-fitting, the jump
weight, and now the opponent's own uncertainty — every one null or worse, and
five of the six with the same signature: concede less, bid higher, make fewer.
**The auction search's pessimism about continuing is load-bearing, and the
5.45-against-1.47 residual is not reachable by changing what the tree believes.**

**WHAT IS LEFT, honestly.** The remaining candidates are all bigger than a
search change: a better ABSTRACTION for the exploitability instrument itself
(denominations are still collapsed to a burn count), a leaf calibrated on
REAL PLAY rather than the double-dummy guarantee (the ladder is measured 16%
looser than the solver believes, and every arm above inherits that), or
accepting that the tier is where it is and spending the effort elsewhere in the
game. **The code is kept and gated** — `belief_of`, `belief_into` and
`OppModel::Belief` are correct, tested and one env var from running, so a future
attempt starts from a built mechanism rather than from this paragraph.

### THE LEAF IS ALREADY CALIBRATED: THE DOUBLE-DUMMY GUARANTEE IS A MINIMUM, NOT A BIAS (2026-08-20)

**The seventh treatment, the one with the best premise, and the one that closes
the campaign.** `DIS_PLAY_CAL` ships at 0.

**THE PREMISE WAS A REAL MISALIGNMENT.** The exploitability instrument scores
every arm with the REAL-PLAY leaf — `cfrlab`'s own `leaf` applies the measured
deviation whenever the deal cache carries one — while the tree it grades
optimises the DOUBLE-DUMMY guarantee. The bot had been maximising an objective
it was not marked on, through six failed treatments, every one of them tuning a
coefficient inside that mismatch. The gap is measured, not assumed: 794 imposed
contracts played out by the shipped search on both seats put a real declarer
**+0.95 points** above the guarantee with **sd 1.94**, and the ladder that
follows 16% looser than the solver believes.

**ALIGNING THEM MADE IT MUCH WORSE, AND SO DID GOING THE OTHER WAY.** Paired on
324 deals, all four arms on identical seeds, each also split into four disjoint
quarters:

| leaf shift | exploitability | q0 | q1 | q2 | q3 | settled | made | probe-pass |
|---|---|---|---|---|---|---|---|---|
| **−1.45** (more pessimistic) | 6.69 | 7.44 | 6.86 | 6.74 | 6.55 | 3.45 | 86.7% | 91.4% |
| **0 — the guarantee (shipped)** | **5.42** | **6.54** | **5.09** | **5.35** | **5.60** | 4.47 | 67.3% | 81.6% |
| **+1.45**, no spread | 7.95 | 9.42 | 7.26 | 9.03 | 9.23 | 5.60 | 41.0% | 67.0% |
| **+1.45** + spread 1.94 | 6.89 | 7.39 | 6.57 | 8.61 | 8.78 | 4.86 | 51.9% | 68.6% |

**The shipped value is the minimum in the full sample AND in every one of the
four disjoint quarters.** That is as strong as this instrument gets, and it is
the one result in the campaign that is unanimous under the subset check rather
than merely surviving it.

* **The behaviour is perfectly monotone in the shift**, which is what says the
  knob does exactly what it looks like: settled mean 3.45 → 4.47 → 5.60 and
  contracts made 86.7% → 67.3% → 41.0%. **A shift of 1.45 points is almost
  exactly one rung of the ladder.**
* **So this experiment is an AGGRESSION DIAL wearing a calibration's clothes,
  and that is the finding.** It sweeps the bot's bidding level directly, in both
  directions, and the shipped point is the optimum of that sweep. The
  double-dummy leaf is not a pessimism to be corrected; it lands the bot exactly
  where the payoff wants it.
* **The spread half partly RESCUES the mean's damage** (7.95 → 6.89): making
  marginal contracts uncertain pulls back the overbidding a higher mean causes.
  Worth knowing, and not enough to matter.

**A RISK-PREMIUM READING WAS PROPOSED AND IS REFUTED BY ITS OWN TEST.** When the
+1.45 arm failed, the explanation on offer was that the guarantee acts as a risk
premium — bidding commits you to TAKE the points, and this payoff punishes a set
far harder than an overtrick pays, so the right estimate sits below the mean.
That story predicts **more** pessimism should help. `DIS_PLAY_CAL` was opened to
negative scales specifically to test it, and −1.45 reads **6.69**: worse, in all
four quarters. The story was wrong and the knob said so in three blocks. **A
prediction a knob can already express is worth checking before it becomes a
paragraph.**

**WHAT THE WHOLE CAMPAIGN ADDS UP TO.** Seven treatments — the opening bias, the
exact leaf, opponent softening, cross-fitting, the jump weight, the opponent's
own uncertainty, and the real-play leaf — all null or worse. **Five of the seven
moved the bot's aggression, and this last one sweeps that axis directly in both
directions and finds the shipped point at the bottom.** So the residual
exploitability (5.42 against this abstraction's 1.47 floor) **is not an
aggression problem**, and every treatment that failed was tuning the one axis
that was already right.

**That is a genuinely useful place to have got to**, and it is a stopping rule
with a reason rather than a shrug: what is left must be CONDITIONAL — which
hands the tree wins the auction with, not how high it bids — and nothing that
moves a coefficient uniformly can touch it. **`payoff_terms`, the leaf, the
opponent model and the selection rule are all now measured and all at or past
their optimum.** The next honest step is not another arm on this bot; it is
either a finer abstraction for the instrument (so a conditional defect can be
SEEN), or a different part of the game.

### THE INSTRUMENT IS VALIDATED, AND THE AUCTION'S WORLD COUNT IS MEASURED AT LAST (2026-08-20)

**After eight treatments made the bot more exploitable and none made it less,
the honest question stopped being "what next" and became "does this statistic
order strength at all".** The way to answer it is a bot that is knowably weaker
for a reason nobody disputes: fewer determinized worlds. Paired on 220 deals,
2-D abstraction, each arm also split into four disjoint quarters:

| arm | exploitability | q0 | q1 | q2 | q3 | settled | made |
|---|---|---|---|---|---|---|---|
| **k=1** (one world) | **13.25** | 13.76 | 15.01 | 15.14 | 12.84 | 5.60 | 40.5% |
| **k=2** | **8.13** | 7.72 | 10.51 | 11.21 | 9.50 | 4.83 | 54.5% |
| **k=8** (shipped) | **6.28** | 7.44 | 6.79 | 7.95 | 7.85 | 4.49 | 69.1% |
| k=16 | 6.73 | 7.55 | 7.47 | 8.41 | 8.19 | 4.42 | 74.5% |

**THE INSTRUMENT ORDERS SEARCH STRENGTH, STEEPLY AND IN EVERY QUARTER.** A
one-world bidder reads 13.25 against the shipped 6.28 — more than twice as
exploitable — and the ordering k=1 > k=2 > k=8 holds in all four disjoint
subsets. So exploitability is measuring something real about how well the bot
bids, and **the eight negative results are credible rather than an artefact of a
statistic that rewards whatever the shipped tier happens to do.** That question
had to be asked, and this is the answer.

**AND IT CLOSES AN OPEN QUESTION THIS FILE HAS CARRIED SINCE THE TIER SHIPPED.**
`CLIENT_AI_AUCTION_WORLDS` was raised 3 → 8 by analogy with the card search,
and the file said so outright: *"the auction's compute→strength curve is still
unmeasured; its cap is a separate `CLIENT_AI_AUCTION_WORLDS` (3) and nothing
says whether that sits at the knee the way 8 does here."* **It is measured now
and 8 is the right cap.** The curve falls hard to 8 (13.25 → 8.13 → 6.28) and
does not improve past it — k=16 reads 6.73, higher in all four quarters, for
double the solves. The knee is at or just below the shipped value.

* **k=16 is the eighth treatment and the eighth failure**, and it also refutes
  the mechanism that motivated it. The 2-D abstraction localised the bot's loss
  on CONCENTRATED hands, and the proposed cause was that a one-suit hand's value
  rests on a single denomination's estimate where a flexible hand's is
  corroborated across several — so more worlds should have flattened the
  grading. It does not: shape 2 goes 2.15 → 2.40 and shape 0 goes 1.19 → 1.53.
  Doubling the sample leaves the conditional defect exactly where it was.
* **Note that k=16 MAKES MORE CONTRACTS (74.5% against 69.1%) while being
  slightly more exploitable.** A clean reminder that the two quantities are
  different: a best responder is a far harsher opponent than the one across the
  table, and a policy can play better against real opposition while being easier
  to punish by an exact exploiter.

**WHAT THE CONDITIONAL DEFECT NOW IS, stated precisely, since it is what
survives.** The bot loses 1.75x more per unit of reach on one-suit hands than on
flexible ones; the mistake is concrete (it concedes strong concentrated hands
where the equilibrium overtakes); it is not the abstraction crediting an illegal
HOLD (legality is a uniform 78% across shape buckets, measured on 15,512 rebuilt
states); and it is **not a sampling-noise problem**, because doubling the worlds
does not touch it. It is a judgement the tree makes about a KIND of hand, and
the remaining candidates for it are structural rather than parametric.

### TWO PARALLEL RESEARCH LINES MEET HERE (2026-08-21)

Everything from here to the end came from **two session lineages that both
branched from `00170c9` and never saw each other's results**. The block
immediately below is the line that ran on `main` (cross-fitting, opponent
uncertainty, leaf calibration, the finer HAND abstraction, skat's talon); the
block after it is the line that ran on the research branch (the Double margin,
the trump channel, the pass/raise shading, the contested gate, the real ACTION
space, the CFR sampler).

**They agree, and the agreement is the interesting part.** The first closed with
"what is left must be CONDITIONAL — which hands the tree wins the auction with,
not how high it bids". The second widened a different abstraction and measured
one: the level-only ACTION space is **14.0 points a deal more EXPLOITABLE**
than a denomination-aware one -- a gap between two research blueprints against
an exact best responder, NOT a gain the shipped bot would make. Read "the
campaign closes" as scoped to uniform coefficients over the shipped action
space; it does not cover the action space itself.

Full narrative and the reconciliation: [`docs/ai-research-log.md`](../../docs/ai-research-log.md).

### AND THE WIDENED BLUEPRINT LOSES TO EXPERT BY 12.8 POINTS A ROUND (2026-08-20)

**`bpwt` vs `expertst`, CRN-paired, dd-resolved, 354 paired deals:**

| | |
|---|---|
| **blueprint − Expert** | **−12.8377 ± 1.4738 payoff/round** |
| 95% CI | **[−15.726, −9.949]** |
| auctions that differ | 342/345 (99.1%) |
| mirror (`hard hard`) | exactly **+0.0000** |

**8.7 SE, and stable the whole way** (−13.28 at n=87, −13.74 at n=95, −12.84 at
n=345). Stopped there rather than run to 1550: nothing at that separation
reverses, and the box was better spent elsewhere. For scale, the entire
`opp_temp` gain this file ships is **+0.957**, and Expert's whole edge over Hard
is **+1.19** — the blueprint loses by ten times either.

**THE MECHANISM IS ONE NUMBER:**

| | declared | mean level | **made** |
|---|---|---|---|
| blueprint | 337 | 4.08 | **49.6%** |
| Expert | 363 | 4.42 | **73.0%** |

**It buys contracts at the same heights and fulfils barely half of them.** That
is what an abstraction with NO DENOMINATIONS produces when its policy is
shipped: the blueprint names a LEVEL, the pricer then takes the best suit still
legal, and a level chosen blind to the suit is a commitment the actual hand may
not support. Expert's tree picks level and denomination together and makes three
quarters.

**SO THE WIDENING WAS THE WRONG AXIS, and that is the finding to carry.** The
extra hand features are real — the section below shows the equilibrium
conditioning on them by up to 1.9 rungs — and they are nowhere near the binding
constraint. **The abstraction's problem is its ACTION space, not its hand
space.** Anyone returning to this should put denominations in the tree and raise
the `MAXL = 8` ladder cap before adding a single further feature; more private
resolution on a policy that cannot name a suit buys nothing.

**AND IT BRACKETS THE THEORY EMPIRICALLY.** The equilibrium direction was argued
here as producing SAFETY rather than STRENGTH — in a two-player zero-sum game an
equilibrium guarantees the game value against any opponent but does not punish a
flawed one, so a perfect equilibrium bidder should DRAW with Expert. It lost by
12.8, which is worse than the theory predicts, and the extra distance is the
second fault: **an equilibrium of a coarse abstraction is not an equilibrium of
this game at all.** It is simply a policy, and a bad one. Its measured
exploitability of **1.46** was taken inside that same toy — the circularity
flagged when the number was first computed, now with a price attached.

Together with the `Diverse` gate above, two independent arms now say the same
thing: **exploitability is not strength here, and optimising it produces bidders
that are equal at best and catastrophic at worst.**

**HARNESS GAP, recorded because it is mine.** The `bp` branch returns before the
arena's opening-telemetry block, so `open` events are not recorded for a
blueprint tier — `mean opening` reads 0.00 at n=0 for `bpwt` above. It affects
the descriptive stats only; the strength number and the make rates come from the
round resolution and are unaffected.

### THE DOUBLE IS FINE. THE "-3.73" WAS THE DRIVER'S BASE RATE. (2026-08-20)

**RETRACTION FIRST.** The entry below concluded from `dblprobe` that the shipped
Double is "net destructive" and "the largest single shipped defect" — doubling
31% of contracts when 9.5% deserve it, discriminating by 3.5 points, capturing
−3.73 payoff a round. **That is wrong, and it is wrong for exactly the reason
that entry flagged as its load-bearing caveat: `dblprobe` drives with the SERVER
bot.** Re-taken on EXPERT-bid contracts, via `ARENA_DBL=1` + `tools/dblreport.py`
over 320 paired deals (640 doubles):

| | server-bot bid | **Expert bid** |
|---|---|---|
| doubles taken | 31.0% | 33.1% |
| doubles that SHOULD be | **9.5%** | **29.4%** |
| agreement with truth | 66.0% | **81.9%** |
| hit / false alarm / miss | 13 / 111 / 25 | **142 / 70 / 46** |
| doubles contracts that MADE | 30.7% | **15.5%** |
| doubles contracts that FAILED | 34.2% | **75.5%** |
| **discrimination** | **+3.5 pts** | **+60.0 pts** |
| **value captured** | **−3.73** | **+0.66** (of +5.36 available) |

**The Double doubles three quarters of failing contracts and one seventh of
making ones. It is not broken; it is working.**

**THE MECHANISM IS A BASE RATE, and it is worth carrying because it will happen
again.** Only **9.5%** of the server bot's contracts are worth doubling against
**29.4%** of Expert's. When almost nothing deserves a double, almost every
double taken is a false alarm BY CONSTRUCTION, and both the discrimination and
the captured value collapse without the decision rule changing at all. The
harness was measuring its driver's bidding, not the Double. **"Which bot did the
bidding IS the distribution" is already this file's rule; it applies to
DEFENDING decisions too, and a probe that drives itself is choosing its own
base rate.**

**THE MARGIN IS THE ONE THING THAT MIGHT STILL MOVE.** `dblsweep --live 12` over
the same recorded run — the sums are recorded, so every threshold is priced
exactly off one run:

| margin | dbl% | on FAIL | on MADE | disc | defender gain |
|---|---|---|---|---|---|
| **12** *(shipped)* | 32.5% | 74.5% | 15.0% | +59.4 | **+0.77** |
| 15 | 29.1% | 70.2% | 11.9% | +58.3 | +1.22 |
| **20** | 20.9% | 52.1% | 8.0% | +44.2 | **+1.45** |
| 24 | 11.6% | 28.7% | 4.4% | +24.3 | +1.04 |
| 32 | 5.3% | 16.0% | 0.9% | +15.1 | +1.14 |

**20 roughly doubles the defender's gain over the shipped 12**, by doubling less
often and more selectively — the payoff is asymmetric (a doubled contract that
MAKES costs far more than a doubled set wins), so the break-even sits well above
"more likely than not to fail".

**DO NOT SHIP THAT OFF THIS TABLE.** The declarer-EV column carries ±2.4–3.0, so
these candidates are not separated; the gain column has no error bar at all; and
**this file already records a `DOUBLE_MARGIN` re-fit that was wrong, shipped and
reverted (2026-08-16)**.

### AND IT WAS ONE RUN'S LUCK. `DOUBLE_MARGIN` STAYS AT 12. (2026-08-20)

**The +1.45 above did not replicate, and the constant does not move.** Re-taken
on deals 320–640 — a deal sample the first run never touched, same tier, same
harness — margin 20 reads **+0.966 against the shipped 12's +1.122**, i.e. the
peak is not merely smaller, it is on the wrong side. Pooled over both runs,
1280 recorded doubles:

| margin | dbl% | on FAIL | on MADE | disc | value/round | **vs 12** | **SE** | **t** | moved |
|---|---|---|---|---|---|---|---|---|---|
| 0 | 57.7% | 90.3% | 42.2% | +48.1 | −1.748 | **−2.694** | 0.296 | **−9.11** | 288 |
| 4 | 49.2% | 86.4% | 31.6% | +54.8 | −0.706 | **−1.652** | 0.252 | **−6.54** | 180 |
| 8 | 41.9% | 82.0% | 22.8% | +59.2 | +0.206 | **−0.739** | 0.193 | **−3.82** | 88 |
| **12** *(shipped)* | 34.8% | 71.8% | 17.3% | +54.6 | **+0.945** | — | — | — | 0 |
| 16 | 29.8% | 63.1% | 14.1% | +49.1 | +1.144 | +0.198 | 0.168 | +1.18 | 64 |
| 18 | 27.3% | 58.3% | 12.7% | +45.6 | +1.159 | +0.214 | 0.190 | +1.12 | 92 |
| 20 | 22.7% | 49.0% | 10.1% | +38.9 | +1.208 | +0.263 | 0.240 | +1.09 | 152 |
| 22 | 17.7% | 38.3% | 7.8% | +30.5 | +1.166 | +0.220 | 0.284 | +0.77 | 214 |
| 24 | 14.2% | 29.1% | 7.1% | +22.0 | +0.819 | −0.127 | 0.309 | −0.41 | 258 |
| 40 | 2.8% | 6.3% | 1.2% | +5.2 | +0.473 | −0.472 | 0.402 | −1.17 | 400 |

**THE VALUE CURVE IS FLAT FROM 12 TO 22 AND FALLS OFF A CLIFF BELOW IT.** Every
candidate above the shipped value sits at ~1 SE and none is separated from any
other; every candidate below it is decisive in the other direction (−3.8 SE at
8, −6.5 at 4, −9.1 at 0). **So the one thing this measurement establishes is
that the 2026-08-16 re-fit downward was wrong**, which is already known — and it
now has a number instead of a postmortem. There is no measured reason to move
the constant up, and one run said there was.

**THE ERROR BAR IS PAIRED AND EXACT, AND THAT IS WHY IT COULD BE HAD AT ALL.**
The margin changes which doubles are TAKEN and nothing else — the auction tree
does not model the Double, so the contracts are identical at every candidate,
and a Double changes the payoff rather than the card play, so the rounds are
too. Every round therefore appears in both arms and most contribute exactly
zero. `moved` is how many rounds a candidate actually re-decides, so the SE is
visibly a statement about those: **at margin 14 it is 34 rounds of 1280**, which
is why a swept table with no error bar reads so much more confidently than the
data supports. **A CRN-paired arena would have been the wrong instrument** — it
would re-measure this same quantity through 18 points of per-deal payoff noise,
at hours per candidate, when the recorded sums and the exact ground truth price
every candidate for free.

**THE METHOD NOTE, and this file has now recorded it five times.** A single 320-
deal run put margin 20 at **+0.681 ± 0.351** — 1.94 SE, a plausible-looking
peak, a smooth single-humped curve, and a mechanism that reads as sound (the
asymmetric payoff really does push break-even above 50%). The independent sample
put it at −0.156. **A smooth curve with a mechanism is not a replication.** This
is the same constant the repo has already re-fitted wrongly once; the only thing
that stopped it happening twice was running the second sample before writing the
first one down as a result.

**Instrument notes.** `dbl_truth` runs on its own bidserve channel for the reason
`quality_of` documents — the `Solved` cache is one slot and an off-tier ask
evicts the auction entry; the mirror still reads exactly +0.0000 with recording
on. `dblreport` pools BOTH flips of a pair, since each flip is its own Double by
its own tier and reading `events[0]` alone would halve the sample and silently
drop every decision the second seating made.

### THE PRIOR'S UNSPENT CHANNEL IS TRUMP LENGTH — and the DOUBLE turned out to be fine (2026-08-20)

**THE PRIOR'S OWN AXIS IS FINISHED.** `tools/channelprobe.py`, 400 rounds at the
Double, 200 resamples each, shipped tilt 0.35. Percentile of the declarer's TRUE
holding inside the sampler's own distribution; **0.500 is unbiased**:

| statistic | uniform | under the shipped tilt |
|---|---|---|
| **strength** *(the control)* | 0.737 | **0.508 ± 0.014** |
| **trumps** — cards in the DECLARED denomination | 0.779 | **0.744 ± 0.011** |
| **tops** — cards in the top two ranks | 0.624 | **0.457 ± 0.013** |
| **voids** | 0.506 | 0.506 ± 0.005 |

The control validates the instrument: the prior takes strength from 0.737 to
0.508, i.e. it does exactly what it claims and there is nothing left on that
axis. **Re-tuning tilt/curve/tries is spent.**

**TRUMP LENGTH IS THE UNSPENT CHANNEL, AND IT IS BIGGER THAN THE BIAS THE PRIOR
WAS BUILT FOR.** *(SPENT, 2026-08-20 — it corrects cleanly and is worth nothing;
see "THE TRUMP CHANNEL: CORRECTED, CENTRED, AND WORTH NOTHING" below. Read the
rest of this paragraph as the diagnosis, not as an open lever.)* 0.779 against the 0.765 that started this whole thread — and
the tilt removes only **0.035 of a 0.279 bias, about 13% of it**. The reason is
structural: `trump_mult = 2.0` makes trumps count double *in a scalar sum*,
which is not the same as modelling suit LENGTH — a hand reaches the same sum
with high cards anywhere. A declarer who NAMED a denomination is direct evidence
about that suit specifically, and the sampler still deals them too few of it.

`tops` is mildly OVER-corrected (0.624 → 0.457, past centre) and `voids` carries
nothing. So of four dimensions: one finished, one large and untouched, one
slightly over-shot, one empty.

**TWO CHANNELS COULD NOT BE MEASURED AT ALL under a server-bot driver, and that
is a fact about the harness rather than about the channels.** `to_double` drives
with `bot.act`, which opens at the level it settles on and always swaps:

* **bid path** — only **5 of 400** rounds had the declarer pushed above its
  opening. Those 5 read **0.704 ± 0.105** against 0.506 for the rest, which
  hints that a pushed declarer is badly under-rated, but n=5 is a hint and
  nothing more.
* **talon swap** — **400 of 400** swapped. Zero information; the split cannot
  exist under this driver.

Both need Expert-driven auctions (`ARENA_DEALS=1` records the position at the
Double for exactly this).

---

**THE DOUBLE: the prior does not help it, and the Double has a much bigger
problem than the prior.** `tools/dblprobe.py`, same 400 rounds, ground truth an
exact double-dummy resolve under both the doubled and undoubled terms:

| | prior ON *(shipped)* | prior OFF |
|---|---|---|
| doubles taken | 124 (**31.0%**) | 115 (28.8%) |
| doubles that SHOULD be taken | 38 (9.5%) | 38 (9.5%) |
| agreement with truth | 264 (**66.0%**) | 273 (**68.2%**) |
| hit / false alarm / miss | 13 / **111** / 25 | 13 / **102** / 25 |
| **value captured** | **−3.73** | **−3.33** |
| doubles contracts that MADE | 111/362 = **30.7%** | 102/362 = 28.2% |
| doubles contracts that FAILED | 13/38 = **34.2%** | 13/38 = 34.2% |

**The prior makes the Double slightly WORSE.** Identical hits (13), nine MORE
false alarms, lower agreement, worse value. So the one place the belief thread
left open — "the Double is a binary make/fail call, not a move choice, so
strategy fusion does not apply there" — measures negative too.

**AND THE DOUBLE BARELY DISCRIMINATES AT ALL — RETRACTED, see the section above.
On EXPERT-bid contracts it discriminates by 60.0 points and captures POSITIVE
value; everything in this paragraph is the server-bot driver's base rate.** It
doubles contracts that MADE at 30.7% and contracts that FAILED at 34.2% —
three and a half points of separation. `value captured` is `sum(gain) / rounds` where
`gain = payoff(undoubled) − payoff(doubled)`, so **−3.73 means the doubles taken
COST the defender 3.73 payoff a round**, against **+2.84** available if they
were targeted perfectly. The shipped Double is not a small inefficiency; it is
net destructive on this measurement.

**CAVEATS, and the first is load-bearing.** These rounds are driven by the
SERVER bot, so the contracts arriving at the Double are its contracts, not
Expert's — and this file's own rule is that **which bot did the bidding IS the
distribution**. The ON/OFF comparison is clean because both arms share the
driver; the ABSOLUTE rates may not transfer to an Expert-bid room, and should be
re-run through `ARENA_DEALS` positions before anything is re-priced on them.
`DOUBLE_MARGIN` was live at its shipped 12 in both arms, so this is the Double
*with* its suppressor already applied.

**AND `dblprobe` WAS MEASURING A DOUBLE THE SERVER DOES NOT PLAY.** Its `ask`
said "the armed double request, exactly as main.py builds it" while sending
NEITHER shipped knob — no `bid_prior`, no `double_margin`. Every number it ever
produced described an adjacent decision. Fourth instrument of this exact shape
after `cmatch`, `abench` and `nullbot`; both knobs now default to the shipped
values with `DIS_BID_PRIOR=0` / `DIS_DBL_MARGIN=<x>` keeping the control arms
reachable.

**A METHOD NOTE worth carrying.** `channelprobe`'s percentile is MID-RANK, and
that is not a refinement: three of its four statistics are small integers
(0–13 trumps, 0–4 tops, 0–4 voids), so ties are the common case and a strict `<`
counts every tie as "above me". The first cut did that and `voids` read exactly
0.000 on every round. `beliefprobe` gets away with strict `<` because its
statistic is a float sum that essentially never ties; a discrete one cannot.

### THE TRUMP CHANNEL: CORRECTED, CENTRED, AND WORTH NOTHING (2026-08-20)

**`BidPrior.trump_len` is built, correct and SHIPS AT 0.0.** The fourth
consecutive entry in this file where a real, measured belief bias did not become
a measured gain — and the first where the null came with its own decomposition,
so it is not merely "no effect" but "here is where the apparent effect went".

**THE CORRECTION WORKS, AND IT IS NEARLY FREE ON EVERY OTHER CHANNEL.** A flat
worth per trump added on top of the rank curve — `exp(beta x strength + gamma x
trumps)`, gamma 0 being the shipped prior byte for byte. Swept offline over one
run of draws (`channelprobe sweep`, 400 rounds, 200 resamples each; `draws_of`
is split from `score` so every candidate gamma is a lookup, the `swaplab`
method):

| gamma | strength *(control)* | trumps | tops | voids |
|---|---|---|---|---|
| **0.00** *(shipped)* | 0.508 | **0.744** | 0.457 | 0.506 |
| 0.50 | 0.491 | 0.639 | 0.465 | 0.502 |
| **1.00** | **0.483** | **0.530** | **0.477** | 0.497 |
| 1.50 | 0.481 | 0.429 | 0.491 | 0.491 |

At gamma 1.0 the trump channel centres and **nothing pays for it**: strength
stays inside 2 SE of 0.500, voids do not move, and `tops` — which the shipped
prior OVER-corrects to 0.457 — comes back toward centre. This is not the usual
trade of one channel against another, which is what made it worth gating.

**WHY A FLAT TERM AND NOT A BIGGER `trump_mult`:** the multiplier scales a
trump's RANK, so the same strength sum is reachable with high cards anywhere and
a long suit is worth only what its cards happen to be. A flat term values the
sixth trump as much as the first, which no multiplier on a curve can express at
any dose. That is the shape the 0.779 → 0.744 residual is made of.

**THE GATE: 320 CRN-PAIRED DEALS, ONE CHANGE WIDE, EXACT GROUND TRUTH.**
`expertst` self-play both arms, same seeds, `ARENA_DBL=1` so every Double is
scored against an exact double-dummy resolve of both branches:

| | gamma 0 *(shipped)* | gamma 1.0 |
|---|---|---|
| doubles taken | 33.1% | 35.6% |
| **agreement with truth** | **81.9%** | **80.0%** |
| **discrimination** | **+60.0** | **+56.9** |
| value captured | +0.66 | +0.98 |
| *of an available* | *+5.36* | *+5.84* |

**PAIRED PER DEAL: +0.328 ± 0.784 a round, t = +0.42.** Nothing — and the two
quality columns that carry no base rate at all (agreement, discrimination) both
move slightly the WRONG way.

**AND THE DECOMPOSITION IS THE FINDING.** The available value moved **+0.481 ±
0.547** on the same pairing: the trump term changes the BIDDING as well as the
doubling, so more contracts worth doubling arrived at the Double. Net of that,
the decision itself is **−0.153 ± 0.565**. **The entire nominal gain is a base
rate.** That is the exact mechanism behind the `dblprobe` claim this file
retracted a day earlier, caught this time BEFORE it was written down as a
result — which is the whole return on having understood it: *"which bot did the
bidding IS the distribution"* applies to a bot bidding against ITSELF under a
changed prior, not only to swapping one bot for another. **Any measurement of a
defensive decision must report the base rate beside the value captured, or it
cannot tell a better defender from an easier population.**

**IT IS KEPT, OFF, AND THAT IS DELIBERATE.** `trump_len` is optional on the
wire, so 0.0 is the old prior byte for byte and a cached wasm reads 0.0 — the
`tilt = 0` discipline. No wasm was rebuilt, which is safe for exactly that
reason and does mean the term reaches only the offline harnesses until one is.
`DIS_BID_TRUMP_LEN` arms it for any future arm that needs a better-calibrated
sampler for its own reasons.

**THIS CLOSES THE BELIEF THREAD FOR THE SECOND TIME, on its last open channel.**
The file already recorded it closed on the strength axis with a mechanism —
`DOUBLE_MARGIN` discards every decision below its threshold and the prior
sharpens precisely those, so the two are treatments for one disease and the
margin gets there first. The trump channel was the one large uncorrected bias
left, it corrects cleanly, and it lands in the same place. Four instruments now
agree (the Double at +0.161 ± 0.623, card play at +0.617 ± 2.522,
exploitability, and this): **in this game a better world distribution is not a
better bot**, which is CAMPAIGN.md's strategy-fusion verdict arrived at from a
fourth direction. Do not re-open this without a mechanism that is not "the
sampler is biased" — that has now been true, correctable and worthless four
times.

### THE WIDENED ABSTRACTION CARRIES REAL SIGNAL — the equilibrium conditions on it (2026-08-20)

The Edelkamp direction, first half. `CFR_FEATURES=2` makes the private bucket a
JOINT index over strength x `tops` (quick tricks: cards in the top two ranks the
seat can NAME), 8 buckets to 24. Solved on a purpose-built 1500-deal cache,
200k external-sampling iterations, all 24 buckets occupied:

**MEAN OPENING BY (strength bucket, tops bin) — and read across the ROWS:**

| strength | tops=0 | tops=1 | tops=2 | spread |
|---|---|---|---|---|
| 0 | 1.43 | 1.57 | 1.68 | 0.24 |
| 1 | 1.50 | 1.96 | 1.75 | 0.47 |
| 2 | 1.49 | 2.00 | 1.89 | 0.52 |
| 3 | 3.28 | 2.03 | 2.35 | 1.26 |
| 4 | 3.83 | 3.28 | 2.67 | 1.16 |
| 5 | 2.31 | 3.03 | 3.49 | 1.18 |
| 6 | 2.92 | 2.85 | 3.95 | 1.10 |
| 7 | 3.94 | 3.05 | 4.95 | 1.90 |

**At the SAME strength, the equilibrium opens up to 1.9 rungs apart depending on
quick tricks.** That is the whole claim the widening had to support: the feature
is not merely correlated with the leaf, it changes what the solved policy does.
A feature the policy ignored would have shown flat rows and the 24 buckets would
have been 8 buckets in an expensive coat.

**MEASURED BEFORE BUILT.** `tools/featlab.py` scored every candidate by the R^2
it adds ON TOP of the strength already in the bucket — `tops` +0.0294,
`shortest` +0.0216, `voids` +0.0114 against a 0.4013 baseline, over 1600
seat-hands. The control in that table is `s_mean`: 0.3660 alone, **+0.0001
incremental**, the same information restated. Anything that could not separate
those two would be measuring correlation and calling it structure.

**THE COST IS REAL AND VISIBLE IN THE OCCUPANCY.** 24 buckets over 3000
seat-hands: median 117, **minimum 1**. The tail is thin, which is precisely what
this file records as having wrecked the exploitability instrument once already
(54% of a best responder's winnings coming from infosets nobody visited).
Widening is only affordable against a bigger cache, which is the bootstrapping
half of the idea and why the cache was rebuilt at 1500 rather than reused at 400.
`CFR_FEATURES=3` (adding `shortest`, 72 buckets) is built and should not be run
until the cache is several times larger again.

**WHAT IS NOT ESTABLISHED, and it is the important half.** This says the widened
equilibrium BIDS DIFFERENTLY, conditioned on a feature the narrow one cannot
see. It says nothing about whether it PLAYS BETTER. Per the gate above,
exploitability and head-to-head strength are close to independent in this game,
so the only thing that can answer that is a CRN-paired arena — blueprint-wide
against blueprint-narrow, and against Expert. Until that runs this is a
structural result, not a strength result.

### THE GATE: DIVERSE IS LESS EXPLOITABLE AND NOT STRONGER. IT DOES NOT SHIP. (2026-08-20)

**`expertdt` vs `expertst`, CRN-paired, dd-resolved, 1550 paired deals — the
same n the shipped `opp_temp` result was published at:**

| | |
|---|---|
| **diverse − Expert** | **−0.6810 ± 0.5329 payoff/round** |
| 95% CI | **[−1.725, +0.363]** |
| auctions that differ | 1512/1550 (**97.5%**) |
| mirror (`hard hard`) | exactly **+0.0000** |

**1.28 SE, spanning zero, and pointing the wrong way. The ship bar is a positive
head-to-head at equal time; this does not clear it, and `Diverse` costs ~2.5x.
It stays behind its flag, off.**

**THE TWO NUMBERS TOGETHER ARE THE FINDING, and they are worth more than either
alone.** `Diverse` is **23% less exploitable** (9.14 → 7.06, split-half bands
not overlapping) and **not measurably stronger**. This file already records the
same dissociation in the other direction — Expert is MORE exploitable than Hard
while beating it +0.957 ± 0.454. Two independent instances, opposite signs:

> **In this game, exploitability and head-to-head strength are close to
> independent. The exploitability instrument is not a proxy for strength, and a
> campaign steering by it alone is steering by something else.**

That is the durable lesson of the whole 2026-08-19/20 run and it applies
retroactively: every exploitability figure in the sections above is a statement
about exploitability, and none of them was ever evidence about strength.

**WHY IT COMES OUT NULL, and the mechanism is legible in the arms' own
statistics:**

| | mean opening | mean settled | made |
|---|---|---|---|
| `expertdt` (diverse) | 2.56 | 4.00 | 66.7% |
| `expertst` (Expert) | 2.42 | 4.17 | 66.5% |

**97.5% of auctions take a different SEQUENCE and the aggregate SHAPE barely
moves.** Diverse rearranges which line it walks without changing the
distribution it lands on — so a best responder finds it harder to punish (fewer
crisply predictable nodes) while the opponent across the table sees the same
contracts made at the same rate. Less exploitable, equally strong, by
construction.

**AND IT LEAVES THE STANDING DIAGNOSIS UNTOUCHED, which was predicted before the
run.** The conditional defect is that the opening barely varies with the hand;
the equilibrium opens near 4 almost regardless. Diverse moved the mean opening
**2.42 → 2.56 — a fifth of a rung.** It attacks the pass-vs-raise pessimism
asymmetry, which is a real and different defect. Nothing here is evidence about
the conditional one.

**METHOD NOTE, and this file has now recorded it four times.** The running
estimate wandered **−2.57 (n=196) → −2.02 → −1.51 → −0.77 → −0.21 (n=718) →
−0.85 → −0.68 (n=1550)**. Any of those early reads, quoted alone, would have
been a different conclusion — including a confident "diverse is clearly worse"
at n≈200. The harness's own warning is the same one: a 300-deal read once said
+1.71 where the full run said −0.28.

**COST OF THE MEASUREMENT, for whoever runs the next one:** ~5.5 deals/min on an
uncontended 4-core box at 4 shards, so n=1550 is 4-5 hours; per-deal sigma ≈18.
**And the harness's variance reduction is inert for expert-vs-expert races** —
the quality covariate is captured only when a seat's tier is literally `hard`,
so `q` is 0 throughout and the adjustment does nothing. That is true of this
gate and of the `opp_temp` measurement whose ±0.454 was therefore raw. Fixing it
costs one extra myopic ask per deal. See `tools/GATE_RESUME.md`.

### MULTI-VALUED STATES CUT EXPLOITABILITY 23%, AND THE BLUEPRINT NUMBER IS CIRCULAR (2026-08-19)

Three bidders, **same 400-deal cache, same instrument, same 90 rounds, same
`CFR_PROBES=96`** — so the three are comparable TO EACH OTHER and to nothing
else in this file:

| bidder | BR seat 0 | BR seat 1 | exploitability | split-halves |
|---|---|---|---|---|
| CFR equilibrium (the floor) | −1.73 | +3.22 | **0.75** | — |
| **base** — shipped Expert, `soft` temp 5 | +8.08 | +10.20 | **9.14** | 10.01 / 10.77 |
| **diverse** — `OppModel::Diverse(6, 3)` | +4.64 | +9.47 | **7.06** | 7.76 / 7.71 |
| **blueprint** — the equilibrium as the bidder | −0.88 | +3.81 | **1.46** | 1.67 / 1.59 |

**THE ABSOLUTE NUMBERS DO NOT COMPARE TO THE 5.45 / 5.70 ON RECORD.** Different
deal cache (400 deals against 2000), different corpus size (90 rounds against
420), and the floor moves with it — 0.75 here against 1.47 there. This file
already states the rule and it applies to its own new rows: read the two rows as
a difference, and only within one cache.

**DIVERSE IS THE REAL RESULT: 9.14 → 7.06, a 23% cut**, with split-halves 7.76 /
7.71 against base's 10.01 / 10.77 — the two bands do not overlap. It is the first
thing this campaign has measured that moves exploitability at all: the opening
bias did not, the exact leaf did not, and the temperature knob's own sweep
cancelled. And it is **not** circular — `Diverse` is a minimax variant, not the
equilibrium, so the abstraction's best responder has no special purchase on it.

**THE BLUEPRINT'S 1.46 IS LARGELY CIRCULAR AND MUST NOT BE READ AS STRENGTH.**
The blueprint plays (an approximation of) the abstraction's own equilibrium, and
the best responder is computed *inside that same abstraction*. A policy scoring
near the floor of the game it was solved for is the expected outcome, not
evidence about the real game — where denominations exist, the forever-ban binds,
and a real opponent is not restricted to the ladder. **The only thing that can
price the blueprint is a CRN-paired auction arena against Expert at equal time,
with the mirror reading exactly 0.5000.** That has not been run.

**COSTS, measured.** `Diverse` runs about **2.5x slower** than `soft` on the
control arm (the base arm's three shards finished in ~6 minutes; diverse took
~15). That is worth understanding before shipping: a MIN node under `soft`
evaluates every child and memoises, while `Diverse` evaluates at most three but
also prices every legal reply through `opp_myopic` first, and the narrower child
set appears to share less of the memo. At the shipped 12s watchdog that matters.

**WHAT IS NOT ESTABLISHED.** 90 rounds is well under the 200–414 this file's own
readings use (200 read 6.01, 414 read 5.87 on the other cache), so treat all
three as preliminary. No head-to-head has been run for either arm, and this file
is explicit that exploitability and head-to-head strength are different
quantities — Expert is *more* exploitable than Hard while beating it +0.957.

**THE STAMP HAD THE SAME BUG AGAIN, ONE RELEASE LATER.** The blueprint corpus
carried `dv: 0` and `temp: 5`, so `corpus_tiers` labelled it "soft temp 5
(expert)" — the exact mislabelling the stamp exists to prevent, reintroduced by
adding a bidder without adding it to the stamp. `bp` is in the row now. Fourth
instrument bug of this shape.

### THE 2026-08-16 RE-PRICE LEFT THREE OFFLINE HARNESSES AND FOUR DOC CLAIMS BEHIND (audited 2026-08-19)

**The question that started it: "anything tested against the wrong scoring must
be invalid — do we need to restart anything?" The answer is yes for two
harnesses, no for a third, and no for anything measured on 2026-08-19.**

`a317bb1` re-priced classic in one commit — make `N²+10 → N²+4`, set
`N+10 → 2N+2`, and `JUMP_SET_BONUS 3 → 6`. It updated the engine, `rules.jsx`
and `payoff.jsonl`. It did not update anything that builds its own `Contract`.

**THE THREE STALE BINS.** Each was internally consistent, which is why each
stayed wrong:

| bin | carried | shipped | what it invalidates |
|---|---|---|---|
| `cmatch.rs` | `N²+10` / `N+10` / **`over: 0`** | `N²+4` / `2N+2` / `over: 1` | every contract-vs-points number, incl. "+0.55 at level 4, +1.25 at level 1" and "6–7 Nulls per 40 rounds" |
| `nullbot.rs` | `N²+10` / `N+10` / `over: 1` | as above | every Null rate it has reported |
| `abench.rs` | level-3 `make 19` / `set_base 13` / `over: 0` | `13` / `8` / `1` | **nothing — see below** |

**`abench` SURVIVES, and the reason is worth stating rather than assumed.** Its
numbers are NODE COUNTS (18,435k → 7,220k, −61%; MTD(f) −6%; the cross-world
seeding null). Those measure hits in `bid::Solved`, which is keyed on the HAND
and the denomination — the price list changes the arithmetic layered on top of a
solve, never which solves happen. The caching results stand as measured.

**`cmatch`, RE-RUN on the shipped price list** (80 deals x2, k=8):

| level | edge (contract-aware − points) | mirror control | Nulls |
|---|---|---|---|
| 1 | **+2.562 ± 1.605** | **0.000 ± 1.602** | 12 vs 0 |
| 4 | **+7.112 ± 3.442** | **0.000 ± 3.552** | 14 vs 0 |

**AND THE HARNESS PRINTED NO ERROR BAR UNTIL NOW, WHICH IS THE REAL FINDING.**
At n=160 the level-1 edge is **1.6 SE** and level 4 is **2.1 SE** — one interval
spans zero and the other barely clears it. The recorded +1.25 and +0.55 were
taken at n=80 with no interval printed at all, so results that were never
established have read as settled fact for months. This file's own
rule ("an interval spanning zero is not a direction") could not be applied to a
harness incapable of producing one. It produces one now.
* The mirror reading **exactly 0.000** is the good news: `cmatch` rotates which
  bot is contract-aware across the two seatings, so the seed asymmetry that
  makes `arena`'s null read +0.147 at n≈200 genuinely cancels here. Its pairing
  is sounder than `arena`'s.
* **The Null rate roughly HALVED, exactly as this file predicted and never
  re-ran**: 12 per 160 rounds is 3 per 40, against the recorded 6–7 per 40. The
  standing note — "the cliff is smaller and the Null rate should have fallen
  with it. **Nobody has re-run it**" — is now discharged.
* **THE CONCLUSION SURVIVES; THE EVIDENCE FOR IT IS WEAKER THAN THE FILE
  IMPLIED.** The direction is positive at both levels with clean mirrors, and
  the Null counts are a CATEGORICAL difference no error bar touches — the points
  searcher takes zero Nulls in 160 rounds at either level, which is the
  structural claim ("a points solver cannot see the consolation cliff") showing
  up as a count rather than a margin. That is what actually justifies the
  contract-aware tier; the payoff margins never carried it.
* Do NOT read +2.562 against the old +1.25 as a ratio. The payoff CURRENCY moved
  too (a level-1 make base went 11 → 5), which is this file's own
  `DOUBLE_MARGIN` lesson: a measurement in payoff units is silently re-scaled by
  a re-pricing.

**FOUR DOC CLAIMS FROM THE SAME COMMIT, now corrected**: the section that
DEFINES the jump bonus still said 3 (`rules.jsx` had 6 all along, so players
were told the truth and the manual was not); "what shipping a rate change would
entail" read as pending work when it had shipped; the leaf-bug postmortem quoted
the set base as `(N + 10 + 3j) × D`; and `Dissonance.jsx`'s worked example
showed `(N × N + 10)`.

**VERIFIED CLEAN:** `payoff.jsonl` regenerates byte-identical, and a sweep of
every `src/bin/*.rs` plus the Python and JSX finds no other copy.

**THE MECHANICAL FIX, so this class cannot recur.**
`tools/gen_shipped_terms.py` emits the plain per-level classic terms — and the
jump axis — straight out of `engine._terms_for` into
`tests/fixtures/shipped_terms.jsonl`; `dd::shipped_classic_terms` is the crate's
ONE copy and two Rust tests hold it to that fixture. The pre-existing
`wire::payoff_parity` pins the arithmetic that turns terms into a number; this
pins WHICH TERMS the game charges, which is the half nothing covered and the
half a bin inventing its own was free to get wrong. Verified non-vacuous
(reverting the make base fails it), and a jump-rate test would have caught the
documentation half too.

**NOT AFFECTED: everything measured on 2026-08-19.** `pimcprops`, `sigma` and
the alpha-mu arena all score in trick POINTS and never build a contract; the
three `cfrlab` exploitability arms price through `engine._terms_for`, i.e. the
live engine; and `priorexp` was written after the fix and reads
`shipped_classic_terms`. None needs re-running.

## Not built yet


**Before picking anything here up, read
[`docs/dissonance-external-ai-survey.md`](../../docs/dissonance-external-ai-survey.md)
(2026-08-19).** It maps the world's strongest AIs for adjacent games — Skat
(Kermit, and Edelkamp's paranoia search / hope cards), bridge declarer play
(NooK), heads-up poker (Libratus / Modicum / ReBeL), DouDizhu (PerfectDou) — onto
the two open problems this file has measured, and it names published algorithms
for both. The three findings worth knowing without opening it:

* **No game with this shape has a superhuman AI** (two-player trick-taking WITH a
  competitive auction). Skat is expert-level and is the closest cousin for CARD
  PLAY; heads-up poker is the closest cousin for the AUCTION.
* **The auction is a BETTER-CONDITIONED problem than the one poker solved**,
  because its leaf is exactly solvable and cached per hand. `cfrlab`'s
  equilibrium is currently only an instrument; poker's answer to "the abstraction
  is too coarse to ship" was to make the blueprint a SEED and re-solve the real
  subgame at decision time.
* **`OppModel::Soft` and CAMPAIGN.md's "untried one-sided search" are both
  hand-rolled cousins of published algorithms** — multi-valued states
  (Brown/Sandholm/Amos) and αµ (Cazenave/Ventos) respectively. The two cheapest
  items are pure diagnostics that need no new search: this game's three PIMC
  properties (leaf correlation / bias / disambiguation factor), which predict in
  advance how much strategy fusion is recoverable, and the sigma measurement this
  file already asks for and has never run.

### THE TREE IS PESSIMISTIC ONLY ABOUT THE BRANCH THAT CONTINUES — CONFIRMED, QUANTIFIED, LOCALISED (2026-08-20)

**The first positive finding of this campaign.** Ten items attacked the SAMPLER
(four nulls) or the ABSTRACTION (three refusals); this is the first instrument
pointed at the defect the attribution kept naming, and the defect is real.

**THE STATISTIC, and it needs no ground truth and no continuation assumption:**

    shade(option) = tree value - price-list value, SAME option, SAME node

Passing is a LEAF IN BOTH pricers, so its shade is an exact control. Bidding
continues into a subtree whose modelled opponent holds our exact hand. Both
vectors come off the SAME `entry.worlds` — `answer_auction` computes them
together — so this cannot be a leaf-accuracy artefact or a sampling artefact.
`tools/shadeprobe.py`, 400 deals, 900 decisions where both branches were legal,
`expertst` driving its own auction:

| | per-world payoff points |
|---|---|
| **passing (the CONTROL)** | **+0.000 ± 0.000** — exactly zero on every node |
| bidding, every option unselected | **−0.735 ± 0.056** (13 SE) |
| **bidding, the price list's favourite** | **−10.222 ± 0.391** (26 SE) |

**THE TREE SHADES THE BID BRANCH BY ~10 POINTS ON THE OPTION IT IS ACTUALLY
CHOOSING, AND THE PASS BRANCH BY EXACTLY NOTHING.** Consequence at the same
nodes: **the tree concedes 44.4% where the price list concedes 29.0%.**

**AND IT IS LOCALISED EXACTLY WHERE THE DEFECT WAS NAMED.** The shading decays
monotonically as the standing bid rises — because a higher standing bid leaves
fewer rungs, i.e. less subtree to be pessimistic about:

| standing | n | bid shade | tree passes | price list passes |
|---|---|---|---|---|
| 1 | 264 | −1.193 ± 0.159 | **22.3%** | **0.0%** |
| 2 | 67 | −1.803 ± 0.197 | **31.3%** | **1.5%** |
| 3 | 108 | −1.192 ± 0.115 | **36.1%** | **9.3%** |
| 4 | 170 | −0.472 ± 0.067 | **48.8%** | **34.1%** |
| 5 | 181 | −0.111 ± 0.033 | 60.2% | 56.9% |
| 6 | 100 | +0.027 ± 0.016 | 79.0% | 79.0% |
| 7 | 9 | +0.013 ± 0.013 | 100.0% | 100.0% |

At standing 6–7 the two pricers agree to the decision, and the shade is zero.
Every point of divergence is at standing 1–4. **That is the "concedes level 4"
finding, plus three rungs below it nobody had looked at.**

**WHERE THE SHADING FLIPS THE DECISION (153 nodes), IT LOOKS WRONG — and this
row is the confounded one.** Against an exact double-dummy resolve of each
branch, the tree's choice is worth **−9.020 ± 1.816** against the price list's,
better on 54 and worse on 99. **Read it as direction, not magnitude**, for two
reasons that both cut the same way: the resolve prices each option as if the
auction SETTLES there, and a bid's true value is at most its settled value (the
opponent may raise over it), so it FLATTERS bidding; and the price list is not
a better bidder in general — the tree beats the worlds-matched price list
**+1.19 ± 0.32** head to head — so these 153 nodes are selected on disagreement.
The shade rows above carry no such confound.

**THE FIX IS A ONE-CONSTANT ADDITIVE CORRECTION AND NEEDS NO RUST CHANGE.**
A per-option term the SERVER computes and the search adds is a pattern this
package already ships twice (`double_margin`, `open_bias`), so a pass penalty —
or equivalently a bid bonus — rides the same wire field. And it can be swept
EXACTLY off recorded nodes rather than arena'd per candidate, the method that
priced every `DOUBLE_MARGIN` for free: record each node's two vectors plus an
exact resolve, and every candidate correction is a re-argmax over numbers
already in hand. **The ship gate is unchanged and is not the sweep table** — a
CRN-paired arena at equal time, mirror exactly +0.0000 — because this file
already records one constant re-fitted on a sweep, shipped, and reverted.

**TWO INSTRUMENT TRAPS, both of which produced clean plausible tables first.**
* **The two pricers must land on the SAME WORLDS.** Sent to its own channel per
  the `quality_of` discipline, the price list drew a fresh sample and the
  control read **−13.2 ± 6.5** — two samples disagreeing, not a tree shading
  anything. It now goes to the SAME `bidserve` processes right after the tree
  ask, where the one-slot `Solved` entry is already filled with the union of
  denominations and the price list wants a subset, so it is a pure cache hit.
  **The `swap` block is load-bearing**: it is XOR'd into the cache key, so a
  myopic ask omitting the talon model keys differently, misses, solves fresh
  worlds, and evicts the tree's entry on the way out.
* **IMPORTING `auction_arena` RUNS IT.** It reads `sys.argv` at module level and
  its race body has no `__main__` guard, so the first run of this parsed argv as
  mode "6", **k = 0**, and reported a full table off a search over ZERO worlds.
  It is imported under a valid empty-window argv now, with `K` read back OFF the
  arena so the two cannot diverge — rather than copying `ask()`, which is
  exactly how `cfrlab` spent a campaign measuring Hard while claiming Expert.
* And the control read `−0.000` rather than `0.000` until the **`1e-5 × myopic`
  tie-break** was subtracted back off the tree's sums. It is recoverable exactly
  (the same `myopic` vector is in hand), and the report now SHOUTS if the
  control is ever non-zero rather than leaving it to be noticed.

### AND BOTH DIAGNOSTICS ANSWER: IT IS CLAIRVOYANCE, AND ALMOST NONE OF IT IS LEGITIMATE (2026-08-20)

**The two questions a correction had to answer before it could be designed, both
measured on 400 deals / 973 decisions, control exactly zero at every arm.**

**1. WHICH MECHANISM — the temperature is a direct lever, so it is the modelled
opponent's clairvoyance, not the optimiser's curse.** Every temp is priced at
the SAME node on the SAME worlds (`opp_model`/`opp_temp` are search parameters,
not world parameters — they are not in `hand_key`), and the first drives the
auction, so the arms are exactly paired:

| opp_temp | pass (control) | bid, all options | bid, the chosen one | concedes |
|---|---|---|---|---|
| **5** *(shipped)* | +0.000 | −0.618 ± 0.043 | **−10.050 ± 0.378** | **41.1%** |
| 8 | +0.000 | +0.243 ± 0.045 | −7.183 ± 0.369 | 36.3% |
| 10 | +0.000 | +1.060 ± 0.051 | −4.820 ± 0.366 | 32.4% |
| **12** | +0.000 | +2.112 ± 0.061 | −2.190 ± 0.363 | **29.0%** |
| 15 | +0.000 | +4.190 ± 0.077 | +2.103 ± 0.357 | 23.1% |
| 25 | +0.000 | +14.934 ± 0.111 | +15.827 ± 0.331 | 10.6% |

**The shade on the option actually being chosen crosses zero at temp ≈ 13.5, and
temp 12 puts the tree's concession rate at 29.0% — which is the price list's own
rate to the decimal.** Two independent routes landing on the same place is the
same pattern that first justified `DOUBLE_MARGIN = 20`.

**2. HOW MUCH IS LEGITIMATE — essentially NONE of it**, which is the finding
that changes what should be built (573 nodes where the tree bid; `settles here`
is an exact resolve of the chosen bid, `realised` an exact resolve of the
contract the auction actually reached, signed for the deciding seat):

| | |
|---|---|
| the tree shades the chosen bid by | **−9.969 ± 0.442** |
| **LEGITIMATE** (realised − settles here) | **−0.206 ± 0.855** — indistinguishable from zero |
| **EXCESS** (shade − legitimate) | **−9.763 ± 0.915** |

**Being outbid costs essentially nothing.** The standing worry — that a bid is
genuinely worth less than its settled value because the opponent can raise over
it, so correcting the shade would delete the lookahead — **is measured false**.
The mechanism is the game's own shape: the set base rises with the level, so
being raised over hands us a *better* defensive proposition, and the two roughly
cancel. Almost the whole −10 is bias.

**SO WHERE IS THE TREE'S MEASURED +1.19 OVER THE PRICE LIST?** Not in the
discount — that is zero. It must be in WHICH bid the tree picks and in the
capping play, not in WHETHER it bids. That is a coherent and testable split:
**the tree adds value choosing among bids and adds bias choosing between bidding
and passing.** Correcting the second need not cost the first.

**THEREFORE: DO NOT SHIP AN ADDITIVE CONSTANT.** Three reasons, all measured
here. The shade is not constant (−1.13 at standing 2, +0.02 at standing 6, where
the two pricers already agree on 100% of decisions, so a flat term is pure
damage there). The lever that moves it already exists and is already fitted. And
a constant would be a fourth tuning knob where a knob is already in the payload.

**THE IMPLEMENTATION IS THE EXISTING TEMPERATURE, GATED TO CONTESTED NODES.**
`opp_temp` is read per REQUEST, and the server knows whether a pass is legal at
this node because it built the option list — so a higher temperature can be sent
exactly where the asymmetry lives and the opening can keep its fitted 5. **No
new wire field, no Rust change, no wasm rebuild.** This is precisely the
isolating change this file already said was required and had never been built:
the recorded temp sweep (2/5/12 at n=150, +1.07/+0.99, "somewhere around 5–12,
not a tuned optimum") was UNGATED, and the file's own explanation for why
softening cancelled is that it *also lowered the opening across every bucket*.
Gating it separates the two effects for the first time.

**WHAT IS STILL NOT ESTABLISHED, and it is the whole ship question.** Every
number here is about the ESTIMATOR, not about strength. Zeroing the shade is not
self-evidently right — the price list concedes 29.0% and the *equilibrium*
concedes 0–5%, so both pricers may be conceding far too much and matching the
price list would only be matching a bidder the tree already beats. The gate is
unchanged: a CRN-paired arena at equal time, mirror exactly +0.0000, **watching
the settled distribution and make rate as well as payoff** — this file records
Experts already bidding each other past the making point, and a correction that
wins on points while pushing contracts up the ladder is buying strength the
game's shape says it should not keep.

**ONE ROW IS UNSTABLE AND IS THE ONE ALREADY FLAGGED AS CONFOUNDED.** The
flipped-decision row read −9.020 ± 1.816 on the first sample and −2.752 ± 1.758
on this one — same deals, different world draws (the six temp asks advance
`bidserve`'s per-request seed, so a later deal is determinized differently),
i.e. ~2.5 SE apart on nominally ±1.8 error bars. The shade rows are stable
across the same two samples (−10.222 vs −10.050 on the chosen bid; concession
44.4% vs 41.1%), which is the difference between a measurement and an artefact.
**Do not quote the flip row as a magnitude.**

### THE CONTESTED GATE: THE MECHANISM WORKS EXACTLY AS DESIGNED AND IT DOES NOT PAY (2026-08-20)

**Built, pre-registered, run to the declared n, and it stays OFF.**
`EXPERT_OPP_TEMP_CONTESTED = 12` softens the modelled opponent only at nodes
where a PASS is legal; the opening — the one node that cannot pass — keeps its
fitted 5. `expertsgt` vs shipped `expertst`, CRN-paired, dd-resolved:

**−0.4786 ± 0.3951 payoff/round, 95% CI [−1.253, +0.296], t = −1.21, n = 2900.**

**It does not ship, and the interesting part is that the sign FLIPPED on the way
there.** The pre-registered first read at n=800 was **+1.1938 ± 0.7555** and was
recorded as "promising, not established"; carried to the declared 2900 it is
mildly NEGATIVE. In blocks of 500:

| deals | 0–500 | 500–1000 | 1000–1500 | 1500–2000 | 2000–2500 | 2500–2900 |
|---|---|---|---|---|---|---|
| | **+2.62** | −1.08 | −1.93 | −0.88 | −1.47 | −0.04 |

**The entire positive reading was the first 500 deals**, and every block after it
is negative. This is the same lesson this file has now recorded five times
(+1.71 at n=300 → −0.28 at n=2250; −2.57 at n=196 → −0.68 at n=1550; a
`DOUBLE_MARGIN` peak that vanished on the next 320 deals) — and this time it
caught a result that had already been written down as encouraging. **The
pre-registration is what made that a correction rather than a shipped
regression.**

**AND THE MECHANISM DID EXACTLY WHAT IT WAS BUILT TO DO — which is now the
FIFTH time in this campaign that a confirmed mechanism has not paid.** At the
full 2900:

| | gated (12) | shipped (5) |
|---|---|---|
| **mean opening** | **2.46** | **2.48** |
| contracts declared | **3531** | 2269 |
| decisions that PASS | **21.4%** | 31.4% |
| mean settled level | **4.45** | 4.71 |
| settled at level 6 | **23%** | 30% |
| sacrifices | 14.0% | 12.4% |
| **made** | **58.7%** | **60.3%** |

**THE MAKE RATE IS THE ROW THAT EXPLAINS THE RESULT, AND IT FLIPPED WITH THE
SAMPLE** (60.1% vs 58.9% at n=800; 58.7% vs 60.3% at n=2900). The gate wins far
more auctions — 3531 contracts against 2269 — but the extra ones it buys are
MARGINAL: it makes fewer of them and sacrifices more. So the tree's pessimism
about contesting, although formally a bias by every measurement in the section
above, was suppressing decisions that were close to worthless. **A shade can be
a genuine estimator bias and still be suppressing nothing worth having.**

**THE OPENING IS UNMOVED TO WITHIN 0.02 OF A RUNG WHILE THE CONCESSION RATE
FALLS TEN POINTS.** That is the whole design goal, demonstrated: the ungated
2/5/12 sweep cancelled *because softening also lowered the opening across every
bucket*, and gating on "is a pass legal here" separates the two effects for the
first time. The level-6 pile-up this file has flagged since the 800-round
profile (28% settling at 6, 64% of those set) comes down to 22%, the settled
mean falls, and the make rate rises — so the correction is not buying points by
climbing the ladder.

**METHOD NOTE, AND IT IS THE EXPENSIVE ONE.** Per-deal σ measured **21.3**, not
the 18 the pre-registration budgeted with, so the declared first read at n=800
bought ±0.76 rather than ±0.64 — **the pre-registration under-powered itself.**
σ is a property of the ARM, not of the harness, and a new arm's σ must be
measured on its first shard rather than inherited from the last campaign.
**But the deeper lesson is that n=800 was never going to be enough at any σ:
at this harness's noise, an arena arm's minimum useful n is ~2000–3000, and
anything smaller can only produce a number that later gets corrected.** Declare
that up front or do not start the run.

**DOES A DIFFERENT TEMPERATURE HELP? PROBABLY NOT, AND THE REASON IS NOW
STRUCTURAL RATHER THAN A GUESS.** 12 was chosen because the shade crosses zero
at ≈13.5. Zeroing the shade turns out to be the wrong target: the marginal
contracts it buys are ones the bot makes less often, so pushing FURTHER (15, 20)
buys more of exactly what measured negative here. The old note that "the
equilibrium concedes 0–5%, so both pricers may still concede far too much"
survives only as a statement about the equilibrium — and this package already
measured that equilibrium's blueprint losing by **−12.84** as a bidder. **Read
this arm as closing the direction, not as one dose of it.** A further sweep
needs a new reason, not a new number.

**Verified before any number was taken**, and all three are the reason the
result can be attributed to one change: unarmed `expertsgt` vs `expertst` reads
**exactly +0.0000** (byte-identical when the gate is off), the armed mirror
reads **exactly +0.0000**, and armed it changes 13 of 14 auctions.
`test_the_contested_gate_softens_only_where_a_pass_is_legal` pins both ends and
is verified non-vacuous by defeating the gate.

### THE REAL ACTION SPACE: BUILT, CHEAP IN STATES, 51x IN SOLVER TIME (2026-08-20)

**The ReBeL direction, costed properly — and the cost is not where this file
said it was.** The standing finding was that the blueprint's binding constraint
is its ACTION space (no denominations, ladder capped at 8), not its hand space.
That is now built (`CFR_DENOMS`, off by default) and the arithmetic is measured
rather than inferred.

**THE STATE COUNT SAYS IT IS NEARLY FREE.** Enumerated exactly:

| abstraction | reachable states |
|---|---|
| levels only, no denominations | 58 |
| **+ real denominations** | **384** — 1.2x what `cfrlab` reaches today (321) |
| + the per-player FOREVER-BAN's `used` masks | **30,373** — 79x on top |

So denominations were never the expensive half. **The ban is**, and it alone
would want ~19M iterations against the 200k that converges here. **Dropping the
ban is measured, not assumed**: `cfrlab banned` put the pass rate at standing 4
at 44% whether the seat's best denomination was still free or not (9,032 probed
decisions), and the suit-priced ladder measured a same-level overtake costing
1.13 points of difficulty against a level's 1.00 while paying the same. The
rungs the ban withholds are rungs nobody wants.

**AND THE STATE COUNT IS THE WRONG COST MODEL, WHICH IS THE ACTUAL FINDING.**
External-sampling MCCFR samples ONE action at the opponent's node and evaluates
EVERY action at ours, so its per-iteration cost is driven by the branching
factor at our own nodes — not by how many distinct states exist. Measured in
separate processes:

| | opening actions | walk calls / iteration | ms / iteration |
|---|---|---|---|
| level-only (shipped) | 8 | **102** | 0.94 |
| real action space | 40 | **4,128** | **47.6** |

**40x the traversals and 51x the wall clock for 1.2x the states.** A converged
200k-iteration solve goes from ~3 minutes to **~2.6 hours per seed**, before
allowing that a 5x larger action set plausibly needs more iterations too.

**SO THE PREREQUISITE IS A CHEAPER CFR, AND THIS FILE ALREADY NAMED IT.** The
finer-ladder note says "converging it needs a cheaper CFR (outcome sampling) or
a real compute budget", and that is exactly right for the same reason: outcome
sampling draws OUR action as well, making per-iteration cost independent of the
branching factor. **Build that before running this arm**, or budget ~2.6 hours a
seed. Do not re-derive the state count and conclude it is cheap.

**WHAT IS COMMITTED.** `DENOMS` packs a bid as `level * 8 + rank` so every
existing reader that tests `a == -1` keeps working; `actions`/`_step`/`act_level`
/`act_rank` are the only new vocabulary; `leaf` needed NO change because it
already indexed the all-denomination cache by rank ("rank = holds"). The four
paths that still read an action as a bare level — `blueprint_bid`,
`best_response`, `_live_abstract_state`, `_path_to` — **refuse loudly** under
`CFR_DENOMS` rather than bidding level 41. With the flag off the `curve` output
is **byte-identical** to before the change.

**TWO INSTRUMENT BUGS, BOTH OF THE FAMILY THIS FILE KEEPS RECORDING.**
* **A control that only exercises the OFF path cannot catch an ON path that was
  never wired.** `str.replace(pat, new, 1)` patched the FIRST match — which was
  `jump_main`, not `curve_main` — so the playout that actually runs still read
  packed action codes as levels. It printed a full, plausible table: settled
  "levels" of 8..40, a settled mean of 23.33 and a make rate of 0.0%. The
  byte-identical control passed throughout, because with DENOMS off both copies
  are equivalent. **A duplicated function is not caught by a flag-off control.**
* **A module reload that does not re-read its env flag reports the null twice.**
  The first per-iteration benchmark deleted `sys.modules` entries and
  re-imported with `CFR_DENOMS` flipped, and reported **1.16x** — it had
  measured level-only both times, visible in hindsight as "infosets touched
  1,218 vs 1,354" when a real DENOMS run touches 40x more. Re-run in SEPARATE
  PROCESSES it is 51x. **Fork, do not reload, when a module reads its config at
  import.**

### THE OUTCOME SAMPLER WAS BIASED, AND EXTERNAL STILL WINS AT EQUAL TIME (2026-08-21)

The sampler landed 2026-08-20 explicitly marked NOT correct: on the level-only
abstraction it and external sampling converged to DIFFERENT equilibria, which is
the signature of a mis-weighted estimator rather than a slow one. Both halves of
that are now settled.

**THE BUG, AND THE INSTRUMENT THAT FOUND IT.** A convergence ladder can only say
THAT the two disagree — regret matching is a feedback loop, so a small weighting
error moves the strategy, which moves the next estimate, and nothing localises.
`tools/cfrcheck.py` asks the one question with an exact answer: freeze the
strategy at UNIFORM, and both samplers estimate `v(I,a) - v(I)`, which a tiny
game (`CFR_MAXL=3`, one deal) computes by enumeration. That property holds
independently of the dynamics. It read:

    external  mean |estimate - truth| / mean |truth| = 0.0021
    outcome   mean |estimate - truth| / mean |truth| = 0.7115

— decisive in one run, and it points at the weighting and nowhere else.

The defect was a `descend(a)` closure that captured the PARENT's `q`. The
recursive branch was entered with `q * probe[a]`, but a terminal reached by a
PASS was priced at plain `q`: the sampled action's own probability was missing
from exactly the outcomes that end the auction. Every such estimate came back
shrunk toward zero (worst infoset: 2.83 against a true 6.64). The fix is
structural rather than a patched line — **draw the action FIRST, compute
`nq`/`n_opp` ONCE above the branch, then build the child** — so a terminal and a
node cannot disagree about what has been sampled. `dbl_os` had the same omission
twice over (the pass never entered the defender's reach either).

After: 0.7115 -> 0.0187 at 400k iterations, and the residual is variance, not a
second bias — 0.0459 / 0.0187 / 0.0095 across 100k / 400k / 1.6M is a clean
`1/sqrt(n)` (4.83x over 16x).

**A GATE THAT RUNS, NOT A NOTE.** `tests/test_cfr_unbiased.py` is the checker as
a permanent test, on four hand-written deal records rather than the gitignored
research cache (a test that needs an artifact is a test that skips, which this
package forbids). It carries its own non-vacuity proof: a third test re-injects
the defect's SHAPE — a missing multiplicative factor in `1/q` — at a MILDER
constant than the real one, and asserts the band still catches it. The iteration
counts are per sampler and sized off five seeds, because their costs and
variances run in opposite directions: external ~0.005 at 60k, outcome
0.036–0.045 at 400k, one 0.10 band over both.

**AND THE COST RESULT DOES NOT SURVIVE AN EQUAL-TIME READING.** The 260x
per-iteration figure is real and unchanged. It is also the wrong axis. Solving
for real and pricing with the exact best response, on the level-only
abstraction:

      sampler     iters     solve      exploitability
      external     200k     170.9s               1.04
      outcome        1M      40.9s               6.58
      outcome        4M     163.1s               4.11

At matched wall clock external is **4x less exploitable**. Outcome sampling is
converging — 12.15 / 6.58 / 4.11 at 200k / 1M / 4M — just far slower per
iteration, which is the standard OS-MCCFR trade and not a defect. Its decay
fits `n^-0.36` against external's `n^-0.24`, and extrapolating both into the
`DENOMS` space (where external costs 51x more per iteration and outcome barely
changes) still favours external, narrowly. **So the sampler is correct, it is
kept, and it is NOT the automatic answer for the real action space** — this
repo's own equal-time rule applies to solvers exactly as it does to arenas.
What actually blocks pricing `DENOMS` is that `best_response` still reads
actions as bare levels and refuses to run; that port, not the sampler, is the
next thing standing between here and a number.

### OUTCOME SAMPLING LOSES BY *MORE* IN THE SPACE IT WAS BUILT FOR (2026-08-21)

Follow-on from the bias fix above, and it closes the sampler question rather
than merely qualifying it. `best_response` is now abstraction-agnostic (it
routes every transition through `_step`), so the real action space can finally
be PRICED, and the equal-time comparison runs where it always should have.

**`DENOMS`, 600 all-denomination deals, exact best response:**

      sampler      iters     solve     exploitability
      external        2k     63.7s               9.97
      external        5k    131.4s               6.76
      external       19k    351.6s               4.27
      outcome       100k     12.7s              44.97
      outcome       500k     64.4s              37.83
      outcome       4.7M    641.7s              25.79

At ~64 seconds external reads 9.97 against outcome's 37.83; at ~640 it is
roughly 3.3 (extrapolated from 4.27 at 352s) against 25.79. **External is
3.8x better at the small budget and ~8x at the large one, and the gap WIDENS.**
External at TWO THOUSAND iterations beats outcome at a hundred thousand.

**AND THAT REVERSES THE EXTRAPOLATION, WHICH IS THE lesson worth keeping.** The
level-only reading (external 1.04 vs outcome 4.11 at matched time) plus the
measured 51x cost gap suggested the two would be near-even here. They are not
close. The extrapolation assumed each sampler's exploitability-vs-iterations
curve TRANSFERS between abstractions, and outcome sampling's does not: widening
the action space 5x costs external only per-iteration TIME, but it costs
outcome sampling VARIANCE -- each infoset is visited a fifth as often per
trajectory and every `1/q` weight grows. Its cost advantage is real and its
statistical efficiency degrades faster than the advantage buys back. **A
per-iteration cost ratio is not a convergence ratio, and fitting a decay curve
in one abstraction says nothing about another.**

**WHAT THIS MEANS FOR THE SAMPLER.** It is correct, it is gated
(`tests/test_cfr_unbiased.py`), and it stays -- it is the right tool if the
action space ever grows to where external's per-node branching is genuinely
unaffordable (the FOREVER-BAN's 30,373 states, say). It is NOT the answer for
`DENOMS`, and `CFR_SAMPLING` should stay on `external` for everything this
campaign currently measures. Do not re-open it on the strength of the 260x.

### THE LEVEL-ONLY ABSTRACTION IS 14 POINTS MORE EXPLOITABLE (2026-08-21)

The question the whole `DENOMS` arm exists for, finally asked properly.

**WHY IT COULD NOT BE ASKED BEFORE, and it is not the reason I assumed.** Two
exploitability numbers from two abstractions cannot be compared: exploitability
is only defined against a best responder, and the two abstractions hand the
responder different action sets, so they are numbers from different games.
Ranking them is meaningless. What was needed was ONE game and ONE responder.

**THE EMBEDDING IS EXACT, WHICH IS WHAT MAKES IT POSSIBLE.** The level-only
game is a strict SUB-GAME of the wide one, not an approximation:

    pass            -> pass
    HOLD            -> the SAME level at rank `holds + 1`
    raise to `L`    -> level `L` at rank 0

`leaf` already prices a contract as "rank = holds", and level-only's `_step`
resets `holds` on a raise and increments it on a HOLD -- so a level-only state
`(level, prev, holds)` and a wide state `(level, prev, rank)` with
`rank == holds` are THE SAME CONTRACT at THE SAME PAYOFF. The lift is a
relabelling. `tools/liftlab.py` does it; `tests/test_lift_is_faithful.py`
PROVES it, by the one identity that settles the matter: restrict the wide
responder to the lift's image and the exact best response must come back at the
level-only value to floating point. It does. The test also asserts the two
things that would make that identity worthless -- that handing the responder
the full denomination set MOVES the number (and never downward, since a larger
action set cannot do worse), and that a one-character mis-lift is caught.

**THE RESULT, at matched wall clock (324s vs 343s), 600 all-denomination
deals:**

      policy                 backoff   BR seat 0   BR seat 1   exploitability
      level-only, LIFTED       False       14.73       19.07            16.90
      level-only, LIFTED        True       15.93       19.33            17.63
      wide (native)            False        5.23        2.05             3.64
      wide (native)             True        5.23        2.05             3.64

**A 14.0-point gap in exploitability.** And it is not a convergence artifact in
either direction: 2.5x the level-only iterations moved it 21.33 -> 17.63 while the
wide arm sat at 3.64, so the narrow policy is converging toward something well
above the wide one, not merely under-solved.

**WHAT THIS NUMBER IS, AND FOUR THINGS IT IS NOT.** Written down because the
shorthand "a 14-point prize" is wrong in four different ways, and I used it
repeatedly in conversation before writing this paragraph.

It **is** the difference in EXPLOITABILITY -- how much an exact best responder
wins, in payoff points a deal -- between two CFR blueprints solved on the same
deals and priced by the same responder in the same game.

* **NOT a gain the shipped bot would make.** Neither policy here is the shipped
  bot. Expert is a search-based tree bidder that uses no blueprint at all, and
  the blueprint LOST to Expert by **−12.84 ± 1.47** a round.
* **NOT comparable to "floor 1.47 / Hard 5.45 / Expert 5.70".** Those were
  measured in the NARROW game, against a NARROW responder, on a different deal
  cache. Setting 17.63 beside 5.70 is precisely the abstraction-mixing error
  this whole measurement was built to avoid.
* **NOT a strength claim.** This campaign has measured exploitability and
  head-to-head strength close to INDEPENDENT in this game -- the Diverse arm was
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
this is a reason to look here -- not a result.**

**READ THE BACKOFF ROWS, NOT THE NO-BACKOFF ONES.** `Policy`'s docstring
records why an unseen infoset conceding makes a number "mostly the sample
size", and the lifted policy is structurally the one with holes (12.9% of
reach-weighted lookups). That is the artifact that would manufacture exactly
this answer, so it was checked rather than argued: with backoff on, the holes
close and the gap gets BIGGER (16.90 -> 17.63). Coverage was flattering the
narrow arm, not damning it.

**THIS IS THE SAME DEFECT THE HEAD-TO-HEAD ALREADY SAW, from the other end.**
The blueprint lost to Expert by **-12.84 +- 1.47** and the mechanism was one
number: it made **49.6%** of its contracts against Expert's **73.0%** at the
same levels -- because a level chosen blind to the suit is a commitment the
real hand may not support. That was inferred from a play-out; this measures it
directly against a best responder. The two figures are close and the
correspondence is suggestive, but they are NOT the same quantity (points a deal
against an exact responder vs points a round against Expert) and should not be
quoted as one number.

**WHAT THIS UNBLOCKS AND WHAT IT DOES NOT.** It says the widened action space
is where the auction's remaining money is, which is the first positive result
this campaign has had after a long run of nulls (eval weights, exact leaf,
trump channel, contested gate, diverse continuations). It does NOT yet ship
anything: `blueprint_bid` and `_path_to` still refuse under `DENOMS`, because
serving needs to map an abstract action back onto a REAL bid -- a new mapping,
not a transition `_step` already owns. That port is the next step, and unlike
every other item on the list this one points at a structural gap of a MEASURED
SIZE. Not at a priced gain -- read the four caveats above before quoting the
number.

### THE TWO ARCHITECTURAL REWRITES, PARKED WITH THEIR REASONS (noted 2026-08-20)

Neither is scheduled. They are here because the question "should this be a
neural net or an MCTS" now has a measured answer for the ARCHITECTURE THIS GAME
ALREADY HAS, and the answer is no — so anyone returning to it should know which
two things were NOT ruled out, and why they are different in kind.

**WHAT WAS RULED OUT, so it is not re-argued.** A net cannot help the CARD-PLAY
leaf: that leaf is an exact double-dummy solve, and every other game in this
repo carries a net precisely because its leaf cannot be solved. A net there buys
only SPEED, speed buys WORLD COUNT, and world count is measured at its stop
(`pimc:24` vs `pimc:8` reads 50.0%; `pimc:32` over `pimc:8` is +0.21 for four
times the compute). MCTS fails for the mirror reason — it is what you reach for
when you cannot solve, and here a world solves exactly in ~20–74ms. And the
prize is small either way: **89.5% of card decisions are already exactly
optimal**, the whole oracle gap is 0.79 pts/round on a 5-point pool, CAMPAIGN.md
reads most of that as irreducible, and IIMC — the correct tool for the reducible
part — measured **+0.067 ± 0.053**. In the AUCTION a net is an eval, and the
exact leaf (`threat_value`, the best evaluation obtainable) measured null twice.

**WHAT THAT LEAVES.** Both survivors replace the whole approach rather than a
component, which is why neither is refuted by anything above.

* **R-NaD / DeepNash. NOT RUNNABLE IN THIS CONTAINER, and here is exactly what
  it would need** (checked 2026-08-20): 4 CPU cores, 15GB RAM, **no GPU, and
  neither torch, numpy, jax nor scipy installed**. R-NaD is model-free deep RL
  over millions of self-play games; it needs a GPU box, a DL framework, and the
  auction+play loop exposed as a stepped RL environment (the Rust engine is the
  simulator but has no such API). None of that is a judgement about the method —
  it is the one candidate here with a plausible route to a STEP change — and all
  of it is why nothing about it can be measured on this machine. It is the only
  method on the survey's list that took a
  two-player zero-sum imperfect-information game of this size to top-human, and
  it uses NO SEARCH — regularised Nash dynamics, model-free, over millions of
  self-play games. It is the only candidate with a plausible route to a STEP
  change rather than another tenth of a point. Two things here make it less
  far-fetched than it sounds: the Rust engine is already a fast simulator, which
  is the usual blocker, and **CoC already proves this repo can serve a fetched
  `.bin` model client-side**, so the serving path exists. The cost is weeks to
  months of training compute against a Hard tier whose whole edge over greedy is
  +1.10 pts/round — disproportionate for this site, which is why it is parked
  and not scheduled.
* **ReBeL.** Better SUITED in principle than anywhere it has been applied: its
  hard part is a value function over public belief states at a depth limit, and
  this game's leaf is *exactly solvable and cached per hand*, which is the part
  that makes it expensive elsewhere. It is the natural successor to the
  blueprint arm that failed — poker's own answer to "the abstraction is too
  coarse to ship" was to make the blueprint a SEED and re-solve the real subgame
  at decision time, which is exactly what `cfrlab`'s blueprint never did.

**IF EITHER IS PICKED UP, the gate is unchanged and is the lesson of this whole
campaign: a CRN-paired arena at equal time, mirror reading exactly +0.0000.**
Not exploitability — two independent arms measured exploitability and
head-to-head strength close to INDEPENDENT in this game, and the blueprint that
scored near the abstraction's floor lost by −12.84 a round.

* **Announcements beyond Sharp.** `auction_payoff_options` enumerates Sharp but
  never Open, and the multiplier is priced without modelling the extra risk.
* ~~**The Expert tier's leaf is still a points solve, and that is where the
  next effort belongs.**~~ **BUILT AND MEASURED 2026-08-19 — it is exact, it
  costs 2.1x rather than the per-contract solve this bullet assumed, and it
  moves exploitability not at all (6.01 -> 6.21 on 200 paired rounds).** Off
  behind `DIS_EXACT_LEAF`; see the section above. Do not re-open it as "the next
  effort" — what the exploitability measurement points at is that Expert's
  opening barely varies with its hand, which is a CONDITIONAL defect no leaf
  accuracy can touch.
* ~~**Skat's talon swap still runs the OLD take-high/give-low rule.**~~
  **DONE 2026-08-21 — it got its own `swaplab` run and its own fit, never
  classic's weights, and it is worth +4.086 ± 0.183 a round.** See "Skat's
  talon is fitted too, and the FIRST fit was better and shipped nothing" below.
* ~~**Modelling the opponent's UNCERTAINTY in the auction tree.**~~ **BUILT AND
  MEASURED 2026-08-20 — it is the SIXTH null.** `View::belief_of` /
  `bid::belief_into` / `OppModel::Belief` are correct, tested and shipped at
  `DIS_BELIEF_W = 0`; paired on 200 seeds it reads 5.43 against 5.25 and takes
  the make rate from 69.5% to 49.0%. See the section above, and do not re-open
  it as "the live direction" — the mechanism exists and the measurement is the
  answer.
* A `/review`.