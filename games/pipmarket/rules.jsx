import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function PipMarketRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Buy dice from the market, build them into your board, and score straight
        lines of matching faces. After three rounds, your points plus the money
        you have left is your score. The highest score wins; a shared top score
        is a shared win.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>Pip Market is for two to four players. The market holds one set per
        player plus one, and each set is five vertical pairs of freshly rolled
        dice. A pair costs its position in its set: the leftmost costs 1, the
        next 2, up to 5.</p>
      <p>Seats are drawn at random. The first player starts with 10 money and
        everyone else with 12. Nobody may ever hold more than 18.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>Players take turns in seat order until the market is empty. On your
        turn, do one thing:</p>
      <RulesDefs items={[
        { t: "A. Buy a pair", d: "Pay its price and place both dice on your board. The pairs to its right slide left and get cheaper." },
        { t: "B. Take 2 money", d: "Not allowed at 18." },
        { t: "C. Reroll a column", d: "Pay a column's price to reroll the dice in that position in every stall: pay 3 and the third column of each stall is rerolled. Once per round." },
      ]} />
      <p>A pair you have no legal place for cannot be bought. A player with no
        legal action is skipped.</p>
    </RulesSection>

    <RulesSection title="Placing dice">
      <p>Dice keep the faces they were rolled with. A pair stays together but may
        be turned either way. After your first pair, each new pair must touch a
        die already on your board, side to side.</p>
      <p>There is no fixed grid, but the dice on your board may never span more
        than six rows or six columns.</p>
    </RulesSection>

    <RulesSection title="Scoring lines">
      <p>When the market is empty, players take turns scoring one line at a
        time, starting with whoever bought the last pair. A line is a straight,
        unbroken row or column of one face that is at least as long as the
        face: one 1, two 2s, three 3s, up to six 6s. Part of a longer run may be
        scored on its own.</p>
      <RulesDefs items={[
        { t: "Points", d: "The face times the number of dice." },
        { t: "Money", d: "+1 for the line; +5 if it scored 15 or more; a line of 30 or more sets you to 18." },
      ]} />
      <p>After a line is removed, every die left on your board must still touch
        another die. Scoring is compulsory: while you have a line you can score,
        you must score one on your turn. You choose which line, and so the order.
        A player with no line left is out of scoring for the round.</p>
      <RulesTip>Order matters: score a die that would be stranded first. Two 1s
        scored one at a time earn two money instead of one.</RulesTip>
    </RulesSection>

    <RulesSection title="End of the round">
      <p>When nobody has a line left, every scored die is rerolled and dealt back
        into the market as evenly as possible: no stall holds more than one die
        more than another. Within a stall the dice stand in vertical pairs, and a
        stall with an odd count ends on a single die. Dice you did not score stay
        on your board. Whoever bought the last pair goes first next round.</p>
    </RulesSection>

    <RulesSection title="End of the game">
      <p>The game ends after the third round, or at once if nobody scored in a
        round. Add your money to your points.</p>
      <RulesTip>Unscored dice carry over, so a short row of 5s or 6s can be grown
        across rounds into a 30-point line.</RulesTip>
    </RulesSection>

    <RulesSection title="At the table">
      <p>Select a lit pair in the market, then a glowing cell on your board.
        Select the same cell again to turn the pair, and Place to buy it. When
        scoring, select a lit die or a line from the list, then Score line.</p>
    </RulesSection>
  </>;
}
