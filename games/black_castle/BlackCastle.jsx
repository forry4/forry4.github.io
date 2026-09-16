import { useCallback, useEffect, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbyHero, LobbyCreateRow, LobbyUser, LobbySectionHd,
  LobbyEmpty, LobbyAction, LobbyTabs, CreateModal, CmRow, CmSeg, RulesModal,
  rulesModalCss, createModalCss, lobbyCreateRowCss, gameMenuCss, GameMenu,
  LobbyBotTier, LobbyMatchup, useLastDifficulty, useProgressiveList, notWaiting,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { buildPath, pushPath } from "../../shared/router.js";
import BlackCastleRules from "./rules.jsx";
import cssText from "./BlackCastle.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const HTTP_BASE = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "");
const styles = baseCss + lobbyCss + createModalCss + lobbyCreateRowCss + rulesModalCss + gameMenuCss + cssText;

const ROOM_KEY = "blackcastle_room";
const TOKEN_PREFIX = "blackcastle_token_";
const PLAYER_COLORS = { coral: "Coral", black: "Black", white: "Ivory", gold: "Gold" };
const WORKER_LABEL = { courtiers: "Courtier", warriors: "Warrior", gardeners: "Gardener" };
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

function Die({ die, onClick, disabled }) {
  if (!die) return <span className="bc-die empty">·</span>;
  return <button type="button" className={`bc-die bc-die-${die.color}`} onClick={onClick} disabled={disabled}
    title={`${die.value} ${die.color} die`}><span>{die.value}</span></button>;
}

function ResourcePill({ name, value }) {
  return <span className={`bc-resource bc-${name}`}><i />{value}</span>;
}

function PlayerPanel({ pid, player, name, active, mine }) {
  const workers = player?.workers || {};
  return <article className={`bc-player${active ? " active" : ""}${mine ? " mine" : ""}`}>
    <div className="bc-player-head"><span className={`bc-clan-dot bc-${player?.color || "gold"}`} />
      <strong>{name}{mine ? " · You" : ""}</strong>{active && <em>turn</em>}</div>
    <div className="bc-player-stats"><b>{player?.points || 0}</b><span>points</span><b>{player?.coins || 0}</b><span>coins</span><b>{player?.seals || 0}</b><span>seals</span></div>
    <div className="bc-resource-row">{["food", "iron", "pearl"].map((r) => <ResourcePill key={r} name={r} value={player?.resources?.[r] || 0} />)}</div>
    <div className="bc-worker-row">{Object.entries(workers).map(([worker, places]) => <span key={worker} title={`${WORKER_LABEL[worker]}s in your domain and on the board`}><b>{WORKER_LABEL[worker]?.slice(0, 1)}</b>{Object.values(places || {}).reduce((a, v) => a + (Number(v) || 0), 0)}</span>)}</div>
  </article>;
}

function CardFace({ card, compact = false }) {
  if (!card) return <div className="bc-card bc-card-empty">No card</div>;
  return <div className={`bc-card${compact ? " compact" : ""}`}>
    <span className="bc-card-kind">{card.kind}</span><strong>{card.name}</strong>
    {card.vp ? <b className="bc-card-vp">{card.vp} VP</b> : null}
    {!compact && <small>{card.back === "vp" ? "Lantern reward" : `${card.level ? `Floor ${card.level}` : "Clan card"}`}</small>}
  </div>;
}

function Lobby({ myId, authUser, openGames, activeGames, history, onRefresh, refreshing, onCreate, onJoin, onExit, onRules }) {
  const active = notWaiting(activeGames);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [visibleHistory, historySentinel] = useProgressiveList(history);
  return <div className="app blackcastle" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}>
    <style>{styles}</style>
    <LobbyHeader onBack={onExit} title="Black Castle" onRules={onRules} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="blackcastle"><LobbyCreateRow onCreate={onCreate} onJoin={onJoin} onRefresh={onRefresh}
        refreshing={refreshing} onRules={onRules} /></LobbyHero>
      <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[{ key: "open", label: "Open", count: openGames.length || null }, { key: "active", label: "Active", count: activeGames.length || null }, { key: "history", label: "History", count: history.length || null }]} />
      <div className={`bc-lobby-grid lby-cols tab-${lobbyTab}`}>
        <section className="bc-lobby-column lby-col-open"><LobbySectionHd title="Open tables" note={`${openGames.length} waiting`} />
          {!openGames.length && <LobbyEmpty>No open castles yet — start one under the moon.</LobbyEmpty>}
          <div className="lby-list">{openGames.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><div className="lby-card-title">{g.player1_name || "Player"}'s castle <span className="lby-seats">{[g.player1_name, g.player2_name, g.player3_name, g.player4_name].filter(Boolean).length}/{g.max_players || 4}</span></div>
              <div className="lby-card-meta">{g.id} · standard base game</div></div>
            <div className="lby-card-actions"><LobbyAction onClick={() => onJoin(g.id)}>Join</LobbyAction></div>
          </div>)}</div>
        </section>
        <section className="bc-lobby-column lby-col-active"><LobbySectionHd title="Active tables" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No active castles yet.</LobbyEmpty>}
          <div className="lby-list">{active.map((g) => <div className="lby-card" key={g.id}><div className="lby-card-info"><LobbyMatchup placeholder="Opponent" seats={[{ name: g.player1_name || "Clan", you: true }, { name: g.player2_name || "Opponent", you: false }]} /><div className="lby-card-meta"><LobbyBotTier tier={g.ai_difficulty} labels={BLACK_CASTLE_AI_LABELS} /></div></div><div className="lby-card-actions"><LobbyAction onClick={() => onJoin(g.id)}>Resume</LobbyAction></div></div>)}</div>
        </section>
        <section className="bc-lobby-column lby-col-history"><LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser ? "No finished castles yet." : "Log in to keep your history."}</LobbyEmpty>}
          <div className="lby-list">{visibleHistory.map((g) => <div className="lby-card lby-card-hist" key={g.id}><div className="lby-card-info"><div className="lby-card-title">{g.outcome || "Finished"} · {g.player1_name || "Clan"}</div><div className="lby-card-meta"><LobbyBotTier tier={g.ai_difficulty} labels={BLACK_CASTLE_AI_LABELS} /></div></div></div>)}{historySentinel}</div>
        </section>
        <aside className="bc-lobby-aside"><span className="bc-kicker">HIMEJI · 1761</span><h2>Build your clan in the lantern light.</h2>
          <p>Choose a die from a bridge, place it where its value matters, and guide your workers through the castle before the final bell.</p>
          <div className="bc-aside-rule"><span>2–4</span><small>seats</small><span>3</span><small>rounds</small><span>9</span><small>turns each</small></div>
        </aside>
      </div>
    </div></div>
  </div>;
}

function DraftPanel({ game, sendMove }) {
  return <section className="bc-decision bc-draft"><span className="bc-kicker">OPENING DRAFT</span><h2>Choose a starting pair</h2><p>Take one face-up resource and action card for your clan.</p>
    <div className="bc-draft-grid">{(game.draft_options || []).map((option, i) => <button type="button" key={i} onClick={() => sendMove({ type: "draft", index: i })}>
      <CardFace card={option.resource} compact /><span className="bc-plus">+</span><CardFace card={option.action} compact /></button>)}</div>
  </section>;
}

function DecisionPanel({ game, sendMove }) {
  const pending = game.pending;
  const moves = game.legal_moves || [];
  if (game.phase === "draft") return <DraftPanel game={game} sendMove={sendMove} />;
  if (!pending && !moves.length) return <section className="bc-decision quiet"><p>Waiting for the next clan to move…</p></section>;
  return <section className="bc-decision" aria-live="polite"><span className="bc-kicker">{pending?.kind === "place_die" ? "PLACE YOUR DIE" : pending?.kind === "outside_worker" ? "CHOOSE A WORKER" : pending?.kind === "end_turn" ? "ACTION RESOLVED" : "YOUR CHOICE"}</span>
    <h2>{pending?.kind === "place_die" ? "Where will it shape the castle?" : pending?.kind === "outside_worker" ? "Who goes outside the walls?" : pending?.kind === "end_turn" ? "End your turn" : "Choose an action"}</h2>
    {pending?.kind === "place_die" && <p>The die can be placed on any highlighted space. Its value is compared with the printed value.</p>}
    <div className="bc-choice-grid">{moves.map((move, i) => <button type="button" key={i} className={move.type === "end_turn" ? "primary" : ""} onClick={() => sendMove(move)}>
      {move.type === "place_die" ? (move.space === "well" ? "Well · reveal 2 benefits" : move.space.replace(":", " · ").replace("castle", "Castle").replace("outside", "Outside").replace("domain", "Domain").replace("yard", "Training Yard").replace("garden", "Garden")) : move.type === "outside_worker" ? (move.action === "audience" ? "Courtier · audience (2 coins)" : move.action === "climb" ? "Courtier · social climb" : WORKER_LABEL[move.worker]) : move.type === "worker_destination" ? `${WORKER_LABEL[move.worker]} · ${move.worker === "warriors" ? "Training Yard" : "Garden"} ${Number(move.index) + 1}` : move.type === "courtier_destination" ? `Climb to ${move.to} · ${move.cost} pearl` : move.type === "end_turn" ? "End Turn" : move.type === "convert" ? `Trade ${move.from} → ${move.to || "coin"}` : "Choose"}</button>)}</div>
    {game.can_undo && <button type="button" className="bc-undo" onClick={() => sendMove({ type: "undo" })}>↶ Undo this turn</button>}
  </section>;
}

function Board({ game, sendMove, myId, names }) {
  const legal = game.legal_moves || [];
  const take = (color, side) => legal.some((m) => m.type === "take_die" && m.bridge === color && m.side === side);
  return <div className="bc-board">
    <section className="bc-castle"><div className="bc-section-label"><span>THE KEEP</span><small>castle rooms</small></div><div className="bc-rooms">{(game.castle?.rooms || []).map((room) => <article className="bc-room" key={room.id}><span className="bc-room-floor">F{room.floor}</span><CardFace card={room.card} compact /><div className="bc-room-dice">{(room.dice || []).map((die, i) => <Die key={i} die={die} disabled />)}</div></article>)}</div><div className="bc-daimyo"><CardFace card={game.castle?.daimyo} /><span>Daimyo hall</span></div></section>
    <section className="bc-bridges"><div className="bc-section-label"><span>BRIDGES</span><small>take an end die</small></div>{["coral", "black", "white"].map((color) => <div className={`bc-bridge bc-bridge-${color}`} key={color}><span className="bc-bridge-name">{color}</span><div className="bc-bridge-dice">{(game.bridges?.[color] || []).map((die, i, arr) => <Die key={die.id || i} die={die} disabled={!(i === 0 ? take(color, "left") : i === arr.length - 1 ? take(color, "right") : false)} onClick={() => sendMove({ type: "take_die", bridge: color, side: i === 0 ? "left" : "right" })} />)}</div></div>)}</section>
    <section className="bc-lower-board"><div className="bc-outside"><div className="bc-section-label"><span>OUTSIDE THE WALLS</span><small>value 5</small></div><div className="bc-outside-spaces">{["0", "1"].map((id) => <div key={id} className="bc-space">{game.outside?.[id] ? <><b>{names[game.outside[id].pid] || game.outside[id].pid}</b><Die die={game.outside[id].die} disabled /></> : "open"}</div>)}</div></div><div className="bc-well"><div className="bc-section-label"><span>THE WELL</span><small>value 1 · unlimited</small></div><div className="bc-well-stone">◈</div></div><div className="bc-gardens"><div className="bc-section-label"><span>GARDENS</span><small>food cost · end-round points</small></div><div className="bc-garden-grid">{(game.gardens || []).map((garden) => <div className="bc-garden" key={garden.id}><CardFace card={garden.plant || garden.stone} compact /><span>{garden.occupants?.length || 0} gardeners</span></div>)}</div></div></section>
    <section className="bc-domain-board"><div className="bc-section-label"><span>PERSONAL DOMAINS</span><small>one activation per colour each turn</small></div><div className="bc-domain-row">{Object.entries(game.players || {}).map(([pid, player]) => <div className="bc-domain" key={pid}><strong>{names[pid] || pid}</strong><CardFace card={player.action_card} compact />{["coral", "black", "white"].map((color) => <div className={`bc-domain-slot bc-${color}`} key={color}><span>{color}</span>{player.domain?.[color]?.die ? <Die die={player.domain[color].die} disabled /> : "6"}</div>)}</div>)}</div></section>
  </div>;
}

function Game({ roomData, myId, sendMove, onExit, onRules, onAbandon, connected, authUser }) {
  const game = roomData.game;
  const names = roomData.players || {};
  const myPlayer = game?.players?.[myId];
  const turnName = game?.turn_pid ? names[game.turn_pid] || game.turn_pid : "—";
  const log = (game?.log || []).slice(-12).reverse();
  return <div className="app blackcastle" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}><style>{styles}</style>
    <LobbyHeader title="Black Castle" menu={<GameMenu onLeave={onExit} onRules={onRules} onAbandon={game?.phase === "over" ? null : onAbandon} />} user={<span className={`bc-connection${connected ? "" : " lost"}`}>{connected ? "Connected" : "Reconnecting…"}</span>} />
    <main className="bc-game-shell"><header className="bc-game-hero"><div><span className="bc-kicker">HIMEJI · MOONLIT TABLE</span><h1>The Black Castle</h1><p>{game?.phase === "over" ? `${names[game.winner] || "The winning clan"} takes the castle.` : `Round ${game?.round || 1} · ${turnName}'s turn`}</p></div><div className="bc-round-mark"><b>{game?.round || 1}</b><span>/ 3 rounds</span></div></header>
      <div className="bc-players">{Object.entries(game?.players || {}).map(([pid, player]) => <PlayerPanel key={pid} pid={pid} player={player} name={names[pid] || pid} active={game?.turn_pid === pid} mine={pid === myId} />)}</div>
      {game?.phase === "over" && <div className="bc-result"><span className="bc-kicker">CASTLE SCORED</span><h2>{names[game.winner] || "The winning clan"} wins with {game.scores?.[game.winner] || 0} points.</h2><p>Return to the menu to start another table.</p></div>}
      {game && <Board game={game} sendMove={sendMove} myId={myId} names={names} />}
      <div className="bc-bottom"><DecisionPanel game={game || {}} sendMove={sendMove} /><section className="bc-log"><div className="bc-section-label"><span>CASTLE CHRONICLE</span><small>server log</small></div>{log.length ? log.map((entry, i) => <p key={`${entry.turn}-${i}`}><b>{entry.turn}</b>{entry.message}</p>) : <p>The lanterns are quiet.</p>}</section></div>
    </main>
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
    if (!rid) return;
    intentRef.current = "reconnect";
    tokenRef.current = (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })();
    connect();
    return () => { try { wsRef.current?.close(); } catch {} };
  // Deep links are intentionally handled once. Subsequent room transitions use openRoom.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const openRoom = useCallback((rid, intent, createPayload) => {
    const id = rid.toUpperCase();
    setRoomId(id); roomRef.current = id; intentRef.current = intent; tokenRef.current = ""; createPayloadRef.current = createPayload || null; setScreen("game");
    try { pushPath(buildPath("blackcastle", id)); } catch {}
    connect();
  }, [connect]);
  const createGame = useCallback(() => {
    setShowCreate(false);
    rememberDifficulty(createDifficulty);
    openRoom(roomCode(), "create", { name: authUser?.name || "Player", max_players: maxPlayers, num_bots: Math.min(numBots, maxPlayers - 1), ai_difficulty: createDifficulty });
  }, [authUser, createDifficulty, maxPlayers, numBots, openRoom, rememberDifficulty]);
  const joinRoom = useCallback((rid) => { openRoom(rid, "join"); }, [openRoom]);
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);
  const abandon = useCallback(() => send({ action: "abandon" }), [send]);
  const exit = useCallback(() => { try { wsRef.current?.close(); } catch {} wsRef.current = null; setConnected(false); setRoomData(null); setRoomId(""); setScreen("lobby"); try { pushPath(buildPath("blackcastle")); } catch {} onExit?.(); }, [onExit]);
  const start = useCallback(() => send({ action: "start" }), [send]);
  const showWaiting = screen === "game" && roomData && !roomData.game;
  return <>
    {screen === "lobby" && <Lobby {...{ myId, authUser, openGames, activeGames, history, onRefresh: refresh, refreshing, onCreate: () => setShowCreate(true), onJoin: joinRoom, onExit, onRules: () => setShowRules(true) }} />}
    {showWaiting && <div className="app blackcastle" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}><style>{styles}</style><LobbyHeader onBack={exit} onRules={() => setShowRules(true)} user={<LobbyUser user={authUser} />} /><div className="bc-waiting"><span className="bc-kicker">{roomData.room_id}</span><h1>Lanterns are being lit.</h1><p>Share this room code with your clan. The host can start when at least two seats are ready.</p><div className="bc-wait-seats">{Object.entries(roomData.players || {}).map(([pid, name]) => <span key={pid}>{name}</span>)}</div>{roomData.host === myId && <button type="button" className="bc-primary" onClick={start}>Start standard game</button>}</div></div>}
    {roomData?.game && <Game {...{ roomData, myId, sendMove, onExit: exit, onAbandon: abandon, onRules: () => setShowRules(true), connected, authUser }} />}
    {showCreate && <CreateModal title="New Black Castle table" onClose={() => setShowCreate(false)}><CmRow label="Seats"><CmSeg value={maxPlayers} onChange={(v) => { setMaxPlayers(v); setNumBots(Math.min(numBots, v - 1)); }} options={[2, 3, 4].map((v) => ({ value: v, label: `${v} seats` }))} /></CmRow><CmRow label="Easy bots"><CmSeg value={numBots} onChange={setNumBots} options={Array.from({ length: maxPlayers }, (_, i) => ({ value: i, label: i ? `${i} bot${i > 1 ? "s" : ""}` : "Friends" }))} wrap /></CmRow><CmRow label="Opponent tier"><CmSeg value={createDifficulty} onChange={setCreateDifficulty} options={BLACK_CASTLE_AI_TIER_OPTIONS} /></CmRow><div className="cm-footer"><span className="cm-summary">Standard base game · {BLACK_CASTLE_AI_LABELS[createDifficulty]} opponent</span><button type="button" className="cm-create" onClick={createGame}>Open table</button></div></CreateModal>}
    {showRules && <RulesModal title="How to play — Black Castle" onClose={() => setShowRules(false)}><BlackCastleRules /></RulesModal>}
    {toast && <div className="bc-toast" role="status">{toast}</div>}
  </>;
}
