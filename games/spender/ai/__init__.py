"""Spender AI package: offline trainer, scripted opponent, and the learned
weight / value-model data files loaded by the server at startup.

The game server lives in ``games.spender.main``; everything here is the AI's
data and training tooling, kept separate so the rest of the package (server,
frontend) stays free of training-only concerns.
"""
