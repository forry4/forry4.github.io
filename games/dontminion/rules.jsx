// Dontminion's how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides Dontminion's own chunk.
//
// Structured on Orbit's ruleset: Goal of the Game -> Setup -> Turn overview -> the
// subsystems -> End of the game, in a terse rulebook voice. The A/B/C phases were
// already lettered, which is the same shape Orbit gives its three turn actions.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function DontminionRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>A deck-building game. Everyone starts with the same weak ten-card deck and
        buys cards from a shared Supply in the middle. Everything bought goes into
        your own deck, gets shuffled in, and comes back around to be played later, so
        the game is about improving the deck you keep drawing from.</p>
      <p>At the end, whoever has the most victory points in their deck wins. A tie
        goes to whoever took fewer turns.</p>
      <RulesTip>Victory cards are dead weight. They do nothing when you draw them —
        no coins, no actions — and only count at the very end. So buying points makes
        your deck worse at buying more points, and knowing WHEN to stop improving and
        start hoarding is the whole game.</RulesTip>
    </RulesSection>

    <RulesSection title="Setup">
      <p>2 to 4 players, and bots can fill any of the seats. Each player begins with
        7 Coppers and 3 Estates, shuffled, and draws 5 cards as their opening hand.</p>
      <p>The Supply always holds money (Copper $1, Silver $3, Gold $6), points
        (Estate 1 VP, Duchy 3 VP, Province 6 VP), Curses at −1 VP, and ten kingdom
        piles dealt at random from the expansions the host enabled. Those ten piles
        change every game, and they are the game: the same rules produce a completely
        different puzzle each time.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>A turn is three phases, in order. You get 1 action and 1 buy by default;
        cards that say "+1 Buy" or "+2 Actions" raise those for that turn only.</p>
      <RulesDefs items={[
        { t: "A. Action phase", d: "Play ONE Action card from your hand. Cards themselves can grant more actions — \"+1 Action\" lets you play another — which is how long chains happen. With no Action cards, skip straight to B." },
        { t: "B. Buy phase", d: "Play Treasures from your hand for coins, then buy ONE card from the Supply costing no more than your coins. The card goes to your DISCARD pile, not your hand. You cannot play more Treasures once you have bought." },
        { t: "C. Clean-up", d: "Everything you played and everything still in your hand goes to the discard pile. Draw a fresh 5 cards, and play passes." },
      ]} />
    </RulesSection>

    <RulesSection title="How your deck cycles">
      <p>When your draw pile runs out, your discard pile is shuffled to become the
        new draw pile. That is why a card you buy actually shows up: it enters the
        discard, and comes back on the next shuffle.</p>
      <p>It also means every card you add dilutes the rest. A deck of 10 sees each
        card often; a deck of 40 rarely.</p>
    </RulesSection>

    <RulesSection title="Card types">
      <RulesDefs items={[
        { t: "Treasure", d: "Played in the buy phase for coins. Copper $1, Silver $3, Gold $6." },
        { t: "Action", d: "Played in the action phase. Draws cards, gives coins, gives extra actions and buys, attacks — read the card." },
        { t: "Victory", d: "Estate 1, Duchy 3, Province 6. Worth nothing during play." },
        { t: "Curse", d: "−1 VP, handed to you by attacks. Pure junk." },
        { t: "Attack", d: "An Action that hits the other players: discarding down, handing out Curses, and worse." },
        { t: "Reaction", d: "Revealed from your hand when something happens to you. A Moat revealed from hand blocks an attack against you." },
      ]} />
    </RulesSection>

    <RulesSection title="End of the game">
      <p>The game ends immediately at the end of a turn when either the Province
        pile is empty, or any three Supply piles are empty. With Colonies in the
        game, emptying the Colony pile ends it too.</p>
      <p>Everyone then counts the victory points in their entire deck — draw pile,
        discard, hand, everything.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <p>Right-click any card, or press and hold it on a touch screen, to read its
        full text at any time, anywhere on the board. With 300+ cards in the pool you
        will use this constantly, and it is never a move.</p>
      <p>A plain click does whatever the card is for right now: play it, buy it, or
        pick it for whatever the current card is asking. The button under the Supply
        moves you on — "To buy phase →" and then "End turn" — and Play all treasures
        saves clicking seven Coppers.</p>
    </RulesSection>
  </>;
}
