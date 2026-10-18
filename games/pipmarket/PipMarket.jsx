import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbyHero, LobbyCreateRow, LobbyUser, LobbySectionHd,
  LobbyEmpty, LobbyAction, LobbyTabs, LobbyMatchup, LobbyBotTier, TurnBadge,
  LobbyOpenTitle, LobbyOpenActions, seatStateOf, notWaiting, timeAgo,
  CreateModal, CmRow, CmSeg, RulesModal, GameMenu,
  createModalCss, lobbyCreateRowCss, rulesModalCss, gameMenuCss,
  WaitingRoom, waitingRoomCss, useProgressiveList, useListFade,
  readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame, useLastDifficulty,
  LobbyOpenHd, LobbyActiveHd, LobbyNoOpen, LobbyNoActive,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { buildPath, pushPath, subscribe } from "../../shared/router.js";
import { leaveOpenSeat, readRoomToken } from "../../shared/roomLifecycle.js";
// The tiers this picker offers live in shared/botTiers.js, beside every other
// game's: the profile page names them too, off the same list.
import { PIPMARKET_AI_TIER_OPTIONS } from "../../shared/botTiers.js";
import PipMarketRules from "./rules.jsx";
import cssText from "./PipMarket.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const HTTP_BASE = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "");
const styles = baseCss + lobbyCss + createModalCss + lobbyCreateRowCss
  + rulesModalCss + gameMenuCss + waitingRoomCss + cssText;
const ACCENT = { "--lby-accent": GAME_ACCENTS.pipmarket };
const TOKEN_PREFIX = "pipmarket_token_";
const PM_AI_TIERS = PIPMARKET_AI_TIER_OPTIONS.map((tier) => tier.value);
const PM_AI_LABELS = Object.fromEntries(PIPMARKET_AI_TIER_OPTIONS.map((tier) => [tier.value, tier.label]));

const SPAN = 6;
// A board is drawn in a fixed 8x8 frame: the dice can span six cells, and a new
// pair can reach up to two cells past them, so the window never needs more.
const FRAME = 8;
const SEAT_COLORS = ["#f2917c", "#7cc6f2", "#b9e27a", "#c9a0f5"];
const STALLS = "ABCDE";
const PIPS = { 1: [4], 2: [2, 6], 3: [2, 4, 6], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };
const SLOTS = [0, 1, 2, 3, 4, 5, 6, 7, 8];

// ── geometry (mirrors engine.py; the server re-validates every move) ─────────
const keyOf = (r, c) => `${r},${c}`;

function boundsOf(cells) {
  if (!cells.length) return null;
  let r0 = Infinity, r1 = -Infinity, c0 = Infinity, c1 = -Infinity;
  for (const [r, c] of cells) { r0 = Math.min(r0, r); r1 = Math.max(r1, r); c0 = Math.min(c0, c); c1 = Math.max(c1, c); }
  return { r0, r1, c0, c1 };
}
const fits = (cells) => { const b = boundsOf(cells); return !b || (b.r1 - b.r0 < SPAN && b.c1 - b.c0 < SPAN); };
const NEIGHBOURS = [[-1, 0], [1, 0], [0, -1], [0, 1]];

function windowFor(board) {
  if (!board.length) return { r0: 0, r1: 3, c0: 0, c1: 3 };
  const b = boundsOf(board.map((d) => [d.r, d.c]));
  return {
    r0: Math.max(b.r0 - 2, b.r1 - (SPAN - 1)), r1: Math.min(b.r1 + 2, b.r0 + SPAN - 1),
    c0: Math.max(b.c0 - 2, b.c1 - (SPAN - 1)), c1: Math.min(b.c1 + 2, b.c0 + SPAN - 1),
  };
}

function placementsFor(board, k) {
  const occ = new Set(board.map((d) => keyOf(d.r, d.c)));
  const out = [];
  if (!occ.size) {
    const w = windowFor(board);
    for (let r = w.r0; r <= w.r1; r++) for (let c = w.c0; c <= w.c1; c++) {
      if (k === 1) { out.push([[r, c]]); continue; }
      for (const [dr, dc] of NEIGHBOURS) {
        const q = [r + dr, c + dc];
        if (q[0] >= w.r0 && q[0] <= w.r1 && q[1] >= w.c0 && q[1] <= w.c1) out.push([[r, c], q]);
      }
    }
    return out;
  }
  const cells = board.map((d) => [d.r, d.c]);
  const frontier = new Map();
  for (const d of board) for (const [dr, dc] of NEIGHBOURS) {
    const q = [d.r + dr, d.c + dc];
    if (!occ.has(keyOf(...q))) frontier.set(keyOf(...q), q);
  }
  for (const p of frontier.values()) {
    if (k === 1) { if (fits([...cells, p])) out.push([p]); continue; }
    for (const [dr, dc] of NEIGHBOURS) {
      const q = [p[0] + dr, p[1] + dc];
      if (occ.has(keyOf(...q))) continue;
      if (fits([...cells, p, q])) { out.push([p, q]); if (!frontier.has(keyOf(...q))) out.push([q, p]); }
    }
  }
  return out;
}

function moneyFaces(m) {
  const out = [];
  let left = Math.max(0, m | 0);
  while (left > 0) { out.push(Math.min(6, left)); left -= 6; }
  return out;
}

function roomCode() {
  return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
}

function deepRoom() {
  try {
    const match = /\/pipmarket\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    return match ? match[1].toUpperCase() : null;
  } catch { return null; }
}

const prefersReducedMotion = () => {
  try { return window.matchMedia?.("(prefers-reduced-motion: reduce)").matches; } catch { return false; }
};

// ── dice ─────────────────────────────────────────────────────────────────────
function Die({ id, face, kind = "ivory", className = "", style, onClick, label }) {
  const on = PIPS[face] || [];
  const tracked = id != null ? { "data-die": id, "data-face": face } : {};
  const Tag = onClick ? "button" : "span";
  return <Tag type={onClick ? "button" : undefined} className={`pm-die pm-die-${kind} ${className}`} style={style}
    onClick={onClick} aria-label={label || `die showing ${face}`} {...tracked}>
    {SLOTS.map((i) => <i key={i} className={on.includes(i) ? "on" : undefined} />)}
  </Tag>;
}

// A die built straight in the DOM for the flight layer — the same markup as <Die>.
function dieNode(face, extra = "") {
  const el = document.createElement("span");
  el.className = `pm-die pm-die-ivory pm-flying ${extra}`;
  setNodeFace(el, face);
  return el;
}
function setNodeFace(el, face) {
  const on = PIPS[face] || [];
  el.replaceChildren(...SLOTS.map((i) => { const pip = document.createElement("i"); if (on.includes(i)) pip.className = "on"; return pip; }));
}

function MoneyDice({ amount, pid }) {
  const faces = moneyFaces(amount);
  return <span className="pm-money" data-money={pid}>
    <span className="pm-money-dice">{faces.length ? faces.map((f, i) => <Die key={i} face={f} kind="gold" />)
      : <span className="pm-money-empty" />}</span>
    <b key={amount} className="pm-money-n">{amount}</b>
  </span>;
}

// ── the moving parts: every die flies from where it was to where it is ──────
function measureDice(root) {
  const snap = new Map();
  if (!root) return snap;
  root.querySelectorAll("[data-die]").forEach((el) => {
    const r = el.getBoundingClientRect();
    if (r.width) snap.set(el.dataset.die, { x: r.left, y: r.top, w: r.width, h: r.height, face: Number(el.dataset.face) });
  });
  return snap;
}

function flyDice(root, layer, snap) {
  if (!root || !layer) return;
  const movers = [];
  root.querySelectorAll("[data-die]").forEach((el) => {
    const before = snap.get(el.dataset.die);
    if (!before) return;
    const after = el.getBoundingClientRect();
    if (!after.width) return;
    const face = Number(el.dataset.face);
    const dx = before.x - after.left, dy = before.y - after.top;
    const rolled = before.face !== face;
    if (Math.abs(dx) < 1.5 && Math.abs(dy) < 1.5 && Math.abs(before.w - after.width) < 1.5 && !rolled) return;
    movers.push({ el, before, after, face, rolled, dist: Math.hypot(dx, dy) });
  });
  movers.sort((a, b) => a.after.top - b.after.top || a.after.left - b.after.left);
  movers.forEach((m, index) => {
    const { el, before, after, face, rolled, dist } = m;
    const clone = dieNode(rolled ? before.face : face, rolled ? "rolling" : "");
    Object.assign(clone.style, { left: `${after.left}px`, top: `${after.top}px`, width: `${after.width}px`, height: `${after.height}px` });
    clone.style.setProperty("--d", `${after.width}px`);
    layer.appendChild(clone);
    // opacity, not visibility: a pip's own `visibility:visible` would show through.
    el.style.opacity = "0";
    const dx = before.x - after.left, dy = before.y - after.top, s = before.w / after.width;
    const lift = dist < 90 ? dist * 0.25 : Math.min(110, 16 + dist * 0.22);
    const duration = Math.round(520 + Math.min(380, dist * 0.4));
    const delay = rolled ? Math.min(index * 34, 1300) : index * 45;
    const spin = rolled ? 540 + (index % 3) * 120 : (dist > 140 ? (index % 2 ? -14 : 14) : 0);
    const anim = clone.animate([
      { transform: `translate(${dx}px, ${dy}px) scale(${s}) rotate(0deg)` },
      { transform: `translate(${dx * 0.45}px, ${dy * 0.45 - lift}px) scale(${(s + 1) / 2 * 1.16}) rotate(${spin * 0.6}deg)`, offset: 0.5 },
      { transform: `translate(0px, 0px) scale(1) rotate(${spin}deg)` },
    ], { duration, delay, easing: "cubic-bezier(.3,.75,.25,1)", fill: "both" });
    if (rolled) setTimeout(() => setNodeFace(clone, face), delay + duration * 0.55);
    const done = () => { clone.remove(); el.style.opacity = ""; el.classList.add("pm-landed"); setTimeout(() => el.classList.remove("pm-landed"), 380); };
    anim.onfinish = done;
    anim.oncancel = done;
  });
}

function useDiceFlight(game, rootRef, layerRef) {
  const seqRef = useRef(game?.event_seq ?? null);
  const snapRef = useRef(null);
  // Read where every die IS (mid-flight included) before React commits the
  // next position — the render body is the last moment the old DOM exists.
  if (game && game.event_seq !== seqRef.current && rootRef.current && !snapRef.current) {
    snapRef.current = measureDice(rootRef.current);
  }
  useLayoutEffect(() => {
    const prev = seqRef.current;
    seqRef.current = game?.event_seq ?? null;
    const snap = snapRef.current;
    snapRef.current = null;
    if (!snap || prev == null || prev === seqRef.current || prefersReducedMotion()) return;
    layerRef.current?.replaceChildren();
    rootRef.current?.querySelectorAll("[data-die]").forEach((el) => { el.style.opacity = ""; });
    flyDice(rootRef.current, layerRef.current, snap);
  }, [game?.event_seq]); // eslint-disable-line react-hooks/exhaustive-deps
}

// ── the market ──────────────────────────────────────────────────────────────
function Stall({ index, columns, buyable, selected, onPick, myTurn }) {
  return <div className="pm-stall">
    <div className="pm-stall-head"><span className="pm-stall-letter">Stall {STALLS[index]}</span></div>
    <div className="pm-stall-cols">
      {[0, 1, 2, 3, 4].map((slot) => {
        const col = columns[slot];
        if (!col) return <span key={`e${slot}`} className="pm-col empty" aria-hidden="true"><span className="pm-col-dice" /><span className="pm-price">{slot + 1}</span></span>;
        const can = buyable.has(`${index}:${slot}`);
        const isSel = selected && selected.s === index && selected.c === slot;
        return <button type="button" key={col.map((d) => d.id).join("-")}
          className={`pm-col${can ? " buyable" : ""}${isSel ? " selected" : ""}${myTurn && !can ? " locked" : ""}`}
          disabled={!can} onClick={() => onPick(index, slot)}
          aria-label={`Stall ${STALLS[index]}, column ${slot + 1}: ${col.map((d) => d.f).join(" and ")} for ${slot + 1}`}>
          <span className="pm-col-dice">{col.map((d) => <Die key={d.id} id={d.id} face={d.f} />)}</span>
          <span className="pm-price">{slot + 1}</span>
        </button>;
      })}
    </div>
  </div>;
}

// ── a board ─────────────────────────────────────────────────────────────────
function Board({ board, targets, ghost, lit, chosen, onCell, onDie, onCellDouble, compact, label }) {
  const win = windowFor(board);
  const w = win.c1 - win.c0 + 1, h = win.r1 - win.r0 + 1;
  const ox = (FRAME - w) / 2, oy = (FRAME - h) / 2;
  const at = (r, c) => ({ "--x": c - win.c0 + ox, "--y": r - win.r0 + oy });
  const occupied = new Set(board.map((d) => keyOf(d.r, d.c)));
  const ghostAt = new Set((ghost || []).map((g) => keyOf(g.r, g.c)));
  const cells = [];
  for (let r = win.r0; r <= win.r1; r++) for (let c = win.c0; c <= win.c1; c++) {
    const k = keyOf(r, c);
    if (occupied.has(k)) { cells.push(<span key={k} className="pm-cell filled" style={at(r, c)} />); continue; }
    const target = targets?.has(k);
    cells.push(target
      ? <button key={k} type="button" className={`pm-cell target${ghostAt.has(k) ? " previewed" : ""}`} style={at(r, c)}
        onClick={() => onCell?.(r, c)} onDoubleClick={() => onCellDouble?.(r, c)} aria-label={`Place here, row ${r - win.r0 + 1} column ${c - win.c0 + 1}`} />
      : <span key={k} className="pm-cell" style={at(r, c)} />);
  }
  return <div className={`pm-board${compact ? " compact" : ""}`} role="group" aria-label={label}>
    <div className="pm-board-in">
      {cells}
      {board.map((d) => {
        const k = keyOf(d.r, d.c);
        const cls = `${lit?.has(k) ? " lit" : ""}${chosen?.has(k) ? " chosen" : ""}`;
        return <Die key={d.id} id={d.id} face={d.f} className={`on-board${cls}`} style={at(d.r, d.c)}
          onClick={onDie && lit?.has(k) ? () => onDie(d) : undefined} />;
      })}
      {(ghost || []).map((g, i) => <Die key={`g${i}`} face={g.f} className="on-board ghost" style={at(g.r, g.c)} />)}
    </div>
  </div>;
}

function PlayerPanel({ game, pid, myId, seat, isBot, children, mine }) {
  const active = game.turn === pid && game.phase !== "over";
  const passed = game.phase === "scoring" && (game.passed || []).includes(pid);
  const won = game.phase === "over" && (game.winners || []).includes(pid);
  return <section className={`pm-player${mine ? " mine" : ""}${active ? " active" : ""}${passed ? " passed" : ""}${won ? " won" : ""}`}
    style={{ "--seat": SEAT_COLORS[seat % SEAT_COLORS.length] }}>
    <header className="pm-player-head">
      <span className="pm-seat-dot" aria-hidden="true" />
      <div className="pm-player-id">
        <strong>{game.names?.[pid] || "Player"}</strong>
        <small>{mine ? "You" : isBot ? "Bot" : "Player"}{game.first === pid && game.phase !== "over" ? " · opened" : ""}{passed ? " · done scoring" : ""}</small>
      </div>
      <div className="pm-player-score" title="Points scored">
        <b key={game.points?.[pid]}>{game.points?.[pid] || 0}</b><span>pts</span>
      </div>
      <MoneyDice amount={game.money?.[pid] || 0} pid={pid} />
    </header>
    {children}
  </section>;
}

// ── words ───────────────────────────────────────────────────────────────────
function MiniDice({ faces }) {
  return <span className="pm-mini">{(faces || []).map((f, i) => <Die key={i} face={f} kind="mini" />)}</span>;
}

function LogLine({ entry, names }) {
  const who = <b>{names?.[entry.pid] || "A player"}</b>;
  const name = (pid) => <b>{names?.[pid] || "A player"}</b>;
  switch (entry.kind) {
    case "deal": return <p>Round 1. {name(entry.first)} opens the market.</p>;
    case "buy": return <p>{who} buys <MiniDice faces={entry.faces} /> for {entry.price}.</p>;
    case "take": return <p>{who} takes {entry.amount} money.</p>;
    case "market_closed": return <p>Nobody can buy; {entry.left} dice go to the cup.</p>;
    case "scoring": return <p className="pm-log-phase">The market closes. {name(entry.first)} scores first.</p>;
    case "score": return <p>{who} scores <MiniDice faces={Array(entry.count).fill(entry.face)} /> for <em>{entry.points}</em>{entry.money ? ` and ${entry.money} money` : ""}.</p>;
    case "pass": return <p className="pm-log-quiet">{who} {entry.auto ? "has nothing to score" : "stops scoring"}.</p>;
    case "round": return <p className="pm-log-phase">Round {entry.round}. {entry.dice} dice rerolled; {name(entry.first)} opens.</p>;
    case "concede": return <p>{who} leaves the table.</p>;
    case "game_over": {
      const ws = entry.winners || [];
      return <p className="pm-log-phase">{entry.early ? "Nobody scored, so the game ends. " : "The game ends. "}
        {ws.map((p, i) => <span key={p}>{i ? " and " : ""}{name(p)}</span>)} {ws.length > 1 ? "share the win" : "wins"}.</p>;
    }
    default: return null;
  }
}

function moneyBadge(line) {
  return line.money === "max" ? "→18" : `+${line.money}`;
}

// ── the table ───────────────────────────────────────────────────────────────
function GameView({ room, myId, connected, onMove, onExit, onRules, onAbandon, errorNonce }) {
  const game = room.game;
  const rootRef = useRef(null);
  const layerRef = useRef(null);
  useDiceFlight(game, rootRef, layerRef);

  const order = game.players;
  const seatOf = (pid) => Math.max(0, order.indexOf(pid));
  const bots = new Set(room.ai_players || []);
  const seated = order.includes(myId);
  const me = seated ? myId : order[0];
  const rivals = order.filter((pid) => pid !== me);
  const options = game.options;
  const myTurn = connected && options && options.pid === myId;
  const auction = game.phase === "auction";
  const scoring = game.phase === "scoring";

  const [picked, setPicked] = useState(null);          // {s, c}
  const [preview, setPreview] = useState(null);        // {anchor, i}
  const [lineIdx, setLineIdx] = useState(null);
  const [busy, setBusy] = useState(false);
  const [popups, setPopups] = useState([]);
  const [banner, setBanner] = useState(null);
  const [showResult, setShowResult] = useState(true);
  const lastSeq = useRef(game.event_seq);

  useEffect(() => { setPicked(null); setPreview(null); setLineIdx(null); setBusy(false); }, [game.event_seq]);
  useEffect(() => { setBusy(false); }, [errorNonce]);

  const buyable = useMemo(() => new Set(myTurn && auction ? (options.columns || []).map(([s, c]) => `${s}:${c}`) : []), [myTurn, auction, options]);
  const myBoard = game.boards[me] || [];
  const pickedCol = picked ? game.market?.[picked.s]?.[picked.c] : null;
  const places = useMemo(() => pickedCol ? placementsFor(myBoard, pickedCol.length) : [], [pickedCol, myBoard]);
  const targets = useMemo(() => new Set(places.flat().map(([r, c]) => keyOf(r, c))), [places]);
  const candidates = useMemo(() => {
    if (!preview) return [];
    const k = keyOf(...preview.anchor);
    const first = places.filter((p) => keyOf(...p[0]) === k);
    const second = places.filter((p) => p.length > 1 && keyOf(...p[1]) === k);
    return [...first, ...second];
  }, [preview, places]);
  const chosenPlacement = candidates.length ? candidates[preview.i % candidates.length] : null;
  const ghost = chosenPlacement ? chosenPlacement.map(([r, c], i) => ({ r, c, f: pickedCol[i].f })) : null;

  const lines = myTurn && scoring ? options.lines || [] : [];
  const lit = useMemo(() => new Set(lines.flatMap((l) => l.cells.map(([r, c]) => keyOf(r, c)))), [lines]);
  const chosenLine = lineIdx != null ? lines[lineIdx] : null;
  const chosenCells = useMemo(() => new Set((chosenLine?.cells || []).map(([r, c]) => keyOf(r, c))), [chosenLine]);

  const send = useCallback((move) => {
    if (busy || !connected) return;
    setBusy(true);
    onMove(move);
  }, [busy, connected, onMove]);

  const pickColumn = (s, c) => {
    if (picked && picked.s === s && picked.c === c) { setPicked(null); setPreview(null); return; }
    setPicked({ s, c }); setPreview(null);
  };
  const clickCell = (r, c) => {
    if (preview && preview.anchor[0] === r && preview.anchor[1] === c) setPreview({ anchor: [r, c], i: preview.i + 1 });
    else setPreview({ anchor: [r, c], i: 0 });
  };
  const place = useCallback(() => {
    if (!chosenPlacement || !picked) return;
    send({ type: "buy", set: picked.s, col: picked.c, cells: chosenPlacement });
  }, [chosenPlacement, picked, send]);
  const placeAt = (r, c) => {
    const k = keyOf(r, c);
    const p = places.find((x) => keyOf(...x[0]) === k) || places.find((x) => x.some((cell) => keyOf(...cell) === k));
    if (p && picked) send({ type: "buy", set: picked.s, col: picked.c, cells: p });
  };
  const clickDie = (d) => {
    const k = keyOf(d.r, d.c);
    const idxs = lines.map((l, i) => [l, i]).filter(([l]) => l.cells.some(([r, c]) => keyOf(r, c) === k)).map(([, i]) => i);
    if (!idxs.length) return;
    const at = idxs.indexOf(lineIdx);
    setLineIdx(at >= 0 ? idxs[(at + 1) % idxs.length] : idxs[0]);
  };
  const scoreLine = useCallback(() => { if (chosenLine) send({ type: "score", cells: chosenLine.cells }); }, [chosenLine, send]);

  useEffect(() => {
    const onKey = (event) => {
      if (event.target?.closest?.("input,textarea,[role=dialog]")) return;
      if (event.key === "Escape") { setPicked(null); setPreview(null); setLineIdx(null); }
      if ((event.key === "r" || event.key === "R") && preview) setPreview((p) => p && { ...p, i: p.i + 1 });
      // A focused button answers Enter itself; the shortcut is for the board.
      if (event.key === "Enter" && !event.target?.closest?.("button")) { if (chosenPlacement) place(); else if (chosenLine) scoreLine(); }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [preview, chosenPlacement, chosenLine, place, scoreLine]);

  // Popups and banners for whatever just happened — read off the log, so a
  // reconnect or a duplicate broadcast (no new seq) never replays anything.
  useLayoutEffect(() => {
    const prev = lastSeq.current;
    lastSeq.current = game.event_seq;
    if (prev == null || game.event_seq <= prev) return;
    const fresh = (game.log || []).filter((e) => e.seq > prev);
    const root = rootRef.current;
    const next = [];
    const rectOf = (sel) => root?.querySelector(sel)?.getBoundingClientRect();
    for (const e of fresh) {
      const color = SEAT_COLORS[seatOf(e.pid) % SEAT_COLORS.length];
      if (e.kind === "score") {
        const ids = new Set((e.dice || []).map(String));
        const rects = [...(root?.querySelectorAll("[data-die]") || [])].filter((el) => ids.has(el.dataset.die)).map((el) => el.getBoundingClientRect());
        const box = rectOf(`[data-board="${e.pid}"]`);
        const x = box ? box.left + box.width / 2 : (rects[0]?.left || 0);
        const y = box ? box.top + box.height * 0.45 : (rects[0]?.top || 0);
        next.push({ id: `s${e.seq}`, x, y, color, big: `+${e.points}`, small: e.money ? `+${e.money} money` : "" });
      } else if (e.kind === "take" || e.kind === "buy") {
        const r = rectOf(`[data-money="${e.pid}"]`);
        if (r) next.push({ id: `m${e.seq}`, x: r.left + r.width / 2, y: r.top, color: e.kind === "take" ? "#f1c65e" : "#ff9c8a", big: e.kind === "take" ? `+${e.amount}` : `−${e.price}`, small: "", tiny: true });
      } else if (e.kind === "round") {
        setBanner({ id: e.seq, title: `Round ${e.round}`, text: `${e.dice} dice rolled back into the market`, sub: `${game.names?.[e.first] || "A player"} opens` });
      } else if (e.kind === "scoring") {
        setBanner({ id: e.seq, title: "Market closed", text: "Score your lines", sub: `${game.names?.[e.first] || "A player"} goes first` });
      } else if (e.kind === "game_over") {
        setShowResult(true);
      }
    }
    if (next.length && !prefersReducedMotion()) {
      setPopups((cur) => [...cur, ...next]);
      const ids = new Set(next.map((p) => p.id));
      setTimeout(() => setPopups((cur) => cur.filter((p) => !ids.has(p.id))), 1500);
    }
  }, [game.event_seq]); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!banner) return undefined;
    const t = setTimeout(() => setBanner(null), 2100);
    return () => clearTimeout(t);
  }, [banner]);

  const turnName = game.names?.[game.turn] || "A player";
  const status = (() => {
    if (!connected) return ["Reconnecting", "Your seat is safe."];
    if (game.phase === "over") return ["Game over", (game.winners || []).length > 1 ? "A shared win." : `${game.names?.[game.winners?.[0]] || "A player"} wins.`];
    if (myTurn && auction) {
      if (!pickedCol) return ["Your turn", options.columns?.length ? "Pick a pair from a stall, or take 2 money." : "Nothing you can place or afford — take 2 money."];
      if (!ghost) return [`Pair for ${picked.c + 1}`, "Choose a glowing cell on your board."];
      return ["Place it?", candidates.length > 1 ? "Tap the cell again to turn the pair." : "Confirm to buy."];
    }
    if (myTurn && scoring) return ["Score a line", chosenLine ? `${chosenLine.count} × ${chosenLine.face} for ${chosenLine.points}.` : "Pick a lit die or a line below, or stop."];
    if (scoring) return [`${turnName} is scoring`, "Lines come off one at a time."];
    return [`${turnName}'s turn`, bots.has(game.turn) ? "The bot is shopping." : "Waiting on their pick."];
  })();

  const finalRows = game.phase === "over" ? [...order].sort((a, b) => (game.final?.[b] ?? 0) - (game.final?.[a] ?? 0)) : [];

  return <div ref={rootRef} className="app pipmarket pm-game" style={ACCENT}>
    <style>{styles}</style>
    <LobbyHeader title="Pip Market" menu={<GameMenu onLeave={onExit} onRules={onRules}
      onAbandon={game.phase === "over" || !seated ? null : onAbandon} />}
      user={<span className={`pm-live${connected ? "" : " lost"}`}><i />{connected ? "Live" : "Reconnecting…"}</span>} />
    <main className={`pm-table rivals-${rivals.length}`}>
      <section className="pm-market-zone" aria-label="The market">
        <div className="pm-zone-head">
          <div className="pm-rounds" aria-label={`Round ${game.round} of ${game.rounds || 3}`}>
            {[1, 2, 3].map((r) => <span key={r} className={`pm-lantern${r < game.round ? " past" : ""}${r === game.round ? " now" : ""}`}><i />{r}</span>)}
          </div>
          <h2>{game.phase === "over" ? "Market closed" : auction ? "The market" : "Scoring"}</h2>
          <span className="pm-zone-note">{auction ? `${game.market.flat().reduce((n, col) => n + col.length, 0)} dice for sale` : `Round ${game.round} of ${game.rounds || 3}`}</span>
        </div>
        <div className={`pm-market stalls-${game.market.length}`}>
          {game.market.map((cols, s) => <Stall key={s} index={s} columns={cols} buyable={buyable}
            selected={picked} onPick={pickColumn} myTurn={myTurn && auction} />)}
        </div>
      </section>

      <section className="pm-play">
        <PlayerPanel game={game} pid={me} myId={myId} seat={seatOf(me)} isBot={bots.has(me)} mine={seated}>
          <div data-board={me} className="pm-board-wrap">
            <Board board={myBoard} label={seated ? "Your board" : "Board"}
              targets={myTurn && auction && pickedCol ? targets : null} ghost={ghost}
              lit={lit} chosen={chosenCells} onCell={clickCell} onCellDouble={placeAt} onDie={clickDie} />
          </div>
        </PlayerPanel>
        <div className="pm-rivals">
          {rivals.map((pid) => <PlayerPanel key={pid} game={game} pid={pid} myId={myId} seat={seatOf(pid)} isBot={bots.has(pid)}>
            <div data-board={pid} className="pm-board-wrap"><Board board={game.boards[pid] || []} compact label={`${game.names?.[pid]}'s board`} /></div>
          </PlayerPanel>)}
        </div>
      </section>

      <aside className="pm-side">
        <div className={`pm-actions${myTurn ? " yours" : ""}`} aria-live="polite">
          <div className="pm-status"><b>{status[0]}</b><span>{status[1]}</span></div>
          {myTurn && auction && <div className="pm-buttons">
            {pickedCol && <button type="button" className="pm-btn primary" disabled={!ghost || busy} onClick={place}>
              Place · pay {picked.c + 1}</button>}
            {pickedCol && ghost && candidates.length > 1 && <button type="button" className="pm-btn" onClick={() => setPreview((p) => ({ ...p, i: p.i + 1 }))}>Turn pair</button>}
            {pickedCol && <button type="button" className="pm-btn quiet" onClick={() => { setPicked(null); setPreview(null); }}>Cancel</button>}
            {!pickedCol && <button type="button" className="pm-btn primary" disabled={!options.take || busy}
              onClick={() => send({ type: "take" })} title={options.take ? "" : "At 18 you must buy"}>
              {options.take ? `Take ${Math.min(2, (game.max_money || 18) - (game.money?.[myId] || 0))} money` : "At 18 — you must buy"}</button>}
          </div>}
          {myTurn && scoring && <>
            <div className="pm-lines" role="listbox" aria-label="Lines you can score">
              {lines.map((line, i) => <button type="button" key={line.cells.flat().join(".")} role="option" aria-selected={i === lineIdx}
                className={`pm-line${i === lineIdx ? " sel" : ""}`} onClick={() => setLineIdx(i)}>
                <MiniDice faces={Array(line.count).fill(line.face)} />
                <span className="pm-line-pts">{line.points}</span>
                <span className="pm-line-money">{moneyBadge(line)}</span>
              </button>)}
            </div>
            <div className="pm-buttons">
              <button type="button" className="pm-btn primary" disabled={!chosenLine || busy} onClick={scoreLine}>Score line</button>
              <button type="button" className="pm-btn" disabled={busy} onClick={() => send({ type: "pass" })}>Stop scoring</button>
            </div>
          </>}
          {game.phase === "over" && !showResult && <div className="pm-buttons"><button type="button" className="pm-btn primary" onClick={() => setShowResult(true)}>Results</button></div>}
        </div>
        <div className="pm-cup">
          <div className="pm-side-head"><span>The cup</span><small>{game.cup?.length ? "rerolled when the round ends" : "scored dice land here"}</small></div>
          <div className="pm-cup-dice">{(game.cup || []).map((d) => <Die key={d.id} id={d.id} face={d.f} />)}</div>
        </div>
        <details className="pm-log" open>
          <summary>Market log</summary>
          <div>{(game.log || []).slice(-80).reverse().map((entry) => <LogLine key={entry.seq} entry={entry} names={game.names} />)}</div>
        </details>
      </aside>
    </main>

    <div className="pm-fx" ref={layerRef} aria-hidden="true" />
    <div className="pm-popups" aria-hidden="true">
      {popups.map((p) => <span key={p.id} className={`pm-pop${p.tiny ? " tiny" : ""}`} style={{ left: p.x, top: p.y, "--pop": p.color }}>
        <b>{p.big}</b>{p.small && <small>{p.small}</small>}</span>)}
    </div>
    {banner && <div key={banner.id} className="pm-banner" role="status"><div><span>{banner.text}</span><h2>{banner.title}</h2><small>{banner.sub}</small></div></div>}
    {game.phase === "over" && showResult && <div className="pm-result" role="dialog" aria-modal="true" aria-label="Final scores">
      <div className="pm-result-card">
        <span className="pm-result-kicker">{game.conceded ? "Table closed" : "Final tally"}</span>
        <h2>{(game.winners || []).length > 1 ? "A shared win" : `${game.names?.[game.winners?.[0]] || "A player"} wins`}</h2>
        <table className="pm-final">
          <thead><tr><th scope="col">Player</th><th scope="col">Points</th><th scope="col">Money</th><th scope="col">Total</th></tr></thead>
          <tbody>{finalRows.map((pid) => <tr key={pid} className={(game.winners || []).includes(pid) ? "win" : ""} style={{ "--seat": SEAT_COLORS[seatOf(pid) % SEAT_COLORS.length] }}>
            <th scope="row"><i />{game.names?.[pid]}{pid === myId ? " (you)" : ""}</th>
            <td>{game.points?.[pid]}</td><td>{game.money?.[pid]}</td><td><b>{game.final?.[pid]}</b></td>
          </tr>)}</tbody>
        </table>
        <div className="pm-result-actions">
          <button type="button" className="pm-btn" onClick={() => setShowResult(false)}>View the table</button>
          <button type="button" className="pm-btn primary" onClick={onExit}>Return to lobby</button>
        </div>
      </div>
    </div>}
  </div>;
}

// ── the lobby ───────────────────────────────────────────────────────────────
function seatsLabel(game) {
  return `${game.player_count || 1}/${game.max_players || 4} seats${game.bots ? ` · ${game.bots} bot${game.bots > 1 ? "s" : ""}` : ""}`;
}

function historyTitle(game) {
  const word = game.outcome === "won" ? "Won" : game.outcome === "tied" ? "Shared win" : "Lost";
  const scores = (game.standings || []).map((s) => s.score).filter((n) => n != null);
  return `${word}${scores.length ? ` · ${scores.join("–")}` : ""}`;
}

function Lobby({ myId, authUser, openGames, myGames, history, refreshing, onRefresh,
  onCreate, onJoin, onLeave, onCancel, onExit, onRules }) {
  const active = notWaiting(myGames);
  const [tab, setTab] = useState("open");
  const [shownHistory, sentinel] = useProgressiveList(history);
  return <div className="app pipmarket" style={ACCENT}><style>{styles}</style>
    <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="pipmarket"><LobbyCreateRow onCreate={onCreate} onJoin={onJoin}
        onRefresh={onRefresh} refreshing={refreshing} onRules={onRules} /></LobbyHero>
      <LobbyTabs value={tab} onChange={setTab} tabs={[
        { key: "open", label: "Open", count: openGames.length || null },
        { key: "active", label: "Active", count: active.length || null },
        { key: "history", label: "History", count: history.length || null },
      ]} />
      <div className={`lby-cols tab-${tab}`}>
        <section className="lby-col-open"><LobbyOpenHd count={openGames.length} />
          {!openGames.length && <LobbyNoOpen />}
          <div className="lby-list">{openGames.map((game) => <div className="lby-card" key={game.id}>
            <div className="lby-card-info"><LobbyOpenTitle game={game} myId={myId} defaultMaxPlayers={4} />
              <div className="lby-card-meta">{game.id} · {seatsLabel(game)} · {timeAgo(game.updated_at)}</div></div>
            <div className="lby-card-actions"><LobbyOpenActions state={seatStateOf(game, myId)}
              onReturn={() => onJoin(game.id)} onJoin={() => onJoin(game.id)}
              onLeave={() => onLeave(game.id)} onCancel={() => onCancel(game.id)} /></div>
          </div>)}</div>
        </section>
        <section className="lby-col-active"><LobbyActiveHd count={active.length} />
          {!active.length && <LobbyNoActive />}
          <div className="lby-list">{active.map((game) => <div className="lby-card" key={game.id}>
            <div className="lby-card-info"><LobbyMatchup seats={game.seats || []} />
              <div className="lby-card-meta">{game.round ? `Round ${game.round} of 3` : "Dealing"} · {timeAgo(game.updated_at)}<LobbyBotTier tier={game.ai_difficulty} labels={PM_AI_LABELS} /></div></div>
            <div className="lby-card-actions">{game.your_turn && <TurnBadge mine>Your turn</TurnBadge>}<LobbyAction onClick={() => onJoin(game.id)}>Resume</LobbyAction></div>
          </div>)}</div>
        </section>
        <section className="lby-col-history"><LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser && !authUser.guest ? "Your finished games will appear here." : "Log in to keep your game history."}</LobbyEmpty>}
          <div className="lby-list">{shownHistory.map((game) => <div className="lby-card lby-card-hist" key={game.id}>
            <div className="lby-card-info"><div className="lby-card-title">{historyTitle(game)}</div>
              <div className="lby-card-meta">{(game.standings || []).map((s) => s.name).join(", ")}<LobbyBotTier tier={game.ai_difficulty} labels={PM_AI_LABELS} /></div></div>
            <div className="lby-card-actions"><LobbyAction kind="secondary" onClick={() => onJoin(game.id)}>Review</LobbyAction></div>
          </div>)}{sentinel}</div>
        </section>
      </div>
    </div></div>
  </div>;
}

export default function PipMarket({ myId, authUser, onExit }) {
  const initialRoom = deepRoom();
  const [screen, setScreen] = useState(initialRoom ? "game" : "lobby");
  const [roomId, setRoomId] = useState(initialRoom || "");
  const [roomData, setRoomData] = useState(null);
  const [connected, setConnected] = useState(false);
  const [toast, setToast] = useState("");
  const [errorNonce, setErrorNonce] = useState(0);
  const [showCreate, setShowCreate] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [createSeats, setCreateSeats] = useState(2);
  const [createBots, setCreateBots] = useState(1);
  const [createDifficulty, setCreateDifficulty, rememberDifficulty] =
    useLastDifficulty("pipmarket", myId, PM_AI_TIERS, "normal");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("pipmarket", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("pipmarket", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("pipmarket", myId, "history", []));
  const [refreshing, setRefreshing] = useState(false);
  const wsRef = useRef(null);
  const roomRef = useRef(roomId);
  const tokenRef = useRef("");
  const intentRef = useRef(initialRoom ? "reconnect" : "join");
  const createRef = useRef(null);
  const urlAttempt = useRef(Boolean(initialRoom));
  roomRef.current = roomId;
  useListFade();

  useEffect(() => { if (!toast) return undefined; const t = setTimeout(() => setToast(""), 4200); return () => clearTimeout(t); }, [toast]);

  const fetchGames = useCallback(async () => {
    setRefreshing(true);
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    try {
      const [open, mine, old] = await Promise.all([
        fetch(`${HTTP_BASE}/pipmarket/games`).then((r) => r.json()),
        fetch(`${HTTP_BASE}/pipmarket/games/mine?player_id=${encodeURIComponent(myId)}`, { headers }).then((r) => r.ok ? r.json() : { games: [] }),
        fetch(`${HTTP_BASE}/pipmarket/games/history`, { headers }).then((r) => r.ok ? r.json() : { games: [] }),
      ]);
      const nextOpen = open.games || [], nextMine = mine.games || [], nextHistory = old.games || [];
      setOpenGames(nextOpen); setMyGames(nextMine); setHistory(nextHistory);
      writeLobbyCache("pipmarket", myId, "open", nextOpen);
      writeLobbyCache("pipmarket", myId, "mine", nextMine);
      writeLobbyCache("pipmarket", myId, "history", nextHistory);
    } catch { setToast("Could not refresh Pip Market tables."); }
    finally { setRefreshing(false); }
  }, [authUser, myId]);
  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);

  const handleMessage = useCallback((message) => {
    if (message.type === "error") { setToast(message.message || "Pip Market refused that."); setErrorNonce((n) => n + 1); return; }
    if (message.room) {
      setRoomData(message.room); setScreen("game");
      intentRef.current = "reconnect"; urlAttempt.current = false;
      const rid = message.room.room_id || roomRef.current;
      const token = message.room.reconnect_tokens?.[myId];
      if (token && rid) { tokenRef.current = token; try { localStorage.setItem(`${TOKEN_PREFIX}${rid}`, token); } catch {} }
      if (rid) { try { pushPath(buildPath("pipmarket", rid)); } catch {} }
    }
  }, [myId]);

  const connect = useCallback(() => {
    const rid = roomRef.current;
    if (!rid) return;
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(`${WS_BASE}/pipmarket/ws/${encodeURIComponent(rid)}/${encodeURIComponent(myId)}`);
    wsRef.current = ws;
    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      setConnected(true);
      const stored = tokenRef.current || (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })();
      const first = intentRef.current === "create"
        ? { action: "create", name: authUser?.name || "Player", ...(createRef.current || {}) }
        : stored ? { action: "reconnect", token: stored }
          : { action: "join", name: authUser?.name || "Player", session_token: authUser?.session_token || null };
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
  // The deep link is consumed once; later transitions call openRoom.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const leaveToLobby = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; roomRef.current = ""; setRoomId(""); setRoomData(null); setConnected(false); setScreen("lobby");
    try { pushPath(buildPath("pipmarket")); } catch {}
  }, []);
  useEffect(() => subscribe((route) => {
    if (route.game !== "pipmarket") return;
    if (!route.room) { if (screen !== "lobby") leaveToLobby(); return; }
    if (route.room !== roomRef.current) openRoom(route.room, "join");
  }), [leaveToLobby, openRoom, screen]);

  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("pipmarket", myId, "mine", rid, setMyGames);
    fetchGames();
  });

  const send = useCallback((payload) => { try { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(payload)); } catch {} }, []);
  const createGame = useCallback(() => {
    setShowCreate(false);
    const bots = Math.min(createBots, createSeats - 1);
    if (bots > 0) rememberDifficulty(createDifficulty);
    openRoom(roomCode(), "create", { max_players: createSeats, num_bots: bots, ai_difficulty: createDifficulty });
  }, [createBots, createDifficulty, createSeats, openRoom, rememberDifficulty]);
  const cancelGame = useCallback(async (id) => {
    try {
      const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
      const roomToken = readRoomToken(`${TOKEN_PREFIX}${id}`); if (roomToken) headers["X-Room-Token"] = roomToken;
      const response = await fetch(`${HTTP_BASE}/pipmarket/games/${id}?player_id=${encodeURIComponent(myId)}`, { method: "DELETE", headers });
      const data = await response.json(); if (!data.ok) throw new Error(data.message || "Could not cancel"); fetchGames();
    } catch (error) { setToast(error.message || "Could not cancel"); }
  }, [authUser, fetchGames, myId]);
  const leaveSeat = useCallback(async (id) => {
    try {
      await leaveOpenSeat({ endpoint: `${HTTP_BASE}/pipmarket/games`, roomId: id, playerId: myId,
        tokenKey: `${TOKEN_PREFIX}${id}`, sessionToken: authUser?.session_token });
      fetchGames();
    } catch (error) { setToast(error.message || "Could not leave that table"); }
  }, [authUser, fetchGames, myId]);

  const bots = Math.min(createBots, createSeats - 1);
  const friends = createSeats - 1 - bots;
  const summary = [bots ? `${bots} bot${bots > 1 ? "s" : ""}` : null, friends ? `${friends} friend${friends > 1 ? "s" : ""}` : null].filter(Boolean).join(" + ");

  const rulesModal = showRules && <div className="pipmarket pm-overlay" style={ACCENT}><RulesModal title="How to play — Pip Market" onClose={() => setShowRules(false)}><PipMarketRules /></RulesModal></div>;
  const toastNode = toast && <div className="pipmarket pm-toast" role="status">{toast}</div>;

  if (screen === "lobby") return <><Lobby {...{ myId, authUser, openGames, myGames, history, refreshing,
    onRefresh: fetchGames, onCreate: () => setShowCreate(true), onJoin: (id) => openRoom(id, "join"),
    onLeave: leaveSeat, onCancel: cancelGame, onExit, onRules: () => setShowRules(true) }} />
    {showCreate && <div className="pipmarket pm-overlay" style={ACCENT}><CreateModal title="New Pip Market game" onClose={() => setShowCreate(false)}>
      <CmRow label="Players"><CmSeg value={createSeats} onChange={(v) => { setCreateSeats(v); setCreateBots((b) => Math.min(b, v - 1)); }}
        options={[2, 3, 4].map((v) => ({ value: v, label: `${v} players` }))} /></CmRow>
      <CmRow label="Bots"><CmSeg value={bots} onChange={setCreateBots}
        options={Array.from({ length: createSeats }, (_, i) => ({ value: i, label: i ? `${i} bot${i > 1 ? "s" : ""}` : "No bots" }))} /></CmRow>
      {bots > 0 && <CmRow label="AI difficulty"><CmSeg value={createDifficulty} onChange={setCreateDifficulty} options={PIPMARKET_AI_TIER_OPTIONS} /></CmRow>}
      <div className="cm-footer"><span className="cm-summary">{createSeats} players · <b>You + {summary}</b></span>
        <button type="button" className="cm-create" onClick={createGame}>Create Game</button></div>
    </CreateModal></div>}
    {rulesModal}{toastNode}</>;

  if (!roomData) return <div className="app pipmarket pm-connecting" style={ACCENT}><style>{styles}</style>
    <LobbyHeader title="Pip Market" onBack={leaveToLobby} />
    <div className="pm-connecting-in"><div className="pm-connecting-dice"><Die face={3} /><Die face={5} /></div>
      <h1>{toast ? "That table stayed closed." : "Setting up the stalls…"}</h1>
      <p role="status">{toast || "Connecting to the market."}</p>
      <button type="button" className="pm-btn primary" onClick={leaveToLobby}>Return to lobby</button></div>
    {rulesModal}</div>;

  if (!roomData.game) {
    const seated = Object.keys(roomData.players || {}).length;
    const botCount = (roomData.ai_players || []).length;
    return <div className="app pipmarket" style={ACCENT}><style>{styles}</style>
      <WaitingRoom game="pipmarket" roomId={roomData.room_id} players={roomData.players}
        hostId={roomData.host} myId={myId} min={2} max={roomData.max_players || 4}
        note={`${seated} of ${roomData.max_players || 4} seats taken${botCount ? ` · ${botCount} bot${botCount > 1 ? "s" : ""} seated` : ""}. Empty seats are left out when the host starts.`}
        user={authUser} onLeave={leaveToLobby} onRules={() => setShowRules(true)}
        onStart={() => send({ action: "start" })} canStart={connected} blockedLabel="Reconnecting…" />
      {rulesModal}{toastNode}</div>;
  }

  return <><GameView room={roomData} myId={myId} connected={connected} errorNonce={errorNonce}
    onMove={(move) => send({ action: "move", move })} onExit={leaveToLobby}
    onRules={() => setShowRules(true)} onAbandon={() => send({ action: "abandon" })} />
    {rulesModal}{toastNode}</>;
}
