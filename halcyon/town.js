/* Halcyon Rift — the town: a plaza the player walks around (owner's ask, 2026-11-18).
 *
 * The town is where everything that is not a fight happens, as PLACES you walk up
 * to and use with E: the vault (the account's storage), the forge (fusion), and
 * one portal per realm. It is client-only and has no rewards, so unlike the
 * dungeon it needs no server and no determinism — but it is written the same way
 * (a pure state + `stepTown(state, input)`), so the page drives both with one loop
 * and the renderer draws both with one map painter.
 *
 * The player can SHOOT here (owner's ask, 2026-11-18) — the same weapon code as the
 * fight (`playerFire`, `wallHit`), so a bow fires in town exactly as in a rift. Two
 * practice posts take the hits and show the damage, and what the last few seconds
 * add up to a second, so weapons can be compared before a run.
 *
 * A new realm is one more entry in REALMS and one more portal here.
 */
import { PLAYER_R, PLAYER_SPEED, DT, TPS, REACH, statsFor, playerFire, wallHit, landStarfalls } from "./sim.js";

// '#' wall, 'o' planter (blocks), '~' fountain water (blocks), '.' flagstone.
const MAP = [
	"######################",
	"#....................#",
	"#....................#",
	"#....................#",
	"#.oo..............oo.#",
	"#....................#",
	"#....................#",
	"#....................#",
	"#....................#",
	"#....................#",
	"#.........~~.........#",
	"#........~~~~........#",
	"#.oo......~~......oo.#",
	"#....................#",
	"######################",
];

/* The realms a portal can lead to. Only the Shallows exists yet (design §14.4). */
export const REALMS = [{ id: "shallows", name: "The Shallows" }];

/* Places to use. `hw`/`hh` are a solid station's half-size; a portal is walked
 * onto, so it is not solid. `reach` is how close counts as "at" it. */
export const STATIONS = [
	{ id: "vault", kind: "vault", label: "Vault", x: 3.5, y: 8, hw: 1.2, hh: 0.8, solid: true, reach: 0.9 },
	{ id: "forge", kind: "forge", label: "Forge", x: 18.5, y: 8, hw: 1.0, hh: 0.8, solid: true, reach: 0.9 },
	// The Dream Rift is a portal like a realm's (owner's call, 2026-11-18): walked
	// onto, not solid, and "at" it measured from its centre.
	{ id: "dream", kind: "dream", label: "Dream Rift", x: 6, y: 4.7, hw: 0, hh: 0, solid: false, reach: 1.3 },
	...REALMS.map((r, i) => ({ id: `realm:${r.id}`, kind: "portal", realm: r.id, label: r.name,
		x: 11 + (i - (REALMS.length - 1) / 2) * 5, y: 2.6, hw: 0, hh: 0, solid: false, reach: 1.3 })),
];

export const SPAWN = { x: 11, y: 7.5 };

/* Practice posts: solid, unkillable, and they keep the hits of the last DPS_WINDOW. */
export const POSTS = [{ id: "post-w", x: 6.5, y: 12.4, r: 0.45 }, { id: "post-e", x: 15.5, y: 12.4, r: 0.45 }];
export const DPS_WINDOW = 3 * TPS;

export function createTown(at = SPAWN, classId = "ranger") {
	const st = { tick: 0, w: MAP[0].length, h: MAP.length, tiles: MAP, stations: STATIONS,
		p: { x: at.x, y: at.y, r: PLAYER_R, mp: 0, fireCd: 0, burstLeft: 0, burstCd: 0, abilityCd: 0, empower: 0 }, near: null,
		bullets: [], starfalls: [], blasts: [], posts: POSTS.map((q) => ({ ...q, hits: [] })), floats: [],
		// What lies on the town's ground: { key, x, y } (the page keeps it from the store).
		floor: [], nearFloor: null };
	setTownGear(st, [], 1, classId);
	return st;
}

/* What the player has equipped, for the town's shooting. MP regenerates at the
 * gear's own rate, as in a fight (owner's call, 2026-11-18: no town bonus); a
 * change of gear only clamps it to the new maximum. */
export function setTownGear(st, gear, level = 1, classId = st.classId || "ranger") {
	st.classId = classId;
	const first = !st.stats;
	st.stats = statsFor(gear, level, classId);
	st.p.mp = first ? st.stats.maxMp : Math.min(st.p.mp, st.stats.maxMp);
	st.p.burstLeft = 0;
}

const solidTile = (c) => c === "#" || c === "o" || c === "~";
const shotSolidTile = (c) => c === "#" || c === "o";        // arrows fly over the fountain
const tileAt = (st, x, y) => {
	const ty = Math.floor(y), tx = Math.floor(x);
	return ty < 0 || ty >= st.h || tx < 0 || tx >= st.w ? "#" : st.tiles[ty][tx];
};
const inStation = (st, x, y, r) => st.stations.some((s) => s.solid && (s.rad
	? (x - s.x) ** 2 + (y - s.y) ** 2 < (s.rad + r) ** 2
	: Math.abs(x - s.x) < s.hw + r && Math.abs(y - s.y) < s.hh + r));
const inPost = (st, x, y, r) => st.posts.some((q) => (x - q.x) * (x - q.x) + (y - q.y) * (y - q.y) < (q.r + r) * (q.r + r));

function blocked(st, x, y, r) {
	for (let ty = Math.floor(y - r); ty <= Math.floor(y + r); ty++)
		for (let tx = Math.floor(x - r); tx <= Math.floor(x + r); tx++) {
			if (ty < 0 || ty >= st.h || tx < 0 || tx >= st.w || solidTile(st.tiles[ty][tx])) return true;
		}
	return inStation(st, x, y, r) || inPost(st, x, y, r);
}

/* Damage a post has taken per second over the last DPS_WINDOW (0 when idle). */
export function postDps(st, q) {
	const since = st.tick - DPS_WINDOW;
	let sum = 0;
	for (const h of q.hits) if (h.t > since) sum += h.dmg;
	return Math.round(sum / (DPS_WINDOW / TPS));
}

/* How far the player is from a station: from its EDGE for a solid one, its centre
 * for a portal. */
export function distanceTo(p, s) {
	if (s.rad) return Math.max(0, Math.hypot(p.x - s.x, p.y - s.y) - s.rad);
	const dx = Math.max(0, Math.abs(p.x - s.x) - s.hw), dy = Math.max(0, Math.abs(p.y - s.y) - s.hh);
	return Math.sqrt(dx * dx + dy * dy);
}

/* input: { mx, my: -1|0|1; ax, ay: aim; fire, ability: bool }. Moves the player
 * (sliding along what blocks it), shoots, flies the arrows, and sets `near` to the
 * station within reach, closest first, or null. */
export function stepTown(st, input) {
	st.tick++;
	const p = st.p;
	let mx = input.mx || 0, my = input.my || 0;
	if (mx && my) { mx *= 0.7071067811865476; my *= 0.7071067811865476; }
	const dx = mx * PLAYER_SPEED * DT, dy = my * PLAYER_SPEED * DT;
	if (dx !== 0 && !blocked(st, p.x + dx, p.y, p.r)) p.x += dx;
	if (dy !== 0 && !blocked(st, p.x, p.y + dy, p.r)) p.y += dy;

	p.mp = Math.min(st.stats.maxMp, p.mp + st.stats.mpRegen * DT);
	playerFire(st, input);
	// A star lands on the posts as on enemies, so the Diviner can try it here.
	landStarfalls(st, (f) => {
		for (const q of st.posts) {
			const ddx = q.x - f.x, ddy = q.y - f.y, rr = q.r + f.r;
			if (ddx * ddx + ddy * ddy >= rr * rr) continue;
			q.hits.push({ t: st.tick, dmg: f.dmg });
			st.floats.push({ x: q.x, y: q.y - 0.6, text: String(f.dmg), until: st.tick + 40 });
		}
	});
	const keep = [];
	for (const b of st.bullets) {
		b.x += b.vx * DT; b.y += b.vy * DT;
		if (--b.life <= 0 || wallHit(b, (x, y) => shotSolidTile(tileAt(st, x, y)) || inStation(st, x, y, 0))) continue;
		let gone = false;
		for (const q of st.posts) {
			if (b.hit.includes(q.id)) continue;
			const ddx = q.x - b.x, ddy = q.y - b.y, rr = q.r + b.r;
			if (ddx * ddx + ddy * ddy >= rr * rr) continue;
			b.hit.push(q.id);
			q.hits.push({ t: st.tick, dmg: b.dmg });
			st.floats.push({ x: q.x + (st.tick % 7 - 3) * 0.08, y: q.y - 0.6, text: String(b.dmg), until: st.tick + 40 });
			if (b.pierce-- <= 0) { gone = true; break; }
		}
		if (!gone) keep.push(b);
	}
	st.bullets = keep;
	for (const q of st.posts) while (q.hits.length && q.hits[0].t <= st.tick - DPS_WINDOW) q.hits.shift();
	st.floats = st.floats.filter((f) => f.until > st.tick);

	let best = null, bd = Infinity;
	for (const s of st.stations) {
		const d = distanceTo(p, s) - p.r;
		if (d <= s.reach && d < bd) { bd = d; best = s; }
	}
	st.near = best ? best.id : null;
	// The closest thing on the ground within reach, picked up with E before any station.
	let fb = null, fd = REACH * REACH;
	for (const f of st.floor || []) {
		const d = (f.x - p.x) ** 2 + (f.y - p.y) ** 2;
		if (d <= fd) { fd = d; fb = f.key; }
	}
	st.nearFloor = fb;
	return st;
}

/* Where to stand to use a station — just in front of it (for the harness and for
 * putting the player back beside the portal they came through). */
export function standAt(id) {
	const s = STATIONS.find((x) => x.id === id);
	if (!s) return SPAWN;
	if (s.kind === "portal" || s.kind === "dream") return { x: s.x, y: s.y + 2.2 };
	return { x: s.x + (s.x < SPAWN.x ? 1 : -1) * (s.hw + 0.8), y: s.y };
}
