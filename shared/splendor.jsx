
// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _splendorCardCssText from "./splendor.splendor-card-css.css?inline";
import _splendorCardExtraCssText from "./splendor.splendor-card-extra-css.css?inline";
import _splendorLogCssText from "./splendor.splendor-log-css.css?inline";
import _splendorPanelCssText from "./splendor.splendor-panel-css.css?inline";
import _splendorPillCssText from "./splendor.splendor-pill-css.css?inline";
/* Shared Splendor visual vocabulary — gem tokens, jewel cards, and the move log.
 *
 * Spender and Spender Duel are the same FAMILY of game (gems, cards with costs and
 * bonuses, gold-as-wild, reserves), so they must LOOK the same. The components and
 * CSS below were extracted VERBATIM out of Spender.jsx — which exported only its app
 * component, so Duel had re-implemented lookalikes and drifted visually (square
 * swatches vs round, its own palette/fonts, a different log). Both games now import
 * from here, so there is no second copy to drift.
 *
 * Duel-only affordances (crowns, pearls, wild bonuses, ability glyphs) are OPTIONAL:
 * Spender never passes them and renders exactly as it always did.
 *
 * NOTE: like every css string in this repo, the template literals here must contain
 * NO backtick (the documented blank-page footgun).
 */

// The 5 gem colors (both games) + Duel's pearl and the shared gold wild.
export const GEM_COLORS = ["white", "blue", "green", "red", "black"];
export const GEM_LABELS = {
  white: "Diamond", blue: "Sapphire", green: "Emerald", red: "Ruby",
  black: "Onyx", gold: "Gold", pearl: "Pearl",
};
export const GEM_HEX = {
  white: "#ddd4be", blue: "#4257ff", green: "#3f9c2e", red: "#dc4040",
  black: "#15151a", gold: "#f5c842", pearl: "#e8c0d4",
};
// Light chips need a dark glyph.
const DARK_TEXT = new Set(["white", "gold", "pearl"]);
// An UNATTACHED wild bonus can become any gem colour you already own a card for, so it
// reads as a multi-colour disc rather than a blank one: a DESATURATED diagonal spectrum
// (muted to sit calmly beside the matte gems, not a garish rainbow) plus a soft gloss
// highlight, so it looks like a polished gem. (A conic wheel of the five GEM colours was
// the obvious idea and looked bad — it put a black wedge in the "rainbow".)
export const WILD_RAINBOW = [
  "radial-gradient(circle at 32% 24%, rgba(255,255,255,.55) 0%, rgba(255,255,255,.12) 20%, rgba(255,255,255,0) 48%)",
  "linear-gradient(135deg, #c98a86 0%, #ccb079 20%, #c3c583 38%, #8ec08f 56%, #83bcc7 72%, #8f9ed0 88%, #bd97cf 100%)",
].join(", ");
// The wilds show a symbol; the five gems are colour alone. They used to show their
// initial, which labelled blue AND black "B" — the one pair the letter had to separate.
const tokenGlyph = (c) => (c === "gold" ? "★" : c === "pearl" ? "●" : "");

/* Gem token. `size` is applied inline (Spender's 42px default). Pass size={null} to
 * let CSS size it instead — Duel's board scales its tokens with the column, and an
 * inline width/height would beat the stylesheet and freeze them. */
export function GemToken({ color, size = 42, className = "", onClick, title, dataCell }) {
  const style = { "--gc": GEM_HEX[color], color: DARK_TEXT.has(color) ? "#333" : "#fff" };
  if (size) { style.width = size; style.height = size; }
  return (
    <div className={`gem-token ${className}`.trim()} style={style} onClick={onClick}
      title={title} data-cell={dataCell} aria-label={GEM_LABELS[color] || color}>
      {tokenGlyph(color)}
    </div>
  );
}

/* A jewel card.
 * Spender passes {card, selected, affordable, needsGold, disabled, onClick, aiValue,
 * valsMine, dataPos}. Duel additionally uses card.crowns, card.cost.pearl,
 * card.bonus === "wild" (+ `asColor` once attached), and card.ability with the glyph
 * and tooltip supplied BY THE CALLER — so this shared file owns no game rules. */
export function CardView({ card, selected, affordable, needsGold, disabled, onClick,
                          aiValue, valsMine, dataPos, asColor, abilityGlyph, abilityTitle,
                          small }) {
  const who = valsMine ? "Your values" : "AI's values";
  // An opponent's blind deck-top reserve is hidden info — show a face-down back.
  if (card.hidden) {
    return (
      <div className={`card card-back${small ? " card-small" : ""}`}>
        <span className="card-back-level">{["I", "II", "III"][(card.level || 1) - 1]}</span>
        <span className="card-back-label">Reserved</span>
      </div>
    );
  }
  const isWild = card.bonus === "wild";
  // Unattached => the rainbow (it can still become any colour you own); once attached it
  // simply IS that colour.
  const bonusBg = isWild ? (asColor ? GEM_HEX[asColor] : WILD_RAINBOW) : GEM_HEX[card.bonus];
  const gems = Object.entries(card.cost || {}).filter(([c, n]) => c !== "pearl" && n > 0);
  const pearl = (card.cost || {}).pearl || 0;
  return (
    <div data-pos={dataPos}
      className={`card${small ? " card-small" : ""}${selected ? " selected" : ""}${affordable ? (needsGold ? " affordable-gold" : " affordable") : ""}${disabled ? " disabled" : ""}`}
      onClick={disabled ? undefined : onClick}
    >
      <div className="card-header">
        <span className={`card-points${card.points === 0 ? " zero" : ""}`}>{card.points || ""}</span>
        {card.crowns > 0 && (
          <span className="card-crowns" title={`${card.crowns} crown${card.crowns > 1 ? "s" : ""}`}>
            {"♛".repeat(card.crowns)}
          </span>
        )}
        {card.bonus && (
          // A double bonus is TWO gems, drawn as two overlapping discs (a stack you can
          // count) rather than one disc with a ring around it — concentric circles read
          // as a single gem sitting on top of another.
          card.bonus_count === 2 ? (
            <div className="card-bonus-pair" title="Gives 2 of this bonus">
              <div className={`card-bonus${isWild ? " card-bonus-wild" : ""}`} style={isWild ? { background: bonusBg } : { "--gc": bonusBg }} />
              <div className={`card-bonus${isWild ? " card-bonus-wild" : ""}`} style={isWild ? { background: bonusBg } : { "--gc": bonusBg }} />
            </div>
          ) : (
            <div className={`card-bonus${isWild ? " card-bonus-wild" : ""}`}
              style={isWild ? { background: bonusBg } : { "--gc": bonusBg }}
              title={isWild ? (asColor ? `Wild bonus (as ${asColor})` : "Wild bonus — attaches to one of your colors") : undefined} />
          )
        )}
      </div>
      {card.ability && abilityGlyph && (
        <div className="card-ability" title={abilityTitle}>{abilityGlyph}</div>
      )}
      {/* Gems stack in the first column; a pearl ALWAYS sits in the second, so its
          position never shifts from card to card. With no pearl there is a single
          column and this renders exactly as Spender always has. */}
      <div className={`card-cost${pearl ? " card-cost-2col" : ""}`}>
        <div className="cost-col">
          {gems.map(([c, n]) => (
            <div key={c} className="cost-row">
              <div className="cost-gem" style={{ "--gc": GEM_HEX[c] }} />
              <span className="cost-num">{n}</span>
            </div>
          ))}
        </div>
        {pearl > 0 && (
          <div className="cost-col">
            <div className="cost-row">
              <div className="cost-gem" style={{ "--gc": GEM_HEX.pearl }} />
              <span className="cost-num">{pearl}</span>
            </div>
          </div>
        )}
      </div>
      {aiValue != null && (typeof aiValue === "object" ? (
        <div className={`ai-vals${valsMine ? " mine" : ""}`} title={`${who} — ${aiValue._s
          ? "S"
          : aiValue.pot != null
          ? "H3"
          : "H2"} — take / engine / point / cost`}>
          <span><b>T</b>{aiValue.t}</span>
          <span><b>E</b>{aiValue.e}</span>
          <span><b>P</b>{aiValue.p}</span>
          <span><b>C</b>{aiValue.c}</span>
        </div>
      ) : (
        <span className={`ai-val${valsMine ? " mine" : ""}`} title={`${who} (variant H)`}>{aiValue}</span>
      ))}
    </div>
  );
}

/* A gem-in-hand pill (Spender's player panel). Works for any token incl. Duel's pearl. */
export function TokenPill({ color, count, dataToken }) {
  const rim = color === "black" ? "rgba(255,255,255,.4)" : GEM_HEX[color];
  return (
    <span data-token={dataToken ?? color} className="token-pill"
      title={`${count} ${GEM_LABELS[color] || color}`}
      style={{ background: GEM_HEX[color] + "55", border: `1px solid ${rim}` }}>
      {/* light rim so the near-black onyx stays visible on the warm "your turn" panel */}
      <span style={{ width: 10, height: 10, borderRadius: "50%", background: GEM_HEX[color],
        border: color === "black" ? "1px solid rgba(255,255,255,.4)" : "1px solid rgba(255,255,255,.25)",
        display: "inline-block" }} />
      {count}
    </span>
  );
}

/* A BOUGHT-CARD pill: "+N" in that color — Spender's indicator for the cards you own.
 * `extra` appends a game-specific suffix, unspaced so it stays inside a narrow pill
 * (Duel shows the color's prestige as "★N", since 10 points in one color wins).
 * No color initial: the pill is already color-coded, and blue and black share one. */
export function BonusPill({ color, count, extra, title }) {
  const rim = color === "black" ? "rgba(255,255,255,.4)" : GEM_HEX[color];
  return (
    <span data-bonus={color} className="bonus-pill" title={title}
      style={{ background: GEM_HEX[color] + "55", borderColor: rim,
        color: color === "black" ? "#a8a8a8" : GEM_HEX[color] }}>
      +{count}{extra}
    </span>
  );
}

/* One move-log row, in Spender's structure: turn | name | action. `win`/`start` are
 * the review anchors ("X won the game" / "Game started"). */
export function LogEntry({ turn, name, action, clickable, selected, kind, future, onClick }) {
  const extra = kind === "win" ? " log-win" : kind === "start" ? " log-start" : "";
  return (
    <div className={`log-entry${clickable ? " clickable" : ""}${selected ? " log-selected" : ""}${future ? " future" : ""}${extra}`}
      onClick={onClick}>
      {kind ? null : <span className="log-turn">{turn ?? ""}</span>}
      {name ? <span className="log-name">{name}</span> : null}
      <span className="log-action">{action}</span>
    </div>
  );
}

/* Gems + jewel cards — extracted VERBATIM from Spender.jsx. Don't restyle for one
   game only: both import this. */
export const splendorCardCss = _splendorCardCssText;

/* Additions the shared CardView needs beyond Spender's originals: Duel's crowns, wild
   bonus, ability glyph and the pearl's second cost column, plus a `small` variant for
   reserve hands. Kept SEPARATE and applied after the verbatim block, so Spender's own
   rules keep both their content and their order — it simply never emits these. */
export const splendorCardExtraCss = _splendorCardExtraCssText;

/* The move log — extracted VERBATIM from Spender.jsx. It already carries the review
   vocabulary (clickable rows, log-selected, log-win, log-start). */
export const splendorLogCss = _splendorLogCssText;

/* The panel shell — extracted VERBATIM from Spender.jsx. */
export const splendorPanelCss = _splendorPanelCssText;

/* Player pills (gems held + BOUGHT-CARD bonuses) — extracted VERBATIM from Spender.jsx.
   .bonus-pill is the "what cards you own" indicator; .token-pill the gems in hand. */
export const splendorPillCss = _splendorPillCssText;
