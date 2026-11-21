"""How LoL Stats' harvesters talk to the sites they read: one place, so every source is
asked the same courteous way.

The sites are free community resources (Leaguepedia, Google Drive for Oracle's Elixir), and
both refresh jobs run on GitHub runners whose IPs are SHARED with everyone else's jobs, so
a site's patience with "this IP" is partly spent before we arrive. What that asks of us:

- **Say who we are.** A User-Agent naming the project and a URL to reach it, and gzip.
- **One request at a time, spaced.** `Client(min_interval=...)` waits between requests to
  the same site, however the caller loops.
- **Ask for as little as possible.** That is the callers' half: a refresh asks only for the
  year still being played and keeps settled years on disk (worlds.py), and a retry day
  does nothing once the month has landed (refresh_due.py).
- **Back off, and give up for the day rather than push.** A 5xx, a dropped connection or
  a MediaWiki `ratelimited`/`maxlag` error is waited out with exponential backoff and
  jitter (honoring Retry-After), inside a fixed time BUDGET for the whole run. A 429 is
  waited out only when it says how long and that fits the budget; a bare 429 is a block
  (Liquipedia's "Rate Limited" page, 2026-11-21: lifted by a CAPTCHA or by time), and
  retrying a block only renews it. Either way the run ends with `TryLater`, which the
  scripts turn into exit 75 (EX_TEMPFAIL) and the workflows into "try again tomorrow".
- **Name what happened.** Every failure carries the status and the start of the body.
"""
import gzip
import json
import random
import time
import urllib.error
import urllib.parse
import urllib.request

UA = "ForrestGames-LoLStats/1.1 (+https://forry4.github.io; github.com/forry4/forry4.github.io)"
EX_TEMPFAIL = 75   # sysexits: a temporary failure; try again later
TRANSIENT_HTTP = {500, 502, 503, 504}
TRANSIENT_API = {"ratelimited", "maxlag"}   # MediaWiki's own "slow down" answers


def notice(title, message):
    """On a runner, a public ::notice:: annotation. The Actions log needs a sign-in to read
    even on a public repo; annotations do not, and the pipeline alert links the run."""
    import os
    if os.environ.get("GITHUB_ACTIONS") == "true":
        text = str(message).replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
        print(f"::notice title={title}::{text}", flush=True)


class TryLater(Exception):
    """The site asked us to stop for now (a block, a quota, a rate limit that did not clear
    inside the budget). Not a fault of ours or of the data; the next scheduled run retries."""


class Refused(SystemExit):
    """A refusal that waiting will not fix (a 403, a 404, an unknown API error)."""


def _body(b, headers):
    if headers is not None and headers.get("Content-Encoding") == "gzip":
        try:
            b = gzip.decompress(b)
        except OSError:
            pass
    return b


def _retry_after(headers):
    try:
        return max(0, int((headers or {}).get("Retry-After") or ""))
    except ValueError:
        return None


class Client:
    """One site. `min_interval` seconds between requests; `budget` seconds of waiting
    (spacing excluded) before the run gives up for the day; `base` the first backoff."""

    def __init__(self, name, min_interval=2.0, budget=600, base=30, cap=300,
                 sleep=time.sleep, clock=time.monotonic, rand=random.random):
        self.name, self.min_interval, self.budget = name, min_interval, budget
        self.base, self.cap = base, cap
        self._sleep, self._clock, self._rand = sleep, clock, rand
        self._last = None
        self.waited = 0.0
        self.requests = 0

    def _space(self):
        if self._last is not None:
            gap = self.min_interval - (self._clock() - self._last)
            if gap > 0:
                self._sleep(gap)
        self._last = self._clock()

    def _backoff(self, attempt, why, hint=None):
        """Wait before the next try, or raise TryLater once the budget would be spent."""
        wait = hint if hint is not None else min(self.cap, self.base * 2 ** (attempt - 1))
        wait = max(wait, self.min_interval) * (1 + 0.25 * self._rand())   # jitter: never in step
        if self.waited + wait > self.budget:
            raise TryLater(f"{self.name}: {why}; still refused after {attempt} tries and "
                           f"{self.waited:.0f}s of waiting, so stopping for today")
        print(f"{self.name}: {why}; waiting {wait:.0f}s (try {attempt})", flush=True)
        self.waited += wait
        self._sleep(wait)

    def open(self, url, params=None):
        """The response, open, for the caller to read or stream. Retries what is transient."""
        if params:
            url = url + ("&" if "?" in url else "?") + urllib.parse.urlencode(params)
        attempt = 0
        while True:
            attempt += 1
            self._space()
            self.requests += 1
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip"})
            try:
                return urllib.request.urlopen(req, timeout=120)
            except urllib.error.HTTPError as e:
                body = _body(e.read() or b"", e.headers)[:200]
                ra = _retry_after(e.headers)
                if e.code == 429:
                    if ra is None:
                        raise TryLater(f"{self.name}: HTTP 429 with no Retry-After, i.e. this IP is "
                                       f"blocked for now; retrying would only renew it: {body!r}")
                    self._backoff(attempt, f"HTTP 429, Retry-After {ra}s", ra)
                    continue
                if e.code in TRANSIENT_HTTP:
                    self._backoff(attempt, f"HTTP {e.code}", ra)
                    continue
                raise Refused(f"{self.name}: HTTP {e.code} {e.reason}: {body!r}")
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                self._backoff(attempt, f"could not connect ({e})")

    def json(self, url, params=None, mediawiki=False):
        """A JSON answer. With `mediawiki`, also sends maxlag=5 (the server refuses rather
        than answer while its replicas lag, the courteous default for bots) and waits out
        the API's own ratelimited/maxlag errors, which arrive as HTTP 200."""
        params = {**(params or {}), "format": "json"} if mediawiki else (params or {})
        if mediawiki:
            params.setdefault("maxlag", "5")
        attempt = 0
        while True:
            attempt += 1
            with self.open(url, params) as r:
                d = json.loads(_body(r.read(), r.headers))
            err = d.get("error") if isinstance(d, dict) else None
            code = err.get("code") if isinstance(err, dict) else None
            if code in TRANSIENT_API:
                self._backoff(attempt, f"API error {code}")
                continue
            if code:
                raise Refused(f"{self.name}: API error {code}: {err.get('info')}")
            return d
