# Linux font regression fixture

`DejaVuSans-Bold.ttf` comes from Matplotlib's pinned `v3.10.7` distribution:
[font source](https://github.com/matplotlib/matplotlib/blob/v3.10.7/lib/matplotlib/mpl-data/fonts/ttf/DejaVuSans-Bold.ttf).
Its redistribution license is in `LICENSE_DEJAVU`.

SHA-256: `b184b89e3c1075f22f6b71575b6fc20d4972b3cfd3b23322ca6fd596dcaef167`.

The font is loaded only by browser tests, never shipped in the website. The
Orbit numeric layout check runs with both the machine's normal font and these
wider Linux metrics. Pages runs #827/#828 passed local Windows checks before
failing on Ubuntu; increasing a clearance threshold alone did not close that gap.
`font-profiles.mjs` verifies the loaded glyph metrics so a missing font cannot
silently fall back and turn this test green.
