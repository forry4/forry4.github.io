/* The prompts for every picture, in the order to make them (the art gallery shows
 * them with copy buttons; dev only). What keeps them one game:
 *   - STYLE is pasted before EVERY prompt, word for word. Fix a bad result by
 *     regenerating or changing the subject — never by editing STYLE.
 *   - EVERY prompt attaches the owner's STYLE BOARD and asks for its look (REFERENCE).
 *     The owner generated it from one open prompt ("Create an original visual style
 *     exploration board for a browser-based top-down projectile action RPG", 2026-11-19)
 *     and it beat every picture made to these rules: drawn together, everything on it
 *     shares one pixel size and one set of colors, so it is the look to aim at. It
 *     replaced the approved Ranger as the reference, and step 1's separate example.
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
import { artPx, SLOTS, DECO_PARTS } from "./art.js";
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

/* The style board line, on every prompt. The board is a whole scene on a dark ground,
 * so it also says what NOT to take from it: the scene and the background. */
export const REFERENCE = "Attached is this game's style board. Match its art style exactly: its pixel size, outlines, shading, colors and " +
	"level of detail. Draw only the new subject described below, on its own — not a copy of anything on the board, and not a scene. " +
	"Use the background asked for here, not the board's dark one.";

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
		why: "Everything else will be matched to this one picture, so take your time. Attach the style board (above the steps) to this prompt. " +
			"Generate it several times, drop each try here, " +
			"and keep the one you like best at game size. If it looks too big or too small next to a tile, change \"Ranger height\" above the " +
			"steps: that sets the pixel size every other picture is matched to.",
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
		title: "3. Projectiles and hit effects",
		why: "Player shots are cool and hostile shots are warm. Draw directional effects pointing right so the game can turn them in flight.",
		items: [
			{ keys: ["shot.player", "shot.bolt", "shot.slash"], subject: "Three pale cyan shots in one row: a wooden arrow with a white arrowhead, a bright round magic bolt, and a crescent melee wave." },
			{ keys: ["shot.star", "shot.blade", "shot.gale", "shot.flare"], subject: "Four pale cyan shots in one row: a four-point shuriken, a compact triangular kunai, an icy crescent gust, and a small blue flame with a short tail." },
			{ keys: ["shot.power", "shot.impact"], subject: "Two gold-white flashes in one row: a large empowered four-point spark and a small sharp cross-shaped hit spark." },
			{ keys: ["shot.enemy", "shot.enemyHeavy", "shot.enemyShard"], subject: "Three hostile shots in one row: a bright round orange bolt, a heavy hot pink jewel, and an angular warm magenta shatter crystal." },
		],
	},
	{
		title: "4. The Shallows' creatures",
		why: "All three in one picture so they look like they come from the same place.",
		items: [{ keys: ["enemy.chaser", "enemy.shooter", "enemy.radial"], subject: `${ROW("Three")} ` +
			"(1) a low, fast crab-like creature with big snapping claws, built to rush in; " +
			"(2) an upright sea creature like a tall anemone with a single gaping mouth that spits shots from a distance; " +
			"(3) a squat, rooted, round spiny coral creature that sprays shots in every direction. " +
			"Their bodies are deep red, orange and hot magenta with dark undersides, clearly dangerous." }],
	},
	{
		title: "5. The Tidewarden",
		why: "The Shallows' boss: twice a character's height.",
		items: [{ keys: ["enemy.tidewarden"], subject: "A large boss creature, the guardian of the shallows: a hulking armored creature with a heavy barnacled " +
			"gray-green shell, facing the viewer, with glowing red-orange eyes and a faint glowing seam cracked across its shell. Imposing but readable." }],
	},
	{
		title: "6. The other three classes",
		why: "One picture each, three facings, the style board attached so the four look like one party.",
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
			{ keys: ["town.vault", "town.forge", "town.target", "town.bag"], subject: "Four separate town props in one row, seen from slightly above: a wide brass-banded oak chest, a squat stone forge with an amber hearth, a straw archery target on a stake, and a small tied leather sack." },
			{ keys: ["town.fountain"], subject: "One low carved violet-gray pedestal with short pale-blue water arcs, seen from slightly above. Draw only the centerpiece and its jets." },
			{ keys: ["town.shallows", "town.fracture", "town.ashen", "town.dream"], subject: "Four low stone gates in one row: pale sandstone and teal water, broken plum slate and a violet fissure, basalt and an ember opening, and a silver-lavender moon arch with a blue center." },
		],
	},
	{
		title: "8. The Fracture",
		why: "Where the Rift is breaking apart: dark violet stone over a black void.",
		items: [
			{ keys: ["tile.fracture.floor"], tile: true, subject: `One square tile seen straight from above: quiet amethyst-gray flagstones with broad slabs, two muted values, and shallow mortar. ${SEAMLESS}` },
			{ keys: ["tile.fracture.void"], tile: true, subject: `One square tile seen straight from above: a black void with a few tiny dim violet specks, like empty space. ${SEAMLESS}` },
			{ keys: ["tile.fracture.wall"], tile: true, subject: "One square tile seen from above: the flat top of a wall in cool, dark violet slate masonry. It must repeat seamlessly in every direction." },
			{ keys: ["tile.fracture.wallTop"], tile: true, subject: "One square tile: a pale violet-gray stone lip above the dark violet front face, seen from slightly above. It must repeat seamlessly left to right." },
			{ keys: ["tile.fracture.rock"], tile: true, subject: "One square tile seen from slightly above: a thick square violet slate pillar with a flat pale cap and a narrow dark base." },
			{ keys: ["enemy.shard", "enemy.splitter", "enemy.splinter", "enemy.flicker"], subject: `${ROW("Four")} ` +
				"(1) a floating jagged crystal creature; (2) a heavy six-sided crystal creature with a crack down its middle, about to split; " +
				"(3) a SMALL fast crystal fragment creature, half the size of the others; (4) a flickering ring-shaped spirit that is not quite all there. " +
				"Their bodies are hot magenta, red and orange crystal with dark cores, clearly dangerous." },
			{ keys: ["rift.fracture.buttress", "rift.fracture.crack", "rift.fracture.gate"],
				subject: "Three separate graphics in one row: a square wall buttress with a lavender cap, a thin pale-violet crooked warning seam, and a dark iron gate panel with three upright bars." },
			{ keys: ["enemy.breach"], subject: "A large boss creature, the Schism: a torn star-shaped rift creature of violet and black stone with a blazing " +
				"magenta-red wound at its heart, jagged and unstable, facing the viewer. Imposing but readable." },
		],
	},
	{
		title: "9. The Ashen Breach",
		why: "Charcoal and ash, embers banked low; the only bright fire is the enemies'.",
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
	{
		title: "10. Decorations",
		why: "What makes a room look lived in: a light and a hanging for the walls, something growing in the corners, and something " +
			"lying on the floor. Four to a picture, one picture per place; the game places them itself. Each must be ONE connected " +
			"object (a pile, a clump), or the cleanup cannot tell where one ends.",
		items: [
			{ keys: DECO_KEYS("shallows"), subject: DECOS("a bright daylit shore at the edge of the Rift, muted sand and gray-green stone",
				"a small weathered bronze lantern on a wall bracket, its glass glowing warm pale yellow",
				"a long strand of dark green kelp hanging down",
				"a clump of pale dry reeds and sea grass growing from one base",
				"a small heap of pale shells and pebbles touching each other") },
			{ keys: DECO_KEYS("fracture"), subject: DECOS("a place breaking apart: dark violet stone over a black void",
				"a dark violet stone wall sconce with a small amber flame",
				"a torn, faded burgundy banner with muted brass trim",
				"a small muted green corner ivy cluster",
				"a small heap of broken dark violet stone rubble") },
			{ keys: DECO_KEYS("ashen"), subject: DECOS("a scorched place: charcoal, gray ash and banked embers",
				"a small iron brazier on a wall bracket holding dull glowing orange embers",
				"a length of rusted iron chain hanging down",
				"a clump of dead, charred thorny branches growing from one base",
				"a small heap of cooled black slag and gray ash") },
			{ keys: DECO_KEYS("town"), subject: DECOS("the safe town: cool gray stone and warm timber",
				"a compact bronze wall lantern with a warm amber square flame",
				"a muted red cloth banner with a gold trim hanging from a short rod, its bottom cut in a notch",
				"a clump of green ivy growing from one base",
				"a small connected pile of muted gray slate chips") },
		],
	},
];
/* The four decoration slots of a place, in the order the picture shows them. */
function DECO_KEYS(rift) { return Object.keys(DECO_PARTS).map((part) => `deco.${rift}.${part}`); }
function DECOS(place, light, hang, growth, scatter) {
	return `Four small decoration objects for ${place}, in one row on a wide landscape image, left to right in the order listed, with ` +
		`wide empty space between them, each ONE connected object, seen from the front: (1) ${light}, seen as it hangs on a wall; ` +
		`(2) ${hang}; (3) ${growth}; (4) ${scatter}. Muted colors that sit quietly in the background; the light's flame or crystal is the one bright spot.`;
}

/* The size line for an item at density `px` (art pixels a tile): game pixels tall
 * for each thing in it, and the one pixel grid they share. */
/* The Ranger's own height in game pixels: it SETS the density (art.js), so its prompt
 * asks for a fixed size rather than following the density. ~20, as in the owner's
 * style example (a wizard about 21 pixels tall). */
export const ANCHOR_PX = 20;
export function sizeLine(item, px = artPx()) {
	const grid = "every pixel a crisp, hard-edged square, all the same size";
	if (item.tile) return `Size: the tile is exactly ${px} by ${px} pixels, ${grid}. Count the pixels: ${px} across, ${px} down.`;
	const hs = item.keys.map((k) => (k === "player.ranger" ? ANCHOR_PX : targetHeight(k, px)));
	const what = item.keys[0].startsWith("shot.") ? "long" : "tall";
	const lead = item.keys.length === 1
		? `Size: ${item.keys[0].startsWith("player.") ? "Each of the three figures is" : "It is"} exactly ${hs[0]} pixels ${what}, ${grid}.`
		: `Size, left to right: ${hs.map((h, i) => `(${i + 1}) ${h} pixels ${what}`).join(", ")}. All on the same pixel grid, ${grid}.`;
	return `${lead} ${small(item)}`;
}
/* How much of the picture the subject may fill. A generator smooths every edge it
 * draws, and drawn LARGE that smoothing is many pixels wide: the owner's Ranger asked
 * for alone in the frame came out as blurry 24-pixel blocks of uneven sizes, while the
 * same Ranger on their style board — small, among other things — was crisp
 * (2026-11-19). So every sprite is asked for small, a hero at about a fifth of the
 * picture's height and the rest in proportion to how tall each is in the game. */
const SHARE = [[0.1, "a tenth"], [0.15, "a seventh"], [0.2, "a fifth"], [0.25, "a quarter"], [0.33, "a third"], [0.4, "two fifths"]];
function small(item) {
	const tall = Math.max(...item.keys.map((k) => SLOTS[k].tall)), f = 0.2 * tall / SLOTS["player.ranger"].tall;
	const [, words] = SHARE.reduce((a, b) => (Math.abs(b[0] - f) < Math.abs(a[0] - f) ? b : a));
	return `Draw it SMALL, the way sprites sit on a style board: the tallest thing in the picture is only about ${words} of the image's height, ` +
		"with plenty of empty background around everything.";
}

/* The full text to paste for an item: the style, the style board line, the subject,
 * then the size at the current density. */
export function promptFor(item, batch, px = artPx()) {
	return [item.tile ? TILE_STYLE : STYLE, REFERENCE, item.subject, sizeLine(item, px)].join("\n\n");
}
