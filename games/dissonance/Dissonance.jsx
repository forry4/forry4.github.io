import { fetchGameHistory } from "../../shared/lobbyHistory.js";
import { Fragment, useState, useEffect, useLayoutEffect, useRef, useCallback, useMemo } from "react";
import { baseCss } from "../../shared/theme.js";
import {
  lobbyCss, LobbyHeader, LobbySectionHd, LobbyEmpty, TurnBadge, LobbyMatchup, LobbyLoading,
  LobbyTabs, GameMenu, gameMenuCss, readLobbyCache, writeLobbyCache, useFinishedGameSync, dropLobbyGame,
  createModalCss, CreateModal, CmRow, CmSeg, LobbyCreateRow, lobbyCreateRowCss,
  RulesModal, rulesModalCss,
  useProgressiveList, notWaiting, LobbyAction, useLastDifficulty, LobbyHero,
  SCORECARD_GLYPH, LobbyUser, useListFade, LobbyBotTier,
  WaitingRoom, waitingRoomCss,
} from "../../shared/lobby.jsx";
import DissonanceRules from "./rules.jsx";
import DissonanceScorecard from "./scorecard.jsx";
// OFFLINE VS-AI: the local driver (wasm referee + IndexedDB saves). The
// component below cannot tell which referee it is talking to -- both hand it
// `engine.view_for`'s payload and both take the same move objects -- so the
// wiring is a `send` that routes to the driver and a bot loop that arms
// `ai_search` the way the server does. See offline.js.
import { dissonanceOfflineRoomData, applyOfflineDissonanceMove,
  runDissonanceBotLoop, loadOfflineDissonanceGame,
  abandonOfflineDissonanceGame } from "./offline.js";
import { contractPrices } from "./pricing.js";
import { parsePath, buildPath, pushPath, subscribe } from "../../shared/router.js";

// CSS lives in the sibling .css file, imported ?inline as a STRING and injected
// by this component's own <style> while mounted. Never a JS template literal —
// one stray backtick there reparses the rest of the file and blanks the page.
import _cssText from "./Dissonance.css?inline";
// The bid pad and the paper scorecard are their own sheets because the CARD
// mounts outside this component (the offline hub opens it with no room and no
// board). Composed here too, appended last — see bidpad.css for why that is
// safe rather than lucky.
import _bidpadCss from "./bidpad.css?inline";
import _scorecardCss from "./scorecard.css?inline";

const WS_RAW = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const OT_WS = WS_RAW.replace(/\/ws$/, "/dissonance/ws");
const OT_HTTP = WS_RAW.replace(/^ws/, "http").replace(/\/ws$/, "/dissonance");

const styles = baseCss + lobbyCss + gameMenuCss + createModalCss + lobbyCreateRowCss
  + rulesModalCss + waitingRoomCss + _cssText + _bidpadCss + _scorecardCss;

const SUIT_GLYPH = ["♣", "♦", "♥", "♠"];   // c d h s
// 32-card deck: 7 low, ace high, eight ranks per suit — ids 0..31, `suit*8 +
// rank`. DUMMY mode deals a FORTY-card deck (three seats of thirteen do not
// come out of 32): the same 32 plus a 5 and a 6 in each suit, bolted on as ids
// 32..39, and the full deck's 2/3/4 at 40..51, so no existing card id moves.
// See `engine.rank` for the whole argument; the consequence here is that
// `rankOf` returns a STRENGTH index 0..12 (0 = the 2) rather than the id's low
// bits, so this list is in strength order and comparisons stay a plain `>`.
//
// THE BLOCKS MUST MATCH `engine.suit`/`engine.rank` EXACTLY. This is a second
// copy of the card layout and there is no test that compares the two directly
// -- what catches a drift is `screens.mjs` asserting a low card renders as
// ITSELF, because a client decoding ids on the wrong block draws a real card
// with the wrong rank rather than throwing.
const RANKS = ["2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K", "A"];
const NCARD = 32;        // the base deck: ids 0..31, ranks 7..A
const NCARD_WIDE = 40;   // + the 5 and 6 at ids 32..39
const NEXTRA_WIDE = 2;   // ranks per suit in that block
const NEXTRA_FULL = 3;   // + the 2, 3 and 4 at ids 40..51
const BASE_OFFSET = 5;   // strength of the 7
const WIDE_OFFSET = 3;   // strength of the 5
// Denominations are RANKED left to right: a same-level overtake must name one
// further right. Null is the top rung and exists only at level 6.
// Indexed by DENOMINATION, so index 5 is the legacy Null marker and Grand
// sits at 6 rather than beside no-trump. A dense array is what the wire
// hands us; the gap is the point, not an oversight.
const DENOM_LABEL = ["♣", "♦", "♥", "♠", "NT", "Null", "Grand"];
const DENOM_NAME = ["Clubs", "Diamonds", "Hearts", "Spades", "No-trump",
  "Null — win no +2 trick", "Grand (the four 10s are trump)"];
// THE SUIT SYMBOL IS COLOURED, AND NOTHING ELSE IS (2026-08-09). ♦ and ♥ are
// red, ♣ and ♠ take the surrounding ink -- the playing-card convention, scoped
// to the GLYPH rather than to the whole contract. The level beside it stays
// the colour of the text it sits in, so "3♥" reads as a number and a red heart
// rather than as a red contract.
//
// Two things this gets right that the old whole-label tint did not. It went on
// only SOME of the places a contract appears (the chip, the scorecard, the
// pickers; never the bid log, the result panel or the History row), so a
// colour that meant nothing looked like it meant something -- `Den` is now the
// single renderer, so every mention is coloured the same way by construction.
// And it dyed the LEVEL too, which put a red "3" one column from a Score that
// is red when you lost the round.
//
// "Black" is the surrounding ink, not #000: this board is #0f0e0c, so a
// literal black suit would be invisible. On the one LIGHT surface a suit ever
// lands on -- a selected picker button, filled with the accent -- the CSS
// swaps in the true card red against that button's near-black ink.
const NOTRUMP = 4;

/** A denomination label — THE ONE PLACE one is written out.
 *
 *  Every mention of a contract goes through this, which is what makes the
 *  suit colour a rule rather than a habit: the previous tint was applied by
 *  hand at five sites and forgotten at six others.
 *
 *  Only the four real suits are SYMBOLS. "NT", "Null" and "Grand" are words
 *  and take the surrounding ink, exactly as ♣ and ♠ do — a black suit is not
 *  given a colour of its own, it simply is not red, which is also what keeps
 *  it legible in dim text (the scorecard) and on the accent (a selected
 *  picker button) without a rule per context. */
function Den({ d }) {
  const label = DENOM_LABEL[d] || "";
  if (!label) return null;
  if (d > 3) return <>{label}</>;   // NT / Null / Grand are words, not suits
  return <span className={d === 1 || d === 2 ? "dis-suit-r" : "dis-suit-b"}>
    {label}</span>;
}

/** A card named in TEXT — the talon reveal, the swap buttons — with the same
 *  suit colouring `Den` gives a contract. A card FACE is a different renderer
 *  (`Card`, which paints the whole face) and keeps its own deeper red against
 *  the light card stock; this one is a glyph inside a sentence. */
function CardName({ c }) {
  if (c === null || c === undefined) return null;
  return <>{RANKS[rankOf(c)]}<span className={isRed(c) ? "dis-suit-r" : "dis-suit-b"}>
    {SUIT_GLYPH[suitOf(c)]}</span></>;
}

// Null is a CONSOLATION, not a contract: take no +2 trick as declarer and you
// score this instead of being set, whatever you actually declared. There is no
// denomination and no level to render -- `NULL_DENOM` survives only so a game
// SAVED while Null was still biddable still reads back.
const NULL_DENOM = 5;
const NULL_MAKE = 20;

// How long a completed trick stays face up before it moves to the Last trick
// panel. Long enough to read two cards, short enough not to stall the bot,
// whose own floor is 450ms — so its next lead lands while this is still up and
// simply waits its turn.
/** Used only until `/catalog` answers; the server's value is authoritative. */
const SHORT_PENALTY_FALLBACK = 5;

const TRICK_HOLD_MS = 700;

const BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, blunders often" },
  { id: "normal", name: "Normal", desc: "Knows which tricks it wants" },
  // The ladder moved up a rung on 2026-08-14: the auction tree was Expert's
  // defining feature and is now Hard's, and Expert is the tree with an opponent
  // model that does not assume it can see your cards.
  { id: "hard", name: "Hard", desc: "Solves the hand exactly and searches the auction, in your browser" },
  { id: "expert", name: "Expert", desc: "Hard, and reads the bidding without assuming it can see your hand" },
];
const BOT_TIER_IDS = BOT_TIERS.map((t) => t.id);   // what a remembered tier is validated against
// id -> the words a player sees, off the same list the picker renders — what
// `LobbyBotTier` prints on the Active and History rows.
const BOT_TIER_NAMES = Object.fromEntries(BOT_TIERS.map((t) => [t.id, t.name]));

// The Hard tier's card play is searched HERE, on the player's CPU. It is an
// exact double-dummy solve per sampled deal — ~70ms for one deal at trick 1 —
// which is unthinkable on Render's free tier and unremarkable on a laptop.
// Every failure path (no Worker, no wasm, a search error, a slow phone) is a
// no-op that leaves the server's heuristic bot to play the move.
// Expert is the same client search with one extra block on the armed request:
// its AUCTION decisions carry `auction.search`, which the wasm minimaxes
// instead of pricing. Nothing in this file has to know that — the option list,
// the pooling by index and the move handed back are identical.
const CLIENT_AI_TIERS = ["hard", "expert"];
//: A flat floor per move, so the bot's pace does not advertise how fast the
//  player's machine is — and so it never lands inside the completed-trick beat.
const CLIENT_AI_MIN_MS = 600;

// Two auctions over the same card play, picked per room. Skat mode bids a bare
// NUMBER and only names the game after winning — so the ladder cannot be read
// backwards into a denomination. Every number on it (the values list, each
// declaration's base and minimum level) arrives from the server in
// `game.options` / `game.declare`; nothing about the price table is hardcoded
// here, so the two can never disagree about what a bid costs.
const MODES = [
  { id: "classic", label: "Classic", title: "Bid a level and a denomination — the shipped auction" },
  { id: "skat", label: "Skat", title: "Bid a number, then declare the game that satisfies it" },
  { id: "minor", label: "Minor", title: "Even tricks pay only +1 — a harsher, quieter game to 25" },
  { id: "dummy", label: "Dummy", title: "A third hand, face up — the declarer plays it, and it plays second in every trick" },
  { id: "quartet", label: "Quartet", title: "Four hands, two players — you play the hand opposite you too, and keep three cards back" },
];
const MODE_LABEL = { classic: "Classic", skat: "Skat", minor: "Minor", dummy: "Dummy", quartet: "Quartet" };
// Classic and Dummy are public modes. The newer Skat, Minor, and Quartet
// variants remain in the shared rules/catalogue for admin testing, but should
// not appear in public lobbies while they are still being validated.
const ADMIN_ONLY_MODE_IDS = new Set(["skat", "minor", "quartet"]);
const PUBLIC_MODES = MODES.filter((mode) => !ADMIN_ONLY_MODE_IDS.has(mode.id));
//: The dummy's index into the seat arrays. Positions are not seats: 0 and 1
//: are the players, 2 is the hand the declarer also plays.
const DUMMY_POS = 2;
//: QUARTET: how many hands one player commands. Positions 0 and 1 are the
//: players' OWN hands, 2 and 3 the hands opposite them, so a player holds
//: `p` and `p + QUARTET_HANDS` and the side of a position is `pos % 2`.
//: Mirrors `engine.QUARTET_HANDS`.
const QUARTET_HANDS = 2;

/** The announcement stack, spelled out for the result and side panels. */
function multParts(ct) {
  const parts = [];
  if (ct?.hand) parts.push("Hand");
  if (ct?.sharp) parts.push("Sharp");
  if (ct?.open) parts.push("Open");
  return parts;
}

/** The overtrick bonus as the tail of a made contract's arithmetic line.
 *
 *  Empty when nothing was scored past the target, so a contract brought home
 *  exactly reads the way it always did ("3 × 3 = 9 to Alice") rather than
 *  growing a "+ 0". Both modes share it: the chain in front differs, the tail
 *  does not. The numbers are the RESULT ROW's — `over` and the final score are
 *  the engine's own, never recomputed here.
 *
 *  SKAT ONLY since the classic result panel was re-worded (see `ResultMaths`),
 *  which spells its formula out term by term instead and never simplifies.
 */
function overTail(res) {
  if (!res?.over) return "";
  return ` + ${res.over} = ${res.scores[res.declarer]}`;
}

/** THE TWO CURRENCIES, told apart by colour as well as by word.
 *
 *  The round has two numbers that are both "how much", and the panel used the
 *  verb "scored" for both: TRICK POINTS are what you take at the table and what
 *  a contract is measured against, SCORE is what the round pays. So the words
 *  are now fixed — "points" is only ever the trick currency, "score" only ever
 *  the payout — and the formula is colour-keyed to the sentence above it, so
 *  "took 3 extra points" and the `+ 3` it turns into are visibly the same 3.
 *
 *  `lvl` (the contract) is plain, `pts` is the trick-point quantity, `score` is
 *  what lands on the scoreboard. Every number is the RESULT ROW's own — this
 *  colours the arithmetic, it never computes it. */
const Lvl = ({ children }) => <span className="dis-n-lvl">{children}</span>;
const Pts = ({ children }) => <span className="dis-n-pts">{children}</span>;
const Score = ({ children }) => <span className="dis-n-score">{children}</span>;

/** WHAT THE DOUBLE WAS WORTH — the bet's outcome as the difference it made.
 *
 *  The defender doubles, so the line is written from their side: it EARNED
 *  them the extra on a set contract and COST them the extra on a made one.
 *  Both numbers are the engine's (`undoubled` is this same round re-scored
 *  with the bet taken off), so nothing here re-derives the doubling rule.
 *
 *  Doubling scales both ends and its ramp only adds, so it can never flip who
 *  won the round — which is what lets this compare two magnitudes for the
 *  same seat rather than reasoning about signs. */
function DoubleWorth({ res, nameOf }) {
  const got = Math.abs(res.scores[res.made ? res.declarer : 1 - res.declarer]);
  const would = Math.abs(res.undoubled ?? 0);
  const defender = nameOf(1 - res.declarer);
  // A round where the bet changed nothing is possible in principle (a Null
  // is the live case, and it has its own line) -- say so rather than
  // announcing a difference of zero as a result.
  if (!res.undoubled || got === would) {
    return <>Kontra: it made no difference to this round.</>;
  }
  return res.made
    ? <>The Kontra cost {defender} <b>{got - would}</b> — {nameOf(res.declarer)}{" "}
      scored {got} instead of {would}.</>
    : <>The Kontra earned {defender} <b>{got - would}</b> — {got} instead of{" "}
      {would}.</>;
}

/** The classic/minor round's arithmetic, spelled out and never simplified.
 *
 *  Deliberately NOT reduced to an intermediate ("4 × 4 + 10 = 26 + 3 = 29"):
 *  the reader wants to see the contract they bought, the flat stake riding on
 *  it, and the points they took as separate, recognisable terms, so the shape
 *  stays `(N × N + 10) + P = X` — the
 *  "+ 0" of a contract brought home exactly included, because a formula that
 *  changes shape with its values is one the eye has to re-parse every round.
 *
 *  DOUBLING RIDES INSIDE THE TERMS IT ACTUALLY MULTIPLIES, and getting that
 *  wrong was live here: the old line printed `4 × 4 × 2 = 32 + 3 = 38`, which
 *  does not add up, because a Double doubles the overtrick RATE too
 *  (`over_bonus`) and the tail only ever showed the raw points. */
function ResultMaths({ res, nameOf, price }) {
  const lvl = res.level;
  if (res.null) {
    return <div className="dis-maths">
      flat <Score>{res.null_value}</Score> to {nameOf(res.declarer)}
    </div>;
  }
  const dbl = res.doubled ? 2 : 1;
  if (res.made) {
    const rate = res.over_bonus ?? 1;
    // The flat stake, read OFF THE ROW: `make_value` is the whole (doubled)
    // base the engine paid, so the spelled-out terms provably reach the total
    // whatever the stake is priced at — the client never guesses a 10.
    const stake = (res.make_value ?? dbl * lvl * lvl) / dbl - lvl * lvl;
    return <div className="dis-maths">
      (<Lvl>{lvl}</Lvl> × <Lvl>{lvl}</Lvl>{stake ? ` + ${stake}` : ""})
      {res.doubled ? " × 2" : ""} +{" "}
      {rate > 1
        ? <>({rate} × <Pts>{res.over}</Pts>)</>
        : <Pts>{res.over}</Pts>}
      {" = "}<Score>{res.scores[res.declarer]}</Score> to {nameOf(res.declarer)}
    </div>;
  }
  // Set: the set base, then the shortfall charge. Undoubled that is a flat rate
  // times the points missed; a ramped one is spelled out rather than faked as a
  // product. Every number is the ROW's own.
  //
  // THE BASE IS NO LONGER "THE LEVEL, DOUBLED". This line used to print
  // `(N + stake) × 2`, which was three separate claims the game has stopped
  // making: the set base is `SET_LEVEL_RATE × N + stake`, the LEAP the winning
  // bid took rides inside it, and Kontra multiplies those two by different
  // amounts (classic: the stake by 1, the leap by 2). So the terms are priced
  // by `priceContract` and CHECKED against `set_base` before they are shown --
  // if they do not reproduce the base the engine charged (an old round scored
  // under a different price list, or a catalog fetch that never landed), the
  // base is printed whole rather than decomposed into a lie.
  const ramp = res.ramp || 0;
  const flat = res.short_rate ?? 4;
  const s = res.short || 0;
  const total = res.set_base ?? dbl * lvl;
  const p = price ? price(lvl, res.jump || 0, !!res.doubled) : null;
  const parts = p && p.setBase === total ? p : null;
  const base = parts && (parts.setParts.rate > 1 || parts.setParts.flat || parts.leap)
    ? <>({parts.setParts.rate > 1 ? <>{parts.setParts.rate} × </> : null}
      <Lvl>{lvl}</Lvl>
      {parts.setParts.flat ? ` + ${parts.setParts.flat}` : ""}
      {parts.leap ? ` + ${parts.leap}` : ""})</>
    : <Lvl>{total}</Lvl>;
  return <div className="dis-maths">
    {base} + (
    {ramp
      ? Array.from({ length: s }, (_, i) => flat + ramp * (i + 1)).join(" + ")
      : <>{flat} × <Pts>{s}</Pts></>}
    ){" = "}<Score>{res.scores[1 - res.declarer]}</Score> to{" "}
    {nameOf(1 - res.declarer)}
  </div>;
}

/** One row of the Kontra prompt's table: what it pays now, and doubled.
 *
 *  The arrow is DROPPED when the number does not move, which is a fact about
 *  the shipped bet rather than a rendering nicety: classic's set base takes
 *  `DOUBLE_BASE_MULT = 1`, so a jump-free contract's set price is the same
 *  either way and "14 → 14" would read as a typo. */
function KontraRow({ label, now, dbl }) {
  return (
    <div className="dis-scorerow">
      <span>{label}</span>
      <b>{now === dbl ? <span className="dis-kbig">{dbl}</span>
        : <>{now}{" → "}<span className="dis-kbig">{dbl}</span></>}</b>
    </div>
  );
}

const suitOf = (c) => (
  c < NCARD ? Math.floor(c / 8)
    : c < NCARD_WIDE ? Math.floor((c - NCARD) / NEXTRA_WIDE)
      : Math.floor((c - NCARD_WIDE) / NEXTRA_FULL));
const rankOf = (c) => (
  c < NCARD ? (c % 8) + BASE_OFFSET
    : c < NCARD_WIDE ? ((c - NCARD) % NEXTRA_WIDE) + WIDE_OFFSET
      : (c - NCARD_WIDE) % NEXTRA_FULL);
const isRed = (c) => suitOf(c) === 1 || suitOf(c) === 2;
/* SORT A HAND BY SUIT, THEN BY RANK. Card ids stopped being sortable the moment
   the deck grew: the base 32 are `suit * 8 + rank`, so id order IS suit order
   for them -- but the wide deck's 5s and 6s live at 32..39 and the full deck's
   2/3/4 at 40..51, appended so nothing older moved. Sorted by id, a quartet
   hand therefore reads 7..A of every suit, THEN the 5s and 6s of every suit,
   then the 2s, 3s and 4s: four suits interleaved three times over.
   This is a no-op for the 32-card modes (their id order already equals this
   one), so it is applied to every hand rather than gated on the mode. */
const bySuit = (a, b) => suitOf(a) - suitOf(b) || rankOf(a) - rankOf(b);
const sortHand = (cards) => [...(cards || [])].sort(bySuit);
const cardName = (c) => RANKS[rankOf(c)] + SUIT_GLYPH[suitOf(c)];
// Trick NUMBER t (1-based): even ones pay `even` (+2 classic, +1 in minor
// mode — the view ships `even_val`), odd ones cost 1. PARITY MODES ONLY.
const trickValue = (t0, even = 2) => (t0 % 2 === 1 ? even : -1);
// What an even trick pays in this room. Off the VIEW, not the mode string,
// so a future re-pricing needs no client change at all.
const evenVal = (game) => game?.even_val ?? 2;
// CARD SCORING (skat, 2026-08-09): captured cards score — 9/10/J/Q +2,
// 7/8/K/A −1 — and a trick is worth the sum of its two cards. The flag and
// the per-rank table both come off the VIEW (`card_pts` / `card_values`); the
// local table below is the render fallback for the corner chips and mirrors
// `engine.CARD_VALUES` (also served as `catalog.card_values`) — a mismatch
// could mislabel a chip, never score a point.
// `RANKS.length` entries, in `rankOf` order — it is indexed at FULL width by
// `cardWorth` below, so it must stay exactly as long as `RANKS`. The wide
// deck's 5 and 6 are worth ZERO — a genuinely safe discard, and the thing that
// breaks the mod-3 granularity the old all-±(1,2) table gave dummy's contract
// ladder — and the full deck's 2, 3 and 4 are zero for the same reason.
//                    2  3  4  5  6   7   8  9 10  J  Q   K   A
const CARD_VALS = [   0, 0, 0, 0, 0, -1, -1, 2, 2, 2, 2, -1, -1];
const cardPts = (game) => game?.card_pts === true;
// The VIEW's table is sliced to the deck that room deals — eight entries in a
// 32-card room (so a bundle cached from before the wide deck still reads it
// correctly), ten in a dummy room. Take the offset from the LENGTH rather than
// a version field: `RANKS.length - t.length` is 5 for the base deck, 3 for the
// wide one and 0 for the full one, which is exactly how far its first entry
// sits up the ladder. THAT is why a third deck width needed no change here.
const cardVal = (game, c) => {
  const t = game?.card_values || CARD_VALS;
  return t[rankOf(c) - (RANKS.length - t.length)];
};
// The render fallback for a card's corner chip, off the local table — the chip
// is cosmetic (a mismatch mislabels it, never scores a point), and a Card has
// no idea which room it is in.
const cardWorth = (c) => CARD_VALS[rankOf(c)];
// The Null consolation's condition, in this room's own words: no positive
// trick under card scoring, no +even trick under the parities.
/** "1 pt" / "N pts" — the trick-point unit, so a target never reads "1 pts".
 *  Abbreviated because its two callers are tight one-line rows (the contract
 *  chip, which is the phone's only contract line, and the side panel). */
const ptsLabel = (n) => `${n} ${n === 1 ? "pt" : "pts"}`;
const nullCond = (game) =>
  cardPts(game) ? "no positive trick" : `no +${evenVal(game)} trick`;

/** What both seats' points must add up to over a whole round.
 *
 *  This was the literal "Always adds up to +5." — classic's parity and nobody
 *  else's. Minor pays 1 for an even trick, so its pool is −1; skat scores the
 *  CARDS CAPTURED and its pool is a property of the DEAL (which cards sat out),
 *  so there is no constant to state and the note says what it can instead.
 *  Derived from the wire (`tricks`, `even_val`) rather than a per-mode table,
 *  so the next parity mode gets a correct sentence without touching this. */
function poolNote(game) {
  if (cardPts(game)) return "Both totals are the cards you capture.";
  const n = game?.tricks ?? 13;
  const evens = Math.floor(n / 2);        // tricks 2, 4, … pay
  const pool = evens * evenVal(game) - (n - evens);
  // "by the end of the round" is the whole point of the sentence: mid-round the
  // two totals say nothing (they are behind by the tricks not yet played), so
  // without it the line reads as a claim about the numbers directly above it
  // and is simply wrong most of the time you are looking at it.
  return `Always adds up to ${pool > 0 ? "+" : ""}${pool} by the end of the round.`;
}

/** Does `follow` beat `led`? A mirror of `engine.beats` — kept in step with it
 *  by hand, like `trickValue` above. Only used to mark who TOOK the previous
 *  trick, so a drift here mislabels a badge and cannot affect play: every move
 *  is validated server-side and the points come off the wire. */
const beats = (led, follow, trump) => {
  const ls = suitOf(led), fs = suitOf(follow);
  if (fs === ls) return rankOf(follow) > rankOf(led);
  if (trump < NOTRUMP) return fs === trump && ls !== trump;
  return false;
};

/** The two cards of the last COMPLETED trick, with who played each and who took
 *  it. `history` is [seat, card, source] in play order, two entries per trick,
 *  so a trailing odd entry is the card currently face up on the table. */
/** EVERY completed trick, oldest first: who played what, who took it, and what
 *  it was worth. The Last-trick panel and the round's trick history are the
 *  same question asked at two lengths, so they share one derivation -- a
 *  second copy of the winner fold is exactly where the two would drift. */
function trickList(game) {
  const h = game.history || [];
  // HOW MANY CARDS TO A TRICK -- two normally, three with a dummy, FOUR in
  // quartet. Genuinely off the wire now: `piles` carries one entry per
  // POSITION in every mode, so its length is the hand count and therefore the
  // trick width, with no mode test at all.
  //
  // The old form was `game.dummy ? 3 : 2` under a comment claiming it came off
  // the wire, and quartet is what proved it did not. Slicing a four-card
  // history into pairs silently produced half-tricks: the completed-trick hold
  // showed two of the four cards, the Last trick panel was wrong, and every
  // trick's parity value was computed for the wrong trick NUMBER -- all of it
  // rendering perfectly, which is why `screens.mjs` had to catch it rather
  // than anything throwing.
  const w = game.piles?.length || (game.dummy ? 3 : 2);
  const done = Math.floor(h.length / w);
  const out = [];
  for (let n = 1; n <= done; n++) {
    const plays = h.slice(w * (n - 1), w * n);
    // The winner, folded exactly as the engine folds it: carry the best card
    // forward and ask whether the next one beats it.
    let winner = plays[0];
    for (const p of plays.slice(1)) {
      if (beats(winner[1], p[1], game.trump)) winner = p;
    }
    // Trick index `n - 1` is 0-based, matching `trickValue`. Under card
    // scoring the trick is worth the CARDS in it, whichever number it was.
    const value = cardPts(game)
      ? plays.reduce((t, p) => t + cardVal(game, p[1]), 0)
      : trickValue(n - 1, evenVal(game));
    out.push({ plays, winner: winner[0], value, number: n });
  }
  return out;
}

function lastTrick(game) {
  const all = trickList(game);
  return all.length ? all[all.length - 1] : null;
}

/* WHERE THIS SEAT PLAYS IN THE TRICK, 1..4 (quartet only; `null` everywhere
   else renders nothing). Four hands make the order genuinely hard to read --
   two of them are yours and they are not adjacent -- and it CHANGES every
   trick, because the winner leads the next one. A number on each seat is the
   cheapest way to say it, and it beats any amount of prose about who follows
   whom. */
function OrderPip({ n }) {
  if (!n) return null;
  return <span className="dis-qorder" title={`plays ${n} of 4 this trick`}>{n}</span>;
}

function uid() { return Math.random().toString(36).slice(2, 10); }
function roomCode() {
  return Array.from({ length: 6 }, () => "ABCDEFGHIJKLMNOPQRSTUVWXYZ"[Math.floor(Math.random() * 26)]).join("");
}
function timeAgo(ts) {
  if (!ts) return "";
  const s = Math.max(0, Math.floor(Date.now() / 1000 - ts));
  if (s < 60) return "just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

// ─── pieces ─────────────────────────────────────────────────────────────────

// There is deliberately no `dim` prop: every face-up card renders identically,
// playable or not. See the note in the stylesheet.
function Card({ c, onClick, sel, small, ghost }) {
  if (ghost) return <div className={`dis-card ghost${small ? " sm" : ""}`}>?</div>;
  if (c === null || c === undefined) return <div className="dis-card back" />;
  const cls = `dis-card ${isRed(c) ? "red" : "black"}${onClick ? " play" : ""}`
    + `${sel ? " sel" : ""}${small ? " sm" : ""}`;
  return (
    /* NO `title`. A native tooltip on every card meant hovering your own hand
       popped "King of Spades" over the board a half-second later — noise on a
       card whose rank and suit are already the two biggest things on it. The
       name stays available to assistive tech as an `aria-label`, which no
       browser renders as a tooltip. */
    <div className={cls} onClick={onClick} aria-label={cardName(c)}>
      {/* A large ghosted centre pip, painted FIRST so the index and the
          worth chip draw over it. Pure dressing — the corner index is still
          the identity (it is what a pile's offset keeps visible). */}
      <span className="dis-center" aria-hidden="true">{SUIT_GLYPH[suitOf(c)]}</span>
      {/* The index sits in the TOP-RIGHT corner, which is what lets a pile
          reveal its buried card by offsetting it up and to the right — the
          corner alone identifies the card, so the hint labels underneath the
          piles ("1 hidden", "over 7♥") are no longer needed. */}
      <span className="dis-ix">
        <span className="dis-r">{RANKS[rankOf(c)]}</span>
        <span className="dis-s">{SUIT_GLYPH[suitOf(c)]}</span>
      </span>
      {/* The mirrored index, bottom-left and rotated — a real card's second
          corner, so a face reads composed (and legible upside-down) instead
          of lopsided. The worth chip keeps the bottom-RIGHT corner. */}
      <span className="dis-ix dis-ix-b" aria-hidden="true">
        <span className="dis-r">{RANKS[rankOf(c)]}</span>
        <span className="dis-s">{SUIT_GLYPH[suitOf(c)]}</span>
      </span>
      {/* The card's WORTH, bottom-right, rendered on every card and shown by
          CSS only inside `.dis-cardpts` (a card-scored skat room). Always in
          the markup so the board class alone decides — a Card has no idea
          which room it is in, and threading the game through every call site
          for a cosmetic chip is how props rot. */}
      <span className={`dis-pts ${cardWorth(c) > 0 ? "pos"
        : cardWorth(c) < 0 ? "neg" : "nil"}`}>
        {cardWorth(c) > 0 ? `+${cardWorth(c)}` : cardWorth(c)}
      </span>
    </div>
  );
}

function Pile({ pile, onPlay }) {
  if (!pile || pile.n === 0) {
    return (
      <div className="dis-pile">
        <div className="dis-pilewrap"><div className="dis-card ghost">–</div></div>
      </div>
    );
  }
  const twoLeft = pile.n === 2;
  const under = pile.under;
  const knownUnder = under !== null && under !== undefined;
  return (
    <div className="dis-pile">
      <div className="dis-pilewrap">
        {/* The buried card, offset up and right so its top-right index clears
            the card covering it. That IS the label: a face shows which card is
            coming (the middle pile, dealt face up), a back shows only that
            something is there — which is exactly what the outer piles hide,
            from their owner too. A one-card pile has nothing behind it. */}
        {twoLeft && (
          <div className="dis-buried" aria-label={knownUnder ? cardName(under) : "face down"}>
            <Card c={knownUnder ? under : null} />
          </div>
        )}
        <Card c={pile.top} onClick={onPlay} />
      </div>
    </div>
  );
}

/** How the shortfall was charged, as the reader would add it up.
 *
 *  Undoubled it is a flat rate and multiplication is the honest shorthand
 *  ("4 x 3"). Doubled it RAMPS -- 5, then 6, then 7 -- and a product would be a
 *  lie, so the terms are spelled out. `ramp` is absent on a result row written
 *  before the Double existed, which reads as the flat case, correctly. */
function shortTail(res) {
  const s = res.short || 0;
  const ramp = res.ramp || 0;
  const flat = res.short_rate ?? 4;
  if (!ramp) return `${flat} × ${s}`;
  return Array.from({ length: s }, (_, i) => flat + ramp * (i + 1)).join(" + ");
}

/** THE BIDDING, as it happened. It used to sit inside the auction panel in the
 *  middle column, which meant it vanished the moment the auction ended -- and
 *  "what did they bid to get here" is a question you ask most while PLAYING.
 *  It lives in the Contract box now, under the contract it produced. */
function BidLog({ game, nameOf, skat }) {
  const log = game.auction?.log || [];
  if (!log.length) return null;
  return (
    <div className="dis-bidlog">
      {log.map((e, i) => (
        <div key={i}>
          <span>{nameOf(e.seat)}</span>
          <span>{e.pass ? "pass"
            : skat ? e.value
              : <>{e.level}<Den d={e.denom} /></>}</span>
        </div>
      ))}
    </div>
  );
}

/** THE ROUND'S TRICKS: which one, who took it, what it paid. The board only
 *  ever showed the LAST one, so the shape of the round -- who has been taking
 *  the +2s, whether the -1s are landing on the right seat -- had to be held in
 *  your head. Newest FIRST, because the recent tricks are the ones being
 *  reasoned about; the list scrolls in place rather than growing the panel. */
function TrickHistory({ game, nameOf }) {
  const tricks = trickList(game);
  if (!tricks.length) return null;
  return (
    <div className="dis-trickhist">
      {tricks.slice().reverse().map((t) => (
        <div key={t.number} className="dis-th-row">
          <span className="dis-th-n">#{t.number}</span>
          <span className="dis-th-who">{nameOf(t.winner)}</span>
          <span className={`dis-val ${t.value > 0 ? "good" : "bad"}`}>
            {t.value > 0 ? `+${t.value}` : t.value}
          </span>
        </div>
      ))}
    </div>
  );
}

function ContractChip({ game, nameOf, sharpBonus }) {
  const a = game.auction || {};
  if (!a.level) return null;
  const ct = game.contract || {};
  const doubling = ct.re ? 4 : ct.kontra ? 2 : 1;
  const parts = multParts(ct);
  return (
    <div className="dis-chip">
      <span className="dis-chip-den">
        {a.level}<Den d={a.denom} />
      </span>
      {/* SKAT ONLY, and that is the whole rule (2026-08-17). The target is a
          promise in TRICK points -- "score" is reserved for what the round pays
          out -- but in classic and minor the target IS the level, already shown
          as a glyph immediately to the left, so spelling it out restated the
          same number in words one span later. Skat keeps it because there the
          target genuinely differs from the bid: the sharp bonus is added on top,
          so "must take N" is a fact the glyph does not carry.
          This is the line a phone leans on -- the side panel is display:none
          there -- which is exactly why it should not spend half its width
          saying something twice. */}
      <span className="dis-chip-who">
        {nameOf(a.declarer)}
        {game.mode === "skat"
          ? <>{" must take "}{ptsLabel(a.level + (ct.sharp ? sharpBonus : 0))}</>
          : null}
      </span>
      {(parts.length > 0 || doubling > 1) && (
        <span className={`dis-chip-mult${doubling > 1 ? " dbl" : ""}`}>
          {parts.join(" + ")}{parts.length && doubling > 1 ? " · " : ""}
          {doubling > 1 ? (ct.re ? "Kontra + Re" : "Kontra") : ""}
          {ct.value ? ` · ${ct.value * (ct.mult || 1) * doubling}` : ""}
        </span>
      )}
      {/* Classic's Kontra (the engine still says `doubled` on the wire), in
          the slot skat's uses. It has to be on the chip and not only in the
          side panel: the panel is display:none on a phone. NO payout number
          here — over/undertricks move the real figure, so a quoted "· 92"
          was often wrong in both directions. */}
      {game.doubled && (
        <span className="dis-chip-mult dbl">Kontra</span>
      )}
    </div>
  );
}

/** A finished game's one-line summary for the lobby's History card.
 *
 *  The row's score is the MATCH standing, so this says what produced it: how
 *  many deals, played to what. Only a one-round game gets its contract named —
 *  in a ten-round match the last deal's contract is not the story, and putting
 *  it here read as though it were.
 */
function histLine(g) {
  if (g.abandoned) return `abandoned after ${g.rounds || 1} round${(g.rounds || 1) === 1 ? "" : "s"}`;
  if (g.rounds > 1) return `${g.rounds} rounds${g.target ? ` to ${g.target}` : ""}`;
  const c = g.contract;
  if (!c || !c.level) return "";
  // JSX rather than a string, so the suit here is coloured like every other
  // mention of a contract. It is rendered as a child, so a fragment drops
  // straight into the same slot the string used to fill.
  return <>
    {c.you_declared ? "declared" : "defended"}{" "}
    {c.level}<Den d={c.denom} />
    {g.mode === "skat" && c.value
      ? ` for ${c.value}${c.mult > 1 ? `×${c.mult}` : ""}` : ""}
    {c.made ? " (made)" : " (set)"}
  </>;
}

/** The match's scorecard: one line per round played, under the running total.
 *
 *  Every number here is the ENGINE's — `match.rounds` is written when a round
 *  is banked, off the same result row the panel narrates, so nothing is
 *  re-derived from the board. Renders nothing at all for a match with no
 *  scorecard: one that was already in progress when this shipped has no rounds
 *  recorded and there is nowhere to recover them from.
 *
 *  The score column is signed from YOUR seat — exactly one side scores a round,
 *  so a `+` is what you took and a `−` is what it cost you, which is the read
 *  the running total above is made of.
 */
function MatchCard({ rounds, mySeat, oppSeat, nameOf, onStory }) {
  if (!rounds || rounds.length === 0) return null;
  /* THE DD FIGURE MOVED INTO THE ROUND'S STORY (2026-08-13). It was a fifth
     column here, which made every line carry a number that is only meaningful
     once you are looking at the deal — and it cost the contract column the
     width it needed. It lives in the modal now, where the hands it prices are
     on screen. */
  return (
    <div className="dis-mcard">
      <div className="dis-mrow dis-mrow-hd">
        <span>#</span><span>Contract</span><span>Pts</span><span>Score</span>
      </div>
      {rounds.map((r, i) => {
        const mine = r.scores?.[mySeat] || 0;
        const theirs = r.scores?.[oppSeat] || 0;
        const declared = r.declarer === mySeat;
        // A row with a banked layout opens the round's story. Click and
        // right-click both work (contextmenu is also what a phone's
        // long-press fires); a row banked before the reveal shipped has
        // nothing to show and stays inert.
        const story = onStory && (r.deal || r.reveal)
          ? (e) => { e.preventDefault(); onStory(r); } : null;
        return (
          <div className={`dis-mrow${story ? " dis-mrow-open" : ""}`}
            key={r.round ?? i}
            onClick={story} onContextMenu={story}
            title={story ? "Show this round face up" : undefined}>
            <span className="dis-mrow-n">{r.round ?? i + 1}</span>
            <span className={`dis-mrow-ct${declared ? " mine" : ""}`}
              title={story ? roundTitle(r, nameOf) + " — click for the full deal" : roundTitle(r, nameOf)}>
              {r.abandoned ? "forfeit"
                : r.declarer < 0 ? "—"
                  : <>{nameOf(r.declarer)}{" "}
                    <b>{r.level}<Den d={r.denom} /></b>
                    {/* The defender's bet, on the line it doubled. A doubled
                        round otherwise looked ordinary with a surprising
                        number beside it — which is the row a reader most wants
                        explained. Absent on a round banked before the field
                        shipped, which reads as undoubled, correctly. */}
                    {r.doubling > 1
                      ? <span className="dis-mrow-dbl"
                          title={r.doubling === 4
                            ? "Kontra and Re — this round was played at higher stakes still"
                            : "Kontra — this round was played at higher stakes"}>
                          {r.doubling === 4 ? "Kontra · Re" : "Kontra"}
                        </span>
                      : ""}
                    {r.null ? " Null" : ""}</>}
            </span>
            {/* The declarer's trick points against what they promised — the
                yardstick and the bar, which is what makes a made/set line
                readable at a glance. */}
            <span className="dis-mrow-pts">
              {r.declarer >= 0 && !r.abandoned
                ? `${r.pts?.[r.declarer] ?? 0}/${r.target}` : "—"}
            </span>
            <span className={`dis-mrow-sc ${mine >= theirs ? "good" : "bad"}`}>
              {mine >= theirs ? `+${mine}` : `−${theirs}`}
            </span>
          </div>
        );
      })}
    </div>
  );
}

/** The hover text for a scorecard line — the whole sentence the row abbreviates. */
function roundTitle(r, nameOf) {
  if (r.abandoned) return `Round ${r.round}: forfeited`;
  if (r.declarer < 0) return `Round ${r.round}`;
  const who = nameOf(r.declarer);
  const what = `${r.level}${DENOM_LABEL[r.denom] || ""}`;
  const took = `took ${r.pts?.[r.declarer] ?? 0} of ${r.target}`;
  const bet = r.doubling > 1 ? ` (doubled, ×${r.doubling})` : "";
  return `Round ${r.round}: ${who} declared ${what}${bet}, ${took} — `
    + (r.null ? "Null" : r.made ? "made" : "set");
}

/** A finished round, face up: the deal laid out the way the BOARD lays it out
 *  — opponent across the table, your own seat nearest you, each seat its hand
 *  row over (or under) its piles, the out-of-play cards in the middle where
 *  the trick lives — with the round's bidding and the settled contract in a
 *  column on the right, the same split the live board uses. Everything here
 *  is the scorecard line's own banked data (`r.deal` + `r.reveal`) — nothing
 *  is re-derived, and rounds banked before the reveal shipped cannot open
 *  this.
 */
function RoundStory({ r, mySeat, nameOf, roomId, mode, maxLevel, onClose }) {
  /* THE DOUBLE-DUMMY FIGURE LIVES HERE NOW, not as a fifth column on the
     scorecard: it prices THIS deal in THIS contract, so it belongs where the
     hands are on screen. One round, so the hook is handed a single-entry list
     — it caches per room and round either way. */
  const dd = useDdReviews([r], roomId);
  /* PAR: the same deal solved in every denomination from BOTH sides. Skat is
     the only mode with a sixth denomination (Grand sits at 6, above no-trump,
     because 5 is the legacy Null marker). */
  const parDenoms = mode === "skat" ? [0, 1, 2, 3, 4, 6] : [0, 1, 2, 3, 4];
  const par = useParTable(r, roomId, parDenoms);
  /* Each seat's best denomination — marked only once that seat's whole column
     has landed, since a running maximum over a half-filled table moves as it
     fills and would decorate the wrong row on the way. */
  const best = [0, 1].map((seat) => {
    const col = parDenoms.map((den) => par?.[den]?.pts?.[seat]);
    return col.every((p) => typeof p === "number") ? Math.max(...col) : null;
  });
  const deal = r.deal || {};
  const rev = r.reveal || {};
  const hands = deal.hands || [];
  const piles = deal.piles || [];
  const out = deal.out || [];
  const shown = new Set(rev.looked === false ? [] : rev.shown || []);
  const [take, give] = rev.swap || [null, null];
  const ann = rev.announce || {};
  const annNames = ["hand", "sharp", "open"].filter((k) => ann[k]);
  const seatName = (q) => (q === 2 ? "Dummy" : nameOf(q));
  // Board order from the viewer's seat: opponent at the top, the dummy where
  // it sits on the felt, you nearest yourself. `mySeat` can be null on a
  // finished room opened from the lobby — fall back to seat 0's view.
  const me = mySeat ?? 0;
  const order = [1 - me, ...(hands.length > 2 ? [2] : []), me]
    .filter((q) => hands[q]);

  // One bid-log line. Classic entries carry level+denom, skat's carry value,
  // either may be a pass — render whichever fields the entry has.
  const bidLine = (e, i) => (
    <div key={i} className="dis-story-bid">
      <span>{nameOf(e.seat)}</span>
      <span>
        {e.pass ? "pass"
          : e.value !== undefined ? e.value
            : <>{e.level}<Den d={e.denom} /></>}
      </span>
    </div>
  );

  const seatHd = (q) => (
    <div className="dis-story-seatname">
      <b>{seatName(q)}</b>
      {q === r.declarer && <span className="dis-story-tag">declared</span>}
    </div>
  );
  const handRow = (q) => (
    <div className="dis-story-cards dis-story-hand">
      {hands[q].map((c) => (
        <span key={c} className={c === take ? "dis-story-took" : undefined}
          title={c === take ? "Taken from the talon" : undefined}>
          <Card c={c} small />
        </span>
      ))}
    </div>
  );
  // The board's own pile shape — the buried card peeking out top-right from
  // under the card that covered it — just face up.
  const pileRow = (q) => piles[q] && (
    <div className="dis-story-cards dis-story-piles">
      {piles[q].map((p, i) => (
        <span className="dis-story-pile" key={i}
          title="A pile: the offset card sat underneath">
          {p.length > 1 && (
            <span className="dis-story-buried"><Card c={p[0]} small /></span>
          )}
          <Card c={p[p.length - 1]} small />
        </span>
      ))}
    </div>
  );

  return (
    <CreateModal title={`Round ${r.round} — face up`} onClose={onClose}>
      <div className="dis-story">
        <div className="dis-story-sum">
          {roundTitle(r, nameOf).replace(/^Round \d+: /, "")}
        </div>

        <div className="dis-story-grid">
          <div className="dis-story-felt">
            {order.filter((q) => q !== me).map((q) => (
              <div className="dis-story-seat" key={q}>
                {seatHd(q)}
                {handRow(q)}
                {pileRow(q)}
              </div>
            ))}

            {/* The out-of-play cards sit in the middle of the felt, where the
                trick lives on the live board — between the other seats above
                and your own below. */}
            <div className="dis-story-sec dis-story-out">
              <div className="dis-story-hd">
                Out of play
                {rev.looked === false && (
                  <span className="dis-story-tag">Hand — never looked</span>
                )}
              </div>
              <div className="dis-story-cards">
                {out.map((c) => (
                  <span key={c}
                    className={c === give ? "dis-story-gave"
                      : shown.has(c) ? "dis-story-shown" : undefined}
                    title={c === give ? "Discarded into the talon by the declarer"
                      : shown.has(c) ? "Shown to the declarer" : "Never seen during the round"}>
                    <Card c={c} small />
                  </span>
                ))}
              </div>
              {(shown.size > 0 || take !== null) && (
                <div className="dis-story-note muted">
                  {shown.size > 0 && <>Outlined: shown to {nameOf(r.declarer)}. </>}
                  {take !== null
                    ? <>Took <CardName c={take} />, discarded <CardName c={give} />.</>
                    : rev.looked === false ? null : <>Stood pat.</>}
                </div>
              )}
            </div>

            {/* Your seat mirrors the board: piles above the hand, name under. */}
            {hands[me] && (
              <div className="dis-story-seat">
                {pileRow(me)}
                {handRow(me)}
                {seatHd(me)}
              </div>
            )}
          </div>

          {/* The right column: how the contract was bought, then what it was —
              the same information split the live board's rail uses. */}
          <div className="dis-story-side">
            {rev.auction && rev.auction.length > 0 && (
              <div className="dis-story-sec">
                <div className="dis-story-hd">Bidding</div>
                <div className="dis-story-bids">
                  {rev.auction.map(bidLine)}
                  {/* The bets are not in the log — they are phases of their
                      own — so the story synthesizes them from the row's own
                      doubling, the field the scorecard chip already trusts. */}
                  {r.doubling > 1 && (
                    <div className="dis-story-bid dis-story-dbl">
                      <span>{nameOf(1 - r.declarer)}</span>
                      <span>Kontra</span>
                    </div>
                  )}
                  {r.doubling === 4 && (
                    <div className="dis-story-bid dis-story-dbl">
                      <span>{nameOf(r.declarer)}</span>
                      <span>Re</span>
                    </div>
                  )}
                  {annNames.length > 0 && (
                    <div className="dis-story-bid">
                      <span>{nameOf(r.declarer)}</span>
                      <span>{annNames.map((k) => k[0].toUpperCase() + k.slice(1)).join(" + ")}</span>
                    </div>
                  )}
                </div>
              </div>
            )}
            {r.declarer >= 0 && !r.abandoned && (
              <div className="dis-story-sec">
                <div className="dis-story-hd">Contract</div>
                <div className="dis-story-ctline">
                  <b>{r.level}<Den d={r.denom} /></b>
                  {r.doubling > 1 && (
                    <span className="dis-mrow-dbl">
                      {r.doubling === 4 ? "Kontra · Re" : "Kontra"}
                    </span>
                  )}
                </div>
                <div className="dis-story-note muted">
                  {nameOf(r.declarer)} declared
                  {annNames.length > 0 ? ` (${annNames.join(", ")})` : ""} —{" "}
                  {r.null ? "Null" : r.made ? "made it" : "set"},{" "}
                  {r.pts?.[r.declarer] ?? 0} of {r.target}.
                </div>
              </div>
            )}

            {/* WHAT PERFECT PLAY WAS WORTH — the same deal and the same
                contract, the card play redone from trick 1 by two players who
                see every card. Beating it means the hidden cards broke your
                way; trailing it is the cost of playing honestly in the dark.
                It is an exact solve, not an opinion, which is why it is stated
                as a fact about the round rather than as a bot's view.
                Two rounds cannot be priced and say so: one banked before the
                deal was stored, and a DUMMY round, whose three hands the
                two-seat solver cannot take. */}
            {r.declarer >= 0 && !r.abandoned && (
              <div className="dis-story-sec">
                <div className="dis-story-hd">Double dummy</div>
                {(() => {
                  const seatWord = (v) => {
                    const dScore = Math.max(v, 0), oScore = Math.max(-v, 0);
                    const mine = r.declarer === me ? dScore : oScore;
                    const theirs = r.declarer === me ? oScore : dScore;
                    const got = r.scores?.[me] ?? 0;
                    const lost = r.scores?.[1 - me] ?? 0;
                    const real = got >= lost ? got : -lost;
                    const ideal = mine >= theirs ? mine : -theirs;
                    return (
                      <>
                        <div className="dis-story-ctline">
                          <b className={ideal >= 0 ? "dis-story-dd-good" : "dis-story-dd-bad"}>
                            {ideal >= 0 ? `+${ideal}` : `−${Math.abs(ideal)}`}
                          </b>
                        </div>
                        <div className="dis-story-note muted">
                          Perfect play in this contract scores{" "}
                          {ideal >= 0 ? `${ideal} to you` : `${Math.abs(ideal)} against you`};
                          {" "}the round actually paid{" "}
                          {real >= 0 ? `${real} to you` : `${Math.abs(real)} against you`}.
                        </div>
                      </>
                    );
                  };
                  if (!r.deal) {
                    return <div className="dis-story-note muted">
                      No stored deal — this round predates the review, or was forfeited.
                    </div>;
                  }
                  if ((r.deal.hands?.length ?? 2) !== 2) {
                    return <div className="dis-story-note muted">
                      A dummy round has three hands; the exact solver prices two.
                    </div>;
                  }
                  const v = dd[r.round];
                  if (v === undefined) {
                    return <div className="dis-story-note muted">Solving…</div>;
                  }
                  if (v === null) {
                    return <div className="dis-story-note muted">Could not be solved.</div>;
                  }
                  return seatWord(v);
                })()}
              </div>
            )}

            {/* PAR — the same deal solved in every denomination from BOTH
                sides: how many trick points each player could have taken as
                declarer, and whether they could have ducked to Null there.
                The points ARE the contract: a level is a promise of that many
                points, so the number in a cell is the highest level that
                player could have bid in that denomination and still made.
                Everything here is an exact solve of the real cards, which is
                why it is stated as a fact about the deal. */}
            {r.declarer >= 0 && !r.abandoned && r.deal
              && (r.deal.hands?.length ?? 2) === 2 && (
              <div className="dis-story-sec dis-story-par">
                <div className="dis-story-hd">Par</div>
                {par === null ? (
                  <div className="dis-story-note muted">Could not be solved.</div>
                ) : (
                  <>
                    <div className="dis-partable">
                      <div className="dis-parhd" />
                      <div className="dis-parhd">{nameOf(me)}</div>
                      <div className="dis-parhd">{nameOf(1 - me)}</div>
                      {parDenoms.map((den) => {
                        const row = par[den] || {};
                        const cell = (seat) => {
                          const p = row.pts?.[seat];
                          const duck = row.duck?.[seat];
                          const played = den === r.denom && seat === r.declarer;
                          // A seat's BEST denomination, marked only once every
                          // cell in its column has landed — a running maximum
                          // over a half-filled table moves as it fills.
                          const top = best[seat] != null && p === best[seat];
                          return (
                            <div key={seat}
                              className={`dis-parcell${played ? " dis-parcell-played" : ""}`
                                + (top ? " dis-parcell-top" : "")}
                              title={played ? "The contract that was actually played"
                                : top ? `${nameOf(seat)}'s best denomination` : undefined}>
                              {typeof p === "number"
                                ? <b>{Math.max(p, 0)}</b>
                                : <span className="dis-parwait">·</span>}
                              {duck && (
                                <span className="dis-parnull"
                                  title="Could win no scoring trick at all — Null">N</span>
                              )}
                            </div>
                          );
                        };
                        return (
                          <Fragment key={den}>
                            <div className="dis-parden"><Den d={den} /></div>
                            {cell(me)}
                            {cell(1 - me)}
                          </Fragment>
                        );
                      })}
                    </div>
                    <div className="dis-story-note muted">
                      Points each side could take as declarer with every card face
                      up — the highest level they could have bid there and made
                      {maxLevel ? <> (levels stop at {maxLevel})</> : null}.
                      {" "}<b>N</b>: could duck every scoring trick for Null.
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </div>
    </CreateModal>
  );
}

/** Solved perfect-play reviews, for the life of the tab. A banked round's deal
 *  is immutable and the solve is exact, so a result can never go stale — and a
 *  match reopened from the lobby must not pay the solver again. */
const REVIEW_CACHE = new Map();   // `${roomId}:${round}` -> value | null (unsolvable)

/** The DD column's numbers: every banked round's exact double-dummy result —
 *  the same deal, the same contract, the card play redone from trick 1 by two
 *  players who can see all 32 cards. A property of the DEAL, not a bot's
 *  opinion: the solve has no seed, so it is the same number on every render
 *  and on both players' screens.
 *
 *  Solves run lazily in ONE on-demand module worker, torn down when the batch
 *  is answered. One is enough — a round costs ~250ms and the cells fill in as
 *  answers land — and it must NOT lean on the Hard tier's pool: the scorecard
 *  renders at every tier and in human-vs-human rooms.
 *
 *  Returns `{ [round]: value | null }`; a round still solving is simply absent.
 */
function useDdReviews(rounds, roomId) {
  const [vals, setVals] = useState({});
  const n = rounds ? rounds.length : 0;
  useEffect(() => {
    if (!n) return undefined;
    // Seed what the tab already knows, then solve only what it does not.
    const seed = {};
    const todo = [];
    for (const r of rounds) {
      const k = `${roomId}:${r.round}`;
      if (REVIEW_CACHE.has(k)) seed[r.round] = REVIEW_CACHE.get(k);
      else if (r.deal && (r.deal.hands?.length ?? 2) === 2) todo.push(r);
    }
    setVals(seed);
    if (todo.length === 0 || typeof Worker === "undefined") return undefined;
    let dead = false;
    const fail = (rs) => {
      for (const r of rs) REVIEW_CACHE.set(`${roomId}:${r.round}`, null);
      if (!dead) setVals((prev) => {
        const next = { ...prev };
        for (const r of rs) next[r.round] = null;
        return next;
      });
    };
    let w;
    try { w = new Worker(`${import.meta.env.BASE_URL}wasm/dissonance-worker.js`, { type: "module" }); }
    catch { fail(todo); return undefined; }
    const idFor = new Map();
    let nextId = 1;
    w.onmessage = (e) => {
      const d = e.data || {};
      if (d.ready !== undefined) {
        if (!d.ready) { fail(todo); try { w.terminate(); } catch {} return; }
        for (const r of todo) {
          const id = nextId++;
          idFor.set(id, r.round);
          w.postMessage({ id, kind: "review",
            req: JSON.stringify({ deal: r.deal, payoff: r.deal.terms }) });
        }
        return;
      }
      if (d.id == null || !idFor.has(d.id)) return;
      const round = idFor.get(d.id);
      idFor.delete(d.id);
      // An error is deterministic (a deal the reader refuses), so it is cached
      // like an answer — re-solving it on every render buys nothing.
      const v = d.error != null || typeof d.value !== "number" ? null : d.value;
      REVIEW_CACHE.set(`${roomId}:${round}`, v);
      if (!dead) setVals((prev) => ({ ...prev, [round]: v }));
      if (idFor.size === 0) { try { w.terminate(); } catch {} }
    };
    w.onerror = () => { fail(todo); try { w.terminate(); } catch {} };
    return () => { dead = true; try { w.terminate(); } catch {} };
    // The rounds ARRAY is a fresh object on every broadcast, but a banked round
    // never changes — only the COUNT can move, so the count is the dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roomId, n]);
  return vals;
}

/** Solved par tables, cached beside the reviews and for the same reason: a
 *  banked deal is immutable and the solves are exact. */
const PAR_CACHE = new Map();   // `${roomId}:${round}` -> {denom: {pts, duck}} | null

/** THE PAR TERMS: two synthetic contracts that make `odd_review` answer the
 *  two questions the par table asks, neither of which the wasm exports.
 *
 *  `odd_review` prices a CONTRACT, and the artifact is a committed build, so
 *  each question is asked by naming a contract whose payoff IS the answer:
 *
 *  * **points** — target 0, make 0, over 1, set_base 0, short 1. At or above
 *    the target that pays `0 + 1 × (pts − 0)`; below it `−(0 + 1 × (0 − pts))`
 *    — the same number, so the payoff is the identity on the declarer's trick
 *    points at every leaf and the minimax over it IS the points minimax. No
 *    `null` key: a consolation is a cliff at one bit of state, not a point
 *    count, and it would make the answer something else entirely.
 *  * **the duck** — every ordinary leaf worth 0 and the consolation worth 1,
 *    so the value is 1 exactly when the declarer can force taking no scoring
 *    trick all round. That is `Dd::null_no_even_makeable`, which the browser
 *    has no export for.
 *
 *  Both are held to the crate's own solvers by `wire::review::the_par_contract_
 *  is_exactly_a_double_dummy_points_solve` and `..._the_par_null_probe_is_
 *  exactly_the_ducking_search` — the claim is about the solver, and nothing on
 *  this side of the wire can see it.
 */
const PAR_TERMS = {
  pts: (declarer) => ({
    declarer, target: 0, make: 0, over: 1, set_base: 0, short: 1, ramp: 0,
  }),
  duck: (declarer) => ({
    declarer, target: 0, make: 0, over: 0, set_base: 0, short: 0, ramp: 0, null: 1,
  }),
};

/** PAR — what each seat could have taken as declarer in every denomination,
 *  with all 32 cards face up, and whether they could have ducked to Null.
 *
 *  Two exact solves per (denomination, seat): the deal is the round's own
 *  snapshot with `trump` swapped and `leader` set to whoever is declaring,
 *  because the declarer leads to trick 1 and that is worth ~0.93 points — the
 *  two sides of a row are different POSITIONS, not one number negated.
 *
 *  That is 20 solves in a classic round, so they run over a SMALL POOL rather
 *  than the review's single worker — and small is the point: the never-take-
 *  every-core rule applies here exactly as it does to the Hard tier's pool,
 *  and this one runs while a player is reading a modal.
 *
 *  Answers land one at a time and the table fills in; the set is cached only
 *  once it is complete, so a modal closed mid-solve re-asks rather than
 *  caching half a table. Returns `{[denom]: {pts: [p0, p1], duck: [d0, d1]}}`
 *  with cells absent until solved, or `null` when nothing can be solved.
 */
function useParTable(r, roomId, denoms) {
  const [par, setPar] = useState({});
  const round = r?.round;
  const key = `${roomId}:${round}`;
  const dkey = denoms.join(",");
  useEffect(() => {
    if (round == null) return undefined;
    if (PAR_CACHE.has(key)) { setPar(PAR_CACHE.get(key)); return undefined; }
    const deal = r.deal;
    // The two-seat solver cannot take a dummy round's three hands, and a round
    // banked before the snapshot shipped has nothing to solve.
    if (!deal || (deal.hands?.length ?? 2) !== 2 || typeof Worker === "undefined") {
      setPar(null); return undefined;
    }
    setPar({});
    let dead = false;
    // POINTS FIRST, every denomination, then the Null probes: the table's
    // numbers are what a reader is waiting for, and the markers are a detail
    // that can arrive after them.
    const queue = [];
    for (const what of ["pts", "duck"]) {
      for (const den of denoms) for (const seat of [0, 1]) queue.push([what, den, seat]);
    }
    const total = queue.length;
    const table = {};
    let done = 0;
    const pool = [];
    const stop = () => { for (const w of pool) { try { w.terminate(); } catch { /* gone */ } } };
    const fail = () => { PAR_CACHE.set(key, null); if (!dead) setPar(null); stop(); };
    const feed = (w, id) => {
      const job = queue.shift();
      if (!job) return false;
      const [what, den, seat] = job;
      w._job = job;
      w.postMessage({ id, kind: "review", req: JSON.stringify({
        deal: { ...deal, trump: den, leader: seat }, payoff: PAR_TERMS[what](seat),
      }) });
      return true;
    };
    const n = Math.max(1, Math.min((navigator.hardwareConcurrency || 4) - 2, 2));
    let bad = 0, issued = 0;
    for (let i = 0; i < n; i++) {
      let w;
      try { w = new Worker(`${import.meta.env.BASE_URL}wasm/dissonance-worker.js`, { type: "module" }); }
      catch { break; }
      w.onmessage = (e) => {
        const d = e.data || {};
        if (d.ready !== undefined) {
          // One worker that will not load is survivable — the others drain the
          // queue. All of them is the wasm being unavailable, which is the
          // review's own failure and says so.
          if (!d.ready) { bad += 1; if (bad >= pool.length) fail(); return; }
          feed(w, ++issued);
          return;
        }
        const job = w._job;
        if (!job) return;
        const [what, den, seat] = job;
        done += 1;
        // An error is deterministic (a deal the reader refuses), so the cell
        // simply stays empty rather than being retried.
        if (typeof d.value === "number") {
          const row = { ...(table[den] || {}) };
          const col = [...(row[what] || [])];
          col[seat] = what === "duck" ? d.value === 1 : d.value;
          row[what] = col;
          table[den] = row;
          if (!dead) setPar({ ...table });
        }
        if (!feed(w, ++issued) && done >= total) {
          PAR_CACHE.set(key, table);
          stop();
        }
      };
      w.onerror = fail;
      pool.push(w);
    }
    if (pool.length === 0) { fail(); return undefined; }
    return () => { dead = true; stop(); };
    // Same argument as the review hook's: a banked round never changes, so the
    // round — and which denominations are being asked about — is the whole
    // dependency.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key, dkey]);
  return par;
}

/** What the declared skat game is worth right now, and why.
 *  `rows` renders it as side-panel score rows; otherwise as one inline line. */
function SkatStake({ game, nameOf, rows, shortRate }) {
  const ct = game.contract || {};
  if (!ct.value) return null;
  const doubling = ct.re ? 4 : ct.kontra ? 2 : 1;
  const stake = ct.value * ct.mult * doubling;
  const parts = multParts(ct);
  const why = [
    parts.length ? `×${ct.mult} ${parts.join(" + ")}` : null,
    ct.re ? "×4 Kontra + Re" : ct.kontra ? "×2 Kontra" : null,
  ].filter(Boolean).join(" · ");
  if (!rows) {
    return (
      <div className="dis-maths">
        {ct.value}{ct.mult > 1 ? ` × ${ct.mult}` : ""}{doubling > 1 ? ` × ${doubling}` : ""}
        {" = "}<b>{stake}</b>{why ? ` — ${why}` : ""}
      </div>
    );
  }
  return (
    <>
      <div className="dis-scorerow"><span>At stake</span><b>{stake}</b></div>
      {why && <div className="muted" style={{ fontSize: "0.72rem" }}>{why}</div>}
      <div className="muted" style={{ fontSize: "0.72rem" }}>
        Made, it goes to {nameOf(game.auction.declarer)} plus 1 a point over;
        missed, to {nameOf(1 - game.auction.declarer)} plus{" "}
        {shortRate ?? SHORT_PENALTY_FALLBACK} a point short.
      </div>
    </>
  );
}

/** What `value` would COMMIT you to in each denomination — the lowest level
 *  whose base x level reaches it, which is the number of trick points you would
 *  then have to take.
 *
 *  Every denomination, not only the ones that hit the number exactly. The
 *  decision at the ladder is "if I win here, what am I promising?", and for four
 *  of the five that answer is a level whose value OVERSHOOTS the bid — showing
 *  only the exact hits answered it for one denomination and left the rest blank.
 *  It also makes the cheap end legible: a bid of 2 requires level 1 in
 *  everything, i.e. it commits you to nothing at all. */
function levelsFor(value, bases, maxLevel) {
  if (!value || !bases?.length || !maxLevel) return [];
  return bases
    // A base of 0 marks a denomination that is NOT on the ladder (Null). Left
    // in, it divides to Infinity and only survives because the level cap
    // happens to drop it -- filter it explicitly rather than rely on that.
    .map((base, denom) => (base > 0
      ? { denom, level: Math.max(1, Math.ceil(value / base)) }
      : null))
    .filter((x) => x && x.level <= maxLevel);
}

/** What a number commits its winner to, per denomination. Rendered for the
 *  STANDING bid as well as your own selection: while the opponent holds it, the
 *  question you are answering is what THEIR number would cost you to take over,
 *  and that was only ever shown for a value you had already picked. */
function NeedsRow({ value, prefix, bases, maxLevel }) {
  if (!value || !bases?.length) return null;
  return (
    <div className="dis-clears">
      <span className="muted">{prefix}</span>
      {levelsFor(value, bases, maxLevel).map((x) => (
        <span key={x.denom} className="dis-clear">
          {x.level}<Den d={x.denom} />
        </span>
      ))}
    </div>
  );
}

/** Which mode a room runs. Classic is the default, so only the others are
 *  marked -- skat's second auction, and minor's +1 evens. */
// THE MODE IS A META TOKEN, NOT A PILL IN THE TITLE, and it moved for three
// separate reasons that all had the same root. As a pill inside `.lby-card-title` it
// (a) was CLIPPED MID-WORD at the tablet tier — the title is a two-line clamped box
// with `overflow:hidden`, so the pill's right border was amputated and "MINOR" came
// out as "MIN" plus half a glyph, hard against the turn pill beside it; (b) forced
// "Your game" to wrap after "Your" on a phone, orphaning one word beside 215px of
// empty space; and (c) was drawn identically to the TURN pill 180px away on the same
// line, so a permanent property of the room and a transient state read as the same
// class of object. The meta line is where a room's facts already live — its code, its
// age, Dontminion's expansion sets — and it is set as text there rather than as a
// second kind of chip. Classic carries no token at all; it is the default.
function ModeBadge({ mode }) {
  if (!ADMIN_ONLY_MODE_IDS.has(mode)) return null;
  return <span className="lby-meta-extra"> · {MODE_LABEL[mode]}</span>;
}

// `who` prefixes the holder's name, so the standing bid is ONE line -- "Ada 5♦"
// rather than a contract row with a separate "Ada needs 5 pts" under it.
//
// NOTHING is rendered before a bid stands: the placeholders ("no bid yet", "no
// contract yet") are gone. The row keeps its height from `.dis-contractrow`'s
// `min-height`, NOT from its content, which is what stops the keypad below
// moving when the first bid lands -- the bug those two placeholders were
// themselves shortened to avoid. Deleting the text without that reserve would
// reintroduce it.
function ContractLine({ game, who }) {
  const a = game.auction || {};
  // Skat mode: until the declaration lands, all there is to show is the number.
  if (game.mode === "skat" && !a.level) {
    return a.value ? <span className="dis-contract"><b>{a.value}</b></span> : null;
  }
  if (!a.level) return null;
  return (
    <span className="dis-contract">
      {who ? <span className="dis-holder">{who}</span> : null}
      <b>{a.level}</b>
      <Den d={a.denom} />
    </span>
  );
}

/** What a contract pays and what it costs, for a bid not yet made.
 *
 *  Two call sites and one component: the bid the player has SELECTED (beside
 *  the Bid button, so the price is read where the decision is taken) and the
 *  contract currently STANDING (under the auction's headline).
 *
 *  Renders nothing when there is no contract to price, and the row it sits in
 *  reserves its own height -- same reason as the contract row above it. A line
 *  that appears when the first bid lands would push the keypad down, which is
 *  the bug this panel has now been through twice.
 */
function BidWorth({ level, jump, price, label }) {
  if (!level) return null;
  const { make, down } = price(level, jump);
  return (
    <span className="dis-worth-in">
      {label ? <span className="dis-worth-lbl">{label}</span> : null}
      makes <b>{make}</b> · down for <b>{down}</b>
    </span>
  );
}

// ─── socket ─────────────────────────────────────────────────────────────────

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
  const send = useCallback((o) => { try { wsRef.current?.send(JSON.stringify(o)); } catch {} }, []);
  const disconnect = useCallback(() => {
    try { wsRef.current?.close(); } catch {}
    wsRef.current = null; setConnected(false);
  }, []);
  const socketReady = useCallback(() => wsRef.current?.readyState, []);
  return { connected, connect, send, disconnect, socketReady };
}

// ─── main ───────────────────────────────────────────────────────────────────

export default function Dissonance({ myId, authUser, onExit, offline = null }) {
  const [screen, setScreen] = useState("lobby");     // lobby | waiting | game
  const [roomId, setRoomId] = useState("");
  const [roomData, setRoomData] = useState(null);
  const [openGames, setOpenGames] = useState(() => readLobbyCache("dissonance", myId, "open", []));
  const [myGames, setMyGames] = useState(() => readLobbyCache("dissonance", myId, "mine", []));
  const [history, setHistory] = useState(() => readLobbyCache("dissonance", myId, "history", []));
  const isAdmin = !!authUser?.is_admin;
  const modeOptions = isAdmin ? MODES : PUBLIC_MODES;
  const modeVisible = useCallback((mode) => isAdmin || !ADMIN_ONLY_MODE_IDS.has(mode), [isAdmin]);
  const visibleOpenGames = useMemo(
    () => openGames.filter((game) => modeVisible(game.mode)),
    [openGames, modeVisible],
  );
  const visibleMyGames = useMemo(
    () => myGames.filter((game) => modeVisible(game.mode)),
    [myGames, modeVisible],
  );
  const visibleHistory = useMemo(
    () => history.filter((game) => modeVisible(game.mode)),
    [history, modeVisible],
  );
  const [historyShown, historyMore] = useProgressiveList(visibleHistory);
  // A column that scrolls inside itself must say so — see `useListFade`.
  useListFade();
  // A room still waiting for an opponent belongs in Open, not in progress.
  const activeMine = notWaiting(visibleMyGames);
  const [lobbyTab, setLobbyTab] = useState("open");
  const [loadingGames, setLoadingGames] = useState(false);
  const [connecting, setConnecting] = useState(false);
  const [reconnecting, setReconnecting] = useState(false);
  const [toast, setToast] = useState("");
  const [showRules, setShowRules] = useState(false);
  // THE PAPER SCORECARD -- a keeper for a classic game played with real cards,
  // lobby-only because that is where you are when you are not playing here.
  const [showCard, setShowCard] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [confirmAbandon, setConfirmAbandon] = useState(false);
  // The scorecard row someone asked to see face up, or null.
  const [storyRound, setStoryRound] = useState(null);
  const [bidLevel, setBidLevel] = useState(null);
  const [bidDenom, setBidDenom] = useState(null);
  const [newMode, setNewMode] = useState("classic");
  // If an admin logs out while this lobby stays mounted, do not leave a
  // restricted mode selected in the public create modal.
  useEffect(() => {
    if (!modeOptions.some((mode) => mode.id === newMode)) setNewMode("classic");
  }, [modeOptions, newMode]);
  // Create-modal selections. Deferred until "Create Game" rather than firing on
  // the option click — the shape every other game's modal uses.
  const [createOpp, setCreateOpp] = useState("ai");
  // Difficulty defaults to the tier this player last actually played, Normal
  // until they have one.
  const [createDiff, setCreateDiff, rememberDiff] =
    useLastDifficulty("dissonance", myId, BOT_TIER_IDS, "normal");
  // Skat mode's half-built moves: the number, then the declaration.
  const [bidValue, setBidValue] = useState(null);
  const [declDenom, setDeclDenom] = useState(null);
  const [declLevel, setDeclLevel] = useState(null);
  const [declSharp, setDeclSharp] = useState(false);
  const [declOpen, setDeclOpen] = useState(false);

  // Client-side search: the worker pool, whether it came up, and the two
  // idempotence keys (armed once per room+socket, dispatched once per decision).
  const wasmPoolRef = useRef(null);
  // The loaded artifact's wire vintage (see the ready handshake below); 1
  // until a pool reports otherwise, which is also what a pre-wire worker is.
  const wasmWireRef = useRef(1);
  const [wasmReady, setWasmReady] = useState(false);
  const clientAiArmedRef = useRef(null);
  const aiDispatchRef = useRef(null);
  const reconnTimer = useRef(null);
  const reconnTries = useRef(0);
  const roomIdRef = useRef("");
  const popHandlerRef = useRef(() => {});
  const didInitRef = useRef(false);
  roomIdRef.current = roomId;

  const game = roomData?.game || null;
  const players = roomData?.players || {};
  const seats = game?.seats || [];
  const mySeat = game ? game.you : null;

  // `turn_seat`, not `to_play`. They are the same number in every two-seat
  // mode, but `to_play` is a POSITION and the dummy's is 2 -- comparing that
  // against your seat tells the declarer it is not their move on a third of
  // the plies they actually have to make. `??` so a cached bundle talking to
  // an older server still reads the old field.
  const turnSeat = game?.turn_seat ?? game?.to_play;
  const myTurn = !!game && game.phase !== "over"
    && (game.phase === "auction" ? game.auction.to_act === mySeat : turnSeat === mySeat);
  // The dummy is on turn AND it is mine to play -- the two halves of "click
  // its cards", kept apart because the defender watches the same seat move.
  const dummyIsMine = !!game?.dummy && game.dummy_seat === mySeat;
  const dummyToPlay = !!game?.dummy && game.to_play === DUMMY_POS && myTurn;
  const isSkat = game?.mode === "skat";
  //: QUARTET: four hands, two players. `game.mine` is the SECOND hand this
  //: player commands (position `mySeat + QUARTET_HANDS`) and is private to
  //: them -- the mode's central information decision, since a finesse is a
  //: guess about which of two hidden hands holds a card.
  const isQuartet = game?.mode === "quartet";
  const myOther = isQuartet && mySeat != null ? mySeat + QUARTET_HANDS : null;
  //: Which of my two positions is on turn, if either. `to_play` is a POSITION
  //: and `turn_seat` is the PLAYER, so a quartet player is told "your move"
  //: on half the plies and has to be told WHICH HAND as well.
  const qToPlay = isQuartet && myTurn && game?.phase === "play" ? game.to_play : null;
  const declSeat = game?.auction?.declarer;
  const iDeclare = game != null && mySeat != null && declSeat === mySeat;
  // Skat's post-auction prompts each belong to exactly one seat; the server
  // only ships `talon` / `declare` to that seat, and Kontra/Re go by phase.
  const myKontra = isSkat && game?.phase === "kontra" && !iDeclare;
  // Classic's Double is the same seat's decision as skat's Kontra: the DEFENDER.
  const myDouble = !isSkat && game?.phase === "double" && !iDeclare;
  const myRe = isSkat && game?.phase === "re" && iDeclare;
  // Did the declarer actually SEE the talon? Classic always shows it to them;
  // skat only if they looked, and declining to look is what Hand means. The
  // round-end reveal must not say "was shown" about a Hand game.
  const sawTalon = !isSkat || !!game?.looked;

  const onMessage = useCallback((msg) => {
    if (msg.type === "error") { setToast(msg.message || "error"); setConnecting(false); return; }
    if (msg.room) {
      setRoomData(msg.room);
      setConnecting(false);
      const tok = msg.room.reconnect_tokens?.[myId];
      if (tok) { try { localStorage.setItem(`dissonance_token_${msg.room.room_id}_${myId}`, tok); } catch {} }
      if (msg.room.room_id) {
        setRoomId(msg.room.room_id);
        pushPath(buildPath("dissonance", msg.room.room_id));
      }
      setScreen(msg.room.game ? "game" : "waiting");
    }
  }, [myId]);

  const { connected, connect, send: wsSend, disconnect, socketReady } = useSocket(onMessage);

  // ─── OFFLINE VS-AI ────────────────────────────────────────────────────────
  // Mounted by the shell with `offline` = a saved-game record (or its id): no
  // socket at all. `send` below routes the SAME message objects to the local
  // referee instead, so every call site in this file is unchanged and there is
  // one protocol rather than two.
  const offlineRef = useRef(offline);
  offlineRef.current = offline;
  const offRecRef = useRef(null);       // the live record (mutated by the driver)
  const offTokenRef = useRef(0);        // bumps on unmount → cancels stale bot loops

  const publishOffline = useCallback(async (rec, aiSearch) => {
    offRecRef.current = rec;
    const data = await dissonanceOfflineRoomData(rec, myId, authUser?.name);
    // The armed decision rides on roomData exactly as the server ships it, so
    // the pool effect below needs no offline branch at all.
    setRoomData(aiSearch ? { ...data, ai_search: aiSearch } : data);
  }, [myId, authUser?.name]);

  const pumpOfflineBot = useCallback(() => {
    const token = offTokenRef.current;
    const rec = offRecRef.current;
    if (!rec) return;
    runDissonanceBotLoop(rec, myId, publishOffline, () => offTokenRef.current === token)
      .catch((e) => console.debug("[dissonance offline-AI] bot loop:", e));
  }, [myId, publishOffline]);

  /* One `send` for both referees. Offline the move objects are identical —
     that is the whole point of the driver taking `engine.apply_move`'s own
     shapes — so this is a router, never a second protocol. */
  const send = useCallback((msg) => {
    if (!offlineRef.current) { wsSend(msg); return; }
    const rec = offRecRef.current;
    if (!rec) return;
    (async () => {
      if (msg.action === "move" || msg.action === "ai_move") {
        const isAi = msg.action === "ai_move";
        // A search answer that lands after the position moved on is DROPPED,
        // not played — the online staleness rule, which offline needs just as
        // much because the pool answers asynchronously.
        if (isAi && msg.decision !== rec.decisionSeq) return;
        const move = isAi
          ? (msg.move || { kind: "play", card: msg.card })
          : msg.move;
        const res = await applyOfflineDissonanceMove(rec, move, myId, { isAi });
        if (!res.ok) { setToast(res.err); return; }
        await publishOffline(res.rec, null);
        pumpOfflineBot();
        return;
      }
      if (msg.action === "abandon") {
        await publishOffline(await abandonOfflineDissonanceGame(rec), null);
        return;
      }
      // `start` and `client_ai_ready` have no offline meaning: there is no
      // lobby to start and nothing to tell a server about.
    })().catch((e) => setToast(String(e?.message || e)));
  }, [wsSend, myId, publishOffline, pumpOfflineBot]);

  useEffect(() => {
    if (!offline) return;
    let live = true;
    (async () => {
      try {
        const rec = typeof offline === "string" ? await loadOfflineDissonanceGame(offline) : offline;
        if (!rec || !live) return;
        offRecRef.current = rec;
        setScreen("game");
        setRoomId(rec.id);
        await publishOffline(rec, null);
        // The bot may be on turn already — it opens the bidding half the time.
        pumpOfflineBot();
      } catch (e) {
        setToast(String(e?.message || "Couldn't open the offline game"));
      }
    })();
    return () => { live = false; offTokenRef.current += 1; };
  }, [offline]); // eslint-disable-line react-hooks/exhaustive-deps

  const fetchGames = useCallback(() => {
    setLoadingGames(true);
    fetch(`${OT_HTTP}/games`).then((r) => r.json())
      .then((d) => { const g = d.games || []; setOpenGames(g); writeLobbyCache("dissonance", myId, "open", g); })
      .catch(() => {}).finally(() => setLoadingGames(false));
    if (authUser?.session_token) {
      const headers = { Authorization: `Bearer ${authUser.session_token}` };
      fetch(`${OT_HTTP}/games/mine`, { headers }).then((r) => r.json())
        .then((d) => { const g = d.games || []; setMyGames(g); writeLobbyCache("dissonance", myId, "mine", g); }).catch(() => {});
      fetchGameHistory(`${OT_HTTP}/games/history`, authUser)
        .then((d) => { const g = d.games || []; setHistory(g); writeLobbyCache("dissonance", myId, "history", g); }).catch(() => {});
    } else {
      setMyGames([]); setHistory([]);
      writeLobbyCache("dissonance", myId, "mine", []); writeLobbyCache("dissonance", myId, "history", []);
    }
  }, [authUser, myId]);

  // The skat price table is the server's, never a copy: /catalog hands over the
  // per-denomination bases so the "what clears this number" hint below is the
  // same arithmetic the engine validates with.
  const [catalog, setCatalog] = useState(null);
  // The set-score rate, read from the server's own catalog rather than written
  // as a literal: it has moved once (4 -> 5) and the Double's ramp is defined
  // on top of it. DECLARED HERE, not earlier: `catalog` is a `const` from
  // `useState`, so touching it above this line is a temporal dead zone -- which
  // throws at render and blanks the entire screen rather than failing softly.
  //
  // MINOR MODE has its own two prices (set rate 2, Null 6 -- re-anchored to a
  // scale whose payoffs run a quarter of classic's), so both are picked by the
  // room's mode. `game?.mode` is safely undefined outside a room, where
  // nothing renders either number.
  // THE PRICE LIST, off the catalog and out of `pricing.js` -- one mirror of
  // `engine._terms_for` for the whole client, because the paper scorecard needs
  // the same arithmetic and a second copy of it is exactly the drift that guard
  // exists to prevent. `game?.mode` is safely undefined outside a room, where
  // nothing renders a number.
  //
  // DECLARED AFTER `catalog`, not before: it is a `const` from `useState`, so
  // touching it above that line is a temporal dead zone -- which throws at
  // render and blanks the entire screen rather than failing softly.
  const prices = useMemo(() => contractPrices(catalog, game?.mode),
    [catalog, game?.mode]);
  const { short: shortRate, nullMake, dblShort, dblRamp } = prices;
  const priceContract = prices.price;
  /** The auction's own pricing: a bid is not doubled while it is being made. */
  const priceBid = (level, jump) => priceContract(level, jump, false);
  useEffect(() => {
    fetch(`${OT_HTTP}/catalog`).then((r) => r.json()).then(setCatalog).catch(() => {});
  }, []);

  useEffect(() => { if (screen === "lobby") fetchGames(); }, [screen, fetchGames]);
  // The game you just finished leaves Active and joins History the moment it
  // ENDS, not when the lobby next loads — see useFinishedGameSync (shared kit).
  useFinishedGameSync(roomData?.status === "over", roomData?.room_id, (rid) => {
    dropLobbyGame("dissonance", myId, "mine", rid, setMyGames);
    fetchGames();
  });
  useEffect(() => () => disconnect(), []); // eslint-disable-line

  // ── client-side (WASM) bot search ──────────────────────────────────────────
  // World-parallel: every worker searches the SAME decision from its own seed,
  // sampling its own deals, and returns per-move value SUMS. We add them by move
  // index — the index space is `State::legal`, a pure function of the position,
  // so index i is the same card everywhere — and hand the totals back to the
  // wasm to pick. The pick rule is NOT reimplemented here (see the worker).
  useEffect(() => {
    if (!roomData?.vs_ai || !CLIENT_AI_TIERS.includes(roomData?.ai_difficulty)
      || wasmPoolRef.current || typeof Worker === "undefined") return;
    const url = `${import.meta.env.BASE_URL}wasm/dissonance-worker.js`;
    // NEVER TAKE EVERY CORE. The solver is CPU-bound and a pool that pegs all of
    // them starves the browser's main/compositor/raster threads, so the board
    // stutters while the bot thinks. Only bites at <=4 cores; the cap dominates
    // above that. Two other games shipped without this rule for months.
    const cores = Math.max(1, Math.min((navigator.hardwareConcurrency || 4) - 1, 4));
    const makeWorker = () => {
      let w;
      try { w = new Worker(url, { type: "module" }); } catch { return null; }
      const pending = new Map();
      let resolveReady, nextId = 1;
      const ready = new Promise((res) => (resolveReady = res));
      w.onmessage = (e) => {
        const d = e.data || {};
        // `wire` is the artifact's protocol vintage (2 = speaks minor mode's
        // `even_val`). A cached worker from before the field resolves plain
        // booleans, which reads as wire 1 below — exactly right.
        if (d.ready !== undefined) { resolveReady(d.ready ? { wire: d.wire || 1 } : false); return; }
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
        // The pool's wire vintage is its WEAKEST member: a mixed pool would
        // answer a minor decision with only some workers' worlds, so the
        // announcement below has to promise no more than all of them speak.
        wasmWireRef.current = Math.min(...flags.filter(Boolean).map((f) => f.wire || 1));
        setWasmReady(true);
      } else {
        console.warn("[dissonance client-AI] no WASM workers loaded -> server bot");
      }
    });
    return () => { pool.forEach((wk) => wk.terminate()); wasmPoolRef.current = null; setWasmReady(false); };
  }, [roomData?.vs_ai, roomData?.ai_difficulty]);

  // The server disarms the client when its socket drops, so a reconnect MUST
  // re-announce or the room quietly serves the server bot for the rest of it.
  useEffect(() => { if (!connected) clientAiArmedRef.current = null; }, [connected]);
  useEffect(() => {
    if (wasmReady && connected && roomData?.room_id
      && clientAiArmedRef.current !== roomData.room_id) {
      clientAiArmedRef.current = roomData.room_id;
      // `wire` tells the server what this client's artifact speaks. A minor
      // room refuses to arm anything below 2 (the server-side half of the
      // fail-closed pair; the worker's own export probe is the other), so an
      // honest number here is what keeps a stale-wasm tab on the server bot
      // instead of searching the wrong game.
      send({ action: "client_ai_ready", wire: wasmWireRef.current });
    }
  }, [wasmReady, connected, roomData?.room_id, send]);

  // One armed decision at a time; the server re-ships it on every broadcast, so
  // this must be idempotent. Keyed by ROOM as well as decision number: the
  // counter restarts at 1 in a new room, so a bare number could collide with the
  // last one we answered and silently skip the bot's first card.
  useEffect(() => {
    const as = roomData?.ai_search;
    const pool = wasmPoolRef.current;
    if (!as || !wasmReady || !pool || pool.length === 0) return;
    const key = `${roomData.room_id}:${as.decision}`;
    if (aiDispatchRef.current === key) return;
    aiDispatchRef.current = key;
    // The seat's view AND the scoring rule it is playing for. The search
    // optimises the payoff the server will actually apply, not the trick points
    // that only measure it — which is what lets it duck for the Null
    // consolation, and lets a defender play to force one +2 trick on a declarer
    // who is ducking. The terms come straight from `engine.payoff_terms`.
    // `bid_prior` rides at the TOP level because the card play needs it too and
    // a play request carries no `auction` block to nest it in: the declarer won
    // an auction, so the worlds this searches must not hand them an average
    // hand. This list is a deliberate whitelist rather than a spread of `as` —
    // adding a field is how a new one reaches the worker, and forgetting is a
    // search that runs on a belief the server meant to correct.
    const view = JSON.stringify({ view: as.view, payoff: as.payoff,
                                  auction: as.auction, bid_prior: as.bid_prior });
    const t0 = performance.now();
    // The server's cap counts WORLDS in total, and worlds are summed across the
    // pool, so split it rather than handing every worker the whole budget.
    //
    // EXCEPT a TREE-searched auction decision (Expert), which goes to ONE
    // worker with the whole budget. Pooling sums per-option values, and for
    // Hard's linear pricing four workers' quarter-samples summed ARE one
    // combined sample — but a minimax tree is not linear in its worlds, and
    // four small trees summed were MEASURED weaker than one big one (pooled
    // 4x2: +0.14 ± 0.45 vs hard; one tree over the same 8 worlds: +1.36 ±
    // 0.48). The other workers idle for one bid; the card play still fans out.
    const solo = !!(as.auction && as.auction.search);
    const crew = solo ? [pool[0]] : pool;
    const perWorker = solo ? (as.max_worlds || 8)
      : Math.max(1, Math.ceil((as.max_worlds || 8) / pool.length));
    (async () => {
      try {
        // An AUCTION decision ranks the options the server priced; a card
        // decision ranks the legal cards. Same pooling either way — both index
        // spaces are the server's or a pure function of the position, so index
        // i means the same thing in every worker.
        const kind = as.auction ? "bid" : "search";
        const parts = await Promise.all(crew.map((wk, i) => wk.request({
          kind, view, budget: as.budget_ms, maxWorlds: perWorker,
          seed: ((as.decision * 2654435761) ^ (i * 40503 + 1)) >>> 0,
        }).catch(() => null)));
        if (as.auction) {
          const ok = parts.filter((p) => p && p.sums && p.sums.length);
          if (!ok.length) return;
          const k = ok[0].sums.length;
          const sum = new Array(k).fill(0);
          let worlds = 0;
          for (const p of ok) {
            if (p.sums.length !== k) continue;   // stale worker — see below
            for (let a2 = 0; a2 < k; a2++) sum[a2] += p.sums[a2];
            worlds += p.worlds;
          }
          let best = 0;
          for (let a2 = 1; a2 < k; a2++) if (sum[a2] > sum[best]) best = a2;
          const opt = as.auction.options[best];
          // Every branch sends a move the SERVER handed us; nothing here knows
          // what a bid or a declaration is.
          //   - Kontra/Re: the option is the standing contract and the decision
          //     is the SIGN. Declining is worth exactly zero, so a value at or
          //     below zero takes the `decline` move.
          //   - Bidding: PASSING IS ONE OF THE PRICED OPTIONS now, worth minus
          //     what the standing contract pays the opponent, so the argmax
          //     above already covers it and nothing here compares against zero.
          //     The old `!(sum[best] > 0) -> pass` rule is kept only as the
          //     fallback for a server that did not price the pass (or a cached
          //     wasm that dropped the flag): it is what made a sacrifice
          //     unreachable, since a sacrifice is by definition a contract that
          //     prices negative, bought because passing prices worse.
          let move = opt?.move;
          const priced = as.auction.options.some((o) => o?.move?.kind === "pass");
          if (opt?.decline && !(sum[best] > 0)) move = opt.decline;
          else if (!priced && as.auction.pass && !(sum[best] > 0)) move = as.auction.pass;
          if (!move) return;
          console.info(`[oddtrick client-AI] ${ok.length} workers, ${worlds} worlds, `
            + `${k} options in ${Math.round(performance.now() - t0)}ms ->`, move);
          const wait0 = CLIENT_AI_MIN_MS - (performance.now() - t0);
          if (wait0 > 0) await new Promise((r) => setTimeout(r, wait0));
          send({ action: "ai_move", decision: as.decision, move });
          return;
        }
        const good = parts.filter((p) => p && p.moves && p.sum);
        if (!good.length) return;              // every worker failed -> server bot
        const k = good[0].moves.length;
        const sum = new Array(k).fill(0);
        let worlds = 0;
        for (const p of good) {
          // Same view in => same legal list, so a length mismatch means a stale
          // worker. Pooling it would add up DIFFERENT cards' values.
          if (p.sum.length !== k || p.moves.length !== k) continue;
          for (let a = 0; a < k; a++) sum[a] += p.sum[a];
          worlds += p.worlds;
        }
        const res = await pool[0].request({ kind: "pick", moves: good[0].moves, sum });
        const card = res?.card;
        if (typeof card !== "number" || card < 0) return;
        // Every failure above is a silent return that hands the decision back to
        // the server, so the ONE thing that says the client tier is actually
        // running is this line.
        console.info(`[dissonance client-AI] ${good.length} workers, ${worlds} worlds `
          + `in ${Math.round(performance.now() - t0)}ms -> card ${card}`);
        // A flat floor per move: a fast machine waits, a slow one does not, so
        // the bot's pace never leaks the device. A submit that lands after the
        // decision was superseded is harmless — the server drops it as stale.
        const wait = CLIENT_AI_MIN_MS - (performance.now() - t0);
        if (wait > 0) await new Promise((r) => setTimeout(r, wait));
        send({ action: "ai_move", decision: as.decision, card, worlds });
      } catch {}
    })();
  }, [roomData, wasmReady, send]);
  useEffect(() => { if (toast) { const t = setTimeout(() => setToast(""), 2600); return () => clearTimeout(t); } }, [toast]);
  // A fresh contract clears any half-built bid. In skat mode the standing bid
  // is `value`, not `level` — `level` stays 0 until the declaration.
  useEffect(() => {
    setBidLevel(null); setBidDenom(null); setBidValue(null);
  }, [game?.auction?.level, game?.auction?.value, game?.auction?.to_act,
      game?.redeals]);
  // The completed trick stays on the table for a beat. The server clears `led`
  // the instant the second card lands, so without this the trick you just lost
  // (or won) vanishes mid-blink and the only record is the side panel — you
  // never actually SEE the two cards together.
  //
  // `over` is in here with `play` ON PURPOSE: the thirteenth trick and the +2
  // that breaks a Null both END the game in the same message that completes the
  // trick, so a hold that stops at `play` skips the one trick a player most
  // wants to see and swaps straight to the result panel. Measured: every other
  // trick held 655–700ms and the last one held 0.
  //
  // **useLayoutEffect, NOT useEffect — the hold has to be armed BEFORE the
  // browser paints.** The last card of a round arrives in a message that has
  // already ended the game, so that render has `phase === "over"` while
  // `heldTrick` is still null from the previous trick — and the result branch
  // is keyed on exactly that pair. A passive effect runs AFTER paint, so the
  // "contract made" panel got a frame of its own before the hold put the final
  // trick back: result -> the trick you just played -> result. Reported from a
  // phone as "a flash right as I press the last card, before the card shows up
  // in the middle", which is precisely that ordering.
  //
  // It hid from four played-out games at desk speed because the paint/effect
  // gap is ~0 on fast hardware. Reproduced by throttling the CPU 6x, where it
  // measures ONE FRAME (8ms) against the 711ms hold that follows it.
  // useLayoutEffect fires synchronously after the DOM mutation and before the
  // paint, so the intermediate state can never reach the screen. Nothing else
  // changes: same deps, same timer, same 700ms.
  const [heldTrick, setHeldTrick] = useState(null);
  const holdTimer = useRef(null);
  const wasPlaying = useRef(false);
  useLayoutEffect(() => {
    const playing = game?.phase === "play";
    // Only a game that ENDED under us gets the over-hold. Opening a finished
    // room from the lobby would otherwise replay its last trick at you before
    // showing the result, and a forfeit has no trick to hold at all.
    const ending = game?.phase === "over" && wasPlaying.current;
    wasPlaying.current = playing;
    if (!playing && !ending) { setHeldTrick(null); return; }
    const done = lastTrick(game);
    if (!done) { setHeldTrick(null); return; }
    setHeldTrick(done);
    holdTimer.current = setTimeout(() => setHeldTrick(null), TRICK_HOLD_MS);
    return () => clearTimeout(holdTimer.current);
  }, [game?.trick, game?.phase]);
  // Swap-phase selection (declarer only).
  const [swapTake, setSwapTake] = useState(null);
  const [swapGive, setSwapGive] = useState(null);
  // QUARTET's commit phase: which of my two hands leads, and the one optional
  // card swapped between them. `null` lead means nothing picked yet -- the go
  // button stays disabled rather than defaulting, because which hand leads is
  // a real decision and a silent default would make it look like it is not.
  const [commitLead, setCommitLead] = useState(null);
  const [commitTake, setCommitTake] = useState(null);
  const [commitGive, setCommitGive] = useState(null);

  //: WHERE EACH SEAT SITS IN THIS TRICK, 1..4. Play goes round the table from
  //: whoever leads (`engine.trick_order`), so a seat's number is just its
  //: distance from the leader -- and because the winner of a trick leads the
  //: next one, the four numbers RE-ORDER every trick. That is the single
  //: hardest thing to see on a four-hand board: with two seats "they go, then
  //: you" needs no explanation, with four it does.
  //:
  //: During the COMMIT phase it previews the choice being made rather than the
  //: standing one, so picking a leading hand renumbers the board live.
  //:
  //: DECLARED HERE, BELOW `commitLead`, AND THAT PLACEMENT IS THE WHOLE POINT.
  //: It first sat with the other quartet derivations 400 lines up, which reads
  //: `commitLead` before its `const` -- a temporal dead zone throw that blanked
  //: the whole app with "Cannot access before initialization". A `const` is not
  //: hoisted the way a function is.
  const qLead = !isQuartet ? null
    : game?.phase === "commit" ? commitLead
      : game?.phase === "play" ? game.leader : null;
  const orderOf = (pos) => (qLead === null || qLead === undefined ? null
    : ((pos - qLead + 4) % 4) + 1);
  useEffect(() => { setSwapTake(null); setSwapGive(null); }, [game?.phase]);
  /* THE OPTIMISTIC CARD (see `doPlay`). Cleared by ANY authoritative change,
     which is what keeps it honest: the server's next state is the truth
     whether it accepted the move or refused it. `plays.length` alone is not
     enough — the play that COMPLETES a trick clears `plays` back to empty, so
     the history length and the trick number are in the key too. */
  const [pendingPlay, setPendingPlay] = useState(null);
  useEffect(() => { setPendingPlay(null); }, [
    game?.phase, game?.trick, game?.plays?.length, game?.history?.length,
    game?.hand?.length,
  ]);
  // Entering the declaration: start on the cheapest denomination the bid allows.
  useEffect(() => {
    const opts = game?.declare?.denoms;
    if (!opts?.length) return;
    const best = opts.reduce((a, b) => (b.min_level < a.min_level ? b : a));
    setDeclDenom(best.denom); setDeclLevel(best.min_level);
    setDeclSharp(false); setDeclOpen(false);
  }, [game?.phase, game?.declare?.bid]);

  const createGame = (vsAi, difficulty) => {
    if (vsAi) rememberDiff(difficulty);   // this game's tier is the next modal's default
    const rid = roomCode();
    setConnecting(true); setShowCreate(false);
    connect(`${OT_WS}/${rid}/${myId}`, {
      action: "create", name: authUser?.name || "Player",
      vs_ai: vsAi, ai_difficulty: difficulty, mode: newMode,
    });
  };
  const joinGame = (rid) => {
    setConnecting(true);
    connect(`${OT_WS}/${rid}/${myId}`, {
      action: "join", name: authUser?.name || "Player",
      session_token: authUser?.session_token || null,
    });
  };
  const resumeGame = (rid) => {
    setConnecting(true);
    let tok = null;
    try { tok = localStorage.getItem(`dissonance_token_${rid}_${myId}`); } catch {}
    if (tok) connect(`${OT_WS}/${rid}/${myId}`, { action: "reconnect", token: tok });
    else if (authUser?.session_token) {
      connect(`${OT_WS}/${rid}/${myId}`, { action: "auth_reconnect", session_token: authUser.session_token });
    } else joinGame(rid);
  };
  const cancelGame = (rid) => {
    if (!authUser?.session_token) return;
    fetch(`${OT_HTTP}/games/${rid}`, {
      method: "DELETE", headers: { Authorization: `Bearer ${authUser.session_token}` },
    }).then(() => fetchGames()).catch(() => {});
  };
  const leaveToLobby = () => {
    // OFFLINE THERE IS NO LOBBY TO GO BACK TO -- the shell owns the URL
    // (/offline/<id>) and the hub is the screen behind this one, so hand the
    // exit back rather than routing to a lobby that needs the backend.
    if (offlineRef.current) { offTokenRef.current += 1; onExit?.(); return; }
    disconnect(); setRoomId(""); setRoomData(null); setScreen("lobby");
    pushPath(buildPath("dissonance", null));
  };

  // ── URL deep entry + back/forward (this component owns /dissonance/<ROOM>) ──
  useEffect(() => {
    if (didInitRef.current) return;
    didInitRef.current = true;
    const r = parsePath();
    if (r.game === "dissonance" && r.room) resumeGame(r.room);
  }, []); // eslint-disable-line
  popHandlerRef.current = (r) => {
    if (r.game !== "dissonance") return;
    if (r.room && r.room !== roomIdRef.current) resumeGame(r.room);
    else if (!r.room && roomIdRef.current) leaveToLobby();
  };
  useEffect(() => subscribe((r) => popHandlerRef.current(r)), []); // eslint-disable-line

  // Auto-reconnect while in a live game. Load-bearing for vs-bot: the server
  // re-drives the bot's turn on reconnect, which is what unsticks a game whose
  // scheduler died with the socket.
  const inLiveGame = !!roomId && (screen === "game" || screen === "waiting")
    && roomData?.status !== "over";
  const attemptReconnect = useCallback(() => {
    if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; }
    const rs = socketReady();
    if (rs === 0 || rs === 1) { reconnTimer.current = setTimeout(attemptReconnect, 3000); return; }
    let tok = null;
    try { tok = localStorage.getItem(`dissonance_token_${roomId}_${myId}`); } catch {}
    if (tok) { setReconnecting(true); connect(`${OT_WS}/${roomId}/${myId}`, { action: "reconnect", token: tok }); }
    reconnTries.current += 1;
    reconnTimer.current = setTimeout(attemptReconnect, Math.min(2000 * reconnTries.current, 8000));
  }, [roomId, myId, connect, socketReady]);
  useEffect(() => {
    const clear = () => { if (reconnTimer.current) { clearTimeout(reconnTimer.current); reconnTimer.current = null; } };
    if (connected || !inLiveGame) {
      clear(); reconnTries.current = 0;
      if (connected) setReconnecting(false);
      return clear;
    }
    if (!reconnTimer.current) attemptReconnect();
    return clear;
  }, [connected, inLiveGame, attemptReconnect]);

  const doBid = () => {
    if (bidLevel === null || bidDenom === null) return;
    send({ action: "move", move: { kind: "bid", level: bidLevel, denom: bidDenom } });
  };
  const doPass = () => send({ action: "move", move: { kind: "pass" } });
  /* THE CARD LEAVES YOUR HAND ON THE CLICK, not on the server's answer.
     A play is a round trip — send, validate, broadcast — so until the room
     came back the board did nothing at all: the card you clicked sat in the
     hand, unmoved, for as long as the network took. That is the lag, and no
     amount of CSS timing touches it, because nothing was animating yet.
     The optimistic card is rendered from `pendingPlay`: dropped from the hand
     and drawn into the trick immediately. The SERVER still decides — this
     never sends anything different, and the very next broadcast overwrites
     it wholesale (the effect below clears it on any state change), so a move
     the engine refuses simply snaps back. */
  const doPlay = (card) => {
    setPendingPlay(card);
    send({ action: "move", move: { kind: "play", card } });
  };
  const doSwap = (take, give) => send({ action: "move", move: { kind: "swap", take, give } });
  const doMove = (move) => send({ action: "move", move });
  const doValueBid = () => {
    if (bidValue === null) return;
    doMove({ kind: "bid", value: bidValue });
  };
  const doDeclare = (denom, level, sharp, open) =>
    doMove({ kind: "declare", denom, level, sharp, open });

  // ── lobby ────────────────────────────────────────────────────────────────
  if (screen === "lobby") {
    if (connecting) {
      return <div className="dis"><style>{styles}</style><LobbyLoading label="Connecting…" /></div>;
    }
    const openCol = (
      <div className="lby-col-open">
        <LobbySectionHd title="Open Games" note={`${visibleOpenGames.length} waiting`} />
        <div className="lby-list">
          {visibleOpenGames.length === 0 && <LobbyEmpty>No open games — create one.</LobbyEmpty>}
          {visibleOpenGames.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-card-info">
                <div className="lby-card-title">
                  {g.host_id === myId ? "Your game" : `${g.host_name || "Player"}'s game`}
                  <span className="lby-seats">1/2</span>
                </div>
                <div className="lby-card-meta">{g.id} · {timeAgo(g.created_at)}<ModeBadge mode={g.mode} /></div>
              </div>
              <div className="lby-card-actions">
                {/* Return, then Cancel — the shape the other six use for a room you
                    host. Cancel alone left a host who navigated away with no way back
                    into their own waiting room, and against six siblings that all show
                    the pair it read as a button that failed to render. */}
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
    );
    const activeCol = (
      <div className="lby-col-active">
        <LobbySectionHd title="Active Games" note={`${activeMine.length} in progress`} />
        <div className="lby-list">
          {activeMine.length === 0 && <LobbyEmpty>No games in progress.</LobbyEmpty>}
          {activeMine.map((g) => (
            <div key={g.id} className="lby-card">
              <div className="lby-card-info">
                <LobbyMatchup placeholder="Waiting…" seats={[
                  { name: g.player1_name, you: g.you_are_p1 },
                  { name: g.player2_name, you: !g.you_are_p1 },
                ]} />
                <div className="lby-card-meta">{g.id} · {timeAgo(g.updated_at)}<ModeBadge mode={g.mode} /><LobbyBotTier tier={g.ai_difficulty} labels={BOT_TIER_NAMES} /></div>
              </div>
              {/* THE TURN PILL LIVES ON THE ACTIONS RAIL, beside Resume, which is
                  where the other six put it. Inline after the title it floated in
                  the middle of the row and left the right cluster under-weighted,
                  so a glance down the column could not answer "which of these is
                  waiting on me" without reading each one. */}
              <div className="lby-card-actions">
                {g.your_turn ? <TurnBadge mine>Your turn</TurnBadge> : <TurnBadge>Their turn</TurnBadge>}
                <LobbyAction onClick={() => resumeGame(g.id)}>Resume</LobbyAction>
              </div>
            </div>
          ))}
        </div>
      </div>
    );
    const histCol = (
      <div className="lby-col-history">
        <LobbySectionHd title="History" note={`${visibleHistory.length} finished`} />
        <div className="lby-list" ref={historyMore}>
          {visibleHistory.length === 0 && <LobbyEmpty>No finished games yet.</LobbyEmpty>}
          {historyShown.map((g) => {
            const line = histLine(g);
            return (
              <div key={g.id} className="lby-card lby-card-hist">
                <div className="lby-card-info">
                  <div className="lby-card-title">
                    {/* A match CAN end level — a forfeit banks whatever the
                        round was worth and then closes the match regardless of
                        the target — so "not won" is not the same as lost. `tie`
                        is the shared kit's own class, which CoC and Dontminion
                        already use; this game had no third state before.
                        The OUTCOME comes off the row (`tie`/`you_won`), not
                        from comparing the two numbers next to it: walking out
                        is a loss at any standing, including a level one. The
                        `??` is the fallback for a server that predates the
                        field, where the comparison was the whole answer. */}
                    {(() => {
                      const tie = g.tie ?? (g.your_score === g.opp_score);
                      return (
                        <span className={`hist-result ${tie ? "tie" : g.you_won ? "won" : "lost"}`}>
                          {tie ? "Tie" : g.you_won ? "Won" : "Lost"}
                        </span>
                      );
                    })()}
                    <span className="hist-scores"> vs {g.opp_name}{" "}
                      <span className="hist-score-num">{g.your_score}–{g.opp_score}</span>
                    </span>
                    <ModeBadge mode={g.mode} />
                  </div>
                  {/* The score above is the MATCH, so the meta line says what it
                      took. A single round is the one case where the contract is
                      the whole story — over ten deals it is just the last one,
                      which read as the headline and was never true. */}
                  <div className="lby-card-meta">
                    {line}{line ? " · " : ""}{timeAgo(g.updated_at)}
                    <LobbyBotTier tier={g.ai_difficulty} labels={BOT_TIER_NAMES} />
                  </div>
                </div>
              </div>
            );
          })}
        </div>
      </div>
    );
    return (
      <div className="dis">
        <style>{styles}</style>
        <LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} />} />
        <div className="lby-page"><div className="lby-page-in">
        <LobbyHero game="dissonance">
        <LobbyCreateRow
          onCreate={() => setShowCreate(true)}
          onJoin={(code) => joinGame(code.toUpperCase())}
          onRefresh={fetchGames}
          onRules={() => setShowRules(true)}
          refreshing={loadingGames}
          extra={(
            <button type="button" className="lby-extra" aria-label="Scorecard"
              onClick={() => setShowCard(true)}>
              <span className="lby-rules-ic" aria-hidden="true">{SCORECARD_GLYPH}</span>
              <span className="lby-btn-label">Scorecard</span>
            </button>
          )}
        />
        </LobbyHero>
        {/* `key`, not `id` — LobbyTabs reads `t.key`, and the grid's `tab-<key>`
            class is what the CSS hides the other columns off. With `id` the bar
            rendered but every click set the tab to undefined, and `data-tab`
            matched no rule, so the phone lobby showed all three sections at once
            and the bar did nothing at all. */}
        <LobbyTabs value={lobbyTab} onChange={setLobbyTab} tabs={[
          { key: "open", label: "Open", count: visibleOpenGames.length || null },
          { key: "active", label: "Active", count: activeMine.length || null },
          { key: "history", label: "History", count: visibleHistory.length || null },
        ]} />
        <div className={`lby-cols tab-${lobbyTab}`}>
          {openCol}{activeCol}{histCol}
        </div>
        </div></div>
        {showCreate && (
          <CreateModal title="New Game" onClose={() => setShowCreate(false)}>
            <CmRow label="Opponent">
              <CmSeg value={createOpp} onChange={setCreateOpp} options={[
                { value: "friend", label: "VS Friend", title: "Head-to-head — one friend joins from the lobby (or your room code)" },
                { value: "ai", label: "VS AI", title: "Starts instantly against the bot" },
              ]} />
            </CmRow>
            {createOpp === "ai" ? (
              <CmRow label="AI Difficulty">
                <CmSeg value={createDiff} onChange={setCreateDiff}
                  options={BOT_TIERS.map((t) => ({ value: t.id, label: t.name, title: t.desc }))} />
              </CmRow>
            ) : (
              <span className="cm-hint">Dissonance is head-to-head — one friend joins from the lobby.</span>
            )}
            <CmRow label="Mode">
              <CmSeg value={newMode} onChange={setNewMode}
                options={modeOptions.map((m) => ({ value: m.id, label: m.label, title: m.title }))} />
              <span className="cm-hint">
                {newMode === "skat"
                  ? "Bid a number; name the game only after you win it. Then Hand, Sharp, Open — and their Kontra."
                  : newMode === "minor"
                    ? "Classic's auction, but even tricks pay only +1 — contracts run 1–6, every one is a fight, and the match plays to 25."
                    : "Bid a level and a denomination, ranked ♣ < ♦ < ♥ < ♠ < NT."}
              </span>
            </CmRow>
            <div className="cm-footer">
              <span className="cm-summary">
                Creating: <b>{createOpp === "ai"
                  ? `${BOT_TIERS.find((t) => t.id === createDiff)?.name || createDiff} bot`
                  : "vs Friend"}</b>
                {", "}<b>{MODE_LABEL[newMode]}</b>{newMode === "minor" ? " mode" : " auction"}
              </span>
              <button type="button" className="cm-create"
                onClick={() => createGame(createOpp === "ai", createDiff)}>
                Create Game
              </button>
            </div>
          </CreateModal>
        )}
        {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
        {showCard && (
          <DissonanceScorecard catalog={catalog} onClose={() => setShowCard(false)} />
        )}
        {toast && <div className="toast">{toast}</div>}
      </div>
    );
  }

  // ── waiting room ─────────────────────────────────────────────────────────
  // `WaitingRoom` in shared/lobby.jsx. This screen used to say "Share this code, or
  // the link in your address bar" — the only game that knew the link was the thing
  // worth sharing, and it still made the player go and find it themselves.
  if (screen === "waiting" || !game) {
    return (
      <div className="dis">
        <style>{styles}</style>
        <WaitingRoom
          game="dissonance" roomId={roomId}
          players={players} hostId={roomData?.host} myId={myId}
          min={2} max={2}
          note={`${MODE_LABEL[roomData?.mode] || MODE_LABEL.classic} — two players, one deck.`}
          user={authUser}
          onLeave={leaveToLobby}
          onRules={() => setShowRules(true)}
          onStart={() => send({ action: "start" })} />
        {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
        {toast && <div className="toast">{toast}</div>}
      </div>
    );
  }

  // ── game ─────────────────────────────────────────────────────────────────
  const oppSeat = 1 - mySeat;
  // POSITIONS, not just seats: 2 is the dummy, which belongs to no pid at all.
  // Naming it after its owner is what makes the board readable -- "Dummy
  // (Alice's)" says who is choosing its cards, which is the whole mechanic.
  const nameOf = (seat) => {
    if (seat === DUMMY_POS && game?.dummy) {
      const owner = players[seats[game.dummy_seat]];
      return owner ? `Dummy (${owner}'s)` : "Dummy";
    }
    // QUARTET: four POSITIONS, two players. A position names the player whose
    // side it is on, and the two hands they command are told apart by
    // "opposite" rather than by number — the board already shows which is
    // which by where it sits, and a bare "seat 2" means nothing to a player.
    if (isQuartet) {
      const who = players[seats[seat % QUARTET_HANDS]]
        || (seat % QUARTET_HANDS === mySeat ? "You" : "Opponent");
      return seat >= QUARTET_HANDS ? `${who} — opposite` : who;
    }
    return players[seats[seat]] || (seat === mySeat ? "You" : "Opponent");
  };
  const opt = game.options || { bids: [], may_pass: false };
  const bids = opt.bids || [];
  // Skat's price table, straight off /catalog — absent until it lands, which
  // only costs the "what clears this number" hint.
  const skatBases = catalog?.skat_bases || [];
  const ct = game.contract || {};
  const prev = lastTrick(game);
  // THE LEVEL PAD IS THE WHOLE LADDER, ALWAYS, and the illegal rungs are
  // DISABLED rather than absent. It used to render only the legal set, so the
  // pad shrank and re-flowed after every bid: the key under your thumb was a
  // different number a moment later, which on a phone is a misbid waiting to
  // happen. The denominations were already drawn this way (all five, disabled
  // when they do not apply) -- this makes the two rows one keypad in behaviour
  // as well as in looks.
  //
  // Off `/catalog`'s per-mode ceiling, with the legal set as the fallback, so
  // a room whose catalog has not landed yet still shows exactly what it can
  // bid rather than an empty pad.
  const ladderTop = catalog?.max_levels?.[game?.mode]
    ?? catalog?.max_level
    ?? Math.max(1, ...bids.map((b) => b[0]));
  const bidLevels = Array.from({ length: ladderTop }, (_, i) => i + 1);
  const levelOk = (l) => bids.some((b) => b[0] === l);
  const denomOkAt = (l, d) => bids.some((b) => b[0] === l && b[1] === d);
  const bidReady = bidLevel !== null && bidDenom !== null && denomOkAt(bidLevel, bidDenom);
  const legal = new Set(game.legal || []);
  const res = game.result;
  // A round that stopped early banked the SCORE but not the final tally: the
  // contract was already safe, and the tricks nobody played would still have
  // moved the trick points. Printing the running total as if it were the final
  // one reads as a miscount, so say what is actually true — at least this many.
  //
  // `ended_early` is always false while overtricks pay (every trick moves the
  // score, so no round stops short) — kept because the engine's early end is
  // SHELVED rather than removed, and a stored result from before the bonus can
  // still carry it. See `_score_is_settled`.
  const scored = (n) => (res?.ended_early ? `at least ${n}` : `${n}`);
  // THE BEAT BLOCKS PLAY, and that is what makes it a beat rather than a race.
  // The hold is 700ms and a trick takes ~600ms at full tilt, so a player who
  // answers before it expires was leading the NEXT trick behind a screen still
  // showing the last one: their card sat invisible, the opponent's reply landed
  // inside the same window, and the two finished tricks ran together with a
  // single 18ms frame between them (measured). Nothing is swallowed — a card
  // with no click handler also loses its `.play` affordance, so during the hold
  // the hand plainly is not offering itself.
  const canPlay = myTurn && !heldTrick;

  const trickCards = (() => {
    // A just-finished trick outranks the next lead: both cards stay up until
    // the hold expires, so the trick is always seen complete — including the
    // one that ends the game, which is why this is checked before the phase.
    if (heldTrick) {
      return heldTrick.plays.map((p) => ({ seat: p[0], c: p[1], won: p[0] === heldTrick.winner }));
    }
    if (game.phase !== "play") return [];
    // Straight off the wire: the engine keeps the in-progress trick as
    // [position, card] in play order, so a three-card trick needs no
    // reconstruction here and the two shapes share one path.
    if (game.plays?.length) {
      return game.plays.map((p) => ({ seat: p[0], c: p[1] }));
    }
    if (game.led === null || game.led === undefined) return [];
    return [{ seat: game.leader, c: game.led }];
  })();
  /* WHICH MIDDLE THE BOARD IS SHOWING, as a class rather than as `:has()` on
     the table (see the note by `.dis-main`). Derived from the SAME conditions
     the middle's ternary chain branches on, in the same order:
       * the round-ended net and the round report both render `.dis-result`;
       * every auction-family phase renders `.dis-auction`;
       * everything else — play, and the completed-trick hold, which keeps the
         board up after the phase has already flipped to `over` — renders the
         trick plus `.dis-playside`.
     That last case is why this cannot key on the phase alone, and it is the
     bug the `:has()` version was written to avoid: a phase-keyed budget
     shrank the cards for exactly that beat. `screens.mjs` asserts the class
     and the rendered child agree, so the two cannot drift. */
  // Every phase whose middle renders `.dis-auction`. `commit` is quartet's
  // stage-two declaration and belongs here for the same reason `swap` does --
  // the rail keys on this to lay the board out, and a phase left off it lays
  // out as if the trick were on the felt.
  const AUCTION_PHASES = ["auction", "commit", "swap", "talon", "declare",
                          "double", "kontra", "re"];
  const railKind = (game.phase === "over" && !heldTrick) ? "result"
    : AUCTION_PHASES.includes(game.phase) ? "auction"
      : "play";

  /* THE OPTIMISM IS ONLY APPLIED WHERE THE RESULT IS KNOWN. A card from the
     hand always is. A PILE top is not: uncovering reveals the card underneath,
     and on an outer pile the client does not know it — rendering that pile
     early would draw a card BACK for one frame and then the real face, which
     is a worse artifact than the wait it removes. So a pile play is optimistic
     only when the new top is already known (the middle pile) or there is no
     card under it at all. */
  const optimisticCard = (() => {
    if (pendingPlay === null || pendingPlay === undefined) return null;
    if ((game.hand || []).includes(pendingPlay)) return pendingPlay;
    const p = (game.piles?.[mySeat] || []).find((x) => x?.top === pendingPlay);
    if (!p) return null;
    return p.n === 1 || (p.under !== null && p.under !== undefined) ? pendingPlay : null;
  })();
  /* ...and the card goes into the trick until the room confirms it. Appended
     rather than merged: `trickCards` is built from the wire, so the moment the
     server's copy arrives the pending one is cleared and this stops firing.
     Guarded on the card not already being there, so a broadcast landing
     mid-render cannot double it. */
  if (optimisticCard !== null && !trickCards.some((t) => t.c === optimisticCard)) {
    trickCards.push({ seat: mySeat, c: optimisticCard });
  }

  /* WHAT THE TRICK ON THE TABLE IS WORTH — one derivation, rendered beside
     the cards it prices. Parity rooms label a trick with its fixed value; a
     card-scored room cannot until every card is down, so mid-trick it shows
     the sum SO FAR (the cards already played) and the held beat shows what
     the trick really paid. Null when there is nothing to price — a
     card-scored lead nobody has answered yet, or no trick at all. */
  const trickVal = (() => {
    const fmt = (v) => (v > 0 ? `+${v}` : `−${Math.abs(v)}`);
    if (heldTrick) return { v: heldTrick.value, label: fmt(heldTrick.value) };
    if (game.phase !== "play") return null;
    if (cardPts(game)) {
      if (game.led === null || game.led === undefined) return null;
      const v = cardVal(game, game.led);
      return { v, label: `${fmt(v)} so far` };
    }
    const v = game.trick_value;
    if (v === null || v === undefined) return null;
    return { v, label: fmt(v) };
  })();

  return (
    // `dis-cardpts` is what turns the per-card worth chips on: skat scores
    // captured cards (2026-08-09), and a board that did not say which cards
    // are the +2s would be a memory quiz, not a card game.
    /* `dis-game` marks the GAME screen specifically -- `.dis` is also the
       lobby's root, and the desktop rules below lock this screen to the
       viewport so the board never scrolls. */
    <div className={`dis dis-game${cardPts(game) ? " dis-cardpts" : ""}`}>
      <style>{styles}</style>
      <LobbyHeader title="Dissonance" menu={<OddMenu onLeave={leaveToLobby}
        onRules={() => setShowRules(true)}
        onAbandon={game.phase !== "over" ? () => setConfirmAbandon(true) : null} />}
        user={authUser?.name ? <span className="lby-head-name">{authUser.name}</span> : null} />
      {reconnecting && <div className="banner">Reconnecting…</div>}
      {/* `dis-has-match` and the table's `dis-rail-*` below are what the
          desktop grid keys on. They used to be `:has(> .dis-side-match)` and
          `:has(> .dis-playside)` — correct, and cheap in Chrome, but `:has()`
          sits on the ANCESTORS of every card and Firefox re-evaluates it far
          less cheaply, which is where "the hover is laggy in Firefox but fine
          elsewhere" comes from: a :hover on a card can invalidate the whole
          subtree those selectors guard. The renderer already knows both facts,
          so it says them. */}
      <div className={`dis-main${game.match ? " dis-has-match" : ""}`}>
        {/* `dis-3seat` is what re-derives the card size: the height budget
            divides by the number of CARD ROWS, and a dummy table has six
            where two seats have four. */}
        <div className={`dis-table ph-${game.phase} dis-rail-${railKind}`
          + (game.dummy ? " dis-3seat" : "")
          + (isQuartet ? " dis-4seat" : "")}>
          {/* opponent */}
          <div className={`dis-seat${isQuartet ? " dis-qtheirs" : ""}`}>
            <div className="dis-seatname">
              <b>{nameOf(oppSeat)}</b>
              <OrderPip n={orderOf(oppSeat)} />
              <span>{game.pts[oppSeat] >= 0 ? "+" : ""}{game.pts[oppSeat]} pts</span>
            </div>
            <div className="dis-hand">
              {/* Open: the declarer bought a multiplier by playing face up, so
                  their real cards are on the table from trick 1. */}
              {game.opp_hand
                ? sortHand(game.opp_hand).map((c) => <Card key={c} c={c} />)
                : Array.from({ length: game.opp_hand_n }, (_, i) => <Card key={i} c={null} />)}
            </div>
            {game.opp_hand && (
              <div className="muted" style={{ fontSize: "0.72rem" }}>Open — played face up</div>
            )}
            <div className="dis-piles">
              {game.piles[oppSeat].map((p, i) => <Pile key={i} pile={p} />)}
            </div>
          </div>

          {/* QUARTET: THE OPPONENT'S SECOND HAND, face down like their first.
              Both of their hands are hidden, and that is the whole reason
              this mode has finesses: a finesse is a guess about WHICH of two
              hidden hands holds a card, so publishing either one would delete
              it. All the board can show is the count, which is public in any
              card game because both players can count. */}
          {isQuartet && (
            <div className="dis-seat dis-qopp">
              <div className="dis-seatname">
                <b>{nameOf(oppSeat + QUARTET_HANDS)}</b>
                <OrderPip n={orderOf(oppSeat + QUARTET_HANDS)} />
                {game.to_play === oppSeat + QUARTET_HANDS && game.phase === "play"
                  && <span className="muted">to play</span>}
              </div>
              <div className="dis-hand">
                {Array.from({ length: game.hand_n?.[oppSeat + QUARTET_HANDS] ?? 0 },
                  (_, i) => <Card key={i} c={null} />)}
              </div>
            </div>
          )}

          {/* THE DUMMY — a third hand, face up, played by the declarer. It
              sits between the opponent and the trick because that is where it
              plays from: second, every trick, whoever led. Its cards get the
              same `play` affordance as your own when it is your turn to move
              for it, so commanding two hands is one uninterrupted gesture
              rather than a mode switch. Its PILES are dealt like anyone's, so
              its outer bottoms are face down here too — the dummy is open,
              not solved. */}
          {game.dummy && (
            <div className={`dis-seat dis-dummy${dummyIsMine ? " mine" : ""}`}>
              <div className="dis-seatname">
                <b>{nameOf(DUMMY_POS)}</b>
                {dummyToPlay && <span className="dis-yourturn">to play</span>}
              </div>
              <div className="dis-hand">
                {sortHand(game.dummy).map((c) => (
                  <Card key={c} c={c}
                    onClick={canPlay && dummyToPlay && legal.has(c) ? () => doPlay(c) : null} />
                ))}
              </div>
              <div className="dis-piles">
                {game.piles[DUMMY_POS].map((p, i) => (
                  <Pile key={i} pile={p}
                    onPlay={canPlay && dummyToPlay && legal.has(p?.top) ? () => doPlay(p.top) : null} />
                ))}
              </div>
            </div>
          )}

          {/* middle */}
          {game.phase === "auction" && isSkat ? (
            <div className="dis-auction">
              <div className="muted">Auction</div>
              <div className="dis-contractrow"><ContractLine game={game} /></div>
              {game.auction.value > 0 && (<>
                <div className="muted">{nameOf(declSeat)} holds it at {game.auction.value}</div>
                <NeedsRow value={game.auction.value} bases={skatBases}
                  maxLevel={catalog?.max_level}
                  prefix={`${game.auction.value} would need`} />
              </>)}
              {game.redeals > 0 && (
                <div className="muted" style={{ fontSize: "0.78rem" }}>
                  Hand thrown in{game.redeals > 1 ? ` ${game.redeals} times` : ""} — redealt.
                </div>
              )}
              {myTurn ? (
                <>
                  <div className="dis-valgrid">
                    {(opt.values || []).map((v) => (
                      <button key={v} className={bidValue === v ? "on" : ""}
                        onClick={() => setBidValue(bidValue === v ? null : v)}>{v}</button>
                    ))}
                  </div>
                  {bidValue !== null && bidValue !== game.auction.value && (
                    <NeedsRow value={bidValue} bases={skatBases}
                      maxLevel={catalog?.max_level}
                      prefix={`yours would need`} />
                  )}
                  <div className="dis-actrow">
                    <button className="btn dis-gobtn" disabled={bidValue === null} onClick={doValueBid}>
                      Bid {bidValue ?? ""}
                    </button>
                    <button className="btn btn-ghost" onClick={doPass}>Pass</button>
                  </div>
                  {/* Only the open-pass beat gets a hint: what passing DOES
                      is genuinely non-obvious there. Mid-auction advice was
                      dropped — it read as chatter on every bid. */}
                  {game.auction.value === 0 && (
                    <div className="muted dis-hint">
                      Pass and your opponent takes the talon and the lead — at
                      their own price. Both of you passing throws the hand in.
                    </div>
                  )}
                </>
              ) : <div className="muted">Waiting for {nameOf(game.auction.to_act)}…</div>}
            </div>
          ) : game.phase === "auction" ? (
            <div className="dis-auction">
              <div className="muted">Auction</div>
              {/* Wrapped in a RESERVED ROW for the same reason the standing
                  line below is always rendered: `ContractLine` swaps a
                  body-size "no contract yet" for a 1.5rem contract the moment
                  a bid lands, and those are different heights — measured at
                  7px, which the whole keypad underneath inherited as a jump.
                  The placeholder is gone entirely now, so the row is empty
                  until a bid stands and the reserve is doing ALL the work. */}
              <div className="dis-contractrow">
                <ContractLine game={game}
                  who={game.auction.level > 0
                    ? nameOf(game.auction.declarer) : null} />
              </div>
              {/* What the STANDING contract is worth. Always rendered so the
                  keypad below cannot move when the first bid lands; empty until
                  there is something to price. */}
              <div className="dis-worth">
                <BidWorth level={game.auction.level}
                  jump={game.auction.jump ?? 0} price={priceBid} />
              </div>
              {/* POINTS, not "score" — the level is a promise in TRICK points,
                  and "score" is what the round pays out. Same vocabulary the
                  result panel keeps to. (This comment sits OUTSIDE the `&&`:
                  a JSX comment is a child expression, and one inside those
                  parens is a syntax error.) */}
              {myTurn ? (
                <>
                  <div className="dis-bidgrid">
                    {bidLevels.map((l) => {
                      const ok = levelOk(l);
                      return (
                        <button key={l} className={bidLevel === l ? "on" : ""}
                          disabled={!ok}
                          title={ok ? `level ${l}` : "does not outrank the standing bid"}
                          onClick={() => {
                            setBidLevel(l);
                            // Keep the denom only if it stays legal at this level.
                            if (bidDenom !== null && !denomOkAt(l, bidDenom)) setBidDenom(null);
                          }}>{l}</button>
                      );
                    })}
                  </div>
                  <div className="dis-denoms">
                    {[0, 1, 2, 3, 4].map((d) => {
                      const ok = bidLevel !== null && denomOkAt(bidLevel, d);
                      return (
                        <button key={d}
                          className={bidDenom === d ? "on" : ""}
                          disabled={!ok}
                          title={ok ? DENOM_NAME[d]
                            : bidLevel === null ? "pick a level first"
                              : "not available at that level"}
                          onClick={() => setBidDenom(d)}><Den d={d} /></button>
                      );
                    })}
                  </div>
                  <div className="dis-actrow">
                    <button className="btn dis-gobtn" disabled={!bidReady} onClick={doBid}>
                      Bid {bidLevel ?? ""}{bidDenom !== null ? <Den d={bidDenom} /> : ""}
                    </button>
                    {opt.may_pass && <button className="btn btn-ghost" onClick={doPass}>Pass</button>}
                  </div>
                  {/* ...and what the SELECTED bid would be worth, priced off the
                      level alone -- the denomination changes who can outrank it,
                      never what it pays -- so this fills in as soon as a rung is
                      picked rather than waiting for both halves. The jump is
                      measured from the STANDING level, which is what the set
                      bonus charges for. */}
                  <div className="dis-worth dis-worth-pick">
                    <BidWorth level={bidLevel}
                      jump={(bidLevel ?? 0) - game.auction.level}
                      price={priceBid} label="if you bid: " />
                  </div>
                  {/* No hint row at all. It said "The opener must bid." at the
                      opening and nothing afterwards, and the panel is centred
                      in the rail (`align-self: center`), so a row that comes
                      and goes moved EVERY row in the panel — the keypad above
                      it included, measured at 15px. Reserving the row fixed
                      the movement; removing the text removes the row, which
                      fixes it the same way and costs a line nobody needed —
                      the absence of a Pass button says it already. */}
                </>
              ) : <div className="muted">Waiting for {nameOf(game.auction.to_act)}…</div>}
            </div>
          ) : game.phase === "commit" ? (
            /* QUARTET's stage two. The auction competes on level and
               denomination; this is where the declarer DECLARES -- which of
               their two hands leads, and the one card they may move between
               them. Both are declarations rather than contests, which is why
               they sit after the bidding rather than inside it.

               Shipped to the declarer alone (`game.commit`), so the defender
               gets the waiting line and learns only THAT a swap happened. */
            <div className="dis-auction">
              <div className="muted">Your call</div>
              <ContractLine game={game} />
              {game.commit ? (
                <>
                  <div className="muted dis-hint">
                    You won the auction. Say which of your two hands leads
                    trick 1 — <b>leading costs you the last card of every
                    trick</b> — and you may move one card between them.
                  </div>
                  {/* `btn-ghost` IS WHAT PAINTS THE BORDER. `.btn` is
                      `border: none` and `.dis-annbtn` only sets a border
                      COLOUR, so without it these rendered as bare accent text
                      -- reported from a real game as "I'm stuck here": they did
                      not read as buttons at all, and the go button below stays
                      disabled until one is chosen. */}
                  <div className="dis-actrow">
                    {game.commit.leads.map((p) => (
                      <button key={p}
                        className={`btn btn-ghost dis-annbtn${commitLead === p ? " sel" : ""}`}
                        aria-pressed={commitLead === p}
                        onClick={() => setCommitLead(p)}>
                        {p < QUARTET_HANDS ? "Your hand leads" : "Opposite leads"}
                      </button>
                    ))}
                  </div>
                  {/* The consequence of that choice, spelled out and LIVE --
                      the numbered badges on the four seats re-order as soon as
                      a lead is picked, so the trade (the lead gives up the last
                      card of the trick) can be read off the board itself
                      rather than taken on trust from the sentence above. */}
                  <div className="muted" style={{ fontSize: "0.78rem" }}>
                    {commitLead === null
                      ? "Pick one — the seats will number themselves 1-4 in play order."
                      : <>Play goes <b>1 → 2 → 3 → 4</b> round the table, and your
                        side takes seats <b>1</b> and <b>3</b>.</>}
                  </div>
                  <div className="muted" style={{ fontSize: "0.8rem" }}>
                    Take one from the hand opposite…
                  </div>
                  <div className="dis-hand" style={{ justifyContent: "center" }}>
                    {game.commit.take.map((c) => (
                      <Card key={c} c={c} sel={commitTake === c}
                        onClick={() => setCommitTake(commitTake === c ? null : c)} />
                    ))}
                  </div>
                  {commitTake !== null && (
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      …and send which of your own back?
                    </div>
                  )}
                  {commitTake !== null && (
                    <div className="dis-hand" style={{ justifyContent: "center" }}>
                      {game.commit.give.map((c) => (
                        <Card key={c} c={c} sel={commitGive === c}
                          onClick={() => setCommitGive(commitGive === c ? null : c)} />
                      ))}
                    </div>
                  )}
                  <div className="dis-actrow">
                    <button className="btn dis-gobtn"
                      disabled={commitLead === null
                        || (commitTake !== null && commitGive === null)}
                      onClick={() => {
                        doMove({
                          kind: "commit", lead: commitLead,
                          take: commitTake, give: commitTake === null ? null : commitGive,
                        });
                        setCommitLead(null); setCommitTake(null); setCommitGive(null);
                      }}>
                      {commitLead === null
                        ? "Pick which hand leads first"
                        : commitTake !== null && commitGive !== null
                          ? <>Swap <CardName c={commitTake} /> for <CardName c={commitGive} /> and play</>
                          : "Play it as dealt"}
                    </button>
                  </div>
                </>
              ) : (
                <div className="muted">
                  {nameOf(game.auction.declarer)} is choosing which hand leads…
                </div>
              )}
            </div>
          ) : game.phase === "swap" ? (
            <div className="dis-auction">
              <div className="muted">The talon</div>
              <ContractLine game={game} />
              {game.swap ? (
                <>
                  <div className="muted" style={{ fontSize: "0.85rem" }}>
                    You won the auction. Three of the six talon cards — take
                    one into hand and discard, or stand pat.
                  </div>
                  <div className="dis-hand" style={{ justifyContent: "center" }}>
                    {game.swap.shown.map((c) => (
                      <Card key={c} c={c} sel={swapTake === c}
                        onClick={() => setSwapTake(swapTake === c ? null : c)} />
                    ))}
                  </div>
                  {swapTake !== null && (
                    <div className="muted" style={{ fontSize: "0.8rem" }}>
                      …and discard which card from your hand?
                    </div>
                  )}
                  <div className="dis-actrow">
                    <button className="btn dis-gobtn" disabled={swapTake === null || swapGive === null}
                      onClick={() => doSwap(swapTake, swapGive)}>
                      Swap {swapTake !== null ? <CardName c={swapTake} /> : ""}
                      {swapGive !== null ? <> for <CardName c={swapGive} /></> : ""}
                    </button>
                    <button className="btn btn-ghost" onClick={() => doSwap(null, null)}>
                      Stand pat
                    </button>
                  </div>
                </>
              ) : (
                <div className="muted">
                  {nameOf(game.auction.declarer)} is looking at three of the
                  talon cards…
                </div>
              )}
            </div>
          ) : game.phase === "talon" ? (
            <div className="dis-auction">
              <div className="muted">The talon · {game.auction.value} to beat</div>
              <ContractLine game={game} />
              {game.talon ? (
                !game.talon.looked ? (
                  <>
                    <div className="muted dis-hint">
                      You bought the declaration at <b>{game.auction.value}</b>. Look at
                      three of the six talon cards and you may take one into
                      hand — or decline to look at all and play <b>Hand</b>, worth
                      +1 to your multiplier.
                    </div>
                    <div className="dis-actrow">
                      <button className="btn dis-gobtn" onClick={() => doMove({ kind: "look" })}>
                        Look at the talon
                      </button>
                      <button className="btn btn-ghost dis-annbtn"
                        onClick={() => doMove({ kind: "hand" })}>
                        Play Hand (×2)
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <div className="muted dis-hint">
                      Take one into hand and discard, or stand pat. Either way you
                      have looked, so Hand is gone.
                    </div>
                    <div className="dis-hand" style={{ justifyContent: "center" }}>
                      {game.talon.shown.map((c) => (
                        <Card key={c} c={c} sel={swapTake === c}
                          onClick={() => setSwapTake(swapTake === c ? null : c)} />
                      ))}
                    </div>
                    {swapTake !== null && (
                      <div className="muted" style={{ fontSize: "0.8rem" }}>
                        …and discard which card from your hand?
                      </div>
                    )}
                    <div className="dis-actrow">
                      <button className="btn dis-gobtn" disabled={swapTake === null || swapGive === null}
                        onClick={() => doSwap(swapTake, swapGive)}>
                        Swap{swapTake !== null ? <> <CardName c={swapTake} /></> : ""}
                        {swapGive !== null ? <> for <CardName c={swapGive} /></> : ""}
                      </button>
                      <button className="btn btn-ghost" onClick={() => doSwap(null, null)}>
                        Stand pat
                      </button>
                    </div>
                  </>
                )
              ) : (
                <div className="muted">
                  {nameOf(declSeat)} won the auction at {game.auction.value} and is
                  deciding about the talon…
                </div>
              )}
            </div>
          ) : game.phase === "declare" ? (
            <div className="dis-auction">
              <div className="muted">Declare · your bid was {game.auction.value}</div>
              {game.declare ? (() => {
                const d = game.declare;
                const row = d.denoms.find((x) => x.denom === declDenom);
                const value = row ? row.base * (declLevel || 0) : 0;
                const mult = 1 + (d.hand ? 1 : 0) + (declSharp ? 1 : 0) + (declOpen ? 1 : 0);
                // The same conditions apply_declare enforces, so the button is
                // never live on a declaration the server will refuse.
                const ok = !!row && declLevel >= row.min_level
                  && declLevel <= d.max_level && (!declOpen || declSharp);
                return (
                  <>
                    <div className="dis-denoms">
                      {d.denoms.map((x) => (
                        <button key={x.denom}
                          className={declDenom === x.denom ? "on" : ""}
                          title={`${DENOM_NAME[x.denom]} — base ${x.base}, so at least level ${x.min_level}`}
                          // Switching denomination resets the announcements: the
                          // level moves with it, and a stale Open without its
                          // Sharp is a combination the server refuses.
                          onClick={() => {
                            setDeclDenom(x.denom); setDeclLevel(x.min_level);
                            setDeclSharp(false); setDeclOpen(false);
                          }}>
                          <Den d={x.denom} /><small>×{x.base}</small>
                        </button>
                      ))}
                    </div>
                    {row && (
                      <>
                        <div className="muted" style={{ fontSize: "0.8rem" }}>
                          At least level {row.min_level} to reach {d.bid}. Higher is
                          voluntary — it pays more and promises more.
                        </div>
                        <div className="dis-bidgrid">
                          {Array.from({ length: d.max_level - row.min_level + 1 },
                            (_, i) => row.min_level + i).map((l) => (
                              <button key={l} className={declLevel === l ? "on" : ""}
                                title={`${row.base} × ${l} = ${row.base * l}`}
                                onClick={() => setDeclLevel(l)}>{l}</button>
                            ))}
                        </div>
                      </>
                    )}
                    <div className="dis-anns">
                      {d.hand && <span className="dis-ann on" title="You never looked at the talon">Hand</span>}
                      <button className={`dis-ann${declSharp ? " on" : ""}`}
                        title={`Promise ${d.sharp_bonus} more than your level`}
                        onClick={() => {
                          const next = !declSharp;
                          setDeclSharp(next);
                          if (!next) setDeclOpen(false);   // Open rides on Sharp
                        }}>Sharp +{d.sharp_bonus}</button>
                      <button className={`dis-ann${declOpen ? " on" : ""}`}
                        disabled={!declSharp}
                        title="Sharp, with your hand face up from trick 1"
                        onClick={() => setDeclOpen(!declOpen)}>Open</button>
                    </div>
                    <div className="dis-maths">
                      {`${row?.base} × ${declLevel} = ${value}`}
                      {mult > 1 ? ` × ${mult} (${multParts({ ...d, sharp: declSharp, open: declOpen }).join(" + ")})` : ""}
                      {" = "}<b>{value * mult}</b>
                      {` · you must take ${ptsLabel(declLevel + (declSharp ? d.sharp_bonus : 0))}`}
                    </div>
                    <button className="btn dis-gobtn" disabled={!ok}
                      onClick={() => doDeclare(declDenom, declLevel, declSharp, declOpen)}>
                      Declare
                    </button>
                  </>
                );
              })() : (
                <div className="muted">{nameOf(declSeat)} is naming the game…</div>
              )}
            </div>
          ) : game.phase === "double" ? (
            <div className="dis-auction">
              <div className="muted">Kontra?</div>
              <ContractLine game={game} />
              {myDouble ? (
                <>
                  {/* THE NUMBERS, AS NUMBERS. The whole point of Double is that
                      the two sides of the bet are LOPSIDED, and a player cannot
                      weigh that from the word "doubles" — but the paragraph that
                      said it in prose ran five lines in a 17rem rail and pushed
                      the buttons under a scrollbar, which is worse than not
                      explaining it. Two rows, each `now → doubled`, so the
                      asymmetry is something you SEE rather than parse. */}
                  {(() => {
                    // PRICED, never retyped: both columns come out of
                    // `priceContract`, which mirrors `_terms_for`. The three
                    // rows used to hardcode a ×2 on both bases and a rising
                    // ramp on the shortfall, and by 2026-08-17 every one of
                    // those was a rule the game had stopped applying — the
                    // set base does NOT double any more, the leap does, and a
                    // doubled point short is a flat rate rather than a ramp.
                    const jump = game.auction.jump ?? 0;
                    const now = priceContract(game.auction.level, jump, false);
                    const dbl = priceContract(game.auction.level, jump, true);
                    return (
                      <div className="dis-ktable">
                        <KontraRow label="They make it" now={now.make} dbl={dbl.make} />
                        {/* The set base and the leap in one number, because
                            that is what a set pays. With classic's base ×1 and
                            no leap this row does not move under Kontra — which
                            is the bet's whole shape, so it is shown standing
                            still rather than dropped. */}
                        <KontraRow label="You set them" now={now.setBase} dbl={dbl.setBase} />
                        <KontraRow label="…plus, per point short"
                          now={now.short}
                          dbl={dblRamp
                            ? [1, 2, 3].map((i) => dbl.short + dblRamp * i).join(", ") + "…"
                            : dbl.short} />
                      </div>
                    );
                  })()}
                  <div className="dis-actrow">
                    <button className="btn dis-kontrabtn"
                      onClick={() => doMove({ kind: "double", on: true })}>Kontra</button>
                    <button className="btn btn-ghost"
                      onClick={() => doMove({ kind: "double", on: false })}>Let it stand</button>
                  </div>
                </>
              ) : (
                <div className="muted">Waiting for {nameOf(1 - declSeat)}…</div>
              )}
            </div>
          ) : game.phase === "kontra" || game.phase === "re" ? (
            <div className="dis-auction">
              <div className="muted">{game.phase === "re" ? "Re?" : "Kontra?"}</div>
              <ContractLine game={game} />
              <SkatStake game={game} nameOf={nameOf} shortRate={shortRate} />
              {myKontra ? (
                <>
                  <div className="muted dis-hint">
                    You know the game at last. <b>Kontra</b> doubles it whichever
                    way it falls.
                  </div>
                  <div className="dis-actrow">
                    <button className="btn dis-kontrabtn"
                      onClick={() => doMove({ kind: "kontra", on: true })}>Kontra</button>
                    <button className="btn btn-ghost"
                      onClick={() => doMove({ kind: "kontra", on: false })}>Let it stand</button>
                  </div>
                </>
              ) : myRe ? (
                <>
                  <div className="muted dis-hint">
                    {nameOf(1 - declSeat)} doubled you. <b>Re</b> doubles it again.
                  </div>
                  <div className="dis-actrow">
                    <button className="btn dis-kontrabtn"
                      onClick={() => doMove({ kind: "re", on: true })}>Re</button>
                    <button className="btn btn-ghost"
                      onClick={() => doMove({ kind: "re", on: false })}>Accept</button>
                  </div>
                </>
              ) : (
                <div className="muted">
                  Waiting for {nameOf(game.phase === "re" ? declSeat : 1 - declSeat)}…
                </div>
              )}
            </div>
          ) : (game.phase === "over" && !heldTrick && !res) ? (
            /* A ROUND THAT ENDED WITHOUT A RESULT. Everything below reads
               `res` unguarded and `res.made` is the first thing it touches, so
               without this branch a missing result blanks the whole board with
               `TypeError: null is not an object (evaluating 'r.made')`.

               A NET, not the primary handler, and deliberately kept as one.
               The state was reachable because `load_game_to_memory` used to
               VOID a save it could not resume (a pre-v2 deck, or a dummy round
               dealt before the wide deck) by closing the round in place with no
               result; it DELETES those rows now, so nothing should arrive here.
               "Should" is the reason this stays: the cost is a dozen lines and
               the failure it prevents is the entire screen. */
            <div className="dis-result">
              <div className="dis-big set">Round ended</div>
              <div className="muted">
                A rules update means this round can no longer be played out, so
                it was closed where it stood. Nothing was scored. Start a new
                game from the lobby.
              </div>
              <button className="btn dis-gobtn" onClick={leaveToLobby}>Back to lobby</button>
            </div>
          ) : (game.phase === "over" && !heldTrick) ? (
            <div className="dis-result">
              <div className={`dis-big ${res.made ? "made" : "set"}`}>
                {res.abandoned_by !== null && res.abandoned_by !== undefined
                  ? "Game abandoned"
                  : res.denom === NULL_DENOM
                    ? (res.made ? "Null made" : "Null broken")
                    : res.null ? "Null!"
                      : (res.made ? "Contract made" : "Contract set")}
              </div>
              {/* A forfeit has no contract to narrate — in skat mode the auction
                  may not even have produced a declarer, so every arithmetic line
                  below is skipped rather than printed against missing keys. */}
              {res.abandoned_by !== null && res.abandoned_by !== undefined ? (
                <div className="muted">
                  {nameOf(res.abandoned_by)} left the game, so{" "}
                  {nameOf(1 - res.abandoned_by)} takes{" "}
                  {res.scores[1 - res.abandoned_by]}
                  {res.level ? <>
                    {" "}for the standing {res.level}<Den d={res.denom} /> contract.
                  </> : "."}
                </div>
              ) : res.mode === "skat" ? <>
                {/* COLOUR-KEYED LIKE CLASSIC's — the panel's own convention
                    (points blue, score green, the contract plain-strong) is
                    mode-independent, and skat shipped without it: the same
                    screen implemented its signature scheme in one mode and
                    not the other. */}
                <div className="muted">
                  {`${nameOf(res.declarer)} bought it at ${res.bid}, declared `}
                  <Lvl>{res.level}</Lvl><Den d={res.denom} />
                  {multParts(res).length ? ` ${multParts(res).join(" + ")}` : ""}
                  {res.kontra ? (res.re ? " · Kontra + Re" : " · Kontra") : ""}
                  {" and scored "}<Pts>{scored(res.declarer_pts)}</Pts>
                  {" of the "}<Lvl>{res.target}</Lvl>{" promised"}
                  {res.null ? ` — taking no scoring trick at all` : ""}
                </div>
                {/* THE WHOLE CHAIN, from the denomination's base price. Skat's
                    value is base × level and that first step used to be
                    invisible, so a made contract printed a bare number where
                    classic prints "3 × 3 = 9". Only the FINAL total wears the
                    score green — whichever number that is in this round's
                    shape — so the colour always marks what reached the
                    scoreboard, never an intermediate. */}
                <div className="dis-maths">
                  {res.null ? <>flat <Score>{res.null_value}</Score> to {nameOf(res.declarer)}</> : (() => {
                    const hasMult = res.mult > 1 || res.doubling > 1;
                    const headIsFinal = res.made && !res.over && !hasMult;
                    const stakeIsFinal = res.made && !res.over && hasMult;
                    return <>
                      {res.base} (<Den d={res.denom} />) × <Lvl>{res.level}</Lvl>{" = "}
                      {headIsFinal ? <Score>{res.value}</Score> : res.value}
                      {res.mult > 1 ? ` × ${res.mult}` : ""}
                      {res.doubling > 1 ? ` × ${res.doubling}` : ""}
                      {hasMult ? <>{" = "}{stakeIsFinal ? <Score>{res.stake}</Score> : res.stake}</> : null}
                      {res.made
                        ? <>{res.over
                          ? <>{" + "}<Pts>{res.over}</Pts>{" = "}<Score>{res.scores[res.declarer]}</Score></>
                          : null}{" "}to {nameOf(res.declarer)}</>
                        // `shortTail`/`short_rate` off the row, never a
                        // literal: the rate moved 4 -> 5 and this line kept
                        // charging the old one, printing a sum that did not
                        // reach the score beside it. A ramp is spelled out;
                        // the flat case colours the points missed, exactly
                        // as classic's ResultMaths does.
                        : <>{" + "}{res.ramp
                          ? shortTail(res)
                          : <>{res.short_rate ?? 4} × <Pts>{res.short || 0}</Pts></>}
                          {" = "}<Score>{res.scores[1 - res.declarer]}</Score>{" "}
                          to {nameOf(1 - res.declarer)}</>}
                    </>;
                  })()}
                </div>
              </> : <>
                {/* POINTS vs SCORE. The sentence says what happened in TRICK
                    POINTS — the currency the contract is measured in — and the
                    line below turns that into SCORE. The two quantities are
                    colour-keyed across both, so the P in "took 3 extra points"
                    and the `+ 3` in the formula are visibly one number. */}
                <div className="muted">
                  {nameOf(res.declarer)} bid <Lvl>{res.level}</Lvl>
                  <Den d={res.denom} />
                  {res.doubled ? <>, doubled by {nameOf(1 - res.declarer)},</> : ""}
                  {res.null
                    // `nullCond`, so the condition is stated in the room's own
                    // currency ("no +2 trick", "no positive trick") rather than
                    // in a word that only fits the parity modes.
                    ? <> and won {nullCond(game)} at all</>
                    : res.made
                      ? <> and took <Pts>{scored(res.over)}</Pts>{" "}
                        extra {res.over === 1 ? "point" : "points"}</>
                      : <> and finished <Pts>{res.short}</Pts>{" "}
                        {res.short === 1 ? "point" : "points"} short</>}
                </div>
                {/* The doubling is shown as the STEP it is, not as a bigger
                    number arriving from nowhere. Every term is the result row's
                    own -- off the terms `_finish` scored with -- so the panel
                    cannot narrate an arithmetic the room did not apply. */}
                {/* QUARTET: the declarer's total is TWO numbers added, and
                    without this the panel prints a total the player cannot
                    check against anything they watched happen. Tricks are
                    what the felt showed; the keeps are the three cards their
                    own hand was still holding when the ninth trick ended. */}
                {res.mode === "quartet" && res.keeps && (
                  <div className="muted" style={{ fontSize: "0.8rem" }}>
                    <Pts>{scored(res.declarer_pts)}</Pts>{" is "}
                    <Pts>{scored(res.trick_pts[res.declarer])}</Pts>{" from tricks"}
                    {" plus "}<Pts>{scored(res.keeps[res.declarer])}</Pts>
                    {" from the three cards kept in hand."}
                  </div>
                )}
                <ResultMaths res={res} nameOf={nameOf} price={priceContract} />
                {res.doubled && (
                  /* WHAT THE BET WAS WORTH, as the difference it made. This
                     used to report the set BASE moving ("the set base went
                     4 → 10"), which says nothing about the round just played
                     and quoted a base the game stopped charging in 2026-08.
                     `undoubled` is the engine's own re-score of this same
                     round with the Double taken off, so the comparison is
                     never a second copy of the scoring. */
                  <div className="muted" style={{ fontSize: "0.8rem" }}>
                    {res.null
                      ? `Kontra — but Null is untouched: a declarer who wins ${nullCond(game)}
                         scores the flat ${res.null_value} either way.`
                      : <DoubleWorth res={res} nameOf={nameOf} />}
                  </div>
                )}
              </>}
              {res.null && (
                <div className="muted" style={{ fontSize: "0.8rem" }}>
                  Null: a declarer who wins {nullCond(game)} all round
                  scores it instead of being set, whatever they declared.
                </div>
              )}
              {/* Labelled, and smaller than the match total below: in round 1
                  the two rows carry identical numbers, and unlabelled at
                  near-identical sizes they read as one row printed twice. */}
              <div className="dis-round-tally">
                <div className="muted">This round</div>
                <div className="dis-scorerow">
                  <span>{nameOf(mySeat)} <b>{res.scores[mySeat]}</b></span>
                  <span>{nameOf(oppSeat)} <b>{res.scores[oppSeat]}</b></span>
                </div>
              </div>
              {/* ...and what that did to the match. The round's number on its
                  own is only half the story once there is a target: being set
                  for 3 reads very differently at 12-all and at 47-all. */}
              {res.match_scores && (
                <div className="dis-match">
                  <div className="muted">
                    {res.match_over
                      ? `Match to ${res.match_target}`
                      : `Match to ${res.match_target} · after round ${res.round}`}
                  </div>
                  <div className="dis-scorerow dis-match-total">
                    <span>{nameOf(mySeat)} <b>{res.match_scores[mySeat]}</b></span>
                    <span>{nameOf(oppSeat)} <b>{res.match_scores[oppSeat]}</b></span>
                  </div>
                  {/* WHO WON COMES OFF THE ROW. Comparing the two numbers above
                      it is right for a played-out match and wrong for the one
                      case that matters most: a player who abandons while ahead
                      keeps the higher score, and this told them "You win the
                      match". Walking out is a loss at any standing. `??` is the
                      fallback for a result saved before the field existed. */}
                  {res.match_over && (() => {
                    const w = res.match_winner ?? (
                      res.match_scores[mySeat] === res.match_scores[oppSeat] ? -1
                        : res.match_scores[mySeat] > res.match_scores[oppSeat] ? mySeat : oppSeat);
                    return (
                      <div className={`dis-big ${w === mySeat ? "made" : "set"}`}>
                        {w === -1 ? "Match drawn"
                          : w === mySeat ? "You win the match"
                            : `${nameOf(oppSeat)} wins the match`}
                        {res.abandoned_by !== null && res.abandoned_by !== undefined
                          && ` — ${nameOf(res.abandoned_by)} forfeited`}
                      </div>
                    );
                  })()}
                </div>
              )}
              {/* THE TALON — the six nobody was dealt, revealed. Every card you
                  could not account for all round was either in their hand or in
                  here, so this is the answer sheet — as cards, because a run of
                  text codes is not something you can read a hand off.

                  "The talon" is the whole six-card stock, and the line beneath
                  says which three of it the declarer was actually shown. Note
                  the swap means this is the talon as it ENDED: the card the
                  declarer took is in their hand, and their discard is here in
                  its place. */}
              {game.out && (
                <div className="dis-reveal">
                  <div className="muted">The talon</div>
                  {/* THE THREE THE DECLARER SAW ARE GROUPED, AND ON THEIR SIDE.
                      The six were rendered in the order the engine stores them,
                      which mixes seen and unseen — so "which three did they get
                      to choose from" was a question you answered by reading the
                      caption underneath and matching card names. Now they are
                      one group, outlined, and placed in the row nearest whoever
                      declared: the top row if the opponent did, the bottom row
                      if you did (the panel wraps six into two rows of three).
                      WITHIN each group the DEALT order is kept — the talon is
                      not a hand and sorting it by suit or rank would invent an
                      order the round never had. */}
                  <div className="dis-outrow">
                    {(() => {
                      const seen = new Set(sawTalon ? (game.shown_at_deal || []) : []);
                      /* GROUP BY SLOT, NOT BY CARD — a swap takes one of the
                         shown three into hand and puts the discard IN ITS
                         PLACE (the engine rewrites `out` positionally), so a
                         card-keyed group came out 2 + 4: the taken card is no
                         longer in the talon at all, and the discard drifted
                         into the unseen half. What the group means is "the
                         three the declarer could place", which is the shown
                         three with the take substituted by the give. */
                      const slots = new Set([...seen].map((c) =>
                        (c === game.swap_take && game.swap_give != null
                          ? game.swap_give : c)));
                      const a = game.out.filter((c) => slots.has(c));
                      const b = game.out.filter((c) => !slots.has(c));
                      const declaredByMe = res.declarer === mySeat;
                      const rows = declaredByMe ? [b, a] : [a, b];
                      return rows.flat().map((c) => {
                        // The discard is in the talon but was never SHOWN — it
                        // came out of the declarer's own hand — so it takes the
                        // swap's own dashed badge rather than the shown ring.
                        const gave = c === game.swap_give && game.swap_take != null;
                        return (
                          <span key={c}
                            className={gave ? "dis-out-gave" : seen.has(c) ? "dis-out-seen" : undefined}
                            title={gave
                              ? "Discarded into the talon, in the place of the card the declarer took"
                              : seen.has(c) ? "Shown to the declarer" : undefined}>
                            <Card c={c} small />
                          </span>
                        );
                      });
                    })()}
                  </div>
                  {/* WHAT THE DECLARER ACTUALLY SAW AND DID — and no more than
                      that. This line used to read `shown` straight off the
                      state, which the engine rewrote on a swap, so it named the
                      discarded card as one they had been shown; and it said
                      "was shown" even for a Hand game, where the declarer never
                      looked at the talon at all. Both are the same mistake:
                      describing the talon from the final position instead of
                      from what happened. */}
                  {game.shown_at_deal && (sawTalon ? (
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {nameOf(res.declarer)} was shown{" "}
                      {/* A span, not React.Fragment: this file uses the modern
                          JSX transform and never imports React, so the
                          namespace does not exist at runtime — and a build
                          would not have told me. */}
                      {game.shown_at_deal.map((c, i) => (
                        <span key={c}>{i ? " " : ""}<CardName c={c} /></span>
                      ))}
                      {game.swap_take != null && game.swap_give != null
                        ? <>, and swapped <CardName c={game.swap_take} /> with{" "}
                          <CardName c={game.swap_give} /></>
                        : game.swapped
                          // A save written before the engine recorded which
                          // cards moved. Say that one did, not which.
                          ? ", and swapped one of them"
                          : ", and stood pat"}
                    </div>
                  ) : (
                    <div className="muted" style={{ fontSize: "0.72rem" }}>
                      {nameOf(res.declarer)} played a Hand — never looked at these
                    </div>
                  ))}
                </div>
              )}
              {/* A match that is not decided yet deals again rather than
                  sending anyone back to the lobby. EITHER seat may press it --
                  waiting on one nominated player is how a match stalls when
                  they close the tab -- and the round it was pressed on rides
                  along so two simultaneous clicks cannot deal twice. */}
              {res.match_scores && !res.match_over ? (
                <div className="dis-resbtns">
                  <button className="btn dis-gobtn" onClick={() => doMove({
                    kind: "next_round", round: res.round,
                  })}>Next round</button>
                  <button className="btn btn-ghost" onClick={leaveToLobby}>Back to lobby</button>
                </div>
              ) : (
                <button className="btn dis-gobtn" onClick={leaveToLobby}>Back to lobby</button>
              )}
            </div>
          ) : (
            <>
              <div className="dis-trick">
                {/* The trick band holds the cards, each card's "who played
                    this" name, and — since 2026-08-12 — WHAT THE TRICK IS
                    WORTH. The rest of what the middle used to carry (the
                    counter, the contract chip, the turn bar) lives in
                    `.dis-playside` below, which the wide desktop places in
                    the rail beside the felt.

                    The value pill came BACK to the trick because it is the
                    one number that is about the two cards you are looking
                    at: in the rail it sat a column away from the thing it
                    prices, and deciding whether to take a trick means
                    reading both at once. */}
                <div className="dis-trickcards">
                  {trickCards.length === 0
                    ? <div className="muted">{myTurn ? "Your lead" : "Waiting…"}</div>
                    : trickCards.map((t, i) => (
                      <div key={i} className={`dis-tp${t.won ? " won" : ""}`}>
                        <Card c={t.c} />
                        <div className="muted" style={{ fontSize: "0.72rem" }}>
                          {/* The same 1..4 the seats wear, so a card on the
                              felt can be traced back to the hand it came from
                              without counting round the table. */}
                          {isQuartet && <OrderPip n={i + 1} />}{nameOf(t.seat)}
                        </div>
                      </div>
                    ))}
                  {/* IN THE ROW, not positioned over it: the pill is the last
                      flex child, so it sits beside the cards at any card size
                      and with any number of them (a dummy trick is three
                      cards wide). An absolute offset had to guess both. */}
                  {trickVal && (
                    <span className={`dis-val dis-trickval ${trickVal.v > 0 ? "good" : "bad"}`}>
                      {trickVal.label}
                    </span>
                  )}
                </div>
              </div>
              <div className="dis-playside">
                {/* While a finished trick is held, this line is ABOUT that
                    trick — the server's counter has already moved on, so
                    reading it here labelled the two cards you are looking at
                    with the next trick's number. */}
                <div className="dis-trickinfo">
                  Trick {heldTrick ? heldTrick.number : game.trick + 1} of{" "}
                  {game.tricks ?? 13}
                </div>
                <ContractChip game={game} nameOf={nameOf}
                  sharpBonus={catalog?.sharp_bonus ?? 2} />
                <div className="dis-turnbar">
                  {game.phase === "over" ? <span className="muted">Last trick</span>
                    : heldTrick ? <span className="muted">{nameOf(heldTrick.winner)} takes it</span>
                      : myTurn ? <>
                        <span className="dis-yourturn">Your turn</span>
                        {/* WHY the hand has stopped offering most of itself.
                            Cards are never dimmed here (see the stylesheet), so
                            without a word the narrowed set reads as a bug. The
                            server decides it -- `must_head_now` off the view --
                            because the client's `beats` is label-only and does
                            not know Grand. */}
                        {game.must_head_now && (
                          <span className="dis-mhead">must beat it</span>
                        )}
                      </>
                        : <span className="muted">{nameOf(game.to_play)} is thinking…</span>}
                </div>
              </div>
            </>
          )}

          {/* QUARTET: THE HAND OPPOSITE YOU, which you also play. Face up to
              you alone, and its cards take the same `play` affordance as your
              own when it is that position's turn -- commanding two hands is
              one uninterrupted gesture rather than a mode switch, the same
              call dummy mode made.

              It sits ABOVE your own hand, between you and the trick, because
              that is the order it plays in relative to you half the time and
              because the two rows read as one side of the table. */}
          {isQuartet && (
            <div className={`dis-seat dis-qmine${qToPlay === myOther ? " mine" : ""}`}>
              <div className="dis-seatname">
                <b>{nameOf(myOther)}</b>
                <OrderPip n={orderOf(myOther)} />
                {qToPlay === myOther && <span className="dis-yourturn">to play</span>}
              </div>
              <div className="dis-hand">
                {sortHand(game.mine).map((c) => (
                  <Card key={c} c={c}
                    onClick={canPlay && qToPlay === myOther && legal.has(c)
                      ? () => doPlay(c) : null} />
                ))}
              </div>
            </div>
          )}

          {/* you */}
          <div className="dis-seat">
            <div className="dis-piles">
              {game.piles[mySeat].map((p, i) => (
                <Pile key={i}
                  // The played top is gone and what was under it is now the
                  // top — the same shape the server sends back. Only reached
                  // for a pile whose result is known (see `optimisticCard`).
                  pile={p?.top === optimisticCard
                    ? { ...p, top: p.n === 1 ? null : p.under, under: null,
                      n: Math.max(0, (p.n ?? 1) - 1) }
                    : p}
                  onPlay={canPlay && legal.has(p?.top) ? () => doPlay(p.top) : null} />
              ))}
            </div>
            <div className="dis-hand">
              {/* `pendingPlay` is filtered out here and drawn into the trick
                  instead — the optimistic half of a play. See `doPlay`. */}
              {sortHand(game.hand).filter((c) => c !== optimisticCard).map((c) => (
                <Card key={c} c={c}
                  sel={(game.phase === "swap" || game.phase === "talon") && swapGive === c}
                  onClick={
                    (game.phase === "swap" ? game.swap : game.phase === "talon" ? game.talon : null)
                      && swapTake !== null
                      ? () => setSwapGive(swapGive === c ? null : c)
                      : canPlay && legal.has(c) ? () => doPlay(c) : null
                  } />
              ))}
            </div>
            <div className="dis-seatname">
              <b>{nameOf(mySeat)}</b>
              <OrderPip n={orderOf(mySeat)} />
              <span>{game.pts[mySeat] >= 0 ? "+" : ""}{game.pts[mySeat]} pts</span>
            </div>
          </div>
        </div>

        {/* side panel */}
        {/* THE INFO COLUMN (right on a desktop): what the round IS -- the
            talon you bought, the last trick, the contract with the bidding
            that produced it, and the points with the round's trick history.
            Roughly live-first: the two panels that change every trick are at
            the top, the two that settle once a round below them. The
            MATCH gets a column of its own (below, left on a desktop): it is
            about the match rather than this round, and the scorecard is the
            one panel with real content to show. DOM order is board, info,
            match -- which is how a phone stacks them; the desktop grid places
            the match column to the LEFT explicitly. */}
        <div className="dis-side dis-side-info">
          {/* THE TALON FIRST, for the seat that bought the right to see it.
              Three cards you know are out of play is the one thing in this
              column you play FROM rather than read after the fact, so it sits
              at the top where the eye lands, above the standing. It stays up
              for the rest of the round — losing sight of it the moment the swap
              resolves threw away the holding you paid the auction for.

              It tracks what is ACTUALLY OUT, so after a swap your discard sits
              where the card you took used to be. That is the useful half while
              you are still playing, and it is also the shape the client-side
              searcher reads off the wire. The round-end reveal is where "what
              you were SHOWN" gets answered, from `shown_at_deal`. */}
          {/* `?.length`, not truthiness: a DUMMY room has no talon and ships
              an empty array, which is truthy in JS -- so the panel rendered
              with nothing in it under a heading promising cards. A defender
              gets `null` and is excluded either way. */}
          {game.shown?.length > 0 && game.phase !== "over" && (
            <div className="dis-panel dis-p-talon">
              <h4>The talon · you saw these</h4>
              <div className="dis-outrow">
                {game.shown.map((c) => <Card key={c} c={c} small />)}
              </div>
              {game.swapped && (
                <div className="muted" style={{ fontSize: "0.7rem", marginTop: "0.3rem" }}>
                  Includes the card you discarded.
                </div>
              )}
            </div>
          )}
          {/* The trick just gone, ABOVE the contract. It leaves the table the
              instant the next lead arrives, and "what did they just play" is
              the question the log answers worst — it is a flat list of cards
              with no trick breaks. It sat under the contract until 2026-08-11,
              which had it changing every trick halfway down a column of things
              that change once a round; the live panel belongs at the top, next
              to the talon, where the eye already is. */}
          {prev && (
            <div className="dis-panel dis-p-last">
              <h4>Last trick</h4>
              <div className="dis-lasttrick">
                {prev.plays.map((p, i) => (
                  <div key={i} className={`dis-lt-play${p[0] === prev.winner ? " won" : ""}`}>
                    <Card c={p[1]} small />
                    <div className="muted">{nameOf(p[0])}</div>
                  </div>
                ))}
                <div className="dis-lt-note">
                  <div>#{prev.number}</div>
                  <div className={`dis-val ${prev.value > 0 ? "good" : "bad"}`}>
                    {prev.value > 0 ? `+${prev.value}` : "−1"}
                  </div>
                  <div className="muted">{nameOf(prev.winner)} took it</div>
                </div>
              </div>
            </div>
          )}
          <div className="dis-panel dis-p-contract">
            <h4>Contract</h4>
            {/* THE BET, at the top of the box it re-prices. This row and the
                gold chip on the felt are where a Double lives now — the
                full-screen flash it replaced covered the board at the exact
                moment the declarer wants to read their own lead. One gold
                treatment in all three places (chip, this row, the scorecard's
                ×2) so the live round and its banked line agree. */}
            {(ct.re || ct.kontra || game.doubled) && (
              <div className="dis-dblrow">
                {ct.re ? "Kontra + Re" : "Kontra"} — higher stakes
              </div>
            )}
            {isSkat && <>
              <div className="dis-scorerow">
                <span>{declSeat >= 0 ? `${nameOf(declSeat)} bought it at` : "Standing bid"}</span>
                <b>{game.auction.value || "—"}</b>
              </div>
              {game.auction.level > 0 && <>
                <div className="dis-scorerow">
                  <span>Declared</span>
                  <b>{game.auction.level}<Den d={game.auction.denom} /></b>
                </div>
                <div className="dis-scorerow">
                  <span>Must score</span>
                  <b>{game.auction.level + (ct.sharp ? (catalog?.sharp_bonus ?? 2) : 0)}</b>
                </div>
                <SkatStake game={game} nameOf={nameOf} rows shortRate={shortRate} />
              </>}
            </>}
            {/* THE CLASSIC CONTRACT IS ONE HEADLINE AND ONE MONEY LINE.
                It used to be four scorerows — needs / Trump / Makes it for /
                Or Null — and the second of those said in a word what the
                first already said in a glyph ("4♣" over "Trump: Clubs").
                Now: who bought it and what they bought, big; then the target
                and both payouts on one line, since they are the same kind of
                fact and are read together. */}
            {isSkat ? null : game.auction.level
              ? <>
                <div className="dis-ctline">
                  <b>{nameOf(game.auction.declarer)}</b>
                  <span className="dis-ctbid">
                    {game.auction.level}<Den d={game.auction.denom} />
                  </span>
                </div>
                {/* The Null CONDITION stays. Condensing the box to one money
                    line first dropped it, and it is not decoration: it is what
                    Null means, and it differs by mode ("no +2 trick" in
                    classic, "no +1 trick" in minor, "no positive trick" under
                    card scoring). `nullCond` reads it off the wire, so the
                    line is right in every mode without knowing which. */}
                {/* NO "needs N pts" HERE EITHER (2026-08-17). The target IS the
                    level in classic and minor -- `_terms_for` sets
                    `target = level` -- so it restated the number in the headline
                    directly above it, one line down and in words. That is the
                    same glyph-vs-word duplication the note above says was
                    removed once already; it had simply survived in the other
                    half of the box. What is left is the two PAYOUTS, which are
                    real facts and appear nowhere else on screen. */}
                <div className="dis-ctsub">
                  makes{" "}
                  <b>{priceContract(game.auction.level, game.auction.jump ?? 0,
                    !!game.doubled).make}</b>
                  {" "}· Null <b>{nullMake}</b>{" "}
                  <span className="dis-ctcond">({nullCond(game)})</span>
                </div>
                {game.doubled && (
                  <div className="dis-scorerow">
                    <span>Kontra · set pays</span>
                    {/* PRICED, not retyped. This row has now been wrong twice
                        in the same way: it predated the 4 -> 5 shortfall move,
                        and then it kept doubling the set base and ramping the
                        shortfall after the Double stopped doing either. Both
                        numbers come out of `priceContract` now, so the next
                        re-pricing moves them without an edit. */}
                    <b>{priceContract(game.auction.level, game.auction.jump ?? 0,
                      true).setBase}{" + "}
                      {dblRamp
                        ? `${dblShort + dblRamp}, ${dblShort + 2 * dblRamp}…`
                        : `${dblShort} a point`}</b>
                  </div>
                )}
              </>
              : <div className="muted">Being decided…</div>}
            {/* Skat keeps its own rows — bought-at, declared and must-score are
                three genuinely different numbers there — so its Null line
                stays a row of its own. */}
            {isSkat && game.auction.level > 0 && (
              <div className="dis-scorerow">
                <span>Or Null ({nullCond(game)})</span>
                <b>{catalog?.skat_null_value ?? ""}</b>
              </div>
            )}
            {/* HOW THE CONTRACT WAS BOUGHT, under the contract itself. */}
            <BidLog game={game} nameOf={nameOf} skat={isSkat} />
            {game.swapped !== null && game.swapped !== undefined && (
              <div className="muted" style={{ fontSize: "0.72rem", marginTop: "0.3rem" }}>
                {game.swapped
                  ? `${nameOf(declSeat)} exchanged a card with the talon.`
                  : isSkat && ct.hand
                    // Hand and stood-pat both leave `swapped` false, and they are
                    // very different reads — one never saw the cards at all.
                    ? `${nameOf(declSeat)} never looked at the talon.`
                    : `${nameOf(declSeat)} stood pat.`}
              </div>
            )}
          </div>
          <div className="dis-panel dis-p-points">
            <h4>Points</h4>
            <div className="dis-scorerow"><span>{nameOf(mySeat)}</span><b>{game.pts[mySeat]}</b></div>
            <div className="dis-scorerow"><span>{nameOf(oppSeat)}</span><b>{game.pts[oppSeat]}</b></div>
            <div className="muted" style={{ fontSize: "0.72rem", marginTop: "0.3rem" }}>
              {poolNote(game)}
            </div>
            {/* ...and where those points came from, trick by trick. */}
            <TrickHistory game={game} nameOf={nameOf} />
          </div>
        </div>
        {/* THE MATCH COLUMN. Its own grid item rather than a panel inside the
            info column, which is what lets a wide desktop put it on the far
            side of the felt — see the three-column tier in the stylesheet. It
            stays LAST in the DOM because that is the order a phone stacks
            (board, then this round, then the match) and the order a screen
            reader hears; the desktop grid places it to the left explicitly
            rather than by source order. Absent on a game saved before matches
            existed, which is one round with no running total to show — and the
            grid asks `:has()` rather than assuming the element is there. */}
        {game.match && (
          <div className="dis-side dis-side-match">
            <div className="dis-panel dis-p-match">
              <h4>Match to {game.match.target}</h4>
              <div className="dis-scorerow">
                <span>{nameOf(mySeat)}</span><b>{game.match.scores[mySeat]}</b>
              </div>
              <div className="dis-scorerow">
                <span>{nameOf(oppSeat)}</span><b>{game.match.scores[oppSeat]}</b>
              </div>
              <div className="muted" style={{ fontSize: "0.72rem" }}>
                Round {game.match.round}
              </div>
              {/* ...and how the total got there. A running total on its own
                  says who is ahead and nothing about why: which rounds were
                  bought cheaply, who has been declaring, and whether the gap is
                  one big set or six small ones. Absent on a match that was
                  already in progress when the scorecard shipped — there is
                  nowhere to recover its earlier rounds from. */}
              <MatchCard rounds={game.match.rounds} mySeat={mySeat}
                oppSeat={oppSeat} nameOf={nameOf} onStory={setStoryRound} />
            </div>
          </div>
        )}
      </div>

      {showRules && <OddRulesModal onClose={() => setShowRules(false)} />}
      {storyRound && (
        <RoundStory r={storyRound} mySeat={mySeat} nameOf={nameOf}
          roomId={roomData?.room_id} mode={game?.mode}
          maxLevel={catalog?.max_levels?.[game?.mode] ?? catalog?.max_level}
          onClose={() => setStoryRound(null)} />
      )}
      {confirmAbandon && (
        <CreateModal title="Abandon game?" onClose={() => setConfirmAbandon(false)}>
          <span className="cm-hint">
            {/* Say the part that costs the most. The forfeit payment was the
                only consequence named here, which read as "one round" — the
                match ends, and it ends as a LOSS however far ahead you are. */}
            Your opponent is paid what the contract is currently worth, and the
            match ends there — as a loss for you, whatever the score is. This
            cannot be undone.
          </span>
          <div className="cm-footer">
            <button type="button" className="btn btn-ghost"
              onClick={() => setConfirmAbandon(false)}>Keep playing</button>
            <button type="button" className="cm-create"
              onClick={() => { send({ action: "abandon" }); setConfirmAbandon(false); }}>
              Abandon
            </button>
          </div>
        </CreateModal>
      )}
      {toast && <div className="toast">{toast}</div>}
    </div>
  );
}

/** The in-game ☰. Every game uses this shape rather than a row of buttons in
 *  the header — Dissonance was the last one still showing Back + Rules. */
function OddMenu({ onLeave, onRules, onAbandon }) {
  return (
    // Only for a live game you are still in — the caller passes a null
    // `onAbandon` otherwise, and the shared menu drops the row.
    <GameMenu onLeave={onLeave} onRules={onRules} onAbandon={onAbandon} />
  );
}

function OddRulesModal({ onClose }) {
  return (
    <RulesModal title="How to play — Dissonance" onClose={onClose}>
      <DissonanceRules />
    </RulesModal>
  );
}
