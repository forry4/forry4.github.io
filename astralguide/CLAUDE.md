# Astral Ascent Guide — Claude Context

A **frontend-only** reference page for the game Astral Ascent, in the home menu's Extras
(`/astral`). No backend, no auth: it fetches one static JSON built from the community wiki
and does everything client-side. Like BGG Filter in shape.

| File | What it is |
|---|---|
| `AstralGuide.jsx` | the page; props are just `{ onExit }` |
| `AstralGuide.css` | `?inline`-imported stylesheet, `.aag`-prefixed |
| `derive.js` | **the logic, kept pure so `node --test` can reach it**: the effect vocabulary, the text linker, the synergy index, search, and the charts' maths |
| `editorial.js` | **hand-written judgment**: tier lists, starting auras, build outlines, the voko→echo pairing, the wiki's tips condensed |
| `ingame.js` | **numbers read off the game** that replace the wiki's where it is out of date (spells so far); `derive.applyGameSpells` merges them before anything is computed |
| `fieldnotes.js` | **named effects the wiki never explains** (Kamikaze Wisp, Fire Plasma, Ice Dagger…: ~50), each with its parent effect and, where known, what it makes plus the source of that fact |
| `runs.js` | **23 winning runs transcribed from end-of-run screens** (Destiny 54–100), the in-game text where it differs from the wiki (`GAME_TEXT`), and names the wiki lacks (`NOT_ON_WIKI`) |
| `tools/harvest.py` | fetches every wiki page's wikitext → `tools/cache/pages.json` (gitignored) |
| `tools/make_data.py` | `pages.json` → `webapp/public/data/astral-guide.json` (the shipped payload) |

## The data is GENERATED — do not hand-edit the JSON

Regenerate with `python -I astralguide/tools/harvest.py && python -I astralguide/tools/make_data.py`.
**The wiki's HTML and `?action=raw` answer a script with a "Blocked" page; its MediaWiki API
(`api.php`) does not**, so the harvester only uses the API. Every parser in `make_data.py`
asserts a FLOOR on what it found (`floor()`), because the wiki is hand-edited and a
reformatted table parses to nothing rather than to an error — a section that comes back
empty fails the build instead of shipping an empty tab. The wiki's own typos are fixed at
that boundary (`SPELL_FIX`, `MOJIBAKE`), never in the JSON.

Where each section comes from: Auras / Gambits / Spells / Echo / Zodiac Summon / Prowess /
Void Catalyst / Telluric Telescope / Cursed Telescope / Elemental Effect / Path of
Destinies / Player Stats pages, the 90 imprint pages, and the 13 Zodiac + 6 Star Guardian
pages. The electric gambit icons are numbered rather than named; `GAMBIT_FAMILY` pairs them
using the Elemental Effect page.

## Editorial vs derived — keep them apart

**The winning runs are evidence, and everything counted from them is counted, not typed.**
`runs.js` holds 23 end screens the site's owner shared (2026-10-20). `derive.runUsage`
counts auras, imprints, summons, engines and heroes across them; the tier lists' ★ badges,
the Runs tab's bars and the drawers' "In N winning runs" all read that one count. The
aura/imprint/summon tiers are WEIGHTED by it (an S-tier aura must be in ≥3 wins — the unit
test enforces it), and `RUN_FINDINGS`' numbers are asserted against the counts, so a new run
that moves a number fails the test until the prose is updated. Things the runs taught that
the wiki gets wrong: **each spell level is +20% damage** (the screen prints X as 200%; the
wiki's Spell Mechanics page says 10%), several auras' numbers (`GAME_TEXT`), the game's
capitalization of two aura names (`AURA_FIX` in make_data.py), and "Topaz Gladius -
Downfall". Arven (DLC, May 2026) has no spells on the wiki at all. A summon is recorded only
where its portrait is unmistakable (Capricorn, Leo); echo icons are unreadable, so the echo
tiers are not weighted by the runs.

Everything on the page is derived from the payload EXCEPT `editorial.js`. **No community
tier list for Astral Ascent exists to cite** (searched 2026-10-19), so the tier lists and
picks are ours, and the page says so next to each one with its criteria. Spell tiers are
the exception: computed (damage per mana, quartiles within each mana cost).
`webapp/test/unit/astralguide.test.mjs` resolves **every name in `editorial.js` against the
payload**, and requires every echo to be ranked exactly once and every `-voko` imprint to
be paired with an echo — so a wiki rename fails the test rather than rendering a dead link.

## The synergy index is heuristic, and says so

`classifyLine` reads the wiki's phrasing: in "On X hit, creates Y" the trigger clause USES X
and the effect clause MAKES Y; "Increases X damage", "per X" and "for each X" USE X;
"Transforms X into Y" uses X. That is what fills "Makes it / Pays it off" and each drawer's
"Works well with". The page labels those lists as automatically linked.
- **`Target` and `Shield` only count Capitalized**, and Target only singular: "Targets and
  falls on one enemy" is the verb. Poison skips "poison affinity".
- **A spell named after "like" is a comparison, not a cast**: the clone imprints make a clone
  "like pisces clones".
- Spell names under five letters ("Sol", "Fax", "Luna") are never auto-linked; they are
  ordinary words too often.

## Routing

`/astral/<tab>` is segment 2 (router.js upper-cases it; the page lower-cases it back). The
open entry is the **hash** (`#aura:flame-blessing`): opening one pushes a history entry, so
browser Back steps back through the drawer, and a hashed link opens that entry on a cold
load. The shell's popstate handler sees the same `astral` route and no-ops.

## Gates

`npm run test:unit` (derive + editorial), the `astralGuide` block in `webapp/test/screens.mjs`
(every tab deep-links and renders at 1280 and 390px with no sideways scroll, filters match
the payload's counts, search → drawer → Back, a hashed cold load, the charts' verdict, the
phone spells table), plus `formControlZoom` (`/astral/auras`, `/astral/charts`) and
`offlineRead` (the guide is in the offline hub's reading pack). `affected.mjs` maps this
directory and `astral-guide.json` to those blocks.

## Field notes — what the wiki names but never explains

The wiki's aura and imprint text names ~50 things it never defines ("summons 1 Kamikaze
Wisp"), so the synergy index could not see through them: Careless Wisper's Kamikaze Wisps
make Thunder Strikes, and nothing on the wiki says so. `fieldnotes.js` lists each one with a
`parent` (anything that makes a Kamikaze Wisp makes Wisps) and, once known, `known.makes`,
which `classifyLine` credits exactly like the wiki's own wording. Variants come FIRST in the
linker's alternation, so they link as themselves rather than as the keyword whose pattern
would also take them. **The game is only on Switch here, so its files cannot be read**:
facts come from play and the community, and every `known` entry carries its `source`, which
the page prints. The Glossary's checklist shows which are still blank. The unit test fails
an entry the wiki's text never mentions (a typo in `re`), and the linker's trailing edge
allows a hyphen because the wiki glues words on ("fire idol-Unique").

## In-game numbers beat the wiki's

**Every spell is shown at LEVEL 1**, the base once every Destiny Fragment is unlocked
(`GAME_BASE_LEVEL`). Damage is (1 + 20% x level) of the level-0 number, and **the wiki's
spell table IS level 0**: four unchanged spells read off the game match the wiki's x1.2 at
level 1 and x1.4 at level 2 to the point (`atLevel`, `WIKI_LEVEL`; the unit test holds
those four to it). So `applyGameSpells` lifts every wiki number to level 1, and each
reading in `ingame.js` from the `level` it was read at. A reading is only needed where a
patch changed the spell (mana, damage or hits); the rest are the wiki's x1.2 and say
"not checked in game". The first batch of readings (2026-10-21 morning) turned out to be
level 2 — the three read again came back x1.18 — so the four not read again are marked
`inferred` and the panel asks for a re-read. Readings are laid over the payload in the
page, never in the JSON, which stays the wiki's raw level-0 numbers; the spell panel shows
those beside the game's. A spell with no recorded hero stays out of the tier list.
