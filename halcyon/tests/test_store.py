"""The Halcyon Rift item store (halcyon/store.py).

The design's "what must never happen" list (docs/halcyon-rift-game-design.md
§20.3) is the spine of this file: an item in two places or none, a drop minted
twice, a half-done fusion or death, a re-sent batch that changes anything, a
town operation on a character who is mid-run, and a client that names its own
loot. Everything runs on a real sqlite FILE through core.db's `_Conn` wrapper —
the same wrapper prod uses over Turso — and the all-or-nothing tests inject a
failure between statements to prove the transaction leaves nothing behind.
"""
import random

from halcyon import content as C
import sqlite3

import pytest

from core.db import _Conn
from halcyon import store as S
from halcyon.content import EQUIP_SLOTS

ME, THEM = "u_me", "u_them"
BOW = {"base_id": "shortbow", "tier": 1, "slot_count": 1, "enchants": [{"id": "attack", "q": 0.5}]}
VEST = {"base_id": "leather_vest", "tier": 1, "slot_count": 0, "enchants": []}
VIGOR = {"base_id": "band_of_vigor", "tier": 2, "slot_count": 0, "enchants": []}
FOCUS = {"base_id": "band_of_focus", "tier": 2, "slot_count": 0, "enchants": []}


@pytest.fixture()
def db(tmp_path):
    path = str(tmp_path / "halcyon.db")

    def connect():
        return _Conn(sqlite3.connect(path))
    conn = connect()
    S.init_schema(conn)
    conn.close()
    connect.path = path
    return connect


@pytest.fixture()
def me(db):
    S.register_owner(db, ME, "account")
    return S.create_character(db, ME, 0, "ranger")


def _dungeon():
    return {"enemies": {"e1": {"type": "chaser"}, "e2": {"type": "shooter"}, "boss": {"type": "boss"}},
            "boss": "boss",
            "drops": {"d1": {**BOW, "enemy": "e1"},
                      "d2": {**VEST, "enemy": "e2"},
                      "d3": {**VIGOR, "enemy": "boss"}}}


DREAM_KEY = {"base_id": "dream_key", "tier": 1, "slot_count": 0, "enchants": []}
RUSH_KEY = {"base_id": "boss_rush_key", "tier": 1, "slot_count": 0, "enchants": []}


def _key(db, char_id, spec=DREAM_KEY, slot=15, owner=ME):
    """A key in the character's bag (the last slot, out of the tests' way)."""
    return S.grant_item(db, owner, spec, ("inventory", char_id, slot))


def _rows(db, sql, params=()):
    conn = db()
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return S._dicts(cur)
    finally:
        conn.close()


def _live(db, owner=ME):
    return _rows(db, "SELECT * FROM hr_items WHERE owner_id=? AND loc != 'destroyed' ORDER BY item_id", (owner,))


def _snapshot(db):
    """Everything persistent, for 'nothing changed' comparisons. Timestamps
    included on purpose: a no-op must not even touch a row."""
    return {t: _rows(db, f"SELECT * FROM {t} ORDER BY 1")
            for t in ("hr_items", "hr_characters", "hr_runs")}


def assert_invariants(db):
    """Every live item is in exactly one well-formed place, and nothing is left
    where the rules say nothing can be."""
    items = _rows(db, "SELECT * FROM hr_items")
    for it in items:
        loc = it["loc"]
        assert loc in ("vault", "inventory", "equipped", "ground", "destroyed"), it
        if loc == "vault":
            assert it["slot_index"] is not None and it["char_id"] is None, it
        elif loc in ("inventory", "equipped"):
            assert it["slot_index"] is not None and it["char_id"], it
            ch = _rows(db, "SELECT status FROM hr_characters WHERE char_id=?", (it["char_id"],))
            assert ch and ch[0]["status"] == "alive", f"an item on a fallen character: {it}"
        elif loc == "ground":
            run = _rows(db, "SELECT status FROM hr_runs WHERE run_id=?", (it["run_id"],))
            assert run and run[0]["status"] == "open", f"an item left on a closed run's floor: {it}"
        else:
            assert it["destroyed_reason"] in ("death", "fusion", "discard", "run_end", "key", "left"), it
    drops = [(i["origin_run_id"], i["origin_drop_id"]) for i in items if i["origin"] == "drop"]
    assert len(drops) == len(set(drops)), "a drop was minted twice"


def _seq(*events):
    return [{**e, "seq": n} for n, e in enumerate(events, start=1)]


class _FailOn:
    """A connection whose Nth statement matching `needle` raises — the
    'crash between statements' an all-or-nothing operation must survive."""

    def __init__(self, inner, needle):
        self._inner, self._needle = inner, needle

    def cursor(self):
        cur, needle = self._inner.cursor(), self._needle

        class C:
            description = property(lambda s: cur.description)

            def execute(s, sql, params=()):
                if needle in sql:
                    raise RuntimeError("injected failure")
                cur.execute(sql, params)
                return s

            def fetchone(s):
                return cur.fetchone()

            def fetchall(s):
                return cur.fetchall()
        return C()

    def commit(self):
        self._inner.commit()

    def close(self):
        self._inner.close()


def _failing(db, needle):
    return lambda: _FailOn(db(), needle)


# ── drops are minted once, from the server's record ──────────────────────────
def test_a_re_sent_batch_mints_its_drop_once_and_changes_nothing(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    batch = _seq({"type": "kill", "enemy": "e1"}, {"type": "pickup", "drop": "d1", "slot": 0})
    first = S.apply_events(db, ME, run["run_id"], batch)
    assert first == {"status": "open", "last_seq": 2, "refused": []}
    before = _snapshot(db)
    again = S.apply_events(db, ME, run["run_id"], batch)
    assert again["last_seq"] == 2 and again["refused"] == []
    after = _snapshot(db)
    for t in ("hr_items", "hr_characters"):
        assert after[t] == before[t], f"re-sending the batch changed {t}"
    assert [i["base_id"] for i in _live(db)] == ["shortbow"]
    assert_invariants(db)


def test_picking_up_the_same_drop_under_a_new_number_is_refused(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "kill", "enemy": "e1"},
        {"type": "pickup", "drop": "d1", "slot": 0},
        {"type": "pickup", "drop": "d1", "slot": 1}))
    assert out["refused"] == [3]
    assert len(_live(db)) == 1
    assert_invariants(db)


def test_the_database_itself_refuses_a_second_mint_of_one_drop(db, me):
    """The guard is a UNIQUE index, not just code: even a buggy path that skips
    every check cannot write the same drop twice."""
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "e1"},
                                               {"type": "pickup", "drop": "d1", "slot": 0}))
    conn = db()
    try:
        with pytest.raises(sqlite3.IntegrityError):
            S._insert_item(conn.cursor(), ME, S._validate_spec(BOW), "drop",
                           ("inventory", me["char_id"], None, 5), 0.0, run_id=run["run_id"], drop_id="d1")
    finally:
        conn.close()


def test_a_client_cannot_name_its_own_loot(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "pickup", "drop": "d1", "slot": 0},                      # nothing has dropped it yet
        {"type": "pickup", "drop": "d99", "slot": 0},                     # not in this dungeon
        {"type": "kill", "enemy": "e1"},
        {"type": "kill", "enemy": "e1"},                                  # killed twice
        {"type": "pickup", "drop": "d1", "slot": 0,                       # extra fields are ignored
         "base_id": "kingfisher_eye", "tier": 5, "enchants": [{"id": "attack", "q": 1.0}] * 4}))
    assert out["refused"] == [1, 2, 4]
    (it,) = _live(db)
    assert (it["base_id"], it["tier"], it["slot_count"]) == ("shortbow", 1, 1)
    assert S._item_out(it)["enchants"] == [{"id": "attack", "q": 0.5}]


def test_a_refused_event_does_not_block_the_ones_after_it(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "teleport"}, {"type": "kill", "enemy": "e1"}, {"type": "pickup", "drop": "d1", "slot": 0}))
    assert out == {"status": "open", "last_seq": 3, "refused": [1]}
    assert len(_live(db)) == 1


def test_a_gap_in_the_numbers_stops_the_batch_where_the_server_is(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], [
        {"seq": 1, "type": "kill", "enemy": "e1"},
        {"seq": 3, "type": "pickup", "drop": "d1", "slot": 0}])
    assert out["last_seq"] == 1 and _live(db) == []
    out = S.apply_events(db, ME, run["run_id"], [
        {"seq": 2, "type": "kill", "enemy": "e2"},
        {"seq": 3, "type": "pickup", "drop": "d1", "slot": 0}])
    assert out["last_seq"] == 3 and len(_live(db)) == 1


def test_a_pickup_into_a_full_slot_is_refused_and_the_drop_stays_available(db, me):
    S.grant_item(db, ME, VEST, ("inventory", me["char_id"], 0))
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "kill", "enemy": "e1"},
        {"type": "pickup", "drop": "d1", "slot": 0},
        {"type": "pickup", "drop": "d1", "slot": 1}))
    assert out["refused"] == [2]
    assert sorted(i["slot_index"] for i in _live(db)) == [0, 1]


# ── death ────────────────────────────────────────────────────────────────────
def _carrying(db, char_id):
    """A character with an equipped bow, a carried vest, a ring on the floor of
    its run and a ring in the vault."""
    S.grant_item(db, ME, VIGOR, ("vault", 0))
    bow = S.grant_item(db, ME, BOW, ("inventory", char_id, 0))
    S.move_item(db, ME, bow["item_id"], ("equipped", char_id, "weapon"))
    run = S.start_run(db, ME, char_id, "shallows", "seed", _dungeon())
    S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "kill", "enemy": "e2"}, {"type": "pickup", "drop": "d2", "slot": 3},
        {"type": "kill", "enemy": "boss"}, {"type": "pickup", "drop": "d3", "slot": 4}))
    ring = next(i for i in _live(db) if i["origin_drop_id"] == "d3")
    S.apply_events(db, ME, run["run_id"], [{"seq": 5, "type": "drop_item", "item": ring["item_id"]}])
    return run


def test_an_item_put_down_is_picked_back_up_by_its_drop_or_its_id_and_never_from_another_run(db, me):
    run = _carrying(db, me["char_id"])
    # The ring picked up this run is named by its drop (the page has no id for it yet).
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 6, "type": "pickup_item", "drop": "d3", "slot": 7}])
    assert out["refused"] == []
    ring = next(i for i in _live(db) if i["origin_drop_id"] == "d3")
    assert (ring["loc"], ring["slot_index"]) == ("inventory", 7)
    # A carried-in item goes down and comes back by its id.
    bow = next(i for i in _live(db) if i["base_id"] == "shortbow")
    out = S.apply_events(db, ME, run["run_id"], [
        {"seq": 7, "type": "drop_item", "item": bow["item_id"]},
        {"seq": 8, "type": "pickup_item", "item": bow["item_id"], "slot": 2}])
    assert out["refused"] == []
    bow = next(i for i in _live(db) if i["item_id"] == bow["item_id"])
    assert (bow["loc"], bow["slot_index"]) == ("inventory", 2)
    # Only from the floor: picking up what is already carried is refused.
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 9, "type": "pickup_item", "item": bow["item_id"], "slot": 5}])
    assert out["refused"] == [9]


def test_death_destroys_everything_carried_and_nothing_in_the_vault(db, me):
    run = _carrying(db, me["char_id"])
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 6, "type": "death"}])
    assert out["status"] == "died"
    live = _live(db)
    assert [(i["loc"], i["base_id"]) for i in live] == [("vault", "band_of_vigor")]
    dead = _rows(db, "SELECT destroyed_reason FROM hr_items WHERE loc='destroyed'")
    assert sorted(d["destroyed_reason"] for d in dead) == ["death"] * 3
    ch = _rows(db, "SELECT status, death_run_id FROM hr_characters")[0]
    assert ch == {"status": "dead", "death_run_id": run["run_id"]}
    view = S.owner_view(db, ME)
    assert view["characters"] == [] and len(view["fallen"]) == 1
    assert_invariants(db)


def test_a_dream_rift_death_is_a_safe_return_to_town(db, me):
    item = S.grant_item(db, ME, BOW, ("inventory", me["char_id"], 0))
    _key(db, me["char_id"])
    run = S.start_run(db, ME, me["char_id"], "shallows", "dream-death", _dungeon(), practice=True)
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 1, "type": "drop_item", "item": item["item_id"]},
                                                   {"seq": 2, "type": "death"}])
    assert out["status"] == "died"
    assert _char(db, me["char_id"]) == {"level": 1, "xp": 0, "status": "alive"}
    assert [(i["base_id"], i["loc"]) for i in _live(db)] == [("shortbow", "inventory")]
    assert not _rows(db, "SELECT * FROM hr_items WHERE destroyed_reason='death'")


def test_a_dream_rift_gives_no_rewards_or_xp_and_records_a_boss_time(db, me):
    _key(db, me["char_id"])
    run = S.start_run(db, ME, me["char_id"], "shallows", "dream-clear", _dungeon(), practice=True)
    out = S.apply_events(db, ME, run["run_id"], [
        {"seq": 1, "type": "kill", "enemy": "boss", "elapsed_ticks": 321},
        {"seq": 2, "type": "pickup", "drop": "d3", "slot": 0},
        {"seq": 3, "type": "complete"},
    ])
    assert out["status"] == "completed" and out["refused"] == [2]
    assert _char(db, me["char_id"]) == {"level": 1, "xp": 0, "status": "alive"}
    assert _live(db) == []
    assert S.owner_view(db, ME)["leaderboards"] == {"shallows": [{"time_ticks": 321, "practice": True}]}


def test_a_personal_rift_leaderboard_keeps_only_the_five_fastest_times(db, me):
    for n, ticks in enumerate((500, 100, 300, 200, 50, 600), start=1):
        _key(db, me["char_id"])
        run = S.start_run(db, ME, me["char_id"], "shallows", f"time-{n}", _dungeon(), practice=True)
        S.apply_events(db, ME, run["run_id"], [
            {"seq": 1, "type": "kill", "enemy": "boss", "elapsed_ticks": ticks},
            {"seq": 2, "type": "complete"},
        ])
    assert [x["time_ticks"] for x in S.owner_view(db, ME)["leaderboards"]["shallows"]] == [50, 100, 200, 300, 500]


def test_a_death_that_fails_half_way_changes_nothing(db, me):
    run = _carrying(db, me["char_id"])
    before = _snapshot(db)
    with pytest.raises(RuntimeError, match="injected"):
        S.apply_events(_failing(db, "SET status='dead'"), ME, run["run_id"], [{"seq": 6, "type": "death"}])
    assert _snapshot(db) == before
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 6, "type": "death"}])
    assert out["status"] == "died"                  # and the retry still lands
    assert_invariants(db)


def test_a_dead_character_frees_its_slot(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    S.apply_events(db, ME, run["run_id"], [{"seq": 1, "type": "death"}])
    again = S.create_character(db, ME, 0, "ranger")
    assert again["char_id"] != me["char_id"]
    with pytest.raises(S.HalcyonError):
        S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())


# ── recall, closed runs and leaving without a word ───────────────────────────
def test_recall_keeps_what_was_picked_up_and_clears_the_floor(db, me):
    run = _carrying(db, me["char_id"])
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 6, "type": "recall"}])
    assert out["status"] == "recalled"
    assert sorted(i["base_id"] for i in _live(db)) == ["band_of_vigor", "leather_vest", "shortbow"]
    gone = _rows(db, "SELECT base_id, destroyed_reason FROM hr_items WHERE loc='destroyed'")
    assert gone == [{"base_id": "band_of_vigor", "destroyed_reason": "run_end"}]
    assert_invariants(db)


def test_a_closed_run_accepts_nothing(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "e1"}, {"type": "recall"}))
    before = _snapshot(db)
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 3, "type": "pickup", "drop": "d1", "slot": 0},
                                                 {"seq": 4, "type": "death"}])
    assert out["status"] == "recalled"
    assert _snapshot(db) == before


def test_completion_needs_the_boss_dead(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq({"type": "complete"}))
    assert out == {"status": "open", "last_seq": 1, "refused": [1]}
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 2, "type": "kill", "enemy": "boss"},
                                                 {"seq": 3, "type": "complete"}])
    assert out["status"] == "completed"


def test_a_closed_tab_is_a_recall_when_the_character_is_next_opened(db, me):
    run = _carrying(db, me["char_id"])              # the tab closes here: no recall sent
    S.open_character(db, ME, me["char_id"])
    status = _rows(db, "SELECT status FROM hr_runs WHERE run_id=?", (run["run_id"],))[0]["status"]
    assert status == "recalled"
    assert sorted(i["base_id"] for i in _live(db)) == ["band_of_vigor", "leather_vest", "shortbow"]
    assert_invariants(db)


def test_starting_a_new_run_closes_the_old_one_as_a_recall(db, me):
    old = _carrying(db, me["char_id"])
    S.start_run(db, ME, me["char_id"], "shallows", "seed2", _dungeon())
    assert _rows(db, "SELECT status FROM hr_runs WHERE run_id=?", (old["run_id"],))[0]["status"] == "recalled"
    late = S.apply_events(db, ME, old["run_id"], [{"seq": 6, "type": "death"}])
    assert late["status"] == "recalled"             # a late death report for a closed run is ignored
    assert len(S.owner_view(db, ME)["characters"]) == 1
    assert_invariants(db)


def test_the_sweep_closes_only_runs_idle_past_the_limit(db, me):
    S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon(), now=1000.0)
    assert S.sweep_runs(db, now=1000.0 + 3600) == 0
    assert S.sweep_runs(db, now=1000.0 + 25 * 3600) == 1
    assert _rows(db, "SELECT status FROM hr_runs")[0]["status"] == "recalled"


# ── town ─────────────────────────────────────────────────────────────────────
def test_town_cannot_touch_a_character_who_is_in_a_dungeon(db, me):
    bow = S.grant_item(db, ME, BOW, ("inventory", me["char_id"], 0))
    vault_ring = S.grant_item(db, ME, VIGOR, ("vault", 0))
    S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    for op in (lambda: S.move_item(db, ME, bow["item_id"], ("vault", 5)),
               lambda: S.discard(db, ME, bow["item_id"]),
               lambda: S.move_item(db, ME, vault_ring["item_id"], ("inventory", me["char_id"], 4))):
        with pytest.raises(S.HalcyonError, match="dungeon"):
            op()
    other = S.create_character(db, ME, 1, "ranger")    # the vault is still usable by others
    S.move_item(db, ME, vault_ring["item_id"], ("inventory", other["char_id"], 0))
    assert_invariants(db)


def test_moving_into_an_occupied_slot_swaps(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 0))
    b = S.grant_item(db, ME, VEST, ("inventory", me["char_id"], 2))
    S.move_item(db, ME, a["item_id"], ("inventory", me["char_id"], 2))
    places = {i["item_id"]: (i["loc"], i["slot_index"]) for i in _live(db)}
    assert places == {a["item_id"]: ("inventory", 2), b["item_id"]: ("vault", 0)}
    assert_invariants(db)


def test_equipment_rules(db, me):
    bow = S.grant_item(db, ME, BOW, ("vault", 0))
    r1 = S.grant_item(db, ME, VIGOR, ("vault", 1))
    r2 = S.grant_item(db, ME, VIGOR, ("vault", 2))
    r3 = S.grant_item(db, ME, FOCUS, ("vault", 3))
    cid = me["char_id"]
    with pytest.raises(S.HalcyonError, match="slot"):
        S.move_item(db, ME, bow["item_id"], ("equipped", cid, "armor"))
    S.move_item(db, ME, r1["item_id"], ("equipped", cid, "ring1"))
    # Two of the same STANDARD ring are fine (owner's call, 2026-11-18) ...
    S.move_item(db, ME, r2["item_id"], ("equipped", cid, "ring2"))
    S.move_item(db, ME, r2["item_id"], ("vault", 2))
    S.move_item(db, ME, r3["item_id"], ("equipped", cid, "ring2"))
    # swapping the same base into the slot it already fills is fine
    S.move_item(db, ME, r2["item_id"], ("equipped", cid, "ring1"))
    eq = {i["slot_index"]: i["item_id"] for i in _live(db) if i["loc"] == "equipped"}
    assert eq == {EQUIP_SLOTS.index("ring1"): r2["item_id"], EQUIP_SLOTS.index("ring2"): r3["item_id"]}
    assert_invariants(db)


def test_a_stale_version_is_refused(db, me):
    it = S.grant_item(db, ME, BOW, ("vault", 0))
    S.move_item(db, ME, it["item_id"], ("vault", 1), expected_version=it["version"])
    with pytest.raises(S.HalcyonError, match="changed"):
        S.move_item(db, ME, it["item_id"], ("vault", 2), expected_version=it["version"])


def test_nobody_moves_anyone_elses_items(db, me):
    S.register_owner(db, THEM, "account")
    it = S.grant_item(db, ME, BOW, ("vault", 0))
    with pytest.raises(S.HalcyonError, match="no such item"):
        S.move_item(db, THEM, it["item_id"], ("vault", 0))
    with pytest.raises(S.HalcyonError, match="no such item"):
        S.discard(db, THEM, it["item_id"])
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    with pytest.raises(S.HalcyonError, match="no such run"):
        S.apply_events(db, THEM, run["run_id"], [{"seq": 1, "type": "death"}])


def test_discard_leaves_a_tombstone(db, me):
    it = S.grant_item(db, ME, BOW, ("vault", 0))
    S.discard(db, ME, it["item_id"])
    assert _live(db) == []
    row = _rows(db, "SELECT loc, destroyed_reason FROM hr_items WHERE item_id=?", (it["item_id"],))
    assert row == [{"loc": "destroyed", "destroyed_reason": "discard"}]


# ── fusion ───────────────────────────────────────────────────────────────────
def test_fusion_consumes_two_and_mints_one_in_the_first_ones_place(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 4))
    b = S.grant_item(db, ME, {**BOW, "enchants": [{"id": "max_hp", "q": 0.9}]}, ("vault", 9))
    new = S.fuse(db, ME, a["item_id"], b["item_id"], rng=random.Random(7))
    assert (new["loc"], new["slot_index"], new["base_id"], new["tier"]) == ("vault", 4, "shortbow", 1)
    assert new["fused_from"] == [a["item_id"], b["item_id"]] and new["origin"] == "fusion"
    assert len(new["enchants"]) == new["slot_count"] >= 1
    assert [i["item_id"] for i in _live(db)] == [new["item_id"]]
    gone = _rows(db, "SELECT destroyed_reason FROM hr_items WHERE item_id IN (?, ?)", (a["item_id"], b["item_id"]))
    assert [g["destroyed_reason"] for g in gone] == ["fusion", "fusion"]
    assert_invariants(db)


def test_only_two_of_the_same_item_fuse(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 0))
    b = S.grant_item(db, ME, {"base_id": "longbow", "tier": 1, "slot_count": 1,
                              "enchants": [{"id": "attack", "q": 0.5}]}, ("vault", 1))
    with pytest.raises(S.HalcyonError, match="same item"):
        S.fuse(db, ME, a["item_id"], b["item_id"])
    with pytest.raises(S.HalcyonError):
        S.fuse(db, ME, a["item_id"], a["item_id"])
    assert len(_live(db)) == 2


def test_two_of_a_base_fuse_whatever_their_tiers_and_slots(db, me):
    """RotMG's route (owner, 2026-11-19): the higher tier, at least the fewer slots."""
    for seed in range(40):
        a = S.grant_item(db, ME, {**BOW, "tier": 2}, ("vault", 0))
        b = S.grant_item(db, ME, {**BOW, "tier": 5, "slot_count": 2,
                                  "enchants": [{"id": "attack", "q": 0.5}, {"id": "max_hp", "q": 0.5}]}, ("vault", 1))
        new = S.fuse(db, ME, a["item_id"], b["item_id"], rng=random.Random(seed))
        assert new["tier"] == 5 and new["slot_count"] >= 1
        assert not any(C.is_special(e["id"]) for e in new["enchants"])
        S.discard(db, ME, new["item_id"])
    assert_invariants(db)


def test_a_fusion_that_fails_half_way_changes_nothing(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 0))
    b = S.grant_item(db, ME, BOW, ("vault", 1))
    before = _snapshot(db)
    with pytest.raises(RuntimeError, match="injected"):
        S.fuse(_failing(db, "INSERT INTO hr_items"), ME, a["item_id"], b["item_id"])
    assert _snapshot(db) == before
    assert_invariants(db)


def test_fusion_odds_are_the_slot_table_from_the_floor_up():
    """0 -> 50% for 1+, 1 -> 37.5% for 2+, 2 -> 25% for 3+, 3 -> 12.5% for 4."""
    for floor, up in ((0, 0.5), (1, 0.375), (2, 0.25), (3, 0.125)):
        odds = dict(C.fuse_slot_odds(floor))
        assert min(odds) == floor and abs(sum(odds.values()) - 1) < 1e-12
        assert abs(1 - odds[floor] - up) < 1e-12
    assert C.fuse_slot_odds(4) == ((4, 1.0),)


def test_fusion_never_drops_below_the_floor_and_reaches_every_count(db, me):
    seen = set()
    for seed in range(400):
        a = S.grant_item(db, ME, VIGOR, ("vault", 0))
        b = S.grant_item(db, ME, VIGOR, ("vault", 1))
        new = S.fuse(db, ME, a["item_id"], b["item_id"], rng=random.Random(seed))
        seen.add(new["slot_count"])
        S.discard(db, ME, new["item_id"])
    assert seen == {0, 1, 2, 3}, seen          # 4 from a 0-slot pair is 1 in 171: not asserted
    full = {"base_id": "band_of_focus", "tier": 1, "slot_count": 4,
            "enchants": [{"id": e, "q": 0.1} for e in ("max_hp", "max_mp", "attack", "defense")]}
    for seed in range(30):
        a = S.grant_item(db, ME, full, ("vault", 0))
        b = S.grant_item(db, ME, full, ("vault", 1))
        assert S.fuse(db, ME, a["item_id"], b["item_id"], rng=random.Random(seed))["slot_count"] == 4
        S.discard(db, ME, _live(db)[0]["item_id"])


# ── shards, the reroll and breaking down ─────────────────────────────────────
def _give_shards(db, n, owner=ME):
    conn = db()
    conn.cursor().execute("UPDATE hr_owners SET shards=? WHERE owner_id=?", (n, owner))
    conn.commit(); conn.close()


def _balance(db, owner=ME):
    return S.owner_view(db, owner)["shards"]


RING3 = {"base_id": "band_of_focus", "tier": 3, "slot_count": 3,
         "enchants": [{"id": "attack", "q": 0.9}, {"id": "defense", "q": 0.2}, {"id": "max_hp", "q": 0.3}]}


def test_a_reroll_keeps_locked_lines_and_charges_double_for_each(db, me):
    it = S.grant_item(db, ME, RING3, ("vault", 0))
    base = C.reroll_cost(3, 3, 0)
    _give_shards(db, base * 2 + base * 4)
    one = S.reroll(db, ME, it["item_id"], [0], rng=random.Random(1))
    assert one["cost"] == base * 2 and one["enchants"][0] == RING3["enchants"][0]
    assert len({e["id"] for e in one["enchants"]}) == 3 and one["item_id"] == it["item_id"]
    two = S.reroll(db, ME, it["item_id"], [0, 1], rng=random.Random(2))
    assert two["cost"] == base * 4 and two["enchants"][:2] == one["enchants"][:2]
    assert _balance(db) == 0
    with pytest.raises(S.HalcyonError, match="not enough shards"):
        S.reroll(db, ME, it["item_id"], [], rng=random.Random(3))
    assert_invariants(db)


def test_a_reroll_never_makes_a_special_line_and_always_keeps_one(db, me):
    it = S.grant_item(db, ME, {**RING3, "enchants": [{"id": "fury", "q": 0.5}, *RING3["enchants"][1:]]}, ("vault", 0))
    _give_shards(db, 10 ** 6)
    for seed in range(60):
        out = S.reroll(db, ME, it["item_id"], [], rng=random.Random(seed))
        assert out["enchants"][0] == {"id": "fury", "q": 0.5}
        assert out["cost"] == C.reroll_cost(3, 3, 1)            # the special line counts as a lock
        assert not any(C.is_special(e["id"]) for e in out["enchants"][1:])
    with pytest.raises(S.HalcyonError, match="nothing to reroll"):
        S.reroll(db, ME, it["item_id"], [1, 2])


def test_a_reroll_refuses_bad_lines_locked_items_and_keys(db, me):
    it = S.grant_item(db, ME, RING3, ("vault", 0))
    key = S.grant_item(db, ME, DREAM_KEY, ("vault", 1))
    bare = S.grant_item(db, ME, VIGOR, ("vault", 2))
    _give_shards(db, 10 ** 6)
    for keep in ([5], [-1], [True], "0"):
        with pytest.raises(S.HalcyonError):
            S.reroll(db, ME, it["item_id"], keep)
    with pytest.raises(S.HalcyonError):
        S.reroll(db, ME, key["item_id"], [])
    with pytest.raises(S.HalcyonError, match="no lines"):
        S.reroll(db, ME, bare["item_id"], [])
    S.set_lock(db, ME, it["item_id"], True)
    with pytest.raises(S.HalcyonError, match="locked"):
        S.reroll(db, ME, it["item_id"], [])
    assert _balance(db) == 10 ** 6


def test_breaking_an_item_down_pays_shards_and_destroys_it(db, me):
    it = S.grant_item(db, ME, RING3, ("vault", 0))
    out = S.salvage(db, ME, it["item_id"])
    assert out["gained"] == C.salvage_value(3, 3) == out["shards"] == _balance(db)
    assert _live(db) == []
    (row,) = _rows(db, "SELECT destroyed_reason FROM hr_items WHERE item_id=?", (it["item_id"],))
    assert row["destroyed_reason"] == "salvage"
    locked = S.grant_item(db, ME, RING3, ("vault", 0))
    S.set_lock(db, ME, locked["item_id"], True)
    with pytest.raises(S.HalcyonError, match="locked"):
        S.salvage(db, ME, locked["item_id"])


# ── owners ───────────────────────────────────────────────────────────────────
def test_a_guest_secret_is_issued_once_and_verifies(db):
    secret = S.register_owner(db, "g_123", "guest")
    assert secret and S.verify_guest(db, "g_123", secret)
    assert not S.verify_guest(db, "g_123", secret + "x")
    assert not S.verify_guest(db, "g_123", "")
    assert S.register_owner(db, "g_123", "guest") is None
    assert S.register_owner(db, ME, "account") is None
    assert not S.verify_guest(db, ME, "anything")


def test_idle_guests_are_pruned_and_accounts_are_not(db):
    S.register_owner(db, "g_old", "guest", now=0.0)
    ch = S.create_character(db, "g_old", 0, "ranger", now=0.0)
    S.grant_item(db, "g_old", BOW, ("inventory", ch["char_id"], 0), now=0.0)
    S.register_owner(db, "g_new", "guest", now=90000.0)
    S.register_owner(db, ME, "account", now=0.0)
    assert S.prune_guests(db, now=100000.0) == 1
    owners = {r["owner_id"] for r in _rows(db, "SELECT owner_id FROM hr_owners")}
    assert owners == {"g_new", ME}
    assert _rows(db, "SELECT * FROM hr_items WHERE owner_id='g_old'") == []
    assert _rows(db, "SELECT * FROM hr_characters WHERE owner_id='g_old'") == []


def test_four_character_slots(db):
    S.register_owner(db, ME, "account")
    for s in range(4):
        S.create_character(db, ME, s, "ranger")
    with pytest.raises(S.HalcyonError):
        S.create_character(db, ME, 4, "ranger")
    with pytest.raises(S.HalcyonError, match="already"):
        S.create_character(db, ME, 0, "ranger")


# ── XP and levels (design §10.1) ──────────────────────────────────────────────
def _xp_dungeon():
    d = _dungeon()
    for e, xp in (("e1", 4), ("e2", 5), ("boss", 20)):
        d["enemies"][e]["xp"] = xp
    d["complete_xp"] = 30
    return d


def _char(db, char_id):
    return _rows(db, "SELECT level, xp, status FROM hr_characters WHERE char_id=?", (char_id,))[0]


def test_each_kill_credits_the_xp_the_servers_dungeon_says_it_was_worth(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "e1", "xp": 9999},
                                               {"type": "kill", "enemy": "e2"}))
    assert _char(db, me["char_id"])["xp"] == 9, "an XP amount on the event is ignored"


def test_a_kill_counted_twice_or_refused_earns_nothing(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    batch = _seq({"type": "kill", "enemy": "e1"}, {"type": "kill", "enemy": "e1"},
                 {"type": "kill", "enemy": "nobody"})
    S.apply_events(db, ME, run["run_id"], batch)
    S.apply_events(db, ME, run["run_id"], batch)                  # re-sent whole
    assert _char(db, me["char_id"])["xp"] == 4


def test_recall_keeps_the_xp_the_run_earned(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "e1"}, {"type": "recall"}))
    assert _char(db, me["char_id"])["xp"] == 4
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "e2"}))
    S.open_character(db, ME, me["char_id"])                       # a closed tab is a recall too
    assert _char(db, me["char_id"])["xp"] == 9


def test_the_boss_kill_adds_the_clear_bonus_and_reaches_the_level_the_table_says(db, me):
    from halcyon import content as C
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "complete"}))     # refused: boss alive
    assert _char(db, me["char_id"])["xp"] == 0
    S.apply_events(db, ME, run["run_id"], [{"seq": 2, "type": "kill", "enemy": "boss"},
                                           {"seq": 3, "type": "complete"}])
    assert _char(db, me["char_id"]) == {"level": 1, "xp": 50, "status": "alive"}
    db_conn = db()
    db_conn.execute("UPDATE hr_characters SET xp=? WHERE char_id=?", (C.LEVEL_XP[1] - 10, me["char_id"]))
    db_conn.commit(); db_conn.close()
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "boss"}))
    assert _char(db, me["char_id"])["level"] == 2


def test_the_level_table_climbs_to_twenty_and_a_shallows_clear_is_about_one_level():
    from halcyon import content as C
    from halcyon import dungeon as D
    assert len(C.LEVEL_XP) == C.MAX_LEVEL and C.LEVEL_XP[0] == 0
    steps = [b - a for a, b in zip(C.LEVEL_XP, C.LEVEL_XP[1:])]
    assert all(b > a for a, b in zip(steps, steps[1:])), "each level asks more than the last"
    assert C.level_for(0) == 1 and C.level_for(10 ** 9) == C.MAX_LEVEL
    assert all(C.level_for(t) == n + 1 and C.level_for(t - 1) == n for n, t in enumerate(C.LEVEL_XP) if n)
    for seed in map(str, range(30)):
        d = D.generate("shallows", seed)
        clear = sum(e["xp"] for e in d["enemies"].values()) + d["complete_xp"]
        assert C.LEVEL_XP[1] <= clear < C.LEVEL_XP[2], (seed, clear)


def test_a_dungeon_with_a_made_up_xp_value_is_refused(db, me):
    d = _xp_dungeon()
    d["enemies"]["e1"]["xp"] = "lots"
    with pytest.raises(S.HalcyonError):
        S.start_run(db, ME, me["char_id"], "shallows", "seed", d)


# ── changing gear mid-run ────────────────────────────────────────────────────
def test_a_drop_picked_up_this_run_can_be_equipped_by_naming_the_drop(db, me):
    bow = S.grant_item(db, ME, BOW, ("inventory", me["char_id"], 0))
    S.move_item(db, ME, bow["item_id"], ("equipped", me["char_id"], "weapon"))
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "kill", "enemy": "e2"},
        {"type": "pickup", "drop": "d2", "slot": 3},                      # a vest, into slot 3
        {"type": "move", "drop": "d2", "to": ["equipped", "armor"]},
        {"type": "move", "drop": "d2", "to": ["equipped", "weapon"]},     # a vest is not a weapon
        {"type": "move", "drop": "nope", "to": ["inventory", 5]}))
    assert out["refused"] == [4, 5]
    vest = _rows(db, "SELECT loc, slot_index FROM hr_items WHERE origin_drop_id='d2'")
    assert vest == [{"loc": "equipped", "slot_index": EQUIP_SLOTS.index("armor")}]


def test_a_drop_picked_up_this_run_can_be_locked_and_then_cannot_be_dropped(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "kill", "enemy": "e2"},
        {"type": "pickup", "drop": "d2", "slot": 3},
        {"type": "lock", "drop": "d2", "locked": True},
        {"type": "drop_item", "drop": "d2"},                              # locked: refused
        {"type": "lock", "drop": "nope", "locked": True},                 # no such drop
        {"type": "lock", "drop": "d2", "locked": "yes"}))                 # not a bool
    assert out["refused"] == [4, 5, 6]
    vest = _rows(db, "SELECT loc, locked FROM hr_items WHERE origin_drop_id='d2'")
    assert vest == [{"loc": "inventory", "locked": 1}]
    S.apply_events(db, ME, run["run_id"], [{"type": "lock", "drop": "d2", "locked": False, "seq": 7}])
    assert _rows(db, "SELECT locked FROM hr_items WHERE origin_drop_id='d2'") == [{"locked": 0}]


def test_a_drop_from_another_run_cannot_be_named(db, me):
    run1 = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    S.apply_events(db, ME, run1["run_id"], _seq({"type": "kill", "enemy": "e1"},
                                                {"type": "pickup", "drop": "d1", "slot": 0},
                                                {"type": "recall"}))
    run2 = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run2["run_id"], _seq({"type": "move", "drop": "d1", "to": ["equipped", "weapon"]}))
    assert out["refused"] == [1], "a drop id names an item of THIS run only"


def test_items_follow_their_base_when_content_makes_it_unique_and_keep_their_tier(db, me):
    S.grant_item(db, ME, {"base_id": "repeater", "tier": 3, "slot_count": 0, "enchants": []}, ("vault", 5))
    conn = db()
    conn.execute("UPDATE hr_items SET kind='standard' WHERE base_id='repeater'")   # as minted before the change
    conn.commit()
    S.init_schema(conn)
    conn.close()
    assert _rows(db, "SELECT kind, tier FROM hr_items WHERE base_id='repeater'") == [{"kind": "unique", "tier": 3}]


def test_the_clear_bonus_comes_with_the_boss_so_a_recall_after_it_keeps_it(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "seed", _xp_dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "boss"}, {"type": "recall"}))
    assert _char(db, me["char_id"])["xp"] == 50          # boss 20 + the clear's 30, no portal needed


def test_never_two_of_the_same_unique_whatever_their_slots(db, me):
    eye = lambda n: {"base_id": "kingfisher_eye", "tier": 1, "slot_count": n,
                     "enchants": [{"id": e, "q": 0.5} for e in ("attack", "defense", "max_hp", "max_mp")[:n]]}
    a = S.grant_item(db, ME, eye(0), ("vault", 0))
    b = S.grant_item(db, ME, eye(2), ("vault", 1))
    cid = me["char_id"]
    S.move_item(db, ME, a["item_id"], ("equipped", cid, "ring1"))
    with pytest.raises(S.HalcyonError, match="two of the same unique"):
        S.move_item(db, ME, b["item_id"], ("equipped", cid, "ring2"))
    assert_invariants(db)


def test_init_schema_moves_abilities_to_their_new_classes(db):
    """The shield retired (2026-11-18): every Grounding Aegis becomes a Stillness Orb
    (now the Paladin's), and a Diviner WEARING an orb gets a Star Tome instead. Run
    twice: the second pass changes nothing."""
    S.register_owner(db, ME, "account")
    div = S.create_character(db, ME, 1, "diviner")
    aegis = S.grant_item(db, ME, {"base_id": "grounding_aegis", "tier": 2, "slot_count": 1,
                                  "enchants": [{"id": "ability_power", "q": 0.4}]}, ("vault", 0))
    orb = S.grant_item(db, ME, {"base_id": "stillness_orb", "tier": 1, "slot_count": 0, "enchants": []}, ("vault", 1))
    # An orb a Diviner already wore before the change (the store refuses it now).
    raw = sqlite3.connect(db.path)
    raw.execute("UPDATE hr_items SET loc='equipped', char_id=?, slot_index=? WHERE item_id=?",
                (div["char_id"], EQUIP_SLOTS.index("ability"), orb["item_id"]))
    raw.commit(); raw.close()
    for _ in range(2):
        conn = db(); S.init_schema(conn); conn.close()
        got = {i["item_id"]: i["base_id"] for i in _live(db)}
        assert got[aegis["item_id"]] == "stillness_orb" and got[orb["item_id"]] == "star_tome"


# ── going deeper (design §14.6) ────────────────────────────────────────────────
def _make(dungeon_id, seed, class_id, mods, level):
    from halcyon import dungeon as D
    return D.generate(dungeon_id, seed, class_id=class_id, mods=mods, level=level)


def _real_run(db, me):
    from halcyon import dungeon as D
    d = D.generate("shallows", "deep", class_id="ranger")
    run = S.start_run(db, ME, me["char_id"], "shallows", "deep", d)
    return run, d


def test_descend_needs_the_boss_dead_and_an_offered_modifier(db, me):
    run, d = _real_run(db, me)
    rid, offer = run["run_id"], d["offers"][0]
    with pytest.raises(S.HalcyonError, match="boss"):
        S.descend(db, ME, rid, offer, 1, _make)
    S.apply_events(db, ME, rid, _seq({"type": "kill", "enemy": d["boss"]}))
    not_offered = next(m for m in C.RIFT_MODS if m not in d["offers"])
    with pytest.raises(S.HalcyonError, match="offered"):
        S.descend(db, ME, rid, not_offered, 1, _make)
    with pytest.raises(S.HalcyonError):
        S.descend(db, THEM, rid, offer, 1, _make)
    two = S.descend(db, ME, rid, offer, 1, _make)
    assert two["level"] == 2 and two["mods"] == [offer] and two["boss"] == "L2-boss"
    assert S.descend(db, ME, rid, offer, 1, _make) == two, "a retried descent hands back the same level"
    with pytest.raises(S.HalcyonError):
        S.descend(db, ME, rid, two["offers"][0], 2, _make)     # level 2's boss still stands


def test_a_deeper_level_pays_its_own_bonus_its_drops_mint_once_and_only_level_one_is_timed(db, me):
    run, d = _real_run(db, me)
    rid = run["run_id"]
    S.apply_events(db, ME, rid, _seq({"type": "kill", "enemy": d["boss"], "elapsed_ticks": 3000}))
    xp1 = _rows(db, "SELECT xp FROM hr_characters WHERE char_id=?", (me["char_id"],))[0]["xp"]
    two = S.descend(db, ME, rid, d["offers"][0], 1, _make)
    drop = next(k for k, v in two["drops"].items() if v["enemy"] == two["boss"])
    out = S.apply_events(db, ME, rid, [
        {"seq": 2, "type": "kill", "enemy": d["boss"]},                # level 1's boss, again
        {"seq": 3, "type": "kill", "enemy": two["boss"], "elapsed_ticks": 900},
        {"seq": 4, "type": "pickup", "drop": drop, "slot": 3},
        {"seq": 5, "type": "complete"}])
    assert out["refused"] == [2] and out["status"] == "completed"
    xp2 = _rows(db, "SELECT xp FROM hr_characters WHERE char_id=?", (me["char_id"],))[0]["xp"]
    assert xp2 - xp1 == two["enemies"][two["boss"]]["xp"] + two["complete_xp"]
    times = _rows(db, "SELECT time_ticks FROM hr_rift_times WHERE run_id=?", (rid,))
    assert [t["time_ticks"] for t in times] == [3000]
    assert [i["origin_drop_id"] for i in _live(db) if i["origin"] == "drop"] == [drop]
    assert_invariants(db)


def test_descending_leaves_the_floor_behind(db, me):
    run, d = _real_run(db, me)
    rid = run["run_id"]
    drop = next(k for k, v in d["drops"].items() if v["enemy"] == d["boss"])
    out = S.apply_events(db, ME, rid, _seq({"type": "kill", "enemy": d["boss"]},
                                           {"type": "pickup", "drop": drop, "slot": 0},
                                           {"type": "drop_item", "drop": drop}))
    assert out["refused"] == []
    assert [i["loc"] for i in _live(db)] == ["ground"]
    S.descend(db, ME, rid, d["offers"][0], 1, _make)
    assert _live(db) == [], "what was left on level 1's floor is gone"
    assert_invariants(db)


# ── the QOL pass (design §19.1): lock, the graveyard, the one record ─────────
def test_a_locked_item_cannot_be_discarded_fused_or_dropped_and_unlocks_again(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 0))
    b = S.grant_item(db, ME, BOW, ("vault", 1))
    out = S.set_lock(db, ME, a["item_id"], True)
    assert out["locked"] is True and out["version"] == a["version"]     # a lock is not a move
    with pytest.raises(S.HalcyonError, match="locked"):
        S.discard(db, ME, a["item_id"])
    with pytest.raises(S.HalcyonError, match="locked"):
        S.fuse(db, ME, b["item_id"], a["item_id"])
    assert len(_live(db)) == 2
    # Mid-run: it can be moved, never put on the floor.
    S.move_item(db, ME, a["item_id"], ("inventory", me["char_id"], 0))
    run = S.start_run(db, ME, me["char_id"], "shallows", "lock", _dungeon())
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 1, "type": "drop_item", "item": a["item_id"]},
                                                   {"seq": 2, "type": "move", "item": a["item_id"], "to": ["inventory", 5]}])
    assert out["refused"] == [1]
    S.set_lock(db, ME, a["item_id"], False)                             # locking works mid-run too
    out = S.apply_events(db, ME, run["run_id"], [{"seq": 3, "type": "drop_item", "item": a["item_id"]}])
    assert 3 not in out["refused"]                                      # (the list is the run's so far)
    assert next(i for i in _live(db) if i["item_id"] == a["item_id"])["loc"] == "ground"
    assert_invariants(db)


def test_nobody_locks_anyone_elses_items(db, me):
    S.register_owner(db, THEM, "account")
    it = S.grant_item(db, ME, BOW, ("vault", 0))
    with pytest.raises(S.HalcyonError):
        S.set_lock(db, THEM, it["item_id"], True)


def test_a_death_leaves_its_screen_in_the_graveyard(db, me):
    run = _carrying(db, me["char_id"])
    S.apply_events(db, ME, run["run_id"], [{"seq": 6, "type": "death", "summary": {
        "src": "boss:nova", "hit": 31.6, "taken": 412.4, "kills": 9, "ticks": 5400,
        "dungeon_name": "made up", "items": ["not the page's to say"], "x" * 50: 1}}])
    view = S.owner_view(db, ME)
    d = view["fallen"][0]["death_summary"]
    assert (d["src"], d["hit"], d["taken"], d["kills"], d["ticks"]) == ("boss:nova", 31.6, 412.4, 9, 5400)
    # The server's own facts, not the page's: where, and what was carried as it fell.
    assert d["dungeon_id"] == "shallows" and d["dungeon_name"] == "shallows" and d["depth"] == 1
    assert sorted((i["base_id"], i["loc"]) for i in d["items"]) == [("leather_vest", "inventory"), ("shortbow", "equipped")]
    assert next(i for i in d["items"] if i["base_id"] == "shortbow")["equip_slot"] == "weapon"
    assert "x" * 50 not in d
    assert view["fallen_count"] == 1


def test_a_strange_death_summary_is_bounded_and_a_dream_death_writes_none(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "odd", _dungeon())
    S.apply_events(db, ME, run["run_id"], [{"seq": 1, "type": "death",
                                            "summary": {"src": "y" * 500, "hit": 1e12, "kills": -4, "taken": "lots"}}])
    d = S.owner_view(db, ME)["fallen"][0]["death_summary"]
    assert len(d["src"]) == 40 and d["hit"] == 100_000 and d["kills"] == 0 and "taken" not in d
    c = S.create_character(db, ME, 1, "ranger")
    _key(db, c["char_id"])
    run = S.start_run(db, ME, c["char_id"], "shallows", "dream", _dungeon(), practice=True)
    S.apply_events(db, ME, run["run_id"], [{"seq": 1, "type": "death", "summary": {"src": "boss:fan"}}])
    assert _rows(db, "SELECT death_summary FROM hr_characters WHERE char_id=?", (c["char_id"],)) == [{"death_summary": None}]


def test_the_best_level_counts_the_fallen_too(db, me):
    assert S.owner_view(db, ME)["best_level"] == 1
    conn = db()
    conn.cursor().execute("UPDATE hr_characters SET level=7, status='dead' WHERE char_id=?", (me["char_id"],))
    conn.commit(); conn.close()
    S.create_character(db, ME, 0, "ninja")
    assert S.owner_view(db, ME)["best_level"] == 7


# ── keys (owner's ask, 2026-11-18) ─────────────────────────────────────────────
def test_a_dream_rift_needs_a_dream_key_in_the_bag_and_spends_it(db, me):
    with pytest.raises(S.HalcyonError, match="Dream Key"):
        S.start_run(db, ME, me["char_id"], "shallows", "no-key", _dungeon(), practice=True)
    S.grant_item(db, ME, DREAM_KEY, ("vault", 0))                 # the vault's does not count
    with pytest.raises(S.HalcyonError, match="Dream Key"):
        S.start_run(db, ME, me["char_id"], "shallows", "no-key", _dungeon(), practice=True)
    assert not _rows(db, "SELECT * FROM hr_runs")
    key = _key(db, me["char_id"])
    S.start_run(db, ME, me["char_id"], "shallows", "key", _dungeon(), practice=True)
    assert _rows(db, "SELECT loc, destroyed_reason FROM hr_items WHERE item_id=?", (key["item_id"],)) == [
        {"loc": "destroyed", "destroyed_reason": "key"}]
    assert [i["loc"] for i in _live(db) if i["base_id"] == "dream_key"] == ["vault"]
    assert_invariants(db)


def test_a_boss_rush_run_spends_its_key_and_records_no_time(db, me):
    rush = {**_dungeon(), "boss_rush": True}
    with pytest.raises(S.HalcyonError, match="Boss Rush key"):
        S.start_run(db, ME, me["char_id"], "shallows", "rush", rush)
    _key(db, me["char_id"], RUSH_KEY)
    run = S.start_run(db, ME, me["char_id"], "shallows", "rush", rush)
    assert not [i for i in _live(db) if i["base_id"] == "boss_rush_key"]
    S.apply_events(db, ME, run["run_id"], [{"seq": 1, "type": "kill", "enemy": "boss", "elapsed_ticks": 99},
                                           {"seq": 2, "type": "complete"}])
    assert S.owner_view(db, ME)["leaderboards"] == {}
    _key(db, me["char_id"], RUSH_KEY)
    _key(db, me["char_id"], DREAM_KEY, slot=14)
    with pytest.raises(S.HalcyonError, match="no Boss Rush"):
        S.start_run(db, ME, me["char_id"], "shallows", "both", rush, practice=True)


def test_keys_do_not_fuse_or_go_in_an_equipment_slot(db, me):
    a, b = _key(db, me["char_id"], slot=1), _key(db, me["char_id"], slot=2)
    with pytest.raises(S.HalcyonError, match="keys do not fuse"):
        S.fuse(db, ME, a["item_id"], b["item_id"])
    for slot in EQUIP_SLOTS:
        with pytest.raises(S.HalcyonError):
            S.move_item(db, ME, a["item_id"], ("equipped", me["char_id"], slot))


# ── the town's ground (owner's ask, 2026-11-18) ────────────────────────────────
def _loc(db, item_id):
    return _rows(db, "SELECT loc, run_id, destroyed_reason FROM hr_items WHERE item_id=?", (item_id,))[0]


def test_dropping_in_town_puts_it_on_the_ground_and_it_can_be_picked_back_up(db, me):
    bow = S.grant_item(db, ME, BOW, ("inventory", me["char_id"], 0))
    S.move_item(db, ME, bow["item_id"], ("floor", me["char_id"]))
    assert _loc(db, bow["item_id"]) == {"loc": "ground", "run_id": "town:" + me["char_id"], "destroyed_reason": None}
    back = S.move_item(db, ME, bow["item_id"], ("inventory", me["char_id"], 3))
    assert back["loc"] == "inventory" and back["slot_index"] == 3
    S.move_item(db, ME, bow["item_id"], ("floor", me["char_id"]))
    S.move_item(db, ME, bow["item_id"], ("vault", 5))               # straight into the vault works too
    assert _loc(db, bow["item_id"])["loc"] == "vault"
    assert_invariants(db)


def test_the_town_ground_is_emptied_on_leaving_town(db, me):
    for n, leave in enumerate((
            lambda: S.start_run(db, ME, me["char_id"], "shallows", "s", _dungeon()),
            lambda: S.open_character(db, ME, me["char_id"]),
            lambda: S.leave_town(db, ME, me["char_id"]))):
        it = S.grant_item(db, ME, VEST, ("inventory", me["char_id"], 0))
        S.move_item(db, ME, it["item_id"], ("floor", me["char_id"]))
        leave()
        assert _loc(db, it["item_id"])["loc"] == "destroyed" and _loc(db, it["item_id"])["destroyed_reason"] == "left", n
        S.open_character(db, ME, me["char_id"])                     # back in town for the next
    assert_invariants(db)


def test_the_town_ground_refuses_what_it_should(db, me):
    bow = S.grant_item(db, ME, BOW, ("inventory", me["char_id"], 0))
    S.set_lock(db, ME, bow["item_id"], True)
    with pytest.raises(S.HalcyonError, match="locked"):
        S.move_item(db, ME, bow["item_id"], ("floor", me["char_id"]))
    S.set_lock(db, ME, bow["item_id"], False)
    with pytest.raises(S.HalcyonError):
        S.move_item(db, ME, bow["item_id"], ("ground", "some-run"))   # only the town's own ground
    S.move_item(db, ME, bow["item_id"], ("floor", me["char_id"]))
    vest = S.grant_item(db, ME, VEST, ("inventory", me["char_id"], 1))
    with pytest.raises(S.HalcyonError, match="full"):
        S.move_item(db, ME, bow["item_id"], ("inventory", me["char_id"], 1))   # no swapping onto the ground
    with pytest.raises(S.HalcyonError):
        S.discard(db, ME, bow["item_id"])                                    # lying there, it is only picked up
    S.register_owner(db, THEM, "account")
    with pytest.raises(S.HalcyonError):
        S.move_item(db, THEM, bow["item_id"], ("vault", 0))
    S.start_run(db, ME, me["char_id"], "shallows", "s", _dungeon())
    with pytest.raises(S.HalcyonError, match="dungeon"):
        S.move_item(db, ME, vest["item_id"], ("floor", me["char_id"]))



def _clear_shallows(db, char_id, practice=False):
    """Fell the Shallows' boss with this character (what opens the Fracture)."""
    from halcyon import dungeon as D
    d = D.generate("shallows", "opens-fracture")
    run = S.start_run(db, ME, char_id, "shallows", d["seed"], d, practice=practice)
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": d["boss"]}))


def test_the_fracture_opens_once_this_character_fells_the_shallows_boss(db, me):
    from halcyon import dungeon as D
    d = D.generate("fracture", "gate")
    with pytest.raises(S.HalcyonError, match="clear The Shallows"):
        S.start_run(db, ME, me["char_id"], "fracture", d["seed"], d)
    assert S.owner_view(db, ME)["characters"][0]["cleared"] == []
    _key(db, me["char_id"])                            # a Dream Rift's boss does not count
    _clear_shallows(db, me["char_id"], practice=True)
    assert S.owner_view(db, ME)["characters"][0]["cleared"] == []
    _clear_shallows(db, me["char_id"])
    assert S.owner_view(db, ME)["characters"][0]["cleared"] == ["shallows"]
    S.start_run(db, ME, me["char_id"], "fracture", d["seed"], d)
    # another character on the same account starts at the beginning
    other = S.create_character(db, ME, 1, "ranger")
    with pytest.raises(S.HalcyonError, match="clear The Shallows"):
        S.start_run(db, ME, other["char_id"], "fracture", d["seed"], d)


def test_a_run_starts_with_at_most_three_modifiers(db, me):
    from halcyon import dungeon as D
    four = D.generate("shallows", "four", mods=["fortified", "brutal", "swift", "warded"])
    with pytest.raises(S.HalcyonError, match="at most 3"):
        S.start_run(db, ME, me["char_id"], "shallows", four["seed"], four)
    three = D.generate("shallows", "three", mods=["fortified", "brutal", "swift"])
    S.start_run(db, ME, me["char_id"], "shallows", three["seed"], three)


def test_a_splinter_is_credited_only_after_its_splitter(db, me):
    from halcyon import dungeon as D
    _clear_shallows(db, me["char_id"])
    d = D.generate("fracture", "split-store")
    splitter = next(k for k, e in d["enemies"].items() if e["type"] == "splitter")
    kid = next(k for k, e in d["enemies"].items() if e.get("parent") == splitter)
    run = S.start_run(db, ME, me["char_id"], "fracture", d["seed"], d)
    out = S.apply_events(db, ME, run["run_id"], _seq(
        {"type": "kill", "enemy": kid},                  # its Splitter is still standing
        {"type": "kill", "enemy": splitter},
        {"type": "kill", "enemy": kid}))
    assert out["refused"] == [1]


def test_armor_is_shared_by_type():
    """Light armor is the Ranger's and the Diviner's, heavy the Paladin's and the Ninja's."""
    for base in ("leather_vest", "seer_robes"):
        assert C.usable_by(base, "ranger") and C.usable_by(base, "diviner")
        assert not C.usable_by(base, "paladin") and not C.usable_by(base, "ninja")
    for base in ("plate_armor", "shadow_garb"):
        assert C.usable_by(base, "paladin") and C.usable_by(base, "ninja")
        assert not C.usable_by(base, "ranger") and not C.usable_by(base, "diviner")
    from halcyon import dungeon as D
    for cls, table in D.LOOT_BY_CLASS.items():
        armor = [(b, w) for b, w in table if C.BASE_ITEMS[b]["slot"] == "armor"]
        assert len(armor) == 2 and sum(w for _, w in armor) == 22, cls
        assert all(C.usable_by(b, cls) for b, _ in armor), cls


def test_a_ranger_wears_light_armor_of_either_kind_but_not_heavy(db, me):
    robes = S.grant_item(db, ME, {"base_id": "seer_robes", "tier": 1, "slot_count": 0, "enchants": []},
                         ("inventory", me["char_id"], 0))
    S.move_item(db, ME, robes["item_id"], ("equipped", me["char_id"], "armor"))
    plate = S.grant_item(db, ME, {"base_id": "plate_armor", "tier": 1, "slot_count": 0, "enchants": []},
                         ("inventory", me["char_id"], 1))
    with pytest.raises(S.HalcyonError, match="class cannot use it"):
        S.move_item(db, ME, plate["item_id"], ("equipped", me["char_id"], "armor"))


# ── shards from runs ─────────────────────────────────────────────────────────
def test_shards_come_home_on_a_recall_and_scale_with_the_loot_bonus(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "sh-a", _dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "e1"}, {"type": "kill", "enemy": "e2"},
                                               {"type": "kill", "enemy": "boss"}, {"type": "recall"}))
    assert _balance(db) == 2 * C.SHARDS_PER_KILL + C.SHARDS_PER_BOSS
    d = {**_dungeon(), "mods": ["brutal", "swarming", "volatile"], "level": 3}
    run = S.start_run(db, ME, me["char_id"], "shallows", "sh-b", d)
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "boss"}, {"type": "complete"}))
    bonus = C.loot_bonus(3, 3)
    assert _balance(db) == 12 + int(C.SHARDS_PER_BOSS * (1 + bonus) + 1e-9)


def test_a_death_loses_the_runs_shards_and_a_dream_rift_pays_none(db, me):
    _give_shards(db, 7)
    _key(db, me["char_id"])
    run = S.start_run(db, ME, me["char_id"], "shallows", "sh-d", _dungeon(), practice=True)
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "boss"}, {"type": "complete"}))
    assert _balance(db) == 7
    run = S.start_run(db, ME, me["char_id"], "shallows", "sh-c", _dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "boss"}, {"type": "death"}))
    assert _balance(db) == 7, "the vault's shards are never touched by a death"


def test_a_run_closed_by_opening_the_character_still_banks_its_shards(db, me):
    run = S.start_run(db, ME, me["char_id"], "shallows", "sh-e", _dungeon())
    S.apply_events(db, ME, run["run_id"], _seq({"type": "kill", "enemy": "boss"}))
    S.open_character(db, ME, me["char_id"])
    assert _balance(db) == C.SHARDS_PER_BOSS
