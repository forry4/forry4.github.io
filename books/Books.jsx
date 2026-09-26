import { useState, useEffect, useRef } from "react";
import { baseCss } from "../shared/theme.js";

// CSS lives in the sibling .css file(s) imported below, NOT in a JS template
// literal. `?inline` hands us the stylesheet as a STRING, so it is still injected
// by this component's own <style> tag only while it is mounted — behaviour is
// unchanged. What goes away is the footgun: a single stray backtick inside a css
// template literal silently reparsed the rest of the file as a tagged template and
// blanked the whole page. A .css file cannot do that, and editors lint it properly.
import _cssText from "./Books.css?inline";

// ─── Config ────────────────────────────────────────────────────────────────
// Derive the HTTP base the same way Spender.jsx does, so dev (localhost:8000)
// and prod (Render) both work without extra config.
const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

const RATINGS = [5, 4, 3, 2, 1];
const newId = () => "new_" + Math.random().toString(36).slice(2, 9);
const coverUrl = (id, size) => id
	? `https://covers.openlibrary.org/b/id/${id}-${size}.jpg?default=false`
	: "";

// Open Library covers are served through TWO 302 redirects (-> archive.org) and cached
// for only 3 hours, so they re-fetch slowly every few hours. A bookshelf is stable, so we
// bake each cover into the saved record once: fetch it (CORS is open: ACAO *), downscale to
// the small size it's shown at, and store it as a self-contained data: URI in cover_url.
// Saved covers then render instantly from the list payload with no external request.
// Any failure (offline / a host without CORS) falls back to keeping the original URL.
const COVER_MAX_W = 128, COVER_MAX_H = 192;
async function inlineCover(url) {
	if (!url || url.startsWith("data:")) return url || "";
	try {
		const res = await fetch(url, { mode: "cors" });
		if (!res.ok) return url;
		const bmp = await createImageBitmap(await res.blob());
		const scale = Math.min(1, COVER_MAX_W / bmp.width, COVER_MAX_H / bmp.height);
		const w = Math.max(1, Math.round(bmp.width * scale));
		const h = Math.max(1, Math.round(bmp.height * scale));
		const canvas = document.createElement("canvas");
		canvas.width = w; canvas.height = h;
		canvas.getContext("2d").drawImage(bmp, 0, 0, w, h);
		bmp.close && bmp.close();
		return canvas.toDataURL("image/jpeg", 0.82);
	} catch {
		return url;  // keep the remote URL if we can't inline it
	}
}

// ─── The offline copy ──────────────────────────────────────────────────────
// The last list (and this reader's own suggestions) this browser loaded, for the
// offline hub's Read section. Covers are already inlined data URIs (above), so the
// copy is complete. A screen showing it is READ-ONLY: editing needs the server.
// The key is also read by the hub (Spender.jsx offlineReadRows) to say whether a
// copy exists — keep them in step.
const OFFLINE_KEY = "books.offline.v1";
function readOfflineCopy() {
	try { return JSON.parse(localStorage.getItem(OFFLINE_KEY) || "null"); } catch { return null; }
}
function writeOfflineCopy(patch) {
	const next = { ...(readOfflineCopy() || {}), ...patch, savedAt: Date.now() };
	try { localStorage.setItem(OFFLINE_KEY, JSON.stringify(next)); }
	catch { /* over quota — the copy is a convenience, never worth an error */ }
}

/** Take a copy now, without opening the screen (the offline hub's Reading download). */
export async function saveOfflineCopy(authUser) {
	const token = authUser?.session_token || null;
	const headers = token ? { Authorization: `Bearer ${token}` } : {};
	const [b, sg] = await Promise.all([
		fetch(`${HTTP_BASE}/books`, { headers }).then((r) => r.json()),
		fetch(`${HTTP_BASE}/books/suggestions`, { headers }).then((r) => r.json()).catch(() => null),
	]);
	if (!b?.ok) return;
	writeOfflineCopy({
		books: b.books || [],
		...(sg?.ok ? { sugg: { uid: authUser?.id || null, mine: sg.mine || [], all: sg.all || [],
			info: { is_owner: !!sg.is_owner, logged_in: !!sg.logged_in, max: sg.max || 10 } } } : {}),
	});
}

function Stars({ value }) {
	return (
		<span className="bk-stars" aria-label={`${value} out of 5 stars`}>
			{[1, 2, 3, 4, 5].map(n => (
				<span key={n} className={n <= value ? "bk-star on" : "bk-star"}>★</span>
			))}
		</span>
	);
}

// Reusable debounced Open Library search. Open Library is free, keyless and
// CORS-enabled, so we query it straight from the browser. Calls onPick(result)
// when a result is chosen, then clears itself.
function BookSearch({ onPick, placeholder }) {
	const [query, setQuery] = useState("");
	const [results, setResults] = useState([]);
	const [searching, setSearching] = useState(false);
	const [error, setError] = useState("");

	useEffect(() => {
		const q = query.trim();
		if (q.length < 3) { setResults([]); setSearching(false); setError(""); return; }
		const ctrl = new AbortController();
		let timedOut = false;
		setSearching(true);
		setError("");
		const t = setTimeout(async () => {
			// Open Library is keyless but can be slow/flaky; cap the request so a hung
			// fetch can't leave the UI stuck on "Searching…" forever (it has no timeout of its own).
			const guard = setTimeout(() => { timedOut = true; ctrl.abort(); }, 12000);
			let superseded = false;
			try {
				const url = `https://openlibrary.org/search.json?q=${encodeURIComponent(q)}`
					+ `&limit=8&fields=key,title,author_name,cover_i,first_publish_year`;
				const res = await fetch(url, { signal: ctrl.signal });
				const data = await res.json();
				setResults((data.docs || []).slice(0, 8));
			} catch (e) {
				if (e.name === "AbortError" && !timedOut) { superseded = true; return; }  // newer keystroke owns it
				setResults([]);
				setError(timedOut ? "Open Library is slow right now — try again."
					: "Couldn't reach Open Library — check your connection and try again.");
			} finally {
				clearTimeout(guard);
				if (!superseded) setSearching(false);
			}
		}, 300);
		return () => { ctrl.abort(); clearTimeout(t); };
	}, [query]);

	const pick = (r) => { onPick(r); setQuery(""); setResults([]); };

	return (
		<div className="bk-search">
			<input className="bk-in bk-search-in" placeholder={placeholder || "Search a book…"}
				value={query} onChange={(e) => setQuery(e.target.value)} />
			{(searching || error || results.length > 0) && (
				<div className="bk-results">
					{searching && <div className="bk-result-hint">Searching…</div>}
					{!searching && error && <div className="bk-result-hint">{error}</div>}
					{!searching && !error && results.length === 0 && <div className="bk-result-hint">No matches</div>}
					{results.map(r => (
						<button type="button" key={r.key} className="bk-result" onClick={() => pick(r)}>
							{r.cover_i
								? <img className="bk-result-cover" src={coverUrl(r.cover_i, "S")}
									alt="" onError={(e) => { e.currentTarget.style.visibility = "hidden"; }} />
								: <span className="bk-result-cover bk-cover-blank">📖</span>}
							<span className="bk-result-text">
								<span className="bk-result-title">{r.title}</span>
								<span className="bk-result-sub">
									{(r.author_name && r.author_name[0]) || "Unknown"}
									{r.first_publish_year ? ` · ${r.first_publish_year}` : ""}
								</span>
							</span>
						</button>
					))}
				</div>
			)}
		</div>
	);
}

// Read-only ranked list of suggestion cards (used in both the owner's all-view
// and a user's own read view).
function SuggestionList({ items }) {
	return (
		<ol className="bk-cards">
			{items.map((s, i) => (
				<li key={s.id} className="bk-card">
					<span className="bk-rank">{i + 1}</span>
					{s.cover_url
						? <img className="bk-cover" src={s.cover_url} alt=""
							onError={(e) => { e.currentTarget.style.display = "none"; }} />
						: <span className="bk-cover bk-cover-blank">📖</span>}
					<div className="bk-meta">
						<div className="bk-title">{s.title}</div>
						{s.author && <div className="bk-author">{s.author}</div>}
						{s.blurb && <div className="bk-note">{s.blurb}</div>}
					</div>
				</li>
			))}
		</ol>
	);
}

// The Books page the shell mounts on `screen === "books"`.
// Two sections: the owner's public ranking, and per-user suggestions FOR the
// owner. Props: { authUser, onExit }.
export default function Books({ authUser, onExit }) {
	// ── ranking state ──
	const [books, setBooks] = useState([]);      // flat array, in display order
	const [canEdit, setCanEdit] = useState(false);
	const [loading, setLoading] = useState(true);
	const [editing, setEditing] = useState(false);
	const [saving, setSaving] = useState(false);
	const rankSnap = useRef(null);
	const rankDrag = useRef(null);

	// ── suggestions state ──
	const [sugg, setSugg] = useState([]);        // my own suggestions
	const [allSugg, setAllSugg] = useState([]);  // everyone's (owner only)
	const [suggInfo, setSuggInfo] = useState(null); // {is_owner, logged_in, max}
	const [suggEditing, setSuggEditing] = useState(false);
	const [suggSaving, setSuggSaving] = useState(false);
	const suggSnap = useRef(null);
	const suggDrag = useRef(null);
	const [dragOverId, setDragOverId] = useState(null);  // row currently under the drag (visual cue)

	const [toast, setToast] = useState("");
	// Set (to the copy's timestamp) when the server could not be reached and the page is
	// showing the offline copy instead — which also turns every editing control off.
	const [offlineAt, setOfflineAt] = useState(null);

	const token = authUser?.session_token || null;
	// Send the session token in the Authorization header (keeps it out of URLs/logs);
	// the backend still accepts ?token= as a fallback for older clients.
	const authHeaders = token ? { Authorization: `Bearer ${token}` } : {};
	const maxSugg = suggInfo?.max || 10;

	// ── data load ──
	useEffect(() => {
		let cancelled = false;
		(async () => {
			try {
				const res = await fetch(`${HTTP_BASE}/books`, { headers: authHeaders });
				const data = await res.json();
				if (cancelled) return;
				if (data.ok) {
					setBooks(data.books || []); setCanEdit(!!data.can_edit);
					writeOfflineCopy({ books: data.books || [] });
				}
			} catch {
				// No server: show the copy this browser kept, read-only.
				const copy = readOfflineCopy();
				if (!cancelled && copy?.books) { setBooks(copy.books); setCanEdit(false); setOfflineAt(copy.savedAt || Date.now()); }
			}
			finally { if (!cancelled) setLoading(false); }
		})();
		return () => { cancelled = true; };
	}, [token]);

	useEffect(() => {
		let cancelled = false;
		(async () => {
			try {
				const res = await fetch(`${HTTP_BASE}/books/suggestions`, { headers: authHeaders });
				const data = await res.json();
				if (cancelled || !data.ok) return;
				setSugg(data.mine || []);
				setAllSugg(data.all || []);
				const info = { is_owner: !!data.is_owner, logged_in: !!data.logged_in, max: data.max || 10 };
				setSuggInfo(info);
				writeOfflineCopy({ sugg: { uid: authUser?.id || null, mine: data.mine || [], all: data.all || [], info } });
			} catch {
				// Only THIS reader's copy: suggestions are per account.
				const copy = readOfflineCopy()?.sugg;
				if (cancelled || !copy || copy.uid !== (authUser?.id || null)) return;
				setSugg(copy.mine || []); setAllSugg(copy.all || []); setSuggInfo(copy.info || null);
				setOfflineAt((at) => at || readOfflineCopy()?.savedAt || Date.now());   // read-only either way
			}
		})();
		return () => { cancelled = true; };
	}, [token]);

	const showToast = (m) => setToast(m);
	// Auto-dismiss with a TRACKED timer: a raw setTimeout per toast let an earlier
	// timer clear a newer message early (and could setState after unmount). Re-armed
	// whenever `toast` changes; cleared on change/unmount.
	useEffect(() => {
		if (!toast) return;
		const t = setTimeout(() => setToast(""), 2500);
		return () => clearTimeout(t);
	}, [toast]);

	// ── ranking edit ops ──
	const startEdit = () => { rankSnap.current = JSON.parse(JSON.stringify(books)); setEditing(true); };
	const cancelEdit = () => { setBooks(rankSnap.current || []); setEditing(false); };
	const addBook = () => setBooks(b => [
		...b, { id: newId(), title: "", author: "", rating: 5, note: "", cover_url: "" },
	]);
	const addFromSearch = (r) => {
		setBooks(b => [...b, {
			id: newId(), title: r.title || "",
			author: (r.author_name && r.author_name[0]) || "",
			rating: 5, note: "", cover_url: coverUrl(r.cover_i, "M"),
		}]);
		showToast(`Added “${r.title}” at 5★ — set its rating`);
	};
	const updateBook = (id, patch) => setBooks(b => b.map(x => x.id === id ? { ...x, ...patch } : x));
	const removeBook = (id) => setBooks(b => b.filter(x => x.id !== id));
	// Changing a rating moves the book to the end of its array, so within the new
	// star tier it lands predictably at the bottom (then can be dragged up).
	const changeRating = (id, rating) => setBooks(b => {
		const item = b.find(x => x.id === id);
		if (!item) return b;
		return [...b.filter(x => x.id !== id), { ...item, rating }];
	});

	const save = async () => {
		setSaving(true);
		try {
			// Bake any remote covers into the records (downscaled data: URIs) so they load
			// instantly next time instead of re-fetching through Open Library's redirects.
			const inlined = await Promise.all(books.map(async b =>
				({ ...b, cover_url: await inlineCover(b.cover_url) })));
			setBooks(inlined);
			const payload = {
				books: inlined.map(({ id, title, author, rating, note, cover_url }) =>
					({ id, title, author, rating, note, cover_url })),
			};
			const res = await fetch(`${HTTP_BASE}/books`, {
				method: "PUT", headers: { "Content-Type": "application/json", ...authHeaders },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (data.ok) { setBooks(data.books || []); setEditing(false); showToast("Saved"); }
			else showToast(data.message === "not the owner" ? "Only the owner can edit"
				: data.message || "Save failed");
		} catch { showToast("Save failed"); }
		finally { setSaving(false); }
	};

	// ── suggestion edit ops ──
	const startSuggEdit = () => { suggSnap.current = JSON.parse(JSON.stringify(sugg)); setSuggEditing(true); };
	const cancelSuggEdit = () => { setSugg(suggSnap.current || []); setSuggEditing(false); };
	const atCap = () => {
		if (sugg.length >= maxSugg) { showToast(`You can suggest up to ${maxSugg} books`); return true; }
		return false;
	};
	const addSuggBlank = () => { if (!atCap()) setSugg(s => [...s, { id: newId(), title: "", author: "", cover_url: "", blurb: "" }]); };
	const addSuggFromSearch = (r) => {
		if (atCap()) return;
		setSugg(s => [...s, {
			id: newId(), title: r.title || "",
			author: (r.author_name && r.author_name[0]) || "",
			cover_url: coverUrl(r.cover_i, "M"), blurb: "",
		}]);
	};
	const updateSugg = (id, patch) => setSugg(s => s.map(x => x.id === id ? { ...x, ...patch } : x));
	const removeSugg = (id) => setSugg(s => s.filter(x => x.id !== id));

	const saveSugg = async () => {
		setSuggSaving(true);
		try {
			const inlined = await Promise.all(sugg.map(async s =>
				({ ...s, cover_url: await inlineCover(s.cover_url) })));
			setSugg(inlined);
			const payload = {
				suggestions: inlined.map(({ id, title, author, cover_url, blurb }) =>
					({ id, title, author, cover_url, blurb })),
			};
			const res = await fetch(`${HTTP_BASE}/books/suggestions`, {
				method: "PUT", headers: { "Content-Type": "application/json", ...authHeaders },
				body: JSON.stringify(payload),
			});
			const submitted = sugg.filter(s => (s.title || "").trim()).length;
			const data = await res.json();
			if (data.ok) {
				const saved = data.mine || [];
				setSugg(saved); setSuggEditing(false);
				if (saved.length < submitted)
					showToast(`Saved ${saved.length} — the site's ${data.max_total || 100}-suggestion limit was reached`);
				else showToast("Suggestions saved");
			}
			else showToast(data.message || "Save failed");
		} catch { showToast("Save failed"); }
		finally { setSuggSaving(false); }
	};

	// ── shared drag reorder (works on any [items,setItems] keyed by id) ──
	const makeDrop = (ref, setItems, sameGroup) => (targetId) => {
		const from = ref.current; ref.current = null;
		if (!from || from === targetId) return;
		setItems(arrIn => {
			const arr = [...arrIn];
			const fi = arr.findIndex(x => x.id === from);
			const ti = arr.findIndex(x => x.id === targetId);
			if (fi < 0 || ti < 0) return arrIn;
			if (sameGroup && arr[fi].rating !== arr[ti].rating) return arrIn; // tier-locked
			const [moved] = arr.splice(fi, 1);
			// Insert AFTER the target when dragging downward (source was above it), BEFORE when
			// dragging upward — else a downward drop re-inserts before the target and nothing
			// visibly moves (the source was already above it).
			let at = arr.findIndex(x => x.id === targetId);
			if (fi < ti) at += 1;
			arr.splice(at, 0, moved);
			return arr;
		});
	};
	const onRankDrop = makeDrop(rankDrag, setBooks, true);
	const onSuggDrop = makeDrop(suggDrag, setSugg, false);

	// ── ▲/▼ reorder buttons (native drag-and-drop doesn't work on touch, and is fiddly
	//    on desktop — buttons give a precise, mobile-friendly way to nudge order). ──
	const moveBook = (id, dir) => setBooks(b => {
		const arr = [...b];
		const fi = arr.findIndex(x => x.id === id);
		if (fi < 0) return b;
		const rating = arr[fi].rating;
		let ni = -1;                                   // nearest same-tier neighbour in `dir`
		for (let i = fi + dir; i >= 0 && i < arr.length; i += dir)
			if (arr[i].rating === rating) { ni = i; break; }
		if (ni < 0) return b;                          // already at the tier edge
		[arr[fi], arr[ni]] = [arr[ni], arr[fi]];
		return arr;
	});
	const moveSugg = (id, dir) => setSugg(s => {
		const arr = [...s];
		const fi = arr.findIndex(x => x.id === id);
		const ni = fi + dir;
		if (fi < 0 || ni < 0 || ni >= arr.length) return s;
		[arr[fi], arr[ni]] = [arr[ni], arr[fi]];
		return arr;
	});

	// ── ranking render ──
	const byRating = (r) => books.filter(b => b.rating === r);

	const rankReadView = () => (
		<div className="bk-list">
			{books.length === 0 && <div className="bk-empty">No books ranked yet.</div>}
			{RATINGS.map(r => {
				const group = byRating(r);
				if (!group.length) return null;
				return (
					<section key={r} className="bk-tier">
						<div className="bk-tier-head"><Stars value={r} /></div>
						<ol className="bk-cards">
							{group.map((b, i) => (
								<li key={b.id} className="bk-card">
									<span className="bk-rank">{i + 1}</span>
									{b.cover_url
										? <img className="bk-cover" src={b.cover_url} alt=""
											onError={(e) => { e.currentTarget.style.display = "none"; }} />
										: <span className="bk-cover bk-cover-blank">📖</span>}
									<div className="bk-meta">
										<div className="bk-title">{b.title}</div>
										{b.author && <div className="bk-author">{b.author}</div>}
										{b.note && <div className="bk-note">{b.note}</div>}
									</div>
								</li>
							))}
						</ol>
					</section>
				);
			})}
		</div>
	);

	const rankEditView = () => (
		<div className="bk-list">
			<BookSearch onPick={addFromSearch} placeholder="Search a book to add (title, author)…" />
			{RATINGS.map(r => {
				const group = byRating(r);
				return (
					<section key={r} className="bk-tier">
						<div className="bk-tier-head"><Stars value={r} /></div>
						{!group.length && <div className="bk-tier-empty">— drag a book here or set a book to {r}★ —</div>}
						<div className="bk-cards">
							{group.map((b, i) => (
								<div key={b.id} className={"bk-edit-row" + (dragOverId === b.id ? " bk-dragover" : "")}
									onDragOver={(e) => { e.preventDefault(); if (dragOverId !== b.id) setDragOverId(b.id); }}
									onDrop={() => { onRankDrop(b.id); setDragOverId(null); }}>
									<div className="bk-reorder">
										<button type="button" className="bk-move" title="Move up" disabled={i === 0}
											onClick={() => moveBook(b.id, -1)}>▲</button>
										<span className="bk-handle" draggable title="Drag to reorder within this rating"
											onDragStart={() => { rankDrag.current = b.id; }}
											onDragEnd={() => setDragOverId(null)}>⠿</span>
										<button type="button" className="bk-move" title="Move down" disabled={i === group.length - 1}
											onClick={() => moveBook(b.id, 1)}>▼</button>
									</div>
									<div className="bk-fields">
										<div className="bk-field-line">
											<input className="bk-in bk-in-title" placeholder="Title"
												value={b.title} onChange={(e) => updateBook(b.id, { title: e.target.value })} />
											<select className="bk-in bk-in-rating" value={b.rating}
												onChange={(e) => changeRating(b.id, Number(e.target.value))}>
												{RATINGS.map(n => <option key={n} value={n}>{n}★</option>)}
											</select>
											<button className="bk-del" title="Remove" onClick={() => removeBook(b.id)}>✕</button>
										</div>
										<input className="bk-in" placeholder="Author"
											value={b.author} onChange={(e) => updateBook(b.id, { author: e.target.value })} />
										<input className="bk-in" placeholder="Cover image URL (optional)"
											value={b.cover_url} onChange={(e) => updateBook(b.id, { cover_url: e.target.value })} />
										<textarea className="bk-in bk-in-note" placeholder="Note (optional)" rows={2}
											value={b.note} onChange={(e) => updateBook(b.id, { note: e.target.value })} />
									</div>
								</div>
							))}
						</div>
					</section>
				);
			})}
			<button className="bk-add" onClick={addBook}>+ Add book manually</button>
		</div>
	);

	// ── suggestions render ──
	const suggGroups = () => {
		const order = [];
		const map = new Map();
		for (const s of allSugg) {
			if (!map.has(s.user_id)) { map.set(s.user_id, []); order.push(s.user_id); }
			map.get(s.user_id).push(s);
		}
		return order.map(uid => ({ uid, name: map.get(uid)[0].user_name || "Someone", items: map.get(uid) }));
	};

	const suggEditor = () => (
		<div className="bk-list" style={{ padding: 0 }}>
			<BookSearch onPick={addSuggFromSearch} placeholder="Search a book to suggest…" />
			<div className="bk-counter">{sugg.length} / {maxSugg}</div>
			<div className="bk-cards">
				{sugg.map((s, i) => (
					<div key={s.id} className={"bk-edit-row" + (dragOverId === s.id ? " bk-dragover" : "")}
						onDragOver={(e) => { e.preventDefault(); if (dragOverId !== s.id) setDragOverId(s.id); }}
						onDrop={() => { onSuggDrop(s.id); setDragOverId(null); }}>
						<div className="bk-reorder">
							<button type="button" className="bk-move" title="Move up" disabled={i === 0}
								onClick={() => moveSugg(s.id, -1)}>▲</button>
							<span className="bk-handle" draggable title="Drag to reorder"
								onDragStart={() => { suggDrag.current = s.id; }}
								onDragEnd={() => setDragOverId(null)}>⠿</span>
							<button type="button" className="bk-move" title="Move down" disabled={i === sugg.length - 1}
								onClick={() => moveSugg(s.id, 1)}>▼</button>
						</div>
						{s.cover_url
							? <img className="bk-cover" src={s.cover_url} alt=""
								onError={(e) => { e.currentTarget.style.display = "none"; }} />
							: <span className="bk-cover bk-cover-blank">📖</span>}
						<div className="bk-fields">
							<div className="bk-field-line">
								<input className="bk-in bk-in-title" placeholder="Title"
									value={s.title} onChange={(e) => updateSugg(s.id, { title: e.target.value })} />
								<button className="bk-del" title="Remove" onClick={() => removeSugg(s.id)}>✕</button>
							</div>
							<input className="bk-in" placeholder="Author"
								value={s.author} onChange={(e) => updateSugg(s.id, { author: e.target.value })} />
							<textarea className="bk-in bk-in-note" rows={2}
								placeholder="Why should I read it?"
								value={s.blurb} onChange={(e) => updateSugg(s.id, { blurb: e.target.value })} />
						</div>
					</div>
				))}
			</div>
			{sugg.length < maxSugg && <button className="bk-add" onClick={addSuggBlank}>+ Add manually</button>}
		</div>
	);

	const suggestionsSection = () => {
		if (!suggInfo) return null;
		let body, controls = null;

		if (suggInfo.is_owner) {
			const groups = suggGroups();
			body = groups.length === 0
				? <div className="bk-empty">No suggestions yet.</div>
				: groups.map(g => (
					<div key={g.uid} className="bk-sugg-group">
						<div className="bk-sugg-by">Suggested by {g.name}</div>
						<SuggestionList items={g.items} />
					</div>
				));
		} else if (suggInfo.logged_in) {
			if (suggEditing) {
				controls = (
					<>
						<button className="btn btn-ghost btn-sm" onClick={cancelSuggEdit} disabled={suggSaving}>Cancel</button>
						<button className="btn btn-gold btn-sm" onClick={saveSugg} disabled={suggSaving}>
							{suggSaving ? "Saving…" : "Save"}
						</button>
					</>
				);
				body = suggEditor();
			} else {
				controls = offlineAt ? null
					: <button className="btn btn-outline btn-sm" onClick={startSuggEdit}>{sugg.length ? "Edit" : "Suggest a book"}</button>;
				body = sugg.length === 0
					? <div className="bk-empty">You haven't suggested any books yet.</div>
					: <SuggestionList items={sugg} />;
			}
		} else {
			body = <div className="bk-login-note">Log in to suggest books for me to read.</div>;
		}

		return (
			<div className="bk-section">
				<div className="bk-section-head">
					<div>
						<div className="bk-section-title">Suggestions</div>
						<div className="bk-section-sub">
							{suggInfo.is_owner
								? "Books readers think you should read."
								: "Recommend up to " + maxSugg + " books for me to read."}
						</div>
					</div>
					<div className="bk-headright">{controls}</div>
				</div>
				{body}
			</div>
		);
	};

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="bk-app">
				<header className="bk-header">
					<button className="btn btn-ghost btn-sm" onClick={onExit}>← Back</button>
					<div className="bk-headtitle">Books</div>
					<div className="bk-headright">
						{canEdit && !editing && <button className="btn btn-outline btn-sm" onClick={startEdit}>Edit ranking</button>}
						{editing && (
							<>
								<button className="btn btn-ghost btn-sm" onClick={cancelEdit} disabled={saving}>Cancel</button>
								<button className="btn btn-gold btn-sm" onClick={save} disabled={saving}>
									{saving ? "Saving…" : "Save"}
								</button>
							</>
						)}
					</div>
				</header>

				<div className="bk-hero">
					<div className="bk-logo">My Bookshelf</div>
				</div>
				{offlineAt && (
					<div className="bk-offline-note" role="status">
						Offline — showing the copy saved {new Date(offlineAt).toLocaleDateString(undefined, { month: "short", day: "numeric" })}.
						Editing needs a connection.
					</div>
				)}

				<div className="bk-columns">
					{loading ? <div className="bk-empty">Loading…</div> : (editing ? rankEditView() : rankReadView())}
					{suggestionsSection()}
				</div>

				{toast && <div className="bk-toast">{toast}</div>}
			</div>
		</>
	);
}

// ─── Styles (uses the shared theme tokens/fonts from shared/theme.js) ─────────
const css = _cssText;
