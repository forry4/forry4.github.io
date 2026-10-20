// The guide's logic, kept out of the component so it can be unit-tested with plain
// `node --test` (webapp/test/unit/astralguide.test.mjs): the vocabulary of effects,
// the text linker, the synergy index, the global search, and the two charts' maths.
//
// Everything here is DERIVED from the wiki payload (webapp/public/data/astral-guide.json).
// The hand-written layer — tier lists, starting picks, build notes — is editorial.js.

export const ELEMENTS = ["Fire", "Ice", "Electric", "Poison", "Neutral"];
export const RARITIES = ["Common", "Heroic", "Mythic", "Astral"];

// THE EFFECT VOCABULARY. Each entry: canonical name, element, the pattern that finds
// it in the wiki's prose (singular, plural and the variant forms auras transform it
// into), and `cap` when only the Capitalized word is the effect — "Target" and
// "Shield" are also ordinary English ("targets the nearest enemy").
export const KEYWORDS = [
	{ k: "Burn", el: "Fire", re: "burns?" },
	{ k: "Combustion", el: "Fire", re: "combustions?" },
	{ k: "Embers", el: "Fire", re: "(?:blue )?embers?" },
	{ k: "Wisps", el: "Fire", re: "(?:venomous |kamikaze |giant )?wisps?" },
	{ k: "Ignition", el: "Fire", re: "(?:poison )?ignit(?:ion|iton)s?" },
	{ k: "Fire Shield", el: "Fire", re: "fire[- ]shields?" },
	{ k: "Freeze", el: "Ice", re: "freezes?" },
	{ k: "Frostbite", el: "Ice", re: "frostbites?" },
	{ k: "Ice Idol", el: "Ice", re: "(?:ice|fire) idol(?:e|s)?" },
	{ k: "Snowflake", el: "Ice", re: "snowflakes?" },
	{ k: "Ice Fragment", el: "Ice", re: "ice fragments?" },
	{ k: "Ice Sword", el: "Ice", re: "ice swords?" },
	{ k: "Poison", el: "Poison", re: "poisons?(?! affinity)" },
	{ k: "Slime", el: "Poison", re: "(?:lava |giant |flying )?slimes?" },
	{ k: "Sapling", el: "Poison", re: "(?:lightning )?saplings?" },
	{ k: "Toxic Gas", el: "Poison", re: "toxic gas(?:es)?" },
	{ k: "Meteor", el: "Poison", re: "(?:electric )?meteors?" },
	{ k: "Electrify", el: "Electric", re: "electrif(?:y|ies|ied|ying)" },
	{ k: "Spark", el: "Electric", re: "(?:poisonous )?sparks?" },
	{ k: "Plasma", el: "Electric", re: "(?:fire )?plasmas?" },
	{ k: "Nimbus", el: "Electric", re: "(?:frost )?nimbus(?:es|'s)?" },
	{ k: "Lightning Orb", el: "Electric", re: "lightning orbs?" },
	{ k: "Thunder Strike", el: "Electric", re: "(?:thunder|lightning) strikes?" },
	{ k: "Vulnerability", el: "Neutral", re: "vu(?:l)?nerabilit(?:y|ies)" },
	{ k: "Pacification", el: "Neutral", re: "pacifications?" },
	// Singular only: the wiki writes the effect "apply 3 Target", and "Targets" is the verb.
	{ k: "Target", el: "Neutral", re: "target", cap: true },
	{ k: "Missiles", el: "Neutral", re: "(?:giant |explosive )?missiles?" },
	{ k: "Yalee", el: "Neutral", re: "(?:thick |freeze |electrify )?yalee(?:s|'s)?(?! madness| skyship| air balloon)" },
	{ k: "Spirit Sword", el: "Neutral", re: "spirit swords?" },
	{ k: "Critical Hit", el: "Neutral", re: "critical hits?" },
	{ k: "Random Effect", el: "Neutral", re: "random effects?" },
	{ k: "Shield", el: "Neutral", re: "shields?", cap: true },
	{ k: "Barrier", el: "Neutral", re: "barriers?", cap: true },
	{ k: "Enrage", el: "Neutral", re: "enrage" },
	{ k: "Velocity", el: "Neutral", re: "velocity" },
	{ k: "Movespeed", el: "Neutral", re: "move ?speed|movement speed" },
	{ k: "Thunder Dash", el: "Neutral", re: "thunder dash" },
	{ k: "Yalee Madness", el: "Neutral", re: "yalee madness" },
	{ k: "Infinite Mana", el: "Neutral", re: "infinite mana" },
];
export const KEYWORD = Object.fromEntries(KEYWORDS.map((x) => [x.k, x]));

// What each buff does, for the drawer. The wiki's Elemental Effect page covers the
// stacking effects; these six are named in aura text but defined nowhere on it.
const BUFF_NOTES = {
	"Shield": "A short protective state granted by gambits, auras and summons.",
	"Barrier": "A protective buff granted by gambits and auras.",
	"Enrage": "A damage buff granted by gambits, auras and prowess.",
	"Velocity": "A speed buff granted by gambits, auras and prowess.",
	"Movespeed": "Faster movement for a few seconds.",
	"Thunder Dash": "An empowered dash granted by auras, prowess and echoes.",
	"Yalee Madness": "A buff granted by the Yalee Madness gambit.",
	"Infinite Mana": "Spells cost no mana while it lasts.",
	"Critical Hit": "A hit that deals 50% more damage by default (multiplicative).",
	"Random Effect": "Adds stacks of a random effect.",
};

const esc = (s) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

// Spells that auras and imprints CAST, matched in their prose. A name under five
// letters ("Sol", "Fax", "Luna") is an ordinary word too often to link safely.
const SPELL_ALIASES = { "cryogenic sword": "Cold-Steel Sword", "eye of judgment": "Eye of Judgment" };

export function spellMatcher(spells) {
	const names = spells.map((s) => s.name).filter((n) => n.length >= 5);
	const forms = new Map();
	for (const n of names) {
		const stem = n.endsWith("s") ? n.slice(0, -1) : n;
		forms.set(stem.toLowerCase(), n);
		forms.set(n.toLowerCase(), n);
	}
	for (const [a, n] of Object.entries(SPELL_ALIASES)) if (names.includes(n)) forms.set(a, n);
	const pats = [...forms.keys()].sort((a, b) => b.length - a.length).map((f) => `${esc(f)}s?`);
	return { forms, source: pats.join("|") };
}

// ONE regex over spells AND keywords, longest alternative first, so "Meteor Blades"
// links the spell and not the Meteor effect inside it.
export function makeLinker(spells) {
	const sm = spellMatcher(spells);
	const kwSrc = KEYWORDS.map((x) => `(?<k_${x.k.replace(/\W/g, "_")}>${x.re})`).join("|");
	const re = new RegExp(`(?<![\\w-])(?:(?<spell>${sm.source})|${kwSrc})(?![\\w-])`, "gi");
	const resolveSpell = (text) => {
		const t = text.toLowerCase();
		return sm.forms.get(t) || sm.forms.get(t.replace(/s$/, "")) || null;
	};
	return function segments(text) {
		const out = [];
		let last = 0;
		for (const m of String(text || "").matchAll(re)) {
			const g = m.groups;
			let seg = null;
			if (g.spell) {
				const name = resolveSpell(g.spell);
				if (name) seg = { t: "spell", name, text: m[0] };
			} else {
				const key = Object.keys(g).find((n) => n.startsWith("k_") && g[n] !== undefined);
				const kw = KEYWORDS.find((x) => `k_${x.k.replace(/\W/g, "_")}` === key);
				if (kw && !(kw.cap && m[0][0] !== m[0][0].toUpperCase())) seg = { t: "kw", k: kw.k, text: m[0] };
			}
			if (!seg) continue;
			if (m.index > last) out.push({ t: "text", text: text.slice(last, m.index) });
			out.push(seg);
			last = m.index + m[0].length;
		}
		if (last < String(text || "").length) out.push({ t: "text", text: text.slice(last) });
		return out;
	};
}

// ── Synergy ────────────────────────────────────────────────────────────────
// Per effect line: which effects it MAKES and which it USES (pays off). The rules are
// the shape of the wiki's own phrasing:
//   "On <trigger>, <effect>"      the trigger clause USES, the effect clause MAKES
//   "Increases <X> damage/..."    USES X
//   "per <X>" / "for each <X>"    USES X
//   "Transforms <X> into <Y>"     USES X, MAKES Y
const TRIGGER = /^(on|when|if|for each|while|after|during|at the|every|when walking)\b/i;
const AMPLIFY_AFTER = /^\s*(damage|duration|time|size|range|fire rate|critical|limit|effect duration)/i;

export function classifyLine(line, segments) {
	const makes = new Set(), uses = new Set();
	const text = String(line || "");
	let cut = -1;
	if (TRIGGER.test(text)) cut = text.indexOf(",");
	let pos = 0;
	for (const s of segments(text)) {
		const start = pos;
		pos += s.text.length;
		if (s.t !== "kw") continue;
		const before = text.slice(0, start);
		const after = text.slice(pos);
		if (cut > 0 && start < cut) { uses.add(s.k); continue; }
		if (AMPLIFY_AFTER.test(after) || /\b(per|for each|with|on enemies with|transforms?)\s+(\d+\s+)?$/i.test(before)
			|| /\bincreases?\s+(the\s+)?$/i.test(before)) { uses.add(s.k); continue; }
		makes.add(s.k);
	}
	// "Transforms Embers into Blue Embers": the second mention is the same family, so a
	// transform reads as a payoff only.
	if (/^transforms?\b/i.test(text)) for (const k of makes) { uses.add(k); makes.delete(k); }
	return { makes, uses };
}

// ── The model: every entity the guide shows, with ids, search text and synergy ──
export const TYPE_LABEL = {
	aura: "Aura", gambit: "Gambit", imprint: "Imprint", spell: "Spell", echo: "Echo",
	summon: "Summon", prowess: "Prowess", boss: "Boss", catalyst: "Void Catalyst",
	telluric: "Telluric Telescope", cursed: "Cursed Telescope", effect: "Effect",
};

const slug = (s) => String(s).toLowerCase().replace(/[^a-z0-9]+/g, "-").replace(/^-|-$/g, "");
export const keyOf = (type, id) => `${type}:${id}`;

const PREFIX_EL = [["Fajro", "Fire"], ["Glacio", "Ice"], ["Venen", "Poison"], ["Elekt", "Electric"], ["Nul", "Neutral"]];

export function imprintKind(imp, castSpells) {
	const t = `${imp.effect} ${imp.transcendence}`;
	if (/voko/i.test(imp.name)) return "Summons an echo";
	if (castSpells.length) return "Casts a spell";
	if (/\bsummons?\b|\bclone\b/i.test(t)) return "Summons";
	if (/more damage|increases? (spell )?damage|damage by \d+%|kill an enemy/i.test(imp.effect)) return "Damage boost";
	if (/\b(restore|buff|gain|attract|movespeed|barrier)/i.test(imp.effect) && !/\bcreates?\b/i.test(imp.effect)) return "Utility";
	return "Creates effects";
}

export function imprintNeeds(imp) {
	const t = imp.effect;
	const needs = [];
	if (/full \w+ affinity|max \w+ affinity/i.test(t)) needs.push("Full affinity");
	if (/costs? 3 mana|cost 3 mana/i.test(t)) needs.push("3-mana spell");
	if (/lvl 10|level 10/i.test(t)) needs.push("Level 10");
	if (/critical/i.test(t)) needs.push("Critical hits");
	if (/electrif|freeze|burn on|with burn|poison on/i.test(t) && /on enemies with|on electrified|with electrify|with freeze/i.test(t)) needs.push("Enemy status");
	return needs;
}

export function buildModel(data, editorial = {}) {
	const segments = makeLinker(data.spells);
	const spellByName = Object.fromEntries(data.spells.map((s) => [s.name, s]));
	const list = [];
	const add = (e) => { e.key = keyOf(e.type, e.id); list.push(e); return e; };
	// A spell named in the text is one it CASTS — unless it is a comparison: the clone
	// imprints make a clone "like pisces clones", which is not a cast of that spell.
	const castsIn = (text) => {
		const found = new Set();
		let pos = 0;
		for (const s of segments(text)) {
			if (s.t === "spell" && !/\blike\s*\(?\s*$/i.test(text.slice(0, pos))) found.add(s.name);
			pos += s.text.length;
		}
		return [...found];
	};
	const syn = (lines) => {
		const makes = new Set(), uses = new Set();
		for (const l of lines) {
			const r = classifyLine(l, segments);
			r.makes.forEach((k) => makes.add(k));
			r.uses.forEach((k) => uses.add(k));
		}
		return { makes: [...makes], uses: [...uses] };
	};

	for (const a of data.auras) {
		const lines = a.tiers.flatMap((t) => t.lines);
		add({ type: "aura", id: slug(a.name), name: a.name, element: a.element,
			rarities: a.tiers.map((t) => t.rarity), astral: a.astral, tiers: a.tiers,
			casts: castsIn(lines.join(" | ")), unique: lines.some((l) => /unique/i.test(l)),
			triggers: auraTriggers(lines), text: lines.join(" "), ...syn(lines) });
	}
	// Gambits are listed per FAMILY: one entity holding every rarity row.
	const fams = new Map();
	for (const g of data.gambits) {
		const id = slug(`${g.element}-${g.family}`);
		if (!fams.has(id)) fams.set(id, { type: "gambit", id, name: g.family, element: g.element, rows: [] });
		fams.get(id).rows.push(g);
	}
	for (const f of fams.values()) {
		const lines = f.rows.map((r) => r.text);
		add({ ...f, rarities: [...new Set(f.rows.map((r) => r.rarity))], triggers: [...new Set(f.rows.map((r) => r.trigger))],
			text: lines.join(" "), ...syn(lines) });
	}
	const echoAlias = editorial.VOKO_ECHO || {};
	for (const i of data.imprints) {
		const casts = castsIn(`${i.effect} ${i.transcendence}`);
		add({ type: "imprint", id: slug(i.name), name: i.name, element: i.element, gambit: i.gambit,
			effect: i.effect, transcendence: i.transcendence, casts, echo: echoAlias[i.name] || null,
			kind: imprintKind(i, casts), needs: imprintNeeds(i),
			text: `${i.effect} ${i.transcendence} ${i.gambit}`, ...syn([i.effect, i.transcendence]) });
	}
	for (const s of data.spells) {
		add({ type: "spell", id: slug(s.name), name: s.name, element: null, ...s,
			text: `${s.desc} ${s.group} ${s.hero || ""} ${s.tags.join(" ")}`, makes: [], uses: [] });
	}
	for (const e of data.echoes) {
		add({ type: "echo", id: slug(e.name), name: e.name, element: null, desc: e.desc, cooldown: e.cooldown,
			trigger: echoTrigger(e), text: `${e.desc} ${e.cooldown}`, ...syn([e.desc]) });
	}
	for (const s of data.summons) {
		add({ type: "summon", id: slug(s.zodiac), name: s.zodiac, element: null, effect: s.effect, desc: s.desc,
			text: `${s.effect} ${s.desc}`, ...syn([s.desc, s.effect]) });
	}
	for (const p of data.prowess) {
		add({ type: "prowess", id: slug(`${p.hero}-${p.name}`), name: p.name, element: null, hero: p.hero,
			path: p.path, effect: p.effect, text: `${p.effect} ${p.hero} ${p.path}`, ...syn(p.effect.split(" · ")) });
	}
	for (const b of data.bosses) {
		add({ type: "boss", id: slug(b.name), name: b.name, element: null, ...b,
			text: `${b.kind} ${b.world} ${b.attacks.map((a) => `${a.name} ${a.text}`).join(" ")} ${b.strategy}`, makes: [], uses: [] });
	}
	for (const c of data.catalyst) {
		add({ type: "catalyst", id: slug(c.name), name: c.name, element: null, ...c,
			text: `${c.desc} ${c.strategy} ${c.row}`, makes: [], uses: [] });
	}
	for (const t of data.telluric) {
		add({ type: "telluric", id: slug(t.name), name: t.name, element: null, ...t, text: `${t.desc} ${t.synergy}`, makes: [], uses: [] });
	}
	for (const t of data.cursed) {
		add({ type: "cursed", id: slug(`${t.kind}-${t.name}`), name: t.name, element: null, ...t, text: `${t.kind} ${t.desc}`, makes: [], uses: [] });
	}
	const glossary = Object.fromEntries(data.effects.map((e) => [normEffect(e.name), e]));
	for (const kw of KEYWORDS) {
		const g = glossary[kw.k];
		add({ type: "effect", id: slug(kw.k), name: kw.k, element: kw.el,
			desc: g ? g.desc : BUFF_NOTES[kw.k] || "", text: g ? g.desc : "", makes: [], uses: [] });
	}

	const byKey = Object.fromEntries(list.map((e) => [e.key, e]));
	// Who makes / uses each effect, and which entities cast each spell.
	const makers = {}, users = {}, castBy = {};
	for (const e of list) {
		for (const k of e.makes || []) (makers[k] ||= []).push(e.key);
		for (const k of e.uses || []) (users[k] ||= []).push(e.key);
		for (const s of e.casts || []) (castBy[s] ||= []).push(e.key);
	}
	for (const e of list) if (e.type === "spell") e.castBy = castBy[e.name] || [];
	for (const e of list) e.hay = haystack(e);
	return { list, byKey, makers, users, castBy, segments, spellByName };
}

// The glossary names a few effects in a different number than the vocabulary.
function normEffect(name) {
	const map = { "Ember": "Embers", "Ice Idols": "Ice Idol", "Slimes": "Slime", "Wisps": "Wisps" };
	return map[name] || name;
}

export function auraTriggers(lines) {
	const t = lines.join(" ").toLowerCase();
	const out = [];
	if (/on spell cast|spell cast/.test(t)) out.push("On cast");
	if (/on spell hit|on each hit|on hit\b/.test(t)) out.push("On hit");
	if (/spell refresh/.test(t)) out.push("On refresh");
	if (/on dash|dashing/.test(t)) out.push("On dash");
	if (/fall attack/.test(t)) out.push("On fall attack");
	if (/critical hit/.test(t)) out.push("Critical");
	if (/when hero is hit|hero gets hit/.test(t)) out.push("When hit");
	if (/enemy death|enemies death|on death|killed/.test(t)) out.push("On kill");
	if (/life is (above|below)|life is full|enemy life is full/.test(t)) out.push("Life threshold");
	if (/mana spent|mana used|max mana|out of mana/.test(t)) out.push("Mana");
	if (/permanent/.test(t)) out.push("Permanent summon");
	if (/increases? (strength|armou?r|max life|attack speed|critical hit chances)/.test(t)) out.push("Stats");
	return out;
}

export function echoTrigger(e) {
	const d = `${e.desc} ${e.cooldown}`.toLowerCase();
	if (/signature spell/.test(d)) return "After signature";
	if (/spell refresh/.test(d)) return "On refresh";
	if (/once per room/.test(d)) return "Once per room";
	if (/during fights|regularly/.test(d)) return "During fights";
	if (/quartz|keys|stars|stone|feather|aura|altar|half-price|price/.test(d)) return "Economy";
	if (/life|hp|resurrect|shield|healing/.test(d)) return "Survival";
	return "Other";
}

function haystack(e) {
	const bits = [e.name, TYPE_LABEL[e.type], e.element, e.text, ...(e.rarities || []), e.kind, e.hero, e.path,
		e.gambit, e.group, e.trigger, ...(e.triggers || []), ...(e.makes || []), ...(e.uses || []), ...(e.casts || [])];
	return bits.filter(Boolean).join(" ").toLowerCase();
}

// ── Search ─────────────────────────────────────────────────────────────────
// Every word must appear somewhere (name, element, rarity, effect text, synergy
// keywords); the NAME decides the order. So "fire astral" lists Astral fire auras,
// "embers" finds everything that makes or uses Embers, and "flame" puts Flame
// Blessing first.
export function search(model, query, { types = null, limit = 60 } = {}) {
	const words = String(query || "").toLowerCase().split(/\s+/).filter(Boolean);
	if (!words.length) return [];
	const out = [];
	for (const e of model.list) {
		if (types && !types.includes(e.type)) continue;
		if (!words.every((w) => e.hay.includes(w))) continue;
		const n = e.name.toLowerCase();
		const q = words.join(" ");
		let score = 0;
		if (n === q) score += 1000;
		else if (n.startsWith(q)) score += 400;
		else if (n.includes(q)) score += 200;
		// A word naming the entity's element, rarity or type ranks exact matches first, so
		// "fire astral" lists Fire Astral auras before an Electric one that makes Fire Plasma.
		const facets = [e.element, TYPE_LABEL[e.type], ...(e.rarities || [])].filter(Boolean).map((x) => x.toLowerCase());
		for (const w of words) {
			if (facets.includes(w)) score += 120;
			if (n.split(/[\s'-]+/).some((p) => p.startsWith(w))) score += 50;
			if ((e.makes || []).some((k) => k.toLowerCase() === w) || (e.uses || []).some((k) => k.toLowerCase() === w)) score += 15;
		}
		score += { effect: 30, aura: 12, imprint: 10, gambit: 10, spell: 8, echo: 8, summon: 8 }[e.type] || 0;
		out.push({ e, score });
	}
	out.sort((a, b) => b.score - a.score || a.e.name.localeCompare(b.e.name));
	return out.slice(0, limit).map((x) => x.e);
}

// A tab's own text filter: the same every-word rule, no ranking.
export const matches = (e, q) => {
	const words = String(q || "").toLowerCase().split(/\s+/).filter(Boolean);
	return words.every((w) => e.hay.includes(w));
};

// ── The charts' maths (Player Stats page: crit = +50% MORE damage; armor 3%/stone,
// capped at 70%; a Life stone is +15) ──────────────────────────────────────
export const critMultiplier = (chancePct, bonusPct) =>
	1 + (Math.min(Math.max(chancePct, 0), 100) / 100) * (bonusPct / 100);

export const armorPct = (stones, extraPct = 0, cap = 70, perStone = 3) =>
	Math.min(cap, Math.max(0, stones * perStone + extraPct));

export const effectiveLife = (life, armor) => life / (1 - Math.min(armor, 99.9) / 100);

// What the NEXT stone of each kind adds in effective life.
export function nextStone(life, armor, { cap = 70, perStone = 3, lifePerStone = 15 } = {}) {
	const now = effectiveLife(life, armor);
	const lifeGain = effectiveLife(life + lifePerStone, armor) - now;
	const armorGain = armor >= cap ? 0 : effectiveLife(life, Math.min(cap, armor + perStone)) - now;
	return { now, lifeGain, armorGain };
}

// The life total at which a Life stone and an Armor stone add the same effective life.
export const breakEvenLife = (armor, perStone = 3, lifePerStone = 15) =>
	(lifePerStone * (1 - armor / 100 - perStone / 100)) / (perStone / 100);

// Damage from the next Strength stone (additive with other "increased" damage) vs the
// next Critical stone (multiplicative), as a fraction of current damage.
export function nextDamageStone(strengthPct, critChancePct, critBonusPct, { str = 5, crit = 2 } = {}) {
	const strGain = str / (100 + strengthPct);
	const before = critMultiplier(critChancePct, critBonusPct);
	const critGain = critMultiplier(critChancePct + crit, critBonusPct) / before - 1;
	return { strGain, critGain };
}

// ── Winning runs (runs.js) ──────────────────────────────────────────────────
// How many runs used each aura / imprint / summon / engine, and how many copies.
// The tier lists' "N wins" badges and the Runs tab's bars both read this, so the
// numbers the page states can only come from the transcribed runs.
export function runUsage(runs) {
	const tally = () => new Map();
	const auras = tally(), imprints = tally(), summons = tally(), engines = tally(), heroes = tally(), spells = tally();
	const bump = (m, name, id) => {
		if (!m.has(name)) m.set(name, { name, runs: new Set(), copies: 0 });
		const e = m.get(name);
		e.runs.add(id);
		e.copies += 1;
	};
	for (const r of runs) {
		r.auras.forEach((a) => bump(auras, a, r.id));
		r.spells.forEach((s) => { bump(spells, s.name, r.id); if (s.imprint) bump(imprints, s.imprint, r.id); });
		if (r.summon) bump(summons, r.summon, r.id);
		r.engines.forEach((e) => bump(engines, e, r.id));
		bump(heroes, r.hero, r.id);
	}
	const rank = (m) => [...m.values()].map((e) => ({ ...e, runs: [...e.runs], n: e.runs.size }))
		.sort((a, b) => b.n - a.n || b.copies - a.copies || a.name.localeCompare(b.name));
	return { auras: rank(auras), imprints: rank(imprints), summons: rank(summons), engines: rank(engines),
		heroes: rank(heroes), spells: rank(spells) };
}

// min / median / max of one stat across runs.
export function statRange(runs, key) {
	const v = runs.map((r) => r[key]).filter((x) => typeof x === "number").sort((a, b) => a - b);
	if (!v.length) return null;
	const mid = v.length >> 1;
	const median = v.length % 2 ? v[mid] : (v[mid - 1] + v[mid]) / 2;
	return { min: v[0], median, max: v[v.length - 1], n: v.length };
}

// Each spell level adds 20% damage: the end screen prints level X as 200%.
export const levelBonus = (level) => level * 20;

export { slug };
export const elementOfImprint = (name) => (PREFIX_EL.find(([p]) => name.startsWith(p)) || [])[1] || "Neutral";
