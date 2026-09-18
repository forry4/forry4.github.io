import { fetchGameHistory } from "../../shared/lobbyHistory.js";
import { Fragment, useState, useEffect, useLayoutEffect, useRef, useCallback, useId } from "react";
import { lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyMatchup, LobbyLoading, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss,
  useProgressiveList, LobbyTabs, useLastDifficulty, LobbyHero,
  LobbyAction, LobbyUser, useListFade, LobbyBotTier,
  WaitingRoom, waitingRoomCss } from "../../shared/lobby.jsx";
import CocRules from "./rules.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";
// Offline vs-AI: the local game driver (wasm engine + IndexedDB saves) — see offline.js.
import { applyOfflineCocMove, armCocUndoIfMyTurn, cocOfflineRoomData, runCocBotLoop,
  loadOfflineCocGame } from "./offline.js";

// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _cssText from "./CastlesOfCrimson.css?inline";
// The home card and this screen must be the same colour; one value, see shared/accents.js.
import { GAME_ACCENTS } from "../../shared/accents.js";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const COC_WS = WS_RAW.replace(/\/ws$/, "/coc/ws");
const COC_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/coc");

// Board layouts are fully static, so we cache them in localStorage (stale-while-
// revalidate). The board is then available synchronously on CoC entry — it never
// gates the game screen on a network fetch — and a background refresh self-heals if
// the board set ever changes (e.g. a board added). Bump the key on a shape change.
const COC_BOARDS_CACHE = "coc_boards_v1";
const boardsWithById = (d) => {
  if (!d) return null;
  const byId = {};
  (d.boards || []).forEach((b) => { byId[b.id] = b; });
  return { ...d, byId };
};

const TILE_HEX = {
  burgundy: "#a3263a",   // castle  -> crimson (the "burgundy" key is the backend's castle color)
  blue: "#3d6ea5",       // ship
  gray: "#6b6f76",       // mine
  green: "#8cc873",      // livestock -> light green
  beige: "#7a5f33",      // building (darker tan — the colorful building icons sit on top)
  yellow: "#fdd520",     // monastery -> bright yellow
};
const GOODS_HEX = {
  amber: "#e0a526", rose: "#d6678b", jade: "#3fae8e",
  cobalt: "#3b6fd0", plum: "#8a5cc0", rust: "#c0552f",
};
// The 6 territory colors, in the backend's board.COLORS order (drives the bonus strip).
const BOARD_COLORS = ["burgundy", "blue", "gray", "green", "beige", "yellow"];
// Region-completion VP has two parts (mirrors tiles.PHASE_BONUS / AREA_SCORE):
//  • phase bonus — a time bonus that shrinks each phase (finish regions early!)
//  • size bonus  — fixed VP by the region's number of spaces (1–8)
const PHASE_BONUS = { A: 10, B: 8, C: 6, D: 4, E: 2 };
const AREA_SCORE = [1, 3, 6, 10, 15, 21, 28, 36];   // completing a size-n region (n=1..8)
const TYPE_LABEL = {
  castle: "Castle", ship: "Ship", mine: "Mine",
  livestock: "Livestock", building: "Building", monastery: "Monastery",
};
// Fixed per-phase depot layout — mirrors tiles.DEPOT_PLAN (a deliberate house
// variant: each numbered depot always refills with the SAME two tile types).
// We keep a faint colored hex outline ("ghost") in any planned slot whose tile
// has been taken, so players can remember what goes where across phases. Colors
// are the tile-type colors from TILE_HEX above.
const DEPOT_PLAN_COLORS = {
  1: ["blue", "beige"],       // ship + building
  2: ["burgundy", "yellow"],  // castle + monastery
  3: ["green", "beige"],      // livestock + building
  4: ["blue", "beige"],       // ship + building
  5: ["gray", "yellow"],      // mine + monastery
  6: ["green", "beige"],      // livestock + building
};
// Tile color -> its type label (inverse of TILE_HEX's type comments), for ghost tooltips.
const COLOR_TYPE_LABEL = {
  burgundy: "Castle", blue: "Ship", gray: "Mine",
  green: "Livestock", beige: "Building", yellow: "Monastery",
};
// Friendly display name for a space's color (the backend's castle color is "burgundy",
// but the castle tiles are crimson, so show "crimson" to the player).
const colorLabel = (c) => (c === "burgundy" ? "crimson" : c);
// Ordered render slots for a numbered depot, one per planned tile type: each slot
// is either the tile currently sitting there (matched by color) or a ghost outline
// (taken). Because the slots stay in the fixed plan order, taking the LEFT tile
// leaves a ghost in its place and does NOT shift the right tile left — slot
// identity is stable across takes. Any unexpected extra tile is appended.
function depotSlots(d, hexes) {
  const present = [...(hexes || [])];
  const slots = [];
  for (const c of DEPOT_PLAN_COLORS[d] || []) {
    const i = present.findIndex((t) => t.color === c);
    if (i >= 0) slots.push({ tile: present.splice(i, 1)[0] });  // matching tile present
    else slots.push({ ghost: c });                              // planned but taken → ghost
  }
  for (const t of present) slots.push({ tile: t });             // defensive: unexpected leftovers
  return slots;
}
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
    return `#${n} goods — sell with die ${n} to gain 1 silver and 2 VP per good (2-player).`;
  }
  switch (t.type) {
    case "castle": return "Castle — when placed, take an immediate bonus action (a die of your choice).";
    case "ship": return "Ship — when placed, take all goods from one depot and advance the turn order.";
    case "mine": return "Mine — gain 1 silver at the end of each phase.";
    case "livestock": return `Livestock (${t.animal} ×${t.count}) — score VP for the animals; same-type animals grouped in one region re-score.`;
    case "building": return BUILDING_DESC[t.building] || "Building.";
    case "monastery": {
      const d = board?.monastery_meta?.[t.effect_id];
      return `Monastery #${t.effect_id}${d ? " — " + d : " — special effect."}`;
    }
    default: return TYPE_LABEL[t.type] || "Tile";
  }
}

// Full building name (for the move log).
const BUILDING_NAME = {
  market: "Market", carpenter: "Carpenter's Workshop", church: "Church",
  warehouse: "Warehouse", boarding: "Boarding House", bank: "Bank",
  townhall: "Town Hall", watchtower: "Watchtower",
};
// Short name for a tile in the move log, e.g. "a Ship", "Monastery #5", "Market".
function tileName(t) {
  if (!t) return "a tile";
  if (t.kind === "goods") return "goods";
  switch (t.type) {
    case "castle": return "a Castle";
    case "ship": return "a Ship";
    case "mine": return "a Mine";
    case "monastery": return `Monastery #${t.effect_id}`;
    case "building": return BUILDING_NAME[t.building] || "a Building";
    case "livestock": return `Livestock (${t.animal || "?"}${t.count ? " ×" + t.count : ""})`;
    default: return TYPE_LABEL[t.type] || "a tile";
  }
}
// Display name for a log record's source tile/ability (`via`), appended in parens so
// ability-driven actions read "took a Ship (Market)" / "gained 4 workers (Boarding House)".
function viaLabel(via) {
  if (!via) return "";
  if (via.slice(0, 10) === "monastery:") return `Monastery #${via.slice(10)}`;
  if (via === "ship") return "Ship";
  if (via === "castle") return "Castle";
  return BUILDING_NAME[via] || "a tile";
}
// Optimistic move preview (client-side): return a COPY of the game dict with the
// CERTAIN visible effect of `move` already applied, so the board reacts INSTANTLY
// instead of waiting the ~90ms server round-trip. The server stays authoritative —
// this preview is replaced wholesale by the next room_update (and reverted if the
// move errors, see handleMessage), so a wrong guess self-heals in a beat. Only the
// core, unambiguous moves are predicted (a tile moving in/out of storage/duchy + the
// die marked used — NOT scoring, resources, goods, or pending sub-decisions, which
// the server fills in on reconcile). Every other move returns null and falls through
// to the plain send-and-wait path. Guards bail to null on anything it can't be sure
// of (missing tile, occupied space, full storage) so it never shows a false board.
function optimisticMove(game, move, myId) {
  if (!game || !move || game.turn !== myId || game.phase !== "playing" || game.pending_pid) return null;
  const type = move.type;
  if (type !== "place_tile" && type !== "take_hex" && type !== "discard_storage") return null;
  let g;
  try { g = JSON.parse(JSON.stringify(game)); } catch { return null; }   // game is JSON-safe; board is small
  const me = g.players?.[myId];
  if (!me) return null;
  const dice = g.dice?.[myId];
  const useDie = () => { if (dice?.used && move.die_index != null) dice.used[move.die_index] = true; };
  if (type === "place_tile") {
    const st = me.storage || [];
    const idx = st.findIndex((x) => x && x.id === move.tile_id);
    me.duchy = me.duchy || {};
    if (idx < 0 || !move.space_id || me.duchy[move.space_id]) return null;
    me.duchy[move.space_id] = st.splice(idx, 1)[0];
    useDie();
    return g;
  }
  if (type === "take_hex") {
    const hexes = g.depots?.[String(move.depot)]?.hexes;
    if (!Array.isArray(hexes)) return null;
    const idx = hexes.findIndex((x) => x && x.id === move.tile_id);
    me.storage = me.storage || [];
    if (idx < 0 || me.storage.length >= 3) return null;   // full storage: let the server decide
    me.storage.push(hexes.splice(idx, 1)[0]);
    useDie();
    return g;
  }
  // discard_storage
  const st = me.storage || [];
  const idx = st.findIndex((x) => x && x.id === move.tile_id);
  if (idx < 0) return null;
  st.splice(idx, 1);
  return g;
}
// Descriptive move-log line built from the data already in each record (tile, depot, …).
// `board` supplies the goods number (goods are named "#N goods", never by color). The
// source-tile parenthetical (`via`) + any VP are appended by the log renderer, NOT here.
function moveText(m, board) {
  const t = m.tile;
  const gnum = (c) => (board ? board.goods_colors.indexOf(c) + 1 : "?");
  switch (m.type) {
    case "take_hex": return `took ${tileName(t)} from depot ${m.depot}`;
    case "place_tile": return `placed ${tileName(t)}`;
    case "buy_black": return `bought ${tileName(t)} from the black depot`;
    case "monastery6_take": return `took ${tileName(t)}`;
    case "building_take": return `took ${tileName(t)}`;
    case "discard_storage": return `discarded ${tileName(t)}`;
    case "place_starting_castle": return "placed their starting castle";
    case "sell_goods": return `sold ${m.count} #${gnum(m.color)} goods`;
    case "take_workers": return "took 2 workers";
    case "adjust_die": return m.frm != null ? `adjusted a ${m.frm} to a ${m.to}` : `adjusted a die to a ${m.to}`;
    case "ship_take_goods": return `took goods from depot ${m.depot}`;
    case "ship_adjacent_take": return `took goods from depot ${m.depot}`;
    case "build_gain":                                   // immediate-gain building effect
      if (m.workers) return `gained ${m.workers} worker${m.workers === 1 ? "" : "s"}`;
      if (m.silver) return `gained ${m.silver} silver`;
      if (m.vp) return `gained ${m.vp} VP`;
      return "used a building";
    case "building_effect": return `used ${BUILDING_NAME[m.building] || "a building"}`;  // legacy saved games
    case "monastery_placed": return `placed Monastery #${m.effect_id}`;
    case "area_complete": return "completed a region";
    case "bonus_tile": return `earned a ${colorLabel(m.color)} bonus tile`;
    case "livestock_score": return `scored ${m.animal || "livestock"}`;
    case "track_advance": return `advanced ${m.spaces} on the turn track`;
    case "end_turn": return "ended their turn";
    case "undo_turn": return "undid their turn";
    case "skip_pending": return "skipped";
    case "roll": return `rolled a ${m.d0} and a ${m.d1}`;
    case "mine_income": return `gained ${m.silver} silver from ${m.mines} mine${m.mines === 1 ? "" : "s"}`;
    case "monastery_income": return `gained ${m.workers} worker${m.workers === 1 ? "" : "s"} from Monastery ${m.effect}`;
    case "phase_end": return `— Phase ${m.phase} ended —`;
    default: return m.type;
  }
}

// ─── Tile icons ──────────────────────────────────────────────────────────────
// Little monochrome SVG icons (drawn in a 0..24 box, single color `c`). ship /
// castle / mine sit on dark tiles, so they're drawn in a light glyph; livestock
// animals sit on the light-green livestock tile, so they're dark with small white facial
// details to keep cow / pig / sheep distinguishable at tiny sizes.
const ICON = {
  ship: (c) => (<>
    <path d="M11 2 L11 14 L3.5 14 Z" fill={c} />
    <path d="M12.7 5 L12.7 14 L19 14 Z" fill={c} />
    <path d="M2.5 15.5 H21.5 L18.5 21 H5.5 Z" fill={c} />
  </>),
  castle: (c) => (
    <path fill={c} d="M3 21 V8 H5 V11 H7 V8 H9 V11 H11 V8 H13 V11 H15 V8 H17 V11 H19 V8 H21 V21 Z" />
  ),
  mine: (c) => (<>
    <path d="M3 8 Q12 3 21 8 L20 10 Q12 5.5 4 10 Z" fill={c} />
    <path d="M11 8 H13 L12.4 21 H11.6 Z" fill={c} />
  </>),
  // Buildings — themed colors on the beige building tile; holes (doors/windows/
  // clock) use fillRule="evenodd" so the tan tile shows through.
  market: () => (<>
    <path fill="#7ec46a" d="M3 4 H6 V7 Q4.5 8.6 3 7 Z" />
    <path fill="#7ec46a" d="M6 4 H9 V7 Q7.5 8.6 6 7 Z" />
    <path fill="#7ec46a" d="M9 4 H12 V7 Q10.5 8.6 9 7 Z" />
    <path fill="#7ec46a" d="M12 4 H15 V7 Q13.5 8.6 12 7 Z" />
    <path fill="#7ec46a" d="M15 4 H18 V7 Q16.5 8.6 15 7 Z" />
    <path fill="#7ec46a" d="M18 4 H21 V7 Q19.5 8.6 18 7 Z" />
    <path fill="#2f6fb0" d="M5 8.2 H6.8 V20 H5 Z M17.2 8.2 H19 V20 H17.2 Z" />
    <path fill="#2f6fb0" d="M4.5 18 H19.5 V20 H4.5 Z" />
  </>),
  carpenter: () => (<>
    <rect x="4.5" y="3.6" width="15" height="4.6" rx="1.5" fill="#4a3526" />
    <path fill="#9a6b3a" d="M10.4 8.2 H13.6 L13 21 Q12.9 21.8 12 21.8 Q11.1 21.8 11 21 Z" />
  </>),
  church: () => (<>
    <path fill="#e6b41e" d="M11.2 1 H12.8 V2.4 H14.2 V3.8 H12.8 V5.2 H11.2 V3.8 H9.8 V2.4 H11.2 Z" />
    <path fill="#b23a3a" d="M12 5.4 L18.5 12.5 H5.5 Z" />
    <path fill="#9a9aa3" fillRule="evenodd" d="M6.5 12.5 H17.5 V21 H6.5 Z M10.3 21 V16.8 Q12 15.2 13.7 16.8 V21 Z" />
  </>),
  warehouse: () => (<>
    <path fill="#7e9abb" fillRule="evenodd" d="M3 11 L12 5 L21 11 V21 H3 Z M7 13 H17 V21 H7 Z" />
    <path fill="#56729a" d="M7 14.6 H17 V15.6 H7 Z M7 16.8 H17 V17.8 H7 Z M7 19 H17 V20 H7 Z" />
  </>),
  boarding: () => (<>
    <path fill="#9a6b3a" d="M2 7 H4.2 V13 H2 Z" />
    <path fill="#9a6b3a" d="M2 13 H22 V16.6 H2 Z" />
    <path fill="#9a6b3a" d="M19.8 11 H22 V16.6 H19.8 Z" />
    <path fill="#9a6b3a" d="M2 16.6 H3.9 V19 H2 Z M20.1 16.6 H22 V19 H20.1 Z" />
    <path fill="#9a6b3a" d="M4.6 11.2 H11 Q12 11.2 12 12.2 V13 H4.6 Z" />
  </>),
  bank: () => (<>
    <path fill="#c2c6d0" d="M2.5 8 L12 3 L21.5 8 Z" />
    <path fill="#b3b7c2" d="M3.5 8.4 H20.5 V10 H3.5 Z" />
    <path fill="#a6abb7" d="M4.5 10.2 H6.4 V18 H4.5 Z M8.7 10.2 H10.6 V18 H8.7 Z M13.4 10.2 H15.3 V18 H13.4 Z M17.6 10.2 H19.5 V18 H17.6 Z" />
    <path fill="#9498a4" d="M3 18 H21 V20.6 H3 Z" />
  </>),
  townhall: () => (<>
    <rect x="11.4" y="1.6" width="1" height="5" fill="#b23a3a" />
    <path fill="#b23a3a" d="M12.4 1.9 H16.2 L14.7 3.3 L16.2 4.7 H12.4 Z" />
    <path fill="#b23a3a" fillRule="evenodd" d="M9.3 6.6 H14.7 V12 H9.3 Z M10.5 9.5 A1.5 1.5 0 1 1 13.5 9.5 A1.5 1.5 0 1 1 10.5 9.5 Z" />
    <path fill="#b23a3a" fillRule="evenodd" d="M4 12 H20 V21 H4 Z M10.5 21 V15.6 Q12 14.2 13.5 15.6 V21 Z" />
  </>),
  watchtower: () => (<>
    <path fill="#356340" fillRule="evenodd" d="M8 6 H9.6 V4.4 H11.2 V6 H12.8 V4.4 H14.4 V6 H16 V21 H8 Z M10.4 13 V10.6 Q12 8.9 13.6 10.6 V13 Z" />
    <path fill="#284e30" d="M6.5 19 H17.5 V21 H6.5 Z" />
  </>),
  cow: () => (<>
    <path d="M6.5 6 Q4 3.5 2.6 5 Q4 6.2 6.5 7.4 Z" fill="#15100a" />
    <path d="M17.5 6 Q20 3.5 21.4 5 Q20 6.2 17.5 7.4 Z" fill="#15100a" />
    <ellipse cx="12" cy="13" rx="7.6" ry="6.6" fill="#15100a" />
    <ellipse cx="12" cy="16" rx="4.4" ry="2.9" fill="#fff" />
    <circle cx="10.4" cy="16" r="0.7" fill="#15100a" />
    <circle cx="13.6" cy="16" r="0.7" fill="#15100a" />
    <circle cx="9" cy="11" r="1" fill="#fff" />
    <circle cx="15" cy="11" r="1" fill="#fff" />
  </>),
  pig: () => (<>
    <path d="M6 5.5 L10.5 6 L8.5 11 Z" fill="#e493aa" />
    <path d="M18 5.5 L13.5 6 L15.5 11 Z" fill="#e493aa" />
    <ellipse cx="12" cy="13.5" rx="7.6" ry="6.6" fill="#e493aa" />
    <ellipse cx="12" cy="15" rx="3.9" ry="3" fill="#f3d0db" />
    <ellipse cx="10.6" cy="15" rx="0.7" ry="1" fill="#b05f78" />
    <ellipse cx="13.4" cy="15" rx="0.7" ry="1" fill="#b05f78" />
    <circle cx="9" cy="11" r="1" fill="#fff" />
    <circle cx="15" cy="11" r="1" fill="#fff" />
  </>),
  sheep: () => (<>
    {/* round fluffy wool body: solid core + a full ring of bumps */}
    <circle cx="12" cy="12" r="6.4" fill="#888a8f" />
    <circle cx="18.3" cy="12" r="2.6" fill="#888a8f" />
    <circle cx="17.5" cy="15.2" r="2.6" fill="#888a8f" />
    <circle cx="15.2" cy="17.5" r="2.6" fill="#888a8f" />
    <circle cx="12" cy="18.3" r="2.6" fill="#888a8f" />
    <circle cx="8.8" cy="17.5" r="2.6" fill="#888a8f" />
    <circle cx="6.5" cy="15.2" r="2.6" fill="#888a8f" />
    <circle cx="5.7" cy="12" r="2.6" fill="#888a8f" />
    <circle cx="6.5" cy="8.8" r="2.6" fill="#888a8f" />
    <circle cx="8.8" cy="6.5" r="2.6" fill="#888a8f" />
    <circle cx="12" cy="5.7" r="2.6" fill="#888a8f" />
    <circle cx="15.2" cy="6.5" r="2.6" fill="#888a8f" />
    <circle cx="17.5" cy="8.8" r="2.6" fill="#888a8f" />
    {/* white ears poking out of the white face */}
    <ellipse cx="8.7" cy="8.3" rx="1.7" ry="1.8" fill="#fff" transform="rotate(-28 8.7 8.3)" />
    <ellipse cx="15.3" cy="8.3" rx="1.7" ry="1.8" fill="#fff" transform="rotate(28 15.3 8.3)" />
    {/* white face + eyes */}
    <rect x="8.3" y="9.1" width="7.4" height="7.4" rx="3.2" fill="#fff" />
    <circle cx="10.5" cy="12.3" r="0.8" fill="#33312e" />
    <circle cx="13.5" cy="12.3" r="0.8" fill="#33312e" />
  </>),
  chicken: () => (<>
    <path d="M4.2 12 Q1.4 13 3 16.3 Q5.2 15 6.8 13.8 Z" fill="#c9a24a" />{/* tail */}
    <ellipse cx="10.6" cy="14.6" rx="6.7" ry="5.5" fill="#f1ede1" />{/* body */}
    <circle cx="16" cy="9.6" r="3.4" fill="#f1ede1" />{/* head */}
    <path d="M14.5 5.2 Q15.3 3.5 16.1 5 Q16.9 3.5 17.5 5.2 Q17.1 6.5 16 6.7 Q14.8 6.5 14.5 5.2 Z" fill="#c0392b" />{/* comb */}
    <path d="M18.9 10 L22 9.2 L18.9 11.2 Z" fill="#e0a526" />{/* beak */}
    <path d="M16.3 12.3 Q16.4 13.6 15.3 13.5 Q16 12.7 15.8 12.1 Z" fill="#c0392b" />{/* wattle */}
    <circle cx="16.6" cy="9.1" r="0.75" fill="#15100a" />{/* eye */}
    <rect x="9" y="19.6" width="0.9" height="2.6" fill="#e0a526" />
    <rect x="12.3" y="19.6" width="0.9" height="2.6" fill="#e0a526" />
  </>),
};

function Icon({ kind, color, size }) {
  const draw = ICON[kind];
  if (!draw) return null;
  return (
    <svg viewBox="0 0 24 24" width={size} height={size}
      style={{ display: "block", filter: "drop-shadow(0 1px 1px rgba(0,0,0,.45))" }}>
      {draw(color)}
    </svg>
  );
}

// ── Monastery benefit icons ─────────────────────────────────────────────────
// Each of the 26 unique monasteries gets a small pictogram of the power it grants,
// so players read the tile at a glance. Everything is drawn in a 24x24 box (like
// ICON) as dark-on-yellow art with a few accent colors; a shared `MonasteryArt`
// composes the pictogram + a tiny corner id (kept for identity + "Monastery #N"
// log/tooltip references). Reused by BOTH render paths (HTML depot/storage tiles
// and the SVG board), since the fragment is pure SVG children.
const M_INK = "#2a1e0a";        // dark ink readable on the yellow tile
const M_WORK = "#5a3d22";       // worker (brown pawn)
const M_COIN = "#dfe3ea";       // silver coin face
const M_COINR = "#8b8f99";      // coin rim
const M_GREEN = "#2e7d32";      // "free / allowed" (die-shift) arrows
const M_VP = "#356340";         // victory-point star (watchtower green)
// worker pawn, ~6.5 tall, centered at (cx,cy)
const mPawn = (cx, cy, k = 1, c = M_WORK) => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <circle cx="0" cy="-2.6" r="1.9" fill={c} />
    <path d="M-2.7 3.4 Q-2.7 -0.7 0 -0.7 Q2.7 -0.7 2.7 3.4 Z" fill={c} />
  </g>
);
// silver coin, radius ~3.4
const mCoin = (cx, cy, k = 1) => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <circle r="3.4" fill={M_COIN} stroke={M_COINR} strokeWidth="0.8" />
    <circle r="1.6" fill="none" stroke={M_COINR} strokeWidth="0.7" />
  </g>
);
// die face (7x7) with pips at [x,y] in roughly -1..1
const mDie = (cx, cy, k = 1, pips = [[0, 0]]) => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <rect x="-3.5" y="-3.5" width="7" height="7" rx="1.4" fill="#f5eede" stroke={M_INK} strokeWidth="0.8" />
    {pips.map(([px, py], i) => <circle key={i} cx={(px * 2).toFixed(2)} cy={(py * 2).toFixed(2)} r="0.72" fill={M_INK} />)}
  </g>
);
// 5-point star (VP), outer radius r centered at (cx,cy)
const mStar = (cx, cy, r = 3.2, c = M_VP) => {
  const pts = Array.from({ length: 10 }, (_, i) => {
    const ang = -Math.PI / 2 + i * Math.PI / 5, rr = i % 2 ? r * 0.42 : r;
    return `${(cx + rr * Math.cos(ang)).toFixed(2)},${(cy + rr * Math.sin(ang)).toFixed(2)}`;
  }).join(" ");
  return <polygon points={pts} fill={c} />;
};
// double-headed shift arrow (horizontal) — used ONLY for two-way die adjustment
const mShift = (cx, cy, k = 1, c = M_INK) => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <path d="M-4 0 L-1.7 -1.9 L-1.7 -0.7 L1.7 -0.7 L1.7 -1.9 L4 0 L1.7 1.9 L1.7 0.7 L-1.7 0.7 L-1.7 1.9 Z" fill={c} />
  </g>
);
// single right-pointing arrow — for one-way transformations (spend X -> gain Y)
const mArrowR = (cx, cy, k = 1, c = M_INK) => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <path d="M-3.6 -1 H1 V-2.4 L4.2 0 L1 2.4 V1 H-3.6 Z" fill={c} />
  </g>
);
// filled colored hexagon (a tile-type swatch), thin ink rim for contrast on yellow
const mHexFill = (cx, cy, k = 1, c = "#888") => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <path d="M0 -3.4 L2.95 -1.7 L2.95 1.7 L0 3.4 L-2.95 1.7 L-2.95 -1.7 Z"
      fill={c} stroke="#2a1e0a" strokeWidth="0.7" />
  </g>
);
// vertical arrow — dir=1 points DOWN (placing onto the board), dir=-1 points UP (taking from it)
const mArrowV = (cx, cy, k = 1, dir = 1, c = M_GREEN) => (
  <g transform={`translate(${cx} ${cy}) scale(${k} ${k * dir})`}>
    <path d="M-1.2 -3.6 H1.2 V0.9 H2.7 L0 4.2 L-2.7 0.9 H-1.2 Z" fill={c} />
  </g>
);
// a hexagon striped with the given tile-type colors (one solid color = a plain fill).
// Uses a per-instance clip id so many striped hexes can co-exist in one document.
const _HEX_D = "M0 -3.9 L3.35 -1.95 L3.35 1.95 L0 3.9 L-3.35 1.95 L-3.35 -1.95 Z";
function HexStriped({ cx, cy, k = 1, colors = ["#888"] }) {
  const cid = "hx" + useId().replace(/[^a-zA-Z0-9]/g, "");
  const n = colors.length, x0 = -3.35, sw = 6.7 / n;
  return (
    <g transform={`translate(${cx} ${cy}) scale(${k})`}>
      <clipPath id={cid}><path d={_HEX_D} /></clipPath>
      <g clipPath={`url(#${cid})`}>
        {colors.map((c, i) => (
          <rect key={i} x={(x0 + i * sw - 0.02).toFixed(3)} y="-4.2" width={(sw + 0.04).toFixed(3)} height="8.4" fill={c} />
        ))}
      </g>
      <path d={_HEX_D} fill="none" stroke="#2a1e0a" strokeWidth="0.8" />
    </g>
  );
}
// goods barrel, ~6.8 tall
const mBarrel = (cx, cy, k = 1, c = "#8a5a2a") => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <rect x="-3" y="-3.4" width="6" height="6.8" rx="1.2" fill={c} />
    <rect x="-3.2" y="-1.9" width="6.4" height="0.9" fill="rgba(0,0,0,.22)" />
    <rect x="-3.2" y="1" width="6.4" height="0.9" fill="rgba(0,0,0,.22)" />
  </g>
);
// simple house (duplicate-building marker), ~7 tall
const mHouse = (cx, cy, k = 1, c = "#6b4a2a") => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <path d="M-3.2 4 V-0.5 L0 -3.5 L3.2 -0.5 V4 Z" fill={c} />
    <rect x="-1" y="1" width="2" height="3" fill="#f5eede" />
  </g>
);
// hexagon outline (take-a-hex marker)
const mHex = (cx, cy, k = 1, c = M_INK) => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <path d="M0 -3.6 L3.1 -1.8 L3.1 1.8 L0 3.6 L-3.1 1.8 L-3.1 -1.8 Z" fill="none" stroke={c} strokeWidth="1.2" />
  </g>
);
// small numeral/glyph accent
const mNum = (cx, cy, s, txt, c = M_INK) => (
  <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
    fontFamily="'Cinzel',serif" fontWeight="700" fontSize={s} fill={c}>{txt}</text>
);
// embed an existing ICON kind, scaled into an `s`-sized box centered at (cx,cy)
const mIcon = (kind, cx, cy, s, color = M_INK) => (
  <g transform={`translate(${(cx - s / 2).toFixed(2)} ${(cy - s / 2).toFixed(2)}) scale(${(s / 24).toFixed(4)})`}>
    {ICON[kind](color)}
  </g>
);
// shared base for the four "free die shift when placing X" monasteries (9-12)
const mDieShift = () => (<>
  {mDie(9, 13.5, 1.5, [[-0.55, -0.55], [0.55, 0.55]])}
  {mShift(16.4, 13.5, 1.15, M_GREEN)}
</>);
// the BONUS-TILE emblem — a color-tintable hex medallion with a white star. Used
// both in monastery #26 and (via `BonusTileBadge`) as the in-game color-bonus chip.
const mBonusTile = (cx, cy, k = 1, c = "#e0a526") => (
  <g transform={`translate(${cx} ${cy}) scale(${k})`}>
    <path d="M0 -3.9 L3.35 -1.95 L3.35 1.95 L0 3.9 L-3.35 1.95 L-3.35 -1.95 Z"
      fill={c} stroke="#2a1e0a" strokeWidth="0.8" />
    {mStar(0, 0.15, 2.5, "#2a1e0a")}
    {mStar(0, 0, 2.0, "#fff")}
  </g>
);
// the same emblem as a standalone badge (fills a 24-box svg), for the bonus bar.
function BonusTileBadge({ color, className, style }) {
  return (
    <svg viewBox="0 0 24 24" className={className}
      style={{ borderRadius: 0, boxShadow: "none", overflow: "visible", ...style }}>
      {mBonusTile(12, 12, 2.7, color)}
    </svg>
  );
}

const MONASTERY_ICON = {
  // ── continuous powers ──
  1: () => (<>{mHouse(8.4, 13, 1.2, "#8a6a3a")}{mHouse(15.2, 13, 1.2, "#6b4a2a")}</>),           // any # of same building/town
  2: () => (<>{mIcon("mine", 8, 11.6, 11)}{mNum(12.8, 6.7, 4.4, "+")}{mPawn(16.8, 11.9, 1.1)}{mNum(12.2, 19.6, 3.9, "A-E")}</>), // worker per mine, each phase (A-E)
  3: () => (<>{mBarrel(5.4, 13, 0.82)}{mArrowR(9.2, 13, 0.66)}{mCoin(15.0, 13, 0.82)}{mCoin(18.2, 13, 0.82)}</>), // sell goods -> 2 silver
  4: () => (<>{mBarrel(7, 13, 0.92)}{mArrowR(11.5, 13, 0.82)}{mPawn(16.6, 13, 1.05)}</>),          // sell goods -> worker
  5: () => (<>{mBarrel(3.8, 12.5, 0.72)}{mIcon("ship", 12, 11, 12)}{mBarrel(20.2, 12.5, 0.72)}</>), // ship also takes goods on either side
  6: () => (<>{mCoin(6.4, 13, 1.0)}{mArrowR(10.6, 13, 0.78)}{mPawn(15, 13, 1.0)}{mPawn(18.6, 13, 1.0)}</>), // 1 silver -> 2 workers
  7: () => (<>{mIcon("cow", 8.8, 13.2, 12)}<g transform="rotate(-35 15.8 11.5)">{mArrowR(15.8, 11.5, 0.7, M_INK)}</g>{mStar(18.2, 6.4, 3)}</>), // livestock scored -> +1 VP
  8: () => (<>{mDie(5.0, 13, 1.1, [[0, 0]])}{mShift(12, 13, 0.76)}{mDie(19.0, 13, 1.1, [[-0.62, -0.62], [0, 0], [0.62, 0.62]])}</>), // adjust die by 2 (1 <-> 3)
  // 9-11: die + a colored hex swatch of the tile type(s) the free shift applies to
  // 9-11 (PLACING): striped tile (top) + a worker LEFT of a down-pointing arrow (~70% size)
  9: () => (<><HexStriped cx={12} cy={10.2} k={1.2} colors={[TILE_HEX.beige]} />{mPawn(7.4, 17.3, 0.82)}{mArrowV(12, 17.3, 0.7, 1, M_GREEN)}</>),
  10: () => (<><HexStriped cx={12} cy={10.2} k={1.2} colors={[TILE_HEX.blue, TILE_HEX.green]} />{mPawn(7.4, 17.3, 0.82)}{mArrowV(12, 17.3, 0.7, 1, M_GREEN)}</>),
  11: () => (<><HexStriped cx={12} cy={10.2} k={1.2} colors={[TILE_HEX.burgundy, TILE_HEX.gray, TILE_HEX.yellow]} />{mPawn(7.4, 17.3, 0.82)}{mArrowV(12, 17.3, 0.7, 1, M_GREEN)}</>),
  // 12 (TAKING): striped tile (left) + a worker above a right-pointing arrow (~70% size)
  12: () => (<><HexStriped cx={7.5} cy={13} k={1.16} colors={[TILE_HEX.burgundy, TILE_HEX.blue, TILE_HEX.gray, TILE_HEX.green, TILE_HEX.beige, TILE_HEX.yellow]} />{mPawn(17.3, 7.4, 0.82)}{mArrowR(17.3, 13.2, 0.67, M_GREEN)}</>),
  13: () => (<>{mPawn(7.4, 13, 1.05)}{mPawn(10.9, 13, 1.05)}{mNum(14, 7.4, 4.2, "+")}{mCoin(17.2, 13, 1.08)}</>), // 2-workers action + 1 silver
  14: () => (<>{mPawn(5.6, 13, 0.92)}{mPawn(8.7, 13, 0.92)}{mNum(11.8, 7.4, 4.2, "+")}{mPawn(14.9, 13, 0.92)}{mPawn(18.0, 13, 0.92)}</>), // 2-workers action -> 4 (2 + 2)
  // ── end-game scoring ──
  15: () => (<>{mBarrel(7.2, 14, 0.82, GOODS_HEX.amber)}{mBarrel(12, 14, 0.82, GOODS_HEX.rose)}{mBarrel(16.8, 14, 0.82, GOODS_HEX.jade)}{mStar(18.4, 6.2, 2.7)}</>), // 2VP/goods type sold (goods #1/#2/#3 colors)
  16: () => (<>{mIcon("market", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  17: () => (<>{mIcon("watchtower", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  18: () => (<>{mIcon("carpenter", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  19: () => (<>{mIcon("church", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  20: () => (<>{mIcon("warehouse", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  21: () => (<>{mIcon("boarding", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  22: () => (<>{mIcon("bank", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  23: () => (<>{mIcon("townhall", 9.4, 12.4, 13)}{mStar(17.8, 6.8, 3)}</>),
  24: () => (<>{mIcon("cow", 8.2, 12.6, 11)}{mIcon("pig", 15.4, 13.4, 10)}{mStar(18.2, 6.2, 2.7)}</>), // 4VP/livestock type
  25: () => (<>{mBarrel(11, 13.4, 1.15, "#8a5a2a")}{mStar(17.8, 6.8, 3)}</>),                        // 1VP/goods sold
  26: () => (<>{mBonusTile(9.6, 12.6, 1.25, "#e0a526")}{mBonusTile(16.8, 15.6, 0.82, "#c56b8a")}{mStar(17.8, 6.6, 3)}</>), // 3VP per bonus tile owned
};

// A monastery tile's art: the benefit pictogram + a tiny corner id. Pure SVG
// children, so it drops into either a nested <svg> (HTML tiles) or a <g> (board).
function MonasteryArt({ id }) {
  const draw = MONASTERY_ICON[id];
  return (<>
    {draw ? draw() : mNum(12, 13, 9, String(id))}
    <text x="4.8" y="6.6" fontFamily="'Cinzel',serif" fontWeight="700" fontSize="5"
      fill={M_INK} fillOpacity="0.72">{id}</text>
  </>);
}

// What to draw inside a hex tile: an icon for ship/castle/mine, `count`-many animal
// icons for livestock, or the text glyph for monastery (#) / building (code). `px`
// is the hex's pixel size so the icon/glyph scale to the depot, storage, and board.
function TileArt({ tile, px = 70 }) {
  if (!tile) return null;
  const t = tile;
  if (t.type === "ship") return <Icon kind="ship" color="#f3ead8" size={px * 0.56} />;
  if (t.type === "castle") return <Icon kind="castle" color="#f3ead8" size={px * 0.54} />;
  if (t.type === "mine") return <Icon kind="mine" color="#f3ead8" size={px * 0.56} />;
  if (t.type === "building" && ICON[t.building]) return <Icon kind={t.building} color="#15100a" size={px * 0.6} />;
  if (t.type === "livestock" && ICON[t.animal]) {
    const n = t.count || 1;
    const each = n >= 4 ? px * 0.34 : n === 3 ? px * 0.36 : px * 0.42;
    return (
      <div className="coc-animals" style={{ maxWidth: px * 0.92, maxHeight: px * 0.82 }}>
        {Array.from({ length: n }).map((_, i) => (
          <Icon key={i} kind={t.animal} color="#15100a" size={each} />
        ))}
      </div>
    );
  }
  if (t.type === "monastery") return (
    <svg viewBox="0 0 24 24" width={px * 0.9} height={px * 0.9}
      style={{ display: "block", filter: "drop-shadow(0 1px 1px rgba(0,0,0,.4))" }}>
      <MonasteryArt id={t.effect_id} />
    </svg>
  );
  const g = tileGlyph(t);
  return g ? <span className="coc-glyph" style={{ fontSize: px * 0.27 }}>{g}</span> : null;
}

// SVG-native tile art for the duchy board (drawn straight into the hex SVG, so it
// renders reliably — the old <foreignObject> wrapper silently failed to paint).
// `box` is the art-box side in SVG user units; the icon is centered on (cx, cy).
const _ART_SHADOW = { filter: "drop-shadow(0 0.6px 0.6px rgba(0,0,0,.45))" };
function _artIcon(kind, color, cx, cy, s, key) {
  return (
    <g key={key} transform={`translate(${(cx - s / 2).toFixed(2)} ${(cy - s / 2).toFixed(2)}) scale(${(s / 24).toFixed(4)})`}>
      {ICON[kind](color)}
    </g>
  );
}
function TileArtSvg({ tile, cx, cy, box }) {
  if (!tile) return null;
  const t = tile;
  if (t.type === "ship") return <g style={_ART_SHADOW}>{_artIcon("ship", "#f3ead8", cx, cy, box * 0.56)}</g>;
  if (t.type === "castle") return <g style={_ART_SHADOW}>{_artIcon("castle", "#f3ead8", cx, cy, box * 0.54)}</g>;
  if (t.type === "mine") return <g style={_ART_SHADOW}>{_artIcon("mine", "#f3ead8", cx, cy, box * 0.56)}</g>;
  if (t.type === "building" && ICON[t.building]) return <g style={_ART_SHADOW}>{_artIcon(t.building, "#15100a", cx, cy, box * 0.6)}</g>;
  if (t.type === "livestock" && ICON[t.animal]) {
    const n = Math.min(t.count || 1, 4);
    const L = {
      1: { s: 0.56, pos: [[0, 0]] },
      2: { s: 0.46, pos: [[-0.55, 0], [0.55, 0]] },
      3: { s: 0.40, pos: [[-0.56, -0.5], [0.56, -0.5], [0, 0.52]] },
      4: { s: 0.36, pos: [[-0.56, -0.55], [0.56, -0.55], [-0.56, 0.55], [0.56, 0.55]] },
    }[n];
    const e = box * L.s;
    return <g style={_ART_SHADOW}>{L.pos.map(([ox, oy], i) => _artIcon(t.animal, "#15100a", cx + ox * e, cy + oy * e, e, i))}</g>;
  }
  if (t.type === "monastery") {
    const s = box * 0.9;
    return (
      <g style={_ART_SHADOW}
        transform={`translate(${(cx - s / 2).toFixed(2)} ${(cy - s / 2).toFixed(2)}) scale(${(s / 24).toFixed(4)})`}>
        <MonasteryArt id={t.effect_id} />
      </g>
    );
  }
  const g = tileGlyph(t);
  return g ? <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
    fontFamily="'Cinzel', serif" fontWeight="700" fontSize={(box * 0.42).toFixed(1)} fill="#15100a">{g}</text> : null;
}

function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }

// Hexagon-ring vertex positions (% of the board box) for the 6 numbered depots,
// depot 1 at top going clockwise; the black depot sits in the center. The four
// ring-SIDE depots (2/3/5/6) are narrow-and-tall (tiles stacked, goods below), so
// they need a wide vertical spread — and they don't use `left` at all: 5/6 hug the
// board's LEFT edge (same gutter as the turn-order track) and 2/3 mirror on the
// right (see coc-anchor-l/r). `left` here only steers each mini-die's inner edge.
const DEPOT_POS = [
  { left: 50, top: 12.1 },  // 1 top (raised ~5px so the black depot doesn't cover its die when goods pile up)
  { left: 83, top: 49 },    // 2 top-right — BOTTOM edge pinned just above board-center; grows UP
  { left: 83, top: 51 },    // 3 bottom-right — TOP edge pinned just below board-center; grows DOWN
  { left: 50, top: 88 },    // 4 bottom
  { left: 17, top: 51 },    // 5 bottom-left — TOP edge pinned just below board-center; grows DOWN
  { left: 17, top: 49 },    // 6 top-left — BOTTOM edge pinned just above board-center; grows UP
];

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
  // readyState of the live socket (0 CONNECTING / 1 OPEN / 2 CLOSING / 3 CLOSED / undefined
  // if none) — lets auto-reconnect avoid aborting a still-pending connection (a cold-starting
  // Render can hold the WS in CONNECTING until the service is up).
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// Relative timestamp for the lobby game lists (mirrors Spender's timeAgo).
function timeAgo(ts) {
  if (!ts) return "";
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// Die faces as dots/pips (1-6) instead of a numeral. Cells of a 3x3 grid:
//   1 2 3 / 4 5 6 / 7 8 9 . Scales with the die via % sizing, so it works for the
// big rolled dice, the white die, and the small depot mini-dice alike.
const PIP_MAP = { 1: [5], 2: [1, 9], 3: [1, 5, 9], 4: [1, 3, 7, 9], 5: [1, 3, 5, 7, 9], 6: [1, 3, 4, 6, 7, 9] };
function Pips({ n }) {
  const on = PIP_MAP[n];
  if (!on) return n;   // non-1..6 (shouldn't happen) — fall back to the numeral
  const set = new Set(on);
  return (
    <span className="coc-pips" aria-label={`die showing ${n}`}>
      {[1, 2, 3, 4, 5, 6, 7, 8, 9].map((i) => <span key={i} className={`coc-pip${set.has(i) ? " on" : ""}`} />)}
    </span>
  );
}

// ─── Styles ───────────────────────────────────────────────────────────────-
// lobbyCss is appended AFTER CoC's own styles (see the close of this template) so the
// shared .lby-* rules win the specificity TIE against CoC's `.coc *{margin:0;padding:0}`
// reset (both are one class) — otherwise the reset strips the kit's padding/margins.
const css = _cssText + lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss + rulesModalCss + waitingRoomCss;

// ─── Hex geometry ─────────────────────────────────────────────────────────────
const HEX_S = 26;
// Side of the square foreignObject that holds a placed tile's TileArt on the duchy
// board — sized to fit inside the hex (which is ~2*HEX_S tall, ~√3*HEX_S wide).
const HEX_ART = HEX_S * 1.4;
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

// A die value (1-6) as SVG pips centered in a duchy hex — replaces the numeral on
// empty spaces so the "die you need" reads as a die face (matches the dice + depot
// mini-dice). White dots with a thin dark rim so they show on any hex color.
function svgPips(cx, cy, n, key) {
  const on = PIP_MAP[n];
  if (!on) return null;
  const set = new Set(on);
  const g = HEX_S * 0.34, r = HEX_S * 0.12;
  const cell = { 1: [-g, -g], 2: [0, -g], 3: [g, -g], 4: [-g, 0], 5: [0, 0], 6: [g, 0], 7: [-g, g], 8: [0, g], 9: [g, g] };
  return [1, 2, 3, 4, 5, 6, 7, 8, 9].filter((i) => set.has(i)).map((i) => (
    <circle key={`${key}-p${i}`} cx={cx + cell[i][0]} cy={cy + cell[i][1]} r={r}
      fill="#fff" stroke="rgba(0,0,0,.55)" strokeWidth={0.7} />
  ));
}

// Fixed pixel size for the CSS clip-path hex tiles on the shared board (depots +
// black depot) and in the storage row, so they read at the same scale as the
// duchy hexes and stay constant across every board. KEEP IN SYNC with the
// `.coc-tile` / `.coc-stt` width/height in the stylesheet below.
// On-board / storage hex tiles. The box is NOT square: a regular pointy-top hex
// has width:height = √3:2, so height = width * 2/√3. With that ratio the
// clip-path renders a true (un-squished) hexagon matching the duchy hexes.
// KEEP IN SYNC with `.coc-tile` / `.coc-stt` width/height in the stylesheet.
const HEX_W = 70;
const HEX_H = 81;   // ≈ 70 * 2/√3
// Central black depot: a 2-column grid, rows = player count (4/6/8 tiles at 2/3/4p).
// BLACK_GAP separates the tiles; BLACK_PAD is the breathing room to the box border.
const BLACK_GAP = 6;
const BLACK_PAD = 9;

// A small selectable thumbnail of one board's hex layout (lobby board picker).
function BoardThumb({ spaces, name, selected, onClick }) {
  const sids = Object.keys(spaces || {});
  if (!sids.length) return null;
  let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
  const centers = {};
  for (const sid of sids) {
    const sp = spaces[sid];
    const c = hexCenter(sp.q, sp.r);
    centers[sid] = c;
    minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
    minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
  }
  const pad = HEX_S + 2;
  const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;
  return (
    <button type="button" className={`coc-bthumb${selected ? " sel" : ""}`} onClick={onClick} title={name}>
      <svg viewBox={vb} className="coc-bthumb-svg" preserveAspectRatio="xMidYMid meet">
        {sids.map((sid) => {
          const sp = spaces[sid];
          const c = centers[sid];
          return <polygon key={sid} points={hexPoints(c.x, c.y, HEX_S - 1.2)}
            fill={TILE_HEX[sp.color] || "#444"} stroke="rgba(0,0,0,.45)" strokeWidth={0.8} />;
        })}
      </svg>
      <span className="coc-bthumb-name">{name}</span>
    </button>
  );
}

// The tiers the create modal OFFERS. `main.AI_DIFFICULTIES` also carries
// "normal", which the picker has never shown — so this list, not that tuple, is
// what a remembered last-played tier is validated against.
const AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "A capable search opponent — a solid game without neural-net strength" },
  { value: "hard", label: "Hard", title: "The first-generation neural net, searched in your browser — a real challenge" },
  { value: "expert", label: "Expert", title: "The strongest neural net, searched in your browser" },
];
const AI_TIER_IDS = AI_TIER_OPTIONS.map((t) => t.value);
// id -> the words a player sees, off the same list the picker renders — what
// `LobbyBotTier` prints on the Active and History rows. A retired tier still
// sitting on an old saved game falls through to its raw id rather than to a
// blank, which is the honest read: the row is reporting what was played.
const AI_TIER_LABELS = Object.fromEntries(AI_TIER_OPTIONS.map((t) => [t.value, t.label]));

export default function CastlesOfCrimson({ myId, authUser, onExit, offline = null }) {
  const [board, setBoard] = useState(() => {           // {spaces, colors, castle, ...} — hydrated from cache
    try { const c = localStorage.getItem(COC_BOARDS_CACHE); if (c) return boardsWithById(JSON.parse(c)); } catch {}
    return null;
  });
  const [screen, setScreen] = useState("lobby");        // lobby | waiting | game
  // Instant feedback while the WS connects + the first room state arrives (~1 RTT +
  // a DB load): the screen otherwise stays frozen on the lobby, so clicking Resume/
  // Join/Create feels like a dead half-second. Set true on click, cleared the moment
  // authoritative state (or an error) lands; a timeout drops it so it can't hang.
  const [connecting, setConnecting] = useState(false);
  const connectTimer = useRef(null);
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const optimisticRef = useRef(false);          // a move preview is showing (awaiting the server's truth)
  const preOptimisticRoomRef = useRef(null);    // last authoritative room, to revert to if the previewed move errors
  const [openGames, setOpenGames] = useState(() => readLobbyCache("coc", myId, "open", []));
  const [activeGames, setActiveGames] = useState(() => readLobbyCache("coc", myId, "active", []));   // ALL in-progress games (yours + others')
  const [history, setHistory] = useState(() => readLobbyCache("coc", myId, "history", []));           // your finished games (lobby History column)
  // ...revealed 10 at a time as the reader reaches the end, up to the 50 the
  // backend sends — see useProgressiveList.
  const [historyShown, historyMore] = useProgressiveList(history);
  // A column that scrolls inside itself must say so — see `useListFade`.
  useListFade();
  // CoC was the only three-column lobby with no phone tab bar — the sections
  // just stacked. Now the shared one, same as the other three.
  const [lobbyTab, setLobbyTab] = useState("open");
  const [reviewOnly, setReviewOnly] = useState(false);  // HTTP-loaded finished-game review (no WS)
  const [loadingGames, setLoadingGames] = useState(false);
  const [toast, setToast] = useState("");
  const [reviewing, setReviewing] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);   // socket dropped mid-game, retrying
  const [showCreateModal, setShowCreateModal] = useState(false);  // the New Game options modal
  const [createOpp, setCreateOpp] = useState("ai");               // "friend" | "ai"
  // AI difficulty (easy|hard|expert) — the tier this player last actually
  // played, Expert until they have one.
  const [createDiff, setCreateDiff, rememberDiff] =
    useLastDifficulty("coc", myId, AI_TIER_IDS, "expert");
  const [createSeats, setCreateSeats] = useState(2);              // VS-Friend seat cap (2-4)
  const [createSameBoard, setCreateSameBoard] = useState(false);  // VS-Friend: force everyone onto the host's board
  const [joinBoardFor, setJoinBoardFor] = useState(null);         // room id pending a board pick before join
  const [showRules, setShowRules] = useState(false);            // lobby "How to Play" modal

  // interaction state
  const [selDie, setSelDie] = useState(null);
  const [selStorage, setSelStorage] = useState(null);
  const [silverArmed, setSilverArmed] = useState(false);  // black-depot buy: armed via the silver token
  const [actedThisTurn, setActedThisTurn] = useState(false);  // did I take any action this turn? (gates Undo)
  const [extraValue, setExtraValue] = useState(null);
  const [showScores, setShowScores] = useState(false);   // mid-game VP breakdown popup
  const [viewOppId, setViewOppId] = useState(null);      // which opponent's board is shown (3-4p peek tabs)
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [myBoard, setMyBoard] = useState("1");          // board the local player picked
  const [oppBoard, setOppBoard] = useState("1");        // board chosen for the bot (vs-AI)
  const [flyers, setFlyers] = useState([]);             // tile-move animations (depot->storage, storage->duchy)
  const [phasePop, setPhasePop] = useState(null);       // {from,to,silver,workers} — the between-phase overlay
  const animSnap = useRef(null);                        // prev snapshot for diffing my tile moves
  const flyerSeq = useRef(0);
  const reconnTimer = useRef(null);                     // auto-reconnect backoff timer
  const reconnTries = useRef(0);
  const turnSimsRef = useRef(0);                         // client-AI sims accumulated across the bot's turn
  const prevAiSimRef = useRef(false);                    // edge-detect the bot turn for the per-turn sim log
  const prevPhaseRef = useRef(null);                    // last phase_letter seen (detect a phase advance)
  const phasePopTimer = useRef(null);                   // auto-dismiss timer for the phase overlay
  const boardHexRef = useRef(null);                     // the depot ring — sized to fit its tiles (3-4p need more height)

  // ── URL routing (segment 2 = room id; the shell owns segment 1 = "/coc") ──
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const urlAttemptRef = useRef(null);   // {rid, retried} — a URL-driven room attempt in flight
  const didInitRef = useRef(false);     // StrictMode double-mount guard for the deep-entry effect
  const popHandlerRef = useRef(() => {}); // fresh-closure mirror for the mount-once popstate effect

  const playerName = authUser?.name || "Player";

  // ── Offline vs-AI mode ──────────────────────────────────────────────────
  // Mounted by the shell with `offline` = the saved-game record: no socket at all,
  // moves apply through the local wasm engine (offline.js), and the EXISTING search
  // loop below plays the bot from a driver-synthesized ai_search. The shell owns the
  // URL (/offline/<id>), so the /coc deep-entry + popstate effects are gated off.
  const offlineRef = useRef(offline);
  offlineRef.current = offline;
  const offlineRecRef = useRef(null);              // the LIVE record (mutated by the driver)
  const offlineTokenRef = useRef(0);               // bumps on unmount/exit → cancels stale bot loops
  const publishOffline = useCallback(async (rec, aiSearch) => {
    offlineRecRef.current = rec;
    const rd = await cocOfflineRoomData(rec, myId, authUser?.name);
    if (aiSearch) rd.ai_search = aiSearch;
    setRoomData(rd);
    return rd;
  }, [myId, authUser?.name]);
  const kickOfflineBot = useCallback(() => {
    const token = offlineTokenRef.current;
    const rec = offlineRecRef.current;
    if (!rec) return;
    runCocBotLoop(rec, myId, publishOffline, () => offlineTokenRef.current === token)
      .catch((e) => console.debug("[coc offline-AI] bot loop:", e));
  }, [myId, publishOffline]);
  useEffect(() => {
    if (!offline) return;
    let live = true;
    (async () => {
      try {
        // The prop may be a record or a saved id (shell resume passes the record).
        const rec = typeof offline === "string" ? await loadOfflineCocGame(offline) : offline;
        if (!rec || !live) return;
        await armCocUndoIfMyTurn(rec);
        setRoomId(rec.id);
        // roomData BEFORE the screen flip: the game-screen render assumes `game`
        // exists (the online flow sets both from one message; a "game" screen with
        // null roomData crashes on the first unguarded game.* read).
        await publishOffline(rec, null);
        if (!live) return;
        setScreen("game");
        kickOfflineBot();
      } catch (e) {
        setToast(String(e?.message || "Couldn't open the offline game"));
      }
    })();
    return () => { live = false; offlineTokenRef.current += 1; };
  }, [offline]); // eslint-disable-line react-hooks/exhaustive-deps
  // The die value needed to sell a goods color (its index in the goods order + 1).
  const goodsSellNum = (color) => (board ? board.goods_colors.indexOf(color) + 1 : 0);
  // Description shown when the face-down "sold goods" pile is clicked/hovered.
  const soldGoodsDesc = (n) => `Sold ${n} good${n === 1 ? "" : "s"} this game.`;

  // ── derived ──
  const game = roomData?.game;
  const players = roomData?.players || {};

  // The depot ring is absolutely-positioned (each depot pinned by % of the board-hex height),
  // so the board-hex height doesn't grow with its content. With 3-4 players the side depots
  // hold 3-4 stacked tiles (vs 2) and overflow the board — spilling into the turn-order track
  // above and off the bottom. Measure each depot and set a min-height (--coc-board-minh) that
  // guarantees every depot fits within [0, H] given its center-fraction + pin type, so the
  // board always extends to hold everything. Content-sized depot heights are independent of H,
  // so one pass converges (no loop). 3-col desktop only (below 1280 the depots reflow in-flow).
  useLayoutEffect(() => {
    const compute = () => {
      const bh = boardHexRef.current;
      if (!bh) return;
      const col0 = bh.closest(".coc-col-board");
      const area0 = document.querySelector(".coc-duchy-area");
      if (window.innerWidth < 1280) {
        bh.style.removeProperty("--coc-board-minh");
        bh.style.removeProperty("--coc-board-cap");
        if (col0) col0.style.height = "";   // clear the desktop height-sync below 1280
        if (area0) area0.style.height = "";
        document.querySelectorAll(".coc-storage").forEach((s) => { s.style.zoom = ""; });
        return;
      }
      const zoom = parseFloat(getComputedStyle(bh).zoom) || 1;
      // How much height this WINDOW actually has for the two columns — so the CSS floor
      // (38vw, a HEIGHT derived from the viewport's WIDTH) can't ask for room the window
      // hasn't got and scroll the page for it.  Everything else is stacked above the
      // columns (top bar, status bar) or is the wrap's bottom padding, and NONE of it
      // moves when the columns resize, so measuring it is board-independent and one pass
      // converges — the same property the depot measure below relies on.  Measured, not
      // assumed: a hand-totalled constant was 6px short here, which is exactly the size
      // of scrollbar this whole measure exists to avoid.
      const wrapEl = bh.closest(".coc-wrap-game");
      const colsEl = bh.closest(".coc-game-cols");
      let availCols = Infinity, header = 0;
      if (wrapEl && colsEl && col0) {
        const wr = wrapEl.getBoundingClientRect(), cr = colsEl.getBoundingClientRect();
        availCols = window.innerHeight - (cr.top - wr.top) - (wr.bottom - cr.bottom) - 2;
        header = col0.getBoundingClientRect().height - bh.getBoundingClientRect().height;
        // The board's share of that: the column minus its phase/turn-order header. A
        // CEILING on the aesthetic size only — `--coc-board-minh` beats it through the
        // CSS max(), so a depot ring that genuinely needs more height still gets it (and
        // then the page scrolls, correctly).
        bh.style.setProperty("--coc-board-cap",
          `${Math.max(0, Math.floor((availCols - header) / zoom))}px`);
      }
      // The central black depot is centered (f=0.5) and grows with player count (2/3/4 rows).
      // At 4p it's tall enough to collide with the top/bottom depots' mini-dice (which point
      // inward toward the center), so it becomes a real height constraint — measure it.
      const blackEl = bh.querySelector("[data-blackdepot]");
      const blackH = blackEl ? blackEl.getBoundingClientRect().height : 0;
      let needScreen = 0;
      bh.querySelectorAll("[data-depot]").forEach((el) => {
        const idx = ["1", "2", "3", "4", "5", "6"].indexOf(el.getAttribute("data-depot"));
        if (idx < 0) return;
        const f = DEPOT_POS[idx].top / 100;          // center-fraction of the board height
        const r = el.getBoundingClientRect();
        const h = r.height;                           // rendered (screen) px, content-driven
        const isSide = idx !== 0 && idx !== 3;
        // tb depots (1/4) are centered on the point (translate -50% -> half-height each side);
        // side depots pin their inner edge at the point and grow OUTWARD by their full height
        // (topside -100%, bottomside 0). Exact-fit: the near edge just reaches [0, H]. Any
        // per-edge margin is amplified 1/f (~8x near the bottom depot at f=.88), so we keep it
        // exact + a small final buffer; goods growth is caught by re-measuring on every change.
        const reach = isSide ? h : h / 2;            // distance the depot extends past its point
        const outward = f < 0.5 ? f : (1 - f);       // fraction of H between the point and the near edge
        needScreen = Math.max(needScreen, reach / outward);
        // tb-depot die (points inward) must clear the black depot: the die's inner edge sits a
        // FIXED px offset k from the depot center (f·H), so H(|0.5-f|) >= blackH/2 + k + margin.
        if (!isSide && blackH) {
          const die = el.querySelector(".coc-minidie");
          if (die) {
            const dr = die.getBoundingClientRect();
            const center = (r.top + r.bottom) / 2;
            const k = idx === 0 ? (dr.bottom - center) : (center - dr.top);
            needScreen = Math.max(needScreen, (blackH / 2 + k + 8) / Math.abs(0.5 - f));
          }
        }
      });
      // needScreen is post-zoom; min-height is set in the element's own (pre-zoom) px.
      bh.style.setProperty("--coc-board-minh", needScreen ? `${Math.ceil(needScreen / zoom) + 10}px` : "0px");

      // Pin the duchy-area to the board column's natural (depot-driven) height so the LOG
      // fills beneath the duchies and SCROLLS — the board never stretches to the log's
      // length. Reset both to natural, measure the board (flex-start ⇒ the log can't inflate
      // it) and the duchy row (log excluded), then set both to the same target.
      const row = document.querySelector(".coc-duchy-row");
      if (col0 && area0 && row) {
        col0.style.height = ""; area0.style.height = "";
        const boardNat = col0.getBoundingClientRect().height;
        const rowH = row.getBoundingClientRect().height;
        // The LOG's floor is what's left of the window, not a constant. 130px of log is
        // what we WANT under the duchies; on a short window (a 2560x1600 panel at 150% OS
        // scaling is ~940 CSS px tall) demanding it unconditionally is what pushed the
        // page past the viewport by a few dozen px — a page scrollbar to protect log rows
        // that scroll internally anyway. So the log gives its space back down to 60px
        // before the page starts scrolling; below that the duchy row itself is the floor
        // and the page scrolls, correctly.
        const logH = Math.max(60, Math.min(130, Math.round(availCols - rowH - 16)));
        const target = Math.max(Math.round(boardNat), Math.ceil(rowH) + logH + 16);
        col0.style.height = `${target}px`;
        area0.style.height = `${target}px`;
      }

      // Storage tiles are a fixed 70px (icons sized in fixed px), so at narrower 3-col widths
      // the 3 storage tiles + the fixed-width goods box don't both fit the duchy row and the
      // goods box wraps below. Zoom the storage down to fill the space left beside the goods
      // box so they stay on one row (caps at 1 — full size once there's room, e.g. ~1920+).
      document.querySelectorAll(".coc-stor-goods").forEach((sg) => {
        const storage = sg.querySelector(".coc-storage");
        const goods = sg.querySelector(".coc-goods-row");
        if (!storage || !goods) return;
        storage.style.zoom = "";                                   // reset to measure natural width
        const natW = storage.getBoundingClientRect().width;
        const avail = sg.getBoundingClientRect().width - goods.getBoundingClientRect().width - 14 - 4;
        if (natW > avail && avail > 0) storage.style.zoom = String(Math.max(0.4, avail / natW));
      });
    };
    compute();
    window.addEventListener("resize", compute);
    return () => window.removeEventListener("resize", compute);
  }, [game]);
  // All opponents in seat order (2-4 players). `oppId` is the ONE currently shown in the
  // opponent column — the peek-tab selection (or, by default, whoever is acting), so the
  // rest of the render (renderDuchy, dice, flyers) stays single-opponent.
  const opponentIds = (game?.order || Object.keys(players)).filter((p) => p !== myId);
  const oppId = opponentIds.includes(viewOppId) ? viewOppId : opponentIds[0];
  const me = game?.players?.[myId];
  const opp = oppId ? game?.players?.[oppId] : null;
  const over = game?.phase === "over";
  const fscore = roomData?.final_scores;   // final VP incl. end-of-game bonuses (shown when over)
  const pendingMine = game && game.pending_pid === myId;
  const myTurnRaw = game && !over && (game.pending_pid ? game.pending_pid === myId : game.turn === myId);
  const aiThinking = game && roomData?.vs_ai && !over &&
    (game.pending_pid || game.turn) === roomData?.ai_player;
  // Setup phase: each player places a starting castle on a crimson (castle) space before
  // dice are rolled. `setupMine` = it's my turn to choose.
  const setupPhase = !!game && game.phase === "setup";
  const setupMine = setupPhase && !over && game.turn === myId;
  // Monastery #6: on your turn, spend 1 silver to gain 2 workers (unlimited uses).
  // Atomic — click the workers token to do it (no target). Mirrors the engine gate.
  const canUseM6 = !!me && myTurnRaw && !pendingMine
    && (me.monastery_effects || []).includes(6)
    && (me.silver || 0) >= 1;
  // Black-depot buy: on your turn, spend 2 silver to take a tile from the central depot.
  // Usable once/turn, needs >=2 silver + a free storage slot + a tile in the black depot.
  const canBuyBlack = !!me && myTurnRaw && !pendingMine
    && !game.black_depot_used_this_turn && (me.silver || 0) >= 2 && (me.storage?.length || 0) < 3
    && (game.black_depot?.length || 0) > 0;
  // Take 2 workers = select a die, then click the workers token (replaces the old
  // "Take 2 Workers" button). Takes priority over arming Monastery #6 while a die
  // is selected — deselect the die to arm #6 instead.
  const canTakeWorkers = !!me && myTurnRaw && !pendingMine && selDie != null
    && !!game.dice?.[myId] && !game.dice[myId].used[selDie];

  // ── socket ──
  const handleMessage = useCallback((msg) => {
    if (msg.type === "error") {
      // Revert an optimistic preview the server rejected, so a bad guess doesn't linger.
      if (optimisticRef.current && preOptimisticRoomRef.current) setRoomData(preOptimisticRoomRef.current);
      optimisticRef.current = false;
      setConnecting(false);                                 // a connect that errored drops back to the lobby
      // A URL-driven room attempt (deep link / popstate) failed. A stale token gets ONE
      // retry as a plain join (invite-link case); anything else falls back to the lobby
      // and the dead room URL is replaced with /coc so a reload doesn't re-attempt it.
      const ua = urlAttemptRef.current;
      if (ua) {
        if (msg.message === "invalid token" && !ua.retried) {
          ua.retried = true;
          try { localStorage.removeItem(`coc_token_${ua.rid}_${myId}`); } catch {}
          resume(ua.rid);   // token now gone → plain join
          return;
        }
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("coc_roomId") === ua.rid) localStorage.removeItem("coc_roomId");
          localStorage.removeItem(`coc_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("coc"));
      }
      setToast(msg.message || "error"); return;
    }
    const room = msg.room;
    if (!room) return;
    setConnecting(false);                                   // authoritative state arrived — hide the connect loader
    optimisticRef.current = false;                        // authoritative state arrived — reconcile below
    const tok = room.reconnect_tokens?.[myId];
    const rid = room.room_id || roomId;
    if (tok) { try { localStorage.setItem(`coc_token_${rid}_${myId}`, tok); localStorage.setItem("coc_roomId", rid); } catch {} }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      // Entering the room gives it its URL (waiting + game share it; dedup makes
      // deep-link/repeat messages no-ops). Server-confirmed, never at click time.
      if (rid) pushPath(buildPath("coc", rid));
      urlAttemptRef.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update") {
      if (inGame && screen !== "game") setScreen("game");
    }
  }, [myId, roomId, screen]); // eslint-disable-line react-hooks/exhaustive-deps

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  // fetch every selectable board layout once (shared meta + per-board spaces). The state
  // is pre-hydrated from cache above, so this is a background refresh — it won't block
  // the lobby/game render on a cold cache-miss either (LobbyLoading covers that).
  useEffect(() => {
    fetch(`${COC_HTTP}/boards`).then((r) => r.json()).then((d) => {
      if (!d.ok) return;
      setBoard(boardsWithById(d));
      try { localStorage.setItem(COC_BOARDS_CACHE, JSON.stringify(d)); } catch {}
    }).catch(() => {});
  }, []);

  // Safety: never leave the connect loader spinning forever — if the first room state
  // hasn't arrived within the window (dead socket / cold-start that never wakes), drop
  // back to the lobby with a hint. handleMessage clears `connecting` on success/error.
  useEffect(() => {
    if (!connecting) { if (connectTimer.current) { clearTimeout(connectTimer.current); connectTimer.current = null; } return; }
    connectTimer.current = setTimeout(() => {
      setConnecting(false);
      setToast("Still connecting… the server may be waking up. Try again in a moment.");
    }, 15000);
    return () => { if (connectTimer.current) { clearTimeout(connectTimer.current); connectTimer.current = null; } };
  }, [connecting]);

  // Resolve the hex layout for a given board id (falls back to the default board).
  const boardSpaces = useCallback((boardId) => {
    const by = board?.byId || {};
    return (by[boardId] || by[board?.default_board] || {}).spaces || {};
  }, [board]);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${COC_HTTP}/games`).then((r) => r.json()).then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("coc", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    // Active Games is PUBLIC: all in-progress games (yours + others', vs-bot or not).
    // The frontend pins yours to the top via myId. No auth needed.
    fetch(`${COC_HTTP}/games/active`).then((r) => r.json()).then((d) => { const g = d.games || []; setActiveGames(g); writeLobbyCache("coc", myId, "active", g); }).catch(() => {});
    // History = your finished games (session-gated). Guests have none.
    if (authUser?.session_token) {
      fetchGameHistory(`${COC_HTTP}/games/history`, authUser).then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("coc", myId, "history", g); }).catch(() => {});
    } else {
      setHistory([]); writeLobbyCache("coc", myId, "history", []);
    }
  }, [authUser, myId]);

  // Load + show a finished game's board + results, read-only over HTTP (no WebSocket).
  const enterCocReview = (id) => {
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    fetch(`${COC_HTTP}/games/${id}/review?player_id=${encodeURIComponent(myId)}`, { headers }).then((r) => r.json()).then((d) => {
      if (!d.ok) { setToast(d.message || "Could not load review"); return; }
      setRoomData({
        game: d.game, players: d.players || {}, host: null, status: "over",
        vs_ai: false, ai_player: null,
        final_scores: d.final_scores || {}, vp_breakdown: d.vp_breakdown || {},
      });
      setReviewOnly(true);
      setReviewing(false);   // land on the results page first (Review Board is one click away)
      setRoomId(id);
      setScreen("game");
    }).catch(() => setToast("Could not load review"));
  };

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  // The game you just finished leaves Active and joins History the moment it
  // ENDS, not when the lobby next loads — see useFinishedGameSync (shared kit).
  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("coc", myId, "active", rid, setActiveGames);
    fetchGames();
  });

  // Mount: do NOT auto-resume a saved game — it snapped you from the lobby into the game
  // on load (jarring). Resume is EXPLICIT via the lobby's Resume button. Keep only the
  // disconnect cleanup so an explicit connection tears down on unmount. (A room id IN THE
  // URL is different — that's an explicit destination; see the deep-entry effect below.)
  useEffect(() => {
    return () => disconnect();
  }, []); // eslint-disable-line

  // ── URL deep entry + popstate (this component owns "/coc/<ROOMID>") ──
  // Mount with a room in the URL → the EXISTING resume semantics (saved token →
  // reconnect, else join — exactly the invite-link behavior). A plain /coc mounts at
  // the lobby exactly as before.
  // URL-driven room entry: clear any read-only review state first (a popstate Forward can
  // fire while reviewOnly is set — resume() alone would leave it stale and the reconnect
  // loop gated off), then run the existing resume semantics.
  const urlResume = (rid) => {
    setReviewOnly(false); setReviewing(false);
    urlAttemptRef.current = { rid, retried: false };
    resume(rid);
  };
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    if (offlineRef.current) return;   // offline: the shell owns the URL (/offline/<id>)
    const r = parsePath();
    if (r.game === "coc" && r.room) urlResume(r.room);
  }, []); // eslint-disable-line
  // Back/Forward while mounted: only our own segment 2 — mode changes unmount us via the
  // shell (whose unmount cleanup disconnects). Routed through a ref so the mount-once
  // subscription never runs a stale closure.
  popHandlerRef.current = (r) => {
    if (offlineRef.current) return;   // offline popstate is the shell's (mode "offline")
    if (r.game !== "coc") return;
    if (r.room && r.room !== roomIdRef.current) {
      urlResume(r.room);
    } else if (!r.room && (roomIdRef.current || urlAttemptRef.current)) {
      // Back out of the room — INCLUDING out of a still-connecting attempt (popping
      // during the join's round trip would otherwise let the late "reconnected"
      // message push the room URL right back). leaveToLobby's disconnect kills the
      // in-flight socket; its pushPath dedups (URL is already /coc after the pop).
      urlAttemptRef.current = null;
      leaveToLobby();
    }
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // Auto-reconnect: if the socket drops while in a LIVE game (Render cold start, a
  // network blip, or iOS killing a backgrounded WS), keep retrying with backoff —
  // through the ~30-50s a cold start takes — until we're back. This is load-bearing
  // for vs-bot games: a bot's turn is only re-driven when our client reconnects
  // (`_handle_reconnect` re-triggers the server scheduler), so WITHOUT this the bot's
  // turn freezes until a manual refresh (the "hung for minutes" bug). Reconnect uses
  // the `reconnect` action (NOT `join`) so the backend actually resumes the bot.
  const inLiveGame = !offline && !!roomId && !reviewOnly
    && (screen === "game" || screen === "waiting") && roomData?.status !== "over";
  // One reconnect attempt that reschedules itself — shared by the backoff loop AND the
  // tab-focus nudge, so neither can leave the loop dead by clearing the other's timer.
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) {                          // CONNECTING/OPEN — don't abort it, re-check
      reconnTimer.current = setTimeout(attemptReconnect, 3000);
      return;
    }
    let tok = null;
    try { tok = localStorage.getItem(`coc_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${COC_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    // 2s, 4s, 6s … capped at 8s — retries indefinitely until connected (or we leave).
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);

  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear();
      reconnTries.current = 0;
      if (connected) setReconnecting(false);             // no-op re-render if already false
      return;
    }
    if (!reconnTimer.current) attemptReconnect();        // start the loop if it isn't running
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  // Tab back into focus (iOS often kills a backgrounded socket without firing onclose):
  // fire an immediate attempt instead of waiting out the backoff.
  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || connected || !inLiveGame) return;
      reconnTries.current = 0;
      attemptReconnect();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2400); return () => clearTimeout(t); } }, [toast]);

  // clear selection at the start of a fresh decision
  useEffect(() => { setSelDie(null); setSelStorage(null); setExtraValue(null); }, [game?.turn, game?.round, game?.pending_kind]);
  // Disarm Monastery #6 the moment it's no longer usable (turn ended, used, storage full…).
  // Same for the silver / black-depot buy.
  useEffect(() => { if (!canBuyBlack) setSilverArmed(false); }, [canBuyBlack]);
  // "acted this turn" resets only when the turn itself changes (NOT on pending
  // open/close, since opening a pending means you already acted).
  useEffect(() => { setActedThisTurn(false); }, [game?.turn, game?.round, game?.phase_letter]);
  // Peek tabs (3-4p): auto-follow whichever opponent is currently acting, so you watch
  // the live player's board. On YOUR turn it keeps the last-viewed opponent. Manual tab
  // clicks still work; they just get re-followed when the next opponent starts a turn.
  useEffect(() => {
    const actor = game?.pending_pid || game?.turn;
    if (game && !over && actor && actor !== myId
        && (game.order || Object.keys(players)).includes(actor)) setViewOppId(actor);
  }, [game?.turn, game?.pending_pid]);  // eslint-disable-line react-hooks/exhaustive-deps
  // NOTE: the old View-Opponent modal (auto-open on the bot's turn + the setup-castle
  // reveal choreography) is GONE — the opponent's duchy is now permanently on screen
  // beside yours, so the generic flyer diff below animates their moves (including the
  // starting-castle pop-in, via its popIn fallback) with no modal to orchestrate.

  // Tile-move animations: diff MY storage/duchy each update and fly the moved tile
  // from where it was (depot / black depot / storage) to its new home. Mirrors
  // Spender's flying overlay; uses persistent data-* anchors in the live DOM.
  useEffect(() => {
    if (!game || !me) { animSnap.current = null; return; }
    const loc = {};
    for (const d of [1, 2, 3, 4, 5, 6]) (game.depots?.[String(d)]?.hexes || []).forEach((t) => { loc[t.id] = { kind: "depot", d }; });
    (game.black_depot || []).forEach((t) => { loc[t.id] = { kind: "black" }; });
    (me.storage || []).forEach((t) => { loc[t.id] = { kind: "storage" }; });
    const storageIds = new Set((me.storage || []).map((t) => t.id));
    const duchyIds = new Set(Object.values(me.duchy || {}).filter(Boolean).map((t) => t.id));
    const depotGoods = [];
    for (const d of [1, 2, 3, 4, 5, 6]) (game.depots?.[String(d)]?.goods || []).forEach((g) => depotGoods.push({ id: g.id, color: g.color, d }));
    const myGoods = { ...(me.goods || {}) };
    // The opponent's board is permanently rendered beside yours, so their moves
    // animate directly on it (depot -> their storage slot / duchy hex, goods into
    // their goods row) — same diff as for your own board.
    const oId = oppId;                                   // the opponent currently shown (peek-tab selection)
    const oPlayer = oId ? game.players[oId] : null;
    const oppLoc = {};   // opponent tile id -> where it sits on THEIR board
    (oPlayer?.storage || []).forEach((t, i) => { if (t) oppLoc[t.id] = { kind: "oppslot", i }; });
    Object.entries(oPlayer?.duchy || {}).forEach(([sid, t]) => { if (t) oppLoc[t.id] = { kind: "oppsid", sid }; });
    const oppStorageIds = new Set((oPlayer?.storage || []).filter(Boolean).map((t) => t.id));
    const oppDuchyIds = new Set(Object.values(oPlayer?.duchy || {}).filter(Boolean).map((t) => t.id));
    const oppGoods = { ...(oPlayer?.goods || {}) };
    const prev = animSnap.current;
    animSnap.current = { loc, storageIds, duchyIds, depotGoods, myGoods, oppLoc, oppStorageIds, oppDuchyIds, oppGoods,
      workers: me.workers, silver: me.silver, oppWorkers: oPlayer?.workers, oppSilver: oPlayer?.silver, oppId: oId };
    if (!prev) return;                                  // first paint: nothing to animate
    // When the peek tab switches opponents, the snapshot's opp portion is a different
    // player — skip opponent flyers this frame (else all the new opponent's tiles animate
    // in as if just placed). Your own board still animates normally.
    const oppChanged = prev.oppId !== oId;
    const rectOf = (spec) => {
      if (!spec) return null;
      const sel = spec.kind === "depot" ? `[data-depot="${spec.d}"]`
        : spec.kind === "black" ? "[data-blackdepot]"
        : spec.kind === "storage" ? "[data-storage]"
        : spec.kind === "slot" ? `[data-storage-slot="${spec.i}"]`
        : spec.kind === "hex" ? `[data-sid="${spec.sid}"]`
        : spec.kind === "mygoods" ? "[data-mygoods]"
        : spec.kind === "goodsleft" ? "[data-goodsleft]"
        : spec.kind === "depotgood" ? `[data-depotgood="${spec.id}"]`
        : spec.kind === "goodchip" ? `[data-goodchip="${spec.c}"]`
        : spec.kind === "oppgoodchip" ? `[data-oppgoodchip="${spec.c}"]`
        : spec.kind === "oppslot" ? `[data-oppstorage-slot="${spec.i}"]`
        : spec.kind === "oppsid" ? `[data-oppsid="${spec.sid}"]`
        : spec.kind === "oppgoods" ? "[data-oppgoods]" : null;
      const el = sel && document.querySelector(sel);
      return el ? el.getBoundingClientRect() : null;
    };
    const mk = (tile, src, dest) => {
      const s = rectOf(src), d = rectOf(dest);
      if (!s || !d) return null;
      const W = 58, H = 67;
      const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
      const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
      const s1 = (dest.kind === "hex" || dest.kind === "oppsid") ? Math.max(0.5, Math.min(1, d.width / W)) : 1;
      return { id: `f${flyerSeq.current++}`, tile, left: scx - W / 2, top: scy - H / 2, w: W, h: H, dx: dcx - scx, dy: dcy - scy, s1 };
    };
    // A placement with no source (a starting castle isn't drawn from a depot/storage) —
    // "pop" it IN at the destination hex (scale up in place) so it still animates.
    const popIn = (tile, dest) => {
      const d = rectOf(dest);
      if (!d) return null;
      const W = 58, H = 67;
      const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
      const s1 = (dest.kind === "hex" || dest.kind === "oppsid") ? Math.max(0.5, Math.min(1, d.width / W)) : 1;
      return { id: `f${flyerSeq.current++}`, tile, left: dcx - W / 2, top: dcy - H / 2, w: W, h: H, dx: 0, dy: 0, s0: 0.2, s1 };
    };
    const add = [];
    const storage = me.storage || [];
    for (let i = 0; i < storage.length; i++) {
      const t = storage[i];
      if (prev.storageIds.has(t.id)) continue;          // newly in storage = took / bought
      const f = mk(t, prev.loc[t.id], { kind: "slot", i });   // fly to the exact slot it landed in
      if (f) add.push(f);
    }
    for (const [sid, t] of Object.entries(me.duchy || {})) {
      if (!t || prev.duchyIds.has(t.id)) continue;      // newly in duchy = placed
      const f = mk(t, prev.loc[t.id], { kind: "hex", sid }) || popIn(t, { kind: "hex", sid });
      if (f) add.push(f);
    }
    // Goods I took from a depot (a ship action) -> fly each to my goods section.
    const goodsDelta = {};
    for (const c of new Set([...Object.keys(me.goods || {}), ...Object.keys(prev.myGoods || {})])) {
      goodsDelta[c] = (me.goods?.[c] || 0) - (prev.myGoods?.[c] || 0);
    }
    const curGoodIds = new Set();
    for (const d of [1, 2, 3, 4, 5, 6]) (game.depots?.[String(d)]?.goods || []).forEach((g) => curGoodIds.add(g.id));
    const gDest = rectOf({ kind: "mygoods" });
    for (const g of (prev.depotGoods || [])) {
      if (!gDest || curGoodIds.has(g.id) || (goodsDelta[g.color] || 0) <= 0) continue;   // still in a depot, or it went to the opponent
      goodsDelta[g.color] -= 1;
      const s = rectOf({ kind: "depot", d: g.d });
      if (!s) continue;
      const W = 26, H = 26;
      const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
      // Land on the actual goods chip for this color; fall back to the row's left edge.
      const chip = rectOf({ kind: "goodchip", c: g.color });
      const dcx = chip ? chip.left + chip.width / 2 : gDest.left + 18;
      const dcy = chip ? chip.top + chip.height / 2 : gDest.top + gDest.height / 2;
      add.push({ id: `f${flyerSeq.current++}`, goods: true, color: g.color, left: scx - W / 2, top: scy - H / 2, w: W, h: H, dx: dcx - scx, dy: dcy - scy, s1: 1 });
    }
    // Opponent's moves, animated on their always-visible board: depot -> their
    // storage slot, their storage/depot -> their duchy hex (popIn covers sourceless
    // placements like the starting castle), plus goods they drain into their goods row.
    if (!oppChanged) {
    (oPlayer?.storage || []).forEach((t, i) => {
      if (!t || prev.oppStorageIds.has(t.id)) return;          // newly in their storage
      const f = mk(t, prev.loc[t.id] || prev.oppLoc[t.id], { kind: "oppslot", i });
      if (f) add.push(f);
    });
    for (const [sid, t] of Object.entries(oPlayer?.duchy || {})) {
      if (!t || prev.oppDuchyIds.has(t.id)) continue;          // newly in their duchy = placed
      const f = mk(t, prev.oppLoc[t.id] || prev.loc[t.id], { kind: "oppsid", sid }) || popIn(t, { kind: "oppsid", sid });
      if (f) add.push(f);
    }
    {
      const oGoodsDest = rectOf({ kind: "oppgoods" });
      const oGoodsDelta = {};
      for (const c of new Set([...Object.keys(oppGoods), ...Object.keys(prev.oppGoods || {})])) {
        oGoodsDelta[c] = (oppGoods[c] || 0) - (prev.oppGoods?.[c] || 0);
      }
      if (oGoodsDest) for (const g of (prev.depotGoods || [])) {
        if (curGoodIds.has(g.id) || (oGoodsDelta[g.color] || 0) <= 0) continue;
        oGoodsDelta[g.color] -= 1;
        const s = rectOf({ kind: "depot", d: g.d });
        if (!s) continue;
        const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
        const oChip = rectOf({ kind: "oppgoodchip", c: g.color });
        const dcx = oChip ? oChip.left + oChip.width / 2 : oGoodsDest.left + 14;
        const dcy = oChip ? oChip.top + oChip.height / 2 : oGoodsDest.top + oGoodsDest.height / 2;
        add.push({ id: `f${flyerSeq.current++}`, goods: true, color: g.color, left: scx - 13, top: scy - 13, w: 26, h: 26, dx: dcx - scx, dy: dcy - scy, s1: 1 });
      }
    }
    }  // end opponent flyers (skipped on a peek-tab switch, when the snapshot's opp is stale)
    // Round start: a good is handed out onto the white-die depot. Goods only ever appear
    // on a depot via the per-round deal, so a good that's newly present on a depot (not in
    // last update's depotGoods) is that deal — fly it from the goods-left row (the queue it
    // left) to the chosen depot, growing as it lands.
    {
      const prevGoodIds = new Set((prev.depotGoods || []).map((g) => g.id));
      const src = rectOf({ kind: "goodsleft" });
      if (src) for (const g of depotGoods) {
        if (prevGoodIds.has(g.id)) continue;
        // Land on the exact goods element that just rendered in the depot (already in the DOM
        // when this post-render effect runs), sized to its real rect — so it doesn't snap from
        // the depot center to the goods sub-row at the end. getBoundingClientRect is post-zoom,
        // so the size/position are correct under the board's zoom.
        const d = rectOf({ kind: "depotgood", id: g.id });
        if (!d) continue;
        const W = d.width, H = d.height;
        const scx = src.left + src.width / 2, scy = src.top + src.height / 2;
        const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
        add.push({ id: `f${flyerSeq.current++}`, goods: true, color: g.color,
          left: scx - W / 2, top: scy - H / 2, w: W, h: H, dx: dcx - scx, dy: dcy - scy, s0: 0.55, s1: 1 });
      }
    }
    // Skip a flood of TILE changes (reconnect / initial catch-up) so we animate only
    // normal, incremental updates. NB: we can't gate on the move-log length — engine.py
    // caps game["moves"], so its delta is 0 late-game, which once disabled ALL animation.
    if (add.length > 8) return;
    // Workers / silver token flyers: pop tokens OUT of the counter when spent (Δ<0),
    // fly them IN when gained (Δ>0). Diff-driven, so it covers every source/sink
    // (die-adjust, buy-black, sell, phase income) without knowing which move caused it.
    const resFly = (attr, kind, cur, prevV) => {
      const delta = (cur || 0) - (prevV || 0);
      if (!delta) return;
      const el = document.querySelector(`[data-${attr}]`);
      if (!el) return;
      const r = el.getBoundingClientRect();
      const cx = r.left + r.width / 2, cy = r.top + r.height / 2;
      const spent = delta < 0, n = Math.min(Math.abs(delta), 6);
      for (let k = 0; k < n; k++) {
        const ang = -Math.PI / 2 + (k - (n - 1) / 2) * 0.5;   // fan upward
        const dist = 28 + k * 4;
        const ox = Math.cos(ang) * dist, oy = Math.sin(ang) * dist;
        add.push({
          id: `f${flyerSeq.current++}`, token: kind, spent,
          left: (spent ? cx : cx + ox) - 16, top: (spent ? cy : cy + oy) - 16, w: 32, h: 32,
          dx: spent ? ox : -ox, dy: spent ? oy : -oy,
        });
      }
    };
    resFly("workers", "worker", me.workers, prev.workers);
    resFly("silver", "silver", me.silver, prev.silver);
    if (!oppChanged) {
      resFly("opp-workers", "worker", oPlayer?.workers, prev.oppWorkers);   // opponent's spends,
      resFly("opp-silver", "silver", oPlayer?.silver, prev.oppSilver);      // on their visible panel
    }
    if (!add.length) return;
    setFlyers((fs) => [...fs, ...add]);
    const ids = new Set(add.map((f) => f.id));
    setTimeout(() => setFlyers((fs) => fs.filter((f) => !ids.has(f.id))), 460);
  }, [game, me]);
  // Between-phase overlay: when the phase letter advances (A->B->C->D->E), pop a banner
  // announcing the new phase + the mine income you just collected, so the phase-end silver
  // (which flies to your counter on the same update) is never missed. Skipped while
  // reviewing and at game end (the results screen covers the final phase's income).
  useEffect(() => {
    const cur = game?.phase_letter;
    const prev = prevPhaseRef.current;
    prevPhaseRef.current = cur;
    if (reviewing || !cur || !prev || prev === cur || game?.phase === "over") return;
    const mines = me?.mines_count || 0;                 // mines held = silver gained this phase-end
    const workers = (me?.monastery_effects || []).includes(2) ? mines : 0;  // Monastery 2: +1 worker/mine
    setPhasePop({ from: prev, to: cur, silver: mines, workers });
    if (phasePopTimer.current) clearTimeout(phasePopTimer.current);
    phasePopTimer.current = setTimeout(() => { phasePopTimer.current = null; setPhasePop(null); }, 3300);
  }, [game?.phase_letter]);
  useEffect(() => () => { if (phasePopTimer.current) clearTimeout(phasePopTimer.current); }, []);  // tidy on unmount
  // Deselect a die once it's been used (its action applied) — adjust_die leaves
  // the die unused, so it stays selected.
  useEffect(() => {
    const d = game?.dice?.[myId];
    if (selDie != null && d && d.used[selDie]) setSelDie(null);
  }, [game, selDie, myId]);
  // Drop a stale storage selection so the "Click a glowing hex to place" hint never
  // lingers: clear it once the tile leaves storage (placed/discarded) or there's no
  // longer a way to place it (no die / extra-action value / town-hall placement).
  useEffect(() => {
    if (selStorage == null) return;
    const inStorage = (me?.storage || []).some((t) => t.id === selStorage);
    const placeCtx = pendingMine
      ? (game?.pending_kind === "townhall_place" || (game?.pending_kind === "extra_action" && extraValue != null))
      : (selDie != null);
    if (!inStorage || !placeCtx) setSelStorage(null);
  }, [me, selDie, selStorage, pendingMine, game?.pending_kind, extraValue]);

  // ── Hard/Expert tiers: client-side WASM search (coc-core) ──
  // The server ships each bot ENGINE-MOVE decision via `ai_search` in room state;
  // this pool searches the decision's micro-actions one at a time (root-parallel:
  // every worker searches the same micro with a distinct seed, root visits are
  // SUMMED), builds the action chain, converts it to the compact dict-move and
  // submits it as `ai_move`. The server validates by legal-move membership and
  // applies; ANY failure here (worker crash, wasm blocked, tab lag) just times out
  // into the server's hard bot for that turn — never a stuck game.
  // The two tiers differ only in the MODEL the workers load (?model= on the
  // worker URL): hard = the first netval champion (coc_pv_model_hard.bin),
  // expert = the r2 net (coc_pv_model.bin).
  const COC_AI_SIMS_FALLBACK = 20000;      // aggregate per micro-decision if the server sends no cap
  const CLIENT_AI_TIERS = ["hard", "expert"];
  const wasmPoolRef = useRef(null);        // [{ ready, request, terminate }]
  const [wasmReady, setWasmReady] = useState(false);
  const clientAiArmedRef = useRef(null);   // room we've announced capability for (reset per socket)
  const aiDecisionRef = useRef(-1);        // decision seq already dispatched

  useEffect(() => {
    if (!CLIENT_AI_TIERS.includes(roomData?.ai_difficulty) || !roomData?.vs_ai || reviewOnly
        || wasmPoolRef.current || typeof Worker === "undefined") return;
    const model = roomData.ai_difficulty === "hard" ? "coc_pv_model_hard.bin" : "coc_pv_model.bin";
    const url = `${import.meta.env.BASE_URL}wasm/coc-worker.js?model=${model}`;
    // Worker count: bigger machines get up to 8 workers, always leaving 2 cores for
    // the main thread + OS (CoC trees are small — ~30MB at the sims cap — so RAM is
    // not the constraint here). Small devices leave ONE core for the same reason:
    // the <=4-core branch used to take every core, and a pool that pegs them all
    // starves the browser's compositor/raster threads, so animations stutter while
    // the AI thinks. Spender documents this rule; CoC and Duel never had it.
    const hc = navigator.hardwareConcurrency || 4;
    const cores = hc <= 4 ? Math.max(1, hc - 1) : Math.min(hc - 2, 8);
    const makeWorker = () => {
      let w;
      try { w = new Worker(url, { type: "module" }); } catch { return null; }
      const pending = new Map();
      let resolveReady, nextId = 1;
      const ready = new Promise((res) => (resolveReady = res));
      w.onmessage = (e) => {
        const d = e.data || {};
        if (d.ready !== undefined) { resolveReady(!!d.ready); return; }
        if (d.id != null && pending.has(d.id)) { pending.get(d.id)(d); pending.delete(d.id); }
      };
      w.onerror = () => resolveReady(false);
      return {
        ready,
        request(payload) {
          const id = nextId++;
          return new Promise((res) => { pending.set(id, res); w.postMessage({ ...payload, id }); });
        },
        terminate() { try { w.terminate(); } catch {} },
      };
    };
    const pool = Array.from({ length: cores }, makeWorker).filter(Boolean);
    wasmPoolRef.current = pool;
    Promise.all(pool.map((wk) => wk.ready)).then((flags) => {
      const live = pool.filter((_, i) => flags[i]);
      if (live.length > 0) {
        wasmPoolRef.current = live;
        setWasmReady(true);
        console.info(`[coc client-AI] ${live.length}/${cores} WASM workers ready`);
      } else {
        console.warn("[coc client-AI] no WASM workers loaded → server bot");
      }
    });
    return () => { pool.forEach((wk) => wk.terminate()); wasmPoolRef.current = null; setWasmReady(false); };
  }, [roomData?.ai_difficulty, roomData?.vs_ai, reviewOnly]);

  // Announce capability once per socket connection — the server disarms client_ai
  // on disconnect, so a reconnect must re-announce (hence the reset effect).
  useEffect(() => { if (!connected) clientAiArmedRef.current = null; }, [connected]);
  useEffect(() => {
    if (wasmReady && connected && CLIENT_AI_TIERS.includes(roomData?.ai_difficulty)
        && roomData?.room_id && clientAiArmedRef.current !== roomData.room_id) {
      clientAiArmedRef.current = roomData.room_id;
      send({ action: "client_ai_ready" });
    }
  }, [wasmReady, connected, roomData?.room_id, roomData?.ai_difficulty, send]); // eslint-disable-line react-hooks/exhaustive-deps

  // Drive one shipped decision: probe → (forced | fan-out search) → append → repeat
  // to the engine-move boundary → convert → submit. One dispatch per decision seq.
  useEffect(() => {
    const as = roomData?.ai_search;
    const pool = wasmPoolRef.current;
    if (!as || !wasmReady || !pool || pool.length === 0 || reviewOnly) return;
    if (aiDecisionRef.current === as.decision) return;
    aiDecisionRef.current = as.decision;
    const stateStr = JSON.stringify(as.state);
    const perWorkerSims = Math.max(1, Math.ceil((as.max_sims || COC_AI_SIMS_FALLBACK) / pool.length));
    let cancelled = false;
    (async () => {
      try {
        const prefix = [];
        for (let step = 0; step < 16 && !cancelled; step++) {
          const probe = await pool[0].request({ kind: "stepInfo", state: stateStr, prefix: JSON.stringify(prefix) });
          const info = probe?.info;
          if (!info || info.error) return;                    // server watchdog takes over
          if (info.boundary || (info.over && prefix.length)) {
            const conv = await pool[0].request({ kind: "chainMove", state: stateStr, prefix: JSON.stringify(prefix) });
            const mv = conv?.move;
            if (!cancelled && mv && !mv.includes('"error"')) {
              // Offline: the browser is the server — apply the compact move through
              // the driver (validated there) and continue the bot loop. A stale or
              // illegal submission is dropped silently, same policy as the server.
              if (offlineRef.current) {
                const rec = offlineRecRef.current;
                if (rec && rec.decisionSeq === as.decision) {
                  const res = await applyOfflineCocMove(rec, JSON.parse(mv), myId, { isAi: true });
                  if (res.ok) { await publishOffline(res.rec, null); kickOfflineBot(); }
                  else console.debug("[coc offline-AI] dropped:", res.err);
                }
              } else {
                send({ action: "ai_move", decision: as.decision, move: JSON.parse(mv) });
              }
            }
            return;
          }
          if (info.over) return;
          let action;
          if (info.forced >= 0) {
            action = info.forced;                             // single-legal: no search needed
          } else {
            // NOTE: no `ntrees` — the multi-tree batched-eval path (coc_search_timed_multi)
            // measured 3.3x SLOWER in wasm (v128 is COMPUTE-bound; the batched kernel is a
            // memory-bandwidth optimization + register-blocks past what v128 codegen has).
            // Single-tree per worker is the wasm optimum; parallelism comes from the pool.
            //
            // ADAPTIVE BUDGET: search in time slices up to budget_ms total. The wasm
            // keeps each worker's tree alive between calls (same state+prefix →
            // CONTINUE; the returned visits are therefore CUMULATIVE per worker — use
            // the latest response, never add across chunks). Stop early once the
            // summed visit lead is mathematically uncatchable in the remaining time —
            // easy decisions finish in one slice, contested ones use the full budget.
            const budgetTotal = as.budget_ms || 1500;
            const CHUNK_MS = 500;
            let total = null;
            let spent = 0;
            for (let chunk = 0; spent < budgetTotal && !cancelled; chunk++) {
              const budget = Math.min(CHUNK_MS, budgetTotal - spent);
              const results = await Promise.all(pool.map((wk, i) => wk.request({
                kind: "searchCoC", state: stateStr, prefix: JSON.stringify(prefix),
                mode: as.mode || "hybrid", budget, maxSims: perWorkerSims,
                seed: ((as.decision * 2654435761) ^ (step * 97 + i * 40503 + chunk * 715827883 + 1)) >>> 0,
              }).catch(() => null)));
              const sum = new Int32Array(102);
              let got = 0;
              for (const r of results) {
                const v = r && r.visits;
                if (!v || v.length < 102) continue;
                got++;
                for (let a = 0; a < 102; a++) sum[a] += v[a];
              }
              if (!got) { total = null; break; }
              total = sum;
              spent += budget;
              let v1 = 0, v2 = 0, t = 0;
              for (let a = 0; a < 102; a++) {
                t += sum[a];
                if (sum[a] > v1) { v2 = v1; v1 = sum[a]; } else if (sum[a] > v2) v2 = sum[a];
              }
              const remaining = budgetTotal - spent;
              if (remaining <= 0 || v1 - v2 > (t / spent) * remaining) break; // lead uncatchable
            }
            if (!total) return;
            action = 0;
            let stepSims = 0;   // cumulative root visits (slightly overcounts under tree reuse)
            for (let a = 0; a < 102; a++) { stepSims += total[a]; if (total[a] > total[action]) action = a; }
            turnSimsRef.current += stepSims;                 // accumulate across the whole bot turn
          }
          prefix.push(action);
        }
      } catch { /* watchdog fallback */ }
    })();
    return () => { cancelled = true; };
  }, [roomData?.ai_search?.decision, wasmReady, reviewOnly, send]); // eslint-disable-line react-hooks/exhaustive-deps

  // Print ONE line per bot turn with the total client-AI sims it searched (Expert tier).
  // Reset when the bot's turn begins; log the accumulated total when it hands back to you.
  useEffect(() => {
    const wasAi = prevAiSimRef.current;
    prevAiSimRef.current = aiThinking;
    if (aiThinking && !wasAi) turnSimsRef.current = 0;                 // bot's turn starting
    else if (!aiThinking && wasAi) {
      if (turnSimsRef.current > 0) console.info(`[coc client-AI] turn used ${turnSimsRef.current.toLocaleString()} sims`);
      turnSimsRef.current = 0;
    }
  }, [aiThinking]);

  // ── actions ──
  const startCreate = (vsAi, difficulty = "hard") => {
    if (vsAi) rememberDiff(difficulty);   // this game's tier is the next modal's default
    const rid = roomCode();
    setRoomId(rid);
    setConnecting(true);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, {
      action: "create", name: playerName, vs_ai: vsAi,
      board_id: myBoard, opp_board_id: oppBoard,
      ai_difficulty: difficulty,
      max_players: vsAi ? 2 : createSeats,
      same_board: vsAi ? false : createSameBoard,
    });
  };
  const startJoin = (rid) => {
    rid = (rid || "").toUpperCase();
    if (!rid) return;
    setRoomId(rid);
    setConnecting(true);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, { action: "join", name: playerName, board_id: myBoard, session_token: authUser?.session_token });
  };
  const resume = (rid) => {
    const tok = localStorage.getItem(`coc_token_${rid}_${myId}`);
    setRoomId(rid);
    setConnecting(true);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const leaveToLobby = () => {
    // Offline: there is no CoC lobby — every exit path (Leave / Back to lobby /
    // Return to menu) hands back to the shell, which shows the Local-vs-AI hub.
    // The save persists; the boot effect's cleanup token cancels any bot loop.
    if (offlineRef.current) { onExit?.(); return; }
    setConnecting(false);
    disconnect();
    // A read-only HTTP review has no WS and must NOT clear the resume pointer of a
    // real in-progress game the player also has.
    if (!reviewOnly) { try { localStorage.removeItem("coc_roomId"); } catch {} }
    setReviewOnly(false);
    pushPath(buildPath("coc"));   // leave the room URL (dedup no-op when popstate-driven)
    setRoomData(null); setRoomId(""); setReviewing(false); setScreen("lobby"); fetchGames();
  };
  // Cancel an open game you created (host_id === myId). Mirrors Spender: authorize
  // by session token OR host player_id (so it still works after a session expires),
  // and only clear local resume state AFTER the server confirms the delete.
  const handleCancel = (id) => {
    const params = new URLSearchParams();
    params.set("player_id", myId);
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    fetch(`${COC_HTTP}/games/${id}/cancel?${params.toString()}`, { method: "POST", headers })
      .then((r) => r.json())
      .then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("coc_roomId") === id) localStorage.removeItem("coc_roomId");
          localStorage.removeItem(`coc_token_${id}_${myId}`);
        } catch {}
        setToast("Game canceled");
        fetchGames();
      })
      .catch(() => setToast("Could not cancel"));
  };
  const mv = (move) => {
    // Any action other than the undo itself means there's now something to undo.
    if (move?.type && move.type !== "undo_turn") setActedThisTurn(true);
    // Offline: apply through the local engine — the driver's publish IS the
    // authoritative update (lands in ~ms; no optimistic preview needed), then the
    // bot loop takes over if the turn passed.
    if (offlineRef.current) {
      const rec = offlineRecRef.current;
      if (!rec) return;
      (async () => {
        const res = await applyOfflineCocMove(rec, move, myId, { isAi: false });
        if (!res.ok) { setToast(res.err); return; }
        await publishOffline(res.rec, null);
        kickOfflineBot();
      })().catch((e) => setToast(String(e?.message || "Move failed")));
      return;
    }
    // Optimistic preview: show this move's certain visible effect instantly, then let
    // the server's authoritative room_update reconcile (see handleMessage). Safe by
    // construction — the server never sees the preview; it's overwritten on the next
    // update and reverted on error. Unpredictable moves get null -> plain send.
    const preview = optimisticMove(roomData?.game, move, myId);
    if (preview) {
      preOptimisticRoomRef.current = roomData;
      optimisticRef.current = true;
      setRoomData((prev) => (prev ? { ...prev, game: preview } : prev));
    }
    send({ action: "move", move });
  };

  // ── move helpers (respect extra_action mode) ──
  const inExtra = pendingMine && game?.pending_kind === "extra_action";
  const actionValue = inExtra ? extraValue : (selDie != null ? game?.dice?.[myId]?.values?.[selDie] : null);

  // Ship goods-depot pick: while a ship/monastery is asking which depot to drain, you
  // can click the depot directly on the board (in addition to the modal buttons).
  const shipPickMine = pendingMine && (game?.pending_kind === "ship_choose_depot" || game?.pending_kind === "ship_adjacent_depot");
  const shipCands = !shipPickMine ? []
    : (game.pending_kind === "ship_adjacent_depot" ? (game.pending?.ctx?.candidates || []) : [1, 2, 3, 4, 5, 6]);
  const shipPick = (d) => {
    if (game.pending_kind === "ship_choose_depot") { mv({ type: "ship_take_goods", depot: d }); return; }
    if (game.pending_kind === "ship_adjacent_depot" && shipCands.includes(d)) mv({ type: "ship_adjacent_take", depot: d });
  };

  // Building take-a-tile (carpenter/church/etc): same board-picking style as the ship —
  // click the depot holding the tile you want. A depot with exactly ONE candidate
  // (the carpenter's building case) takes on a depot click; a depot holding TWO
  // candidates (church: castle+monastery / mine+monastery) needs the specific tile
  // clicked to disambiguate (handled in clickDepotTile).
  const buildingPickMine = pendingMine && game?.pending_kind === "building_take_choice";
  const buildingCands = buildingPickMine ? (game.pending?.ctx?.candidates || []) : [];
  const buildingDepotCands = (d) => (game.depots[String(d)].hexes || []).filter((t) => buildingCands.includes(t.id)).map((t) => t.id);
  const buildingPick = (id) => mv({ type: "building_take_choice", tile_id: id });

  // Goods pick: the chosen depot had more new goods colors than free slots, so you
  // choose which type(s) to take. Click a goods token of an offered color in the
  // depot (that depot's tokens pulse), or a button in the floating modal.
  const goodsPickMine = pendingMine && game?.pending_kind === "goods_pick";
  const goodsPickColors = goodsPickMine ? (game.pending?.ctx?.colors || []) : [];
  const goodsPickDepot = goodsPickMine ? game.pending?.ctx?.depot : null;
  const goodsPick = (color) => { if (goodsPickColors.includes(color)) mv({ type: "goods_pick", color }); };

  // Warehouse: sell one goods type for silver. Optional — click one of YOUR goods
  // (they pulse), a button in the floating modal, or Skip. Mirrors the ship/goods picks.
  const warehouseMine = pendingMine && game?.pending_kind === "warehouse_sell";
  const warehouseSell = (color) => { if ((me?.goods?.[color] || 0) > 0) mv({ type: "warehouse_sell", color }); };

  // Click a goods chip in YOUR storage to sell it. Ability scenarios (a Warehouse
  // pending, the Castle bonus's chosen die) sell on click directly. Selling WITHOUT an
  // ability needs a die SELECTED first, and only the goods that die can sell (its value
  // == the goods' sell number) are clickable — otherwise a click just shows the goods
  // description, like before.
  const sellDieForGood = (color) => {
    const d = game?.dice?.[myId];
    if (!d || selDie == null || d.used[selDie]) return -1;
    return d.values[selDie] === goodsSellNum(color) ? selDie : -1;
  };
  const extraSellColor = (inExtra && extraValue != null) ? board?.goods_colors?.[extraValue - 1] : null;
  const canSellGood = (color) => (me?.goods?.[color] || 0) > 0 && (
    warehouseMine
    || extraSellColor === color
    || (myTurnRaw && !pendingMine && sellDieForGood(color) >= 0)
  );
  const sellGood = (color) => {
    if (!((me?.goods?.[color] || 0) > 0)) return;
    if (warehouseMine) { warehouseSell(color); return; }
    if (extraSellColor === color) { mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } }); return; }
    const i = sellDieForGood(color);
    if (myTurnRaw && !pendingMine && i >= 0) mv({ type: "sell_goods", die_index: i });
  };

  // Tapping a tile you can't act on yet shows its description (mobile has no hover,
  // so this mirrors the PC title-tooltip — see also clickBlackTile).
  // Inspection is independent of the armed action: a right-click must never
  // buy, take, place, or sell the piece under the pointer.
  const inspect = (event, description) => {
    event.preventDefault();
    event.stopPropagation();
    setToast(description);
  };

  const clickDepotTile = (depot, tile, e) => {
    if (shipPickMine) return;   // clicking anywhere in a depot picks it (handled on the depot div)
    if (buildingPickMine) {
      // Take this exact tile if it's a candidate (disambiguates a 2-candidate depot);
      // stop the click from also hitting the depot's own pick handler.
      if (buildingCands.includes(tile.id)) { if (e) e.stopPropagation(); buildingPick(tile.id); }
      else setToast(tileDesc(tile, board));
      return;
    }
    if (!pendingMine && !myTurnRaw) { setToast(tileDesc(tile, board)); return; }
    if (inExtra) { if (extraValue == null) { setToast(tileDesc(tile, board)); return; } mv({ type: "extra_action", value: extraValue, sub: { type: "take_hex", depot, tile_id: tile.id } }); return; }
    if (selDie == null) { setToast(tileDesc(tile, board)); return; }
    mv({ type: "take_hex", die_index: selDie, depot, tile_id: tile.id });
  };
  const clickBlackTile = (tile) => {
    // Buying needs the silver token armed first; otherwise a click just shows the tile.
    if (silverArmed) { mv({ type: "buy_black", tile_id: tile.id }); setSilverArmed(false); return; }
    setToast(`${tileDesc(tile, board)}  ·  buy for 2 silver`);
  };
  const clickHex = (sid, legal) => {
    if (!legal) return;
    if (setupPhase) { mv({ type: "place_starting_castle", space_id: sid }); return; }
    if (!selStorage) return;
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
  // Net worker cost of nudging die `i` by `dir` (±1). Cost is distance-from-roll, so
  // moving back toward the rolled value REFUNDS (delta < 0). Mirrors engine _adjust_cost.
  const adjustDelta = (i, dir) => {
    const d = game?.dice?.[myId];
    if (!d) return 0;
    const cur = d.values[i];
    const to = ((cur - 1 + dir + 6) % 6) + 1;
    const orig = (d.orig || d.values)[i];
    const per = (me?.monastery_effects || []).includes(8) ? 2 : 1;
    const dist = (a, b) => { const s = Math.min(((b - a) % 6 + 6) % 6, ((a - b) % 6 + 6) % 6); return Math.ceil(s / per); };
    return dist(orig, to) - dist(orig, cur);
  };

  // ── placement legality (client-side highlight; server is authoritative) ──
  const placeValue = inExtra ? extraValue : (selDie != null ? game?.dice?.[myId]?.values?.[selDie] : null);
  const ignoreNumber = pendingMine && game?.pending_kind === "townhall_place";
  const legalTarget = (sid) => {
    if (!me) return false;
    // During setup any empty castle ("burgundy" backend color) space is a legal starting-castle spot.
    if (setupPhase) {
      if (game.turn !== myId) return false;
      const sp = boardSpaces(me.board_id)[sid];
      return !!sp && sp.color === "burgundy" && !me.duchy[sid];
    }
    if (!selStorage) return false;
    const sp = boardSpaces(me.board_id)[sid];
    if (!sp || me.duchy[sid]) return false;
    const tile = me.storage.find((t) => t.id === selStorage);
    if (!tile || tile.color !== sp.color) return false;
    if (!ignoreNumber) {
      if (placeValue == null) return false;
      // Match the engine's _free_shift_for_tile: the die's 1<->6-wrapping neighbors
      // are only legal when the player owns the free-shift monastery for THIS tile
      // type (9=building, 10=ship/livestock, 11=castle/mine/monastery). Otherwise
      // only the exact die value places (highlighting the ±1 spaces was misleading).
      const eff = me.monastery_effects || [];
      const freeShift = (tile.type === "building" && eff.includes(9))
        || ((tile.type === "ship" || tile.type === "livestock") && eff.includes(10))
        || ((tile.type === "castle" || tile.type === "mine" || tile.type === "monastery") && eff.includes(11));
      const allowed = freeShift
        ? new Set([placeValue, (placeValue % 6) + 1, ((placeValue - 2 + 6) % 6) + 1])
        : new Set([placeValue]);
      if (!allowed.has(sp.number)) return false;
    }
    const dirs = [[1, 0], [-1, 0], [0, 1], [0, -1], [1, -1], [-1, 1]];
    // One-building-per-region: a building can't go in a region that already holds the
    // SAME building type, UNLESS you own the enabling monastery (effect 1). Mirrors
    // engine._building_town_ok — the region is the same-color connected component of
    // `sid` (matches the engine REGIONS); scan its placed tiles for a duplicate. All
    // placement paths (die / extra_action / townhall) enforce this in the engine.
    if (tile.type === "building" && !(me.monastery_effects || []).includes(1)) {
      const spaces = boardSpaces(me.board_id);
      const seen = new Set([sid]);
      const stack = [sid];
      while (stack.length) {
        const cur = stack.pop();
        const placed = cur === sid ? null : me.duchy[cur];
        if (placed && placed.type === "building" && placed.building === tile.building) return false;
        const [cq, cr] = cur.split(",").map(Number);
        for (const [dq, dr] of dirs) {
          const nb = `${cq + dq},${cr + dr}`;
          if (!seen.has(nb) && spaces[nb] && spaces[nb].color === sp.color) { seen.add(nb); stack.push(nb); }
        }
      }
    }
    // adjacency: any filled neighbor
    const [q, r] = sid.split(",").map(Number);
    return dirs.some(([dq, dr]) => me.duchy[`${q + dq},${r + dr}`]);
  };

  // Rules modal — defined once and rendered in BOTH the lobby and the in-game options
  // menu, so "How to Play" is reachable during a game too.
  const cocRulesModal = showRules && (
    <RulesModal title="How to play — Castles of Crimson" onClose={() => setShowRules(false)}>
      <CocRules />
    </RulesModal>
  );

  // ─── Lobby ───────────────────────────────────────────────────────────────
  // The lobby renders IMMEDIATELY (like the other games) rather than blocking the whole
  // screen on the board-layout fetch — only the board-picker below shows a spinner until
  // the layouts arrive. The game/waiting screens still need `board` (guarded after this).
  // Instant feedback the moment a game is clicked, while the WS + first state land.
  if (connecting && screen === "lobby") {
    return (<div className="coc coc-neutral" style={{ "--lby-accent": GAME_ACCENTS.coc }}><style>{css}</style><LobbyLoading /></div>);
  }
  if (screen === "lobby") {
    // Board pickers live in the create/join modals (not the lobby), so the lobby
    // paints instantly and the layouts fetch resolves in the background.
    const boardStrip = (sel, onPick) => board ? (
      <div className="coc-board-grid">
        {(board.boards || []).map((b) => (
          <BoardThumb key={b.id} spaces={b.spaces} name={b.name}
            selected={sel === b.id} onClick={() => onPick(b.id)} />
        ))}
      </div>
    ) : (
      <div className="lby-empty"><span className="lby-spinner lby-spinner-sm" /> Loading boards…</div>
    );
    const boardName = (id) => board?.byId?.[id]?.name || `Board ${id}`;
    const diffLabel = (d) => d.charAt(0).toUpperCase() + d.slice(1);
    return (
      <div className="coc coc-neutral" style={{ "--lby-accent": GAME_ACCENTS.coc }}><style>{css}</style>
        <LobbyHeader
          onBack={onExit}
          user={<LobbyUser user={authUser || { name: playerName, guest: true }} />}
        />
        <div className="coc-wrap lby-page">
          <div className="lby-page-in">
          <LobbyHero game="coc">
          <LobbyCreateRow
            onCreate={() => setShowCreateModal(true)}
            onJoin={(code) => setJoinBoardFor(code)}
            onRefresh={fetchGames}
            onRules={() => setShowRules(true)} />
          </LobbyHero>

          {showCreateModal && (
            <CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
              <CmRow label="Opponent">
                <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                  { value: "friend", label: "VS Friend", title: "Create a game a friend can join from Open Games (or your room code)" },
                  { value: "ai", label: "VS AI", title: "Starts instantly against the bot" },
                ]} />
              </CmRow>
              {createOpp === "ai" ? (
                <CmRow label="AI Difficulty">
                  <CmSeg value={createDiff} onChange={setCreateDiff} options={AI_TIER_OPTIONS} />
                </CmRow>
              ) : (
                <CmRow label="Players">
                  <CmSeg value={createSeats} onChange={setCreateSeats}
                    options={[2, 3, 4].map((n) => ({ value: n, label: String(n) }))} />
                  <span className="cm-hint">Friends join from Open Games — or send your room code.</span>
                </CmRow>
              )}
              <CmRow label={createOpp === "friend" && createSameBoard ? "Shared Board" : "Your Board"}>{boardStrip(myBoard, setMyBoard)}</CmRow>
              {createOpp === "ai" ? (
                <CmRow label="Bot's Board">{boardStrip(oppBoard, setOppBoard)}</CmRow>
              ) : (
                <>
                  <CmRow label="Boards">
                    <CmSeg value={createSameBoard} onChange={setCreateSameBoard} options={[
                      { value: false, label: "Each picks", title: "Every player chooses their own board when they join" },
                      { value: true, label: "Same board", title: "Everyone plays on the board you picked above" },
                    ]} />
                  </CmRow>
                  <span className="cm-hint">{createSameBoard ? "Everyone plays on your board." : "Your friends pick their own boards when they join."}</span>
                </>
              )}
              <div className="cm-footer">
                <span className="cm-summary">
                  Creating: <b>{createOpp === "ai" ? `${diffLabel(createDiff)} bot` : `vs Friend · up to ${createSeats} players`}</b> · <b>{boardName(myBoard)}</b>
                  {createOpp === "ai" && <> · bot on <b>{boardName(oppBoard)}</b></>}
                  {createOpp === "friend" && createSameBoard && <> · <b>same board</b></>}
                </span>
                <button type="button" className="cm-create"
                  onClick={() => { setShowCreateModal(false); startCreate(createOpp === "ai", createDiff); }}>
                  Create Game
                </button>
              </div>
            </CreateModal>
          )}

          {joinBoardFor && (() => {
            // joinBoardFor is either a bare room-code string (join-by-code) or, from an
            // Open Games card, {id, sameBoard, hostBoard}. When the host locked a shared
            // board, the joiner has no board pick — the start assigns the host's board.
            const jb = typeof joinBoardFor === "string" ? { id: joinBoardFor } : joinBoardFor;
            const rid = jb.id;
            return (
              <CreateModal title="Join Game" onClose={() => setJoinBoardFor(null)}>
                {jb.sameBoard
                  ? <CmRow label="Board"><span className="cm-hint">Everyone plays on the host's board — <b>{boardName(jb.hostBoard)}</b>.</span></CmRow>
                  : <CmRow label="Your Board">{boardStrip(myBoard, setMyBoard)}</CmRow>}
                <div className="cm-footer">
                  <span className="cm-summary">Joining <b>{rid.toUpperCase()}</b> on <b>{jb.sameBoard ? boardName(jb.hostBoard) : boardName(myBoard)}</b></span>
                  <button type="button" className="cm-create"
                    onClick={() => { setJoinBoardFor(null); startJoin(rid); }}>
                    Join Game
                  </button>
                </div>
              </CreateModal>
            );
          })()}

          <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
            { key: "open", label: "Open", count: openGames.length || null },
            { key: "active", label: "Active", count: activeGames.length || null },
            { key: "history", label: "History", count: history.length || null },
          ]} />
          <div className={`coc-lobby-grid lby-cols tab-${lobbyTab}`}>
            <div className="coc-lobby-col lby-col-open">
              <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
              {loadingGames && openGames.length === 0 ? (
                <div className="lby-empty"><span className="lby-spinner lby-spinner-sm" />Loading…</div>
              ) : openGames.length === 0 ? (
                <div className="lby-empty">No open games — create one.</div>
              ) : (
                <div className="lby-list">
                {openGames.map((g) => (
                  <div className="lby-card" key={g.id}>
                    <div className="lby-card-info">
                      <div className="lby-card-title">{g.host_id === myId ? "Your game" : `${g.host_name}'s game`}
                        <span className="lby-seats">{g.player_count || 1}/{g.max_players || 4}</span></div>
                      <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                    </div>
                    <div className="lby-card-actions">
                      {g.host_id === myId
                        ? <>
                            <LobbyAction kind="secondary" onClick={() => resume(g.id)}>Return</LobbyAction>
                            <LobbyAction kind="danger" onClick={() => handleCancel(g.id)}>Cancel</LobbyAction>
                          </>
                        : ((g.player_count || 1) >= (g.max_players || 4)
                            ? <TurnBadge>Full</TurnBadge>
                            : <LobbyAction onClick={() => setJoinBoardFor({ id: g.id, sameBoard: !!g.same_board, hostBoard: g.host_board })}>Join</LobbyAction>)}
                    </div>
                  </div>
                ))}
                </div>
              )}
            </div>

            <div className="coc-lobby-col lby-col-active">
              <LobbySectionHd title="Active Games" note={`${activeGames.length} in progress`} />
              {activeGames.length === 0 ? (
                <div className="lby-empty">No games in progress.</div>
              ) : (() => {
                // All in-progress games (yours + others'). Yours pinned to the top;
                // each sub-list is already updated_at-desc from the backend.
                // Prefer the N-player `players` array; fall back to legacy p1/p2 fields.
                const plOf = (g) => (g.players && g.players.length ? g.players : [
                  ...(g.player1_id ? [{ id: g.player1_id, name: g.player1_name }] : []),
                  ...(g.player2_id ? [{ id: g.player2_id, name: g.player2_name }] : []),
                ]);
                const isMineG = (g) => plOf(g).some((p) => p.id === myId);
                const mine = activeGames.filter(isMineG);
                const others = activeGames.filter((g) => !isMineG(g));
                const ordered = [...mine, ...others];
                return <div className="lby-list">{ordered.map((g) => {
                  const pl = plOf(g);
                  const isMine = pl.some((p) => p.id === myId);
                  const turnName = (pl.find((p) => p.id === g.turn) || {}).name;
                  // ONE SEAT PER LINE, not a "A vs B vs C" run. Spender's public
                  // Active column already stacks; CoC flowed the same string into the
                  // same width and it wrapped wherever it landed — "Marguerite vs /
                  // Aurelia (you)", a dangling preposition at the line end, while the
                  // row above it fitted on one line. Same feature, same column, two
                  // typographic treatments and one bad break.
                  const seats = pl.length
                    ? pl.map((p) => ({ name: p.name, you: p.id === myId }))
                    : [{ name: "waiting…" }];
                  return (
                    <div className="lby-card" key={g.id}>
                      <div className="lby-card-info">
                        <LobbyMatchup seats={seats} />
                        <div className="lby-card-meta">{g.id} · {timeAgo(g.updated_at)}<LobbyBotTier tier={g.ai_difficulty} labels={AI_TIER_LABELS} /></div>
                      </div>
                      <div className="lby-card-actions">
                        {isMine ? (
                          <>
                            {g.turn === myId
                              ? <TurnBadge mine>Your turn</TurnBadge>
                              : <TurnBadge>Their turn</TurnBadge>}
                            <LobbyAction onClick={() => resume(g.id)}>Resume</LobbyAction>
                          </>
                        ) : (
                          <TurnBadge>{turnName ? `${turnName}'s turn` : "In progress"}</TurnBadge>
                        )}
                      </div>
                    </div>
                  );
                })}</div>;
              })()}
            </div>

            <div className="coc-lobby-col lby-col-history">
              <LobbySectionHd title="History" note={`${history.length} finished`} />
              {!authUser ? (
                <div className="lby-empty">Log in to keep your game history.</div>
              ) : history.length === 0 ? (
                <div className="lby-empty">No finished games yet.</div>
              ) : (
                <div className="lby-list">
                {historyShown.map((g) => (
                  <div className="lby-card lby-card-hist" key={g.id}>
                    <div className="lby-card-info">
                      <div className="lby-card-title">
                        <span className={`hist-result ${g.tie ? "tie" : (g.you_won ? "won" : "lost")}`}>{g.tie ? "Tie" : (g.you_won ? "Won" : "Lost")}</span>
                        <span className="hist-scores"> vs {g.opp_name}{g.your_score != null && g.opp_score != null ? <> <span className="hist-score-num">{g.your_score}–{g.opp_score}</span></> : null}</span>
                      </div>
                      <div className="lby-card-meta">{timeAgo(g.updated_at)}<LobbyBotTier tier={g.ai_difficulty} labels={AI_TIER_LABELS} /></div>
                    </div>
                    <div className="lby-card-actions">
                      <LobbyAction kind="secondary" onClick={() => enterCocReview(g.id)}>Review</LobbyAction>
                    </div>
                  </div>
                ))}
                {historyMore}
                </div>
              )}
            </div>
          </div>
          </div>
        </div>
        {cocRulesModal}
        {toast && <div className="coc-toast">{toast}</div>}
      </div>
    );
  }

  // ─── Waiting ─────────────────────────────────────────────────────────────
  // `WaitingRoom` in shared/lobby.jsx — the panel, the invite link, the seats and
  // the way out are the kit's; CoC brings its accent and its seat cap.
  if (screen === "waiting") {
    const cap = roomData?.max_players || 4;          // host-chosen seat cap
    return (
      <div className="coc" style={{ "--lby-accent": GAME_ACCENTS.coc }}><style>{css}</style>
        <WaitingRoom
          game="coc" roomId={roomId}
          players={players} hostId={roomData?.host} myId={myId}
          min={2} max={cap}
          user={authUser}
          onLeave={leaveToLobby}
          onRules={() => setShowRules(true)}
          onStart={() => send({ action: "start" })} />
        {cocRulesModal}
        {toast && <div className="coc-toast">{toast}</div>}
      </div>
    );
  }

  // The GAME screens render the board, so they still wait for the layout fetch.
  // The waiting room above does NOT any more — it is the shared kit, it draws no
  // tiles, and making an invite screen wait on a board fetch put a spinner in
  // front of the one thing a host opens the room to do.
  if (!board) {
    return (<div className="coc coc-neutral" style={{ "--lby-accent": GAME_ACCENTS.coc }}><style>{css}</style><LobbyLoading /></div>);
  }

  // ─── Winner ──────────────────────────────────────────────────────────────
  if (over && !reviewing) {
    const w = game.winner;
    const tie = Array.isArray(w);
    const isMe = !tie && w === myId;
    const winnerName = tie ? "Tie" : (players[w] || w);
    const order = game.order || Object.keys(players);
    const scores = roomData?.final_scores || {};
    const breakdowns = roomData?.vp_breakdown || {};
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-wrap">
          <div className="coc-review">
            <h2>{isMe ? "Victory!" : tie ? "It's a tie!" : "Defeat"}</h2>
            <p className="coc-card-meta" style={{ margin: "6px 0 4px" }}>
              {tie ? "The duchy is shared." : `${winnerName} has the greater duchy`}
            </p>
            <VpReview order={order} players={players} myId={myId} scores={scores}
              breakdowns={breakdowns} winnerPid={w} projected={false} />
            <div style={{ display: "flex", gap: 10, justifyContent: "center", marginTop: 18 }}>
              <button className="coc-btn outline" onClick={() => setReviewing(true)}>Review game</button>
              <button className="coc-btn gold" onClick={leaveToLobby}>Back to lobby</button>
            </div>
          </div>
        </div>
      </div>
    );
  }

  // ─── Game ────────────────────────────────────────────────────────────────
  const dice = game.dice?.[myId];
  const oppDice = oppId ? game.dice?.[oppId] : null;
  // You must use BOTH dice before ending the turn (take-2-workers is always a
  // legal use for an otherwise-stuck die, so this can never soft-lock).
  const bothDiceUsed = !!dice && dice.used[0] && dice.used[1];
  // Something is undoable once you've spent a die / bought black / used monastery 6,
  // or this client recorded an action (covers worker-only die adjusts).
  const hasActed = actedThisTurn || (!!dice && (dice.used[0] || dice.used[1]))
    || !!game.black_depot_used_this_turn || !!game.m6_used_this_turn;
  const renderDuchy = (pdata, interactive, opp = false) => {
    const spaces = boardSpaces(pdata.board_id);
    const sids = Object.keys(spaces);
    let minX = 1e9, minY = 1e9, maxX = -1e9, maxY = -1e9;
    const centers = {};
    for (const sid of sids) {
      const sp = spaces[sid];
      const c = hexCenter(sp.q, sp.r);
      centers[sid] = c;
      minX = Math.min(minX, c.x); maxX = Math.max(maxX, c.x);
      minY = Math.min(minY, c.y); maxY = Math.max(maxY, c.y);
    }
    // Pointy-top hexes reach (HEX_S-1.5)·√3/2 sideways (the DRAWN flat half-width — the
    // polygons use radius HEX_S-1.5) but HEX_S up/down (points). Pad X to exactly that
    // drawn flat half so the leftmost/rightmost hex fills flush to the viewBox edge — same
    // 0 side-buffer as the storage slots above it (the +0.5 is a hair of rim-stroke room).
    // Any bigger padX leaves a visible gap the storage row doesn't have.
    const padX = (HEX_S - 1.5) * Math.sqrt(3) / 2 + 0.5;
    // Match the top/bottom buffer to the sides: the pointy hex reaches HEX_S-1.5 up/down,
    // so pad to that + the same 0.5 rim — the board is flush all around (no extra bottom gap).
    const padY = (HEX_S - 1.5) + 0.5;
    const vb = `${(minX - padX).toFixed(1)} ${(minY - padY).toFixed(1)} ${(maxX - minX + padX * 2).toFixed(1)} ${(maxY - minY + padY * 2).toFixed(1)}`;
    return (
      <svg className="coc-hexsvg" viewBox={vb}>
        <defs>
          {/* Empty spaces are SOCKETS the tiles drop into, so they read LOWERED: a
              strong dark band at the top (the socket lip's shadow) fading to a faint
              light rim at the bottom (the lit floor) — the inverse of a raised tile. */}
          <linearGradient id="coc-socket" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="#000" stopOpacity="0.62" />
            <stop offset="42%" stopColor="#000" stopOpacity="0.16" />
            <stop offset="84%" stopColor="#000" stopOpacity="0" />
            <stop offset="100%" stopColor="#fff" stopOpacity="0.22" />
          </linearGradient>
          {/* A placed tile sits ON the board, so it gets the same raised bevel as
              the depot tiles (light top-left -> dark bottom) to pop out of its socket. */}
          <linearGradient id="coc-raise" x1="0" y1="0" x2="0.4" y2="1">
            <stop offset="0%" stopColor="#fff" stopOpacity="0.55" />
            <stop offset="26%" stopColor="#fff" stopOpacity="0.12" />
            <stop offset="60%" stopColor="#000" stopOpacity="0.06" />
            <stop offset="100%" stopColor="#000" stopOpacity="0.55" />
          </linearGradient>
        </defs>
        {sids.map((sid) => {
          const sp = spaces[sid];
          const c = centers[sid];
          const tile = pdata.duchy[sid];
          const legal = interactive && legalTarget(sid);
          const placed = !!tile;
          // Full colors for every hex (matching the depot tiles); placed tiles
          // are distinguished by a bright highlighted outline, not by dimming.
          const fill = placed ? (TILE_HEX[tile.color] || "#555") : (TILE_HEX[sp.color] || "#444");
          // Both the placed-tile gold rim AND the legal-target glow are drawn LAST
          // (stroke-only polygons over the bevel/socket gradient) so each stays uniform
          // all the way around — otherwise the gradient paints over the inner half of
          // the stroke (pale at the top, dark at the bottom) and the outline reads
          // asymmetrically.
          let stroke, strokeWidth;
          if (legal || placed) { stroke = "none"; strokeWidth = 0; }
          else { stroke = "rgba(0,0,0,.4)"; strokeWidth = 1; }
          return (
            <g key={sid} data-sid={opp ? undefined : sid} data-oppsid={opp ? sid : undefined} className={`coc-hex${legal ? " legal" : ""}`}
              onContextMenu={(e) => inspect(e, tile ? tileDesc(tile, board) : `${colorLabel(sp.color)} space (die ${sp.number}).`)}
              onClick={() => { if (interactive && legal) clickHex(sid, legal); else if (tile) setToast(tileDesc(tile, board)); }}>
              <title>{tile ? tileDesc(tile, board)
                : setupPhase ? (sp.color === "burgundy" ? "Click to place your starting castle here." : `${colorLabel(sp.color)} space (die ${sp.number}).`)
                : `Empty ${colorLabel(sp.color)} space — place a matching tile using die ${sp.number}.`}</title>
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill={fill} fillOpacity={placed ? 1 : 0.5}
                stroke={stroke} strokeWidth={strokeWidth} />
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill={placed ? "url(#coc-raise)" : "url(#coc-socket)"}
                stroke="none" style={{ pointerEvents: "none" }} />
              {placed && <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill="none"
                stroke="#fff2c0" strokeWidth={2.6} style={{ pointerEvents: "none" }} />}
              {legal && <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill="none"
                stroke="var(--gold)" strokeWidth={3} style={{ pointerEvents: "none" }} />}
              {placed
                ? <TileArtSvg tile={tile} cx={c.x} cy={c.y} box={HEX_ART} />
                : svgPips(c.x, c.y, sp.number, sid)}
            </g>
          );
        })}
      </svg>
    );
  };

  const goodsForDie = actionValue != null ? board.goods_colors[actionValue - 1] : null;

  // Whose turn is it? The badge shows on the ACTIVE player's own panel — beside your
  // Discard/End buttons on your turn, in the same header spot on the opponent's turn.
  const mineActive = !over && (setupPhase ? setupMine : myTurnRaw);
  const myBadgeText = setupPhase ? "Place your starting castle" : (pendingMine ? "Your decision" : "Your turn");
  const oppBadgeText = setupPhase
    ? (aiThinking ? "Bot is choosing…" : `${players[game.turn] || "Opponent"} is choosing…`)
    : (aiThinking ? "Bot is playing…" : `${players[game.turn] || "Opponent"}'s turn`);

  return (
    <div className="coc" style={{ "--lby-accent": GAME_ACCENTS.coc }}><style>{css}</style>
      <div className="coc-wrap coc-wrap-game">
        <div className="coc-top coc-top-game">
          <div className="coc-top-left">
            {over
              ? <button className="coc-btn ghost sm" onClick={() => setReviewing(false)}>← Results</button>
              : <GameMenu onLeave={leaveToLobby}
                  onRules={() => setShowRules(true)}
                  onAbandon={() => setConfirmAbandon(true)} />}
          </div>
          <span className="coc-title">Castles of Crimson</span>
          <div className="coc-top-right coc-top-abandon">
            {!over && confirmAbandon && (
              <>
                <span className="coc-card-meta">{offline ? "Leave this game? The save stays on this device." : "Abandon game?"}</span>
                <button className="coc-btn crimson sm" onClick={() => {
                  if (offline) { setConfirmAbandon(false); onExit?.(); return; }
                  send({ action: "abandon" }); setConfirmAbandon(false);
                }}>{offline ? "Yes, leave" : "Yes, resign"}</button>
                <button className="coc-btn ghost sm" onClick={() => setConfirmAbandon(false)}>No</button>
              </>
            )}
          </div>
        </div>

        {/* Bonuses row: region phase/size + color-completion bonuses on the left, with
            the live score centered. (Replaces the old status box — phase/round/goods-left
            moved onto the board header.) */}
        <div className="coc-bonusbar">
          <div className="coc-bonus-groups">
            <span className="coc-bonusbar-lbl coc-bonuses-lead">Bonuses:</span>
            <span className="coc-bonus-sec coc-regbonus-lbl"
              title="Complete any region THIS phase for this many bonus VP, on top of its size bonus. It shrinks each phase: A +10 → B +8 → C +6 → D +4 → E +2.">
              <span className="coc-bonusbar-lbl">Phase</span> <b className="coc-regbonus">+{PHASE_BONUS[game.phase_letter] ?? 0}</b>
            </span>
            <span className="coc-bonus-div" />
            <span className="coc-bonus-sec coc-regbonus-lbl"
              title="Fixed VP for completing a region, by its number of spaces (1–8). Added to the region phase bonus.">
              <span className="coc-bonusbar-lbl">Size</span> <b className="coc-regbonus coc-regsize">{AREA_SCORE.join("/")}</b>
            </span>
            <span className="coc-bonus-div" />
            <span className="coc-bonus-sec"
              title="VP for being the 1st (large) / 2nd (small) player to fully complete every space of a color">
              <span className="coc-bonusbar-lbl">Color</span>
              {BOARD_COLORS.map((c) => {
                const rem = game.bonus_tiles?.[c] || [];
                const size = rem.length >= 2 ? "large" : rem.length === 1 ? "small" : null;
                return (
                  <span key={c} className={`coc-bonuschip${size ? "" : " gone"}`}
                    title={`${colorLabel(c)}: ${size ? `${size} bonus available (+${rem[0]} VP)` : "both bonuses taken"}`}>
                    <BonusTileBadge className="coc-bonus-sw" color={TILE_HEX[c]} />
                    {size ? <b>+{rem[0]}</b> : <i>—</i>}
                  </span>
                );
              })}
            </span>
          </div>
          <div className="coc-vp coc-vp-click" onClick={() => over ? setReviewing(false) : setShowScores(true)}
            title={over ? "Final score (with end-of-game bonuses). Click for the full breakdown" : "Click for the full VP breakdown"}>
            {/* At game end show the FINAL score (leftover resources + monastery bonuses
                folded in); during play show the live placed-tile VP. */}
            <span className="v">{me ? "You" : ""} <b>{over && fscore?.[myId] != null ? fscore[myId] : (me?.vp ?? 0)}</b></span>
            {opp && <span className="v">{players[oppId]} <b>{over && fscore?.[oppId] != null ? fscore[oppId] : opp.vp}</b></span>}
            <span className="coc-vp-info">ⓘ</span>
          </div>
          <span className="coc-bonus-spacer">
            {over
              ? <span className="coc-turnbadge you coc-gameover-badge">Game over</span>
              : mineActive
                ? <span className="coc-turnbadge you">{myBadgeText}</span>
                : <span className="coc-turnbadge them">{oppBadgeText}</span>}
          </span>
        </div>

        {/* The table: shared board + your duchy + the opponent's duchy, all visible
            together (3 columns on wide screens, 2+1 on medium, stacked on phones). */}
        <div className="coc-game-cols">
        {/* Shared board: 6 numbered depots arranged as a hexagon, black depot centered */}
        <div className="coc-panel coc-board-panel coc-col-board">
          <div className="coc-board-head">
            <div className="coc-board-status">
              <span className="coc-pill coc-pill-phase">Phase <b>{game.phase_letter}</b></span>
              {(() => {
                // This phase's 5 goods, one handed out at the start of each round. The queue
                // holds the not-yet-dealt goods (deal order, leftmost = next); the already-dealt
                // ones show as faded slots so the round-by-round progression is visible
                // (round 1 uses slot 1, round 2 slot 2, ...). No "Goods left" label — the row
                // speaks for itself.
                const q = game.goods_queue || [];
                const TOTAL = 5;                             // GOODS_PER_PHASE
                const used = Math.max(0, TOTAL - q.length);  // dealt so far this phase
                return (
                  <span className="coc-pill coc-goods-left" data-goodsleft="1" title="This phase's goods — one is handed out each round; faded = already used">
                    {Array.from({ length: used }).map((_, i) => (
                      <span key={"u" + i} className="coc-tile goods coc-goods-used"
                        title={"Round " + (i + 1) + " goods — already handed out"} aria-hidden="true"></span>
                    ))}
                    {q.map((g, i) => (
                      <span key={g.id || i} className="coc-tile goods" title={tileDesc({ kind: "goods", color: g.color }, board)}
                        style={{ background: GOODS_HEX[g.color] }}>{goodsSellNum(g.color)}</span>
                    ))}
                  </span>
                );
              })()}
            </div>
            <div className="coc-whitedie">
              <div className="coc-die white" title="White die — sets which depot gets goods this phase"><Pips n={game.white_die} /></div>
            </div>
          </div>

          {/* Turn-order track: pinned flush to the panel's upper-LEFT (it sits in the
              gutter beside the centered board — it used to overlap depot 1 after the
              board was narrowed). On mobile it reflows to a block above the board. */}
          <div className="coc-track-block">
            <div className="coc-track">
              <span className="coc-track-lbl">Turn order</span>
              <div className="coc-track-spaces">
                {(game.track || []).map((stack, s) => (
                  <div className="coc-track-space" key={s}>
                    <div className="coc-track-stack">
                      {[...stack].reverse().map((pid) => (
                        <div key={pid} className={`coc-track-token${pid === game.start_player ? " start" : ""}`}
                          style={{ background: pid === myId ? "var(--gold)" : "#5a86c4", color: pid === myId ? "#15100a" : "#fff" }}
                          title={`${pid === myId ? "You" : (players[pid] || "Opp")}${pid === game.start_player ? " — goes first" : ""}`}>
                          {pid === myId ? "You" : (players[pid] || "Opp")}
                        </div>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>

          <div className="coc-board-hex" ref={boardHexRef}>
            {[1, 2, 3, 4, 5, 6].map((d, idx) => {
              const depot = game.depots[String(d)];
              // Highlight a depot only while a matching die is SELECTED (not just
              // present). Monastery 12 lets you take from a depot adjacent to the die
              // value (as a free worker shift), with 1<->6 wrapping — so highlight those too.
              const selDieVal = (selDie != null && dice && !dice.used[selDie]) ? dice.values[selDie] : null;
              const hasM12 = (me?.monastery_effects || []).includes(12);
              const matchVals = selDieVal == null ? []
                : (hasM12 ? [selDieVal, selDieVal === 6 ? 1 : selDieVal + 1, selDieVal === 1 ? 6 : selDieVal - 1] : [selDieVal]);
              const match = !pendingMine && matchVals.includes(d);
              const pos = DEPOT_POS[idx];
              const bCands = buildingPickMine ? buildingDepotCands(d) : [];
              const pickable = shipPickMine ? shipCands.includes(d)
                : buildingPickMine ? bCands.length > 0
                : goodsPickMine ? d === goodsPickDepot     // pulse the pick depot; click its token
                : false;
              const depotPick = shipPickMine ? () => shipPick(d)
                : (buildingPickMine && bCands.length === 1 ? () => buildingPick(bCands[0]) : undefined);
              const isSide = d !== 1 && d !== 4;           // ring-side depots stack tiles vertically
              // Top-half side depots (2/6) render goods ABOVE the tiles so the pile grows UP
              // into empty board space; bottom side depots (3/5) keep goods below (grow down).
              const topSide = isSide && pos.top < 50;
              // Side depots anchor to the board's edges (left for 5/6 — the same gutter
              // as the turn-order track — right for 2/3) instead of centering on left%;
              // top/bottom depots (coc-depot-tb) keep the horizontal tile row.
              const anchor = isSide ? (pos.left < 50 ? " coc-anchor-l" : " coc-anchor-r") : "";
              // The depot-number die sits OUTSIDE the box on the edge facing the central black
              // depot (as before). For side depots it's pinned to the BETWEEN-TILES level — a
              // FIXED offset from the pinned inner tile (HEX_H+9 = the gap center, −12 to center
              // the 24px die on it) — so it never moves as goods grow (0 change at 0 goods, when
              // that level IS the box center). Top/bottom depots keep it just beyond the near edge.
              const vx = 50 - pos.left, vy = 50 - pos.top, G = 6;
              let numStyle;
              if (isSide) {
                const edge = vx < 0
                  ? { left: 0, transform: `translateX(calc(-100% - ${G}px))` }
                  : { left: "100%", transform: `translateX(${G}px)` };
                numStyle = topSide ? { ...edge, bottom: `${HEX_H - 3}px` } : { ...edge, top: `${HEX_H - 3}px` };
              } else {
                numStyle = vy < 0
                  ? { left: "50%", top: 0, transform: `translate(-50%, calc(-100% - ${G}px))` }
                  : { left: "50%", top: "100%", transform: `translate(-50%, ${G}px)` };
              }
              return (
                <div key={d} data-depot={d} className={`coc-depot${isSide ? " coc-depot-side" : " coc-depot-tb"}${topSide ? " coc-depot-topside" : ""}${anchor}${match ? " match" : ""}${pickable ? " coc-depot-pick" : ""}`}
                  style={{ left: isSide ? (pos.left < 50 ? 0 : "100%") : `${pos.left}%`, top: `${pos.top}%` }}
                  onClick={depotPick}
                  title={pickable ? (shipPickMine ? `Take all goods from depot ${d}` : buildingPickMine ? `Take the highlighted tile from depot ${d}` : `Click a goods token to take that type`) : undefined}>
                  <span className="coc-minidie" style={numStyle} title={`Depot ${d} — take a tile here with a die showing ${d}`}><Pips n={d} /></span>
                  <div className="coc-tilewrap">
                    <div className={`coc-tiles-inner${(game.num_players || 2) === 3 ? " coc-tiles-tri" : ""}`}>
                    {depotSlots(d, depot.hexes).map((slot, i) => slot.tile ? (
                      <div key={slot.tile.id} className={`coc-tile${buildingPickMine && buildingCands.includes(slot.tile.id) ? " coc-tile-pick" : ""}`} style={{ background: TILE_HEX[slot.tile.color] }}
                        onContextMenu={(e) => inspect(e, tileDesc(slot.tile, board))}
                        title={tileDesc(slot.tile, board)} onClick={(e) => clickDepotTile(d, slot.tile, e)}>
                        <TileArt tile={slot.tile} px={HEX_W} />
                      </div>
                    ) : (
                      <div key={`ghost-${i}`} className="coc-tile coc-tile-ghost"
                        style={{ background: TILE_HEX[slot.ghost] }}
                        title={`${COLOR_TYPE_LABEL[slot.ghost] || "Tile"} taken — this depot refills a ${COLOR_TYPE_LABEL[slot.ghost]?.toLowerCase() || ""} tile here each phase`}>
                      </div>
                    ))}
                    </div>
                    <div className="coc-depot-goods">
                      {depot.goods.map((gt) => {
                        const canPickGood = goodsPickMine && d === goodsPickDepot && goodsPickColors.includes(gt.color);
                        return (
                          <div key={gt.id} data-depotgood={gt.id} className={`coc-tile goods${canPickGood ? " coc-tile-pick" : ""}`} style={{ background: GOODS_HEX[gt.color] }}
                            onContextMenu={(e) => inspect(e, tileDesc(gt, board))}
                            title={canPickGood ? `Take all #${goodsSellNum(gt.color)} goods` : tileDesc(gt, board)}
                            onClick={(e) => { if (canPickGood) { e.stopPropagation(); goodsPick(gt.color); } else if (!shipPickMine) setToast(tileDesc(gt, board)); }}>{goodsSellNum(gt.color)}</div>
                        );
                      })}
                    </div>
                  </div>
                </div>
              );
            })}
            {/* Central black depot: 2 columns × (player-count) rows — a FIXED size that never
                shrinks as tiles are bought (explicit rows leave empty cells for taken tiles). */}
            <div data-blackdepot="1" className="coc-depot coc-black-center"
              style={{ display: "grid", gridTemplateColumns: `repeat(2, ${HEX_W}px)`, gridTemplateRows: `repeat(${game.num_players || 2}, ${HEX_H}px)`, gap: `${BLACK_GAP}px`, justifyContent: "center", alignContent: "start", width: 2 * HEX_W + BLACK_GAP + 2 * BLACK_PAD }}
              title="Central black depot — buy one tile per turn for 2 silver">
              {game.black_depot.map((t) => (
                <div key={t.id} className={`coc-tile${silverArmed ? " coc-tile-pick" : ""}`} style={{ background: TILE_HEX[t.color], opacity: .9 }}
                  onContextMenu={(e) => inspect(e, `${tileDesc(t, board)}  (Black depot: buy for 2 silver.)`)}
                  title={silverArmed ? `Buy ${tileName(t)} for 2 silver` : `${tileDesc(t, board)}  (Black depot: buy for 2 silver.)`} onClick={() => clickBlackTile(t)}>
                  <TileArt tile={t} px={HEX_W} />
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* 3-col: the two duchies sit in a row and the LOG fills beneath them inside this
            area, which stretches to the (taller) board column's height — so the log scrolls
            instead of stretching the board. Both wrappers are display:contents below 1280,
            so the narrower layouts keep treating the duchies + log as direct grid children. */}
        <div className="coc-duchy-area">
        <div className="coc-duchy-row">

        {/* Your area: dice/storage/goods controls, your duchy board below */}
        <div className="coc-panel">
          <div className="coc-duchy-head">
            {/* At game end show the FINAL score (leftover resources + monastery
                end-game bonuses folded in) so it matches the top score bar. */}
            <h3>Your Duchy — {over && fscore?.[myId] != null ? fscore[myId] : (me?.vp ?? 0)} VP</h3>
            {/* Always shown during play (not setup/over) so the panel keeps a stable
                height across turns; each button just disables (fades) when it can't act,
                including on the opponent's turn (!myTurnRaw). */}
            {!over && !setupPhase && (
              <div style={{ display: "flex", gap: 8 }}>
                <button className="coc-btn ghost sm" disabled={!myTurnRaw || !selStorage || pendingMine}
                  title="Discard the selected storage tile (back to the box) — free, anytime on your turn"
                  onClick={() => { mv({ type: "discard_storage", tile_id: selStorage }); setSelStorage(null); }}>Discard</button>
                <button className="coc-btn ghost sm" disabled={!myTurnRaw || !hasActed}
                  title={hasActed ? "Undo everything you've done this turn" : "Nothing to undo yet"}
                  onClick={() => { setSelDie(null); setSelStorage(null); setExtraValue(null); setActedThisTurn(false); mv({ type: "undo_turn" }); }}>↩ Undo</button>
                <button className="coc-btn crimson sm" disabled={!myTurnRaw || !bothDiceUsed || pendingMine}
                  title={pendingMine ? "Resolve the pending decision first" : bothDiceUsed ? "End your turn" : "Use both dice before ending your turn"}
                  onClick={() => mv({ type: "end_turn" })}>End Turn</button>
              </div>
            )}
          </div>
          <div className="coc-duchy-layout">
            <div className="coc-duchy-controls">
              {/* dice + resources */}
              <div className="coc-dicebar">
                {dice && [0, 1].map((i) => (
                  <div key={i} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <div className={`coc-die${selDie === i ? " sel" : ""}${dice.used[i] ? " used" : ""}`}
                      onClick={() => { if (!dice.used[i] && !pendingMine) setSelDie(selDie === i ? null : i); }}><Pips n={dice.values[i]} /></div>
                    {!pendingMine && (
                      <div className="coc-die-adj">
                        <button disabled={dice.used[i] || !me || adjustDelta(i, +1) > (me.workers || 0)}
                          title={adjustDelta(i, +1) < 0 ? "Refunds a worker (back toward the roll)" : "Spend a worker to raise this die"}
                          onClick={() => adjustDie(i, +1)}>▲</button>
                        <button disabled={dice.used[i] || !me || adjustDelta(i, -1) > (me.workers || 0)}
                          title={adjustDelta(i, -1) < 0 ? "Refunds a worker (back toward the roll)" : "Spend a worker to lower this die"}
                          onClick={() => adjustDie(i, -1)}>▼</button>
                      </div>
                    )}
                  </div>
                ))}
                <div className="coc-resbar">
                  <span className="coc-token-chip"
                    title={canTakeWorkers ? "Take 2 workers with the selected die"
                      : canUseM6 ? "Monastery #6: spend 1 silver to gain 2 workers (unlimited)"
                      : "Workers — spent to adjust dice. Select a die, then click here to take 2 workers."}>
                    <span className={`coc-token worker${(canTakeWorkers || canUseM6) ? " coc-arm" : ""}`} data-workers="1"
                      onClick={canTakeWorkers ? () => mv({ type: "take_workers", die_index: selDie })
                        : canUseM6 ? () => mv({ type: "monastery6_take" }) : undefined}>⚒</span><b>{me?.workers ?? 0}</b>
                  </span>
                  <span className="coc-token-chip"
                    title={canBuyBlack ? (silverArmed ? "Buy armed — click a tile in the central black depot (2 silver). Click again to cancel." : "Click, then a tile in the central black depot to buy it for 2 silver") : "Silver — spent to buy black-depot tiles"}>
                    <span className={`coc-token silver${canBuyBlack ? " coc-arm" : ""}${silverArmed ? " coc-on" : ""}`} data-silver="1"
                      onClick={canBuyBlack ? () => setSilverArmed((a) => !a) : undefined}>⛃</span><b>{me?.silver ?? 0}</b>
                  </span>
                </div>
              </div>

              {/* storage + goods, side by side */}
              <div className="coc-stor-goods">
                <div>
                  <div className="coc-storage" data-storage="1">
                    {[0, 1, 2].map((i) => {
                      const t = me?.storage?.[i];
                      if (!t) return <div key={i} data-storage-slot={i} className="coc-stt empty" style={{ background: "var(--surface2)" }} />;
                      const isSel = selStorage === t.id;
                      return (
                        <div key={t.id} className={`coc-stt-wrap${isSel ? " sel" : ""}`}>
                          <div data-storage-slot={i} className={`coc-stt${isSel ? " sel" : ""}`} style={{ background: TILE_HEX[t.color] }}
                            onContextMenu={(e) => inspect(e, tileDesc(t, board))} title={tileDesc(t, board)}
                            onClick={() => {
                              // Only SELECT a storage tile when there's a way to place it
                              // (a die chosen, or an extra-action value, or a town-hall extra
                              // placement). Otherwise a tap just shows the description.
                              const canPlace = pendingMine
                                ? (game.pending_kind === "townhall_place" || (inExtra && extraValue != null))
                                : (selDie != null);
                              if (canPlace) setSelStorage(isSel ? null : t.id);
                              else setToast(tileDesc(t, board));
                            }}>
                            <TileArt tile={t} px={70} />
                          </div>
                        </div>
                      );
                    })}
                  </div>
                </div>
                <div>
                  <div className="coc-goods-row" data-mygoods="1">
                    {me && Object.entries(me.goods).map(([c, n]) => {
                      const sellable = canSellGood(c);
                      return (
                        <span key={c} data-goodchip={c} className={`coc-goods-chip${sellable ? " coc-goods-pick" : ""}`}
                          onContextMenu={(e) => inspect(e, tileDesc({ kind: "goods", color: c }, board))}
                          title={sellable ? `Sell #${goodsSellNum(c)} goods for silver` : tileDesc({ kind: "goods", color: c }, board)}
                          onClick={() => sellable ? sellGood(c) : setToast(tileDesc({ kind: "goods", color: c }, board))}>
                          <span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}
                        </span>
                      );
                    })}
                    <span className={`coc-goods-sold${(me?.sold_goods?.length || 0) ? "" : " none"}`}
                      onContextMenu={(e) => inspect(e, soldGoodsDesc(me?.sold_goods?.length || 0))}
                      title={soldGoodsDesc(me?.sold_goods?.length || 0)}
                      onClick={() => setToast(soldGoodsDesc(me?.sold_goods?.length || 0))}>
                      <span className="coc-goods-back" />×{me?.sold_goods?.length || 0}
                    </span>
                  </div>
                  {me?.claimed_bonus?.length > 0 && (
                    <div className="coc-claimed-row" data-myclaimed="1" title="Color-bonus tiles you've claimed">
                      {me.claimed_bonus.map((bt, i) => (
                        <span key={i} className={`coc-claimed-badge${bt.vp > (game.num_players || 2) ? " large" : " small"}`}
                          title={`${colorLabel(bt.color)} color bonus — ${bt.vp} VP (${bt.vp > (game.num_players || 2) ? "large / first" : "small / second"})`}>
                          <BonusTileBadge color={TILE_HEX[bt.color]} />
                        </span>
                      ))}
                    </div>
                  )}
                </div>
              </div>

              {/* No action row: Discard/Undo/End Turn live in the panel header, selling
                  is click-your-goods, take-2-workers is die -> workers token. The panel
                  therefore matches the opponent panel's height (a deliberate ask). */}
            </div>
            <div className="coc-duchy-board">
              {renderDuchy(me, myTurnRaw)}
            </div>
          </div>
        </div>

        {/* Opponent's area: always on screen (replaces the old View Opponent modal).
            The data-opp* anchors here are the flyer-animation targets. */}
        {opp && (
          <div className="coc-panel">
            <div className="coc-duchy-head">
              <h3>{players[oppId] || "Opponent"} — {over && fscore?.[oppId] != null ? fscore[oppId] : (opp.vp ?? 0)} VP</h3>
              {opponentIds.length > 1 && (
                <div className="coc-opp-tabs" role="tablist">
                  {opponentIds.map((pid) => {
                    const isTurn = !over && (game.pending_pid || game.turn) === pid;
                    return (
                      <button key={pid} type="button"
                        className={`coc-opp-tab${pid === oppId ? " on" : ""}${isTurn ? " turn" : ""}`}
                        onClick={() => setViewOppId(pid)}
                        title={`View ${players[pid] || "player"}'s duchy${isTurn ? " (their turn)" : ""}`}>
                        {players[pid] || "Player"}
                        {over && fscore?.[pid] != null ? <b> {fscore[pid]}</b> : (game.players?.[pid]?.vp != null ? <b> {game.players[pid].vp}</b> : null)}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="coc-oppbar coc-dicebar">
              {oppDice && (<>
                {[0, 1].map((i) => (
                  <div key={i} className={`coc-die${oppDice.used?.[i] ? " used" : ""}`}
                    style={{ cursor: "default" }}><Pips n={oppDice.values[i]} /></div>
                ))}
              </>)}
              <div className="coc-resbar">
                <span className="coc-token-chip" title="Their workers">
                  <span className="coc-token worker" data-opp-workers="1">⚒</span><b>{opp.workers ?? 0}</b>
                </span>
                <span className="coc-token-chip" title="Their silver">
                  <span className="coc-token silver" data-opp-silver="1">⛃</span><b>{opp.silver ?? 0}</b>
                </span>
              </div>
            </div>
            <div className="coc-opp-sections">
              <div>
                <div className="coc-storage">
                  {[0, 1, 2].map((i) => {
                    const t = opp.storage?.[i];
                    if (!t) return <div key={i} data-oppstorage-slot={i} className="coc-stt empty" style={{ background: "var(--surface2)" }} />;
                    return <div key={t.id} data-oppstorage-slot={i} className="coc-stt" style={{ background: TILE_HEX[t.color] }}
                      onContextMenu={(e) => inspect(e, tileDesc(t, board))} title={tileDesc(t, board)} onClick={() => setToast(tileDesc(t, board))}><TileArt tile={t} px={70} /></div>;
                  })}
                </div>
              </div>
              <div>
                <div className="coc-goods-row" data-oppgoods="1">
                  {Object.entries(opp.goods || {}).map(([c, n]) => (
                    <span key={c} data-oppgoodchip={c} className="coc-goods-chip" onContextMenu={(e) => inspect(e, tileDesc({ kind: "goods", color: c }, board))} title={tileDesc({ kind: "goods", color: c }, board)}
                      onClick={() => setToast(tileDesc({ kind: "goods", color: c }, board))}>
                      <span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}
                    </span>
                  ))}
                  <span className={`coc-goods-sold${(opp.sold_goods?.length || 0) ? "" : " none"}`}
                    onContextMenu={(e) => inspect(e, soldGoodsDesc(opp.sold_goods?.length || 0))}
                    title={soldGoodsDesc(opp.sold_goods?.length || 0)}
                    onClick={() => setToast(soldGoodsDesc(opp.sold_goods?.length || 0))}>
                    <span className="coc-goods-back" />×{opp.sold_goods?.length || 0}
                  </span>
                </div>
                {opp?.claimed_bonus?.length > 0 && (
                  <div className="coc-claimed-row" data-oppclaimed="1" title="Color-bonus tiles they've claimed">
                    {opp.claimed_bonus.map((bt, i) => (
                      <span key={i} className={`coc-claimed-badge${bt.vp > (game.num_players || 2) ? " large" : " small"}`}
                        title={`${colorLabel(bt.color)} color bonus — ${bt.vp} VP (${bt.vp > (game.num_players || 2) ? "large / first" : "small / second"})`}>
                        <BonusTileBadge color={TILE_HEX[bt.color]} />
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
            <div className="coc-duchy-board">
              {renderDuchy(opp, false, true)}
            </div>
          </div>
        )}
        </div>

        {/* Move log — fills the area beneath the duchy row (3-col), scrolling internally
            so it never stretches the board. Full width below everything at narrower widths. */}
        <div className="coc-panel coc-log-panel">
          <h3>Log</h3>
          <div className="coc-log">
            {(game.moves || []).map((m, i) => (
              m.type === "phase_end"
                ? <div key={i} className="coc-log-phase">{moveText(m, board)}</div>
                : <div key={i}>
                    {/* phase-round label ("A-1".."E-5"); T# fallback for pre-ph saved games */}
                    <span className="coc-log-t">{m.t ? (m.ph ? `${m.ph}-${m.rd}` : `T${m.t}`) : "·"}</span>
                    {/* base text, then VP (build_gain already states its VP), then the source
                        tile in parens so ability actions end with e.g. "(Market)". */}
                    {m.pid ? `${players[m.pid] || m.pid} ` : ""}{moveText(m, board)}{(m.type !== "build_gain" && m.vp) ? ` (+${m.vp} VP)` : ""}{m.via ? ` (${viaLabel(m.via)})` : ""}
                  </div>
            ))}
          </div>
        </div>
        </div>
        </div>
      </div>

      {/* pending decision modals */}
      {pendingMine && <PendingModal game={game} board={board} me={me} extraValue={extraValue}
        setExtraValue={setExtraValue} mv={mv} goodsForDie={goodsForDie} />}

      {/* Mid-game VP breakdown (click the score). End-of-game bonuses are faded — a
          projection that only counts once the game ends. */}
      {showScores && !over && (
        <div className="coc-modal-bg" onClick={() => setShowScores(false)}>
          <div className="coc-modal coc-review-modal" onClick={(e) => e.stopPropagation()}>
            <h3>Score breakdown</h3>
            <p className="coc-review-hint">End-of-game bonuses are faded — they're projected and only count once the game ends.</p>
            <VpReview order={game.order || Object.keys(players)} players={players} myId={myId}
              scores={roomData?.final_scores || {}} breakdowns={roomData?.vp_breakdown || {}}
              winnerPid={null} projected />
            <div className="coc-modal-row" style={{ marginTop: 12, justifyContent: "flex-end" }}>
              <button className="coc-btn gold sm" onClick={() => setShowScores(false)}>Close</button>
            </div>
          </div>
        </div>
      )}

      {flyers.length > 0 && (
        <div className="coc-fly-layer">
          {flyers.map((f) => (
            f.token ? (
              <div key={f.id} className={`coc-token-flyer ${f.token} ${f.spent ? "spent" : "gain"}`}
                style={{ left: f.left, top: f.top, width: f.w, height: f.h, "--dx": `${f.dx}px`, "--dy": `${f.dy}px` }}>
                {f.token === "worker" ? "⚒" : "⛃"}
              </div>
            ) : f.goods ? (
              <div key={f.id} className="coc-flyer goods"
                style={{ left: f.left, top: f.top, width: f.w, height: f.h, background: GOODS_HEX[f.color] || "#555",
                  "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0 ?? 1, "--s1": f.s1 }}>
                {goodsSellNum(f.color)}
              </div>
            ) : (
              <div key={f.id} className="coc-flyer"
                style={{ left: f.left, top: f.top, width: f.w, height: f.h, background: TILE_HEX[f.tile.color] || "#555",
                  "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": f.s0 ?? 1, "--s1": f.s1 }}>
                <TileArt tile={f.tile} px={f.w} />
              </div>
            )
          ))}
        </div>
      )}

      {phasePop && (
        <div className="coc-phase-pop" key={`${phasePop.from}${phasePop.to}`}>
          <div className="coc-phase-pop-card">
            <div className="coc-phase-pop-sub">Phase {phasePop.from} complete</div>
            <div className="coc-phase-pop-big">Phase {phasePop.to}</div>
            {(phasePop.silver > 0 || phasePop.workers > 0) ? (
              <div className="coc-phase-pop-inc">
                {phasePop.silver > 0 && (
                  <span className="coc-phase-pop-gain"><span className="coc-token silver">⛃</span>+{phasePop.silver}</span>
                )}
                {phasePop.workers > 0 && (
                  <span className="coc-phase-pop-gain"><span className="coc-token worker">⚒</span>+{phasePop.workers}</span>
                )}
                <span className="coc-phase-pop-src">from your mines</span>
              </div>
            ) : null}
          </div>
        </div>
      )}

      {reconnecting && !connected && inLiveGame && (
        <div className="coc-reconnbar"><span className="lby-spinner lby-spinner-sm" /> Reconnecting…</div>
      )}
      {cocRulesModal}
      {toast && <div className="coc-toast">{toast}</div>}
    </div>
  );
}

// ─── VP breakdown (shared by the end-game results + the mid-game score popup) ──
// `projected` = the game is still on, so the end-of-game items are a projection —
// fade them and show the header as the currently-realized VP (not the projected total).
function VpReview({ order, players, myId, scores, breakdowns, winnerPid, projected }) {
  const winners = Array.isArray(winnerPid) ? winnerPid : (winnerPid != null ? [winnerPid] : []);
  return (
    <div className="coc-review-grid">
      {order.map((pid) => {
        const bd = breakdowns[pid] || [];
        const during = bd.filter((i) => i.t != null).sort((a, b) => (a.t - b.t) || 0);
        const ends = bd.filter((i) => i.t == null);
        const total = scores[pid] != null ? scores[pid] : bd.reduce((s, i) => s + i.vp, 0);
        const realized = during.reduce((s, i) => s + i.vp, 0);   // officially-scored so far
        const won = winners.includes(pid);
        return (
          <div key={pid} className={`coc-review-col${won ? " win" : ""}`}>
            <div className="coc-review-hd">
              <span>{(players[pid] || pid)}{pid === myId ? " (you)" : ""}</span>
              <b>{projected ? realized : total} VP</b>
            </div>
            <div className="coc-review-list">
              {bd.length === 0 && <div className="coc-review-empty">No breakdown available for this game.</div>}
              {during.map((i, k) => (
                <Fragment key={`d${k}`}>
                  {/* segment by phase (like the log's phase dividers); items carry ph/rd
                      from the move log — absent on pre-ph saved games (no dividers, T# label) */}
                  {i.ph && i.ph !== during[k - 1]?.ph && (
                    <div className="coc-review-phase">— Phase {i.ph} —</div>
                  )}
                  <div className="coc-review-row">
                    <span className="coc-review-t">{i.ph ? `${i.ph}-${i.rd}` : `T${i.t}`}</span>
                    <span className="coc-review-lbl">{i.label}</span>
                    <span className="coc-review-vp">+{i.vp}</span>
                  </div>
                </Fragment>
              ))}
              {ends.length > 0 && <div className={`coc-review-phase${projected ? " proj" : ""}`}>— End of game{projected ? " (projected)" : ""} —</div>}
              {ends.map((i, k) => (
                <div key={`e${k}`} className={`coc-review-row${projected ? " proj" : ""}`}>
                  <span className="coc-review-t">end</span>
                  <span className="coc-review-lbl">{i.label}</span>
                  <span className="coc-review-vp">+{i.vp}</span>
                </div>
              ))}
              <div className={`coc-review-row coc-review-total${projected ? " proj" : ""}`}>
                <span className="coc-review-t" />
                <span className="coc-review-lbl">{projected ? "Projected total" : "Total"}</span>
                <span className="coc-review-vp">{total}</span>
              </div>
            </div>
          </div>
        );
      })}
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
      <Modal title="Ship — take goods" desc="Click a highlighted depot on the board (or a button below) to take all its goods." interactive>
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
  if (kind === "ship_adjacent_depot") {
    const cands = game.pending?.ctx?.candidates || [];
    return (
      <Modal title="Monastery — adjacent depot" desc="Click a highlighted adjacent depot on the board (or a button below) to also take its goods." interactive>
        <div className="coc-modal-row">
          {cands.map((d) => {
            const n = game.depots[String(d)].goods.length;
            return <button key={d} className="coc-btn outline sm" onClick={() => mv({ type: "ship_adjacent_take", depot: d })}>◆{d} ({n})</button>;
          })}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "goods_pick") {
    const colors = game.pending?.ctx?.colors || [];
    return (
      <Modal title="Choose goods to take" desc="This depot has more goods types than you have free slots. Click a highlighted goods token on the board (or a button below) to take that type; you may take more until your slots are full." interactive>
        <div className="coc-modal-row">
          {colors.map((c) => (
            <button key={c} className="coc-btn outline sm" onClick={() => mv({ type: "goods_pick", color: c })}>
              <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[c], marginRight: 5 }}>{sellNum(c)}</span>#{sellNum(c)} goods
            </button>
          ))}
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
      <Modal title="Take a tile" desc="Click a highlighted tile in a depot on the board (or a button below) to take it into storage." interactive>
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
      <Modal title="Warehouse — sell goods" desc="Click one of your goods (or a button below) to sell it for silver — optional." interactive>
        <div className="coc-modal-row">
          {Object.keys(me.goods).filter((c) => me.goods[c] > 0).map((c) => (
            <button key={c} className="coc-btn outline sm" onClick={() => mv({ type: "warehouse_sell", color: c })}>
              <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[c], marginRight: 5 }}>{sellNum(c)}</span>#{sellNum(c)} goods ×{me.goods[c]}
            </button>
          ))}
          <button className="coc-btn ghost sm" onClick={skip}>Skip</button>
        </div>
      </Modal>
    );
  }
  if (kind === "townhall_place") {
    return (
      <Modal title="Town Hall — extra placement" desc="Select a storage tile, then click a glowing hex to place it (any number)." interactive>
        <div className="coc-modal-row"><button className="coc-btn ghost sm" onClick={skip}>Skip</button></div>
      </Modal>
    );
  }
  if (kind === "extra_action") {
    return (
      <Modal title="Castle — bonus action" desc={extraValue == null ? "Pick a die value, then take an action (depot/board/buttons)." : `Value ${extraValue}: take a hex, place a tile, sell, or take workers.`} interactive>
        <div className="coc-modal-row">
          {[1, 2, 3, 4, 5, 6].map((v) => (
            <button key={v} className={`coc-btn ${extraValue === v ? "gold" : "outline"} sm`} onClick={() => setExtraValue(v)}>{v}</button>
          ))}
        </div>
        {extraValue != null && (
          <div className="coc-modal-row" style={{ marginTop: 10 }}>
            <button className="coc-btn ghost sm" onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "take_workers" } })}>Take 2 Workers</button>
            <button className="coc-btn ghost sm" disabled={!(me.goods[goodsForDie] > 0)} onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } })}>
              Sell{goodsForDie
                ? <> <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[goodsForDie] }}>{sellNum(goodsForDie)}</span> #{sellNum(goodsForDie)} goods{me.goods[goodsForDie] ? ` ×${me.goods[goodsForDie]}` : ""}</>
                : " goods"}</button>
          </div>
        )}
        <div className="coc-modal-row" style={{ marginTop: 10 }}><button className="coc-btn ghost sm" onClick={skip}>Skip bonus</button></div>
      </Modal>
    );
  }
  return null;
}

// `interactive` modals (Town Hall / Castle bonus) must NOT block the board behind
// them — the player resolves them by clicking storage tiles + glowing hexes. So the
// backdrop passes clicks through (pointer-events:none) and the panel is pinned to the
// bottom edge, clear of the depots/storage/duchy.
function Modal({ title, desc, children, interactive }) {
  return (
    <div className={`coc-modal-bg${interactive ? " coc-modal-float" : ""}`}>
      <div className="coc-modal">
        <h3>{title}</h3>
        <p>{desc}</p>
        {children}
      </div>
    </div>
  );
}









