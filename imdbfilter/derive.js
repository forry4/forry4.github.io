// IMDb Filter's logic, kept out of the component so webapp/test/unit/imdbfilter.test.mjs
// can hold it without a DOM. The payload is imdbfilter/tools/make_data.py's.

// The four kinds of title, in the payload's one-letter codes.
export const KINDS = [
	{ k: "f", label: "Films", one: "Film" },
	{ k: "t", label: "TV films", one: "TV film" },
	{ k: "s", label: "Series", one: "Series" },
	{ k: "m", label: "Mini-series", one: "Mini-series" },
];
export const ALL_KINDS = KINDS.map((x) => x.k);
export const SERIES = new Set(["s", "m"]);
const ONE = Object.fromEntries(KINDS.map((x) => [x.k, x.one]));

// IMDb's own Top 250 formula: m votes at the mean c are added to every title, so a
// title with few votes is pulled toward the mean and one with millions keeps its own.
export function weighted(r, v, bayes) {
	return (v * r + bayes.m * bayes.c) / (v + bayes.m);
}

// tt + at least seven digits, as IMDb writes its ids.
export const ttid = (i) => `tt${String(i).padStart(7, "0")}`;

// The payload's rows, with the interned names and genres spelled out and the search
// text built once rather than on every keystroke.
export function buildRows(data) {
	const names = data.names, genres = data.genres;
	return data.titles.map((t) => {
		const d = (t.d || []).map((i) => names[i]);
		const c = (t.c || []).map((i) => names[i]);
		return {
			...t, key: t.i, id: ttid(t.i), g: (t.g || []).map((i) => genres[i]), d, c,
			kind: ONE[t.k], w: weighted(t.r, t.v, data.bayes),
			hay: [t.n, t.o, ...d, ...c].filter(Boolean).join("\n").toLowerCase(),
		};
	});
}

// Criteria: kinds (allowed codes), yfrom/yto, votes, rating, rtmin/rtmax (0 = no bound),
// inc (every one required) and exc (none allowed) genres. A bound on a field a title
// does not have (no year, no runtime) fails it, since nothing says it would pass.
export function passes(r, d) {
	if (d.kinds && !d.kinds.includes(r.k)) return false;
	if (d.yfrom && !(r.y >= d.yfrom)) return false;
	if (d.yto && !(r.y <= d.yto)) return false;
	if (d.votes && !(r.v >= d.votes)) return false;
	if (d.rating && !(r.r >= d.rating)) return false;
	if (d.rtmin && !(r.rt >= d.rtmin)) return false;
	if (d.rtmax && !(r.rt <= d.rtmax)) return false;
	for (const g of d.inc || []) if (!r.g.includes(g)) return false;
	for (const g of d.exc || []) if (r.g.includes(g)) return false;
	return true;
}

export function matches(r, needle) {
	return !needle || r.hay.includes(needle);
}

// Sort comparator: a missing value sorts last whichever way the column runs.
export function sorter(key, dir) {
	return (a, b) => {
		const x = a[key], y = b[key];
		if ((x == null) !== (y == null)) return x == null ? 1 : -1;
		const c = x == null ? 0 : typeof x === "string" ? x.localeCompare(y) : x - y;
		return c * dir || b.v - a.v || a.n.localeCompare(b.n);
	};
}

// A genre chip cycles off -> required -> excluded -> off.
export function cycleGenre(inc, exc, g) {
	if (inc.includes(g)) return { inc: inc.filter((x) => x !== g), exc: [...exc, g] };
	if (exc.includes(g)) return { inc, exc: exc.filter((x) => x !== g) };
	return { inc: [...inc, g], exc };
}

export function years(r) {
	if (!r.y) return "—";
	if (!SERIES.has(r.k)) return `${r.y}`;
	if (!r.ye) return `${r.y}–`;
	return r.ye === r.y ? `${r.y}` : `${r.y}–${r.ye}`;
}

export function runtime(m) {
	if (!m) return "—";
	const h = Math.floor(m / 60), mm = m % 60;
	return h ? `${h}h ${String(mm).padStart(2, "0")}m` : `${mm}m`;
}

export function length(r) {
	if (!SERIES.has(r.k)) return "";
	const out = [];
	if (r.se) out.push(`${r.se} season${r.se === 1 ? "" : "s"}`);
	if (r.ep) out.push(`${r.ep.toLocaleString("en-US")} episode${r.ep === 1 ? "" : "s"}`);
	return out.join(" · ");
}
