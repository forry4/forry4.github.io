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
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../shared/theme.js";
import { lobbyCss, LobbyHeader, LobbyUser, LobbyLoading } from "../shared/lobby.jsx";
import { GAME_ACCENTS } from "../shared/accents.js";
import { makeClient } from "./client.js";
import { createSim, step, TPS, REACH, xpProgress, WEAPONS, statsFor, enchantValue, recoveryLimit } from "./sim.js";
import { camera, draw, drawTown, promptFor } from "./render.js";
import { createTown, stepTown, setTownGear, postDps, STATIONS, standAt } from "./town.js";
import cssText from "./HalcyonRift.css?inline";

const styles = baseCss + lobbyCss + cssText;
const ACCENT = { "--lby-accent": GAME_ACCENTS.halcyon };
const STEP_MS = 1000 / TPS;

const NAMES = { shortbow: "Shortbow", longbow: "Longbow", repeater: "Repeater", tidecaller: "Tidecaller",
	leather_vest: "Leather Vest", volley_quiver: "Volley Quiver", band_of_vigor: "Band of Vigor",
	band_of_focus: "Band of Focus", kingfisher_eye: "Kingfisher's Eye" };
// Every enchantment reads as flat points ("+4 Attack"), never a percentage.
const ENCHANT_NAMES = { max_hp: "Max HP", max_mp: "Max MP", attack: "Attack", defense: "Defense",
	attack_speed: "Dexterity", ability_power: "Volley damage", mp_regen: "MP regen", hp_regen: "HP regen" };
const SLOT_NAMES = { weapon: "Weapon", armor: "Armor", ability: "Ability", ring1: "Ring", ring2: "Ring" };
const FAMILY = { weapon: "Weapon", armor: "Armor", ability: "Ability", ring: "Ring" };
const ABBR = { shortbow: "SB", longbow: "LB", repeater: "RP", tidecaller: "TC", leather_vest: "LV",
	volley_quiver: "VQ", band_of_vigor: "BV", band_of_focus: "BF", kingfisher_eye: "KE" };
const WEAPON_FEEL = { shortbow: "Fast and close: twin arrows that spread with distance.",
	longbow: "Slow and far: one heavy arrow that passes through enemies.",
	tidecaller: "Three arrows in a wide fan that glance off a wall once.",
	repeater: "A three-bolt burst, then a reload." };
/* A UNIQUE is named, not tiered: it is its own thing, not a rung on the ladder. */
const nameOf = (it) => (it.kind === "unique" ? NAMES[it.base_id] || it.base_id : `${NAMES[it.base_id] || it.base_id} · T${it.tier}`);
const num = (x) => (Number.isInteger(x) ? String(x) : x.toFixed(1));

/* A weapon's pattern in words, off the sim's own numbers (so they cannot drift). */
function weaponLine(it) {
	const w = WEAPONS[it.base_id];
	if (!w) return null;
	const s = statsFor([{ ...it, enchants: [] }]);
	const shape = w.burst > 1 ? `${w.burst}-bolt burst` : w.shots > 1 ? `${w.shots} arrows` : "1 arrow";
	return `${shape} · ${s.weaponDmg} damage each · ${num(w.rate)} a second · range ${w.range}`
		+ `${w.pierce ? ` · pierces ${w.pierce}` : ""}${w.bounce ? " · bounces once" : ""}`;
}

/* What an item's base gives, flat, worked out by the sim (what it adds to bare stats). */
const STAT_WORDS = [["maxHp", "Max HP"], ["maxMp", "Max MP"], ["att", "Attack"], ["dex", "Dexterity"],
	["def", "Defense"], ["mpRegen", "MP regen"], ["hpRegen", "HP regen"], ["abilityDmg", "Volley damage"], ["pierce", "Pierce"]];
function baseLine(it) {
	if (WEAPONS[it.base_id]) return null;
	const bare = statsFor([]), s = statsFor([{ ...it, enchants: [] }]);
	return STAT_WORDS.filter(([k]) => s[k] !== bare[k]).map(([k, w]) => `+${num(s[k] - bare[k])} ${w}`).join(" · ") || null;
}

// The three places an item can be in town, as the wire writes them.
const at = {
	vault: (i) => ["vault", i],
	inv: (c, i) => ["inventory", c, i],
	eq: (c, s) => ["equipped", c, s],
};
const keyOf = (to) => to.join(":");
function placeKey(it) {
	if (it.loc === "vault") return keyOf(at.vault(it.slot_index));
	if (it.loc === "inventory") return keyOf(at.inv(it.char_id, it.slot_index));
	if (it.loc === "equipped") return keyOf(at.eq(it.char_id, it.equip_slot));
	return null;
}

/* Where an item on a character is, as a place tuple (the inverse of placeKey). */
function placeAt_(it) {
	return it.loc === "equipped" ? at.eq(it.char_id, it.equip_slot) : at.inv(it.char_id, it.slot_index);
}

/* The run's own model of the character's bag and equipment, owned OUTSIDE React so
 * the fight's loop can ask it synchronously (is there room? which slot does this
 * pickup go to?) on the tick the pickup happens. Every change is mirrored into the
 * page's state for drawing; `gear` is the equipment the fight takes on its next tick. */
function runControl(mine, charId, view, setRunItems) {
	const ctl = {
		items: mine.map((it) => ({ ...it })),
		gear: null,
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

export default function HalcyonRift({ authUser, onExit }) {
	const client = useMemo(() => makeClient(authUser), [authUser?.id, authUser?.session_token]); // eslint-disable-line react-hooks/exhaustive-deps
	const [view, setView] = useState(null);
	const [error, setError] = useState(null);
	const [busy, setBusy] = useState(false);
	const [selChar, setSelChar] = useState(null);
	const [picked, setPicked] = useState(null);       // an item id, for click-to-move
	const [drag, setDrag] = useState(null);           // the item id being dragged
	const [tip, setTip] = useState(null);             // { item, rect }
	const [discardAsk, setDiscardAsk] = useState(null);
	const [panel, setPanel] = useState(null);         // "vault" | "forge" | null
	const [forge, setForge] = useState([]);           // the item ids picked for fusion (at most two)
	const [forged, setForged] = useState(null);
	const [near, setNear] = useState(null);
	const [run, setRun] = useState(null);
	// During a run, this character's equipment and bag as the PAGE knows them: what it
	// carried in, what it picked up (named by drop until the server mints it), moved
	// wherever the player moved it. Kept until the town's refresh replaces it.
	const [runItems, setRunItems] = useState(null);
	const [result, setResult] = useState(null);
	const townRef = useRef(null);
	if (!townRef.current) townRef.current = createTown();
	const townNotes = useRef([]);

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

	// One heartbeat for the queue: during a run it delivers the fight's reports every
	// few seconds, and after one it keeps trying until the last of them has landed.
	useEffect(() => {
		const id = setInterval(() => { if (client.pendingRun()) client.flush(); }, 3000);
		const bye = () => client.flush({ keepalive: true });
		window.addEventListener("pagehide", bye);
		return () => { clearInterval(id); window.removeEventListener("pagehide", bye); };
	}, [client]);

	const act = useCallback(async (fn) => {
		setBusy(true);
		let failed = null;
		try { await fn(); }
		catch (e) { failed = e.message || "That did not work."; }
		setBusy(false); setPicked(null); setDiscardAsk(null);
		await refresh();
		// After the refresh, which clears it. The store's reasons are lower-case clauses.
		if (failed) setError(failed[0].toUpperCase() + failed.slice(1));
	}, [refresh]);

	const items = view?.items || [];
	const onChar = (it, id) => (it.loc === "inventory" || it.loc === "equipped") && it.char_id === id;
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

	const townNote = (text, color) => townNotes.current.push({ text, color, until: townRef.current.tick + 3 * TPS });

	const chooseChar = (c) => {
		setPicked(null);
		setSelChar(c.char_id);
		// A run this character left open (a closed tab) ends as a recall now (§13.1a).
		if (view.open_runs[c.char_id]) act(() => client.openCharacter(c.char_id));
	};

	const enter = (realm) => {
		if (!char) { townNote("Make a Ranger first: the + beside your roster.", "#f3a39c"); return; }
		act(async () => {
			await client.flush();
			if (client.pendingRun()) throw new Error("Your last run is still being saved. Try again in a moment.");
			const { run_id, dungeon } = await client.startRun(char.char_id, realm);
			client.beginRun(run_id);
			const ctl = runControl(items.filter((it) => onChar(it, char.char_id)), char.char_id, view, setRunItems);
			setResult(null); setPanel(null); setTip(null); setPicked(null);
			setRunItems(ctl.items);
			setRun({ run_id, dungeon, gear: ctl.equipped(), ctl, realm, bases: view.bases, hero: { level: char.level, xp: char.xp, levels: view.levels } });
		});
	};
	const enterRef = useRef(enter);
	enterRef.current = enter;

	const use = useCallback((station) => {
		if (station.kind === "portal") { enterRef.current(station.realm); return; }
		setPanel((p) => (p === station.kind ? null : station.kind));
		setForged(null);
	}, []);

	const endRun = useCallback((outcome) => {
		const t = townRef.current;
		Object.assign(t.p, standAt(`realm:${outcome.realm}`));    // back out of the portal you took
		setRun(null);
		setPicked(null); setDrag(null); setTip(null);
		setResult(outcome);
		// The town's copy replaces the run's once it has landed — unless a new run began meanwhile.
		refresh().then(() => setRunItems((cur) => (cur === outcome.items ? null : cur)));
	}, [refresh]);

	// ── moving items: drag and drop, or click one and then click where it goes ──
	const fits = (it, to) => {
		if (to[0] !== "equipped") return true;
		const b = view.bases[it.base_id];
		return !!b && (!b.cls || b.cls === char?.class_id)
			&& (b.slot === to[2] || (b.slot === "ring" && to[2].startsWith("ring")));
	};
	const accepts = (target, it) => (target.kind === "place" ? fits(it, target.to) : true);
	// Mid-run, a move is a run EVENT (queued with the fight's reports, so it lands after
	// the pickup that minted the item) and the fight takes the new gear on its next tick.
	const runMove = (it, to) => {
		const ctl = run.ctl, here = placeAt_(it);
		if (ctl.ended) return;                         // the run is closed; the server takes nothing more
		if (keyOf(here) === keyOf(to)) return;
		const other = ctl.items.find((x) => placeKey(x) === keyOf(to));
		if (!fits(it, to) || (other && !fits(other, here))) { setError(`${nameOf(other && fits(it, to) ? other : it)} does not go there.`); return; }
		ctl.move(it, to, other, here);
		client.report({ type: "move", ...(it.fresh ? { drop: it.drop } : { item: it.item_id }), to: [to[0], to[2]] });
	};
	const placeAt = (target, it) => {
		if (!it) return;
		if (run) {
			if (target.kind === "place" && target.to[0] !== "vault") runMove(it, target.to);
			setPicked(null);
			return;
		}
		if (it.fresh) return;
		if (target.kind === "place") {
			if (placeKey(it) === keyOf(target.to)) { setPicked(null); return; }
			const other = byPlace[keyOf(target.to)];
			if (!fits(it, target.to) || (other && it.loc === "equipped" && !fits(other, placeAt_(it)))) {
				setError(`${nameOf(fits(it, target.to) ? other : it)} does not go there.`); setPicked(null); return;
			}
			act(() => client.move(it.item_id, target.to, it.version));
		} else if (target.kind === "trash") setDiscardAsk(it);
		setPicked(null);
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
		const free = [...Array(view.limits.inventory).keys()].find((i) => !byPlace[keyOf(at.inv(char.char_id, i))]);
		if (free === undefined) { setError("Your bag is full."); return null; }
		return at.inv(char.char_id, free);
	};
	const quick = (it) => {
		if (!it || busy || panel === "forge") return;
		const to = quickTo(it);
		if (to) placeAt({ kind: "place", to }, it);
	};
	const quickRef = useRef(null);
	quickRef.current = (i) => char && quick(byPlace[keyOf(at.inv(char.char_id, i))]);
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
		setForged(null);
		setForge((f) => (f.includes(it.item_id) ? f.filter((id) => id !== it.item_id) : [...f, it.item_id].slice(-2)));
	};
	const slotCtx = {
		bases: view?.bases || {}, picked, drag, dragItem: drag ? byId[drag] : null, accepts, inRun: !!run, forge, quick,
		startDrag: (it) => { setDrag(it.item_id); setTip(null); },
		endDrag: () => setDrag(null),
		dropAt: (target) => placeAt(target, byId[drag]),
		clickAt: (target, it) => {
			if (panel === "forge" && !run && target.to?.[0] !== "vault") { if (it) forgePick(it); return; }
			const held = picked ? byId[picked] : null;
			if (!held) { if (it && (run || !it.fresh)) setPicked(it.item_id); return; }
			if (it && it.item_id === held.item_id) { setPicked(null); return; }
			placeAt(target, held);
		},
		showTip: (it, el) => { if (!drag) setTip({ item: it, rect: el.getBoundingClientRect() }); },
		hideTip: () => setTip(null),
	};

	const header = <LobbyHeader onBack={run ? null : onExit} title={run ? run.dungeon.name : "Halcyon Rift"}
		user={<LobbyUser user={authUser} profile={!run} />} />;

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
	const fusable = fa && fb && ["base_id", "tier", "kind", "slot_count"].every((k) => fa[k] === fb[k]);
	const invItem = (i) => (char ? byPlace[keyOf(at.inv(char.char_id, i))] : null);
	const equipped = char ? view.limits.equip.map((s) => byPlace[keyOf(at.eq(char.char_id, s))]).filter(Boolean) : [];

	return (
		<div className={"app halcyon fg-table" + (run ? " hr-in-run" : "")} style={ACCENT}><style>{styles}</style>
			{header}
			<main className="hr-main">
				<section className="hr-stage" aria-label={run ? run.dungeon.name : "The town"}
					data-near={near || ""} data-panel={panel || ""}>
					<div className="hr-view">
						{run
							? <Dungeon run={run} client={client} onEnd={endRun} />
							: <Town st={townRef.current} notes={townNotes} ready={!!char && !busy} gear={equipped} level={char?.level || 1}
								onUse={use} onNear={setNear} onEscape={() => { setPanel(null); setDiscardAsk(null); }} />}

						{result && !run && <ResultPanel result={result} onClose={() => setResult(null)} />}
						{error && <div className="hr-error" role="alert">{error}
							<button className="hr-x" aria-label="Dismiss" onClick={() => setError(null)}>×</button></div>}

						{panel === "vault" && !run && (
							<Overlay title="Vault" onClose={() => setPanel(null)} className="hr-vault">
								<p className="hr-hint">Shared by every character. Drag items in and out.</p>
								<div className="hr-grid hr-grid-vault">
									{[...Array(view.limits.vault).keys()].map((i) => (
										<Slot key={i} item={byPlace[keyOf(at.vault(i))]} target={{ kind: "place", to: at.vault(i) }}
											locked={locked} ctx={slotCtx} />))}
								</div>
							</Overlay>)}

						{panel === "forge" && !run && (
							<Overlay title="Forge" onClose={() => setPanel(null)} className="hr-forge-panel">
								<p className="hr-hint">Click two identical items in your bag or equipment — same item,
									tier and number of enchantment slots. They fuse into one with fresh enchantments,
									and now and then an extra slot.</p>
								<div className="hr-forge">
									<span className={"hr-forge-pick" + (fa ? " on" : "")}>{fa ? nameOf(fa) : "First item"}</span>
									<span className="hr-plus" aria-hidden="true">+</span>
									<span className={"hr-forge-pick" + (fb ? " on" : "")}>{fb ? nameOf(fb) : "Second item"}</span>
									<button className="btn btn-gold" disabled={!fusable || locked}
										onClick={() => act(async () => { setForged(await client.fuse(fa.item_id, fb.item_id)); setForge([]); })}>
										Fuse</button>
								</div>
								<p className="hr-forge-note" role="status">
									{forged ? `Made ${nameOf(forged)} with ${forged.enchants.length} enchantment${forged.enchants.length === 1 ? "" : "s"}.`
										: !fa || !fb ? "Pick two items."
										: fusable ? "Ready to fuse. Both items are used up."
										: fa.base_id !== fb.base_id ? "Not the same item."
										: fa.tier !== fb.tier ? `Not the same tier (${fa.tier} and ${fb.tier}).`
										: fa.slot_count !== fb.slot_count ? `Not the same number of enchantment slots (${fa.slot_count} and ${fb.slot_count}).`
										: "These two are not identical."}
								</p>
							</Overlay>)}

						{discardAsk && (
							<Overlay title="Discard?" onClose={() => setDiscardAsk(null)} className="hr-confirm">
								<p>{nameOf(discardAsk)} is destroyed for good.</p>
								<div className="hr-actions">
									<button className="btn btn-outline" disabled={busy}
										onClick={() => act(() => client.discard(discardAsk.item_id, discardAsk.version))}>Discard</button>
									<button className="btn btn-ghost" onClick={() => setDiscardAsk(null)}>Keep it</button>
								</div>
							</Overlay>)}
					</div>
					<p className="hr-keys">
						{run
							? <><kbd>WASD</kbd> move · <kbd>mouse</kbd> aim, hold to shoot · <kbd>F</kbd> auto-fire ·
								<kbd>Space</kbd> volley · <kbd>E</kbd> pick up · <kbd>1</kbd>–<kbd>8</kbd> equip · <kbd>R</kbd> recall</>
							: <><kbd>WASD</kbd> walk · <kbd>mouse</kbd> shoot · <kbd>E</kbd> use the vault, the forge or a portal ·
								<kbd>1</kbd>–<kbd>8</kbd> or double-click to equip</>}
					</p>
				</section>

				<aside className="hr-side fg-panel" aria-label="Your character">
					<div className="hr-roster" role="group" aria-label="Characters">
						{slots.map((s) => {
							const c = view.characters.find((x) => x.slot === s);
							if (!c) return (
								<button key={s} className="hr-char hr-char-empty" disabled={locked || !!run} title="New Ranger"
									aria-label="New Ranger" onClick={() => act(() => client.createCharacter(s))}>+</button>);
							return (
								<button key={s} className={"hr-char" + (c.char_id === selChar ? " sel" : "")} disabled={!!run}
									title={`Ranger · Level ${c.level}`} aria-pressed={c.char_id === selChar} onClick={() => chooseChar(c)}>
									<span className="hr-char-glyph" aria-hidden="true" />
									<span className="hr-char-lv">Lv {c.level}</span>
								</button>);
						})}
					</div>
					<div className="hr-who">
						{char ? <>
							<span className="hr-char-name">Ranger</span>
							<span className="fg-label-soft">Level {char.level}</span>
							<XpBar levels={view.levels} xp={char.xp} />
						</> : <span className="hr-hint">Make a Ranger to begin: press +.</span>}
						{view.fallen.length > 0 && <span className="hr-fallen">{view.fallen.length} fallen</span>}
					</div>

					{char && <Vitals read={() => vitalsOf(run ? run.ctl.st : townRef.current)} />}
					{char && <Stats gear={equipped} level={char.level} />}
					<h2 className="fg-label">Equipment</h2>
					<div className="hr-equip">
						{view.limits.equip.map((s) => {
							const to = char ? at.eq(char.char_id, s) : null;
							return <Slot key={s} label={SLOT_NAMES[s]} item={to ? byPlace[keyOf(to)] : null}
								target={to && { kind: "place", to }} locked={locked} ctx={slotCtx} />;
						})}
					</div>
					<h2 className="fg-label">Inventory</h2>
					<div className="hr-grid hr-grid-inv">
						{[...Array(view.limits.inventory).keys()].map((i) => {
							const to = char ? at.inv(char.char_id, i) : null;
							return <Slot key={i} num={i < 8 ? i + 1 : null} item={invItem(i)} target={to && { kind: "place", to }} locked={locked} ctx={slotCtx} />;
						})}
					</div>
					<div className={"hr-trash" + (drag && !run ? " armed" : "")} aria-label="Discard"
						onDragOver={(e) => { if (drag && !locked && !run) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
						onDrop={(e) => { e.preventDefault(); if (!locked && !run) slotCtx.dropAt({ kind: "trash" }); setDrag(null); }}>
						{run ? "Swap gear any time · the vault and the bin are in town" : "Drop an item here to discard it"}
					</div>
				</aside>
			</main>
			{tip && <ItemTip tip={tip} bases={view.bases} />}
		</div>
	);
}

/* An item slot: a drag source, a drop target, and a click target. `target` says
 * what dropping here means: a place, a forge input, or nothing. */
function Slot({ label, item, target, locked, ctx, num: n = null }) {
	const fam = item ? ctx.bases[item.base_id]?.slot : null;
	const ok = ctx.dragItem && target ? ctx.accepts(target, ctx.dragItem) : null;
	const name = item ? nameOf(item) : `${label || "Empty"} slot`;
	const forged = item && ctx.forge.includes(item.item_id);
	return (
		<button className={"hr-slot" + (item ? ` has fam-${fam}` : "") + (item && item.item_id === ctx.picked ? " sel" : "")
			+ (item?.kind === "unique" ? " unique" : "") + (item?.fresh ? " fresh" : "") + (forged ? " forging" : "")
			+ (ok === true ? " ok" : ok === false ? " no" : "") + (item && item.item_id === ctx.drag ? " dragging" : "")}
			aria-label={name} aria-pressed={forged || undefined} disabled={!target && !item}
			draggable={!!item && !locked && (!item.fresh || ctx.inRun)}
			onDragStart={(e) => { e.dataTransfer.setData("text/plain", item.item_id); e.dataTransfer.effectAllowed = "move"; ctx.startDrag(item); }}
			onDragEnd={(e) => { ctx.endDrag(); if (ctx.inRun) e.currentTarget.blur(); }}
			onDragOver={(e) => { if (ctx.drag && target && !locked) { e.preventDefault(); e.dataTransfer.dropEffect = "move"; } }}
			onDrop={(e) => { e.preventDefault(); if (target && !locked) ctx.dropAt(target); ctx.endDrag(); }}
			onMouseEnter={(e) => item && ctx.showTip(item, e.currentTarget)}
			onMouseLeave={ctx.hideTip}
			onFocus={(e) => item && ctx.showTip(item, e.currentTarget)}
			onBlur={ctx.hideTip}
			onClick={(e) => { if (!locked && target) ctx.clickAt(target, item); if (ctx.inRun) e.currentTarget.blur(); }}
			onDoubleClick={(e) => { if (!locked && item && target) ctx.quick(item); if (ctx.inRun) e.currentTarget.blur(); }}>
			{n && <span className="hr-num" aria-hidden="true">{n}</span>}
			{item ? <><span className="hr-abbr">{ABBR[item.base_id] || "?"}</span>
				{item.kind === "unique" ? <span className="hr-tier hr-star" aria-hidden="true">★</span>
					: <span className="hr-tier">{item.tier}</span>}
				{item.slot_count > 0 && <span className="hr-dots">{"•".repeat(item.slot_count)}</span>}</>
				: label && <span className="hr-slot-label">{label}</span>}
		</button>
	);
}

/* What an item is, beside the slot under the pointer — kept inside the window. */
function ItemTip({ tip, bases }) {
	const ref = useRef(null);
	const [pos, setPos] = useState(null);
	useLayoutEffect(() => {
		const el = ref.current, r = tip.rect, w = el.offsetWidth, h = el.offsetHeight;
		const left = r.left > window.innerWidth / 2 ? r.left - w - 10 : r.right + 10;
		setPos({ left: Math.max(8, Math.min(window.innerWidth - w - 8, left)),
			top: Math.max(8, Math.min(window.innerHeight - h - 8, r.top)) });
	}, [tip]);
	const it = tip.item, fam = bases[it.base_id]?.slot, line = weaponLine(it), base = baseLine(it);
	return (
		<div ref={ref} className={"hr-tip fg-panel" + (it.kind === "unique" ? " fg-lit unique" : "")} role="tooltip"
			style={pos ? { left: pos.left, top: pos.top } : { left: 0, top: 0, visibility: "hidden" }}>
			<h3 className="fg-label">{nameOf(it)}</h3>
			<p className="fg-label-soft">{it.kind === "unique" ? `Unique ${(FAMILY[fam] || "item").toLowerCase()}` : `${FAMILY[fam] || ""} · Tier ${it.tier}`}
				{it.fresh ? " · picked up this run" : ""}</p>
			{line && <p className="hr-tip-weapon">{WEAPON_FEEL[it.base_id]}<br /><span className="hr-q">{line}</span></p>}
			{base && <p className="hr-q">{base}</p>}
			{it.enchants?.length > 0 && (
				<ul className="hr-enchants">
					{it.enchants.map((e, i) => <li key={i}>+{enchantValue(e.id, e.q)} {ENCHANT_NAMES[e.id] || e.id}</li>)}
				</ul>)}
		</div>
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
function Stats({ gear, level }) {
	const s = statsFor(gear, level);
	const cells = [["ATT", s.att, "Attack: each point adds to every arrow's damage"], ["DEX", s.dex, "Dexterity: each point adds to how fast you shoot"],
		["DEF", s.def, "Defense: taken off every hit"], ["DMG", s.shots > 1 ? `${s.dmg}×${s.shots}` : s.dmg, "Damage per arrow, with Attack"],
		["RATE", `${num(Math.round(s.rate * 10) / 10)}/s`, "Shots a second, with Dexterity"], ["RNG", s.range, "Range in tiles"]];
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
	const s = st.stats, p = st.p, town = p.hp === undefined;
	return { hp: town ? s.maxHp : p.hp, limit: town ? s.maxHp : recoveryLimit(st), maxHp: s.maxHp, mp: p.mp, maxMp: s.maxMp };
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
		const [hpFill, hpRec, hpText, mpFill, mpText] = ["hp-fill", "hp-rec", "hp-text", "mp-fill", "mp-text"]
			.map((k) => el.querySelector(`[data-k="${k}"]`));
		const frame = () => {
			const v = readRef.current();
			if (v) {
				const hp = Math.ceil(v.hp), lim = Math.ceil(v.limit), mp = Math.floor(v.mp);
				const key = `${hp}|${lim}|${v.maxHp}|${mp}|${v.maxMp}`;
				if (key !== last) {
					last = key;
					hpFill.style.width = `${(100 * Math.min(v.hp, v.maxHp)) / v.maxHp}%`;
					hpRec.style.width = `${(100 * Math.min(v.limit, v.maxHp)) / v.maxHp}%`;
					hpText.textContent = `${hp} / ${v.maxHp}`;
					mpFill.style.width = `${(100 * Math.min(v.mp, v.maxMp)) / v.maxMp}%`;
					mpText.textContent = `${mp} / ${v.maxMp}`;
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
			<div className="hr-bar hr-bar-hp" title="Health. Light gray: regeneration brings it back. Dark gray: only a heal does.">
				<i className="hr-bar-rec" data-k="hp-rec" /><i className="hr-bar-fill" data-k="hp-fill" />
				<span className="hr-bar-name">HP</span><span className="hr-bar-num" data-k="hp-text" />
			</div>
			<div className="hr-bar hr-bar-mp" title="Mana">
				<i className="hr-bar-fill" data-k="mp-fill" />
				<span className="hr-bar-name">MP</span><span className="hr-bar-num" data-k="mp-text" />
			</div>
		</div>
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

function ResultPanel({ result, onClose }) {
	const title = { completed: "The Shallows are cleared", recalled: "Recalled to town", dead: "Your Ranger has fallen" }[result.status];
	return (
		<section className={"hr-result fg-panel fg-lit res-" + result.status} role="status">
			<h2 className="fg-label">{title}</h2>
			{result.status === "dead"
				? <p>Everything the Ranger carried is gone. The vault is untouched.</p>
				: result.loot.length
					? <p>Brought back: {result.loot.join(", ")}.</p>
					: <p>Nothing was picked up.</p>}
			{result.status !== "dead" && result.xp > 0 && (
				<p className="hr-result-xp">+{result.xp} XP{result.levelUp ? ` · reached level ${result.level}` : ""}</p>)}
			<button className="btn btn-outline" onClick={onClose}>OK</button>
		</section>
	);
}

const KEY_DIR = { KeyW: [0, -1], ArrowUp: [0, -1], KeyS: [0, 1], ArrowDown: [0, 1],
	KeyA: [-1, 0], ArrowLeft: [-1, 0], KeyD: [1, 0], ArrowRight: [1, 0] };

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
function Town({ st, notes, ready, onUse, onNear, onEscape, gear, level }) {
	const canvasRef = useRef(null);
	const cb = useRef(null);
	cb.current = { ready, onUse, onNear, onEscape };
	const gearKey = JSON.stringify([gear.map((g) => [g.base_id, g.tier, g.enchants]), level]);
	useEffect(() => { setTownGear(st, gear, level); }, [gearKey]); // eslint-disable-line react-hooks/exhaustive-deps

	useEffect(() => {
		const cv = canvasRef.current;
		const g = cv.getContext("2d");
		const keys = new Set();
		const mouse = { x: 0, y: 0, down: false };
		let px = 32, raf = 0, prev = null, lastNear, auto = false, ability = false, cam = { ox: 0, oy: 0 };
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
			for (const k of keys) { const d = KEY_DIR[k]; if (d) { mx += d[0]; my += d[1]; } }
			stepTown(st, { mx: Math.sign(mx), my: Math.sign(my), ax: (mouse.x - cam.ox) / px - st.p.x,
				ay: (mouse.y - cam.oy) / px - st.p.y, fire: mouse.down || auto, ability });
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
				aim: { x: (mouse.x - cam.ox) / px - pp.x, y: (mouse.y - cam.oy) / px - pp.y },
				prompt: promptFor(station, station?.kind !== "portal" || cb.current.ready) });
			raf = requestAnimationFrame(frame);
		};
		raf = requestAnimationFrame(frame);
		// DEV ONLY (stripped from a production build), like the dungeon's hook.
		if (import.meta.env.DEV) window.__halcyonTown = { st, advance: (n) => { for (let i = 0; i < n; i++) tick(); return st.near; } };

		const typing = (e) => /^(INPUT|TEXTAREA|SELECT)$/.test(e.target?.tagName || "");
		const onKeyDown = (e) => {
			if (typing(e)) return;
			if (KEY_DIR[e.code]) { keys.add(e.code); e.preventDefault(); return; }
			if (e.repeat) return;
			if (e.code === "KeyE") {
				const s = STATIONS.find((x) => x.id === st.near);
				if (s) cb.current.onUse(s);
			} else if (e.code === "Escape") cb.current.onEscape();
			else if (e.code === "KeyF") auto = !auto;
			else if (e.code === "Space" || e.code === "KeyQ") { ability = true; e.preventDefault(); }
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
		aria-label="The town. Walk with WASD, shoot with the mouse; press E at the vault, the forge or a portal." />;
}

// ── the dungeon ─────────────────────────────────────────────────────────────
function Dungeon({ run, client, onEnd }) {
	const canvasRef = useRef(null);
	const [ending, setEnding] = useState(null);

	useEffect(() => {
		const cv = canvasRef.current;
		const g = cv.getContext("2d");
		const st = createSim(run.dungeon, run.gear, run.hero);
		const ctl = run.ctl;
		ctl.st = st;                                 // the side panel's HP and MP bars read it live
		const loot = [];
		const notes = [];
		const keys = new Set();
		const mouse = { x: 0, y: 0, down: false };
		const edge = { ability: false, interact: false, recall: false };
		let auto = false, px = 32, raf = 0, ended = false;
		// Where each moving thing was before the last tick, so a frame can draw it part
		// of the way to where it is now (the sim steps at 60 Hz; a screen may run at 144).
		let prev = new WeakMap(), alpha = 1;
		let cam = camera(st, 1, 1, px);              // the camera of the last drawn frame
		// DEV ONLY (stripped from a production build): the live sim, and a seam for a
		// scripted driver, so a whole run can be played through the real page.
		if (import.meta.env.DEV) window.__halcyon = { st, drive: null };

		const note = (text, color) => { notes.push({ text, color, until: st.tick + 4 * TPS }); };
		const resize = () => { px = fitCanvas(cv); };
		const ro = new ResizeObserver(resize);
		ro.observe(cv);
		resize();

		const nearestBag = () => {
			let best = null, bd = REACH * REACH;
			for (const b of st.bags) {
				const d = (b.x - st.p.x) ** 2 + (b.y - st.p.y) ** 2;
				if (d <= bd) { bd = d; best = b; }
			}
			return best;
		};

		const input = () => {
			let mx = 0, my = 0;
			for (const k of keys) { const d = KEY_DIR[k]; if (d) { mx += d[0]; my += d[1]; } }
			const { ox, oy } = cam;                    // aim through what the player SEES
			const bag = edge.interact ? nearestBag() : null;
			let take = null;
			if (bag && ctl.room()) take = bag.drops[0];
			else if (bag) note("Inventory full", "#f3a39c");
			const out = { mx: Math.sign(mx), my: Math.sign(my), ax: (mouse.x - ox) / px - st.p.x, ay: (mouse.y - oy) / px - st.p.y,
				fire: mouse.down || auto, ability: edge.ability, heal: edge.interact, take, recall: edge.recall,
				enter: edge.interact && !bag };
			edge.ability = edge.interact = edge.recall = false;
			return out;
		};

		const handle = (ev) => {
			if (ev.type === "level") note(`Level ${ev.level}!`, "#cdc6fb");
			if (ev.local) return;
			if (ev.type === "pickup") {
				const d = run.dungeon.drops[ev.drop];
				const slot = ctl.take(ev.drop, d);
				if (slot === undefined) return;            // input() never takes into a full bag
				client.report({ ...ev, slot });
				const name = nameOf({ ...d, kind: run.bases[d.base_id]?.kind });
				loot.push(name);
				note(`Picked up ${name}`, "#e9c25a");
				return;
			}
			client.report(ev);
		};

		const finish = (status) => {
			ended = true;
			ctl.ended = true;
			setEnding(status);
			client.flush();
			const h = st.hero;
			setTimeout(() => onEnd({ status, loot, items: ctl.items, realm: run.realm, xp: h.xp - h.startXp, level: h.level, levelUp: h.level > h.startLevel }),
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
			if (gear) note("Gear changed", "#cdc6fb");
			for (const ev of st.events) handle(ev);
			if (st.status === "dead" || st.status === "recalled" || st.status === "complete") {
				finish(st.status === "complete" ? "completed" : st.status);
			}
		};

		const bagHint = () => {
			const b = nearestBag();
			if (!b && st.portal && Math.hypot(st.portal.x - st.p.x, st.portal.y - st.p.y) <= REACH)
				return [{ text: "E: leave the Shallows", color: "#9fe7ff" }];
			if (!b) return [];
			const d = run.dungeon.drops[b.drops[0]];
			return [{ text: `E: take ${nameOf({ ...d, kind: run.bases[d.base_id]?.kind })}${b.drops.length > 1 ? ` (+${b.drops.length - 1})` : ""}`, color: "#e9c25a" }];
		};

		// DEV ONLY: step the real loop without frames (a hidden tab gets none).
		if (import.meta.env.DEV) window.__halcyon.advance = (n) => { for (let i = 0; i < n && !ended; i++) tick(); return st.status; };

		let acc = 0, last = performance.now();
		const frame = (now) => {
			acc += Math.min(250, now - last);
			last = now;
			while (acc >= STEP_MS && !ended) { acc -= STEP_MS; tick(); }
			while (notes.length && notes[0].until < st.tick) notes.shift();
			alpha = ended ? 1 : acc / STEP_MS;
			const at = (o) => {
				const q = prev.get(o);
				return q ? { x: q[0] + (o.x - q[0]) * alpha, y: q[1] + (o.y - q[1]) * alpha } : o;
			};
			const pp = at(st.p);
			cam = camera(st, cv.width, cv.height, px, pp);
			draw(g, st, { width: cv.width, height: cv.height, px, at,
				aim: { x: (mouse.x - cam.ox) / px - pp.x, y: (mouse.y - cam.oy) / px - pp.y },
				notes: [...notes, ...(ended ? [] : bagHint())] });
			raf = requestAnimationFrame(frame);
		};
		raf = requestAnimationFrame(frame);

		const onKeyDown = (e) => {
			if (KEY_DIR[e.code]) { keys.add(e.code); e.preventDefault(); return; }
			if (e.repeat) return;
			if (e.code === "Space" || e.code === "KeyQ") { edge.ability = true; e.preventDefault(); }
			else if (e.code === "KeyE") edge.interact = true;
			else if (e.code === "KeyR") edge.recall = true;
			else if (e.code === "KeyF") { auto = !auto; note(auto ? "Auto-fire on" : "Auto-fire off"); }
		};
		const onKeyUp = (e) => keys.delete(e.code);
		const toCanvas = (e) => {
			const r = cv.getBoundingClientRect(), dpr = cv.width / Math.max(1, r.width);
			mouse.x = (e.clientX - r.left) * dpr; mouse.y = (e.clientY - r.top) * dpr;
		};
		const onMove = (e) => toCanvas(e);
		const onDown = (e) => { toCanvas(e); if (e.button === 0) mouse.down = true; if (e.button === 2) edge.ability = true; };
		const onUp = (e) => { if (e.button === 0) mouse.down = false; };
		const onBlur = () => { keys.clear(); mouse.down = false; };
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
	}, [run, client, onEnd]);

	return (
		<>
			<canvas ref={canvasRef} className="hr-canvas hr-canvas-run" aria-label="The dungeon" />
			{ending && <div className={"hr-ending res-" + ending}>{{ completed: "Cleared", recalled: "Recalled", dead: "Fallen" }[ending]}</div>}
		</>
	);
}
