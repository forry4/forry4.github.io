"""SecretNames rules — the single source of truth.

Pure Python: no FastAPI, no DB, no sockets, no randomness beyond the ``rng``
handed to :func:`new_game`. ``main.py`` validates every client action through
here and stores the dict this module returns.

═══ THE INVERSION ═══════════════════════════════════════════════════════════
A player's key card says what happens when THE OTHER PLAYER guesses. Seat 0
holds side A, seat 1 holds side B — and side A is the answer sheet for seat 1's
guesses. So:

    role = keys[1 - guesser_seat][pos]

and equivalently ``keys[clue_giver][pos]``, because the guesser is always the
other seat during an ordinary turn. Resolving against the guesser's own key
produces a game that runs, logs, persists and plays — and is a different game.
:func:`resolve_role` is the ONE place this is written down, and every caller
goes through it.

═══ WHAT IS PUBLIC AND WHAT IS NOT ══════════════════════════════════════════
``keys`` is the only secret, and it is per-seat: :func:`player_view` ships the
viewer's own side and NOTHING of the other's until the game is over. Everything
else in the dict is genuinely shared — in the physical game both players look at
one grid, so a bystander token placed by either player is on the table for both
to see, and so is the fact that one player has run out of agents to clue (that
is exactly what §17's "the other player gives every remaining clue" makes
observable). ``bystanders`` and ``exhausted`` are therefore broadcast in full,
and neither leaks: a bystander for the OTHER player is a fact about YOUR key,
which you already hold.

The counts a player may NOT learn are the other seat's remaining agents and its
assassins. Nothing in the view carries either.

═══ NO ``rng_state`` ════════════════════════════════════════════════════════
All of this game's randomness is spent in :func:`new_game` — the words, the key
card and who clues first. Nothing draws again, so there is no RNG to persist,
which is the Where Wolf? shape rather than the Spender one. 625 words of
incompressible Mersenne noise per save would have been the largest single item
in the row (it measured 90% of a Where Wolf blob) for something no code path
reads. ``tests/test_engine.py`` plays a full game with the stdlib RNG booby
trapped, so a future draw cannot be added here without the test saying so.
"""
from __future__ import annotations

import re
from typing import Any

from .words import BOARD_SIZE, deal_words

AGENT = "agent"
BYSTANDER = "bystander"
ASSASSIN = "assassin"

#: Unique agent positions across both key sides. The win condition, and the
#: number this whole game is about — it is NOT 9 + 9.
TOTAL_AGENTS = 15

#: Timer tokens. 9 is the standard game; the two longer ladders are the
#: published easier settings (spec §4) and are the only thing the create modal
#: chooses.
DEFAULT_TURNS = 9
TURN_OPTIONS = (9, 10, 11)

CLUE_MAX_LEN = 24
CLUE_NUMBER_MAX = 9

# THE KEY-CARD COMPOSITION (spec §2), written as the pair distribution rather
# than as two independent sides, because the sides are not independent: the
# overlap is what makes 9 + 9 come to 15 unique agents with exactly 3 shared.
# Generating each side separately and hoping the union lands on 15 is the
# obvious wrong implementation and cannot be made to work.
#
#   (side A role, side B role) -> how many of the 25 positions
KEY_COMPOSITION: tuple[tuple[tuple[str, str], int], ...] = (
    ((AGENT, AGENT), 3),
    ((AGENT, BYSTANDER), 5),
    ((BYSTANDER, AGENT), 5),
    ((AGENT, ASSASSIN), 1),
    ((ASSASSIN, AGENT), 1),
    ((ASSASSIN, ASSASSIN), 1),
    ((ASSASSIN, BYSTANDER), 1),
    ((BYSTANDER, ASSASSIN), 1),
    ((BYSTANDER, BYSTANDER), 7),
)
assert sum(n for _, n in KEY_COMPOSITION) == BOARD_SIZE


# ─── Setup ───────────────────────────────────────────────────────────────────
def make_key_card(rng) -> list[list[str]]:
    """A valid two-sided key: ``[sideA, sideB]``, each 25 roles long.

    Shuffle the POSITIONS and hand them out to the pair buckets above. Every
    generated key satisfies the published composition by construction rather
    than by rejection sampling, so this cannot loop and cannot produce a board
    that is subtly off.
    """
    positions = list(range(BOARD_SIZE))
    rng.shuffle(positions)
    side_a = [BYSTANDER] * BOARD_SIZE
    side_b = [BYSTANDER] * BOARD_SIZE
    cursor = 0
    for (role_a, role_b), count in KEY_COMPOSITION:
        for pos in positions[cursor:cursor + count]:
            side_a[pos] = role_a
            side_b[pos] = role_b
        cursor += count
    return [side_a, side_b]


def agent_positions(keys: list[list[str]]) -> list[int]:
    """The 15 positions that are an agent on at least one side."""
    return sorted(i for i in range(BOARD_SIZE)
                  if keys[0][i] == AGENT or keys[1][i] == AGENT)


def new_game(seats: list[str], names: dict[str, str] | None = None, *,
             rng, turns: int = DEFAULT_TURNS) -> dict[str, Any]:
    """A fresh board. ``seats`` is exactly two player ids; seat 0 holds side A."""
    if len(seats) != 2:
        raise ValueError("SecretNames is a two-player game")
    turns = turns if turns in TURN_OPTIONS else DEFAULT_TURNS
    keys = make_key_card(rng)
    game: dict[str, Any] = {
        "seats": list(seats),
        "names": dict(names or {pid: pid for pid in seats}),
        "words": deal_words(rng),
        "keys": keys,
        "found": [],
        # Indexed by the seat that GUESSED it, which is the half that matters:
        # a bystander is player-relative, so the same position can be a dead end
        # for one seat and an agent the other seat still has to find.
        "bystanders": [[], []],
        "turns_remaining": turns,
        "turns_max": turns,
        # Either player may open (spec §4). Drawn here rather than fixed at seat
        # 0 so two players who always sit in the same order do not always get
        # the same job.
        "clue_giver": rng.randrange(2),
        "clue": None,
        "clues": [],
        "guesses_this_turn": 0,
        "passed": [False, False],
        "phase": "clue",
        "loss_reason": None,
        # Where the game ended, for the result screen's reveal. Only ever set
        # once the game is already over, so it cannot leak mid-play.
        "fatal_pos": None,
        "log": [],
    }
    _log(game, f"{_name(game, game['clue_giver'])} gives the first clue.",
         kind="turn", seat=game["clue_giver"])
    return game


# ─── Small readers ───────────────────────────────────────────────────────────
def seat_of(game: dict, pid: str) -> int | None:
    try:
        return game["seats"].index(pid)
    except (ValueError, KeyError, AttributeError):
        return None


def _name(game: dict, seat: int) -> str:
    pid = game["seats"][seat]
    return game.get("names", {}).get(pid, pid)


def _log(game: dict, text: str, *, kind: str = "note", seat: int | None = None,
         pos: int | None = None) -> None:
    game["log"].append({"k": kind, "t": text, "seat": seat, "pos": pos})


def is_over(game: dict | None) -> bool:
    return bool(game) and game.get("phase") in ("won", "lost")


def guesser(game: dict) -> int:
    """The seat that guesses during an ordinary turn — always the other one."""
    return 1 - game["clue_giver"]


def resolve_role(game: dict, guesser_seat: int, pos: int) -> str:
    """THE INVERSION, in one place. A guess is answered by the OTHER seat's key."""
    return game["keys"][1 - guesser_seat][pos]


def agents_left_for(game: dict, seat: int) -> list[int]:
    """Agents still to be found on ``seat``'s own key — i.e. the words that seat
    still has something to clue about. Private to that seat (spec §20)."""
    found = set(game["found"])
    return [i for i in range(BOARD_SIZE)
            if game["keys"][seat][i] == AGENT and i not in found]


def can_clue(game: dict, seat: int) -> bool:
    return not game["passed"][seat] and bool(agents_left_for(game, seat))


def all_found(game: dict) -> bool:
    return len(game["found"]) >= TOTAL_AGENTS


# ─── Turn machinery ──────────────────────────────────────────────────────────
def _choose_next_clue_giver(game: dict) -> None:
    """Spec §29. Alternate — unless one side can no longer clue, in which case
    the other gives every remaining clue, and if neither can, sudden death."""
    a_ok, b_ok = can_clue(game, 0), can_clue(game, 1)
    if not a_ok and not b_ok:
        _enter_sudden_death(game, "Neither player can give another clue.")
        return
    if not a_ok:
        game["clue_giver"] = 1
    elif not b_ok:
        game["clue_giver"] = 0
    else:
        game["clue_giver"] = 1 - game["clue_giver"]
    game["phase"] = "clue"
    _log(game, f"{_name(game, game['clue_giver'])} gives the next clue.",
         kind="turn", seat=game["clue_giver"])


def _enter_sudden_death(game: dict, why: str) -> None:
    game["phase"] = "sudden_death"
    game["clue"] = None
    game["guesses_this_turn"] = 0
    _log(game, f"{why} Sudden death — every remaining agent, no more clues.",
         kind="sudden")


def _win(game: dict) -> None:
    game["phase"] = "won"
    game["clue"] = None
    _log(game, "All 15 agents identified. The team wins.", kind="won")


def _end_normal_turn(game: dict) -> None:
    """Spec §28. Exactly ONE timer token, however many correct guesses were made."""
    game["turns_remaining"] -= 1
    game["clue"] = None
    game["guesses_this_turn"] = 0
    if all_found(game):
        _win(game)
        return
    if game["turns_remaining"] <= 0:
        _enter_sudden_death(game, "The last timer token is spent.")
        return
    _choose_next_clue_giver(game)


# ─── Moves ───────────────────────────────────────────────────────────────────
# Most clue legality is semantic and is left to the players (spec §7); what IS
# mechanical is checked here. A clue is one token (two are allowed for a proper
# name, which is the optional rule most groups play), it is short enough to be a
# word, and it may not simply BE a board word that is still uncovered.
_CLUE_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9'.\-]*(?: [A-Za-z0-9'.\-]+)?$")


def _apply_clue(game: dict, seat: int, move: dict) -> tuple[bool, str | None]:
    if game["phase"] != "clue":
        return False, "not waiting for a clue"
    if seat != game["clue_giver"]:
        return False, "you are not the clue-giver this turn"
    word = str(move.get("word") or "").strip()
    if not word:
        return False, "a clue needs a word"
    if len(word) > CLUE_MAX_LEN:
        return False, f"a clue is at most {CLUE_MAX_LEN} characters"
    if not _CLUE_RE.match(word):
        return False, "a clue is one word (two for a proper name), letters and digits"
    found = set(game["found"])
    uncovered = {game["words"][i].upper() for i in range(BOARD_SIZE) if i not in found}
    if word.upper() in uncovered:
        return False, "that word is still on the board"
    try:
        number = int(move.get("number"))
    except (TypeError, ValueError):
        return False, "a clue needs a number"
    if not 0 <= number <= CLUE_NUMBER_MAX:
        return False, f"the clue number is 0 to {CLUE_NUMBER_MAX}"

    game["clue"] = {"word": word, "number": number}
    game["clues"].append({"seat": seat, "word": word, "number": number,
                          "token": game["turns_remaining"]})
    game["guesses_this_turn"] = 0
    game["phase"] = "guess"
    _log(game, f"{_name(game, seat)}: {word} {number}", kind="clue", seat=seat)
    return True, None


def _apply_guess(game: dict, seat: int, move: dict) -> tuple[bool, str | None]:
    phase = game["phase"]
    if phase not in ("guess", "sudden_death"):
        return False, "no guessing right now"
    if phase == "guess" and seat != guesser(game):
        return False, "it is not your turn to guess"
    try:
        pos = int(move.get("pos"))
    except (TypeError, ValueError):
        return False, "which word?"
    if not 0 <= pos < BOARD_SIZE:
        return False, "no such word"
    if pos in set(game["found"]):
        return False, "that agent is already found"

    word = game["words"][pos]
    role = resolve_role(game, seat, pos)
    who = _name(game, seat)

    if role == ASSASSIN:
        game["phase"] = "lost"
        game["loss_reason"] = "assassin"
        game["fatal_pos"] = pos
        game["clue"] = None
        _log(game, f"{who} contacts {word} — an assassin. The mission is over.",
             kind="assassin", seat=seat, pos=pos)
        return True, None

    if role == BYSTANDER:
        if phase == "sudden_death":
            game["phase"] = "lost"
            game["loss_reason"] = "sudden_death_mistake"
            game["fatal_pos"] = pos
            _log(game, f"{who} contacts {word} — a bystander, in sudden death. "
                       "The mission is over.", kind="bystander", seat=seat, pos=pos)
            return True, None
        if pos not in game["bystanders"][seat]:
            game["bystanders"][seat].append(pos)
        _log(game, f"{who} contacts {word} — a bystander. The turn ends.",
             kind="bystander", seat=seat, pos=pos)
        _end_normal_turn(game)
        return True, None

    # AGENT — covered globally, for good, for both players.
    game["found"].append(pos)
    game["found"].sort()
    _log(game, f"{who} finds an agent at {word}.", kind="agent", seat=seat, pos=pos)
    if all_found(game):
        _win(game)
        return True, None
    if phase == "guess":
        game["guesses_this_turn"] += 1
    return True, None


def _apply_end_turn(game: dict, seat: int) -> tuple[bool, str | None]:
    if game["phase"] != "guess":
        return False, "there is no turn to end"
    if seat != guesser(game):
        return False, "only the guesser can end the turn"
    if game["guesses_this_turn"] < 1:
        return False, "make at least one guess first"
    _log(game, f"{_name(game, seat)} stops there.", kind="end", seat=seat)
    _end_normal_turn(game)
    return True, None


def _apply_pass(game: dict, seat: int) -> tuple[bool, str | None]:
    """Spec §18. Permanently give up clue-giving. Costs no timer token: passing
    is not the guessing turn, it hands the CURRENT turn to the other player."""
    if game["phase"] != "clue":
        return False, "you can only pass instead of giving a clue"
    if seat != game["clue_giver"]:
        return False, "you are not the clue-giver this turn"
    if game["passed"][seat]:
        return False, "you have already passed"
    game["passed"][seat] = True
    _log(game, f"{_name(game, seat)} passes, for the rest of the game.",
         kind="pass", seat=seat)
    other = 1 - seat
    if can_clue(game, other):
        game["clue_giver"] = other
        game["phase"] = "clue"
        _log(game, f"{_name(game, other)} gives the clue.", kind="turn", seat=other)
    else:
        _enter_sudden_death(game, "Neither player can give another clue.")
    return True, None


def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    """The one entry point ``main.py`` calls. Returns ``(ok, error)``.

    Every action is re-validated here against the server's own state: the client
    says WHICH word, never what it turned out to be (spec §31).
    """
    if not isinstance(game, dict):
        return False, "no game"
    if is_over(game):
        return False, "the game is over"
    seat = seat_of(game, pid)
    if seat is None:
        return False, "not a player in this game"
    kind = (move or {}).get("type")
    if kind == "clue":
        return _apply_clue(game, seat, move)
    if kind == "guess":
        return _apply_guess(game, seat, move)
    if kind == "end_turn":
        return _apply_end_turn(game, seat)
    if kind == "pass":
        return _apply_pass(game, seat)
    return False, "unknown action"


def abandon(game: dict, pid: str) -> None:
    """A seat leaves for good. The game is cooperative, so there is no winner to
    award it to — the run simply ends."""
    if not isinstance(game, dict) or is_over(game):
        return
    seat = seat_of(game, pid)
    game["phase"] = "lost"
    game["loss_reason"] = "abandoned"
    game["clue"] = None
    _log(game, f"{_name(game, seat) if seat is not None else pid} left the mission.",
         kind="abandon", seat=seat)


# ─── The wire view ───────────────────────────────────────────────────────────
def player_view(game: dict | None, pid: str | None) -> dict | None:
    """What one client is allowed to know.

    PER-FIELD, not "everything minus a couple of keys": the payload is BUILT
    from the public fields and the viewer's own side, so a field added to the
    game dict is absent from the wire until somebody puts it here. The repo has
    paid three times for the other arrangement — `mk_room_state` copies that
    leaked `decks`, `deck` and `rng_state` in three different games.
    """
    if not isinstance(game, dict):
        return None
    seat = seat_of(game, pid) if pid is not None else None
    over = is_over(game)
    return {
        "seats": list(game["seats"]),
        "names": dict(game.get("names", {})),
        "words": list(game["words"]),
        "found": list(game["found"]),
        "bystanders": [list(game["bystanders"][0]), list(game["bystanders"][1])],
        "turns_remaining": game["turns_remaining"],
        "turns_max": game["turns_max"],
        "clue_giver": game["clue_giver"],
        "guesser": guesser(game),
        "clue": dict(game["clue"]) if game.get("clue") else None,
        "clues": [dict(c) for c in game["clues"]],
        "guesses_this_turn": game["guesses_this_turn"],
        "passed": list(game["passed"]),
        # Public by the same reasoning §17 makes it public: once a side is
        # exhausted the clue-giver stops alternating, which is visible at the
        # table. It is a boolean at zero, never a remaining COUNT.
        "exhausted": [not agents_left_for(game, 0), not agents_left_for(game, 1)],
        "phase": game["phase"],
        "loss_reason": game.get("loss_reason"),
        "agents_total": TOTAL_AGENTS,
        "log": [dict(e) for e in game["log"]],
        "you": seat,
        # YOUR OWN SIDE ONLY. Never `game["keys"]`, and never the other index —
        # this is the whole secret of the game.
        "key": list(game["keys"][seat]) if seat is not None else None,
        "your_agents_left": len(agents_left_for(game, seat)) if seat is not None else None,
        "fatal_pos": game.get("fatal_pos") if over else None,
        # The reveal, and it exists ONLY once the game has ended.
        "reveal": [list(game["keys"][0]), list(game["keys"][1])] if over else None,
    }
