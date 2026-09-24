/* Site health — the owner's alerts panel, opened from the Extras tile on Home.
 *
 * Reads /admin/health (owner-only on the server, core/monitor.py): the recent owner
 * alerts, whether a push channel is configured, and a snapshot of what the monitor
 * watches (database size against its budget, memory, open tables, Notes storage).
 * The panel is the durable record; the push to the owner's phone is the alarm.
 *
 * Drawn in the shared RulesModal chrome (like Dissonance's scorecard), so it gets
 * the focus trap, Escape, and the one-scroller panel for free.
 */
import { useCallback, useEffect, useState } from "react";
import { RulesModal, RulesSection, RulesDefs, RulesTip } from "./lobby.jsx";
import _css from "./SiteHealth.css?inline";

const WS_BASE = import.meta.env.VITE_WS_URL || "ws://localhost:8000/ws";
const HTTP_BASE = WS_BASE.replace(/^ws/, "http").replace(/\/ws$/, "");

const HEALTH_GLYPH = (
	<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><path d="M3.5 12.5h4l2-5 4 10 2-5h5" /></svg>
);
export { HEALTH_GLYPH };

async function call(token, method, path) {
	const res = await fetch(HTTP_BASE + path, { method, headers: { Authorization: `Bearer ${token}` } });
	if (!res.ok) throw new Error(`HTTP ${res.status}`);
	return res.json();
}

/* The unread count for the Home tile's badge. Owner-only; anything that is not a
 * clean answer (a 401 for a stale session, a cold server) is simply no badge. */
export function useUnackedAlerts(authUser) {
	const [n, setN] = useState(0);
	const token = authUser?.is_admin ? authUser.session_token : null;
	const refresh = useCallback(() => {
		if (!token) return;
		call(token, "GET", "/admin/alerts").then((d) => setN(d.unacked || 0), () => {});
	}, [token]);
	useEffect(refresh, [refresh]);
	return [n, refresh];
}

const mb = (b) => (b == null ? "—" : `${(b / (1024 * 1024)).toFixed(b < 10 * 1024 * 1024 ? 1 : 0)} MB`);
const when = (t) => new Date(t * 1000).toLocaleString(undefined,
	{ month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });

export default function SiteHealth({ authUser, onClose, onChanged }) {
	const token = authUser?.session_token;
	const [data, setData] = useState(null);
	const [err, setErr] = useState("");
	const [note, setNote] = useState("");

	const load = useCallback(() => {
		call(token, "GET", "/admin/health").then((d) => { setData(d); setErr(""); },
			(e) => setErr(`Couldn't load site health (${e.message}).`));
	}, [token]);
	useEffect(load, [load]);

	const ack = () => call(token, "POST", "/admin/alerts/ack")
		.then(() => { load(); onChanged?.(); }, (e) => setNote(`Couldn't mark them read (${e.message}).`));
	const test = () => call(token, "POST", "/admin/alerts/test").then((d) => {
		setNote(d.channels?.length
			? `Test alert sent to ${d.channels.join(" and ")}.`
			: "Test alert recorded here. No push channel is set, so nothing went to your phone.");
		setTimeout(load, 800);
	}, (e) => setNote(`Couldn't send a test (${e.message}).`));

	const s = data?.snapshot;
	const storage = s?.storage_fraction;
	return (
		<>
			<style>{_css}</style>
			<RulesModal title="Site health" icon={HEALTH_GLYPH} closeLabel="Close" onClose={onClose}>
				{err && <p className="sh-err">{err}</p>}
				{!data && !err && <p>Loading…</p>}
				{data && (
					<>
						{!data.channels.length && (
							<RulesTip>
								No push channel is set, so alerts only appear here. Set <b>ALERT_NTFY_TOPIC</b>
								(or <b>ALERT_WEBHOOK_URL</b>) on Render to get them on your phone.
							</RulesTip>
						)}
						<RulesSection title="Right now">
							<RulesDefs items={[
								{ t: "Database", d: <>{mb(s.db_bytes)} of {mb(s.storage_budget_bytes)}
									{storage != null && <span className={storage >= 0.75 ? "sh-hot" : "sh-dim"}> · {Math.round(storage * 100)}%</span>}
									<span className="sh-dim"> · {s.db_backend}</span></> },
								{ t: "Memory", d: s.rss_mb == null ? "—" : <>{Math.round(s.rss_mb)} MB
									<span className="sh-dim"> · alerts at {s.memory_warn_mb} MB</span></> },
								{ t: "Accounts", d: s.users ?? "—" },
								{ t: "Open tables", d: s.open_lobbies },
								{ t: "Live rooms", d: s.rooms_in_memory ?? "—" },
								{ t: "Notes", d: <>{mb(s.notes_bytes)}<span className="sh-dim"> · {s.notes_users ?? 0} accounts</span></> },
							]} />
						</RulesSection>
						<RulesSection title={`Alerts${data.unacked ? ` · ${data.unacked} new` : ""}`}>
							<div className="sh-acts">
								<button type="button" className="btn btn-ghost btn-sm" onClick={ack} disabled={!data.unacked}>Mark all read</button>
								<button type="button" className="btn btn-ghost btn-sm" onClick={test}>Send a test alert</button>
							</div>
							{note && <p className="sh-note" role="status">{note}</p>}
							{data.alerts.length === 0
								? <p>Nothing has gone wrong yet.</p>
								: (
									<ol className="sh-list">
										{data.alerts.map((a) => (
											<li key={a.id} className={`sh-alert sh-${a.severity}${a.acked ? "" : " sh-new"}`}>
												<div className="sh-alert-hd">
													<span className="sh-kind">{a.kind}</span>
													<time>{when(a.created_at)}</time>
												</div>
												<div className="sh-msg">{a.message}{a.folded > 0 && <span className="sh-dim"> (+{a.folded} more)</span>}</div>
											</li>
										))}
									</ol>
								)}
						</RulesSection>
					</>
				)}
			</RulesModal>
		</>
	);
}
