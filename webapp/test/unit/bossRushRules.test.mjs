import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import { CLASS_INFO } from "../../../bossrush/sim.js";

// The rules list the classes as literals (the rules-shape gate reads them as text), so
// hold them to the class data: a renamed class or a reworded ability fails here.
test("How to play names every class and its ability as the class data does", () => {
	const rules = readFileSync(new URL("../../../bossrush/rules.jsx", import.meta.url), "utf8");
	for (const { name, description } of Object.values(CLASS_INFO))
		assert(rules.includes(`{ t: "${name}", d: "${description}" }`), `${name}: "${description}" is missing from bossrush/rules.jsx`);
});
