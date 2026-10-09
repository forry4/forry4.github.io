import { test } from "node:test";
import assert from "node:assert/strict";
import { botTierLabel, BOT_TIER_LABELS, SPENDER_AI_TIERS } from "../../../shared/botTiers.js";

test("every game's label map names every tier it lists", () => {
	for (const [game, labels] of Object.entries(BOT_TIER_LABELS)) {
		assert.ok(Object.keys(labels).length > 0, `${game} has no tiers`);
		for (const [id, label] of Object.entries(labels)) {
			assert.equal(typeof label, "string", `${game}:${id}`);
			assert.ok(label.length > 0, `${game}:${id}`);
		}
	}
});

test("Spender's variant codes read as difficulties, not codes", () => {
	for (const code of Object.keys(SPENDER_AI_TIERS)) {
		assert.notEqual(botTierLabel("spender", code), code);
	}
});

test("no tier renders nothing; a retired tier keeps a readable name", () => {
	assert.equal(botTierLabel("duel", null), null);
	assert.equal(botTierLabel("duel", ""), null);
	const retired = botTierLabel("dontminion", "retiredtier");
	assert.ok(retired && /^[A-Z]/.test(retired), retired);
});
