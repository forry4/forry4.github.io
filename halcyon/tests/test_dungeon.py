"""The dungeon generator (halcyon/dungeon.py): every dungeon it can make is
completable, and what it hands the item store is accepted by it."""
import sqlite3

import random

import pytest

from core.db import _Conn
from halcyon import dungeon as D
from halcyon import store as S
from halcyon import store
from halcyon import content as C

SEEDS = [f"s{i}" for i in range(200)]


@pytest.mark.parametrize("name,t", [("entrance", D.ENTRANCE), ("boss", D.BOSS_ROOM)]
                         + [(f"combat{i}", t) for i, t in enumerate(D.COMBAT)])
def test_templates_are_well_formed(name, t):
    assert len({len(r) for r in t}) == 1, f"{name}: ragged rows"
    assert len(t) % 2 == 1, f"{name}: needs an odd row count so its doors meet the corridor"
    assert len(t) + 2 <= max(len(x) for x in [D.BOSS_ROOM, D.ENTRANCE] + D.COMBAT) + 2
    mid = len(t) // 2
    for dy in (-1, 0, 1):
        row = t[mid + dy]
        assert row[0] not in "o~" and row[-1] not in "o~", f"{name}: a door row is blocked at an edge"
    assert set("".join(t)) <= set(".o~EBHS"), f"{name}: unknown tile"


def test_the_same_seed_makes_the_same_dungeon():
    assert D.generate("shallows", "abc") == D.generate("shallows", "abc")
    assert D.generate("shallows", "abc")["tiles"] != D.generate("shallows", "abd")["tiles"]


@pytest.mark.parametrize("seed", SEEDS)
def test_every_dungeon_is_completable(seed):
    d = D.generate("shallows", seed)
    assert len({len(r) for r in d["tiles"]}) == 1 and len(d["tiles"]) == d["height"]
    reach = D.reachable(d)
    for eid, e in d["enemies"].items():
        assert (int(e["x"]), int(e["y"])) in reach, f"{eid} cannot be reached"
    for p in d["pickups"]:      # heal orbs drop from an ordinary enemy, never from the boss
        assert p["kind"] == "heal" and p["enemy"] in d["enemies"] and p["enemy"] != d["boss"], p
    assert d["boss"] == "boss" and d["enemies"]["boss"]["type"] == "boss"
    assert d["rooms"][0]["kind"] == "entrance" and d["rooms"][-1]["kind"] == "boss"
    assert sum(r["kind"] == "combat" for r in d["rooms"]) == 4
    # the outer edge is solid: nothing can walk or fly off the map
    assert set(d["tiles"][0]) == {"#"} and set(d["tiles"][-1]) == {"#"}
    assert all(r[0] == "#" and r[-1] == "#" for r in d["tiles"])


def test_the_boss_always_drops_and_drops_name_real_enemies():
    for seed in SEEDS:
        d = D.generate("shallows", seed)
        assert any(dr["enemy"] == "boss" for dr in d["drops"].values()), seed
        assert all(dr["enemy"] in d["enemies"] for dr in d["drops"].values())


def test_mirroring_and_every_enemy_type_are_reached():
    kinds, mirrored = set(), set()
    for seed in SEEDS:
        d = D.generate("shallows", seed)
        kinds |= {e["type"] for e in d["enemies"].values()}
        mirrored.add(d["start"]["x"] < 6)            # the entrance's S is left of centre unmirrored
    assert kinds == {"chaser", "shooter", "radial", "boss"}
    assert mirrored == {False, True}


def test_the_store_accepts_every_generated_dungeon(tmp_path):
    path = str(tmp_path / "h.db")
    connect = lambda: _Conn(sqlite3.connect(path))  # noqa: E731
    conn = connect()
    S.init_schema(conn)
    conn.close()
    S.register_owner(connect, "u", "account")
    ch = S.create_character(connect, "u", 0, "ranger")
    for seed in SEEDS[:40]:
        d = D.generate("shallows", seed)
        run = S.start_run(connect, "u", ch["char_id"], "shallows", seed, d)
        assert set(run["dungeon"]["drops"]) == set(d["drops"])


def test_an_unknown_dungeon_is_refused():
    with pytest.raises(S.HalcyonError):
        D.generate("the_deep")


def test_loot_is_two_weapons_per_class_plus_uniques_and_nothing_retired():
    from halcyon import content as C
    names = [b for b, _ in D.LOOT]
    assert all(b in C.BASE_ITEMS and not C.BASE_ITEMS[b].get("retired") for b in names)
    for cls in C.CLASSES:
        std = [b for b in names if C.BASE_ITEMS[b]["slot"] == "weapon" and C.BASE_ITEMS[b]["cls"] == cls
               and C.BASE_ITEMS[b]["kind"] == "standard"]
        assert len(std) == 2, (cls, std)
    assert any(C.BASE_ITEMS[b]["kind"] == "unique" and C.BASE_ITEMS[b]["slot"] == "weapon" for b in names)


def test_a_unique_drop_has_no_tier_to_climb():
    from halcyon import content as C
    seen = 0
    for seed in map(str, range(300)):
        for d in D.generate("shallows", seed)["drops"].values():
            if C.BASE_ITEMS[d["base_id"]]["kind"] == "unique":
                seen += 1
                assert d["tier"] == 1, d
    assert seen > 0, "300 dungeons rolled no unique at all"


def test_heal_orbs_come_about_one_a_rift_and_none_are_placed_in_rooms():
    counts = [len(D.generate("shallows", f"h{i}")["pickups"]) for i in range(400)]
    mean = sum(counts) / len(counts)
    assert 0.5 <= mean <= 1.5, mean
    assert sum(c <= 2 for c in counts) / len(counts) >= 0.85
    assert all("H" not in row for t in D.COMBAT + [D.ENTRANCE, D.BOSS_ROOM] for row in t)


def test_uniques_drop_only_from_the_boss():
    seen_boss_unique = False
    for i in range(300):
        d = D.generate("shallows", f"u{i}", mods=["fortified", "brutal", "swift"])
        for dr in d["drops"].values():
            if C.base(dr["base_id"])["kind"] == "unique":
                assert dr["enemy"] == d["boss"], dr
                seen_boss_unique = True
    assert seen_boss_unique


def _loot_sample(n, mods=(), cls="ranger", dungeon="shallows"):
    """Per source: how many items each enemy dropped, and each item's quality."""
    counts = {t: [] for t in C.DROP_COUNT}
    quality = {"enemy": [], "boss": []}
    slots = []
    for i in range(n):
        d = D.generate(dungeon, f"loot-{i}-{len(mods)}", cls, mods=list(mods))
        per = {}
        for dr in d["drops"].values():
            if C.base(dr["base_id"])["kind"] == "key":
                continue                                 # keys are their own roll (KEY_DROPS)
            per[dr["enemy"]] = per.get(dr["enemy"], 0) + 1
            src = "boss" if dr["enemy"] == d["boss"] else "enemy"
            quality[src].append("unique" if C.base(dr["base_id"])["kind"] == "unique" else f"t{dr['tier']}")
            slots.append(dr["slot_count"])
        for eid, e in d["enemies"].items():
            counts[e["type"]].append(per.get(eid, 0))
    return counts, quality, slots


def _close(seen: list, want: dict):
    """Each result turns up at the rate its table says, within 4 standard errors."""
    n = len(seen)
    for r, p in want.items():
        got = seen.count(r) / n
        assert abs(got - p) <= 4 * (p * (1 - p) / n) ** 0.5 + 1e-9, (r, got, p, n)


def test_drops_come_at_the_rates_the_tables_say():
    """One weighted roll per outcome, never a cascade of checks: a row's real rate
    is exactly weight / total (a cascade under-delivers the middle rows)."""
    for dungeon, spec in D.DUNGEONS.items():
        for mods in ((), ("fortified", "brutal", "swift")):
            counts, quality, slots = _loot_sample(1500 if dungeon == "shallows" else 600, mods, dungeon=dungeon)
            for etype, table in C.DROP_COUNT.items():
                if counts[etype]:                        # each rift has its own enemies
                    _close(counts[etype], C.chances(table))
            for src, table in zip(("enemy", "boss"), spec["quality"]):
                _close(quality[src], C.chances(C.quality_table(table, len(mods))))
            _close(slots, C.chances(D.SLOT_ODDS))


def test_slot_odds_are_the_owners_cumulative_table():
    p = C.chances(D.SLOT_ODDS)
    at_least = lambda n: sum(v for k, v in p.items() if k >= n)
    assert (at_least(1), at_least(2), at_least(3), at_least(4)) == (0.5, 0.1875, 0.046875, 0.005859375)
    assert max(p) == C.MAX_ENCHANT_SLOTS


def test_the_boss_is_a_better_table_not_a_jackpot():
    counts, quality, _ = _loot_sample(600)
    assert min(counts["boss"]) == 1 and max(counts["boss"]) <= 3          # one item guaranteed, no more
    assert counts["boss"].count(1) / len(counts["boss"]) > 0.5           # usually just the one
    tier = lambda q: 0 if q == "unique" else int(q[1:])
    mean = lambda xs: sum(xs) / len(xs)
    boss = [tier(q) for q in quality["boss"] if q != "unique"]
    mob = [tier(q) for q in quality["enemy"]]
    assert mean(boss) > mean(mob) + 0.3                                   # higher tiers ...
    assert boss.count(1) / len(boss) > 0.3                                # ... but a tier 1 is still common
    assert "unique" not in quality["enemy"] and "unique" in quality["boss"]


def test_rift_modifiers_raise_quality_but_not_counts_or_slots():
    c0, q0, s0 = _loot_sample(500)
    c3, q3, s3 = _loot_sample(500, ("fortified", "brutal", "swift"))
    # Each modifier raises the boss's unique chance by 15% of itself: 45% with all three.
    for r in range(4):
        assert abs(C.loot_odds(r)["boss_unique"] / C.loot_odds(0)["boss_unique"] - (1 + 0.15 * r)) < 1e-4, r
    assert C.loot_odds(3)["enemy_t2_plus"] > C.loot_odds(0)["enemy_t2_plus"]
    assert all(r in ("t1", "t2", "t3") for r in q3["enemy"])
    assert abs(sum(s3) / len(s3) - sum(s0) / len(s0)) < 0.15            # the same enchantment slots
    assert C.loot_odds(3)["boss_items"] == C.loot_odds(0)["boss_items"]   # and the same count


def test_rift_modifiers_are_named_and_scale_the_enemies():
    d = D.generate("shallows", "x", mods=["swift", "fortified"])
    assert d["mods"] == ["fortified", "swift"]
    assert {k: d["scale"][k] for k in ("hp", "dmg", "speed")} == {"hp": 1.5, "dmg": 1.0, "speed": 1.25}
    w = D.generate("shallows", "x", mods=["warded", "bulky", "frenzied", "volatile"])["scale"]
    assert (w["ward"], w["ward_boss"], w["shot"], w["volatile"]) == (3, 10, 1.5, 1) and w["cadence"] < 1
    assert len(C.RIFT_MODS) == 8 and all(m["name"] and m["text"] for m in C.RIFT_MODS.values())
    with pytest.raises(store.HalcyonError):
        D.generate("shallows", "x", mods=["nope"])


def test_one_enemy_never_drops_the_same_item_twice():
    seen_multi = 0
    for seed in range(400):
        d = D.generate("shallows", f"dup-{seed}", ["ranger", "paladin", "diviner", "ninja"][seed % 4])
        by_enemy: dict[str, list[str]] = {}
        for dr in d["drops"].values():
            by_enemy.setdefault(dr["enemy"], []).append(dr["base_id"])
        for eid, bases in by_enemy.items():
            assert len(bases) == len(set(bases)), (seed, eid, bases)
            seen_multi += len(bases) > 1
    assert seen_multi > 50          # enemies with two or more drops were really checked


# ── going deeper (design §14.6) ────────────────────────────────────────────────
def test_level_one_is_what_it_always_was_and_deeper_levels_are_shorter_and_tougher():
    one, two = D.generate("shallows", "lv", level=1), D.generate("shallows", "lv", level=2)
    assert one["level"] == 1 and not any(k.startswith("L") for k in list(one["enemies"]) + list(one["drops"]))
    assert len(one["rooms"]) == 2 + D.DUNGEONS["shallows"]["combat_rooms"]
    assert len(two["rooms"]) == 2 + D.DEEP_ROOMS
    assert two["boss"] == "L2-boss" and all(k.startswith("L2-") for k in list(two["enemies"]) + list(two["drops"]))
    assert all(h["id"].startswith("L2-") for h in two["pickups"])
    assert abs(two["scale"]["hp"] - (1 + D.LEVEL_HP)) < 1e-9 and one["scale"]["hp"] == 1.0
    assert two["tiles"] != one["tiles"]
    # Every level is reachable end to end: start to the boss.
    for d in (one, two):
        b = d["enemies"][d["boss"]]
        assert (int(b["x"]), int(b["y"])) in D.reachable(d)


def test_the_portal_deeper_offers_three_the_run_does_not_have_the_same_every_time():
    for seed in range(60):
        mods = sorted(random.Random(seed).sample(sorted(C.RIFT_MODS), seed % 4))
        for level in range(1, D.MAX_LEVEL + 1):
            d = D.generate("shallows", f"o{seed}", mods=mods, level=level)
            if level == D.MAX_LEVEL:
                assert d["offers"] == []
                continue
            assert len(d["offers"]) == min(3, 8 - len(mods)) and len(set(d["offers"])) == len(d["offers"])
            assert not set(d["offers"]) & set(mods), "never one the run already has"
            assert d["offers"] == D.generate("shallows", f"o{seed}", mods=mods, level=level)["offers"]


def test_swarming_puts_more_enemies_in_every_fight_the_boss_room_included():
    for seed in range(20):
        plain = D.generate("shallows", f"s{seed}")
        many = D.generate("shallows", f"s{seed}", mods=["swarming"])
        count = lambda d, n: sum(1 for e in d["enemies"].values() if e["room"] == n)
        for n, room in enumerate(plain["rooms"]):
            if room["kind"] == "combat":
                assert count(many, n) >= count(plain, n) + 1, (seed, n)
            if room["kind"] == "boss":
                assert count(many, n) == 1 + D.SWARM_BOSS
        spots = {(int(e["x"]), int(e["y"])) for e in many["enemies"].values()}
        assert len(spots) == len(many["enemies"]), "two enemies on one tile"
        reach = D.reachable(many)
        assert all((int(e["x"]), int(e["y"])) in reach for e in many["enemies"].values())
        assert all(many["tiles"][int(e["y"])][int(e["x"])] == "." for e in many["enemies"].values())


def test_keys_drop_from_the_boss_at_their_rates_and_a_boss_rush_never_drops_its_own_key():
    n, got = 2000, {"dream_key": 0, "boss_rush_key": 0}
    for i in range(n):
        d = D.generate("shallows", f"keys-{i}")
        for x in d["drops"].values():
            if x["base_id"] in got:
                assert x["enemy"] == d["boss"] and x["slot_count"] == 0 and x["enchants"] == []
                got[x["base_id"]] += 1
    assert abs(got["dream_key"] / n - 0.10) < 0.02, got
    assert abs(got["boss_rush_key"] / n - 0.03) < 0.012, got
    for i in range(300):
        d = D.generate("shallows", f"rush-{i}", boss_rush=True)
        assert "boss_rush_key" not in {x["base_id"] for x in d["drops"].values()}


def test_the_keys_leave_every_other_drop_as_it_was():
    """Keys roll on their own stream: an item a seed dropped before still drops."""
    d = D.generate("shallows", "same-loot")
    items = [x for x in d["drops"].values() if x["base_id"] not in ("dream_key", "boss_rush_key")]
    assert items and all(x["base_id"] in C.BASE_ITEMS and C.BASE_ITEMS[x["base_id"]]["kind"] != "key" for x in items)


def test_each_modifier_adds_a_tenth_of_the_levels_xp():
    def total(mods):
        d = D.generate("shallows", "xp-seed", mods=mods)
        return d["complete_xp"] + sum(e["xp"] for e in d["enemies"].values()), d
    base, plain = total([])
    for mods in (["brutal"], ["brutal", "swift"], ["brutal", "swift", "fortified"]):
        got, d = total(mods)
        assert got == round(base * (1 + D.MOD_XP * len(mods))), (mods, got, base)
        assert d["complete_xp"] >= plain["complete_xp"], "the clear bonus never shrinks"


# ── the Fracture (design §14.4a) ─────────────────────────────────────────────
def test_the_fracture_is_crossable_with_any_crack_group_open():
    """Doors and spawns are never on a crack, and the way through never depends on
    one being closed: open each group in turn and the boss's room is still reached."""
    for i in range(60):
        d = D.generate("fracture", f"cross-{i}", mods=["swarming"] if i % 3 == 0 else [])
        assert d["cracks"], "the Fracture has cracks"
        spawns = {(int(e["x"]), int(e["y"])) for e in d["enemies"].values()}
        mid = d["door_y"]
        for c in d["cracks"]:
            for x, y in c["tiles"]:
                assert (x, y) not in spawns, ("a spawn on a crack", x, y)
                assert not (abs(y - mid) <= 1 and any(x in (r["x0"], r["x1"] - 1) for r in d["rooms"])), ("a doorway crack", x, y)
        boss = d["enemies"][d["boss"]]
        for g in range(3):
            shut = {(x, y) for c in d["cracks"] if c["group"] == g for x, y in c["tiles"]}
            tiles = ["".join("x" if (x, y) in shut else ch for x, ch in enumerate(row)) for y, row in enumerate(d["tiles"])]
            seen = D.reachable({**d, "tiles": tiles})
            assert (int(boss["x"]) + 2, int(boss["y"])) in seen or (int(boss["x"]), int(boss["y"])) in seen, (i, g)
            for e in d["enemies"].values():
                if e["type"] != "boss":
                    assert (int(e["x"]), int(e["y"])) in seen, ("an enemy cut off", i, g, e)


def test_every_splitter_has_its_splinters_and_the_fracture_pays_more():
    d = D.generate("fracture", "split")
    kids = [e for e in d["enemies"].values() if e["type"] == "splinter"]
    splitters = [k for k, e in d["enemies"].items() if e["type"] == "splitter"]
    assert len(kids) == D.SPLINTERS * len(splitters) and splitters
    assert all(k["parent"] in splitters for k in kids)
    assert d["boss_kind"] == "breach" and d["enemies"][d["boss"]]["xp"] == D.DUNGEONS["fracture"]["boss_xp"]
    s = D.generate("shallows", "split")
    total = lambda x: x["complete_xp"] + sum(e["xp"] for e in x["enemies"].values())
    assert total(d) > 1.5 * total(s)


def test_fracture_loot_starts_at_tier_two_and_its_boss_at_three():
    for i in range(200):
        d = D.generate("fracture", f"tiers-{i}")
        for dr in d["drops"].values():
            if C.base(dr["base_id"])["kind"] != "standard":
                continue                                  # uniques and keys are their own thing
            floor = 3 if dr["enemy"] == d["boss"] else 2
            assert dr["tier"] >= floor, dr
