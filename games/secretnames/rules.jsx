import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function SecretNamesRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Work together to identify all 15 unique agents before the timer runs out.
        The team wins as soon as every agent has been found. An assassin loses the
        mission immediately.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>SecretNames is a two-player cooperative game. Deal a 5×5 grid of 25
        words, two private key cards, and nine timer tokens. Each key has nine
        agents, three assassins and thirteen bystanders. The keys share three
        agents, so the board contains 15 unique agents.</p>
      <p>The host chooses nine, ten or eleven timer tokens, then deals the board.
        One player gives the first clue; the other player guesses. The roles
        alternate after each normal turn.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>During a normal turn, the clue-giver and guesser take these steps:</p>
      <RulesDefs items={[
        { t: "A. Give a clue", d: "Say one word of up to 16 letters and a number related to the agents on your key. The number does not limit the number of guesses." },
        { t: "B. Guess", d: "The other player taps words on the grid. A correct agent is covered permanently, and the guesser may continue while every guess is correct." },
        { t: "C. End the turn", d: "After at least one correct guess, the guesser may stop. A bystander also ends the turn. Either ending spends exactly one timer token." },
      ]} />
      <RulesTip>Your key describes what happens when your partner guesses. You
        clue the agents on your own key, but the other player's key resolves the
        guesses.</RulesTip>
    </RulesSection>

    <RulesSection title="Key cards and word roles">
      <RulesDefs items={[
        { t: "Agent", d: "The team needs this word. Cover it permanently when found; it counts for both players." },
        { t: "Bystander", d: "The turn ends and one timer token is spent for the player who guessed it. Record it for that player; the same position can still be an agent from the other direction." },
        { t: "Assassin", d: "The mission ends in a loss immediately. A word can be safe on one key and an assassin on the other." },
      ]} />
    </RulesSection>

    <RulesSection title="Passing and exhausted sides">
      <p>When all nine agents on your key are found, you are exhausted and no
        longer give clues. Your partner gives every remaining clue. You may also
        pass instead of giving a clue; passing is permanent, costs no timer
        token, and hands the current turn to your partner.</p>
      <p>If neither player can give another clue, enter sudden death immediately.
        Passing does not win the game by itself: all 15 unique agents still have
        to be found.</p>
    </RulesSection>

    <RulesSection title="End of turn">
      <p>A normal turn costs one timer token, whether it ends on a bystander or
        because the guesser stops. Finding the last agent wins immediately and
        spends no token.</p>
      <p>When the last token is spent, or neither player can clue, the game enters
        sudden death instead of ending.</p>
    </RulesSection>

    <RulesSection title="End of the game">
      <p>In sudden death there are no new clues. Either player may guess one word
        at a time, using the clues already given, and every guess must be an
        agent. A bystander or an assassin ends the mission in a loss. Finding the
        last remaining agent wins.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <p>A clue must relate to the words by meaning. It cannot use a word's
        position, spelling or letter count, and it cannot be an uncovered word on
        the grid. After giving a clue, say nothing else: no nudges, reactions or
        hints about your key.</p>
    </RulesSection>
  </>;
}
