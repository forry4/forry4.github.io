# Shared frontend kits (`shared/`) — notes

Cross-game frontend kits. **Dependency direction is one-way: `games/* → shared/`, never back.**

- **`theme.js` — `baseCss`** is the single source of truth for the design system (font `@import`/
  `@font-face` first, `:root` tokens, `.btn`/`.input`). Spender + Books + Duel + WW import it; CoC renders
  it too (CoC carries a copy since it mounts bare).
  **`font-display` IS `swap` AND MUST NOT GO BACK TO `optional`.** `optional` gives a face a
  ~100ms block period and then, if it has not arrived, uses the fallback **for the lifetime of
  the page** — the font still lands in the cache and `document.fonts.check()` starts answering
  true, but nothing on screen changes. So Spender.jsx's `waitFonts` gate would wait for Cinzel,
  see it resolve, and then the whole site painted in Georgia; only the SECOND visit looked
  right. Caught in the shot harness, where every browser context is a cold cache: the wordmark
  came out in lowercase Georgia with `cinzel:true` in the same probe. `swap` is safe here
  precisely because of the `size-adjust` metric-matched fallbacks — the worst case is a repaint
  at the same widths, not a reflow.
- **`lobbyHistory.js`** owns authenticated history refresh for every game. Failed,
  malformed, superseded, or unverified empty replies must preserve the last successful
  list and cache. Legacy endpoints return `{games: []}` for expired sessions: verify
  `/auth/session` before accepting that empty result. Only a confirmed dead token asks
  the shell for sign-in, keeping the route for recovery without reloading. A same-account
  login in another tab supplies the fresh token; never borrow another account's token.
  `screens.mjs`'s `historyRecovery` block covers these paths and every lobby's wiring.
- **`lobby.jsx`** — shared lobby chrome (`LobbyHeader`/`LobbySectionHd`/`LobbyEmpty`/`LobbyLoading`/
  `TurnBadge`, cache helpers) + `GameMenu` (the in-game ☰ dropdown: Return / View rules / Abandon; falsy
  items filtered; Esc/click-outside close) + `CreateModal`/`LobbyCreateRow` (the unified "New Game" modal
  + create/join-by-code/refresh/**rules** row).
  **THE HOW-TO-PLAY MODAL IS SHARED TOO** (`RulesModal` + `RulesSection`/`RulesFacts`/`RulesDefs`/
  `RulesTip` + `rulesModalCss`, appended AFTER `lobbyCreateRowCss`); each game keeps only its WORDS,
  in a `games/<game>/rules.jsx` that rides its own lazy chunk. The panel is capped to the viewport
  and **`.rl-body` is the only scroller** — `min-height:0` on it is load-bearing (a flex item won't
  shrink below its content, so without it the panel grows past `max-height`, nothing scrolls and
  "Got it" sits below the fold, which is what two of the five per-game copies did). Every lobby
  passes `onRules`; the button is opt-in only so the component stays usable without one, and
  `screens.mjs` drives all six lobbies precisely because a game that forgets it still renders a
  perfectly fine lobby with no way in.
  **`LobbyCreateRow` has ONE optional `extra` node**, rendered after Rules, for a control a
  single game keeps there — today Dissonance's paper scorecard. A node rather than another
  `onX`/`xLabel` pair, so the kit never learns what any one game puts in it; style its button
  `.lby-extra`, which the sheet gives the Rules look. **Deliberately NOT `.lby-rules`**: the
  render gate counts Rules buttons by that class, so a second button wearing it reads there as a
  duplicate. `RulesModal` also takes an `icon` (default `RULES_GLYPH`, a line-art book on the
  site's 24x24 drawing grid — **not an emoji**, for the reason the home menu's side-feature row
  was rebuilt: an emoji arrives as a different typeface, weight and often COLOUR SCHEME on every
  OS) — the panel is reused for things that are not a rulebook.
  **On phones (≤600px) `.lby-create-row` IS A TWO-ROW GRID that FITS** — Create + ↻ + Rules on
  row 1, the code field + Join on row 2, with the tertiary pair collapsed to their glyphs (their
  `aria-label` keeps them named). It used to scroll sideways instead, which fitted nothing: at
  390px the row is ~650px of controls in a 370px box, so Rules ended 280px past the right edge
  and Dissonance's Scorecard was entirely off-screen behind it, with nothing on a
  vertically-scrolling page to say either was there. **Its column gaps are MARGINS, not `gap`** —
  the grid keeps a fourth track for the optional sixth control, and a `column-gap` allocates the
  gutter before that track even when it is empty. Token-driven via a per-game `--lby-accent` with
  **hard fallbacks so it renders in CoC's bare mount** — append its CSS AFTER the `.coc *` reset.
  **THE WHOLE LOBBY LAYOUT IS HERE as of 2026-08-05** — `.lby-cols` (the column grid + the single
  responsive ladder: 3 columns ≥1041px, 2 columns 761–1040 with History spanning below, 1 column +
  tabs ≤760), `.lby-list` (the card list, and the only thing the desktop internal scroll can hang
  off — cap via `--lby-list-max`), `.lby-card-hist` (a history title WRAPS instead of truncating),
  and `LobbyTabs` (the phone segmented bar; `key` must match the column's `lby-col-<key>` class,
  because show/hide is pure CSS off `tab-<key>` on the grid, so a hidden column stays mounted and
  keeps its scroll position and History paging). Spender was converted onto all of it in the same
  pass — it had been the ORIGINAL this kit was extracted from and the only game never moved onto it.
  **A game's own sheet must not set `display`/`grid-template-columns`/`gap` on its lobby-grid class**:
  four of the five are concatenated AFTER this one, so a base rule out-orders these MEDIA rules and
  pins the lobby to three columns on a phone (CoC is the exception — its sheet comes first).
  Where Wolf? has no History (a one-night party game — nothing to review) and uses the
  **`.lby-cols-2` modifier** on the shared grid rather than a private grid of its own, so it
  inherits the ladder, the internal scroll and the phone tab bar. Its lists and section headers
  are capped to 470px: uncapped, two tracks of a 1500px page draw 714px rows with a name at one
  end and a button at the other, and pairing the cards two-up instead put FOUR cards in one strip
  whose section gutter equalled its card gutter, so two different lists read as one.
  `shared/tests/test_lobby_kit.py` carries the no-History exemption as a self-policing LIST — a
  game on it that starts rendering a History column fails as STALE.
  Also **`useProgressiveList` + `HISTORY_PAGE`/`HISTORY_MAX`** — the lobby History list's 10-at-a-time
  reveal, wired identically into all four games. **`HISTORY_MAX` must equal `core.rooms.HISTORY_LIMIT`**
  (the SQL row cap); `core/tests/test_history_limit.py` reads this file as TEXT to hold the two
  together, since `core/` may not import a feature. It pages off a SENTINEL + IntersectionObserver
  rather than a scroll handler, because the four lobbies scroll different elements — see the root
  `CLAUDE.md`.
  **And `useLastDifficulty` — the create modal's AI-difficulty row defaults to the tier the player
  LAST PLAYED**, per game and per identity (localStorage `lastdiff.<ns>.<myId>`, same discipline as
  the cache above). It returns `[value, setValue, remember]` and a game opts in by holding its
  difficulty state in it and calling `remember` **where the vs-AI game is created** — not from the
  picker's `onChange`, or browsing the tiers and backing out would rewrite the default. The stored
  id is validated against the tiers the picker currently OFFERS, because a retired one (Spender's
  variant codes, Dontminion's plain Big Money) would otherwise restore as a selection the server
  silently coerces to a different bot than the label names. **A game that skips this compiles and
  renders a perfectly normal picker; it just forgets** — so
  `shared/tests/test_ai_difficulty_memory.py` derives the roster from the tree (any game screen
  whose create message carries `ai_difficulty`/`ai_variant`) and fails the next game that lands
  without it. `screens.mjs` covers the behaviour end-to-end on Duel.
- **`splendor.jsx`** — Spender + Duel SHARE gems, jewel cards, and the move log
  (`GemToken`/`CardView`/`TokenPill`/`BonusPill`/`LogEntry` + CSS), lifted verbatim from Spender.jsx.
  **If a second game needs a Spender visual, EXTRACT it here — don't re-approximate it** (Duel drifted
  before this existed). Gems are matte gradient via a `--gc` custom property + drop shadow, **no ring**
  (a same-hue ring paints a bright lower-edge arc). `CardView` is game-rule-free (Duel's extras are
  optional props). Verify a splice against the pristine pre-refactor commit `dc1b005`, not a `.bak`.
- **`AuthScreen.jsx` / `HomeScreen.jsx`** — site-SHELL screens, here for the DEPENDENCY DIRECTION, not
  for semantics. See `games/spender/CLAUDE.md` → Frontend for why, and what finishing the split needs.
  **THE SHELL HAS TWO DELIBERATE WORDMARK TREATMENTS.** The menu keeps a compact mark in
  its upper-left identity rail; loading and auth are one entrance sequence and share the
  foiled hero wordmark and `HERO_RULE` ornament. All three share the fixed warm ground,
  vignette and tiled feTurbulence grain through paired selectors in
  `games/spender/Spender.css` (the loading screen still lives in `Spender.jsx`).
  `HERO_RULE` is exported from `HomeScreen.jsx` and passed into `AuthScreen`; do not copy
  its declaration.
  **Historical note — before the menu refinement, the gate rendered all three screens**
  (the loading screen by stalling `**/games**` past the shell's 250ms fast path) and
  fails if the type size, tracking, ornament width or the gap under the title differ.
  It was written because they DID: clamp(...,3.1rem)/(...,3.4rem)/(...,4rem) meant the
  title grew 50→54→67px at 1920 while a visitor watched, and `.home-rule` at `74%` drew
  at 253/241/265px because the three columns are padded 32/20/16. The ornament is
  viewport-relative now for exactly that reason. Note that the h1's own BOX width still
  differs (it is its container's) and is deliberately not compared. **It runs at TWO
  viewports, and the second one is the whole point**: at 1440x900 it passed while the
  wordmark was 48px on the menu and 64px on the two screens in front of it at 1280x800,
  because the short-viewport tier (height <= 880) compressed only `.home-logo` and 900
  sits just above it. A gate that tests one viewport tests one branch of a ramp.
  **The emblem plate is gated too** — that it is visibly tinted at all, and that it holds
  its accent's HUE. It is derived by mixing the accent into the card ground, and mixing
  `in srgb` let the warm ground win: Where Wolf's plate came out chromatically neutral
  and read as disabled beside six tinted siblings, and Dontminion's cyan rendered green.
  It mixes `in oklab` at 36% now, and 36 is the measured floor — 30% still drifted Duel
  and Dissonance past 22 degrees.
  **Any colour probe in that gate must go through a 1x1 canvas.** `getComputedStyle`
  returns whatever notation the DECLARATION used, so a `color-mix(in oklab, ...)` comes
  back as `oklab(0.36 0.002 0.04)` — and a regex that assumes `rgb()` reads those three
  numbers as R,G,B and reports a near-black grey. That is how the plate check first
  "failed" on plates that were perfectly correct. `canvas.fillStyle` parses any CSS
  colour and hands back sRGB bytes.
  **The footer is `.shell-foot`, ONE class on all three screens, and it must stay one.**
  It was `.home-foot`/`.auth-foot`/`.loading-foot` — five rules across four different
  selector lists — and they drifted exactly as that arrangement guarantees: the loading
  one missed the `<=430px` step and set 24% larger than its neighbours on a phone, the
  auth one missed the `>=1500` step and set 11% smaller at 1920, and home let it flow at
  the end of a centred column while the other two pinned it, so at 2560 the same
  sentence sat 207px off the bottom against their 35. All three screens use the same
  `main` + `shell-foot` shell now.
  **ALL SEVEN GAME CARDS ARE THE SAME SIZE, AT EVERY TIER — do not reintroduce a
  "banner".** A card alone on its row used to span the row, which made the seventh game a
  different SHAPE from the other six, and that one idea cost three separate bugs on its
  own: the pill aligned to the block instead of the title line, a half-lit chevron leaked
  into the one-column tier where all seven cards are identical and there is no hover to
  explain it, and the plate sat 15px below its siblings'. Every one of them came from the
  same root — `:last-child:nth-child(3n+1)` also matches when there is only ONE column —
  and each needed its own counter-rule in a `@media(max-width:559px)` block that was
  missed three times running. The user called it: seven identical cards and a last row
  that is simply not full. `screens.mjs` measures width, height, plate/title/pill offsets
  and chevron opacity across all seven at five widths, so the whole class is gated rather
  than the instance in front of you. The fold still holds at 1280x800 and 1920x1080; the
  room for the third equal row came out of the two tiers' card padding and plate size.
  **`.auth-panel`'s `min-height` is a MEASURED number and rots on any copy change.** It
  is the tallest tab's natural height, so the three tabs come out one height and the
  centred card cannot move the tab strip under the cursor. Adding one helper line moved
  it 272 -> 344. `screens.mjs` gates the card height AND the CTA's offset across the
  three tabs at two viewports, and caught that on the first run after the edit. Note the
  `>=1500` floor is LOWER than the base one (310 vs 344) and that is not a mistake: the
  card is 480px wide there against 420, so the helper lines wrap less.
  **A height lock can outlive its reason — re-derive it before defending it.** The
  panel's floor existed because the card was vertically CENTRED, so a shorter tab moved
  the tab strip up, under the cursor that had just clicked it. Top-anchoring the card
  (for the wordmark, below) removed that hazard entirely, at which point the lock was
  buying nothing and costing an 84px void above AND below Guest's fact list. The gate
  now asserts the tab strip and first field hold still, which is what the hazard
  actually was; the floor is gone. The same applies to the error slot: it was RESERVED
  space so the CTA could not jump, and with no lock it is just a ~50px hole the eye
  reads as a missing element — it collapses when empty, but stays in the DOM, because an
  aria-live region must not be added and removed.
  **The wordmark's POSITION is part of the lockup, not just its size.** It sat at
  269 / 98.5 / 68.5 at 1280x800 while size and centring were pixel-identical — loading
  and auth centred their block, home top-anchored — so both boot paths moved the brand
  mark ~200px while the user watched, and the gate passed throughout. All three screens
  top-anchor now and share `--shell-top` / `--shell-rail` / `--shell-hero-gap`; the two
  with no identity rail stand in for its height, which is why the rail is `height` and
  not `min-height` (a floor is not the real height, and the wordmark sat 6px low while
  it was one).
  **Nothing interactive may use `--text-dim`.** At 4.36:1 it fails AA for something a
  person is being asked to click, and it was setting `.btn-ghost` — the EXIT chip and
  the loading screen's only escape hatch from a cold host. The tertiary tier also sits
  in the LIT part of the page, where the warm top light raises the local ground and
  takes the contrast down with it, so measure these against the lit ground rather than
  against `--bg`.
  Two layout rules there are load-bearing rather than stylistic:
  - **The card is a list ROW at 1–2 columns and a POSTER at 3.** At two columns the card
    is 440–550px wide and ~190 tall (nearly 3:1), and the poster stacks everything down
    the left, so 40% of every card was empty. One DOM serves both via
    `grid-template-areas` over four flat children (emblem / text / players / go).
  - **A card that would be alone on its row SPANS the row** (`:last-child:nth-child(3n+1)`
    at three columns, `2n+1` at two, and the same for `.home-extra`). It is keyed on the
    COUNT, not on "seven games": an eighth game turns it off by itself. Centring a
    partial row instead only lands on the grid for some column/remainder parities, so it
    was on-grid at the laptop width and straddling a gutter at the tablet width.
    **The banner's composition is ONE rule shared by both tiers**; only the
    `flex-basis:100%` lives per tier. It first kept the list-row stack at two columns
    (everything in the left 40% of a 1400px card) and sent the pill to the far container
    edge at three (1000px from the description it annotates) — two fallbacks rather than
    a design. Note the `@media(max-width:559px)` counter-block: at one column EVERY card
    is `:last-child`-eligible in the sense that matters, so without it the whole list
    turned into banners.
  - **`@media(min-width:1000px) and (max-height:880px)` compresses the ramp**, and it is
    keyed on HEIGHT because that is what runs out. 1280x800 is the one common desktop
    size where the page overflowed, and the fold landed within ~20px of the "Also here"
    rule — a section divider and three card tops as the last thing on screen, which is
    the worst possible cut. A 1280x1100 window keeps the full ramp. It is LAST in the
    section so it out-orders what it overrides; a media query adds no specificity.
- **`.home` NEEDS `width:100%`, and this is not tidiness.** It is a flex ITEM (`.app` is a
  column flex container) and it carries `margin:0 auto`. **Auto inline margins on a flex
  item switch off the default `stretch`**, so with `max-width:900px` alone the box sized to
  fit-content — about 516px — and the max-width never applied at any viewport. The site
  rendered as a narrow ribbon down the middle of every desktop, with the game titles
  wrapping in 240px columns, for as long as that rule existed. `.offline-hub` already
  carried `width:100%` and is why IT looked right. **Every DOM-level check passed the whole
  time**, which is why `screens.mjs`'s `homeScreen` block now asserts a WIDTH.
- **`--text-soft` (`theme.base-css.css`) is the body-copy dim; `--text-dim` is for labels and
  `--text-muted` is DECORATION ONLY.** Measured on `--surface`: soft 6.1:1, dim 4.40:1 (fails
  AA for normal-size text), muted 2.5:1. A sentence in `--text-dim` on a card is below AA.
- **A HOME CARD'S ACCENT *IS* ITS GAME'S `--lby-accent`** — one value, in
  `shared/accents.js`, imported by both ends. **Hue separation between games is explicitly
  NOT a requirement, and the rule that said otherwise is why this note exists.** A gate
  once asserted the seven accents sat ≥23° apart inside a 0.364–0.404 luminance band, and
  the accents were tuned until they satisfied it: Castles of CRIMSON shipped pink and
  Dontminion's gold shipped cyan. The gate's own comment gave it away — *"the pair this was
  written for (two identical golds) measured 0"* — that pair is Spender and Dontminion, and
  they are both gold because Dontminion inherits the site gold. A true fact about the games,
  reported as a defect. Cards are told apart by name, emblem, tagline and colour together.
  **What IS gated**: `screens.mjs` enters each game and compares its RENDERED `--lby-accent`
  against the colour its home card paints. Note honestly what that does and does not buy —
  the four games that import the module cannot drift (one source), so the check is really
  for the three that define theirs in CSS and cannot import JS (`CastlesOfCrimson.css`,
  `RagTag.css`, and Dissonance aliasing its own `--accent`). Verified by breaking the module
  first, watching the gate PASS — both ends moved together — and then breaking RagTag.css,
  where it correctly failed and named the game.
  **Contrast is still gated, with a self-policing exemption.** Titles must clear 4.5:1
  except those listed in `ACCENT_AA_EXEMPT`; today only Castles of Crimson, whose exact
  crimson measures 3.59:1 and was shipped that way deliberately. A listed title must still
  clear 3.0, and a listed title that *starts* clearing 4.5 fails as STALE so the row gets
  deleted rather than sitting there forever — the same discipline as
  `core/tests/test_no_conditional_skips.py`.
- **`update-nudge.js`** — the stale-tab refresh prompt. It compares frontend-to-frontend via
  `version.json` / `__BUILD_ID__`, **never** against the backend's commit (frontend-only pushes leave the
  two SHAs legitimately different — a cross-comparison would cry wolf on every deploy).

---

## THE LOBBY IS THE SHELL'S ROOM NOW (2026-09-03)

The seven lobbies were rebuilt to the site menu's design. What changed is worth knowing
because most of it is now SHARED, so a new game inherits it and a new game can break it.

* **`shared/catalog.js` is the game catalogue** — id, name, player range, screen, accent.
  It was a private `GAMES` const inside `HomeScreen.jsx`; a lobby's identity band draws
  the same three facts, and two lists that agree by habit is the drift this repo keeps
  paying for. `shared/emblems.jsx` is the same move for the glyphs (a lobby importing the
  home SCREEN for one `<svg>` would have dragged the whole catalogue into every game's
  lazy chunk). `accents.js` remains the single source for the colour and is merged in.
* **`.lby-page` / `.lby-page-in` / `<LobbyHero>`** are the page. The ground is the shell's
  own recipe (`.home::before/::after`), with the accent added as a **7% tint on the
  vignette, never a wash on the paper** — at 13% Rag Tag's section labels fell to ~2.5:1
  and its emblem plate read as a hole. Two games painted their own ground on the game
  ROOT and so painted the lobby too (Rag Tag's arena floor, Dissonance's green): per-game
  ACCENT is the system, per-game PAPER is not.
* **`--lby-page-w` is the page's measure and the top bar reads it too** — the bar is
  full-bleed but its rails sit on the same arithmetic as `.lby-page-in`. Where Wolf tried
  narrowing this for its two-column lobby and it was wrong: the bar, the wordmark and the
  username narrowed with it, so walking in from another lobby slid the whole frame 160px.
  **Persistent chrome must not move between siblings.** The narrowing belongs to the GRID
  (`.lby-cols-2`, capped and left-aligned).
* **A lobby's `LobbyHeader` passes no `title`** — the identity band below carries the
  emblem, the accent wordmark and the player pill. In-GAME the header keeps its title.
* **`LobbyAction` is `.lby-act`, not `.btn`**, and the three kinds are a HIERARCHY:
  `primary` (Resume/Join) is a lit plate in the accent, `secondary` (Review/Return) an
  accent outline, `danger` (Cancel) the QUIETEST, red only on hover. Three games had
  drifted to styling Cancel exactly like Return.
* **Everything in the create row reads `--lby-accent`.** The old rule ("Create is always
  gold") predates accents meaning anything; a purple game's loudest object being Spender's
  gold is the same defect as seven identical Resume buttons.
* **`useListFade()` — one line per lobby, and it is not optional.** A column scrolls
  inside itself at the widest tier, so its last card is cut wherever the cap lands. Both
  CSS-only signals fail: an unconditional `mask-image` erases the last card of a column
  that does NOT overflow (a card with no bottom edge and clear page under it, on every
  lobby at 1920), and a visible scrollbar is invisible on every overlay-scrollbar platform
  and in every headless capture. The hook measures overflow, sets `data-more`, and also
  writes `--lby-list-fit` — **the column's height is measured, not `calc(100vh - <a
  number>)`**: the band's height is not a constant (it steps at 1500, its create row is
  one line or two, a sixth control makes it taller), so every number tried was wrong at
  some tier, either hiding a row or making the PAGE taller than the viewport.
* **One information architecture for a row.** Open: `<Host>'s game` + a `.lby-seats`
  chip + `CODE · time`. Active: the opponent + `CODE · time`, with the turn pill on the
  ACTIONS rail beside Resume. Packing the seat count into the meta is what made that line
  long enough to truncate to `· 2/4 players · 11…` on a phone.
* **Two lobbies stack a matchup** (`.lby-card-title.matchup`) because their Active list is
  PUBLIC. A lone dimmed `vs` leading an opponent-only title reads as a truncation and was
  removed; it stays where it joins two names that are both on screen.
* **A missing token renders BRIGHT, not dim.** CoC mounts bare and carries its own copy of
  the palette, and the copy predated `--text-soft`/`--text-muted` — an undefined custom
  property invalidates the declaration, so `.lby-card-meta` INHERITED `--text` and every
  room code on a Castles card rendered at nearly the weight of its title. Nothing looked
  broken; it looked emphasised.
* **A shared kit is only shared where nothing overrides it.** Every per-game defect this
  pass found was a local rule that had outlived its reason: Spender's phone card padding
  (12px shorter than the other six), Rag Tag's `--lby-list-max: 30rem` (its History
  stopped 344px above everyone's at 1920), Duel's and Spender's own bottom margins (the
  only two pages that out-scrolled their content), Dissonance's private 44px touch
  minimum (which made its band 8px taller than five siblings'), four different page
  gutters. **When you fix a shared rule, delete the local override that was working
  around it** — otherwise the two drift in the opposite direction.
* **THE PROSE ABOVE IS NOW A GATE, because prose in THIS file could never have stopped
  the drift it describes.** Two of the rules on this page — "a lobby's `LobbyHeader`
  passes no `title`" and "a shared kit is only shared where nothing overrides it" — were
  already written when Black Castle shipped a lobby that broke both, along with 20 more
  overrides. The mechanism is worth naming: `shared/CLAUDE.md` is loaded when you read
  files in `shared/`, and a new game is written entirely in `games/<new>/`, so nothing
  ever puts this document in front of the person who most needs it. The rule now lives in
  the ROOT `CLAUDE.md` (always loaded) and in two tests:
  `shared/tests/test_lobby_chrome_is_shared.py` refuses an appearance property on any
  chrome class from a game sheet (self-policing `SANCTIONED` map, non-vacuity test
  included), and `lobbyChrome` in `webapp/test/screens.mjs` walks all nine lobbies and
  asserts the kit's COMPUTED typography and geometry are IDENTICAL across them. The
  second one exists because the most expensive override in that set never mentioned a kit
  class: `.blackcastle button{font-family:inherit}` out-specifies `.lby-back`/`.lby-cta`/
  `.cm-create` and took the Cinzel off every shared control in that game. **Equality
  across games, not a table of expected values** — the invariant is "one kit, one look",
  so a deliberate change to the kit moves all nine together and the gate needs no edit.
* **A GAME'S PRIVATE PATCH OF A KIT BUG HIDES THE KIT BUG.** `.rl-title-ic` — the icon
  slot in the shared Rules modal — had no rule in `shared/` at all. `RULES_GLYPH` is an
  inline `<svg>` with a viewBox and no intrinsic size, so it fell back to the SVG default
  of 300x150 and eight of the nine lobbies opened "How to play" under a book glyph a
  third of the panel tall. It looked like eight separate design mistakes; it was one missing rule, and the
  create row's `.lby-rules-ic` next door sizes the same glyph correctly. The one game that
  looked right was the one carrying a private copy in its own sheet. Sized in the kit now,
  and `lobbyChrome` measures it in all nine.
* **The harness:** `webapp/test/lobby-shots.mjs` captures all seven lobbies empty and
  populated at four viewports; `webapp/test/lobby-probe.mjs` measures what a shot can only
  suggest (gutters, card widths, truncation, page overflow). Neither is a gate — `npm run
  screens` decides shipping. Both stub the list endpoints, and **a stub with a missing
  field looks exactly like a product bug**: "· players" with no number, a scoreless
  History and an actionless Rag Tag row were all the harness, and each cost a round.

---

## `CmSeg` CLIPS RATHER THAN SCROLLS, so a long picker needs `wrap` (2026-08-18)

The segmented control is `overflow: hidden` with `white-space: nowrap` buttons.
That is right for the 2–3 option pickers every create modal uses, and it fails
TOTALLY the moment the options outgrow one phone row: an option past the fold is
not off-screen, it is **unreachable** — nothing to scroll, nothing to swipe, no
affordance that anything is missing. The only symptom is a game that appears not
to exist.

**Measured when Dissonance became the offline hub's FOURTH game**: 485px of
buttons in a 330px box at a 390px viewport, the last option ending **154px past
the right edge**. Every width below ~545px was affected.

* **`<CmSeg wrap>` is the opt-in**, and it becomes separate CHIPS rather than a
  segmented bar: the shared 1px dividers (`border-left` between siblings) cannot
  survive wrapping — the first chip of each later row would wear one against the
  container edge, and nothing would divide the rows at all. Chips read as a group
  without dividers, so the container drops its border and each button takes one.
* **The basis is measured, not picked.** `flex: 1 1 10.5rem` — the hub's panel
  caps at 560px, so the row's widest client box is ~512px, and any smaller basis
  packs THREE chips with the fourth stranded alone on row 2 at every desktop
  width. 10.5rem is the smallest that cannot fit three there, giving 2×2 on a
  desktop, 2×2 from ~430px and one per row on a small phone.
* **A BASIS rather than a percentage**, so a fifth option adds a row instead of
  silently re-clipping.
* **Gated by rectangles, not by the DOM** (`screens.mjs`, `offlineDissonance` at
  a 390px viewport): every button must sit inside its container's box and the
  container must not overflow. A DOM-only check passed the entire time the bug
  was live. Verified non-vacuous by dropping `wrap` — it fails and NAMES the
  options that fall outside.

---

## URL routing (`router.js` — LIVE on prod)

Every mode has a path (`/spender /coc /duel /werewolf /books /puzzles`) and every room a sub-path
(`/spender/ABC123`) — reload/reconnect lands right, Back/Forward work, room URLs double as invite links.
- **The load-bearing contract:** `pushPath`/`replacePath` are **NO-OPS when the path is already current**
  (one function serves both a click and a popstate call → no duplicate history); `subscribe` fires on
  **popstate ONLY** (programmatic writes never notify → no echo loop).
- **Ownership split:** the shell owns segment 1 (`nav(screen)` writes the URL FIRST, then sets the screen —
  a sub-game reads `parsePath()` at mount, so its URL must already be correct); each sub-game owns its own
  room segment via a mount `parsePath()` + a `subscribe()` popstate handler (routed through a per-render
  ref so the mount-once effect never runs a stale closure).
- Room URL is pushed at **server-confirmed success** (`created`/`joined`/`reconnected`), never at click
  time. Entering a room by URL runs the existing resume semantics (token → `reconnect`, else `join`).
- **The race (caught by e2e):** Back during a join round-trip must abort a still-connecting attempt
  (`urlAttemptRef`/WW's `attemptRef`) or the late confirm re-pushes the room URL.
- **Deploy:** `dist/404.html` is REQUIRED (Pages has no rewrite rules) — `deploy-pages.yml` copies
  `index.html`→`404.html` AFTER build. **Cloudflare staging SPA-routes natively, so staging green NEVER
  validates prod deep links** — always cold-load a prod deep link after shipping.

---

## Verification harness for shared UI (reusable)

esbuild-bundle a scratch React harness importing the real component + shared CSS, with **react aliased to
`webapp/node_modules`** (`--alias:react=<webapp>/node_modules/react`), then Playwright-screenshot
(`chromium.launch()`, fall back to `channel:"msedge"`). `npm run smoke` only renders the Spender LOBBY, so
game-screen changes need this isolation render or a live staging check.
