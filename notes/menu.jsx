// The right-click menu (editor + sidebar) and the note picker used to link notes.
//
// A menu is a list of items: { label, onSelect, hint, danger, disabled, checked,
// children } or "-" for a separator. `children` makes a flyout submenu. It renders in
// a portal at fixed coordinates, is clamped inside the viewport, and closes on a click
// outside, Escape, scroll, resize or window blur. Keyboard: arrows move, Enter/Space
// choose, → opens a submenu, ← / Escape closes it.
import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { I } from "./icons.jsx";

const CHEVRON = <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="1.8"
	strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M9.5 6.5 15 12l-5.5 5.5" /></svg>;
const TICK = <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" strokeWidth="2"
	strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="m5.5 12.5 4 4 9-9" /></svg>;

function MenuList({ items, x, y, onClose, onBack, level, flipX }) {
	const ref = useRef(null);
	const [pos, setPos] = useState({ left: x, top: y, ready: false });
	const [open, setOpen] = useState(-1);      // index of the open submenu
	const [sub, setSub] = useState(null);      // { x, y, flip } for it
	const btns = useRef([]);
	const list = items.filter(Boolean);

	// Clamp into the viewport once the menu's size is known; a submenu that would run
	// off the right edge opens to the LEFT of its parent instead.
	useLayoutEffect(() => {
		const r = ref.current.getBoundingClientRect();
		const vw = window.innerWidth, vh = window.innerHeight;
		let left = flipX ? x - r.width : x;
		if (left + r.width > vw - 6) left = vw - r.width - 6;
		left = Math.max(6, left);
		const top = Math.max(6, Math.min(y, vh - r.height - 6));
		setPos({ left, top, ready: true });
	}, [x, y, flipX, level]);

	// Focus the first item once the menu is VISIBLE: it renders hidden for one frame
	// while it measures itself, and a visibility:hidden button cannot take focus — which
	// left focus in the editor, so arrows and Escape did nothing.
	useEffect(() => {
		if (!pos.ready) return;
		const first = btns.current.find((b) => b && !b.disabled);
		first?.focus({ preventScroll: true });
	}, [pos.ready]);

	const openSub = (i) => {
		const b = btns.current[i];
		if (!b) return;
		const r = b.getBoundingClientRect();
		const flip = r.right + 230 > window.innerWidth;
		setSub({ x: flip ? r.left : r.right - 2, y: r.top - 5, flip });
		setOpen(i);
	};
	const activate = (it, i) => {
		if (it.disabled) return;
		if (it.children) { openSub(i); return; }
		onClose();
		it.onSelect?.();
	};
	const move = (d) => {
		const idx = btns.current.map((b, i) => (b && !b.disabled ? i : -1)).filter((i) => i >= 0);
		const cur = idx.indexOf(btns.current.indexOf(document.activeElement));
		const next = idx[(cur + d + idx.length) % idx.length];
		btns.current[next]?.focus({ preventScroll: true });
	};
	const onKey = (e) => {
		if (e.key === "ArrowDown") { e.preventDefault(); e.stopPropagation(); move(1); }
		else if (e.key === "ArrowUp") { e.preventDefault(); e.stopPropagation(); move(-1); }
		else if (e.key === "ArrowRight") {
			e.preventDefault(); e.stopPropagation();
			const i = btns.current.indexOf(document.activeElement);
			if (list[i]?.children) openSub(i);
		} else if (e.key === "ArrowLeft" && level) { e.preventDefault(); e.stopPropagation(); onBack(); }
		else if (e.key === "Escape") { e.preventDefault(); e.stopPropagation(); level ? onBack() : onClose(); }
	};

	btns.current = [];
	return (
		<>
			<div ref={ref} className="nt-cmenu" role="menu" onKeyDown={onKey}
				style={{ left: pos.left, top: pos.top, visibility: pos.ready ? "visible" : "hidden" }}
				onContextMenu={(e) => e.preventDefault()}>
				{list.map((it, i) => (it === "-"
					? <div key={`s${i}`} className="nt-cmenu-sep" role="separator" />
					: (
						<button key={it.label} type="button" role="menuitem" ref={(el) => { btns.current[i] = el; }}
							className={`nt-cmenu-it${it.danger ? " danger" : ""}${open === i ? " open" : ""}`}
							disabled={it.disabled} aria-haspopup={it.children ? "menu" : undefined}
							aria-expanded={it.children ? open === i : undefined}
							// mousedown must not move focus: the editor's selection is what
							// Cut / Copy / Bold act on, and a focused button would lose it
							onMouseDown={(e) => e.preventDefault()}
							onMouseEnter={() => { if (it.children) openSub(i); else if (open !== -1) setOpen(-1); }}
							onClick={() => activate(it, i)}>
							<span className="nt-cmenu-tick">{it.checked ? TICK : null}</span>
							<span className="nt-cmenu-label">{it.label}</span>
							{it.hint && <span className="nt-cmenu-hint">{it.hint}</span>}
							{it.children && <span className="nt-cmenu-more">{CHEVRON}</span>}
						</button>
					)))}
			</div>
			{open !== -1 && sub && list[open]?.children && (
				<MenuList items={list[open].children} x={sub.x} y={sub.y} flipX={sub.flip} level={level + 1}
					onClose={onClose} onBack={() => { const i = open; setOpen(-1); btns.current[i]?.focus(); }} />
			)}
		</>
	);
}

export function ContextMenu({ x, y, items, onClose }) {
	useEffect(() => {
		const down = (e) => { if (!e.target.closest?.(".nt-cmenu")) onClose(); };
		// A scroll closes the menu — but not one already in flight when it opened: scroll
		// events arrive a frame late, so the page settling (or scrolling the clicked line
		// into view) used to close the menu the instant it appeared.
		const opened = performance.now();
		const scroll = (e) => {
			if (performance.now() - opened < 300) return;
			if (!e.target?.closest?.(".nt-cmenu")) onClose();
		};
		// Escape closes from anywhere, not only while a menu item has focus.
		const key = (e) => { if (e.key === "Escape" && !e.target?.closest?.(".nt-cmenu")) onClose(); };
		document.addEventListener("keydown", key);
		document.addEventListener("pointerdown", down, true);
		window.addEventListener("scroll", scroll, true);
		window.addEventListener("resize", onClose);
		window.addEventListener("blur", onClose);
		return () => {
			document.removeEventListener("pointerdown", down, true);
			document.removeEventListener("keydown", key);
			window.removeEventListener("scroll", scroll, true);
			window.removeEventListener("resize", onClose);
			window.removeEventListener("blur", onClose);
		};
	}, [onClose]);
	return createPortal(<MenuList items={items} x={x} y={y} onClose={onClose} level={0} />, document.body);
}

// ── note picker ───────────────────────────────────────────────────────────────
// Choose a note to link to, by title. Offers to CREATE a note with the typed title
// when nothing matches exactly — the wiki habit of linking a page before writing it.
export function NotePicker({ title, notes, folderPath, excludeId, onPick, onCreate, onClose }) {
	const [q, setQ] = useState("");
	const [hi, setHi] = useState(0);
	const input = useRef(null);
	useEffect(() => { input.current?.focus(); }, []);
	const rows = useMemo(() => {
		const t = q.trim().toLowerCase();
		const list = notes.filter((n) => n.deleted_at == null && n.id !== excludeId
			&& (!t || (n.title || "Untitled").toLowerCase().includes(t)))
			.sort((a, b) => (b.updated_at || 0) - (a.updated_at || 0)).slice(0, 50)
			.map((n) => ({ kind: "note", n }));
		const exact = list.some((r) => (r.n.title || "").toLowerCase() === t);
		if (t && !exact && onCreate) list.push({ kind: "create", title: q.trim() });
		return list;
	}, [q, notes, excludeId, onCreate]);
	useEffect(() => { setHi(0); }, [q]);
	const choose = (r) => { if (!r) return; if (r.kind === "create") onCreate(r.title); else onPick(r.n); };
	return createPortal(
		<div className="nt-modal-back" onPointerDown={(e) => e.target === e.currentTarget && onClose()}>
			<div className="nt-modal nt-picker" role="dialog" aria-label={title}>
				<div className="nt-modal-hd">{title}</div>
				<div className="nt-picker-q">
					<span className="nt-ic">{I.search}</span>
					<input ref={input} value={q} placeholder="Find a note by title…" aria-label="Note title"
						autoComplete="off" spellCheck={false} onChange={(e) => setQ(e.target.value)}
						onKeyDown={(e) => {
							if (e.key === "ArrowDown") { e.preventDefault(); setHi((h) => Math.min(rows.length - 1, h + 1)); }
							if (e.key === "ArrowUp") { e.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
							if (e.key === "Enter") { e.preventDefault(); choose(rows[hi]); }
							if (e.key === "Escape") { e.preventDefault(); onClose(); }
						}} />
				</div>
				<div className="nt-modal-list" role="listbox">
					{rows.length === 0 && <div className="nt-side-note">No notes match.</div>}
					{rows.map((r, i) => (
						<button key={r.kind === "note" ? r.n.id : "create"} type="button" role="option" aria-selected={i === hi}
							className={`nt-move-row nt-pick-row${i === hi ? " hi" : ""}`}
							onMouseEnter={() => setHi(i)} onClick={() => choose(r)}>
							<span className="nt-ic">{r.kind === "note" ? I.note : I.plus}</span>
							{r.kind === "note" ? (
								<span className="nt-pick-text">
									<span className="nt-row-title">{r.n.title || "Untitled"}</span>
									<span className="nt-row-sub">{r.n.folder_id ? folderPath(r.n.folder_id) : "Top level"}</span>
								</span>
							) : <span className="nt-pick-text"><span className="nt-row-title">Create “{r.title}”</span></span>}
						</button>
					))}
				</div>
				<div className="nt-modal-ft">
					<button type="button" className="btn btn-ghost btn-sm" onClick={onClose}>Cancel</button>
				</div>
			</div>
		</div>,
		document.body,
	);
}
