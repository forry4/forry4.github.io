// Halcyon Rift — the greybox (design §23): a roster, gear, the vault, and the
// Shallows played as colored shapes.
//
// TOWN is React over the server's state (GET /halcyon/state): four character slots,
// the selected character's equipment and inventory, and the account vault. Every
// change to it is one server call, and the page re-reads the state after each.
//
// THE DUNGEON runs in this browser (sim.js, a fixed 60 Hz deterministic step) and
// is drawn on a canvas (render.js). The server generated it and pre-rolled its
// drops; what the fight reports goes through client.js's queue, which is saved on
// the device before it is sent. Nothing here decides what an item IS — a pickup
// names a drop id, and the server mints the item it rolled for that drop.
//
// Route: /halcyon. No room segment — there is nothing to share a link to.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../shared/theme.js";
import { lobbyCss, LobbyHeader, LobbyUser, LobbyLoading } from "../shared/lobby.jsx";
import { GAME_ACCENTS } from "../shared/accents.js";
import { makeClient } from "./client.js";
import { createSim, step, TPS, REACH } from "./sim.js";
import { bakeMap, camera, draw } from "./render.js";
import cssText from "./HalcyonRift.css?inline";

const styles = baseCss + lobbyCss + cssText;
const ACCENT = { "--lby-accent": GAME_ACCENTS.halcyon };

const NAMES = { shortbow: "Shortbow", longbow: "Longbow", leather_vest: "Leather Vest",
	volley_quiver: "Volley Quiver", band_of_vigor: "Band of Vigor", band_of_focus: "Band of Focus",
	kingfisher_eye: "Kingfisher's Eye" };
const ENCHANT_NAMES = { max_hp: "Max HP", max_mp: "Max MP", attack: "Attack", defense: "Defense",
	attack_speed: "Attack speed", ability_power: "Ability power", mp_regen: "MP regen", hp_regen: "HP regen" };
const SLOT_NAMES = { weapon: "Weapon", armor: "Armor", ability: "Ability", ring1: "Ring", ring2: "Ring" };
const ABBR = { shortbow: "SB", longbow: "LB", leather_vest: "LV", volley_quiver: "VQ",
	band_of_vigor: "BV", band_of_focus: "BF", kingfisher_eye: "KE" };
const nameOf = (it) => `${NAMES[it.base_id] || it.base_id} · T${it.tier}`;
const pct = (q) => `${Math.round(q * 100)}%`;

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

export default function HalcyonRift({ authUser, onExit }) {
	const client = useMemo(() => makeClient(authUser), [authUser?.id, authUser?.session_token]); // eslint-disable-line react-hooks/exhaustive-deps
	const [view, setView] = useState(null);
	const [error, setError] = useState(null);
	const [busy, setBusy] = useState(false);
	const [selChar, setSelChar] = useState(null);
	const [picked, setPicked] = useState(null);       // an item id
	const [confirmDiscard, setConfirmDiscard] = useState(false);
	const [run, setRun] = useState(null);
	const [result, setResult] = useState(null);

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
		setBusy(false); setPicked(null); setConfirmDiscard(false);
		await refresh();
		// After the refresh, which clears it. The store's reasons are lower-case clauses.
		if (failed) setError(failed[0].toUpperCase() + failed.slice(1));
	}, [refresh]);

	const items = view?.items || [];
	const byPlace = useMemo(() => Object.fromEntries(items.map((it) => [placeKey(it), it]).filter(([k]) => k)), [items]);
	const pickedItem = items.find((it) => it.item_id === picked) || null;
	const char = view?.characters.find((c) => c.char_id === selChar) || null;

	const chooseChar = (c) => {
		setPicked(null);
		setSelChar(c.char_id);
		// A run this character left open (a closed tab) ends as a recall now (§13.1a).
		if (view.open_runs[c.char_id]) act(() => client.openCharacter(c.char_id));
	};

	const clickSlot = (to) => {
		const there = byPlace[keyOf(to)];
		if (!pickedItem) { if (there) { setPicked(there.item_id); setConfirmDiscard(false); } return; }
		if (there && there.item_id === pickedItem.item_id) { setPicked(null); return; }
		act(() => client.move(pickedItem.item_id, to, pickedItem.version));
	};

	const enter = () => act(async () => {
		await client.flush();
		if (client.pendingRun()) throw new Error("Your last run is still being saved. Try again in a moment.");
		const { run_id, dungeon } = await client.startRun(char.char_id);
		client.beginRun(run_id);
		const gear = items.filter((it) => it.loc === "equipped" && it.char_id === char.char_id);
		const used = new Set(items.filter((it) => it.loc === "inventory" && it.char_id === char.char_id).map((it) => it.slot_index));
		const free = [...Array(view.limits.inventory).keys()].filter((i) => !used.has(i));
		setResult(null);
		setRun({ run_id, dungeon, gear, free });
	});

	const endRun = useCallback((outcome) => {
		setRun(null);
		setResult(outcome);
		refresh();
	}, [refresh]);

	const header = <LobbyHeader onBack={run ? null : onExit} title={run ? run.dungeon.name : "Halcyon Rift"}
		user={<LobbyUser user={authUser} profile={!run} />} />;

	if (run) {
		return (
			<div className="app halcyon hr-run fg-table" style={ACCENT}><style>{styles}</style>
				{header}
				<Dungeon run={run} client={client} onEnd={endRun} />
			</div>
		);
	}
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
	const identical = pickedItem ? items.filter((it) => it.item_id !== pickedItem.item_id
		&& ["vault", "inventory", "equipped"].includes(it.loc)
		&& it.base_id === pickedItem.base_id && it.tier === pickedItem.tier
		&& it.kind === pickedItem.kind && it.slot_count === pickedItem.slot_count) : [];

	return (
		<div className="app halcyon fg-table" style={ACCENT}><style>{styles}</style>
			{header}
			<main className="hr-town">
				{result && <ResultPanel result={result} onClose={() => setResult(null)} />}
				{error && <div className="hr-error" role="alert">{error}</div>}

				<section className="hr-roster fg-panel" aria-label="Characters">
					<h2 className="fg-label">Characters</h2>
					{slots.map((s) => {
						const c = view.characters.find((x) => x.slot === s);
						if (!c) return (
							<button key={s} className="hr-char hr-char-empty" disabled={busy}
								onClick={() => act(() => client.createCharacter(s))}>+ New Ranger</button>);
						return (
							<button key={s} className={"hr-char" + (c.char_id === selChar ? " sel" : "")}
								onClick={() => chooseChar(c)}>
								<span className="hr-char-glyph" aria-hidden="true" />
								<span className="hr-char-name">Ranger</span>
								<span className="fg-label-soft">Level {c.level}</span>
							</button>);
					})}
					{view.fallen.length > 0 && <p className="hr-fallen">{view.fallen.length} fallen</p>}
				</section>

				<section className="hr-hero fg-panel" aria-label="Equipment and inventory">
					{char ? <>
						<h2 className="fg-label">Equipment</h2>
						<div className="hr-equip">
							{view.limits.equip.map((s) => (
								<Slot key={s} label={SLOT_NAMES[s]} item={byPlace[keyOf(at.eq(char.char_id, s))]}
									picked={picked} bases={view.bases} onClick={() => clickSlot(at.eq(char.char_id, s))} />))}
						</div>
						<h2 className="fg-label">Inventory</h2>
						<div className="hr-grid hr-grid-inv">
							{[...Array(view.limits.inventory).keys()].map((i) => (
								<Slot key={i} item={byPlace[keyOf(at.inv(char.char_id, i))]} picked={picked}
									bases={view.bases} onClick={() => clickSlot(at.inv(char.char_id, i))} />))}
						</div>
						<button className="btn btn-gold hr-enter" disabled={busy} onClick={enter}>Enter the Shallows</button>
					</> : <p className="hr-hint">Make a Ranger to begin.</p>}
				</section>

				<section className="hr-vault fg-panel" aria-label="Vault">
					<h2 className="fg-label">Vault</h2>
					<div className="hr-grid hr-grid-vault">
						{[...Array(view.limits.vault).keys()].map((i) => (
							<Slot key={i} item={byPlace[keyOf(at.vault(i))]} picked={picked} bases={view.bases}
								onClick={() => clickSlot(at.vault(i))} />))}
					</div>
				</section>

				<section className="hr-detail fg-panel" aria-label="Selected item">
					{pickedItem ? <>
						<h2 className="fg-label">{nameOf(pickedItem)}{pickedItem.kind === "unique" ? " · Unique" : ""}</h2>
						<ul className="hr-enchants">
							{pickedItem.enchants.length ? pickedItem.enchants.map((e, i) => (
								<li key={i}>{ENCHANT_NAMES[e.id] || e.id} <span className="hr-q">{pct(e.q)}</span></li>))
								: <li className="hr-q">No enchantments</li>}
						</ul>
						<p className="hr-hint">Click a slot to move it there.</p>
						<div className="hr-actions">
							{identical.map((o) => (
								<button key={o.item_id} className="btn btn-outline" disabled={busy}
									onClick={() => act(() => client.fuse(pickedItem.item_id, o.item_id))}>
									Fuse with {o.loc === "vault" ? `vault ${o.slot_index + 1}` : o.loc}</button>))}
							{confirmDiscard
								? <button className="btn btn-outline" disabled={busy}
									onClick={() => act(() => client.discard(pickedItem.item_id, pickedItem.version))}>Confirm discard</button>
								: <button className="btn btn-ghost" onClick={() => setConfirmDiscard(true)}>Discard</button>}
						</div>
					</> : <p className="hr-hint">Select an item to see it.</p>}
				</section>
			</main>
		</div>
	);
}

function Slot({ label, item, picked, bases, onClick }) {
	const fam = item ? bases[item.base_id]?.slot : null;
	return (
		<button className={"hr-slot" + (item ? ` has fam-${fam}` : "") + (item && item.item_id === picked ? " sel" : "")
			+ (item?.kind === "unique" ? " unique" : "")}
			title={item ? nameOf(item) : label || "Empty"} aria-label={item ? nameOf(item) : `${label || "Empty"} slot`}
			onClick={onClick}>
			{item ? <><span className="hr-abbr">{ABBR[item.base_id] || "?"}</span><span className="hr-tier">{item.tier}</span>
				{item.slot_count > 0 && <span className="hr-dots">{"•".repeat(item.slot_count)}</span>}</>
				: label && <span className="hr-slot-label">{label}</span>}
		</button>
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
			<button className="btn btn-outline" onClick={onClose}>OK</button>
		</section>
	);
}

// ── the dungeon ─────────────────────────────────────────────────────────────
const KEY_DIR = { KeyW: [0, -1], ArrowUp: [0, -1], KeyS: [0, 1], ArrowDown: [0, 1],
	KeyA: [-1, 0], ArrowLeft: [-1, 0], KeyD: [1, 0], ArrowRight: [1, 0] };

function Dungeon({ run, client, onEnd }) {
	const canvasRef = useRef(null);
	const [ending, setEnding] = useState(null);

	useEffect(() => {
		const cv = canvasRef.current;
		const g = cv.getContext("2d");
		const st = createSim(run.dungeon, run.gear);
		const free = [...run.free];
		const loot = [];
		const notes = [];
		const keys = new Set();
		const mouse = { x: 0, y: 0, down: false };
		const edge = { ability: false, interact: false, recall: false };
		let auto = false, px = 32, map = null, raf = 0, ended = false;
		// DEV ONLY (stripped from a production build): the live sim, and a seam for a
		// scripted driver, so a whole run can be played through the real page.
		if (import.meta.env.DEV) window.__halcyon = { st, drive: null };

		const note = (text, color) => { notes.push({ text, color, until: st.tick + 4 * TPS }); };
		const resize = () => {
			const dpr = window.devicePixelRatio || 1, r = cv.getBoundingClientRect();
			cv.width = Math.max(1, Math.round(r.width * dpr));
			cv.height = Math.max(1, Math.round(r.height * dpr));
			px = Math.max(18, Math.floor(Math.min(cv.height / 12, cv.width / 16)));
			map = bakeMap(st, px);
		};
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
			const { ox, oy } = camera(st, cv.width, cv.height, px);
			const bag = edge.interact ? nearestBag() : null;
			let take = null;
			if (bag && free.length) take = bag.drops[0];
			else if (bag) note("Inventory full", "#f3a39c");
			const out = { mx: Math.sign(mx), my: Math.sign(my), ax: (mouse.x - ox) / px - st.p.x, ay: (mouse.y - oy) / px - st.p.y,
				fire: mouse.down || auto, ability: edge.ability, heal: edge.interact, take, recall: edge.recall,
				enter: edge.interact && !bag };
			edge.ability = edge.interact = edge.recall = false;
			return out;
		};

		const handle = (ev) => {
			if (ev.local) return;
			if (ev.type === "pickup") {
				const d = run.dungeon.drops[ev.drop];
				client.report({ ...ev, slot: free.shift() });
				const name = `${NAMES[d.base_id] || d.base_id} T${d.tier}`;
				loot.push(name);
				note(`Picked up ${name}`, "#e9c25a");
				return;
			}
			client.report(ev);
		};

		const finish = (status) => {
			ended = true;
			setEnding(status);
			client.flush();
			setTimeout(() => onEnd({ status, loot }), status === "dead" ? 1400 : 700);
		};

		const tick = () => {
			const drive = import.meta.env.DEV && window.__halcyon?.drive;
			step(st, drive ? drive(st) : input());
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
			return [{ text: `E: take ${NAMES[d.base_id] || d.base_id} T${d.tier}${b.drops.length > 1 ? ` (+${b.drops.length - 1})` : ""}`, color: "#e9c25a" }];
		};

		// DEV ONLY: step the real loop without frames (a hidden tab gets none).
		if (import.meta.env.DEV) window.__halcyon.advance = (n) => { for (let i = 0; i < n && !ended; i++) tick(); return st.status; };

		let acc = 0, last = performance.now();
		const STEP_MS = 1000 / TPS;
		const frame = (now) => {
			acc += Math.min(250, now - last);
			last = now;
			while (acc >= STEP_MS && !ended) { acc -= STEP_MS; tick(); }
			while (notes.length && notes[0].until < st.tick) notes.shift();
			const { ox, oy } = camera(st, cv.width, cv.height, px);
			draw(g, st, map, { width: cv.width, height: cv.height, px,
				aim: { x: (mouse.x - ox) / px - st.p.x, y: (mouse.y - oy) / px - st.p.y },
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
		<div className="hr-stage">
			<canvas ref={canvasRef} className="hr-canvas" aria-label="The dungeon" />
			{ending && <div className={"hr-ending res-" + ending}>{{ completed: "Cleared", recalled: "Recalled", dead: "Fallen" }[ending]}</div>}
			<p className="hr-keys">
				<kbd>WASD</kbd> move · <kbd>mouse</kbd> aim, hold to shoot · <kbd>F</kbd> auto-fire ·
				<kbd>Space</kbd> volley · <kbd>E</kbd> pick up · <kbd>R</kbd> recall
			</p>
		</div>
	);
}
