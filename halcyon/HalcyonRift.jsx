// Halcyon Rift — the greybox (design §23): a walkable town, and the Shallows,
// played as colored shapes.
//
// ONE SCREEN, NEVER SCROLLED. The stage (a canvas) is the town or the dungeon; the
// side panel beside it is the character — roster, equipment, inventory — and is on
// screen the whole time, in town and in a run. Everything is sized to the window.
//
// THE TOWN (town.js) is walked with WASD and shot in with the mouse (two practice
// posts show the damage); its places are used with E: the vault opens a panel over
// the stage, the forge lets you pick two items in your bag to fuse, a realm's portal
// starts a run. Items move by drag and drop, click-then-click, a double click (on
// and off) or the number keys 1-8 (the first eight bag slots, swapped on); the
// server does every move, and the page re-reads the state after each.
//
// THE DUNGEON runs in this browser (sim.js, a fixed 60 Hz deterministic step) and
// is drawn on a canvas (render.js). The server generated it and pre-rolled its
// drops; what the fight reports goes through client.js's queue, which is saved on
// the device before it is sent. Nothing here decides what an item IS — a pickup
// names a drop id, and the server mints the item it rolled for that drop.
//
// Route: /halcyon. No room segment — there is nothing to share a link to.
import { lazy, Suspense, useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../shared/theme.js";
import { lobbyCss, LobbyHeader, LobbyUser, LobbyLoading } from "../shared/lobby.jsx";
import { GAME_ACCENTS } from "../shared/accents.js";
import { makeClient } from "./client.js";
import { createSim, step, TPS, REACH, xpProgress, WEAPONS, statsFor, enchantValue, recoveryLimit, roomRegenMultiplier, CLASS_INFO, SPECIAL, isSpecial, lineLevel,
	STAT_SCALE, ABILITY_COST, ABILITY, SLOW_DURATION, SLOW_FACTOR, SLOW_PULSE,
	STARFALL_DELAY, STARFALL_RADIUS, STARFALL_RANGE, COUNTER_WINDOW, COUNTER_GUARD, POTION_HEAL, POTION_COOLDOWN, UNIQUE, EMBER } from "./sim.js";
import { camera, draw, drawTown, promptFor, formatRiftTime, TIER_COLORS, UNIQUE_COLOR } from "./render.js";
import { createTown, stepTown, setTownGear, postDps, STATIONS, SPAWN, standAt, REALMS } from "./town.js";
import { loadArt, setArtEnabled } from "./art.js";
import cssText from "./HalcyonRift.css?inline";

/* The art gallery (ArtGallery.jsx) is a dev-server page, /halcyon?art: the
 * production build drops the import with the branch. */
const ArtGallery = import.meta.env.DEV ? lazy(() => import("./ArtGallery.jsx")) : null;

const styles = baseCss + lobbyCss + cssText;
const ACCENT = { "--lby-accent": GAME_ACCENTS.halcyon };
const STEP_MS = 1000 / TPS;

const NAMES = { shortbow: "Shortbow", longbow: "Longbow", mace: "Mace", greatsword: "Greatsword",
	wand: "Wand", starstaff: "Starstaff", repeater: "Repeater", tidecaller: "Tidecaller",
	leather_vest: "Leather Vest", volley_quiver: "Volley Quiver", plate_armor: "Plate Armor",
	grounding_aegis: "Grounding Aegis", seer_robes: "Seer Robes", stillness_orb: "Stillness Orb",
	band_of_vigor: "Band of Vigor", band_of_focus: "Band of Focus", kingfisher_eye: "Kingfisher's Eye",
	star_tome: "Star Tome", shuriken: "Shuriken", kunai: "Kunai", shadow_garb: "Shadow Garb", mirror_charm: "Mirror Charm",
	dream_key: "Dream Key", boss_rush_key: "Boss Rush Key",
	ember_loop: "Ember Loop", misers_coil: "Miser's Coil", leechstone: "Leechstone", glass_ring: "Glass Ring",
	windrunner_cloak: "Windrunner's Cloak", full_moon_mantle: "Mantle of the Full Moon", thornplate: "Thornplate",
	duskmail: "Duskmail", gale_quiver: "Gale Quiver", oathhammer: "Oathhammer", anchor_orb: "Anchor Orb",
	comet_rod: "Comet Rod", echo_codex: "Codex of Echoes", chakram: "Ricochet Chakram", echo_charm: "Echo Charm",
	phoenix_feather: "Phoenix Feather", ash_sigil: "Ash Sigil", banked_coal: "Banked Coal", emberweave: "Emberweave",
	cinderguard: "Cinderguard", flare_bow: "Flare Bow", censer: "Censer", meteor_tome: "Meteor Tome", ember_kunai: "Ember Kunai" };
/* KEYS (owner's ask, 2026-11-18): carried in the bag, spent on entering. */
const KEY_TEXT = { dream_key: "Opens the Dream Rift for one practice run. Spent on entering.",
	boss_rush_key: "Lets you pick Boss Rush at a realm portal: every level is only its boss. Spent on entering; no time is recorded." };
const BOSS_RUSH = "boss_rush";
/* A run's modifiers in words (Boss Rush first: it is the run's shape), for the HUD
 * under the minimap and the game menu. */
const runModRows = (run) => !run ? [] : [
	...(run.dungeon?.boss_rush ? [{ id: BOSS_RUSH, name: run.bossRush?.name || "Boss Rush", text: run.bossRush?.text || "" }] : []),
	...(run.dungeon?.mods || []).map((id) => ({ id, name: run.modInfo?.[id]?.name || id, text: run.modInfo?.[id]?.text || "" }))];
// Every enchantment reads as flat points ("+4 Attack"), never a percentage.
const ENCHANT_NAMES = { max_hp: "Max HP", max_mp: "Max MP", attack: "Attack", defense: "Defense",
	attack_speed: "Dexterity", ability_power: "Ability power", mp_regen: "MP regen", hp_regen: "HP regen",
	fury: "Fury", glass_mind: "Glass Mind", fleetfoot: "Fleetfoot", kindling: "Kindling", second_wind: "Second Wind", bulwark: "Bulwark" };
const ROMAN = ["I", "II", "III", "IV"];
/* One line as a player reads it: "+5 Attack III", or a SPECIAL line's name, level and
 * what it does ("Fury III: +7 Attack, −3 Defense"). */
function lineText(e) {
	const v = enchantValue(e.id, e.q), lv = ROMAN[lineLevel(e.q) - 1];
	if (!isSpecial(e.id)) return `+${v} ${ENCHANT_NAMES[e.id] || e.id} ${lv}`;
	const what = {
		fury: `+${v} Attack, −${SPECIAL.fury.def} Defense`,
		glass_mind: `+${v} Ability power, −${SPECIAL.glass_mind.hp} HP`,
		fleetfoot: `+${v} Dexterity, −${SPECIAL.fleetfoot.hp} HP`,
		kindling: `after your ability, your next ${SPECIAL.kindling.shots} shots burn for ${v} a pulse`,
		second_wind: `a kill gives back ${v} MP (once a second)`,
		bulwark: `a hit gives +${v} Defense for ${SPECIAL.bulwark.last / TPS}s (every ${SPECIAL.bulwark.cooldown / TPS}s at most)`,
	}[e.id] || "";
	return `${ENCHANT_NAMES[e.id] || e.id} ${lv}: ${what}`;
}
/* ONE ORDER FOR EVERY STAT, on every item (owner's ask, 2026-11-18): two tooltips side
 * by side line up row for row. The base's stats (STAT_WORDS) and the enchantments
 * (ENCHANT_ORDER) follow the same sequence. */
const ENCHANT_ORDER = ["max_hp", "max_mp", "attack", "attack_speed", "defense", "ability_power", "hp_regen", "mp_regen",
	"fury", "glass_mind", "fleetfoot", "kindling", "second_wind", "bulwark"];
const byEnchantOrder = (a, b) => ENCHANT_ORDER.indexOf(a.id) - ENCHANT_ORDER.indexOf(b.id);
const sortedEnchants = (it) => [...(it.enchants || [])].sort(byEnchantOrder);
const SLOT_NAMES = { weapon: "Weapon", armor: "Armor", ability: "Ability", ring1: "Ring", ring2: "Ring" };
const FAMILY = { weapon: "Weapon", armor: "Armor", ability: "Ability", ring: "Ring", key: "Key" };
const ABBR = { shortbow: "SB", longbow: "LB", mace: "MC", greatsword: "GS", wand: "WD", starstaff: "SS",
	repeater: "RP", tidecaller: "TC", leather_vest: "LV", volley_quiver: "VQ", plate_armor: "PA",
	grounding_aegis: "GA", seer_robes: "SR", stillness_orb: "SO", band_of_vigor: "BV", band_of_focus: "BF",
	kingfisher_eye: "KE", star_tome: "ST", shuriken: "SH", kunai: "KN", shadow_garb: "SG", mirror_charm: "MR",
	dream_key: "DK", boss_rush_key: "BR",
	ember_loop: "EL", misers_coil: "MI", leechstone: "LS", glass_ring: "GR", windrunner_cloak: "WC",
	full_moon_mantle: "FM", thornplate: "TP", duskmail: "DM", gale_quiver: "GQ", oathhammer: "OH",
	anchor_orb: "AO", comet_rod: "CR", echo_codex: "EC", chakram: "CK", echo_charm: "EH",
	phoenix_feather: "PF", ash_sigil: "AS", banked_coal: "BC", emberweave: "EW", cinderguard: "CG",
	flare_bow: "FB", censer: "CE", meteor_tome: "MT", ember_kunai: "EK" };
const WEAPON_FEEL = { shortbow: "Fast and close: twin arrows that spread with distance.",
	longbow: "Slow and far: one heavy arrow.",
	mace: "Melee range: a quick, solid strike.", greatsword: "Short range: a heavy sweeping strike.",
	wand: "A steady bolt with medium range.", starstaff: "Long range: a heavy star that reaches eight tiles.",
	tidecaller: "Three arrows in a wide fan that glance off a wall once.",
	repeater: "A three-bolt burst, then a reload.",
	shuriken: "A spinning star with a short reach.",
	kunai: "A slow, heavy blade thrown hard and far.",
	oathhammer: "A mace whose every hit also strikes what stands beside its target.",
	comet_rod: "A slow bolt that bursts into shards where it lands.",
	chakram: "Flies out, turns back half way, and cuts through everything both ways.",
	flare_bow: "A steady bow whose every fourth shot is a flare that sets the ground burning.",
	ember_kunai: "A kunai that sticks where it hits and bursts a second later." };
/* Every item but a key says its tier; a UNIQUE is tiered too since 2026-11-19 (owner's
 * call), and is marked by its gold, not by a missing tier. */
const nameOf = (it) => (it.kind === "key" ? NAMES[it.base_id] || it.base_id : `${NAMES[it.base_id] || it.base_id} · T${it.tier}`);
const num = (x) => (Number.isInteger(x) ? String(x) : x.toFixed(1));
const classInfo = (id) => CLASS_INFO[id] || CLASS_INFO.ranger;
/* An item's class: none (any class), one id, or a list (shared armor, 2026-11-19). */
const classOk = (cls, id) => !cls || (Array.isArray(cls) ? cls.includes(id) : cls === id);
const classWords = (cls) => [].concat(cls).map((c) => CLASS_INFO[c]?.name || c).join(" or ");
const className = (id) => classInfo(id).name;

/* A weapon's numbers, one per line, off the sim's own (so they cannot drift). Range
 * lives here, not in the character's stats: it is the bow's, not the Ranger's. */
function weaponLines(it) {
	const w = WEAPONS[it.base_id];
	if (!w) return [];
	const s = statsFor([{ ...it, enchants: [] }]);
	const noun = { star: "star", blade: "blade" }[w.look] || "arrow";      // what the weapon throws
	return [w.burst > 1 ? `${w.burst}-bolt burst` : w.shots > 1 ? `${w.shots} ${noun}s a shot` : `1 ${noun} a shot`,
		`${s.weaponDmg} damage a ${noun}`, `${num(w.rate)} shots a second`, `Range ${w.range} tiles`,
		...(w.pierce ? [`Pierces ${w.pierce}`] : []), ...(w.bounce ? ["Bounces off a wall once"] : [])];
}

/* What an item's base gives, flat, worked out by the sim (what it adds to bare stats). */
const STAT_WORDS = [["maxHp", "Max HP"], ["maxMp", "Max MP"], ["att", "Attack"], ["dex", "Dexterity"],
	["def", "Defense"], ["ap", "Ability power"], ["hpRegen", "HP regen"], ["mpRegen", "MP regen"], ["abilityDmg", "Ability damage"], ["pierce", "Pierce"]];
function baseLines(it) {
	if (WEAPONS[it.base_id]) return [];
	const bare = statsFor([]), s = statsFor([{ ...it, enchants: [] }]);
	return STAT_WORDS.filter(([k]) => s[k] !== bare[k]).map(([k, w]) => `${s[k] > bare[k] ? "+" : "−"}${num(Math.abs(s[k] - bare[k]))} ${w}`);
}

/* What a UNIQUE does besides its stats, in words, off the sim's own numbers. */
function uniqueLines(it) {
	const s = statsFor([{ ...it, enchants: [] }]), secs = (t) => num(Math.round(t / TPS * 10) / 10), pct = (m) => `${Math.round((m - 1) * 100)}%`;
	const w = WEAPONS[it.base_id];
	switch (it.base_id) {
	case "ember_loop": return [`Weapon hits set enemies burning: ${s.burn} damage every ${secs(UNIQUE.burn.every)}s for ${secs(UNIQUE.burn.last)}s`, "A new hit restarts the burn; it never stacks"];
	case "misers_coil": return [`Abilities cost ${s.costCut} less MP`];
	case "leechstone": return [`Each kill heals ${s.leech} HP, up to your recovery limit`];
	case "windrunner_cloak": return [`Move ${pct(UNIQUE.windrunner)} faster`];
	case "full_moon_mantle": return [`While your MP is full, your shots do ${pct(UNIQUE.fullMoon)} more damage`];
	case "thornplate": return [`Each hit you take throws ${UNIQUE.thorns.n} shards outward for ${s.thorns} damage each`];
	case "duskmail": return [`A kill makes your next shot do ${pct(UNIQUE.dusk)} more damage`];
	case "oathhammer": return [`Each hit also does ${Math.round(UNIQUE.splash.share * 100)}% to enemies within ${UNIQUE.splash.r} tile of the target`];
	case "comet_rod": return [`Bursts into ${UNIQUE.comet.n} shards (${Math.round(UNIQUE.comet.share * 100)}% damage each) where it hits or ends`];
	case "chakram": return [`Turns back after ${num(w.range / 2)} tiles; passes through every enemy, both ways`];
	// the Ashen Breach's
	case "phoenix_feather": return ["Once each dungeon level, a hit that would kill you leaves you at 1 HP instead",
		`and sets the ground around you burning for ${secs(UNIQUE.phoenix.last)}s: ${s.phoenix} damage every ${secs(EMBER.every)}s to enemies in it`];
	case "ash_sigil": return [`An enemy that dies while burning explodes for ${s.ashSigil} damage to enemies within ${UNIQUE.ash.r} tiles`];
	case "banked_coal": return [`+1 Attack for every ${secs(UNIQUE.coal.every)}s you go without being hit, up to +${s.coalCap}`, "A hit starts it over"];
	case "emberweave": return [`Moving leaves a trail of fire behind you: ${s.trail} damage every ${secs(EMBER.every)}s to enemies in it`];
	case "cinderguard": return ["Burning ground does not hurt you", `+${s.cinderDef} Defense while you stand in it`];
	case "flare_bow": return [`Every ${w.flare}th shot is a flare: where it lands the ground burns for ${secs(UNIQUE.flare.last)}s`,
		`for ${Math.round(UNIQUE.flare.share * 100)}% of the shot's damage every ${secs(EMBER.every)}s, to enemies in it`];
	case "ember_kunai": return [`Sticks in what it hits, and bursts ${secs(UNIQUE.kunai.delay)}s later for ${Math.round(UNIQUE.kunai.share * 100)}% more damage`];
	default: return [];
	}
}

/* What an ability item DOES, at the Ability power the character has now (owner's ask,
 * 2026-11-18: AP is the ability's stat, as Attack is the weapon's). */
function abilityLines(it, ap = 0) {
	const s = statsFor([{ ...it, enchants: [] }]), pw = 1 + ap / STAT_SCALE, secs = (t) => num(Math.round(t / TPS * 10) / 10);
	const kind = s.abilityKind, cost = `Costs ${s.abilityCost ?? ABILITY_COST} MP`;
	const r2 = (x) => num(Math.round(x * 100) / 100);
	if (kind === "volley" && s.gale) return [`Space: one great arrow through every enemy in ${UNIQUE.gale.range} tiles`,
		`${Math.round(s.abilityDmg * pw)} damage to each enemy it passes`, cost];
	if (kind === "volley") return [`Space: a fan of ${s.arrows} arrows`, `${Math.round(s.abilityDmg * s.arrows * pw)} damage in all, shared by the arrows`, cost];
	if (kind === "slow") return [s.anchored ? "Space: a field where you stand that STAYS there, slowing enemy shots inside it" : "Space: a field around you that slows enemy shots inside it",
		`and burns enemies inside it for ${r2(s.abilityDmg * pw)} damage every ${secs(SLOW_PULSE)}s`,
		`${r2(s.slowRadius * pw)}-tile radius (its tier and Ability power widen it)`,
		`${Math.round((1 - (s.censer ? UNIQUE.censer.slow : SLOW_FACTOR)) * 100)}% slower, lasts ${secs(SLOW_DURATION)}s`,
		...(s.censer ? [`Burns ${UNIQUE.censer.burn}x as hard as a Stillness Orb, but slows shots less`] : []), cost];
	if (kind === "starfall") return [`Space: a star falls where you aim (up to ${STARFALL_RANGE} tiles)`,
		`Lands after ${secs(STARFALL_DELAY)}s, ${Math.round(s.abilityDmg * pw)} damage to all within ${STARFALL_RADIUS} tiles`,
		...(s.echo ? [`Lands again ${secs(UNIQUE.echo.delay)}s later for ${Math.round(s.abilityDmg * s.echo * pw)}`] : []),
		...(s.crater ? [`Leaves a burning crater for ${secs(UNIQUE.meteor.last)}s: ${Math.max(1, Math.round(s.abilityDmg * pw * UNIQUE.meteor.share))} damage every ${secs(EMBER.every)}s to enemies in it`] : []), cost];
	if (kind === "counter") return [`Space: the next hit within ${secs(COUNTER_WINDOW)}s is ignored`,
		`Then ${secs(COUNTER_GUARD)}s untouchable, and your next attack does ${r2(s.counterMult * pw)}x damage`,
		"A second counter before attacking does not stack",
		...(s.echoRing ? [`A caught hit also throws ${UNIQUE.echoRing.n} blades out around you for your weapon's damage`] : []),
		cost, `Cooldown ${secs(ABILITY.counter.cooldown)}s`];
	if (kind === "shield") return ["Space: plant a shield in front of you",
		`Blocks ${1 + Math.floor(ap / 8)} enemy shot${ap >= 8 ? "s" : ""}, lasts ${secs(s.shieldTime * pw)}s`, cost];
	return [];
}

// The three places an item can be in town, as the wire writes them.
const at = {
	vault: (i) => ["vault", i],
	inv: (c, i) => ["inventory", c, i],
	eq: (c, s) => ["equipped", c, s],
	floor: (c) => ["floor", c],                 // the town's ground under that character
};
const TOWN_FLOOR = "town:";
const onTownFloor = (it, charId) => it.loc === "ground" && it.run_id === TOWN_FLOOR + charId;
const keyOf = (to) => to.join(":");
function placeKey(it) {
	if (it.loc === "vault") return keyOf(at.vault(it.slot_index));
	if (it.loc === "inventory") return keyOf(at.inv(it.char_id, it.slot_index));
	if (it.loc === "equipped") return keyOf(at.eq(it.char_id, it.equip_slot));
	return null;
}

/* Where any town item is, as a place tuple; and an item put somewhere else (a version on). */
function placeOf(it) {
	if (it.loc === "ground" && String(it.run_id).startsWith(TOWN_FLOOR)) return at.floor(it.run_id.slice(TOWN_FLOOR.length));
	return it.loc === "vault" ? at.vault(it.slot_index) : placeAt_(it);
}
function putAt(it, to) {
	const [loc] = to;
	if (loc === "floor") return { ...it, loc: "ground", run_id: TOWN_FLOOR + to[1], char_id: null, slot_index: null,
		equip_slot: null, version: it.version + 1 };
	return { ...it, loc, version: it.version + 1, run_id: null,
		char_id: loc === "vault" ? null : to[1],
		slot_index: loc === "vault" ? to[1] : loc === "inventory" ? to[2] : null,
		equip_slot: loc === "equipped" ? to[2] : null };
}

/* Where an item on a character is, as a place tuple (the inverse of placeKey). */
function placeAt_(it) {
	return it.loc === "equipped" ? at.eq(it.char_id, it.equip_slot) : at.inv(it.char_id, it.slot_index);
}

/* SETTINGS (design §19.1), kept on this device: the keys, reduced flashing and the
 * interface size. `livePrefs` is what the fight's and the town's loops read on each
 * key and frame; the page's state is what the settings panel draws. */
const PREFS_KEY = "halcyon.prefs.v1";
export const ACTIONS = [
	["up", "Move up", ["KeyW"]], ["left", "Move left", ["KeyA"]], ["down", "Move down", ["KeyS"]], ["right", "Move right", ["KeyD"]],
	["ability", "Ability", ["Space", "KeyQ"]], ["interact", "Use / pick up", ["KeyE"]], ["potion", "Healing potion", ["KeyR"]],
	["takeAll", "Take all the loot here", ["KeyG"]], ["recall", "Recall to town", ["KeyF"]], ["auto", "Auto-fire on / off", ["KeyT"]],
	["drop", "Drop the item under the pointer", ["KeyX"]],
];
const DEFAULT_KEYS = Object.fromEntries(ACTIONS.map(([id, , k]) => [id, k]));
// Keys that are never rebound: Escape (the menu), the arrows (always move), 1-8 (the bag).
const FIXED_KEY = (code) => code === "Escape" || /^Arrow/.test(code) || /^(?:Digit|Numpad)[1-8]$/.test(code);
const UI_SIZES = [[0.9, "Small"], [1, "Normal"], [1.12, "Large"], [1.25, "Larger"]];
function loadPrefs() {
	let p = {};
	try { p = JSON.parse(localStorage.getItem(PREFS_KEY) || "{}") || {}; } catch { p = {}; }
	const keys = { ...DEFAULT_KEYS };
	for (const [id] of ACTIONS) if (Array.isArray(p.keys?.[id]) && p.keys[id].every((c) => typeof c === "string" && !FIXED_KEY(c))) keys[id] = p.keys[id];
	// auto-fire is never read back: every visit starts with it off (below)
	return { keys, calm: !!p.calm, ui: UI_SIZES.some(([v]) => v === p.ui) ? p.ui : 1,
		artStyle: p.artStyle === "greybox" ? "greybox" : "pixel", auto: false };
}
const livePrefs = { current: loadPrefs() };
/* AUTO-FIRE IS REMEMBERED FOR THE VISIT, NOT THE NEXT ONE (owner, 2026-11-18 and
 * 2026-11-19): it stays on across town and every run, but a fresh load of the game
 * starts with it off. So it is never written to storage; the loops read it live. */
function toggleAuto() {
	livePrefs.current = { ...livePrefs.current, auto: !livePrefs.current.auto };
	return livePrefs.current.auto;
}
const actionOf = (code) => ACTIONS.find(([id]) => livePrefs.current.keys[id]?.includes(code))?.[0] || null;
export function keyLabel(code) {
	if (!code) return "—";
	if (/^Key[A-Z]$/.test(code)) return code.slice(3);
	if (/^Digit\d$/.test(code)) return code.slice(5);
	const names = { Space: "Space", ShiftLeft: "Shift", ShiftRight: "Right Shift", ControlLeft: "Ctrl", ControlRight: "Right Ctrl",
		AltLeft: "Alt", AltRight: "Right Alt", Tab: "Tab", CapsLock: "Caps Lock", Enter: "Enter", Backquote: "`", Minus: "-", Equal: "=",
		BracketLeft: "[", BracketRight: "]", Semicolon: ";", Quote: "'", Comma: ",", Period: ".", Slash: "/", Backslash: "\\" };
	return names[code] || code.replace(/^Numpad/, "Num ");
}
const keysOf = (id) => (livePrefs.current.keys[id] || []).map(keyLabel).join(" · ") || "—";
/* Where the movement keys point, for both loops: the bound four, and the arrows always. */
const ARROWS = { ArrowUp: [0, -1], ArrowDown: [0, 1], ArrowLeft: [-1, 0], ArrowRight: [1, 0] };
const MOVE = { up: [0, -1], down: [0, 1], left: [-1, 0], right: [1, 0] };
const dirOf = (code) => ARROWS[code] || MOVE[actionOf(code)] || null;

/* The run's own model of the character's bag and equipment, owned OUTSIDE React so
 * the fight's loop can ask it synchronously (is there room? which slot does this
 * pickup go to?) on the tick the pickup happens. Every change is mirrored into the
 * page's state for drawing; `gear` is the equipment the fight takes on its next tick. */
function runControl(mine, charId, view, setRunItems) {
	const ctl = {
		items: mine.map((it) => ({ ...it })),
		gear: null,
		floor: new Map(),              // key -> the item, for what the player put down
		drops: [],                     // keys to put on the floor on the fight's next tick
		equipped: () => ctl.items.filter((it) => it.loc === "equipped"),
		room: () => ctl.items.filter((it) => it.loc === "inventory").length < view.limits.inventory,
		take(drop, spec) {
			const used = new Set(ctl.items.filter((it) => it.loc === "inventory").map((it) => it.slot_index));
			const slot = [...Array(view.limits.inventory).keys()].find((i) => !used.has(i));
			if (slot === undefined) return undefined;
			ctl.items = [...ctl.items, { ...spec, item_id: `drop:${drop}`, drop, fresh: true, char_id: charId,
				loc: "inventory", slot_index: slot, kind: view.bases[spec.base_id]?.kind || "standard" }];
			setRunItems(ctl.items);
			return slot;
		},
		freeSlot() {
			const used = new Set(ctl.items.filter((it) => it.loc === "inventory").map((it) => it.slot_index));
			return [...Array(view.limits.inventory).keys()].find((i) => !used.has(i));
		},
		drop(it) {
			ctl.items = ctl.items.filter((x) => x.item_id !== it.item_id);
			ctl.floor.set(it.item_id, it);
			ctl.drops.push(it.item_id);
			if (it.loc === "equipped") ctl.gear = ctl.equipped();
			setRunItems(ctl.items);
		},
		lift(key) {
			const it = ctl.floor.get(key), slot = ctl.freeSlot();
			if (!it || slot === undefined) return undefined;
			ctl.floor.delete(key);
			ctl.items = [...ctl.items, { ...it, loc: "inventory", slot_index: slot, equip_slot: null }];
			setRunItems(ctl.items);
			return slot;
		},
		move(it, to, other, back) {
			const put = (x, p) => ({ ...x, loc: p[0], equip_slot: p[0] === "equipped" ? p[2] : null,
				slot_index: p[0] === "inventory" ? p[2] : null });
			const gearBefore = it.loc === "equipped" || other?.loc === "equipped" || to[0] === "equipped";
			ctl.items = ctl.items.map((x) => (x.item_id === it.item_id ? put(x, to) : other && x.item_id === other.item_id ? put(x, back) : x));
			if (gearBefore) ctl.gear = ctl.equipped();
			setRunItems(ctl.items);
		},
	};
	return ctl;
}

export default function HalcyonRift(props) {
	const [gallery] = useState(() => !!ArtGallery && new URLSearchParams(window.location.search).has("art"));
	if (gallery) return <Suspense fallback={null}><style>{styles}</style><ArtGallery onExit={props.onExit} /></Suspense>;
	return <HalcyonGame {...props} />;
}

function HalcyonGame({ authUser, onExit }) {
	useEffect(() => { loadArt(); }, []);
	const client = useMemo(() => makeClient(authUser), [authUser?.id, authUser?.session_token]); // eslint-disable-line react-hooks/exhaustive-deps
	const [view, setView] = useState(null);
	const [error, setError] = useState(null);
	const [busy, setBusy] = useState(false);
	const [selChar, setSelChar] = useState(null);
	const [picked, setPicked] = useState(null);       // an item id, for click-to-move
	const [drag, setDrag] = useState(null);           // the item id being dragged
	const [tip, setTip] = useState(null);             // { item, rect }
	const [panel, setPanel] = useState(null);         // "vault" | "forge" | "dream" | null
	const [createSlot, setCreateSlot] = useState(null);
	const [forge, setForge] = useState([]);           // the item ids picked for fusion (at most two)
	const [forged, setForged] = useState(null);
	const [forgeTab, setForgeTab] = useState("reroll");   // "reroll" (one item) | "fuse" (two)
	const [keep, setKeep] = useState([]);                 // the reroll's locked lines, by index
	const [breaking, setBreaking] = useState(false);      // Break down asks twice
	const [near, setNear] = useState(null);
	const [run, setRun] = useState(null);
	// THE GAME MENU (owner's ask, 2026-11-18): Escape opens it over the town or the run
	// — the keys, Resume, and the way back to the main menu, which is the only screen
	// that wears the site's banner. NOTHING PAUSES under it (owner's call): the fight
	// goes on, and the keys still work.
	const [gameMenu, setGameMenu] = useState(false);
	// The portal deeper's offer, once the player walks into it: { offers, from, mods }.
	const [deeper, setDeeper] = useState(null);
	const [descending, setDescending] = useState(false);
	// The death screen (owner's ask, 2026-11-18): what killed you and what was lost,
	// before the main menu. The outcome of the run that ended.
	const [fallen, setFallen] = useState(null);
	const toMenuAfterRun = useRef(false);
	// During a run, this character's equipment and bag as the PAGE knows them: what it
	// carried in, what it picked up (named by drop until the server mints it), moved
	// wherever the player moved it. Kept until the town's refresh replaces it.
	const [runItems, setRunItems] = useState(null);
	// NOTIFICATIONS (owner's ask, 2026-11-18): a line in the top left that fades on its
	// own, kept in a log you can open again — never a banner you have to click away.
	const [notices, setNotices] = useState([]);
	const noticeId = useRef(0);
	const notify = useCallback((text, tone = "info", extra = null) => {
		const id = ++noticeId.current;
		setNotices((l) => [...l.slice(-49), { id, text, tone, at: Date.now(), ...(extra || {}) }]);
	}, []);
	// A run's summary, opened from its line in the log (never on its own: owner's call).
	const [report, setReport] = useState(null);
	const [graveyard, setGraveyard] = useState(false);
	const [settings, setSettings] = useState(false);
	const [prefs, setPrefsState] = useState(() => livePrefs.current);
	const setPrefs = useCallback((fn) => setPrefsState(() => {
		// From the LIVE prefs: auto-fire changes there without a render.
		const next = typeof fn === "function" ? fn(livePrefs.current) : fn;
		livePrefs.current = next;
		try { localStorage.setItem(PREFS_KEY, JSON.stringify(next)); } catch { /* kept for this visit only */ }
		return next;
	}), []);
	useLayoutEffect(() => {
		setArtEnabled(prefs.artStyle === "pixel");
		return () => setArtEnabled(true);
	}, [prefs.artStyle]);
	// THE INTERFACE SIZE scales every rem on the page; the page is the whole window,
	// so the root's font size is ours while it is mounted (and given back after).
	useEffect(() => {
		const root = document.documentElement, was = root.style.fontSize;
		root.style.fontSize = prefs.ui === 1 ? was : `${16 * prefs.ui}px`;
		return () => { root.style.fontSize = was; };
	}, [prefs.ui]);
	const [vaultQuery, setVaultQuery] = useState("");
	const [vaultFam, setVaultFam] = useState("");
	const [vaultUsable, setVaultUsable] = useState(false);
	const [flash, setFlash] = useState(null);         // an item id lit in the panel for a moment
	// THE MAIN MENU (owner's ask, 2026-11-18): where you make or pick a character,
	// and where a death sends you. The town is entered from it with one character.
	const [menu, setMenu] = useState(true);
	const townRef = useRef(null);
	if (!townRef.current) townRef.current = createTown();
	const floorAt = useRef(new Map());                 // item id -> where it was put down in town
	const townNotes = useRef([]);
	const [mods, setMods] = useState([]);             // the rift modifiers picked at a portal

	const refresh = useCallback(async () => {
		try {
			await client.flush();                       // a backlog from last visit goes first
			const v = await client.state();
			setView(v);
			setError(null);
			setSelChar((cur) => (v.characters.some((c) => c.char_id === cur) ? cur : v.characters[0]?.char_id || null));
			return v;
		} catch (e) {
			setError(e.message || "Could not reach the server.");
			return null;
		}
	}, [client]);
	useEffect(() => { refresh(); }, [refresh]);
	// Once the page is up, a failure is a notification; before, it is the page.
	useEffect(() => { if (error && view) { notify(error, "bad"); setError(null); } }, [error, view, notify]);

	// One heartbeat for the queue: during a run it delivers the fight's reports every
	// few seconds, and after one it keeps trying until the last of them has landed.
	useEffect(() => {
		const id = setInterval(() => { if (client.pendingRun()) client.flush(); }, 3000);
		const bye = () => client.flush({ keepalive: true });
		window.addEventListener("pagehide", bye);
		return () => { clearInterval(id); window.removeEventListener("pagehide", bye); };
	}, [client]);

	// Town moves are applied on the page at once and sent in order behind it (see
	// townMove); anything else waits for them, so it never acts on a stale version.
	const moveChain = useRef(Promise.resolve());
	const movesOut = useRef(0);
	const act = useCallback(async (fn) => {
		setBusy(true);
		let failed = null;
		try { await moveChain.current; await fn(); }
		catch (e) { failed = e.message || "That did not work."; }
		setBusy(false); setPicked(null);
		await refresh();
		// After the refresh, which clears it. The store's reasons are lower-case clauses.
		if (failed) setError(failed[0].toUpperCase() + failed.slice(1));
	}, [refresh]);

	const items = view?.items || [];
	const onChar = (it, id) => (it.loc === "inventory" || it.loc === "equipped") && it.char_id === id;
	// How many of a key the selected character carries in its bag (the only place a key counts).
	const carried = (baseId) => items.filter((it) => it.base_id === baseId && it.loc === "inventory" && it.char_id === char?.char_id).length;
	// (The roster is locked during a run, so the selected character IS the one in it.)
	const shown = useMemo(() => (runItems ? [...items.filter((it) => !onChar(it, selChar)), ...runItems] : items),
		[items, runItems, selChar]);
	const byPlace = useMemo(() => Object.fromEntries(shown.map((it) => [placeKey(it), it]).filter(([k]) => k)), [shown]);
	const byId = useMemo(() => Object.fromEntries(shown.map((it) => [it.item_id, it])), [shown]);
	const char = view?.characters.find((c) => c.char_id === selChar) || null;
	const locked = busy;

	// A picked item that has gone (fused, moved off the character) leaves the forge.
	useEffect(() => { setForge((f) => (f.every((id) => byId[id]) ? f : f.filter((id) => byId[id]))); }, [byId]);
	// Walking away from the vault or the forge closes it; leaving the forge drops its picks.
	useEffect(() => { if (panel && near !== panel) setPanel(null); }, [near, panel]);
	useEffect(() => { if (panel !== "forge") setForge([]); }, [panel]);
	useEffect(() => { setKeep([]); setBreaking(false); }, [forge[0], forgeTab]); // eslint-disable-line react-hooks/exhaustive-deps

	const chooseChar = (c) => {
		setPicked(null); setPanel(null);
		setSelChar(c.char_id);
		Object.assign(townRef.current.p, SPAWN);
		setMenu(false);
		// A run this character left open (a closed tab) ends as a recall now (§13.1a).
		if (view.open_runs[c.char_id]) act(() => client.openCharacter(c.char_id));
	};
	const newChar = (slot, classId) => act(async () => {
		const c = await client.createCharacter(slot, classId);
		setCreateSlot(null);
		setSelChar(c.char_id); setPanel(null);
		Object.assign(townRef.current.p, SPAWN);
		setMenu(false);
	});

	const enter = (realm, practice = false, picked = []) => {
		if (!char) { setMenu(true); return; }
		// Boss Rush is picked beside the modifiers but is not one: it is the run's shape.
		const bossRush = picked.includes(BOSS_RUSH), riftMods = picked.filter((m) => m !== BOSS_RUSH);
		act(async () => {
			await client.flush();
			if (client.pendingRun()) throw new Error("Your last run is still being saved. Try again in a moment.");
			const { run_id, dungeon, class_id, spent = [] } = await client.startRun(char.char_id, realm, practice, riftMods, bossRush);
			client.beginRun(run_id);
			// The keys the server spent on the way in are gone from the bag.
			if (spent.length) setView((v) => ({ ...v, items: v.items.filter((x) => !spent.includes(x.item_id)) }));
			if (bossRush) setMods((cur) => cur.filter((m) => m !== BOSS_RUSH));
			const ctl = runControl(items.filter((it) => onChar(it, char.char_id) && !spent.includes(it.item_id)), char.char_id, view, setRunItems);
			setPanel(null); setTip(null); setPicked(null);
			setRunItems(ctl.items);
			setRun({ run_id, dungeon, gear: ctl.equipped(), ctl, realm, bases: view.bases, practice,
				modInfo: Object.fromEntries((view.rift_mods || []).map((m) => [m.id, m])), bossRush: view.boss_rush,
				class_id: class_id || char.class_id,
				hero: { level: char.level, xp: char.xp, levels: view.levels, class_id: class_id || char.class_id, practice } });
		});
	};
	const enterRef = useRef(enter);
	enterRef.current = enter;
	const modsRef = useRef(mods);
	modsRef.current = mods;
	const panelRef = useRef(panel);
	panelRef.current = panel;

	const use = useCallback((station) => {
		// A portal opens its modifiers first; Enter (or E again) goes in.
		if (station.kind === "portal") {
			if (panelRef.current === station.id) enterRef.current(station.realm, false, modsRef.current);
			else setPanel(station.id);
			return;
		}
		if (station.kind === "dream") { setPanel("dream"); setForged(null); return; }
		setPanel((p) => (p === station.kind ? null : station.kind));
		setForged(null);
	}, []);

	/* Go deeper (design §14.6): everything the fight reported goes first, so the
	 * server has seen this level's boss fall; then the next level comes back and the
	 * run carries on in it — the same run, the same bag, HP and MP as they were. */
	const descend = async (mod) => {
		const r = run, from = deeper?.from;
		if (!r || descending || from == null) return;
		setDescending(true);
		try {
			await client.flush();
			if (client.pendingRun()) throw new Error("The fight is still being saved. Try again in a moment.");
			const { dungeon } = await client.descend(r.run_id, mod, from);
			const st = r.ctl.st;
			if (r.ctl.ended || !st || st.status !== "play") return;   // it ended while we asked
			r.ctl.floor.clear();                                    // what was put down stays behind
			r.ctl.ticksDone = (r.ctl.ticksDone || 0) + st.tick;     // the death screen's time in the rift
			setDeeper(null);
			setRun({ ...r, dungeon, gear: r.ctl.equipped(),
				hero: { ...r.hero, level: st.hero.level, xp: st.hero.xp },
				carry: { hp: st.p.hp, low: st.p.low, mp: st.p.mp } });
		} catch (e) {
			setError(e.message || "Could not go deeper.");
		} finally {
			setDescending(false);
		}
	};

	const endRun = useCallback((outcome) => {
		const t = townRef.current;
		Object.assign(t.p, standAt(`realm:${outcome.realm}`));    // back out of the portal you took
		setRun(null); setDeeper(null);
		setPicked(null); setDrag(null); setTip(null);
		const said = outcome.status === "dead" ? null : outcomeNotice(outcome);   // a death has its own screen
		if (said) notify(...said, { runId: outcome.runId });
		// The run's lines in the log (its clears, its return) now open its summary.
		if (outcome.status !== "dead") setTimeout(() => setNotices((l) => l.map((n) => (n.runId === outcome.runId ? { ...n, report: outcome } : n))), 0);
		// The XP the fight already showed stays on screen until the server's copy lands.
		if (outcome.status !== "dead" && !outcome.practice) setView((v) => v && ({ ...v, characters: v.characters.map((c) =>
			c.char_id === selChar ? { ...c, xp: Math.max(c.xp, outcome.heroXp), level: Math.max(c.level, outcome.level) } : c) }));
		if (outcome.status === "dead") setFallen(outcome);        // the death screen; it goes on to the menu
		if (toMenuAfterRun.current) { toMenuAfterRun.current = false; setMenu(true); }
		// The town's copy replaces the run's once it has landed — unless a new run began meanwhile.
		refresh().then(() => setRunItems((cur) => (cur === outcome.items ? null : cur)));
	}, [refresh, selChar, notify]);

	// A town move lands on the page in the same frame: the item and whatever it
	// swaps with change places, each one version on (the server bumps both by one,
	// so the next move in a quick series names the version it will find). Requests
	// go one at a time, in order; once the last has answered, the server's state is
	// read back — a refusal shows its reason and that read puts things back.
	const sendMoves = (moves) => {
		let failed = false;
		for (const [id, to, version] of moves) {
			movesOut.current += 1;
			moveChain.current = moveChain.current
				.then(() => (failed ? null : client.move(id, to, version)))
				.catch((e) => { failed = true; const m = e.message || "That did not work."; setError(m[0].toUpperCase() + m.slice(1)); })
				.then(async () => {
					if ((movesOut.current -= 1) > 0) return;
					try {
						const v = await client.state();
						if (movesOut.current === 0) setView(v);   // a move made meanwhile reads back after itself
					} catch { /* the next refresh will do */ }
				});
		}
	};
	const townMove = (it, to) => {
		const from = placeOf(it), there = byPlace[keyOf(to)];
		setView((v) => ({ ...v, items: v.items.map((x) => (x.item_id === it.item_id ? putAt(x, to)
			: there && x.item_id === there.item_id ? putAt(x, from) : x)) }));
		sendMoves([[it.item_id, to, it.version]]);
	};

	// SORT (owner's ask, 2026-11-18): the bag by kind (weapon, armor, ability, ring),
	// uniques first, then tier and slots, highest first. A LOCKED item keeps its slot
	// and the rest sort around it. In town it is a series of swaps worked out here and
	// sent in order; in a run, the run's own moves. The vault sorts the same way.
	const sortKey = (it) => [{ weapon: 0, armor: 1, ability: 2, ring: 3, key: 4 }[view.bases[it.base_id]?.slot] ?? 9, it.kind === "unique" ? 0 : 1,
		-(it.tier || 0), -(it.slot_count || 0), NAMES[it.base_id] || it.base_id, String(it.item_id)];
	const cmpItems = (a, b) => { const x = sortKey(a), y = sortKey(b); for (let i = 0; i < x.length; i++) if (x[i] !== y[i]) return x[i] < y[i] ? -1 : 1; return 0; };
	/* Where each item should go: `list` the items, `n` the slots; locked items stay. */
	const sortPlan = (list, n) => {
		const fixed = new Set(list.filter((it) => it.locked).map((it) => it.slot_index));
		const free = [...Array(n).keys()].filter((i) => !fixed.has(i));
		const want = list.filter((it) => !it.locked).sort(cmpItems);
		return want.map((it, k) => [it, free[k]]);
	};
	const sortPlaces = (list, n, placeFor, what) => {
		const plan = sortPlan(list, n);
		if (plan.every(([it, i]) => it.slot_index === i)) { notify(`Your ${what} is already sorted.`); return; }
		const local = Object.fromEntries(list.map((it) => [it.item_id, { ...it }]));
		const bySlot = new Map(list.map((it) => [it.slot_index, it.item_id]));
		const moves = [];
		for (const [w, i] of plan) {
			const me = local[w.item_id];
			if (me.slot_index === i) continue;
			const from = me.slot_index, other = bySlot.get(i);
			moves.push([me.item_id, placeFor(i), me.version]);
			me.version += 1; me.slot_index = i; bySlot.set(i, me.item_id);
			if (other) { local[other].version += 1; local[other].slot_index = from; bySlot.set(from, other); } else bySlot.delete(from);
		}
		setView((v) => ({ ...v, items: v.items.map((x) => local[x.item_id] || x) }));
		sendMoves(moves);
	};
	const sortBag = () => {
		if (!char || busy) return;
		const bag = [...Array(view.limits.inventory).keys()].map(invItem).filter(Boolean);
		if (run) {
			const plan = sortPlan(bag, view.limits.inventory);
			if (plan.every(([it, i]) => it.slot_index === i)) { notify("Your bag is already sorted."); return; }
			for (const [w, i] of plan) {
				const cur = run.ctl.items.find((x) => x.item_id === w.item_id);
				if (cur && cur.slot_index !== i) runMove(cur, at.inv(char.char_id, i));
			}
			return;
		}
		sortPlaces(bag, view.limits.inventory, (i) => at.inv(char.char_id, i), "bag");
	};
	const sortVault = () => {
		if (busy || run) return;
		sortPlaces(items.filter((it) => it.loc === "vault"), view.limits.vault, (i) => at.vault(i), "vault");
	};

	/* LOCK (design §19.1): right-click an item. It changes nothing about where the
	 * item is, so the page shows it at once and the server is told behind it. */
	const toggleLock = (it) => {
		if (!it || it.fresh && !run) return;
		const locked = !it.locked, flip = (x) => (x.item_id === it.item_id ? { ...x, locked } : x);
		setView((v) => ({ ...v, items: v.items.map(flip) }));
		if (run) { run.ctl.items = run.ctl.items.map(flip); setRunItems(run.ctl.items); }
		setTip((t) => (t && t.item.item_id === it.item_id ? { ...t, item: { ...t.item, locked } } : t));
		// An item found this run has no id on the server yet: its lock rides the run's
		// events, naming the drop, and lands with the pickup before it.
		if (it.fresh) client.report({ type: "lock", drop: it.drop, locked });
		else client.lock(it.item_id, locked).catch((e) => { setError(e.message || "Could not lock that."); refresh(); });
	};

	// ── moving items: drag and drop, or click one and then click where it goes ──
	const fits = (it, to) => {
		if (to[0] !== "equipped") return true;
		const b = view.bases[it.base_id];
		return !!b && classOk(b.cls, char?.class_id)
			&& (b.slot === to[2] || (b.slot === "ring" && to[2].startsWith("ring")));
	};
	/* Why an item does not go in a place, in words (owner's ask, 2026-11-19: "does not
	 * go there" said nothing). The class first: that is the one a player cannot see. */
	const whyNot = (it, to) => {
		const b = view.bases[it.base_id], cls = b?.cls;
		if (!classOk(cls, char?.class_id))
			return `Only a ${classWords(cls)} can use ${nameOf(it)}; this is a ${CLASS_INFO[char?.class_id]?.name || "different class"}.`;
		if (b?.slot === "key") return `${nameOf(it)} is carried, not worn.`;
		return `${nameOf(it)} goes in ${b?.slot === "ring" ? "a ring" : `the ${b?.slot || "right"}`} slot.`;
	};
	// Something the open character could put on: a worn slot, and its class (or any).
	const usable = (it) => {
		const b = view.bases[it.base_id];
		return !!b && b.slot !== "key" && classOk(b.cls, char?.class_id);
	};
	const accepts = (target, it) => (target.kind === "place" ? fits(it, target.to) : true);
	// Mid-run, a move is a run EVENT (queued with the fight's reports, so it lands after
	// the pickup that minted the item) and the fight takes the new gear on its next tick.
	const runMove = (it, to) => {
		const ctl = run.ctl, here = placeAt_(it);
		if (ctl.ended) return;                         // the run is closed; the server takes nothing more
		if (keyOf(here) === keyOf(to)) return;
		const other = ctl.items.find((x) => placeKey(x) === keyOf(to));
		if (!fits(it, to) || (other && !fits(other, here))) { const bad = other && fits(it, to) ? other : it; notify(whyNot(bad, bad === it ? to : here), "bad"); return; }
		ctl.move(it, to, other, here);
		client.report({ type: "move", ...(it.fresh ? { drop: it.drop } : { item: it.item_id }), to: [to[0], to[2]] });
	};
	// Mid-run, an item can be put on the floor at the Ranger's feet: the bin's place
	// in a run, or anywhere on the stage. E picks it back up; the run's end takes
	// whatever is still lying there (the server destroys it, design §19).
	const runDrop = (it) => {
		const ctl = run.ctl;
		if (ctl.ended || !ctl.items.some((x) => x.item_id === it.item_id)) return;
		if (run.practice) { notify("Nothing can be dropped in a Dream Rift.", "bad"); return; }   // the store refuses it too
		if (it.locked) { notify(`${nameOf(it)} is locked. Right-click it to unlock.`, "bad"); return; }
		ctl.drop(it);
		client.report({ type: "drop_item", ...(it.fresh ? { drop: it.drop } : { item: it.item_id }) });
	};
	const placeAt = (target, it) => {
		if (!it) return;
		if (run) {
			if (target.kind === "place" && target.to[0] !== "vault") runMove(it, target.to);
			else if (target.kind === "trash") runDrop(it);
			setPicked(null);
			return;
		}
		if (it.fresh) return;
		if (target.kind === "place") {
			if (placeKey(it) === keyOf(target.to)) { setPicked(null); return; }
			const other = byPlace[keyOf(target.to)];
			if (!fits(it, target.to) || (other && it.loc === "equipped" && !fits(other, placeAt_(it)))) {
				const bad = fits(it, target.to) ? other : it; setError(whyNot(bad, bad === it ? target.to : placeAt_(it))); setPicked(null); return;
			}
			townMove(it, target.to);
		} else if (target.kind === "trash") {
			// IN TOWN TOO, DROPPING PUTS IT ON THE GROUND (owner's ask, 2026-11-18): at the
			// player's feet, where E picks it up again, until the character leaves town.
			if (it.locked) notify(`${nameOf(it)} is locked. Right-click it to unlock.`, "bad");
			else if (char) {
				const p = townRef.current.p;
				floorAt.current.set(it.item_id, { x: p.x, y: p.y });
				townMove(it, at.floor(char.char_id));
				notify(`Dropped ${nameOf(it)}. It is gone when you leave town.`);
			}
		}
		setPicked(null);
	};
	const firstFreePlace = (toVault = false) => {
		const limit = toVault ? view.limits.vault : view.limits.inventory;
		for (let i = 0; i < limit; i++) {
			const to = toVault ? at.vault(i) : at.inv(char.char_id, i);
			if (!byPlace[keyOf(to)]) return to;
		}
		notify(toVault ? "Your vault is full." : "Your bag is full.", "bad");
		return null;
	};
	// Where a double click or a number key sends an item: from the bag, onto the
	// slot it fits (a ring: the empty ring slot, else the first), swapping whatever
	// is there; from the equipment or the vault, into the first empty bag slot.
	const quickTo = (it) => {
		if (!char || !it) return null;
		if (it.loc === "inventory") {
			const fam = view.bases[it.base_id]?.slot;
			const slot = fam !== "ring" ? fam : !byPlace[keyOf(at.eq(char.char_id, "ring1"))] ? "ring1"
				: !byPlace[keyOf(at.eq(char.char_id, "ring2"))] ? "ring2" : "ring1";
			return slot ? at.eq(char.char_id, slot) : null;
		}
		return firstFreePlace();
	};
	const quick = (it) => {
		if (!it || busy || panel === "forge") return;
		const to = quickTo(it);
		if (to) placeAt({ kind: "place", to }, it);
	};
	const quickRef = useRef(null);
	quickRef.current = (i) => !menu && char && quick(byPlace[keyOf(at.inv(char.char_id, i))]);
	// Escape: close what is open (a tooltip, a station's panel, a question), else the game menu.
	const escRef = useRef(null);
	escRef.current = () => {
		if (fallen) return;                         // the death screen is left by its own button
		if (menu && !run && !report && !graveyard && !settings) return;
		if (tip) { setTip(null); return; }
		if (report) { setReport(null); return; }
		if (graveyard) { setGraveyard(false); return; }
		if (settings) { setSettings(false); return; }
		if (gameMenu) { setGameMenu(false); return; }
		if (deeper) { setDeeper(null); return; }
		if (panel && !run) { setPanel(null); return; }
		setGameMenu(true);
	};
	useEffect(() => {
		const onKey = (e) => {
			if (e.code !== "Escape" || e.repeat || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "")) return;
			e.preventDefault();
			escRef.current();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);
	useEffect(() => { if (menu) setGameMenu(false); }, [menu]);
	const toMainMenu = () => {
		setGameMenu(false); setPanel(null); setTip(null); setPicked(null);
		if (run) { toMenuAfterRun.current = true; run.ctl.recall = true; return; }   // leave the rift first
		// Leaving town: what lies on its ground is gone (the server clears it).
		if (char && items.some((it) => onTownFloor(it, char.char_id))) {
			setView((v) => ({ ...v, items: v.items.filter((it) => !onTownFloor(it, char.char_id)) }));
			client.leaveTown(char.char_id).catch(() => { /* opening the character clears it too */ });
		}
		setMenu(true);
	};
	// THE DROP KEY (owner's ask, 2026-11-18: dropping should be easier): the item under
	// the pointer goes on the ground, in town or in a run.
	const tipRef = useRef(tip);
	tipRef.current = tip;
	const dropKeyRef = useRef(null);
	dropKeyRef.current = () => {
		const it = tipRef.current?.item;
		if (!it || busy || it.fresh && !run || String(it.item_id).startsWith("drop:") && !run) return;
		const mine = run ? run.ctl.items.some((x) => x.item_id === it.item_id) : items.some((x) => x.item_id === it.item_id && x.loc !== "ground");
		if (!mine) return;
		setTip(null);
		placeAt({ kind: "trash" }, it);
	};
	useEffect(() => {
		const onKey = (e) => {
			if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "")) return;
			if (actionOf(e.code) === "drop") { e.preventDefault(); dropKeyRef.current(); }
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);
	// The number keys 1-8 put the matching bag slot's item on (in town and in a run).
	useEffect(() => {
		const onKey = (e) => {
			if (e.repeat || e.ctrlKey || e.metaKey || e.altKey || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "")) return;
			const m = /^(?:Digit|Numpad)([1-8])$/.exec(e.code);
			if (m) { e.preventDefault(); quickRef.current(Number(m[1]) - 1); }
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);
	// At the forge a click PICKS an item for fusion (it stays where it is, lit).
	const forgePick = (it) => {
		if (it.locked && !forge.includes(it.item_id)) { notify(`${nameOf(it)} is locked. Right-click it to unlock.`, "bad"); return; }
		if (it.kind === "key") { notify("Keys cannot be forged.", "bad"); return; }
		if (forged) setForged(null);
		const most = forgeTab === "fuse" ? 2 : 1;
		setForge((f) => (f.includes(it.item_id) ? f.filter((id) => id !== it.item_id) : [...f, it.item_id].slice(-most)));
	};
	const vaultOpen = panel === "vault" && !run;
	const slotCtx = {
		bases: view?.bases || {}, picked, drag, flash, dragItem: drag ? byId[drag] : null, accepts, inRun: !!run, forge, quick, vaultOpen,
		startDrag: (it) => { setDrag(it.item_id); setTip(null); },
		endDrag: () => setDrag(null),
		dropAt: (target) => placeAt(target, byId[drag]),
		clickAt: (target, it, shift) => {
			if (shift && vaultOpen && (it?.loc === "inventory" || it?.loc === "vault")) {
				if (busy || !char) return;
				const to = firstFreePlace(it.loc === "inventory");
				if (to) { placeAt({ kind: "place", to }, it); setTip(null); }
				return;
			}
			if (panel === "forge" && !run && target.to?.[0] !== "vault") { if (it) forgePick(it); return; }
			const held = picked ? byId[picked] : null;
			if (!held) { if (it && (run || !it.fresh)) setPicked(it.item_id); return; }
			if (it && it.item_id === held.item_id) { setPicked(null); return; }
			placeAt(target, held);
		},
		showTip: (it, el, canLock) => { if (!drag) setTip({ item: it, rect: el.getBoundingClientRect(), canLock }); },
		lock: toggleLock,
		hideTip: () => setTip(null),
	};

	const header = <LobbyHeader onBack={run ? null : menu ? onExit : () => { setPanel(null); setMenu(true); }}
		title={run ? run.dungeon.name : "Halcyon Rift"} user={<LobbyUser user={authUser} profile={!run} />} />;

	if (!view) {
		return (
			<div className="app halcyon fg-table" style={ACCENT}><style>{styles}</style>
				{header}
				{error ? <div className="hr-error-page fg-panel"><p>{error}</p>
					<button className="btn btn-gold" onClick={refresh}>Try again</button></div>
					: <LobbyLoading label="Connecting…" />}
			</div>
		);
	}

	const slots = [...Array(view.limits.characters).keys()];
	const [fa, fb] = [byId[forge[0]] || null, byId[forge[1]] || null];
	const fusable = fa && fb && fa.base_id === fb.base_id;
	const shards = view.shards ?? 0;
	// The reroll's price, as the store works it out (content.reroll_cost): special lines are always kept.
	const rr = view.odds?.reroll || { base: 8, per_tier: 2, per_slot: 6 };
	const kept = fa ? new Set([...keep, ...(fa.enchants || []).map((e, i) => (isSpecial(e.id) ? i : -1)).filter((i) => i >= 0)]) : new Set();
	const rerollCost = fa ? (rr.base + rr.per_tier * Math.max(0, fa.tier) + rr.per_slot * fa.slot_count) * 2 ** kept.size : 0;
	const canReroll = fa && (fa.enchants || []).length > kept.size && shards >= rerollCost;
	const salvageValue = fa ? 2 + 2 * Math.max(0, fa.tier) + 4 * fa.slot_count : 0;
	const reroll = () => act(async () => {
		const out = await client.reroll(fa.item_id, [...keep].sort(), fa.version);
		setFlash(out.item_id);
		setTimeout(() => setFlash((f) => (f === out.item_id ? null : f)), 1400);
	});
	const breakDown = () => {
		if (!breaking) { setBreaking(true); return; }
		const it = fa;
		act(async () => {
			const out = await client.salvage(it.item_id, it.version);
			setForge([]);
			notify(`${nameOf(it)} broke down into ${out.gained} shards.`);
		});
	};
	const fuse = () => act(async () => {
		const made = await client.fuse(fa.item_id, fb.item_id);
		setForged({ item: made, a: fa, b: fb });
		setForge([]);
		setFlash(made.item_id);
		setTimeout(() => setFlash((f) => (f === made.item_id ? null : f)), 2600);
	});
	const invItem = (i) => (char ? byPlace[keyOf(at.inv(char.char_id, i))] : null);
	// What lies on the town's ground, and picking it up (E beside it): into the first
	// empty bag slot.
	const townFloor = char ? items.filter((it) => onTownFloor(it, char.char_id)) : [];
	const liftFromFloor = (itemId) => {
		const it = items.find((x) => x.item_id === itemId);
		if (!it || !char || busy) return;
		const free = [...Array(view.limits.inventory).keys()].find((i) => !byPlace[keyOf(at.inv(char.char_id, i))]);
		if (free === undefined) { notify("Your bag is full.", "bad"); return; }
		floorAt.current.delete(itemId);
		townMove(it, at.inv(char.char_id, free));
		if (it.kind === "unique") notify(`Picked up ${nameOf(it)}`, "unique");   // only a unique is worth a line
	};
	// The vault's search and filter dim what does not match; nothing moves.
	const vaultMatch = (it) => {
		const fam = view.bases[it.base_id]?.slot;
		if (vaultFam === "unique" ? it.kind !== "unique" : vaultFam && fam !== vaultFam) return false;
		if (vaultUsable && !usable(it)) return false;
		const q = vaultQuery.trim().toLowerCase();
		if (!q) return true;
		const words = [nameOf(it), FAMILY[fam] || "", it.kind === "unique" ? `unique tier ${it.tier}` : `tier ${it.tier}`,
			...(it.enchants || []).map((e) => ENCHANT_NAMES[e.id] || e.id)].join(" ").toLowerCase();
		return q.split(/\s+/).every((w) => words.includes(w));
	};
	const equipped = char ? view.limits.equip.map((s) => byPlace[keyOf(at.eq(char.char_id, s))]).filter(Boolean) : [];
	const stats = char ? statsFor(equipped, char.level, char.class_id) : null;
	// What a hovered item is set beside: what is worn in its slot (both rings for a ring).
	const compareFor = (it) => {
		if (!char || !it || it.loc === "equipped" || String(it.item_id).startsWith("grave:")) return [];
		const fam = view.bases[it.base_id]?.slot;
		return fam ? equipped.filter((e) => e.item_id !== it.item_id && (fam === "ring" ? e.equip_slot?.startsWith("ring") : e.equip_slot === fam)) : [];
	};
	const reportView = report && (
		<div className="hr-report-scrim">
			<RunReport r={report} equip={view.limits.equip} ctx={{ ...slotCtx, lock: null }} overlay doneLabel="Close" onDone={() => { setReport(null); setTip(null); }} />
		</div>);

	if (fallen && !run && !report) {
		const gear = fallen.items.filter((it) => it.loc === "equipped");
		const done = () => { const r = fallen; setFallen(null); setTip(null); if (!r.practice) setMenu(true); };
		return (
			<div className="app halcyon fg-table hr-playing" style={ACCENT}><style>{styles}</style>
				<main className="hr-death-page">
					<RunReport r={fallen} equip={view.limits.equip} ctx={{ ...slotCtx, lock: null }} onDone={done} />
				</main>
				{tip && <ItemTip tip={{ ...tip, canLock: false }} bases={view.bases} ap={statsFor(gear, fallen.level, fallen.classId).ap} classId={fallen.classId} />}
			</div>
		);
	}

	if (menu && !run) {
		return (
			<div className="app halcyon fg-table" style={ACCENT}><style>{styles}</style>
				{header}
				<main className="hr-menu">
					<h1 className="hr-menu-title">Halcyon Rift</h1>
					<p className="hr-hint">{view.characters.length ? "Choose a character, or make a new one." : "Make a character to begin."}</p>
					<Notices list={notices} onReport={(r) => { setReport(r); setTip(null); }} />
					<div className="hr-menu-cards" role="group" aria-label="Characters">
						{slots.map((s) => {
							const c = view.characters.find((x) => x.slot === s);
							if (!c) return (
								<button key={s} className={"hr-menu-card hr-menu-new" + (createSlot === s ? " sel" : "")} disabled={busy}
									onClick={() => setCreateSlot((cur) => (cur === s ? null : s))}>
									<span className="hr-menu-plus" aria-hidden="true">+</span>
									<span>New character</span>
								</button>);
							const weapon = items.find((it) => it.char_id === c.char_id && it.loc === "equipped" && it.equip_slot === "weapon");
							return (
								<button key={s} className={`hr-menu-card hr-class-${c.class_id}`} disabled={busy} onClick={() => chooseChar(c)}
									aria-label={`${className(c.class_id)}, level ${c.level}`}>
									<span className="hr-char-glyph hr-menu-glyph" aria-hidden="true" />
									<span className="hr-char-name">{className(c.class_id)}</span>
									<span className="fg-label-soft">Level {c.level}</span>
									<XpBar levels={view.levels} xp={c.xp} />
									<span className="hr-menu-weapon">{weapon ? nameOf(weapon) : "No weapon"}</span>
								</button>);
						})}
					</div>
					{createSlot !== null && (
						<section className="hr-character-menu fg-panel" aria-label="New character">
							<p className="hr-hint">Choose a class. A character keeps its class forever.</p>
							<div className="hr-class-options">
								{Object.entries(CLASS_INFO).map(([id, info]) => <button key={id} className={`hr-class-option hr-class-${id}`}
									disabled={busy} onClick={() => newChar(createSlot, id)}>
									<strong>{info.name}</strong><span>{info.description}</span>
								</button>)}
							</div>
						</section>)}
					<div className="hr-menu-foot">
						<button className="btn btn-ghost btn-sm" onClick={() => setSettings(true)}>Settings</button>
						{view.best_level > 0 && <span className="hr-best">Best level reached: <strong>{view.best_level}</strong></span>}
						{(view.fallen_count ?? view.fallen.length) > 0 && <button className="btn btn-ghost btn-sm" onClick={() => setGraveyard(true)}>
							Graveyard ({view.fallen_count ?? view.fallen.length})</button>}
					</div>
					{graveyard && <Graveyard fallen={view.fallen} count={view.fallen_count ?? view.fallen.length}
						onOpen={(c) => { const r = reportOfFallen(c); if (r) { setReport(r); setGraveyard(false); } }}
						onClose={() => setGraveyard(false)} />}
					{settings && <Settings prefs={prefs} setPrefs={setPrefs} onClose={() => setSettings(false)} />}
					{reportView}
				</main>
				{tip && <ItemTip tip={{ ...tip, canLock: false }} bases={view.bases} ap={0} />}
			</div>
		);
	}

	return (
		<div className={"app halcyon fg-table hr-playing" + (run ? " hr-in-run" : "")} style={ACCENT}><style>{styles}</style>
			<main className="hr-main">
				<section className="hr-stage" aria-label={run ? run.dungeon.name : "The town"}
					data-near={near || ""} data-panel={panel || ""}
					onDragOver={(e) => { if (drag && !busy) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
					onDrop={(e) => { if (drag && !busy && !e.defaultPrevented) { e.preventDefault(); slotCtx.dropAt({ kind: "trash" }); setDrag(null); } }}>
					<div className="hr-view">
						{run
							? <Dungeon run={run} client={client} onEnd={endRun} notify={notify} tips={slotCtx} onDeeper={setDeeper} />
							: <Town st={townRef.current} notes={townNotes} ready={!!char && !busy} gear={equipped} level={char?.level || 1}
								classId={char?.class_id || "ranger"} floor={townFloor} floorAt={floorAt.current}
								onUse={use} onNear={setNear} onLift={liftFromFloor} />}

						<button className="hr-menu-btn" onClick={(e) => { e.currentTarget.blur(); setGameMenu((m) => !m); }}
							aria-expanded={gameMenu} title="Menu (Esc)"><span aria-hidden="true">☰</span> Menu <kbd>Esc</kbd></button>
						{run && deeper && !gameMenu && (() => {
							const names = Object.fromEntries((view.rift_mods || []).map((m) => [m.id, m]));
							// The next level's bonus: every modifier, plus each level past the first.
							const r = deeper.mods.length + 1, rule = lootRule(view);
							const plus = (x) => `+${Math.round(x * 100)}%`;
							return (
								<Overlay title={`Deeper: level ${deeper.from + 1}`} onClose={() => setDeeper(null)} className="hr-deeper-panel">
									<p className="hr-hint">Pick one modifier to add. It stays for the rest of this run, and every
										modifier makes the loot better. Recall is the only way out.</p>
									<div className="hr-mods hr-mods-3" role="group" aria-label="Pick a modifier">
										{deeper.offers.map((id) => (
											<button key={id} className="hr-mod" disabled={descending} onClick={() => descend(id)}>
												<strong>{names[id]?.name || id}</strong><span>{names[id]?.text}</span></button>))}
									</div>
									{deeper.mods.length > 0 && <p className="hr-hint">This run: {deeper.mods.map((m) => names[m]?.name || m).join(", ")}</p>}
									<dl className="hr-mod-sum">
										<div><dt>Loot</dt><dd>{plus(rule.per_mod * r + rule.per_level * deeper.from)}</dd></div>
										<div><dt>XP</dt><dd>{plus(rule.xp_per_mod * r)}</dd></div>
									</dl>
									{descending && <p className="hr-hint" role="status">Descending…</p>}
								</Overlay>);
						})()}
						{gameMenu && !settings && <GameMenu inRun={!!run} practice={!!run?.practice} mods={runModRows(run)}
							onSettings={() => setSettings(true)}
							onResume={() => setGameMenu(false)}
							onRecall={() => { setGameMenu(false); run.ctl.recall = true; }}
							onMainMenu={toMainMenu} />}
						{settings && <Settings prefs={prefs} setPrefs={setPrefs} onClose={() => setSettings(false)} />}
						{reportView}

						<Notices list={notices} onReport={(r) => { setReport(r); setTip(null); }} />

						{vaultOpen && (
							<Overlay title="Vault" onClose={() => setPanel(null)} className="hr-vault">
								<p className="hr-hint">Shift-click an item to move it between your bag and the shared vault.</p>
								<div className="hr-vault-tools">
									<input className="hr-vault-search" type="search" placeholder="Search: name or enchantment" value={vaultQuery}
										aria-label="Search the vault" onChange={(e) => setVaultQuery(e.target.value)} />
									<div className="hr-vault-fams" role="group" aria-label="Show only">
										{[["", "All"], ["weapon", "Weapons"], ["armor", "Armor"], ["ability", "Abilities"], ["ring", "Rings"], ["key", "Keys"], ["unique", "Uniques"]].map(([f, label]) =>
											<button key={f || "all"} className={"hr-chip" + (vaultFam === f ? " on" : "")} aria-pressed={vaultFam === f}
												onClick={() => setVaultFam(f)}>{label}</button>)}
										<button className={"hr-chip hr-chip-usable" + (vaultUsable ? " on" : "")} aria-pressed={vaultUsable}
											title={`What this ${CLASS_INFO[char?.class_id]?.name || "character"} can equip`}
											onClick={() => setVaultUsable((u) => !u)}>Equippable</button>
									</div>
									<button className="btn btn-ghost btn-sm" disabled={locked} onClick={sortVault} title="Weapons, armor, abilities, rings; best first. Locked items stay put.">Sort</button>
								</div>
								<div className="hr-grid hr-grid-vault">
									{[...Array(view.limits.vault).keys()].map((i) => {
										const it = byPlace[keyOf(at.vault(i))];
										return <Slot key={i} item={it} target={{ kind: "place", to: at.vault(i) }} dim={!!it && !vaultMatch(it)}
											locked={locked} ctx={slotCtx} />;
									})}
								</div>
							</Overlay>)}

						{panel === "forge" && !run && (
							<Overlay title="Forge" onClose={() => setPanel(null)} className="hr-forge-panel">
								{forged ? <ForgeReveal forged={forged} ap={stats?.ap || 0}
									where={forged.item.loc === "equipped" ? `Equipped as your ${(SLOT_NAMES[forged.item.equip_slot] || "gear").toLowerCase()}`
										: forged.item.loc === "inventory" ? `In your bag, slot ${forged.item.slot_index + 1}` : "In the vault"}
									onAgain={() => setForged(null)} onDone={() => { setForged(null); setPanel(null); }} />
								: <>
									<div className="hr-forge-top">
										<div className="hr-forge-tabs" role="tablist">
											{[["reroll", "Reroll"], ["fuse", "Fuse"]].map(([id, label]) =>
												<button key={id} role="tab" aria-selected={forgeTab === id}
													className={"btn " + (forgeTab === id ? "btn-gold" : "btn-ghost")}
													onClick={() => { setForgeTab(id); setForge((f) => f.slice(0, id === "fuse" ? 2 : 1)); }}>{label}</button>)}
										</div>
										<span className="hr-shards" aria-label="Your shards">◈ {shards} shards</span>
									</div>
									{forgeTab === "reroll" ? <>
										<p className="hr-hint">Click an item in your bag or equipment. Click its lines to keep them:
											each kept line doubles the price. Special lines (✦) are always kept.</p>
										{fa ? <div className="hr-forge-card hr-reroll-card">
											<span className="hr-forge-glyph">{ABBR[fa.base_id] || "?"}</span>
											<strong>{nameOf(fa)}</strong>
											<Dots n={fa.slot_count} />
											<ul className="hr-reroll-lines">
												{(fa.enchants || []).map((e, i) => {
													const special = isSpecial(e.id), on = kept.has(i);
													return <li key={i}><button className={"hr-line" + (on ? " kept" : "") + (special ? " special" : "")}
														disabled={special} aria-pressed={on}
														onClick={() => setKeep((k) => (k.includes(i) ? k.filter((x) => x !== i) : [...k, i]))}>
														<i aria-hidden="true">{special ? "✦" : on ? "🔒︎" : "○"}</i>{lineText(e)}</button></li>;
												})}
												{!fa.enchants?.length && <li className="hr-hint">No enchantment slots: nothing to reroll</li>}
											</ul>
											<button className="hr-forge-clear btn btn-ghost" onClick={() => forgePick(fa)}>Put it back</button>
										</div> : <div className="hr-forge-card empty"><span className="hr-hint">Pick an item</span></div>}
										<div className="hr-actions hr-forge-go">
											<button className="btn btn-gold" disabled={!canReroll || locked} onClick={reroll}>
												Reroll{fa ? ` · ${rerollCost} shards` : ""}</button>
											<button className="btn btn-outline" disabled={!fa || locked} onClick={breakDown}>
												{breaking ? `Click again: break it down for ${salvageValue}` : fa ? `Break down · +${salvageValue} shards` : "Break down"}</button>
										</div>
										{fa && shards < rerollCost && (fa.enchants || []).length > kept.size &&
											<p className="hr-hint">You need {rerollCost - shards} more shards. Kills in a rift pay them, more with modifiers and deeper levels.</p>}
									</> : <>
										<p className="hr-hint">Click two of the same item, any tier. Both are used up; one comes back
											with the higher tier, at least the fewer slots, and fresh lines.</p>
										<div className="hr-forge">
											<ForgeCard item={fa} label="First item" ap={stats?.ap || 0} onClear={fa ? () => forgePick(fa) : null} />
											<span className="hr-plus" aria-hidden="true">+</span>
											<ForgeCard item={fb} label="Second item" ap={stats?.ap || 0} onClear={fb ? () => forgePick(fb) : null} />
											<span className="hr-plus" aria-hidden="true">=</span>
											<div className={"hr-forge-card hr-forge-out" + (fusable ? " ready" : "")}>
												{fusable ? <>
													<span className="hr-forge-glyph">{ABBR[fa.base_id]}<b>?</b></span>
													<strong>{nameOf({ ...fa, tier: Math.max(fa.tier, fb.tier) })}</strong>
													<span className="hr-forge-slots">At least {Math.min(fa.slot_count, fb.slot_count)} slot{Math.min(fa.slot_count, fb.slot_count) === 1 ? "" : "s"}</span>
													<ul className="hr-forge-odds">
														{(view.odds?.fuse_slots?.[Math.min(fa.slot_count, fb.slot_count)] || []).map(([n, pr]) =>
														<li key={n}>{n} slot{n === 1 ? "" : "s"}: {Math.round(pr * 1000) / 10}%</li>)}
													</ul>
													<span className="hr-hint">Every line rolled fresh</span>
													{[fa, fb].some((x) => (x.enchants || []).some((e) => isSpecial(e.id))) &&
														<span className="hr-warn">A special line (✦) will be lost</span>}
												</> : <span className="hr-hint">{!fa || !fb ? "Pick two items" : "Not the same item"}</span>}
											</div>
										</div>
										<div className="hr-actions hr-forge-go">
											<button className="btn btn-gold" disabled={!fusable || locked} onClick={fuse}>Fuse</button>
										</div>
									</>}
								</>}
							</Overlay>)}

						{panel?.startsWith?.("realm:") && !run && (() => {
							const realm = panel.slice(6), d = (view.dungeons || []).find((x) => x.id === realm);
							const r = mods.filter((m) => m !== BOSS_RUSH).length, rule = lootRule(view), cap = rule.start_mods;
							const plus = (x) => `+${Math.round(x * 100)}%`;
							const shut = riftShut(view, d, char);
							if (shut) return (
								<Overlay title={d?.name || "Rift"} onClose={() => setPanel(null)} className="hr-rift-panel hr-rift-shut">
									<p className="hr-hint">{shut}</p>
								</Overlay>);
							return (
								<Overlay title={d?.name || "Rift"} onClose={() => setPanel(null)} className="hr-rift-panel">
									<p className="hr-hint">Add modifiers for a harder rift and better loot: up to {cap} to start. Each level deeper adds one more.</p>
									<div className="hr-mods" role="group" aria-label="Rift modifiers">
										{(view.rift_mods || []).map((m) => {
											const on = mods.includes(m.id);
											return <button key={m.id} className={"hr-mod" + (on ? " on" : "")} aria-pressed={on} disabled={!on && r >= cap}
												onClick={() => setMods((cur) => (on ? cur.filter((x) => x !== m.id) : [...cur, m.id]))}>
												<strong>{m.name || m.id}</strong><span>{m.text}</span></button>;
										})}
									</div>
									{(() => {
										const keys = carried("boss_rush_key"), on = mods.includes(BOSS_RUSH);
										return keys > 0 || on ? <button className={"hr-mod hr-mod-rush" + (on ? " on" : "")} aria-pressed={on}
											onClick={() => setMods((cur) => (on ? cur.filter((x) => x !== BOSS_RUSH) : [...cur, BOSS_RUSH]))}>
											<strong>{view.boss_rush?.name || "Boss Rush"} <small>· {keys} key{keys === 1 ? "" : "s"} in your bag</small></strong>
											<span>{view.boss_rush?.text}</span></button>
											: <p className="hr-hint">With a Boss Rush key in your bag you can skip straight to each level's boss.</p>;
									})()}
									<dl className="hr-mod-sum">
										<div><dt>Loot</dt><dd>{plus(rule.per_mod * r)}</dd></div>
										<div><dt>XP</dt><dd>{plus(rule.xp_per_mod * r)}</dd></div>
									</dl>
									<div className="hr-actions">
										<button className="btn btn-gold" disabled={!char || busy}
											onClick={() => enterRef.current(realm, false, mods)}>Enter the rift</button>
										{r > 0 && <button className="btn btn-ghost" onClick={() => setMods([])}>Clear</button>}
									</div>
								</Overlay>);
						})()}

						{panel === "dream" && !run && (
							<Overlay title="Dream Rifts" onClose={() => setPanel(null)} className="hr-dream-panel">
								<p className="hr-hint">Practice any rift without loot, XP, stats, item drops or character death. A fallen practice run returns you to town.</p>
								<p className={"hr-dream-keys" + (carried("dream_key") ? "" : " none")}>{carried("dream_key")
									? `Each practice run spends a Dream Key from your bag. You carry ${carried("dream_key")}.`
									: "Each practice run spends a Dream Key, and your bag has none. Bosses drop them now and then."}</p>
								<div className="hr-dream-list">
									{(view.dungeons || []).map((d) => {
										const best = view.leaderboards?.[d.id] || [], shut = riftShut(view, d, char);
										return <article className="hr-dream-rift" key={d.id}>
											<div><h3 className="fg-label">{d.name}</h3><p className="hr-hint">{shut || (best.length ? "Your five fastest boss times" : "No recorded times yet")}</p></div>
											{best.length > 0 && <ol className="hr-times">{best.map((t, i) => <li key={`${t.time_ticks}-${i}`}>
												<span>{formatRiftTime(t.time_ticks)}</span><small>{t.practice ? "Dream" : "Rift"}</small>
											</li>)}</ol>}
											<button className="btn btn-gold" disabled={!char || busy || !carried("dream_key") || !!shut}
												onClick={() => { setPanel(null); enterRef.current(d.id, true); }}>Practice</button>
										</article>;
									})}
								</div>
							</Overlay>)}

					</div>
				</section>

				<aside className="hr-side fg-panel" aria-label="Your character">
					<div className="hr-who">
						{char ? <>
							<span className="hr-char-name">{className(char.class_id)}</span>
							{run ? <LiveHero levels={view.levels} read={() => run.ctl.st?.hero} />
								: <><span className="fg-label-soft">Level {char.level}</span>
									<XpBar levels={view.levels} xp={char.xp} /></>}
						</> : null}
					</div>

					{char && <Vitals read={() => vitalsOf(run ? run.ctl.st : townRef.current)} />}
					{char && <Stats gear={equipped} level={char.level} classId={char.class_id} />}
					<h2 className="fg-label">Equipment</h2>
					<div className="hr-equip">
						{view.limits.equip.map((s) => {
							const to = char ? at.eq(char.char_id, s) : null;
							return <Slot key={s} label={SLOT_NAMES[s]} item={to ? byPlace[keyOf(to)] : null}
								target={to && { kind: "place", to }} locked={locked} ctx={slotCtx} />;
						})}
					</div>
					<div className="hr-inv-hd">
						<h2 className="fg-label">Inventory</h2>
						<button className="btn btn-ghost btn-sm hr-sort" disabled={!char || locked} onClick={sortBag}
							title="Weapons, armor, abilities, rings; best first">Sort</button>
					</div>
					<div className="hr-grid hr-grid-inv">
						{[...Array(view.limits.inventory).keys()].map((i) => {
							const to = char ? at.inv(char.char_id, i) : null;
							return <Slot key={i} num={i < 8 ? i + 1 : null} item={invItem(i)} target={to && { kind: "place", to }} locked={locked} ctx={slotCtx} />;
						})}
					</div>
					<div className={"hr-trash hr-ground" + (drag && !run?.practice ? " armed" : "")} aria-label="Drop on the ground"
						onDragOver={(e) => { if (drag && !locked) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
						onDrop={(e) => { e.preventDefault(); if (!locked) slotCtx.dropAt({ kind: "trash" }); setDrag(null); }}>
						{run?.practice ? "Swap gear any time · nothing can be dropped in a Dream Rift"
							: `Drag here or onto the stage, or point and press ${keysOf("drop")}, to drop an item. It lies there until you leave ${run ? "the rift" : "town"}.`}
					</div>
				</aside>
			</main>
			{tip && <ItemTip tip={tip} bases={view.bases} ap={stats?.ap || 0} compare={compareFor(tip.item)} classId={char?.class_id} />}
		</div>
	);
}

/* An item slot: a drag source, a drop target, and a click target. `target` says
 * what dropping here means: a place, a forge input, or nothing. */
function Slot({ label, item, target, locked, ctx, num: n = null, dim = false }) {
	const fam = item ? ctx.bases[item.base_id]?.slot : null;
	const ok = ctx.dragItem && target ? ctx.accepts(target, ctx.dragItem) : null;
	const name = item ? nameOf(item) + (item.locked ? ", locked" : "") : `${label || "Empty"} slot`;
	const forged = item && ctx.forge.includes(item.item_id);
	return (
		<button className={"hr-slot" + (item ? ` has fam-${fam}` : "") + (item && item.item_id === ctx.picked ? " sel" : "") + (dim ? " dim" : "")
			+ (item?.kind === "unique" ? " unique" : "") + (forged ? " forging" : "") + (item && item.item_id === ctx.flash ? " flash" : "")
			+ (ok === true ? " ok" : ok === false ? " no" : "") + (item && item.item_id === ctx.drag ? " dragging" : "")}
			aria-label={name} aria-pressed={forged || undefined} disabled={!target && !item}
			draggable={!!item && !locked && (!item.fresh || ctx.inRun)}
			onDragStart={(e) => { e.dataTransfer.setData("text/plain", item.item_id); e.dataTransfer.effectAllowed = "move"; ctx.startDrag(item); }}
			onDragEnd={(e) => { ctx.endDrag(); if (ctx.inRun) e.currentTarget.blur(); }}
			onDragOver={(e) => { if (ctx.drag && target && !locked) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
			onDrop={(e) => { e.preventDefault(); if (target && !locked) ctx.dropAt(target); ctx.endDrag(); }}
			onMouseEnter={(e) => item && ctx.showTip(item, e.currentTarget, !!(ctx.lock && target))}
			onMouseLeave={ctx.hideTip}
			onFocus={(e) => item && ctx.showTip(item, e.currentTarget, !!(ctx.lock && target))}
			onBlur={ctx.hideTip}
			onClick={(e) => { if (!locked && target) ctx.clickAt(target, item, e.shiftKey); if (ctx.inRun) e.currentTarget.blur(); }}
			onDoubleClick={(e) => { if (!locked && item && target && !(ctx.vaultOpen && e.shiftKey)) ctx.quick(item); if (ctx.inRun) e.currentTarget.blur(); }}
			onContextMenu={(e) => { e.preventDefault(); if (item && target && ctx.lock) ctx.lock(item); }}>
			{n && <span className="hr-num" aria-hidden="true">{n}</span>}
			{item?.locked && <span className="hr-lock" aria-hidden="true">🔒︎</span>}
			{item ? <><span className="hr-abbr">{ABBR[item.base_id] || "?"}</span>
				{item.kind === "unique" ? <span className="hr-tier hr-star" aria-hidden="true">★{item.tier}</span>
					: item.kind === "key" ? <span className="hr-tier hr-key" aria-hidden="true">⚷</span>
					: <span className="hr-tier">{item.tier}</span>}
				{item.slot_count > 0 && <span className="hr-dots">{"•".repeat(item.slot_count)}</span>}</>
				: label && <span className="hr-slot-label">{label}</span>}
		</button>
	);
}

/* What an item is, beside the slot under the pointer — kept inside the window. With
 * `compare` (what is equipped in that slot: both rings for a ring), the cards stand
 * SIDE BY SIDE (owner's ask, 2026-11-18: not stat deltas), every stat in one order. */
function ItemTip({ tip, bases, ap = 0, compare = [], classId = null }) {
	const ref = useRef(null);
	const [pos, setPos] = useState(null);
	const key = `${tip.item.item_id}|${compare.map((c) => c.item_id).join(",")}`;
	useLayoutEffect(() => {
		const el = ref.current, r = tip.rect, w = el.offsetWidth, h = el.offsetHeight;
		const left = r.left > window.innerWidth / 2 ? r.left - w - 10 : r.right + 10;
		setPos({ left: Math.max(8, Math.min(window.innerWidth - w - 8, left)),
			top: Math.max(8, Math.min(window.innerHeight - h - 8, r.top)) });
	}, [tip, key]); // eslint-disable-line react-hooks/exhaustive-deps
	const unique = tip.item.kind === "unique";
	return (
		<div ref={ref} className={"hr-tip" + (compare.length ? " hr-tip-compare" : "")} role="tooltip"
			style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: "hidden" }}>
			<TipCard it={tip.item} bases={bases} ap={ap} lit={unique} kicker={compare.length ? "This item" : null}
				classId={classId} canLock={tip.canLock} />
			{compare.map((c) => <TipCard key={c.item_id} it={c} bases={bases} ap={ap} classId={classId} equipped />)}
		</div>
	);
}

/* One item's card in a tooltip: name, kind, its own stats, then its enchantment slots. */
function TipCard({ it, bases, ap, lit = false, equipped = false, kicker = null, classId = null, canLock }) {
	const fam = bases[it.base_id]?.slot, cls = bases[it.base_id]?.cls, lines = [...weaponLines(it), ...abilityLines(it, ap), ...baseLines(it), ...uniqueLines(it)];
	const ench = sortedEnchants(it);
	return (
		<div className={"hr-tip-card fg-panel" + (it.kind === "unique" ? " unique" : "") + (lit ? " fg-lit" : "")}>
			{(equipped || kicker) && <p className="hr-tip-kicker">{equipped ? "Equipped" : kicker}</p>}
			<h3 className="fg-label">{it.locked && <span className="hr-lock-mark" aria-label="Locked">🔒︎ </span>}{nameOf(it)}</h3>
			<p className="fg-label-soft">{it.kind === "key" ? "Key" : it.kind === "unique" ? `Unique ${(FAMILY[fam] || "item").toLowerCase()} · Tier ${it.tier}` : `${FAMILY[fam] || ""} · Tier ${it.tier}`}
			</p>
			{fam && fam !== "key" && (classId && !classOk(cls, classId)
				? <p className="hr-tip-class cant">{classWords(cls)} only — your {CLASS_INFO[classId]?.name || "character"} cannot use it</p>
				: <p className="hr-tip-class">{cls ? `${classWords(cls)} only` : "Any class"}</p>)}
			{bases[it.base_id]?.home && <p className="hr-tip-class hr-tip-home">Found in {REALMS.find((r) => r.id === bases[it.base_id].home)?.name || bases[it.base_id].home}</p>}
			{WEAPON_FEEL[it.base_id] && <p className="hr-tip-weapon">{WEAPON_FEEL[it.base_id]}</p>}
			{KEY_TEXT[it.base_id] && <p className="hr-tip-weapon">{KEY_TEXT[it.base_id]}</p>}
			{lines.length > 0 && <ul className="hr-tip-lines hr-q">{lines.map((l) => <li key={l}>{l}</li>)}</ul>}
			{/* The item's own stats above; its enchantment slots below a rule, one row a
			    slot — filled or empty — so a count never has to be read (owner's ask). */}
			{it.slot_count > 0 && (
				<ul className="hr-tip-lines hr-enchants" aria-label="Enchantment slots">
					{[...Array(it.slot_count).keys()].map((i) => {
						const e = ench[i];
						return e ? <li key={i} className={isSpecial(e.id) ? "special" : ""}><i aria-hidden="true">{isSpecial(e.id) ? "✦" : "◆"}</i>{lineText(e)}</li>
							: <li key={i} className="empty"><i aria-hidden="true">◇</i>Empty slot</li>;
					})}
				</ul>)}
			{!equipped && (canLock ?? (it.item_id && !String(it.item_id).startsWith("drop:") && !it.fresh && it.loc)) &&
				<p className="hr-tip-hint">{it.locked ? "Locked: Sort, discard and fuse leave it alone. Right-click to unlock." : "Right-click to lock."}</p>}
		</div>
	);
}

function Dots({ n, of = n, lit = 0 }) {
	return <span className="hr-forge-dots" aria-label={`${n} enchantment slot${n === 1 ? "" : "s"}`}>
		{[...Array(Math.max(n, of)).keys()].map((i) => <i key={i} className={(i < n ? "on" : "") + (i >= n - lit && i < n ? " new" : "")} />)}</span>;
}

const enchantLine = lineText;

/* One input on the forge: the item picked, or an empty socket. */
function ForgeCard({ item, label, onClear }) {
	if (!item) return <div className="hr-forge-card empty"><span className="hr-hint">{label}</span></div>;
	return (
		<button className={"hr-forge-card" + (item.kind === "unique" ? " unique" : "")} onClick={onClear} title="Click to put it back">
			<span className="hr-forge-glyph">{ABBR[item.base_id] || "?"}</span>
			<strong>{nameOf(item)}</strong>
			<Dots n={item.slot_count} />
			<ul className="hr-forge-ench">{sortedEnchants(item).map((e, i) => <li key={i}>{enchantLine(e)}</li>)}</ul>
		</button>
	);
}

/* What came out of the forge, side by side with what went in: the slot count before
 * and after (a gained slot is the headline), and each enchantment against the best
 * of the same kind on either input. */
function ForgeReveal({ forged, where, onAgain, onDone }) {
	const { item, a, b } = forged;
	const before = Math.min(a.slot_count, b.slot_count), after = item.slot_count, gained = after - before;
	const best = {};
	for (const e of [...(a.enchants || []), ...(b.enchants || [])]) best[e.id] = Math.max(best[e.id] ?? -Infinity, enchantValue(e.id, e.q));
	return (
		<div className={"hr-reveal" + (gained > 0 ? " gained" : "")}>
			<div className="hr-reveal-in" aria-label="Used up">
				{[a, b].map((x, i) => <span key={i} className="hr-reveal-used">{nameOf(x)}</span>)}
			</div>
			<div className={"hr-forge-card hr-reveal-card" + (item.kind === "unique" ? " unique" : "")}>
				<span className="hr-forge-glyph">{ABBR[item.base_id] || "?"}</span>
				<strong>{nameOf(item)}</strong>
				<Dots n={after} lit={Math.max(0, gained)} />
				{gained > 0
					? <p className="hr-reveal-gain">+{gained} enchantment slot{gained > 1 ? "s" : ""}! {before} → {after}</p>
					: <p className="hr-hint">{after} slot{after === 1 ? "" : "s"}: the fewer of the two</p>}
				<ul className="hr-forge-ench hr-reveal-ench">
					{sortedEnchants(item).map((e, i) => {
						const v = enchantValue(e.id, e.q), was = best[e.id];
						const tag = was === undefined ? ["new", "New"] : v > was ? ["up", `was +${was}`] : v < was ? ["down", `was +${was}`] : ["same", "same"];
						return <li key={i} className={"tag-" + tag[0]} style={{ animationDelay: `${300 + i * 180}ms` }}>
							{enchantLine(e)} <small>{tag[1]}</small></li>;
					})}
					{!item.enchants?.length && <li className="hr-hint">No enchantments</li>}
				</ul>
			</div>
			<p className="hr-hint hr-reveal-where">{where}.</p>
			<div className="hr-actions">
				<button className="btn btn-gold" onClick={onAgain}>Fuse again</button>
				<button className="btn btn-ghost" onClick={onDone}>Done</button>
			</div>
		</div>
	);
}

/* The game menu: Escape (or the Menu button) over the town or a run. The keys live
 * here now, not in a line under the stage, so the stage can have the room. They read
 * off the player's own bindings (Settings). */
const keyRows = () => [
	[[keysOf("up"), keysOf("left"), keysOf("down"), keysOf("right")].join(" "), "Move (the arrow keys too)"],
	["Mouse", "Aim; hold the left button to shoot"], [keysOf("auto"), "Auto-fire on / off"],
	[`${keysOf("ability")} · right-click`, "Your ability"], [keysOf("interact"), "Use: vault, forge, portal, Dream Rift; pick up loot"],
	[keysOf("potion"), `Healing potion: +${POTION_HEAL} HP, then ${Math.round(POTION_COOLDOWN / TPS)}s to refill (in a rift)`],
	[keysOf("takeAll"), "Take all the loot here"], ["1 – 8", "Equip that bag slot (or double-click it)"],
	["Right-click an item", "Lock or unlock it"], [keysOf("recall"), "Recall to town (in a rift)"], ["Esc", "This menu; closes a panel"],
];
/* What dealt the killing blow, in words: the sim tags every enemy shot (and a
 * chaser's charge) with "<enemy>:<attack>" and keeps the last hit that landed. */
const ENEMY_NAMES = { chaser: "a Chaser", shooter: "a Shooter", radial: "a Radial", boss: "the boss",
	shard: "a Shard", splitter: "a Splitter", splinter: "a Splinter", flicker: "a Flicker", rift: "the Rift",
	cinder: "a Cinder", kiln: "a Kiln", smolder: "a Smolder" };
const ATTACK_NAMES = { touch: "charge", spit: "spit", bolt: "bolt", ring: "ring of shots", spiral: "spiral",
	fan: "fan of shots", nova: "nova", burst: "dying burst", mortar: "mortar", fire: "burning ground",
	cross: "cross of shots", pair: "pair of shots", fault: "fault line", shatter: "shatter shard", tear: "tear", blink: "ring", crack: "opening crack",
	bomb: "firebomb", flame: "cross of fire", eruption: "vent eruption", vent: "vent fire" };
function causeOf(hit) {
	if (!hit || !hit.src) return "Fell in the rift";
	const [who, how] = hit.src.split(":");
	return `Slain by ${ENEMY_NAMES[who] || "an enemy"}’s ${ATTACK_NAMES[how] || "attack"}`;
}

/* THE RUN REPORT. A death shows it at once (owner's ask, 2026-11-18): what killed you,
 * how the run went, what was on the character — lost for good, or (a Dream Rift)
 * kept. A clear or a recall shows it only when its line in the log is clicked, and
 * the graveyard keeps every death's. `r` is the run's outcome (see Dungeon's finish). */
function RunReport({ r, equip, ctx, onDone, doneLabel = null, overlay = false }) {
	const dead = r.status === "dead";
	const lost = dead && !r.practice;
	const gear = r.items.filter((it) => it.loc === "equipped");
	const bag = r.items.filter((it) => it.loc === "inventory").sort((a, b) => a.slot_index - b.slot_index);
	const found = r.items.filter((it) => it.fresh);
	const hit = r.lastHit;
	const btn = useRef(null);
	useEffect(() => { btn.current?.focus(); }, []);
	const kicker = dead ? (r.practice ? "Dream Rift failed" : "Fallen")
		: r.status === "completed" ? (r.practice ? "Dream Rift complete" : "Cleared") : "Recalled";
	return (
		<section className={"hr-death fg-panel" + (dead ? "" : " hr-report-won") + (overlay ? " hr-report-overlay" : "")}
			role="dialog" aria-labelledby="hr-death-title">
			<p className="hr-death-kicker">{kicker}</p>
			<h1 id="hr-death-title" className="hr-death-title">{className(r.classId)} · Level {r.level}</h1>
			{dead && <p className="hr-death-cause">{causeOf(hit)}{hit && hit.dmg > 0 && <small> · the last hit dealt {Math.round(hit.dmg * 10) / 10}</small>}</p>}
			<dl className="hr-death-facts">
				<div><dt>Rift</dt><dd>{r.practice ? "Dream: " : ""}{r.dungeonName}{r.depth > 1 ? `, level ${r.depth}` : ""}</dd></div>
				<div><dt>Modifiers</dt><dd>{r.mods?.length ? r.mods.map((m) => m[0].toUpperCase() + m.slice(1)).join(", ") : "None"}</dd></div>
				{r.ticks != null && <div><dt>Time in the rift</dt><dd>{formatRiftTime(r.ticks)}</dd></div>}
				{!dead && r.timeTicks != null && <div><dt>Boss time</dt><dd>{formatRiftTime(r.timeTicks)}</dd></div>}
				{r.kills != null && <div><dt>Enemies slain</dt><dd>{r.kills}</dd></div>}
				{r.taken != null && <div><dt>Damage taken</dt><dd>{Math.round(r.taken)}</dd></div>}
				{r.diedAt && <div><dt>Fell</dt><dd>{new Date(r.diedAt * 1000).toLocaleDateString()}</dd></div>}
			</dl>
			<div className="hr-death-gear">
				<div>
					<h2 className="fg-label">{lost ? "Equipment lost" : "Equipment"}</h2>
					<div className="hr-equip">{equip.map((s) => <Slot key={s} label={SLOT_NAMES[s]}
						item={gear.find((it) => it.equip_slot === s) || null} locked ctx={ctx} />)}</div>
				</div>
				<div>
					<h2 className="fg-label">{lost ? "Bag lost" : "Bag"}</h2>
					{bag.length ? <div className="hr-death-bag">{bag.map((it) => <Slot key={it.item_id} item={it} locked ctx={ctx} />)}</div>
						: <p className="hr-hint">The bag was empty.</p>}
				</div>
			</div>
			{found.length > 0 && <p className="hr-hint">{dead ? "Found this run" : "Brought back"}: {found.map(nameOf).join(", ")}.</p>}
			{!dead && !found.length && !r.practice && <p className="hr-hint">Nothing new was brought back.</p>}
			{dead && <p className="hr-hint">{r.practice ? "Nothing changed: a Dream Rift never costs your character anything."
				: "Everything it carried is gone. The vault is untouched."}</p>}
			<div className="hr-actions">
				<button ref={btn} className="btn btn-gold" onClick={onDone}>{doneLabel || (dead ? (r.practice ? "Back to town" : "Main menu") : "Close")}</button>
			</div>
		</section>
	);
}

/* A fallen character's death screen, from the graveyard's record of it (the store
 * wrote it as the character died). An older death, from before the record, has none. */
function reportOfFallen(c) {
	const d = c.death_summary;
	if (!d) return null;
	return { status: "dead", practice: false, classId: c.class_id, level: c.level, diedAt: c.died_at,
		lastHit: d.src ? { src: d.src, dmg: d.hit || 0 } : null, dungeonName: d.dungeon_name, depth: d.depth || 1, mods: d.mods || [],
		ticks: d.ticks ?? null, kills: d.kills ?? null, taken: d.taken ?? null,
		items: (d.items || []).map((it, i) => ({ ...it, item_id: `grave:${c.char_id}:${i}`, fresh: it.origin_run_id === d.run_id })) };
}

/* The graveyard: every fallen character, newest first; each opens its death screen. */
function Graveyard({ fallen, count, onOpen, onClose }) {
	return (
		<Overlay title="Graveyard" onClose={onClose} className="hr-graveyard">
			{fallen.length ? <ol className="hr-grave-list">
				{fallen.map((c) => {
					const d = c.death_summary;
					return <li key={c.char_id}>
						<button className={`hr-grave hr-class-${c.class_id}`} onClick={() => onOpen(c)} disabled={!d}>
							<strong>{className(c.class_id)} · Level {c.level}</strong>
							<span>{d ? `${causeOf(d.src ? { src: d.src } : null)} in ${d.dungeon_name}${d.depth > 1 ? `, level ${d.depth}` : ""}` : "Fell before the graveyard kept records"}</span>
							{c.died_at && <small>{new Date(c.died_at * 1000).toLocaleDateString()}</small>}
						</button></li>;
				})}
			</ol> : <p className="hr-hint">Nobody has fallen yet.</p>}
			{count > fallen.length && <p className="hr-hint">The newest {fallen.length} of {count}.</p>}
		</Overlay>
	);
}

/* SETTINGS (design §19.1), kept on this device: the keys, reduced flashing, the
 * interface's size. A key is rebound by clicking it and pressing the new one; a key
 * already in use moves over (the other action loses it). */
function Settings({ prefs, setPrefs, onClose }) {
	const [wait, setWait] = useState(null);      // the action waiting for a key
	useEffect(() => {
		if (!wait) return undefined;
		const onKey = (e) => {
			e.preventDefault(); e.stopImmediatePropagation();
			if (e.code === "Escape") { setWait(null); return; }
			if (FIXED_KEY(e.code)) return;            // Escape, the arrows and 1-8 are fixed
			setPrefs((p) => {
				const keys = Object.fromEntries(Object.entries(p.keys).map(([id, ks]) => [id, ks.filter((k) => k !== e.code)]));
				keys[wait] = [e.code];
				return { ...p, keys };
			});
			setWait(null);
		};
		window.addEventListener("keydown", onKey, { capture: true });
		return () => window.removeEventListener("keydown", onKey, { capture: true });
	}, [wait, setPrefs]);
	return (
		<Overlay title="Settings" onClose={onClose} className="hr-settings">
			<h3 className="fg-label">Display</h3>
			<div className="hr-sizes" role="group" aria-label="Art style">
				<span>Art style</span>
				{[["pixel", "Pixel art"], ["greybox", "Greybox"]].map(([v, label]) => <button key={v}
					className={"hr-size" + (prefs.artStyle === v ? " on" : "")} aria-pressed={prefs.artStyle === v}
					onClick={() => setPrefs((p) => ({ ...p, artStyle: v }))}>{label}</button>)}
			</div>
			<label className="hr-check"><input type="checkbox" checked={prefs.calm}
				onChange={(e) => setPrefs((p) => ({ ...p, calm: e.target.checked }))} />
				<span>Reduced flashing: no white hit flashes, and the boss's phase change holds still</span></label>
			<div className="hr-sizes" role="group" aria-label="Interface size">
				<span>Interface size</span>
				{UI_SIZES.map(([v, label]) => <button key={v} className={"hr-size" + (prefs.ui === v ? " on" : "")} aria-pressed={prefs.ui === v}
					onClick={() => setPrefs((p) => ({ ...p, ui: v }))}>{label}</button>)}
			</div>
			<h3 className="fg-label">Keys</h3>
			<p className="hr-hint">Click a key, then press the new one. Escape, the arrow keys and 1 – 8 stay as they are.</p>
			<dl className="hr-binds">
				{ACTIONS.map(([id, what]) => <div key={id}>
					<dt>{what}</dt>
					<dd><button className={"hr-bind" + (wait === id ? " waiting" : "") + (!prefs.keys[id]?.length ? " unbound" : "")}
						onClick={() => setWait((w) => (w === id ? null : id))}>
						{wait === id ? "Press a key…" : (prefs.keys[id] || []).map(keyLabel).join(" · ") || "Not set"}</button></dd>
				</div>)}
			</dl>
			<div className="hr-actions">
				<button className="btn btn-ghost" onClick={() => setPrefs((p) => ({ ...p, keys: { ...DEFAULT_KEYS } }))}>Reset keys</button>
				<button className="btn btn-gold" onClick={onClose}>Done</button>
			</div>
			<p className="hr-hint">Sound settings arrive with the sound.</p>
		</Overlay>
	);
}

function GameMenu({ inRun, practice, mods = [], onResume, onRecall, onMainMenu, onSettings }) {
	return (
		<Overlay title="Menu" onClose={onResume} className="hr-game-menu">
			<div className="hr-game-menu-acts">
				<button className="btn btn-gold" onClick={onResume}>Resume</button>
				{inRun && <button className="btn btn-outline" onClick={onRecall}>Recall to town</button>}
				<button className="btn btn-outline" onClick={onMainMenu}>{inRun ? "Recall and go to the main menu" : "Main menu"}</button>
				<button className="btn btn-ghost" onClick={onSettings}>Settings</button>
			</div>
			{inRun && !practice && <p className="hr-hint">Recalling keeps what you carry; the rift is closed behind you.</p>}
			{inRun && <>
				<h3 className="fg-label">This rift's modifiers</h3>
				{mods.length ? <dl className="hr-keylist hr-run-mods">
					{mods.map((m) => <div key={m.id}><dt>{m.name}</dt><dd>{m.text}</dd></div>)}
				</dl> : <p className="hr-hint">None.</p>}
			</>}
			<h3 className="fg-label">Keys</h3>
			<dl className="hr-keylist">
				{keyRows().map(([k, what]) => <div key={what}><dt><kbd>{k}</kbd></dt><dd>{what}</dd></div>)}
			</dl>
		</Overlay>
	);
}

function Overlay({ title, onClose, className = "", children }) {
	return (
		<section className={"hr-overlay fg-panel " + className} role="dialog" aria-label={title}>
			<header className="hr-overlay-hd">
				<h2 className="fg-label">{title}</h2>
				<button className="hr-x" aria-label="Close" onClick={onClose}>×</button>
			</header>
			{children}
		</section>
	);
}

/* The character's numbers, all flat: what the sim will use with this gear on. */
function Stats({ gear, level, classId = "ranger" }) {
	const s = statsFor(gear, level, classId);
	// Damage and fire rate are the WEAPON's (its tooltip), not the character's.
	const cells = [["ATT", s.att, "Attack: each point adds to your weapon's damage"], ["DEX", s.dex, "Dexterity: each point adds to how fast you shoot"],
		["DEF", s.def, "Defense: taken off every hit"], ["AP", s.ap, "Ability power: each point makes your ability stronger"]];
	return (
		<dl className="hr-stats" aria-label="Stats">
			{cells.map(([k, v, t]) => <div key={k} title={t}><dt>{k}</dt><dd>{v}</dd></div>)}
		</dl>
	);
}

/* HP and MP from the live fight or the town. HP has three parts: what you have (red),
 * what regeneration can still bring back up to the recovery limit (light gray), and
 * what it cannot until a heal raises the limit (dark gray). */
function vitalsOf(st) {
	if (!st || !st.stats) return null;
	const s = st.stats, p = st.p, town = p.hp === undefined, regen = roomRegenMultiplier(st);
	return { hp: town ? s.maxHp : p.hp, limit: town ? s.maxHp : recoveryLimit(st), maxHp: s.maxHp, mp: p.mp, maxMp: s.maxMp,
		hpRegen: s.hpRegen * regen, mpRegen: s.mpRegen * regen };
}

/* The bars repaint themselves each frame from `read()` and touch the DOM only when a
 * number changes, so a fight at 60 Hz never re-renders the page. */
function Vitals({ read }) {
	const ref = useRef(null);
	const readRef = useRef(read);
	readRef.current = read;
	useEffect(() => {
		let raf = 0, last = "";
		const el = ref.current;
		const [hpFill, hpRec, hpText, mpFill, mpText, hpReg, mpReg] = ["hp-fill", "hp-rec", "hp-text", "mp-fill", "mp-text", "hp-reg", "mp-reg"]
			.map((k) => el.querySelector(`[data-k="${k}"]`));
		const frame = () => {
			const v = readRef.current();
			if (v) {
				const hp = Math.ceil(v.hp), lim = Math.ceil(v.limit), mp = Math.floor(v.mp);
				const key = `${hp}|${lim}|${v.maxHp}|${mp}|${v.maxMp}|${v.hpRegen}|${v.mpRegen}`;
				if (key !== last) {
					last = key;
					hpFill.style.width = `${(100 * Math.min(v.hp, v.maxHp)) / v.maxHp}%`;
					hpRec.style.width = `${(100 * Math.min(v.limit, v.maxHp)) / v.maxHp}%`;
					hpText.textContent = `${hp} / ${v.maxHp}`;
					mpFill.style.width = `${(100 * Math.min(v.mp, v.maxMp)) / v.maxMp}%`;
					mpText.textContent = `${mp} / ${v.maxMp}`;
					hpReg.textContent = `+${num(v.hpRegen)}/s`;
					mpReg.textContent = `+${num(v.mpRegen)}/s`;
					el.dataset.hp = hp; el.dataset.limit = lim; el.dataset.maxHp = v.maxHp;
				}
			}
			raf = requestAnimationFrame(frame);
		};
		frame();
		return () => cancelAnimationFrame(raf);
	}, []);
	return (
		<div className="hr-vitals" ref={ref}>
			<div className="hr-bar hr-bar-hp" title="Health, and what it regenerates a second. Light gray: regeneration brings it back. Dark gray: only a heal does.">
				<i className="hr-bar-rec" data-k="hp-rec" /><i className="hr-bar-fill" data-k="hp-fill" />
				<span className="hr-bar-name">HP <span className="hr-bar-reg" data-k="hp-reg" /></span><span className="hr-bar-num" data-k="hp-text" />
			</div>
			<div className="hr-bar hr-bar-mp" title="Mana, and what it regenerates a second">
				<i className="hr-bar-fill" data-k="mp-fill" />
				<span className="hr-bar-name">MP <span className="hr-bar-reg" data-k="mp-reg" /></span><span className="hr-bar-num" data-k="mp-text" />
			</div>
		</div>
	);
}

/* During a run the level and XP move as kills land (the boss's carries the clear), read
 * off the sim each frame like the vitals — so nothing is left to arrive on the way back. */
function LiveHero({ levels, read }) {
	const ref = useRef(null);
	const readRef = useRef(read);
	readRef.current = read;
	useEffect(() => {
		let raf = 0, last = "";
		const el = ref.current, lv = el.querySelector(".fg-label-soft"), bar = el.querySelector(".hr-xp"), fill = bar.firstChild;
		const frame = () => {
			const h = readRef.current();
			if (h && `${h.level}|${h.xp}` !== last) {
				last = `${h.level}|${h.xp}`;
				const { into, span } = xpProgress(levels, h.xp);
				lv.textContent = `Level ${h.level}`;
				fill.style.width = `${span ? (100 * into) / span : 100}%`;
				bar.setAttribute("aria-valuenow", span ? into : 1);
				bar.setAttribute("aria-valuemax", span || 1);
				bar.title = span ? `${into} / ${span} XP` : "Top level";
			}
			raf = requestAnimationFrame(frame);
		};
		frame();
		return () => cancelAnimationFrame(raf);
	}, [levels]);
	return (
		<span className="hr-live-hero" ref={ref}>
			<span className="fg-label-soft" />
			<span className="hr-xp" role="meter" aria-label="Experience" aria-valuemin={0}><i /></span>
		</span>
	);
}

/* How far into its level a character is. The server's table decides the level. */
function XpBar({ levels, xp }) {
	if (!levels) return null;
	const { into, span } = xpProgress(levels, xp);
	const label = span ? `${into} / ${span} XP` : "Top level";
	return (
		<span className="hr-xp" role="meter" aria-label="Experience" aria-valuemin={0}
			aria-valuemax={span || 1} aria-valuenow={span ? into : 1} aria-valuetext={label} title={label}>
			<i style={{ width: `${span ? (100 * into) / span : 100}%` }} />
		</span>
	);
}

/* The loot rule the panels say (the server's; an older server sends none, so the
 * same numbers stand in). */
function lootRule(view) {
	return { per_mod: 0.15, per_level: 0.10, xp_per_mod: 0.10, start_mods: 3, ...(view.loot_rule || {}) };
}
/* Why this character cannot enter a rift yet (a rift opened by clearing another), or null. */
function riftShut(view, d, char) {
	if (!d?.requires || (char?.cleared || []).includes(d.requires)) return null;
	const need = (view.dungeons || []).find((x) => x.id === d.requires);
	return `Fell ${need?.boss_name || "the boss"} in ${need?.name || "the first rift"} with this character to open ${d.name}.`;
}

/* How a run ended, as one notification (text, tone) — or null. A CLEAR says nothing
 * on the way back (owner's ask, 2026-11-18): the run already said "cleared" when
 * the boss fell, with the time. */
function outcomeNotice(r) {
	if (r.status === "completed") return null;
	const time = r.timeTicks != null ? ` Time ${formatRiftTime(r.timeTicks)}.` : "";
	if (r.practice) return [{ completed: "Dream Rift complete.", recalled: "Dream Rift left.", dead: "Dream Rift failed." }[r.status]
		+ time + " Nothing changed; your character is safe.", r.status === "dead" ? "bad" : "info"];
	if (r.status === "dead") return [`Your ${className(r.classId)} has fallen. Everything it carried is gone; the vault is untouched.`, "bad"];
	return ["Recalled to town.", "info"];   // nothing about what came back (owner's ask)
}

/* The notifications: the newest few in the top left, each fading after a few
 * seconds; the button opens every one of them again. */
const NOTICE_MS = 6000;
function Notices({ list, onReport }) {
	const [open, setOpen] = useState(false);
	const [now, setNow] = useState(() => Date.now());
	const live = list.filter((n) => now - n.at < NOTICE_MS);
	useEffect(() => {
		if (!live.length) return undefined;
		const id = setInterval(() => setNow(Date.now()), 500);
		return () => clearInterval(id);
	}, [live.length, list]);
	if (!list.length) return null;
	return (
		<div className={"hr-notices" + (open ? " open" : "")}>
			<button className="hr-notices-btn" aria-expanded={open} onClick={() => setOpen((o) => !o)}
				title={open ? "Hide messages" : "Show every message"}>{open ? "Hide" : `Log ${list.length}`}</button>
			{open
				? <ol className="hr-notice-log fg-panel" aria-label="Messages">
					{[...list].reverse().map((n) => <li key={n.id} className={"hr-notice tone-" + n.tone + (n.report ? " has-report" : "")}>
						{n.report && onReport ? <button className="hr-notice-open" onClick={() => onReport(n.report)}
							title="Open this run's summary">{n.text}<span className="hr-notice-more">Summary ›</span></button> : n.text}</li>)}</ol>
				: <div className="hr-notice-live" role="status" aria-live="polite">
					{live.slice(-5).map((n) => <div key={n.id} className={"hr-notice tone-" + n.tone}
						style={{ animationDelay: `${Math.min(0, n.at - Date.now())}ms` }}>{n.text}</div>)}</div>}
		</div>
	);
}


/* A canvas's backing size and the tile size: about 16 x 12 tiles of view. */
function fitCanvas(cv) {
	const dpr = window.devicePixelRatio || 1, r = cv.getBoundingClientRect();
	cv.width = Math.max(1, Math.round(r.width * dpr));
	cv.height = Math.max(1, Math.round(r.height * dpr));
	return Math.max(18, Math.floor(Math.min(cv.height / 12, cv.width / 16)));
}

// ── the town ────────────────────────────────────────────────────────────────
/* The plaza, walked at the same fixed 60 Hz step as the fight and drawn between
 * ticks the same way. `st` lives in the page, so the town keeps where you stood. */
function Town({ st, notes, ready, onUse, onNear, onLift, gear, level, classId, floor = [], floorAt }) {
	const canvasRef = useRef(null);
	const cb = useRef(null);
	cb.current = { ready, onUse, onNear, onLift };
	// The town's ground as the plaza draws it: each item where it was put down (one
	// whose spot this page never saw lies by the spawn).
	st.floor = floor.map((it) => ({ key: it.item_id, ...(floorAt.get(it.item_id) || { x: SPAWN.x + 0.8, y: SPAWN.y + 0.6 }),
		color: it.kind === "unique" ? UNIQUE_COLOR : it.kind === "key" ? "#f0d27a" : TIER_COLORS[it.tier] || TIER_COLORS[1], name: nameOf(it) }));
	const gearKey = JSON.stringify([gear.map((g) => [g.base_id, g.tier, g.enchants]), level]);
	useEffect(() => { setTownGear(st, gear, level, classId); }, [gearKey, classId]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		const cv = canvasRef.current;
		const g = cv.getContext("2d");
		const keys = new Set();
		const mouse = { x: 0, y: 0, down: false };
		let px = 32, raf = 0, prev = null, lastNear, ability = false, cam = { ox: 0, oy: 0 };
		// The whole plaza is always in view: where everything is should never be a search.
		const fit = () => {
			fitCanvas(cv);
			px = Math.max(12, Math.min(cv.height / (st.h + 0.4), cv.width / (st.w + 0.4)));
			cam = camera(st, cv.width, cv.height, px);          // aim is right before the first frame
		};
		const ro = new ResizeObserver(fit);
		ro.observe(cv);
		fit();

		const tick = () => {
			prev = [st.p.x, st.p.y];
			let mx = 0, my = 0;
			for (const k of keys) { const d = dirOf(k); if (d) { mx += d[0]; my += d[1]; } }
			stepTown(st, { mx: Math.sign(mx), my: Math.sign(my), ax: (mouse.x - cam.ox) / px - st.p.x,
				ay: (mouse.y - cam.oy) / px - st.p.y, fire: mouse.down || livePrefs.current.auto, ability });
			ability = false;
			if (st.near !== lastNear) { lastNear = st.near; cb.current.onNear(st.near); }
		};
		let acc = 0, last = performance.now();
		const frame = (now) => {
			acc += Math.min(250, now - last);
			last = now;
			while (acc >= STEP_MS) { acc -= STEP_MS; tick(); }
			const a = acc / STEP_MS;
			const atPos = (o) => (o === st.p && prev ? { x: prev[0] + (o.x - prev[0]) * a, y: prev[1] + (o.y - prev[1]) * a } : o);
			const list = notes.current;
			while (list.length && list[0].until < st.tick) list.shift();
			const station = STATIONS.find((s) => s.id === st.near);
			const pp = atPos(st.p);
			cam = camera(st, cv.width, cv.height, px, pp);
			drawTown(g, st, { width: cv.width, height: cv.height, px, at: atPos, notes: list, dps: (q) => postDps(st, q),
				auto: livePrefs.current.auto, ui: livePrefs.current.ui,
				aim: { x: (mouse.x - cam.ox) / px - pp.x, y: (mouse.y - cam.oy) / px - pp.y },
				prompt: st.nearFloor ? `E — Pick up ${st.floor.find((f) => f.key === st.nearFloor)?.name || "it"}`
					: promptFor(station, !["portal", "dream"].includes(station?.kind) || cb.current.ready) });
			raf = requestAnimationFrame(frame);
		};
		raf = requestAnimationFrame(frame);
		// DEV ONLY (stripped from a production build), like the dungeon's hook.
		if (import.meta.env.DEV) window.__halcyonTown = { st, advance: (n) => { for (let i = 0; i < n; i++) tick(); return st.near; } };

		const typing = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "");
		const onKeyDown = (e) => {
			if (typing(e)) return;
			if (dirOf(e.code)) { keys.add(e.code); e.preventDefault(); return; }
			if (e.repeat) return;
			const act = actionOf(e.code);
			if (act === "interact") {
				if (st.nearFloor) { cb.current.onLift(st.nearFloor); return; }   // what lies here comes first
				const s = STATIONS.find((x) => x.id === st.near);
				if (s) cb.current.onUse(s);
			} else if (act === "auto") toggleAuto();
			else if (act === "ability") { ability = true; e.preventDefault(); }
		};
		const onKeyUp = (e) => keys.delete(e.code);
		const onBlur = () => { keys.clear(); mouse.down = false; };
		const toCanvas = (e) => {
			const r = cv.getBoundingClientRect(), dpr = cv.width / Math.max(1, r.width);
			mouse.x = (e.clientX - r.left) * dpr; mouse.y = (e.clientY - r.top) * dpr;
		};
		const onMove = (e) => toCanvas(e);
		const onDown = (e) => { toCanvas(e); if (e.button === 0) mouse.down = true; if (e.button === 2) ability = true; };
		const onUp = (e) => { if (e.button === 0) mouse.down = false; };
		const noMenu = (e) => e.preventDefault();
		window.addEventListener("keydown", onKeyDown);
		window.addEventListener("keyup", onKeyUp);
		window.addEventListener("blur", onBlur);
		window.addEventListener("mouseup", onUp);
		cv.addEventListener("mousemove", onMove);
		cv.addEventListener("mousedown", onDown);
		cv.addEventListener("contextmenu", noMenu);
		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			window.removeEventListener("keydown", onKeyDown);
			window.removeEventListener("keyup", onKeyUp);
			window.removeEventListener("blur", onBlur);
			window.removeEventListener("mouseup", onUp);
			cv.removeEventListener("mousemove", onMove);
			cv.removeEventListener("mousedown", onDown);
			cv.removeEventListener("contextmenu", noMenu);
		};
	}, [st, notes]);

	return <canvas ref={canvasRef} className="hr-canvas hr-canvas-town"
		aria-label="The town. Walk with WASD, shoot with the mouse; press E at the vault, forge, Dream Rift gate or portal." />;
}

// ── the dungeon ─────────────────────────────────────────────────────────────
function Dungeon({ run, client, onEnd, notify, tips, onDeeper }) {
	const canvasRef = useRef(null);
	const notifyRef = useRef(notify);
	notifyRef.current = notify;
	const onDeeperRef = useRef(onDeeper);
	onDeeperRef.current = onDeeper;
	// What lies within reach (the bags and what the player put down), shown as slots in
	// the stage's bottom right; and the bag under the mouse, named in a tooltip.
	const [loot, setLoot] = useState([]);
	const [hover, setHover] = useState(null);
	const lootApi = useRef(null);

	useEffect(() => {
		const cv = canvasRef.current;
		const g = cv.getContext("2d");
		const st = createSim(run.dungeon, run.gear, run.hero);
		const ctl = run.ctl;
		if (run.carry) Object.assign(st.p, run.carry);   // a level deeper: as you left the last one
		ctl.st = st;                                 // the side panel's HP and MP bars read it live
		const keys = new Set();
		const mouse = { x: 0, y: 0, down: false, cx: 0, cy: 0, over: false };
		const want = [];                             // takes asked for from the loot panel, one a tick
		let lootKey = "", hoverKey = "";
		const edge = { ability: false, interact: false, recall: false, potion: false };
		let px = 32, raf = 0, ended = false;
		const modNames = runModRows(run).map((m) => m.name);
		// Where each moving thing was before the last tick, so a frame can draw it part
		// of the way to where it is now (the sim steps at 60 Hz; a screen may run at 144).
		let prev = new WeakMap(), alpha = 1;
		let cam = camera(st, 1, 1, px, st.p, true);              // the camera of the last drawn frame
		// DEV ONLY (stripped from a production build): the live sim, and a seam for a
		// scripted driver, so a whole run can be played through the real page.
		if (import.meta.env.DEV) window.__halcyon = { st, drive: null };

		const note = (text, tone = "info") => notifyRef.current(text, tone);
		const specOf = (dropId) => { const d = run.dungeon.drops[dropId]; return { ...d, kind: run.bases[d.base_id]?.kind || "standard" }; };
		// Everything in reach, nearest bag first: what the loot panel shows.
		const inReach = () => {
			const out = [];
			const d2 = (o) => (o.x - st.p.x) ** 2 + (o.y - st.p.y) ** 2;
			for (const b of [...st.bags].sort((x, y) => d2(x) - d2(y))) if (d2(b) <= REACH * REACH)
				for (const id of b.drops) out.push({ key: `d:${id}`, take: id, item: { ...specOf(id), item_id: `drop:${id}` } });
			for (const f of st.floor) if (d2(f) <= REACH * REACH) {
				const it = ctl.floor.get(f.key);
				if (it) out.push({ key: `f:${f.key}`, lift: f.key, item: it });
			}
			return out;
		};
		lootApi.current = {
			take: (entry) => { if (!want.some((w) => w.key === entry.key)) want.push(entry); },
			takeAll: () => { for (const e of inReach()) if (!want.some((w) => w.key === e.key)) want.push(e); },
		};
		let dpr = 1;
		const resize = () => { px = fitCanvas(cv); dpr = cv.width / Math.max(1, cv.getBoundingClientRect().width); };
		// A bag's best item (unique, else the highest tier), for its color.
		const bests = new WeakMap();
		const bagBest = (b) => {
			const key = b.drops.join(","), had = bests.get(b);
			if (had && had.key === key) return had;
			const specs = b.drops.map(specOf);
			const best = { key, unique: specs.some((d) => d.kind === "unique"), tier: Math.max(1, ...specs.map((d) => d.tier || 1)) };
			bests.set(b, best);
			return best;
		};
		const ro = new ResizeObserver(resize);
		ro.observe(cv);
		resize();

		// The nearest thing E would take: a loot bag or an item the player put down.
		const nearestLoot = () => {
			let best = null, bd = REACH * REACH;
			for (const b of st.bags) {
				const d = (b.x - st.p.x) ** 2 + (b.y - st.p.y) ** 2;
				if (d <= bd) { bd = d; best = { bag: b }; }
			}
			for (const f of st.floor) {
				const d = (f.x - st.p.x) ** 2 + (f.y - st.p.y) ** 2;
				if (d <= bd) { bd = d; best = { floor: f }; }
			}
			return best;
		};

		const input = () => {
			let mx = 0, my = 0;
			for (const k of keys) { const d = dirOf(k); if (d) { mx += d[0]; my += d[1]; } }
			const { ox, oy } = cam;                    // aim through what the player SEES
			const loot = edge.interact ? nearestLoot() : null;
			let take = null, lift = null;
			if (loot && ctl.room()) { if (loot.bag) take = loot.bag.drops[0]; else lift = loot.floor.key; }
			else if (loot) note("Your bag is full.", "bad");
			else if (want.length) {
				const w = want.shift();
				if (!ctl.room()) { want.length = 0; note("Your bag is full.", "bad"); }
				else if (w.take) take = w.take; else lift = w.lift;
			}
			const out = { mx: Math.sign(mx), my: Math.sign(my), ax: (mouse.x - ox) / px - st.p.x, ay: (mouse.y - oy) / px - st.p.y,
				fire: mouse.down || livePrefs.current.auto, ability: edge.ability, take, lift, drop: ctl.drops.shift() || null,
				recall: edge.recall, enter: edge.interact && !loot, potion: edge.potion };
			if (ctl.recall) { out.recall = true; ctl.recall = false; }      // Recall / Main menu in the game menu
			edge.ability = edge.interact = edge.recall = edge.potion = false;
			return out;
		};

		const handle = (ev) => {
			if (ev.type === "level") note(`Level ${ev.level}!`, "good");
			if (ev.type === "phoenix") note("The Phoenix Feather caught you at 1 HP.", "good");
			if (ev.type === "kill") ctl.kills = (ctl.kills || 0) + 1;
			if (ev.type === "damage") ctl.taken = (ctl.taken || 0) + ev.amount;
			if (ev.type === "deeper") { onDeeperRef.current?.({ offers: st.offers, from: st.depth, mods: run.dungeon.mods || [] }); return; }
			if (ev.type === "cleared") {
				const time = st.bossTimeTicks != null ? ` ${formatRiftTime(st.bossTimeTicks)}` : "";
				// The log keeps this line; once the run is over, clicking it opens the run's summary.
				notifyRef.current(`${run.practice ? "Dream Rift" : run.dungeon.name}${st.depth > 1 ? ` level ${st.depth}` : ""} cleared!${time}${ev.xp > 0 ? ` +${ev.xp} XP` : ""}`,
					"good", { runId: run.run_id });
			}
			if (ev.type === "death") {
				// The graveyard's death screen: what killed it and the run's tallies (the
				// server adds what it wore, where, and the rift's facts of its own).
				const h = st.lastHit;
				client.report({ ...ev, summary: { src: h?.src || "", hit: h?.dmg || 0, taken: ctl.taken || 0,
					kills: ctl.kills || 0, ticks: (ctl.ticksDone || 0) + st.tick } });
				return;
			}
			if (ev.type === "lift") {
				const it = ctl.floor.get(ev.key), slot = ctl.lift(ev.key);
				if (slot === undefined) return;
				client.report({ type: "pickup_item", ...(it.fresh ? { drop: it.drop } : { item: it.item_id }), slot });
				if (it.kind === "unique") note(`Picked up ${nameOf(it)}`, "unique");
				return;
			}
			if (ev.local) return;
			if (ev.type === "pickup") {
				const d = run.dungeon.drops[ev.drop];
				const slot = ctl.take(ev.drop, d);
				if (slot === undefined) return;            // input() never takes into a full bag
				client.report({ ...ev, slot });
				if (run.bases[d.base_id]?.kind === "unique") note(`Picked up ${nameOf({ ...d, kind: "unique" })}`, "unique");
				return;
			}
			client.report(ev.type === "kill" && ev.enemy === run.dungeon.boss
				? { ...ev, elapsed_ticks: st.bossTimeTicks } : ev);
		};

		const finish = (status) => {
			ended = true;
			ctl.ended = true;
			setLoot([]); setHover(null);
			client.flush();
			const h = st.hero;
			// What came back is what is still carried (an item put down and left is gone).
			setTimeout(() => onEnd({ status, runId: run.run_id, items: ctl.items, realm: run.realm, dungeonName: run.dungeon.name,
				classId: run.class_id || st.classId, practice: run.practice, timeTicks: st.bossTimeTicks,
				heroXp: h.xp, level: h.level, startLevel: run.startLevel ?? h.startLevel,
				lastHit: st.lastHit || null, depth: st.depth, mods: run.dungeon.mods || [],
				kills: ctl.kills || 0, taken: ctl.taken || 0, ticks: (ctl.ticksDone || 0) + st.tick, maxHp: st.stats.maxHp }),
				status === "dead" ? 1400 : 700);
		};

		const tick = () => {
			prev = new WeakMap();
			prev.set(st.p, [st.p.x, st.p.y]);
			for (const e of st.enemies) if (e.hp > 0) prev.set(e, [e.x, e.y]);
			for (const b of st.bullets) prev.set(b, [b.x, b.y]);
			const drive = import.meta.env.DEV && window.__halcyon?.drive;
			const gear = ctl.gear;                      // a swap made in the side panel
			ctl.gear = null;
			step(st, gear ? { ...(drive ? drive(st) : input()), gear } : drive ? drive(st) : input());

			for (const ev of st.events) handle(ev);
			if (st.status === "dead" || st.status === "recalled" || st.status === "complete") {
				finish(st.status === "complete" ? "completed" : st.status);
			}
		};

		// What is in reach is in the loot panel; the canvas keeps only the way out.
		const by = (o) => o && Math.hypot(o.x - st.p.x, o.y - st.p.y) <= REACH;
		const bagHint = () => (nearestLoot() ? []
			: by(st.portal) ? [{ text: `${keysOf("interact")}: leave ${run.dungeon.name}`, color: "#9fe7ff" }]
			: by(st.deeper) ? [{ text: `${keysOf("interact")}: go deeper`, color: "#ff9f5a" }] : []);

		// DEV ONLY: step the real loop without frames (a hidden tab gets none).
		if (import.meta.env.DEV) window.__halcyon.advance = (n) => { for (let i = 0; i < n && !ended; i++) tick(); return st.status; };

		let acc = 0, last = performance.now();
		const frame = (now) => {
			acc += Math.min(250, now - last);
			last = now;
			while (acc >= STEP_MS && !ended) { acc -= STEP_MS; tick(); }
			// The loot panel and the bag tooltip: React hears only when what they show changes.
			const near = ended ? [] : inReach();
			const k = near.map((e) => e.key).join(",");
			if (k !== lootKey) { lootKey = k; setLoot(near); }
			let hv = null;
			if (mouse.over && !ended) {
				const wx = (mouse.x - cam.ox) / px, wy = (mouse.y - cam.oy) / px;
				const bag = st.bags.find((b) => (b.x - wx) ** 2 + (b.y - wy) ** 2 < 0.5 * 0.5);
				if (bag) hv = { key: `${bag.enemy}:${bag.drops.join(",")}`, x: mouse.cx, y: mouse.cy, items: bag.drops.map(specOf) };
			}
			const hk = hv ? `${hv.key}@${Math.round(hv.x)},${Math.round(hv.y)}` : "";
			if (hk !== hoverKey) { hoverKey = hk; setHover(hv); }
			alpha = ended ? 1 : acc / STEP_MS;
			const at = (o) => {
				const q = prev.get(o);
				return q ? { x: q[0] + (o.x - q[0]) * alpha, y: q[1] + (o.y - q[1]) * alpha } : o;
			};
			const pp = at(st.p);
			cam = camera(st, cv.width, cv.height, px, pp, true);
			const pf = livePrefs.current;
			draw(g, st, { width: cv.width, height: cv.height, px, at,
				aim: { x: (mouse.x - cam.ox) / px - pp.x, y: (mouse.y - cam.oy) / px - pp.y },
				notes: ended ? [] : bagHint(), bagBest, calm: pf.calm, ui: pf.ui, dpr,
				bossName: run.dungeon.boss_name || "The boss", keys: { potion: keyLabel(pf.keys.potion?.[0]) },
				mods: modNames, auto: pf.auto });
			raf = requestAnimationFrame(frame);
		};
		raf = requestAnimationFrame(frame);

		const onKeyDown = (e) => {
			if (dirOf(e.code)) { keys.add(e.code); e.preventDefault(); return; }
			if (e.repeat || /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "")) return;
			const act = actionOf(e.code);
			if (act === "ability") { edge.ability = true; e.preventDefault(); }
			else if (act === "interact") edge.interact = true;
			else if (act === "recall") edge.recall = true;
			else if (act === "potion") edge.potion = true;
			else if (act === "auto") note(toggleAuto() ? "Auto-fire on" : "Auto-fire off");
			else if (act === "takeAll") lootApi.current?.takeAll();
		};
		const onKeyUp = (e) => keys.delete(e.code);
		const toCanvas = (e) => {
			const r = cv.getBoundingClientRect(), dpr = cv.width / Math.max(1, r.width);
			mouse.x = (e.clientX - r.left) * dpr; mouse.y = (e.clientY - r.top) * dpr;
			mouse.cx = e.clientX; mouse.cy = e.clientY; mouse.over = true;
		};
		const onMove = (e) => toCanvas(e);
		const onLeave = () => { mouse.over = false; };
		const onDown = (e) => { toCanvas(e); if (e.button === 0) mouse.down = true; if (e.button === 2) edge.ability = true; };
		const onUp = (e) => { if (e.button === 0) mouse.down = false; };
		const onBlur = () => { keys.clear(); mouse.down = false; };
		const noMenu = (e) => e.preventDefault();
		window.addEventListener("keydown", onKeyDown);
		window.addEventListener("keyup", onKeyUp);
		window.addEventListener("blur", onBlur);
		window.addEventListener("mouseup", onUp);
		cv.addEventListener("mousemove", onMove);
		cv.addEventListener("mouseleave", onLeave);
		cv.addEventListener("mousedown", onDown);
		cv.addEventListener("contextmenu", noMenu);
		return () => {
			cancelAnimationFrame(raf);
			ro.disconnect();
			window.removeEventListener("keydown", onKeyDown);
			window.removeEventListener("keyup", onKeyUp);
			window.removeEventListener("blur", onBlur);
			window.removeEventListener("mouseup", onUp);
			cv.removeEventListener("mousemove", onMove);
			cv.removeEventListener("mouseleave", onLeave);
			cv.removeEventListener("mousedown", onDown);
			cv.removeEventListener("contextmenu", noMenu);
		};
	}, [run, client, onEnd]);

	return (
		<>
			<canvas ref={canvasRef} className="hr-canvas hr-canvas-run" aria-label="The dungeon" />
			{loot.length > 0 && (
				<section className="hr-loot fg-panel" aria-label="Loot here">
					<header className="hr-loot-hd">
						<h2 className="fg-label">Loot</h2>
						<button className="btn btn-ghost btn-sm hr-loot-all" onClick={(e) => { lootApi.current?.takeAll(); e.currentTarget.blur(); }}
							title="Take everything here (G)">Take all</button>
					</header>
					<div className="hr-loot-grid">
						{loot.map((e) => {
							const it = e.item, fam = run.bases[it.base_id]?.slot;
							return <button key={e.key} className={`hr-slot has fam-${fam}` + (it.kind === "unique" ? " unique" : "")}
								aria-label={`Take ${nameOf(it)}`}
								onClick={(ev) => { lootApi.current?.take(e); tips.hideTip(); ev.currentTarget.blur(); }}
								onMouseEnter={(ev) => tips.showTip(it, ev.currentTarget)} onMouseLeave={tips.hideTip}>
								<span className="hr-abbr">{ABBR[it.base_id] || "?"}</span>
								{it.kind === "unique" ? <span className="hr-tier hr-star" aria-hidden="true">★{it.tier}</span>
									: it.kind === "key" ? <span className="hr-tier hr-key" aria-hidden="true">⚷</span> : <span className="hr-tier">{it.tier}</span>}
								{it.slot_count > 0 && <span className="hr-dots">{"•".repeat(it.slot_count)}</span>}
							</button>;
						})}
					</div>
					<p className="hr-loot-keys">Click to take · <kbd>E</kbd> the first · <kbd>G</kbd> all</p>
				</section>)}
			{hover && (
				<div className="hr-bag-tip fg-panel" role="tooltip" style={{ left: hover.x + 14, top: hover.y + 14 }}>
					<h3 className="fg-label">Loot bag</h3>
					<ul>{hover.items.map((it, i) => <li key={i} className={it.kind === "unique" ? "unique" : ""}>{nameOf(it)}
						{it.slot_count > 0 && <small> · {it.slot_count} slot{it.slot_count > 1 ? "s" : ""}</small>}</li>)}</ul>
				</div>)}
		</>
	);
}
