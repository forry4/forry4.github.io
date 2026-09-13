/* The site's sign-in / register / guest screen.
 *
 * FIRST PIECE OF THE SHELL/GAME SPLIT. games/spender/Spender.jsx is both the site
 * shell (auth, home menu, routing to every game, Books, Puzzles) and Spender's own
 * game UI, in ONE component with 58 useState hooks. Auth is the cleanest seam in it:
 * six of those hooks (tab, name, password, guest name, error, loading) are touched by
 * nothing else in the file, and the screen's only outward effect is "a user was
 * authenticated". So it lifts out whole, with a one-callback interface.
 *
 * It lives in shared/ so the dependency runs ONE WAY, games -> shared, exactly like
 * every other game. It sat briefly in webapp/shell/ — which is where it belongs in the
 * finished architecture (main.jsx -> Shell.jsx -> games/*) — but until the shell is
 * actually lifted out of Spender.jsx that made games/spender import from webapp/ while
 * webapp/main.jsx imports games/spender: a directory-level cycle, and Spender the only
 * game reaching outside shared/. A mild naming compromise (shared/ otherwise means
 * cross-game kits) beats a cycle waiting on a refactor that may never happen.
 *
 * Owns only its own form state. It does NOT know about localStorage, routing, or the
 * session — the shell still owns identity, and `onAuthenticated(user)` hands it back.
 *
 * It is also the site's FRONT DOOR, and it shares the home menu's ground, wordmark and
 * ornament rather than approximating them: the `.auth-screen`/`.home` selector pairs in
 * Spender.css are deliberate, so the two screens cannot drift into two looks.
 */
import { useState } from "react";

const TABS = [
	{ id: "login", label: "Sign In" },
	{ id: "register", label: "Register" },
	{ id: "guest", label: "Guest" },
];

// Same 24-grid / 1.5-stroke family as the home menu's emblems.
const ICON = {
	user: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><circle cx="12" cy="8.4" r="3.7" /><path d="M4.8 19.6a7.2 7.2 0 0 1 14.4 0" /></svg>),
	lock: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><rect x="5" y="10.4" width="14" height="9.2" rx="2.2" /><path d="M8.4 10.4V7.8a3.6 3.6 0 0 1 7.2 0v2.6" /></svg>),
	alert: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"><circle cx="12" cy="12" r="8" /><path d="M12 8v4.6M12 15.6v.1" /></svg>),
	yes: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round"><path d="M5 12.6 9.8 17.4 19 6.6" /></svg>),
	no: (<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinejoin="round" strokeLinecap="round"><path d="M6.4 6.4 17.6 17.6M17.6 6.4 6.4 17.6" /></svg>),
};

// WHAT GUEST MODE COSTS YOU, as three scannable rows rather than a sentence: one
// thing it buys you and the two it takes away, so the trade is read rather than
// inferred. (An older note here claimed the list also existed to hold the Guest panel
// to the other two panels' height. That height lock is gone -- the card is
// top-anchored now, see the `.auth-panel` comment in Spender.css -- so these rows
// carry their own weight and are free to say less.)
const GUEST_FACTS = [
	["yes", "Play immediately"],
	["no", "Game history is not saved"],
	["no", "Cannot resume on another device"],
];

export default function AuthScreen({ siteName, httpBase, css, myId, onAuthenticated, heroRule }) {
	const [tab, setTab] = useState("login");
	const [name, setName] = useState("");
	const [password, setPassword] = useState("");
	const [guestName, setGuestName] = useState("");
	const [error, setError] = useState("");
	const [loading, setLoading] = useState(false);

	const submit = async () => {
		if (!name.trim() || !password.trim()) {
			setError("Name and password required");
			return;
		}
		setError("");
		setLoading(true);
		try {
			const endpoint = tab === "login" ? "/auth/login" : "/auth/register";
			const res = await fetch(`${httpBase}${endpoint}`, {
				method: "POST",
				headers: { "Content-Type": "application/json" },
				body: JSON.stringify({ name: name.trim(), password: password.trim() }),
			});
			const data = await res.json();
			if (data.ok) {
				onAuthenticated({
					id: data.user.id,
					name: data.user.name,
					is_admin: !!data.user.is_admin,
					session_token: data.session_token || null,
				});
			} else {
				// The backend returns HTTP 200 with ok:false for a rate-limited attempt
				// too, so this one branch covers bad credentials AND the throttle message.
				setError(data.message || "Something went wrong");
			}
		} catch {
			setError("Could not reach server");
		}
		setLoading(false);
	};

	const playAsGuest = () => {
		// A guest keeps the shell's existing anonymous id, so a game started before
		// signing in stays theirs.
		onAuthenticated({
			id: myId,
			name: guestName.trim() || `Guest${Math.floor(Math.random() * 9000 + 1000)}`,
			guest: true,
		});
	};

	// A real <label> per field, not a placeholder doing double duty. A placeholder
	// vanishes the moment you type, so on a two-field form the user loses the only
	// thing telling them which box they are in — and a screen reader gets nothing at
	// all on browsers that do not expose it.
	const field = (id, label, icon, props) => (
		<div className="auth-field-wrap">
			<label className="auth-label" htmlFor={id}>{label}</label>
			<div className="auth-input-row">
				<span className="auth-input-icon" aria-hidden="true">{ICON[icon]}</span>
				<input id={id} className="auth-field" {...props} />
			</div>
		</div>
	);

	return (
		<>
			<style>{css}</style>
			<div className="app auth-screen">
				{/* hero + card centre together, top-anchored, exactly as on the home
				    menu — the wordmark must not move as the boot steps through the
				    three screens. */}
				<div className="auth-main">
				<div className="auth-hero">
					<h1 className="auth-logo">{siteName}</h1>
					{heroRule}
					<p className="auth-tagline">A collection of tabletop games</p>
				</div>

				<div className="auth-card">
					{/* role=tablist is not used: these switch the FORM, and the panel is
					    re-rendered rather than shown/hidden, so the simple button group
					    is the honest markup. `.auth-tab` and a count of 3 are what
					    webapp/test/screens.mjs keys on. */}
					<div className="auth-tabs">
						{TABS.map(t => (
							<button key={t.id} type="button"
								className={`auth-tab${tab === t.id ? " active" : ""}`}
								aria-pressed={tab === t.id}
								onClick={() => { setTab(t.id); setError(""); }}>
								{t.label}
							</button>
						))}
					</div>

					<div className="auth-panel">
						{tab !== "guest" ? (
							<>
								{/* maxLength mirrors core.auth.validate_credentials: register is
								    capped at 16, login accepts longer legacy values. */}
								{field("auth-name", "Name", "user", {
									value: name, placeholder: "Your name", autoComplete: "username", autoCapitalize: "off",
									autoCorrect: "off", spellCheck: false, maxLength: tab === "register" ? 16 : 64,
									onChange: e => setName(e.target.value),
									onKeyDown: e => e.key === "Enter" && submit(),
								})}
								{field("auth-pass", "Password", "lock", {
									type: "password", value: password, placeholder: "Your password",
									autoComplete: tab === "register" ? "new-password" : "current-password",
									maxLength: tab === "register" ? 16 : 128,
									onChange: e => setPassword(e.target.value),
									onKeyDown: e => e.key === "Enter" && submit(),
								})}
								{/* aria-live so the failure is announced, not just drawn. */}
								<div className="auth-error-slot" role="alert" aria-live="polite">
									{error && <div className="auth-error">
										<span className="auth-error-icon" aria-hidden="true">{ICON.alert}</span>{error}
									</div>}
								</div>
								{/* Register says ONE thing. The field rules it used to spell out
								    (1-16 characters, letters and numbers) are enforced by the
								    maxLength above and by core.auth.validate_credentials, and a
								    rejected value comes back through the error slot naming what was
								    wrong -- so the second line was reciting a rule at everyone to
								    pre-empt it for the few who would hit it. The one line left is the
								    only thing a new account holder cannot find out by trying. */}
								<p className="auth-note">
									{tab === "login"
										? "Signed-in games are saved and can be resumed from any device."
										: "No email verification required."}
									{tab === "login" && (
										<span className="auth-note-sub">Names are not case-sensitive.</span>
									)}
								</p>
								{/* THE BUSY SPINNER IS ABSOLUTELY POSITIONED, AND IT IS A CLASS THAT
								    EXISTS. It used to be `<span className="spinner" />`, and nothing has
								    defined `.spinner` since the site's three hand-rolled spinners were
								    consolidated into `.lby-spinner` — so the front door's one piece of
								    "working on it" feedback drew NOTHING. What it did do was occupy a
								    flex slot in a `.btn` with `gap: 8px`, which slid the centred label
								    4px right for the length of the request and then slid it back: a
								    label that jumps, at low opacity, mid-repaint, on a phone, with no
								    spinner to explain it. Out of flow it contributes no gap, so the
								    label does not move at all and the spinner is the only thing that
								    changes. */}
								<button className="btn btn-gold btn-full" onClick={submit} disabled={loading}>
									{loading && <span className="btn-spin lby-spinner lby-spinner-sm" aria-hidden="true" />}
									{tab === "login" ? "Sign In" : "Create Account"}
								</button>
							</>
						) : (
							<>
								{field("auth-guest", "Display name", "user", {
									value: guestName, placeholder: "Optional",
									autoComplete: "off", maxLength: 20,
									onChange: e => setGuestName(e.target.value),
									onKeyDown: e => e.key === "Enter" && playAsGuest(),
								})}
								<ul className="auth-facts">
									{GUEST_FACTS.map(([kind, text]) => (
										<li key={text} className={`auth-fact ${kind}`}>
											<span className="auth-fact-icon" aria-hidden="true">{ICON[kind]}</span>
											{text}
										</li>
									))}
								</ul>
								<button className="btn btn-gold btn-full" onClick={playAsGuest}>
									Play as Guest
								</button>
							</>
						)}
					</div>
					</div>
				</div>
			</div>
		</>
	);
}
