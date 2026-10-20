import { useState, useEffect, useMemo, useRef, useCallback, Fragment } from "react";
import { baseCss } from "../shared/theme.js";
import { buildPath, parsePath, pushPath, subscribe } from "../shared/router.js";
import {
	ELEMENTS, RARITIES, KEYWORDS, TYPE_LABEL, buildModel, search, matches, keyOf, slug,
	critMultiplier, armorPct, effectiveLife, nextStone, breakEvenLife, nextDamageStone,
} from "./derive.js";
import * as ED from "./editorial.js";

// CSS lives in the sibling .css file, imported with `?inline` (see CLAUDE.md: never move
// it back into a JS template literal).
import _cssText from "./AstralGuide.css?inline";
const css = _cssText;

// The payload is a build artifact (tools/make_data.py), fetched rather than bundled so
// the lazy chunk stays small and the CDN caches the data on its own.
const DATA_URL = `${import.meta.env.BASE_URL || "/"}data/astral-guide.json`;

const TABS = [
	{ id: "start", label: "Start" },
	{ id: "auras", label: "Auras" },
	{ id: "gambits", label: "Gambits" },
	{ id: "imprints", label: "Imprints" },
	{ id: "spells", label: "Spells" },
	{ id: "echoes", label: "Echoes & Summons" },
	{ id: "prowess", label: "Prowess" },
	{ id: "synergy", label: "Synergies" },
	{ id: "tiers", label: "Tier lists" },
	{ id: "charts", label: "Charts" },
	{ id: "bosses", label: "Bosses" },
	{ id: "meta", label: "Meta" },
	{ id: "glossary", label: "Glossary" },
];
const TAB_IDS = TABS.map((t) => t.id);
const TAB_OF_TYPE = { aura: "auras", gambit: "gambits", imprint: "imprints", spell: "spells", echo: "echoes",
	summon: "echoes", prowess: "prowess", boss: "bosses", catalyst: "meta", telluric: "meta", cursed: "meta", effect: "glossary" };

// Segment 2 of /astral/<tab>; router.js upper-cases it (it was written for room codes),
// and tab ids are lowercase letters, so lower-casing it back is exact.
const routeTab = () => {
	const t = (parsePath().room || "").toLowerCase();
	return TAB_IDS.includes(t) ? t : "start";
};
const hashKey = () => decodeURIComponent((window.location.hash || "").slice(1)) || null;

const plural = (t) => ({ prowess: "Prowess", echo: "Echoes", boss: "Bosses", catalyst: "Void Catalyst", telluric: "Telluric Telescope",
	cursed: "Cursed Telescope" }[t] || `${TYPE_LABEL[t]}s`);

const fmt = (n, d = 0) => Number(n).toLocaleString("en-US", { maximumFractionDigits: d, minimumFractionDigits: d });

// ── Small pieces ───────────────────────────────────────────────────────────
function ElementTag({ el }) {
	if (!el) return null;
	return <span className="aag-el" data-el={el}>{el}</span>;
}

function RarityTag({ r }) {
	return <span className="aag-rar" data-r={r}>{r}</span>;
}

function TierTag({ tier }) {
	if (!tier) return null;
	return <span className="aag-tier" data-tier={tier.tier} title={`${tier.list} tier ${tier.tier}: ${tier.why}`}>{tier.tier}</span>;
}

// Prose with every effect and spell made clickable.
function Rich({ text, ctx }) {
	const segs = useMemo(() => ctx.model.segments(text || ""), [text, ctx.model]);
	return segs.map((s, i) => {
		if (s.t === "kw") {
			const el = KEYWORDS.find((k) => k.k === s.k)?.el;
			return <button type="button" key={i} className="aag-kw" data-el={el} onClick={() => ctx.open(keyOf("effect", slug(s.k)))}>{s.text}</button>;
		}
		if (s.t === "spell") {
			return <button type="button" key={i} className="aag-sp" onClick={() => ctx.open(keyOf("spell", slug(s.name)))}
				title={spellTitle(ctx.model.spellByName[s.name])}>{s.text}</button>;
		}
		return <Fragment key={i}>{s.text}</Fragment>;
	});
}

const spellTitle = (s) => (s ? `${s.name}: ${s.mana} mana · ${s.dmg} dmg · ${s.hits} hits` : "");

function EntityLink({ k, ctx, children }) {
	const e = ctx.model.byKey[k];
	if (!e) return <span>{children}</span>;
	return <button type="button" className="aag-link" onClick={() => ctx.open(k)}>{children || e.name}</button>;
}

function SpellStats({ s, ctx }) {
	if (!s) return null;
	return (
		<div className="aag-spellstat">
			<EntityLink k={keyOf("spell", slug(s.name))} ctx={ctx}>{s.name}</EntityLink>
			<span><b>{s.mana}</b> mana</span><span><b>{s.dmg}</b> dmg</span><span><b>{s.hits}</b> hits</span>
			{s.dpm != null && <span className="aag-muted">{s.dpm} dmg/mana</span>}
		</div>
	);
}

function Chips({ label, options, value, onChange, colorBy }) {
	const toggle = (o) => onChange(value.includes(o) ? value.filter((x) => x !== o) : [...value, o]);
	return (
		<div className="aag-chips" role="group" aria-label={label}>
			<span className="aag-chips-lbl">{label}</span>
			{options.map((o) => {
				const id = typeof o === "string" ? o : o.id;
				const text = typeof o === "string" ? o : o.label;
				return (
					<button type="button" key={id} className="aag-chip" aria-pressed={value.includes(id)}
						data-el={colorBy === "el" ? id : undefined} data-r={colorBy === "r" ? id : undefined}
						onClick={() => toggle(id)}>{text}</button>
				);
			})}
		</div>
	);
}

// Phones get the chips behind a toggle: open, they would fill the first screen
// before a single result showed.
const narrow = () => typeof window !== "undefined" && window.matchMedia?.("(max-width: 760px)").matches;

function FilterBar({ f, set, placeholder, count, total, children }) {
	const active = Object.entries(f).reduce((n, [k, v]) => n + (k !== "q" && Array.isArray(v) ? v.length : 0), 0);
	const [open, setOpen] = useState(() => !narrow());
	return (
		<div className="aag-filters">
			<div className="aag-frow">
				<label className="aag-find">
					<SearchIcon />
					<input type="search" value={f.q} placeholder={placeholder} aria-label={placeholder}
						onChange={(e) => set({ q: e.target.value })} />
				</label>
				{children && <button type="button" className="aag-ftoggle" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
					Filters{active ? <> · <b>{active}</b></> : null} {open ? "▴" : "▾"}</button>}
				<span className="aag-count"><b>{count}</b> of {total}</span>
				{(f.q || active > 0) && <button type="button" className="aag-clear" onClick={() => set(null)}>Clear</button>}
			</div>
			{open && children}
		</div>
	);
}

const SearchIcon = () => (
	<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" aria-hidden="true">
		<circle cx="11" cy="11" r="7" /><path d="M20 20l-3.6-3.6" />
	</svg>
);

function Empty({ children }) {
	return <div className="aag-empty">{children || "Nothing matches. Loosen a filter."}</div>;
}

// Shows `step` cards, then more on demand — 175 auras render fine, but a phone
// should not lay out 200 prowess cards to show the first ten.
function useMore(items, step = 40, resetKey = "") {
	const [n, setN] = useState(step);
	useEffect(() => setN(step), [resetKey, step]);
	return [items.slice(0, n), items.length > n ? () => setN((v) => v + step) : null, items.length - n];
}

function More({ onMore, left }) {
	if (!onMore) return null;
	return <button type="button" className="aag-more" onClick={onMore}>Show more · {left} left</button>;
}

function Section({ title, sub, children, id }) {
	return (
		<section className="aag-sec" id={id}>
			<h2 className="aag-h2">{title}</h2>
			{sub && <p className="aag-sub">{sub}</p>}
			{children}
		</section>
	);
}

// ── Cards ──────────────────────────────────────────────────────────────────
function AuraCard({ e, ctx, rarity }) {
	const tier = e.tiers.find((t) => t.rarity === rarity) || e.tiers[e.tiers.length - 1];
	return (
		<article className="aag-card" data-el={e.element}>
			<header className="aag-card-hd">
				<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
				<TierTag tier={ctx.tierOf(e.key)} />
				<span className="aag-card-tags"><ElementTag el={e.element} />
					{e.astral ? <RarityTag r="Astral" /> : e.tiers.map((t) => (
						<span key={t.rarity} className={`aag-rdot${t.rarity === tier.rarity ? " on" : ""}`} data-r={t.rarity} title={t.rarity} />
					))}
				</span>
			</header>
			<ul className="aag-lines">{tier.lines.map((l, i) => <li key={i}><Rich text={l} ctx={ctx} /></li>)}</ul>
			{!e.astral && <div className="aag-card-ft">{tier.rarity}{tier.rarity !== "Mythic" ? " — tap the name for every rarity" : ""}</div>}
		</article>
	);
}

function GambitCard({ e, ctx, rarities }) {
	const rows = rarities.length ? e.rows.filter((r) => rarities.includes(r.rarity)) : e.rows;
	return (
		<article className="aag-card" data-el={e.element}>
			<header className="aag-card-hd">
				<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
				<span className="aag-card-tags"><ElementTag el={e.element} /></span>
			</header>
			<ul className="aag-grows">
				{rows.map((r, i) => (
					<li key={i}><RarityTag r={r.rarity} /><span><Rich text={r.text} ctx={ctx} /></span></li>
				))}
			</ul>
		</article>
	);
}

function ImprintCard({ e, ctx }) {
	return (
		<article className="aag-card" data-el={e.element}>
			<header className="aag-card-hd">
				<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
				<TierTag tier={ctx.tierOf(e.key)} />
				<span className="aag-card-tags"><ElementTag el={e.element} /></span>
			</header>
			<div className="aag-kind">{e.kind}{e.gambit && e.gambit !== "None" ? ` · gambit: ${e.gambit}` : ""}</div>
			<p className="aag-p"><Rich text={e.effect} ctx={ctx} /></p>
			{e.transcendence && <p className="aag-p aag-trans"><b>Transcendence</b> <Rich text={e.transcendence} ctx={ctx} /></p>}
			{e.casts.map((n) => <SpellStats key={n} s={ctx.model.spellByName[n]} ctx={ctx} />)}
			{e.echo && <div className="aag-echo-ref">Echo: <EntityLink k={keyOf("echo", slug(e.echo))} ctx={ctx}>{e.echo}</EntityLink>
				{ED.VOKO_GUESS.has(e.name) && <span className="aag-muted"> (matched by description)</span>}</div>}
			{e.needs.length > 0 && <div className="aag-needs">{e.needs.map((n) => <span key={n}>{n}</span>)}</div>}
		</article>
	);
}

function EchoCard({ e, ctx }) {
	const vokos = Object.entries(ED.VOKO_ECHO).filter(([, n]) => n === e.name).map(([i]) => i);
	return (
		<article className="aag-card">
			<header className="aag-card-hd">
				<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
				<TierTag tier={ctx.tierOf(e.key)} />
				<span className="aag-card-tags"><span className="aag-pill">{e.trigger}</span></span>
			</header>
			<p className="aag-p"><Rich text={e.desc} ctx={ctx} /></p>
			<div className="aag-card-ft">Cooldown: {e.cooldown}
				{vokos.length > 0 && <> · summoned by {vokos.map((v, i) => (
					<Fragment key={v}>{i ? ", " : ""}<EntityLink k={keyOf("imprint", slug(v))} ctx={ctx}>{v}</EntityLink></Fragment>))}</>}
			</div>
		</article>
	);
}

function SummonCard({ e, ctx }) {
	const seg = ctx.model.segments(e.effect).find((x) => x.t === "kw");
	const kw = seg && KEYWORDS.find((k) => k.k === seg.k);
	return (
		<article className="aag-card">
			<header className="aag-card-hd">
				<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
				<TierTag tier={ctx.tierOf(e.key)} />
				<span className="aag-card-tags"><span className="aag-pill" data-el={kw?.el}>{e.effect}</span></span>
			</header>
			<p className="aag-p"><Rich text={e.desc} ctx={ctx} /></p>
		</article>
	);
}

function ProwessCard({ e, ctx }) {
	return (
		<article className="aag-card aag-card-sm">
			<header className="aag-card-hd">
				<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
				<span className="aag-card-tags"><span className="aag-pill">{e.hero === "All heroes" ? "Attack" : e.hero}</span>
					{e.path !== "Generic" && e.path !== "Attack" && <span className="aag-pill aag-pill-dim">{e.path}</span>}</span>
			</header>
			<p className="aag-p"><Rich text={e.effect} ctx={ctx} /></p>
		</article>
	);
}

function MiniList({ keys, ctx, limit = 12 }) {
	const [all, setAll] = useState(false);
	if (!keys?.length) return <span className="aag-muted">None found.</span>;
	const shown = all ? keys : keys.slice(0, limit);
	return (
		<div className="aag-mini">
			{shown.map((k) => {
				const e = ctx.model.byKey[k];
				return e ? (
					<button type="button" key={k} className="aag-mchip" data-el={e.element || undefined} onClick={() => ctx.open(k)}>
						<span className="aag-mtype">{TYPE_LABEL[e.type]}</span>{e.name}
					</button>
				) : null;
			})}
			{keys.length > limit && !all && <button type="button" className="aag-mmore" onClick={() => setAll(true)}>+{keys.length - limit} more</button>}
		</div>
	);
}

// Group a key list by type, auras first: the order a builder reads it in.
const TYPE_ORDER = ["aura", "gambit", "imprint", "prowess", "summon", "echo", "spell"];
const groupKeys = (keys, model) => {
	const by = {};
	for (const k of keys || []) {
		const e = model.byKey[k];
		if (e) (by[e.type] ||= []).push(k);
	}
	return TYPE_ORDER.filter((t) => by[t]).map((t) => [t, by[t]]);
};

function Related({ e, ctx }) {
	const uses = (e.uses || []).filter((k) => ctx.model.makers[k]);
	const makes = (e.makes || []).filter((k) => ctx.model.users[k]);
	if (!uses.length && !makes.length) return null;
	return (
		<div className="aag-related">
			<h3 className="aag-h3">Works well with</h3>
			{uses.map((k) => (
				<div key={`u${k}`} className="aag-rel">
					<div className="aag-rel-hd">Needs <EntityLink k={keyOf("effect", slug(k))} ctx={ctx}>{k}</EntityLink> — made by</div>
					<MiniList keys={ctx.model.makers[k].filter((x) => x !== e.key)} ctx={ctx} limit={8} />
				</div>
			))}
			{makes.map((k) => (
				<div key={`m${k}`} className="aag-rel">
					<div className="aag-rel-hd">Makes <EntityLink k={keyOf("effect", slug(k))} ctx={ctx}>{k}</EntityLink> — paid off by</div>
					<MiniList keys={ctx.model.users[k].filter((x) => x !== e.key)} ctx={ctx} limit={8} />
				</div>
			))}
		</div>
	);
}

// ── The detail drawer ──────────────────────────────────────────────────────
function Detail({ e, ctx }) {
	const tier = ctx.tierOf(e.key);
	const body = (() => {
		switch (e.type) {
			case "aura": return (<>
				{e.tiers.map((t) => (
					<div key={t.rarity} className="aag-dtier">
						<RarityTag r={t.rarity} />
						<ul className="aag-lines">{t.lines.map((l, i) => <li key={i}><Rich text={l} ctx={ctx} /></li>)}</ul>
					</div>
				))}
				{e.casts.length > 0 && <><h3 className="aag-h3">Casts</h3>{e.casts.map((n) => <SpellStats key={n} s={ctx.model.spellByName[n]} ctx={ctx} />)}</>}
				{e.triggers.length > 0 && <div className="aag-needs">{e.triggers.map((t) => <span key={t}>{t}</span>)}</div>}
			</>);
			case "gambit": return (<>
				<ul className="aag-grows">{e.rows.map((r, i) => <li key={i}><RarityTag r={r.rarity} /><span><Rich text={r.text} ctx={ctx} /></span></li>)}</ul>
				<p className="aag-p aag-muted">Shop price by rarity: {Object.entries(ctx.data.gambitMeta.price).map(([r, p]) => `${r} ${p}`).join(" · ")} Quartz.
					A gambit matching the spell's element adds 10% spell damage; four matching add 50%.</p>
			</>);
			case "imprint": return (<>
				<div className="aag-kind">{e.kind}{e.gambit && e.gambit !== "None" ? ` · listed gambit: ${e.gambit}` : ""}</div>
				<p className="aag-p"><Rich text={e.effect} ctx={ctx} /></p>
				{e.transcendence && <p className="aag-p aag-trans"><b>Transcendence</b> <Rich text={e.transcendence} ctx={ctx} /></p>}
				{e.casts.length > 0 && <><h3 className="aag-h3">Casts</h3>{e.casts.map((n) => <SpellStats key={n} s={ctx.model.spellByName[n]} ctx={ctx} />)}
					<p className="aag-p aag-muted">The numbers are that spell's base stats from the wiki's Spells table. The wiki doesn't say whether an imprint's cast deals the same.</p></>}
				{e.echo && (() => { const ec = ctx.model.byKey[keyOf("echo", slug(e.echo))]; return ec ? (<>
					<h3 className="aag-h3">Summons echo{ED.VOKO_GUESS.has(e.name) ? " (matched by description)" : ""}</h3>
					<EchoCard e={ec} ctx={ctx} /></>) : null; })()}
				{e.needs.length > 0 && <div className="aag-needs">{e.needs.map((n) => <span key={n}>{n}</span>)}</div>}
			</>);
			case "spell": return (<>
				<div className="aag-stats">
					<div><b>{e.mana}</b><span>mana</span></div><div><b>{e.dmg}</b><span>damage</span></div>
					<div><b>{e.hits}</b><span>hits</span></div>{e.dpm != null && <div><b>{e.dpm}</b><span>dmg / mana</span></div>}
				</div>
				<p className="aag-p">{e.group === "Hero" ? `${e.hero}'s spell` : `${e.group} spell`}{e.tags.length ? ` · ${e.tags.join(" · ")}` : ""}</p>
				{e.desc && <p className="aag-p">{e.desc}</p>}
				{e.castBy.length > 0 && <><h3 className="aag-h3">Also cast by</h3><MiniList keys={e.castBy} ctx={ctx} /></>}
			</>);
			case "echo": return <EchoCard e={e} ctx={ctx} />;
			case "summon": return <p className="aag-p"><Rich text={e.desc} ctx={ctx} /></p>;
			case "prowess": return (<>
				<p className="aag-p">{e.hero === "All heroes" ? "Attack prowess — every hero" : `${e.hero} · ${e.path}`}</p>
				<p className="aag-p"><Rich text={e.effect} ctx={ctx} /></p>
			</>);
			case "boss": return <BossBody b={e} ctx={ctx} open />;
			case "catalyst": return (<>
				<p className="aag-p"><b>{e.row}</b> · cost per tier: {e.cost}</p>
				<p className="aag-p">{e.desc}</p>
				{e.strategy && <p className="aag-p aag-muted">{e.strategy}</p>}
			</>);
			case "telluric": return (<><p className="aag-p">{e.desc}</p>{e.synergy && <p className="aag-p aag-muted"><b>Synergy:</b> {e.synergy}</p>}</>);
			case "cursed": return <p className="aag-p"><b>{e.kind}.</b> <Rich text={e.desc} ctx={ctx} /></p>;
			case "effect": return <EffectBody e={e} ctx={ctx} />;
			default: return null;
		}
	})();
	return (
		<>
			<div className="aag-dhead">
				<span className="aag-dtype">{TYPE_LABEL[e.type]}</span>
				<h2 className="aag-dname">{e.name}</h2>
				<span className="aag-card-tags"><ElementTag el={e.element} />{tier && <TierTag tier={tier} />}</span>
			</div>
			{tier && <p className="aag-p aag-tierwhy"><b>{tier.list} tier {tier.tier}.</b> {tier.why}</p>}
			{body}
			{e.type !== "effect" && <Related e={e} ctx={ctx} />}
		</>
	);
}

function EffectBody({ e, ctx }) {
	const makers = groupKeys(ctx.model.makers[e.name], ctx.model);
	const users = groupKeys(ctx.model.users[e.name], ctx.model);
	const arch = ED.ARCHETYPES.find((a) => a.effect === e.name);
	return (<>
		{e.desc && <p className="aag-p">{e.desc}</p>}
		{arch && <p className="aag-p aag-muted">Build: <button type="button" className="aag-link" onClick={() => ctx.go("synergy", e.name)}>{arch.name}</button> — {arch.how}</p>}
		<h3 className="aag-h3">Makes it</h3>
		{makers.length ? makers.map(([t, keys]) => (
			<div className="aag-rel" key={t}><div className="aag-rel-hd">{plural(t)}</div><MiniList keys={keys} ctx={ctx} /></div>
		)) : <p className="aag-muted">Nothing found.</p>}
		<h3 className="aag-h3">Pays it off</h3>
		{users.length ? users.map(([t, keys]) => (
			<div className="aag-rel" key={t}><div className="aag-rel-hd">{plural(t)}</div><MiniList keys={keys} ctx={ctx} /></div>
		)) : <p className="aag-muted">Nothing found.</p>}
		<p className="aag-p aag-muted">Linked automatically from the wiki's wording: "On X hit…", "Increases X damage" and "per X" count as payoffs; "creates/summons/applies X" as makers.</p>
	</>);
}

function Drawer({ k, ctx, onClose, onBack, canBack }) {
	const e = ctx.model.byKey[k];
	const ref = useRef(null);
	useEffect(() => { ref.current?.scrollTo?.(0, 0); ref.current?.focus(); }, [k]);
	if (!e) return null;
	const share = `${window.location.origin}${window.location.pathname}#${encodeURIComponent(k)}`;
	return (
		<div className="aag-drawer-wrap" onClick={(ev) => { if (ev.target === ev.currentTarget) onClose(); }}>
			<aside className="aag-drawer" role="dialog" aria-modal="true" aria-label={e.name} tabIndex={-1} ref={ref}>
				<div className="aag-dbar">
					{canBack ? <button type="button" className="aag-dbtn" onClick={onBack}>← Back</button> : <span />}
					<CopyLink url={share} />
					<button type="button" className="aag-dbtn" onClick={onClose} aria-label="Close">✕</button>
				</div>
				<div className="aag-dbody"><Detail e={e} ctx={ctx} /></div>
			</aside>
		</div>
	);
}

function CopyLink({ url }) {
	const [st, setSt] = useState("");
	const copy = async () => {
		try { await navigator.clipboard.writeText(url); setSt("Copied"); }
		catch {
			try {
				const t = document.createElement("textarea");
				t.value = url; document.body.appendChild(t); t.select();
				setSt(document.execCommand("copy") ? "Copied" : "Copy failed");
				t.remove();
			} catch { setSt("Copy failed"); }
		}
		setTimeout(() => setSt(""), 1600);
	};
	return <button type="button" className="aag-dbtn" onClick={copy} aria-live="polite">{st || "Copy link"}</button>;
}

// ── The global search ──────────────────────────────────────────────────────
function GlobalSearch({ ctx, inputRef }) {
	const [q, setQ] = useState("");
	const [open, setOpen] = useState(false);
	const [hi, setHi] = useState(0);
	const boxRef = useRef(null);
	// Closed by a press OUTSIDE, not by blur: on a phone the input blurs as the finger
	// lands on a result, and a popup closed on blur is gone before the tap's click.
	useEffect(() => {
		if (!open) return undefined;
		const away = (ev) => { if (!boxRef.current?.contains(ev.target)) setOpen(false); };
		document.addEventListener("pointerdown", away);
		return () => document.removeEventListener("pointerdown", away);
	}, [open]);
	const res = useMemo(() => search(ctx.model, q, { limit: 200 }), [ctx.model, q]);
	const groups = useMemo(() => {
		const by = new Map();
		for (const e of res) {
			if (!by.has(e.type)) by.set(e.type, []);
			by.get(e.type).push(e);
		}
		return [...by.entries()];
	}, [res]);
	const flat = useMemo(() => groups.flatMap(([, list]) => list.slice(0, 6)), [groups]);
	useEffect(() => setHi(0), [q]);
	const pick = (e) => { ctx.open(e.key); setOpen(false); inputRef.current?.blur(); };
	const onKey = (ev) => {
		if (ev.key === "ArrowDown") { ev.preventDefault(); setHi((h) => Math.min(flat.length - 1, h + 1)); }
		else if (ev.key === "ArrowUp") { ev.preventDefault(); setHi((h) => Math.max(0, h - 1)); }
		else if (ev.key === "Enter" && flat[hi]) pick(flat[hi]);
		else if (ev.key === "Escape") { if (q) setQ(""); else inputRef.current?.blur(); setOpen(false); }
	};
	let idx = -1;
	return (
		<div className="aag-gs" ref={boxRef}>
			<label className="aag-gs-box">
				<SearchIcon />
				<input ref={inputRef} type="search" value={q} placeholder="Search auras, gambits, imprints, effects…"
					aria-label="Search the whole guide" onFocus={() => setOpen(true)}
					onChange={(e) => { setQ(e.target.value); setOpen(true); }} onKeyDown={onKey} />
				<kbd className="aag-kbd" aria-hidden="true">/</kbd>
			</label>
			{open && q.trim() && (
				<div className="aag-gs-pop" role="listbox">
					{!res.length && <div className="aag-gs-none">No matches for “{q}”.</div>}
					{groups.map(([type, list]) => (
						<div key={type} className="aag-gs-grp">
							<div className="aag-gs-hd">{plural(type)} <span>{list.length}</span></div>
							{list.slice(0, 6).map((e) => {
								idx += 1;
								const me = idx;
								return (
									<button type="button" key={e.key} className={`aag-gs-item${me === hi ? " hi" : ""}`} role="option"
										aria-selected={me === hi} onMouseEnter={() => setHi(me)} onClick={() => pick(e)}>
										<span className="aag-gs-name">{e.name}</span>
										<span className="aag-gs-meta">{[e.element, e.rarities?.at(-1), e.kind, e.hero, e.cooldown, e.effect && e.type === "summon" ? e.effect : null]
											.filter(Boolean).slice(0, 2).join(" · ")}</span>
									</button>
								);
							})}
							{list.length > 6 && (
								<button type="button" className="aag-gs-all" onClick={() => { ctx.go(TAB_OF_TYPE[type], q); setOpen(false); }}>
									See all {list.length} in {TABS.find((t) => t.id === TAB_OF_TYPE[type]).label} →
								</button>
							)}
						</div>
					))}
				</div>
			)}
		</div>
	);
}

// ── Tabs ───────────────────────────────────────────────────────────────────
function StartTab({ ctx }) {
	const s = ctx.data.stats;
	const counts = { auras: "aura", gambits: "gambit", imprints: "imprint", spells: "spell", echoes: "echo", prowess: "prowess", bosses: "boss" };
	const n = (t) => ctx.model.list.filter((e) => e.type === t).length;
	const quick = [
		["auras", "Auras", `${n("aura")} passives, by element, rarity and trigger`],
		["gambits", "Gambits", `${n("gambit")} gambit families, every rarity`],
		["imprints", "Imprints", "What each casts or summons, with spell stats"],
		["spells", "Spells", "Mana, damage and hits for all " + n("spell")],
		["synergy", "Synergies", "Pick an effect: what makes it, what pays it off"],
		["tiers", "Tier lists", "Echoes, imprints, auras and summons"],
		["charts", "Charts", "Crit damage and life/armor calculators"],
		["bosses", "Bosses", "Every Zodiac and Star Guardian's attacks"],
	];
	return (<>
		<div className="aag-hero">
			<h1 className="aag-logo">Astral Ascent Guide</h1>
			<p className="aag-tag">Every aura, gambit, imprint, spell, echo and boss from the community wiki, searchable in one place.
				Press <kbd className="aag-kbd">/</kbd> to search from anywhere, and tap any highlighted effect or spell to open it.</p>
		</div>
		<div className="aag-quick">
			{quick.map(([id, label, sub]) => (
				<button type="button" key={id} className="aag-qtile" onClick={() => ctx.go(id)}>
					<span className="aag-qlabel">{label}</span><span className="aag-qsub">{sub}</span>
				</button>
			))}
		</div>
		<Section title="Key numbers" sub="From the wiki's Player Stats, Spell Mechanics and Gambits pages.">
			<div className="aag-tiles">
				<div className="aag-stile"><b>{s.baseLife}</b><span>starting life, +{s.lifePerStone} per Life stone</span></div>
				<div className="aag-stile"><b>{s.armorCap}%</b><span>armor cap, {s.armorPerStone}% per Armor stone</span></div>
				<div className="aag-stile"><b>+{s.critBonus}%</b><span>crit damage (more, multiplicative); {s.critPerStone}% chance per stone</span></div>
				<div className="aag-stile"><b>+{s.strengthPerStone}%</b><span>damage per Strength stone, additive</span></div>
				<div className="aag-stile"><b>+10%</b><span>spell damage per matching gambit; +50% with all four</span></div>
				<div className="aag-stile"><b>+10%</b><span>spell damage per spell level (X is the usual max)</span></div>
			</div>
		</Section>
		<Section title="Stat priority" sub="The wiki's recommended order for stones and drinks, for a newer player.">
			<ol className="aag-prio">{ED.STAT_PRIORITY.map((p) => <li key={p.stat}><b>{p.stat}</b> <span>{p.why}</span></li>)}</ol>
		</Section>
		<Section title="Best starting auras" sub={`Editor's picks. ${ED.TIER_NOTES.starting}`}>
			<div className="aag-picks">
				{ED.STARTING_AURAS.map(([name, why]) => {
					const e = ctx.model.byKey[keyOf("aura", slug(name))];
					return (
						<button type="button" key={name} className="aag-pick" data-el={e?.element} onClick={() => ctx.open(e.key)}>
							<span className="aag-pick-name">{name}</span><ElementTag el={e?.element} />
							<span className="aag-pick-why">{why}</span>
						</button>
					);
				})}
			</div>
		</Section>
		<Section title="How builds work" sub="The wiki's general strategies. See Synergies for each element's engines.">
			<div className="aag-cols2">
				{ED.BUILD_STRATEGIES.map((b) => <div key={b.name} className="aag-note"><b>{b.name}</b><p>{b.text}</p></div>)}
			</div>
		</Section>
		<Section title="Tips">
			<div className="aag-cols2">{ED.TIPS.map(([h, t]) => <div key={h} className="aag-note"><b>{h}</b><p>{t}</p></div>)}</div>
		</Section>
		<Section title="Anatomy of a run" sub="4 worlds of 12 rooms (5 with the final world), each ending on a Zodiac.">
			<dl className="aag-dl">{ED.RUN_MAP.map(([r, t]) => <Fragment key={r}><dt>{r}</dt><dd>{t}</dd></Fragment>)}</dl>
		</Section>
		<Section title="Heroes" sub="Each hero's signature spell. Prowess for each is in the Prowess tab.">
			<dl className="aag-dl">{ED.HEROES.map((h) => <Fragment key={h.name}><dt>{h.name}</dt><dd>{h.signature}</dd></Fragment>)}</dl>
		</Section>
		<p className="aag-source">Data from <a href="https://astralascent.wiki.gg" target="_blank" rel="noopener noreferrer">astralascent.wiki.gg</a>,
			collected {ctx.data.collected} (latest wiki edit {ctx.data.wikiUpdated}). Tier lists and picks are this guide's own judgment.
			Counts: {Object.entries(counts).map(([t, ty]) => `${n(ty)} ${t}`).join(", ")}.</p>
	</>);
}

const AURA_TRIGGERS = ["On cast", "On hit", "On refresh", "On dash", "On fall attack", "Critical", "When hit", "On kill", "Life threshold", "Mana", "Permanent summon", "Stats"];

function AurasTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "aura");
	const [show, setShow] = useState("Mythic");
	const list = all.filter((e) => matches(e, f.q)
		&& (!f.el.length || f.el.includes(e.element))
		&& (!f.rar.length || f.rar.some((r) => e.rarities.includes(r)))
		&& (!f.trig.length || f.trig.every((t) => e.triggers.includes(t)))
		&& (!f.fx.length || f.fx.every((k) => e.makes.includes(k) || e.uses.includes(k))));
	const [shown, more, left] = useMore(list, 40, JSON.stringify(f));
	const [fxOpen, setFxOpen] = useState(f.fx.length > 0);
	const fx = KEYWORDS.filter((k) => all.some((e) => e.makes.includes(k.k) || e.uses.includes(k.k))).map((k) => k.k);
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter auras by name or effect…" count={list.length} total={all.length}>
			<Chips label="Element" options={ELEMENTS} value={f.el} onChange={(v) => set({ el: v })} colorBy="el" />
			<Chips label="Rarity" options={RARITIES} value={f.rar} onChange={(v) => set({ rar: v })} colorBy="r" />
			<Chips label="Trigger" options={AURA_TRIGGERS} value={f.trig} onChange={(v) => set({ trig: v })} />
			{fxOpen ? <Chips label="Effect" options={fx} value={f.fx} onChange={(v) => set({ fx: v })} />
				: <button type="button" className="aag-fxtoggle" onClick={() => setFxOpen(true)}>+ Filter by effect (Burn, Embers, Missiles…)</button>}
		</FilterBar>
		<div className="aag-seg" role="group" aria-label="Show rarity">
			<span className="aag-chips-lbl">Show</span>
			{["Common", "Heroic", "Mythic"].map((r) => (
				<button type="button" key={r} aria-pressed={show === r} data-r={r} onClick={() => setShow(r)}>{r}</button>))}
			<span className="aag-muted aag-seg-note">text for non-Astral auras · {ctx.data.auras.filter((a) => a.astral).length} Astral auras have one tier</span>
		</div>
		{list.length ? <div className="aag-grid">{shown.map((e) => <AuraCard key={e.key} e={e} ctx={ctx} rarity={show} />)}</div> : <Empty />}
		<More onMore={more} left={left} />
	</>);
}

function GambitsTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "gambit");
	const list = all.filter((e) => matches(e, f.q)
		&& (!f.el.length || f.el.includes(e.element))
		&& (!f.rar.length || f.rar.some((r) => e.rarities.includes(r)))
		&& (!f.trig.length || f.trig.some((t) => e.triggers.includes(t))));
	const price = ctx.data.gambitMeta.price;
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter gambits…" count={list.length} total={all.length}>
			<Chips label="Element" options={ELEMENTS} value={f.el} onChange={(v) => set({ el: v })} colorBy="el" />
			<Chips label="Rarity" options={RARITIES} value={f.rar} onChange={(v) => set({ rar: v })} colorBy="r" />
			<Chips label="Trigger" options={["On hit", "On cast"]} value={f.trig} onChange={(v) => set({ trig: v })} />
		</FilterBar>
		<p className="aag-sub">Each spell has up to 4 slots. A gambit matching the spell's element adds 10% spell damage, and four matching add 50%.
			A placed gambit can be replaced but never removed. Shop prices: {Object.entries(price).map(([r, p]) => `${r} ${p}`).join(" · ")} Quartz.
			Elemental gambits (Sun Room only) are Mythic-strength and convert the spell's element.</p>
		{list.length ? <div className="aag-grid">{list.map((e) => <GambitCard key={e.key} e={e} ctx={ctx} rarities={f.rar} />)}</div> : <Empty />}
	</>);
}

const IMPRINT_KINDS = ["Casts a spell", "Summons an echo", "Summons", "Creates effects", "Damage boost", "Utility"];

function ImprintsTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "imprint");
	const list = all.filter((e) => matches(e, f.q)
		&& (!f.el.length || f.el.includes(e.element))
		&& (!f.kind.length || f.kind.includes(e.kind))
		&& (!f.need.length || (f.need.includes("No condition") ? !e.needs.length : f.need.every((n) => e.needs.includes(n)))));
	const casters = all.filter((e) => e.casts.length || e.echo || e.kind === "Summons");
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter imprints…" count={list.length} total={all.length}>
			<Chips label="Element" options={ELEMENTS} value={f.el} onChange={(v) => set({ el: v })} colorBy="el" />
			<Chips label="Does" options={IMPRINT_KINDS} value={f.kind} onChange={(v) => set({ kind: v })} />
			<Chips label="Needs" options={["No condition", "Full affinity", "3-mana spell", "Level 10", "Critical hits"]} value={f.need} onChange={(v) => set({ need: v })} />
		</FilterBar>
		<p className="aag-sub">One imprint per spell. Found in Exploration Rooms; more unlock from Blueprints dropped by bosses and elites.
			Meeting the Transcendence condition upgrades it. Every imprint found in a run can be swapped at Andromeda's Bar.</p>
		{list.length ? <div className="aag-grid">{list.map((e) => <ImprintCard key={e.key} e={e} ctx={ctx} />)}</div> : <Empty />}
		<Section title="Quick table: imprints that cast or summon" sub="The spell's base cost, damage and hits from the wiki's Spells table.">
			<div className="aag-tablewrap">
				<table className="aag-table">
					<thead><tr><th>Imprint</th><th>What it does</th><th>Spell or echo</th><th>Mana</th><th>Dmg</th><th>Hits</th></tr></thead>
					<tbody>
						{casters.map((e) => {
							const sp = e.casts.map((n) => ctx.model.spellByName[n]).filter(Boolean);
							return (
								<tr key={e.key}>
									<td><EntityLink k={e.key} ctx={ctx}>{e.name}</EntityLink> <ElementTag el={e.element} /></td>
									<td>{e.kind}</td>
									<td>{sp.length ? sp.map((s) => <EntityLink key={s.name} k={keyOf("spell", slug(s.name))} ctx={ctx}>{s.name}</EntityLink>)
										: e.echo ? <EntityLink k={keyOf("echo", slug(e.echo))} ctx={ctx}>{e.echo}</EntityLink> : <span className="aag-muted">a summon</span>}</td>
									<td className="aag-num">{sp.map((s) => s.mana).join(" / ") || "—"}</td>
									<td className="aag-num">{sp.map((s) => s.dmg).join(" / ") || "—"}</td>
									<td className="aag-num">{sp.map((s) => s.hits).join(" / ") || "—"}</td>
								</tr>
							);
						})}
					</tbody>
				</table>
			</div>
		</Section>
	</>);
}

// Type and tags ride under the name rather than in a column, so a phone shows the four
// numbers without scrolling sideways; Cast by drops out at that width.
const SPELL_COLS = [["name", "Spell"], ["mana", "Mana"], ["dmg", "Dmg"], ["hitsMax", "Hits"], ["dpm", "Dmg/mana"], ["cast", "Cast by"]];

function SpellsTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "spell");
	const [sort, setSort] = useState(["dpm", -1]);
	const groups = ["Common", "Zodiac", ...ED.HEROES.map((h) => h.name)];
	const tags = [...new Set(all.flatMap((e) => e.tags))].sort();
	const list = all.filter((e) => matches(e, f.q)
		&& (!f.grp.length || f.grp.includes(e.group === "Hero" ? e.hero : e.group))
		&& (!f.mana.length || f.mana.includes(String(e.mana)))
		&& (!f.tag.length || f.tag.every((t) => e.tags.includes(t))));
	const val = (e, k) => (k === "cast" ? e.castBy.length : k === "group" ? (e.hero || e.group) : e[k] ?? -1);
	list.sort((a, b) => {
		const x = val(a, sort[0]), y = val(b, sort[0]);
		return (typeof x === "string" ? x.localeCompare(y) : x - y) * sort[1] || a.name.localeCompare(b.name);
	});
	const by = (k) => setSort(([sk, d]) => [k, sk === k ? -d : k === "name" || k === "group" ? 1 : -1]);
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter spells…" count={list.length} total={all.length}>
			<Chips label="Type" options={groups} value={f.grp} onChange={(v) => set({ grp: v })} />
			<Chips label="Mana" options={["1", "2", "3"]} value={f.mana} onChange={(v) => set({ mana: v })} />
			<Chips label="Tags" options={tags} value={f.tag} onChange={(v) => set({ tag: v })} />
		</FilterBar>
		<p className="aag-sub">Damage is the wiki's estimate if every hit lands, before crits and gambits. Each spell level adds 10%.
			Dmg / mana is the fair comparison across costs, but cheap spells also make Spell Refresh come round sooner.</p>
		<div className="aag-tablewrap">
			<table className="aag-table aag-spells">
				<thead><tr>{SPELL_COLS.map(([k, l]) => (
					<th key={k} aria-sort={sort[0] === k ? (sort[1] < 0 ? "descending" : "ascending") : undefined}>
						<button type="button" onClick={() => by(k)}>{l}{sort[0] === k ? (sort[1] < 0 ? " ▼" : " ▲") : ""}</button>
					</th>))}</tr></thead>
				<tbody>
					{list.map((e) => (
						<tr key={e.key}>
							<td><EntityLink k={e.key} ctx={ctx}>{e.name}</EntityLink>
								<span className="aag-ttags">{[e.hero || e.group, ...e.tags].join(" · ")}</span></td>
							<td className="aag-num">{e.mana}</td><td className="aag-num">{e.dmg}</td><td className="aag-num">{e.hits}</td>
							<td className="aag-num"><DpmBar v={e.dpm} max={ctx.maxDpm} /></td>
							<td className="aag-num">{e.castBy.length ? <EntityLink k={e.key} ctx={ctx}>{e.castBy.length}</EntityLink> : ""}</td>
						</tr>
					))}
				</tbody>
			</table>
			{!list.length && <Empty />}
		</div>
	</>);
}

function DpmBar({ v, max }) {
	if (v == null) return "—";
	return <span className="aag-dpm"><span className="aag-dpm-t"><i style={{ width: `${Math.round((v / max) * 100)}%` }} /></span><span>{v}</span></span>;
}

function EchoesTab({ ctx, f, set }) {
	const echoes = ctx.model.list.filter((e) => e.type === "echo");
	const summons = ctx.model.list.filter((e) => e.type === "summon");
	const trig = [...new Set(echoes.map((e) => e.trigger))];
	const list = echoes.filter((e) => matches(e, f.q) && (!f.trig.length || f.trig.includes(e.trigger))
		&& (!f.tier.length || f.tier.includes(ctx.tierOf(e.key)?.tier)));
	const sl = summons.filter((e) => matches(e, f.q));
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter echoes and summons…" count={list.length + sl.length} total={echoes.length + summons.length}>
			<Chips label="Fires" options={trig} value={f.trig} onChange={(v) => set({ trig: v })} />
			<Chips label="Tier" options={["S", "A", "B", "C"]} value={f.tier} onChange={(v) => set({ tier: v })} />
		</FilterBar>
		<Section title="Echoes" sub="Garden characters who help for a moment, on a cooldown. Up to 5 at once. Echo effects trigger your auras where they can.">
			{list.length ? <div className="aag-grid">{list.map((e) => <EchoCard key={e.key} e={e} ctx={ctx} />)}</div> : <Empty />}
		</Section>
		<Section title="Zodiac summons" sub="Impress a Zodiac in its challenge room (or convince one in the bar). Casting fills the gauge. Summon effects trigger your auras — pick the one that matches them.">
			{sl.length ? <div className="aag-grid">{sl.map((e) => <SummonCard key={e.key} e={e} ctx={ctx} />)}</div> : <Empty />}
		</Section>
	</>);
}

function ProwessTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "prowess");
	const heroes = ["All heroes", ...ED.HEROES.map((h) => h.name)];
	const paths = [...new Set(all.filter((e) => !f.hero.length || f.hero.includes(e.hero)).map((e) => e.path))].filter((p) => p !== "Generic" && p !== "Attack");
	const list = all.filter((e) => matches(e, f.q) && (!f.hero.length || f.hero.includes(e.hero)) && (!f.path.length || f.path.includes(e.path)));
	const [shown, more, left] = useMore(list, 60, JSON.stringify(f));
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter prowess…" count={list.length} total={all.length}>
			<Chips label="Hero" options={heroes.map((h) => ({ id: h, label: h === "All heroes" ? "Attack (all heroes)" : h }))} value={f.hero} onChange={(v) => set({ hero: v, path: [] })} />
			{paths.length > 0 && <Chips label="Path" options={paths} value={f.path} onChange={(v) => set({ path: v })} />}
		</FilterBar>
		<p className="aag-sub">One prowess per level gained, chosen at each world's Guardian statue. The first level picks your hero's path;
			then signature and attack prowess alternate. Up to 8 are held; levels 9–12 reroll.</p>
		{list.length ? <div className="aag-grid aag-grid-sm">{shown.map((e) => <ProwessCard key={e.key} e={e} ctx={ctx} />)}</div> : <Empty />}
		<More onMore={more} left={left} />
	</>);
}

function SynergyTab({ ctx, focus }) {
	const [pick, setPick] = useState(focus || "Combustion");
	useEffect(() => { if (focus) setPick(focus); }, [focus]);
	const e = ctx.model.byKey[keyOf("effect", slug(pick))];
	const arch = ED.ARCHETYPES.find((a) => a.effect === pick);
	return (<>
		<p className="aag-sub">Pick an effect to see everything that <b>makes</b> it and everything that <b>pays it off</b>. The lists are linked
			automatically from the wiki's wording; the build outlines are curated.</p>
		<div className="aag-fxpick">
			{ELEMENTS.map((el) => (
				<div key={el} className="aag-fxrow">
					<span className="aag-chips-lbl" data-el={el}>{el}</span>
					{KEYWORDS.filter((k) => k.el === el).map((k) => (
						<button type="button" key={k.k} className="aag-chip" data-el={el} aria-pressed={pick === k.k} onClick={() => setPick(k.k)}>
							{k.k} <span className="aag-chipn">{(ctx.model.makers[k.k] || []).length}/{(ctx.model.users[k.k] || []).length}</span>
						</button>
					))}
				</div>
			))}
		</div>
		{arch && (
			<div className="aag-arch" data-el={arch.element}>
				<h3 className="aag-h3">{arch.name}</h3>
				<p className="aag-p">{arch.how}</p>
				<div className="aag-archgrid">
					<div><div className="aag-rel-hd">Core makers</div><MiniList keys={arch.makers.map((n) => keyOf("aura", slug(n)))} ctx={ctx} /></div>
					<div><div className="aag-rel-hd">Core payoffs</div><MiniList keys={arch.payoffs.map((n) => keyOf("aura", slug(n)))} ctx={ctx} /></div>
					<div><div className="aag-rel-hd">Gambits · imprints</div><MiniList keys={[
						...arch.gambits.map((g) => ctx.model.list.find((x) => x.type === "gambit" && x.name === g)?.key).filter(Boolean),
						...arch.imprints.map((n) => keyOf("imprint", slug(n)))]} ctx={ctx} /></div>
					{(arch.summon || arch.echo) && <div><div className="aag-rel-hd">Summon · echo</div><MiniList keys={[
						arch.summon && keyOf("summon", slug(arch.summon)), arch.echo && keyOf("echo", slug(arch.echo))].filter(Boolean)} ctx={ctx} /></div>}
				</div>
			</div>
		)}
		{e && <div className="aag-panel"><div className="aag-dhead"><span className="aag-dtype">Effect</span><h2 className="aag-dname">{e.name}</h2><ElementTag el={e.element} /></div>
			<EffectBody e={e} ctx={ctx} /></div>}
		<Section title="All build outlines">
			<div className="aag-grid">
				{ED.ARCHETYPES.map((a) => (
					<button type="button" key={a.name} className="aag-pick" data-el={a.element} onClick={() => { setPick(a.effect); window.scrollTo({ top: 0, behavior: "smooth" }); }}>
						<span className="aag-pick-name">{a.name}</span><ElementTag el={a.element} /><span className="aag-pick-why">{a.how}</span>
					</button>
				))}
			</div>
		</Section>
	</>);
}

function TierBoard({ list, tiers, ctx, keyFor }) {
	return (
		<div className="aag-tierboard">
			{Object.entries(tiers).map(([t, rows]) => (
				<div key={t} className="aag-tierrow">
					<div className="aag-tierlbl" data-tier={t}>{t}</div>
					<div className="aag-tieritems">
						{rows.map(([name, why]) => {
							const k = keyFor(name);
							const e = ctx.model.byKey[k];
							return (
								<button type="button" key={name} className="aag-tieritem" data-el={e?.element} onClick={() => ctx.open(k)}>
									<b>{name}</b><span>{why}</span>
								</button>
							);
						})}
					</div>
				</div>
			))}
			<span className="aag-sr">{list}</span>
		</div>
	);
}

function TiersTab({ ctx }) {
	const [which, setWhich] = useState("echoes");
	const lists = [
		["echoes", "Echoes", (n) => keyOf("echo", slug(n))],
		["imprints", "Imprints", (n) => keyOf("imprint", slug(n))],
		["auras", "Auras", (n) => keyOf("aura", slug(n))],
		["summons", "Summons", (n) => keyOf("summon", slug(n))],
		["spells", "Spells by the numbers", null],
	];
	const cur = lists.find((l) => l[0] === which);
	return (<>
		<p className="aag-sub">Editor's picks: no community tier list for Astral Ascent exists to cite, so these are judged from the wiki's own
			descriptions. The criteria are stated with each list. Tap any entry for its full text.</p>
		<div className="aag-seg aag-seg-big" role="tablist" aria-label="Tier list">
			{lists.map(([id, label]) => <button type="button" key={id} role="tab" aria-selected={which === id} aria-pressed={which === id} onClick={() => setWhich(id)}>{label}</button>)}
		</div>
		{which !== "spells" ? (<>
			<p className="aag-sub"><b>Judged on:</b> {ED.TIER_NOTES[which]}</p>
			<TierBoard list={cur[1]} tiers={ED.TIERS[which]} ctx={ctx} keyFor={cur[2]} />
		</>) : <SpellTiers ctx={ctx} />}
	</>);
}

// Spells ranked by damage per mana WITHIN their cost, since a 1-mana spell also buys a
// faster Spell Refresh. Tiers are quartiles of that cost bracket — computed, not judged.
function SpellTiers({ ctx }) {
	const spells = ctx.model.list.filter((e) => e.type === "spell" && e.dpm != null && e.group !== "Hero");
	return (<>
		<p className="aag-sub"><b>Computed:</b> shared spells (common and Zodiac) ranked by damage per mana within each mana cost, split into quartiles.
			Hero spells are left out because only that hero can take them; sort them in the Spells tab.</p>
		{[1, 2, 3].map((m) => {
			const row = spells.filter((s) => s.mana === m).sort((a, b) => b.dpm - a.dpm);
			if (!row.length) return null;
			const q = (i) => ["S", "A", "B", "C"][Math.min(3, Math.floor((i / row.length) * 4))];
			const tiers = {};
			row.forEach((s, i) => (tiers[q(i)] ||= []).push([s.name, `${s.dmg} dmg · ${s.hits} hits · ${s.dpm}/mana`]));
			return (
				<Section key={m} title={`${m}-mana spells`}>
					<TierBoard list={`${m} mana`} tiers={tiers} ctx={ctx} keyFor={(n) => keyOf("spell", slug(n))} />
				</Section>
			);
		})}
	</>);
}

// ── Charts ─────────────────────────────────────────────────────────────────
// Heat cells: one hue (the site's gold) from the surface up, so magnitude reads as
// brightness. Ink flips to dark on the bright end.
function heat(t) {
	const p = Math.round(6 + Math.max(0, Math.min(1, t)) * 78);
	return { background: `color-mix(in oklab, var(--gold) ${p}%, var(--surface))`, color: p > 58 ? "#17140f" : "var(--text)" };
}

function NumField({ label, value, set, min, max, step = 1, suffix }) {
	return (
		<label className="aag-nf">
			<span className="aag-nf-l">{label} <b>{fmt(value)}{suffix}</b></span>
			<input type="range" min={min} max={max} step={step} value={value} onChange={(e) => set(Number(e.target.value))} />
			<input type="number" min={min} max={max} step={step} value={value} aria-label={label}
				onChange={(e) => { const v = Number(e.target.value); if (Number.isFinite(v)) set(Math.max(min, Math.min(max, v))); }} />
		</label>
	);
}

function ChartsTab({ ctx }) {
	const s = ctx.data.stats;
	const [chance, setChance] = useState(20);
	const [bonus, setBonus] = useState(s.critBonus);
	const [str, setStr] = useState(50);
	const [life, setLife] = useState(300);
	const [stones, setStones] = useState(5);
	const [extra, setExtra] = useState(0);
	const armor = armorPct(stones, extra, s.armorCap, s.armorPerStone);
	const mult = critMultiplier(chance, bonus);
	const ds = nextDamageStone(str, chance, bonus, { str: s.strengthPerStone, crit: s.critPerStone });
	const ns = nextStone(life, armor, { cap: s.armorCap, perStone: s.armorPerStone, lifePerStone: s.lifePerStone });
	const be = breakEvenLife(armor, s.armorPerStone, s.lifePerStone);

	const CH = [0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100];
	const BO = [50, 60, 70, 80, 90, 100, 125, 150, 200];
	const maxM = critMultiplier(100, 200);
	const LIFE = [150, 225, 300, 375, 450, 525, 600, 675, 750, 900, 1050, 1200];
	const ST = [0, 2, 4, 6, 8, 10, 12, 14, 16, 18, 20, 22, 24];
	const maxE = effectiveLife(1200, s.armorCap);
	const near = (arr, v) => arr.reduce((b, x) => (Math.abs(x - v) < Math.abs(b - v) ? x : b), arr[0]);
	const nc = near(CH, chance), nb = near(BO, bonus), nl = near(LIFE, life), nst = near(ST, stones);

	return (<>
		<Section title="Critical hits" sub={`A crit deals +${s.critBonus}% MORE damage by default, multiplying everything else. Your average damage is 1 + chance × crit bonus.`}>
			<div className="aag-calc">
				<div className="aag-calc-in">
					<NumField label="Crit chance" value={chance} set={setChance} min={0} max={100} suffix="%" />
					<NumField label="Crit damage bonus" value={bonus} set={setBonus} min={0} max={250} step={5} suffix="%" />
					<p className="aag-hint">Raise the bonus with Sixth Sense (+{s.sixthSensePerTier}% per tier, Void Catalyst), The Arrow (+50%, Cursed Telescope),
						Balance Master or Disorienting Weapon (+25%), Eye of the Eagle or Weakspot (+15%).</p>
				</div>
				<div className="aag-calc-out">
					<div className="aag-big"><b>×{mult.toFixed(3)}</b><span>average damage from crits ({mult >= 1 ? "+" : ""}{((mult - 1) * 100).toFixed(1)}%)</span></div>
					<NumField label="Your increased damage (Strength etc.)" value={str} set={setStr} min={0} max={500} step={5} suffix="%" />
					<div className="aag-vs">
						<div><b>+{(ds.strGain * 100).toFixed(2)}%</b><span>next Strength stone</span></div>
						<div><b>+{(ds.critGain * 100).toFixed(2)}%</b><span>next Crit stone</span></div>
					</div>
					<p className="aag-verdict">{ds.strGain >= ds.critGain ? "Strength is the better stone here." : "Crit is the better stone here."}</p>
				</div>
			</div>
			<HeatTable caption="Average damage multiplier: crit chance (rows) × crit damage bonus (columns)" rowsLbl="Chance" colsLbl="Bonus"
				rows={CH} cols={BO} rowFmt={(r) => `${r}%`} colFmt={(c) => `+${c}%`}
				cell={(r, c) => critMultiplier(r, c)} cellFmt={(v) => `×${v.toFixed(2)}`} norm={(v) => (v - 1) / (maxM - 1)}
				hi={[nc, nb]} />
		</Section>

		<Section title="Life and armor" sub={`Effective life = life ÷ (1 − armor). Armor is ${s.armorPerStone}% per stone, capped at ${s.armorCap}%, so each stone adds more than the last.`}>
			<div className="aag-calc">
				<div className="aag-calc-in">
					<NumField label="Max life" value={life} set={setLife} min={50} max={2000} step={5} />
					<NumField label="Armor stones" value={stones} set={setStones} min={0} max={24} />
					<NumField label="Armor from auras" value={extra} set={setExtra} min={0} max={50} suffix="%" />
				</div>
				<div className="aag-calc-out">
					<div className="aag-big"><b>{fmt(ns.now)}</b><span>effective life at {armor}% armor{armor >= s.armorCap ? " (capped)" : ""}</span></div>
					<div className="aag-vs">
						<div><b>+{fmt(ns.lifeGain, 1)}</b><span>next Life stone (+{s.lifePerStone})</span></div>
						<div><b>+{fmt(ns.armorGain, 1)}</b><span>next Armor stone (+{s.armorPerStone}%)</span></div>
					</div>
					<p className="aag-verdict">{armor >= s.armorCap ? "Armor is capped — take Life." : ns.armorGain >= ns.lifeGain ? "Armor is the better stone here." : "Life is the better stone here."}
						{armor < s.armorCap && <> Break-even at {fmt(be)} life with your armor.</>}</p>
				</div>
			</div>
			<StoneChart armor={armor} life={life} s={s} />
			<HeatTable caption="Effective life: max life (rows) × armor stones (columns)" rowsLbl="Life" colsLbl="Stones"
				rows={LIFE} cols={ST} rowFmt={(r) => fmt(r)} colFmt={(c) => `${c} · ${armorPct(c, 0, s.armorCap, s.armorPerStone)}%`}
				cell={(r, c) => effectiveLife(r, armorPct(c, 0, s.armorCap, s.armorPerStone))} cellFmt={(v) => fmt(v)} norm={(v) => v / maxE}
				hi={[nl, nst]} />
		</Section>
	</>);
}

function HeatTable({ caption, rows, cols, rowFmt, colFmt, cell, cellFmt, norm, hi, rowsLbl, colsLbl }) {
	const [hover, setHover] = useState(null);
	return (
		<div className="aag-tablewrap aag-heatwrap">
			<table className="aag-heat" onMouseLeave={() => setHover(null)}>
				<caption>{caption}</caption>
				<thead><tr><th scope="col">{rowsLbl} \ {colsLbl}</th>{cols.map((c) => <th scope="col" key={c} className={c === hi[1] ? "hi" : ""}>{colFmt(c)}</th>)}</tr></thead>
				<tbody>
					{rows.map((r) => (
						<tr key={r}>
							<th scope="row" className={r === hi[0] ? "hi" : ""}>{rowFmt(r)}</th>
							{cols.map((c) => {
								const v = cell(r, c);
								const mine = r === hi[0] && c === hi[1];
								const hov = hover && (hover[0] === r || hover[1] === c);
								return (
									<td key={c} style={heat(norm(v))} className={`${mine ? "mine" : ""}${hov ? " hov" : ""}`}
										title={`${rowsLbl} ${rowFmt(r)}, ${colsLbl} ${colFmt(c)}: ${cellFmt(v)}`}
										onMouseEnter={() => setHover([r, c])}>{cellFmt(v)}</td>
								);
							})}
						</tr>
					))}
				</tbody>
			</table>
		</div>
	);
}

// The one line chart: what the NEXT stone of each kind adds, across max life, at your
// armor. The two lines cross at the break-even life — the wiki's "~500 life" rule.
function StoneChart({ armor, life, s }) {
	const W = 640, H = 240, P = { l: 44, r: 16, t: 16, b: 34 };
	const X0 = 100, X1 = 1500;
	const xs = Array.from({ length: 57 }, (_, i) => X0 + i * 25);
	const pts = xs.map((L) => ({ L, ...nextStone(L, armor, { cap: s.armorCap, perStone: s.armorPerStone, lifePerStone: s.lifePerStone }) }));
	const yMax = Math.max(10, ...pts.map((p) => Math.max(p.lifeGain, p.armorGain))) * 1.08;
	const x = (L) => P.l + ((L - X0) / (X1 - X0)) * (W - P.l - P.r);
	const y = (v) => H - P.b - (v / yMax) * (H - P.t - P.b);
	const path = (k) => pts.map((p, i) => `${i ? "L" : "M"}${x(p.L).toFixed(1)},${y(p[k]).toFixed(1)}`).join("");
	const [hov, setHov] = useState(null);
	const svgRef = useRef(null);
	const onMove = (ev) => {
		const r = svgRef.current.getBoundingClientRect();
		const L = X0 + ((ev.clientX - r.left) / r.width * W - P.l) / (W - P.l - P.r) * (X1 - X0);
		setHov(pts.reduce((b, p) => (Math.abs(p.L - L) < Math.abs(b.L - L) ? p : b), pts[0]));
	};
	const be = breakEvenLife(armor, s.armorPerStone, s.lifePerStone);
	const ticks = [250, 500, 750, 1000, 1250, 1500];
	const yt = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round((yMax / 1.08) * f));
	const last = pts[pts.length - 1];
	const capped = armor >= s.armorCap;
	return (
		<figure className="aag-fig">
			<figcaption className="aag-figcap">Effective life added by your next stone, at {armor}% armor</figcaption>
			<div className="aag-legend">
				<span><i style={{ background: "var(--aag-s1)" }} />Life stone (+{s.lifePerStone})</span>
				<span><i style={{ background: "var(--aag-s2)" }} />Armor stone (+{s.armorPerStone}%)</span>
			</div>
			<div className="aag-chartbox">
				<svg ref={svgRef} viewBox={`0 0 ${W} ${H}`} className="aag-svg" role="img"
					aria-label={`Life stone versus armor stone value; they cross at ${fmt(be)} life`}
					onPointerMove={onMove} onPointerLeave={() => setHov(null)}>
					{yt.map((v) => <g key={v}><line x1={P.l} x2={W - P.r} y1={y(v)} y2={y(v)} className="aag-grid-l" />
						<text x={P.l - 6} y={y(v) + 4} className="aag-ax" textAnchor="end">{v}</text></g>)}
					{ticks.map((t) => <text key={t} x={x(t)} y={H - 12} className="aag-ax" textAnchor="middle">{t}</text>)}
					<text x={W - P.r} y={H - 1} className="aag-ax" textAnchor="end">max life</text>
					{!capped && be > X0 && be < X1 && <g>
						<line x1={x(be)} x2={x(be)} y1={P.t} y2={H - P.b} className="aag-be" />
						<text x={x(be) + 4} y={P.t + 10} className="aag-ax">break-even {fmt(be)}</text></g>}
					<line x1={x(Math.min(X1, Math.max(X0, life)))} x2={x(Math.min(X1, Math.max(X0, life)))} y1={P.t} y2={H - P.b} className="aag-you" />
					<path d={path("lifeGain")} className="aag-line" style={{ stroke: "var(--aag-s1)" }} />
					<path d={path("armorGain")} className="aag-line" style={{ stroke: "var(--aag-s2)" }} />
					<text x={x(last.L) - 4} y={y(last.lifeGain) - 6} className="aag-dl1" textAnchor="end">Life</text>
					<text x={x(last.L) - 4} y={y(last.armorGain) - 6} className="aag-dl2" textAnchor="end">Armor</text>
					{hov && <g>
						<line x1={x(hov.L)} x2={x(hov.L)} y1={P.t} y2={H - P.b} className="aag-xh" />
						<circle cx={x(hov.L)} cy={y(hov.lifeGain)} r="4" className="aag-dot" style={{ fill: "var(--aag-s1)" }} />
						<circle cx={x(hov.L)} cy={y(hov.armorGain)} r="4" className="aag-dot" style={{ fill: "var(--aag-s2)" }} />
					</g>}
				</svg>
				{hov && (
					<div className="aag-tip" style={{ left: `${(x(hov.L) / W) * 100}%` }}>
						<div className="aag-tip-hd">{fmt(hov.L)} life</div>
						<div><i style={{ background: "var(--aag-s1)" }} /><b>+{fmt(hov.lifeGain, 1)}</b> Life stone</div>
						<div><i style={{ background: "var(--aag-s2)" }} /><b>+{fmt(hov.armorGain, 1)}</b> Armor stone</div>
					</div>
				)}
			</div>
		</figure>
	);
}

// ── Bosses ─────────────────────────────────────────────────────────────────
const WORLD_ORDER = ["Fragmented Plains", "Red Barrens", "Coral Archipelago", "Crimson Highlands", "Event Horizon"];

// In a card the strategy is its first paragraph with the rest folded; the drawer
// (`open`) shows all of it.
function BossBody({ b, ctx, open }) {
	const paras = (b.strategy || "").split("\n").map((l) => l.replace(/^[*#\s]+/, "")).filter(Boolean);
	const shown = open ? paras : paras.slice(0, 1);
	return (<>
		<p className="aag-p">{b.kind}{b.world ? ` · ${b.world}` : ""}{b.hp ? ` · ${fmt(b.hp)} HP (base)` : ""}</p>
		{paras.length > 0 && <><h3 className="aag-h3">Strategy</h3>{shown.map((l, i) => <p key={i} className="aag-p">{l}</p>)}
			{!open && paras.length > 1 && (
				<details className="aag-atk"><summary>More strategy ({paras.length - 1})</summary>
					{paras.slice(1).map((l, i) => <p key={i} className="aag-p">{l}</p>)}</details>
			)}</>}
		<details className="aag-atk" open={open}>
			<summary>Attacks ({b.attacks.length})</summary>
			<dl className="aag-dl">{b.attacks.map((a, i) => <Fragment key={i}><dt>{a.name || "—"}</dt><dd><Rich text={a.text} ctx={ctx} /></dd></Fragment>)}</dl>
		</details>
	</>);
}

function BossesTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "boss");
	const list = all.filter((e) => matches(e, f.q));
	const groups = [...WORLD_ORDER.map((w) => [w, list.filter((b) => b.world === w)]), ["Star Guardians (Void rooms)", list.filter((b) => b.kind === "Star Guardian")]];
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter bosses or attacks…" count={list.length} total={all.length} />
		{groups.filter(([, l]) => l.length).map(([w, l]) => (
			<Section key={w} title={w}>
				<div className="aag-grid">{l.map((b) => (
					<article key={b.key} className="aag-card">
						<header className="aag-card-hd">
							<button type="button" className="aag-name" onClick={() => ctx.open(b.key)}>{b.name}</button>
							<span className="aag-card-tags">{b.hp && <span className="aag-pill">{fmt(b.hp)} HP</span>}</span>
						</header>
						<BossBody b={b} ctx={ctx} />
					</article>
				))}</div>
			</Section>
		))}
		{!list.length && <Empty />}
	</>);
}

// ── Meta: Void Catalyst, the telescopes, Destiny levels ────────────────────
function MetaTab({ ctx, f, set }) {
	const [part, setPart] = useState("catalyst");
	const parts = [["catalyst", "Void Catalyst"], ["telluric", "Telluric Telescope"], ["cursed", "Cursed Telescope"], ["destiny", "Destiny levels"]];
	const ofType = (t) => ctx.model.list.filter((e) => e.type === t && matches(e, f.q));
	const picks10 = new Map(ED.CATALYST_PICKS.first10), picks50 = new Map(ED.CATALYST_PICKS.first50);
	return (<>
		<div className="aag-seg aag-seg-big" role="tablist" aria-label="Section">
			{parts.map(([id, l]) => <button type="button" key={id} role="tab" aria-selected={part === id} aria-pressed={part === id} onClick={() => setPart(id)}>{l}</button>)}
		</div>
		{part !== "destiny" && <FilterBar f={f} set={set} placeholder="Filter…" count={ofType(part).length} total={ctx.model.list.filter((e) => e.type === part).length} />}
		{part === "catalyst" && (<>
			<p className="aag-sub">Unlocked after your first win and powered by Destiny Fragments (1 per Zodiac per Destiny level, 3 for the Master; 15 per level).
				Reset freely. Badges show the wiki's recommended first 10 and first 50 fragments.</p>
			{["Row 1", "Row 2", "Row 3"].map((r) => (
				<Section key={r} title={r}>
					<div className="aag-grid">{ofType("catalyst").filter((c) => c.row === r).map((c) => (
						<article key={c.key} className="aag-card">
							<header className="aag-card-hd">
								<button type="button" className="aag-name" onClick={() => ctx.open(c.key)}>{c.name}</button>
								<span className="aag-card-tags">
									{picks10.has(c.name) && <span className="aag-pill aag-pill-gold">First 10: {picks10.get(c.name)}</span>}
									{picks50.has(c.name) && <span className="aag-pill">First 50: {picks50.get(c.name)}</span>}
								</span>
							</header>
							<p className="aag-p">{c.desc}</p>
							<div className="aag-card-ft">Cost per tier: {c.cost}</div>
						</article>
					))}</div>
				</Section>
			))}
		</>)}
		{part === "telluric" && (<>
			<p className="aag-sub">From Sire Bapy after a number of runs: pick one of 3 modifiers that rotate every 24 hours. It applies to every run until it expires.</p>
			<div className="aag-grid">{ofType("telluric").map((t) => (
				<article key={t.key} className="aag-card aag-card-sm">
					<header className="aag-card-hd"><button type="button" className="aag-name" onClick={() => ctx.open(t.key)}>{t.name}</button></header>
					<p className="aag-p">{t.desc}</p>{t.synergy && <p className="aag-p aag-muted">{t.synergy}</p>}
				</article>))}</div>
		</>)}
		{part === "cursed" && (<>
			<p className="aag-sub">A room offering 3 permanent perks, each with a malus that lasts until you next enter Andromeda's Bar.</p>
			{["Perk", "Malus"].map((k) => (
				<Section key={k} title={k === "Perk" ? "Perks" : "Malus (the cost)"}>
					<div className="aag-grid">{ofType("cursed").filter((c) => c.kind === k).map((c) => (
						<article key={c.key} className="aag-card aag-card-sm" data-bad={k === "Malus" || undefined}>
							<header className="aag-card-hd"><button type="button" className="aag-name" onClick={() => ctx.open(c.key)}>{c.name}</button></header>
							<p className="aag-p"><Rich text={c.desc} ctx={ctx} /></p>
						</article>))}</div>
				</Section>
			))}
		</>)}
		{part === "destiny" && (<>
			<p className="aag-sub">After your first win, each Malice modifier raises the Destiny level by one. Levels 1–6 are fixed and must be cleared in order.</p>
			<dl className="aag-dl">{ctx.data.destiny.map((d) => <Fragment key={d.level}><dt>Level {d.level}: {d.name}</dt><dd>{d.text}</dd></Fragment>)}</dl>
		</>)}
	</>);
}

function GlossaryTab({ ctx, f, set }) {
	const all = ctx.model.list.filter((e) => e.type === "effect");
	const list = all.filter((e) => matches(e, f.q) && (!f.el.length || f.el.includes(e.element)));
	return (<>
		<FilterBar f={f} set={set} placeholder="Filter effects…" count={list.length} total={all.length}>
			<Chips label="Element" options={ELEMENTS} value={f.el} onChange={(v) => set({ el: v })} colorBy="el" />
		</FilterBar>
		<p className="aag-sub">Every elemental gambit, aura, summon and prowess can apply its element's affliction. Tap an effect for what makes it and what pays it off.</p>
		<div className="aag-grid aag-grid-sm">
			{list.map((e) => (
				<article key={e.key} className="aag-card aag-card-sm" data-el={e.element}>
					<header className="aag-card-hd">
						<button type="button" className="aag-name" onClick={() => ctx.open(e.key)}>{e.name}</button>
						<span className="aag-card-tags"><ElementTag el={e.element} /></span>
					</header>
					{e.desc && <p className="aag-p">{e.desc}</p>}
					<div className="aag-card-ft">{(ctx.model.makers[e.name] || []).length} makers · {(ctx.model.users[e.name] || []).length} payoffs</div>
				</article>
			))}
		</div>
		<Section title="Spell tags">
			<dl className="aag-dl">
				<dt>Duration</dt><dd>Part of the spell happens over time.</dd>
				<dt>Stackable</dt><dd>Happens around the player and stacks with other casts of the same spell.</dd>
				<dt>Homing</dt><dd>Travels toward enemies on its own.</dd>
				<dt>Single Target</dt><dd>Each hit can only hit one enemy.</dd>
				<dt>Weapon Buff</dt><dd>A stackable buff activated by basic attacks.</dd>
				<dt>Channeled</dt><dd>A continuous effect you channel.</dd>
				<dt>Dodge</dt><dd>Makes the player intangible.</dd>
				<dt>Pull / Push</dt><dd>Pulls enemies in, or pushes them away.</dd>
			</dl>
		</Section>
		<Section title="Rules worth knowing">
			<dl className="aag-dl">
				<dt>Spell Refresh</dt><dd>A cast spell is locked until all four have been cast; then all refresh at once, triggering every "On Spell Refresh" effect.</dd>
				<dt>Unique</dt><dd>Several copies of an aura stack, except effects marked Unique: only one copy of those works.</dd>
				<dt>Separate rolls</dt><dd>Each gambit trigger is its own event: two 50% chances are two chances, not 100%.</dd>
				<dt>Healing Shards</dt><dd>Heal 5% of max life each, or 10% each (50%) at five. A shard picked up at five heals 10 instead.</dd>
				<dt>Aura Refiner</dt><dd>At Andromeda's Bar: Common → Heroic or Heroic → Mythic, twice per run (more with Star-Forged).</dd>
			</dl>
		</Section>
	</>);
}

// ── The page ───────────────────────────────────────────────────────────────
const FILTER_DEFAULTS = { q: "", el: [], rar: [], trig: [], fx: [], kind: [], need: [], grp: [], mana: [], tag: [], hero: [], path: [], tier: [] };

export default function AstralGuide({ onExit }) {
	const [data, setData] = useState(null);
	const [err, setErr] = useState("");
	const [tab, setTab] = useState(routeTab);
	const [filters, setFilters] = useState({});
	const [focus, setFocus] = useState(null);
	const [stack, setStack] = useState(() => (hashKey() ? [hashKey()] : []));
	const searchRef = useRef(null);
	const tabsRef = useRef(null);

	useEffect(() => {
		let live = true;
		fetch(DATA_URL)
			.then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); })
			.then((j) => { if (live) setData(j); })
			.catch((e) => { if (live) setErr(String(e.message || e)); });
		return () => { live = false; };
	}, []);

	const model = useMemo(() => (data ? buildModel(data, ED) : null), [data]);
	const tierIndex = useMemo(() => {
		const out = {};
		const types = { echoes: "echo", imprints: "imprint", auras: "aura", summons: "summon" };
		const label = { echoes: "Echo", imprints: "Imprint", auras: "Aura", summons: "Summon" };
		for (const [list, rows] of Object.entries(ED.TIERS)) {
			for (const [tier, items] of Object.entries(rows)) {
				for (const [name, why] of items) out[keyOf(types[list], slug(name))] = { tier, why, list: label[list] };
			}
		}
		return out;
	}, []);

	// Back/Forward: the path names the tab, the hash names the open entry.
	useEffect(() => subscribe((r) => {
		if (r.game !== "astral") return;
		setTab(routeTab());
		const h = hashKey();
		setStack(h ? [h] : []);
	}), []);

	// "/" focuses the search from anywhere; Escape closes the drawer.
	useEffect(() => {
		const onKey = (e) => {
			const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
			if (e.key === "/" && !typing) { e.preventDefault(); searchRef.current?.focus(); }
			else if (e.key === "Escape" && stack.length && !typing) closeDrawer();
		};
		window.addEventListener("keydown", onKey);
		return () => window.removeEventListener("keydown", onKey);
	});

	useEffect(() => {
		const b = tabsRef.current?.querySelector('[aria-selected="true"]');
		b?.scrollIntoView?.({ block: "nearest", inline: "center" });
	}, [tab]);

	const go = useCallback((t, q) => {
		setStack([]);
		setTab(t);
		if (t === "synergy" && q) setFocus(q);
		else if (q != null) setFilters((all) => ({ ...all, [t]: { ...FILTER_DEFAULTS, q } }));
		pushPath(buildPath("astral", t === "start" ? undefined : t));
		window.scrollTo({ top: 0 });
	}, []);

	const open = useCallback((k) => {
		setStack((s) => (s[s.length - 1] === k ? s : [...s, k]));
		try { window.history.pushState(window.history.state, "", `${window.location.pathname}#${encodeURIComponent(k)}`); } catch { /* sandboxed */ }
	}, []);

	const closeDrawer = useCallback(() => {
		setStack([]);
		try { window.history.replaceState(window.history.state, "", window.location.pathname); } catch { /* sandboxed */ }
	}, []);
	const backDrawer = useCallback(() => {
		setStack((s) => {
			const next = s.slice(0, -1);
			try { window.history.replaceState(window.history.state, "", `${window.location.pathname}${next.length ? `#${encodeURIComponent(next[next.length - 1])}` : ""}`); } catch { /* sandboxed */ }
			return next;
		});
	}, []);

	const f = { ...FILTER_DEFAULTS, ...(filters[tab] || {}) };
	const set = (patch) => setFilters((all) => ({ ...all, [tab]: patch === null ? { ...FILTER_DEFAULTS } : { ...FILTER_DEFAULTS, ...(all[tab] || {}), ...patch } }));

	const ctx = model && {
		data, model, open, go,
		tierOf: (k) => tierIndex[k],
		maxDpm: Math.max(...data.spells.map((s) => s.dpm || 0)),
	};

	const counts = model ? {
		auras: data.auras.length, gambits: model.list.filter((e) => e.type === "gambit").length, imprints: data.imprints.length,
		spells: data.spells.length, echoes: data.echoes.length + data.summons.length, prowess: data.prowess.length,
		bosses: data.bosses.length, glossary: KEYWORDS.length,
	} : {};

	const body = !ctx ? null : (() => {
		const p = { ctx, f, set };
		switch (tab) {
			case "auras": return <AurasTab {...p} />;
			case "gambits": return <GambitsTab {...p} />;
			case "imprints": return <ImprintsTab {...p} />;
			case "spells": return <SpellsTab {...p} />;
			case "echoes": return <EchoesTab {...p} />;
			case "prowess": return <ProwessTab {...p} />;
			case "synergy": return <SynergyTab ctx={ctx} focus={focus} />;
			case "tiers": return <TiersTab ctx={ctx} />;
			case "charts": return <ChartsTab ctx={ctx} />;
			case "bosses": return <BossesTab {...p} />;
			case "meta": return <MetaTab {...p} />;
			case "glossary": return <GlossaryTab {...p} />;
			default: return <StartTab ctx={ctx} />;
		}
	})();

	return (
		<>
			<style>{baseCss + css}</style>
			<div className="aag">
				<header className="aag-top">
					<div className="aag-bar">
						<button className="btn btn-ghost btn-sm aag-back" onClick={onExit}>← Back</button>
						<button type="button" className="aag-title" onClick={() => go("start")}>Astral Ascent Guide</button>
						{ctx && <GlobalSearch ctx={ctx} inputRef={searchRef} />}
					</div>
					<nav className="aag-tabs" role="tablist" aria-label="Guide sections" ref={tabsRef}>
						{TABS.map((t) => (
							<button type="button" key={t.id} role="tab" aria-selected={tab === t.id} className="aag-tab" onClick={() => go(t.id)}>
								{t.label}{counts[t.id] ? <span className="aag-tabn">{counts[t.id]}</span> : null}
							</button>
						))}
					</nav>
				</header>
				<main className="aag-main" data-tab={tab}>
					{err && <div className="aag-loading">Couldn’t load the guide data ({err}).</div>}
					{!err && !ctx && <div className="aag-loading">Loading the guide…</div>}
					{body}
				</main>
				{ctx && stack.length > 0 && (
					<Drawer k={stack[stack.length - 1]} ctx={ctx} onClose={closeDrawer} onBack={backDrawer} canBack={stack.length > 1} />
				)}
			</div>
		</>
	);
}
