import { useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_HTTP, markBackendAwake } from "../shared/backend.js";
import { GAME_INFO } from "../shared/catalog.js";
import { LobbyHeader, LobbyUser, lobbyCss } from "../shared/lobby.jsx";
import { baseCss } from "../shared/theme.js";
import { useNoContextMenu } from "../shared/useNoContextMenu.js";
import { CHARACTERS } from "./loadouts.js";
import { camera, draw } from "./render.js";
import { createSim, fingerprint, step, TPS } from "./sim.js";
import { newRecording, recordInput, startStage } from "./replay.js";
import { canPackFilms, filmRun, openFilmFile, packFilm, unpackFilm } from "./film.js";
import Replay from "./Replay.jsx";
import css from "./BossRush.css?inline";

const GAME = GAME_INFO.bossrush;
const styles = baseCss + lobbyCss + css;
const STEP_MS = 1000 / TPS;
const AUTO_FIRE_KEY = "bossrush.autoFire";
let autoFire = false;
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

/* The day a run finished, short ("Nov 21"; with the year once it is not this
 * year's), and the full date and time for its tooltip. */
function runDate(seconds) {
	if (!seconds) return { short: "", full: "" };
	const d = new Date(seconds * 1000);
	const thisYear = d.getFullYear() === new Date().getFullYear();
	return {
		short: d.toLocaleDateString(undefined, thisYear ? { month: "short", day: "numeric" } : { month: "short", day: "numeric", year: "numeric" }),
		full: d.toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" }),
	};
}

/* A leaderboard run's film: fetched gzipped, unpacked here. */
async function fetchFilm(filmId) {
	const res = await fetch(`${BACKEND_HTTP}/bossrush/films/${encodeURIComponent(filmId)}`);
	if (!res.ok) throw new Error(res.status === 404 ? "This replay is no longer on the board." : "Could not load the replay.");
	return unpackFilm(await res.arrayBuffer());
}

function Leaderboard({ sets, setId, onSet, character, onCharacter }) {
	const [entries, setEntries] = useState(null);
	const [error, setError] = useState("");
	const [retry, setRetry] = useState(0);
	const [watching, setWatching] = useState(null);      // { film, title } once loaded
	const [loading, setLoading] = useState(null);        // the rank being fetched
	const [watchError, setWatchError] = useState("");
	const watch = async (entry) => {
		setWatchError("");
		setLoading(entry.rank);
		try {
			const film = await fetchFilm(entry.film_id);
			setWatching({ film, title: `${entry.name} · ${CHARACTERS[entry.character]?.name} · ${formatTime(entry.elapsed_ms)}` });
		} catch (e) {
			setWatchError(e.message);
		} finally {
			setLoading(null);
		}
	};
	const films = canPackFilms() && entries?.some((entry) => entry.film_id);
	const fileInput = useRef(null);
	const openFile = async (e) => {
		const file = e.target.files?.[0];
		e.target.value = "";                                // the same file can be picked again
		if (!file) return;
		setWatchError("");
		try {
			const film = await openFilmFile(file);
			setWatching({ film, title: film.title || file.name });
		} catch (err) {
			setWatchError(err.message);
		}
	};
	useEffect(() => {
		const controller = new AbortController();
		setError("");
		setEntries(null);
		const query = new URLSearchParams({ set_id: setId });
		if (character) query.set("character", character);
		request(`/leaderboard?${query}`, { signal: controller.signal })
			.then((board) => { if (!controller.signal.aborted) setEntries(board.entries); })
			.catch(() => { if (!controller.signal.aborted) setError("Leaderboard unavailable."); });
		return () => controller.abort();
	}, [retry, setId, character]);
	return <section className="br-panel br-board">
		<h2>Leaderboard</h2>
		<div className="br-filters">
			<div>
				<label htmlFor="br-board-set">Set</label>
				<select id="br-board-set" value={setId} onChange={(e) => onSet(e.target.value)}>
					{sets.map((set) => <option key={set.id} value={set.id}>{set.name}</option>)}
				</select>
			</div>
			<div>
				<label htmlFor="br-board-character">Character</label>
				<select id="br-board-character" value={character} onChange={(e) => onCharacter(e.target.value)}>
					<option value="">All characters</option>
					{Object.entries(CHARACTERS).map(([id, entry]) => <option key={id} value={id}>{entry.name}</option>)}
				</select>
			</div>
		</div>
		{error ? <p role="status">{error} <button className="btn btn-outline" onClick={() => setRetry(retry + 1)}>Refresh</button></p>
			: entries === null ? <p role="status">Loading times…</p>
			: entries.length === 0 ? <p>{character ? "No clears for this character." : "No clears yet."}</p>
			: <table>
				<thead><tr><th scope="col"><abbr title="Rank">#</abbr></th><th scope="col">Player</th><th scope="col">Character</th><th scope="col" className="br-date">Date</th><th scope="col" className="br-time">Time</th><th scope="col" className="br-taken"><abbr title="Damage taken"><span className="br-wide">Damage</span><span className="br-narrow" aria-hidden="true">Dmg</span></abbr></th>
					{films && <th scope="col" className="br-watch"><span className="br-sr-only">Replay</span></th>}</tr></thead>
				<tbody>{entries.map((entry) => <tr key={entry.rank}>
					<td>{entry.rank}</td><td>{entry.name}</td><td>{CHARACTERS[entry.character]?.name}</td>
					<td className="br-date"><time dateTime={entry.finished_at ? new Date(entry.finished_at * 1000).toISOString() : undefined}
						title={runDate(entry.finished_at).full}>{runDate(entry.finished_at).short}</time></td><td className="br-time">{formatTime(entry.elapsed_ms)}</td>
					<td className="br-taken" title={entry.damage_taken == null ? "Not recorded for this run" : undefined}>{entry.damage_taken == null ? "—" : Math.round(entry.damage_taken)}</td>
					{films && <td className="br-watch">{entry.film_id && <button type="button" className="btn btn-outline"
						disabled={loading !== null} onClick={() => watch(entry)}
						aria-label={`Watch ${entry.name}'s run`} title="Watch this run">{loading === entry.rank ? "…" : "▶"}</button>}</td>}
				</tr>)}</tbody>
			</table>}
		{films && <p className="br-board-note">Each character's five best times keep a replay anyone can watch or download.</p>}
		{canPackFilms() && <p className="br-board-note">
			<button type="button" className="btn btn-outline" onClick={() => fileInput.current?.click()}>Open a replay file</button>
			<input ref={fileInput} type="file" accept=".bossrush" hidden aria-label="Replay file" onChange={openFile} />
		</p>}
		{watchError && <p className="br-error" role="alert">{watchError}</p>}
		{watching && <Replay film={watching.film} title={watching.title} onClose={() => setWatching(null)} />}
	</section>;
}

export default function BossRush({ authUser, onExit }) {
	useNoContextMenu();
	const [run, setRun] = useState(null);
	const [starting, setStarting] = useState(false);
	const [error, setError] = useState("");
	const [sets, setSets] = useState([]);
	const [setsError, setSetsError] = useState(false);
	const [setsRetry, setSetsRetry] = useState(0);
	const [pickedCharacter, setPickedCharacter] = useState(null);
	const [boardSet, setBoardSet] = useState("");
	const [boardCharacter, setBoardCharacter] = useState("");
	const [firstBoss, setFirstBoss] = useState({});          // per set: a boss key, or "" for random

	useEffect(() => {
		const controller = new AbortController();
		setSetsError(false);
		request("/sets?lantern=true", { signal: controller.signal }).then(({ sets: list }) => {
			if (controller.signal.aborted) return;
			setSets(list);
			setBoardSet((current) => current || list.find((set) => set.playable)?.id || list[0]?.id || "");
		}).catch(() => { if (!controller.signal.aborted) setSetsError(true); });
		return () => controller.abort();
	}, [setsRetry]);

	async function openRun(character, setId) {
		const headers = { "Content-Type": "application/json" };
		if (authUser?.session_token) headers.Authorization = `Bearer ${authUser.session_token}`;
		const attempt = await request("/runs", { method: "POST", headers, body: JSON.stringify({ character, set_id: setId, starter_timer: true,
			...(firstBoss[setId] ? { first: firstBoss[setId] } : {}) }) });
		if (!attempt.starter_timer) throw new Error("Boss Rush timing is updating. Try again shortly.");
		return { ...attempt, character, setId };
	}

	async function start(setId) {
		if (!pickedCharacter || starting) return;
		const selectedSet = sets.find((set) => set.id === setId && set.playable);
		if (!selectedSet) return;
		setStarting(true);
		setError("");
		try {
			const fresh = await openRun(pickedCharacter, setId);
			setBoardSet(setId);
			setRun(fresh);
		} catch (e) {
			setError(e.message);
		} finally {
			setStarting(false);
		}
	}

	// Hold R: the same character, set and first-boss choice as a brand-new run — a
	// new boss order when that is random, and (RushRun is keyed by the run) full HP
	// and MP, a zeroed clock and an empty replay (owner's ask, 2026-11-21).
	const restart = useCallback(async () => {
		if (!run) return;
		setRun(await openRun(run.character, run.setId));
	}, [run, firstBoss, authUser]);   // eslint-disable-line react-hooks/exhaustive-deps

	const chooseCharacter = () => setRun(null);
	return <div className="bossrush" style={{ "--lby-accent": GAME.accent }}>
		<style>{styles}</style>
		{run ? <RushRun key={run.run_id} run={run} onLeave={chooseCharacter} onRestart={restart} />
			: <>
				<LobbyHeader title={GAME.name} onBack={onExit} user={<LobbyUser user={authUser} />} />
				<main className="br-menu">
					<section className="br-panel br-select">
						<h1>Choose your character</h1>
						<p>Choose a set after picking your character. Its three bosses appear in random order, unless you pick the first.</p>
						<div className="br-characters">
							{Object.entries(CHARACTERS).map(([id, character]) => <button
								key={id} type="button" className="br-character" aria-pressed={pickedCharacter === id}
								disabled={starting} onClick={() => setPickedCharacter(id)}>
								<i className={`br-glyph br-${id}`} aria-hidden="true" />
								<strong>{character.name}</strong>
								<span>{character.description}</span>
							</button>)}
						</div>
						<h2>Choose a boss set</h2>
						{setsError && <p role="status">Boss sets unavailable. <button type="button" className="btn btn-outline"
							onClick={() => setSetsRetry((n) => n + 1)}>Retry</button></p>}
						{!setsError && sets.length === 0 && <p role="status">Loading boss sets…</p>}
						<div className="br-sets">
							{sets.map((set) => <div key={set.id} className="br-set-pick">
								<button type="button" className="br-character br-set"
									disabled={!set.playable || !pickedCharacter || starting} onClick={() => start(set.id)}>
									<strong>{set.name}</strong>
									<span>{set.bosses.join(", ")}</span>
									{!set.playable && <span>Coming soon</span>}
								</button>
								{set.playable && set.keys && <label className="br-first">First boss
									<select value={firstBoss[set.id] || ""} disabled={starting}
										onChange={(e) => setFirstBoss((all) => ({ ...all, [set.id]: e.target.value }))}>
										<option value="">Random</option>
										{set.keys.map((key, i) => <option key={key} value={key}>{set.bosses[i]}</option>)}
									</select>
								</label>}
							</div>)}
						</div>
						{starting && <p role="status">Opening rift…</p>}
						{error && <p className="br-error" role="alert">{error}</p>}
						<p className="br-controls">WASD or arrows to move · Mouse to aim and fire · Space for ability · E for portal · Esc to pause · Hold R to restart</p>
					</section>
					{boardSet && <Leaderboard sets={sets} setId={boardSet} onSet={setBoardSet}
						character={boardCharacter} onCharacter={setBoardCharacter} />}
				</main>
			</>}
	</div>;
}

export const RESTART_HOLD_MS = 750;

/* The run clock ticks on its own: only this one line re-renders ten times a second,
 * not the whole run page around the fight (it used to). `clock` is the run page's
 * timer; `elapsed` there is set only when the clock stops. */
function RunClock({ clock, fixed }) {
	const [, setTick] = useState(0);
	useEffect(() => {
		const timer = setInterval(() => { if (clock.current.enteredAt !== null) setTick((n) => n + 1); }, 100);
		return () => clearInterval(timer);
	}, [clock]);
	const { elapsed, enteredAt } = clock.current;
	const ms = fixed ?? elapsed + (enteredAt === null ? 0 : Math.max(0, performance.now() - enteredAt));
	return <time aria-label="Run time">{formatTime(ms)}</time>;
}

function RushRun({ run, onLeave, onRestart }) {
	const [stage, setStage] = useState(0);
	const [status, setStatus] = useState("fight");
	const [paused, setPaused] = useState(false);
	const pause = useRef(false);
	const carriedLow = useRef(null);
	// Damage taken in the fight on screen; each clear sends its fight's share.
	const taken = useRef(0);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [elapsed, setElapsed] = useState(0);
	const clock = useRef({ elapsed: 0, enteredAt: null, active: false, pending: [], syncing: null });
	const [savedTime, setSavedTime] = useState(null);
	// The run's replay: each fight's start and its controls, tick by tick. It lives
	// only on this page — never sent, never stored — and goes when the run is left.
	const recording = useRef(null);
	if (!recording.current) recording.current = newRecording(run.character);
	const [watching, setWatching] = useState(false);
	const [filmNote, setFilmNote] = useState("");
	const dungeon = run.stages[stage];
	const final = stage === run.stages.length - 1;
	const [holdingR, setHoldingR] = useState(false);
	const [restartError, setRestartError] = useState("");
	const [restarting, setRestarting] = useState(false);
	const restartingRef = useRef(false);
	const watchingRef = useRef(false);
	watchingRef.current = watching;
	// Hold R and the Play again button both land here. Success remounts this run
	// (keyed by run id), so nothing after it runs.
	const restartNow = useCallback(async () => {
		if (restartingRef.current) return;
		restartingRef.current = true;
		setRestarting(true);
		setRestartError("");
		try { await onRestart(); }
		catch (err) { restartingRef.current = false; setRestarting(false); setHoldingR(false); setRestartError(`Couldn't restart: ${err.message}`); }
	}, [onRestart]);
	useEffect(() => {
		let timer = null;
		const cancel = () => { clearTimeout(timer); timer = null; setHoldingR(false); };
		const down = (e) => {
			if (e.code !== "KeyR" || e.repeat || e.altKey || e.ctrlKey || e.metaKey || restartingRef.current || watchingRef.current) return;
			if (e.target?.closest?.("input, textarea, select")) return;
			e.preventDefault();
			setRestartError("");
			setHoldingR(true);
			timer = setTimeout(() => { timer = null; restartNow(); }, RESTART_HOLD_MS);
		};
		const up = (e) => { if (e.code === "KeyR" && timer) cancel(); };
		const blur = () => { if (timer) cancel(); };
		window.addEventListener("keydown", down);
		window.addEventListener("keyup", up);
		window.addEventListener("blur", blur);
		return () => { clearTimeout(timer); window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); window.removeEventListener("blur", blur); };
	}, [restartNow]);
	const runPath = `/runs/${run.run_id}`;
	const syncClock = useCallback(() => {
		const timer = clock.current;
		if (!timer.syncing) {
			timer.syncing = (async () => {
				while (timer.pending.length) {
					const action = timer.pending[0];
					const path = action === "entry" ? `entries/${stage + 1}` : `clock/${stage + 1}/${action}`;
					await request(`${runPath}/${path}`, { method: "POST" });
					timer.pending.shift();
				}
			})().finally(() => { timer.syncing = null; });
		}
		return timer.syncing;
	}, [runPath, stage]);

	const stopClock = useCallback(() => {
		const timer = clock.current;
		if (timer.enteredAt !== null) timer.elapsed += performance.now() - timer.enteredAt;
		timer.enteredAt = null;
		setElapsed(timer.elapsed);
	}, []);

	const changePause = useCallback((value) => {
		if (pause.current === value) return;
		pause.current = value;
		setPaused(value);
		const timer = clock.current;
		if (!timer.active) return;
		if (value) stopClock();
		else timer.enteredAt = performance.now();
		timer.pending.push(value ? "pause" : "resume");
		syncClock().catch(() => {}); // Save retries any clock events that could not be sent.
	}, [stopClock, syncClock]);

	// End run: the fight stops where it stands and the run ends as a death would, so
	// the replay and Play again are one click away (owner's ask, 2026-11-21).
	const quit = useRef(false);
	const endRun = useCallback(() => {
		quit.current = true;
		pause.current = false;
		setPaused(false);
		clock.current.active = false;
		stopClock();
		setStatus("ended");
	}, [stopClock]);

	const save = useCallback(async () => {
		setBusy(true);
		setError("");
		try {
			await syncClock();
			const result = await request(`${runPath}/clears/${stage + 1}?taken=${Math.round(taken.current * 10) / 10}`, { method: "POST" });
			if (final) {
				setSavedTime(result.elapsed_ms);
				// A top-5 time keeps a film of the run for the leaderboard (film.js):
				// made here, from this run's controls, under the rules it was played with.
				if (result.film_wanted && canPackFilms()) {
					setFilmNote("Saving your replay to the leaderboard…");
					filmRun(recording.current).then(packFilm).then((body) => fetch(`${BACKEND_HTTP}/bossrush${runPath}/film`, {
						method: "POST", headers: { "Content-Type": "application/octet-stream" }, body,
					})).then((res) => setFilmNote(res.ok ? "Top 5 for this character: your replay is on the leaderboard."
						: "Could not save your replay to the leaderboard."))
						.catch(() => setFilmNote("Could not save your replay to the leaderboard."));
				}
			} else {
				setStage((n) => n + 1);
				setStatus("fight");
			}
		} catch (e) {
			setError(e.message);
		} finally {
			setBusy(false);
		}
	}, [runPath, stage, final, syncClock]);

	const fightEvent = useCallback((event, low) => {
		const timer = clock.current;
		if (event === "entry") {
			timer.enteredAt = performance.now();
			timer.active = true;
			timer.pending.push("entry");
			syncClock().catch(() => {});
			return;
		}
		if (event === "portal") { setStatus("portal"); return; }
		timer.active = false;
		stopClock();
		if (event === "advance") {
			carriedLow.current = low;
			setStatus("advance");
			save();
			return;
		}
		setStatus(event);
		if (event === "won") save();
	}, [save, stopClock, syncClock]);

	const over = status === "won" || status === "dead" || status === "ended";
	return <main className="br-run">
		<header className="br-run-head">
			<div><span className="br-stage">Boss {stage + 1} / {run.stages.length}</span> <strong>{dungeon.name}</strong></div>
			<RunClock clock={clock} fixed={savedTime} />
			{over ? <button type="button" className="btn btn-outline" disabled={busy} onClick={onLeave}>Main menu</button>
				: <button type="button" className="btn btn-outline" disabled={busy || paused || status === "advance"} onClick={endRun}>End run</button>}
		</header>
		<div className="br-arena">
			<Encounter key={stage} stage={stage} dungeon={dungeon} character={run.character} final={final} onEvent={fightEvent}
				carriedLow={carriedLow} taken={taken} pause={pause} changePause={changePause} recording={recording.current} quit={quit} />
			{paused && <div className="br-shade">
				<section className="br-panel br-result" role="dialog" aria-modal="true" aria-labelledby="br-pause-title">
					<h2 id="br-pause-title">Paused</h2>
					<p>The run timer is paused.</p>
					<button type="button" className="btn btn-outline" autoFocus onClick={() => changePause(false)}>Resume</button>
					<button type="button" className="btn btn-outline" onClick={endRun}>End run</button>
				</section>
			</div>}
			{(status === "advance" || over) && <div className="br-shade">
				<section className="br-panel br-result" aria-live="polite">
					<h2>{status === "won" ? "Boss Rush cleared" : status === "dead" || status === "ended" ? "Run ended" : `${dungeon.boss_name} defeated`}</h2>
					{status === "won" && <p className="br-final-time">{formatTime(savedTime ?? elapsed)}</p>}
					{busy && <p>{final ? "Posting your time…" : "Entering next rift…"}</p>}
					{savedTime !== null && <p>Time posted to the leaderboard.</p>}
					{filmNote && <p role="status">{filmNote}</p>}
					{(status === "dead" || status === "ended") && <p>You reached {dungeon.boss_name}, boss {stage + 1} of {run.stages.length}.</p>}
					{error && <p className="br-error">{error}</p>}
					{error && <button type="button" className="btn btn-outline" onClick={save}>
						{final ? "Retry posting time" : "Retry portal"}
					</button>}
					{over && <button type="button" className="btn btn-gold"
						disabled={restarting} onClick={restartNow}>{restarting ? "Opening rift…" : "Play again"}</button>}
					{over && <button type="button" className="btn btn-outline"
						disabled={restarting} onClick={() => setWatching(true)}>Watch replay</button>}
					{status === "won" && savedTime !== null && <button type="button" className="btn btn-outline" onClick={onLeave}>View leaderboard</button>}
				</section>
			</div>}
		</div>
		{holdingR && <div className="br-restart" role="status">
			<span>Restarting run</span>
			<i style={{ animationDuration: `${RESTART_HOLD_MS}ms` }} />
		</div>}
		{restartError && <p className="br-error br-restart-error" role="alert">{restartError}</p>}
		{watching && <Replay recording={recording.current} stageCount={run.stages.length} onClose={() => setWatching(false)}
			title={`${CHARACTERS[run.character]?.name} · ${status === "won" ? formatTime(savedTime ?? elapsed) : `reached boss ${stage + 1}`}`} />}
		<p className="br-run-foot" aria-live="polite">
			{status === "portal" ? "Boss defeated. Approach the blue portal and press E." : "WASD move · Click fire · Space ability · T auto-fire · Esc pause · Hold R restart"}
		</p>
	</main>;
}

function Encounter({ stage, dungeon, character, final, onEvent, carriedLow, taken, pause, changePause, recording, quit }) {
	const canvas = useRef(null);
	useEffect(() => {
		const cv = canvas.current;
		try { autoFire = localStorage.getItem(AUTO_FIRE_KEY) === "1"; } catch { /* storage may be unavailable */ }
		const ctx = cv.getContext("2d");
		const st = createSim(dungeon, CHARACTERS[character].gear, { classId: character, low: carriedLow.current });
		taken.current = 0;
		const record = startStage(recording, stage, dungeon, carriedLow.current);
		const keys = new Set();
		const edge = { ability: false, enter: false };
		const pointer = { x: 0, y: 0, fire: false };
		const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		let ended = false, raf, px, cam;
		let last = performance.now(), acc = 0;
		// Where each moving thing was before the last tick, so a frame can draw it part
		// of the way to where it is now: the game steps 60 times a second, a screen may
		// refresh 120 or 144, and without this some frames repeat a position and motion
		// steps unevenly (owner's report, 2026-11-21: live play looked rougher than the
		// replay). Halcyon Rift draws the same way.
		const prev = new Map();     // cleared each tick, so it holds only this tick's things
		let alpha = 1;
		const at = (o) => {
			const q = prev.get(o);
			return q ? { x: q[0] + (o.x - q[0]) * alpha, y: q[1] + (o.y - q[1]) * alpha } : o;
		};

		function resize() {
			const dpr = Math.min(window.devicePixelRatio || 1, 2);
			cv.width = Math.max(1, Math.round(cv.clientWidth * dpr));
			cv.height = Math.max(1, Math.round(cv.clientHeight * dpr));
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			px = Math.max(cv.clientWidth / 24, cv.clientHeight / 10);
			cam = camera(st, cv.clientWidth, cv.clientHeight, px);
		}
		const observer = new ResizeObserver(resize);
		observer.observe(cv);
		resize();

		function tick() {
			prev.clear();
			prev.set(st.p, [st.p.x, st.p.y]);
			for (const e of st.enemies) prev.set(e, [e.x, e.y]);
			for (const b of st.bullets) prev.set(b, [b.x, b.y]);
			let mx = 0, my = 0;
			for (const key of keys) { mx += DIRECTIONS[key][0]; my += DIRECTIONS[key][1]; }
			const input = {
				ability: edge.ability, enter: edge.enter, mx: Math.sign(mx), my: Math.sign(my),
				ax: (pointer.x - cam.ox) / px - st.p.x, ay: (pointer.y - cam.oy) / px - st.p.y,
				fire: pointer.fire || autoFire,
			};
			record.rows.push(recordInput(input, autoFire));
			step(st, input);
			edge.ability = edge.enter = false;
			for (const e of st.events) if (e.type === "damage") taken.current += e.amount;
			if (st.events.some((e) => e.type === "seal")) onEvent("entry");
			if (st.status === "dead") { ended = true; onEvent("dead"); }
			else if (st.status === "complete") { ended = true; onEvent("advance", st.p.low); }
			else if (st.events.some((e) => e.type === "cleared")) {
				if (final) { ended = true; record.end = fingerprint(st); st.portal = null; onEvent("won"); }
				else onEvent("portal");
			}
			if (ended && !record.end) record.end = fingerprint(st);   // the replay checks it ends the same way
		}

		function frame(now) {
			if (quit.current) ended = true;                 // End run: freeze where it stands
			acc = pause.current ? 0 : acc + Math.min(100, now - last);
			last = now;
			while (!ended && acc >= STEP_MS) { acc -= STEP_MS; tick(); }
			const width = cv.clientWidth, height = cv.clientHeight;
			alpha = ended || pause.current ? 1 : acc / STEP_MS;
			const pp = at(st.p);
			cam = camera(st, width, height, px, pp);              // the camera you see: the mouse aims in it
			// For the browser check: MP, and how far the exit is from the hero (for its walk
			// to it). Written only when they change, not on every frame.
			const resource = `${Math.floor(st.p.mp)} / ${Math.round(st.stats.maxMp)}`;
			if (resource !== cv.dataset.resource) cv.dataset.resource = resource;
			const portal = st.portal ? `${(st.portal.x - st.p.x).toFixed(2)} ${(st.portal.y - st.p.y).toFixed(2)}` : "";
			if (portal !== cv.dataset.portal) cv.dataset.portal = portal;
			draw(ctx, st, { width, height, px, calm, auto: autoFire, bossName: dungeon.boss_name, at,
				aim: { x: (pointer.x - cam.ox) / px - pp.x, y: (pointer.y - cam.oy) / px - pp.y } });
			if (!ended) raf = requestAnimationFrame(frame);
		}
		raf = requestAnimationFrame(frame);

		function keyDown(e) {
			if (ended || e.altKey || e.ctrlKey || e.metaKey) return;
			if (e.code === "Escape") {
				e.preventDefault();
				if (!e.repeat) { blur(); changePause(!pause.current); }
				return;
			}
			if (pause.current) return;
			if (DIRECTIONS[e.code]) { keys.add(e.code); e.preventDefault(); return; }
			if (e.repeat) return;
			if (e.code === "KeyQ" || e.code === "Space") { edge.ability = true; e.preventDefault(); }
			else if (e.code === "KeyE") edge.enter = true;
			else if (e.code === "KeyT") {
				autoFire = !autoFire;
				try { localStorage.setItem(AUTO_FIRE_KEY, autoFire ? "1" : "0"); } catch { /* keep the in-memory setting */ }
			}
		}
		const keyUp = (e) => keys.delete(e.code);
		const blur = () => { keys.clear(); pointer.fire = false; edge.ability = edge.enter = false; };
		const move = (e) => {
			const rect = cv.getBoundingClientRect();
			pointer.x = e.clientX - rect.left;
			pointer.y = e.clientY - rect.top;
		};
		const down = (e) => {
			if (ended || pause.current) return;
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
	}, [dungeon, character, final, onEvent, carriedLow, taken, pause, changePause]);

	return <canvas ref={canvas} tabIndex={0} role="img" aria-label={`${dungeon.name} boss arena`} />;
}
