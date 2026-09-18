/* SecretNames — the two-player cooperative word game (Codenames: Duet).
 *
 * The server is authoritative for everything that matters here, and in this
 * game that is not a slogan: the client is never told the partner's key card,
 * so it CANNOT resolve a guess even if it wanted to. It sends `{type:"guess",
 * pos}` and renders what comes back. Nothing in this file has, or asks for,
 * both key sides until the game is over and the server sends the reveal.
 *
 * The one piece of private state the client does hold is `game.key` — the
 * viewer's OWN side — which is what the board's spines and corner marks are
 * drawn from. It arrives per-socket from `engine.player_view`.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbyHero, LobbyCreateRow, LobbyUser, LobbySectionHd,
  LobbyEmpty, LobbyAction, LobbyTabs, LobbyMatchup, CreateModal, CmRow, CmSeg,
  RulesModal, GameMenu, rulesModalCss, createModalCss, lobbyCreateRowCss, gameMenuCss,
  useProgressiveList, useListFade, notWaiting, timeAgo,
  readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame,
  WaitingRoom, waitingRoomCss, seatStateOf, LobbyOpenActions,
} from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";
import { buildPath, pushPath } from "../../shared/router.js";
import SecretNamesRules from "./rules.jsx";
import cssText from "./SecretNames.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const HTTP_BASE = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "");
const styles = baseCss + lobbyCss + createModalCss + lobbyCreateRowCss + rulesModalCss
  + gameMenuCss + waitingRoomCss + cssText;

const ACCENT = { "--lby-accent": GAME_ACCENTS.secretnames };
const TOKEN_PREFIX = "secretnames_token_";
const TURN_OPTIONS = [9, 10, 11];
const CLUE_NUMBER_MAX = 9;

function roomCode() {
  return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
}

// The character count the card's type scale divides by — see `.sn-word` in the
// stylesheet for where its constant was measured.
function longestToken(word) {
  return Math.max(...String(word).split(" ").map((part) => part.length));
}

function deepRoom() {
  try {
    const m = /\/secretnames\/([A-Za-z0-9_-]{1,24})\/?$/.exec(window.location.pathname);
    return m ? m[1].toUpperCase() : null;
  } catch { return null; }
}

// The agent glyph on a contacted card — the same 24x24 grid, 1.5 stroke and
// round joins as the site's emblems, so a covered card reads as part of the set
// rather than as a checkmark borrowed from a form.
const AGENT_GLYPH = (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
    strokeLinejoin="round" strokeLinecap="round" aria-hidden="true" focusable="false">
    <path d="M12 3.6 19.2 6.6v5.5c0 4-3 7.1-7.2 8.3-4.2-1.2-7.2-4.3-7.2-8.3V6.6Z" />
    <path d="M8.8 12.1 11 14.4l4.2-4.6" />
  </svg>
);

/* ── The board ─────────────────────────────────────────────────────────────
 * One card per position. Everything it paints comes from the server view:
 *   • `key[i]`        your OWN side — the spine and the corner mark
 *   • `found`         covered agents, flipped, for both players
 *   • `bystanders[s]` who has already burnt a turn on this word
 *   • `reveal`        both sides, and only after the game is over
 */
function Board({ game, mySeat, canPick, onPick }) {
  const found = useMemo(() => new Set(game.found || []), [game.found]);
  const otherSeat = mySeat == null ? null : 1 - mySeat;
  const mine = useMemo(() => new Set(game.bystanders?.[mySeat] || []), [game.bystanders, mySeat]);
  const theirs = useMemo(() => new Set(game.bystanders?.[otherSeat] || []), [game.bystanders, otherSeat]);
  const key = game.key || [];
  const reveal = game.reveal;
  return (
    <div className="sn-boardwrap">
      <div className="sn-board" role="grid" aria-label="Codeword grid">
        {(game.words || []).map((word, i) => {
          const isFound = found.has(i);
          const role = key[i];
          const pickable = canPick && !isFound;
          const classes = ["sn-card"];
          if (isFound) classes.push("sn-found");
          if (mine.has(i) && !isFound) classes.push("sn-bys-you");
          if (pickable) classes.push("sn-pickable");
          if (game.fatal_pos === i) classes.push("sn-fatal");
          const note = isFound ? "agent, found"
            : mine.has(i) ? "you have already found a bystander here"
              : role === "agent" ? "an agent on your key"
                : role === "assassin" ? "an assassin on your key" : "";
          return (
            // `data-key` is YOUR side of the card and is what the spine, the
            // corner mark and the whole front-face tint are drawn from. It is
            // dropped once a card is found — the flipped face is the same for
            // both players, and leaving the attribute on would keep painting a
            // key colour behind a card that no longer has a role to play.
            <button key={word + i} type="button" className={classes.join(" ")}
              data-key={isFound ? undefined : role} disabled={!pickable}
              // `--len` is the LONGEST TOKEN, not the string length: "ICE CREAM"
              // breaks at its space for free, and sizing it as a nine-letter
              // word would shrink it for a line it was never going to need.
              style={{ "--i": i, "--len": longestToken(word) }}
              aria-label={`${word}${note ? ` — ${note}` : ""}`}
              onClick={() => pickable && onPick(i)}>
              <span className="sn-flip">
                <span className="sn-face sn-face-front">
                  {!isFound && role && <span className="sn-spine" aria-hidden="true" />}
                  {!isFound && role === "agent" && <span className="sn-keymark" aria-hidden="true">AGENT</span>}
                  {!isFound && role === "assassin" && <span className="sn-keymark" aria-hidden="true">✖</span>}
                  {/* `lang` is on the word, not on the document: `hyphens: auto`
                      resolves against the ELEMENT's language, and the site's
                      <html> carries none — which is why a ten-letter word on a
                      phone card broke as REVOLUTI/ON rather than REVO-/LUTION.
                      Scoped here so one game's card typography does not change
                      line breaking on eight other screens. */}
                  <span className="sn-word" lang="en">{word}</span>
                  {!isFound && (mine.has(i) || theirs.has(i)) && (
                    <span className="sn-bys-dots" aria-hidden="true">
                      {mine.has(i) && <span className="sn-bys-dot" title="you hit a bystander here" />}
                      {theirs.has(i) && <span className="sn-bys-dot sn-theirs" title="your partner hit a bystander here" />}
                    </span>
                  )}
                  {reveal && <>
                    <span className="sn-reveal-a" data-r={reveal[0][i]} aria-hidden="true" />
                    <span className="sn-reveal-b" data-r={reveal[1][i]} aria-hidden="true" />
                  </>}
                </span>
                <span className="sn-face sn-face-back">
                  <span className="sn-agent-mark">{AGENT_GLYPH}</span>
                  <span className="sn-word" lang="en">{word}</span>
                </span>
              </span>
            </button>
          );
        })}
      </div>
    </div>
  );
}

/* ── The console ───────────────────────────────────────────────────────────
 * ONE component for every phase, because the phases are the same control strip
 * wearing different contents, and splitting them produced a layout that jumped
 * by 20-40px every time the turn changed. What it shows is decided entirely by
 * the server's `phase` / `clue_giver` / `guesses_this_turn`, never by a local
 * guess at whose turn it is — a stale client then renders a disabled console
 * rather than a control that silently does nothing.
 */
function Console({ game, mySeat, onClue, onPass, onEndTurn, error }) {
  const [word, setWord] = useState("");
  const [number, setNumber] = useState(1);
  const phase = game.phase;
  const iClue = mySeat != null && mySeat === game.clue_giver;
  const iGuess = mySeat != null && mySeat === game.guesser;
  const partner = game.names?.[game.seats?.[mySeat == null ? 0 : 1 - mySeat]] || "Your partner";
  const sudden = phase === "sudden_death";

  const submit = () => {
    const w = word.trim();
    if (!w) return;
    onClue(w, number);
    setWord(""); setNumber(1);
  };

  if (phase === "won" || phase === "lost") return null;

  return (
    <div className={`sn-console${sudden ? " sn-sudden" : ""}`}>
      {sudden && (
        <div className="sn-console-lead">
          <span className="sn-console-k">Sudden death</span>
          <span className="sn-console-v">No more clues. Either of you may contact one
            word at a time — every one of them has to be an agent.</span>
        </div>
      )}
      {!sudden && phase === "clue" && iClue && <>
        <div className="sn-console-lead">
          <span className="sn-console-k">Your clue</span>
          <span className="sn-console-v">One word, and how many of {partner}'s guesses it is worth.</span>
        </div>
        <div className="sn-form">
          <input className="sn-input" value={word} maxLength={24} placeholder="CLUE"
            aria-label="Clue word" onChange={(e) => setWord(e.target.value)}
            onKeyDown={(e) => { if (e.key === "Enter") submit(); }} />
          <div className="sn-stepper">
            <button type="button" className="sn-step" aria-label="Fewer" disabled={number <= 0}
              onClick={() => setNumber((n) => Math.max(0, n - 1))}>−</button>
            <span className="sn-step-val" aria-live="polite">{number}</span>
            <button type="button" className="sn-step" aria-label="More" disabled={number >= CLUE_NUMBER_MAX}
              onClick={() => setNumber((n) => Math.min(CLUE_NUMBER_MAX, n + 1))}>+</button>
          </div>
          <button type="button" className="sn-btn sn-btn-go" disabled={!word.trim()} onClick={submit}>Send clue</button>
          <button type="button" className="sn-btn sn-btn-quiet" onClick={onPass}
            title="Give up clue-giving for the rest of the game">Pass for good</button>
        </div>
      </>}
      {!sudden && phase === "clue" && !iClue && (
        <div className="sn-console-lead">
          <span className="sn-console-k">Waiting</span>
          <span className="sn-console-v">{partner} is choosing a clue.</span>
        </div>
      )}
      {!sudden && phase === "guess" && game.clue && (
        <div className="sn-console-lead">
          <span className="sn-console-k">{iGuess ? "Your clue to work from" : "You gave"}</span>
          <div className="sn-clue" key={`${game.clues.length}:${game.clue.word}`}>
            <span className="sn-clue-word">{game.clue.word}</span>
            <span className="sn-clue-num">{game.clue.number}</span>
          </div>
        </div>
      )}
      {!sudden && phase === "guess" && iGuess && (
        <div className="sn-form" style={{ flex: "0 1 auto" }}>
          <button type="button" className="sn-btn" disabled={(game.guesses_this_turn || 0) < 1}
            onClick={onEndTurn}
            title={(game.guesses_this_turn || 0) < 1 ? "Make at least one guess first" : "Stop here and spend the turn"}>
            End turn
          </button>
        </div>
      )}
      {!sudden && phase === "guess" && !iGuess && (
        <div className="sn-console-lead">
          <span className="sn-console-k">Say nothing</span>
          <span className="sn-console-v">{partner} is guessing. No hints, no reactions.</span>
        </div>
      )}
      {error && <div className="sn-err" role="alert">{error}</div>}
    </div>
  );
}

function MissionStrip({ game, mySeat }) {
  const max = game.turns_max || 9;
  const left = Math.max(0, game.turns_remaining || 0);
  const found = (game.found || []).length;
  const total = game.agents_total || 15;
  const seats = game.seats || [];
  return (
    <div className="sn-strip">
      <div className="sn-metric">
        <span className="sn-metric-k">Timer tokens</span>
        <span className="sn-tokens" role="img" aria-label={`${left} of ${max} turns left`}>
          {Array.from({ length: max }, (_, i) => (
            <span key={i} className={`sn-token${i >= left ? " sn-spent" : ""}${left === 1 && i === 0 ? " sn-last" : ""}`} />
          ))}
        </span>
      </div>
      <div className="sn-metric" style={{ flex: "1 1 160px" }}>
        <span className="sn-metric-k">Agents contacted</span>
        <span className="sn-metric-v"><b>{found}</b> / {total}</span>
        <span className="sn-progress"><i style={{ width: `${(found / total) * 100}%` }} /></span>
      </div>
      {mySeat != null && (
        <div className="sn-metric">
          <span className="sn-metric-k">Still on your key</span>
          <span className="sn-metric-v"><b>{game.your_agents_left ?? 0}</b> to clue</span>
        </div>
      )}
      <div className="sn-roles">
        {seats.map((pid, seat) => {
          const acting = game.phase === "clue" ? seat === game.clue_giver
            : game.phase === "guess" ? seat === game.guesser : false;
          const job = game.phase === "sudden_death" ? "Either may guess"
            : game.passed?.[seat] ? "Passed"
              : game.exhausted?.[seat] ? "Side complete"
                : seat === game.clue_giver ? "Clue-giver" : "Guessing";
          return (
            <div key={pid} className={`sn-role${acting ? " sn-acting" : ""}${game.exhausted?.[seat] ? " sn-done" : ""}`}>
              <span className="sn-role-name">{game.names?.[pid] || "Player"}{seat === mySeat ? " (you)" : ""}</span>
              <span className="sn-role-job">{job}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}

const LOSS_TEXT = {
  assassin: "An assassin was contacted. Nothing else in the grid mattered after that.",
  sudden_death_mistake: "Sudden death allows no mistakes — that word was not an agent.",
  abandoned: "A player left the mission.",
};

function Result({ game, onExit, onAgain }) {
  const won = game.phase === "won";
  const found = (game.found || []).length;
  const used = (game.turns_max || 9) - Math.max(0, game.turns_remaining || 0);
  return (
    <div className={`sn-result ${won ? "sn-won" : "sn-lost"}`} role="status">
      <h2>{won ? "All 15 agents contacted" : "Mission lost"}</h2>
      <p>{won
        ? `You found every agent with ${Math.max(0, game.turns_remaining || 0)} token${game.turns_remaining === 1 ? "" : "s"} to spare.`
        : `${LOSS_TEXT[game.loss_reason] || "The mission ended."} ${found} of 15 agents found in ${used} turn${used === 1 ? "" : "s"}.`}
        {" Both key cards are now on the board — the top-left wedge is the first seat's side, the bottom-right the second's."}</p>
      <div className="sn-result-actions">
        <button type="button" className="sn-btn sn-btn-go" onClick={onAgain}>New mission</button>
        <button type="button" className="sn-btn" onClick={onExit}>Back to lobby</button>
      </div>
    </div>
  );
}

function Rail({ game }) {
  const clues = [...(game.clues || [])].reverse();
  const log = [...(game.log || [])].reverse().slice(0, 60);
  return (
    <div className="sn-rail">
      <div className="sn-panel sn-clues">
        <div className="sn-panel-hd"><span>Clues given</span><span>{(game.clues || []).length}</span></div>
        <div className="sn-panel-body">
          {!clues.length && <span className="sn-log-line">No clues yet.</span>}
          {clues.map((c, i) => (
            <div className="sn-clue-row" key={`${i}-${c.word}`}>
              <b>{c.word}</b><span className="sn-n">{c.number}</span>
              <small>{game.names?.[game.seats?.[c.seat]] || "Player"}</small>
            </div>
          ))}
        </div>
      </div>
      <div className="sn-panel">
        <div className="sn-panel-hd"><span>Your key</span></div>
        <div className="sn-panel-body">
          <div className="sn-legend">
            <span><i className="sn-l-agent" />Agent — get your partner to say it</span>
            <span><i className="sn-l-bystander" />Bystander you have hit</span>
            <span><i className="sn-l-assassin" />Assassin — keep them away</span>
          </div>
        </div>
      </div>
      <div className="sn-panel sn-log">
        <div className="sn-panel-hd"><span>Mission log</span></div>
        <div className="sn-panel-body">
          {log.map((e, i) => <span className="sn-log-line" data-k={e.k} key={i}>{e.t}</span>)}
        </div>
      </div>
    </div>
  );
}

function Lobby({ myId, authUser, openGames, activeGames, history, onRefresh, refreshing,
  onCreate, onJoin, onCancel, onExit, onRules }) {
  const active = notWaiting(activeGames);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [visibleHistory, historySentinel] = useProgressiveList(history);
  useListFade();
  return <div className="app secretnames" style={ACCENT}>
    <style>{styles}</style>
    <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
    <div className="lby-page"><div className="lby-page-in">
      <LobbyHero game="secretnames">
        <LobbyCreateRow onCreate={onCreate} onJoin={onJoin} onRefresh={onRefresh}
          refreshing={refreshing} onRules={onRules} />
      </LobbyHero>
      <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
        { key: "open", label: "Open", count: openGames.length || null },
        { key: "active", label: "Active", count: active.length || null },
        { key: "history", label: "History", count: history.length || null },
      ]} />
      {/* ABOVE the column grid, never inside it: the phone tab bar shows and
          hides columns by their own class names, so a fourth child of that grid
          could be neither shown nor hidden. */}
      <div className={`lby-cols tab-${lobbyTab}`}>
        <section className="lby-col-open">
          <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
          {!openGames.length && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
          <div className="lby-list">{openGames.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info">
              <div className="lby-card-title">{g.player1_name || "Player"} is waiting</div>
              <div className="lby-card-meta">{g.id} · {g.turns} turns · {timeAgo(g.updated_at)}</div>
            </div>
            {/* FOUR ANSWERS, NOT TWO. This row used to ask only "do I host it?",
                so a partner who joined by link and then went back to the lobby
                was offered Join on a seat they already held — which the server
                correctly refuses as a takeover, leaving the one row that could
                have carried them back as the one row that could not. */}
            <div className="lby-card-actions">
              <LobbyOpenActions state={seatStateOf(g, myId)}
                onReturn={() => onJoin(g.id)} onJoin={() => onJoin(g.id)}
                onCancel={() => onCancel(g.id)} />
            </div>
          </div>)}</div>
        </section>
        <section className="lby-col-active">
          <LobbySectionHd title="Active Games" note={`${active.length} in progress`} />
          {!active.length && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          <div className="lby-list">{active.map((g) => <div className="lby-card" key={g.id}>
            <div className="lby-card-info">
              <LobbyMatchup placeholder="Partner" seats={[
                { name: g.player1_name, you: g.you_are_host },
                { name: g.player2_name, you: !g.you_are_host },
              ]} />
              <div className="lby-card-meta">{g.found ?? 0}/15 agents · {g.turns_remaining ?? g.turns} tokens left</div>
            </div>
            <div className="lby-card-actions"><LobbyAction onClick={() => onJoin(g.id)}>Resume</LobbyAction></div>
          </div>)}</div>
        </section>
        <section className="lby-col-history">
          <LobbySectionHd title="History" note={`${history.length} finished`} />
          {!history.length && <LobbyEmpty>{authUser && !authUser.guest
            ? "Finished missions will appear here."
            : "Log in to keep a record of your missions."}</LobbyEmpty>}
          <div className="lby-list">{visibleHistory.map((g) => <div className="lby-card lby-card-hist" key={g.id}>
            <div className="lby-card-info">
              <div className="lby-card-title">
                <span className={`sn-tag ${g.outcome === "won" ? "sn-tag-won" : "sn-tag-lost"}`}>
                  {g.outcome === "won" ? "Won" : "Lost"}
                </span>
                {" "}{g.player1_name || "Player"} &amp; {g.player2_name || "partner"}
              </div>
              <div className="lby-card-meta">
                {g.found}/15 agents · {g.turns_used}/{g.turns_max} turns
                {g.loss_reason === "assassin" ? " · assassin" : ""}
                {g.loss_reason === "sudden_death_mistake" ? " · sudden death" : ""}
                {" · "}{timeAgo(g.updated_at)}
              </div>
            </div>
          </div>)}{historySentinel}</div>
        </section>
      </div>
    </div></div>
  </div>;
}

export default function SecretNames({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState(() => deepRoom() ? "game" : "lobby");
  const [roomId, setRoomId] = useState(() => deepRoom() || "");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState(() => readLobbyCache("secretnames", myId, "open", []));
  const [activeGames, setActiveGames] = useState(() => readLobbyCache("secretnames", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("secretnames", myId, "history", []));
  const [refreshing, setRefreshing] = useState(false);
  const [connected, setConnected] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [turns, setTurns] = useState(9);
  const [toast, setToast] = useState("");
  const [error, setError] = useState("");
  const wsRef = useRef(null);
  const roomRef = useRef(roomId);
  const tokenRef = useRef("");
  const intentRef = useRef("join");
  const createPayloadRef = useRef(null);
  roomRef.current = roomId;

  const refresh = useCallback(async () => {
    setRefreshing(true);
    try {
      const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
      const [open, mine, old] = await Promise.all([
        fetch(`${HTTP_BASE}/secretnames/games`).then((r) => r.ok ? r.json() : { games: [] }).catch(() => ({ games: [] })),
        // `player_id` is what lets a GUEST see their own Active column, and in a
        // game invited by link that is most of the table: a partner who joins as
        // a guest, backs out to the lobby to wait, and then has the host deal
        // would otherwise have no row anywhere — Active is the only list a
        // started game lands in. A real session always wins over it server-side
        // (`core.rooms.lobby_viewer_id`), so it is safe to send unconditionally.
        fetch(`${HTTP_BASE}/secretnames/games/mine?player_id=${encodeURIComponent(myId)}`, { headers })
          .then((r) => r.ok ? r.json() : { games: [] }).catch(() => ({ games: [] })),
        fetch(`${HTTP_BASE}/secretnames/games/history`, { headers }).then((r) => r.ok ? r.json() : { games: [] }).catch(() => ({ games: [] })),
      ]);
      setOpenGames(open.games || []); writeLobbyCache("secretnames", myId, "open", open.games || []);
      setActiveGames(mine.games || []); writeLobbyCache("secretnames", myId, "mine", mine.games || []);
      setHistory(old.games || []); writeLobbyCache("secretnames", myId, "history", old.games || []);
    } catch { setToast("Could not reach headquarters."); }
    finally { setRefreshing(false); }
  }, [authUser, myId]);
  useEffect(() => { if (screen === "lobby") refresh(); }, [screen, refresh]);

  // A finished mission leaves Active and joins History at the moment it ends,
  // while the player is still reading the result — see the shared kit.
  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("secretnames", myId, "mine", rid, setActiveGames);
    refresh();
  });

  // A ref rather than a dep so `onMessage` stays stable across every room update
  // (it is wired into the socket exactly once per connection).
  const roomDataHasGame = useRef(false);
  roomDataHasGame.current = !!roomData?.game;

  const onMessage = useCallback((message) => {
    if (message.room) {
      intentRef.current = "reconnect";
      setRoomData(message.room);
      setScreen("game");
      const token = message.room.reconnect_tokens?.[myId];
      if (token && roomRef.current) {
        tokenRef.current = token;
        try { localStorage.setItem(`${TOKEN_PREFIX}${roomRef.current}`, token); } catch {}
      }
    }
    if (message.type === "error") {
      // A rejected MOVE belongs beside the control that made it; a rejected
      // handshake is the whole screen's problem. Two channels, because a clue
      // bounced for being a board word must not look like a lost connection.
      if (roomRef.current && roomDataHasGame.current) setError(message.message || "Not allowed.");
      else setToast(message.message || "Headquarters refused that.");
    } else {
      setError(""); setToast("");
    }
  }, [myId]);

  const connect = useCallback(() => {
    const rid = roomRef.current;
    if (!rid) return;
    try { wsRef.current?.close(); } catch {}
    const ws = new WebSocket(`${WS_BASE}/secretnames/ws/${encodeURIComponent(rid)}/${encodeURIComponent(myId)}`);
    wsRef.current = ws;
    ws.onopen = () => {
      if (wsRef.current !== ws) return;
      setConnected(true);
      const token = tokenRef.current || (() => {
        try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; }
      })();
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
  const send = useCallback((payload) => {
    try { if (wsRef.current?.readyState === 1) wsRef.current.send(JSON.stringify(payload)); } catch {}
  }, []);
  useAutoReconnect({ enabled: !!roomId && screen === "game", connected, connect, socketReady });

  useEffect(() => {
    const rid = deepRoom();
    if (!rid) return () => { try { wsRef.current?.close(); } catch {} };
    intentRef.current = "reconnect";
    tokenRef.current = (() => { try { return localStorage.getItem(`${TOKEN_PREFIX}${rid}`) || ""; } catch { return ""; } })();
    connect();
    return () => { try { wsRef.current?.close(); } catch {} };
  // Deep links are handled once; later room transitions go through openRoom.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(""), 3200);
    return () => clearTimeout(t);
  }, [toast]);

  const openRoom = useCallback((rid, intent, createPayload) => {
    const id = rid.toUpperCase();
    setRoomData(null); setToast(""); setError(""); setConnected(false);
    setRoomId(id); roomRef.current = id; intentRef.current = intent; tokenRef.current = "";
    createPayloadRef.current = createPayload || null; setScreen("game");
    try { pushPath(buildPath("secretnames", id)); } catch {}
    connect();
  }, [connect]);

  const createGame = useCallback(() => {
    setShowCreate(false);
    openRoom(roomCode(), "create", { name: authUser?.name || "Player", turns });
  }, [authUser, openRoom, turns]);
  const joinRoom = useCallback((rid) => { openRoom(rid, "join"); }, [openRoom]);
  const cancelGame = useCallback(async (gameId) => {
    try {
      const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
      await fetch(`${HTTP_BASE}/secretnames/games/${gameId}`, { method: "DELETE", headers });
    } catch { /* the refresh below reports the real state either way */ }
    refresh();
  }, [authUser, refresh]);

  const exit = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null;
    setConnected(false); setRoomData(null); setRoomId(""); setScreen("lobby"); setError("");
    try { pushPath(buildPath("secretnames")); } catch {}
    refresh();
  }, [refresh]);

  const move = useCallback((m) => { setError(""); send({ action: "move", move: m }); }, [send]);
  const abandon = useCallback(() => send({ action: "abandon" }), [send]);

  const game = roomData?.game;
  const mySeat = game?.you ?? null;
  const canPick = !!game && mySeat != null && (
    game.phase === "sudden_death" || (game.phase === "guess" && mySeat === game.guesser));
  const over = game?.phase === "won" || game?.phase === "lost";
  const waiting = screen === "game" && roomData && !game;

  return <>
    {screen === "lobby" && <Lobby {...{
      myId, authUser, openGames, activeGames, history, onRefresh: refresh, refreshing,
      onCreate: () => setShowCreate(true), onJoin: joinRoom, onCancel: cancelGame,
      onExit, onRules: () => setShowRules(true),
    }} />}

    {screen === "game" && !roomData && <div className="app secretnames" style={ACCENT}>
      <style>{styles}</style>
      <LobbyHeader title="SecretNames" onBack={exit} />
      <div className="sn-waiting">
        <h1>{toast ? "That table is not available." : "Opening a secure line…"}</h1>
        <p role="status">{toast || "Connecting to the table. A cold server can take up to a minute."}</p>
        <button type="button" className="sn-btn" onClick={exit}>Back to lobby</button>
      </div>
    </div>}

    {/* `WaitingRoom` in shared/lobby.jsx. What this screen used to be was a
        hand-built panel with a room CODE on it — six letters plus instructions
        for where to type them, which is the thing the kit replaced with a link
        across all nine games. The only word SecretNames keeps is its own for
        the act: "Deal the board" rather than the shared "Start Game". */}
    {waiting && <div className="app secretnames" style={ACCENT}>
      <style>{styles}</style>
      <WaitingRoom
        game="secretnames" roomId={roomData.room_id}
        players={roomData.players} hostId={roomData.host} myId={myId}
        min={2} max={2} user={authUser} connected={connected}
        note="SecretNames is played by exactly two, on the same side. Send the link over — you will each get your own key card, and neither of you ever sees the other's."
        startLabel="Deal the board"
        onLeave={exit} onRules={() => setShowRules(true)}
        onStart={() => send({ action: "start" })} />
    </div>}

    {game && <div className="app secretnames sn-game" style={ACCENT}>
      <style>{styles}</style>
      <LobbyHeader title="SecretNames" user={<LobbyUser user={authUser} />}
        menu={<GameMenu onLeave={exit} onRules={() => setShowRules(true)}
          onAbandon={over ? null : abandon} />} />
      <div className="sn-game-shell">
        <div className="sn-main">
          {!connected && <div className="sn-console"><div className="sn-console-lead">
            <span className="sn-console-k">Reconnecting</span>
            <span className="sn-console-v">The line dropped. Retrying — nothing has been lost.</span>
          </div></div>}
          {over && <Result game={game} onExit={exit} onAgain={() => { exit(); setShowCreate(true); }} />}
          <MissionStrip game={game} mySeat={mySeat} />
          <Board game={game} mySeat={mySeat} canPick={canPick && connected}
            onPick={(pos) => move({ type: "guess", pos })} />
          <Console game={game} mySeat={mySeat} error={error}
            onClue={(word, number) => move({ type: "clue", word, number })}
            onPass={() => move({ type: "pass" })}
            onEndTurn={() => move({ type: "end_turn" })} />
        </div>
        <Rail game={game} />
      </div>
    </div>}

    {showCreate && <div className="secretnames sn-overlay-scope" style={ACCENT}>
      <CreateModal title="New SecretNames table" onClose={() => setShowCreate(false)}>
        <CmRow label="Timer tokens">
          {/* BARE NUMBERS, AND NO `wrap`. The row label already says what they
              are, and the standard-vs-easier distinction is a sentence, so it
              belongs in the summary rather than in three chips.
              Both of the alternatives were measured and rejected:
              "9 · standard" / "10 · easier" / "11 · easier" needs the kit's
              wrapping variant, which gives each chip a 10.5rem basis and stacked
              them into three full-width bars in a 330px panel; "9 turns" fits one
              row but measured 246px of chips in a 290px track at 360px wide —
              15% slack, and this control is `overflow:hidden` with `nowrap`
              chips, so anything past the fold is unreachable rather than merely
              clipped. Bare numbers measure 102px in that same track — 65% slack
              at 360px and 70% at desktop, which is clear of any font spread. */}
          <CmSeg value={turns} onChange={setTurns}
            options={TURN_OPTIONS.map((v) => ({
              value: v,
              label: String(v),
              title: v === 9 ? "The published game" : `${v} turns before sudden death`,
            }))} />
        </CmRow>
        <div className="cm-footer">
          <span className="cm-summary">You + one partner, 15 agents.
            {turns === 9 ? " 9 turns is the standard game." : ` ${turns} turns is the easier setting.`}</span>
          <button type="button" className="cm-create" onClick={createGame}>Open table</button>
        </div>
      </CreateModal>
    </div>}

    {showRules && <div className="secretnames sn-overlay-scope" style={ACCENT}>
      <RulesModal title="How to play — SecretNames" onClose={() => setShowRules(false)}>
        <SecretNamesRules />
      </RulesModal>
    </div>}

    {/* The connecting screen prints the same string in its own body, so the
        floating copy would be a duplicate there and nowhere else. */}
    {toast && !(screen === "game" && !roomData) && <div className="sn-toast" role="status">{toast}</div>}
  </>;
}
