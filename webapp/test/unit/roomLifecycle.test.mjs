import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installDom, mockFetch } from "./dom-stub.mjs";
import { leaveOpenSeat, readRoomToken } from "../../../shared/roomLifecycle.js";

const args = { endpoint: "https://api.example/pinch/games", roomId: "AB 12", playerId: "p1",
	tokenKey: "pinch_token_AB12", sessionToken: "sess" };
beforeEach(() => { installDom(); localStorage.setItem(args.tokenKey, "room-secret"); });

test("leaving sends both credentials, escapes the room id and clears the room token", async () => {
	const calls = mockFetch([{ body: { ok: true } }]);
	await leaveOpenSeat(args);
	assert.equal(calls[0].url, "https://api.example/pinch/games/AB%2012/leave?player_id=p1");
	assert.equal(calls[0].init.method, "POST");
	assert.equal(calls[0].init.headers.Authorization, "Bearer sess");
	assert.equal(calls[0].init.headers["X-Room-Token"], "room-secret");
	assert.equal(readRoomToken(args.tokenKey), "");
});

test("a refused leave keeps the room token and surfaces the server's message", async () => {
	mockFetch([{ status: 403, body: { ok: false, message: "Not your seat" } }]);
	await assert.rejects(leaveOpenSeat(args), /Not your seat/);
	assert.equal(readRoomToken(args.tokenKey), "room-secret");
});

test("a guest leave sends no Authorization header", async () => {
	const calls = mockFetch([{ body: { ok: true } }]);
	await leaveOpenSeat({ ...args, sessionToken: null });
	assert.equal("Authorization" in calls[0].init.headers, false);
});
