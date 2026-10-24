// The Steam Filter's saved-games sync logic (steamfilter/saved.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { toggle, adopt, settle, batch } from "../../../steamfilter/saved.js";

const EMPTY = { saved: {}, pending: {} };

test("a guest's star is local only", () => {
	const s = toggle(EMPTY, 105600, 10, false);
	assert.deepEqual(s, { saved: { 105600: 10 }, pending: {} });
	assert.deepEqual(toggle(s, 105600, 20, false), EMPTY);
});

test("a member's star is queued until the server has it", () => {
	let s = toggle(EMPTY, 105600, 10, true);
	assert.deepEqual(s.pending, { 105600: true });
	const sent = { ...s.pending };
	assert.deepEqual(batch(sent), { save: [105600], unsave: [] });
	s = settle(s, sent, [[105600, 11], [440, 5]]);
	assert.deepEqual(s, { saved: { 105600: 11, 440: 5 }, pending: {} });
});

test("a change made while a request was out stays queued and shown", () => {
	let s = toggle(EMPTY, 1, 10, true);
	const sent = { ...s.pending };            // request goes out: save 1
	s = toggle(s, 1, 11, true);               // ...the reader unsaves 1 meanwhile
	s = toggle(s, 2, 12, true);               // ...and saves 2
	s = settle(s, sent, [[1, 10]]);           // the server answers for the first request
	assert.deepEqual(s.pending, { 1: false, 2: true });
	assert.deepEqual(s.saved, { 2: 12 });     // 1 is shown unsaved, 2 saved
	assert.deepEqual(batch(s.pending), { save: [2], unsave: [1] });
});

test("the server's list replaces the device's, so a star from another device appears", () => {
	const s = settle({ saved: { 1: 10 }, pending: {} }, {}, [[7, 30]]);
	assert.deepEqual(s.saved, { 7: 30 });
});

test("a guest's list is handed to the account as queued saves", () => {
	const s = adopt({ saved: { 1: 5 }, pending: {} }, { saved: { 1: 9, 2: 8 }, pending: {} }, 50);
	assert.deepEqual(s.saved, { 1: 5, 2: 8 });
	assert.deepEqual(batch(s.pending), { save: [1, 2], unsave: [] });
});
