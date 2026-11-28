import { RulesDefs, RulesSection, RulesTip } from "../shared/lobby.jsx";

/* How to play Boss Rush, on the site's shared rules shape (Goal, Setup, the turn, the
 * subsystems, the end). The class lines repeat sim.js CLASS_INFO's names and
 * descriptions: reword an ability there and here together. */
export default function BossRushRules() {
	return <>
		<RulesSection title="Goal of the Game">
			<p>Beat three bosses in a row as fast as you can. Your time is the time spent
				inside the boss rooms, added up over the three fights. The fastest clears of
				each boss set go on its leaderboard.</p>
		</RulesSection>

		<RulesSection title="Setup">
			<p>Play alone, or open a co-op room for 2–4 players and share its link. Pick a
				character and a boss set. The three bosses come in a random order, or pick
				the one to fight first by clicking its portrait.</p>
			<p>Each class has a fixed kit and one ability:</p>
			<RulesDefs items={[
				{ t: "Ranger", d: "Dash and fire a heavy arrow." },
				{ t: "Paladin", d: "Slow enemy shots and burn nearby enemies." },
				{ t: "Mage", d: "Place a zone that boosts your shots." },
				{ t: "Ninja", d: "Negate damage to empower your next shot." },
				{ t: "Simon", d: "Boost your movement speed for a few seconds." },
			]} />
		</RulesSection>

		<RulesSection title="A fight">
			<p>Walk into the boss room. The doors seal behind you, the clock starts, and the
				boss wakes a second later. Move, aim and fire until it falls.</p>
			<RulesDefs items={[
				{ t: "Move", d: "WASD or the arrow keys; the left stick on a phone." },
				{ t: "Fire", d: "Hold the mouse button and aim with the mouse; the right stick on a phone. T turns auto-fire on and off." },
				{ t: "Ability", d: "Space or right click. It costs MP, which refills over time." },
			]} />
			<p>Bright marks on the floor show where an attack is about to land. At half
				health every boss changes to its second phase, with new attacks.</p>
		</RulesSection>

		<RulesSection title="Between bosses">
			<p>When a boss falls, a blue portal opens. Step into it and press E (or tap
				Enter portal) to go on to the next boss. The clock is stopped until you seal
				the next room.</p>
			<p>Your health carries over. It slowly recovers, but never to more than 40 above
				the lowest it has been this run, so every hit you take stays with you.</p>
			<RulesTip>Damage taken is shown beside each time on the leaderboard. It is never
				ranked by: only the time counts.</RulesTip>
		</RulesSection>

		<RulesSection title="Co-op">
			<p>Every extra player adds 130% of the boss’s solo health. Aimed attacks pick one
				living player at a time. A player who falls is out until the next boss, and
				comes back with the same health limit as above. The fight ends when everyone
				is down.</p>
			<p>A co-op fight cannot be paused; Esc opens the menu while it carries on.</p>
		</RulesSection>

		<RulesSection title="End of the run">
			<p>The run ends when the third boss falls, or when you fall. Esc pauses a solo
				run (the clock stops too), and End run in the pause menu stops it. Hold R at
				any time to start a new run with the same picks.</p>
			<p>Each class’s five best solo times, and the five best co-op times, keep a
				replay that anyone can watch from the leaderboard.</p>
		</RulesSection>
	</>;
}
