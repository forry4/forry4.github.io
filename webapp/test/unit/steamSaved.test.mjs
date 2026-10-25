// The Steam Filter's saved / not-interested sync logic (steamfilter/saved.js).
import { test } from "node:test";
import assert from "node:assert/strict";
import { setMark, markOf, adopt, settle, batch } from "../../../steamfilter/saved.js";

const EMPTY = { saved: {}, hidden: {}, pending: {} };

test("a guest's marks are local only, and a game carries one mark at a time", () => {
	let s = setMark(EMPTY, 105600, "saved", 10, false);
	assert.deepEqual(s, { saved: { 105600: 10 }, hidden: {}, pending: {} });
	s = setMark(s, 105600, "hidden", 20, false);
	assert.deepEqual(s, { saved: {}, hidden: { 105600: 20 }, pending: {} });
	assert.equal(markOf(s, 105600), "hidden");
	assert.deepEqual(setMark(s, 105600, "none", 30, false), EMPTY);
});

test("a member's mark is queued until the server has it", () => {
	let s = setMark(EMPTY, 105600, "saved", 10, true);
	s = setMark(s, 440, "hidden", 10, true);
	const sent = { ...s.pending };
	assert.deepEqual(batch(sent), { save: [105600], unsave: [], hide: [440], unhide: [] });
	s = settle(s, sent, { saved: [[105600, 11]], hidden: [[440, 11], [7, 3]] });
	assert.deepEqual(s, { saved: { 105600: 11 }, hidden: { 440: 11, 7: 3 }, pending: {} });
});

test("clearing a mark asks for both removals", () => {
	assert.deepEqual(batch({ 9: "none" }), { save: [], unsave: [9], hide: [], unhide: [9] });
});

test("a change made while a request was out stays queued and shown", () => {
	let s = setMark(EMPTY, 1, "saved", 10, true);
	const sent = { ...s.pending };            // request goes out: save 1
	s = setMark(s, 1, "hidden", 11, true);    // ...the reader hides 1 meanwhile
	s = setMark(s, 2, "saved", 12, true);     // ...and saves 2
	s = settle(s, sent, { saved: [[1, 10]], hidden: [] });
	assert.deepEqual(s.pending, { 1: "hidden", 2: "saved" });
	assert.deepEqual([s.saved, s.hidden], [{ 2: 12 }, { 1: 11 }]);
});

test("a server from before not-interested: saves land, hides stay queued and shown", () => {
	let s = setMark(EMPTY, 1, "saved", 10, true);
	s = setMark(s, 2, "hidden", 10, true);
	s = settle(s, { ...s.pending }, { saved: [[1, 10]] });
	assert.deepEqual(s.pending, { 2: "hidden" });
	assert.deepEqual([s.saved, s.hidden], [{ 1: 10 }, { 2: 10 }]);
});

test("the server's lists replace the device's, so a mark from another device appears", () => {
	const s = settle({ saved: { 1: 10 }, hidden: { 2: 10 }, pending: {} }, {}, { saved: [[7, 30]], hidden: [[8, 30]] });
	assert.deepEqual([s.saved, s.hidden], [{ 7: 30 }, { 8: 30 }]);
});

test("a guest's lists are handed to the account as queued marks", () => {
	const s = adopt({ saved: { 1: 5 }, hidden: {}, pending: {} },
		{ saved: { 1: 9, 2: 8 }, hidden: { 3: 7 }, pending: {} }, 50);
	assert.deepEqual([s.saved, s.hidden], [{ 1: 9, 2: 8 }, { 3: 7 }]);
	assert.deepEqual(batch(s.pending), { save: [1, 2], unsave: [], hide: [3], unhide: [] });
});
