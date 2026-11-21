/* Exporting a Boss Rush replay as a video file the player saves (owner's ask,
 * 2026-11-21). Nothing is uploaded: the frames are drawn on a canvas in this tab,
 * encoded here, and handed to the browser as a download.
 *
 * MP4 (H.264) first, through WebCodecs: frames are encoded as fast as the machine
 * draws them, so a minute of play takes seconds. `mp4-muxer` only packages the
 * encoded frames into a file, and is loaded on first export. A browser with no
 * H.264 encoder falls back to MediaRecorder, which can only record in real time.
 *
 * Firefox's encoder never emits the frame stamped 0 — its first chunk is the
 * one at 1/30s, and B-frames follow out of order — and mp4-muxer refuses a first
 * chunk that is not at 0. It refused EVERY chunk, so no setup was ever stored and
 * `finalize` died on "track.info.decoderConfig is null" (owner's report,
 * 2026-11-21). Each chunk now goes in with an explicit decode time (its place in
 * the stream) and composition offset, which makes a reordered stream legal.
 * Any muxer or encoder failure, or a first chunk with no setup (`decoderConfig`,
 * the avcC), still restarts the export on the software encoder and then on
 * MediaRecorder rather than failing at the end. */
import { draw } from "./render.js";
import { openCursor } from "./film.js";
import { TPS } from "./sim.js";

/* SIZE (owner, 2026-11-21: 30s of one boss came out just over Discord's 20 MB at
 * 6 Mbps). The art is flat color, so 3 Mbps keeps it clean (measured in Firefox on
 * a fire-filled Pyre fight: 6 Mbps 21.3 MB, 3 Mbps 10.9 MB, 2.3 Mbps still clean,
 * 1.5 Mbps — even at 540p — smeared bullets and unreadable text, so the owner
 * ruled it out). A clip lowers the rate toward `floor` to land under `maxBytes`
 * (up to about a minute); a longer one stays at `floor` and goes over, and the
 * Export button says so, so the clip range can trim it. */
export const EXPORT = { width: 1280, height: 720, fps: 30, bitrate: 3_000_000, floor: 2_200_000, maxBytes: 19_000_000, discordMb: 20 };
const TICKS_PER_FRAME = TPS / EXPORT.fps;

/* The rate for `ticks` of replay, and the file it should make (MB). */
export function exportPlan(ticks) {
	const seconds = Math.max(1, ticks / TPS);
	const fit = Math.floor(EXPORT.maxBytes * 8 * 0.92 / seconds);   // 8% for the container and overshoot
	const bitrate = Math.max(EXPORT.floor, Math.min(EXPORT.bitrate, fit));
	const mb = bitrate * seconds / 8 / 1e6;
	return { width: EXPORT.width, height: EXPORT.height, bitrate, mb, overDiscord: mb * 1.06 > EXPORT.discordMb };
}
const AVC = ["avc1.640028", "avc1.4d0028", "avc1.42e01f", "avc1.42001f"];

function frameDrawer(timeline, calm, { width, height }) {
	const canvas = document.createElement("canvas");
	canvas.width = width; canvas.height = height;
	const ctx = canvas.getContext("2d");
	const px = Math.max(width / 24, height / 10);   // the live page's own scale rule
	const paint = (c) => {
		draw(ctx, c.st, { width, height, px, calm, bossName: c.stage.bossName, auto: c.auto, aim: c.aim });
	};
	return { canvas, paint };
}

async function pickCodec(plan, software = false) {
	if (typeof VideoEncoder === "undefined" || typeof VideoFrame === "undefined") return null;
	for (const codec of AVC) {
		const config = { codec, width: plan.width, height: plan.height, bitrate: plan.bitrate, framerate: EXPORT.fps,
			avc: { format: "avc" }, ...(software ? { hardwareAcceleration: "prefer-software" } : {}) };
		try { if ((await VideoEncoder.isConfigSupported(config)).supported) return config; } catch { /* try the next */ }
	}
	return null;
}

const NO_SETUP = "the encoder gave no setup";
const aborted = (e) => e?.name === "AbortError";

/* The stretch [from, to] (global ticks) as a video Blob. `onProgress(0..1)`;
 * `signal` aborts. Resolves { blob, ext }. */
export async function exportReplay(timeline, { from, to, calm = false, onProgress = () => {}, signal } = {}) {
	from = Math.max(0, Math.floor(from)); to = Math.min(timeline.total, Math.ceil(to));
	if (to <= from) throw new Error("Pick a longer stretch to export.");
	const frames = Math.max(1, Math.floor((to - from) / TICKS_PER_FRAME));
	const plan = exportPlan(to - from);
	for (const software of [false, true]) {
		const config = await pickCodec(plan, software);
		if (!config) continue;
		try { return await exportMp4(timeline, config, plan, from, frames, calm, onProgress, signal); }
		catch (e) {                                              // the next encoder, then the recorder
			if (aborted(e)) throw e;
			console.warn(`Replay export: MP4 (${software ? "software" : "default"} encoder) failed (${e?.message}), trying the next way`);
			onProgress(0);
		}
	}
	return exportRecorded(timeline, plan, from, frames, calm, onProgress, signal);
}

async function exportMp4(timeline, config, plan, from, frames, calm, onProgress, signal) {
	const { Muxer, ArrayBufferTarget } = await import("mp4-muxer");
	const target = new ArrayBufferTarget();
	const muxer = new Muxer({ target, video: { codec: "avc", width: plan.width, height: plan.height }, fastStart: "in-memory", firstTimestampBehavior: "offset" });
	let failure = null, first = true, decoded = 0;
	const encoder = new VideoEncoder({
		output: (chunk, meta) => {
			if (failure) return;
			if (first && !meta?.decoderConfig?.description) { failure = new Error(NO_SETUP); return; }
			first = false;
			// Chunks arrive in DECODE order, stamped with their display time. Firefox
			// reorders (B-frames, display times one frame late), so each chunk's decode
			// time is its place in the stream and the gap is its composition offset;
			// Chrome does not reorder and every offset comes out 0. (Rounding can put a
			// display time a microsecond before its decode time: clamp that to 0.)
			const dts = Math.round(decoded++ * 1e6 / EXPORT.fps);
			const offset = Math.max(0, chunk.timestamp - dts);
			try { muxer.addVideoChunk(chunk, meta, dts + offset, offset); } catch (e) { failure = e; }
		},
		error: (e) => { failure = e; },
	});
	encoder.configure(config);
	const { canvas, paint } = frameDrawer(timeline, calm, plan);
	const c = openCursor(timeline).seek(from);
	try {
		for (let i = 0; i < frames; i++) {
			if (signal?.aborted) throw new DOMException("Export canceled", "AbortError");
			if (failure) throw failure;
			paint(c);
			const frame = new VideoFrame(canvas, { timestamp: Math.round(i * 1e6 / EXPORT.fps), duration: Math.round(1e6 / EXPORT.fps) });
			encoder.encode(frame, { keyFrame: i % (EXPORT.fps * 2) === 0 });
			frame.close();
			c.advance(TICKS_PER_FRAME);
			// Let the encoder catch up, and the page breathe, every few frames.
			while (encoder.encodeQueueSize > 6) await new Promise((r) => setTimeout(r, 0));
			if (i % 10 === 0) { onProgress(i / frames); await new Promise((r) => setTimeout(r, 0)); }
		}
		await encoder.flush();
		if (failure) throw failure;
		if (first) throw new Error(NO_SETUP);
		muxer.finalize();
		onProgress(1);
		return { blob: new Blob([target.buffer], { type: "video/mp4" }), ext: "mp4" };
	} finally {
		if (encoder.state !== "closed") encoder.close();
	}
}

async function exportRecorded(timeline, plan, from, frames, calm, onProgress, signal) {
	if (typeof MediaRecorder === "undefined") throw new Error("This browser cannot make video files.");
	const type = ["video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t));
	if (!type) throw new Error("This browser cannot make video files.");
	const { canvas, paint } = frameDrawer(timeline, calm, plan);
	const c = openCursor(timeline).seek(from);
	paint(c);
	const stream = canvas.captureStream(EXPORT.fps);
	const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: plan.bitrate });
	const chunks = [];
	recorder.ondataavailable = (e) => { if (e.data.size) chunks.push(e.data); };
	const done = new Promise((resolve) => { recorder.onstop = resolve; });
	recorder.start(1000);
	const started = performance.now();
	try {
		for (let i = 1; i < frames; i++) {
			if (signal?.aborted) throw new DOMException("Export canceled", "AbortError");
			const due = started + i * 1000 / EXPORT.fps;   // real time: MediaRecorder stamps frames as they come
			await new Promise((r) => setTimeout(r, Math.max(0, due - performance.now())));
			c.advance(TICKS_PER_FRAME);
			paint(c);
			if (i % 10 === 0) onProgress(i / frames);
		}
	} finally {
		recorder.stop();
		stream.getTracks().forEach((t) => t.stop());
		await done;
	}
	onProgress(1);
	const ext = type.startsWith("video/mp4") ? "mp4" : "webm";
	return { blob: new Blob(chunks, { type: type.split(";")[0] }), ext };
}

export function saveBlob(blob, name) {
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url; a.download = name;
	document.body.append(a); a.click(); a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 60_000);
}
