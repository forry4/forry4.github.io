"""Owner alerts — tell the site owner when something bad is happening.

`alert(kind, message)` is the one call. It is safe to make from ANYWHERE — an
async route, a WebSocket handler, a thread, the middle of a rate-limit check —
because it never blocks and never raises: it deduplicates in memory, puts the
alert on a queue, and returns. One daemon thread drains the queue, writes each
alert to the `site_alerts` table (what the owner's Site health panel reads) and
pushes it to whichever channels are configured:

  * ALERT_NTFY_TOPIC   — push to a phone via ntfy (https://ntfy.sh). Install the
                         ntfy app and subscribe to the same topic. The topic name
                         is the only secret, so make it long and random.
    ALERT_NTFY_SERVER  — optional, default https://ntfy.sh
    ALERT_NTFY_TOKEN   — optional access token for a reserved/protected topic
    ALERT_EMAIL        — optional: ntfy also forwards the alert to this address
                         (ntfy.sh rate-limits these; the push is the primary path)
  * ALERT_WEBHOOK_URL  — a Discord or Slack incoming webhook (posts `content`
                         and `text`, so either accepts it).

With nothing configured, alerts still land in the table and the log. Render's free
tier blocks outbound SMTP, which is why there is no direct email channel — every
channel here is one HTTPS POST.

DEDUP. The same `key` (default: the kind) is sent at most once per `cooldown`
seconds; repeats inside the window are COUNTED and the next alert that does go
out says how many were folded into it. So a flood produces one push an hour, not
ten thousand, and the push still tells you it was a flood. The dedup state is
per-process and in memory, like the rate limiters it sits next to.
"""
from __future__ import annotations

import json
import logging
import os
import queue
import threading
import time
import urllib.request

LOG = logging.getLogger("core.alerts")

SEVERITIES = ("info", "warn", "critical")
DEFAULT_COOLDOWN = 3600
KEEP_ROWS = 500              # the table is a recent log, not an archive
_MSG_MAX = 1000
_SITE = "Forrest Games"

# ntfy priorities: 3 = default, 4 = high, 5 = urgent (bypasses Do Not Disturb on
# Android if the user allows it).
_NTFY_PRIORITY = {"info": "3", "warn": "4", "critical": "5"}
_NTFY_TAG = {"info": "information_source", "warn": "warning", "critical": "rotating_light"}


def init_alerts_schema(conn) -> None:
    conn.execute("""
    CREATE TABLE IF NOT EXISTS site_alerts (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        created_at INTEGER NOT NULL,
        kind       TEXT NOT NULL,
        severity   TEXT NOT NULL,
        message    TEXT NOT NULL,
        folded     INTEGER DEFAULT 0,
        acked      INTEGER DEFAULT 0
    )""")
    conn.commit()


# ── dedup ────────────────────────────────────────────────────────────────────
_lock = threading.Lock()
_last_sent: dict[str, float] = {}
_folded: dict[str, int] = {}


def _admit(key: str, cooldown: float, now: float) -> int | None:
    """None if `key` is inside its cooldown (the repeat is counted); otherwise the
    number of repeats folded since the last one that went out."""
    with _lock:
        last = _last_sent.get(key)
        if last is not None and now - last < cooldown:
            _folded[key] = _folded.get(key, 0) + 1
            return None
        _last_sent[key] = now
        return _folded.pop(key, 0)


def reset() -> None:
    """Forget the dedup state (tests)."""
    with _lock:
        _last_sent.clear()
        _folded.clear()


# ── the call ─────────────────────────────────────────────────────────────────
# TESTS set this to a list (the root conftest does, per test): alerts are appended
# to it instead of being stored and pushed, so no test writes to a real database or
# pings a real phone, and a test can assert on exactly what was raised.
_sink: list | None = None

_queue: "queue.Queue[dict]" = queue.Queue(maxsize=1000)
_worker: threading.Thread | None = None
_worker_lock = threading.Lock()


def alert(kind: str, message: str, *, key: str | None = None, severity: str = "warn",
          cooldown: float = DEFAULT_COOLDOWN) -> bool:
    """Raise an owner alert. Returns True if it was queued, False if it was folded
    into an earlier one (or dropped). Never blocks, never raises."""
    try:
        if severity not in SEVERITIES:
            severity = "warn"
        now = time.time()
        folded = _admit(key or kind, cooldown, now)
        if folded is None:
            return False
        item = {"kind": str(kind)[:64], "severity": severity, "created_at": int(now),
                "message": str(message)[:_MSG_MAX], "folded": folded}
        log = LOG.error if severity == "critical" else LOG.warning
        log("ALERT [%s] %s: %s%s", severity, item["kind"], item["message"],
            f" (+{folded} since last)" if folded else "")
        if _sink is not None:
            _sink.append(item)
            return True
        _ensure_worker()
        _queue.put_nowait(item)
        return True
    except Exception:  # noqa: BLE001 - an alert must never break the caller
        return False


def _ensure_worker() -> None:
    global _worker
    if _worker is not None and _worker.is_alive():
        return
    with _worker_lock:
        if _worker is None or not _worker.is_alive():
            _worker = threading.Thread(target=_run, name="site-alerts", daemon=True)
            _worker.start()


def drain(timeout: float = 5.0) -> bool:
    """Wait until every queued alert has been delivered (tests, shutdown)."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _queue.unfinished_tasks == 0:
            return True
        time.sleep(0.01)
    return False


def _run() -> None:
    while True:
        item = _queue.get()
        try:
            _deliver(item)
        except Exception as e:  # noqa: BLE001
            LOG.warning("alert delivery failed: %s", e)
        finally:
            _queue.task_done()


# ── delivery ─────────────────────────────────────────────────────────────────
def channels() -> list[str]:
    out = []
    if os.environ.get("ALERT_NTFY_TOPIC", "").strip():
        out.append("ntfy")
    if os.environ.get("ALERT_WEBHOOK_URL", "").strip():
        out.append("webhook")
    return out


def _text(item: dict) -> str:
    extra = f"\n(+{item['folded']} more like this since the last alert)" if item.get("folded") else ""
    return item["message"] + extra


def _deliver(item: dict) -> None:
    _store(item)
    for name, send in (("ntfy", _send_ntfy), ("webhook", _send_webhook)):
        if name in channels():
            try:
                send(item)
            except Exception as e:  # noqa: BLE001 - one channel failing must not stop the other
                LOG.warning("alert channel %s failed: %s", name, e)


def _store(item: dict) -> None:
    from core.db import get_db_conn   # lazy: core.db must never import this module back
    conn = get_db_conn()
    try:
        init_alerts_schema(conn)
        conn.execute(
            "INSERT INTO site_alerts (created_at, kind, severity, message, folded, acked) "
            "VALUES (?, ?, ?, ?, ?, 0)",
            (item["created_at"], item["kind"], item["severity"], item["message"], item["folded"]))
        cur = conn.cursor()
        cur.execute("SELECT id FROM site_alerts ORDER BY id DESC LIMIT 1 OFFSET ?", (KEEP_ROWS,))
        r = cur.fetchone()
        if r:
            conn.execute("DELETE FROM site_alerts WHERE id <= ?", (r[0],))
        conn.commit()
    except Exception as e:  # noqa: BLE001 - a DB hiccup must not stop the push
        LOG.warning("could not store alert: %s", e)
    finally:
        conn.close()


def _post(url: str, data: bytes, headers: dict) -> None:
    req = urllib.request.Request(url, data=data, headers=headers, method="POST")
    with urllib.request.urlopen(req, timeout=10) as res:   # noqa: S310 - fixed https endpoints
        res.read()


def _send_ntfy(item: dict) -> None:
    server = (os.environ.get("ALERT_NTFY_SERVER") or "https://ntfy.sh").rstrip("/")
    topic = os.environ["ALERT_NTFY_TOPIC"].strip()
    # HTTP headers are latin-1; the title is ASCII by construction, the body is UTF-8.
    headers = {
        "Title": f"{_SITE}: {item['kind']}",
        "Priority": _NTFY_PRIORITY[item["severity"]],
        "Tags": _NTFY_TAG[item["severity"]],
    }
    token = os.environ.get("ALERT_NTFY_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    email = os.environ.get("ALERT_EMAIL", "").strip()
    if email:
        headers["Email"] = email
    _post(f"{server}/{topic}", _text(item).encode("utf-8"), headers)


def _send_webhook(item: dict) -> None:
    icon = {"info": "ℹ️", "warn": "⚠️", "critical": "🚨"}[item["severity"]]
    text = f"{icon} **{_SITE} — {item['kind']}**\n{_text(item)}"
    body = json.dumps({"content": text[:1900], "text": text}).encode("utf-8")
    _post(os.environ["ALERT_WEBHOOK_URL"].strip(), body,
          {"Content-Type": "application/json", "User-Agent": "forrest-games-alerts"})


# ── reads for the Site health panel ──────────────────────────────────────────
def recent(conn, limit: int = 100) -> list[dict]:
    init_alerts_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT id, created_at, kind, severity, message, folded, acked FROM site_alerts "
                "ORDER BY id DESC LIMIT ?", (limit,))
    return [{"id": r[0], "created_at": r[1], "kind": r[2], "severity": r[3], "message": r[4],
             "folded": r[5] or 0, "acked": bool(r[6])} for r in cur.fetchall()]


def unacked(conn) -> int:
    init_alerts_schema(conn)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM site_alerts WHERE acked=0")
    return cur.fetchone()[0]


def ack_all(conn) -> None:
    init_alerts_schema(conn)
    conn.execute("UPDATE site_alerts SET acked=1 WHERE acked=0")
    conn.commit()
