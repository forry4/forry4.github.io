"""Structural invariants for every selectable duchy board.

A wrong board silently breaks every downstream scoring test, so these lock each
layout's correctness before any engine logic depends on it. The invariants run
over all 9 boards in the registry (parametrized by board id).
"""
import pytest

from games.castles_of_crimson import board

ALL_BOARDS = list(board.BOARDS.values())
BOARD_IDS = [b.id for b in ALL_BOARDS]


@pytest.fixture(params=ALL_BOARDS, ids=BOARD_IDS)
def b(request):
    return request.param


def test_registry_has_nine_boards():
    assert len(board.BOARDS) == 9
    assert BOARD_IDS == [str(i) for i in range(1, 10)]
    assert all(bd.name for bd in ALL_BOARDS)


def test_space_count(b):
    # Radius-3 hexagon = 1 + 6 + 12 + 18 = 37 spaces.
    assert len(b.SPACES) == 37


def test_every_space_has_valid_number_and_color(b):
    for sid, info in b.SPACES.items():
        assert 1 <= info["number"] <= 6, sid
        assert info["color"] in board.COLORS, sid


def test_has_burgundy_spaces(b):
    # Each board must have at least one burgundy space for the starting castle.
    castles = [sid for sid, info in b.SPACES.items() if info["is_castle"]]
    assert len(castles) >= 1
    assert all(b.SPACES[sid]["color"] == "burgundy" for sid in castles)


def test_adjacency_is_symmetric(b):
    for sid, nbrs in b.ADJACENCY.items():
        for nb in nbrs:
            assert sid in b.ADJACENCY[nb], f"{sid} ~ {nb} not symmetric"
        assert sid not in nbrs                       # no self-loops
        assert len(nbrs) == len(set(nbrs))           # no duplicates
        assert len(nbrs) <= 6                         # at most 6 neighbors


def test_board_is_connected(b):
    # Every space reachable from an arbitrary start through adjacency.
    start = next(iter(b.SPACES))
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        for nb in b.ADJACENCY[cur]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    assert seen == set(b.SPACES)


def test_regions_partition_all_spaces(b):
    covered = set()
    for rid, reg in b.REGIONS.items():
        assert reg["spaces"], rid
        assert covered.isdisjoint(reg["spaces"]), f"{rid} overlaps another region"
        covered |= reg["spaces"]
    assert covered == set(b.SPACES)


def test_region_sizes_in_score_domain(b):
    # Area-score table covers sizes 1..8; a larger area would crash the scorer.
    for rid, reg in b.REGIONS.items():
        assert 1 <= reg["size"] <= 8, f"{b.id}:{rid} size {reg['size']} out of 1..8"


def test_regions_are_single_color_and_contiguous(b):
    for rid, reg in b.REGIONS.items():
        colors = {b.SPACES[s]["color"] for s in reg["spaces"]}
        assert colors == {reg["color"]}, rid
        start = next(iter(reg["spaces"]))
        seen = {start}
        stack = [start]
        while stack:
            cur = stack.pop()
            for nb in b.ADJACENCY[cur]:
                if nb in reg["spaces"] and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        assert seen == reg["spaces"], f"{rid} not contiguous"


def test_region_of_lookup_consistent(b):
    for sid in b.SPACES:
        rid = b.region_of(sid)
        assert sid in b.REGIONS[rid]["spaces"]


def test_castle_regions_in_score_domain(b):
    # Burgundy regions can be any size 1-8; the starting castle placement is
    # chosen at game start (engine state), not fixed by the board.
    for rid, reg in b.REGIONS.items():
        if reg["color"] == "burgundy":
            assert 1 <= reg["size"] <= 8, f"{b.id}:{rid} burgundy region size {reg['size']}"


def test_all_six_colors_present(b):
    present = {info["color"] for info in b.SPACES.values()}
    assert present == set(board.COLORS)


# ── Back-compat module-level shim still points at the default board ───────────
def test_module_shim_matches_default_board():
    d = board.BOARDS[board.DEFAULT_BOARD_ID]
    assert board.SPACES is d.SPACES
    some_sid = next(iter(d.SPACES))
    assert board.neighbors(some_sid) == d.neighbors(some_sid)
    assert board.region_of(some_sid) == d.region_of(some_sid)
