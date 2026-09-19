import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbyHero, LobbyCreateRow, LobbyUser, LobbySectionHd,
  LobbyEmpty, LobbyAction, LobbyTabs, LobbyMatchup, LobbyBotTier, TurnBadge,
  LobbyOpenTitle, LobbyOpenActions, seatStateOf, notWaiting, timeAgo,
  CreateModal, CmRow, CmSeg, RulesModal, GameMenu,
  createModalCss, lobbyCreateRowCss, rulesModalCss, gameMenuCss,
  WaitingRoom, waitingRoomCss, useProgressiveList, useListFade,
  readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame, useLastDifficulty,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { buildPath, pushPath, subscribe } from "../../shared/router.js";
import { leaveOpenSeat, readRoomToken } from "../../shared/roomLifecycle.js";
import PinchRules from "./rules.jsx";
import cssText from "./Pinch.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const HTTP_BASE = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "");
const styles = baseCss + lobbyCss + createModalCss + lobbyCreateRowCss
  + rulesModalCss + gameMenuCss + waitingRoomCss + cssText;
const ACCENT = { "--lby-accent": GAME_ACCENTS.pinch };
const TOKEN_PREFIX = "pinch_token_";
const PINCH_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "Uniformly random legal actions" },
];
const PINCH_AI_TIERS = PINCH_AI_TIER_OPTIONS.map((tier) => tier.value);
const PINCH_AI_LABELS = Object.fromEntries(PINCH_AI_TIER_OPTIONS.map((tier) => [tier.value, tier.label]));
const MODES = [
  { value: "standard", label: "Standard", title: "First to remove three rings" },
  { value: "blitz", label: "Blitz", title: "First to score one row" },
];
const DIRECTIONS = [[1, 0], [0, 1], [1, -1]];
const CORNERS = new Set(["5,0", "5,-5", "0,-5", "-5,0", "-5,5", "0,5"]);

const NODES = [];
for (let r = -5; r <= 5; r += 1) for (let q = -5; q <= 5; q += 1) {
  const s = -q - r;
  if (Math.max(Math.abs(q), Math.abs(r), Math.abs(s)) <= 5 && !CORNERS.has(`${q},${r}`)) NODES.push([q, r]);
}
const NODE_ID = new Map(NODES.map((coord, index) => [coord.join(","), index]));
const pointOf = (node) => {
  const [q, r] = NODES[node] || [0, 0];
  return { x: (q + r / 2) * 86, y: r * 74.48 };
};
const EDGES = [];
NODES.forEach(([q, r], node) => DIRECTIONS.forEach(([dq, dr]) => {
  const other = NODE_ID.get(`${q + dq},${r + dr}`);
  if (other != null) EDGES.push([node, other]);
}));

function roomCode() {
  return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
}

function playerName(raw) {
  return String(raw || "Player").replace(/[^A-Za-z]/g, "").slice(0, 16) || "Player";
}

function deepRoom() {
  try {
    const match = /\/pinch\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    return match ? match[1].toUpperCase() : null;
  } catch { return null; }
}

function modeLabel(mode) { return mode === "blitz" ? "Blitz" : "Standard"; }

function moveKey(move) {
  return `${move.action}:${move.from ?? ""}:${move.to ?? ""}:${move.at ?? ""}:${(move.cells || []).join("-")}`;
}

function useMotionEvent(game) {
  const previous = useRef(game?.event_seq ?? null);
  const [event, setEvent] = useState(null);
  useEffect(() => {
    const seq = game?.event_seq ?? null;
    if (seq != null && previous.current != null && seq > previous.current) {
      const next = game.log?.[game.log.length - 1] || null;
      setEvent(next);
      const timer = setTimeout(() => setEvent(null), 760);
      previous.current = seq;
      return () => clearTimeout(timer);
    }
    previous.current = seq;
  }, [game?.event_seq]); // eslint-disable-line react-hooks/exhaustive-deps
  return event;
}

function Piece({ kind, owner, pearlPid, node, interactive, selected, legal, motion, onActivate }) {
  const point = pointOf(node);
  const pearl = owner === pearlPid;
  const classes = ["pi-piece", `pi-${kind}`, pearl ? "pi-pearl" : "pi-obsidian"];
  if (interactive) classes.push("interactive");
  if (selected) classes.push("selected");
  if (legal) classes.push("legal");
  if (motion?.kind === "move_ring" && kind === "ring" && motion.to === node && motion.pid === owner) classes.push("pi-moving");
  if (motion?.kind === "move_ring" && kind === "marker" && motion.from === node) classes.push("pi-dropping");
  if (motion?.kind === "remove_row" && kind === "marker" && (motion.cells || []).includes(node)) classes.push("pi-scoring-marker");
  if (motion?.kind === "remove_ring" && kind === "ring" && motion.at === node) classes.push("pi-scoring-ring");
  const source = motion?.kind === "move_ring" && motion.to === node ? pointOf(motion.from) : point;
  const flippedIndex = motion?.kind === "move_ring" ? (motion.flipped || []).indexOf(node) : -1;
  if (flippedIndex >= 0) classes.push("pi-flipping");
  return <g transform={`translate(${point.x} ${point.y})`} className={classes.join(" ")}
    style={{ "--dx": `${source.x - point.x}px`, "--dy": `${source.y - point.y}px`, "--flip-i": Math.max(0, flippedIndex) }}>
    {kind === "marker" ? <>
      <circle r="18" className="pi-marker-edge" />
      <circle r="15" className="pi-marker-face" />
    </> : <>
      <circle r="27" className="pi-ring-shadow" />
      <circle r="23" className="pi-ring-face" />
      <circle r="12" className="pi-ring-hole" />
    </>}
    {interactive && <circle r="35" className="pi-hit" role="button" tabIndex="0"
      aria-label={`${kind === "ring" ? "Ring" : "Intersection"} ${node}`}
      onClick={onActivate} onKeyDown={(event) => {
        if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onActivate(); }
      }} />}
  </g>;
}

function Board({ game, myId, onMove, connected }) {
  const legal = game.legal_moves || [];
  const [selected, setSelected] = useState(null);
  const [busy, setBusy] = useState(false);
  const motion = useMotionEvent(game);
  const autoKey = useRef("");
  const pearlPid = game.order?.[0];
  const scoreSlots = game.mode === "blitz" ? [0] : [0, 1, 2];
  const rotated = game.order?.[1] === myId;
  const ringsAt = useMemo(() => {
    const map = new Map();
    Object.entries(game.rings || {}).forEach(([owner, nodes]) => nodes.forEach((node) => map.set(node, owner)));
    return map;
  }, [game.rings]);
  const markersAt = useMemo(() => new Map(Object.entries(game.markers || {}).map(([node, owner]) => [Number(node), owner])), [game.markers]);
  const placement = useMemo(() => new Map(legal.filter((m) => m.action === "place_ring").map((m) => [m.at, m])), [legal]);
  const removal = useMemo(() => new Map(legal.filter((m) => m.action === "remove_ring").map((m) => [m.at, m])), [legal]);
  const ringMoves = useMemo(() => legal.filter((m) => m.action === "move_ring"), [legal]);
  const destinations = useMemo(() => new Map(ringMoves.filter((m) => m.from === selected).map((m) => [m.to, m])), [ringMoves, selected]);
  const rowMoves = useMemo(() => legal.filter((m) => m.action === "remove_row"), [legal]);

  useEffect(() => { setBusy(false); setSelected(null); }, [game.event_seq]);
  useEffect(() => {
    const forced = legal.length === 1 && ["remove_row", "remove_ring", "pass"].includes(legal[0].action);
    if (!forced || !connected || busy) return;
    const key = `${game.event_seq}:${moveKey(legal[0])}`;
    if (autoKey.current === key) return;
    autoKey.current = key;
    const timer = setTimeout(() => { setBusy(true); onMove(legal[0]); }, legal[0].action === "remove_row" ? 520 : 260);
    return () => clearTimeout(timer);
  }, [legal, connected, busy, game.event_seq, onMove]);

  const choose = (move) => {
    if (!move || busy || !connected) return;
    setBusy(true);
    onMove(move);
  };
  const activateNode = (node) => {
    if (placement.has(node)) return choose(placement.get(node));
    if (removal.has(node)) return choose(removal.get(node));
    if (destinations.has(node)) return choose(destinations.get(node));
    if (ringMoves.some((move) => move.from === node)) return setSelected((current) => current === node ? null : node);
  };
  const ringInteractive = (node, owner) => owner === myId && (removal.has(node) || ringMoves.some((move) => move.from === node));
  const boardClass = `pi-board-svg${rotated ? " rotated" : ""}${busy ? " busy" : ""}`;

  return <div className="pi-board-frame">
    <svg className={boardClass} viewBox="-520 -500 1040 1000" role="group" aria-label="Pinch board">
      <defs>
        <radialGradient id="pi-board-glow"><stop offset="0" stopColor="#263139" /><stop offset="1" stopColor="#0d1216" /></radialGradient>
        <filter id="pi-soft"><feGaussianBlur stdDeviation="8" /></filter>
      </defs>
      <rect x="-505" y="-485" width="1010" height="970" rx="76" className="pi-board-ground" />
      <ellipse cx="0" cy="0" rx="430" ry="380" className="pi-board-aura" />
      <g className="pi-grid">
        {EDGES.map(([a, b]) => { const p = pointOf(a); const q = pointOf(b); return <line key={`${a}-${b}`} x1={p.x} y1={p.y} x2={q.x} y2={q.y} />; })}
        {NODES.map((_, node) => { const p = pointOf(node); return <circle key={node} cx={p.x} cy={p.y} r="4" />; })}
      </g>

      <g className="pi-score-rail pi-score-top">
        <text x="0" y="-451">{game.players?.[game.order?.[rotated ? 0 : 1]] || "OPPONENT"}</text>
        {scoreSlots.map((i) => <circle key={i} cx={(i - (scoreSlots.length - 1) / 2) * 70} cy="-420" r="22"
          className={i < (game.removed?.[game.order?.[rotated ? 0 : 1]] || 0) ? "filled" : ""} />)}
      </g>
      <g className="pi-score-rail pi-score-bottom">
        <text x="0" y="467">{game.players?.[game.order?.[rotated ? 1 : 0]] || "YOU"}</text>
        {scoreSlots.map((i) => <circle key={i} cx={(i - (scoreSlots.length - 1) / 2) * 70} cy="420" r="22"
          className={i < (game.removed?.[game.order?.[rotated ? 1 : 0]] || 0) ? "filled" : ""} />)}
      </g>

      <g className="pi-board-content" transform={rotated ? "rotate(180)" : undefined}>
        {placement.size > 0 && NODES.map((_, node) => placement.has(node) ? <Piece key={`p-${node}`} kind="target" owner={pearlPid} pearlPid={pearlPid} node={node} interactive legal onActivate={() => activateNode(node)} /> : null)}
        {[...markersAt].map(([node, owner]) => <Piece key={`m-${node}`} kind="marker" owner={owner} pearlPid={pearlPid} node={node}
          motion={motion} />)}
        {[...ringsAt].map(([node, owner]) => <Piece key={`r-${node}`} kind="ring" owner={owner} pearlPid={pearlPid} node={node}
          interactive={ringInteractive(node, owner)} selected={selected === node} legal={removal.has(node)}
          motion={motion} onActivate={() => activateNode(node)} />)}
        {[...destinations].map(([node]) => ringsAt.has(node) || markersAt.has(node) ? null : <Piece key={`d-${node}`} kind="target" owner={pearlPid} pearlPid={pearlPid} node={node} interactive legal onActivate={() => activateNode(node)} />)}
        {rowMoves.map((move, index) => {
          const start = pointOf(move.cells[0]); const end = pointOf(move.cells[4]);
          return <g className="pi-row-choice" key={moveKey(move)} role="button" tabIndex="0"
            aria-label={`Score highlighted row ${index + 1}`} onClick={() => choose(move)}
            onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); choose(move); } }}>
            <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} className="pi-row-halo" />
            <line x1={start.x} y1={start.y} x2={end.x} y2={end.y} className="pi-row-hit" />
          </g>;
        })}
        {motion?.kind === "remove_row" && (motion.cells || []).map((node) => <Piece key={`ghost-${motion.seq}-${node}`} kind="marker" owner={motion.pid} pearlPid={pearlPid} node={node}
          motion={motion} />)}
        {motion?.kind === "remove_ring" && <Piece key={`ghost-ring-${motion.seq}`} kind="ring" owner={motion.pid} pearlPid={pearlPid} node={motion.at}
          motion={motion} />}
      </g>
    </svg>
  </div>;
}

function phaseCopy(game, myId, connected) {
  if (!connected) return ["Reconnecting", "Your position is safe."];
  if (game.phase === "over") return [game.winner === myId ? "Victory" : game.winner ? "Game complete" : "Draw", "The final position is locked."];
  if (game.pending_pid) {
    const mine = game.pending_pid === myId;
    if (game.pending_kind === "choose_row") return [mine ? "Choose a row" : "Scoring in progress", mine ? "Select the line of five to remove." : "Your opponent is choosing a line."];
    return [mine ? "Remove a ring" : "Scoring in progress", mine ? "Choose the ring that becomes your point." : "Your opponent is choosing a ring."];
  }
  if (game.phase === "setup") return [game.turn_pid === myId ? "Place a ring" : "Opening position", game.turn_pid === myId ? "Choose any open intersection." : "Your opponent is placing a ring."];
  return [game.turn_pid === myId ? "Your move" : "Opponent’s move", game.turn_pid === myId ? "Select a ring, then its destination." : "Watch the board reshape."];
}

function PlayerRail({ game, pid, myId }) {
  const pearl = game.order?.[0] === pid;
  const active = game.turn_pid === pid || game.pending_pid === pid;
  return <section className={`pi-player${pid === myId ? " mine" : ""}${active ? " active" : ""}`}>
    <span className={`pi-color-token ${pearl ? "pearl" : "obsidian"}`} aria-hidden="true" />
    <div><small>{pid === myId ? "YOU" : "OPPONENT"}</small><strong>{game.players?.[pid] || "Player"}</strong></div>
    <div className="pi-player-score"><b>{game.removed?.[pid] || 0}</b><span>rings scored</span></div>
  </section>;
}

function logText(entry, names) {
  const who = names?.[entry.pid] || "A player";
  if (entry.kind === "start") return `${modeLabel(entry.mode)} table opened.`;
  if (entry.kind === "place_ring") return `${who} places a ring.`;
  if (entry.kind === "setup_complete") return "The opening position is set.";
  if (entry.kind === "move_ring") return `${who} moves a ring${entry.flipped?.length ? ` and flips ${entry.flipped.length} marker${entry.flipped.length === 1 ? "" : "s"}` : ""}.`;
  if (entry.kind === "remove_row") return `${who} scores a row of five.`;
  if (entry.kind === "remove_ring") return `${who} removes ring ${entry.score}.`;
  if (entry.kind === "pass") return `${who} has no legal ring move and passes.`;
  if (entry.kind === "concede") return `${who} concedes.`;
  if (entry.kind === "game_over") return entry.pid ? `${names?.[entry.pid] || "A player"} wins.` : "The game ends in a draw.";
  return "The position changes.";
}

function GameView({ room, myId, connected, onMove, onExit, onRules, onAbandon }) {
  const game = room.game;
  const [heading, detail] = phaseCopy(game, myId, connected);
  const other = game.order.find((pid) => pid !== myId) || game.order[1];
  const winTarget = game.mode === "blitz" ? 1 : 3;
  return <div className="app pinch pi-game" style={ACCENT}>
    <style>{styles}</style>
    <LobbyHeader title="Pinch" menu={<GameMenu onLeave={onExit} onRules={onRules}
      onAbandon={game.phase === "over" ? null : onAbandon} />} user={<span className={`pi-live-dot${connected ? "" : " lost"}`}><i />{connected ? "Live" : "Reconnecting…"}</span>} />
    <main className="pi-live-grid">
      <div className="pi-opponent"><PlayerRail game={game} pid={other} myId={myId} /></div>
      <div className="pi-self"><PlayerRail game={game} pid={myId} myId={myId} /></div>
      <section className="pi-center">
        <div className="pi-table-head"><div><span>{modeLabel(game.mode)} · first to {winTarget}</span><strong>{heading}</strong></div><p>{detail}</p></div>
        <Board game={game} myId={myId} onMove={onMove} connected={connected} />
        <div className="pi-decision" aria-live="polite"><b>{heading}</b><span>{detail}</span></div>
      </section>
      <aside className="pi-side">
        <div className="pi-mark"><span className="pi-mark-ring" />PINCH</div>
        <div className="pi-mode-card"><small>MARKER POOL</small><strong>{game.marker_pool}</strong><span>of 51 remaining</span></div>
        <details className="pi-log" open>
          <summary>Move log</summary>
          <div>{(game.log || []).slice().reverse().map((entry) => <p key={entry.seq}>{logText(entry, game.players)}</p>)}</div>
        </details>
      </aside>
    </main>
    {game.phase === "over" && <div className="pi-result" role="dialog" aria-modal="true">
      <div><span>{game.result === "concession" ? "TABLE CLOSED" : game.winner ? "FINAL RING" : "EVEN POSITION"}</span>
        <h2>{game.winner ? `${game.players?.[game.winner] || "Player"} wins` : "Draw"}</h2>
        <p>{Object.entries(game.removed || {}).map(([pid, score]) => `${game.players?.[pid] || pid} ${score}`).join(" · ")}</p>
        <button type="button" className="pi-primary" onClick={onExit}>Return to lobby</button>
      </div>
    </div>}
  </div>;
}

function Lobby({ myId, authUser, openGames, myGames, history, refreshing, onRefresh,
  onCreate, onJoin, onLeave, onCancel, onExit, onRules }) {
  const active = notWaiting(myGames);
  const [tab, setTab] = useState("open");
  const [shownHistory, sentinel] = useProgressiveList(history);
  return <div className="app pinch" style={ACCENT}><style>{styles}</style>
    <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="pinch"><LobbyCreateRow onCreate={onCreate} onJoin={onJoin}
        onRefresh={onRefresh} refreshing={refreshing} onRules={onRules} /></LobbyHero>
      <LobbyTabs value={tab} onChange={setTab} tabs={[
        { key: "open", label: "Open", count: openGames.length || null },
        { key: "active", label: "Active", count: active.length || null },
        { key: "history", label: "History", count: history.length || null },
      ]} />
      <div className={`lby-cols tab-${tab}`}>
        <section className="lby-col-open"><LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
          {!openGames.length && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
          <div className="lby-list">{openGames.map((game) => <div className="lby-card" key={game.id}>
            <div className="lby-card-info"><LobbyOpenTitle game={game} myId={myId} />
              <div className="lby-card-meta">{game.id} · {modeLabel(game.mode)} · {timeAgo(game.updated_at)}</div></div>
            <div className="lby-card-actions"><LobbyOpenActions state={seatStateOf(game, myId)}
              onReturn={() => onJoin(game.id)} onJoin={() => onJoin(game.id)}
              onLeave={() => onLeave(game.id)} onCancel={() => onCancel(game.id)} /></div>
          </div>)}</div>
        </section>
        <section className="lby-col-active"><LobbySectionHd title="Active Games" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          <div className="lby-list">{active.map((game) => <div className="lby-card" key={game.id}>
            <div className="lby-card-info"><LobbyMatchup seats={[
              { name: game.player1_name || "Player", you: game.player1_id === myId },
              { name: game.player2_name || "Opponent", you: game.player2_id === myId },
            ]} /><div className="lby-card-meta">{modeLabel(game.mode)}<LobbyBotTier tier={game.ai_difficulty} labels={PINCH_AI_LABELS} /></div></div>
            <div className="lby-card-actions">{game.your_turn && <TurnBadge mine>Your turn</TurnBadge>}<LobbyAction onClick={() => onJoin(game.id)}>Resume</LobbyAction></div>
          </div>)}</div>
        </section>
        <section className="lby-col-history"><LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser && !authUser.guest ? "Your finished games will appear here." : "Log in to keep your game history."}</LobbyEmpty>}
          <div className="lby-list">{shownHistory.map((game) => <div className="lby-card lby-card-hist" key={game.id}>
            <div className="lby-card-info"><div className="lby-card-title">{game.outcome || "finished"} · {modeLabel(game.mode)}</div>
              <div className="lby-card-meta">{game.turns || 0} turns<LobbyBotTier tier={game.ai_difficulty} labels={PINCH_AI_LABELS} /></div></div>
            <div className="lby-card-actions"><LobbyAction kind="secondary" onClick={() => onJoin(game.id)}>Review</LobbyAction></div>
          </div>)}{sentinel}</div>
        </section>
      </div>
    </div></div>
  </div>;
}

export default function Pinch({ myId, authUser, onExit }) {
  const initialRoom = deepRoom();
  const [screen, setScreen] = useState(initialRoom ? "game" : "lobby");
  const [roomId, setRoomId] = useState(initialRoom || "");
  const [roomData, setRoomData] = useState(null);
  const [connected, setConnected] = useState(false);
  const [toast, setToast] = useState("");
  const [showCreate, setShowCreate] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");
  const [createMode, setCreateMode] = useState("standard");
  const [createDifficulty, setCreateDifficulty, rememberDifficulty] =
    useLastDifficulty("pinch", myId, PINCH_AI_TIERS, "easy");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("pinch", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("pinch", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("pinch", myId, "history", []));
  const [refreshing, setRefreshing] = useState(false);
  const wsRef = useRef(null);
  const roomRef = useRef(roomId);
  const tokenRef = useRef("");
  const intentRef = useRef(initialRoom ? "reconnect" : "join");
  const createRef = useRef(null);
  const urlAttempt = useRef(Boolean(initialRoom));
  roomRef.current = roomId;
  useListFade();

  const fetchGames = useCallback(async () => {
    setRefreshing(true);
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    try {
      const [open, mine, old] = await Promise.all([
        fetch(`${HTTP_BASE}/pinch/games`).then((r) => r.json()),
        fetch(`${HTTP_BASE}/pinch/games/mine?player_id=${encodeURIComponent(myId)}`, { headers }).then((r) => r.ok ? r.json() : { games: [] }),
        fetch(`${HTTP_BASE}/pinch/games/history`, { headers }).then((r) => r.ok ? r.json() : { games: [] }),
      ]);
      const nextOpen = open.games || [], nextMine = mine.games || [], nextHistory = old.games || [];
      setOpenGames(nextOpen); setMyGames(nextMine); setHistory(nextHistory);
      writeLobbyCache("pinch", myId, "open", nextOpen);
      writeLobbyCache("pinch", myId, "mine", nextMine);
      writeLobbyCache("pinch", myId, "history", nextHistory);
    } catch { setToast("Could not refresh Pinch tables."); }
    finally { setRefreshing(false); }
  }, [authUser, myId]);
  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  const handleMessage = useCallback((message) => {
    if (message.type === "error") { setToast(message.message || "Pinch rejected that action."); return; }
    if (message.room) {
      setToast(""); setRoomData(message.room); setScreen("game");
      intentRef.current = "reconnect"; urlAttempt.current = false;
      const rid = message.room.room_id || roomRef.current;
      const token = message.room.reconnect_tokens?.[myId];
      if (token && rid) { tokenRef.current = token; try { localStorage.setItem(`${TOKEN_PREFIX}${rid}`, token); } catch {} }
      if (rid) { try { pushPath(buildPath("pinch", rid)); } catch {} }
    }
  }, [myId]);

  const connect = useCallback(() => {
    const rid = roomRef.current;
    if (!rid) return;
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(`${WS_BASE}/pinch/ws/${encodeURIComponent(rid)}/${encodeURIComponent(myId)}`);
    wsRef.current = ws;
    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      setConnected(true);
      const stored = tokenRef.current || (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })();
      const first = intentRef.current === "create"
        ? { action: "create", name: playerName(authUser?.name), ...(createRef.current || {}) }
        : stored ? { action: "reconnect", token: stored }
          : { action: "join", name: playerName(authUser?.name), session_token: authUser?.session_token || null };
      ws.send(JSON.stringify(first));
    };
    ws.onmessage = (event) => { if (wsRef.current === ws) { try { handleMessage(JSON.parse(event.data)); } catch {} } };
    ws.onclose = () => { if (wsRef.current === ws) setConnected(false); };
  }, [authUser, handleMessage, myId]);
  const socketReady = useCallback(() => wsRef.current?.readyState ?? 3, []);
  useAutoReconnect({ enabled: !!roomId && screen === "game", connected, connect, socketReady });

  const openRoom = useCallback((raw, intent, payload = null) => {
    const rid = String(raw || "").trim().toUpperCase();
    if (!rid) return;
    const stored = intent === "join" ? (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })() : "";
    setRoomId(rid); roomRef.current = rid; setRoomData(null); setConnected(false); setToast(""); setScreen("game");
    intentRef.current = stored ? "reconnect" : intent; tokenRef.current = stored; createRef.current = payload; urlAttempt.current = true;
    connect();
  }, [connect]);

  useEffect(() => {
    if (!initialRoom) return undefined;
    tokenRef.current = (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${initialRoom}`) || ""; } catch { return ""; } })();
    connect();
    return () => { try { wsRef.current?.close(); } catch {} };
  // Deep link is consumed once; later transitions call openRoom.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const leaveToLobby = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; roomRef.current = ""; setRoomId(""); setRoomData(null); setConnected(false); setScreen("lobby");
    try { pushPath(buildPath("pinch")); } catch {}
  }, []);
  useEffect(() => subscribe((route) => {
    if (route.game !== "pinch") return;
    if (!route.room) { if (screen !== "lobby") leaveToLobby(); return; }
    if (route.room !== roomRef.current) openRoom(route.room, "join");
  }), [leaveToLobby, openRoom, screen]);

  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("pinch", myId, "mine", rid, setMyGames);
    fetchGames();
  });

  const send = useCallback((payload) => { try { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(payload)); } catch {} }, []);
  const createGame = useCallback(() => {
    setShowCreate(false);
    if (createOpp === "ai") rememberDifficulty(createDifficulty);
    openRoom(roomCode(), "create", { vs_ai: createOpp === "ai", ai_difficulty: createDifficulty, mode: createMode });
  }, [createDifficulty, createMode, createOpp, openRoom, rememberDifficulty]);
  const cancelGame = useCallback(async (id) => {
    try {
      const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
      const roomToken = readRoomToken(`${TOKEN_PREFIX}${id}`); if (roomToken) headers["X-Room-Token"] = roomToken;
      const response = await fetch(`${HTTP_BASE}/pinch/games/${id}?player_id=${encodeURIComponent(myId)}`, { method: "DELETE", headers });
      const data = await response.json(); if (!data.ok) throw new Error(data.message || "Could not cancel"); fetchGames();
    } catch (error) { setToast(error.message || "Could not cancel"); }
  }, [authUser, fetchGames, myId]);
  const leaveSeat = useCallback(async (id) => {
    try {
      await leaveOpenSeat({ endpoint: `${HTTP_BASE}/pinch/games`, roomId: id, playerId: myId,
        tokenKey: `${TOKEN_PREFIX}${id}`, sessionToken: authUser?.session_token });
      fetchGames();
    } catch (error) { setToast(error.message || "Could not leave that table"); }
  }, [authUser, fetchGames, myId]);

  const rulesModal = showRules && <div className="pinch pi-overlay" style={ACCENT}><RulesModal title="How to play — Pinch" onClose={() => setShowRules(false)}><PinchRules /></RulesModal></div>;
  if (screen === "lobby") return <><Lobby {...{ myId, authUser, openGames, myGames, history, refreshing,
    onRefresh: fetchGames, onCreate: () => setShowCreate(true), onJoin: (id) => openRoom(id, "join"),
    onLeave: leaveSeat, onCancel: cancelGame, onExit, onRules: () => setShowRules(true) }} />
    {showCreate && <div className="pinch pi-overlay" style={ACCENT}><CreateModal title="New Pinch game" onClose={() => setShowCreate(false)}>
      <CmRow label="Opponent"><CmSeg value={createOpp} onChange={setCreateOpp} options={[
        { value: "friend", label: "VS Friend" }, { value: "ai", label: "VS AI" },
      ]} /></CmRow>
      {createOpp === "ai" && <CmRow label="AI difficulty"><CmSeg value={createDifficulty} onChange={setCreateDifficulty} options={PINCH_AI_TIER_OPTIONS} /></CmRow>}
      <CmRow label="Mode"><CmSeg value={createMode} onChange={setCreateMode} options={MODES} /></CmRow>
      <div className="cm-footer"><span className="cm-summary">{modeLabel(createMode)} · <b>{createOpp === "ai" ? "Easy AI" : "Friend"}</b></span>
        <button type="button" className="cm-create" onClick={createGame}>Create Game</button></div>
    </CreateModal></div>}
    {rulesModal}{toast && <div className="pi-toast" role="status">{toast}</div>}</>;

  if (!roomData) return <div className="app pinch pi-connecting" style={ACCENT}><style>{styles}</style>
    <LobbyHeader title="Pinch" onBack={leaveToLobby} /><div><span className="pi-mark-ring" /><h1>{toast ? "That table stayed closed." : "Aligning the board…"}</h1>
      <p role="status">{toast || "Connecting to the authoritative game state."}</p><button type="button" className="pi-primary" onClick={leaveToLobby}>Return to lobby</button></div>{rulesModal}</div>;

  if (!roomData.game) return <div className="app pinch" style={ACCENT}><style>{styles}</style>
    <WaitingRoom game="pinch" roomId={roomData.room_id} players={roomData.players}
      hostId={roomData.host} myId={myId} min={2} max={2}
      note={`${modeLabel(roomData.mode)} · two players · no hidden information.`}
      user={authUser} onLeave={leaveToLobby} onRules={() => setShowRules(true)}
      onStart={() => send({ action: "start" })} canStart={connected} blockedLabel="Reconnecting…" />
    {rulesModal}</div>;

  return <><GameView room={roomData} myId={myId} connected={connected}
    onMove={(move) => send({ action: "move", move })} onExit={leaveToLobby}
    onRules={() => setShowRules(true)} onAbandon={() => send({ action: "abandon" })} />
    {rulesModal}{toast && <div className="pi-toast" role="status">{toast}</div>}</>;
}
