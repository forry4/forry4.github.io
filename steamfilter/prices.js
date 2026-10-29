// Prices for the Steam Filter page, off webapp/public/data/steam-prices.json (written by
// steamfilter/tools/prices.py). A store's entry is `[price]` or `[sale, regular, end,
// start]` in cents and Unix seconds (an end of 0: no end given). The eShop's start is
// its own; a Steam start is when the price check FIRST SAW the sale, because Steam
// publishes none — and one at or before the file's `tracked_since` was already running
// when starts began to be recorded, so it is only "on or before" that. Kept apart from
// the JSX so `npm run test:unit` can run it.

// A sale counts only inside its window. The file can be a day old, and a sale that has
// ended must read at its regular price, never at one that is gone. A discount with no
// end (Steam names none for a few) counts as running. `since` is the file's
// `tracked_since`, passed for Steam only: a start at or before it is not a date, so it
// comes back as `before` instead of `start`.
export function priceNow(p, now, since = 0) {
	if (!Array.isArray(p) || !p.length) return null;
	const [cur, reg, end, start] = p;
	if (p.length > 1 && (!end || now < end) && (!start || now >= start)) {
		const known = start && start > since;
		return { cur, reg, end: end || null, start: known ? start : null,
			before: start && !known ? since : null, off: Math.round((1 - cur / reg) * 100) };
	}
	return { cur: p.length > 1 ? reg : cur };
}

// True when a sale on `store` ("steam", "switch" or "either") started within the last
// `days`. A sale with no known start (Steam's, from before starts were recorded) is not
// recent by definition: it was already running then.
export function startedWithin(g, store, now, days) {
	const fresh = (p) => !!(p && p.off && p.start && now - p.start <= days * 86400);
	if (store === "steam") return fresh(g.ps);
	if (store === "switch") return fresh(g.pw);
	return fresh(g.ps) || fresh(g.pw);
}

// Adds to each game: `ps`/`pw` (Steam / eShop, from priceNow), `sp`/`wp` (today's price
// in cents, the sort keys) and `w2` (a Switch 2 version is sold). Rows missing from the
// file, or a file that never loaded, leave every price null.
export function attachPrices(games, rows, now, since = 0) {
	for (const g of games) {
		const r = (rows && rows[g.id]) || {};
		g.ps = priceNow(r.s, now, since);
		g.pw = priceNow(r.w, now);
		g.sp = g.ps ? g.ps.cur : null;
		g.wp = g.pw ? g.pw.cur : null;
		g.w2 = r.w2 ? 1 : 0;
	}
	return games;
}

export const money = (cents) => (cents === 0 ? "Free" : `$${(cents / 100).toFixed(2)}`);

// "Oct 31", in the reader's own time zone: the eShop ends a US sale at 11:59pm Pacific.
export const day = (sec) => new Date(sec * 1000).toLocaleDateString("en-US", { month: "short", day: "numeric" });

// "Oct 26–31", or "Oct 26–Nov 1" across a month end.
export function span(from, to) {
	const a = day(from), b = day(to);
	const [am] = a.split(" "), [bm, bd] = b.split(" ");
	return am === bm ? `${a}–${bd}` : `${a}–${b}`;
}
