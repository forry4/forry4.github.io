import { useState, useEffect, useRef, useCallback } from "react";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const COC_WS = WS_RAW.replace(/\/ws$/, "/coc/ws");
const COC_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/coc");

const TILE_HEX = {
  burgundy: "#1f4d2b",   // castle  -> dark green
  blue: "#3d6ea5",       // ship
  gray: "#6b6f76",       // mine
  green: "#8cc873",      // livestock -> light green
  beige: "#c4a86a",      // building
  yellow: "#ffd21a",     // monastery -> bright yellow
};
const GOODS_HEX = {
  amber: "#e0a526", rose: "#d6678b", jade: "#3fae8e",
  cobalt: "#3b6fd0", plum: "#8a5cc0", rust: "#c0552f",
};
const TYPE_LABEL = {
  castle: "Castle", ship: "Ship", mine: "Mine",
  livestock: "Livestock", building: "Building", monastery: "Monastery",
};
// Two-letter building codes so tiles are identifiable without mousing over.
const BUILDING_ABBR = {
  market: "Mk", carpenter: "Cp", church: "Ch", warehouse: "Wh",
  boarding: "Bo", bank: "Bk", townhall: "TH", watchtower: "WT",
};
const BUILDING_DESC = {
  market: "Market — take a ship or livestock tile from a depot.",
  carpenter: "Carpenter's Workshop — take a building tile from a depot.",
  church: "Church — take a mine, monastery, or castle tile from a depot.",
  warehouse: "Warehouse — immediately sell a goods type.",
  boarding: "Boarding House — gain 4 workers.",
  bank: "Bank — gain 2 silver.",
  townhall: "Town Hall — immediately place an additional tile.",
  watchtower: "Watchtower — score 4 VP.",
};
// Short on-tile label: monastery number, building code, livestock animal+count.
function tileGlyph(t) {
  if (!t) return "";
  if (t.type === "monastery") return String(t.effect_id);
  if (t.type === "building") return BUILDING_ABBR[t.building] || "B";
  if (t.type === "livestock") return (t.animal?.[0]?.toUpperCase() || "L") + t.count;
  return "";
}
// Full mouse-over description of what a tile does.
function tileDesc(t, board) {
  if (!t) return "";
  if (t.kind === "goods") {
    const n = board ? board.goods_colors.indexOf(t.color) + 1 : "?";
    return `Goods — sell with die ${n} to gain 1 silver and 2 VP per good (2-player).`;
  }
  switch (t.type) {
    case "castle": return "Castle — when placed, take an immediate bonus action (a die of your choice).";
    case "ship": return "Ship — when placed, take all goods from one depot and advance the turn order.";
    case "mine": return "Mine — gain 1 silver at the end of each phase.";
    case "livestock": return `Livestock (${t.animal} ×${t.count}) — score VP for the animals; same-type animals in a pasture re-score.`;
    case "building": return BUILDING_DESC[t.building] || "Building.";
    case "monastery": {
      const d = board?.monastery_meta?.[t.effect_id];
      return `Monastery #${t.effect_id}${d ? " — " + d : " — special effect."}`;
    }
    default: return TYPE_LABEL[t.type] || "Tile";
  }
}

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }

// ─── Minimal WebSocket hook ──────────────────────────────────────────────────
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

// ─── Styles ───────────────────────────────────────────────────────────────-
const css = `
@import url('https://fonts.googleapis.com/css2?family=Cinzel:wght@400;600;700&family=Crimson+Pro:ital,wght@0,300;0,400;1,300&display=swap');
.coc *,.coc *::before,.coc *::after{box-sizing:border-box;margin:0;padding:0}
.coc{--bg:#120c0d;--surface:#1d1416;--surface2:#281a1d;--border:#3e2a2e;--crimson:#a3263a;--crimson-l:#c8455a;
  --gold:#c9a84c;--gold-l:#e8c96a;--text:#ecdfd6;--text-dim:#9c8780;--radius:8px;--radius-lg:14px;
  font-family:'Crimson Pro',Georgia,serif;color:var(--text);background:var(--bg);min-height:100vh}
.coc-wrap{max-width:1100px;margin:0 auto;padding:calc(env(safe-area-inset-top,0px) + 18px) 16px 48px}
.coc-top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.coc-top-left{display:flex;align-items:center;gap:12px;min-width:0}
.coc-title{font-family:'Cinzel',serif;font-size:1.5rem;font-weight:700;color:var(--crimson-l);letter-spacing:.03em;white-space:nowrap}
.coc-user{font-family:'Cinzel',serif;font-size:.78rem;color:var(--text-dim);letter-spacing:.05em}
.coc-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 16px;border-radius:var(--radius);border:none;cursor:pointer;font-family:'Cinzel',serif;font-size:.82rem;letter-spacing:.05em;font-weight:600;transition:all .15s;white-space:nowrap}
.coc-btn:disabled{opacity:.35;cursor:not-allowed}
.coc-btn.gold{background:var(--gold);color:#120c0d}.coc-btn.gold:hover:not(:disabled){background:var(--gold-l)}
.coc-btn.crimson{background:var(--crimson);color:#fff}.coc-btn.crimson:hover:not(:disabled){background:var(--crimson-l)}
.coc-btn.ghost{background:transparent;color:var(--text-dim);border:1px solid var(--border)}.coc-btn.ghost:hover:not(:disabled){color:var(--text);border-color:var(--text-dim)}
.coc-btn.tool{background:var(--surface2);color:var(--gold-l);border:1px solid var(--gold)}.coc-btn.tool:hover:not(:disabled){background:#3a2a18;color:var(--gold-l)}
.coc-btn.outline{background:transparent;color:var(--gold);border:1px solid var(--gold)}.coc-btn.outline:hover:not(:disabled){background:var(--gold);color:#120c0d}
.coc-btn.sm{padding:6px 11px;font-size:.74rem}
.coc-hero{text-align:center;margin:24px 0 30px}
.coc-hero h1{font-family:'Cinzel',serif;font-size:2.4rem;color:var(--crimson-l);letter-spacing:.04em}
.coc-hero p{color:var(--text-dim);font-style:italic;margin-top:6px}
.coc-lobby-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:24px}
.coc-join{display:flex;gap:8px}
.coc-input{padding:9px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Cinzel',serif;letter-spacing:.12em;outline:none;width:130px;text-transform:uppercase}
.coc-input:focus{border-color:var(--gold)}
.coc-section-title{font-family:'Cinzel',serif;font-size:.68rem;letter-spacing:.18em;color:var(--gold);text-transform:uppercase;margin:18px 0 8px;border-bottom:1px solid var(--border);padding-bottom:6px}
.coc-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px 14px;display:flex;align-items:center;gap:12px;margin-bottom:8px}
.coc-card-info{flex:1;min-width:0}
.coc-card-title{font-family:'Cinzel',serif;font-size:.85rem}
.coc-card-meta{font-size:.78rem;color:var(--text-dim)}
.coc-empty{color:var(--text-dim);font-style:italic;padding:14px;text-align:center}
.coc-waiting{max-width:420px;margin:60px auto;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px}
.coc-code{font-family:'Cinzel',serif;font-size:2rem;letter-spacing:.3em;color:var(--gold);background:var(--surface2);border:1px dashed var(--border);border-radius:var(--radius);padding:12px;margin:14px 0;cursor:pointer}
/* game */
.coc-game{display:grid;grid-template-columns:1fr;gap:16px}
.coc-statusbar{display:flex;flex-wrap:wrap;align-items:center;gap:14px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:10px 14px}
.coc-pill{font-family:'Cinzel',serif;font-size:.72rem;letter-spacing:.06em;color:var(--text-dim)}
.coc-pill b{color:var(--text)}
.coc-vp{display:flex;gap:14px;margin-left:auto}
.coc-vp .v{font-family:'Cinzel',serif;font-size:.8rem}
.coc-vp .v b{color:var(--gold);font-size:1.05rem}
.coc-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px}
.coc-panel h3{font-family:'Cinzel',serif;font-size:.68rem;letter-spacing:.16em;color:var(--gold);text-transform:uppercase;margin-bottom:10px}
.coc-depots{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.coc-depot{border:1px solid var(--border);border-radius:var(--radius);padding:6px;min-height:78px;background:var(--surface2)}
.coc-depot.match{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
.coc-depot-n{font-family:'Cinzel',serif;font-size:.7rem;color:var(--text-dim);text-align:center;margin-bottom:4px}
.coc-tilewrap{display:flex;flex-wrap:wrap;gap:3px;justify-content:center}
.coc-tile{width:26px;height:26px;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:.62rem;font-family:'Cinzel',serif;color:#15100a;font-weight:700;transition:transform .1s;line-height:1;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)}
.coc-tile:hover{transform:scale(1.14)}
.coc-tile.goods{width:21px;height:21px;border-radius:50%;clip-path:none;color:#fff;font-size:.66rem;text-shadow:0 1px 2px rgba(0,0,0,.7)}
.coc-whitedie{display:flex;align-items:center;gap:6px;margin-left:auto}
.coc-whitedie .lbl{font-family:'Cinzel',serif;font-size:.66rem;letter-spacing:.06em;color:var(--text-dim);text-transform:uppercase}
.coc-dicebar{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.coc-die{width:46px;height:46px;border-radius:8px;background:#f3ead8;color:#1a1010;font-family:'Cinzel',serif;font-weight:700;font-size:1.3rem;display:flex;align-items:center;justify-content:center;cursor:pointer;border:2px solid transparent;position:relative}
.coc-die.sel{border-color:var(--gold);box-shadow:0 0 8px rgba(201,168,76,.6)}
.coc-die.used{opacity:.35;cursor:not-allowed}
.coc-die.white{background:#fff;cursor:default}
.coc-die-adj{display:flex;flex-direction:column;gap:2px}
.coc-die-adj button{width:20px;height:20px;font-size:.7rem;line-height:1;border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:4px;cursor:pointer}
.coc-die-adj button:disabled{opacity:.3;cursor:not-allowed}
.coc-storage{display:flex;gap:6px;flex-wrap:wrap}
.coc-stt{width:34px;height:34px;border-radius:6px;border:2px solid transparent;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:.65rem;font-family:'Cinzel',serif;font-weight:700;color:#1a1010}
.coc-stt.sel{border-color:var(--gold);box-shadow:0 0 8px rgba(201,168,76,.6)}
.coc-goods-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.coc-goods-chip{display:flex;align-items:center;gap:4px;font-size:.78rem;color:var(--text-dim)}
.coc-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.coc-hexsvg{width:100%;max-width:520px;display:block;margin:0 auto}
.coc-hex{cursor:default;transition:opacity .12s}
.coc-hex.legal{cursor:pointer}
.coc-hex.legal:hover{opacity:.8}
.coc-hexnum{font-family:'Cinzel',serif;font-weight:700;pointer-events:none}
.coc-modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
.coc-modal{background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:20px;max-width:440px;width:100%}
.coc-modal h3{font-family:'Cinzel',serif;color:var(--gold);font-size:1rem;margin-bottom:6px}
.coc-modal p{color:var(--text-dim);font-size:.88rem;margin-bottom:14px}
.coc-modal-row{display:flex;flex-wrap:wrap;gap:8px}
.coc-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--crimson);color:#fff;padding:10px 18px;border-radius:var(--radius);font-family:'Cinzel',serif;font-size:.82rem;z-index:60;box-shadow:0 6px 20px rgba(0,0,0,.5)}
.coc-winner{max-width:460px;margin:50px auto;text-align:center;background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:30px}
.coc-winner h2{font-family:'Cinzel',serif;font-size:2rem;color:var(--gold)}
.coc-log{max-height:150px;overflow:auto;font-size:.78rem;color:var(--text-dim)}
.coc-log div{padding:2px 0;border-bottom:1px solid rgba(62,42,46,.4)}
.coc-turnbadge{font-family:'Cinzel',serif;font-size:.74rem;padding:4px 10px;border-radius:12px;letter-spacing:.05em}
.coc-turnbadge.you{background:var(--gold);color:#120c0d}
.coc-turnbadge.them{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
`;

// ─── Hex geometry ─────────────────────────────────────────────────────────────
const HEX_S = 26;
function hexCenter(q, r) {
  return { x: HEX_S * Math.sqrt(3) * (q + r / 2), y: HEX_S * 1.5 * r };
}
function hexPoints(cx, cy, s) {
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 180) * (60 * i - 90);
    pts.push(`${(cx + s * Math.cos(a)).toFixed(1)},${(cy + s * Math.sin(a)).toFixed(1)}`);
  }
  return pts.join(" ");
}

export default function CastlesOfCrimson({ myId, authUser, onExit }) {
  const [board, setBoard] = useState(null);            // {spaces, colors, castle, ...}
  const [screen, setScreen] = useState("lobby");        // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState([]);
  const [myGames, setMyGames] = useState([]);
  const [joinCode, setJoinCode] = useState("");
  const [toast, setToast] = useState("");
  const [reviewing, setReviewing] = useState(false);

  // interaction state
  const [selDie, setSelDie] = useState(null);
  const [selStorage, setSelStorage] = useState(null);
  const [extraValue, setExtraValue] = useState(null);
  const [viewOpp, setViewOpp] = useState(false);

  const playerName = authUser?.name || "Player";
  const pendingAction = useRef(null);
  // The die value needed to sell a goods color (its index in the goods order + 1).
  const goodsSellNum = (color) => (board ? board.goods_colors.indexOf(color) + 1 : 0);

  // ── derived ──
  const game = roomData?.game;
  const players = roomData?.players || {};
  const oppId = Object.keys(players).find((p) => p !== myId);
  const me = game?.players?.[myId];
  const opp = oppId ? game?.players?.[oppId] : null;
  const over = game?.phase === "over";
  const pendingMine = game && game.pending_pid === myId;
  const myTurnRaw = game && !over && (game.pending_pid ? game.pending_pid === myId : game.turn === myId);
  const aiThinking = game && roomData?.vs_ai && !over &&
    (game.pending_pid || game.turn) === roomData?.ai_player;

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") { setToast(msg.message || "error"); return; }
    const room = msg.room;
    if (!room) return;
    const tok = room.reconnect_tokens?.[myId];
    const rid = room.room_id || roomId;
    if (tok) { try { localStorage.setItem(`coc_token_${rid}_${myId}`, tok); localStorage.setItem("coc_roomId", rid); } catch {} }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update") {
      if (inGame && screen !== "game") setScreen("game");
    }
  }, [myId, roomId, screen]);

  const { connected, connect, send, disconnect } = useSocket(handleMessage);

  // fetch the static board layout once
  useEffect(() => {
    fetch(`${COC_HTTP}/board`).then((r) => r.json()).then((d) => { if (d.ok) setBoard(d); }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    fetch(`${COC_HTTP}/games`).then((r) => r.json()).then((d) => setOpenGames(d.games || [])).catch(() => {});
    if (authUser && !authUser.guest && authUser.session_token) {
      fetch(`${COC_HTTP}/games/mine?token=${authUser.session_token}`).then((r) => r.json())
        .then((d) => setMyGames(d.games || [])).catch(() => {});
    }
  }, [authUser]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  // auto-resume a saved room on mount
  useEffect(() => {
    try {
      const rid = localStorage.getItem("coc_roomId");
      const tok = rid ? localStorage.getItem(`coc_token_${rid}_${myId}`) : null;
      if (rid && tok) {
        setRoomId(rid);
        connect(`${COC_WS}/${rid}/${myId}`, { action: "reconnect", token: tok });
      }
    } catch {}
    return () => disconnect();
  }, []); // eslint-disable-line

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2400); return () => clearTimeout(t); } }, [toast]);

  // clear selection at the start of a fresh decision
  useEffect(() => { setSelDie(null); setSelStorage(null); setExtraValue(null); }, [game?.turn, game?.round, game?.pending_kind]);

  // ── actions ──
  const startCreate = (vsAi) => {
    const rid = roomCode();
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, { action: "create", name: playerName, vs_ai: vsAi });
  };
  const startJoin = (rid) => {
    rid = (rid || "").toUpperCase();
    if (!rid) return;
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, { action: "join", name: playerName });
  };
  const resume = (rid) => {
    const tok = localStorage.getItem(`coc_token_${rid}_${myId}`);
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName });
  };
  const leaveToLobby = () => {
    disconnect();
    try { localStorage.removeItem("coc_roomId"); } catch {}
    setRoomData(null); setRoomId(""); setReviewing(false); setScreen("lobby"); fetchGames();
  };
  const mv = (move) => send({ action: "move", move });

  // ── move helpers (respect extra_action mode) ──
  const inExtra = pendingMine && game?.pending_kind === "extra_action";
  const actionValue = inExtra ? extraValue : (selDie != null ? game?.dice?.[myId]?.values?.[selDie] : null);

  const doTakeWorkers = () => {
    if (inExtra) { if (extraValue == null) return; mv({ type: "extra_action", value: extraValue, sub: { type: "take_workers" } }); }
    else if (selDie != null) mv({ type: "take_workers", die_index: selDie });
  };
  const doSell = () => {
    if (inExtra) { if (extraValue == null) return; mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } }); }
    else if (selDie != null) mv({ type: "sell_goods", die_index: selDie });
  };
  const clickDepotTile = (depot, tile) => {
    if (!pendingMine && !myTurnRaw) return;
    if (pendingMine && game.pending_kind === "building_take_choice") {
      mv({ type: "building_take_choice", tile_id: tile.id }); return;
    }
    if (inExtra) { if (extraValue == null) { setToast("Pick a die value first"); return; } mv({ type: "extra_action", value: extraValue, sub: { type: "take_hex", depot, tile_id: tile.id } }); return; }
    if (selDie == null) { setToast("Select a die first"); return; }
    mv({ type: "take_hex", die_index: selDie, depot, tile_id: tile.id });
  };
  const clickBlackTile = (tile) => {
    if (!myTurnRaw || pendingMine) return;
    mv({ type: "buy_black", tile_id: tile.id });
  };
  const clickHex = (sid, legal) => {
    if (!legal || !selStorage) return;
    if (pendingMine && game.pending_kind === "townhall_place") { mv({ type: "townhall_place", tile_id: selStorage, space_id: sid }); return; }
    if (inExtra) { if (extraValue == null) { setToast("Pick a die value first"); return; } mv({ type: "extra_action", value: extraValue, sub: { type: "place_tile", tile_id: selStorage, space_id: sid } }); return; }
    if (selDie == null) { setToast("Select a die first"); return; }
    mv({ type: "place_tile", die_index: selDie, tile_id: selStorage, space_id: sid });
  };
  const adjustDie = (i, dir) => {
    const v = game.dice[myId].values[i];
    const to = ((v - 1 + dir + 6) % 6) + 1;
    mv({ type: "adjust_die", die_index: i, to });
  };

  // ── placement legality (client-side highlight; server is authoritative) ──
  const placeValue = inExtra ? extraValue : (selDie != null ? game?.dice?.[myId]?.values?.[selDie] : null);
  const ignoreNumber = pendingMine && game?.pending_kind === "townhall_place";
  const legalTarget = (sid) => {
    if (!selStorage || !me) return false;
    const sp = board?.spaces?.[sid];
    if (!sp || me.duchy[sid]) return false;
    const tile = me.storage.find((t) => t.id === selStorage);
    if (!tile || tile.color !== sp.color) return false;
    if (!ignoreNumber) {
      if (placeValue == null) return false;
      const allowed = new Set([placeValue, (placeValue % 6) + 1, ((placeValue - 2 + 6) % 6) + 1]);
      // (we always allow neighbors here; server enforces whether a free-shift applies)
      if (!allowed.has(sp.number)) return false;
    }
    // adjacency: any filled neighbor
    const [q, r] = sid.split(",").map(Number);
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, -1], [-1, 1]];
    return dirs.some(([dq, dr]) => me.duchy[`${q + dq},${r + dr}`]);
  };

  if (!board) {
    return (<div className="coc"><style>{css}</style><div className="coc-wrap"><p className="coc-empty">Loading…</p></div></div>);
  }

  // ─── Lobby ───────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    const savedId = (() => { try { return localStorage.getItem("coc_roomId"); } catch { return null; } })();
    const savedTok = savedId ? (() => { try { return localStorage.getItem(`coc_token_${savedId}_${myId}`); } catch { return null; } })() : null;
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-wrap">
          <div className="coc-top">
            <div className="coc-top-left">
              <button className="coc-btn ghost sm" onClick={onExit}>← Forrest Games</button>
              <span className="coc-title">Castles of Crimson</span>
            </div>
            <span className="coc-user">{playerName}</span>
          </div>
          <div className="coc-hero">
            <h1>Castles of Crimson</h1>
            <p>Build your duchy of crimson estates.</p>
          </div>
          <div className="coc-lobby-actions">
            <button className="coc-btn gold" onClick={() => startCreate(false)}>+ New Game</button>
            <button className="coc-btn crimson" onClick={() => startCreate(true)}>Play vs Bot</button>
            <div className="coc-join">
              <input className="coc-input" placeholder="CODE" value={joinCode} maxLength={6}
                onChange={(e) => setJoinCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && startJoin(joinCode)} />
              <button className="coc-btn outline" onClick={() => startJoin(joinCode)}>Join</button>
            </div>
            <button className="coc-btn ghost sm" onClick={fetchGames}>↻</button>
          </div>

          {savedId && savedTok && (
            <>
              <div className="coc-section-title">Resume</div>
              <div className="coc-card">
                <div className="coc-card-info"><div className="coc-card-title">Game in progress</div><div className="coc-card-meta">{savedId}</div></div>
                <button className="coc-btn gold sm" onClick={() => resume(savedId)}>Resume</button>
              </div>
            </>
          )}

          {myGames.length > 0 && (
            <>
              <div className="coc-section-title">Your Games</div>
              {myGames.map((g) => (
                <div className="coc-card" key={g.id}>
                  <div className="coc-card-info">
                    <div className="coc-card-title">{g.player1_name} vs {g.player2_name || "waiting…"}</div>
                    <div className="coc-card-meta">{g.id} · {g.status}{g.your_turn ? " · your turn" : ""}</div>
                  </div>
                  <button className="coc-btn outline sm" onClick={() => resume(g.id)}>Continue</button>
                </div>
              ))}
            </>
          )}

          <div className="coc-section-title">Open Games</div>
          {openGames.length === 0 ? <div className="coc-empty">No open games. Create one!</div> :
            openGames.map((g) => (
              <div className="coc-card" key={g.id}>
                <div className="coc-card-info"><div className="coc-card-title">{g.host_id === myId ? "Your game" : `${g.host_name}'s game`}</div><div className="coc-card-meta">{g.id}</div></div>
                {g.host_id !== myId && <button className="coc-btn gold sm" onClick={() => startJoin(g.id)}>Join</button>}
              </div>
            ))}
        </div>
        {toast && <div className="coc-toast">{toast}</div>}
      </div>
    );
  }

  // ─── Waiting ─────────────────────────────────────────────────────────────
  if (screen === "waiting") {
    const isHost = roomData?.host === myId;
    const count = Object.keys(players).length;
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-wrap">
          <div className="coc-waiting">
            <div className="coc-section-title" style={{ border: "none" }}>Room Code</div>
            <div className="coc-code" onClick={() => { navigator.clipboard?.writeText(roomId); setToast("Copied!"); }}>{roomId}</div>
            <p className="coc-card-meta">{count}/2 players joined</p>
            <div style={{ marginTop: 18, display: "flex", gap: 10, justifyContent: "center" }}>
              {isHost
                ? <button className="coc-btn gold" disabled={count < 2} onClick={() => send({ action: "start" })}>Start Game</button>
                : <span className="coc-card-meta">Waiting for host…</span>}
              <button className="coc-btn ghost" onClick={leaveToLobby}>Leave</button>
            </div>
          </div>
        </div>
        {toast && <div className="coc-toast">{toast}</div>}
      </div>
    );
  }

  // ─── Winner ──────────────────────────────────────────────────────────────
  if (over && !reviewing) {
    const w = game.winner;
    const isMe = w === myId;
    const name = players[w] || w;
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-wrap">
          <div className="coc-winner">
            <h2>{isMe ? "Victory!" : "Defeat"}</h2>
            <p className="coc-card-meta" style={{ margin: "10px 0" }}>{name} wins the duchy.</p>
            <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 16 }}>
              <button className="coc-btn outline" onClick={() => setReviewing(true)}>Review Board</button>
              <button className="coc-btn gold" onClick={leaveToLobby}>Back to Lobby</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Game ────────────────────────────────────────────────────────────────
  const dice = game.dice?.[myId];
  const renderDuchy = (pdata, interactive) => {
    const sids = Object.keys(board.spaces);
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    const centers = {};
    for (const sid of sids) {
      const sp = board.spaces[sid];
      const c = hexCenter(sp.q, sp.r);
      centers[sid] = c;
      minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
      minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
    }
    const pad = HEX_S + 4;
    const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;
    return (
      <svg className="coc-hexsvg" viewBox={vb}>
        {sids.map((sid) => {
          const sp = board.spaces[sid];
          const c = centers[sid];
          const tile = pdata.duchy[sid];
          const legal = interactive && legalTarget(sid);
          let fill, num = "";
          if (tile) {
            fill = TILE_HEX[tile.color] || "#555";
            num = tileGlyph(tile);
          } else {
            fill = TILE_HEX[sp.color] || "#444";
            num = String(sp.number);
          }
          return (
            <g key={sid} className={`coc-hex${legal ? " legal" : ""}`} onClick={() => interactive && clickHex(sid, legal)}>
              <title>{tile ? tileDesc(tile, board) : `Empty ${sp.color} space — place a matching tile using die ${sp.number}.`}</title>
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)}
                fill={fill} fillOpacity={tile ? 1 : 0.32}
                stroke={legal ? "var(--gold)" : "#1a1010"} strokeWidth={legal ? 2.5 : 1} />
              {num && <text className="coc-hexnum" x={c.x} y={c.y + 4} textAnchor="middle"
                fontSize={tile ? 11 : 12} fill={tile ? "#1a1010" : "rgba(255,255,255,.75)"}>{num}</text>}
            </g>
          );
        })}
      </svg>
    );
  };

  const goodsForDie = actionValue != null ? board.goods_colors[actionValue - 1] : null;

  return (
    <div className="coc"><style>{css}</style>
      <div className="coc-wrap">
        <div className="coc-top">
          <div className="coc-top-left">
            <button className="coc-btn ghost sm" onClick={over ? () => setReviewing(false) : leaveToLobby}>← {over ? "Results" : "Menu"}</button>
            <span className="coc-title">Castles of Crimson</span>
          </div>
          <button className="coc-btn outline sm" onClick={() => setViewOpp(true)}>View Opponent</button>
        </div>

        <div className="coc-statusbar">
          <span className="coc-pill">Phase <b>{game.phase_letter}</b></span>
          <span className="coc-pill">Round <b>{game.round}/5</b></span>
          <span className={`coc-turnbadge ${myTurnRaw ? "you" : "them"}`}>
            {over ? "Game over" : aiThinking ? "Bot is playing…" : myTurnRaw ? (pendingMine ? "Your decision" : "Your turn") : `${players[game.turn] || "Opponent"}'s turn`}
          </span>
          {game.turn === myId && !over && (
            <button className="coc-btn ghost sm" title="Undo everything you've done this turn"
              onClick={() => { setSelDie(null); setSelStorage(null); setExtraValue(null); mv({ type: "undo_turn" }); }}>↩ Undo Turn</button>
          )}
          <div className="coc-vp">
            <span className="v">{me ? "You" : ""} <b>{me?.vp ?? 0}</b></span>
            {opp && <span className="v">{players[oppId]} <b>{opp.vp}</b></span>}
          </div>
        </div>

        {/* Shared board: depots */}
        <div className="coc-panel">
          <h3>The Board</h3>
          <div className="coc-depots">
            {[1, 2, 3, 4, 5, 6].map((d) => {
              const depot = game.depots[String(d)];
              const match = dice && !pendingMine && [0, 1].some((i) => !dice.used[i] && dice.values[i] === d);
              return (
                <div key={d} className={`coc-depot${match ? " match" : ""}`}>
                  <div className="coc-depot-n">◆ {d}</div>
                  <div className="coc-tilewrap">
                    {depot.hexes.map((t) => (
                      <div key={t.id} className="coc-tile" style={{ background: TILE_HEX[t.color] }}
                        title={tileDesc(t, board)} onClick={() => clickDepotTile(d, t)}>
                        {tileGlyph(t)}
                      </div>
                    ))}
                    {depot.goods.map((gt) => (
                      <div key={gt.id} className="coc-tile goods" style={{ background: GOODS_HEX[gt.color] }} title={tileDesc(gt, board)}>{goodsSellNum(gt.color)}</div>
                    ))}
                  </div>
                </div>
              );
            })}
          </div>
          <div style={{ marginTop: 10, display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
            <span className="coc-pill">Black depot:</span>
            <div className="coc-tilewrap">
              {game.black_depot.map((t) => (
                <div key={t.id} className="coc-tile" style={{ background: TILE_HEX[t.color], opacity: .85 }}
                  title={`${tileDesc(t, board)}  (Black depot: buy for 2 silver.)`} onClick={() => clickBlackTile(t)}>
                  {tileGlyph(t)}
                </div>
              ))}
            </div>
            <div className="coc-whitedie">
              <span className="lbl">White die</span>
              <div className="coc-die white" title="white die (sets the goods depot)">{game.white_die}</div>
            </div>
          </div>
        </div>

        {/* Your area */}
        <div className="coc-panel">
          <h3>Your Duchy — {me?.vp ?? 0} VP</h3>
          {renderDuchy(me, myTurnRaw)}

          {/* dice + resources */}
          <div className="coc-dicebar" style={{ marginTop: 12 }}>
            <span className="coc-pill">Your dice</span>
            {dice && [0, 1].map((i) => (
              <div key={i} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                <div className={`coc-die${selDie === i ? " sel" : ""}${dice.used[i] ? " used" : ""}`}
                  onClick={() => { if (!dice.used[i] && !pendingMine) setSelDie(i); }}>{dice.values[i]}</div>
                {!dice.used[i] && !pendingMine && (
                  <div className="coc-die-adj">
                    <button disabled={!me || me.workers < 1} onClick={() => adjustDie(i, +1)}>▲</button>
                    <button disabled={!me || me.workers < 1} onClick={() => adjustDie(i, -1)}>▼</button>
                  </div>
                )}
              </div>
            ))}
            <span className="coc-pill" style={{ marginLeft: 8 }}>⚒ Workers <b>{me?.workers ?? 0}</b></span>
            <span className="coc-pill">⛃ Silver <b>{me?.silver ?? 0}</b></span>
          </div>

          {/* storage + goods */}
          <div style={{ marginTop: 12, display: "flex", gap: 18, flexWrap: "wrap" }}>
            <div>
              <div className="coc-pill" style={{ marginBottom: 4 }}>Storage</div>
              <div className="coc-storage">
                {[0, 1, 2].map((i) => {
                  const t = me?.storage?.[i];
                  if (!t) return <div key={i} className="coc-stt" style={{ background: "var(--surface2)", border: "1px dashed var(--border)" }} />;
                  return (
                    <div key={t.id} className={`coc-stt${selStorage === t.id ? " sel" : ""}`} style={{ background: TILE_HEX[t.color] }}
                      title={tileDesc(t, board)}
                      onClick={() => setSelStorage(selStorage === t.id ? null : t.id)}>
                      {tileGlyph(t)}
                    </div>
                  );
                })}
              </div>
            </div>
            <div>
              <div className="coc-pill" style={{ marginBottom: 4 }}>Goods</div>
              <div className="coc-goods-row">
                {me && Object.entries(me.goods).length === 0 && <span className="coc-card-meta">none</span>}
                {me && Object.entries(me.goods).map(([c, n]) => (
                  <span key={c} className="coc-goods-chip" title={tileDesc({ kind: "goods", color: c }, board)}>
                    <span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}
                  </span>
                ))}
              </div>
            </div>
          </div>

          {/* action buttons */}
          {myTurnRaw && !pendingMine && (
            <div className="coc-actions">
              <button className="coc-btn tool sm" disabled={selDie == null} onClick={doTakeWorkers}>Take 2 Workers</button>
              <button className="coc-btn tool sm" disabled={selDie == null || !(me?.goods?.[goodsForDie] > 0)} onClick={doSell}>
                Sell{goodsForDie
                  ? <> <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[goodsForDie] }}>{actionValue}</span>{me?.goods?.[goodsForDie] ? ` ×${me.goods[goodsForDie]}` : ""}</>
                  : " goods"}
              </button>
              <button className="coc-btn crimson sm" onClick={() => mv({ type: "end_turn" })}>End Turn</button>
              <span className="coc-card-meta" style={{ alignSelf: "center" }}>
                {selStorage ? "Click a glowing hex to place." : selDie != null ? "Click a depot tile to take, or a storage tile to place." : "Select a die to act."}
              </span>
            </div>
          )}
        </div>

        {/* move log */}
        <div className="coc-panel">
          <h3>Log</h3>
          <div className="coc-log">
            {(game.moves || []).slice(0, 15).map((m, i) => (
              <div key={i}>{players[m.pid] || m.pid}: {m.type}{m.vp ? ` (+${m.vp} VP)` : ""}</div>
            ))}
          </div>
        </div>
      </div>

      {/* pending decision modals */}
      {pendingMine && <PendingModal game={game} board={board} me={me} extraValue={extraValue}
        setExtraValue={setExtraValue} mv={mv} goodsForDie={goodsForDie} />}

      {/* opponent view */}
      {viewOpp && opp && (
        <div className="coc-modal-bg" onClick={() => setViewOpp(false)}>
          <div className="coc-modal" style={{ maxWidth: 560 }} onClick={(e) => e.stopPropagation()}>
            <h3>{players[oppId]} — {opp.vp} VP</h3>
            <p style={{ marginBottom: 10 }}>Silver {opp.silver} · Workers {opp.workers}</p>
            <div style={{ display: "flex", gap: 18, flexWrap: "wrap", alignItems: "flex-start", marginBottom: 10 }}>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Dice</div>
                <div className="coc-dicebar">
                  {game.dice?.[oppId]?.values.map((v, i) => (
                    <div key={i} className={`coc-die${game.dice[oppId].used[i] ? " used" : ""}`} style={{ width: 34, height: 34, fontSize: "1rem" }}>{v}</div>
                  ))}
                </div>
              </div>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Storage</div>
                <div className="coc-storage">
                  {[0, 1, 2].map((i) => {
                    const t = opp.storage?.[i];
                    if (!t) return <div key={i} className="coc-stt" style={{ background: "var(--surface2)", border: "1px dashed var(--border)" }} />;
                    return <div key={t.id} className="coc-stt" style={{ background: TILE_HEX[t.color] }} title={tileDesc(t, board)}>{tileGlyph(t)}</div>;
                  })}
                </div>
              </div>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Goods</div>
                <div className="coc-goods-row">
                  {Object.entries(opp.goods).length === 0 && <span className="coc-card-meta">none</span>}
                  {Object.entries(opp.goods).map(([c, n]) => (
                    <span key={c} className="coc-goods-chip" title={tileDesc({ kind: "goods", color: c }, board)}><span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}</span>
                  ))}
                </div>
              </div>
            </div>
            {renderDuchy(opp, false)}
            <div className="coc-modal-row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button className="coc-btn gold sm" onClick={() => setViewOpp(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {toast && <div className="coc-toast">{toast}</div>}
    </div>
  );
}

// ─── Pending decision modal ──────────────────────────────────────────────────
function PendingModal({ game, board, me, extraValue, setExtraValue, mv, goodsForDie }) {
  const kind = game.pending_kind;
  const skip = () => mv({ type: "skip_pending" });
  const sellNum = (c) => board.goods_colors.indexOf(c) + 1;

  if (kind === "ship_choose_depot") {
    return (
      <Modal title="Ship — take goods" desc="Choose a depot to take all its goods from.">
        <div className="coc-modal-row">
          {[1, 2, 3, 4, 5, 6].map((d) => {
            const n = game.depots[String(d)].goods.length;
            return <button key={d} className="coc-btn outline sm" onClick={() => mv({ type: "ship_take_goods", depot: d })}>◆{d} ({n})</button>;
          })}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "building_take_choice") {
    const ids = game.pending?.ctx?.candidates || [];
    const find = (id) => {
      for (let d = 1; d <= 6; d++) { const t = game.depots[String(d)].hexes.find((x) => x.id === id); if (t) return t; }
      return null;
    };
    return (
      <Modal title="Take a tile" desc="Choose a tile to take into storage.">
        <div className="coc-modal-row">
          {ids.map((id) => { const t = find(id); if (!t) return null; return (
            <button key={id} className="coc-btn outline sm" onClick={() => mv({ type: "building_take_choice", tile_id: id })}>
              {TYPE_LABEL[t.type]}{t.type === "monastery" ? ` #${t.effect_id}` : t.type === "building" ? ` (${t.building})` : ""}
            </button>); })}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "warehouse_sell") {
    return (
      <Modal title="Warehouse — sell goods" desc="Choose a goods type to sell.">
        <div className="coc-modal-row">
          {Object.keys(me.goods).map((c) => (
            <button key={c} className="coc-btn outline sm" onClick={() => mv({ type: "warehouse_sell", color: c })}>
              <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[c], marginRight: 5 }}>{sellNum(c)}</span>×{me.goods[c]}
            </button>
          ))}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "townhall_place") {
    return (
      <Modal title="Town Hall — extra placement" desc="Select a storage tile, then click a glowing hex to place it (any number).">
        <div className="coc-modal-row"><button className="coc-btn ghost sm" onClick={skip}>Skip</button></div>
      </Modal>
    );
  }
  if (kind === "extra_action") {
    return (
      <Modal title="Castle — bonus action" desc={extraValue == null ? "Pick a die value, then take an action (depot/board/buttons)." : `Value ${extraValue}: take a hex, place a tile, sell, or take workers.`}>
        <div className="coc-modal-row">
          {[1, 2, 3, 4, 5, 6].map((v) => (
            <button key={v} className={`coc-btn ${extraValue === v ? "gold" : "outline"} sm`} onClick={() => setExtraValue(v)}>{v}</button>
          ))}
        </div>
        {extraValue != null && (
          <div className="coc-modal-row" style={{ marginTop: 10 }}>
            <button className="coc-btn ghost sm" onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "take_workers" } })}>Take 2 Workers</button>
            <button className="coc-btn ghost sm" disabled={!(me.goods[goodsForDie] > 0)} onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } })}>Sell {goodsForDie}</button>
          </div>
        )}
        <div className="coc-modal-row" style={{ marginTop: 10 }}><button className="coc-btn ghost sm" onClick={skip}>Skip bonus</button></div>
      </Modal>
    );
  }
  return null;
}

function Modal({ title, desc, children }) {
  return (
    <div className="coc-modal-bg">
      <div className="coc-modal">
        <h3>{title}</h3>
        <p>{desc}</p>
        {children}
      </div>
    </div>
  );
}
