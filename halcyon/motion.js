/* Drawing history lives beside the scene. It advances with the sim even when the
 * browser skips frames, and never affects collision, damage or the event queue. */
export const DEFEAT_TICKS = 24;
const DOOR_TICKS = 12;
export const clamp01 = (n) => Math.max(0, Math.min(1, n));

const LEFT = { x: -1, y: 0 }, RIGHT = { x: 1, y: 0 };
const UP = { x: 0, y: -1 }, DOWN = { x: 0, y: 1 };

/* Let the previous facing win near a diagonal. Small mouse changes and rounding
 * in each movement axis should not flip the entire silhouette back and forth. */
export function spriteFacing(direction, previous = null) {
	if (!direction || (!direction.x && !direction.y)) return previous;
	const { x, y } = direction, horizontal = Math.abs(x), vertical = Math.abs(y);
	const margin = previous ? (previous.x ? 1 / 1.2 : 1.2) : 1;
	if (horizontal > vertical * margin) return x < 0 ? LEFT : RIGHT;
	return y < 0 ? UP : DOWN;
}

export function createSceneMotion(st) {
	const bodies = new WeakMap(), arrivals = new WeakMap(), doors = new Map();
	let sealed = st.sealed;
	const record = (body) => {
		let m = bodies.get(body);
		if (!m) {
			m = { x: body.x, y: body.y, facing: DOWN, travel: 0, pace: 0,
				tele: body.tele || 0, releasedAt: -Infinity, defeatedAt: null };
			bodies.set(body, m);
		}
		const dx = body.x - m.x, dy = body.y - m.y, distance = Math.hypot(dx, dy);
		// A teleport has a destination but no walk between the two points.
		if (distance > 0.001 && distance < 0.45) {
			m.travel += distance;
			m.facing = spriteFacing({ x: dx, y: dy }, m.facing);
			m.pace = Math.min(1, distance / 0.045);
		} else {
			m.pace = Math.max(0, m.pace - 0.24);
		}
		if (m.tele > 0 && !(body.tele > 0) && body.active) m.releasedAt = st.tick;
		if (body.hp <= 0 && m.defeatedAt === null) m.defeatedAt = st.tick;
		m.x = body.x; m.y = body.y; m.tele = body.tele || 0;
	};
	const advance = () => {
		record(st.p);
		for (const e of st.enemies || []) {
			if (e.hp > 0 || bodies.get(e)?.defeatedAt === null) record(e);
		}
		if (st.sealed !== sealed) {
			if (sealed >= 0) doors.set(sealed, { at: st.tick, opening: true });
			if (st.sealed >= 0) doors.set(st.sealed, { at: st.tick, opening: false });
			sealed = st.sealed;
		}
	};
	advance();
	return {
		advance,
		body: (obj) => bodies.get(obj),
		age(obj, tick) {
			if (!arrivals.has(obj)) arrivals.set(obj, tick);
			return tick - arrivals.get(obj);
		},
		door(room, tick) {
			const move = doors.get(room);
			if (!move) return sealed === room ? 1 : 0;
			const p = clamp01((tick - move.at + 1) / DOOR_TICKS);
			return move.opening ? (1 - p) ** 2 : 1 - (1 - p) ** 2;
		},
	};
}

/* Four walking poses with planted beats between steps. The cadence follows ground
 * distance, so blocked movement stops and slow enemies take fewer steps. */
export function gait(m, strideLength) {
	if (!m?.pace) return 0;
	const phase = Math.floor(m.travel / strideLength * 4) % 4;
	return (phase === 1 ? 1 : phase === 3 ? -1 : 0) * m.pace;
}
