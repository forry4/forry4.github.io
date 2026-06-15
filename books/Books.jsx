import { useState, useEffect, useRef } from "react";

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

	useEffect(() => {
		const q = query.trim();
		if (q.length < 3) { setResults([]); setSearching(false); return; }
		const ctrl = new AbortController();
		setSearching(true);
		const t = setTimeout(async () => {
			try {
				const url = `https://openlibrary.org/search.json?q=${encodeURIComponent(q)}`
					+ `&limit=8&fields=key,title,author_name,cover_i,first_publish_year`;
				const res = await fetch(url, { signal: ctrl.signal });
				const data = await res.json();
				setResults((data.docs || []).slice(0, 8));
			} catch (e) { if (e.name !== "AbortError") setResults([]); }
			finally { setSearching(false); }
		}, 300);
		return () => { ctrl.abort(); clearTimeout(t); };
	}, [query]);

	const pick = (r) => { onPick(r); setQuery(""); setResults([]); };

	return (
		<div className="bk-search">
			<input className="bk-in bk-search-in" placeholder={placeholder || "Search a book…"}
				value={query} onChange={(e) => setQuery(e.target.value)} />
			{(searching || results.length > 0) && (
				<div className="bk-results">
					{searching && <div className="bk-result-hint">Searching…</div>}
					{!searching && results.length === 0 && <div className="bk-result-hint">No matches</div>}
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

	const [toast, setToast] = useState("");

	const token = authUser?.session_token || null;
	const tokenQS = token ? `?token=${encodeURIComponent(token)}` : "";
	const maxSugg = suggInfo?.max || 10;

	// ── data load ──
	useEffect(() => {
		let cancelled = false;
		(async () => {
			try {
				const res = await fetch(`${HTTP_BASE}/books${tokenQS}`);
				const data = await res.json();
				if (cancelled) return;
				if (data.ok) { setBooks(data.books || []); setCanEdit(!!data.can_edit); }
			} catch { /* leave empty */ }
			finally { if (!cancelled) setLoading(false); }
		})();
		return () => { cancelled = true; };
	}, [tokenQS]);

	useEffect(() => {
		let cancelled = false;
		(async () => {
			try {
				const res = await fetch(`${HTTP_BASE}/books/suggestions${tokenQS}`);
				const data = await res.json();
				if (cancelled || !data.ok) return;
				setSugg(data.mine || []);
				setAllSugg(data.all || []);
				setSuggInfo({ is_owner: !!data.is_owner, logged_in: !!data.logged_in, max: data.max || 10 });
			} catch { /* leave empty */ }
		})();
		return () => { cancelled = true; };
	}, [tokenQS]);

	const showToast = (m) => { setToast(m); setTimeout(() => setToast(""), 2500); };

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
			const payload = {
				books: books.map(({ id, title, author, rating, note, cover_url }) =>
					({ id, title, author, rating, note, cover_url })),
			};
			const res = await fetch(`${HTTP_BASE}/books${tokenQS}`, {
				method: "PUT", headers: { "Content-Type": "application/json" },
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
			const payload = {
				suggestions: sugg.map(({ id, title, author, cover_url, blurb }) =>
					({ id, title, author, cover_url, blurb })),
			};
			const res = await fetch(`${HTTP_BASE}/books/suggestions${tokenQS}`, {
				method: "PUT", headers: { "Content-Type": "application/json" },
				body: JSON.stringify(payload),
			});
			const data = await res.json();
			if (data.ok) { setSugg(data.mine || []); setSuggEditing(false); showToast("Suggestions saved"); }
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
			arr.splice(arr.findIndex(x => x.id === targetId), 0, moved);
			return arr;
		});
	};
	const onRankDrop = makeDrop(rankDrag, setBooks, true);
	const onSuggDrop = makeDrop(suggDrag, setSugg, false);

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
							{group.map((b) => (
								<div key={b.id} className="bk-edit-row"
									draggable
									onDragStart={() => { rankDrag.current = b.id; }}
									onDragOver={(e) => e.preventDefault()}
									onDrop={() => onRankDrop(b.id)}>
									<span className="bk-handle" title="Drag to reorder within this rating">⠿</span>
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
				{sugg.map((s) => (
					<div key={s.id} className="bk-edit-row"
						draggable
						onDragStart={() => { suggDrag.current = s.id; }}
						onDragOver={(e) => e.preventDefault()}
						onDrop={() => onSuggDrop(s.id)}>
						<span className="bk-handle" title="Drag to reorder">⠿</span>
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
						<button className="bk-btn bk-ghost" onClick={cancelSuggEdit} disabled={suggSaving}>Cancel</button>
						<button className="bk-btn bk-primary" onClick={saveSugg} disabled={suggSaving}>
							{suggSaving ? "Saving…" : "Save"}
						</button>
					</>
				);
				body = suggEditor();
			} else {
				controls = <button className="bk-btn" onClick={startSuggEdit}>{sugg.length ? "Edit" : "Suggest a book"}</button>;
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
			<style>{css}</style>
			<div className="bk-app">
				<header className="bk-header">
					<button className="bk-back" onClick={onExit}>← Forrest Games</button>
					<div className="bk-headtitle">Books</div>
					<div className="bk-headright">
						{canEdit && !editing && <button className="bk-btn" onClick={startEdit}>Edit ranking</button>}
						{editing && (
							<>
								<button className="bk-btn bk-ghost" onClick={cancelEdit} disabled={saving}>Cancel</button>
								<button className="bk-btn bk-primary" onClick={save} disabled={saving}>
									{saving ? "Saving…" : "Save"}
								</button>
							</>
						)}
					</div>
				</header>

				<div className="bk-hero">
					<div className="bk-logo">My Bookshelf</div>
					<p className="bk-tagline">Favorites I've read, ranked — grouped by stars, ordered within.</p>
				</div>

				{loading ? <div className="bk-empty">Loading…</div> : (editing ? rankEditView() : rankReadView())}

				{suggestionsSection()}

				{toast && <div className="bk-toast">{toast}</div>}
			</div>
		</>
	);
}

// ─── Styles (self-contained, dark theme to match the site) ───────────────────
const css = `
.bk-app{min-height:100vh;background:#14121b;color:#e8e4f0;
	font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;
	padding:0 0 80px;}
.bk-header{position:sticky;top:0;z-index:5;display:flex;align-items:center;gap:12px;
	padding:12px 20px;background:rgba(20,18,27,.92);backdrop-filter:blur(6px);
	border-bottom:1px solid #2a2638;}
.bk-back{background:none;border:none;color:#b8b0cc;font-size:14px;cursor:pointer;padding:6px 8px;border-radius:6px;}
.bk-back:hover{color:#fff;background:#221f2e;}
.bk-headtitle{font-weight:700;letter-spacing:.5px;}
.bk-headright{margin-left:auto;display:flex;gap:8px;}
.bk-btn{background:#241f33;color:#e8e4f0;border:1px solid #3a3550;border-radius:8px;
	padding:7px 14px;font-size:14px;cursor:pointer;}
.bk-btn:hover{border-color:#5a5278;}
.bk-btn:disabled{opacity:.5;cursor:default;}
.bk-primary{background:#e0b65c;color:#1a1622;border-color:#e0b65c;font-weight:600;}
.bk-primary:hover{background:#ecc878;}
.bk-ghost{background:none;}
.bk-hero{text-align:center;padding:34px 20px 24px;}
.bk-logo{font-size:32px;font-weight:800;letter-spacing:1px;
	background:linear-gradient(90deg,#e0b65c,#f5d98a);-webkit-background-clip:text;
	background-clip:text;-webkit-text-fill-color:transparent;}
.bk-tagline{color:#9b94ad;margin:8px 0 0;font-size:15px;}
.bk-list{max-width:720px;margin:0 auto;padding:0 20px;}
.bk-empty{text-align:center;color:#9b94ad;padding:30px 0;}
.bk-tier{margin-bottom:30px;}
.bk-tier-head{margin-bottom:12px;border-bottom:1px solid #2a2638;padding-bottom:8px;}
.bk-tier-empty{color:#6b6480;font-size:13px;font-style:italic;padding:6px 0 14px;}
.bk-stars{font-size:20px;letter-spacing:2px;}
.bk-star{color:#3a3550;}
.bk-star.on{color:#f5c842;}
.bk-cards{list-style:none;margin:0;padding:0;display:flex;flex-direction:column;gap:10px;}
.bk-card{display:flex;align-items:center;gap:14px;background:#1e1b29;border:1px solid #2a2638;
	border-radius:12px;padding:12px 14px;}
.bk-rank{flex:none;width:26px;text-align:center;font-weight:700;color:#e0b65c;font-size:16px;}
.bk-cover{flex:none;width:42px;height:60px;object-fit:cover;border-radius:5px;background:#15131c;
	display:flex;align-items:center;justify-content:center;font-size:22px;}
.bk-cover-blank{color:#4a4560;}
.bk-meta{min-width:0;}
.bk-title{font-weight:600;font-size:16px;}
.bk-author{color:#9b94ad;font-size:13px;margin-top:2px;}
.bk-note{color:#c4bdd6;font-size:13px;margin-top:5px;line-height:1.4;}
/* edit mode */
.bk-edit-row{display:flex;gap:10px;background:#1e1b29;border:1px solid #2a2638;border-radius:12px;
	padding:12px;align-items:flex-start;}
.bk-handle{flex:none;cursor:grab;color:#6b6480;font-size:18px;padding-top:6px;user-select:none;}
.bk-fields{flex:1;min-width:0;display:flex;flex-direction:column;gap:7px;}
.bk-field-line{display:flex;gap:7px;}
.bk-in{background:#15131c;border:1px solid #332e45;color:#e8e4f0;border-radius:7px;
	padding:7px 10px;font-size:14px;width:100%;box-sizing:border-box;font-family:inherit;}
.bk-in:focus{outline:none;border-color:#e0b65c;}
.bk-in-title{flex:1;font-weight:600;}
.bk-in-rating{flex:none;width:64px;}
.bk-in-note{resize:vertical;}
.bk-del{flex:none;background:none;border:1px solid #4a2230;color:#e07a7a;border-radius:7px;
	width:32px;cursor:pointer;font-size:14px;}
.bk-del:hover{background:#2a1a20;}
.bk-add{display:block;width:100%;margin:10px auto 0;background:none;
	border:1px dashed #4a4560;color:#b8b0cc;border-radius:10px;padding:12px;cursor:pointer;font-size:15px;}
.bk-add:hover{border-color:#e0b65c;color:#fff;}
.bk-toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%);
	background:#241f33;border:1px solid #3a3550;color:#fff;padding:10px 20px;border-radius:10px;
	font-size:14px;box-shadow:0 8px 24px rgba(0,0,0,.4);}
/* search-to-add */
.bk-search{position:relative;margin-bottom:24px;}
.bk-search-in{font-size:15px;padding:11px 14px;}
.bk-results{margin-top:6px;background:#1b1826;border:1px solid #332e45;border-radius:10px;
	overflow:hidden;box-shadow:0 10px 30px rgba(0,0,0,.4);}
.bk-result-hint{padding:12px 14px;color:#9b94ad;font-size:14px;}
.bk-result{display:flex;align-items:center;gap:12px;width:100%;text-align:left;background:none;
	border:none;border-bottom:1px solid #262234;color:#e8e4f0;padding:9px 14px;cursor:pointer;}
.bk-result:last-child{border-bottom:none;}
.bk-result:hover{background:#241f33;}
.bk-result-cover{flex:none;width:34px;height:48px;object-fit:cover;border-radius:4px;
	background:#15131c;display:flex;align-items:center;justify-content:center;font-size:18px;}
.bk-result-text{display:flex;flex-direction:column;min-width:0;}
.bk-result-title{font-weight:600;font-size:14px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;}
.bk-result-sub{color:#9b94ad;font-size:12px;margin-top:2px;}
/* suggestions section */
.bk-section{max-width:720px;margin:40px auto 0;padding:24px 20px 0;border-top:1px solid #2a2638;}
.bk-section-head{display:flex;align-items:flex-start;gap:12px;margin-bottom:18px;}
.bk-section-title{font-size:22px;font-weight:700;}
.bk-section-sub{color:#9b94ad;font-size:14px;margin-top:3px;}
.bk-sugg-group{margin-bottom:26px;}
.bk-sugg-by{color:#e0b65c;font-size:13px;font-weight:600;text-transform:uppercase;
	letter-spacing:.5px;margin-bottom:10px;}
.bk-counter{color:#9b94ad;font-size:13px;margin-bottom:10px;}
.bk-login-note{color:#9b94ad;font-size:15px;padding:14px 0;}
`;
