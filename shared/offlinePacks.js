/* Offline packs — what the offline hub's "Download" keeps, and KEEPING it.
 *
 * A pack is the set of things one offline feature needs that the page does not
 * fetch until you use it: static files (a game's wasm, the puzzle bank, the BGG
 * data), its SCREEN CODE (the lazy chunk and its dependencies), and an optional
 * `warm` step that stores data from the backend in the browser.
 *
 * TWO GAPS THIS CLOSES, both silent:
 *  - THE SCREEN CODE WAS NEVER DOWNLOADED. The hub fetched a game's wasm, but its
 *    component is a lazy chunk the page loads only when you open the game, so an
 *    offline game worked only if that game had also been opened online once.
 *    Importing the chunk here fetches it through the service worker, whose
 *    cache-first rule for `/assets/` keeps it.
 *  - A DEPLOY THREW EVERY DOWNLOAD AWAY. sw.js names its cache after the build and
 *    deletes the previous one on activate (so a stale bundle can never be served),
 *    and this site deploys several times a day — so what you downloaded on Monday
 *    was gone by the time you were offline on Tuesday. A download is now RECORDED
 *    (pack -> build id, in localStorage), and `refreshOfflinePacks` quietly
 *    re-downloads anything recorded under an older build the next time the site
 *    opens online. Download means "keep this available", not "fetch it once".
 *
 * Mechanics only: the list of packs lives in the shell (games import shared, never
 * the other way round), passed in as specs:
 *   { key, urls: [...paths under BASE_URL], chunks: [() => import(...)], warm?: (ctx) => Promise }
 */

const KEY = "offline_packs_v1";                       // { [packKey]: buildId }
const BUILD_ID = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const BASE = (import.meta.env && import.meta.env.BASE_URL) || "/";

function readRecord() {
	try { return JSON.parse(localStorage.getItem(KEY) || "{}") || {}; } catch { return {}; }
}
function writeRecord(rec) {
	try { localStorage.setItem(KEY, JSON.stringify(rec)); } catch { /* private mode / full */ }
}

/** True when this pack was downloaded for the build that is running now. */
export function packReady(key) {
	return readRecord()[key] === BUILD_ID;
}

/** Keys of every pack this device has ever downloaded (any build). */
export function recordedPacks() {
	return Object.keys(readRecord());
}

function precacheFiles(urls, onProgress) {
	const ctrl = typeof navigator !== "undefined" && navigator.serviceWorker?.controller;
	if (!ctrl) return Promise.reject(new Error("no service worker controls this page yet"));
	if (!urls.length) return Promise.resolve();
	return new Promise((resolve, reject) => {
		const ch = new MessageChannel();
		ch.port1.onmessage = (e) => {
			const d = e.data || {};
			if (d.ok) resolve();
			else if (d.error) reject(new Error(d.error));
			else if (d.total) onProgress?.({ done: d.done, total: d.total });
		};
		onProgress?.({ done: 0, total: urls.length });
		ctrl.postMessage({ type: "PRECACHE_OFFLINE", urls: urls.map((p) => `${BASE}${p}`) }, [ch.port2]);
	});
}

/** Download one pack: files through the service worker, then its screen code,
 *  then its warm step (best effort — a warm failure does not fail the pack, the
 *  screens also save their own copies whenever they are used online). Records
 *  the pack against the running build only once the files and code are in. */
export async function downloadPack(spec, { onProgress, ctx } = {}) {
	await precacheFiles(spec.urls || [], onProgress);
	await Promise.all((spec.chunks || []).map((load) => load()));
	if (spec.warm) { try { await spec.warm(ctx || {}); } catch { /* the screen saves its own copy */ } }
	writeRecord({ ...readRecord(), [spec.key]: BUILD_ID });
}

/** Re-download every recorded pack whose build is not the running one. Quiet and
 *  sequential; call it once after the site has loaded online. A pack whose spec no
 *  longer exists is forgotten. */
export async function refreshOfflinePacks(specs, ctx) {
	if (BUILD_ID === "dev" || typeof navigator === "undefined" || !navigator.onLine) return;
	if (!navigator.serviceWorker?.controller) return;
	const rec = readRecord();
	for (const key of Object.keys(rec)) {
		const spec = specs[key];
		if (!spec) { delete rec[key]; writeRecord(rec); continue; }
		if (rec[key] === BUILD_ID) continue;
		try { await downloadPack({ ...spec, key }, { ctx }); } catch { /* try again next load */ }
	}
}
