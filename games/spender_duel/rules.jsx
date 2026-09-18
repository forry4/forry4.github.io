// Spender Duel's how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides Duel's own chunk.
//
// Structured on Orbit's ruleset: Goal of the Game (the three victory conditions,
// which is the shape Orbit's own goal section has) -> Setup -> Turn overview ->
// the subsystems -> End of turn, in a terse rulebook voice.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function DuelRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Two players buy cards, each of which permanently discounts every later
        purchase, and take their tokens off a shared 5×5 grid in straight lines — so
        what you take also decides what you leave behind. There are 3 victory
        conditions:</p>
      <RulesDefs items={[
        { t: "Prestige victory", d: "Reach 20 prestige points in total." },
        { t: "Crown victory", d: "Reach 10 crowns, the crown symbols printed on cards and royals." },
        { t: "Color victory", d: "Reach 10 points within a single bonus color, counting only points printed on cards that share it." },
      ]} />
      <p>The game ends immediately as soon as a player meets 1 of these three
        conditions. There is no final round, which makes the crown and color routes
        real ambushes: a player on 9 points can be one card from winning if those
        points are all green.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>Exactly 2 players, a friend or the bot. The 25 grid cells are filled from a
        bag of 4 tokens in each of the 5 colors, 2 pearls and 3 gold, laid out from
        the center outward in a spiral.</p>
      <p>The card pyramid is dealt 5 face-up level-1 cards (cheap), 4 level-2 and 3
        level-3 (expensive, high points and crowns), each replaced from its deck when
        taken. Beside it sit 4 royal cards, claimed by crowns rather than bought, and
        3 privilege scrolls, which start in the middle between the players.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>First, optionally, and in this exact order:</p>
      <RulesDefs items={[
        { t: "1. Spend privileges ⚜", d: "Each scroll takes any single gem or pearl off the grid for free and returns to the middle." },
        { t: "2. Replenish", d: "Refill the empty grid cells from the bag, center-out. This hands your opponent a privilege, so it is a real cost." },
      ]} />
      <p>Then take exactly 1 of the three following actions:</p>
      <RulesDefs items={[
        { t: "A. Take tokens", d: "1 to 3 tokens from a single unbroken straight line — horizontal, vertical or diagonal. Empty cells and gold break the line, and gold cannot be taken this way." },
        { t: "B. Take gold and reserve", d: "Take a gold token from the grid and reserve any face-up card or the unseen top card of a deck. Reserves are secret from your opponent." },
        { t: "C. Buy a card", d: "From the pyramid or from your reserve, paying its cost. Spent tokens go back into the bag." },
      ]} />
      <RulesTip>Taking 3 tokens of one color, or 2 pearls, gives your opponent a
        privilege. That is the price of a greedy line.</RulesTip>
    </RulesSection>

    <RulesSection title="Cards and bonuses">
      <p>A card's cost is paid in the colors shown. Each card already owned gives a
        permanent bonus that discounts that color, a few cards give two bonuses at
        once, and gold is a wild that covers any one gem. Cards can also carry:</p>
      {/* The glyphs are the ones painted on the real cards — a legend is worth more
          here than prose, since a new player's first question is what ↻ means. */}
      <RulesDefs items={[
        { t: "Points", d: "Prestige, counting toward the 20-point win and toward the one-color win if the card has a bonus color." },
        { t: "Crowns", d: "Count toward the 10-crown win and unlock royal cards." },
        { t: "↻  Take again", d: "Immediately take another turn." },
        { t: "+● Matching token", d: "Take one token from the grid of that card's own color (the dot is painted in that color)." },
        { t: "⚜  Take a privilege", d: "Gain a scroll, from the middle or off your opponent if the middle is empty." },
        { t: "✋  Steal", d: "Take one token, never gold, straight out of your opponent's hand." },
        { t: "Grey (wild) cards", d: "Have no color of their own. When bought they attach to a color you already own and count as that color from then on, points included." },
      ]} />
    </RulesSection>

    <RulesSection title="Crowns and royals">
      <p>On reaching 3 crowns, and again at 6, a player immediately claims one of
        the four royal cards. Royals are worth 2–3 points and most carry an ability —
        another turn, a steal, a privilege. Crowns therefore pay twice: toward the
        royals, and toward the 10-crown win.</p>
    </RulesSection>

    <RulesSection title="End of turn">
      <p>A player may end their turn holding at most 10 tokens, gold and pearls
        included, and discards the excess back to the bag. Three reserved cards is
        the maximum.</p>
      <p>Only 3 privilege scrolls exist in total, so a player owed one when the
        middle is empty takes it off their opponent instead.</p>
    </RulesSection>
  </>;
}
