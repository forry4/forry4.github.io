"""Halcyon Rift HTTP routes (design §18.4) — plain `def`, no sockets, no rooms.

`setup_halcyon(app, get_db_conn, get_user_by_session, token_resolver)` follows the
Books / Notes / Box Puzzles injected-dependency pattern. Every route is plain `def`,
so FastAPI runs it on its thread pool and a Turso round trip never pauses the
event loop the board games share (root CLAUDE.md).

WHO IS ASKING. An account is its session (Authorization: Bearer). A guest is a
roster the SERVER minted — `POST /halcyon/guest` returns an owner id and a secret,
once, and the device sends both on every request (X-Halcyon-Owner / -Secret). The
owner id is server-made rather than the site's guest id because guest ids are
printed in other games' public player lists, and a known id could be registered
first by someone else.
"""
from __future__ import annotations

import secrets
import threading
import time

from fastapi import Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field

from core import alerts
from core.ratelimit import SlidingWindowLimiter
from halcyon import content as C
from halcyon import dungeon as D
from halcyon import store as S

# New characters start at TIER 0 (owner's call, 2026-11-19), so the first drops are upgrades.
STARTERS = {
    "ranger": [({"base_id": "longbow", "tier": 0, "slot_count": 0, "enchants": []}, "weapon"),
               ({"base_id": "leather_vest", "tier": 0, "slot_count": 0, "enchants": []}, "armor"),
               ({"base_id": "volley_quiver", "tier": 0, "slot_count": 0, "enchants": []}, "ability")],
    "paladin": [({"base_id": "mace", "tier": 0, "slot_count": 0, "enchants": []}, "weapon"),
                ({"base_id": "plate_armor", "tier": 0, "slot_count": 0, "enchants": []}, "armor"),
                ({"base_id": "stillness_orb", "tier": 0, "slot_count": 0, "enchants": []}, "ability")],
    "diviner": [({"base_id": "starstaff", "tier": 0, "slot_count": 0, "enchants": []}, "weapon"),
                ({"base_id": "seer_robes", "tier": 0, "slot_count": 0, "enchants": []}, "armor"),
                ({"base_id": "star_tome", "tier": 0, "slot_count": 0, "enchants": []}, "ability")],
    "ninja": [({"base_id": "shuriken", "tier": 0, "slot_count": 0, "enchants": []}, "weapon"),
              ({"base_id": "shadow_garb", "tier": 0, "slot_count": 0, "enchants": []}, "armor"),
              ({"base_id": "mirror_charm", "tier": 0, "slot_count": 0, "enchants": []}, "ability")],
}
# Kept as a named Ranger alias for the existing route tests and tools.
STARTER = STARTERS["ranger"]

_guests_hour = SlidingWindowLimiter(max_hits=10, window_seconds=3600)
_runs_hour = SlidingWindowLimiter(max_hits=120, window_seconds=3600)
_events_minute = SlidingWindowLimiter(max_hits=120, window_seconds=60)
_upkeep = {"at": 0.0, "lock": threading.Lock()}
UPKEEP_EVERY = 3600.0


def _default_token_resolver(token: str | None = Query(default=None)) -> str | None:
    return token


class CharacterIn(BaseModel):
    slot: int = Field(ge=0, lt=C.CHARACTER_SLOTS)
    class_id: str = Field(default="ranger", max_length=32)


class RunIn(BaseModel):
    char_id: str = Field(max_length=64)
    dungeon_id: str = Field(default="shallows", max_length=32)
    practice: bool = False
    mods: list[str] = Field(default_factory=list, max_length=8)
    boss_rush: bool = False


class DescendIn(BaseModel):
    mod: str = Field(max_length=32)
    from_level: int = Field(ge=1, le=99)


class EventsIn(BaseModel):
    events: list[dict] = Field(max_length=500)


class MoveIn(BaseModel):
    to: list = Field(min_length=2, max_length=3)
    version: int | None = None


class DiscardIn(BaseModel):
    version: int | None = None


class LockIn(BaseModel):
    locked: bool


class FuseIn(BaseModel):
    a: str = Field(max_length=64)
    b: str = Field(max_length=64)


def _refuse(e: S.HalcyonError):
    raise HTTPException(status_code=409, detail=str(e))


def _place(to: list) -> tuple:
    """The wire's place ([kind, ...]) as the store's tuple, with indexes as ints."""
    kind, rest = to[0], list(to[1:])
    if kind == "vault":
        return ("vault", rest[0] if isinstance(rest[0], int) else -1)
    if kind == "inventory" and len(rest) == 2:
        return ("inventory", str(rest[0]), rest[1] if isinstance(rest[1], int) else -1)
    if kind == "equipped" and len(rest) == 2:
        return ("equipped", str(rest[0]), str(rest[1]))
    if kind == "floor" and len(rest) == 1:
        return ("floor", str(rest[0]))
    return ("nowhere",)


def setup_halcyon(app, get_db_conn, get_user_by_session, token_resolver=None) -> None:
    conn = get_db_conn()
    try:
        S.init_schema(conn)
    finally:
        conn.close()
    connect = get_db_conn
    resolve_token = token_resolver or _default_token_resolver

    def owner(token: str | None = Depends(resolve_token),
              x_halcyon_owner: str | None = Header(default=None),
              x_halcyon_secret: str | None = Header(default=None)) -> str:
        user = get_user_by_session(token) if token else None
        if user and user.get("id") and not user.get("guest"):
            S.register_owner(connect, user["id"], "account")      # idempotent
            return user["id"]
        if x_halcyon_owner and x_halcyon_secret and len(x_halcyon_owner) <= 64 \
                and S.verify_guest(connect, x_halcyon_owner, x_halcyon_secret):
            return x_halcyon_owner
        raise HTTPException(status_code=401, detail="no roster")

    def upkeep() -> None:
        """Tidy idle guests and abandoned runs at most hourly, on a read."""
        with _upkeep["lock"]:
            now = time.time()
            if now - _upkeep["at"] < UPKEEP_EVERY:
                return
            _upkeep["at"] = now
        S.prune_guests(connect)
        S.sweep_runs(connect)

    def call(fn, *a, **kw):
        try:
            return fn(connect, *a, **kw)
        except S.HalcyonError as e:
            _refuse(e)

    @app.post("/halcyon/guest")
    def halcyon_guest(request: Request):
        ip = request.client.host if request.client else "unknown"
        if _guests_hour.exceeded(ip):
            alerts.alert("halcyon-guests", f"{ip} is minting Halcyon guest rosters past the limit.",
                         key=f"halcyon-guests:{ip}")
            raise HTTPException(status_code=429, detail="Too many new rosters. Try again later.")
        _guests_hour.record(ip)
        owner_id = "hg_" + secrets.token_hex(12)
        secret = S.register_owner(connect, owner_id, "guest")
        return {"owner": owner_id, "secret": secret}

    @app.get("/halcyon/state")
    def halcyon_state(who: str = Depends(owner)):
        upkeep()
        view = S.owner_view(connect, who)
        return {**view, "dungeons": [{"id": k, "name": v["name"], "boss_name": v["boss_name"],
                                  "requires": (C.REQUIRES.get(k) or (None,))[0],
                                  # this rift's loot at 0..START_MODS modifiers (its own tables)
                                  "loot": [C.loot_odds(r, *v["quality"]) for r in range(C.START_MODS + 1)]}
                                 for k, v in D.DUNGEONS.items()],
                # What the panels say: one loot bonus per modifier and per level deeper.
                "loot_rule": {"per_mod": C.LOOT_PER_MODIFIER, "per_level": C.LOOT_PER_LEVEL,
                              "xp_per_mod": C.MOD_XP, "start_mods": C.START_MODS},
                "limits": {"vault": C.VAULT_SIZE, "inventory": C.INVENTORY_SIZE,
                           "characters": C.CHARACTER_SLOTS, "equip": list(C.EQUIP_SLOTS)},
                "classes": [{"id": k, "name": C.CLASS_NAMES[k], "description": C.CLASS_DESCRIPTIONS[k]}
                            for k in C.CLASSES],
                "levels": list(C.LEVEL_XP),
                "rift_mods": [{"id": k, **v} for k, v in C.RIFT_MODS.items()],
                "boss_rush": C.BOSS_RUSH,
                # The odds the page shows (the forge's and the modifiers' panels), read
                # off the same constants the generator and the store roll against.
                "odds": {"fuse_slot_gain": [list(g) for g in C.FUSE_SLOT_GAIN], "max_slots": C.MAX_ENCHANT_SLOTS,
                         # The loot odds at 0..N modifiers, worked out from the tables.
                         "loot": [C.loot_odds(r) for r in range(C.START_MODS + 1)]},
                "bases": C.BASE_ITEMS}

    @app.post("/halcyon/characters")
    def halcyon_create(body: CharacterIn, who: str = Depends(owner)):
        return call(S.create_character, who, body.slot, body.class_id,
                    starter=STARTERS.get(body.class_id, STARTER))

    @app.post("/halcyon/characters/{char_id}/open")
    def halcyon_open(char_id: str, who: str = Depends(owner)):
        return call(S.open_character, who, char_id)

    @app.post("/halcyon/characters/{char_id}/leave")
    def halcyon_leave(char_id: str, who: str = Depends(owner)):
        call(S.leave_town, who, char_id)
        return {"ok": True}

    @app.post("/halcyon/runs")
    def halcyon_run(body: RunIn, who: str = Depends(owner)):
        if _runs_hour.exceeded(who):
            raise HTTPException(status_code=429, detail="Too many dungeons this hour.")
        _runs_hour.record(who)
        try:
            class_id = S.character_class(connect, who, body.char_id)
            d = D.generate(body.dungeon_id, class_id=class_id, mods=body.mods, boss_rush=body.boss_rush)
            run = S.start_run(connect, who, body.char_id, body.dungeon_id, d["seed"], d,
                              practice=body.practice)
        except S.HalcyonError as e:
            _refuse(e)
        return {"run_id": run["run_id"], "dungeon": d, "practice": body.practice, "class_id": class_id,
                "spent": run["spent"]}

    @app.post("/halcyon/runs/{run_id}/descend")
    def halcyon_descend(run_id: str, body: DescendIn, who: str = Depends(owner)):
        if _events_minute.exceeded(who):
            raise HTTPException(status_code=429, detail="slow down")
        _events_minute.record(who)
        make = lambda dungeon_id, seed, class_id, mods, level, boss_rush=False: D.generate(
            dungeon_id, seed, class_id=class_id, mods=mods, level=level, boss_rush=boss_rush)
        d = call(S.descend, who, run_id, body.mod, body.from_level, make)
        return {"dungeon": d}

    @app.post("/halcyon/runs/{run_id}/events")
    def halcyon_events(run_id: str, body: EventsIn, who: str = Depends(owner)):
        if _events_minute.exceeded(who):
            raise HTTPException(status_code=429, detail="slow down")
        _events_minute.record(who)
        return call(S.apply_events, who, run_id, body.events)

    @app.post("/halcyon/items/{item_id}/move")
    def halcyon_move(item_id: str, body: MoveIn, who: str = Depends(owner)):
        return call(S.move_item, who, item_id, _place(body.to), body.version)

    @app.post("/halcyon/items/{item_id}/discard")
    def halcyon_discard(item_id: str, body: DiscardIn, who: str = Depends(owner)):
        call(S.discard, who, item_id, body.version)
        return {"ok": True}

    @app.post("/halcyon/items/{item_id}/lock")
    def halcyon_lock(item_id: str, body: LockIn, who: str = Depends(owner)):
        return call(S.set_lock, who, item_id, body.locked)

    @app.post("/halcyon/fuse")
    def halcyon_fuse(body: FuseIn, who: str = Depends(owner)):
        return call(S.fuse, who, body.a, body.b)
