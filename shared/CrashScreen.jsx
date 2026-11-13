/* The screen a player sees when a page throws, and the boundaries that draw it.
 *
 * Two boundaries, one screen:
 *   * `ScreenBoundary` wraps each lazily loaded screen in the shell (Spender.jsx), so a
 *     crash inside one game is THAT game's problem: the shell stays mounted, and
 *     "Back to menu" is the shell's own `nav("home")`, no reload needed.
 *   * `AppBoundary` is the last resort at the root (webapp/main.jsx), for a throw in
 *     the shell itself. There is no shell left to navigate, so its "Back to menu" is a
 *     full load of the home path (`buildPath("home")`, which owns VITE_BASE).
 * Both report through `shared/crashReport.js`, and both offer Reload — a game in
 * progress is server-side state (or IndexedDB, offline), so a reload resumes it.
 *
 * It brings its OWN sheet (baseCss + CrashScreen.css): the per-game sheets are injected
 * by each game's own <style> while it is mounted, and the game is exactly what is no
 * longer mounted. The technical detail sits behind a disclosure — it is for a bug
 * report, not for the player.
 */
import { Component } from "react";
import { baseCss } from "./theme.js";
import _css from "./CrashScreen.css?inline";
import { buildPath } from "./router.js";
import { reportBoundaryError } from "./crashReport.js";

const css = baseCss + _css;

export function CrashScreen({ error, componentStack, reported, onHome }) {
	const detail = [String(error && error.stack ? error.stack : error),
		componentStack ? String(componentStack).replace(/^\s*\n/, "") : ""].filter(Boolean).join("\n");
	return (
		<div className="crash" role="alert">
			<style>{css}</style>
			<div className="crash-card">
				<svg className="crash-glyph" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5"
					strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
					<path d="M12 3.5 21 19.5H3z" /><path d="M12 9.5v4.5" /><path d="M12 16.9v.1" />
				</svg>
				<h1 className="crash-title">Something went wrong</h1>
				<p className="crash-lede">
					This page hit an error. Reloading usually fixes it, and a game in progress is kept.
				</p>
				{reported && <p className="crash-note">The site&rsquo;s owner has been sent a report.</p>}
				<div className="crash-acts">
					<button type="button" className="btn btn-gold crash-reload" onClick={() => window.location.reload()}>
						Reload
					</button>
					<button type="button" className="btn btn-ghost crash-home" onClick={onHome}>
						Back to menu
					</button>
				</div>
				<details className="crash-detail">
					<summary>Technical details</summary>
					<pre>{detail}</pre>
				</details>
			</div>
		</div>
	);
}

class Boundary extends Component {
	constructor(props) {
		super(props);
		this.state = { error: null, componentStack: "", reported: false };
	}
	static getDerivedStateFromError(error) { return { error }; }
	componentDidCatch(error, info) {
		// The component stack stays in the console too: the screen folds it away.
		try { console.error(`[${this.props.label}] render failed`, error, info && info.componentStack); } catch { /* */ }
		const reported = reportBoundaryError(error, info);
		this.setState({ componentStack: (info && info.componentStack) || "", reported });
	}
	render() {
		const { error, componentStack, reported } = this.state;
		if (!error) return this.props.children;
		return <CrashScreen error={error} componentStack={componentStack} reported={reported} onHome={this.props.onHome} />;
	}
}

// One per lazily loaded screen. Give it `key={screen}` at the call site: the shell's
// branches all return a boundary at the same position, so without a key React would
// reuse one instance — and its error — across screens.
export function ScreenBoundary({ onHome, children }) {
	return <Boundary label="screen" onHome={onHome}>{children}</Boundary>;
}

export function AppBoundary({ children }) {
	return <Boundary label="app" onHome={() => window.location.assign(buildPath("home"))}>{children}</Boundary>;
}
