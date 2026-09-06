import { useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import { useCardInfoGesture } from "../../shared/gestures.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, TurnBadge, LobbyMatchup, LobbyLoading, GameMenu, gameMenuCss,
  readLobbyCache, writeLobbyCache, createModalCss, CreateModal, CmRow, CmSeg,
  notWaiting, LobbyAction,
  LobbyCreateRow, lobbyCreateRowCss, useProgressiveList, LobbyTabs, useLastDifficulty,
  LobbyHero, LobbyUser, useListFade,
  RulesModal, rulesModalCss,
} from "../../shared/lobby.jsx";
// Only the shared CARD FRAME (sizing vars + .card chrome). Dontminion's card face
// is its own markup — no gems here, but the frame keeps all five games' cards the
// same physical object on screen.
import { splendorCardCss } from "../../shared/splendor.jsx";
import DontminionRules from "./rules.jsx";
import { parsePath, buildPath, pushPath, replacePath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported `?inline` (a string injected by this
// component's own <style> tag) — NEVER a JS template literal (the documented
// stray-backtick blank-page footgun).
import _cssText from "./Dontminion.css?inline";
// The home card and this screen must be the same colour; one value, see shared/accents.js.
import { GAME_ACCENTS } from "../../shared/accents.js";

// ─── Config ────────────────────────────────────────────────────────────────
const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const DM_WS = WS_RAW.replace(/\/ws$/, "/dontminion/ws");
const DM_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/dontminion");

// The bot tiers OFFERED in the picker, and now the whole shipped ladder: a
// barely-playing Random and the real opponent, Big Money+. Plain Big Money
// left the UI first and has since been dropped from `main.AI_DIFFICULTIES`
// too — it is a strictly weaker bmplus, so it only added a choice no one
// should pick. Keep this list a subset of AI_DIFFICULTIES: the server coerces
// anything it doesn't know to the default, so an id that drifts out of that
// tuple silently hands the player a different bot than the one they picked.
//
// LABELS ARE SHORT ON PURPOSE. These render as a `cm-seg` sharing one row with
// the Bots counter (the side-by-side layout is what keeps the create modal
// inside its 148px budget), and `.cm-seg-btn` is `white-space:nowrap` inside an
// `overflow:hidden` track — a label too wide for its half of the track is
// CLIPPED, not wrapped. The full name rides along as the button's title.
const BOTS = [
  { id: "easy", name: "Random", title: "Random legal moves — barely plays" },
  { id: "bmplus", name: "Money+", title: "Big Money+ — reads the board for a terminal, knows how the game ends" },
];
// A remembered last-played tier is validated against THIS list, not against
// `main.AI_DIFFICULTIES` — plain Big Money left the picker before it left the
// server, and a retired id must fall back to the default rather than restore as
// a selection whose label no longer names the bot the server would seat.
const BOT_IDS = BOTS.map((b) => b.id);
// Display NAMES only. The SERVER decides which expansions exist (/catalog
// "expansions", from main.KNOWN_EXPANSIONS) and the picker is built from that,
// so a set the server ships without a label here still appears (under a
// title-cased id) instead of being silently unpickable.
const EXPANSIONS = [
  { id: "base", name: "Base Set" },
  { id: "intrigue", name: "Intrigue" },
  { id: "seaside", name: "Seaside" },
  { id: "prosperity", name: "Prosperity" },
  { id: "hinterlands", name: "Hinterlands" },
  { id: "cornucopia", name: "Cornucopia & Guilds" },
  { id: "alchemy", name: "Alchemy" },
  { id: "darkages", name: "Dark Ages" },
  { id: "adventures", name: "Adventures" },
  { id: "empires", name: "Empires" },
  { id: "renaissance", name: "Renaissance" },
  { id: "menagerie", name: "Menagerie" },
];
// Adventures tokens that sit ON a Supply pile (engine.TOKEN_KINDS). Public
// markers, so they render for every player; the glyph is the token's own
// shorthand rather than an emoji, because "+1 Card on Smithy" has to be
// readable at a pile-corner size.
const TOKEN_GLYPH = {
  "+card": "+C", "+action": "+A", "+buy": "+B", "+coin": "+$",
  "-cost": "−$2", trashing: "🗑", estate: "🏠",
};
// ...and the ones that sit in front of a PLAYER (seat.tokens). The Journey
// token is stored as its DOWN state, so absence means face up — which is where
// it starts, and what an old save correctly means.
const seatTokens = (seat) => {
  const t = seat?.tokens || {};
  const out = [];
  if (t["-card"]) out.push({ key: "-card", thing: "stok:-card", glyph: "−1🃏", title: "-1 Card token: your next draw is one card short" });
  if (t["-coin"]) out.push({ key: "-coin", thing: "stok:-coin", glyph: "−$1", title: "-$1 token: the next $ you get is reduced by 1" });
  if (t.journey_down) out.push({ key: "journey", thing: "stok:journey", glyph: "🧭", title: "Journey token: face DOWN" });
  if (t.estate) out.push({ key: "estate", thing: "stok:estate", glyph: `🏠 ${t.estate}`, title: `Inheritance: their Estates play ${t.estate}`, extra: { sub: `naming ${t.estate}` } });
  return out;
};

// ─── THINGS THAT ARE NOT CARDS ─────────────────────────────────────────────
// A Dominion table is not only cards. Mats, tokens, Artifacts and the spendable
// counters all carry real rules, and — unlike a card, a pile or a landscape —
// NONE of them prints those rules on anything the player can open. A `title`
// tooltip is not an answer either: touch has no hover, which is the same hole
// that once hid the Native Village mat's contents on a phone.
//
// So every one of them gets an entry here and answers the SAME gesture a card
// face does (press-and-hold / right-click → the detail modal, via
// useCardInfoGesture). The rule the whole board now keeps: whatever the reader
// points at, "what does this do?" has one answer in one place.
const THINGS = {
  // — mats —
  "mat:tavern": { icon: "🍺", title: "Tavern mat", sub: "Adventures — face up",
    text: "Some cards set themselves aside on your Tavern mat instead of going to your discard pile. They sit there face up — public, out of your deck, and not in play — until you Call them.\n\nYou never press a Call button: every card says exactly when it may be called, so the game asks you at that moment, as an ordinary decision." },
  "mat:island": { icon: "🏝", title: "Island mat", sub: "Seaside — face up",
    text: "Island puts itself and another card from your hand onto your Island mat, out of your deck for the rest of the game.\n\nCards on the mat are public and they still count for scoring at the end — which is the point of putting Victory cards there." },
  "mat:village": { icon: "🏕", title: "Native Village mat", sub: "Seaside — face down",
    text: "Native Village either sets the top card of your deck aside on your mat, or puts every card on the mat into your hand.\n\nThe mat is face down: you may look at your own whenever you like, but an opponent only sees how many cards are on theirs. Cards there still count for scoring." },
  "mat:aside": { icon: "⏳", title: "Set aside", sub: "cards waiting to come back",
    text: "Cards a Duration effect has set aside. They are out of your deck and not in play, and they return on their own — at the moment the card that set them aside says, with no action needed from you." },
  // — the spendable / counted resources in the turn bar —
  actions: { icon: "⚔", title: "Actions", sub: "this turn only",
    text: "How many Action cards you may still play this turn. You start your turn with 1; a Village-type card gives you more.\n\nUnspent Actions do not carry over — they are gone at the end of your turn." },
  buys: { icon: "🛒", title: "Buys", sub: "this turn only",
    text: "How many cards (and Events/Projects) you may still buy this turn. You start with 1.\n\nUnspent Buys do not carry over." },
  coins: { icon: "$", title: "Money", sub: "this turn only",
    text: "The coins available to spend right now — from Treasures you have played, from +$ on Action cards, and from anything you have spent Coffers or Debt payments on.\n\nUnspent money does NOT carry over: it disappears at the end of your turn. Coffers are the way to keep it." },
  potions: { icon: "🧪", title: "Potions", sub: "Alchemy",
    text: "Alchemy's second currency. Playing a Potion gives +1 Potion, and cards like Familiar cost a Potion as well as coins — a $3 + Potion card cannot be bought with $3 alone.\n\nLike money, unspent Potions vanish at the end of your turn." },
  coffers: { icon: "🪙", title: "Coffers", sub: "Cornucopia & Guilds",
    text: "Saved money, kept on a mat between turns. Spend a Coffers at any time during your turn to get +$1.\n\nThey never expire, so money put into Coffers is money you did not have to spend this turn." },
  villagers: { icon: "🧑", title: "Villagers", sub: "Renaissance",
    text: "Coffers' twin, one column over: saved Actions. Spend a Villager during your Action phase to get +1 Action.\n\nThey never expire — but unlike Coffers they are Action-phase only." },
  debt: { icon: "🪙", title: "Debt", sub: "Empires",
    text: "Debt is not a price you pay — it is a debt you TAKE. While you have any Debt at all you cannot buy anything: no card, no Event, no Project.\n\nPay it off at $1 per token, any time during your turn. Paying costs you no Buy, and you may pay off as much or as little as you can afford." },
  vp_tokens: { icon: "⭐", title: "VP tokens", sub: "counted at the end",
    text: "Victory point tokens sit in front of you, public, and are added to the VP on your cards when the game is scored.\n\nOnce you have them they are safe — trashing or discarding a card never takes them away." },
  // — Artifacts (the per-artifact rules text comes from the catalog) —
  artifact: { icon: "🏳", title: "Artifact", sub: "Renaissance",
    text: "An Artifact is not a card. Exactly one copy of each exists, it is never bought, gained or shuffled into anyone's deck, and it is never in play.\n\nIt sits in front of whoever took it last — so taking one TAKES it from the player who had it." },
  // — Adventures tokens sitting ON a Supply pile —
  "tok:+card": { icon: "+C", title: "+1 Card token", sub: "Pathfinding — on a Supply pile",
    text: "While this token is on a Supply pile, its owner gets +1 Card when they play a card from that pile — before the card does anything else." },
  "tok:+action": { icon: "+A", title: "+1 Action token", sub: "Lost Arts — on a Supply pile",
    text: "While this token is on a Supply pile, its owner gets +1 Action when they play a card from that pile — before the card does anything else." },
  "tok:+buy": { icon: "+B", title: "+1 Buy token", sub: "Seaway — on a Supply pile",
    text: "While this token is on a Supply pile, its owner gets +1 Buy when they play a card from that pile — before the card does anything else." },
  "tok:+coin": { icon: "+$", title: "+$1 token", sub: "Training — on a Supply pile",
    text: "While this token is on a Supply pile, its owner gets +$1 when they play a card from that pile — before the card does anything else." },
  "tok:-cost": { icon: "−$2", title: "−$2 cost token", sub: "Ferry — on a Supply pile",
    text: "Cards from this pile cost $2 less on their owner's turns (never below $0). It changes the price for its OWNER only." },
  "tok:trashing": { icon: "🗑", title: "Trashing token", sub: "Plan — on a Supply pile",
    text: "When its owner buys a card from this pile, they may trash a card from their hand." },
  "tok:estate": { icon: "🏠", title: "Estate token", sub: "Inheritance — on a Supply pile",
    text: "Its owner's Estates are also the Action card this token sits on: their Estates may be played as that card, in addition to being Estates." },
  // — Adventures tokens sitting in front of a PLAYER —
  "stok:-card": { icon: "−1🃏", title: "−1 Card token", sub: "in front of a player",
    text: "When this player draws their hand in Clean-up they draw one card fewer, and then return the token.\n\nIt is a one-shot penalty, not a permanent one — but it sits there until the hand it costs actually gets drawn." },
  "stok:-coin": { icon: "−$1", title: "−$1 token", sub: "in front of a player",
    text: "The next time this player would get $ on their turn, they get $1 less and return the token.\n\nOne-shot, like the −1 Card token: it waits in front of them until it bites." },
  "stok:journey": { icon: "🧭", title: "Journey token", sub: "in front of a player",
    text: "The Journey token starts face up and gets turned over by the cards that use it. What those cards do depends on which way it is showing — so it is public, and worth watching.\n\nRight now it is face DOWN." },
  "stok:estate": { icon: "🏠", title: "Inheritance", sub: "in front of a player",
    text: "This player has set their Estate token on an Action card. Their Estates are also that card — they may be played as it, and they are still Estates for scoring." },
};

// A landscape's kind, as a heading and as one word on its own face. Derived
// from the DATA rather than a hardcoded row, so a set that adds a kind (Ways,
// Traits, Prophecies) gets its section for free.
const KIND_PLURAL = {
  event: "Events", project: "Projects", landmark: "Landmarks",
  way: "Ways", trait: "Traits", prophecy: "Prophecies", ally: "Allies",
};
// The order the Kingdom browser lists the kinds in — buyable first, then the
// ones that just sit there. A kind not listed here still gets a section; it
// simply sorts to the end, which is the right default for a set we haven't
// shipped yet.
const KIND_ORDER = ["event", "project", "landmark", "way", "trait", "prophecy", "ally"];
const kindPlural = (k) => KIND_PLURAL[k] || (k ? k.charAt(0).toUpperCase() + k.slice(1) + "s" : "Landscapes");
// What a KIND of landscape is, as opposed to what one particular card does.
// The distinction is the half a first-time reader is missing — "you buy an
// Event instead of a card, with a Buy" is not printed on any Event — so the
// detail modal leads with it and the card's own text follows.
const LANDSCAPE_BLURB = {
  event: "An Event is bought with a Buy, like a card — but you get its effect instead of a card, and it stays on the table for anyone to buy again. Its price never changes: Bridge and friends discount cards, not Events.",
  project: "A Project is bought once, with a Buy, and you put a cube on it. From then on its ability is on for you for the REST OF THE GAME. You may only ever have two Projects.",
  landmark: "A Landmark is never bought. It sits on the table all game and changes how the game is scored — every player is under it, whether they play to it or not.",
  way: "A Way is never bought. When you play an Action card you may follow the Way instead of the card's own instructions — any Action, any turn.",
  trait: "A Trait is never bought. It attaches to one Supply pile at setup, and every card from that pile has it for the whole game.",
  prophecy: "A Prophecy is never bought. It starts covered by Sun tokens and takes effect for everyone once the last one is removed.",
};
// Platinum/Colony slot into the basics row when the Prosperity setup rule
// put them in this game's supply
const basicsRowFor = (supply) => {
  const row = ["Copper", "Silver", "Gold"];
  if (supply && supply.Platinum != null) row.push("Platinum");
  // Alchemy's Potion is a basic-supply Treasure (like Platinum) — it joins the
  // Supply whenever a Kingdom card costs a Potion, and MUST be buyable then, or
  // every Potion-costed card is unreachable.
  if (supply && supply.Potion != null) row.push("Potion");
  row.push("Estate", "Duchy", "Province");
  if (supply && supply.Colony != null) row.push("Colony");
  row.push("Curse");
  return row;
};
const BASIC_ROW = ["Copper", "Silver", "Gold", "Estate", "Duchy", "Province", "Curse"];

// Kernel pseudo-card names (frames the engine owns, not real cards) → what the
// player reads. "__abilities" is the p23 §2 concurrency prompt: several of your
// own abilities triggered at once and YOU pick what resolves first.
const PSEUDO_CARDS = { __attack: "Attack", __abilities: "Choose what resolves first" };
const displayCard = (name) => PSEUDO_CARDS[name] || name;

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() { return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join(""); }
function timeAgo(ts) {
  if (!ts) return "";
  const diff = Math.floor(Date.now() / 1000) - ts;
  if (diff < 60) return "just now";
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  return `${Math.floor(diff / 86400)}d ago`;
}

// Card-face tinting by primary type (dual types show a split banner).
const TYPE_LABEL = {
  action: "Action", treasure: "Treasure", victory: "Victory", curse: "Curse",
  attack: "Attack", reaction: "Reaction", duration: "Duration",
};
const faceClass = (types) => {
  if (!types) return "";
  if (types.includes("curse")) return "dm-f-curse";
  if (types.includes("treasure")) return "dm-f-treasure";
  if (types.includes("victory")) return "dm-f-victory";
  return "dm-f-action";
};

// The card-info gesture (right-click / press-and-hold) now lives in
// shared/gestures.js — Rag Tag uses it too, and the tricky half is the iOS
// vs Android difference, which is not a thing to keep two copies of.

function DmCardFace({ name, card, onClick, onInfo, selected, disabled, highlight, small, badge, body }) {
  const types = card?.types || [];
  const infoGesture = useCardInfoGesture(onInfo);
  // A card that isn't actionable right now still answers a click with its
  // detail modal (onInfo) — nothing on the board is a dead click.
  const click = (!disabled && onClick) ? onClick : onInfo;
  const cls = ["card", "dm-card", faceClass(types),
    small ? "dm-card-small" : "",
    selected ? "dm-sel" : "", highlight ? "dm-hl" : "",
    disabled ? "dm-dis" : "", click ? "dm-clickable" : ""].filter(Boolean).join(" ");
  // long rules text shrinks to fit — the card itself NEVER grows
  const text = card?.text || "";
  const textCls = text.length > 200 ? " dm-text-xxl" : text.length > 130 ? " dm-text-xl"
    : text.length > 80 ? " dm-text-l" : "";
  return (
    <div className={cls} onClick={click} {...infoGesture}
      title={card ? `${name} (${card.cost}) — ${card.text}` : name}>
      {types.includes("attack") && <span className="dm-edge dm-edge-atk" />}
      {types.includes("reaction") && <span className="dm-edge dm-edge-rx" />}
      {types.includes("duration") && !types.includes("attack") && <span className="dm-edge dm-edge-dur" />}
      <FitText text={name} className="dm-card-name" />
      {/* supply piles opt into fitted body text via `body` (small stays text-free
          on the 56px in-play/hand/mat faces); large faces keep the length tiers */}
      {body
        ? <FitBodyText text={text} hasPotion={card?.potion > 0} />
        : (!small && <div className={"dm-card-text" + textCls + (card?.potion > 0 ? " dm-has-potion" : "")}>{text}</div>)}
      {/* foot row: type lines bottom-LEFT, the coin cost bottom-RIGHT */}
      <div className="dm-card-foot">
        <div className="dm-types">
          {types.map((t) => <span key={t} className="dm-type">{TYPE_LABEL[t] || t}</span>)}
        </div>
        {/* A card whose whole price is Debt prints NO coin cost at all
            (Engineer is {4D}, not "$0 + 4D"), so the coin column is dropped
            rather than showing a misleading 0. */}
        <span className="dm-cost">
          {card ? (card.cost === 0 && card.debt > 0 ? "" : card.cost) : ""}
        </span>
      </div>
      {/* Debt is the third cost dimension (Empires) — an orange hexagon, the
          colour and shape the physical cards use, sitting where a Potion
          would. You do not pay it to buy: you TAKE it, and then cannot buy
          anything until it is paid off. */}
      {card?.debt > 0 && (
        <span className={"dm-cost-d" + (card.cost === 0 ? " dm-cost-d-solo" : "")}
          title={`costs ${card.debt} Debt`}>
          <svg viewBox="0 0 24 24" role="img" aria-label={`costs ${card.debt} Debt`}>
            <path d="M12 1 L22 6.5 L22 17.5 L12 23 L2 17.5 L2 6.5 Z"
                  fill="#d8722f" stroke="#8d4413" strokeWidth="1.4" />
            <text x="12" y="16.6" textAnchor="middle" fontSize="12" fontWeight="800"
                  fill="#fff">{card.debt}</text>
          </svg>
        </span>
      )}
      {/* A Potion is part of the cost (Alchemy): a little bottle sitting just
          ABOVE the coin. It is absolutely placed so it never grows the foot row —
          the rules text reflows AROUND its corner (see .dm-has-potion) instead of
          stopping short above a tall cost column. */}
      {card?.potion > 0 && (
        <span className="dm-cost-p" title="costs a Potion">
          <svg viewBox="0 0 24 28" role="img" aria-label="costs a Potion">
            {/* blue potion: a bulbous body tapering up into a narrow spout */}
            <path d="M9.4 5 L9.4 9 C9.4 12 3 12.6 3 18.4 C3 23.4 7.4 26 12 26
                     C16.6 26 21 23.4 21 18.4 C21 12.6 14.6 12 14.6 9 L14.6 5 Z"
                  fill="#3f57d8" stroke="#243a9e" strokeWidth="1" />
            {/* a glassy shine down the left of the liquid */}
            <ellipse cx="8.8" cy="16.5" rx="1.6" ry="3" fill="#89a4f2" opacity="0.7" />
            {/* the cork, plugging the spout */}
            <rect x="8.3" y="1.4" width="7.4" height="4.3" rx="1.4"
                  fill="#caa268" stroke="#8a6a3c" strokeWidth="0.8" />
            <text x="12" y="20.4" textAnchor="middle" fontSize="9.5" fontWeight="800"
                  fill="#fff">P</text>
          </svg>
        </span>
      )}
      {badge != null && <span className="dm-card-badge">{badge}</span>}
    </div>
  );
}

// Button label that fits itself to the button's width (buttons themselves are
// capped at 100% of their box — never overflow it). One line if it fits; if it
// doesn't, the label WRAPS to a second row and the button grows to two rows
// rather than shrinking the text into illegibility or clipping it. Minion's
// "discard your hand, +4 Cards, …" option is the case that forced this: no font
// size makes that fit one row of a prompt button.
const FIT_MIN_PX = 9;
function FitLabel({ children }) {
  const ref = useRef(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.fontSize = "";
    el.classList.remove("dm-fitlabel-wrap");
    if (el.scrollWidth <= el.clientWidth + 1) return;      // fits on one row
    // Two rows. Shrink only as far as two rows actually need — most labels
    // wrap at full size and never lose a pixel of type.
    el.classList.add("dm-fitlabel-wrap");
    const base = parseFloat(getComputedStyle(el).fontSize) || 15;
    for (let size = base; size >= FIT_MIN_PX; size -= 0.5) {
      el.style.fontSize = size + "px";
      const lh = parseFloat(getComputedStyle(el).lineHeight) || size * 1.2;
      if (el.scrollHeight <= lh * 2 + 1) return;
    }
  }, [children]);
  return <span ref={ref} className="dm-fitlabel">{children}</span>;
}

// Text that shrinks ONLY as far as it must to fit its box's full width (and
// never below `min`). Replaces the old length-tiered name classes, which were
// compensation for a layout where the cost coin shared the name's row — the
// coin moved to the foot, so "Tide Pools" was rendering at ~60% of the width
// it had available. Re-fits when the box's WIDTH changes (container queries,
// rotation); height changes are ignored so shrinking can't feed itself.
function FitText({ text, className, min = 8 }) {
  const box = useRef(null);
  const span = useRef(null);
  useLayoutEffect(() => {
    const b = box.current, s = span.current;
    if (!b || !s) return;
    let lastW = -1;
    const fit = () => {
      b.style.fontSize = "";
      // clientWidth is the PADDING box, so measuring against it let the name
      // grow into (and past) its own right inset — the title sat visibly
      // closer to the right edge than the left, on every card. Fit to the
      // CONTENT box instead, and the two insets match by construction.
      const cs0 = getComputedStyle(b);
      const avail = b.clientWidth - parseFloat(cs0.paddingLeft)
        - parseFloat(cs0.paddingRight) - 1;
      if (avail <= 0) return;
      const natural = s.scrollWidth;
      if (natural > avail) {
        const base = parseFloat(getComputedStyle(b).fontSize) || 12;
        b.style.fontSize = Math.max(min, base * (avail / natural)) + "px";
      }
    };
    fit();
    let ro;
    if (typeof ResizeObserver !== "undefined") {
      ro = new ResizeObserver((entries) => {
        const w = entries[0].contentRect.width;
        if (Math.abs(w - lastW) < 0.5) return;   // width only — never height
        lastW = w;
        fit();
      });
      ro.observe(b);
    }
    return () => { if (ro) ro.disconnect(); };
  }, [text, min]);
  return (
    <div ref={box} className={className}>
      <span ref={span} className="dm-fitspan">{text}</span>
    </div>
  );
}

// Supply-face rules text: FILL the body between a legible floor and a ceiling —
// the ceiling stops a short card (Smithy) ballooning, the floor keeps it readable.
// If the whole rule won't fit even at the floor, drop to the floor and trim with a
// "…"; the full text is one press/right-click away (useCardInfoGesture opens the
// detail modal, and the face's `title` carries it for a desktop hover). Unlike the
// large faces' length-tiered .dm-text-* classes, this MEASURES the real box, so it
// stays correct as the container query resizes the pile (180px on a wide screen
// down to the ~88px floor of the two-column laptop layout).
const BODY_MIN_PX = 10;
const BODY_MAX_PX = 16;
const BODY_LH = 1.2;

function FitBodyText({ text, min = BODY_MIN_PX, max = BODY_MAX_PX, hasPotion = false }) {
  const ref = useRef(null);
  const [shown, setShown] = useState(text);
  const [size, setSize] = useState(max);
  const [clipped, setClipped] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    let lastW = -1;
    // Trial strings are written imperatively (one layout read each), then the
    // winner is COMMITTED through state so the vdom and the DOM agree — textContent
    // replaces the single text node React manages for {shown}, so there is no
    // orphaned-node fight, and the transient writes happen before paint.
    const fits = (px, str) => {
      el.style.fontSize = px + "px";
      el.textContent = str;
      return el.scrollHeight <= el.clientHeight + 0.5;   // box height is fixed (overflow:hidden)
    };
    const fit = () => {
      el.style.lineHeight = BODY_LH;
      for (let px = max; px >= min; px -= 0.5) {          // largest whole-text size in [min,max]
        if (fits(px, text)) { setSize(px); setShown(text); setClipped(false); return; }
      }
      let lo = 0, hi = text.length, best = 0;             // floor won't fit → trim to an ellipsis
      while (lo <= hi) {
        const mid = (lo + hi) >> 1;
        if (fits(min, text.slice(0, mid).replace(/\s+$/, "") + "…")) { best = mid; lo = mid + 1; }
        else hi = mid - 1;
      }
      let cut = text.slice(0, best);
      const sp = cut.lastIndexOf(" ");
      if (sp > best * 0.6) cut = cut.slice(0, sp);        // don't cut mid-word
      const out = cut.replace(/\s+$/, "") + "…";
      setSize(min); setShown(out); setClipped(true);
      el.style.fontSize = min + "px"; el.textContent = out;   // leave DOM == committed state
    };
    fit();
    let ro;
    if (typeof ResizeObserver !== "undefined") {
      // RE-FIT ON EITHER DIMENSION. This guard was width-only, and the fit criterion
      // is `scrollHeight <= clientHeight` — a HEIGHT test against a box that is
      // `flex:1` between the name and the foot, so its height is the card minus the
      // NAME. FitText sizes that name independently, and when it does, this box
      // changes height with its width untouched: the refit was skipped and the text
      // was left spilling out of the card, permanently. Measured on a real board:
      // resizing the names alone moved all 17 body boxes' heights, changed no width,
      // triggered ZERO refits and left 8 piles overflowing.
      // It is also invisible to a settle-until-stable harness — a fitter that wrongly
      // declines to refit is indistinguishable from one that has converged — which is
      // how it reached CI as an intermittently red gate rather than a bug report.
      // NOTE the asymmetry with FitText above, which is width-only and CORRECT: its
      // box's height is driven by its own font-size, so observing height there would
      // feed back on itself. This box's height is set by the flex parent and cannot
      // be changed by anything `fit()` does, so there is no loop to guard against.
      let lastH = -1;
      ro = new ResizeObserver((entries) => {
        const { width: w, height: h } = entries[0].contentRect;
        if (Math.abs(w - lastW) < 0.5 && Math.abs(h - lastH) < 0.5) return;
        lastW = w; lastH = h; fit();
      });
      ro.observe(el);
    }
    return () => { if (ro) ro.disconnect(); };
  }, [text, min, max, hasPotion]);
  return (
    <div ref={ref}
      className={"dm-card-text dm-card-body" + (clipped ? " dm-body-clip" : "")
        + (hasPotion ? " dm-has-potion" : "")}
      style={{ fontSize: size + "px", lineHeight: BODY_LH }}>
      {shown}
    </div>
  );
}

// Keys that stay stable as a zone changes: the Nth copy of a card keeps its
// key when other cards leave, so only genuinely NEW cards mount (and animate).
// The turn prefix makes a fresh hand at turn start count as new.
function zoneKeys(list, prefix) {
  const seen = {};
  return list.map((name) => {
    seen[name] = (seen[name] || 0) + 1;
    return `${prefix}:${name}#${seen[name]}`;
  });
}

// Selection toggle for the pick-N prompts. Clicking a NEW item when the quota
// is full swaps rather than doing nothing: with max 1 it replaces outright,
// otherwise the oldest pick makes room. (Having to deselect first was a
// reported annoyance — every click should change something.)
function pickToggle(sel, item, max) {
  if (sel.includes(item)) return sel.filter((x) => x !== item);
  if (sel.length < max) return [...sel, item];
  if (max === 1) return [item];
  return [...sel.slice(1), item];
}

function DmCardBack() {
  return (
    <div className="card dm-card dm-card-small dm-card-back">
      <span className="dm-back-emblem">D</span>
    </div>
  );
}

// A real pile: deck = face-down back with a count badge; discard = its top card
// face up. Sizing rides the surrounding container's --card-w-s.
function DmPile({ kind, label, count, top, card, onInfo }) {
  const stacked = count > 1 ? " dm-pile-stacked" : "";
  return (
    <div className="dm-pile-slot dm-zpile">
      {kind === "deck"
        ? (count > 0
          ? <div className={"dm-pilewrap" + stacked}><DmCardBack /></div>
          : <div className="dm-empty-slot" />)
        : (top
          // keyed on the face + depth: a new top card remounts and flips over
          ? <div key={top + ":" + count} className={"dm-pilewrap" + stacked}>
              <DmCardFace name={top} card={card} small onInfo={onInfo} />
            </div>
          : <div className="dm-empty-slot" />)}
      <span className="dm-pile-count">{label} <Pop n={count} /></span>
    </div>
  );
}

// A number that pops when it changes: the key remount is what replays the
// CSS animation (a re-render alone would not).
function Pop({ n }) {
  return <span key={n} className="dm-count-pop">{n}</span>;
}

// A mat chip (Island / Native Village / Tavern / Set-aside). When the cards on
// it are KNOWN — your own mats, or any public one (Island, Tavern) — it's
// tappable to open a viewer; a hover title alone is invisible on touch, which is
// what hid the Native Village contents on a phone. A face-down mat (an
// opponent's Native Village / set-aside) shows the count only.
//
// The mat's own RULES are a second question from what is on it, and the answer
// used to exist nowhere: press-and-hold / right-click opens the mat's
// description, exactly as it does on a card. A face-down mat has no viewer, so
// its plain click opens that description too — no dead clicks.
function DmMatChip({ emoji, count, label, cards, onView, onInfo }) {
  const canView = Array.isArray(cards) && cards.length > 0;
  const gesture = useCardInfoGesture(onInfo);
  const click = canView ? () => onView({ label, cards }) : onInfo;
  return (
    <span className={"dm-mat-chip" + (click ? " dm-mat-chip-view" : "")}
      title={label + ": " + (canView ? cards.join(", ") : "face down")
        + (onInfo ? " — hold or right-click for what the mat does" : "")}
      role={click ? "button" : undefined} tabIndex={click ? 0 : undefined}
      onClick={click} {...gesture}
      onKeyDown={click ? (e) => { if (e.key === "Enter" || e.key === " ") click(); } : undefined}>
      {emoji} {count}
    </span>
  );
}

// A landscape (Event / Project / Landmark / …). LANDSCAPE-orientation — wide
// where a card is tall — because that is what they physically are and what
// tells them apart from the Supply at a glance.
//
// It is a component rather than a render helper for one reason: it calls the
// info-gesture hook, and hooks may not live in a function called from a `.map`.
// The face's own text is TRUNCATED by its box (`.dm-ls-text` clips), so unlike
// the tooltip theory this used to rest on, a long Event genuinely needs the
// modal — press-and-hold / right-click, same as a card.
function DmLandscape({ name, d, st, buyable, spent, seatOrder, names, myId, onBuy, onInfo, idx = 0 }) {
  const gesture = useCardInfoGesture(onInfo);
  const store = st.vp || 0;
  const kind = d.kind || st.kind || "event";
  // An Event or Project prints a price; a LANDMARK and a WAY print none,
  // because neither can be bought at all. A Way's `cost` field is inert (`way`
  // is not in BUYABLE_LANDSCAPE_KINDS), so showing its $0 would read as "free
  // to buy" for something there is no move for. Debt (Empires) is the third
  // dimension and reads "5D".
  const priceLabel = ["landmark", "way"].includes(kind) ? ""
    : [d.cost || !d.debt ? "$" + (d.cost ?? 0) : "",
       d.debt ? d.debt + "D" : ""].filter(Boolean).join(" + ");
  const cls = "dm-lscape dm-ls-" + kind
    + (buyable ? " dm-ls-buyable" : "") + (spent ? " dm-ls-spent" : "");
  // A non-buyable landscape stays a live element (never `disabled`) precisely so
  // it keeps both its tooltip and its gesture: reading it must not depend on
  // being able to afford it.
  return (
    <button type="button" className={cls}
      style={{ animationDelay: Math.min(idx * 16, 260) + "ms" }}
      title={`${name} — ${priceLabel || kind}\n${d.text || ""}`}
      onClick={buyable && onBuy ? onBuy : onInfo} {...gesture}>
      <span className="dm-ls-name">{name}</span>
      <span className="dm-ls-text">{d.text || ""}</span>
      <span className="dm-ls-foot">
        <span className="dm-ls-kind">{kind}</span>
        {priceLabel && <span className="dm-ls-cost">{priceLabel}</span>}
        {/* What a Landmark shows instead of a price: the VP tokens left on
            it. Arena and Battlefield drain over a game, and "if there are
            none left you get nothing", so the count is real information. */}
        {store > 0 && (
          <span className="dm-ls-vp" title="VP tokens left on this landmark">
            &#9733; <Pop n={store} />
          </span>
        )}
        {/* PROJECT CUBES (Renaissance): a Project's ability is active for
            whoever has a cube on it, for the rest of the game — so the
            cubes ARE the state and every player needs to see them. One
            coloured dot per owner, in seat order. */}
        {st.kind === "project" && (st.bought_by || []).length > 0 && (
          <span className="dm-ls-cubes">
            {(seatOrder || []).filter((p) => (st.bought_by || []).includes(p)).map((p) => (
              <span key={p} className={"dm-cube dm-cube-" + (seatOrder.indexOf(p) % 4)}
                title={`${names?.[p] || p} has a cube on ${name}`} />
            ))}
          </span>
        )}
        {/* Sinister Plot's counters — per player, next to their cube */}
        {(st.tokens?.[myId] || 0) > 0 && (
          <span className="dm-ls-vp" title="your tokens here">
            ● <Pop n={st.tokens[myId]} />
          </span>
        )}
      </span>
      {spent && <span className="dm-ls-tick" title="you have bought this">✓</span>}
    </button>
  );
}

// Every OTHER not-a-card thing that sits on the table: an Artifact badge, a
// token on a pile, a token in front of a player, a counter in the resource bar.
// One component so the gesture contract is identical to a card's — plain click
// opens the description, and press-and-hold / right-click does too even when
// something else owns the click (the resource counters carry spend BUTTONS, and
// a hold on the counter must read the rule, never spend).
function DmChip({ className = "", title, onInfo, children }) {
  const gesture = useCardInfoGesture(onInfo);
  return (
    <span className={(className + (onInfo ? " dm-chip-info" : "")).trim() || undefined} title={title}
      role={onInfo ? "button" : undefined} tabIndex={onInfo ? 0 : undefined}
      onClick={onInfo ? (e) => { if (!e.target.closest("button")) onInfo(); } : undefined}
      onKeyDown={onInfo ? (e) => {
        if ((e.key === "Enter" || e.key === " ") && e.target === e.currentTarget) { e.preventDefault(); onInfo(); }
      } : undefined}
      {...gesture}>
      {children}
    </span>
  );
}

// ─── Log formatting (the Dominion-online look: full sentences, articles,
//     grouped card lists, sub-effects indented under the play that caused them) ──
const art = (name) => (/^[AEIOU]/.test(name) ? "an" : "a") + " " + name;
function pluralCard(name, k) {
  if (k === 1) return art(name);
  if (name.endsWith("s")) return `${k} ${name}`;
  if (name.endsWith("y")) return `${k} ${name.slice(0, -1)}ies`;
  return `${k} ${name}s`;
}
function listCards(cards) {
  const counts = [];
  for (const c of cards) {
    const hit = counts.find((x) => x[0] === c);
    if (hit) hit[1] += 1; else counts.push([c, 1]);
  }
  const parts = counts.map(([c, k]) => pluralCard(c, k));
  if (parts.length <= 1) return parts.join("");
  return parts.slice(0, -1).join(", ") + " and " + parts[parts.length - 1];
}
function fmtLog(e, names) {
  const who = e.pid ? (names[e.pid] || e.pid) : "";
  const nameOf = (p) => names[p] || p;
  const listNames = (ps) => {
    const ns = (ps || []).map(nameOf);
    if (ns.length <= 1) return ns.join("");
    return ns.slice(0, -1).join(", ") + " and " + ns[ns.length - 1];
  };
  switch (e.event) {
    case "turn_start": return `— ${who}'s turn (${e.turn}) —`;
    case "phase": return null;                       // pure plumbing, not an event
    case "play": return `${who} plays ${art(e.card)}${e.coins != null ? ` (+$${e.coins})` : ""}`;
    case "plus": {
      const bits = [];
      if (e.coins) bits.push(`+$${e.coins}`);
      if (e.actions) bits.push(`+${e.actions} Action${e.actions > 1 ? "s" : ""}`);
      if (e.buys) bits.push(`+${e.buys} Buy${e.buys > 1 ? "s" : ""}`);
      if (e.potions) bits.push(`+${e.potions} Potion${e.potions > 1 ? "s" : ""}`);
      if (!bits.length) return null;
      return `${who} gets ${bits.join(", ")}${e.why ? ` (${e.why})` : ""}`;
    }
    case "minus": {
      if (!e.coins) return null;
      return `${who} loses $${e.coins}`;
    }
    case "off_turn_bonus": {
      // earned on someone else's turn, so there is no pool to put it in and it
      // is LOST. Without this case the generic fallback rendered it as
      // "bob off turn bonus: coins 2", which reads as though he got it.
      const bits = [];
      if (e.coins) bits.push(`$${e.coins}`);
      if (e.actions) bits.push(`${e.actions} Action${e.actions > 1 ? "s" : ""}`);
      if (e.buys) bits.push(`${e.buys} Buy${e.buys > 1 ? "s" : ""}`);
      if (!bits.length) return null;
      return `${who} can't use ${bits.join(", ")} — not their turn`;
    }
    case "cleanup_off_turn":
      return `${who} discards ${listCards(e.cards)} (played on another turn)`;
    // Seaside/Prosperity events that had been falling through to the generic
    // fallback since their phases shipped
    case "lighthouse": return `${who} is protected by Lighthouse`;
    case "vp_tokens": return `${who} takes ${e.count} VP token${e.count === 1 ? "" : "s"}`;
    case "island": return `${who} sets ${listCards(e.cards)} aside on their Island mat`;
    case "village_mat":
      return `${who} sets ${e.count} card${e.count === 1 ? "" : "s"} aside on their Native Village mat`;
    case "village_take":
      return `${who} takes ${e.count} card${e.count === 1 ? "" : "s"} from their Native Village mat`;
    case "exchange":
      return `${who} exchanges ${art(e.card)} for ${art(e.into)}`;
    case "shuffle_into_deck":
      return `${who} shuffles ${e.count || 0} card${e.count === 1 ? "" : "s"} into their deck`;
    case "buy": return `${who} buys and gains ${art(e.card)}`;
    case "gain": return e.dest && e.dest !== "discard"
      ? `${who} gains ${art(e.card)} (to ${e.dest === "deck" ? "their deck" : e.dest})`
      : `${who} gains ${art(e.card)}`;
    case "gain_from_trash": return e.dest === "deck"
      ? `${who} gains ${art(e.card)} from the trash, onto their deck`
      : `${who} gains ${art(e.card)} from the trash`;
    case "return_to_pile": return `${who} returns ${art(e.card)} to its pile`;
    case "set_aside_return": return `${who} sets ${art(e.card)} aside, to return it to the Supply in Clean-up`;
    case "enchanted": return `${who} gets +1 Card and +1 Action instead of resolving ${art(e.card)}`;
    // taking a card OUT of the trash without gaining it (Fortress)
    case "from_trash": return e.dest === "hand"
      ? `${who} takes ${art(e.card)} from the trash into their hand`
      : `${who} takes ${art(e.card)} from the trash`;
    case "deck_to_discard":
      return `${who} puts their deck (${e.count} card${e.count === 1 ? "" : "s"}) into their discard pile`;
    case "play_from_supply": return `${who} plays ${art(e.card)} from the Supply, leaving it there`;
    // Inheritance: an Estate playing the card its owner's token sits on
    case "play_set_aside": return `${who} plays their set-aside ${art(e.card)}, leaving it there`;
    case "set_aside_supply": return `${who} sets ${art(e.card)} aside from the Supply and moves their Estate token to it`;
    // landscapes (Events/Projects/...): bought with a Buy and money, but they
    // are not cards, so nothing is gained and there is no pile
    case "buy_landscape": return `${who} buys ${e.name}`;
    // the Tavern mat: a Reserve card waits there to be CALLED, which is not
    // playing it
    case "to_tavern": return `${who} puts ${art(e.card)} on their Tavern mat`;
    case "call": return `${who} calls ${art(e.card)}`;
    case "move_token":
      return `${who} moves their ${e.token} token onto the ${e.pile} pile`;
    case "seat_token": {
      // the Journey token is stored as its DOWN state, so it reads as a flip
      if (e.token === "journey_down") return `${who} turns their Journey token ${e.value ? "face down" : "face up"}`;
      return e.value == null
        ? `${who} loses their ${e.token} token`
        : `${who} takes their ${e.token} token`;
    }
    // the -1 Card / -$1 tokens being spent by the thing they were waiting for
    case "minus_card_token": return `${who} removes their -1 Card token instead of drawing`;
    case "minus_coin_token": return `${who} removes their -$1 token, losing $1`;
    case "coffers": {
      const k = e.count ?? e.n;                    // pre-fix entries kept it in n
      return `${who} gets +${k} Coffers (${e.total} total)`;
    }
    // EXILE (Menagerie): a public mat that is still YOURS — Exiled cards
    // score. Coming in is not a gain; going out to the discard is a real
    // discard, which is why only that direction has when-discard triggers.
    case "exile":
      return `${who} Exiles ${listCards(e.cards || [])}`;
    // WAYS: "you may choose to resolve the Way instead of resolving the play
    // ability of the Action card" — the card is still played either way
    case "way": return `${who} plays ${art(e.card)} using ${e.name}`;
    // Way of the Mouse plays the set-aside card, LEAVING IT THERE
    case "play_mouse": return `${who} plays the set-aside ${e.card}, leaving it there`;
    // Way of the Chameleon swaps +Cards for +$ and back, for the whole turn
    case "chameleon_swap":
      return e.got === "coins"
        ? `${who} takes +$${e.count} instead of +${e.count} Card${e.count === 1 ? "" : "s"} (Way of the Chameleon)`
        : `${who} draws ${e.count} card${e.count === 1 ? "" : "s"} instead of +$${e.count} (Way of the Chameleon)`;
    // Snowy Village: "ignore any further +Actions you get this turn"
    case "actions_ignored":
      return `${who} ignores +${e.count} Action${e.count === 1 ? "" : "s"}`;
    // VILLAGERS (Renaissance): the other half of the Coffers mat. Spent for
    // +1 Action each, and only in your Action phase.
    case "villagers": {
      const k = e.count ?? e.n;
      return `${who} gets +${k} Villager${k === 1 ? "" : "s"} (${e.total} total)`;
    }
    case "spend": {
      const k = e.count ?? e.n;                    // pre-fix entries kept it in n
      // paying off Debt is a spend too — $1 per token, and it uses up no Buy
      if (e.what === "debt") return `${who} pays off ${k} Debt`;
      if (e.what === "villagers")
        return `${who} spends ${k} Villager${k === 1 ? "" : "s"} for +${k} Action${k === 1 ? "" : "s"}`;
      return `${who} spends ${k} ${e.what === "coffers" ? "Coffers" : e.what}`;
    }
    // DEBT (Empires): taken instead of paying, and you can't buy anything until
    // it is paid off. Public — everyone needs to see who is stuck.
    case "debt":
      return `${who} takes ${e.count} Debt (${e.total} total)`;
    // VP / Debt tokens sitting on a Supply pile or on a landscape — table
    // state with no owner, so these read without a player
    case "pile_vp":
      return `${e.count} VP ${e.count === 1 ? "is" : "are"} put on the ${e.pile} pile (${e.total} total)`;
    case "pile_debt":
      return `${e.count} Debt ${e.count === 1 ? "token is" : "tokens are"} put on the ${e.pile} pile (${e.total} total)`;
    case "landscape_vp":
      return `${e.count} VP ${e.count === 1 ? "is" : "are"} put on ${e.name} (${e.total} total)`;
    // plain tokens a player keeps on a landscape next to their cube (Sinister
    // Plot) — a negative count is the player cashing them all in
    case "landscape_tokens":
      return e.count < 0
        ? `${who} removes their ${-e.count} token${e.count === -1 ? "" : "s"} from ${e.name}`
        : `${who} adds a token to ${e.name} (${e.total} total)`;
    // ARTIFACTS (Renaissance): unique objects that sit in front of whoever
    // holds them — taking one takes it FROM its previous holder
    case "artifact":
      return e.from_pid
        ? `${who} takes the ${e.name} from ${nameOf(e.from_pid)}`
        : `${who} takes the ${e.name}`;
    // STAR CHART: the pick is private to its owner (only they saw the cards)
    case "star_chart": return `${who} puts ${art(e.card)} on top of their shuffled deck`;
    case "star_chart_skip":
      return `${who} shuffles mid-ability, so Star Chart can't pick a card`;
    // THE 2025 DURATION RULE (B9): a played Duration that left the table stops.
    // It has to be said out loud — from the player's seat, a Duration that
    // simply never pays next turn is indistinguishable from a broken trigger.
    case "duration_stopped":
      return `${nameOf(e.card)} left play, so its future effects stop`;
    // FLEET: the extra round of turns after the game would have ended
    case "fleet_round":
      return `The game would end — Fleet gives ${listNames(e.players)} one more turn each`;
    case "set_aside": return e.cards
      ? `${who} sets aside ${listCards(e.cards)}`
      : `${who} sets aside ${e.count} card${e.count === 1 ? "" : "s"}`;
    case "end_draw": {
      const k = e.count ?? e.n;                    // pre-fix entries kept it in n
      return `${who} will draw ${k} more card${k === 1 ? "" : "s"} at the end of the turn`;
    }
    case "trash": return `${who} trashes ${listCards(e.cards || [])}`;
    case "supply_trash": return `${who} trashes ${art(e.card)} from the Supply`;
    case "discard": {
      if (e.cards) return `${who} discards ${listCards(e.cards)}`;
      const k = e.count ?? e.n;                    // pre-fix entries kept it in n
      return `${who} discards ${k} card${k === 1 ? "" : "s"}`;
    }
    case "draw": {
      if (e.cards) return `${who} draws ${listCards(e.cards)}`;
      const k = e.count ?? e.n;
      return `${who} draws ${k} card${k === 1 ? "" : "s"}`;
    }
    case "to_hand": {
      // a card moved into hand off the top of the deck (Sea Chart's match,
      // Wishing Well, Library's keep, Patrol's pocketed Victory cards)
      if (e.cards) return `${who} puts ${listCards(e.cards)} into their hand`;
      const k = e.count ?? e.n;
      return `${who} puts ${k} card${k === 1 ? "" : "s"} into their hand`;
    }
    case "shuffle": return `${who} shuffles their deck`;
    case "reveal": return `${who} reveals ${listCards(e.cards || [])}`;
    case "topdeck": return e.card ? `${who} puts ${art(e.card)} onto their deck`
      : `${who} puts a card onto their deck`;
    case "deck_insert": return `${who} slips a card into their deck`;
    case "secret_passage": return `${who} places it ${e.position === 0 ? "on top" : e.position >= (e.depth - 1) ? "on the bottom" : `${e.position} deep`}`;
    case "named": return `${who} names ${e.card}`;
    case "pass": return `${who} passes ${art(e.card)} to ${names[e.to] || e.to}`;
    case "pass_public": return `${who} passes a card to ${names[e.to] || e.to}`;
    // An ability skipped because its card moved (the lose-track rule) — most
    // often a second discarded Trail that the first one's draw shuffled back
    // into the deck. Without this line the prompt simply never appears, which
    // is indistinguishable from a broken trigger. `verb` is absent for
    // abilities that aren't one word (Watchtower's trash-or-topdeck).
    case "lost_track": return `${who} loses track of ${art(e.card)} — ${e.why || "it moved"}, so `
      + (e.verb ? `it can't be ${e.verb}` : "the ability is skipped");
    case "undo": return `${who} takes back a move`;
    case "abandon": return `${who} abandoned the game`;
    case "game_over": return `Game over — ${(e.winners || []).map((w) => names[w] || w).join(" & ")} win${(e.winners || []).length > 1 ? "" : "s"}!`;
    default: {
      // An engine event this client doesn't know yet (every expansion adds
      // some) must never be SILENT — a missing line reads as "the game did
      // nothing". Render a plain readable fallback until it gets a case above.
      if (!e.event) return null;
      const skip = ["n", "pid", "event", "d", "private_to"];
      const bits = Object.entries(e)
        .filter(([k, v]) => !skip.includes(k) && (typeof v === "string" || typeof v === "number"))
        .map(([k, v]) => (k === "card" || k === "count" ? String(v) : `${k} ${v}`));
      const cards = Array.isArray(e.cards) ? listCards(e.cards) : "";
      const detail = [cards, ...bits].filter(Boolean).join(", ");
      const verb = e.event.replace(/_/g, " ");
      return `${who ? who + " " : ""}${verb}${detail ? ": " + detail : ""}`.trim();
    }
  }
}

// Every card a seat owns at game over, folded to name→count — the player's
// FINAL DECK. Mirrors engine.owned_cards: all zones reveal at over, so this
// needs no new wire field (duration cards ride duration_view, since the raw
// duration list is popped by player_view).
function deckCensus(seat) {
  if (!seat) return {};
  const all = [
    ...(seat.deck || []), ...(seat.hand || []), ...(seat.discard || []),
    ...(seat.in_play || []), ...(seat.aside || []), ...(seat.dur_aside || []),
    ...(seat.island || []), ...(seat.village_mat || []),
    ...((seat.duration_view || []).flatMap((e) => [e.card, ...(e.riders || [])])),
  ];
  const counts = {};
  for (const c of all) counts[c] = (counts[c] || 0) + 1;
  return counts;
}

// "12–9" for a finished game (yours first, then each opponent), the way CoC's
// history reads. Prefers the server's ordered `standings`, which survives two
// players sharing a display name; falls back to the name-keyed `scores` for a
// response cached before standings shipped. Renders nothing unless EVERY score
// is present — a half-filled line reads as a wrong score.
function historyScores(g) {
  const vps = Array.isArray(g.standings) && g.standings.length
    ? g.standings.map((s) => s.vp)
    : [g.your_vp, ...(g.opponents || []).map((n) => (g.scores || {})[n])];
  if (vps.length < 2 || vps.some((v) => v == null)) return "";
  return vps.join("–");
}

// The buy handler logs "buy" and the gain it causes logs "gain" back-to-back —
// fold the pair into the single "buys and gains" line.
function buildLogLines(log, names) {
  const out = [];
  for (let i = 0; i < log.length; i++) {
    const e = log[i];
    if (e.event === "gain" && i > 0) {
      const p = log[i - 1];
      if (p.event === "buy" && p.pid === e.pid && p.card === e.card) continue;
    }
    const text = fmtLog(e, names);
    // key = position in the (append-only) view log — e.n is NOT safe as a React
    // key: entries written before the count/sequence fix share n values, and
    // duplicate keys made React visibly scramble the list.
    if (text) out.push({ key: i, d: Math.min(e.d || 0, 3), turn: e.event === "turn_start", text });
  }
  return out;
}

// ─── Socket hook ─────────────────────────────────────────────────────────────
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
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// ─── Styles (no backticks anywhere in the css string) ───────────────────────
const dmStyles = baseCss + lobbyCss + splendorCardCss + _cssText
  + gameMenuCss + createModalCss + lobbyCreateRowCss + rulesModalCss;

// ─── Main component ─────────────────────────────────────────────────────────
export default function Dontminion({ myId, authUser, onExit }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [catalog, setCatalog] = useState(null);      // {cards, kingdom, expansions}
  const [openGames, setOpenGames] = useState(() => readLobbyCache("dontminion", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("dontminion", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("dontminion", myId, "history", []));
  // ...revealed 10 at a time as the reader reaches the end, up to the 50 the
  // backend sends — see useProgressiveList.
  const [historyShown, historyMore] = useProgressiveList(history);
  // A column that scrolls inside itself must say so — see `useListFade`.
  useListFade();
  const [loadingGames, setLoadingGames] = useState(false);
  const [toast, setToast] = useState("");
  const [reconnecting, setReconnecting] = useState(false);
  // A room connect is in flight (create / join / deep-link resume). While it is
  // AND we're still on the lobby screen, show the loading spinner instead of the
  // lobby, so a reconnect doesn't flash the lobby then snap into the game (CoC).
  const [connecting, setConnecting] = useState(false);
  const [showRules, setShowRules] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [createOpp, setCreateOpp] = useState("ai");
  const [createBots, setCreateBots] = useState(1);
  // The bot style this player last actually played. Big Money+ until they have
  // one: the strongest tier that still answers instantly, and the one that
  // plays a recognisable game of Dominion (it reads the board for a terminal
  // and knows how the game ends).
  const [createBotKind, setCreateBotKind, rememberBotKind] =
    useLastDifficulty("dontminion", myId, BOT_IDS, "bmplus");
  // Kingdom requirements — none by default, so a plain Create still deals the
  // fully random 10 the game has always dealt.
  const [createReqs, setCreateReqs] = useState([]);
  const [createPlayers, setCreatePlayers] = useState(4);
  // Base Set only by default — the newcomer's game, and the set every Dominion
  // player knows. Everything else is opt-in through the picker.
  const [createExps, setCreateExps] = useState(["base"]);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  const [gameOverDismissed, setGameOverDismissed] = useState(false);
  const [showTrash, setShowTrash] = useState(false);
  const [showKingdom, setShowKingdom] = useState(false);
  // The detail modal is not card-only. `info` is a DESCRIPTOR — {kind:"card"|
  // "landscape"|"thing", …} — because a mat, an Artifact and an Event are all
  // things a player points at and asks "what does this do?", and until now only
  // a card could answer. One state, one modal, one gesture (see THINGS).
  const [info, setInfo] = useState(null);
  const [deckView, setDeckView] = useState(null);    // game-over: whose final deck to show
  const [matView, setMatView] = useState(null);      // {label, cards} for a mat viewer modal
  const [lobbyTab, setLobbyTab] = useState("open");  // mobile-only Open/Active/History selector
  const [reviewOnly, setReviewOnly] = useState(false);  // HTTP-loaded finished-game review (no WS)
  const [reviewLoadingId, setReviewLoadingId] = useState(null);  // History row whose Review is in flight
  // decision-prompt interaction state (generic across all frame kinds)
  const [pickIdx, setPickIdx] = useState([]);        // choose_cards: selected INDICES (dups!)
  const [pickOpts, setPickOpts] = useState([]);      // choose_option pick>1: selected ids
  const [orderIdx, setOrderIdx] = useState([]);      // order_cards: click sequence of indices
  const [promptMin, setPromptMin] = useState(false); // decision modal minimized (peek at board)

  // ── URL routing refs (segment 2 = room id; the shell owns "/dontminion") ──
  const screenRef = useRef(screen);
  screenRef.current = screen;
  const roomIdRef = useRef(roomId);
  roomIdRef.current = roomId;
  const urlAttemptRef = useRef(null);
  const didInitRef = useRef(false);
  const popHandlerRef = useRef(() => {});
  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);
  const logRef = useRef(null);

  const playerName = authUser?.name || "Player";

  // ── derived (keep ABOVE all effects — TDZ rule) ──
  const game = roomData?.game;
  const names = roomData?.players || {};
  const cards = catalog?.cards || {};
  const seats = game?.seats || {};
  const mySeat = seats[myId];
  const over = !!game?.over;
  const pv = game?.pending_view || null;
  const iAmActor = !!pv && !over && game?.pending_pid === myId && !!pv.constraint;
  const waitingOn = pv && !iAmActor ? pv.waiting_on : null;
  const botActing = !!game && !over && (roomData?.ai_players || []).includes(game.pending_pid || game.turn);
  const bridges = game?.turn_ctx?.bridges || 0;
  // Prices come from the SERVER (engine.cost): Bridge, Quarry, Peddler's
  // dynamic self-cost and anything a future set adds. The bridges-only
  // fallback covers a pre-costs save being replayed by a cached client.
  // A PILE is not always the card it is named after. An ordered pile (Ruins,
  // Knights, a split pile) shows its TOP card, and that is what it costs, is,
  // and hands you when you buy it — so anything reading card data off a pile
  // name has to go through its face. The server owns the face (engine.cost
  // resolves it too); the fallback to the name itself covers both an ordinary
  // pile and a cached client looking at a pre-piles save.
  const pileFace = (name) => game?.piles?.[name]?.face || name;
  const pileLeft = (name) => game?.piles?.[name]?.count ?? game?.supply?.[name] ?? 0;
  const effCost = (name) => game?.costs?.[name]
    ?? Math.max(0, (cards[pileFace(name)]?.cost ?? 0) - bridges);
  const printedCost = (name) => cards[pileFace(name)]?.cost ?? 0;
  // Alchemy: the POTION half of a price. Rendered beside the coin cost rather
  // than folded into it — {$3, 1 Potion} is a different price from $3, and a
  // pile you cannot afford for want of a Potion has to look unaffordable.
  const potionCost = (name) => game?.potion_costs?.[name] ?? 0;
  const affordable = (name) => effCost(name) <= game.coins
    && potionCost(name) <= (game.potions ?? 0);
  // Coffers (Guilds / Cornucopia & Guilds) — public table state, spendable in
  // EITHER phase, which is why this is not gated on inBuy.
  const myCoffers = game?.coffers?.[myId] ?? 0;
  // What the SERVER says you may spend (engine.spendable). Read off the wire
  // rather than re-derived: the rule moved in ph. 7 — Coffers are spendable in
  // the middle of resolving an ability now, for Storyteller — and a client
  // carrying its own copy of it is the Peddler-cost bug's exact shape.
  const canSpend = (game?.spendable?.coffers ?? 0) > 0 && !over;
  // Debt (Empires) — the same shape one dimension over: a public counter with
  // a payoff you may make "at any time during your turn", $1 per token and
  // costing no Buy. How much you may pay RIGHT NOW is the server's number
  // (engine.spendable caps it by your money), never re-derived here.
  const myDebt = game?.debt?.[myId] ?? 0;
  const payableDebt = over ? 0 : (game?.spendable?.debt ?? 0);
  // MIRRORS engine.debt_blocks_buying: with any Debt you may buy nothing at
  // all — no card, no Event, no Project. Display only (the server refuses the
  // move regardless), but without it every pile lights up as affordable and
  // the click bounces, which reads as a broken board rather than a rule.
  const debtBlocks = myDebt > 0;
  // Villagers (Renaissance) — the other half of the Coffers mat, spent for
  // +1 Action each. The SERVER decides when: unlike Coffers they are ACTION
  // PHASE ONLY (they never got Coffers' 2022 "any time during your turn"
  // change), and that rule lives in engine.spendable, not here.
  const myVillagers = game?.villagers?.[myId] ?? 0;
  const spendableVillagers = over ? 0 : (game?.spendable?.villagers ?? 0);
  const inBuy = !!game && game.phase === "buy" && game.turn === myId && !game.pending_pid && !over;
  const inAction = !!game && game.phase === "action" && game.turn === myId && !game.pending_pid && !over;
  const bought = !!game?.turn_ctx?.bought;
  // "Play all treasures" SKIPS the interactive ones (War Chest/Anvil), so a
  // hand holding only those must not offer the button — it would do nothing.
  // built from what the SERVER offers, so shipping a set needs no frontend edit
  const expansionOptions = (catalog?.expansions?.length
    ? catalog.expansions
    : EXPANSIONS.map((e) => e.id)
  ).map((id) => ({
    id,
    name: EXPANSIONS.find((e) => e.id === id)?.name
      || id.charAt(0).toUpperCase() + id.slice(1),
  }));
  const allExpsOn = expansionOptions.length > 0
    && expansionOptions.every((e) => createExps.includes(e.id));
  // Kingdom requirements, from the server too (main.REQUIREMENT_ORDER) — the
  // bar for each ("+2 Actions") is the SERVER's label, so the picker can never
  // promise a threshold the dealer doesn't use.
  const requireOptions = catalog?.requirements || [];
  const manualTreasures = catalog?.manual_treasures || [];
  const handTreasures = (mySeat?.hand || []).some((c) => (cards[c]?.types?.includes("treasure")
    || (c === "Curse" && game?.curse_is_treasure)) && !manualTreasures.includes(c));
  const constraint = iAmActor ? pv.constraint : null;
  const byCost = (a, b) =>
    ((cards[pileFace(a)]?.cost ?? 0) - (cards[pileFace(b)]?.cost ?? 0))
    || a.localeCompare(b);
  // A pile is buyable only if it sits in the Supply. Non-Supply piles (Ferryman's
  // set-aside pile, Joust's Rewards) still ship, so guard the buy paths on this.
  const isSupplyPile = (name) => game?.piles?.[name]?.supply !== false;
  // The Kingdom row is EVERY Supply pile that isn't a basic one — derived from
  // the Supply, not game.kingdom, so a set-up extra Supply pile (Young Witch's
  // Bane) shows up and is buyable. Falls back to game.kingdom for a cached
  // pre-piles save that shipped no per-pile `supply` flags.
  const basicNames = new Set(basicsRowFor(game?.supply));
  const kingdomByCost = (game?.supply
    ? Object.keys(game.supply).filter((n) => !basicNames.has(n))
    : [...(game?.kingdom || [])]).sort(byCost);
  // Non-Supply piles set aside at setup — shown so the player can see what
  // Ferryman will gain, or which Rewards are available, when viewing the
  // Kingdom. They are info-only on the board (never buyable).
  const asidePiles = Object.entries(game?.piles || {})
    .filter(([, p]) => p.supply === false)
    .map(([n]) => n)
    .sort(byCost);
  // LANDSCAPES (Events/Projects/...). Their static data (cost, text, kind) is
  // in the catalog and never changes — "its cost cannot be changed by cards
  // like Bridge" — so unlike a pile there is no per-game price to read; the
  // game dict says only which ones are on the table and their state.
  const landscapeData = catalog?.landscapes || {};
  const boardLandscapes = Object.keys(game?.landscapes || {}).sort();
  // ...the same set, grouped by kind, for the Kingdom browser. Events, Projects
  // and Landmarks are dealt WITH the kingdom and belong in the thing that calls
  // itself "this game's Kingdom" — before this they existed only as a row above
  // the Supply, which scrolls away and says nothing about what a Project IS.
  const landscapeGroups = (() => {
    const by = {};
    for (const n of boardLandscapes) {
      const k = landscapeData[n]?.kind || game.landscapes[n]?.kind || "event";
      (by[k] = by[k] || []).push(n);
    }
    const rank = (k) => (KIND_ORDER.indexOf(k) + 1) || 99;
    return Object.entries(by).sort((a, b) => rank(a[0]) - rank(b[0]) || a[0].localeCompare(b[0]));
  })();
  // Artifacts (Renaissance) exist ONLY as a badge in front of whoever holds one
  // — so until someone takes it, an Artifact this game keeps available is
  // literally unreadable anywhere on the board. The Kingdom browser is where it
  // belongs, held or not.
  const gameArtifacts = Object.keys(game?.artifacts || {}).sort();
  // MIRRORS engine.landscape_gate + the legal_moves enumeration. Display only,
  // as always — the server stays authoritative and will refuse anything this
  // gets wrong. Kept beside the pile affordance for exactly that reason.
  const landscapeBuyable = (name) => {
    const d = landscapeData[name] || {};
    const st = game?.landscapes?.[name] || {};
    if (!["event", "project"].includes(st.kind)) return false;
    if (d.once === "turn" && st.bought_turn === game.turn_number) return false;
    if (d.once === "game" && (st.bought_by || []).includes(myId)) return false;
    return inBuy && !debtBlocks && game.buys > 0 && (d.cost ?? 99) <= game.coins;
  };
  // "spent" for the player: a once-per-game Event they have already bought is
  // shown dimmed and ticked rather than silently un-clickable.
  const landscapeSpent = (name) => {
    const d = landscapeData[name] || {};
    const st = game?.landscapes?.[name] || {};
    return d.once === "game" && (st.bought_by || []).includes(myId);
  };
  // Adventures tokens ON a pile: pile.attach.tokens = {pid: [kind, ...]}. Every
  // player's, flattened — they are public markers, and whose is whose matters
  // (a -$2 token only discounts on its OWNER's turns).
  // Gathered VP and Tax's Debt, both on the pile's public `attach` (ph. 7H).
  const pileVp = (name) => game?.piles?.[name]?.attach?.vp ?? 0;
  const pileDebt = (name) => game?.piles?.[name]?.attach?.debt ?? 0;
  const pileTokens = (name) => {
    const toks = game?.piles?.[name]?.attach?.tokens || {};
    return Object.entries(toks)
      .flatMap(([pid, kinds]) => (kinds || []).map((kind) => ({ pid, kind })));
  };
  const seatOrder = game?.players || Object.keys(names);
  // The single opponent play box tracks the ACTION: the opponent whose turn it
  // is — or, on your turn, whoever plays next. (2p: always the one opponent.)
  const focusOpp = !game ? null
    : game.turn !== myId ? game.turn
    : seatOrder[(seatOrder.indexOf(myId) + 1) % Math.max(seatOrder.length, 1)];
  // Undo walks back ONE move per press. undo_depth (how many snapshots the
  // server holds) is the WHOLE gate: a reveal empties the server's stack, so
  // depth 0 means "nothing reversible since the last new information" — and
  // moves made after a reveal are undoable again.
  const canUndo = !!game && !over && game.turn === myId
    && (game.undo_depth || 0) > 0;
  // Stable per-card keys so ONLY genuinely new cards mount — that mount is
  // what plays the entrance animation (drawn, played, gained).
  const handKeys = zoneKeys(mySeat?.hand || [], "h" + (game?.turn_number || 0));
  const inPlayKeys = zoneKeys(mySeat?.in_play || [], "p" + (game?.turn_number || 0));
  // What-you-can-do hint, shown at the right of the resource bar. Board-driven
  // prompts (choose_pile) live HERE instead of in their own prompt box.
  const promptCardName = displayCard(pv?.card);
  // A pile prompt describes what the CARD does ("gain a card costing up to
  // $4") rather than the mechanically obvious "pick a highlighted pile". The
  // text comes from the catalog, minus its vanilla +Card/+Action/+Buy/+$ lines;
  // when every eligible pile shares one cost (Upgrade, Swindler) the exact
  // target cost is appended, since the card text can't name it.
  const VANILLA_LINE = /^\+(\d+\s*(Cards?|Actions?|Buys?)|\$\d+)$/i;
  const effectText = (name) => (cards[name]?.text || "")
    .split("\n").map((s) => s.trim())
    .filter((s) => s && !VANILLA_LINE.test(s)).join(" ");
  const pileHint = (name, piles) => {
    const body = effectText(name);
    const parts = body.split(/\.\s+/).map((s, i, a) => (i < a.length - 1 ? s + "." : s));
    // a choose_pile prompt is always a GAIN/TRASH action, so prefer that clause
    // over a "names a card" one — War Chest reads "The player to your left names
    // a card. Gain a card costing up to $5…", and we want the Gain clause, not
    // the opponent's naming.
    const clause = parts.find((s) => /\b(gain|trash)\b/i.test(s))
      || parts.find((s) => /\bname/i.test(s)) || body;
    const costs = (piles || []).map(effCost);
    const band = costs.length && Math.min(...costs) === Math.max(...costs)
      ? ` (piles costing $${costs[0]})` : "";
    return `${name}: ${clause || "pick a highlighted Supply pile"}${band}`;
  };
  const resHint = (() => {
    if (!game || over || game.turn !== myId) return "";
    if (iAmActor) {
      return pv.kind === "choose_pile" ? pileHint(promptCardName, pv.constraint?.piles) : "";
    }
    if (game.pending_pid) return "";               // waiting bar covers it
    if (game.phase === "action") return "you may play Action cards";
    if (game.buys > 0) return bought ? "you may buy cards" : "you may play Treasures and buy cards";
    return "no buys left — end your turn";
  })();

  // ── socket plumbing ──
  const handleMessage = useCallback((msg) => {
    setConnecting(false);        // any authoritative reply ends the connect loader
    if (msg.type === "error") {
      const ua = urlAttemptRef.current;
      if (ua) {
        if (msg.message === "invalid token" && !ua.retried) {
          ua.retried = true;
          try { localStorage.removeItem(`dm_token_${ua.rid}_${myId}`); } catch {}
          resumeGame(ua.rid);
          return;
        }
        urlAttemptRef.current = null;
        try {
          if (localStorage.getItem("dm_roomId") === ua.rid) localStorage.removeItem("dm_roomId");
          localStorage.removeItem(`dm_token_${ua.rid}_${myId}`);
        } catch {}
        setRoomId(""); setRoomData(null); setScreen("lobby");
        replacePath(buildPath("dontminion"));
      }
      setToast(msg.message || "error"); return;
    }
    const room = msg.room;
    if (!room) return;
    const rid = room.room_id || roomId;
    const tok = room.reconnect_tokens?.[myId];
    if (tok) {
      try {
        localStorage.setItem(`dm_token_${rid}_${myId}`, tok);
        localStorage.setItem("dm_roomId", rid);
      } catch {}
    }
    setRoomData(room);
    const inGame = room.status === "playing" || room.status === "over";
    if (msg.type === "created" || msg.type === "joined" || msg.type === "reconnected") {
      if (rid) pushPath(buildPath("dontminion", rid));
      urlAttemptRef.current = null;
      setScreen(inGame ? "game" : "waiting");
    } else if (msg.type === "room_update" && inGame && screenRef.current !== "game") {
      setScreen("game");
    }
  }, [myId, roomId]); // eslint-disable-line react-hooks/exhaustive-deps

  const { connected, connect, send, disconnect, socketReady } = useSocket(handleMessage);

  useEffect(() => {
    fetch(`${DM_HTTP}/catalog`).then((r) => r.json()).then((d) => { if (d.ok) setCatalog(d); }).catch(() => {});
  }, []);

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${DM_HTTP}/games`).then((r) => r.json()).then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("dontminion", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${DM_HTTP}/games/mine`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("dontminion", myId, "mine", g); }).catch(() => {});
      fetch(`${DM_HTTP}/games/history`, { headers }).then((r) => r.json()).then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("dontminion", myId, "history", g); }).catch(() => {});
    } else { setMyGames([]); setHistory([]); writeLobbyCache("dontminion", myId, "mine", []); writeLobbyCache("dontminion", myId, "history", []); }
  }, [authUser, myId]);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  useEffect(() => { return () => disconnect(); }, []); // eslint-disable-line

  // ── URL deep entry + popstate ──
  const urlResume = (rid) => {
    setReviewOnly(false);   // a stale review must not linger past a URL-driven resume
    urlAttemptRef.current = { rid, retried: false };
    resumeGame(rid);
  };
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "dontminion" && r.room) urlResume(r.room);
  }, []); // eslint-disable-line
  popHandlerRef.current = (r) => {
    if (r.game !== "dontminion") return;
    if (r.room && r.room !== roomIdRef.current) {
      urlResume(r.room);
    } else if (!r.room && (roomIdRef.current || urlAttemptRef.current)) {
      urlAttemptRef.current = null;
      leaveToLobby();
    }
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // ── auto-reconnect while in a live game (re-kicks the bot scheduler server-side) ──
  const inLiveGame = !!roomId && !reviewOnly && (screen === "game" || screen === "waiting") && roomData?.status !== "over";
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) { reconnTimer.current = setTimeout(attemptReconnect, 3000); return; }
    let tok = null;
    try { tok = localStorage.getItem(`dm_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${DM_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);

  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear(); reconnTries.current = 0;
      if (connected) setReconnecting(false);
      return;
    }
    if (!reconnTimer.current) attemptReconnect();
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => {
    const onVis = () => {
      if (document.visibilityState !== "visible" || connected || !inLiveGame) return;
      reconnTries.current = 0;
      attemptReconnect();
    };
    document.addEventListener("visibilitychange", onVis);
    return () => document.removeEventListener("visibilitychange", onVis);
  }, [connected, inLiveGame, attemptReconnect]);

  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);

  // A connect that never answers (server asleep, socket never opens) must not
  // leave the spinner up forever — bail back to the lobby with a hint.
  useEffect(() => {
    if (!connecting) return;
    const t = setTimeout(() => {
      setConnecting(false);
      setToast("Still connecting — the server may be waking up. Try again in a moment.");
    }, 15000);
    return () => clearTimeout(t);
  }, [connecting]);

  // The log reads oldest-at-top, so the newest line is at the BOTTOM and the
  // view has to follow it — unless the reader deliberately scrolled up to
  // re-read a turn, which must not be yanked away by the next move.
  //
  // Stickiness is the reader's SCROLL INTENT (captured on their scroll events),
  // NOT the distance-from-bottom measured after the content grew: a bot turn
  // adds many lines at once, and on the short mobile log (180px) that jump
  // exceeded the old 80px gate, so the log stopped following on a phone. And
  // the scroll is deferred to rAF — iOS Safari drops a scrollTop set that races
  // the DOM update, the other half of why mobile wasn't scrolling.
  // ...and "the reader scrolled up" means a scroll THE READER CAUSED. The
  // browser moves scrollTop on its own too, and on a PC that is what broke
  // this: the list renders only the newest 200 lines, so once a game passes
  // 200 entries every turn EVICTS lines off the top — and Chrome/Firefox
  // SCROLL ANCHORING compensates by pulling scrollTop back to keep the visible
  // text still, which fires a scroll event reporting a large distance from the
  // bottom. A position-only test read that as "they scrolled up to re-read"
  // and latched the log in place for the rest of the game. iOS Safari
  // implements no scroll anchoring, which is exactly why the log kept
  // following on a phone and stopped on a desktop.
  // So: reaching the bottom always re-arms (whoever scrolled), and only a
  // scroll within a real gesture — wheel, drag, touch — may un-arm.
  const logLen = (game?.log || []).length;
  const logPinRef = useRef("");
  const logStickRef = useRef(true);
  const logGestureAtRef = useRef(0);
  const onLogGesture = useCallback(() => { logGestureAtRef.current = Date.now(); }, []);
  const onLogScroll = useCallback((e) => {
    const el = e.currentTarget;
    const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 48;
    if (atBottom) { logStickRef.current = true; return; }
    // 1.5s covers wheel inertia and touch momentum, which keep scrolling well
    // after the gesture's own events have stopped
    if (Date.now() - logGestureAtRef.current < 1500) logStickRef.current = false;
  }, []);
  useEffect(() => {
    const el = logRef.current;
    if (!el) return;
    const key = `${roomId}:${screen}`;
    const opened = logPinRef.current !== key;   // just opened this game
    if (opened) { logPinRef.current = key; logStickRef.current = true; }
    if (!opened && !logStickRef.current) return;
    const raf = requestAnimationFrame(() => { el.scrollTop = el.scrollHeight; });
    return () => cancelAnimationFrame(raf);
  }, [logLen, screen, roomId]);

  // clear decision-prompt state whenever the decision context changes
  useEffect(() => {
    setPickIdx([]); setPickOpts([]); setOrderIdx([]); setPromptMin(false);
  }, [game?.turn, game?.turn_number, game?.pending_kind, game?.pending_pid, (game?.log || []).length]);
  useEffect(() => { setGameOverDismissed(false); setDeckView(null); setMatView(null); }, [roomId]);

  // The engine auto-advances action->buy after moves and at turn hand-offs, but
  // deliberately not at game CREATION (test fixtures stage hands post-deal). The
  // client covers that one case: an action phase with no Action card in hand is
  // skipped, once per turn (never re-fired after an undo).
  const autoSkipRef = useRef("");
  useEffect(() => {
    if (!game || over || game.turn !== myId || game.phase !== "action" || game.pending_pid) return;
    const hand = mySeat?.hand || [];
    if (hand.some((c) => cards[c]?.types?.includes("action"))) return;
    const key = `${roomId}:${game.turn_number || 0}`;
    if (autoSkipRef.current === key) return;
    autoSkipRef.current = key;
    send({ action: "move", move: { type: "end_phase" } });
  }, [game, roomId, myId, over, mySeat, cards, send]);

  // ── actions ──
  const mv = (move) => send({ action: "move", move });

  const createGame = () => {
    // The server rejects an empty expansion set; the Create button is disabled
    // for it, and this is the belt to that suspenders (a stale click, a keyboard
    // submit) so the failure can never be an opaque socket error.
    if (!createExps.length) { setToast("Pick at least one expansion."); return; }
    const rid = roomCode();
    setRoomId(rid);
    setRoomData(null);
    setShowCreateModal(false);
    const msg = {
      action: "create", name: playerName, expansions: createExps,
      requires: createReqs, vs_ai: createOpp === "ai",
    };
    if (createOpp === "ai") {
      msg.num_bots = createBots;
      msg.ai_difficulty = createBotKind;
      rememberBotKind(createBotKind);   // this game's bot style is the next modal's default
    } else {
      msg.max_players = createPlayers;
    }
    setConnecting(true);
    connect(`${DM_WS}/${rid}/${myId}`, msg);
  };
  const joinGame = (rid) => {
    rid = (rid || "").toUpperCase().trim();
    if (!rid) return;
    setRoomId(rid);
    setConnecting(true);
    connect(`${DM_WS}/${rid}/${myId}`, { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  const resumeGame = (rid) => {
    let tok = null;
    try { tok = localStorage.getItem(`dm_token_${rid}_${myId}`); } catch {}
    setRoomId(rid);
    setConnecting(true);
    connect(`${DM_WS}/${rid}/${myId}`, tok ? { action: "reconnect", token: tok } : { action: "join", name: playerName, session_token: authUser?.session_token });
  };
  // Load + show a finished game read-only over HTTP (no WebSocket). Everything
  // reveals at game over, so the live game screen renders the whole thing: the
  // game-over panel (winner, scores, each player's final deck), the board, and
  // the full log — all already gated on `over`, so nothing is actionable.
  const enterReview = async (rid) => {
    if (reviewLoadingId) return;                 // one review load at a time
    setReviewLoadingId(rid);
    const headers = authUser?.session_token ? { Authorization: `Bearer ${authUser.session_token}` } : {};
    const url = `${DM_HTTP}/games/${rid}/review?player_id=${encodeURIComponent(myId)}`;
    // Render's free tier cold-starts (~30-50s, serving 503s while it wakes), and
    // the lobby History renders from localStorage cache — so the FIRST review
    // click can race the spin-up, and a 503/HTML body would make r.json() throw
    // into a dead-end toast. Retry through the wake like a browser, and only a
    // real JSON rejection (not your game / not finished) stops immediately.
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
    try {
      let d = null;
      for (let attempt = 0; attempt < 4; attempt++) {
        let res;
        try { res = await fetch(url, { headers }); }
        catch { await sleep(1500 * (attempt + 1)); continue; }   // offline / still waking
        if (res.status >= 500) { await sleep(1500 * (attempt + 1)); continue; }  // cold start
        try { d = await res.json(); } catch { d = null; }
        break;
      }
      if (!d) { setToast("Couldn't reach the server — it may be waking up. Try again in a moment."); return; }
      if (!d.ok) { setToast(d.message || "Could not load review"); return; }
      setReviewOnly(true);
      setGameOverDismissed(false);   // land on the results panel first
      setRoomData({
        game: d.game, players: d.players || {}, host: null, status: "over",
        vs_ai: false, ai_players: [],
      });
      setRoomId(rid);
      setScreen("game");
    } finally {
      setReviewLoadingId(null);
    }
  };
  const cancelGame = (rid) => {
    const headers = { "Content-Type": "application/json" };
    if (authUser?.session_token) headers.Authorization = `Bearer ${authUser.session_token}`;
    fetch(`${DM_HTTP}/games/${rid}/cancel?player_id=${encodeURIComponent(myId)}`, { method: "POST", headers })
      .then((r) => r.json()).then((d) => {
        if (!d.ok) { setToast(d.message || "Could not cancel"); return; }
        try {
          if (localStorage.getItem("dm_roomId") === rid) localStorage.removeItem("dm_roomId");
          localStorage.removeItem(`dm_token_${rid}_${myId}`);
        } catch {}
        fetchGames();
      }).catch(() => setToast("Could not cancel"));
  };
  const leaveToLobby = () => {
    disconnect();
    setConnecting(false);
    setReviewOnly(false);   // a read-only review holds no WS / resume pointer
    pushPath(buildPath("dontminion"));
    setScreen("lobby");
    setRoomData(null);
    setRoomId("");
  };
  const abandonGame = () => { send({ action: "abandon" }); setConfirmAbandon(false); };

  // ── the detail modal's three doors ──
  // Everything readable on the board goes through one of these. A card and a
  // landscape are named (their text is catalog data, so the modal reads it live
  // rather than snapshotting it); a THING is a key into the static table, plus
  // whatever per-instance facts the caller has (who holds this Artifact).
  const showCard = (name) => { if (name) setInfo({ kind: "card", name }); };
  const showLandscape = (name) => { if (name) setInfo({ kind: "landscape", name }); };
  const showThing = (key, extra) => { if (THINGS[key]) setInfo({ kind: "thing", key, ...extra }); };
  // An Artifact's rules text is the SERVER's (catalog.artifacts), and what the
  // generic entry adds is the part no card explains: what an Artifact even is.
  const showArtifact = (name) => setInfo({
    kind: "thing", key: "artifact", title: name,
    sub: game?.artifacts?.[name]
      ? `held by ${names[game.artifacts[name]] || game.artifacts[name]}`
      : "not taken yet",
    lead: catalog?.artifacts?.[name]?.text || "",
  });

  // Charlatan's game rule: Curse is also a Treasure (playable for $1)
  const typesFor = (c) => {
    const t = cards[c]?.types || [];
    return c === "Curse" && game?.curse_is_treasure ? [...t, "treasure"] : t;
  };

  // Every click lands somewhere: playable → play, buyable → buy, anything
  // else → the card-detail modal (never a dead click).
  const handClick = (card) => {
    const t = typesFor(card);
    if (!iAmActor && inAction && t.includes("action") && game.actions > 0) mv({ type: "play_action", card });
    else if (!iAmActor && inBuy && t.includes("treasure") && !bought) mv({ type: "play_treasure", card });
    else showCard(card);
  };
  const pileClick = (pile) => {
    if (iAmActor && constraint?.piles) {
      if (constraint.piles.includes(pile)) { mv({ type: "decision", pile }); return; }
      showCard(pileFace(pile)); return;
    }
    if (inBuy && !debtBlocks && game.buys > 0 && pileLeft(pile) > 0
        && isSupplyPile(pile) && affordable(pile)) {
      mv({ type: "buy", card: pile }); return;
    }
    showCard(pileFace(pile));
  };

  // ── render helpers ──
  const kindOfPrompt = iAmActor ? pv.kind : null;
  // These decision kinds open as a minimizable MODAL; choose_pile stays a
  // board hint, waiting-on stays an inline bar.
  const hasModalPrompt = iAmActor
    && ["choose_cards", "choose_option", "order_cards", "place_in_deck", "name_card"].includes(pv.kind);

  const promptTitle = () => {
    const c = constraint;
    const promptCard = displayCard(pv.card);
    switch (kindOfPrompt) {
      case "choose_cards": {
        const label = c.min === c.max ? `${c.purpose} ${c.min}` : c.min === 0 ? `${c.purpose} up to ${c.max}` : `${c.purpose} ${c.min}–${c.max}`;
        return `${promptCard}: ${label}${pickIdx.length ? ` (${pickIdx.length} picked)` : ""}`;
      }
      case "choose_option": {
        const pick = c.pick || 1;
        return pick === 1 ? promptCard : `${promptCard}: choose ${pick} (different)`;
      }
      case "order_cards": return `${promptCard}: click cards in order (first = top of deck)`;
      case "place_in_deck": return `Secret Passage: where in your deck? (${c.card})`;
      case "name_card": return `${promptCard}: name a card`;
      default: return promptCard;
    }
  };

  const promptBody = () => {
    const c = constraint;
    if (kindOfPrompt === "choose_cards") {
      const need = pickIdx.length;
      const okPick = need >= c.min && need <= c.max;
      return (
        <>
          <div className="dm-prompt-cards">
            {c.cards.map((n, i) => (
              <DmCardFace key={i} name={n} card={cards[n]} small
                selected={pickIdx.includes(i)}
                onClick={() => setPickIdx((s) => pickToggle(s, i, c.max))}
                onInfo={() => showCard(n)} />
            ))}
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" disabled={!okPick}
              onClick={() => { mv({ type: "decision", cards: pickIdx.map((i) => c.cards[i]) }); }}>
              Confirm{c.purpose === "pass" ? " (kept secret)" : ""}
            </button>
            {c.min === 0 && <button className="btn btn-outline" onClick={() => mv({ type: "decision", cards: [] })}>None</button>}
          </div>
        </>
      );
    }
    if (kindOfPrompt === "choose_option") {
      const pick = c.pick || 1;
      if (pick === 1) {
        return (
          <div className="dm-prompt-actions">
            {c.options.map((o) => (
              <button key={o.id} className="btn btn-gold" onClick={() => mv({ type: "decision", ids: [o.id] })}>
                <FitLabel>{o.label}</FitLabel>
              </button>
            ))}
          </div>
        );
      }
      return (
        <div className="dm-prompt-actions">
          {c.options.map((o) => (
            <button key={o.id}
              className={"btn " + (pickOpts.includes(o.id) ? "btn-gold" : "btn-outline")}
              onClick={() => setPickOpts((s) => pickToggle(s, o.id, pick))}>
              <FitLabel>{o.label}</FitLabel>
            </button>
          ))}
          <button className="btn btn-gold" disabled={pickOpts.length !== pick}
            onClick={() => mv({ type: "decision", ids: pickOpts })}>Confirm</button>
        </div>
      );
    }
    if (kindOfPrompt === "order_cards") {
      const remaining = c.cards.map((n, i) => i).filter((i) => !orderIdx.includes(i));
      return (
        <>
          <div className="dm-prompt-cards">
            {c.cards.map((n, i) => (
              <DmCardFace key={i} name={n} card={cards[n]} small
                selected={orderIdx.includes(i)}
                badge={orderIdx.includes(i) ? orderIdx.indexOf(i) + 1 : null}
                onClick={() => setOrderIdx((s) => s.includes(i) ? s.filter((x) => x !== i) : [...s, i])}
                onInfo={() => showCard(n)} />
            ))}
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" disabled={remaining.length > 0}
              onClick={() => mv({ type: "decision", order: orderIdx.map((i) => c.cards[i]) })}>Confirm order</button>
            <button className="btn btn-outline" onClick={() => setOrderIdx([])}>Reset</button>
          </div>
        </>
      );
    }
    if (kindOfPrompt === "place_in_deck") {
      return (
        <div className="dm-prompt-actions dm-slots">
          {Array.from({ length: c.deck_len + 1 }, (_, p) => (
            <button key={p} className="btn btn-outline"
              onClick={() => mv({ type: "decision", position: p })}>
              {p === 0 ? "Top" : p === c.deck_len ? "Bottom" : p}
            </button>
          ))}
        </div>
      );
    }
    if (kindOfPrompt === "name_card") {
      return (
        <div className="dm-prompt-actions dm-names">
          {c.cards.map((n) => (
            <button key={n} className="btn btn-outline" onClick={() => mv({ type: "decision", card: n })}>
              <FitLabel>{n}</FitLabel>
            </button>
          ))}
        </div>
      );
    }
    return null;
  };

  // inline slot above the supply: only the waiting bar and the rare
  // off-turn choose_pile keep living here
  const renderPrompt = () => {
    if (!game || over) return null;
    if (waitingOn) {
      return (
        <div className="dm-waitbar">
          Waiting for <b>{names[waitingOn] || waitingOn}</b>
          {pv?.card && pv.card !== "__attack" ? <> — {displayCard(pv.card)}</> : null}
          {botActing ? <span className="dm-dots">…</span> : null}
        </div>
      );
    }
    if (iAmActor && kindOfPrompt === "choose_pile" && game.turn !== myId) {
      return (
        <div className="dm-prompt">
          <div className="dm-prompt-hd">{pileHint(promptCardName, constraint?.piles)}</div>
        </div>
      );
    }
    return null;
  };

  // decision MODAL — minimize to study the board; the restore button takes the
  // hint slot in the resource bar
  const renderPromptModal = () => {
    if (!hasModalPrompt || promptMin || over) return null;
    return (
      <div className="dm-backdrop dm-backdrop-top" onClick={() => setPromptMin(true)}>
        <div className="dm-modal dm-prompt dm-prompt-modal" onClick={(e) => e.stopPropagation()}>
          <div className="dm-prompt-hdrow">
            <div className="dm-prompt-hd">{promptTitle()}</div>
            <button className="btn btn-ghost btn-sm" onClick={() => setPromptMin(true)}>▾ Look at the board</button>
          </div>
          {promptBody()}
        </div>
      </div>
    );
  };

  const renderPile = (name, idx = 0) => {
    // the FACE, not the pile name — an ordered pile shows its top card
    const face = pileFace(name);
    const cardData = cards[face];
    const count = pileLeft(name);
    const promptPiles = iAmActor && constraint?.piles ? constraint.piles : null;
    const highlight = promptPiles ? promptPiles.includes(name)
      : (inBuy && !debtBlocks && game.buys > 0 && count > 0
         && isSupplyPile(name) && affordable(name));
    const disabled = promptPiles ? !promptPiles.includes(name)
      : (count === 0 || !isSupplyPile(name));
    return (
      <div key={name} className="dm-pile-slot"
        style={{ animationDelay: Math.min(idx * 16, 260) + "ms" }}>
        <DmCardFace name={face} card={cardData} small body
          highlight={highlight} disabled={disabled && !highlight}
          onClick={() => pileClick(name)} onInfo={() => showCard(face)} />
        {/* the count sits OUTSIDE the card (the card clips its overflow) */}
        <span className="dm-pile-count"><Pop n={count} /></span>
        {/* any active discount (Bridge, Quarry, Peddler's own rule) */}
        {cardData && effCost(name) !== printedCost(name)
          && <span className="dm-disc">now {effCost(name)}</span>}
        {/* Young Witch's Bane — the one extra pile added to the Supply. Marked
            top-right (the Potion cost now lives on the card face itself). */}
        {game.bane === name && <span className="dm-bane" title="Young Witch's Bane">B</span>}
        {/* Adventures tokens sitting ON this pile. Top-LEFT, deliberately: the
            Bane marker owns top-right and the count pill straddles the bottom
            edge, so this is the only corner left free. */}
        {/* VP tokens GATHERED on this pile (Farmers' Market/Temple/Wild Hunt
            gather their own; Aqueduct and Defiled Shrine seed other piles) and
            Tax's Debt. Both are public per-pile state and both change what the
            pile is worth buying, so they sit on the face. */}
        {(pileVp(name) > 0 || pileDebt(name) > 0) && (
          <span className="dm-pile-attach">
            {pileVp(name) > 0 && (
              <span className="dm-pile-vp" title="VP tokens on this pile">
                &#9733;<Pop n={pileVp(name)} /></span>
            )}
            {pileDebt(name) > 0 && (
              <span className="dm-pile-debt" title="Debt the next buyer takes">
                <Pop n={pileDebt(name)} />D</span>
            )}
          </span>
        )}
        {/* Adventures tokens on this pile. "+C" on a pile corner is a glyph
            nobody can guess, so each one answers the info gesture with the
            rule it stands for — and whose it is. */}
        {pileTokens(name).length > 0 && (
          <span className="dm-tokens">
            {pileTokens(name).map(({ pid, kind }, i) => (
              <DmChip key={i} className={"dm-tok" + (pid === myId ? " dm-tok-mine" : "")}
                title={`${names[pid] || pid}'s ${kind} token`}
                onInfo={() => showThing("tok:" + kind, {
                  sub: `${pid === myId ? "yours" : `${names[pid] || pid}'s`} — on ${name}`,
                })}>
                {TOKEN_GLYPH[kind] || "•"}
              </DmChip>
            ))}
          </span>
        )}
      </div>
    );
  };

  // A landscape face: LANDSCAPE-orientation (wide), because that is what they
  // physically are and what tells them apart from the Supply at a glance.
  // Click buys; the info gesture (right-click / press-and-hold) reads it, like
  // every other face — and a landscape you CAN'T buy (a Landmark, an Event you
  // can't afford, one you already took) opens the detail modal on a plain click
  // too, the same "nothing on the board is a dead click" rule the cards keep.
  // `readOnly` is the Kingdom browser's copy: it is a reference shelf, so a
  // click there must READ the Event, never spend a Buy on it from behind an
  // open modal.
  const renderLandscape = (name, idx = 0, readOnly = false) => (
    <DmLandscape key={name} name={name} idx={idx}
      d={landscapeData[name] || {}} st={game?.landscapes?.[name] || {}}
      buyable={!readOnly && landscapeBuyable(name)} spent={landscapeSpent(name)}
      seatOrder={seatOrder} names={names} myId={myId}
      onBuy={() => mv({ type: "buy_landscape", name })}
      onInfo={() => showLandscape(name)} />
  );

  // THE detail modal — one panel, three shapes. A card gets its real face beside
  // the text; a landscape gets its real (wide) face; a thing gets an emblem,
  // because there is no physical face to draw. Everything else about the panel —
  // title, meta line, rules text, Close — is identical on purpose: the reader
  // learns one thing to read, not three.
  const renderInfoModal = () => {
    if (!info) return null;
    const close = () => setInfo(null);
    let face = null, title = "", meta = "", text = "", tint = "";

    if (info.kind === "card") {
      const c = cards[info.name];
      if (!c) return null;
      tint = faceClass(c.types);
      face = <div className="dm-cardinfo-face"><DmCardFace name={info.name} card={c} /></div>;
      title = info.name;
      meta = [
        `Cost $${c.cost}`
          + (effCost(info.name) !== printedCost(info.name) ? ` (now $${effCost(info.name)})` : "")
          + (c.debt ? ` + ${c.debt} Debt` : "") + (c.potion ? " + Potion" : ""),
        (c.types || []).map((t) => TYPE_LABEL[t] || t).join(" – "),
        game.piles?.[info.name]
          ? `${pileLeft(info.name)} left${game.piles[info.name].supply ? " in the Supply" : ""}` : "",
      ].filter(Boolean).join(" · ");
      text = c.text || "";
    } else if (info.kind === "landscape") {
      const d = landscapeData[info.name] || {};
      const st = game?.landscapes?.[info.name] || {};
      const kind = d.kind || st.kind || "event";
      face = (
        <div className="dm-cardinfo-face dm-cardinfo-lscape">
          <DmLandscape name={info.name} d={d} st={st} buyable={false} spent={false}
            seatOrder={seatOrder} names={names} myId={myId} />
        </div>
      );
      title = info.name;
      meta = [
        kindPlural(kind).replace(/s$/, ""),
        kind === "landmark" || kind === "way" || kind === "trait" ? ""
          : [d.cost != null ? `costs $${d.cost}` : "", d.debt ? `${d.debt} Debt` : ""].filter(Boolean).join(" + "),
        // "once per turn" / "once per game" is a real rule and it is printed
        // nowhere on the face — only the ✓ tick hints at it after the fact.
        d.once === "game" ? "once per game, per player" : d.once === "turn" ? "once per turn" : "",
        (st.bought_by || []).length ? `${st.bought_by.length} cube${st.bought_by.length === 1 ? "" : "s"} on it` : "",
        st.vp ? `${st.vp} VP left on it` : "",
      ].filter(Boolean).join(" · ");
      // What a landscape's kind MEANS is the half a first-time reader is
      // missing, and it is not on the card either — so it leads the text.
      text = [LANDSCAPE_BLURB[kind] || "", d.text || ""].filter(Boolean).join("\n\n");
    } else {
      const t = THINGS[info.key];
      if (!t) return null;
      face = <div className="dm-cardinfo-face dm-cardinfo-emblem"><span>{t.icon}</span></div>;
      title = info.title || t.title;
      meta = info.sub != null ? info.sub : t.sub;
      text = [info.lead || "", t.text].filter(Boolean).join("\n\n");
    }

    return (
      <div className="dm-backdrop" onClick={close}>
        <div className={"dm-modal dm-cardinfo " + tint} onClick={(e) => e.stopPropagation()}>
          <div className="dm-cardinfo-cols">
            {face}
            <div className="dm-cardinfo-detail">
              <h2>{title}</h2>
              {meta && <p className="dm-cardinfo-meta">{meta}</p>}
              <p className="dm-cardinfo-text">{text}</p>
            </div>
          </div>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" onClick={close}>Close</button>
          </div>
        </div>
      </div>
    );
  };

  // Sidebar player box (one per seat, above the Trash): identity + score only —
  // name, VP, turns taken, and whose turn it is. Card zones live in play boxes.
  const renderPlayerBox = (pid) => {
    const s = seats[pid] || {};
    const isBot = (roomData?.ai_players || []).includes(pid);
    const acting = !over && (game.pending_pid || game.turn) === pid;
    return (
      <div key={pid} className={"dm-pbox" + (acting ? " dm-pbox-acting" : "")}>
        <span className="dm-pbox-name">
          {names[pid] || pid}{isBot ? " 🤖" : ""}{pid === myId ? " (you)" : ""}
        </span>
        {acting && (
          <TurnBadge mine={pid === myId}>
            {game.pending_pid === pid ? "deciding" : pid === myId ? "your turn" : "their turn"}
          </TurnBadge>
        )}
        <span className="dm-vp" title="victory points">🛡 <Pop n={game.vp?.[pid] ?? 0} /> VP</span>
        {(game.vp_tokens?.[pid] || 0) > 0 && (
          <DmChip className="dm-opp-turns" title="VP tokens (included in the total)"
            onInfo={() => showThing("vp_tokens")}>⭐ <Pop n={game.vp_tokens[pid]} /></DmChip>
        )}
        {/* DEBT (Empires): public, and it stops that player buying ANYTHING
            until it is paid off at $1 per token — which is exactly why it is
            on every seat's row and not only your own. */}
        {(game.debt?.[pid] || 0) > 0 && (
          <DmChip className="dm-debt" title="Debt — can't buy anything until it's paid off ($1 per token)"
            onInfo={() => showThing("debt")}>
            🪙 <Pop n={game.debt[pid]} /> Debt</DmChip>
        )}
        <span className="dm-opp-turns" title="turns taken">⏱ {s.turns_taken ?? 0}</span>
        {/* VILLAGERS (Renaissance) — the other half of the Coffers mat. Public
            like Coffers: an opponent sitting on six Villagers is about to
            take a very long turn, and that is information the table has. */}
        {(game.villagers?.[pid] || 0) > 0 && (
          <DmChip className="dm-opp-turns" title="Villagers — each is +1 Action in their Action phase"
            onInfo={() => showThing("villagers")}>
            🧑 <Pop n={game.villagers[pid]} /></DmChip>
        )}
        {(game.coffers?.[pid] || 0) > 0 && (
          <DmChip className="dm-opp-turns" title="Coffers — each is +$1, spendable any time in their turn"
            onInfo={() => showThing("coffers")}>
            🪙 <Pop n={game.coffers[pid]} /></DmChip>
        )}
        {/* ARTIFACTS (Renaissance): one copy of each exists and it sits in
            front of whoever took it last — public, and taken FROM the
            previous holder, so the badge has to move rather than duplicate. */}
        {Object.entries(game.artifacts || {})
          .filter(([, holder]) => holder === pid)
          .map(([a]) => (
            <DmChip key={a} className="dm-seat-tok"
              title={`${a} — ${catalog?.artifacts?.[a]?.text || "Artifact"}`}
              onInfo={() => showArtifact(a)}>
              🏳 {a}
            </DmChip>
          ))}
        {/* Adventures tokens that sit in front of a PLAYER rather than on a
            pile. Public markers, so they render for every seat — and the two
            negative ones matter enough to the reader that hiding them would be
            the surprise ("why did I only draw 4?"). */}
        {seatTokens(s).map(({ key, thing, glyph, title, extra }) => (
          <DmChip key={key} className="dm-seat-tok" title={title}
            onInfo={() => showThing(thing, extra)}>{glyph}</DmChip>
        ))}
      </div>
    );
  };

  // Opponent PLAY box (center column, same width as mine): face-DOWN backs for
  // the hand, face-UP cards for what they've played, real deck/discard piles.
  const renderOppPlay = (pid) => {
    const s = seats[pid] || {};
    const acting = !over && (game.pending_pid || game.turn) === pid;
    const handN = Math.min(s.hand_count ?? 0, 12);
    return (
      <div key={pid} className={"dm-opp" + (acting ? " dm-opp-acting" : "")}>
        <div className="dm-opp-zones">
          <DmPile kind="deck" label="deck" count={s.deck_count ?? 0} />
          <DmPile kind="discard" label="discard" count={s.discard_view?.count ?? 0}
            top={s.discard_view?.top} card={cards[s.discard_view?.top]}
            onInfo={() => showCard(s.discard_view?.top)} />
          <div className="dm-opp-hand dm-pile-slot" title={`${s.hand_count ?? 0} cards in hand`}>
            <div className="dm-fan">
              {handN > 0
                ? Array.from({ length: handN }, (_, i) => <DmCardBack key={i} />)
                : <div className="dm-empty-slot" />}
            </div>
            <span className="dm-pile-count">hand <Pop n={s.hand_count ?? 0} /></span>
          </div>
          <div className="dm-opp-inplay">
            {(s.duration_view || []).flatMap((e, i) => [
              <div key={"d" + i} className="dm-durwrap" title="Duration — stays in play">
                <DmCardFace name={e.card} card={cards[e.card]} small onInfo={() => showCard(e.card)} />
              </div>,
              ...(e.riders || []).map((r, j) => (
                <div key={"d" + i + "r" + j} className="dm-durwrap">
                  <DmCardFace name={r} card={cards[r]} small onInfo={() => showCard(r)} />
                </div>
              )),
            ])}
            {(() => {
              const ip = s.in_play || [];
              const ks = zoneKeys(ip, "o" + pid + (game.turn_number || 0));
              return ip.map((c, i) => (
                <DmCardFace key={ks[i]} name={c} card={cards[c]} small onInfo={() => showCard(c)} />
              ));
            })()}
            {(s.in_play || []).length === 0 && (s.duration_view || []).length === 0
              && <span className="dm-zone-hint">nothing in play</span>}
            {(s.island || []).length > 0 && (
              <DmMatChip emoji="🏝" count={s.island.length} label="Island mat"
                cards={s.island} onView={setMatView} onInfo={() => showThing("mat:island")} />
            )}
            {(s.village_count || 0) > 0 && (
              /* face down — the opponent's mat contents are hidden, count only */
              <DmMatChip emoji="🏕" count={s.village_count} label="Native Village mat"
                cards={null} onView={setMatView} onInfo={() => showThing("mat:village")} />
            )}
            {/* ...whereas a Tavern mat IS face up, so an opponent's contents show */}
            {(s.tavern || []).length > 0 && (
              <DmMatChip emoji="🍺" count={s.tavern.length} label="Tavern mat"
                cards={s.tavern} onView={setMatView} onInfo={() => showThing("mat:tavern")} />
            )}
            {/* The EXILE mat (Menagerie) is face up too, and it SCORES — an
                opponent's Exiled Estates are part of the score line everyone
                can already see, so hiding the contents would leave that number
                unexplainable. */}
            {(s.exile || []).length > 0 && (
              <DmMatChip emoji="🚪" count={s.exile.length} label="Exile mat"
                cards={s.exile} onView={setMatView} />
            )}
          </div>
        </div>
      </div>
    );
  };

  const renderGameOver = () => {
    if (!over || gameOverDismissed) return null;
    const scores = game.scores || {};
    const ranked = [...seatOrder].sort((a, b) => (scores[b]?.vp ?? 0) - (scores[a]?.vp ?? 0));
    const winners = game.winners || [];
    // Drilldown: one player's full final deck (every zone folded to counts).
    // Grouped by type — Treasures, then Actions, then Victory, then Curses —
    // and within each group most expensive first (then name). A card with
    // several types counts as an Action if it has the Action type at all, so an
    // Action-Victory like Nobles sits with the Actions rather than the Victory.
    if (deckView) {
      const counts = deckCensus(seats[deckView]);
      const typeRank = (name) => {
        const t = cards[name]?.types || [];
        if (t.includes("action")) return 1;
        if (t.includes("treasure")) return 0;
        if (t.includes("victory")) return 2;
        if (t.includes("curse")) return 3;
        return 4;
      };
      const entries = Object.entries(counts).sort((a, b) =>
        (typeRank(a[0]) - typeRank(b[0]))
        || ((cards[b[0]]?.cost ?? 0) - (cards[a[0]]?.cost ?? 0))
        || a[0].localeCompare(b[0]));
      const total = entries.reduce((n, [, k]) => n + k, 0);
      return (
        <div className="dm-backdrop" onClick={() => setDeckView(null)}>
          <div className="dm-modal dm-deckview" onClick={(e) => e.stopPropagation()}>
            <h2>{names[deckView] || deckView}{deckView === myId ? " (you)" : ""}</h2>
            <p className="dm-wait-note">Final deck — {total} cards · {scores[deckView]?.vp ?? "?"} VP</p>
            <div className="dm-deck-list">
              {entries.map(([name, k]) => (
                <div key={name} className={"dm-deck-row " + faceClass(cards[name]?.types)}>
                  <span className="dm-deck-count">{k}&times;</span>
                  <span className="dm-deck-name">{name}</span>
                  <span className="dm-deck-cost">${cards[name]?.cost ?? "?"}</span>
                </div>
              ))}
            </div>
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setDeckView(null)}>&larr; Back</button>
            </div>
          </div>
        </div>
      );
    }
    return (
      <div className="dm-backdrop">
        <div className="dm-modal">
          <h2>{winners.includes(myId) ? "Victory!" : "Game over"}</h2>
          <p className="dm-winline">
            {winners.length > 1 ? "Shared victory: " : "Winner: "}
            {winners.map((w) => names[w] || w).join(" & ")}
          </p>
          <table className="dm-scores">
            <thead><tr><th></th><th>VP</th><th>Turns</th><th></th></tr></thead>
            <tbody>
              {ranked.map((p) => (
                <tr key={p} className={"dm-score-row" + (winners.includes(p) ? " dm-win" : "")}
                  onClick={() => setDeckView(p)} title="See this player's final deck">
                  <td>{names[p] || p}{p === myId ? " (you)" : ""}</td>
                  <td>{scores[p]?.vp ?? "?"}</td>
                  <td>{scores[p]?.turns ?? "?"}</td>
                  <td className="dm-score-deck">deck &rsaquo;</td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className="dm-prompt-actions">
            <button className="btn btn-gold" onClick={leaveToLobby}>Back to lobby</button>
            <button className="btn btn-outline" onClick={() => setGameOverDismissed(true)}>View board</button>
          </div>
        </div>
      </div>
    );
  };

  const renderRules = () => (
    <RulesModal title="How to play — Dontminion" onClose={() => setShowRules(false)}>
      <DontminionRules />
    </RulesModal>
  );

  // ─── screens ───────────────────────────────────────────────────────────────
  // Connecting to a room (deep-link resume / join / create) while still on the
  // lobby screen → show the spinner, not the lobby, so a reconnect doesn't flash
  // the lobby then snap into the game (matches CoC).
  if (connecting && screen === "lobby") {
    return (
      <div className="app dm" style={{ "--lby-accent": GAME_ACCENTS.dontminion }}>
        <style>{dmStyles}</style>
        <div className="dm-center"><LobbyLoading label="Connecting…" /></div>
      </div>
    );
  }
  if (screen === "lobby") {
    // A room you are in but which has not STARTED is waiting, not active — it is
    // already listed under Open with a Cancel. Named once here rather than filtered
    // inline at the map, so the section's count and its list cannot disagree (they
    // did: the count read `myGames`, the list read `notWaiting(myGames)`).
    const activeMine = notWaiting(myGames);
    return (
      <div className="app dm" style={{ "--lby-accent": GAME_ACCENTS.dontminion }}>
        <style>{dmStyles}</style>
        <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser || { name: "Guest", guest: true }} />} />
        <div className="lby-page"><div className="lby-page-in">
        <LobbyHero game="dontminion">
        <LobbyCreateRow onCreate={() => setShowCreateModal(true)} onJoin={joinGame}
          onRefresh={fetchGames} refreshing={loadingGames}
          onRules={() => setShowRules(true)} />
        </LobbyHero>
        {showCreateModal && (
          <CreateModal title="New Game" onClose={() => setShowCreateModal(false)}>
            <CmRow label="Opponent">
              <CmSeg options={[{ value: "ai", label: "vs AI" }, { value: "friend", label: "vs Friends" }]}
                value={createOpp} onChange={setCreateOpp} />
            </CmRow>
            {createOpp === "ai" ? (
              /* Two labelled segments on ONE line. Stacked they cost 126px of a
                 modal that must not itself scroll, and the bot count is three
                 single digits — it never needed a full row. The 1:2 split is
                 what keeps "Big Money" on one line at phone width. */
              <div className="cm-row dm-cm-two">
                <div className="dm-cm-col">
                  <span className="cm-label">Bots</span>
                  <CmSeg options={[1, 2, 3].map((n) => ({ value: n, label: String(n) }))}
                    value={createBots} onChange={setCreateBots} />
                </div>
                <div className="dm-cm-col dm-cm-botstyle">
                  <span className="cm-label">Bot style</span>
                  <CmSeg options={BOTS.map((b) => ({ value: b.id, label: b.name, title: b.title }))}
                    value={createBotKind} onChange={setCreateBotKind} />
                </div>
              </div>
            ) : (
              <CmRow label="Players">
                <CmSeg options={[2, 3, 4].map((n) => ({ value: n, label: String(n) }))}
                  value={createPlayers} onChange={setCreatePlayers} />
              </CmRow>
            )}
            <CmRow label="Expansions">
              {/* The LIST scrolls, not the modal — the set count grows every
                  phase, and a picker that pushes Create below the fold is the
                  thing that breaks first. Select all is a plain toggle. */}
              <div className="dm-checks">
                {expansionOptions.map((ex) => {
                  const on = createExps.includes(ex.id);
                  return (
                    <button key={ex.id} type="button"
                      className={"dm-check" + (on ? " dm-check-on" : "")}
                      onClick={() => setCreateExps((s) => on
                        ? s.filter((x) => x !== ex.id)
                        : [...s, ex.id])}>
                      {on ? "☑" : "☐"} {ex.name}
                    </button>
                  );
                })}
              </div>
              <button type="button"
                className={"dm-check dm-check-all" + (allExpsOn ? " dm-check-on" : "")}
                onClick={() => setCreateExps(allExpsOn ? [] : expansionOptions.map((e) => e.id))}>
                {allExpsOn ? "☑" : "☐"} Select all
              </button>
            </CmRow>
            {requireOptions.length > 0 && (
              /* Not a plain CmRow: the label sits INLINE with the chips (see
                 .dm-req-row) because the modal has no vertical budget for
                 another stacked row. */
              <div className="cm-row dm-req-row">
                <span className="cm-label">Require</span>
                {/* Guarantee the random 10 contains at least one card giving
                    each checked bonus. Multi-select, none checked by default —
                    an unchecked list deals exactly the board it always did. */}
                <div className="dm-checks-req">
                  {requireOptions.map((rq) => {
                    const on = createReqs.includes(rq.id);
                    return (
                      <button key={rq.id} type="button"
                        className={"dm-check" + (on ? " dm-check-on" : "")}
                        onClick={() => setCreateReqs((s) => on
                          ? s.filter((x) => x !== rq.id)
                          : [...s, rq.id])}>
                        {on ? "☑" : "☐"} {rq.label}
                      </button>
                    );
                  })}
                </div>
              </div>
            )}
            <div className="cm-hint">
              {!createExps.length
                ? "Pick at least one expansion to deal a Kingdom from."
                : createReqs.length
                  ? `10 kingdom piles are dealt at random from the enabled expansions, always including a card that gives ${createReqs
                      .map((r) => requireOptions.find((x) => x.id === r)?.label || r)
                      .join(", ")}.`
                  : "10 kingdom piles are dealt at random from the enabled expansions."}
            </div>
            <div className="cm-footer">
              <span className="cm-summary">
                {createOpp === "ai"
                  ? `You + ${createBots} ${BOTS.find((b) => b.id === createBotKind)?.name || "bot"} bot${createBots > 1 ? "s" : ""}`
                  : `Up to ${createPlayers} players`}
                {createExps.length
                  ? " · " + createExps.map((e) => expansionOptions.find((x) => x.id === e)?.name || e).join(" + ")
                  : ""}
              </span>
              <button className="btn btn-gold cm-create" disabled={!createExps.length}
                onClick={createGame}>Create</button>
            </div>
          </CreateModal>
        )}
        {/* Mobile-only tab bar: the three columns can't sit side by side on a
            phone, so pick ONE section to show. Hidden on wide screens (CSS). */}
        <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
          { key: "open", label: "Open", count: openGames.length || null },
          { key: "active", label: "Active", count: myGames.length || null },
          { key: "history", label: "History", count: history.length || null },
        ]} />
        <div className={"dm-lobby-cols lby-cols tab-" + lobbyTab}>
          <div className="dm-section lby-col-open">
            <LobbySectionHd title="Open Games" note={`${openGames.length} waiting`} />
            {openGames.length === 0 && <div className="lby-empty">No open games — create one.</div>}
            <div className="lby-list">
            {openGames.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  <div className="lby-card-title">{g.host_id === myId ? "Your game" : `${g.host_name || "Player"}'s game`}
                    <span className="lby-seats">{g.player_count}/{g.max_players}</span></div>
                  {/* The expansion list goes LAST. The meta truncates from the right,
                      so whatever sits at the end is what a narrow column gives up —
                      and the room code and the age are how you identify and rank a
                      row, while the sets are how you choose between two you already
                      understand. */}
                  {/* The set names are TITLE CASE and live in their own span. Raw,
                      they were the only lowercase running text in the system ("base +
                      intrigue") and read as database values that escaped the
                      formatter; and on a phone this line truncated mid-word to
                      "seasi…" on the one row whose two buttons squeeze it, so the span
                      is what lets the least load-bearing token step aside there
                      instead (see `.lby-meta-extra`). */}
                  <div className="lby-card-meta">
                    {g.id} · {timeAgo(g.created_at)}
                    {(g.expansions || []).length ? (
                      <span className="lby-meta-extra"> · {(g.expansions || [])
                        .map((x) => String(x).replace(/(^|[\s-])(\w)/g, (m) => m.toUpperCase()))
                        .join(" + ")}</span>
                    ) : null}
                  </div>
                </div>
                <div className="lby-card-actions">
                  {g.host_id === myId
                    ? <>
                        <LobbyAction kind="secondary" onClick={() => resumeGame(g.id)}>Return</LobbyAction>
                        <LobbyAction kind="danger" onClick={() => cancelGame(g.id)}>Cancel</LobbyAction>
                      </>
                    : <LobbyAction onClick={() => joinGame(g.id)}>Join</LobbyAction>}
                </div>
              </div>
            ))}
            </div>
          </div>
          <div className="dm-section lby-col-active">
            <LobbySectionHd title="Active Games" note={`${activeMine.length} in progress`} />
            <div className="lby-list">
            {activeMine.map((g) => (
              <div key={g.id} className="lby-card">
                <div className="lby-card-info">
                  {/* `seats` is the new shape (seat order + which one is you); the
                      `opponents` fallback is for a bundle that loads against a
                      backend from before it, and drops out at the contract step. */}
                  <LobbyMatchup seats={g.seats || (g.opponents || []).map((n) => ({ name: n }))} />
                  <div className="lby-card-meta">{g.id} · {timeAgo(g.updated_at)}</div>
                </div>
                {/* THE TURN PILL BELONGS ON THE ACTIONS RAIL, beside Resume, which is
                    where the other five games put it. It sat inline in the META line
                    here — mid-sentence, between the status word and the timestamp —
                    so a glance down the column could not answer "which of these is
                    waiting on me" without reading, and the row it appeared in came
                    out ~22px taller than its neighbours. */}
                <div className="lby-card-actions">
                  {g.your_turn ? <TurnBadge mine>Your turn</TurnBadge> : <TurnBadge>Their turn</TurnBadge>}
                  <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction>
                </div>
              </div>
            ))}
            </div>
            {activeMine.length === 0 && <div className="lby-empty">No games in progress.</div>}
          </div>
          <div className="dm-section lby-col-history">
            <LobbySectionHd title="History" note={`${history.length} finished`} />
            <div className="lby-list">
            {historyShown.map((g) => {
              const line = historyScores(g);
              // Dominion breaks a VP tie on fewer turns taken, so a shared win
              // is rare but real — CoC's history has the same three states.
              const tie = g.you_won && (g.winners || []).length > 1;
              return (
                <div key={g.id} className="lby-card lby-card-hist">
                  <div className="lby-card-info">
                    <div className="lby-card-title">
                      <span className={"hist-result " + (tie ? "tie" : g.you_won ? "won" : "lost")}>
                        {tie ? "Tie" : g.you_won ? "Won" : "Lost"}
                      </span>
                      <span className="hist-scores"> vs {(g.opponents || []).join(", ")}
                        {line ? <> <span className="hist-score-num">{line}</span></> : null}
                      </span>
                    </div>
                    <div className="lby-card-meta">{timeAgo(g.updated_at)}</div>
                  </div>
                  <div className="lby-card-actions">
                    <LobbyAction kind="secondary" onClick={() => enterReview(g.id)}>
                      {reviewLoadingId === g.id ? "Loading…" : "Review"}
                    </LobbyAction>
                  </div>
                </div>
              );
            })}
            {historyMore}
            </div>
            {history.length === 0 && <div className="lby-empty">No finished games yet.</div>}
          </div>
        </div>
        </div></div>
        {showRules && renderRules()}
        {toast && <div className="dm-toast">{toast}</div>}
      </div>
    );
  }

  if (screen === "waiting") {
    const count = Object.keys(names).length;
    const cap = roomData?.max_players || 4;
    const isHost = roomData?.host === myId;
    return (
      <div className="app dm" style={{ "--lby-accent": GAME_ACCENTS.dontminion }}>
        <style>{dmStyles}</style>
        <LobbyHeader onBack={leaveToLobby} backLabel="← Leave" title="Dontminion" user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : "Guest"} />
        <div className="dm-wait">
          <h2>Room {roomId}</h2>
          <p className="dm-wait-note">Share this code — friends join with it from the lobby.</p>
          <p className="dm-wait-note">{(roomData?.expansions || []).map((e) => EXPANSIONS.find((x) => x.id === e)?.name || e).join(" + ")}</p>
          <div className="dm-wait-players">
            Players ({count}/{cap})
            <ul>
              {Object.entries(names).map(([p, n]) => (
                <li key={p}>{n}{p === roomData?.host ? " ♛" : ""}{p === myId ? " (you)" : ""}</li>
              ))}
            </ul>
          </div>
          {isHost
            ? <button className="btn btn-gold btn-full" disabled={count < 2}
                onClick={() => send({ action: "start" })}>
                {count < 2 ? "Waiting for players…" : `Deal & Start (${count} players)`}
              </button>
            : <div className="lby-loading"><span className="lby-spinner" /> Waiting for the host to start…</div>}
        </div>
        {toast && <div className="dm-toast">{toast}</div>}
      </div>
    );
  }

  if (!game) {
    return (
      <div className="app dm" style={{ "--lby-accent": GAME_ACCENTS.dontminion }}>
        <style>{dmStyles}</style>
        <div className="lby-loading dm-center"><span className="lby-spinner" /> Loading game…</div>
      </div>
    );
  }

  // ── game screen ──
  return (
    <div className="app dm dm-gamescreen" style={{ "--lby-accent": GAME_ACCENTS.dontminion }}>
      <style>{dmStyles}</style>
      {/* Title bar only — the game's NAME, centred, like every other game on the
          site. Whose turn it is and which phase you're in are already carried by
          the seat boxes (acting badge) and the resource bar's hint. The two side
          slots are equal-flex so the title centres on the PAGE, not merely in
          the gap left over by the menu. */}
      <div className="dm-top">
        <div className="dm-top-side">
          {/* Same wording, same order, same icons as every other game: Return /
              rules / abandon. This was the odd one out — "Back to lobby" with
              no icons and Rules below Abandon. */}
          <GameMenu onLeave={leaveToLobby} onRules={() => setShowRules(true)}
            onAbandon={over ? null : () => setConfirmAbandon(true)} />
        </div>
        <h1 className="dm-title">Dontminion</h1>
        <div className="dm-top-side dm-top-right">
          {reconnecting && !connected && <span className="dm-reconn">reconnecting…</span>}
        </div>
      </div>

      <div className="dm-main">
        <div className="dm-side">
          <button className="btn btn-ghost dm-kingdom-btn" onClick={() => setShowKingdom(true)}>🃏 Kingdom</button>
          <div className="dm-pboxes">{seatOrder.map(renderPlayerBox)}</div>
          <div className="dm-trash" onClick={() => setShowTrash((s) => !s)}>
            Trash ({(game.trash || []).length}) {showTrash ? "▾" : "▸"}
            {showTrash && (
              <div className="dm-trash-list">
                {(game.trash || []).length ? game.trash.join(", ") : "empty"}
              </div>
            )}
          </div>
          {/* the gesture handlers are what tell a reader's scroll apart from
              the browser's own — see onLogScroll */}
          <div className="dm-log" ref={logRef} onScroll={onLogScroll}
               onWheel={onLogGesture} onPointerDown={onLogGesture}
               onTouchMove={onLogGesture}>
            {/* CHRONOLOGICAL: oldest at the top, newest appended at the bottom,
                and the view auto-scrolls to keep the newest line visible. Reads
                the way the turn actually happened, which matters here because
                sub-effects INDENT under the play that caused them — newest-first
                showed every effect above its own cause. Capped to the most
                recent 200 lines. */}
            {buildLogLines(game.log || [], names).slice(-200).map((l) => (
              <div key={l.key}
                className={"dm-log-line" + (l.d ? ` dm-log-d${l.d}` : "") + (l.turn ? " dm-log-turn" : "")}>
                {l.text}
              </div>
            ))}
          </div>
        </div>

        <div className="dm-center-col">
          {focusOpp && renderOppPlay(focusOpp)}
          {renderPrompt()}
          <div className="dm-supply">
            {/* Landscapes sit ABOVE the Supply, and the row renders NOTHING at
                all when the game has none — no ghost row and no layout shift,
                which is every game until Adventures (ph. 7) ships one. */}
            {boardLandscapes.length > 0 && (
              <div className="dm-lscape-row">{boardLandscapes.map((n, i) => renderLandscape(n, i))}</div>
            )}
            <div className="dm-supply-row dm-basics">{basicsRowFor(game.supply).map(renderPile)}</div>
            <div className="dm-supply-row dm-kingdom">{kingdomByCost.map(renderPile)}</div>
            {asidePiles.length > 0 && (
              <div className="dm-aside-piles">
                <div className="dm-aside-label">Set aside — not in the Supply</div>
                <div className="dm-supply-row">{asidePiles.map(renderPile)}</div>
              </div>
            )}
          </div>
          <div className="dm-me">
            {!over && game.turn === myId && (
              <div className="dm-resbar">
                {/* Even the three vanilla counters answer the gesture: "unspent
                    money does not carry over" is the rule that costs a new
                    player their first game, and it is written nowhere. */}
                <DmChip onInfo={() => showThing("actions")}>Actions <b><Pop n={game.actions} /></b></DmChip>
                <DmChip onInfo={() => showThing("buys")}>Buys <b><Pop n={game.buys} /></b></DmChip>
                <DmChip onInfo={() => showThing("coins")}>Money <b>$<Pop n={game.coins} /></b></DmChip>
                {/* Coffers: a SPENDABLE counter, not a resource that ticks
                    down on its own. Spendable "at any time during your turn",
                    so the button lives here rather than in the buy row — and
                    it is hidden while a decision is open, which is exactly
                    when the server refuses the move. */}
                {myCoffers > 0 && (
                  <DmChip className="dm-counter" onInfo={() => showThing("coffers")}>Coffers <b><Pop n={myCoffers} /></b>
                    {canSpend && (
                      <button className="btn btn-gold btn-sm dm-spend"
                        title="Spend 1 Coffers for +$1"
                        onClick={() => mv({ type: "spend", what: "coffers", n: 1 })}>
                        spend $1
                      </button>
                    )}
                    {canSpend && myCoffers > 1 && (
                      <button className="btn btn-outline btn-sm dm-spend"
                        title={`Spend all ${myCoffers} Coffers`}
                        onClick={() => mv({ type: "spend", what: "coffers", n: myCoffers })}>
                        all
                      </button>
                    )}
                  </DmChip>
                )}
                {/* Villagers: Coffers' twin one column over — spent for +1
                    Action each, and only in your Action phase. The buttons
                    key on the SERVER's spendable count, so the phase rule is
                    never duplicated here. */}
                {myVillagers > 0 && (
                  <DmChip className="dm-counter" title="Villagers — spend in your Action phase for +1 Action each"
                    onInfo={() => showThing("villagers")}>
                    Villagers <b><Pop n={myVillagers} /></b>
                    {spendableVillagers > 0 && (
                      <button className="btn btn-gold btn-sm dm-spend"
                        title="Spend 1 Villager for +1 Action"
                        onClick={() => mv({ type: "spend", what: "villagers", n: 1 })}>
                        +1 Action
                      </button>
                    )}
                    {spendableVillagers > 1 && (
                      <button className="btn btn-outline btn-sm dm-spend"
                        title={`Spend all ${spendableVillagers} Villagers`}
                        onClick={() => mv({ type: "spend", what: "villagers", n: spendableVillagers })}>
                        all
                      </button>
                    )}
                  </DmChip>
                )}
                {/* Debt: not a resource you spend on cards — it is a debt that
                    blocks every buy until it's gone. Pay off any amount up to
                    what you can afford, at any time in your turn, for no Buy. */}
                {myDebt > 0 && (
                  <DmChip className="dm-counter dm-debt" title="Debt — you can't buy anything until this is paid off ($1 per token)"
                    onInfo={() => showThing("debt")}>
                    Debt <b><Pop n={myDebt} /></b>
                    {payableDebt > 0 && (
                      <button className="btn btn-gold btn-sm dm-spend"
                        title={`Pay off ${payableDebt} Debt for $${payableDebt}`}
                        onClick={() => mv({ type: "spend", what: "debt", n: payableDebt })}>
                        pay ${payableDebt}
                      </button>
                    )}
                    {payableDebt > 1 && (
                      <button className="btn btn-outline btn-sm dm-spend"
                        title="Pay off 1 Debt for $1"
                        onClick={() => mv({ type: "spend", what: "debt", n: 1 })}>
                        one
                      </button>
                    )}
                  </DmChip>
                )}
                {(game.potions ?? 0) > 0 && (
                  <DmChip title="Potions — spent on cards with a Potion in their cost"
                    onInfo={() => showThing("potions")}>
                    Potions <b><Pop n={game.potions} /></b></DmChip>
                )}
                {bridges > 0 && <span>Cards cost <b>−<Pop n={bridges} /></b></span>}
                {hasModalPrompt && promptMin
                  ? <button className="btn btn-gold btn-sm dm-reshint-btn"
                      onClick={() => setPromptMin(false)}><FitLabel>{promptCardName}: make your choice ▸</FitLabel></button>
                  : resHint ? <span className="dm-reshint">{resHint}</span> : null}
              </div>
            )}
            {!over && game.turn !== myId && hasModalPrompt && promptMin && (
              <div className="dm-resbar">
                <button className="btn btn-gold btn-sm dm-reshint-btn"
                  onClick={() => setPromptMin(false)}><FitLabel>{promptCardName}: make your choice ▸</FitLabel></button>
              </div>
            )}
            <div className="dm-inplay">
              {(mySeat?.duration_view || []).flatMap((e, i) => [
                <div key={"d" + i} className="dm-durwrap" title="Duration — stays in play">
                  <DmCardFace name={e.card} card={cards[e.card]} small onInfo={() => showCard(e.card)} />
                </div>,
                ...(e.riders || []).map((r, j) => (
                  <div key={"d" + i + "r" + j} className="dm-durwrap">
                    <DmCardFace name={r} card={cards[r]} small onInfo={() => showCard(r)} />
                  </div>
                )),
              ])}
              {(mySeat?.in_play || []).map((c, i) => (
                <DmCardFace key={inPlayKeys[i]} name={c} card={cards[c]} small onInfo={() => showCard(c)} />
              ))}
              {(mySeat?.in_play || []).length === 0 && (mySeat?.duration_view || []).length === 0
                && <span className="dm-zone-hint">in play</span>}
              {(mySeat?.island || []).length > 0 && (
                <DmMatChip emoji="🏝" count={mySeat.island.length} label="Island mat"
                  cards={mySeat.island} onView={setMatView} onInfo={() => showThing("mat:island")} />
              )}
              {(mySeat?.village_count || 0) > 0 && (
                <DmMatChip emoji="🏕" count={mySeat.village_count} label="Native Village mat"
                  cards={mySeat.village_mat} onView={setMatView} onInfo={() => showThing("mat:village")} />
              )}
              {(mySeat?.dur_aside_count || 0) > 0 && (
                <DmMatChip emoji="⏳" count={mySeat.dur_aside_count} label="Set aside"
                  cards={mySeat.dur_aside} onView={setMatView} onInfo={() => showThing("mat:aside")} />
              )}
              {/* The Tavern mat is PUBLIC — the cards lie face up — so it is
                  the same chip for you and for an opponent, contents and all.
                  There is no Call button: every call in the game is a timed
                  WINDOW, so it arrives as an ordinary decision prompt. */}
              {(mySeat?.tavern || []).length > 0 && (
                <DmMatChip emoji="🍺" count={mySeat.tavern.length} label="Tavern mat"
                  cards={mySeat.tavern} onView={setMatView} onInfo={() => showThing("mat:tavern")} />
              )}
              {/* The Exile mat, same chip for you and for an opponent: it is
                  face up and it scores. There is no "discard from Exile"
                  button — the mat's own ability is a timed window on a gain,
                  so it arrives as an ordinary decision prompt. */}
              {(mySeat?.exile || []).length > 0 && (
                <DmMatChip emoji="🚪" count={mySeat.exile.length} label="Exile mat"
                  cards={mySeat.exile} onView={setMatView} />
              )}
            </div>
            <div className="dm-handrow">
              <div className="dm-mypiles">
                <DmPile kind="deck" label="deck" count={mySeat?.deck_count ?? 0} />
                <DmPile kind="discard" label="discard" count={mySeat?.discard_view?.count ?? 0}
                  top={mySeat?.discard_view?.top} card={cards[mySeat?.discard_view?.top]}
                  onInfo={() => showCard(mySeat?.discard_view?.top)} />
              </div>
              <div className="dm-pile-slot dm-myhand">
                <div className="dm-hand">
                  {(mySeat?.hand || []).map((c, i) => {
                    const t = typesFor(c);
                    const playable = !iAmActor && ((inAction && t.includes("action") && game.actions > 0)
                      || (inBuy && t.includes("treasure") && !bought));
                    return <DmCardFace key={handKeys[i]} name={c} card={cards[c]}
                      highlight={playable} disabled={!playable && !over}
                      onClick={() => handClick(c)} onInfo={() => showCard(c)} />;
                  })}
                  {(mySeat?.hand || []).length === 0 && <span className="dm-zone-hint">hand empty</span>}
                </div>
                <span className="dm-pile-count">hand <Pop n={(mySeat?.hand || []).length} /></span>
              </div>
              <div className="dm-turnbtns">
                {!over && (
                  <button className="btn btn-outline dm-undo" disabled={!canUndo}
                    title={canUndo
                      ? "Take back your last action — press again to keep stepping back (until the turn started or new information was revealed)"
                      : "Nothing to undo — undo unlocks after a move of yours that revealed no new information"}
                    onClick={() => canUndo && mv({ type: "undo_turn" })}>↩ Undo{(game.undo_depth || 0) > 1 ? ` (${game.undo_depth})` : ""}</button>
                )}
                {inBuy && handTreasures && !bought && (
                  <button className="btn btn-gold" onClick={() => mv({ type: "play_all_treasures" })}>Play all treasures</button>
                )}
                {(inAction || inBuy) && (
                  <button className="btn btn-outline" onClick={() => mv({ type: "end_phase" })}>
                    {inAction ? "To buy phase →" : "End turn"}
                  </button>
                )}
              </div>
            </div>
          </div>
        </div>
      </div>

      {confirmAbandon && (
        <div className="dm-backdrop" onClick={() => setConfirmAbandon(false)}>
          <div className="dm-modal" onClick={(e) => e.stopPropagation()}>
            <h2>Abandon this game?</h2>
            <div className="dm-prompt-actions">
              <button className="btn btn-danger" onClick={abandonGame}>Abandon</button>
              <button className="btn btn-outline" onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            </div>
          </div>
        </div>
      )}
      {showKingdom && (
        <div className="dm-backdrop" onClick={() => setShowKingdom(false)}>
          <div className="dm-modal dm-kingdom-modal" onClick={(e) => e.stopPropagation()}>
            <h2>This game's Kingdom</h2>
            <p className="dm-wait-note">{(roomData?.expansions || []).map((e) => EXPANSIONS.find((x) => x.id === e)?.name || e).join(" + ")}</p>
            <div className="dm-kgrid">
              {kingdomByCost.map((n) => (
                <div key={n} className="dm-pile-slot">
                  <DmCardFace name={pileFace(n)} card={cards[pileFace(n)]}
                    onInfo={() => showCard(pileFace(n))} />
                  <span className="dm-pile-count">{pileLeft(n)} left</span>
                  {game.bane === n && <span className="dm-bane" title="Young Witch's Bane">B</span>}
                </div>
              ))}
            </div>
            {/* Everything below is dealt with the Kingdom but is NOT a Supply
                pile, so nothing above shows it: the landscapes (an Event scrolls
                away above the Supply; a Landmark is never bought at all) and the
                Artifacts (which live only as a badge in front of a holder, so an
                untaken one appears nowhere on the board). Each one opens its own
                description, same as a card. */}
            {landscapeGroups.map(([kind, list]) => (
              <div key={kind}>
                <h3>{kindPlural(kind)}</h3>
                <p className="dm-kg-note">{LANDSCAPE_BLURB[kind] || ""}</p>
                <div className="dm-kgrid dm-kgrid-wide">
                  {list.map((n, i) => renderLandscape(n, i, true))}
                </div>
              </div>
            ))}
            {gameArtifacts.length > 0 && (
              <>
                <h3>Artifacts</h3>
                <p className="dm-kg-note">{THINGS.artifact.text.split("\n\n")[0]}</p>
                <div className="dm-kgrid dm-kgrid-wide">
                  {gameArtifacts.map((a) => (
                    <button key={a} type="button" className="dm-lscape dm-ls-artifact"
                      onClick={() => showArtifact(a)}>
                      <span className="dm-ls-name">🏳 {a}</span>
                      <span className="dm-ls-text">{catalog?.artifacts?.[a]?.text || ""}</span>
                      <span className="dm-ls-foot">
                        <span className="dm-ls-kind">artifact</span>
                        <span className="dm-ls-holder">
                          {game.artifacts[a]
                            ? (game.artifacts[a] === myId ? "you have it"
                               : `${names[game.artifacts[a]] || game.artifacts[a]} has it`)
                            : "not taken yet"}
                        </span>
                      </span>
                    </button>
                  ))}
                </div>
              </>
            )}
            <h3>Basic supply</h3>
            <div className="dm-kgrid">
              {basicsRowFor(game.supply).map((n) => (
                <div key={n} className="dm-pile-slot">
                  <DmCardFace name={n} card={cards[n]} onInfo={() => showCard(n)} />
                  <span className="dm-pile-count">{pileLeft(n)} left</span>
                </div>
              ))}
            </div>
            {asidePiles.length > 0 && (
              <>
                <h3>Set aside — not in the Supply</h3>
                <div className="dm-kgrid">
                  {asidePiles.map((n) => (
                    <div key={n} className="dm-pile-slot">
                      <DmCardFace name={pileFace(n)} card={cards[pileFace(n)]}
                        onInfo={() => showCard(pileFace(n))} />
                      <span className="dm-pile-count">{pileLeft(n)} left</span>
                    </div>
                  ))}
                </div>
              </>
            )}
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setShowKingdom(false)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {renderPromptModal()}
      {matView && (
        <div className="dm-backdrop" onClick={() => setMatView(null)}>
          <div className="dm-modal dm-kingdom-modal dm-matview" onClick={(e) => e.stopPropagation()}>
            <h2>{matView.label}</h2>
            <p className="dm-wait-note">{matView.cards.length} card{matView.cards.length === 1 ? "" : "s"}</p>
            <div className="dm-kgrid">
              {matView.cards.map((n, i) => (
                <div key={n + "#" + i} className="dm-pile-slot">
                  <DmCardFace name={n} card={cards[n]} onInfo={() => showCard(n)} />
                </div>
              ))}
            </div>
            <div className="dm-prompt-actions">
              <button className="btn btn-gold" onClick={() => setMatView(null)}>Close</button>
            </div>
          </div>
        </div>
      )}
      {renderInfoModal()}
      {showRules && renderRules()}
      {renderGameOver()}
      {toast && <div className="dm-toast">{toast}</div>}
    </div>
  );
}
