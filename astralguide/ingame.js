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

export const GAME_BASE_LEVEL = 1;
export const GAME_SOURCE = "Read off the game (Switch) by the site's owner";

const SEEN = `${GAME_SOURCE}, 2026-10-21`;
const FIRST = { level: 2, inferred: true, source: SEEN };

export const GAME_SPELLS = {
	// From the first batch, so the level is inferred (see above). Octave's three, then Kiran's.
	"Resilio": { dmg: 190, hits: "2-4", ...FIRST },
	"Hasta": { dmg: 91, hits: "4-6", ...FIRST },
	"Laceratio": { dmg: 186, hits: "2-6", ...FIRST },
	"Lightning Dance": { dmg: 169, hits: "1-5", ...FIRST },
	// Kiran's, at the level given.
	"Dirty Way Of Doing This": { dmg: 150, hits: "3-5", level: 1, source: SEEN },
	"Relentless Fury": { dmg: 150, hits: "2-6", level: 1, source: SEEN },
	"Flaming Slide": { mana: 1, dmg: 96, hits: "3-5", level: 1, source: SEEN },
	"Flamin' Hot Strike": { mana: 2, dmg: 162, hits: "1-5", level: 1, source: SEEN },
	"UUUUUULTIMATE BEAM": { mana: 2, dmg: 210, hits: "2-8", level: 2, source: SEEN },
	"Lightspeed Fist": { mana: 2, dmg: 173, hits: "3", level: 1, source: SEEN },
	// Unchanged from the wiki: these four are the evidence that the wiki is level 0.
	"Ultra Loaded Knuckles": { mana: 2, dmg: 180, hits: "1", level: 1, source: SEEN },
	"Twin Dragon Punch": { mana: 3, dmg: 269, hits: "2", level: 1, source: SEEN },
	"Explosive Hug": { mana: 3, dmg: 298, hits: "1", level: 1, source: SEEN },
	"Helping Hands (got it?)": { mana: 3, dmg: 346, hits: "1", level: 2, source: SEEN },
	// Shared spells.
	"Plasma Portal": { mana: 2, dmg: 135, hits: "2-4", level: 2, source: SEEN },
	"Ki Blast": { mana: 1, dmg: 96, hits: "1", level: 1, source: SEEN },
	"Poisonous Vortex": { mana: 2, dmg: 173, hits: "2-10", level: 1, source: SEEN },
	"Dark Burst": { mana: 2, dmg: 266, hits: "1", level: 2, source: SEEN },
	// Not on the wiki at all. Crater Maker's hero is not recorded, so it is not ranked.
	"Crater Maker": { mana: 2, dmg: 192, hits: "2-6", level: 1, hero: null, source: SEEN },
	// Kiran's (run 10 cast it).
	"Hard Rock Punch": { mana: 2, dmg: 144, hits: "1-3", level: 1, hero: "Kiran", source: SEEN },
};
