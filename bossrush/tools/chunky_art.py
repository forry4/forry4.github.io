"""Rebuild the Boss Rush boss sprites chunky, in the RotMG / Darza manner.

The source is the 80 px art in bossrush/art/sprites80/ (the sprites the owner
liked). Each one is rebuilt on a 32 px frame: the old outline is stripped, every
new pixel takes the most common color of the source pixels under it (a small
bright detail wins if it fills a third of the pixel), lone stray pixels are
merged into their neighbours, the hand fixes in FIXES are applied, and a black
outline one pixel thick goes round the whole sprite. The frame keeps the 80 px
art's proportions, so a boss still fills the footprint its hitbox expects.

    python bossrush/tools/chunky_art.py            # writes webapp/public/art/bossrush/*.png
    python bossrush/tools/chunky_art.py --zoom DIR # also writes a gridded 16x view of each
"""
from __future__ import annotations

import sys
from collections import Counter
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "bossrush" / "art" / "sprites80"
OUT = ROOT / "webapp" / "public" / "art" / "bossrush"

# name: (frame in px, colors kept)
SPRITES = {
    "tidewarden": (32, 12), "breach": (32, 12), "pyre": (32, 14), "orrery": (32, 12),
    "glassweaver": (32, 14), "cantor": (32, 12), "orrery-tower": (15, 8),
}

# Hand fixes after the rebuild: (x, y) -> a color from the sprite ("#rrggbb"), or None to clear.
FIXES: dict[str, dict[tuple[int, int], str | None]] = {
    # The Schism's core: one lilac eye where the shrink left a stray blue pixel.
    "breach": {(14, 16): "#ea91f8"},
    # The Tidewarden's sea-green sliver between its upper-right lobes, lost in the shrink.
    "tidewarden": {(20, 9): "#87a594", (21, 10): "#87a594", (22, 11): "#87a594", (23, 12): "#87a594"},
}


def strip_outline(a: np.ndarray) -> np.ndarray:
    a = a.copy()
    for _ in range(2):
        op = a[:, :, 3] > 0
        p = np.pad(op, 1)
        edge = op & ~(p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:])
        lum = a[:, :, :3].astype(int).sum(2) / 3
        a[edge & (lum < 70), 3] = 0
    return a


def rebuild(img: Image.Image, n: int, colors: int) -> np.ndarray:
    """The sprite on an n-pixel frame, its body inside a one-pixel border for the outline."""
    a = strip_outline(np.asarray(img.convert("RGBA")))
    op = a[:, :, 3] > 0
    pal = Image.fromarray(a[:, :, :3]).quantize(colors=colors, method=Image.Quantize.MEDIANCUT)
    idx = np.asarray(pal).copy()
    cols = np.array(pal.getpalette()[:colors * 3]).reshape(-1, 3)
    # Near-identical shades are one color: fold each into the more common of the pair.
    counts = np.bincount(idx[op], minlength=colors)
    for k in np.argsort(counts):
        near = [q for q in range(colors) if q != k and counts[q] >= counts[k]
                and np.abs(cols[q] - cols[k]).sum() <= 24]
        if near:
            idx[idx == k] = near[0]
            counts[near[0]] += counts[k]
            counts[k] = 0
    lum = cols.sum(1)
    w, m = a.shape[0], n - 2
    out = np.zeros((n, n, 4), np.uint8)
    for j in range(m):
        for i in range(m):
            y0, y1 = int(j * w / m), int((j + 1) * w / m)
            x0, x1 = int(i * w / m), int((i + 1) * w / m)
            blk = op[y0:y1, x0:x1]
            if blk.mean() < 0.45:
                continue
            cnt = Counter(idx[y0:y1, x0:x1][blk].tolist())
            c = cnt.most_common(1)[0][0]
            for k, v in cnt.items():                  # a small bright detail survives
                if lum[k] > lum[c] + 150 and v >= blk.size * 0.3:
                    c = k
            out[j + 1, i + 1, :3] = cols[c]
            out[j + 1, i + 1, 3] = 255
    return out


def despeckle(s: np.ndarray) -> np.ndarray:
    """A pixel unlike all four neighbours takes their most common color (not a highlight)."""
    s = s.copy()
    n = s.shape[0]
    for y in range(1, n - 1):
        for x in range(1, n - 1):
            if s[y, x, 3] == 0:
                continue
            me = tuple(int(v) for v in s[y, x, :3])
            nb = [tuple(int(v) for v in s[y + dy, x + dx, :3]) for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1))
                  if s[y + dy, x + dx, 3]]
            if len(nb) < 3 or me in nb:
                continue
            brightest = max(sum(c) for c in nb)
            if sum(me) > brightest + 120:            # a lone highlight is a choice, keep it
                continue
            s[y, x, :3] = Counter(nb).most_common(1)[0][0]
    return s


def outline(s: np.ndarray) -> np.ndarray:
    s = s.copy()
    op = s[:, :, 3] > 0
    p = np.pad(op, 1)
    ring = ~op & (p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:])
    s[ring] = (10, 6, 14, 255)
    return s


def hexrgb(h: str):
    h = h.lstrip("#")
    return [int(h[i:i + 2], 16) for i in (0, 2, 4)]


def make(name: str) -> np.ndarray:
    n, colors = SPRITES[name]
    s = despeckle(rebuild(Image.open(SRC / f"{name}.png"), n, colors))
    for (x, y), c in FIXES.get(name, {}).items():
        s[y, x] = (0, 0, 0, 0) if c is None else hexrgb(c) + [255]
    return outline(s)


def zoom(s: np.ndarray, k=16) -> Image.Image:
    n = s.shape[0]
    bg = Image.new("RGBA", (n * k, n * k), (52, 48, 74, 255))
    bg.alpha_composite(Image.fromarray(s).resize((n * k, n * k), Image.NEAREST))
    d = ImageDraw.Draw(bg)
    for i in range(n + 1):
        d.line([(i * k, 0), (i * k, n * k)], fill=(255, 255, 255, 40))
        d.line([(0, i * k), (n * k, i * k)], fill=(255, 255, 255, 40))
    for i in range(0, n, 4):
        d.text((i * k + 2, 2), str(i), fill=(255, 255, 120, 255))
        d.text((2, i * k + 2), str(i), fill=(255, 255, 120, 255))
    return bg


def main(argv):
    zdir = Path(argv[argv.index("--zoom") + 1]) if "--zoom" in argv else None
    for name in SPRITES:
        s = make(name)
        Image.fromarray(s).save(OUT / f"{name}.png", optimize=True)
        if zdir:
            zoom(s).save(zdir / f"{name}-zoom.png")
        print(f"{name:13s} {s.shape[0]} px, {len({tuple(c) for c in s[s[:, :, 3] > 0][:, :3]})} colors")


if __name__ == "__main__":
    main(sys.argv[1:])
