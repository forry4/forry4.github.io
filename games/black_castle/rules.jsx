import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function BlackCastleRules() {
  return <>
    <RulesSection title="Goal">
      <p>Guide your clan through Himeji Castle over three rounds. Place dice to
        deploy Courtiers, Warriors, and Gardeners, collect resources, and earn the
        most points when the castle closes.</p>
    </RulesSection>
    <RulesSection title="Setup">
      <p>Each table uses the standard base game: three bridges of coral, black, and
        white dice; five castle rooms; gardens, training yards, and a Daimyo card.
        Starting resource and action pairs are drafted in reverse Heron order.</p>
      <RulesTip>Black Castle supports any 2–4 seats. A room can be filled with one
        human and up to three Easy random bots.</RulesTip>
    </RulesSection>
    <RulesSection title="Your turn">
      <RulesDefs items={[
        { t: "1. Take a die", d: "Choose a die from either end of any bridge. The nearest die slides toward the open end." },
        { t: "2. Place it", d: "Use a castle room, the Well, Outside the Walls, or your personal domain. Compare the die with the printed value: gain the difference when higher, or pay it when lower." },
        { t: "3. Resolve actions", d: "Activate the room, worker, resource, lantern, or Well benefit shown by the destination. Then press End Turn." },
      ]} />
      <p>Dice in your personal domain are colour-coded: coral moves Courtiers,
        black moves Gardeners, and white moves Warriors. Resources are capped at
        seven; seals are capped at five.</p>
    </RulesSection>
    <RulesSection title="Workers and spaces">
      <p>Courtiers climb from the Gate to the first and second floors and finally
        the Daimyo. Warriors dispatched Outside occupy Training Yards and score
        their printed value for each Courtier inside the castle. Gardeners occupy
        Gardens and score the garden's printed value. A Well placement grants a
        seal and two hidden-tile benefits. Daimyo Seals can also be traded one for
        one coin or two for one resource.</p>
    </RulesSection>
    <RulesSection title="Passage of Time and scoring">
        <p>When Influence crosses one of the three season checkpoints, pay its
        required Daimyo Seals or stop there. After rounds one and two, each
        occupied Garden whose bridge still has a die activates once, then turn
        order is rebuilt from Influence and the bridges are rerolled. After round
        three, score coins and seals in groups of five, resources, Influence,
        workers, Training Yards, and Gardens. The highest total wins; turn order
        breaks ties.</p>
    </RulesSection>
    <RulesSection title="Undo">
      <p>Undo is available after taking a die and before a hidden Well benefit is
        revealed. Once that information is shown, finish the turn normally.</p>
    </RulesSection>
  </>;
}
