import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function PinchRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Build straight rows of five markers showing your color. Each row you
        score lets you remove one of your rings from the board.</p>
      <RulesDefs items={[
        { t: "Standard", d: "Remove three of your rings to win." },
        { t: "Blitz", d: "Score one row to win." },
      ]} />
    </RulesSection>

    <RulesSection title="Setup">
      <p>Pinch is for two players. One player takes pearl and moves first; the
        other takes obsidian. Starting with an empty board, alternate placing
        one ring on any open intersection until all five rings per player are in play.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <RulesDefs items={[
        { t: "1. Choose a ring", d: "Pick one of your rings that has a legal destination." },
        { t: "2. Leave a marker", d: "A marker showing your color is placed where that ring began." },
        { t: "3. Move the ring", d: "Slide it in one straight line to an open intersection." },
        { t: "4. Flip markers", d: "Turn over every marker the ring crossed." },
        { t: "5. Score rows", d: "Resolve completed rows before the next turn begins." },
      ]} />
    </RulesSection>

    <RulesSection title="Moving a ring">
      <p>A ring may travel across any number of empty intersections. It cannot
        cross another ring and cannot finish on a ring or marker.</p>
      <p>After reaching a continuous group of markers, the ring must stop on the
        first empty intersection beyond that group. It cannot continue through
        further empty spaces.</p>
      <p>If none of your rings has a legal move, your turn passes automatically.</p>
    </RulesSection>

    <RulesSection title="Flipping markers">
      <p>After the ring lands, every marker it crossed flips to the opposite
        color. The new marker left at the ring’s starting point does not flip.
        Markers never move to another intersection.</p>
    </RulesSection>

    <RulesSection title="Completing rows">
      <p>A row is five adjacent markers of one color on one straight board line.
        Rings do not count. Remove the five markers, then choose one of your
        rings to remove as your score.</p>
      <p>For a run longer than five, choose which adjacent five to remove. If
        several rows remain after a removal, keep scoring them one at a time.
        The player who moved resolves their rows first, followed by the opponent.</p>
      <RulesTip>A move can complete your opponent’s row. They score it before
        taking their next turn.</RulesTip>
    </RulesSection>

    <RulesSection title="End of the game">
      <p>The game ends immediately when a player removes the winning ring. If
        the final marker enters play without a winner, the player who has
        removed more rings wins; equal scores are a draw.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <p>Select one of your rings to reveal its legal destinations, then select
        a destination. Cyan marks actions the server will accept. During scoring,
        select the highlighted row and then the ring you want to remove.</p>
    </RulesSection>
  </>;
}
