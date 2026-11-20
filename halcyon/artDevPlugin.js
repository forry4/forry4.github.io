/* The art gallery's "Use this", on the DEV SERVER only (vite `apply: "serve"` — a
 * build never has it): local routes that write a finished picture into the
 * repo, so taking a generated image into the game is a click, not a file chore.
 *
 *   POST /__halcyon-art/save    { items: [{ key, png, facings }], raw?, rawName? }  (base64)
 *     -> webapp/public/art/halcyon/<key>.png per item, their lines in
 *        halcyon/artManifest.js (ONE write, so a group lands whole), and the ORIGINAL
 *        image kept in halcyon/art/source/<key>/ (not committed — generated
 *        originals are big; they stay on this machine as the record).
 *   GET  /__halcyon-art/source/<key>  -> the newest original kept for that key (the
 *        style reference to attach to later prompts).
 *   POST /__halcyon-art/settings { artPx }  -> the shared density (art pixels a tile).
 *   POST /__halcyon-art/remove  { key }
 *     -> the manifest line and the finished picture go (the originals stay).
 *
 * Only keys in art.js SLOTS are accepted, and nothing is written outside those
 * three places. */
import { writeFileSync, readFileSync, mkdirSync, rmSync, existsSync, readdirSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const PUBLIC = path.join(here, "..", "webapp", "public", "art", "halcyon");
const SOURCE = path.join(here, "art", "source");
const MANIFEST_FILE = path.join(here, "artManifest.js");

export function readManifest(text = readFileSync(MANIFEST_FILE, "utf8")) {
	const m = text.match(/export const ART = (\{[\s\S]*\});\s*$/);
	if (!m) throw new Error("artManifest.js is not in its expected shape");
	const art = JSON.parse(m[1]);
	art.pictures ||= {};
	return art;
}
export function manifestText(art) {
	const pictures = Object.fromEntries(Object.keys(art.pictures).sort().map((k) => [k, art.pictures[k]]));
	return "/* The pictures that exist and the shared density (art.js explains the fields).\n" +
		" * Written by the art studio's \"Use this\" (dev server only) — keep it plain JSON. */\n" +
		`export const ART = ${JSON.stringify({ artPx: art.artPx, pictures }, null, "\t")};\n`;
}

function body(req) {
	return new Promise((ok, fail) => {
		let s = "";
		req.on("data", (c) => { s += c; if (s.length > 40e6) fail(new Error("too big")); });
		req.on("end", () => { try { ok(JSON.parse(s)); } catch (e) { fail(e); } });
	});
}

export default function halcyonArtDev() {
	return {
		name: "halcyon-art-dev",
		apply: "serve",
		configureServer(server) {
			server.middlewares.use(async (req, res, next) => {
				if (!req.url.startsWith("/__halcyon-art/")) return next();
				const send = (code, obj) => { res.statusCode = code; res.setHeader("content-type", "application/json"); res.end(JSON.stringify(obj)); };
				try {
					const { SLOTS } = await server.ssrLoadModule(path.join(here, "art.js"));
					if ((req.method === "GET" || req.method === "HEAD") && req.url.startsWith("/__halcyon-art/source/")) {
						const key = decodeURIComponent(req.url.slice("/__halcyon-art/source/".length));
						const dir = path.join(SOURCE, key);
						if (!SLOTS[key] || !existsSync(dir)) return send(404, { error: "none kept" });
						const newest = readdirSync(dir).sort().pop();
						if (!newest) return send(404, { error: "none kept" });
						res.setHeader("content-disposition", `attachment; filename="${newest.replace(/^\d+-/, "")}"`);
						res.setHeader("content-type", "application/octet-stream");
						return res.end(readFileSync(path.join(dir, newest)));
					}
					if (req.method !== "POST") return next();
					const msg = await body(req), art = readManifest(), manifest = art.pictures;
					if (Number.isInteger(msg.artPx) && msg.artPx >= 8 && msg.artPx <= 64) art.artPx = msg.artPx;
					if (req.url === "/__halcyon-art/settings") { writeFileSync(MANIFEST_FILE, manifestText(art)); return send(200, { ok: true }); }
					if (req.url === "/__halcyon-art/save") {
						const items = Array.isArray(msg.items) ? msg.items : [];
						if (!items.length || items.some((it) => !SLOTS[it.key] || typeof it.png !== "string")) return send(400, { error: "bad items" });
						mkdirSync(PUBLIC, { recursive: true });
						const v = Date.now();
						for (const it of items) {
							writeFileSync(path.join(PUBLIC, `${it.key}.png`), Buffer.from(it.png, "base64"));
							if (typeof msg.raw === "string") {
								const dir = path.join(SOURCE, it.key);
								mkdirSync(dir, { recursive: true });
								const name = String(msg.rawName || "original.png").replace(/[^A-Za-z0-9._-]/g, "_").slice(-80);
								writeFileSync(path.join(dir, `${v}-${name}`), Buffer.from(msg.raw, "base64"));
							}
							manifest[it.key] = { src: `${it.key}.png`, v, ...(it.w ? { w: it.w, h: it.h } : {}), ...(it.facings > 1 ? { facings: it.facings } : {}) };
						}
						writeFileSync(MANIFEST_FILE, manifestText(art));
						return send(200, { ok: true });
					}
					if (req.url === "/__halcyon-art/remove") {
						if (!SLOTS[msg.key]) return send(400, { error: `no slot ${msg.key}` });
						delete manifest[msg.key];
						writeFileSync(MANIFEST_FILE, manifestText(art));
						const file = path.join(PUBLIC, `${msg.key}.png`);
						if (existsSync(file)) rmSync(file);
						return send(200, { ok: true });
					}
					return next();
				} catch (e) { return send(500, { error: String(e.message || e) }); }
			});
		},
	};
}
