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

const css = _cssText;
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

const COLOR_NAME = { GY: "gray", WH: "white", PU: "violet", YE: "yellow", GN: "green",
	PI: "pink", BK: "black", RD: "red", OR: "orange", BU: "blue" };
const CORNER_NAME = ["top-left", "top-right", "bottom-right", "bottom-left"];
const swatch = (c) => ({ "--t": `var(--bx-${c})` });

// ── storage (every access guarded: private windows and blocked storage throw) ──
const PROGRESS_KEY = "boxpuzzles.progress.v1";      // { id: [tile presses since reset] }
const resultsKey = (who) => `boxpuzzles.results.v1.${who}`;   // { id: { moves, optimal? } }
function readJson(key, fallback) {
	try { const v = JSON.parse(localStorage.getItem(key)); return v && typeof v === "object" ? v : fallback; }
	catch { return fallback; }
}
function writeJson(key, value) {
	try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* storage unavailable */ }
}
function saveProgress(id, moves) {
	const all = readJson(PROGRESS_KEY, {});
	if (moves.length) all[id] = moves; else delete all[id];
	writeJson(PROGRESS_KEY, all);
}

// A box resumed from storage: replay its saved presses (buttons are not saved; a
// lit button is one press away again).
function restoredBox(p) {
	let box = newBox(p);
	const saved = readJson(PROGRESS_KEY, {})[p.id];
	if (Array.isArray(saved)) {
		for (const i of saved) if (Number.isInteger(i) && i >= 0 && i < 9) box = pressTileInBox(box, p.target, i);
	}
	return box;
}

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

// Rows or nothing: no loading line, no empty state, no footnotes.
function Leaderboard({ board }) {
	if (!board || board.error || !board.entries.length) return null;
	const { entries, you } = board;
	const youListed = entries.some((e) => e.you);
	return (
		<div className="bx-board">
			<h2>Leaderboard</h2>
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
		</div>
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

	const solved = Object.keys(results).filter((id) => BANK.some((p) => p.id === id)).length;
	return (
		<div className="bx">
			<style>{baseCss + css}</style>
			<header className="bx-header">
				<button className="btn btn-ghost btn-sm" onClick={num ? () => go(null) : onExit}>← Back</button>
				<div className="bx-headtitle">Box Puzzles</div>
				<div className="bx-headright">{solved} / {BANK.length}</div>
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
	const [box, setBox] = useState(() => restoredBox(p));
	const [shake, setShake] = useState(0);
	const [opened, setOpened] = useState(null);     // { moves, post: "guest"|"posting"|"error"|result }
	const [board, setBoard] = useState(null);

	const loadBoard = useCallback(() => {
		api(`/boxpuzzles/leaderboard/${p.id}`, token).then(setBoard).catch(() => setBoard({ error: true }));
	}, [p.id, token]);
	useEffect(loadBoard, [loadBoard]);

	const commit = (next) => {
		setBox(next);
		saveProgress(p.id, next.moves);
	};

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
		commit(pressTileInBox(box, p.target, i));
	};
	const pressButton = (k) => {
		if (opened) return;
		const { box: next, result } = pressButtonInBox(box, p, k);
		if (result === "reset") setShake((s) => s + 1);
		commit(next);
		if (result === "open") {
			const moves = next.moves;
			saveProgress(p.id, []);
			if (!token && (!best || moves.length < best.moves)) onResult(p.id, { moves: moves.length });
			post(moves);
		}
	};
	const again = () => { setOpened(null); setBox(newBox(p)); saveProgress(p.id, []); };

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
				<aside className="bx-side"><Leaderboard board={board} /></aside>
			</div>
		</div>
	);
}
