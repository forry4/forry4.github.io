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
  'x' torn floor    — the Fracture's void: blocks movement, projectiles fly over it
  '.' floor
A Fracture template may also mark CRACKS with '1', '2', '3': floor that opens into
void on a cycle, one group per digit (design §14.4a). They are laid as floor and
listed in the dungeon's `cracks`; the browser's fight opens and closes them.
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

# ── the Fracture (design §14.4a) ────────────────────────────────────────────
# Same shape rules as above. Cracks never touch a doorway row's edge columns or a
# spawn, and every room stays crossable with ANY one crack group open (tested).
FRACTURE_COMBAT = [
    [
        "................",
        "..E.....1....E..",
        "....xx..1.......",
        "....xx..1...oo..",
        "........1.......",
        "......E...2222..",
        "..3333..........",
        "..........xx....",
        "...oo..E..xx..E.",
        "................",
        "................",
    ],
    [
        "..................",
        ".E..xx......xx..E.",
        "....xx......xx....",
        "......1....2......",
        ".......1..2.......",
        "....E....E....E...",
        ".......2..1.......",
        "......2....1......",
        "....oo......oo....",
        "....oo..E...oo....",
        "..................",
    ],
    [
        "................",
        "...E........E...",
        "..1111....2222..",
        "................",
        "....xx....xx....",
        ".......E........",
        "....xx....xx....",
        "................",
        "..3333....1111..",
        "...E........E...",
        "................",
    ],
    [
        "....................",
        "..E....xxxxxx....E..",
        "....................",
        "...111........222...",
        "........oooo........",
        ".....E........E.....",
        "........oooo........",
        "...333........111...",
        "....................",
        "..E....xxxxxx....E..",
        "....................",
    ],
    [
        "..............",
        "..E....1....E.",
        ".......1......",
        "..xx...1..xx..",
        "..xx......xx..",
        "......E.......",
        "..xx......xx..",
        "..xx...2..xx..",
        ".......2......",
        "..E....2....E.",
        "..............",
    ],
]

FRACTURE_BOSS = [
    "......................",
    "......................",
    "...oo.....1......oo...",
    "...oo.....1......oo...",
    "..........1...........",
    "......................",
    "..222...........333...",
    "..........B...........",
    "..333...........222...",
    "......................",
    "..........1...........",
    "...oo.....1......oo...",
    "...oo.....1......oo...",
    "......................",
    "......................",
]

# ── the Ashen Breach (owner's design, 2026-11-19) ───────────────────────────
# Fire vents follow the fight, so the rocks provide cover between eruptions.
ASHEN_COMBAT = [
    [
        "................",
        "..E..........E..",
        "....oo....oo....",
        "....oo....oo....",
        "................",
        "......E..E......",
        "................",
        "....oo....oo....",
        "....oo..E.oo....",
        "..E..........E..",
        "................",
    ],
    [
        "..................",
        ".E......oo......E.",
        "........oo........",
        "...o..........o...",
        "...o...E..E...o...",
        "..................",
        "...o...E..E...o...",
        "...o..........o...",
        "........oo........",
        ".E......oo......E.",
        "..................",
    ],
    [
        "................",
        "...E........E...",
        "..oo........oo..",
        "................",
        ".......E........",
        "................",
        "........E.......",
        "................",
        "..oo........oo..",
        "...E........E...",
        "................",
    ],
    [
        "....................",
        "..E..............E..",
        "......oo....oo......",
        "....................",
        "...o.....E......o...",
        "...o............o...",
        "...o......E.....o...",
        "....................",
        "......oo....oo......",
        "..E..............E..",
        "....................",
    ],
    [
        "..............",
        "..E.......E...",
        "..............",
        "..oo....oo....",
        "..............",
        "......E.......",
        "..............",
        "....oo....oo..",
        "..............",
        "...E.......E..",
        "..............",
    ],
]

ASHEN_BOSS = [
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
    "......................",
    "..........B...........",
    "......................",
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
]
ASHEN_WEIGHTS = (("cinder", 28), ("kiln", 20), ("smolder", 22), ("shooter", 30))
# The Pyre calls this many Kilns into its fight at half health. They are generated
# with it (so each is a real enemy the server credits), kept out of play until then,
# and fall with it if it falls first.
PYRE_KILNS = 2

CORRIDOR = 3
# MODIFIERS PAY XP TOO (owner's ask, 2026-11-19: "it should increase it a bit"): each
# modifier adds MOD_XP of the level's whole XP. Each enemy's share is rounded DOWN, and the
# clear bonus takes up what the rounding left, so the TOTAL is right (an enemy worth 4
# would round 4.4 back to 4 and one modifier would pay nothing for it).
MOD_XP = C.MOD_XP
# The Shallows (design §14.4): the gentlest dungeon. Four combat rooms.
# `complete_xp` is the bonus for finishing it (design §10.1); each enemy's own XP
# is content.ENEMY_XP, written onto the enemy here so the run keeps what it was worth.
ENEMY_WEIGHTS = (("chaser", 40), ("shooter", 35), ("radial", 25))
FRACTURE_WEIGHTS = (("shard", 35), ("splitter", 30), ("flicker", 35))
# A Splitter breaks into this many Splinters (generated with it, so each is a real
# enemy the server can credit; the fight keeps them out of play until it dies).
SPLINTERS = 2

# Each dungeon: its rooms, its enemies, its loot tables (content.QUALITY rows), and
# what its boss is (`boss_kind`, read by the fight). `boss_xp` overrides the boss's
# usual XP. The Fracture is design §14.4a. `hazard` names what a room does while it
# is fought (the sim reads it); `summons` is what the boss calls in at half health.
DUNGEONS = {
    "shallows": {"name": "The Shallows", "boss_name": "The Tidewarden", "combat_rooms": 4, "complete_xp": 30,
                 "combat": COMBAT, "boss_room": BOSS_ROOM, "weights": ENEMY_WEIGHTS,
                 "quality": ("enemy", "boss"), "boss_kind": "tidewarden"},
    # The boss is NAMED the Schism (owner's call, 2026-11-19: the Ashen Breach took the
    # word); its kind stays "breach", which saved runs and the sim read.
    "fracture": {"name": "The Fracture", "boss_name": "The Schism", "combat_rooms": 4, "complete_xp": 60,
                 "boss_xp": 40, "combat": FRACTURE_COMBAT, "boss_room": FRACTURE_BOSS, "weights": FRACTURE_WEIGHTS,
                 "quality": ("fracture_enemy", "fracture_boss"), "boss_kind": "breach"},
    "ashen": {"name": "The Ashen Breach", "boss_name": "The Pyre", "combat_rooms": 4, "complete_xp": 100,
              "boss_xp": 60, "combat": ASHEN_COMBAT, "boss_room": ASHEN_BOSS, "weights": ASHEN_WEIGHTS,
              "quality": ("ashen_enemy", "ashen_boss"), "boss_kind": "pyre", "hazard": "vents",
              "summons": ("kiln", PYRE_KILNS)},
}
# A heal orb drops from an ordinary enemy at this chance: about one a rift (0-2 is
# the usual spread). The boss never drops one — the fight is over.
HEAL_CHANCE = 0.035
# Bags hold at most this many items (the page's loot panel is one row of eight).
BAG_MAX = 8
# Each class's armor share (22) is split between the two armors of its type
# (owner's call, 2026-11-19), so armor drops as often as before.
RANGER_LOOT = (("shortbow", 16), ("longbow", 14), ("leather_vest", 11), ("seer_robes", 11), ("volley_quiver", 14),
               ("band_of_vigor", 14), ("band_of_focus", 14))
PALADIN_LOOT = (("mace", 16), ("greatsword", 14), ("plate_armor", 11), ("shadow_garb", 11), ("stillness_orb", 14),
                ("band_of_vigor", 14), ("band_of_focus", 14))
DIVINER_LOOT = (("wand", 16), ("starstaff", 14), ("leather_vest", 11), ("seer_robes", 11), ("star_tome", 14),
                ("band_of_vigor", 14), ("band_of_focus", 14))
NINJA_LOOT = (("shuriken", 16), ("kunai", 14), ("plate_armor", 11), ("shadow_garb", 11), ("mirror_charm", 14),
              ("band_of_vigor", 14), ("band_of_focus", 14))
# UNIQUES DROP ONLY FROM BOSSES (owner's ask, 2026-11-18): the "unique" row of the
# boss's quality table (content.QUALITY). The loot tables themselves are in content.py.
# Every unique a class can wear, equally likely (owner's list, 2026-11-19): the five
# rings, the two unique armors of its type, and its own weapons and abilities.
_RINGS = ("kingfisher_eye", "ember_loop", "misers_coil", "leechstone", "glass_ring",
          "phoenix_feather", "ash_sigil", "banked_coal")
_LIGHT, _HEAVY = ("windrunner_cloak", "full_moon_mantle", "emberweave"), ("thornplate", "duskmail", "cinderguard")
UNIQUE_LOOT = {cls: tuple((b, 1) for b in _RINGS + arm + own) for cls, arm, own in (
    ("ranger", _LIGHT, ("tidecaller", "repeater", "gale_quiver", "flare_bow")),
    ("paladin", _HEAVY, ("oathhammer", "anchor_orb", "censer")),
    ("diviner", _LIGHT, ("comet_rod", "echo_codex", "meteor_tome")),
    ("ninja", _HEAVY, ("chakram", "echo_charm", "ember_kunai")))}
# Kept as the complete content list for audits and content tests. A run uses the
# class-specific table below, so a Ranger never receives a Paladin's starter gear.
LOOT = RANGER_LOOT + PALADIN_LOOT + DIVINER_LOOT + NINJA_LOOT + tuple(x for t in UNIQUE_LOOT.values() for x in t)
LOOT_BY_CLASS = {"ranger": RANGER_LOOT, "paladin": PALADIN_LOOT, "diviner": DIVINER_LOOT, "ninja": NINJA_LOOT}
# Enchantment slots on a drop (owner's table, 2026-11-18), set by the CUMULATIVE
# chance of at least n slots: 1+ 50%, 2+ 18.75% (50% x 37.5%), 3+ 4.6875% (x 25%),
# 4 0.5859% (x 12.5%). As one weighted roll (in 2048ths) that is exactly
# 0: 50%, 1: 31.25%, 2: 14.0625%, 3: 4.1016%, 4: 0.5859%.
SLOT_ODDS = C.SLOT_ODDS


def slot_odds(bonus: float = 0.0) -> tuple:
    """The slot table at this loot bonus: n slots weigh (1 + bonus)^n more (content.loot_bonus)."""
    k = 1 + bonus
    return tuple((n, w * k ** n) for n, w in SLOT_ODDS)


def _pick(rng: random.Random, table) -> object:
    total = sum(w for _, w in table)
    r = rng.random() * total
    for v, w in table:
        r -= w
        if r < 0:
            return v
    return table[-1][0]


def _item(rng: random.Random, tier: int, class_id: str, unique: bool = False,
          exclude: frozenset = frozenset(), bonus: float = 0.0, dungeon_id: str = "shallows") -> dict:
    # ONE ENEMY NEVER DROPS THE SAME ITEM TWICE (owner's ask, 2026-11-18): what it
    # already dropped is left out. A unique the boss already gave becomes a standard
    # item instead (a class may have only one unique).
    left = lambda t: tuple((b, w) for b, w in t if b not in exclude)
    # Only the uniques whose home is THIS dungeon (content.UNIQUE_HOME).
    table = left(tuple((b, w) for b, w in UNIQUE_LOOT.get(class_id, ()) if C.UNIQUE_HOME.get(b) == dungeon_id)) if unique else ()
    table = table or left(LOOT_BY_CLASS[class_id]) or LOOT_BY_CLASS[class_id]
    base_id = _pick(rng, table)
    slots = _pick(rng, slot_odds(bonus))
    return {"base_id": base_id, "tier": tier, "slot_count": slots,
            "enchants": store.roll_enchants(base_id, slots, rng)}


def _specials(it: dict, stream: random.Random, level: int) -> None:
    """SPECIAL LINES (owner's calls, 2026-11-19): from depth 3 down, each slot of a drop
    may hold a special line instead (content.SPECIAL_CHANCE). Its OWN stream per drop,
    so every other roll in the dungeon is what it was. Rolled for EVERY slot whether it
    hits or not, so one slot's luck never moves another's."""
    chance = C.SPECIAL_CHANCE.get(level, 0.0)
    pool = C.enchants_for(it["base_id"], special=True)
    for line in it["enchants"]:
        hit, pick, u = stream.random(), stream.random(), stream.random()
        left = [e for e in pool if e not in {x["id"] for x in it["enchants"]}]
        if hit < chance and left:
            line["id"] = left[int(pick * len(left))]
            line["q"] = C.line_q(u)


def _unique_tier(stream: str, quality) -> int:
    """A UNIQUE IS TIERED LIKE ANYTHING ELSE (owner's call, 2026-11-19): it takes a
    tier rolled from the same table its boss rolls (depth lift included), less the
    unique row, so a deep boss's unique keeps up with the gear around it. Its own
    stream, so every other roll in the dungeon is what it was."""
    rows = tuple((r, w) for r, w in quality if r != "unique")
    return int(_pick(random.Random(stream), rows)[1:])


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
    bonus = C.loot_bonus(rarity, level)
    xp_mult = 1 + MOD_XP * len(mods)
    seed = seed or secrets.token_hex(8)
    rng = random.Random(f"{dungeon_id}:{seed}" if level == 1 else f"{dungeon_id}:{seed}:L{level}")
    swarm = random.Random(f"{dungeon_id}:{seed}:swarm{level}") if "swarming" in mods else None
    pre = "" if level == 1 else f"L{level}-"
    spec = DUNGEONS[dungeon_id]

    combat = rng.sample(spec["combat"], spec["combat_rooms"] if level == 1 else DEEP_ROOMS)
    if boss_rush:
        combat = []
    rooms = [("entrance", ENTRANCE)] + [("combat", t) for t in combat] + [("boss", spec["boss_room"])]
    rooms = [(k, _mirror(t) if rng.random() < 0.5 else list(t)) for k, t in rooms]

    height = max(len(t) for _, t in rooms) + 2
    mid = height // 2
    width = sum(len(t[0]) + 2 for _, t in rooms) + CORRIDOR * (len(rooms) - 1)
    grid = [["#"] * width for _ in range(height)]

    enemies, pickups, room_spans, cracks = {}, [], [], {}
    start = boss = None
    x = 0
    weights = spec["weights"]
    worth = lambda etype: spec.get("boss_xp", C.ENEMY_XP["boss"]) if etype == "boss" else C.ENEMY_XP[etype]

    def add(etype: str, n: int, gx: int, gy: int, parent: str | None = None, summon: str | None = None) -> str:
        eid = f"{pre}boss" if etype == "boss" else f"{pre}e{sum(1 for k in enemies if not k.endswith('boss')) + 1}"
        enemies[eid] = {"type": etype, "room": n, "xp": int(worth(etype) * xp_mult + 1e-9), "x": gx + 0.5, "y": gy + 0.5}
        if parent:
            enemies[eid]["parent"] = parent
        if summon:
            # Called into the boss's fight, so NOT a parent: the server takes its kill
            # whether the boss has fallen or not (it may be killed first or after).
            enemies[eid]["summon"] = summon
        if etype == "splitter":
            for _ in range(SPLINTERS):
                add("splinter", n, gx, gy, parent=eid)
        if etype == "boss" and spec.get("summons"):
            kind, count = spec["summons"]
            for _ in range(count):
                add(kind, n, gx, gy, summon=eid)
        return eid

    for n, (kind, t) in enumerate(rooms):
        h, w = len(t), len(t[0])
        top = (height - (h + 2)) // 2
        spawns = []
        for r, row in enumerate(t):
            for c, ch in enumerate(row):
                gx, gy = x + 1 + c, top + 1 + r
                grid[gy][gx] = ch if ch in "o~.x" else "."
                if ch in "123":
                    cracks.setdefault((n, int(ch) - 1), []).append([gx, gy])
                if ch == "S":
                    start = {"x": gx + 0.5, "y": gy + 0.5}
                elif ch in "EB":
                    spawns.append((c, r))
                    eid = add("boss" if ch == "B" else _pick(rng, weights), n, gx, gy)
                    if ch == "B":
                        boss = eid
        if swarm and kind in ("combat", "boss"):
            extra = SWARM_BOSS if kind == "boss" else -(-len(spawns) * SWARM_ROOM // 1)
            for c, r in _swarm_spots(swarm, t, spawns, int(extra)):
                add(_pick(swarm, weights), n, x + 1 + c, top + 1 + r)
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
        n = _pick(rng, C.drop_count(e["type"], bonus))       # how many items: one roll
        if not is_boss and rng.random() < HEAL_CHANCE:           # a heal orb, dropped where it falls
            pickups.append({"id": f"{pre}h{len(pickups) + 1}", "kind": "heal", "enemy": eid})
        quality = C.quality_table(spec["quality"][1] if is_boss else spec["quality"][0], rarity, level)
        dropped: set[str] = set()
        for _ in range(min(n, BAG_MAX)):
            q = _pick(rng, quality)                          # what each is: one roll
            unique = q == "unique"
            tier = _unique_tier(f"{dungeon_id}:{seed}:utier{level}:{eid}:{n_drop}", quality) if unique else int(q[1:])
            it = _item(rng, tier, class_id, unique, frozenset(dropped), bonus, dungeon_id)
            if C.SPECIAL_CHANCE.get(level):
                _specials(it, random.Random(f"{dungeon_id}:{seed}:spec{level}:{n_drop}"), level)
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

    base = spec["complete_xp"] + sum(worth(e["type"]) for e in enemies.values())
    complete_xp = round(base * xp_mult) - sum(e["xp"] for e in enemies.values())
    return {"id": dungeon_id, "name": spec["name"], "boss_name": spec["boss_name"], "seed": seed, "width": width, "height": height,
            "tiles": ["".join(r) for r in grid], "start": start, "rooms": room_spans, "door_y": mid,
            "enemies": enemies, "boss": boss, "drops": drops, "pickups": pickups,
            "complete_xp": complete_xp, "class_id": class_id,
            "mods": mods, "scale": mod_scale(mods, level), "level": level,
            "offers": offers_for(dungeon_id, seed, mods, level), "boss_rush": bool(boss_rush),
            "boss_kind": spec["boss_kind"],
            **({"hazard": spec["hazard"]} if spec.get("hazard") else {}),
            # Cracks (design §14.4a), one entry per room and group, in a fixed order.
            "cracks": [{"room": n, "group": g, "tiles": t} for (n, g), t in sorted(cracks.items())]}


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
