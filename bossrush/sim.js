// Boss Rush combat baseline from Halcyon Rift's last greybox (d52d2f57).
// This is a standalone copy for Boss Rush balance changes.
/* Halcyon Rift — the fight, simulated in the browser (design §18.5).
 *
 * A PURE module: no DOM, no React, no renderer, no clock. `step(state, input)`
 * advances exactly one fixed tick of 1/60 s and is DETERMINISTIC — same dungeon,
 * same loadout, same inputs gives the same run on any browser:
 *   - all randomness comes from the seeded generator below (never Math.random);
 *   - timers are integer TICKS, never wall-clock;
 *   - no Math.sin/cos/atan2/exp: engines may differ in their last bit, so the
 *     module carries its own `dsin`/`dcos` built from + - * / only, which IEEE
 *     754 makes exact everywhere. Math.sqrt/round/floor are exact too.
 *
 * What the server learns of a run comes from `state.events` (kill, pickup,
 * death, recall, complete) — the page queues them (design §18.4), all but the
 * ones marked `local` (a heal, a level-up: the server keeps no HP and works the
 * level out from the XP it credits itself). The server
 * never simulates; it checks those claims against the dungeon it generated.
 *
 * GREYBOX: every number below is a placeholder to tune by playing (design §23).
 */

export const TPS = 60;
export const DT = 1 / TPS;
const PI = 3.141592653589793;
const TAU = 6.283185307179586;
const HALF_PI = 1.5707963267948966;

// ── deterministic maths ─────────────────────────────────────────────────────
export function dsin(a) {
	a = a - TAU * Math.round(a / TAU);                 // [-PI, PI]
	if (a > HALF_PI) a = PI - a; else if (a < -HALF_PI) a = -PI - a;
	const a2 = a * a;                                  // Taylor to a^13: < 1e-9 on [-PI/2, PI/2]
	return a * (1 - a2 / 6 * (1 - a2 / 20 * (1 - a2 / 42 * (1 - a2 / 72 * (1 - a2 / 110 * (1 - a2 / 156))))));
}
export const dcos = (a) => dsin(a + HALF_PI);

function hashSeed(str) {
	let h = 2166136261 >>> 0;
	for (let i = 0; i < str.length; i++) { h ^= str.charCodeAt(i); h = Math.imul(h, 16777619) >>> 0; }
	return h;
}
function rand(st) {                                  // mulberry32, its state in the sim state
	st.rng = (st.rng + 0x6D2B79F5) >>> 0;
	let t = st.rng;
	t = Math.imul(t ^ (t >>> 15), t | 1);
	t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
	return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
}

// ── tuning (greybox) ────────────────────────────────────────────────────────
export const PLAYER_R = 0.32;
export const PLAYER_SPEED = 5.6;                     // tiles / s
export const REACH = 1.3;                            // how close E has to be
export const RECOVERY_MARGIN = 40;                   // design §9.2: limit = min(max, lowest + margin)
export const HEAL = 35;                              // a heal pickup: +HP and +limit
/* THE HEALING POTION (owner's call, 2026-11-18, design §19.1): never a stock, always
 * a cooldown. It heals and raises the recovery limit like a smaller heal orb. */
export const POTION_HEAL = 30;
export const POTION_COOLDOWN = 20 * TPS;
/* THE ABILITY TABLE (owner's calls, 2026-11-19). Every ability costs 30 MP at tier 0
 * and 5 more a tier (80 at tier 10); what it does grows a little faster, so a higher
 * tier is always a little better per MP and never worse:
 *   volley   — 55 damage in all (its arrows share it), +10 a tier;
 *   starfall — 45, +10 a tier;
 *   field    — a 2.0-tile radius, +10% of that a tier; burns 6 a pulse, +20% a tier;
 *   counter  — the next shot x2.0, +0.4 a tier (x6 at tier 10), with a FLAT cooldown:
 *              its cost rising cannot alone stop a cheap charm being the best guard.
 * Ability power multiplies the effects, never the cost. */
export const ABILITY_COST = 30;
export const ABILITY_COST_PER_TIER = 5;
export const abilityCost = (kind, tier = 0) => ABILITY_COST + ABILITY_COST_PER_TIER * (tier ?? 0);
export const ABILITY = {
	volley: { dmg: 55, perTier: 10 },
	starfall: { dmg: 45, perTier: 10 },
	slow: { radius: 2, radiusPerTier: 0.1, pulse: 6, pulsePerTier: 0.2 },
	counter: { mult: 2, perTier: 0.4, cooldown: 6 * TPS },
};
export const SHIELD_DURATION = 5 * TPS;
export const SLOW_DURATION = 4 * TPS;
export const SLOW_RADIUS = 2;
export const SLOW_FACTOR = 0.45;

/* NO ABILITY COOLDOWN (owner's call, 2026-11-19, reversing 2026-11-18's): MP is the
 * only limit on casting — except the Ninja's counter, which has a flat 6s one
 * (ABILITY.counter.cooldown, owner's call the same day) so it is never constant safety. The Paladin's field also BURNS (owner's ask, 2026-11-19):
 * every SLOW_PULSE ticks it hits every enemy inside it for its damage — slight,
 * tier- and Ability-power-scaled like the other abilities' damage. */
export const SLOW_PULSE = 30;
export const SLOW_DAMAGE = 6;
// Starfall (the Diviner): a star lands where you aim, after a beat, on everything near it.
export const STARFALL_DELAY = 36;
export const STARFALL_RADIUS = 1.5;
export const STARFALL_RANGE = 8;
// Counter (the Ninja): a hit inside the window is ignored, guards for a moment after,
// and the next shot hits harder. The guard does NOT scale (owner: no late-game
// invincibility); Ability power scales the damage.
export const COUNTER_WINDOW = TPS;
export const COUNTER_GUARD = 30;
export const COUNTER_MULT = 2;
/* THE UNIQUES' numbers (owner's list, 2026-11-19). A ring's effect grows with its tier
 * like a band's (`tierScale`); an armor's stats follow the armor ladder. */
export const UNIQUE = {
	burn: { dmg: 3, every: 30, last: 120 },          // Ember Loop: per tick of burning, at T1
	coilCut: 10, coilHp: 20,                          // Miser's Coil: MP off each cast, HP it costs
	leech: 5,                                         // Leechstone: HP a kill heals, at T1
	glass: { att: 12, def: 6 },                       // Glass Ring
	windrunner: 1.15,                                 // move speed
	fullMoon: 1.2,                                    // shot damage while MP is full
	thorns: { n: 4, dmg: 10, speed: 10, life: 30 },  // shards each hit sends out, at T1
	dusk: 1.5,                                        // the next shot after a kill
	gale: { speed: 18, range: 10, r: 0.3 },           // the volley as one arrow through everything
	anchor: 1.5,                                      // the anchored field: radius and burn
	echo: { delay: TPS, share: 0.5, cost: 10 },       // the star lands again
	echoRing: { n: 8, speed: 14, life: 21 },          // blades a caught hit sends out
	splash: { r: 1, share: 0.5 },
	comet: { n: 4, share: 0.4, speed: 10, life: 24 },
	// THE ASHEN BREACH'S (owner's list, 2026-11-19). Damage and caps here are at T1.
	phoenix: { guard: TPS, r: 2.5, last: 3 * TPS, dmg: 8 },       // the fire it sets, per pulse
	ash: { r: 1.8, dmg: 20 },                                      // an enemy dying while it burns
	coal: { every: 90, cap: 8 },                                   // +1 Attack each 1.5 s unhit, to the cap
	emberweave: { every: 12, r: 0.55, last: 90, dmg: 4 },          // the trail, per pulse
	cinderguard: { def: 6 },                                       // Defense while standing in fire
	flare: { r: 1.2, last: 3 * TPS, share: 0.3 },                  // a flare's fire, per pulse, of the shot
	censer: { burn: 2, slow: 0.75 },                               // twice the burn; shots keep 75% speed
	meteor: { last: 3 * TPS, share: 0.08 },                        // the crater, per pulse, of the star
	kunai: { delay: TPS, share: 0.6 },                             // the stuck blade's burst, of the throw
};

/* One standard ability per class (owner's call, 2026-11-18). The shield is retired
 * with its item, kept in the code for a future class. */
export const CLASS_INFO = {
	ranger: { name: "Ranger", description: "A quick ranged fighter with a volley of arrows.", ability: "volley" },
	paladin: { name: "Paladin", description: "A close-range guardian whose field slows enemy shots and burns enemies around them.", ability: "slow" },
	diviner: { name: "Diviner", description: "A long-range mage who calls stars down on a spot.", ability: "starfall" },
	ninja: { name: "Ninja", description: "A quick thrower who counters a hit and strikes back twice as hard.", ability: "counter" },
};

/* ROOMS LOCK (owner's call, 2026-11-18, design §14.1a): an enemy sleeps — and
 * cannot be hurt — until the player is all the way inside its room; then both of
 * that room's doors seal and everything in it wakes at once. The doors open when
 * the last of them falls. While a room has not been fought, its doorways are a
 * VEIL that stops shots both ways, so nothing is fought through a door. */
export const ENEMY = {
	// A chaser also spits a short shot when it is close (owner's ask, 2026-11-18): a
	// short telegraph, then one slow bolt that dies after `shot.range` tiles.
	chaser: { hp: 55, r: 0.4, speed: 3.4, shot: { range: 3.5, speed: 7, dmg: 9, tele: 14, every: 75 } },
	shooter: { hp: 48, r: 0.38, speed: 2.4 },
	radial: { hp: 95, r: 0.45, speed: 0 },
	boss: { hp: 1150, r: 1.0, speed: 1.2 },
	// The Fracture (design §14.4a)
	shard: { hp: 85, r: 0.42, speed: 1.4 },
	splitter: { hp: 110, r: 0.5, speed: 2.0 },
	splinter: { hp: 30, r: 0.28, speed: 3.6, shot: { range: 3, speed: 7, dmg: 8, tele: 12, every: 70 } },
	flicker: { hp: 75, r: 0.38, speed: 0 },
	// The Ashen Breach (owner's design, 2026-11-19)
	cinder: { hp: 70, r: 0.36, speed: 4.2, shot: { range: 3.5, speed: 7, dmg: 10, tele: 14, every: 80 } },
	kiln: { hp: 120, r: 0.5, speed: 0 },
	smolder: { hp: 90, r: 0.44, speed: 0 },
};
// Each dungeon's boss is a `boss` enemy of its own KIND (dungeon.boss_kind).
export const BOSS_HP = { tidewarden: 1150, breach: 1950, pyre: 2800 };

/* CRACKS (the Fracture, design §14.4a): authored lines of floor that open into void
 * while their room is being fought. Each counts `t` round a `period`: closed, then
 * `warn` ticks of a flickering seam, then `open` ticks as void (walking blocked,
 * shots fly over). One that opens under a body throws it to the nearest solid
 * ground, and hurts the player `dmg`. Groups start `stagger` apart. */
export const CRACK = { period: 480, warn: 60, open: 180, stagger: 160, dmg: 14 };

/* Each weapon fires its own PATTERN, not just its own numbers (owner's ask,
 * 2026-11-18). `rate` is volleys a second; a volley is `shots` arrows fanned
 * `spread` radians apart, or a `burst` of bolts `gap` ticks apart. `pierce` is how
 * many enemies a shot passes through (no base weapon pierces since 2026-11-19; the
 * Kingfisher's Eye adds it). `dmg` is per arrow AT TIER 0, and each tier adds a FIFTH of
 * it, flat, so tier 10 is three times tier 0 (owner's call, 2026-11-19).
 * THE DAMAGE FOLLOWS THE RANGE (owner's call, 2026-11-19): one target, every shot
 * landing, a weapon's tier-1 damage a second is about 55 x sqrt(5 / range), so each
 * tile of reach costs a share in proportion to the range. Twin arrows get +10% (both
 * land only up close) and the kunai -5% (the fastest shot is the easiest to land); each
 * `dmg` is a multiple of 5 and `rate` was nudged to meet the curve. The uniques sit off
 * it on purpose.
 * Two STANDARD types per class plus uniques (owner's call, 2026-11-18); ranges in
 * tiles are the owner's: shortbow 5, repeater 6, longbow 7.
 *   shortbow   — twin arrows, fast, short: strong up close, spreads out at range.
 *   longbow    — one heavy arrow, slow, the longest reach.
 *   tidecaller — UNIQUE: three arrows in a wide fan that glance off a wall once.
 *   repeater   — UNIQUE: a three-bolt burst, then a reload: front-loaded damage.
 * `bounce` is how many walls a shot glances off before it breaks. */
export const WEAPONS = {
	none: { dmg: 6, rate: 3, range: 5, speed: 14, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	shortbow: { dmg: 5, rate: 5, range: 5, speed: 15, shots: 2, spread: 0.12, pierce: 0, burst: 1, gap: 0 },
	longbow: { dmg: 25, rate: 1.5, range: 7, speed: 20, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	mace: { dmg: 25, rate: 2.4, range: 3, speed: 15, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	greatsword: { dmg: 45, rate: 1.1, range: 4, speed: 17, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	wand: { dmg: 15, rate: 2.8, range: 6, speed: 16, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	starstaff: { dmg: 25, rate: 1.4, range: 8, speed: 20, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0 },
	tidecaller: { dmg: 10, rate: 2.5, range: 6, speed: 16, shots: 3, spread: 0.24, pierce: 0, burst: 1, gap: 0, bounce: 1 },
	repeater: { dmg: 10, rate: 1.5, range: 6, speed: 17, shots: 1, spread: 0, pierce: 0, burst: 3, gap: 5 },
	// The Ninja's (2026-11-18): stars spin through one enemy; a kunai is one heavy, fast blade.
	// Slower and harder since 2026-11-18 (owner's ask): at 4.5 a second the doubled
	// countered shot left before the player could aim it.
	shuriken: { dmg: 20, rate: 2.3, range: 5, speed: 15, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, look: "star" },
	kunai: { dmg: 30, rate: 1.3, range: 6.5, speed: 22, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, look: "blade" },
	// UNIQUE weapons (owner's list, 2026-11-19), each a twist on its class's pair:
	//   oathhammer — a mace whose hits SPLASH half damage on whatever stands within a tile;
	//   comet_rod  — a slow bolt that BURSTS into four shards where it hits or where it ends;
	//   chakram    — flies out, turns back half way, and cuts through everything both ways.
	oathhammer: { dmg: 25, rate: 2.2, range: 3, speed: 15, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, splash: 1 },
	comet_rod: { dmg: 25, rate: 1.2, range: 7, speed: 14, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, comet: 1 },
	chakram: { dmg: 10, rate: 2, range: 5, speed: 15, shots: 1, spread: 0, pierce: 99, burst: 1, gap: 0, ret: 1, look: "star" },
	// The Ashen Breach's (2026-11-19):
	//   flare_bow   — every `flare`th shot is a flare, and leaves the ground burning where it lands;
	//   ember_kunai — a kunai that STICKS, and bursts a second later for more (UNIQUE.kunai).
	flare_bow: { dmg: 20, rate: 2.2, range: 6, speed: 16, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, flare: 4 },
	ember_kunai: { dmg: 25, rate: 1.3, range: 6.5, speed: 22, shots: 1, spread: 0, pierce: 0, burst: 1, gap: 0, look: "blade", stick: 1 },
};

/* EVERY NUMBER A PLAYER READS IS FLAT (owner's ask, 2026-11-18: "stop with all the
 * percentages"). A character has Attack and Dexterity as plain points; each point
 * is worth 1/STAT_SCALE more damage (Attack) or shots a second (Dexterity), so a
 * weapon's damage is still its own and the points scale every weapon alike. The
 * points themselves and damage are whole numbers; HP/MP regeneration may use one
 * decimal place for finer tuning. */
export const STAT_SCALE = 25;

/* An enchantment's flat value at roll quality q (0-1): [at q=0, at q=1], rounded.
 * The store keeps the QUALITY, so changing a row here re-scales every item. */
/* MP regen tops out at +1.5 (was 2.5, 2026-11-19): a character starts at 2.5 MP a second,
 * so four +2.5 lines more than quadrupled casting. FLAT on purpose: a line is a big
 * share of a level-1 character and a solid one of a level-20 (owner's call). */
export const ENCHANT_FLAT = {
	max_hp: [5, 25], max_mp: [5, 25], attack: [1, 6], attack_speed: [1, 6], defense: [1, 5],
	ability_power: [2, 10], mp_regen: [0.3, 1.5], hp_regen: [0.2, 1.2],
	// the SPECIAL lines (content.ENCHANTS `special`): the main number; SPECIAL below has the rest
	fury: [5, 9], glass_mind: [8, 14], fleetfoot: [4, 7],
	kindling: [2, 4], second_wind: [3, 6], bulwark: [3, 6],
};
/* What a special line costs or how it fires (fixed, whatever its roll). */
export const SPECIAL = {
	fury: { def: 3 },                       // +Attack, -3 Defense
	glass_mind: { hp: 20 },                 // +Ability power, -20 HP
	fleetfoot: { hp: 15 },                  // +Dexterity, -15 HP
	kindling: { shots: 3 },                 // a cast sets the next 3 volleys burning (burn per pulse)
	second_wind: { cooldown: TPS },         // MP back on a kill, at most once a second
	bulwark: { last: 2 * TPS, cooldown: 4 * TPS },   // +Defense for 2 s after a hit, every 4 s at most
};
export const isSpecial = (id) => id in SPECIAL;
/* A line's level, I-IV: the quarter of its quality (content.line_level). */
export const lineLevel = (q) => Math.min(4, Math.floor((q || 0) * 4) + 1);
export const enchantValue = (id, q) => {
	const r = ENCHANT_FLAT[id];
	if (!r) return 0;
	const precision = id === "mp_regen" || id === "hp_regen" ? 10 : 1;
	return Math.round((r[0] + (r[1] - r[0]) * q) * precision) / precision;
};

/* What each level past the first adds (design §10.1: levels are separate from
 * the per-dungeon stat rewards and their caps). Greybox numbers. */
export const PER_LEVEL = { maxHp: 6, maxMp: 4, att: 1, ap: 1 };

/* Tier 0 is starter gear (owner's call, 2026-11-19): a fifth weaker than tier 1, so
 * the first drops are upgrades. It never takes away max HP (`up` below). */
const tierScale = (it) => 1 + 0.2 * ((it.tier ?? 1) - 1);
/* What a tier does to an ability's NON-damage reach (the field's radius, the counter's
 * multiplier, the shield's time): 12% a tier, not 20%, so tier 10 (2026-11-19) is a
 * field of ~6 tiles, not ~8. */
const effectScale = (it) => 1 + 0.12 * ((it.tier ?? 1) - 1);

/* A character's numbers from its level and what it wears. `gear` is the equipped
 * items as the server lists them ({base_id, tier, enchants: [{id, q}]}). */
export function statsFor(gear = [], level = 1, classId = "ranger") {
	// HP regeneration halved 2026-11-18 (owner: "decrease hp/s regen"); heals are rarer drops now.
	const s = { maxHp: 100, maxMp: 100, att: 0, dex: 0, def: 0, ap: 0, hpRegen: 0.5, mpRegen: 2.5,
		arrows: 0, abilityDmg: 0, abilityKind: null, classId,
		...weaponStats(WEAPONS.none, 0) };
	// Points gather first and apply once the weapon is known, so the order the
	// server lists gear in can never change the numbers.
	let pierce = 0;
	for (const it of gear) {
		const t = tierScale(it), tier = it.tier ?? 1, up = Math.max(0, tier - 1);
		const w = WEAPONS[it.base_id];
		if (w) Object.assign(s, weaponStats(w, tier));
		// ARMOR (owner's numbers, 2026-11-19): every armor gives Defense and HP, and the
		// two of a type lean only a little apart. Light: the vest (HP, a little MP) and
		// the robes (MP and regen); heavy: plate (Defense, HP) and the garb (Dexterity).
		if (it.base_id === "leather_vest") { s.def += 1 + tier; s.maxHp += 10 * up; s.maxMp += 5 * tier; }
		const T = tier;                                       // an ability item's tier, 0-10
		if (it.base_id === "volley_quiver") { s.arrows = 7; s.abilityDmg += (ABILITY.volley.dmg + ABILITY.volley.perTier * T) / 7; s.abilityKind = "volley"; s.abilityItemTier = T; }
		if (it.base_id === "plate_armor") { s.def += 2 + tier; s.maxHp += 15 * up; }
		if (it.base_id === "grounding_aegis") { s.abilityKind = "shield"; s.abilityTier = effectScale(it); }
		if (it.base_id === "seer_robes") { s.def += tier; s.maxHp += 5 * up; s.maxMp += 12 * tier; s.mpRegen += 0.5; }
		if (it.base_id === "stillness_orb") { s.abilityKind = "slow"; s.abilityDmg += ABILITY.slow.pulse * (1 + ABILITY.slow.pulsePerTier * T);
			s.abilityTier = 1 + ABILITY.slow.radiusPerTier * T; s.abilityItemTier = T; }
		if (it.base_id === "star_tome") { s.abilityKind = "starfall"; s.abilityDmg += ABILITY.starfall.dmg + ABILITY.starfall.perTier * T; s.abilityItemTier = T; }
		if (it.base_id === "shadow_garb") { s.def += 1 + tier; s.dex += 1 + Math.floor(tier / 2); s.maxHp += 10 * up; }
		if (it.base_id === "mirror_charm") { s.abilityKind = "counter"; s.abilityItemTier = T; }
		if (it.base_id === "band_of_vigor") s.maxHp += Math.round(15 * t);
		if (it.base_id === "band_of_focus") { s.maxMp += Math.round(15 * t); s.mpRegen += 2; }
		if (it.base_id === "kingfisher_eye") { pierce += 1; s.att += Math.round(5 * t); }   // tiered since 2026-11-19
		// the unique roster (UNIQUE above)
		if (it.base_id === "ember_loop") s.burn = Math.max(1, Math.round(UNIQUE.burn.dmg * t));
		if (it.base_id === "misers_coil") { s.costCut = Math.round(UNIQUE.coilCut * t); s.maxHp -= UNIQUE.coilHp; }
		if (it.base_id === "leechstone") s.leech = Math.round(UNIQUE.leech * t);
		if (it.base_id === "glass_ring") { s.att += Math.round(UNIQUE.glass.att * t); s.def -= Math.round(UNIQUE.glass.def * t); }
		if (it.base_id === "windrunner_cloak") { s.def += tier; s.maxHp += 5 * up; s.moveMult = UNIQUE.windrunner; }
		if (it.base_id === "full_moon_mantle") { s.def += tier; s.maxMp += 10 * tier; s.fullMoon = UNIQUE.fullMoon; }
		if (it.base_id === "thornplate") { s.def += 1 + tier; s.maxHp += 15 * up; s.thorns = Math.round(UNIQUE.thorns.dmg * t); }
		if (it.base_id === "duskmail") { s.def += 1 + tier; s.maxHp += 10 * up; s.dusk = UNIQUE.dusk; }
		if (it.base_id === "gale_quiver") { s.arrows = 1; s.gale = true; s.abilityDmg += ABILITY.volley.dmg + ABILITY.volley.perTier * T; s.abilityKind = "volley"; s.abilityItemTier = T; }
		if (it.base_id === "anchor_orb") { s.abilityKind = "slow"; s.anchored = true; s.abilityDmg += ABILITY.slow.pulse * (1 + ABILITY.slow.pulsePerTier * T) * UNIQUE.anchor;
			s.abilityTier = (1 + ABILITY.slow.radiusPerTier * T) * UNIQUE.anchor; s.abilityItemTier = T; }
		if (it.base_id === "echo_codex") { s.abilityKind = "starfall"; s.abilityDmg += ABILITY.starfall.dmg + ABILITY.starfall.perTier * T; s.abilityItemTier = T;
			s.echo = UNIQUE.echo.share; s.costExtra = UNIQUE.echo.cost; }
		if (it.base_id === "echo_charm") { s.abilityKind = "counter"; s.abilityItemTier = T; s.echoRing = true; }
		// the Ashen Breach's
		if (it.base_id === "phoenix_feather") s.phoenix = Math.round(UNIQUE.phoenix.dmg * t);
		if (it.base_id === "ash_sigil") s.ashSigil = Math.round(UNIQUE.ash.dmg * t);
		if (it.base_id === "banked_coal") s.coalCap = Math.round(UNIQUE.coal.cap * t);
		if (it.base_id === "emberweave") { s.def += tier; s.maxHp += 5 * up; s.trail = Math.round(UNIQUE.emberweave.dmg * t); }
		if (it.base_id === "cinderguard") { s.def += 1 + tier; s.maxHp += 15 * up; s.fireproof = true; s.cinderDef = Math.round(UNIQUE.cinderguard.def * t); }
		if (it.base_id === "censer") { s.abilityKind = "slow"; s.censer = true; s.abilityDmg += ABILITY.slow.pulse * (1 + ABILITY.slow.pulsePerTier * T) * UNIQUE.censer.burn;
			s.abilityTier = 1 + ABILITY.slow.radiusPerTier * T; s.abilityItemTier = T; }
		if (it.base_id === "meteor_tome") { s.abilityKind = "starfall"; s.abilityDmg += ABILITY.starfall.dmg + ABILITY.starfall.perTier * T; s.abilityItemTier = T; s.crater = true; }
		for (const e of it.enchants || []) {
			const v = enchantValue(e.id, e.q);
			if (e.id === "max_hp") s.maxHp += v;
			else if (e.id === "max_mp") s.maxMp += v;
			else if (e.id === "attack") s.att += v;
			else if (e.id === "attack_speed") s.dex += v;
			else if (e.id === "defense") s.def += v;
			else if (e.id === "ability_power") s.ap += v;
			else if (e.id === "mp_regen") s.mpRegen += v;
			else if (e.id === "hp_regen") s.hpRegen += v;
			else if (e.id === "fury") { s.att += v; s.def -= SPECIAL.fury.def; }
			else if (e.id === "glass_mind") { s.ap += v; s.maxHp -= SPECIAL.glass_mind.hp; }
			else if (e.id === "fleetfoot") { s.dex += v; s.maxHp -= SPECIAL.fleetfoot.hp; }
			else if (e.id === "kindling") s.kindle = Math.max(s.kindle || 0, v);
			else if (e.id === "second_wind") s.secondWind = Math.max(s.secondWind || 0, v);
			else if (e.id === "bulwark") s.bulwark = Math.max(s.bulwark || 0, v);
		}
	}
	const up = Math.max(0, (level | 0) - 1);
	s.maxHp += PER_LEVEL.maxHp * up;
	s.maxMp += PER_LEVEL.maxMp * up;
	s.att += PER_LEVEL.att * up;
	s.ap += PER_LEVEL.ap * up;
	s.pierce += pierce;
	s.weaponDmg = s.dmg;                                   // per arrow, before Attack
	s.dmg = Math.round(s.dmg * (1 + s.att / STAT_SCALE));
	s.rate = s.rate * (1 + s.dex / STAT_SCALE);
	// ABILITY POWER (owner's ask, 2026-11-18) is the ability's own stat, as Attack is
	// the weapon's: each point is 1/STAT_SCALE more of what the ability does — the
	// volley's and the starfall's damage, the slowing field's REACH (not its time),
	// the counter's damage (not its guard).
	s.abilityPower = 1 + s.ap / STAT_SCALE;
	// Not rounded: a volley's 55 is shared by its 7 arrows (each hit's number is shown to
	// a tenth), and the tooltip reads the whole volley.
	s.abilityDmg = s.abilityKind === "volley" || s.abilityKind === "starfall" || s.abilityKind === "slow" ? s.abilityDmg * s.abilityPower : 0;
	// EVERY ABILITY GROWS WITH ITS TIER (owner's ask, 2026-11-19: "a t5 ability should
	// have higher base effectiveness than a t2"): `abilityTier` is the tier's scale, the
	// same 20% a tier as weapons and armor. The damage abilities take it in abilityDmg;
	// the field's reach, the counter's multiplier and the shield's time take it here.
	const at = s.abilityTier || 1;
	s.slowRadius = Math.round(ABILITY.slow.radius * at * s.abilityPower * 100) / 100;
	s.counterMult = Math.round((ABILITY.counter.mult + ABILITY.counter.perTier * (s.abilityItemTier ?? 0)) * s.abilityPower * 100) / 100;
	s.shieldTime = Math.round(SHIELD_DURATION * at * s.abilityPower);
	s.abilityCost = Math.max(5, abilityCost(s.abilityKind, s.abilityItemTier ?? 0) + (s.costExtra || 0) - (s.costCut || 0));
	return s;
}

/* A weapon at a tier: its tier-0 damage plus a fifth of it a tier (T10 = 3 x T0). */
export const weaponDmgAt = (w, tier = 0) => Math.round(w.dmg * (1 + 0.2 * Math.max(0, tier)));
function weaponStats(w, tier) {
	return { dmg: weaponDmgAt(w, tier), rate: w.rate, range: w.range, shotSpeed: w.speed, shots: w.shots,
		spread: w.spread, pierce: w.pierce, burst: w.burst, gap: w.gap, bounce: w.bounce || 0, look: w.look || null,
		splash: w.splash || 0, comet: w.comet || 0, ret: w.ret || 0, flare: w.flare || 0, stick: w.stick || 0 };
}

// ── the map ─────────────────────────────────────────────────────────────────
/* A doorway of a room that still has enemies in it reads as "=" while the room is
 * sealed (nothing passes) and "|" before it is entered (a veil: shots stop, feet
 * do not). Once the room is cleared it is plain floor again. */
function tileAt(st, x, y) {
	const ty = Math.floor(y), tx = Math.floor(x);
	if (ty < 0 || ty >= st.h || tx < 0 || tx >= st.w) return "#";
	if (st.doorCols && ty >= st.doorY - 1 && ty <= st.doorY + 1) {
		const r = st.doorCols[tx];
		if (r >= 0 && st.roomLeft[r] > 0) return st.sealed === r ? "=" : "|";
	}
	if (st.cracks?.length) {
		const k = st.crackAt[ty * st.w + tx];
		if (k !== undefined && st.cracks[k].open) return "x";
	}
	return st.tiles[ty][tx];
}
export const doorAt = (st, x, y) => tileAt(st, x, y);
const walkSolid = (c) => c === "#" || c === "o" || c === "~" || c === "=" || c === "x";
const shotSolid = (c) => c === "#" || c === "o" || c === "=" || c === "|";

function blocked(st, x, y, r) {
	for (let ty = Math.floor(y - r); ty <= Math.floor(y + r); ty++)
		for (let tx = Math.floor(x - r); tx <= Math.floor(x + r); tx++)
			if (walkSolid(tileAt(st, tx, ty))) return true;
	return false;
}

/* Move a circle (as its bounding square) axis by axis, so it slides along walls. */
function moveBody(st, b, dx, dy) {
	if (dx !== 0 && !blocked(st, b.x + dx, b.y, b.r)) b.x += dx;
	if (dy !== 0 && !blocked(st, b.x, b.y + dy, b.r)) b.y += dy;
}

/* The level `xp` reaches on the server's table (`levels[n]` = the XP to BE
 * level n + 1 — the state route ships it, so the two sides read one table). */
export function levelFor(levels, xp) {
	let level = 1;
	while (level < levels.length && xp >= levels[level]) level++;
	return level;
}

/* Where `xp` sits inside its level: { level, into, span } (span 0 at the top). */
export function xpProgress(levels, xp) {
	const level = levelFor(levels, xp);
	if (level >= levels.length) return { level, into: 0, span: 0 };
	return { level, into: xp - levels[level - 1], span: levels[level] - levels[level - 1] };
}

// ── state ───────────────────────────────────────────────────────────────────
/* `hero` is the character as the server lists it: { level, xp }, plus the
 * server's level table. The XP a run earns is shown and levelled on here, but it
 * is CREDITED by the server from its own dungeon (each enemy's `xp`). */
export function createSim(dungeon, gear = [], hero = {}) {
	const levels = hero.levels || [0];
	const xp = hero.xp || 0, level = Math.max(hero.level || 1, levelFor(levels, xp));
	const classId = hero.class_id || hero.classId || dungeon.class_id || "ranger";
	const stats = statsFor(gear, level, classId);
	const low = Math.min(stats.maxHp, hero.low ?? stats.maxHp);
	const scale = { hp: 1, dmg: 1, speed: 1, shot: 1, cadence: 1, ward: 0, ward_boss: 0, volatile: 0, ...(dungeon.scale || {}) };
	const bossKind = dungeon.boss_kind || "tidewarden";
	const hpOf = (e) => (e.type === "boss" ? BOSS_HP[bossKind] || ENEMY.boss.hp : ENEMY[e.type].hp);
	const enemies = Object.entries(dungeon.enemies)
		.sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))      // a fixed order, never insertion order
		.map(([id, e]) => ({ id, type: e.type, room: e.room, x: e.x, y: e.y, xp: e.xp || 0,
			r: ENEMY[e.type].r, hp: Math.round(hpOf(e) * scale.hp), maxHp: Math.round(hpOf(e) * scale.hp),
			parent: e.parent || null, summon: e.summon || null, dormant: !!(e.parent || e.summon),
			form: e.type === "boss" ? bossKind : null, homeX: e.x, homeY: e.y, lit: false, charge: 0, scorched: 0,
			active: false, cd: 30 + (e.type === "boss" ? 60 : 0), tele: 0, scd: 0, flash: 0,
			ward: e.type === "boss" ? scale.ward_boss : scale.ward,
			side: 1, phase: 1, mode: 0, modeT: e.type === "boss" ? ({ breach: BREACH_CYCLE, pyre: PYRE_CYCLE }[bossKind] || BOSS_CYCLE)[0][1] : 0,
			ang: 0, aimX: 0, aimY: 0, toX: 0, toY: 0 }));
	// The doors: each room's left and right doorway columns, on the three rows
	// around the map's middle row (dungeon.py cuts them there).
	const rooms = dungeon.rooms || [];
	const doorY = dungeon.door_y ?? Math.floor(dungeon.height / 2);
	const doorCols = new Array(dungeon.width).fill(-1);
	rooms.forEach((r, i) => { if (i > 0) doorCols[r.x0 - 1] = i; if (i < rooms.length - 1) doorCols[r.x1] = i; });
	const roomLeft = rooms.map((_, i) => enemies.filter((e) => e.room === i).length);
	// Each room's top and bottom rows, used to place the Pyre's barrages.
	const roomY = rooms.map((r) => {
		let y0 = -1, y1 = -1;
		for (let y = 0; y < dungeon.height; y++)
			if (dungeon.tiles[y].slice(r.x0, r.x1).replace(/#/g, "").length) { if (y0 < 0) y0 = y; y1 = y; }
		return [y0, y1];
	});
	const cracks = (dungeon.cracks || []).map((c) => ({ room: c.room, group: c.group, tiles: c.tiles,
		t: c.group * CRACK.stagger, open: false, warn: false }));
	const crackAt = {};
	cracks.forEach((c, i) => { for (const [x, y] of c.tiles) crackAt[y * dungeon.width + x] = i; });
	const dropsBy = {};
	for (const [id, d] of Object.entries(dungeon.drops)) (dropsBy[d.enemy] ||= []).push(id);
	for (const k of Object.keys(dropsBy)) dropsBy[k].sort();
	return {
		tick: 0, elapsedTicks: 0, bossTimeTicks: null, rng: hashSeed(String(dungeon.seed)), status: "play",
		classId, practice: !!hero.practice,
		w: dungeon.width, h: dungeon.height, tiles: dungeon.tiles, rooms, dungeonId: dungeon.id || "shallows",
		cracks, crackAt, fastRoom: -1, roomY,
		doorY, doorCols, roomLeft, sealed: -1, depth: dungeon.level || 1, offers: dungeon.offers || [],
		stats, gear, levels, completeXp: dungeon.complete_xp || 0,
		hero: { level, xp, startLevel: level, startXp: xp },
		p: { x: dungeon.start.x, y: dungeon.start.y, r: PLAYER_R, hp: Math.min(stats.maxHp, low + RECOVERY_MARGIN), low,
			mp: stats.maxMp, fireCd: 0, hurt: 0, burstLeft: 0, burstCd: 0,
			potionCd: 0, counterUntil: 0, guardUntil: 0, empower: 0, abilityCd: 0, primed: 0,
			kindled: 0, windAt: 0, bulwarkUntil: 0, bulwarkAt: 0, hitAt: 0, volleys: 0, phoenixUsed: false, inFire: false },
		enemies, bullets: [], dropsBy, scale,
		// Heal orbs DROP from the enemy that carries one (dungeon.py); one with a
		// position of its own (an older dungeon) lies where it was placed.
		pickups: dungeon.pickups.filter((h) => h.enemy == null).map((h) => ({ ...h })),
		healsBy: Object.fromEntries(dungeon.pickups.filter((h) => h.enemy != null).map((h) => [h.enemy, h.id])),
		bags: [], floor: [], portal: null, deeper: null, shield: null, slowUntil: 0, starfalls: [], blasts: [], mortars: [], fires: [], damageNumbers: [], events: [],
		embers: [], stuck: [],
	};
}

export const recoveryLimit = (st) => Math.min(st.stats.maxHp, st.p.low + RECOVERY_MARGIN);

/* `src` names what hit ("shooter:bolt", "boss:nova", "chaser:touch"…): the last hit
 * that landed is kept in `st.lastHit`, so a death can say what did it. */
function hurtPlayer(st, dmg, src = null) {
	if (st.status !== "play") return;
	dmg *= st.scale ? st.scale.dmg : 1;                     // the Brutal modifier
	const p = st.p;
	if (p.guardUntil > st.tick) return;                      // just countered: nothing lands
	if (p.counterUntil >= st.tick) {                         // the counter catches this hit
		p.counterUntil = 0;
		p.guardUntil = st.tick + COUNTER_GUARD;
		p.empower = st.stats.counterMult;                    // the next shot; a second counter does not stack
		st.events.push({ type: "counter", local: true });
		if (st.stats.echoRing) {                             // the Echo Charm: blades out from where you stand
			const q = UNIQUE.echoRing;
			for (let k = 0; k < q.n; k++) playerShot(st, p.x, p.y, k * TAU / q.n, q.speed, st.stats.dmg, q.life, { look: "blade" });
		}
		return;
	}
	const def = st.stats.def + (p.bulwarkUntil > st.tick ? st.stats.bulwark : 0)
		+ (p.inFire && st.stats.cinderDef ? st.stats.cinderDef : 0);           // Cinderguard, standing in fire
	const taken = Math.round(Math.max(dmg * 0.4, dmg - def) * 10) / 10;
	if (st.stats.bulwark && !(p.bulwarkAt > st.tick)) {      // Bulwark: Defense up for the hits after this one
		p.bulwarkUntil = st.tick + SPECIAL.bulwark.last;
		p.bulwarkAt = st.tick + SPECIAL.bulwark.cooldown;
	}
	p.hp -= taken;
	p.hurt = 8;
	p.hitAt = st.tick;                                       // Banked Coal starts over
	st.lastHit = { src, dmg: taken, tick: st.tick };
	if (!st.damageNumbers) st.damageNumbers = [];
	st.damageNumbers.push({ x: p.x, y: p.y, amount: taken, until: st.tick + 45 });
	st.events.push({ type: "damage", amount: taken, local: true });
	if (p.hp < p.low) p.low = Math.max(0, p.hp);
	if (st.stats.thorns && p.hp > 0) {                       // Thornplate: shards out from the hit
		const q = UNIQUE.thorns;
		for (let k = 0; k < q.n; k++) playerShot(st, p.x, p.y, k * TAU / q.n + PI / 4, q.speed, st.stats.thorns, q.life);
	}
	if (p.hp <= 0 && st.stats.phoenix && !p.phoenixUsed) {    // the Phoenix Feather: once a level
		const q = UNIQUE.phoenix;
		p.phoenixUsed = true; p.hp = 1; p.low = 1;
		p.guardUntil = st.tick + q.guard;
		(st.embers ||= []).push({ x: p.x, y: p.y, r: q.r, until: st.tick + q.last, dmg: st.stats.phoenix });
		for (const e of st.enemies) {
			if (e.hp <= 0 || !e.active) continue;
			const dx = e.x - p.x, dy = e.y - p.y, rr = q.r + e.r;
			if (dx * dx + dy * dy < rr * rr) { e.burnUntil = st.tick + UNIQUE.burn.last; e.burnDmg = st.stats.phoenix; }
		}
		(st.blasts ||= []).push({ x: p.x, y: p.y, r: q.r, until: st.tick + 18, hot: true });
		st.events.push({ type: "phoenix", local: true });
		return;
	}
	if (p.hp <= 0) {
		p.hp = 0;
		st.status = "dead";
		st.events.push({ type: "death" });
	}
}

/* One of the player's shots that is not the weapon's (thorns, blades, shards). */
function playerShot(st, x, y, ang, speed, dmg, life, extra = {}) {
	st.bullets.push({ owner: "p", x, y, vx: dcos(ang) * speed, vy: dsin(ang) * speed, dmg, r: 0.12, life,
		pierce: 0, bounce: 0, hit: [], ...extra });
}

/* The Comet Rod's bolt bursting into shards (a shard never bursts again). Shared with
 * the town. `skip` is what it just hit, which its shards fly past. */
export function cometBurst(st, b, x, y, skip = null) {
	const q = UNIQUE.comet, dmg = Math.max(1, Math.round(b.dmg * q.share));
	for (let k = 0; k < q.n; k++) {
		const a = k * TAU / q.n + PI / 4;
		st.bullets.push({ owner: "p", x, y, vx: dcos(a) * q.speed, vy: dsin(a) * q.speed, dmg, r: 0.11, life: q.life,
			pierce: 0, bounce: 0, hit: skip ? [skip] : [], shard: 1 });
	}
}

/* A chakram turns back half way, and may cut the same enemies again. Shared with the town. */
export function turnBack(b) {
	if (b.ret && b.life === b.ret) { b.vx = -b.vx; b.vy = -b.vy; b.hit = []; b.ret = 0; }
}

/* An enemy's attack cooldown, shortened by Frenzied. */
const cadence = (st, ticks) => Math.max(1, Math.round(ticks * st.scale.cadence));

function shoot(st, owner, x, y, ang, speed, dmg, r, life, pierce = 0) {
	if (owner === "e") { speed *= st.scale.speed; life = Math.round(life / st.scale.speed); r *= st.scale.shot; }
	st.bullets.push({ owner, x, y, vx: dcos(ang) * speed, vy: dsin(ang) * speed, dmg, r, life, pierce, hit: [],
		...(owner === "e" ? { src: st.src } : {}) });
}

function shootAt(st, owner, x, y, tx, ty, speed, dmg, r, life) {
	if (owner === "e") { speed *= st.scale.speed; life = Math.round(life / st.scale.speed); r *= st.scale.shot; }
	const dx = tx - x, dy = ty - y, d = Math.sqrt(dx * dx + dy * dy) || 1;
	st.bullets.push({ owner, x, y, vx: dx / d * speed, vy: dy / d * speed, dmg, r, life, pierce: 0, hit: [],
		...(owner === "e" ? { src: st.src } : {}) });
}

// No atan2 (not deterministic): a pattern that needs an aimed FAN rotates the
// unit aim vector instead of computing its angle.
function rotate(vx, vy, a) {
	const c = dcos(a), s = dsin(a);
	return [vx * c - vy * s, vx * s + vy * c];
}

// ── cracks ──────────────────────────────────────────────────────────────────
/* The nearest place a body fits, searching outward in a fixed order. */
const DIRS = [[1, 0], [0, 1], [-1, 0], [0, -1], [0.7071, 0.7071], [-0.7071, 0.7071], [-0.7071, -0.7071], [0.7071, -0.7071]];
function nearestClear(st, b) {
	for (let d = 0.5; d <= 6; d += 0.5)
		for (const [dx, dy] of DIRS) if (!blocked(st, b.x + dx * d, b.y + dy * d, b.r)) return { x: b.x + dx * d, y: b.y + dy * d };
	return null;
}

function stepCracks(st) {
	if (!st.cracks?.length) return;
	let opened = false;
	for (const c of st.cracks) {
		if (st.sealed !== c.room) {                    // only while its room is fought
			c.open = c.warn = false;
			c.t = c.group * CRACK.stagger;
			continue;
		}
		c.t = (c.t + (st.fastRoom === c.room ? 2 : 1)) % CRACK.period;
		const was = c.open;
		c.open = c.t >= CRACK.period - CRACK.open;
		c.warn = !c.open && c.t >= CRACK.period - CRACK.open - CRACK.warn;
		if (c.open && !was) opened = true;
	}
	if (!opened) return;
	const p = st.p;
	if (blocked(st, p.x, p.y, p.r)) {
		const to = nearestClear(st, p);
		if (to) { p.x = to.x; p.y = to.y; }
		hurtPlayer(st, CRACK.dmg, "rift:crack");
	}
	for (const e of st.enemies) {
		if (e.hp <= 0 || e.dormant || !blocked(st, e.x, e.y, e.r)) continue;
		const to = nearestClear(st, e);
		if (to) { e.x = to.x; e.y = to.y; }
	}
}

function nearCrack(st, x, y, r) {
	for (const [cx, cy] of [[x - r, y - r], [x + r, y - r], [x - r, y + r], [x + r, y + r]])
		if (st.crackAt[Math.floor(cy) * st.w + Math.floor(cx)] !== undefined) return true;
	return false;
}

/* A place in the enemy's room it can blink to: clear, off every crack (one may open
 * before it lands), and `lo`..`hi` tiles from the player. Up to a dozen tries, then
 * nowhere (it stays). */
function blinkSpot(st, e, lo, hi) {
	const r = st.rooms[e.room];
	if (!r) return null;
	for (let k = 0; k < 12; k++) {
		const x = r.x0 + 1 + rand(st) * (r.x1 - r.x0 - 2), y = 1.5 + rand(st) * (st.h - 3);
		const d = Math.sqrt((x - st.p.x) ** 2 + (y - st.p.y) ** 2);   // never Math.hypot: not exact everywhere
		if (d >= lo && d <= hi && !blocked(st, x, y, e.r + 0.1) && !nearCrack(st, x, y, e.r + 0.1)) return { x, y };
	}
	return null;
}

// ── enemies ─────────────────────────────────────────────────────────────────
function enemyStep(st, e) {
	const p = st.p;
	if (e.flash > 0) e.flash--;
	const dx = p.x - e.x, dy = p.y - e.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
	const ux = dx / d, uy = dy / d;
	const sp = ENEMY[e.type].speed * st.scale.speed * DT;
	if (e.cd > 0) e.cd--;

	if (e.type === "chaser") {
		moveBody(st, e, ux * sp, uy * sp);
		const sh = ENEMY.chaser.shot;
		if (e.scd > 0) e.scd--;
		if (e.tele > 0) {
			if (--e.tele === 0) {
				st.src = "chaser:spit";
				shootAt(st, "e", e.x, e.y, p.x, p.y, sh.speed, sh.dmg, 0.16, Math.round((sh.range / sh.speed) * TPS));
				e.scd = cadence(st, sh.every);
			}
		} else if (!(e.scd > 0) && d < sh.range) e.tele = sh.tele;
		return;
	}
	if (e.type === "shooter") {
		if (st.tick % 90 === 0 && rand(st) < 0.5) e.side = -e.side;
		if (d < 4) moveBody(st, e, -ux * sp, -uy * sp);
		else if (d > 6.5) moveBody(st, e, ux * sp, uy * sp);
		else moveBody(st, e, -uy * sp * e.side, ux * sp * e.side);
		if (e.tele > 0) {
			if (--e.tele === 0) { st.src = "shooter:bolt"; shootAt(st, "e", e.x, e.y, p.x, p.y, 7.5, 14, 0.18, 150); e.cd = cadence(st, 84); }
		} else if (e.cd === 0 && d < 11) e.tele = 21;
		return;
	}
	if (e.type === "shard") {                          // drifts at mid range; a turning four-way cross
		if (d < 4.5) moveBody(st, e, -ux * sp, -uy * sp);
		else if (d > 7) moveBody(st, e, ux * sp, uy * sp);
		if (e.tele > 0) {
			if (--e.tele === 0) {
				st.src = "shard:cross";
				for (let k = 0; k < 4; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / 4, 5.5, 15, 0.2, 200);
				e.ang = e.ang === 0 ? TAU / 8 : 0;
				e.cd = cadence(st, 96);
			}
		} else if (e.cd === 0 && d < 11) e.tele = 24;
		return;
	}
	if (e.type === "splitter") {                       // keeps its distance; an aimed pair
		if (st.tick % 100 === 0 && rand(st) < 0.5) e.side = -e.side;
		if (d < 4) moveBody(st, e, -ux * sp, -uy * sp);
		else if (d > 7) moveBody(st, e, ux * sp, uy * sp);
		else moveBody(st, e, -uy * sp * e.side, ux * sp * e.side);
		if (e.tele > 0) {
			if (--e.tele === 0) {
				st.src = "splitter:pair";
				for (const a of [-0.14, 0.14]) {
					const [vx, vy] = rotate(ux, uy, a);
					shootAt(st, "e", e.x, e.y, e.x + vx, e.y + vy, 7.5, 13, 0.19, 150);
				}
				e.cd = cadence(st, 100);
			}
		} else if (e.cd === 0 && d < 11) e.tele = 18;
		return;
	}
	if (e.type === "splinter") {                       // small and fast; a short spit
		moveBody(st, e, ux * sp, uy * sp);
		const sh = ENEMY.splinter.shot;
		if (e.scd > 0) e.scd--;
		if (e.tele > 0) {
			if (--e.tele === 0) {
				st.src = "splinter:spit";
				shootAt(st, "e", e.x, e.y, p.x, p.y, sh.speed, sh.dmg, 0.15, Math.round((sh.range / sh.speed) * TPS));
				e.scd = cadence(st, sh.every);
			}
		} else if (!(e.scd > 0) && d < sh.range) e.tele = sh.tele;
		return;
	}
	if (e.type === "flicker") {                        // blinks (marked first), then a ring
		if (e.tele > 0) {
			if (--e.tele === 0) {
				if (e.toX || e.toY) {                    // a crack may have opened there meanwhile
					const to = blocked(st, e.toX, e.toY, e.r) ? nearestClear(st, { x: e.toX, y: e.toY, r: e.r }) : { x: e.toX, y: e.toY };
					if (to) { e.x = to.x; e.y = to.y; }
				}
				e.toX = e.toY = 0;
				st.src = "flicker:ring";
				e.ang = e.ang === 0 ? TAU / 16 : 0;
				for (let k = 0; k < 8; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / 8, 4.8, 15, 0.2, 200);
				e.cd = cadence(st, 150);
			}
		} else if (e.cd === 0) {
			const to = blinkSpot(st, e, 3, 7);
			e.toX = to ? to.x : 0; e.toY = to ? to.y : 0;
			e.tele = 36;
		}
		return;
	}
	if (e.type === "cinder") {                         // a fast chaser that leaves fire where it runs
		moveBody(st, e, ux * sp, uy * sp);
		if (st.tick % CINDER.every === 0) (st.fires ||= []).push({ x: e.x, y: e.y, r: CINDER.r, until: st.tick + CINDER.last, src: "cinder:fire" });
		const sh = ENEMY.cinder.shot;
		if (e.scd > 0) e.scd--;
		if (e.tele > 0) {
			if (--e.tele === 0) {
				st.src = "cinder:spit";
				shootAt(st, "e", e.x, e.y, p.x, p.y, sh.speed, sh.dmg, 0.16, Math.round((sh.range / sh.speed) * TPS));
				e.scd = cadence(st, sh.every);
			}
		} else if (!(e.scd > 0) && d < sh.range) e.tele = sh.tele;
		return;
	}
	if (e.type === "kiln") {                           // stands still and lobs firebombs where you are
		if (e.tele > 0) {
			if (--e.tele === 0) {
				(st.mortars ||= []).push({ x: p.x, y: p.y, r: KILN.r, at: st.tick + KILN.delay, d: KILN.delay,
					dmg: KILN.dmg, burn: KILN.burn, src: "kiln:bomb", fire: "kiln:fire" });
				e.cd = cadence(st, KILN.every);
			}
		} else if (e.cd === 0 && d < KILN.range) e.tele = KILN.tele;
		return;
	}
	if (e.type === "smolder") {                        // harmless until hit; then it flares, charges and bursts
		if (!e.lit) return;
		if (e.tele > 0) { e.tele--; return; }
		const q = SMOLDER;
		if (e.charge > 0) {
			e.charge--;
			const s2 = q.speed * st.scale.speed * DT;
			moveBody(st, e, ux * s2, uy * s2);
			if (d > q.reach && e.charge > 0) return;
		}
		(st.mortars ||= []).push({ x: e.x, y: e.y, r: q.r, at: st.tick + q.fuse, d: q.fuse,
			dmg: q.dmg, burn: q.burn, src: "smolder:burst", fire: "smolder:fire" });
		kill(st, e);
		return;
	}
	if (e.type === "radial") {
		if (e.tele > 0) {
			if (--e.tele === 0) {
				e.ang = e.ang === 0 ? TAU / 20 : 0;
				st.src = "radial:ring";
				for (let k = 0; k < 10; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / 10, 4.5, 16, 0.2, 200);
				e.cd = cadence(st, 144);
			}
		} else if (e.cd === 0) e.tele = 30;
		return;
	}
	if (e.form === "breach") breachStep(st, e, ux, uy);
	else if (e.form === "pyre") pyreStep(st, e);
	else bossStep(st, e, d, ux, uy);
}

/* THE BREACH (the Fracture's boss, design §14.4a). Nothing about it turns: the
 * Tidewarden's spiral is the Shallows' (owner's note, 2026-11-19).
 *  FAULT  — lines from its body, marked first, that TEAR into a still wall of shots
 *           for a moment; a pillar stops a line. Three (a Y aimed at the player) in
 *           phase 1, four (an X) in phase 2, in waves.
 *  SHATTER — slow heavy shards aimed round the player that burst into rings.
 *  TEAR   — an aimed line of shots, fast to slow.
 * Phase 2 (half health, after the same telegraphed pause): its room's cracks run
 * twice as fast, and it BLINKS between four anchors round where it started, a ring
 * on each landing. It lobs the mortar at a player who hides, as every boss does. */
const BREACH_CYCLE = [["fault", 100], ["rest", 24], ["shatter", 66], ["rest", 24], ["tear", 80], ["rest", 24]];
const BREACH_CYCLE_2 = [["fault", 110], ["blink", 50], ["shatter", 66], ["blink", 50], ["tear", 70], ["blink", 50]];
const BREACH_ANCHORS = [[-5, -3], [5, 3], [5, -3], [-5, 3]];
export const FAULT = { tele: 34, reach: 14, gap: 0.55, life: 40, dmg: 18, waves: [0, 50] };
export const SHATTER = { fuse: 58, n: 8, speed: 6, dmg: 12 };
/* Mark fault lines from the body, the first at the player: [vx, vy, length], each
 * stopped by the first pillar or wall (what the page draws is what will tear). */
function markFaults(st, e, n) {
	const dx = st.p.x - e.x, dy = st.p.y - e.y, d = Math.sqrt(dx * dx + dy * dy) || 1;
	e.faults = [];
	for (let k = 0; k < n; k++) {
		const [vx, vy] = rotate(dx / d, dy / d, k * TAU / n);
		let len = 0;
		for (let s = 1; s <= FAULT.reach && !shotSolid(tileAt(st, e.x + vx * s, e.y + vy * s)); s += FAULT.gap) len = s;
		e.faults.push([vx, vy, len]);
	}
	e.faultT = FAULT.tele;
}
/* Tear the marked lines open: a still wall of shots along each, for a moment. */
function tearFaults(st, e) {
	for (const [vx, vy, len] of e.faults || [])
		for (let s = 1; s <= len; s += FAULT.gap) shoot(st, "e", e.x + vx * s, e.y + vy * s, 0, 0, FAULT.dmg, 0.24, FAULT.life);
	e.faults = null; e.faultT = 0;
}
function breachStep(st, e, ux, uy) {
	const p = st.p;
	if (e.phase === 1 && e.hp <= e.maxHp / 2) { e.phase = 0; e.modeT = 70; e.tele = 70; e.faults = null; e.faultT = 0; return; }
	if (e.phase === 0) {
		if (--e.modeT <= 0) { e.phase = 2; e.mode = 0; e.modeT = BREACH_CYCLE_2[0][1]; e.tele = 0; st.fastRoom = e.room; }
		else e.tele = e.modeT;
		return;
	}
	if (e.cd > 0) return;
	bossMortar(st, e);
	const cycle = e.phase === 1 ? BREACH_CYCLE : BREACH_CYCLE_2;
	const [mode, len] = cycle[e.mode];
	const t = len - e.modeT;
	st.src = `boss:${mode}`;
	if (mode === "fault") {
		const lines = e.phase === 1 ? 3 : 4;
		for (const w of FAULT.waves) if (t === w) markFaults(st, e, lines);
		if (e.faultT > 0 && --e.faultT === 0) tearFaults(st, e);
	} else if (mode === "shatter") {
		if (t === 0) e.tele = 20;
		if (t === 20 || t === 44) {
			const dx = p.x - e.x, dy = p.y - e.y, n = Math.sqrt(dx * dx + dy * dy) || 1;
			for (let i = -1; i <= 1; i++) {
				const [vx, vy] = rotate(dx / n, dy / n, i * 0.42 + (t === 44 ? 0.21 : 0));
				shootAt(st, "e", e.x, e.y, e.x + vx, e.y + vy, 3.6, 22, 0.42, 200);
				const b = st.bullets[st.bullets.length - 1];
				b.fuse = SHATTER.fuse; b.shard = true;
			}
		}
	} else if (mode === "tear") {
		const k = t % 34;
		if (k === 0) { e.aimX = p.x; e.aimY = p.y; e.tele = 16; }
		if (k === 16) {
			const dx = e.aimX - e.x, dy = e.aimY - e.y, n = Math.sqrt(dx * dx + dy * dy) || 1;
			for (let i = 0; i < 7; i++) shootAt(st, "e", e.x, e.y, e.x + dx / n, e.y + dy / n, 6.5 + i, 14, 0.2, 200);
		}
	} else if (mode === "blink") {
		if (t === 0) {
			e.anchor = ((e.anchor || 0) + 1) % BREACH_ANCHORS.length;
			const [ax, ay] = BREACH_ANCHORS[e.anchor];
			e.toX = e.homeX + ax; e.toY = e.homeY + ay; e.tele = 40;
		}
		if (t === 40) {
			const to = blocked(st, e.toX, e.toY, e.r) ? nearestClear(st, { x: e.toX, y: e.toY, r: e.r }) : { x: e.toX, y: e.toY };
			if (to) { e.x = to.x; e.y = to.y; }
			e.toX = e.toY = 0;
			for (let k = 0; k < 20; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / 20, 5, 16, 0.22, 240);
		}
	}
	if (e.tele > 0) e.tele--;
	if (--e.modeT <= 0) {
		e.mode = (e.mode + 1) % cycle.length;
		e.modeT = cycle[e.mode][0] === "rest" ? cadence(st, cycle[e.mode][1]) : cycle[e.mode][1];
	}
}

/* The boss: two phases. Phase 1 alternates a rotating SPIRAL with aimed FANS.
 * Phase 2 (at half health, after a telegraphed pause) adds the NOVA — two dense
 * rings of heavy shots. Caught in the open, a nova is lethal; behind a rock, or
 * in a gap read early, it is not (design §8.3). */
const BOSS_CYCLE = [["spiral", 150], ["rest", 40], ["fan", 100], ["rest", 40]];
/* THE MORTAR (owner's ask, 2026-11-19): cover is for a moment, not for good. Once the
 * player has been out of the boss's sight for `after` ticks, it lobs a shell at
 * where they stand every `every` ticks while they stay hidden: a ring that fills for
 * `delay` ticks, `dmg` on landing, then BURNING ground for `burn` ticks that hurts
 * `burnDmg` every `burnEvery` ticks — so the same spot behind the same pillar cannot
 * be gone back to for a while. In sight, the boss fires as before and lobs nothing. */
export const MORTAR = { after: 60, every: 100, delay: 54, r: 1.4, dmg: 22, burn: 300, burnEvery: 20, burnDmg: 6 };

// ── the Ashen Breach (owner's design, 2026-11-19) ───────────────────────────
export const CINDER = { every: 12, r: 0.45, last: 80 };            // the trail it leaves
export const KILN = { every: 140, tele: 24, delay: 50, r: 1.1, dmg: 18, burn: 150, range: 10 };
export const SMOLDER = { flare: 30, charge: 150, speed: 5, reach: 1, fuse: 24, r: 1.6, dmg: 20, burn: 240 };
/* PLAYER FIRE ("embers"): burning ground the PLAYER sets (the Ashen uniques). It never
 * hurts the player. Every `every` ticks each enemy standing in it takes the hottest
 * one's damage, once. Shared with the town's posts. */
export const EMBER = { every: 20 };

/* The Pyre threads aimed volleys between its opening rings. At half health it
 * summons Kilns and alternates rings with barrages that force a lane change. */
const PYRE_CYCLE = [["rings", 120], ["rest", 30], ["cross", 110], ["rest", 30]];
const PYRE_CYCLE_2 = [["rings", 100], ["rest", 24], ["lanes", 180], ["rest", 24]];
export const PYRE = {
	ring: { n: 16, n2: 20, speed: 5, dmg: 16, every: 40 },
	cross: { arm: 6, gap: 1.1, r: 0.6, delay: 48, dmg: 16, burn: 150, waves: [0, 38, 76] },
	kilns: [[-6, -4], [6, 4]],                                     // where its Kilns come in, from its spawn
};
/* A cross of shells on (cx, cy): a + or (diagonal) an x, each arm stopped by a wall or rock. */
function flameCross(st, cx, cy, diagonal) {
	const q = PYRE.cross, at = st.tick + q.delay;
	const lob = (x, y) => st.mortars.push({ x, y, r: q.r, at, d: q.delay, dmg: q.dmg, burn: q.burn, src: "boss:flame", fire: "boss:fire" });
	const dirs = diagonal ? [[0.7071, 0.7071], [-0.7071, 0.7071], [0.7071, -0.7071], [-0.7071, -0.7071]] : [[1, 0], [-1, 0], [0, 1], [0, -1]];
	st.mortars ||= [];
	lob(cx, cy);
	for (const [vx, vy] of dirs)
		for (let k = 1; k <= q.arm; k++) {
			const x = cx + vx * k * q.gap, y = cy + vy * k * q.gap;
			if (walkSolid(tileAt(st, x, y))) break;
			lob(x, y);
		}
}
// Two offset waves in one direction, then two across it. Each floor marker
// detonates once, leaving safe bands and keeping the whole arena traversable.
function flameLanes(st, e, wave) {
	const room = st.rooms[e.room];
	const [top, bottom] = st.roomY[e.room];
	const vertical = wave >= 2;
	const first = vertical ? room.x0 : top;
	const end = vertical ? room.x1 : bottom + 1;
	const delay = 48;
	for (let line = first + 1 + (wave % 2) * 2; line < end; line += 4) {
		for (let pos = vertical ? top : room.x0; pos < (vertical ? bottom + 1 : room.x1); pos++) {
			const x = (vertical ? line : pos) + 0.5;
			const y = (vertical ? pos : line) + 0.5;
			if (!walkSolid(tileAt(st, x, y))) st.mortars.push({
				x, y, r: 0.64, at: st.tick + delay, d: delay, dmg: 24, burn: 0, src: "boss:barrage",
			});
		}
	}
}

function pyreStep(st, e) {
	const p = st.p;
	if (e.phase === 1 && e.hp <= e.maxHp / 2) { e.phase = 0; e.modeT = 70; e.tele = 70; return; }
	if (e.phase === 0) {
		if (--e.modeT <= 0) {
			e.phase = 2; e.mode = 0; e.modeT = PYRE_CYCLE_2[0][1]; e.tele = 0;
			let k = 0;
			for (const o of st.enemies) {                    // its Kilns come into the fight
				if (o.summon !== e.id || !o.dormant || o.hp <= 0) continue;
				const [ax, ay] = PYRE.kilns[k++ % PYRE.kilns.length];
				o.x = e.homeX + ax; o.y = e.homeY + ay;
				if (blocked(st, o.x, o.y, o.r)) { const to = nearestClear(st, o); if (to) { o.x = to.x; o.y = to.y; } }
				o.dormant = false; o.active = true; o.cd = 40;
			}
		} else e.tele = e.modeT;
		return;
	}
	if (e.cd > 0) return;
	bossMortar(st, e);
	const cycle = e.phase === 1 ? PYRE_CYCLE : PYRE_CYCLE_2;
	const [mode, len] = cycle[e.mode];
	const t = len - e.modeT;
	st.src = mode === "cross" ? "boss:flame" : "boss:ring";
	if (mode === "rings") {
		const q = PYRE.ring, n = e.phase === 1 ? q.n : q.n2;
		if (t % q.every === 0) {
			e.ang = e.ang === 0 ? PI / n : 0;
			for (let k = 0; k < n; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / n, q.speed, q.dmg, 0.22, 240);
		}
		if (e.phase === 1 && t % q.every === 20) {
			const a = Math.atan2(p.y - e.y, p.x - e.x);
			for (let i = -2; i <= 2; i++) shoot(st, "e", e.x, e.y, a + i * 0.19, 8, 18, 0.19, 180);
		}
		if (t % q.every === q.every - 16 && t + 16 < len) e.tele = 16;
	} else if (mode === "cross") {
		const w = PYRE.cross.waves.indexOf(t);
		if (w >= 0) flameCross(st, p.x, p.y, w % 2 === 1);
	} else if (mode === "lanes" && t % 45 === 0) {
		flameLanes(st, e, t / 45);
	}
	if (e.tele > 0) e.tele--;
	if (--e.modeT <= 0) {
		e.mode = (e.mode + 1) % cycle.length;
		e.modeT = cycle[e.mode][0] === "rest" ? cadence(st, cycle[e.mode][1]) : cycle[e.mode][1];
	}
}

/* One pulse of the player's fire (embers): `hurt(target, dmg)` for each target standing
 * in it, by the hottest one. Shared with the town's posts. */
export function emberPulse(st, targets, hurt) {
	if (st.embers?.length) st.embers = st.embers.filter((f) => f.until > st.tick);
	if (!st.embers?.length || st.tick % EMBER.every !== 0) return;
	for (const t of targets) {
		let best = 0;
		for (const f of st.embers) {
			const dx = t.x - f.x, dy = t.y - f.y, rr = f.r + (t.r || 0);
			if (dx * dx + dy * dy < rr * rr && f.dmg > best) best = f.dmg;
		}
		if (best > 0) hurt(t, best);
	}
}
/* The Emberweave's trail: fire under the player's feet while they move. Shared with the town. */
export function trailEmber(st, moving) {
	const s = st.stats, q = UNIQUE.emberweave;
	if (s.trail && moving && st.tick % q.every === 0) (st.embers ||= []).push({ x: st.p.x, y: st.p.y, r: q.r, until: st.tick + q.last, dmg: s.trail });
}
/* A Flare Bow's flare coming down: fire where it lands. Shared with the town. */
export function flareLand(st, b, x, y) {
	const q = UNIQUE.flare;
	(st.embers ||= []).push({ x, y, r: q.r, until: st.tick + q.last, dmg: Math.max(1, Math.round(b.dmg * q.share)) });
	(st.blasts ||= []).push({ x, y, r: q.r, until: st.tick + 18, hot: true });
}
/* An Ember Kunai stuck in what it hit: the burst comes `UNIQUE.kunai.delay` later. */
export function stickKunai(st, b, id) {
	(st.stuck ||= []).push({ id, at: st.tick + UNIQUE.kunai.delay, dmg: Math.max(1, Math.round(b.dmg * UNIQUE.kunai.share)) });
}
/* The stuck kunai that are due: `hit(k)` deals each burst. Shared with the town. */
export function burstStuck(st, hit) {
	if (!st.stuck?.length) return;
	const due = st.stuck.filter((k) => k.at <= st.tick);
	if (!due.length) return;
	st.stuck = st.stuck.filter((k) => k.at > st.tick);
	for (const k of due) hit(k);
}

/* Can the boss see the player? A shot's line: no rock or wall between them. */
export function inSight(st, a, b) {
	const dx = b.x - a.x, dy = b.y - a.y, n = Math.ceil(Math.sqrt(dx * dx + dy * dy) / 0.25);
	for (let i = 1; i < n; i++) {
		if (shotSolid(tileAt(st, a.x + dx * i / n, a.y + dy * i / n))) return false;
	}
	return true;
}

function bossMortar(st, e) {
	if (inSight(st, e, st.p)) { e.hidden = 0; return; }
	e.hidden = (e.hidden || 0) + 1;
	const k = e.hidden - MORTAR.after;
	if (k < 0 || k % cadence(st, MORTAR.every) !== 0) return;
	(st.mortars ||= []).push({ x: st.p.x, y: st.p.y, r: MORTAR.r, at: st.tick + MORTAR.delay, d: MORTAR.delay });
}

/* Shells landing, and the ground they leave burning. A shell may say its own damage,
 * burn and names (a Kiln's, a Smolder's, the Pyre's); the boss's mortar is the default.
 * The player burns standing in a fire pool, every
 * MORTAR.burnEvery ticks — unless their Cinderguard makes them fireproof. */
function stepMortars(st) {
	const p = st.p;
	if (st.fires?.length) st.fires = st.fires.filter((f) => f.until > st.tick);
	if (st.mortars?.length) {
		const due = st.mortars.filter((m) => m.at <= st.tick);
		st.mortars = st.mortars.filter((m) => m.at > st.tick);
		for (const m of due) {
			const dx = p.x - m.x, dy = p.y - m.y, rr = m.r + p.r;
			if (dx * dx + dy * dy < rr * rr) hurtPlayer(st, m.dmg ?? MORTAR.dmg, m.src || "boss:mortar");
			const burn = m.burn ?? MORTAR.burn;
			if (burn > 0) st.fires.push({ x: m.x, y: m.y, r: m.r, until: st.tick + burn, ...(m.fire ? { src: m.fire } : {}) });
			(st.blasts ||= []).push({ x: m.x, y: m.y, r: m.r, until: st.tick + 18, hot: true });
			if (st.status !== "play") return;
		}
	}
	const pool = st.fires?.length ? st.fires.find((f) => { const dx = p.x - f.x, dy = p.y - f.y, rr = f.r + p.r * 0.5; return dx * dx + dy * dy < rr * rr; }) : null;
	p.inFire = !!pool;
	if (p.inFire && !st.stats.fireproof && st.tick % MORTAR.burnEvery === 0) hurtPlayer(st, MORTAR.burnDmg, pool.src || "boss:fire");
}

const BOSS_CYCLE_2 = [["spiral", 140], ["rest", 30], ["nova", 80], ["rest", 40], ["fan", 90], ["rest", 30]];

function bossStep(st, e, d, ux, uy) {
	const p = st.p;
	if (e.phase === 1 && e.hp <= e.maxHp / 2) { e.phase = 0; e.modeT = 70; e.tele = 70; return; }
	if (e.phase === 0) {                              // the transition: telegraphed, harmless
		if (--e.modeT <= 0) { e.phase = 2; e.mode = 0; e.modeT = BOSS_CYCLE_2[0][1]; e.tele = 0; }
		else e.tele = e.modeT;
		return;
	}
	if (e.cd > 0) return;                             // the opening beat after the room wakes it
	bossMortar(st, e);
	const cycle = e.phase === 1 ? BOSS_CYCLE : BOSS_CYCLE_2;
	const [mode] = cycle[e.mode];
	const t = cycle[e.mode][1] - e.modeT;              // ticks into this mode
	st.src = `boss:${mode}`;
	if (e.phase === 2 && d > 3) moveBody(st, e, ux * ENEMY.boss.speed * st.scale.speed * DT, uy * ENEMY.boss.speed * st.scale.speed * DT);

	if (mode === "spiral") {
		const every = cadence(st, e.phase === 1 ? 6 : 5), arms = e.phase === 1 ? 3 : 5;
		if (t % every === 0) {
			for (let k = 0; k < arms; k++) shoot(st, "e", e.x, e.y, e.ang + k * TAU / arms, 5, 14, 0.2, 240);
			e.ang += 0.21;
		}
	} else if (mode === "fan") {
		const k = t % 33;
		if (k === 0) { e.aimX = p.x; e.aimY = p.y; e.tele = 18; }
		if (k === 18) {
			const dx = e.aimX - e.x, dy = e.aimY - e.y, n = Math.sqrt(dx * dx + dy * dy) || 1;
			for (let i = -2; i <= 2; i++) {
				const [vx, vy] = rotate(dx / n, dy / n, i * 0.22);
				shootAt(st, "e", e.x, e.y, e.x + vx, e.y + vy, 8, 18, 0.22, 180);
			}
		}
	} else if (mode === "nova") {
		if (t === 0) e.tele = 48;
		if (t === 48 || t === 60) {
			const off = t === 48 ? 0 : TAU / 56;
			for (let k = 0; k < 28; k++) shoot(st, "e", e.x, e.y, off + k * TAU / 28, 6.5, 34, 0.26, 260);
		}
	}
	if (e.tele > 0) e.tele--;
	if (--e.modeT <= 0) {
		e.mode = (e.mode + 1) % cycle.length;
		e.modeT = cycle[e.mode][0] === "rest" ? cadence(st, cycle[e.mode][1]) : cycle[e.mode][1];
	}
}

// ── one tick ────────────────────────────────────────────────────────────────
/* input: { mx, my: -1|0|1; ax, ay: the aim vector (any length); fire: bool;
 *          ability: bool (this tick only); take: drop id | null;
 *          drop: an item the player put down (an opaque key the page names it by);
 *          lift: the key of an item on the floor to take back; potion: bool (this tick only); enter: bool (E on the portal); recall: bool;
 *          gear: the whole equipped list, on the tick it changes (else absent) } */
export function step(st, input) {
	st.events = [];
	if (st.status !== "play") return st;
	st.tick++;
	if (st.bossTimeTicks == null) st.elapsedTicks++;
	if (st.shield && st.shield.until <= st.tick) st.shield = null;
	if (st.damageNumbers) st.damageNumbers = st.damageNumbers.filter((f) => f.until > st.tick);
	if (input.gear) setGear(st, input.gear);
	const p = st.p, s = st.stats;

	if (input.recall) { st.status = "recalled"; st.events.push({ type: "recall" }); return st; }

	// movement
	let mx = input.mx || 0, my = input.my || 0;
	if (mx && my) { mx *= 0.7071067811865476; my *= 0.7071067811865476; }
	const speed = PLAYER_SPEED * (s.moveMult || 1);                // the Windrunner's Cloak
	moveBody(st, p, mx * speed * DT, my * speed * DT);
	trailEmber(st, mx !== 0 || my !== 0);                          // the Emberweave

	// regeneration, never past the recovery limit (design §9.3)
	const limit = recoveryLimit(st);
	if (p.hp < limit) p.hp = Math.min(limit, p.hp + s.hpRegen * DT);
	p.mp = Math.min(s.maxMp, p.mp + s.mpRegen * DT);
	if (p.hurt > 0) p.hurt--;

	playerFire(st, input);

	// the healing potion: only when it would heal, then a cooldown
	if (p.potionCd > 0) p.potionCd--;
	// It heals only up to the recovery limit and never raises it (owner's call,
	// 2026-11-18): a potion tops up what regeneration could reach, faster.
	if (input.potion && !(p.potionCd > 0) && p.hp < limit) {
		p.hp = Math.min(limit, p.hp + POTION_HEAL);
		p.potionCd = POTION_COOLDOWN;
		st.events.push({ type: "potion", local: true });
	}

	// HEAL ORBS ARE TAKEN BY WALKING OVER THEM (owner's ask, 2026-11-19; was E) —
	// unless it would do nothing (full HP and a full recovery limit), so a full-health
	// player does not waste one by passing it.
	for (let i = 0; i < st.pickups.length; i++) {
		const h = st.pickups[i];
		if (!near(p, h, p.r + 0.35) || (p.hp >= s.maxHp && p.low >= s.maxHp)) continue;
		st.pickups.splice(i, 1);
		p.low = Math.min(s.maxHp, p.low + HEAL);
		p.hp = Math.min(recoveryLimit(st), p.hp + HEAL);
		st.events.push({ type: "heal", local: true });   // the server keeps no HP
		break;
	}
	if (input.take) {
		const bag = st.bags.find((b) => b.drops.includes(input.take) && near(p, b, REACH));
		if (bag) {
			bag.drops = bag.drops.filter((d) => d !== input.take);
			st.events.push({ type: "pickup", drop: input.take });
		}
		st.bags = st.bags.filter((b) => b.drops.length);
	}
	// The floor: items the PLAYER put down, at their feet. The sim only keeps where
	// they lie; what they are is the page's (it reports drop_item / pickup_item).
	if (input.drop) st.floor.push({ key: input.drop, x: p.x, y: p.y });
	if (input.lift) {
		const i = st.floor.findIndex((f) => f.key === input.lift && near(p, f, REACH));
		if (i >= 0) { st.floor.splice(i, 1); st.events.push({ type: "lift", key: input.lift, local: true }); }
	}
	// Leaving is a choice (E), never a step: walking over the portal to reach the
	// boss's loot must not end the run with that loot still on the floor.
	if (input.enter && st.portal && near(p, st.portal, REACH)) {
		st.status = "complete";
		st.events.push({ type: "complete" });
		return st;
	}
	// The way deeper is a choice the PAGE makes (three modifiers, pick one, and a
	// new level from the server): the sim only says the player asked.
	if (input.enter && st.deeper && near(p, st.deeper, REACH)) st.events.push({ type: "deeper", local: true });

	sealRoom(st);
	stepCracks(st);
	if (st.status !== "play") return st;
	for (const e of st.enemies) {
		if (e.hp <= 0 || !e.active) continue;
		enemyStep(st, e);
		if (st.status !== "play") return st;
	}

	stepMortars(st);
	if (st.status !== "play") return st;
	for (const e of st.enemies) {                         // the Ember Loop's burning
		if (!(e.burnUntil > st.tick) || e.hp <= 0) continue;
		if ((e.burnUntil - st.tick) % UNIQUE.burn.every === 0) hurtEnemy(st, e, e.burnDmg, 2);
	}
	// the player's own fire, and the Ember Kunai's stuck blades
	emberPulse(st, st.enemies, (e, dmg) => {
		if (e.hp <= 0 || !e.active || e.phase === 0) return;
		e.scorched = st.tick + EMBER.every + 10;
		hurtEnemy(st, e, dmg, 2);
	});
	burstStuck(st, (k) => {
		const e = st.enemies.find((x) => x.id === k.id);
		if (!e || e.hp <= 0 || !e.active || e.phase === 0) return;
		(st.blasts ||= []).push({ x: e.x, y: e.y, r: 0.55, until: st.tick + 18, hot: true });
		hurtEnemy(st, e, k.dmg, 4);
	});
	if (st.status !== "play") return st;

	// stars landing (the Diviner's ability)
	landStarfalls(st, (f) => {
		for (const e of st.enemies) {
			if (e.hp <= 0 || e.phase === 0 || !e.active) continue;
			const dx = e.x - f.x, dy = e.y - f.y, rr = f.r + e.r;
			if (dx * dx + dy * dy >= rr * rr) continue;
			hurtEnemy(st, e, f.dmg, 6);
		}
	});
	if (st.status !== "play") return st;
	// the Paladin's field burning what is inside it
	slowPulse(st, (r) => {
		for (const e of st.enemies) {
			if (e.hp <= 0 || e.phase === 0 || !e.active) continue;
			const c = st.slowAt || st.p, dx = e.x - c.x, dy = e.y - c.y, rr = r + e.r;
			if (dx * dx + dy * dy < rr * rr) { hurtEnemy(st, e, st.slowDmg, 3); if (st.status !== "play") return; }
		}
	});
	if (st.status !== "play") return st;

	// bullets
	const keep = [];
	for (const b of st.bullets) {
		const fc = st.slowAt || st.p, dxp = fc.x - b.x, dyp = fc.y - b.y;
		const sr = st.slowR || SLOW_RADIUS;
		const slowed = b.owner === "e" && st.slowUntil > st.tick && dxp * dxp + dyp * dyp <= sr * sr;
		const speedScale = slowed ? st.slowF || SLOW_FACTOR : 1;          // the Censer slows less
		b.x += b.vx * DT * speedScale; b.y += b.vy * DT * speedScale;
		if (b.owner === "e" && st.shield) {
			const sx = st.shield.x - b.x, sy = st.shield.y - b.y;
			const rr = st.shield.r + b.r;
			if (sx * sx + sy * sy < rr * rr) { if (--st.shield.hits <= 0) st.shield = null; continue; }
		}
		if (b.fuse && --b.fuse <= 0) {                    // a shatter shard bursts into a ring
			const src = st.src; st.src = b.src;
			for (let k = 0; k < SHATTER.n; k++) shoot(st, "e", b.x, b.y, k * TAU / SHATTER.n + 0.2, SHATTER.speed, SHATTER.dmg, 0.18, 120);
			st.src = src;
			continue;
		}
		turnBack(b);
		if (--b.life <= 0 || wallHit(b, (x, y) => shotSolid(tileAt(st, x, y)))) {
			if (b.comet) cometBurst(st, b, b.x - b.vx * DT, b.y - b.vy * DT);
			if (b.flare) flareLand(st, b, b.x - b.vx * DT, b.y - b.vy * DT);
			continue;
		}
		let gone = false;
		if (b.owner === "p") {
			for (const e of st.enemies) {
				if (e.hp <= 0 || b.hit.includes(e.id)) continue;
				if (e.phase === 0 || !e.active) continue;        // the boss's turn, and a room not entered
				const dx = e.x - b.x, dy = e.y - b.y, rr = e.r + b.r;
				if (dx * dx + dy * dy < rr * rr) {
					b.hit.push(e.id);
					hurtEnemy(st, e, b.dmg, 4);
					if (b.burn && e.hp > 0) { e.burnUntil = st.tick + UNIQUE.burn.last; e.burnDmg = b.burn; }   // refreshed, never stacked
					if (b.stick && e.hp > 0) stickKunai(st, b, e.id);                // the Ember Kunai
					if (b.flare) { flareLand(st, b, e.x, e.y); gone = true; break; }  // the Flare Bow's flare comes down
					if (b.splash) for (const o of st.enemies) {    // the Oathhammer
						if (o === e || o.hp <= 0 || o.phase === 0 || !o.active) continue;
						const ox = o.x - e.x, oy = o.y - e.y, sr = UNIQUE.splash.r + o.r;
						if (ox * ox + oy * oy < sr * sr) hurtEnemy(st, o, Math.round(b.dmg * UNIQUE.splash.share), 3);
					}
					if (b.comet) { cometBurst(st, b, b.x, b.y, e.id); gone = true; break; }
					if (b.pierce-- <= 0) { gone = true; break; }
				}
			}
		} else {
			const dx = p.x - b.x, dy = p.y - b.y, rr = p.r + b.r;
			if (dx * dx + dy * dy < rr * rr) { hurtPlayer(st, b.dmg, b.src || null); gone = true; }
		}
		if (!gone) keep.push(b);
		if (st.status !== "play") break;
	}
	st.bullets = st.bossDown ? keep.filter((b) => b.owner === "p") : keep;
	if (st.bossDown) { st.mortars = []; st.fires = []; }   // its shells and fires too
	st.bossDown = false;
	if (st.rings?.length) {                            // Volatile: what fell this tick bursts
		for (const r of st.rings) {
			st.src = `${r.type}:burst`;
			for (let k = 0; k < r.n; k++) shoot(st, "e", r.x, r.y, r.a + k * TAU / r.n, 4, 10, 0.18, 110);
		}
		st.rings = [];
	}
	return st;
}

/* The player's weapon and ability for one tick: aim, the fire cooldown, a burst in
 * flight, the volley ability. Shared with the town (town.js), which has a `p`, its
 * `stats` and `bullets` of the same shape, so a weapon fires there exactly as here. */
export function playerFire(st, input) {
	const p = st.p, s = st.stats;
	const ix = input.ax || 0, iy = input.ay || 0, al = Math.sqrt(ix * ix + iy * iy);
	const ax = al > 0 ? ix / al : 1, ay = al > 0 ? iy / al : 0;
	if (p.fireCd > 0) p.fireCd--;
	if (input.fire && p.fireCd === 0) {
		volley(st, ax, ay);
		p.burstLeft = s.burst - 1; p.burstCd = s.gap;
		p.fireCd = Math.max(1, Math.round(TPS / s.rate));
	} else if (p.burstLeft > 0 && --p.burstCd <= 0) {   // a burst finishes once started
		volley(st, ax, ay);
		p.burstLeft--; p.burstCd = s.gap;
	}
	if (p.abilityCd > 0) p.abilityCd--;
	if (input.ability && s.abilityKind && p.mp >= s.abilityCost && !(p.abilityCd > 0)) {
		p.mp -= s.abilityCost;
		if (s.kindle) p.kindled = SPECIAL.kindling.shots;       // Kindling: the next volleys burn
		if (s.abilityKind === "volley" && s.gale) {           // the Gale Quiver: one arrow through everything
			const q = UNIQUE.gale;
			st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: ax * q.speed, vy: ay * q.speed, dmg: s.abilityDmg,
				r: q.r, life: Math.round(q.range / q.speed * TPS), pierce: 99, bounce: 0, hit: [], look: "gale" });
		} else if (s.abilityKind === "volley") {
			for (let i = 0; i < s.arrows; i++) {
				const [vx, vy] = rotate(ax, ay, (i - (s.arrows - 1) / 2) * 0.14);
				st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: vx * 16, vy: vy * 16, dmg: s.abilityDmg,
					r: 0.16, life: 45, pierce: 1, bounce: 0, hit: [] });
			}
		} else if (s.abilityKind === "shield") {
			st.shield = { x: p.x + ax * 0.95, y: p.y + ay * 0.95, r: 0.72, hits: 1 + Math.floor(s.ap / 8),
				until: st.tick + s.shieldTime };
		} else if (s.abilityKind === "slow") {
			st.slowUntil = st.tick + SLOW_DURATION;
			st.slowR = s.slowRadius;
			st.slowDmg = s.abilityDmg;
			st.slowAt = s.anchored ? { x: p.x, y: p.y } : null;   // the Anchor Orb stays where it was cast
			st.slowF = s.censer ? UNIQUE.censer.slow : SLOW_FACTOR;
		} else if (s.abilityKind === "starfall") {
			// Where the cursor is, no farther than STARFALL_RANGE.
			const k = al > STARFALL_RANGE ? STARFALL_RANGE / al : 1;
			(st.starfalls ||= []).push({ x: p.x + ix * k, y: p.y + iy * k, r: STARFALL_RADIUS, dmg: s.abilityDmg,
				at: st.tick + STARFALL_DELAY, cast: st.tick, ...(s.crater ? { crater: 1 } : {}) });
			if (s.echo) st.starfalls.push({ x: p.x + ix * k, y: p.y + iy * k, r: STARFALL_RADIUS,   // the Codex's echo
				dmg: Math.round(s.abilityDmg * s.echo * 100) / 100, at: st.tick + STARFALL_DELAY + UNIQUE.echo.delay, cast: st.tick, echo: true });
		} else if (s.abilityKind === "counter") {
			p.counterUntil = st.tick + COUNTER_WINDOW;
			p.abilityCd = ABILITY.counter.cooldown;          // the one ability with a cooldown
		}
	}
}

/* One volley from the player: `shots` arrows fanned around the aim. A counter's
 * empowerment is spent on the whole of the next volley. */
function volley(st, ax, ay) {
	const p = st.p, s = st.stats, life = Math.round(s.range / s.shotSpeed * TPS);
	let mult = p.empower > 0 ? p.empower : 1;
	p.empower = 0;
	if (s.fullMoon && p.mp >= s.maxMp) mult *= s.fullMoon;      // the Mantle of the Full Moon
	if (p.primed > 0) { mult *= p.primed; p.primed = 0; }       // Duskmail: the shot after a kill
	let burn = s.burn || 0;
	if (p.kindled > 0) { burn = Math.max(burn, s.kindle || 0); p.kindled--; }   // Kindling
	if (s.coalCap) {                                            // Banked Coal: Attack while unhit
		const b = Math.min(s.coalCap, Math.floor((st.tick - (p.hitAt || 0)) / UNIQUE.coal.every));
		if (b > 0) mult *= (1 + (s.att + b) / STAT_SCALE) / (1 + s.att / STAT_SCALE);
	}
	const flare = s.flare > 0 && (p.volleys = (p.volleys || 0) + 1) % s.flare === 0;   // the Flare Bow
	for (let i = 0; i < s.shots; i++) {
		const [vx, vy] = s.shots > 1 ? rotate(ax, ay, (i - (s.shots - 1) / 2) * s.spread) : [ax, ay];
		st.bullets.push({ owner: "p", x: p.x, y: p.y, vx: vx * s.shotSpeed, vy: vy * s.shotSpeed,
			dmg: Math.round(s.dmg * mult), r: 0.14, life, pierce: s.pierce, bounce: s.bounce, hit: [],
			...(s.look ? { look: s.look } : {}), ...(mult > 1 ? { power: true } : {}),
			...(burn ? { burn } : {}), ...(s.splash ? { splash: 1 } : {}), ...(s.comet ? { comet: 1 } : {}),
			...(s.ret ? { ret: Math.floor(life / 2) } : {}), ...(flare ? { flare: 1, look: "flare" } : {}),
			...(s.stick ? { stick: 1 } : {}) });
	}
}

/* Stars that are due land now: `hit(star)` deals the damage (enemies in a rift,
 * the practice posts in town). Each leaves a short-lived blast for the renderer. */
/* One pulse of the Paladin's field while it is up: `hit(radius)` deals its damage
 * around the player. Shared with the town's posts. */
export function slowPulse(st, hit) {
	if (!(st.slowUntil > st.tick) || !st.slowDmg) return;
	const left = st.slowUntil - st.tick;
	if (left % SLOW_PULSE === 0) hit(st.slowR || SLOW_RADIUS);
}

export function landStarfalls(st, hit) {
	if (st.blasts?.length) st.blasts = st.blasts.filter((b) => b.until > st.tick);
	if (!st.starfalls?.length) return;
	const due = st.starfalls.filter((f) => f.at <= st.tick);
	if (!due.length) return;
	st.starfalls = st.starfalls.filter((f) => f.at > st.tick);
	for (const f of due) {
		hit(f);
		(st.blasts ||= []).push({ x: f.x, y: f.y, r: f.r, until: st.tick + 18 });
		if (f.crater) (st.embers ||= []).push({ x: f.x, y: f.y, r: f.r, until: st.tick + UNIQUE.meteor.last,   // the Meteor Tome
			dmg: Math.max(1, Math.round(f.dmg * UNIQUE.meteor.share)) });
	}
}

/* A shot that has just moved into something solid: true if it breaks there. One
 * with `bounce` left glances off instead — back to where it was, its velocity
 * mirrored on the axis it crossed (both, into a corner). */
export function wallHit(b, solidAt) {
	if (!solidAt(b.x, b.y)) return false;
	if (!(b.bounce > 0)) return true;
	const x0 = b.x - b.vx * DT, y0 = b.y - b.vy * DT;
	const flipX = solidAt(b.x, y0), flipY = solidAt(x0, b.y);
	if (flipX || !flipY) b.vx = -b.vx;
	if (flipY || !flipX) b.vy = -b.vy;
	b.x = x0; b.y = y0; b.bounce--;
	return false;
}

function near(a, b, r) {
	const dx = a.x - b.x, dy = a.y - b.y;
	return dx * dx + dy * dy <= r * r;
}

/* The exit opens a few tiles from where the boss fell — clear of its loot bag, on
 * floor the player can stand on. Where it fell is the fallback (always walkable). */
export const PORTAL_OFFSET = 3;
function portalSpot(st, e, not = null) {
	for (const [dx, dy] of [[0, PORTAL_OFFSET], [0, -PORTAL_OFFSET], [PORTAL_OFFSET, 0], [-PORTAL_OFFSET, 0]]) {
		const x = e.x + dx, y = e.y + dy;
		if (blocked(st, x, y, PLAYER_R) || (not && near({ x, y }, not, PORTAL_OFFSET))) continue;
		return { x, y };
	}
	return { x: e.x, y: e.y };
}

/* The player all the way inside a room that still has enemies: both its doors seal
 * and everything in it wakes. One room at a time; the doors open in `kill`. */
function sealRoom(st) {
	if (st.sealed >= 0 || !st.rooms.length) return;
	const p = st.p;
	for (let i = 0; i < st.rooms.length; i++) {
		const r = st.rooms[i];
		if (st.roomLeft[i] > 0 && p.x - p.r > r.x0 && p.x + p.r < r.x1) {
			st.sealed = i;
			for (const e of st.enemies) if (e.room === i && e.hp > 0 && !e.dormant) e.active = true;
			st.events.push({ type: "seal", room: i, local: true });
			return;
		}
	}
}

/* A hit on an enemy. Warded: the first few hits (counted per enemy, each one —
 * an arrow, a star — one hit) do nothing but flash. */
function hurtEnemy(st, e, dmg, flash) {
	if (e.type === "smolder" && !e.lit) { e.lit = true; e.tele = SMOLDER.flare; e.charge = SMOLDER.charge; }   // it wakes
	if (e.ward > 0) { e.ward--; e.flash = 2; return; }
	// What a hit did, floated over the enemy (drawing only: not in the fingerprint).
	(st.damageNumbers ||= []).push({ x: e.x, y: e.y - e.r, amount: Math.round(Math.min(dmg, e.hp) * 10) / 10, until: st.tick + 36, foe: true });
	e.hp -= dmg; e.flash = flash;
	if (e.hp <= 0) kill(st, e);
}

/* Gear changed mid-run (the player moved an item in the side panel). It is an
 * INPUT, applied at the top of a tick, so a replay of the same inputs swaps on the
 * same tick. Nothing is given for free: HP, the recovery limit and MP keep their
 * values and only come DOWN to a smaller maximum — otherwise taking a +HP ring off
 * and putting it back would be a heal. A burst in flight stops. */
export function setGear(st, gear) {
	st.gear = gear;
	st.stats = statsFor(gear, st.hero.level, st.classId);
	const p = st.p, s = st.stats;
	p.hp = Math.min(p.hp, s.maxHp);
	p.low = Math.min(p.low, s.maxHp);
	p.mp = Math.min(p.mp, s.maxMp);
	p.burstLeft = 0; p.burstCd = 0;
	p.empower = 0; p.primed = 0; p.kindled = 0; p.volleys = 0;
}

/* XP, and a level when it crosses one: the new stats apply at once, and the HP,
 * recovery limit and MP each rise by what the level added to their maximum. */
function gainXp(st, amount) {
	const h = st.hero;
	if (st.practice || amount <= 0) return;
	h.xp += amount;
	const level = levelFor(st.levels, h.xp);
	if (level <= h.level) return;
	const was = st.stats, now = statsFor(st.gear, level, st.classId), p = st.p;
	p.hp += now.maxHp - was.maxHp;
	p.low += now.maxHp - was.maxHp;
	p.mp = Math.min(now.maxMp, p.mp + now.maxMp - was.maxMp);
	st.stats = now;
	h.level = level;
	st.events.push({ type: "level", level, local: true });
}

function kill(st, e) {
	e.hp = 0;
	st.events.push({ type: "kill", enemy: e.id });
	if (st.roomLeft && e.room != null && --st.roomLeft[e.room] === 0 && st.sealed === e.room) {
		st.sealed = -1;
		st.events.push({ type: "unseal", room: e.room, local: true });
	}
	if (st.scale.volatile) (st.rings ||= []).push({ x: e.x, y: e.y, n: e.type === "boss" ? 16 : 8, a: rand(st) * TAU, type: e.type });
	gainXp(st, e.xp);
	if (st.stats.leech) st.p.hp = Math.min(recoveryLimit(st), st.p.hp + st.stats.leech);   // the Leechstone
	if (st.stats.dusk) st.p.primed = st.stats.dusk;                                       // Duskmail
	if (st.stats.secondWind && !(st.p.windAt > st.tick)) {                               // Second Wind
		st.p.mp = Math.min(st.stats.maxMp, st.p.mp + st.stats.secondWind);
		st.p.windAt = st.tick + SPECIAL.second_wind.cooldown;
	}
	// A Splitter breaks into its Splinters: they come into play where it fell.
	let k = 0;
	for (const s of st.enemies) {
		if (s.parent !== e.id || !s.dormant) continue;
		s.dormant = false; s.active = true; s.cd = 20;
		s.x = e.x + (k++ % 2 ? 0.45 : -0.45); s.y = e.y;
		if (blocked(st, s.x, s.y, s.r)) { const to = nearestClear(st, s); if (to) { s.x = to.x; s.y = to.y; } }
	}
	const drops = st.practice ? [] : st.dropsBy[e.id];
	if (e.type === "boss") st.bossTimeTicks = st.elapsedTicks;
	if (drops && drops.length) st.bags.push({ enemy: e.id, x: e.x, y: e.y, drops: [...drops] });
	const heal = st.healsBy && st.healsBy[e.id];
	if (heal) st.pickups.push({ id: heal, kind: "heal", x: e.x, y: e.y + (drops && drops.length ? 0.6 : 0) });
	if (e.type === "boss") {
		st.portal = portalSpot(st, e);
		if (st.offers.length && st.depth < 5) st.deeper = portalSpot(st, e, st.portal);
		// The dungeon is CLEARED when its boss falls: the bonus and the news come now,
		// not at the portal (owner's ask, 2026-11-18). The server credits it on the
		// same kill event.
		gainXp(st, st.completeXp);
		st.events.push({ type: "cleared", xp: st.completeXp, local: true });
		st.bossDown = true;                                        // its fire dies with it (below)
		for (const o of st.enemies) if (o.summon === e.id && o.hp > 0) kill(st, o);   // its Kilns fall with it
	}
	if (st.stats.ashSigil && (e.burnUntil > st.tick || e.scorched > st.tick)) {   // the Ash Sigil
		const q = UNIQUE.ash;
		(st.blasts ||= []).push({ x: e.x, y: e.y, r: q.r, until: st.tick + 18, hot: true });
		for (const o of st.enemies) {
			if (o === e || o.hp <= 0 || !o.active || o.phase === 0) continue;
			const dx = o.x - e.x, dy = o.y - e.y, rr = q.r + o.r;
			if (dx * dx + dy * dy < rr * rr) hurtEnemy(st, o, st.stats.ashSigil, 4);
		}
	}
}

/* A compact fingerprint of everything that decides the future — for the
 * determinism tests and for comparing a replay against a live run. */
export function fingerprint(st) {
	const r = (v) => Math.round(v * 1e6) / 1e6;
	return JSON.stringify([st.tick, st.elapsedTicks, st.bossTimeTicks, st.rng, st.status, st.classId, st.practice,
		st.hero.level, st.hero.xp, st.p.burstLeft, r(st.p.x), r(st.p.y), r(st.p.hp), r(st.p.low), r(st.p.mp),
		st.enemies.map((e) => [e.id, r(e.x), r(e.y), r(e.hp), e.cd, e.tele, e.scd, e.mode, e.modeT, e.ward, e.active]),
		st.sealed, st.roomLeft,
		st.bullets.length, st.bullets.map((b) => [r(b.x), r(b.y)]).slice(0, 40),
		st.bags.map((b) => b.drops.join(",")), st.pickups.length, st.shield && [r(st.shield.x), r(st.shield.y), st.shield.until], st.slowUntil, st.slowDmg || 0,
		st.p.potionCd, st.p.counterUntil, st.p.guardUntil, st.p.empower, st.p.abilityCd || 0, st.p.primed || 0,
		st.p.kindled || 0, st.p.windAt || 0, st.p.bulwarkUntil || 0, st.p.bulwarkAt || 0,
		st.slowAt ? [r(st.slowAt.x), r(st.slowAt.y)] : 0, st.enemies.map((e) => e.burnUntil || 0), (st.starfalls || []).map((f) => [r(f.x), r(f.y), f.at]),
		(st.mortars || []).map((m) => [r(m.x), r(m.y), m.at]), (st.fires || []).map((f) => [r(f.x), r(f.y), f.until]), st.enemies.map((e) => e.hidden || 0),
		(st.cracks || []).map((c) => c.t), st.fastRoom ?? -1, st.enemies.map((e) => (e.dormant ? 1 : 0)),
		(st.embers || []).map((f) => [r(f.x), r(f.y), f.until, f.dmg]),
		(st.stuck || []).map((k) => [k.id, k.at, k.dmg]), st.p.hitAt || 0, st.p.volleys || 0, st.p.phoenixUsed ? 1 : 0, st.p.inFire ? 1 : 0,
		st.slowF || 0, st.enemies.map((e) => [e.lit ? 1 : 0, e.charge || 0, e.scorched || 0])]);
}
