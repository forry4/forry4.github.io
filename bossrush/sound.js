// Boss Rush sounds — synthesised with Web Audio, so there are no files to fetch and
// every sound starts on the frame it is asked for. RENDER-ONLY: nothing here reads or
// writes the fight's rules; the run pages tell `hear()` what they are drawing, and it
// compares that with the last frame it saw (sim.js stays bit-identical for co-op).
//
// THE KIT is the owner's pick from the audition page (the "Boss Rush Sounds" artifact,
// 2026-11-26): one take of each, ported from that page as heard — do not re-tune them by
// ear here. The big-attack warning was auditioned and left unpicked, and the run-start
// horn and the boss's death wail were cut after playing them (owner, 2026-11-26).
//
// As in boxpuzzles/sound.js (read its notes before changing any of this):
//   - the AudioContext is made inside a click or key press (`primeSound`), which is all
//     iOS allows; a sound asked for before that is simply not played;
//   - the iPhone audio session is "ambient", so the sounds mix over the player's music
//     or audiobook instead of pausing it (and the silent switch mutes them);
//   - the master bus is a tanh soft clipper, not a compressor;
//   - muting is per device (localStorage `bossrush.muted`).

const MUTE_KEY = "bossrush.muted";
const MASTER = 0.7;        // the audition page's volume as the owner heard it
// Every sound but the portal's plays at 60% of its auditioned level (owner, 2026-11-26).
const LEVEL = 0.6, FULL = new Set(["portalOpen", "portalEnter"]);
let level = 1;             // the level of the sound being built, set by playSound
let ctx = null, master = null, noiseBuf = null;
let muted = (() => { try { return localStorage.getItem(MUTE_KEY) === "1"; } catch { return false; } })();

export const isMuted = () => muted;
export function setMuted(m) {
	muted = !!m;
	try { localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); } catch { /* storage refused */ }
	if (muted && ctx && ctx.state === "running") ctx.suspend().catch(() => {});
	if (!muted && ctx && ctx.state !== "running") ctx.resume().catch(() => {});
}

function session(type) {
	try {
		const as = typeof navigator !== "undefined" && navigator.audioSession;
		if (as && as.type !== type) as.type = type;
	} catch { /* not supported here */ }
}

/* Make (or wake) the AudioContext. Call it from a click or key handler: that is the
 * only place iOS lets audio start. Safe to call on every press. */
export function primeSound() {
	if (muted) return null;
	session("ambient");
	if (!ctx) {
		const AC = typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext);
		if (!AC) return null;
		try {
			ctx = new AC();
			const clip = ctx.createWaveShaper();
			const curve = new Float32Array(1024);
			for (let i = 0; i < curve.length; i++) curve[i] = Math.tanh((i / (curve.length - 1)) * 2 - 1) / Math.tanh(1);
			clip.curve = curve;
			master = ctx.createGain();
			master.gain.value = MASTER;
			master.connect(clip).connect(ctx.destination);
			noiseBuf = ctx.createBuffer(1, ctx.sampleRate, ctx.sampleRate);
			const d = noiseBuf.getChannelData(0);
			let s = 1;   // a fixed seed: the same noise every time
			for (let i = 0; i < d.length; i++) { s = (s * 16807) % 2147483647; d[i] = s / 1073741823.5 - 1; }
			// The classic iOS unlock: one silent sample started inside the gesture.
			const unlock = ctx.createBufferSource();
			unlock.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
			unlock.connect(ctx.destination);
			unlock.start(0);
		} catch { ctx = null; return null; }
	}
	if (ctx.state !== "running") ctx.resume().catch(() => {});
	return ctx;
}

// The context, only once a gesture has made it: a sound from an animation frame never
// creates one (it would sit suspended on iOS and in Chrome alike).
const live = () => (muted || !ctx ? null : ctx);

/* ---- the audition page's primitives, as heard ---- */

function shape(g, t, a, peak, d) {
	g.gain.setValueAtTime(0.0001, t);
	g.gain.exponentialRampToValueAtTime(peak, t + a);
	g.gain.exponentialRampToValueAtTime(0.0001, t + a + d);
}
function tone(o) {
	const c = live(); if (!c) return;
	const t = c.currentTime + (o.at || 0);
	const a = o.a ?? 0.005, d = o.d ?? 0.12;
	const osc = c.createOscillator(), g = c.createGain();
	osc.type = o.type || "sine";
	osc.frequency.setValueAtTime(o.f0, t);
	if (o.f1 && o.f1 !== o.f0) osc.frequency.exponentialRampToValueAtTime(o.f1, t + (o.glide ?? a + d));
	if (o.vib) {
		const lfo = c.createOscillator(), lg = c.createGain();
		lfo.frequency.value = o.vib[0]; lg.gain.value = o.vib[1];
		lfo.connect(lg).connect(osc.frequency); lfo.start(t); lfo.stop(t + a + d + 0.05);
	}
	shape(g, t, a, (o.peak ?? 0.3) * level, d);
	let node = osc;
	if (o.lp) { const f = c.createBiquadFilter(); f.type = "lowpass"; f.frequency.value = o.lp; f.Q.value = o.q ?? 0.7; node = node.connect(f); }
	node.connect(g).connect(master);
	osc.start(t); osc.stop(t + a + d + 0.05);
}
function noise(o) {
	const c = live(); if (!c) return;
	const t = c.currentTime + (o.at || 0);
	const a = o.a ?? 0.003, d = o.d ?? 0.1;
	const src = c.createBufferSource(), f = c.createBiquadFilter(), g = c.createGain();
	src.buffer = noiseBuf; src.loop = true;
	f.type = o.filter || "bandpass"; f.Q.value = o.q ?? 1;
	f.frequency.setValueAtTime(o.f0 ?? 1000, t);
	if (o.f1) f.frequency.exponentialRampToValueAtTime(o.f1, t + a + d);
	shape(g, t, a, (o.peak ?? 0.3) * level, d);
	src.connect(f).connect(g).connect(master);
	src.start(t, (o.offset ?? 0) % 0.9); src.stop(t + a + d + 0.05);
}
const NOTE = (n) => 440 * 2 ** ((n - 69) / 12);

/* ---- the owner's picks ---- */

const SOUNDS = {
	// Combat
	shot: () => noise({ f0: 900, f1: 3200, q: 1.4, a: 0.01, d: 0.09, peak: 0.22 }),                              // B Whoosh
	hit: () => { tone({ f0: 190, f1: 60, d: 0.09, peak: 0.4 }); noise({ f0: 1800, q: 0.8, d: 0.02, peak: 0.12 }); }, // A Thud
	hurt: () => tone({ type: "sawtooth", f0: 320, f1: 110, d: 0.18, peak: 0.22, lp: 1400 }),                        // A Oof
	ability: () => { noise({ f0: 500, f1: 4200, q: 1.6, a: 0.04, d: 0.24, peak: 0.24 }); tone({ f0: 440, f1: 880, a: 0.02, d: 0.22, peak: 0.08 }); }, // B Swoosh up
	// Boss beats
	phase: () => [45, 52, 57].forEach((n) => tone({ type: "sawtooth", f0: NOTE(n), a: 0.01, d: 0.6, peak: 0.12, lp: 1800 })), // B Power chord
	portalOpen: () => { tone({ f0: 220, a: 0.4, d: 0.8, peak: 0.16, vib: [5, 3] }); tone({ f0: 330, a: 0.5, d: 0.7, peak: 0.09, vib: [5.5, 4] }); }, // A Hum swell
	portalEnter: () => tone({ f0: 200, f1: 1600, a: 0.02, d: 0.42, peak: 0.2, vib: [14, 40] }),                      // A Warp
	// Run beats
	runEnd: () => [64, 62, 60, 57].forEach((n, i) => tone({ type: "triangle", f0: NOTE(n), at: i * 0.22, a: 0.01, d: i === 3 ? 0.9 : 0.25, peak: 0.16 })), // A Sad descent
	setClear: () => { [60, 64, 67].forEach((n, i) => tone({ type: "square", f0: NOTE(n), at: i * 0.12, a: 0.005, d: 0.11, peak: 0.07, lp: 3000 })); [60, 64, 67, 72].forEach((n) => tone({ type: "square", f0: NOTE(n), at: 0.36, a: 0.005, d: 0.9, peak: 0.05, lp: 3000 })); }, // A Fanfare
	// Menu
	select: () => tone({ f0: 1250, d: 0.025, peak: 0.12 }),                                                          // A Tick
	start: () => { tone({ f0: 660, d: 0.07, peak: 0.16 }); tone({ f0: 990, at: 0.07, d: 0.16, peak: 0.16 }); },      // A Confirm
};

/* Play one sound by name. Menu sounds are asked for inside their click, so they prime. */
export function playSound(name, { gesture = false } = {}) {
	if (muted) return;
	if (gesture) primeSound();
	level = FULL.has(name) ? 1 : LEVEL;
	try { SOUNDS[name]?.(); } catch { /* a sound must never break the page */ }
}

/* ---- hearing a fight: what changed since the last frame drawn ---- */

/* One per FIGHT (each Encounter makes its own). `hear(st, hero)` is called once per
 * drawn frame with the state being drawn and the hero this page plays (`st` solo; in
 * co-op its own entry of `heroes`, whose fields are the same). The first frame only
 * takes its measure. Nothing is compared by object: co-op draws a predicted copy that
 * can be rebuilt between frames, and only the values carry over. */
export function createHearing() {
	let last = null;
	return function hear(st, hero = st) {
		const p = hero.p;
		const bosses = new Map();
		for (const e of st.enemies) if (e.type === "boss") bosses.set(e.id, e.phase);
		let foe = 0;
		for (const n of st.damageNumbers || []) if (n.foe && n.until > foe) foe = n.until;
		const now = { fireCd: p.fireCd || 0, abilityCd: p.abilityCd || 0, hurt: p.hurt || 0, foe, bosses, portal: !!st.portal, dead: !!p.dead };
		if (last && !muted) {
			if (!now.dead) {
				if (now.fireCd > last.fireCd) playSound("shot");
				if (now.abilityCd > last.abilityCd) playSound("ability");
				if (now.hurt > last.hurt) playSound("hurt");
			}
			if (now.foe > last.foe) playSound("hit");
			for (const [id, phase] of last.bosses) if (phase === 1 && bosses.get(id) === 2) playSound("phase");
			if (now.portal && !last.portal) playSound("portalOpen");
		}
		last = now;
	};
}
