// Castles of Crimson's how-to-play content. Chrome comes from the shared RulesModal
// kit (shared/lobby.jsx) — this file is only the words, and rides CoC's own chunk.
//
// Structured on Orbit's ruleset: Goal of the Game -> Setup -> Turn overview -> the
// subsystems -> end of phase and end of the game, in a terse rulebook voice.
import { RulesDefs, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function CocRules() {
  return <>
    <RulesSection title="Goal of the Game">
      <p>Each player owns a duchy — a personal board of empty hexagonal spaces
        grouped into colored regions — and fills it with tiles: mines that pay out,
        ships that bring trade goods, buildings that grant extra actions,
        monasteries with unique powers. Filling a whole region scores points, and
        filling it early scores far more.</p>
      <p>The game runs 5 phases of 5 rounds — 25 turns each, and that is the entire
        clock. Most victory points at the end wins.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>2 to 4 players, or 2 against the bot. Each player begins with one castle
        already placed in their duchy, 1 silver, 3 goods and no workers.</p>
      <p>Every space in a duchy shows a number from 1 to 6 and belongs to a colored
        region. To fill a space you need a die showing its number, and the tile you
        place must be the type that space's color calls for. Every tile placed after
        the starting castle must be adjacent to something you already own, so a
        duchy grows outward from that castle.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>Roll 2 dice. Each die buys 1 action, so you act twice per turn. Before
        using a die you may spend a worker to change it by 1; nudging a die back
        toward the number it actually rolled refunds that worker. The five actions:</p>
      <RulesDefs items={[
        { t: "A. Take a tile", d: "From the depot whose number matches the die, into your storage. Storage holds 3 tiles — if it is full, something has to go." },
        { t: "B. Place a tile", d: "From storage onto an empty space showing the die's number, adjacent to your duchy. This is the action that scores." },
        { t: "C. Sell goods", d: "Sell a batch of goods whose number matches the die, for silver and VP." },
        { t: "D. Buy a black tile", d: "From the central depot for 2 silver, at any die value." },
        { t: "E. Take 2 workers", d: "At any die value. Workers are how you fix a bad roll." },
      ]} />
      <RulesTip>Taking a tile and placing it are two separate actions needing two
        different die values. That is the core tension of the game: the tile you want
        and the space it goes into rarely match the dice you rolled.</RulesTip>
    </RulesSection>

    <RulesSection title="Tile effects">
      <RulesDefs items={[
        { t: "Castle", d: "Take one extra action immediately, at any die value you like. Chaining castles is a genuine strategy." },
        { t: "Mine", d: "Pays silver at the end of every phase for the rest of the game, so an early mine is worth several times a late one." },
        { t: "Ship", d: "Brings a batch of trade goods and moves you up the turn order." },
        { t: "Livestock", d: "Scores VP the moment it is placed, and much more for grouping the same animal together." },
        { t: "Building", d: "An instant effect: market, carpenter and church take a tile into storage; warehouse sells goods; boarding house gives 4 workers; bank 2 silver; town hall places another tile; watchtower 4 VP. Only one of each building type per region." },
        { t: "Monastery", d: "One of 26 unique tiles, identified by its number, granting an ongoing power, an end-game scoring bonus, or both." },
      ]} />
    </RulesSection>

    <RulesSection title="Goods and selling">
      <p>Goods come in six colors, each tied to a number. Matching a die to that
        number sells every goods tile of that color at once, for silver plus VP for
        each tile sold — 2 VP per tile at two players, more with more. A player may
        hold at most three different colors at a time, so sell before a ship arrives
        and crowds you out.</p>
    </RulesSection>

    <RulesSection title="Scoring">
      <p>Completing a region — every space of one colored area filled — scores by its
        size: 1, 3, 6, 10, 15, 21, 28 or 36 VP for regions of 1 to 8 spaces. On top
        of that comes a phase bonus that shrinks all game, 10, 8, 6, 4 and 2 VP in
        phases 1 through 5. A 3-space region finished in phase 1 is worth 16 VP; the
        same region in phase 5 is worth 8.</p>
      <p>The first player to fill every space of a given color across their whole
        duchy takes the large color bonus, 5 VP at two players; the second player to
        do it takes the small one, 2 VP. Selling goods, watchtowers and livestock
        score as they happen.</p>
    </RulesSection>

    <RulesSection title="End of phase">
      <p>Mines pay out their silver, then the numbered depots are cleared and
        refilled with the same types of tile — the faint ghost outlines on the depots
        show what is coming back.</p>
    </RulesSection>

    <RulesSection title="End of the game">
      <p>After the last round, leftover resources score: 1 VP per goods tile, 1 VP
        per silver, and 1 VP per two workers. Any monastery end-game bonuses are
        added last, and the highest total wins.</p>
    </RulesSection>
  </>;
}
