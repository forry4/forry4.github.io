/* "A new version is available — Refresh."
 *
 * GitHub Pages caches the bundle (~10 min TTL), so for a while after a deploy some
 * browsers are still running the OLD frontend against the NEW backend. Usually
 * harmless — but when a backend change DEPENDS on a frontend change it is not, and
 * a stale client fails in a way that looks like a bug rather than a stale tab. The
 * seat-binding release did exactly that: an old bundle omitted `session_token` on
 * join, so re-entering your own seat answered "seat already taken".
 *
 * Expand/contract (ship the backend accepting BOTH shapes first) is the real fix and
 * should be the default — see CLAUDE.md. This is the safety net for the cases where
 * you deliberately break old clients, e.g. closing a security hole, where a
 * compatibility window is the vulnerability.
 *
 * HOW: the build emits `version.json` next to the bundle containing the same id that
 * is compiled into this file as `__BUILD_ID__` (see webapp/vite.config.js). If the
 * served file ever reports a different id, a newer frontend has been deployed and
 * this tab is stale.
 *
 * Deliberately NOT compared against the backend's commit: the backend only
 * redeploys when backend paths change, so a frontend-only release would leave the
 * two SHAs legitimately different and the banner would cry wolf on every push.
 *
 * Checks happen on tab-focus and on a slow interval — never during load, so this
 * cannot move first paint or cost the smoke test's CLS budget. Plain DOM, appended
 * to <body>: it must appear on every screen, and the shell early-returns each game's
 * component, so there is no one React tree to live in.
 */

const BUILD_ID = typeof __BUILD_ID__ === "string" ? __BUILD_ID__ : "dev";
const BANNER_ID = "fg-update-nudge";

let shown = false;
let stopped = false;

async function fetchDeployedBuildId(base) {
	// `cache: no-store` matters: the whole point is to bypass the CDN copy that is
	// keeping this tab stale in the first place.
	const res = await fetch(`${base}version.json`, { cache: "no-store" });
	if (!res.ok) throw new Error(`version.json ${res.status}`);
	const data = await res.json();
	return data && typeof data.build === "string" ? data.build : null;
}

function showBanner() {
	if (shown || document.getElementById(BANNER_ID)) return;
	shown = true;

	const bar = document.createElement("div");
	bar.id = BANNER_ID;
	bar.setAttribute("role", "status");
	// Inline styles on purpose: each game injects its own <style> only while mounted,
	// so there is no stylesheet this can rely on being present.
	// CENTRED BY AUTO MARGINS BETWEEN BOTH EDGES, NOT `left:50%` + translateX(-50%):
	// a fixed box at left:50% can only size itself to the space RIGHT of that line,
	// i.e. half the viewport, so on a 390px phone the message wrapped into a ~190px
	// column ("kinda squished on mobile"). Pinned 12px from each edge with
	// `width:fit-content` it takes the width it needs and centres in the rest.
	Object.assign(bar.style, {
		position: "fixed", left: "12px", right: "12px", margin: "0 auto", width: "fit-content",
		bottom: "calc(18px + env(safe-area-inset-bottom, 0px))",
		zIndex: "2147483647", display: "flex", alignItems: "center", gap: "12px",
		padding: "10px 14px", borderRadius: "10px", boxSizing: "border-box",
		background: "#2a1c20", border: "1px solid #e8c96a", color: "#f3e9d2",
		font: "14px/1.3 Georgia, serif", boxShadow: "0 6px 24px rgba(0,0,0,.45)",
	});

	const msg = document.createElement("span");
	msg.textContent = "A new version is available.";
	Object.assign(msg.style, { flex: "1 1 auto", minWidth: "0" });

	const refresh = document.createElement("button");
	refresh.type = "button";
	refresh.textContent = "Refresh";
	Object.assign(refresh.style, {
		cursor: "pointer", padding: "5px 12px", borderRadius: "7px",
		border: "1px solid #e8c96a", background: "#e8c96a", color: "#2a1c20",
		font: "600 14px/1 Georgia, serif", flexShrink: "0", whiteSpace: "nowrap",
	});
	refresh.addEventListener("click", () => window.location.reload());

	const dismiss = document.createElement("button");
	dismiss.type = "button";
	dismiss.textContent = "✕";
	dismiss.setAttribute("aria-label", "Dismiss");
	Object.assign(dismiss.style, {
		cursor: "pointer", padding: "5px 8px", borderRadius: "7px",
		border: "1px solid transparent", background: "transparent", color: "#f3e9d2",
		font: "14px/1 Georgia, serif", flexShrink: "0",
	});
	// Dismiss stops the checks too — never nag someone mid-game who has decided to
	// finish first. The next full load picks up the new build anyway.
	dismiss.addEventListener("click", () => { bar.remove(); stopped = true; });

	bar.append(msg, refresh, dismiss);
	document.body.appendChild(bar);
}

async function check(base) {
	if (stopped || shown) return;
	try {
		const deployed = await fetchDeployedBuildId(base);
		if (deployed && deployed !== BUILD_ID) showBanner();
	} catch {
		// Offline, or version.json not deployed yet. Never surface this: a failed
		// check must be indistinguishable from "you are up to date".
	}
}

/**
 * Start watching for a newer deployed frontend.
 * @param {object} [opts]
 * @param {number} [opts.intervalMs] how often to check while the tab is visible
 * @returns {() => void} stop function (used by tests; the app never needs it)
 */
export function startUpdateNudge({ intervalMs = 10 * 60 * 1000 } = {}) {
	// `dev` means an unstamped local build — comparing would be noise.
	if (BUILD_ID === "dev") return () => {};
	const base = (import.meta.env && import.meta.env.BASE_URL) || "/";

	const onVisible = () => { if (document.visibilityState === "visible") check(base); };
	document.addEventListener("visibilitychange", onVisible);
	const timer = setInterval(() => {
		if (document.visibilityState === "visible") check(base);
	}, intervalMs);

	return () => {
		document.removeEventListener("visibilitychange", onVisible);
		clearInterval(timer);
		stopped = true;
	};
}
