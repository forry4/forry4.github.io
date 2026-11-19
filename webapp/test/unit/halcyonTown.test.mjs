/* Halcyon Rift's town (halcyon/town.js): every place can be walked to and used,
 * the solid ones block, and coming back out of a portal does not put you back in it. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { createTown, stepTown, setTownGear, postDps, POSTS, STATIONS, REALMS, SPAWN, standAt, distanceTo } from "../../../halcyon/town.js";

/* Walk straight at a point, one tick at a time, until `stop(st)` or `limit` ticks. */
function walk(st, to, stop, limit = 600) {
	for (let i = 0; i < limit && !stop(st); i++) {
		const dx = to.x - st.p.x, dy = to.y - st.p.y;
		stepTown(st, { mx: Math.abs(dx) > 0.05 ? Math.sign(dx) : 0, my: Math.abs(dy) > 0.05 ? Math.sign(dy) : 0 });
	}
	return st;
}

test("every station can be reached from the spawn and reports itself as near", () => {
	assert.ok(STATIONS.some((s) => s.kind === "vault") && STATIONS.some((s) => s.kind === "forge"));
	assert.equal(STATIONS.filter((s) => s.kind === "portal").length, REALMS.length, "one portal per realm");
	for (const s of STATIONS) {
		const to = s.kind === "portal" || s.kind === "dream" ? { x: s.x, y: s.y } : standAt(s.id);   // standAt(portal) is just out of reach
		const st = walk(createTown(), to, (t) => t.near === s.id);
		assert.equal(st.near, s.id, `${s.id}: stopped at ${st.p.x.toFixed(2)},${st.p.y.toFixed(2)}`);
	}
});

test("the vault and the forge are solid; nothing stands inside a wall or a station", () => {
	for (const s of STATIONS.filter((x) => x.solid)) {
		const st = walk(createTown(), { x: s.x, y: s.y }, () => false, 400);
		assert.ok(Math.abs(st.p.x - s.x) >= s.hw + st.p.r - 1e-9 || Math.abs(st.p.y - s.y) >= s.hh + st.p.r - 1e-9, s.id);
	}
	const st = walk(createTown(), { x: -5, y: -5 }, () => false, 600);
	assert.ok(st.p.x > 1 && st.p.y > 1, "the plaza's wall holds");
});

test("the spawn is near nothing, and stepping out of a portal does not put you back in it", () => {
	const st = stepTown(createTown(SPAWN), {});
	assert.equal(st.near, null);
	for (const r of REALMS) {
		const back = stepTown(createTown(standAt(`realm:${r.id}`)), {});
		assert.notEqual(back.near, `realm:${r.id}`);
		const portal = STATIONS.find((s) => s.id === `realm:${r.id}`);
		assert.ok(distanceTo(back.p, portal) < 3, "but it is close by");
	}
});

/* Stand south-west of a post and hold the trigger at it for `ticks`. */
function practice(base, ticks = 3 * 60) {
	const post = POSTS[0];
	const st = createTown({ x: post.x - 2.5, y: post.y });
	if (base) setTownGear(st, [{ base_id: base, tier: 1 }]);
	for (let i = 0; i < ticks; i++) stepTown(st, { ax: post.x - st.p.x, ay: post.y - st.p.y, fire: true });
	return { st, post: st.posts[0] };
}

test("the town can be shot in: arrows hit a practice post and it shows what it took", () => {
	const { st, post } = practice("longbow");
	assert.ok(post.hits.length >= 3, `${post.hits.length} hits`);
	assert.ok(post.hits.every((h) => Number.isInteger(h.dmg) && h.dmg === st.stats.dmg));
	assert.equal(postDps(st, post), Math.round(post.hits.reduce((a, h) => a + h.dmg, 0) / 3));
	assert.ok(st.floats.length > 0, "a number floats off the post");
	// The posts and the walls stop arrows: nothing flies forever.
	for (let i = 0; i < 200; i++) stepTown(st, {});
	assert.equal(st.bullets.length, 0);
	assert.equal(postDps(st, post), 0, "and the reading falls back to nothing when you stop");
});

test("each weapon fires in town as it does in a rift: the shortbow's pair, the longbow's single heavy arrow", () => {
	const short = practice("shortbow", 1).st, long = practice("longbow", 1).st;
	assert.equal(short.bullets.length, 2);
	assert.equal(long.bullets.length, 1);
	assert.ok(long.bullets[0].pierce === 0 && long.bullets[0].dmg > short.bullets[0].dmg);
});

test("nobody can stand inside a practice post", () => {
	for (const q of POSTS) {
		const st = walk(createTown({ x: q.x, y: q.y - 2 }), { x: q.x, y: q.y }, () => false, 300);
		assert.ok(Math.hypot(st.p.x - q.x, st.p.y - q.y) >= q.r + st.p.r - 1e-9, q.id);
	}
});

test("the Dream Rift is walked onto like a realm portal: nothing stops you on it", () => {
	const s = STATIONS.find((x) => x.id === "dream");
	assert.equal(s.solid, false);
	const st = createTown({ x: s.x + 2, y: s.y });
	for (let i = 0; i < 40 && st.p.x > s.x; i++) stepTown(st, { mx: -1, my: 0 });
	assert.ok(st.p.x <= s.x + 0.05, `walked over its centre, at ${st.p.x}`);
	assert.equal(st.near, "dream");
});

test("what lies on the town's ground is in reach before any station, and only close by", () => {
	const st = createTown();
	st.floor = [{ key: "a", x: st.p.x + 0.5, y: st.p.y }, { key: "b", x: st.p.x + 5, y: st.p.y }];
	stepTown(st, {});
	assert.equal(st.nearFloor, "a");
	st.floor = [{ key: "b", x: st.p.x + 5, y: st.p.y }];
	stepTown(st, {});
	assert.equal(st.nearFloor, null);
});
