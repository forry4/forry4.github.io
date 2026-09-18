import { RulesSection, RulesDefs, RulesTip } from "../../shared/lobby.jsx";

/* The WORDS for the shared RulesModal. Chrome (the panel, the scroller, the
   close button) lives in shared/lobby.jsx; only this file is game-specific.

   Structured on Orbit's ruleset — Goal of the Game, then Setup, then a Round,
   then the subsystems, then how a Fight ends — which is also the printed
   rulebook's order, so a player who has read the real rules finds the same
   thing in the same place. The VOCABULARY is the rulebook's too (Active
   Fighter, Partner, Opponents, Bonus Action, Success, Direct Damage, Stop,
   THEN, Power cubes, Fight Deck), since a rules panel that renames things is
   worse than no rules panel: it makes the cards harder to read rather than
   easier.

   There is deliberately no `RulesFacts` strip and no lead paragraph — every
   ruleset on the site opens on Goal of the Game, so the player count and the
   win condition are stated there and in Setup instead. `RulesDefs` still takes
   `{t, d}` PAIRS, not strings; this file once passed bare strings in three
   places and rendered three empty boxes, which is what
   shared/tests/test_rules_kit_shapes.py now exists to catch. */

export default function RagTagRules() {
  return (
    <>
      <RulesSection title="Goal of the Game">
        <p>
          An auto battler and a deckbuilder for 2 players, a friend or the bot.
          Each player fields a team of two Fighters, and the Fight is won by
          Knocking Out one of the opponent&rsquo;s two Fighters.
        </p>
        <p>
          Every Turn both players flip the top card of their Fight Deck at the
          same moment and both cards resolve together — you cannot react, only
          prepare. Then you add one card to your deck. <b>Your deck is never
          shuffled</b>, so you always know exactly what is coming, and so does
          your opponent.
        </p>
      </RulesSection>

      <RulesSection title="Setup">
        <p>
          You are dealt 6 of the 12 Fighters. Take one, pass the rest across, and
          take a second from the ones your opponent passed you. Those two are
          your team for the whole Fight.
        </p>
        <p>
          Each Fighter has a board and a deck of 10 cards. Their two <b>Starting
          Cards</b> are set aside, and in an order you choose they are your whole
          opening Fight Deck — two cards. The remaining 18 shuffle together into
          your <b>Build Deck</b>.
        </p>
      </RulesSection>

      <RulesSection title="A Round">
        <RulesDefs items={[
          ["FIGHT!", "You both flip one card at a time and resolve them simultaneously, until both Fight Decks run out."],
          ["BUILD!", "Draw the top 3 of your Build Deck, secretly keep 1, and slide it anywhere into your Fight Deck. The other 2 go to the bottom of the Build Deck."],
        ].map(([t, d]) => ({ t, d }))} />
        <p>
          A Turn is both players flipping one card and performing what it says,
          at the same time. Every Action on a card is <b>mandatory</b> — you
          cannot decline one, even when it hurts you.
        </p>
        <p>
          The cards you just played keep their order and become next Round&rsquo;s
          Fight Deck — one card longer than last Round. <b>You may not reorder
          what is already there</b>; you only choose where the new card goes.
        </p>
        <RulesTip>
          Where you slide a card matters more than which card it is. Line your
          Block up against the Attack you know is coming, and your Attack
          against the gap.
        </RulesTip>
      </RulesSection>

      <RulesSection title="Who is who">
        <RulesDefs items={[
          ["Active Fighter", "Whoever's card came up this Turn. They perform the Actions, and they are the default target."],
          ["Partner", "The other Fighter on the same team as the Active Fighter."],
          ["Opponent", "The other player's Active Fighter."],
          ["Opponents", "Their Active Fighter AND their Partner."],
          ["You", "The Active Fighter — so a card saying 'you' means whoever played it."],
        ].map(([t, d]) => ({ t, d }))} />
      </RulesSection>

      <RulesSection title="Health and Power">
        <p>
          A Fighter&rsquo;s <b>Health marker</b> moves up and down their Health
          track as they take hits and heal. A marker on the <b>KO space</b> at
          the end of a Turn loses the Fight for that whole team. A Fighter who
          has reached the KO space can never be healed off it, and can never go
          above their top space.
        </p>
        <p>
          <b>Power cubes</b> are how hard you hit: an Attack costs the target as
          many HP as the attacker has Power. Power is <b>not spent</b> when you
          attack, and an Attack always uses the Power you had at the{" "}
          <b>start of the Turn</b> — cubes gained or lost during the Turn do not
          count until the next one.
        </p>
      </RulesSection>

      <RulesSection title="Actions">
        <RulesDefs items={[
          ["Attack", "The target loses HP equal to your Power at the start of the Turn. A 0-Power Attack is still an Attack."],
          ["Block", "Negates every Attack the opposing team makes this Turn — including ones aimed at their own Partner. It does NOT stop Direct Damage."],
          ["Direct Damage", "A flat HP loss printed on the card. Not an Attack, so a Block cannot stop it — but Stops and Health-track icons still apply."],
          ["Heal", "Move back up the track. Healed and hit on the same Turn, only the difference moves."],
          ["Power Gain / Loss", "Add or remove cubes. It settles after the cards resolve, so it never fuels this Turn's Attack."],
          ["Transfer", "Move Power from one Fighter to another. Move as much as you can, even if it is less than asked."],
          ["Cancel", "The opposing card is ignored completely and does nothing at all."],
        ].map(([t, d]) => ({ t, d }))} />
        <p>
          Direct Damage and an Attack landing on the same Fighter in the same
          Turn are <b>added together</b>, and Healing is subtracted from the
          total — one movement of the marker, not three.
        </p>
      </RulesSection>

      <RulesSection title="Success and the Bonus Action">
        <p>
          A card is a <b>Success</b> when its Attack was not Blocked, or when its
          Block caught at least one Attack. Some cards pay a <b>Bonus Action</b>
          for it, resolved at the same time as the card&rsquo;s main Action.
        </p>
        <p>
          A Block&rsquo;s Bonus fires <b>once per Turn</b> however many Attacks it
          caught — and a 0-Power Attack still counts as one caught.
        </p>
      </RulesSection>

      <RulesSection title="Health track icons">
        <p>
          An icon fires when your marker <b>lands on or passes through</b> it,
          once every marker has finished moving. Sitting on an icon at the start
          of a Turn and stepping off it pays nothing — you have to arrive. Pass
          over several in one movement and they all fire, and a marker that
          crosses the same icon twice in a Round fires it twice.
        </p>
        <p>
          A <b>Stop</b> halts the marker the instant it reaches that space, going
          up or down, and the rest of the movement is lost — so a +3 Heal into a
          Stop one space away heals 1.
        </p>
      </RulesSection>

      <RulesSection title="On the cards">
        <RulesDefs items={[
          ["THEN", "Do what follows THEN after everything before it, whether or not that succeeded."],
          ["Instant Bonus", "Fires once, the moment you slide the card into your Fight Deck — not when it is later revealed. You must tell your opponent what you gained."],
          ["Starting Card", "Marked with a star. Set aside at setup, so it is guaranteed to come up in Round 1."],
        ].map(([t, d]) => ({ t, d }))} />
      </RulesSection>

      <RulesSection title="How a Fight ends">
        <RulesDefs items={[
          ["Knocked Out", "A Fighter's marker is on the KO space at the end of a Turn. Their team loses immediately."],
          ["Double KO", "Fighters on both teams go down on the same Turn. That is a draw."],
          ["Depleted Build Deck", "You cannot draw 3 cards to Build. Also a draw, and it caps a Fight at about sixteen Rounds."],
        ].map(([t, d]) => ({ t, d }))} />
        <p>
          Some Fighters treat being KO&rsquo;d as a suggestion. Maman Brijit comes
          back from beyond her KO spaces, the Fey Folk have no KO space at all,
          and Mephisto has a card that turns any loss into a win.
        </p>
      </RulesSection>

      <RulesSection title="The Fighters">
        <p>
          All twelve have their own board, health track and ten-card deck, and
          several break the rules above on purpose. Their boards say what they
          do — press and hold, or right-click, any Fighter or card to read it in
          full.
        </p>
        <RulesTip>
          <b>The golden rule:</b> anything printed on a card or a Fighter board
          overrules anything on this page.
        </RulesTip>
      </RulesSection>
    </>
  );
}
