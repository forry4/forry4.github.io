import { useState, useEffect, useMemo, useCallback } from "react";
import { baseCss } from "../shared/theme.js";

// CSS lives in the sibling .css file, imported with `?inline` so it is still a string
// injected by this component's own <style> while mounted. Never move it back into a JS
// template literal — one stray backtick there blanked the whole site twice.
import _cssText from "./BggFilter.css?inline";
const css = _cssText;

// The dataset is a build artifact, not a bundle import: at ~1MB it would bloat the lazy
// chunk for everyone who opens the page, so it is fetched once on mount and cached by the
// CDN like any other static asset. Regenerate with bggfilter/tools/make_data.py.
const DATA_URL = `${import.meta.env.BASE_URL || "/"}data/bgg-filter.json`;

const RATINGS = [100, 250, 500, 1000, 2000, 3000, 5000, 10000, 20000, 50000, 100000];
const COUNTS = ["2", "3", "4"];
const PAGE = 50;
// v2: the ratings dial is an INDEX into RATINGS, and RATINGS grew a 100/250 floor at the
// front — a v1 value would silently mean a different threshold than the one it was saved at.
const STORE = "bgg_filter_dials_v2";

// The oldest entries are ancient abstracts (year 1000 up) and the median is 2015, so a
// linear slider from the true minimum would bury 99% of the data in its last few pixels.
// The dial floors here and that position means "any year" — nothing is excluded there.
const YMIN = 1970;

const DEFAULTS = { wmin: 1.5, wmax: 3.5, rat: RATINGS.indexOf(1000), yr: YMIN, b2: 60, b3: 0, b4: 0, r2: 0, r3: 0, r4: 0 };
const fmt = (n) => n.toLocaleString("en-US");

function loadDials() {
	try {
		const v = JSON.parse(localStorage.getItem(STORE) || "null");
		if (!v || typeof v !== "object") return { ...DEFAULTS };
		const out = { ...DEFAULTS };
		for (const k of Object.keys(DEFAULTS)) {
			if (typeof v[k] === "number" && isFinite(v[k])) out[k] = v[k];
		}
		return out;
	} catch { return { ...DEFAULTS }; }
}

// Percentages are derived once per dataset so filtering and sorting stay plain lookups.
// A count with no votes reads -1, which fails every threshold above zero while still
// rendering as "no votes" rather than 0%.
function derive(games) {
	for (const g of games) {
		for (const k of COUNTS) {
			const row = g.p[k];
			const tot = row ? row[0] + row[1] + row[2] : 0;
			g["t" + k] = tot;
			g["b" + k] = tot ? (row[0] / tot) * 100 : -1;
			g["r" + k] = tot ? ((row[0] + row[1]) / tot) * 100 : -1;
		}
		if (!g.pt) g.pt = Math.max(g.t2 || 0, g.t3 || 0, g.t4 || 0);
		// F average — the midpoint of the two ratings either side of it in the table. The
		// Geek rating drags an unproven game towards the mean and the raw average lets forty
		// devotees crown one, so the blend sits between the pessimist and the optimist.
		g.f = (g.geek + g.avg) / 2;
	}
	return games;
}

// The poll size rides ALONG WITH the percentage it is the denominator of, rather than in a
// column of its own: one number per row could only ever describe the biggest poll, and it is
// the count-by-count denominator that decides whether that count's bar means anything.
function Bar({ g, k }) {
	const tot = g["t" + k];
	if (!tot) return (
		<td className="bgf-pc"><div className="bgf-bar" /><div className="bgf-pcnum bgf-none">no votes</div></td>
	);
	const row = g.p[k];
	const b = (row[0] / tot) * 100, r = (row[1] / tot) * 100;
	return (
		<td className={`bgf-pc${tot < 100 ? " bgf-thin" : ""}`} title={`${fmt(tot)} poll votes at ${k} players`}>
			<div className="bgf-bar" role="img"
				aria-label={`${b.toFixed(0)}% best, ${(b + r).toFixed(0)}% best or recommended at ${k} players`}>
				<span className="bgf-b" style={{ width: `${b}%` }} />
				<span className="bgf-r" style={{ left: `${b}%`, width: `${r}%` }} />
			</div>
			<div className="bgf-pcnum bgf-num">{b.toFixed(0)}%<span> / {(b + r).toFixed(0)}%</span></div>
		</td>
	);
}

function Dial({ id, label, value, min, max, step, onChange, display }) {
	return (
		<div className="bgf-knob">
			<label htmlFor={id}>{label} <span className="bgf-v bgf-num">{display}</span></label>
			<input id={id} type="range" min={min} max={max} step={step} value={value}
				onChange={(e) => onChange(Number(e.target.value))} />
		</div>
	);
}

// Props: { onExit }.
export default function BggFilter({ onExit }) {
	const [games, setGames] = useState(null);
	const [err, setErr] = useState("");
	const [meta, setMeta] = useState(null);
	const [d, setD] = useState(loadDials);
	const [q, setQ] = useState("");
	const [sortKey, setSortKey] = useState("geek");
	const [dir, setDir] = useState(-1);
	const [limit, setLimit] = useState(PAGE);

	useEffect(() => {
		let live = true;
		fetch(DATA_URL)
			.then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.then((j) => { if (live) { setMeta(j); setGames(derive(j.games)); } })
			.catch((e) => { if (live) setErr(String(e.message || e)); });
		return () => { live = false; };
	}, []);

	useEffect(() => { try { localStorage.setItem(STORE, JSON.stringify(d)); } catch { /* private mode */ } }, [d]);

	// Dragging one complexity end past the other pushes it along, so the range can never invert.
	const setDial = useCallback((k, v) => {
		setD((prev) => {
			const next = { ...prev, [k]: v };
			if (k === "wmin" && next.wmin > next.wmax) next.wmax = next.wmin;
			if (k === "wmax" && next.wmax < next.wmin) next.wmin = next.wmax;
			return next;
		});
		setLimit(PAGE);
	}, []);

	const pass = useCallback((g) => {
		if (g.w < d.wmin || g.w > d.wmax) return false;
		if (g.v < RATINGS[d.rat]) return false;
		if (d.yr > YMIN && (!g.y || g.y < d.yr)) return false;
		for (const k of COUNTS) {
			if (d["b" + k] > 0 && !(g["b" + k] >= d["b" + k])) return false;
			if (d["r" + k] > 0 && !(g["r" + k] >= d["r" + k])) return false;
		}
		return true;
	}, [d]);

	const pool = useMemo(() => (games || []).filter(pass), [games, pass]);
	const view = useMemo(() => {
		const needle = q.trim().toLowerCase();
		const rows = needle ? pool.filter((g) => g.n.toLowerCase().includes(needle)) : pool.slice();
		rows.sort((a, b) => {
			const x = a[sortKey], y = b[sortKey];
			const c = typeof x === "string" ? x.localeCompare(y) : x - y;
			return c * dir || a.n.localeCompare(b.n);
		});
		return rows;
	}, [pool, q, sortKey, dir]);

	const sortBy = (k) => {
		if (k === sortKey) setDir((v) => -v);
		else { setSortKey(k); setDir(k === "n" ? 1 : -1); }
		setLimit(PAGE);
	};

	const th = (k, label) => (
		<th className="bgf-s" tabIndex={0} role="button"
			aria-sort={sortKey === k ? (dir === -1 ? "descending" : "ascending") : undefined}
			onClick={() => sortBy(k)}
			onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(k); } }}>
			{label}<span className="bgf-arw">{dir === -1 ? "▼" : "▲"}</span>
		</th>
	);

	const pctDial = (k, which, label) => {
		const id = which + k;
		return (
			<div className="bgf-mrow" key={id}>
				<label htmlFor={id}>{label} <span className="bgf-v bgf-num">{d[id] ? `${d[id]}%` : "off"}</span></label>
				<input id={id} type="range" min="0" max="100" step="5" value={d[id]}
					onChange={(e) => setDial(id, Number(e.target.value))} />
			</div>
		);
	};

	const solid = pool.filter((g) => g.pt >= 100).length;

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="bgf">
				<header className="bgf-header">
					<button className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
					<div className="bgf-headtitle">BGG Filter</div>
					<div className="bgf-headright">{meta ? `collected ${meta.collected}` : ""}</div>
				</header>

				<div className="bgf-hero">
					<div className="bgf-logo">BGG Filter</div>
					<p className="bgf-tagline">
						Every ranked game on BoardGameGeek with 100 or more ratings. Dial in complexity,
						ratings, year, and how strongly players vouch for the game at two, three or four.
					</p>
				</div>

				<div className="bgf-wrap">
					{err && <div className="bgf-loading">Couldn’t load the game data ({err}).</div>}
					{!err && !games && <div className="bgf-loading">Loading the ranked list…</div>}

					{games && (
						<>
							<section className="bgf-panel">
								<div className="bgf-phead">
									<h2>The game itself</h2>
									<button type="button" className="btn btn-ghost btn-sm"
										onClick={() => { setD({ ...DEFAULTS }); setLimit(PAGE); }}>Reset all dials</button>
								</div>
								<div className="bgf-knobs">
									<Dial id="wmin" label="Complexity from" min={1} max={5} step={0.1}
										value={d.wmin} display={d.wmin.toFixed(1)} onChange={(v) => setDial("wmin", v)} />
									<Dial id="wmax" label="Complexity to" min={1} max={5} step={0.1}
										value={d.wmax} display={d.wmax.toFixed(1)} onChange={(v) => setDial("wmax", v)} />
									<Dial id="rat" label="Minimum ratings" min={0} max={RATINGS.length - 1} step={1}
										value={d.rat} display={`${fmt(RATINGS[d.rat])}+`} onChange={(v) => setDial("rat", v)} />
									<Dial id="yr" label="Published from" min={YMIN} max={2026} step={1}
										value={d.yr} display={d.yr > YMIN ? `${d.yr}+` : "any year"}
										onChange={(v) => setDial("yr", v)} />
								</div>

								<p className="bgf-mhead">Player-count fit —{" "}
									<em>the share of poll voters who rate that count Best, or Best or Recommended</em></p>
								<div className="bgf-matrix">
									{COUNTS.map((k) => (
										<div className="bgf-mcell" key={k}>
											<h3>{k} players</h3>
											{pctDial(k, "b", "Best at least")}
											{pctDial(k, "r", "Best or Rec. at least")}
										</div>
									))}
								</div>

								<p className="bgf-effect">
									{pool.length
										? <><b>{fmt(pool.length)}</b> of {fmt(games.length)} games clear these dials — <b>{fmt(solid)}</b> with a poll of 100+ votes behind them.</>
										: <>No game clears every dial. Loosen one.</>}
								</p>
							</section>

							<div className="bgf-controls">
								<label className="bgf-search">
									<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
										strokeWidth="2.2" aria-hidden="true">
										<circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" />
									</svg>
									<input type="search" placeholder="Filter by title…" aria-label="Filter by title"
										value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
								</label>
								<span className="bgf-legend">
									<span><i style={{ background: "var(--gold)" }} />Best</span>
									<span><i style={{ background: "var(--gold)", opacity: .32 }} />Recommended</span>
								</span>
								<p className="bgf-count"><b>{fmt(view.length)}</b> of {fmt(pool.length)} shown</p>
							</div>

							<div className="bgf-tablewrap">
								<table>
									<thead>
										<tr>
											<th className="bgf-pos">#</th>
											{th("n", "Game")}
											{th("geek", "Geek rating")}
											{th("f", "F average")}
											{th("avg", "Average")}
											{th("w", "Complexity")}
											{th("b2", "2 players")}
											{th("b3", "3 players")}
											{th("b4", "4 players")}
											{th("v", "Ratings")}
										</tr>
									</thead>
									<tbody>
										{!view.length && (
											<tr><td className="bgf-empty" colSpan={10}>
												<b>Nothing clears every dial.</b>Loosen one — the player-count minimums bite hardest.
											</td></tr>
										)}
										{view.slice(0, limit).map((g, i) => (
											<tr key={g.id}>
												<td className="bgf-pos bgf-num">{i + 1}</td>
												<td className="bgf-game">
													<a href={`https://boardgamegeek.com/boardgame/${g.id}`}
														target="_blank" rel="noopener noreferrer">{g.n}</a>
													<span className="bgf-yr bgf-num">{g.y || ""}</span>
													<span className="bgf-rank">BGG rank #{g.rk}</span>
												</td>
												<td className="bgf-geek bgf-num"><b>{g.geek.toFixed(3)}</b></td>
												<td className="bgf-f bgf-num">{g.f.toFixed(2)}</td>
												<td className="bgf-avg bgf-num">{g.avg.toFixed(2)}</td>
												<td className="bgf-wt">
													<div className="bgf-scale">
														<span className="bgf-seg" role="img" aria-label={`Complexity ${g.w.toFixed(2)} of 5`}>
															<i style={{ width: `${(g.w / 5) * 100}%` }} />
														</span>
														<span className="bgf-v2 bgf-num">{g.w.toFixed(2)}</span>
													</div>
												</td>
												<Bar g={g} k="2" /><Bar g={g} k="3" /><Bar g={g} k="4" />
												<td className="bgf-v bgf-num">{fmt(g.v)}</td>
											</tr>
										))}
									</tbody>
								</table>
								{view.length > limit && (
									<button className="bgf-more" onClick={() => setLimit((v) => v + PAGE)}>
										Show {Math.min(view.length - limit, PAGE)} more · {fmt(view.length - limit)} remaining
									</button>
								)}
							</div>

							<section className="bgf-notes">
								<div>
									<h3>What the percentages mean</h3>
									<p>BGG’s poll lets every voter mark each player count Best, Recommended or Not
										Recommended, independently. <b>Best</b> is the share of people who expressed an
										opinion about that count and called it the best; <b>Best or Recommended</b> adds
										those who said it merely works.</p>
									<p>The two dials stack: asking for 60% Best and 90% Best-or-Recommended finds games
										genuinely at their peak there that almost nobody thinks are bad there.</p>
								</div>
								<div>
									<h3>Watch the poll size</h3>
									<p>Far fewer people answer the poll than rate the game, and a thin poll produces loud
										percentages — 100% off 40 voters is much weaker than 97% off 1,500. A count with
										fewer than 100 votes behind it is printed in amber; hover any bar for its vote
										count.</p>
									<p>A 60% bar also means different things at different counts, and the middle one is the
										harsh one: votes at three spread onto its neighbours, while two and four sit at the
										ends of the usual range and collect concentrated ones. Asking 80% Best finds
										hundreds of games at two or four players, and a few dozen at three.</p>
								</div>
								<div>
									<h3>Scope</h3>
									<p><b>{fmt(games.length)}</b> ranked games with 100+ ratings. Alternate editions and
										big boxes are excluded — BGG leaves them out of its ranking, so their Geek ratings
										aren’t comparable.</p>
									<p>The year dial floors at 1970, where it means <em>any year</em>; older games and
										those with no year on file sit below it. Your dial settings are remembered in this
										browser.</p>
								</div>
							</section>
						</>
					)}
				</div>
			</div>
		</>
	);
}
