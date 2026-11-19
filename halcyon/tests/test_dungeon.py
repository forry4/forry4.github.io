"""The dungeon generator (halcyon/dungeon.py): every dungeon it can make is
completable, and what it hands the item store is accepted by it."""
import sqlite3

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


def _loot_sample(n, mods=(), cls="ranger"):
    """Per source: how many items each enemy dropped, and each item's quality."""
    counts = {t: [] for t in C.DROP_COUNT}
    quality = {"enemy": [], "boss": []}
    slots = []
    for i in range(n):
        d = D.generate("shallows", f"loot-{i}-{len(mods)}", cls, mods=list(mods))
        per = {}
        for dr in d["drops"].values():
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
    for mods in ((), ("fortified", "brutal", "swift")):
        counts, quality, slots = _loot_sample(1500, mods)
        for etype, table in C.DROP_COUNT.items():
            _close(counts[etype], C.chances(table))
        for src in ("enemy", "boss"):
            _close(quality[src], C.chances(C.quality_table(src, len(mods))))
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
    assert d["mods"] == ["fortified", "swift"] and d["scale"] == {"hp": 1.5, "dmg": 1.0, "speed": 1.25}
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
