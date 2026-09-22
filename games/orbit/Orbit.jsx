import { fetchGameHistory } from "../../shared/lobbyHistory.js";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyMatchup, LobbyLoading, LobbyEmpty,
  LobbyAction, LobbyTabs, notWaiting, GameMenu, gameMenuCss,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, useProgressiveList, LobbyHero, LobbyUser, useListFade,
  readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame, timeAgo, useLastDifficulty,
  LobbyBotTier, LobbyOpenTitle, LobbyOpenActions, seatStateOf, WaitingRoom, waitingRoomCss,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { leaveOpenSeat, readRoomToken } from "../../shared/roomLifecycle.js";
import { useCardInfoGesture } from "../../shared/gestures.js";
import OrbitRules from "./rules.jsx";
import { Resource, ResourceIcon, decisionCopy, victoryCondition, InfluenceDisc, OrbitSky } from "./presentation.jsx";
import { automaticChoices, adjacentPairs, adjacentOrderMatters } from "./decisions.js";
import { useCardMotion } from "./cardMotion.js";
import orbitCssText from "./Orbit.css?inline";


const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const ORBIT_WS = `${WS_BASE}/orbit/ws`;
const ORBIT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/orbit");
// The tiers the create modal offers, and — mapped to ids — the list a
// remembered tier is validated against. ONE list, because a hand-written copy
// drifts: when Expert landed the id list still read easy/normal/hard, so
// picking Expert was stored and then rejected on the next open, and the modal
// silently came back on Hard.
const ORBIT_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "Public-information ranker" },
  { value: "normal", label: "Normal", title: "Effect-aware ranker with a validated server fallback" },
  { value: "hard", label: "Hard", title: "Searches its main action in your browser, resampling the hidden hand every simulation" },
  { value: "expert", label: "Expert", title: "Searches its main action against one coherent hidden world; the strongest tier" },
];
const ORBIT_AI_TIERS = ORBIT_AI_TIER_OPTIONS.map((t) => t.value);
// id -> the words a player sees, off the SAME list the picker renders. The
// create summary used to carry its own hand-written copy of these four labels,
// which is the shape that let the tier list and the label list disagree once
// already (see the comment above `ORBIT_AI_TIER_OPTIONS`).
const ORBIT_AI_LABELS = Object.fromEntries(ORBIT_AI_TIER_OPTIONS.map((t) => [t.value, t.label]));
const ORBIT_AI_WIRE = 1;
const ORBIT_AI_MODEL_VERSION = 2;
const ORBIT_AI_ENCODER = "orbit-observation-v1";
const ORBIT_AI_SCHEMA = 1;
const ORBIT_AI_TURN_BUDGET_MS = 5000;
const ORBIT_AI_WORKER_CAP = 4;
// The tiers served by the browser worker. Mirrors CLIENT_AI_TIERS in main.py:
// both speak the same boundary, and Expert additionally asks it to search.
const CLIENT_AI_TIERS = ["hard", "expert"];
const styles = baseCss + lobbyCss + gameMenuCss + createModalCss
  + lobbyCreateRowCss + rulesModalCss + waitingRoomCss + orbitCssText;

const PLANETS = ["mercury", "venus", "terra", "mars", "jupiter"];
const FACTIONS = ["robot", "human", "animod"];
const LEADER_EFFECT = {
  robot: "gain 1 Zenithium",
  human: "gain 3 Credits",
  animod: "mobilize 2",
};
/* PLANETS CARRY NO SYMBOL. The five planets used to each print a glyph (☿ ♀ ⊕
   ♂ ♃) beside their name on the card, the column head, the influence row and
   every capture chip — four places to learn an alphabet that the colour already
   said, on a card whose OUTLINE is that same colour. The name plus the colour is
   the identity now, and `PlanetName` is the one place that renders it, so a
   planet reads the same everywhere. Factions keep their glyph: a faction has no
   colour of its own, and three shapes is a small alphabet. */
const FACTION_GLYPH = { robot: "◇", human: "△", animod: "⬡" };
const BOARD_LETTER = {
  robot: { 1: "S", 2: "D" },
  human: { 1: "U", 2: "O" },
  animod: { 1: "N", 2: "P" },
};
/* The badge's two sides, named as the rulebook and the imported BGA card text
   name them ("place it on the Silver side … flip it to the Gold side"). */
const LEADER_SIDES = { 1: "Silver", 2: "Gold" };


function useSocket(onMessage) {
  const wsRef = useRef(null);
  const onMsg = useRef(onMessage);
  const [connected, setConnected] = useState(false);
  onMsg.current = onMessage;
  const connect = useCallback((url, firstMessage) => {
    try { wsRef.current?.close(); } catch {}
    setConnected(false);
    const ws = new WebSocket(url);
    wsRef.current = ws;
    ws.onopen = () => {
      if (firstMessage) ws.send(JSON.stringify(firstMessage));
    };
    ws.onclose = () => { if (wsRef.current === ws) setConnected(false); };
    ws.onmessage = (event) => {
      if (wsRef.current !== ws) return;
      try {
        onMsg.current(JSON.parse(event.data));
        // Establish the first restored frame and the connection together, so
        // motion starts from this snapshot rather than replaying the outage.
        setConnected(true);
      } catch {}
    };
  }, []);
  const send = useCallback((message) => {
    try { wsRef.current?.send(JSON.stringify(message)); } catch {}
  }, []);
  const socketReady = useCallback(() => wsRef.current?.readyState ?? 3, []);
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null;
    setConnected(false);
  }, []);
  return { connected, connect, send, socketReady, disconnect };
}


/* ONE renderer for a planet's identity, everywhere it appears. The colour is
   the `or-<planet>` class (which also drives the card outline, the track and
   the disc), the word is the label. */
function PlanetName({ planet, className = "" }) {
  return <b className={`or-pl or-${planet}${className ? ` ${className}` : ""}`}>{planet}</b>;
}

// Read-only faces offer the same detail view with either mouse button.
function detailClick(open) {
  return {
    onClick: open,
    onContextMenu: (event) => { event.preventDefault(); event.stopPropagation(); open(event); },
  };
}

/* THE LOG IS THE GAME'S ONLY NARRATION, so an entry is not a sentence but a
   list of PARTS the engine wrote: a plain string is literal text and a dict is
   a token — `{c}` an Agent, `{p}` a planet, `{b}` a bonus token, `{f,l}` a
   technology space. Every token opens the SAME detail modal the table does, so
   "which card was that?" is never a question the log leaves open. Each token
   also carries its own label in `v`, so the line still reads before the catalog
   fetch lands. Entries persisted before this shape (and the harness fixture)
   carry a flat `message` instead and render as plain text. */
function LogPart({ part, game, catalog, onInfo }) {
  if (typeof part === "string") return part;
  if (part.p) return <PlanetName planet={part.p} />;
  const open = (info) => (event) => { event.stopPropagation(); onInfo?.(info); };
  if (part.c != null) {
    const card = catalog?.cards?.[String(part.c)];
    if (!card || !onInfo) return <b className="or-log-name">{part.v}</b>;
    return <button type="button" className="or-log-ref or-log-card"
      title={`${card.name} — ${card.description}`}
      {...detailClick(open({ kind: "card", card }))}>{card.name}</button>;
  }
  if (part.b != null) {
    const bonus = catalog?.bonuses?.[String(part.b)] || catalog?.bonuses?.[part.b];
    const text = bonus?.description || part.v;
    if (!onInfo) return <b className="or-log-name">{text}</b>;
    return <button type="button" className="or-log-ref or-log-bonus" title={text}
      {...detailClick(open({ kind: "bonus", token: part.b }))}>{text}</button>;
  }
  if (part.f) {
    const space = (game?.board?.[part.f] || []).find((row) => row.level === part.l);
    if (!space || !onInfo) return <b className="or-log-name">{part.v}</b>;
    return <button type="button" className={`or-log-ref or-log-tech or-${part.f}`}
      title={`${part.v}: ${space.description}`}
      {...detailClick(open({ kind: "tech", faction: part.f, level: part.l, description: space.description }))}>
      {part.v}</button>;
  }
  return part.v || "";
}

function logText(entry) {
  if (!entry.parts) return entry.message || "";
  return entry.parts.map((part) => typeof part === "string" ? part : (part.v || "")).join("");
}

function MoveLog({ entries = [], game, catalog, myId, onInfo }) {
  const viewport = useRef(null);
  useEffect(() => {
    const node = viewport.current;
    const follow = () => { node.scrollTop = node.scrollHeight; };
    follow();
    const observer = new ResizeObserver(follow);
    observer.observe(node);
    return () => observer.disconnect();
  }, [entries]);
  return <section className="or-log"><h2>Log</h2><div ref={viewport}>
    {entries.map((entry, i) => {
      const seat = !entry.pid ? "" : entry.pid === myId ? " mine" : " theirs";
      return <p key={`${entry.turn}-${i}`}
        className={`or-log-line${seat}${entry.turn_start ? " turn-start" : ""}`}
        title={logText(entry)}>
        <b>{entry.turn}</b>
        <span>{entry.parts
          ? entry.parts.map((part, index) => <LogPart key={index} part={part}
            game={game} catalog={catalog} onInfo={onInfo} />)
          : entry.message}</span>
      </p>;
    })}
  </div></section>;
}

function Hand({ children }) {
  return <div className="or-hand" aria-label="Your hand">{children}</div>;
}


/* The captured-disc tally. A disc that ARRIVES while you watch lands with a
   pulse, timed to the board's own capture (the disc reaches the goal, bursts,
   and then turns up here). "Arrives" means added after mount: the caller keys
   this on the connection, like `Resource`, so a reconnect's snapshot mounts
   quietly instead of pulsing every disc it already had. */
function Captures({ captured = [] }) {
  const seen = useRef({ count: captured.length, from: captured.length });
  if (captured.length !== seen.current.count) {
    seen.current = { count: captured.length, from: Math.min(seen.current.count, captured.length) };
  }
  if (!captured.length) return null;
  return <span className="or-captures" aria-label="Captured planets">
    {captured.map((planet, index) => (
      <i className={`or-capture-disc or-${planet}${index >= seen.current.from ? " arrived" : ""}`} key={`${planet}-${index}`}
        title={`Captured ${planet}`} aria-label={`Captured ${planet}`} />
    ))}
  </span>;
}


/* The badge is SHOWN FOR BOTH SEATS, including the seat that does not hold it.
   It used to render only under its owner, so "no badge" and "the panel just
   doesn't mention it" looked identical — and the badge is what sets a hand
   limit of 4 / 5 / 6, which is the number printed over the hand.
   ONE function decides that limit and every counter on the page reads it. The
   badge is the only thing that moves it, and it moves MID-TURN, so a limit
   printed from a second hand-rolled expression is a counter that disagrees
   with the badge sitting right beside it. */
function handLimit(leader, pid) {
  if (!pid || leader?.owner !== pid) return 4;
  return leader.level >= 2 ? 6 : 5;
}

function LeaderBadge({ leader, pid }) {
  const level = leader?.owner === pid ? (leader.level || 0) : 0;
  const side = LEADER_SIDES[level];
  return <b data-motion-key={`leader-${pid}`} data-motion-value={level} className={`or-leader lv-${level}`}
    title={side ? `${side} Leader badge — hand limit ${handLimit(leader, pid)}`
      : `No Leader badge — hand limit ${handLimit(leader, pid)}`}>
    <i className="or-leader-medal" aria-hidden="true" />
    {side ? `${side} Leader` : "No badge"}
  </b>;
}


/* Always show the held count and the hand limit together. Both player boxes use
   the same compact `N / N cards` treatment so the two hands are immediately
   comparable, including while a player is temporarily below or above the limit. */
function HandCount({ held, limit }) {
  const over = held > limit;
  return <span className={`or-hand-count${over ? " over" : ""}`}
    title={over ? `${held} Agents held, over the limit of ${limit}. An effect put them there and a hand is never discarded down.`
      : `${held} of a ${limit}-card hand limit, refilled at the end of that player’s turn.`}>
    <b>{held}</b> / {limit} cards
  </span>;
}

/* THE HAND IS SORTED, NOT DEALT-ORDER — by planet, then by printed cost.
   Server order is draw order, so a card's place in the row meant nothing and
   moved every turn: the end-of-turn draw appends, and an effect that hands you
   an Agent mid-turn inserts wherever the engine put it. Every question a player
   asks of their own hand is grouped by one of these two keys — "can I still
   push Mars?" is the planet, "what can I afford after paying 4 Credits?" is the
   cost — and the planet comes first because it is also the order of the five
   influence tracks beside the hand, so the hand reads down the board.
   `id` is the final tie-break so two same-planet, same-cost Agents hold a
   stable order across re-renders rather than depending on the sort's stability
   for input the engine may have reordered.
   It is presentation ONLY: every move still carries `card_id`, so nothing about
   which card a click plays depends on where it sits. */
const PLANET_ORDER = Object.fromEntries(PLANETS.map((planet, i) => [planet, i]));
function sortedHand(hand) {
  return [...(hand || [])].sort((a, b) =>
    (PLANET_ORDER[a?.planet] ?? PLANETS.length) - (PLANET_ORDER[b?.planet] ?? PLANETS.length)
    || (a?.cost ?? 0) - (b?.cost ?? 0)
    || (a?.id ?? 0) - (b?.id ?? 0));
}


function orbitMoveKey(move) {
  if (!move || typeof move !== "object") return "";
  const stable = (value) => Array.isArray(value)
    ? `[${value.map(stable).join(",")}]`
    : value && typeof value === "object"
      ? `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`
      : JSON.stringify(value);
  try { return stable(move); } catch { return ""; }
}


function PlayerRail({ player, name, active, me, leader, hint, orderLabel, onInfo, connected }) {
  if (!player) return null;
  const owner = me ? "Your" : `${name || "Opponent"}’s`;
  return <section data-motion-key={`seat-${player.__pid}`} data-motion-value={String(active)} className={`or-player${active ? " active" : ""}${me ? " mine" : " theirs"}`}>
    <div className="or-player-name">
      <i className="or-seat-dot" aria-hidden="true" />
      <span>{name || "Player"}</span>
      {me && <em>you</em>}
      {hint && <span className="or-player-hint">{hint}</span>}
      <LeaderBadge leader={leader} pid={player.__pid} />
    </div>
    {orderLabel && <div className="or-player-order">{orderLabel}</div>}
    <div className="or-resources">
      <Resource key={`credits-${connected}`} kind="credits" value={player.credits} animate={connected} />
      <Resource key={`zenithium-${connected}`} kind="zenithium" value={player.zenithium} animate={connected} />
      <span className="or-resource-cards">
        <HandCount held={player.hand?.length || 0} limit={handLimit(leader, player.__pid)} />
        <Captures key={`captures-${connected}`} captured={player.captured} />
      </span>
    </div>
    {/* THE PLAYED AGENTS ARE THE PLANET BOARD'S OWN BOTTOM (or top) ROW — five
        cells on the SAME five-column grid as `.or-influence`, sharing its inline
        padding and its gutter through `--or-board-pad` / `--or-board-gap`, so a
        planet's stack sits directly under (yours) or over (theirs) that planet's
        track. That adjacency IS the label, which is why the row no longer
        carries a heading of its own: the word naming each cell is printed one
        row away, in the planet's own colour.
        It is also the ONLY treatment at every width now — the separate
        `.or-columns` panels are gone — so the cell has to carry the two facts
        that used to live on the panel face: the top Agent's NAME and its cost.
        The name is the half that drops first (it wants ~150px and a phone
        column is ~70px); the count is the half that never does, because it is
        the recruit discount and not decoration.
        THE CELL IS DRAWN AS THE TOP CARD OF A PILE. The price is that card's
        own price, and a gold number on a column read as "this column costs N" —
        so it sits where every hand card carries it (a struck coin in the top-
        left corner, beside the name) and the Agents underneath show as one or
        two card edges above the cell (`depth-1`/`depth-2`, capped at two). The
        count, which is about the pile and not the card, trails on the right. */}
    <div className="or-played-agents" aria-label={`${owner} played Agents`}>
      {PLANETS.map((planet) => {
        const cards = player.columns?.[planet] || [];
        const top = cards[cards.length - 1];
        const depth = Math.min(cards.length - 1, 2);
        return <button type="button" key={planet} className={`or-played-agent or-${planet}${cards.length ? "" : " empty"}${depth > 0 ? ` depth-${depth}` : ""}`}
          data-motion-key={`column-${player.__pid}-${planet}`} data-motion-value={cards.map((card) => card.id).join(",")}
          disabled={!cards.length} title={`${cards.length} ${planet} Agent${cards.length === 1 ? "" : "s"}${top ? `. ${top.name} on top, printed cost ${top.cost} Credits` : ""}. ${cards.length ? "Open details" : "None played"}`}
          aria-label={`${cards.length} ${planet} Agent${cards.length === 1 ? "" : "s"}${top ? `, ${top.name} on top with a printed cost of ${top.cost} Credits` : ""}${cards.length ? ". Open details" : ""}`}
          {...detailClick(() => cards.length && onInfo?.({ kind: "column", planet, cards, owner }))}>
          {top && <span className="or-played-cost" aria-hidden="true">{top.cost}</span>}
          <span className="or-played-name">{top ? top.name : "empty"}</span>
          {!!cards.length && <span className="or-played-quantity" aria-hidden="true"><span>×</span><b className="or-played-count">{cards.length}</b></span>}
        </button>;
      })}
    </div>
  </section>;
}


/* A bonus is a physical TOKEN, never a text pill. Its effect belongs in the
   modal; letting variable-length rules text size the piece made the five
   planet rows ragged on desktop and made the piece collide with the track on
   phones. `compact` remains in the API for callers, but every token now has the
   same circular silhouette. */
function Bonus({ token, catalog, onInfo, compact = false, className = "" }) {
  if (token == null) {
    return <span className={`or-bonus spent${className ? ` ${className}` : ""}`}
      title="This bonus has already been claimed" aria-label="Bonus claimed">
      <i aria-hidden="true">✓</i>
    </span>;
  }
  const bonus = catalog?.bonuses?.[String(token)] || catalog?.bonuses?.[token];
  const text = bonus?.description || `Bonus token ${token}`;
  return <button type="button"
    className={`or-bonus${compact ? " compact" : ""}${className ? ` ${className}` : ""}`}
    aria-label={`${text}. Open bonus details`} title={text}
    {...(onInfo ? detailClick((event) => { event.stopPropagation(); onInfo({ kind: "bonus", token }); }) : {})}>
    <i aria-hidden="true">✦</i><span className="or-sr-only">{text}</span>
  </button>;
}


function InfluenceBoard({ game, myId, catalog, onInfo }) {
  const mineIsPositive = game.order?.[0] === myId;
  const spaces = [-4, -3, -2, -1, 0, 1, 2, 3, 4];
  return <section className="or-influence" aria-label="Planet influence board">
    {PLANETS.map((planet) => {
      const raw = game.influence?.[planet];
      const position = raw == null ? null : (mineIsPositive ? raw : -raw);
      return <div className={`or-track or-${planet}`} key={planet}>
        <div className="or-track-name"><PlanetName planet={planet} /></div>
        <div className="or-track-spaces">
          {spaces.map((space) => <span className={`or-space${Math.abs(space) === 4 ? ` goal ${space > 0 ? "mine" : "theirs"}` : ""}${space === 0 ? " middle" : ""}`} key={space} />)}
          <InfluenceDisc position={position} planet={planet} game={game} myId={myId} />
        </div>
        <Bonus token={game.planet_bonus?.[planet]} catalog={catalog} onInfo={onInfo} />
      </div>;
    })}
  </section>;
}


/* Five compact, equal rungs. The number has a permanent rail and the effect is
   one normally aligned block; nothing indents only its first line. Player
   tokens live on the numbered rung itself. Full rules text remains one press
   away, so the board can use readable type instead of fitting paragraphs. */
function TechBoard({ game, myId, otherId, myName, theirName, catalog, onInfo }) {
  const [collapsed, setCollapsed] = useState(true);
  const me = game.players?.[myId];
  const them = game.players?.[otherId];
  return <section className={`or-tech${collapsed ? " collapsed" : ""}`} aria-label="Technology board">
    <header>
      <h2>Technology</h2>
      <span className="or-tech-key">
        <b className="mine"><i aria-hidden="true" />{myName || "You"}</b>
        <b className="theirs"><i aria-hidden="true" />{theirName || "Opponent"}</b>
      </span>
      <button type="button" className="or-tech-toggle" aria-expanded={!collapsed}
        aria-controls="or-tech-body" onClick={() => setCollapsed((old) => !old)}>
        {collapsed ? "Show tracks" : "Hide tracks"}<i aria-hidden="true">⌄</i>
      </button>
    </header>
    <div className="or-tech-summary" aria-label="Current technology levels">
      {FACTIONS.map((faction) => <div className={`or-tech-summary-row or-${faction}`} key={faction}>
        <strong><i aria-hidden="true">{FACTION_GLYPH[faction]}</i>{faction}</strong>
        <span className="mine" title={`${myName || "You"} — level ${me?.technology?.[faction] || 0}`}>
          <i aria-hidden="true" /><b data-motion-key={`tech-${myId}-${faction}`} data-motion-value={me?.technology?.[faction] || 0}>{me?.technology?.[faction] || 0}</b>
        </span>
        <span className="theirs" title={`${theirName || "Opponent"} — level ${them?.technology?.[faction] || 0}`}>
          <i aria-hidden="true" /><b data-motion-key={`tech-${otherId}-${faction}`} data-motion-value={them?.technology?.[faction] || 0}>{them?.technology?.[faction] || 0}</b>
        </span>
      </div>)}
    </div>
    <div className="or-tech-body" id="or-tech-body">
      <div className="or-tech-grid">
      {FACTIONS.map((faction) => {
        const mineLevel = me?.technology?.[faction] || 0;
        const theirLevel = them?.technology?.[faction] || 0;
        const rows = [...(game.board?.[faction] || [])].reverse();
        const seats = (level) => <span className="or-tech-seats">
          {mineLevel === level && <i className="mine" title={`${myName || "You"} — level ${level}`} />}
          {theirLevel === level && <i className="theirs" title={`${theirName || "Opponent"} — level ${level}`} />}
        </span>;
        return <div className={`or-tech-col or-${faction}`} key={faction}>
          <h3><i>{FACTION_GLYPH[faction]}</i>{faction}<em title="Board strip in play">{BOARD_LETTER[faction][game.board_sides?.[faction]]}</em></h3>
          {/* YOUR LADDER LIGHTS, THEIRS DOES NOT. Every rung you have reached is
              lit and the conduit beside it runs up to your level; the next rung
              up is outlined as the one to develop. The opponent's position stays
              the dot it has always been — lighting both seats' progress on one
              ladder would say nothing about whose it is. */}
          {rows.map((space) => <div className={`or-tech-row${space.level === 2 ? " has-token" : ""}${space.level <= mineLevel ? " reached" : space.level === mineLevel + 1 ? " next" : ""}`} key={space.level}>
            <button type="button"
              data-motion-key={`tech-rung-${faction}-${space.level}`} data-motion-value={`${mineLevel === space.level}-${theirLevel === space.level}`}
              className={`or-tech-space${mineLevel === space.level ? " mine" : ""}${theirLevel === space.level ? " theirs" : ""}`}
              title={`Level ${space.level}: ${space.description}`}
              {...detailClick(() => onInfo({ kind: "tech", faction, level: space.level, description: space.description }))}>
              <span className="or-tech-rail">
                <b className="or-tech-lv">{space.level}</b>
                {seats(space.level)}
              </span>
              <span className="or-tech-text">{space.description}</span>
            </button>
            {space.level === 2 && <Bonus token={game.technology_bonus?.[faction]}
              catalog={catalog} onInfo={onInfo} compact className="or-tech-token" />}
          </div>)}
        </div>;
      })}
      </div>
      <p className="or-row-bonus">Complete all three tracks: level 1 → +1 influence · level 2 → +2 · level 3 → +3</p>
    </div>
  </section>;
}


/* A hand card is NEVER disabled any more: on the opponent's turn its click had
   nothing to do, and reading your own hand while you wait is the most ordinary
   thing a player does. `playable` — not the `disabled` attribute — is now what
   says the click will PLAY it, which is also the signal `screens.mjs` waits on
   for "this seat has legal moves". Click plays when it can and otherwise reads;
   press-and-hold / right-click always reads (see shared/gestures.js).

   TWO MARKED STATES, AND THEY MEAN OPPOSITE THINGS. `selected` is "this is the
   card I am about to play" — lifted, ringed in its planet colour, the brightest
   thing in the hand. `discarding` is the mulligan's "this one is going away",
   and it used the SAME treatment: picking three cards to throw away lit them up
   as the three you had chosen to keep, and the mulligan is the first screen of
   a player's first game. It now reads as removal — faded, desaturated, pushed
   DOWN rather than lifted, with the word on it — so the two are not merely
   different shades of emphasis but opposite directions. */
// A CARD NAME IS ONE LINE, ALWAYS — it shrinks to fit rather than wrapping.
// The name shares its row with the price and the faction glyph, so a long one
// ("Interplanetary Logistics Board") used to take a second line, and that line
// was charged to EVERY card: the hand reserves one height for all 90 faces, so
// the longest name set the height of the shortest card. Wrapping also moved the
// rules sentence down on exactly the cards whose sentence was already longest.
//
// Fit by WIDTH, which is what "one line" actually means — unlike a body-text
// fitter, whose criterion is height and which must therefore watch height too
// (see Dontminion's FitBodyText, where a width-only observer was the bug). Here
// width is both the criterion and the trigger, so a width-only ResizeObserver
// is right, and it cannot feed itself: shrinking the font never changes the box.
//
// The scale is measured, not stepped through: one pass of avail/natural lands
// within a pixel because glyph advance is linear in font-size, and a second
// pass corrects the rounding. A floor stops a pathological name becoming
// unreadable — it would rather clip than shrink past legibility.
const NAME_MIN_PX = 8;

function FitName({ text }) {
  const box = useRef(null);
  const span = useRef(null);
  useLayoutEffect(() => {
    const b = box.current, s = span.current;
    if (!b || !s) return;
    let lastW = -1;
    const fit = () => {
      b.style.fontSize = "";
      // Fit to the CONTENT box: clientWidth is the padding box, and measuring
      // against that lets the name grow into its own inset.
      const cs = getComputedStyle(b);
      const avail = b.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 1;
      if (avail <= 0) return;
      for (let pass = 0; pass < 2; pass++) {
        const natural = s.scrollWidth;
        if (natural <= avail) break;
        const base = parseFloat(getComputedStyle(b).fontSize) || 14;
        const next = Math.max(NAME_MIN_PX, base * (avail / natural));
        if (next >= base - 0.05) break;
        b.style.fontSize = next + "px";
      }
    };
    fit();
    let ro;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        const w = entries[0].contentRect.width;
        if (Math.abs(w - lastW) < 0.5) return;
        lastW = w;
        fit();
      });
      ro.observe(b);
    }
    // THE ONE INPUT THE WIDTH OBSERVER NEVER SEES: the title's web font landing.
    // Names are set in a self-hosted face, and a name fitted against the
    // fallback's glyphs keeps that size when the real (wider or narrower) glyphs
    // swap in — the box never changes width, so nothing above refits it.
    const fonts = typeof document !== "undefined" ? document.fonts : null;
    let live = true;
    const refit = () => { if (live) fit(); };
    fonts?.ready?.then(refit);
    fonts?.addEventListener?.("loadingdone", refit);
    return () => { live = false; if (ro) ro.disconnect(); fonts?.removeEventListener?.("loadingdone", refit); };
  }, [text]);
  return <strong ref={box}><span ref={span}>{text}</span></strong>;
}

function AgentCard({ card, selected, discarding = false, onClick, onInfo, hidden = false }) {
  const info = useCardInfoGesture(onInfo && card && !card.hidden
    ? () => onInfo({ kind: "card", card }) : null);
  if (hidden || card?.hidden) return <div className="or-agent hidden" aria-label="Hidden Agent"><span>ORBIT</span></div>;
  if (!card) return null;
  return <button type="button" data-card-id={card.id} aria-pressed={discarding ? true : undefined}
    className={`or-agent or-${card.planet} or-${card.faction}${selected ? " selected" : ""}${discarding ? " discarding" : ""}${onClick ? " playable" : ""}`}
    onClick={onClick || (onInfo ? () => onInfo({ kind: "card", card }) : undefined)}
    disabled={!onClick && !onInfo} title={discarding ? `${card.name} — marked for replacement` : card.description} {...info}>
    {discarding && <span className="or-discard-tag" aria-hidden="true">Replacing</span>}
    <span className="or-agent-top"><span className="or-card-price"><ResourceIcon kind="credits" /><b>{card.cost}</b></span><FitName text={card.name} /><i>{FACTION_GLYPH[card.faction]}</i></span>
    <span className="or-agent-text">{card.description}</span>
    <span className="or-agent-foot"><PlanetName planet={card.planet} /> · {card.faction}</span>
  </button>;
}


/* THE PRINTED SENTENCE IS THE AUTHORITY; THIS IS THE FOOTNOTE UNDER IT.
   Every card, technology space and bonus token carries BGA's own prose, and
   several of its terms are load-bearing jargon a first-time player cannot
   guess — "transfer", "mobilize", "opposing card", and above all "middle
   space" and "dominated", whose meanings are POSITIONS ON THE BOARD rather
   than the readings the words suggest. `engine.py` reads `middle` as a track
   whose disc sits on the centre space and `dominated` as one on the opponent's
   side, so those two definitions are transcribed FROM the engine, not from
   what the phrase looks like it means.
   This is additive, and that is the whole difference from the icon vocabulary
   that was tried on the card FACE and reverted: that replaced the prose with a
   lossy regex summary, this leaves the prose untouched and explains its terms
   beneath it. Order is the reading order of a term's first appearance. */
const GLOSSARY = [
  { k: "influence", re: /influence/i, t: "Influence",
    d: "Move that planet’s disc one space toward your control zone. Reaching the fourth space captures the disc; any further movement in the same effect is lost." },
  { k: "capture", re: /captur|dominat/i, t: "Capture",
    d: "A disc that reaches your end of a track is yours to keep, and pays that planet’s face-up bonus if it is still there. Three discs from one planet, four different planets, or five discs in all wins the game at once." },
  { k: "dominated", re: /dominated|opponent'?s side/i, t: "Dominated planet",
    d: "A track whose disc currently sits on your OPPONENT’s side of the centre — the planets you are behind on, not the ones you lead." },
  { k: "middle", re: /middle space|its middle|middle track/i, t: "Middle space",
    d: "A track whose disc is on the centre space right now, level between both players. Not the three middle planets." },
  { k: "credits", re: /credits?/i, t: "Credits",
    d: "The spending money that pays to recruit Agents. Each Agent already in a column reduces that column’s next recruit cost by 1, never below 0." },
  { k: "zenithium", re: /zenithium/i, t: "Zenithium",
    d: "The rarer resource. It pays only for technology: advancing to level N costs N Zenithium, less any reduction the card grants." },
  { k: "recruit", re: /recruit/i, t: "Recruit",
    d: "Play an Agent from your hand into its own planet’s column, pay its reduced cost, gain 1 influence on that planet, then resolve its text." },
  { k: "mobilize", re: /mobiliz/i, t: "Mobilize",
    d: "Take the top Agent off the deck and put it straight into the column of its own colour. You pay nothing, its text does NOT resolve, and it brings no recruit influence with it unless the effect says otherwise." },
  { k: "exile", re: /exile/i, t: "Exile",
    d: "Discard the TOP Agent of a column — the one added most recently. Exiled Agents go to the Agent discard pile and stop reducing that column’s recruit cost." },
  { k: "transfer", re: /transfer/i, t: "Transfer",
    d: "Take the top Agent out of your opponent’s column and add it to your own column of the same planet. Its text does not resolve; you gain its body, not its effect." },
  { k: "opposing", re: /opposing|opponent'?s card/i, t: "Opposing card",
    d: "An Agent standing in your opponent’s column. Only the top one of a column can ever be taken or exiled." },
  { k: "leader", re: /leader/i, t: "Leader badge",
    d: "One badge, held by at most one player. Taking it when you do not have it gives the Silver side and a hand limit of 5; taking it again flips it to Gold and a limit of 6. Giving it up returns your limit to 4." },
  { k: "bonus", re: /bonus/i, t: "Bonus token",
    d: "Eight tokens start face up: one on each planet and one on each technology track’s level-2 space. Claiming one resolves its effect immediately and removes it for the rest of the game." },
  { k: "technology", re: /technolog|develop/i, t: "Develop technology",
    d: "Advance one faction track by one level, paying the NEW level in Zenithium. You then resolve that level and every level below it, from the top down." },
  { k: "reduction", re: /reduction/i, t: "Reduction",
    d: "A discount on the Zenithium cost of the advance only. The price never goes below 0, and the level you reach is unchanged." },
  { k: "corresponding", re: /corresponding|of the same color|different color/i, t: "Corresponding colour",
    d: "Every Agent belongs to exactly one planet, printed in its colour along the bottom of the card. “The corresponding planet” is that one." },
  { k: "adjacent", re: /adjacent/i, t: "Adjacent planets",
    d: "Neighbours in the fixed board order Mercury · Venus · Terra · Mars · Jupiter. Mercury and Jupiter are the two ends and are not adjacent to each other." },
  { k: "tiers", re: /\d+\/\d+\/\d+|respectively/i, t: "Tiered cost",
    d: "Pick ONE of the listed rungs and pay it for the reward at the same position. You may always decline and take nothing." },
  { k: "discard", re: /discard/i, t: "Discard from hand",
    d: "Put that Agent from your hand into the Agent discard pile. It is not played and its text never resolves." },
  { k: "hand", re: /\bhand\b/i, t: "Hand limit",
    d: "At the end of your turn you draw back up to 4 Agents, or 5 with the Silver Leader badge and 6 with the Gold. You never discard down if an effect pushed you above it." },
  { k: "firstlevel", re: /first level you have reached/i, t: "First levels reached",
    d: "Counts how many of the three technology tracks you have advanced to level 1 or higher — at most 3, whatever the levels above 1 are." },
  { k: "give", re: /you can give|if you give/i, t: "Optional cost",
    d: "You choose whether to pay. Declining costs nothing and simply skips the part of the effect that hangs off it." },
];

function glossaryFor(...texts) {
  const text = texts.filter(Boolean).join(" ");
  return GLOSSARY.filter((entry) => entry.re.test(text));
}

function Glossary({ terms }) {
  if (!terms.length) return null;
  return <div className="or-info-defs">
    <h3>Keywords</h3>
    <dl>{terms.map((entry) => <div key={entry.k}>
      <dt>{entry.t}</dt><dd>{entry.d}</dd>
    </div>)}</dl>
  </div>;
}


/* One modal, four shapes — a card, a bonus token, a technology space, or a
   whole column. Every readable thing on the table opens it, so no piece of
   rules text on this page is a dead end. */
function InfoModal({ info, catalog, onClose, onInfo }) {
  const backdropPress = useRef(false);
  useEffect(() => {
    backdropPress.current = false;
    if (!info) return undefined;
    const onKey = (event) => { if (event.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [info, onClose]);
  if (!info) return null;

  let tint = "";
  let eyebrow = "";
  let title = "";
  let body = null;
  if (info.kind === "card") {
    const card = info.card;
    tint = `or-${card.planet}`;
    eyebrow = "Agent";
    title = card.name;
    body = <>
      <p className="or-info-tags">
        <PlanetName planet={card.planet} />
        <span className="or-info-faction"><i>{FACTION_GLYPH[card.faction]}</i>{card.faction}</span>
        <span className="or-info-cost"><ResourceIcon kind="credits" /><b>{card.cost}</b> Credits</span>
      </p>
      <p className="or-info-text">{card.description}</p>
      <Glossary terms={glossaryFor(card.description)} />
    </>;
  } else if (info.kind === "bonus") {
    const bonus = catalog?.bonuses?.[String(info.token)] || catalog?.bonuses?.[info.token];
    eyebrow = "Bonus token";
    title = bonus?.description || `Bonus token ${info.token}`;
    body = <>
      <p className="or-info-note">A planet’s token is claimed by the first player to capture a
        disc from that planet. A technology token sits on level 2 and is claimed by the first player
        to reach it, resolving after that level’s own effect. A claimed token resolves at once and
        leaves the board for good.</p>
      <Glossary terms={glossaryFor(bonus?.description)} />
    </>;
  } else if (info.kind === "tech") {
    tint = `or-${info.faction}`;
    eyebrow = `${info.faction} technology`;
    title = `Level ${info.level}`;
    body = <>
      <p className="or-info-text">{info.description}</p>
      <p className="or-info-note">Reaching this space costs {info.level} Zenithium, less any
        reduction. You then resolve level {info.level} and every level below it, top to bottom, so
        a lower space pays out again on every later advance up this track.</p>
      <Glossary terms={glossaryFor(info.description)} />
    </>;
  } else if (info.kind === "column") {
    tint = `or-${info.planet}`;
    eyebrow = `${info.owner} column`;
    title = info.planet;
    body = <ul className="or-info-list">
      {[...info.cards].reverse().map((card, index) => <li key={card.id}>
        <button type="button" {...detailClick(() => onInfo({ kind: "card", card }))}>
          <span className="or-info-li-head"><b>{card.cost}</b><strong>{card.name}</strong>
            {index === 0 && <em>top</em>}</span>
          <span>{card.description}</span>
        </button>
      </li>)}
    </ul>;
    body = <>
      {body}
      <p className="or-info-note">{info.cards.length} Agent{info.cards.length === 1 ? "" : "s"} here.
        Only the top one can be exiled or transferred, and the stack takes {info.cards.length} off
        the printed price of the next <PlanetName planet={info.planet} /> recruit. Press any Agent
        to read it in full.</p>
    </>;
  }

  return <div className="or-info-back"
    onPointerDown={(event) => { backdropPress.current = event.target === event.currentTarget; }}
    onClick={(event) => {
      // A long press can open this backdrop before the opening finger lifts.
      // Only dismiss when a new gesture actually began on the backdrop.
      if (backdropPress.current && event.target === event.currentTarget) onClose();
      backdropPress.current = false;
    }}>
    <div className={`or-info ${tint}`} role="dialog" aria-modal="true" aria-label={title}
      onClick={(event) => event.stopPropagation()}>
      <button type="button" className="or-info-x" onClick={onClose} aria-label="Close">×</button>
      <span className="or-eyebrow">{eyebrow}</span>
      <h2>{title}</h2>
      {body}
    </div>
  </div>;
}


function choiceLabel(move, pending, game, catalog) {
  if ("planet" in move) return <PlanetName planet={move.planet} />;
  if ("planets" in move) {
    return <>{move.planets.map((planet, index) => <span key={planet}>
      {index ? " + " : ""}<PlanetName planet={planet} />
    </span>)}</>;
  }
  if ("accept" in move) return move.accept ? (pending.type === "optional_exile_each" ? "Exile Agent" : "Accept effect") : (pending.type === "optional_exile_each" ? "Keep Agent" : "Decline");
  if ("faction" in move) {
    const level = game.players?.[game.pending_pid]?.technology?.[move.faction] || 0;
    return `${FACTION_GLYPH[move.faction]} ${move.faction} · ${level} → ${level + 1} · ${Math.max(0, level + 1 - (pending.discount || 0))} Zenithium`;
  }
  if ("tier" in move) return move.tier ? `Exile ${move.tier} → gain ${pending.reward === "zenithium" ? move.tier : { 2: 1, 4: 2, 7: 3 }[move.tier]} ${pending.reward === "zenithium" ? "Zenithium" : `${pending.planet} influence`}` : "No Agents can be exiled";
  if ("cost" in move) return move.cost ? `Spend ${move.cost} ${pending.resource === "credits" ? "Credits" : "Zenithium"} → gain ${move.amount} influence` : "Skip";
  if ("card_id" in move) {
    const card = game.players && Object.values(game.players).flatMap((p) => p.hand || []).find((c) => c.id === move.card_id);
    return card?.name || catalog?.cards?.[String(move.card_id)]?.name || `Agent ${move.card_id}`;
  }
  if ("bonus_area" in move) {
    const board = move.bonus_area === "planet" ? game.planet_bonus : game.technology_bonus;
    const token = board?.[move.slot];
    const desc = catalog?.bonuses?.[String(token)]?.description;
    return `${move.slot}: ${desc || `bonus ${token}`}`;
  }
  if ("branch" in move) return pending?.branch_labels?.[move.branch] || `Option ${move.branch + 1}`;
  return "Choose";
}


function DecisionChoice({ move, task, game, catalog, sendMove, onInfo }) {
  const pid = game.pending_pid;
  const otherId = game.order.find((id) => id !== pid);
  const owner = task.type === "transfer" || (task.type === "exile" && task.owner !== "self") ? otherId : pid;
  const isAgentChoice = ["exile", "exile_for_matching", "transfer"].includes(task.type);
  const card = isAgentChoice ? game.players?.[owner]?.columns?.[move.planet]?.at(-1)
    : move.card_id != null ? game.players?.[pid]?.hand?.find((c) => c.id === move.card_id) : null;
  const info = useCardInfoGesture(card ? () => onInfo({ kind: "card", card }) : null);
  const adjacent = task.type === "adjacent_three" && move.planet;
  const index = PLANETS.indexOf(move.planet);
  return <button type="button" title={card?.description} onClick={() => sendMove(move)} {...info}>
    {choiceLabel(move, task, game, catalog)}
    {card && move.planet && <span className="or-choice-agent">{card.name}</span>}
    {adjacent && <span className="or-choice-agent">{PLANETS[index - 1]} + {PLANETS[index + 1]}</span>}
  </button>;
}

function DecisionPanel({ game, catalog, sendMove, onInfo }) {
  const [orderedPair, setOrderedPair] = useState(null);
  const pending = game.pending?.task;
  const moves = game.legal_moves || [];
  const frameKey = JSON.stringify([game.turn_number, game.pending, moves, game.log?.slice(-2)]);
  if (!pending || automaticChoices(game).length) return null;
  const pairMoves = orderedPair?.key === frameKey ? orderedPair.moves : null;
  const choices = pending.type === "two_adjacent" ? pairMoves || adjacentPairs(moves).map((pair) => pair[0]) : moves;
  const choose = (move) => {
    const pair = pending.type === "two_adjacent" && adjacentPairs(moves).find((pair) => pair.includes(move));
    if (!pairMoves && pair?.length > 1 && adjacentOrderMatters(game, move)) setOrderedPair({ key: frameKey, moves: pair });
    else sendMove(move);
  };
  const optionalPlanet = pending.planets?.[pending.index || 0];
  const optionalAgent = game.players?.[game.pending_pid]?.columns?.[optionalPlanet]?.at(-1);
  const { title, detail } = decisionCopy(pending, optionalAgent?.name);
  const planetChoices = moves.every((move) => "planet" in move) && moves.length <= 5;
  const action = [...(game.log || [])].reverse().find((entry) => entry.action)?.action;
  const context = action === "technology" ? "Technology" : action === "leader" ? "Leader action" : "Agent effect";
  return <section className="or-decision" aria-live="polite" aria-label="Current decision">
    <div className="or-decision-source"><span>{context}</span><b>{game.pending.source}</b></div>
    <h2>{pairMoves ? "Which planet gains influence first?" : title}</h2>
    {pairMoves && <p className="or-decision-detail">A capture can resolve its bonus before the second planet moves.</p>}
    {detail && <p className="or-decision-detail">{detail}</p>}
    {!moves.length && <p className="or-decision-detail">Waiting for the server to resolve this effect…</p>}
    <div className={`or-choice-grid${planetChoices ? " planet-choices" : ""}`} style={{ "--or-choice-count": Math.min(5, moves.length) }}>
      {choices.map((move, index) => pairMoves ? <button type="button" key={index} onClick={() => sendMove(move)}>
        <PlanetName planet={move.planets[0]} /> first, then <PlanetName planet={move.planets[1]} />
      </button> : <DecisionChoice key={index} {...{ move, task: pending, game, catalog, onInfo }} sendMove={choose} />)}
    </div>
    {pairMoves && <button type="button" onClick={() => setOrderedPair(null)}>Back to planet pairs</button>}
    {["exile", "exile_for_matching", "transfer", "discard_hand"].includes(pending.type) && <p className="or-decision-help">Hold an Agent to read its card.</p>}
  </section>;
}


function Lobby({ authUser, myId, onExit, openGames, myGames, history, historyShown,
  historyMore, refreshing, fetchGames, joinGame, resumeGame, cancelGame, leaveSeat,
  showCreate, setShowCreate, createOpp, setCreateOpp,
  createDifficulty, setCreateDifficulty, createGame, lobbyTab, setLobbyTab,
  showRules, setShowRules, toast }) {
  const active = notWaiting(myGames);
  const selectedOpponent = createOpp === "friend" ? "friend" : createDifficulty;
  return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}>
    <style>{styles}</style>
    <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="orbit">
        <LobbyCreateRow onCreate={() => setShowCreate(true)}
          onJoin={joinGame} onRefresh={fetchGames} refreshing={refreshing}
          onRules={() => setShowRules(true)} />
      </LobbyHero>
      <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
        { key: "open", label: "Open", count: openGames.length || null },
        { key: "active", label: "Active", count: active.length || null },
        { key: "history", label: "History", count: history.length || null },
      ]} />
      <div className={`or-lobby-cols lby-cols tab-${lobbyTab}`}>
        <div className="lby-col-open">
          <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
          {!openGames.length && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
          <div className="lby-list">{openGames.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><LobbyOpenTitle game={g} myId={myId} />
              <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div></div>
            <div className="lby-card-actions"><LobbyOpenActions state={seatStateOf(g, myId)}
              onReturn={() => resumeGame(g.id)} onJoin={() => joinGame(g.id)}
              onLeave={() => leaveSeat(g.id)} onCancel={() => cancelGame(g.id)} /></div>
          </div>)}</div>
        </div>
        <div className="lby-col-active">
          <LobbySectionHd title="Active Games" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          <div className="lby-list">{active.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><LobbyMatchup placeholder="Opponent" seats={[
              { name: g.player1_name, you: g.you_are_p1 }, { name: g.player2_name, you: !g.you_are_p1 },
            ]} />
              <div className="lby-card-meta">{g.turn ? `turn ${g.turn} · ` : ""}{timeAgo(g.updated_at)}<LobbyBotTier tier={g.ai_difficulty} labels={ORBIT_AI_LABELS} /></div></div>
            <div className="lby-card-actions"><TurnBadge mine={g.your_turn}>{g.your_turn ? "Your turn" : "Their turn"}</TurnBadge>
              <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction></div>
          </div>)}</div>
        </div>
        <div className="lby-col-history">
          <LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser ? "No finished games yet." : "Log in to keep your game history."}</LobbyEmpty>}
          <div className="lby-list">{historyShown.map((g) => <div className="lby-card lby-card-hist" key={g.id}>
            <div className="lby-card-info"><div className="lby-card-title"><span className={`hist-result ${g.outcome}`}>{g.outcome === "won" ? "Won" : g.outcome === "draw" ? "Draw" : "Lost"}</span>
              <span className="hist-scores"> vs {g.you_are_p1 ? g.player2_name : g.player1_name}</span></div>
              <div className="lby-card-meta">{g.turns ? `${g.turns} turns · ` : ""}{timeAgo(g.updated_at)}<LobbyBotTier tier={g.ai_difficulty} labels={ORBIT_AI_LABELS} /></div></div>
          </div>)}{historyMore}</div>
        </div>
      </div>
    </div></div>
    {showCreate && <CreateModal title="New Orbit game" onClose={() => setShowCreate(false)}>
      <CmRow label="Opponent"><CmSeg value={createOpp} onChange={setCreateOpp} options={[
        { value: "friend", label: "VS Friend" },
        { value: "ai", label: "VS AI" },
      ]} /></CmRow>
      {createOpp === "ai" && <CmRow label="AI difficulty"><CmSeg value={createDifficulty} onChange={setCreateDifficulty}
        options={ORBIT_AI_TIER_OPTIONS} wrap /></CmRow>}
      <div className="cm-footer"><span className="cm-summary">Creating: <b>{selectedOpponent === "friend" ? "vs Friend" : `vs ${ORBIT_AI_LABELS[selectedOpponent] || "Hard"} AI`}</b></span>
        <button type="button" className="cm-create" onClick={() => createGame(createOpp === "ai", createDifficulty)}>Create Game</button></div>
    </CreateModal>}
    {showRules && <RulesModal title="How to play — Orbit" onClose={() => setShowRules(false)}><OrbitRules /></RulesModal>}
    {toast && <div className="or-toast">{toast}</div>}
  </div>;
}


// The room id a deep link is asking for, read at MOUNT rather than in an effect.
// `useEffect` runs after paint, so seeding `connecting` from it left the very
// first frame as `screen:"lobby"` + `connecting:false` — the full lobby, painted
// for one frame on top of a game you were already in, which is what a player
// coming back through the sign-in screen sees as "a flash of another screen
// before it reconnects". The URL is known before React renders anything; reading
// it here makes the first paint the "Connecting…" panel it was always meant to be.
const deepLinkRoom = () => {
  try {
    const match = /\/orbit\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    return match ? match[1].toUpperCase() : null;
  } catch { return null; }
};

export default function Orbit({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");
  const [connecting, setConnecting] = useState(() => !!deepLinkRoom());
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [toast, setToast] = useState("");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("orbit", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("orbit", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("orbit", myId, "history", []));
  const [refreshing, setRefreshing] = useState(false);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [showCreate, setShowCreate] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");
  const [createDifficulty, setCreateDifficulty, rememberDifficulty] =
    useLastDifficulty("orbit", myId, ORBIT_AI_TIERS, "expert");
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [selectedCard, setSelectedCard] = useState(null);
  // ONE descriptor, one modal, one gesture. `info` is {kind:"card"|"bonus"|
  // "tech"|"column", ...} — see InfoModal. Every readable face on the table
  // sets it, so nothing on the page is a dead press.
  const [info, setInfo] = useState(null);
  const [mulligan, setMulligan] = useState([]);
  const urlAttempt = useRef(null);
  const wasmPoolRef = useRef(null);
  const wasmMetaRef = useRef(null);
  const clientAiArmedRef = useRef(null);
  const aiDispatchRef = useRef(null);
  const aiGenerationRef = useRef(0);
  const [wasmReady, setWasmReady] = useState(false);
  const [historyShown, historyMore] = useProgressiveList(history);
  useListFade();

  const handleMessage = useCallback((message) => {
    setConnecting(false);
    if (message.type === "error") {
      if (urlAttempt.current) {
        const attempted = urlAttempt.current;
        urlAttempt.current = null;
        try {
          if (localStorage.getItem("orbit_roomId") === attempted) localStorage.removeItem("orbit_roomId");
          localStorage.removeItem(`orbit_token_${attempted}_${myId}`);
        } catch {}
        setRoomData(null); setRoomId(""); setScreen("lobby");
        replacePath(buildPath("orbit"));
      }
      setToast(message.message || "Something went wrong");
      return;
    }
    const room = message.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const token = room.reconnect_tokens?.[myId];
    if (token) {
      try {
        localStorage.setItem(`orbit_token_${rid}_${myId}`, token);
        localStorage.setItem("orbit_roomId", rid);
      } catch {}
    }
    setRoomData(room); setRoomId(rid);
    const inGame = room.status === "playing" || room.status === "over";
    if (message.type === "created" || message.type === "joined") {
      if (rid) pushPath(buildPath("orbit", rid));
      urlAttempt.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (inGame) setScreen("game");
  }, [myId, roomId]);

  const { connected, connect, send, socketReady, disconnect } = useSocket(handleMessage);
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);

  // Hard Orbit is a per-decision browser tier.  Root-parallel workers leave one
  // hardware thread for the compositor, matching the serving rule used by the
  // other games.  A missing/failed worker simply leaves the room unarmed and
  // the server watchdog plays the validated fallback.
  useEffect(() => {
    const enabled = roomData?.vs_ai && CLIENT_AI_TIERS.includes(roomData?.ai_difficulty);
    if (!enabled || typeof Worker === "undefined") {
      wasmPoolRef.current = null;
      wasmMetaRef.current = null;
      setWasmReady(false);
      return undefined;
    }
    const hardware = Math.max(1, Number(navigator.hardwareConcurrency) || 1);
    const count = Math.max(1, Math.min(hardware - 1, ORBIT_AI_WORKER_CAP));
    const url = `${import.meta.env.BASE_URL}wasm/orbit-worker.js`;
    const generation = ++aiGenerationRef.current;
    const workers = [];
    const makeWorker = () => {
      let worker;
      try { worker = new Worker(url, { type: "module" }); } catch { return null; }
      const pending = new Map();
      let nextId = 1;
      let resolveReady;
      const ready = new Promise((resolve) => { resolveReady = resolve; });
      worker.onmessage = (event) => {
        const data = event.data || {};
        if (data.ready !== undefined) { resolveReady(data.ready ? data : null); return; }
        const callback = pending.get(data.id);
        if (callback) { pending.delete(data.id); callback(data); }
      };
      worker.onerror = () => resolveReady(null);
      return {
        ready,
        request(payload) {
          const id = nextId++;
          return new Promise((resolve) => {
            pending.set(id, resolve);
            try { worker.postMessage({ ...payload, id }); } catch { pending.delete(id); resolve(null); }
          });
        },
        terminate() { try { worker.terminate(); } catch {} },
      };
    };
    for (let i = 0; i < count; i += 1) {
      const worker = makeWorker();
      if (worker) workers.push(worker);
    }
    wasmPoolRef.current = workers;
    wasmMetaRef.current = null;
    setWasmReady(false);
    Promise.all(workers.map((worker) => worker.ready)).then((metas) => {
      if (generation !== aiGenerationRef.current) return;
      const live = workers.filter((_, index) => metas[index]);
      if (!live.length) return;
      wasmPoolRef.current = live;
      wasmMetaRef.current = metas.find(Boolean) || null;
      setWasmReady(true);
      console.info(`[orbit client-AI] ${live.length}/${count} workers ready`);
    });
    return () => {
      aiGenerationRef.current += 1;
      workers.forEach((worker) => worker.terminate());
      wasmPoolRef.current = null;
      wasmMetaRef.current = null;
      setWasmReady(false);
    };
  }, [roomData?.vs_ai, roomData?.ai_difficulty]);

  useEffect(() => {
    if (!connected) {
      clientAiArmedRef.current = null;
      aiDispatchRef.current = null;
    }
  }, [connected]);

  useEffect(() => {
    if (wasmReady && connected && roomData?.room_id
      && CLIENT_AI_TIERS.includes(roomData?.ai_difficulty)
      && clientAiArmedRef.current !== roomData.room_id) {
      const meta = wasmMetaRef.current;
      if (!meta?.rules) return;
      clientAiArmedRef.current = roomData.room_id;
      send({ action: "client_ai_ready", wire: meta.abi_version || ORBIT_AI_WIRE,
        abi_version: meta.abi_version || ORBIT_AI_WIRE,
        model_version: meta.model_version || ORBIT_AI_MODEL_VERSION,
        encoder: meta.encoder || ORBIT_AI_ENCODER, schema: meta.schema || ORBIT_AI_SCHEMA,
        rules: meta.rules });
    }
  }, [wasmReady, connected, roomData?.room_id, roomData?.ai_difficulty, send]);

  useEffect(() => {
    const request = roomData?.ai_search;
    const pool = wasmPoolRef.current;
    if (!request || !wasmReady || !pool?.length || !connected) return;
    const key = `${roomData.room_id}:${request.decision}:${request.position}`;
    if (aiDispatchRef.current === key) return;
    aiDispatchRef.current = key;
    const generation = aiGenerationRef.current;
    const legal = request.legal_moves || request.observation?.legal_moves || [];
    const payload = {
      kind: "choose",
      observation: request.observation,
      // The effect queue, which the observation redacts to its first task.
      // Without it the Expert cannot rebuild an effect-resolution position and
      // hands 45% of its decisions to the 1-ply ranker instead of searching.
      pending_chain: request.pending_chain ?? null,
      legal_moves: legal,
      memory: request.memory || {},
      remaining_turn_budget: request.remaining_turn_budget ?? ORBIT_AI_TURN_BUDGET_MS,
      // Expert searches; budget_ms is THIS decision's slice of the turn, which
      // the server already split into a main action and a follow-up reserve.
      tier: request.tier || roomData?.ai_difficulty || "hard",
      budget_ms: request.budget_ms ?? request.remaining_turn_budget ?? ORBIT_AI_TURN_BUDGET_MS,
    };
    (async () => {
      try {
        const results = await Promise.all(pool.map((worker, index) => worker.request({
          ...payload,
          seed: ((Number(request.decision) * 2654435761) ^ (index * 40503 + 1)) >>> 0,
        }).catch(() => null)));
        if (generation !== aiGenerationRef.current || aiDispatchRef.current !== key) return;
        const allowed = new Map(legal.map((move) => [orbitMoveKey(move), move]));
        // A searching worker reports root visits, and independent trees are
        // combined by SUMMING them -- the arena measured that aggregation, and
        // it keeps how sure each tree was.  A ranking worker (Hard) reports no
        // stats, so each answer is worth one vote, exactly as before.
        const votes = new Map();
        for (const result of results) {
          const move = result?.move;
          const canonical = orbitMoveKey(move);
          if (!allowed.has(canonical)) continue;
          const item = votes.get(canonical) || { count: 0, move: allowed.get(canonical) };
          item.count += 1; votes.set(canonical, item);
        }
        let summed = new Map();
        for (const result of results) {
          for (const entry of Array.isArray(result?.stats) ? result.stats : []) {
            const canonical = orbitMoveKey(entry?.move);
            if (!allowed.has(canonical)) continue;
            const visits = Number(entry?.visits);
            if (!Number.isFinite(visits) || visits <= 0) continue;
            const item = summed.get(canonical) || { count: 0, move: allowed.get(canonical) };
            item.count += visits; summed.set(canonical, item);
          }
        }
        if (summed.size) votes.clear(), summed.forEach((v, k) => votes.set(k, v));
        if (!votes.size) return; // watchdog fallback owns a failed pool
        const chosen = [...votes.values()].sort((a, b) => b.count - a.count
          || orbitMoveKey(a.move).localeCompare(orbitMoveKey(b.move)))[0];
        const memory = results.find((result) => orbitMoveKey(result?.move) === orbitMoveKey(chosen.move))?.memory
          || request.memory || {};
        send({ action: "ai_move", protocol: ORBIT_AI_WIRE,
          decision: request.decision, position: request.position,
          wire: ORBIT_AI_WIRE, model_version: ORBIT_AI_MODEL_VERSION,
          encoder: ORBIT_AI_ENCODER, schema: ORBIT_AI_SCHEMA,
          rules: request.rules, move: chosen.move, memory });
      } catch { /* the server watchdog owns this decision */ }
    })();
  }, [roomData, wasmReady, connected, send]);

  useEffect(() => {
    try {
      const cached = localStorage.getItem("orbit_catalog");
      if (cached) setCatalog(JSON.parse(cached));
    } catch {}
    fetch(`${ORBIT_HTTP}/catalog`).then((r) => r.json()).then((data) => {
      if (!data.cards) return;
      setCatalog(data);
      try { localStorage.setItem("orbit_catalog", JSON.stringify(data)); } catch {}
    }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setRefreshing(true);
    fetch(`${ORBIT_HTTP}/games`).then((r) => r.json()).then((data) => {
      const rows = data.games || []; setOpenGames(rows); writeLobbyCache("orbit", myId, "open", rows);
    }).catch(() => {}).finally(() => setRefreshing(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${ORBIT_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((data) => {
        const rows = data.games || []; setMyGames(rows); writeLobbyCache("orbit", myId, "mine", rows);
      }).catch(() => {});
      fetchGameHistory(`${ORBIT_HTTP}/games/history`, authUser).then((data) => {
        const rows = data.games || []; setHistory(rows); writeLobbyCache("orbit", myId, "history", rows);
      }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby" && !connecting) fetchGames(); }, [screen, connecting, fetchGames]);
  // The game you just finished leaves Active and joins History the moment it
  // ENDS, not when the lobby next loads — see useFinishedGameSync (shared kit).
  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("orbit", myId, "mine", rid, setMyGames);
    fetchGames();
  });
  useEffect(() => () => disconnect(), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(""), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  const createGame = useCallback((vsAi, difficulty = createDifficulty) => {
    const rid = Math.random().toString(36).slice(2, 7).toUpperCase();
    setConnecting(true); setRoomId(rid); setShowCreate(false);
    if (vsAi) rememberDifficulty(difficulty);
    connect(`${ORBIT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player", vs_ai: vsAi, configuration: "random",
      ai_difficulty: difficulty,
    });
  }, [connect, myId, authUser, createDifficulty, rememberDifficulty]);

  const joinGame = useCallback((raw) => {
    const rid = String(raw || "").trim().toUpperCase();
    if (!rid) return;
    setConnecting(true); setRoomId(rid);
    connect(`${ORBIT_WS}/${rid}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  }, [connect, myId, authUser]);

  const resumeGame = useCallback((rid) => {
    let token = null;
    try { token = localStorage.getItem(`orbit_token_${rid}_${myId}`); } catch {}
    setConnecting(true); setRoomId(rid);
    connect(`${ORBIT_WS}/${rid}/${myId}`, token
      ? { action: "reconnect", token }
      : { action: "join", name: authUser?.name || "Player", session_token: authUser?.session_token || null });
  }, [connect, myId, authUser]);

  const cancelGame = useCallback((gid) => {
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    const roomToken = readRoomToken(`orbit_token_${gid}_${myId}`);
    if (roomToken) headers["X-Room-Token"] = roomToken;
    fetch(`${ORBIT_HTTP}/games/${gid}?player_id=${encodeURIComponent(myId)}`, {
      method: "DELETE", headers,
    }).then(fetchGames).catch(() => {});
  }, [authUser, fetchGames, myId]);
  const leaveSeat = useCallback(async (gid) => {
    try {
      await leaveOpenSeat({
        endpoint: `${ORBIT_HTTP}/games`, roomId: gid, playerId: myId,
        tokenKey: `orbit_token_${gid}_${myId}`, sessionToken: authUser?.session_token,
      });
      setToast("Seat released");
      fetchGames();
    } catch (err) { setToast(err?.message || "Could not leave that table"); }
  }, [authUser, myId, fetchGames]);

  const reconnectNow = useCallback(() => {
    let token = null;
    try { token = localStorage.getItem(`orbit_token_${roomId}_${myId}`); } catch {}
    if (token) connect(`${ORBIT_WS}/${roomId}/${myId}`, { action: "reconnect", token });
  }, [roomId, myId, connect]);
  useAutoReconnect({
    enabled: !!roomId && screen === "game" && roomData?.status !== "over",
    connected, connect: reconnectNow, socketReady,
  });

  const leaveToLobby = useCallback(() => {
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    replacePath(buildPath("orbit"));
  }, [disconnect]);

  useEffect(() => {
    const rid = deepLinkRoom();
    if (rid) { urlAttempt.current = rid; resumeGame(rid); }
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => subscribe((route) => {
    if (route.game !== "orbit") return;
    if (route.room) { urlAttempt.current = route.room; resumeGame(route.room); }
    else leaveToLobby();
  }), [resumeGame, leaveToLobby]);

  const game = roomData?.game;
  const motionSurface = useRef(null);
  const names = roomData?.players || {};
  const otherId = game?.order?.find((pid) => pid !== myId);
  const me = game?.players?.[myId];
  const other = game?.players?.[otherId];
  const legal = game?.legal_moves || [];
  const isMyTurn = legal.length > 0;
  const over = game?.phase === "over";
  useCardMotion({ game, catalog, myId, roomId, connected, surface: motionSurface });

  useEffect(() => {
    if (!me?.hand?.some((card) => card.id === selectedCard)) setSelectedCard(null);
  }, [me?.hand, selectedCard]);
  useEffect(() => { if (game?.phase !== "mulligan") setMulligan([]); }, [game?.phase]);
  const forcedChoice = useRef(null);
  useEffect(() => {
    const automatic = automaticChoices(game);
    if (!connected || !game?.pending || game.pending_pid !== myId || !automatic.length) {
      forcedChoice.current = null;
      return;
    }
    const key = orbitMoveKey({ roomId, turn: game.turn_number, pending: game.pending, moves: automatic, log: game.log?.slice(-2) });
    if (forcedChoice.current === key) return;
    forcedChoice.current = key;
    sendMove(automatic[Math.floor(Math.random() * automatic.length)]);
  }, [game, connected, myId, roomId, sendMove]);


  if (connecting && screen === "lobby") return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style><LobbyLoading label="Connecting…" /></div>;
  if (screen === "lobby") return <Lobby {...{
    authUser, myId, onExit, openGames, myGames, history, historyShown, historyMore,
    refreshing, fetchGames, joinGame, resumeGame, cancelGame, leaveSeat, showCreate, setShowCreate,
    createOpp, setCreateOpp, createDifficulty, setCreateDifficulty,
    createGame, lobbyTab, setLobbyTab,
    showRules, setShowRules, toast,
  }} />;

  // `WaitingRoom` in shared/lobby.jsx.
  if (screen === "waiting") {
    return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style>
      <WaitingRoom
        game="orbit" roomId={roomId}
        players={names} hostId={roomData?.host} myId={myId}
        min={2} max={2}
        note="One vs one, five planets, three factions."
        user={authUser}
        onLeave={leaveToLobby}
        onRules={() => setShowRules(true)}
        onStart={() => send({ action: "start" })} />
      {showRules && <RulesModal title="How to play — Orbit" onClose={() => setShowRules(false)}><OrbitRules /></RulesModal>}
      {toast && <div className="or-toast">{toast}</div>}
    </div>;
  }

  if (!game || !me) return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style><LobbyLoading label="Loading Orbit…" /></div>;

  const cardMoves = selectedCard == null ? [] : legal.filter((move) => move.card_id === selectedCard);
  const selectedAgent = me.hand.find((card) => card.id === selectedCard);
  const recruitCost = selectedAgent
    ? Math.max(0, selectedAgent.cost - (me.columns?.[selectedAgent.planet]?.length || 0))
    : null;
  const technologyCost = selectedAgent
    ? (me.technology?.[selectedAgent.faction] || 0) + 1
    : null;
  const winnerName = game.winner ? names[game.winner] : null;
  const botIsOpponent = roomData?.ai_player === otherId;
  const myHint = over ? null
    : game.phase === "mulligan" && isMyTurn ? "Choose replacements"
      : game.pending_pid === myId ? (legal.length > 1 ? "Your turn" : "Resolving…")
        : isMyTurn ? "Choose an Agent" : null;
  const otherHint = !over && botIsOpponent
    ? game.pending_pid === otherId ? "Resolving…"
      : game.phase === "mulligan" && !isMyTurn ? "Thinking…"
        : !game.pending && game.turn_pid === otherId ? "Thinking…" : null
    : null;
  // WHO IS ACTING lights the table (seat glow, the hand's pool of light) and
  // dims the seat that is waiting. Nobody, once the game is over.
  const actor = over ? null : game.pending_pid || game.turn_pid;
  const acting = actor === myId ? " or-acting-mine" : actor && actor === otherId ? " or-acting-theirs" : "";
  const playerRails = (
      <div className="or-score-rail">
        <PlayerRail player={{ ...other, __pid: otherId }} name={names[otherId]} active={!over && (game.pending_pid || game.turn_pid) === otherId}
          leader={game.leader} connected={connected} orderLabel={game.phase === "mulligan" ? (game.order[0] === otherId ? "First player" : "Second player") : null} hint={otherHint} onInfo={setInfo} />
        <PlayerRail player={{ ...me, __pid: myId }} name={names[myId]} active={!over && (game.pending_pid || game.turn_pid) === myId}
          me leader={game.leader} connected={connected} orderLabel={game.phase === "mulligan" ? (game.order[0] === myId ? "First player" : "Second player") : null} hint={myHint} onInfo={setInfo} />
      </div>
  );
  return <div className={`app orbit or-game${!over && game.phase !== "mulligan" ? " or-live" : ""}`} style={{ "--lby-accent": GAME_ACCENTS.orbit }}>
    <style>{styles}</style>
    <LobbyHeader title="Orbit" user={<span className={`or-connection${connected ? "" : " lost"}`}>{connected ? (authUser?.name || "Connected") : "Reconnecting…"}</span>}
      menu={<GameMenu onLeave={leaveToLobby} onRules={() => setShowRules(true)}
        onAbandon={over ? null : () => setConfirmAbandon(true)} />} />
    <OrbitSky />
    <main className={`or-table${connected ? "" : " motion-paused"}${acting}`} ref={motionSurface}>
      {game.phase === "mulligan" && playerRails}

      {over && <section className="or-result">
        <h1>{winnerName ? `${winnerName} wins${victoryCondition(game) ? ` by ${victoryCondition(game)}` : ""}` : "The Agent supply was exhausted"}</h1>
        <button type="button" onClick={leaveToLobby}>Return to lobby</button>
      </section>}

      {game.phase === "mulligan" && isMyTurn && <section className="or-mulligan">
        <span className="or-eyebrow">Opening hand</span><h2>Replace any Agents?</h2>
        {/* The copy names the CUE, not the gesture. "Select the cards you want to
            discard" describes a click and leaves the reader to work out which of
            two marked states they are looking at; naming the fade means the
            picture and the sentence say the same thing. */}
        <p>Tap the Agents you want to replace — they fade out. You draw back to four.</p>
        <div className="or-hand">{sortedHand(me.hand).map((card) => <AgentCard card={card} key={card.id} discarding={mulligan.includes(card.id)} onInfo={setInfo}
          onClick={() => setMulligan((old) => old.includes(card.id) ? old.filter((id) => id !== card.id) : [...old, card.id])} />)}</div>
        <button type="button" className="or-primary" onClick={() => sendMove({ action: "mulligan", card_ids: [...mulligan].sort((a, b) => a - b) })}>
          {mulligan.length ? `Replace ${mulligan.length} card${mulligan.length === 1 ? "" : "s"}` : "Keep this hand"}
        </button>
      </section>}
      {game.phase === "mulligan" && !isMyTurn && !botIsOpponent && <section className="or-status"><span className="or-spinner" /> Waiting for the other mulligan…</section>}

      {game.phase !== "mulligan" && <div className="or-board-layout">
        <div className="or-board-main">
          {playerRails}
          <InfluenceBoard key={`${roomId}-${connected}`} game={game} myId={myId} catalog={catalog} onInfo={setInfo} />
          <section className="or-hand-zone">
            <Hand>{sortedHand(me.hand).map((card) => <AgentCard card={card} key={card.id} selected={selectedCard === card.id} onInfo={setInfo}
              onClick={isMyTurn && !game.pending ? () => setSelectedCard(card.id) : null} />)}</Hand>
            <div className={`or-controls${game.pending_pid === myId && legal.length > 1 && !automaticChoices(game).length ? " deciding" : ""}`}>
            {!over && game.pending && game.pending_pid === myId && <DecisionPanel game={game} catalog={catalog} sendMove={sendMove} onInfo={setInfo} />}
            {!over && game.pending && game.pending_pid !== myId && !botIsOpponent && <section className="or-status"><span className="or-spinner" /> {names[game.pending_pid] || "Opponent"} is resolving {game.pending.source}…</section>}
            {!over && !game.pending && !isMyTurn && !botIsOpponent && <section className="or-status"><span className="or-spinner" /> {names[game.turn_pid] || "Opponent"} is choosing an action…</section>}
            {selectedAgent && isMyTurn && !game.pending && <div className="or-action-bar">
              <span>Play <b>{me.hand.find((card) => card.id === selectedCard)?.name}</b> as:</span>
              <div>{["recruit", "technology", "leader"].map((action) => {
                const move = cardMoves.find((candidate) => candidate.action === action);
                const label = action === "recruit"
                  ? `Recruit · ${recruitCost} Credits`
                  : action === "technology"
                    ? `Develop ${selectedAgent?.faction || "Technology"} · ${technologyCost} Zenithium`
                    : `Become Leader · ${selectedAgent?.faction || "Faction"}${selectedAgent?.faction
                      ? ` (${LEADER_EFFECT[selectedAgent.faction]})` : ""}`;
                return <button type="button" key={action} disabled={!move} onClick={() => move && sendMove(move)}>{label}</button>;
              })}</div>
            </div>}
            {!over && !game.pending && isMyTurn && !selectedAgent && <p className="or-control-hint">Choose a card to recruit an Agent, develop technology, or become Leader.</p>}
            </div>
          </section>
        </div>
        <div className="or-sideboards"><TechBoard game={game} myId={myId} otherId={otherId} catalog={catalog}
          myName={names[myId]} theirName={names[otherId]} onInfo={setInfo} />
          <MoveLog entries={game.log} game={game} catalog={catalog} myId={myId} onInfo={setInfo} />
        </div>
      </div>}
    </main>
    <InfoModal info={info} catalog={catalog} onInfo={setInfo} onClose={() => setInfo(null)} />
    {showRules && <RulesModal title="How to play — Orbit" onClose={() => setShowRules(false)}><OrbitRules /></RulesModal>}
    {confirmAbandon && <div className="or-confirm" onClick={() => setConfirmAbandon(false)}><div role="dialog" onClick={(e) => e.stopPropagation()}>
      <h2>Abandon this game?</h2><p>Your opponent will win immediately.</p><span><button type="button" onClick={() => setConfirmAbandon(false)}>Keep playing</button>
        <button type="button" className="danger" onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>Abandon</button></span>
    </div></div>}
    {toast && <div className="or-toast">{toast}</div>}
  </div>;
}
