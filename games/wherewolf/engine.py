"""Pure rules engine for Where Wolf? — a One Night Ultimate Werewolf clone.

Web-free and deterministic (seedable). All game state lives in one JSON-safe dict
(no sets/tuples; the RNG is persisted in ``game["rng_state"]`` as lists), so a game
survives save/load and reconnects. Mirrors the engine contract used by the other
games (``new_game`` / ``apply_move`` / ``is_over`` / ``winner``), plus:

  * ``player_view(game, pid)`` — a PER-RECIPIENT redaction (the hidden-information
    boundary). A client is only ever sent the cards it may see; everything else is
    ``None`` in the payload, so a snooping client literally cannot read a hidden card.
  * ``resolve_votes(game)`` — official ONUW multi-death tally + Hunter chain + the
    full team/tanner/minion win logic.

THE load-bearing rule: a player PERFORMS the role they were DEALT for the whole
night (``players[pid]["dealt_role"]`` — immutable). Swaps only move the CARD in
front of a player (``players[pid]["card"]`` / ``center``); whatever card sits in
front of you when night ends is your FINAL role (possibly unknown to you).
"""
from __future__ import annotations

import random

from . import roles

# ── Phases ────────────────────────────────────────────────────────────────────
DEALING, NIGHT, DAY, OVER = "dealing", "night", "day", "over"

# Night steps (also the conductor's narration cadence).
STEP_INTRO, STEP_WOLVES, STEP_MINION, STEP_MASONS, STEP_SEER, STEP_ROBBER, \
    STEP_TMAKER, STEP_DRUNK, STEP_INSOMNIAC, STEP_WAKE = (
        "intro", "werewolves", "minion", "masons", "seer", "robber",
        "troublemaker", "drunk", "insomniac", "wakeup")


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
             seed: int | None = None, deck: list[str] | None = None) -> dict:
    """Deal hidden roles and enter the DEALING (ready) phase.

    ``deck`` (optional): the host-chosen multiset of role cards (length players+3).
    Validated then seeded-shuffled. When omitted, the default ``build_deck`` is used.
    """
    names = names or {}
    rng = random.Random(seed)
    order = list(player_ids)
    n = len(order)
    if deck is None:
        cards = roles.build_deck(n, rng)
    else:
        ok, err = roles.validate_deck(deck, n)
        if not ok:
            raise ValueError(err)
        cards = list(deck)
        rng.shuffle(cards)

    players: dict[str, dict] = {}
    for i, pid in enumerate(order):
        role = cards[i]
        players[pid] = {"dealt_role": role, "card": role, "ready": False}
    center = cards[n:]  # exactly 3

    game = {
        "phase": DEALING,
        "winner": None,                       # legacy: "villagers" | "wolves" | None
        "order": order,
        "names": {pid: names.get(pid, pid) for pid in order},
        "players": players,
        "center": center,
        "deck": list(cards),                  # public multiset in play (drives the conductor)
        "roles_in_play": sorted(roles.TOKEN_LETTERS[c] for c in cards),
        # Dealt-role groupings (server-only; redacted by player_view).
        "wolf_pids": [p for p in order if players[p]["dealt_role"] == "werewolf"],
        "mason_pids": [p for p in order if players[p]["dealt_role"] == "mason"],
        "minion_pids": [p for p in order if players[p]["dealt_role"] == "minion"],

        # Night conductor state.
        "night_step": None,
        "step_deadline": None,
        "acted": {"seer": False, "robber": False, "troublemaker": False, "drunk": False},
        "seer_peek": None,                    # {"kind":"player","pid":X} | {"kind":"center","indices":[i,j]}
        "robber_swap": None,                  # {"target": pid}
        "troublemaker_swap": None,            # {"a": pid, "b": pid}
        "drunk_swap": None,                   # {"center_index": i}  (BLIND — card moved, not revealed)
        "lone_wolf_peek": None,               # {"index": i}  (i == -1 means "declined")

        # Day / voting.
        "votes": {},                          # {voter_pid: target_pid}
        "locked": {},                         # {pid: bool}
        "vote_deadline": None,                # epoch seconds

        # Outcome (multi-death).
        "deaths": [],                         # pids who died
        "revealed": [],                       # == deaths (revealed at OVER)
        "revealed_pid": None,                 # legacy: first dead pid (back-compat)
        "vote_tally": {},
        "winners": [],                        # pids who won
        "winning_teams": [],                  # ["village"] | ["werewolf"] | ["tanner"] | ...
        "headline": None,                     # human result string

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
                 "troublemaker_swap", "drunk_swap", "wolf_peek_center", "skip"):
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
        if (step in ("seer", "robber", "troublemaker", "drunk")
                and role == roles.STEP_ROLE.get(step) and not game["acted"].get(step)):
            game["acted"][step] = True
            return True, None
        # lone wolf declining the optional center peek
        if (step == STEP_WOLVES and role == "werewolf"
                and len(game["wolf_pids"]) == 1 and game["lone_wolf_peek"] is None):
            game["lone_wolf_peek"] = {"index": -1}
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
        if a_id == b_id or a_id not in game["players"] or b_id not in game["players"]:
            return False, "pick two different players"
        pa, pb = game["players"][a_id], game["players"][b_id]
        pa["card"], pb["card"] = pb["card"], pa["card"]
        game["troublemaker_swap"] = {"a": a_id, "b": b_id}
        game["acted"]["troublemaker"] = True
        return True, None

    if mtype == "drunk_swap":
        if step != STEP_DRUNK:
            return False, "not the drunk's turn"
        if role != "drunk":
            return False, "you are not the drunk"
        if game["acted"]["drunk"]:
            return False, "already acted"
        ci = move.get("center_index")
        if not (isinstance(ci, int) and 0 <= ci < len(game["center"])):
            return False, "pick a center card"
        p = game["players"][pid]
        p["card"], game["center"][ci] = game["center"][ci], p["card"]   # BLIND — no reveal
        game["drunk_swap"] = {"center_index": ci}
        game["acted"]["drunk"] = True
        return True, None

    if mtype == "wolf_peek_center":
        if step != STEP_WOLVES:
            return False, "not the werewolves' turn"
        if role != "werewolf":
            return False, "you are not a werewolf"
        if len(game["wolf_pids"]) != 1:
            return False, "only a lone wolf may peek"
        if game["lone_wolf_peek"] is not None:
            return False, "already peeked"
        idx = move.get("index")
        if not (isinstance(idx, int) and 0 <= idx < len(game["center"])):
            return False, "pick a center card"
        game["lone_wolf_peek"] = {"index": idx}
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


# ── Vote resolution (official ONUW: multi-death + Hunter + team/tanner/minion) ──
_TEAM_NAMES = {"village": "Villagers", "werewolf": "Werewolves",
               "tanner": "Tanner", "minion": "Minion"}


def _headline(winning_teams: list[str]) -> str:
    if not winning_teams:
        return "No one wins"
    names = [_TEAM_NAMES.get(t, t.title()) for t in winning_teams]
    if len(names) == 1 and winning_teams[0] in ("tanner", "minion"):
        return names[0] + " wins"
    return " & ".join(names) + " win"


def resolve_votes(game: dict) -> None:
    """Tally votes → deaths (multi-death + Hunter chain) → winners. OVER. Idempotent
    (no-op unless DAY). Uses FINAL cards."""
    if game.get("phase") != DAY:
        return
    order = game["order"]
    players = game["players"]

    tally: dict[str, int] = {}
    for tgt in game.get("votes", {}).values():
        if tgt in players:
            tally[tgt] = tally.get(tgt, 0) + 1
    game["vote_tally"] = tally

    # The player(s) with the MOST votes die — but only if the max is >= 2 (if nobody
    # got "ganged up on", no one dies). Ties at the top all die.
    deaths: set[str] = set()
    if tally:
        top = max(tally.values())
        if top >= 2:
            deaths = {p for p, c in tally.items() if c == top}

    def final(p: str) -> str:
        return players[p]["card"]

    # Hunter chain: a dead Hunter (final card) kills the player they voted for.
    # Transitive, with a cycle guard.
    queue = list(deaths)
    while queue:
        p = queue.pop()
        if final(p) == "hunter":
            tgt = game.get("votes", {}).get(p)
            if tgt in players and tgt not in deaths:
                deaths.add(tgt)
                queue.append(tgt)

    dead = sorted(deaths, key=order.index)
    game["deaths"] = dead
    game["revealed"] = list(dead)
    game["revealed_pid"] = dead[0] if dead else None

    _resolve_win(game, dead)
    game["phase"] = OVER


def _resolve_win(game: dict, dead: list[str]) -> None:
    order = game["order"]
    players = game["players"]

    def final(p: str) -> str:
        return players[p]["card"]

    wolf_in_play = any(final(p) == "werewolf" for p in order)   # players only
    wolf_died = any(final(p) == "werewolf" for p in dead)       # a WEREWOLF card died
    tanner_died = any(final(p) == "tanner" for p in dead)
    someone_died = bool(dead)

    teams: set[str] = set()
    if tanner_died:
        teams.add("tanner")

    if wolf_in_play:
        if wolf_died:
            teams.add("village")                 # a werewolf died → village wins
        elif not tanner_died:
            teams.add("werewolf")                # no wolf died (and no tanner death) → wolves win
        # tanner died + no wolf died → only the tanner wins (wolf-team win suppressed)
    else:
        if not someone_died:
            teams.add("village")                 # no wolves in play, nobody died → village wins
        # else: village loses (no village winner)

    # Minion special: a minion is in play, no werewolves are, and any NON-minion
    # died → the minion wins.
    minion_in_play = any(final(p) == "minion" for p in order)
    minion_special = (minion_in_play and not wolf_in_play and someone_died
                      and any(final(p) != "minion" for p in dead))

    winners: list[str] = []
    for p in order:
        fc = final(p)
        t = roles.team_of(fc)
        if t == "tanner":
            if "tanner" in teams and p in dead:
                winners.append(p)              # the tanner wins ONLY by dying
        elif t == "village":
            if "village" in teams:
                winners.append(p)
        elif t == "werewolf":
            if "werewolf" in teams:
                winners.append(p)
            elif fc == "minion" and minion_special:
                winners.append(p)

    winning_teams = sorted(teams)
    if minion_special and "minion" not in winning_teams:
        winning_teams.append("minion")

    game["winners"] = winners
    game["winning_teams"] = winning_teams
    game["headline"] = _headline(winning_teams)
    game["winner"] = ("villagers" if "village" in teams
                      else "wolves" if "werewolf" in teams else None)


# ── Per-recipient redaction (the hidden-information boundary) ──────────────────
def _card_visible(game: dict, viewer: str, target: str) -> bool:
    """May ``viewer`` see ``target``'s CARD right now?"""
    phase = game.get("phase")
    step = game.get("night_step")
    if phase == OVER:
        return True                                       # all final cards revealed
    dealt = _dealt(game, viewer)
    if target == viewer:
        if phase == DEALING:
            return True                                   # own dealt card, pre-flip
        if phase == NIGHT and step == STEP_ROBBER and dealt == "robber":
            return True                                   # robber views their NEW card
        if phase == NIGHT and step == STEP_INSOMNIAC and dealt == "insomniac":
            return True                                   # insomniac checks their own card
        return False
    if phase != NIGHT:
        return False
    if step == STEP_WOLVES:
        return viewer in game["wolf_pids"] and target in game["wolf_pids"]
    if step == STEP_MINION:
        # minion sees the wolves; wolves do NOT learn the minion (asymmetric).
        return dealt == "minion" and target in game["wolf_pids"]
    if step == STEP_MASONS:
        return viewer in game["mason_pids"] and target in game["mason_pids"]
    if step == STEP_SEER and dealt == "seer":
        peek = game.get("seer_peek")
        return bool(peek and peek.get("kind") == "player" and peek.get("pid") == target)
    return False


def player_view(game: dict, pid: str) -> dict:
    """Return a redaction of ``game`` safe to send to player ``pid``. ``dealt_role``
    is only ever sent for the recipient's own seat; every other card is ``None``
    unless the visibility rules permit it."""
    phase = game.get("phase")
    step = game.get("night_step")
    dealt = _dealt(game, pid)

    players_out: dict[str, dict] = {}
    for tpid, pdata in game["players"].items():
        players_out[tpid] = {
            "name": game["names"].get(tpid, tpid),
            "ready": pdata["ready"],
            "card": pdata["card"] if _card_visible(game, pid, tpid) else None,
        }

    visible_centers: set[int] = set()
    if phase == NIGHT and step == STEP_SEER and dealt == "seer":
        peek = game.get("seer_peek")
        if peek and peek.get("kind") == "center":
            visible_centers = set(peek["indices"])
    if phase == NIGHT and step == STEP_WOLVES and dealt == "werewolf":
        lw = game.get("lone_wolf_peek")
        if lw and lw.get("index", -1) >= 0:
            visible_centers = {lw["index"]}
    center_out = [
        (c if (phase == OVER or i in visible_centers) else None)
        for i, c in enumerate(game["center"])
    ]

    over = phase == OVER
    return {
        "phase": phase,
        "winner": game.get("winner"),
        "order": list(game["order"]),
        "names": dict(game["names"]),
        "players": players_out,
        "center": center_out,
        "center_count": len(game["center"]),
        "roles_in_play": list(game["roles_in_play"]),
        "deck": list(game.get("deck", [])),   # public multiset (== the token row)
        "you": pid,
        "your_dealt_role": dealt,
        "is_active": dealt in roles.ACTIVE_ROLES,
        "is_lone_wolf": dealt == "werewolf" and len(game["wolf_pids"]) == 1,
        "night_step": step,
        "step_deadline": game.get("step_deadline"),
        "acted": dict(game.get("acted", {})),
        # Votes/locks public during DAY and at OVER; hidden otherwise.
        "votes": dict(game["votes"]) if phase in (DAY, OVER) else {},
        "locked": dict(game["locked"]) if phase in (DAY, OVER) else {},
        "vote_deadline": game.get("vote_deadline") if phase == DAY else None,
        # Outcome (OVER only).
        "deaths": list(game.get("deaths", [])) if over else [],
        "revealed": list(game.get("revealed", [])) if over else [],
        "revealed_pid": game.get("revealed_pid") if over else None,
        "vote_tally": dict(game.get("vote_tally", {})) if over else {},
        "winners": list(game.get("winners", [])) if over else [],
        "winning_teams": list(game.get("winning_teams", [])) if over else [],
        "headline": game.get("headline") if over else None,
    }
