"""Halcyon Rift item store — characters, items, vault and runs (design §18, §20).

The contract, in one paragraph: every item has a permanent random id and is in
EXACTLY ONE place (vault, a character's inventory or equipment, the floor of a
run, or destroyed — destroyed items are kept as tombstones). Every operation is
ONE transaction, opened and closed here: it commits on success, and on any
failure the connection is closed WITHOUT a commit, which rolls back on sqlite
and on Turso alike (`core/db.py`'s wrapper has no `rollback()`, and needs none).
A run's events are numbered and applied idempotently, so a batch re-sent after
a restart or a dropped connection changes nothing; a drop is minted at most
once, enforced by a UNIQUE index rather than by code. A client never names an
item, an XP amount or a stat — it names what it did ("picked up drop 4"), and
the item comes from the run's own record of what drop 4 is.

Concurrency: the site is ONE uvicorn process, so each owner's writes are
serialised behind an in-process lock, and the reads an operation validates
against happen under it. Town operations may also carry the `version` the
client last saw; a mismatch is refused as stale.

The wrapper has no `rowcount` (CLAUDE.md, Backend footguns), so nothing here
depends on one: every check is a SELECT under the lock, before the write.
"""
from __future__ import annotations

import hashlib
import json
import random
import secrets
import threading
import time
from contextlib import contextmanager

from halcyon import content as C


class HalcyonError(ValueError):
    """A refused operation. The message is safe to show the player."""


# ── locks ────────────────────────────────────────────────────────────────────
# A fixed pool, so guest ids that come and go never grow a dict. Two owners
# sharing a stripe only wait on each other; correctness never depends on it.
_LOCKS = [threading.Lock() for _ in range(64)]


def _owner_lock(owner_id: str) -> threading.Lock:
    return _LOCKS[hash(owner_id) % len(_LOCKS)]


@contextmanager
def _tx(connect, owner_id: str | None = None):
    """One operation = one transaction. Commit on success; on ANY exception,
    close without committing (= roll back) and re-raise."""
    lock = _owner_lock(owner_id) if owner_id is not None else None
    if lock:
        lock.acquire()
    try:
        conn = connect()
        try:
            yield conn.cursor()
            conn.commit()
        finally:
            conn.close()
    finally:
        if lock:
            lock.release()


def _now(now: float | None) -> float:
    return time.time() if now is None else now


def _new_id() -> str:
    return secrets.token_hex(16)                     # 128 random bits


# ── schema ───────────────────────────────────────────────────────────────────
SCHEMA = [
    """CREATE TABLE IF NOT EXISTS hr_owners (
        owner_id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,                  -- account | guest
        guest_secret_hash TEXT,
        created_at REAL NOT NULL,
        last_seen_at REAL NOT NULL)""",
    """CREATE TABLE IF NOT EXISTS hr_characters (
        char_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        slot INTEGER NOT NULL,
        class_id TEXT NOT NULL,
        level INTEGER NOT NULL DEFAULT 1,
        xp INTEGER NOT NULL DEFAULT 0,
        stat_progress TEXT NOT NULL DEFAULT '{}',
        status TEXT NOT NULL,                -- alive | dead
        created_at REAL NOT NULL,
        died_at REAL,
        death_run_id TEXT,
        death_summary TEXT)""",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_char_alive_slot "
    "ON hr_characters (owner_id, slot) WHERE status = 'alive'",
    """CREATE TABLE IF NOT EXISTS hr_items (
        item_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        base_id TEXT NOT NULL,
        tier INTEGER NOT NULL,
        kind TEXT NOT NULL,                  -- standard | unique
        slot_count INTEGER NOT NULL,
        enchants TEXT NOT NULL,              -- JSON [{"id": ..., "q": 0..1}]
        content_version INTEGER NOT NULL,
        origin TEXT NOT NULL,                -- drop | fusion | grant
        origin_run_id TEXT,
        origin_drop_id TEXT,
        fused_from TEXT,                     -- JSON [a, b]
        loc TEXT NOT NULL,                   -- vault | inventory | equipped | ground | destroyed
        char_id TEXT,
        run_id TEXT,
        slot_index INTEGER,
        destroyed_reason TEXT,               -- death | fusion | discard | run_end
        destroyed_at REAL,
        created_at REAL NOT NULL,
        updated_at REAL NOT NULL,
        version INTEGER NOT NULL DEFAULT 1,
        locked INTEGER NOT NULL DEFAULT 0)""",
    # THE DUPLICATION GUARD: a drop is minted once, however often its pickup is sent.
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_items_drop "
    "ON hr_items (origin_run_id, origin_drop_id)",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_items_vault_slot "
    "ON hr_items (owner_id, slot_index) WHERE loc = 'vault'",
    "CREATE UNIQUE INDEX IF NOT EXISTS idx_hr_items_char_slot "
    "ON hr_items (char_id, loc, slot_index) WHERE loc IN ('inventory', 'equipped')",
    "CREATE INDEX IF NOT EXISTS idx_hr_items_owner ON hr_items (owner_id, loc)",
    "CREATE INDEX IF NOT EXISTS idx_hr_items_run ON hr_items (run_id)",
    """CREATE TABLE IF NOT EXISTS hr_runs (
        run_id TEXT PRIMARY KEY,
        char_id TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        dungeon_id TEXT NOT NULL,
        seed TEXT NOT NULL,
        content_version INTEGER NOT NULL,
        status TEXT NOT NULL,                -- open | recalled | completed | died
        practice INTEGER NOT NULL DEFAULT 0,  -- Dream Rift: no rewards or character loss
        started_at REAL NOT NULL,
        last_event_at REAL NOT NULL,
        last_seq INTEGER NOT NULL DEFAULT 0,
        dungeon TEXT NOT NULL,               -- JSON: the server's generated dungeon
        state TEXT NOT NULL,                 -- JSON: {"killed": [...], "picked": [...]}
        refused TEXT NOT NULL DEFAULT '[]')""",
    "CREATE INDEX IF NOT EXISTS idx_hr_runs_char ON hr_runs (char_id, status)",
    """CREATE TABLE IF NOT EXISTS hr_rift_times (
        time_id TEXT PRIMARY KEY,
        owner_id TEXT NOT NULL,
        dungeon_id TEXT NOT NULL,
        run_id TEXT NOT NULL UNIQUE,
        time_ticks INTEGER NOT NULL,
        practice INTEGER NOT NULL DEFAULT 0,
        created_at REAL NOT NULL)""",
    "CREATE INDEX IF NOT EXISTS idx_hr_rift_times_owner ON hr_rift_times (owner_id, dungeon_id, time_ticks)",
]


def init_schema(conn) -> None:
    cur = conn.cursor()
    for stmt in SCHEMA:
        cur.execute(stmt)
    # `hr_runs` predates Dream Rifts on existing Turso/sqlite databases. Keep the
    # migration additive: old real runs remain ordinary runs (practice=0).
    cur.execute("PRAGMA table_info(hr_runs)")
    if not any(row[1] == "practice" for row in cur.fetchall()):
        cur.execute("ALTER TABLE hr_runs ADD COLUMN practice INTEGER NOT NULL DEFAULT 0")
    # The QOL pass (2026-11-18, design §19.1), additive like the one above: an item
    # LOCK, and the graveyard's copy of each death screen.
    cur.execute("PRAGMA table_info(hr_items)")
    if not any(row[1] == "locked" for row in cur.fetchall()):
        cur.execute("ALTER TABLE hr_items ADD COLUMN locked INTEGER NOT NULL DEFAULT 0")
    cur.execute("PRAGMA table_info(hr_characters)")
    if not any(row[1] == "death_summary" for row in cur.fetchall()):
        cur.execute("ALTER TABLE hr_characters ADD COLUMN death_summary TEXT")
    # Whether a base is standard or unique belongs to the BASE, so items follow
    # content.py when it changes (the repeater became a unique, 2026-11-18). Uniques
    # are tiered like everything else since 2026-11-19 (they were all tier 1, and
    # stay so). Cheap, and a no-op once everything agrees.
    # One ability per class (2026-11-18): the Diviner's equipped Stillness Orbs become
    # Star Tomes FIRST (the orb is the Paladin's now, so no Diviner can be wearing one
    # after this), then every retired shield becomes the Paladin's orb. Both are no-ops
    # once done. Enchantments carry over: all three are ability items.
    cur.execute("UPDATE hr_items SET base_id='star_tome' WHERE base_id='stillness_orb' AND loc='equipped' "
                "AND char_id IN (SELECT char_id FROM hr_characters WHERE class_id='diviner')")
    cur.execute("UPDATE hr_items SET base_id='stillness_orb' WHERE base_id='grounding_aegis'")
    for base_id, b in C.BASE_ITEMS.items():
        cur.execute("UPDATE hr_items SET kind=? WHERE base_id=? AND kind<>?", (b["kind"], base_id, b["kind"]))
    conn.commit()


# ── row helpers ──────────────────────────────────────────────────────────────
def _dicts(cur) -> list[dict]:
    cols = [c[0] for c in (cur.description or [])]
    return [dict(zip(cols, list(r))) for r in cur.fetchall()]


def _one(cur, sql: str, params=()) -> dict | None:
    cur.execute(sql, params)
    rows = _dicts(cur)
    return rows[0] if rows else None


def _item_out(row: dict) -> dict:
    out = dict(row)
    out["enchants"] = json.loads(row["enchants"])
    out["fused_from"] = json.loads(row["fused_from"]) if row.get("fused_from") else None
    out["locked"] = bool(row.get("locked") or 0)
    if row["loc"] == "equipped" and row["slot_index"] is not None:
        out["equip_slot"] = C.EQUIP_SLOTS[row["slot_index"]]
    return out


def _require_owner(cur, owner_id: str, now: float) -> dict:
    o = _one(cur, "SELECT * FROM hr_owners WHERE owner_id=?", (owner_id,))
    if o is None:
        raise HalcyonError("no such player")
    cur.execute("UPDATE hr_owners SET last_seen_at=? WHERE owner_id=?", (now, owner_id))
    return o


def _require_char(cur, owner_id: str, char_id: str, alive: bool = True) -> dict:
    ch = _one(cur, "SELECT * FROM hr_characters WHERE char_id=?", (char_id,))
    if ch is None or ch["owner_id"] != owner_id:
        raise HalcyonError("no such character")
    if alive and ch["status"] != "alive":
        raise HalcyonError("that character has fallen")
    return ch


def _require_item(cur, owner_id: str, item_id: str) -> dict:
    it = _one(cur, "SELECT * FROM hr_items WHERE item_id=?", (item_id,))
    if it is None or it["owner_id"] != owner_id:
        raise HalcyonError("no such item")
    if it["loc"] == "destroyed":
        raise HalcyonError("that item no longer exists")
    return it


def _open_run(cur, char_id: str) -> dict | None:
    return _one(cur, "SELECT * FROM hr_runs WHERE char_id=? AND status='open'", (char_id,))


def _check_version(it: dict, expected: int | None) -> None:
    if expected is not None and it["version"] != expected:
        raise HalcyonError("that item changed; reload")


# ── places ───────────────────────────────────────────────────────────────────
# A place is a tuple, and the only spelling of one the store accepts:
#   ("vault", i)  ("inventory", char_id, i)  ("equipped", char_id, slot_name)  ("ground", run_id)
#   ("floor", char_id) — the TOWN's ground under that character (owner's ask, 2026-11-18):
#   stored as ground under the run id "town:<char_id>", destroyed when the character
#   leaves town (a run starts, the character is opened again, or the player leaves).
TOWN_FLOOR = "town:"
def _place_cols(owner_id: str, place: tuple) -> tuple[str, str | None, str | None, int | None]:
    """(loc, char_id, run_id, slot_index) for a place, range-checked."""
    kind = place[0] if place else None
    if kind == "vault" and len(place) == 2:
        i = place[1]
        if not isinstance(i, int) or not 0 <= i < C.VAULT_SIZE:
            raise HalcyonError("no such vault slot")
        return "vault", None, None, i
    if kind == "inventory" and len(place) == 3:
        i = place[2]
        if not isinstance(i, int) or not 0 <= i < C.INVENTORY_SIZE:
            raise HalcyonError("no such inventory slot")
        return "inventory", place[1], None, i
    if kind == "equipped" and len(place) == 3:
        if place[2] not in C.EQUIP_SLOTS:
            raise HalcyonError("no such equipment slot")
        return "equipped", place[1], None, C.EQUIP_SLOTS.index(place[2])
    if kind == "ground" and len(place) == 2:
        return "ground", None, place[1], None
    if kind == "floor" and len(place) == 2:
        return "ground", None, TOWN_FLOOR + str(place[1]), None
    raise HalcyonError("not a place")


def _place_of(it: dict) -> tuple:
    if it["loc"] == "vault":
        return ("vault", it["slot_index"])
    if it["loc"] == "inventory":
        return ("inventory", it["char_id"], it["slot_index"])
    if it["loc"] == "equipped":
        return ("equipped", it["char_id"], C.EQUIP_SLOTS[it["slot_index"]])
    if it["loc"] == "ground":
        if str(it["run_id"]).startswith(TOWN_FLOOR):
            return ("floor", it["run_id"][len(TOWN_FLOOR):])
        return ("ground", it["run_id"])
    raise HalcyonError("that item is not anywhere")


def _occupant(cur, owner_id: str, cols: tuple) -> dict | None:
    loc, char_id, _run, slot = cols
    if loc == "vault":
        return _one(cur, "SELECT * FROM hr_items WHERE owner_id=? AND loc='vault' AND slot_index=?",
                    (owner_id, slot))
    if loc in ("inventory", "equipped"):
        return _one(cur, "SELECT * FROM hr_items WHERE char_id=? AND loc=? AND slot_index=?",
                    (char_id, loc, slot))
    return None                                     # the ground holds any number


def _check_fits(cur, it: dict, cols: tuple, ignore_item: str | None = None) -> None:
    """May this item sit in this place? Equipment rules live here: the slot
    family, the class, and never two of the same UNIQUE (owner's call, 2026-11-18:
    two of the same standard ring are fine, whatever their slots)."""
    loc, char_id, _run, slot = cols
    if loc != "equipped":
        return
    name = C.EQUIP_SLOTS[slot]
    if not C.slot_fits(it["base_id"], name):
        raise HalcyonError("that does not go in that slot")
    ch = _one(cur, "SELECT class_id FROM hr_characters WHERE char_id=?", (char_id,))
    if ch is not None and not C.usable_by(it["base_id"], ch["class_id"]):
        raise HalcyonError("that character's class cannot use it")
    if name in ("ring1", "ring2"):
        other = C.EQUIP_SLOTS.index("ring2" if name == "ring1" else "ring1")
        twin = _one(cur, "SELECT item_id, base_id FROM hr_items WHERE char_id=? AND loc='equipped' "
                         "AND slot_index=?", (char_id, other))
        if (twin and twin["item_id"] not in (it["item_id"], ignore_item) and twin["base_id"] == it["base_id"]
                and C.base(it["base_id"])["kind"] == "unique"):
            raise HalcyonError("you cannot wear two of the same unique")


def _set_place(cur, item_id: str, cols: tuple, now: float) -> None:
    loc, char_id, run_id, slot = cols
    cur.execute("UPDATE hr_items SET loc=?, char_id=?, run_id=?, slot_index=?, updated_at=?, "
                "version=version+1 WHERE item_id=?", (loc, char_id, run_id, slot, now, item_id))


def _move_with_swap(cur, owner_id: str, it: dict, cols: tuple, now: float) -> None:
    """Put `it` at `cols`; whatever is there takes `it`'s old place. Validates
    BOTH directions before writing anything."""
    src = (it["loc"], it["char_id"], it["run_id"], it["slot_index"])
    if src == cols:
        return
    there = _occupant(cur, owner_id, cols)
    _check_fits(cur, it, cols, ignore_item=there["item_id"] if there else None)
    if there is not None:
        if src[0] == "ground":
            raise HalcyonError("that slot is full")
        _check_fits(cur, there, src, ignore_item=it["item_id"])
        # Through limbo: the slot indexes are checked per statement.
        cur.execute("UPDATE hr_items SET loc='limbo', slot_index=NULL WHERE item_id=?", (it["item_id"],))
        _set_place(cur, there["item_id"], src, now)
    _set_place(cur, it["item_id"], cols, now)


def _destroy(cur, where_sql: str, params: tuple, reason: str, now: float) -> None:
    cur.execute(f"UPDATE hr_items SET loc='destroyed', slot_index=NULL, destroyed_reason=?, "
                f"destroyed_at=?, updated_at=?, version=version+1 "
                f"WHERE loc != 'destroyed' AND ({where_sql})", (reason, now, now) + params)


def _insert_item(cur, owner_id: str, spec: dict, origin: str, cols: tuple, now: float,
                 run_id: str | None = None, drop_id: str | None = None,
                 fused_from: list | None = None) -> str:
    item_id = _new_id()
    loc, char_id, place_run, slot = cols
    cur.execute(
        "INSERT INTO hr_items (item_id, owner_id, base_id, tier, kind, slot_count, enchants, "
        "content_version, origin, origin_run_id, origin_drop_id, fused_from, loc, char_id, run_id, "
        "slot_index, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (item_id, owner_id, spec["base_id"], spec["tier"], spec["kind"], spec["slot_count"],
         json.dumps(spec["enchants"]), C.CONTENT_VERSION, origin, run_id, drop_id,
         json.dumps(fused_from) if fused_from else None, loc, char_id, place_run, slot, now, now))
    return item_id


def _validate_spec(spec: dict) -> dict:
    """An item description from the SERVER's own generator (never a client)."""
    b = C.base(spec["base_id"])
    tier, slots, ench = spec["tier"], spec["slot_count"], spec.get("enchants", [])
    if tier not in C.TIERS:
        raise HalcyonError("no such tier")
    if not 0 <= slots <= C.MAX_ENCHANT_SLOTS or len(ench) != slots:
        raise HalcyonError("enchantments do not match the slot count")
    allowed = set(C.enchants_for(spec["base_id"]))
    for e in ench:
        if e["id"] not in allowed or not 0.0 <= float(e["q"]) <= 1.0:
            raise HalcyonError("not a valid enchantment")
    return {"base_id": spec["base_id"], "tier": tier, "kind": b["kind"], "slot_count": slots,
            "enchants": [{"id": e["id"], "q": float(e["q"])} for e in ench]}


def roll_enchants(base_id: str, slot_count: int, rng: random.Random) -> list[dict]:
    pool = C.enchants_for(base_id)
    picks = rng.sample(pool, min(slot_count, len(pool)))
    return [{"id": e, "q": rng.random()} for e in picks]


# ── owners and characters ────────────────────────────────────────────────────
def _hash_secret(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def register_owner(connect, owner_id: str, kind: str, now: float | None = None) -> str | None:
    """Create the roster's owner. For a GUEST, returns a secret — once — that the
    device keeps beside its guest id and sends on every request (design §20.1).
    Returns None for an account, or for an owner that already exists."""
    if kind not in ("account", "guest"):
        raise HalcyonError("not an owner kind")
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        if _one(cur, "SELECT owner_id FROM hr_owners WHERE owner_id=?", (owner_id,)):
            return None
        secret = secrets.token_urlsafe(24) if kind == "guest" else None
        cur.execute("INSERT INTO hr_owners (owner_id, kind, guest_secret_hash, created_at, last_seen_at) "
                    "VALUES (?,?,?,?,?)", (owner_id, kind, _hash_secret(secret) if secret else None, now, now))
        return secret


def verify_guest(connect, owner_id: str, secret: str) -> bool:
    conn = connect()
    try:
        o = _one(conn.cursor(), "SELECT kind, guest_secret_hash FROM hr_owners WHERE owner_id=?", (owner_id,))
    finally:
        conn.close()
    if not o or o["kind"] != "guest" or not o["guest_secret_hash"] or not secret:
        return False
    return secrets.compare_digest(o["guest_secret_hash"].encode(), _hash_secret(secret).encode())


def create_character(connect, owner_id: str, slot: int, class_id: str, now: float | None = None,
                     starter: list[tuple[dict, str]] | None = None) -> dict:
    """A new character, optionally with `starter` gear [(spec, equip_slot)]
    minted onto it in the SAME transaction — a character never exists without it."""
    if class_id not in C.CLASSES:
        raise HalcyonError("no such class")
    if not isinstance(slot, int) or not 0 <= slot < C.CHARACTER_SLOTS:
        raise HalcyonError("no such character slot")
    now = _now(now)
    starter = [(_validate_spec(s), e) for s, e in (starter or [])]
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        if _one(cur, "SELECT char_id FROM hr_characters WHERE owner_id=? AND slot=? AND status='alive'",
                (owner_id, slot)):
            raise HalcyonError("that slot already has a character")
        char_id = _new_id()
        cur.execute("INSERT INTO hr_characters (char_id, owner_id, slot, class_id, status, created_at) "
                    "VALUES (?,?,?,?, 'alive', ?)", (char_id, owner_id, slot, class_id, now))
        for spec, equip in starter:
            cols = _place_cols(owner_id, ("equipped", char_id, equip))
            probe = {"item_id": "", "base_id": spec["base_id"]}
            _check_fits(cur, probe, cols)
            _insert_item(cur, owner_id, spec, "grant", cols, now)
        return _one(cur, "SELECT * FROM hr_characters WHERE char_id=?", (char_id,))


def character_class(connect, owner_id: str, char_id: str) -> str:
    """Read the class for server-side dungeon generation."""
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, _now(None))
        return _require_char(cur, owner_id, char_id)["class_id"]


def grant_item(connect, owner_id: str, spec: dict, place: tuple, now: float | None = None) -> dict:
    """Mint an item from nothing — starter gear and admin grants only."""
    now = _now(now)
    spec = _validate_spec(spec)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        cols = _place_cols(owner_id, place)
        if cols[0] not in ("vault", "inventory"):
            raise HalcyonError("grants go to the vault or an inventory")
        if cols[1] is not None:
            ch = _require_char(cur, owner_id, cols[1])
            if _open_run(cur, ch["char_id"]):
                raise HalcyonError("that character is in a dungeon")
        if _occupant(cur, owner_id, cols):
            raise HalcyonError("that slot is full")
        item_id = _insert_item(cur, owner_id, spec, "grant", cols, now)
        return _item_out(_one(cur, "SELECT * FROM hr_items WHERE item_id=?", (item_id,)))


# ── runs ─────────────────────────────────────────────────────────────────────
def _close_run(cur, run: dict, status: str, now: float) -> None:
    """End a run. A normal death destroys the character and everything on it;
    normal endings destroy what was left on the run's floor. Dream runs never
    touch the character, its carried items, or their floor state. The vault is
    never touched."""
    # Dream Rifts are disposable practice instances. Their death and any future
    # completion path must never touch the character or its carried items.
    if status == "died" and not bool(run.get("practice", 0)):
        _destroy(cur, "char_id=? AND loc IN ('inventory','equipped')", (run["char_id"],), "death", now)
        _destroy(cur, "loc='ground' AND run_id=?", (run["run_id"],), "death", now)
        cur.execute("UPDATE hr_characters SET status='dead', died_at=?, death_run_id=? WHERE char_id=?",
                    (now, run["run_id"], run["char_id"]))
    elif not bool(run.get("practice", 0)):
        _destroy(cur, "loc='ground' AND run_id=?", (run["run_id"],), "run_end", now)
    cur.execute("UPDATE hr_runs SET status=?, last_event_at=? WHERE run_id=?", (status, now, run["run_id"]))


def _validate_dungeon(dungeon: dict) -> dict:
    class_id = dungeon.get("class_id", "ranger")
    if class_id not in C.CLASSES:
        raise HalcyonError("the dungeon has no such class")
    enemies = dungeon.get("enemies") or {}
    boss = dungeon.get("boss")
    if boss is not None and boss not in enemies:
        raise HalcyonError("the boss is not one of the enemies")
    drops = {}
    for drop_id, d in (dungeon.get("drops") or {}).items():
        if d.get("enemy") is not None and d["enemy"] not in enemies:
            raise HalcyonError("a drop names an enemy that is not there")
        drops[str(drop_id)] = {**_validate_spec(d), "enemy": d.get("enemy")}
    for e in enemies.values():
        if not _is_xp(e.get("xp", 0)):
            raise HalcyonError("an enemy's XP is not a whole number")
    if not _is_xp(dungeon.get("complete_xp", 0)):
        raise HalcyonError("the completion XP is not a whole number")
    level = dungeon.get("level", 1)
    if not isinstance(level, int) or isinstance(level, bool) or not 1 <= level <= 99:
        raise HalcyonError("the dungeon's level is not a level")
    mods, offers = list(dungeon.get("mods") or []), list(dungeon.get("offers") or [])
    if any(m not in C.RIFT_MODS for m in mods + offers) or set(mods) & set(offers):
        raise HalcyonError("the dungeon names a modifier it cannot")
    return {"enemies": {str(k): v for k, v in enemies.items()}, "boss": boss, "drops": drops,
            "complete_xp": dungeon.get("complete_xp", 0), "class_id": class_id,
            "level": level, "mods": mods, "offers": offers, "boss_rush": bool(dungeon.get("boss_rush")),
            # Only for the graveyard's words; nothing is decided by it.
            "name": str(dungeon.get("name") or "")[:60]}


def _is_xp(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and 0 <= v <= 100_000


def _credit_xp(cur, char_id: str, amount: int) -> None:
    """Add XP the server's own record says was earned, and the level it reaches.
    Written as each kill lands, so a recall (or a closed tab) keeps it."""
    if amount <= 0:
        return
    ch = _one(cur, "SELECT xp FROM hr_characters WHERE char_id=?", (char_id,))
    xp = ch["xp"] + amount
    cur.execute("UPDATE hr_characters SET xp=?, level=? WHERE char_id=?", (xp, C.level_for(xp), char_id))


def _cleared(cur, char_id: str) -> set:
    """The rifts (of those another rift REQUIRES) this character has felled a boss of,
    in a real run (a Dream Rift does not count). Reads only the boss id and the small
    state, never the whole dungeon."""
    want = sorted({need for need, _ in C.REQUIRES.values()})
    if not want:
        return set()
    cur.execute("SELECT dungeon_id, json_extract(dungeon, '$.boss') AS boss, state FROM hr_runs "
                f"WHERE char_id=? AND practice=0 AND dungeon_id IN ({','.join('?' * len(want))})",
                (char_id, *want))
    done = set()
    for r in _dicts(cur):
        if r["dungeon_id"] not in done and r["boss"] in json.loads(r["state"] or "{}").get("killed", []):
            done.add(r["dungeon_id"])
    return done


def _record_time(cur, run: dict, elapsed_ticks, now: float) -> None:
    """Keep the five fastest boss-kill times for this owner and rift.

    The combat simulation is intentionally client-side. This is a personal
    leaderboard, not a competitive ranking, so a claimed time is useful for the
    player's own practice without becoming an authority boundary for loot or XP.
    """
    if json.loads(run["dungeon"]).get("boss_rush"):
        return                      # a Boss Rush clear is not a clear of the rift (owner's call)
    if (not isinstance(elapsed_ticks, int) or isinstance(elapsed_ticks, bool)
            or not 0 < elapsed_ticks <= 7 * 24 * 60 * 60 * 60):
        return
    if _one(cur, "SELECT time_id FROM hr_rift_times WHERE run_id=?", (run["run_id"],)):
        return
    cur.execute("INSERT INTO hr_rift_times (time_id, owner_id, dungeon_id, run_id, time_ticks, practice, created_at) "
                "VALUES (?,?,?,?,?,?,?)",
                (_new_id(), run["owner_id"], run["dungeon_id"], run["run_id"], elapsed_ticks,
                 int(bool(run.get("practice", 0))), now))
    rows = _dicts(cur.execute("SELECT time_id FROM hr_rift_times WHERE owner_id=? AND dungeon_id=? "
                             "ORDER BY time_ticks ASC, created_at ASC", (run["owner_id"], run["dungeon_id"])))
    for row in rows[5:]:
        cur.execute("DELETE FROM hr_rift_times WHERE time_id=?", (row["time_id"],))


def _key_needed(practice: bool, boss_rush: bool) -> list[str]:
    """The keys a run spends on entry (owner's ask, 2026-11-18)."""
    return ([C.DREAM_KEY] if practice else []) + ([C.BOSS_RUSH_KEY] if boss_rush else [])


def _carried_key(cur, char_id: str, base_id: str) -> dict | None:
    """A key of this kind in the character's bag, an unlocked one first."""
    return _one(cur, "SELECT * FROM hr_items WHERE char_id=? AND loc='inventory' AND base_id=? "
                     "ORDER BY locked, slot_index LIMIT 1", (char_id, base_id))


def _clear_town_floor(cur, char_id: str, now: float) -> None:
    """Leaving town: what this character left on the town's ground is gone."""
    _destroy(cur, "loc='ground' AND run_id=?", (TOWN_FLOOR + char_id,), "left", now)


def start_run(connect, owner_id: str, char_id: str, dungeon_id: str, seed: str, dungeon: dict,
              practice: bool = False, now: float | None = None) -> dict:
    """Begin a run with a dungeon the SERVER generated. A run this character
    left open (a closed tab) is closed first, as a recall (design §13.1a).

    KEYS ARE SPENT HERE, in the run's own transaction: a Dream Rift needs a Dream
    Key in the character's bag, a Boss Rush run a Boss Rush key, and the run does
    not begin without them."""
    now = _now(now)
    dungeon = _validate_dungeon(dungeon)
    if practice and dungeon["boss_rush"]:
        raise HalcyonError("a Dream Rift has no Boss Rush")
    if dungeon["level"] == 1 and len(dungeon["mods"]) > C.START_MODS:
        raise HalcyonError(f"a run starts with at most {C.START_MODS} modifiers; each level deeper adds one")
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        ch = _require_char(cur, owner_id, char_id)
        if dungeon["class_id"] != ch["class_id"]:
            raise HalcyonError("the dungeon was made for another class")
        need = C.REQUIRES.get(dungeon_id)
        if need and need[0] not in _cleared(cur, char_id):
            raise HalcyonError(f"clear {need[1]} with this character first")
        prior = _open_run(cur, char_id)
        if prior:
            _close_run(cur, prior, "recalled", now)
        _clear_town_floor(cur, char_id, now)
        spent = []
        for base_id in _key_needed(practice, dungeon["boss_rush"]):
            key = _carried_key(cur, char_id, base_id)
            if key is None:
                raise HalcyonError("you need a Dream Key in your bag" if base_id == C.DREAM_KEY
                                   else "you need a Boss Rush key in your bag")
            _destroy(cur, "item_id=?", (key["item_id"],), "key", now)
            spent.append(key["item_id"])
        run_id = _new_id()
        cur.execute("INSERT INTO hr_runs (run_id, char_id, owner_id, dungeon_id, seed, content_version, "
                    "status, practice, started_at, last_event_at, dungeon, state) "
                    "VALUES (?,?,?,?,?,?, 'open', ?, ?,?,?,?)",
                    (run_id, char_id, owner_id, dungeon_id, str(seed), C.CONTENT_VERSION, int(bool(practice)),
                     now, now, json.dumps(dungeon), json.dumps({"killed": [], "picked": []})))
        return {"run_id": run_id, "dungeon": dungeon, "practice": bool(practice), "spent": spent}


def open_character(connect, owner_id: str, char_id: str, now: float | None = None) -> dict:
    """The character is opened in town: an open run it left behind ends as a recall."""
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        ch = _require_char(cur, owner_id, char_id)
        run = _open_run(cur, char_id)
        if run:
            _close_run(cur, run, "recalled", now)
        _clear_town_floor(cur, char_id, now)
        return ch


def leave_town(connect, owner_id: str, char_id: str, now: float | None = None) -> None:
    """The player left town for the main menu: the town's ground is cleared."""
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        _require_char(cur, owner_id, char_id, alive=False)
        _clear_town_floor(cur, char_id, now)


class _Refused(Exception):
    pass


# What the page may add to a death (the cause and its tallies). It only DESCRIBES the
# run, for the graveyard: nothing is credited from it, so a bad value costs nothing
# but a strange gravestone. Each field is bounded; anything else is dropped.
_DEATH_TEXT = {"src": 40}
_DEATH_NUMS = {"hit": 100_000, "taken": 10_000_000, "kills": 100_000, "ticks": 100_000_000}


def _write_death(cur, run: dict, dungeon: dict, state: dict, summary) -> None:
    """The graveyard's death screen, written while the character still carries
    everything (the run's close destroys it next): what it wore and carried, as
    item specs, and where it fell. The server's own facts win over the page's."""
    page = summary if isinstance(summary, dict) else {}
    out = {}
    for k, n in _DEATH_TEXT.items():
        if isinstance(page.get(k), str):
            out[k] = page[k][:n]
    for k, cap in _DEATH_NUMS.items():
        v = page.get(k)
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v == v:
            out[k] = max(0, min(cap, round(float(v), 1)))
    cur.execute("SELECT * FROM hr_items WHERE char_id=? AND loc IN ('inventory','equipped')", (run["char_id"],))
    items = []
    for row in _dicts(cur):
        it = _item_out(row)
        items.append({k: it.get(k) for k in ("base_id", "tier", "kind", "slot_count", "enchants", "loc",
                                             "equip_slot", "slot_index", "origin_run_id")})
    out.update({"dungeon_id": run["dungeon_id"], "dungeon_name": dungeon.get("name") or run["dungeon_id"],
                "depth": dungeon.get("level", 1), "mods": list(dungeon.get("mods") or []),
                "items": items, "run_id": run["run_id"]})
    cur.execute("UPDATE hr_characters SET death_summary=? WHERE char_id=?", (json.dumps(out), run["char_id"]))


def _apply_one(cur, run: dict, dungeon: dict, state: dict, ev: dict, now: float) -> str | None:
    """Apply one run event. Validates fully BEFORE writing, so a refusal never
    leaves half an event behind. Returns the run's new status if the event ended it."""
    owner, char_id, run_id = run["owner_id"], run["char_id"], run["run_id"]
    practice = bool(run.get("practice", 0))
    t = ev.get("type")
    if t == "kill":
        e = str(ev.get("enemy"))
        if e not in dungeon["enemies"] or e in state["killed"]:
            raise _Refused
        parent = dungeon["enemies"][e].get("parent")
        if parent is not None and parent not in state["killed"]:
            raise _Refused                           # a Splinter is only out once its Splitter fell
        state["killed"].append(e)
        if not practice:
            _credit_xp(cur, char_id, dungeon["enemies"][e].get("xp", 0))
        if e == dungeon.get("boss"):
            # The boss's fall clears the dungeon; its bonus is credited here so
            # a recall after the kill keeps it. Practice runs earn nothing.
            if not practice:
                _credit_xp(cur, char_id, dungeon.get("complete_xp", 0))
            # Each level's boss pays its own clear bonus; the time is the FIRST
            # level's (a deeper run is not a faster clear of the rift).
            if dungeon.get("level", 1) == 1:
                _record_time(cur, run, ev.get("elapsed_ticks"), now)
    elif t == "pickup":
        if practice:
            raise _Refused
        d = str(ev.get("drop"))
        drop = dungeon["drops"].get(d)
        if drop is None or d in state["picked"]:
            raise _Refused
        if drop["enemy"] is not None and drop["enemy"] not in state["killed"]:
            raise _Refused                           # nothing dropped it yet
        try:
            cols = _place_cols(owner, ("inventory", char_id, ev.get("slot")))
        except HalcyonError:
            raise _Refused
        if _occupant(cur, owner, cols):
            raise _Refused
        state["picked"].append(d)
        _insert_item(cur, owner, drop, "drop", cols, now, run_id=run_id, drop_id=d)
    elif t == "lock":
        # LOCKING an item found THIS run (2026-11-19: refusing it read as a bug). The
        # page has no item id for it yet, so it names the drop, as a move does. Any
        # item the owner has may be named; a lock is never a move.
        if ev.get("item") is None and ev.get("drop") is not None:
            it = _one(cur, "SELECT * FROM hr_items WHERE origin_run_id=? AND origin_drop_id=?",
                      (run_id, str(ev["drop"])))
        else:
            it = _one(cur, "SELECT * FROM hr_items WHERE item_id=?", (str(ev.get("item")),))
        if it is None or it["owner_id"] != owner or not isinstance(ev.get("locked"), bool):
            raise _Refused
        cur.execute("UPDATE hr_items SET locked=?, updated_at=? WHERE item_id=?",
                    (1 if ev["locked"] else 0, now, it["item_id"]))
    elif t in ("pickup_item", "drop_item", "move"):
        if practice and t == "drop_item":
            raise _Refused
        # An item picked up THIS run may be named by its drop: the page has no item id
        # for it until the run's reports land, and within one run a drop names exactly
        # one item (the UNIQUE index on origin_run_id + origin_drop_id).
        if ev.get("item") is None and ev.get("drop") is not None:
            it = _one(cur, "SELECT * FROM hr_items WHERE origin_run_id=? AND origin_drop_id=?",
                      (run_id, str(ev["drop"])))
        else:
            it = _one(cur, "SELECT * FROM hr_items WHERE item_id=?", (str(ev.get("item")),))
        if it is None or it["owner_id"] != owner:
            raise _Refused
        on_me = it["loc"] in ("inventory", "equipped") and it["char_id"] == char_id
        on_floor = it["loc"] == "ground" and it["run_id"] == run_id
        if t == "drop_item":
            if not on_me or it.get("locked"):
                raise _Refused
            _set_place(cur, it["item_id"], ("ground", None, run_id, None), now)
            return None
        if t == "pickup_item" and not on_floor:
            raise _Refused
        if t == "move" and not on_me:
            raise _Refused
        to = ev.get("to") if t == "move" else ["inventory", ev.get("slot")]
        if not isinstance(to, (list, tuple)) or len(to) != 2 or to[0] not in ("inventory", "equipped"):
            raise _Refused
        try:
            cols = _place_cols(owner, (to[0], char_id, to[1]))
            _move_with_swap(cur, owner, it, cols, now)
        except HalcyonError:
            raise _Refused
    elif t == "death":
        if not practice:
            _write_death(cur, run, dungeon, state, ev.get("summary"))
        return "died"
    elif t == "recall":
        return "recalled"
    elif t == "complete":
        if dungeon["boss"] is None or dungeon["boss"] not in state["killed"]:
            raise _Refused
        return "completed"
    else:
        raise _Refused
    return None


def apply_events(connect, owner_id: str, run_id: str, events: list[dict], now: float | None = None) -> dict:
    """Apply a batch of run events (design §18.4), as one transaction.

    Each event carries `seq`, numbered from 1 per run. Anything at or below the
    run's last applied number is skipped, so re-sending is always safe; a gap
    stops the batch there (the client re-sends from where the server is). An
    event the server will not accept is RECORDED AS REFUSED and the sequence
    moves past it — a client stuck re-sending a refused event forever would
    never deliver anything after it. A closed run accepts nothing.
    """
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        run = _one(cur, "SELECT * FROM hr_runs WHERE run_id=?", (run_id,))
        if run is None or run["owner_id"] != owner_id:
            raise HalcyonError("no such run")
        if run["status"] != "open":
            return {"status": run["status"], "last_seq": run["last_seq"], "refused": json.loads(run["refused"])}
        _require_owner(cur, owner_id, now)
        dungeon, state = json.loads(run["dungeon"]), json.loads(run["state"])
        refused = json.loads(run["refused"])
        last, status = run["last_seq"], "open"
        for ev in sorted((e for e in events if isinstance(e, dict) and isinstance(e.get("seq"), int)),
                         key=lambda e: e["seq"]):
            if ev["seq"] <= last:
                continue
            if ev["seq"] != last + 1:
                break
            try:
                ended = _apply_one(cur, run, dungeon, state, ev, now)
            except _Refused:
                refused.append(ev["seq"])
                ended = None
            last = ev["seq"]
            if ended:
                status = ended
                break
        cur.execute("UPDATE hr_runs SET last_seq=?, last_event_at=?, state=?, refused=? WHERE run_id=?",
                    (last, now, json.dumps(state), json.dumps(refused), run_id))
        if status != "open":
            _close_run(cur, run, status, now)
        return {"status": status, "last_seq": last, "refused": refused}


def descend(connect, owner_id: str, run_id: str, mod: str, from_level: int, make,
            now: float | None = None) -> dict:
    """Go deeper (design §14.6): the current level's boss is dead and `mod` is one
    of the modifiers its portal offered. `make(dungeon_id, seed, class_id, mods,
    level)` generates the next level (the generator lives in dungeon.py, which imports this module).

    The new level's enemies and drops are ADDED to the run's record, so every id
    the run ever had stays checkable and a drop's UNIQUE index (per run) still
    holds; the boss, the bonus and the offers become the new level's. What the
    player left on the floor stays behind and is destroyed, as on any way out.
    Safe to repeat: asked again for a descent that already happened (the answer was
    lost), it hands back the level the run is on."""
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        run = _one(cur, "SELECT * FROM hr_runs WHERE run_id=?", (run_id,))
        if run is None or run["owner_id"] != owner_id:
            raise HalcyonError("no such run")
        _require_owner(cur, owner_id, now)
        dungeon, state = json.loads(run["dungeon"]), json.loads(run["state"])
        level, mods = dungeon.get("level", 1), list(dungeon.get("mods") or [])
        rush = {"boss_rush": True} if dungeon.get("boss_rush") else {}   # Boss Rush holds at every level
        if run["status"] == "open" and level == from_level + 1 and mod in mods:
            return make(run["dungeon_id"], run["seed"], dungeon["class_id"], mods, level, **rush)  # a retry
        if run["status"] != "open":
            raise HalcyonError("that run is over")
        if level != from_level:
            raise HalcyonError("the run is not on that level")
        if dungeon.get("boss") is None or dungeon["boss"] not in state["killed"]:
            raise HalcyonError("the way deeper opens when the boss falls")
        if mod not in (dungeon.get("offers") or []):
            raise HalcyonError("that modifier was not offered")
        d = make(run["dungeon_id"], run["seed"], dungeon["class_id"], mods + [mod], level + 1, **rush)
        nxt = _validate_dungeon(d)
        if nxt["class_id"] != dungeon["class_id"] or nxt["boss_rush"] != bool(dungeon.get("boss_rush")) or set(nxt["enemies"]) & set(dungeon["enemies"])                 or set(nxt["drops"]) & set(dungeon["drops"]):
            raise HalcyonError("the next level does not fit this run")
        merged = {**nxt, "enemies": {**dungeon["enemies"], **nxt["enemies"]},
                  "drops": {**dungeon["drops"], **nxt["drops"]}}
        if not bool(run.get("practice", 0)):
            _destroy(cur, "loc='ground' AND run_id=?", (run_id,), "run_end", now)
        cur.execute("UPDATE hr_runs SET dungeon=?, last_event_at=? WHERE run_id=?",
                    (json.dumps(merged), now, run_id))
        return d


def sweep_runs(connect, now: float | None = None, max_idle: float = 24 * 3600) -> int:
    """Close runs nobody has touched for `max_idle` as recalls. Tidiness only:
    opening the character closes its run anyway."""
    now = _now(now)
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT run_id, owner_id FROM hr_runs WHERE status='open' AND last_event_at < ?",
                    (now - max_idle,))
        stale = _dicts(cur)
    finally:
        conn.close()
    closed = 0
    for r in stale:
        with _tx(connect, r["owner_id"]) as cur:
            run = _one(cur, "SELECT * FROM hr_runs WHERE run_id=?", (r["run_id"],))
            if run and run["status"] == "open" and run["last_event_at"] < now - max_idle:
                _close_run(cur, run, "recalled", now)
                closed += 1
    return closed


# ── town ─────────────────────────────────────────────────────────────────────
def _town_item(cur, owner_id: str, item_id: str, expected_version: int | None,
               floor: bool = False) -> dict:
    """An item town operations may touch. `floor`: the town's ground counts too (a
    move may pick an item up from it; nothing else works on what lies there)."""
    it = _require_item(cur, owner_id, item_id)
    _check_version(it, expected_version)
    on_floor = it["loc"] == "ground" and str(it["run_id"]).startswith(TOWN_FLOOR)
    if it["loc"] not in ("vault", "inventory", "equipped") and not (floor and on_floor):
        raise HalcyonError("that item is not in town")
    char_id = it["run_id"][len(TOWN_FLOOR):] if on_floor else it["char_id"]
    if char_id is not None:
        _require_char(cur, owner_id, char_id)
        if _open_run(cur, char_id):
            raise HalcyonError("that character is in a dungeon")
    return it


def move_item(connect, owner_id: str, item_id: str, to: tuple, expected_version: int | None = None,
              now: float | None = None) -> dict:
    """Vault <-> inventory <-> equipment <-> the town's ground, swapping with
    whatever is there (the ground holds any number, so nothing swaps onto it)."""
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        it = _town_item(cur, owner_id, item_id, expected_version, floor=True)
        to = tuple(to)
        cols = _place_cols(owner_id, to)
        if cols[0] == "ground":
            if to[0] != "floor":
                raise HalcyonError("that is not the town's ground")
            if it.get("locked"):
                raise HalcyonError("that item is locked")
            if it["loc"] == "ground":
                raise HalcyonError("that item is already on the ground")
        whose = to[1] if to[0] == "floor" else cols[1]
        if whose is not None:
            _require_char(cur, owner_id, str(whose))
            if _open_run(cur, str(whose)):
                raise HalcyonError("that character is in a dungeon")
        _move_with_swap(cur, owner_id, it, cols, now)
        return _item_out(_one(cur, "SELECT * FROM hr_items WHERE item_id=?", (item_id,)))


def discard(connect, owner_id: str, item_id: str, expected_version: int | None = None,
            now: float | None = None) -> None:
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        it = _town_item(cur, owner_id, item_id, expected_version)
        if it.get("locked"):
            raise HalcyonError("that item is locked")
        _destroy(cur, "item_id=?", (item_id,), "discard", now)


def set_lock(connect, owner_id: str, item_id: str, locked: bool, now: float | None = None) -> dict:
    """Lock or unlock an item (design §19.1): a locked item cannot be discarded,
    fused or dropped on a run's floor, and Sort leaves it where it is. It is not a
    move, so the item's version does not change — anywhere, even mid-run."""
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        _require_item(cur, owner_id, item_id)
        cur.execute("UPDATE hr_items SET locked=?, updated_at=? WHERE item_id=?", (1 if locked else 0, now, item_id))
        return _item_out(_one(cur, "SELECT * FROM hr_items WHERE item_id=?", (item_id,)))


def fuse(connect, owner_id: str, a: str, b: str, rng: random.Random | None = None,
         expected_versions: tuple[int, int] | None = None, now: float | None = None) -> dict:
    """Two identical items in, one rerolled item out (design §11.7), all or
    nothing. The result takes the first item's place."""
    if a == b:
        raise HalcyonError("pick two different items")
    rng = rng or random.Random(secrets.randbits(64))
    now = _now(now)
    with _tx(connect, owner_id) as cur:
        _require_owner(cur, owner_id, now)
        ev = expected_versions or (None, None)
        ia = _town_item(cur, owner_id, a, ev[0])
        ib = _town_item(cur, owner_id, b, ev[1])
        if ia.get("locked") or ib.get("locked"):
            raise HalcyonError("a locked item cannot be fused")
        if ia["kind"] == "key" or ib["kind"] == "key":
            raise HalcyonError("keys do not fuse")
        for k in ("base_id", "tier", "kind", "slot_count"):
            if ia[k] != ib[k]:
                raise HalcyonError("only identical items fuse")
        slots = ia["slot_count"]
        for gain, p in C.FUSE_SLOT_GAIN:
            if rng.random() < p:
                slots = min(C.MAX_ENCHANT_SLOTS, slots + gain)
                break
        spec = {"base_id": ia["base_id"], "tier": ia["tier"], "kind": ia["kind"], "slot_count": slots,
                "enchants": roll_enchants(ia["base_id"], slots, rng)}
        spec["slot_count"] = len(spec["enchants"])     # a small pool can cap it
        place = (ia["loc"], ia["char_id"], ia["run_id"], ia["slot_index"])
        _destroy(cur, "item_id IN (?, ?)", (a, b), "fusion", now)
        new_id = _insert_item(cur, owner_id, spec, "fusion", place, now, fused_from=[a, b])
        return _item_out(_one(cur, "SELECT * FROM hr_items WHERE item_id=?", (new_id,)))


# ── reading and pruning ──────────────────────────────────────────────────────
FALLEN_SHOWN = 30                                   # the graveyard lists the newest this many


def owner_view(connect, owner_id: str) -> dict:
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM hr_characters WHERE owner_id=? ORDER BY created_at", (owner_id,))
        chars = _dicts(cur)
        cur.execute("SELECT * FROM hr_items WHERE owner_id=? AND loc != 'destroyed'", (owner_id,))
        items = [_item_out(r) for r in _dicts(cur)]
        cur.execute("SELECT run_id, char_id FROM hr_runs WHERE owner_id=? AND status='open'", (owner_id,))
        runs = {r["char_id"]: r["run_id"] for r in _dicts(cur)}
        cur.execute("SELECT dungeon_id, time_ticks, practice FROM hr_rift_times "
                    "WHERE owner_id=? ORDER BY dungeon_id, time_ticks, created_at", (owner_id,))
        times = {}
        for row in _dicts(cur):
            times.setdefault(row["dungeon_id"], []).append({
                "time_ticks": row["time_ticks"], "practice": bool(row["practice"]),
            })
        for c in chars:
            if c["status"] == "alive":
                c["cleared"] = sorted(_cleared(cur, c["char_id"]))
    finally:
        conn.close()
    fallen = []
    for c in sorted((c for c in chars if c["status"] == "dead"), key=lambda c: -(c["died_at"] or 0))[:FALLEN_SHOWN]:
        c = dict(c)
        c["death_summary"] = json.loads(c["death_summary"]) if c.get("death_summary") else None
        fallen.append(c)
    return {"characters": [c for c in chars if c["status"] == "alive"],
            "fallen": fallen, "fallen_count": sum(1 for c in chars if c["status"] == "dead"),
            # THE ONE RECORD (owner's call, 2026-11-18): the best level any character on
            # the account has reached, alive or fallen.
            "best_level": max((c["level"] for c in chars), default=0),
            "items": items, "open_runs": runs, "leaderboards": times}


def prune_guests(connect, now: float | None = None, max_idle: float = 24 * 3600) -> int:
    """Remove guest rosters idle for `max_idle` (design §7.1) — every row, not
    tombstones: a pruned guest has nobody to answer "where did it go" for."""
    now = _now(now)
    conn = connect()
    try:
        cur = conn.cursor()
        cur.execute("SELECT owner_id FROM hr_owners WHERE kind='guest' AND last_seen_at < ?", (now - max_idle,))
        gone = [r["owner_id"] for r in _dicts(cur)]
    finally:
        conn.close()
    pruned = 0
    for owner in gone:
        with _tx(connect, owner) as cur:
            o = _one(cur, "SELECT last_seen_at FROM hr_owners WHERE owner_id=?", (owner,))
            if not o or o["last_seen_at"] >= now - max_idle:
                continue                             # came back while we looked
            for table in ("hr_items", "hr_runs", "hr_rift_times", "hr_characters", "hr_owners"):
                cur.execute(f"DELETE FROM {table} WHERE owner_id=?", (owner,))
            pruned += 1
    return pruned
