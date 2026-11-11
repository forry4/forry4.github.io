import { useState, useEffect, useMemo, useCallback, Fragment } from "react";
import { baseCss } from "../shared/theme.js";
import { rangePointer } from "../shared/rangePointer.js";
import { fetchData } from "../shared/dataUrl.js";
import { SITES, ALL_SITES, DUB, FORMAT, rescore, seasonRows, showRows, passes, matches, sorter } from "./derive.js";

// CSS lives in the sibling .css file, imported with `?inline` so it is still a string
// injected by this component's own <style> while mounted. Never move it back into a JS
// template literal — one stray backtick there blanked the whole site twice.
import _cssText from "./AnimeFilter.css?inline";
const css = _cssText;

// The dataset is a build artifact, fetched rather than bundled (see BggFilter.jsx).
// Harvested by .github/workflows/anime-harvest.yml; built by animefilter/tools/make_data.py.
// Read through shared/dataUrl.js: the data store's copy (refreshed with no commit and
// no deploy), else the copy bundled with the site.
const DATA_FILE = "anime-filter.json";

const MEMBERS = [0, 50000, 100000, 250000, 500000, 1000000, 2000000];
const PAGE = 50;
const STORE = "anime_filter_dials_v1";
const YMIN = 1980;
const YMAX = new Date().getFullYear();
const DEMOS = ["Shounen", "Seinen", "Shoujo", "Josei"];

const DEFAULTS = { mem: 0, yfrom: YMIN, yto: YMAX, dub: "any", fmt: "any", demo: "any", jp: false,
	sites: ALL_SITES, genres: [], tags: [] };
const fmt = (n) => n.toLocaleString("en-US");
const one = (v, d = 2) => (v == null ? "—" : v.toFixed(d));

function loadDials() {
	try {
		const v = JSON.parse(localStorage.getItem(STORE) || "null");
		if (!v || typeof v !== "object") return { ...DEFAULTS };
		const out = { ...DEFAULTS };
		for (const k of ["mem", "yfrom", "yto"]) if (typeof v[k] === "number" && isFinite(v[k])) out[k] = v[k];
		if (DUB.some(([k]) => k === v.dub)) out.dub = v.dub;
		if (FORMAT.some(([k]) => k === v.fmt)) out.fmt = v.fmt;
		if (DEMOS.includes(v.demo)) out.demo = v.demo;
		out.jp = v.jp === true;
		if (Array.isArray(v.sites)) {
			const s = ALL_SITES.filter((k) => v.sites.includes(k));
			if (s.length) out.sites = s;
		}
		for (const k of ["genres", "tags"]) if (Array.isArray(v[k])) out[k] = v[k].filter((x) => typeof x === "string");
		out.mem = Math.min(MEMBERS.length - 1, Math.max(0, out.mem));
		out.yfrom = Math.min(YMAX, Math.max(YMIN, out.yfrom));
		out.yto = Math.min(YMAX, Math.max(out.yfrom, out.yto));
		return out;
	} catch { return { ...DEFAULTS }; }
}

function Dial({ id, label, value, min, max, step, onChange, display }) {
	return (
		<div className="anf-knob">
			<label htmlFor={id}>{label} <span className="anf-v anf-num">{display}</span></label>
			<input id={id} type="range" min={min} max={max} step={step} value={value}
				onChange={(e) => onChange(Number(e.target.value))} {...rangePointer(onChange)} />
		</div>
	);
}

function Dub({ d }) {
	if (d === 2) return <i className="anf-dub" title="English dub available">Dub</i>;
	if (d === 1) return <i className="anf-dub anf-dub-part" title="An English dub exists for part of it">Part dub</i>;
	return null;
}

function Seg({ label, options, value, onPick }) {
	return (
		<div className="anf-seg" role="group" aria-label={label}>
			{options.map(([k, l]) => (
				<button type="button" key={k} aria-pressed={value === k} onClick={() => onPick(k)}>{l}</button>
			))}
		</div>
	);
}

// Props: { onExit }.
export default function AnimeFilter({ onExit }) {
	const [data, setData] = useState(null);
	// PHONES OPEN ON THE RESULTS. The dials are several screens tall at 390px, so the
	// list they filter started far below the fold; there they begin folded behind one
	// button, with the "N of M clear these dials" line still showing. The fold is
	// CSS-scoped to the phone tier, so on a wide screen this state does nothing.
	const [dialsOpen, setDialsOpen] = useState(() => {
		try { return !window.matchMedia("(max-width:640px)").matches; } catch { return true; }
	});
	const [err, setErr] = useState("");
	const [d, setD] = useState(loadDials);
	const [q, setQ] = useState("");
	const [view, setView] = useState("shows");
	const [sortKey, setSortKey] = useState("s");
	const [dir, setDir] = useState(-1);
	const [limit, setLimit] = useState(PAGE);
	const [open, setOpen] = useState(() => new Set());

	useEffect(() => {
		let live = true;
		fetchData(DATA_FILE)
			.then((j) => { if (live) setData(j); })
			.catch((e) => { if (live) setErr(String(e.message || e)); });
		return () => { live = false; };
	}, []);

	useEffect(() => { try { localStorage.setItem(STORE, JSON.stringify(d)); } catch { /* private mode */ } }, [d]);

	const set = useCallback((patch) => { setD((prev) => ({ ...prev, ...patch })); setLimit(PAGE); }, []);
	const setYear = (k, v) => setD((prev) => {
		const next = { ...prev, [k]: v };
		if (k === "yfrom" && next.yfrom > next.yto) next.yto = next.yfrom;
		if (k === "yto" && next.yto < next.yfrom) next.yfrom = next.yto;
		return next;
	});
	const toggle = (k, x) => set({ [k]: d[k].includes(x) ? d[k].filter((y) => y !== x) : [...d[k], x] });
	// At least one site always counts: switching off the last one is refused.
	const toggleSite = (k) => {
		const next = d.sites.includes(k) ? d.sites.filter((s) => s !== k) : ALL_SITES.filter((s) => s === k || d.sites.includes(s));
		if (next.length) set({ sites: next });
	};

	const shows = data?.shows || [];
	const rows = useMemo(() => {
		if (!data) return [];
		const base = view === "seasons" ? seasonRows(shows) : showRows(shows);
		return rescore(base, data.scale, d.sites);
	}, [data, shows, view, d.sites]);

	const genres = data?.genres || [];
	const tags = data?.tags || [];
	const picked = useMemo(() => ({
		genres: d.genres.filter((g) => genres.includes(g)), tags: d.tags.filter((t) => tags.includes(t)),
	}), [d.genres, d.tags, genres, tags]);

	const crit = useMemo(() => ({
		yfrom: d.yfrom > YMIN ? d.yfrom : 0, yto: d.yto < YMAX ? d.yto : 0, dub: d.dub, fmt: d.fmt,
		demo: d.demo, jp: d.jp, members: MEMBERS[d.mem], genres: picked.genres, tags: picked.tags,
	}), [d, picked]);
	const pool = useMemo(() => rows.filter((r) => passes(r, crit)), [rows, crit]);
	// A chip's count is how many rows the list would hold with that chip on as well.
	const counts = useMemo(() => {
		const g = {}, t = {};
		for (const r of pool) {
			for (const x of r.g) g[x] = (g[x] || 0) + 1;
			for (const x of r.t) t[x] = (t[x] || 0) + 1;
		}
		return { g, t };
	}, [pool]);
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
		<th className="anf-s" tabIndex={0} role="button" title={title}
			aria-sort={sortKey === k ? (dir === -1 ? "descending" : "ascending") : undefined}
			onClick={() => sortBy(k)}
			onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(k); } }}>
			{label}<span className="anf-arw">{dir === -1 ? "▼" : "▲"}</span>
		</th>
	);
	const flip = (id) => setOpen((prev) => {
		const n = new Set(prev);
		if (n.has(id)) n.delete(id); else n.add(id);
		return n;
	});

	const c = data?.compare;
	const siteOn = (k) => d.sites.includes(k);

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="anf site-ground">
				<header className="anf-header">
					<button className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
					<div className="anf-headtitle">Anime Filter</div>
					<div className="anf-headright">{data?.collected ? `collected ${data.collected}` : ""}</div>
				</header>

				<div className="anf-hero">
					<div className="anf-logo">Anime Filter</div>
					<p className="anf-tagline">
						The top {data?.top || 500} anime by MyAnimeList, AniList and Kitsu together, with each
						show’s seasons averaged into one score. Filter by genre, tag, year and English dub.
					</p>
				</div>

				<div className="anf-wrap">
					{err && <div className="anf-loading">Couldn’t load the anime data ({err}).</div>}
					{!err && !data && <div className="anf-loading">Loading the list…</div>}
					{data && (
						<>
							<section className={`anf-panel${dialsOpen ? "" : " is-folded"}`}>
								<div className="anf-phead">
									<h2>Dials</h2>
									<button type="button" className="btn btn-ghost btn-sm anf-fold" aria-expanded={dialsOpen}
										onClick={() => setDialsOpen((o) => !o)}>{dialsOpen ? "Hide dials" : "Show dials"}</button>
									<button type="button" className="btn btn-ghost btn-sm"
										onClick={() => { setD({ ...DEFAULTS }); setLimit(PAGE); }}>Reset all dials</button>
								</div>
								<div className="anf-knobs">
									<Dial id="anf-yfrom" label="First aired from" min={YMIN} max={YMAX} step={1}
										value={d.yfrom} display={d.yfrom > YMIN ? `${d.yfrom}` : "any year"}
										onChange={(v) => { setYear("yfrom", v); setLimit(PAGE); }} />
									<Dial id="anf-yto" label="First aired to" min={YMIN} max={YMAX} step={1}
										value={d.yto} display={d.yto < YMAX ? `${d.yto}` : "now"}
										onChange={(v) => { setYear("yto", v); setLimit(PAGE); }} />
									<Dial id="anf-mem" label="MAL members at least" min={0} max={MEMBERS.length - 1} step={1}
										value={d.mem} display={d.mem ? `${fmt(MEMBERS[d.mem])}+` : "any"}
										onChange={(v) => set({ mem: v })} />
								</div>

								<div className="anf-rowset">
									<div>
										<p className="anf-mhead">English dub</p>
										<Seg label="English dub" options={DUB} value={d.dub} onPick={(k) => set({ dub: k })} />
									</div>
									<div>
										<p className="anf-mhead">Format — <em>of the first season</em></p>
										<Seg label="Format" options={FORMAT} value={d.fmt} onPick={(k) => set({ fmt: k })} />
									</div>
									<div>
										<p className="anf-mhead">Demographic</p>
										<Seg label="Demographic" options={[["any", "Any"], ...DEMOS.map((x) => [x, x])]}
											value={d.demo} onPick={(k) => set({ demo: k })} />
									</div>
									<div>
										<p className="anf-mhead">Origin</p>
										<Seg label="Origin" options={[["all", "Any"], ["jp", "Japanese only"]]}
											value={d.jp ? "jp" : "all"} onPick={(k) => set({ jp: k === "jp" })} />
									</div>
								</div>

								<p className="anf-mhead">Sites in the score — <em>switch one off to see the list without it</em></p>
								<div className="anf-chips">
									{SITES.map((s) => (
										<button type="button" key={s.k} className="anf-chip" aria-pressed={siteOn(s.k)}
											onClick={() => toggleSite(s.k)}>{s.label}</button>
									))}
								</div>

								<p className="anf-mhead">Genres — <em>a show must have every one you pick</em></p>
								<div className="anf-chips">
									{genres.map((g) => (
										<button type="button" key={g} className="anf-chip" aria-pressed={picked.genres.includes(g)}
											onClick={() => toggle("genres", g)}>
											{g}<span className="anf-num">{fmt(counts.g[g] || 0)}</span>
										</button>
									))}
								</div>

								<details className="anf-more-tags" open={picked.tags.length > 0 || undefined}>
									<summary>Tags{picked.tags.length ? ` · ${picked.tags.length} picked` : ""} — <em>AniList’s, the strongest few per show</em></summary>
									<div className="anf-chips">
										{tags.map((t) => (
											<button type="button" key={t} className="anf-chip" aria-pressed={picked.tags.includes(t)}
												onClick={() => toggle("tags", t)}>
												{t}<span className="anf-num">{fmt(counts.t[t] || 0)}</span>
											</button>
										))}
									</div>
								</details>

								<p className="anf-effect">
									{pool.length
										? <><b>{fmt(pool.length)}</b> of {fmt(rows.length)} {view === "seasons" ? "seasons and films" : "shows"} clear these dials.</>
										: <>Nothing clears every dial. Loosen one.</>}
								</p>
							</section>

							<div className="anf-controls">
								<Seg label="Rows" options={[["shows", "Shows · seasons averaged"], ["seasons", "Each season"]]}
									value={view} onPick={(k) => { setView(k); setLimit(PAGE); }} />
								<label className="anf-search">
									<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
										strokeWidth="2.2" aria-hidden="true">
										<circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" />
									</svg>
									<input type="search" placeholder="Filter by title…" aria-label="Filter by title"
										value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
								</label>
								<p className="anf-count"><b>{fmt(list.length)}</b> of {fmt(pool.length)} shown</p>
							</div>

							<div className="anf-tablewrap">
								<table>
									<thead>
										<tr>
											<th className="anf-pos">#</th>
											{th("n", "Title")}
											{th("s", "Score", "The three sites combined, on MyAnimeList's scale")}
											{SITES.map((s) => <Fragment key={s.k}>{th(s.k, s.short)}</Fragment>)}
											{th("y", view === "seasons" ? "Aired" : "First aired")}
											{view === "shows" && th("seasons", "Seasons")}
											{th("mv", "MAL members")}
										</tr>
									</thead>
									<tbody>
										{!list.length && (
											<tr><td className="anf-empty" colSpan={view === "shows" ? 9 : 8}>
												<b>Nothing clears every dial.</b>Drop a genre or tag, or widen the years.
											</td></tr>
										)}
										{list.slice(0, limit).map((r, i) => {
											const isOpen = view === "shows" && open.has(r.id);
											return (
												<Fragment key={r.key}>
													<tr className={isOpen ? "anf-open" : undefined}>
														<td className="anf-pos anf-num">{i + 1}</td>
														<td className="anf-title">
															<a href={`https://anilist.co/anime/${r.id}`} target="_blank" rel="noopener noreferrer">{r.n}</a>
															<Dub d={r.dub} />
															{view === "seasons" && r.show.p.length > 1 && <span className="anf-of">of {r.show.n}</span>}
															{view === "shows" && r.r && r.r.toLowerCase() !== r.n.toLowerCase() && <span className="anf-of">{r.r}</span>}
															<span className="anf-tags">
																{[r.f, r.dm, ...r.g].filter(Boolean).join(" · ")}
																{r.t.length > 0 && <span className="anf-tagline2">{r.t.join(" · ")}</span>}
															</span>
														</td>
														<td className="anf-score anf-num"><b>{one(r.s)}</b></td>
														{SITES.map((s) => (
															<td key={s.k} className={`anf-site anf-num${siteOn(s.k) ? "" : " anf-off"}`}>{one(r[s.k])}</td>
														))}
														<td className="anf-y anf-num">{r.y || "—"}</td>
														{view === "shows" && (
															<td className="anf-n">
																{r.seasons > 1
																	? <button type="button" className="anf-expand" aria-expanded={isOpen}
																		onClick={() => flip(r.id)}>{r.seasons} {isOpen ? "▴" : "▾"}</button>
																	: <span className="anf-num">1</span>}
															</td>
														)}
														<td className="anf-mv anf-num">{r.mv ? fmt(r.mv) : "—"}</td>
													</tr>
													{isOpen && r.p.map((p) => (
														<tr key={`p${p.id}`} className="anf-part">
															<td />
															<td className="anf-title">
																<a href={p.mal ? `https://myanimelist.net/anime/${p.mal}` : `https://anilist.co/anime/${p.id}`}
																	target="_blank" rel="noopener noreferrer">{p.n}</a>
																<Dub d={p.d} />
																<span className="anf-tags">{p.f}{p.e ? ` · ${p.e} ep` : ""}{p.mr ? ` · MAL rank #${fmt(p.mr)}` : ""}</span>
															</td>
															<td className="anf-score anf-num">{one(rescore([{ ...p }], data.scale, d.sites)[0].s)}</td>
															{SITES.map((s) => (
																<td key={s.k} className={`anf-site anf-num${siteOn(s.k) ? "" : " anf-off"}`}>{one(p[s.k])}</td>
															))}
															<td className="anf-y anf-num">{p.y || "—"}</td>
															<td /><td />
														</tr>
													))}
												</Fragment>
											);
										})}
									</tbody>
								</table>
								{list.length > limit && (
									<button className="anf-more" onClick={() => setLimit((v) => v + PAGE)}>
										Show {Math.min(list.length - limit, PAGE)} more · {fmt(list.length - limit)} remaining
									</button>
								)}
							</div>

							<section className="anf-notes">
								<div>
									<h3>The score</h3>
									<p>Each site scores on its own curve — Kitsu’s bunches tightly, MAL’s stretches
										out at the top — so each site’s score is measured against that site’s own spread
										(how far above its average a show sits), the sites are averaged, and the result is
										written on MyAnimeList’s scale. Switch a site off and the list re-ranks without it.</p>
									<p>A season’s score on a site counts once it has {fmt(data.floors.m)}+ members on
										MAL, {fmt(data.floors.a)}+ list adds on AniList, or {fmt(data.floors.k)}+ ratings
										on Kitsu.</p>
								</div>
								<div>
									<h3>Seasons averaged</h3>
									<p>Seasons and films joined by sequel links on AniList are one show, and on each
										site the show scores the plain average of its seasons — each counts once, whatever
										its length. The show is named after its first season, and dated by it.</p>
									{c && (
										<p>Ranked season by season, MAL’s top 100 holds only <b>{c.mal_top100_shows}</b>{" "}
											different shows — {c.most_spots} alone takes {c.most_spots_n} places. Here{" "}
											{c.multi_season} of the {data.top} are multi-season shows, each in one row. Pick{" "}
											<b>Each season</b> to see them split out again.</p>
									)}
								</div>
								<div>
									<h3>Dubs, genres and tags</h3>
									<p><b>Dub</b> means an English dub exists for every season, <b>Part dub</b> for some
										of them, or one still being made. It comes from MAL-Dubs, a community list keyed to
										MyAnimeList.</p>
									<p>Genres are AniList’s across every season. Tags are AniList’s community tags
										without spoilers, the few most relevant to the whole show.</p>
								</div>
								<div>
									<h3>Scope</h3>
									<p>The top <b>{fmt(shows.length)}</b> shows with {fmt(data.min_members)}+ members on
										MyAnimeList (counting their most-watched season), rated on at least two of the three
										sites. TV, web series and films; specials and OVAs are left out. English titles
										where one exists.</p>
									<p>Your dial settings are remembered in this browser.</p>
								</div>
							</section>
						</>
					)}
				</div>
			</div>
		</>
	);
}
