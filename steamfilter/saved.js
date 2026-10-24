// Saved games for the Steam Filter page. Kept apart from the JSX so `npm run test:unit`
// can run it.
//
// The device keeps a copy per identity: `{ saved: {appId: savedAtSec}, pending: {appId:
// true|false} }`. For a guest that copy IS the list. For a signed-in reader the server
// (/steamfilter/saved) is, and `pending` holds the stars not yet sent — made offline, or
// mid-request — so nothing a reader does is lost to a dropped connection.

export const savedKey = (who) => `steam_filter_saved_v1.${who}`;
const EMPTY = { saved: {}, pending: {} };

export function readSaved(who) {
	try {
		const v = JSON.parse(localStorage.getItem(savedKey(who)) || "null");
		if (!v || typeof v !== "object") return EMPTY;
		const obj = (o) => (o && typeof o === "object" && !Array.isArray(o) ? o : {});
		return { saved: obj(v.saved), pending: obj(v.pending) };
	} catch { return EMPTY; }
}

export function writeSaved(who, store) {
	try { localStorage.setItem(savedKey(who), JSON.stringify(store)); } catch { /* storage unavailable */ }
}

export function clearSaved(who) {
	try { localStorage.removeItem(savedKey(who)); } catch { /* storage unavailable */ }
}

// One star pressed. A member's change is also queued for the server.
export function toggle(store, id, now, member) {
	const saved = { ...store.saved };
	const on = !(id in saved);
	if (on) saved[id] = now; else delete saved[id];
	return { saved, pending: member ? { ...store.pending, [id]: on } : store.pending };
}

// A guest's list handed to the account the first time they are signed in: every game
// they saved is queued as a save, on top of whatever the account already holds.
export function adopt(store, guest, now) {
	const saved = { ...store.saved };
	const pending = { ...store.pending };
	for (const [id, at] of Object.entries(guest.saved)) {
		if (!(id in saved)) saved[id] = at || now;
		pending[id] = true;
	}
	return { saved, pending };
}

// The server answered with its whole list (`[[appId, savedAt], ...]`) after `sent` was
// applied. A queued change is done once the server has it — unless the reader changed
// that game again while the request was out, in which case it stays queued. The list
// shown is the server's with whatever is still queued laid over it.
export function settle(store, sent, list) {
	const pending = {};
	for (const [id, on] of Object.entries(store.pending)) {
		if (sent[id] !== on) pending[id] = on;
	}
	const saved = {};
	for (const [id, at] of list) saved[id] = at;
	for (const [id, on] of Object.entries(pending)) {
		if (on && !(id in saved)) saved[id] = store.saved[id] || 0;
		if (!on) delete saved[id];
	}
	return { saved, pending };
}

// What to send for the queued changes.
export function batch(pending) {
	const save = [], unsave = [];
	for (const [id, on] of Object.entries(pending)) (on ? save : unsave).push(Number(id));
	return { save, unsave };
}
