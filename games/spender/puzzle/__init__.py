"""Spender Puzzle mode — offline generation + (later) serving.

A puzzle is a serialized late-game position where the side to move (the "hero")
can FORCE a win within K of their own turns against the opponent, and the forcing
line is UNIQUE at every hero decision. The opponent is variant S (the deployed
strong AI). Because a scripted puzzle ends the instant the player deviates, the
opponent only ever needs to reply ALONG the canonical line — so its replies are
frozen into the puzzle file and the whole thing plays as a deterministic
walkthrough (no AI compute at serve time).

This package is offline + pure-Python. It reuses games/spender/ai/az/* (engine for
rules/state, vsearch for variant S, heuristic3 for the greedy "triviality" filter).
"""
