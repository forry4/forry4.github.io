import { useEffect, useLayoutEffect, useRef } from "react";

const actionKey = (entry) => JSON.stringify([entry.turn, entry.pid, entry.action, entry.parts]);
const visible = (node) => node && node.getBoundingClientRect().width > 0;
const bounds = (node) => {
  const { left, top, width, height } = node.getBoundingClientRect();
  return { left, top, width, height };
};
const columnCards = (game) => new Map(Object.entries(game?.players || {}).flatMap(([pid, player]) =>
  Object.entries(player.columns || {}).flatMap(([planet, cards]) => cards.map((card) =>
    [String(card.id), { card, pid, key: `column-${pid}-${planet}` }]))));
const publicFace = (card) => {
  const face = document.createElement("div");
  face.className = `or-agent or-${card.planet}`;
  const title = document.createElement("strong"); title.textContent = card.name;
  const text = document.createElement("span"); text.className = "or-agent-text"; text.textContent = card.description;
  face.append(title, text);
  return face;
};

// Only confirmed public actions and changes to our own visible hand drive card
// travel. No inferred opponent hand, optimistic move, or animation-gated input.
export function useCardMotion({ game, catalog, myId, roomId, connected, surface }) {
  const previous = useRef(null);
  const faces = useRef(new Map());
  const running = useRef(new Set());
  const reduced = useRef(false);
  const pendingFrame = useRef(null);

  useEffect(() => {
    const media = matchMedia("(prefers-reduced-motion: reduce)");
    const stop = () => {
      pendingFrame.current?.();
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
    const resize = () => {
      // A queued flight has not measured its destinations yet. Let it pick up
      // the new geometry, including scroll anchoring after a mobile decision.
      for (const finish of [...running.current]) finish();
      capture();
    };
    const scroll = (event) => {
      // Auto-following the log is unrelated to card geometry and happens on
      // precisely the same update as a card play. It must not cancel the flight.
      if (event.target === document || event.target === window || event.target?.classList?.contains("or-hand")) resize();
    };
    window.addEventListener("resize", resize);
    window.addEventListener("scroll", scroll, true);
    window.visualViewport?.addEventListener("resize", resize);
    window.visualViewport?.addEventListener("scroll", resize);
    const visibility = () => { if (document.hidden) stop(); };
    document.addEventListener("visibilitychange", visibility);
    return () => {
      stop();
      media.removeEventListener("change", preference);
      window.removeEventListener("resize", resize);
      window.removeEventListener("scroll", scroll, true);
      window.visualViewport?.removeEventListener("resize", resize);
      window.visualViewport?.removeEventListener("scroll", resize);
      document.removeEventListener("visibilitychange", visibility);
    };
  }, [surface]);

  useLayoutEffect(() => {
    const root = surface.current;
    const old = previous.current;
    const hand = game?.players?.[myId]?.hand || [];
    const actions = (game?.log || []).filter((entry) => entry.action);
    const cached = faces.current;
    const columns = columnCards(game);
    const nodes = [...root?.querySelectorAll(".or-hand [data-card-id]") || []];
    faces.current = new Map(nodes.filter(visible).map((node) =>
      [String(node.dataset.cardId), { rect: bounds(node), face: node.cloneNode(true) }]));
    previous.current = {
      roomId, connected, turn: game?.turn_number, phase: game?.phase,
      hand: new Set(hand.map((card) => String(card.id))),
      actions: new Set(actions.map(actionKey)),
      columns,
    };
    if (!root || !old || !connected || !old.connected || old.roomId !== roomId
      || reduced.current || matchMedia("(prefers-reduced-motion: reduce)").matches
      || document.hidden || game?.turn_number < old.turn || game?.turn_number > old.turn + 1) {
      pendingFrame.current?.();
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
      if (reveal) ghost.dataset.arrivalCard = reveal.dataset.cardId;
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
      // Draws enter entirely from off-screen left, at the settled hand height.
      // No pause on an existing card: travel straight to the final sorted slot.
      const duration = draw ? 1500 : 1200;
      const fromColumn = kind === "transfer" || kind === "exile";
      const startSize = fromColumn ? .3 : 1;
      const endSize = kind === "exile" ? .85 : size;
      const animation = ghost.animate(draw ? [
        { transform: `translateX(${-from.left - width - 24}px)`, opacity: 1, easing: "ease-in-out" },
        { transform: "translateX(0)", opacity: 1 },
      ] : [
        { transform: `translate(0, 0) scale(${startSize})`, opacity: 1 },
        { transform: `translate(${dx * .45}px, ${dy * .45 - 28}px) scale(${fromColumn ? .85 : .68}) rotate(-4deg)`, opacity: 1, offset: .45 },
        { opacity: .95, offset: .82 },
        { transform: `translate(${dx}px, ${dy}px) scale(${endSize}) rotate(0deg)`, opacity: 0 },
      ], { duration, delay, easing: draw ? "linear" : "cubic-bezier(.4,0,.2,1)", fill: "both" });
      const arrival = reveal?.animate([{ opacity: 0 }, { opacity: 0, offset: .99 }, { opacity: 1 }],
        { duration, delay, fill: "both" });
      const finish = () => {
        running.current.delete(finish);
        animation.cancel(); arrival?.cancel(); ghost.remove();
      };
      finish.isStale = () => {
        if (!reveal) return false;
        if (!root.contains(reveal)) return true;
        const rect = bounds(reveal);
        return Math.abs(rect.left - from.left) > 1 || Math.abs(rect.top - from.top) > 1
          || Math.abs(rect.width - from.width) > 1 || Math.abs(rect.height - from.height) > 1;
      };
      running.current.add(finish);
      animation.onfinish = finish;
    };

    // Read destinations after React has settled controls and the mobile browser
    // has applied scroll anchoring. Hide new faces before that first paint.
    const drawn = nodes.filter((node) => !old.hand.has(node.dataset.cardId) && visible(node));
    if (!drawn.length && actions.every((entry) => old.actions.has(actionKey(entry)))
      && hand.length === old.hand.size && hand.every((card) => old.hand.has(String(card.id)))
      && columns.size === old.columns?.size
      && [...columns].every(([id, card]) => old.columns.get(id)?.pid === card.pid)) return;
    const holds = drawn.map((node) => node.animate([{ opacity: 0 }, { opacity: 0 }], { duration: 1, fill: "both" }));
    let frame;
    const cancelPending = () => { cancelAnimationFrame(frame); holds.forEach((hold) => hold.cancel()); pendingFrame.current = null; };
    pendingFrame.current?.();
    pendingFrame.current = cancelPending;
    frame = requestAnimationFrame(() => {
      frame = requestAnimationFrame(() => {
        pendingFrame.current = null;
        holds.forEach((hold) => hold.cancel());
        if (!root.isConnected || reduced.current || document.hidden) return;
        for (const finish of [...running.current]) if (finish.isStale()) finish();
        const currentNodes = [...root.querySelectorAll(".or-hand [data-card-id]")];
        faces.current = new Map(currentNodes.filter(visible).map((node) =>
          [String(node.dataset.cardId), { rect: bounds(node), face: node.cloneNode(true) }]));
        const recruited = new Set();
        for (const entry of actions.filter((entry) => !old.actions.has(actionKey(entry)))) {
          if (!["recruit", "technology", "leader"].includes(entry.action)) continue;
          const id = entry.parts?.find((part) => typeof part === "object" && part.c != null)?.c;
          const card = catalog?.cards?.[String(id)];
          if (!card) continue;
          if (entry.action === "recruit") recruited.add(String(id));
          let source = entry.pid === myId ? cached.get(String(id)) : null;
          if (!source) {
            const seat = byKey(`seat-${entry.pid}`);
            if (!seat) continue;
            const rect = bounds(seat);
            const face = publicFace(card);
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
        // Both columns are public. Membership changes identify transfers, arrivals
        // from the deck, and exiles without ever inspecting an opposing hand.
        const board = root.querySelector(".or-influence");
        const centreFace = (rect) => ({ left: rect.left + rect.width / 2 - 73, top: rect.top + rect.height / 2 - 76, width: 146, height: 152 });
        const edge = (rect) => ({ ...centreFace(rect), left: bounds(board).left - 170 });
        let step = 0;
        if (board) {
          for (const [id, current] of columns) {
            const before = old.columns?.get(id);
            if (before?.pid === current.pid || recruited.has(id)) continue;
            const target = byKey(current.key), source = before && byKey(before.key);
            if (!target || (before && !source)) continue;
            const from = before ? centreFace(bounds(source)) : edge(bounds(target));
            fly(publicFace(current.card), from, bounds(target), before ? "transfer" : "mobilize", step++ * 220);
          }
          for (const [id, before] of old.columns || []) {
            if (columns.has(id)) continue;
            const source = byKey(before.key);
            if (source) fly(publicFace(before.card), centreFace(bounds(source)), edge(bounds(source)), "exile", step++ * 220);
          }
        }
        if (drawn.length) {
          let index = 0;
          for (const node of drawn) {
            // A newer server response can remove a card during the two-frame
            // layout settle (for example, an automatic discard).
            if (!root.contains(node)) continue;
            const card = faces.current.get(node.dataset.cardId);
            if (!card) continue;
            fly(card.face, card.rect, card.rect, "draw", index++ * 230, node);
          }
        }
      });
    });
  }, [game, connected, roomId, myId, catalog, surface]);
}
