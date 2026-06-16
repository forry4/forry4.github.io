"""games.spender package — the Spender game (rules + WebSocket server + AI).

Its HTTP/WS routes are exposed as ``main.router``; the site's FastAPI app is
assembled in the top-level ``app`` module (the composition root). The deploy
entrypoint is ``games.spender.app:app`` — a shim re-exporting that app.
"""
