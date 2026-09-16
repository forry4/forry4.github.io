# Deploy & CI reliability log

Dated postmortems for **red runs** — the deploy gates, the scheduled jobs, and the
harness itself. `CLAUDE.md` keeps the durable rules that come out of these; this file
keeps the measurements and the reasoning, so a conclusion can be re-checked rather
than re-argued.

> Status lines and commit hashes are historical snapshots — trust git and the live
> code over them.

---

## 2026-09-14 — reproduce the runner's font before the next push

The latest failed deployment was [Pages #828](https://github.com/forry4/forry4.github.io/actions/runs/34797488411),
at `baebb007`: Orbit's 320px, 18-Agent check reported two spills and 0.953125px
clearance. The publish job never ran. `259c2562` fixed the layout; Pages
#829–#832 and the latest Render deploy (#432) subsequently succeeded. Both live
`version.json` and backend `/health` reported `9dbc9517` during this investigation.

The remaining prevention gap was local reproduction. A clearance assertion still
measures only the installed font. `screens.mjs` now measures the same widest
position again with a pinned, test-only DejaVu Sans Bold font on every platform.
The helper checks the font's actual digit width before applying it, so a missing
fixture cannot silently turn into the same Windows fallback that missed the bug.
The native-font check stays in place; the font adds no production bytes or runtime
dependency. Each block also writes its measurements, browser version, deal seed,
and full exception to JSON; Pages uploads those reports on failure. The Linux
numeric check saves its HTML and screenshot if it fails.

Validation: smoke and the full screen suite passed on Windows. Replaying
`baebb007`'s stylesheet against the saved 320px position with the pinned font
reproduced the CI result exactly: **2 spills, 0.953125px clearance**. The current
stylesheet produced **0 spills, 2.90625px clearance**. This proves the new check
detects the historical failure without needing an Ubuntu runner.

The newer [keepalive #850](https://github.com/forry4/forry4.github.io/actions/runs/34896541406)
failure is separate: its watchdog reported a 16:54 UTC backend restart during
play hours with no matching deployment. The expected Worker URL returned 404
(Cloudflare error 1042) with a browser user agent. Neither Wrangler nor the
available browser was signed in to Cloudflare, so the Worker's deployed state
and cron activity could not be verified. A 404 alone does not establish that a
cron is absent. This remains an access-dependent follow-up, not a resolved outage.

## 2026-09-13/14 — every Pages failure is one gate, and the daily keepalive alarm was real

### The census

26 days, 600 runs, 34 failures:

| Workflow | Runs | Failed | What failed |
|---|---|---|---|
| Deploy to GitHub Pages | 92 | 8 (8.7%) | **the screens gate — 8 of 8** |
| Keep backend warm | 315 | 14 (4.4%) | `warm-window-watchdog`, twice a day since 09-07 |
| Python CI | 111 | 6 (5.4%) | one iterating session on 09-09, 21:03→23:32 |
| Deploy Backend to Render | 37 | 4 (10.8%) | 2× test gate blocking, 2× `/health` verify |
| Rust CI (orbit-core) | 41 | 0 | — |

**Nothing but the screens gate has ever failed a Pages deploy.** That is the number
worth carrying: the gate is the single point of failure for shipping the frontend, so
its false-failure rate *is* the deploy's failure rate.

The two Render failure modes were both the system working — the test gate refusing a
bad backend deploy, and the `/health` verify catching a build that never came up.

### Root cause: assertions that are true here and false on the runner

All 8 share one signature. Two sub-classes:

- **Sampling** — random deals. Already fixed by `core.rooms.deal_rng` / `bot_seed`;
  CLAUDE.md records it as 11 of 15 earlier failures.
- **Environment — fonts.** Not previously covered, and the cause of all three failures
  on 09-13/14.

**The font gap is much larger than "a hair", and that assumption is what cost two
failed deploys.** Measured on the played-Agent cell at 320px:

| | dev box (Windows) | CI (Ubuntu) |
|---|---|---|
| the same five glyphs | 28.4px | **36.1px — 27% wider** |
| clearance from the cell | 1.69px | **−2px (spilling)** |

3.85px **per side**. Any "it fits" assertion with less margin than that is a coin
flip that lands green locally every time.

A first fix trimmed ~6px of gaps against a *guessed* difference, shipped, and failed
again at 0.95px. The second was sized from a model validated against both platforms
(DejaVu Sans Bold: digits 0.696em, `×` 0.838em — predicted the measured width to
**0.04px**) and prefers levers that are identical everywhere: row geometry, and
dropping the `×` glyph below 360px. 0.95px → ~5.8px.

**The rule:** measure the platform spread before budgeting against it, and prefer a
font-independent lever to a font-denominated one.

### The gate could not report why it failed

The Actions logs API needs authentication even on a public repo, so a screens failure
was readable only by someone who could sign in and unzip a log. Annotations *are*
public. Every failing check now emits one (`runLane`, one site — all 28 per-block
`check` helpers funnel through that buffer). That single change turned the second fix
from a blind guess into a measurement.

### Assert the margin, not the absence of overflow

An overflow check with a 1px tolerance rates *"fits by 0.69px"* and *"fits"*
identically — and that is exactly the distinction that failed the deploy. The three
Orbit fit assertions now report their narrowest **clearance** and require ≥2px.
Verified non-vacuous: the check fails on the old CSS at exactly 1.6875px.

### A wait on one card, measured six

`all 90 card sentences fit` failed roughly 1 run in 10, always naming cards
201/301/401/501 — every one the **first id of its own batch**. The batch wait returned
as soon as React committed the first face, so the other five were measured mid-render:
they report empty computed styles (`NaN`) or a pre-fit geometry.

Two lessons, and the second is the bigger one:

- Wait for the whole batch, not its first member.
- **`NaN` passes every `>` comparison.** The new title checks were `m.nameH > x` style,
  so mid-render rows sailed through all three assertions while proving nothing; the
  measured count drifting 90 → 89 was the only outward sign. A geometry check must
  assert its **roster** before its geometry.

### The keepalive watchdog: right alarm, wrong evidence

`warm-window-watchdog` failed twice a day from 09-07, saying the 11:00–13:59 UTC warm
ramp had fired zero times. The histogram confirms it — **UTC hours 11, 12 and 13 have
fired 0 times in 14 days**, and note the dead band *moved* (it was 13–14 in the
previous incident), so spreading the ramp across five hours did not help. The earliest
reliably-firing hours are 15–17.

The first read was that this had become a false alarm, since `keepalive-worker/` fires
every 5 minutes from 13:00 UTC and covers 7am PDT on its own. **That read was wrong.**
Measured 2026-09-14 03:59 UTC — *inside* the 13:00–06:59 warm window — the backend was
cold and a probe woke it. Both pingers had missed it: GitHub had dropped the 03:13 and
03:47 firings, and the Worker answered 404 at the URL its own `wrangler.jsonc`
documents. A cron-only Worker needs no route, so the 404 is suggestive rather than
proof — **but the cold box is not**. Open item: confirm the Worker is deployed.

What *was* wrong was the evidence. "A GitHub cron did not fire" stopped implying "the
backend was cold" the moment a second independent pinger existed. The watchdog now
measures the property — `/health`'s `started_at` answers *"was it already up when the
play window opened?"* whichever pinger did the work — with a carve-out for deploys
(which also restart the process; without it, 09-13's 16:00 boot, deploy `d8ff7259` at
15:57, would have read as an outage). A stated blind spot: `started_at` is the current
boot only, so the 00:00–07:00 UTC stretch is not covered, because a watchdog can only
run when the scheduler runs it — and that is the scheduler it is auditing.

**The transferable rule: an alarm must measure the property, not a mechanism that
used to imply it.** One that cries daily is one nobody reads, and it shares a
dashboard with the gates that matter.

### A note on measuring flakiness

Three screens blocks appeared to go flaky during this work. They were not: running
several harnesses at once (a background loop plus foreground runs, each spawning a
browser, a backend and a vite preview) starves the frame-timing blocks that lane A
exists to protect. On a quiet box the same build passed 4/4. **Do not attribute a
timing failure until the machine is idle** — and kill stale `vite preview` / `uvicorn`
listeners before re-running, or the next run measures the previous one's leftovers.
