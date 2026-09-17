# The Black Castle

The Black Castle is the base-game digital port of The White Castle (2023).
`engine.py` is the authoritative, JSON-safe rules engine. `main.py` owns only
rooms, websocket authentication, persistence, and bot scheduling. The browser
never calculates outcomes.

The first release intentionally exposes one ruleset (`base`) and one opponent
tier (`easy`). Easy chooses uniformly from the legal move list. The room model
already supports two or three bot seats, so a single human can play a 3- or
4-seat table while expansion data can be added later without changing the
wire protocol.

Keep private ordered decks, RNG state, undo snapshots, and pending choices out
of `player_view` for every recipient. New fields in the room state need a
redaction test and a persistence round trip before shipping.

## BGA parity: the catalogue comes BEFORE the audit

`cards.py` is placeholder and says so in its own code — stewards, diplomats, daimyo,
gardens and yards are generated in loops keyed on `i % 3` / `i % 4` and named
"Diplomat 1".."Diplomat 12", with `data/base_game_manifest.json` recording
`"bga_parity": "planned after launch"`. Only the COUNTS are real (15/12/9/5/5/…).

**So do not point an audit at real games and read the output as a bug list.** Every card
would be flagged, and not one flag would be an engine defect — it would be the placeholders
being placeholders. The corpus's first job is to SUPPLY the catalogue, not to grade it.

That is possible because BGA ships each card's **definition** inside its notification
payloads, not just the fact that a card moved:

    card.id 10  type steward  back coin  typeArg 3
      actionBlocks[]  id "10-1"  type light|dark|blueCurtain|yellowCurtain
                      position [top|middle|bottom]  conditional and|or
        actionDescriptions[].description  "Pay ${iconPlaceholder2} ${qty} to perform …"
        …descriptionArgs  iconPlaceholder=coin  qty=1  numberOfResources=2
      lanternDescription + args
    gardens  foodCost, pointValue, type plant|rock       tiles  id, type, side, effects

`description` + `descriptionArgs` is already the (effect, operands) pair our `light`/`dark`
lists store as `{"op": …, "amount": …}`, so the port's own note — "a BGA fixture diff can
replace individual definitions without changing the engine contract" — is exactly right.

- **`tools/extract_bga_catalogue.py`** does the extraction. It finds card objects by SHAPE
  (an `id` plus `actionBlocks`/`lanternDescription`) rather than by field name, because the
  same definition arrives under `card`, `iconCard`, `topCard`, `mainCard`, `mainCards[]`,
  `gardenCards[]` and more — keying on the name of whichever field happened to hold it is
  a rename away from silently extracting nothing.
- **Its own check is that one id means one definition.** A definition is seen many times per
  game, so a walk that picked up the wrong objects would collide and report conflicts. One
  log yields 34 definitions over 211 sightings at 0 conflicts.
- **A tile's FACE is part of its identity, not a disagreement.** Matcha yard tiles are
  double-sided — front "Perform 1 yard-tile Action(s)", back "Gain chasen 3", and even a
  different `typeArg`. Keying without `side` reported that as a corrupted definition.
- **What the log does NOT give**: which card a player drew or holds. `actionCardGained` and
  `lanternCardGained` carry only a `playerId`, and `newMainBoardCardRevealed` is empty. So
  hands are hidden, exactly as in Orbit — the catalogue and the public board are readable,
  a full move-replay is not.
- **What it gives generously**: `diePlaced` names the die (id, colour, pip value) AND the
  exact action space (`action-space-main-board-steward-2`), and `warriorAssigned` /
  `courtierMovedUp` / `geishaAssigned` / `gardenerAssigned` / `passageOfTimeMoved` /
  `resourceGained` / `sealPaid` / `scoreUpdated` cover placement, worker movement and
  payment. That is the structural core of the game, and it is what the rules audit will run
  on once the catalogue is real.

The corpus is `$WHITECASTLE_CORPUS` (default `C:/Users/Forrest/WhiteCastle_corpus`), filled
by the `cob-mining` cron at ~10 games/day against a 1,516-table manifest spanning 2-, 3- and
4-player games. The seat spread is deliberate: the game deals 3/4/5 dice per colour at 2/3/4
players, so a 2-player-only corpus could never verify the setup.
