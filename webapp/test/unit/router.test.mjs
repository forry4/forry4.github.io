import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installDom } from "./dom-stub.mjs";
import { parsePath, buildPath, pushPath, replacePath, subscribe, navigateTo, cameFromInsideApp, MODES }
	from "../../../shared/router.js";

let win;
beforeEach(() => { win = installDom("/"); });

test("parsePath reads home, a mode and a room", () => {
	assert.deepEqual(parsePath("/"), { game: "home", room: null });
	assert.deepEqual(parsePath("/duel"), { game: "duel", room: null });
	assert.deepEqual(parsePath("/duel/abc123"), { game: "duel", room: "ABC123" });
});

test("parsePath rejects an unknown mode and a malformed room", () => {
	assert.deepEqual(parsePath("/nope/ABC"), { game: null, room: null });
	assert.deepEqual(parsePath("/duel/has space"), { game: "duel", room: null });
	assert.deepEqual(parsePath("/duel/" + "X".repeat(25)), { game: "duel", room: null });
});

test("parsePath and buildPath round-trip every mode", () => {
	for (const mode of MODES) {
		assert.deepEqual(parsePath(buildPath(mode, "ROOM1")), { game: mode, room: "ROOM1" });
		assert.deepEqual(parsePath(buildPath(mode)), { game: mode, room: null });
	}
	assert.equal(buildPath("home"), "/");
	assert.equal(buildPath(null), "/");
});

test("pushPath and replacePath are no-ops when the path is already current", () => {
	pushPath("/");
	replacePath("/");
	assert.equal(win.history.pushes, 0);
	assert.equal(win.history.replaces, 0);
	pushPath("/coc");
	assert.equal(win.history.pushes, 1);
	pushPath("/coc");
	assert.equal(win.history.pushes, 1, "a second push to the same path adds no history entry");
});

test("subscribe fires on popstate only, never on a programmatic push", () => {
	const seen = [];
	const off = subscribe((r) => seen.push(r));
	pushPath("/orbit/AB12");
	assert.equal(seen.length, 0);
	win.dispatchEvent(new PopStateEvent("popstate"));
	assert.deepEqual(seen, [{ game: "orbit", room: "AB12" }]);
	off();
	win.dispatchEvent(new PopStateEvent("popstate"));
	assert.equal(seen.length, 1, "unsubscribe removes the listener");
});

test("navigateTo pushes, notifies subscribers and marks the entry as in-app", () => {
	const seen = [];
	subscribe((r) => seen.push(r));
	navigateTo("profile");
	assert.equal(win.location.pathname, "/profile");
	assert.deepEqual(seen, [{ game: "profile", room: null }]);
	assert.equal(cameFromInsideApp(), true);
	navigateTo("profile");
	assert.equal(seen.length, 1, "navigating to the current path does nothing");
});
