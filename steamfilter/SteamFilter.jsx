import { useState, useEffect, useMemo, useCallback } from "react";
import { baseCss } from "../shared/theme.js";
import { rangePointer } from "../shared/rangePointer.js";

// CSS lives in the sibling .css file, imported with `?inline` so it is still a string
// injected by this component's own <style> while mounted. Never move it back into a JS
// template literal — one stray backtick there blanked the whole site twice.
import _cssText from "./SteamFilter.css?inline";
const css = _cssText;

// The dataset is a build artifact, fetched rather than bundled (see BggFilter.jsx).
// Regenerate with steamfilter/tools/scan_steam.py + make_data.py.
const DATA_URL = `${import.meta.env.BASE_URL || "/"}data/steam-filter.json`;

const REVIEWS = [50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000];
const PAGE = 50;
const STORE = "steam_filter_dials_v1";

// Steam opened its store to other publishers in 2005; the few older dates are
// re-releases. The floor position means "any year", the ceiling "up to now".
const YMIN = 2005;
const YMAX = new Date().getFullYear();

// `cats`: category ids a game must ALL carry (AND, so Roguelike + Card game finds the
// roguelike deckbuilders). `sw`: "any", "yes" (on Nintendo Switch) or "no".
const DEFAULTS = { rev: REVIEWS.indexOf(500), yfrom: YMIN, yto: YMAX, cats: [], sw: "any" };
const SWITCH = [["any", "Any"], ["yes", "On Switch"], ["no", "Not on Switch"]];
const fmt = (n) => n.toLocaleString("en-US");

function loadDials() {
	try {
		const v = JSON.parse(localStorage.getItem(STORE) || "null");
		if (!v || typeof v !== "object") return { ...DEFAULTS };
		const out = { ...DEFAULTS };
		for (const k of ["rev", "yfrom", "yto"]) {
			if (typeof v[k] === "number" && isFinite(v[k])) out[k] = v[k];
		}
		if (Array.isArray(v.cats)) out.cats = v.cats.filter((c) => typeof c === "string");
		if (SWITCH.some(([k]) => k === v.sw)) out.sw = v.sw;
		out.rev = Math.min(REVIEWS.length - 1, Math.max(0, out.rev));
		out.yfrom = Math.min(YMAX, Math.max(YMIN, out.yfrom));
		out.yto = Math.min(YMAX, Math.max(out.yfrom, out.yto));
		return out;
	} catch { return { ...DEFAULTS }; }
}

// The three ratings, derived once per dataset so sorting stays a plain lookup.
//   a — Positive: the raw share of English reviews that recommend the game.
//   r — Rating: that share pulled towards 50% by an amount that shrinks with the review
//       count (SteamDB's formula: a − (a − ½)·2^−log10(n+1)). 100% off 50 reviews lands
//       near 85%; 97% off 100,000 barely moves. The Steam analogue of BGG's Geek rating.
//   f — F score: the midpoint of the two, exactly as BGG Filter's F average is — the
//       Rating punishes a well-liked small game, the raw share lets fifty fans crown one.
export function derive(games) {
	for (const g of games) {
		const a = g.t ? g.p / g.t : 0;
		const r = a - (a - 0.5) * Math.pow(2, -Math.log10(g.t + 1));
		g.c = g.c || [];
		g.a = a * 100;
		g.r = r * 100;
		g.f = (g.a + g.r) / 2;
	}
	return games;
}

function Dial({ id, label, value, min, max, step, onChange, display }) {
	return (
		<div className="stf-knob">
			<label htmlFor={id}>{label} <span className="stf-v stf-num">{display}</span></label>
			<input id={id} type="range" min={min} max={max} step={step} value={value}
				onChange={(e) => onChange(Number(e.target.value))} {...rangePointer(onChange)} />
		</div>
	);
}

// Props: { onExit }.
export default function SteamFilter({ onExit }) {
	const [games, setGames] = useState(null);
	const [err, setErr] = useState("");
	const [meta, setMeta] = useState(null);
	const [d, setD] = useState(loadDials);
	const [q, setQ] = useState("");
	const [sortKey, setSortKey] = useState("f");
	const [dir, setDir] = useState(-1);
	const [limit, setLimit] = useState(PAGE);

	useEffect(() => {
		let live = true;
		fetch(DATA_URL)
			.then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.then((j) => { if (live) { setMeta(j); setGames(derive(j.games || [])); } })
			.catch((e) => { if (live) setErr(String(e.message || e)); });
		return () => { live = false; };
	}, []);

	useEffect(() => { try { localStorage.setItem(STORE, JSON.stringify(d)); } catch { /* private mode */ } }, [d]);

	// Dragging one year end past the other pushes it along, so the range can never invert.
	const setDial = useCallback((k, v) => {
		setD((prev) => {
			const next = { ...prev, [k]: v };
			if (k === "yfrom" && next.yfrom > next.yto) next.yto = next.yfrom;
			if (k === "yto" && next.yto < next.yfrom) next.yfrom = next.yto;
			return next;
		});
		setLimit(PAGE);
	}, []);

	// The categories this payload knows. A saved pick the payload no longer has is
	// dropped rather than filtering everything out.
	const cats = useMemo(() => meta?.categories || [], [meta]);
	const catLabel = useMemo(() => Object.fromEntries(cats.map((c) => [c.id, c.label])), [cats]);
	const picked = useMemo(() => d.cats.filter((c) => catLabel[c]), [d.cats, catLabel]);
	const toggleCat = (id) => {
		setD((prev) => ({ ...prev, cats: prev.cats.includes(id)
			? prev.cats.filter((c) => c !== id) : [...prev.cats, id] }));
		setLimit(PAGE);
	};

	// Everything but the categories, so each chip can say how many it would leave.
	const passBase = useCallback((g) => {
		if (g.t < REVIEWS[d.rev]) return false;
		// Either year end off its stop is a real bound, and a game with no date fails it.
		if (d.yfrom > YMIN && (!g.y || g.y < d.yfrom)) return false;
		if (d.yto < YMAX && (!g.y || g.y > d.yto)) return false;
		if (d.sw === "yes" && !g.sw) return false;
		if (d.sw === "no" && g.sw) return false;
		return true;
	}, [d]);

	const base = useMemo(() => (games || []).filter(passBase), [games, passBase]);
	const pool = useMemo(() => base.filter((g) => picked.every((c) => g.c.includes(c))), [base, picked]);
	// A chip's count is what the list would hold with that chip on as well.
	const catCount = useMemo(() => {
		const n = {};
		for (const c of cats) n[c.id] = 0;
		for (const g of pool) for (const c of g.c) if (c in n) n[c]++;
		return n;
	}, [pool, cats]);
	const view = useMemo(() => {
		const needle = q.trim().toLowerCase();
		const rows = needle ? pool.filter((g) => g.n.toLowerCase().includes(needle)) : pool.slice();
		rows.sort((a, b) => {
			const x = a[sortKey] ?? -1, y = b[sortKey] ?? -1;
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
		<th className="stf-s" tabIndex={0} role="button"
			aria-sort={sortKey === k ? (dir === -1 ? "descending" : "ascending") : undefined}
			onClick={() => sortBy(k)}
			onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); sortBy(k); } }}>
			{label}<span className="stf-arw">{dir === -1 ? "▼" : "▲"}</span>
		</th>
	);

	const floor = meta?.min_reviews ?? REVIEWS[0];
	const minPct = Math.round((meta?.min_positive ?? 0.9) * 100);

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="stf">
				<header className="stf-header">
					<button className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
					<div className="stf-headtitle">Steam Filter</div>
					<div className="stf-headright">{meta?.collected ? `collected ${meta.collected}` : ""}</div>
				</header>

				<div className="stf-hero">
					<div className="stf-logo">Steam Filter</div>
					<p className="stf-tagline">
						Every game on Steam whose English reviews are {minPct}% or more positive, from {fmt(floor)}{" "}
						reviews up. Dial in how many reviews and which years, and rank by a score that weighs
						the share against how many people wrote one.
					</p>
				</div>

				<div className="stf-wrap">
					{err && <div className="stf-loading">Couldn’t load the game data ({err}).</div>}
					{!err && !games && <div className="stf-loading">Loading the list…</div>}
					{games && (
						<>
							<section className="stf-panel">
								<div className="stf-phead">
									<h2>Dials</h2>
									<button type="button" className="btn btn-ghost btn-sm"
										onClick={() => { setD({ ...DEFAULTS }); setLimit(PAGE); }}>Reset all dials</button>
								</div>
								<div className="stf-knobs">
									<Dial id="stf-rev" label="Minimum English reviews" min={0} max={REVIEWS.length - 1} step={1}
										value={d.rev} display={`${fmt(REVIEWS[d.rev])}+`} onChange={(v) => setDial("rev", v)} />
									<Dial id="stf-yfrom" label="Released from" min={YMIN} max={YMAX} step={1}
										value={d.yfrom} display={d.yfrom > YMIN ? `${d.yfrom}` : "any year"}
										onChange={(v) => setDial("yfrom", v)} />
									<Dial id="stf-yto" label="Released to" min={YMIN} max={YMAX} step={1}
										value={d.yto} display={d.yto < YMAX ? `${d.yto}` : "now"}
										onChange={(v) => setDial("yto", v)} />
								</div>
								{cats.length > 0 && (
									<>
										<p className="stf-mhead">Categories — <em>a game must carry every one you pick</em></p>
										<div className="stf-chips">
											{cats.map((c) => {
												const on = picked.includes(c.id);
												return (
													<button type="button" key={c.id} className="stf-chip" aria-pressed={on}
														onClick={() => toggleCat(c.id)}>
														{c.label}<span className="stf-num">{fmt(catCount[c.id])}</span>
													</button>
												);
											})}
										</div>
										<p className="stf-mhead">Nintendo Switch</p>
										<div className="stf-seg" role="group" aria-label="Nintendo Switch">
											{SWITCH.map(([k, label]) => (
												<button type="button" key={k} aria-pressed={d.sw === k}
													onClick={() => { setD((prev) => ({ ...prev, sw: k })); setLimit(PAGE); }}>
													{label}
												</button>
											))}
										</div>
									</>
								)}
								<p className="stf-effect">
									{!games.length
										? <>The Steam list hasn’t been harvested yet.</>
										: pool.length
											? <><b>{fmt(pool.length)}</b> of {fmt(games.length)} games clear these dials.</>
											: <>No game clears every dial. Loosen one.</>}
								</p>
							</section>

							<div className="stf-controls">
								<label className="stf-search">
									<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
										strokeWidth="2.2" aria-hidden="true">
										<circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" />
									</svg>
									<input type="search" placeholder="Filter by title…" aria-label="Filter by title"
										value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
								</label>
								<p className="stf-count"><b>{fmt(view.length)}</b> of {fmt(pool.length)} shown</p>
							</div>

							<div className="stf-tablewrap">
								<table>
									<thead>
										<tr>
											<th className="stf-pos">#</th>
											{th("n", "Game")}
											{th("r", "Rating")}
											{th("f", "F score")}
											{th("a", "Positive")}
											{th("t", "Reviews")}
											{th("y", "Released")}
										</tr>
									</thead>
									<tbody>
										{!view.length && (
											<tr><td className="stf-empty" colSpan={7}>
												{games.length
													? <><b>Nothing clears every dial.</b>Drop a category, loosen the review minimum or widen the years.</>
													: <><b>No data yet.</b>The Steam list hasn’t been harvested.</>}
											</td></tr>
										)}
										{view.slice(0, limit).map((g, i) => (
											<tr key={g.id}>
												<td className="stf-pos stf-num">{i + 1}</td>
												<td className="stf-game">
													<a href={`https://store.steampowered.com/app/${g.id}/`}
														target="_blank" rel="noopener noreferrer">{g.n}</a>
													{(g.sw || g.c.length > 0) && (
														<span className="stf-tags">
															{g.sw ? <i className="stf-switch">Switch</i> : null}
															{g.c.map((c) => catLabel[c]).filter(Boolean).join(" · ")}
														</span>
													)}
												</td>
												<td className="stf-rating stf-num"><b>{g.r.toFixed(1)}</b></td>
												<td className="stf-f stf-num">{g.f.toFixed(1)}</td>
												<td className="stf-a stf-num" title={`${fmt(g.p)} of ${fmt(g.t)} English reviews positive`}>
													{g.a.toFixed(1)}%
												</td>
												<td className="stf-t stf-num">{fmt(g.t)}</td>
												<td className="stf-y stf-num">{g.y || "—"}</td>
											</tr>
										))}
									</tbody>
								</table>
								{view.length > limit && (
									<button className="stf-more" onClick={() => setLimit((v) => v + PAGE)}>
										Show {Math.min(view.length - limit, PAGE)} more · {fmt(view.length - limit)} remaining
									</button>
								)}
							</div>

							<section className="stf-notes">
								<div>
									<h3>The three numbers</h3>
									<p><b>Positive</b> is the raw share of English reviews that recommend the game.
										<b> Rating</b> pulls that share towards 50% by an amount that shrinks as reviews
										pile up — SteamDB’s formula — so 100% off 60 reviews rates about 85, while 97%
										off 100,000 still rates above 95.</p>
									<p><b>F score</b> is the midpoint of the two, the same blend as BGG Filter’s F
										average: the Rating is harsh on a well-loved small game, the raw share lets a few
										dozen fans crown one.</p>
								</div>
								<div>
									<h3>Only English reviews</h3>
									<p>Every count here is English reviews alone — the store’s own score can blend
										languages, so a game’s Steam page may show a different share. Reviews from key
										activations count too; Steam’s off-topic review-bomb filter stays on.</p>
								</div>
								{cats.length > 0 && (
									<div>
										<h3>Categories and Switch</h3>
										<p>Categories group Steam’s player-applied tags — <b>Roguelike / Roguelite</b>{" "}
											covers Roguelike, Roguelite, Action Roguelike and Roguelike Deckbuilder, for
											instance — read from SteamSpy’s tag lists. Picking two finds games that are
											both.</p>
										<p><b>Switch</b> means a game of the same title is in Nintendo’s European eShop.
											It is matched by name, so a port sold under a different title can be missed.</p>
									</div>
								)}
								<div>
									<h3>Scope</h3>
									<p><b>{fmt(games.length)}</b> games, each {minPct}%+ positive across{" "}
										{fmt(floor)}+ English reviews. Games under that line were never collected,
										so the review dial can only tighten it.</p>
									<p>The year dials stop at {YMIN}, where they mean <em>any year</em>, and at{" "}
										{YMAX}, where they mean <em>up to now</em>. Your dial settings are remembered in
										this browser.</p>
								</div>
							</section>
						</>
					)}
				</div>
			</div>
		</>
	);
}
