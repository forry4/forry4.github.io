/* The prompts for every picture, in the order to make them (the art gallery shows
 * them with copy buttons; dev only). What keeps them one game:
 *   - STYLE is pasted before EVERY prompt, word for word. Fix a bad result by
 *     regenerating or changing the subject — never by editing STYLE.
 *   - After batch 1, every prompt attaches the approved Ranger as a REFERENCE.
 *   - Things that belong together (a rift's enemies, the shots) are drawn in ONE
 *     image and cut apart by the cleanup step, so they match by construction.
 *   - The cleanup step (artClean.js) then forces the shared size, colors and
 *     outline, whatever the generator did.
 * Colors are described by job (art direction §2.3): the player cyan/white, enemies
 * red/orange/magenta, the ground quiet.
 *
 * SIZES are asked for in GAME pixels, worked out from the shared density (art.js
 * `artPx`, which the approved Ranger sets): "26 pixels tall, enlarged with
 * nearest-neighbor". A generator still draws big blocks, but about the right NUMBER of
 * them, so the cleanup can keep its pixels as drawn instead of resizing (anything more
 * than 15% off is resized by whole pixels, which drops detail). The format rules in
 * STYLE — hard edges, a margin, a small palette — are the things the cleanup reads
 * worst when they are missing.
 *
 * THE LOOK (owner, 2026-11-19, from a wizard they generated and liked): simple, bold,
 * cute and low-detail — a head about HALF the height, big flat areas, ~10 colors, ONE
 * bright accent. The first prompts asked for a third-height head, cyan trim on every
 * edge and ~16 colors at 26 pixels tall, and the first Ranger came out busy. */
import { artPx } from "./art.js";
import { targetHeight } from "./artClean.js";

export const STYLE = "Original 2D pixel art game sprite for a top-down action RPG, seen from the front and slightly above. " +
	"Simple, bold, cute and LOW-DETAIL: big simple shapes and large flat areas of color, very few small details, no tiny straps, " +
	"buckles, stitches or patterns. One dark outline around the figure. Flat shading: each color has one shadow tone and at most one " +
	"small highlight. About 10 colors in the whole figure. Hard pixel edges: no anti-aliasing, no dithering, no soft or half-transparent " +
	"pixels, no detail smaller than one pixel. No glow, no blur, no gradients, no shadow on the ground. Readable silhouette even when " +
	"shrunk very small. Plain flat solid #00FF00 green background, nothing else behind the subject, and a wide empty margin of " +
	"background around everything: nothing touches the edges of the image. No text, no logo, no watermark, no border, no extra objects.";

export const TILE_STYLE = "Original 2D pixel art game tile for a top-down action RPG. Simple and low-detail: large flat areas of color, " +
	"few small details, about 6 colors, one consistent pixel size, flat shading, light coming from above. Hard pixel edges: no anti-aliasing, no " +
	"dithering, no detail smaller than one pixel. No glow, no blur, no gradients. " +
	"Quiet, low-contrast colors: the ground must never compete with the characters on it. Fill the whole square edge to edge, with no " +
	"border, no frame and no background. No text, no logo, no watermark.";

/* Step 1 only: a picture in the style the owner wants (made by them), attached to the
 * Ranger's prompt. The Ranger then carries that style to every later step. */
export const STYLE_EXAMPLE = "If an example image is attached, it shows the art style I want: match its pixel size, proportions, " +
	"outline, shading, number of colors and level of detail exactly, but draw the new character described below, not the one in the example.";

export const REFERENCE = "Attached is this game's approved style reference. Match its pixel size, outline, shading and level of detail " +
	"exactly; draw only the new subject described below, not the character in the reference.";

/* The hero's ONE bright spot (the art direction's cyan), in one place — trim on
 * every edge made the first Ranger busy. */
const ACCENT = (what) => `The only bright color is one small glowing cyan accent, ${what}, so the hero stands out on any floor`;
const THREE = (who, accent) => `${who}, drawn three times in one row on a wide landscape image, with wide empty space between them: facing the viewer, facing right, ` +
	"facing away from the viewer. The same character, size and colors in all three. Cute chunky proportions: the head (or hood) is about " +
	`HALF the figure's height, with a small body and short legs. ${ACCENT(accent)}.`;
const ROW = (n) => `${n} different creatures standing in one row on a wide landscape image, left to right in the order listed, with ` +
	"wide empty space between them, all facing the viewer:";
const SEAMLESS = "It must repeat seamlessly when placed next to copies of itself on all four sides.";

/* One BATCH is one sitting. An item is one generated image: `keys` are the slots it
 * fills (several = one image cut apart left to right), `tile` uses TILE_STYLE. */
export const BATCHES = [
	{
		title: "1. The style anchor: the Ranger",
		why: "Everything else will be matched to this one picture, so take your time. If you have a picture in the style you want, attach " +
			"it to this prompt as the example. Generate it several times, drop each try here, " +
			"and keep the one you like best at game size. If it looks too big or too small next to a tile, change \"Ranger height\" above the " +
			"steps: that sets the pixel size every other picture is matched to. The original image is kept for you; every later prompt attaches it.",
		anchor: true,
		items: [{ keys: ["player.ranger"], subject: THREE(`A small hooded ranger with a plain dark slate-blue hooded cloak, the face hidden in the hood's shadow with two small pale eyes, ` +
			"holding a short bow UPRIGHT at its side, never across its body: the bow a clean, simple curve two pixels thick in a light warm brown that " +
			"stands out against the dark cloak, with a thin pale string. In the side view the bow is held out in front, upright", "the arrowhead") }],
	},
	{
		title: "2. The Shallows' ground",
		why: "Daylit sandbars and shallow water at the edge of the Rift: gentle and quiet. Tiles are hard for generators — expect to " +
			"retry the floor; a visible seam in the gallery's room means try again.",
		items: [
			{ keys: ["tile.shallows.floor"], tile: true, subject: `One square ground tile seen straight from above: pale, muted sand of a daylit sandbar with a few tiny pebbles and faint ripples. ${SEAMLESS}` },
			{ keys: ["tile.shallows.water"], tile: true, subject: `One square tile of calm, clear, shallow water over sand, seen straight from above: muted teal with a few soft light ripples. ${SEAMLESS}` },
			{ keys: ["tile.shallows.wall"], tile: true, subject: "One square tile seen from above: the flat top of a wall of weathered gray-green stone blocks, darker than pale sand. It must repeat seamlessly in every direction." },
			{ keys: ["tile.shallows.wallTop"], tile: true, subject: "One square tile: the front face of a weathered gray-green stone wall seen from slightly above, lit from above, the face darker toward its foot. It must repeat seamlessly left to right." },
			{ keys: ["tile.shallows.rock"], tile: true, subject: "One square tile seen from slightly above: a single rounded gray-green boulder sitting on pale sand, filling most of the square, the sand showing around it." },
		],
	},
	{
		title: "3. The shots",
		why: "Three projectiles in one picture, cut apart for you. Yours are cyan and white; every enemy shot is red, orange or magenta with a hot core.",
		items: [{ keys: ["shot.player", "shot.enemy", "shot.enemyHeavy"], subject: "Three small projectiles in one row, left to right, with wide empty space between, " +
			"each flying to the right: a short magic arrow glowing cyan and white; a round enemy orb, red-orange with a hot pale-yellow core; " +
			"a slightly larger round enemy orb, hot magenta with a pale core." }],
	},
	{
		title: "4. The Shallows' creatures",
		why: "All three in one picture so they look like they come from the same place. Attach the Ranger as the reference.",
		items: [{ keys: ["enemy.chaser", "enemy.shooter", "enemy.radial"], subject: `${ROW("Three")} ` +
			"(1) a low, fast crab-like creature with big snapping claws, built to rush in; " +
			"(2) an upright sea creature like a tall anemone with a single gaping mouth that spits shots from a distance; " +
			"(3) a squat, rooted, round spiny coral creature that sprays shots in every direction. " +
			"Their bodies are deep red, orange and hot magenta with dark undersides, clearly dangerous." }],
	},
	{
		title: "5. The Tidewarden",
		why: "The Shallows' boss: twice a character's height. Attach the Ranger as the reference.",
		items: [{ keys: ["enemy.tidewarden"], subject: "A large boss creature, the guardian of the shallows: a hulking armored creature with a heavy barnacled " +
			"gray-green shell, facing the viewer, with glowing red-orange eyes and a faint glowing seam cracked across its shell. Imposing but readable." }],
	},
	{
		title: "6. The other three classes",
		why: "One picture each, three facings, the Ranger attached as the reference so the four look like one party.",
		items: [
			{ keys: ["player.paladin"], subject: THREE(`A small armored paladin with a mace and a round shield, plain warm steel armor over a muted brown tabard`, "a gem in the middle of the shield") },
			{ keys: ["player.diviner"], subject: THREE(`A small robed mage holding a staff topped with a star, a plain deep violet hooded robe`, "the star on the staff") },
			{ keys: ["player.ninja"], subject: THREE(`A small nimble ninja with throwing knives, plain dark green wrappings and a mask`, "the blades of the knives") },
		],
	},
	{
		title: "7. The town",
		why: "The safe place: cool gray flagstone, so it never reads like a dungeon.",
		items: [
			{ keys: ["tile.town.floor"], tile: true, subject: `One square tile seen straight from above: cool gray flagstones, worn and clean. ${SEAMLESS}` },
			{ keys: ["tile.town.wall"], tile: true, subject: "One square tile seen from above: the flat top of a dark gray stone town wall. It must repeat seamlessly in every direction." },
			{ keys: ["tile.town.wallTop"], tile: true, subject: "One square tile: the front face of a dark gray dressed-stone town wall seen from slightly above, lit from above. It must repeat seamlessly left to right." },
			{ keys: ["tile.town.rock"], tile: true, subject: "One square tile seen from slightly above: a square stone planter with a small green shrub, on gray flagstone." },
			{ keys: ["tile.town.water"], tile: true, subject: `One square tile of still fountain water seen straight from above: muted blue-gray with soft light ripples. ${SEAMLESS}` },
		],
	},
	{
		title: "8. The Fracture",
		why: "Where the Rift is breaking apart: dark violet stone over a black void. Attach the Ranger as the reference for the creatures and the boss.",
		items: [
			{ keys: ["tile.fracture.floor"], tile: true, subject: `One square tile seen straight from above: dark violet stone floor with thin faint cracks. ${SEAMLESS}` },
			{ keys: ["tile.fracture.void"], tile: true, subject: `One square tile seen straight from above: a black void with a few tiny dim violet specks, like empty space. ${SEAMLESS}` },
			{ keys: ["tile.fracture.wall"], tile: true, subject: "One square tile seen from above: the flat top of a wall of near-black violet stone. It must repeat seamlessly in every direction." },
			{ keys: ["tile.fracture.wallTop"], tile: true, subject: "One square tile: the front face of a near-black violet stone wall seen from slightly above, lit from above. It must repeat seamlessly left to right." },
			{ keys: ["tile.fracture.rock"], tile: true, subject: "One square tile seen from slightly above: a broken pillar of dark violet stone on a dark violet floor, filling most of the square." },
			{ keys: ["enemy.shard", "enemy.splitter", "enemy.splinter", "enemy.flicker"], subject: `${ROW("Four")} ` +
				"(1) a floating jagged crystal creature; (2) a heavy six-sided crystal creature with a crack down its middle, about to split; " +
				"(3) a SMALL fast crystal fragment creature, half the size of the others; (4) a flickering ring-shaped spirit that is not quite all there. " +
				"Their bodies are hot magenta, red and orange crystal with dark cores, clearly dangerous." },
			{ keys: ["enemy.breach"], subject: "A large boss creature, the Schism: a torn star-shaped rift creature of violet and black stone with a blazing " +
				"magenta-red wound at its heart, jagged and unstable, facing the viewer. Imposing but readable." },
		],
	},
	{
		title: "9. The Ashen Breach",
		why: "Charcoal and ash, embers banked low; the only bright fire is the enemies'. Attach the Ranger as the reference for the creatures and the boss.",
		items: [
			{ keys: ["tile.ashen.floor"], tile: true, subject: `One square tile seen straight from above: dark charcoal ground dusted with gray ash, a few dim dull embers. ${SEAMLESS}` },
			{ keys: ["tile.ashen.wall"], tile: true, subject: "One square tile seen from above: the flat top of a wall of black scorched stone. It must repeat seamlessly in every direction." },
			{ keys: ["tile.ashen.wallTop"], tile: true, subject: "One square tile: the front face of a black scorched stone wall seen from slightly above, lit from above. It must repeat seamlessly left to right." },
			{ keys: ["tile.ashen.rock"], tile: true, subject: "One square tile seen from slightly above: a lump of cooled black slag rock on charcoal ground, filling most of the square." },
			{ keys: ["enemy.cinder", "enemy.kiln", "enemy.smolder"], subject: `${ROW("Three")} ` +
				"(1) a small quick living flame, a teardrop of fire with eyes; (2) a squat stone oven creature with a glowing mouth that lobs firebombs; " +
				"(3) a lump of banked coal, dull dark brown with orange cracks, that flares when struck. Fire colors are red, orange and pale yellow." },
			{ keys: ["enemy.pyre"], subject: "A large boss creature, the Pyre: a towering ring of flame tongues around a white-hot heart, set in a body of " +
				"black scorched stone, facing the viewer. Imposing but readable." },
		],
	},
];

/* The size line for an item at density `px` (art pixels a tile): game pixels tall
 * for each thing in it, and the one pixel grid they share. */
/* The Ranger's own height in game pixels: it SETS the density (art.js), so its prompt
 * asks for a fixed size rather than following the density. ~20, as in the owner's
 * style example (a wizard about 21 pixels tall). */
export const ANCHOR_PX = 20;
export function sizeLine(item, px = artPx()) {
	const grid = "every pixel drawn as one big square block, as if a tiny sprite were enlarged with nearest-neighbor scaling";
	if (item.tile) return `Size: the tile is exactly ${px} by ${px} pixels, ${grid}. Count the pixels: ${px} across, ${px} down.`;
	const hs = item.keys.map((k) => (k === "player.ranger" ? ANCHOR_PX : targetHeight(k, px)));
	const what = item.keys[0].startsWith("shot.") ? "long" : "tall";
	if (item.keys.length === 1) {
		const n = item.keys[0].startsWith("player.") ? "Each of the three figures is" : "It is";
		return `Size: ${n} exactly ${hs[0]} pixels ${what}, ${grid}.`;
	}
	return `Size, left to right: ${hs.map((h, i) => `(${i + 1}) ${h} pixels ${what}`).join(", ")}. All on the same pixel grid, ${grid}.`;
}

/* The full text to paste for an item: the style, the reference line after batch 1,
 * the subject, then the size at the current density. */
export function promptFor(item, batch, px = artPx()) {
	return [item.tile ? TILE_STYLE : STYLE, batch.anchor ? STYLE_EXAMPLE : null, !batch.anchor && !item.tile ? REFERENCE : null,
		item.subject, sizeLine(item, px)].filter(Boolean).join("\n\n");
}
