// Box Puzzles rules for the browser — the same rules as engine.py beside it, and both
// are held to tests/fixtures/parity.json, which is the reference simulator's own
// answers (see engine.py's docstring for the rules and their provenance).
//
// The server never trusts this file: a solve is sent as the list of tile presses and
// replayed through engine.py before anything reaches the leaderboard.

export const COLORS = ["GY", "WH", "PU", "YE", "GN", "PI", "BK", "RD", "OR", "BU"];
// Corner button k sits at corner tile CORNERS[k], clockwise from the top-left.
export const CORNERS = [0, 2, 8, 6];

const ortho = (i) => {
	const r = Math.floor(i / 3), c = i % 3, out = [];
	if (r > 0) out.push(i - 3);
	if (c < 2) out.push(i + 1);
	if (r < 2) out.push(i + 3);
	if (c > 0) out.push(i - 1);
	return out;
};
const RING_STEPS = [[-1, -1], [-1, 0], [-1, 1], [0, 1], [1, 1], [1, 0], [1, -1], [0, -1]];
const ring = (i) => {
	const r = Math.floor(i / 3), c = i % 3, out = [];
	for (const [dr, dc] of RING_STEPS) {
		const rr = r + dr, cc = c + dc;
		if (rr >= 0 && rr < 3 && cc >= 0 && cc < 3) out.push(rr * 3 + cc);
	}
	return out;
};
const ORTHO = Array.from({ length: 9 }, (_, i) => ortho(i));
const RING = Array.from({ length: 9 }, (_, i) => ring(i));

// The board after pressing tile i. Never mutates its input.
export function press(tiles, i) {
	const t = tiles.slice();
	const me = t[i];
	const act = me === "BU" ? t[4] : me;
	switch (act) {
		case "WH":
			for (const j of [i, ...ORTHO[i]]) {
				if (t[j] === me) t[j] = "GY";
				else if (t[j] === "GY") t[j] = me;
			}
			break;
		case "PU":
			if (i < 6) [t[i], t[i + 3]] = [t[i + 3], t[i]];
			break;
		case "YE":
			if (i >= 3) [t[i], t[i - 3]] = [t[i - 3], t[i]];
			break;
		case "GN":
			[t[i], t[8 - i]] = [t[8 - i], t[i]];
			break;
		case "PI": {
			const rg = RING[i], vals = rg.map((j) => t[j]);
			rg.forEach((j, k) => { t[j] = vals[(k + vals.length - 1) % vals.length]; });
			break;
		}
		case "BK": {
			const r = i - (i % 3);
			[t[r], t[r + 1], t[r + 2]] = [t[r + 2], t[r], t[r + 1]];
			break;
		}
		case "RD":
			for (let j = 0; j < 9; j++) {
				if (t[j] === "WH") t[j] = "BK";
				else if (t[j] === "BK") t[j] = me;
			}
			break;
		case "OR": {
			const counts = new Map();
			for (const j of ORTHO[i]) counts.set(t[j], (counts.get(t[j]) || 0) + 1);
			const top = Math.max(...counts.values());
			const leaders = [...counts].filter(([, n]) => n === top);
			if (leaders.length === 1) t[i] = leaders[0][0];
			break;
		}
		default:
			break;
	}
	return t;
}

export const cornersMatch = (tiles, target) => CORNERS.every((c, k) => tiles[c] === target[k]);

// THE BOX — a board plus its four buttons. `lit[k]` is button k pressed while its
// corner matched; a tile press puts out any button whose corner no longer matches,
// and a press on a button whose corner does NOT match resets the whole box. That
// makes "all four lit" the same thing as "all four corners match and each button
// was pressed", which is why a solve can be checked from the tile presses alone.
export function newBox(puzzle) {
	return { tiles: puzzle.tiles.slice(), lit: [false, false, false, false], moves: [] };
}

export function pressTileInBox(box, target, i) {
	const tiles = press(box.tiles, i);
	return {
		tiles,
		lit: box.lit.map((on, k) => on && tiles[CORNERS[k]] === target[k]),
		moves: [...box.moves, i],
	};
}

// -> { box, result: "lit" | "reset" | "open" }
export function pressButtonInBox(box, puzzle, k) {
	if (box.tiles[CORNERS[k]] !== puzzle.target[k]) return { box: newBox(puzzle), result: "reset" };
	const lit = box.lit.slice();
	lit[k] = true;
	const next = { ...box, lit };
	return { box: next, result: lit.every(Boolean) ? "open" : "lit" };
}
