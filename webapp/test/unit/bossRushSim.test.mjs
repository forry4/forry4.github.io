import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { BELL, FEN, FULL_DRAW_TICKS, TPS, WARDEN, createSim, step } from "../../../bossrush/sim.js";

function encounter(kind, objectives = [], gear = CHARACTERS.ranger.gear) {
	const border = "#".repeat(24);
	const dungeon = {
		id: kind, boss_kind: kind, seed: "lantern-test", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 8, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 12.5, y: 8.5 } },
		drops: {}, pickups: [], objectives, scale: { dmg: 0 },
	};
	return createSim(dungeon, gear);
}

function advance(st, until, input = () => ({})) {
	for (let tick = 0; tick < 2000 && !until(); tick++) step(st, input());
	assert(until(), "the encounter advanced");
}

const aimAt = (st, boss) => ({ fire: true, ax: boss.x - st.p.x, ay: boss.y - st.p.y });

test("Full Draw can be canceled free and uses the aim when the arrow releases", () => {
	const st = encounter("warden");
	step(st, { ability: true });
	assert.equal(st.p.drawUntil, st.tick + FULL_DRAW_TICKS);
	step(st, { mx: 1 });
	assert.equal(st.p.drawUntil, 0);
	assert.equal(st.p.mp, 120);
	step(st, { ability: true, fire: true, ax: 1 });
	advance(st, () => st.tick === st.p.drawUntil - 1, () => ({ fire: true, ax: 1 }));
	assert.equal(st.bullets.length, 0);
	assert.equal(st.p.mp, 120);
	step(st, { fire: true, ay: 1 });
	assert.equal(st.p.mp, 75);
	assert.equal(st.p.drawUntil, 0);
	const [arrow] = st.bullets;
	assert.equal(arrow.dmg, 240);
	assert(Math.abs(arrow.vx) < 0.001 && arrow.vy > 0);
});

const SEALS = [{ x: 8, y: 8.5 }, { x: 17, y: 5 }, { x: 17, y: 12 }];
const BELLS = [{ x: 12.5, y: 4.5 }, { x: 17.5, y: 7.5 }, { x: 15.5, y: 11.5 }, { x: 9.5, y: 11.5 }, { x: 7.5, y: 7.5 }];
const BRAZIERS = [{ x: 3.5, y: 3.5 }, { x: 20.5, y: 4.5 }, { x: 12.5, y: 14.5 }];
const ringAt = (st, bell) => st.bullets.push({ owner: "p", x: bell.x, y: bell.y, vx: 0, vy: 0, dmg: 1, r: 0.1, life: 5, pierce: 0, hit: [] });

const standIn = (st, spot) => { st.p.x = spot.x; st.p.y = spot.y; };

test("standing in the Warden's glowing seal when it ends chains him; missing it costs nothing", () => {
	const st = encounter("warden", SEALS);
	const [boss] = st.enemies;
	const w = st.warden;
	st.p.x = 3; st.p.y = 3;
	advance(st, () => !!w.glow);
	const first = w.glow.seal, hp = st.p.hp;
	advance(st, () => !w.glow);
	assert(!w.chainedUntil, "missed: no chains");
	assert.equal(st.p.hp, hp, "and no punishment");
	advance(st, () => !!w.glow);
	assert.notEqual(w.glow.seal, first, "never the same seal twice");
	advance(st, () => !w.glow, () => { standIn(st, w.seals[w.glow?.seal ?? 0]); return {}; });
	assert(w.chainedUntil > st.tick);
	assert(!st.bullets.some((b) => b.owner === "e") && !st.mortars.length, "his attacks are cleared");
	const age = w.age;
	step(st, {});
	assert.equal(w.age, age, "bound: he does nothing");
	boss.fx = 1; boss.fy = 0; st.p.x = boss.x + 3; st.p.y = boss.y;   // in front of him
	const before = boss.hp;
	advance(st, () => boss.hp < before, () => aimAt(st, boss));
	const chainedHit = before - boss.hp;
	advance(st, () => !(w.chainedUntil > st.tick));
	const mid = boss.hp;
	advance(st, () => boss.hp < mid, () => { boss.fx = 1; boss.fy = 0; return aimAt(st, boss); });
	assert.equal(chainedHit, (mid - boss.hp) * WARDEN.bound, "double damage in the chains");
});

test("the Warden's back takes extra damage, and his front takes plain damage", () => {
	const st = encounter("warden", SEALS);
	const [boss] = st.enemies;
	const hitFrom = (dx) => {
		st.p.x = boss.x + dx; st.p.y = boss.y;
		st.bullets = [];
		const before = boss.hp;
		advance(st, () => boss.hp < before, () => { boss.fx = 1; boss.fy = 0; return aimAt(st, boss); });
		return before - boss.hp;
	};
	const front = hitFrom(3), back = hitFrom(-3);
	assert.equal(back, Math.round(front * WARDEN.back * 10) / 10);
});

test("a glowing bell, shot, rings and its peal hits the Bellkeeper; a dark bell lets shots through", () => {
	const st = encounter("bellkeeper", BELLS);
	const [boss] = st.enemies;
	const b = st.bellkeeper;
	advance(st, () => b.bells.some((bell) => bell.litUntil > st.tick));
	assert.equal(b.bells.filter((bell) => bell.litUntil > st.tick).length, 1);
	const dark = b.bells.find((bell) => !(bell.litUntil > st.tick));
	ringAt(st, dark);
	step(st, {});
	assert(st.bullets.some((x) => x.owner === "p" && x.dmg === 1), "a dark bell does not stop the shot");
	st.bullets = st.bullets.filter((x) => x.owner !== "p");
	const bell = b.bells.find((x) => x.litUntil > st.tick), before = boss.hp;
	ringAt(st, bell);
	step(st, {});
	assert(!bell.litUntil, "rung");
	assert.equal(before - boss.hp, BELL.peal);
	advance(st, () => b.bells.some((x) => x.litUntil > st.tick));
	const missed = b.bells.find((x) => x.litUntil > st.tick), hp = st.p.hp, bossHp = boss.hp;
	advance(st, () => !(missed.litUntil > st.tick));
	assert.equal(st.p.hp, hp, "a bell that fades costs nothing");
	assert.equal(boss.hp, bossHp);
});

test("from half health two bells light, and ringing both doubles the second peal", () => {
	const st = encounter("bellkeeper", BELLS);
	const [boss] = st.enemies;
	const b = st.bellkeeper;
	advance(st, () => b.started);
	boss.hp = boss.maxHp * 0.45;
	advance(st, () => b.bells.filter((bell) => bell.litUntil > st.tick).length === 2);
	const [one, two] = b.bells.filter((bell) => bell.litUntil > st.tick);
	let before = boss.hp;
	ringAt(st, one); step(st, {});
	assert.equal(before - boss.hp, BELL.peal);
	before = boss.hp;
	ringAt(st, two); step(st, {});
	assert.equal(before - boss.hp, BELL.peal * BELL.chord);
});

test("the Cinderwake can always be shot, and a lantern walked into a dark brazier blasts it", () => {
	const st = encounter("cinderwake", BRAZIERS);
	const [boss] = st.enemies;
	const c = st.cinderwake;
	st.p.x = boss.x - 2.5; st.p.y = boss.y;
	advance(st, () => boss.hp < boss.maxHp, () => aimAt(st, boss));
	assert.equal(boss.phase, 1, "never under the water");
	advance(st, () => !!c.lantern);
	st.p.x = c.lantern.x; st.p.y = c.lantern.y;
	step(st, {});
	assert(c.carrying && !c.lantern);
	st.p.x = boss.x - 3; st.p.y = boss.y;
	st.bullets = st.bullets.filter((b) => b.owner !== "p");
	advance(st, () => st.bullets.some((b) => b.owner === "p"), () => aimAt(st, boss));
	assert(c.carrying, "you can still shoot while you carry it");
	const [bz] = c.braziers;
	const before = boss.hp;
	st.p.x = bz.x; st.p.y = bz.y;
	step(st, {});
	assert(!c.carrying && bz.lit);
	assert(before - boss.hp >= FEN.blast, "the brazier's fire hits it");
});

test("a lit brazier is full until it burns down, so the next lantern goes to another", () => {
	const st = encounter("cinderwake", BRAZIERS);
	const c = st.cinderwake;
	const [bz] = c.braziers;
	const deliver = () => {
		advance(st, () => !!c.lantern);
		st.p.x = c.lantern.x; st.p.y = c.lantern.y;
		step(st, {});
		st.p.x = bz.x; st.p.y = bz.y;
		step(st, {});
	};
	deliver();
	assert(bz.lit);
	const lit = bz.litUntil;
	deliver();
	assert(c.carrying, "a full brazier does not take it");
	assert.equal(bz.litUntil, lit);
	advance(st, () => !c.carrying);
	assert(bz.lit && st.tick >= lit && bz.litUntil > lit, "once it burns down it takes the lantern");
});
