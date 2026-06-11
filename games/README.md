Games directory: each game is a subpackage (e.g. `games/spender`).

Each game package should export a FastAPI `app` or a `register_routes(app)` function.
