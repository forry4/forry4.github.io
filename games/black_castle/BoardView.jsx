import { useEffect, useRef, useState } from "react";
import { LobbyHeader, GameMenu, RulesModal } from "../../shared/lobby.jsx";
import { GAME_ACCENTS } from "../../shared/accents.js";
import { Icon, effectItems, rewardText } from "./presentation.jsx";

const COLORS = ["coral", "black", "white"];
const CASTLE_ROOM_DICE = 2;
// Two dice fit on a castle room or an Outside the Walls space -- unless the table is a
// duel, where dice are never stacked anywhere.
const dicePerSpace = game => (Object.keys(game.players || {}).length <= 2 ? 1 : CASTLE_ROOM_DICE);
// Outside the Walls used to hold a single {pid, die}; it holds a list now, and a game
// saved before that carries the lone object.
const outsideDice = (game, i) => { const row = game.outside?.[String(i)]; return !row ? [] : Array.isArray(row) ? row : [row]; };
const COLOR_NAMES = { coral: "Coral", black: "Obsidian", white: "Ivory", gold: "Gold" };
const WORKERS = { courtiers: "Courtiers", warriors: "Warriors", gardeners: "Gardeners" };
const RESOURCE_NAMES = { food: "Rice", iron: "Iron", pearl: "Pearl" };
const FLOORS = { gate: "Castle gate", floor1: "First floor", floor2: "Second floor", daimyo: "Daimyo hall" };
const DOMAIN_RESOURCE = { coral: "food", black: "iron", white: "pearl" };
const PIPS = { 1: [4], 2: [0, 8], 3: [0, 4, 8], 4: [0, 2, 6, 8], 5: [0, 2, 4, 6, 8], 6: [0, 2, 3, 5, 6, 8] };

export function Die({ die, onClick, disabled = true, label }) {
  if (!die) return null;
  const contents = <span className="bc-pips" aria-hidden="true">{Array.from({ length: 9 }, (_, i) => <i key={i} className={PIPS[die.value]?.includes(i) ? "on" : ""} />)}</span>;
  const props = { className: `bc-die bc-die-${die.color}`, title: label || `${COLOR_NAMES[die.color]} die, ${die.value}`, "aria-label": label || `${COLOR_NAMES[die.color]} die, ${die.value}` };
  return onClick ? <button type="button" {...props} disabled={disabled} onClick={onClick}>{contents}</button> : <span {...props} role="img">{contents}</span>;
}

function Effects({ effects, className = "" }) {
  const items = effectItems(effects || []);
  return <ul className={`bc-effects ${className}`}>{items.map((item, i) => <li key={i}>{typeof item === "string" ? item : item.text}</li>)}</ul>;
}

function Stat({ name, value, cap }) {
  return <span className={`bc-stat bc-stat-${name}`} title={cap ? `${name}: maximum ${cap}` : name}><Icon name={name} /><b>{value || 0}</b><span>{name}</span>{cap && <small>/{cap}</small>}</span>;
}

function SectionHead({ icon, title, note, children }) {
  return <header className="bc-section-label"><div><Icon name={icon} /><h2>{title}</h2>{note && <span>{note}</span>}</div>{children}</header>;
}

function CardFace({ card, activeSide, onlyLight = false }) {
  if (!card) return <div className="bc-card bc-card-empty">Choose a starting pair to receive an action card.</div>;
  return <div className="bc-card"><div className="bc-card-heading"><strong>{card.name}</strong>{card.level > 0 && <Icon name={card.level === 3 ? "points" : "castle"} />}</div>
    <div className={`bc-card-action${activeSide === "light" ? " selected" : ""}${activeSide === "dark" ? " inactive" : ""}`}><span className="bc-card-side">Light</span><Effects effects={card.light} /></div>
    {!onlyLight && card.dark?.length > 0 && <div className={`bc-card-action dark${activeSide === "dark" ? " selected" : ""}${activeSide === "light" ? " inactive" : ""}`}><span className="bc-card-side">Dark</span><Effects effects={card.dark} /></div>}
  </div>;
}

function PlayerPanel({ pid, player, name, active, mine, onInspect, game }) {
  return <button className={`bc-player${active ? " active" : ""}${mine ? " mine" : ""}`} onClick={onInspect} aria-label={`Inspect ${name}${mine ? ", your clan" : "'s clan"}`}>
    <div className="bc-player-head"><span className={`bc-clan-mon bc-${player.color}`}><Icon name="castle" /></span><strong>{name}<small>{mine ? "Your clan" : "Opponent"}{active ? " · Playing" : ""}</small></strong><span className="bc-score"><b>{game.phase === "over" && Number.isFinite(game.scores?.[pid]) ? game.scores[pid] : player.points || 0}</b><small>points</small></span></div>
    <div className="bc-player-resources">{["coins", "seals"].map(name => <Stat key={name} name={name} value={player[name]} />)}{["food", "iron", "pearl"].map(name => <Stat key={name} name={name} value={player.resources?.[name]} />)}</div>
    <div className="bc-player-foot"><span><Icon name="influence" />{player.influence || 0} influence</span><span>View clan <Icon name="arrow" /></span></div>
  </button>;
}

// Each bridge carries TWO garden plots with separate gardeners. Older saved games wrote
// one flat list per bridge, back when a bridge was a single place to stand, so that shape
// is read as the Plant plot's -- the only card those games could reach.
function gardenOccupants(garden, kind) {
  const seats = garden?.occupants;
  if (seats && !Array.isArray(seats)) return seats[kind] || [];
  return kind === "plant" ? seats || [] : [];
}

function gardenCard(game, move) {
  return move.worker === "warriors" ? game.yards[move.index] : game.gardens[move.index][move.kind || "plant"];
}

function Occupants({ pids, names, players, empty = "Unoccupied" }) {
  if (!pids.length) return <span className="bc-empty-occupants">{empty}</span>;
  return <span className="bc-occupants">{pids.map((pid, i) => <span key={`${pid}-${i}`} className={`bc-occupant bc-${players[pid]?.color}`} title={names[pid] || pid}><Icon name="courtiers" /><span>{names[pid] || pid}</span></span>)}</span>;
}

function placementInfo(game, space) {
  const [area, index] = space.split(":");
  if (area === "castle") {
    const room = game.castle.rooms.find(r => String(r.id) === index);
    const side = game.pending?.die ? (Number(game.pending.die.value) + Number(room.id)) % 2 === 0 ? "light" : "dark" : null;
    return { title: room.card.name, target: room.floor === 1 ? 3 : 4, subtitle: `${room.floor === 1 ? "First" : "Second"} floor${side ? ` · ${side} action` : ""}`, effects: room.card[side], side };
  }
  if (area === "domain") return { title: `${COLOR_NAMES[index]} domain`, target: 6, subtitle: "Your personal domain", effects: [{ op: "gain", resource: DOMAIN_RESOURCE[index], amount: 1 }, ...(game.players[game.viewer]?.action_card?.light || [])] };
  if (area === "outside") return { title: "Outside the walls", target: 5, subtitle: `Gate ${Number(index) + 1}`, description: "Choose a worker action next. Deployment costs are paid separately." };
  return { title: "The well", target: 1, subtitle: "Always available", description: "Gain 1 Daimyo Seal plus the rewards on the well's two tiles. They are face up from setup and pay the same on every visit." };
}

function Price({ die, target }) {
  const delta = Number(die.value) - target;
  return <span className={`bc-price ${delta > 0 ? "gain" : delta < 0 ? "cost" : "even"}`}><Icon name="coins" />{delta > 0 ? `Gain ${delta}` : delta < 0 ? `Pay ${-delta}` : "No cost"}{delta !== 0 && <small>{Math.abs(delta) === 1 ? "coin" : "coins"}</small>}</span>;
}

function Target({ game, space, onSelect, selected, children, className = "", busy }) {
  const choosing = game.pending?.kind === "place_die" && game.pending?.pid === game.viewer;
  const legal = game.legal_moves?.some(m => m.type === "place_die" && m.space === space);
  const info = placementInfo(game, space);
  const domain = space.startsWith("domain") && game.players[game.viewer]?.domain?.[space.split(":")[1]];
  const occupied = domain ? domain.die || domain.uses : space.startsWith("outside") ? outsideDice(game, space.split(":")[1]).length >= dicePerSpace(game) : space.startsWith("castle") ? game.castle.rooms.find(r => String(r.id) === space.split(":")[1])?.dice?.length >= dicePerSpace(game) : false;
  const reason = occupied ? (domain ? "Used this turn" : "Occupied") : "Not enough coins";
  return <button type="button" className={`bc-target ${className}${legal ? " available" : ""}${selected === space ? " picked" : ""}`} disabled={!legal || busy} onClick={() => onSelect(space)} aria-label={`${info.title}, ${info.subtitle}${choosing ? `, ${legal ? "review placement" : reason}` : ""}`} aria-pressed={selected === space} data-space={space}>
    {children}<span className="bc-target-footer"><span className="bc-value">{info.target}<small>base</small></span>{choosing && game.pending.die ? <><Price die={game.pending.die} target={info.target} /><span className="bc-target-cta">{legal ? (selected === space ? "Selected" : "Choose") : reason}</span></> : <span>{info.subtitle}</span>}</span>
  </button>;
}

function Bridges({ game, sendMove, busy }) {
  const canTake = (color, side) => game.legal_moves?.some(m => m.type === "take_die" && m.bridge === color && m.side === side);
  return <section className="bc-bridges bc-panel" id="bc-bridges"><SectionHead icon="lantern" title="The three bridges" note="Choose an end die" /><div className="bc-bridge-grid">
    {COLORS.map(color => { const dice = game.bridges?.[color] || []; return <div className={`bc-bridge bc-bridge-${color}`} key={color}><div className="bc-bridge-title"><i /><h3>{COLOR_NAMES[color]}</h3><small>{dice.length} remaining</small></div>
      <div className="bc-bridge-dice">{dice.length ? dice.map((die, i) => <Die key={die.id || i} die={die} onClick={() => sendMove({ type: "take_die", bridge: color, side: i === 0 ? "left" : "right" })} disabled={busy || !(i === 0 ? canTake(color, "left") : i === dice.length - 1 && canTake(color, "right"))} label={`${COLOR_NAMES[color]} ${die.value}${i === 0 ? ", low die, activates lantern" : i === dice.length - 1 ? ", high die" : ", not at a bridge end"}`} />) : <span className="bc-bridge-empty">Bridge cleared</span>}</div>
      <div className="bc-bridge-ends"><button disabled={busy || !canTake(color, "left")} onClick={() => sendMove({ type: "take_die", bridge: color, side: "left" })}><Icon name="lantern" /><span>Low die<small>+ lantern</small></span></button><button disabled={busy || !canTake(color, "right")} onClick={() => sendMove({ type: "take_die", bridge: color, side: "right" })}><span>High die<small>no lantern</small></span><Icon name="arrow" /></button></div>
    </div>; })}
  </div></section>;
}

function CourtierRow({ game, names, location }) {
  const pids = Object.entries(game.players).flatMap(([pid, p]) => Array(p.workers?.courtiers?.[location] || 0).fill(pid));
  return <div className="bc-courtier-row"><span><Icon name="courtiers" />{FLOORS[location]}</span><Occupants pids={pids} names={names} players={game.players} /></div>;
}

function Castle({ game, names, onSelect, selected, busy }) {
  return <section className="bc-castle bc-panel" id="bc-castle"><SectionHead icon="castle" title="The keep" note="Place a die to activate a room" />
    <div className="bc-daimyo"><div><span className="bc-kicker">DAIMYO HALL</span><h3>{game.castle?.daimyo?.name}</h3><p>Courtiers here score 10 points each.</p></div><Icon name="castle" /><CourtierRow game={game} names={names} location="daimyo" /></div>
    {[2, 1].map(floor => <div className={`bc-floor bc-floor-${floor}`} key={floor}><div className="bc-floor-label"><span>{floor === 2 ? "02" : "01"}</span><h3>{floor === 2 ? "Second" : "First"} floor</h3><small>{floor === 2 ? "6" : "3"} points per courtier</small></div><div className="bc-rooms">
      {game.castle?.rooms?.filter(room => room.floor === floor).map(room => <Target key={room.id} {...{ game, onSelect, selected, busy }} space={`castle:${room.id}`} className="bc-room"><CardFace card={room.card} activeSide={game.pending?.die ? (Number(game.pending.die.value) + Number(room.id)) % 2 === 0 ? "light" : "dark" : null} /><div className="bc-room-occupancy">{room.dice?.length ? room.dice.map((die, i) => <Die key={i} die={die} />) : <span>Open room</span>}<small>{room.dice?.length || 0}/{dicePerSpace(game)} dice</small></div></Target>)}
    </div><CourtierRow game={game} names={names} location={`floor${floor}`} /></div>)}
    <CourtierRow game={game} names={names} location="gate" />
  </section>;
}

function Grounds({ game, names, onSelect, selected, busy, sendMove }) {
  const workerMove = (worker, index, kind) => game.legal_moves?.find(m => m.type === "worker_destination" && m.worker === worker && m.index === index && (kind === undefined || m.kind === kind));
  return <>
    <section className="bc-gates bc-panel" id="bc-grounds"><SectionHead icon="courtiers" title="Beyond the keep" note="Deploy a worker, or draw on the well" /><div className="bc-gate-grid">
      {[0, 1].map(i => <Target key={i} {...{ game, onSelect, selected, busy }} space={`outside:${i}`} className="bc-outside"><Icon name="courtiers" /><h3>Outside the walls</h3><p>{i === 0 ? "Plant a gardener, or send a courtier to the castle." : "Train a warrior, or send a courtier to the castle."}</p><div className="bc-space-occupancy">{outsideDice(game, i).length ? outsideDice(game, i).map((slot, k) => <span key={k} className="bc-outside-slot"><Die die={slot.die} /><span>{names[slot.pid]}</span></span>) : <span>Gate {i + 1} · Open</span>}<small>{outsideDice(game, i).length}/{dicePerSpace(game)} dice</small></div></Target>)}
      <Target {...{ game, onSelect, selected, busy }} space="well" className="bc-well"><Icon name="moon" /><h3>The well</h3><p>1 seal + the rewards on its two tiles.<br />Face up, and the same on every visit.</p><div className="bc-space-occupancy"><span>Unlimited visits</span></div></Target>
    </div></section>
    <section className="bc-gardens bc-panel" id="bc-gardens"><SectionHead icon="gardeners" title="The gardens" note="Food to plant · Points at game end" /><div className="bc-garden-grid">{(game.gardens || []).flatMap((garden, i) => ["plant", "stone"].map(kind => { const card = garden[kind]; if (!card) return null; const move = workerMove("gardeners", i, kind); return <button key={`${garden.id}-${kind}`} className={`bc-garden bc-worker-target${move ? " available" : ""}`} disabled={!move || busy} onClick={() => sendMove(move)}><div className="bc-garden-art"><Icon name="gardeners" /><span className={`bc-color-label bc-${garden.bridge}`}>{COLOR_NAMES[garden.bridge]} bridge</span></div><h3>{card.name}</h3><div className="bc-worker-cost"><span><Icon name="food" />{card.cost} food</span><b>{card.vp} points</b></div><Effects effects={card.light} /><p className="bc-card-note">On placement; repeats after rounds 1–2 if this bridge has dice.</p><Occupants pids={gardenOccupants(garden, kind)} names={names} players={game.players} />{move && <span className="bc-worker-cta">Plant a gardener <Icon name="arrow" /></span>}</button>; }))}</div></section>
    <section className="bc-yards bc-panel" id="bc-yards"><SectionHead icon="warriors" title="Training yards" note="Iron to train · Score with your courtiers" /><div className="bc-yard-grid">{(game.yards || []).map((yard, i) => { const move = workerMove("warriors", i); const pids = Object.entries(game.players).flatMap(([pid, p]) => (p.yards || []).filter(y => y.id === yard.id).map(() => pid)); return <button key={yard.id} className={`bc-yard bc-worker-target${move ? " available" : ""}`} disabled={!move || busy} onClick={() => sendMove(move)}><Icon name="warriors" /><h3>{yard.name}</h3><div className="bc-worker-cost"><span><Icon name="iron" />{yard.cost} iron</span><b>{yard.vp} ×</b></div><p className="bc-card-note">Points per courtier inside the castle.</p><Effects effects={yard.effect} /><Occupants pids={pids} names={names} players={game.players} empty="No warriors" />{move && <span className="bc-worker-cta">Train a warrior <Icon name="arrow" /></span>}</button>; })}</div></section>
  </>;
}

function Domain({ game, pid, names, onSelect, selected, busy, inspect = false }) {
  const player = game.players[pid];
  if (!player) return null;
  return <section className="bc-domain-board bc-panel" id={inspect ? undefined : "bc-domain"}><SectionHead icon="castle" title={inspect ? `${names[pid]}'s domain` : "Your domain"} note="Personal actions" />
    <CardFace card={player.action_card} onlyLight />
    <div className="bc-domain-row">{COLORS.map(color => inspect ? <div className="bc-domain-inspect" key={color}><span>{COLOR_NAMES[color]}</span><span>+1 {DOMAIN_RESOURCE[color]}</span>{player.domain?.[color]?.die && <Die die={player.domain[color].die} />}</div> : <Target key={color} {...{ game, onSelect, selected, busy }} space={`domain:${color}`} className={`bc-domain-slot bc-${color}`}><div><span className="bc-domain-dot" /><strong>{COLOR_NAMES[color]}</strong><span>+1 {DOMAIN_RESOURCE[color]}</span>{player.domain?.[color]?.die && <Die die={player.domain[color].die} />}</div><p>Also activate your card above.</p></Target>)}</div>
    <div className="bc-lantern"><h3><Icon name="lantern" />Lantern rewards</h3><p>Collect every reward when you place a low die.</p><div>{player.lantern?.length ? player.lantern.map((reward, i) => <span key={i}>{rewardText(reward)}</span>) : <span>No rewards yet</span>}</div></div>
    <div className="bc-workers"><h3>Workers in your domain</h3>{Object.entries(WORKERS).map(([key, label]) => <div key={key}><Icon name={key} /><span>{label}</span><b>{player.workers?.[key]?.domain || 0}<small>/ 5</small></b></div>)}<p>Remaining workers available to deploy.</p></div>
    {inspect && <div className="bc-worker-positions"><h3>Deployed workers</h3>{Object.entries(WORKERS).map(([key, label]) => <p key={key}><strong>{label}</strong>{Object.entries(player.workers?.[key] || {}).filter(([place, count]) => place !== "domain" && count > 0).map(([place, count]) => `${count} ${FLOORS[place] || ({ yard_pool: "in training reserve", garden_pool: "in garden reserve", yard: "in training yards", garden: "in gardens" })[place]}`).join(" · ") || "None yet"}</p>)}</div>}
  </section>;
}

function moveLabel(move, game) {
  if (move.type === "outside_worker") return move.action === "audience" ? ["Request an audience", "Pay 2 coins · Move a courtier to the gate", "courtiers"] : move.action === "climb" ? ["Climb the castle", "Choose a floor and pay pearls", "courtiers"] : move.worker === "warriors" ? ["Train a warrior", "Choose a training yard · Pay iron", "warriors"] : ["Plant a gardener", "Choose a garden · Pay food", "gardeners"];
  if (move.type === "courtier_destination") return [FLOORS[move.to], `Pay ${move.cost} pearls`, "courtiers"];
  if (move.type === "worker_destination") { const card = gardenCard(game, move); return [card.name, `Pay ${card.cost} ${move.worker === "warriors" ? "iron" : "food"}`, move.worker]; }
  if (move.type === "convert") return [move.from === "seals" ? `2 seals → 1 ${move.to}` : move.from === "seal" ? "1 seal → 1 coin" : `2 ${move.from} → 1 coin`, "", "seals"];
  // A card that grants "a resource" without naming one. Without this case the three
  // picks fall through to the default below and render as three "End Turn" buttons.
  if (move.type === "choose_resource") return [RESOURCE_NAMES[move.resource] || move.resource, "Take one of this resource", move.resource];
  return ["End Turn", "", "check"];
}

function DecisionPanel({ game, names, myId, sendMove, selected, onSelect, busy, connected }) {
  const moves = game.legal_moves || [];
  const acting = moves.length > 0;
  const kind = game.pending?.kind;
  const taking = moves.some(m => m.type === "take_die");
  const placing = acting && kind === "place_die";
  const ending = moves.some(m => m.type === "end_turn");
  const nextName = names[game.turn_pid] || "The next clan";
  const step = placing ? 2 : taking ? 1 : 3;
  const title = !connected ? "Reconnecting to the table" : !acting ? `${nextName} is playing` : taking ? "Choose your die" : placing ? "Choose a destination" : ending ? "Your action is complete" : kind === "choose_resource" ? "Choose a resource" : kind === "outside_worker" ? "Deploy a worker" : kind === "courtier_destination" ? "Choose a floor" : "Choose a worker destination";
  const selectedMove = selected && moves.find(m => m.type === "place_die" && m.space === selected);
  const info = selectedMove ? placementInfo(game, selected) : null;
  const choices = moves.filter(m => !["take_die", "place_die", "convert", "end_turn"].includes(m.type));
  const trades = moves.filter(m => m.type === "convert");
  return <section className="bc-decision bc-panel" id="bc-decision" aria-labelledby="bc-decision-title"><div className="bc-turn-label"><span className={acting ? "lit" : ""} />{acting ? "YOUR TURN" : "AT THE TABLE"}{busy && <small>Sending…</small>}</div>
    <div className="bc-stepper" aria-label={`Turn step ${step} of 3`}>{["Take", "Place", "Resolve"].map((s, i) => <span className={acting && step === i + 1 ? "current" : step > i + 1 ? "done" : ""} key={s}><b>{step > i + 1 ? <Icon name="check" /> : i + 1}</b>{s}</span>)}</div>
    <h2 id="bc-decision-title" aria-live="polite">{title}</h2>
    {!acting && <p>You can explore the board and inspect every clan while you wait.</p>}
    {taking && <p>Take either end of a bridge. The low die also activates your lantern rewards.</p>}
    {placing && <><div className="bc-held-die"><Die die={game.pending.die} /><div><strong>{COLOR_NAMES[game.pending.die.color]} · {game.pending.die.value}</strong><span>{game.pending.side === "left" ? "Low die · Lantern will activate" : "High die · No lantern reward"}</span></div></div><p>Choose a gold-outlined space on the board, then confirm here.</p></>}
    {info && <div className="bc-placement-preview" tabIndex={-1}><span className="bc-kicker">PLACEMENT PREVIEW</span><h3>{info.title}</h3><p>{info.subtitle}</p><Price die={game.pending.die} target={info.target} />{info.effects && <Effects effects={info.effects} />}{info.description && <p>{info.description}</p>}{game.pending.side === "left" && <p className="bc-preview-lantern"><Icon name="lantern" />Plus all your lantern rewards.</p>}<button className="bc-primary bc-confirm" disabled={busy || !connected} onClick={() => sendMove(selectedMove)}>{selected === "well" ? "Place & reveal rewards" : "Place die"}<Icon name="arrow" /></button><button className="bc-text-button" onClick={() => onSelect(null)}>Choose another space</button></div>}
    {placing && <details className="bc-destination-list"><summary>All available destinations <span>{moves.length}</span></summary><div className="bc-choice-grid">{moves.filter(m => m.type === "place_die").map(m => { const choice = placementInfo(game, m.space); return <button key={m.space} onClick={() => onSelect(m.space)} disabled={busy}><strong>{choice.title}{m.space.startsWith("outside") ? ` · ${choice.subtitle}` : ""}</strong><Price die={game.pending.die} target={choice.target} /></button>; })}</div></details>}
    {choices.length > 0 && <div className="bc-choice-grid">{choices.map((move, i) => { const [label, note, icon] = moveLabel(move, game); return <button type="button" key={i} disabled={busy || !connected} onClick={() => sendMove(move)}><Icon name={icon} /><span><strong>{label}</strong><small>{note}</small>{move.type === "worker_destination" && (() => { const card = gardenCard(game, move); return <><Effects effects={card.effect || card.light} /><small className="bc-choice-reward">{card.vp}{move.worker === "warriors" ? " points × each of your courtiers inside the castle" : " points at game end"}</small></>; })()}</span><Icon name="arrow" /></button>; })}</div>}
    {ending && <><p>Finish your turn, or make an optional trade below.</p><button className="bc-primary bc-end-turn" disabled={busy || !connected} onClick={() => sendMove(moves.find(m => m.type === "end_turn"))}>End Turn <Icon name="arrow" /></button></>}
    {trades.length > 0 && <details className="bc-trades"><summary>Trade resources <span>Optional</span></summary><div className="bc-trade-grid">{trades.map((m, i) => <button key={i} disabled={busy || !connected} onClick={() => sendMove(m)}>{moveLabel(m, game)[0]}</button>)}</div></details>}
    {game.can_undo && <button className="bc-undo" disabled={busy || !connected} onClick={() => sendMove({ type: "undo" })}><Icon name="undo" />Undo this turn</button>}
  </section>;
}

function ResourceChoice({ moves, sendMove, busy, connected }) {
  return <div className="bc-resource-choice"><span className="bc-kicker">YOUR CARD GRANTS A RESOURCE</span>
    <h3>Choose one.</h3>
    <div className="bc-choice-grid">{moves.map((move, i) => <button type="button" key={i} disabled={busy || !connected} onClick={() => sendMove(move)}><Icon name={move.resource} /><span><strong>{RESOURCE_NAMES[move.resource] || move.resource}</strong><small>Take one</small></span><Icon name="arrow" /></button>)}</div>
  </div>;
}

function Draft({ game, names, sendMove, busy, connected }) {
  const available = game.legal_moves || [];
  const active = available.some(m => m.type === "draft");
  // A drafted card can stop the draft to ask for a resource. The draft is held open for
  // that pick, so it has to be answerable from this screen -- the decision panel is not
  // mounted during the draft phase.
  const picks = available.filter(m => m.type === "choose_resource");
  const [selection, setSelection] = useState(null);
  useEffect(() => setSelection(null), [game.draft_options]);
  const chosen = game.draft_options?.find(o => o.resource.id === selection);
  if (picks.length) return <section className="bc-draft"><ResourceChoice moves={picks} {...{ sendMove, busy, connected }} /></section>;
  return <section className="bc-draft"><div className="bc-draft-intro"><span className="bc-kicker">THE OPENING DRAFT</span><h2>{active ? "Every great clan begins with a choice." : `${names[game.draft_queue?.[0]] || "Another clan"} is choosing.`}</h2><p>Choose a pair. Take its starting resources now, keep the action card for your domain, and add the lantern reward.</p></div>
    <div className="bc-draft-grid">{(game.draft_options || []).map((option, i) => <button type="button" key={option.resource.id} className={`bc-draft-pair${selection === option.resource.id ? " selected" : ""}`} disabled={!active || busy || !connected} onClick={() => setSelection(option.resource.id)} aria-pressed={selection === option.resource.id}><span className="bc-draft-number">PAIR {String(i + 1).padStart(2, "0")}<Icon name={selection === option.resource.id ? "check" : "castle"} /></span><div className="bc-draft-resource"><span className="bc-kicker">START WITH</span><h3>{option.resource.name}</h3><Effects effects={option.resource.light} /></div><div className="bc-draft-action"><span className="bc-kicker">YOUR DOMAIN ACTION</span><h3>{option.action.name}</h3><Effects effects={option.action.light} /></div><div className="bc-draft-lantern"><Icon name="lantern" /><span>Lantern<small>{rewardText({ icon: ["food", "iron", "pearl", "coin", "seal", "influence", "vp"].includes(option.resource.back) ? option.resource.back : "coin", amount: 1 })}</small></span></div><span className="bc-draft-select">{selection === option.resource.id ? "Selected" : active ? "Select pair" : "Waiting for your turn"}<Icon name="arrow" /></span></button>)}</div>
    <div className="bc-draft-confirm"><span>{chosen ? `${chosen.resource.name} + ${chosen.action.name}` : active ? "Select a pair to see your choice here." : "The remaining pairs will be yours to choose from."}</span><button className="bc-primary" disabled={!chosen || !active || busy || !connected} onClick={() => sendMove({ type: "draft", index: game.draft_options.findIndex(o => o.resource.id === selection) })}>Begin with this pair <Icon name="arrow" /></button></div>
  </section>;
}

function Influence({ game, names }) {
  return <section className="bc-influence bc-panel"><SectionHead icon="influence" title="Passage of time" note="Influence decides next round’s order" /><div className="bc-influence-list">{(game.turn_order || []).map((pid, i) => <div key={pid}><span className={`bc-order bc-${game.players[pid]?.color}`}>{i + 1}</span><strong>{names[pid]}</strong><div className="bc-influence-track" aria-hidden="true"><i style={{ width: `${100 * (game.players[pid]?.influence || 0) / 15}%` }} />{[6, 10, 11].map(gate => <span key={gate} style={{ left: `${gate / 15 * 100}%` }} />)}</div><b>{game.players[pid]?.influence || 0}<small>/15</small></b></div>)}</div><p>Crossing 6 / 10 / 11 costs 1 / 2 / 3 seals respectively.</p></section>;
}

function Results({ game, names, onExit }) {
  const scored = Object.keys(game.scores || {}).length > 0;
  const ranked = [...game.turn_order].sort((a, b) => (game.scores?.[b] || 0) - (game.scores?.[a] || 0));
  return <section className="bc-result"><Icon name="points" /><span className="bc-kicker">{scored ? "THE FINAL BELL" : "TABLE CLOSED"}</span><h2>{scored ? `${names[game.winner]} wins the castle.` : "This game ended early."}</h2><p>{scored ? "Three rounds. Nine turns. A legacy written in lantern light." : "A player left the castle before final scoring."}</p>{scored && <ol>{ranked.map((pid, i) => <li key={pid}><span><small>{i + 1}.</small> {names[pid]}</span><b>{game.scores[pid]}<small> points</small></b></li>)}</ol>}<button className="bc-primary" onClick={onExit}>Return to lobby <Icon name="arrow" /></button></section>;
}

export default function BoardView({ roomData, myId, sendMove, onExit, onRules, onAbandon, connected, styles }) {
  const game = roomData.game;
  const names = roomData.players || {};
  const [selected, setSelected] = useState(null);
  const [inspect, setInspect] = useState(null);
  const [busy, setBusy] = useState(false);
  const inFlight = useRef(false);
  const turn = game.turn_pid === myId;
  useEffect(() => { setSelected(null); setBusy(false); inFlight.current = false; }, [roomData]);
  useEffect(() => { if (!busy) return; const timer = setTimeout(() => { setBusy(false); inFlight.current = false; }, 3000); return () => clearTimeout(timer); }, [busy]);
  const act = move => { if (inFlight.current || !connected) return; inFlight.current = true; setBusy(true); sendMove(move); };
  const choose = space => { setSelected(space); if (space) requestAnimationFrame(() => { const el = document.querySelector(".bc-placement-preview"); el?.focus({ preventScroll: true }); el?.scrollIntoView({ behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "instant" : "smooth", block: "nearest" }); }); };
  const roundTurn = Math.min(3, Math.floor((game.turn_in_round || 0) / Object.keys(game.players).length) + 1);
  return <div className="app blackcastle bc-play" style={{ "--lby-accent": GAME_ACCENTS.blackcastle }}><style>{styles}</style>
    <LobbyHeader title="Black Castle" menu={<GameMenu onLeave={onExit} onRules={onRules} onAbandon={game.phase === "over" ? null : onAbandon} />} user={<span className={`bc-connection${connected ? "" : " lost"}`}><i />{connected ? "Live table" : "Reconnecting…"}</span>} />
    <main className="bc-game-shell"><header className="bc-game-hero"><div><span className="bc-kicker">HIMEJI · THE AGE OF THE CLANS</span><h1>The Black Castle<span>.</span></h1><p>{game.phase === "draft" ? "A quiet ambition. A lasting legacy." : game.phase === "over" ? (Object.keys(game.scores || {}).length ? "The final bell has sounded." : "This table has closed.") : `${turn ? "Your turn" : `${names[game.turn_pid] || "Opponent"}’s turn`} · Turn ${roundTurn} of 3 this round`}</p></div><div className="bc-round-mark"><span>{game.phase === "draft" ? "OPENING DRAFT" : "ROUND"}</span><div>{[1, 2, 3].map(n => <b key={n} className={n === game.round ? "current" : n < game.round ? "complete" : ""}>{n}</b>)}</div><small>{Object.keys(game.players).length} clans at the table</small></div></header>
      <div className="bc-players">{Object.entries(game.players).map(([pid, player]) => <PlayerPanel key={pid} {...{ pid, player, game }} name={names[pid] || pid} active={game.phase === "draft" ? game.draft_queue?.[0] === pid : game.turn_pid === pid} mine={pid === myId} onInspect={() => setInspect(pid)} />)}</div>
      <p className="bc-player-scroll-hint" aria-hidden="true">Swipe to see every clan <Icon name="arrow" /></p>
      {game.phase === "draft" ? <Draft {...{ game, names, busy, connected }} sendMove={act} /> : <>
        {game.phase === "over" && <Results {...{ game, names, onExit }} />}
        <div className={`bc-workspace${game.phase === "over" ? " finished" : ""}`}><aside className="bc-rail">{game.phase !== "over" && <DecisionPanel {...{ game, names, myId, selected, busy, connected }} sendMove={act} onSelect={choose} />}<Domain {...{ game, names, selected, busy }} pid={myId} onSelect={choose} /></aside>
          <div className="bc-board"><Bridges {...{ game, busy }} sendMove={act} /><nav className="bc-board-nav" aria-label="Board areas">{[["bc-castle", "Castle"], ["bc-grounds", "Gates & well"], ["bc-gardens", "Gardens"], ["bc-yards", "Training yards"], ["bc-domain", "Your domain"]].map(([id, label]) => <a key={id} href={`#${id}`}>{label}</a>)}</nav><Castle {...{ game, names, selected, busy }} onSelect={choose} /><Grounds {...{ game, names, selected, busy }} sendMove={act} onSelect={choose} /><Influence {...{ game, names }} /><details className="bc-log bc-panel" open><summary>Castle chronicle <span>{game.log?.length || 0} events</span></summary><div>{(game.log || []).slice(-20).reverse().map(entry => <p key={entry.seq}><b>{entry.turn ? `T${entry.turn}` : "•"}</b><span>{entry.message}</span></p>)}</div></details></div>
        </div>
      </>}
    </main>
    {game.phase === "play" && <button className="bc-mobile-turn" onClick={() => document.getElementById("bc-decision")?.scrollIntoView({ behavior: "smooth", block: "start" })}><span><i />{turn ? "Your turn" : `${names[game.turn_pid] || "Opponent"}’s turn`}</span><strong>{turn ? game.pending?.kind === "place_die" ? "Place your die" : game.pending?.kind === "end_turn" ? "Finish turn" : "View action" : "View table"} ↑</strong></button>}
    {inspect && <RulesModal icon={<Icon name="castle" />} title={`${names[inspect]}${inspect === myId ? " · Your clan" : " · Clan overview"}`} onClose={() => setInspect(null)}><div className="blackcastle bc-inspector"><div className="bc-inspector-stats">{["coins", "seals", "influence"].map(name => <Stat key={name} name={name} value={game.players[inspect][name]} cap={name === "seals" ? 5 : name === "influence" ? 15 : null} />)}{["food", "iron", "pearl"].map(name => <Stat key={name} name={name} value={game.players[inspect].resources?.[name]} cap={7} />)}</div><Domain {...{ game, names }} pid={inspect} inspect /></div></RulesModal>}
  </div>;
}
