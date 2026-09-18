// Spender's how-to-play content. Chrome (panel, scrolling, typography) comes from
// the shared RulesModal kit — this file is ONLY the words, so the rules can grow
// without touching the 3,000-line screen file, and it rides Spender's own chunk.
//
// Structured on Orbit's ruleset: Goal of the Game (what you are doing and how the
// game is won) -> Setup -> Turn overview -> the subsystems -> End of turn, in a
// terse rulebook voice. The player count lives in Setup and the win condition in
// Goal, which is where a reader looks for them.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function SpenderRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Players buy gem mines and workshops to collect prestige points. Every card
        bought is a permanent discount on every later purchase, so cheap early cards
        are what make expensive high-point cards affordable.</p>
      <p>The moment a player reaches the target — 15 prestige in Classic, 21 in Long
        — the round is played out so that everyone has taken the same number of
        turns. The highest prestige then wins, and a tie goes to whoever bought
        fewer cards.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>2 to 4 players, or 2 against the bot. The bank holds five gem colors —
        white, blue, green, red and black — with 4 of each at two players, 5 at
        three and 7 at four, plus 5 gold in every game.</p>
      <p>Three rows of cards are dealt four face up each. The bottom row is cheap
        and mostly worth no points, the middle row costs more and pays 1–3 points,
        the top row is expensive and pays 3–5. Nobles, one more than the number of
        players, are laid out beside them.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>Take 1 of the four following actions. You may not pass, and you may not
        combine two of them in one turn:</p>
      <RulesDefs items={[
        { t: "A. Take 3 gems", d: "One each of three different colors." },
        { t: "B. Take 2 gems", d: "Both of one color, allowed only while at least 4 of that color remain in the bank." },
        { t: "C. Buy a card", d: "From the face-up rows or from your own reserve, paying its cost back to the bank." },
        { t: "D. Reserve a card", d: "Put a face-up card, or the unseen top card of a deck, into your hand and take 1 gold." },
      ]} />
      <RulesTip>Buying or reserving a face-up card immediately flips a replacement
        from that row's deck, so the board a player leaves behind is never quite the
        one they acted on.</RulesTip>
    </RulesSection>

    <RulesSection title="Buying and bonuses">
      <p>A card's cost is printed down its left edge — two white and one blue, say —
        and is paid back to the bank. Every card already bought shows a gem in its
        corner: that is a permanent bonus, and each bonus of a color reduces that
        color's cost by 1 on every future purchase, forever. Own three white cards
        and a cost of three white is free.</p>
      <p>Gold is a wild. One gold stands in for one gem of any color when buying,
        and reserving is the only action that takes one.</p>
    </RulesSection>

    <RulesSection title="Reserving">
      <p>A reserved card is out of every opponent's reach and is bought later like
        any other card. The top card of a deck may be reserved unseen, and stays
        hidden from everyone until it is bought. Three reserved cards is the
        maximum.</p>
    </RulesSection>

    <RulesSection title="Nobles">
      <p>Each noble lists its requirement in card bonuses rather than gems — 4 red
        and 4 green, or 3 black, 3 red and 3 white. At the end of a turn, a player
        whose bonuses meet a noble's requirement is visited by that noble for 3
        points. If several qualify the player chooses, and only one may arrive per
        turn. Nobles cost nothing and can be neither bought nor reserved.</p>
    </RulesSection>

    <RulesSection title="End of turn">
      <p>A player may end their turn holding at most 10 tokens, gold included, and
        discards back down to 10 before play passes on. Card bonuses are not tokens
        and never count toward the limit.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <p>Click gem tokens to select them and press Take; clicking a selected gem
        puts it back. Click a card to select it and press Buy — cards you cannot
        currently afford are dimmed. To reserve, click the gold coin and then any
        card or face-down deck, in either order.</p>
    </RulesSection>
  </>;
}
