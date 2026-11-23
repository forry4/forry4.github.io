/* Boss Rush CO-OP (owner's ask, 2026-11-22): two players, two browsers, one fight.
 *
 * `CoopRoom` is the table: the socket to bossrush/coop.py, the shared waiting room with
 * the invite link, each player's character pick and the host's boss set. Once the
 * server opens a run, `CoopRun` plays it: each browser predicts the next frames,
 * but records outcomes only once both players' inputs are known.
 *
 * Both browsers confirm each stage's outcome. The host posts entries and clears, and
 * shares the saved time with the guest. There is no pause in co-op — Esc opens the menu
 * over a fight that keeps going. */
import { useCallback, useEffect, useRef, useState } from "react";
import { BACKEND_HTTP, openSocket } from "../shared/backend.js";
import { WaitingRoom } from "../shared/lobby.jsx";
import { useAutoReconnect } from "../shared/useAutoReconnect.js";
import { CHARACTERS } from "./loadouts.js";
import { camera, draw } from "./render.js";
import { createSim, fingerprint, TPS } from "./sim.js";
import { newRecording, recordInput, startStage } from "./replay.js";
import { canPackFilms, filmRun, packFilm } from "./film.js";
import { FP_EVERY, Lockstep, hashText } from "./lockstep.js";
import { FightPrediction, stepPair } from "./prediction.js";
import Replay from "./Replay.jsx";
import { AUTO_FIRE_KEY, DIRECTIONS, RESTART_HOLD_MS, RunClock, formatTime, request } from "./common.jsx";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const BUILD_ID = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const STEP_MS = 1000 / TPS;
const PROTOCOL = 3;
const STALL_LIMIT_MS = 15000;
const PARTNER_SMOOTH_MS = 35;
const ENTER_TOGETHER = "Both players need to enter the boss room.";
const CREATE_KEY = (code) => `bossrush.coop.create.${code}`;
const TOKEN_KEY = (code) => `bossrush.coop.token.${code}`;
// A refusal that retrying cannot fix: the room is gone or full, or the seat is someone else's.
const FATAL = /closed|full|not yours|taken|expired/i;

async function postRun(path) {
	const controller = new AbortController();
	const timer = setTimeout(() => controller.abort(), STALL_LIMIT_MS);
	try {
		return await request(path, { method: "POST", signal: controller.signal });
	} catch (e) {
		if (controller.signal.aborted) throw new Error("The Boss Rush server took too long to respond.");
		throw e;
	} finally {
		clearTimeout(timer);
	}
}

const store = {
	get: (k, s = localStorage) => { try { return s.getItem(k) || ""; } catch { return ""; } },
	set: (k, v, s = localStorage) => { try { s.setItem(k, v); } catch { /* storage may be unavailable */ } },
	drop: (k, s = localStorage) => { try { s.removeItem(k); } catch { /* storage may be unavailable */ } },
};

export function newRoomCode() {
	return Array.from({ length: 6 }, () => "ABCDEFGHJKLMNPQRSTUVWXYZ"[Math.floor(Math.random() * 24)]).join("");
}
/* The menu opens a new room by marking it to be CREATED, then going to its URL. */
export function markRoomToCreate(code) { store.set(CREATE_KEY(code), "1", sessionStorage); }

export function CoopRoom({ code, authUser, sets, onLeave }) {
	const myId = String(authUser?.id || "");
	const [room, setRoom] = useState(null);
	const [seat, setSeat] = useState(null);
	const [run, setRun] = useState(null);
	const [shown, setShown] = useState(null);           // the run on screen (a finished one stays until left)
	const [connected, setConnected] = useState(false);
	const [toast, setToast] = useState("");
	const [fatal, setFatal] = useState("");
	const wsRef = useRef(null);
	const listeners = useRef(new Map());
	const net = useRef(null);
	if (!net.current) {
		net.current = {
			send: (msg) => { try { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(msg)); } catch { /* closed */ } },
			on: (type, fn) => {
				const set = listeners.current.get(type) || new Set();
				set.add(fn); listeners.current.set(type, set);
				return () => set.delete(fn);
			},
		};
	}
	const pings = useRef({ sent: new Map(), got: [] });

	const failRoom = useCallback((message) => {
		setFatal(message);
		wsRef.current?.close();
	}, []);
	const onMessage = useCallback((msg) => {
		for (const fn of listeners.current.get(msg.type) || []) fn(msg);
		if (msg.type === "room") setRoom(msg.room);
		else if (msg.type === "seat") {
			if (msg.protocol !== PROTOCOL) {
				failRoom("Co-op is updating. Try opening the room again in a moment.");
				return;
			}
			setSeat(msg.seat);
			setConnected(true);
			store.set(TOKEN_KEY(code), msg.token);
			store.drop(CREATE_KEY(code), sessionStorage);
			setToast("");
		} else if (msg.type === "run") { setRun(msg.run); setShown(msg.run.run_id); setToast(""); }
		else if (msg.type === "pong") {
			const at = pings.current.sent.get(msg.t);
			if (at != null) {
				pings.current.sent.delete(msg.t);
				pings.current.got.push(performance.now() - at);
				const { got } = pings.current;
				if (got.length === 1 || got.length === 3) {
					const sorted = [...got].sort((a, b) => a - b);
					net.current.send({ action: "rtt", ms: Math.round(sorted[Math.floor(sorted.length / 2)]) });
				}
				if (got.length === 3) pings.current.got = [];
			}
		} else if (msg.type === "closed") failRoom(msg.message || "The room closed.");
		else if (msg.type === "error") {
			if (FATAL.test(msg.message || "")) failRoom(msg.message);
			else setToast(msg.message || "Something went wrong.");
		}
	}, [code, failRoom]);
	const onMessageRef = useRef(onMessage);
	onMessageRef.current = onMessage;

	const connect = useCallback(() => {
		try { wsRef.current?.close(); } catch { /* closed */ }
		const ws = openSocket(`${WS_BASE}/bossrush/coop/${encodeURIComponent(code)}/${encodeURIComponent(myId)}`);
		wsRef.current = ws;
		ws.onopen = () => {
			if (wsRef.current !== ws) return;
			const create = store.get(CREATE_KEY(code), sessionStorage) === "1";
			ws.send(JSON.stringify({ action: create ? "create" : "join", name: authUser?.name || "Guest",
				session_token: authUser?.guest ? null : authUser?.session_token || null,
				token: store.get(TOKEN_KEY(code)) || null, build: BUILD_ID, protocol: PROTOCOL }));
		};
		ws.onmessage = (event) => {
			if (wsRef.current !== ws) return;
			let msg;
			try { msg = JSON.parse(event.data); } catch { return; }
			if (msg && typeof msg.type === "string") onMessageRef.current(msg);
		};
		ws.onclose = () => {
			if (wsRef.current !== ws) return;
			setConnected(false);
			for (const fn of listeners.current.get("disconnect") || []) fn();
		};
	}, [code, myId, authUser]);
	const socketReady = useCallback(() => wsRef.current?.readyState ?? 3, []);
	useAutoReconnect({ enabled: !fatal, connected, connect, socketReady });
	// The hook opens the first socket too (it attempts at once while not connected).
	useEffect(() => () => { const ws = wsRef.current; wsRef.current = null; try { ws?.close(); } catch { /* closed */ } }, []);

	// The server sizes the prediction window from both players' round trips.
	useEffect(() => {
		if (seat == null || !connected) return undefined;
		pings.current = { sent: new Map(), got: [] };
		const ping = () => {
			const t = performance.now(), { sent } = pings.current;
			if (sent.size >= 8) { wsRef.current?.close(); return; }
			sent.set(t, t);
			net.current.send({ action: "ping", t });
		};
		const timer = setInterval(ping, 1500);
		ping();
		return () => clearInterval(timer);
	}, [seat, connected]);

	const leave = () => { net.current.send({ action: "leave" }); store.drop(TOKEN_KEY(code)); onLeave(); };
	const start = useCallback(() => {
		setToast("");
		net.current.send({ action: "start", run_id: room?.last_run_id ?? null });
	}, [room?.last_run_id]);

	if (fatal) return <main className="br-menu"><section className="br-panel br-select">
		<h1>Co-op room {code}</h1>
		<p role="alert">{fatal}</p>
		<button type="button" className="btn btn-gold" onClick={onLeave}>Back to Boss Rush</button>
	</section></main>;

	if (run && shown === run.run_id && seat != null) {
		return <CoopRun key={run.run_id} run={run} seat={seat} net={net.current} connected={connected}
			toast={toast} onBack={() => setShown(null)} onAgain={start} />;
	}

	const seats = room?.seats || [];
	const me = seats[seat ?? -1], partner = seats[seat == null ? -1 : 1 - seat];
	const players = Object.fromEntries(seats.filter(Boolean).map((s) => [s.id, s.name]));
	const host = seats[0]?.id;
	const set = sets.find((x) => x.id === room?.set_id);
	const blocked = !partner ? null
		: !partner.online ? "Your partner is offline…"
		: !me?.character || !partner.character ? "Both players pick a character"
		: room?.same_build === false ? "Both of you refresh the page (different versions)" : null;
	return <WaitingRoom game="bossrush" roomId={code} players={players} hostId={host} myId={myId}
		min={2} max={2} connected={connected} canStart={!blocked} blockedLabel={blocked}
		onStart={start} onLeave={leave} user={authUser}
		note="Co-op: the bosses have twice the health, and every aimed attack comes at both of you.">
		<div className="br-coop-room">
			<h2>Your character</h2>
			<div className="br-characters br-coop-picks">
				{Object.entries(CHARACTERS).map(([id, character]) => <button key={id} type="button" className="br-character"
					aria-pressed={me?.character === id} disabled={!connected || !me} onClick={() => net.current.send({ action: "pick", character: id })}>
					<i className={`br-glyph br-${id}`} aria-hidden="true" />
					<strong>{character.name}</strong>
					<span>{character.description}</span>
				</button>)}
			</div>
			<p className="br-coop-partner" aria-live="polite">{partner
				? `${partner.name}: ${!partner.online ? "offline" : CHARACTERS[partner.character]?.name || "choosing…"}`
				: "Send the link to your partner."}</p>
			{seat === 0 && connected && partner && !partner.online && <button type="button" className="btn btn-outline"
				onClick={() => net.current.send({ action: "remove_offline" })}>Free offline partner’s seat</button>}
			{seat === 0 ? <div className="br-filters">
				<div>
					<label htmlFor="br-coop-set">Boss set</label>
					<select id="br-coop-set" value={room?.set_id || ""} onChange={(e) => net.current.send({ action: "set", set_id: e.target.value, first: null })}>
						{sets.filter((x) => x.playable && !x.solo_only).map((x) => <option key={x.id} value={x.id}>{x.name}</option>)}
					</select>
				</div>
				<div>
					<label htmlFor="br-coop-first">First boss</label>
					<select id="br-coop-first" value={room?.first || ""} onChange={(e) => net.current.send({ action: "set", set_id: room?.set_id, first: e.target.value || null })}>
						<option value="">Random</option>
						{(set?.keys || []).map((key, i) => <option key={key} value={key}>{set.bosses[i]}</option>)}
					</select>
				</div>
			</div> : <p>{set ? `${set.name}: ${set.bosses.join(", ")}` : ""}</p>}
			{toast && <p className="br-error" role="alert">{toast}</p>}
		</div>
	</WaitingRoom>;
}

const ENDED = { ended: "The run was ended.", left: "Your partner disconnected. You can start a new run from the room.",
	disconnect: "You lost the connection. You can start a new run once you reconnect.",
	timeout: "The connection stalled. Start a new run when both players are ready.",
	desync: "The two fights fell out of step, so the run was stopped.",
	rejoined: "A player reconnected, so the fight was stopped." };

function CoopRun({ run, seat, net, connected, toast, onBack, onAgain }) {
	const [stage, setStage] = useState(0);
	const [status, setStatus] = useState("fight");
	const [endedWhy, setEndedWhy] = useState("");
	const [menu, setMenu] = useState(false);
	const [busy, setBusy] = useState(false);
	const [error, setError] = useState("");
	const [elapsed, setElapsed] = useState(0);
	const [savedTime, setSavedTime] = useState(null);
	const [filmNote, setFilmNote] = useState("");
	const [watching, setWatching] = useState(false);
	const [news, setNews] = useState(ENTER_TOGETHER);
	const [waiting, setWaiting] = useState(true);
	const [holdingR, setHoldingR] = useState(false);
	const [saveDelayed, setSaveDelayed] = useState(false);
	const host = seat === 0;
	const carriedLow = useRef(null);
	const taken = useRef(0);
	const quit = useRef(false);
	const entry = useRef(null);
	const saving = useRef(false);
	const clock = useRef({ elapsed: 0, enteredAt: null });
	const recording = useRef(null);
	if (!recording.current) recording.current = newRecording(run.characters[0], run.characters[1], run.names);
	const dungeon = run.stages[stage];
	const final = stage === run.stages.length - 1;
	const runPath = `/runs/${run.run_id}`;
	const partnerName = run.names[1 - seat];

	const stopClock = useCallback(() => {
		const c = clock.current;
		if (c.enteredAt !== null) c.elapsed += performance.now() - c.enteredAt;
		c.enteredAt = null;
		setElapsed(c.elapsed);
	}, []);

	useEffect(() => net.on("stage", (m) => {
		if (quit.current || m.run_id !== run.run_id || m.stage !== stage + 1) return;
		entry.current = null;
		setStage(m.stage);
		setStatus("fight");
		setNews(ENTER_TOGETHER);
		setSaveDelayed(false);
		setWaiting(true);
	}), [net, run.run_id, stage]);
	const interrupted = useCallback((reason) => {
		if (quit.current) return;
		quit.current = true;
		stopClock();
		setEndedWhy(ENDED[reason]);
		setStatus((s) => (s === "won" || s === "dead" ? s : "ended"));
	}, [stopClock]);
	useEffect(() => net.on("end", (m) => {
		if (m.run_id === run.run_id && ENDED[m.reason]) interrupted(m.reason);
	}), [net, run.run_id, interrupted]);
	useEffect(() => net.on("disconnect", () => interrupted("disconnect")), [net, interrupted]);
	useEffect(() => net.on("result", (m) => {
		if (m.run_id === run.run_id) {
			setSaveDelayed(false);
			setSavedTime(m.elapsed_ms);
		}
	}), [net, run.run_id]);
	useEffect(() => net.on("save_delayed", (m) => {
		if (m.run_id === run.run_id && m.stage === stage) setSaveDelayed(true);
	}), [net, run.run_id, stage]);

	const postEntry = useCallback(() => postRun(`${runPath}/entries/${stage + 1}`), [runPath, stage]);

	const postClear = useCallback(async () => {
		if (!host || saving.current) return;
		saving.current = true;
		setBusy(true);
		setError("");
		try {
			if (!(await entry.current)) {
				await postEntry();
				entry.current = Promise.resolve(true);
			}
			if (quit.current && !final) return;
			const result = await postRun(`${runPath}/clears/${stage + 1}?taken=${Math.round(taken.current * 10) / 10}`);
			if (final) {
				setSavedTime(result.elapsed_ms);
				net.send({ action: "result", run_id: run.run_id, elapsed_ms: result.elapsed_ms });
				if (result.film_wanted && canPackFilms()) {
					setFilmNote("Saving your replay to the leaderboard…");
					filmRun(recording.current).then(packFilm).then((body) => fetch(`${BACKEND_HTTP}/bossrush${runPath}/film`, {
						method: "POST", headers: { "Content-Type": "application/octet-stream" }, body,
					})).then((res) => setFilmNote(res.ok ? "Top 5 in co-op: your replay is on the leaderboard."
						: "Could not save your replay to the leaderboard."))
						.catch(() => setFilmNote("Could not save your replay to the leaderboard."));
				}
			} else net.send({ action: "stage", run_id: run.run_id, stage: stage + 1 });
		} catch (e) {
			setError(e.message);
			net.send({ action: "save_delayed", run_id: run.run_id, stage });
		} finally {
			saving.current = false;
			setBusy(false);
		}
	}, [runPath, stage, final, host, net, run.run_id, postEntry]);

	const fightEvent = useCallback((event, detail) => {
		if (event === "entry") {
			clock.current.enteredAt = performance.now();
			setNews("");
			if (host) entry.current = postEntry().then(() => true, () => false);
			return;
		}
		if (event === "portal") { setStatus("portal"); return; }
		if (event === "down") { setNews(detail === seat ? "You are down. Your partner fights on." : `${partnerName} is down.`); return; }
		if (event === "stall") { setWaiting(detail); return; }
		if (event === "desync" || event === "timeout") {
			net.send({ action: "end", run_id: run.run_id, reason: event });
			interrupted(event);
			return;
		}
		if (event === "finishing") { stopClock(); setStatus("finishing"); return; }
		setMenu(false);
		setWaiting(false);
		if (event === "advance") {
			carriedLow.current = detail;
			setStatus("advance");
		} else {
			setStatus(event);
		}
		if (host && (event === "advance" || event === "won")) postClear();
	}, [host, seat, partnerName, net, run.run_id, stopClock, postClear, postEntry, interrupted]);

	const endRun = useCallback(() => {
		setMenu(false);
		if (quit.current) return;
		quit.current = true;
		stopClock();
		setEndedWhy(ENDED.ended);
		setStatus("ended");
		net.send({ action: "end", run_id: run.run_id, reason: "ended" });
	}, [net, run.run_id, stopClock]);

	// Hold R: a new run for both of you (either player may).
	useEffect(() => {
		let timer = null;
		const cancel = () => { clearTimeout(timer); timer = null; setHoldingR(false); };
		const down = (e) => {
			if (e.code !== "KeyR" || e.repeat || e.altKey || e.ctrlKey || e.metaKey || watching || !connected) return;
			if (e.target?.closest?.("input, textarea, select")) return;
			e.preventDefault();
			setHoldingR(true);
			timer = setTimeout(() => { timer = null; setHoldingR(false); onAgain(); }, RESTART_HOLD_MS);
		};
		const up = (e) => { if (e.code === "KeyR" && timer) cancel(); };
		window.addEventListener("keydown", down);
		window.addEventListener("keyup", up);
		window.addEventListener("blur", cancel);
		return () => { clearTimeout(timer); window.removeEventListener("keydown", down); window.removeEventListener("keyup", up); window.removeEventListener("blur", cancel); };
	}, [onAgain, watching, connected]);

	const over = status === "won" || status === "dead" || status === "ended";
	return <main className="br-run">
		<header className="br-run-head">
			<div className="br-run-info">
				<div className="br-run-boss"><span className="br-stage">Boss {stage + 1} / {run.stages.length}</span> <strong>{dungeon.boss_name}</strong>
					<span className="br-coop-tag">Co-op with {partnerName}</span></div>
				<p className="br-run-portal" aria-live="polite">
					{!connected ? "Reconnecting…" : status === "finishing" ? "Syncing the result…"
						: waiting ? `Waiting for ${partnerName}…`
						: status === "portal" ? "Boss defeated. Either player can press E at the blue portal." : news}
				</p>
			</div>
			<RunClock clock={clock} fixed={savedTime} />
			{over ? <button type="button" className="btn btn-outline" onClick={onBack}>Back to room</button>
				: <button type="button" className="btn btn-outline" onClick={endRun}>End run</button>}
		</header>
		<div className="br-arena">
			<CoopEncounter key={stage} stage={stage} dungeon={dungeon} run={run} seat={seat} final={final} net={net}
				onEvent={fightEvent} carriedLow={carriedLow} taken={taken} recording={recording.current} quit={quit}
				menu={menu} setMenu={setMenu} />
			{menu && !over && <div className="br-shade">
				<section className="br-panel br-result" role="dialog" aria-modal="true" aria-labelledby="br-menu-title">
					<h2 id="br-menu-title">Menu</h2>
					<p>The fight does not pause in co-op.</p>
					<p>WASD move · Click fire · Space ability · T auto-fire · E portal · Esc close · Hold R restart</p>
					<button type="button" className="btn btn-outline" autoFocus onClick={() => setMenu(false)}>Back to the fight</button>
					<button type="button" className="btn btn-outline" onClick={endRun}>End run</button>
				</section>
			</div>}
			{(status === "advance" || over) && <div className="br-shade">
				<section className="br-panel br-result" aria-live="polite">
					<h2>{status === "won" ? "Boss Rush cleared" : over ? "Run ended" : `${dungeon.boss_name} defeated`}</h2>
					{status === "won" && <p className="br-final-time">{formatTime(savedTime ?? elapsed)}</p>}
					{status === "advance" && !error && !saveDelayed && <p>Entering next rift…</p>}
					{status === "won" && savedTime === null && !saveDelayed && (busy || !host) && <p>{host ? "Posting your time…" : "Waiting for the host to post your time…"}</p>}
					{!host && saveDelayed && <p>The host can retry saving this clear.</p>}
					{savedTime !== null && <p>Time posted to the co-op leaderboard.</p>}
					{filmNote && <p role="status">{filmNote}</p>}
					{endedWhy && <p>{endedWhy}</p>}
					{status === "dead" && <p>You both fell to {dungeon.boss_name}, boss {stage + 1} of {run.stages.length}.</p>}
					{toast && <p className="br-error" role="alert">{toast}</p>}
					{error && (status === "advance" || status === "won") && <>
						<p className="br-error">{error}</p>
						<button type="button" className="btn btn-outline" onClick={postClear}>{final ? "Retry posting time" : "Retry portal"}</button>
					</>}
					{over && <button type="button" className="btn btn-gold" disabled={!connected} onClick={onAgain}>Play again</button>}
					{over && <button type="button" className="btn btn-outline" onClick={() => setWatching(true)}>Watch replay</button>}
				</section>
			</div>}
		</div>
		{toast && status !== "advance" && !over && <p className="br-error br-restart-error" role="alert">{toast}</p>}
		{holdingR && <div className="br-restart" role="status">
			<span>Restarting run</span>
			<i style={{ animationDuration: `${RESTART_HOLD_MS}ms` }} />
		</div>}
		{watching && <Replay recording={recording.current} stageCount={run.stages.length} onClose={() => setWatching(false)}
			title={`${run.names.join(" & ")} · ${status === "won" ? formatTime(savedTime ?? elapsed) : `reached boss ${stage + 1}`}`} />}
	</main>;
}

/* One boss of a co-op run: sample local inputs immediately and confirm them in order. */
function CoopEncounter({ stage, dungeon, run, seat, final, net, onEvent, carriedLow, taken, recording, quit, menu, setMenu }) {
	const canvas = useRef(null);
	const menuRef = useRef(menu);
	menuRef.current = menu;
	useEffect(() => {
		const cv = canvas.current;
		let autoFire = false;
		try { autoFire = localStorage.getItem(AUTO_FIRE_KEY) === "1"; } catch { /* storage may be unavailable */ }
		const ctx = cv.getContext("2d");
		const [a, b] = run.characters, low = carriedLow.current;
		const st = createSim(dungeon, CHARACTERS[a].gear, { classId: a, low: low?.[0] }, { gear: CHARACTERS[b].gear, classId: b, low: low?.[1] });
		taken.current = 0;
		const record = startStage(recording, stage, dungeon, low ? [...low] : null);
		const limit = run.prediction_window;
		const lock = new Lockstep({ seat, window: 2 * limit + 30 });
		const prediction = new FightPrediction(lock);
		const viewSeat = (state) => state.heroes[seat].p.dead && !state.heroes[1 - seat].p.dead ? 1 - seat : seat;
		let partnerBody = st.heroes[1 - seat].p;
		const partnerDraw = { x: partnerBody.x, y: partnerBody.y };
		const renderPosition = (body) => body === partnerBody ? partnerDraw : body;
		const aims = [{ x: 1, y: 0 }, { x: 1, y: 0 }];
		const keys = new Set();
		const edge = { ability: false, enter: false, fire: false };
		const pointer = { x: 0, y: 0, fire: false };
		const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		let started = false, ended = false, terminal = null, awaitingResult = false;
		let raf, px, sampled = 0, fp = null, stalledSince = null, said = false;
		let lastRepair = -Infinity;
		let last = performance.now(), acc = 0;
		const forStage = (m) => m.run_id === run.run_id && m.stage === stage;
		const send = (m) => net.send({ run_id: run.run_id, stage, ...m });
		const offInput = net.on("in", (m) => {
			if (!forStage(m) || !Array.isArray(m.rows)) return;
			lock.remote(m.from, m.rows, (tick, row) => prediction.receive(tick, row));
			if (Array.isArray(m.fp) && lock.theirPrint(m.fp[0], m.fp[1]) && !ended) { ended = true; onEvent("desync"); }
		});
		const offRepair = net.on("need_input", (m) => {
			if (!forStage(m) || quit.current) return;
			const batch = lock.resend(m.from);
			if (batch) send({ action: "in", ...batch });
		});
		const offReady = net.on("ready", (m) => {
			if (!forStage(m)) return;
			started = true;
			last = performance.now();
			acc = 0;
			stalledSince = null;
			onEvent("stall", false);
		});
		const offSettled = net.on("settled", (m) => {
			if (!forStage(m) || !awaitingResult || quit.current) return;
			awaitingResult = false;
			onEvent(m.reason, st.heroes.map((h) => h.p.low));
		});
		send({ action: "ready" });

		function resize() {
			const dpr = Math.min(window.devicePixelRatio || 1, 2);
			cv.width = Math.max(1, Math.round(cv.clientWidth * dpr));
			cv.height = Math.max(1, Math.round(cv.clientHeight * dpr));
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			px = Math.max(1, cv.clientWidth / 24, cv.clientHeight / 10);
		}
		const observer = new ResizeObserver(resize);
		observer.observe(cv);
		resize();

		function localAim(state, cam) {
			const p = state.heroes[seat].p;
			return { x: (pointer.x - cam.ox) / px - p.x, y: (pointer.y - cam.oy) / px - p.y };
		}

		function sample() {
			let mx = 0, my = 0;
			for (const key of keys) { mx += DIRECTIONS[key][0]; my += DIRECTIONS[key][1]; }
			const busy = menuRef.current;
			const view = prediction.view(st, sampled);
			const cam = camera(view, cv.clientWidth, cv.clientHeight, px, view.heroes[viewSeat(view)].p);
			const aim = localAim(view, cam);
			lock.local(sampled++, recordInput({
				ability: !busy && edge.ability, enter: !busy && edge.enter, mx: busy ? 0 : Math.sign(mx), my: busy ? 0 : Math.sign(my),
				ax: aim.x, ay: aim.y,
				fire: !busy && (pointer.fire || edge.fire || autoFire),
			}, autoFire));
			edge.ability = edge.enter = edge.fire = false;
		}

		function confirm() {
			const tick = lock.next;
			const [r0, r1] = lock.take(tick);
			prediction.confirm(tick, seat === 0 ? r1 : r0);
			record.rows.push([...r0, ...r1]);
			stepPair(st, r0, r1);
			for (const e of st.events) {
				if (e.type === "damage") taken.current += e.amount;
				else if (e.type === "down") onEvent("down", e.hero);
			}
			if (st.events.some((e) => e.type === "seal")) onEvent("entry");
			if (st.status === "dead") terminal = "dead";
			else if (st.status === "complete") terminal = "advance";
			else if (st.events.some((e) => e.type === "cleared")) {
				if (final) terminal = "won";
				else onEvent("portal");
			}
			if (terminal) {
				ended = true;
				record.end = fingerprint(st);
				if (terminal === "won") st.portal = null;
				onEvent("finishing");
				return;
			}
			if (lock.next % FP_EVERY === 0) {
				const h = hashText(fingerprint(st));
				fp = [lock.next, h];
				if (lock.ownPrint(lock.next, h) && !ended) { ended = true; onEvent("desync"); }
			}
		}

		function frame(now) {
			if (quit.current) ended = true;
			const frameMs = Math.max(0, Math.min(100, now - last));
			acc = Math.min(STEP_MS * 8, acc + frameMs);
			last = now;
			const before = lock.next;
			while (started && !ended && lock.ready(lock.next)) confirm();
			while (started && !ended && acc >= STEP_MS && sampled - lock.next < limit) {
				acc -= STEP_MS;
				sample();
			}
			while (started && !ended && lock.ready(lock.next)) confirm();
			const missingInput = started && !ended && sampled > lock.next;
			const atLimit = sampled - lock.next >= limit;
			if (!quit.current && (missingInput || !started || awaitingResult)) {
				if (lock.next !== before) stalledSince = now;
				stalledSince ??= now;
				if (missingInput && now - stalledSince > 250 && now - lastRepair > 250) {
					lastRepair = now;
					send({ action: "need_input", from: lock.next });
				}
				if (atLimit && !said && now - stalledSince > 400) { said = true; onEvent("stall", true); }
				if (!atLimit && said) { said = false; onEvent("stall", false); }
				if (now - stalledSince > STALL_LIMIT_MS) onEvent("timeout");
			} else {
				stalledSince = null;
				if (said) { said = false; onEvent("stall", false); }
			}
			const msg = lock.flush();
			if (msg && !quit.current) {
				send({ action: "in", ...msg, ...(fp ? { fp } : {}) });
				fp = null;
			}
			if (terminal && !quit.current && !lock.outbox.length) {
				awaitingResult = true;
				send({ action: "finish", reason: terminal, tick: lock.next, hash: hashText(record.end) });
				terminal = null;
			}
			const width = cv.clientWidth, height = cv.clientHeight;
			const view = ended ? st : prediction.view(st, sampled);
			const spectator = viewSeat(view);
			// Ease small position corrections for the partner only. The sim and
			// local hero still use the exact predicted positions.
			partnerBody = view.heroes[1 - seat].p;
			const dx = partnerBody.x - partnerDraw.x, dy = partnerBody.y - partnerDraw.y;
			const snap = ended || partnerBody.dead || partnerBody.dashLeft > 0 || dx * dx + dy * dy > 2.25;
			const blend = snap ? 1 : frameMs / (frameMs + PARTNER_SMOOTH_MS);
			partnerDraw.x += dx * blend;
			partnerDraw.y += dy * blend;
			const cam = camera(view, width, height, px, renderPosition(view.heroes[spectator].p));
			const p = view.heroes[seat].p;
			const resource = `${Math.floor(p.mp)} / ${Math.round(view.heroes[seat].stats.maxMp)}`;
			if (resource !== cv.dataset.resource) cv.dataset.resource = resource;
			const portal = st.portal ? `${(st.portal.x - p.x).toFixed(2)} ${(st.portal.y - p.y).toFixed(2)}` : "";
			if (portal !== cv.dataset.portal) cv.dataset.portal = portal;
			cv.dataset.tick = String(lock.next);
			const boss = view.enemies.find((e) => e.type === "boss" && e.hp > 0);   // for the browser check: where to aim
			const bossAt = boss ? `${Math.round(cam.ox + boss.x * px)} ${Math.round(cam.oy + boss.y * px)} ${(boss.x - p.x).toFixed(2)} ${(boss.y - p.y).toFixed(2)}` : "";
			if (bossAt !== cv.dataset.boss) cv.dataset.boss = bossAt;
			aims[seat] = localAim(view, cam);
			aims[1 - seat] = { x: prediction.lastRemote[2], y: prediction.lastRemote[3] };
			draw(ctx, view, { width, height, px, calm, auto: autoFire && spectator === seat, bossName: dungeon.boss_name,
				at: renderPosition, me: spectator, you: seat, names: run.names, aims });
			raf = requestAnimationFrame(frame);
		}
		raf = requestAnimationFrame(frame);

		function keyDown(e) {
			if (e.altKey || e.ctrlKey || e.metaKey) return;
			if (e.code === "Escape") { e.preventDefault(); if (!e.repeat && !ended) { blur(); setMenu(!menuRef.current); } return; }
			if (ended || menuRef.current) return;
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
		const blur = () => { keys.clear(); pointer.fire = false; edge.ability = edge.enter = edge.fire = false; };
		const move = (e) => { const rect = cv.getBoundingClientRect(); pointer.x = e.clientX - rect.left; pointer.y = e.clientY - rect.top; };
		const down = (e) => {
			if (ended || menuRef.current) return;
			move(e);
			if (e.button === 0) pointer.fire = edge.fire = true;
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
			offInput();
			offRepair();
			offReady();
			offSettled();
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
	}, [dungeon, run, seat, final, net, onEvent, carriedLow, taken, recording, quit, stage, setMenu]);

	return <canvas ref={canvas} tabIndex={0} role="img" aria-label={`${dungeon.name} boss arena`} />;
}
