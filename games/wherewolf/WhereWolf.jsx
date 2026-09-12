import { useState, useEffect, useRef, useCallback } from "react";
import { baseCss } from "../../shared/theme.js";
import { lobbyCss, LobbyHeader, LobbySectionHd, LobbyLoading, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame,
  createModalCss, CreateModal, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, LobbyHero, LobbyAction, LobbyTabs, timeAgo,
  notWaiting, LobbyUser, useListFade } from "../../shared/lobby.jsx";
import WhereWolfRules from "./rules.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _cssText from "./WhereWolf.css?inline";
// The home card and this screen must be the same colour; one value, see shared/accents.js.
import { GAME_ACCENTS } from "../../shared/accents.js";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WW_WS = WS_RAW.replace(/\/ws$/, "/werewolf/ws");
const WW_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/werewolf");

// Display metadata per role. `letter` mirrors the backend token letters
// (mason = "MA"); collisions (tanner/troublemaker both "T") are intentional —
// the physical tokens collide too.
const ROLE_META = {
  werewolf: { name: "Werewolf", color: "#b3322f", team: "werewolf",
    desc: "Wakes to see the other werewolves. The werewolf team wins if no werewolf is killed." },
  villager: { name: "Villager", color: "#5b8c5a", team: "village",
    desc: "No night action — just a townsperson trying to root out the werewolves." },
  seer: { name: "Seer", color: "#6a4ea3", team: "village",
    desc: "May look at one other player's card, or two of the three center cards." },
  robber: { name: "Robber", color: "#b8863b", team: "village",
    desc: "May swap their card with another player's, then look at their new card." },
  troublemaker: { name: "Troublemaker", color: "#c25b8a", team: "village",
    desc: "May swap two OTHER players' cards — without looking at either." },
  tanner: { name: "Tanner", color: "#8a6d3b", team: "tanner",
    desc: "Hates their job: wins only by being killed, and a tanner death denies the werewolves their win." },
  drunk: { name: "Drunk", color: "#7a8aa0", team: "village",
    desc: "Swaps their card with a center card — blindly, never seeing the new one." },
  hunter: { name: "Hunter", color: "#7d5a3c", team: "village",
    desc: "If the hunter is killed, the player they voted for dies too." },
  mason: { name: "Mason", color: "#3f8f8f", team: "village",
    desc: "Wakes to see the other Mason (or that they're alone)." },
  insomniac: { name: "Insomniac", color: "#a05a7a", team: "village",
    desc: "Wakes at the end of the night to look at their own (possibly swapped) card." },
  minion: { name: "Minion", color: "#9a3a3a", team: "werewolf",
    desc: "Sees the werewolves and wins with them — but is NOT a werewolf, so killing the minion doesn't save the village." },
  doppelganger: { name: "Doppelganger", color: "#6a6aa0", team: "village",
    desc: "Copies another player's role and acts as it. (Not available yet.)" },
};
const roleName = (r) => (r && ROLE_META[r]?.name) || (r ? r : "Unknown");
const roleColor = (r) => (r && ROLE_META[r]?.color) || "#3a342a";
const roleDesc = (r) => (r && ROLE_META[r]?.desc) || "";
// Public token letter for a role (mirror of roles.TOKEN_LETTERS — mason is "MA" so
// it doesn't collide with minion's "M").
const tokenLetter = (r) => (r === "mason" ? "MA" : (r ? r[0].toUpperCase() : "?"));

// Cinzel renders as wide caps, so the longer role names don't fit one card line.
// The 12-char names (Troublemaker/Doppelganger) are too wide for ANY card, so force a
// HARD break — a soft <wbr> is not honored reliably inside a flex item in every
// browser, which left "Troublemaker" overflowing on desktop. The borderline names get
// a soft <wbr> that only breaks on the narrow center cards (with overflow-wrap:anywhere
// as the safety net). Index = where to split.
const CARD_BR = { troublemaker: 7, doppelganger: 6 };          // always two lines
const CARD_WBR = { werewolf: 4, villager: 4, insomniac: 5 };   // break only if it doesn't fit
const cardLabel = (r) => {
  const n = roleName(r);
  if (CARD_BR[r]) { const i = CARD_BR[r]; return <>{n.slice(0, i)}<br />{n.slice(i)}</>; }
  const at = CARD_WBR[r];
  return at ? <>{n.slice(0, at)}<wbr />{n.slice(at)}</> : n;
};

// Seat cards scale down as the table fills so up to 10 still ring the circle (card
// height must stay under the chord between adjacent seats), while the common 3–7
// player games get big, readable cards. On a phone the whole table is smaller and
// the ellipse is tall, so the tiers are tighter. Returns inline CSS vars the cards
// read via var(--pcw/--pch/--pcf).
const cardVars = (n, mobile) => {
  const tiers = mobile
    ? (n <= 7 ? ["58px", "76px", "10px"] : n <= 9 ? ["52px", "68px", "9.5px"] : ["46px", "60px", "9px"])
    : (n <= 7 ? ["76px", "98px", "11.5px"] : n <= 9 ? ["66px", "86px", "10.5px"] : ["56px", "76px", "10px"]);
  const [w, h, f] = tiers;
  return { "--pcw": w, "--pch": h, "--pcf": f };
};

// Host role picker: selectable roles (no doppelganger yet) + per-role copy caps.
const ROLE_CAPS = { werewolf: 2, villager: 3, mason: 2, seer: 1, robber: 1,
  troublemaker: 1, minion: 1, tanner: 1, drunk: 1, hunter: 1, insomniac: 1 };
const PICKABLE = ["werewolf", "villager", "seer", "robber", "troublemaker", "mason",
  "minion", "tanner", "drunk", "hunter", "insomniac"];
const ACTION_ROLES = ["seer", "robber", "troublemaker", "drunk"];   // take a move in their step
const TEAM_CLASS = { village: "villagers", werewolf: "wolves", tanner: "tanner", minion: "wolves" };
function deckCounts(deck) {
  const c = {}; (deck || []).forEach((r) => { c[r] = (c[r] || 0) + 1; }); return c;
}

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() {
  return Array.from({ length: 4 }, () => "ABCDEFGHJKLMNPQRSTUVWXYZ"[Math.floor(Math.random() * 24)]).join("");
}
function fmtTime(s) {
  if (s == null) return "";
  s = Math.max(0, Math.floor(s));
  return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0");
}

// Seat position on a unit circle (percent of the square table). `rel` is the
// seat index relative to the local player, who sits at rel 0 = 6 o'clock (bottom).
function seatXY(rel, total) {
  const ang = Math.PI / 2 + (rel / total) * 2 * Math.PI;   // +PI/2 = bottom
  return { x: 50 + 39 * Math.cos(ang), y: 50 + 39 * Math.sin(ang) };
}

// A small looping arrow from a seat back to ITSELF (self-vote). The loop sits just
// inside the seat (toward the table centre, where there's open space) and the arrow
// curls almost all the way round so the head points back at the card. Coords are in
// the 0..100 unit viewBox the vote SVG uses.
function selfLoopPath(sx, sy) {
  let ix = 50 - sx, iy = 50 - sy;                  // unit vector toward the table centre
  const L = Math.hypot(ix, iy) || 1; ix /= L; iy /= L;
  const cx = sx + ix * 9, cy = sy + iy * 9;        // loop centre, in open space
  const r = 4.2, g = 0.6;                          // radius + gap (radians) for the arrow mouth
  const px = -iy, py = ix;                         // tangent (perpendicular to inward dir)
  // start/end both on the seat-facing side of the circle, separated by the gap `g`
  const sX = cx - (ix * Math.cos(g) - px * Math.sin(g)) * r;
  const sY = cy - (iy * Math.cos(g) - py * Math.sin(g)) * r;
  const eX = cx - (ix * Math.cos(g) + px * Math.sin(g)) * r;
  const eY = cy - (iy * Math.cos(g) + py * Math.sin(g)) * r;
  // sweep the long way round (large-arc=1) and end at eX,eY so the head points home
  return `M ${sX.toFixed(2)} ${sY.toFixed(2)} A ${r} ${r} 0 1 1 ${eX.toFixed(2)} ${eY.toFixed(2)}`;
}

// ─── Narration audio ─────────────────────────────────────────────────────────
// Prefer the pre-rendered neural clips (one mp3 per NARRATION key, rendered offline
// by games/wherewolf/render_narration.py into webapp/public/werewolf/narration/);
// fall back to the browser's Web Speech voice (tuned a touch lower/slower) if a clip
// is missing or can't play. Only ever one narration audible at a time.
let _narrAudio = null;
function _speakFallback(text) {
  if (typeof window === "undefined" || !window.speechSynthesis || !text) return;
  try {
    const u = new SpeechSynthesisUtterance(text);
    u.rate = 0.95;
    u.pitch = 0.9;
    window.speechSynthesis.speak(u);
  } catch {}
}
function playNarration(key, text) {
  try { if (_narrAudio) _narrAudio.pause(); } catch {}
  _narrAudio = null;
  try { if (typeof window !== "undefined" && window.speechSynthesis) window.speechSynthesis.cancel(); } catch {}
  const base = (import.meta.env && import.meta.env.BASE_URL) || "/";
  if (!key || typeof Audio === "undefined") { _speakFallback(text); return; }
  const a = new Audio(`${base}werewolf/narration/${key}.mp3`);
  _narrAudio = a;
  let fellBack = false;
  const fallback = () => {                 // fire at most once (onerror OR play() reject)
    if (fellBack) return;
    fellBack = true;
    if (_narrAudio === a) _narrAudio = null;
    _speakFallback(text);
  };
  a.onerror = fallback;
  a.play().catch(fallback);
}

// ─── Minimal WebSocket hook (same shape as the other games) ──────────────────
function useSocket(onMessage) {
  const wsRef = useRef(null);
  const [connected, setConnected] = useState(false);
  const onMsg = useRef(onMessage);
  onMsg.current = onMessage;
  const connect = useCallback((url, firstMsg) => {
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => { setConnected(true); if (firstMsg) ws.send(JSON.stringify(firstMsg)); };
    ws.onclose = () => setConnected(false);
    ws.onmessage = (e) => { try { onMsg.current(JSON.parse(e.data)); } catch {} };
  }, []);
  const send = useCallback((obj) => { try { wsRef.current?.send(JSON.stringify(obj)); } catch {} }, []);
  const disconnect = useCallback(() => { try { wsRef.current?.close(); } catch {} wsRef.current = null; setConnected(false); }, []);
  return { connected, connect, send, disconnect };
}

// ─── Countdown hook (ticks while a deadline is set; server is the clock) ──────
function useNow(active) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    if (!active) return;
    const t = setInterval(() => setNow(Date.now() / 1000), 250);
    return () => clearInterval(t);
  }, [active]);
  return now;
}

// ─── Phone breakpoint (drives the smaller seat cards; the table itself reshapes
// to a tall ellipse via the @media block). Mirrors the 600px CSS breakpoint. ──
function useIsMobile() {
  const [m, setM] = useState(() => typeof window !== "undefined" && !!window.matchMedia?.("(max-width:600px)").matches);
  useEffect(() => {
    const mq = window.matchMedia?.("(max-width:600px)");
    if (!mq) return;
    const fn = () => setM(mq.matches);
    fn();
    mq.addEventListener?.("change", fn);
    return () => mq.removeEventListener?.("change", fn);
  }, []);
  return m;
}

// ─── Styles (baseCss first; NEVER put a backtick inside this template) ───────
const css = baseCss + lobbyCss + _cssText + gameMenuCss + createModalCss + lobbyCreateRowCss + rulesModalCss;

// ─── Component ───────────────────────────────────────────────────────────────
export default function WhereWolf({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");      // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState(() => readLobbyCache("ww", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("ww", myId, "mine", []));
  const [showRules, setShowRules] = useState(false);  // lobby "How to Play" modal
  // phone-only: which of the two lobby sections the tab bar is showing
  const [lobbyTab, setLobbyTab] = useState("open");
  // A column that scrolls inside itself must say so — see `useListFade`.
  useListFade();
  const [showCreateModal, setShowCreateModal] = useState(false);  // New Game confirm modal
  const [toast, setToast] = useState("");
  // room connect in flight (create / join / deep-link resume) — show the spinner
  // instead of the lobby while it is, so a reconnect doesn't flash the lobby.
  const [connecting, setConnecting] = useState(false);

  // narration
  const [caption, setCaption] = useState("");
  const [narrateOn, setNarrateOn] = useState(() => {
    try { const v = localStorage.getItem("werewolf_narrate"); return v == null ? null : v === "1"; } catch { return null; }
  });

  // night/day interaction selection
  const [centerSel, setCenterSel] = useState([]);     // seer: selected center indices
  const [tmSel, setTmSel] = useState([]);             // troublemaker: selected pids
  const [pickDeck, setPickDeck] = useState(null);     // host's local role-picker deck
  const [tokenInfo, setTokenInfo] = useState(null);   // role whose info is shown (token tap)
  const isMobile = useIsMobile();

  const playerName = authUser?.name || "Guest";

  // ── derived game state ──
  const game = roomData?.game;
  const phase = game?.phase;
  const order = game?.order || [];
  const myIdx = order.indexOf(myId);
  const myDealt = game?.your_dealt_role || null;
  const step = game?.night_step;
  const acted = game?.acted || {};
  const isHost = roomData?.host === myId;

  // effective narrate: explicit pref wins, else default ON for the host only
  const effNarrate = narrateOn == null ? isHost : narrateOn;
  const narrateRef = useRef(effNarrate);
  narrateRef.current = effNarrate;

  // bounded auto-reconnect attempts (reset to 0 once a socket opens)
  const reconnectTries = useRef(0);
  // what the most recent connect() was for, so an error can be handled in context:
  // "auto"/"reconnect" fail SILENTLY (no scary toast); "join" retries once.
  const attemptRef = useRef({ kind: null, rid: null, retried: false });
  // true once this game is finished — stops auto-reconnect from re-entering a
  // game that's already over (you stay on the results screen until you leave).
  const overRef = useRef(false);
  overRef.current = phase === "over";

  // ── URL routing (segment 2 = room id; the shell owns segment 1 = "/werewolf") ──
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const didInitRef = useRef(false);       // StrictMode double-mount guard for the deep-entry effect
  const popHandlerRef = useRef(() => {}); // fresh-closure mirror for the mount-once popstate effect

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    setConnecting(false);        // any authoritative reply ends the connect loader
    if (msg.type === "error") {
      const m = msg.message || "error";
      const at = attemptRef.current;
      const stale = /invalid token|no such room/i.test(m);
      // A join that hit a transient "no such room" (cold-started backend / a racing
      // stale socket) — retry it once before giving up.
      if (stale && at.kind === "join" && !at.retried) {
        at.retried = true;
        setTimeout(() => { try { connect(`${WW_WS}/${at.rid}/${myId}`, { action: "join", name: playerName, session_token: authUser?.session_token }); } catch {} }, 600);
        return;
      }
      if (stale) {
        // Recoverable: a dead/stale room pointer. Clean up and return to the lobby —
        // SILENTLY for an automatic (re)connect so it never flashes an alarming toast.
        reconnectTries.current = 99;
        try {
          const sid = localStorage.getItem("werewolf_roomId");
          if (sid) localStorage.removeItem(`werewolf_token_${sid}_${myId}`);
          localStorage.removeItem("werewolf_roomId");
        } catch {}
        if (at.kind === "join" || at.kind === "resume") setToast("That game is no longer available");
        attemptRef.current = { kind: null, rid: null, retried: false };
        setScreen("lobby");   // the lobby effect refreshes the games list
        replacePath(buildPath("werewolf"));   // strip a dead room URL (dedup no-op otherwise)
        return;
      }
      setToast(m);
      return;
    }
    if (msg.type === "narrate") {
      setCaption(msg.text || "");
      if (narrateRef.current) playNarration(msg.key, msg.text);
      return;
    }
    const room = msg.room;
    if (!room) return;
    const tok = room.reconnect_tokens?.[myId];
    const rid = room.room_id || roomId;
    if (tok) { try { localStorage.setItem(`werewolf_token_${rid}_${myId}`, tok); localStorage.setItem("werewolf_roomId", rid); } catch {} }
    attemptRef.current = { kind: null, rid: null, retried: false };   // connected OK
    // A finished game is GONE: drop the resume pointer so it can't be resumed/listed
    // or auto-rejoined. This does NOT navigate away — you stay on the results screen
    // (it's driven by roomData) until you choose to leave.
    if (room.status === "over" || room.game?.phase === "over") {
      try { localStorage.removeItem(`werewolf_token_${rid}_${myId}`); localStorage.removeItem("werewolf_roomId"); } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      // Entering the room gives it its URL (server-confirmed, never at click time;
      // waiting + game share it and pushPath's dedup makes repeats no-ops).
      if (rid) pushPath(buildPath("werewolf", rid));
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update") {
      setScreen(inGame ? "game" : "waiting");
    }
  }, [myId, roomId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { connected, connect, send, disconnect } = useSocket(handleMessage);

  const fetchGames = useCallback(() => {
    fetch(`${WW_HTTP}/games`).then((r) => r.json()).then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("ww", myId, "open", g); }).catch(() => {});
    if (authUser && !authUser.guest && authUser.session_token) {
      fetch(`${WW_HTTP}/games/mine`, { headers: { Authorization: `Bearer ${authUser.session_token}` } })
        .then((r) => r.json()).then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("ww", myId, "mine", g); }).catch(() => {});
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  // The game you just finished leaves Active and joins History the moment it
  // ENDS, not when the lobby next loads — see useFinishedGameSync (shared kit).
  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("ww", myId, "mine", rid, setMyGames);
    fetchGames();
  });

  // Mount: do NOT auto-resume a saved game — it snapped you from the lobby into the game
  // on load (jarring). Resume is EXPLICIT via the lobby's Rejoin button. Keep only the
  // disconnect cleanup so an explicit connection tears down on unmount. (A room id IN THE
  // URL is different — that's an explicit destination; see the deep-entry effect below.)
  useEffect(() => {
    return () => disconnect();
  }, []); // eslint-disable-line

  // ── URL deep entry + popstate (this component owns "/werewolf/<ROOMID>") ──
  // Mount with a room in the URL → the EXISTING resume semantics (saved token →
  // reconnect, else join — the invite-link behavior; the stale-error branch above
  // handles failures with a toast + lobby + URL cleanup). Plain /werewolf mounts at
  // the lobby exactly as before.
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "werewolf" && r.room) resume(r.room);
  }, []); // eslint-disable-line
  // Back/Forward while mounted: only our own segment 2 — mode changes unmount us via
  // the shell. Routed through a ref so the mount-once subscription never goes stale.
  popHandlerRef.current = (r) => {
    if (r.game !== "werewolf") return;
    // NB leaveToLobby keeps roomId (WW leave keeps membership), so "same id" is not
    // "already there" — re-enter whenever we're sitting in the lobby.
    if (r.room && (r.room !== roomIdRef.current || screenRef.current === "lobby")) {
      resume(r.room);
    } else if (!r.room) {
      if (screenRef.current === "game" || screenRef.current === "waiting") {
        leaveToLobby();   // WW leave keeps membership; its pushPath dedups after a pop
      } else if (attemptRef.current.kind) {
        // Popping back during a still-connecting attempt: kill it, or the late
        // "reconnected"/"joined" would push the room URL right back.
        attemptRef.current = { kind: null, rid: null, retried: false };
        leaveToLobby();
      }
    }
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2400); return () => clearTimeout(t); } }, [toast]);

  // a connect that never answers must not leave the spinner up forever
  useEffect(() => {
    if (!connecting) return;
    const t = setTimeout(() => {
      setConnecting(false);
      setToast("Still connecting — the server may be waking up. Try again in a moment.");
    }, 15000);
    return () => clearTimeout(t);
  }, [connecting]);
  // clear transient selection when the step changes
  useEffect(() => { setCenterSel([]); setTmSel([]); }, [step, phase]);

  // Seed the host's role picker from the server's chosen deck / recommended default.
  useEffect(() => {
    if (screen === "waiting" && isHost && pickDeck == null && roomData) {
      setPickDeck(roomData.deck || roomData.recommended_deck || null);
    }
  }, [screen, isHost, roomData, pickDeck]);

  // Auto-reconnect if the socket drops while we expect to be in a room (network
  // blip, laptop sleep, or a connection getting replaced). Bounded retries spaced
  // out; resets once a socket re-opens. A manual Reconnect button is also shown.
  useEffect(() => {
    if (connected) { reconnectTries.current = 0; return; }
    if (screen !== "waiting" && screen !== "game") return;
    if (overRef.current) return;   // game's done; don't re-enter it on a drop
    let rid = roomId;
    try { rid = rid || localStorage.getItem("werewolf_roomId"); } catch {}
    if (!rid || reconnectTries.current >= 6) return;
    const t = setTimeout(() => {
      reconnectTries.current += 1;
      let tok = null;
      try { tok = localStorage.getItem(`werewolf_token_${rid}_${myId}`); } catch {}
      attemptRef.current = { kind: "reconnect", rid, retried: true };   // silent on failure
      connect(`${WW_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
    }, 1500);
    return () => clearTimeout(t);
  }, [connected, screen, roomId, myId]); // eslint-disable-line

  // Wall-clock tick for the night/day countdowns (hook must run unconditionally,
  // BEFORE the lobby/waiting early returns — server deadlines are authoritative).
  const now = useNow(phase === "night" || phase === "day");

  // ── lobby actions ──
  const startCreate = () => {
    const rid = roomCode();
    setRoomId(rid);
    try { localStorage.setItem("werewolf_roomId", rid); } catch {}
    attemptRef.current = { kind: "create", rid, retried: true };
    setConnecting(true);
    connect(`${WW_WS}/${rid}/${myId}`, { action: "create", name: playerName });
  };
  const startJoin = (rid) => {
    rid = (rid || "").toUpperCase().trim();
    if (!rid) return;
    setRoomId(rid);
    try { localStorage.setItem("werewolf_roomId", rid); } catch {}
    attemptRef.current = { kind: "join", rid, retried: false };
    setConnecting(true);
    connect(`${WW_WS}/${rid}/${myId}`, { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const resume = (rid) => {
    const tok = localStorage.getItem(`werewolf_token_${rid}_${myId}`);
    setRoomId(rid);
    try { localStorage.setItem("werewolf_roomId", rid); } catch {}
    attemptRef.current = { kind: tok ? "resume" : "join", rid, retried: false };
    setConnecting(true);
    connect(`${WW_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  // Step out to the lobby but STAY a member of the room (socket only drops): the
  // resume pointer + reconnect token are kept so the Resume card / Your Games can
  // bring you right back. Use Cancel (host) to actually dispose of an open game.
  const leaveToLobby = () => {
    disconnect();
    setConnecting(false);
    pushPath(buildPath("werewolf"));   // leave the room URL (dedup no-op when popstate-driven)
    setRoomData(null); setCaption(""); setScreen("lobby"); fetchGames();
  };
  // Force a fresh connection to the current room (manual recovery from a drop).
  const reconnectNow = (ridArg) => {
    let rid = ridArg || roomId;
    try { rid = rid || localStorage.getItem("werewolf_roomId"); } catch {}
    if (!rid) return;
    let tok = null;
    try { tok = localStorage.getItem(`werewolf_token_${rid}_${myId}`); } catch {}
    reconnectTries.current = 0;
    setRoomId(rid);
    attemptRef.current = { kind: tok ? "reconnect" : "join", rid, retried: !tok ? false : true };
    connect(`${WW_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const handleCancel = (id) => {
    const params = new URLSearchParams();
    params.set("player_id", myId);
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    fetch(`${WW_HTTP}/games/${id}/cancel?${params.toString()}`, { method: "POST", headers })
      .then((r) => r.json()).then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("werewolf_roomId") === id) localStorage.removeItem("werewolf_roomId");
          localStorage.removeItem(`werewolf_token_${id}_${myId}`);
        } catch {}
        setToast("Game canceled"); fetchGames();
      }).catch(() => setToast("Could not cancel"));
  };
  const startGame = () => send({ action: "start" });
  const mv = (move) => send({ action: "move", move });
  // host role picker: set the local deck + push it to the room.
  const pushDeck = (deck) => { setPickDeck(deck); send({ action: "set_roles", deck }); };
  const adjustRole = (role, delta) => {
    const base = pickDeck || roomData?.deck || roomData?.recommended_deck || [];
    const counts = deckCounts(base);
    const cur = counts[role] || 0;
    const next = cur + delta;
    if (next < 0 || next > (ROLE_CAPS[role] || 0)) return;
    const deck = base.filter((r) => r !== role);
    for (let i = 0; i < next; i++) deck.push(role);
    pushDeck(deck);
  };
  const toggleNarrate = () => {
    const next = !effNarrate;
    setNarrateOn(next);
    try { localStorage.setItem("werewolf_narrate", next ? "1" : "0"); } catch {}
    if (!next && window.speechSynthesis) { try { window.speechSynthesis.cancel(); } catch {} }
  };

  // ── click handlers on the table ──
  // Only the move-taking roles (seer/robber/troublemaker/drunk) get an "active" step;
  // info roles (minion/mason/insomniac) just look. The lone wolf is handled separately.
  const myActiveStep = phase === "night" && ACTION_ROLES.includes(myDealt) && step === myDealt && !acted[step];
  const loneWolfActive = phase === "night" && step === "werewolves" && game?.is_lone_wolf && game?.lone_wolf_peek == null;
  const clickPlayer = (pid) => {
    if (phase === "day") {
      if (game.locked?.[myId]) { setToast("Unlock to change your vote"); return; }
      mv({ type: "vote", target: pid });
      return;
    }
    if (phase !== "night") return;
    if (step === "seer" && myDealt === "seer" && !acted.seer) {
      if (pid === myId) return;
      mv({ type: "seer_peek_player", target: pid });
    } else if (step === "robber" && myDealt === "robber" && !acted.robber) {
      if (pid === myId) return;
      mv({ type: "robber_swap", target: pid });
    } else if (step === "troublemaker" && myDealt === "troublemaker" && !acted.troublemaker) {
      // Compute from current state, then send OUTSIDE the updater — a setState updater must be
      // pure; a send() inside it can double-fire under StrictMode / a concurrent re-render.
      const next = tmSel.includes(pid) ? tmSel.filter((x) => x !== pid) : [...tmSel, pid];
      if (next.length === 2) { setTmSel([]); mv({ type: "troublemaker_swap", a: next[0], b: next[1] }); }
      else { setTmSel(next); }
    }
  };
  const clickCenter = (idx) => {
    if (phase !== "night") return;
    if (step === "seer" && myDealt === "seer" && !acted.seer) {
      // Compute from current state, then send OUTSIDE the updater (updaters must be pure).
      const next = centerSel.includes(idx) ? centerSel.filter((x) => x !== idx) : [...centerSel, idx];
      if (next.length === 2) { setCenterSel([]); mv({ type: "seer_peek_center", indices: next }); }
      else { setCenterSel(next); }
      return;
    }
    if (step === "drunk" && myDealt === "drunk" && !acted.drunk) { mv({ type: "drunk_swap", center_index: idx }); return; }
    if (loneWolfActive) { mv({ type: "wolf_peek_center", index: idx }); return; }
  };

  // Rules modal — defined once and rendered in the lobby AND the in-game options menu,
  // so "How to Play" is reachable during a game too.
  const wwRulesModal = showRules && (
    <RulesModal title="How to play — Where Wolf?" onClose={() => setShowRules(false)}>
      <WhereWolfRules />
    </RulesModal>
  );

  // ─── Lobby ─────────────────────────────────────────────────────────────────
  // connecting to a room while still on the lobby → spinner, not a lobby flash (CoC)
  if (connecting && screen === "lobby") {
    return (
      <div className="ww" style={{ "--lby-accent": GAME_ACCENTS.wherewolf }}><style>{css}</style>
        <LobbyLoading label="Connecting…" />
      </div>
    );
  }
  if (screen === "lobby") {
    const savedId = (() => { try { return localStorage.getItem("werewolf_roomId"); } catch { return null; } })();
    const savedTok = savedId ? (() => { try { return localStorage.getItem(`werewolf_token_${savedId}_${myId}`); } catch { return null; } })() : null;
    const activeMine = notWaiting(myGames);
    return (
      <div className="ww" style={{ "--lby-accent": GAME_ACCENTS.wherewolf }}><style>{css}</style>
        <LobbyHeader
          onBack={onExit}
          user={<LobbyUser user={authUser || { name: playerName, guest: true }} />}
        />
        <div className="ww-wrap lby-page">
          <div className="lby-page-in">
          <LobbyHero game="wherewolf">
          <LobbyCreateRow
            onCreate={() => setShowCreateModal(true)}
            onJoin={(code) => startJoin(code)}
            onRefresh={fetchGames}
            onRules={() => setShowRules(true)}
            codeMaxLength={4} />
          </LobbyHero>

          {showCreateModal && (
            <CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
              <div className="cm-info">
                <span className="cm-info-line">3–10 players, one device each</span>
                <span className="cm-info-line">Friends join from the lobby or your room code</span>
                <span className="cm-info-line">You'll pick the roles together in the waiting room once everyone's in</span>
              </div>
              <div className="cm-footer">
                <button type="button" className="cm-create"
                  onClick={() => { setShowCreateModal(false); startCreate(); }}>
                  Create Room
                </button>
              </div>
            </CreateModal>
          )}

          {savedId && savedTok && !myGames.some((g) => g.id === savedId) && (
            <div className="lby-card">
              <div className="lby-card-info"><div className="lby-card-title">Game in progress</div><div className="lby-card-meta">{savedId} · resume to rejoin</div></div>
              <div className="lby-card-actions"><LobbyAction onClick={() => resume(savedId)}>Resume</LobbyAction></div>
            </div>
          )}

          {/* THE SHARED GRID, TWO-COLUMN VARIANT, and a tab bar like everyone else's.
              Where Wolf kept a private `.ww-lobby-grid` with its own breakpoint,
              which meant it was the one lobby that stacked BOTH sections raw on a
              phone while the other six collapsed to Open/Active tabs — a different
              product at 390px — and the one whose second heading landed 18px under
              the card above it with 50px below, so the heading read as belonging to
              the list it had just left. `lby-col-open`/`lby-col-active` are what the
              tab bar switches on; History it has never had. */}
          {/* A room you are in but which has NOT started is waiting, not active: it
              is already in Open, with Return and Cancel if you host it. Listing it
              here too offered a "Rejoin" that just dropped you back into the same
              waiting room from a column headed "in progress". */}
          <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
            { key: "open", label: "Open", count: openGames.length || null },
            { key: "active", label: "Active", count: activeMine.length || null },
          ]} />
          <div className={`lby-cols lby-cols-2 tab-${lobbyTab}`}>
            <div className="lby-col-open">
              <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
              {openGames.length === 0 ? (
                <div className="lby-empty">No open games — create one.</div>
              ) : <div className="lby-list">{openGames.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info"><div className="lby-card-title">
                      {g.host_id === myId ? "Your game" : `${g.host_name || "Player"}'s game`}
                      <span className="lby-seats">{g.players ?? 1}/10</span></div>
                    <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div></div>
                  <div className="lby-card-actions">
                    {/* RETURN, then Cancel — the shape every other lobby uses for a
                        room you host. Where Wolf offered only Cancel here, so a host
                        who navigated away could get back into their own waiting room
                        only via the Active column, which is why that column listed
                        rooms that had not started. Giving the row its Return is what
                        lets Active mean "in progress" here as it does everywhere
                        else. */}
                    {g.host_id === myId
                      ? <>
                          <LobbyAction kind="secondary" onClick={() => resume(g.id)}>Return</LobbyAction>
                          <LobbyAction kind="danger" onClick={() => handleCancel(g.id)}>Cancel</LobbyAction>
                        </>
                      : <LobbyAction onClick={() => startJoin(g.id)}>Join</LobbyAction>}
                  </div>
                </div>
              ))}</div>}
            </div>
            <div className="lby-col-active">
              <LobbySectionHd title="Active Games" note={`${activeMine.length} in progress`} />
              {activeMine.length === 0 ? (
                <div className="lby-empty">No games in progress.</div>
              ) : <div className="lby-list">{activeMine.map((g) => (
                <div className="lby-card" key={g.id}>
                  {/* THE ROOM CODE IS THE TITLE. It read "In progress", under a header
                      that already says ACTIVE GAMES and a count that already says "2 in
                      progress" — the most prominent line in the card spent restating the
                      section label three times in one 400px band, leaving the code, the
                      only identifying thing in the row, on the quiet second line. Where
                      Wolf is a hidden-role party game and its `/games/mine` carries no
                      opponent names, so the room itself is what there is to name. */}
                  <div className="lby-card-info"><div className="lby-card-title">
                      Room {g.id}
                      <span className="lby-seats">{g.players ?? 1}/10</span></div>
                    <div className="lby-card-meta">{timeAgo(g.updated_at)}{g.you_are_host ? " · you host" : ""}</div></div>
                  <div className="lby-card-actions">
                    <LobbyAction onClick={() => resume(g.id)}>Rejoin</LobbyAction>
                  </div>
                </div>
              ))}</div>}
            </div>
          </div>
          </div>
        </div>
        {wwRulesModal}
        {toast && <div className="ww-toast">{toast}</div>}
      </div>
    );
  }

  // ─── Waiting room (+ host role picker) ───────────────────────────────────────
  if (screen === "waiting") {
    const players = roomData?.players || {};
    const ids = Object.keys(players);
    const need = ids.length + 3;
    const enough = ids.length >= (roomData?.min_players || 3);
    // Non-hosts see EXACTLY what the host has picked (room.deck) — no recommended
    // fallback, so before the host picks they see nothing (not a misleading default),
    // and they see over-/under-full selections as-is. The host seeds their own picker
    // from the recommended default for convenience.
    const curDeck = (isHost ? (pickDeck || roomData?.deck || roomData?.recommended_deck)
                            : roomData?.deck) || [];
    const counts = deckCounts(curDeck);
    const selected = curDeck.length;
    const deckOk = selected === need;
    return (
      <div className="ww" style={{ "--lby-accent": GAME_ACCENTS.wherewolf }}><style>{css}</style>
        <div className="ww-wrap">
          <div className="ww-top">
            <div className="ww-top-left"><GameMenu onLeave={leaveToLobby} onRules={() => setShowRules(true)} />
              <span className="ww-title">Where Wolf</span></div>
            <div className="ww-row" style={{ gap: 8 }}>
              {!connected && <button className="ww-btn sm" onClick={() => reconnectNow()} title="Reconnect">⟳ Reconnecting…</button>}
              <span className="ww-user">{playerName}</span>
            </div>
          </div>
          <div className="ww-hero"><p className="ww-card-meta">Share this code</p><div className="ww-code">{roomId}</div></div>
          <div className="ww-section">Players ({ids.length}/{roomData?.max_players || 10})</div>
          <div className="ww-players-list">
            {ids.map((pid) => (
              <div className="ww-pl" key={pid}>
                {roomData?.host === pid && <span className="crown">♛</span>}
                <span>{players[pid]}{pid === myId ? " (you)" : ""}</span>
              </div>
            ))}
          </div>

          <div className="ww-section">Roles in the deck
            <span className={`ww-deck-status ${deckOk ? "ok" : "bad"}`}>
              {selected} / {need}{deckOk ? " ✓" : isHost ? (selected < need ? ` · add ${need - selected}` : ` · remove ${selected - need}`) : ""}
            </span>
          </div>
          {isHost ? (
            <>
              <div className="ww-rolepick">
                {PICKABLE.map((role) => {
                  const n = counts[role] || 0;
                  return (
                    <div className="ww-rolepick-row" key={role} title={roleDesc(role)}>
                      <span className="ww-rp-name" style={{ color: roleColor(role) }}>{roleName(role)}</span>
                      <button className="ww-cap-btn" disabled={n <= 0} onClick={() => adjustRole(role, -1)}>−</button>
                      <span className="ww-rp-count">{n}</span>
                      <button className="ww-cap-btn" disabled={n >= (ROLE_CAPS[role] || 0)} onClick={() => adjustRole(role, 1)}>+</button>
                    </div>
                  );
                })}
              </div>
              <div className="ww-row" style={{ gap: 8 }}>
                <button className="ww-btn sm" onClick={() => pushDeck(roomData?.recommended_deck || [])}>Recommended</button>
                <span className="ww-card-meta">3 cards are placed face-down in the center.</span>
              </div>
            </>
          ) : (
            <div className="ww-rolepick readonly">
              {Object.keys(counts).sort().map((role) => (
                <span className="ww-rp-chip" key={role} title={roleDesc(role)} style={{ borderColor: roleColor(role) }}>
                  {roleName(role)}{counts[role] > 1 ? ` ×${counts[role]}` : ""}
                </span>
              ))}
              <div className="ww-card-meta" style={{ width: "100%", marginTop: 4 }}>
                {curDeck.length ? "The host is setting the roles…" : "The host is choosing the roles…"}
              </div>
            </div>
          )}

          <div className="ww-row" style={{ marginTop: 12 }}>
            {isHost
              ? <button className="ww-btn gold" disabled={!enough || !deckOk} onClick={startGame}>
                  {!enough ? `Need ${roomData?.min_players || 3}+ players` : !deckOk ? `Deck ${selected}/${need}` : "Deal & Start"}</button>
              : <span className="ww-card-meta">Waiting for the host to start…</span>}
          </div>
          {wwRulesModal}
          {toast && <div className="ww-toast">{toast}</div>}
        </div>
      </div>
    );
  }

  // ─── Game ────────────────────────────────────────────────────────────────────
  const players = game?.players || {};
  const dayActive = phase === "day";
  const voteLeft = dayActive && game?.vote_deadline ? game.vote_deadline - now : null;
  const stepLeft = phase === "night" && game?.step_deadline ? game.step_deadline - now : null;

  // banner + sub-prompt
  let banner = caption;
  let subPrompt = "";
  if (phase === "dealing") {
    banner = "This is your card. Memorize it.";
    subPrompt = players[myId]?.ready ? "Waiting for everyone to be ready…" : "Tap Ready when you have it.";
  } else if (phase === "night") {
    if (!caption) banner = "Night falls…";
    if (myActiveStep) {
      if (step === "seer") subPrompt = centerSel.length === 1 ? "Pick one more center card…" : "Tap a player's card, or two center cards.";
      else if (step === "robber") subPrompt = "Tap a player to rob and see your new card.";
      else if (step === "troublemaker") subPrompt = tmSel.length === 1 ? "Tap one more player…" : "Tap two players to swap their cards.";
      else if (step === "drunk") subPrompt = "Tap a center card to swap with — you won't see your new card.";
    } else if (loneWolfActive) {
      subPrompt = "You are the lone wolf — you may tap one center card to peek.";
    } else if (step === "werewolves" && myDealt === "werewolf") {
      subPrompt = "You are a Werewolf. Note the other werewolves.";
    } else if (step === "minion" && myDealt === "minion") {
      subPrompt = "You are the Minion. The werewolves are revealed to you.";
    } else if (step === "masons" && myDealt === "mason") {
      subPrompt = "You are a Mason. Your fellow Masons are revealed.";
    } else if (step === "insomniac" && myDealt === "insomniac") {
      subPrompt = "You wake and check your card.";
    } else {
      subPrompt = "Keep your eyes closed.";
    }
  } else if (phase === "day") {
    banner = "Daybreak — who is the werewolf?";
    subPrompt = game?.locked?.[myId] ? "Vote locked. Tap Unlock to change." : "Tap a player to vote. Tap Lock when sure.";
  }

  const seatNode = (pid, i) => {
    const rel = ((i - myIdx) + order.length) % order.length;
    const pos = seatXY(rel, order.length);
    const pdata = players[pid] || {};
    const faceUp = pdata.card != null;
    const isMe = pid === myId;
    const voteCount = phase === "over" ? (game.vote_tally?.[pid] || 0) : null;
    const clickable =
      (phase === "day" && !game.locked?.[myId]) ||
      (phase === "night" && myActiveStep && step === "seer" && !isMe) ||
      (phase === "night" && myActiveStep && step === "robber" && !isMe) ||
      (phase === "night" && myActiveStep && step === "troublemaker" && !isMe);   // swaps two OTHERS
    const selected = tmSel.includes(pid);
    const revealed = phase === "over" && (game.deaths || []).includes(pid);
    return (
      <div className={`ww-seat${isMe ? " me" : ""}`} key={pid} style={{ left: pos.x + "%", top: pos.y + "%" }}>
        <div
          data-pid={pid}
          className={`ww-pcard${faceUp ? "" : " back"}${clickable ? " clickable" : ""}${selected ? " selected" : ""}${revealed ? " revealed" : ""}`}
          style={faceUp ? { borderColor: roleColor(pdata.card), background: "#1a1622" } : undefined}
          onClick={clickable ? () => clickPlayer(pid) : undefined}
        >
          {faceUp ? cardLabel(pdata.card) : ""}
          {phase === "dealing" && pdata.ready && <span className="ww-ready">✓</span>}
          {dayActive && game.locked?.[pid] && <span className="ww-lock">🔒</span>}
          {phase === "over" && voteCount > 0 && <span className="ww-badge">{voteCount}</span>}
        </div>
        <span className="seat-name">{roomData?.players?.[pid] || pdata.name}{isMe ? " (you)" : ""}{roomData?.host === pid ? " ♛" : ""}</span>
      </div>
    );
  };

  // vote arrows (square table → simple unit viewBox, no DOM measuring needed)
  const voteEntries = dayActive ? Object.entries(game.votes || {}) : [];
  const seatOf = (pid) => seatXY(((order.indexOf(pid) - myIdx) + order.length) % order.length, order.length);
  const arrows = voteEntries.map(([voter, target]) => {
    const vi = order.indexOf(voter), ti = order.indexOf(target);
    if (vi < 0 || ti < 0 || voter === target) return null;
    const a = seatOf(voter), b = seatOf(target);
    return { id: voter, x1: a.x, y1: a.y, x2: b.x, y2: b.y, me: voter === myId };
  }).filter(Boolean);
  // a self-vote shows a little loop curling back to the voter's own card
  const selfArrows = voteEntries.map(([voter, target]) => {
    if (voter !== target || order.indexOf(voter) < 0) return null;
    const p = seatOf(voter);
    return { id: voter, d: selfLoopPath(p.x, p.y), me: voter === myId };
  }).filter(Boolean);

  return (
    <div className="ww" style={{ "--lby-accent": GAME_ACCENTS.wherewolf }}><style>{css}</style>
      <div className="ww-wrap">
        <div className="ww-top">
          <div className="ww-top-left"><GameMenu onLeave={leaveToLobby} onRules={() => setShowRules(true)} />
            <span className="ww-title">Where Wolf</span></div>
          <div className="ww-row" style={{ gap: 8 }}>
            {!connected && <button className="ww-btn sm" onClick={() => reconnectNow()} title="Reconnect">⟳ Reconnecting…</button>}
            <button className="ww-btn ghost sm" title="Narration voice" onClick={toggleNarrate}>{effNarrate ? "🔊" : "🔇"}</button>
            {myDealt && phase !== "over" && <span className="ww-you">You: <b>{roleName(myDealt)}</b></span>}
          </div>
        </div>

        {phase === "over" ? (
          <WinScreen game={game} order={order} myIdx={myIdx} players={players} roomData={roomData} isMobile={isMobile} onExit={leaveToLobby} />
        ) : (
          <div className="ww-table-wrap">
            <div className="ww-banner">{banner}</div>
            <div className="ww-sub">{subPrompt}</div>

            <div className={`ww-table${phase === "night" ? " night" : ""}`} style={cardVars(order.length, isMobile)}>
              <svg className="ww-arrows" viewBox="0 0 100 100" preserveAspectRatio="none">
                <defs>
                  <marker id="ww-ah" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto">
                    <path d="M0,0 L5,2.5 L0,5 Z" fill="#e0c14c" />
                  </marker>
                  <marker id="ww-ah-me" markerWidth="5" markerHeight="5" refX="4" refY="2.5" orient="auto">
                    <path d="M0,0 L5,2.5 L0,5 Z" fill="#e0655a" />
                  </marker>
                </defs>
                {arrows.map((ar) => (
                  <line key={ar.id} x1={ar.x1} y1={ar.y1} x2={ar.x2} y2={ar.y2}
                    stroke={ar.me ? "#e0655a" : "#e0c14c"} strokeWidth="0.7" strokeOpacity="0.85"
                    markerEnd={ar.me ? "url(#ww-ah-me)" : "url(#ww-ah)"} />
                ))}
                {selfArrows.map((s) => (
                  <path key={"self-" + s.id} d={s.d} fill="none"
                    stroke={s.me ? "#e0655a" : "#e0c14c"} strokeWidth="0.7" strokeOpacity="0.85"
                    markerEnd={s.me ? "url(#ww-ah-me)" : "url(#ww-ah)"} />
                ))}
              </svg>

              {/* center: 3 cards + token row */}
              <div className="ww-center">
                <div className="ww-center-cards">
                  {(game?.center || []).map((c, i) => {
                    const up = c != null;
                    const sel = centerSel.includes(i);
                    const clickable = phase === "night" && (
                      (myActiveStep && (step === "seer" || step === "drunk")) || loneWolfActive);
                    return (
                      <div key={i} data-center-idx={i}
                        className={`ww-ccard${up ? " up" : ""}${clickable ? " clickable" : ""}${sel ? " selected" : ""}`}
                        onClick={clickable ? () => clickCenter(i) : undefined}>
                        {up ? cardLabel(c) : ""}
                      </div>
                    );
                  })}
                </div>
                <div className="ww-tokens">
                  {/* game.deck = public role multiset (== the token row). Render the
                      public letter + hover/tap for what the role does. Falls back to
                      the legacy roles_in_play letters if an old payload lacks deck. */}
                  {(game?.deck ? [...game.deck].sort() : (game?.roles_in_play || [])).map((r, i) => {
                    const known = !!ROLE_META[r];
                    return (
                      <span className="ww-token" key={i}
                        title={known ? `${roleName(r)} — ${roleDesc(r)}` : r}
                        onClick={known ? () => setTokenInfo((c) => (c === r ? null : r)) : undefined}>
                        {known ? tokenLetter(r) : r}
                      </span>
                    );
                  })}
                </div>
                {tokenInfo && (
                  <div className="ww-token-info" onClick={() => setTokenInfo(null)}>
                    <b style={{ color: roleColor(tokenInfo) }}>{roleName(tokenInfo)}</b> — {roleDesc(tokenInfo)}
                  </div>
                )}
              </div>

              {order.map((pid, i) => seatNode(pid, i))}
            </div>

            <div className="ww-actions">
              {phase === "dealing" && !players[myId]?.ready &&
                <button className="ww-btn gold" onClick={() => mv({ type: "ready" })}>Ready</button>}
              {phase === "dealing" && players[myId]?.ready &&
                <span className="ww-card-meta">Ready ✓ — waiting for {order.filter((p) => !players[p]?.ready).length} more…</span>}

              {((myActiveStep && step !== "drunk") || loneWolfActive) &&
                <button className="ww-btn sm" onClick={() => mv({ type: "skip" })}>Skip</button>}
              {phase === "night" && stepLeft != null && (myActiveStep || loneWolfActive) &&
                <span className="ww-timer">{Math.ceil(stepLeft)}s</span>}

              {dayActive && (
                <>
                  <span className="ww-timer">{fmtTime(voteLeft)}</span>
                  {game.votes?.[myId] && (game.locked?.[myId]
                    ? <button className="ww-btn" onClick={() => mv({ type: "unlock_vote" })}>Unlock</button>
                    : <button className="ww-btn gold" onClick={() => mv({ type: "lock_vote" })}>Lock vote</button>)}
                </>
              )}
            </div>
          </div>
        )}
        {wwRulesModal}
        {toast && <div className="ww-toast">{toast}</div>}
      </div>
    </div>
  );
}

function WinScreen({ game, order, myIdx, players, roomData, isMobile, onExit }) {
  const teams = game.winning_teams || [];
  const deaths = game.deaths || [];
  const winners = game.winners || [];
  const klass = teams.includes("village") ? "villagers"
    : teams.includes("werewolf") ? "wolves"
    : teams.includes("tanner") ? "tanner"
    : teams.includes("minion") ? "wolves" : "neutral";
  const deathLine = deaths.length
    ? "Died: " + deaths.map((p) => `${roomData?.players?.[p] || players[p]?.name || p} (${roleName(game.players?.[p]?.card)})`).join(", ")
    : "No one died.";
  return (
    <div className="ww-table-wrap">
      <div className={`ww-win ${klass}`}>
        <h2>{game.headline || "Game over"}</h2>
        <p className="ww-card-meta">{deathLine}</p>
      </div>
      <div className="ww-table" style={cardVars(order.length, isMobile)}>
        <div className="ww-center">
          <div className="ww-card-meta">Center cards</div>
          <div className="ww-center-cards">
            {(game.center || []).map((c, i) => (
              <div key={i} className="ww-ccard up" style={{ borderColor: roleColor(c) }}>{cardLabel(c)}</div>
            ))}
          </div>
        </div>
        {order.map((pid, i) => {
          const rel = ((i - myIdx) + order.length) % order.length;
          const pos = seatXY(rel, order.length);
          const pdata = players[pid] || {};
          const isDead = deaths.includes(pid);
          const votes = game.vote_tally?.[pid] || 0;
          const won = winners.includes(pid);
          return (
            <div className={`ww-seat${pid === order[myIdx] ? " me" : ""}`} key={pid} style={{ left: pos.x + "%", top: pos.y + "%" }}>
              <div className={`ww-pcard${isDead ? " revealed" : ""}`} style={{ borderColor: roleColor(pdata.card), background: "#1a1622" }}>
                {cardLabel(pdata.card)}
                {votes > 0 && <span className="ww-badge">{votes}</span>}
                {isDead && <span className="ww-dead">☠</span>}
              </div>
              <span className="seat-name">{roomData?.players?.[pid] || pdata.name} <span className={won ? "ww-won" : "ww-lost"}>{won ? "✓" : "✗"}</span></span>
            </div>
          );
        })}
      </div>
      <div className="ww-row"><button className="ww-btn gold" onClick={onExit}>Back to lobby</button></div>
    </div>
  );
}
