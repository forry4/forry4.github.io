/* What the solo run page (BossRush.jsx) and the co-op one (Coop.jsx) share. */
import { useEffect, useState } from "react";
import { BACKEND_HTTP, markBackendAwake } from "../shared/backend.js";
import { bossArtUrl, heroArtUrl } from "./bossSprites.js";
import { isMuted, playSound, setMuted } from "./sound.js";

export const AUTO_FIRE_KEY = "bossrush.autoFire";
export const RESTART_HOLD_MS = 750;
export const DIRECTIONS = {
	KeyA: [-1, 0], ArrowLeft: [-1, 0], KeyD: [1, 0], ArrowRight: [1, 0],
	KeyW: [0, -1], ArrowUp: [0, -1], KeyS: [0, 1], ArrowDown: [0, 1],
};

export function movementOf(keys, touch, analog = true) {
	const { mx, my } = touch;
	if (mx || my) {
		if (analog) return [mx, my];
		// Older co-op servers only relay the eight keyboard directions.
		const octant = Math.round(Math.atan2(my, mx) / (Math.PI / 4));
		return [Math.round(Math.cos(octant * Math.PI / 4)) || 0, Math.round(Math.sin(octant * Math.PI / 4)) || 0];
	}
	let x = 0, y = 0;
	for (const key of keys) { x += DIRECTIONS[key][0]; y += DIRECTIONS[key][1]; }
	return [Math.sign(x), Math.sign(y)];
}

/* Every Boss Rush call is safe to send twice (the run's writes are conditional, and a
 * second start only opens a run nobody plays), so a dropped connection or a gateway
 * hiccup is retried a few times before the player sees anything. The browser reports
 * a dropped connection only as "Failed to fetch" (owner, 2026-11-26), which says
 * nothing a player can use. */
const RETRY_MS = [400, 1200, 3000];
export async function request(path, options) {
	let res;
	for (let attempt = 0; ; attempt++) {
		try {
			res = await fetch(`${BACKEND_HTTP}/bossrush${path}`, options);
			if (![502, 503, 504].includes(res.status) || attempt >= RETRY_MS.length) break;
		} catch (err) {
			if (options?.signal?.aborted) throw err;
			if (attempt >= RETRY_MS.length) throw new Error("Could not reach the Boss Rush server. Check your connection and try again.");
		}
		await new Promise((resolve) => setTimeout(resolve, RETRY_MS[attempt]));
		if (options?.signal?.aborted) throw new DOMException("Aborted", "AbortError");
	}
	if (res.ok) {
		markBackendAwake();
		return res.json();
	}
	const error = await res.json().catch(() => null);
	throw new Error(typeof error?.detail === "string" ? error.detail : "Could not reach the Boss Rush server.");
}

export function formatTime(ms) {
	const minutes = Math.floor(ms / 60_000);
	const seconds = (Math.floor(ms) % 60_000 / 1000).toFixed(3).padStart(6, "0");
	return `${minutes}:${seconds}`;
}

/* The run clock ticks on its own: only this one line re-renders ten times a second,
 * not the whole run page around the fight (it used to). `clock` is the run page's
 * timer; `elapsed` there is set only when the clock stops. */
export function RunClock({ clock, fixed }) {
	const [, setTick] = useState(0);
	useEffect(() => {
		const timer = setInterval(() => { if (clock.current.enteredAt !== null) setTick((n) => n + 1); }, 100);
		return () => clearInterval(timer);
	}, [clock]);
	const { elapsed, enteredAt } = clock.current;
	const ms = fixed ?? elapsed + (enteredAt === null ? 0 : Math.max(0, performance.now() - enteredAt));
	return <time aria-label="Run time">{formatTime(ms)}</time>;
}

/* A class's hero sprite as the menus show it: the picker cards and the boards' phone
 * column. The 12 px art drawn unsmoothed, at a whole multiple, like the fight. */
/* The controls as key caps: `keys` is [[cap or [caps], what it does], …]; several caps
 * are alternatives ("Space / Right click"). The page hides the list that does not apply
 * to the device (br-keyboard-only / br-touch-only). */
export function KeyHints({ keys, className = "" }) {
	return <ul className={`br-keys ${className}`.trim()}>
		{keys.map(([caps, does]) => <li key={does}>
			{[caps].flat().map((cap, i) => <span key={cap}>{i > 0 && <span className="br-key-or">/</span>}<kbd className="br-key">{cap}</kbd></span>)}
			{" "}{does}
		</li>)}
	</ul>;
}

/* The run so far as its bosses' portraits: the ones beaten, the one the run stopped at
 * (`fell`), and the ones it never reached. Decoration: the panel's words say the same. */
export function RunTrail({ stages, reached, won = false, fell = false }) {
	return <ol className="br-trail" aria-hidden="true">
		{stages.map((d, i) => {
			const state = won || i < reached ? "beaten" : i === reached ? (fell ? "fell" : "here") : "ahead";
			const art = bossArtUrl(d.id);
			return <li key={i} data-state={state} title={d.boss_name}>
				{art ? <img src={art} alt="" draggable={false} /> : <span>{d.boss_name.replace(/^The /, "")[0]}</span>}
			</li>;
		})}
	</ol>;
}

export function HeroGlyph({ id }) {
	return <img className={`br-glyph br-${id}`} src={heroArtUrl(id)} alt="" aria-hidden="true" draggable={false} />;
}

/* The sound toggle, in the run header and beside Start run: a speaker with waves or a
 * cross, remembered per device (sound.js). Box Puzzles draws the same speaker. */
export function MuteToggle() {
	const [muted, setM] = useState(isMuted);
	return <button type="button" className="btn btn-outline br-mute" aria-pressed={muted}
		aria-label={muted ? "Turn sound on" : "Turn sound off"} title={muted ? "Sound off" : "Sound on"}
		onClick={() => { setMuted(!muted); setM(!muted); if (muted) playSound("select", { gesture: true }); }}>
		<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" aria-hidden="true">
			<path d="M4.5 9.5h3.2L12 5.8v12.4l-4.3-3.7H4.5Z" />
			{muted ? <path d="M15.6 9.6l4.8 4.8M20.4 9.6l-4.8 4.8" /> : <path d="M15.4 9.2a4 4 0 0 1 0 5.6M17.9 6.8a7.4 7.4 0 0 1 0 10.4" />}
		</svg>
	</button>;
}
