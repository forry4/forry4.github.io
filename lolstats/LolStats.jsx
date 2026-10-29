import { useState, useEffect, useMemo, useRef, useCallback } from "react";
import { baseCss } from "../shared/theme.js";
import { buildPath, parsePath, pushPath, subscribe } from "../shared/router.js";
import * as D from "./derive.js";

// CSS lives in the sibling .css file, imported with `?inline` (see CLAUDE.md: never move
// it back into a JS template literal).
import _cssText from "./LolStats.css?inline";
const css = _cssText;

// The payloads are build artifacts (tools/), fetched rather than bundled so the lazy
// chunk stays small. Each is fetched once per page load.
const dataUrl = (f) => `${import.meta.env.BASE_URL || "/"}data/${f}`;
const cache = new Map();
const getJson = (f) => {
	if (!cache.has(f)) {
		cache.set(f, fetch(dataUrl(f)).then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.catch((e) => { cache.delete(f); throw e; }));
	}
	return cache.get(f);
};

const TABS = [{ id: "seeds", label: "Worlds seeds" }, { id: "champions", label: "Champions" }];
// Segment 2 of /lolstats/<tab>; router.js upper-cases it (it was written for room codes).
const routeTab = () => {
	const t = (parsePath().room || "").toLowerCase();
	return TABS.some((x) => x.id === t) ? t : "seeds";
};
const hashChamp = () => decodeURIComponent((window.location.hash || "").slice(1)) || null;

const fmt = (n, d = 0) => (n == null ? "–" : Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d }));
const rec = (w, l) => `${w}–${l}`;
const monthDay = (iso) => new Date(`${iso}T12:00:00Z`).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "UTC" }).replace(" ", " ");

// Win-rate fill: red below 50%, blue above, the card ground at 50%; full strength at
// 20% and 80%. The poles are the dataviz palette's dark-mode blue and red.
const WIN = [57, 135, 229], LOSS = [230, 103, 103], MID = [44, 40, 32];
const mix = (a, b, t) => a.map((v, i) => Math.round(v + (b[i] - v) * t));
const lum = (c) => {
	const f = c.map((v) => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; });
	return 0.2126 * f[0] + 0.7152 * f[1] + 0.0722 * f[2];
};
function heat(p) {
	const t = Math.max(-1, Math.min(1, (p - 0.5) / 0.3));
	const c = t >= 0 ? mix(MID, WIN, t) : mix(MID, LOSS, -t);
	return { background: `rgb(${c})`, color: lum(c) > 0.4 ? "#13110d" : "#fbf6ea" };
}

function Chips({ label, options, value, onToggle, multi = false }) {
	return (
		<div className="lol-chips" role="group" aria-label={label}>
			<span className="lol-chips-lbl">{label}</span>
			{options.map(([v, text]) => (
				<button type="button" key={String(v)} className="lol-chip"
					aria-pressed={multi ? value.includes(v) : value === v} onClick={() => onToggle(v)}>{text}</button>
			))}
		</div>
	);
}
// A multi-select that never empties: clicking the last chip left on does nothing.
const toggleIn = (list, v, all) => {
	const next = list.includes(v) ? list.filter((x) => x !== v) : [...list, v];
	return next.length ? all.filter((x) => next.includes(x)) : list;
};

// ── Worlds seeds ────────────────────────────────────────────────────────────
const SEED_DEFAULTS = { years: D.SEED_YEARS, stages: ["Main event"], metric: "games", majors: true, splitG2: true };
const SEED_KEY = "lolstats.seeds.v1";
const loadSeedFilters = () => {
	try { const s = JSON.parse(localStorage.getItem(SEED_KEY) || "null"); if (s) return { ...SEED_DEFAULTS, ...s }; } catch { /* storage off */ }
	return SEED_DEFAULTS;
};

function HeatCell({ a, metric, title, className = "", ...rest }) {
	const [w, l] = D.wl(a, metric);
	if (!w && !l) return <td className={`lol-cell empty ${className}`} {...rest}>–</td>;
	const tip = `${title}\nGames ${rec(a.gw, a.gl)} (${D.pct(a.gw / (a.gw + a.gl), 1)})\nSeries ${rec(a.sw, a.sl)} (${D.pct(a.sw / (a.sw + a.sl), 1)})`;
	return (
		<td className={`lol-cell ${D.isLow(a, metric) ? "low" : ""} ${className}`} style={heat(w / (w + l))} title={tip} {...rest}>
			<span className="lol-pct">{D.pct(w / (w + l))}</span>
			<span className="lol-rec">{rec(w, l)}</span>
		</td>
	);
}

function SeedsTab() {
	const [payload, setPayload] = useState(null);
	const [err, setErr] = useState("");
	const [f, setF] = useState(loadSeedFilters);
	const [sel, setSel] = useState("LCK|1");
	useEffect(() => { getJson("lol-worlds.json").then(setPayload, (e) => setErr(String(e.message || e))); }, []);
	useEffect(() => { try { localStorage.setItem(SEED_KEY, JSON.stringify(f)); } catch { /* storage off */ } }, [f]);
	const set = (patch) => setF((x) => ({ ...x, ...patch }));

	const view = useMemo(() => {
		if (!payload) return null;
		const sides = D.seedSides(payload.matches, { ...f, nonMajorTeams: payload.nonMajorTeams });
		const regions = D.seedRegions(f);
		return { sides, regions, rows: D.seedRows(sides, regions) };
	}, [payload, f]);

	if (err) return <div className="lol-loading">Couldn’t load the Worlds results ({err}).</div>;
	if (!view) return <div className="lol-loading">Loading the Worlds results…</div>;
	const { sides, regions, rows } = view;
	const selKey = rows.some(([r, s]) => `${r}|${s}` === sel) ? sel : `${rows[0]?.[0]}|${rows[0]?.[1]}`;
	const [selReg, selSeedS] = selKey.split("|");
	const selSeed = Number(selSeedS);
	const of = (pred) => D.tally(sides.filter(pred));
	const m = f.metric;
	const games = sides.reduce((n, x) => n + x.gw, 0);
	const teams = D.seedTeams(sides, selReg, selSeed);
	const selTally = D.tally(teams.flatMap((t) => t.sides));
	const [sw, sl] = D.wl(selTally, m);

	return (
		<>
			<div className="lol-intro">
				<h1 className="lol-h1">How each regional seed fares at Worlds</h1>
				<p className="lol-sub">Worlds 2020–2025, sorted by the seed each team brought from its region. Blue won more than half its {m}, red lost more than half. On a desktop, hover a cell for both records.</p>
			</div>
			<div className="lol-controls">
				<Chips label="Years" multi options={D.SEED_YEARS.map((y) => [y, y])} value={f.years}
					onToggle={(y) => set({ years: toggleIn(f.years, y, D.SEED_YEARS) })} />
				<Chips label="Stages" multi options={D.SEED_STAGES.map((s) => [s, s])} value={f.stages}
					onToggle={(s) => set({ stages: toggleIn(f.stages, s, D.SEED_STAGES) })} />
				<Chips label="Count" options={[["games", "Games"], ["series", "Series"]]} value={m} onToggle={(v) => set({ metric: v })} />
				<Chips label="Regions" options={[[true, "Majors only"], [false, "All regions"]]} value={f.majors} onToggle={(v) => set({ majors: v })} />
				<Chips label="Europe" options={[[true, "G2 separate"], [false, "LEC combined"]]} value={f.splitG2} onToggle={(v) => set({ splitG2: v })} />
				<span className="lol-count">{fmt(games)} games · {fmt(sides.length / 2)} series</span>
			</div>

			<section className="lol-sec">
				<h2 className="lol-h2">Win rate by seed</h2>
				<p className="lol-sub">One cell per region and seed. Pick a cell to list the teams behind it.</p>
				<div className="lol-frame">
					<table className="lol-heat">
						<thead><tr><th />{[1, 2, 3, 4].map((s) => <th key={s} scope="col">Seed {s}</th>)}<th scope="col">All seeds</th></tr></thead>
						<tbody>
							{regions.map((r) => (
								<tr key={r}>
									<th scope="row">{r}</th>
									{[1, 2, 3, 4].map((s) => {
										if (!rows.some(([rr, ss]) => rr === r && ss === s)) return <td key={s} className="lol-cell empty">·</td>;
										const key = `${r}|${s}`;
										return <HeatCell key={s} a={of((x) => x.reg === r && x.seed === s)} metric={m} title={`${r} #${s}`}
											className={`pick ${key === selKey ? "sel" : ""}`} tabIndex={0} role="button" aria-pressed={key === selKey}
											aria-label={`${r} seed ${s}`} onClick={() => setSel(key)}
											onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(key); } }} />;
									})}
									<HeatCell a={of((x) => x.reg === r)} metric={m} title={`${r}, all seeds`} className="total" />
								</tr>
							))}
						</tbody>
					</table>
				</div>
				<div className="lol-detail">
					<h3 className="lol-h3">{selReg} #{selSeed} · {sw + sl ? `${D.pct(sw / (sw + sl))} ` : ""}<span className="lol-dim">{rec(sw, sl)} {m}</span></h3>
					{!teams.length && <p className="lol-sub">No {m} for this seed in the selected years and stages.</p>}
					<div className="lol-apps">
						{teams.map((t) => {
							const [tw, tl] = D.wl(t.tally, m);
							const lg = selReg === "Wildcard" || t.lg === "LTA" || t.lg === "LCP" ? ` (${t.lg})` : "";
							return (
								<div className="lol-app" key={`${t.y}${t.team}`}>
									<span className="lol-app-who"><span className="lol-pip" style={{ background: heat(tw / Math.max(1, tw + tl)).background }} />
										<span className="lol-dim">{t.y}</span> {t.team}{lg && <span className="lol-dim">{lg}</span>}</span>
									<span className="lol-app-r">{rec(tw, tl)} · {t.furthest}</span>
								</div>
							);
						})}
					</div>
				</div>
			</section>

			<section className="lol-sec">
				<h2 className="lol-h2">Seed against each region</h2>
				<p className="lol-sub">Read across a row: how that seed did against teams from each region.</p>
				<div className="lol-frame">
					<table className="lol-heat">
						<thead><tr><th />{regions.map((r) => <th key={r} scope="col"><span className="lol-dim">vs</span> {r}</th>)}<th scope="col">Overall</th></tr></thead>
						<tbody>
							{rows.map(([r, s], i) => (
								<tr key={`${r}${s}`} className={i && rows[i - 1][0] !== r ? "lol-gap" : ""}>
									<th scope="row">{r} #{s}</th>
									{regions.map((o) => <HeatCell key={o} metric={m} title={`${r} #${s} vs ${o}`}
										a={of((x) => x.reg === r && x.seed === s && x.oreg === o)} />)}
									<HeatCell a={of((x) => x.reg === r && x.seed === s)} metric={m} title={`${r} #${s}, overall`} className="total" />
								</tr>
							))}
						</tbody>
					</table>
				</div>
			</section>

			<section className="lol-sec">
				<h2 className="lol-h2">Region against region</h2>
				<p className="lol-sub">All seeds pooled. Each row is that region’s win rate against the column’s region, so the grid mirrors itself.</p>
				<div className="lol-frame">
					<table className="lol-heat">
						<thead><tr><th />{regions.map((r) => <th key={r} scope="col"><span className="lol-dim">vs</span> {r}</th>)}<th scope="col">Overall</th></tr></thead>
						<tbody>
							{regions.map((r) => (
								<tr key={r}>
									<th scope="row">{r}</th>
									{regions.map((o) => (o === r
										? <td key={o} className="lol-cell empty" title="Games within a region always split 50/50">–</td>
										: <HeatCell key={o} a={of((x) => x.reg === r && x.oreg === o)} metric={m} title={`${r} vs ${o}`} />))}
									<HeatCell a={of((x) => x.reg === r && x.oreg !== r)} metric={m} title={`${r} vs other regions`} className="total" />
								</tr>
							))}
						</tbody>
					</table>
				</div>
				<div className="lol-legend" aria-hidden="true">
					<span className="lol-ramp"><span>20%</span><span className="lol-ramp-bar"
						style={{ background: `linear-gradient(90deg, ${heat(0.2).background}, ${heat(0.5).background}, ${heat(0.8).background})` }} /><span>80%+</span></span>
					<span><span className="lol-dash" /> fewer than 10 games (or 4 series): an anecdote, not a rate</span>
				</div>
			</section>

			<section className="lol-sec lol-notes">
				<h2 className="lol-h2">How this was counted</h2>
				<p><b>Source.</b> Results from <a href="https://liquipedia.net/leagueoflegends/World_Championship" target="_blank" rel="noreferrer">Liquipedia</a>’s Worlds brackets (CC BY-SA), tiebreakers included. The 2023 Qualifying Series and every regional final are left out; Worlds 2026 is added once it finishes.</p>
				<p><b>Games or series.</b> Games count every game, so a 3–2 final adds five. Series count each Bo1, Bo3 or Bo5 once.</p>
				<p><b>Seeds.</b> A team that entered through Play-In keeps its region’s seed. In 2020 the LCK sent three teams and the LPL and LEC four each. In 2024 Hanwha Life were LCK #1 and Gen.G LCK #2. In 2023 Team BDS were LEC #4 through the Qualifying Series. G2 played every year but 2021: LEC #1 in 2020, 2023, 2024 and 2025, LEC #2 in 2022.</p>
				<p><b>2025.</b> The LTA replaced the LCS and CBLOL; its seeds sit in the LCS/LTA row. Its #2, Vivo Keyd Stars, is Brazilian, so “Majors only” leaves their games out. The LCP replaced the PCS, VCS and LJL; its #2, Team Secret Whales, is Vietnamese.</p>
				<p><b>Majors only</b> keeps games where both teams are from the LCK, LPL, LEC or LCS/LTA. <b>Wildcard</b> (All regions) pools the single-slot leagues: CBLOL, LLA, LJL, TCL, LCL and LCO.</p>
			</section>
		</>
	);
}

// ── Champions ───────────────────────────────────────────────────────────────
const PHASES = [["all", "All games"], ["regular", "Regular season"], ["playoffs", "Playoffs"]];
const SORTS = [["name", "Champion"], ["role", "Role"], ["games", "Games"], ["winRate", "Win %"], ["pickRate", "Pick %"], ["banRate", "Ban %"], ["presence", "Presence"]];
const MINS = [5, 10, 20, 40];

function ChampSearch({ names, onPick, inputRef }) {
	const [q, setQ] = useState("");
	const [open, setOpen] = useState(false);
	const [hi, setHi] = useState(0);
	const hits = useMemo(() => D.findChampions(names, q).slice(0, 8), [names, q]);
	const pick = (n) => { setQ(""); setOpen(false); onPick(n); };
	return (
		<div className="lol-search">
			<div className="lol-search-box">
				<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="1.8" aria-hidden="true"><circle cx="11" cy="11" r="6.5" /><path d="m16 16 4.5 4.5" /></svg>
				<input ref={inputRef} id="lol-champ-search" type="search" placeholder="Search a champion" value={q} autoComplete="off"
					aria-label="Search a champion" role="combobox" aria-expanded={open && hits.length > 0} aria-controls="lol-champ-hits"
					onChange={(e) => { setQ(e.target.value); setOpen(true); setHi(0); }}
					onFocus={() => setOpen(true)} onBlur={() => setTimeout(() => setOpen(false), 150)}
					onKeyDown={(e) => {
						if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(h + 1, hits.length - 1)); }
						else if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(h - 1, 0)); }
						else if (e.key === "Enter" && hits[hi]) { e.preventDefault(); pick(hits[hi]); }
						else if (e.key === "Escape") setOpen(false);
					}} />
			</div>
			{open && q.trim() && (
				<div className="lol-search-pop" id="lol-champ-hits" role="listbox">
					{hits.length ? hits.map((n, i) => (
						<button type="button" key={n} role="option" aria-selected={i === hi} className={`lol-search-hit ${i === hi ? "hi" : ""}`}
							onMouseDown={(e) => e.preventDefault()} onClick={() => pick(n)}>{n}</button>
					)) : <div className="lol-search-none">No champion matches “{q}”.</div>}
				</div>
			)}
		</div>
	);
}

function ChampTable({ games, onOpen, title }) {
	const [sort, setSort] = useState({ key: "presence", dir: -1 });
	const [filter, setFilter] = useState("");
	const rows = useMemo(() => {
		const all = D.champTable(games);
		const f = filter.trim() ? new Set(D.findChampions(all.map((r) => r.name), filter)) : null;
		const val = (r) => (sort.key === "winRate" ? (r.winRate ?? -1) : r[sort.key]);
		return all.filter((r) => !f || f.has(r.name)).sort((a, b) => {
			const x = val(a), y = val(b);
			const c = typeof x === "string" ? x.localeCompare(y) : x - y;
			return sort.dir * c || b.games - a.games || a.name.localeCompare(b.name);
		});
	}, [games, sort, filter]);
	const by = (key) => setSort((s) => (s.key === key ? { key, dir: -s.dir } : { key, dir: key === "name" || key === "role" ? 1 : -1 }));
	return (
		<section className="lol-sec">
			<div className="lol-tablehd">
				<h2 className="lol-h2">{title}</h2>
				<div className="lol-find">
					<input id="lol-table-filter" type="search" placeholder="Filter the list" value={filter} aria-label="Filter the champion list"
						onChange={(e) => setFilter(e.target.value)} />
				</div>
			</div>
			<p className="lol-sub">{fmt(games.length)} games. Presence is how often a champion was picked or banned. Pick a row for its partners and matchups.</p>
			<div className="lol-frame">
				<table className="lol-table">
					<thead>
						<tr>{SORTS.map(([k, label]) => (
							<th key={k} scope="col" className={k === "name" || k === "role" ? "" : "num"} aria-sort={sort.key === k ? (sort.dir > 0 ? "ascending" : "descending") : "none"}>
								<button type="button" className="lol-sort" onClick={() => by(k)}>{label}{sort.key === k ? (sort.dir > 0 ? " ▲" : " ▼") : ""}</button>
							</th>
						))}</tr>
					</thead>
					<tbody>
						{rows.map((r) => (
							<tr key={r.name}>
								<th scope="row"><button type="button" className="lol-link" onClick={() => onOpen(r.name)}>{r.name}</button></th>
								<td className="lol-dim">{r.games ? r.role : "–"}</td>
								<td className="num">{fmt(r.games)}</td>
								<td className="num">{r.games ? <span className="lol-wr" style={heat(r.winRate)}>{D.pct(r.winRate, 1)}</span> : "–"}</td>
								<td className="num">{D.pct(r.pickRate, 1)}</td>
								<td className="num">{D.pct(r.banRate, 1)}</td>
								<td className="num">{D.pct(r.presence, 1)}</td>
							</tr>
						))}
					</tbody>
				</table>
				{!rows.length && <p className="lol-sub lol-pad">No champion matches “{filter}”.</p>}
			</div>
		</section>
	);
}

function Partners({ title, sub, list, onOpen, min }) {
	return (
		<div className="lol-plist">
			<h3 className="lol-h3">{title}</h3>
			<p className="lol-psub">{sub}</p>
			{list.length ? (
				<ol className="lol-prows">
					{list.map((e) => (
						<li key={e.name} className="lol-prow">
							<button type="button" className="lol-link" onClick={() => onOpen(e.name)}>{e.name}</button>
							<span className="lol-prec">{rec(e.wins, e.games - e.wins)}</span>
							<span className="lol-wr" style={heat(e.winRate)}>{D.pct(e.winRate)}</span>
						</li>
					))}
				</ol>
			) : <p className="lol-psub">Nothing with {min}+ games together. Lower the minimum or widen the filters.</p>}
		</div>
	);
}

function StatTile({ label, value, note }) {
	return (
		<div className="lol-tile">
			<span className="lol-tile-lbl">{label}</span>
			<span className="lol-tile-val">{value}</span>
			{note && <span className="lol-tile-note">{note}</span>}
		</div>
	);
}

function ChampView({ champ, games, years, allLoaded, regions, phase, onOpen, onClose }) {
	const [min, setMin] = useState(10);
	const line = useMemo(() => D.champLine(games, champ), [games, champ]);
	const byRegion = useMemo(() => D.CHAMP_REGIONS.map((r) => [r, D.champLine(D.scope(years, { regions: [r], phase }), champ)]),
		[years, phase, champ]);
	const byYear = useMemo(() => allLoaded.map((y) => [y.year, D.champLine(D.scope([y], { regions, phase }), champ)]),
		[allLoaded, regions, phase, champ]);
	const lists = useMemo(() => {
		const withs = D.partners(games, champ, "with"), intos = D.partners(games, champ, "into");
		return {
			bestWith: D.ranked(withs, { min, best: true }), worstWith: D.ranked(withs, { min, best: false }),
			bestInto: D.ranked(intos, { min, best: true }), worstInto: D.ranked(intos, { min, best: false }),
		};
	}, [games, champ, min]);
	const a = line.avg;
	const mainRole = line.roles.reduce((b, r) => (r.games > b.games ? r : b), line.roles[0]);

	return (
		<>
			<div className="lol-champhd">
				<button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>← All champions</button>
				<h1 className="lol-h1 lol-champname">{champ}</h1>
				{line.games > 0 && <span className="lol-dim">{mainRole.role}{line.roles.filter((r) => r.games).length > 1 ? " mostly" : ""}</span>}
			</div>
			{line.games === 0 ? (
				<p className="lol-sub">{champ} was not picked in these games{line.bans ? ` (banned ${fmt(line.bans)} times)` : ""}. Try another year or more regions.</p>
			) : (
				<>
					<div className="lol-tiles">
						<StatTile label="Games" value={fmt(line.games)} note={rec(line.wins, line.games - line.wins)} />
						<StatTile label="Win rate" value={D.pct(line.winRate, 1)} />
						<StatTile label="Presence" value={D.pct(line.presence, 1)} note={`picked ${D.pct(line.pickRate)} · banned ${D.pct(line.banRate)}`} />
						<StatTile label="K / D / A" value={`${fmt(a.k, 1)} / ${fmt(a.d, 1)} / ${fmt(a.a, 1)}`} note={`KDA ${fmt(a.kda, 2)}`} />
						<StatTile label="Damage / min" value={fmt(a.dpm)} />
						<StatTile label="Gold diff @15" value={a.gd == null ? "–" : `${a.gd > 0 ? "+" : ""}${fmt(a.gd)}`}
							note={a.gdN < line.games ? `${fmt(a.gdN)} of ${fmt(line.games)} games recorded it` : "vs its lane opponent"} />
					</div>

					<section className="lol-sec">
						<div className="lol-tablehd">
							<h2 className="lol-h2">Partners and matchups</h2>
							<Chips label="At least" options={MINS.map((n) => [n, `${n} games`])} value={min} onToggle={setMin} />
						</div>
						<p className="lol-sub">{champ}’s win rate in games with each champion on its team, or on the enemy team in any role.</p>
						<div className="lol-plists">
							<Partners title="Best with" sub="Highest win rate on the same team" list={lists.bestWith} onOpen={onOpen} min={min} />
							<Partners title="Worst with" sub="Lowest win rate on the same team" list={lists.worstWith} onOpen={onOpen} min={min} />
							<Partners title="Best into" sub="Highest win rate against" list={lists.bestInto} onOpen={onOpen} min={min} />
							<Partners title="Worst into" sub="Lowest win rate against" list={lists.worstInto} onOpen={onOpen} min={min} />
						</div>
					</section>
				</>
			)}

			<section className="lol-sec">
				<h2 className="lol-h2">By region</h2>
				<p className="lol-sub">Each region on its own, whatever the region filter says. International is Worlds, MSI, First Stand and 2020’s Mid-Season Cup.</p>
				<LineTable rows={byRegion.map(([r, l]) => [r, l])} label="Region" />
			</section>
			<section className="lol-sec">
				<h2 className="lol-h2">By year</h2>
				<p className="lol-sub">Every year with the regions and games selected above.</p>
				{allLoaded.length ? <LineTable rows={byYear} label="Year" /> : <div className="lol-loading lol-loading-sm">Loading every year…</div>}
			</section>
			{line.games > 0 && (
				<section className="lol-sec">
					<h2 className="lol-h2">By role</h2>
					<div className="lol-frame">
						<table className="lol-table">
							<thead><tr><th scope="col">Role</th><th scope="col" className="num">Games</th><th scope="col" className="num">W–L</th><th scope="col" className="num">Win %</th></tr></thead>
							<tbody>
								{line.roles.filter((r) => r.games).map((r) => (
									<tr key={r.role}><th scope="row">{r.role}</th><td className="num">{fmt(r.games)}</td>
										<td className="num">{rec(r.wins, r.games - r.wins)}</td>
										<td className="num"><span className="lol-wr" style={heat(r.wins / r.games)}>{D.pct(r.wins / r.games, 1)}</span></td></tr>
								))}
							</tbody>
						</table>
					</div>
				</section>
			)}
		</>
	);
}

function LineTable({ rows, label }) {
	return (
		<div className="lol-frame">
			<table className="lol-table">
				<thead>
					<tr><th scope="col">{label}</th><th scope="col" className="num">Games</th><th scope="col" className="num">W–L</th>
						<th scope="col" className="num">Win %</th><th scope="col" className="num">Pick %</th><th scope="col" className="num">Ban %</th>
						<th scope="col" className="num">Presence</th></tr>
				</thead>
				<tbody>
					{rows.map(([k, l]) => (
						<tr key={k}>
							<th scope="row">{k}</th>
							<td className="num">{fmt(l.games)}</td>
							<td className="num">{l.games ? rec(l.wins, l.games - l.wins) : "–"}</td>
							<td className="num">{l.games ? <span className="lol-wr" style={heat(l.winRate)}>{D.pct(l.winRate, 1)}</span> : "–"}</td>
							<td className="num">{l.scope ? D.pct(l.pickRate, 1) : "–"}</td>
							<td className="num">{l.scope ? D.pct(l.banRate, 1) : "–"}</td>
							<td className="num">{l.scope ? D.pct(l.presence, 1) : "–"}</td>
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

function ChampionsTab({ champ, onOpen, onClose }) {
	const [index, setIndex] = useState(null);
	const [loaded, setLoaded] = useState({});
	const [err, setErr] = useState("");
	const [year, setYear] = useState(null);
	const [regions, setRegions] = useState(D.CHAMP_REGIONS);
	const [phase, setPhase] = useState("all");
	const searchRef = useRef(null);

	useEffect(() => {
		getJson("lol-champs-index.json").then((ix) => { setIndex(ix.years); setYear((y) => y ?? ix.years[ix.years.length - 1].year); },
			(e) => setErr(String(e.message || e)));
	}, []);
	// A champion's page shows every year (the By year table), so it loads them all;
	// the list loads only the year it shows.
	const want = !index || year == null ? [] : (champ || year === "all" ? index.map((y) => y.year) : [year]);
	useEffect(() => {
		for (const y of want) {
			if (loaded[y]) continue;
			getJson(`lol-champs-${y}.json`).then((p) => setLoaded((l) => (l[y] ? l : { ...l, [y]: D.decodeYear(p) })),
				(e) => setErr(String(e.message || e)));
		}
	}, [want.join(",")]); // eslint-disable-line react-hooks/exhaustive-deps

	// "/" focuses the search.
	useEffect(() => {
		const onKey = (e) => {
			if (e.key === "/" && !/^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "")) { e.preventDefault(); searchRef.current?.focus(); }
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);

	const yearsSel = year === "all" ? (index || []).map((y) => loaded[y.year]) : [loaded[year]];
	const ready = index && year != null && yearsSel.every(Boolean);
	const games = useMemo(() => (ready ? D.scope(yearsSel, { regions, phase }) : []), [ready, year, regions, phase, loaded]); // eslint-disable-line react-hooks/exhaustive-deps
	const allLoaded = index && index.every((y) => loaded[y.year]) ? index.map((y) => loaded[y.year]) : [];
	const names = useMemo(() => {
		const s = new Set();
		for (const y of Object.values(loaded)) for (const g of y.games) for (const c of g.picks) s.add(c);
		return [...s].sort();
	}, [loaded]);

	if (err) return <div className="lol-loading">Couldn’t load the champion data ({err}).</div>;
	const yearLabel = year === "all" ? `${index?.[0]?.year}–${index?.[index.length - 1]?.year}` : String(year);
	const latest = index?.[index.length - 1];
	const thisYear = new Date().getFullYear();

	return (
		<>
			<div className="lol-intro">
				<h1 className="lol-h1">{champ ? "Champion stats" : "Champions in pro play"}</h1>
				<p className="lol-sub">LCK, LPL, LEC and LCS regular seasons and playoffs, plus Worlds, MSI and First Stand.
					{latest && latest.year === thisYear ? ` ${latest.year} data runs through ${monthDay(latest.last)}.` : ""}</p>
			</div>
			<div className="lol-controls">
				<ChampSearch names={names} onPick={onOpen} inputRef={searchRef} />
				<Chips label="Year" options={[...(index || []).map((y) => [y.year, y.year]), ["all", "All"]]} value={year} onToggle={setYear} />
				<Chips label="Regions" multi options={D.CHAMP_REGIONS.map((r) => [r, r === "International" ? "Intl" : r])} value={regions}
					onToggle={(r) => setRegions((rs) => toggleIn(rs, r, D.CHAMP_REGIONS))} />
				<Chips label="Games" options={PHASES} value={phase} onToggle={setPhase} />
			</div>
			{!ready ? <div className="lol-loading">Loading {yearLabel}…</div> : champ ? (
				<ChampView champ={champ} games={games} years={yearsSel} allLoaded={allLoaded} regions={regions} phase={phase}
					onOpen={onOpen} onClose={onClose} />
			) : (
				<ChampTable games={games} onOpen={onOpen} title={`Champions, ${yearLabel}`} />
			)}
			<section className="lol-sec lol-notes">
				<h2 className="lol-h2">How this was counted</h2>
				<p><b>Source.</b> Game data from <a href="https://oracleselixir.com" target="_blank" rel="noreferrer">Oracle’s Elixir</a>, rebuilt from its yearly files.</p>
				<p><b>Which games.</b> The LCK, LPL, LEC and LCS, regular season and playoffs (their Worlds regional finals count as playoffs). In 2025 the LCS was the LTA North; its games against Brazilian teams are left out. Internationals are Worlds (Play-In included), MSI, First Stand and 2020’s Mid-Season Cup, with every game counted, including those against teams from smaller regions. The Esports World Cup and other invitationals are not counted. The Regular season and Playoffs filters apply to league games; internationals follow the Intl chip.</p>
				<p><b>Partners and matchups.</b> “With” is a champion on the same team. “Into” is any champion on the enemy team, not only the lane opponent. Win rates under a few dozen games swing a lot, so raise the minimum before trusting a list.</p>
			</section>
		</>
	);
}

// ── The page ────────────────────────────────────────────────────────────────
export default function LolStats({ onExit }) {
	const [tab, setTab] = useState(routeTab);
	const [champ, setChamp] = useState(hashChamp);
	const tabsRef = useRef(null);

	// Back/Forward: the path names the tab, the hash names the open champion.
	useEffect(() => subscribe((r) => {
		if (r.game !== "lolstats") return;
		setTab(routeTab());
		setChamp(hashChamp());
	}), []);

	const go = useCallback((t) => {
		setTab(t);
		setChamp(null);
		pushPath(buildPath("lolstats", t === "seeds" ? undefined : t));
		window.scrollTo({ top: 0 });
	}, []);
	const open = useCallback((name) => {
		setChamp(name);
		try { window.history.pushState(window.history.state, "", `${buildPath("lolstats", "champions")}#${encodeURIComponent(name)}`); } catch { /* sandboxed */ }
		window.scrollTo({ top: 0 });
	}, []);
	const close = useCallback(() => {
		setChamp(null);
		try { window.history.pushState(window.history.state, "", buildPath("lolstats", "champions")); } catch { /* sandboxed */ }
	}, []);

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="lol">
				<header className="lol-top">
					<div className="lol-bar">
						<button className="btn btn-ghost btn-sm lol-back" onClick={onExit}>← Back</button>
						<button type="button" className="lol-title" onClick={() => go("seeds")}>LoL Stats</button>
						<nav className="lol-tabs" role="tablist" aria-label="LoL Stats sections" ref={tabsRef}>
							{TABS.map((t) => (
								<button type="button" key={t.id} role="tab" aria-selected={tab === t.id} className="lol-tab" onClick={() => go(t.id)}>{t.label}</button>
							))}
						</nav>
					</div>
				</header>
				<main className="lol-main" data-tab={tab}>
					{tab === "champions" ? <ChampionsTab champ={champ} onOpen={open} onClose={close} /> : <SeedsTab />}
				</main>
			</div>
		</>
	);
}
