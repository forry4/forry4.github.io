import { readFileSync } from "node:fs";

// Test-only font: this is the wider Linux fallback behind Pages failures #827/828.
// Loading the bytes explicitly makes the regression reproducible on Windows too.

// DejaVu Sans Bold advances a digit by this fraction of the em. It is a property
// of the FILE, so it is the same everywhere; the RASTERISED width is not.
const DIGIT_EM = 0.69580078125;
// Chrome positions glyphs subpixel on Windows and hints the advance to whole
// pixels on Linux, so the same file measures 69.580078125 here and 70 on the
// Ubuntu runner. That 0.42px spread failed Pages #837/#838 on an exact-match
// guard. Probing at a large size makes the rounding vanish into the ratio
// (<=1px of 2000), while every other candidate for a silent fallback is orders
// of magnitude further away: Arial/Liberation Bold digits are 0.556em and
// Verdana Bold 0.7139em, i.e. 0.018em clear of this window at the nearest.
const PROBE_PX = 2000;
const DIGIT_EM_TOLERANCE = 0.002;
export const isFixtureDigitWidth = (width, px = PROBE_PX) =>
	Math.abs(width / px - DIGIT_EM) <= DIGIT_EM_TOLERANCE;

// A tolerance wide enough to swallow a wrong font is the same green-tick-over-
// nothing this whole fixture exists to prevent, so prove the window still
// excludes one. Pure arithmetic: no font, no platform, runs every time.
if (isFixtureDigitWidth(0.556 * PROBE_PX) || !isFixtureDigitWidth(DIGIT_EM * PROBE_PX)) {
	throw new Error("font fixture tolerance is vacuous: it no longer tells DejaVu from a fallback");
}

export async function linuxNumericFont(page, selector) {
	// Missing or corrupt bytes throw here and at face.load() below: that, not the
	// measured width, is what proves the fixture loaded. The width check cannot
	// carry it alone, because the Ubuntu runner's own sans IS DejaVu, so a silent
	// fallback there measures exactly like a successful load.
	const bytes = readFileSync(new URL("./fixtures/fonts/DejaVuSans-Bold.ttf", import.meta.url));
	await page.evaluate(async ({ base64, probePx, digitEm, tolerance }) => {
		const face = new FontFace("ScreensLinuxSans", `url(data:font/ttf;base64,${base64})`, { weight: "700" });
		document.fonts.add(await face.load());
		const canvas = document.createElement("canvas").getContext("2d");
		canvas.font = `700 ${probePx}px "ScreensLinuxSans"`;
		const width = canvas.measureText("0").width;
		const em = width / probePx;
		if (face.status !== "loaded" || !document.fonts.check(`700 ${probePx}px "ScreensLinuxSans"`)) {
			throw new Error(`Linux font fixture did not register: status=${face.status}`);
		}
		if (!(Math.abs(em - digitEm) <= tolerance)) {
			throw new Error(`Linux font fixture has the wrong metrics: ${em.toFixed(6)}em `
				+ `(${width}px at ${probePx}px), expected ${digitEm}em +/-${tolerance}`);
		}
	}, { base64: bytes.toString("base64"), probePx: PROBE_PX, digitEm: DIGIT_EM, tolerance: DIGIT_EM_TOLERANCE });
	return page.addStyleTag({ content: `${selector} { font-family: "ScreensLinuxSans" !important; }` });
}
