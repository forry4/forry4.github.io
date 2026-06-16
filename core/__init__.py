"""Neutral backend platform shared by every site feature (Spender, Castles of
Crimson, Books).

Owns the cross-cutting infrastructure that used to live inside
``games/spender/main.py`` — the database connection/wrapper (``core.db``) and the
user / session / admin auth layer (``core.auth``). Feature packages now depend on
``core`` instead of reaching into a game module, which removes the circular
imports those reach-ins required (Castles of Crimson previously imported the
helpers lazily from inside functions to dodge the cycle; Books had them injected).

``core`` depends on nothing in ``games`` or ``books`` — it is the bottom layer.
"""
