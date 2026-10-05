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
		noiseBuf = c.createBuffer(1, Math.floor(c.sampleRate * 0.25), c.sampleRate);
		const d = noiseBuf.getChannelData(0);
		for (let i = 0; i < d.length; i++) d[i] = Math.random() * 2 - 1;
	}
	const src = c.createBufferSource();
	src.buffer = noiseBuf;
	return src;
}

// A filtered noise transient: the "contact" part of any click.
function tick(c, t, { freq, q = 1.2, gain, dur, type = "bandpass" }) {
	const src = noise(c);
	const f = c.createBiquadFilter();
	f.type = type;
	f.frequency.value = freq;
	f.Q.value = q;
	const g = c.createGain();
	g.gain.setValueAtTime(gain, t);
	g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
	src.connect(f).connect(g).connect(master);
	src.start(t);
	src.stop(t + dur + 0.02);
}

// A decaying sine, optionally gliding: the "body" of a thock or a thunk.
function tone(c, t, { freq, to = freq, gain, dur, type = "sine", attack = 0.003 }) {
	const o = c.createOscillator();
	o.type = type;
	o.frequency.setValueAtTime(freq, t);
	if (to !== freq) o.frequency.exponentialRampToValueAtTime(to, t + dur);
	const g = c.createGain();
	g.gain.setValueAtTime(0.0001, t);
	g.gain.exponentialRampToValueAtTime(gain, t + attack);
	g.gain.exponentialRampToValueAtTime(0.0001, t + dur);
	o.connect(g).connect(master);
	o.start(t);
	o.stop(t + dur + 0.02);
}

// A small bell: a few inharmonic partials, the higher ones dying first.
function bell(c, t, freq, gain, dur = 0.9) {
	[[1, 1, 1], [2.01, 0.42, 0.6], [3.98, 0.18, 0.35], [5.43, 0.08, 0.22]].forEach(([ratio, g, d]) =>
		tone(c, t, { freq: freq * ratio, gain: gain * g, dur: dur * d, attack: 0.002 }));
}

const jitter = (cents) => Math.pow(2, ((Math.random() * 2 - 1) * cents) / 1200);

// Pressing a tile: a soft, woody thock.
export function tileSound() {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.001;
	const j = jitter(60);
	tone(c, t, { freq: 260 * j, to: 150 * j, gain: 0.3, dur: 0.09 });
	tick(c, t, { freq: 2300 * j, q: 1.4, gain: 0.13, dur: 0.035 });
	tick(c, t + 0.004, { freq: 700 * j, q: 2.5, gain: 0.07, dur: 0.05 });
}

// A corner button that lights: a crisp latch click and a bell that climbs with each
// button lit (1st..4th), so a box being closed in on sounds like it.
const LIT_NOTES = [659.25, 783.99, 987.77, 1174.66];   // E5 G5 B5 D6
export function litSound(litCount) {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.001;
	tick(c, t, { freq: 3800, q: 0.9, gain: 0.28, dur: 0.025, type: "highpass" });
	tone(c, t, { freq: 420, to: 300, gain: 0.25, dur: 0.05 });
	bell(c, t + 0.012, LIT_NOTES[Math.max(0, Math.min(3, litCount - 1))], 0.27, 0.8);
}

// A corner button pressed on the wrong colour: a dull click and the box falling back.
export function resetSound() {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.001;
	tick(c, t, { freq: 1500, q: 1, gain: 0.25, dur: 0.04 });
	tone(c, t, { freq: 210, to: 70, gain: 0.38, dur: 0.22, type: "triangle" });
	tick(c, t + 0.06, { freq: 500, q: 0.8, gain: 0.12, dur: 0.16, type: "lowpass" });
}

// The box opening: the last latch, a deep wooden release, then a bright chime.
const OPEN_CHORD = [783.99, 987.77, 1174.66, 1567.98];   // G5 B5 D6 G6
export function openSound() {
	const c = audio();
	if (!c) return;
	const t = c.currentTime + 0.001;
	tick(c, t, { freq: 3800, q: 0.9, gain: 0.3, dur: 0.025, type: "highpass" });
	tone(c, t + 0.02, { freq: 140, to: 90, gain: 0.55, dur: 0.25 });
	tick(c, t + 0.02, { freq: 900, q: 1.5, gain: 0.18, dur: 0.12 });
	OPEN_CHORD.forEach((f, i) => bell(c, t + 0.09 + i * 0.075, f, 0.21, 1.6));
}
