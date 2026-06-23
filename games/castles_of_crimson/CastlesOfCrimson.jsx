import { useState, useEffect, useRef, useCallback } from "react";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const COC_WS = WS_RAW.replace(/\/ws$/, "/coc/ws");
const COC_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/coc");

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

// ─── Tile icons ──────────────────────────────────────────────────────────────
// Little monochrome SVG icons (drawn in a 0..24 box, single color `c`). ship /
// castle / mine sit on dark tiles, so they're drawn in a light glyph; livestock
// animals sit on the light-green pasture, so they're dark with small white facial
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
  const g = tileGlyph(t);
  return g ? <text x={cx} y={cy} textAnchor="middle" dominantBaseline="central"
    fontFamily="'Cinzel', serif" fontWeight="700" fontSize={(box * 0.42).toFixed(1)} fill="#15100a">{g}</text> : null;
}

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }

// Hexagon-ring vertex positions (% of the board box) for the 6 numbered depots,
// depot 1 at top going clockwise; the black depot sits in the center.
const DEPOT_POS = [
  { left: 50, top: 13 },   // 1 top
  { left: 83, top: 35 },   // 2 top-right
  { left: 83, top: 65 },   // 3 bottom-right
  { left: 50, top: 87 },   // 4 bottom
  { left: 17, top: 65 },   // 5 bottom-left
  { left: 17, top: 35 },   // 6 top-left
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
  return { connected, connect, send, disconnect };
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
const css = `
/* Self-hosted fonts (CoC is mounted bare without baseCss, so it carries its own copy;
   the browser dedupes identical @font-face by src url). Metric-matched fallbacks keep
   the layout stable if the real font isn't loaded yet. */
@font-face{font-family:'Cinzel';font-style:normal;font-weight:400 700;font-display:optional;src:url(/fonts/cinzel.latin.woff2) format('woff2')}
@font-face{font-family:'Crimson Pro';font-style:normal;font-weight:300 400;font-display:optional;src:url(/fonts/crimsonpro.latin.woff2) format('woff2')}
@font-face{font-family:'Crimson Pro';font-style:italic;font-weight:300 400;font-display:optional;src:url(/fonts/crimsonpro-italic.latin.woff2) format('woff2')}
@font-face{font-family:'Cinzel Fallback';src:local('Georgia');size-adjust:111.8%}
@font-face{font-family:'Crimson Fallback';src:local('Georgia');size-adjust:87.9%}
/* CoC is mounted bare (the shell early-returns it without Spender's baseCss), so
   reset the body here too — otherwise the browser-default body margin shows an
   unstyled (white) frame around the dark .coc page. */
html,body{margin:0;padding:0;background:#120c0d}
.coc *,.coc *::before,.coc *::after{box-sizing:border-box;margin:0;padding:0}
.coc{--bg:#120c0d;--surface:#1d1416;--surface2:#281a1d;--border:#3e2a2e;--crimson:#a3263a;--crimson-l:#c8455a;
  --gold:#c9a84c;--gold-l:#e8c96a;--text:#ecdfd6;--text-dim:#9c8780;--radius:8px;--radius-lg:14px;
  font-family:'Crimson Pro','Crimson Fallback',Georgia,serif;color:var(--text);background:var(--bg);min-height:100vh}
.coc-wrap{max-width:1100px;margin:0 auto;padding:calc(env(safe-area-inset-top,0px) + 18px) 16px 48px}
.coc-top{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px;padding-bottom:12px;border-bottom:1px solid var(--border)}
.coc-top-left{display:flex;align-items:center;gap:12px;min-width:0}
.coc-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:1.5rem;font-weight:700;color:var(--crimson-l);letter-spacing:.03em;white-space:nowrap}
.coc-user{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.78rem;color:var(--text-dim);letter-spacing:.05em}
/* Lobby banner: full-width (flush to screen edges — lives OUTSIDE the centered .coc-wrap),
   back button far left, game name centered (left/right flex:1 so it's truly centered),
   user far right. */
.coc-top.coc-top-lobby{margin-bottom:0;padding:12px 20px;padding-top:calc(env(safe-area-inset-top,0px) + 12px);background:var(--surface);border-bottom:1px solid var(--border)}
.coc-top-lobby .coc-top-left{flex:1 1 0;justify-content:flex-start}
.coc-top-lobby .coc-title{flex:0 0 auto;text-align:center}
.coc-top-lobby .coc-user{flex:1 1 0;text-align:right}
.coc-top-lobby + .coc-wrap{padding-top:18px}
.coc-btn{display:inline-flex;align-items:center;justify-content:center;gap:6px;padding:9px 16px;border-radius:var(--radius);border:none;cursor:pointer;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;letter-spacing:.05em;font-weight:600;transition:all .15s;white-space:nowrap}
.coc-btn:disabled{opacity:.35;cursor:not-allowed}
.coc-btn.gold{background:var(--gold);color:#120c0d}.coc-btn.gold:hover:not(:disabled){background:var(--gold-l)}
.coc-btn.crimson{background:var(--crimson);color:#fff}.coc-btn.crimson:hover:not(:disabled){background:var(--crimson-l)}
.coc-btn.ghost{background:transparent;color:var(--text-dim);border:1px solid var(--border)}.coc-btn.ghost:hover:not(:disabled){color:var(--text);border-color:var(--text-dim)}
.coc-btn.tool{background:var(--surface2);color:var(--gold-l);border:1px solid var(--gold)}.coc-btn.tool:hover:not(:disabled){background:#3a2a18;color:var(--gold-l)}
.coc-btn.outline{background:transparent;color:var(--gold);border:1px solid var(--gold)}.coc-btn.outline:hover:not(:disabled){background:var(--gold);color:#120c0d}
.coc-btn.sm{padding:6px 11px;font-size:.74rem}
.coc-hero{text-align:center;margin:24px 0 30px}
.coc-hero h1{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2.4rem;color:var(--crimson-l);letter-spacing:.04em}
.coc-hero p{color:var(--text-dim);font-style:italic;margin-top:6px}
.coc-lobby-actions{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:24px}
.coc-vsbot{display:inline-flex;align-items:center;gap:6px;padding:3px 8px 3px 10px;border:1px solid var(--border);border-radius:var(--radius)}
.coc-vsbot-lbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase}
.coc-join{display:flex;gap:8px}
.coc-input{padding:9px 12px;background:var(--surface2);border:1px solid var(--border);border-radius:var(--radius);color:var(--text);font-family:'Cinzel','Cinzel Fallback',serif;letter-spacing:.12em;outline:none;width:130px;text-transform:uppercase}
.coc-input:focus{border-color:var(--gold)}
.coc-section-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;letter-spacing:.18em;color:var(--gold);text-transform:uppercase;margin:18px 0 8px;border-bottom:1px solid var(--border);padding-bottom:6px}
.coc-card{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:12px 14px;display:flex;align-items:center;gap:12px;margin-bottom:8px}
.coc-card-info{flex:1;min-width:0}
.coc-card-title{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.85rem}
.coc-card-meta{font-size:.78rem;color:var(--text-dim)}
.coc-empty{text-align:center;padding:28px 16px;color:var(--text-dim);font-style:italic;font-size:.9rem;background:var(--surface2);border-radius:var(--radius);border:1px dashed var(--border)}
.coc-section-hd{display:flex;justify-content:space-between;align-items:center;margin:18px 0 10px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.coc-section-hd .coc-section-title{margin:0;border:none;padding:0}
.coc-muted{font-size:.74rem;color:var(--text-dim)}
.coc-card-actions{display:flex;align-items:center;gap:8px;flex-shrink:0}
.coc-turn-badge{background:var(--gold);color:#120c0d;padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.12em;font-weight:700;text-transform:uppercase;white-space:nowrap}
.coc-their-badge{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border);padding:3px 10px;border-radius:12px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;text-transform:uppercase;white-space:nowrap}
.coc-spinner{display:inline-block;width:14px;height:14px;border:2px solid var(--border);border-top-color:var(--gold);border-radius:50%;animation:coc-spin .7s linear infinite;vertical-align:middle;margin-right:6px}
@keyframes coc-spin{to{transform:rotate(360deg)}}
.coc-waiting{max-width:420px;margin:60px auto;text-align:center;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:28px}
.coc-code{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;letter-spacing:.3em;color:var(--gold);background:var(--surface2);border:1px dashed var(--border);border-radius:var(--radius);padding:12px;margin:14px 0;cursor:pointer}
/* game */
.coc-game{display:grid;grid-template-columns:1fr;gap:16px}
.coc-statusbar{display:grid;grid-template-columns:1fr auto 1fr;align-items:center;gap:12px;background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:10px 14px}
.coc-status-left{display:flex;align-items:center;gap:14px;flex-wrap:wrap;min-width:0}
.coc-pill{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.72rem;letter-spacing:.06em;color:var(--text-dim)}
.coc-goods-left{display:inline-flex;align-items:center;gap:7px;flex-wrap:wrap}
.coc-goods-left-lbl{text-transform:uppercase;opacity:.7}
.coc-goods-mini{display:inline-flex;align-items:center;gap:3px}
.coc-pill b{color:var(--text)}
.coc-vp{display:flex;gap:14px;justify-self:center}
.coc-vp .v{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.8rem}
.coc-vp .v b{color:var(--gold);font-size:1.05rem}
/* Abandon / View Opponent + the opponent's dice, at the right end of the status bar. */
.coc-status-right{display:flex;align-items:center;gap:10px;justify-self:end;flex-wrap:wrap;justify-content:flex-end}
.coc-oppdice{display:inline-flex;gap:4px;align-items:center}
.coc-oppdie{width:26px;height:26px;border-radius:5px;background:#f3ead8;display:inline-flex;align-items:center;justify-content:center;box-shadow:inset 0 0 0 1px rgba(0,0,0,.3),0 1px 2px rgba(0,0,0,.5)}
.coc-oppdie.used{opacity:.4}
/* Workers / silver resources — a bit larger than the plain pills. */
.coc-res{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.92rem;letter-spacing:.04em;color:var(--text-dim);display:inline-flex;align-items:center;gap:5px}
.coc-res b{color:var(--text)}
.coc-res-ic{font-size:1.15rem;line-height:1}
.coc-panel{background:var(--surface);border:1px solid var(--border);border-radius:var(--radius-lg);padding:14px}
.coc-panel h3{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.68rem;letter-spacing:.16em;color:var(--gold);text-transform:uppercase;margin-bottom:10px}
.coc-depots{display:grid;grid-template-columns:repeat(6,1fr);gap:8px}
.coc-depot{border:1px solid var(--border);border-radius:var(--radius);padding:6px;min-height:78px;background:var(--surface2)}
.coc-depot.match{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold) inset}
/* hexagon board layout */
.coc-board-head{display:flex;justify-content:space-between;align-items:center;margin-bottom:4px}
.coc-board-head h3{margin-bottom:0}
.coc-board-hex{position:relative;width:100%;max-width:760px;margin:6px auto 0;aspect-ratio:1/0.98}
.coc-board-hex .coc-depot{position:absolute;width:31%;min-height:96px;padding:6px;transform:translate(-50%,-50%);display:flex;flex-direction:column;justify-content:center}
/* central black depot: a dark box holding the kite of tiles (positioned absolutely) */
.coc-black-center{left:50%;top:50%;box-sizing:border-box;padding:0!important;border:1px solid var(--gold)!important;background:#0c0809!important;border-radius:8px;min-height:0!important;z-index:1}
.coc-blacklbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.08em;color:var(--gold);text-transform:uppercase}
/* turn-order track — boxed, sat at the board's upper-left (left of depot 1) */
.coc-track-block{position:absolute;left:-15%;top:4%;z-index:3;max-width:360px;background:var(--surface2);border:1px solid var(--gold);border-radius:8px;padding:7px 9px;box-shadow:0 2px 8px rgba(0,0,0,.45)}
.coc-track{display:flex;flex-direction:column;align-items:flex-start;gap:3px;margin:0}
.coc-track-lbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.62rem;letter-spacing:.1em;color:var(--text-dim);text-transform:uppercase;white-space:nowrap}
.coc-track-spaces{display:flex;gap:3px;align-items:stretch}
.coc-track-space{position:relative;width:42px;min-height:58px;border:1px solid var(--border);border-radius:5px;background:var(--surface);display:flex;flex-direction:column;justify-content:flex-end;gap:2px;padding:19px 3px 5px}
.coc-track-snum{position:absolute;top:3px;left:0;right:0;text-align:center;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.64rem;color:var(--text-dim)}
.coc-track-stack{display:flex;flex-direction:column;gap:6px}
.coc-track-token{border-radius:3px;font-family:'Cinzel','Cinzel Fallback',serif;font-size:.56rem;font-weight:700;text-align:center;padding:2px 1px;line-height:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.coc-track-token.start{box-shadow:0 0 0 2px #fff}
.coc-track-cap{display:block;margin:3px 0 0;font-size:.58rem;color:var(--text-dim);font-style:italic}

/* duchy: controls on the left, board on the right */
.coc-duchy-head{display:flex;justify-content:space-between;align-items:center;gap:10px;margin-bottom:10px}
.coc-duchy-head h3{margin-bottom:0}
.coc-duchy-layout{display:flex;gap:20px;align-items:flex-start}
.coc-duchy-controls{flex:1 1 0;min-width:240px;display:flex;flex-direction:column;gap:14px}
.coc-duchy-board{flex:0 0 auto;width:clamp(300px,50%,560px)}
.coc-duchy-board .coc-hexsvg{max-width:100%;margin:0}
@media (max-width:760px){.coc-duchy-layout{flex-direction:column}.coc-duchy-board{width:100%}}
.coc-depot-n{display:flex;justify-content:center;margin-bottom:5px}
.coc-minidie{position:absolute;transform:translate(-50%,-50%);z-index:3;pointer-events:none;display:inline-flex;align-items:center;justify-content:center;width:24px;height:24px;background:#f3ead8;color:#15100a;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:.82rem;border-radius:5px;box-shadow:inset 0 0 0 1px rgba(0,0,0,.3),0 1px 3px rgba(0,0,0,.55)}
/* Phone: the hexagonal depot ring + absolutely-positioned turn-order track overflow
   on narrow screens (fixed 70px hex tiles can't fit a 31%-wide depot box). Reflow the
   shared board into a stack — turn order on top, the 6 numbered depots in a 2-col grid,
   the black depot centered below. !important beats the inline left/top/transform. */
@media (max-width:600px){
  .coc-board-hex{display:grid;grid-template-columns:1fr 1fr;gap:8px;justify-items:center;aspect-ratio:auto;max-width:none;margin-top:6px}
  .coc-board-hex .coc-track-block{position:static;left:auto;top:auto;max-width:none;grid-column:1/-1;justify-self:stretch;margin:0;padding:6px 7px}
  /* shrink the 7 turn-order spaces so 0-6 fit on one row */
  .coc-track-spaces{flex-wrap:wrap;gap:2px}
  .coc-track-space{width:36px;min-height:50px;padding:16px 2px 4px}
  /* zoom shrinks each depot card AND the black depot's inline-px diamond consistently,
     and (unlike transform) reduces the layout footprint so the board is more compact */
  .coc-board-hex .coc-depot{zoom:.82}
  .coc-board-hex .coc-depot:not(.coc-black-center){position:relative;left:auto!important;top:auto!important;transform:none!important;width:auto!important;min-height:0}
  .coc-board-hex .coc-minidie{position:static!important;left:auto!important;top:auto!important;transform:none!important;margin:0 auto 6px}
  .coc-board-hex .coc-black-center{position:relative;grid-column:1/-1;justify-self:center;left:auto!important;top:auto!important;transform:none!important}
  /* status bar: the 3-zone grid is too tight on phones — stack the left group on its
     own row, then center the score + right group (Abandon/View Opp/opp dice) below */
  .coc-statusbar{display:flex;flex-wrap:wrap;justify-content:center}
  .coc-status-left{width:100%;justify-content:center}
  .coc-status-right{justify-content:center}
  /* lobby header: the big crimson title is redundant with the hero h1 below and
     overlaps the username on narrow screens — drop it on phones, shrink the hero */
  .coc-top-lobby .coc-title{display:none}
  .coc-hero{margin:16px 0 22px}
  .coc-hero h1{font-size:1.9rem}
}
.coc-tilewrap{display:flex;flex-wrap:wrap;gap:6px;justify-content:center}
.coc-animals{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:1px;line-height:0}
.coc-glyph{font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:#15100a;line-height:1}
.coc-fo{width:100%;height:100%;display:flex;align-items:center;justify-content:center}
.coc-tile{width:70px;height:81px;border:none;cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:1.05rem;font-family:'Cinzel','Cinzel Fallback',serif;color:#15100a;font-weight:700;transition:transform .1s;line-height:1;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)}
.coc-tile:hover{transform:scale(1.1)}
.coc-tile.goods{width:34px;height:34px;border-radius:4px;clip-path:none;color:#fff;font-size:.82rem;text-shadow:0 1px 2px rgba(0,0,0,.7)}
/* Ghost: a taken tile leaves a colored hex OUTLINE (its type color) so the fixed
   per-phase depot layout stays memorable. The element is a full-color hex; the
   ::after carves the center back to the depot surface, leaving a colored rim. */
.coc-tile-ghost{cursor:default;position:relative;opacity:.7}
.coc-tile-ghost:hover{transform:none}
.coc-tile-ghost::after{content:"";position:absolute;inset:3px;background:var(--surface2);clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%)}
.coc-whitedie{display:flex;align-items:center;gap:6px;margin-left:auto}
.coc-whitedie .lbl{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.66rem;letter-spacing:.06em;color:var(--text-dim);text-transform:uppercase}
.coc-dicebar{display:flex;flex-wrap:wrap;align-items:center;gap:10px}
.coc-die{width:46px;height:46px;border-radius:8px;background:#f3ead8;color:#1a1010;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;font-size:1.3rem;display:flex;align-items:center;justify-content:center;cursor:pointer;border:2px solid transparent;position:relative}
.coc-die.sel{border-color:var(--gold);box-shadow:0 0 8px rgba(201,168,76,.6)}
.coc-die.used{opacity:.35;cursor:not-allowed}
.coc-die.white{background:#fff;cursor:default}
.coc-die-adj{display:flex;flex-direction:column;gap:2px}
.coc-die-adj button{width:20px;height:20px;font-size:.7rem;line-height:1;border:1px solid var(--border);background:var(--surface2);color:var(--text);border-radius:4px;cursor:pointer}
.coc-die-adj button:disabled{opacity:.3;cursor:not-allowed}
/* Die faces rendered as dots/pips (1-6) instead of a numeral; scales with the die. */
.coc-pips{display:grid;grid-template-columns:repeat(3,1fr);grid-template-rows:repeat(3,1fr);width:82%;height:82%}
.coc-pip{place-self:center;width:62%;height:62%;border-radius:50%}
.coc-pip.on{background:#15100a;box-shadow:inset 0 0 1px rgba(0,0,0,.35)}
/* Bordered hexes (depots + storage) for a bit of depth: a crisp ~1px edge all around
   the clip-path hex (separates adjacent tiles) + a soft drop shadow to lift them. */
.coc-tile,.coc-stt{position:relative;filter:drop-shadow(0 1.5px 1px rgba(0,0,0,.55))}
.coc-tile.goods{filter:none}     /* goods are small squares, not hexes */
.coc-tile-ghost{filter:none}     /* ghost placeholders stay subtle */
/* Glossy bevel along each hex's edges (light top-left -> dark bottom-right) so the
   flat single-color tiles read as raised/3D rather than dull. Clipped to the hex,
   inert to clicks; excludes goods squares, ghost placeholders, and empty slots. */
.coc-tile:not(.goods):not(.coc-tile-ghost)::after,.coc-stt:not(.empty)::after{content:"";position:absolute;inset:0;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);background:linear-gradient(150deg,rgba(255,255,255,.62) 0%,rgba(255,255,255,.16) 16%,rgba(255,255,255,0) 34%,rgba(0,0,0,.06) 56%,rgba(0,0,0,.32) 84%,rgba(0,0,0,.6) 100%);pointer-events:none}
.coc-storage{display:flex;gap:6px;flex-wrap:wrap}
.coc-stt{width:70px;height:81px;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);cursor:pointer;display:flex;align-items:center;justify-content:center;font-size:1.05rem;font-family:'Cinzel','Cinzel Fallback',serif;font-weight:700;color:#15100a;transition:transform .1s}
.coc-stt:hover{transform:scale(1.08)}
.coc-stt.empty{cursor:default}
.coc-stt.sel{filter:drop-shadow(0 0 3px var(--gold)) drop-shadow(0 0 2px var(--gold))}
/* Tile-move animation overlay (depot->storage, storage->duchy) */
.coc-fly-layer{position:fixed;inset:0;pointer-events:none;z-index:140}
.coc-flyer{position:fixed;display:flex;align-items:center;justify-content:center;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);filter:drop-shadow(0 2px 4px rgba(0,0,0,.6));will-change:transform;animation:coc-fly .5s cubic-bezier(.4,.05,.25,1) forwards}
.coc-flyer::after{content:"";position:absolute;inset:0;clip-path:polygon(50% 0%,100% 25%,100% 75%,50% 100%,0% 75%,0% 25%);background:linear-gradient(150deg,rgba(255,255,255,.62) 0%,rgba(255,255,255,.16) 16%,rgba(255,255,255,0) 34%,rgba(0,0,0,.06) 56%,rgba(0,0,0,.32) 84%,rgba(0,0,0,.6) 100%);pointer-events:none}
@keyframes coc-fly{from{transform:translate(0,0) scale(var(--s0,1))}to{transform:translate(var(--dx),var(--dy)) scale(var(--s1,1))}}
.coc-goods-row{display:flex;gap:8px;flex-wrap:wrap;align-items:center}
.coc-goods-chip{display:flex;align-items:center;gap:4px;font-size:.78rem;color:var(--text-dim);cursor:pointer}
.coc-actions{display:flex;flex-wrap:wrap;gap:8px;margin-top:12px}
.coc-setup-banner{background:rgba(212,160,74,.14);border:1px solid var(--gold);border-radius:8px;padding:9px 12px;margin-bottom:12px;font-size:.85rem;line-height:1.35}
.coc-hexsvg{width:100%;max-width:520px;display:block;margin:0 auto}
.coc-hex{cursor:default;transition:opacity .12s}
.coc-hex.legal{cursor:pointer}
.coc-hex.legal:hover{opacity:.8}
.coc-modal-bg{position:fixed;inset:0;background:rgba(0,0,0,.6);display:flex;align-items:center;justify-content:center;z-index:50;padding:16px}
.coc-modal{background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:20px;max-width:440px;width:100%}
.coc-modal h3{font-family:'Cinzel','Cinzel Fallback',serif;color:var(--gold);font-size:1rem;margin-bottom:6px}
.coc-modal p{color:var(--text-dim);font-size:.88rem;margin-bottom:14px}
.coc-modal-row{display:flex;flex-wrap:wrap;gap:8px}
/* non-blocking variant: clicks fall through to the board; panel pinned to the bottom */
.coc-modal-float{background:transparent;pointer-events:none;align-items:flex-end;padding-bottom:16px}
.coc-modal-float .coc-modal{pointer-events:auto;max-width:560px;box-shadow:0 8px 30px rgba(0,0,0,.7)}
.coc-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);background:var(--crimson);color:#fff;padding:10px 18px;border-radius:var(--radius);font-family:'Cinzel','Cinzel Fallback',serif;font-size:.82rem;z-index:60;box-shadow:0 6px 20px rgba(0,0,0,.5);max-width:min(92vw,460px);text-align:center;line-height:1.35}
.coc-winner{max-width:460px;margin:50px auto;text-align:center;background:var(--surface);border:1px solid var(--gold);border-radius:var(--radius-lg);padding:30px}
.coc-winner h2{font-family:'Cinzel','Cinzel Fallback',serif;font-size:2rem;color:var(--gold)}
.coc-log{max-height:150px;overflow:auto;font-size:.78rem;color:var(--text-dim)}
.coc-log div{padding:2px 0;border-bottom:1px solid rgba(62,42,46,.4)}
.coc-turnbadge{font-family:'Cinzel','Cinzel Fallback',serif;font-size:.74rem;padding:4px 10px;border-radius:12px;letter-spacing:.05em}
.coc-turnbadge.you{background:var(--gold);color:#120c0d}
.coc-turnbadge.them{background:var(--surface2);color:var(--text-dim);border:1px solid var(--border)}
.coc-board-pick{margin:4px 0 8px}
.coc-board-pick .coc-section-title{display:flex;align-items:center;gap:8px}
.coc-board-grid{display:flex;gap:8px;overflow-x:auto;padding:6px 2px 8px}
.coc-bthumb{flex:0 0 auto;width:86px;background:var(--surface2);border:2px solid var(--border);border-radius:10px;padding:5px 5px 4px;cursor:pointer;display:flex;flex-direction:column;align-items:center;gap:3px;transition:border-color .15s,transform .1s}
.coc-bthumb:hover{transform:translateY(-2px)}
.coc-bthumb.sel{border-color:var(--gold);box-shadow:0 0 0 1px var(--gold)}
.coc-bthumb-svg{width:72px;height:66px;display:block}
.coc-bthumb-name{font-size:.6rem;color:var(--text-dim);text-align:center;line-height:1.05;font-family:'Cinzel','Cinzel Fallback',serif}
.coc-bthumb.sel .coc-bthumb-name{color:var(--gold)}
`;

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
// mini-dice). White dots with a thin dark rim so they show on any hex colour.
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
// Central black depot: its (up to 4) tiles sit in a kite — 1 top, 2 middle,
// 1 bottom. Horizontal offsets use HEX_W, vertical offsets use HEX_H so the
// hexes nest into a diamond. BLACK_GAP nudges them apart a touch so the four
// tiles read as separate hexes (edge-to-edge they looked like they overlapped).
const BLACK_GAP = 6;
const BLACK_KITE = [
  { left: 0.5 * HEX_W + 0.5 * BLACK_GAP, top: 0 },                         // top
  { left: 0,                             top: 0.75 * HEX_H + BLACK_GAP },  // middle-left
  { left: HEX_W + BLACK_GAP,             top: 0.75 * HEX_H + BLACK_GAP },  // middle-right
  { left: 0.5 * HEX_W + 0.5 * BLACK_GAP, top: 1.5 * HEX_H + 2 * BLACK_GAP }, // bottom
];
// Breathing room (px) between the kite and the black box border around it.
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

export default function CastlesOfCrimson({ myId, authUser, onExit }) {
  const [board, setBoard] = useState(null);            // {spaces, colors, castle, ...}
  const [screen, setScreen] = useState("lobby");        // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState([]);
  const [activeGames, setActiveGames] = useState([]);   // ALL in-progress games (yours + others')
  const [loadingGames, setLoadingGames] = useState(false);
  const [joinCode, setJoinCode] = useState("");
  const [toast, setToast] = useState("");
  const [reviewing, setReviewing] = useState(false);

  // interaction state
  const [selDie, setSelDie] = useState(null);
  const [selStorage, setSelStorage] = useState(null);
  const [actedThisTurn, setActedThisTurn] = useState(false);  // did I take any action this turn? (gates Undo)
  const [extraValue, setExtraValue] = useState(null);
  const [viewOpp, setViewOpp] = useState(false);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [myBoard, setMyBoard] = useState("1");          // board the local player picked
  const [oppBoard, setOppBoard] = useState("1");        // board chosen for the bot (vs-AI)
  const [flyers, setFlyers] = useState([]);             // tile-move animations (depot->storage, storage->duchy)
  const animSnap = useRef(null);                        // prev snapshot for diffing my tile moves
  const flyerSeq = useRef(0);

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
  // Setup phase: each player places a starting castle on a crimson (castle) space before
  // dice are rolled. `setupMine` = it's my turn to choose.
  const setupPhase = !!game && game.phase === "setup";
  const setupMine = setupPhase && !over && game.turn === myId;

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

  // fetch every selectable board layout once (shared meta + per-board spaces)
  useEffect(() => {
    fetch(`${COC_HTTP}/boards`).then((r) => r.json()).then((d) => {
      if (!d.ok) return;
      const byId = {};
      (d.boards || []).forEach((b) => { byId[b.id] = b; });
      setBoard({ ...d, byId });
    }).catch(() => {});
  }, []);

  // Resolve the hex layout for a given board id (falls back to the default board).
  const boardSpaces = useCallback((boardId) => {
    const by = board?.byId || {};
    return (by[boardId] || by[board?.default_board] || {}).spaces || {};
  }, [board]);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${COC_HTTP}/games`).then((r) => r.json()).then((d) => setOpenGames(d.games || []))
      .catch(() => {}).finally(() => setLoadingGames(false));
    // Active Games is PUBLIC: all in-progress games (yours + others', vs-bot or not).
    // The frontend pins yours to the top via myId. No auth needed.
    fetch(`${COC_HTTP}/games/active`).then((r) => r.json()).then((d) => setActiveGames(d.games || [])).catch(() => {});
  }, []);

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
  // "acted this turn" resets only when the turn itself changes (NOT on pending
  // open/close, since opening a pending means you already acted).
  useEffect(() => { setActedThisTurn(false); }, [game?.turn, game?.round, game?.phase_letter]);

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
    const movesLen = (game.moves || []).length;
    const prev = animSnap.current;
    animSnap.current = { loc, storageIds, duchyIds, movesLen };
    if (!prev) return;                                  // first paint: nothing to animate
    const adv = movesLen - prev.movesLen;
    if (adv < 1 || adv > 6) return;                     // skip initial load / reconnect catch-up
    const rectOf = (spec) => {
      if (!spec) return null;
      const sel = spec.kind === "depot" ? `[data-depot="${spec.d}"]`
        : spec.kind === "black" ? "[data-blackdepot]"
        : spec.kind === "storage" ? "[data-storage]"
        : spec.kind === "slot" ? `[data-storage-slot="${spec.i}"]`
        : spec.kind === "hex" ? `[data-sid="${spec.sid}"]` : null;
      const el = sel && document.querySelector(sel);
      return el ? el.getBoundingClientRect() : null;
    };
    const mk = (tile, src, dest) => {
      const s = rectOf(src), d = rectOf(dest);
      if (!s || !d) return null;
      const W = 58, H = 67;
      const scx = s.left + s.width / 2, scy = s.top + s.height / 2;
      const dcx = d.left + d.width / 2, dcy = d.top + d.height / 2;
      const s1 = dest.kind === "hex" ? Math.max(0.5, Math.min(1, d.width / W)) : 1;
      return { id: `f${flyerSeq.current++}`, tile, left: scx - W / 2, top: scy - H / 2, w: W, h: H, dx: dcx - scx, dy: dcy - scy, s1 };
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
      const f = mk(t, prev.loc[t.id], { kind: "hex", sid });
      if (f) add.push(f);
    }
    if (!add.length) return;
    setFlyers((fs) => [...fs, ...add]);
    const ids = new Set(add.map((f) => f.id));
    setTimeout(() => setFlyers((fs) => fs.filter((f) => !ids.has(f.id))), 560);
  }, [game, me]);
  // Deselect a die once it's been used (its action applied) — adjust_die leaves
  // the die unused, so it stays selected.
  useEffect(() => {
    const d = game?.dice?.[myId];
    if (selDie != null && d && d.used[selDie]) setSelDie(null);
  }, [game, selDie, myId]);

  // ── actions ──
  const startCreate = (vsAi, difficulty = "hard") => {
    const rid = roomCode();
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, {
      action: "create", name: playerName, vs_ai: vsAi,
      board_id: myBoard, opp_board_id: oppBoard,
      ai_difficulty: difficulty,
    });
  };
  const startJoin = (rid) => {
    rid = (rid || "").toUpperCase();
    if (!rid) return;
    setRoomId(rid);
    try { localStorage.setItem("coc_roomId", rid); } catch {}
    connect(`${COC_WS}/${rid}/${myId}`, { action: "join", name: playerName, board_id: myBoard });
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
    send({ action: "move", move });
  };

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
  // Tapping a tile you can't act on yet shows its description (mobile has no hover,
  // so this mirrors the PC title-tooltip — see also clickBlackTile).
  const clickDepotTile = (depot, tile) => {
    if (!pendingMine && !myTurnRaw) { setToast(tileDesc(tile, board)); return; }
    if (pendingMine && game.pending_kind === "building_take_choice") {
      mv({ type: "building_take_choice", tile_id: tile.id }); return;
    }
    if (inExtra) { if (extraValue == null) { setToast(tileDesc(tile, board)); return; } mv({ type: "extra_action", value: extraValue, sub: { type: "take_hex", depot, tile_id: tile.id } }); return; }
    if (selDie == null) { setToast(tileDesc(tile, board)); return; }
    mv({ type: "take_hex", die_index: selDie, depot, tile_id: tile.id });
  };
  const clickBlackTile = (tile) => {
    if (!myTurnRaw || pendingMine) { setToast(`${tileDesc(tile, board)}  ·  buy for 2 silver`); return; }
    mv({ type: "buy_black", tile_id: tile.id });
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
    return (
      <div className="coc"><style>{css}</style>
        <div className="coc-top coc-top-lobby">
          <div className="coc-top-left">
            <button className="coc-btn ghost sm" onClick={onExit}>← Back</button>
          </div>
          <span className="coc-title">Castles of Crimson</span>
          <span className="coc-user">{playerName}</span>
        </div>
        <div className="coc-wrap">
          <div className="coc-hero">
            <h1>Castles of Crimson</h1>
            <p>Build your duchy of crimson estates.</p>
          </div>

          <div className="coc-board-pick">
            <div className="coc-section-title">Your Board <span className="coc-card-meta">— {board.byId?.[myBoard]?.name}</span></div>
            <div className="coc-board-grid">
              {(board.boards || []).map((b) => (
                <BoardThumb key={b.id} spaces={b.spaces} name={b.name}
                  selected={myBoard === b.id} onClick={() => setMyBoard(b.id)} />
              ))}
            </div>
            <div className="coc-section-title">Bot's Board <span className="coc-card-meta">— {board.byId?.[oppBoard]?.name} (Play vs Bot only)</span></div>
            <div className="coc-board-grid">
              {(board.boards || []).map((b) => (
                <BoardThumb key={b.id} spaces={b.spaces} name={b.name}
                  selected={oppBoard === b.id} onClick={() => setOppBoard(b.id)} />
              ))}
            </div>
          </div>

          <div className="coc-lobby-actions">
            <button className="coc-btn gold" onClick={() => startCreate(false)}>+ New Game</button>
            <span className="coc-vsbot">
              <span className="coc-vsbot-lbl">vs Bot</span>
              <button className="coc-btn crimson sm" title="A capable opponent that makes the occasional mistake"
                onClick={() => startCreate(true, "normal")}>Normal</button>
              <button className="coc-btn crimson sm" title="Full-strength search — a real challenge"
                onClick={() => startCreate(true, "hard")}>Hard</button>
            </span>
            <div className="coc-join">
              <input className="coc-input" placeholder="CODE" value={joinCode} maxLength={6}
                onChange={(e) => setJoinCode(e.target.value)} onKeyDown={(e) => e.key === "Enter" && startJoin(joinCode)} />
              <button className="coc-btn outline" onClick={() => startJoin(joinCode)}>Join</button>
            </div>
            <button className="coc-btn ghost sm" onClick={fetchGames}>↻</button>
          </div>

          <div className="coc-section-hd">
            <div className="coc-section-title">Open Games</div>
            <span className="coc-muted">waiting for a second player</span>
          </div>
          {loadingGames && openGames.length === 0 ? (
            <div className="coc-empty"><span className="coc-spinner" />Loading…</div>
          ) : openGames.length === 0 ? (
            <div className="coc-empty">No open games. Create one!</div>
          ) : (
            openGames.map((g) => (
              <div className="coc-card" key={g.id}>
                <div className="coc-card-info">
                  <div className="coc-card-title">{g.host_id === myId ? "Your game" : `${g.host_name}'s game`}</div>
                  <div className="coc-card-meta">{g.id} · {timeAgo(g.created_at)}</div>
                </div>
                <div className="coc-card-actions">
                  {g.host_id === myId
                    ? <>
                        <button className="coc-btn outline sm" onClick={() => resume(g.id)}>Return</button>
                        <button className="coc-btn ghost sm" onClick={() => handleCancel(g.id)}>Cancel</button>
                      </>
                    : <button className="coc-btn gold sm" onClick={() => startJoin(g.id)}>Join</button>}
                </div>
              </div>
            ))
          )}

          {activeGames.length > 0 && (() => {
            // All in-progress games (yours + others'). Yours pinned to the top;
            // each sub-list is already updated_at-desc from the backend.
            const mine = activeGames.filter((g) => g.player1_id === myId || g.player2_id === myId);
            const others = activeGames.filter((g) => g.player1_id !== myId && g.player2_id !== myId);
            const ordered = [...mine, ...others];
            return (
              <>
                <div className="coc-section-hd">
                  <div className="coc-section-title">Active Games</div>
                  <span className="coc-muted">{activeGames.length} in progress</span>
                </div>
                {ordered.map((g) => {
                  const isMine = g.player1_id === myId || g.player2_id === myId;
                  const youP1 = g.player1_id === myId;
                  const turnName = g.turn === g.player1_id ? g.player1_name
                    : (g.turn === g.player2_id ? g.player2_name : null);
                  return (
                    <div className="coc-card" key={g.id}>
                      <div className="coc-card-info">
                        <div className="coc-card-title">
                          {isMine
                            ? <>{youP1 ? `${g.player1_name} (you)` : g.player1_name}{" vs "}{g.player2_name ? (youP1 ? g.player2_name : `${g.player2_name} (you)`) : "waiting…"}</>
                            : <>{g.player1_name} vs {g.player2_name || "waiting…"}</>}
                        </div>
                        <div className="coc-card-meta">{g.id} · {timeAgo(g.updated_at)}</div>
                      </div>
                      <div className="coc-card-actions">
                        {isMine ? (
                          <>
                            {g.turn === myId
                              ? <span className="coc-turn-badge">Your Turn</span>
                              : <span className="coc-their-badge">Their Turn</span>}
                            <button className="coc-btn outline sm" onClick={() => resume(g.id)}>Resume</button>
                          </>
                        ) : (
                          <span className="coc-their-badge">{turnName ? `${turnName}'s turn` : "In progress"}</span>
                        )}
                      </div>
                    </div>
                  );
                })}
              </>
            );
          })()}
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
  const oppDice = oppId ? game.dice?.[oppId] : null;
  // You must use BOTH dice before ending the turn (take-2-workers is always a
  // legal use for an otherwise-stuck die, so this can never soft-lock).
  const bothDiceUsed = !!dice && dice.used[0] && dice.used[1];
  // Something is undoable once you've spent a die / bought black / used monastery 6,
  // or this client recorded an action (covers worker-only die adjusts).
  const hasActed = actedThisTurn || (!!dice && (dice.used[0] || dice.used[1]))
    || !!game.black_depot_used_this_turn || !!game.m6_used_this_turn;
  const renderDuchy = (pdata, interactive) => {
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
    const pad = HEX_S + 4;
    const vb = `${(minX - pad).toFixed(0)} ${(minY - pad).toFixed(0)} ${(maxX - minX + pad * 2).toFixed(0)} ${(maxY - minY + pad * 2).toFixed(0)}`;
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
          let stroke, strokeWidth;
          if (legal) { stroke = "var(--gold)"; strokeWidth = 3; }
          else if (placed) { stroke = "#fff2c0"; strokeWidth = 2.6; }
          else { stroke = "rgba(0,0,0,.4)"; strokeWidth = 1; }
          return (
            <g key={sid} data-sid={interactive ? sid : undefined} className={`coc-hex${legal ? " legal" : ""}`}
              onClick={() => { if (interactive && legal) clickHex(sid, legal); else if (tile) setToast(tileDesc(tile, board)); }}>
              <title>{tile ? tileDesc(tile, board)
                : setupPhase ? (sp.color === "burgundy" ? "Click to place your starting castle here." : `${colorLabel(sp.color)} space (die ${sp.number}).`)
                : `Empty ${colorLabel(sp.color)} space — place a matching tile using die ${sp.number}.`}</title>
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill={fill} fillOpacity={placed ? 1 : 0.5}
                stroke={stroke} strokeWidth={strokeWidth} />
              <polygon points={hexPoints(c.x, c.y, HEX_S - 1.5)} fill={placed ? "url(#coc-raise)" : "url(#coc-socket)"}
                stroke="none" style={{ pointerEvents: "none" }} />
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

  return (
    <div className="coc"><style>{css}</style>
      <div className="coc-wrap">
        <div className="coc-top">
          <div className="coc-top-left">
            <button className="coc-btn ghost sm" onClick={over ? () => setReviewing(false) : leaveToLobby}>← {over ? "Results" : "Menu"}</button>
            <span className="coc-title">Castles of Crimson</span>
          </div>
        </div>

        <div className="coc-statusbar">
          <div className="coc-status-left">
            <span className="coc-pill">Phase <b>{game.phase_letter}</b></span>
            <span className="coc-pill">Round <b>{game.round}/5</b></span>
            {(() => {
              // Goods still to be handed out this game: the undrawn supply + this
              // phase's queued-but-not-yet-placed goods, counted per color.
              const rem = {};
              [...(game.goods_supply || []), ...(game.goods_queue || [])].forEach((g) => { rem[g.color] = (rem[g.color] || 0) + 1; });
              const cols = (board && board.goods_colors) || Object.keys(rem);
              if (!cols.length) return null;
              return (
                <span className="coc-pill coc-goods-left" title="Goods still to be handed out (remaining supply + this phase's queue)">
                  <span className="coc-goods-left-lbl">Goods left</span>
                  {cols.map((c) => (
                    <span key={c} className="coc-goods-mini" title={tileDesc({ kind: "goods", color: c }, board)}>
                      <span className="coc-tile goods" style={{ width: 15, height: 15, fontSize: ".52rem", background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>
                      {rem[c] || 0}
                    </span>
                  ))}
                </span>
              );
            })()}
            <span className={`coc-turnbadge ${myTurnRaw ? "you" : "them"}`}>
              {over ? "Game over"
                : setupPhase ? (setupMine ? "Place your starting castle" : aiThinking ? "Bot is choosing…" : `${players[game.turn] || "Opponent"} is choosing…`)
                : aiThinking ? "Bot is playing…"
                : myTurnRaw ? (pendingMine ? "Your decision" : "Your turn")
                : `${players[game.turn] || "Opponent"}'s turn`}
            </span>
          </div>
          <div className="coc-vp">
            <span className="v">{me ? "You" : ""} <b>{me?.vp ?? 0}</b></span>
            {opp && <span className="v">{players[oppId]} <b>{opp.vp}</b></span>}
          </div>
          <div className="coc-status-right">
            {!over && (confirmAbandon
              ? <>
                  <span className="coc-card-meta">Abandon game?</span>
                  <button className="coc-btn crimson sm" onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>Yes, resign</button>
                  <button className="coc-btn ghost sm" onClick={() => setConfirmAbandon(false)}>No</button>
                </>
              : <button className="coc-btn ghost sm" onClick={() => setConfirmAbandon(true)}>Abandon</button>)}
            <button className="coc-btn outline sm" onClick={() => setViewOpp(true)}>View Opponent</button>
            {oppDice && (
              <span className="coc-oppdice" title={`${players[oppId] || "Opponent"}'s dice`}>
                {[0, 1].map((i) => (
                  <span key={i} className={`coc-oppdie${oppDice.used?.[i] ? " used" : ""}`}><Pips n={oppDice.values[i]} /></span>
                ))}
              </span>
            )}
          </div>
        </div>

        {/* Shared board: 6 numbered depots arranged as a hexagon, black depot centered */}
        <div className="coc-panel">
          <div className="coc-board-head">
            <h3>The Board</h3>
            <div className="coc-whitedie">
              <span className="lbl">White die</span>
              <div className="coc-die white" title="white die (sets the goods depot)"><Pips n={game.white_die} /></div>
            </div>
          </div>

          <div className="coc-board-hex">
            {/* Turn-order track: label on top, positioned at the upper-left (left of depot 1) */}
            <div className="coc-track-block">
              <div className="coc-track">
                <span className="coc-track-lbl">Turn order</span>
                <div className="coc-track-spaces">
                  {(game.track || []).map((stack, s) => (
                    <div className="coc-track-space" key={s}>
                      <span className="coc-track-snum">{s}</span>
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
              <div className="coc-track-cap">furthest right and furthest up goes first · each ship moves you 1 space right</div>
            </div>
            {[1, 2, 3, 4, 5, 6].map((d, idx) => {
              const depot = game.depots[String(d)];
              const match = dice && !pendingMine && [0, 1].some((i) => !dice.used[i] && dice.values[i] === d);
              const pos = DEPOT_POS[idx];
              // Put the number JUST OUTSIDE the box edge that faces the central
              // black depot. Pick the dominant axis of the vector toward center,
              // then sit the square a few px beyond that edge.
              const vx = 50 - pos.left, vy = 50 - pos.top, G = 6;
              let numStyle;
              if (Math.abs(vx) >= Math.abs(vy)) {
                numStyle = vx < 0
                  ? { left: 0, top: "50%", transform: `translate(calc(-100% - ${G}px), -50%)` }
                  : { left: "100%", top: "50%", transform: `translate(${G}px, -50%)` };
              } else {
                numStyle = vy < 0
                  ? { left: "50%", top: 0, transform: `translate(-50%, calc(-100% - ${G}px))` }
                  : { left: "50%", top: "100%", transform: `translate(-50%, ${G}px)` };
              }
              return (
                <div key={d} data-depot={d} className={`coc-depot${match ? " match" : ""}`} style={{ left: `${pos.left}%`, top: `${pos.top}%` }}>
                  <span className="coc-minidie" style={numStyle} title={`Depot ${d} — take a tile here with a die showing ${d}`}><Pips n={d} /></span>
                  <div className="coc-tilewrap">
                    {depotSlots(d, depot.hexes).map((slot, i) => slot.tile ? (
                      <div key={slot.tile.id} className="coc-tile" style={{ background: TILE_HEX[slot.tile.color] }}
                        title={tileDesc(slot.tile, board)} onClick={() => clickDepotTile(d, slot.tile)}>
                        <TileArt tile={slot.tile} px={HEX_W} />
                      </div>
                    ) : (
                      <div key={`ghost-${i}`} className="coc-tile coc-tile-ghost"
                        style={{ background: TILE_HEX[slot.ghost] }}
                        title={`${COLOR_TYPE_LABEL[slot.ghost] || "Tile"} taken — this depot refills a ${COLOR_TYPE_LABEL[slot.ghost]?.toLowerCase() || ""} tile here each phase`}>
                      </div>
                    ))}
                    {depot.goods.map((gt) => (
                      <div key={gt.id} className="coc-tile goods" style={{ background: GOODS_HEX[gt.color] }} title={tileDesc(gt, board)}
                        onClick={() => setToast(tileDesc(gt, board))}>{goodsSellNum(gt.color)}</div>
                    ))}
                  </div>
                </div>
              );
            })}
            <div data-blackdepot="1" className="coc-depot coc-black-center" style={{ width: 2 * HEX_W + BLACK_GAP + 2 * BLACK_PAD, height: 2.5 * HEX_H + 2 * BLACK_GAP + 2 * BLACK_PAD }}
              title="Central black depot — buy one tile per turn for 2 silver">
              {game.black_depot.map((t, i) => {
                const k = BLACK_KITE[i];
                if (!k) return null;   // the black depot holds at most 4 tiles
                return (
                  <div key={t.id} className="coc-tile" style={{ position: "absolute", left: `${k.left + BLACK_PAD}px`, top: `${k.top + BLACK_PAD}px`, background: TILE_HEX[t.color], opacity: .9 }}
                    title={`${tileDesc(t, board)}  (Black depot: buy for 2 silver.)`} onClick={() => clickBlackTile(t)}>
                    <TileArt tile={t} px={HEX_W} />
                  </div>
                );
              })}
            </div>
          </div>
        </div>

        {/* Your area: controls on the left, duchy board on the right */}
        <div className="coc-panel">
          <div className="coc-duchy-head">
            <h3>Your Duchy — {me?.vp ?? 0} VP</h3>
            {game.turn === myId && !over && !setupPhase && (
              <button className="coc-btn ghost sm" disabled={!hasActed}
                title={hasActed ? "Undo everything you've done this turn" : "Nothing to undo yet"}
                onClick={() => { setSelDie(null); setSelStorage(null); setExtraValue(null); setActedThisTurn(false); mv({ type: "undo_turn" }); }}>↩ Undo Turn</button>
            )}
          </div>
          <div className="coc-duchy-layout">
            <div className="coc-duchy-controls">
              {setupPhase && (
                <div className="coc-setup-banner">
                  <b>Starting castle.</b>{" "}
                  {setupMine
                    ? "Click a glowing crimson space to place it — your duchy grows outward from here."
                    : `Waiting for ${players[game.turn] || "your opponent"} to choose…`}
                </div>
              )}
              {/* dice + resources */}
              <div className="coc-dicebar">
                <span className="coc-pill">Your dice</span>
                {dice && [0, 1].map((i) => (
                  <div key={i} style={{ display: "flex", gap: 4, alignItems: "center" }}>
                    <div className={`coc-die${selDie === i ? " sel" : ""}${dice.used[i] ? " used" : ""}`}
                      onClick={() => { if (!dice.used[i] && !pendingMine) setSelDie(selDie === i ? null : i); }}><Pips n={dice.values[i]} /></div>
                    {!pendingMine && (
                      <div className="coc-die-adj">
                        <button disabled={dice.used[i] || !me || me.workers < 1} onClick={() => adjustDie(i, +1)}>▲</button>
                        <button disabled={dice.used[i] || !me || me.workers < 1} onClick={() => adjustDie(i, -1)}>▼</button>
                      </div>
                    )}
                  </div>
                ))}
                <span className="coc-res" style={{ marginLeft: 8 }}><span className="coc-res-ic">⚒</span> Workers <b>{me?.workers ?? 0}</b></span>
                <span className="coc-res"><span className="coc-res-ic">⛃</span> Silver <b>{me?.silver ?? 0}</b></span>
              </div>

              {/* storage + goods */}
              <div style={{ display: "flex", gap: 18, flexWrap: "wrap" }}>
                <div>
                  <div className="coc-pill" style={{ marginBottom: 4 }}>Storage</div>
                  <div className="coc-storage" data-storage="1">
                    {[0, 1, 2].map((i) => {
                      const t = me?.storage?.[i];
                      if (!t) return <div key={i} data-storage-slot={i} className="coc-stt empty" style={{ background: "var(--surface2)" }} />;
                      return (
                        <div key={t.id} data-storage-slot={i} className={`coc-stt${selStorage === t.id ? " sel" : ""}`} style={{ background: TILE_HEX[t.color] }}
                          title={tileDesc(t, board)}
                          onClick={() => {
                            // Only SELECT a storage tile when there's a way to place it
                            // (a die chosen, or an extra-action value, or a town-hall extra
                            // placement). Otherwise a tap just shows the description.
                            const canPlace = pendingMine
                              ? (game.pending_kind === "townhall_place" || (inExtra && extraValue != null))
                              : (selDie != null);
                            if (canPlace) setSelStorage(selStorage === t.id ? null : t.id);
                            else setToast(tileDesc(t, board));
                          }}>
                          <TileArt tile={t} px={70} />
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
                      <span key={c} className="coc-goods-chip" title={tileDesc({ kind: "goods", color: c }, board)}
                        onClick={() => setToast(tileDesc({ kind: "goods", color: c }, board))}>
                        <span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}
                      </span>
                    ))}
                  </div>
                </div>
              </div>

              {/* action buttons */}
              {myTurnRaw && !pendingMine && !setupPhase && (
                <div className="coc-actions">
                  <button className="coc-btn tool sm" disabled={selDie == null} onClick={doTakeWorkers}>Take 2 Workers</button>
                  <button className="coc-btn tool sm" disabled={selDie == null || !(me?.goods?.[goodsForDie] > 0)} onClick={doSell}>
                    Sell{goodsForDie
                      ? <> <span className="coc-tile goods" style={{ display: "inline-flex", width: 15, height: 15, fontSize: ".55rem", background: GOODS_HEX[goodsForDie] }}>{actionValue}</span>{me?.goods?.[goodsForDie] ? ` ×${me.goods[goodsForDie]}` : ""}</>
                      : " goods"}
                  </button>
                  {me?.storage?.length >= 3 && (
                    <button className="coc-btn ghost sm" disabled={!selStorage}
                      title="Storage is full — discard a tile (back to the box) to make room"
                      onClick={() => { mv({ type: "discard_storage", tile_id: selStorage }); setSelStorage(null); }}>
                      Discard
                    </button>
                  )}
                  <button className="coc-btn crimson sm" disabled={!bothDiceUsed}
                    title={bothDiceUsed ? "End your turn" : "Use both dice before ending your turn"}
                    onClick={() => mv({ type: "end_turn" })}>End Turn</button>
                  <span className="coc-card-meta" style={{ alignSelf: "center" }}>
                    {me?.storage?.length >= 3 && selStorage ? "Storage full — Discard frees this slot."
                      : selStorage ? "Click a glowing hex to place."
                      : selDie != null ? "Click a depot tile to take, or a storage tile to place." : "Select a die to act."}
                  </span>
                </div>
              )}
            </div>
            <div className="coc-duchy-board">
              {renderDuchy(me, myTurnRaw)}
            </div>
          </div>
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
                    <div key={i} className={`coc-die${game.dice[oppId].used[i] ? " used" : ""}`} style={{ width: 34, height: 34, fontSize: "1rem" }}><Pips n={v} /></div>
                  ))}
                </div>
              </div>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Storage</div>
                <div className="coc-storage">
                  {[0, 1, 2].map((i) => {
                    const t = opp.storage?.[i];
                    if (!t) return <div key={i} className="coc-stt empty" style={{ background: "var(--surface2)" }} />;
                    return <div key={t.id} className="coc-stt" style={{ background: TILE_HEX[t.color] }} title={tileDesc(t, board)} onClick={() => setToast(tileDesc(t, board))}><TileArt tile={t} px={70} /></div>;
                  })}
                </div>
              </div>
              <div>
                <div className="coc-pill" style={{ marginBottom: 4 }}>Goods</div>
                <div className="coc-goods-row">
                  {Object.entries(opp.goods).length === 0 && <span className="coc-card-meta">none</span>}
                  {Object.entries(opp.goods).map(([c, n]) => (
                    <span key={c} className="coc-goods-chip" title={tileDesc({ kind: "goods", color: c }, board)} onClick={() => setToast(tileDesc({ kind: "goods", color: c }, board))}><span className="coc-tile goods" style={{ background: GOODS_HEX[c] }}>{goodsSellNum(c)}</span>×{n}</span>
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

      {flyers.length > 0 && (
        <div className="coc-fly-layer">
          {flyers.map((f) => (
            <div key={f.id} className="coc-flyer"
              style={{ left: f.left, top: f.top, width: f.w, height: f.h, background: TILE_HEX[f.tile.color] || "#555",
                "--dx": `${f.dx}px`, "--dy": `${f.dy}px`, "--s0": 1, "--s1": f.s1 }}>
              <TileArt tile={f.tile} px={f.w} />
            </div>
          ))}
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
  if (kind === "ship_adjacent_depot") {
    const cands = game.pending?.ctx?.candidates || [];
    return (
      <Modal title="Monastery — adjacent depot" desc="You may also take all goods from one adjacent depot.">
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
            <button className="coc-btn ghost sm" disabled={!(me.goods[goodsForDie] > 0)} onClick={() => mv({ type: "extra_action", value: extraValue, sub: { type: "sell_goods" } })}>Sell {goodsForDie}</button>
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
