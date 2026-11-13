// The browser crash reporter (shared/crashReport.js): what it sends, what it drops,
// and that one page load can never send more than its cap.
import test from "node:test";
import assert from "node:assert/strict";
import { createReporter, describe, shouldIgnore, trimStack, MAX_REPORTS, MESSAGE_MAX, STACK_MAX }
	from "../../../shared/crashReport.js";

function harness(opts = {}) {
	const sent = [];
	const r = createReporter({
		build: "abc1234", endpoint: "https://api.test/ops/client-error",
		send: (url, body) => sent.push({ url, body }), isOnline: () => true,
		route: () => "/coc/ABCDEF?token=nope#frag", force: () => false, ...opts,
	});
	return { r, sent };
}

test("a report carries the build, the path, the message, a trimmed stack and its source", () => {
	const { r, sent } = harness();
	const err = new TypeError("x is undefined");
	err.stack = "TypeError: x is undefined\n    at Board (https://x/a.js:1:2)\n    at App (https://x/a.js:3:4)";
	assert.equal(r.report(err, "boundary", "\n    in Board\n    in Suspense"), true);
	assert.equal(sent.length, 1);
	assert.equal(sent[0].url, "https://api.test/ops/client-error");
	assert.deepEqual(sent[0].body, {
		build: "abc1234", route: "/coc/ABCDEF", source: "boundary", message: "TypeError: x is undefined",
		stack: "    at Board (https://x/a.js:1:2)\n    at App (https://x/a.js:3:4)\n    in Board\n    in Suspense",
	});
});

test("never more than the cap per page load, and a repeat of one bug is not a new report", () => {
	const { r, sent } = harness();
	r.report(new Error("same"));
	r.report(new Error("same"));            // a boundary catch and a window error for one throw
	assert.equal(sent.length, 1);
	for (let i = 0; i < 20; i++) r.report(new Error(`loop ${i}`));
	assert.equal(sent.length, MAX_REPORTS);
	assert.equal(r.sent, MAX_REPORTS);
});

test("a local dev build stays quiet unless the harness forces it", () => {
	assert.equal(harness({ build: "dev" }).r.report(new Error("boom")), false);
	const forced = harness({ build: "dev", force: () => true });
	assert.equal(forced.r.report(new Error("boom")), true);
	assert.equal(forced.sent[0].body.build, "dev");
});

test("offline sends nothing and does not spend the cap", () => {
	let online = false;
	const { r, sent } = harness({ isOnline: () => online });
	for (let i = 0; i < 5; i++) assert.equal(r.report(new Error(`off ${i}`)), false);
	online = true;
	assert.equal(r.report(new Error("back online")), true);
	assert.equal(sent.length, 1);
});

test("the known non-bugs are dropped", () => {
	const { r, sent } = harness();
	for (const m of [
		"ResizeObserver loop completed with undelivered notifications.",
		"ResizeObserver loop limit exceeded",
		"TypeError: Failed to fetch dynamically imported module: https://x/assets/Orbit-abc.js",
		"TypeError: Importing a module script failed.",
		"TypeError: error loading dynamically imported module: https://x/a.js",
		"Error: Unable to preload CSS for /assets/a.css",
		"Script error.",
		"",
	]) assert.equal(r.report(m), false, m);
	const ext = new Error("from an extension");
	ext.stack = "Error: from an extension\n    at x (chrome-extension://abcdef/content.js:1:2)";
	assert.equal(r.report(ext), false);
	assert.equal(sent.length, 0);
	// A stack that merely passes THROUGH an extension is still ours.
	assert.equal(shouldIgnore("Error: ours",
		"    at x (chrome-extension://a/c.js:1:2)\n    at Board (https://x/a.js:1:2)"), false);
});

test("whatever is thrown becomes a message, and nothing makes the reporter throw", () => {
	assert.deepEqual(describe("plain string"), { message: "plain string", stack: "" });
	assert.equal(describe(undefined).message, "undefined");
	assert.equal(describe({ code: 7 }).message, 'Non-error thrown: {"code":7}');
	const loop = {}; loop.self = loop;
	assert.match(describe(loop).message, /^Non-error thrown: /);
	assert.equal(describe(new RangeError("bad")).message, "RangeError: bad");
	assert.equal(describe({ name: "AbortError", message: "aborted" }).message, "AbortError: aborted");
	const { r } = harness({ send: () => { throw new Error("network"); } });
	assert.equal(r.report(new Error("still fine")), false);     // a throwing send is swallowed
	const hostile = { get message() { throw new Error("getter"); } };
	assert.doesNotThrow(() => harness().r.report(hostile));
});

test("long messages and stacks are cut to their caps", () => {
	const { r, sent } = harness();
	const err = new Error("m".repeat(5000));
	err.stack = Array.from({ length: 500 }, (_, i) => `    at f${i} (${"p".repeat(40)}.js:1:1)`).join("\n");
	r.report(err);
	assert.equal(sent[0].body.message.length, MESSAGE_MAX);
	assert.ok(sent[0].body.stack.length <= STACK_MAX);
	assert.ok(trimStack(err.stack).split("\n").length <= 12);
});
