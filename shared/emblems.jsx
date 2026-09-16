/* The game emblems - one 24x24 line-art glyph per game, drawn as one family.
 *
 * Lifted OUT of HomeScreen.jsx so that the two places a game announces itself -
 * its card on the site menu, and the hero of its own lobby - draw the same mark
 * from one source. A lobby importing the whole home SCREEN for a glyph map would
 * also have dragged the catalogue and the side-feature icons into every game's
 * lazy chunk, for one <svg>.
 *
 * The three drawing rules below are the reason the set reads as a set, and they
 * are a constraint on anything added here, not a description of what is.
 */
/* ── THE EMBLEMS ARE ONE FAMILY, AND THAT IS A CONSTRAINT, NOT A DESCRIPTION ──
 * Inline SVG rather than an icon font or an image set: they inherit currentColor for
 * the per-card accent, and cost no extra request.
 *
 * Every glyph in this file — game emblems, side-feature icons, the card chevron — is
 * drawn to the SAME three rules, because the first set was not and it showed:
 *   • one 24x24 grid, with the ink inside roughly x,y in [4,20], so no glyph reads
 *     visibly bigger or smaller than its neighbours in an identical 48px plate;
 *   • one stroke width (1.5) — the old set mixed 1.4 strokes with solid fills, so the
 *     castle looked finer than the gem sitting next to it;
 *   • one join/cap (round), and no detail finer than ~1.5 units, because these render
 *     at 27px on a card and at 20px in the side-feature row, and anything denser than
 *     that turns to mush. The old Rag Tag glyph — three fingers and a chevron — was
 *     illegible at both sizes.
 * Two emblems were also re-CONCEIVED rather than redrawn: Dontminion and Dissonance
 * were both "some playing cards" and were confusable in a list of seven, so
 * Dontminion is now its economy (a stack of coins) and Dissonance keeps the cards.
 */
const GAME_EMBLEM = {
	// A brilliant-cut gem, table and facets.
	spender: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M8 4.6h8l3 4.9-7 10.5-7-10.5Z" /><path d="M5 9.5h14M10 9.5 12 20M14 9.5 12 20" /></svg>),
	// A keep with a raised gate.
	coc: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.5 19.6V9.4h2.7V6.6h2.7v2.8h4.2V6.6h2.7v2.8h2.7v10.2Z" /><path d="M10 19.6v-4.4h4v4.4" /></svg>),
	// The night. Grown ~15% on the old one, which read a size smaller than the rest.
	wherewolf: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M20.3 14.6A8.4 8.4 0 1 1 10.6 4.2 7.7 7.7 0 0 0 20.3 14.6Z" /><path d="M17.3 4.4v2.6M16 5.7h2.6" /></svg>),
	// The crown the duel is played for.
	duel: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.2 9 7.1 16.3h9.8L19.8 9l-4.4 3.6L12 5.5 8.6 12.6Z" /><path d="M7.4 19.2h9.2" /></svg>),
	// A treasure chest — Dontminion IS its economy, and a chest cannot be mistaken for
	// "some cards" the way the old fanned deck could. It replaced a stack of coins that
	// was drawn as three stacked ellipses and therefore read, unmistakably, as a
	// DATABASE CYLINDER: the one glyph in the set naming a technology instead of a
	// subject. The domed lid is what keeps it apart from the Castles keep at 27px.
	dontminion: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.6 10.8c0-3.3 3.3-5.6 7.4-5.6s7.4 2.3 7.4 5.6v7.4a.9.9 0 0 1-.9.9H5.5a.9.9 0 0 1-.9-.9Z" /><path d="M4.6 10.8h14.8" /><path d="M10.6 10.8h2.8v3.3h-2.8Z" /></svg>),
	// Two cards, the near one pipped — the trick.
	dissonance: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><rect x="3.9" y="6.4" width="8.6" height="12.2" rx="1.7" transform="rotate(-11 8.2 12.5)" /><rect x="11.5" y="4.9" width="8.6" height="12.2" rx="1.7" transform="rotate(9 15.8 11)" /><path d="M15.8 8.6 17.4 10.6 15.8 12.6 14.2 10.6Z" /></svg>),
	// Crossed blades, WITH GUARDS AND POMMELS, and both are load-bearing. The first
	// attempt at "the tag" was a two-headed swap arrow — legible at any size, and the
	// glyph every UI in the world uses for transfer/sync, sitting in a row with a
	// castle, a moon and a crown. The second was two bare diagonals with token
	// crossguards, and measured it carried 36% less ink than the mean of the other six;
	// worse, at 24px the guards disappeared and what remained was a plain X, i.e. the
	// universal close/cancel. The filled pommels and the full-length guards are what
	// make it read as swords rather than as a multiplication sign at the size it is
	// actually drawn.
	ragtag: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75" strokeLinejoin="round" strokeLinecap="round"><path d="M19 4.2 10.2 14.2 8.6 16" /><path d="M8.2 12.5 12.2 15.9" /><circle cx="7.6" cy="16.8" r="1.35" fill="currentColor" stroke="none" /><path d="M5 4.2 13.8 14.2 15.4 16" /><path d="M15.8 12.5 11.8 15.9" /><circle cx="16.4" cy="16.8" r="1.35" fill="currentColor" stroke="none" /></svg>),
	// A planet and its tilted orbital path — five worlds moving around one
	// centre, reduced to the one relationship that survives at menu size.
	orbit: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><circle cx="12" cy="12" r="3.1" /><ellipse cx="12" cy="12" rx="8.3" ry="4.2" transform="rotate(-24 12 12)" /><circle cx="18.3" cy="7.9" r="1.1" fill="currentColor" stroke="none" /></svg>),
	// A gate beneath the night moon — Black Castle's wood-and-lantern keep.
	blackcastle: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.5 19.5V9.8l3.1-2.2 2.2 1.5 2.2-1.5 2.2 1.5 2.2-1.5 3.1 2.2v9.7Z" /><path d="M9 19.5v-4.2h6v4.2M3.5 11.3h17M8 5.3h8" /></svg>),
};

export { GAME_EMBLEM };
