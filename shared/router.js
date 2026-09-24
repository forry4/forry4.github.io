// shared/router.js — minimal hand-rolled History-API sync for the games site.
// No router library on purpose: the shell (Spender.jsx) routes by `screen` state and the
// sub-games are self-contained; this module is just a thin two-way mirror between that
// state and the address bar. Path grammar:
//   "/"                 -> { game: "home",  room: null }
//   "/<mode>"           -> { game: <mode>,  room: null }     e.g. /duel
//   "/<mode>/<ROOMID>"  -> { game: <mode>,  room: "ROOMID" } e.g. /duel/ABC123
// Unknown first segments parse to { game: null } — the caller normalizes to "/".
//
// Contract (load-bearing, do not change casually):
//  - pushPath/replacePath are NO-OPS when the path is already current. This dedup guard is
//    what lets one function (leaveToLobby, goToMenu, ...) serve both user clicks (URL
//    differs -> push) and popstate-driven calls (URL already there -> no-op) with zero
//    duplicate history entries.
//  - subscribe() fires on POPSTATE ONLY (browser Back/Forward). Programmatic push/replace
//    never notify, so URL-write + state-write at a call site can't echo back into a loop.

export const MODES = ["spender", "coc", "duel", "werewolf", "dontminion", "dissonance", "ragtag", "orbit", "blackcastle", "secretnames", "pinch", "books", "notes", "profile", "puzzles", "bggfilter", "offline"];

// Room ids are short alphanumeric codes (normalize_room uppercases server-side).
const ROOM_RE = /^[A-Za-z0-9_-]{1,24}$/;

// Honors VITE_BASE if the site is ever served off a sub-path (prod/staging use "/").
function base() {
  const b = (import.meta.env && import.meta.env.BASE_URL) || "/";
  return b.endsWith("/") ? b.slice(0, -1) : b;
}

export function parsePath(pathname) {
  let p = pathname != null ? pathname : window.location.pathname;
  const b = base();
  if (b && p.startsWith(b)) p = p.slice(b.length);
  const seg = p.split("/").filter(Boolean);
  if (seg.length === 0) return { game: "home", room: null };
  const game = seg[0].toLowerCase();
  if (!MODES.includes(game)) return { game: null, room: null };
  const room = seg[1] && ROOM_RE.test(seg[1]) ? seg[1].toUpperCase() : null;
  return { game, room };
}

export function buildPath(game, room) {
  if (!game || game === "home") return base() + "/";
  return base() + "/" + game + (room ? "/" + room : "");
}

export function pushPath(path) {
  if (window.location.pathname === path) return;
  try { window.history.pushState(null, "", path); } catch { /* e.g. file:// harness */ }
}

export function replacePath(path) {
  if (window.location.pathname === path) return;
  try { window.history.replaceState(null, "", path); } catch { /* e.g. file:// harness */ }
}

// Navigate the way the browser's own Back/Forward does: write the URL, then tell
// the shell through the popstate its subscriber already handles. It exists for
// SHARED components the shell hands no callback to: the name in every lobby's top
// bar opens the profile this way, instead of eleven lobbies each threading an
// `onProfile` prop down from the shell. Every game's own subscriber ignores a
// route that is not its mode, and the shell unmounts it. `state.inApp` is how the
// destination knows Back can return where you came from (`cameFromInsideApp`).
export function navigateTo(game, room) {
  const path = buildPath(game, room);
  if (window.location.pathname === path) return;
  try { window.history.pushState({ inApp: true }, "", path); } catch { return; }
  window.dispatchEvent(new PopStateEvent("popstate", { state: { inApp: true } }));
}

export function cameFromInsideApp() {
  try { return !!window.history.state?.inApp; } catch { return false; }
}

export function subscribe(fn) {
  const h = () => fn(parsePath());
  window.addEventListener("popstate", h);
  return () => window.removeEventListener("popstate", h);
}
