"""Halcyon Rift dungeon generator — runs on the SERVER only (design §18.2).

There is exactly one generator and one loot roller, and they are here: the server
generates a run's dungeon, stores the parts it must check claims against (enemies,
drops — `store.start_run`), and sends the whole thing to the browser, which only
simulates it. The browser never generates anything.

Shape (design §14.2): a LINEAR sequence of authored room templates — entrance,
combat rooms, boss room — laid left to right and joined by three-tile corridors.
Variation is template choice, order, left-to-right MIRRORING (never rotation: art
direction §7.4), the enemy type at each spawn point, and the drops.

Tiles (one character each, a row is a string):
  '#' wall / void   — blocks movement and projectiles
  'o' rock          — blocks movement and projectiles (cover)
  '~' water         — blocks movement, projectiles fly over it
  '.' floor
Template-only markers, replaced by floor when laid: 'E' enemy spawn, 'B' boss
spawn, 'S' the player's start. Healing orbs are not placed: they DROP from
enemies (owner's ask, 2026-11-18), about one a rift.

GREYBOX: the templates, odds and loot table are placeholders for play-testing.
"""
from __future__ import annotations

import random
import secrets
from collections import deque

from halcyon import content as C
from halcyon import store

# Every template has an ODD number of rows, so its middle row is the map's middle
# row once vertically centred; the doors (three tiles, middle row +/- 1) are cut
# there. A template's first and last columns on those rows must be floor.
ENTRANCE = [
    "..........",
    "..........",
    "..........",
    "..........",
    "....S.....",
    "..........",
    "..........",
    "..........",
    "..........",
]

COMBAT = [
    [
        "................",
        "..E..........E..",
        "....oo..E.~~....",
        "....oo....~~....",
        "................",
        "......E.........",
        "................",
        "...~~.....oo....",
        "...~~...E.oo..E.",
        "................",
        "................",
    ],
    [
        "................",
        ".E....~~~~....E.",
        "......~~~~.E....",
        "................",
        "...o........o...",
        "......E..E......",
        "...o........o...",
        "................",
        "......~~~~.E....",
        "......~~~~....E.",
        "................",
    ],
    [
        "..................",
        "..oo..........oo..",
        "..oo...E.E....oo..",
        "..................",
        "......~~~~~~......",
        ".E....~~~~~~....E.",
        "......~~~~~~......",
        "..................",
        "..oo......E...oo..",
        "..oo....E.....oo..",
        "..................",
    ],
    [
        "..............",
        "..E....~~.....",
        ".....E.~~...E.",
        "..o....~~.....",
        "..o...........",
        "........E.....",
        "..o...........",
        "..o....~~.....",
        ".....E.~~...E.",
        "..............",
        "..............",
    ],
    [
        "....................",
        "...E............E...",
        "........oooo.E......",
        "....................",
        "..~~............~~..",
        "..~~....E..E....~~..",
        "..~~............~~..",
        "....................",
        "........oooo.E......",
        "................E...",
        "....................",
    ],
]

BOSS_ROOM = [
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
    "......................",
    ".........B............",
    "......................",
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
]

CORRIDOR = 3
# MODIFIERS PAY XP TOO (owner's ask, 2026-11-19: "it should increase it a bit"): each
# modifier adds MOD_XP of the level's whole XP. Each enemy's share is rounded DOWN, and the
# clear bonus takes up what the rounding left, so the TOTAL is right (an enemy worth 4
# would round 4.4 back to 4 and one modifier would pay nothing for it).
MOD_XP = 0.10
# The Shallows (design §14.4): the gentlest dungeon. Four combat rooms.
# `complete_xp` is the bonus for finishing it (design §10.1); each enemy's own XP
# is content.ENEMY_XP, written onto the enemy here so the run keeps what it was worth.
DUNGEONS = {"shallows": {"name": "The Shallows", "boss_name": "The Tidewarden", "combat_rooms": 4, "complete_xp": 30}}

ENEMY_WEIGHTS = (("chaser", 40), ("shooter", 35), ("radial", 25))
# A heal orb drops from an ordinary enemy at this chance: about one a rift (0-2 is
# the usual spread). The boss never drops one — the fight is over.
HEAL_CHANCE = 0.035
# Bags hold at most this many items (the page's loot panel is one row of eight).
BAG_MAX = 8
RANGER_LOOT = (("shortbow", 16), ("longbow", 14), ("leather_vest", 22), ("volley_quiver", 14),
               ("band_of_vigor", 14), ("band_of_focus", 14))
PALADIN_LOOT = (("mace", 16), ("greatsword", 14), ("plate_armor", 22), ("stillness_orb", 14),
                ("band_of_vigor", 14), ("band_of_focus", 14))
DIVINER_LOOT = (("wand", 16), ("starstaff", 14), ("seer_robes", 22), ("star_tome", 14),
                ("band_of_vigor", 14), ("band_of_focus", 14))
NINJA_LOOT = (("shuriken", 16), ("kunai", 14), ("shadow_garb", 22), ("mirror_charm", 14),
              ("band_of_vigor", 14), ("band_of_focus", 14))
# UNIQUES DROP ONLY FROM BOSSES (owner's ask, 2026-11-18): the "unique" row of the
# boss's quality table (content.QUALITY). The loot tables themselves are in content.py.
UNIQUE_LOOT = {"ranger": (("kingfisher_eye", 1), ("tidecaller", 1), ("repeater", 1)),
               "paladin": (("kingfisher_eye", 1),), "diviner": (("kingfisher_eye", 1),),
               "ninja": (("kingfisher_eye", 1),)}
# Kept as the complete content list for audits and content tests. A run uses the
# class-specific table below, so a Ranger never receives a Paladin's starter gear.
LOOT = RANGER_LOOT + PALADIN_LOOT + DIVINER_LOOT + NINJA_LOOT + tuple(x for t in UNIQUE_LOOT.values() for x in t)
LOOT_BY_CLASS = {"ranger": RANGER_LOOT, "paladin": PALADIN_LOOT, "diviner": DIVINER_LOOT, "ninja": NINJA_LOOT}
# Enchantment slots on a drop (owner's table, 2026-11-18), set by the CUMULATIVE
# chance of at least n slots: 1+ 50%, 2+ 18.75% (50% x 37.5%), 3+ 4.6875% (x 25%),
# 4 0.5859% (x 12.5%). As one weighted roll (in 2048ths) that is exactly
# 0: 50%, 1: 31.25%, 2: 14.0625%, 3: 4.1016%, 4: 0.5859%.
SLOT_ODDS = ((0, 1024), (1, 640), (2, 288), (3, 84), (4, 12))


def _pick(rng: random.Random, table) -> object:
    total = sum(w for _, w in table)
    r = rng.random() * total
    for v, w in table:
        r -= w
        if r < 0:
            return v
    return table[-1][0]


def _item(rng: random.Random, tier: int, class_id: str, unique: bool = False,
          exclude: frozenset = frozenset()) -> dict:
    # ONE ENEMY NEVER DROPS THE SAME ITEM TWICE (owner's ask, 2026-11-18): what it
    # already dropped is left out. A unique the boss already gave becomes a standard
    # item instead (a class may have only one unique).
    left = lambda t: tuple((b, w) for b, w in t if b not in exclude)
    table = left(UNIQUE_LOOT.get(class_id, ())) if unique else ()
    table = table or left(LOOT_BY_CLASS[class_id]) or LOOT_BY_CLASS[class_id]
    base_id = _pick(rng, table)
    slots = _pick(rng, SLOT_ODDS)
    if C.base(base_id)["kind"] == "unique":
        tier = 1                  # a unique is its own thing, not a rung on the tier ladder
    return {"base_id": base_id, "tier": tier, "slot_count": slots,
            "enchants": store.roll_enchants(base_id, slots, rng)}


def _mirror(rows: list[str]) -> list[str]:
    return [r[::-1] for r in rows]


# GOING DEEPER (design §14.6): a level's boss opens the way home AND a portal
# deeper, which offers three modifiers the run does not have yet; the one picked
# is added and the next level is generated. Deeper levels are SHORTER and carry a
# small base scale on enemy health; their ids are prefixed ("L2-e1") so every
# enemy and drop id stays unique across the whole run (the store keeps them all,
# and a drop's UNIQUE index is per run). Level 1 is exactly what it always was.
MAX_LEVEL = 5
DEEP_ROOMS = 2
LEVEL_HP = 0.15
OFFERS = 3
# Swarming (owner's wording, 2026-11-18: "more enemies spawn", the boss's room
# included): half again as many in each combat room, and a few in the boss's.
SWARM_ROOM = 0.5
SWARM_BOSS = 3


def mod_scale(mods: list[str], level: int = 1) -> dict:
    """What the run's modifiers (and its depth) do to the enemies. Multipliers are
    multiplied together; wards and the death ring are flags the sim reads."""
    out = {"hp": 1.0, "dmg": 1.0, "speed": 1.0, "shot": 1.0, "cadence": 1.0,
           "ward": 0, "ward_boss": 0, "volatile": 0}
    for m in mods:
        spec = C.RIFT_MODS[m]
        for k, v in spec["scale"].items():
            out[k] *= v
        if "ward" in spec:
            out["ward"], out["ward_boss"] = spec["ward"]
        if spec.get("volatile"):
            out["volatile"] = 1
    out["hp"] *= 1 + LEVEL_HP * (level - 1)
    return out


def offers_for(dungeon_id: str, seed: str, mods, level: int) -> list[str]:
    """The modifiers the portal out of `level` offers: three the run does not have,
    from the run's seed — the same every time it is asked (a retried descent)."""
    if level >= MAX_LEVEL:
        return []
    left = sorted(m for m in C.RIFT_MODS if m not in set(mods))
    return random.Random(f"{dungeon_id}:{seed}:offers{level}").sample(left, min(OFFERS, len(left)))


def _swarm_spots(rng: random.Random, t: list[str], taken: list[tuple[int, int]], n: int) -> list[tuple[int, int]]:
    """`n` floor tiles in a template for extra enemies: clear of its side walls (so
    nothing waits in a doorway) and of every other spawn."""
    w = len(t[0])
    spots = [(c, r) for r, row in enumerate(t) for c, ch in enumerate(row)
             if ch == "." and 3 <= c < w - 3 and 1 <= r < len(t) - 1]
    rng.shuffle(spots)
    out = []
    for c, r in spots:
        if len(out) >= n:
            break
        if all((c - x) ** 2 + (r - y) ** 2 >= 4 for x, y in taken + out):
            out.append((c, r))
    return out


def generate(dungeon_id: str, seed: str | None = None, class_id: str = "ranger",
             mods: list[str] | tuple = (), level: int = 1, boss_rush: bool = False) -> dict:
    """One level of a run's dungeon, as JSON-safe data. BOSS RUSH (owner's ask,
    2026-11-18) drops the combat rooms at every level: the entrance opens straight
    onto the boss's room."""
    if dungeon_id not in DUNGEONS:
        raise store.HalcyonError("no such dungeon")
    if class_id not in C.CLASSES:
        raise store.HalcyonError("no such class")
    if not isinstance(level, int) or not 1 <= level <= MAX_LEVEL:
        raise store.HalcyonError("no such level")
    mods = sorted(set(mods))
    if any(m not in C.RIFT_MODS for m in mods):
        raise store.HalcyonError("no such rift modifier")
    rarity = len(mods)
    xp_mult = 1 + MOD_XP * len(mods)
    seed = seed or secrets.token_hex(8)
    rng = random.Random(f"{dungeon_id}:{seed}" if level == 1 else f"{dungeon_id}:{seed}:L{level}")
    swarm = random.Random(f"{dungeon_id}:{seed}:swarm{level}") if "swarming" in mods else None
    pre = "" if level == 1 else f"L{level}-"
    spec = DUNGEONS[dungeon_id]

    combat = rng.sample(COMBAT, spec["combat_rooms"] if level == 1 else DEEP_ROOMS)
    if boss_rush:
        combat = []
    rooms = [("entrance", ENTRANCE)] + [("combat", t) for t in combat] + [("boss", BOSS_ROOM)]
    rooms = [(k, _mirror(t) if rng.random() < 0.5 else list(t)) for k, t in rooms]

    height = max(len(t) for _, t in rooms) + 2
    mid = height // 2
    width = sum(len(t[0]) + 2 for _, t in rooms) + CORRIDOR * (len(rooms) - 1)
    grid = [["#"] * width for _ in range(height)]

    enemies, pickups, room_spans = {}, [], []
    start = boss = None
    x = 0

    def add(etype: str, n: int, gx: int, gy: int) -> str:
        eid = f"{pre}boss" if etype == "boss" else f"{pre}e{sum(1 for k in enemies if not k.endswith('boss')) + 1}"
        enemies[eid] = {"type": etype, "room": n, "xp": int(C.ENEMY_XP[etype] * xp_mult + 1e-9), "x": gx + 0.5, "y": gy + 0.5}
        return eid

    for n, (kind, t) in enumerate(rooms):
        h, w = len(t), len(t[0])
        top = (height - (h + 2)) // 2
        spawns = []
        for r, row in enumerate(t):
            for c, ch in enumerate(row):
                gx, gy = x + 1 + c, top + 1 + r
                grid[gy][gx] = ch if ch in "o~." else "."
                if ch == "S":
                    start = {"x": gx + 0.5, "y": gy + 0.5}
                elif ch in "EB":
                    spawns.append((c, r))
                    eid = add("boss" if ch == "B" else _pick(rng, ENEMY_WEIGHTS), n, gx, gy)
                    if ch == "B":
                        boss = eid
        if swarm and kind in ("combat", "boss"):
            extra = SWARM_BOSS if kind == "boss" else -(-len(spawns) * SWARM_ROOM // 1)
            for c, r in _swarm_spots(swarm, t, spawns, int(extra)):
                add(_pick(swarm, ENEMY_WEIGHTS), n, x + 1 + c, top + 1 + r)
        if n > 0:                                    # door in the left wall
            for dy in (-1, 0, 1):
                grid[mid + dy][x] = "."
        if n < len(rooms) - 1:                       # door in the right wall + corridor
            for dy in (-1, 0, 1):
                for cx in range(x + w + 1, x + w + 2 + CORRIDOR + 1):
                    grid[mid + dy][cx] = "."
        room_spans.append({"kind": kind, "x0": x + 1, "x1": x + 1 + w})
        x += w + 2 + CORRIDOR

    drops, n_drop = {}, 0
    for eid, e in enemies.items():
        is_boss = e["type"] == "boss"
        n = _pick(rng, C.DROP_COUNT[e["type"]])               # how many items: one roll
        if not is_boss and rng.random() < HEAL_CHANCE:           # a heal orb, dropped where it falls
            pickups.append({"id": f"{pre}h{len(pickups) + 1}", "kind": "heal", "enemy": eid})
        quality = C.quality_table("boss" if is_boss else "enemy", rarity)
        dropped: set[str] = set()
        for _ in range(min(n, BAG_MAX)):
            q = _pick(rng, quality)                          # what each is: one roll
            unique = q == "unique"
            it = _item(rng, 1 if unique else int(q[1:]), class_id, unique, frozenset(dropped))
            dropped.add(it["base_id"])
            n_drop += 1
            drops[f"{pre}d{n_drop}"] = {**it, "enemy": eid}
        if is_boss:                                          # the keys: their own stream
            keys = random.Random(f"{dungeon_id}:{seed}:keys{level}")
            for key, chance in C.KEY_DROPS:
                if keys.random() < chance and not (boss_rush and key == C.BOSS_RUSH_KEY):
                    n_drop += 1
                    drops[f"{pre}d{n_drop}"] = {"base_id": key, "tier": 1, "slot_count": 0, "enchants": [],
                                               "enemy": eid}

    base = spec["complete_xp"] + sum(C.ENEMY_XP[e["type"]] for e in enemies.values())
    complete_xp = round(base * xp_mult) - sum(e["xp"] for e in enemies.values())
    return {"id": dungeon_id, "name": spec["name"], "boss_name": spec["boss_name"], "seed": seed, "width": width, "height": height,
            "tiles": ["".join(r) for r in grid], "start": start, "rooms": room_spans, "door_y": mid,
            "enemies": enemies, "boss": boss, "drops": drops, "pickups": pickups,
            "complete_xp": complete_xp, "class_id": class_id,
            "mods": mods, "scale": mod_scale(mods, level), "level": level,
            "offers": offers_for(dungeon_id, seed, mods, level), "boss_rush": bool(boss_rush)}


def walkable(d: dict, x: int, y: int) -> bool:
    return 0 <= y < d["height"] and 0 <= x < d["width"] and d["tiles"][y][x] == "."


def reachable(d: dict) -> set[tuple[int, int]]:
    """Every floor tile a player can walk to from the start."""
    sx, sy = int(d["start"]["x"]), int(d["start"]["y"])
    seen, q = {(sx, sy)}, deque([(sx, sy)])
    while q:
        x, y = q.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if (nx, ny) not in seen and walkable(d, nx, ny):
                seen.add((nx, ny))
                q.append((nx, ny))
    return seen
