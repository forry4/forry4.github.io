"""Tiny in-memory sliding-window rate limiter.

Used to throttle the auth endpoints (login / register) so password brute-forcing
and account-spam are bounded. In-memory is sufficient: the site runs as a single
uvicorn process (see Procfile), and losing counters on restart is acceptable for
abuse-prevention (a restart doesn't help an attacker who needs thousands of tries).

`exceeded(key)` is a read-only check (purges expired hits first); `record(key)`
appends a timestamped hit. Callers decide what a "hit" is — e.g. login records
every attempt against the per-IP limiter but only FAILED attempts against the
per-username limiter, so legitimate multi-device logins are never locked out.
"""
import time
from collections import defaultdict, deque


class SlidingWindowLimiter:
    def __init__(self, max_hits: int, window_seconds: float):
        self.max_hits = max_hits
        self.window = window_seconds
        self._hits: dict[str, deque] = defaultdict(deque)

    def _purge(self, key: str, now: float) -> deque:
        dq = self._hits[key]
        cutoff = now - self.window
        while dq and dq[0] < cutoff:
            dq.popleft()
        if not dq:
            # Don't leak empty deques for one-off keys.
            self._hits.pop(key, None)
            return deque()
        return dq

    def exceeded(self, key: str, now: float | None = None) -> bool:
        """True if `key` has already reached the limit within the window."""
        now = time.time() if now is None else now
        return len(self._purge(key, now)) >= self.max_hits

    def record(self, key: str, now: float | None = None) -> None:
        """Record one hit for `key`."""
        now = time.time() if now is None else now
        self._hits[key].append(now)

    def reset(self, key: str | None = None) -> None:
        """Clear one key (e.g. on a successful login) or all keys (tests)."""
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)
