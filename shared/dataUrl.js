/* Where the site's GENERATED data files come from.
 *
 * They used to be only `<site>/data/<name>` — files committed to the repo and shipped
 * in the Pages build, so refreshing one meant a commit and a full deploy. A refreshed
 * file can now live in the data store instead (data-worker/, a Workers KV namespace behind
 * a Worker), and this is the one place that knows about both:
 *
 *   1. the data store, when the build was given VITE_DATA_URL — the fresh copy;
 *   2. the copy bundled with the site — always there, and what serves OFFLINE (the
 *      service worker only handles same-origin requests, so the bundled path is also
 *      what an offline pack keeps).
 *
 * ANY failure of the first — the store unreachable, a 404 for a file never uploaded, a
 * body that is not JSON — falls through to the second, so the store can be down, or
 * never set up at all, and every page still loads what it loaded before.
 */
const REMOTE = ((import.meta.env && import.meta.env.VITE_DATA_URL) || "").replace(/\/+$/, "");
const BASE = (import.meta.env && import.meta.env.BASE_URL) || "/";

export const bundledDataUrl = (name, base = BASE) => `${base}data/${name}`;

export async function fetchData(name, { fetchImpl = fetch, remote = REMOTE, base = BASE } = {}) {
	if (remote) {
		try {
			const r = await fetchImpl(`${remote}/${name}`);
			if (r.ok) return await r.json();
		} catch { /* fall through to the bundled copy */ }
	}
	const r = await fetchImpl(bundledDataUrl(name, base));
	if (!r.ok) throw new Error(`HTTP ${r.status}`);
	return r.json();
}
