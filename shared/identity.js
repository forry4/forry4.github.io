/* Who this device is.
 *
 * ONE localStorage key, `spender_user`, and once the site has loaded it is never
 * empty: a visitor who has not signed in IS a guest, stored in the same key and the
 * same shape as an account —
 *
 *   guest    { id, name, guest: true }
 *   account  { id, name, is_admin, session_token }
 *
 * — so the shell has an identity from its first render and nothing downstream has to
 * handle "nobody". Signing in replaces the guest; signing out (or a session the
 * server says is dead) replaces the account with a fresh guest. The id is the seat id
 * every game uses, which is why a guest keeps theirs across reloads.
 *
 * A guest never reaches the server here: the id and name are made on the device, and
 * a seat is still proved per room by the token that room hands out.
 */
const KEY = "spender_user";
export const GUEST_NAME_MAX = 20;

const newId = () => Math.random().toString(36).slice(2, 10);

export const isMember = (user) => !!(user && !user.guest && user.session_token);

export function readIdentity() {
	try {
		const user = JSON.parse(localStorage.getItem(KEY));
		return user && user.id ? user : null;
	} catch { return null; }
}

export function writeIdentity(user) {
	try { localStorage.setItem(KEY, JSON.stringify(user)); } catch {}
	return user;
}

export function newGuest() {
	return { id: newId(), name: `Guest${Math.floor(Math.random() * 9000 + 1000)}`, guest: true };
}

// The identity to start with: the stored one, else a guest made now.
export function loadIdentity() {
	const stored = readIdentity();
	if (stored) return stored;
	const guest = newGuest();
	// Guests used to keep only an id, under `spender_myId`, and were asked for a name
	// on every visit. Carry that id over so a game such a guest is seated in is still
	// theirs after this build lands.
	try {
		const old = localStorage.getItem("spender_myId");
		if (old) { guest.id = old; localStorage.removeItem("spender_myId"); }
	} catch {}
	return writeIdentity(guest);
}

// The guest to become when a login ends. Another tab may have got there first, in
// which case this tab takes the guest it stored rather than making a second one.
export function guestAfterLogin() {
	const stored = readIdentity();
	return stored?.guest ? stored : writeIdentity(newGuest());
}

// A guest's chosen display name; an empty one keeps the name they had.
export function renamedGuest(guest, name) {
	const clean = String(name || "").trim().slice(0, GUEST_NAME_MAX);
	return clean && clean !== guest.name ? writeIdentity({ ...guest, name: clean }) : guest;
}
