"""SecretNames — the two-player cooperative word game (Codenames: Duet).

The rules live in :mod:`engine`, which is the single source of truth for the
websocket server, the persistence layer and the tests. Nothing in this package
imports ``core`` except ``main`` (the room server) — the engine is pure.

THE ONE RULE TO KEEP IN MIND while reading anything here: a player's key card
describes what happens when THE OTHER PLAYER guesses. Every guess is therefore
resolved against ``keys[1 - guesser_seat]``, never against the guesser's own
side. That single inversion is what the whole game is made of, and getting it
backwards produces a game that plays perfectly and is a different game.
"""
