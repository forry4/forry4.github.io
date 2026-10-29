import { useState, useEffect, useMemo, useCallback, useRef } from "react";
import { baseCss } from "../shared/theme.js";
import { rangePointer } from "../shared/rangePointer.js";
import { attachPrices, startedWithin, money, day, span } from "./prices.js";
import { readSaved, writeSaved, clearSaved, setMark, markOf, adopt, settle, batch } from "./saved.js";

// CSS lives in the sibling .css file, imported with `?inline` so it is still a string
// injected by this component's own <style> while mounted. Never move it back into a JS
// template literal — one stray backtick there blanked the whole site twice.
import _cssText from "./SteamFilter.css?inline";
const css = _cssText;

// The dataset is a build artifact, fetched rather than bundled (see BggFilter.jsx).
// Regenerate with steamfilter/tools/scan_steam.py + make_data.py.
const DATA_URL = `${import.meta.env.BASE_URL || "/"}data/steam-filter.json`;
// Prices move daily, so they ship in their own file (steamfilter/tools/prices.py, run by
// the steam-prices workflow). The page works without it: every price reads "—".
const PRICES_URL = `${import.meta.env.BASE_URL || "/"}data/steam-prices.json`;
// Saved games are the page's one piece of server state (steamfilter/api.py).
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

const REVIEWS = [50, 100, 250, 500, 1000, 2500, 5000, 10000, 25000, 50000, 100000];
const PAGE = 50;
const STORE = "steam_filter_dials_v1";

// Steam opened its store to other publishers in 2005; the few older dates are
// re-releases. The floor position means "any year", the ceiling "up to now".
const YMIN = 2005;
const YMAX = new Date().getFullYear();

// `cats`: category ids a game must ALL carry (AND, so Roguelike + Card game finds the
// roguelike deckbuilders). `sw`: "any", "yes" (on Nintendo Switch) or "no". `sale`: a
// sale running today on either store, on Steam, or on the eShop. `started`: only sales
// that began within that many days (on the store `sale` names, either if it names none).
const DEFAULTS = { rev: REVIEWS.indexOf(500), yfrom: YMIN, yto: YMAX, cats: [], sw: "any", sale: "any",
	started: "any" };
const SWITCH = [["any", "Any"], ["yes", "On Switch"], ["no", "Not on Switch"]];
const SALE = [["any", "Any"], ["either", "On sale"], ["steam", "Steam sale"], ["switch", "Switch sale"]];
const STARTED = [["any", "Any time"], ["1", "Past day"], ["3", "Past 3 days"], ["7", "Past week"], ["14", "Past 2 weeks"]];
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
		if (SALE.some(([k]) => k === v.sale)) out.sale = v.sale;
		if (STARTED.some(([k]) => k === v.started)) out.started = v.started;
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

// One store's price cell: today's price, and for a sale the regular price, the discount
// and the day it ends. `none` is what a game with no price there shows.
function Price({ p, store, none = "—" }) {
	if (!p) return <td className="stf-price stf-num stf-none">{none}</td>;
	if (!p.off) return <td className="stf-price stf-num">{money(p.cur)}</td>;
	// Steam publishes no start: its start is when the daily price check first saw the sale.
	const seen = store === "Steam" ? "First seen on sale" : "Started";
	const began = p.start ? `${seen} ${day(p.start)}` : p.before ? `${seen} on or before ${day(p.before)}` : "";
	const ends = p.end ? `ends ${day(p.end)}` : "no end date given";
	const tip = began ? `${began}; ${ends}.` : `${ends[0].toUpperCase()}${ends.slice(1)}.`;
	return (
		<td className="stf-price stf-num"
			title={`${store} sale: ${money(p.cur)}, regularly ${money(p.reg)}. ${tip}`}>
			<b className="stf-sale">{money(p.cur)}</b><span className="stf-off">−{p.off}%</span>
			<span className="stf-was"><s>{money(p.reg)}</s>
				{p.start && p.end ? ` · ${span(p.start, p.end)}` : p.end ? ` · to ${day(p.end)}` : ""}</span>
		</td>
	);
}

async function api(path, token, body) {
	const headers = { Authorization: `Bearer ${token}` };
	if (body) headers["Content-Type"] = "application/json";
	const res = await fetch(HTTP_BASE + path, { method: body ? "POST" : "GET", headers,
		body: body ? JSON.stringify(body) : undefined });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

// The saved and not-interested lists: this device's copy, and for a signed-in reader
// the account's, synced. A tap shows at once; the request follows, one at a time, and
// whatever was pressed while one was out goes in the next. Offline (or signed out by
// the server) the device copy stands and the queue waits for the next visit.
function useSaved(authUser) {
	const token = authUser && !authUser.guest && authUser.session_token ? authUser.session_token : null;
	const who = token ? authUser.id : "guest";
	const [store, setStore] = useState(() => readSaved(who));
	const ref = useRef(store);
	const busy = useRef(false);

	const update = useCallback((next) => {
		ref.current = next;
		setStore(next);
		writeSaved(who, next);
	}, [who]);

	const sync = useCallback(async () => {
		if (!token || busy.current) return;
		busy.current = true;
		try {
			for (let round = 0; round < 5; round++) {
				const sent = { ...ref.current.pending };
				const r = Object.keys(sent).length
					? await api("/steamfilter/saved", token, batch(sent))
					: await api("/steamfilter/saved", token);
				const before = Object.keys(ref.current.pending).length;
				const next = settle(ref.current, sent, r);
				update(next);
				// Done, or nothing landed (a server from before "not interested" keeps a
				// hide queued): either way, stop until the next tap or visit.
				const left = Object.keys(next.pending).length;
				if (!left || left >= before) break;
			}
		} catch { /* offline or signed out: the device copy stands, the queue waits */ }
		finally { busy.current = false; }
	}, [token, update]);

	useEffect(() => {
		let s = readSaved(who);
		// Lists made as a guest on this device join the account the first time.
		if (token) {
			const guest = readSaved("guest");
			if (Object.keys(guest.saved).length || Object.keys(guest.hidden).length) {
				s = adopt(s, guest, Date.now() / 1000);
				clearSaved("guest");
			}
		}
		update(s);
		sync();
	}, [who, token, update, sync]);

	// Give a game `mark` ("saved" / "hidden"), or take it off if it already has it.
	const mark = useCallback((id, m) => {
		const next = markOf(ref.current, id) === m ? "none" : m;
		update(setMark(ref.current, id, next, Date.now() / 1000, !!token));
		sync();
	}, [token, update, sync]);

	return { saved: store.saved, hidden: store.hidden, mark, member: !!token };
}

// "Not interested": an eye struck through — the game leaves the list.
const EyeOff = () => (
	<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
		strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
		<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12z" /><circle cx="12" cy="12" r="3" />
		<path d="M3 3l18 18" />
	</svg>
);

// Props: { authUser, onExit }.
export default function SteamFilter({ authUser, onExit }) {
	const [games, setGames] = useState(null);
	const [err, setErr] = useState("");
	const [meta, setMeta] = useState(null);
	const [prices, setPrices] = useState(null);
	const [d, setD] = useState(loadDials);
	const [q, setQ] = useState("");
	const [sortKey, setSortKey] = useState("f");
	const [dir, setDir] = useState(-1);
	const [limit, setLimit] = useState(PAGE);
	const { saved, hidden, mark, member } = useSaved(authUser);
	// "all": the dials' list, less the games marked not interested. "saved" / "hidden":
	// every game with that mark, dials or not — a game kept for later should not vanish
	// because a dial moved since, and a hidden one has to be findable to bring it back.
	const [show, setShow] = useState("all");
	// The last game hidden from the list, for a moment, so a mis-tap can be taken back.
	const [undo, setUndo] = useState(null);
	useEffect(() => {
		if (!undo) return undefined;
		const t = setTimeout(() => setUndo(null), 8000);
		return () => clearTimeout(t);
	}, [undo]);

	useEffect(() => {
		let live = true;
		fetch(DATA_URL)
			.then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.then((j) => { if (live) { setMeta(j); setGames(derive(j.games || [])); } })
			.catch((e) => { if (live) setErr(String(e.message || e)); });
		fetch(PRICES_URL)
			.then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.then((j) => { if (live) setPrices(j); })
			.catch(() => { /* no prices: the columns read "—" */ });
		return () => { live = false; };
	}, []);

	// A new array when prices land, so everything downstream re-sorts and re-filters.
	const priced = useMemo(() => (games ? attachPrices(games, prices?.games, Date.now() / 1000, prices?.tracked_since || 0).slice() : null),
		[games, prices]);
	const nSaved = useMemo(() => (priced || []).filter((g) => g.id in saved).length, [priced, saved]);
	const nHidden = useMemo(() => (priced || []).filter((g) => g.id in hidden).length, [priced, hidden]);
	const hide = (g) => {
		const wasHidden = g.id in hidden;
		mark(g.id, "hidden");
		setUndo(wasHidden ? null : { id: g.id, n: g.n, was: g.id in saved ? "saved" : null });
	};

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
		if (g.id in hidden) return false;
		if (g.t < REVIEWS[d.rev]) return false;
		// Either year end off its stop is a real bound, and a game with no date fails it.
		if (d.yfrom > YMIN && (!g.y || g.y < d.yfrom)) return false;
		if (d.yto < YMAX && (!g.y || g.y > d.yto)) return false;
		if (d.sw === "yes" && !g.sw) return false;
		if (d.sw === "no" && g.sw) return false;
		if (d.sale === "either" && !g.ps?.off && !g.pw?.off) return false;
		if (d.sale === "steam" && !g.ps?.off) return false;
		if (d.sale === "switch" && !g.pw?.off) return false;
		if (d.started !== "any"
			&& !startedWithin(g, d.sale === "any" ? "either" : d.sale, Date.now() / 1000, Number(d.started))) return false;
		return true;
	}, [d, hidden]);

	const base = useMemo(() => (priced || []).filter(passBase), [priced, passBase]);
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
		const marked = show === "saved" ? saved : show === "hidden" ? hidden : null;
		const from = marked ? (priced || []).filter((g) => g.id in marked) : pool;
		const rows = needle ? from.filter((g) => g.n.toLowerCase().includes(needle)) : from.slice();
		// A missing value (no year, no price in that store) sorts last in either direction.
		rows.sort((a, b) => {
			const x = a[sortKey], y = b[sortKey];
			if ((x == null) !== (y == null)) return x == null ? 1 : -1;
			const c = x == null ? 0 : typeof x === "string" ? x.localeCompare(y) : x - y;
			return c * dir || a.n.localeCompare(b.n);
		});
		return rows;
	}, [pool, priced, saved, hidden, show, q, sortKey, dir]);

	const sortBy = (k) => {
		if (k === sortKey) setDir((v) => -v);
		else { setSortKey(k); setDir(k === "n" || k === "sp" || k === "wp" ? 1 : -1); }
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
								{prices && (
									<>
										<p className="stf-mhead">Sales — <em>running today, US stores</em></p>
										<div className="stf-seg" role="group" aria-label="Sales">
											{SALE.map(([k, label]) => (
												<button type="button" key={k} aria-pressed={d.sale === k}
													onClick={() => { setD((prev) => ({ ...prev, sale: k })); setLimit(PAGE); }}>
													{label}
												</button>
											))}
										</div>
										<p className="stf-mhead">Sale started — <em>to see what just went on sale</em></p>
										<div className="stf-seg" role="group" aria-label="Sale started">
											{STARTED.map(([k, label]) => (
												<button type="button" key={k} aria-pressed={d.started === k}
													onClick={() => { setD((prev) => ({ ...prev, started: k })); setLimit(PAGE); }}>
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
									{games.length > 0 && nHidden > 0 && (
										<> {fmt(nHidden)} you’re not interested in {nHidden === 1 ? "is" : "are"} left out.</>
									)}
								</p>
							</section>

							<div className="stf-controls">
								<div className="stf-seg" role="group" aria-label="Show">
									<button type="button" aria-pressed={show === "all"}
										onClick={() => { setShow("all"); setLimit(PAGE); }}>All games</button>
									<button type="button" aria-pressed={show === "saved"}
										onClick={() => { setShow("saved"); setLimit(PAGE); }}>
										Saved<span className="stf-num">{fmt(nSaved)}</span>
									</button>
									<button type="button" aria-pressed={show === "hidden"}
										onClick={() => { setShow("hidden"); setLimit(PAGE); }}>
										Not interested<span className="stf-num">{fmt(nHidden)}</span>
									</button>
								</div>
								<label className="stf-search">
									<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor"
										strokeWidth="2.2" aria-hidden="true">
										<circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" />
									</svg>
									<input type="search" placeholder="Filter by title…" aria-label="Filter by title"
										value={q} onChange={(e) => { setQ(e.target.value); setLimit(PAGE); }} />
								</label>
								<p className="stf-count">
									{show === "saved"
										? <><b>{fmt(view.length)}</b> of {fmt(nSaved)} saved shown</>
										: show === "hidden"
											? <><b>{fmt(view.length)}</b> of {fmt(nHidden)} not interested shown</>
											: <><b>{fmt(view.length)}</b> of {fmt(pool.length)} shown</>}
								</p>
							</div>
							{undo && (
								<div className="stf-undo" role="status">
									<span><b>{undo.n}</b> is hidden — find it under Not interested.</span>
									<button type="button" className="btn btn-ghost btn-sm" onClick={() => {
										mark(undo.id, undo.was || "hidden");   // back to saved, or off "hidden"
										setUndo(null);
									}}>Undo</button>
								</div>
							)}

							<div className="stf-tablewrap">
								<table>
									<thead>
										<tr>
											<th className="stf-pos">#</th>
											<th className="stf-marks" aria-label="Saved or not interested" />
											{th("n", "Game")}
											{th("r", "Rating")}
											{th("f", "F score")}
											{th("a", "Positive")}
											{th("t", "Reviews")}
											{th("y", "Released")}
											{th("sp", "Steam")}
											{th("wp", "Switch")}
										</tr>
									</thead>
									<tbody>
										{!view.length && (
											<tr><td className="stf-empty" colSpan={10}>
												{show === "saved"
													? (nSaved
														? <><b>No saved game matches that title.</b>Clear the title filter to see them all.</>
														: <><b>No saved games yet.</b>Tap the ☆ beside a game to keep it here for later.</>)
													: show === "hidden"
													? (nHidden
														? <><b>No hidden game matches that title.</b>Clear the title filter to see them all.</>
														: <><b>Nothing hidden.</b>Tap the crossed-out eye beside a game you know you won’t like, and it leaves the list.</>)
													: games.length
													? <><b>Nothing clears every dial.</b>Drop a category, loosen the review minimum or widen the years.</>
													: <><b>No data yet.</b>The Steam list hasn’t been harvested.</>}
											</td></tr>
										)}
										{view.slice(0, limit).map((g, i) => (
											<tr key={g.id}>
												<td className="stf-pos stf-num">{i + 1}</td>
												<td className="stf-marks">
													<button type="button" className="stf-save" aria-pressed={g.id in saved}
														aria-label={g.id in saved ? `Remove ${g.n} from saved` : `Save ${g.n} for later`}
														title={g.id in saved ? "Saved — tap to remove" : "Save for later"}
														onClick={() => mark(g.id, "saved")}>{g.id in saved ? "★" : "☆"}</button>
													<button type="button" className="stf-hide" aria-pressed={g.id in hidden}
														aria-label={g.id in hidden ? `Show ${g.n} again` : `Not interested in ${g.n}`}
														title={g.id in hidden ? "Not interested — tap to show it again" : "Not interested — hide it"}
														onClick={() => hide(g)}><EyeOff /></button>
												</td>
												<td className="stf-game">
													<a href={`https://store.steampowered.com/app/${g.id}/`}
														target="_blank" rel="noopener noreferrer">{g.n}</a>
													{(g.sw || g.c.length > 0) && (
														<span className="stf-tags">
															{g.sw ? <i className="stf-switch">{g.w2 ? "Switch 2" : "Switch"}</i> : null}
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
												<Price p={g.ps} store="Steam" />
												<Price p={g.pw} store="eShop" none={g.sw ? "—" : ""} />
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
											instance — read from each game’s Steam store tags. Picking two finds games that are
											both.</p>
										<p><b>Switch</b> means a game of the same title is in Nintendo’s European eShop.
											It is matched by name, so a port sold under a different title can be missed.</p>
									</div>
								)}
								{prices && (
									<div>
										<h3>Prices and sales</h3>
										<p>US prices, read {prices.priced ? prices.priced.slice(0, 10) : "recently"} and
											refreshed daily. <b>Steam</b> is the game’s own store listing; <b>Switch</b> is
											the cheapest eShop listing of the same title today — a Switch 2 version or
											Nintendo Switch 2 Edition counts, and the badge reads <b>Switch 2</b> when one
											is sold.</p>
										<p>A sale shows its discount and its dates, in your time zone, and drops back
											to the regular price once it ends. Sort a store’s column for the cheapest
											first.</p>
										<p><b>Sale started</b> keeps the sales that began in that window. The eShop
											publishes when a sale starts; Steam doesn’t, so a Steam sale’s start is the
											day the twice-daily price check first saw it — right to within a day.
											{prices.tracked_since
												? ` Steam sales already running on ${day(prices.tracked_since)}, when the check started recording, count as older than every window.`
												: ""}</p>
									</div>
								)}
								<div>
									<h3>Saved and not interested</h3>
									<p>Tap <b>☆</b> beside a game to keep it, and <b>Saved</b> above the list to see
										them all — the dials don’t hide a saved game. Tap the <b>crossed-out eye</b> on a
										game you know you won’t like and it leaves the list for good; <b>Not
										interested</b> lists those, to bring one back.</p>
									<p>{member
										? "Both lists are kept with your account, so they follow you to any device you sign in on."
										: "As a guest they stay in this browser; sign in and they move to your account."}</p>
								</div>
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
