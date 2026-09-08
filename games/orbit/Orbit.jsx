import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyMatchup, LobbyLoading, LobbyEmpty,
  LobbyAction, LobbyTabs, notWaiting, GameMenu, gameMenuCss,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, useProgressiveList, LobbyHero, LobbyUser, useListFade,
  readLobbyCache, writeLobbyCache, timeAgo, useLastDifficulty,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { useCardInfoGesture } from "../../shared/gestures.js";
import OrbitRules from "./rules.jsx";
import { Resource, ResourceIcon, decisionCopy, victoryCondition, InfluenceDisc } from "./presentation.jsx";
import orbitCssText from "./Orbit.css?inline";


const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const ORBIT_WS = `${WS_BASE}/orbit/ws`;
const ORBIT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/orbit");
const ORBIT_AI_TIERS = ["random", "hard"];
const ORBIT_AI_WIRE = 1;
const ORBIT_AI_MODEL_VERSION = 1;
const ORBIT_AI_ENCODER = "orbit-observation-v1";
const ORBIT_AI_SCHEMA = 1;
const ORBIT_AI_TURN_BUDGET_MS = 5000;
const ORBIT_AI_WORKER_CAP = 4;
const styles = baseCss + lobbyCss + gameMenuCss + createModalCss
  + lobbyCreateRowCss + rulesModalCss + orbitCssText;

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
    return <button type="button" className="or-log-ref or-log-bonus" title={`${text} — tap to read`}
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
  const viewport = useRef(null);
  useEffect(() => {
    const node = viewport.current;
    const fit = () => {
      const css = getComputedStyle(node);
      const available = node.clientWidth - parseFloat(css.paddingLeft) - parseFloat(css.paddingRight);
      node.style.setProperty("--or-hand-scale", Math.min(1, (available - 5 * parseFloat(css.columnGap)) / (6 * 145)));
    };
    const observer = new ResizeObserver(fit);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);
  return <div className="or-hand" ref={viewport}>{children}</div>;
}


function captureSummary(captured = []) {
  return captured.map((planet, index) => (
    <i className={`or-capture-disc or-${planet}`} key={`${planet}-${index}`}
      title={`Captured ${planet}`} aria-label={`Captured ${planet}`} />
  ));
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

function orbitMoveKey(move) {
  if (!move || typeof move !== "object") return "";
  const stable = (value) => Array.isArray(value)
    ? `[${value.map(stable).join(",")}]`
    : value && typeof value === "object"
      ? `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${stable(value[key])}`).join(",")}}`
      : JSON.stringify(value);
  try { return stable(move); } catch { return ""; }
}


function PlayerRail({ player, name, active, me, leader, hint, onInfo, connected }) {
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
    <div className="or-resources">
      <Resource key={`credits-${connected}`} kind="credits" value={player.credits} animate={connected} />
      <Resource key={`zenithium-${connected}`} kind="zenithium" value={player.zenithium} animate={connected} />
      <span className="or-resource-cards">
        <HandCount held={player.hand?.length || 0} limit={handLimit(leader, player.__pid)} />
        {!!player.captured?.length && <span className="or-captures" aria-label="Captured planets">
          {captureSummary(player.captured)}
        </span>}
      </span>
    </div>
    <div className="or-played-agents" aria-label={`${owner} played Agents`}>
      <span>Played</span>
      <div>{PLANETS.map((planet) => {
        const cards = player.columns?.[planet] || [];
        return <button type="button" key={planet} className={`or-played-agent or-${planet}`}
          data-motion-key={`column-${player.__pid}-${planet}`} data-motion-value={cards.map((card) => card.id).join(",")}
          disabled={!cards.length} title={`${cards.length} ${planet} Agent${cards.length === 1 ? "" : "s"}. ${cards.length ? "Open details" : "None played"}`}
          aria-label={`${cards.length} ${planet} Agent${cards.length === 1 ? "" : "s"}${cards.length ? ". Open details" : ""}`}
          {...detailClick(() => cards.length && onInfo?.({ kind: "column", planet, cards, owner }))}>
          {cards.length}
        </button>;
      })}</div>
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
    aria-label={`${text}. Open bonus details`} title={`${text} — tap to read`}
    {...(onInfo ? detailClick((event) => { event.stopPropagation(); onInfo({ kind: "bonus", token }); }) : {})}>
    <i aria-hidden="true">✦</i><span className="or-sr-only">{text}</span>
  </button>;
}


function InfluenceBoard({ game, myId, catalog, onInfo, names, connected }) {
  const mineIsPositive = game.order?.[0] === myId;
  const spaces = [-4, -3, -2, -1, 0, 1, 2, 3, 4];
  const recent = [...(game.log || [])].reverse();
  const latest = recent.find((entry) => !entry.turn_start && !/draws? .*Agents?|ends? (the |their )?turn/i.test(logText(entry)))
    || recent.find((entry) => !entry.turn_start);
  const recentTurn = latest ? (game.log || []).filter((entry) => entry.turn === latest.turn) : [];
  const actor = latest?.pid;
  return <section className="or-influence" aria-label="Planet influence board">
    {PLANETS.map((planet) => {
      const raw = game.influence?.[planet];
      const position = raw == null ? null : (mineIsPositive ? raw : -raw);
      return <div className={`or-track or-${planet}`} key={planet}>
        <div className="or-track-name"><PlanetName planet={planet} /></div>
        <div className="or-track-spaces">
          {spaces.map((space) => <span className={`or-space${Math.abs(space) === 4 ? " goal" : ""}${space === 0 ? " middle" : ""}`} key={space} />)}
          <InfluenceDisc position={position} planet={planet} game={game} myId={myId} />
        </div>
        <Bonus token={game.planet_bonus?.[planet]} catalog={catalog} onInfo={onInfo} />
      </div>;
    })}
    <div className={`or-activity ${actor === myId ? "mine" : "theirs"}`} role="status" aria-live="polite" aria-atomic="true">
      <b key={`${game.turn_number}-${actor}-${game.phase}`} className="or-turn-label">Turn recap</b>
      <button type="button" className="or-activity-detail" disabled={!latest}
        aria-label="Read the latest turn" onClick={() => onInfo({ kind: "activity", entries: recentTurn })}>
        <span>{latest ? logText(latest) : "Influence moves toward the player who gains it."}</span>
      </button>
    </div>
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
          {rows.map((space) => <div className={`or-tech-row${space.level === 2 ? " has-token" : ""}`} key={space.level}>
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
   press-and-hold / right-click always reads (see shared/gestures.js). */
function AgentCard({ card, selected, onClick, onInfo, hidden = false }) {
  const info = useCardInfoGesture(onInfo && card && !card.hidden
    ? () => onInfo({ kind: "card", card }) : null);
  if (hidden || card?.hidden) return <div className="or-agent hidden" aria-label="Hidden Agent"><span>ORBIT</span></div>;
  if (!card) return null;
  return <button type="button" className={`or-agent or-${card.planet} or-${card.faction}${selected ? " selected" : ""}${onClick ? " playable" : ""}`}
    onClick={onClick || (onInfo ? () => onInfo({ kind: "card", card }) : undefined)}
    disabled={!onClick && !onInfo} title={card.description} {...info}>
    <span className="or-agent-top"><span className="or-card-price"><ResourceIcon kind="credits" /><b>{card.cost}</b></span><i>{FACTION_GLYPH[card.faction]}</i></span>
    <strong>{card.name}</strong>
    <span className="or-agent-text">{card.description}</span>
    <span className="or-agent-foot"><PlanetName planet={card.planet} /> · {card.faction}</span>
  </button>;
}


/* THE PLACED-AGENT COLUMNS, CONDENSED SO ALL FIVE PLANETS FIT. Each occupied
   column is one recognisable mini-card with up to two offset layers behind it;
   the count sits beside the planet name. That reads as a stack without the old
   detached "+N below" button looking like a second unrelated control.
   The section names its OWNER unambiguously — "Your agents" with a seat dot,
   never a bare possessive a player has to match against a half-read name.
   Reading your own recruit into the opponent's panel is the exact mistake the
   old pair of identical panels invited. */
function Columns({ game, pid, name, mine, onInfo }) {
  const player = game.players?.[pid];
  return <section className={`or-columns${mine ? " mine" : " theirs"}`}>
    <h3><i className="or-seat-dot" aria-hidden="true" />{mine ? "Your agents" : `${name || "Opponent"} · agents`}</h3>
    <div className="or-column-grid">
      {PLANETS.map((planet) => {
        const cards = player?.columns?.[planet] || [];
        const top = cards[cards.length - 1];
        const stackInfo = cards.length > 1
          ? { kind: "column", planet, cards, owner: mine ? "Your" : `${name || "Opponent"}’s` }
          : { kind: "card", card: top };
        return <div className={`or-column or-${planet}`} key={planet}>
          <span className="or-column-head"><PlanetName planet={planet} /><b data-motion-key={`stack-${pid}-${planet}`} data-motion-value={cards.map((card) => card.id).join(",")} className="or-column-count" aria-label={`${cards.length} Agents`}>{cards.length}</b></span>
          {top ? <button type="button" className={`or-slot${cards.length > 1 ? " stacked" : ""}`}
            title={`${cards.length} Agent${cards.length === 1 ? "" : "s"} — ${top.name} on top`}
            {...detailClick(() => onInfo(stackInfo))}>
            <strong>{top.name}</strong>
          </button> : <span className="or-column-empty">empty</span>}
        </div>;
      })}
    </div>
  </section>;
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
  } else if (info.kind === "activity") {
    eyebrow = "Turn recap";
    title = "Latest action";
    body = <div className="or-recap">{info.entries.map((entry, index) => <p className="or-info-text" key={index}>{logText(entry)}</p>)}</div>;
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
  const pending = game.pending?.task;
  const moves = game.legal_moves || [];
  if (!pending || moves.length === 1) return null;
  const optionalPlanet = pending.planets?.[pending.index || 0];
  const optionalAgent = game.players?.[game.pending_pid]?.columns?.[optionalPlanet]?.at(-1);
  const { title, detail } = decisionCopy(pending, optionalAgent?.name);
  const planetChoices = moves.every((move) => "planet" in move) && moves.length <= 5;
  const action = [...(game.log || [])].reverse().find((entry) => entry.action)?.action;
  const context = action === "technology" ? "Technology" : action === "leader" ? "Leader action" : "Agent effect";
  return <section className="or-decision" aria-live="polite">
    <div className="or-decision-source"><span>{context}</span><b>{game.pending.source}</b></div>
    <h2>{title}</h2>
    {detail && <p className="or-decision-detail">{detail}</p>}
    {!moves.length && <p className="or-decision-detail">Waiting for the server to resolve this effect…</p>}
    <div className={`or-choice-grid${planetChoices ? " planet-choices" : ""}`} style={{ "--or-choice-count": Math.min(5, moves.length) }}>
      {moves.map((move, index) => <DecisionChoice key={index} {...{ move, task: pending, game, catalog, sendMove, onInfo }} />)}
    </div>
    {["exile", "exile_for_matching", "transfer", "discard_hand"].includes(pending.type) && <p className="or-decision-help">Hold an Agent to read its card.</p>}
  </section>;
}


function Lobby({ authUser, myId, onExit, openGames, myGames, history, historyShown,
  historyMore, refreshing, fetchGames, joinGame, resumeGame, cancelGame,
  showCreate, setShowCreate, createOpp, setCreateOpp, createSetup, setCreateSetup,
  createDifficulty, setCreateDifficulty, createGame, lobbyTab, setLobbyTab,
  showRules, setShowRules, toast }) {
  const active = notWaiting(myGames);
  const selectedOpponent = createOpp === "friend" ? "friend" : createDifficulty;
  const chooseOpponent = (value) => {
    if (value === "friend") {
      setCreateOpp("friend");
      return;
    }
    setCreateOpp("ai");
    setCreateDifficulty(value);
  };
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
            <div className="lby-card-info"><div className="lby-card-title">{g.host_id === myId ? "Your game" : `${g.host_name || "Player"}’s game`}<span className="lby-seats">1/2</span></div>
              <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div></div>
            <div className="lby-card-actions">{g.host_id === myId ? <>
              <LobbyAction kind="secondary" onClick={() => resumeGame(g.id)}>Return</LobbyAction>
              <LobbyAction kind="danger" onClick={() => cancelGame(g.id)}>Cancel</LobbyAction>
            </> : <LobbyAction onClick={() => joinGame(g.id)}>Join</LobbyAction>}</div>
          </div>)}</div>
        </div>
        <div className="lby-col-active">
          <LobbySectionHd title="Active Games" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          <div className="lby-list">{active.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info"><LobbyMatchup placeholder="Opponent" seats={[
              { name: g.player1_name, you: g.you_are_p1 }, { name: g.player2_name, you: !g.you_are_p1 },
            ]} />
              <div className="lby-card-meta">{g.turn ? `turn ${g.turn} · ` : ""}{timeAgo(g.updated_at)}</div></div>
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
              <div className="lby-card-meta">{g.turns ? `${g.turns} turns · ` : ""}{timeAgo(g.updated_at)}</div></div>
          </div>)}{historyMore}</div>
        </div>
      </div>
    </div></div>
    {showCreate && <CreateModal title="New Orbit game" onClose={() => setShowCreate(false)}>
      <CmRow label="Opponent"><CmSeg value={selectedOpponent} onChange={chooseOpponent} options={[
        { value: "friend", label: "VS Friend" },
        { value: "random", label: "VS Random AI" },
        { value: "hard", label: "VS Strong AI", title: "Browser search with a validated server fallback" },
      ]} wrap /></CmRow>
      <CmRow label="Technology board"><CmSeg value={createSetup} onChange={setCreateSetup} options={[
        { value: "sun", label: "S.U.N.", title: "The recommended first-game board" },
        { value: "random", label: "Random", title: "Flip all three faction strips independently" },
      ]} /></CmRow>
      <span className="cm-hint">Complete 1v1 rules and all 90 base-game Agents. Strong AI searches in your browser and falls back safely if it is unavailable.</span>
      <div className="cm-footer"><span className="cm-summary">Creating: <b>{selectedOpponent === "friend" ? "vs Friend" : selectedOpponent === "hard" ? "vs Strong AI" : "vs Random AI"}</b></span>
        <button type="button" className="cm-create" onClick={() => createGame(createOpp === "ai", createSetup, createDifficulty)}>Create Game</button></div>
    </CreateModal>}
    {showRules && <RulesModal title="How to play — Orbit" onClose={() => setShowRules(false)}><OrbitRules /></RulesModal>}
    {toast && <div className="or-toast">{toast}</div>}
  </div>;
}


export default function Orbit({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");
  const [connecting, setConnecting] = useState(false);
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
  const [createSetup, setCreateSetup] = useState("sun");
  const [createDifficulty, setCreateDifficulty, rememberDifficulty] =
    useLastDifficulty("orbit", myId, ORBIT_AI_TIERS, "hard");
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
    const enabled = roomData?.vs_ai && roomData?.ai_difficulty === "hard";
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
      && roomData?.ai_difficulty === "hard"
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
      legal_moves: legal,
      memory: request.memory || {},
      remaining_turn_budget: request.remaining_turn_budget ?? ORBIT_AI_TURN_BUDGET_MS,
    };
    (async () => {
      try {
        const results = await Promise.all(pool.map((worker, index) => worker.request({
          ...payload,
          seed: ((Number(request.decision) * 2654435761) ^ (index * 40503 + 1)) >>> 0,
        }).catch(() => null)));
        if (generation !== aiGenerationRef.current || aiDispatchRef.current !== key) return;
        const allowed = new Map(legal.map((move) => [orbitMoveKey(move), move]));
        const votes = new Map();
        for (const result of results) {
          const move = result?.move;
          const canonical = orbitMoveKey(move);
          if (!allowed.has(canonical)) continue;
          const item = votes.get(canonical) || { count: 0, move: allowed.get(canonical) };
          item.count += 1; votes.set(canonical, item);
        }
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
      fetch(`${ORBIT_HTTP}/games/history`, { headers }).then((r) => r.json()).then((data) => {
        const rows = data.games || []; setHistory(rows); writeLobbyCache("orbit", myId, "history", rows);
      }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => () => disconnect(), []); // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (!toast) return undefined;
    const timer = setTimeout(() => setToast(""), 2800);
    return () => clearTimeout(timer);
  }, [toast]);

  const createGame = useCallback((vsAi, configuration, difficulty = createDifficulty) => {
    const rid = Math.random().toString(36).slice(2, 7).toUpperCase();
    setConnecting(true); setRoomId(rid); setShowCreate(false);
    if (vsAi) rememberDifficulty(difficulty);
    connect(`${ORBIT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player", vs_ai: vsAi, configuration,
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
    if (!authUser?.session_token) return;
    fetch(`${ORBIT_HTTP}/games/${gid}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${authUser.session_token}` },
    }).then(fetchGames).catch(() => {});
  }, [authUser, fetchGames]);

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
    const match = /\/orbit\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    if (match) {
      const rid = match[1].toUpperCase(); urlAttempt.current = rid; resumeGame(rid);
    }
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

  useEffect(() => {
    if (!me?.hand?.some((card) => card.id === selectedCard)) setSelectedCard(null);
  }, [me?.hand, selectedCard]);
  useEffect(() => { if (game?.phase !== "mulligan") setMulligan([]); }, [game?.phase]);
  const forcedChoice = useRef(null);
  useEffect(() => {
    if (!connected || !game?.pending || game.pending_pid !== myId || legal.length !== 1 || legal[0].action !== "choose") {
      forcedChoice.current = null;
      return;
    }
    const key = orbitMoveKey({ roomId, turn: game.turn_number, pending: game.pending, move: legal[0], log: game.log?.slice(-2) });
    if (forcedChoice.current === key) return;
    forcedChoice.current = key;
    sendMove(legal[0]);
  }, [game, connected, myId, roomId, sendMove]);


  if (connecting && screen === "lobby") return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style><LobbyLoading label="Connecting…" /></div>;
  if (screen === "lobby") return <Lobby {...{
    authUser, myId, onExit, openGames, myGames, history, historyShown, historyMore,
    refreshing, fetchGames, joinGame, resumeGame, cancelGame, showCreate, setShowCreate,
    createOpp, setCreateOpp, createSetup, setCreateSetup, createDifficulty, setCreateDifficulty,
    createGame, lobbyTab, setLobbyTab,
    showRules, setShowRules, toast,
  }} />;

  if (screen === "waiting") {
    const host = roomData?.host === myId;
    return <div className="app orbit" style={{ "--lby-accent": GAME_ACCENTS.orbit }}><style>{styles}</style>
      <div className="or-wait"><span className="or-kicker">Orbit · 1 vs 1</span><h1>Room {roomId}</h1>
        <p>{Object.keys(names).length < 2 ? "Waiting for an opponent…" : "Both players are here."}</p>
        <div className="or-wait-seats">{Object.values(names).map((name) => <span key={name}>{name}</span>)}</div>
        {host && Object.keys(names).length >= 2 && <button type="button" className="or-primary" onClick={() => send({ action: "start" })}>Start game</button>}
        <LobbyAction kind="secondary" onClick={leaveToLobby}>Back to lobby</LobbyAction>
      </div>{toast && <div className="or-toast">{toast}</div>}
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
  const myHint = over ? null
    : game.phase === "mulligan" && isMyTurn ? "Choose replacements"
      : game.pending_pid === myId ? (legal.length > 1 ? "Your turn" : "Resolving…")
        : isMyTurn ? "Choose an Agent" : null;
  const playerRails = (
      <div className="or-score-rail">
        <PlayerRail player={{ ...other, __pid: otherId }} name={names[otherId]} active={!over && (game.pending_pid || game.turn_pid) === otherId}
          leader={game.leader} connected={connected} onInfo={setInfo} />
        <PlayerRail player={{ ...me, __pid: myId }} name={names[myId]} active={!over && (game.pending_pid || game.turn_pid) === myId}
          me leader={game.leader} connected={connected} hint={myHint} onInfo={setInfo} />
      </div>
  );
  return <div className="app orbit or-game" style={{ "--lby-accent": GAME_ACCENTS.orbit }}>
    <style>{styles}</style>
    <LobbyHeader title="Orbit" user={<span className={`or-connection${connected ? "" : " lost"}`}>{connected ? (authUser?.name || "Connected") : "Reconnecting…"}</span>}
      menu={<GameMenu onLeave={leaveToLobby} onRules={() => setShowRules(true)}
        onAbandon={over ? null : () => setConfirmAbandon(true)} />} />
    <main className={`or-table${connected ? "" : " motion-paused"}`} ref={motionSurface}>
      {game.phase === "mulligan" && playerRails}

      {over && <section className="or-result">
        <h1>{winnerName ? `${winnerName} wins${victoryCondition(game) ? ` by ${victoryCondition(game)}` : ""}` : "The Agent supply was exhausted"}</h1>
        <button type="button" onClick={leaveToLobby}>Return to lobby</button>
      </section>}

      {game.phase === "mulligan" && isMyTurn && <section className="or-mulligan">
        <span className="or-eyebrow">Opening hand</span><h2>Replace any Agents?</h2>
        <p>Select any cards you want to discard, then confirm. You draw back to four.</p>
        <div className="or-hand">{me.hand.map((card) => <AgentCard card={card} key={card.id} selected={mulligan.includes(card.id)} onInfo={setInfo}
          onClick={() => setMulligan((old) => old.includes(card.id) ? old.filter((id) => id !== card.id) : [...old, card.id])} />)}</div>
        <button type="button" className="or-primary" onClick={() => sendMove({ action: "mulligan", card_ids: [...mulligan].sort((a, b) => a - b) })}>
          {mulligan.length ? `Replace ${mulligan.length} card${mulligan.length === 1 ? "" : "s"}` : "Keep this hand"}
        </button>
      </section>}
      {game.phase === "mulligan" && !isMyTurn && <section className="or-status"><span className="or-spinner" /> Waiting for the other mulligan…</section>}

      {game.phase !== "mulligan" && <div className="or-board-layout">
        <div className="or-board-main">
          {playerRails}
          <InfluenceBoard key={`${roomId}-${connected}`} game={game} myId={myId} catalog={catalog} names={names} connected={connected} onInfo={setInfo} />
          <Columns game={game} pid={otherId} name={names[otherId]} onInfo={setInfo} />
          <Columns game={game} pid={myId} name={names[myId]} mine onInfo={setInfo} />
          {!over && game.pending && game.pending_pid === myId && <DecisionPanel game={game} catalog={catalog} sendMove={sendMove} onInfo={setInfo} />}
          {!over && game.pending && game.pending_pid !== myId && <section className="or-status"><span className="or-spinner" /> {names[game.pending_pid] || "Opponent"} is resolving {game.pending.source}…</section>}
          {!over && !game.pending && !isMyTurn && <section className="or-status"><span className="or-spinner" /> {names[game.turn_pid] || "Opponent"} is choosing an action…</section>}

          <section className="or-hand-zone">
            <div className="or-hand-head"><span className="or-eyebrow">Your hand</span>
              <HandCount held={me.hand.length} limit={handLimit(game.leader, myId)} /></div>
            <Hand>{me.hand.map((card) => <AgentCard card={card} key={card.id} selected={selectedCard === card.id} onInfo={setInfo}
              onClick={isMyTurn && !game.pending ? () => setSelectedCard(card.id) : null} />)}</Hand>
            {selectedCard != null && isMyTurn && !game.pending && <div className="or-action-bar">
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
