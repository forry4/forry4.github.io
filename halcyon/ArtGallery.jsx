// Halcyon Rift's art gallery — a DEV-ONLY page (`/halcyon?art` under `npm run dev`;
// the production build leaves it out). It draws every picture the game can use
// (art.js SLOTS) at real game size on each rift's own floor, through the SAME draw
// functions the game uses, so what it shows is what a run shows: the picture where
// one exists, the greybox shape where none does.
//
// A generated image can be TRIED here before it is anyone's job to cut it: drop it
// on a row and it is keyed off its flat #00FF00 background, cropped to what is left,
// shrunk to the slot's size and put in the game's place for that key — in this tab
// only. Nothing is saved; the real art goes through the manifest.
import { useEffect, useRef, useState } from "react";
import { SLOTS, MANIFEST, ART_PX, RIFT_NAMES, loadArt, override, sprite } from "./art.js";
import { drawMap, drawEnemyBody, drawPlayer, drawShots, COLORS, PALETTES, TOWN } from "./render.js";
import { ENEMY } from "./sim.js";

const RIFTS = ["shallows", "fracture", "ashen", "town"];
const CLASSES = ["ranger", "paladin", "diviner", "ninja"];
const FOES = { shallows: ["chaser", "shooter", "radial"], fracture: ["shard", "splitter", "splinter", "flicker"], ashen: ["cinder", "kiln", "smolder"], town: [] };
const BOSSES = { shallows: "tidewarden", fracture: "breach", ashen: "pyre" };
const FACE = { down: { x: 0, y: 1 }, right: { x: 1, y: 0 }, left: { x: -1, y: 0 }, up: { x: 0, y: -1 } };
const SIZES = [32, 48, 64, 80];

/* A small room: walls round the edge, a rock or two, water in the Shallows. */
function room(rift) {
	const w = 17, h = 8, rows = [];
	for (let y = 0; y < h; y++) {
		let r = "";
		for (let x = 0; x < w; x++) {
			const edge = y === 0 || y === h - 1 || x === 0 || x === w - 1;
			r += edge ? "#" : (x === 2 && y === 5) || (x === 14 && y === 2) ? "o" : rift === "shallows" && y === 6 && x >= 6 && x <= 8 ? "~" : ".";
		}
		rows.push(r);
	}
	return { w, h, tiles: rows };
}

/* `cssPx` is a tile in CSS pixels; the canvas is drawn at the screen's own pixels,
 * as the game's is, so a picture's art pixels land on whole screen pixels where
 * they would in a run. */
function Scene({ rift, px: cssPx, facing, tick }) {
	const ref = useRef(null);
	const st = useRef(room(rift)).current;
	useEffect(() => {
		const cv = ref.current, g = cv.getContext("2d"), px = cssPx * (window.devicePixelRatio || 1);
		cv.width = st.w * px; cv.height = st.h * px;
		cv.style.width = `${st.w * cssPx}px`;
		g.fillStyle = "#1b2220"; g.fillRect(0, 0, cv.width, cv.height);
		drawMap(g, st, 0, 0, px, cv.width, cv.height, PALETTES[rift] || TOWN);
		const s = { tick };
		const face = FACE[facing];
		CLASSES.forEach((c, i) => drawPlayer(g, { r: 0.4, hurt: 0 }, (2 + i * 1.6) * px, 2.6 * px, px, face, c, false, tick));
		FOES[rift].forEach((type, i) => {
			const e = { type, form: null, r: ENEMY[type].r, flash: 0, phase: 1 };
			drawEnemyBody(g, s, e, (2 + i * 1.6) * px, 4.6 * px, px, COLORS[type], false, face);
		});
		if (BOSSES[rift]) {
			const form = BOSSES[rift];
			drawEnemyBody(g, s, { type: "boss", form, r: ENEMY.boss.r, flash: 0, phase: 1 }, 12 * px, 4.6 * px, px,
				COLORS[form] || COLORS.boss, false, face);
		}
		const dir = face.x || face.y ? face : FACE.right;
		drawShots(g, [
			{ owner: "p", x: 9, y: 2.2, vx: dir.x * 15, vy: dir.y * 15, r: 0.1 },
			{ owner: "e", x: 10.2, y: 2.2, vx: -dir.x * 7, vy: -dir.y * 7, r: 0.15, dmg: 10 },
			{ owner: "e", x: 11.2, y: 2.2, vx: -dir.x * 7, vy: -dir.y * 7, r: 0.2, dmg: 30 },
		], (x) => x * px, (y) => y * px, px, (o) => o);
	});
	return <canvas ref={ref} style={{ display: "block", maxWidth: "100%", imageRendering: "pixelated", border: "1px solid #2c3532" }} />;
}

/* A dropped image, made ready to stand in for `key`: the green keyed out, cropped to
 * what is left, shrunk so it is `height` art pixels tall (tiles: the whole square),
 * centered in the slot's frame with its foot near the frame's bottom. `sheet3` reads
 * three facings side by side (down, side, up) into three rows. */
async function prepare(file, key, { height, sheet3 }) {
	const slot = SLOTS[key], tile = key.startsWith("tile.");
	const img = await createImageBitmap(file);
	const src = document.createElement("canvas");
	src.width = img.width; src.height = img.height;
	const sg = src.getContext("2d", { willReadFrequently: true });
	sg.drawImage(img, 0, 0);
	const out = document.createElement("canvas"), rows = sheet3 && !tile ? 3 : 1;
	out.width = slot.w; out.height = slot.h * rows;
	const og = out.getContext("2d");
	if (tile) {
		og.imageSmoothingQuality = "high";
		og.drawImage(src, 0, 0, slot.w, slot.h);
		return { canvas: out, rows };
	}
	const data = sg.getImageData(0, 0, src.width, src.height), d = data.data;
	for (let i = 0; i < d.length; i += 4) {
		const r = d[i], gg = d[i + 1], b = d[i + 2];
		if (gg > 140 && gg > r + 50 && gg > b + 50) d[i + 3] = 0;   // the #00FF00 background
	}
	sg.putImageData(data, 0, 0);
	const part = src.width / rows;
	for (let k = 0; k < rows; k++) {
		let x0 = Infinity, y0 = Infinity, x1 = -1, y1 = -1;
		for (let y = 0; y < src.height; y++)
			for (let x = Math.floor(k * part); x < Math.floor((k + 1) * part); x++)
				if (d[(y * src.width + x) * 4 + 3] > 0) { if (x < x0) x0 = x; if (x > x1) x1 = x; if (y < y0) y0 = y; if (y > y1) y1 = y; }
		if (x1 < 0) continue;
		const cw = x1 - x0 + 1, ch = y1 - y0 + 1, sc = Math.min(height / ch, slot.w / cw, slot.h / ch);
		const W = Math.max(1, Math.round(cw * sc)), H = Math.max(1, Math.round(ch * sc));
		const foot = Math.min(slot.h, Math.round(slot.h * 0.92));
		const tmp = document.createElement("canvas");
		tmp.width = W; tmp.height = H;
		const tg = tmp.getContext("2d");
		tg.imageSmoothingQuality = "high";
		tg.drawImage(src, x0, y0, cw, ch, 0, 0, W, H);
		// Pixel art has no half-see-through edge: every pixel is in or out.
		const td = tg.getImageData(0, 0, W, H);
		for (let i = 3; i < td.data.length; i += 4) td.data[i] = td.data[i] >= 128 ? 255 : 0;
		tg.putImageData(td, 0, 0);
		og.drawImage(tmp, Math.round((slot.w - W) / 2), k * slot.h + Math.max(0, foot - H));
	}
	return { canvas: out, rows };
}

function SlotRow({ id, slot, status, onDrop, onClear }) {
	const [over, setOver] = useState(false);
	const pick = (files) => { if (files?.[0]) onDrop(id, files[0]); };
	const rec = sprite(id);
	return (
		<tr onDragOver={(e) => { e.preventDefault(); setOver(true); }} onDragLeave={() => setOver(false)}
			onDrop={(e) => { e.preventDefault(); setOver(false); pick(e.dataTransfer.files); }}
			style={{ background: over ? "rgba(127,227,240,.12)" : undefined }}>
			<td style={{ padding: "4px 8px" }}>{slot.label}</td>
			<td style={{ padding: "4px 8px", opacity: 0.7 }}><code>{id}</code></td>
			<td style={{ padding: "4px 8px", opacity: 0.7 }}>{slot.w}×{slot.h}</td>
			<td style={{ padding: "4px 8px", color: status === "shape" ? "#8e8a80" : status === "preview" ? "#e9c25a" : "#6fd36a" }}>{status}</td>
			<td style={{ padding: "4px 8px" }}>
				{rec && <canvas width={rec.img.width} height={rec.img.height} style={{ height: rec.img.height * 2, imageRendering: "pixelated", verticalAlign: "middle" }}
					ref={(cv) => { if (cv) { const g = cv.getContext("2d"); g.clearRect(0, 0, cv.width, cv.height); g.drawImage(rec.img, 0, 0); } }} />}
			</td>
			<td style={{ padding: "4px 8px" }}>
				<label className="btn btn-ghost" style={{ cursor: "pointer" }}>
					Try an image<input type="file" accept="image/*" hidden onChange={(e) => pick(e.target.files)} />
				</label>
				{status === "preview" && <button className="btn btn-ghost" onClick={() => onClear(id)}>Clear</button>}
			</td>
		</tr>
	);
}

export default function ArtGallery({ onExit }) {
	const [px, setPx] = useState(48);
	const [facing, setFacing] = useState("down");
	const [tick, setTick] = useState(0);
	const [previews, setPreviews] = useState({});
	const [charH, setCharH] = useState(20);
	const [sheet3, setSheet3] = useState(false);
	const [note, setNote] = useState("");
	useEffect(() => { loadArt(); }, []);
	useEffect(() => {                      // the clock, so animated sheets play (and loads show up)
		let raf = 0;
		const go = () => { setTick((t) => t + 1); raf = requestAnimationFrame(go); };
		raf = requestAnimationFrame(go);
		return () => cancelAnimationFrame(raf);
	}, []);
	const drop = async (id, file) => {
		const slot = SLOTS[id], boss = slot.h >= 40, shot = slot.h <= 8;
		const height = shot ? slot.h : boss ? Math.round(charH * 2) : charH;
		try {
			const { canvas, rows } = await prepare(file, id, { height, sheet3: sheet3 && id.startsWith("player.") || sheet3 && id.startsWith("enemy.") });
			override(id, canvas, { facings: rows });
			setPreviews((p) => ({ ...p, [id]: file.name }));
			setNote(`${slot.label}: ${file.name}, ${canvas.width}×${canvas.height} art pixels`);
		} catch (err) { setNote(`Could not read ${file.name}: ${err.message}`); }
	};
	const clear = (id) => {
		override(id, null);
		loadArt();
		setPreviews((p) => { const n = { ...p }; delete n[id]; return n; });
	};
	const groups = {};
	for (const [id, slot] of Object.entries(SLOTS)) (groups[slot.group] ||= []).push([id, slot]);
	const statusOf = (id) => (previews[id] ? "preview" : MANIFEST[id] ? (sprite(id) ? "picture" : "loading") : "shape");
	const scale = px / ART_PX;
	return (
		<div style={{ minHeight: "100vh", background: "#121615", color: "#e8e3d6", padding: "16px 20px 48px" }}>
			<div style={{ display: "flex", gap: 12, alignItems: "center", flexWrap: "wrap", marginBottom: 12 }}>
				<button className="btn btn-outline" onClick={onExit}>← Back</button>
				<h1 style={{ margin: 0, fontSize: "1.4rem" }}>Halcyon Rift — art gallery</h1>
				<span style={{ opacity: 0.65 }}>dev only · {Object.keys(MANIFEST).length} of {Object.keys(SLOTS).length} pictures made</span>
			</div>
			<div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap", marginBottom: 16 }}>
				<span>Tile size:{" "}
					{SIZES.map((s) => <button key={s} className={`btn ${s === px ? "btn-gold" : "btn-ghost"}`} onClick={() => setPx(s)}>{s}px</button>)}
					<span style={{ opacity: 0.65 }}> = {scale % 1 ? scale.toFixed(2) : scale} screen pixels per art pixel</span>
				</span>
				<span>Facing:{" "}
					{Object.keys(FACE).map((f) => <button key={f} className={`btn ${f === facing ? "btn-gold" : "btn-ghost"}`} onClick={() => setFacing(f)}>{f}</button>)}
				</span>
			</div>
			<div style={{ display: "grid", gap: 16, gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 560px), 1fr))" }}>
				{RIFTS.map((r) => (
					<section key={r}>
						<h2 style={{ fontSize: "1rem", margin: "0 0 6px" }}>{RIFT_NAMES[r]}</h2>
						<Scene rift={r} px={px} facing={facing} tick={tick} />
					</section>
				))}
			</div>
			<h2 style={{ fontSize: "1.1rem", margin: "28px 0 6px" }}>Every picture</h2>
			<p style={{ opacity: 0.75, maxWidth: 820, margin: "0 0 10px" }}>
				Drop a generated image on a row (or use Try an image) to see it in the rooms above at real size.
				The flat green background is cut out, the rest is cropped and shrunk to the row's size. It lasts until you reload.
			</p>
			<div style={{ display: "flex", gap: 18, alignItems: "center", flexWrap: "wrap", marginBottom: 10 }}>
				<label>Character height <input type="number" min={8} max={24} value={charH}
					onChange={(e) => setCharH(Math.max(8, Math.min(24, Number(e.target.value) || 20)))} style={{ width: 64, fontSize: 16 }} /> art pixels
					<span style={{ opacity: 0.65 }}> (bosses twice that)</span></label>
				<label><input type="checkbox" checked={sheet3} onChange={(e) => setSheet3(e.target.checked)} /> image shows three facings side by side (down, side, up)</label>
			</div>
			{note && <p style={{ color: "#e9c25a", margin: "0 0 10px" }}>{note}</p>}
			{Object.entries(groups).map(([name, rows]) => (
				<div key={name} style={{ marginBottom: 14 }}>
					<h3 style={{ fontSize: ".95rem", margin: "10px 0 4px", opacity: 0.85 }}>{name}</h3>
					<table style={{ borderCollapse: "collapse" }}>
						<tbody>
							{rows.map(([id, slot]) => <SlotRow key={id} id={id} slot={slot} status={statusOf(id)} onDrop={drop} onClear={clear} />)}
						</tbody>
					</table>
				</div>
			))}
		</div>
	);
}
