// IN-GAME NUMBERS — values read off the game itself (Switch, by the site's owner) that
// replace the wiki's where the wiki is out of date.
//
// The wiki's spell table predates several balance passes: these spells differ from it
// by 1.06x to 1.62x, and three changed their hit ranges, so they are real changes rather
// than a level or Strength multiplier. derive.applyGameSpells merges them over the
// payload before anything is computed, so damage per mana, the tier lists and the
// imprint tables all use them; each spell keeps the wiki's old numbers for display.
//
// A field left out keeps the wiki's value (none of these came with a mana cost). A spell
// the wiki lacks entirely needs `mana` and `hero` before it can be ranked; until then it
// is listed with those blank.

const SEEN = "In game (Switch), read by the site's owner, 2026-10-21";

export const GAME_SPELLS = {
	"Resilio": { dmg: 190, hits: "2-4", source: SEEN },
	"Hasta": { dmg: 91, hits: "4-6", source: SEEN },
	"Laceratio": { dmg: 186, hits: "2-6", source: SEEN },
	"Lightning Dance": { dmg: 169, hits: "1-5", source: SEEN },
	"Ultra Loaded Knuckles": { dmg: 212, hits: "1", source: SEEN },
	"Twin Dragon Punch": { dmg: 316, hits: "2", source: SEEN },
	// Not on the wiki at all.
	"Crater Maker": { dmg: 226, hits: "2-6", mana: null, hero: null, source: SEEN },
};
