"""Castles of Crimson — a second game in the Forrest Games collection.

A faithful digital port of a dice-and-tile duchy-building euro game. The pure
rules engine (``engine``/``board``/``tiles``/``effects``) has no web dependency
and is unit-testable in isolation; ``main`` adds the FastAPI/WebSocket server
(mounted under ``/coc`` by ``games.spender.main``).
"""
