// Black Castle's how-to-play content. Chrome comes from the shared RulesModal kit.
//
// Structured on Orbit's ruleset: Goal of the Game -> Setup -> Turn overview ->
// the subsystems -> End of the game, in a terse rulebook voice.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function BlackCastleRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Guide your clan through Himeji Castle over three rounds. Place dice to
        deploy Courtiers, Warriors and Gardeners, collect resources, and score the
        most points when the castle closes.</p>
      <p>After the third round everything is counted up. The highest total wins,
        and turn order breaks a tie.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>2 to 4 players, and a room can be filled with one human and up to three
        Easy random bots.</p>
      <p>Each table uses the standard base game: three bridges of coral, obsidian
        (black) and ivory (white) dice; five castle rooms; gardens, training yards
        and a Daimyo card. Starting resource and action pairs are drafted in reverse
        Heron order.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>A turn is three steps, in order:</p>
      <RulesDefs items={[
        { t: "1. Take a die", d: "Choose a die from either end of any bridge. A low (left) die also activates all your lantern rewards when placed; a high (right) die does not." },
        { t: "2. Place it", d: "Choose a highlighted castle room, the Well, Outside the Walls, or your domain. The preview shows the active effect and coin cost: gain the difference above the base value, or pay it below. Confirm to place your die." },
        { t: "3. Resolve actions", d: "Activate the room, worker, resource, lantern or Well benefit shown by the destination, then press End Turn." },
      ]} />
      <p>Your domain gives one resource plus the light action of your domain card:
        coral gives food, obsidian gives iron, and ivory gives pearl. Resources are
        capped at seven; seals are capped at five.</p>
    </RulesSection>

    <RulesSection title="Workers and spaces">
      <p>Courtiers climb from the Gate to the first and second floors and finally
        the Daimyo. Warriors dispatched Outside occupy Training Yards and score
        their printed value for each Courtier inside the castle. Gardeners occupy
        Gardens and score the garden's printed value.</p>
      <p>A Well placement grants a seal and two hidden-tile benefits. Daimyo Seals
        can also be traded one for one coin, or two for one resource.</p>
    </RulesSection>

    <RulesSection title="Passage of Time">
      <p>When Influence crosses one of the three season checkpoints, pay its
        required Daimyo Seals or stop there.</p>
      <p>After rounds one and two, each occupied Garden whose bridge still has a die
        activates once. Turn order is then rebuilt from Influence and the bridges
        are rerolled.</p>
    </RulesSection>

    <RulesSection title="End of the game">
      <p>After round three, score coins and seals in groups of five, then resources,
        Influence, workers, Training Yards and Gardens.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <RulesTip>Undo is available after taking a die and before a hidden Well
        benefit is revealed. Once that information is shown, finish the turn
        normally.</RulesTip>
    </RulesSection>
  </>;
}
