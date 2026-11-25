"""Draw the Boss Rush bosses as hi-bit pixel art.

Each boss is a stack of layers. A layer is a shape (drawn 4x supersampled, then
snapped to whole pixels), a palette ramp, and a bevel: the distance from the
layer's own edge becomes a height, lit from the upper left, and the light picks a
step on the ramp through a 4x4 ordered dither. A layer's edge against the layers
under it gets the ramp's darkest step, and the whole sprite gets a one-pixel
outline. That one recipe is what makes the six bosses one family.

    python -m bossrush.tools.hibit_art            # writes webapp/public/art/bossrush/*.png
    python -m bossrush.tools.hibit_art --preview  # also writes a contact sheet
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "webapp" / "public" / "art" / "bossrush"
SS = 4                                             # supersampling for shape edges
BAYER = np.array([[0, 8, 2, 10], [12, 4, 14, 6], [3, 11, 1, 9], [15, 7, 13, 5]]) / 16 - 0.5
LIGHT = np.array([-0.55, -0.75, 0.6])
LIGHT = LIGHT / np.linalg.norm(LIGHT)


def hexrgb(h: str) -> tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# ---- shapes: each returns a boolean mask at N x N --------------------------------

class Canvas:
    """Shapes are given in frame coordinates; `fit` scales them about the frame's center."""
    fit = 1.0

    def __init__(self, n: int):
        self.n = n

    def _p(self, x, y):
        c = self.n / 2
        return (c + (x - c) * Canvas.fit) * SS, (c + (y - c) * Canvas.fit) * SS

    def _new(self):
        img = Image.new("L", (self.n * SS, self.n * SS), 0)
        return img, ImageDraw.Draw(img)

    def _done(self, img) -> np.ndarray:
        a = np.asarray(img, dtype=np.float32).reshape(self.n, SS, self.n, SS).mean(axis=(1, 3))
        return a >= 128

    def poly(self, pts) -> np.ndarray:
        img, d = self._new()
        d.polygon([self._p(x, y) for x, y in pts], fill=255)
        return self._done(img)

    def disc(self, cx, cy, r, ry=None) -> np.ndarray:
        ry = r if ry is None else ry
        img, d = self._new()
        x0, y0 = self._p(cx - r, cy - ry)
        x1, y1 = self._p(cx + r, cy + ry)
        d.ellipse([x0, y0, x1, y1], fill=255)
        return self._done(img)

    def rounded(self, x0, y0, x1, y1, rad) -> np.ndarray:
        img, d = self._new()
        a, b = self._p(x0, y0)
        c, e = self._p(x1, y1)
        d.rounded_rectangle([a, b, c, e], radius=rad * SS * Canvas.fit, fill=255)
        return self._done(img)


def rot(pts, cx, cy, ang):
    c, s = math.cos(ang), math.sin(ang)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def arc_band(cx, cy, r0, r1, a0, a1, steps=48, taper=True):
    """A crescent blade: between radius r0 and r1 from angle a0 to a1, pointed at both ends."""
    outer, inner = [], []
    for i in range(steps + 1):
        t = i / steps
        a = a0 + (a1 - a0) * t
        w = math.sin(math.pi * t) ** 0.7 if taper else 1
        ro, ri = r1, r1 - (r1 - r0) * w
        outer.append((cx + ro * math.cos(a), cy + ro * math.sin(a)))
        inner.append((cx + ri * math.cos(a), cy + ri * math.sin(a)))
    return outer + inner[::-1]


def spiral_tongue(cx, cy, a, r0, r1, turn, w0, steps=40):
    """A flame tongue: a curve from radius r0 to r1 while turning by `turn`, tapering to a point."""
    left, right = [], []
    for i in range(steps + 1):
        t = i / steps
        r, th = r0 + (r1 - r0) * t, a + turn * t
        x, y = cx + r * math.cos(th), cy + r * math.sin(th)
        # the curve's direction, for the perpendicular
        dr, dth = (r1 - r0), turn
        tx, ty = dr * math.cos(th) - r * dth * math.sin(th), dr * math.sin(th) + r * dth * math.cos(th)
        ln = math.hypot(tx, ty) or 1
        nx, ny = -ty / ln, tx / ln
        w = w0 * (1 - t) ** 0.9 + 0.4
        left.append((x + nx * w, y + ny * w))
        right.append((x - nx * w, y - ny * w))
    return left + right[::-1]


# ---- the lighting ----------------------------------------------------------------

def distance_in(mask: np.ndarray, limit: int) -> np.ndarray:
    """Pixels from the mask's edge (8-neighbour erosion), capped at limit."""
    d = np.zeros(mask.shape, np.float32)
    cur = mask.copy()
    for k in range(1, limit + 1):
        d[cur] = k
        p = np.pad(cur, 1)
        nxt = cur.copy()
        for dy in (-1, 0, 1):
            for dx in (-1, 0, 1):
                nxt &= p[1 + dy:1 + dy + cur.shape[0], 1 + dx:1 + dx + cur.shape[1]]
        cur = nxt
        if not cur.any():
            break
    return d


def blur(a: np.ndarray, times=2) -> np.ndarray:
    for _ in range(times):
        p = np.pad(a, 1, mode="edge")
        a = (p[:-2, 1:-1] + p[2:, 1:-1] + p[1:-1, :-2] + p[1:-1, 2:] + 2 * p[1:-1, 1:-1]) / 6
    return a


def shade(mask, bevel, concave=False, flat=0.0, dome=None):
    """0..1 lightness for each pixel of the mask."""
    d = distance_in(mask, bevel)
    h = np.sqrt(np.clip(d / bevel, 0, 1))
    if dome is not None:                       # (cx, cy, r): a rounded top over the whole layer
        cx, cy, r = dome
        yy, xx = np.mgrid[0:mask.shape[0], 0:mask.shape[1]]
        q = np.clip(1 - ((xx + 0.5 - cx) ** 2 + (yy + 0.5 - cy) ** 2) / r ** 2, 0, 1)
        h = h * 0.6 + np.sqrt(q) * 0.8
    h = blur(h * mask, 2)
    if concave:
        h = -h
    gy, gx = np.gradient(h)
    nx, ny, nz = -gx * 6, -gy * 6, np.ones_like(h)
    norm = np.sqrt(nx * nx + ny * ny + nz * nz)
    lam = (nx * LIGHT[0] + ny * LIGHT[1] + nz * LIGHT[2]) / norm
    flat_lam = LIGHT[2]
    v = 0.5 + (lam - flat_lam) * 1.6 + flat
    return np.clip(v, 0, 1)


# ---- a sprite --------------------------------------------------------------------

class Sprite:
    def __init__(self, n: int, outline: str):
        self.n = n
        self.cv = Canvas(n)
        self.rgb = np.zeros((n, n, 3), np.uint8)
        self.alpha = np.zeros((n, n), bool)
        self.outline = hexrgb(outline)

    def layer(self, mask, ramp, bevel=4, concave=False, flat=0.0, dome=None, edge=True,
              lo=0.0, hi=1.0, dither=0.85, value=None):
        """Paint `mask`, lit, in the steps of `ramp` (dark to light)."""
        cols = np.array([hexrgb(c) for c in ramp], np.uint8)
        v = shade(mask, bevel, concave, flat, dome) if value is None else value
        v = lo + (hi - lo) * v
        n = len(ramp)
        yy, xx = np.mgrid[0:self.n, 0:self.n]
        idx = np.clip(np.round(v * (n - 1) + BAYER[yy % 4, xx % 4] * dither), 0, n - 1).astype(int)
        # Where this layer meets an earlier one, its rim takes the darkest step: a selout line.
        if edge:
            p = np.pad(mask, 1)
            inner = p[:-2, 1:-1] & p[2:, 1:-1] & p[1:-1, :-2] & p[1:-1, 2:]
            rim = mask & ~inner & self.alpha
            idx[rim] = 0
        self.rgb[mask] = cols[idx[mask]]
        self.alpha |= mask

    def flat(self, mask, color):
        self.rgb[mask] = hexrgb(color)
        self.alpha |= mask

    def image(self) -> Image.Image:
        p = np.pad(self.alpha, 1)
        near = p[:-2, 1:-1] | p[2:, 1:-1] | p[1:-1, :-2] | p[1:-1, 2:]
        ring = near & ~self.alpha
        rgb = self.rgb.copy()
        rgb[ring] = self.outline
        a = (self.alpha | ring).astype(np.uint8) * 255
        return Image.fromarray(np.dstack([rgb, a]), "RGBA")


# ---- the bosses (frame 96: core at 48, about 80% footprint) ---------------------

N = 96
C = N / 2


def tidewarden() -> Image.Image:
    s = Sprite(N, "#2a0a14")
    cv = s.cv
    coral = ["#5a1a26", "#8e3140", "#c2524f", "#e2715f", "#f29179", "#fbb39b", "#ffd8c6"]
    deep = ["#4a1520", "#73283a", "#a04449", "#c45f58", "#de7d6c"]
    for k in range(4):                                       # the four small lobes behind
        a = math.pi / 4 + k * math.pi / 2
        x, y = C + 25 * math.cos(a), C + 25 * math.sin(a)
        s.layer(cv.disc(x, y, 12), deep, bevel=5, dome=(x, y, 12))
    s.layer(cv.disc(C, C, 24), coral, bevel=6, dome=(C, C, 24), lo=0.05, hi=0.85)
    for k in (3, 0, 2, 1):                                   # the four big lobes; the top one last
        a = k * math.pi / 2 - math.pi / 2
        x, y = C + 22 * math.cos(a), C + 22 * math.sin(a)
        s.layer(cv.disc(x, y, 16), coral, bevel=6, dome=(x, y - 2, 16))
    s.layer(cv.disc(C + 23, C - 23, 5.5), ["#1f4d46", "#2f6b62", "#4f9686", "#7cc4b0", "#b4ecd9"],
            bevel=3, dome=(C + 22, C - 24, 6))
    s.layer(cv.disc(C, C, 13), ["#4a0f22", "#6a1a30", "#8a2a40", "#a83e50"], bevel=3, concave=True)
    s.layer(cv.disc(C, C, 9.5), ["#12030a", "#24061a", "#3a0c24", "#561634"], bevel=4, concave=True, lo=0.0, hi=0.8)
    return s.image()


def breach() -> Image.Image:
    s = Sprite(N, "#14061f")
    cv = s.cv
    purple = ["#220936", "#3a1258", "#561d80", "#7329a8", "#9142cc", "#ad66e6"]
    lilac = ["#7d3fb8", "#b47ef0", "#dcb6ff", "#f6eaff"]
    a0, a1 = math.radians(150), math.radians(318)
    for turn in (0, math.pi):
        band = arc_band(C, C, 13, 34, a0, a1)
        half = cv.poly(rot(band, C, C, turn))
        for deg, tip in ((176, 45), (228, 44), (282, 46)):      # shards torn off the outer edge
            a = math.radians(deg)
            spike = [(C + 26 * math.cos(a - 0.22), C + 26 * math.sin(a - 0.22)),
                     (C + tip * math.cos(a + 0.05), C + tip * math.sin(a + 0.05)),
                     (C + 26 * math.cos(a + 0.26), C + 26 * math.sin(a + 0.26))]
            half |= cv.poly(rot(spike, C, C, turn))
        s.layer(half, purple, bevel=5, flat=-0.05)
        # The torn inner edge glows: the band nearest the seam.
        seam = arc_band(C, C, 13, 19, a0 + 0.15, a1 - 0.1, taper=True)
        s.layer(cv.poly(rot(seam, C, C, turn)) & half, lilac, bevel=2, edge=False, lo=0.3)
    s.flat(cv.disc(C, C, 8.5), "#14061f")
    ring = cv.disc(C, C, 7.5) & ~cv.disc(C, C, 4.5)
    s.layer(ring, ["#5c1a96", "#8a2fd0", "#b45cff", "#dca8ff"], bevel=2, edge=False, lo=0.2)
    s.flat(cv.disc(C, C, 4.5), "#1b0830")
    return s.image()


def pyre() -> Image.Image:
    s = Sprite(N, "#2a0806")
    cv = s.cv
    flame = ["#6a1408", "#a82a0c", "#d9470f", "#f26e18", "#ff9a2c", "#ffc24a", "#ffe58a"]
    for k in range(8):                                       # eight tongues swirling clockwise
        a = k * math.pi / 4
        s.layer(cv.poly(spiral_tongue(C, C, a, 8, 43, 1.25, 8.5)), flame, bevel=4, lo=0.05, hi=0.95)
    for k in range(8):                                       # embers between the tongues
        a = k * math.pi / 4 + 0.95
        x, y = C + 21 * math.cos(a), C + 21 * math.sin(a)
        s.layer(cv.disc(x, y, 3.4), ["#3a0c0c", "#6a1616", "#922626", "#b83a2a"], bevel=2)
    yy, xx = np.mgrid[0:N, 0:N]
    rr = np.sqrt((xx + 0.5 - C) ** 2 + (yy + 0.5 - C) ** 2)
    core = cv.disc(C, C, 15)
    s.layer(core, ["#ff9a2c", "#ffc24a", "#ffe58a", "#fff4c4", "#fffdf0"],
            value=np.clip(1.1 - rr / 15, 0, 1), edge=False, dither=1.0)
    return s.image()


def orrery() -> Image.Image:
    s = Sprite(N, "#0d1a17")
    cv = s.cv
    green = ["#173a32", "#245044", "#356b58", "#4c8a71", "#6aac8e", "#93d0b0", "#c6f0dc"]
    for k in range(3):
        a = k * 2 * math.pi / 3 - math.pi / 2
        s.layer(cv.poly(arc_band(C, C, 19, 43, a, a + 1.75)), green, bevel=6)
    s.layer(cv.disc(C, C, 15), ["#0f201b", "#18302a", "#22433a", "#2e574b", "#3d6d5e"], bevel=3)
    s.layer(cv.disc(C, C, 12) & ~cv.disc(C, C, 9), ["#3e7d68", "#5fa58a", "#8fd0b2", "#c4f0dc"],
            bevel=2, edge=False, lo=0.2)
    s.flat(cv.disc(C, C, 9), "#132621")
    star = [(C, C - 7), (C + 1.6, C - 1.6), (C + 7, C), (C + 1.6, C + 1.6), (C, C + 7),
            (C - 1.6, C + 1.6), (C - 7, C), (C - 1.6, C - 1.6)]
    s.layer(cv.poly(star), ["#8fd0b2", "#c4f0dc", "#eafff6"], bevel=2, edge=False, lo=0.4)
    return s.image()


def glassweaver() -> Image.Image:
    s = Sprite(N, "#0f1626")
    cv = s.cv
    steel = ["#1b2840", "#2a3d60", "#3d5784", "#5675a6", "#7896c4", "#a3bde0", "#d0e0f6"]
    gold = ["#5c3a06", "#8c5a0a", "#c2840e", "#e8a816", "#fbc73a", "#ffe27e", "#fff6cc"]
    for k in range(4):                                       # four petals of the frame
        a = k * math.pi / 2
        petal = [(C, C - 6), (C + 15, C - 22), (C + 2, C - 42), (C - 15, C - 22)]
        s.layer(cv.poly(rot(petal, C, C, a)), steel, bevel=4)
        notch = [(C, C - 16), (C + 6, C - 24), (C, C - 32), (C - 6, C - 24)]
        s.layer(cv.poly(rot(notch, C, C, a)), steel, bevel=3, concave=True, lo=0.0, hi=0.6)
    gem = [(C, C - 22), (C + 22, C), (C, C + 22), (C - 22, C)]
    s.layer(cv.poly(gem), gold, bevel=7)
    facet = [(C - 4, C - 14), (C + 4, C - 14), (C + 10, C - 6), (C - 2, C - 4)]
    s.layer(cv.poly(facet), gold, edge=False, value=np.full((N, N), 0.95), dither=0.6)
    return s.image()


def cantor() -> Image.Image:
    s = Sprite(N, "#150a19")
    cv = s.cv
    mauve = ["#2a1630", "#3f2249", "#573364", "#704880", "#8c639c", "#ab84b9", "#cfadd9"]
    lav = ["#8a5cb8", "#b98ae6", "#dcb9ff", "#f4e8ff"]
    hood = [(C, C - 42), (C + 40, C + 4), (C + 36, C + 22), (C + 24, C + 40), (C + 8, C + 36),
            (C, C + 42), (C - 8, C + 36), (C - 24, C + 40), (C - 36, C + 22), (C - 40, C + 4)]
    s.layer(cv.poly(hood), mauve, bevel=7)
    lower = [(C - 40, C + 4), (C + 40, C + 4), (C + 36, C + 22), (C + 24, C + 40), (C + 8, C + 36),
             (C, C + 42), (C - 8, C + 36), (C - 24, C + 40), (C - 36, C + 22)]
    s.layer(cv.poly(lower) & cv.poly(hood), mauve, bevel=5, lo=0.0, hi=0.55)
    rim = [(C, C - 22), (C + 20, C + 2), (C, C + 26), (C - 20, C + 2)]
    s.layer(cv.poly(rim), lav, bevel=3, lo=0.15)
    win = [(C, C - 15), (C + 13, C + 2), (C, C + 19), (C - 13, C + 2)]
    s.layer(cv.poly(win), ["#05020a", "#0e0616", "#1a0c26"], bevel=4, concave=True, hi=0.7)
    chev = [(C - 22, C + 14), (C, C + 34), (C + 22, C + 14), (C + 22, C + 19), (C, C + 39), (C - 22, C + 19)]
    s.layer(cv.poly(chev) & cv.poly(hood), lav, bevel=2, edge=False, lo=0.2)
    return s.image()


def orrery_tower() -> Image.Image:
    n = 44
    s = Sprite(n, "#0b1412")
    cv = s.cv
    s.layer(cv.rounded(6, 3, 38, 41, 6), ["#162a23", "#22392f", "#30503f", "#436a55", "#5c8770", "#86ac96"], bevel=4)
    s.layer(cv.rounded(11, 10, 33, 34, 3), ["#0e1414", "#161e1e", "#1f2929", "#2a3636"], bevel=3, concave=True)
    return s.image()


BOSSES = {
    "tidewarden": tidewarden, "breach": breach, "pyre": pyre,
    "orrery": orrery, "glassweaver": glassweaver, "cantor": cantor,
    "orrery-tower": orrery_tower,
}


FOOTPRINT = 0.80          # bossSprites.js: the visible boss fills 80% of its frame


def reach(img: Image.Image) -> float:
    """The farthest opaque pixel from the frame's center, as a fraction of the half-frame."""
    a = np.asarray(img)[:, :, 3] > 0
    yy, xx = np.nonzero(a)
    c = img.width / 2
    return float(np.sqrt((xx + 0.5 - c) ** 2 + (yy + 0.5 - c) ** 2).max() / c)


def fitted(name, make) -> Image.Image:
    """Draw, measure, and redraw at the scale that brings the farthest point to the footprint."""
    Canvas.fit = 1.0
    if name == "orrery-tower":
        return make()
    first = make()
    # A round-ish body's farthest point sits on a diagonal of its footprint square; allow a
    # little past the circle (sqrt 2 would let the corners of a square boss through whole).
    Canvas.fit = min(1.0, FOOTPRINT * 1.08 / reach(first))
    img = make()
    Canvas.fit = 1.0
    return img


def main(argv):
    imgs = {name: fitted(name, make) for name, make in BOSSES.items()}
    for name, img in imgs.items():
        print(f"{name:13s} {img.width}px  reach {reach(img):.2f} of the half-frame")
    for name, img in imgs.items():
        img.save(OUT / f"{name}.png", optimize=True)
    if "--preview" in argv:
        scale = 4
        w = sum(i.width * scale + 24 for i in imgs.values()) + 24
        sheet = Image.new("RGBA", (w, N * scale + 48), (44, 41, 64, 255))
        x = 24
        for img in imgs.values():
            sheet.alpha_composite(img.resize((img.width * scale, img.height * scale), Image.NEAREST), (x, 24))
            x += img.width * scale + 24
        dest = argv[argv.index("--preview") + 1] if len(argv) > argv.index("--preview") + 1 else "hibit-preview.png"
        sheet.save(dest)
        print("preview:", dest)


if __name__ == "__main__":
    main(sys.argv[1:])
