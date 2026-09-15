export const SESSION_EXPIRED = "lobby-session-expired";

// A login in another tab replaces the server's one session token. Refresh with
// that account's current token, never a stale callback's or another account's.
export function latestSession(user) {
  let saved;
  try { saved = JSON.parse(localStorage.getItem("spender_user")); } catch {}
  if (saved?.id && saved.id !== user.id) throw new Error("Account changed");
  return saved?.session_token ? saved : user;
}

const requests = new Map();
export async function fetchGameHistory(url, user) {
  const session = latestSession(user);
  const key = `${url}:${user.id}`;
  const request = {};
  requests.set(key, request);
  const headers = { Authorization: `Bearer ${session.session_token}` };
  const current = () => {
    if (requests.get(key) !== request || latestSession(user).session_token !== session.session_token) {
      throw new Error("History request superseded");
    }
  };
  try {
    const response = await fetch(url, { headers });
    if (!response.ok) throw new Error("History unavailable");
    const data = await response.json();
    current();
    if (!Array.isArray(data.games)) throw new Error("Invalid history response");
    // Several older endpoints return just {games: []} for an expired login.
    // Only a confirmed valid session makes that an authoritative empty history.
    if (data.ok === false || (!data.games.length && data.ok !== true)) {
      const validation = await fetch(new URL("/auth/session", url), { headers });
      if (!validation.ok) throw new Error("Session check unavailable");
      const result = await validation.json();
      current();
      if (result.ok === false) {
        window.dispatchEvent(new CustomEvent(SESSION_EXPIRED, { detail: session }));
      }
      if (result.ok !== true || data.ok === false) throw new Error("History unavailable");
    }
    current();
    return data;
  } finally {
    if (requests.get(key) === request) requests.delete(key);
  }
}
