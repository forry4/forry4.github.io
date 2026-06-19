"""WWSD ('What Would Steve Do') — a standalone service that runs Splendor variant S on a
position dumped from the mattle 'spendee' client, for a shareable bookmarklet.

Runs as its OWN Render service (process-isolated from the live game backend): `analyze.prepare()`
rewrites the shared `games.spender.ai.az.engine` deck globals to the friend's deck, which would
corrupt the main game's AI if they shared a process. Nothing here mutates engine state at import
time — only `prepare()` (called at service startup) does.
"""
