/* Notes, read offline — a copy of this account's notes and pictures on this device.
 *
 * The offline hub's Read section opens Notes with no connection. The folder tree was
 * already kept (localStorage, `notes.tree.<uid>`); the note BODIES and the pictures
 * were not, since both come from the server per note. This keeps them:
 *   - `syncNotesOffline` runs in the background whenever Notes loads online (and from
 *     the hub's Reading download). It fetches only notes edited since the copy was
 *     taken (by `updated_at`), then any picture those notes name that is not stored yet, one
 *     request at a time so it never competes with the page.
 *   - offline, the editor opens a note from here READ-ONLY, and images.js falls back
 *     here for pictures.
 *
 * PRIVATE DATA ON A DEVICE, so: its own database (`forrest-notes`, separate from the
 * offline games), keyed by account, and `clearNotesOffline()` wipes all of it on
 * sign-out (Spender.jsx handleLogout). A note deleted or trashed on the server is
 * dropped from the copy at the next sync.
 *
 * Every call swallows storage failures (private mode, eviction) into "no copy".
 */

const DB_NAME = "forrest-notes";
const NOTES = "notes";      // { k: "<uid>:<noteId>", uid, note }
const IMAGES = "images";    // { k: "<uid>:<imageId>", uid, blob }

let _dbP = null;
function openDb() {
	if (_dbP) return _dbP;
	_dbP = new Promise((resolve, reject) => {
		try {
			const req = indexedDB.open(DB_NAME, 1);
			req.onupgradeneeded = () => {
				for (const name of [NOTES, IMAGES]) {
					if (!req.result.objectStoreNames.contains(name)) req.result.createObjectStore(name, { keyPath: "k" });
				}
			};
			req.onsuccess = () => resolve(req.result);
			req.onerror = () => reject(req.error);
		} catch (e) { reject(e); }
	});
	_dbP.catch(() => { _dbP = null; });
	return _dbP;
}

function run(store, mode, fn) {
	return openDb().then((db) => new Promise((resolve, reject) => {
		const t = db.transaction(store, mode);
		const req = fn(t.objectStore(store));
		t.oncomplete = () => resolve(req?.result);
		t.onerror = () => reject(t.error);
		t.onabort = () => reject(t.error);
	}));
}

export async function getOfflineNote(uid, id) {
	try { return (await run(NOTES, "readonly", (s) => s.get(`${uid}:${id}`)))?.note || null; }
	catch { return null; }
}

export async function putOfflineNote(uid, note) {
	if (!uid || !note?.id) return;
	try { await run(NOTES, "readwrite", (s) => s.put({ k: `${uid}:${note.id}`, uid, note })); } catch { /* no copy */ }
}

export async function getOfflineImage(uid, id) {
	try { return (await run(IMAGES, "readonly", (s) => s.get(`${uid}:${id}`)))?.blob || null; }
	catch { return null; }
}

async function putOfflineImage(uid, id, blob) {
	try { await run(IMAGES, "readwrite", (s) => s.put({ k: `${uid}:${id}`, uid, blob })); } catch { /* no copy */ }
}

async function keysFor(store, uid) {
	try {
		const all = await run(store, "readonly", (s) => s.getAllKeys());
		return (all || []).filter((k) => typeof k === "string" && k.startsWith(`${uid}:`));
	} catch { return []; }
}

/** Every image id a TipTap doc names. */
export function imageIdsIn(doc) {
	const out = new Set();
	const walk = (node) => {
		if (!node || typeof node !== "object") return;
		if (node.attrs?.imageId) out.add(node.attrs.imageId);
		(node.content || []).forEach(walk);
	};
	walk(doc);
	return out;
}

let _syncing = null;
// Bumped by clearNotesOffline. A sync that started before a sign-out must not write
// the old account's notes back into the database the sign-out just deleted.
let _generation = 0;
/** Bring this device's copy up to date with `tree` (the server's current listing).
 *  Trashed notes are kept only if already copied (they open read-only anyway);
 *  notes gone from the tree are dropped. One sync at a time per page. */
export function syncNotesOffline(api, uid, tree) {
	if (!uid || !tree || _syncing) return _syncing || Promise.resolve();
	const gen = _generation;
	const current = () => gen === _generation;
	_syncing = (async () => {
		const liveIds = new Set((tree.notes || []).map((n) => n.id));
		for (const k of await keysFor(NOTES, uid)) {
			if (!liveIds.has(k.slice(uid.length + 1))) {
				try { await run(NOTES, "readwrite", (s) => s.delete(k)); } catch { /* ignore */ }
			}
		}
		const wantImages = new Set();
		for (const meta of tree.notes || []) {
			if (meta.deleted_at != null) continue;
			let note = await getOfflineNote(uid, meta.id);
			// `updated_at`, not `rev`: the listing carries no rev. A content save moves it
			// (notes/api.py save_note); moving or pinning does not, and needs no re-copy —
			// the folder tree comes from its own cache.
			if (!note || note.updated_at !== meta.updated_at) {
				try { note = await api.getNote(meta.id); } catch { return; }   // offline mid-sync: stop, try next time
				if (!current()) return;
				await putOfflineNote(uid, note);
			}
			for (const id of imageIdsIn(note.doc)) wantImages.add(id);
		}
		const have = new Set((await keysFor(IMAGES, uid)).map((k) => k.slice(uid.length + 1)));
		for (const id of wantImages) {
			if (have.has(id)) continue;
			let blob;
			try { blob = await api.imageBlob(id); } catch { return; }
			if (!current()) return;
			await putOfflineImage(uid, id, blob);
		}
	})().finally(() => { _syncing = null; });
	return _syncing;
}

/** Sign-out: wipe every account's copy on this device, and the cached folder trees. */
export async function clearNotesOffline() {
	_generation += 1;
	try {
		for (const k of Object.keys(localStorage)) if (k.startsWith("notes.tree.")) localStorage.removeItem(k);
	} catch { /* ignore */ }
	try {
		const db = await openDb();
		db.close();
		_dbP = null;
	} catch { /* never opened */ }
	try {
		await new Promise((resolve) => {
			const req = indexedDB.deleteDatabase(DB_NAME);
			req.onsuccess = req.onerror = req.onblocked = () => resolve();
		});
	} catch { /* nothing stored */ }
}
