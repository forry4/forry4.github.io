import { useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_HTTP, markBackendAwake } from "../shared/backend.js";
import { GAME_INFO } from "../shared/catalog.js";
import { LobbyHeader, LobbyUser, lobbyCss } from "../shared/lobby.jsx";
import { baseCss } from "../shared/theme.js";
import { CHARACTERS } from "./loadouts.js";
import { camera, draw } from "./render.js";
import { createSim, step, TPS } from "./sim.js";
import css from "./BossRush.css?inline";

const GAME = GAME_INFO.bossrush;
const styles = baseCss + lobbyCss + css;
const STEP_MS = 1000 / TPS;
const DIRECTIONS = {
	KeyA: [-1, 0], ArrowLeft: [-1, 0], KeyD: [1, 0], ArrowRight: [1, 0],
	KeyW: [0, -1], ArrowUp: [0, -1], KeyS: [0, 1], ArrowDown: [0, 1],
};

async function request(path, options) {
	const res = await fetch(`${BACKEND_HTTP}/bossrush${path}`, options);
	if (res.ok) {
		markBackendAwake();
		return res.json();
	}
	const error = await res.json().catch(() => null);
	throw new Error(typeof error?.detail === "string" ? error.detail : "Could not reach the Boss Rush server.");
}

function formatTime(ms) {
	const minutes = Math.floor(ms / 60_000);
	const seconds = (Math.floor(ms) % 60_000 / 1000).toFixed(3).padStart(6, "0");
	return `${minutes}:${seconds}`;
}

function Leaderboard() {
	const [entries, setEntries] = useState(null);
	const [error, setError] = useState("");
	const [retry, setRetry] = useState(0);
	useEffect(() => {
		const controller = new AbortController();
		setError("");
		request("/leaderboard", { signal: controller.signal })
			.then((board) => setEntries(board.entries))
			.catch(() => { if (!controller.signal.aborted) setError("Leaderboard unavailable."); });
		return () => controller.abort();
	}, [retry]);
	return <section className="br-panel br-board">
		<h2>Leaderboard</h2>
		{error ? <p role="status">{error} <button className="btn btn-outline" onClick={() => setRetry(retry + 1)}>Refresh</button></p>
			: entries === null ? <p role="status">Loading times…</p>
			: entries.length === 0 ? <p>No clears yet.</p>
			: <table>
				<thead><tr><th scope="col">Rank</th><th scope="col">Player</th><th scope="col">Character</th><th scope="col">Time</th></tr></thead>
				<tbody>{entries.map((entry) => <tr key={entry.rank}>
					<td>{entry.rank}</td><td>{entry.name}</td><td>{CHARACTERS[entry.character]?.name}</td><td>{formatTime(entry.elapsed_ms)}</td>
				</tr>)}</tbody>
			</table>}
	</section>;
}

export default function BossRush({ authUser, onExit }) {
	const [run, setRun] = useState(null);
	const [starting, setStarting] = useState(false);
	const [error, setError] = useState("");

	async function start(character) {
		setStarting(true);
		setError("");
		try {
			const headers = { "Content-Type": "application/json" };
			if (authUser?.session_token) headers.Authorization = `Bearer ${authUser.session_token}`;
			const attempt = await request("/runs", { method: "POST", headers, body: JSON.stringify({ character }) });
			setRun({ ...attempt, character, started: performance.now() });
		} catch (e) {
			setError(e.message);
		} finally {
			setStarting(false);
		}
	}

	const chooseCharacter = () => setRun(null);
	return <div className="bossrush" style={{ "--lby-accent": GAME.accent }}>
		<style>{styles}</style>
		{run ? <RushRun run={run} onLeave={chooseCharacter} />
			: <>
				<LobbyHeader title={GAME.name} onBack={onExit} user={<LobbyUser user={authUser} />} />
				<main className="br-menu">
					<section className="br-panel br-select">
						<h1>Choose your character</h1>
						<p>Defeat all three bosses in a single timed run. The order changes every run.</p>
						<div className="br-characters">
							{Object.entries(CHARACTERS).map(([id, character]) => <button
								key={id} type="button" className="br-character" disabled={starting} onClick={() => start(id)}>
								<i className={`br-glyph br-${id}`} aria-hidden="true" />
								<strong>{character.name}</strong>
								<span>{character.description}</span>
							</button>)}
						</div>
						{starting && <p role="status">Opening rift…</p>}
						{error && <p className="br-error" role="alert">{error}</p>}
						<p className="br-controls">WASD or arrows to move · Mouse to aim and fire · Q for ability · R for potion · E for portal</p>
					</section>
					<Leaderboard />
				</main>
			</>}
	</div>;
}

function RushRun({ run, onLeave }) {
	const [stage, setStage] = useState(0);
	const [status, setStatus] = useState("fight");
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [elapsed, setElapsed] = useState(0);
	const [savedTime, setSavedTime] = useState(null);
	const dungeon = run.stages[stage];
	const final = stage === run.stages.length - 1;
	useEffect(() => {
		if (status === "won" || status === "dead") return;
		const timer = setInterval(() => setElapsed(performance.now() - run.started), 100);
		return () => clearInterval(timer);
	}, [run.started, status]);

	const save = useCallback(async () => {
		setBusy(true);
		setError("");
		try {
			const result = await request(`/runs/${run.run_id}/clears/${stage + 1}`, { method: "POST" });
			if (final) {
				setSavedTime(result.elapsed_ms);
			} else {
				setStage((n) => n + 1);
				setStatus("fight");
			}
		} catch (e) {
			setError(e.message);
		} finally {
			setBusy(false);
		}
	}, [run.run_id, stage, final]);

	const fightEvent = useCallback((event) => {
		if (event === "portal") { setStatus("portal"); return; }
		if (event === "advance") { setStatus("advance"); save(); return; }
		setElapsed(performance.now() - run.started);
		setStatus(event);
		if (event === "won") save();
	}, [run.started, save]);

	return <main className="br-run">
		<header className="br-run-head">
			<div><span className="br-stage">Boss {stage + 1} / {run.stages.length}</span> <strong>{dungeon.name}</strong></div>
			<time aria-label="Run time">{formatTime(savedTime ?? elapsed)}</time>
			<button type="button" className="btn btn-outline" disabled={busy} onClick={onLeave}>
				{status === "won" || status === "dead" ? "Characters" : "End run"}
			</button>
		</header>
		<div className="br-arena">
			<Encounter key={stage} dungeon={dungeon} character={run.character} final={final} onEvent={fightEvent} />
			{(status === "advance" || status === "won" || status === "dead") && <div className="br-shade">
				<section className="br-panel br-result" aria-live="polite">
					<h2>{status === "won" ? "Boss Rush cleared" : status === "dead" ? "Run ended" : `${dungeon.boss_name} defeated`}</h2>
					{status === "won" && <p className="br-final-time">{formatTime(savedTime ?? elapsed)}</p>}
					{busy && <p>{final ? "Posting your time…" : "Entering next rift…"}</p>}
					{savedTime !== null && <p>Time posted to the leaderboard.</p>}
					{status === "dead" && <p>You reached {dungeon.boss_name}, boss {stage + 1} of {run.stages.length}.</p>}
					{error && <p className="br-error">{error}</p>}
					{error && <button type="button" className="btn btn-outline" onClick={save}>
						{final ? "Retry posting time" : "Retry portal"}
					</button>}
					{status !== "advance" && <button type="button" className="btn btn-outline" disabled={busy} onClick={onLeave}>
						{status === "won" && savedTime !== null ? "View leaderboard" : "Choose character"}
					</button>}
				</section>
			</div>}
		</div>
		<p className="br-run-foot" aria-live="polite">
			{status === "portal" ? "Boss defeated. Approach the blue portal and press E." : "WASD move · Click fire · Q ability · R potion · T auto-fire"}
		</p>
	</main>;
}

function Encounter({ dungeon, character, final, onEvent }) {
	const canvas = useRef(null);
	useEffect(() => {
		const cv = canvas.current;
		const ctx = cv.getContext("2d");
		const st = createSim(dungeon, CHARACTERS[character].gear, { classId: character });
		const keys = new Set();
		const edge = { ability: false, potion: false, enter: false };
		const pointer = { x: 0, y: 0, fire: false };
		const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		let auto = false, ended = false, raf, px, cam;
		let last = performance.now(), acc = 0;

		function resize() {
			const dpr = Math.min(window.devicePixelRatio || 1, 2);
			cv.width = Math.max(1, Math.round(cv.clientWidth * dpr));
			cv.height = Math.max(1, Math.round(cv.clientHeight * dpr));
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			px = Math.max(18, Math.min(cv.clientWidth / 23, cv.clientHeight / 16, 42));
			cam = camera(st, cv.clientWidth, cv.clientHeight, px, st.p, true);
		}
		const observer = new ResizeObserver(resize);
		observer.observe(cv);
		resize();

		function tick() {
			let mx = 0, my = 0;
			for (const key of keys) { mx += DIRECTIONS[key][0]; my += DIRECTIONS[key][1]; }
			step(st, {
				...edge, mx: Math.sign(mx), my: Math.sign(my),
				ax: (pointer.x - cam.ox) / px - st.p.x, ay: (pointer.y - cam.oy) / px - st.p.y,
				fire: pointer.fire || auto,
			});
			edge.ability = edge.potion = edge.enter = false;
			if (st.status === "dead") { ended = true; onEvent("dead"); }
			else if (st.status === "complete") { ended = true; onEvent("advance"); }
			else if (st.events.some((e) => e.type === "cleared")) {
				if (final) { ended = true; st.portal = null; onEvent("won"); }
				else onEvent("portal");
			}
		}

		function frame(now) {
			acc += Math.min(100, now - last);
			last = now;
			while (!ended && acc >= STEP_MS) { acc -= STEP_MS; tick(); }
			const width = cv.clientWidth, height = cv.clientHeight;
			cam = camera(st, width, height, px, st.p, true);
			draw(ctx, st, { width, height, px, calm, auto, bossName: dungeon.boss_name,
				aim: { x: (pointer.x - cam.ox) / px - st.p.x, y: (pointer.y - cam.oy) / px - st.p.y } });
			if (!ended) raf = requestAnimationFrame(frame);
		}
		raf = requestAnimationFrame(frame);

		function keyDown(e) {
			if (ended || e.altKey || e.ctrlKey || e.metaKey) return;
			if (DIRECTIONS[e.code]) { keys.add(e.code); e.preventDefault(); return; }
			if (e.repeat) return;
			if (e.code === "KeyQ" || (e.code === "Space" && e.target === cv)) { edge.ability = true; e.preventDefault(); }
			else if (e.code === "KeyR") edge.potion = true;
			else if (e.code === "KeyE") edge.enter = true;
			else if (e.code === "KeyT") auto = !auto;
		}
		const keyUp = (e) => keys.delete(e.code);
		const blur = () => { keys.clear(); pointer.fire = false; edge.ability = edge.potion = edge.enter = false; };
		const move = (e) => {
			const rect = cv.getBoundingClientRect();
			pointer.x = e.clientX - rect.left;
			pointer.y = e.clientY - rect.top;
		};
		const down = (e) => {
			move(e);
			if (e.button === 0) pointer.fire = true;
			if (e.button === 2) edge.ability = true;
		};
		const up = (e) => { if (e.button === 0) pointer.fire = false; };
		const noMenu = (e) => e.preventDefault();
		window.addEventListener("keydown", keyDown);
		window.addEventListener("keyup", keyUp);
		window.addEventListener("blur", blur);
		window.addEventListener("mouseup", up);
		cv.addEventListener("mousemove", move);
		cv.addEventListener("mousedown", down);
		cv.addEventListener("contextmenu", noMenu);
		return () => {
			cancelAnimationFrame(raf);
			observer.disconnect();
			window.removeEventListener("keydown", keyDown);
			window.removeEventListener("keyup", keyUp);
			window.removeEventListener("blur", blur);
			window.removeEventListener("mouseup", up);
			cv.removeEventListener("mousemove", move);
			cv.removeEventListener("mousedown", down);
			cv.removeEventListener("contextmenu", noMenu);
		};
	}, [dungeon, character, final, onEvent]);

	return <canvas ref={canvas} tabIndex={0} role="img" aria-label={`${dungeon.name} boss arena`} />;
}
