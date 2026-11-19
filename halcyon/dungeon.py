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
# The Shallows (design §14.4): the gentlest dungeon. Four combat rooms.
# `complete_xp` is the bonus for finishing it (design §10.1); each enemy's own XP
# is content.ENEMY_XP, written onto the enemy here so the run keeps what it was worth.
DUNGEONS = {"shallows": {"name": "The Shallows", "combat_rooms": 4, "complete_xp": 30}}

ENEMY_WEIGHTS = (("chaser", 40), ("shooter", 35), ("radial", 25))
DROP_CHANCE = {"chaser": 0.20, "shooter": 0.30, "radial": 0.35}
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
# UNIQUES DROP ONLY FROM BOSSES (owner's ask, 2026-11-18), by their own roll
# (content.UNIQUE_BASE, raised by rift modifiers). A class with none gets a
# standard item instead.
UNIQUE_LOOT = {"ranger": (("kingfisher_eye", 1), ("tidecaller", 1), ("repeater", 1)),
               "paladin": (("kingfisher_eye", 1),), "diviner": (("kingfisher_eye", 1),),
               "ninja": (("kingfisher_eye", 1),)}
# Kept as the complete content list for audits and content tests. A run uses the
# class-specific table below, so a Ranger never receives a Paladin's starter gear.
LOOT = RANGER_LOOT + PALADIN_LOOT + DIVINER_LOOT + NINJA_LOOT + tuple(x for t in UNIQUE_LOOT.values() for x in t)
LOOT_BY_CLASS = {"ranger": RANGER_LOOT, "paladin": PALADIN_LOOT, "diviner": DIVINER_LOOT, "ninja": NINJA_LOOT}
SLOT_ODDS = ((0, 50), (1, 35), (2, 12), (3, 3))


def _pick(rng: random.Random, table) -> object:
    total = sum(w for _, w in table)
    r = rng.random() * total
    for v, w in table:
        r -= w
        if r < 0:
            return v
    return table[-1][0]


def _item(rng: random.Random, tier: int, class_id: str, unique: bool = False) -> dict:
    base_id = _pick(rng, UNIQUE_LOOT[class_id] if unique and UNIQUE_LOOT.get(class_id) else LOOT_BY_CLASS[class_id])
    slots = _pick(rng, SLOT_ODDS)
    if C.base(base_id)["kind"] == "unique":
        tier = 1                  # a unique is its own thing, not a rung on the tier ladder
    return {"base_id": base_id, "tier": tier, "slot_count": slots,
            "enchants": store.roll_enchants(base_id, slots, rng)}


def _mirror(rows: list[str]) -> list[str]:
    return [r[::-1] for r in rows]


def mod_scale(mods: list[str]) -> dict:
    """What the chosen rift modifiers do to the enemies, multiplied together."""
    out = {"hp": 1.0, "dmg": 1.0, "speed": 1.0}
    for m in mods:
        for k, v in C.RIFT_MODS[m]["scale"].items():
            out[k] *= v
    return out


def generate(dungeon_id: str, seed: str | None = None, class_id: str = "ranger",
             mods: list[str] | tuple = ()) -> dict:
    """The whole dungeon for one run, as JSON-safe data."""
    if dungeon_id not in DUNGEONS:
        raise store.HalcyonError("no such dungeon")
    if class_id not in C.CLASSES:
        raise store.HalcyonError("no such class")
    mods = sorted(set(mods))
    if any(m not in C.RIFT_MODS for m in mods):
        raise store.HalcyonError("no such rift modifier")
    rarity = len(mods)
    seed = seed or secrets.token_hex(8)
    rng = random.Random(f"{dungeon_id}:{seed}")
    spec = DUNGEONS[dungeon_id]

    combat = rng.sample(COMBAT, spec["combat_rooms"])
    rooms = [("entrance", ENTRANCE)] + [("combat", t) for t in combat] + [("boss", BOSS_ROOM)]
    rooms = [(k, _mirror(t) if rng.random() < 0.5 else list(t)) for k, t in rooms]

    height = max(len(t) for _, t in rooms) + 2
    mid = height // 2
    width = sum(len(t[0]) + 2 for _, t in rooms) + CORRIDOR * (len(rooms) - 1)
    grid = [["#"] * width for _ in range(height)]

    enemies, pickups, room_spans = {}, [], []
    start = boss = None
    x = 0
    for n, (kind, t) in enumerate(rooms):
        h, w = len(t), len(t[0])
        top = (height - (h + 2)) // 2
        for r, row in enumerate(t):
            for c, ch in enumerate(row):
                gx, gy = x + 1 + c, top + 1 + r
                grid[gy][gx] = ch if ch in "o~." else "."
                pos = {"x": gx + 0.5, "y": gy + 0.5}
                if ch == "S":
                    start = pos
                elif ch in "EB":
                    eid = "boss" if ch == "B" else f"e{len(enemies) + 1}"
                    etype = "boss" if ch == "B" else _pick(rng, ENEMY_WEIGHTS)
                    enemies[eid] = {"type": etype, "room": n, "xp": C.ENEMY_XP[etype], **pos}
                    if ch == "B":
                        boss = eid
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
        boss_roll = e["type"] == "boss"
        if boss_roll:
            rolls = [2 if rng.random() < 0.7 else 3]
            if rng.random() < 0.5:
                rolls.append(2)
        else:
            rolls = [1 if rng.random() < 0.85 else 2] if rng.random() < DROP_CHANCE[e["type"]] else []
            if rng.random() < HEAL_CHANCE:           # a heal orb, dropped where it falls
                pickups.append({"id": f"h{len(pickups) + 1}", "kind": "heal", "enemy": eid})
        for tier in rolls[:BAG_MAX]:
            # Rarity (rift modifiers) can lift the tier, a step per point that hits.
            for _ in range(rarity):
                if rng.random() < C.TIER_UP_PER_RARITY:
                    tier = min(C.MAX_TIER, tier + 1)
            unique = boss_roll and rng.random() < C.UNIQUE_BASE + C.UNIQUE_PER_RARITY * rarity
            n_drop += 1
            drops[f"d{n_drop}"] = {**_item(rng, tier, class_id, unique), "enemy": eid}

    return {"id": dungeon_id, "name": spec["name"], "seed": seed, "width": width, "height": height,
            "tiles": ["".join(r) for r in grid], "start": start, "rooms": room_spans,
            "enemies": enemies, "boss": boss, "drops": drops, "pickups": pickups,
            "complete_xp": spec["complete_xp"], "class_id": class_id,
            "mods": mods, "scale": mod_scale(mods)}


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
