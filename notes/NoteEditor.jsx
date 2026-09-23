import { useCallback, useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useEditor, useEditorState, EditorContent, NodeViewWrapper, ReactNodeViewRenderer } from "@tiptap/react";
import { Node, mergeAttributes } from "@tiptap/core";
import { NodeSelection, Selection } from "@tiptap/pm/state";
import StarterKit from "@tiptap/starter-kit";
import { TaskList, TaskItem } from "@tiptap/extension-list";
import { Placeholder } from "@tiptap/extensions";

import { I } from "./icons.jsx";
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
	const { imageId, uploadKey, width, caption, w, h } = node.attrs;
	const api = extension.options.api;
	const pending = !imageId && uploadKey ? pendingUploads.get(uploadKey) : null;
	const [src, setSrc] = useState(pending?.previewUrl || null);
	const [failed, setFailed] = useState(false);
	const [open, setOpen] = useState(false);

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
		<NodeViewWrapper className={`nt-img nt-img-${width}${selected ? " is-selected" : ""}`}>
			<div className="nt-img-frame" data-drag-handle="" draggable="true"
				style={w && h ? { aspectRatio: `${w} / ${h}` } : undefined}>
				{src && !failed
					? <img src={src} alt={caption || "Screenshot"} draggable={false} onDoubleClick={() => setOpen(true)} />
					: <div className="nt-img-ph">{label}</div>}
				{pending && <div className="nt-img-busy">Uploading…</div>}
			</div>
			{/* The controls sit UNDER the image, never on it: a screenshot is kept for the
			    text in it, and an overlay on its top edge also slid under the sticky
			    toolbar the moment a tall image was scrolled. */}
			{(selected || caption) && (
				<div className="nt-img-bar">
					<input className="nt-img-cap" value={caption || ""} placeholder="Add a caption…"
						aria-label="Image caption" maxLength={300}
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

function Toolbar({ editor, onPickImages }) {
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
			link: e.isActive("link"),
			canUndo: e.can().undo(),
			canRedo: e.can().redo(),
		}),
	});
	const fileRef = useRef(null);
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
				<B label="Add image" onDown={(e) => { e.preventDefault(); fileRef.current?.click(); }}>{I.image}</B>
				<input ref={fileRef} type="file" accept="image/*" multiple hidden
					onChange={(e) => { const f = Array.from(e.target.files || []); e.target.value = ""; if (f.length) onPickImages(f); }} />
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
const KEEPALIVE_MAX = 60_000;   // fetch keepalive bodies are capped at 64KB

function LoadedEditor({ api, initial, onSaved, onGone, onReload, onRestore, notify, statusSlot }) {
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
	const cb = useRef(null);
	cb.current = { onSaved, onGone, notify };

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
			Placeholder.configure({ placeholder: "Start writing… paste or drop screenshots anywhere." }),
			NoteImage.configure({ api }),
		],
		content: initial.doc || "",
		editorProps: {
			attributes: { class: "nt-prose", spellcheck: "true", "aria-label": "Note" },
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
			{editor && <Toolbar editor={editor} onPickImages={(f) => insertImages(f)} />}
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
			<div className="nt-page">
				<input className="nt-title" value={title} placeholder="Untitled" aria-label="Title" maxLength={200}
					readOnly={trashed} onChange={(e) => onTitle(e.target.value)}
					onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); focusBodyStart(); } }} />
				<EditorContent editor={editor} />
			</div>
		</div>
	);
}

// Loads a note, then hands it to the editor. `version` remounts the editor with a
// fresh copy — how "Load theirs" and Restore take effect.
export default function NoteEditor({ api, noteId, onSaved, onGone, onRestore, notify, statusSlot }) {
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
			onSaved={onSaved} onGone={onGone}
			onReload={(server) => { if (server) { setNote(server); setVersion((v) => v + 1); } else setVersion((v) => v + 1); }}
			onRestore={async () => { await onRestore(note.id); setVersion((v) => v + 1); }} />
	);
}
