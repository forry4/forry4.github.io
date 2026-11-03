// Anime Filter's logic, kept out of the component so webapp/test/unit/animefilter.test.mjs
// can hold it without a DOM. The payload is animefilter/tools/make_data.py's.

export const SITES = [
	{ k: "m", label: "MyAnimeList", short: "MAL" },
	{ k: "a", label: "AniList", short: "AniList" },
	{ k: "k", label: "Kitsu", short: "Kitsu" },
];
export const ALL_SITES = SITES.map((s) => s.k);

// The combined score: each site's score as a z-score over the shows that site rates
// (`scale[site] = [mean, sd]`, from make_data.py), the z-scores present averaged, and
// the result put back on MAL's scale. A site switched off simply drops out of the
// average; a row no chosen site rates scores null and sorts last.
export function combined(row, scale, use = ALL_SITES) {
	let z = 0, n = 0;
	for (const s of use) {
		const v = row[s];
		if (v == null || !scale[s]) continue;
		z += (v - scale[s][0]) / scale[s][1];
		n++;
	}
	if (!n) return null;
	return scale.m[0] + (z / n) * scale.m[1];
}

// "Each season" view: one row per season or film of every listed show, carrying its
// show's descriptive fields (genres, tags, demographic) so the same filters apply.
export function seasonRows(shows) {
	const out = [];
	for (const s of shows) {
		for (const p of s.p) {
			out.push({ ...p, key: `p${p.id}`, show: s, n: p.n, r: null, g: s.g, t: s.t, dm: s.dm, c: s.c,
				dub: p.d, mv: s.mv, seasons: 1 });
		}
	}
	return out;
}

export function showRows(shows) {
	return shows.map((s) => ({ ...s, key: `s${s.id}`, show: s, seasons: s.p.length,
		e: s.p.reduce((t, p) => t + (p.e || 0), 0) || null }));
}

export function rescore(rows, scale, use) {
	for (const r of rows) r.s = combined(r, scale, use);
	return rows;
}

// Dub filter: "any", "some" (at least one season has an English dub), "full" (every
// season does — a dub still airing counts as some, not full).
export const DUB = [["any", "Any"], ["some", "Has a dub"], ["full", "Fully dubbed"]];
export const FORMAT = [["any", "Any"], ["series", "Series"], ["movie", "Movies"]];

export function passes(r, d) {
	if (d.yfrom && (!r.y || r.y < d.yfrom)) return false;
	if (d.yto && (!r.y || r.y > d.yto)) return false;
	if (d.dub === "some" && !(r.dub >= 1)) return false;
	if (d.dub === "full" && r.dub !== 2) return false;
	if (d.fmt === "series" && r.f === "Movie") return false;
	if (d.fmt === "movie" && r.f !== "Movie") return false;
	if (d.demo && d.demo !== "any" && r.dm !== d.demo) return false;
	if (d.jp && r.c !== "JP") return false;
	if (d.members && !(r.mv >= d.members)) return false;
	for (const g of d.genres || []) if (!r.g.includes(g)) return false;
	for (const t of d.tags || []) if (!r.t.includes(t)) return false;
	return true;
}

export function matches(r, needle) {
	if (!needle) return true;
	const hay = [r.n, r.r, r.show && r.show.n, ...(r.p ? r.p.map((p) => p.n) : [])];
	return hay.some((h) => h && h.toLowerCase().includes(needle));
}

// Sort comparator: a missing value sorts last whichever way the column runs.
export function sorter(key, dir) {
	return (a, b) => {
		const x = a[key], y = b[key];
		if ((x == null) !== (y == null)) return x == null ? 1 : -1;
		const c = x == null ? 0 : typeof x === "string" ? x.localeCompare(y) : x - y;
		return c * dir || a.n.localeCompare(b.n);
	};
}
