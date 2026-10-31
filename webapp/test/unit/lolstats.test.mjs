// LoL Stats' logic (lolstats/derive.js), run against the shipped payloads. The two
// tabs come from two independent sources -- Liquipedia's Worlds brackets and Oracle's
// Elixir's game files -- so where they overlap (the number of Worlds games each year)
// they are held to each other.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import * as D from "../../../lolstats/derive.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..", "..");
const pub = (f) => JSON.parse(readFileSync(path.join(root, "webapp", "public", "data", f), "utf8"));
const worlds = pub("lol-worlds.json");
const index = pub("lol-champs-index.json");
const years = index.years.map((y) => D.decodeYear(pub(`lol-champs-${y.year}.json`)));

test("every seeded series has a winner and a best-of score", () => {
	for (const m of worlds.matches) {
		assert.notEqual(m.ag, m.bg, JSON.stringify(m));
		assert.ok([1, 2, 3].includes(Math.max(m.ag, m.bg)), JSON.stringify(m));
	}
});

test("each year's champion is the one team to win three Knockout series", () => {
	const champion = { 2020: "DAMWON Gaming", 2021: "EDward Gaming", 2022: "DRX", 2023: "T1", 2024: "T1", 2025: "T1" };
	for (const [y, team] of Object.entries(champion)) {
		const wins = {};
		for (const m of worlds.matches) {
			if (m.y !== Number(y) || m.st !== "Knockout") continue;
			const w = m.ag > m.bg ? m.a : m.b;
			wins[w] = (wins[w] || 0) + 1;
		}
		assert.deepEqual(Object.keys(wins).filter((t) => wins[t] === 3), [team], `${y}: ${JSON.stringify(wins)}`);
	}
});

test("Liquipedia's brackets and Oracle's Elixir agree on every year's Worlds game count", () => {
	for (const y of D.SEED_YEARS) {
		const lp = worlds.matches.filter((m) => m.y === y).reduce((n, m) => n + m.ag + m.bg, 0);
		const oe = years.find((x) => x.year === y).games.filter((g) => g.league === "WLDs").length;
		assert.equal(oe, lp, `${y}: Oracle's Elixir ${oe}, Liquipedia ${lp}`);
	}
});

test("seed views: majors only drops the Brazilian LTA seed, and the G2 split covers the whole LEC", () => {
	const all = D.seedSides(worlds.matches, { majors: false, splitG2: false, stages: D.SEED_STAGES });
	const majors = D.seedSides(worlds.matches, { nonMajorTeams: worlds.nonMajorTeams, stages: D.SEED_STAGES });
	assert.ok(all.some((x) => x.team === "Vivo Keyd Stars"));
	assert.ok(!majors.some((x) => x.team === "Vivo Keyd Stars"));
	assert.ok(majors.every((x) => D.seedRegions({ splitG2: true, majors: true }).includes(x.reg)));
	const split = D.seedSides(worlds.matches, { majors: false, splitG2: true, stages: D.SEED_STAGES });
	const lec = D.tally(all.filter((x) => x.reg === "LEC"));
	const parts = D.tally(split.filter((x) => x.reg === "G2" || x.reg === "LEC excl. G2"));
	assert.deepEqual(parts, lec);
	// Two sides per series, and the two sides of a series are mirror images.
	assert.equal(all.length, 2 * worlds.matches.length);
	const t = D.tally(all);
	assert.equal(t.gw, t.gl);
	assert.equal(t.sw, t.sl);
});

test("every game is ten distinct champions with a winner, and the tables add up", () => {
	for (const y of years) {
		for (const g of y.games) {
			assert.equal(new Set(g.picks).size, 10, `${y.year} ${g.blue} vs ${g.red}`);
			assert.ok(g.win === 0 || g.win === 1);
			assert.ok(D.CHAMP_REGIONS.includes(g.region));
		}
		const t = D.champTable(y.games);
		assert.equal(t.reduce((n, r) => n + r.games, 0), 10 * y.games.length, String(y.year));
		assert.equal(t.reduce((n, r) => n + r.wins, 0), 5 * y.games.length, String(y.year));
	}
});

test("partners are symmetric: A with B is B with A, and A into B plus B into A is every meeting", () => {
	const games = D.scope([years[years.length - 1]]);
	const top = D.champTable(games).sort((a, b) => b.games - a.games).slice(0, 12).map((r) => r.name);
	for (const a of top) for (const b of top) {
		if (a === b) continue;
		const ab = D.partners(games, a, "with").find((e) => e.name === b);
		const ba = D.partners(games, b, "with").find((e) => e.name === a);
		assert.deepEqual(ab && [ab.games, ab.wins], ba && [ba.games, ba.wins], `${a} with ${b}`);
		const ai = D.partners(games, a, "into").find((e) => e.name === b);
		const bi = D.partners(games, b, "into").find((e) => e.name === a);
		if (ai || bi) {
			assert.equal(ai.games, bi.games, `${a} into ${b}`);
			assert.equal(ai.wins + bi.wins, ai.games, `${a} into ${b}`);
		}
	}
});

test("the pair table holds every teammate and opponent: 4 and 5 per game, with no minimum", () => {
	const games = D.scope([years[years.length - 1]]);
	for (const r of D.champTable(games).sort((a, b) => b.games - a.games).slice(0, 15)) {
		const rows = D.pairTable(games, r.name);
		assert.equal(rows.reduce((n, x) => n + (x.with?.games || 0), 0), 4 * r.games, r.name);
		assert.equal(rows.reduce((n, x) => n + (x.into?.games || 0), 0), 5 * r.games, r.name);
		assert.equal(rows.reduce((n, x) => n + (x.with?.wins || 0), 0), 4 * r.wins, r.name);
		assert.ok(rows.every((x) => x.with || x.into) && !rows.some((x) => x.name === r.name), r.name);
	}
});

test("a champion's line matches the table, and its regions add up to it", () => {
	const y = years[years.length - 1];
	const games = D.scope([y]);
	for (const r of D.champTable(games).slice(0, 20)) {
		const line = D.champLine(games, r.name);
		assert.equal(line.games, r.games);
		assert.equal(line.wins, r.wins);
		assert.equal(line.bans, r.bans);
		assert.equal(line.roles.reduce((n, x) => n + x.games, 0), line.games);
		const byRegion = D.CHAMP_REGIONS.map((reg) => D.champLine(D.scope([y], { regions: [reg] }), r.name));
		assert.equal(byRegion.reduce((n, l) => n + l.games, 0), line.games, r.name);
	}
});

test("the phase filter splits league games and leaves internationals alone", () => {
	const y = years[0];
	const all = D.scope([y]).length;
	const reg = D.scope([y], { phase: "regular" }).length;
	const po = D.scope([y], { phase: "playoffs" }).length;
	const intl = D.scope([y], { regions: ["International"] }).length;
	assert.ok(intl > 0 && reg > 0 && po > 0);
	assert.equal(reg + po - intl, all);
});

test("sortPairs: the minimum applies to the side being sorted, ties go to the larger sample", () => {
	const e = (games, wins) => ({ games, wins, winRate: wins / games });
	const rows = [
		{ name: "A", with: e(12, 9), into: e(3, 0) },
		{ name: "B", with: e(40, 30), into: null },
		{ name: "C", with: e(4, 4), into: e(30, 6) },
		{ name: "D", with: e(20, 5), into: e(12, 9) },
		{ name: "E", with: null, into: e(11, 11) },
	];
	const names = (opts) => D.sortPairs(rows, opts).map((r) => r.name).join("");
	assert.equal(names({ key: "withRate", dir: -1, min: 10 }), "BAD");     // best with: 75% (40g) beats 75% (12g)
	assert.equal(names({ key: "withRate", dir: 1, min: 10 }), "DBA");      // worst with
	assert.equal(names({ key: "intoRate", dir: -1, min: 10 }), "EDC");     // best into: C counts here, 30 games against
	assert.equal(names({ key: "intoRate", dir: 1, min: 10 }), "CDE");
	assert.equal(names({ key: "together", dir: -1, min: 1 }), "BCDAE");    // most met, both sides added
	assert.equal(names({ key: "name", dir: 1, min: 1 }), "ABCDE");
	// On a real champion: "Best with" at 10 is exactly the same-team partners met 10+ times, best first.
	const games = D.scope([years[years.length - 1]]);
	const real = D.pairTable(games, "Azir");
	const best = D.sortPairs(real, { key: "withRate", dir: -1, min: 10 });
	assert.deepEqual(best.map((r) => r.name).sort(), real.filter((r) => (r.with?.games || 0) >= 10).map((r) => r.name).sort());
	assert.ok(best.every((r, i) => i === 0 || best[i - 1].with.winRate >= r.with.winRate));
	assert.equal(D.sortPairs(real, { min: 1 }).length, real.length);
});

test("search finds names by prefix, word or spelling without punctuation", () => {
	const names = [...new Set(years.flatMap((y) => y.games.flatMap((g) => g.picks)))];
	assert.equal(D.findChampions(names, "kaisa")[0], "Kai'Sa");
	assert.equal(D.findChampions(names, "AZI")[0], "Azir");
	assert.ok(D.findChampions(names, "sol").includes("Aurelion Sol"));
	assert.equal(D.findChampions(names, "lee")[0], "Lee Sin");
	assert.deepEqual(D.findChampions(names, "  "), []);
});
