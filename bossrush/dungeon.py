"""Two-room Boss Rush arenas, based on the Halcyon Rift greybox (d52d2f57)."""

ENTRANCE = (
    "..........",
    "..........",
    "..........",
    "..........",
    "....S.....",
    "..........",
    "..........",
    "..........",
    "..........",
)

BOSS_ROOM = (
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
    "......................",
    ".........B............",
    "......................",
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
)

# A full-height fissure divides the room. The two five-tile crossings trade off.
FRACTURE_BOSS = (
    "..........xx..........",
    "..........xx..........",
    "..oo......11......oo..",
    "..oo......11......oo..",
    "..........11..........",
    "..........11..........",
    "..........11..........",
    "..........xx..........",
    "..........22..........",
    "..........22..........",
    "..........22..........",
    "..oo......22......oo..",
    "..oo......22......oo..",
    "..........xx..........",
    "..........xx..........",
)


ASHEN_BOSS = (
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
    "......................",
    "..........B...........",
    "......................",
    "......................",
    "......................",
    "...oo............oo...",
    "...oo............oo...",
    "......................",
    "......................",
)

LANTERN_FEN = (
    "......................",
    "......................",
    "..L..oo...............",
    ".....oo.........o..L..",
    "................o.....",
    "......................",
    "......................",
    "..........B...........",
    "......................",
    "......................",
    ".................oo...",
    "....o............oo...",
    "....o.....L...........",
    "......................",
    "......................",
)

WARDEN_COURT = (
    "......................",
    "......................",
    "......................",
    "................Z.....",
    "......................",
    "......................",
    "......................",
    "....Z.....B...........",
    "......................",
    "......................",
    "......................",
    "................Z.....",
    "......................",
    "......................",
    "......................",
)

BELL_COURT = (
    "......................",
    "......................",
    "......................",
    "..........L...........",
    "......................",
    "......................",
    ".....L.........L......",
    "..........B...........",
    "......................",
    "......................",
    ".......L.....L........",
    "......................",
    "......................",
    "......................",
    "......................",
)

BOSSES = {
    "shallows": ("The Shallows", "The Tidewarden", "tidewarden", BOSS_ROOM),
    "fracture": ("The Fracture", "The Schism", "breach", FRACTURE_BOSS),
    "ashen": ("The Ashen Breach", "The Pyre", "pyre", ASHEN_BOSS),
    "fen": ("The Lantern Fen", "The Cinderwake", "cinderwake", LANTERN_FEN),
    "seal-court": ("The Seal Court", "The Warden", "warden", WARDEN_COURT),
    "bell-court": ("The Bell Court", "The Hollow Bellkeeper", "bellkeeper", BELL_COURT),
}


DEFAULT_BOSS_SET = "rift-trio"
BOSS_SETS = {
    DEFAULT_BOSS_SET: ("Rift Trio", ("shallows", "fracture", "ashen")),
    "lantern-trio": ("Lantern Trio", ("fen", "seal-court", "bell-court")),
}


def arena(rift: str, seed: str) -> dict:
    name, boss_name, boss_kind, template = BOSSES[rift]
    height = len(template) + 2
    mid = height // 2
    corridor = 3
    width = len(ENTRANCE[0]) + len(template[0]) + corridor + 4
    grid = [["#"] * width for _ in range(height)]
    rooms = []
    cracks = {}
    objectives = []
    start = boss = None
    left_wall = 0
    for kind, rows in (("entrance", ENTRANCE), ("boss", template)):
        x0 = left_wall + 1
        y0 = (height - len(rows)) // 2
        for dy, row in enumerate(rows):
            for dx, tile in enumerate(row):
                x, y = x0 + dx, y0 + dy
                grid[y][x] = tile if tile in "ox" else "."
                if tile == "S":
                    start = {"x": x + 0.5, "y": y + 0.5}
                elif tile == "B":
                    boss = {"x": x + 0.5, "y": y + 0.5}
                elif tile in "ZL":
                    objectives.append({"x": x + 0.5, "y": y + 0.5})
                elif tile in "123":
                    cracks.setdefault(int(tile) - 1, []).append([x, y])
        x1 = x0 + len(rows[0])
        rooms.append({"kind": kind, "x0": x0, "x1": x1})
        left_wall = x1 + corridor + 1

    for y in range(mid - 1, mid + 2):
        for x in range(rooms[0]["x1"], rooms[1]["x0"]):
            grid[y][x] = "."

    fissure = [x for x, tile in enumerate(grid[mid]) if tile == "x"]
    if rift == "fracture":
        # The Schism starts suspended over the fissure between the two banks.
        room = rooms[1]
        boss = {"x": (room["x0"] + room["x1"]) / 2, "y": mid + 0.5}
    enemies = {"boss": {"type": "boss", "room": 1, **boss}}

    return {
        "id": rift, "name": name, "boss_name": boss_name, "boss_kind": boss_kind,
        "seed": seed, "width": width, "height": height, "door_y": mid,
        "tiles": ["".join(row) for row in grid], "rooms": rooms,
        "start": start, "enemies": enemies, "drops": {}, "pickups": [],
        "cracks": [{"room": 1, "group": group, "tiles": cracks[group]} for group in sorted(cracks)],
        **({"fissure": [fissure[0], fissure[-1] + 1]} if fissure else {}),
        **({"objectives": objectives} if objectives else {}),
        "hazard": "creep" if rift == "ashen" else None,
    }
