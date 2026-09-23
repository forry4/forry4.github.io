import { lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "../shared/theme.js";
import { buildPath, parsePath, pushPath, subscribe } from "../shared/router.js";
import { makeApi } from "./api.js";
import { I } from "./icons.jsx";

// CSS in a real .css file, imported ?inline and injected by this component's own
// <style> tag while it is mounted (see the root CLAUDE.md: never a JS template literal).
import css from "./Notes.css?inline";

// The editor (TipTap/ProseMirror) is the heavy half of this page; splitting it keeps
// the sidebar and the "private" screen fast, and a visitor who is not the owner never
// downloads an editor at all.
const NoteEditor = lazy(() => import("./NoteEditor.jsx"));

// Segment 2 of /notes/<x> is either a note id or "trash". router.js upper-cases
// segment 2 (it was written for room codes); note ids are lowercase [a-z0-9], so
// lower-casing it back is exact.
const TRASH = "trash";
const routeTarget = () => (parsePath().room || "").toLowerCase() || null;

const RECENT_COUNT = 6;

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
function RowMenu({ items, onClose }) {
	const ref = useRef(null);
	useEffect(() => {
		const down = (e) => { if (ref.current && !ref.current.contains(e.target)) onClose(); };
		const key = (e) => { if (e.key === "Escape") onClose(); };
		document.addEventListener("pointerdown", down);
		document.addEventListener("keydown", key);
		ref.current?.querySelector("button")?.focus();
		return () => { document.removeEventListener("pointerdown", down); document.removeEventListener("keydown", key); };
	}, [onClose]);
	return (
		<div className="nt-menu" role="menu" ref={ref}>
			{items.filter(Boolean).map(([label, fn, danger]) => (
				<button key={label} type="button" role="menuitem" className={danger ? "danger" : ""}
					onClick={() => { onClose(); fn(); }}>{label}</button>
			))}
		</div>
	);
}

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

// ─── the page ─────────────────────────────────────────────────────────────────
export default function Notes({ authUser, onExit }) {
	const token = authUser?.session_token || null;
	const api = useMemo(() => makeApi(token), [token]);
	const cacheKey = `notes.tree.${authUser?.id || "anon"}`;

	// Stale-while-revalidate: the sidebar paints from the last tree this browser saw
	// while the (possibly cold) backend answers.
	const [tree, setTree] = useState(() => readLS(cacheKey, null));
	const [access, setAccess] = useState(token ? "loading" : "denied");   // loading | ok | denied | offline
	const [target, setTarget] = useState(routeTarget);
	const [expanded, setExpanded] = useState(() => new Set(readLS("notes.expanded", [])));
	const [sort, setSort] = useState(() => readLS("notes.sort", "edited"));
	const [activeFolder, setActiveFolder] = useState(null);
	const [menu, setMenu] = useState(null);         // "n:<id>" | "f:<id>"
	const [renaming, setRenaming] = useState(null); // folder id
	const [moving, setMoving] = useState(null);     // { kind: "note"|"folder", id }
	const [dropOn, setDropOn] = useState(null);     // folder id | "root"
	const [toast, setToast] = useState("");
	const toastTimer = useRef(null);
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
			writeLS(cacheKey, next);
			setAccess("ok");
		} catch (e) {
			setAccess(e.status === 401 || e.status === 403 ? "denied" : "offline");
		}
	}, [api, token, cacheKey]);

	useEffect(() => { load(); }, [load]);
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

	const openNote = target && target !== TRASH ? target : null;
	const openMeta = openNote ? notes.find((n) => n.id === openNote) : null;
	// New notes land in the folder you are looking at.
	const newNoteFolder = activeFolder && folderById.has(activeFolder) ? activeFolder
		: (openMeta?.folder_id && folderById.has(openMeta.folder_id) ? openMeta.folder_id : null);

	// ── mutations ──
	const patchNote = (n) => setTree((t) => t && ({ ...t, notes: t.notes.some((x) => x.id === n.id)
		? t.notes.map((x) => (x.id === n.id ? { ...x, ...pickMeta(n) } : x))
		: [pickMeta(n), ...t.notes] }));
	const fail = (e) => notify(e.status === undefined ? "Can't reach the server — try again in a moment." : e.message);

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
			// The title field is the first thing a new note wants.
			setTimeout(() => document.querySelector(".nt-title")?.focus(), 250);
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
	const trashNote = async (n) => {
		try {
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
		} catch (e) { fail(e); }
	};
	const emptyTrash = async () => {
		if (!window.confirm(`Delete all ${trashed.length} notes in the Trash forever?`)) return;
		try {
			await api.emptyTrash();
			setTree((t) => ({ ...t, notes: t.notes.filter((x) => x.deleted_at == null) }));
		} catch (e) { fail(e); }
	};
	const deleteFolder = async (f) => {
		const n = countIn(f.id);
		const msg = n
			? `Delete “${f.name}”? Its ${n} note${n === 1 ? "" : "s"} will move to the Trash.`
			: `Delete the empty folder “${f.name}”?`;
		if (!window.confirm(msg)) return;
		try {
			await api.deleteFolder(f.id);
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
			<div key={key} className={`nt-row nt-note-row${where === "tree" ? " in-tree" : ""}${openNote === n.id ? " on" : ""}`} style={{ "--depth": depth }}>
				<button type="button" className="nt-row-main" draggable onDragStart={(e) => dragData(e, "note", n.id)}
					onClick={() => { setActiveFolder(n.folder_id); go(n.id); }}>
					<span className="nt-ic">{I.note}</span>
					<span className="nt-row-text">
						<span className="nt-row-title">{n.title || "Untitled"}</span>
						<span className="nt-row-sub">{ago(n.updated_at)}</span>
					</span>
					{n.pinned && where !== "pinned" && <span className="nt-ic nt-pin-mark" title="Pinned">{I.pin}</span>}
				</button>
				<button type="button" className="nt-row-more" aria-label={`More for ${n.title || "Untitled"}`}
					aria-haspopup="menu" aria-expanded={menu === key} onClick={() => setMenu(menu === key ? null : key)}>{I.dots}</button>
				{menu === key && (
					<RowMenu onClose={() => setMenu(null)} items={[
						[n.pinned ? "Unpin" : "Pin to top", () => togglePin(n)],
						["Move to…", () => setMoving({ kind: "note", id: n.id })],
						["Move to Trash", () => trashNote(n), true],
					]} />
				)}
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
					style={{ "--depth": depth }} {...dropProps(f.id, f.id)}>
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
						aria-haspopup="menu" aria-expanded={menu === key} onClick={() => setMenu(menu === key ? null : key)}>{I.dots}</button>
					{menu === key && (
						<RowMenu onClose={() => setMenu(null)} items={[
							["New note here", () => newNote(f.id)],
							["New folder inside", () => newFolder(f.id)],
							["Rename", () => setRenaming(f.id)],
							["Move to…", () => setMoving({ kind: "folder", id: f.id })],
							["Delete folder", () => deleteFolder(f), true],
						]} />
					)}
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

	// ── screens ──
	if (access === "denied") return (
		<div className="nt-app nt-private">
			<style>{baseCss + css}</style>
			<header className="nt-header">
				<button type="button" className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
				<div className="nt-headtitle">Notes</div>
			</header>
			<div className="nt-empty">
				<p>Notes are private to the site owner.</p>
				{(!authUser || authUser.guest) && <p className="nt-dim">Sign in with the owner account to open them.</p>}
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

					{!tree && access === "loading" && <div className="nt-side-note">Loading…</div>}

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
							<NoteEditor key={openNote} api={api} noteId={openNote} notify={notify} statusSlot={statusSlot}
								onSaved={patchNote}
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
			{toast && <div className="nt-toast" role="status">{toast}</div>}
		</div>
	);
}

function pickMeta(n) {
	const { id, folder_id, title, pinned, created_at, updated_at, deleted_at } = n;
	return { id, folder_id, title, pinned, created_at, updated_at, deleted_at };
}
