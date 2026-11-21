/* The Boss Rush replay player (owner's ask, 2026-11-21): the run rebuilt from its
 * recorded controls (replay.js) — or, for a leaderboard run, drawn back from its
 * film (film.js) — with a video player's controls, markers on the scrub bar, a
 * clip range, and an export to a video file (replayExport.js). */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { draw } from "./render.js";
import { FILM_FILE_EXT, fileNameOf, filmRun, filmTimeline, openCursor, packFilm } from "./film.js";
import { buildTimeline, formatClock } from "./replay.js";
import { exportPlan, exportReplay, saveBlob } from "./replayExport.js";
import { TPS } from "./sim.js";

const STEP_MS = 1000 / TPS;
const SPEEDS = [0.25, 0.5, 1, 2, 4];
const SKIP = 5 * TPS;   // the arrow keys jump five seconds

export default function Replay({ recording, film, title = "Replay", stageCount, onClose }) {
	const timeline = useMemo(() => (film ? filmTimeline(film) : buildTimeline(recording)), [recording, film]);
	const total = timeline.total;
	const c = useMemo(() => openCursor(timeline), [timeline]);
	const canvas = useRef(null);
	const shell = useRef(null);
	const track = useRef(null);
	const [pos, setPos] = useState(0);
	const [playing, setPlaying] = useState(true);
	const [speed, setSpeed] = useState(1);
	const [clip, setClip] = useState({ from: 0, to: total });
	const [exporting, setExporting] = useState(null);   // { progress, abort } while a file is made
	const [notice, setNotice] = useState("");
	const live = useRef({ playing: true, speed: 1, dirty: true, scrubbing: false });
	live.current.playing = playing;
	live.current.speed = speed;

	const seek = useCallback((at) => {
		c.seek(at);
		live.current.dirty = true;
		setPos(c.at);
	}, [c]);

	// The drawing loop: steps the cursor at the chosen speed and paints every frame.
	useEffect(() => {
		const cv = canvas.current;
		const ctx = cv.getContext("2d");
		const calm = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		let px = 1, raf, last = performance.now(), acc = 0, shown = -1;
		const resize = () => {
			const dpr = Math.min(window.devicePixelRatio || 1, 2);
			cv.width = Math.max(1, Math.round(cv.clientWidth * dpr));
			cv.height = Math.max(1, Math.round(cv.clientHeight * dpr));
			ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
			px = Math.max(cv.clientWidth / 24, cv.clientHeight / 10);
			live.current.dirty = true;
		};
		const observer = new ResizeObserver(resize);
		observer.observe(cv);
		resize();
		const frame = (now) => {
			const l = live.current;
			const dt = Math.min(100, now - last);
			last = now;
			if (l.playing && !l.scrubbing) {
				acc += dt * l.speed;
				const n = Math.floor(acc / STEP_MS);
				if (n > 0) { acc -= n * STEP_MS; c.advance(n); l.dirty = true; }
				if (c.at >= total) { setPlaying(false); acc = 0; }
			} else acc = 0;
			if (l.dirty && c.st) {
				draw(ctx, c.st, { width: cv.clientWidth, height: cv.clientHeight, px, calm, bossName: c.stage.bossName,
					auto: c.auto, aim: c.aim });
				l.dirty = false;
				if (c.at !== shown) { shown = c.at; setPos(c.at); }
			}
			raf = requestAnimationFrame(frame);
		};
		raf = requestAnimationFrame(frame);
		return () => { cancelAnimationFrame(raf); observer.disconnect(); };
	}, [c, total]);

	const togglePlay = useCallback(() => {
		if (!playing && c.at >= total) seek(0);
		setPlaying((p) => !p);
	}, [playing, c, total, seek]);
	const stepFrames = useCallback((n) => { setPlaying(false); seek(c.at + n); }, [c, seek]);
	const bosses = timeline.markers.filter((m) => m.kind === "boss");
	const jumpBoss = useCallback((dir) => {
		const at = c.at;
		const target = dir < 0
			? [...bosses].reverse().find((m) => m.at < at - TPS)          // a second in, Back restarts this fight
			: bosses.find((m) => m.at > at);
		seek(target ? target.at : dir < 0 ? 0 : total);
	}, [bosses, c, seek, total]);

	const fullscreen = useCallback(() => {
		if (document.fullscreenElement) document.exitFullscreen?.();
		else shell.current?.requestFullscreen?.().catch(() => {});
	}, []);

	useEffect(() => {
		const key = (e) => {
			if (e.altKey || e.ctrlKey || e.metaKey) return;
			const tag = e.target?.tagName;
			if (tag === "SELECT" || tag === "INPUT") return;
			const map = {
				Space: togglePlay, KeyK: togglePlay,
				ArrowLeft: () => seek(c.at - (e.shiftKey ? TPS : SKIP)), ArrowRight: () => seek(c.at + (e.shiftKey ? TPS : SKIP)),
				Comma: () => stepFrames(-1), Period: () => stepFrames(1),
				Home: () => seek(0), End: () => seek(total), KeyF: fullscreen,
				Escape: () => { if (!document.fullscreenElement && !exporting) onClose(); },
			};
			const act = map[e.code];
			if (!act) return;
			if (e.code === "Space" && tag === "BUTTON") e.target.blur();
			e.preventDefault(); e.stopPropagation();
			act();
		};
		window.addEventListener("keydown", key, true);
		return () => window.removeEventListener("keydown", key, true);
	}, [togglePlay, seek, stepFrames, fullscreen, onClose, c, total, exporting]);

	// Scrubbing: press anywhere on the bar and drag; play resumes on release.
	const atPointer = (e) => {
		const r = track.current.getBoundingClientRect();
		return Math.round(Math.max(0, Math.min(1, (e.clientX - r.left) / r.width)) * total);
	};
	const scrubDown = (e) => {
		if (e.button !== 0) return;
		e.currentTarget.setPointerCapture(e.pointerId);
		live.current.scrubbing = true;
		seek(atPointer(e));
	};
	const scrubMove = (e) => { if (live.current.scrubbing) seek(atPointer(e)); };
	const scrubUp = () => { live.current.scrubbing = false; };
	const scrubKey = (e) => {
		const map = { ArrowLeft: -TPS, ArrowRight: TPS, PageDown: -10 * TPS, PageUp: 10 * TPS };
		if (map[e.code] === undefined) return;
		e.preventDefault(); e.stopPropagation();
		seek(c.at + map[e.code]);
	};

	const stageIndex = c.stageIndex;
	const thisBoss = () => {
		const s = timeline.stages[stageIndex];
		if (s) setClip({ from: s.offset, to: s.offset + s.ticks });
	};
	const setFrom = () => setClip((k) => ({ from: Math.min(pos, k.to - TPS), to: k.to }));
	const setTo = () => setClip((k) => ({ from: k.from, to: Math.max(pos, k.from + TPS) }));
	const fullClip = clip.from === 0 && clip.to === total;
	const plan = exportPlan(clip.to - clip.from);

	// The replay as a file anyone can open again from Boss Rush's menu. A run of
	// your own is filmed first, so the file plays back under any later rules too.
	const [packing, setPacking] = useState(false);
	async function doDownload() {
		setPacking(true);
		setNotice("");
		try {
			const made = film || await filmRun(recording);
			const blob = await packFilm({ ...made, title: made.title || title });
			saveBlob(blob, `boss-rush-${fileNameOf(made.title || title)}.${FILM_FILE_EXT}`);
			setNotice(`Saved the replay file (${(blob.size / 1e6).toFixed(1)} MB). Open it from Boss Rush's menu to watch it.`);
		} catch (e) {
			setNotice(`Could not save the replay: ${e.message}`);
		} finally {
			setPacking(false);
		}
	}

	async function doExport() {
		const abort = new AbortController();
		setPlaying(false);
		setNotice("");
		setExporting({ progress: 0, abort });
		try {
			const { blob, ext } = await exportReplay(timeline, {
				from: clip.from, to: clip.to, signal: abort.signal,
				calm: window.matchMedia("(prefers-reduced-motion: reduce)").matches,
				onProgress: (progress) => setExporting((x) => x && { ...x, progress }),
			});
			const stamp = new Date().toISOString().slice(0, 16).replace(/[-:T]/g, "");
			saveBlob(blob, `boss-rush-${timeline.recording.character}-${stamp}.${ext}`);
			setNotice(`Saved ${(blob.size / 1e6).toFixed(1)} MB ${ext.toUpperCase()}.`);
		} catch (e) {
			setNotice(e.name === "AbortError" ? "Export canceled." : `Export failed: ${e.message}`);
		} finally {
			setExporting(null);
		}
	}

	const pct = (at) => `${total ? (at / total) * 100 : 0}%`;
	return <div className="br-replay" ref={shell} role="dialog" aria-modal="true" aria-label="Replay">
		<header className="br-replay-head">
			<strong>{title}</strong>
			<span className="br-replay-stage">{c.stage ? `Boss ${c.stage.index + 1} / ${stageCount ?? timeline.stages.length} · ${c.stage.name}` : ""}</span>
			<button type="button" className="btn btn-outline" onClick={onClose} disabled={!!exporting}>Close</button>
		</header>
		<div className="br-replay-view">
			<canvas ref={canvas} role="img" aria-label="Replay of the run" onClick={togglePlay} />
		</div>
		<div className="br-replay-bar">
			<div className="br-scrub" ref={track} role="slider" tabIndex={0} aria-label="Replay position"
				aria-valuemin={0} aria-valuemax={total} aria-valuenow={pos} aria-valuetext={formatClock(pos)}
				onPointerDown={scrubDown} onPointerMove={scrubMove} onPointerUp={scrubUp} onPointerCancel={scrubUp} onKeyDown={scrubKey}>
				<div className="br-scrub-rail" />
				<div className="br-scrub-fill" style={{ width: pct(pos) }} />
				{!fullClip && <div className="br-scrub-clip" style={{ left: pct(clip.from), width: pct(clip.to - clip.from) }} />}
				{timeline.markers.map((m, i) => <span key={i} className={`br-mark br-mark-${m.kind}`} style={{ left: pct(m.at) }}
					title={m.kind === "hit" ? `Hit · ${formatClock(m.at)}` : `${m.label} · ${formatClock(m.at)}`} />)}
				<div className="br-scrub-thumb" style={{ left: pct(pos) }} />
			</div>
			<div className="br-replay-controls">
				<div className="br-replay-group">
					<button type="button" className="btn btn-ghost" onClick={() => jumpBoss(-1)} aria-label="Previous boss" title="Previous boss">⏮</button>
					<button type="button" className="btn btn-ghost" onClick={() => stepFrames(-1)} aria-label="Back one frame" title="Back one frame (,)">◀︎❙</button>
					<button type="button" className="btn btn-gold br-play" onClick={togglePlay} aria-label={playing ? "Pause" : "Play"}>{playing ? "❚❚" : "▶︎"}</button>
					<button type="button" className="btn btn-ghost" onClick={() => stepFrames(1)} aria-label="Forward one frame" title="Forward one frame (.)">❙▶︎</button>
					<button type="button" className="btn btn-ghost" onClick={() => jumpBoss(1)} aria-label="Next boss" title="Next boss">⏭</button>
					<time className="br-replay-time">{formatClock(pos)} / {formatClock(total)}</time>
					<label className="br-replay-speed">Speed
						<select value={speed} onChange={(e) => setSpeed(Number(e.target.value))}>
							{SPEEDS.map((s) => <option key={s} value={s}>{s}x</option>)}
						</select>
					</label>
				</div>
				<div className="br-replay-group">
					<span className="br-replay-label">Clip {fullClip ? "· full run" : `${formatClock(clip.from)}–${formatClock(clip.to)}`}</span>
					<button type="button" className="btn btn-outline" onClick={setFrom}>Set start</button>
					<button type="button" className="btn btn-outline" onClick={setTo}>Set end</button>
					<button type="button" className="btn btn-outline" onClick={thisBoss}>This boss</button>
					{!fullClip && <button type="button" className="btn btn-outline" onClick={() => setClip({ from: 0, to: total })}>Full run</button>}
					<button type="button" className="btn btn-gold" onClick={doExport} disabled={!!exporting}>
							Export video · ~{Math.max(1, Math.round(plan.mb))} MB</button>
					<button type="button" className="btn btn-outline" onClick={doDownload} disabled={!!exporting || packing}
						title="A small file of the run you can open again from Boss Rush's menu">{packing ? "Saving…" : "Download replay"}</button>
					<button type="button" className="btn btn-ghost" onClick={fullscreen} aria-label="Full screen" title="Full screen (F)">⛶</button>
				</div>
			</div>
			{exporting && <div className="br-replay-export" role="status">
				<progress max={1} value={exporting.progress} /> Making video… {Math.round(exporting.progress * 100)}%
				<button type="button" className="btn btn-outline" onClick={() => exporting.abort.abort()}>Cancel</button>
			</div>}
			{notice && !exporting && <p className="br-replay-note" role="status">{notice}</p>}
			{!timeline.exact && <p className="br-replay-note">This replay may differ slightly from how the run went.</p>}
		</div>
	</div>;
}
