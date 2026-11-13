// shared/backend.js — the "is the server up yet?" module the boot no longer waits on.
// What matters: the probe asks /health and does not give up or cut a request short;
// a socket opened during the wake survives one refusal and only a second one reaches
// the game; and once the server answered, a socket is a plain WebSocket.
import test from "node:test";
import assert from "node:assert/strict";
import {
	startBackendProbe, isBackendAwake, whenBackendAwake, markBackendAwake,
	openSocket, _resetBackendForTest,
} from "../../../shared/backend.js";

const tick = () => new Promise((r) => setTimeout(r, 0));

test("the probe asks /health, retries a refusal and a 503, and marks the server awake", async () => {
	_resetBackendForTest();
	const calls = [];
	const answers = [new Error("refused"), { status: 503 }, { status: 200 }];
	globalThis.fetch = async (url, init) => {
		calls.push({ url: String(url), init });
		const a = answers.shift();
		if (a instanceof Error) throw a;
		return { ok: a.status < 300, status: a.status };
	};
	let woke = false;
	whenBackendAwake().then(() => { woke = true; });
	await startBackendProbe({ base: "https://api.test", retryMs: 1 });
	assert.equal(isBackendAwake(), true);
	await tick();
	assert.equal(woke, true);
	assert.deepEqual(calls.map((c) => c.url), Array(3).fill("https://api.test/health"));
	assert.equal(calls[0].init.cache, "no-store");
});

test("a held request is not aborted after a few seconds (the cold start needs it held)", async () => {
	_resetBackendForTest();
	let signal;
	let release;
	globalThis.fetch = (_url, init) => { signal = init.signal; return new Promise((r) => { release = r; }); };
	const done = startBackendProbe({ base: "https://api.test", attemptMs: 90_000 });
	await new Promise((r) => setTimeout(r, 300));
	assert.equal(signal.aborted, false, "the probe cut its own request short");
	release({ ok: true, status: 200 });
	await done;
	assert.equal(isBackendAwake(), true);
});

test("startBackendProbe is one probe however many callers", async () => {
	_resetBackendForTest();
	let n = 0;
	globalThis.fetch = async () => { n += 1; return { ok: true, status: 200 }; };
	await Promise.all([startBackendProbe({ base: "x" }), startBackendProbe({ base: "x" })]);
	assert.equal(n, 1);
});

// A minimal WebSocket the tests drive by hand.
class FakeWS {
	static all = [];
	constructor(url) { this.url = url; this.readyState = 0; this.sent = []; FakeWS.all.push(this); }
	send(d) { this.sent.push(d); }
	close() { this.readyState = 3; this.onclose?.({ code: 1000 }); }
	open() { this.readyState = 1; this.onopen?.({}); }
	fail() { this.readyState = 3; this.onerror?.({}); this.onclose?.({ code: 1006 }); }
}

test("once awake, openSocket is a plain WebSocket", () => {
	_resetBackendForTest();
	globalThis.WebSocket = FakeWS; FakeWS.all = [];
	markBackendAwake();
	const ws = openSocket("wss://api.test/ws/R/P");
	assert.ok(ws instanceof FakeWS);
});

test("a socket refused during the wake waits for the server and tries once more, unseen", async () => {
	_resetBackendForTest();
	globalThis.WebSocket = FakeWS; FakeWS.all = [];
	const ws = openSocket("wss://api.test/ws/R/P");
	const seen = [];
	ws.onopen = () => seen.push("open");
	ws.onclose = () => seen.push("close");
	ws.onerror = () => seen.push("error");
	FakeWS.all[0].fail();
	assert.deepEqual(seen, [], "the game heard about a failure the wake explains");
	assert.equal(ws.readyState, 0, "it should report CONNECTING while it waits");
	assert.throws(() => ws.send("x"));
	markBackendAwake();
	await tick();
	assert.equal(FakeWS.all.length, 2);
	FakeWS.all[1].open();
	assert.deepEqual(seen, ["open"]);
	assert.equal(ws.readyState, 1);
	ws.send("hello");
	assert.deepEqual(FakeWS.all[1].sent, ["hello"]);
});

test("the second failure reaches the game", async () => {
	_resetBackendForTest();
	globalThis.WebSocket = FakeWS; FakeWS.all = [];
	const ws = openSocket("wss://api.test/ws/R/P");
	const seen = [];
	ws.onclose = () => seen.push("close");
	FakeWS.all[0].fail();
	markBackendAwake();
	await tick();
	FakeWS.all[1].fail();
	assert.deepEqual(seen, ["close"]);
});

test("a socket the server holds through the wake just opens (no second attempt)", () => {
	_resetBackendForTest();
	globalThis.WebSocket = FakeWS; FakeWS.all = [];
	const ws = openSocket("wss://api.test/ws/R/P");
	let opened = false;
	ws.onopen = () => { opened = true; };
	FakeWS.all[0].open();
	assert.equal(opened, true);
	assert.equal(FakeWS.all.length, 1);
	assert.equal(isBackendAwake(), true, "an open socket proves the server is up");
});

test("closing a socket that is waiting out the wake cancels the retry and still fires onclose", async () => {
	_resetBackendForTest();
	globalThis.WebSocket = FakeWS; FakeWS.all = [];
	const ws = openSocket("wss://api.test/ws/R/P");
	let closed = 0;
	ws.onclose = () => { closed += 1; };
	FakeWS.all[0].fail();
	ws.close();
	await new Promise((r) => setTimeout(r, 5));
	assert.equal(closed, 1);
	assert.equal(ws.readyState, 3);
	markBackendAwake();
	await tick();
	assert.equal(FakeWS.all.length, 1, "a closed socket must not reconnect");
});
