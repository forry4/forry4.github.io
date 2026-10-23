// Prices for the Steam Filter page, off webapp/public/data/steam-prices.json (written by
// steamfilter/tools/prices.py). A store's entry is `[price]` or `[sale, regular, end]`
// in cents, end in Unix seconds; the eShop adds the sale's start. Kept apart from the
// JSX so `npm run test:unit` can run it.

// A sale counts only inside its window. The file can be a day old, and a sale that has
// ended must read at its regular price, never at one that is gone. A discount with no
// end (Steam names none for a few) counts as running.
export function priceNow(p, now) {
	if (!Array.isArray(p) || !p.length) return null;
	const [cur, reg, end, start] = p;
	if (p.length > 1 && (!end || now < end) && (!start || now >= start)) {
		return { cur, reg, end: end || null, start: start || null, off: Math.round((1 - cur / reg) * 100) };
	}
	return { cur: p.length > 1 ? reg : cur };
}

// Adds to each game: `ps`/`pw` (Steam / eShop, from priceNow), `sp`/`wp` (today's price
// in cents, the sort keys) and `w2` (a Switch 2 version is sold). Rows missing from the
// file, or a file that never loaded, leave every price null.
export function attachPrices(games, rows, now) {
	for (const g of games) {
		const r = (rows && rows[g.id]) || {};
		g.ps = priceNow(r.s, now);
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
