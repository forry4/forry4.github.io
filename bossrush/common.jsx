/* What the solo run page (BossRush.jsx) and the co-op one (Coop.jsx) share. */
import { useEffect, useState } from "react";
import { BACKEND_HTTP, markBackendAwake } from "../shared/backend.js";

export const AUTO_FIRE_KEY = "bossrush.autoFire";
export const RESTART_HOLD_MS = 750;
export const DIRECTIONS = {
	KeyA: [-1, 0], ArrowLeft: [-1, 0], KeyD: [1, 0], ArrowRight: [1, 0],
	KeyW: [0, -1], ArrowUp: [0, -1], KeyS: [0, 1], ArrowDown: [0, 1],
};

export async function request(path, options) {
	const res = await fetch(`${BACKEND_HTTP}/bossrush${path}`, options);
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
