/* THE UNIQUE ROSTER (owner's list, 2026-11-19): each unique's effect, driven through
 * the real sim on a real dungeon from halcyon/dungeon.py. */
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createSim, step, statsFor, fingerprint, UNIQUE, TPS, COUNTER_WINDOW, STARFALL_DELAY, abilityCost } from "../../../halcyon/sim.js";
import { createTown, stepTown, setTownGear } from "../../../halcyon/town.js";

const A = JSON.parse(readFileSync(new URL("./fixtures/halcyon-dungeon-unit-a.json", import.meta.url)));
const KIT = {
	ranger: [{ base_id: "shortbow", tier: 1 }, { base_id: "leather_vest", tier: 1 }, { base_id: "volley_quiver", tier: 1 }],
	paladin: [{ base_id: "mace", tier: 1 }, { base_id: "plate_armor", tier: 1 }, { base_id: "stillness_orb", tier: 1 }],
	diviner: [{ base_id: "wand", tier: 1 }, { base_id: "seer_robes", tier: 1 }, { base_id: "star_tome", tier: 1 }],
	ninja: [{ base_id: "shuriken", tier: 1 }, { base_id: "shadow_garb", tier: 1 }, { base_id: "mirror_charm", tier: 1 }],
};
const SLOT = { weapon: 0, armor: 1, ability: 2 };
/* A class's kit with one item swapped in (or a ring added). */
function kit(cls, base_id, slot = null, tier = 1) {
	const g = KIT[cls].map((x) => ({ ...x }));
	if (slot == null) g.push({ base_id, tier }); else g[SLOT[slot]] = { base_id, tier };
	return g;
}
/* A sim with one still target `d` tiles east of the player (more if `n`), and nothing else. */
function range(gear, cls, { d = 2, n = 1, gap = 0.7 } = {}) {
	const st = createSim(A, gear, { class_id: cls });
	const proto = st.enemies.find((e) => e.type === "chaser");
	st.enemies = [];
	for (let i = 0; i < n; i++)
		st.enemies.push({ ...proto, id: `t${i}`, room: null, x: st.p.x + d + i * gap, y: st.p.y, hp: 10000, maxHp: 10000,
			active: true, cd: 1e9, scd: 1e9, tele: 0, ward: 0 });
	st.p.hp = st.stats.maxHp = 100000; st.p.low = st.p.hp;
	st.hold = () => { for (const e of st.enemies) { e.x = e.homeX; e.y = e.homeY; } };
	for (const e of st.enemies) { e.homeX = e.x; e.homeY = e.y; }
	return st;
}
const run = (st, ticks, input = {}) => { for (let i = 0; i < ticks; i++) { step(st, input); st.hold?.(); } };
const fire = { fire: true, ax: 1, ay: 0 };
const enemyShot = (st, dmg = 30) => st.bullets.push({ owner: "e", x: st.p.x, y: st.p.y, vx: 0, vy: 0, dmg, r: 0.1, life: 5, pierce: 0, hit: [] });

test("Ember Loop: a weapon hit sets the target burning, which ticks and is refreshed, not stacked", () => {
	const st = range(kit("ranger", "ember_loop"), "ranger");
	assert.equal(st.stats.burn, UNIQUE.burn.dmg);
	while (!st.enemies[0].burnUntil) run(st, 1, fire);
	const e = st.enemies[0], hp = e.hp;
	run(st, UNIQUE.burn.every);
	assert.equal(hp - e.hp, st.stats.burn, "one burn tick, no shots in between");
	run(st, UNIQUE.burn.last);
	const after = e.hp; run(st, UNIQUE.burn.every * 2);
	assert.equal(e.hp, after, "and it goes out");
});

test("Miser's Coil: abilities cost less, and it costs HP", () => {
	const a = statsFor(KIT.ranger), b = statsFor(kit("ranger", "misers_coil"));
	assert.equal(b.abilityCost, a.abilityCost - UNIQUE.coilCut);
	assert.equal(b.maxHp, a.maxHp - UNIQUE.coilHp);
});

test("Leechstone: a kill heals, never past the recovery limit", () => {
	const st = range(kit("ranger", "leechstone"), "ranger");
	st.p.hp = st.p.low = 50; st.stats.maxHp = 200;
	st.enemies[0].hp = 1;
	while (st.enemies[0].hp > 0) run(st, 1, fire);
	assert.ok(st.p.hp >= 50 + UNIQUE.leech - 0.1 && st.p.hp <= st.p.low + 40, `hp ${st.p.hp}`);
});

test("Glass Ring: more Attack, less Defense", () => {
	const a = statsFor(KIT.ranger), b = statsFor(kit("ranger", "glass_ring"));
	assert.ok(b.dmg > a.dmg);
	assert.equal(a.def - b.def, UNIQUE.glass.def);
});

test("Windrunner's Cloak moves the player farther in a rift and in town; light armor only", () => {
	const go = (gear) => { const st = createSim(A, gear, { class_id: "diviner" }); st.enemies = []; const x = st.p.x; run(st, 20, { mx: 1 }); return st.p.x - x; };
	const plain = go(KIT.diviner), quick = go(kit("diviner", "windrunner_cloak", "armor"));
	assert.ok(Math.abs(quick / plain - UNIQUE.windrunner) < 0.01, `${quick} vs ${plain}`);
	const t = createTown(undefined, "diviner"); setTownGear(t, kit("diviner", "windrunner_cloak", "armor"), 1, "diviner");
	const x = t.p.x; stepTown(t, { mx: 1 });
	assert.ok(t.p.x - x > 5.6 / TPS * 1.1, "town too");
});

test("Mantle of the Full Moon: shots hit harder only while MP is full", () => {
	const st = range(kit("diviner", "full_moon_mantle", "armor"), "diviner");
	run(st, 1, fire);
	assert.equal(st.bullets.find((b) => b.owner === "p").dmg, Math.round(st.stats.dmg * UNIQUE.fullMoon));
	st.bullets = []; st.p.mp = 0;
	run(st, TPS, fire);
	assert.ok(st.bullets.filter((b) => b.owner === "p").every((b) => b.dmg === st.stats.dmg));
});

test("Thornplate: a hit taken throws shards outward", () => {
	const st = range(kit("paladin", "thornplate", "armor"), "paladin", { d: 30 });
	enemyShot(st); run(st, 1);
	const shards = st.bullets.filter((b) => b.owner === "p");
	assert.equal(shards.length, UNIQUE.thorns.n);
	assert.ok(shards.every((b) => b.dmg === st.stats.thorns));
});

test("Duskmail: the shot after a kill is stronger, once", () => {
	const st = range(kit("ninja", "duskmail", "armor"), "ninja", { d: 1.2, n: 2, gap: 6 });
	st.enemies[0].hp = 1;
	while (st.enemies[0].hp > 0) run(st, 1, fire);
	assert.equal(st.p.primed, UNIQUE.dusk);
	const dmg = [];
	for (let i = 0; i < TPS; i++) {                     // every shot as it leaves
		const seen = new Set(st.bullets); run(st, 1, fire);
		for (const x of st.bullets) if (x.owner === "p" && !seen.has(x)) dmg.push(x.dmg);
	}
	assert.equal(dmg[0], Math.round(st.stats.dmg * UNIQUE.dusk), dmg.join());
	assert.ok(dmg.slice(1).every((d) => d === st.stats.dmg), dmg.join());
});

test("Gale Quiver: one arrow with the whole volley's damage, through every enemy", () => {
	const st = range(kit("ranger", "gale_quiver", "ability"), "ranger", { n: 4 });
	run(st, 1, { ability: true, ax: 1, ay: 0 });
	const g = st.bullets.filter((b) => b.owner === "p");
	assert.equal(g.length, 1);
	assert.equal(g[0].dmg, statsFor(KIT.ranger).abilityDmg * 7);
	const hp = st.enemies.map((e) => e.hp);
	run(st, 40);
	assert.ok(st.enemies.every((e, i) => hp[i] - e.hp === g[0].dmg), "every one hit");
	assert.equal(statsFor(kit("ranger", "gale_quiver", "ability")).abilityCost, abilityCost("volley", 1));
});

test("Oathhammer: a hit also strikes what stands within a tile of the target", () => {
	const st = range(kit("paladin", "oathhammer", "weapon"), "paladin", { d: 1.5, n: 2, gap: 0.6 });
	st.enemies[1].y += 0.6; st.enemies[1].homeY = st.enemies[1].y; st.enemies[1].x = st.enemies[0].x; st.enemies[1].homeX = st.enemies[1].x;
	while (st.enemies[0].hp === 10000) run(st, 1, fire);
	const dealt = 10000 - st.enemies[0].hp, splash = 10000 - st.enemies[1].hp;
	assert.equal(splash, Math.round(dealt * UNIQUE.splash.share));
});

test("Comet Rod: the bolt bursts into shards where it hits, and where it ends", () => {
	const st = range(kit("diviner", "comet_rod", "weapon"), "diviner", { d: 2 });
	run(st, 1, fire);
	while (!st.bullets.some((b) => b.shard)) run(st, 1);
	assert.equal(st.bullets.filter((b) => b.shard).length, UNIQUE.comet.n);
	const far = range(kit("diviner", "comet_rod", "weapon"), "diviner", { d: 40 });
	run(far, 1, fire);
	for (let i = 0; i < 40 && !far.bullets.some((b) => b.shard); i++) run(far, 1);
	assert.equal(far.bullets.filter((b) => b.shard).length, UNIQUE.comet.n, "a miss bursts too");
});

test("Ricochet Chakram: turns back half way and cuts the same enemy twice", () => {
	const st = range(kit("ninja", "chakram", "weapon"), "ninja", { d: 1.5 });
	run(st, 1, fire);
	const c = st.bullets.find((b) => b.owner === "p");
	assert.ok(c.ret > 0 && c.pierce > 10);
	const hits = [];
	for (let i = 0; i < 30; i++) { const hp = st.enemies[0].hp; run(st, 1); if (st.enemies[0].hp < hp) hits.push(i); }
	assert.equal(hits.length, 2, `hit on ticks ${hits}`);
});

test("Anchor Orb: the field stays where it was cast, wider and hotter", () => {
	const a = statsFor(KIT.paladin), b = statsFor(kit("paladin", "anchor_orb", "ability"));
	assert.ok(Math.abs(b.slowRadius - a.slowRadius * UNIQUE.anchor) < 0.02 && Math.abs(b.abilityDmg - a.abilityDmg * UNIQUE.anchor) < 0.02);
	const st = range(kit("paladin", "anchor_orb", "ability"), "paladin", { d: 30 });
	const x = st.p.x;
	run(st, 1, { ability: true });
	run(st, 30, { mx: -1 });
	assert.ok(Math.abs(st.slowAt.x - x) < 0.2 && st.p.x < x - 1, "it did not follow");
});

test("Codex of Echoes: the star lands again later for half, and costs 10 more", () => {
	const b = statsFor(kit("diviner", "echo_codex", "ability"));
	assert.equal(b.abilityCost, abilityCost("starfall", 1) + UNIQUE.echo.cost);
	const st = range(kit("diviner", "echo_codex", "ability"), "diviner", { d: 3 });
	run(st, 1, { ability: true, ax: 3, ay: 0 });
	assert.equal(st.starfalls.length, 2);
	const e = st.enemies[0];
	run(st, STARFALL_DELAY);
	const first = 10000 - e.hp;
	run(st, UNIQUE.echo.delay);
	assert.equal(10000 - e.hp - first, Math.round(first * UNIQUE.echo.share * 100) / 100);
});

test("Echo Charm: a caught hit throws blades out around the player", () => {
	const st = range(kit("ninja", "echo_charm", "ability"), "ninja", { d: 30 });
	run(st, 1, { ability: true });
	run(st, COUNTER_WINDOW - 10);
	enemyShot(st); run(st, 1);
	const blades = st.bullets.filter((b) => b.owner === "p" && b.look === "blade");
	assert.equal(blades.length, UNIQUE.echoRing.n);
	assert.equal(st.p.abilityCd > 0, true, "the cooldown is the same");
});

test("a unique-laden run plays the same twice", () => {
	const gear = [{ base_id: "comet_rod", tier: 3 }, { base_id: "full_moon_mantle", tier: 2 }, { base_id: "echo_codex", tier: 2 },
		{ base_id: "ember_loop", tier: 2 }, { base_id: "leechstone", tier: 1 }];
	const go = () => { const st = createSim(A, gear, { class_id: "diviner" });
		for (let t = 0; t < 30 * TPS && st.status === "play"; t++) step(st, { mx: t % 300 < 200 ? 1 : 0, my: t % 90 < 45 ? 1 : -1, fire: true, ax: 1, ay: 0, ability: t % 200 === 0 });
		return fingerprint(st); };
	assert.equal(go(), go());
});

test("every item base has a name and a slot abbreviation on the page", () => {
	const py = readFileSync(new URL("../../../halcyon/content.py", import.meta.url), "utf8");
	const jsx = readFileSync(new URL("../../../halcyon/HalcyonRift.jsx", import.meta.url), "utf8");
	const ids = [...py.matchAll(/^ {4}"([a-z_]+)":\s*\{"slot"/gm)].map((m) => m[1]);
	assert.ok(ids.length >= 39, `found ${ids.length} bases`);
	const block = (name) => jsx.slice(jsx.indexOf(`const ${name} = {`), jsx.indexOf("};", jsx.indexOf(`const ${name} = {`)));
	const names = block("NAMES"), abbr = block("ABBR");
	const codes = [...abbr.matchAll(/[a-z_]+: "([A-Z]{2})"/g)].map((m) => m[1]);
	assert.equal(new Set(codes).size, codes.length, "abbreviations are unique");
	for (const id of ids) {
		const at = new RegExp(`(^|[^a-z_])${id}: "`);
		assert.ok(at.test(names), `${id} has no name`);
		assert.ok(at.test(abbr), `${id} has no abbreviation`);
	}
});
