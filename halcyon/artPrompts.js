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
 * red/orange/magenta, the ground quiet. */

export const STYLE = "Original 2D pixel art game asset for a top-down action RPG, seen from slightly above (three-quarter top-down view). " +
	"Chunky, crisp pixel clusters with one consistent pixel size, a clean near-black outline around every figure, simple flat shading with " +
	"two or three tones per color, light coming from above. No glow, no blur, no gradients, no shadow on the ground. Readable silhouette " +
	"even when shrunk very small. Plain flat solid #00FF00 green background, nothing else behind the subject. No text, no logo, no " +
	"watermark, no border, no extra objects.";

export const TILE_STYLE = "Original 2D pixel art game tile for a top-down action RPG. Chunky, crisp pixel clusters with one consistent " +
	"pixel size, simple flat shading with two or three tones per color, light coming from above. No glow, no blur, no gradients. " +
	"Quiet, low-contrast colors: the ground must never compete with the characters on it. Fill the whole square edge to edge, with no " +
	"border, no frame and no background. No text, no logo, no watermark.";

export const REFERENCE = "Attached is this game's approved style reference. Match its pixel size, outline, shading and level of detail " +
	"exactly; draw only the new subject described below, not the character in the reference.";

const ACCENT = "with bright cyan and white trim so the hero stands out on any floor";
const THREE = (who) => `${who}, drawn three times in one row with wide empty space between them: facing the viewer, facing right, ` +
	"facing away from the viewer. The same character, size and colors in all three. Compact, slightly chunky proportions, head about " +
	"a third of the height.";
const ROW = (n) => `${n} different creatures standing in one row, left to right in the order listed, with wide empty space between ` +
	"them, all the same height, all facing the viewer:";
const SEAMLESS = "It must repeat seamlessly when placed next to copies of itself on all four sides.";

/* One BATCH is one sitting. An item is one generated image: `keys` are the slots it
 * fills (several = one image cut apart left to right), `tile` uses TILE_STYLE. */
export const BATCHES = [
	{
		title: "1. The style anchor: the Ranger",
		why: "Everything else will be matched to this one picture, so take your time. Generate it several times, drop each try here, " +
			"and keep the one you like best at game size. Then keep that ORIGINAL image file: every later prompt attaches it.",
		anchor: true,
		items: [{ keys: ["player.ranger"], subject: THREE(`A small hooded ranger with a short bow, a dark slate-blue cloak and brown leather, ${ACCENT} on the hood and bow`) }],
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
			{ keys: ["player.paladin"], subject: THREE(`A small armored paladin with a mace and a round shield, warm steel plate over a muted brown tabard, ${ACCENT} on the shield rim and helmet`) },
			{ keys: ["player.diviner"], subject: THREE(`A small robed mage holding a staff topped with a star, a deep violet hooded robe, ${ACCENT} on the hood edge and the staff's star`) },
			{ keys: ["player.ninja"], subject: THREE(`A small nimble ninja with throwing knives, dark green wrappings and a mask, ${ACCENT} on the scarf and the blades`) },
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

/* The full text to paste for an item: the style, the reference line after batch 1,
 * then the subject. */
export function promptFor(item, batch) {
	return [item.tile ? TILE_STYLE : STYLE, !batch.anchor && !item.tile ? REFERENCE : null, item.subject].filter(Boolean).join("\n\n");
}
