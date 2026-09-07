import { RulesDefs, RulesFacts, RulesSection, RulesTip } from "../../shared/lobby.jsx";

export default function OrbitRules() {
  return <>
    <RulesFacts items={[
      { k: "Players", v: "2" },
      { k: "Time", v: "about 30 min" },
      { k: "Goal", v: "control the solar system" },
    ]} />

    <RulesSection title="Goal of the Game">
      <p>Players will struggle to gain Influence on the 5 planets: Mercury, Venus,
        Terra, Mars, and Jupiter. This Influence is represented by discs in different
        colors. In Orbit, there are 3 victory conditions:</p>
      <RulesDefs items={[
        { t: "Absolute victory", d: "Gain 3 Influence discs from the same planet." },
        { t: "Democratic victory", d: "Gain 4 Influence discs from strictly different planets." },
        { t: "Popular victory", d: "Gain 5 Influence discs (from any planets)." },
      ]} />
      <p>The game ends immediately as soon as a player meets 1 of these three
        conditions.</p>
    </RulesSection>

    <RulesSection title="Setup">
      <p>Each player starts with 12 Credits, 1 Zenithium, and 4 secret Agent cards.
        The second player begins with 1 Terra influence. Before the first turn, each
        player may replace any number of starting cards.</p>
      <p>Eight random bonus tokens are placed in play: one on each planet and one on
        each technology track.</p>
    </RulesSection>

    <RulesSection title="Turn overview">
      <p>On your turn, you must:</p>
      <p>Play 1 card from your hand to take 1 of the three following actions:</p>
      <RulesDefs items={[
        { t: "A. Recruit the Agent", d: "Put the Agent in its planet column, pay its cost minus the cards already there, gain 1 matching influence, then resolve its text left to right." },
        { t: "B. Develop Technology", d: "Discard the Agent, pay the next technology level in Zenithium (1–5), advance its faction, then resolve that level and every lower level from top to bottom." },
        { t: "C. Become the Leader", d: "Discard the Agent. Robot takes the Leader badge and gains 1 Zenithium; Human takes the Leader badge and gains 3 Credits; Animod takes the Leader badge and mobilizes 2. Taking the badge from elsewhere gives the Silver side and a hand limit of 5. Taking your own Silver badge upgrades it to Gold and a limit of 6." },
      ]} />
      <RulesTip>A recruited Agent reduces the future cost of its column, and it is
        already the top card when its own effects resolve.</RulesTip>
    </RulesSection>

    <RulesSection title="Influence and planets">
      <p>Influence moves a planet disc one space toward you. Reaching your control
        zone captures it; extra movement is lost. The first capture from a planet
        also resolves and removes its bonus token. A fresh disc appears in the
        middle only at the end of the active player’s turn.</p>
      <p>An effect can move a disc toward your opponent—even far enough for them to
        capture it and win during your turn.</p>
    </RulesSection>

    <RulesSection title="Technology bonuses">
      <p>The first player to reach level 2 on a faction resolves that track’s bonus
        after its level-2 effect and before level 1. Completing all three tracks at
        level 1, 2, or 3 grants respectively 1, 2, or 3 influence on one planet,
        after all track effects.</p>
    </RulesSection>

    <RulesSection title="Agent effects">
      <RulesDefs items={[
        { t: "Mobilize", d: "Draw the top Agent and add it to its matching column without resolving its text or its normal recruit influence." },
        { t: "Exile", d: "Discard the most recently added Agent from the chosen column." },
        { t: "Transfer", d: "Move the opponent’s top Agent to your matching column without resolving it." },
      ]} />
    </RulesSection>

    <RulesSection title="End of turn">
      <p>Draw up to 4 cards, or 5/6 while holding the silver/gold Leader. Never
        discard down if an effect put you above the limit. Every planet disc captured
        this turn is then returned to its middle space and play passes.</p>
      <p>If the Agent deck or face-down bonus reserve runs out, shuffle its discard
        pile to make a new one.</p>
    </RulesSection>
  </>;
}
