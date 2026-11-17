/* ROLE ART — one line-art glyph per role, drawn on the site's 24x24 grid.
 *
 * A role card used to be its NAME in a dark box: "SEER", and nothing else. The glyph is
 * what lets a card be read across the table and at 58px on a phone, and it is the same
 * drawing language as the home menu's emblems (shared/emblems.jsx): 1.6 stroke, round
 * caps, no fills except the odd pupil.
 *
 * NOT EMOJI, for the reason the menu's side-feature row was rebuilt: an emoji arrives as
 * a different typeface, weight and colour scheme on every OS. These inherit `color`.
 *
 * Purely presentational — no rules live here. A role with no entry renders no glyph and
 * the card falls back to its name alone.
 */
const S = { fill: "none", stroke: "currentColor", strokeWidth: 1.6, strokeLinecap: "round", strokeLinejoin: "round" };
const DOT = { fill: "currentColor", stroke: "none" };

const GLYPHS = {
	// A wolf's head, front on: two ears, a narrowing muzzle, slanted eyes.
	werewolf: (<>
		<path {...S} d="M5 3.5 8.6 9c1.9-1 4.9-1 6.8 0L19 3.5l.6 8c0 3.4-2.9 5.3-5.5 6.9L12 21l-2.1-2.6C7.3 16.800 4.400 14.900 4.400 11.500Z" />
		<path {...S} d="m8.800 12.300 1.900 1M15.200 12.300l-1.900 1M11 17.300h2" />
	</>),
	// A cottage: the village.
	villager: (<>
		<path {...S} d="M3.500 11.500 12 4.500l8.500 7" />
		<path {...S} d="M6 10v9.500h12V10" />
		<path {...S} d="M10.300 19.500v-4.700h3.400v4.700" />
	</>),
	// A crystal ball on its stand, with a glint.
	seer: (<>
		<circle {...S} cx="12" cy="10.200" r="6.400" />
		<path {...S} d="M7.500 20h9M9 20c.2-1.900 1.200-2.900 3-2.900s2.800 1 3 2.900" />
		<path {...S} d="M9.300 8.900c.4-1.400 1.300-2.300 2.700-2.700" />
	</>),
	// A bandit's eye mask.
	robber: (<>
		<path {...S} d="M3 9.300c3-1.500 6-1.300 9 .9 3-2.200 6-2.400 9-.9.500 4.100-1.500 6.700-4.500 6.700-2 0-3.300-1.300-4.500-2.600-1.200 1.300-2.500 2.600-4.500 2.600-3 0-5-2.600-4.500-6.700Z" />
		<path {...S} d="M6.900 12.200h2.500M14.600 12.200h2.500" />
	</>),
	// Two arrows trading places: the swap.
	troublemaker: (<>
		<path {...S} d="M4 8h12.500M13.500 5l3 3-3 3" />
		<path {...S} d="M20 16H7.500M10.500 13l-3 3 3 3" />
	</>),
	// A hide stretched to dry.
	tanner: (<>
		<path {...S} d="M8 4.200c1.800 1.500 6.200 1.500 8 0l3.500 2.500-2 3c1 1.900 1 3.700 0 5.600l2 3L16 20c-1.800-1.500-6.200-1.500-8 0l-3.500-1.700 2-3c-1-1.900-1-3.700 0-5.600l-2-3Z" />
	</>),
	// A foaming tankard.
	drunk: (<>
		<path {...S} d="M6 9.500h10v10H6Z" />
		<path {...S} d="M16 11.800h2.300c1.100 0 1.700.6 1.700 1.700v1.800c0 1.100-.6 1.700-1.700 1.700H16" />
		<path {...S} d="M6 9.500c-.2-2.300 1.400-3.300 3-2.700.7-1.800 3.300-1.800 4 0 1.600-.6 3.200.4 3 2.700" />
		<path {...S} d="M9.300 12.800v3.700M12.700 12.800v3.700" />
	</>),
	// Crosshairs.
	hunter: (<>
		<circle {...S} cx="12" cy="12" r="6.600" />
		<path {...S} d="M12 2.500v4.300M12 17.200v4.300M2.500 12h4.300M17.200 12h4.300" />
		<circle {...DOT} cx="12" cy="12" r="1.200" />
	</>),
	// Coursed brickwork.
	mason: (<>
		<path {...S} d="M3.500 6.500h17v11h-17Z" />
		<path {...S} d="M3.500 12h17M9 6.500V12M15 6.500V12M6.500 12v5.500M12 12v5.500M17.500 12v5.500" />
	</>),
	// A wide-open eye, lashes up: the one who cannot sleep.
	insomniac: (<>
		<path {...S} d="M3 13.500c3-4 6-5.400 9-5.400s6 1.400 9 5.400c-3 4-6 5.400-9 5.400s-6-1.400-9-5.400Z" />
		<circle {...S} cx="12" cy="13.500" r="2.500" />
		<path {...S} d="M12 3.500v2.200M6.200 5.300l1.300 1.900M17.800 5.300l-1.300 1.900" />
	</>),
	// A horned imp: the wolves' servant, and not a wolf.
	minion: (<>
		<path {...S} d="M7.200 9.200C5 8.200 4 6.200 4.500 3.500c1.500 2 3 2.800 4.600 3.100 1.800-.6 4-.6 5.800 0 1.600-.3 3.100-1.100 4.600-3.100.5 2.700-.5 4.700-2.700 5.700 1 2.100.9 4.900-.5 7.300L12 20.500l-4.300-4c-1.400-2.400-1.500-5.200-.5-7.300Z" />
		<path {...S} d="m9.200 12.300 1.700.9M14.800 12.300l-1.700.9" />
	</>),
	// Two faces, overlapping.
	doppelganger: (<>
		<circle {...S} cx="9.300" cy="12" r="5.600" />
		<circle {...S} cx="14.700" cy="12" r="5.600" />
	</>),
};

/** The glyph for a role, or null when the role has none. */
export function RoleGlyph({ role }) {
	const g = GLYPHS[role];
	if (!g) return null;
	return <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">{g}</svg>;
}

/** The crescent on every card back. One moon, so a face-down card says "night" and not "?". */
export function MoonBack() {
	return (
		<svg className="ww-back-moon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">
			<path fill="currentColor" d="M15.300 3.600a8.700 8.700 0 1 0 5.100 12.300A7.200 7.200 0 0 1 15.300 3.600Z" />
			<circle fill="currentColor" cx="5.600" cy="6.300" r=".7" />
			<circle fill="currentColor" cx="19.300" cy="19.600" r=".6" />
			<circle fill="currentColor" cx="20.200" cy="6.800" r=".5" />
		</svg>
	);
}
