// Dissonance's how-to-play content. Chrome comes from the shared RulesModal kit.
//
// Structured on Orbit's ruleset: Goal of the Game -> Setup -> the phases in the
// order the engine runs them -> Scoring, in a terse rulebook voice. The phase
// order is auction -> talon -> kontra -> play (engine.py sets `phase` in exactly
// that sequence); the older copy of this file described trick play before the
// talon and the Kontra, which is not the order a round actually happens in.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function DissonanceRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>A two-player trick-taking game in which winning is not always good.
        Even-numbered tricks are worth +2 trick points; odd-numbered tricks cost
        −1. The art is choosing which tricks to take.</p>
      <p>Each round one player contracts to reach a trick-point target. Scores carry
        across rounds, and the first player to 200 points wins the match.</p>
      <RulesTip>These rules describe Classic mode. Skat, Minor, Dummy and Quartet
        are beta modes with their own deals and their own scoring, chosen at game
        setup.</RulesTip>
    </RulesSection>

    <RulesSection title="Setup">
      <p>Exactly 2 players, a friend or the bot. The 32-card deck holds 7, 8, 9, 10,
        J, Q, K and A in each suit.</p>
      <p>Each player receives seven cards in hand and three two-card piles. Only the
        top card of a pile is playable; when it is gone, the card below becomes
        visible and playable. One middle-pile card starts face up, and six cards sit
        out of the round unseen.</p>
    </RulesSection>

    <RulesSection title="The auction">
      <p>Bid a level from 1 to 10 and a denomination: one of the four suits, or
        no-trump. The winning bid makes its player declarer, the denomination becomes
        trump, and the level is that player's trick-point target.</p>
      <RulesDefs items={[
        { t: "Opening", d: "The opener must make a bid." },
        { t: "Raising", d: "Beat the standing bid with a higher denomination at the same level, or a higher level in a denomination you have not already named. You may also pass." },
        { t: "Jumps", d: "The final bid's rise over the level it overtook is its jump, and an opening bid counts as a jump over level 0. If the contract is then set, the defender is paid an extra 5 points per level jumped — so climbing a rung at a time is cheap and leaping is not. A same-level overtake jumps nothing." },
      ]} />
    </RulesSection>

    <RulesSection title="The talon">
      <p>The declarer may take one of three revealed talon cards, then discards one
        card from hand face-down.</p>
    </RulesSection>

    <RulesSection title="Kontra">
      <p>After the talon, the defender may call Kontra or let the contract stand.
        Kontra doubles the round's payout either way — what the declarer earns for
        making it, and what a set costs. It is the defender's chance to raise the
        stakes on a contract they believe is misjudged.</p>
    </RulesSection>

    <RulesSection title="Playing tricks">
      <p>The declarer leads trick one, which is odd and therefore negative. You must
        follow the suit led when you can; otherwise play any available card, and
        trumping is allowed but never required. The highest trump wins a trick, and
        with no trump the highest card in the led suit wins. The winner leads the
        next trick.</p>
      <p>Tricks alternate in value: the 1st, 3rd, 5th and so on are worth −1, and the
        2nd, 4th, 6th and so on are worth +2.</p>
    </RulesSection>

    <RulesSection title="Scoring">
      <p>If the declarer makes the contract, they score N × N for a level of N, plus
        1 for every trick point above N. If they miss it, the defender scores 5 for
        every point short, plus any jump bonus from the auction.</p>
      <p>A declarer who takes no scoring trick at all is not set: they make Null
        instead, for a flat 20 points.</p>
    </RulesSection>
  </>;
}
