// LoL Stats' logic, kept pure (no React, no DOM) so `node --test` can reach it.
// Two halves: the Seeds tab's aggregation over Liquipedia's Worlds series, and the
// Champions tab's over Oracle's Elixir games (see tools/make_data.py for the layout).

// ── Seeds ───────────────────────────────────────────────────────────────────
export const SEED_REGIONS = ["LCK", "LPL", "LEC", "LCS/LTA", "PCS/LCP", "VCS", "Wildcard"];
export const MAJOR_REGIONS = ["LCK", "LPL", "LEC", "LCS/LTA"];
export const SEED_YEARS = [2020, 2021, 2022, 2023, 2024, 2025];
export const G2 = "G2 Esports";

// Split G2 out of the LEC: "G2" and "LEC excl. G2" take the LEC's place in the order.
export function seedRegions({ splitG2, majors }) {
	const list = splitG2
		? SEED_REGIONS.flatMap((r) => (r === "LEC" ? ["G2", "LEC excl. G2"] : [r]))
		: SEED_REGIONS;
	return majors ? list.filter((r) => MAJOR_REGIONS.includes(r) || r === "G2" || r === "LEC excl. G2") : list;
}

const regOf = (reg, team, splitG2) => (splitG2 && reg === "LEC" ? (team === G2 ? "G2" : "LEC excl. G2") : reg);

// One "side" per team per series. `majors` drops every series with a team from outside
// the four majors, including a major's seed held by a team from elsewhere
// (nonMajorTeams: 2025's LTA #2, Vivo Keyd Stars, is Brazilian).
export const SEED_STAGES = ["Play-In", "Main event"];
export function seedSides(matches, { splitG2 = true, majors = true, nonMajorTeams = [], years = SEED_YEARS, stages = ["Main event"] } = {}) {
	const isMajor = (reg, team) => MAJOR_REGIONS.includes(reg) && !nonMajorTeams.includes(team);
	const yrs = new Set(years);
	const out = [];
	for (const m of matches) {
		if (!yrs.has(m.y)) continue;
		if (!stages.includes(m.st === "Play-In" ? "Play-In" : "Main event")) continue;
		if (majors && !(isMajor(m.ar, m.a) && isMajor(m.br, m.b))) continue;
		const aw = m.ag > m.bg ? 1 : 0;
		const ra = regOf(m.ar, m.a, splitG2), rb = regOf(m.br, m.b, splitG2);
		out.push({ y: m.y, st: m.st, team: m.a, lg: m.al, reg: ra, seed: m.aseed, oreg: rb, gw: m.ag, gl: m.bg, sw: aw, sl: 1 - aw });
		out.push({ y: m.y, st: m.st, team: m.b, lg: m.bl, reg: rb, seed: m.bseed, oreg: ra, gw: m.bg, gl: m.ag, sw: 1 - aw, sl: aw });
	}
	return out;
}

export function tally(sides) {
	const a = { gw: 0, gl: 0, sw: 0, sl: 0 };
	for (const x of sides) { a.gw += x.gw; a.gl += x.gl; a.sw += x.sw; a.sl += x.sl; }
	return a;
}
export const wl = (a, metric) => (metric === "series" ? [a.sw, a.sl] : [a.gw, a.gl]);
// Under 10 games (or 4 series) a cell is an anecdote; the page outlines it.
export const isLow = (a, metric) => { const [w, l] = wl(a, metric); return w + l < (metric === "series" ? 4 : 10); };

// Every region+seed that has a side, in display order.
export function seedRows(sides, regions) {
	const rows = [];
	for (const r of regions) for (let s = 1; s <= 4; s++) if (sides.some((x) => x.reg === r && x.seed === s)) rows.push([r, s]);
	return rows;
}

// The teams behind one seed cell: one entry per team-year, with its record and furthest stage.
export function seedTeams(sides, reg, seed) {
	const by = new Map();
	for (const x of sides) {
		if (x.reg !== reg || x.seed !== seed) continue;
		const k = `${x.y}|${x.team}`;
		if (!by.has(k)) by.set(k, { y: x.y, team: x.team, lg: x.lg, stages: new Set(), sides: [] });
		const e = by.get(k);
		e.stages.add(x.st);
		e.sides.push(x);
	}
	const order = ["Knockout", "Swiss", "Groups", "Play-In"];
	return [...by.values()].sort((a, b) => a.y - b.y || a.team.localeCompare(b.team))
		.map((e) => ({ ...e, tally: tally(e.sides), furthest: order.find((s) => e.stages.has(s)) }));
}

// ── Champions ───────────────────────────────────────────────────────────────
export const CHAMP_REGIONS = ["LCK", "LPL", "LEC", "LCS", "International"];
export const ROLES = ["Top", "Jungle", "Mid", "Bot", "Support"];
// LTA N (2025) and the cross-conference LTA games make_data.py kept are the LCS's slot.
const REGION_OF_LEAGUE = { LCK: "LCK", LPL: "LPL", LEC: "LEC", LCS: "LCS", "LTA N": "LCS", LTA: "LCS",
	WLDs: "International", MSI: "International", FST: "International", MSC: "International" };
export const EVENT_NAME = { WLDs: "Worlds", MSI: "MSI", FST: "First Stand", MSC: "Mid-Season Cup" };
const NO_GD = -99999;

// One year's payload -> games keyed by champion NAME (indexes differ between years).
export function decodeYear(p) {
	const regionOf = p.leagues.map((l) => REGION_OF_LEAGUE[l]);
	if (regionOf.some((r) => !r)) throw new Error(`unknown league in ${p.year}: ${p.leagues}`);
	const games = p.games.map((g) => ({
		year: p.year, league: p.leagues[g[0]], region: regionOf[g[0]], playoffs: g[1] === 1,
		patch: p.patches[g[2]], blue: p.teams[g[3]], red: p.teams[g[4]], win: g[5],
		picks: g.slice(6, 16).map((i) => p.champs[i]),
		bans: g.slice(16, 26).map((i) => (i < 0 ? null : p.champs[i])),
		stats: g.slice(26, 76),
	}));
	return { year: p.year, last: p.last, games };
}

// The games a filter keeps. `phase` applies to domestic games; international games
// are governed only by the International region chip.
export function scope(years, { regions = CHAMP_REGIONS, phase = "all" } = {}) {
	const want = new Set(regions);
	const out = [];
	for (const y of years) for (const g of y.games) {
		if (!want.has(g.region)) continue;
		if (g.region !== "International" && phase !== "all" && g.playoffs !== (phase === "playoffs")) continue;
		out.push(g);
	}
	return out;
}

const blank = () => ({ games: 0, wins: 0, bans: 0, scope: 0 });

// Every champion's line over a set of games: picks, wins, bans, presence.
export function champTable(games) {
	const by = new Map();
	const row = (c) => { if (!by.has(c)) by.set(c, { name: c, ...blank(), roles: [0, 0, 0, 0, 0] }); return by.get(c); };
	for (const g of games) {
		g.picks.forEach((c, i) => {
			const r = row(c);
			r.games++; r.roles[i % 5]++;
			if (g.win === (i < 5 ? 0 : 1)) r.wins++;
		});
		for (const c of new Set(g.bans)) if (c) row(c).bans++;
	}
	const n = games.length;
	return [...by.values()].map((r) => ({
		...r, scope: n,
		winRate: r.games ? r.wins / r.games : null,
		pickRate: n ? r.games / n : 0, banRate: n ? r.bans / n : 0,
		presence: n ? (r.games + r.bans) / n : 0,
		role: ROLES[r.roles.indexOf(Math.max(...r.roles))],
	}));
}

// One champion over a set of games: the headline line, each role, and per-game averages.
export function champLine(games, champ) {
	const line = { ...blank(), scope: games.length, roles: ROLES.map((role) => ({ role, games: 0, wins: 0 })),
		k: 0, d: 0, a: 0, dpm: 0, gd: 0, gdN: 0 };
	for (const g of games) {
		const i = g.picks.indexOf(champ);
		if (g.bans.includes(champ)) line.bans++;
		if (i < 0) continue;
		const won = g.win === (i < 5 ? 0 : 1);
		line.games++; line.wins += won;
		const role = line.roles[i % 5];
		role.games++; role.wins += won;
		const s = g.stats.slice(i * 5, i * 5 + 5);
		line.k += s[0]; line.d += s[1]; line.a += s[2]; line.dpm += s[3];
		if (s[4] !== NO_GD) { line.gd += s[4]; line.gdN++; }
	}
	const n = line.games;
	return {
		...line,
		winRate: n ? line.wins / n : null,
		pickRate: line.scope ? n / line.scope : 0, banRate: line.scope ? line.bans / line.scope : 0,
		presence: line.scope ? (n + line.bans) / line.scope : 0,
		avg: n ? { k: line.k / n, d: line.d / n, a: line.a / n, kda: (line.k + line.a) / Math.max(1, line.d),
			dpm: line.dpm / n, gd: line.gdN ? line.gd / line.gdN : null, gdN: line.gdN } : null,
	};
}

// The champion's record WITH each ally (same team) or INTO each enemy (any role on the
// other team), over every game it was picked in.
export function partners(games, champ, mode) {
	const by = new Map();
	for (const g of games) {
		const i = g.picks.indexOf(champ);
		if (i < 0) continue;
		const side = i < 5 ? 0 : 1;
		const won = g.win === side;
		const lo = (mode === "with") === (side === 0) ? 0 : 5;
		for (let j = lo; j < lo + 5; j++) {
			if (j === i) continue;
			const c = g.picks[j];
			const e = by.get(c) || { name: c, games: 0, wins: 0 };
			e.games++; e.wins += won;
			by.set(c, e);
		}
	}
	return [...by.values()].map((e) => ({ ...e, winRate: e.wins / e.games }));
}

// The top `n` of a partner list at or above `min` games, highest or lowest win rate
// first; ties go to the larger sample.
export function ranked(list, { min = 10, best = true, n = 8 } = {}) {
	return list.filter((e) => e.games >= min)
		.sort((a, b) => (best ? b.winRate - a.winRate : a.winRate - b.winRate) || b.games - a.games || a.name.localeCompare(b.name))
		.slice(0, n);
}

// Search: exact-prefix matches first, then word-prefix ("sol" -> Aurelion Sol), then
// substring; punctuation and case ignored ("kaisa" finds Kai'Sa).
const fold = (s) => s.toLowerCase().replace(/[^a-z0-9 ]/g, "");
export function findChampions(names, q) {
	const f = fold(q.trim());
	if (!f) return [];
	const score = (n) => {
		const x = fold(n);
		if (x.startsWith(f) || x.replace(/ /g, "").startsWith(f.replace(/ /g, ""))) return 0;
		if (x.split(" ").some((w) => w.startsWith(f))) return 1;
		return x.replace(/ /g, "").includes(f.replace(/ /g, "")) ? 2 : -1;
	};
	return names.map((n) => [n, score(n)]).filter(([, s]) => s >= 0)
		.sort((a, b) => a[1] - b[1] || a[0].localeCompare(b[0])).map(([n]) => n);
}

export const pct = (x, d = 0) => (x == null ? "–" : `${(100 * x).toFixed(d)}%`);
