// THE GUIDE'S EDITORIAL LAYER — the only hand-written content on the page.
//
// Everything else is parsed from the wiki (tools/make_data.py). What lives here is
// judgment: tier lists, starting picks and build outlines, plus the wiki's own advice
// condensed. No community tier list for Astral Ascent exists to cite (searched
// 2026-10-19), so every ranking here is ours, and the page says so beside it.
//
// Every NAME below must exist in the payload: webapp/test/unit/astralguide.test.mjs
// resolves each one, so a renamed aura fails the build instead of rendering a dead link.

// The "-voko" imprints name their echo loosely ("summon Linda ignition echo"); this pairs
// each with the Echo-page entry it describes. Three are inferred from the description
// rather than the name, and carry `guess` so the page can say so.
export const VOKO_ECHO = {
	"Fajrovoko I": "Linda's Explosive Crescendo",
	"Fajrovoko II": "Kiran's Fire Combo",
	"Fajrovoko III": "Calie's Sigil Weapons",
	"Glaciovoko I": "Octave's Ice Combo",
	"Glaciovoko II": "Mark's Scourging Whip",
	"Elektvoko I": "Poetic Peddler's Delivery",
	"Elektvoko II": "Calie's Lightning Combo",
	"Elektvoko III": "Lucy's Cyclone",
	"Elektvoko IV": "Ayla's Flashing Knives",
	"Venenvoko I": "Yamat's Scavenger Feast",
	"Venenvoko II": "Ayla's Poison Combo",
	"Venenvoko III": "Zim-Zim's Roots",
	"Venenvoko IV": "Oloon's Secret Recipe",
	"Venenvoko V": "Joey's Smite",
	"Nulovoko I": "Ordan's Rage",
	"Nulovoko III": "John's Heaven Strike",
	"Nulovoko IV": "Sova's Feather Tornado",
	"Nulovoko V": "Kevin's Fan of Knives",
};
export const VOKO_GUESS = new Set(["Fajrovoko III", "Elektvoko I", "Nulovoko IV"]);

// ── Stats ──────────────────────────────────────────────────────────────────
// The wiki's recommended order for a newer player (Player Stats + Hints and Tips).
export const STAT_PRIORITY = [
	{ stat: "Strength", why: "+5% increased damage per stone, additive with spell level and affinity. The stat to max first." },
	{ stat: "Armor", why: "+3% damage reduction per stone, capped at 70%. Each stone adds more effective life than the last." },
	{ stat: "Mana", why: "+1 per stone. More casts per room and faster Zodiac summon charge." },
	{ stat: "Attack Speed", why: "+5% per stone. Basic attacks restore mana and trigger prowess, so speed is also mana." },
	{ stat: "Life", why: "+15 per stone. Past ~500 life an Armor stone is worth more (see Charts)." },
	{ stat: "Critical Chance", why: "+2% per stone, about +1% damage at the default +50% crit. Only take it with crit auras, prowess or Sixth Sense." },
];

// ── The tier lists ─────────────────────────────────────────────────────────
// Judged from the wiki's own text: how often it fires, how much it does, what it
// adds on top, and (for imprints) how hard its condition is to meet.
export const TIER_NOTES = {
	echoes: "How often it fires (automatic > after a Signature Spell or Spell Refresh > once per room), how much it hits, and what it adds — debuffs, healing, economy.",
	imprints: "Payoff against the condition. An imprint that works on any spell beats a stronger one that needs full affinity, a 3-mana spell and level 10.",
	auras: "Value on its own, in any build. A build-defining engine aura can outplay these once its pieces arrive; see Synergies.",
	summons: "Pick the Zodiac whose effect matches your auras first — the wiki's own advice. This ranks raw value when nothing matches.",
	starting: "Auras whose value does not depend on what else you find, for the Room 1 dragon and the first chest.",
};

export const TIERS = {
	echoes: {
		S: [
			["Ordan's Fury", "20% of the boss's max life, free, at the start of every Zodiac fight."],
			["Kevin's Fan of Knives", "Automatic every 30s: 30 knives plus 10 Missiles. No trigger needed."],
			["Ordan's Rage", "30s, the shortest cooldown of the damage echoes: three massive slashes plus 2 Vulnerability."],
			["Sova's Curse", "Marks random enemies and kills them outright. No cooldown."],
			["Ikki's Kind Words", "A revive with 150 HP in every world."],
			["Poetic Peddler's Delivery", "Massive damage, 2 Thunder Strikes, and 5 Quartz per hit."],
		],
		A: [
			["Chamaeleon's Stare", "Every Stone Altar gives 3 random stones — a pile of free stats over a run."],
			["Linda's Explosive Crescendo", "Automatic every 35s, an arrow barrage that applies Ignition."],
			["Joey's Smite", "A damaging breach for a few seconds plus 6 Meteors."],
			["John's Heaven Strike", "12 falling swords and up to 3 Spirit Swords on Spell Refresh."],
			["Yamat's Scavenger Feast", "Crows plus poison sword pillars: two damage sources at once."],
			["Kiran's Water Dragons", "A giant water dragon that 'massively damages' enemies."],
			["Octave's Star-Killer Shot", "A gigantic laser across the arena after a Signature Spell."],
			["Lucy's Cyclone", "A 6s tornado making 2 Sparks every 0.5s — about 24 Sparks per trigger."],
			["Oloon's Secret Recipe", "12 projectiles plus 10 Slimes every 40s."],
			["Zim-Zim's Touch", "Up to 150 HP of healing whenever you drop to 40%."],
			["Sire Bapy's Star Boon", "8 stars at the start of every special room."],
		],
		B: [
			["Yamat's Dance of Contempt", "A slashing wave on a 25s cooldown."],
			["Papa Yalee's Reputation", "A Yalee on spell cast that can chain into more. Great with Yalee auras."],
			["Sova's Feather Tornado", "Automatic, large area, follows you, applies Pacification."],
			["Mark's Scourging Whip", "Pulls enemies together and makes 3 Ice Idols."],
			["Ayla's Poison Combo", "A combo plus 5 Toxic Gas after a Signature Spell."],
			["Kiran's Fire Combo", "A combo plus a shower of Embers."],
			["Octave's Ice Combo", "A combo plus Ice Fragments in every direction."],
			["Calie's Lightning Combo", "A combo plus a chain of 5 plasma."],
			["Ikki's Support", "6 mana, Movespeed and Enrage when a Zodiac reaches 40%."],
			["Apan's Magic Glyph", "Damage plus healing when mana runs low."],
			["Zim-Zim's Laugh", "Infinite Mana when mana runs low, every 80s."],
			["Sova's Benediction", "Every Pavo's Feather is at least +2 levels."],
			["Oloon's Protection", "A damage-absorbing shield after you heal."],
			["Yalee's Warm Aura", "A random buff every 40s."],
			["Sire Bapy's Life Boon", "3 Healing Shards every 40 kills."],
		],
		C: [
			["Ayla's Flashing Knives", "10 blades plus 10s of Thunder Dash, but only once per room."],
			["Calie's Sigil Weapons", "4 swords plus 4 wisps, once per room."],
			["Zim-Zim's Roots", "10 projectiles plus Saplings, once per room."],
			["Ikki's Regenerating Pack", "Wolves that heal 2 HP per hit, on a 75s cooldown."],
			["Chamaeleon's Luck", "A small random reward after each fight room."],
			["Poetic Peddler's Chance", "3 keys per 150 Quartz collected."],
			["Poetic Peddler's Loyalty Card", "Two half-price items per bar visit."],
			["Barbecue's Astral Wish", "A recycled Aura Altar becomes a new aura."],
		],
	},
	imprints: {
		S: [
			["Nuloklingo", "2 Thousand Knives (8 hits each) per mana spent, on any spell, no condition."],
			["Venenkateno", "4 Thorns Chains per mana spent; +6 more at full poison affinity."],
			["Fajrokometo", "A Magma Comet per 2 spell levels — 5 at level 10, +3 at full fire."],
			["Glaciopugno", "A Water Bubble per 2 spell levels, +5 at full ice."],
			["Nulomisilo", "4 giant exploding missiles on every cast, no condition."],
			["Nulobrulo", "+20% spell damage per neutral gambit — +80% on a full neutral spell."],
		],
		A: [
			["Nulopiko", "4 Freezing Needles per mana spent, more with spell levels."],
			["Nulosfero", "4 Surrounding Spheres per cast, and they keep stacking at level 10."],
			["Elektsparko", "4 Sparks per mana spent; Quicksilver at level 10."],
			["Nulokato", "2 Yalee per mana spent."],
			["Nuloekzekuto", "9% chance per hit to kill a non-boss outright, +4% per neutral gambit."],
			["Fajroklingo", "2 Meteor Blades on every cast, +1 per ember gambit."],
			["Elektlasero", "A destructive laser on every cast, +2 with 4 plasma gambits."],
			["Nulovortico", "Corrupted Typhoon (8 hits) on every cast at full neutral affinity."],
			["Nulovoko V", "Kevin's Fan of Knives echo, without needing a 3-mana spell."],
			["Nulovoko I", "Ordan's Rage echo — the best damage echo, on a 3-mana neutral spell."],
		],
		B: [
			["Venenspiralo", "2 Poisonous Vortex (up to 10 hits each) at full poison affinity."],
			["Fajropluvo", "Fire Rain from the first enemy hit at full fire affinity."],
			["Veneneksplodo", "Dark Burst around you at full poison affinity."],
			["Elektokulo", "Eye of Judgment at full electric affinity."],
			["Glaciosabro", "A cryogenic sword at full ice affinity."],
			["Fajroglobo", "A Giant Wisp casting World-Ender at full fire affinity."],
			["Nulograndkato", "A Thick Yalee at full neutral affinity."],
			["Fajroklono", "A fire clone that explodes and applies 3 Burn."],
			["Glacioklono", "An ice clone whose pulse applies 2 Freeze."],
			["Venenklono", "A poison clone with a 2-Poison pulse."],
			["Elektklono", "An electric clone near the first enemy hit."],
			["Elektbrulo", "+10% damage per Electrify stack on the target."],
			["Glaciobrulo", "+12% damage per Freeze stack on the target."],
			["Venenbrulo", "+7% damage per Poison stack on the target."],
		],
		C: [
			["Fajrosfero", "A 30% chance of one fireball on a critical hit."],
			["Venenakva", "A 30% chance of Aqua Ball on a critical hit."],
			["Fajrosorbo", "Heals 5 life per burning enemy."],
			["Nulomagneto", "Pulls 4 enemies together; +100% damage only at full neutral."],
			["Nuloforto", "A random 3-second buff."],
			["Venenforto", "+30% poison damage for 10 seconds."],
		],
	},
	auras: {
		S: [
			["Sword of the Warrior", "+30% Strength, +20% Attack Speed, +20% crit chance. Fits any build."],
			["Spinning Spirit", "+30% Strength and a free Ravaging Spheres every 10 seconds."],
			["Grey Pulsar", "+30% Strength and a periodic 5-stack Vulnerability pulse."],
			["Cetus Secret", "+150 max life, +12% armor, +3 max mana."],
			["Warchief Bracers", "Enrage and 2 mana on every Spell Refresh, +3 max mana."],
			["Entropic Magic", "20 Missiles on every Spell Refresh that apply random effects."],
		],
		A: [
			["Twin Calibur", "2 permanent Spirit Swords that fire Missiles."],
			["Seal of the Storm Lord", "2 permanent Nimbus that grow stronger together."],
			["Vampiric Friend", "2 permanent Wisps, +100% Wisp damage, and life steal."],
			["Seal of the Fairy King", "2 permanent Wisps that shoot explosive fireballs."],
			["Newfound Strength", "+50% Strength above 70% life, heals 3 on every cast."],
			["Balance Master", "+20% crit chance, +25% crit damage, Velocity on crit."],
			["Guardian Shield", "+60% Strength and +30% Attack Speed while its Shield is up."],
			["Adamantite Armor", "Absorbs a hit every 3 hits taken, +12% armor."],
			["Toxic Chains", "Thorns Chains on poisoned enemies, +8% Strength per poisoned enemy."],
			["Blinding Comets", "6 Magma Comets on every Combustion."],
			["Missiles Overload", "Corrupted Typhoon every 15 Missiles, +100% Missile damage."],
			["Mirror Swords", "Thousand Knives on every Spirit Sword spawn."],
		],
		B: [
			["Traveler Wisdom", "15% life, 6 mana and Movespeed every room."],
			["Wild Breath", "+75 max life, healing on hit and on refresh."],
			["Eye of the Eagle", "+15% crit chance and damage, Missiles on crit."],
			["Disorienting Weapon", "+20% crit chance, +25% crit damage, a boomerang on crit."],
			["Sorceror Mantle", "Infinite Mana and Enrage when you run dry."],
			["Thunder Blessing", "+25% damage on Electrify, and doubles Electrify applied."],
			["Flame Blessing", "+25% damage on Burn, and doubles Burn applied."],
			["Frost Blessing", "+25% damage on Freeze, plus Frostbite chances."],
			["Magic Weapon", "+2% Strength per max mana."],
			["Scale Armor", "+9% armor plus Ice Swords and a Shield when hit."],
		],
	},
	summons: {
		S: [
			["Libra", "A powerful energy ray that annihilates everything in its path: pure damage."],
			["Andromeda", "Kills an enemy below 20% life, automatically, without replacing your summon (DLC)."],
		],
		A: [
			["Gemini", "Shares strength for 16s; every spell cast summons a clone that makes a Lightning Orb."],
			["Virgo", "Shares strength for 16s; basic attacks summon Virgo, who makes 3 Sparks."],
			["Capricorn", "Shield for 6s, then Velocity and Movespeed for 10s, plus Meteors."],
			["Taurus", "A massive energy wave plus 4 Spirit Swords."],
		],
		B: [
			["Sagittarius", "Follows you for 6s shooting Missiles."],
			["Pisces", "6 water elementals for 10s that make Ice Swords."],
			["Aquarius", "Attacks for 6s and calls 4 Nimbus."],
			["Scorpio", "10 spears from the sky that make Ice Idols."],
			["Cancer", "Bombs from Basileus plus 8 Snowflakes."],
			["Leo", "Spins for 6s applying Ignition."],
			["Aries", "A giant punch plus 6s of Fire Shield."],
		],
	},
};

// For the Room 1 dragon and the first chest: auras that are good with NOTHING else.
export const STARTING_AURAS = [
	["Sword of the Warrior", "Strength, speed and crit with no conditions."],
	["Spinning Spirit", "Strength plus a free spell every 10s."],
	["Grey Pulsar", "Strength plus Vulnerability, which helps everything else you find."],
	["Cetus Secret", "Life, armor and mana: the safest start for a new player."],
	["Warchief Bracers", "Mana and Enrage every refresh. Any spell list triggers it."],
	["Newfound Strength", "+50% Strength while healthy, plus healing on every cast."],
	["Traveler Wisdom", "Sustain every room — the best common-tier pick for learning."],
	["Entropic Magic", "Missiles and random effects on refresh, with no setup."],
];

// ── Build archetypes ───────────────────────────────────────────────────────
// Engines read straight off the aura text: what MAKES the effect, what PAYS IT OFF.
// The Synergies tab derives the full lists automatically; these are the curated cores.
export const ARCHETYPES = [
	{ name: "Combustion engine", element: "Fire", effect: "Combustion",
		how: "Stack Burn until it hits 10 and explodes, then let every Combustion cast more spells.",
		makers: ["The First Flame", "Flame Blessing", "Raw Force", "Exalted Fall", "Ardent Sprint"],
		payoffs: ["Blinding Comets", "Fire Propellant", "Explosive Flames", "Explosive Wisp"],
		gambits: ["Burn"], imprints: ["Fajrokometo", "Fajroeksplodo", "Fajromino"], summon: "Leo" },
	{ name: "Embers", element: "Fire", effect: "Embers",
		how: "Flood the floor with Embers, then convert them into Meteor Blades and missiles.",
		makers: ["Ember Shock", "Wisdom of the Blue Fire", "Killer Ember", "Homing Ember"],
		payoffs: ["Solar Swords", "Killer Ember", "Wisdom of the Blue Fire"],
		gambits: ["Embers"], imprints: ["Fajroklingo"], echo: "Kiran's Fire Combo" },
	{ name: "Wisp swarm", element: "Fire", effect: "Wisps",
		how: "Permanent wisps plus on-cast wisps; every Wisp damage aura multiplies the swarm.",
		makers: ["Seal of the Fairy King", "Vampiric Friend", "Careless Wisper", "Wisp Caller", "Fairy Revenge"],
		payoffs: ["Explosive Wisp", "Vampiric Friend", "Careless Wisper"],
		gambits: ["Wisps"], imprints: ["Fajroglobo"] },
	{ name: "Frostbite", element: "Ice", effect: "Frostbite",
		how: "Reach 10 Freeze for Frostbite, then trigger every 'on Frostbite enemy' payoff.",
		makers: ["Gelid Charm", "Frost Blessing", "Icy Blow", "Glacier's Fall", "Sudden Frostbite"],
		payoffs: ["Frost Sculptor", "Bubbling Projectiles", "Absolute Zero", "Brittle Ice"],
		gambits: ["Freeze"], imprints: ["Glaciogrundo", "Glacioeksplodo", "Glaciobrulo"], summon: "Cancer" },
	{ name: "Ice Swords", element: "Ice", effect: "Ice Sword",
		how: "On-cast and on-refresh swords, then Cold-Steel Sword every fifth one.",
		makers: ["Serac Saber", "Saber Call", "Icy Shiv", "Vision of the Mountain Hunter"],
		payoffs: ["Frozen Overpower", "Swords Invasion", "Icy Shiv"],
		gambits: ["Ice Sword"], imprints: ["Glaciosabro"], summon: "Pisces" },
	{ name: "Snowflake orbit", element: "Ice", effect: "Snowflake",
		how: "Orbiting snowflakes that cast Frost Mines and Plasma on hit.",
		makers: ["Glacial Spirit", "Ring of Storms and Blizzards", "Snow Amulet", "Frost Sculptor"],
		payoffs: ["Magnifying Snowflake", "Ring of Storms and Blizzards", "Flaming Touch"],
		gambits: ["Snowflake"], imprints: ["Glaciomino"], summon: "Cancer" },
	{ name: "Spark chain", element: "Electric", effect: "Spark",
		how: "Double every Electrify, then turn Sparks into Quicksilver casts.",
		makers: ["Thunder Blessing", "Sparkling Cast", "Sparks Conductor", "Sparkling Sprint"],
		payoffs: ["Chasing Sparkle", "Sparks Conductor", "Storm Blow"],
		gambits: ["Electrify"], imprints: ["Elektsparko", "Elektbrulo"], summon: "Virgo" },
	{ name: "Plasma", element: "Electric", effect: "Plasma",
		how: "Plasma on cast and on refresh, lasers every fifth one.",
		makers: ["Plasma Cast", "Plasma Generator", "Weaponized Conduct", "Form of Plasma"],
		payoffs: ["Weaponized Conduct", "Short Circuit", "Plasma Generator"],
		gambits: ["Plasma"], imprints: ["Elektlasero"], echo: "Calie's Lightning Combo" },
	{ name: "Nimbus storm", element: "Electric", effect: "Nimbus",
		how: "Permanent Nimbus that grow stronger the more are active.",
		makers: ["Seal of the Storm Lord", "Storm Caller", "Stormy Outburst", "Sleety Cloud"],
		payoffs: ["Seal of the Storm Lord", "Nimbus Revenge"],
		gambits: ["Nimbus"], imprints: ["Elektokulo"], summon: "Aquarius" },
	{ name: "Toxic chain", element: "Poison", effect: "Toxic Gas",
		how: "Poison everything, then let Toxic Gas cast Demonic Explosion and Spirit Swords.",
		makers: ["Toxic Firework", "Spreading Pest", "Sword Fang", "Maddening Darkness", "Viper Fall"],
		payoffs: ["Chain Reaction", "Toxic Chains", "Sword Fang"],
		gambits: ["Toxic Gas", "Poison"], imprints: ["Venendiablo", "Venenkateno"], echo: "Ayla's Poison Combo" },
	{ name: "Sapling garden", element: "Poison", effect: "Sapling",
		how: "A standing army of saplings that casts Poisonous Vortex every tenth.",
		makers: ["Green Thumb", "Xeno Seeds", "Living Rocks", "Sapling Generator", "Cold Snap"],
		payoffs: ["Saplings Wrath", "Poisonous Seeds", "Green Thumb"],
		gambits: ["Sapling"], imprints: ["Venenspiralo"], echo: "Zim-Zim's Roots" },
	{ name: "Meteor shower", element: "Poison", effect: "Meteor",
		how: "Meteors on cast; each hit casts Dark Burst or grows saplings.",
		makers: ["Meteor Cast", "Living Rocks", "Sparkling Stars", "Meteor Caller"],
		payoffs: ["Radioactive Impact", "Weakening Star", "Living Rocks"],
		gambits: ["Meteor"], imprints: ["Veneneksplodo"], summon: "Capricorn", echo: "Joey's Smite" },
	{ name: "Missile barrage", element: "Neutral", effect: "Missiles",
		how: "Missiles from every source, cashed in for Corrupted Typhoon.",
		makers: ["Entropic Magic", "Astral Cast", "Missile Generator", "Bigger Body Initiative", "Twin Calibur"],
		payoffs: ["Missiles Overload", "Bigger Body Initiative", "Entropic Magic"],
		gambits: ["Missiles"], imprints: ["Nulomisilo"], summon: "Sagittarius", echo: "Kevin's Fan of Knives" },
	{ name: "Spirit Swords", element: "Neutral", effect: "Spirit Sword",
		how: "Permanent and on-cast swords, each spawn casting Thousand Knives.",
		makers: ["Twin Calibur", "Blade Dance", "Durendal Shard", "Sword Sculptor"],
		payoffs: ["Mirror Swords", "Blade Dance", "Twin Calibur"],
		gambits: ["Spirit Sword"], imprints: ["Nuloklingo"], summon: "Taurus", echo: "John's Heaven Strike" },
	{ name: "Yalee army", element: "Neutral", effect: "Yalee",
		how: "Yalee on every cast and refresh; every fifth is a Thick Yalee, every tenth a skyship.",
		makers: ["Polar-Yalee Coat", "Thunder-Yalee Coat", "Yalee Token", "Catnip", "Yalee Magic Charm"],
		payoffs: ["Thick Yalee", "Cast Off", "Thunder-Yalee Coat"],
		gambits: ["Yalee"], imprints: ["Nulokato", "Nulograndkato"], echo: "Papa Yalee's Reputation" },
	{ name: "Critical", element: "Neutral", effect: "Critical Hit",
		how: "Stack crit chance and crit damage together — each multiplies the other (see Charts).",
		makers: ["Sword of the Warrior", "Balance Master", "Disorienting Weapon", "Eye of the Eagle", "Carve Mastery"],
		payoffs: ["Eye of the Eagle", "Carve Mastery", "Homing Ember", "Ignited Scar"],
		gambits: ["Critical Hit", "Target"], imprints: ["Fajrosfero", "Venenakva"] },
];

// The wiki's four general build strategies (Hints and Tips).
export const BUILD_STRATEGIES = [
	{ name: "Avatar", text: "Grab one spell of each element early. Most gambits then have a home, and you can pivot when a strong aura shows up late." },
	{ name: "Pure Neutral", text: "Mostly or only neutral spells. Generically strong gambits fit everywhere, and any neutral aura works." },
	{ name: "Focused", text: "One or two elements, all in. Recycle anything off-theme for Quartz to buy the right spells and gambits later." },
	{ name: "Low Cost Caster", text: "Only 1-mana, multi-hit spells with on-cast gambits and mana-on-hit gambits. Take every on-cast aura you see." },
];

// The wiki's general tips, condensed.
export const TIPS = [
	["Aura first", "It is easier to find spells and gambits for an aura than an aura for your spells. Pick one or two auras to keep and build every trigger around them."],
	["Gambits later", "Avoid chasing gambit rooms in worlds 1–2 until you know which spells will stay. A placed gambit can only be replaced, never removed."],
	["Rarer isn't always better", "An off-build Astral aura can be worth less than the Star Fragments you get for scrapping it."],
	["Keep 5 keys", "Exploration rooms always have a key shrine; the 5-key option is the best value."],
	["Cheap refreshes", "All four spells must be cast before any refreshes. A couple of 1-mana spells make Spell Refresh — and every 'on refresh' effect — come round faster."],
	["Save the Sun Room", "Its Mythic gambit converts the spell's affinity. Use it later on a spell you like whose element doesn't match your build."],
	["Charge before you leave", "Casting spends mana you would lose at the door and fills the Zodiac summon gauge."],
	["Heal, then buy shards", "A Healing Shrine refills all 5 shards for the same price whether you need 1 or 5, so use your shards first."],
];

// Rooms that always appear, and the ones worth knowing (New Player Guide).
export const RUN_MAP = [
	["Room 1", "Safe. The Prowess shrine (one upgrade per level gained) and the world choice. World 1 also offers a new spell; with Zim-Zim's upgrade, a baby dragon offers a free aura."],
	["Room 5, world 1", "Telluric spell room: a free spell from a selection (reroll for 100 Sun Pieces)."],
	["Room 11", "Andromeda's Bar: Healing Shrine, Drinks (stats), the Aura Refiner, the Peddler's shop, and Zodiacs to recruit."],
	["Room 12", "A Zodiac boss — one of the world's three. The chest holds healing and a choice of aura."],
	["Void Room", "A Star Guardian mini-boss. One per world. Dangerous early; rewards grow with the Void Catalyst."],
	["Sun Room", "A free Mythic gambit of any kind that converts the spell's affinity. Once per run."],
	["Moon Room", "150 life buys a Zodiac spell, often levelled and pre-gambited. Once per run."],
	["Pavo's Ruins", "Trade life for Pavo's Feathers (+1, +2 or +5 spell levels)."],
	["Cetus' Cavern", "A gambit slot unlocker plus 2 themed gambits."],
	["The Forge", "Choose: unlock a gambit slot on all spells, +1 level on all spells, or any hero spell in any element."],
	["Yalee Kingdom", "An aura shop with better odds of upgraded rarities."],
	["Echo Isles", "A free echo of your choice."],
	["Cursed Telescope", "A permanent perk with a malus that lasts until the next bar."],
];

// The wiki's recommended first Destiny Fragments (Early Destiny Fragment Allocation).
export const CATALYST_PICKS = {
	first10: [["Opalescent Vigor", 1], ["Magic Symbiosis", 1], ["Best Customer", 1], ["Star Shards", 1]],
	first50: [["Opalescent Vigor", 1], ["Magic Symbiosis", 2], ["Evolutive Growth", 1], ["Best Customer", 1],
		["Star Shards", 2], ["Adventurer's Gift", 1], ["Sacred Dew", 1], ["Star-Forged", 1], ["Locksmith", 2], ["Spirit Friends", 1]],
};

// Signature spells, from the wiki's Signature Spell page.
export const HEROES = [
	{ name: "Ayla", signature: "Dashes to a target, dealing damage, and applies a Shadow Mark that increases damage taken." },
	{ name: "Kiran", signature: "A counter stance (invincible), then a counter punch." },
	{ name: "Calie", signature: "Attacks create gems; the signature pulls them back to her, dealing damage." },
	{ name: "Octave", signature: "Summons a drone (Bellator) that attacks nearby enemies." },
	{ name: "Yamat", signature: "Transforms for mobility while firing homing missiles at nearby enemies (DLC)." },
];
