import { useEffect, useRef, useState } from "react";
import { REACH } from "./sim.js";

// These are the same inputs sampled for keyboard and mouse. A short tap is
// queued until the next tick so it works even when co-op is waiting on a peer.
export function useArenaTouch() {
	const [input] = useState(() => ({
		active: false, mx: 0, my: 0, ax: 1, ay: 0, fire: false, fireQueued: false,
		ability: false, enter: false, portal: null,
	}));
	return input;
}

export function clearTouchActions(input) {
	input.fireQueued = input.ability = input.enter = false;
}

export function updateTouchPortal(input, portal, p) {
	if (!input.portal) return;
	const hidden = !portal || p.dead || (portal.x - p.x) ** 2 + (portal.y - p.y) ** 2 > REACH ** 2;
	if (input.portal.hidden !== hidden) input.portal.hidden = hidden;
}

// A tap on the playfield should not generate a mouse shot.
export function suppressTouchMouse(e) {
	if (e.pointerType === "touch") e.preventDefault();
}

function Stick({ input, aim, disabled }) {
	const pad = useRef(null), pointer = useRef(null);
	useEffect(() => {
		const reset = () => {
			pointer.current = null;
			pad.current?.style.removeProperty("--stick-x");
			pad.current?.style.removeProperty("--stick-y");
			if (aim) input.fire = input.fireQueued = false;
			else input.mx = input.my = 0;
		};
		if (disabled) reset();
		window.addEventListener("blur", reset);
		return () => { window.removeEventListener("blur", reset); reset(); };
	}, [input, aim, disabled]);

	function move(e) {
		if (pointer.current !== e.pointerId || disabled) return;
		const box = e.currentTarget.getBoundingClientRect();
		const dx = e.clientX - box.left - box.width / 2;
		const dy = e.clientY - box.top - box.height / 2;
		const length = Math.hypot(dx, dy), radius = box.width * 0.29;
		const active = length >= radius * 0.28;
		const scale = active ? Math.min(1, radius / length) : 0;
		const style = e.currentTarget.style;
		style.setProperty("--stick-x", `${dx * scale}px`);
		style.setProperty("--stick-y", `${dy * scale}px`);
		if (aim) {
			if (active) {
				input.ax = dx / length;
				input.ay = dy / length;
				if (!input.fire) input.fireQueued = true;
			}
			input.fire = active;
		} else if (active) {
			// Lockstep rows use the same eight directions as WASD.
			const octant = Math.round(Math.atan2(dy, dx) / (Math.PI / 4));
			input.mx = Math.round(Math.cos(octant * Math.PI / 4)) || 0;
			input.my = Math.round(Math.sin(octant * Math.PI / 4)) || 0;
		} else input.mx = input.my = 0;
	}

	function release(e) {
		if (pointer.current !== e.pointerId) return;
		pointer.current = null;
		e.currentTarget.style.removeProperty("--stick-x");
		e.currentTarget.style.removeProperty("--stick-y");
		if (aim) {
			input.fire = false;
			if (e.type !== "pointerup") input.fireQueued = false;
		} else input.mx = input.my = 0;
	}

	return <div ref={pad} className="br-touch-stick" role="group" aria-label={aim ? "Aim and fire joystick" : "Move joystick"}
		onPointerDown={(e) => {
			if (disabled || e.button !== 0 || pointer.current !== null) return;
			e.preventDefault();
			input.active = true;
			pointer.current = e.pointerId;
			e.currentTarget.setPointerCapture(e.pointerId);
			move(e);
		}} onPointerMove={move} onPointerUp={release} onPointerCancel={release} onLostPointerCapture={release}>
		<span className="br-touch-thumb" aria-hidden="true" />
		<span className="br-touch-label" aria-hidden="true">{aim ? "Aim & fire" : "Move"}</span>
	</div>;
}

export default function ArenaTouch({ input, disabled, menuLabel, onMenu }) {
	useEffect(() => {
		const clear = () => clearTouchActions(input);
		if (disabled) clear();
		window.addEventListener("blur", clear);
		return () => window.removeEventListener("blur", clear);
	}, [input, disabled]);
	const action = (key) => ({
		onPointerDown(e) {
			if (disabled || e.button !== 0) return;
			e.preventDefault();
			input.active = input[key] = true;
		},
		onClick(e) {
			if (!disabled && e.detail === 0) input.active = input[key] = true;
		},
	});
	return <div className="br-touch" aria-label="Touch controls">
		<Stick input={input} disabled={disabled} />
		<div className="br-touch-actions">
			<button type="button" className="btn btn-outline" disabled={disabled} onClick={onMenu}>{menuLabel}</button>
			<button type="button" className="btn btn-gold" disabled={disabled} {...action("ability")}>Ability</button>
			<button type="button" className="btn btn-outline br-touch-portal" disabled={disabled}
				ref={(button) => { input.portal = button; }} hidden {...action("enter")}>Enter portal</button>
		</div>
		<Stick input={input} aim disabled={disabled} />
	</div>;
}
