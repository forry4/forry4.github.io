const PLANETS = ["mercury", "venus", "terra", "mars", "jupiter"];
const PLANET_ORDER = Object.fromEntries(PLANETS.map((planet, i) => [planet, i]));

// The hand's display order (see the note above its use in Orbit.jsx).
export function sortedHand(hand) {
  return [...(hand || [])].sort((a, b) =>
    (PLANET_ORDER[a?.planet] ?? PLANETS.length) - (PLANET_ORDER[b?.planet] ?? PLANETS.length)
    || (a?.cost ?? 0) - (b?.cost ?? 0)
    || (a?.id ?? 0) - (b?.id ?? 0));
}

// Choices read in the order of what they point at: planets Mercury -> Jupiter,
// as the board lays them out, and hand cards in the hand's own order. Server
// order is whatever the engine happened to generate. Only moves that name a
// planet or a hand card are reordered, and they keep the slots they already
// held, so an Accept/Decline or Skip beside them stays where it was.
export function orderedChoices(game, moves) {
  const handIndex = new Map(sortedHand(game?.players?.[game?.pending_pid]?.hand)
    .map((card, i) => [card.id, i]));
  const planetRank = (planet) => PLANET_ORDER[planet] ?? PLANETS.length;
  const rank = (move) => {
    if ("planet" in move) return [planetRank(move.planet)];
    // A pair sorts by its span first; the two orientations of one pair
    // ("Venus first, then Mercury") then follow the planet that moves first.
    if ("planets" in move) {
      const ranks = move.planets.map(planetRank);
      return [Math.min(...ranks), Math.max(...ranks), ranks[0]];
    }
    if (move.bonus_area === "planet") return [planetRank(move.slot)];
    if ("card_id" in move) return [handIndex.get(move.card_id) ?? handIndex.size];
    return null;
  };
  const ranked = moves.map((move, i) => ({ move, i, rank: rank(move) }));
  const slots = ranked.filter((entry) => entry.rank);
  const sorted = [...slots].sort((a, b) => {
    for (let k = 0; k < Math.max(a.rank.length, b.rank.length); k += 1) {
      const d = (a.rank[k] ?? -1) - (b.rank[k] ?? -1);
      if (d) return d;
    }
    return a.i - b.i;
  });
  const out = [...moves];
  slots.forEach((slot, k) => { out[slot.i] = sorted[k].move; });
  return out;
}

// Presentation choices always retain an exact server-legal response.
export function automaticChoices(game) {
  const moves = game?.legal_moves || [];
  if (!moves.length || !moves.every((move) => move.action === "choose")) return [];
  if (moves.length === 1) return moves;
  const task = game.pending?.task;
  const hand = game.players?.[game.pending_pid]?.hand || [];
  // Matching influence can interrupt discards with a capture bonus. Its order
  // is meaningful, even if all the original cards will eventually leave.
  const remaining = Number(task?.count) - (task?.done || 0);
  if (task?.type === "discard_hand" && !task.reward
    && (task.count === "all" || remaining >= hand.length)
    && hand.length === moves.length && moves.every((move) => hand.some((card) => card.id === move.card_id))) return moves;
  return [];
}

export function adjacentPairs(moves) {
  const pairs = new Map();
  for (const move of moves) {
    const key = [...move.planets].sort().join(",");
    if (!pairs.has(key)) pairs.set(key, []);
    pairs.get(key).push(move);
  }
  return [...pairs.values()];
}

export function adjacentOrderMatters(game, move) {
  const sign = game.pending_pid === game.order[0] ? 1 : -1;
  return move.planets.some((planet) => game.influence[planet] != null
    && game.influence[planet] * sign + game.pending.task.amount >= 4);
}
