// IN-GAME NUMBERS — values read off the game itself (Switch, by the site's owner) that
// replace the wiki's where the wiki is out of date.
//
// EVERY SPELL IS SHOWN AT LEVEL 1. With every Destiny Fragment unlocked, spells start at
// level 1, so that is the guide's base. Damage scales as (1 + 20% x level) of the level-0
// number, and the wiki's table turned out to BE level 0: the game's level-1 reading of
// each unchanged spell is the wiki's x1.2 to the point (Ultra Loaded Knuckles 150 -> 180,
// Twin Dragon Punch 224 -> 269, Explosive Hug 248 -> 298) and its level-2 reading x1.4
// (Helping Hands 247 -> 346). So derive.applyGameSpells lifts every wiki number to level 1,
// and lifts or lowers each reading here from the `level` it was read at.
//
// A reading here is only needed where a patch changed the spell (or to confirm one that
// did not — those four above are kept as the evidence for the conversion). A field left
// out keeps the wiki's value. A spell the wiki lacks needs `mana` and `hero` before it can
// be ranked; until then it is listed with those blank.
//
// THE FIRST READINGS (2026-10-21, morning) WERE LEVEL 2. Ultra Loaded Knuckles, Twin
// Dragon Punch and Crater Maker came in at 212/316/226 that morning and 180/269/192 at
// level 1 that evening — x1.18 each, which is level 2 over level 1 (x1.17) plus ~1%.
// The four from that batch not yet read again are marked `inferred` and converted from
// level 2; read them again at level 1 to replace the inference.
//
// READINGS VARY. Four spells read twice at the same stated level came out 4-10% apart
// (Balista 140/134, Laceratio 186/202, Plasma Portal 135@2/148@1, Hasta 91/90). The
// spell screen's damage adds Strength and gambit affinity (+10% per matching gambit) to
// the level bonus, so a reading taken mid-run carries that run's bonuses. The cleanest
// reading is a spell with no gambits slotted and no Strength; where two disagree the
// later one is kept. THE SPELL SCREEN LEAVES STRENGTH OUT: at 15% Strength, Sol, Aqua Ball,
// Adustio, Plasma Portal and Eye of Judgment read exactly what they read before. One
// sitting (Balista 140, Sol 313, Pluvia 163, Miseria 156) did carry a +5% bonus from
// something else in that run — Sol and Miseria came out exactly right once it was taken
// out (Sol = the wiki's 300; Miseria 156 -> 150 = its later level-2 175 -> 150). A
// reading with such a bonus says so (`bonus`, in percent) and the conversion removes it. The seven exact matches above were evidently clean, which is why
// the inferred level-2 batch is shaky (Hasta's first reading was level 1 after all).

export const GAME_BASE_LEVEL = 1;
export const GAME_SOURCE = "Read off the game (Switch) by the site's owner";

const SEEN = `${GAME_SOURCE}, 2026-10-21`;
const FIRST = { level: 2, inferred: true, source: SEEN };

export const GAME_SPELLS = {
	// From the first batch, so the level is inferred (see above). Octave's, then Kiran's.
	"Resilio": { dmg: 190, hits: "2-4", ...FIRST },
	"Lightning Dance": { dmg: 169, hits: "1-5", ...FIRST },
	// Octave's. Balista, Hasta and Laceratio were read twice and the later reading is kept
	// (134 vs 140, 90 vs 91, 202 vs 186) — see READINGS VARY above.
	"Balista": { mana: 1, dmg: 134, hits: "2-12", level: 1, source: SEEN },
	// Read 4-6 hits twice and 2-6 once (at level 2, 105 -> 90, the same damage); 4-6 kept.
	"Hasta": { mana: 1, dmg: 90, hits: "4-6", level: 1, source: SEEN },
	"Laceratio": { mana: 2, dmg: 202, hits: "2-6", level: 1, source: SEEN },
	// Sol read 313 in the +5% sitting and 300 since: the wiki's 250 x1.2, unchanged.
	"Sol": { mana: 3, dmg: 300, hits: "1", level: 1, source: SEEN },
	"Pluvia": { mana: 2, dmg: 163, hits: "3-7", level: 1, bonus: 5, source: SEEN },
	// 156 at level 1 in the +5% sitting, 175 at level 2 since: both are 150 at level 1.
	"Miseria": { mana: 2, dmg: 175, hits: "5", level: 2, source: SEEN },
	"Sagitta": { mana: 3, dmg: 300, hits: "1", level: 1, source: SEEN },
	"Gravitas": { mana: 2, dmg: 203, hits: "1", level: 2, source: SEEN },
	"Luna": { mana: 2, dmg: 173, hits: "4-12", level: 1, source: SEEN },
	"Mecanica Aranea": { mana: 2, dmg: 168, hits: "2-12", level: 1, source: SEEN },
	// Not on the wiki. Octave's by its name — every one of his spells is Latin.
	"Infinitus": { mana: 2, dmg: 175, hits: "4-6", level: 2, hero: "Octave", source: SEEN },
	"Adustio": { mana: 2, dmg: 144, hits: "3-5", level: 1, source: SEEN },
	"Perforatio": { mana: 2, dmg: 144, hits: "1-3", level: 1, source: SEEN },
	// 286 at level 2 first, then 245 at level 1: exactly what the conversion predicted.
	"Praecipitatio": { mana: 2, dmg: 245, hits: "1-11", level: 1, source: SEEN },
	"Fax": { mana: 1, dmg: 102, hits: "4-6", level: 1, source: SEEN },
	"Pruna": { mana: 2, dmg: 150, hits: "4-6", level: 1, source: SEEN },
	"Eruca": { mana: 3, dmg: 252, hits: "6", level: 1, source: SEEN },
	// 252 at level 1 and 294 at level 2: the same spell either way.
	"Stella": { mana: 3, dmg: 294, hits: "6-8", level: 2, source: SEEN },
	// Calie's. Prismatic Beam, Emerald Bow, Ruby Spear - Legion and Azurite Falchions -
	// Disk were read twice, on 2026-10-23 and 10-24, and came out the same both times.
	"Prismatic Beam": { mana: 2, dmg: 169, hits: "3", level: 1, source: SEEN },
	"Deadly Connections": { mana: 2, dmg: 148, hits: "2-4", level: 1, source: SEEN },
	"Kunzite Scythe": { mana: 2, dmg: 168, hits: "1-3", level: 2, source: SEEN },
	"Emerald Bow": { mana: 2, dmg: 202, hits: "6", level: 1, source: SEEN },
	"Ruby Spear - Legion": { mana: 1, dmg: 96, hits: "1-3", level: 1, source: SEEN },
	"Ruby Spear - Swarm": { mana: 2, dmg: 172, hits: "1-5", level: 2, source: SEEN },
	"Shimmering Ascent": { mana: 2, dmg: 197, hits: "2-4", level: 1, source: SEEN },
	"Stones Of The Ancients": { mana: 2, dmg: 194, hits: "1-3", level: 1, source: SEEN },
	"Wall Of Arrows": { mana: 2, dmg: 144, hits: "2-6", level: 1, source: SEEN },
	"Azurite Falchions - Disk": { mana: 3, dmg: 280, hits: "3-7", level: 2, source: SEEN },
	"Kunzite Scythe - Scourge": { mana: 3, dmg: 252, hits: "5-7", level: 1, source: SEEN },
	"Pillar of Destruction": { mana: 2, dmg: 184, hits: "3", level: 1, source: SEEN },
	// Unchanged from the wiki (within 1-2 of x1.2 / x1.4). Topaz Gladius - Guardian read
	// 122 at level 1 and 143 at level 2: both the wiki's 102 to the point.
	"Topaz Gladius - Guardian": { mana: 1, dmg: 122, hits: "6", level: 1, source: SEEN },
	"Ruby Spear - Domination": { mana: 3, dmg: 299, hits: "1", level: 1, source: SEEN },
	"Scylla & Charybdis": { mana: 3, dmg: 299, hits: "1", level: 1, source: SEEN },
	"Stellar Radiation": { mana: 2, dmg: 203, hits: "1", level: 2, source: SEEN },
	// Not on the wiki. Calie's by the company it was read in (her gem spells) and its name.
	"Opulent Waltz": { mana: 3, dmg: 252, hits: "3", level: 1, hero: "Calie", source: SEEN },
	// Not on the wiki either: a third Kunzite Scythe beside the plain one and Scourge.
	"Kunzite Scythe - Quake": { mana: 2, dmg: 180, hits: "1-3", level: 1, hero: "Calie", source: SEEN },
	// Kiran's, at the level given.
	"Dirty Way Of Doing This": { dmg: 150, hits: "3-5", level: 1, source: SEEN },
	"Relentless Fury": { dmg: 150, hits: "2-6", level: 1, source: SEEN },
	"Flaming Slide": { mana: 1, dmg: 96, hits: "3-5", level: 1, source: SEEN },
	"Flamin' Hot Strike": { mana: 2, dmg: 162, hits: "1-5", level: 1, source: SEEN },
	"UUUUUULTIMATE BEAM": { mana: 2, dmg: 210, hits: "2-8", level: 2, source: SEEN },
	"Lightspeed Fist": { mana: 2, dmg: 173, hits: "3", level: 1, source: SEEN },
	// Unchanged from the wiki: these (and the three shared ones below) are the evidence
	// that the wiki is level 0.
	"Ultra Loaded Knuckles": { mana: 2, dmg: 180, hits: "1", level: 1, source: SEEN },
	"Twin Dragon Punch": { mana: 3, dmg: 269, hits: "2", level: 1, source: SEEN },
	"Explosive Hug": { mana: 3, dmg: 298, hits: "1", level: 1, source: SEEN },
	"Helping Hands (got it?)": { mana: 3, dmg: 346, hits: "1", level: 2, source: SEEN },
	// Shared spells. Unchanged from the wiki, so more evidence for level 0:
	"Sword of Judgment": { mana: 3, dmg: 364, hits: "1", level: 2, source: SEEN },
	"Magic Cyclone": { mana: 2, dmg: 156, hits: "1-9", level: 1, source: SEEN },
	"Aqua Ball": { mana: 1, dmg: 144, hits: "1-3", level: 1, source: SEEN },
	// Changed. Plasma Portal was read three times: 135 at level 2, then 148 at level 1 twice.
	"Plasma Portal": { mana: 2, dmg: 148, hits: "2-4", level: 1, source: SEEN },
	// The wiki's 117 x 3 hits would be 140 at level 1.
	"Slashing Squall": { mana: 2, dmg: 162, hits: "4-6", level: 1, source: SEEN },
	// Thunder Orb, Meteor Blades and Dark Burst were first read at level 2; their later
	// level-1 readings are exactly what the conversion gave (96, 185, 228).
	"Thunder Orb": { mana: 1, dmg: 96, hits: "3-5", level: 1, source: SEEN },
	"Ice Thrower": { mana: 1, dmg: 94, hits: "3", level: 1, source: SEEN },
	"Nightbreaker": { mana: 2, dmg: 186, hits: "3-5", level: 1, source: SEEN },
	// 202 is also exactly the wiki's 139 at level 2 WITH +5% Strength — taken as clean,
	// like the rest of its sitting, but a re-read would settle it.
	"Thousand Knives": { mana: 2, dmg: 202, hits: "8", level: 2, source: SEEN },
	"Meteor Blades": { mana: 2, dmg: 185, hits: "1-3", level: 1, source: SEEN },
	"Freezing Needles": { mana: 2, dmg: 266, hits: "1-2", level: 2, source: SEEN },
	"Electrospheres": { mana: 1, dmg: 146, hits: "1-7", level: 1, source: SEEN },
	"Burning Wave": { mana: 3, dmg: 250, hits: "8", level: 1, source: SEEN },
	"World-Ender": { mana: 2, dmg: 228, hits: "1", level: 1, source: SEEN },
	"Corrupted Typhoon": { mana: 3, dmg: 259, hits: "8", level: 1, source: SEEN },
	"Eye of Judgment": { mana: 2, dmg: 180, hits: "3-7", level: 1, source: SEEN },
	// Read 105 then 104 at level 2; 104 is the wiki's 74 x1.4 exactly, so it is unchanged.
	"Frost Splinters": { mana: 1, dmg: 104, hits: "2-4", level: 2, source: SEEN },
	"Water Bubbles": { mana: 2, dmg: 218, hits: "6", level: 2, source: SEEN },
	"Demonic Explosion": { mana: 2, dmg: 144, hits: "1-3", level: 1, source: SEEN },
	"Frost Mines": { mana: 2, dmg: 169, hits: "2-4", level: 1, source: SEEN },
	"Dark Outbreak": { mana: 3, dmg: 314, hits: "3-5", level: 2, source: SEEN },
	// Only the mana was read: 2, not the wiki's 1. Damage stays the wiki's x1.2.
	"Fire Rain": { mana: 2, level: 1, source: SEEN },
	// Now 1 mana (the wiki says 2).
	"Shattering Stars": { mana: 1, dmg: 90, hits: "2-4", level: 1, source: SEEN },
	"Shooting Star": { mana: 1, dmg: 120, hits: "1-2", level: 1, source: SEEN },
	"Ravaging Spheres": { mana: 2, dmg: 173, hits: "2-6", level: 1, source: SEEN },
	"Glacial Spikes": { mana: 2, dmg: 173, hits: "2-4", level: 1, source: SEEN },
	"Electrical Deluge": { mana: 3, dmg: 221, hits: "4-12", level: 1, source: SEEN },
	"Ki Blast": { mana: 1, dmg: 96, hits: "1", level: 1, source: SEEN },
	"Poisonous Vortex": { mana: 2, dmg: 173, hits: "2-10", level: 1, source: SEEN },
	"Dark Burst": { mana: 2, dmg: 228, hits: "1", level: 1, source: SEEN },
	// Not on the wiki at all. Crater Maker's hero is not recorded, so it is not ranked.
	"Crater Maker": { mana: 2, dmg: 192, hits: "2-6", level: 1, hero: null, source: SEEN },
	"Hard Rock Punch": { mana: 2, dmg: 144, hits: "1-3", level: 1, source: SEEN },
};
