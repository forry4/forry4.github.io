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
    "paladin": "A close-range guardian whose field slows enemy shots around them.",
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
}

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
RIFT_MODS: dict[str, dict] = {
    "fortified": {"name": "Fortified", "text": "Enemies have 50% more health.", "scale": {"hp": 1.5}},
    "brutal":    {"name": "Brutal", "text": "Enemies hit 40% harder.", "scale": {"dmg": 1.4}},
    "swift":     {"name": "Swift", "text": "Enemies and their shots move 25% faster.", "scale": {"speed": 1.25}},
}
TIER_UP_PER_RARITY = 0.25        # each rarity point: this chance (each) to raise a drop's tier by one
UNIQUE_BASE = 0.12               # a boss roll's chance to be a unique, at rarity 0 ...
UNIQUE_PER_RARITY = 0.10         # ... plus this per rarity point
MAX_TIER = 5


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
