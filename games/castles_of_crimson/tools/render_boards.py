"""Render every board as an ASCII hexagon for visual verification against the
source image.

Run:  python -m games.castles_of_crimson.tools.render_boards

Each cell is a 2-char color code + die number, e.g. ``Y1`` = yellow/monastery
needing a 1. The rows are indented so the layout reads as the same radius-3
hexagon shown in the image (row widths 4-5-6-7-6-5-4). ASCII-only output (the
Windows console is cp1252).

Color codes (our 6 terrain colors -> tile type):
    C = burgundy / castle      S = blue / ship        G = gray / mine
    L = green / livestock      B = beige / building   Y = yellow / monastery
"""
from __future__ import annotations

from .. import board

CODE = {
    "burgundy": "C", "blue": "S", "gray": "G",
    "green": "L", "beige": "B", "yellow": "Y",
}


def _render(b: board.Board) -> str:
    rows = []
    for r in range(-3, 4):
        cells = []
        for q in range(-3, 4):
            sid = board.space_id(q, r)
            info = b.SPACES.get(sid)
            if info is None:
                continue
            mark = "*" if info["is_castle"] else " "
            cells.append(f"{CODE[info['color']]}{info['number']}{mark}")
        # Indent each row to centre the hexagon (row width varies 4..7).
        indent = "  " * (7 - len(cells))
        rows.append(indent + " ".join(cells))
    return "\n".join(rows)


def main() -> None:
    legend = ("Legend: C=castle S=ship G=mine L=livestock B=building Y=monastery"
              "   ('*' marks the starting castle)")
    print(legend)
    for bid in sorted(board.BOARDS):
        b = board.BOARDS[bid]
        # Region-size sanity (areas must be 1..8 and partition all 37 spaces).
        sizes = sorted((rg["size"] for rg in b.REGIONS.values()), reverse=True)
        covered = sum(sizes)
        print("\n" + "=" * 60)
        print(f"Board {b.id} - {b.name}   (spaces={len(b.SPACES)}, "
              f"regions={len(b.REGIONS)}, max_area={max(sizes)}, covered={covered})")
        print("-" * 60)
        print(_render(b))


if __name__ == "__main__":
    main()
