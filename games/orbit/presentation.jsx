import { useEffect, useRef, useState } from "react";

export function victoryCondition(game) {
  const discs = game.players?.[game.winner]?.captured || [];
  if (discs.some((planet) => discs.filter((p) => p === planet).length >= 3)) return "Absolute victory";
  if (new Set(discs).size >= 4) return "Democratic victory";
  if (discs.length >= 5) return "Popular victory";
  return null; // Concession, or an older save without a captured-disc result.
}

const resourceName = (kind) => ({ credits: "Credits", zenithium: "Zenithium", influence: "influence" }[kind] || kind);
// Resource-piece choreography follows the same 15% faster timing as Orbit's
// card flights and CSS transitions.
const MOTION_RATE = 0.85;
const scaleMs = (ms) => Math.round(ms * MOTION_RATE);
export function decisionCopy(task, agentName) {
  const remaining = Math.max(1, (Number(task.count) || 1) - (task.done || 0));
  const owner = task.owner === "self" || task.type === "exile_for_matching" ? "your" : "your opponent’s";
  const selected = task.selected?.length || 0;
  const rawPlanet = task.planets?.[task.index || 0];
  const planet = rawPlanet ? rawPlanet[0].toUpperCase() + rawPlanet.slice(1) : "";
  const titles = {
    influence: `Choose a planet to ${task.target === "opponent" ? "give your opponent" : "gain"} ${task.amount} influence`,
    influence_other: `Choose a different planet to gain ${task.amount} influence`,
    split_influence: `Gain ${task.amounts?.[selected]} influence on ${selected ? "a different" : "a"} planet`,
    exile: `Exile ${owner} top Agent${task.reward === "matching_influence" ? ` and gain ${task.amount || 1} influence on its planet` : ""}`,
    exile_for_matching: "Exile your top Agent to gain matching influence",
    transfer: `Take your opponent’s top Agent${task.reward === "matching_influence" ? " and gain 1 influence on its planet" : ""}`,
    discard_hand: "Choose an Agent to discard from your hand",
    develop: `Choose ${task.lowest ? "one of your lowest technologies" : "a technology"} to develop`,
    exile_tier: `Exile Agents from your ${task.planet} column`,
    spend_tier: `Spend ${resourceName(task.resource)} to gain influence`,
    reset_planet: "Choose a disc to return to the centre",
    take_board_bonus: "Choose a bonus token to claim",
    optional_exile_each: `Exile ${agentName || "your top Agent"} from ${planet}?`,
    two_adjacent: `Gain ${task.amount} influence on each of two adjacent planets`,
    adjacent_three: `Choose a centre planet: gain ${task.center} influence there and ${task.neighbor} on each neighbour`,
    optional: task.label,
    choose_branch: task.label || "Choose one effect",
  };
  const notes = [];
  if (task.type === "split_influence") notes.push(`Planet ${selected + 1} of ${task.amounts?.length}. Each must be different.`);
  if (["exile", "transfer", "discard_hand", "exile_for_matching"].includes(task.type)) notes.push(task.count === "all" ? "Discard all remaining Agents, one at a time." : `${remaining} Agent${remaining === 1 ? "" : "s"} remaining.`);
  if (task.restriction === "middle") notes.push("Only discs on the centre space are eligible.");
  if (task.restriction === "dominated") notes.push("Choose a disc on your opponent’s side.");
  if (task.exclude) notes.push(`${task.exclude[0].toUpperCase() + task.exclude.slice(1)} is excluded.`);
  if (task.type === "optional_exile_each") notes.push(`Gain 1 ${task.reward === "influence" ? `${planet} influence` : "Zenithium"}, or keep the Agent.`);
  else if (task.reward === "card_cost") notes.push("Gain Credits equal to the selected Agent’s printed cost.");
  else if (task.reward === "matching_influence" && !["exile", "transfer"].includes(task.type)) notes.push(`Gain ${task.amount || 1} influence on that Agent’s planet.`);
  else if (task.reward && typeof task.reward === "object") notes.push(`After completing the exile, gain ${task.reward.amount} ${resourceName(task.reward.resource)}.`);
  if (task.type === "develop" && task.discount) notes.push(`Pay the next level’s cost, reduced by ${task.discount} Zenithium.`);
  return { title: titles[task.type] || task.label || "Choose how to resolve this effect", detail: notes.join(" ") };
}

// Small vector pieces stay sharp at every device pixel ratio, with no asset fetch.
export function ResourceIcon({ kind }) {
  return <svg className={`or-resource-icon ${kind}`} viewBox="0 0 24 24" fill="none" aria-hidden="true">
    {kind === "credits" ? <>
      <circle cx="12" cy="12" r="10" fill="#725025" stroke="#ffe1a1" />
      <circle cx="12" cy="12" r="7.4" fill="#dca957" stroke="#f6cf88" />
      <path d="M15 8.5h-4.5L8 12l2.5 3.5H15M7 12h8" stroke="#51351b" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
      <path d="M5 8a8 8 0 0 1 8-4" stroke="#fff1cd" strokeLinecap="round" />
    </> : <>
      <path d="m12 1 8 7-3 11-5 4-5-4L4 8Z" fill="#367d9a" stroke="#adf5ff" strokeLinejoin="round" />
      <path d="m12 1-3 8 3 14 4-14Z" fill="#a6efff" />
      <path d="m4 8 5 1 3-8Zm12 1 4-1-3 11-5 4Z" fill="#54bedc" />
      <path d="m4 8 5 1 7 0 4-1M9 9l3 14 4-14" stroke="#e1fbff" strokeWidth=".65" />
    </>}
  </svg>;
}

export function Resource({ kind, value, animate }) {
  const previous = useRef(value);
  const [change, setChange] = useState(null);
  useEffect(() => {
    const delta = value - previous.current;
    previous.current = value;
    if (!animate || !Number.isFinite(delta) || !delta) { setChange(null); return; }
    const rawStagger = delta > 1 ? Math.min(150, 1800 / (delta - 1)) : 0;
    const stagger = scaleMs(rawStagger);
    setChange({ delta, stagger, id: performance.now() });
    const timer = setTimeout(() => setChange(null), scaleMs(Math.max(2800, 1250 + rawStagger * (delta - 1))));
    return () => clearTimeout(timer);
  }, [value, animate]);
  return <span className={`or-resource ${kind}`}>
    <ResourceIcon kind={kind} /><b>{value}</b><span>{kind === "credits" ? "Credits" : "Zenithium"}</span>
    {change?.delta > 0 && <span key={`pieces-${change.id}`} className="or-resource-pieces" aria-hidden="true">
      {Array.from({ length: change.delta }, (_, index) => <i key={index} className="or-resource-piece"
        style={{ "--or-piece-delay": `${index * change.stagger}ms`, "--or-piece-x": `${-28 - (index % 3) * 7}px` }}><ResourceIcon kind={kind} /></i>)}
    </span>}
    {change && <em key={change.id} className={`or-resource-delta ${change.delta > 0 ? "gain" : "spent"}`}>
      {change.delta > 0 ? "+" : "−"}{Math.abs(change.delta)}
    </em>}
  </span>;
}

// A captured disc leaves toward its owner. A replacement appears at centre;
// it never slides back across the board as though influence had been reversed.
export function InfluenceDisc({ position, planet, game, myId }) {
  const own = game.players?.[myId]?.captured?.filter((p) => p === planet).length || 0;
  const otherId = game.order?.find((pid) => pid !== myId);
  const other = game.players?.[otherId]?.captured?.filter((p) => p === planet).length || 0;
  const previous = useRef({ position, own, other, captured: position == null });
  const captured = position == null;
  const destination = captured ? own > previous.current.own ? 4 : other > previous.current.other ? -4 : previous.current.position ?? 0 : position;
  const returning = !captured && previous.current.captured;
  useEffect(() => { previous.current = { position: destination, own, other, captured }; }, [destination, own, other, captured]);
  return <i className={`or-disc${captured ? " captured" : ""}${returning ? " returning" : ""}`}
    style={{ "--or-position": (destination + 4.5) / 9 * 100 + "%" }}
    aria-label={`${planet}: ${captured ? "captured" : position === 0 ? "neutral" : `${Math.abs(position)} toward ${position > 0 ? "you" : "opponent"}`}`} />;
}
