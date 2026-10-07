// WHAT A PUSH NEEDS CHECKED LOCALLY — the pre-push hook's targeted gate.
//
// The full local rehearsal (pytest + smoke + every screens block) is ~6.5 minutes on
// the dev box, so on 2026-09-04 the hook was cut to a bare `vite build`. Pages red runs
// went from 4.9% to ~11.5% in the weeks after (docs/deploy-reliability-log.md,
// 2026-10-07). This is the middle ground: the checks a change can plausibly break,
// which for a one-game change is seconds, while GitHub Actions still runs everything.
//
//   node test/affected.mjs <git range>...   prints PYTEST_ARGS=… / SCREENS_BLOCKS=… for the hook
//
// The map is held to the tree by `assertAffectedMap`, which screens.mjs calls on every
// run (so CI enforces it, not just whoever has the hook on): a block named here must
// exist, and every game directory with a frontend must have an entry — even an empty
// one — so a new game cannot join without someone deciding what guards it.

import { execFileSync } from "node:child_process";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");

// The kit-wide checks. A change to shared/ or the shell can break any lobby, and these
// are the blocks that walk every lobby's chrome rather than one game's board (~80s).
const SHELL = ["routeMounts", "shellNav", "lobbyChrome", "waitingRoomKit", "rulesModal",
	"phoneLobbyColumns", "formControlZoom", "updateNudgeLayout"];

// Per feature directory: its own screens blocks. `dissonanceBeat` is left out on purpose:
// it measures elapsed time by design and reads short on a busy dev box (397ms of 700 on
// 2026-10-07 with nothing else running), and a hook that cries wolf gets switched off.
// CI still runs it.
export const FEATURE_BLOCKS = {
	"games/black_castle": ["blackCastlePlay"],
	"games/castles_of_crimson": ["offlineCoc"],
	"games/dissonance": ["dissonanceScorecard", "dissonanceSkat", "dissonanceQuartet",
		"dissonanceHard", "offlineDissonance"],
	"games/dontminion": ["dmExpansionPicker", "dmCardFace", "dmAdventures", "dmEmpires",
		"dmRenaissance", "dmInfoModal"],
	"games/orbit": ["orbitPlay", "lobbyFinishSync"],
	"games/pinch": ["pinchPlay"],
	"games/rag_tag": ["ragtagFight"],
	"games/secretnames": ["secretNamesPlay"],
	// Spender.jsx is the site SHELL, so it gets the kit-wide set as well as its own.
	"games/spender": [...SHELL, "authScreen", "homeScreen", "spenderPlayTurn",
		"spenderWaitingRoom", "offlineSpender", "profilePage"],
	"games/spender_duel": ["offlineDuel"],
	"games/wherewolf": ["routeMounts"],   // no block of its own; this one mounts it
	"books": ["offlineRead"],
	"notes": ["notesEditor", "offlineRead"],
	"boxpuzzles": ["boxPuzzles", "boxDaily"],
	"bggfilter": ["formControlZoom", "offlineRead"],
	"shared": SHELL,
	"webapp": SHELL,
};

// A game's sheet restyling the kit's chrome is the drift that has broken every new
// game so far (CLAUDE.md, "A GAME THEMES ITS ROWS"), so any game change also walks it.
const GAME_EXTRA = ["lobbyChrome"];

// Static assets named for the game they serve.
const PUBLIC_TOKENS = [
	[/dissonance/, "games/dissonance"], [/coc/, "games/castles_of_crimson"],
	[/duel/, "games/spender_duel"], [/orbit/, "games/orbit"], [/spender/, "games/spender"],
	[/blackcastle/, "games/black_castle"], [/werewolf/, "games/wherewolf"],
	[/bgg-filter/, "bggfilter"], [/puzzles\.json/, "games/spender"],
];

// Python: core/ and shared/ tests read the whole tree as text (rosters derived from
// games/*, the JSX, the workflows), so they run for any change (~11s). A change to the
// platform every feature imports runs the full suite (~75s).
const ALWAYS_PYTEST = ["core/tests", "shared/tests"];
const FULL_PYTEST = [/^core\/.*\.py$/, /^app\.py$/, /^conftest\.py$/, /^pytest\.ini$/,
	/requirements.*\.txt$/];
const PY_DEPENDENTS = { "games/spender": ["wwsd/tests"] };   // wwsd imports the Spender engine

const featureOf = (file) => {
	const m = file.match(/^games\/([^/]+)\//);
	if (m) return `games/${m[1]}`;
	const top = file.split("/")[0];
	return FEATURE_BLOCKS[top] ? top : null;
};

const SCREENS_FILE = "webapp/test/screens.mjs";

const git = (...args) => execFileSync("git", args, { cwd: repoRoot, encoding: "utf8" });

export function declaredBlocks(source = readFileSync(path.join(repoRoot, SCREENS_FILE), "utf8")) {
	return [...source.matchAll(/^\tasync function (\w+)\(log\)/gm)].map((m) => m[1]);
}

// The blocks whose bodies a diff of screens.mjs touched: each changed line belongs to
// the nearest block declared above it in the NEW file.
function changedScreenBlocks(ranges) {
	const source = readFileSync(path.join(repoRoot, SCREENS_FILE), "utf8").split("\n");
	const starts = [];
	source.forEach((line, i) => {
		const m = line.match(/^\tasync function (\w+)\(log\)/);
		if (m) starts.push([i + 1, m[1]]);
	});
	const hit = new Set();
	for (const range of ranges) {
		const diff = git("diff", "-U0", range, "--", SCREENS_FILE);
		for (const m of diff.matchAll(/^@@ -\S+ \+(\d+)(?:,(\d+))? @@/gm)) {
			const first = Number(m[1]), count = m[2] === undefined ? 1 : Number(m[2]);
			for (let line = first; line < first + Math.max(count, 1); line++) {
				const owner = starts.filter(([start]) => start <= line).pop();
				if (owner) hit.add(owner[1]);
			}
		}
	}
	return [...hit];
}

export function plan(files, ranges = []) {
	const pytest = new Set(ALWAYS_PYTEST);
	const blocks = new Set();
	let fullPytest = false;
	for (const file of files) {
		if (file.endsWith(".md")) continue;
		if (FULL_PYTEST.some((re) => re.test(file))) fullPytest = true;
		if (file === SCREENS_FILE) { changedScreenBlocks(ranges).forEach((b) => blocks.add(b)); continue; }
		if (file === "webapp/test/font-profiles.mjs") { blocks.add("orbitPlay"); continue; }
		if (file.startsWith("webapp/test/")) continue;          // the gate's own helpers
		if (/^core\/.*\.py$|^app\.py$/.test(file)) { blocks.add("routeMounts"); continue; }
		let feature = featureOf(file);
		if (file.startsWith("webapp/public/")) {
			const hitToken = PUBLIC_TOKENS.find(([re]) => re.test(file));
			feature = hitToken ? hitToken[1] : null;
		}
		if (!feature) continue;
		const testsDir = feature === "webapp" ? null : `${feature}/tests`;
		if (testsDir && existsSync(path.join(repoRoot, testsDir))) pytest.add(testsDir);
		(PY_DEPENDENTS[feature] || []).forEach((t) => pytest.add(t));
		if (/\/tests\//.test(file)) continue;                    // Python tests never reach a page
		if (/\/ai\/offline\/|\/tools\//.test(file)) continue;     // research + tooling: never served
		FEATURE_BLOCKS[feature].forEach((b) => blocks.add(b));
		if (feature.startsWith("games/")) GAME_EXTRA.forEach((b) => blocks.add(b));
	}
	return { pytest: fullPytest ? [] : [...pytest], fullPytest, blocks: [...blocks] };
}

export function assertAffectedMap(declared = declaredBlocks()) {
	const known = new Set(declared);
	const named = new Set([...Object.values(FEATURE_BLOCKS).flat(), ...SHELL, ...GAME_EXTRA,
		"orbitPlay", "routeMounts"]);
	const missing = [...named].filter((b) => !known.has(b));
	const games = readdirSync(path.join(repoRoot, "games"), { withFileTypes: true })
		.filter((d) => d.isDirectory()
			&& readdirSync(path.join(repoRoot, "games", d.name)).some((f) => f.endsWith(".jsx")))
		.map((d) => `games/${d.name}`);
	const unmapped = games.filter((g) => !FEATURE_BLOCKS[g]);
	if (missing.length || unmapped.length) {
		throw new Error("webapp/test/affected.mjs is stale — "
			+ (missing.length ? `it names blocks screens.mjs no longer declares: ${missing.join(", ")}. ` : "")
			+ (unmapped.length ? `these games have no entry (an empty list is fine): ${unmapped.join(", ")}.` : ""));
	}
}

if (process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url)) {
	const ranges = process.argv.slice(2);
	assertAffectedMap();
	const files = [...new Set(ranges.flatMap((r) => git("diff", "--name-only", r).split("\n").filter(Boolean)))];
	const p = plan(files, ranges);
	console.log(`PYTEST_ARGS='${p.fullPytest ? "" : p.pytest.join(" ")}'`);
	console.log(`PYTEST_SCOPE='${p.fullPytest ? "full suite" : p.pytest.join(", ")}'`);
	console.log(`SCREENS_BLOCKS='${p.blocks.join(",")}'`);
}
