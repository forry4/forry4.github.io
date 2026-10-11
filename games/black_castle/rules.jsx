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
        (black) and ivory (white) dice; five castle rooms; six gardens; three training
        yards carrying four Yard tiles; and one Daimyo's Favor card on the top floor.
        Starting resource and action pairs are drafted in reverse Heron order.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>A turn is three steps, in order:</p>
      <RulesDefs items={[
        { t: "1. Take a die", d: "Choose a die from either end of any bridge. A low (left) die also activates all your lantern rewards when placed; a high (right) die does not." },
        { t: "2. Place it", d: "Choose a highlighted castle room, the Well, Outside the Walls, or your domain. The preview shows the active effect and coin cost: gain the difference above the base value, or pay it below. Confirm to place your die." },
        { t: "3. Resolve actions", d: "Activate the room, worker, resource, lantern or Well benefit shown by the destination, then press End Turn." },
      ]} />
      <p>A domain line pays one of its resource (coral food, obsidian iron, ivory
        pearl) plus every reward its departed workers have uncovered, then performs
        the action printed beside that line on your action card. Resources are capped
        at seven; seals are capped at five.</p>
      <p>Any action a card, tile, garden or Daimyo slot grants may be declined.</p>
    </RulesSection>

    <RulesSection title="Workers and spaces">
      <RulesDefs items={[
        { t: "Courtier action", d: "An audience (2 coins: a Courtier to the Gate), a climb (2 pearl a floor, 5 for two), or both. Climbing into a room takes its card into your domain and performs one of its light actions. Reaching the Daimyo collects your Lantern, then takes a free slot on the Daimyo's Favor card and its reward." },
        { t: "Warrior action", d: "Pay a yard's iron and perform its Yard tiles. A Warrior scores its yard's value for each of your Courtiers inside the castle." },
        { t: "Gardener action", d: "Pay a garden's food and perform its action. A Gardener scores the garden's value." },
      ]} />
      <p>A Well placement grants a seal plus the rewards on its two face-up tiles,
        the same every visit. Daimyo Seals can also be traded one for one coin, or
        two for one resource.</p>
    </RulesSection>

    <RulesSection title="Passage of Time">
      <p>When Influence crosses one of the three season checkpoints, pay its
        required Daimyo Seals or stop there.</p>
      <p>After rounds one and two, turn order is rebuilt from Influence. Then each
        occupied Garden whose bridge still has a die activates once for its Gardener,
        clan by clan in the new order, and the bridges are rerolled.</p>
    </RulesSection>

    <RulesSection title="End of the game">
      <p>After round three, score coins and seals in groups of five, then resources,
        Influence, workers, Training Yards and Gardens.</p>
    </RulesSection>

    <RulesSection title="At the table">
      <RulesTip>Undo takes back your whole turn until you press End Turn.</RulesTip>
    </RulesSection>
  </>;
}
