/* Where the site's GENERATED data files come from.
 *
 * They used to be only `<site>/data/<name>` — files committed to the repo and shipped
 * in the Pages build, so refreshing one meant a commit and a full deploy. A refreshed
 * file now lives in the data store instead (data-worker/, a Workers KV namespace
 * behind a Worker), and this is the one place that knows about both:
 *
 *   1. the data store, when the build was given VITE_DATA_URL — the fresh copy;
 *   2. the copy bundled with the site — always there.
 *
 * ANY failure of the first — the store unreachable, a 404 for a file never uploaded, a
 * body that is not JSON — falls through to the second, so the store can be down, or
 * never set up at all, and every page still loads what it loaded before.
 *
 * OFFLINE. The service worker only handles same-origin requests, so it can never keep
 * the store's copy itself, and once the repo stops receiving data commits the bundled
 * copy it does keep goes stale. So a successful store read is ALSO written into the
 * service worker's cache under the BUNDLED path: offline, step 2 above is answered
 * from that cache with the fresh copy. The offline hub's download calls `fetchData`
 * for each file after the service worker has precached the bundled one, so a fresh
 * download ends up holding the store's copy too.
 */
const REMOTE = ((import.meta.env && import.meta.env.VITE_DATA_URL) || "").replace(/\/+$/, "");
const BASE = (import.meta.env && import.meta.env.BASE_URL) || "/";
const BUILD_ID = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";

export const bundledDataUrl = (name, base = BASE) => `${base}data/${name}`;

/* The service worker's cache is named after the build (webapp/sw.js), and only a
 * deployed build registers one — so a dev build, or a browser without Cache Storage,
 * does nothing here. Never throws: an offline copy is a convenience. */
async function keepForOffline(name, text, base, cachesImpl) {
	if (BUILD_ID === "dev" || !cachesImpl) return;
	try {
		const cache = await cachesImpl.open(`forrest-games-${BUILD_ID}`);
		const url = new URL(bundledDataUrl(name, base), globalThis.location?.href).href;
		await cache.put(url, new Response(text, { headers: { "Content-Type": "application/json" } }));
	} catch { /* quota, private mode: the page already has its data */ }
}

export async function fetchData(name, {
	fetchImpl = fetch, remote = REMOTE, base = BASE,
	cachesImpl = typeof caches !== "undefined" ? caches : null,
} = {}) {
	if (remote) {
		try {
			const r = await fetchImpl(`${remote}/${name}`);
			if (r.ok) {
				const text = await r.text();
				const data = JSON.parse(text);
				keepForOffline(name, text, base, cachesImpl);
				return data;
			}
		} catch { /* fall through to the bundled copy */ }
	}
	const r = await fetchImpl(bundledDataUrl(name, base));
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
	return r.json();
}
