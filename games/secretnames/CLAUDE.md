# SecretNames — Claude Context

Codenames: Duet. **Two players, cooperative, no bot.** 25 words in a 5×5 grid, two
private key cards, 15 unique agents, 9 timer tokens, then sudden death.

| File | What it owns |
|---|---|
| `engine.py` | ALL the rules. Pure: no FastAPI, no DB, no randomness past `new_game` |
| `words.py` | the 399-word deck (`deal_words`) — data, not rules |
| `main.py` | the room server, mounted at `/secretnames` |
| `persist.py` | at-rest compaction (the key vocabulary; there is no rng to pack) |
| `SecretNames.jsx` / `.css` | the lobby, the board, the console, the rail |
| `rules.jsx` | the words in the shared How-to-play modal |

---

## THE INVERSION — the one thing to get right

**A player's key card says what happens when THE OTHER PLAYER guesses.** Seat 0 holds
side A; side A is the answer sheet for seat 1's guesses. So every guess resolves as

```python
role = keys[1 - guesser_seat][pos]        # engine.resolve_role, the only site
```

which is the same thing as "resolve against the CLUE-GIVER's key", because during an
ordinary turn the guesser is always the other seat. Resolving against the guesser's own
key produces a game that runs, logs, persists, plays and is a **different game** — no
test that only drives one seat can see it, which is why `tests/test_engine.py` checks
both directions explicitly and why `screens.mjs`'s `secretNamesPlay` drives two real
browsers and clicks a word chosen from the *other* page's key.

**15 unique agents, not 18.** 9 + 9 with exactly 3 shared. Finishing all nine on one
side does **not** win; it only means that player stops giving clues (§17).

---

## Rules facts that are easy to get wrong

- **A turn costs exactly ONE timer token**, however many correct guesses were made. A
  correct guess costs nothing. `_end_normal_turn` is the only place the counter moves.
- **The clue number does NOT cap the guesses.** There is no "number + 1" rule in Duet —
  that is the base game. The guesser may keep going while they keep being right, using
  any earlier clue, not just this turn's.
- **A bystander is player-relative and does NOT remove the word.** It ends that turn and
  is recorded in `bystanders[seat]`; the same position may still be an agent from the
  other direction, and the other player will have to find it.
- **Running out of tokens does not lose.** It enters `sudden_death`: no new clues, either
  player may guess one at a time, and any non-agent ends the game.
- **Passing costs no token.** It permanently retires that seat from clue-giving and hands
  the CURRENT turn to the other player; if neither can clue, sudden death starts
  immediately with tokens still on the table.
- **A win is immediate** and consumes no token.

---

## Hidden information

`keys` is the only secret and it is per-seat. `engine.player_view` BUILDS the payload
from the public fields plus the viewer's own side, rather than copying the game dict and
deleting things — a field added to the game dict is absent from the wire until someone
puts it in the view. `main.mk_room_state` is rebuilt per recipient for the same reason; a
single shared payload would hand both key cards to both players and look completely
normal from either seat.

What is genuinely PUBLIC, and is broadcast in full because both players are looking at
one grid in the physical game:

- `bystanders[0]` and `bystanders[1]` — a token on the table. A bystander for the other
  player is a fact about YOUR key, which you already hold.
- `exhausted` — a boolean at zero per seat. §17 makes it observable anyway (the
  clue-giver stops alternating). It is never a remaining COUNT.
- `your_agents_left` goes to that seat only. There is no field anywhere carrying the
  OTHER seat's remaining agents or assassins (§20).
- `reveal` (both sides) exists **only** once `phase` is `won`/`lost`.

---

## No bot, and no `rng_state`

**No AI opponent.** A bot would have to give and read semantic clues over an arbitrary
25-word board — a word-association model, not a search, and nothing in `rust-cores/` or
the shared AI stack is shaped for it. Where Wolf? is the precedent. The shared AI rosters
(`shared/tests/test_ai_difficulty_memory.py`, `test_lobby_bot_tier.py`) derive themselves
from the tree, so this game drops out on its own and joins them the day it gains a
ladder. Do not add `ai_difficulty` to the create message as a placeholder.

**Nothing draws randomness after the deal** — words, key card and who opens are all spent
in `new_game`. So no `rng_state` is persisted (the Where Wolf? shape, not the Spender
one): 625 words of incompressible Mersenne noise would have been the largest single item
in the row for something nothing reads. `test_nothing_after_the_deal_draws_randomness`
booby-traps the stdlib RNG and plays a turn, so a future draw fails loudly.

---

## Frontend notes

- **The word's type scale is `100cqw / --len`**, where `--len` is the longest
  whitespace-separated token. The constant is MEASURED, not guessed: Cinzel's uppercase
  advance is 0.835em per character averaged and 0.867em for the widest letter mix, and
  the first guess written into the sheet was 0.72 — wrong by 16%, which is how a layout
  comes to fit by 1px. 389 of the deck's 399 words then sit on one line at phone width;
  the ten that do not are all 10+ letters. `overflow-wrap:anywhere` is the safety net, so
  a wrong constant costs a second line and never an overflow.
- **`.sn-card{display:block}` and `.sn-flip{display:block}` are load-bearing.** The card
  is a `<button>` and the flipper is a `<span>` (a `<div>` in phrasing content is invalid
  HTML); without `display:block` the flipper is an inline box, `width`/`height` do not
  apply, and the absolutely positioned faces resolve `inset:0` against an inline
  fragment. The tell was a word overflowing by the SAME 49px at 1440 and 2560.
- **`.sn-progress` must not carry a `flex` shorthand.** Its parent `.sn-metric` is a
  COLUMN flex container, so a flex basis there is a HEIGHT — `flex:1 1 140px` rendered
  the 7px bar as a 130px blob.
- The phone console is `position:sticky` at the bottom with an OPAQUE background: the
  board scrolls under it, and the translucent desktop value let the last row of the grid
  read straight through the clue input.
- `lang="en"` sits on the word span, not on the document, so `hyphens:auto` has a
  language to resolve against without changing line breaking on eight other screens.

## Gates

- `tests/test_engine.py` — all 26 cases the specification lists, plus clue legality, a
  200-deal random walk, and the no-RNG trap. Positions are built by WRITING the key card
  (`_rigged` asserts it is legal), never by hunting a seed: a "find a seed where…" helper
  either loops or bails, and a bail is a green tick over nothing.
- `tests/test_ws_auth.py` — seat binding, and a payload check on every path that sends a
  room.
- `webapp/test/screens.mjs` → `secretNamesPlay` (lane B) — two browser contexts, one
  table. It is the only block in that file driving two clients, and it has to be.
