import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// Co-op runs one fight in several browsers, possibly on different engines, and a
// last-bit difference ends the run "out of step" (bossrush/CLAUDE.md). These maths
// are not rounded alike by every engine, so the fight code must not use them: the
// trig goes through dsin/dcos/rotate, a length through Math.sqrt, a square through
// sq(). `**` is Math.pow. Comments are stripped first: the files explain the rule.
const FIGHT = ["sim.js", "crypt.js"];
const BANNED = /Math\.(sin|cos|tan|asin|acos|atan2?|sinh|cosh|tanh|hypot|exp|expm1|pow|log|log2|log10|log1p|cbrt|random)\b|\*\*/g;

const code = (file) => readFileSync(new URL(`../../../bossrush/${file}`, import.meta.url), "utf8")
	.replace(/\/\*[\s\S]*?\*\//g, "")
	.replace(/\/\/.*$/gm, "");

test("the fight code uses no maths an engine may round its own way", () => {
	for (const file of FIGHT) {
		const found = [...code(file).matchAll(BANNED)].map((m) => m[0]);
		assert.deepEqual(found, [], `bossrush/${file} uses ${[...new Set(found)].join(", ")}`);
	}
});

test("the scan sees what it bans", () => {
	assert.deepEqual("a ** 2 + Math.hypot(x, y) // Math.sin".replace(/\/\/.*$/gm, "").match(BANNED), ["**", "Math.hypot"]);
});
