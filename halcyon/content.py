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

CONTENT_VERSION = 1

CLASSES = ("ranger",)

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
    "leather_vest":  {"slot": "armor",   "cls": "ranger", "kind": "standard"},
    "volley_quiver": {"slot": "ability", "cls": "ranger", "kind": "standard"},
    "band_of_vigor": {"slot": "ring",    "cls": None,     "kind": "standard"},
    "band_of_focus": {"slot": "ring",    "cls": None,     "kind": "standard"},
    "kingfisher_eye": {"slot": "ring",   "cls": None,     "kind": "unique"},
}

# enchantment id -> which slot families it may roll on. Values (what q=1.0 is
# worth) are deliberately absent until the greybox produces real numbers.
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

# Fusion's chance to gain enchantment slots (design §11.7: "may rarely gain
# multiple slots"). Checked in order; the first hit wins.
FUSE_SLOT_GAIN = ((2, 0.01), (1, 0.05))


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
