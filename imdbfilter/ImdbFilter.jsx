import { useState, useEffect, useMemo, useCallback } from "react";
import { baseCss } from "../shared/theme.js";
import { rangePointer } from "../shared/rangePointer.js";
import { KINDS, ALL_KINDS, SERIES, buildRows, passes, matches, sorter, cycleGenre, years, runtime, length } from "./derive.js";

// CSS lives in the sibling .css file, imported with `?inline` so it is still a string
// injected by this component's own <style> while mounted. Never move it back into a JS
// template literal — one stray backtick there blanked the whole site twice.
import _cssText from "./ImdbFilter.css?inline";
const css = _cssText;

// The dataset is a build artifact, fetched rather than bundled (see BggFilter.jsx).
// Harvested by .github/workflows/imdb-harvest.yml; built by imdbfilter/tools/make_data.py.
const DATA_URL = `${import.meta.env.BASE_URL || "/"}data/imdb-filter.json`;

const VOTES = [0, 25000, 50000, 100000, 250000, 500000, 1000000];
const PAGE = 50;
const STORE = "imdb_filter_dials_v1";
const YMIN = 1920;
const YMAX = new Date().getFullYear();
// Rating in tenths: 50 (5.0) reads "any", since almost nothing listed sits below it.
const RMIN = 50, RMAX = 90;
// Runtime in minutes: 0 and RTMAX read "any".
const RTMAX = 240;

const DEFAULTS = { votes: 0, rating: RMIN, yfrom: YMIN, yto: YMAX, rtmin: 0, rtmax: RTMAX,
	kinds: ALL_KINDS, inc: [], exc: [] };
const fmt = (n) => n.toLocaleString("en-US");
const one = (v, d = 1) => (v == null ? "—" : v.toFixed(d));
const short = (n) => (n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : `${n}`);

function loadDials() {
	try {
		const v = JSON.parse(localStorage.getItem(STORE) || "null");
		if (!v || typeof v !== "object") return { ...DEFAULTS };
		const out = { ...DEFAULTS };
		for (const k of ["votes", "rating", "yfrom", "yto", "rtmin", "rtmax"]) {
			if (typeof v[k] === "number" && isFinite(v[k])) out[k] = v[k];
		}
		if (Array.isArray(v.kinds)) {
			const k = ALL_KINDS.filter((x) => v.kinds.includes(x));
			if (k.length) out.kinds = k;
		}
		for (const k of ["inc", "exc"]) if (Array.isArray(v[k])) out[k] = v[k].filter((x) => typeof x === "string");
		out.votes = Math.min(VOTES.length - 1, Math.max(0, out.votes));
		out.rating = Math.min(RMAX, Math.max(RMIN, out.rating));
		out.yfrom = Math.min(YMAX, Math.max(YMIN, out.yfrom));
		out.yto = Math.min(YMAX, Math.max(out.yfrom, out.yto));
		out.rtmin = Math.min(RTMAX, Math.max(0, out.rtmin));
		out.rtmax = Math.min(RTMAX, Math.max(out.rtmin, out.rtmax));
		return out;
	} catch { return { ...DEFAULTS }; }
}

function Dial({ id, label, value, min, max, step, onChange, display }) {
	return (
		<div className="imf-knob">
			<label htmlFor={id}>{label} <span className="imf-v imf-num">{display}</span></label>
			<input id={id} type="range" min={min} max={max} step={step} value={value}
				onChange={(e) => onChange(Number(e.target.value))} {...rangePointer(onChange)} />
		</div>
	);
}

// Props: { onExit }.
export default function ImdbFilter({ onExit }) {
	const [data, setData] = useState(null);
	const [err, setErr] = useState("");
	const [d, setD] = useState(loadDials);
	const [q, setQ] = useState("");
	const [sortKey, setSortKey] = useState("w");
	const [dir, setDir] = useState(-1);
	const [limit, setLimit] = useState(PAGE);

	useEffect(() => {
		let live = true;
		fetch(DATA_URL)
			.then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.then((j) => { if (live) setData(j); })
			.catch((e) => { if (live) setErr(String(e.message || e)); });
		return () => { live = false; };
	}, []);

	useEffect(() => { try { localStorage.setItem(STORE, JSON.stringify(d)); } catch { /* private mode */ } }, [d]);

	const set = useCallback((patch) => { setD((prev) => ({ ...prev, ...patch })); setLimit(PAGE); }, []);
	// Two dials that bound one range push each other rather than crossing.
	const setPair = (lo, hi, k, v) => {
		setD((prev) => {
			const next = { ...prev, [k]: v };
			if (k === lo && next[lo] > next[hi]) next[hi] = next[lo];
			if (k === hi && next[hi] < next[lo]) next[lo] = next[hi];
			return next;
		});
		setLimit(PAGE);
	};
	// At least one kind always stays on: switching off the last one is refused.
	const toggleKind = (k) => {
		const next = d.kinds.includes(k) ? d.kinds.filter((x) => x !== k) : ALL_KINDS.filter((x) => x === k || d.kinds.includes(x));
		if (next.length) set({ kinds: next });
	};

	const rows = useMemo(() => (data ? buildRows(data) : []), [data]);
	const genres = data?.genres || [];
	const picked = useMemo(() => ({
		inc: d.inc.filter((g) => genres.includes(g)), exc: d.exc.filter((g) => genres.includes(g)),
	}), [d.inc, d.exc, genres]);

	const crit = useMemo(() => ({
		yfrom: d.yfrom > YMIN ? d.yfrom : 0, yto: d.yto < YMAX ? d.yto : 0, votes: VOTES[d.votes],
		rating: d.rating > RMIN ? d.rating / 10 : 0, rtmin: d.rtmin, rtmax: d.rtmax < RTMAX ? d.rtmax : 0,
		inc: picked.inc, exc: picked.exc,
	}), [d, picked]);
	// Every dial but the kinds, so each kind chip can say how many it would add.
	const anyKind = useMemo(() => rows.filter((r) => passes(r, crit)), [rows, crit]);
	const pool = useMemo(() => anyKind.filter((r) => d.kinds.includes(r.k)), [anyKind, d.kinds]);
	const counts = useMemo(() => {
		const g = {}, k = {};
		for (const r of anyKind) k[r.k] = (k[r.k] || 0) + 1;
		for (const r of pool) for (const x of r.g) g[x] = (g[x] || 0) + 1;
		return { g, k };
	}, [anyKind, pool]);
	const list = useMemo(() => {
		const needle = q.trim().toLowerCase();
		return pool.filter((r) => matches(r, needle)).sort(sorter(sortKey, dir));
	}, [pool, q, sortKey, dir]);

	const sortBy = (k) => {
		if (k === sortKey) setDir((v) => -v);
		else { setSortKey(k); setDir(k === "n" ? 1 : -1); }
		setLimit(PAGE);
	};
	const th = (k, label, title) => (
		<th className="imf-s" tabIndex={0} role="button" title={title}
			aria-sort={sortKey === k ? (dir === -1 ? "descending" : "ascending") : undefined}
			onClick={() => sortBy(k)}
			onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(k); } }}>
			{label}<span className="imf-arw">{dir === -1 ? "▼" : "▲"}</span>
		</th>
	);

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="imf">
				<header className="imf-header">
					<button className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
					<div className="imf-headtitle">IMDb Filter</div>
					<div className="imf-headright">{data?.collected ? `collected ${data.collected}` : ""}</div>
				</header>

				<div className="imf-hero">
					<div className="imf-logo">IMDb Filter</div>
					<p className="imf-tagline">
						Every film and series on IMDb with {data ? fmt(data.floor) : "10,000"}+ votes, ranked by a
						weighted rating that keeps a thinly-voted title from topping the list. Filter by genre,
						year, runtime, rating and votes.
					</p>
				</div>

				<div className="imf-wrap">
					{err && <div className="imf-loading">Couldn’t load the IMDb data ({err}).</div>}
					{!err && !data && <div className="imf-loading">Loading the list…</div>}
					{data && (
						<>
							<section className="imf-panel">
								<div className="imf-phead">
									<h2>Dials</h2>
									<button type="button" className="btn btn-ghost btn-sm"
										onClick={() => { setD({ ...DEFAULTS }); setLimit(PAGE); }}>Reset all dials</button>
								</div>
								<div className="imf-knobs">
									<Dial id="imf-rating" label="IMDb rating at least" min={RMIN} max={RMAX} step={1}
										value={d.rating} display={d.rating > RMIN ? (d.rating / 10).toFixed(1) : "any"}
										onChange={(v) => set({ rating: v })} />
									<Dial id="imf-votes" label="Votes at least" min={0} max={VOTES.length - 1} step={1}
										value={d.votes} display={d.votes ? `${fmt(VOTES[d.votes])}+` : "any"}
										onChange={(v) => set({ votes: v })} />
									<Dial id="imf-yfrom" label="Released from" min={YMIN} max={YMAX} step={1}
										value={d.yfrom} display={d.yfrom > YMIN ? `${d.yfrom}` : "any year"}
										onChange={(v) => setPair("yfrom", "yto", "yfrom", v)} />
									<Dial id="imf-yto" label="Released to" min={YMIN} max={YMAX} step={1}
										value={d.yto} display={d.yto < YMAX ? `${d.yto}` : "now"}
										onChange={(v) => setPair("yfrom", "yto", "yto", v)} />
									<Dial id="imf-rtmin" label="Runtime at least" min={0} max={RTMAX} step={5}
										value={d.rtmin} display={d.rtmin ? runtime(d.rtmin) : "any"}
										onChange={(v) => setPair("rtmin", "rtmax", "rtmin", v)} />
									<Dial id="imf-rtmax" label="Runtime at most" min={0} max={RTMAX} step={5}
										value={d.rtmax} display={d.rtmax < RTMAX ? runtime(d.rtmax) : "any"}
										onChange={(v) => setPair("rtmin", "rtmax", "rtmax", v)} />
								</div>

								<p className="imf-mhead">Kind — <em>a series’ runtime is one episode’s</em></p>
								<div className="imf-chips">
									{KINDS.map((x) => (
										<button type="button" key={x.k} className="imf-chip" aria-pressed={d.kinds.includes(x.k)}
											onClick={() => toggleKind(x.k)}>
											{x.label}<span className="imf-num">{fmt(counts.k[x.k] || 0)}</span>
										</button>
									))}
								</div>

								<p className="imf-mhead">Genres — <em>click once to require, again to exclude</em></p>
								<div className="imf-chips">
									{genres.map((g) => {
										const s = picked.inc.includes(g) ? "in" : picked.exc.includes(g) ? "out" : "";
										return (
											<button type="button" key={g} className="imf-chip" data-s={s || undefined}
												aria-pressed={s === "in"} aria-label={s === "out" ? `${g} (excluded)` : undefined}
												onClick={() => set(cycleGenre(picked.inc, picked.exc, g))}>
												{g}{s !== "out" && <span className="imf-num">{fmt(counts.g[g] || 0)}</span>}
											</button>
										);
									})}
								</div>

								<p className="imf-effect">
									{pool.length
										? <><b>{fmt(pool.length)}</b> of {fmt(rows.length)} titles clear these dials.</>
										: <>Nothing clears every dial. Loosen one.</>}
								</p>
							</section>

							<div className="imf-controls">
								<label className="imf-search">
									<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
										strokeWidth="2.2" aria-hidden="true">
										<circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" />
									</svg>
									<input type="search" placeholder="Filter by title, director or cast…"
										aria-label="Filter by title, director or cast"
										value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
								</label>
								<p className="imf-count"><b>{fmt(list.length)}</b> of {fmt(pool.length)} shown</p>
							</div>

							<div className="imf-tablewrap">
								<table>
									<thead>
										<tr>
											<th className="imf-pos">#</th>
											{th("n", "Title")}
											{th("w", "Weighted", `IMDb's rating with ${fmt(data.bayes.m)} votes at the mean (${data.bayes.c.toFixed(2)}) added`)}
											{th("r", "Rating", "IMDb's own average rating")}
											{th("v", "Votes")}
											{th("y", "Year")}
											{th("rt", "Runtime", "A film's length, or one episode's")}
										</tr>
									</thead>
									<tbody>
										{!list.length && (
											<tr><td className="imf-empty" colSpan={7}>
												<b>Nothing clears every dial.</b>Drop a genre, or widen the years or the runtime.
											</td></tr>
										)}
										{list.slice(0, limit).map((r, i) => {
											const len = length(r);
											const people = SERIES.has(r.k)
												? (r.c.length ? `with ${r.c.join(", ")}` : "")
												: [r.d.length ? `dir. ${r.d.join(", ")}` : "", r.c.length ? `with ${r.c.join(", ")}` : ""]
													.filter(Boolean).join(" · ");
											return (
												<tr key={r.key}>
													<td className="imf-pos imf-num">{i + 1}</td>
													<td className="imf-title">
														<a href={`https://www.imdb.com/title/${r.id}/`} target="_blank" rel="noopener noreferrer">{r.n}</a>
														{r.o && <span className="imf-of">{r.o}</span>}
														<span className="imf-tags">{[r.kind, len, ...r.g].filter(Boolean).join(" · ")}</span>
														{people && <span className="imf-people">{people}</span>}
													</td>
													<td className="imf-score imf-num"><b>{one(r.w, 2)}</b></td>
													<td className="imf-rate imf-num">{one(r.r)}</td>
													<td className="imf-votes imf-num" title={fmt(r.v)}>{short(r.v)}</td>
													<td className="imf-y imf-num">{years(r)}</td>
													<td className="imf-rt imf-num">{runtime(r.rt)}</td>
												</tr>
											);
										})}
									</tbody>
								</table>
								{list.length > limit && (
									<button className="imf-more" onClick={() => setLimit((v) => v + PAGE)}>
										Show {Math.min(list.length - limit, PAGE)} more · {fmt(list.length - limit)} remaining
									</button>
								)}
							</div>

							<section className="imf-notes">
								<div>
									<h3>The weighted rating</h3>
									<p>IMDb’s rating is the plain average of its votes, which lets a few thousand devotees
										put a film above one scored by millions. <b>Weighted</b> is IMDb’s own Top 250
										formula: every title gets {fmt(data.bayes.m)} extra votes at the list’s mean
										({data.bayes.c.toFixed(2)}), so a thinly-voted title is pulled toward the middle
										and a widely-voted one keeps its own rating. Sort by <b>Rating</b> to see the raw
										average instead.</p>
								</div>
								<div>
									<h3>Scope</h3>
									<p>The <b>{fmt(data.count)}</b> films, TV films, series and mini-series on IMDb with{" "}
										{fmt(data.floor)}+ votes. Shorts, episodes, specials, video games and adult titles
										are left out. A series shows its seasons, its episode count and one episode’s
										runtime; a film shows its directors. Both show the top-billed cast.</p>
									<p>Your dial settings are remembered in this browser.</p>
								</div>
								<div>
									<h3>Source</h3>
									<p>IMDb’s non-commercial datasets, collected {data.collected} and refreshed monthly.
										Titles are IMDb’s primary ones, with the original title beneath where it
										differs.</p>
									<p>Information courtesy of IMDb (<a href="https://www.imdb.com" target="_blank"
										rel="noopener noreferrer">www.imdb.com</a>). Used with permission.</p>
								</div>
							</section>
						</>
					)}
				</div>
			</div>
		</>
	);
}
