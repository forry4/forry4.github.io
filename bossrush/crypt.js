// The Crypt Trio. Enemy shots and floor hazards share a short, readable
// tell, then overlap in the room. All times are simulation ticks.
import { HIT_DY, HIT_R } from "./hitbox.js";
export const CRYPT_HP = { orrery: 3200, glassweaver: 3200, cantor: 3200 };
const TAU = 6.283185307179586;
// A square as one multiply: `**` is Math.pow, which engines need not round alike (co-op).
const sq = (v) => v * v;
const TOWER_FAN = "fan", TOWER_TRACE = "trace";
export const CANTOR_ECHO_RANGE = 6;
const CANTOR_ECHO_INTERVAL = 12;
const CANTOR_PHASE_TWO_ECHO_SPACING = 14;
const CANTOR_PHASE_TWO_SPOKE_INTERVAL = 64;
const CANTOR_MINE_WARNING = 42;
const CANTOR_MINE_MAX_LEAD = 5;
const ORBIT_RAMP = 75;
const ORRERY_PERIODS = [146, 144];
const ORRERY_CORNER_ORDER = [0, 1, 3, 2];
const ORRERY_TRACE_LEAD = 6;
const ORRERY_PHASE_TWO_SPOKE_INTERVAL = 56;
const PHASE_BREAK = 90;
const EXTRA_WARNING = 12;
const GLASS_SAFE_DISTANCE = 3.5;
const GLASS_GAP_MIN_MOVE = 3;
const GLASS_GAP_MAX_MOVE = 11;
const GLASS_EXTRA_WALL_WARNING = 30;
const GLASS_PHASE_TWO_CYCLE = 179;
const GLASS_PHASE_TWO_WALL_PERIOD = GLASS_PHASE_TWO_CYCLE + 30;
const GLASS_SHOTGUN_WARNING = 24;

export function createCrypt(kind, towers = []) {
	return Object.hasOwn(CRYPT_HP, kind) ? {
		age: -1, beat: 0, phase2: false, phaseAt: null, transitionUntil: null, orbit: 0, bounds: null, marks: [],
		towers: towers.map((tower) => ({ ...tower, mode: "idle" })),
	} : null;
}

function mark(st, kind, delay, data) {
	st.crypt.marks.push({ kind, from: st.tick, at: st.tick + delay, ...data });
}

function nextQuarter(st, art, previous) {
	if (previous == null) return Math.floor(art.rand(st) * 4);
	return (previous + 1 + Math.floor(art.rand(st) * 3)) % 4;
}

function fan(st, art, source, count, spread, speed, dmg, angle = 0) {
	st.src = "crypt:needles";
	const [ux, uy] = art.aimFrom(source, art.target(st, source));
	art.fanAt(st, source, ux, uy, count, spread, speed, dmg, angle);
}

function markAimedFan(st, art, e, delay, count, spread, speed, dmg) {
	const p = art.target(st, e);
	mark(st, "fan", delay, { x: e.x, y: e.y, tx: p.x, ty: p.y, count, spread, speed, dmg });
}

function spokes(st, art, e, count, speed, dmg, angle, skip = -1) {
	st.src = "crypt:spokes";
	for (let i = 0; i < count; i++) {
		if (i !== skip) art.shoot(st, "e", e.x, e.y, angle + TAU * i / count, speed, dmg, 0.15, 175);
	}
}

function trace(st, art, tower, delay, r, dmg) {
	const { x0, x1, y0, y1 } = st.crypt.bounds;
	const [vx, vy] = art.aimFrom(tower, art.target(st, tower));
	const rx = vx > 0 ? (x1 - tower.x) / vx : vx < 0 ? (x0 - tower.x) / vx : Infinity;
	const ry = vy > 0 ? (y1 - tower.y) / vy : vy < 0 ? (y0 - tower.y) / vy : Infinity;
	const length = Math.min(rx, ry, 32);
	if (length > 0) mark(st, "line", delay, { x: tower.x, y: tower.y,
		tx: tower.x + vx * length, ty: tower.y + vy * length, r, dmg });
}

function mines(st, center, delay, r, dmg, count) {
	const { x0, x1, y0, y1 } = st.crypt.bounds;
	for (let i = 0; i < count; i++) {
		const dx = i === 0 ? 0 : i === 1 ? 1.5 : -1.5;
		const dy = i === 0 ? 0 : (st.crypt.beat % 2 ? 0.85 : -0.85);
		const x = Math.max(x0 + 0.35, Math.min(x1 - 0.35, center.x + dx));
		const y = Math.max(y0 + 0.35, Math.min(y1 - 0.35, center.y + dy));
		mark(st, "mine", delay, { x, y, r, dmg });
	}
}

const orreryCorner = (beat, start) => ORRERY_CORNER_ORDER[(beat + start) % ORRERY_CORNER_ORDER.length];

// Draw the next gold pillar just before its rail warning starts. The live
// tower assignment, random draw for the first beat, and attacks stay on schedule.
export function orreryTracePreview(crypt) {
	if (crypt.towerStart == null || crypt.transitionUntil != null) return -1;
	const period = ORRERY_PERIODS[crypt.phase2 ? 1 : 0];
	if (crypt.age < period - ORRERY_TRACE_LEAD || !crypt.towers.some((tower) => tower.mode === TOWER_TRACE)) return -1;
	return 3 - orreryCorner(crypt.beat + 1, crypt.towerStart);
}

/* The Orrery: a diagonal lights up on each beat. One corner lays a timed
 * rail across the room while the opposite corner fires aimed needles. The
 * boss adds spoke shots and starts orbiting at half health. */
function orrery(st, art, e, t) {
	const c = st.crypt, hard = c.phase2;
	if (hard) {
		const progress = Math.min(1, (st.tick - c.phaseAt) / ORBIT_RAMP);
		const radius = progress * progress * (3 - 2 * progress);
		c.orbit += 0.015;
		e.x = e.homeX + radius * 3.7 * art.dcos(c.orbit);
		e.y = e.homeY + radius * 2.85 * art.dsin(c.orbit);
	}
	// Keep the tower association stable for this attack, then move to the
	// other diagonal and swap which corner draws the rail.
	c.towerStart ??= nextQuarter(st, art);
	const corner = orreryCorner(c.beat, c.towerStart);
	const f = c.towers[corner], l = c.towers[3 - corner];
	const railRadius = 0.51;   // one width in both phases (owner, 2026-11-26)
	if (t === 0 && f && l) {
		for (const tower of c.towers) tower.mode = "idle";
		f.mode = TOWER_FAN;
		l.mode = TOWER_TRACE;
		trace(st, art, l, hard ? 34 : 38, railRadius, 22);
	}
	const fireSpokes = hard ? (st.tick - c.phaseAt) % ORRERY_PHASE_TWO_SPOKE_INTERVAL === 20 : t === 20 || t === 92;
	if (fireSpokes) {
		// Full rings, none left out: 10 (36 degrees apart), 12 in phase two (30) (owner, 2026-11-26).
		spokes(st, art, e, hard ? 12 : 10, 5.2, 15, c.beat * 0.43 + t * 0.042);
	}
	const secondFan = hard ? 64 : 54;
	if (f && (t === 31 || t === secondFan || t === 105)) {
		const spread = (hard ? 0.22 : 0.16) + Math.PI / 360; // half a degree wider
		fan(st, art, f, hard ? 7 : 5, spread, 6.498, 18, t === secondFan ? -0.08 : 0);
	}
	if (t === 74 && l) trace(st, art, l, 43, railRadius, 22);
}

function curtainEdge(b, side) {
	switch (side) {
		case "left": return b.x0 + 0.35;
		case "right": return b.x1 - 0.35;
		case "top": return b.y0 + 0.35;
		default: return b.y1 - 0.35;
	}
}

function comb(st, side, delay, crossingGap, half, hard, drift = 0, crossAt = 0) {
	const { x0, x1, y0, y1 } = st.crypt.bounds;
	const fromSide = side === "left" || side === "right";
	const low = fromSide ? y0 : x0, high = fromSide ? y1 : x1;
	const edge = curtainEdge(st.crypt.bounds, side);
	// Aim the diagonal opening at its intended crossing with the first curtain.
	const gap = crossingGap - drift * Math.abs(crossAt - edge);
	const points = [];
	for (let u = low + 0.38; u < high; u += 0.68) {
		if (Math.abs(u - gap) > half) points.push(u);
	}
	mark(st, "comb", delay, { side, edge, points, gap, half, fromSide, drift, speed: hard ? 6.84 : 6.03 });
}

function farEndWall(bounds, y) {
	return y < (bounds.y0 + bounds.y1) / 2 ? "bottom" : "top";
}

function glassGap(st, art, e, firstHalf, secondHalf, hard) {
	const { bounds: b, lastGap, previousGap } = st.crypt;
	const from = lastGap ?? st.p;
	const minMove = lastGap ? GLASS_GAP_MIN_MOVE : 0;
	const crossDirection = lastGap ? Math.sign(e.x - lastGap.x) : 0;
	const choices = [];
	let totalWeight = 0;
	const pad = 0.25;
	const y0 = b.y0 + firstHalf + pad, y1 = b.y1 - firstHalf - pad;
	for (const drift of hard ? [-0.48, 0.48] : [0]) {
		// This box encloses the full overlap of the straight and angled openings.
		const halfX = secondHalf + Math.abs(drift) * firstHalf;
		const x0 = b.x0 + halfX + pad, x1 = b.x1 - halfX - pad;
		for (let row = 0; row <= 12; row++) {
			const y = y0 + (y1 - y0) * row / 12;
			const fromBossY = Math.max(0, Math.abs(y - e.y) - firstHalf);
			// Validate the diagonal opening at the far wall it will launch from.
			const edge = curtainEdge(b, farEndWall(b, y));
			const offset = drift * Math.abs(y - edge);
			for (let column = 0; column <= 18; column++) {
				const x = x0 + (x1 - x0) * column / 18;
				const move = sq(x - from.x) + sq(y - from.y);
				if (move < sq(minMove) || move > sq(GLASS_GAP_MAX_MOVE)) continue;
				const fromBossX = Math.max(0, Math.abs(x - e.x) - halfX);
				if (sq(fromBossX) + sq(fromBossY) < sq(GLASS_SAFE_DISTANCE)) continue;
				const launchGap = x - offset;
				if (launchGap - secondHalf < b.x0 + pad || launchGap + secondHalf > b.x1 - pad) continue;
				// Discourage A -> B -> A and give a smaller nudge across the
				// arena. Every legal opening still has a chance to be picked.
				const fromEarlier = previousGap ? sq(x - previousGap.x) + sq(y - previousGap.y) : 0;
				const revisitWeight = 1 + 7 * Math.min(1, fromEarlier / 100);
				const crossWeight = 1 + 1.5 * Math.max(0, crossDirection * (x - from.x)) / GLASS_GAP_MAX_MOVE;
				totalWeight += revisitWeight * crossWeight;
				choices.push({ gap: { x, y, drift }, totalWeight });
			}
		}
	}
	const roll = art.rand(st) * totalWeight;
	return choices.find((choice) => roll < choice.totalWeight)?.gap;
}

/* The Glassweaver: each curtain has an obvious hole. Read two edges ahead
 * of time, then dodge the aimed floor mines without losing your window. */
function glassweaver(st, art, e, t) {
	const c = st.crypt, { beat, phase2: hard } = c;
	const opening = !hard && beat === 0 ? 15 : 0;
	const startWalls = hard ? (st.tick - c.phaseAt) % GLASS_PHASE_TWO_WALL_PERIOD === 0 : t === 0;
	if (startWalls) {
		const firstHalf = hard ? 1.34 : 1.66, secondHalf = hard ? 1.39 : 1.73;
		const gap = glassGap(st, art, e, firstHalf, secondHalf, hard);
		const wallWarning = GLASS_EXTRA_WALL_WARNING + (hard ? EXTRA_WARNING : opening);
		if (gap) {
			c.previousGap = c.lastGap;
			c.lastGap = gap;
			const { bounds } = c;
			const firstWall = gap.x < (bounds.x0 + bounds.x1) / 2 ? "right" : "left";
			comb(st, firstWall, 33 + wallWarning, gap.y, firstHalf, hard);
			comb(st, farEndWall(bounds, gap.y), (hard ? 49 : 56) + wallWarning, gap.x, secondHalf, hard, gap.drift, gap.y);
		}
	}
	if (t === 0) mines(st, art.target(st, e), (hard ? 63 : 70) + opening, 1.1, 22, hard ? 3 : 2);
	if (t === 52 || t === 102 || (hard && t === 126)) {
		markAimedFan(st, art, e, GLASS_SHOTGUN_WARNING, hard ? 5 : 4, 0.21, 6.6, 17);
	}
	if (t === 87) mines(st, art.target(st, e), 42, hard ? 1.18 : 1.0, 23, 2);
}

/* The Null Cantor records three spots from your route. Echoes fire across
 * that path while live fans aim at the player, then fire newest first in phase two. */
function cantor(st, art, e, t) {
	const c = st.crypt, { beat, phase2: hard } = c;
	const p = art.target(st, e);
	const seat = st.heroes?.findIndex((hero) => hero.p === p);
	// A seat switch is not movement along the previous hero's path.
	const previous = c.lastPlayerSeat === seat ? c.lastPlayerSpot : null;
	if (st.heroes) c.lastPlayerSeat = seat;
	// Phase two samples overlapping sets on its own clock. Three bursts per set
	// leave no extra gap between the last echo of one set and the next set's first.
	const echoAge = hard ? st.tick - c.phaseAt : t;
	const groupLength = 3 * CANTOR_PHASE_TWO_ECHO_SPACING;
	const echoTick = hard ? echoAge % groupLength : t;
	const echoGroup = hard ? Math.floor(echoAge / groupLength) : beat;
	if (echoTick <= 2 * CANTOR_ECHO_INTERVAL && echoTick % CANTOR_ECHO_INTERVAL === 0) {
		const index = echoTick / CANTOR_ECHO_INTERVAL;
		const dx = previous ? p.x - previous.x : 0, dy = previous ? p.y - previous.y : 0;
		const speed = Math.sqrt(dx * dx + dy * dy), angle = echoGroup * 0.67 + index * TAU / 3;
		const ux = speed > 0.025 ? -dy / speed : art.dcos(angle);
		const uy = speed > 0.025 ? dx / speed : art.dsin(angle);
		const fireAt = hard ? 62 + (2 - index) * CANTOR_PHASE_TWO_ECHO_SPACING : 64 + index * 18;
		mark(st, "echo", fireAt - echoTick, { x: p.x, y: p.y, ux, uy, speed: hard ? 8.7 : 7.5, dmg: 18 });
	}
	c.lastPlayerSpot = { x: p.x, y: p.y };
	const spokeAge = echoAge - 24;
	const fireSpokes = hard ? spokeAge >= 0 && spokeAge % CANTOR_PHASE_TWO_SPOKE_INTERVAL === 0 : t === 24 || t === 112;
	if (fireSpokes) {
		const slowVolley = hard && spokeAge % (3 * CANTOR_PHASE_TWO_SPOKE_INTERVAL) === CANTOR_PHASE_TWO_SPOKE_INTERVAL;
		spokes(st, art, e, hard ? 16 : 13, slowVolley ? 4.9 : 6.0, 16, beat * 0.4 + t * 0.03, beat % 8);
	}
	if (t === 37 || t === 82 || (hard && t === 110)) {
		markAimedFan(st, art, e, 24, hard ? 6 : 5, 0.22, 7.2, 17);
	}
	if (t === (hard ? 76 : 86) || t === 116) {
		let predicted = null;
		if (previous) {
			const vx = p.x - previous.x, vy = p.y - previous.y;
			const speed = Math.sqrt(vx * vx + vy * vy);
			// Forecast through the warning, capping the distance so a single
			// dash tick cannot throw the whole volley across the arena.
			const lead = speed ? Math.min(CANTOR_MINE_WARNING, CANTOR_MINE_MAX_LEAD / speed) : 0;
			predicted = { x: p.x + vx * lead, y: p.y + vy * lead };
		}
		mines(st, predicted || p, CANTOR_MINE_WARNING, 1.02, 23, hard || t === 116 ? 3 : 2);
	}
}

const CYCLES = {
	orrery: [...ORRERY_PERIODS, orrery],
	glassweaver: [165, GLASS_PHASE_TWO_CYCLE, glassweaver],
	cantor: [174, 170, cantor],
};

/* A mark hits the hero's hitbox (hitbox.js), not its whole body. */
function touches(mark, p) {
	const dx = p.x - mark.x, dy = p.y + HIT_DY - mark.y, reach = mark.r + HIT_R;
	if (mark.kind === "mine") return dx * dx + dy * dy < sq(reach);
	const vx = mark.tx - mark.x, vy = mark.ty - mark.y;
	const along = Math.max(0, Math.min(1, (dx * vx + dy * vy) / (vx * vx + vy * vy)));
	return sq(dx - along * vx) + sq(dy - along * vy) < sq(reach);
}

function resolve(st, art) {
	const { marks } = st.crypt;
	const hits = [];
	for (const m of marks) {
		if (m.at !== st.tick) continue;
		if (m.kind === "comb") {
			if (m.drift) {
				st.src = "crypt:diagonal";
				const dy = m.side === "top" ? 1 : -1;
				for (const x of m.points) art.shootAt(st, "e", x, m.edge, x + m.drift, m.edge + dy, m.speed, 20, 0.15, 220);
			} else {
				st.src = "crypt:curtain";
				const a = { left: 0, right: TAU / 2, top: TAU / 4, bottom: 3 * TAU / 4 }[m.side];
				for (const u of m.points) {
					art.shoot(st, "e", m.fromSide ? m.edge : u, m.fromSide ? u : m.edge, a, m.speed, 20, 0.15, 220);
				}
			}
		} else if (m.kind === "echo") {
			st.src = "crypt:echo";
			art.shootAt(st, "e", m.x, m.y, m.x + m.ux, m.y + m.uy, m.speed, m.dmg, 0.16, 130, CANTOR_ECHO_RANGE);
			art.shootAt(st, "e", m.x, m.y, m.x - m.ux, m.y - m.uy, m.speed, m.dmg, 0.16, 130, CANTOR_ECHO_RANGE);
		} else if (m.kind === "fan") {
			if (m.tx === undefined) fan(st, art, m, m.count, m.spread, m.speed, m.dmg);
			else {
				const dx = m.tx - m.x, dy = m.ty - m.y, length = Math.sqrt(dx * dx + dy * dy);
				st.src = "crypt:needles";
				art.fanAt(st, m, length ? dx / length : 1, length ? dy / length : 0, m.count, m.spread, m.speed, m.dmg);
			}
		} else hits.push(m);
	}
	if (hits.length) {
		const was = st.active;
		for (const i of art.livingIdx(st)) {
			art.useHero(st, i);
			const hit = hits.find((m) => touches(m, st.p));
			if (hit) art.hurtPlayer(st, hit.dmg, "crypt:" + hit.kind);
		}
		art.useHero(st, was);
	}
	st.crypt.marks = marks.filter((m) => st.tick < m.at + (m.linger ?? 8));
}

export function beginCryptTransition(st, e) {
	st.crypt.transitionUntil = st.tick + PHASE_BREAK;
	e.phase = 0;
	// The Glassweaver's walls still on their warning are called off: one would fire
	// through the break and still be crossing the room when phase two opens with its
	// own walls (owner, 2026-11-26). Walls already flying stay, and so do its mines and
	// needle fans; a fired wall's mark lingers a few ticks for drawing and stays too.
	if (e.form === "glassweaver") st.crypt.marks = st.crypt.marks.filter((m) => m.kind !== "comb" || m.at <= st.tick);
}

export function stepCrypt(st, e, art) {
	const c = st.crypt;
	if (!c.bounds) {
		const { x0, x1 } = st.rooms[e.room];
		const [top, bottom] = st.roomY[e.room];
		c.bounds = { x0, x1, y0: top, y1: bottom + 1 };
	}
	if (!c.phase2 && c.transitionUntil === null && e.hp * 2 <= e.maxHp) beginCryptTransition(st, e);
	if (c.transitionUntil !== null) {
		// Finish attacks already on the floor, even if a long warning outlasts the break.
		resolve(st, art);
		if (st.status !== "play" || st.tick < c.transitionUntil || c.marks.length) return;
		c.transitionUntil = null;
		c.phase2 = true;
		c.phaseAt = st.tick;
		e.phase = 2;
		c.age = -1; c.beat++;
	}
	const [normal, harder, act] = CYCLES[e.form], period = c.phase2 ? harder : normal;
	c.age++;
	if (c.age >= period) { c.age = 0; c.beat++; }
	act(st, art, e, c.age);
	resolve(st, art);
}

export function endCrypt(c) {
	c.marks = [];
	for (const tower of c.towers) tower.mode = "idle";
}
