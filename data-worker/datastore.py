"""The data jobs' side of the data store (data-worker/): take the published copy
before a build, publish what the build changed after it.

    python data-worker/datastore.py take    <name.json> ...
    python data-worker/datastore.py take-lol                 # the LoL index + every year it lists
    python data-worker/datastore.py publish <name.json> ...

Reads DATA_URL (and, to publish, DATA_PUBLISH_TOKEN) from the environment; with no
DATA_URL both commands do nothing, so a workflow can call them unconditionally.

TAKE replaces webapp/public/data/<name> with the store's copy. Every builder here
builds ON the previous file — prices.py carries sale starts forward and reads the
Steam game list, enrich re-reads the payload, the anime and BGG builders refuse a
payload under 90% of the current one, LoL rebuilds its index from the year files on
disk — so once the repo stops receiving commits, its copy is stale and building on
it would publish a regression. A 404 means "never published": the repo's copy
stands. Anything else (5xx, a body that is not JSON, no answer) FAILS the job.

PUBLISH uploads each named file that changed since TAKE, or that the store did not
have, then reads it back until the store serves the same bytes (KV is eventually
consistent, up to about a minute). The manifest between the two lives in
$RUNNER_TEMP. Stdlib only, so every job runs it without an install step.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "webapp", "public", "data")
UA = "forrestgames-data-jobs"


def _manifest_path() -> str:
    return os.path.join(os.environ.get("RUNNER_TEMP") or os.path.join(ROOT, ".datastore"), "datastore-manifest.json")


def _read_manifest() -> dict:
    try:
        with open(_manifest_path(), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return {}


def _write_manifest(m: dict) -> None:
    os.makedirs(os.path.dirname(_manifest_path()), exist_ok=True)
    with open(_manifest_path(), "w", encoding="utf-8") as f:
        json.dump(m, f)


def _sha(path: str) -> str | None:
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def _get(url: str, opener=urllib.request.urlopen, tries: int = 3) -> tuple[int, bytes]:
    last = None
    for i in range(tries):
        try:
            with opener(urllib.request.Request(url, headers={"User-Agent": UA}), timeout=60) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            if e.code < 500:
                return e.code, e.read()
            last = e
        except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
            last = e
        time.sleep(2 * (i + 1))
    raise SystemExit(f"the data store did not answer for {url}: {last}")


def take(names: list[str], base: str, opener=urllib.request.urlopen) -> dict:
    manifest = _read_manifest()
    for name in names:
        code, body = _get(f"{base}/{name}", opener)
        dest = os.path.join(DATA, name)
        if code == 200:
            try:
                json.loads(body)
            except ValueError:
                raise SystemExit(f"the data store's {name} is not JSON; refusing to build on it")
            os.makedirs(DATA, exist_ok=True)
            with open(dest, "wb") as f:
                f.write(body)
            manifest[name] = hashlib.sha256(body).hexdigest()
            print(f"took {name} from the data store ({len(body):,} bytes)")
        elif code == 404:
            manifest[name] = None            # never published: the repo's copy stands
            print(f"::notice::the data store has no {name} yet; building on the repo's copy")
        else:
            raise SystemExit(f"the data store answered HTTP {code} for {name}")
    _write_manifest(manifest)
    return manifest


def take_lol(base: str, opener=urllib.request.urlopen) -> None:
    take(["lol-champs-index.json"], base, opener)
    with open(os.path.join(DATA, "lol-champs-index.json"), encoding="utf-8") as f:
        years = [y["year"] for y in json.load(f).get("years") or []]
    take([f"lol-champs-{y}.json" for y in years], base, opener)


def publish(names: list[str], base: str, token: str, opener=urllib.request.urlopen,
            settle_tries: int = 12, settle_wait: float = 10.0) -> list[str]:
    if not token:
        raise SystemExit("DATA_URL is set but the DATA_PUBLISH_TOKEN secret is not")
    manifest = _read_manifest()
    sent = []
    for name in names:
        path = os.path.join(DATA, name)
        body = open(path, "rb").read()
        sha = hashlib.sha256(body).hexdigest()
        if name in manifest and manifest[name] == sha:
            print(f"{name}: unchanged")
            continue
        req = urllib.request.Request(f"{base}/{name}", data=body, method="PUT", headers={
            "Authorization": f"Bearer {token}", "Content-Type": "application/json", "User-Agent": UA})
        try:
            with opener(req, timeout=120) as r:
                print(f"{name}: {r.read().decode(errors='replace')}")
        except urllib.error.HTTPError as e:
            raise SystemExit(f"publishing {name} failed: HTTP {e.code} {e.read()[:300]!r}")
        # A 200 from the PUT is not the file being served: read it back.
        for i in range(settle_tries):
            code, got = _get(f"{base}/{name}?v={time.time_ns()}", opener)
            if code == 200 and got == body:
                break
            time.sleep(settle_wait)
        else:
            raise SystemExit(f"the data store is not serving the {name} that was just published")
        manifest[name] = sha
        sent.append(name)
        print(f"published {name} ({len(body):,} bytes)")
    _write_manifest(manifest)
    return sent


def main(argv: list[str]) -> None:
    base = (os.environ.get("DATA_URL") or "").rstrip("/")
    if not base:
        print("DATA_URL is not set; the data store is off")
        return
    cmd, names = (argv[0] if argv else ""), argv[1:]
    if cmd == "take":
        take(names, base)
    elif cmd == "take-lol":
        take_lol(base)
    elif cmd == "publish":
        publish(names, base, os.environ.get("DATA_PUBLISH_TOKEN") or "")
    else:
        raise SystemExit(__doc__)


if __name__ == "__main__":
    main(sys.argv[1:])
