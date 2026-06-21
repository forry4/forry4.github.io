import { useState, useEffect, useRef, useCallback } from "react";
import { baseCss } from "../../shared/theme.js";

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

// On the small cards, Cinzel renders as wide caps, so the longer role names don't
// fit one line. Insert a soft break opportunity (<wbr>) at a clean syllable so a
// too-wide name wraps tidily (TROUBLE/MAKER) instead of overflowing; names that do
// fit one line ignore the hint. Index = where to split.
const CARD_WBR = { werewolf: 4, villager: 4, troublemaker: 7, insomniac: 5, doppelganger: 6 };
const cardLabel = (r) => {
  const n = roleName(r), at = CARD_WBR[r];
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
const css = baseCss + `
.ww{min-height:100vh;background:radial-gradient(120% 90% at 50% -10%,#241a2e 0%,#0d0b12 60%);color:var(--text)}
.ww *,.ww *::before,.ww *::after{box-sizing:border-box}
.ww-wrap{max-width:1000px;margin:0 auto;padding:14px 14px 40px;display:flex;flex-direction:column;gap:14px}
.ww-top{display:flex;align-items:center;justify-content:space-between;gap:10px}
.ww-top-left{display:flex;align-items:center;gap:10px;min-width:0}
.ww-title{font-family:Cinzel,serif;font-weight:700;color:var(--gold-light);letter-spacing:.5px}
.ww-user{color:var(--text-dim);font-size:13px}
.ww-btn{font-family:Cinzel,serif;font-size:14px;border:1px solid var(--border);background:var(--surface2);color:var(--text);
  padding:9px 16px;border-radius:var(--radius);cursor:pointer;transition:all .15s}
.ww-btn:hover{border-color:var(--gold);color:var(--gold-light)}
.ww-btn.gold{background:linear-gradient(180deg,#7a3f4a,#5a2630);border-color:#9a4a58;color:#f2dcc4}
.ww-btn.gold:hover{filter:brightness(1.12)}
.ww-btn.sm{padding:6px 11px;font-size:12px}
.ww-btn.ghost{background:transparent;border-color:transparent;color:var(--text-dim)}
.ww-btn.ghost:hover{color:var(--gold-light)}
.ww-btn:disabled{opacity:.4;cursor:not-allowed}
.ww-input{font-family:Cinzel,serif;letter-spacing:3px;text-transform:uppercase;background:var(--surface);border:1px solid var(--border);
  color:var(--text);padding:9px 12px;border-radius:var(--radius);width:120px;text-align:center}
.ww-hero{text-align:center;padding:8px 0 4px}
.ww-hero h1{font-family:Cinzel,serif;font-size:30px;color:var(--gold-light)}
.ww-hero p{color:var(--text-dim)}
.ww-row{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:center}
.ww-section{font-family:Cinzel,serif;color:var(--gold);font-size:14px;margin-top:10px;border-bottom:1px solid var(--border);padding-bottom:4px}
.ww-card{display:flex;align-items:center;justify-content:space-between;gap:10px;background:var(--surface);border:1px solid var(--border);
  border-radius:var(--radius);padding:10px 14px}
.ww-card-title{font-family:Cinzel,serif}
.ww-card-meta{color:var(--text-dim);font-size:12px}
.ww-empty{color:var(--text-muted);text-align:center;padding:20px}
.ww-toast{position:fixed;bottom:18px;left:50%;transform:translateX(-50%);background:#2a1c20;border:1px solid var(--gold);
  color:var(--gold-light);padding:10px 18px;border-radius:var(--radius);z-index:50;font-size:14px}

/* waiting room */
.ww-code{font-family:Cinzel,serif;font-size:40px;letter-spacing:8px;color:var(--gold-light);text-align:center}
.ww-players-list{display:flex;flex-direction:column;gap:6px}
.ww-pl{display:flex;align-items:center;gap:8px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:8px 12px}
.ww-pl .crown{color:var(--gold)}

/* the table */
.ww-table-wrap{display:flex;flex-direction:column;align-items:center;gap:8px}
.ww-banner{min-height:30px;text-align:center;font-family:Cinzel,serif;color:var(--gold-light);font-size:16px}
.ww-sub{text-align:center;color:var(--text-dim);font-size:13px;min-height:18px}
.ww-table{position:relative;width:min(92vw,68vh);aspect-ratio:1;margin:4px auto}
.ww-table.night{filter:saturate(.5) brightness(.62)}
.ww-arrows{position:absolute;inset:0;width:100%;height:100%;pointer-events:none;z-index:3}
.ww-seat{position:absolute;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:3px;z-index:2}
.ww-seat .seat-name{font-size:11px;color:var(--text-dim);max-width:74px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ww-seat.me .seat-name{color:var(--gold-light)}
.ww-pcard{width:var(--pcw,72px);height:var(--pch,94px);border-radius:8px;border:2px solid var(--border);display:flex;align-items:center;justify-content:center;
  text-align:center;font-family:Cinzel,serif;font-size:var(--pcf,11px);line-height:1.1;padding:3px;overflow-wrap:break-word;background:#1a1622;position:relative;transition:all .15s}
.ww-pcard.back{background:repeating-linear-gradient(45deg,#241a2e,#241a2e 6px,#2c2038 6px,#2c2038 12px);color:transparent}
.ww-pcard.back::after{content:"?";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#54486a;font-size:24px}
.ww-pcard.clickable{cursor:pointer;border-color:var(--gold)}
.ww-pcard.clickable:hover{box-shadow:0 0 0 2px var(--gold-light);transform:translateY(-2px)}
.ww-pcard.selected{box-shadow:0 0 0 3px var(--gold-light)}
.ww-pcard.revealed{box-shadow:0 0 0 3px #e0c14c}
.ww-badge{position:absolute;top:-9px;right:-9px;background:var(--gold);color:#1a1410;border-radius:999px;min-width:20px;height:20px;
  display:flex;align-items:center;justify-content:center;font-size:12px;font-weight:700;padding:0 5px}
.ww-lock{position:absolute;top:-9px;left:-9px;font-size:14px}
.ww-ready{position:absolute;bottom:-8px;font-size:13px}

/* center: the 3 face-down cards + the token row */
.ww-center{position:absolute;top:42%;left:50%;transform:translate(-50%,-50%);display:flex;flex-direction:column;align-items:center;gap:8px;z-index:2}
.ww-center-cards{display:flex;gap:8px}
.ww-ccard{width:62px;height:82px;border-radius:7px;border:2px solid var(--border);background:repeating-linear-gradient(45deg,#241a2e,#241a2e 6px,#2c2038 6px,#2c2038 12px);
  display:flex;align-items:center;justify-content:center;text-align:center;font-family:Cinzel,serif;font-size:11px;line-height:1.1;padding:3px;overflow-wrap:break-word;color:transparent;position:relative}
.ww-ccard::after{content:"";position:absolute;inset:0;display:flex;align-items:center;justify-content:center;color:#54486a;font-size:18px}
.ww-ccard.up{background:#1a1622;color:var(--text)}
.ww-ccard.clickable{cursor:pointer;border-color:var(--gold)}
.ww-ccard.clickable:hover{box-shadow:0 0 0 2px var(--gold-light)}
.ww-ccard.selected{box-shadow:0 0 0 3px var(--gold-light)}
.ww-tokens{display:flex;gap:5px;flex-wrap:wrap;justify-content:center;max-width:230px}
.ww-token{width:26px;height:26px;border-radius:999px;border:1px solid #6a5a3a;background:#2a2418;color:var(--gold-light);
  display:flex;align-items:center;justify-content:center;font-family:Cinzel,serif;font-size:11px;font-weight:700;cursor:pointer;user-select:none}
.ww-token:hover{border-color:var(--gold);color:#fff}
.ww-token-info{max-width:280px;margin-top:2px;text-align:center;font-family:Crimson Pro,serif;font-size:12px;line-height:1.25;
  color:var(--text-dim);background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:5px 9px;cursor:pointer}

/* action bar */
.ww-actions{display:flex;gap:10px;flex-wrap:wrap;align-items:center;justify-content:center;min-height:44px}
.ww-you{font-size:13px;color:var(--text-dim)}
.ww-you b{color:var(--gold-light)}
.ww-timer{font-family:Cinzel,serif;font-size:18px;color:var(--gold-light)}

/* win screen */
.ww-win{text-align:center;padding:14px}
.ww-win h2{font-family:Cinzel,serif;font-size:30px;margin-bottom:6px}
.ww-win.villagers h2{color:#7ed07a}
.ww-win.wolves h2{color:#e0655a}
.ww-win.tanner h2{color:#d6a24a}
.ww-win.neutral h2{color:var(--gold-light)}
.ww-dead{position:absolute;top:-9px;left:-9px;font-size:14px}
.ww-won{color:#7ed07a;font-weight:700}
.ww-lost{color:var(--text-muted)}

/* host role picker */
.ww-deck-status{font-family:Crimson Pro,serif;font-size:13px;margin-left:8px}
.ww-deck-status.ok{color:#7ed07a}
.ww-deck-status.bad{color:#d99}
.ww-rolepick{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:6px 10px;margin:4px 0}
.ww-rolepick.readonly{display:flex;flex-wrap:wrap;gap:6px}
.ww-rolepick-row{display:flex;align-items:center;gap:6px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);padding:4px 8px}
.ww-rp-name{flex:1;font-family:Cinzel,serif;font-size:13px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.ww-rp-count{min-width:14px;text-align:center;font-family:Cinzel,serif}
.ww-cap-btn{width:24px;height:24px;border-radius:6px;border:1px solid var(--border);background:var(--surface3);color:var(--text);cursor:pointer;font-size:15px;line-height:1}
.ww-cap-btn:hover:not(:disabled){border-color:var(--gold);color:var(--gold-light)}
.ww-cap-btn:disabled{opacity:.35;cursor:not-allowed}
.ww-rp-chip{border:1px solid var(--border);border-radius:999px;padding:3px 9px;font-size:12px;font-family:Cinzel,serif}

/* ── Phone: use the whole screen — the table becomes a TALL ellipse so YOU sit at
   the very bottom and everyone else rings the edges; cards shrink (see cardVars). ── */
@media(max-width:600px){
  .ww-wrap{min-height:100dvh;padding:8px 6px 6px;gap:8px}
  .ww-banner{font-size:14px;min-height:24px}
  .ww-sub{font-size:12px;min-height:16px}
  /* the game's table area fills the space between the sub-prompt and the action bar */
  .ww-table-wrap{flex:1;min-height:0;width:100%;gap:4px}
  .ww-table{width:100%;height:auto;flex:1;min-height:0;aspect-ratio:auto;margin:0}
  /* center cluster sits a bit higher so the tall ellipse stays balanced */
  .ww-center{top:40%;gap:5px}
  .ww-ccard{width:50px;height:66px;font-size:10px}
  .ww-tokens{gap:4px;max-width:96vw}
  .ww-token{width:23px;height:23px;font-size:10px}
  .ww-seat .seat-name{font-size:10px;max-width:64px}
  .ww-actions{min-height:38px;gap:8px}
}
`;

// ─── Component ───────────────────────────────────────────────────────────────
export default function WhereWolf({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");      // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState([]);
  const [myGames, setMyGames] = useState([]);
  const [joinCode, setJoinCode] = useState("");
  const [toast, setToast] = useState("");

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

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") {
      const m = msg.message || "error";
      const at = attemptRef.current;
      const stale = /invalid token|no such room/i.test(m);
      // A join that hit a transient "no such room" (cold-started backend / a racing
      // stale socket) — retry it once before giving up.
      if (stale && at.kind === "join" && !at.retried) {
        at.retried = true;
        setTimeout(() => { try { connect(`${WW_WS}/${at.rid}/${myId}`, { action: "join", name: playerName }); } catch {} }, 600);
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
        return;
      }
      setToast(m);
      return;
    }
    if (msg.type === "narrate") {
      setCaption(msg.text || "");
      if (narrateRef.current && typeof window !== "undefined" && window.speechSynthesis && msg.text) {
        try {
          window.speechSynthesis.cancel();
          window.speechSynthesis.speak(new SpeechSynthesisUtterance(msg.text));
        } catch {}
      }
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
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update") {
      setScreen(inGame ? "game" : "waiting");
    }
  }, [myId, roomId]);

  const { connected, connect, send, disconnect } = useSocket(handleMessage);

  const fetchGames = useCallback(() => {
    fetch(`${WW_HTTP}/games`).then((r) => r.json()).then((d) => setOpenGames(d.games || [])).catch(() => {});
    if (authUser && !authUser.guest && authUser.session_token) {
      fetch(`${WW_HTTP}/games/mine`, { headers: { Authorization: `Bearer ${authUser.session_token}` } })
        .then((r) => r.json()).then((d) => setMyGames(d.games || [])).catch(() => {});
    }
  }, [authUser]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  // auto-resume a saved room on mount
  useEffect(() => {
    try {
      const rid = localStorage.getItem("werewolf_roomId");
      const tok = rid ? localStorage.getItem(`werewolf_token_${rid}_${myId}`) : null;
      if (rid && tok) {
        setRoomId(rid);
        attemptRef.current = { kind: "auto", rid, retried: true };   // silent on failure
        connect(`${WW_WS}/${rid}/${myId}`, { action: "reconnect", token: tok });
      }
    } catch {}
    return () => disconnect();
  }, []); // eslint-disable-line

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2400); return () => clearTimeout(t); } }, [toast]);
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
      connect(`${WW_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName });
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
    connect(`${WW_WS}/${rid}/${myId}`, { action: "create", name: playerName });
  };
  const startJoin = (rid) => {
    rid = (rid || "").toUpperCase().trim();
    if (!rid) return;
    setRoomId(rid);
    try { localStorage.setItem("werewolf_roomId", rid); } catch {}
    attemptRef.current = { kind: "join", rid, retried: false };
    connect(`${WW_WS}/${rid}/${myId}`, { action: "join", name: playerName });
  };
  const resume = (rid) => {
    const tok = localStorage.getItem(`werewolf_token_${rid}_${myId}`);
    setRoomId(rid);
    try { localStorage.setItem("werewolf_roomId", rid); } catch {}
    attemptRef.current = { kind: tok ? "resume" : "join", rid, retried: false };
    connect(`${WW_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName });
  };
  // Step out to the lobby but STAY a member of the room (socket only drops): the
  // resume pointer + reconnect token are kept so the Resume card / Your Games can
  // bring you right back. Use Cancel (host) to actually dispose of an open game.
  const leaveToLobby = () => {
    disconnect();
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
    connect(`${WW_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName });
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
      setTmSel((sel) => {
        const next = sel.includes(pid) ? sel.filter((x) => x !== pid) : [...sel, pid];
        if (next.length === 2) { mv({ type: "troublemaker_swap", a: next[0], b: next[1] }); return []; }
        return next;
      });
    }
  };
  const clickCenter = (idx) => {
    if (phase !== "night") return;
    if (step === "seer" && myDealt === "seer" && !acted.seer) {
      setCenterSel((sel) => {
        const next = sel.includes(idx) ? sel.filter((x) => x !== idx) : [...sel, idx];
        if (next.length === 2) { mv({ type: "seer_peek_center", indices: next }); return []; }
        return next;
      });
      return;
    }
    if (step === "drunk" && myDealt === "drunk" && !acted.drunk) { mv({ type: "drunk_swap", center_index: idx }); return; }
    if (loneWolfActive) { mv({ type: "wolf_peek_center", index: idx }); return; }
  };

  // ─── Lobby ─────────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    const savedId = (() => { try { return localStorage.getItem("werewolf_roomId"); } catch { return null; } })();
    const savedTok = savedId ? (() => { try { return localStorage.getItem(`werewolf_token_${savedId}_${myId}`); } catch { return null; } })() : null;
    return (
      <div className="ww"><style>{css}</style>
        <div className="ww-wrap">
          <div className="ww-top">
            <div className="ww-top-left">
              <button className="ww-btn ghost sm" onClick={onExit}>← Forrest Games</button>
              <span className="ww-title">Where Wolf?</span>
            </div>
            <span className="ww-user">{playerName}</span>
          </div>
          <div className="ww-hero">
            <h1>Where Wolf?</h1>
            <p>A night of deception. One of you is not who they seem.</p>
            <p className="ww-card-meta">3–10 players · one device each</p>
          </div>

          <div className="ww-row">
            <button className="ww-btn gold" onClick={startCreate}>+ New Game</button>
            <input className="ww-input" placeholder="CODE" value={joinCode} maxLength={4}
              onChange={(e) => setJoinCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && startJoin(joinCode)} />
            <button className="ww-btn" onClick={() => startJoin(joinCode)}>Join</button>
            <button className="ww-btn ghost sm" onClick={fetchGames}>↻</button>
          </div>

          {savedId && savedTok && !myGames.some((g) => g.id === savedId) && (
            <>
              <div className="ww-section">Resume</div>
              <div className="ww-card">
                <div><div className="ww-card-title">Game in progress</div><div className="ww-card-meta">{savedId}</div></div>
                <button className="ww-btn gold sm" onClick={() => resume(savedId)}>Resume</button>
              </div>
            </>
          )}

          {myGames.length > 0 && (
            <>
              <div className="ww-section">Your Games</div>
              {myGames.map((g) => (
                <div className="ww-card" key={g.id}>
                  <div><div className="ww-card-title">{g.status === "open" ? "Waiting room" : "In progress"}</div>
                    <div className="ww-card-meta">{g.id} · {g.players} player{g.players === 1 ? "" : "s"}{g.you_are_host ? " · host" : ""}</div></div>
                  <div className="ww-row" style={{ gap: 6 }}>
                    <button className="ww-btn gold sm" onClick={() => resume(g.id)}>Rejoin</button>
                    {g.you_are_host && g.status === "open" && <button className="ww-btn ghost sm" onClick={() => handleCancel(g.id)}>Cancel</button>}
                  </div>
                </div>
              ))}
            </>
          )}

          {openGames.length > 0 && (
            <>
              <div className="ww-section">Open Games</div>
              {openGames.map((g) => (
                <div className="ww-card" key={g.id}>
                  <div><div className="ww-card-title">{g.host_name || "Game"}</div>
                    <div className="ww-card-meta">{g.id} · {g.players} player{g.players === 1 ? "" : "s"}</div></div>
                  {g.host_id === myId
                    ? <button className="ww-btn ghost sm" onClick={() => handleCancel(g.id)}>Cancel</button>
                    : <button className="ww-btn sm" onClick={() => startJoin(g.id)}>Join</button>}
                </div>
              ))}
            </>
          )}
          {toast && <div className="ww-toast">{toast}</div>}
        </div>
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
      <div className="ww"><style>{css}</style>
        <div className="ww-wrap">
          <div className="ww-top">
            <div className="ww-top-left"><button className="ww-btn ghost sm" onClick={leaveToLobby}>← Leave</button>
              <span className="ww-title">Where Wolf?</span></div>
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
      (phase === "night" && myActiveStep && step === "troublemaker");
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
  const arrows = dayActive ? Object.entries(game.votes || {}).map(([voter, target]) => {
    const vi = order.indexOf(voter), ti = order.indexOf(target);
    if (vi < 0 || ti < 0 || voter === target) return null;
    const a = seatXY(((vi - myIdx) + order.length) % order.length, order.length);
    const b = seatXY(((ti - myIdx) + order.length) % order.length, order.length);
    return { id: voter, x1: a.x, y1: a.y, x2: b.x, y2: b.y, me: voter === myId };
  }).filter(Boolean) : [];

  return (
    <div className="ww"><style>{css}</style>
      <div className="ww-wrap">
        <div className="ww-top">
          <div className="ww-top-left"><button className="ww-btn ghost sm" onClick={leaveToLobby}>← Leave</button>
            <span className="ww-title">Where Wolf?</span></div>
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
