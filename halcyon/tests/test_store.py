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
            assert it["destroyed_reason"] in ("death", "fusion", "discard", "run_end"), it
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
    with pytest.raises(S.HalcyonError, match="two of the same ring"):
        S.move_item(db, ME, r2["item_id"], ("equipped", cid, "ring2"))
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


def test_only_identical_items_fuse(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 0))
    for i, other in enumerate(({**BOW, "tier": 2},
                               {**BOW, "slot_count": 0, "enchants": []},
                               {"base_id": "longbow", "tier": 1, "slot_count": 1,
                                "enchants": [{"id": "attack", "q": 0.5}]}), start=1):
        b = S.grant_item(db, ME, other, ("vault", i))
        with pytest.raises(S.HalcyonError, match="identical"):
            S.fuse(db, ME, a["item_id"], b["item_id"])
    with pytest.raises(S.HalcyonError):
        S.fuse(db, ME, a["item_id"], a["item_id"])
    assert len(_live(db)) == 4


def test_a_fusion_that_fails_half_way_changes_nothing(db, me):
    a = S.grant_item(db, ME, BOW, ("vault", 0))
    b = S.grant_item(db, ME, BOW, ("vault", 1))
    before = _snapshot(db)
    with pytest.raises(RuntimeError, match="injected"):
        S.fuse(_failing(db, "INSERT INTO hr_items"), ME, a["item_id"], b["item_id"])
    assert _snapshot(db) == before
    assert_invariants(db)


def test_fusion_can_rarely_gain_slots_and_never_passes_four(db, me):
    gained = set()
    for seed in range(300):
        a = S.grant_item(db, ME, VIGOR, ("vault", 0))
        b = S.grant_item(db, ME, VIGOR, ("vault", 1))
        new = S.fuse(db, ME, a["item_id"], b["item_id"], rng=random.Random(seed))
        gained.add(new["slot_count"])
        S.discard(db, ME, new["item_id"])
    assert gained == {0, 1, 2}, gained              # every branch reached, none beyond
    full = {"base_id": "band_of_focus", "tier": 1, "slot_count": 4,
            "enchants": [{"id": e, "q": 0.1} for e in ("max_hp", "max_mp", "attack", "defense")]}
    for seed in range(50):
        a = S.grant_item(db, ME, full, ("vault", 0))
        b = S.grant_item(db, ME, full, ("vault", 1))
        assert S.fuse(db, ME, a["item_id"], b["item_id"], rng=random.Random(seed))["slot_count"] == 4
        S.discard(db, ME, _live(db)[0]["item_id"])


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


def test_completing_adds_the_bonus_and_reaches_the_level_the_table_says(db, me):
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


def test_a_drop_from_another_run_cannot_be_named(db, me):
    run1 = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    S.apply_events(db, ME, run1["run_id"], _seq({"type": "kill", "enemy": "e1"},
                                                {"type": "pickup", "drop": "d1", "slot": 0},
                                                {"type": "recall"}))
    run2 = S.start_run(db, ME, me["char_id"], "shallows", "seed", _dungeon())
    out = S.apply_events(db, ME, run2["run_id"], _seq({"type": "move", "drop": "d1", "to": ["equipped", "weapon"]}))
    assert out["refused"] == [1], "a drop id names an item of THIS run only"


def test_items_follow_their_base_when_content_makes_it_unique(db, me):
    S.grant_item(db, ME, {"base_id": "repeater", "tier": 3, "slot_count": 0, "enchants": []}, ("vault", 5))
    conn = db()
    conn.execute("UPDATE hr_items SET kind='standard' WHERE base_id='repeater'")   # as minted before the change
    conn.commit()
    S.init_schema(conn)
    conn.close()
    assert _rows(db, "SELECT kind, tier FROM hr_items WHERE base_id='repeater'") == [{"kind": "unique", "tier": 1}]
