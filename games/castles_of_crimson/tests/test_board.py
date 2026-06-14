"""Structural invariants for the standard duchy board.

A wrong board silently breaks every downstream scoring test, so these lock the
layout's correctness before any engine logic depends on it.
"""
from games.castles_of_crimson import board


def test_space_count():
    # Radius-3 hexagon = 1 + 6 + 12 + 18 = 37 spaces.
    assert len(board.SPACES) == 37


def test_every_space_has_valid_number_and_color():
    for sid, info in board.SPACES.items():
        assert 1 <= info["number"] <= 6, sid
        assert info["color"] in board.COLORS, sid


def test_unique_starting_castle():
    castles = [sid for sid, info in board.SPACES.items() if info["is_castle"]]
    assert castles == [board.space_id(*board.CASTLE_SPACE)]
    assert board.SPACES[castles[0]]["color"] == "burgundy"


def test_adjacency_is_symmetric():
    for sid, nbrs in board.ADJACENCY.items():
        for nb in nbrs:
            assert sid in board.ADJACENCY[nb], f"{sid} ~ {nb} not symmetric"
        # No self-loops, no duplicates.
        assert sid not in nbrs
        assert len(nbrs) == len(set(nbrs))
        # A hex has at most 6 neighbors.
        assert len(nbrs) <= 6


def test_board_is_connected():
    # Every space reachable from the castle through adjacency.
    start = board.space_id(*board.CASTLE_SPACE)
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        for nb in board.ADJACENCY[cur]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    assert seen == set(board.SPACES)


def test_regions_partition_all_spaces():
    covered = set()
    for rid, reg in board.REGIONS.items():
        assert reg["spaces"], rid
        assert covered.isdisjoint(reg["spaces"]), f"{rid} overlaps another region"
        covered |= reg["spaces"]
    assert covered == set(board.SPACES)


def test_region_sizes_in_score_domain():
    # Area-score table covers sizes 1..8.
    for rid, reg in board.REGIONS.items():
        assert 1 <= reg["size"] <= 8, f"{rid} size {reg['size']} out of 1..8"


def test_regions_are_single_color_and_contiguous():
    for rid, reg in board.REGIONS.items():
        colors = {board.SPACES[s]["color"] for s in reg["spaces"]}
        assert colors == {reg["color"]}, rid
        # Contiguity: BFS within the region reaches all its spaces.
        start = next(iter(reg["spaces"]))
        seen = {start}
        stack = [start]
        while stack:
            cur = stack.pop()
            for nb in board.ADJACENCY[cur]:
                if nb in reg["spaces"] and nb not in seen:
                    seen.add(nb)
                    stack.append(nb)
        assert seen == reg["spaces"], f"{rid} not contiguous"


def test_region_of_lookup_consistent():
    for sid in board.SPACES:
        rid = board.region_of(sid)
        assert sid in board.REGIONS[rid]["spaces"]


def test_castle_region_is_size_one():
    castle_sid = board.space_id(*board.CASTLE_SPACE)
    reg = board.REGIONS[board.region_of(castle_sid)]
    assert reg["has_castle"]
    assert reg["size"] == 1


def test_all_six_colors_present():
    present = {info["color"] for info in board.SPACES.values()}
    assert present == set(board.COLORS)
