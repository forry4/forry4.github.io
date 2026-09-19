/* Shared seat lifecycle helpers.

   A room token is a credential, not a navigation hint: it proves that the
   browser owns a seat when it reconnects or deliberately leaves an open table.
   Keep the storage and HTTP leave shape in one place so a new game cannot invent
   a second, unauthenticated way to release somebody else's seat.
*/

export function readRoomToken(tokenKey) {
	if (!tokenKey) return "";
	try { return localStorage.getItem(tokenKey) || ""; } catch { return ""; }
}

export function clearRoomToken(tokenKey) {
	if (!tokenKey) return;
	try { localStorage.removeItem(tokenKey); } catch {}
}

/**
 * Explicitly leave a seat in an open room. Leaving the lobby itself must never
 * call this; it only closes the socket and preserves the seat for Return/Resume.
 */
export async function leaveOpenSeat({ endpoint, roomId, playerId, tokenKey, sessionToken }) {
	const params = new URLSearchParams({ player_id: playerId });
	const headers = {};
	if (sessionToken) headers.Authorization = `Bearer ${sessionToken}`;
	const roomToken = readRoomToken(tokenKey);
	if (roomToken) headers["X-Room-Token"] = roomToken;
	const response = await fetch(`${endpoint}/${encodeURIComponent(roomId)}/leave?${params}`, {
		method: "POST",
		headers,
	});
	let data = null;
	try { data = await response.json(); } catch {}
	if (!response.ok || !data?.ok) {
		throw new Error(data?.message || "Could not leave that table");
	}
	clearRoomToken(tokenKey);
	return data;
}
