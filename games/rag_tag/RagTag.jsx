import { fetchGameHistory } from "../../shared/lobbyHistory.js";
import { leaveOpenSeat, readRoomToken } from "../../shared/roomLifecycle.js";
import { useState, useEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import ragtagCssText from "./RagTag.css?inline";
import RagTagRules from "./rules.jsx";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyMatchup, LobbyLoading, LobbyEmpty,
  LobbyAction, LobbyTabs, notWaiting, GameMenu, gameMenuCss,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss, useProgressiveList, LobbyHero, LobbyUser, useListFade,
  readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame,
  LobbyOpenTitle, LobbyOpenActions, seatStateOf, WaitingRoom, waitingRoomCss,
} from "../../shared/lobby.jsx";
import { buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
import {
  Sigil, Icon, sigilOf, iconForOp, FX_TEXT, OP_GLOSSARY,
  TRACK_GLOSSARY, TOKEN_GLOSSARY, SPACE_GLOSSARY, TOKEN_WORD, TRACK_TITLE, TRACK_MARKS, trackWord, tokenWord,
  complexityWord,
} from "./art.jsx";
import { beatStateAt, beatSteps, narrateBeat, narrateRound } from "./narrate.jsx";
import { useCardInfoGesture } from "../../shared/gestures.js";
import { useAutoReconnect } from "../../shared/useAutoReconnect.js";

/* Rag Tag — a two-player auto battler.
 *
 * The one thing that shapes this whole file: the game is SIMULTANEOUS. There is
 * no "your turn". Both players submit secretly and the round resolves when both
 * are in, so every prompt here is "you owe a submission" and every wait is
 * "waiting for them", never "waiting for the board".
 *
 * The FIGHT! step is resolved server-side in one go and arrives as `beats` — one
 * entry per turn with both revealed cards and every delta. This component plays
 * them back with a dwell so the fight reads as a fight rather than a diff. The
 * beats live in GAME STATE, so a reconnect mid-animation re-ships them.
 *
 * Playback has TWO cursors, and they are paced differently on purpose. `beatIdx`
 * walks the TURNS and only ever moves on a click — a turn is a decision the
 * player made a round ago and it deserves to be read. `stepIdx` walks the
 * ACTIONS inside one turn and moves on a timer, because a card that attacks,
 * heals and burns is one decision and three things to watch: it used to land in
 * a single frame, four sentences at once with every bar, total and token jumping
 * to its end-of-turn value together, so the table showed the sum of the card
 * rather than the card.
 */

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const WS_BASE = WS_RAW.replace(/\/ws$/, "");
const RT_WS = `${WS_BASE}/ragtag/ws`;
const RT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/ragtag");

/* How long one action of a turn holds the stage, and how long the two cards sit
   there before the first of them lands. The reveal dwell is `rt-clash`'s own
   520ms, so the VS burst finishes before anything starts moving. */
const STEP_MS = 700;
const REVEAL_MS = 520;
/* "Show me the whole turn" — clamped against the step count wherever it is read,
   so it survives a beat whose length is not known yet. */
const STEP_DONE = 1e9;

/* baseCss FIRST, and it is not optional: the shared lobby kit is written
 * against the site theme tokens (--surface, --border, --radius, --text...).
 * Without it every `border: 1px solid var(--border)` in that kit is invalid at
 * computed-value time and silently resolves to `0px none` — the lobby still
 * lays out, so it looks like a design choice rather than a missing import.
 * Rag Tag shipped without it; the other five games all have it. */
const ragtagStyles =
  baseCss + lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss
  + rulesModalCss + waitingRoomCss + ragtagCssText;

/* There is deliberately NO dwell timer. The fight used to play itself at a
 * fixed 900ms a turn, which meant the one thing worth watching — what the two
 * cards did to each other — was gone before it could be read. Every turn now
 * waits for a click, and the log keeps what has already gone past. */

function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

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
    ws.onclose = () => { if (wsRef.current === ws) setConnected(false); };
    ws.onmessage = (e) => { try { onMsg.current(JSON.parse(e.data)); } catch {} };
  }, []);
  const send = useCallback((obj) => { try { wsRef.current?.send(JSON.stringify(obj)); } catch {} }, []);
  // The retry loop must not abort a socket that is already CONNECTING.
  const socketReady = useCallback(() => wsRef.current?.readyState ?? 3, []);
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; setConnected(false);
  }, []);
  return { connected, connect, send, disconnect, socketReady };
}

/* ── Rendering the mechanics ──────────────────────────────────────────────
 * Cards arrive from /catalog as op lists rather than printed text, because the
 * generated data is mechanics only — no publisher wording, no art. So the UI
 * says what a card DOES in its own vocabulary. That is also why the same op list
 * can drive the board, the log and the tooltip without three transcriptions.
 */

const TARGET_WORD = {
  self: "you", partner: "your partner", opp: "the opponent",
  opp_partner: "their partner", both_opps: "both opponents",
  all_others: "everyone else", all: "everyone",
};

function valueWord(n) {
  if (typeof n === "number") return String(n);
  if (!n) return "?";
  if (n.kind === "power") return "your Power";
  if (n.kind === "attacking_opponents_power") return "the blocked Power";
  if (n.kind === "spirits") return n.times > 1 ? `${n.times} per Spirit` : "1 per Spirit";
  return "?";
}

/* `after: true` is on four cards and was rendered by none of them: the op read
   as if it happened with everything else, when the whole point of the card is
   that it waits. Ching Shih's Terror of the Seas picks its branch on her Ships
   BEFORE the step, and Twin Serpents turns the serpent over only once the card
   that read it is done. */
function opWords(op) {
  if (!op) return "";
  const core = opCore(op);
  return op.after ? `${core} (after their card resolves)` : core;
}

function opCore(op) {
  switch (op.op) {
    case "attack": {
      const who = op.target && op.target !== "opp" ? ` ${TARGET_WORD[op.target]}` : "";
      const by = op.by === "partner" ? ", thrown by your partner" : "";
      // Two cards hit for more than your Power and said only "Attack".
      const more = op.flamepower ? " (+1 per Aflame! on the target)"
        : op.power_bonus ? ` (+${valueWord(op.power_bonus)})` : "";
      return `Attack${who}${by}${more}`;
    }
    case "block": return "Block";
    case "damage": return `${valueWord(op.n)} damage to ${TARGET_WORD[op.target || "opp"]}`;
    case "heal": return `Heal ${valueWord(op.n)} — ${TARGET_WORD[op.target || "self"]}`;
    case "power": {
      const n = valueWord(op.n);
      const sign = typeof op.n === "number" && op.n < 0 ? "" : "+";
      return `${sign}${n} Power — ${TARGET_WORD[op.target || "self"]}`;
    }
    case "transfer_power": {
      // `from` was dropped, so Thunder Stone — which takes a Power off your own
      // partner — read as if it conjured one.
      const src = op.from && op.from !== "self" ? ` from ${TARGET_WORD[op.from]}` : "";
      return `Move ${valueWord(op.n)} Power${src} to ${TARGET_WORD[op.to]}`;
    }
    case "cancel": return "Cancel their card";
    case "track": return `+${valueWord(op.n)} ${trackWord(op.track, op.n)}`;
    case "ignite": return "Set them Aflame";
    case "plant_scheme": return "Plant a Scheme";
    case "unleash_scheme": return "Unleash a Scheme";
    case "give_token": return `Pass the ${tokenWord(op.token)} to ${TARGET_WORD[op.to] || "them"}`;
    case "take_token": return `Take the ${tokenWord(op.token)} back`;
    case "flip_card": return "Turn this card over";
    case "spirit": return "+1 Spirit";
    // "A — else B" read as one branch with a dash in it. The two halves need a
    // separator that cannot be mistaken for punctuation inside either of them.
    case "if": return `If ${condWords(op.cond)}: ${op.then.map(opWords).join(", ")}`
      + (op.else ? ` · otherwise: ${op.else.map(opWords).join(", ")}` : "");
    case "fx": return FX_TEXT[op.name] || "Special";
    default: return op.op;
  }
}

function condWords(cond) {
  if (!cond) return "?";
  switch (cond.kind) {
    case "power_at_least": return `you have ${cond.n}+ Power`;
    case "hp_equals": return `you are on ${cond.n} HP`;
    case "no_opponent_attacked": return "neither opponent attacks";
    case "self_attacked": return "you are attacked";
    case "own_attack_blocked": return "your attack is blocked";
    case "opponent_played_starting_card": return "they played their Starting Card";
    case "serpent": return `the ${cond.face} serpent shows`;
    case "face": return cond.face === "bodvar" ? "still human" : "transformed";
    case "ships": return `${cond.min}–${cond.max} Ships`;
    case "has_token": return `you hold the ${tokenWord(cond.token)}`;
    case "token_on": return `${TARGET_WORD[cond.who]} holds the ${tokenWord(cond.token)}`;
    default: return cond.kind;
  }
}

function cardText(card) {
  if (!card) return "";
  const main = (card.ops || []).map(opWords).filter(Boolean);
  const bonus = [];
  for (const op of card.ops || []) {
    if (op.success) bonus.push(`Success: ${op.success.map(opWords).join(", ")}`);
  }
  return [...main, ...bonus].join(" · ");
}

/* ── Board pieces ───────────────────────────────────────────────────────
 * There is no licensed art in this repo, so a fighter's identity is drawn:
 * an emblem and an accent colour from art.jsx, applied as CSS custom
 * properties so the whole board tints from one place.
 */

function trackFor(state, board) {
  if (state.face === "berserker_bear" && board.back) return board.back.hp_track || [];
  if (board.characters) {
    const ch = board.characters.find((c) => c.id === state.character);
    return ch ? ch.hp_track : [];
  }
  return board.hp_track || [];
}

/* A round's beats include ones that are not TURNS: the instant-bonus beat at
   setup, and anything the engine records before the first card is flipped. They
   carry no revealed cards. Counting them made the stage read "Turn 1 of 1"
   before a single card had been played, over two empty card slots. */
function isTurnBeat(beat) {
  return !!beat && (beat.insts || []).some((x) => x != null);
}

/* ── Reading a board out loud ─────────────────────────────────────────────
 *
 * All of this used to be one function that returned sentences, and the
 * sentences were about the SHAPE of the data rather than about the game: "4
 * spaces carry an icon", "Has a divine voice track of 5 spaces", "Starts with 1
 * presence". A player who opens the Golem to find out what a Presence is and
 * reads that he starts with one has been told the field name and the count.
 *
 * So the split below. What a mechanic MEANS is written once, in art.jsx, keyed
 * by the same name the data uses. WHERE it is and HOW MUCH is derived here from
 * the track, so a corrected import moves the modal with it and the two cannot
 * disagree. Nothing is printed unless this board actually has it — the legend
 * used to name KO, stop, icon and revive on all twelve boards, nine of which
 * have no revive space and ten of which have no STOP.
 */

function spaceIcons(sp) {
  return (sp?.icons || []).filter((ic) => ic && typeof ic === "object");
}

function isStop(sp) {
  return (sp?.icons || []).some((ic) => ic === "stop" || ic?.op === "stop");
}

/* Where a space is, in the numbers printed on the board rather than an index
   into an array. Health tracks are stored bottom-up, so index 0 is the KO. */
function spaceWhere(sp) {
  if (!sp) return "";
  if (sp.kind === "hp") return `${sp.hp} health`;
  if (sp.kind === "ko") return "the KO space";
  if (sp.kind === "revive") return "the revive space";
  if (sp.kind === "spirit") return "the Spirit space";
  return String(sp.kind);
}

/* Which kinds of space this board actually uses, so the legend can name those
   and only those. `icon` is not a kind — it is any space that pays out. */
const KIND_ORDER = ["ko", "stop", "icon", "revive", "spirit"];

function trackKinds(tracks) {
  const kinds = new Set();
  for (const tr of tracks) {
    for (const sp of tr || []) {
      if (sp.kind !== "hp") kinds.add(sp.kind);
      if (isStop(sp)) kinds.add("stop");
      // Only a plain health space earns the "icon" entry. The revive and Spirit
      // spaces carry icons too, and naming both made Maman Brijit's key read
      // "revive, icon, ko" — three entries for two kinds of space.
      if (sp.kind === "hp" && spaceIcons(sp).length) kinds.add("icon");
    }
  }
  // Track order put Brijit's revive space first, because it is index 0. Read the
  // key in the order the rules meet them instead.
  return KIND_ORDER.filter((k) => kinds.has(k));
}

/* What the spaces on ONE track do, said WHERE they are — `{at, text}` so the
   place can be set in the accent colour beside the effect, the same shape the
   dial's read-out uses. This replaces "4 spaces carry an icon", which is the
   hardest possible way to describe a place. */
function trackNotes(track, character) {
  const out = [];
  const stops = (track || []).filter(isStop);
  if (stops.length === 1) {
    out.push({ at: spaceWhere(stops[0]), text: "STOP." });
  } else if (stops.length > 1) {
    const hp = stops.filter((sp) => sp.kind === "hp").map((sp) => sp.hp);
    out.push({
      at: `${Math.min(...hp)}–${Math.max(...hp)} health`,
      text: "STOP on every one of them, so the marker moves one space a turn and no"
        + " further, however much lands on it.",
    });
  }
  for (const sp of track || []) {
    const ops = spaceIcons(sp);
    if (!ops.length) continue;
    // The Fey Folk's icons are all on the space a Character COMES IN on, which
    // is the one fact that makes them make sense: the icon is a signing bonus,
    // not something you climb to.
    out.push({
      at: spaceWhere(sp),
      // Only a Character's top space pays as the marker is PLACED there
      // (`choose_character` fires it). On an ordinary board the start space is
      // just where you begin, and setup icons are a separate field entirely.
      text: ops.map(opWords).join(", ")
        + (character && sp.start ? " — the moment they step in" : ""),
    });
  }
  return out;
}

/* The non-obvious half of every mechanic ONE CARD uses.
 *
 * Without it a one-op card's modal printed the title, the fighter, and the same
 * effect line already on the face — a player who holds a card and learns nothing
 * stops holding cards.
 *
 * Keyed by more than the op name, because the op name is not always the thing
 * the reader does not know. "+1 Ship" is an `op: track`, and the generic line
 * ("a track advances a marker on this fighter's own board") is true of every
 * track in the game and says nothing about the Navigation one the card just
 * stepped. Where the op names a specific track or token, that entry is used
 * instead of / as well as the generic one.
 */
function cardGlossary(lists, note) {
  const out = [];
  const said = [];
  const add = (k, text) => {
    if (text && !out.some((g) => g.k === k)) out.push({ k, text });
  };
  const walk = (list) => {
    for (const op of list || []) {
      said.push(opWords(op));
      if (op.op) add(op.op, OP_GLOSSARY[op.op]);
      if (op.op === "track") add(`t:${op.track}`, TRACK_GLOSSARY[op.track]);
      if (op.op === "spirit") add("t:spirits", TRACK_GLOSSARY.spirits);
      if (op.token) add(`k:${op.token}`, TOKEN_GLOSSARY[op.token]);
      if (op.cond?.token) add(`k:${op.cond.token}`, TOKEN_GLOSSARY[op.cond.token]);
      if (op.cond?.kind === "ships") add("t:navigation", TRACK_GLOSSARY.navigation);
      walk(op.then); walk(op.else); walk(op.success);
    }
  };
  for (const list of lists) walk(list);
  // A card that NAMES a token in its own words gets that token explained, even
  // when it does so through an `fx` with no `token` field — which is most of
  // them. Corrupted Lawman's whole text is "The Sheriff changes sides", and its
  // only glossary line was "this one does not follow the usual pattern".
  const text = said.concat(note || "").join(" ");
  for (const [id, word] of Object.entries(TOKEN_WORD)) {
    const bare = word.replace(/[^A-Za-z]/g, "");
    if (bare && text.includes(bare)) add(`k:${id}`, TOKEN_GLOSSARY[id]);
  }
  return out;
}

/* The rules this board breaks, as opposed to the ones its track draws. Every
   one is read off a field, so a board that gains one gains the sentence. */
function boardFacts(board) {
  if (!board) return [];
  const out = [];
  const tr = board.hp_track || [];
  const kos = tr.filter((sp) => sp.kind === "ko").length;

  if (board.characters) {
    const names = board.characters.map((c) => c.name || c.id);
    const hps = board.characters.map((c) => maxOfTrack(c.hp_track));
    out.push(`${names.length} Characters, one on the board at a time — `
      + names.map((n, i) => `${n} (${hps[i]} health)`).join(", ")
      + ". Each has its own track, and its own icon on the space it starts on.");
    out.push("A Character pushed to their Spirit space becomes a Spirit at the end of that"
      + " turn, the Spirits track goes up, and only then do you pick which of the ones"
      + " left steps in — at full health, so damage never carries across.");
    if (!board.characters.some((c) => (c.hp_track || []).some((sp) => sp.kind === "ko"))) {
      out.push("There is no KO space anywhere on this board, so the Fey Folk cannot be"
        + " knocked out. They lose only if all three are already Spirits when All Legends"
        + " Must Pass is revealed.");
    }
  }
  if (board.back) {
    out.push(`Two-sided: this board turns over to ${board.back.name}, which fights on a`
      + " health track of its own.");
  }
  if (kos > 1) {
    out.push(`${kos} KO spaces in a row, so there is further to fall than the top number`
      + " suggests — and a marker only loses the fight once it is ON one at the end of a turn.");
  }
  if (board.revive_to_hp != null) {
    out.push(`Pushed all the way past the KO spaces, the marker lands on the revive space`
      + ` and comes straight back on ${board.revive_to_hp} health — the moment that movement`
      + " settles, not at the end of the turn, so anything still to land this turn lands on"
      + " the revived fighter.");
  }
  for (const op of board.setup_icons || []) {
    out.push(`Before the first card of the game: ${opWords(op)}.`);
  }
  return out;
}

function maxOfTrack(track) {
  let best = 0;
  for (const sp of track || []) if (sp.kind === "hp" && sp.hp > best) best = sp.hp;
  return best || null;
}

/* The health number on the modal's stat chip.
 *
 * It was the best track on the board, which is not what "how much can this
 * survive" means for either fighter that has more than one. It read 5 for the
 * Fey Folk, whose first Character has 3 and who never has more than one
 * Character on the board; and 15 for Bödvar, who fights on 11 until he turns
 * over. Both now show every track, in the order they are met, which lines up
 * one-to-one with the strips drawn below. */
function healthLabel(board) {
  if (!board) return "?";
  const tracks = board.characters
    ? board.characters.map((c) => c.hp_track)
    : [board.hp_track, board.back?.hp_track];
  const maxes = tracks.filter(Boolean).map(maxOfTrack).filter(Boolean);
  return maxes.length ? maxes.join(" / ") : "?";
}

/* The biggest number ANYWHERE on this fighter's boards. This is the bar-scale
   denominator and nothing else: it answers "how long should this fighter's bar
   be against the toughest in the game", which is a question about the widest
   track. It is NOT the fighter's health — for a board with more than one track
   that is `healthLabel`, and this used to be used for both. */
function maxHpOf(board) {
  if (!board) return null;
  const tracks = board.characters ? board.characters.map((c) => c.hp_track)
    : [board.hp_track, board.back && board.back.hp_track].filter(Boolean);
  let best = 0;
  for (const tr of tracks) {
    for (const sp of tr || []) if (sp.kind === "hp" && sp.hp > best) best = sp.hp;
  }
  return best || null;
}

function spaceValue(track, idx) {
  if (!track || idx == null || !track[idx]) return 0;
  return track[idx].kind === "hp" ? track[idx].hp : 0;
}

/* The health track.
 *
 * This was a row of one box per space, which is how the board is printed — and
 * it did not survive contact with the roster. Health ranges from 3 (a Fey Folk
 * Character) to 25 (the Golem), so the same component drew four fat slabs on one
 * board and twenty-five hairlines on the next, side by side in the same panel,
 * and the two could not be compared at a glance. Worse, colouring each space by
 * what it does made a FULL health bar render as a red-amber-green ramp, which
 * reads as a damaged bar or a rendering fault.
 *
 * So: one bar, filled in proportion, one colour chosen by how much health is
 * left, and its LENGTH scaled to how tough this fighter is against the toughest
 * in the game — otherwise a 5 HP fighter and a 25 HP fighter both draw a full
 * bar and relative durability, the thing a 2v2 brawler is read on, is invisible.
 *
 * The special spaces (KO, Stop, revive, Spirit) were drawn on it as notches and
 * that was WRONG, four review rounds running: they are per-fighter, so one bar
 * came out striped while the three beside it were smooth, and every reader
 * called it a rendering bug rather than information. A bar with no legend cannot
 * carry them. The marker halting on a Stop already shows the player what a Stop
 * does, at the moment it matters.
 */
function HealthTrack({ track, at, scale }) {
  if (!track || track.length < 2 || at == null) return null;
  const top = track.length - 1;
  const pct = Math.max(0, Math.min(100, (at / top) * 100));
  const hpMax = Math.max(0, ...track.filter((sp) => sp.kind === "hp").map((sp) => sp.hp));
  const hpNow = spaceValue(track, at);
  const frac = hpMax ? hpNow / hpMax : 0;
  const tone = frac >= 0.6 ? "hi" : frac >= 0.3 ? "mid" : "lo";
  // How long this fighter's bar is against the toughest fighter in the game.
  // Without it a 5 HP fighter at full health and a 25 HP fighter at full health
  // drew the identical full bar, so relative durability -- the thing a 2v2
  // brawler is read on -- was invisible.
  const cap = Math.max(18, Math.min(100, (hpMax / (scale || hpMax || 1)) * 100));

  return (
    <div className="rt-track" role="img" aria-label={`${hpNow} of ${hpMax} health`}>
      <span className={`rt-track-cap rt-track-${tone}`} style={{ width: `${cap}%` }}>
        <span className="rt-track-fill" style={{ width: `${pct}%` }} />
      </span>
    </div>
  );
}

/* A Fighter's special track, ON THE CARD, drawn as a track.
 *
 * These were chips: "Fleet 7", "Divine Voice 2", "Spirit 1". A number tells you
 * where the marker is and nothing about where it is GOING — how far to the next
 * payout, how far to the top, whether the top is close enough to plan around.
 * That is the whole of what these tracks are for. Ching Shih's deck reads
 * thresholds at 7, 10, 15 and 20; Bödvar's Rage ends the moment it tops out;
 * Joan's dial pays on two of its four spaces. None of that is legible from an
 * integer, and it is exactly what a player needs while deciding where to slide
 * their next card.
 *
 * Drawn from the same `special_track` the modal uses, so a corrected import
 * moves both. A track with real spaces gets a pip per space with the marker on
 * one; a track that is only a range (the Fleet) gets a proportional bar with its
 * thresholds notched.
 */
function SpecialOnCard({ board, state }) {
  const spec = board.special_track;
  if (!spec || !spec.id) return null;
  const at = state.tracks?.[spec.id] ?? spec.start ?? 0;
  const spaces = spec.spaces || [];
  const name = TRACK_TITLE[spec.id] || String(spec.id).replace(/_/g, " ");

  if (spaces.length) {
    return (
      <div className="rt-sp" title={`${name}: ${at} of ${spaces.length - 1}`}>
        <span className="rt-sp-n">{name}</span>
        <span className="rt-sp-pips" role="img"
          aria-label={`${name}, on space ${at} of ${spaces.length - 1}`}>
          {spaces.map((sp, i) => {
            const cls = ["rt-sp-p"];
            if ((sp.icons || []).length) cls.push("rt-sp-pay");
            if (i === at) cls.push("rt-sp-here");
            return <i key={i} className={cls.join(" ")} />;
          })}
        </span>
      </div>
    );
  }

  const max = spec.max ?? 0;
  const min = spec.min ?? 0;
  if (max - min > 0 && max - min <= 8) {
    // Short enough to count at a glance — the Fey Folk's 1-to-4 Spirit track.
    const steps = [];
    for (let v = min; v <= max; v++) steps.push(v);
    return (
      <div className="rt-sp" title={`${name}: ${at} of ${max}`}>
        <span className="rt-sp-n">{name}</span>
        <span className="rt-sp-pips" role="img" aria-label={`${name} ${at} of ${max}`}>
          {steps.map((v) => (
            <i key={v} className={`rt-sp-p${v === at ? " rt-sp-here" : ""}${v < at ? " rt-sp-done" : ""}`} />
          ))}
        </span>
      </div>
    );
  }
  const pct = max > min ? Math.max(0, Math.min(100, ((at - min) / (max - min)) * 100)) : 0;
  return (
    <div className="rt-sp" title={`${name}: ${at} of ${max}`}>
      <span className="rt-sp-n">{name}</span>
      <span className="rt-sp-bar" role="img" aria-label={`${name} ${at} of ${max}`}>
        <span className="rt-sp-fill" style={{ width: `${pct}%` }} />
        {(TRACK_MARKS[spec.id] || []).map((v) => (
          <i key={v} className="rt-sp-mark"
            style={{ left: `${((v - min) / (max - min)) * 100}%` }} />
        ))}
      </span>
      <b className="rt-sp-v">{at}</b>
    </div>
  );
}

/* The Fey Folk's three Characters, all of them, on the fighting card.
 *
 * The card showed only the one on the board — so a fighter with the Fairy up
 * read "3/3" while carrying nine more health in two Characters nobody could
 * see, and there was no way to tell which of the three had already gone. Both
 * matter every turn: how much is left in the team, and how much is left in the
 * one you can actually hit.
 *
 * A waiting Character shows its FULL health because that is what it comes in
 * on — damage never carries across.
 */
function CharacterRoster({ board, state }) {
  const chars = board.characters;
  if (!chars) return null;
  const track = trackFor(state, board);
  return (
    <div className="rt-roster">
      {chars.map((c) => {
        const at = state.chars?.[c.id] || "waiting";
        const max = maxOfTrack(c.hp_track);
        return (
          <span className={`rt-rost rt-rost-${at}`} key={c.id}>
            <b className="rt-cap">{c.name || c.id}</b>
            <i>{at === "spirit" ? "spirit"
              : at === "active" ? `${spaceValue(track, state.hp)}/${max}`
                : `${max}/${max}`}</i>
          </span>
        );
      })}
    </div>
  );
}

function FighterCard({ fid, state, board, active, fx, beatKey, scale, onInfo }) {
  const gesture = useCardInfoGesture(board ? onInfo : null);
  if (!state || !board) return <div className="rt-fighter rt-fighter-ghost" />;
  const sig = sigilOf(fid);
  const track = trackFor(state, board);
  const hpNow = spaceValue(track, state.hp);
  const hpMax = Math.max(0, ...track.filter((s) => s.kind === "hp").map((s) => s.hp));
  const here = track[state.hp];
  const ko = !!here && here.kind === "ko";
  const spirit = !!here && here.kind === "spirit";
  // The Fey Folk with all three Characters gone have NO track at all: they are
  // still in the fight, but they cannot lose or recover health. Without this
  // they rendered as "0 /0" with the bar element missing entirely, still wearing
  // the active glow, and with their Character tag silently replaced by the
  // board's first trait -- three separate lies about the same fighter.
  const spent = board.characters && !state.character;

  const chips = [];
  const tok = state.tokens || {};
  for (const [name, n] of Object.entries(tok)) {
    // `serpent` and `serpent_face` are ONE physical token and which way up it
    // is, not two things to hold. Rendering both read as "1 serpent" beside
    // "black serpent" on the same board.
    if (name === "serpent_face") continue;
    if (name === "serpent") {
      if (n > 0) {
        chips.push(
          <span className="rt-chip" key={name}>
            {tok.serpent_face ? "black" : "white"} serpent
          </span>);
      }
      continue;
    }
    if (n > 0) {
      chips.push(
        <span className={`rt-chip${name === "aflame" ? " rt-chip-fire" : ""}`} key={name}>
          {name === "aflame" && <Icon name="ignite" />}
          {tokenWord(name)} <b>{n}</b>
        </span>);
    }
  }
  if (state.planted > 0) {
    chips.push(
      <span className="rt-chip" key="planted">
        <Icon name="plant_scheme" />planted <b>{state.planted}</b>
      </span>);
  }
  // Special tracks used to be chips here — a bare number. They are DRAWN now,
  // by `SpecialOnCard` below the health bar, so the chip row is tokens only.

  const cls = ["rt-fighter"];
  if (active && !ko && !spirit && !spent) cls.push("rt-active");
  if (ko || spirit || spent) cls.push("rt-ko");
  if (fx?.hp < 0) cls.push("rt-struck");
  if (fx?.hp > 0) cls.push("rt-mended");

  return (
    <div className={cls.join(" ")} style={{ "--f-ink": sig.ink, "--f-deep": sig.deep }}
      {...gesture} title={`${board.name} — hold or right-click for details`}>
      <div className="rt-fighter-glow" aria-hidden="true" />
      <div className="rt-fhd">
        <span className="rt-crest"><Sigil fid={fid} /></span>
        <span className="rt-fname-wrap">
          <span className="rt-fname">{board.name}</span>
          <span className="rt-ftags">
            {state.face === "berserker_bear"
              ? <span className="rt-tag rt-tag-hot">Bear</span>
              : spent
                ? <span className="rt-tag rt-tag-cold">all Spirits</span>
                : state.character
                  ? <span className="rt-tag rt-cap">{state.character}</span>
                  : (board.tags || []).slice(0, 1).map((t) => <span className="rt-tag" key={t}>{t}</span>)}
          </span>
        </span>
      </div>

      <div className="rt-stats">
        <span className="rt-stat rt-hp">
          <Icon name="hp" />
          <b>
            {ko ? "KO" : spirit || spent ? "—" : hpNow}
            {!ko && !spirit && !spent && <small className="rt-den">{`/${hpMax}`}</small>}
          </b>
        </span>
        <span className="rt-stat rt-pw">
          <Icon name="power" /><b>{state.power}</b><small>Power</small>
        </span>
      </div>

      {spent
        ? <div className="rt-track rt-track-gone" role="img" aria-label="no health track" />
        : <HealthTrack track={track} at={state.hp} scale={scale} />}
      <CharacterRoster board={board} state={state} />
      <SpecialOnCard board={board} state={state} />
      {/* Reserved so a chip appearing mid-round does not shift the whole
          column below it. */}
      <div className="rt-chips">{chips}</div>

      {/* The number that floats off a fighter when they are hit. Keyed on the
          beat so stepping back and forward replays it instead of showing a
          stale one frozen at the end of its animation. */}
      {!!fx?.hp && (
        <span className={`rt-pop ${fx.hp < 0 ? "rt-pop-hit" : "rt-pop-heal"}`} key={`hp${beatKey}`}>
          {fx.hp < 0 ? "" : "+"}{fx.hp}
        </span>
      )}
      {!!fx?.power && (
        <span className="rt-pop rt-pop-pw" key={`pw${beatKey}`}>
          {fx.power > 0 ? "+" : ""}{fx.power} pw
        </span>
      )}
      {(ko || spirit || spent) && (
        <span className="rt-kostamp">{spent ? "Spent" : spirit ? "Spirit" : "KO"}</span>
      )}
    </div>
  );
}

function TeamSide({ label, mine, team, fighters, catalog, activeSlot, fxSlots, beatKey, scale, onInfo }) {
  return (
    <div className={`rt-side${mine ? " rt-mine" : ""}`}>
      <div className="rt-side-hd">
        <span className="rt-side-name">{label}</span>
        <span className="rt-side-tag">{mine ? "your team" : "their team"}</span>
      </div>
      <div className="rt-fighters">
        {(team || []).map((fid, slot) => (
          <FighterCard
            key={`${fid}-${slot}`}
            fid={fid}
            state={fighters?.[slot]}
            board={catalog?.fighters?.[fid]}
            active={activeSlot === slot}
            fx={fxSlots?.[slot]}
            beatKey={beatKey}
            scale={scale}
            onInfo={onInfo ? () => onInfo({ kind: "fighter", fid }) : null}
          />
        ))}
      </div>
    </div>
  );
}

/* A card as it sits in the ring.
 *
 * Rendered from the op list, so the picture and the words come from the same
 * source and cannot drift. The emblem gets a proper ART WINDOW at the top rather
 * than being blown up as a watermark behind the text: as a watermark it was
 * clipped by whichever card edge it happened to reach, sat under the body copy
 * greying it out mid-sentence, and landed differently on every card — three
 * separate reviewers read it as a broken background image.
 */
function PlayCard({ card, catalog, flipKey, side, onInfo }) {
  const gesture = useCardInfoGesture(card ? onInfo : null);
  const fid = card?.fighter;
  const sig = sigilOf(fid);
  const board = catalog?.fighters?.[fid];

  if (!card) {
    return (
      <div className={`rt-card rt-card-empty rt-card-${side}`}>
        <div className="rt-card-art rt-card-art-empty" />
        <div className="rt-card-body">
          <span className="rt-card-none">No card</span>
        </div>
      </div>
    );
  }

  const ops = card.ops || [];
  const bonuses = ops.filter((op) => op.success);
  return (
    <div className={`rt-card rt-card-${side}`} key={flipKey}
      style={{ "--f-ink": sig.ink, "--f-deep": sig.deep }}
      {...gesture} title={`${card.name} — hold or right-click for details`}>
      <div className="rt-card-art">
        <Sigil fid={fid} />
        {card.instant_bonus && <span className="rt-card-flag">instant bonus</span>}
      </div>
      <div className="rt-card-body">
        <div className="rt-card-hd">
          <span className="rt-card-name">{card.name}</span>
          <span className="rt-card-by">{board?.name || ""}</span>
        </div>
        <ul className="rt-card-ops">
          {ops.map((op, i2) => (
            <li key={i2}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
          ))}
          {bonuses.map((op, i2) => (
            <li className="rt-card-bonus" key={`b${i2}`}>
              <Icon name="fx" /><span>Success: {op.success.map(opWords).join(", ")}</span>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

/* A board's health track, drawn rather than described.
 *
 * The facts below it were sentences about a spatial thing — "1 STOP space, the
 * marker halts the moment it lands on one", "4 spaces carry an icon" — which is
 * the hardest possible way to say where they are. The strip is generated from
 * the same data, so it cannot disagree with the prose it replaces.
 */
function TrackStrip({ track }) {
  if (!track || track.length < 2) return null;
  return (
    <div className="rt-strip" role="img"
      aria-label={`${maxOfTrack(track) ?? "?"} health over ${track.length} spaces`}>
      {track.map((sp, i) => {
        const stop = isStop(sp);
        const ops = spaceIcons(sp);
        const cls = ["rt-cell"];
        if (sp.kind !== "hp") cls.push(`rt-cell-${sp.kind}`);
        else if (stop) cls.push("rt-cell-stop");
        else if (ops.length) cls.push("rt-cell-icon");
        // The tooltip used to read "icon", which is the word the reader opened
        // the modal to have explained.
        const title = [spaceWhere(sp), stop ? "STOP" : null,
          ops.length ? ops.map(opWords).join(", ") : null].filter(Boolean).join(" — ");
        return <i key={i} className={cls.join(" ")} title={title} />;
      })}
    </div>
  );
}

/* A circular track, drawn as a circle.
 *
 * Joan's dial was a row of five boxes, which is the one shape it is not: the
 * rules call it a ring, the marker goes round it, and a straight line cannot
 * show that space 4 leads back to space 1. It also cannot show the thing that
 * catches every player once — the Halo in the middle is where the marker STARTS
 * and is never returned to, so the ring is four long, not five.
 *
 * Drawn rather than described, and drawn from the data: the node count, which
 * nodes pay and where the marker enters all come off `spaces`, so a corrected
 * import turns the dial with it. Index 0 is the start; the rest are the ring, in
 * travel order, which is why they are laid out clockwise from the top right.
 */
function DialRing({ spaces }) {
  const ring = spaces.slice(1);
  if (!ring.length) return null;
  const C = 62, R = 40, NODE = 12;
  // Place each space where it actually IS on the board when the data says so.
  // Laying them out by index instead put Joan's first step in the top RIGHT
  // corner, where the rulebook has her second — the drawn dial has to agree with
  // the physical one or it is worse than the row of boxes it replaced.
  const CORNER = {
    top_left: -135, top_right: -45, bottom_right: 45, bottom_left: 135,
  };
  const at = (i) => {
    const named = CORNER[ring[i]?.name];
    const deg = named != null ? named : -45 + (360 / ring.length) * i;
    const a = (deg * Math.PI) / 180;
    return [C + R * Math.cos(a), C + R * Math.sin(a)];
  };
  const [ex, ey] = at(0);
  // The travel arrow sits on the ring midway along the arc from the first node
  // to the second, pointing the way the marker goes.
  const ang = (i) => Math.atan2(at(i)[1] - C, at(i)[0] - C);
  const step = ring.length > 1
    ? ((ang(1) - ang(0) + Math.PI * 4) % (Math.PI * 2)) : Math.PI / 2;
  const mid = ang(0) + step / 2;
  const [ax, ay] = [C + R * Math.cos(mid), C + R * Math.sin(mid)];
  const tan = mid + Math.PI / 2;                       // clockwise tangent
  const tip = (d, w) => [ax + d * Math.cos(tan) + w * Math.cos(tan + Math.PI / 2),
    ay + d * Math.sin(tan) + w * Math.sin(tan + Math.PI / 2)];

  return (
    <svg className="rt-dial" viewBox="0 0 124 124" role="img"
      aria-label={`a ring of ${ring.length}, entered from the centre`}>
      <circle className="rt-dial-ring" cx={C} cy={C} r={R} />
      {/* The one-way step out of the centre. Dashed because it is travelled
          once in the whole game. */}
      <line className="rt-dial-in" x1={C} y1={C} x2={ex} y2={ey} />
      <polygon className="rt-dial-arrow"
        points={[tip(7, 0), tip(-2, 4.5), tip(-2, -4.5)]
          .map(([x, y]) => `${x.toFixed(1)},${y.toFixed(1)}`).join(" ")} />
      <circle className="rt-dial-node rt-dial-start" cx={C} cy={C} r={NODE + 1} />
      <text className="rt-dial-t rt-dial-t-start" x={C} y={C}>start</text>
      {ring.map((sp, i) => {
        const [x, y] = at(i);
        const pays = (sp.icons || []).length > 0;
        return (
          <g key={i}>
            <circle className={`rt-dial-node${pays ? " rt-dial-on" : ""}`}
              cx={x} cy={y} r={NODE} />
            <text className={`rt-dial-t${pays ? " rt-dial-t-on" : ""}`} x={x} y={y}>
              {i + 1}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

/* The track BESIDE the health track — Joan's dial, Bödvar's Rage, Ching Shih's
 * Fleet, the Fey Folk's Spirits.
 *
 * Never drawn before. The modal said "Has a divine voice track of 5 spaces" and
 * stopped, which is why a player could watch Joan's marker go round all game and
 * never learn that two of the five positions pay and three do not.
 *
 * Two shapes: a track whose spaces DO something is drawn and then read out, and
 * a track that is only a number cards ask about (Ships, Spirits) has no
 * spaces in the data at all, so it shows its range instead of a fake strip.
 */
function SpecialTrack({ track }) {
  if (!track || !track.id) return null;
  const spaces = track.spaces || [];
  const label = TRACK_TITLE[track.id] || String(track.id).replace(/_/g, " ");
  const gloss = TRACK_GLOSSARY[track.id];
  // A circular track's first space is where the marker STARTS and, for Joan, is
  // never returned to; the rest are the ring. Numbering from the start space
  // rather than from 1 is what makes the read-out below line up with the strip.
  const ring = track.shape === "circular";
  const pipName = (i) => (ring ? (i === 0 ? "start" : String(i))
    : spaces[i]?.name || String(i));

  return (
    <div className="rt-special">
      <div className="rt-special-hd">
        <Icon name="track" />
        <b className="rt-cap">{label}</b>
        {spaces.length
          ? <span>{ring ? `${spaces.length - 1} spaces, in a ring` : `${spaces.length} spaces`}</span>
          : <span>{`runs ${track.min ?? 0} to ${track.max}`}</span>}
      </div>
      {ring
        ? <DialRing spaces={spaces} />
        : spaces.length > 0 && (
          <div className="rt-pips">
            {spaces.map((sp, i) => (
              <span key={i} className={`rt-pip${(sp.icons || []).length ? " rt-pip-on" : ""}`}>
                {pipName(i)}
              </span>
            ))}
          </div>
        )}
      {gloss && <p className="rt-special-note">{gloss}</p>}
      {spaces.some((sp) => (sp.icons || []).length) && (
        <ul className="rt-notes">
          {spaces.map((sp, i) => (sp.icons || []).length ? (
            <li key={i}>
              <b>{pipName(i)}</b><span>{sp.icons.map(opWords).join(", ")}</span>
            </li>
          ) : null)}
        </ul>
      )}
    </div>
  );
}

/* A Fighter's profile, laid out like the printed Fighters' Guide: what they are
 * in one paragraph, then five rated bars and the complexity dots.
 *
 * This is the half of a board that is a JUDGEMENT rather than a rule, and it is
 * the half our modal had none of. Everything else in here is derived from the
 * mechanics, which is right for the mechanics and useless for "is this Fighter
 * for me" -- the question the draft actually asks. The bars are data
 * (`rating` in boards.json, measured off the official sheet), so they draw the
 * same way for a thirteenth Fighter.
 */
const RATED = ["health", "offense", "defense", "heal", "special"];
const RATING_MAX = 5;

function RatingBar({ label, n }) {
  return (
    <div className="rt-rate">
      <span className="rt-rate-l">{label}</span>
      <span className="rt-rate-bar" role="img" aria-label={`${n} of ${RATING_MAX}`}>
        {Array.from({ length: RATING_MAX }, (_, i) => (
          <i key={i} className={`rt-rate-c${i < n ? " rt-rate-on" : ""}`} />
        ))}
      </span>
    </div>
  );
}

function FighterProfile({ board }) {
  const rating = board.rating;
  const cx = board.complexity;
  if (!board.profile && !rating && cx == null) return null;
  return (
    <>
      {board.profile && <p className="rt-profile">{board.profile}</p>}
      {(rating || cx != null) && (
        <div className="rt-rates">
          {rating && RATED.map((k) => (
            <RatingBar key={k} label={k} n={rating[k] ?? 0} />
          ))}
          {cx != null && (
            <div className="rt-rate rt-rate-cx">
              <span className="rt-rate-l">complexity</span>
              <span className="rt-rate-bar" role="img"
                aria-label={`${complexityWord(cx)} to learn, ${cx} of ${RATING_MAX}`}>
                {Array.from({ length: RATING_MAX }, (_, i) => (
                  <i key={i} className={`rt-dot${i < cx ? " rt-dot-on" : ""}`} />
                ))}
              </span>
              <span className="rt-rate-n">{complexityWord(cx)}</span>
            </div>
          )}
        </div>
      )}
    </>
  );
}

function InfoTarget({ as: Tag = "div", onInfo, children, ...rest }) {
  const gesture = useCardInfoGesture(onInfo);
  return <Tag {...rest} {...gesture}>{children}</Tag>;
}

/* A fighter or a card, in full.
 *
 * Reached by right-click or press-and-hold on anything that represents one —
 * the same gesture everywhere, so it means one thing. This is where the rules
 * text lives that will not fit on a face: a fighter's board oddities, and the
 * per-card FAQ notes from the data, which settle exactly the interactions a
 * player stops and wonders about mid-fight.
 */
function InfoModal({ info, catalog, onClose }) {
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const isCard = info.kind === "card";
  const card = isCard ? info.card : null;
  const fid = isCard ? card?.fighter : info.fid;
  const board = catalog?.fighters?.[fid];
  const sig = sigilOf(fid);
  if (isCard && !card) return null;
  if (!isCard && !board) return null;

  const deck = [];
  if (!isCard) {
    for (const [cid, c] of Object.entries(catalog?.cards || {})) {
      if (c.fighter === fid) deck.push({ cid, ...c });
    }
    deck.sort((a, b) => (b.starting ? 1 : 0) - (a.starting ? 1 : 0)
      || a.name.localeCompare(b.name));
  }

  const facts = isCard ? [] : boardFacts(board);
  /* Every health track this fighter can end up on, in the order they are met.
     The Fey Folk have three and no track of their own; Bödvar has a second one
     he can never go back from. Both used to draw an unlabelled strip with the
     number that matters -- how much it can take -- nowhere on it. */
  const tracks = isCard ? [] : (board.characters
    ? board.characters.map((c) => ({
      key: c.id, name: c.name || c.id, track: c.hp_track,
      max: maxOfTrack(c.hp_track), notes: trackNotes(c.hp_track, true),
    }))
    : [{
      // The fighter's own name is already the modal's title -- it only earns
      // the column when there is a second track to tell it apart from.
      key: "hp", name: board.back ? board.name : "health", track: board.hp_track,
      max: maxOfTrack(board.hp_track), notes: trackNotes(board.hp_track),
    }]).concat(!isCard && board.back?.hp_track ? [{
      key: "back", name: board.back.name, track: board.back.hp_track,
      max: maxOfTrack(board.back.hp_track), notes: trackNotes(board.back.hp_track),
    }] : []);
  const kinds = isCard ? [] : trackKinds(tracks.map((t) => t.track));
  const tokenRows = isCard ? []
    : Object.entries(board.tokens || {}).filter(([, n]) => n > 0);
  const absorbs = (!isCard && board.absorbs_attack) || [];
  const ops = isCard ? (card.ops || []) : [];
  const backOps = isCard && card.two_faced ? (card.ops_back || []) : [];
  const instantOps = isCard && Array.isArray(card.instant_bonus) ? card.instant_bonus : [];
  const gloss = isCard ? cardGlossary([ops, backOps, instantOps], card.note) : [];

  return (
    <div className="rt-backdrop" onClick={onClose} role="presentation">
      <div className="rt-modal" style={{ "--f-ink": sig.ink, "--f-deep": sig.deep }}
        role="dialog" aria-modal="true" aria-label={isCard ? card.name : board.name}
        onClick={(e) => e.stopPropagation()}>
        <div className="rt-modal-art">
          <span className="rt-modal-medal"><Sigil fid={fid} /></span>
        </div>
        <div className="rt-modal-body">
          <h2>{isCard ? card.name : board.name}</h2>
          {/* Two tiers, not one dot-run: what KIND of thing this is, then the
              numbers, in the same chip vocabulary the board uses — those are
              what the modal was opened to check. */}
          {!isCard && board.title && <p className="rt-modal-epithet">{board.title}</p>}
          <p className="rt-modal-tags">
            {isCard
              ? [board?.name, card.starting ? "Starting Card" : null,
                card.instant_bonus ? "instant bonus" : null].filter(Boolean).join(" · ")
              : (board.tags || []).join(" · ")}
          </p>
          {!isCard && <FighterProfile board={board} />}
          <p className="rt-modal-stats">
            {isCard ? (
              <span className="rt-chip">
                {card.copies > 1 ? `${card.copies} copies` : "1 copy"} in the deck
              </span>
            ) : (
              <>
                <span className="rt-stat rt-hp">
                  <Icon name="hp" /><b>{healthLabel(board)}</b><small>health</small>
                </span>
                <span className="rt-stat rt-pw">
                  <Icon name="power" /><b>{board.base_power}</b><small>Power</small>
                </span>
              </>
            )}
          </p>

          {isCard && (
            <ul className="rt-modal-ops">
              {ops.map((op, i) => (
                <li key={i}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
              ))}
              {ops.filter((op) => op.success).map((op, i) => (
                <li className="rt-card-bonus" key={`s${i}`}>
                  <Icon name="fx" /><span>Success: {op.success.map(opWords).join(", ")}</span>
                </li>
              ))}
              {backOps.length > 0 && (
                <li className="rt-modal-sep"><Icon name="flip_card" /><span>Turned over:</span></li>
              )}
              {backOps.map((op, i) => (
                <li key={`b${i}`}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
              ))}
              {/* The Instant Bonus was a WORD in the tag line and nothing else,
                  so a card whose whole value is what it pays on the way in
                  showed the reader a label and hid the payment. */}
              {instantOps.length > 0 && (
                <li className="rt-modal-sep"><Icon name="again" /><span>On the way in:</span></li>
              )}
              {instantOps.map((op, i) => (
                <li key={`i${i}`}><Icon name={iconForOp(op)} /><span>{opWords(op)}</span></li>
              ))}
            </ul>
          )}

          {isCard && (card.starting || instantOps.length > 0 || card.two_faced) && (
            <ul className="rt-modal-facts">
              {card.starting && (
                <li>
                  Starting Card — set aside at setup rather than shuffled in. Your two
                  Fighters&apos; Starting Cards, in an order you pick, are your whole opening
                  Fight Deck, so this one is guaranteed to come up in round 1.
                </li>
              )}
              {instantOps.length > 0 && (
                <li>
                  Instant Bonus — fires the moment you slide this card into your Fight Deck at
                  the end of a BUILD, before the next round starts. Once, on the way in; it
                  does nothing on the turns the card is actually revealed.
                </li>
              )}
              {card.two_faced && (
                <li>
                  Two-faced — it starts on the front and stays on whichever face it was left,
                  so what it does next round depends on what turned it over.
                </li>
              )}
            </ul>
          )}

          {isCard && card.note && <p className="rt-modal-note">{card.note}</p>}

          {isCard && gloss.length > 0 && (
            <>
              <h3 className="rt-modal-h3">How it works</h3>
              <ul className="rt-modal-facts">
                {gloss.map((g) => <li key={g.k}>{g.text}</li>)}
              </ul>
            </>
          )}

          {!isCard && (
            <>
              <h3 className="rt-modal-h3">Health track</h3>
              {tracks.map((t) => (
                <div className="rt-modal-track-block" key={t.key}>
                  <div className="rt-modal-track">
                    <span className="rt-modal-track-name rt-cap">{t.name}</span>
                    <TrackStrip track={t.track} />
                    {t.max != null && <b className="rt-modal-track-max">{t.max}</b>}
                  </div>
                  {t.notes.length > 0 && (
                    <ul className="rt-notes">
                      {t.notes.map((n, i) => (
                        <li key={i}><b>{n.at}</b><span>{n.text}</span></li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}
              {/* Only the kinds of space this board actually has. The old key
                  named all four on every fighter, so nine boards advertised a
                  revive space they do not own and the word "icon" was a legend
                  entry meaning "something happens, we are not saying what". */}
              {kinds.length > 0 && (
                <ul className="rt-modal-key">
                  {kinds.map((k) => (
                    <li key={k}>
                      <span className={`rt-cell rt-cell-${k}`} />
                      <span>{SPACE_GLOSSARY[k]}</span>
                    </li>
                  ))}
                </ul>
              )}

              {board.special_track && <SpecialTrack track={board.special_track} />}

              {tokenRows.length > 0 && (
                <>
                  <h3 className="rt-modal-h3">Tokens</h3>
                  <ul className="rt-modal-facts">
                    {tokenRows.map(([t, n]) => (
                      <li key={t}>
                        <b className="rt-cap">{tokenWord(t)}</b>
                        {n > 1 ? ` ×${n}` : ""} — {TOKEN_GLOSSARY[t]
                          || (absorbs.includes(t)
                            ? `Eats one Attack aimed at whoever is holding it, then returns to ${board.name} to be spent again.`
                            : "Read the cards that name it — nothing else moves it.")}
                      </li>
                    ))}
                  </ul>
                </>
              )}

              {(facts.length > 0 || board.note || (board.guide || []).length > 0) && (
                <>
                  <h3 className="rt-modal-h3">What this board does differently</h3>
                  <ul className="rt-modal-facts">
                    {facts.map((f, i) => <li key={i}>{f}</li>)}
                    {board.note && <li>{board.note}</li>}
                    {/* The Fighters' Guide's own entry for this Fighter: the
                        rules that are printed beside the board rather than on
                        it, so nothing in the modal can derive them. */}
                    {(board.guide || []).map((g, i) => <li key={`g${i}`}>{g}</li>)}
                  </ul>
                </>
              )}
            </>
          )}

          {!isCard && deck.length > 0 && (
            <>
              <h3 className="rt-modal-h3">
                Deck — {deck.reduce((n, c) => n + (c.copies || 1), 0)} cards
                {deck.length !== deck.reduce((n, c) => n + (c.copies || 1), 0)
                  && <span className="rt-modal-h3-sub">{deck.length} different</span>}
              </h3>
              <div className="rt-modal-deck">
                {deck.map((c) => (
                  <span className={`rt-modal-chip${c.starting ? " rt-modal-chip-start" : ""}`} key={c.cid}>
                    {c.name}{c.copies > 1 ? ` ×${c.copies}` : ""}
                    {c.starting && <em className="rt-modal-start">start</em>}
                  </span>
                ))}
              </div>
            </>
          )}
        </div>
        <button type="button" className="rt-modal-close" onClick={onClose} aria-label="Close">×</button>
      </div>
    </div>
  );
}

/* ── The component ───────────────────────────────────────────────────────── */

export default function RagTag({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");
  const [connecting, setConnecting] = useState(false);
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [toast, setToast] = useState("");
  const [openGames, setOpenGames] = useState(() => readLobbyCache("ragtag", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("ragtag", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("ragtag", myId, "history", []));
  const [loadingGames, setLoadingGames] = useState(false);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");

  // Local build-step selection, before it is submitted.
  const [buildPick, setBuildPick] = useState(null);
  const [buildPos, setBuildPos] = useState(null);
  // Playback cursor through this round's beats, advanced by hand.
  const [beatIdx, setBeatIdx] = useState(0);
  // ...and through the ACTIONS of the turn on the stage, advanced by a timer.
  // -1 is "the cards are face up and nothing has happened yet".
  const [stepIdx, setStepIdx] = useState(-1);
  // Rounds already fought, kept so the log is the whole fight and not just now.
  const [pastRounds, setPastRounds] = useState([]);
  // The fighter or card being read in full (press-and-hold / right-click).
  const [info, setInfo] = useState(null);

  const [historyShown, historyMore] = useProgressiveList(history);
  // A column that scrolls inside itself must say so — see `useListFade`.
  useListFade();
  const urlAttemptRef = useRef(null);

  const game = roomData?.game;
  const names = roomData?.players || {};
  const mySeat = game?.seats?.indexOf(myId) ?? -1;
  const theirSeat = mySeat >= 0 ? 1 - mySeat : -1;
  const over = !!game && game.winner !== null && game.winner !== undefined;

  /* ── socket ── */
  const handleMessage = useCallback((msg) => {
    setConnecting(false);
    if (msg.type === "error") {
      const ua = urlAttemptRef.current;
      if (ua) {
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("ragtag_roomId") === ua.rid) localStorage.removeItem("ragtag_roomId");
          localStorage.removeItem(`ragtag_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("ragtag"));
      }
      setToast(msg.message || "error");
      return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`ragtag_token_${rid}_${myId}`, tok);
        localStorage.setItem("ragtag_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined") {
      if (rid) pushPath(buildPath("ragtag", rid));
      urlAttemptRef.current = null;
      setRoomId(rid);
      setScreen(inGame ? "game" : "waiting");
    } else if (inGame && screen !== "game") {
      setScreen("game");
    }
  }, [myId, roomId, screen]);

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  /* Static card + board tables, once. Cached so a reconnect renders instantly. */
  useEffect(() => {
    try {
      const cached = localStorage.getItem("ragtag_catalog");
      if (cached) setCatalog(JSON.parse(cached));
    } catch {}
    fetch(`${RT_HTTP}/catalog`).then((r) => r.json()).then((d) => {
      if (d.roster) {
        setCatalog(d);
        try { localStorage.setItem("ragtag_catalog", JSON.stringify(d)); } catch {}
      }
    }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${RT_HTTP}/games`).then((r) => r.json()).then((d) => {
      const g = d.games || []; setOpenGames(g); writeLobbyCache("ragtag", myId, "open", g);
    }).catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${RT_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => {
        const g = d.games || []; setMyGames(g); writeLobbyCache("ragtag", myId, "mine", g);
      }).catch(() => {});
      fetchGameHistory(`${RT_HTTP}/games/history`, authUser).then((d) => {
        const g = d.games || []; setHistory(g); writeLobbyCache("ragtag", myId, "history", g);
      }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
      writeLobbyCache("ragtag", myId, "mine", []);
      writeLobbyCache("ragtag", myId, "history", []);
    }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  // The game you just finished leaves Active and joins History the moment it
  // ENDS, not when the lobby next loads — see useFinishedGameSync (shared kit).
  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("ragtag", myId, "mine", rid, setMyGames);
    fetchGames();
  });
  useEffect(() => () => disconnect(), []); // eslint-disable-line
  useEffect(() => {
    if (!toast) return undefined;
    const t = setTimeout(() => setToast(""), 2600);
    return () => clearTimeout(t);
  }, [toast]);

  const newRoomId = () => Math.random().toString(36).slice(2, 7).toUpperCase();

  const createGame = useCallback((vsAi) => {
    const rid = newRoomId();
    setConnecting(true); setRoomId(rid); setShowCreateModal(false);
    connect(`${RT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player", vs_ai: vsAi,
    });
  }, [connect, myId, authUser]);

  const joinGame = useCallback((rid) => {
    if (!rid) return;
    const code = String(rid).trim().toUpperCase();
    setConnecting(true); setRoomId(code);
    connect(`${RT_WS}/${code}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  }, [connect, myId, authUser]);

  const resumeGame = useCallback((rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`ragtag_token_${rid}_${myId}`); } catch {}
    setConnecting(true); setRoomId(rid);
    connect(`${RT_WS}/${rid}/${myId}`, tok
      ? { action: "reconnect", token: tok }
      : { action: "join", name: authUser?.name || "Player",
          session_token: authUser?.session_token || null });
  }, [connect, myId, authUser]);

  const cancelGame = useCallback((gid) => {
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    const roomToken = readRoomToken(`ragtag_token_${gid}_${myId}`);
    if (roomToken) headers["X-Room-Token"] = roomToken;
    fetch(`${RT_HTTP}/games/${gid}?player_id=${encodeURIComponent(myId)}`, {
      method: "DELETE", headers,
    }).then(() => fetchGames()).catch(() => {});
  }, [authUser, fetchGames, myId]);
  const leaveSeat = useCallback(async (gid) => {
    try {
      await leaveOpenSeat({
        endpoint: `${RT_HTTP}/games`, roomId: gid, playerId: myId,
        tokenKey: `ragtag_token_${gid}_${myId}`, sessionToken: authUser?.session_token,
      });
      setToast("Seat released");
      fetchGames();
    } catch (err) { setToast(err?.message || "Could not leave that table"); }
  }, [authUser, myId, fetchGames]);

  /* A dropped socket used to render "Reconnecting…" and then do nothing about
     it — the word was the whole of the feature. Worse in a vs-bot fight: the
     bot's turn is only re-driven when a client reconnects, so the fight froze
     until the page was reloaded. */
  const reconnectNow = useCallback(() => {
    let tok = null;
    try { tok = localStorage.getItem(`ragtag_token_${roomId}_${myId}`); } catch {}
    if (!tok) return;
    connect(`${RT_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok });
  }, [roomId, myId, connect]);

  useAutoReconnect({
    enabled: !!roomId && screen === "game" && roomData?.status !== "over",
    connected, connect: reconnectNow, socketReady,
  });

  const leaveToLobby = useCallback(() => {
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    replacePath(buildPath("ragtag"));
  }, [disconnect]);

  /* ── URL deep entry + Back/Forward ── */
  useEffect(() => {
    const path = window.location.pathname;
    const m = /\/ragtag\/([A-Za-z0-9_-]{1,24})\/?$/.exec(path);
    if (m) { urlAttemptRef.current = { rid: m[1].toUpperCase() }; resumeGame(m[1].toUpperCase()); }
  }, []); // eslint-disable-line

  useEffect(() => subscribe((r) => {
    if (r.game !== "ragtag") return;
    if (r.room) { urlAttemptRef.current = { rid: r.room }; resumeGame(r.room); }
    else { disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby"); }
  }), [resumeGame, disconnect]);

  /* ── Beat playback ──
   * `beats` is replaced wholesale each round, so the cursor resets when the
   * round does. Nothing here drives the SERVER: the fight is already resolved
   * and saved by the time the first card is shown, so stepping through it is
   * pure replay and a reconnect mid-round simply starts the replay again.
   *
   * The prompt for the next decision is held back until the last turn is on
   * screen. Otherwise the round's outcome arrives as a question before the
   * player has seen what happened, which is the exact thing being fixed.
   */
  const beats = game?.beats || [];
  const teams = game?.teams || [[], []];
  const cards = catalog?.cards || {};
  const instances = game?.instances || [];
  const cardOf = useCallback(
    (inst) => (inst == null ? null : cards[String(instances[inst]?.cid)] || null),
    [cards, instances]);

  useEffect(() => { setBeatIdx(0); setStepIdx(-1); }, [game?.round]);
  useEffect(() => { setPastRounds([]); setBeatIdx(0); setStepIdx(-1); }, [roomId]);

  /* Moving to a turn and moving WITHIN one are one gesture each, so they are one
     function each -- a `setBeatIdx` that forgot its `setStepIdx` would leave the
     new turn showing the old turn's cursor, which reads as a turn that skipped
     its first few actions. `showTurn` replays; `reviewTurn` shows a turn already
     resolved, which is what Back and "To the end" mean. */
  const showTurn = useCallback((n) => { setBeatIdx(n); setStepIdx(-1); }, []);
  const reviewTurn = useCallback((n) => { setBeatIdx(n); setStepIdx(STEP_DONE); }, []);

  /* The cursor walks the TURNS, not the beats. A round's beats also include
     setup and instant-bonus entries with no revealed cards, and stepping onto
     one showed the stage as "No card VS No card" -- an empty duel that the
     player had to click past before the fight started. Those events are not
     lost: they go straight into the log, which walks the full beat list. */
  const turnBeats = useMemo(() => beats.filter(isTurnBeat), [beats]);
  const lastIdx = Math.max(0, turnBeats.length - 1);
  const shownBeat = turnBeats.length ? turnBeats[Math.min(beatIdx, lastIdx)] : null;

  /* Where turn `n` sits in the full beat list, so the log can include whatever
     preceded it. */
  const beatPosOf = useCallback((n) => {
    let seen = -1;
    for (let k = 0; k < beats.length; k++) {
      if (isTurnBeat(beats[k]) && ++seen === n) return k;
    }
    return beats.length - 1;
  }, [beats]);

  /* Everything narration cannot work out for itself. The track comes from the
     BEAT's own snapshot when it has one, because it CHANGES within a round:
     Bödvar flips onto a second board and a Fey Folk Character brings their own,
     so reading an early turn's indices off the round's final track reports the
     wrong numbers. Falling back to live state covers beats saved before the
     snapshot existed. */
  const narrCtx = useMemo(() => ({
    name: (seat, slot) => catalog?.fighters?.[teams?.[seat]?.[slot]]?.name || "",
    track: (seat, slot, beat) => {
      const st = beat?.state?.[seat]?.[slot] || game?.fighters?.[seat]?.[slot];
      const bd = catalog?.fighters?.[teams?.[seat]?.[slot]];
      return st && bd ? trackFor(st, bd) : [];
    },
    mine: (seat) => seat === mySeat,
    cardName: (inst) => cardOf(inst)?.name || null,
  }), [catalog, teams, game?.fighters, mySeat, cardOf]);

  /* THE TURN ON THE STAGE, CUT INTO ITS ACTIONS. One step per event that has
     something to say, in causal order; `upto` is how far through the beat's events
     that step has got, and it is both the narration cutoff and the board cutoff so
     the sentence and the numbers cannot disagree. */
  const steps = useMemo(() => beatSteps(shownBeat, narrCtx), [shownBeat, narrCtx]);
  const lastStep = steps.length - 1;
  const stepNow = Math.max(-1, Math.min(stepIdx, lastStep));
  const stepUpto = stepNow < 0 ? 0 : steps[stepNow].upto;
  /* Whether this TURN has finished playing, and whether the ROUND has. The next
     decision waits on the second one -- it used to wait only on the turn cursor,
     which now lands a whole turn before that turn has finished happening. */
  const atStepEnd = stepIdx >= lastStep;
  const atEnd = turnBeats.length === 0 || (beatIdx >= lastIdx && atStepEnd);

  /* THE TIMER. It only ever walks the actions WITHIN a turn: a turn boundary is a
     click, deliberately, so the fight cannot run away from the player. Reduced
     motion skips straight to the resolved turn -- the stepping is pacing rather
     than decoration, so honouring it means not pacing at all. */
  const stillMotion = useMemo(() => typeof window !== "undefined"
    && !!window.matchMedia?.("(prefers-reduced-motion: reduce)").matches, []);
  const hasBeat = !!shownBeat;
  useEffect(() => {
    if (!hasBeat || atStepEnd) return undefined;
    if (stillMotion) { setStepIdx(STEP_DONE); return undefined; }
    const t = setTimeout(() => setStepIdx((n) => Math.max(-1, Math.min(n, lastStep)) + 1),
      stepNow < 0 ? REVEAL_MS : STEP_MS);
    return () => clearTimeout(t);
    // Deliberately NOT keyed on the beat OBJECT. `beats` is re-parsed on every
    // broadcast, so the beat on the stage is a new object each time one arrives
    // and depending on it restarted the dwell whenever anything at all happened
    // in the room -- an action could hold the stage indefinitely.
  }, [game?.round, beatIdx, hasBeat, atStepEnd, stepNow, lastStep, stillMotion]);

  const beatLines = useMemo(
    () => narrateBeat(shownBeat, narrCtx, stepUpto), [shownBeat, narrCtx, stepUpto]);

  /* THE FIGHTER BOARDS STEP WITH THE CURSOR -- with the ACTION cursor, not just the
     turn one. A round is resolved server-side in one go, so `game.fighters` is the
     state after the LAST turn of it: reading the boards off that made every health
     bar, Power total and token jump to its end-of-round value the moment the round
     landed. Each beat carries the state as it stood when the cards flipped and each
     of its events carries what THAT event moved, so the boards now walk the fight at
     the same rate as the sentences do. Outside a fight -- draft, build, a reconnect
     before the first beat -- there is no beat to read, and the live state is right. */
  const boardState = (shownBeat ? beatStateAt(shownBeat, stepUpto) : null) || game?.fighters;

  /* The log runs UP TO AND INCLUDING the turn on the stage. It used to stop one
     short, to avoid printing the same sentences in the ribbon and the log at
     once -- but "the log is always one turn behind" is how that reads while you
     are playing, and a log that omits what is on screen is not a record of the
     fight. The duplication is handled by marking the live turn instead (`live`
     below), so the log says "you are here" rather than repeating itself. */
  const livePos = useMemo(
    () => (over && atEnd ? beats.length - 1 : beatPosOf(beatIdx)),
    [over, atEnd, beats.length, beatPosOf, beatIdx]);
  const roundRows = useMemo(
    () => narrateRound(beats, livePos, narrCtx, beatPosOf(beatIdx), stepUpto),
    [beats, livePos, beatPosOf, beatIdx, narrCtx, stepUpto]);
  const fullRows = useMemo(() => narrateRound(beats, beats.length - 1, narrCtx), [beats, narrCtx]);

  /* Finished rounds are kept as their NARRATED rows rather than as beats: the
     text depends on board state that has since moved on, so re-narrating an old
     round later would quietly retell it wrong. */
  const carryRef = useRef({ round: null, rows: [] });
  useEffect(() => {
    const prev = carryRef.current;
    if (prev.round != null && prev.round !== game?.round && prev.rows.length) {
      setPastRounds((old) => [...old, { round: prev.round, rows: prev.rows }]);
    }
    carryRef.current = { round: game?.round, rows: [] };
  }, [game?.round]);
  useEffect(() => {
    if (carryRef.current.round === game?.round) carryRef.current.rows = fullRows;
  }, [fullRows, game?.round]);

  /* Which card each fighter opens with. "Who leads?" turns on exactly this and
     used to render "leads the round" under BOTH options -- a template string
     with the variable left out. */
  /* The toughest fighter in the game, so every health bar can be drawn to the
     same scale. Derived from the catalog rather than hardcoded so the next
     expansion's fighters rescale the bars instead of overflowing them. */
  const hpScale = useMemo(() => Math.max(1, ...Object.values(catalog?.fighters || {})
    .map(maxHpOf).filter(Boolean)), [catalog]);

  const startingCards = useMemo(() => {
    const out = {};
    for (const c of Object.values(catalog?.cards || {})) {
      if (c.starting && !out[c.fighter]) out[c.fighter] = c;
    }
    return out;
  }, [catalog]);

  const logRef = useRef(null);
  useEffect(() => {
    const el = logRef.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [roundRows.length, pastRounds.length]);

  /* What each fighter should show for THIS ACTION: the number that floats off
     them, and whether the board shakes. Scoped to the step rather than to the
     whole turn -- summing the turn made a card that hit for 3 and healed 2 float
     a single "−1", which is the arithmetic of the turn and not a thing that
     happened. Still summed WITHIN a step, because two sources reaching one marker
     in one action really is one movement. */
  const fxSlots = useMemo(() => {
    const out = { 0: {}, 1: {} };
    const evs = shownBeat?.events || [];
    const from = stepNow > 0 ? steps[stepNow - 1].upto : 0;
    for (const ev of stepNow < 0 ? [] : evs.slice(from, stepUpto)) {
      const bucket = out[ev.seat];
      if (!bucket || ev.slot == null) continue;
      const cur = bucket[ev.slot] || {};
      if (ev.kind === "hp") {
        // The track as it stands AT THIS STEP, not at the end of the turn:
        // Bödvar flips onto a second board mid-turn, so reading his indices off
        // the turn's final track prices the hit against the wrong board.
        const st = boardState?.[ev.seat]?.[ev.slot];
        const bd = catalog?.fighters?.[teams?.[ev.seat]?.[ev.slot]];
        const tr = st && bd ? trackFor(st, bd) : [];
        const a = tr[ev.from], b = tr[ev.to];
        const d = a && b && a.kind === "hp" && b.kind === "hp"
          ? b.hp - a.hp : ev.to - ev.from;
        bucket[ev.slot] = { ...cur, hp: (cur.hp || 0) + d };
      } else if (ev.kind === "power") {
        bucket[ev.slot] = { ...cur, power: (cur.power || 0) + (ev.to - ev.from) };
      }
    }
    return out;
  }, [shownBeat, steps, stepNow, stepUpto, boardState, catalog, teams]);

  /* What the round actually cost, totalled across every turn in it. The fight
     used to just stop -- the only sign it had ended was a button going grey. */
  const roundTally = useMemo(() => {
    const byWho = new Map();
    for (const beat of beats) {
      for (const ev of beat.events || []) {
        if (ev.kind !== "hp" || ev.slot == null) continue;
        const bd = catalog?.fighters?.[teams?.[ev.seat]?.[ev.slot]];
        const st = game?.fighters?.[ev.seat]?.[ev.slot];
        const tr = st && bd ? trackFor(st, bd) : [];
        const a = tr[ev.from], b = tr[ev.to];
        const d = a && b && a.kind === "hp" && b.kind === "hp"
          ? b.hp - a.hp : ev.to - ev.from;
        const key = `${ev.seat}-${ev.slot}`;
        byWho.set(key, (byWho.get(key) || 0) + d);
      }
    }
    return [...byWho.entries()]
      .filter(([, n]) => n !== 0)
      .map(([key, n]) => {
        const [seat, slot] = key.split("-").map(Number);
        return { key, n, dir: n < 0 ? "down" : "up", name: narrCtx.name(seat, slot) };
      });
  }, [beats, catalog, teams, game?.fighters, narrCtx]);

  /* ── Moves ── */
  const sendMove = useCallback((move) => send({ action: "move", move }), [send]);

  // WHAT DO I OWE? The server answers this (`you_owe`), because a simultaneous
  // game has no "your turn" to read off the phase and a client that re-derives it
  // shows the wrong prompt the moment the two disagree.
  const owes = useMemo(() => {
    if (!game || over || mySeat < 0 || !game.you_owe) return null;
    if (!atEnd) return null;           // let them finish watching the fight
    if (game.pending_is_yours) return "pending";
    return game.phase;                 // draft | order | build
  }, [game, over, mySeat, atEnd]);

  useEffect(() => { setBuildPick(null); setBuildPos(null); }, [game?.round, game?.phase]);

  /* ── Screens ── */
  if (connecting && screen === "lobby") {
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <LobbyLoading label="Connecting…" />
      </div>
    );
  }

  if (screen === "lobby") {
    const activeMine = notWaiting(myGames);
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <LobbyHeader
          onBack={onExit}
          user={<LobbyUser user={authUser} />}
        />
        <div className="lby-page"><div className="lby-page-in">
        <LobbyHero game="ragtag">
        {/* THE CREATE BUTTON SAYS "CREATE GAME" IN EVERY LOBBY. It said "+ Create
            Fight" here (and "+ Create Orbit" in Orbit) to match this lobby's own
            vocabulary — the rows, the empty states and the create modal all say
            fight — but the button is not part of that vocabulary: it is the same
            control in the same place on eight pages, and a player moving between
            them was re-reading a button they had already learned. The theming
            belongs on the things that are actually this game's. */}
        <LobbyCreateRow
          onCreate={() => setShowCreateModal(true)}
          onJoin={(code) => joinGame(code)}
          onRefresh={fetchGames}
          onRules={() => setShowRules(true)}
          refreshing={loadingGames} />
        </LobbyHero>

        {showCreateModal && (
          <CreateModal title="New Fight" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                { value: "friend", label: "VS Friend", title: "One friend joins from the lobby or your room code" },
                { value: "ai", label: "VS Bot", title: "Starts instantly against the bot" },
              ]} />
            </CmRow>
            <span className="cm-hint">
              Two fighters each, drafted. Both players reveal at the same time, and the
              deck is never shuffled.
            </span>
            <div className="cm-footer">
              <span className="cm-summary">
                Creating: <b>{createOpp === "ai" ? "vs Bot" : "vs Friend"}</b>
              </span>
              <button type="button" className="cm-create" onClick={() => createGame(createOpp === "ai")}>
                Create Game
              </button>
            </div>
          </CreateModal>
        )}

        <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
          { key: "open", label: "Open", count: openGames.length || null },
          { key: "active", label: "Active", count: activeMine.length || null },
          { key: "history", label: "History", count: history.length || null },
        ]} />

        <div className={`rt-lobby-cols lby-cols tab-${lobbyTab}`}>
          <div className="lby-col-open">
            <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
            {openGames.length === 0 && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
            <div className="lby-list">
              {openGames.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info">
                    <LobbyOpenTitle game={g} myId={myId} />
                    <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                  </div>
                  <div className="lby-card-actions">
                    <LobbyOpenActions state={seatStateOf(g, myId)}
                      onReturn={() => resumeGame(g.id)} onJoin={() => joinGame(g.id)}
                      onLeave={() => leaveSeat(g.id)} onCancel={() => cancelGame(g.id)} />
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lby-col-active">
            <LobbySectionHd title="Active Games" note={`${activeMine.length} in progress`} />
            {activeMine.length === 0 && <LobbyEmpty>No games in progress.</LobbyEmpty>}
            <div className="lby-list">
              {activeMine.map((g) => (
                <div className="lby-card" key={g.id}>
                  <div className="lby-card-info">
                    <LobbyMatchup placeholder="?" seats={[
                      { name: g.player1_name, you: g.you_are_p1 },
                      { name: g.player2_name, you: !g.you_are_p1 },
                    ]} />
                    <div className="lby-card-meta">
                      {g.round ? `round ${g.round} · ` : ""}{timeAgo(g.updated_at)}
                    </div>
                  </div>
                  <div className="lby-card-actions">
                    {g.your_turn ? <TurnBadge mine>Your turn</TurnBadge> : <TurnBadge>Their turn</TurnBadge>}
                    <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction>
                  </div>
                </div>
              ))}
            </div>
          </div>

          <div className="lby-col-history">
            <LobbySectionHd title="History" note={`${history.length} finished`} />
            {history.length === 0 && (
              <LobbyEmpty>{authUser ? "No finished fights yet." : "Log in to keep your game history."}</LobbyEmpty>
            )}
            <div className="lby-list">
              {historyShown.map((g) => (
                <div className="lby-card lby-card-hist" key={g.id}>
                  <div className="lby-card-info">
                    <div className="lby-card-title">
                      <span className={`hist-result ${g.outcome === "won" ? "won" : "lost"}`}>
                        {g.outcome === "won" ? "Won" : g.outcome === "draw" ? "Draw" : "Lost"}
                      </span>
                      <span className="hist-scores"> vs {g.you_are_p1 ? g.player2_name : g.player1_name}</span>
                    </div>
                  {/* HOW LONG THE FIGHT RAN sits IN the meta line, not in the slot
                      where the other six put a Review button. Rag Tag has no post-game
                      review; parking a non-interactive figure in the button's exact
                      geometry gave every row a target that does nothing, and moving it
                      to the right edge alone left ~250px of empty card between the
                      timestamp and it, repeated down eleven rows. On the meta line it
                      is what it is — a fact about the fight, beside the other two —
                      and the row simply has no right-hand slot to look empty. */}
                    <div className="lby-card-meta">
                      {(g.your_team || []).map((f) => catalog?.fighters?.[f]?.name || f).join(" + ")}
                      {g.rounds != null ? ` · ${g.rounds} round${g.rounds === 1 ? "" : "s"}` : ""}
                      {" · "}{timeAgo(g.updated_at)}
                    </div>
                  </div>
                </div>
              ))}
              {historyMore}
            </div>
          </div>
        </div>
        </div></div>
        {toast && <div className="rt-toast">{toast}</div>}
        {showRules && (
          <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
            <RagTagRules />
          </RulesModal>
        )}
      </div>
    );
  }

  // `WaitingRoom` in shared/lobby.jsx. `--lby-accent` is set on `.ragtag` in
  // RagTag.css (a stylesheet cannot import JS — see shared/accents.js), so the
  // root here needs no inline style the way the other lobbies' roots do.
  if (screen === "waiting") {
    return (
      <div className="app ragtag">
        <style>{ragtagStyles}</style>
        <WaitingRoom
          game="ragtag" roomId={roomId}
          players={names} hostId={roomData?.host} myId={myId}
          min={2} max={2}
          note="Two corners, twelve fighters, and a deck that is never shuffled."
          user={authUser}
          onLeave={leaveToLobby}
          onRules={() => setShowRules(true)}
          onStart={() => send({ action: "start" })}
          startLabel="Start the fight" />
        {showRules && (
          <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
            <RagTagRules />
          </RulesModal>
        )}
        {toast && <div className="rt-toast">{toast}</div>}
      </div>
    );
  }

  /* ── The board ── */
  const myTeam = mySeat >= 0 ? teams[mySeat] : [];
  const theirTeam = theirSeat >= 0 ? teams[theirSeat] : [];
  // Nothing empty is rendered before the bell: the draft used to sit under two
  // hollow team headers and a 200px box reading "The bell has not rung yet.",
  // which pushed the only decision on the screen most of a phone-height down.
  const fightOn = turnBeats.length > 0;
  const teamsKnown = (teams?.[0]?.length || 0) > 0 && (teams?.[1]?.length || 0) > 0;

  /* The instant-bonus beat is a real beat but NOT a turn -- it carries turn -1
     and no cards. Counting it made a two-turn round read "Turn 3 of 3". */
  const realTurns = turnBeats.length;

  const turnLabel = realTurns
    ? `Turn ${Math.min(beatIdx, lastIdx) + 1} of ${realTurns}` : "—";
  /* Kept OUT of `.rt-turnno`: that element is how the render gate proves the fight
     does not advance on its own, and a counter ticking inside it would move for a
     reason that is not a turn. */
  const stepLabel = steps.length > 1
    ? `action ${Math.max(0, stepNow) + 1} of ${steps.length}` : "";

  /* `row.live` is the turn currently on the stage. The log includes it rather than
     stopping one short, and marks it so the reader can see which entry the cards above
     them belong to. */
  const logRow = (row) => (row.kind === "turn"
    ? (
      <div className={`rt-log-turn${row.live ? " rt-log-now" : ""}`} key={row.key}>
        <span className="rt-log-turn-n">{row.turn == null ? "Setup" : `Turn ${row.turn}`}</span>
        {row.cards.filter(Boolean).length > 0 && (
          <span className="rt-log-turn-cards">{row.cards.filter(Boolean).join(" · ")}</span>
        )}
        {row.live && <span className="rt-log-here">on screen</span>}
      </div>
    ) : (
      <div className={`rt-log-line rt-tone-${row.tone}${row.live ? " rt-log-now" : ""}`}
        key={row.key}>
        <Icon name={row.icon} /><span>{row.text}</span>
      </div>
    ));

  return (
    <div className="app ragtag">
      <style>{ragtagStyles}</style>
      <LobbyHeader
        title="Rag Tag"
        /* Same wording, same order, same icons as every other game: return /
           rules / abandon — and abandon ASKS. Rag Tag was the odd one out: no
           icons, no confirmation, and one stray click ended the fight. */
        menu={<GameMenu onLeave={leaveToLobby} onRules={() => setShowRules(true)}
          onAbandon={over ? null : () => setConfirmAbandon(true)} />}
      />
      <div className="rt-wrap">
        {!connected && <div className="rt-waitline rt-warn">Reconnecting…</div>}

        <div className={`rt-layout${fightOn || pastRounds.length > 0 ? "" : " rt-layout-solo"}`}>
          <div className="rt-main">
            {teamsKnown && <TeamSide
              label={names[game?.seats?.[theirSeat]] || "Opponent"}
              team={theirTeam}
              fighters={boardState?.[theirSeat]}
              catalog={catalog}
              activeSlot={shownBeat?.active?.[theirSeat]}
              fxSlots={fxSlots[theirSeat]}
              beatKey={`${game?.round}-${beatIdx}-${stepNow}`}
              scale={hpScale}
              onInfo={setInfo}
            />}

            {fightOn ? (
              <section className="rt-stage">
                <header className="rt-stage-hd">
                  <span className="rt-round">
                    Round <b>{game?.round}</b>
                    <span className="rt-round-sep">·</span>
                    <span className="rt-turnno">{turnLabel}</span>
                    {/* Present for the whole time a turn is playing out, INCLUDING the
                        beat where the cards are face up and nothing has landed yet, and
                        including a turn with only one action in it -- `rt-actno-live` is
                        what says "still resolving", and a turn that dropped the marker
                        during its own reveal would report itself finished before it had
                        started. The COUNT is only worth printing when there is more than
                        one action to count, so a one-action turn shows the marker alone. */}
                    {steps.length > 0 && (
                      <span className={`rt-actno${atStepEnd ? "" : " rt-actno-live"}`}>
                        {stepLabel}
                      </span>
                    )}
                  </span>
                  {/* A tab REVIEWS the turn it names -- except the one you are already
                      on, which replays it. That is the only way back into an action you
                      watched go past, and it costs a control nobody has to learn. */}
                  <span className="rt-steps" role="tablist" aria-label="turns this round">
                    {turnBeats.map((b, i2) => (
                      <button
                        key={i2}
                        type="button"
                        role="tab"
                        aria-selected={i2 === beatIdx}
                        aria-label={`Turn ${i2 + 1}`}
                        title={`Turn ${i2 + 1}`}
                        className={`rt-step${i2 === beatIdx ? " rt-step-on" : ""}${i2 < beatIdx ? " rt-step-done" : ""}`}
                        onClick={() => (i2 === beatIdx ? showTurn(i2) : reviewTurn(i2))} />
                    ))}
                  </span>
                </header>

                <div className="rt-duel">
                  <PlayCard side="them" catalog={catalog}
                    card={cardOf(shownBeat?.insts?.[theirSeat])}
                    onInfo={() => setInfo({ kind: "card", card: cardOf(shownBeat?.insts?.[theirSeat]) })}
                    flipKey={`t-${game?.round}-${beatIdx}`} />
                  <div className="rt-clash" key={`c-${game?.round}-${beatIdx}`} aria-hidden="true">
                    <span className="rt-clash-burst" />
                    <span className="rt-clash-word">VS</span>
                  </div>
                  <PlayCard side="mine" catalog={catalog}
                    card={cardOf(shownBeat?.insts?.[mySeat])}
                    onInfo={() => setInfo({ kind: "card", card: cardOf(shownBeat?.insts?.[mySeat]) })}
                    flipKey={`m-${game?.round}-${beatIdx}`} />
                </div>

                {/* Keyed on the TURN, not on the step: the lines of a turn accumulate
                    here as it plays, and re-keying per step would remount the ones
                    already on screen and replay their entrance every action. The
                    stagger that used to fan them in went with the same change --
                    they arrive one at a time now, which is the thing the stagger was
                    imitating. "Nothing lands." waits for the turn to be over, or it
                    is a verdict passed before the turn has one. */}
                <div className="rt-ribbon" key={`rb-${game?.round}-${beatIdx}`}>
                  {beatLines.map((l) => (
                    <span className={`rt-rib rt-tone-${l.tone}`} key={l.key}>
                      <Icon name={l.icon} />{l.text}
                    </span>
                  ))}
                  {!beatLines.length && atStepEnd && (
                    <span className="rt-rib rt-tone-info"><Icon name="dot" />Nothing lands.</span>
                  )}
                </div>

                {atEnd && realTurns > 0 && (
                  <div className="rt-resolved">
                    <span className="rt-resolved-hd">Round {game?.round} resolved</span>
                    {roundTally.length > 0
                      ? roundTally.map((t) => (
                        <span key={t.key} className={`rt-tally rt-tally-${t.dir}`}>
                          {t.name} {t.dir === "down" ? "−" : "+"}{Math.abs(t.n)}
                        </span>))
                      : <span className="rt-tally">no health changed hands</span>}
                  </div>
                )}

                {/* Back and "To the end" REVIEW -- they land on a turn already
                    resolved, because you press them to see what happened rather
                    than to watch it again. The middle button is the only one that
                    changes what it says: while a turn is still playing it finishes
                    THAT turn, and only once the turn is over does it become the
                    next one -- so a click never costs you an action you had not
                    seen. It is dropped on the last turn, where "To the end" says
                    the same thing. */}
                <div className="rt-controls">
                  <button type="button" className="rt-ctl" disabled={beatIdx <= 0}
                    onClick={() => reviewTurn(Math.max(0, beatIdx - 1))}>
                    <Icon name="prev" />Back
                  </button>
                  {beatIdx < lastIdx && (
                    atStepEnd
                      ? (
                        <button type="button" className="rt-ctl rt-ctl-go"
                          onClick={() => showTurn(Math.min(lastIdx, beatIdx + 1))}>
                          Next turn<Icon name="next" />
                        </button>
                      ) : (
                        <button type="button" className="rt-ctl rt-ctl-go"
                          onClick={() => setStepIdx(STEP_DONE)}>
                          Finish turn<Icon name="next" />
                        </button>
                      )
                  )}
                  {!atEnd && (
                    <button type="button" className="rt-ctl"
                      onClick={() => reviewTurn(lastIdx)}>
                      To the end<Icon name="skip" />
                    </button>
                  )}
                </div>
              </section>
            ) : null}

            {teamsKnown && <TeamSide
              label={names[myId] || "You"} mine
              team={myTeam}
              fighters={boardState?.[mySeat]}
              catalog={catalog}
              activeSlot={shownBeat?.active?.[mySeat]}
              fxSlots={fxSlots[mySeat]}
              beatKey={`${game?.round}-${beatIdx}-${stepNow}`}
              scale={hpScale}
              onInfo={setInfo}
            />}

            {/* ── Prompts. Every one of them is "you owe a submission". ── */}
            {!over && owes === "pending" && game?.pending && (
              <div className="rt-prompt">
                <h3><Icon name="spirit" />Choose your next Character</h3>
                <p>Their marker goes on the top space of their track, and its icon applies at once.</p>
                <div className="rt-picks">
                  {game.pending.options.map((c) => (
                    <button type="button" className="rt-pick rt-pick-plain" key={c}
                      onClick={() => sendMove({ kind: "character", character: c })}>
                      <span className="rt-pick-body">
                        <span className="rt-pick-name rt-cap">{c}</span>
                      </span>
                    </button>
                  ))}
                </div>
              </div>
            )}

            {!over && owes === "draft" && (
              <div className="rt-prompt">
                <h3><Icon name="win" />
                  {game.draft_round === 2 ? "Your second fighter" : "Your first fighter"}
                  <span className="rt-step-of">fighter {game.draft_round === 2 ? 2 : 1} of 2</span>
                </h3>
                <p>
                  {game.draft_round === 2
                    ? "These are the ones your opponent passed on. This one fights beside your first."
                    : "Take one, then pass the rest across to your opponent."}
                </p>
                <div className="rt-picks rt-draft">
                  {(game.draft_hand || []).map((fid) => {
                    const b = catalog?.fighters?.[fid];
                    const sg = sigilOf(fid);
                    // The same number the detail modal shows, for the same
                    // reason: "5 HP" for the Fey Folk is the Elf, and you draft
                    // them knowing only that the Fairy comes in on 3.
                    const hp = b ? healthLabel(b) : null;
                    return (
                      <InfoTarget as="button" type="button" className="rt-pick rt-draft-card" key={fid}
                        style={{ "--f-ink": sg.ink, "--f-deep": sg.deep }}
                        title={`${b?.name || fid} — hold or right-click for details`}
                        onInfo={() => setInfo({ kind: "fighter", fid })}
                        onClick={() => sendMove({ kind: "draft", fighter: fid })}>
                        <span className="rt-draft-art"><Sigil fid={fid} /></span>
                        <span className="rt-draft-body">
                          <span className="rt-pick-name">{b?.name || fid}</span>
                          <span className="rt-draft-stats">
                            <span className="rt-stat rt-hp">
                              <Icon name="hp" /><b>{hp || "—"}</b><small>HP</small>
                            </span>
                            <span className="rt-stat rt-pw">
                              <Icon name="power" /><b>{b ? b.base_power : "?"}</b><small>Power</small>
                            </span>
                          </span>
                          <span className="rt-pick-tags">
                            {(b?.tags || []).map((t) => <em key={t}>{t}</em>)}
                          </span>
                        </span>
                      </InfoTarget>
                    );
                  })}
                </div>
              </div>
            )}

            {!over && owes === "order" && (
              <div className="rt-prompt">
                <h3><Icon name="again" />Who leads?</h3>
                <p>Whoever you pick plays their Starting Card first.</p>
                <div className="rt-picks rt-picks-wide">
                  {myTeam.map((fid, slot) => {
                    const sg = sigilOf(fid);
                    const sc = startingCards[fid];
                    return (
                      <InfoTarget as="button" type="button" className="rt-pick rt-pick-fighter" key={fid}
                        style={{ "--f-ink": sg.ink, "--f-deep": sg.deep }}
                        title={`${catalog?.fighters?.[fid]?.name || fid} — hold or right-click for details`}
                        onInfo={() => setInfo({ kind: "fighter", fid })}
                        onClick={() => sendMove({ kind: "order", slot })}>
                        <span className="rt-pick-crest"><Sigil fid={fid} /></span>
                        <span className="rt-pick-body">
                          <span className="rt-pick-name">{catalog?.fighters?.[fid]?.name || fid}</span>
                          <span className="rt-pick-sub">opens with <b>{sc?.name || "their Starting Card"}</b></span>
                          <span className="rt-pick-ops">
                            {(sc?.ops || []).map((op, n) => (
                              <em key={n}><Icon name={iconForOp(op)} />{opWords(op)}</em>
                            ))}
                          </span>
                        </span>
                      </InfoTarget>
                    );
                  })}
                </div>
              </div>
            )}

            {!over && owes === "build" && (() => {
              const offer = game.build_offer || [];
              // Two of the three offered cards are routinely the SAME card, and
              // rendered identically that reads as a rendering bug rather than
              // as a real choice between two copies. Number them.
              const seen = {};
              const copyOf = {};
              for (const inst of offer) {
                const cid = instances[inst]?.cid;
                seen[cid] = (seen[cid] || 0) + 1;
                copyOf[inst] = seen[cid];
              }
              const total = {};
              for (const inst of offer) total[instances[inst]?.cid] = seen[instances[inst]?.cid];

              const deck = game.fight_deck || [];
              const rows = [];
              const drop = (pos, label) => (
                <button type="button" key={`d${pos}`}
                  className={`rt-drop${buildPos === pos ? " rt-sel" : ""}`}
                  aria-label={label}
                  onClick={() => setBuildPos(pos)}>
                  <span className="rt-drop-line" />
                  <span className="rt-drop-label">{label}</span>
                  <span className="rt-drop-line" />
                </button>
              );
              // One grammar for all three, or the middle one reads as the only
              // target and the outer two read as section headings.
              rows.push(drop(0, "Insert here"));
              deck.forEach((inst, n) => {
                rows.push(
                  <InfoTarget className="rt-deck-row" key={`c${n}`}
                    title={`${cardOf(inst)?.name || "?"} — hold or right-click for details`}
                    onInfo={() => setInfo({ kind: "card", card: cardOf(inst) })}>
                    <span className="rt-deck-n">{n + 1}</span>
                    <span className="rt-deck-name">{cardOf(inst)?.name || "?"}</span>
                  </InfoTarget>);
                rows.push(drop(n + 1, "Insert here"));
              });

              const need = buildPick == null ? "Pick a card to keep"
                : buildPos == null ? "Now choose where it goes"
                : null;

              return (
                <div className="rt-prompt">
                  <h3><Icon name="plant_scheme" />Build your deck</h3>
                  <p>
                    The two you do not keep go to the bottom of your Build Deck.
                  </p>
                  <div className="rt-picks rt-picks-wide">
                    {offer.map((inst) => {
                      const c = cardOf(inst);
                      const sg = sigilOf(c?.fighter);
                      const cid = instances[inst]?.cid;
                      return (
                        <InfoTarget as="button" type="button" key={inst}
                          className={`rt-pick rt-pick-card${buildPick === inst ? " rt-sel" : ""}`}
                          aria-pressed={buildPick === inst}
                          style={{ "--f-ink": sg.ink, "--f-deep": sg.deep }}
                          title={`${c?.name || "card"} — hold or right-click for details`}
                          onInfo={() => setInfo({ kind: "card", card: c })}
                          onClick={() => { setBuildPick(inst); setBuildPos(null); }}>
                          <span className="rt-pick-crest"><Sigil fid={c?.fighter} /></span>
                          <span className="rt-pick-body">
                            <span className="rt-pick-name">
                              {c?.name || "?"}
                              {total[cid] > 1 && copyOf[inst] > 1 && (
                                <span className="rt-copy">2nd copy</span>
                              )}
                            </span>
                            <span className="rt-pick-sub">
                              {catalog?.fighters?.[c?.fighter]?.name}
                              {c?.instant_bonus ? " · instant bonus" : ""}
                            </span>
                            <span className="rt-pick-ops">
                              {(c?.ops || []).map((op, n) => (
                                <em key={n}><Icon name={iconForOp(op)} />{opWords(op)}</em>
                              ))}
                            </span>
                          </span>
                          {buildPick === inst && <span className="rt-pick-tick" aria-hidden="true" />}
                        </InfoTarget>
                      );
                    })}
                  </div>

                  {buildPick != null && (
                    <>
                      <div className="rt-slots">{rows}</div>
                    </>
                  )}

                  {need
                    ? <p className="rt-need"><Icon name="next" />{need}</p>
                    : (
                      <button type="button" className="rt-go"
                        onClick={() => sendMove({ kind: "build", inst: buildPick, pos: buildPos })}>
                        Lock it in
                      </button>
                    )}
                </div>
              );
            })()}

            {!over && owes === null && atEnd && (
              <div className="rt-waitline">
                {game?.phase === "build" ? "Waiting for your opponent to build…"
                  : game?.phase === "draft" ? "Waiting for their pick…"
                  : game?.phase === "order" ? "Waiting for them to choose who leads…"
                  : "Waiting…"}
              </div>
            )}

            {over && atEnd && (
              <div className={`rt-over rt-over-${game.winner === "draw" ? "draw" : game.winner === mySeat ? "win" : "lose"}`}>
                <span className="rt-over-crest"><Icon name="win" /></span>
                <h2>
                  {game.winner === "draw" ? "A draw"
                    : game.winner === mySeat ? "You win" : "You lose"}
                </h2>
                <p>{game.log?.[game.log.length - 1] || ""} · {game.round} rounds</p>
                <div className="rt-over-actions">
                  <LobbyAction onClick={leaveToLobby}>Back to lobby</LobbyAction>
                </div>
              </div>
            )}
            {/* Two different waits, and telling somebody to step to a turn they are
                already standing on is worse than saying nothing. */}
            {over && !atEnd && (
              <div className="rt-waitline rt-warn">
                {beatIdx >= lastIdx
                  ? "It is decided — the last turn is still playing out."
                  : "It is decided — step to the last turn to see how it ended."}
              </div>
            )}
          </div>

          {/* ── The battle log ──
              Only what has actually been watched. Stepping back does not erase
              it: the log is the record of the fight, the stage is the moment. */}
          <aside className={`rt-rail${roundRows.length || pastRounds.length ? "" : " rt-rail-empty"}`}>
            <div className="rt-log">
              <header className="rt-log-hd"><Icon name="track" />Battle log</header>
              <div className="rt-log-body" ref={logRef}>
                {pastRounds.map((r) => (
                  <section className="rt-log-round" key={`r${r.round}`}>
                    <h4>Round {r.round}</h4>
                    {r.rows.map(logRow)}
                  </section>
                ))}
                {roundRows.length > 0 && (
                  <section className="rt-log-round rt-log-live" key={`live-${game?.round}`}>
                    <h4>Round {game?.round}</h4>
                    {roundRows.map(logRow)}
                  </section>
                )}
                {roundRows.length === 0 && pastRounds.length === 0 && (
                  <p className="rt-log-empty">No turns resolved yet.</p>
                )}
              </div>
            </div>
          </aside>
        </div>
      </div>
      {confirmAbandon && (
        <div className="rt-backdrop" onClick={() => setConfirmAbandon(false)} role="presentation">
          <div className="rt-confirm" role="dialog" aria-modal="true"
            aria-label="Abandon this game?" onClick={(e) => e.stopPropagation()}>
            <h3>Abandon this game?</h3>
            <p>Your opponent wins the fight, and it moves to your history.</p>
            <div className="rt-confirm-acts">
              <button type="button" className="rt-ctl rt-ctl-danger"
                onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>
                Abandon
              </button>
              <button type="button" className="rt-ctl"
                onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            </div>
          </div>
        </div>
      )}
      {info && <InfoModal info={info} catalog={catalog} onClose={() => setInfo(null)} />}
      {toast && <div className="rt-toast">{toast}</div>}
      {showRules && (
        <RulesModal title="How to play — Rag Tag" onClose={() => setShowRules(false)}>
          <RagTagRules />
        </RulesModal>
      )}
    </div>
  );
}
