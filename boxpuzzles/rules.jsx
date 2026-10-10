// Box Puzzles — how to play. The words are the owner's, approved line by line
// (2026-10-06): the goal and what each color does, nothing more. White and Red say
// "this tile's color" rather than "white"/"red" on purpose — that is what makes them
// read true when a blue tile borrows the ability (see engine.py's docstring).
// American spelling throughout.
import { RulesDefs, RulesSection } from "../shared/lobby.jsx";

const swatch = (c) => <span className="bx-rl-sw" style={{ "--t": `var(--bx-${c})` }} aria-hidden="true" />;
const color = (c, name) => <>{swatch(c)}{name}</>;

export default function BoxPuzzlesRules() {
	return <>
		<RulesSection title="Goal of the Game">
			<p>Make each corner tile match the color of the button beside it. A button lights
				while its corner matches, and the box is solved when all four are lit.</p>
			<p>Pressing a tile triggers the tile's color ability. Each tile press is a move.
				Pressing an unlit button resets the box to its starting tiles and sets your moves
				back to zero.</p>
		</RulesSection>

		<RulesSection title="The colors">
			<RulesDefs items={[
				{ t: color("GY", "Gray"), d: "Nothing." },
				{ t: color("WH", "White"), d: "This tile and tiles beside it of the same color turn gray, while gray tiles beside it turn this tile's color." },
				{ t: color("PU", "Violet"), d: "Swaps with the tile below it." },
				{ t: color("YE", "Yellow"), d: "Swaps with the tile above it." },
				{ t: color("GN", "Green"), d: "Swaps with the tile opposite it." },
				{ t: color("PI", "Pink"), d: "Rotates the tiles around it clockwise." },
				{ t: color("BK", "Black"), d: "Moves its row right; the last tile wraps to the front." },
				{ t: color("RD", "Red"), d: "Turns every white tile black, and every black tile this tile's color." },
				{ t: color("OR", "Orange"), d: "Becomes the color most of the tiles beside it share. On a tie, nothing happens." },
				{ t: color("BU", "Blue"), d: "Uses the center tile's ability." },
			]} />
			<p>“Beside” means directly above, below, left or right, never diagonal.</p>
		</RulesSection>

		<RulesSection title="Daily mode">
			<p>A new box every day at midnight Pacific time. Your first attempt is saved as you
				play, and a reset doesn't set your moves back to zero. When the box is solved, your
				moves go on the First Attempt leaderboard. After that, play again as often as you
				like; your fewest moves go on the Best Attempt leaderboard.</p>
		</RulesSection>

		<RulesSection title="Practice mode">
			<p>A random box made without the colors you exclude. Nothing is saved, and there is
				no leaderboard.</p>
		</RulesSection>
	</>;
}
