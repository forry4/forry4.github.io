/* While a real-time game is on screen, right-click never opens the browser's own
 * menu (Save page as…, Inspect, Back) — a right-click there is a misclick in the
 * middle of a fight, not a request for that menu (owner's ask, 2026-11-21).
 * Text fields keep it, so paste still works; a game's own right-click handlers
 * (Halcyon's item lock) still run, since only the browser default is cancelled. */
import { useEffect } from "react";

export function useNoContextMenu() {
	useEffect(() => {
		const block = (e) => {
			if (e.target?.closest?.("input, textarea, [contenteditable='true']")) return;
			e.preventDefault();
		};
		document.addEventListener("contextmenu", block);
		return () => document.removeEventListener("contextmenu", block);
	}, []);
}
