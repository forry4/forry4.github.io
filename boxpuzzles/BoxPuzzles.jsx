// Box Puzzles — 71 boxes of coloured tiles, each opened by turning its four corner
// tiles to the colours on its four corner buttons and then pressing those buttons.
//
// The boxes play entirely in the browser (engine.js); the server only keeps the
// leaderboard, and replays every posted solve through its own engine before it
// counts (boxpuzzles/api.py). Nothing here explains what a colour does — finding
// that out is the puzzle.
//
// A SCORE IS THE TILE PRESSES SINCE THE BOX WAS LAST RESET, and the only reset is a
// corner button pressed while its corner does not match. Corner presses are free.
//
// THE PAGE CARRIES NO PROSE (owner's call): no instructions, no empty states, no
// explanations of the blue. The board, the count and the leaderboard say it.
//
// THE DAILY BOX (/boxpuzzles/daily) is the exception to all three: one new box a day
// (midnight US Pacific), made and kept by the server (boxpuzzles/daily.py), ONE attempt,
// saved as it is played, and a reset does NOT clear its count. The attempt is a list
// of segments — the presses between resets — because the server replays each one from
// the first board. Once it is open, Play again starts RETRIES under the numbered boxes'
// rules, for a second board: One Shot is the race, Best Shot the fewest presses.
// Yesterday's box can be looked at (view only), with its minimum and a shortest line
// played back on the board.
//
// Routes: /boxpuzzles (the picker), /boxpuzzles/<n> (box n, numbered easiest first) and
// /boxpuzzles/daily. This screen owns its segment 2, like Notes.
import { useState, useEffect, useCallback, useRef } from "react";
import { baseCss } from "../shared/theme.js";
import { buildPath, parsePath, pushPath, subscribe } from "../shared/router.js";
import _cssText from "./BoxPuzzles.css?inline";
import BANK from "./puzzles.json";
import { CORNERS, press, newBox, pressTileInBox, pressButtonInBox } from "./engine.js";
import { isMuted, setMuted, tileSound, litSound, resetSound, openSound } from "./sound.js";

const css = _cssText;
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

const COLOR_NAME = { GY: "gray", WH: "white", PU: "violet", YE: "yellow", GN: "green",
	PI: "pink", BK: "black", RD: "red", OR: "orange", BU: "blue" };
const CORNER_NAME = ["top-left", "top-right", "bottom-right", "bottom-left"];
const swatch = (c) => ({ "--t": `var(--bx-${c})` });

// ── storage (every access guarded: private windows and blocked storage throw) ──
const resultsKey = (who) => `boxpuzzles.results.v1.${who}`;   // { id: { moves, optimal? } }
function readJson(key, fallback) {
	try { const v = JSON.parse(localStorage.getItem(key)); return v && typeof v === "object" ? v : fallback; }
	catch { return fallback; }
}
function writeJson(key, value) {
	try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
// A BOX IS NEVER SAVED MID-SOLVE (owner's call): reloading the page or leaving the box
// starts it again from its first board. Only finished results are kept. The progress
// key an earlier build wrote is cleared once, so no stale line lingers in storage.
try { localStorage.removeItem("boxpuzzles.progress.v1"); } catch { /* storage unavailable */ }

// The open view: a box number, "daily", or null for the picker.
const routeView = () => {
	const room = parsePath().room || "";
	if (room === "DAILY") return "daily";
	const n = parseInt(room, 10);
	return n >= 1 && n <= BANK.length ? n : null;
};

// The daily attempt this device knows of: { day, segments, moves, solved, optimal? }.
// Guests have only this copy; a signed-in player's is a cache of the server's.
const dailyKey = (who) => `boxpuzzles.daily.v1.${who}`;
// Today in US Pacific, for the picker's tile only — the server decides the real day.
const pacificToday = () => {
	try { return new Intl.DateTimeFormat("en-CA", { timeZone: "America/Los_Angeles" }).format(new Date()); }
	catch { return ""; }
};
const shortDate = (day) => {
	try { return new Date(`${day}T12:00:00Z`).toLocaleDateString(undefined, { month: "short", day: "numeric", timeZone: "UTC" }); }
	catch { return day; }
};
const totalMoves = (segs) => segs.reduce((n, s) => n + s.length, 0);
const boardAfter = (tiles, moves) => moves.reduce((t, i) => press(t, i), tiles.slice());
// True if `next` is `prev` played on (the server's rule: an attempt only grows).
const extendsAttempt = (prev, next) => {
	if (next.length < prev.length) return false;
	const k = prev.length - 1;
	for (let i = 0; i < k; i++) if (prev[i].join() !== next[i].join()) return false;
	return prev[k].every((m, j) => next[k][j] === m);
};

// `keepalive` lets a save finish after the page is hidden or closed.
async function api(path, token, body, keepalive = false) {
	const headers = token ? { Authorization: `Bearer ${token}` } : {};
	if (body) headers["Content-Type"] = "application/json";
	const res = await fetch(HTTP_BASE + path, { method: body ? "POST" : "GET", headers, keepalive,
		body: body ? JSON.stringify(body) : undefined });
	let data = null;
	try { data = await res.json(); } catch { /* not JSON */ }
	if (!res.ok) { const e = new Error(data?.detail || `HTTP ${res.status}`); e.status = res.status; throw e; }
	return data;
}

// ── pieces ───────────────────────────────────────────────────────────────────
function MiniBoard({ tiles }) {
	return (
		<span className="bx-mini" aria-hidden="true">
			{tiles.map((c, i) => <span key={i} style={swatch(c)} />)}
		</span>
	);
}

const CALENDAR = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
		<rect x="4" y="5.5" width="16" height="14.5" rx="2" /><path d="M4 10h16M8.5 3.5v4M15.5 3.5v4" />
	</svg>
);

function Picker({ results, daily, onPick }) {
	const today = pacificToday();
	const done = daily && daily.day === today && daily.solved ? daily : null;
	return (
		<div className="bx-wrap">
			<button type="button" className={`bx-daily-tile${done ? " solved" : ""}${done?.optimal ? " optimal" : ""}`}
				onClick={() => onPick("daily")} aria-label={`Daily box${done ? `, solved in ${done.moves}` : ""}`}>
				{CALENDAR}
				<span className="bx-daily-name">Daily</span>
				<span className="bx-daily-date">{today ? shortDate(today) : ""}</span>
				<span className="bx-pick-state">{done ? `✓ ${done.moves}` : ""}</span>
			</button>
			<ol className="bx-picker" aria-label="Boxes">
				{BANK.map((p, idx) => {
					const r = results[p.id];
					const cls = r ? (r.optimal ? "solved optimal" : "solved") : "";
					return (
						<li key={p.id}>
							<button type="button" className={`bx-pick ${cls}`} data-box={idx + 1} onClick={() => onPick(idx + 1)}
								aria-label={`Box ${idx + 1}${r ? `, solved in ${r.moves}` : ""}`}>
								<span className="bx-pick-num">{idx + 1}</span>
								<MiniBoard tiles={p.tiles} />
								<span className="bx-pick-state">{r ? `✓ ${r.moves}` : ""}</span>
							</button>
						</li>
					);
				})}
			</ol>
		</div>
	);
}

// The box itself: the case, its four corner buttons and the nine tiles. `hint` rings
// one tile (yesterday's replay shows each press before it lands).
function BoxFace({ id, target, box, shake = 0, opened, disabled, hint = -1, onTile, onButton }) {
	const off = !!(opened || disabled);
	return (
		<div key={shake} className={`bx-box${shake ? " bx-shake" : ""}${opened ? " open" : ""}`} data-box={id}>
			{CORNERS.map((c, k) => (
				<button key={k} type="button" className={`bx-cbtn bx-c${k}${box.lit[k] ? " lit" : ""}`}
					style={swatch(target[k])} disabled={off} data-button={k}
					aria-label={`${CORNER_NAME[k]} button, ${COLOR_NAME[target[k]]}${box.lit[k] ? ", lit" : ""}`}
					aria-pressed={box.lit[k]} onClick={() => onButton?.(k)} />
			))}
			<div className="bx-grid">
				{box.tiles.map((c, i) => (
					<button key={i} type="button" className={`bx-tile${i === hint ? " hint" : ""}`} style={swatch(c)}
						data-tile={i} data-color={c} disabled={off} aria-label={`Tile ${i + 1}, ${COLOR_NAME[c]}`}
						onClick={() => onTile?.(i)} />
				))}
			</div>
		</div>
	);
}

// ALWAYS THERE, AND CLOSED UNTIL ASKED: the scores are a spoiler (a low best says
// how short the line is), so a box starts with the leaderboard folded to its title
// and opens it for you once you have opened the box. No loading line, no empty-state
// sentence: an open board with nobody on it shows a dash.
const CHEVRON = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
		<path d="M8 10l4 4 4-4" />
	</svg>
);

// THE DAILY'S TWO BOARDS: the one attempt, and the best of the retries after it (the
// attempt counts there too). The server sends One Shot at the top level and Best Shot
// under `best`.
const DAILY_BOARDS = [["first", "One Shot"], ["best", "Best Shot"]];

// `locked`: today's daily board cannot be opened until you have opened the box — in a
// one-attempt race, a glance at the best score is a head start. The server enforces
// it too: it will not hand today's board to anyone who has not opened the box.
// `tab`/`onTab`: the daily's two boards (DAILY_BOARDS), shown as tabs once it is open.
function Leaderboard({ board, open, onToggle, locked = false, tab = null, onTab = null }) {
	const tabbed = !!(tab && board && !board.error && board.best);
	const view = tabbed && tab === "best" ? board.best : board;
	const entries = view && !view.error ? view.entries : [];
	const you = view && !view.error ? view.you : null;
	const youListed = entries.some((e) => e.you);
	return (
		<div className={`bx-board${open ? " open" : ""}${locked ? " locked" : ""}`}>
			<button type="button" className="bx-board-hd" aria-expanded={open} onClick={onToggle} disabled={locked}>
				<h2>Leaderboard</h2>{CHEVRON}
			</button>
			{open && tabbed && <div className="bx-tabs" role="tablist">
				{DAILY_BOARDS.map(([key, label]) => (
					<button key={key} type="button" role="tab" className="bx-tab" data-board={key}
						aria-selected={tab === key} onClick={() => onTab(key)}>{label}</button>
				))}
			</div>}
			{open && (entries.length ? (
				<ol className="bx-rows">
					{entries.map((e) => (
						<li key={e.rank} className={`bx-row${e.you ? " me" : ""}${e.optimal ? " optimal" : ""}`}>
							<span className="bx-row-rank">{e.rank}</span>
							<span className="bx-row-name">{e.name}</span>
							<span className="bx-row-moves">{e.moves}</span>
						</li>
					))}
					{you && !youListed && <>
						<li className="bx-gap" aria-hidden="true">⋯</li>
						<li className={`bx-row me${you.optimal ? " optimal" : ""}`}>
							<span className="bx-row-rank">{you.rank}</span>
							<span className="bx-row-name">You</span>
							<span className="bx-row-moves">{you.moves}</span>
						</li>
					</>}
				</ol>
			) : <div className="bx-empty" aria-label="No entries">—</div>)}
		</div>
	);
}

// PORTRAIT ONLY ON A PHONE. A page cannot lock the orientation in an ordinary browser
// tab (the Screen Orientation lock only works installed/fullscreen, and iOS Safari has
// none), so a phone turned sideways gets the page turned back: the root is counter-
// rotated to the device and sized to the portrait box, which keeps the layout fixed to
// the phone. Where the real lock IS allowed it is taken too. Direction comes from the
// screen angle: 90 = turned counter-clockwise, so the page turns -90deg to follow it.
const PHONE_LANDSCAPE = "(orientation: landscape) and (pointer: coarse) and (max-height: 540px)";
function usePortrait() {
	const [rot, setRot] = useState(null);
	useEffect(() => {
		const mq = window.matchMedia(PHONE_LANDSCAPE);
		const update = () => {
			if (!mq.matches) { setRot(null); return; }
			const so = window.screen && window.screen.orientation;
			const angle = so && typeof so.angle === "number" ? so.angle
				: typeof window.orientation === "number" ? (window.orientation + 360) % 360 : 90;
			setRot({ cw: angle === 270, w: window.innerWidth, h: window.innerHeight });
		};
		update();
		try { window.screen?.orientation?.lock?.("portrait")?.catch?.(() => {}); } catch { /* not allowed here */ }
		mq.addEventListener?.("change", update);
		window.addEventListener("resize", update);
		window.addEventListener("orientationchange", update);
		return () => {
			mq.removeEventListener?.("change", update);
			window.removeEventListener("resize", update);
			window.removeEventListener("orientationchange", update);
			try { window.screen?.orientation?.unlock?.(); } catch { /* nothing to undo */ }
		};
	}, []);
	return rot;
}
const rotStyle = (r) => r && ({
	width: `${r.h}px`, height: `${r.w}px`, minHeight: 0,
	transform: r.cw ? `translateX(${r.w}px) rotate(90deg)` : `translateY(${r.h}px) rotate(-90deg)`,
});

// The header's sound toggle: a speaker, with waves or a cross. Remembered per device.
const SPEAKER = <path d="M4.5 9.5h3.2L12 5.8v12.4l-4.3-3.7H4.5Z" />;
const WAVES = <path d="M15.4 9.2a4 4 0 0 1 0 5.6M17.9 6.8a7.4 7.4 0 0 1 0 10.4" />;
const CROSS = <path d="M15.6 9.6l4.8 4.8M20.4 9.6l-4.8 4.8" />;

function MuteToggle() {
	const [muted, setM] = useState(isMuted);
	return (
		<button type="button" className="btn btn-ghost btn-sm bx-mute" aria-pressed={muted}
			aria-label={muted ? "Unmute sounds" : "Mute sounds"} title={muted ? "Unmute" : "Mute"}
			onClick={() => { setMuted(!muted); setM(!muted); }}>
			<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
				{SPEAKER}{muted ? CROSS : WAVES}
			</svg>
		</button>
	);
}

// Keys: 1-9 press the tiles row by row (1 is top-left).
function useTileKeys(pressTile) {
	const keyRef = useRef(null);
	keyRef.current = pressTile;
	useEffect(() => {
		const onKey = (e) => {
			if (e.ctrlKey || e.metaKey || e.altKey || /input|textarea|select/i.test(e.target?.tagName || "")) return;
			if (e.key >= "1" && e.key <= "9") keyRef.current(+e.key - 1);
			else return;
			e.preventDefault();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);
}

// ── the screen ───────────────────────────────────────────────────────────────
export default function BoxPuzzles({ authUser, onExit }) {
	const token = authUser && !authUser.guest ? authUser.session_token : null;
	const who = (authUser && !authUser.guest && authUser.id) || "guest";
	const [num, setNum] = useState(routeView);
	const [results, setResults] = useState(() => readJson(resultsKey(who), {}));
	const [daily, setDaily] = useState(() => readJson(dailyKey(who), null));

	// The URL is the source of truth for which box is open (Back/Forward included).
	useEffect(() => subscribe((r) => { if (r.game === "boxpuzzles") setNum(routeView()); }), []);
	const go = useCallback((n) => {
		pushPath(buildPath("boxpuzzles", n ? String(n) : undefined));
		setNum(n);
		window.scrollTo(0, 0);
	}, []);
	const noteDaily = useCallback((entry) => { setDaily(entry); writeJson(dailyKey(who), entry); }, [who]);

	// Your results: the server's when signed in (they carry `optimal`), else this device's.
	useEffect(() => {
		if (!token) return undefined;
		let live = true;
		api("/boxpuzzles/mine", token).then((d) => {
			if (!live || !d?.results) return;
			setResults(d.results);
			writeJson(resultsKey(who), d.results);
		}).catch(() => { /* keep the cached copy */ });
		return () => { live = false; };
	}, [token, who]);

	const noteResult = useCallback((id, entry) => {
		setResults((prev) => {
			const next = { ...prev, [id]: entry };
			writeJson(resultsKey(who), next);
			return next;
		});
	}, [who]);

	const rot = usePortrait();
	const rootRef = useRef(null);
	useEffect(() => { if (rootRef.current) rootRef.current.scrollTop = 0; }, [num]);

	const solved = Object.keys(results).filter((id) => BANK.some((p) => p.id === id)).length;
	return (
		<div ref={rootRef} className={`bx${rot ? " bx-rot" : ""}`} style={rotStyle(rot) || undefined}>
			<style>{baseCss + css}</style>
			<header className="bx-header">
				<button className="btn btn-ghost btn-sm" onClick={num ? () => go(null) : onExit}>← Back</button>
				<div className="bx-headtitle">Box Puzzles</div>
				<div className="bx-headright">{solved} / {BANK.length}<MuteToggle /></div>
			</header>
			{num === "daily" ? (
				<DailyScreen token={token} who={who} onDaily={noteDaily} />
			) : num ? (
				<BoxScreen key={num} n={num} token={token} best={results[BANK[num - 1].id]}
					onResult={noteResult} onGo={go} />
			) : (
				<Picker results={results} daily={daily} onPick={go} />
			)}
		</div>
	);
}

function BoxScreen({ n, token, best, onResult, onGo }) {
	const p = BANK[n - 1];
	const [box, setBox] = useState(() => newBox(p));
	const [shake, setShake] = useState(0);
	const [opened, setOpened] = useState(null);     // { moves, post: "guest"|"posting"|"error"|result }
	const [board, setBoard] = useState(null);
	const [boardOpen, setBoardOpen] = useState(false);

	const loadBoard = useCallback(() => {
		api(`/boxpuzzles/leaderboard/${p.id}`, token).then(setBoard).catch(() => setBoard({ error: true }));
	}, [p.id, token]);
	useEffect(loadBoard, [loadBoard]);


	const post = useCallback((moves) => {
		if (!token) { setOpened({ moves: moves.length, post: "guest" }); return; }
		setOpened({ moves: moves.length, post: "posting" });
		api("/boxpuzzles/solve", token, { puzzle: p.id, moves }).then((r) => {
			setOpened({ moves: moves.length, post: r });
			onResult(p.id, { moves: r.best, optimal: r.optimal });
			setBoard(r.leaderboard);
		}).catch(() => setOpened({ moves: moves.length, post: "error" }));
	}, [p.id, token, onResult]);

	const pressTile = (i) => {
		if (opened) return;
		tileSound();
		setBox(pressTileInBox(box, p.target, i));
	};
	const pressButton = (k) => {
		if (opened) return;
		const { box: next, result } = pressButtonInBox(box, p, k);
		if (result === "reset") { resetSound(); setShake((s) => s + 1); }
		else if (result === "open") { openSound(); setBoardOpen(true); }
		else litSound(next.lit.filter(Boolean).length);
		setBox(next);
		if (result === "open") {
			const moves = next.moves;
			if (!token && (!best || moves.length < best.moves)) onResult(p.id, { moves: moves.length });
			post(moves);
		}
	};
	const again = () => { setOpened(null); setBox(newBox(p)); };

	useTileKeys(pressTile);

	const result = opened && typeof opened.post === "object" ? opened.post : null;
	const optimalNow = !!(result && result.optimal && result.best === opened.moves);
	return (
		<div className="bx-wrap">
			<div className="bx-play">
				<div className="bx-stage">
					<div className="bx-nav">
						<button className="btn btn-ghost btn-sm bx-arrow" disabled={n <= 1} onClick={() => onGo(n - 1)} aria-label="Previous box">‹</button>
						<h1 className="bx-title">Box {n}</h1>
						<button className="btn btn-ghost btn-sm bx-arrow" disabled={n >= BANK.length} onClick={() => onGo(n + 1)} aria-label="Next box">›</button>
					</div>
					<BoxFace id={n} target={p.target} box={box} shake={shake} opened={!!opened}
						onTile={pressTile} onButton={pressButton} />
					<div className={`bx-controls${opened ? " bx-result" : ""}${optimalNow ? " optimal" : ""}`} role="status">
						<div className="bx-count"><b data-moves>{opened ? opened.moves : box.moves.length}</b>{(opened ? opened.moves : box.moves.length) === 1 ? "move" : "moves"}</div>
						{opened && <div className="bx-result-actions">
							{opened.post === "error" && <button className="btn btn-ghost btn-sm" onClick={() => post(box.moves)}>Retry</button>}
							<button className="btn btn-ghost btn-sm" onClick={again}>Play again</button>
							{n < BANK.length && <button className="btn btn-gold btn-sm" onClick={() => onGo(n + 1)}>Next box →</button>}
						</div>}
					</div>
				</div>
				<aside className="bx-side"><Leaderboard board={board} open={boardOpen} onToggle={() => setBoardOpen((o) => !o)} /></aside>
			</div>
		</div>
	);
}

// ── the daily box ────────────────────────────────────────────────────────────
const CLOCK = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" aria-hidden="true">
		<circle cx="12" cy="12" r="8.5" /><path d="M12 7.5V12l3 2" />
	</svg>
);

// Time left until the next daily box, h:mm:ss.
function Countdown({ at }) {
	const [now, setNow] = useState(() => Date.now());
	useEffect(() => {
		const t = setInterval(() => setNow(Date.now()), 1000);
		return () => clearInterval(t);
	}, []);
	const s = Math.max(0, Math.round(at - now / 1000));
	const hms = [Math.floor(s / 3600), Math.floor(s / 60) % 60, s % 60]
		.map((n, i) => (i ? String(n).padStart(2, "0") : String(n))).join(":");
	return <span className="bx-next" role="timer" aria-label={`Next daily box in ${hms}`}>{CLOCK}{hms}</span>;
}

function DailyScreen({ token, who, onDaily }) {
	const [daily, setDaily] = useState(null);     // { day, tiles, target, next_at, attempt, yesterday }
	const [gen, setGen] = useState(0);            // bumps on every load, so a reload re-reads the attempt
	const [failed, setFailed] = useState(false);
	const [yesterday, setYesterday] = useState(false);
	const load = useCallback(() => {
		setFailed(false);
		api("/boxpuzzles/daily", token).then((d) => { setDaily(d); setGen((g) => g + 1); })
			.catch(() => setFailed(true));
	}, [token]);
	useEffect(load, [load]);
	// The day turns at midnight Pacific; fetch the new box when it does.
	useEffect(() => {
		if (!daily) return undefined;
		const ms = daily.next_at * 1000 - Date.now() + 1500;
		const t = setTimeout(() => { setYesterday(false); load(); }, Math.min(Math.max(ms, 1000), 2 ** 31 - 1));
		return () => clearTimeout(t);
	}, [daily, load]);

	if (!daily) return (
		<div className="bx-wrap">
			<div className="bx-play"><div className="bx-stage">
				<div className="bx-nav"><h1 className="bx-title">Daily</h1></div>
				{failed && <button className="btn btn-ghost btn-sm" onClick={load}>Retry</button>}
			</div></div>
		</div>
	);
	if (yesterday && daily.yesterday)
		return <DailyYesterday key={daily.yesterday} day={daily.yesterday} token={token} onToday={() => setYesterday(false)} />;
	return <DailyToday key={`${daily.day}:${gen}`} daily={daily} token={token} who={who} onDaily={onDaily}
		onReload={load} onYesterday={daily.yesterday ? () => setYesterday(true) : null} />;
}

// The attempt to resume: the server's, unless this device holds one that extends it
// (presses made while a save was still on its way). A guest has only the device's.
function resumeAttempt(daily, token, who) {
	const local = readJson(dailyKey(who), null);
	const mine = local && local.day === daily.day && Array.isArray(local.segments) && local.segments.length ? local : null;
	const server = daily.attempt;
	if (!token) return mine ? { segments: mine.segments, solved: !!mine.solved, push: false } : null;
	if (server?.solved) return { segments: server.segments, solved: true, push: false };
	if (mine && !mine.solved && (!server || extendsAttempt(server.segments, mine.segments)))
		return { segments: mine.segments, solved: false,
			push: !server || totalMoves(mine.segments) > server.moves || mine.segments.length > server.segments.length };
	return server ? { segments: server.segments, solved: false, push: false } : null;
}

const ALL_LIT = [true, true, true, true];
const NONE_LIT = [false, false, false, false];

function DailyToday({ daily, token, who, onDaily, onReload, onYesterday }) {
	const puzzle = { tiles: daily.tiles, target: daily.target };
	const [start] = useState(() => resumeAttempt(daily, token, who));
	const [segments, setSegments] = useState(() => (start ? start.segments : [[]]));
	const [box, setBox] = useState(() => ({
		tiles: boardAfter(daily.tiles, (start ? start.segments : [[]]).at(-1)),
		lit: start?.solved ? ALL_LIT : NONE_LIT, moves: [],
	}));
	// { moves, post: "guest" | "done" (opened on an earlier visit) | "posting" | "error" | server result }
	const [opened, setOpened] = useState(() => (start?.solved
		? { moves: totalMoves(start.segments), post: token ? "done" : "guest" } : null));
	const [shake, setShake] = useState(0);
	const [board, setBoard] = useState(null);
	const [boardOpen, setBoardOpen] = useState(!!start?.solved);
	const [tab, setTab] = useState("first");
	// A RETRY, once the attempt has opened the box: a fresh box under the numbered
	// boxes' rules (a reset clears its count, nothing is saved mid-solve), whose
	// opening posts to Best Shot. { moves, post } like `opened`.
	const [retryBox, setRetryBox] = useState(null);
	const [retryOpened, setRetryOpened] = useState(null);

	const saveLocal = useCallback((segs, solved, extra = {}) =>
		onDaily({ day: daily.day, segments: segs, moves: totalMoves(segs), solved, ...extra }), [daily.day, onDaily]);

	// SAVING: one request in flight at a time, the latest attempt queued behind it.
	// Presses are debounced; opening is sent at once. A save the server refuses as
	// "not the attempt on record" means another device played on: drop this copy
	// and load the server's.
	const sync = useRef({ busy: false, next: null, timer: 0 });
	const flush = useCallback(() => {
		const s = sync.current;
		clearTimeout(s.timer);
		s.timer = 0;
		if (s.busy || !s.next) return;
		const { segs, open } = s.next;
		s.next = null;
		s.busy = true;
		api("/boxpuzzles/daily/attempt", token, { day: daily.day, segments: segs, open }, true).then((r) => {
			if (!open) return;
			setOpened({ moves: r.moves, post: r });
			setBoard(r.leaderboard);
			saveLocal(segs, true, { optimal: r.optimal });
		}).catch((e) => {
			if (e.status === 409 || (e.status === 400 && !open)) { s.next = null; onDaily(null); onReload(); }
			else if (open) setOpened((o) => ({ ...o, post: "error" }));
		}).finally(() => {
			s.busy = false;
			if (s.next) flush();
		});
	}, [token, daily.day, saveLocal, onDaily, onReload]);
	const queue = useCallback((segs, open) => {
		if (!token) return;
		const s = sync.current;
		s.next = { segs, open };
		clearTimeout(s.timer);
		if (open) flush();
		else s.timer = setTimeout(flush, 350);
	}, [token, flush]);
	// A resumed attempt that is ahead of the server goes up now; one still waiting
	// when the page is hidden or left goes up then.
	const flushRef = useRef(flush);
	flushRef.current = flush;
	useEffect(() => {
		if (start?.push) queue(start.segments, false);
		const hide = () => { if (document.visibilityState === "hidden" && sync.current.timer) flushRef.current(); };
		document.addEventListener("visibilitychange", hide);
		return () => {
			document.removeEventListener("visibilitychange", hide);
			if (sync.current.timer) flushRef.current();
		};
	}, []); // eslint-disable-line react-hooks/exhaustive-deps

	// Today's board is served only to someone who has opened the box: the server knows
	// a signed-in player's, and a guest sends the line that opened it as the proof.
	const proof = token ? "" : `?line=${segments.at(-1).join(",")}`;
	const loadBoard = useCallback(() => {
		api(`/boxpuzzles/daily/${daily.day}/board${proof}`, token).then(setBoard).catch(() => setBoard({ error: true }));
	}, [daily.day, token, proof]);
	const settled = !!opened && (opened.post === "guest" || opened.post === "done");
	useEffect(() => { if (settled) loadBoard(); }, [settled, loadBoard]);

	const postRetry = useCallback((moves) => {
		if (!token) { setRetryOpened({ moves: moves.length, post: "guest" }); return; }
		setRetryOpened({ moves: moves.length, post: "posting" });
		api("/boxpuzzles/daily/retry", token, { day: daily.day, moves }).then((r) => {
			setRetryOpened({ moves: moves.length, post: r });
			setBoard(r.leaderboard);
			setTab("best");
		}).catch((e) => {
			if (e.status === 409) onReload();             // the day turned over
			else setRetryOpened({ moves: moves.length, post: "error" });
		});
	}, [token, daily.day, onReload]);
	const playAgain = () => { setRetryOpened(null); setRetryBox(newBox(puzzle)); };

	const pressRetryTile = (i) => {
		if (retryOpened) return;
		tileSound();
		setRetryBox(pressTileInBox(retryBox, daily.target, i));
	};
	const pressRetryButton = (k) => {
		if (retryOpened) return;
		const { box: next, result } = pressButtonInBox(retryBox, puzzle, k);
		if (result === "reset") { resetSound(); setShake((s) => s + 1); }
		else if (result === "open") { openSound(); setBoardOpen(true); }
		else litSound(next.lit.filter(Boolean).length);
		setRetryBox(next);
		if (result === "open") postRetry(next.moves);
	};

	const pressTile = (i) => {
		if (retryBox) { pressRetryTile(i); return; }
		if (opened) return;
		tileSound();
		const segs = [...segments.slice(0, -1), [...segments.at(-1), i]];
		setSegments(segs);
		setBox(pressTileInBox(box, daily.target, i));
		saveLocal(segs, false);
		queue(segs, false);
	};
	const pressButton = (k) => {
		if (retryBox) { pressRetryButton(k); return; }
		if (opened) return;
		const { box: next, result } = pressButtonInBox(box, puzzle, k);
		setBox(next);
		if (result === "reset") {
			resetSound();
			setShake((s) => s + 1);
			// back to the first board, and the count carries on: a new segment begins
			if (segments.at(-1).length) {
				const segs = [...segments, []];
				setSegments(segs);
				saveLocal(segs, false);
				queue(segs, false);
			}
		} else if (result === "open") {
			openSound();
			setBoardOpen(true);
			const moves = totalMoves(segments);
			if (!token) { setOpened({ moves, post: "guest" }); saveLocal(segments, true); }
			else { setOpened({ moves, post: "posting" }); queue(segments, true); }
		} else litSound(next.lit.filter(Boolean).length);
	};
	useTileKeys(pressTile);

	const firstResult = opened && typeof opened.post === "object" ? opened.post : null;
	// Play again once the attempt is on record (a guest's: on this device).
	const recorded = !!(firstResult || opened?.post === "done" || opened?.post === "guest");
	let shown, done, count, optimal, failed, resend;
	if (retryBox) {
		const r = retryOpened && typeof retryOpened.post === "object" ? retryOpened.post : null;
		shown = retryBox; done = retryOpened;
		count = retryOpened ? retryOpened.moves : retryBox.moves.length;
		optimal = !!(r && r.optimal && r.best === retryOpened.moves);
		failed = retryOpened?.post === "error";
		resend = () => postRetry(retryBox.moves);
	} else {
		shown = box; done = opened;
		count = opened ? opened.moves : totalMoves(segments);
		optimal = !!(firstResult ? firstResult.optimal : opened?.post === "done" && board?.you?.optimal);
		failed = opened?.post === "error";
		resend = () => { setOpened((o) => ({ ...o, post: "posting" })); queue(segments, true); };
	}
	return (
		<div className="bx-wrap">
			<div className="bx-play">
				<div className="bx-stage">
					<div className="bx-nav">
						<button className="btn btn-ghost btn-sm bx-arrow" disabled={!onYesterday} onClick={onYesterday || undefined} aria-label="Yesterday's box">‹</button>
						<h1 className="bx-title">Daily</h1>
						<button className="btn btn-ghost btn-sm bx-arrow" disabled aria-label="Today's box">›</button>
					</div>
					<BoxFace id="daily" target={daily.target} box={shown} shake={shake} opened={!!done}
						onTile={pressTile} onButton={pressButton} />
					<div className={`bx-controls${done ? " bx-result" : ""}${optimal ? " optimal" : ""}`} role="status"
						data-shot={retryBox ? "best" : "first"}>
						<div className="bx-count"><b data-moves>{count}</b>{count === 1 ? "move" : "moves"}</div>
						{done && <div className="bx-result-actions">
							{failed && <button className="btn btn-ghost btn-sm" onClick={resend}>Retry</button>}
							{recorded && !failed && done.post !== "posting" &&
								<button className="btn btn-ghost btn-sm bx-again" onClick={playAgain}>Play again</button>}
							<Countdown at={daily.next_at} />
						</div>}
					</div>
				</div>
				<aside className="bx-side">
					<Leaderboard board={board} open={boardOpen && !!opened} locked={!opened} onToggle={() => setBoardOpen((o) => !o)}
						tab={tab} onTab={setTab} />
				</aside>
			</div>
		</div>
	);
}

// YESTERDAY, VIEW ONLY: its first board, its minimum (blue, as a minimum is drawn
// everywhere), every row that reached it in blue, and ▶ to watch a shortest line play.
function DailyYesterday({ day, token, onToday }) {
	const [data, setData] = useState(null);
	const [failed, setFailed] = useState(false);
	const [step, setStep] = useState(0);          // presses of the line shown so far
	const [playing, setPlaying] = useState(false);
	const [boardOpen, setBoardOpen] = useState(true);
	const [tab, setTab] = useState("first");
	const load = useCallback(() => {
		setFailed(false);
		api(`/boxpuzzles/daily/${day}/board`, token).then(setData).catch(() => setFailed(true));
	}, [day, token]);
	useEffect(load, [load]);
	useEffect(() => {
		if (!playing || !data) return undefined;
		if (step >= data.solution.length) { setPlaying(false); return undefined; }
		const t = setTimeout(() => setStep((n) => n + 1), 700);
		return () => clearTimeout(t);
	}, [playing, step, data]);

	const nav = (
		<div className="bx-nav">
			<button className="btn btn-ghost btn-sm bx-arrow" disabled aria-label="Yesterday's box">‹</button>
			<h1 className="bx-title">{shortDate(day)}</h1>
			<button className="btn btn-ghost btn-sm bx-arrow" onClick={onToday} aria-label="Today's box">›</button>
		</div>
	);
	if (!data) return (
		<div className="bx-wrap"><div className="bx-play"><div className="bx-stage">
			{nav}
			{failed && <button className="btn btn-ghost btn-sm" onClick={load}>Retry</button>}
		</div></div></div>
	);
	const line = data.solution;
	const done = step > 0 && step >= line.length;
	const box = { tiles: boardAfter(data.tiles, line.slice(0, step)), lit: done ? ALL_LIT : NONE_LIT, moves: [] };
	return (
		<div className="bx-wrap">
			<div className="bx-play">
				<div className="bx-stage">
					{nav}
					<BoxFace id="yesterday" target={data.target} box={box} opened={done} disabled
						hint={playing && step < line.length ? line[step] : -1} />
					<div className="bx-controls bx-result optimal" role="status">
						<div className="bx-count"><b data-moves>{playing || step ? step : data.minimum}</b>{data.minimum === 1 ? "move" : "moves"}</div>
						<div className="bx-result-actions">
							<button className="btn btn-ghost btn-sm bx-replay" disabled={playing} aria-label="Play a shortest line"
								onClick={() => { setStep(0); setPlaying(true); }}>▶</button>
						</div>
					</div>
				</div>
				<aside className="bx-side"><Leaderboard board={data} open={boardOpen} onToggle={() => setBoardOpen((o) => !o)}
					tab={tab} onTab={setTab} /></aside>
			</div>
		</div>
	);
}
