// Records the REFERENCE simulator's answers as boxpuzzles/tests/fixtures/parity.json.
//
//   node boxpuzzles/tools/gen_parity_fixtures.mjs <simulator bundle .js â€” path or URL>
//
// The reference is chandler.io's Mora Jai simulator. Its rules are a WASM module
// embedded base64 in the page's `morajai-bundle.min.<hash>.js`; this script pulls it
// out and calls its four exports directly (init_from_string, press_tile, press_outer,
// get_state), so the fixtures are the reference's own output, not a reading of its
// prose. Both engines are tested against them (tests/test_engine.py for engine.py,
// the boxPuzzles block of webapp/test/screens.mjs for engine.js).
//
// COVERAGE IS BUILT, NOT SAMPLED. The first fuzz of these rules used a weak LCG whose
// low bits cycled: five of the ten colours almost never landed in the centre, so blue
// copying white or red â€” the two quirks that decide four of the boxes â€” was never
// exercised and the fuzz read all-green. Every (pressed colour, centre colour) pair now
// gets its own cases, at every tile it can stand on.
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { press, cornersMatch } from "../engine.js";

const here = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(here, "..");
const src = process.argv[2];
if (!src) { console.error("usage: gen_parity_fixtures.mjs <bundle.js path or URL>"); process.exit(2); }
const bundle = /^https?:/.test(src) ? await (await fetch(src)).text() : fs.readFileSync(src, "utf8");
const b64 = bundle.match(/"(AGFzbQ[A-Za-z0-9+/=]+)"/);
if (!b64) { console.error("no embedded WASM found in the bundle"); process.exit(1); }

const { instance } = await WebAssembly.instantiate(Buffer.from(b64[1], "base64"),
	{ a: { a: () => { throw new Error("reference aborted"); } } });
const x = instance.exports;   // b memory, c ctors, d init, e press_tile, f press_outer, g get_state
x.c();
const mem = () => new Uint8Array(x.b.buffer);
const ref = {
	init(target, initial, current) {
		const s = `${target.join(",")}_${initial.join(",")}_${current.join(",")}`;
		const sp = x.j(), ptr = x.i(s.length + 1), m = mem();
		for (let k = 0; k < s.length; k++) m[ptr + k] = s.charCodeAt(k);
		m[ptr + s.length] = 0;
		x.d(ptr);
		x.h(sp);
	},
	tile: (i) => x.e(i),        // 0 ok, 1 reset, 2 opened
	button: (k) => x.f(k),
	state() {
		let p = x.g(), s = "";
		const m = mem();
		while (m[p]) s += String.fromCharCode(m[p++]);
		const [t, o] = s.split("_");
		return { tiles: t.split(","), lit: o.split(",").map((v) => v === "1") };
	},
};

const COLORS = ["GY", "WH", "PU", "YE", "GN", "PI", "BK", "RD", "OR", "BU"];
let seed = 0x2f6b9a1d;
const rand = () => {   // mulberry32
	seed = (seed + 0x6d2b79f5) | 0;
	let t = Math.imul(seed ^ (seed >>> 15), 1 | seed);
	t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
};
const pick = (a) => a[Math.floor(rand() * a.length)];
// A few colours per board, so neighbourhoods repeat colours (orange majorities, white
// clusters, blue next to blue) instead of nine strangers.
const board = () => {
	const pal = COLORS.filter(() => rand() < 0.45);
	if (pal.length < 2) pal.push(pick(COLORS), pick(COLORS));
	return Array.from({ length: 9 }, () => pick(pal));
};
const enc = (t) => t.join("");

const presses = [];
for (const pressed of COLORS) {
	for (const centre of COLORS) {
		for (let i = 0; i < 9; i++) {
			if (i === 4 && pressed !== centre) continue;
			for (let n = 0; n < 2; n++) {
				const t = board();
				t[4] = centre;
				t[i] = pressed;
				ref.init(["GY", "GY", "GY", "GY"], t, t);
				ref.tile(i);
				presses.push([enc(t), i, enc(ref.state().tiles)]);
			}
		}
	}
}

// A shortest line for a box, found with OUR engine — only to choose which presses to
// make. Every result recorded below is still the reference's.
function shortest(p) {
	const prev = new Map([[enc(p.tiles), null]]);
	let frontier = [p.tiles];
	while (frontier.length) {
		const next = [];
		for (const t of frontier) {
			for (let i = 0; i < 9; i++) {
				const u = press(t, i), k = enc(u);
				if (prev.has(k)) continue;
				prev.set(k, [enc(t), i]);
				if (cornersMatch(u, p.target)) {
					const line = [];
					for (let c = k; prev.get(c); c = prev.get(c)[0]) line.unshift(prev.get(c)[1]);
					return line;
				}
				next.push(u);
			}
		}
		frontier = next;
	}
	throw new Error(`no solution for ${p.id}`);
}

// Two sequences per real box. One wanders: tile presses, button presses right and
// wrong, lit buttons going dark, resets. The other SOLVES it — a button lit early,
// the shortest line, then all four buttons — so every box is proven to open in the
// reference itself, and the "opened" result is covered at all.
const bank = JSON.parse(fs.readFileSync(path.join(root, "puzzles.json"), "utf8"));
const sequences = [];
const run = (p, moves) => {
	ref.init(p.target, p.tiles, p.tiles);
	return moves.map((mv) => {
		const k = +mv.slice(1);
		const code = mv[0] === "b" ? ref.button(k) : ref.tile(k);
		const st = ref.state();
		return [mv, code, enc(st.tiles), st.lit.map(Number).join("")];
	});
};
for (const p of bank) {
	const wander = Array.from({ length: 20 }, () => (rand() < 0.3 ? `b${Math.floor(rand() * 4)}` : `t${Math.floor(rand() * 9)}`));
	sequences.push({ id: p.id, steps: run(p, wander) });
	const solve = [`b${Math.floor(rand() * 4)}`, ...shortest(p).map((i) => `t${i}`), "b0", "b1", "b2", "b3"];
	const steps = run(p, solve);
	if (steps[steps.length - 1][1] !== 2) throw new Error(`the reference did not open ${p.id}`);
	sequences.push({ id: p.id, steps });
}

const out = path.join(root, "tests", "fixtures", "parity.json");
fs.mkdirSync(path.dirname(out), { recursive: true });
fs.writeFileSync(out, JSON.stringify({
	source: "chandler.io Mora Jai simulator WASM",
	format: {
		presses: "[board before (9 two-letter codes), tile pressed, board after]",
		sequences: "steps of [t<tile>|b<button>, reference code 0 ok/1 reset/2 opened, board after, lit buttons]",
	},
	presses,
	sequences,
}) + "\n");
console.log(`wrote ${presses.length} presses and ${sequences.length} sequences to ${path.relative(process.cwd(), out)}`);
