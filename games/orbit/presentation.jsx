import { useEffect, useLayoutEffect, useRef, useState } from "react";

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
    setChange({ delta, id: performance.now() });
    const timer = setTimeout(() => setChange(null), 1800);
    return () => clearTimeout(timer);
  }, [value, animate]);
  return <span className={`or-resource ${kind}`}>
    <ResourceIcon kind={kind} /><b>{value}</b><span>{kind === "credits" ? "Credits" : "Zenithium"}</span>
    {change && <em key={change.id} className={`or-resource-delta ${change.delta > 0 ? "gain" : "spent"}`}>
      {change.delta > 0 ? "+" : "−"}{Math.abs(change.delta)}
    </em>}
  </span>;
}

// Compare rendered public values only. Reconnects establish a fresh baseline,
// and equal rebroadcasts never replay a move. Rules and input stay authoritative.
export function useBoardMotion(game, connected, roomId) {
  const surface = useRef(null);
  const previous = useRef(new Map());
  useLayoutEffect(() => { previous.current = new Map(); }, [roomId]);
  useLayoutEffect(() => {
    const nodes = surface.current?.querySelectorAll("[data-motion-key]") || [];
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const current = new Map();
    for (const node of nodes) {
      const key = node.dataset.motionKey;
      const value = node.dataset.motionValue;
      current.set(key, value);
      if (connected && !reduced && previous.current.has(key) && previous.current.get(key) !== value) {
        node.getAnimations().forEach((animation) => animation.cancel());
        node.animate([{ filter: "brightness(1)" }, { filter: "brightness(1.25)", offset: .2 }, { filter: "brightness(1)" }],
          { duration: 950, easing: "ease-out" });
      }
    }
    previous.current = connected ? current : new Map();
  }, [game, connected]);
  return surface;
}
