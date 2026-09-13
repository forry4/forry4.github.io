import { useEffect, useLayoutEffect, useRef } from "react";

const actionKey = (entry) => JSON.stringify([entry.turn, entry.pid, entry.action, entry.parts]);
const visible = (node) => node && node.getBoundingClientRect().width > 0;
const bounds = (node) => {
  const { left, top, width, height } = node.getBoundingClientRect();
  return { left, top, width, height };
};

// Only confirmed public actions and changes to our own visible hand drive card
// travel. No inferred opponent hand, optimistic move, or animation-gated input.
export function useCardMotion({ game, catalog, myId, roomId, connected, surface }) {
  const previous = useRef(null);
  const faces = useRef(new Map());
  const running = useRef(new Set());
  const reduced = useRef(false);

  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const stop = () => {
      for (const finish of [...running.current]) finish();
    };
    const preference = () => { reduced.current = media.matches; if (media.matches) stop(); };
    const capture = () => {
      faces.current = new Map([...surface.current?.querySelectorAll(".or-hand [data-card-id]") || []]
        .filter(visible).map((node) => [String(node.dataset.cardId), { rect: bounds(node), face: node.cloneNode(true) }]));
    };
    preference();
    media.addEventListener("change", preference);
    // Geometry is refreshed on scroll/resize, not just on a server broadcast.
    const resize = () => { stop(); capture(); };
    const scroll = (event) => {
      // Auto-following the log is unrelated to card geometry and happens on
      // precisely the same update as a card play. It must not cancel the flight.
      if (event.target === document || event.target === window || event.target?.classList?.contains("or-hand")) resize();
    };
    window.addEventListener("resize", resize);
    window.addEventListener("scroll", scroll, true);
    const visibility = () => { if (document.hidden) stop(); };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stop();
      media.removeEventListener("change", preference);
      window.removeEventListener("resize", resize);
      window.removeEventListener("scroll", scroll, true);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [surface]);

  useLayoutEffect(() => {
    const root = surface.current;
    const old = previous.current;
    const hand = game?.players?.[myId]?.hand || [];
    const actions = (game?.log || []).filter((entry) => entry.action);
    const cached = faces.current;
    const nodes = [...root?.querySelectorAll(".or-hand [data-card-id]") || []];
    faces.current = new Map(nodes.filter(visible).map((node) =>
      [String(node.dataset.cardId), { rect: bounds(node), face: node.cloneNode(true) }]));
    previous.current = {
      roomId, connected, turn: game?.turn_number, phase: game?.phase,
      hand: new Set(hand.map((card) => String(card.id))),
      actions: new Set(actions.map(actionKey)),
    };
    if (!root || !old || !connected || !old.connected || old.roomId !== roomId
      || reduced.current || matchMedia("(prefers-reduced-motion: reduce)").matches
      || document.hidden || game?.turn_number < old.turn || game?.turn_number > old.turn + 1) {
      for (const finish of [...running.current]) finish();
      return;
    }
    const byKey = (key) => [...root.querySelectorAll("[data-motion-key]")]
      .find((node) => node.dataset.motionKey === key && visible(node));
    const fly = (face, from, to, kind, delay = 0, reveal) => {
      const ghost = face.cloneNode(true);
      ghost.classList.remove("selected", "discarding", "playable");
      ghost.classList.add("or-card-flight");
      ghost.dataset.flight = kind;
      ghost.removeAttribute("data-card-id");
      ghost.setAttribute("aria-hidden", "true");
      ghost.setAttribute("inert", "");
      ghost.tabIndex = -1;
      const width = from.width, height = from.height;
      Object.assign(ghost.style, { left: `${from.left}px`, top: `${from.top}px`, width: `${width}px`, height: `${height}px` });
      root.closest(".orbit").appendChild(ghost);
      const dx = to.left + to.width / 2 - from.left - width / 2;
      const dy = to.top + to.height / 2 - from.top - height / 2;
      const draw = kind === "draw";
      const size = Math.min(.3, Math.max(.12, to.width / width));
      // A DRAW IS TWO MOVEMENTS, NOT ONE. `to` for a draw is the LEFTMOST slot in
      // the hand — the card is dealt there, at full size, and only then slides
      // right into the place the sort order gives it. One straight flight from
      // wherever the card happens to belong looked like it materialised in the
      // middle of the fan; dealing to a fixed edge and then re-ordering is what
      // the hands actually do, and it also reads correctly when several cards
      // arrive at once, because each one is dealt to the same spot in turn.
      const duration = draw ? 760 : 620;
      const animation = ghost.animate(draw ? [
        { transform: `translate(${dx - 54}px, ${dy + 16}px) scale(.62) rotate(-9deg)`, opacity: 0 },
        { transform: `translate(${dx}px, ${dy}px) scale(1) rotate(0deg)`, opacity: 1, offset: .26 },
        { transform: `translate(${dx}px, ${dy}px) scale(1) rotate(0deg)`, opacity: 1, offset: .46 },
        { transform: "translate(0, 0) scale(1) rotate(0deg)", opacity: 1 },
      ] : [
        { transform: "translate(0, 0) scale(1)", opacity: 1 },
        { transform: `translate(${dx * .45}px, ${dy * .45 - 28}px) scale(.68) rotate(-4deg)`, opacity: 1, offset: .45 },
        { opacity: .95, offset: .82 },
        { transform: `translate(${dx}px, ${dy}px) scale(${size}) rotate(0deg)`, opacity: 0 },
      ], { duration, delay, easing: "cubic-bezier(.4,0,.2,1)", fill: "both" });
      const arrival = reveal?.animate([{ opacity: 0 }, { opacity: 0, offset: .88 }, { opacity: 1 }],
        { duration, delay, fill: "both" });
      const finish = () => {
        running.current.delete(finish);
        animation.cancel(); arrival?.cancel(); ghost.remove();
      };
      running.current.add(finish);
      animation.onfinish = finish;
    };

    for (const entry of actions.filter((entry) => !old.actions.has(actionKey(entry)))) {
      if (!["recruit", "technology", "leader"].includes(entry.action)) continue;
      const id = entry.parts?.find((part) => typeof part === "object" && part.c != null)?.c;
      const card = catalog?.cards?.[String(id)];
      if (!card) continue;
      let source = entry.pid === myId ? cached.get(String(id)) : null;
      if (!source) {
        const seat = byKey(`seat-${entry.pid}`);
        if (!seat) continue;
        const rect = bounds(seat);
        const face = document.createElement("div");
        face.className = `or-agent or-${card.planet}`;
        const title = document.createElement("strong"); title.textContent = card.name;
        const text = document.createElement("span"); text.className = "or-agent-text"; text.textContent = card.description;
        face.append(title, text);
        source = { face, rect: { left: rect.left + rect.width / 2 - 73, top: rect.top, width: 146, height: 166 } };
      }
      const level = game.players?.[entry.pid]?.technology?.[card.faction];
      // `column-<pid>-<planet>` is the played-Agent cell in that seat's player
      // box — the ONE place a recruited Agent lands now that the separate
      // placed-Agent panels are gone.
      const target = entry.action === "recruit"
        ? byKey(`column-${entry.pid}-${card.planet}`)
        : entry.action === "leader" ? byKey(`leader-${entry.pid}`)
          : byKey(`tech-rung-${card.faction}-${level}`) || byKey(`tech-${entry.pid}-${card.faction}`);
      if (visible(target)) fly(source.face, source.rect, bounds(target), entry.action);
    }
    // THE HAND HAS NO DECK BESIDE IT ANY MORE, so a drawn card is dealt to the
    // hand's own left edge. The landing spot is the LEFTMOST card's box — the
    // first slot, whatever card ends up occupying it once the hand is re-sorted
    // — and every new card is dealt there before travelling to its own place.
    const drawn = nodes.filter((node) => !old.hand.has(node.dataset.cardId) && visible(node));
    const slot = nodes.find(visible);
    if (drawn.length && slot) {
      const first = bounds(slot);
      let index = 0;
      for (const node of drawn) {
        const card = faces.current.get(node.dataset.cardId);
        fly(card.face, card.rect, { ...first, top: card.rect.top }, "draw", index++ * 110, node);
      }
    }
  }, [game, connected, roomId, myId, catalog, surface]);
}
