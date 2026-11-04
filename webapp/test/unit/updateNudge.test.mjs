// When the "new version" banner shows (shared/update-nudge.js): on a new APP id, not
// on a new commit. The price, LoL and anime refresh jobs deploy a data file several
// times a day, which moves the commit and leaves the app as it was.
import test from "node:test";
import assert from "node:assert/strict";
import { isNewerApp } from "../../../shared/update-nudge.js";

const running = { build: "aaa", app: "app1" };

test("a data-only deploy is not a new version", () => {
	assert.equal(isNewerApp({ build: "bbb", app: "app1" }, running), false);
});

test("a deploy that changed the app is", () => {
	assert.equal(isNewerApp({ build: "bbb", app: "app2" }, running), true);
});

test("the same deploy never is", () => {
	assert.equal(isNewerApp({ build: "aaa", app: "app1" }, running), false);
});

test("without an app id on either side, the commit decides", () => {
	assert.equal(isNewerApp({ build: "bbb" }, running), true);
	assert.equal(isNewerApp({ build: "bbb", app: "app1" }, { build: "aaa", app: null }), true);
});

test("an unreadable version.json is never a new version", () => {
	assert.equal(isNewerApp(null, running), false);
	assert.equal(isNewerApp({}, running), false);
});
