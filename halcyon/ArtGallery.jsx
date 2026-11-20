// Halcyon Rift's art studio — a DEV-ONLY page (`/halcyon?art` under the dev server;
// the production build leaves it out). It is the whole art workflow on one page:
//
//   1. copy a prompt (artPrompts.js, in the order to make things),
//   2. paste it into the image generator, and drop what comes back here,
//   3. the cleanup step (artClean.js) cuts it out, reads it at its own pixels and puts it on the
//      shared colors, and it appears in a real room at game size,
//   4. "Use this" writes the finished picture into the game (artDevPlugin.js).
//
// The rooms are drawn by the game's own draw functions, so what they show is what a
// run shows: the picture where one exists, the greybox shape where none does.
import { useEffect, useRef, useState } from "react";
import { SLOTS, MANIFEST, RIFT_NAMES, loadArt, override, sprite, artPx, setArtPx } from "./art.js";
import { cleanFor, splitFor } from "./artClean.js";
import { BATCHES, promptFor } from "./artPrompts.js";
import { drawMap, drawEnemyBody, drawPlayer, drawShots, COLORS, PALETTES, TOWN } from "./render.js";
import { ENEMY } from "./sim.js";

const RIFTS = ["shallows", "fracture", "ashen", "town"];
const CLASSES = ["ranger", "paladin", "diviner", "ninja"];
const FOES = { shallows: ["chaser", "shooter", "radial"], fracture: ["shard", "splitter", "splinter", "flicker"], ashen: ["cinder", "kiln", "smolder"], town: [] };
const BOSSES = { shallows: "tidewarden", fracture: "breach", ashen: "pyre" };
const FACE = { down: { x: 0, y: 1 }, right: { x: 1, y: 0 }, left: { x: -1, y: 0 }, up: { x: 0, y: -1 } };
const SIZES = [32, 48, 64];
const riftOf = (keys) => keys.map((k) => SLOTS[k].rift).find(Boolean) || "shallows";
const itemId = (item) => item.keys.join("+");

/* A small room of each place: walls round the edge, the tiles that place has. */
function room(rift) {
	const w = 17, h = 8, rows = [];
	for (let y = 0; y < h; y++) {
		let r = "";
		for (let x = 0; x < w; x++) {
			const edge = y === 0 || y === h - 1 || x === 0 || x === w - 1;
			const rock = (x === 2 && y === 5) || (x === 14 && y === 2);
			const pool = y === 6 && x >= 6 && x <= 8;
			r += edge ? "#" : rock ? "o" : pool && (rift === "shallows" || rift === "town") ? "~" : pool && rift === "fracture" ? "x" : ".";
		}
		rows.push(r);
	}
	return { w, h, tiles: rows };
}

/* `cssPx` is a tile in CSS pixels; the canvas is drawn at the screen's own pixels, as
 * the game's is. */
function Room({ rift, px: cssPx, facing, tick }) {
	const ref = useRef(null);
	const st = useRef(null);
	if (!st.current || st.current.rift !== rift) st.current = { ...room(rift), rift };
	useEffect(() => {
		const cv = ref.current, g = cv.getContext("2d"), dpr = window.devicePixelRatio || 1, px = cssPx * dpr, s = st.current;
		cv.width = s.w * px; cv.height = s.h * px;
		cv.style.width = `${s.w * cssPx}px`;
		g.fillStyle = "#1b2220"; g.fillRect(0, 0, cv.width, cv.height);
		drawMap(g, s, 0, 0, px, cv.width, cv.height, PALETTES[rift] || TOWN);
		const face = FACE[facing], clock = { tick };
		CLASSES.forEach((c, i) => drawPlayer(g, { r: 0.4, hurt: 0 }, (2 + i * 1.6) * px, 2.6 * px, px, face, c, false, tick));
		FOES[rift].forEach((type, i) => drawEnemyBody(g, clock, { type, r: ENEMY[type].r, flash: 0, phase: 1 }, (2 + i * 1.6) * px, 4.6 * px, px, COLORS[type], false, face));
		if (BOSSES[rift]) drawEnemyBody(g, clock, { type: "boss", form: BOSSES[rift], r: ENEMY.boss.r, flash: 0, phase: 1 }, 12 * px, 4.6 * px, px, COLORS[BOSSES[rift]] || COLORS.boss, false, face);
		const dir = face.x || face.y ? face : FACE.right;
		drawShots(g, [
			{ owner: "p", x: 9, y: 2.2, vx: dir.x * 15, vy: dir.y * 15, r: 0.1 },
			{ owner: "e", x: 10.2, y: 2.2, vx: -dir.x * 7, vy: -dir.y * 7, r: 0.15, dmg: 10 },
			{ owner: "e", x: 11.2, y: 2.2, vx: -dir.x * 7, vy: -dir.y * 7, r: 0.2, dmg: 30 },
		], (x) => x * px, (y) => y * px, px, (o) => o);
	});
	return <canvas ref={ref} style={{ display: "block", imageRendering: "pixelated", border: "1px solid #2c3532" }} />;
}

/* A file to RGBA at its OWN size: reading the generator's pixel grid needs every
 * screen pixel of it (a shrink here would blur the grid before it is read). Only a
 * truly huge file is reduced. */
async function decode(file) {
	const bmp = await createImageBitmap(file);
	const k = Math.min(1, 3072 / Math.max(bmp.width, bmp.height));
	const cv = document.createElement("canvas");
	cv.width = Math.round(bmp.width * k); cv.height = Math.round(bmp.height * k);
	const g = cv.getContext("2d", { willReadFrequently: true });
	g.imageSmoothingQuality = "high";
	g.drawImage(bmp, 0, 0, cv.width, cv.height);
	const d = g.getImageData(0, 0, cv.width, cv.height);
	return { w: d.width, h: d.height, data: d.data };
}
function toCanvas(sheet) {
	const cv = document.createElement("canvas");
	cv.width = sheet.w; cv.height = sheet.h;
	cv.getContext("2d").putImageData(new ImageData(new Uint8ClampedArray(sheet.data), sheet.w, sheet.h), 0, 0);
	return cv;
}
const base64Of = (file) => new Promise((ok, fail) => { const r = new FileReader(); r.onload = () => ok(String(r.result).split(",")[1]); r.onerror = fail; r.readAsDataURL(file); });

function Big({ canvas, scale = 4 }) {
	return <canvas width={canvas.width} height={canvas.height}
		style={{ width: canvas.width * scale, height: canvas.height * scale, imageRendering: "pixelated", background: "repeating-conic-gradient(#2a3230 0% 25%, #222927 0% 50%) 0 0 / 16px 16px", verticalAlign: "top" }}
		ref={(cv) => { if (cv) { const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height); g.drawImage(canvas, 0, 0); } }} />;
}

function Item({ item, batch, pending, onFile, onUse, onDiscard, busy, px }) {
	const [over, setOver] = useState(false);
	const [copied, setCopied] = useState(false);
	const made = item.keys.every((k) => MANIFEST[k]);
	const copy = async () => {
		const text = promptFor(item, batch, px);
		try { await navigator.clipboard.writeText(text); } catch {
			const ta = document.createElement("textarea"); ta.value = text; document.body.appendChild(ta); ta.select(); document.execCommand("copy"); ta.remove();
		}
		setCopied(true); setTimeout(() => setCopied(false), 1500);
	};
	const p = pending[itemId(item)];
	return (
		<div onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
			onDrop={(e) => { e.preventDefault(); setOver(false); if (e.dataTransfer.files[0]) onFile(item, e.dataTransfer.files[0]); }}
			style={{ border: `1px ${over ? "solid #7fe3f0" : "dashed #3a4441"}`, borderRadius: 8, padding: "10px 12px", margin: "8px 0", background: over ? "rgba(127,227,240,.07)" : "transparent" }}>
			<div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
				<strong style={{ flex: "1 1 auto" }}>{item.keys.map((k) => SLOTS[k].label).join(", ")}</strong>
				<span style={{ color: made ? "#6fd36a" : "#8e8a80" }}>{made ? "✓ in the game" : "not made yet"}</span>
			</div>
			<div style={{ display: "flex", gap: 8, flexWrap: "wrap", margin: "8px 0 0" }}>
				<button className="btn btn-gold" onClick={copy}>{copied ? "Copied" : "Copy prompt"}</button>
				<label className="btn btn-ghost" style={{ cursor: "pointer" }}>
					Choose image<input type="file" accept="image/*" hidden onChange={(e) => { if (e.target.files[0]) onFile(item, e.target.files[0]); e.target.value = ""; }} />
				</label>
				<span style={{ opacity: 0.6, alignSelf: "center" }}>or drop it here</span>
			</div>
			{p && (
				<div style={{ marginTop: 10 }}>
					{p.error ? <p style={{ color: "#ff9b8d", margin: 0 }}>{p.error}</p> : <>
						<div style={{ display: "flex", gap: 12, flexWrap: "wrap", alignItems: "flex-start" }}>
							{p.canvases.map(([k, cv]) => <div key={k}><div style={{ fontSize: ".85rem", opacity: 0.7 }}>{SLOTS[k].label}</div><Big canvas={cv} scale={k.startsWith("tile.") ? 6 : SLOTS[k].h >= 40 ? 3 : 4} /></div>)}
						</div>
						{p.notes.map((n, i) => <p key={i} style={{ color: "#e9c25a", margin: "6px 0 0" }}>Note: {n}</p>)}
						<div style={{ display: "flex", gap: 8, marginTop: 8 }}>
							<button className="btn btn-gold" disabled={busy} onClick={() => onUse(item)}>Use this</button>
							<button className="btn btn-ghost" onClick={() => onDiscard(item)}>Discard</button>
						</div>
					</>}
				</div>
			)}
		</div>
	);
}

export default function ArtGallery({ onExit }) {
	const [px, setPx] = useState(48);
	const [facing, setFacing] = useState("down");
	const [tick, setTick] = useState(0);
	const [rift, setRift] = useState("shallows");
	const [pending, setPending] = useState({});      // itemId -> { item, file, canvases, notes, facings, error }
	/* The Ranger's height in tiles; with the Ranger's own pixel count it sets the
	 * shared density (art pixels a tile) that every other picture is matched to. */
	const saved = MANIFEST["player.ranger"];
	const [tall, setTall] = useState(() => (saved?.h ? Math.round(((saved.h - 2) / artPx()) * 20) / 20 : 1.25));
	const [rangerH, setRangerH] = useState(saved?.h ? saved.h - 2 : 0);   // its native height, saved or being tried
	const [density, setDensity] = useState(artPx());
	const [busy, setBusy] = useState(false);
	const [message, setMessage] = useState("");
	const [refOk, setRefOk] = useState(false);
	useEffect(() => { loadArt(); }, []);
	useEffect(() => {                      // the clock, so animated sheets play and loads show up
		let raf = 0;
		const go = () => { setTick((t) => t + 1); raf = requestAnimationFrame(go); };
		raf = requestAnimationFrame(go);
		return () => cancelAnimationFrame(raf);
	}, []);
	useEffect(() => { fetch("/__halcyon-art/source/player.ranger", { method: "HEAD" }).then((r) => setRefOk(r.ok)).catch(() => {}); }, [MANIFEST["player.ranger"]?.v]);

	/* The density a Ranger of `h` art pixels gives at `t` tiles tall. */
	const densityFor = (h, t) => Math.max(8, Math.min(64, Math.round(h / t)));
	const applyDensity = (n) => { setArtPx(n); setDensity(n); };
	const process = async (item, file, px = density) => {
		setRift(riftOf(item.keys));
		try {
			const img = await decode(file);
			let results;
			if (item.keys.length > 1) {
				const split = splitFor(item.keys, img);
				if (split.error) { setPending((p) => ({ ...p, [itemId(item)]: { item, file, error: `${split.error}.` } })); return; }
				results = split.parts.map(([k, part]) => [k, cleanFor(k, part, { artPx: px, keyed: true })]);
				if (!split.plain) results[0][1].notes.push("the background was not one flat color, so some of it may be left — ask for a plain background");
			} else if (item.keys[0] === "player.ranger") {
				// The Ranger is kept exactly as drawn and SETS the density.
				const r = cleanFor("player.ranger", img, { artPx: px, exact: true });
				setRangerH(r.native);
				applyDensity(densityFor(r.native, tall));
				results = [["player.ranger", r]];
			} else results = [[item.keys[0], cleanFor(item.keys[0], img, { artPx: px })]];
			const canvases = results.map(([k, r]) => [k, toCanvas(r.sheet)]);
			const sizes = results.map(([, r]) => ({ w: r.w, h: r.h, facings: r.facings }));
			canvases.forEach(([k, cv], i) => override(k, cv, sizes[i]));
			setPending((p) => ({ ...p, [itemId(item)]: { item, file, canvases, sizes, notes: [...new Set(results.flatMap(([, r]) => r.notes))] } }));
			setMessage("");
		} catch (err) {
			setPending((p) => ({ ...p, [itemId(item)]: { item, file, error: `Could not read ${file.name}: ${err.message}` } }));
		}
	};
	/* A new character height: a new density from the Ranger, every unsaved try redone
	 * at it, and — once the Ranger is saved — the density written for the game. */
	const pickTall = (t) => {
		setTall(t);
		if (!rangerH) return;
		const n = densityFor(rangerH, t);
		applyDensity(n);
		for (const p of Object.values(pending)) if (p.file && !p.error && !p.item.keys.includes("player.ranger")) process(p.item, p.file, n);
		if (MANIFEST["player.ranger"]) fetch("/__halcyon-art/settings", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ artPx: n }) });
	};

	const discard = (item) => {
		for (const k of item.keys) override(k, null);
		loadArt();
		setPending((p) => { const n = { ...p }; delete n[itemId(item)]; return n; });
	};
	const use = async (item) => {
		const p = pending[itemId(item)];
		if (!p?.canvases) return;
		setBusy(true);
		try {
			const items = p.canvases.map(([key, cv], i) => ({ key, png: cv.toDataURL("image/png").split(",")[1], ...p.sizes[i] }));
			const res = await fetch("/__halcyon-art/save", { method: "POST", headers: { "content-type": "application/json" },
				body: JSON.stringify({ items, artPx: density, raw: await base64Of(p.file), rawName: p.file.name }) });
			const out = await res.json();
			if (!res.ok) throw new Error(out.error || res.status);
			setMessage(`Saved ${item.keys.map((k) => SLOTS[k].label).join(", ")} — it is in the game now.`);
			setPending((q) => { const n = { ...q }; delete n[itemId(item)]; return n; });
		} catch (err) { setMessage(`Could not save: ${err.message}`); }
		setBusy(false);
	};
	const remove = async (key) => {
		await fetch("/__halcyon-art/remove", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ key }) });
		override(key, null);
		setMessage(`Removed ${SLOTS[key].label}; its shape is back.`);
	};

	const total = Object.keys(SLOTS).length, made = Object.keys(MANIFEST).length;
	const firstOpen = BATCHES.findIndex((b) => !b.items.every((it) => it.keys.every((k) => MANIFEST[k])));
	const scale = +(px / density).toFixed(2);
	return (
		<div style={{ minHeight: "100vh", background: "#121615", color: "#e8e3d6", padding: "16px 20px 48px" }}>
			<div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 6 }}>
				<button className="btn btn-outline" onClick={onExit}>← Back</button>
				<h1 style={{ margin: 0, fontSize: "1.4rem" }}>Halcyon Rift — art studio</h1>
				<span style={{ opacity: 0.65 }}>dev only · {made} of {total} pictures made</span>
			</div>
			{message && <p style={{ color: "#e9c25a", margin: "6px 0" }}>{message}</p>}
			<div style={{ display: "flex", gap: 20, flexWrap: "wrap", alignItems: "flex-start" }}>
				{/* The room stays in view while you scroll the steps — only when the steps sit
				    BESIDE it; stacked, a pinned room would cover them. */}
				<style>{"@media (min-width:1320px){.hz-room{position:sticky;top:12px}}"}</style>
				<div className="hz-room" style={{ flex: "0 1 auto", maxWidth: "100%", overflowX: "auto" }}>
					<div style={{ display: "flex", gap: 6, flexWrap: "wrap", alignItems: "center", margin: "8px 0" }}>
						{RIFTS.map((r) => <button key={r} className={`btn ${r === rift ? "btn-gold" : "btn-ghost"}`} onClick={() => setRift(r)}>{RIFT_NAMES[r]}</button>)}
					</div>
					<Room rift={rift} px={px} facing={facing} tick={tick} />
					<div style={{ display: "flex", gap: 14, flexWrap: "wrap", alignItems: "center", margin: "8px 0" }}>
						<span>Tile {SIZES.map((s) => <button key={s} className={`btn ${s === px ? "btn-gold" : "btn-ghost"}`} onClick={() => setPx(s)}>{s}px</button>)}
							<span style={{ opacity: 0.6 }}> {scale} screen px per art px</span></span>
						<span>Facing {Object.keys(FACE).map((f) => <button key={f} className={`btn ${f === facing ? "btn-gold" : "btn-ghost"}`} onClick={() => setFacing(f)}>{f}</button>)}</span>
						<label>Ranger height <select value={tall} onChange={(e) => pickTall(Number(e.target.value))} style={{ fontSize: 16 }}>
							{[1, 1.15, 1.25, 1.4, 1.6].map((t) => <option key={t} value={t}>{t} tiles</option>)}</select>
							<span style={{ opacity: 0.6 }}> {density} art px a tile{rangerH ? `, Ranger ${rangerH} px tall` : ""}</span></label>
					</div>
				</div>
				<div style={{ flex: "1 1 440px", minWidth: 0 }}>
					<details style={{ marginBottom: 10 }}>
						<summary style={{ cursor: "pointer" }}>How this works</summary>
						<ol style={{ lineHeight: 1.5, paddingLeft: 20 }}>
							<li>Work through the steps in order. In each one, Copy prompt, paste it into the image generator, and generate.</li>
							<li>From step 4 on, also attach the Ranger reference image (step 1 has a button to download it).</li>
							<li>Drop the result on its box. It is cut out, read at the generator's own pixel size, put on the game's shared colors, and shows in the room at game size.</li>
							<li>Not right? Generate again and drop the new one. Right? Use this. It is in the game at once.</li>
							<li>Tell Claude when a step is done; Claude checks it in a real run and ships it.</li>
						</ol>
					</details>
					{BATCHES.map((batch, i) => (
						<details key={batch.title} open={i === (firstOpen < 0 ? 0 : firstOpen)} style={{ borderTop: "1px solid #2c3532", padding: "8px 0" }}>
							<summary style={{ cursor: "pointer", fontSize: "1.05rem" }}>
								{batch.title} {batch.items.every((it) => it.keys.every((k) => MANIFEST[k])) ? <span style={{ color: "#6fd36a" }}>✓</span> : null}
							</summary>
							<p style={{ opacity: 0.8, margin: "6px 0" }}>{batch.why}</p>
							{batch.anchor && refOk && <p style={{ margin: "6px 0" }}><a href="/__halcyon-art/source/player.ranger" style={{ color: "#7fe3f0" }}>Download the Ranger reference image</a> to attach from step 4 on.</p>}
							{batch.items.map((item) => <Item key={itemId(item)} item={item} batch={batch} pending={pending} busy={busy} px={density}
								onFile={(it, f) => process(it, f)} onUse={use} onDiscard={discard} />)}
						</details>
					))}
					<details style={{ borderTop: "1px solid #2c3532", padding: "8px 0" }}>
						<summary style={{ cursor: "pointer" }}>Every picture ({made} of {total})</summary>
						<table style={{ borderCollapse: "collapse", marginTop: 6 }}><tbody>
							{Object.entries(SLOTS).map(([k, s]) => {
								const rec = sprite(k);
								return (
									<tr key={k}>
										<td style={{ padding: "3px 8px" }}>{s.group}</td>
										<td style={{ padding: "3px 8px" }}>{s.label}</td>
										<td style={{ padding: "3px 8px", color: MANIFEST[k] ? "#6fd36a" : "#8e8a80" }}>{MANIFEST[k] ? "made" : rec ? "trying" : "shape"}</td>
										<td style={{ padding: "3px 8px" }}>{MANIFEST[k] && <button className="btn btn-ghost" onClick={() => remove(k)}>Remove</button>}</td>
									</tr>
								);
							})}
						</tbody></table>
					</details>
				</div>
			</div>
		</div>
	);
}
