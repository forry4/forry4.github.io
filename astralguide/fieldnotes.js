// FIELD NOTES — named effects the wiki mentions but never explains, and what we know
// about them from play.
//
// The wiki's aura and imprint text names ~50 things it never defines ("summons 1
// Kamikaze Wisp", "creates 1 Ice Dagger", "Transforms Plasma into Fire Plasma").
// Each entry here:
//   name    as the guide shows it
//   re      what finds it in the wiki's prose (singular and plural)
//   parent  the effect it is a kind of, when there is one (a Kamikaze Wisp is a Wisp):
//           anything that makes the variant also makes the parent, for the synergy links
//   el      its element, when it has no parent to take one from
//   known   what it does, when we know: `makes` feeds the synergy index exactly like the
//           wiki's own text, `note` is shown, `source` says where it came from
//
// The game is only on Switch here, so the files cannot be read: facts come from play
// (the site's owner) and, later, the community Discord. Every `known` entry must name
// its source, so a reader can tell a reported fact from the wiki's.
//
// webapp/test/unit/astralguide.test.mjs requires every entry to be found in the wiki's
// text at least once, so a dead entry or a typo in `re` fails the test.

const PLAY = "Reported from play by the site's owner";

export const VARIANTS = [
	// Fire
	{ name: "Kamikaze Wisp", re: "kamikaze wisps?", parent: "Wisps",
		known: { makes: ["Thunder Strike"], note: "Kamikaze Wisps create Thunder Strikes — so Careless Wisper also feeds Thunder Strike builds.", source: `${PLAY}, 2026-10-20` } },
	{ name: "Venomous Wisp", re: "venomous wisps?", parent: "Wisps" },
	{ name: "Giant Wisp", re: "giant wisps?", parent: "Wisps" },
	{ name: "Blue Embers", re: "blue embers?", parent: "Embers" },
	{ name: "Poison Ignition", re: "poison ignitions?", parent: "Ignition" },
	{ name: "Fire Plasma", re: "fire plasmas?", parent: "Plasma" },
	{ name: "Fire Idol", re: "fire idols?", parent: "Ice Idol" },
	{ name: "Lava Slime", re: "lava slimes?", parent: "Slime" },
	{ name: "Fire Link", re: "fire links?", el: "Fire" },
	{ name: "Homing Firebolt", re: "homing firebolts?", el: "Fire" },
	{ name: "Blaze Mine", re: "blaze mines?", el: "Fire" },
	{ name: "Emberwalk", re: "emberwalks?", el: "Fire" },
	{ name: "Pyrowave", re: "pyrowaves?", el: "Fire" },
	{ name: "Incandescent Barrier", re: "incandescent barriers?", el: "Fire" },
	{ name: "Fire Clone", re: "fire clones?", el: "Fire" },
	// Ice
	{ name: "Ice Dagger", re: "ice daggers?", el: "Ice" },
	{ name: "Ice Spear", re: "ice spears?", el: "Ice" },
	{ name: "Ice Detonation", re: "ice detonations?", el: "Ice" },
	{ name: "Ice Pick", re: "ice picks", el: "Ice" },
	{ name: "Ice Vortex", re: "ice vortex(?:es)?", el: "Ice" },
	{ name: "Frozen Mine", re: "frozen mines?", el: "Ice" },
	{ name: "Frozen Ground", re: "frozen grounds?", el: "Ice" },
	{ name: "Cold Barrier", re: "cold barriers?", el: "Ice" },
	{ name: "Ice Clone", re: "ice clones?", el: "Ice" },
	{ name: "Frost Nimbus", re: "frost nimbus(?:es)?", parent: "Nimbus" },
	{ name: "Freeze Yalee", re: "freeze yalees?", parent: "Yalee" },
	// Electric
	{ name: "Electric Link", re: "electric links?", el: "Electric" },
	{ name: "Thunderfall", re: "thunderfalls?", el: "Electric" },
	{ name: "Thunder Blitz", re: "thunder blitz(?:es)?", el: "Electric" },
	{ name: "Static Void", re: "static voids?", el: "Electric" },
	{ name: "Destructive Laser", re: "destructive lasers?", el: "Electric" },
	{ name: "Rolling Thunder", re: "rolling thunders?", el: "Electric" },
	{ name: "Electrified Area", re: "electri(?:fied|fying) areas?", el: "Electric" },
	{ name: "Electric Clone", re: "electric clones?", el: "Electric" },
	{ name: "Poisonous Spark", re: "poisonous sparks?", parent: "Spark" },
	{ name: "Electrify Yalee", re: "electrify yalees?", parent: "Yalee" },
	{ name: "Electric Meteor", re: "electric meteors?", parent: "Meteor" },
	{ name: "Lightning Sapling", re: "lightning saplings?", parent: "Sapling" },
	// Poison
	{ name: "Giant Slime", re: "giant slimes?", parent: "Slime" },
	{ name: "Flying Slime", re: "flying slimes?", parent: "Slime" },
	{ name: "Dark Cloud", re: "dark clouds?", el: "Poison" },
	{ name: "Demonic Explosion", re: "demonic explosions?", el: "Poison",
		known: { makes: [], note: "An unstable projectile that explodes in a cross pattern (a 2-mana spell; the wiki gives no damage or hits).", source: "The wiki's Demonic Explosion page" } },
	{ name: "Venom Mine", re: "venom mines?", el: "Poison" },
	{ name: "Curse Mark", re: "curse marks?", el: "Poison" },
	{ name: "Weakening Zone", re: "weakening zones?", el: "Poison" },
	{ name: "Poison Clone", re: "poison clones?", el: "Poison" },
	// Neutral
	{ name: "Explosive Missile", re: "explosive missiles?", parent: "Missiles" },
	{ name: "Thick Yalee", re: "thick yalees?", parent: "Yalee" },
	{ name: "Yalee Skyship", re: "yalee skyships?", parent: "Yalee" },
	{ name: "Yalee Air Balloon", re: "yalee air balloons?", parent: "Yalee" },
	{ name: "Blade Whirlwind", re: "blade whirlwinds?", el: "Neutral" },
	{ name: "Boomerang", re: "boomerangs?", el: "Neutral" },
	{ name: "Tectoshock", re: "tectoshocks?", el: "Neutral" },
];
