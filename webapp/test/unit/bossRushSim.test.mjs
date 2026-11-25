import assert from "node:assert/strict";
import test from "node:test";
import { CHARACTERS } from "../../../bossrush/loadouts.js";
import { ABILITY_COOLDOWN, BELL, CRACK, FEN, PLAYER_SPEED, PYRE, SIDESTEP, TPS, WARDEN, createSim, inCrack, pyreArmAngle, step } from "../../../bossrush/sim.js";

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

test("every boss has a full second between the seal and its attack schedule", () => {
	for (const kind of ["tidewarden", "breach", "pyre", "orrery", "glassweaver", "cantor", "warden", "bellkeeper", "cinderwake"]) {
		const st = encounter(kind);
		const [boss] = st.enemies;
		step(st, {});
		assert.equal(boss.startsAt, st.tick + TPS, kind);
		const { x, y, modeT } = boss;
		while (st.tick + 1 < boss.startsAt) step(st, {});
		assert.deepEqual([boss.x, boss.y, boss.modeT, st.bullets.length, st.mortars.length], [x, y, modeT, 0, 0], kind);
		assert(!(st.crypt?.marks.length), kind);
		step(st, {});
		assert.equal(st.tick, boss.startsAt, kind);
		if (st.crypt) assert.equal(st.crypt.age, 0, kind);
	}
});

test("Rift bosses stop at half HP and ignore hits until phase two starts", () => {
	for (const kind of ["tidewarden", "breach", "pyre"]) {
		const st = encounter(kind);
		const [boss] = st.enemies;
		const hit = () => st.bullets.push({ owner: "p", x: boss.x, y: boss.y, vx: 0, vy: 0, dmg: boss.maxHp, r: 0.1, life: 2, pierce: 0, hit: [] });
		step(st, {});
		hit();
		step(st, {});
		assert.equal(boss.hp, boss.maxHp, kind);
		advance(st, () => st.tick === boss.startsAt);
		hit(); hit();
		step(st, {});
		assert.equal(boss.hp, boss.maxHp / 2, kind);
		assert.equal(boss.phase, 0, kind);
		while (boss.modeT > 1) {
			hit();
			step(st, {});
			assert.equal(boss.hp, boss.maxHp / 2, kind);
		}
		step(st, {});
		assert.equal(boss.phase, 2, kind);
		hit();
		step(st, {});
		assert.equal(boss.hp, 0, kind);
	}
});

test("Glassweaver curtains launch from the walls farthest from the safe spot in both phases", () => {
	for (const hard of [false, true]) {
		const pairs = new Set();
		for (const x of [3, 21]) for (const y of [3, 14]) for (const seed of [0, 1, 2, 3]) {
			const st = encounter("glassweaver");
			st.rng = seed;
			Object.assign(st.p, { x, y });
			if (hard) st.enemies[0].hp = st.enemies[0].maxHp / 2;
			const crypt = st.crypt;
			advance(st, () => crypt.lastGap);
			assert.equal(crypt.phase2, hard);
			const gap = crypt.lastGap;
			const { x0, x1, y0, y1 } = crypt.bounds;
			const [across, down] = crypt.marks.filter((mark) => mark.kind === "comb");
			assert.equal(across.side, gap.x < (x0 + x1) / 2 ? "right" : "left");
			assert.equal(down.side, gap.y < (y0 + y1) / 2 ? "bottom" : "top");
			assert.equal(across.gap, gap.y);
			assert(Math.abs(down.gap + down.drift * Math.abs(gap.y - down.edge) - gap.x) < 1e-9);
			assert(down.gap - down.half >= x0 && down.gap + down.half <= x1);
			pairs.add(across.side + down.side);
		}
		assert.equal(pairs.size, 4);
	}
});

test("Null Cantor echo shots end at six tiles, including when slowed", () => {
	for (const phase2 of [false, true]) for (const slow of [false, true]) {
		const st = encounter("cantor");
		const [boss] = st.enemies;
		if (phase2) boss.hp = boss.maxHp / 2;
		advance(st, () => boss.phase === (phase2 ? 2 : 1) && st.crypt.age === 0);
		Object.assign(st.p, { x: 12.5, y: 11 });
		if (slow) Object.assign(st, {
			slowUntil: st.tick + 130, slowAt: { x: 12.5, y: 8.5 }, slowR: 8, slowF: 0.6,
		});
		const origin = { x: 12.5, y: 8.5 };
		st.crypt.marks.push({ kind: "echo", from: st.tick, at: st.tick + 1, ...origin,
			ux: 1, uy: 0, speed: phase2 ? 8.7 : 7.5, dmg: 18 });
		step(st, {});
		const echoes = st.bullets.filter((b) => b.src === "crypt:echo");
		assert.equal(echoes.length, 2);
		advance(st, () => echoes.every((echo) => !st.bullets.includes(echo)));
		assert(Math.abs(echoes[0].x - (origin.x + 6)) < 1e-9);
		assert(Math.abs(echoes[1].x - (origin.x - 6)) < 1e-9);
	}
});

test("Sidestep dashes the way your keys point (toward the aim with none), and looses a double arrow at the aim", () => {
	const st = encounter("warden");
	st.enemies[0].active = false;                     // nothing woken to hit
	const { x, y } = st.p, mp = st.p.mp, cost = st.stats.abilityCost;
	step(st, { ability: true, ax: 1, my: 1 });         // aiming right, holding down
	const [arrow] = st.bullets;
	assert(arrow.power && arrow.vx > 0 && Math.abs(arrow.vy) < 1e-9, "the arrow goes where you aim");
	assert.equal(arrow.dmg, st.stats.dmg * SIDESTEP.mult);
	assert.equal(st.p.mp, mp - cost);
	for (let i = 0; i < SIDESTEP.ticks + 3; i++) step(st, {});
	assert(Math.abs(st.p.x - x) < 0.05, "straight down, the way the key points");
	const walked = PLAYER_SPEED / TPS;                // the lean is also a step, on the tick you cast
	assert(Math.abs(st.p.y - y - SIDESTEP.dist - walked) < 0.01, `the dash carries ${SIDESTEP.dist} tiles (moved ${st.p.y - y})`);
	const dash = (input) => { const x0 = st.p.x, y0 = st.p.y; st.p.mp = st.stats.maxMp; st.p.abilityCd = 0; step(st, { ability: true, ...input }); for (let i = 0; i < SIDESTEP.ticks + 3; i++) step(st, {}); return [st.p.x - x0, st.p.y - y0]; };
	const [fx, fy] = dash({ ax: 0, ay: -1 });         // no key held: toward the aim (up)
	assert(Math.abs(fx) < 0.01 && Math.abs(fy + SIDESTEP.dist) < 0.01, `no key dashes toward the aim (${fx}, ${fy})`);
	const [ax2, ay2] = dash({ ax: 0, ay: 1, my: 1 });  // a key held along the aim: that way
	assert(Math.abs(ax2) < 0.01 && Math.abs(ay2 - SIDESTEP.dist - PLAYER_SPEED / TPS) < 0.01, `along the aim (${ax2}, ${ay2})`);
	const [dgx, dgy] = dash({ ax: 1, ay: 0, mx: -1, my: 1 });   // two keys: their diagonal, whatever the aim
	assert(dgx < 0 && dgy > 0 && Math.abs(dgx + dgy) < 0.01, `diagonal (${dgx}, ${dgy})`);
	assert(Math.abs(Math.hypot(dgx, dgy) - SIDESTEP.dist - PLAYER_SPEED / TPS) < 0.01, `the diagonal carries the full dash (${Math.hypot(dgx, dgy)})`);
	// Owner's report: holding D while aiming down-right dashed UP. One key is its own way, whatever the aim.
	const s2 = Math.SQRT1_2;
	for (const [ax, ay] of [[s2, s2], [s2, -s2], [0, 1], [-s2, s2]]) {
		const [rx, ry] = dash({ ax, ay, mx: 1 });
		assert(Math.abs(ry) < 0.01 && Math.abs(rx - SIDESTEP.dist - PLAYER_SPEED / TPS) < 0.01, `D aiming (${ax.toFixed(2)}, ${ay.toFixed(2)}) dashed (${rx.toFixed(2)}, ${ry.toFixed(2)})`);
	}
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
	const quiet = () => { st.bullets = []; st.mortars = []; };
	const pin = (k, d) => { const a = pyreArmAngle(boss, k); st.p.x = boss.x + Math.cos(a) * d; st.p.y = boss.y + Math.sin(a) * d; };
	// First a warning: laid out, still and harmless, for PYRE.arms.warn ticks.
	const warnStart = st.tick, still = boss.arms.at, k0 = boss.arms.gaps.indexOf(Math.max(...boss.arms.gaps));
	st.fires = [{ x: 3, y: 3, r: 1, until: st.tick + 9999 }];
	while (boss.phase !== 2) { pin(k0, boss.r + 0.8); quiet(); step(st, {}); }
	assert.equal(st.fires.length, 0, "phase 2 starts with no fire on the ground");
	assert.equal(boss.arms.at, still, "the warning does not turn");
	assert.equal(boss.arms.hitAt, -1e9, "nor hurt");
	assert(st.tick - warnStart >= PYRE.arms.warn - 1, `the warning lasts ${PYRE.arms.warn} ticks (${st.tick - warnStart})`);
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

test("an open crack is a slow, painful floor for the player, never a shove to the bank", () => {
	const border = "#".repeat(24);
	const dungeon = {
		id: "fracture", boss_kind: "breach", seed: "crack-test", width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 10.5, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 20.5, y: 3.5 } },
		cracks: [{ room: 0, group: 0, tiles: Array.from({ length: 15 }, (_, i) => [12, i + 1]) }],
		drops: {}, pickups: [], objectives: [], scale: { dmg: 1 },
	};
	const st = createSim(dungeon, CHARACTERS.ranger.gear);
	st.enemies[0].dormant = true;                     // only the crack can hurt here
	const crack = st.cracks[0];
	advance(st, () => crack.open);
	const hp0 = st.p.hp;
	advance(st, () => inCrack(st), () => ({ mx: 1 }));
	assert(st.p.hp < hp0, "the first bite lands on the step in");
	const x0 = st.p.x;
	step(st, { mx: 1 });
	const stride = st.p.x - x0;
	assert(Math.abs(stride - PLAYER_SPEED * CRACK.slow / TPS) < 1e-9, `wading is slow (${stride} a tick)`);
	advance(st, () => st.p.x > 13.6, () => ({ mx: 1 }));
	assert(crack.open, "crossed while it was still open");
	assert(hp0 - st.p.hp > CRACK.dmg, `wading costs more than one bite (${hp0 - st.p.hp})`);
	// Standing on a bridge as it fails: you stay where you are and start to burn.
	advance(st, () => !crack.open);
	advance(st, () => st.p.x < 12.5, () => ({ mx: -1 }));
	const at = { x: st.p.x, y: st.p.y }, hp1 = st.p.hp;
	advance(st, () => crack.open);
	assert.deepEqual({ x: st.p.x, y: st.p.y }, at, "a failing bridge does not throw you");
	step(st, {});                                     // the bite comes on the next tick
	assert(st.p.hp < hp1, "and it hurts");
	// The fissure's permanent void wades the same way.
	const solid = createSim({ ...dungeon, cracks: [],
		tiles: dungeon.tiles.map((row, y) => y === 0 || y === 16 ? row : row.slice(0, 12) + "x" + row.slice(13)) }, CHARACTERS.ranger.gear);
	solid.enemies[0].dormant = true;
	const hp2 = solid.p.hp;
	advance(solid, () => solid.p.x > 13.6, () => ({ mx: 1 }));
	assert(solid.p.hp < hp2 - CRACK.dmg, `the fissure hurts to wade (${hp2 - solid.p.hp})`);
	assert(solid.enemies.every((e) => !inCrack(solid, e)), "enemies stay out of it");
});

test("every ability waits one second between casts, the Ninja's counter included", () => {
	for (const id of Object.keys(CHARACTERS)) {
		const st = encounter("warden", [], CHARACTERS[id].gear);
		st.enemies[0].active = false;
		assert.equal(ABILITY_COOLDOWN, TPS);
		const cast = () => { st.p.mp = st.stats.maxMp; step(st, { ability: true, ax: 1, ay: 0 }); return st.p.mp < st.stats.maxMp; };
		assert(cast(), `${id} casts`);
		for (let i = 0; i < 20; i++) step(st, {});
		assert(!cast(), `${id} cannot cast again inside a second`);
		for (let i = 0; i < TPS; i++) step(st, {});
		assert(cast(), `${id} casts again after a second`);
	}
});

test("a bullet slowed by the Paladin's field still travels its full range", () => {
	const st = encounter("warden");
	st.enemies[0].active = false;
	const life = 120, speed = 3;
	st.slowUntil = st.tick + 10_000; st.slowAt = { x: 12, y: 8.5 }; st.slowR = 30; st.slowF = 0.45;   // a field over the whole room
	st.bullets.push({ owner: "e", x: 2, y: 2, vx: speed, vy: 0, dmg: 0, r: 0.1, life, src: "boss:sweep", hit: [] });
	const b = st.bullets[0];
	let last = b.x;
	for (let t = 0; t < 1000 && st.bullets.includes(b); t++) { last = b.x; step(st, {}); }
	assert(!st.bullets.includes(b), "it does run out");
	const travelled = last - 2, range = speed * life / TPS;
	assert(Math.abs(travelled - range) < speed / TPS * 1.5, `travelled ${travelled.toFixed(2)} of its ${range} tiles`);
});

test("the Paladin's Boss Rush field deals 10 damage per pulse", () => {
	const st = encounter("warden", [], CHARACTERS.paladin.gear);
	step(st, { ability: true, ax: 1 });
	assert.equal(st.slowDmg, 10);
});

test("which Fracture bridge fails first is a coin flip per run, and fixed for a run", () => {
	const border = "#".repeat(24);
	const make = (seed) => createSim({
		id: "fracture", boss_kind: "breach", seed, width: 24, height: 17,
		tiles: [border, ...Array(15).fill("#" + ".".repeat(22) + "#"), border],
		rooms: [{ kind: "boss", x0: 1, x1: 23 }], start: { x: 6.5, y: 8.5 },
		enemies: { boss: { type: "boss", room: 0, x: 20.5, y: 3.5 } },
		cracks: [{ room: 0, group: 0, tiles: [[12, 3]] }, { room: 0, group: 1, tiles: [[12, 12]] }],
		drops: {}, pickups: [], objectives: [], scale: { dmg: 0 },
	}, CHARACTERS.ranger.gear);
	// A crack counts UP toward opening, so the one that starts further along fails first.
	const topFirst = (seed) => { const [top, bottom] = make(seed).cracks; return top.t > bottom.t; };
	let tops = 0;
	for (let i = 0; i < 400; i++) {
		const seed = `run${i * 7919}:fracture`;
		assert.equal(topFirst(seed), topFirst(seed), "the same run always breaks the same bridge first");
		if (topFirst(seed)) tops++;
	}
	assert(tops > 160 && tops < 240, `the top bridge breaks first on ${tops} of 400 runs`);
});

test("The exit portal opens right where the boss fell", () => {
	const st = encounter("warden");
	const boss = st.enemies[0];
	boss.hp = 1;
	advance(st, () => !!st.portal, () => aimAt(st, boss));
	assert(Math.hypot(st.portal.x - boss.x, st.portal.y - boss.y) < 1e-9, `portal at (${st.portal.x}, ${st.portal.y}), boss fell at (${boss.x}, ${boss.y})`);
});

test("Simon: 90 HP, 140 MP, 2 Defense, and a ring of ten 70-damage shots, one on the aim", () => {
	const st = encounter("warden", [], CHARACTERS.simon.gear), s = st.stats;
	assert.deepEqual([s.maxHp, s.maxMp, s.def, s.dmg, s.shots, s.range], [90, 140, 2, 70, 10, 3]);
	assert.equal(s.range, encounter("warden", [], CHARACTERS.paladin.gear).stats.range - 1, "a tile less than the Paladin");
	assert.equal(s.dmg, encounter("warden", [], CHARACTERS.diviner.gear).stats.dmg, "the Diviner's damage a shot");
	st.enemies[0].active = false;
	step(st, { fire: true, ax: 0, ay: 1 });
	const ring = st.bullets.filter((b) => b.owner === "p");
	assert.equal(ring.length, 10);
	const angles = ring.map((b) => Math.atan2(b.vy, b.vx)).sort((x, y) => x - y);
	angles.forEach((x, i) => i && assert(Math.abs(x - angles[i - 1] - Math.PI / 5) < 1e-9, "36 degrees apart"));
	assert(ring.some((b) => Math.abs(b.vx) < 1e-9 && b.vy > 0), "one shot goes straight at the aim");
	assert(ring.every((b) => b.dmg === 70));
});

test("Simon's Haste: 20% faster for three seconds, then back to normal", () => {
	const walk = (cast) => {
		const st = encounter("warden", [], CHARACTERS.simon.gear);
		if (cast) step(st, { ability: true });
		const x0 = st.p.x;
		for (let t = 0; t < 20; t++) step(st, { mx: 1 });
		return { st, d: st.p.x - x0 };
	};
	const plain = walk(false).d, { st, d } = walk(true);
	assert.ok(Math.abs(d / plain - 1.2) < 0.01, `hasted ${d} vs ${plain}`);
	for (let t = 0; t < 3 * 60; t++) step(st, {});
	assert.ok(!(st.p.hasteUntil > st.tick), "it wears off");
});
