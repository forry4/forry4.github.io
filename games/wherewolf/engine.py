"""Pure rules engine for Where Wolf? — a One Night Werewolf-style party game.

Web-free and deterministic (seedable). All game state lives in one JSON-safe dict
(no sets/tuples; the RNG is persisted in ``game["rng_state"]`` as lists), so a game
survives save/load and reconnects. Mirrors the engine contract used by the other
games (``new_game`` / ``apply_move`` / ``is_over`` / ``winner``), plus the two
pieces this game needs:

  * ``player_view(game, pid)`` — a PER-RECIPIENT redaction of the game. This is the
    hidden-information boundary: a client is only ever sent the cards it is allowed
    to see in the current phase; everything else is ``None`` in the payload, so a
    snooping client literally cannot read a hidden card.
  * ``resolve_votes(game)`` — pure tally → reveal → winner.

THE load-bearing rule: a player PERFORMS the role they were DEALT for the whole
night (``players[pid]["dealt_role"]`` — immutable). Swaps only move the CARD in
front of a player (``players[pid]["card"]`` / ``center``); whatever card sits in
front of you when night ends is your FINAL role (possibly unknown to you).
"""
from __future__ import annotations

import random
from typing import Any

from . import roles

# ── Phases ────────────────────────────────────────────────────────────────────
DEALING, NIGHT, DAY, OVER = "dealing", "night", "day", "over"

# Night steps (also the conductor's narration cadence). ``intro``/``wakeup`` are
# "all eyes closed" beats; the middle three are the action windows.
STEP_INTRO, STEP_WOLVES, STEP_SEER, STEP_ROBBER, STEP_TMAKER, STEP_WAKE = (
    "intro", "werewolves", "seer", "robber", "troublemaker", "wakeup")


# ── RNG persistence (JSON-safe; mirrors the other engines) ────────────────────
def _load_rng(game: dict) -> random.Random:
    rng = random.Random()
    st = game.get("rng_state")
    if st:
        rng.setstate((st[0], tuple(st[1]), st[2]))
    return rng


def _save_rng(game: dict, rng: random.Random) -> None:
    st = rng.getstate()
    game["rng_state"] = [st[0], list(st[1]), st[2]]


def _dealt(game: dict, pid: str) -> str | None:
    p = game.get("players", {}).get(pid)
    return p.get("dealt_role") if p else None


# ── Construction ──────────────────────────────────────────────────────────────
def new_game(player_ids: list[str], names: dict[str, str] | None = None,
             seed: int | None = None) -> dict:
    """Deal hidden roles and enter the DEALING (ready) phase."""
    names = names or {}
    rng = random.Random(seed)
    order = list(player_ids)
    n = len(order)
    cards = roles.build_deck(n, rng)

    players: dict[str, dict] = {}
    for i, pid in enumerate(order):
        role = cards[i]
        players[pid] = {"dealt_role": role, "card": role, "ready": False}
    center = cards[n:]  # exactly 3

    game = {
        "phase": DEALING,
        "winner": None,                       # "villagers" | "wolves" | None
        "order": order,
        "names": {pid: names.get(pid, pid) for pid in order},
        "players": players,
        "center": center,
        # Public token row — the multiset of tokens for EVERY card in play. Reveals
        # WHICH roles exist (never who holds them). Sorted so it leaks no position.
        "roles_in_play": sorted(roles.TOKEN_LETTERS[c] for c in cards),
        "wolf_pids": [pid for pid in order if players[pid]["dealt_role"] == "werewolf"],

        # Night conductor state.
        "night_step": None,
        "step_deadline": None,
        "acted": {"seer": False, "robber": False, "troublemaker": False},
        "seer_peek": None,                    # {"kind":"player","pid":X} | {"kind":"center","indices":[i,j]}
        "robber_swap": None,                  # {"target": pid}
        "troublemaker_swap": None,            # {"a": pid, "b": pid}

        # Day / voting.
        "votes": {},                          # {voter_pid: target_pid}
        "locked": {},                         # {pid: bool}
        "vote_deadline": None,                # epoch seconds

        # Outcome.
        "revealed_pid": None,                 # whose card got flipped (None on tie)
        "vote_tally": {},

        "rng_state": None,
    }
    _save_rng(game, rng)
    return game


# ── State helpers (transitions the server conductor drives; pure + testable) ──
def all_ready(game: dict) -> bool:
    return (game.get("phase") == DEALING
            and bool(game["players"])
            and all(p["ready"] for p in game["players"].values()))


def start_night(game: dict) -> None:
    game["phase"] = NIGHT
    game["night_step"] = STEP_INTRO
    game["step_deadline"] = None


def set_step(game: dict, step: str, deadline: float | None = None) -> None:
    game["night_step"] = step
    game["step_deadline"] = deadline


def begin_day(game: dict, deadline: float | None) -> None:
    game["phase"] = DAY
    game["night_step"] = None
    game["step_deadline"] = None
    game["seer_peek"] = None
    game["votes"] = {}
    game["locked"] = {}
    game["vote_deadline"] = deadline


def all_locked(game: dict) -> bool:
    order = game.get("order", [])
    return (game.get("phase") == DAY and bool(order)
            and all(game["locked"].get(p) for p in order))


def is_over(game: dict) -> bool:
    return game.get("phase") == OVER


def winner(game: dict):
    return game.get("winner")


# ── Moves ─────────────────────────────────────────────────────────────────────
def apply_move(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    """Validate + apply a move (mutates ``game``). Returns ``(ok, error)``."""
    if not isinstance(move, dict):
        return False, "bad move"
    if pid not in game.get("players", {}):
        return False, "not in this game"
    mtype = move.get("type")

    if mtype == "ready":
        if game.get("phase") != DEALING:
            return False, "not the ready phase"
        game["players"][pid]["ready"] = True
        return True, None

    if mtype in ("seer_peek_player", "seer_peek_center", "robber_swap",
                 "troublemaker_swap", "skip"):
        return _apply_night(game, pid, move)

    if mtype in ("vote", "lock_vote", "unlock_vote"):
        return _apply_day(game, pid, move)

    return False, "unknown move"


def _apply_night(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if game.get("phase") != NIGHT:
        return False, "not the night phase"
    step = game.get("night_step")
    role = _dealt(game, pid)
    mtype = move["type"]

    if mtype == "skip":
        # The current actor declines their optional action.
        if step in ("seer", "robber", "troublemaker") and role == step and not game["acted"][step]:
            game["acted"][step] = True
            return True, None
        return False, "nothing to skip"

    if mtype == "seer_peek_player":
        if step != STEP_SEER:
            return False, "not the seer's turn"
        if role != "seer":
            return False, "you are not the seer"
        if game["acted"]["seer"] or game["seer_peek"] is not None:
            return False, "already acted"
        target = move.get("target")
        if target == pid or target not in game["players"]:
            return False, "bad target"
        game["seer_peek"] = {"kind": "player", "pid": target}
        game["acted"]["seer"] = True
        return True, None

    if mtype == "seer_peek_center":
        if step != STEP_SEER:
            return False, "not the seer's turn"
        if role != "seer":
            return False, "you are not the seer"
        if game["acted"]["seer"] or game["seer_peek"] is not None:
            return False, "already acted"
        idx = move.get("indices")
        if not (isinstance(idx, list) and len(idx) == 2 and len(set(idx)) == 2
                and all(isinstance(i, int) and 0 <= i < len(game["center"]) for i in idx)):
            return False, "pick two distinct center cards"
        game["seer_peek"] = {"kind": "center", "indices": sorted(idx)}
        game["acted"]["seer"] = True
        return True, None

    if mtype == "robber_swap":
        if step != STEP_ROBBER:
            return False, "not the robber's turn"
        if role != "robber":
            return False, "you are not the robber"
        if game["acted"]["robber"]:
            return False, "already acted"
        target = move.get("target")
        if target == pid or target not in game["players"]:
            return False, "bad target"
        a, b = game["players"][pid], game["players"][target]
        a["card"], b["card"] = b["card"], a["card"]   # CARDS swap; dealt_role stays
        game["robber_swap"] = {"target": target}
        game["acted"]["robber"] = True
        return True, None

    if mtype == "troublemaker_swap":
        if step != STEP_TMAKER:
            return False, "not the troublemaker's turn"
        if role != "troublemaker":
            return False, "you are not the troublemaker"
        if game["acted"]["troublemaker"]:
            return False, "already acted"
        a_id, b_id = move.get("a"), move.get("b")
        # The troublemaker may include themselves, but the two targets must differ.
        if a_id == b_id or a_id not in game["players"] or b_id not in game["players"]:
            return False, "pick two different players"
        pa, pb = game["players"][a_id], game["players"][b_id]
        pa["card"], pb["card"] = pb["card"], pa["card"]
        game["troublemaker_swap"] = {"a": a_id, "b": b_id}
        game["acted"]["troublemaker"] = True
        return True, None

    return False, "unknown night move"


def _apply_day(game: dict, pid: str, move: dict) -> tuple[bool, str | None]:
    if game.get("phase") != DAY:
        return False, "not the day phase"
    mtype = move["type"]

    if mtype == "vote":
        if game["locked"].get(pid):
            return False, "your vote is locked"
        target = move.get("target")
        if target not in game["players"]:
            return False, "bad target"
        game["votes"][pid] = target            # self-votes are allowed
        return True, None

    if mtype == "lock_vote":
        if game["votes"].get(pid) is None:
            return False, "cast a vote first"
        game["locked"][pid] = True
        return True, None

    if mtype == "unlock_vote":
        if not game["locked"].get(pid):
            return False, "not locked"
        game["locked"][pid] = False
        return True, None

    return False, "unknown day move"


def resolve_votes(game: dict) -> None:
    """Tally votes → set ``revealed_pid`` (None on tie) → set ``winner`` → OVER.

    Pure and idempotent: a no-op unless the game is in the DAY phase. The revealed
    player's FINAL card decides — a werewolf revealed means the villagers win.
    """
    if game.get("phase") != DAY:
        return

    tally: dict[str, int] = {}
    for target in game.get("votes", {}).values():
        if target in game["players"]:
            tally[target] = tally.get(target, 0) + 1
    game["vote_tally"] = tally

    revealed = None
    if tally:
        top = max(tally.values())
        leaders = [p for p, c in tally.items() if c == top]
        if len(leaders) == 1:
            revealed = leaders[0]
    game["revealed_pid"] = revealed

    if revealed is not None and game["players"][revealed]["card"] == "werewolf":
        game["winner"] = "villagers"
    else:
        game["winner"] = "wolves"            # incl. tie / no-reveal
    game["phase"] = OVER


# ── Per-recipient redaction (the hidden-information boundary) ──────────────────
def _card_visible(game: dict, pid: str, target_pid: str) -> bool:
    """May recipient ``pid`` see ``target_pid``'s CARD right now?"""
    phase = game.get("phase")
    step = game.get("night_step")
    if phase == OVER:
        return True                                   # all final cards revealed
    if target_pid == pid:
        if phase == DEALING:
            return True                               # your own dealt card, pre-flip
        if phase == NIGHT and step == STEP_ROBBER and _dealt(game, pid) == "robber":
            return True                               # the robber views their NEW card
        return False
    # Another player's card:
    if phase == NIGHT and step == STEP_WOLVES:
        return pid in game["wolf_pids"] and target_pid in game["wolf_pids"]
    if phase == NIGHT and step == STEP_SEER and _dealt(game, pid) == "seer":
        peek = game.get("seer_peek")
        if peek and peek.get("kind") == "player" and peek.get("pid") == target_pid:
            return True
    return False


def player_view(game: dict, pid: str) -> dict:
    """Return a redaction of ``game`` safe to send to player ``pid``.

    ``dealt_role`` is never sent for ANY player except the recipient's own (it's
    their own start-of-night knowledge, needed to drive the night-action UI and to
    survive reconnects). Every other player's ``card`` is ``None`` unless the
    visibility rules permit it; the center cards are ``None`` unless the recipient
    is the seer peeking them (or the game is over).
    """
    phase = game.get("phase")
    step = game.get("night_step")

    players_out: dict[str, dict] = {}
    for tpid, pdata in game["players"].items():
        players_out[tpid] = {
            "name": game["names"].get(tpid, tpid),
            "ready": pdata["ready"],
            "card": pdata["card"] if _card_visible(game, pid, tpid) else None,
        }

    seer_centers: set[int] = set()
    if phase == NIGHT and step == STEP_SEER and _dealt(game, pid) == "seer":
        peek = game.get("seer_peek")
        if peek and peek.get("kind") == "center":
            seer_centers = set(peek["indices"])
    center_out = [
        (c if (phase == OVER or i in seer_centers) else None)
        for i, c in enumerate(game["center"])
    ]

    return {
        "phase": phase,
        "winner": game.get("winner"),
        "order": list(game["order"]),
        "names": dict(game["names"]),
        "players": players_out,
        "center": center_out,
        "center_count": len(game["center"]),
        "roles_in_play": list(game["roles_in_play"]),
        "you": pid,
        # The recipient's OWN starting role — what they performed all night.
        "your_dealt_role": _dealt(game, pid),
        # Whether the recipient is an active role this round (drives night prompts).
        "is_active": _dealt(game, pid) in roles.ACTIVE_ROLES,
        "night_step": step,
        "step_deadline": game.get("step_deadline"),
        "acted": dict(game.get("acted", {})),
        # Votes/locks are public during DAY and at OVER; hidden otherwise.
        "votes": dict(game["votes"]) if phase in (DAY, OVER) else {},
        "locked": dict(game["locked"]) if phase in (DAY, OVER) else {},
        "vote_deadline": game.get("vote_deadline") if phase == DAY else None,
        "revealed_pid": game.get("revealed_pid") if phase == OVER else None,
        "vote_tally": dict(game.get("vote_tally", {})) if phase == OVER else {},
    }
