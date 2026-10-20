"""tools/cache/pages.json (from harvest.py) -> webapp/public/data/astral-guide.json

Parses the Astral Ascent wiki's wikitext into the tables the guide renders. Every
section is parsed from the wiki, never typed here; the only hand-written content in
the guide is the editorial layer (tier lists, starting picks, build notes), which
lives in astralguide/editorial.js next to the page.

Each parser asserts a FLOOR on what it found. The wiki is edited by hand and a
reformatted table parses to nothing rather than to an error, so a section that comes
back empty must fail the build here instead of shipping an empty tab.
"""
import json
import os
import re
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", ".."))
SRC = os.path.join(HERE, "cache", "pages.json")
DST = os.path.join(ROOT, "webapp", "public", "data", "astral-guide.json")

ELEMENTS = ["Fire", "Ice", "Electric", "Poison", "Neutral"]
RARITIES = ["Common", "Heroic", "Mythic", "Astral"]

# The wiki's text was saved through a lossy encoding in a few places.
MOJIBAKE = {"Doppelg�nger": "Doppelgänger", "DoppelG�nger": "Doppelgänger",
	"360�": "360°", "Na�ad": "Naïad", "N�": "N°", "Don�t": "Don't"}


def clean(s):
	"""Wikitext -> plain text, keeping line breaks."""
	if s is None:
		return ""
	for a, b in MOJIBAKE.items():
		s = s.replace(a, b)
	s = s.replace("�", "")
	# <nowiki> marks text that LOOKS like markup but is content (Libra's attacks are
	# named `{{exec_func: "boot_sequence"}}`), so it must survive the template strip.
	s = re.sub(r"<nowiki>(.*?)</nowiki>", lambda m: m.group(1).replace("{{", "").replace("}}", ""), s)
	s = re.sub(r"<ref[^>]*/>", "", s)
	s = re.sub(r"<ref[^>]*>.*?</ref>", "", s, flags=re.S)
	s = re.sub(r"<br\s*/?>", "\n", s)
	s = re.sub(r"\[\[(?:File|Image):[^\]]*\]\]", "", s)
	s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
	s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s)
	s = re.sub(r"\[https?://\S+ ([^\]]*)\]", r"\1", s)
	s = re.sub(r"\{\{[^{}]*\}\}", "", s)
	s = re.sub(r"<[^>]+>", "", s)
	s = s.replace("'''", "").replace("''", "").replace("&nbsp;", " ")
	s = re.sub(r"[ \t]+", " ", s)
	return "\n".join(l.strip() for l in s.split("\n")).strip()


def tidy(line):
	"""One effect line: no bullet, normalised spacing around the cooldown dashes."""
	line = clean(line).lstrip("*#: ").strip()
	line = re.sub(r"\s*-\s*(\d+ ?second)", r" — \1", line)
	line = re.sub(r"\s+-\s+", " — ", line)
	line = re.sub(r"\s{2,}", " ", line)
	return line[:1].upper() + line[1:] if line else line


def floor(name, items, n):
	if len(items) < n:
		raise SystemExit(f"{name}: parsed {len(items)}, expected at least {n} — did the wiki page change shape?")
	return items


def rows_of(table):
	return [r for r in re.split(r"\n\|-[^\n]*", table)]


def sections(text, level):
	"""[(heading, body)] for headings of exactly `level` '=' signs."""
	eq = "=" * level
	parts = re.split(rf"^{eq}(?!=)\s*(.*?)\s*{eq}\s*$", text, flags=re.M)
	return [(clean(parts[i]), parts[i + 1]) for i in range(1, len(parts) - 1, 2)]


# ── Auras ────────────────────────────────────────────────────────────────────
def parse_auras(p):
	text = p["Auras"]["text"]
	out = []
	for head, body in sections(text, 3):
		m = re.match(r"(\w+) Element Auras", head)
		if not m:
			continue
		element = m.group(1)
		for row in rows_of(body)[1:]:
			nm = re.search(r"^\|\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]", row, re.M)
			if not nm:
				continue
			name = clean(nm.group(1))
			tiers, cur = {}, None
			for line in row.split("\n"):
				r = re.match(r"\s*'''\s*(Common|Heroic|Mythic|Astral)\s*'''", line)
				if r:
					cur = r.group(1)
					tiers[cur] = []
					continue
				if line.startswith("|}") or line.startswith("=="):
					break
				if cur and line.strip() and not line.startswith("|") and not line.startswith("[[File"):
					t = tidy(line)
					if t:
						tiers[cur].append(t)
			if not tiers:
				continue
			out.append({"name": name, "element": element, "astral": "Astral" in tiers,
				"tiers": [{"rarity": r, "lines": tiers[r]} for r in RARITIES if r in tiers]})
	return floor("auras", out, 150)


# ── Gambits ──────────────────────────────────────────────────────────────────
GAMBIT_FAMILY = {
	"pacification": "Pacification", "vulnerability": "Vulnerability", "health": "Life",
	"mana": "Mana", "target": "Target", "criticalhit": "Critical Hit", "missiles": "Missiles",
	"spiritsword": "Spirit Sword", "yalee": "Yalee", "damageamp": "Damage Amp",
	"sheild": "Shield", "barrier": "Barrier", "yaleemadness": "Yalee Madness",
	"enrage": "Enrage", "velocity": "Velocity", "poison": "Poison", "slime": "Slime",
	"sapling": "Sapling", "toxicgas": "Toxic Gas", "meteor": "Meteor", "burn": "Burn",
	"embers": "Embers", "ignition": "Ignition", "wisps": "Wisps", "fireshield": "Fire Shield",
	"freeze": "Freeze", "iceidol": "Ice Idol", "snowflake": "Snowflake",
	"icefragment": "Ice Fragment", "icesword": "Ice Sword",
	# The electric icons are numbered, not named; the Elemental Effect page pairs them.
	"061": "Electrify", "069": "Plasma", "080": "Nimbus", "074": "Lightning Orb", "083": "Thunder Strike",
}


def gambit_family(fname):
	f = fname.lower()
	for key, fam in GAMBIT_FAMILY.items():
		if re.search(rf"[-\s]{key}[\(.\s]", f) or f.endswith(f"{key}.png"):
			return fam
	raise SystemExit(f"gambits: unrecognized icon {fname!r} — add it to GAMBIT_FAMILY")


def parse_gambits(p):
	text = p["Gambits"]["text"]
	out = []
	for head, body in sections(text, 3):
		if head not in ELEMENTS:
			continue
		fam = None
		for row in rows_of(body):
			icon = re.search(r"\[\[File:([^\]|]+)", row)
			if icon:
				fam = gambit_family(icon.group(1))
			cells = [c.strip() for c in re.findall(r"^\|(?!\-|\})(.*)$", row, re.M)]
			cells = [c.split("|", 1)[-1].strip() if c.startswith(" rowspan") or "rowspan" in c else c for c in cells]
			cells = [c for c in cells if c and not c.startswith("[[File")]
			if len(cells) >= 2 and cells[0] in RARITIES and fam:
				eff = tidy(cells[1])
				trig = "On cast" if re.match(r"On spell cast", eff, re.I) else "On hit" if re.match(r"On each hit|On hit", eff, re.I) else "Other"
				out.append({"family": fam, "element": head, "rarity": cells[0], "trigger": trig, "text": eff})
	return floor("gambits", out, 90)


def gambit_meta(p):
	text = p["Gambits"]["text"]
	price = dict(re.findall(r"\|(Common|Heroic|Mythic|Astral)\s*(?:\|\||\n\|)\s*(\d+)", text))
	return {"price": {k: int(v) for k, v in price.items()}}


# ── Spells ───────────────────────────────────────────────────────────────────
# The spell table's own typos, fixed so the names match the pages and the text that cites them.
SPELL_FIX = {"Eye Of Judgmen": "Eye of Judgment", "Topez Gladius - Downwell": "Topaz Gladius - Downwell",
	"Sliterhing Sword": "Slithering Sword"}

TAGS = {":0": "Duration", ":1": "Stackable", ":2": "Weapon Buff", ":3": "Homing",
	":4": "Single Target", ":5": "Channeled", ":6": "Dodge", ":7": "Pull", ":8": "Push"}


def num(s):
	s = clean(s)
	try:
		return float(s) if "." in s else int(s)
	except ValueError:
		return s


def spell_desc(p, name):
	page = p.get(name)
	if not page:
		return ""
	m = re.search(r"\|\s*description\s*=\s*(.*?)\n\s*\|", page["text"], re.S)
	return clean(m.group(1)) if m else ""


def parse_spells(p):
	text = p["Spells"]["text"]
	table = text[: text.find("== Effect Glossary")]
	out, group, hero = [], None, None
	for row in rows_of(table):
		h = re.search(r'colspan="\d+"\s*\|(.*)', row)
		if h:
			label = clean(h.group(1))
			if label.startswith("Common"):
				group, hero = "Common", None
			elif label.startswith("Zodiac"):
				group, hero = "Zodiac", None
			else:
				group, hero = "Hero", re.sub(r"'s Spells$", "", label)
			continue
		nm = re.search(r"<br>\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]((?:<ref[^>]*>)*)", row) or \
			re.search(r"\]\]\s*<br>\s*([^\n<|]+)", row)
		vals = re.findall(r"<big>([^<]*)</big>", row)
		if not nm or len(vals) < 4 or group is None:
			continue
		name = clean(nm.group(1))
		desc = spell_desc(p, name)
		name = SPELL_FIX.get(name, name)
		refs = re.findall(r'<ref name="(:\d)"', row)
		tags = sorted({TAGS[r] for r in refs if r in TAGS})
		mana, dmg, hits = num(vals[0]), num(vals[1]), clean(vals[2])
		hi = [int(x) for x in re.findall(r"\d+", hits)]
		out.append({"name": name, "group": group, "hero": hero, "mana": mana, "dmg": dmg,
			"hits": hits, "hitsMax": max(hi) if hi else None,
			"dpm": round(dmg / mana, 1) if isinstance(dmg, int) and isinstance(mana, int) and mana else None,
			"tags": tags, "desc": desc})
	return floor("spells", out, 150)


# ── Imprints ─────────────────────────────────────────────────────────────────
PREFIX = {"Fajro": "Fire", "Glacio": "Ice", "Venen": "Poison", "Elekt": "Electric", "Nul": "Neutral"}


def parse_imprints(p):
	listing = p["Imprints"]["text"]
	affinity = {}
	for m in re.finditer(r"\[\[([A-Z][a-z]+(?: [IVX]+)?)\]\]\s*(?:<br\s*/?>)?\s*\(([^)]*)\)", listing):
		affinity[m.group(1)] = m.group(2).strip().title()
	names = sorted(t for t, v in p.items() if "[[Imprints|Imprint]]" in v["text"] and t != "Rooms")
	out = []
	for name in dict.fromkeys(names):
		page = p.get(name)
		if not page:
			continue
		m = re.search(r"\|-\s*\n\|(.*?)\n\|\}", page["text"], re.S)
		body = clean(m.group(1) if m else page["text"])
		parts = re.split(r"Transcendence effect\s*[:;]", body)
		eff = " ".join(tidy(x) for x in parts[0].split("\n") if x.strip())
		trans = " ".join(tidy(x) for x in parts[1].split("\n") if x.strip()) if len(parts) > 1 else ""
		element = next(v for k, v in PREFIX.items() if name.startswith(k))
		out.append({"name": name, "element": element, "gambit": affinity.get(name, ""),
			"effect": eff, "transcendence": trans})
	return floor("imprints", out, 85)


# ── Echoes ───────────────────────────────────────────────────────────────────
def parse_echoes(p):
	text = p["Echo"]["text"]
	body = text[text.find("{|"): text.find("|}")]
	out = []
	for row in rows_of(body)[2:]:
		cells = [clean(c) for c in re.split(r"\n\|", "\n" + row.strip())[1:]]
		cells = [c for c in cells if c != ""]
		if len(cells) >= 3:
			out.append({"name": cells[0], "desc": re.sub(r"\s*\n\s*", " ", cells[1]),
				"cooldown": re.sub(r"\s*\n\s*", " ", cells[2])})
	return floor("echoes", out, 35)


# ── Zodiac summons ───────────────────────────────────────────────────────────
def parse_summons(p):
	text = p["Zodiac Summon"]["text"]
	out = []
	for row in rows_of(text):
		m = re.match(r"\s*\|\s*(?:\[\[File:[^\]]*\]\]\s*)?\[\[([^\]]+)\]\]\s*(.*?)\n\|(.+)", row.strip("\n"), re.S)
		if m:
			out.append({"zodiac": clean(m.group(1)), "effect": clean(m.group(2)), "desc": clean(m.group(3))})
	return floor("summons", out, 12)


# ── Prowess ──────────────────────────────────────────────────────────────────
def parse_prowess(p):
	text = p["Prowess"]["text"]
	out = []
	for head, body in sections(text, 3):
		m = re.match(r"(?:(\w+?)(?:'s)? [Pp]rowess|Attack Prowess)", head)
		if not m:
			continue
		hero = {"Callie": "Calie", "Attack": "All heroes", None: "All heroes"}.get(m.group(1), m.group(1))
		path = "Attack" if hero == "All heroes" else "Generic"
		for row in rows_of(body):
			h = re.search(r'!\s*colspan="\d+"\s*\|\s*(.*)', row)
			if h:
				path = clean(h.group(1))
				continue
			cells = [clean(c) for c in re.split(r"\|\|", row)]
			if len(cells) >= 3:
				name = cells[-2].lstrip("| ").strip()
				eff = cells[-1].strip()
				if name and eff and name not in ("Name",):
					out.append({"hero": hero, "path": path, "name": name,
						"effect": re.sub(r"\s*\n\s*", " · ", eff)})
	return floor("prowess", out, 120)


# ── Void Catalyst ────────────────────────────────────────────────────────────
def parse_catalyst(p):
	text = p["Void Catalyst"]["text"]
	out = []
	for rowname, body in sections(text, 3):
		if not rowname.startswith("Row"):
			continue
		body = re.sub(r"\[\[File:[^\]]*\]\]", "", body)
		chunks = re.split(r"\n(?:====\s*)?'''([^\n]+?)'''(?:\s*====)?[ \t]*\n", "\n" + body)
		for i in range(1, len(chunks) - 1, 2):
			name, blk = clean(chunks[i]), chunks[i + 1]
			get = lambda k: clean((re.search(rf"'''{k}:?'''\s*:?\s*(.*?)(?=\n\s*'''|\Z)", blk, re.S) or [None, ""])[1])
			desc, cost, strat = get("Description"), get("Cost"), get("Strategy")
			if desc:
				out.append({"row": rowname, "name": name, "desc": desc, "cost": cost.lstrip(": "), "strategy": strat})
	return floor("catalyst", out, 22)


# ── Telescopes ───────────────────────────────────────────────────────────────
def parse_telluric(p):
	text = p["Telluric Telescope"]["text"]
	out = []
	for m in re.finditer(r"===\s*'''(.*?)'''\s*===\s*\n\|(.*?)(?=\n\|-|\n\|\})", text, re.S):
		blk = m.group(2)
		d = re.search(r"Description:?\s*(.*?)(?:'''\s*<big>|'''|\n|$)(?:\s*Synergy|$)?", clean(blk), re.S)
		c = clean(blk)
		desc = re.search(r"Description:\s*(.*?)(?=\s*Synergy:|$)", c, re.S)
		syn = re.search(r"Synergy:\s*(.*)$", c, re.S)
		out.append({"name": clean(m.group(1)), "desc": (desc.group(1) if desc else c).strip(),
			"synergy": syn.group(1).strip() if syn else ""})
	return floor("telluric", out, 25)


def parse_cursed(p):
	text = p["Cursed Telescope"]["text"]
	out = []
	kind = None
	for line_block in re.split(r"(== List of \w+ ==)", text):
		if line_block.startswith("== List of"):
			kind = "Malus" if "Malus" in line_block else "Perk"
			continue
		if not kind:
			continue
		for m in re.finditer(r"===\s*'''(.*?)'''\s*===\s*\n\|(.*?)(?=\n\|-|\n\|\})", line_block, re.S):
			out.append({"kind": kind, "name": clean(m.group(1)), "desc": re.sub(r"\s*\n\s*", " ", clean(m.group(2)))})
	return floor("cursed", out, 20)


# ── Bosses ───────────────────────────────────────────────────────────────────
ZODIACS = ["Taurus", "Virgo", "Capricorn", "Leo", "Sagittarius", "Aries", "Scorpio", "Pisces",
	"Cancer", "Aquarius", "Libra", "Gemini", "The Master"]
GUARDIANS = ["Lupus", "Pegasus", "Draco", "Hydra", "Monoceros", "Sculptor"]


def boss(p, name, kind):
	t = p[name]["text"]
	hp = re.search(r"\|\s*hp\s*=\s*([\d,]+)", t)
	world = re.search(r"\|\s*worlds\s*=\s*\*?\s*\[\[([^\]]+)\]\]", t)
	attacks, strategy = [], ""
	for head, body in sections(t, 2):
		if head in ("Attacks", "Combat"):
			sub = sections(body, 3)
			# The Zodiac pages lay their attacks out as a table: a `!` header cell
			# naming the attack, then a `|` cell describing it.
			table = re.findall(r"^!\s*(?:style=\"[^\"]*\"\s*\|)?\s*([^\n|]+?)\s*\n\|\s*([^\n]+)", body, re.M)
			if table:
				for an, ab in table:
					txt = clean(ab)
					if txt and not txt.startswith("colspan") and clean(an) != "Description":
						attacks.append({"name": re.sub(r"\s*\n\s*", " ", clean(an)), "text": txt})
			elif sub:
				for an, ab in sub:
					txt = clean(ab)
					if an and txt:
						attacks.append({"name": an, "text": re.sub(r"\s*\n+\s*", " ", txt)})
			else:
				for line in body.split("\n"):
					m = re.match(r"\*\s*'''(.*?)'''\s*[:\-–]?\s*(.*)", line)
					if m:
						attacks.append({"name": clean(m.group(1)).rstrip(":"), "text": clean(m.group(2))})
				if not attacks and clean(body):
					attacks.append({"name": "", "text": re.sub(r"\s*\n+\s*", " ", clean(body))[:1200]})
		if head.startswith("Strateg"):
			strategy = re.sub(r"\n{2,}", "\n", clean(body))
	return {"name": name, "kind": kind, "hp": int(hp.group(1).replace(",", "")) if hp else None,
		"world": clean(world.group(1)) if world else "", "attacks": attacks[:12], "strategy": strategy[:2500]}


def parse_bosses(p):
	out = [boss(p, z, "Zodiac") for z in ZODIACS] + [boss(p, g, "Star Guardian") for g in GUARDIANS]
	return floor("bosses (with attacks)", [b for b in out if b["attacks"]], 15) and out


# ── Elemental effects glossary ───────────────────────────────────────────────
def parse_effects(p):
	text = p["Elemental Effect"]["text"]
	out, element = [], None
	for line in text.split("\n"):
		h = re.match(r"==\s*.*?'''?\s*(Burn|Freeze|Poison|Electrify|Neutral)\b.*?==", line) or \
			re.match(r"==\s*\[\[File:[^\]]*\]\]\s*(Neutral)", line)
		if h:
			element = {"Burn": "Fire", "Freeze": "Ice", "Poison": "Poison", "Electrify": "Electric", "Neutral": "Neutral"}[h.group(1)]
			continue
		m = re.match(r"\s*(?:\[\[File:[^\]]*\]\]\s*)+([A-Z][\w ]+?)\s*(?:\(([A-Za-z]+)\))?\s*-\s*(.+)", line)
		if m:
			name, el, desc = m.group(1).strip(), m.group(2), clean(m.group(3))
			el = {"Ice": "Ice", "Fire": "Fire", "Poison": "Poison", "Electric": "Electric", "Neutral": "Neutral"}.get(el or "", element or "")
			out.append({"name": name, "element": el or "Neutral", "desc": desc})
		# An italic line under an entry defines a term that entry introduced
		# (Combustion under Burn), so it takes that entry's element.
		sub = re.match(r"\s*''([A-Z][\w ]+?)\s*-\s*(.+?)''\s*$", line)
		if sub:
			parent = out[-1]["element"] if out else (element or "Neutral")
			out.append({"name": sub.group(1).strip(), "element": parent, "desc": clean(sub.group(2))})
	seen, uniq = set(), []
	for e in out:
		if e["name"] not in seen:
			seen.add(e["name"])
			uniq.append(e)
	return floor("effects", uniq, 25)


# ── Destiny levels ───────────────────────────────────────────────────────────
def parse_destiny(p):
	text = p["Path of Destinies"]["text"]
	out = []
	for head, body in sections(text, 3):
		m = re.match(r"Destiny Level (\d+):\s*(.*)", head)
		if m:
			c = clean(body)
			strat = re.search(r"Strategy:\s*(.*)", c, re.S)
			out.append({"level": int(m.group(1)), "name": m.group(2).rstrip(". "),
				"text": re.sub(r"\s*\n+\s*", " ", (strat.group(1) if strat else c))[:900]})
	return floor("destiny", out, 6)


# ── Stats (the numbers the two charts are built from) ───────────────────────
def parse_stats(p):
	t = clean(p["Player Stats"]["text"])
	grab = lambda pat: int(re.search(pat, t).group(1))
	return {
		"baseLife": grab(r"starts the game with (\d+) life"),
		"lifePerStone": grab(r"Life-Stones \(\+(\d+) per\)"),
		"baseMana": grab(r"starts the game with (\d+) mana"),
		"strengthPerStone": grab(r"increased by (\d+)% per Strength-Stone"),
		"speedPerStone": grab(r"increased by (\d+)% for each Speed-Stone"),
		"armorPerStone": grab(r"increased by (\d+)% for each Armor-Stone"),
		"armorCap": grab(r"maximum of (\d+)%"),
		"critPerStone": grab(r"increased by (\d+)% for each Critical-Stone"),
		"critBonus": grab(r"critically hit for (\d+)% More damage"),
		"sixthSensePerTier": 10,
	}


def main():
	with open(SRC, encoding="utf-8") as f:
		p = json.load(f)
	newest = max(v["ts"] for v in p.values())
	data = {
		"source": "astralascent.wiki.gg",
		"collected": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
		"wikiUpdated": newest[:10],
		"stats": parse_stats(p),
		"auras": parse_auras(p),
		"gambits": parse_gambits(p),
		"gambitMeta": gambit_meta(p),
		"spells": parse_spells(p),
		"imprints": parse_imprints(p),
		"echoes": parse_echoes(p),
		"summons": parse_summons(p),
		"prowess": parse_prowess(p),
		"catalyst": parse_catalyst(p),
		"telluric": parse_telluric(p),
		"cursed": parse_cursed(p),
		"bosses": parse_bosses(p),
		"effects": parse_effects(p),
		"destiny": parse_destiny(p),
	}
	os.makedirs(os.path.dirname(DST), exist_ok=True)
	with open(DST, "w", encoding="utf-8") as f:
		json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
	print(f"wrote {DST} ({os.path.getsize(DST):,} bytes)")
	for k, v in data.items():
		if isinstance(v, list):
			print(f"  {k}: {len(v)}")


if __name__ == "__main__":
	main()
