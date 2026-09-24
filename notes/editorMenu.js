// Helpers behind the note's right-click menu: clipboard, note links, images,
// checklists and "selection -> new note". Kept out of NoteEditor.jsx so the editor
// file stays about editing.
import { DOMParser as PMDOMParser, DOMSerializer } from "@tiptap/pm/model";
import { buildPath } from "../shared/router.js";

export const MOD = typeof navigator !== "undefined" && /Mac|iPhone|iPad/.test(navigator.platform) ? "⌘" : "Ctrl+";

// ── note links ────────────────────────────────────────────────────────────────
// A link to another note is an ordinary link mark whose href is that note's own app
// URL (/notes/<id>) — so it survives copy/paste, works as a plain URL anywhere, and
// needs no new node type. It is recognised by that href, never by a class.
const NOTE_PATH = /\/notes\/([a-z0-9]{16})\/?$/;
export function noteIdOf(href) {
	try {
		const u = new URL(href, window.location.origin);
		return u.origin === window.location.origin ? (u.pathname.match(NOTE_PATH)?.[1] || null) : null;
	} catch { return null; }
}
export const noteHref = (id) => buildPath("notes", id);
export const noteLinkAttrs = (id) => ({ href: noteHref(id), class: "nt-notelink", target: null, rel: null });
export const noteLinkText = (title, id) => ({
	type: "text", text: title || "Untitled", marks: [{ type: "link", attrs: noteLinkAttrs(id) }],
});
export const absoluteUrl = (href) => new URL(href, window.location.origin).href;

// The link under the cursor: its href and whether it points at a note.
export function linkAt(editor) {
	const attrs = editor.getAttributes("link");
	if (!attrs?.href) return null;
	return { href: attrs.href, noteId: noteIdOf(attrs.href) };
}

// ── clipboard ─────────────────────────────────────────────────────────────────
// Cut/Copy go through the browser's own copy (so ProseMirror serialises the
// selection exactly as Ctrl+C would). Paste has to READ the clipboard, which a page
// may only do with permission: Chrome/Edge ask once, Firefox mostly refuses — then we
// say to use the keyboard rather than fail silently.
export function cutCopy(editor, kind, notify) {
	editor.view.focus();
	let ok = false;
	try { ok = document.execCommand(kind); } catch { ok = false; }
	if (!ok) notify(`Your browser blocked that — use ${MOD}${kind === "cut" ? "X" : "C"} instead.`);
}

export async function pasteFromClipboard(editor, { plain, insertImages, notify }) {
	const { view } = editor;
	view.focus();
	try {
		if (!plain && navigator.clipboard?.read) {
			for (const item of await navigator.clipboard.read()) {
				const img = item.types.find((t) => t.startsWith("image/"));
				if (img) {
					const b = await item.getType(img);
					insertImages([new File([b], `pasted.${img.split("/")[1]}`, { type: img })]);
					return;
				}
				if (item.types.includes("text/html")) { view.pasteHTML(await (await item.getType("text/html")).text()); return; }
				if (item.types.includes("text/plain")) { view.pasteText(await (await item.getType("text/plain")).text()); return; }
			}
			return;
		}
		view.pasteText(await navigator.clipboard.readText());
	} catch {
		notify(`Your browser didn't allow reading the clipboard — press ${MOD}V to paste instead.`);
	}
}

export async function copyText(text, notify, done = "Copied") {
	try { await navigator.clipboard.writeText(text); notify(done); }
	catch { notify("Your browser blocked copying to the clipboard."); }
}

// ── images ────────────────────────────────────────────────────────────────────
// The clipboard takes PNG only (Chrome refuses WebP/JPEG image items), so a copy
// re-encodes. `src` is the image's blob: URL, already loaded for display.
export async function copyImage(src, notify) {
	try {
		const blob = await (await fetch(src)).blob();
		const bmp = await createImageBitmap(blob);
		const c = document.createElement("canvas");
		c.width = bmp.width; c.height = bmp.height;
		c.getContext("2d").drawImage(bmp, 0, 0);
		const png = await new Promise((r) => c.toBlob(r, "image/png"));
		await navigator.clipboard.write([new ClipboardItem({ "image/png": png })]);
		notify("Image copied");
	} catch {
		notify("Your browser couldn't copy the image — use Download image instead.");
	}
}

export async function downloadImage(src, name) {
	const blob = await (await fetch(src)).blob();
	const ext = (blob.type.split("/")[1] || "png").replace("jpeg", "jpg");
	const url = URL.createObjectURL(blob);
	const a = document.createElement("a");
	a.href = url;
	a.download = `${(name || "image").replace(/[\\/:*?"<>|]+/g, " ").trim() || "image"}.${ext}`;
	document.body.appendChild(a);
	a.click();
	a.remove();
	setTimeout(() => URL.revokeObjectURL(url), 5000);
}

// ── checklists ────────────────────────────────────────────────────────────────
// Check or uncheck every item of the checklist the cursor is in (nested ones too).
export function setAllChecked(editor, checked) {
	const { state, view } = editor;
	const { $from } = state.selection;
	for (let d = $from.depth; d > 0; d--) {
		const list = $from.node(d);
		if (list.type.name !== "taskList") continue;
		const start = $from.before(d) + 1;
		const tr = state.tr;
		list.descendants((n, p) => {
			if (n.type.name === "taskItem" && n.attrs.checked !== checked) tr.setNodeMarkup(start + p, undefined, { ...n.attrs, checked });
		});
		if (tr.docChanged) view.dispatch(tr);
		return;
	}
}

// ── selection -> its own document ─────────────────────────────────────────────
// Round-trips the selection through the schema's own HTML serialiser and parser, so
// whatever the selection cut through (half a list, a caption'd image) comes back as a
// VALID standalone document rather than a fragment the server would store verbatim.
export function selectionAsDoc(editor) {
	const { state } = editor;
	const div = document.createElement("div");
	div.appendChild(DOMSerializer.fromSchema(state.schema).serializeFragment(state.selection.content().content));
	return PMDOMParser.fromSchema(state.schema).parse(div).toJSON();
}

export function selectionTitle(editor) {
	const { from, to } = editor.state.selection;
	const first = editor.state.doc.textBetween(from, to, "\n", " ").split("\n").map((s) => s.trim()).find(Boolean) || "";
	return first.length > 80 ? `${first.slice(0, 77).trimEnd()}…` : first || "New note";
}
