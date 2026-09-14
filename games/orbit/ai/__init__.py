"""Orbit AI: two serving modules, and the offline campaign around them.

`serving.py` and `state.py` SERVE — `main.py` imports both and `bot.py` imports
both, so they run in prod and are on the Render deploy path. Everything else
here (search, neural guide, self-play, league, promotion) is offline campaign
code that the serving path never imports, and is deliberately excluded from
that deploy path so a training commit cannot restart the backend.

That split is not a convention to be maintained by hand: this package was
described as offline-only long after the Expert shipped, and the deploy filter
believed it, so the served policy could be changed without ever reaching the
server. `core/tests/test_deploy_filter_covers_serving.py` now derives the
serving set from what `app.py` actually imports and fails if the filter misses
any of it — so adding a serving import here is safe, but it will require the
deploy filter to be updated in the same commit.
"""
