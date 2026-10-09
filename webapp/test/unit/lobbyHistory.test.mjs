import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installDom, mockFetch } from "./dom-stub.mjs";
import { fetchGameHistory, latestSession, SESSION_EXPIRED } from "../../../shared/lobbyHistory.js";

const URL_ = "https://api.example/duel/games/history";
const user = { id: "u1", session_token: "old" };
let win;
beforeEach(() => { win = installDom(); });

test("latestSession prefers the same account's newer token from another tab", () => {
	localStorage.setItem("spender_user", JSON.stringify({ id: "u1", session_token: "new" }));
	assert.equal(latestSession(user).session_token, "new");
});

test("latestSession refuses another account's token", () => {
	localStorage.setItem("spender_user", JSON.stringify({ id: "someone-else", session_token: "x" }));
	assert.throws(() => latestSession(user), /Account changed/);
});

test("a non-empty history is returned with the bearer token", async () => {
	const calls = mockFetch([{ body: { games: [{ id: "G1" }] } }]);
	const data = await fetchGameHistory(URL_, user);
	assert.deepEqual(data.games, [{ id: "G1" }]);
	assert.equal(calls.length, 1);
	assert.equal(calls[0].init.headers.Authorization, "Bearer old");
});

test("an empty legacy reply is only accepted after the session is confirmed", async () => {
	const calls = mockFetch([{ body: { games: [] } }, { body: { ok: true } }]);
	const data = await fetchGameHistory(URL_, user);
	assert.deepEqual(data.games, []);
	assert.equal(calls[1].url, "https://api.example/auth/session");
});

test("an empty reply from a dead session is rejected and announces the expiry", async () => {
	mockFetch([{ body: { games: [] } }, { body: { ok: false } }]);
	const expired = [];
	win.addEventListener(SESSION_EXPIRED, (e) => expired.push(e.detail));
	await assert.rejects(fetchGameHistory(URL_, user), /History unavailable/);
	assert.equal(expired.length, 1);
	assert.equal(expired[0].session_token, "old");
});

test("an empty reply is rejected without an expiry when the session check is inconclusive", async () => {
	mockFetch([{ body: { games: [] } }, { status: 503, body: {} }]);
	const expired = [];
	win.addEventListener(SESSION_EXPIRED, () => expired.push(1));
	await assert.rejects(fetchGameHistory(URL_, user), /Session check unavailable/);
	assert.equal(expired.length, 0);
});

test("a malformed reply and an HTTP error are both rejected", async () => {
	mockFetch([{ body: { games: "nope" } }]);
	await assert.rejects(fetchGameHistory(URL_, user), /Invalid history response/);
	mockFetch([{ status: 500, body: {} }]);
	await assert.rejects(fetchGameHistory(URL_, user), /History unavailable/);
});

test("a newer request for the same list supersedes an older one", async () => {
	let release;
	const gate = new Promise((r) => { release = r; });
	let n = 0;
	globalThis.fetch = async () => {
		n++;
		if (n === 1) await gate;
		return { ok: true, status: 200, json: async () => ({ games: [{ id: `G${n}` }] }) };
	};
	const first = fetchGameHistory(URL_, user);
	const second = fetchGameHistory(URL_, user);
	release();
	await assert.rejects(first, /superseded/);
	assert.deepEqual((await second).games, [{ id: "G2" }]);
});
