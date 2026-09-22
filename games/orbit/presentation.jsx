import { useEffect, useMemo, useRef, useState } from "react";

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

/* THE SKY BEHIND THE TABLE. Painted ONCE per viewport size, never per frame:
   the game already runs a WASM search pool in this tab on the Hard tiers, and a
   backdrop that redraws on requestAnimationFrame would compete with it for the
   main thread for no information at all. So it is three layers, each of which
   costs nothing after it is drawn:
   - the nebula, on a canvas drawn at a QUARTER resolution (it is nothing but
     soft gradients, so upscaling is free of visible loss) and drifted by a
     slow CSS transform the compositor runs on its own;
   - the steady stars, one full-resolution canvas;
   - a few dozen brighter stars as tiny elements whose twinkle is a CSS opacity
     animation, again compositor-only.
   The global reduced-motion rule stops both animations; hidden tabs throttle
   them. Seeded, so the sky is the same every time the table is opened. */
const SKY_TWINKLES = 34;
function skyRandom(seed) {
  let s = seed;
  return () => (s = (s * 16807) % 2147483647) / 2147483647;
}
export function OrbitSky() {
  const nebula = useRef(null);
  const stars = useRef(null);
  useEffect(() => {
    let timer = null;
    const draw = () => {
      const w = window.innerWidth, h = window.innerHeight;
      const n = nebula.current, s = stars.current;
      if (!n || !s || !w || !h) return;
      const q = 0.25;
      n.width = Math.ceil(w * q); n.height = Math.ceil(h * q);
      const nx = n.getContext("2d");
      if (nx) {
        nx.setTransform(q, 0, 0, q, 0, 0);
        nx.fillStyle = "#060812"; nx.fillRect(0, 0, w, h);
        for (const [bx, by, rgb, alpha, radius] of [
          [0.2, 0.15, "120,84,215", 0.55, 0.55], [0.8, 0.3, "28,141,175", 0.5, 0.5],
          [0.55, 0.88, "205,80,150", 0.3, 0.6], [0.35, 0.55, "66,209,199", 0.16, 0.45],
        ]) {
          const g = nx.createRadialGradient(w * bx, h * by, 0, w * bx, h * by, Math.max(w, h) * radius);
          g.addColorStop(0, `rgba(${rgb},${alpha})`); g.addColorStop(1, `rgba(${rgb},0)`);
          nx.fillStyle = g; nx.fillRect(0, 0, w, h);
        }
      }
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      s.width = Math.ceil(w * dpr); s.height = Math.ceil(h * dpr);
      const sx = s.getContext("2d");
      if (sx) {
        sx.setTransform(dpr, 0, 0, dpr, 0, 0);
        const rand = skyRandom(7);
        for (let i = 0, count = Math.round(w * h / 900); i < count; i++) {
          const size = rand();
          sx.globalAlpha = 0.3 + rand() * 0.6;
          sx.fillStyle = rand() < 0.3 ? "#8bd9ff" : "#ffffff";
          sx.beginPath();
          sx.arc(rand() * w, rand() * h, size < 0.04 ? 1.4 : size < 0.3 ? 0.95 : 0.55, 0, Math.PI * 2);
          sx.fill();
        }
        sx.globalAlpha = 1;
      }
    };
    draw();
    const onResize = () => { clearTimeout(timer); timer = setTimeout(draw, 150); };
    window.addEventListener("resize", onResize);
    return () => { clearTimeout(timer); window.removeEventListener("resize", onResize); };
  }, []);
  const twinkles = useMemo(() => {
    const rand = skyRandom(31);
    return Array.from({ length: SKY_TWINKLES }, () => ({
      left: `${(rand() * 100).toFixed(2)}%`, top: `${(rand() * 100).toFixed(2)}%`,
      "--or-twinkle-time": `${(2.6 + rand() * 4).toFixed(2)}s`,
      "--or-twinkle-delay": `${(-rand() * 6).toFixed(2)}s`,
      "--or-twinkle-size": `${rand() < 0.25 ? 3 : 2}px`,
    }));
  }, []);
  return <div className="or-sky" aria-hidden="true">
    <canvas ref={nebula} className="or-sky-nebula" />
    <canvas ref={stars} className="or-sky-stars" />
    {twinkles.map((style, index) => <i key={index} className="or-sky-twinkle" style={style} />)}
  </div>;
}

// A space on the track as a percentage down it: -4 (their goal) is the top
// spot's centre, +4 (yours) the bottom one's, 0 the middle.
const trackPercent = (space) => (space + 4.5) / 9 * 100;
const sideOf = (space) => space > 0 ? "mine" : space < 0 ? "theirs" : "";

// A captured disc leaves toward its owner. A replacement appears at centre;
// it never slides back across the board as though influence had been reversed.
//
// THREE PIECES RIDE ALONG WITH THE DISC, all decoration and all siblings of it
// (never children, never `.or-disc`): the screen gate reads the disc's own
// animations and a replacement disc must have none.
// - the FILL: the channel from the centre to the disc, in the colour of the
//   seat it leans toward — who is winning this planet, and by how much.
// - the TRAIL: one streak from where the disc was to where it is now, drawn
//   once per authoritative move.
// - the BURST: rings and sparks at the goal when the disc is captured.
// Trail and burst are MOTION, so they only come from a change observed while
// mounted. The board remounts on every (re)connection (its key carries
// `connected`), which is what stops a restored snapshot replaying either.
export function InfluenceDisc({ position, planet, game, myId }) {
  const own = game.players?.[myId]?.captured?.filter((p) => p === planet).length || 0;
  const otherId = game.order?.find((pid) => pid !== myId);
  const other = game.players?.[otherId]?.captured?.filter((p) => p === planet).length || 0;
  const previous = useRef({ position, own, other, captured: position == null });
  const captured = position == null;
  const destination = captured ? own > previous.current.own ? 4 : other > previous.current.other ? -4 : previous.current.position ?? 0 : position;
  const returning = !captured && previous.current.captured;
  // The streak persists (finished, invisible) until the next move replaces it,
  // so an unrelated re-render cannot cut it off halfway. Its key only moves on
  // a real change, so the same streak is never drawn twice.
  const lastTrail = useRef(null);
  const moved = !returning && previous.current.position != null && destination !== previous.current.position;
  const trail = returning ? null : moved
    ? { from: previous.current.position, to: destination, key: (lastTrail.current?.key || 0) + 1 }
    : lastTrail.current;
  const lastBurst = useRef(null);
  const burst = !captured ? null : !previous.current.captured
    ? { side: sideOf(destination), key: (lastBurst.current?.key || 0) + 1 }
    : lastBurst.current;
  useEffect(() => {
    previous.current = { position: destination, own, other, captured };
    lastTrail.current = trail;
    lastBurst.current = burst;
  });
  const at = trackPercent(destination);
  const lean = sideOf(destination);
  return <>
    <i className={`or-track-fill${lean ? ` ${lean}` : ""}${captured ? " captured" : ""}${returning ? " returning" : ""}`} aria-hidden="true"
      style={{ top: `${Math.min(at, 50)}%`, height: `${Math.abs(at - 50)}%` }} />
    {trail && <i key={`trail-${trail.key}`} aria-hidden="true"
      className={`or-disc-trail ${trail.to > trail.from ? "down mine" : "up theirs"}`}
      style={{ top: `${Math.min(trackPercent(trail.from), trackPercent(trail.to))}%`,
        height: `${Math.abs(trackPercent(trail.to) - trackPercent(trail.from))}%` }} />}
    <i className={`or-disc${captured ? " captured" : ""}${returning ? " returning" : ""}`}
      style={{ "--or-position": at + "%" }}
      aria-label={`${planet}: ${captured ? "captured" : position === 0 ? "neutral" : `${Math.abs(position)} toward ${position > 0 ? "you" : "opponent"}`}`} />
    {burst && <span key={`burst-${burst.key}`} className={`or-capture-burst ${burst.side}`} aria-hidden="true"
      style={{ top: `${trackPercent(destination)}%` }}>
      <i className="ring" /><i className="ring outer" />
      {[0, 1, 2, 3, 4, 5, 6].map((n) => <i className="spark" key={n} style={{ "--or-spark": n }} />)}
      <b className="or-capture-tag">{planet} captured</b>
    </span>}
  </>;
}
