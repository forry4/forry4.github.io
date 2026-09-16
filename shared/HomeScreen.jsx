/* The site landing menu — pick a game.
 *
 * Second piece of the shell/game split (see AuthScreen.jsx). Purely presentational:
 * no state of its own, no data fetching. The shell still owns identity and routing
 * and passes them in, so the eventual inversion has one less screen to untangle.
 *
 * The game catalogue lives here rather than in games/spender/Spender.jsx because it
 * describes the SITE, not the Spender game — Spender is just one of its entries.
 */
import { GAME_CATALOG } from "./catalog.js";
// The emblems live in their own module: a game's LOBBY hero draws the same mark,
// and it must come from one source rather than a second hand-drawn copy.
import { GAME_EMBLEM } from "./emblems.jsx";

const SITE_NAME = "Forrest Games";

// THE CATALOGUE MOVED to shared/catalog.js. It is no longer only the menu's list:
// every lobby's identity band draws the same name, player range and emblem from it,
// and two copies that agree by habit is the drift this repo keeps paying for.
// `accent` (the card's --accent custom property) is merged in there from
// shared/accents.js, which stays the single source for the colour.
const GAMES = GAME_CATALOG;

// Work-in-progress games stay in the shared catalogue so their lobbies and
// identity bands keep one source of truth, but the landing menu exposes them
// only to administrators. Direct routes are intentionally left unchanged.
const visibleGames = (authUser) => authUser?.is_admin
	? GAMES
	: GAMES.filter((game) => !game.adminOnly);

// The three side features, drawn to the same three rules. Emoji were the old labels,
// and an emoji is the one glyph a hand-set page cannot absorb: it arrives as a
// different typeface, a different weight and often a different COLOUR SCHEME on every
// OS, so the row read as three stickers pasted onto the page.
const EXTRA_ICON = {
	// A planted flag, not a jigsaw piece: the puzzle piece needed two knobs and an
	// interior contour to read as one, and at the 20px these render at, that collapsed
	// into a cluster of corner brackets. A flag is two strokes and says "solved".
	puzzles: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M6.4 20.2V4" /><path d="M6.4 5.2h11.4l-2.5 3.5 2.5 3.5H6.4" /></svg>),
	books: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M12 7.3C10.6 6 8.7 5.3 6.6 5.3H4.4v12.3h2.2c2.1 0 4 .7 5.4 2" /><path d="M12 7.3c1.4-1.3 3.3-2 5.4-2h2.2v12.3h-2.2c-2.1 0-4 .7-5.4 2" /><path d="M12 7.3v12.3" /></svg>),
	// A funnel, which is what the page DOES, and which survives 20px. The die it
	// replaced was a rounded square of five pips drawn inside a rounded-square plate —
	// three nested squares at 20px, i.e. mush.
	bgg: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M4.4 5.2h15.2l-5.9 7v6.4l-3.4-2.1v-4.3Z" /></svg>),
};

// Shared by the loading and sign-in screens. The menu deliberately does not use it:
// its wordmark is now the compact lockup at the upper-left.
//
// THE ORNAMENT AT ITS CENTRE IS THE SITE'S MARK, not a divider glyph. It was a gold
// diamond, which is the shape a rule uses when it has nothing to say: the front door's
// one piece of artwork now says whose door it is, and it is the SAME tree the browser
// is already drawing in the browser's own tab strip above it.
//
// webapp/public/favicon.svg is that tree, and is the one deliberate copy of this
// artwork — a <link rel=icon> cannot be a React node, so the mark cannot have a single
// source. KEEP THE TWO IN STEP. What makes that cheap is that the geometry below is
// the favicon's verbatim, in its own 100x100 box: everything this file adds is the one
// placement transform and the id prefixes, so a redraw is a copy-paste rather than a
// re-fit. The ids ARE prefixed (`fg-`) and that is load-bearing — an SVG url(#id) is
// document-scoped, so a bare `trunkGrad` here would be a name the whole page shares.
//
// The rule grew from a 240x14 box to 340x52 to hold it, and the mark is deliberately
// larger than the diamond was rather than the same size in a different shape. A
// diamond is an ornament and reads at any size; a tree drawn at ~16px is four dark
// circles over a stick, which is a clover.
//
// THE TWO LONG HAIRLINES ARE NEW HERE ONLY IN THE SENSE THAT THEY NOW RENDER. Their
// gradients had no `gradientUnits`, so they defaulted to `objectBoundingBox` — and the
// paths they paint are perfectly horizontal, i.e. a bounding box of zero height, which
// per spec makes the gradient (and so the stroke) not render at all. Chrome duly drew
// nothing: for as long as this rule has existed it has been a centre ornament flanked
// by its two short TICKS — which are `currentColor` and so always drew — with both long
// lines missing on every load. `userSpaceOnUse` with the coordinates written out has no
// bounding box to degenerate, and is the fix for any gradient on an axis-aligned line.
const HERO_RULE = (
	<svg className="home-rule" viewBox="0 0 340 52" aria-hidden="true" focusable="false" preserveAspectRatio="xMidYMid meet">
		<defs>
			<linearGradient id="fg-rule-l" gradientUnits="userSpaceOnUse" x1="3" y1="0" x2="135" y2="0"><stop offset="0" stopColor="currentColor" stopOpacity="0" /><stop offset="1" stopColor="currentColor" stopOpacity="1" /></linearGradient>
			<linearGradient id="fg-rule-r" gradientUnits="userSpaceOnUse" x1="205" y1="0" x2="337" y2="0"><stop offset="0" stopColor="currentColor" stopOpacity="1" /><stop offset="1" stopColor="currentColor" stopOpacity="0" /></linearGradient>
			<linearGradient id="fg-tree-trunk" gradientUnits="userSpaceOnUse" x1="50" y1="50" x2="50" y2="90">
				<stop offset="0" stopColor="#163C11" /><stop offset=".4" stopColor="#20290C" /><stop offset="1" stopColor="#2A1608" />
			</linearGradient>
			{/* The mark's own fills are near-black on a near-black page, so it is read by
			    its OUTLINE rather than by its ink: dilate the alpha, flood that ring with
			    the light hue, merge the source back over it. Two filters because the crown
			    is outlined green and the trunk brown. */}
			<filter id="fg-tree-leaf" x="-20%" y="-20%" width="140%" height="140%">
				<feMorphology in="SourceAlpha" operator="dilate" radius="2" result="d" />
				<feFlood floodColor="#86D466" />
				<feComposite in2="d" operator="in" result="o" />
				<feMerge><feMergeNode in="o" /><feMergeNode in="SourceGraphic" /></feMerge>
			</filter>
			<filter id="fg-tree-bark" x="-30%" y="-30%" width="160%" height="160%">
				<feMorphology in="SourceAlpha" operator="dilate" radius="2" result="d" />
				<feFlood floodColor="#B57B45" />
				<feComposite in2="d" operator="in" result="o" />
				<feMerge><feMergeNode in="o" /><feMergeNode in="SourceGraphic" /></feMerge>
			</filter>
		</defs>
		{/* The rule's own opacity lives on ITS paths, not on the <svg>: an element-level
		    opacity would have dimmed the mark by the same 10% it is there to soften the
		    hairlines by, and the mark is the thing the eye is meant to land on. */}
		<path d="M3 26h132" stroke="url(#fg-rule-l)" strokeWidth="1.4" opacity=".9" />
		<path d="M205 26h132" stroke="url(#fg-rule-r)" strokeWidth="1.4" opacity=".9" />
		<path d="M140 26h5M195 26h5" stroke="currentColor" strokeOpacity=".68" strokeWidth="1.4" />
		{/* 0.5 puts the mark's 91.5-unit drawn height (its outline included) at 46 of the
		    rule's 52; the inner translate is the mark's own centre of mass rather than the
		    centre of its 100x100 box, so it hangs ON the line instead of near it. */}
		<g transform="translate(170 26) scale(.5) translate(-50 -48.25)">
			<g filter="url(#fg-tree-bark)">
				<path d="M46 48 C45.5 62 45 77 34 92 C40 88 46 88 50 88 C54 88 60 88 66 92 C55 77 54.5 62 54 48 Z" fill="url(#fg-tree-trunk)" />
			</g>
			<g filter="url(#fg-tree-leaf)">
				<circle cx="50" cy="25" r="20.5" fill="#163C11" />
				<circle cx="50" cy="43" r="14" fill="#163C11" />
				<circle cx="31" cy="47" r="19" fill="#163C11" />
				<circle cx="69" cy="47" r="19" fill="#163C11" />
			</g>
		</g>
	</svg>
);

const GO_CHEVRON = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round"><path d="M9.5 5.5 16 12l-6.5 6.5" /></svg>
);

export { SITE_NAME, GAMES, GAME_EMBLEM, HERO_RULE };

export default function HomeScreen({ authUser, css, toast, onPickGame, onPuzzles, onBooks, onBggFilter, onLogout }) {
	// Built here rather than at module scope because each entry closes over a prop.
	const games = visibleGames(authUser);
	const extras = [
		{ id: "puzzles", label: "Spender Puzzles", onClick: onPuzzles },
		{ id: "books", label: "Books", onClick: onBooks },
		{ id: "bgg", label: "BGG Filter", onClick: onBggFilter },
	];
	return (
		<>
			<style>{css}</style>
			<div className="app">
				{/* The ambient ground (warm top light, vignette, grain) is painted by
				    .home::before/::after as two fixed layers, so it does not scroll away
				    under a long catalogue and costs no extra element. */}
				<div className="home">
					{/* Same main shell as the auth and loading screens, so the three read as
					    one page as the boot moves through them. */}
					<div className="home-main">
					{/* ONE unboxed identity string and ONE chip. It used to be a bordered
					    "Guest" pill, then a bare username, then a bordered button — three
					    items where the MIDDLE one had no frame, which does not read as a
					    hierarchy, it reads as a style rule that failed to apply. */}
					<header className="home-header">
						<h1 className="home-logo home-corner-logo">{SITE_NAME}</h1>
						<div className="browser-user">
							<span className="home-ident">
								{authUser?.guest && <span className="home-ident-kind">Guest</span>}
								<span className="browser-username">{authUser?.name}</span>
							</span>
							<button className="btn btn-ghost btn-sm" onClick={onLogout}>
								{authUser?.guest ? "Exit" : "Logout"}
							</button>
						</div>
					</header>

					<nav className="home-games" aria-label="Games">
						{games.map(gm => (
							<button key={gm.id} className={`home-game-card ${gm.status}`} data-game={gm.id}
								style={{ "--accent": gm.accent }}
								onClick={() => onPickGame(gm.screen)}>
								{/* FOUR FLAT CHILDREN, PLACED BY grid-template-areas, because the
								    card is two different objects at two sizes and they must not
								    be two different DOMs. In a single column it is a LIST ROW —
								    emblem rail on the left, everything else in one text column
								    beside it. From two columns up it is a POSTER — emblem on its
								    own line, then the title and the player pill down the
								    same left edge. Nesting the text inside a head element made
								    the row layout easy and the poster impossible; areas make
								    both a four-line change of one rule.
								    Spans, not divs: the card is a <button>, and a <div> inside
								    phrasing content is invalid HTML that Safari has historically
								    reflowed differently from Chrome. */}
								<span className="home-game-emblem" aria-hidden="true">{GAME_EMBLEM[gm.id]}</span>
								<span className="home-game-text">
									<span className="home-game-name">{gm.name}</span>
								</span>
								<span className="home-game-players">{gm.players}</span>
								<span className="home-game-go" aria-hidden="true">{GO_CHEVRON}</span>
							</button>
						))}
					</nav>

					<section className="home-more" aria-labelledby="home-more-hd">
						<h2 className="home-more-hd" id="home-more-hd"><span>Extras</span></h2>
						<div className="home-extras">
							{extras.map(x => (
								<button key={x.id} type="button" className="home-extra" onClick={x.onClick}>
									<span className="home-extra-icon" aria-hidden="true">{EXTRA_ICON[x.id]}</span>
									<span className="home-extra-label">{x.label}</span>
								</button>
							))}
						</div>
					</section>
					</div>
				</div>
				{toast && <div className="toast">{toast}</div>}
			</div>
		</>
	);
}
