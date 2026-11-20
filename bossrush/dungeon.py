"""Two-room boss arenas from the Halcyon Rift greybox (d52d2f57)."""

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

FRACTURE_BOSS = (
    "......................",
    "......................",
    "...oo.....1......oo...",
    "...oo.....1......oo...",
    "..........1...........",
    "......................",
    "..222...........333...",
    "..........B...........",
    "..333...........222...",
    "......................",
    "..........1...........",
    "...oo.....1......oo...",
    "...oo.....1......oo...",
    "......................",
    "......................",
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

BOSSES = {
    "shallows": ("The Shallows", "The Tidewarden", "tidewarden", BOSS_ROOM),
    "fracture": ("The Fracture", "The Schism", "breach", FRACTURE_BOSS),
    "ashen": ("The Ashen Breach", "The Pyre", "pyre", ASHEN_BOSS),
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
    start = boss = None
    left_wall = 0
    for kind, rows in (("entrance", ENTRANCE), ("boss", template)):
        x0 = left_wall + 1
        y0 = (height - len(rows)) // 2
        for dy, row in enumerate(rows):
            for dx, tile in enumerate(row):
                x, y = x0 + dx, y0 + dy
                grid[y][x] = "o" if tile == "o" else "."
                if tile == "S":
                    start = {"x": x + 0.5, "y": y + 0.5}
                elif tile == "B":
                    boss = {"x": x + 0.5, "y": y + 0.5}
                elif tile in "123":
                    cracks.setdefault(int(tile) - 1, []).append([x, y])
        x1 = x0 + len(rows[0])
        rooms.append({"kind": kind, "x0": x0, "x1": x1})
        left_wall = x1 + corridor + 1

    for y in range(mid - 1, mid + 2):
        for x in range(rooms[0]["x1"], rooms[1]["x0"]):
            grid[y][x] = "."

    enemies = {"boss": {"type": "boss", "room": 1, **boss}}
    if rift == "ashen":
        # The Pyre wakes these adds halfway through its fight.
        for n in range(2):
            enemies[f"kiln{n + 1}"] = {"type": "kiln", "room": 1, "summon": "boss", **boss}

    return {
        "id": rift, "name": name, "boss_name": boss_name, "boss_kind": boss_kind,
        "seed": seed, "width": width, "height": height, "door_y": mid,
        "tiles": ["".join(row) for row in grid], "rooms": rooms,
        "start": start, "enemies": enemies, "drops": {}, "pickups": [],
        "cracks": [{"room": 1, "group": group, "tiles": cracks[group]} for group in sorted(cracks)],
        "hazard": "creep" if rift == "ashen" else None,
    }
