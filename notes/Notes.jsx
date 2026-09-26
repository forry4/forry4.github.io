import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../shared/theme.js";
import { buildPath, parsePath, pushPath, subscribe } from "../shared/router.js";
import { makeApi } from "./api.js";
import { syncNotesOffline } from "./offlineStore.js";
import { setImageOwner } from "./images.js";
import { I } from "./icons.jsx";
import { ContextMenu } from "./menu.jsx";
import { copyText } from "./editorMenu.js";

// CSS in a real .css file, imported ?inline and injected by this component's own
// <style> tag while it is mounted (see the root CLAUDE.md: never a JS template literal).
import css from "./Notes.css?inline";

// The editor (TipTap/ProseMirror) is the heavy half of this page; splitting it keeps
// the sidebar and the sign-in screen fast, and a guest who has not signed in never
// downloads an editor at all.
const NoteEditor = lazy(() => import("./NoteEditor.jsx"));

// Segment 2 of /notes/<x> is either a note id or "trash". router.js upper-cases
// segment 2 (it was written for room codes); note ids are lowercase [a-z0-9], so
// lower-casing it back is exact.
const TRASH = "trash";
const routeTarget = () => (parsePath().room || "").toLowerCase() || null;

const RECENT_COUNT = 6;

// The server counts storage in decimal megabytes (notes/api.py QUOTA_BYTES).
const megabytes = (b) => `${(b / 1_000_000).toFixed(b < 10_000_000 ? 1 : 0)} MB`;

function readLS(key, fallback) {
	try { const v = localStorage.getItem(key); return v == null ? fallback : JSON.parse(v); } catch { return fallback; }
}
function writeLS(key, value) {
	try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* private mode / quota */ }
}

function ago(ts) {
	if (!ts) return "";
	const s = Date.now() / 1000 - ts;
	if (s < 60) return "just now";
	if (s < 3600) return `${Math.floor(s / 60)}m ago`;
	if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
	const d = new Date(ts * 1000);
	if (s < 6 * 86400) return d.toLocaleDateString(undefined, { weekday: "short" });
	return d.toLocaleDateString(undefined, { month: "short", day: "numeric",
		...(d.getFullYear() !== new Date().getFullYear() ? { year: "numeric" } : {}) });
}

const byTitle = (a, b) => (a.title || "Untitled").localeCompare(b.title || "Untitled", undefined, { numeric: true, sensitivity: "base" });
const byEdited = (a, b) => (b.updated_at || 0) - (a.updated_at || 0);
const byName = (a, b) => a.name.localeCompare(b.name, undefined, { numeric: true, sensitivity: "base" });

// ─── small building blocks ────────────────────────────────────────────────────
function MoveDialog({ title, folders, disabled, current, onPick, onClose }) {
	useEffect(() => {
		const key = (e) => { if (e.key === "Escape") onClose(); };
		document.addEventListener("keydown", key);
		return () => document.removeEventListener("keydown", key);
	}, [onClose]);
	const rows = [];
	const walk = (parent, depth) => {
		folders.filter((f) => f.parent_id === parent).sort(byName).forEach((f) => {
			rows.push({ f, depth });
			walk(f.id, depth + 1);
		});
	};
	walk(null, 1);
	return (
		<div className="nt-modal-back" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
			<div className="nt-modal" role="dialog" aria-label={title}>
				<div className="nt-modal-hd">{title}</div>
				<div className="nt-modal-list">
					<button type="button" className="nt-move-row" disabled={current === null}
						style={{ "--depth": 0 }} onClick={() => onPick(null)}>
						<span className="nt-ic">{I.note}</span> Top level
					</button>
					{rows.map(({ f, depth }) => (
						<button key={f.id} type="button" className="nt-move-row"
							disabled={disabled.has(f.id) || current === f.id}
							style={{ "--depth": depth }} onClick={() => onPick(f.id)}>
							<span className="nt-ic">{I.folder}</span> {f.name}
						</button>
					))}
				</div>
				<div className="nt-modal-ft">
					<button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
				</div>
			</div>
		</div>
	);
}

/** Take a copy now, without opening the page — the offline hub's Reading download.
 *  The folder tree under the key the page paints from, then every note and picture. */
export async function saveOfflineCopy(authUser) {
	const token = authUser && !authUser.guest ? authUser.session_token : null;
	if (!token) return;
	const api = makeApi(token);
	const t = await api.tree();
	const tree = { folders: t.folders, notes: t.notes };
	writeLS(`notes.tree.${authUser.id}`, tree);
	await syncNotesOffline(api, authUser.id, tree);
}

// ─── the page ─────────────────────────────────────────────────────────────────
export default function Notes({ authUser, onExit }) {
	const token = authUser?.session_token || null;
	const api = useMemo(() => makeApi(token), [token]);
	const cacheKey = `notes.tree.${authUser?.id || "anon"}`;

	// Stale-while-revalidate: the sidebar paints from the last tree this browser saw
	// while the (possibly cold) backend answers.
	const [tree, setTree] = useState(() => readLS(cacheKey, null));
	const [access, setAccess] = useState(token ? "loading" : "denied");   // loading | ok | denied | offline
	// { bytes, notes, quota_bytes, max_notes } from the tree; quota_bytes is null for the
	// site owner, whose notebook is unmetered (notes/api.py Meter).
	const [usage, setUsage] = useState(null);
	const [target, setTarget] = useState(routeTarget);
	const [expanded, setExpanded] = useState(() => new Set(readLS("notes.expanded", [])));
	const [sort, setSort] = useState(() => readLS("notes.sort", "edited"));
	const [activeFolder, setActiveFolder] = useState(null);
	const [menu, setMenu] = useState(null);         // { key, x, y, items } — the open row menu
	const [renaming, setRenaming] = useState(null); // folder id
	const [moving, setMoving] = useState(null);     // { kind: "note"|"folder", id }
	const [dropOn, setDropOn] = useState(null);     // folder id | "root"
	const [toast, setToast] = useState("");
	const toastTimer = useRef(null);
	// The note just created here: its title takes focus when its editor MOUNTS. It was a
	// 250ms timer, which fired mid-sentence if you started typing in the body first.
	const freshNote = useRef(null);
	// The open editor's flush(): saves what was typed and waits. Trashing the open note
	// (or its folder) calls it first, or the last edits are refused as "no such note".
	const flushOpen = useRef(null);

	// ── search (the sidebar) ──
	// `scope` is a folder id — that folder and every folder inside it — or null for all
	// notes. Results are the server's (notes/api.py search_notes reads each note's plain
	// text), and a result opens its note with the same query highlighted in the note.
	const [query, setQuery] = useState("");
	const [scope, setScope] = useState(null);
	const [results, setResults] = useState(null);   // null = no search running
	const [searchState, setSearchState] = useState("idle");   // idle | busy | error
	const [findReq, setFindReq] = useState(null);   // { id, q, n } for the note being opened
	const searchBox = useRef(null);
	const searchSeq = useRef(0);
	const q = query.trim();
	useEffect(() => {
		if (!q) { setResults(null); setSearchState("idle"); return undefined; }
		const seq = ++searchSeq.current;
		setSearchState("busy");
		const t = setTimeout(async () => {
			try {
				const r = await api.search(q, scope);
				if (seq === searchSeq.current) { setResults(r); setSearchState("idle"); }
			} catch {
				if (seq === searchSeq.current) setSearchState("error");
			}
		}, 250);
		return () => clearTimeout(t);
	// `tree` too: a save changes what matches, so results stay current as you edit
	}, [q, scope, api, tree]);
	const [statusSlot, setStatusSlot] = useState(null);   // header node the editor portals "Saved" into

	const notify = useCallback((msg) => {
		setToast(msg);
		clearTimeout(toastTimer.current);
		toastTimer.current = setTimeout(() => setToast(""), 4000);
	}, []);

	const load = useCallback(async () => {
		if (!token) { setAccess("denied"); return; }
		try {
			const t = await api.tree();
			const next = { folders: t.folders, notes: t.notes };
			setTree(next);
			setUsage(t.usage || null);
			writeLS(cacheKey, next);
			setAccess("ok");
			// Keep this device's read-only copy current, in the background.
			syncNotesOffline(api, authUser?.id, next).catch(() => {});
		} catch (e) {
			setAccess(e.status === 401 || e.status === 403 ? "denied" : "offline");
		}
	}, [api, token, cacheKey]);

	useEffect(() => { load(); }, [load]);
	useEffect(() => { setImageOwner(authUser?.id); return () => setImageOwner(null); }, [authUser?.id]);
	useEffect(() => { if (tree) writeLS(cacheKey, tree); }, [tree, cacheKey]);
	useEffect(() => { writeLS("notes.expanded", [...expanded]); }, [expanded]);
	useEffect(() => { writeLS("notes.sort", sort); }, [sort]);

	// Back/Forward within /notes belongs to this page (the router contract).
	useEffect(() => subscribe((r) => { if (r.game === "notes") setTarget((r.room || "").toLowerCase() || null); }), []);

	const go = useCallback((t) => {
		pushPath(buildPath("notes", t || undefined));
		setTarget(t);
		setMenu(null);
	}, []);

	// ── derived ──
	const folders = tree?.folders || [];
	const notes = tree?.notes || [];
	const folderById = useMemo(() => new Map(folders.map((f) => [f.id, f])), [folders]);
	const live = useMemo(() => notes.filter((n) => n.deleted_at == null), [notes]);
	const trashed = useMemo(() => notes.filter((n) => n.deleted_at != null).sort((a, b) => b.deleted_at - a.deleted_at), [notes]);
	const pinned = useMemo(() => live.filter((n) => n.pinned).sort(byTitle), [live]);
	const recent = useMemo(() => [...live].sort(byEdited).slice(0, RECENT_COUNT), [live]);
	const childFolders = useCallback((pid) => folders.filter((f) => f.parent_id === pid).sort(byName), [folders]);
	const notesIn = useCallback((fid) => live
		.filter((n) => (n.folder_id && folderById.has(n.folder_id) ? n.folder_id : null) === fid)
		.sort(sort === "title" ? byTitle : byEdited), [live, folderById, sort]);
	const subtree = useCallback((root) => {
		const out = new Set([root]);
		let grew = true;
		while (grew) {
			grew = false;
			for (const f of folders) if (out.has(f.parent_id) && !out.has(f.id)) { out.add(f.id); grew = true; }
		}
		return out;
	}, [folders]);
	const countIn = useCallback((fid) => {
		const sub = subtree(fid);
		return live.filter((n) => sub.has(n.folder_id)).length;
	}, [live, subtree]);

	const folderPath = (fid) => {
		const names = [];
		for (let f = folderById.get(fid); f; f = folderById.get(f.parent_id)) names.unshift(f.name);
		return names.join(" › ");
	};
	const openHit = (h) => {
		setFindReq({ id: h.id, q, n: Date.now() });
		setActiveFolder(h.folder_id);
		go(h.id);
	};
	const searchIn = (fid) => {
		setScope(fid);
		setMenu(null);
		setTimeout(() => searchBox.current?.focus(), 0);
	};

	const openNote = target && target !== TRASH ? target : null;
	const openMeta = openNote ? notes.find((n) => n.id === openNote) : null;
	// New notes land in the folder you are looking at.
	const newNoteFolder = activeFolder && folderById.has(activeFolder) ? activeFolder
		: (openMeta?.folder_id && folderById.has(openMeta.folder_id) ? openMeta.folder_id : null);

	// ── mutations ──
	const patchNote = (n) => setTree((t) => t && ({ ...t, notes: t.notes.some((x) => x.id === n.id)
		? t.notes.map((x) => (x.id === n.id ? { ...x, ...pickMeta(n) } : x))
		: [pickMeta(n), ...t.notes] }));
	// The meter is read from the tree, so it moves when the tree is re-read: on load,
	// after the Trash frees space, and when a write is refused for being over quota.
	const refreshUsage = useCallback(() => {
		api.tree().then((t) => setUsage(t.usage || null), () => {});
	}, [api]);
	const fail = (e) => {
		notify(e.status === undefined ? "Can't reach the server — try again in a moment." : e.message);
		if (e.status === 413) refreshUsage();
	};

	const expandTo = (fid) => setExpanded((s) => {
		const next = new Set(s);
		for (let f = fid; f; f = folderById.get(f)?.parent_id) next.add(f);
		return next;
	});

	const newNote = async (fid = newNoteFolder) => {
		try {
			const n = await api.createNote(fid);
			patchNote(n);
			if (fid) expandTo(fid);
			go(n.id);
			freshNote.current = n.id;   // the title is the first thing a new note wants
		} catch (e) { fail(e); }
	};
	const newFolder = async (parent = activeFolder && folderById.has(activeFolder) ? activeFolder : null) => {
		try {
			const f = await api.createFolder(parent, "New folder");
			setTree((t) => t && ({ ...t, folders: [...t.folders, f] }));
			if (parent) expandTo(parent);
			setActiveFolder(f.id);
			setRenaming(f.id);
		} catch (e) { fail(e); }
	};
	const renameFolder = async (id, name) => {
		setRenaming(null);
		const f = folderById.get(id);
		if (!f || !name.trim() || name.trim() === f.name) return;
		try {
			const out = await api.updateFolder(id, { name: name.trim() });
			setTree((t) => ({ ...t, folders: t.folders.map((x) => (x.id === id ? out : x)) }));
		} catch (e) { fail(e); }
	};
	const moveNote = async (id, fid) => {
		try {
			patchNote(await api.noteMeta(id, { folder_id: fid }));
			if (fid) expandTo(fid);
		} catch (e) { fail(e); }
	};
	const moveFolder = async (id, pid) => {
		try {
			const out = await api.updateFolder(id, { parent_id: pid });
			setTree((t) => ({ ...t, folders: t.folders.map((x) => (x.id === id ? out : x)) }));
			if (pid) expandTo(pid);
		} catch (e) { fail(e); }
	};
	const togglePin = async (n) => {
		try { patchNote(await api.noteMeta(n.id, { pinned: !n.pinned })); } catch (e) { fail(e); }
	};
	const openInNewTab = (n) => window.open(buildPath("notes", n.id), "_blank", "noopener");
	// Titles are edited in the note itself (autosave + the stale-tab guard live there),
	// so Rename opens the note with its title selected, ready to type over.
	const renameNote = (n) => {
		if (openNote === n.id) {
			const t = document.querySelector(".nt-title");
			t?.focus();
			t?.select();
			return;
		}
		freshNote.current = n.id;
		setFindReq(null);
		setActiveFolder(n.folder_id);
		go(n.id);
	};
	const duplicateNote = async (n) => {
		try {
			const full = await api.getNote(n.id);
			const title = `${full.title || "Untitled"} (copy)`;
			const c = await api.createNote(full.folder_id, title);
			// images are shared by id, so the copy costs no image storage
			const saved = full.doc ? await api.saveNote(c.id, { title, doc: full.doc, base_rev: 0 }) : c;
			patchNote(saved);
			if (full.folder_id) expandTo(full.folder_id);
			notify(`Duplicated as “${title}”.`);
		} catch (e) { fail(e); }
	};
	const copyNoteLink = (n) => copyText(new URL(buildPath("notes", n.id), window.location.origin).href, notify, "Link copied");

	const noteItems = (n) => [
		{ label: "Open", onSelect: () => { setFindReq(null); setActiveFolder(n.folder_id); go(n.id); } },
		{ label: "Open in new tab", onSelect: () => openInNewTab(n) },
		"-",
		{ label: "Rename", onSelect: () => renameNote(n) },
		{ label: n.pinned ? "Unpin" : "Pin to top", onSelect: () => togglePin(n) },
		{ label: "Move to…", onSelect: () => setMoving({ kind: "note", id: n.id }) },
		{ label: "Duplicate", onSelect: () => duplicateNote(n) },
		{ label: "Copy link to this note", onSelect: () => copyNoteLink(n) },
		"-",
		{ label: "Move to Trash", danger: true, onSelect: () => trashNote(n) },
	];
	const folderItems = (f) => [
		{ label: "New note here", onSelect: () => newNote(f.id) },
		{ label: "New folder inside", onSelect: () => newFolder(f.id) },
		"-",
		{ label: "Rename", onSelect: () => setRenaming(f.id) },
		{ label: "Move to…", onSelect: () => setMoving({ kind: "folder", id: f.id }) },
		{ label: "Search in this folder", onSelect: () => searchIn(f.id) },
		"-",
		{ label: "Delete folder", danger: true, onSelect: () => deleteFolder(f) },
	];
	// The ⋯ button drops the menu under itself; right-click opens it at the pointer.
	const menuFromButton = (key, items) => (e) => {
		if (menu?.key === key) { setMenu(null); return; }
		const r = e.currentTarget.getBoundingClientRect();
		setMenu({ key, x: Math.max(8, r.right - 220), y: r.bottom + 2, items });
	};
	const menuFromPointer = (key, items) => (e) => {
		if (e.shiftKey) return;
		e.preventDefault();
		setMenu({ key, x: e.clientX, y: e.clientY, items });
	};

	const trashNote = async (n) => {
		try {
			if (openNote === n.id) await flushOpen.current?.();
			patchNote(await api.noteMeta(n.id, { trashed: true }));
			if (openNote === n.id) go(null);
			notify(`“${n.title || "Untitled"}” moved to the Trash.`);
		} catch (e) { fail(e); }
	};
	const restoreNote = async (id) => {
		try { patchNote(await api.noteMeta(id, { trashed: false })); } catch (e) { fail(e); }
	};
	const deleteForever = async (n) => {
		if (!window.confirm(`Delete “${n.title || "Untitled"}” forever? This can't be undone.`)) return;
		try {
			await api.deleteNote(n.id);
			setTree((t) => ({ ...t, notes: t.notes.filter((x) => x.id !== n.id) }));
			refreshUsage();
		} catch (e) { fail(e); }
	};
	const emptyTrash = async () => {
		if (!window.confirm(`Delete all ${trashed.length} notes in the Trash forever?`)) return;
		try {
			await api.emptyTrash();
			setTree((t) => ({ ...t, notes: t.notes.filter((x) => x.deleted_at == null) }));
			refreshUsage();
		} catch (e) { fail(e); }
	};
	const deleteFolder = async (f) => {
		const n = countIn(f.id);
		const msg = n
			? `Delete “${f.name}”? Its ${n} note${n === 1 ? "" : "s"} will move to the Trash.`
			: `Delete the empty folder “${f.name}”?`;
		if (!window.confirm(msg)) return;
		const closing = openMeta && openMeta.deleted_at == null && subtree(f.id).has(openMeta.folder_id);
		try {
			if (closing) await flushOpen.current?.();
			await api.deleteFolder(f.id);
			if (closing) go(null);   // the open note is in the Trash now, like "Move to Trash"
			await load();   // the server trashed a whole subtree — take its word for it
		} catch (e) { fail(e); }
	};

	// ── drag & drop (desktop; touch uses "Move to…") ──
	const dragData = (e, kind, id) => {
		e.dataTransfer.setData("application/x-nt", JSON.stringify({ kind, id }));
		e.dataTransfer.effectAllowed = "move";
	};
	const readDrag = (e) => { try { return JSON.parse(e.dataTransfer.getData("application/x-nt")); } catch { return null; } };
	const canDrop = (e) => Array.from(e.dataTransfer.types || []).includes("application/x-nt");
	const dropProps = (key, fid) => ({
		onDragOver: (e) => { if (canDrop(e)) { e.preventDefault(); if (dropOn !== key) setDropOn(key); } },
		onDragLeave: () => setDropOn((d) => (d === key ? null : d)),
		onDrop: (e) => {
			setDropOn(null);
			const d = readDrag(e);
			if (!d) return;
			e.preventDefault();
			if (d.kind === "note") moveNote(d.id, fid);
			else if (d.kind === "folder" && d.id !== fid && !(fid && subtree(d.id).has(fid))) moveFolder(d.id, fid);
		},
	});

	// ── rows ──
	// Render FUNCTIONS, not components: a component declared inside this one would be
	// a new type every render, so React would remount every row on each keystroke of
	// a rename and cancel a drag the moment its hover state changed.
	const noteRow = (n, depth, where) => {
		const key = `n:${where}:${n.id}`;
		return (
			<div key={key} className={`nt-row nt-note-row${where === "tree" ? " in-tree" : ""}${openNote === n.id ? " on" : ""}`} style={{ "--depth": depth }}
				onContextMenu={menuFromPointer(key, noteItems(n))}>
				<button type="button" className="nt-row-main" draggable onDragStart={(e) => dragData(e, "note", n.id)}
					onClick={() => { setFindReq(null); setActiveFolder(n.folder_id); go(n.id); }}>
					<span className="nt-ic">{I.note}</span>
					<span className="nt-row-text">
						<span className="nt-row-title">{n.title || "Untitled"}</span>
						<span className="nt-row-sub">{ago(n.updated_at)}</span>
					</span>
					{n.pinned && where !== "pinned" && <span className="nt-ic nt-pin-mark" title="Pinned">{I.pin}</span>}
				</button>
				<button type="button" className="nt-row-more" aria-label={`More for ${n.title || "Untitled"}`}
					aria-haspopup="menu" aria-expanded={menu?.key === key} onClick={menuFromButton(key, noteItems(n))}>{I.dots}</button>
			</div>
		);
	};

	const folderRow = (f, depth) => {
		const open = expanded.has(f.id);
		const key = `f:${f.id}`;
		const count = countIn(f.id);
		const toggle = () => setExpanded((s) => { const n = new Set(s); if (n.has(f.id)) n.delete(f.id); else n.add(f.id); return n; });
		return (
			<div key={f.id} className="nt-branch">
				<div className={`nt-row nt-folder-row${activeFolder === f.id ? " active" : ""}${dropOn === f.id ? " drop" : ""}`}
					style={{ "--depth": depth }} {...dropProps(f.id, f.id)}
					onContextMenu={renaming === f.id ? undefined : menuFromPointer(key, folderItems(f))}>
					{renaming === f.id ? (
						<div className="nt-row-main nt-renaming">
							<span className="nt-ic">{I.folder}</span>
							<input className="nt-rename" defaultValue={f.name} autoFocus maxLength={200} aria-label="Folder name"
								onFocus={(e) => e.target.select()}
								onBlur={(e) => renameFolder(f.id, e.target.value)}
								onKeyDown={(e) => {
									if (e.key === "Enter") e.currentTarget.blur();
									if (e.key === "Escape") setRenaming(null);
								}} />
						</div>
					) : (
						<button type="button" className="nt-row-main" aria-expanded={open} draggable
							onDragStart={(e) => dragData(e, "folder", f.id)}
							onClick={() => { toggle(); setActiveFolder(f.id); }}>
							<span className={`nt-ic nt-caret${open ? " open" : ""}`}>{I.caret}</span>
							<span className="nt-ic">{I.folder}</span>
							<span className="nt-row-text"><span className="nt-row-title">{f.name}</span></span>
							{count > 0 && <span className="nt-count">{count}</span>}
						</button>
					)}
					<button type="button" className="nt-row-more" aria-label={`More for folder ${f.name}`}
						aria-haspopup="menu" aria-expanded={menu?.key === key} onClick={menuFromButton(key, folderItems(f))}>{I.dots}</button>
				</div>
				{open && branch(f.id, depth + 1)}
			</div>
		);
	};

	const branch = (parent, depth) => {
		const subs = childFolders(parent);
		const own = notesIn(parent);
		if (parent && !subs.length && !own.length) {
			return <div key="empty" className="nt-row nt-row-empty" style={{ "--depth": depth }}>Empty</div>;
		}
		return (
			<>
				{subs.map((f) => folderRow(f, depth))}
				{own.map((n) => noteRow(n, depth, "tree"))}
			</>
		);
	};

	useEffect(() => {
		if (openNote) return undefined;
		const onKey = (e) => {
			if (!(e.ctrlKey || e.metaKey) || e.altKey || e.shiftKey || e.key.toLowerCase() !== "f") return;
			e.preventDefault();
			searchBox.current?.focus();
			searchBox.current?.select();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	}, [openNote]);

	// A snippet is plain text + the match's offsets, so nothing the server sends is ever
	// rendered as HTML.
	const snippet = (sn, i) => (
		<span key={i} className="nt-hit-snip">
			{sn.text.slice(0, sn.start)}<mark>{sn.text.slice(sn.start, sn.start + sn.length)}</mark>{sn.text.slice(sn.start + sn.length)}
		</span>
	);
	const hitTitle = (h) => {
		const t = h.title || "Untitled";
		const i = h.title_match ? t.toLowerCase().indexOf(q.toLowerCase()) : -1;
		return i < 0 || t.length !== t.toLowerCase().length ? t
			: <>{t.slice(0, i)}<mark>{t.slice(i, i + q.length)}</mark>{t.slice(i + q.length)}</>;
	};

	// ── screens ──
	if (access === "denied") return (
		<div className="nt-app nt-private">
			<style>{baseCss + css}</style>
			<header className="nt-header">
				<button type="button" className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
				<div className="nt-headtitle">Notes</div>
			</header>
			<div className="nt-empty">
				<p>Notes is a private notebook for your account: folders, notes and screenshots only you can see.</p>
				<p className="nt-dim">{!authUser || authUser.guest
					? "Sign in or create an account to start one."
					: "Your sign-in has expired. Sign in again to open your notes."}</p>
			</div>
		</div>
	);

	const trashView = target === TRASH;
	const showMain = !!openNote || trashView;
	const moveDisabled = moving?.kind === "folder" ? subtree(moving.id) : new Set();
	const moveCurrent = moving
		? (moving.kind === "note"
			? (notes.find((n) => n.id === moving.id)?.folder_id ?? null)
			: (folderById.get(moving.id)?.parent_id ?? null))
		: undefined;

	return (
		<div className={`nt-app${showMain ? " nt-open" : ""}`}>
			<style>{baseCss + css}</style>
			<header className="nt-header">
				<button type="button" className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
				<div className="nt-headtitle">Notes</div>
				<div className="nt-head-status" ref={setStatusSlot} />
				{access === "offline" && (
					<button type="button" className="nt-offline" onClick={load}>Offline — retry</button>
				)}
			</header>

			<div className="nt-body">
				<aside className="nt-side" aria-label="Notes">
					<div className="nt-side-acts">
						<button type="button" className="btn btn-gold btn-sm" onClick={() => newNote()} disabled={access !== "ok"}>
							{I.plus} Note
						</button>
						<button type="button" className="btn btn-ghost btn-sm" onClick={() => newFolder()} disabled={access !== "ok"}>
							{I.plus} Folder
						</button>
					</div>

					<div className="nt-search">
						<span className="nt-ic">{I.search}</span>
						<input ref={searchBox} className="nt-search-in" value={query} disabled={access !== "ok"}
							placeholder={scope && folderById.has(scope) ? `Search in ${folderById.get(scope).name}` : "Search all notes"}
							aria-label="Search notes" enterKeyHint="search" autoComplete="off" spellCheck={false}
							onChange={(e) => setQuery(e.target.value)}
							onKeyDown={(e) => { if (e.key === "Escape") { setQuery(""); e.currentTarget.blur(); } }} />
						{query && (
							<button type="button" className="nt-search-x" aria-label="Clear search" onClick={() => { setQuery(""); searchBox.current?.focus(); }}>
								{I.close}
							</button>
						)}
					</div>
					{scope && folderById.has(scope) ? (
						<div className="nt-scope">
							<span>In <b>{folderPath(scope)}</b> and its folders</span>
							<button type="button" onClick={() => setScope(null)}>Search all notes</button>
						</div>
					) : q && activeFolder && folderById.has(activeFolder) ? (
						<div className="nt-scope">
							<span>All notes</span>
							<button type="button" onClick={() => setScope(activeFolder)}>Only in {folderById.get(activeFolder).name}</button>
						</div>
					) : null}

					{!tree && access === "loading" && <div className="nt-side-note">Loading…</div>}

					{q ? (
						<section className="nt-sec nt-results" aria-live="polite">
							<h2 className="nt-sec-hd">
								<span className="nt-ic">{I.search}</span>
								{searchState === "error" ? "Search failed — check your connection"
									: results == null ? "Searching…"
									: results.length ? `${results.length} note${results.length === 1 ? "" : "s"}` : "No matches"}
							</h2>
							{(results || []).map((h) => (
								<button key={h.id} type="button" className={`nt-hit${openNote === h.id ? " on" : ""}`} onClick={() => openHit(h)}>
									<span className="nt-hit-title">{hitTitle(h)}</span>
									<span className="nt-hit-path">{h.folder_id && folderById.has(h.folder_id) ? folderPath(h.folder_id) : "Top level"}
										{h.count > 0 && ` · ${h.count} match${h.count === 1 ? "" : "es"}`}</span>
									{h.snippets.slice(0, 2).map(snippet)}
								</button>
							))}
						</section>
					) : (<>

					{pinned.length > 0 && (
						<section className="nt-sec">
							<h2 className="nt-sec-hd"><span className="nt-ic">{I.pin}</span>Pinned</h2>
							{pinned.map((n) => noteRow(n, 0, "pinned"))}
						</section>
					)}

					{recent.length > 0 && (
						<section className="nt-sec">
							<h2 className="nt-sec-hd"><span className="nt-ic">{I.clock}</span>Recent</h2>
							{recent.map((n) => noteRow(n, 0, "recent"))}
						</section>
					)}

					{tree && (
						<section className="nt-sec">
							<div className={`nt-sec-hd nt-sec-hd-row${dropOn === "root" ? " drop" : ""}`} {...dropProps("root", null)}>
								<h2 className="nt-sec-hd-in"><span className="nt-ic">{I.folder}</span>Folders</h2>
								<button type="button" className="nt-sort" onClick={() => setSort(sort === "title" ? "edited" : "title")}
									title="Sort notes inside folders">{sort === "title" ? "A–Z" : "Last edited"}</button>
							</div>
							{!folders.length && !notesIn(null).length
								? <div className="nt-side-note">No notes yet. Make a folder for a topic — say, one per game — and add notes to it.</div>
								: branch(null, 0)}
						</section>
					)}

					{tree && (
						<button type="button" className={`nt-row-main nt-trash-link${trashView ? " on" : ""}`} onClick={() => go(TRASH)}>
							<span className="nt-ic">{I.trash}</span>
							<span className="nt-row-text"><span className="nt-row-title">Trash</span></span>
							{trashed.length > 0 && <span className="nt-count">{trashed.length}</span>}
						</button>
					)}
					{usage?.quota_bytes > 0 && (() => {
						const frac = Math.min(1, usage.bytes / usage.quota_bytes);
						return (
							<div className={`nt-usage${frac >= 0.9 ? " full" : ""}`}>
								<div className="nt-usage-bar" role="meter" aria-label="Storage used"
									aria-valuemin={0} aria-valuemax={usage.quota_bytes} aria-valuenow={usage.bytes}>
									<span style={{ width: `${Math.max(frac * 100, frac > 0 ? 2 : 0)}%` }} />
								</div>
								<span className="nt-usage-text">{megabytes(usage.bytes)} of {megabytes(usage.quota_bytes)} used</span>
							</div>
						);
					})()}
					</>)}
				</aside>

				<main className="nt-main">
					{showMain && (
						<button type="button" className="nt-mobile-back" onClick={() => go(null)}>
							<span className="nt-ic">{I.back}</span> All notes
						</button>
					)}
					{trashView ? (
						<div className="nt-trash">
							<div className="nt-trash-hd">
								<h2>Trash</h2>
								{trashed.length > 0 && <button type="button" className="btn btn-danger btn-sm" onClick={emptyTrash}>Empty trash</button>}
							</div>
							<p className="nt-dim">Notes stay here for 30 days, then are deleted for good.</p>
							{trashed.length === 0 && <div className="nt-empty">The Trash is empty.</div>}
							<ul className="nt-trash-list">
								{trashed.map((n) => (
									<li key={n.id} className="nt-trash-item">
										<button type="button" className="nt-trash-open" onClick={() => go(n.id)}>
											<span className="nt-row-title">{n.title || "Untitled"}</span>
											<span className="nt-row-sub">
												{n.folder_id && folderById.has(n.folder_id) ? `${folderById.get(n.folder_id).name} · ` : ""}
												deleted {ago(n.deleted_at)}
											</span>
										</button>
										<span className="nt-trash-acts">
											<button type="button" className="btn btn-outline btn-sm" onClick={() => restoreNote(n.id)}>Restore</button>
											<button type="button" className="btn btn-ghost btn-sm" onClick={() => deleteForever(n)}>Delete</button>
										</span>
									</li>
								))}
							</ul>
						</div>
					) : openNote ? (
						<Suspense fallback={<div className="nt-empty nt-loading">Loading…</div>}>
							<NoteEditor key={openNote} api={api} uid={authUser?.id} noteId={openNote} notify={notify} statusSlot={statusSlot}
								focusTitle={freshNote.current === openNote} onTitleFocused={() => { freshNote.current = null; }}
								findRequest={findReq && findReq.id === openNote ? findReq : null}
								nav={{
									notes: live,
									folderPath,
									openNote: (id) => {
										setFindReq(null);
										const m = notes.find((x) => x.id === id);
										if (m) setActiveFolder(m.folder_id);
										go(id);
									},
									searchAll: (text) => {
										setScope(null);
										setQuery(text);
										// on a narrow window the list is hidden while a note is open
										if (window.matchMedia("(max-width: 760px)").matches) go(null);
										setTimeout(() => searchBox.current?.focus(), 0);
									},
									noteCreated: (n) => { patchNote(n); if (n.folder_id) expandTo(n.folder_id); },
									folderOf: () => notes.find((x) => x.id === openNote)?.folder_id ?? null,
								}}
								onSaved={patchNote} flushRef={flushOpen}
								onGone={() => { notify("This note was deleted or moved to the Trash elsewhere."); load(); }}
								onRestore={restoreNote} />
						</Suspense>
					) : (
						<div className="nt-empty nt-welcome">
							<p>Pick a note, or start a new one.</p>
							<button type="button" className="btn btn-outline btn-sm" onClick={() => newNote()} disabled={access !== "ok"}>
								{I.plus} New note
							</button>
						</div>
					)}
				</main>
			</div>

			{moving && (
				<MoveDialog
					title={moving.kind === "note" ? "Move note to…" : "Move folder to…"}
					folders={folders} disabled={moveDisabled} current={moveCurrent}
					onClose={() => setMoving(null)}
					onPick={(fid) => {
						const m = moving;
						setMoving(null);
						if (m.kind === "note") moveNote(m.id, fid); else moveFolder(m.id, fid);
					}} />
			)}
			{menu && <ContextMenu x={menu.x} y={menu.y} items={menu.items} onClose={() => setMenu(null)} />}
			{toast && <div className="nt-toast" role="status">{toast}</div>}
		</div>
	);
}

function pickMeta(n) {
	const { id, folder_id, title, pinned, created_at, updated_at, deleted_at } = n;
	return { id, folder_id, title, pinned, created_at, updated_at, deleted_at };
}
