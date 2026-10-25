// Saved and not-interested games for the Steam Filter page. Kept apart from the JSX so
// `npm run test:unit` can run it.
//
// A game carries at most ONE mark: "saved" (keep it for later), "hidden" (not
// interested — it leaves the list) or "none". The device keeps a copy per identity:
// `{ saved: {appId: at}, hidden: {appId: at}, pending: {appId: mark} }`. For a guest that
// copy IS the lists. For a signed-in reader the server (/steamfilter/saved) is, and
// `pending` holds the marks not yet sent — made offline, or mid-request — so nothing a
// reader does is lost to a dropped connection.

export const savedKey = (who) => `steam_filter_saved_v1.${who}`;
const EMPTY = { saved: {}, hidden: {}, pending: {} };
const MARKS = ["saved", "hidden", "none"];

export function readSaved(who) {
	try {
		const v = JSON.parse(localStorage.getItem(savedKey(who)) || "null");
		if (!v || typeof v !== "object") return EMPTY;
		const obj = (o) => (o && typeof o === "object" && !Array.isArray(o) ? o : {});
		// Before "not interested" existed, a queued change was true (save) / false (unsave).
		const pending = {};
		for (const [id, m] of Object.entries(obj(v.pending))) {
			const mark = m === true ? "saved" : m === false ? "none" : m;
			if (MARKS.includes(mark)) pending[id] = mark;
		}
		return { saved: obj(v.saved), hidden: obj(v.hidden), pending };
	} catch { return EMPTY; }
}

export function writeSaved(who, store) {
	try { localStorage.setItem(savedKey(who), JSON.stringify(store)); } catch { /* storage unavailable */ }
}

export function clearSaved(who) {
	try { localStorage.removeItem(savedKey(who)); } catch { /* storage unavailable */ }
}

export const markOf = (store, id) => (id in store.saved ? "saved" : id in store.hidden ? "hidden" : "none");

// Give a game `mark`, dropping whatever mark it had. A member's change is also queued.
export function setMark(store, id, mark, now, member) {
	const saved = { ...store.saved }, hidden = { ...store.hidden };
	delete saved[id];
	delete hidden[id];
	if (mark === "saved") saved[id] = now;
	if (mark === "hidden") hidden[id] = now;
	return { saved, hidden, pending: member ? { ...store.pending, [id]: mark } : store.pending };
}

// A guest's lists handed to the account the first time they are signed in: every mark
// they made is queued, on top of whatever the account already holds.
export function adopt(store, guest, now) {
	let s = store;
	for (const mark of ["saved", "hidden"]) {
		for (const [id, at] of Object.entries(guest[mark] || {})) {
			s = setMark(s, id, mark, at || now, true);
		}
	}
	return s;
}

const fromList = (list) => {
	const out = {};
	for (const [id, at] of list) out[id] = at;
	return out;
};

// The server answered with its whole lists (`{saved: [[appId, at], ...], hidden: [...]}`)
// after `sent` was applied. A queued mark is done once the server has it — unless the
// reader changed that game again while the request was out, in which case it stays
// queued. A server from before "not interested" sends no `hidden`: then only saves
// count as done, and the device's own not-interested list stands until one does.
// The lists shown are the server's with whatever is still queued laid over them.
export function settle(store, sent, reply) {
	const knowsHidden = Array.isArray(reply.hidden);
	const pending = {};
	for (const [id, mark] of Object.entries(store.pending)) {
		const done = sent[id] === mark && (knowsHidden || mark === "saved");
		if (!done) pending[id] = mark;
	}
	let s = { saved: fromList(reply.saved || []), hidden: knowsHidden ? fromList(reply.hidden) : { ...store.hidden },
		pending: {} };
	for (const [id, mark] of Object.entries(pending)) {
		const at = store.saved[id] || store.hidden[id] || 0;
		s = setMark(s, id, mark, at, false);
	}
	return { ...s, pending };
}

// What to send for the queued marks. "none" asks for both removals; each is a no-op
// where it does not apply.
export function batch(pending) {
	const out = { save: [], unsave: [], hide: [], unhide: [] };
	for (const [id, mark] of Object.entries(pending)) {
		const n = Number(id);
		if (mark === "saved") out.save.push(n);
		else if (mark === "hidden") out.hide.push(n);
		else { out.unsave.push(n); out.unhide.push(n); }
	}
	return out;
}
