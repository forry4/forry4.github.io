/* Halcyon Rift's wire client (halcyon/client.js): who it says it is, and the run
 * queue — saved before it is sent, numbered once, dropped only when the server has
 * it, and never left blocking the next run. */
import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installDom } from "./dom-stub.mjs";
import { makeClient } from "../../../halcyon/client.js";

const GUEST = { id: "g1", name: "Guest1234", guest: true };
const ACCOUNT = { id: "u1", name: "Ada", session_token: "tok" };

/* A fake server: records every request and answers from `routes`. */
function fakeServer(routes) {
	const calls = [];
	const fetchImpl = async (url, init = {}) => {
		const path = url.replace("http://x", "");
		const body = init.body ? JSON.parse(init.body) : undefined;
		calls.push({ path, method: init.method, headers: init.headers || {}, body });
		const [status, json] = await (routes[path] || (() => [404, { detail: "nope" }]))(body);
		return { ok: status >= 200 && status < 300, status, json: async () => json };
	};
	return { calls, fetchImpl };
}

beforeEach(() => installDom());

test("a guest roster is minted once, kept on the device, and sent as two headers", async () => {
	let minted = 0;
	const srv = fakeServer({
		"/halcyon/guest": () => { minted++; return [200, { owner: "hg_1", secret: "s3" }]; },
		"/halcyon/state": () => [200, { characters: [] }],
	});
	const c = makeClient(GUEST, { base: "http://x", fetchImpl: srv.fetchImpl });
	await c.state();
	await makeClient(GUEST, { base: "http://x", fetchImpl: srv.fetchImpl }).state();   // a new page load
	assert.equal(minted, 1);
	const st = srv.calls.filter((x) => x.path === "/halcyon/state");
	assert.deepEqual(st.map((x) => [x.headers["X-Halcyon-Owner"], x.headers["X-Halcyon-Secret"]]), [["hg_1", "s3"], ["hg_1", "s3"]]);
	assert.equal(st[0].headers.Authorization, undefined);
});

test("an account sends its session and never mints a guest", async () => {
	const srv = fakeServer({ "/halcyon/state": () => [200, {}] });
	await makeClient(ACCOUNT, { base: "http://x", fetchImpl: srv.fetchImpl }).state();
	assert.deepEqual(srv.calls.map((x) => x.path), ["/halcyon/state"]);
	assert.equal(srv.calls[0].headers.Authorization, "Bearer tok");
});

test("reports are numbered from 1, saved before sending, and dropped once acknowledged", async () => {
	let up = false;
	const srv = fakeServer({
		"/halcyon/runs/r1/events": (b) => (up ? [200, { status: "open", last_seq: b.events.at(-1).seq, refused: [] }] : [503, {}]),
	});
	const c = makeClient(ACCOUNT, { base: "http://x", fetchImpl: srv.fetchImpl });
	c.beginRun("r1");
	c.report({ type: "kill", enemy: "e1" });
	c.report({ type: "pickup", drop: "d1", slot: 0 });
	assert.equal(c.pendingRun(), "r1");
	assert.equal(await c.flush(), null, "a server that is down keeps the queue");
	assert.equal(c.pendingRun(), "r1");
	// A new page load (the tab was closed) still has them.
	const c2 = makeClient(ACCOUNT, { base: "http://x", fetchImpl: srv.fetchImpl });
	up = true;
	const out = await c2.flush();
	assert.equal(out.last_seq, 2);
	assert.deepEqual(srv.calls.at(-1).body.events.map((e) => [e.seq, e.type]), [[1, "kill"], [2, "pickup"]]);
	assert.equal(c2.pendingRun(), null);
	c2.report({ type: "kill", enemy: "e2" });
	await c2.flush();
	assert.deepEqual(srv.calls.at(-1).body.events.map((e) => e.seq), [3], "numbering continues, nothing resent");
});

test("a closed run's queue is cleared, and so is one the server does not know", async () => {
	const srv = fakeServer({
		"/halcyon/runs/r1/events": () => [200, { status: "recalled", last_seq: 1, refused: [] }],
		"/halcyon/runs/r2/events": () => [409, { detail: "no such run" }],
	});
	const c = makeClient(ACCOUNT, { base: "http://x", fetchImpl: srv.fetchImpl });
	c.beginRun("r1");
	c.report({ type: "recall" });
	await c.flush();
	assert.equal(localStorage.getItem("halcyon.queue.v1.u.u1"), null);
	c.beginRun("r2");
	c.report({ type: "kill", enemy: "e1" });
	await c.flush();
	assert.equal(c.pendingRun(), null);
	assert.equal(localStorage.getItem("halcyon.queue.v1.u.u1"), null);
});

test("a run that reported nothing does not block the next one", () => {
	const c = makeClient(ACCOUNT, { base: "http://x", fetchImpl: async () => { throw new Error("offline"); } });
	c.beginRun("r1");                          // entered, then the tab closed before anything happened
	assert.equal(c.pendingRun(), null);
});

test("an account's queue and a guest's are separate", () => {
	const a = makeClient(ACCOUNT, { base: "http://x" });
	a.beginRun("r1");
	a.report({ type: "kill", enemy: "e1" });
	assert.equal(makeClient(GUEST, { base: "http://x" }).pendingRun(), null);
	assert.equal(a.pendingRun(), "r1");
});
