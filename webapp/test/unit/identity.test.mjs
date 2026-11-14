import { test, beforeEach } from "node:test";
import assert from "node:assert/strict";
import { installDom } from "./dom-stub.mjs";
import { loadIdentity, readIdentity, writeIdentity, guestAfterLogin, isMember,
	isGuestName } from "../../../shared/identity.js";
import { latestSession } from "../../../shared/lobbyHistory.js";

const stored = () => JSON.parse(localStorage.getItem("spender_user"));
const account = { id: "u1", name: "Ada", is_admin: false, session_token: "tok" };
beforeEach(() => { installDom(); });

test("a first visit makes a guest and stores it, so a reload is the same guest", () => {
	const first = loadIdentity();
	assert.equal(first.guest, true);
	assert.match(first.name, /^Guest\d{4}$/);
	assert.ok(first.id);
	assert.deepEqual(stored(), first);
	assert.deepEqual(loadIdentity(), first);
	assert.equal(isMember(first), false);
});

test("a stored account is the identity, untouched", () => {
	writeIdentity(account);
	assert.deepEqual(loadIdentity(), account);
	assert.equal(isMember(account), true);
});

test("a guest from before guests were stored keeps the id their seats are under", () => {
	localStorage.setItem("spender_myId", "oldguest1");
	const guest = loadIdentity();
	assert.equal(guest.id, "oldguest1");
	assert.equal(guest.guest, true);
	assert.equal(localStorage.getItem("spender_myId"), null);
});

test("an unreadable stored identity is replaced by a guest rather than thrown on", () => {
	localStorage.setItem("spender_user", "{not json");
	assert.equal(loadIdentity().guest, true);
	assert.equal(stored().guest, true);
});

test("when a login ends the device becomes a NEW guest, never the account's id", () => {
	writeIdentity(account);
	const guest = guestAfterLogin();
	assert.equal(guest.guest, true);
	assert.notEqual(guest.id, account.id);
	assert.deepEqual(stored(), guest);
});

test("...and a tab that finds another tab already signed out takes that tab's guest", () => {
	const other = writeIdentity({ id: "g-other", name: "Guest1234", guest: true });
	assert.deepEqual(guestAfterLogin(), other);
});

test("a guest never keeps a name of their own: a stored one goes back to Guest####, same id", () => {
	writeIdentity({ id: "g-named", name: "Wanderer", guest: true });
	const guest = loadIdentity();
	assert.equal(guest.id, "g-named");
	assert.ok(isGuestName(guest.name), guest.name);
	assert.deepEqual(stored(), guest);
});

test("...while an account keeps the name it signed up with", () => {
	writeIdentity(account);
	assert.deepEqual(loadIdentity(), account);
});

test("a stored guest is not a login: the token in hand is still the one to use", () => {
	writeIdentity({ id: "g1", name: "Guest1234", guest: true });
	assert.equal(latestSession(account), account);
});
