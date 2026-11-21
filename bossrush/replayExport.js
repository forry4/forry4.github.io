/* Exporting a Boss Rush replay as a video file the player saves (owner's ask,
 * 2026-11-21). Nothing is uploaded: the frames are drawn on a canvas in this tab,
 * encoded here, and handed to the browser as a download.
 *
 * MP4 (H.264) first, through WebCodecs: frames are encoded as fast as the machine
 * draws them, so a minute of play takes seconds. `mp4-muxer` only packages the
 * encoded frames into a file, and is loaded on first export. A browser with no
 * H.264 encoder falls back to MediaRecorder, which can only record in real time. */
import { draw } from "./render.js";
import { cursor } from "./replay.js";
import { TPS } from "./sim.js";

export const EXPORT = { width: 1280, height: 720, fps: 30, bitrate: 6_000_000 };
const TICKS_PER_FRAME = TPS / EXPORT.fps;
const AVC = ["avc1.640028", "avc1.4d0028", "avc1.42e01f", "avc1.42001f"];

function frameDrawer(timeline, calm) {
	const canvas = document.createElement("canvas");
	canvas.width = EXPORT.width; canvas.height = EXPORT.height;
	const ctx = canvas.getContext("2d");
	const px = Math.max(EXPORT.width / 24, EXPORT.height / 10);   // the live page's own scale rule
	const paint = (c) => {
		const st = c.st, row = c.row;
		draw(ctx, st, { width: EXPORT.width, height: EXPORT.height, px, calm, bossName: c.stage.bossName,
			auto: !!row?.[7], aim: row ? { x: row[2], y: row[3] } : undefined });
	};
	return { canvas, paint };
}

async function pickCodec() {
	if (typeof VideoEncoder === "undefined" || typeof VideoFrame === "undefined") return null;
	for (const codec of AVC) {
		const config = { codec, width: EXPORT.width, height: EXPORT.height, bitrate: EXPORT.bitrate, framerate: EXPORT.fps };
		try { if ((await VideoEncoder.isConfigSupported(config)).supported) return config; } catch { /* try the next */ }
	}
	return null;
}

/* The stretch [from, to] (global ticks) as a video Blob. `onProgress(0..1)`;
 * `signal` aborts. Resolves { blob, ext }. */
export async function exportReplay(timeline, { from, to, calm = false, onProgress = () => {}, signal } = {}) {
	from = Math.max(0, Math.floor(from)); to = Math.min(timeline.total, Math.ceil(to));
	if (to <= from) throw new Error("Pick a longer stretch to export.");
	const frames = Math.max(1, Math.floor((to - from) / TICKS_PER_FRAME));
	const config = await pickCodec();
	return config ? exportMp4(timeline, config, from, frames, calm, onProgress, signal)
		: exportRecorded(timeline, from, frames, calm, onProgress, signal);
}

async function exportMp4(timeline, config, from, frames, calm, onProgress, signal) {
	const { Muxer, ArrayBufferTarget } = await import("mp4-muxer");
	const target = new ArrayBufferTarget();
	const muxer = new Muxer({ target, video: { codec: "avc", width: EXPORT.width, height: EXPORT.height }, fastStart: "in-memory" });
	let failure = null;
	const encoder = new VideoEncoder({
		output: (chunk, meta) => muxer.addVideoChunk(chunk, meta),
		error: (e) => { failure = e; },
	});
	encoder.configure(config);
	const { canvas, paint } = frameDrawer(timeline, calm);
	const c = cursor(timeline).seek(from);
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
		muxer.finalize();
		onProgress(1);
		return { blob: new Blob([target.buffer], { type: "video/mp4" }), ext: "mp4" };
	} finally {
		if (encoder.state !== "closed") encoder.close();
	}
}

async function exportRecorded(timeline, from, frames, calm, onProgress, signal) {
	if (typeof MediaRecorder === "undefined") throw new Error("This browser cannot make video files.");
	const type = ["video/mp4", "video/webm;codecs=vp9", "video/webm;codecs=vp8", "video/webm"].find((t) => MediaRecorder.isTypeSupported(t));
	if (!type) throw new Error("This browser cannot make video files.");
	const { canvas, paint } = frameDrawer(timeline, calm);
	const c = cursor(timeline).seek(from);
	paint(c);
	const stream = canvas.captureStream(EXPORT.fps);
	const recorder = new MediaRecorder(stream, { mimeType: type, videoBitsPerSecond: EXPORT.bitrate });
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
