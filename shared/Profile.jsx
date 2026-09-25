/* The profile — a signed-in player's own results across every game.
 *
 * Private: GET /profile (core/results.py) only ever answers for the session that
 * asks, and a guest has no profile at all. It is reached by clicking your name on
 * the home menu or in any lobby's top bar (LobbyUser), and Back returns there.
 *
 * Everything on the page is computed HERE from one list of rows, one row per
 * finished game. The server sends the rows and nothing else, so the numbers at
 * the top, the per-game records and the history below can never disagree.
 *
 * Bot tiers are named from shared/botTiers.js, the lists each game's create modal
 * renders, so a tier reads the same here as it does in that game's lobby.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { baseCss } from "./theme.js";
import {
	lobbyCss, LobbyHeader, LobbyHero, LobbyUser, LobbySectionHd, LobbyEmpty, LobbyLoading,
	useProgressiveList, timeAgo,
} from "./lobby.jsx";
import { GAME_INFO } from "./catalog.js";
import { GAME_EMBLEM } from "./emblems.jsx";
import { botTierLabel } from "./botTiers.js";
import { SESSION_EXPIRED } from "./lobbyHistory.js";
import _css from "./Profile.css?inline";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");
const styles = baseCss + lobbyCss + _css;

const readCache = (key) => { try { return JSON.parse(localStorage.getItem(key) || "null"); } catch { return null; } };
const writeCache = (key, v) => { try { localStorage.setItem(key, JSON.stringify(v)); } catch { /* full or blocked */ } };

const titled = (s) => String(s || "").replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase());
const pct = (n, d) => (d ? `${Math.round((100 * n) / d)}%` : "—");
const gameName = (id) => GAME_INFO[id]?.name || titled(id);
const dateOf = (t) => new Date(t * 1000).toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
// W–L, and –D only when there were draws: most games cannot draw, and a row of
// "–0" on every record is noise the reader has to skip.
const record = (r) => `${r.wins}–${r.losses}${r.draws ? `–${r.draws}` : ""}`;

// The mode a row was played in, when it is not the game's default.
const MODE_DEFAULTS = new Set(["classic", "standard"]);
const modeLabel = (m) => (m && !MODE_DEFAULTS.has(m) ? titled(m) : null);

// Who a player was up against, as the page names them. A bot is its TIER ("Expert
// AI") — its seat name is a code on some games ("AI (N)") and just "Bot" on others.
function opponentLabel(game, row, p) {
	if (!p.bot) return p.name;
	const tier = botTierLabel(game, row.ai_tier);
	return tier ? `${tier} AI` : p.name || "Bot";
}
const others = (row) => row.players.filter((p) => !p.you);

function tally(rows) {
	const t = { played: rows.length, wins: 0, losses: 0, draws: 0 };
	for (const r of rows) {
		if (r.outcome === "win") t.wins += 1;
		else if (r.outcome === "loss") t.losses += 1;
		else t.draws += 1;
	}
	return t;
}

// Per game: the record, and the record against each kind of opponent — people, or
// each bot tier. Sorted most-played first, which is also how "favourite" is read.
function byGame(rows) {
	const games = new Map();
	for (const r of rows) {
		if (!games.has(r.game)) games.set(r.game, []);
		games.get(r.game).push(r);
	}
	return [...games.entries()].map(([game, list]) => {
		const splits = new Map();
		for (const r of list) {
			const key = r.vs_bot ? (r.ai_tier || "bot") : "people";
			if (!splits.has(key)) splits.set(key, []);
			splits.get(key).push(r);
		}
		const vs = [...splits.entries()].map(([key, l]) => ({
			key,
			label: key === "people" ? "people" : key === "bot" ? "the bot" : `${botTierLabel(game, key)} AI`,
			...tally(l),
		})).sort((a, b) => b.played - a.played);
		return { game, ...tally(list), last: Math.max(...list.map((r) => r.finished_at)), vs };
	}).sort((a, b) => b.played - a.played || b.last - a.last);
}

// ─── the win / draw / loss bar ───────────────────────────────────────────────
// Three segments on one track: won (teal), drawn (neutral gray), lost (orange).
// Validated on the page's dark surface for every PAIR, not just neighbours —
// with no draws, won and lost sit side by side (teal/orange holds at ΔE 12 under
// protan; green/orange collapsed to 2.7 under deutan, which is why it is not the
// Won stamp's green). The counts are always printed beside it, so colour is never
// the only way to read it.
function RecordBar({ r }) {
	const parts = [["win", r.wins], ["draw", r.draws], ["loss", r.losses]].filter(([, n]) => n > 0);
	const tip = `${r.wins} won · ${r.draws ? `${r.draws} drawn · ` : ""}${r.losses} lost`;
	return (
		<div className="pf-bar" role="img" aria-label={tip} title={tip}>
			{parts.map(([k, n]) => <span key={k} className={`pf-seg pf-${k}`} style={{ flexGrow: n }} />)}
		</div>
	);
}

function Summary({ rows, games }) {
	const t = tally(rows);
	const fav = games[0];
	const last = rows[0];
	return (
		<div className="pf-tiles">
			<div className="pf-tile"><span className="pf-tile-k">Games</span><span className="pf-tile-v">{t.played}</span></div>
			<div className="pf-tile">
				<span className="pf-tile-k">Win rate</span><span className="pf-tile-v">{pct(t.wins, t.played)}</span>
				<span className="pf-tile-sub">{record(t)}{t.draws ? " (W–L–D)" : " (W–L)"}</span>
			</div>
			<div className="pf-tile">
				<span className="pf-tile-k">Most played</span><span className="pf-tile-v pf-tile-word">{gameName(fav.game)}</span>
				<span className="pf-tile-sub">{fav.played} game{fav.played === 1 ? "" : "s"}</span>
			</div>
			<div className="pf-tile">
				<span className="pf-tile-k">Last played</span><span className="pf-tile-v pf-tile-word">{gameName(last.game)}</span>
				<span className="pf-tile-sub">{timeAgo(last.finished_at)}</span>
			</div>
		</div>
	);
}

function GameRecords({ games, onPick }) {
	return (
		<div className="pf-games">
			{games.map((g) => (
				<div key={g.game} className="pf-game" style={{ "--pf-accent": GAME_INFO[g.game]?.accent }}>
					<div className="pf-game-hd">
						<span className="pf-game-emblem" aria-hidden="true">{GAME_EMBLEM[g.game]}</span>
						<span className="pf-game-name">{gameName(g.game)}</span>
						<span className="pf-game-rate">{pct(g.wins, g.played)} won</span>
					</div>
					<RecordBar r={g} />
					<div className="pf-game-meta">
						<span>{g.played} game{g.played === 1 ? "" : "s"} · {record(g)}</span>
						<button type="button" className="pf-link" onClick={() => onPick(g.game)}>See games</button>
					</div>
					<ul className="pf-vs">
						{g.vs.map((v) => (
							<li key={v.key}><span className="pf-vs-who">vs {v.label}</span><span className="pf-vs-rec">{record(v)}</span></li>
						))}
					</ul>
				</div>
			))}
		</div>
	);
}

const STAMP = { win: ["won", "Won"], loss: ["lost", "Lost"], draw: ["tie", "Draw"] };

function HistoryRow({ row }) {
	const coop = row.game === "secretnames";
	const opp = others(row);
	const [cls, word] = STAMP[row.outcome] || STAMP.draw;
	const scores = row.players.some((p) => p.score != null) && !coop
		? [row.players.find((p) => p.you), ...opp].filter(Boolean).map((p) => p.score ?? "—")
		: null;
	const meta = [
		dateOf(row.finished_at),
		modeLabel(row.mode),
		row.detail && `as ${titled(row.detail)}`,
		coop && row.score != null && `${row.score} agents found`,
	].filter(Boolean);
	return (
		<div className="lby-card lby-card-hist pf-row">
			<div className="lby-card-info">
				<div className="lby-card-title">
					<span className={`hist-result ${cls}`}>{word}</span>
					<span className="pf-row-game">{gameName(row.game)}</span>
					<span className="hist-scores">
						{coop ? "with " : "vs "}{opp.map((p) => opponentLabel(row.game, row, p)).join(", ") || "—"}
						{scores && <> · <span className="hist-score-num">{scores[0]}</span>–{scores.slice(1).join("–")}</>}
					</span>
				</div>
				<div className="lby-card-meta">{meta.join(" · ")}</div>
			</div>
		</div>
	);
}

export default function Profile({ authUser, onExit }) {
	const token = authUser && !authUser.guest ? authUser.session_token : null;
	const cacheKey = `profile.history.${authUser?.id || "anon"}`;
	// Stale-while-revalidate, like Notes: the page paints from the last copy this
	// browser saw while a (possibly cold) backend answers.
	const [rows, setRows] = useState(() => (token ? readCache(cacheKey) : null));
	const [status, setStatus] = useState(token ? "loading" : "guest");   // loading | ok | error | expired | guest
	const [gameFilter, setGameFilter] = useState("");
	const [oppFilter, setOppFilter] = useState("");
	const [resultFilter, setResultFilter] = useState("");

	const authUserRef = useRef(authUser);
	authUserRef.current = authUser;
	const load = useCallback(async () => {
		if (!token) return;
		setStatus("loading");
		try {
			const res = await fetch(`${HTTP_BASE}/profile`, { headers: { Authorization: `Bearer ${token}` } });
			if (res.status === 401) {
				// A 401 here is definitive (GET /profile answers it only for a dead
				// session). Hand it to the shell the way the lobbies do: it signs out,
				// takes you to sign-in and brings you back to this page afterwards. The
				// "expired" state only shows if nothing is listening.
				setStatus("expired");
				window.dispatchEvent(new CustomEvent(SESSION_EXPIRED, { detail: { ...authUserRef.current, session_token: token } }));
				return;
			}
			if (!res.ok) throw new Error(`HTTP ${res.status}`);
			const body = await res.json();
			setRows(body.history || []);
			writeCache(cacheKey, body.history || []);
			setStatus("ok");
		} catch {
			setStatus("error");
		}
	}, [token, cacheKey]);
	useEffect(() => { load(); }, [load]);

	const all = rows || [];
	const games = useMemo(() => byGame(all), [all]);
	const opponents = useMemo(() => {
		const names = new Set();
		for (const r of all) for (const p of others(r)) names.add(opponentLabel(r.game, r, p));
		return [...names].sort((a, b) => a.localeCompare(b));
	}, [all]);
	const filtered = useMemo(() => all.filter((r) =>
		(!gameFilter || r.game === gameFilter)
		&& (!resultFilter || r.outcome === resultFilter)
		&& (!oppFilter || others(r).some((p) => opponentLabel(r.game, r, p) === oppFilter))), [all, gameFilter, oppFilter, resultFilter]);
	const [shown, sentinel] = useProgressiveList(filtered, { page: 20, max: Infinity });
	const oldest = all.length ? all[all.length - 1].finished_at : null;

	const pickGame = (g) => {
		setGameFilter(g);
		document.getElementById("pf-history")?.scrollIntoView({ behavior: "smooth", block: "start" });
	};

	let body;
	if (status === "guest") {
		body = <LobbyEmpty>Profiles are for registered players. Sign in with an account to get one.</LobbyEmpty>;
	} else if (status === "expired") {
		body = <LobbyEmpty>Your session has expired. Sign out and back in to see your profile.</LobbyEmpty>;
	} else if (!rows && status === "loading") {
		body = <LobbyLoading label="Loading your games…" />;
	} else if (!rows && status === "error") {
		body = (
			<LobbyEmpty>
				Couldn't load your profile. <button type="button" className="pf-link" onClick={load}>Try again</button>
			</LobbyEmpty>
		);
	} else if (!all.length) {
		body = <LobbyEmpty>No finished games yet. Every game you finish from now on shows up here.</LobbyEmpty>;
	} else {
		body = (
			<>
				{status === "error" && (
					<p className="pf-note" role="status">
						Showing the last copy this browser saw — the server didn't answer.{" "}
						<button type="button" className="pf-link" onClick={load}>Try again</button>
					</p>
				)}
				<Summary rows={all} games={games} />
				<section className="pf-section">
					<LobbySectionHd title="By game" note={`${games.length} game${games.length === 1 ? "" : "s"}`} />
					<GameRecords games={games} onPick={pickGame} />
				</section>
				<section className="pf-section" id="pf-history">
					<LobbySectionHd title="History" note={`${filtered.length} of ${all.length}`} />
					<div className="pf-filters">
						<label className="pf-filter"><span>Game</span>
							<select value={gameFilter} onChange={(e) => setGameFilter(e.target.value)}>
								<option value="">All games</option>
								{games.map((g) => <option key={g.game} value={g.game}>{gameName(g.game)}</option>)}
							</select>
						</label>
						<label className="pf-filter"><span>Opponent</span>
							<select value={oppFilter} onChange={(e) => setOppFilter(e.target.value)}>
								<option value="">Anyone</option>
								{opponents.map((o) => <option key={o} value={o}>{o}</option>)}
							</select>
						</label>
						<label className="pf-filter"><span>Result</span>
							<select value={resultFilter} onChange={(e) => setResultFilter(e.target.value)}>
								<option value="">Any result</option>
								<option value="win">Won</option>
								<option value="loss">Lost</option>
								<option value="draw">Draw</option>
							</select>
						</label>
					</div>
					{filtered.length
						? <div className="lby-list pf-list">{shown.map((r) => <HistoryRow key={`${r.game}:${r.id}`} row={r} />)}{sentinel}</div>
						: <LobbyEmpty>No games match these filters.</LobbyEmpty>}
				</section>
				{oldest && <p className="pf-note">Games finished since {dateOf(oldest)}.</p>}
			</>
		);
	}

	return (
		<div className="app pf-app">
			<style>{styles}</style>
			<LobbyHeader onBack={onExit} user={<LobbyUser user={authUser} profile={false} />} />
			<div className="lby-page"><div className="lby-page-in pf-in">
				<LobbyHero title={authUser?.name || "Profile"} players="Profile" />
				{body}
			</div></div>
		</div>
	);
}
