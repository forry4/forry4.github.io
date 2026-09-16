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

