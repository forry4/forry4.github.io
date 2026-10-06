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
// Routes: /boxpuzzles (the picker) and /boxpuzzles/<n> (box n, numbered easiest
// first). This screen owns its segment 2, like Notes.
import { useState, useEffect, useCallback, useRef } from "react";
import { baseCss } from "../shared/theme.js";
import { buildPath, parsePath, pushPath, subscribe } from "../shared/router.js";
import _cssText from "./BoxPuzzles.css?inline";
import BANK from "./puzzles.json";
import { CORNERS, newBox, pressTileInBox, pressButtonInBox } from "./engine.js";
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

const routeNumber = () => {
	const n = parseInt(parsePath().room || "", 10);
	return n >= 1 && n <= BANK.length ? n : null;
};

async function api(path, token, body) {
	const headers = token ? { Authorization: `Bearer ${token}` } : {};
	if (body) headers["Content-Type"] = "application/json";
	const res = await fetch(HTTP_BASE + path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined });
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

function Picker({ results, onPick }) {
	return (
		<div className="bx-wrap">
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

// ALWAYS THERE, AND CLOSED UNTIL ASKED: the scores are a spoiler (a low best says
// how short the line is), so a box starts with the leaderboard folded to its title
// and opens it for you once you have opened the box. No loading line, no empty-state
// sentence: an open board with nobody on it shows a dash.
const CHEVRON = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
		<path d="M8 10l4 4 4-4" />
	</svg>
);

function Leaderboard({ board, open, onToggle }) {
	const entries = board && !board.error ? board.entries : [];
	const you = board && !board.error ? board.you : null;
	const youListed = entries.some((e) => e.you);
	return (
		<div className={`bx-board${open ? " open" : ""}`}>
			<button type="button" className="bx-board-hd" aria-expanded={open} onClick={onToggle}>
				<h2>Leaderboard</h2>{CHEVRON}
			</button>
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

// ── the screen ───────────────────────────────────────────────────────────────
export default function BoxPuzzles({ authUser, onExit }) {
	const token = authUser && !authUser.guest ? authUser.session_token : null;
	const who = (authUser && !authUser.guest && authUser.id) || "guest";
	const [num, setNum] = useState(routeNumber);
	const [results, setResults] = useState(() => readJson(resultsKey(who), {}));

	// The URL is the source of truth for which box is open (Back/Forward included).
	useEffect(() => subscribe((r) => { if (r.game === "boxpuzzles") setNum(routeNumber()); }), []);
	const go = useCallback((n) => {
		pushPath(buildPath("boxpuzzles", n ? String(n) : undefined));
		setNum(n);
		window.scrollTo(0, 0);
	}, []);

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
			{num ? (
				<BoxScreen key={num} n={num} token={token} best={results[BANK[num - 1].id]}
					onResult={noteResult} onGo={go} />
			) : (
				<Picker results={results} onPick={go} />
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

	// Keys: 1-9 press the tiles row by row (1 is top-left).
	const keyRef = useRef(null);
	keyRef.current = { pressTile };
	useEffect(() => {
		const onKey = (e) => {
			if (e.ctrlKey || e.metaKey || e.altKey || /input|textarea|select/i.test(e.target?.tagName || "")) return;
			if (e.key >= "1" && e.key <= "9") keyRef.current.pressTile(+e.key - 1);
			else return;
			e.preventDefault();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);

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
					<div key={shake} className={`bx-box${shake ? " bx-shake" : ""}${opened ? " open" : ""}`} data-box={n}>
						{CORNERS.map((c, k) => (
							<button key={k} type="button" className={`bx-cbtn bx-c${k}${box.lit[k] ? " lit" : ""}`}
								style={swatch(p.target[k])} disabled={!!opened} data-button={k}
								aria-label={`${CORNER_NAME[k]} button, ${COLOR_NAME[p.target[k]]}${box.lit[k] ? ", lit" : ""}`}
								aria-pressed={box.lit[k]} onClick={() => pressButton(k)} />
						))}
						<div className="bx-grid">
							{box.tiles.map((c, i) => (
								<button key={i} type="button" className="bx-tile" style={swatch(c)} data-tile={i} data-color={c}
									disabled={!!opened} aria-label={`Tile ${i + 1}, ${COLOR_NAME[c]}`} onClick={() => pressTile(i)} />
							))}
						</div>
					</div>
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
