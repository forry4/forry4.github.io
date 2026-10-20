// The Astral Ascent guide's logic (astralguide/derive.js) and its editorial layer
// (astralguide/editorial.js), run against the shipped payload.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import * as D from "../../../astralguide/derive.js";
import * as ED from "../../../astralguide/editorial.js";
import { RUNS, NOT_ON_WIKI, GAME_TEXT, RUN_FINDINGS } from "../../../astralguide/runs.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const data = JSON.parse(readFileSync(path.join(root, "webapp", "public", "data", "astral-guide.json"), "utf8"));
const model = D.buildModel(data, ED);
const links = (text) => model.segments(text).filter((s) => s.t !== "text").map((s) => (s.t === "kw" ? `kw:${s.k}` : `spell:${s.name}`));

test("the payload carries every section, each above its floor", () => {
	const floors = { auras: 150, gambits: 90, spells: 150, imprints: 85, echoes: 35, summons: 12, prowess: 150,
		catalyst: 22, telluric: 25, cursed: 20, bosses: 15, effects: 25, destiny: 6 };
	for (const [k, n] of Object.entries(floors)) assert.ok(data[k].length >= n, `${k}: ${data[k].length} < ${n}`);
	assert.equal(data.stats.armorCap, 70);
	assert.equal(data.stats.critBonus, 50);
});

test("the linker prefers the longest name: a spell over the effect inside it", () => {
	assert.deepEqual(links("When Embers reach ground, 30% chance to cast 1 Meteor Blades"), ["kw:Embers", "spell:Meteor Blades"]);
	assert.deepEqual(links("On spell cast, cast 1 magma comet every 2 levels"), ["spell:Magma Comets"]);
	assert.deepEqual(links("the first enemy hit by this spell cast 1 cryogenic sword."), ["spell:Cold-Steel Sword"]);
});

test("ordinary English is not linked as an effect", () => {
	// "Target" and "Shield" are effects only when capitalized, as the wiki writes them.
	assert.deepEqual(links("Targets and falls on one enemy"), []);
	assert.deepEqual(links("On spell cast, apply 3 Target"), ["kw:Target"]);
	assert.deepEqual(links("If the spell is full poison affinity"), []);
});

test("a trigger clause USES its effect, the effect clause MAKES one", () => {
	const c = (l) => {
		const r = D.classifyLine(l, model.segments);
		return { makes: [...r.makes].sort(), uses: [...r.uses].sort() };
	};
	assert.deepEqual(c("On Wisp hit, creates 2 Embers"), { makes: ["Embers"], uses: ["Wisps"] });
	assert.deepEqual(c("Increases Embers damage by 100%"), { makes: [], uses: ["Embers"] });
	assert.deepEqual(c("This spell deals 10% more damage per electrify on enemies."), { makes: [], uses: ["Electrify"] });
	assert.deepEqual(c("On each hit, 50% to apply 1 Burn"), { makes: ["Burn"], uses: [] });
	assert.deepEqual(c("Transforms Embers into Blue Embers — Unique"), { makes: [], uses: ["Embers"] });
});

test("every effect in the vocabulary is made by something, so no Synergies page is empty", () => {
	const dead = D.KEYWORDS.filter((k) => !(model.makers[k.k] || []).length).map((k) => k.k);
	assert.deepEqual(dead, []);
});

test("imprints that name a spell are linked to it, and a comparison is not a cast", () => {
	const casts = (n) => model.byKey[D.keyOf("imprint", D.slug(n))].casts;
	assert.deepEqual(casts("Fajrokometo"), ["Magma Comets"]);
	assert.deepEqual(casts("Nuloklingo"), ["Thousand Knives"]);
	assert.deepEqual(casts("Venenkateno"), ["Thorns Chains"]);
	// "create a fire clone (like pisces clones)" is not a cast of Pisces Clones.
	assert.deepEqual(casts("Fajroklono"), []);
	const kinds = new Set(model.list.filter((e) => e.type === "imprint").map((e) => e.kind));
	assert.ok(kinds.has("Casts a spell") && kinds.has("Summons an echo") && kinds.has("Summons"), [...kinds].join(", "));
});

test("search: every word must match, and the name decides the order", () => {
	assert.equal(D.search(model, "flame blessing")[0].name, "Flame Blessing");
	// "fire astral": every result is Astral and mentions fire somewhere; the Fire-element
	// ones come first (an Electric aura that makes "Fire Plasma" still matches, after them).
	const fa = D.search(model, "fire astral", { types: ["aura"] });
	const fireAstral = data.auras.filter((a) => a.element === "Fire" && a.astral).length;
	assert.ok(fa.every((e) => e.rarities.includes("Astral")), JSON.stringify(fa.map((e) => e.name)));
	assert.ok(fa.slice(0, fireAstral).every((e) => e.element === "Fire"), JSON.stringify(fa.map((e) => `${e.name}/${e.element}`)));
	assert.ok(D.search(model, "embers").some((e) => e.type === "effect" && e.name === "Embers"));
	assert.deepEqual(D.search(model, ""), []);
});

test("the charts' maths matches the Player Stats page", () => {
	assert.equal(D.critMultiplier(20, 50), 1.1);
	assert.equal(D.critMultiplier(150, 50), 1.5);          // chance caps at 100%
	assert.equal(D.armorPct(30, 0), 70);                   // 90% from stones, capped at 70
	assert.equal(D.armorPct(10, 0), 30);
	// "the tenth [stone] provides 30% reduced damage taken, resulting in a 43% increase in effective life"
	assert.equal(Math.round((D.effectiveLife(100, 30) / 100 - 1) * 100), 43);
	// "armor should be taken over life when life exceeds 500"
	assert.equal(Math.round(D.breakEvenLife(0)), 485);
	assert.equal(D.nextStone(500, 70).armorGain, 0);       // a capped stone adds nothing
	const ds = D.nextDamageStone(0, 0, 50);
	assert.equal(ds.strGain, 0.05);
	assert.ok(Math.abs(ds.critGain - 0.01) < 1e-9);
});

// ── The editorial layer, held to the data ────────────────────────────────
const names = (type) => new Set(model.list.filter((e) => e.type === type).map((e) => e.name));

test("every name the editorial layer cites exists in the payload", () => {
	const of = { echoes: names("echo"), imprints: names("imprint"), auras: names("aura"), summons: names("summon") };
	const bad = [];
	for (const [list, tiers] of Object.entries(ED.TIERS)) {
		for (const rows of Object.values(tiers)) for (const [n] of rows) if (!of[list].has(n)) bad.push(`${list}: ${n}`);
	}
	for (const [n] of ED.STARTING_AURAS) if (!of.auras.has(n)) bad.push(`start: ${n}`);
	const fam = new Set(data.gambits.map((g) => g.family));
	for (const a of ED.ARCHETYPES) {
		for (const n of [...a.makers, ...a.payoffs]) if (!of.auras.has(n)) bad.push(`${a.name}: ${n}`);
		for (const n of a.gambits) if (!fam.has(n)) bad.push(`${a.name} gambit: ${n}`);
		for (const n of a.imprints) if (!of.imprints.has(n)) bad.push(`${a.name} imprint: ${n}`);
		if (a.summon && !of.summons.has(a.summon)) bad.push(`${a.name} summon: ${a.summon}`);
		if (a.echo && !of.echoes.has(a.echo)) bad.push(`${a.name} echo: ${a.echo}`);
		if (a.effect !== null && !D.KEYWORD[a.effect]) bad.push(`${a.name} effect: ${a.effect}`);
	}
	const cat = new Set(data.catalyst.map((c) => c.name));
	for (const [n] of [...ED.CATALYST_PICKS.first10, ...ED.CATALYST_PICKS.first50]) if (!cat.has(n)) bad.push(`catalyst: ${n}`);
	for (const [i, e] of Object.entries(ED.VOKO_ECHO)) {
		if (!of.imprints.has(i)) bad.push(`voko imprint: ${i}`);
		if (!of.echoes.has(e)) bad.push(`voko echo: ${e}`);
	}
	assert.deepEqual(bad, []);
});

test("every echo-summoning imprint is paired with its echo", () => {
	const vokos = [...names("imprint")].filter((n) => /voko/.test(n));
	assert.deepEqual(vokos.filter((n) => !ED.VOKO_ECHO[n]), []);
});

test("the echo tier list ranks every echo exactly once", () => {
	const ranked = Object.values(ED.TIERS.echoes).flat().map(([n]) => n);
	assert.equal(new Set(ranked).size, ranked.length, "an echo is ranked twice");
	assert.deepEqual([...names("echo")].filter((n) => !ranked.includes(n)), []);
});

test("every tier list names each entry once", () => {
	for (const [list, tiers] of Object.entries(ED.TIERS)) {
		const all = Object.values(tiers).flat().map(([n]) => n);
		assert.equal(new Set(all).size, all.length, `${list} ranks something twice`);
	}
});

// ── The winning runs (runs.js), held to the payload ──────────────────────
test("every name in the winning runs exists, or is declared not on the wiki", () => {
	const of = { aura: names("aura"), imprint: names("imprint"), spell: names("spell"), summon: names("summon") };
	const bad = [];
	for (const r of RUNS) {
		for (const a of r.auras) if (!of.aura.has(a) && !NOT_ON_WIKI.auras.has(a)) bad.push(`run ${r.id} aura: ${a}`);
		for (const s of r.spells) {
			if (!of.spell.has(s.name) && !NOT_ON_WIKI.spells.has(s.name)) bad.push(`run ${r.id} spell: ${s.name}`);
			if (s.imprint && !of.imprint.has(s.imprint) && !NOT_ON_WIKI.imprints.has(s.imprint)) bad.push(`run ${r.id} imprint: ${s.imprint}`);
		}
		if (r.summon && !of.summon.has(r.summon)) bad.push(`run ${r.id} summon: ${r.summon}`);
		for (const e of r.engines) if (e !== "No auras" && !ED.ARCHETYPES.some((a) => a.name === e)) bad.push(`run ${r.id} engine: ${e}`);
	}
	// A "not on the wiki" name that the wiki has since gained must leave the list.
	for (const [kind, set] of [["aura", NOT_ON_WIKI.auras], ["imprint", NOT_ON_WIKI.imprints], ["spell", NOT_ON_WIKI.spells]]) {
		for (const n of set) if (of[kind].has(n)) bad.push(`${n} is on the wiki now; drop it from NOT_ON_WIKI`);
	}
	for (const n of Object.keys(GAME_TEXT)) if (!of.aura.has(n) && !NOT_ON_WIKI.auras.has(n)) bad.push(`GAME_TEXT: ${n}`);
	assert.deepEqual(bad, []);
});

test("each run is a full end screen: four spells, at most five auras, sane stats", () => {
	assert.equal(new Set(RUNS.map((r) => r.id)).size, RUNS.length);
	for (const r of RUNS) {
		assert.equal(r.spells.length, 4, `run ${r.id}`);
		assert.ok(r.auras.length <= 5, `run ${r.id}`);
		assert.ok(r.dl >= 1 && r.dl <= 100 && r.armor <= 70 && r.life > 0, `run ${r.id}`);
		for (const s of r.spells) assert.ok(s.level >= 0 && s.level <= 15 && [0, 10, 20, 30, 50].includes(s.aff), `run ${r.id} ${s.name}`);
	}
});

test("the findings' numbers are the runs' own counts", () => {
	const u = D.runUsage(RUNS);
	const n = (list, name) => u[list].find((x) => x.name === name)?.n || 0;
	const text = RUN_FINDINGS.map(([h, t]) => `${h} ${t}`).join(" ");
	assert.ok(text.includes(`in ${n("auras", "Magic Weapon")} wins`), `Magic Weapon is in ${n("auras", "Magic Weapon")}`);
	assert.ok(text.includes(`${n("summons", "Capricorn")} of the ${RUNS.length} wins`), `Capricorn is in ${n("summons", "Capricorn")}`);
	const loop = n("engines", "Missile ↔ Ice Sword loop");
	assert.ok(text.includes(["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"][loop] + " wins run it"), `the loop is in ${loop}`);
	const stacked = RUNS.filter((r) => new Set(r.auras).size < r.auras.length).length;
	assert.ok(text.includes(["Zero", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight"][stacked] + " runs carry"), `${stacked} runs stack copies`);
	// The aura tier list's S tier is made of proven auras.
	for (const [name] of ED.TIERS.auras.S) assert.ok(n("auras", name) >= 3, `${name} is S tier on ${n("auras", name)} wins`);
});

test("statRange takes the median of the values present", () => {
	assert.deepEqual(D.statRange([{ a: 1 }, { a: 3 }, { a: 2 }], "a"), { min: 1, median: 2, max: 3, n: 3 });
	assert.equal(D.statRange([{ a: 1 }, { a: 4 }], "a").median, 2.5);
	assert.equal(D.levelBonus(10), 200);
});
