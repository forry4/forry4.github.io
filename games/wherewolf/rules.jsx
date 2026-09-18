// Where Wolf?'s how-to-play content. Chrome comes from the shared RulesModal kit
// (shared/lobby.jsx) — this file is only the words, and rides WW's own chunk.
//
// Structured on Orbit's ruleset: Goal of the Game (including the win conditions,
// which are what the whole argument is about) -> Setup -> the night, the day and
// the vote in the order they happen, in a terse rulebook voice.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function WhereWolfRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>One night, one vote, one game. Everyone is secretly dealt a role. Nobody is
        eliminated early and nobody sits out: the whole game is a single night of
        secret actions followed by one argument and one simultaneous vote. There are
        3 ways the game can be won:</p>
      <RulesDefs items={[
        { t: "Village", d: "Wins if at least one WEREWOLF card dies. If there is no werewolf in play at all, the village wins only when nobody dies." },
        { t: "Werewolves", d: "Win if a werewolf is in play and no werewolf dies. The minion wins with them, and killing the minion is not a werewolf death." },
        { t: "Tanner", d: "Wins only by being killed. A tanner death with no werewolf death also blocks the werewolf win — the tanner wins alone." },
      ]} />
      <RulesTip>The role you were DEALT is the role you act as during the night. The
        card in front of you when the night ENDS is the role you are for scoring.
        Those can be different, and if someone swapped your card you will not know —
        you can be a werewolf who spent the night believing they were a villager,
        and you still lose with the wolves.</RulesTip>
    </RulesSection>

    <RulesSection title="Setup">
      <p>3 to 10 players, one device each, and no bots. The host builds a deck of
        exactly players + 3 role cards and everyone is dealt one at random; the 3
        extra cards sit face-down in the center and belong to nobody.</p>
      <p>Everyone can see which roles are in the deck, just not who has what. Because
        3 cards go unused, no role is certain to be in play — a game with two werewolf
        cards may have no werewolf at the table.</p>
    </RulesSection>

    <RulesSection title="The night">
      <p>Roles wake in a fixed order, one at a time, each for a fixed few seconds.
        Your device tells you when it is your turn and what you may do:</p>
      <RulesDefs items={[
        { t: "Werewolves", d: "Wake and see each other. A lone werewolf may instead peek at one center card." },
        { t: "Minion", d: "Sees who the werewolves are, but they do not see the minion. Plays on the wolves' team." },
        { t: "Masons", d: "The two masons see each other. Seeing no other mason means the other mason card is in the center — or that you are being lied to." },
        { t: "Seer", d: "Look at one other player's card, or at two of the three center cards." },
        { t: "Robber", d: "Swap your card with another player's, then look at your new card. You act as the robber all night regardless." },
        { t: "Troublemaker", d: "Swap two OTHER players' cards without looking at either." },
        { t: "Drunk", d: "Swap your card with a center card, blind. You do not get to look, so you will not know what you are." },
        { t: "Insomniac", d: "At the end of the night, look at your own card to see whether it changed." },
        { t: "Villager, Tanner, Hunter", d: "No night action, but the tanner and hunter both change how the vote resolves." },
      ]} />
      <p>Every role in the deck is announced during the night even when all its
        copies are in the center, so silence never gives anything away.</p>
    </RulesSection>

    <RulesSection title="The day">
      <p>Everyone wakes and talks, on a timer. This is the actual game: claim a role,
        ask people to account for what they saw, and work out who is lying. Because
        swaps happen, two players can both be telling the truth and still contradict
        each other.</p>
    </RulesSection>

    <RulesSection title="The vote">
      <p>When the timer runs out, everyone votes at the same time for one player. The
        player with the most votes dies, and if several tie for most then all of them
        die. If nobody receives at least 2 votes, nobody dies. A hunter who dies also
        kills whoever they voted for.</p>
      <p>Teams are then settled by the card in front of each player at dawn, not the
        one they were dealt.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <p>Everyone needs their own device. The app narrates the night out loud, so one
        player can run it from a speaker while everyone else acts on their own
        screen.</p>
    </RulesSection>
  </>;
}
