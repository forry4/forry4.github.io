"""Halcyon Rift content definitions — the data the item store validates against.

GREYBOX PLACEHOLDERS. Every id and number here stands in for content that is
decided by playing (docs/halcyon-rift-game-design.md §23): the base items, the
enchantment list and the fusion odds are only what the store needs to enforce
its rules. Two rules about this file are NOT placeholders:

- **An id is forever.** Items in the database name a base and its enchantments
  by id, so an id is never reused or deleted — only retired (`retired: True`),
  which stops it dropping while existing items keep working.
- **Items store roll QUALITY, not numbers** (design §20.1), so changing a value
  here re-scales every existing item. That is the point: rebalancing is a data
  edit, not a migration.
"""
from __future__ import annotations

CONTENT_VERSION = 2

CLASSES = ("ranger", "paladin", "diviner", "ninja")
CLASS_NAMES = {"ranger": "Ranger", "paladin": "Paladin", "diviner": "Diviner", "ninja": "Ninja"}
CLASS_DESCRIPTIONS = {
    "ranger": "A quick ranged fighter with a volley of arrows.",
    "paladin": "A close-range guardian whose field slows enemy shots and burns enemies around them.",
    "diviner": "A long-range mage who calls stars down on a spot.",
    "ninja": "A quick thrower who counters a hit and strikes back twice as hard.",
}

# The five equipment slots, in the order the store numbers them.
EQUIP_SLOTS = ("weapon", "armor", "ability", "ring1", "ring2")
VAULT_SIZE = 64
INVENTORY_SIZE = 16
CHARACTER_SLOTS = 4
TIERS = (1, 2, 3, 4, 5)
MAX_ENCHANT_SLOTS = 4

# base_id -> what kind of thing it is. `cls` None means any class (rings).
# `slot` is the equipment slot family: a ring fits ring1 or ring2.
BASE_ITEMS: dict[str, dict] = {
    "shortbow":      {"slot": "weapon",  "cls": "ranger", "kind": "standard"},
    "longbow":       {"slot": "weapon",  "cls": "ranger", "kind": "standard"},
    "mace":          {"slot": "weapon",  "cls": "paladin", "kind": "standard"},
    "greatsword":    {"slot": "weapon",  "cls": "paladin", "kind": "standard"},
    "wand":          {"slot": "weapon",  "cls": "diviner", "kind": "standard"},
    "starstaff":     {"slot": "weapon",  "cls": "diviner", "kind": "standard"},
    # Two STANDARD weapon types per class, plus uniques (owner's call, 2026-11-18).
    # The repeater was a third standard bow; it is now a rare unique.
    "repeater":      {"slot": "weapon",  "cls": "ranger", "kind": "unique"},
    "tidecaller":    {"slot": "weapon",  "cls": "ranger", "kind": "unique"},
    "leather_vest":  {"slot": "armor",   "cls": "ranger", "kind": "standard"},
    "volley_quiver": {"slot": "ability", "cls": "ranger", "kind": "standard"},
    "plate_armor":   {"slot": "armor",   "cls": "paladin", "kind": "standard"},
    # ONE STANDARD ABILITY PER CLASS (owner's call, 2026-11-18). The shield is RETIRED
    # (kept for a future class): it no longer drops, and store.init_schema turns every
    # one into the Paladin's new ability, the Stillness Orb, which moved over from the
    # Diviner. The Diviner's is now the Star Tome.
    "grounding_aegis": {"slot": "ability", "cls": "paladin", "kind": "standard", "retired": True},
    "seer_robes":     {"slot": "armor",   "cls": "diviner", "kind": "standard"},
    "stillness_orb":  {"slot": "ability", "cls": "paladin", "kind": "standard"},
    "star_tome":      {"slot": "ability", "cls": "diviner", "kind": "standard"},
    # The Ninja (2026-11-18): throwing stars and kunai, light armor, the counter.
    "shuriken":       {"slot": "weapon",  "cls": "ninja",   "kind": "standard"},
    "kunai":          {"slot": "weapon",  "cls": "ninja",   "kind": "standard"},
    "shadow_garb":    {"slot": "armor",   "cls": "ninja",   "kind": "standard"},
    "mirror_charm":   {"slot": "ability", "cls": "ninja",   "kind": "standard"},
    "band_of_vigor": {"slot": "ring",    "cls": None,     "kind": "standard"},
    "band_of_focus": {"slot": "ring",    "cls": None,     "kind": "standard"},
    "kingfisher_eye": {"slot": "ring",   "cls": None,     "kind": "unique"},
    # KEYS (owner's ask, 2026-11-18). A key is carried in a character's bag and spent
    # on entering: the Dream Key opens the Dream Rift for one practice run, the Boss
    # Rush key one Boss Rush run. Slot family "key" fits no equipment slot, a key has
    # no tier ladder or enchantments, and keys never fuse.
    "dream_key":      {"slot": "key",    "cls": None,     "kind": "key"},
    "boss_rush_key":  {"slot": "key",    "cls": None,     "kind": "key"},
}
DREAM_KEY, BOSS_RUSH_KEY = "dream_key", "boss_rush_key"
# What a level's boss drops besides its items, rolled on their own stream so the
# rest of the loot is unchanged: each a flat chance per boss, any rift, any level,
# never touched by rarity. A Boss Rush run never drops a Boss Rush key.
KEY_DROPS = ((DREAM_KEY, 0.10), (BOSS_RUSH_KEY, 0.03))
BOSS_RUSH = {"name": "Boss Rush", "text": "No ordinary rooms: every level is its boss. Spends a Boss Rush key; "
                                          "no time is recorded."}

# enchantment id -> which slot families it may roll on. Regen rolls may be
# fractional; the browser displays them to one decimal place.
ENCHANTS: dict[str, dict] = {
    "max_hp":        {"slots": ("weapon", "armor", "ability", "ring")},
    "max_mp":        {"slots": ("weapon", "armor", "ability", "ring")},
    "attack":        {"slots": ("weapon", "ring")},
    "defense":       {"slots": ("armor", "ring")},
    "attack_speed":  {"slots": ("weapon", "ring")},
    "ability_power": {"slots": ("ability", "ring")},
    "mp_regen":      {"slots": ("armor", "ability", "ring")},
    "hp_regen":      {"slots": ("armor", "ring")},
}

# ── levels and XP (design §10.1) ────────────────────────────────────────────
# XP comes from kills, plus a bonus for completing a dungeon; recall keeps what a
# run earned (owner's call, 2026-11-18). The SERVER credits it, from the XP it
# wrote into the dungeon it generated — a request never names an amount.
MAX_LEVEL = 20
ENEMY_XP = {"chaser": 4, "shooter": 5, "radial": 6, "boss": 20}


def _level_table() -> tuple[int, ...]:
    """LEVEL_XP[n] = the total XP a character needs to BE level n + 1. A full clear
    of the Shallows (~140 XP) is about level 1 -> 2; each level asks 30% more."""
    out, total = [0], 0
    for level in range(1, MAX_LEVEL):
        total += int(round(120 * 1.3 ** (level - 1) / 10)) * 10
        out.append(total)
    return tuple(out)


LEVEL_XP = _level_table()


def level_for(xp: int) -> int:
    level = 1
    while level < MAX_LEVEL and xp >= LEVEL_XP[level]:
        level += 1
    return level


# Fusion's chance to gain enchantment slots (design §11.7: "may rarely gain
# multiple slots"). Checked in order; the first hit wins. Raised 2026-11-18 (owner:
# "make sure using the forge has a chance of increasing the number of slots") —
# at 5% it never showed up in play.
FUSE_SLOT_GAIN = ((2, 0.04), (1, 0.20))

# Rift modifiers (owner's ask, 2026-11-18): picked before a run; each makes the
# rift harder and adds one RARITY point. Rarity raises the odds of a higher TIER
# and of a boss UNIQUE — never the number of enchantment slots. The scales are
# read by the browser's fight (sim.js) off the dungeon the server generates.
# ONE MODIFIER POOL for the town's rift panel and the portal deeper (owner's call,
# 2026-11-18). Each is worded to hold for ordinary enemies and the boss alike, and
# each is one rarity point however hard it is: no difficulty costs and no rules
# against a bad combination — the player picks, so a hard pair is a choice. A
# run never holds one twice. `scale` multiplies (hp, dmg, speed, shot = enemy shot
# size, cadence = time between attacks); `ward` is hits ignored (ordinary, boss);
# `swarm` adds enemies (dungeon.py); `volatile` rings shots on death (sim.js).
RIFT_MODS: dict[str, dict] = {
    "fortified": {"name": "Fortified", "text": "Enemies have 50% more health.", "scale": {"hp": 1.5}},
    "brutal":    {"name": "Brutal", "text": "Enemies hit 40% harder.", "scale": {"dmg": 1.4}},
    "swift":     {"name": "Swift", "text": "Enemies and their shots move 25% faster.", "scale": {"speed": 1.25}},
    "warded":    {"name": "Warded", "text": "Enemies ignore their first few hits.", "scale": {}, "ward": (3, 10)},
    "swarming":  {"name": "Swarming", "text": "More enemies spawn.", "scale": {}, "swarm": True},
    "bulky":     {"name": "Bulky", "text": "Enemy shots are 50% larger.", "scale": {"shot": 1.5}},
    "frenzied":  {"name": "Frenzied", "text": "Enemies attack 40% more often.", "scale": {"cadence": 1 / 1.4}},
    "volatile":  {"name": "Volatile", "text": "Enemies burst into a ring of shots when they fall.", "scale": {},
                  "volatile": True},
}
# ── LOOT TABLES (owner's ask, 2026-11-18: "rethink how to do loot drop tables") ──
# EVERY RANDOM OUTCOME IS ONE ROLL ON ONE WEIGHTED TABLE THAT NAMES EVERY RESULT,
# "nothing" included (Diablo II's NoDrop row). Never a cascade of independent
# checks ("10% legendary, else 20% epic, else ...") — each later check only sees
# what the earlier ones left, so its real rate is lower than written and the
# bottom row soaks up the rest. With one weighted roll, an entry's chance is
# exactly weight / total, which is what the rift panel shows.
#
# An enemy's loot is two rolls, as most ARPGs split it: HOW MANY items (DROP_COUNT),
# then, for each, WHAT QUALITY (QUALITY: a tier, or a unique). The base item is a
# third roll on the class's table, the slot count a fourth (SLOT_ODDS, the same
# for every source). The BOSS is a better table, not a different game: one item
# guaranteed, a chance of a second or third, a lean toward higher tiers, and the
# only source of uniques.
DROP_COUNT: dict[str, tuple] = {
    "chaser":  ((0, 80), (1, 20)),
    "shooter": ((0, 70), (1, 30)),
    "radial":  ((0, 65), (1, 35)),
    "boss":    ((1, 60), (2, 30), (3, 10)),
}
# (result, weight, + weight per RARITY point). Rarity (one point a rift modifier)
# only ADDS weight to the better rows, so it shifts the odds up without touching
# how many items drop or how many enchantment slots they have.
QUALITY: dict[str, tuple] = {
    "enemy": (("t1", 70, 0), ("t2", 25, 5), ("t3", 5, 3)),
    "boss":  (("t1", 40, 0), ("t2", 35, 0), ("t3", 15, 5), ("t4", 2, 3), ("unique", 8, 0)),
}
# THE BOSS'S UNIQUE CHANCE RISES 15% (of itself) PER MODIFIER, so 45% with all three
# (owner's call, 2026-11-18). A flat weight per point cannot do that — the other rows
# grow too and the boss drops 1-3 items — so the unique row's weight is SOLVED for
# that target at each rarity (`_unique_weight`), and tested to the percent.
UNIQUE_PER_MODIFIER = 0.15
MAX_TIER = 5


def _boss_unique_chance(table) -> float:
    """P(at least one unique) from a boss that rolls this quality table per item."""
    u = chances(table)["unique"]
    return 1 - sum(pc * (1 - u) ** n for n, pc in chances(DROP_COUNT["boss"]).items())


def _unique_weight(rarity: int) -> float:
    """The unique row's weight that puts the boss's unique chance at
    base x (1 + UNIQUE_PER_MODIFIER x rarity), with the other rows as they are."""
    rows = [(r, w + per * rarity) for r, w, per in QUALITY["boss"] if r != "unique"]
    base = _boss_unique_chance(tuple((r, w) for r, w, _ in QUALITY["boss"]))
    want = base * (1 + UNIQUE_PER_MODIFIER * rarity)
    lo, hi = 0.0, 1000.0
    for _ in range(60):                     # bisection: the chance only grows with the weight
        mid = (lo + hi) / 2
        lo, hi = (mid, hi) if _boss_unique_chance(tuple(rows) + (("unique", mid),)) < want else (lo, mid)
    return round((lo + hi) / 2, 6)


def quality_table(source: str, rarity: int = 0) -> tuple:
    """The (result, weight) table a drop of this source rolls on, at this rarity."""
    rows = tuple((r, w + per * rarity) for r, w, per in QUALITY[source])
    if source == "boss" and rarity:
        rows = tuple((r, _unique_weight(rarity) if r == "unique" else w) for r, w in rows)
    return rows


def chances(table) -> dict:
    """Each result's exact chance on a weighted table."""
    total = sum(w for _, w in table)
    return {r: w / total for r, w in table}


def loot_odds(rarity: int) -> dict:
    """What the rift panel shows, worked out from the tables above (never typed twice)."""
    boss_q, enemy_q = chances(quality_table("boss", rarity)), chances(quality_table("enemy", rarity))
    counts = chances(DROP_COUNT["boss"])
    unique = _boss_unique_chance(quality_table("boss", rarity))
    return {"enemy_t2_plus": enemy_q["t2"] + enemy_q["t3"],
            "boss_t3_plus": boss_q["t3"] + boss_q["t4"],
            "boss_unique": unique,
            "boss_items": sum(n * pc for n, pc in counts.items())}

def base(base_id: str) -> dict:
    b = BASE_ITEMS.get(base_id)
    if b is None:
        raise KeyError(f"unknown base item {base_id!r}")
    return b


def slot_fits(base_id: str, equip_slot: str) -> bool:
    fam = base(base_id)["slot"]
    return fam == equip_slot or (fam == "ring" and equip_slot in ("ring1", "ring2"))


def enchants_for(base_id: str) -> list[str]:
    fam = base(base_id)["slot"]
    return sorted(e for e, d in ENCHANTS.items() if fam in d["slots"] and not d.get("retired"))
