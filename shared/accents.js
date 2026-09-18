/* One accent colour per game — the SINGLE source of truth for both ends of it.
 *
 * THE RULE: a game's home-menu card accent IS that game's `--lby-accent`, the custom
 * property its own screen sets to drive its lobby's section titles, hover borders,
 * create-modal buttons and phone tabs. Same value, no lift, no palette-level adjustment.
 * A player who taps a gold card must land on a gold game.
 *
 * HUE SEPARATION BETWEEN GAMES IS EXPLICITLY NOT A REQUIREMENT, and this file exists
 * because assuming otherwise broke the site. A gate once asserted that all seven accents
 * sat >=22 degrees apart in hue and inside a narrow luminance band, and the accents were
 * then tuned until they satisfied it — which turned Castles of CRIMSON pink and
 * Dontminion's gold cyan. The gate's own comment gave the game away: "the pair this was
 * written for (two identical golds) measured 0". That pair is Spender and Dontminion, and
 * they are both gold because Dontminion genuinely inherits the site gold. It was a true
 * fact about the games, reported as a defect. Cards are told apart by name, emblem,
 * tagline and colour together; two golds is what these games actually are.
 *
 * The values used to live in two places that agreed only by habit — this catalogue and
 * each game's own `--lby-accent` — and they drifted the moment something pushed on one of
 * them. Both ends import this now. Two games define theirs in CSS, which cannot import
 * JS (`CastlesOfCrimson.css`, `RagTag.css`), and Dissonance aliases `--lby-accent` to its
 * own `--accent`; those stay literals, and `webapp/test/screens.mjs` holds them honest by
 * entering each game and comparing the RENDERED `--lby-accent` against its home card.
 *
 * Adding a game: add it here, set `--lby-accent` from this module on the game's root, and
 * the gate will tell you if the two ever stop matching.
 */
export const GAME_ACCENTS = {
	spender: "#d4a84c",
	coc: "#d6454b",
	wherewolf: "#6f86d6",
	duel: "#bf6fd0",
	dontminion: "#b08d57",
	dissonance: "#6fe0a0",
	ragtag: "#e8663c",
	orbit: "#42d1c7",
	// PALE STONE, NOT A THIRD GOLD. This was #d5ae62, which put Black Castle's card
	// next to Dontminion's #b08d57 as very nearly the same card — and unlike the
	// Spender/Dontminion pair above, it had no claim to the site gold: it was simply
	// the lantern colour of its own board (`--bc-gold` in BlackCastle.css, which stays
	// gold, because the BOARD is the game and this is the site's handle on it).
	// Drawn instead from the board's own night-green ground (#101b1a), which is what
	// keeps it from reading as "no accent assigned": at chroma 10.5 against gold's
	// 44.3 it is near-neutral, but it is visibly CHOSEN.
	// Black and mid-gray were measured and are not available, which is worth stating
	// because both look reasonable as ideas. The accent is not decoration — the kit
	// paints it as a FILL under #171310 text (.lby-cta, .cm-create, .cm-seg-btn.sel)
	// and as the only colour of the wordmark on a near-black ground. #000 measures
	// 1.34:1 on the card and 1.14:1 for that button text (the rendered page loses its
	// wordmark, its emblem, Join, Rules and every selected control); #808080 measures
	// 3.97:1 on the card, under the 4.5 floor. The floor for anything neutral is
	// around #8a9196.
	blackcastle: "#a8bdb0",
	// SIGNAL BLUE. SecretNames is the one game on the site whose subject is a
	// transmission rather than a place or an object, and the palette had no blue
	// of this kind: Where Wolf's #6f86d6 is a violet-leaning periwinkle (hue 228)
	// and Orbit's #42d1c7 is green-leaning teal (177), so 201 sits in the gap
	// between them rather than beside either. It measures 6.67:1 on the home
	// card's light end (#272319) and 7.87:1 under the #171310 text the kit paints
	// on top of it as a fill, so it needs no AA exemption.
	secretnames: "#4fb3e8",
};

// Titles that do not clear the 4.5:1 AA floor on the card, and are shipped anyway
// because matching the game exactly was the explicit call. Each must still clear 3.0 —
// the floor the spine, plate and pill dot are held to — and `screens.mjs` fails a STALE
// entry too, so an accent that later comes up to 4.5 forces its row out of this map
// rather than sitting here forever claiming an exemption it no longer needs.
export const ACCENT_AA_EXEMPT = {
	// #d6454b on the card's light end (#272319) measures 3.59:1.
	coc: "exact crimson, chosen over a lightness lift so the card matches the game",
};
