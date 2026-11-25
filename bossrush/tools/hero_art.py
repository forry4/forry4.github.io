"""Draw the Boss Rush heroes: one 12 px chunky sprite per class, facing right.

Each hero is a text grid below (one character per pixel, '.' clear) over a palette,
in the RotMG / Darza manner the bosses use: a few flat colors and a black outline.
The game flips a sprite to face left and bobs it a pixel while walking.

    python bossrush/tools/hero_art.py            # writes webapp/public/art/bossrush/hero-*.png
    python bossrush/tools/hero_art.py --zoom DIR # also writes a gridded 16x sheet

A class in HAND_EDITED was retouched in a pixel editor: its PNG is the source then,
and this tool leaves it alone unless told --force.
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "webapp" / "public" / "art" / "bossrush"
HAND_EDITED: set[str] = set()

K = "#0a060e"          # the outline, the same black as the bosses'
SKIN, SKIN_D = "#f2c39b", "#c98b6b"
EYE = "#1c1426"

HEROES = {
    # A hooded archer in teal, bow held out in front.
    "ranger": ({"k": K, "H": "#6fdbe2", "h": "#3aa0ad", "s": SKIN, "e": EYE,
                "C": "#2a7f8c", "b": "#7a4a2e", "w": "#c08a48", "S": "#e8f6f2"}, [
        "....kkkk....",
        "...kHHHHk...",
        "..kHHHHHHk..",
        "..khHsseHk..",
        "..khHsssskw.",
        "..kkhHHHkkSw",
        ".khCCCCCksSw",
        ".khCbbbbCkSw",
        ".khCCCCCCkw.",
        "..kCCCCCCk..",
        "..kCCkCCk...",
        "..kkk.kkk...",
    ]),
    # A knight in gold under a steel helm, a shield in front.
    "paladin": ({"k": K, "M": "#c9cfd6", "m": "#7d8794", "v": "#2a2232", "G": "#f1c46b",
                 "g": "#b9873a", "Y": "#fff0b8", "R": "#c4473f"}, [
        "....kkkk....",
        "...kMMMMk...",
        "..kMMMMMMk..",
        "..kmMvvvvk..",
        "..kmMMMMMk..",
        "...kkGGkkk..",
        "..kGGGGkYYk.",
        ".kgGGGGkYRYk",
        ".kgGYGGkYRYk",
        "..kGGGGkYYk.",
        "..kgGkgGkk..",
        "..kkk.kkk...",
    ]),
    # A seer in a tall lilac hat and robe, a glowing orb held up.
    "diviner": ({"k": K, "P": "#c4a5ff", "p": "#7b5fc0", "s": SKIN, "e": EYE,
                 "O": "#bff4ff", "o": "#62c8ef", "y": "#f6d36b"}, [
        ".....kk.....",
        "....kPPk....",
        "...kPPyPk...",
        ".kpPPPPPPPk.",
        "...kssek.kk.",
        "...ksssk.kOk",
        "..kpPPPPkoOk",
        ".kpPPPPPsko.",
        ".kpPPyPPPk..",
        ".kpPPPPPPPk.",
        ".kpPPPPPPPk.",
        "..kkkkkkkk..",
    ]),
    # A masked runner in charcoal with a green scarf trailing behind.
    "ninja": ({"k": K, "N": "#56607a", "n": "#3a4154", "e": "#f4fdff", "s": SKIN,
               "G": "#8fd6a4", "g": "#4f9a6c"}, [
        "....kkkk....",
        "...kNNNNk...",
        "..kNNNNNNk..",
        "..kNNeNeNk..",
        "kkkGGGGGGk..",
        "kggkGGGGk...",
        ".kkNNNNNNk..",
        "..knNNNNskk.",
        "..knNGGNNk..",
        "..kNNNNNNk..",
        "..knNkNNk...",
        "..kkk.kkk...",
    ]),
    # A jester in pink and white, two belled points on the cap.
    "simon": ({"k": K, "P": "#ff8fc8", "p": "#c4508e", "W": "#fff2e9", "w": "#d9c7d6",
               "s": SKIN, "e": EYE, "y": "#f6d36b"}, [
        ".kyk...kyk..",
        "..kPk.kWk...",
        "..kPPkWWk...",
        "..kPPPWWWk..",
        "..kssssek...",
        "..kWWWWWk...",
        "..kPPWWPPk..",
        ".kpPPWWPPsk.",
        ".kpPyWWyPk..",
        "..kPPWWPPk..",
        "..kpPkWWk...",
        "..kkk.kkk...",
    ]),
}


def hexrgba(h: str):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4)) + (255,)


def make(name: str) -> Image.Image:
    palette, rows = HEROES[name]
    assert len(rows) == 12 and all(len(r) == 12 for r in rows), name
    im = Image.new("RGBA", (12, 12), (0, 0, 0, 0))
    for y, row in enumerate(rows):
        for x, c in enumerate(row):
            if c != ".":
                im.putpixel((x, y), hexrgba(palette[c]))
    return im


def sheet(images, k=16) -> Image.Image:
    n = len(images)
    bg = Image.new("RGBA", (n * 13 * k, 12 * k), (52, 48, 74, 255))
    d = ImageDraw.Draw(bg)
    for i, im in enumerate(images):
        bg.alpha_composite(im.resize((12 * k, 12 * k), Image.NEAREST), (i * 13 * k, 0))
        for j in range(13):
            d.line([(i * 13 * k + j * k, 0), (i * 13 * k + j * k, 12 * k)], fill=(255, 255, 255, 30))
            d.line([(i * 13 * k, j * k), (i * 13 * k + 12 * k, j * k)], fill=(255, 255, 255, 30))
    return bg


def main(argv):
    zdir = Path(argv[argv.index("--zoom") + 1]) if "--zoom" in argv else None
    force = "--force" in argv
    made = []
    for name in HEROES:
        im = make(name)
        made.append(im)
        if name in HAND_EDITED and not force:
            print(f"hero-{name:8s} hand-edited, left alone (--force to rebuild)")
            continue
        im.save(OUT / f"hero-{name}.png", optimize=True)
        print(f"hero-{name:8s} 12 px")
    if zdir:
        sheet(made).save(zdir / "heroes-zoom.png")


if __name__ == "__main__":
    main(sys.argv[1:])
