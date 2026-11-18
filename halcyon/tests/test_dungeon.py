"""The dungeon generator (halcyon/dungeon.py): every dungeon it can make is
completable, and what it hands the item store is accepted by it."""
import sqlite3

import pytest

from core.db import _Conn
from halcyon import dungeon as D
from halcyon import store as S

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
    for p in d["pickups"]:
        assert (int(p["x"]), int(p["y"])) in reach, f"pickup {p['id']} cannot be reached"
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
