import React from "react";

// One 24-unit drawing grid keeps resource, worker and interface symbols visually
// consistent at small sizes. Icons are decorative unless a label is supplied.
const drawings = {
  castle: <><path d="M3 20h18M5 20v-7h14v7M8 13V8h8v5M10 8V4h4v4M6 8h12M3 13h18M8 4h8M10 20v-4h4v4" /><path d="m3 13 2-2m16 2-2-2M6 8l2-2m10 2-2-2" /></>,
  lantern: <><path d="M9 3h6M12 3V1.5M8 6h8l2 4v6l-2 3H8l-2-3v-6zM8 6V4.5h8V6M8 10h8M8 15h8M10 6v13m4-13v13M10 21h4M12 19v2" /></>,
  food: <><path d="M12 21V7M12 14c-4 0-7-3-7-7 4 0 7 3 7 7Zm0 4c4 0 7-3 7-7-4 0-7 3-7 7ZM12 9c-3-3-3-5 0-7 3 2 3 4 0 7Z" /></>,
  iron: <><path d="m7 5 10 1 4 7-5 7-10-1-3-7zM7 5l2 8 7 7M9 13l12 .1M9 13l8-7M3 12l6 1" /></>,
  pearl: <><circle cx="12" cy="12" r="8.2" /><path d="M7 10a5.2 5.2 0 0 1 5-3M15.5 17a6 6 0 0 0 2-2" /></>,
  coins: <><circle cx="10" cy="10" r="6.5" /><path d="M14.5 5a7 7 0 1 1-9.4 9.4M8 8h4v4H8z" /></>,
  seals: <><path d="m12 2 3 2 3.5.5.5 3.5 2 3-2 3-.5 3.5-3.5.5-3 2-3-2-3.5-.5-.5-3.5-2-3 2-3 .5-3.5 3.5-.5z" /><path d="M9 8h6M12 8v7M9 12h6M10 16h4" /></>,
  points: <><path d="M4 9a11.3 11.3 0 0 1 16 0l-8 12zM12 21V6M12 21 8 7.1M12 21l4-13.9M4 9l8 7 8-7" /></>,
  influence: <><path d="M4 20h16M6 17h12M8 14h8M12 14V3m-4 4 4-4 4 4" /></>,
  courtiers: <><path d="M9 3h6v4H9zM9 7l-3 5 2 2-3 7h14l-3-7 2-2-3-5M9 10l3 3 3-3M12 13v8" /></>,
  warriors: <><path d="m7 2 1 4m9-4-1 4M5 12l2-6h10l2 6M4 12h16M8 12v4l4 5 4-5v-4M10 16h4M12 6v6" /></>,
  gardeners: <><path d="M4 10 12 3l8 7zM9 10v4a3 3 0 0 0 6 0v-4M7 21v-2a5 5 0 0 1 10 0v2M10 7h4" /></>,
  arrow: <><path d="M4 12h15m-6-6 6 6-6 6" /></>,
  undo: <><path d="M8 5 3 10l5 5M3 10h10a6 6 0 0 1 0 12" transform="translate(0 -2)" /></>,
  check: <path d="m5 12 4.5 4.5L19 7" />,
  close: <path d="m6 6 12 12M6 18 18 6" />,
  book: <><path d="M12 6c-3-2-6-2.5-9-1.5v14c3-1 6-.5 9 1.5 3-2 6-2.5 9-1.5v-14c-3-1-6-.5-9 1.5Zm0 0v14M6 8h2m-2 4h2m8-4h2m-2 4h2" /></>,
  moon: <path d="M19.7 14.8A8.5 8.5 0 0 1 9.2 4.3a8.5 8.5 0 1 0 10.5 10.5Z" />,
};

const iconAliases = { coin: "coins", seal: "seals", vp: "points", warrior: "warriors", garden: "gardeners", courtier: "courtiers", gardener: "gardeners", plant: "food", stone: "iron" };

export function Icon({ name, size = 20, title, ...props }) {
  const labelled = Boolean(title || props["aria-label"] || props["aria-labelledby"]);
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
    stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" strokeLinejoin="round"
    aria-hidden={labelled ? undefined : true} role={labelled ? "img" : undefined}
    aria-label={title || undefined} focusable="false" {...props}>
    {title && <title>{title}</title>}
    {drawings[iconAliases[name] || name] || <path d="m12 4 8 8-8 8-8-8z" />}
  </svg>;
}

const workerNames = { courtiers: "courtier", warriors: "warrior", gardeners: "gardener" };
const placeNames = {
  domain: "your domain", gate: "the castle gate", floor1: "the first floor",
  floor2: "the second floor", daimyo: "the Daimyo hall",
  // Card effects deploy to these reserves; they do not select a paid location.
  yard: "the training reserve", yard_pool: "the training reserve",
  garden: "the garden reserve", garden_pool: "the garden reserve",
};
const rewardNames = {
  coin: ["coin", "coins"], coins: ["coin", "coins"],
  seal: ["seal", "seals"], seals: ["seal", "seals"],
  vp: ["point", "points"], points: ["point", "points"],
  influence: ["influence", "influence"], food: ["food", "food"],
  iron: ["iron", "iron"], pearl: ["mother-of-pearl", "mother-of-pearl"],
};

const amountOf = (value, fallback = 0) => Number.isFinite(Number(value)) ? Number(value) : fallback;
const quantity = (icon, amount) => {
  const names = rewardNames[icon];
  return names ? `${amount} ${names[Math.abs(amount) === 1 ? 0 : 1]}` : "";
};
const join = (items) => items.length < 3 ? items.join(" and ") : `${items.slice(0, -1).join(", ")}, and ${items.at(-1)}`;

/** The printed reward, without predicting whether a resource cap allows it. */
export function rewardText(reward) {
  const icon = typeof reward === "string" ? reward : reward?.icon;
  const amount = typeof reward === "string" ? 1 : amountOf(reward?.amount, 1);
  return quantity(icon, amount) || "No recurring reward";
}

/** Describe the authoritative effect vocabulary; never infer game outcomes. */
export function effectText(effect) {
  if (!effect || typeof effect !== "object") return "";
  const op = effect.op;
  if (op === "gain") {
    const rewards = ["coins", "seals", "points", "influence"]
      .filter((key) => amountOf(effect[key]) !== 0)
      .map((key) => quantity(key, amountOf(effect[key])));
    if (effect.resource && rewardNames[effect.resource]) {
      rewards.push(quantity(effect.resource, amountOf(effect.amount, 1)));
    }
    return rewards.length ? `Gain ${join(rewards)}` : "";
  }
  if (["coins", "seals", "points", "influence"].includes(op)) {
    return `Gain ${quantity(op, amountOf(effect.amount))}`;
  }
  if (op === "lantern") {
    return `Add ${rewardText({ icon: effect.icon || "coin", amount: amountOf(effect.amount, 1) })} to your lantern rewards`;
  }
  if (op === "well_bonus") return "Reveal up to 2 remaining well tiles and receive their benefits";
  if (op === "move") {
    const worker = workerNames[effect.worker];
    const destination = effect.to || effect.destination;
    const place = placeNames[destination];
    if (!worker || !place) return "";
    if (effect.worker === "courtiers" && effect.from !== "domain") {
      return `Advance 1 courtier to ${place}`;
    }
    return `Move 1 ${worker} from your domain to ${place}`;
  }
  if (op === "pay_seal_for_worker") {
    const worker = effect.worker || "courtiers";
    const destination = worker === "courtiers" ? "gate" : worker === "warriors" ? "yard_pool" : "garden_pool";
    return workerNames[worker] ? `Pay 1 seal to move 1 ${workerNames[worker]} from your domain to ${placeNames[destination]}` : "";
  }
  return "";
}

export function effectItems(effects) {
  return Array.isArray(effects) ? effects.map(effectText).filter(Boolean) : [];
}
