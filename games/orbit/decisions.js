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
