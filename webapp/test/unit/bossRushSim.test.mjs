import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { BELL, FEN, PLAYER_SPEED, PYRE, SIDESTEP, TPS, WARDEN, createSim, pyreArmAngle, step } from "../../../bossrush/sim.js";

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

test("Sidestep dashes across the aim to the side you lean, toward the aim with no key, and looses a double arrow", () => {
	const st = encounter("warden");
	st.enemies[0].active = false;                     // nothing woken to hit
	const { x, y } = st.p, mp = st.p.mp, cost = st.stats.abilityCost;
	step(st, { ability: true, ax: 1, my: 1 });         // aiming right, leaning down
	const [arrow] = st.bullets;
	assert(arrow.power && arrow.vx > 0 && Math.abs(arrow.vy) < 1e-9, "the arrow goes where you aim");
	assert.equal(arrow.dmg, st.stats.dmg * SIDESTEP.mult);
	assert.equal(st.p.mp, mp - cost);
	for (let i = 0; i < SIDESTEP.ticks + 3; i++) step(st, {});
	assert(Math.abs(st.p.x - x) < 0.05, "straight across the aim");
	const walked = PLAYER_SPEED / TPS;                // the lean is also a step, on the tick you cast
	assert(Math.abs(st.p.y - y - SIDESTEP.dist - walked) < 0.01, `the dash carries ${SIDESTEP.dist} tiles (moved ${st.p.y - y})`);
	const dash = (input) => { const x0 = st.p.x, y0 = st.p.y; st.p.mp = st.stats.maxMp; step(st, { ability: true, ...input }); for (let i = 0; i < SIDESTEP.ticks + 3; i++) step(st, {}); return [st.p.x - x0, st.p.y - y0]; };
	const [fx, fy] = dash({ ax: 0, ay: -1 });         // no key held: toward the aim (up)
	assert(Math.abs(fx) < 0.01 && Math.abs(fy + SIDESTEP.dist) < 0.01, `no key dashes toward the aim (${fx}, ${fy})`);
	const [ax2, ay2] = dash({ ax: 0, ay: 1, my: 1 });  // a key held along the aim: that way
	assert(Math.abs(ax2) < 0.01 && Math.abs(ay2 - SIDESTEP.dist - PLAYER_SPEED / TPS) < 0.01, `along the aim (${ax2}, ${ay2})`);
});

test("the Ninja's counter is 2.0x with its Boss Rush kit", () => {
	assert.equal(encounter("warden", [], CHARACTERS.ninja.gear).stats.counterMult, 2);
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

test("from half health the Pyre turns a plus sign of shots, crossed only through each arm's gap", () => {
	const st = encounter("pyre");
	const [boss] = st.enemies;
	advance(st, () => boss.active);
	boss.hp = boss.maxHp * 0.45;
	advance(st, () => !!boss.arms);
	assert.deepEqual([...boss.arms.gaps].sort(), [...PYRE.arms.bands].sort(), "each arm's gap at a different distance");
	const quiet = () => { st.bullets = []; st.mortars = []; st.fires = []; };
	const pin = (k, d) => { const a = pyreArmAngle(boss, k); st.p.x = boss.x + Math.cos(a) * d; st.p.y = boss.y + Math.sin(a) * d; };
	const at0 = boss.arms.at;
	quiet(); step(st, {});
	assert.notEqual(boss.arms.at, at0, "it turns");
	let hits = 0;   // the test arena's enemies deal no damage, so count the arms' own hit clock
	const touch = () => { const h = boss.arms.hitAt; step(st, {}); if (boss.arms.hitAt !== h) hits++; };
	for (let i = 0; i < 2 * TPS; i++) { pin(1, boss.arms.gaps[1] + PYRE.arms.gap / 2); quiet(); touch(); }
	assert.equal(hits, 0, "the gap lets you through");
	const k = boss.arms.gaps.indexOf(Math.max(...boss.arms.gaps));
	hits = 0;
	for (let i = 0; i < TPS; i++) { pin(k, boss.r + 0.8); quiet(); touch(); }
	assert.equal(hits, Math.ceil(TPS / PYRE.arms.every), "touching an arm hurts, at most once per beat");
});
