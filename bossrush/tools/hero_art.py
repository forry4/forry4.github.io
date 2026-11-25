"""Draw the Boss Rush heroes: one 12 px chunky sprite per class, facing right.

Each hero is a text grid below (one character per pixel, '.' clear) over a palette,
in the RotMG / Darza manner the bosses use: a few colors and a near-black outline.
Every hero is legless, the body running down to the ground (the owner's call,
2026-11-25); the ranger, paladin, diviner and ninja are the owner's picks from
generated sheets of variations, and simon is drawn by hand.
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
    # A ranger in moss green under a wide hat with a red feather, a bow held out
    # in front (R4 of the 2026-11-25 sheets; rim-lit).
    "ranger": ({"k": "#0a130c", "1": "#1b3321", "2": "#3a7a4a", "3": "#55a66a", "a": "#c4473f", "e": "#1c1426", "s": "#f2c39b", "t": "#eaf2ee", "w": "#9a6a3c"}, [
        "........k...",
        ".......kak..",
        "....kkkaak..",
        "...k3333ak..",
        "..kk3333kk..",
        ".k33333333k.",
        "..kksssekwk.",
        "...kssssktwk",
        "...k2221ktwk",
        "..k122223twk",
        "...k2221kwk.",
        "....kkkk.k..",
    ]),
    # A knight in silver under an orange-plumed helm, an orange tabard and a
    # shield with a gold cross (P2).
    "paladin": ({"k": "#202026", "1": "#aea8c8", "2": "#e8e6f0", "M": "#c9cfd6", "a": "#e07a2a", "m": "#7d8794", "v": "#221a2c", "y": "#f1c75a"}, [
        ".....kk.....",
        "....kaak....",
        "...kaakk....",
        "...kMMMMk...",
        "..kMMMMMMk..",
        "..kMMvvvMk..",
        "..kmMMMMmk..",
        "...kmmmmkk..",
        "...k1aa2kak.",
        "...k1ay2ayak",
        "...k1aa2kak.",
        "....kkkk.k..",
    ]),
    # A seer in indigo under a tall pointed hat, a staff topped with a
    # glowing orb (D2; the robe falls in folds to the ground).
    "diviner": ({"k": "#151327", "1": "#383267", "2": "#5a4fb0", "3": "#8b84c3", "G": "#f2fdff", "e": "#1c1426", "g": "#ffe08a", "s": "#f2c39b", "w": "#9a6a3c"}, [
        "......k.....",
        ".....k3k....",
        "....k332k.k.",
        "..kk33322kGk",
        ".k33333332gk",
        "..kksssekkwk",
        "...ksssskkwk",
        "...k1221kkwk",
        "...k1221kkwk",
        "..k122122kwk",
        ".k12212212wk",
        "..kkkkkkkkk.",
    ]),
    # A charcoal ninja in a white headband whose tails stream back with his
    # scarf, a sword held up a pixel out from his face (C1).
    "ninja": ({"k": "#0a060e", "1": "#21232b", "2": "#4c5266", "3": "#6c748d", "A": "#eff0f6", "W": "#f6f2ff", "a": "#e4e6f1", "b": "#6b4228", "e": "#1c1426", "m": "#7d8794", "s": "#f2c39b"}, [
        "....kkkk....",
        "...k2222k...",
        "..k222222kk.",
        ".kaaaaaaakWk",
        ".kak22ssekWk",
        ".kak22222kWk",
        "..kkk222kkWk",
        ".kAA1322kmmk",
        "kAAkaaaaskk.",
        ".kkk1223bk..",
        "...k1222k...",
        "....kkkk....",
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
