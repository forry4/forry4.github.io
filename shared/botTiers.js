/* THE BOT TIERS EVERY GAME OFFERS — one list per game, and the only place each is written.
 *
 * Each list is what that game's create modal renders, what its remembered
 * last-played tier is validated against, and where its Active/History rows get
 * the words for `LobbyBotTier`. They lived inside each game's own screen until
 * the profile page (shared/Profile.jsx) needed them too: it names the bot every
 * finished game was played against, across all eleven games, and it cannot load
 * eleven game bundles to find out that "bmplus" is called Money+. A second
 * hand-written copy of the words is the drift `test_lobby_bot_tier.py` exists to
 * stop, so the lists moved here instead and each game imports its own.
 *
 * The shapes differ by game (`value/label` in some, `id/name` in others) because
 * they were written independently; `botTierLabels` below reads both. Rag Tag has
 * one bot and no ladder, Where Wolf? and SecretNames have no bot, so none of the
 * three is here.
 */

// ─── Spender ── variant code -> tier word. The codes are what the server stores
// (`ai_variant`); the create modal's offered list (AI_VARIANTS) stays in Spender.jsx.
export const SPENDER_AI_TIERS = { H2: "easy", H3: "medium", S: "hard", N: "expert" };

// ─── Castles of Crimson ──────────────────────────────────────────
// The tiers the create modal OFFERS. `main.AI_DIFFICULTIES` also carries
// "normal", which the picker has never shown — so this list, not that tuple, is
// what a remembered last-played tier is validated against.
export const COC_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "A capable search opponent — a solid game without neural-net strength" },
  { value: "hard", label: "Hard", title: "The first-generation neural net, searched in your browser — a real challenge" },
  { value: "expert", label: "Expert", title: "The strongest neural net, searched in your browser" },
];

// ─── Spender Duel ────────────────────────────────────────────────
// Bot tiers (wire ids match main.AI_DIFFICULTIES). Easy = the trivial random-legal
// bot; Normal/Hard = determinized MCTS at different budgets.
export const DUEL_BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, barely plans" },
  { id: "normal", name: "Normal", desc: "Thinks a little, makes mistakes" },
  { id: "hard", name: "Hard", desc: "Searches properly — a real fight" },
  { id: "expert", name: "Expert", desc: "Hard, retrained to punish impatience" },
];

// ─── Dontminion ──────────────────────────────────────────────────
// The bot tiers OFFERED in the picker, and now the whole shipped ladder: a
// barely-playing Random and the real opponent, Big Money+. Plain Big Money
// left the UI first and has since been dropped from `main.AI_DIFFICULTIES`
// too — it is a strictly weaker bmplus, so it only added a choice no one
// should pick. Keep this list a subset of AI_DIFFICULTIES: the server coerces
// anything it doesn't know to the default, so an id that drifts out of that
// tuple silently hands the player a different bot than the one they picked.
//
// LABELS ARE SHORT ON PURPOSE. These render as a `cm-seg` sharing one row with
// the Bots counter (the side-by-side layout is what keeps the create modal
// inside its 148px budget), and `.cm-seg-btn` is `white-space:nowrap` inside an
// `overflow:hidden` track — a label too wide for its half of the track is
// CLIPPED, not wrapped. The full name rides along as the button's title.
export const DONTMINION_BOTS = [
  { id: "easy", name: "Random", title: "Random legal moves — barely plays" },
  { id: "bmplus", name: "Money+", title: "Big Money+ — reads the board for a terminal, knows how the game ends" },
];

// ─── Dissonance ──────────────────────────────────────────────────
export const DISSONANCE_BOT_TIERS = [
  { id: "easy", name: "Easy", desc: "Plays legally, blunders often" },
  { id: "normal", name: "Normal", desc: "Knows which tricks it wants" },
  // The ladder moved up a rung on 2026-08-14: the auction tree was Expert's
  // defining feature and is now Hard's, and Expert is the tree with an opponent
  // model that does not assume it can see your cards.
  { id: "hard", name: "Hard", desc: "Solves the hand exactly and searches the auction, in your browser" },
  { id: "expert", name: "Expert", desc: "Hard, and reads the bidding without assuming it can see your hand" },
];

// ─── Orbit ───────────────────────────────────────────────────────
// The tiers the create modal offers, and — mapped to ids — the list a
// remembered tier is validated against. ONE list, because a hand-written copy
// drifts: when Expert landed the id list still read easy/normal/hard, so
// picking Expert was stored and then rejected on the next open, and the modal
// silently came back on Hard.
export const ORBIT_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "Public-information ranker" },
  { value: "normal", label: "Normal", title: "Effect-aware ranker with a validated server fallback" },
  { value: "hard", label: "Hard", title: "Searches its main action in your browser, resampling the hidden hand every simulation" },
  { value: "expert", label: "Expert", title: "Searches its main action against one coherent hidden world; the strongest tier" },
];

// ─── Black Castle ────────────────────────────────────────────────
export const BLACK_CASTLE_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "Random legal moves" },
];

// ─── Pinch ───────────────────────────────────────────────────────
export const PINCH_AI_TIER_OPTIONS = [
  { value: "easy", label: "Easy", title: "Uniformly random legal actions" },
];

// ─── The words, per game ───────────────────────────────────────────────────
const titled = (s) => String(s).replace(/^./, (c) => c.toUpperCase());
const labelsOf = (options) => Object.fromEntries(options.map((t) => [t.value ?? t.id, t.label ?? t.name]));

// { gameId: { tierId: "Label" } }, keyed by the catalogue id (shared/catalog.js).
export const BOT_TIER_LABELS = {
	spender: Object.fromEntries(Object.entries(SPENDER_AI_TIERS).map(([code, tier]) => [code, titled(tier)])),
	coc: labelsOf(COC_AI_TIER_OPTIONS),
	duel: labelsOf(DUEL_BOT_TIERS),
	dontminion: labelsOf(DONTMINION_BOTS),
	dissonance: labelsOf(DISSONANCE_BOT_TIERS),
	orbit: labelsOf(ORBIT_AI_TIER_OPTIONS),
	blackcastle: labelsOf(BLACK_CASTLE_AI_TIER_OPTIONS),
	pinch: labelsOf(PINCH_AI_TIER_OPTIONS),
};

// A retired tier still sitting on an old game keeps its raw id, title-cased —
// the same fallback `LobbyBotTier` uses — rather than going unnamed.
export function botTierLabel(game, tier) {
	if (!tier) return null;
	return BOT_TIER_LABELS[game]?.[tier] || titled(tier);
}
