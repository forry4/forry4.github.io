import { readFileSync } from "node:fs";

// Test-only font: this is the wider Linux fallback behind Pages failures #827/828.
// Loading the bytes explicitly makes the regression reproducible on Windows too.
export async function linuxNumericFont(page, selector) {
	const bytes = readFileSync(new URL("./fixtures/fonts/DejaVuSans-Bold.ttf", import.meta.url));
	await page.evaluate(async (base64) => {
		const face = new FontFace("ScreensLinuxSans", `url(data:font/ttf;base64,${base64})`, { weight: "700" });
		document.fonts.add(await face.load());
		const canvas = document.createElement("canvas").getContext("2d");
		canvas.font = '700 100px "ScreensLinuxSans"';
		const width = canvas.measureText("0").width;
		if (face.status !== "loaded" || Math.abs(width - 69.580078125) > 0.01) {
			throw new Error(`Linux font fixture did not load with the expected metrics: ${width}`);
		}
	}, bytes.toString("base64"));
	return page.addStyleTag({ content: `${selector} { font-family: "ScreensLinuxSans" !important; }` });
}
