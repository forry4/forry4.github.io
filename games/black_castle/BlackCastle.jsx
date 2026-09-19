import { useCallback, useEffect, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbyHero, LobbyCreateRow, LobbyUser, LobbySectionHd,
  LobbyEmpty, LobbyAction, LobbyTabs, CreateModal, CmRow, CmSeg, RulesModal,
  rulesModalCss, createModalCss, lobbyCreateRowCss, gameMenuCss,
  LobbyBotTier, LobbyMatchup, LobbyOpenTitle, LobbyOpenActions, seatStateOf, useLastDifficulty, useProgressiveList, notWaiting,
  WaitingRoom, waitingRoomCss,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { buildPath, pushPath } from "../../shared/router.js";
import { leaveOpenSeat, readRoomToken } from "../../shared/roomLifecycle.js";
import BlackCastleRules from "./rules.jsx";
import cssText from "./BlackCastle.css?inline";
import BoardView from "./BoardView.jsx";
import { Icon } from "./presentation.jsx";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const HTTP_BASE = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "");
const styles = baseCss + lobbyCss + createModalCss + lobbyCreateRowCss + rulesModalCss + gameMenuCss + waitingRoomCss + cssText;

const TOKEN_PREFIX = "blackcastle_token_";
const BLACK_CASTLE_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "Random legal moves" },
];
const BLACK_CASTLE_AI_TIERS = BLACK_CASTLE_AI_TIER_OPTIONS.map((tier) => tier.value);
const BLACK_CASTLE_AI_LABELS = Object.fromEntries(BLACK_CASTLE_AI_TIER_OPTIONS.map((tier) => [tier.value, tier.label]));

function roomCode() {
  return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
}

function deepRoom() {
  try {
    const m = /\/blackcastle\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    return m ? m[1].toUpperCase() : null;
  } catch { return null; }
}

function Lobby({ myId, authUser, openGames, activeGames, history, onRefresh, refreshing, onCreate, onJoin, onLeave, onCancel, onExit, onRules }) {
  const active = notWaiting(activeGames);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [visibleHistory, historySentinel] = useProgressiveList(history);
  return <div className="app blackcastle" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}>
    <style>{styles}</style>
    <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="blackcastle"><LobbyCreateRow onCreate={onCreate} onJoin={onJoin} onRefresh={onRefresh}
        refreshing={refreshing} onRules={onRules} /></LobbyHero>
      <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[{ key: "open", label: "Open", count: openGames.length || null }, { key: "active", label: "Active", count: activeGames.length || null }, { key: "history", label: "History", count: history.length || null }]} />
      <div className={`lby-cols tab-${lobbyTab}`}>
        <section className="lby-col-open"><LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
          {!openGames.length && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
          <div className="lby-list">{openGames.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><LobbyOpenTitle game={g} myId={myId} defaultMaxPlayers={4} />
              <div className="lby-card-meta">{g.id} · standard base game</div></div>
            <div className="lby-card-actions"><LobbyOpenActions state={seatStateOf(g, myId)}
              onReturn={() => onJoin(g.id)} onJoin={() => onJoin(g.id)}
              onLeave={() => onLeave(g.id)} onCancel={() => onCancel(g.id)} /></div>
          </div>)}</div>
        </section>
        <section className="lby-col-active"><LobbySectionHd title="Active Games" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          <div className="lby-list">{active.map((g) => <div className="lby-card" key={g.id}><div className="lby-card-info"><LobbyMatchup placeholder="Opponent" seats={[{ name: g.player1_name || "Clan", you: true }, { name: g.player2_name || "Opponent", you: false }]} /><div className="lby-card-meta"><LobbyBotTier tier={g.ai_difficulty} labels={BLACK_CASTLE_AI_LABELS} /></div></div><div className="lby-card-actions"><LobbyAction onClick={() => onJoin(g.id)}>Resume</LobbyAction></div></div>)}</div>
        </section>
        <section className="lby-col-history"><LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser && !authUser.guest ? "Your finished games will appear here." : "Log in to keep your game history."}</LobbyEmpty>}
          <div className="lby-list">{visibleHistory.map((g) => <div className="lby-card lby-card-hist" key={g.id}><div className="lby-card-info"><div className="lby-card-title">{g.outcome || "Finished"} · {g.player1_name || "Clan"}</div><div className="lby-card-meta"><LobbyBotTier tier={g.ai_difficulty} labels={BLACK_CASTLE_AI_LABELS} /></div></div></div>)}{historySentinel}</div>
        </section>
      </div>
    </div></div>
  </div>;
}

export default function BlackCastle({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState(() => deepRoom() ? "game" : "lobby");
  const [roomId, setRoomId] = useState(() => deepRoom() || "");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState([]);
  const [activeGames, setActiveGames] = useState([]);
  const [history, setHistory] = useState([]);
  const [refreshing, setRefreshing] = useState(false);
  const [connected, setConnected] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [maxPlayers, setMaxPlayers] = useState(3);
  const [numBots, setNumBots] = useState(2);
  const [createDifficulty, setCreateDifficulty, rememberDifficulty] =
    useLastDifficulty("blackcastle", myId, BLACK_CASTLE_AI_TIERS, "easy");
  const [toast, setToast] = useState("");
  const wsRef = useRef(null);
  const roomRef = useRef(roomId);
  const tokenRef = useRef("");
  const intentRef = useRef("join");
  const createPayloadRef = useRef(null);
  roomRef.current = roomId;

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const response = await fetch(`${HTTP_BASE}/blackcastle/games`);
      const data = await response.json();
      setOpenGames(data.games || []);
      const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
      const [mine, old] = await Promise.all([
        fetch(`${HTTP_BASE}/blackcastle/games/mine`, { headers }).then((r) => r.ok ? r.json() : { games: [] }).catch(() => ({ games: [] })),
        fetch(`${HTTP_BASE}/blackcastle/games/history`, { headers }).then((r) => r.ok ? r.json() : { games: [] }).catch(() => ({ games: [] })),
      ]);
      setActiveGames((mine.games || []).filter((g) => g.status === "playing"));
      setHistory(old.games || []);
    } catch { setToast("Could not load open castles."); }
    finally { setRefreshing(false); }
  }, [authUser]);
  useEffect(() => { refresh(); }, [refresh]);

  const onMessage = useCallback((message) => {
    if (message.room) {
      setToast("");
      intentRef.current = "reconnect";
      setRoomData(message.room);
      // Every room update belongs to the room view. A friend-only table has no
      // game object until the host starts it, but it still needs the waiting
      // screen so players can see the seats and share the code.
      setScreen("game");
      const token = message.room.reconnect_tokens?.[myId];
      if (token && roomRef.current) { tokenRef.current = token; try { localStorage.setItem(`${TOKEN_PREFIX}${roomRef.current}`, token); } catch {} }
    }
    if (message.type === "error") setToast(message.message || "The castle rejected that move.");
    else if (message.type === "created" || message.type === "joined") setToast("");
  }, [myId]);

  const connect = useCallback(() => {
    const rid = roomRef.current;
    if (!rid) return;
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(`${WS_BASE}/blackcastle/ws/${encodeURIComponent(rid)}/${encodeURIComponent(myId)}`);
    wsRef.current = ws;
    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      setConnected(true);
      const token = tokenRef.current || (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })();
      const first = intentRef.current === "create"
        ? { action: "create", ...(createPayloadRef.current || {}), name: authUser?.name || "Player" }
        : token && intentRef.current === "reconnect"
          ? { action: "reconnect", token }
          : { action: "join", name: authUser?.name || "Player", session_token: authUser?.session_token || null };
      ws.send(JSON.stringify(first));
    };
    ws.onmessage = (event) => { if (wsRef.current !== ws) return; try { onMessage(JSON.parse(event.data)); } catch {} };
    ws.onclose = () => { if (wsRef.current === ws) setConnected(false); };
  }, [authUser, myId, onMessage]);
  const socketReady = useCallback(() => wsRef.current?.readyState ?? 3, []);
  const send = useCallback((payload) => { try { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(payload)); } catch {} }, []);
  useAutoReconnect({ enabled: !!roomId && screen === "game", connected, connect, socketReady });

  useEffect(() => {
    const rid = deepRoom();
    if (!rid) return () => { try { wsRef.current?.close(); } catch {} };
    intentRef.current = "reconnect";
    tokenRef.current = (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })();
    connect();
    return () => { try { wsRef.current?.close(); } catch {} };
  // Deep links are intentionally handled once. Subsequent room transitions use openRoom.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openRoom = useCallback((rid, intent, createPayload) => {
    const id = rid.toUpperCase();
    const storedToken = intent === "join" ? (() => {
      try { return localStorage.getItem(`${TOKEN_PREFIX}${id}`) || ""; } catch { return ""; }
    })() : "";
    setRoomData(null); setToast(""); setConnected(false);
    setRoomId(id); roomRef.current = id;
    intentRef.current = storedToken ? "reconnect" : intent;
    tokenRef.current = storedToken;
    createPayloadRef.current = createPayload || null; setScreen("game");
    try { pushPath(buildPath("blackcastle", id)); } catch {}
    connect();
  }, [connect]);
  const createGame = useCallback(() => {
    setShowCreate(false);
    if (numBots > 0) rememberDifficulty(createDifficulty);
    openRoom(roomCode(), "create", { name: authUser?.name || "Player", max_players: maxPlayers, num_bots: Math.min(numBots, maxPlayers - 1), ai_difficulty: createDifficulty });
  }, [authUser, createDifficulty, maxPlayers, numBots, openRoom, rememberDifficulty]);
  const joinRoom = useCallback((rid) => { openRoom(rid, "join"); }, [openRoom]);
  const cancelGame = useCallback(async (id) => {
    try {
      const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
      const roomToken = readRoomToken(`${TOKEN_PREFIX}${id}`);
      if (roomToken) headers["X-Room-Token"] = roomToken;
      const response = await fetch(`${HTTP_BASE}/blackcastle/games/${id}?player_id=${encodeURIComponent(myId)}`, { method: "DELETE", headers });
      const data = await response.json().catch(() => ({}));
      if (!data.ok) { setToast(data.message || "Could not cancel"); return; }
      refresh();
    } catch { setToast("Could not cancel"); }
  }, [authUser, myId, refresh]);
  const leaveSeat = useCallback(async (id) => {
    try {
      await leaveOpenSeat({
        endpoint: `${HTTP_BASE}/blackcastle/games`, roomId: id, playerId: myId,
        tokenKey: `${TOKEN_PREFIX}${id}`, sessionToken: authUser?.session_token,
      });
      setToast("Seat released");
      refresh();
    } catch (err) { setToast(err?.message || "Could not leave that table"); }
  }, [authUser, myId, refresh]);
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);
  const abandon = useCallback(() => send({ action: "abandon" }), [send]);
  const exit = useCallback(() => { try { wsRef.current?.close(); } catch {} wsRef.current = null; setConnected(false); setRoomData(null); setRoomId(""); setScreen("lobby"); try { pushPath(buildPath("blackcastle")); } catch {} refresh(); }, [refresh]);
  const start = useCallback(() => send({ action: "start" }), [send]);
  const showWaiting = screen === "game" && roomData && !roomData.game;
  return <>
    {screen === "lobby" && <Lobby {...{ myId, authUser, openGames, activeGames, history, onRefresh: refresh, refreshing, onCreate: () => setShowCreate(true), onJoin: joinRoom, onLeave: leaveSeat, onCancel: cancelGame, onExit, onRules: () => setShowRules(true) }} />}
    {screen === "game" && !roomData && <div className="app blackcastle"><style>{styles}</style><LobbyHeader title="Black Castle" onBack={exit} /><div className="bc-waiting"><Icon name="castle" size={48} /><h1>{toast ? "The gate is closed." : "Opening the castle…"}</h1><p role="status">{toast || "Connecting to your table. This may take a moment."}</p><button type="button" className="bc-primary" onClick={exit}>Return to lobby</button></div></div>}
    {showWaiting && <div className="app blackcastle" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}><style>{styles}</style>
      {/* `WaitingRoom` in shared/lobby.jsx. This was the one waiting room in the
          product with NO way out at all — the way back was the browser's own Back
          button — and the shared kit carries one, so it now has the same one the
          other eight do. `canStart` holds the socket condition Black Castle's own
          Start had: a table cannot be dealt from a closed socket. */}
      <WaitingRoom
        game="blackcastle" roomId={roomData.room_id}
        players={roomData.players} hostId={roomData.host} myId={myId}
        min={2} max={roomData.max_players || 4}
        note="Lanterns are being lit. The host deals once at least two seats are taken."
        user={authUser}
        onLeave={exit}
        onRules={() => setShowRules(true)}
        onStart={start}
        canStart={connected}
        blockedLabel="Reconnecting…" />
    </div>}
    {roomData?.game && <BoardView {...{ roomData, myId, sendMove, onExit: exit, onAbandon: abandon, onRules: () => setShowRules(true), connected, styles }} />}
    {showCreate && <div className="blackcastle bc-overlay-scope" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}>
      <CreateModal title="New Black Castle table" onClose={() => setShowCreate(false)}>
        <CmRow label="Seats"><CmSeg value={maxPlayers} onChange={(v) => { setMaxPlayers(v); setNumBots(Math.min(numBots, v - 1)); }} options={[2, 3, 4].map((v) => ({ value: v, label: `${v} seats` }))} /></CmRow>
        <CmRow label="Computer players"><CmSeg value={numBots} onChange={setNumBots} options={Array.from({ length: maxPlayers }, (_, i) => ({ value: i, label: i ? `${i} bot${i > 1 ? "s" : ""}` : "None" }))} wrap /></CmRow>
        {numBots > 0 && <CmRow label="Opponent tier"><CmSeg value={createDifficulty} onChange={setCreateDifficulty} options={BLACK_CASTLE_AI_TIER_OPTIONS} /></CmRow>}
        <div className="cm-footer">
          <span className="cm-summary">You + {numBots > 0 ? `${numBots} Easy bot${numBots > 1 ? "s" : ""}` : `${maxPlayers - 1} friend${maxPlayers > 2 ? "s" : ""}`}{numBots > 0 && maxPlayers - numBots - 1 > 0 ? ` + ${maxPlayers - numBots - 1} friend${maxPlayers - numBots > 2 ? "s" : ""}` : ""}</span>
          <button type="button" className="cm-create" onClick={createGame}>Open table</button>
        </div>
      </CreateModal>
    </div>}
    {showRules && <div className="blackcastle bc-overlay-scope"><RulesModal title="How to play — Black Castle" onClose={() => setShowRules(false)}><BlackCastleRules /></RulesModal></div>}
    {toast && <div className="bc-toast" role="status">{toast}</div>}
  </>;
}
