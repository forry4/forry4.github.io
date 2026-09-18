import { RulesDefs, RulesFacts, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function SecretNamesRules() {
  return <>
    <RulesFacts items={[
      { k: "Players", v: "2, on the same side" },
      { k: "Length", v: "9 turns (10 or 11 for an easier run)" },
      { k: "Goal", v: "Find all 15 agents before the timer runs out" },
    ]} />
    <RulesSection title="The one rule everything follows from">
      <p>You each hold your own key card, and <b>your key describes what happens when
        your partner guesses</b> — not what happens when you do. So the words marked
        as agents on your card are the words you have to get your partner to say.
        Your partner's card is different, and you never see it.</p>
      <RulesTip>Three words are agents on both cards, which is why there are 15
        agents between you rather than 18. Finding one counts once, for both of you.</RulesTip>
    </RulesSection>
    <RulesSection title="Your turn">
      <RulesDefs items={[
        { t: "Give a clue", d: "One word and a number, related to the agents on YOUR key. The number says how many words you mean; it is not a limit on guesses." },
        { t: "Your partner guesses", d: "They tap words on the grid. Every correct agent is covered for good, and they may keep going as long as they keep being right — and may use any earlier clue, not just this one." },
        { t: "The turn ends", d: "Either they choose to stop after at least one guess, or they hit a bystander. Either way it costs exactly one timer token, however many agents they found." },
        { t: "Then you swap", d: "Your partner gives the next clue and you guess." },
      ]} />
    </RulesSection>
    <RulesSection title="What a word can turn out to be">
      <RulesDefs items={[
        { t: "Agent", d: "Covered permanently, for both of you. Keep guessing." },
        { t: "Bystander", d: "The turn ends and a token is spent — but only for the player who guessed it. The same word can still be an agent from the other direction, so it stays on the board." },
        { t: "Assassin", d: "You both lose, immediately. There are three on each card, and a word that is safe from your side can be an assassin from theirs." },
      ]} />
      <p>The board marks a bystander you have already hit, so you do not spend a
        second turn rediscovering it. Your own key colours stay on the grid the
        whole game — they are yours to read.</p>
    </RulesSection>
    <RulesSection title="Running out of clues, and passing">
      <p>Once all nine agents on your key have been found, you have nothing left to
        clue and your partner gives every remaining clue. You can also <b>pass</b>
        instead of giving a clue, which hands this turn to your partner and retires
        you from clue-giving for the rest of the game. Neither of those wins the
        game on its own — victory is all 15 agents, always.</p>
    </RulesSection>
    <RulesSection title="Sudden death">
      <p>When the last timer token is spent — or when neither of you can clue any
        more — the game does not end. You get one final run at every agent still
        hidden, with no new clues: either player may guess, one at a time, using
        everything said so far. Every guess must be an agent. A bystander or an
        assassin ends it there.</p>
    </RulesSection>
    <RulesSection title="Keeping it fair">
      <p>A clue relates to the words by meaning. It cannot use a word's position on
        the grid, its spelling or its letter count, and it cannot be a word still
        showing on the board (the console rejects that one for you). Everything
        else is between the two of you — and once you have given your clue, say
        nothing: no nudges, no reactions, and never a hint about what your own key
        says.</p>
    </RulesSection>
  </>;
}
