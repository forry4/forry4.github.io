// WINNING RUNS — 23 end-of-run screens at Destiny 54–100, shared by the site's owner
// (2026-10-20) and transcribed by hand. They are one player's wins, so they show what
// HAS worked, not everything that can. The tier lists in editorial.js are weighted by
// them; derive.js `runUsage` counts them.
//
// Read off each screen:
//   stats   the six numbers under the life bar: Strength %, Crit %, Attack Speed %,
//           Armor %, then bonus life and bonus mana (+N)
//   spells  [name, level, imprint | null, affinity %]. The screen also prints the
//           level's damage bonus, which is always 20% per level (X = 200%) — so it is
//           derived, not stored. Names are the wiki's (the screen prefixes Ayla's with
//           her "N°" numbers, which the wiki drops)
//   auras   in slot order; a name appears once per copy (three Allergic Reactions = 3)
//   summon  the Zodiac portrait beside the echoes, only where it is recognizable:
//           Capricorn is the horned elder, Leo the white-maned one. The rest are left
//           null rather than guessed. Echo icons are too small to read at all.
//
// Names the wiki does not have yet are listed in NOT_ON_WIKI; the unit test lets those
// through and holds every other name to the payload.

export const NOT_ON_WIKI = {
	auras: new Set(["Snow Day"]),
	imprints: new Set(["Nulovoko II"]),
	// Arven (DLC, May 2026) has no spell pages yet, and Yamat's two newest are missing.
	spells: new Set(["Gale Claw", "Blazing Thrust", "Maelstrom Howl", "Fowl Plumage",
		"Starburst", "Energy Nexus", "Moonfang", "Moonfang: Void Ripper", "Plenilune Missiles"]),
};

// Where an end screen's own aura text differs from the wiki's. Shown beside the wiki
// text on that aura, labelled as the game's.
export const GAME_TEXT = {
	"Missiles Overload": "Casts Corrupted Typhoon every 20 Missiles created (the wiki says 15).",
	"Dampening Spells": "Mythic: on spell hit, 25% chance to apply 1 Vulnerability (the wiki says 15%).",
	"Meteor Caller": "Mythic: creates 4 Meteor every 8 seconds (the wiki says 10).",
	"Brittle Ice": "Mythic: on a Frostbite enemy, creates 5 Ice Fragment (the wiki says 6).",
	"Heatseeker Shield": "On fall attack, gains Fire Shield for 6 seconds (the wiki says 5).",
	"Warchief Bracers": "The 2-mana refund is Unique.",
	"Magic Weapon": "Mythic: the 1-mana refund is Unique.",
	"Snow Day": "Astral, not on the wiki: on spell cast, creates 2 Snowflake; creates 1 Hail Storm every 7 Snowflake created; increases Snowflake damage by 100%.",
};

const r = (id, date, dl, hero, stats, time, total, summon, engines, spells, auras, note = "") => ({
	id, date, dl, hero, time, total, summon, engines, note,
	str: stats[0], crit: stats[1], speed: stats[2], armor: stats[3], lifeBonus: stats[4], mana: stats[5], life: stats[6],
	spells: spells.map(([name, level, imprint, aff]) => ({ name, level, imprint, aff })),
	auras,
});

export const RUNS = [
	r(1, "2026-05-28", 100, "Yamat", [140, 40, 96, 45, 274, 6, 574], "56:26", 1039020, null, ["Dash", "Ignition"],
		[["Dragon's Breath", 13, "Fajroligo", 50], ["Dragon's Breath", 13, "Fajroinsigno", 50],
			["Dragon's Breath", 14, "Fajrokometo", 50], ["Burning Wave", 15, "Fajrovoko I", 50]],
		["Fire Form", "Blade Storm", "Fire Propellant", "Form of Plasma", "Shrineless Flame"],
		"Three Dragon's Breaths, all full fire. Three of the five auras fire when dashing through enemies."),
	r(2, "2026-05-30", 100, "Ayla", [215, 60, 131, 63, 523, 7, 823], "50:04", 978037, null, ["Missile ↔ Ice Sword loop", "Critical"],
		[["Fatal Trigonometry", 10, "Nulovortico", 50], ["Magic Cyclone", 3, "Glaciobarilo", 50],
			["Thousand Knives", 11, null, 50], ["Dark Burst", 9, "Elektklono", 0]],
		["Aiming System", "Allergic Reaction", "Vision of the Mountain Hunter", "Bigger Body Initiative", "Eye of the Eagle"],
		"Target, crit and Missiles together — and the toughest stat line of the set: 63% armor, 823 life."),
	r(3, "2026-05-30", 100, "Calie", [155, 58, 131, 57, 319, 10, 619], "53:51", 1057755, "Capricorn", ["No auras"],
		[["Topaz Gladius - Downfall", 10, null, 50], ["Topaz Gladius - Downfall", 10, "Nuloinsigno", 50],
			["Kunzite Scythe - Scourge", 13, "Nulovoko II", 50], ["Ruby Spear - Domination", 15, "Fajrondo", 50]],
		[],
		"A Destiny 100 win with all five aura slots empty: spells at X–XV with four gambits each, and the stats, did the work."),
	r(4, "2026-06-03", 70, "Octave", [120, 38, 68, 33, 419, 4, 719], "47:40", 623619, null, ["Missile ↔ Ice Sword loop"],
		[["Caedes", 11, "Nulovortico", 50], ["Incendium", 9, null, 50], ["Pluvia", 7, null, 50], ["Pluvia", 10, null, 50]],
		["Allergic Reaction", "Saber Call", "Missiles Overload", "Allergic Reaction", "Allergic Reaction"],
		"Three Allergic Reactions: 15 Missiles every time life is restored."),
	r(5, "2026-06-13", 100, "Ayla", [120, 46, 131, 36, 307, 7, 607], "47:17", 860378, "Capricorn", ["Thunder Strike", "Max-mana engine"],
		[["Hidden Dirks", 10, "Nulopiko", 50], ["Fatal Dash", 6, "Nulomagneto", 50],
			["Omniscience", 10, "Nulaleatro", 50], ["Fatal Dash", 10, "Nulomisilo", 50]],
		["Warchief Bracers", "Prowess of the Sky", "Thunder Blessing", "Magic Weapon", "Prowess of the Sky"],
		"Two Prowess of the Sky: every hit taken becomes a random buff and 8 Thunder Strikes."),
	r(6, "2026-06-17", 70, "Octave", [145, 50, 48, 18, 395, 10, 695], "48:41", 670589, null, ["Yalee army"],
		[["Fax", 8, null, 50], ["Shooting Star", 8, null, 50], ["Ki Blast", 6, null, 50], ["Ravaging Spheres", 14, "Glacioklono", 50]],
		["Cast Off", "Thunder-Yalee Coat", "Polar-Yalee Coat", "Yalee Magic Charm", "Yalee Token"],
		"Every gambit is Yalee, on cheap 1–2 mana spells that keep the refreshes coming."),
	r(7, "2026-07-19", 100, "Ayla", [200, 43, 141, 30, 403, 6, 703], "50:17", 850657, null, ["Missile ↔ Ice Sword loop"],
		[["Freedom Fighter", 7, "Glaciosabro", 50], ["Flash Step", 7, "Glaciobrulo", 50],
			["Toxic Bomb", 1, "Nulomisilo", 50], ["Electric Scalpels", 6, "Glaciospiralo", 50]],
		["Saber Call", "Allergic Reaction", "Eye of the Eagle", "Saber Call", "Saber Call"],
		"Three Saber Calls: 12 Ice Swords every 8 seconds, each hit making Missiles."),
	r(8, "2026-08-11", 60, "Kiran", [165, 32, 86, 21, 439, 10, 739], "47:18", 631476, "Capricorn", ["Lightning Orb"],
		[["Time-Out!", 10, "Elektkampo", 50], ["Void Punch", 11, "Nulobrulo", 50],
			["Fire Rain", 10, "Fajroeksplodo", 30], ["Energy Projectiles", 1, "Venenkampo", 20]],
		["Dampening Spells", "Magnetic Field", "Thundering Sprint", "Thunder Blessing", "Raging Lightning"]),
	r(9, "2026-08-17", 60, "Arven", [135, 22, 106, 12, 409, 9, 709], "1:17:02", 677327, "Capricorn", ["Ice Fragment"],
		[["Gale Claw", 10, "Glaciopugno", 50], ["Poisonous Vortex", 8, "Venenbrulo", 30],
			["Blazing Thrust", 4, "Nulondo", 30], ["Maelstrom Howl", 10, "Elektropluvo", 50]],
		["Brittle Ice", "Rustling Fall", "Iceberg", "Glacial Spirit", "Ice Pick"]),
	r(10, "2026-08-20", 60, "Kiran", [140, 45, 111, 27, 409, 2, 709], "46:51", 666907, null, ["Fire Shield", "Ignition"],
		[["Hard Rock Punch", 11, "Nulograndkato", 50], ["Energy Projectiles", 10, "Nulobrulo", 50],
			["Flamin' Hot Strike", 12, "Fajroligo", 50], ["Thorns Chains", 1, "Veneninsigno", 50]],
		["Ignited Scar", "Shrineless Flame", "Ring of Sol", "Fiery Retribution", "Heatseeker Shield"]),
	r(11, "2026-08-23", 60, "Ayla", [150, 28, 93, 12, 458, 5, 758], "43:34", 664925, "Leo", ["Meteor shower"],
		[["Hidden Dirks", 14, "Glacioklingo", 30], ["Fatal Dash", 8, "Venenkampo", 10],
			["Fire Rain", 15, "Fajroklingo", 20], ["Toxic Bomb", 5, "Venenforto", 50]],
		["Living Rocks", "Meteor Cast", "Xeno Seeds", "Meteor Caller", "Weakening Star"]),
	r(12, "2026-09-09", 100, "Arven", [37, 19, 44, 9, 268, 7, 568], "55:00", 947030, "Leo", ["Combustion engine", "Critical"],
		[["Moonfang: Void Ripper", 10, "Nulobrulo", 50], ["Moonfang: Void Ripper", 10, "Fajromino", 50],
			["Moonfang: Void Ripper", 5, "Nuloforto", 30], ["Moonfang: Void Ripper", 10, "Nulovortico", 50]],
		["Flame Blessing", "Eye of the Eagle", "The First Flame", "Blazing Scar", "Magic Weapon"],
		"Four copies of one spell made 60% of all damage — and the win came on 37% Strength and 9% armor."),
	r(13, "2026-09-22", 60, "Arven", [115, 22, 93, 9, 461, 3, 761], "46:49", 628911, "Leo", ["Meteor shower"],
		[["Aries Fire Trails", 15, "Nulopiko", 50], ["Shooting Star", 1, "Glacioinsigno", 0],
			["Plenilune Missiles", 10, "Venenmino", 0], ["Energy Nexus", 8, "Fajroinsigno", 50]],
		["Sparkling Stars", "Meteor Caller", "Meteor Caller", "Sparkling Stars", "Meteor Cast"],
		"Two copies each of Sparkling Stars and Meteor Caller; Meteors made 45% of the damage."),
	r(14, "2026-09-26", 100, "Arven", [215, 58, 116, 33, 394, 13, 694], "45:47", 836729, null, ["Ignition"],
		[["Aries Fire Trails", 9, "Fajrospuro", 50], ["Burning Wave", 10, "Nulovoko I", 10],
			["Slashing Squall", 7, "Fajrokometo", 50], ["Meteor Blades", 10, "Fajroeksplodo", 50]],
		["Toxic Burn", "Shrineless Flame", "Incandescent Rain", "Sword of the Warrior", "Blazing Scar"]),
	r(15, "2026-10-09", 100, "Yamat", [305, 48, 111, 33, 502, 9, 802], "35:48", 882596, "Capricorn", ["Ice Swords", "Frostbite"],
		[["Glacial Spikes", 10, "Glaciolanco", 50], ["Glacial Spikes", 10, "Glaciostifto", 50],
			["Fowl Plumage", 10, "Glaciopiko", 50], ["Starburst", 10, "Glaciovoko I", 50]],
		["Saber Call", "Brittle Ice", "Icy Shiv", "Cold Amplification", "Bubbling Projectiles"],
		"The fastest win of the set, on the highest Strength (305%); every imprint is ice."),
	r(16, "2026-10-09", 100, "Arven", [175, 70, 36, 27, 352, 12, 652], "45:39", 817517, "Capricorn", ["Missile ↔ Ice Sword loop"],
		[["Energy Nexus", 6, null, 50], ["Moonfang", 0, "Nulokato", 0],
			["Surrounding Spheres", 8, "Nulosfero", 50], ["Water Bubbles", 6, null, 30]],
		["Durendal Shard", "Magic Weapon", "Vision of the Mountain Hunter", "Astral Cast", "Saber Call"],
		"One spell slot sat at level 0 with no gambits, and the run still won Destiny 100."),
	r(17, "2026-10-13", 100, "Yamat", [255, 30, 106, 36, 463, 10, 763], "37:35", 905869, null, ["Missile ↔ Ice Sword loop"],
		[["Capricorn's Meteor Strikes", 15, "Fajrokometo", 50], ["Sword of Judgment", 15, null, 50],
			["Sword of Judgment", 15, null, 50], ["Slithering Sword", 15, "Glaciobrulo", 50]],
		["Allergic Reaction", "Saber Call", "Allergic Reaction", "Saber Call", "Allergic Reaction"],
		"Every spell at XV, and only two auras: three Allergic Reactions and two Saber Calls."),
	r(18, "2026-10-17", 54, "Calie", [148, 46, 29, 15, 385, 11, 685], "1:13:21", 677003, "Capricorn", ["Max-mana engine"],
		[["Pillar of Destruction", 10, "Glaciostifto", 0], ["Ruby Spear - Legion", 4, "Glaciomino", 30],
			["Ruby Spear - Legion", 10, "Fajrosfero", 30], ["Topaz Gladius - Guardian", 8, "Venenforto", 20]],
		["Warchief Bracers", "Magic Weapon", "Snow Day", "Wisp Caller", "Mana Drainer"]),
	r(19, "2026-10-17", 60, "Calie", [139, 26, 37, 9, 503, 12, 803], "54:06", 661229, null, ["Max-mana engine", "Ice Fragment"],
		[["Kunzite Scythe", 10, null, 0], ["Frost Splinters", 11, "Glacioeksplodo", 10],
			["Surrounding Spheres", 6, "Nuloinsigno", 50], ["Pisces Clones", 11, null, 50]],
		["Magic Weapon", "Warchief Bracers", "Yalee Token", "Ice Pick", "Ice Pebble"]),
	r(20, "2026-10-18", 70, "Calie", [143, 48, 59, 12, 520, 16, 820], "1:14:31", 695797, "Capricorn", ["Max-mana engine"],
		[["Azurite Falchions", 10, null, 50], ["Ruby Spear - Legion", 1, "Nulosejsmo", 50],
			["Ruby Spear - Legion", 10, "Fajroeksplodo", 30], ["Taurus Double Slash", 11, "Fajrosek", 50]],
		["Magic Weapon", "Sparkling Cast", "Warchief Bracers", "Icarus Slime", "Mana Drainer"]),
	r(21, "2026-10-19", 54, "Kiran", [114, 38, 52, 24, 518, 13, 818], "1:44:07", 721258, "Capricorn", ["Max-mana engine"],
		[["Windturner Up-smash", 11, "Nulovortico", 50], ["Flaming Slide", 11, "Venenkampo", 10],
			["Taurus Double Slash", 11, "Elektropluvo", 50], ["Relentless Fury", 9, "Elektklono", 50]],
		["Weaponized Conduct", "Magic Weapon", "Grey Pulsar", "Catnip", "Warchief Bracers"]),
	r(22, "2026-10-20", 80, "Octave", [130, 74, 29, 18, 469, 16, 769], "1:14:39", 732604, null, ["Ice Idol", "Critical"],
		[["Aqua Ball", 6, "Glaciostifto", 50], ["Fax", 11, "Fajrobarilo", 50],
			["Ice Thrower", 3, "Glaciopugno", 50], ["Frost Splinters", 3, "Glaciomino", 30]],
		["Carve Mastery", "Magic Weapon", "Piercing Surprise", "Soothing Ice", "Soothing Ice"],
		"74% crit chance feeds Carve Mastery's Ice Idols; the highest crit of the set."),
	r(23, "2026-10-20", 54, "Octave", [98, 42, 24, 39, 418, 3, 718], "59:54", 628759, null, ["Missile ↔ Ice Sword loop"],
		[["Balista", 11, "Nulobrulo", 50], ["Pruna", 10, "Nulovortico", 50],
			["Hasta", 3, "Fajromino", 50], ["Aries Fire Trails", 11, null, 50]],
		["Pink Pulsar", "Allergic Reaction", "Bigger Body Initiative", "Allergic Reaction", "Allergic Reaction"]),
];

// What the 23 have in common, stated once so the page and the tier notes agree.
export const RUN_FINDINGS = [
	["Engines win, not stat auras",
		"Every run but the aura-less one is built around an engine: one effect (Missiles, Ice Swords, Meteors, Ignition, Lightning Orbs) or max mana. A generic stat aura like Sword of the Warrior shows up once."],
	["Copies stack, and winners stack them",
		"Seven runs carry two or three copies of one aura: three Allergic Reactions (15 Missiles per heal), three Saber Calls, two Prowess of the Sky. Only lines marked Unique stop stacking."],
	["The Missile ↔ Ice Sword loop is the most common engine",
		"Allergic Reaction makes Missiles whenever life is restored and Missile hits make Ice Swords; Saber Call's Ice Swords make Missiles. Six wins run it, across four heroes."],
	["Max mana is the other repeat engine",
		"Magic Weapon (in 8 wins, the most of any aura) turns max mana into Strength; Warchief Bracers and Mana Drainer add max mana and refund it every Spell Refresh."],
	["Levels and gambits carry more than auras",
		"Spells mostly sit at X–XV (+200–300% damage) with four matching gambits (+50%). One Destiny 100 win had no auras at all."],
	["Capricorn is the summon",
		"The horned elder — Capricorn — is the summon in 9 of the 23 wins (Shield, then Velocity and Movespeed, plus Meteors). Leo is next, in 3."],
];
