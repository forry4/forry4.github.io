// Screenshot pipeline: downscale + re-encode in the browser, upload as base64, and
// load back through an authenticated fetch.
//
// Why re-encode at all: a 4K screenshot is 8-15MB as PNG, and every image lives in
// the database (Render's disk is wiped on deploy). Capped to a 1920px long edge and
// encoded as WebP (JPEG where the browser cannot encode WebP — Safari hands back a
// PNG instead of failing, so the TYPE of the result is what is checked) a screenshot
// lands around 150-300KB and stays sharp enough to read in-game text.

export const MAX_EDGE = 1920;
const QUALITY = 0.82;
const MAX_UPLOAD = 3_000_000;   // matches notes/api.py _IMAGE_BYTES

function toBlob(canvas, type, quality) {
	return new Promise((resolve) => canvas.toBlob(resolve, type, quality));
}

export async function compressImage(file) {
	// imageOrientation honours a phone photo's EXIF rotation.
	const bmp = await createImageBitmap(file, { imageOrientation: "from-image" });
	const scale = Math.min(1, MAX_EDGE / Math.max(bmp.width, bmp.height));
	const width = Math.max(1, Math.round(bmp.width * scale));
	const height = Math.max(1, Math.round(bmp.height * scale));
	const canvas = document.createElement("canvas");
	canvas.width = width;
	canvas.height = height;
	canvas.getContext("2d").drawImage(bmp, 0, 0, width, height);
	bmp.close?.();
	let blob = await toBlob(canvas, "image/webp", QUALITY);
	if (!blob || blob.type !== "image/webp") blob = await toBlob(canvas, "image/jpeg", QUALITY);
	if (!blob) throw new Error("could not encode the image");
	if (blob.size > MAX_UPLOAD) blob = await toBlob(canvas, "image/jpeg", 0.6);
	if (!blob || blob.size > MAX_UPLOAD) throw new Error("image is too large");
	return { blob, mime: blob.type, width, height };
}

export function blobToBase64(blob) {
	return new Promise((resolve, reject) => {
		const r = new FileReader();
		r.onload = () => resolve(String(r.result).split(",", 2)[1] || "");
		r.onerror = () => reject(r.error);
		r.readAsDataURL(blob);
	});
}

export function imageFilesFrom(dataTransfer) {
	if (!dataTransfer) return [];
	return Array.from(dataTransfer.files || []).filter((f) => f.type.startsWith("image/"));
}

// ── uploads in flight ─────────────────────────────────────────────────────────
// An image node is inserted the moment a file arrives, carrying an `uploadKey`
// and no `imageId`; its view looks the key up here to show a local preview while
// the upload runs. A node whose key is NOT here and that has no id is a failed or
// abandoned upload (the save path drops those — see stripPending).
export const pendingUploads = new Map();   // uploadKey -> { previewUrl }

export const newUploadKey = () => "up_" + Math.random().toString(36).slice(2, 11);

// ── authenticated image cache ────────────────────────────────────────────────
// id -> Promise<objectURL>. An image id never changes content, so one fetch per
// session is enough; the server also marks it private+immutable for the HTTP cache.
const urlCache = new Map();

export function imageUrl(api, id) {
	if (!urlCache.has(id)) {
		const p = api.imageBlob(id).then((b) => URL.createObjectURL(b));
		p.catch(() => urlCache.delete(id));   // let a later render retry
		urlCache.set(id, p);
	}
	return urlCache.get(id);
}

// Seed the cache with the blob we just uploaded, so the new image never re-downloads.
export function primeImage(id, blob) {
	urlCache.set(id, Promise.resolve(URL.createObjectURL(blob)));
}
