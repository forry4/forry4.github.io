import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useEditor, useEditorState, EditorContent, NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { Extension, Node, mergeAttributes } from "@tiptap/core";
import { NodeSelection, Plugin, Selection, TextSelection } from "@tiptap/pm/state";
import StarterKit from "@tiptap/starter-kit";
import { TaskList, TaskItem } from "@tiptap/extension-list";
import { Placeholder } from "@tiptap/extensions";
import { TextAlign } from "@tiptap/extension-text-align";
import { Highlight } from "@tiptap/extension-highlight";

import { I } from "./icons.jsx";
import { FindInNote, findKey } from "./find.js";
import { ContextMenu, NotePicker } from "./menu.jsx";
import {
	MOD, noteIdOf, noteLinkAttrs, noteLinkText, absoluteUrl, linkAt, cutCopy, pasteFromClipboard,
	copyText, copyImage, downloadImage, setAllChecked, selectionAsDoc, selectionTitle,
} from "./editorMenu.js";
import {
	compressImage, blobToBase64, imageFilesFrom, imageUrl, primeImage,
	pendingUploads, newUploadKey,
} from "./images.js";

// ─── the image node ────────────────────────────────────────────────────────────
// A block atom that REFERENCES an uploaded image by id; the bytes never live in the
// document, so a save is text-sized no matter how many screenshots a note holds.
// Every attribute round-trips through data-* so copy/paste between notes (which goes
// through ProseMirror's HTML clipboard) keeps the image, its size and its caption.
const dataAttr = (name, key, fallback) => ({
	default: fallback,
	parseHTML: (el) => {
		const v = el.getAttribute(`data-${name}`);
		return v == null ? fallback : (typeof fallback === "number" ? Number(v) || 0 : v);
	},
	renderHTML: (attrs) => (attrs[key] == null || attrs[key] === "" ? {} : { [`data-${name}`]: attrs[key] }),
});

const WIDTHS = [["small", "S", "Small"], ["half", "M", "Medium"], ["full", "L", "Full width"]];

function ImageView({ node, updateAttributes, deleteNode, selected, extension }) {
	const { imageId, uploadKey, width, align, caption, w, h } = node.attrs;
	const api = extension.options.api;
	const pending = !imageId && uploadKey ? pendingUploads.get(uploadKey) : null;
	const [src, setSrc] = useState(pending?.previewUrl || null);
	const [failed, setFailed] = useState(false);
	const [open, setOpen] = useState(false);
	const [capOpen, setCapOpen] = useState(false);
	const frameRef = useRef(null);
	const capRef = useRef(null);
	// The right-click menu drives these by DOM event on the frame: the menu lives in the
	// editor, the lightbox and the caption field live here.
	useEffect(() => {
		const el = frameRef.current;
		if (!el) return undefined;
		const lightbox = () => setOpen(true);
		const cap = () => { setCapOpen(true); setTimeout(() => capRef.current?.focus(), 0); };
		el.addEventListener("nt-lightbox", lightbox);
		el.addEventListener("nt-caption", cap);
		return () => { el.removeEventListener("nt-lightbox", lightbox); el.removeEventListener("nt-caption", cap); };
	}, []);

	useEffect(() => {
		let live = true;
		if (imageId) {
			setFailed(false);
			imageUrl(api, imageId).then((u) => live && setSrc(u), () => live && setFailed(true));
		} else if (pending) setSrc(pending.previewUrl);
		return () => { live = false; };
	}, [imageId, uploadKey]);   // eslint-disable-line react-hooks/exhaustive-deps

	const label = failed ? "Image unavailable" : imageId ? "Loading…" : pending ? "" : "Upload failed";
	return (
		<NodeViewWrapper className={`nt-img nt-img-${width} nt-img-align-${align || "left"}${selected ? " is-selected" : ""}`}>
			<div ref={frameRef} className="nt-img-frame" data-drag-handle="" draggable="true"
				style={w && h ? { aspectRatio: `${w} / ${h}` } : undefined}>
				{src && !failed
					? <img src={src} alt={caption || "Screenshot"} draggable={false} onDoubleClick={() => setOpen(true)} />
					: <div className="nt-img-ph">{label}</div>}
				{pending && <div className="nt-img-busy">Uploading…</div>}
			</div>
			{/* The controls sit UNDER the image, never on it: a screenshot is kept for the
			    text in it, and an overlay on its top edge also slid under the sticky
			    toolbar the moment a tall image was scrolled. */}
			{(selected || caption || capOpen) && (
				<div className="nt-img-bar">
					<input ref={capRef} className="nt-img-cap" value={caption || ""} placeholder="Add a caption…"
						aria-label="Image caption" maxLength={300} onBlur={() => setCapOpen(false)}
						onChange={(e) => updateAttributes({ caption: e.target.value })} />
					{selected && (
						<div className="nt-img-tools" contentEditable={false}>
							{WIDTHS.map(([id, short, name]) => (
								<button key={id} type="button" className={width === id ? "on" : ""} title={name} aria-label={name}
									onClick={() => updateAttributes({ width: id })}>{short}</button>
							))}
							{src && !failed && (
								<button type="button" title="Open full size" aria-label="Open full size" onClick={() => setOpen(true)}>{I.expand}</button>
							)}
							<button type="button" className="nt-img-del" title="Remove image" aria-label="Remove image" onClick={() => deleteNode()}>{I.trash}</button>
						</div>
					)}
				</div>
			)}
			{open && src && createPortal(
				<div className="nt-lightbox" role="dialog" aria-label={caption || "Screenshot"} onClick={() => setOpen(false)}
					onKeyDown={(e) => e.key === "Escape" && setOpen(false)} tabIndex={-1} ref={(el) => el?.focus()}>
					<img src={src} alt={caption || "Screenshot"} />
					{caption && <div className="nt-lightbox-cap">{caption}</div>}
					<button type="button" className="nt-lightbox-x" aria-label="Close">{I.close}</button>
				</div>,
				document.body,
			)}
		</NodeViewWrapper>
	);
}

const NoteImage = Node.create({
	name: "noteImage",
	group: "block",
	atom: true,
	draggable: true,
	selectable: true,
	addOptions() { return { api: null }; },
	addAttributes() {
		return {
			imageId: dataAttr("image-id", "imageId", null),
			uploadKey: { default: null, rendered: false, parseHTML: () => null },
			width: dataAttr("width", "width", "full"),
			align: dataAttr("align", "align", "left"),
			caption: dataAttr("caption", "caption", ""),
			w: dataAttr("w", "w", 0),
			h: dataAttr("h", "h", 0),
		};
	},
	parseHTML() { return [{ tag: "figure[data-note-image]" }]; },
	renderHTML({ HTMLAttributes }) { return ["figure", mergeAttributes(HTMLAttributes, { "data-note-image": "" })]; },
	addNodeView() { return ReactNodeViewRenderer(ImageView); },
});

// A node still uploading (or whose upload failed) has no id and is never persisted:
// on reload it would be a hole with nothing behind it.
function stripPending(node) {
	if (!node || !Array.isArray(node.content)) return node;
	return {
		...node,
		content: node.content
			.filter((c) => !(c.type === "noteImage" && !c.attrs?.imageId))
			.map((c) => {
				const out = stripPending(c);
				if (out.type === "noteImage" && out.attrs) {
					const { uploadKey, ...attrs } = out.attrs;   // eslint-disable-line no-unused-vars
					return { ...out, attrs };
				}
				return out;
			}),
	};
}

// ─── indent ───────────────────────────────────────────────────────────────────
// Tab / Shift-Tab. Inside a list they nest / un-nest the item; anywhere else they
// step a paragraph or heading in / out (an `indent` attribute, drawn as a margin).
// Tab is ALWAYS consumed inside the note: left to the browser it moves keyboard
// focus out of the editor, which reads as "Tab does nothing" — including on a
// list's first item, which has nothing above it to nest under.
const INDENT_TYPES = ["paragraph", "heading"];
const MAX_INDENT = 8;

const Indent = Extension.create({
	name: "indent",
	// above the list items' own Tab bindings, so one handler decides for both cases
	priority: 1000,
	addGlobalAttributes() {
		return [{
			types: INDENT_TYPES,
			attributes: {
				indent: {
					default: 0,
					parseHTML: (el) => Math.max(0, Math.min(MAX_INDENT, Number(el.getAttribute("data-indent")) || 0)),
					renderHTML: (a) => (a.indent ? { "data-indent": a.indent, style: `margin-left:${a.indent * 1.6}em` } : {}),
				},
			},
		}];
	},
	addCommands() {
		// tiptap dispatches `tr` itself when a command returns true — never dispatch here.
		const step = (delta) => () => ({ editor, tr, commands }) => {
			const listItem = editor.isActive("taskItem") ? "taskItem" : editor.isActive("listItem") ? "listItem" : null;
			if (listItem) {
				if (delta > 0) commands.sinkListItem(listItem);
				else commands.liftListItem(listItem);
				return true;
			}
			if (editor.isActive("codeBlock")) {
				if (delta > 0) tr.insertText("  ");
				return true;
			}
			const { from, to } = tr.selection;
			tr.doc.nodesBetween(from, to, (node, pos) => {
				if (!INDENT_TYPES.includes(node.type.name)) return true;
				const next = Math.max(0, Math.min(MAX_INDENT, (node.attrs.indent || 0) + delta));
				if (next !== (node.attrs.indent || 0)) tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: next });
				return false;
			});
			return true;
		};
		return { indent: step(1), outdent: step(-1) };
	},
	// A paragraph's indent means nothing inside a list — lists nest instead (Tab) — but
	// it survived the wrap: a line indented first and then bulleted kept its margin, so
	// its text sat a tab-stop away from its bullet. Cleared whenever a list holds one.
	addProseMirrorPlugins() {
		return [new Plugin({
			appendTransaction(trs, _old, state) {
				if (!trs.some((t) => t.docChanged)) return null;
				let tr = null;
				state.doc.descendants((node, pos, parent) => {
					if (INDENT_TYPES.includes(node.type.name) && node.attrs.indent
						&& parent && (parent.type.name === "listItem" || parent.type.name === "taskItem")) {
						tr = tr || state.tr;
						tr.setNodeMarkup(pos, undefined, { ...node.attrs, indent: 0 });
					}
					return true;
				});
				return tr;
			},
		})];
	},
	addKeyboardShortcuts() {
		return {
			Tab: () => this.editor.commands.indent(),
			"Shift-Tab": () => this.editor.commands.outdent(),
		};
	},
});

// ─── find in note ─────────────────────────────────────────────────────────────
// Select match `i` and scroll it to a third of the way down the note — BELOW the
// sticky toolbar + find bar, which ProseMirror's own scrollIntoView does not know
// about (it put a match exactly under the bars, i.e. out of sight).
function reveal(editor, i) {
	const { state, view } = editor;
	const m = findKey.getState(state).matches[i];
	if (!m) return;
	const sel = m.node ? NodeSelection.create(state.doc, m.from) : TextSelection.create(state.doc, m.from, m.to);
	view.dispatch(state.tr.setSelection(sel).setMeta(findKey, { index: i }));
	const scroller = view.dom.closest(".nt-main");
	const el = m.node ? view.nodeDOM(m.from) : null;
	const rect = el?.getBoundingClientRect ? el.getBoundingClientRect() : view.coordsAtPos(m.from);
	if (!scroller || !rect) return;
	const box = scroller.getBoundingClientRect();
	const bars = scroller.querySelector(".nt-bars")?.getBoundingClientRect().height || 0;
	const top = box.top + bars;
	if (rect.top < top + 12 || rect.bottom > box.bottom - 12) {
		scroller.scrollTop += rect.top - (top + (box.height - bars) / 3);
	}
}

function FindBar({ editor, text, setText, onClose, inputRef }) {
	const st = useEditorState({
		editor,
		selector: ({ editor: e }) => {
			const f = findKey.getState(e.state);
			return { count: f.matches.length, index: f.index };
		},
	});
	const step = (d) => { if (st.count) reveal(editor, (st.index + d + st.count) % st.count); };
	return (
		<div className="nt-findbar" role="search">
			<span className="nt-ic">{I.search}</span>
			<input ref={inputRef} className="nt-find-in" value={text} placeholder="Find in this note"
				aria-label="Find in this note" enterKeyHint="search" autoComplete="off" spellCheck={false}
				onChange={(e) => setText(e.target.value)}
				onKeyDown={(e) => {
					if (e.key === "Enter") { e.preventDefault(); step(e.shiftKey ? -1 : 1); }
					if (e.key === "Escape") { e.preventDefault(); onClose(); }
				}} />
			<span className="nt-find-count" aria-live="polite">
				{text ? (st.count ? `${st.index + 1} of ${st.count}` : "No matches") : ""}
			</span>
			<button type="button" className="nt-tb" aria-label="Previous match" title="Previous (Shift+Enter)"
				disabled={!st.count} onClick={() => step(-1)}>{I.up}</button>
			<button type="button" className="nt-tb" aria-label="Next match" title="Next (Enter)"
				disabled={!st.count} onClick={() => step(1)}>{I.down}</button>
			<button type="button" className="nt-tb" aria-label="Close find" title="Close (Esc)" onClick={onClose}>{I.close}</button>
		</div>
	);
}

// ─── toolbar ──────────────────────────────────────────────────────────────────
// onMouseDown + preventDefault keeps the editor's selection while a button is pressed.
// (A keyboard user's Enter/Space fires click, not mousedown, so onClick runs the same.)
function B({ on, label, onDown, disabled, children, cls = "" }) {
	return (
		<button type="button" className={`nt-tb ${on ? "on" : ""} ${cls}`} aria-label={label} title={label}
			aria-pressed={on === undefined ? undefined : !!on} disabled={disabled}
			onMouseDown={onDown} onClick={(e) => { if (e.detail === 0) onDown(e); }}>{children}</button>
	);
}

function Toolbar({ editor, onPickImages, onFind, findOpen, fileRef }) {
	const s = useEditorState({
		editor,
		selector: ({ editor: e }) => ({
			h1: e.isActive("heading", { level: 1 }),
			h2: e.isActive("heading", { level: 2 }),
			bold: e.isActive("bold"),
			italic: e.isActive("italic"),
			strike: e.isActive("strike"),
			bullet: e.isActive("bulletList"),
			ordered: e.isActive("orderedList"),
			task: e.isActive("taskList"),
			quote: e.isActive("blockquote"),
			// With an image selected the align buttons align the IMAGE; otherwise the text.
			align: e.state.selection instanceof NodeSelection && e.state.selection.node.type.name === "noteImage"
				? (e.state.selection.node.attrs.align || "left")
				: (["center", "right"].find((a) => e.isActive({ textAlign: a })) || "left"),
			link: e.isActive("link"),
			canUndo: e.can().undo(),
			canRedo: e.can().redo(),
		}),
	});
	const align = (a) => (ev) => {
		ev.preventDefault();
		const sel = editor.state.selection;
		if (sel instanceof NodeSelection && sel.node.type.name === "noteImage") {
			editor.chain().focus().updateAttributes("noteImage", { align: a }).run();
		} else {
			editor.chain().focus().setTextAlign(a).run();
		}
	};
	const run = (fn) => (ev) => { ev.preventDefault(); fn(editor.chain().focus()).run(); };
	const link = (ev) => {
		ev.preventDefault();
		if (s.link) { editor.chain().focus().extendMarkRange("link").unsetLink().run(); return; }
		const raw = window.prompt("Link to (URL):");
		if (!raw) return;
		const href = /^[a-z][a-z0-9+.-]*:/i.test(raw.trim()) ? raw.trim() : `https://${raw.trim()}`;
		if (editor.state.selection.empty) {
			editor.chain().focus().insertContent({ type: "text", text: raw.trim(), marks: [{ type: "link", attrs: { href } }] }).run();
		} else {
			editor.chain().focus().extendMarkRange("link").setLink({ href }).run();
		}
	};
	return (
		<div className="nt-toolbar" role="toolbar" aria-label="Formatting">
			{/* FIRST, and labelled, because on a phone the toolbar scrolls sideways and
			    the icon-only button at its far end was simply off-screen — the one
			    control a phone user most needs was the one they could not find. It
			    opens the picker on CLICK (a tap's release), which iOS reliably treats
			    as a user gesture; mousedown only keeps the editor's selection. */}
			<div className="nt-tb-group">
				<button type="button" className="nt-tb nt-tb-add" aria-label="Add image" title="Add image"
					onMouseDown={(e) => e.preventDefault()} onClick={() => fileRef.current?.click()}>
					{I.image}<span>Image</span>
				</button>
				<input ref={fileRef} type="file" accept="image/*" multiple hidden
					onChange={(e) => { const f = Array.from(e.target.files || []); e.target.value = ""; if (f.length) onPickImages(f); }} />
				<button type="button" className={`nt-tb ${findOpen ? "on" : ""}`} aria-label="Find in note" title="Find in note (Ctrl+F)"
					aria-pressed={findOpen} onMouseDown={(e) => e.preventDefault()} onClick={onFind}>{I.search}</button>
			</div>
			<div className="nt-tb-group">
				<B label="Heading" on={s.h1} onDown={run((c) => c.toggleHeading({ level: 1 }))} cls="nt-tb-txt">H1</B>
				<B label="Subheading" on={s.h2} onDown={run((c) => c.toggleHeading({ level: 2 }))} cls="nt-tb-txt">H2</B>
			</div>
			<div className="nt-tb-group">
				<B label="Bold" on={s.bold} onDown={run((c) => c.toggleBold())} cls="nt-tb-txt nt-tb-b">B</B>
				<B label="Italic" on={s.italic} onDown={run((c) => c.toggleItalic())} cls="nt-tb-txt nt-tb-i">I</B>
				<B label="Strikethrough" on={s.strike} onDown={run((c) => c.toggleStrike())} cls="nt-tb-txt nt-tb-s">S</B>
				<B label="Link" on={s.link} onDown={link}>{I.link}</B>
			</div>
			<div className="nt-tb-group">
				<B label="Bulleted list" on={s.bullet} onDown={run((c) => c.toggleBulletList())}>{I.bullet}</B>
				<B label="Numbered list" on={s.ordered} onDown={run((c) => c.toggleOrderedList())}>{I.ordered}</B>
				<B label="Checklist" on={s.task} onDown={run((c) => c.toggleTaskList())}>{I.check}</B>
				<B label="Quote" on={s.quote} onDown={run((c) => c.toggleBlockquote())}>{I.quote}</B>
				<B label="Divider" onDown={run((c) => c.setHorizontalRule())}>{I.rule}</B>
			</div>
			<div className="nt-tb-group">
				<B label="Align left" on={s.align === "left"} onDown={align("left")}>{I.alignLeft}</B>
				<B label="Align center" on={s.align === "center"} onDown={align("center")}>{I.alignCenter}</B>
				<B label="Align right" on={s.align === "right"} onDown={align("right")}>{I.alignRight}</B>
			</div>
			<div className="nt-tb-group">
				{/* Tab / Shift-Tab do this on a keyboard; a phone has no Tab key. */}
				<B label="Indent (Tab)" onDown={run((c) => c.indent())}>{I.indent}</B>
				<B label="Outdent (Shift+Tab)" onDown={run((c) => c.outdent())}>{I.outdent}</B>
			</div>
			<div className="nt-tb-group">
				<B label="Undo" disabled={!s.canUndo} onDown={run((c) => c.undo())}>{I.undo}</B>
				<B label="Redo" disabled={!s.canRedo} onDown={run((c) => c.redo())}>{I.redo}</B>
			</div>
		</div>
	);
}

const STATUS_TEXT = {
	saved: "Saved", dirty: "Edited", saving: "Saving…", offline: "Offline — retrying",
	conflict: "Not saved", error: "Not saved", readonly: "In the Trash",
};

function SaveStatus({ status }) {
	return <span className={`nt-status nt-status-${status}`} role="status" aria-live="polite">{STATUS_TEXT[status] || ""}</span>;
}

// ─── the editor ───────────────────────────────────────────────────────────────
const SAVE_DELAY = 1000;
const TOUCH = typeof window !== "undefined" && window.matchMedia?.("(hover: none) and (pointer: coarse)").matches;
const KEEPALIVE_MAX = 60_000;   // fetch keepalive bodies are capped at 64KB

function LoadedEditor({ api, initial, onSaved, onGone, onReload, onRestore, notify, statusSlot, focusTitle, onTitleFocused, findRequest, nav }) {
	const noteId = initial.id;
	const trashed = initial.deleted_at != null;
	const [title, setTitle] = useState(initial.title || "");
	const [status, setStatusState] = useState(trashed ? "readonly" : "saved");
	const [conflict, setConflict] = useState(null);

	const statusRef = useRef(status);
	const setStatus = (s) => { statusRef.current = s; if (mounted.current) setStatusState(s); };
	const mounted = useRef(true);
	const revRef = useRef(initial.rev || 0);
	const editSeq = useRef(0);
	const savedSeq = useRef(0);
	const saving = useRef(false);
	const again = useRef(false);
	const timer = useRef(null);
	const retry = useRef(0);
	const latest = useRef({ title: initial.title || "", doc: initial.doc });
	const editorRef = useRef(null);
	const titleRef = useRef(null);
	useEffect(() => {
		if (!focusTitle) return;
		titleRef.current?.focus();
		titleRef.current?.select();   // "Rename" lands here with the old title ready to type over
		onTitleFocused?.();
	}, []);   // eslint-disable-line react-hooks/exhaustive-deps -- once, at mount
	const cb = useRef(null);
	cb.current = { onSaved, onGone, notify, nav };
	const fileRef = useRef(null);
	const [ctxMenu, setCtxMenu] = useState(null);   // { x, y, items }
	const [picker, setPicker] = useState(null);     // { title, onPick, onCreate }
	const pointerType = useRef("mouse");

	const save = useCallback(async ({ keepalive = false } = {}) => {
		clearTimeout(timer.current);
		if (statusRef.current === "conflict" || statusRef.current === "readonly" || statusRef.current === "gone") return;
		if (saving.current) { again.current = true; return; }
		const seq = editSeq.current;
		if (seq === savedSeq.current) return;
		const body = { title: latest.current.title, doc: stripPending(latest.current.doc), base_rev: revRef.current };
		const ka = keepalive && JSON.stringify(body).length < KEEPALIVE_MAX;
		saving.current = true;
		setStatus("saving");
		try {
			const n = await api.saveNote(noteId, body, { keepalive: ka });
			revRef.current = n.rev;
			savedSeq.current = seq;
			retry.current = 0;
			cb.current.onSaved(n);
			setStatus(editSeq.current > seq ? "dirty" : "saved");
		} catch (e) {
			if (e.status === 409) {
				setStatus("conflict");
				if (mounted.current) setConflict(e.data?.note || null);
			} else if (e.status === 404) {
				setStatus("gone");
				cb.current.onGone?.();
			} else if (e.status === undefined || e.status >= 500) {
				setStatus("offline");
				const wait = Math.min(8000, 2000 * 2 ** retry.current++);
				if (mounted.current) timer.current = setTimeout(() => save(), wait);
			} else {
				setStatus("error");
				cb.current.notify(`Couldn't save: ${e.message}`);
			}
		} finally {
			saving.current = false;
			if ((again.current || editSeq.current > savedSeq.current) && statusRef.current === "dirty") {
				again.current = false;
				if (mounted.current) timer.current = setTimeout(() => save(), SAVE_DELAY);
			}
		}
	}, [api, noteId]);   // eslint-disable-line react-hooks/exhaustive-deps

	const markDirty = () => {
		editSeq.current += 1;
		const s = statusRef.current;
		if (s === "conflict" || s === "readonly" || s === "gone") return;
		if (s !== "saving" && s !== "offline") setStatus("dirty");
		if (s === "saving") { again.current = true; return; }
		if (s === "offline") return;   // the retry loop will pick the edit up
		clearTimeout(timer.current);
		timer.current = setTimeout(() => save(), SAVE_DELAY);
	};

	// ── images ──
	const findByKey = (key) => {
		let hit = null;
		editorRef.current?.state.doc.descendants((n, pos) => {
			if (hit == null && n.type.name === "noteImage" && n.attrs.uploadKey === key) hit = { node: n, pos };
			return hit == null;
		});
		return hit;
	};
	const upload = async (file, key) => {
		try {
			const { blob, mime, width, height } = await compressImage(file);
			const data = await blobToBase64(blob);
			const img = await api.uploadImage({ note_id: noteId, mime, data, width, height });
			primeImage(img.id, blob);
			const ed = editorRef.current;
			const hit = findByKey(key);
			if (ed && !ed.isDestroyed && hit) {
				ed.view.dispatch(ed.state.tr.setNodeMarkup(hit.pos, undefined,
					{ ...hit.node.attrs, imageId: img.id, uploadKey: null, w: width, h: height }));
			}
		} catch (e) {
			cb.current.notify(`Couldn't add the image: ${e.message === "offline" ? "the server is unreachable" : e.message}`);
			const ed = editorRef.current;
			const hit = findByKey(key);
			if (ed && !ed.isDestroyed && hit) ed.view.dispatch(ed.state.tr.delete(hit.pos, hit.pos + hit.node.nodeSize));
		} finally {
			const p = pendingUploads.get(key);
			pendingUploads.delete(key);
			if (p) setTimeout(() => URL.revokeObjectURL(p.previewUrl), 15_000);
		}
	};
	const insertImages = (files, pos = null) => {
		const ed = editorRef.current;
		if (!ed || !files.length) return;
		const nodes = files.map((f) => {
			const key = newUploadKey();
			pendingUploads.set(key, { previewUrl: URL.createObjectURL(f) });
			return { key, file: f, json: { type: "noteImage", attrs: { uploadKey: key, width: "full" } } };
		});
		const content = nodes.map((n) => n.json);
		// With an image SELECTED, "insert at the selection" means replace it — so a new
		// screenshot goes after the selected one instead of silently deleting it.
		if (pos == null && ed.state.selection instanceof NodeSelection) pos = ed.state.selection.to;
		if (pos == null) ed.chain().focus().insertContent(content).run();
		else ed.chain().focus().insertContentAt(pos, content).run();
		nodes.forEach((n) => upload(n.file, n.key));
	};
	const insertRef = useRef(insertImages);
	insertRef.current = insertImages;

	const editor = useEditor({
		editable: !trashed,
		extensions: [
			StarterKit.configure({
				heading: { levels: [1, 2, 3] },
				link: { openOnClick: false, autolink: true, linkOnPaste: true, defaultProtocol: "https",
					HTMLAttributes: { rel: "noopener noreferrer nofollow", target: "_blank" } },
			}),
			TaskList,
			TaskItem.configure({ nested: true }),
			// A phone has no paste-a-screenshot or drag-a-file, so it is told about the button.
			Placeholder.configure({ placeholder: TOUCH
				? "Start writing… tap Image to add a photo or screenshot."
				: "Start writing… paste or drop screenshots anywhere." }),
			NoteImage.configure({ api }),
			Indent,
			FindInNote,
			Highlight,
			TextAlign.configure({ types: ["heading", "paragraph"], alignments: ["left", "center", "right"] }),
		],
		content: initial.doc || "",
		editorProps: {
			attributes: { class: "nt-prose", spellcheck: "true", "aria-label": "Note" },
			// A link to another NOTE opens it on a plain click (it is navigation, like a
			// wiki link); a web link opens with Ctrl/Cmd+click, so a plain click can still
			// put the cursor inside it to edit.
			handleClick: (view, pos, event) => {
				// ProseMirror reports EVERY button here — a right-click on a note link used
				// to open the note instead of the link's menu.
				if (event.button !== 0) return false;
				const a = event.target?.closest?.("a[href]");
				if (!a || !view.dom.contains(a)) return false;
				const id = noteIdOf(a.getAttribute("href"));
				if (id) { cb.current.nav?.openNote(id); return true; }
				if (event.ctrlKey || event.metaKey) { window.open(a.href, "_blank", "noopener,noreferrer"); return true; }
				return false;
			},
			handlePaste: (view, event) => {
				const files = imageFilesFrom(event.clipboardData);
				if (!files.length) return false;
				event.preventDefault();
				insertRef.current(files);
				return true;
			},
			handleDrop: (view, event, slice, moved) => {
				if (moved) return false;   // an image being dragged WITHIN the note
				const files = imageFilesFrom(event.dataTransfer);
				if (!files.length) return false;
				event.preventDefault();
				// Land between BLOCKS, never mid-sentence: a drop onto a line of text puts the
				// image after that paragraph (or before it, when dropped on its very start).
				// Inserting at the raw point split "The clock…" into "T" | image | "he clock…".
				const at = view.posAtCoords({ left: event.clientX, top: event.clientY });
				let pos = null;
				if (at) {
					const $p = view.state.doc.resolve(at.pos);
					pos = $p.parent.isTextblock && $p.depth > 0
						? ($p.parentOffset === 0 ? $p.before() : $p.after())
						: at.pos;
				}
				insertRef.current(files, pos);
				return true;
			},
		},
		onUpdate: ({ editor: e, transaction }) => {
			if (!transaction.docChanged) return;
			latest.current.doc = e.getJSON();
			markDirty();
		},
	});
	editorRef.current = editor;

	// flush on hide / close / note switch
	useEffect(() => {
		mounted.current = true;
		const onHide = () => { if (document.visibilityState === "hidden") save({ keepalive: true }); };
		const onUnload = () => save({ keepalive: true });
		document.addEventListener("visibilitychange", onHide);
		window.addEventListener("pagehide", onUnload);
		return () => {
			document.removeEventListener("visibilitychange", onHide);
			window.removeEventListener("pagehide", onUnload);
			mounted.current = false;
			clearTimeout(timer.current);
			save({ keepalive: true });   // switching notes: the last edits still land
		};
	}, [save]);

	// ── find in note ──
	const [findOpen, setFindOpen] = useState(false);
	const [findText, setFindText] = useState("");
	const findInput = useRef(null);
	const openFind = (prefill, focus = true) => {
		setFindOpen(true);
		if (prefill != null) setFindText(prefill);
		if (focus) setTimeout(() => { findInput.current?.focus(); findInput.current?.select(); }, 0);
	};
	const closeFind = () => {
		setFindOpen(false);
		const ed = editorRef.current;
		if (ed && !ed.isDestroyed) ed.view.focus();   // the cursor is left on the match you stopped at
	};
	// The query lives in the editor's plugin state; this keeps it in step with the bar
	// and jumps to the first match as you type.
	useEffect(() => {
		const ed = editorRef.current;
		if (!ed || ed.isDestroyed) return;
		const q = findOpen ? findText : "";
		ed.view.dispatch(ed.state.tr.setMeta(findKey, { query: q }));
		if (q) reveal(ed, 0);
	}, [findOpen, findText, editor]);
	// Ctrl/Cmd+F opens THIS find (pre-filled with the selection) rather than the
	// browser's, which cannot step through a note or see image captions.
	useEffect(() => {
		const onKey = (e) => {
			if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== "f") return;
			e.preventDefault();
			const ed = editorRef.current;
			const { from, to } = ed?.state.selection || {};
			const sel = ed && to > from ? ed.state.doc.textBetween(from, to, " ") : "";
			openFind(sel && sel.length <= 100 && !sel.includes("\n") ? sel : null);
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, []);   // eslint-disable-line react-hooks/exhaustive-deps
	// Opened from a sidebar search result: show that query already highlighted — without
	// focusing the box, which on a phone would throw the keyboard over the match.
	useEffect(() => {
		if (findRequest?.q && editor) openFind(findRequest.q, false);
	}, [findRequest?.n, editor]);   // eslint-disable-line react-hooks/exhaustive-deps

	// ── right-click menu ──
	const note = (msg) => cb.current.notify(msg);
	const chain = () => editorRef.current.chain().focus();
	const pickNote = (title, onPick) => setPicker({
		title,
		onPick: (n) => { setPicker(null); onPick(n.id, n.title); },
		onCreate: async (t) => {
			setPicker(null);
			try {
				const n = await api.createNote(cb.current.nav?.folderOf?.() ?? initial.folder_id, t);
				cb.current.nav?.noteCreated?.(n);
				onPick(n.id, n.title || t);
			} catch (e) { note(`Couldn't create the note: ${e.message}`); }
		},
	});
	const toNewNote = async (move) => {
		const ed = editorRef.current;
		const { from, to } = ed.state.selection;
		const doc = stripPending(selectionAsDoc(ed));
		const title = selectionTitle(ed);
		try {
			const created = await api.createNote(cb.current.nav?.folderOf?.() ?? initial.folder_id, title);
			const saved = await api.saveNote(created.id, { title, doc, base_rev: 0 });
			cb.current.nav?.noteCreated?.(saved);
			if (move && !ed.isDestroyed) ed.chain().focus().insertContentAt({ from, to }, noteLinkText(title, created.id)).run();
			note(move ? `Moved into a new note, “${title}” (linked here).` : `Copied into a new note, “${title}”.`);
		} catch (e) { note(`Couldn't make the note: ${e.message}`); }
	};
	const openLink = (l) => {
		if (l.noteId) cb.current.nav?.openNote(l.noteId);
		else window.open(absoluteUrl(l.href), "_blank", "noopener,noreferrer");
	};
	const editLink = (l) => {
		if (l.noteId) {
			pickNote("Link to a note", (id) => chain().extendMarkRange("link").setLink(noteLinkAttrs(id)).run());
			return;
		}
		const raw = window.prompt("Link to (URL):", l.href);
		if (raw == null) return;
		if (!raw.trim()) { chain().extendMarkRange("link").unsetLink().run(); return; }
		const href = /^[a-z][a-z0-9+.-]*:/i.test(raw.trim()) ? raw.trim() : `https://${raw.trim()}`;
		chain().extendMarkRange("link").setLink({ href }).run();
	};
	const linkWeb = () => {
		const raw = window.prompt("Link to (URL):");
		if (!raw?.trim()) return;
		const href = /^[a-z][a-z0-9+.-]*:/i.test(raw.trim()) ? raw.trim() : `https://${raw.trim()}`;
		chain().setLink({ href }).run();
	};
	// Convert the WHOLE list the cursor is in (nested lists too), by rebuilding it as the
	// target type item by item. tiptap's toggles convert bullets <-> numbers whole, but
	// into or out of a checklist they rewrap only the selection (one item) — and with the
	// whole list selected, toggling to a checklist unwrapped everything and wrapped nothing.
	const LISTS = ["bulletList", "orderedList", "taskList"];
	const rebuildList = (schema, list, to) => {
		const itemType = schema.nodes[to === "taskList" ? "taskItem" : "listItem"];
		const items = [];
		list.forEach((item) => {
			const kids = [];
			item.forEach((c) => kids.push(LISTS.includes(c.type.name) ? rebuildList(schema, c, to) : c));
			items.push(itemType.create(to === "taskList" ? { checked: !!item.attrs.checked } : null, kids));
		});
		return schema.nodes[to].create(to === "orderedList" ? { start: list.attrs.start ?? 1 } : null, items);
	};
	const convertList = (ed, to) => {
		const { state } = ed;
		const { $from } = state.selection;
		for (let d = $from.depth; d > 0; d--) {
			const list = $from.node(d);
			if (!LISTS.includes(list.type.name)) continue;
			if (list.type.name === to) return;
			const at = $from.before(d);
			ed.view.dispatch(state.tr.replaceWith(at, at + list.nodeSize, rebuildList(state.schema, list, to)));
			ed.view.focus();
			return;
		}
	};
	const insertMenu = (ed) => [
		{ label: "Image…", onSelect: () => fileRef.current?.click() },
		{ label: "Link to a note…", onSelect: () => pickNote("Insert a link to a note", (id, t) => chain().insertContent([noteLinkText(t, id), { type: "text", text: " " }]).run()) },
		"-",
		{ label: "Checklist", onSelect: () => chain().toggleTaskList().run(), checked: ed.isActive("taskList") },
		{ label: "Bulleted list", onSelect: () => chain().toggleBulletList().run(), checked: ed.isActive("bulletList") },
		{ label: "Numbered list", onSelect: () => chain().toggleOrderedList().run(), checked: ed.isActive("orderedList") },
		{ label: "Divider", onSelect: () => chain().setHorizontalRule().run() },
		"-",
		{ label: "Today's date & time", onSelect: () => chain().insertContent(new Date().toLocaleString(undefined,
			{ weekday: "short", year: "numeric", month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })).run() },
	];

	const imageMenu = (ed, pos, frame) => {
		const node = ed.state.doc.nodeAt(pos);
		const src = frame.querySelector("img")?.getAttribute("src");
		const a = node.attrs;
		const set = (attrs) => ed.chain().focus().setNodeSelection(pos).updateAttributes("noteImage", attrs).run();
		const ro = trashed;
		return [
			{ label: "Open full size", onSelect: () => frame.dispatchEvent(new Event("nt-lightbox")), disabled: !src },
			"-",
			{ label: "Size", disabled: ro, children: [
				{ label: "Small", checked: a.width === "small", onSelect: () => set({ width: "small" }) },
				{ label: "Medium", checked: a.width === "half", onSelect: () => set({ width: "half" }) },
				{ label: "Full width", checked: a.width === "full", onSelect: () => set({ width: "full" }) },
			] },
			{ label: "Align", disabled: ro, children: [
				{ label: "Left", checked: (a.align || "left") === "left", onSelect: () => set({ align: "left" }) },
				{ label: "Centre", checked: a.align === "center", onSelect: () => set({ align: "center" }) },
				{ label: "Right", checked: a.align === "right", onSelect: () => set({ align: "right" }) },
			] },
			{ label: a.caption ? "Edit caption" : "Add caption", disabled: ro, onSelect: () => frame.dispatchEvent(new Event("nt-caption")) },
			"-",
			{ label: "Copy image", disabled: !src, onSelect: () => copyImage(src, note) },
			{ label: "Download image", disabled: !src, onSelect: () => downloadImage(src, a.caption || latest.current.title || "image").catch(() => note("Couldn't download the image.")) },
			"-",
			{ label: "Delete image", danger: true, disabled: ro, onSelect: () => ed.chain().focus().setNodeSelection(pos).deleteSelection().run() },
		];
	};

	const textMenu = (ed) => {
		const ro = trashed;
		const hasSel = !ed.state.selection.empty;
		const selText = hasSel ? ed.state.doc.textBetween(ed.state.selection.from, ed.state.selection.to, " ").trim() : "";
		const link = linkAt(ed);
		const inList = ed.isActive("listItem") || ed.isActive("taskItem");
		const inTasks = ed.isActive("taskItem");
		const short = selText.length > 24 ? `${selText.slice(0, 22)}…` : selText;
		const items = [
			{ label: "Cut", hint: `${MOD}X`, disabled: ro || !hasSel, onSelect: () => cutCopy(ed, "cut", note) },
			{ label: "Copy", hint: `${MOD}C`, disabled: !hasSel, onSelect: () => cutCopy(ed, "copy", note) },
			{ label: "Paste", hint: `${MOD}V`, disabled: ro, onSelect: () => pasteFromClipboard(ed, { insertImages, notify: note }) },
			{ label: "Paste as plain text", hint: `${MOD}⇧V`, disabled: ro, onSelect: () => pasteFromClipboard(ed, { plain: true, insertImages, notify: note }) },
		];
		if (hasSel && !ro) {
			items.push("-",
				{ label: "Bold", hint: `${MOD}B`, checked: ed.isActive("bold"), onSelect: () => chain().toggleBold().run() },
				{ label: "Italic", hint: `${MOD}I`, checked: ed.isActive("italic"), onSelect: () => chain().toggleItalic().run() },
				{ label: "Strikethrough", checked: ed.isActive("strike"), onSelect: () => chain().toggleStrike().run() },
				{ label: "Highlight", hint: `${MOD}⇧H`, checked: ed.isActive("highlight"), onSelect: () => chain().toggleHighlight().run() },
				{ label: "Turn into", children: [
					{ label: "Heading", checked: ed.isActive("heading", { level: 1 }), onSelect: () => chain().setHeading({ level: 1 }).run() },
					{ label: "Subheading", checked: ed.isActive("heading", { level: 2 }), onSelect: () => chain().setHeading({ level: 2 }).run() },
					{ label: "Small heading", checked: ed.isActive("heading", { level: 3 }), onSelect: () => chain().setHeading({ level: 3 }).run() },
					{ label: "Paragraph", checked: ed.isActive("paragraph") && !ed.isActive("blockquote"), onSelect: () => chain().setParagraph().run() },
					{ label: "Quote", checked: ed.isActive("blockquote"), onSelect: () => chain().toggleBlockquote().run() },
				] },
				{ label: "Clear formatting", onSelect: () => chain().unsetAllMarks().clearNodes().run() },
				"-",
				{ label: "Link to a note…", onSelect: () => pickNote("Link the selection to a note", (id) => chain().setLink(noteLinkAttrs(id)).run()) },
				{ label: "Link to a web address…", onSelect: linkWeb },
				{ label: `Search all notes for “${short}”`, disabled: !selText, onSelect: () => cb.current.nav?.searchAll(selText) },
				{ label: "Move to a new note", onSelect: () => toNewNote(true) },
				{ label: "Copy to a new note", onSelect: () => toNewNote(false) },
			);
		} else if (hasSel) {
			items.push({ label: `Search all notes for “${short}”`, disabled: !selText, onSelect: () => cb.current.nav?.searchAll(selText) });
		}
		if (link) {
			items.push("-",
				{ label: link.noteId ? "Open note" : "Open link", onSelect: () => openLink(link) },
				...(ro ? [] : [
					{ label: "Edit link…", onSelect: () => editLink(link) },
					{ label: "Remove link", onSelect: () => chain().extendMarkRange("link").unsetLink().run() },
				]),
				{ label: "Copy link address", onSelect: () => copyText(absoluteUrl(link.href), note, "Link copied") },
			);
		}
		if (inList && !ro) {
			items.push("-",
				{ label: "Indent", hint: "Tab", onSelect: () => chain().indent().run() },
				{ label: "Outdent", hint: "⇧Tab", onSelect: () => chain().outdent().run() },
				{ label: "Convert list to", children: [
					{ label: "Bulleted list", checked: ed.isActive("bulletList"), onSelect: () => convertList(ed, "bulletList") },
					{ label: "Numbered list", checked: ed.isActive("orderedList"), onSelect: () => convertList(ed, "orderedList") },
					{ label: "Checklist", checked: ed.isActive("taskList"), onSelect: () => convertList(ed, "taskList") },
				] },
				...(inTasks ? [
					{ label: "Check all", onSelect: () => setAllChecked(ed, true) },
					{ label: "Uncheck all", onSelect: () => setAllChecked(ed, false) },
				] : []),
			);
		}
		items.push("-");
		if (!ro) items.push({ label: "Insert", children: insertMenu(ed) });
		items.push(
			{ label: "Find in note…", hint: `${MOD}F`, onSelect: () => openFind(selText && selText.length <= 100 ? selText : null) },
			{ label: "Select all", hint: `${MOD}A`, onSelect: () => chain().selectAll().run() },
		);
		if (!ro) {
			items.push("-",
				{ label: "Undo", hint: `${MOD}Z`, disabled: !ed.can().undo(), onSelect: () => chain().undo().run() },
				{ label: "Redo", hint: `${MOD}⇧Z`, disabled: !ed.can().redo(), onSelect: () => chain().redo().run() },
			);
		}
		return items;
	};

	// Shift+right-click (and any long-press on a touch screen) keeps the browser's own
	// menu — spell-check suggestions live there.
	const onContextMenu = (e) => {
		const ed = editorRef.current;
		if (!ed || ed.isDestroyed || e.shiftKey || pointerType.current === "touch") return;
		if (!ed.view.dom.contains(e.target)) return;   // the title keeps the native menu
		e.preventDefault();
		const { view } = ed;
		let x = e.clientX, y = e.clientY;
		if (!x && !y) {   // the keyboard's Menu key: open at the cursor
			const c = view.coordsAtPos(ed.state.selection.from);
			x = c.left; y = c.bottom;
		}
		const frame = e.target.closest(".nt-img-frame, .nt-img");
		if (frame) {
			const f = frame.classList.contains("nt-img-frame") ? frame : frame.querySelector(".nt-img-frame");
			let pos = null;
			ed.state.doc.descendants((n, p) => {
				if (pos == null && n.type.name === "noteImage" && view.nodeDOM(p)?.contains(frame)) pos = p;
				return pos == null;
			});
			if (pos != null && f) {
				view.dispatch(ed.state.tr.setSelection(NodeSelection.create(ed.state.doc, pos)));
				setCtxMenu({ x, y, items: imageMenu(ed, pos, f) });
				return;
			}
		}
		// Right-clicking OUTSIDE the selection moves the cursor there (as every editor
		// does); inside it, the selection is what the menu acts on.
		const at = view.posAtCoords({ left: e.clientX, top: e.clientY });
		const { from, to, empty } = ed.state.selection;
		if (at && (empty || at.pos < from || at.pos > to)) {
			view.dispatch(ed.state.tr.setSelection(TextSelection.create(ed.state.doc, at.pos)));
		}
		view.focus();
		setCtxMenu({ x, y, items: textMenu(ed) });
	};

	// Enter in the title continues into the body. SYNCHRONOUSLY: tiptap's focus()
	// command waits a frame, so a key typed straight after Enter landed in the title.
	const focusBodyStart = () => {
		const ed = editorRef.current;
		if (!ed || ed.isDestroyed) return;
		const { view } = ed;
		view.dispatch(view.state.tr.setSelection(Selection.atStart(view.state.doc)));
		view.focus();
	};

	const onTitle = (v) => {
		setTitle(v);
		latest.current.title = v;
		markDirty();
	};

	const keepMine = () => {
		if (!conflict) return;
		revRef.current = conflict.rev;
		setConflict(null);
		setStatus("dirty");
		editSeq.current += 1;
		save();
	};

	return (
		<div className="nt-editor">
			{editor && (
				<div className="nt-bars">
					<Toolbar editor={editor} onPickImages={(f) => insertImages(f)} findOpen={findOpen} fileRef={fileRef}
						onFind={() => (findOpen ? closeFind() : openFind(null))} />
					{findOpen && <FindBar editor={editor} text={findText} setText={setFindText} onClose={closeFind} inputRef={findInput} />}
				</div>
			)}
			{/* The save state lives in the page header (a slot the page hands us): at the
			    end of the toolbar it scrolled off-screen on a phone, which is exactly
			    where "Offline — retrying" most needs to be seen. */}
			{statusSlot && createPortal(<SaveStatus status={status} />, statusSlot)}
			{conflict && (
				<div className="nt-banner" role="alert">
					<span>This note was changed in another tab or on another device.</span>
					<span className="nt-banner-acts">
						<button type="button" className="btn btn-ghost btn-sm" onClick={() => onReload(conflict)}>Load theirs</button>
						<button type="button" className="btn btn-outline btn-sm" onClick={keepMine}>Keep mine</button>
					</span>
				</div>
			)}
			{trashed && (
				<div className="nt-banner">
					<span>This note is in the Trash.</span>
					<span className="nt-banner-acts">
						<button type="button" className="btn btn-outline btn-sm" onClick={onRestore}>Restore</button>
					</span>
				</div>
			)}
			{ctxMenu && <ContextMenu x={ctxMenu.x} y={ctxMenu.y} items={ctxMenu.items} onClose={() => setCtxMenu(null)} />}
			{picker && (
				<NotePicker title={picker.title} notes={cb.current.nav?.notes || []} folderPath={cb.current.nav?.folderPath || (() => "")}
					excludeId={noteId} onPick={picker.onPick} onCreate={picker.onCreate} onClose={() => setPicker(null)} />
			)}
			<div className="nt-page" onContextMenu={onContextMenu}
				onPointerDown={(e) => { pointerType.current = e.pointerType || "mouse"; }}>
				<input ref={titleRef} className="nt-title" value={title} placeholder="Untitled" aria-label="Title" maxLength={200}
					readOnly={trashed} onChange={(e) => onTitle(e.target.value)}
					onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); focusBodyStart(); } }} />
				<EditorContent editor={editor} />
			</div>
		</div>
	);
}

// Loads a note, then hands it to the editor. `version` remounts the editor with a
// fresh copy — how "Load theirs" and Restore take effect.
export default function NoteEditor({ api, noteId, onSaved, onGone, onRestore, notify, statusSlot, focusTitle, onTitleFocused, findRequest, nav }) {
	const [note, setNote] = useState(null);
	const [err, setErr] = useState(null);
	const [version, setVersion] = useState(0);

	useEffect(() => {
		let live = true;
		setNote(null);
		setErr(null);
		api.getNote(noteId).then(
			(n) => live && setNote(n),
			(e) => live && setErr(e.status === 404 ? "missing" : e.status === undefined ? "offline" : "error"),
		);
		return () => { live = false; };
	}, [api, noteId, version]);

	if (err) return (
		<div className="nt-empty">
			<p>{err === "missing" ? "This note doesn't exist any more." : "Couldn't load this note."}</p>
			{err !== "missing" && <button type="button" className="btn btn-outline btn-sm" onClick={() => setVersion((v) => v + 1)}>Try again</button>}
		</div>
	);
	if (!note) return <div className="nt-empty nt-loading">Loading…</div>;
	return (
		<LoadedEditor key={`${note.id}:${note.rev}:${version}`} api={api} initial={note} notify={notify} statusSlot={statusSlot}
			focusTitle={focusTitle} onTitleFocused={onTitleFocused} findRequest={findRequest} nav={nav}
			onSaved={onSaved} onGone={onGone}
			onReload={(server) => { if (server) { setNote(server); setVersion((v) => v + 1); } else setVersion((v) => v + 1); }}
			onRestore={async () => { await onRestore(note.id); setVersion((v) => v + 1); }} />
	);
}
