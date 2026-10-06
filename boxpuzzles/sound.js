// Box Puzzles sounds — synthesised with Web Audio, so there are no files to fetch or
// cache and every sound starts on the frame it is asked for.
//
// The AudioContext is created lazily on the first sound, which is always inside a
// click or key handler: browsers (iOS above all) only let audio start from a user
// gesture, and a context made at import time would sit suspended.
//
// Muting is a per-device preference (localStorage), read on load and written on toggle.
//
// THE iPHONE SILENT SWITCH. Safari plays Web Audio in the "ambient" session, which the
// ring/silent switch mutes — so on a phone set to silent every sound here was silently
// dropped while desktop (no switch) played them all. `navigator.audioSession` (Safari
// 17+) lets a page ask for the "playback" session instead, which plays through the
// switch the way a media app does. It is asked for only while the in-app sound is ON,
// and handed back ("auto") on mute: the in-app toggle is the control. The cost, stated
// plainly: like any media app, a playback session pauses other audio (music) on the
// phone when the first sound plays. Elsewhere the property does not exist and this is
// a no-op.

const MUTE_KEY = "boxpuzzles.muted";
let ctx = null;
let master = null;
let muted = (() => { try { return localStorage.getItem(MUTE_KEY) === "1"; } catch { return false; } })();

function session(type) {
	try {
		const as = typeof navigator !== "undefined" && navigator.audioSession;
		if (as && as.type !== type) as.type = type;
	} catch { /* not supported here */ }
}

export const isMuted = () => muted;
export function setMuted(m) {
	muted = !!m;
	try { localStorage.setItem(MUTE_KEY, muted ? "1" : "0"); } catch { /* storage unavailable */ }
	if (muted) {
		if (ctx && ctx.state === "running") ctx.suspend().catch(() => {});
		session("auto");
	}
}


// THE KIT is the owner's pick from the audition page (Box Puzzle Sound Kits artifact,
// 2026-10-05): "Felt" everywhere except the tile, which is "Brass Latch"'s two-stage
// switch click. The primitives below are that page's, ported as they were heard.
let room = null;   // a short feedback echo the felt notes send into

function audio() {
	if (muted) return null;
	session("playback");
	if (!ctx) {
		const AC = typeof window !== "undefined" && (window.AudioContext || window.webkitAudioContext);
		if (!AC) return null;
		try {
			ctx = new AC();
			// A soft clipper on the master bus, not a compressor: Chrome's compressor
			// crushed the 70ms clicks to a quarter of their level (measured), while a tanh
			// curve is transparent at normal levels and only rounds off what would clip.
			const clip = ctx.createWaveShaper();
			const curve = new Float32Array(1024);
			for (let i = 0; i < curve.length; i++) curve[i] = Math.tanh((i / (curve.length - 1)) * 2 - 1) / Math.tanh(1);
			clip.curve = curve;
			master = ctx.createGain();
			master.gain.value = 0.7;
			master.connect(clip).connect(ctx.destination);
			// The room: 110ms echo, darkened, feeding back at 0.3.
			const d = ctx.createDelay(1);
			d.delayTime.value = 0.11;
			const fb = ctx.createGain();
			fb.gain.value = 0.3;
			const wet = ctx.createGain();
			wet.gain.value = 0.32;
			const lp = ctx.createBiquadFilter();
			lp.type = "lowpass";
			lp.frequency.value = 3800;
			d.connect(lp).connect(fb).connect(d);
			lp.connect(wet).connect(master);
			room = d;
			// The classic iOS unlock: one silent sample started inside the gesture that
			// made the context, so the output path is open before the first real sound.
			const unlock = ctx.createBufferSource();
			unlock.buffer = ctx.createBuffer(1, 1, ctx.sampleRate);
			unlock.connect(ctx.destination);
			unlock.start(0);
		} catch { ctx = null; return null; }
	}
	// Suspended (never started) or "interrupted" (iOS, after a call or the phone locking):
	// resume inside this gesture, which is the only place iOS allows it.
	if (ctx.state !== "running") ctx.resume().catch(() => {});
	return ctx;
}

let noiseBuf = null;
function noise(c) {
	if (!noiseBuf) {
		noiseBuf = c.createBuffer(1, Math.floor(c.sampleRate * 0.6), c.sampleRate);
		const d = noiseBuf.getChannelData(0);
		for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
	}
	const src = c.createBufferSource();
	src.buffer = noiseBuf;
	return src;
}

// Route a voice to the master bus, and some of it into the room.
function bus(c, g, wet) {
	g.connect(master);
	if (wet) {
		const s = c.createGain();
		s.gain.value = wet;
		g.connect(s).connect(room);
	}
}

// A decaying (optionally gliding) oscillator.
function tone(c, t, { f, to = f, g, d, type = "sine", a = 0.003, wet = 0 }) {
	const o = c.createOscillator();
	o.type = type;
	o.frequency.setValueAtTime(f, t);
	if (to !== f) o.frequency.exponentialRampToValueAtTime(to, t + d);
	const e = c.createGain();
	e.gain.setValueAtTime(0.0001, t);
	e.gain.exponentialRampToValueAtTime(g, t + a);
	e.gain.exponentialRampToValueAtTime(0.0001, t + d);
	o.connect(e);
	bus(c, e, wet);
	o.start(t);
	o.stop(t + d + 0.03);
}

// A filtered noise burst: the contact of a click or a knock.
function tick(c, t, { f, q = 1.2, g, d, type = "bandpass", a = 0.001 }) {
	const s = noise(c);
	const fl = c.createBiquadFilter();
	fl.type = type;
	fl.Q.value = q;
	fl.frequency.setValueAtTime(f, t);
	const e = c.createGain();
	e.gain.setValueAtTime(0.0001, t);
	e.gain.exponentialRampToValueAtTime(g, t + a);
	e.gain.exponentialRampToValueAtTime(0.0001, t + d);
	s.connect(fl).connect(e);
	bus(c, e, 0);
	s.start(t);
	s.stop(t + d + 0.03);
}

// A marimba note: the fundamental, a fast-dying fourth-ish overtone and a soft knock.
function mallet(c, t, f, g, d = 0.5, wet = 0) {
	tone(c, t, { f, g, d, a: 0.002, wet });
	tone(c, t, { f: f * 3.95, g: g * 0.35, d: d * 0.18, a: 0.001, wet });
	tick(c, t, { f: f * 2, q: 2, g: g * 0.12, d: 0.02 });
}

const jitter = (cents) => Math.pow(2, ((Math.random() * 2 - 1) * cents) / 1200);
const note = (midi) => 440 * Math.pow(2, (midi - 69) / 12);

// Pressing a tile: a two-stage switch click — the press, its body, and the release.
export function tileSound() {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.005;
	const j = jitter(80);
	tick(c, t, { f: 4200 * j, q: 2.2, g: 1.6, d: 0.018 });
	tick(c, t + 0.002, { f: 1600 * j, q: 3, g: 0.8, d: 0.03 });
	tick(c, t + 0.045, { f: 3400 * j, q: 2.5, g: 0.55, d: 0.014 });
}

// A corner button that lights: a soft knock and a warm marimba note that climbs with
// each button lit (C D E G), so a box being closed in on sounds like it.
const LIT_NOTES = [72, 74, 76, 79];
export function litSound(litCount) {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.005;
	tick(c, t, { f: 1200, q: 0.8, g: 0.08, d: 0.03, type: "lowpass" });
	mallet(c, t + 0.01, note(LIT_NOTES[Math.max(0, Math.min(3, litCount - 1))]), 0.32, 0.6, 0.25);
}

// A corner button pressed on the wrong colour: two marimba notes falling (G to C).
export function resetSound() {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.005;
	mallet(c, t, note(67), 0.24, 0.35);
	mallet(c, t + 0.11, note(60), 0.26, 0.5);
}

// The box opening: a rolled C-major chord over a low C.
export function openSound() {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.005;
	[60, 64, 67, 72, 76].forEach((m, i) => mallet(c, t + i * 0.085, note(m), 0.26, 1.1, 0.3));
	tone(c, t + 0.4, { f: note(48), g: 0.18, d: 1.4, a: 0.04 });
}
