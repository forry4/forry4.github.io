/* THE GAME CATALOGUE — one entry per game, and the only place a game's NAME and
 * PLAYER RANGE are written down.
 *
 * It used to live inside `HomeScreen.jsx` as a private `GAMES` const, which was
 * correct while the menu was the only page that named a game. It is not any more:
 * every lobby now opens with an identity band carrying the same emblem, the same
 * name and the same player range as the card that was clicked to get there
 * (`LobbyHero` in shared/lobby.jsx). Passing those to seven lobbies by hand is the
 * shape of drift this repo has paid for repeatedly — two values that agree only by
 * habit, until something pushes on one of them. One entry, both ends.
 *
 * The COLOUR is still `shared/accents.js` and is merged in here rather than copied:
 * `screens.mjs` holds a game's rendered `--lby-accent` against its home card, and
 * that gate is only meaningful while there is one source.
 *
 * ORDER IS THE MENU ORDER AND IS APPEND-ONLY — `webapp/test/screens.mjs` clicks
 * `.home-game-card` by INDEX.
 */
import { GAME_ACCENTS } from "./accents.js";

export const GAME_CATALOG = [
	{ id: "spender", name: "Spender", status: "ready", screen: "spender", players: "1–4 players" },
	{ id: "coc", name: "Castles of Crimson", status: "ready", screen: "coc", players: "1–4 players" },
	{ id: "wherewolf", name: "Where Wolf", status: "ready", screen: "werewolf", players: "3–10 players" },
	{ id: "duel", name: "Spender Duel", status: "ready", screen: "duel", players: "1–2 players" },
	{ id: "dontminion", name: "Dontminion", status: "ready", screen: "dontminion", players: "1–4 players" },
	{ id: "dissonance", name: "Dissonance", status: "ready", screen: "dissonance", players: "1–2 players" },
	{ id: "ragtag", name: "Rag Tag", status: "ready", screen: "ragtag", players: "1–2 players" },
	{ id: "orbit", name: "Orbit", status: "ready", screen: "orbit", players: "1–2 players" },
	{ id: "blackcastle", name: "Black Castle", status: "ready", screen: "blackcastle", players: "2–4 players" },
].map((g) => ({ ...g, accent: GAME_ACCENTS[g.id] }));

// Keyed lookup, for the lobbies — a lobby knows its own id and nothing else.
export const GAME_INFO = Object.fromEntries(GAME_CATALOG.map((g) => [g.id, g]));
