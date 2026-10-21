// IN-GAME NUMBERS — values read off the game itself (Switch, by the site's owner) that
// replace the wiki's where the wiki is out of date.
//
// THE BASE IS LEVEL 1. With every Destiny Fragment unlocked, spells start at level 1, so
// that is the base this guide uses for any spell read off the game. The wiki's table is
// an older patch at an unstated level, and the two do not differ by one level's +20%:
// these spells move by 1.06x to 1.62x, several with new hit ranges, so a wiki number
// cannot be converted to a level-1 one. Spells without a game reading keep the wiki's
// numbers, and the page says which is which.
//
// derive.applyGameSpells merges these over the payload before anything is computed, so
// damage per mana, the tier lists and the imprint tables all use them; each spell keeps
// the wiki's old numbers for display. A field left out keeps the wiki's value (none of
// these came with a mana cost). A spell the wiki lacks needs `mana` and `hero` before it
// can be ranked; until then it is listed with those blank.

export const GAME_BASE_LEVEL = 1;
export const GAME_SOURCE = "Read off the game (Switch) at level 1 by the site's owner";

const SEEN = `${GAME_SOURCE}, 2026-10-21`;

export const GAME_SPELLS = {
	"Resilio": { dmg: 190, hits: "2-4", source: SEEN },
	"Hasta": { dmg: 91, hits: "4-6", source: SEEN },
	"Laceratio": { dmg: 186, hits: "2-6", source: SEEN },
	"Lightning Dance": { dmg: 169, hits: "1-5", source: SEEN },
	"Ultra Loaded Knuckles": { dmg: 212, hits: "1", source: SEEN },
	"Twin Dragon Punch": { dmg: 316, hits: "2", source: SEEN },
	"Dirty Way Of Doing This": { dmg: 150, hits: "3-5", source: SEEN },
	"Relentless Fury": { dmg: 150, hits: "2-6", source: SEEN },
	// Not on the wiki at all.
	"Crater Maker": { dmg: 226, hits: "2-6", mana: null, hero: null, source: SEEN },
};
