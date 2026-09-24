"""Notes — a private notebook for every signed-in account.

Nested folders of notes; a note is a flowing rich-text document whose body is the
editor's (TipTap/ProseMirror) JSON, stored verbatim as TEXT. Screenshots are
separate rows referenced from the document by id, so saving a note never re-sends
its images.

EVERY ROW BELONGS TO ONE ACCOUNT, AND EVERY QUERY SAYS WHOSE. Notes began as the
site owner's alone, with no owner column at all; opening it to everyone means each
of the three tables carries `owner_id` and every pure function takes the caller's
id as its SECOND argument and scopes by it — reads, writes, the folder-tree walks,
the image fetch and the search. An id that belongs to someone else behaves exactly
like an id that does not exist (404 / "no such folder"), so the API cannot even
confirm another account's note is there. Guests have no session and are refused.
The rows written before this existed have `owner_id IS NULL`: nobody can see them
until the site owner's first visit claims them (`claim_unowned`).

AND IT IS METERED, because a text box anyone can fill is storage anyone can burn:
a byte quota, note and folder caps, and a site-wide ceiling across every non-owner
account (so many accounts at quota cannot fill the database either), plus
per-account write rate limits. Hitting any of them tells the owner (`core.alerts`).
The site owner is unmetered but still rate-limited — a stolen session is still a
session.

Design points worth knowing before editing:
  * The route handlers are plain `def`, not `async def`: FastAPI runs them in its
    threadpool, so a slow Turso round-trip (or a 3MB image insert) never blocks
    the event loop the game sockets share.
  * Stale-edit guard: every note carries `rev`. A save sends the rev it was based
    on; a mismatch is a CONFLICT (another tab/device saved first) and returns the
    server copy instead of overwriting it. Only content saves bump `rev` — moving,
    pinning or trashing a note must not 409 a tab that is mid-sentence.
  * Images are base64 TEXT, not BLOB: the libsql driver cannot be tested on
    Windows, and TEXT is the shape Books' inline covers already prove on Turso.
  * Deletes are soft (`deleted_at` -> Trash), purged after TRASH_DAYS. Images are
    never deleted directly: a sweep drops any image none of its OWNER's notes
    references once it is IMAGE_GRACE old, which keeps editor undo of an image
    delete working and lets an image pasted into a second note survive the first
    note's deletion. Emptying the Trash runs the same sweep for that account with a
    one-hour grace, so the space it frees is back before the quota is next checked.
  * libsql has no `cur.rowcount`, so every "did it exist" is a SELECT first.

The pure functions take a connection so they are unit-tested on a real sqlite file.
"""
import base64
import json
import os
import secrets
import string
import threading
import time

from fastapi import Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core import alerts
from core.auth import is_site_owner, site_owner_name
from core.ratelimit import SlidingWindowLimiter


# ── limits ───────────────────────────────────────────────────────────────────
_ID = 32
_NAME = 200                 # folder name / note title
_DOC = 2_000_000            # editor JSON (images are references, so this is text only)
_IMAGE_BYTES = 3_000_000    # decoded; the client downscales to <=1920px WebP first
_IMAGE_B64 = (_IMAGE_BYTES * 4) // 3 + 8
MAX_DEPTH = 12              # folder nesting depth
TRASH_DAYS = 30
IMAGE_GRACE = 7 * 86400
EMPTY_TRASH_GRACE = 3600    # the per-account sweep an Empty Trash runs
_SWEEP_INTERVAL = 3600


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name) or default)
    except ValueError:
        return default


# Quotas, for every account but the site owner's. Bytes are each note's JSON + its
# plain text + title, and each picture's decoded size. The Trash counts (it is still
# stored) until it is emptied.
NOTES_QUOTA_MB = _env_int("NOTES_QUOTA_MB", 25)
QUOTA_BYTES = NOTES_QUOTA_MB * 1_000_000
MAX_NOTES = 1000            # the Trash included
MAX_FOLDERS = 300
# Every non-owner account together. Registration is capped per hour, but an hour of
# new accounts at 25MB each is still over a gigabyte — this is what bounds that.
SITE_BUDGET_BYTES = _env_int("NOTES_SITE_BUDGET_MB", 1024) * 1_000_000
SITE_ALERT_FRACTION = 0.8

# Write rates, per account. Autosave is debounced (one save after each 1s pause in
# typing), so a fast typist makes well under one a second; these are ~2x that.
_writes_minute = SlidingWindowLimiter(max_hits=120, window_seconds=60)
_writes_hour = SlidingWindowLimiter(max_hits=3000, window_seconds=3600)
_uploads_hour = SlidingWindowLimiter(max_hits=120, window_seconds=3600)
_searches_minute = SlidingWindowLimiter(max_hits=60, window_seconds=60)

# Declared type -> the magic bytes it must start with. The image route serves the
# declared type, so it has to be true (and nosniff is on site-wide).
_MAGIC = {
    "image/jpeg": (b"\xff\xd8\xff",),
    "image/png": (b"\x89PNG\r\n\x1a\n",),
    "image/gif": (b"GIF87a", b"GIF89a"),
    "image/webp": (b"RIFF",),
}

_ALPHABET = string.ascii_lowercase + string.digits


def _gen_id(n: int = 16) -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(n))


def _now() -> int:
    return int(time.time())


# ── schema ───────────────────────────────────────────────────────────────────
def init_notes_db(conn) -> None:
    cur = conn.cursor()
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS note_folders (
            id         TEXT PRIMARY KEY,
            parent_id  TEXT,
            name       TEXT NOT NULL,
            sort_order INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS notes (
            id         TEXT PRIMARY KEY,
            folder_id  TEXT,
            title      TEXT DEFAULT '',
            doc        TEXT DEFAULT '',
            rev        INTEGER DEFAULT 0,
            pinned     INTEGER DEFAULT 0,
            sort_order INTEGER DEFAULT 0,
            created_at INTEGER,
            updated_at INTEGER,
            deleted_at INTEGER
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS note_images (
            id         TEXT PRIMARY KEY,
            note_id    TEXT,
            mime       TEXT NOT NULL,
            width      INTEGER DEFAULT 0,
            height     INTEGER DEFAULT 0,
            bytes      INTEGER DEFAULT 0,
            data       TEXT NOT NULL,
            created_at INTEGER
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_folder ON notes(folder_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_note_folders_parent ON note_folders(parent_id)")
    # Columns added after the tables first shipped, by ALTER; each raises once the
    # column is there, on both sqlite and libsql.
    #   body_text — the note's PLAIN text (one block per line, image captions included),
    #     written on every save. Search reads this, never `doc` — in the editor JSON a
    #     bolded word is its own text node, so "reads 3:15" is not a substring of the doc.
    #   owner_id (all three) and size — when Notes opened to every account.
    for table, col in (("notes", "body_text TEXT"), ("notes", "owner_id TEXT"),
                       ("notes", "size INTEGER"), ("note_folders", "owner_id TEXT"),
                       ("note_images", "owner_id TEXT")):
        try:
            cur.execute(f"ALTER TABLE {table} ADD COLUMN {col}")
        except Exception:  # noqa: BLE001 - "duplicate column" is the expected steady state
            pass
    cur.execute("CREATE INDEX IF NOT EXISTS idx_notes_owner ON notes(owner_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_note_folders_owner ON note_folders(owner_id)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_note_images_owner ON note_images(owner_id)")
    cur.execute("SELECT id, doc FROM notes WHERE body_text IS NULL")
    for r in cur.fetchall():
        try:
            doc = json.loads(r["doc"]) if r["doc"] else None
        except ValueError:
            doc = None
        conn.execute("UPDATE notes SET body_text=? WHERE id=?", (doc_text(doc), r["id"]))
    conn.execute(
        "UPDATE notes SET size = length(CAST(COALESCE(doc,'') AS BLOB)) "
        "+ length(CAST(COALESCE(body_text,'') AS BLOB)) + length(CAST(COALESCE(title,'') AS BLOB)) "
        "WHERE size IS NULL")
    conn.commit()


def claim_unowned(conn, uid: str) -> int:
    """Give every row written before owners existed to `uid` — only ever called for
    the site owner's account, whose notebook this was. Returns the notes claimed."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notes WHERE owner_id IS NULL")
    n = cur.fetchone()[0]
    for table in ("notes", "note_folders", "note_images"):
        conn.execute(f"UPDATE {table} SET owner_id=? WHERE owner_id IS NULL", (uid,))
    conn.commit()
    return n


# ── helpers ──────────────────────────────────────────────────────────────────
def _folder_parents(conn, uid: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT id, parent_id FROM note_folders WHERE owner_id=?", (uid,))
    return {r["id"]: r["parent_id"] for r in cur.fetchall()}


def _folder_exists(conn, uid: str, folder_id) -> bool:
    if folder_id is None:
        return True
    return folder_id in _folder_parents(conn, uid)


def _depth(parents: dict, folder_id) -> int:
    d, seen = 0, set()
    while folder_id is not None and folder_id not in seen:
        seen.add(folder_id)
        folder_id = parents.get(folder_id)
        d += 1
    return d


def _subtree(parents: dict, root: str) -> set:
    out = {root}
    grew = True
    while grew:
        grew = False
        for fid, pid in parents.items():
            if pid in out and fid not in out:
                out.add(fid)
                grew = True
    return out


def _height(parents: dict, root: str) -> int:
    """Levels in the subtree under `root`, counting root itself (a leaf is 1)."""
    best = 0
    for f in _subtree(parents, root):
        n = 1
        while f != root:
            f = parents[f]
            n += 1
        best = max(best, n)
    return best


def _clean_name(s, fallback: str) -> str:
    s = (s or "").strip()
    return s[:_NAME] if s else fallback


def _size(title: str, body: str, text: str) -> int:
    return len(title.encode()) + len(body.encode()) + len(text.encode())


def _note_meta(r) -> dict:
    return {
        "id": r["id"], "folder_id": r["folder_id"], "title": r["title"] or "",
        "pinned": bool(r["pinned"]), "created_at": r["created_at"],
        "updated_at": r["updated_at"], "deleted_at": r["deleted_at"],
    }


_META_COLS = "id, folder_id, title, pinned, created_at, updated_at, deleted_at"


# ── usage + quota ────────────────────────────────────────────────────────────
class QuotaError(ValueError):
    """A write that would take an account (or the site) past its Notes storage."""


def usage(conn, uid: str) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*), COALESCE(SUM(size), 0) FROM notes WHERE owner_id=?", (uid,))
    notes, note_bytes = cur.fetchone()
    cur.execute("SELECT COUNT(*) FROM note_folders WHERE owner_id=?", (uid,))
    folders = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*), COALESCE(SUM(bytes), 0) FROM note_images WHERE owner_id=?", (uid,))
    images, image_bytes = cur.fetchone()
    return {"bytes": int(note_bytes) + int(image_bytes), "notes": notes, "folders": folders,
            "images": images}


def site_metered_bytes(conn) -> int:
    """Notes storage across every account that is metered (everyone but admins)."""
    cur = conn.cursor()
    try:
        cur.execute("SELECT COALESCE(SUM(size), 0) FROM notes WHERE owner_id IS NOT NULL "
                    "AND owner_id NOT IN (SELECT user_id FROM admins)")
        n = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(bytes), 0) FROM note_images WHERE owner_id IS NOT NULL "
                    "AND owner_id NOT IN (SELECT user_id FROM admins)")
        return int(n) + int(cur.fetchone()[0])
    except Exception:  # noqa: BLE001 - no admins table (a bare test DB): count everyone
        cur.execute("SELECT COALESCE(SUM(size), 0) FROM notes")
        n = cur.fetchone()[0]
        cur.execute("SELECT COALESCE(SUM(bytes), 0) FROM note_images")
        return int(n) + int(cur.fetchone()[0])


# Usage is summed from the account's rows, which on Turso is billed per row read.
# Autosave checks it on every save, so it is cached for a minute and moved by each
# write's own delta in between; deletes drop the cache instead of guessing.
_USAGE_TTL = 60
_SITE_TTL = 300
_cache_lock = threading.Lock()
_usage_cache: dict[str, tuple[float, dict]] = {}
_site_cache: list = [0.0, 0]


def forget_usage(uid: str | None = None) -> None:
    with _cache_lock:
        if uid is None:
            _usage_cache.clear()
            _site_cache[0] = 0.0
        else:
            _usage_cache.pop(uid, None)


def _fmt_mb(n: int) -> str:
    return f"{n / 1_000_000:.1f} MB"


class Meter:
    """One account's quota. `check` before a write that grows storage (raises
    QuotaError), `charge` after it lands."""

    def __init__(self, uid: str, name: str = "", *, quota_bytes: int = QUOTA_BYTES,
                 max_notes: int = MAX_NOTES, max_folders: int = MAX_FOLDERS,
                 site_budget: int = SITE_BUDGET_BYTES):
        self.uid, self.name = uid, name
        self.quota_bytes, self.max_notes, self.max_folders = quota_bytes, max_notes, max_folders
        self.site_budget = site_budget

    def current(self, conn) -> dict:
        now = time.time()
        with _cache_lock:
            hit = _usage_cache.get(self.uid)
            if hit and hit[0] > now:
                return dict(hit[1])
        u = usage(conn, self.uid)
        with _cache_lock:
            _usage_cache[self.uid] = (now + _USAGE_TTL, u)
        return dict(u)

    def _site(self, conn) -> int:
        now = time.time()
        with _cache_lock:
            if _site_cache[0] > now:
                return _site_cache[1]
        n = site_metered_bytes(conn)
        with _cache_lock:
            _site_cache[0], _site_cache[1] = now + _SITE_TTL, n
        return n

    def _refuse(self, what: str, message: str) -> None:
        alerts.alert("notes-quota", f"{self.name or self.uid} hit the Notes {what} limit.",
                     key=f"notes-quota:{self.uid}", severity="info", cooldown=86400)
        raise QuotaError(message)

    def check(self, conn, *, add_bytes: int = 0, add_notes: int = 0, add_folders: int = 0) -> None:
        u = self.current(conn)
        if add_notes > 0 and u["notes"] + add_notes > self.max_notes:
            self._refuse("note-count", f"You have {self.max_notes} notes, the most an account can "
                         "keep (notes in the Trash count). Delete some and empty the Trash.")
        if add_folders > 0 and u["folders"] + add_folders > self.max_folders:
            self._refuse("folder-count", f"You have {self.max_folders} folders, the most an "
                         "account can keep.")
        if add_bytes <= 0:
            return
        if u["bytes"] + add_bytes > self.quota_bytes:
            self._refuse("storage", f"Your notes are full ({_fmt_mb(u['bytes'])} of "
                         f"{_fmt_mb(self.quota_bytes)}). Delete notes or pictures, then empty "
                         "the Trash to make room.")
        site = self._site(conn)
        if site + add_bytes > self.site_budget:
            alerts.alert("notes-storage", f"Notes storage across all accounts is full "
                         f"({_fmt_mb(site)} of {_fmt_mb(self.site_budget)}); writes that grow "
                         "a notebook are being refused.", key="notes-site-full", severity="critical")
            raise QuotaError("Notes storage for the site is full right now. Try again later.")
        if site + add_bytes > self.site_budget * SITE_ALERT_FRACTION:
            alerts.alert("notes-storage", f"Notes storage across all accounts is at "
                         f"{_fmt_mb(site)} of {_fmt_mb(self.site_budget)}.",
                         key="notes-site-high", cooldown=86400)

    def charge(self, *, add_bytes: int = 0, add_notes: int = 0, add_folders: int = 0,
               add_images: int = 0) -> None:
        with _cache_lock:
            hit = _usage_cache.get(self.uid)
            if hit:
                u = dict(hit[1])
                u["bytes"] += add_bytes
                u["notes"] += add_notes
                u["folders"] += add_folders
                u["images"] += add_images
                _usage_cache[self.uid] = (hit[0], u)
            if _site_cache[0]:
                _site_cache[1] += add_bytes


# ── reads ────────────────────────────────────────────────────────────────────
def fetch_tree(conn, uid: str) -> dict:
    """Folders + note METADATA (no bodies): enough to draw the sidebar, Pinned,
    Recent and Trash without downloading every document."""
    cur = conn.cursor()
    cur.execute("SELECT id, parent_id, name FROM note_folders WHERE owner_id=? "
                "ORDER BY name COLLATE NOCASE", (uid,))
    folders = [{"id": r["id"], "parent_id": r["parent_id"], "name": r["name"]} for r in cur.fetchall()]
    cur.execute(f"SELECT {_META_COLS} FROM notes WHERE owner_id=? ORDER BY updated_at DESC", (uid,))
    notes = [_note_meta(r) for r in cur.fetchall()]
    return {"folders": folders, "notes": notes}


def get_note(conn, uid: str, note_id: str) -> dict | None:
    cur = conn.cursor()
    cur.execute(f"SELECT {_META_COLS}, doc, rev FROM notes WHERE id=? AND owner_id=?", (note_id, uid))
    r = cur.fetchone()
    if not r:
        return None
    out = _note_meta(r)
    doc = r["doc"] or ""
    try:
        out["doc"] = json.loads(doc) if doc else None
    except ValueError:
        out["doc"] = None
    out["rev"] = r["rev"] or 0
    return out


# ── note writes ──────────────────────────────────────────────────────────────
def create_note(conn, uid: str, folder_id=None, title: str = "", quota: Meter | None = None) -> dict:
    if not _folder_exists(conn, uid, folder_id):
        folder_id = None
    title = (title or "").strip()[:_NAME]
    size = _size(title, "", "")
    if quota is not None:
        quota.check(conn, add_notes=1, add_bytes=size)
    nid, now = _gen_id(), _now()
    conn.execute(
        "INSERT INTO notes (id, owner_id, folder_id, title, doc, rev, pinned, created_at, updated_at, size) "
        "VALUES (?, ?, ?, ?, '', 0, 0, ?, ?, ?)",
        (nid, uid, folder_id, title, now, now, size),
    )
    conn.commit()
    if quota is not None:
        quota.charge(add_notes=1, add_bytes=size)
    return get_note(conn, uid, nid)


# Nodes whose inline children are one line of text; everything else is a container.
_TEXTBLOCKS = {"paragraph", "heading", "codeBlock"}


def doc_text(doc) -> str:
    """The editor document as plain text: one line per text block (so a match never
    runs across two paragraphs), plus each image caption on a line of its own."""
    lines: list[str] = []

    def inline(node) -> str:
        out = []
        for c in node.get("content") or []:
            if c.get("type") == "text":
                out.append(c.get("text") or "")
            elif c.get("type") == "hardBreak":
                out.append(" ")
        return "".join(out)

    def walk(node):
        if not isinstance(node, dict):
            return
        t = node.get("type")
        if t in _TEXTBLOCKS:
            line = inline(node).replace("\n", " ")
            if line.strip():
                lines.append(line)
            return
        if t == "noteImage":
            cap = ((node.get("attrs") or {}).get("caption") or "").replace("\n", " ")
            if cap.strip():
                lines.append(cap)
            return
        for c in node.get("content") or []:
            walk(c)

    walk(doc)
    return "\n".join(lines)


def _encode_doc(doc) -> str:
    if doc is None:
        return ""
    if not isinstance(doc, dict):
        raise ValueError("doc must be an object")
    s = json.dumps(doc, separators=(",", ":"), ensure_ascii=False)
    if len(s) > _DOC:
        raise ValueError("note is too large")
    return s


def save_note(conn, uid: str, note_id: str, title: str, doc, base_rev: int,
              quota: Meter | None = None) -> tuple[str, dict | None]:
    """Content save. Returns ("ok", note) | ("conflict", server_note) | ("missing", None).
    A trashed note cannot be saved into (restore it first). Only GROWTH is checked
    against the quota, so a full account can always save a note smaller."""
    cur = conn.cursor()
    cur.execute("SELECT rev, deleted_at, size FROM notes WHERE id=? AND owner_id=?", (note_id, uid))
    r = cur.fetchone()
    if not r:
        return "missing", None
    if r["deleted_at"] is not None:
        return "missing", None
    if (r["rev"] or 0) != base_rev:
        return "conflict", get_note(conn, uid, note_id)
    body = _encode_doc(doc)
    title = (title or "").strip()[:_NAME]
    text = doc_text(doc)
    size = _size(title, body, text)
    grow = size - (r["size"] or 0)
    if quota is not None:
        quota.check(conn, add_bytes=grow)
    # The rev in the WHERE makes the check-and-write one statement, so two savers
    # racing past the SELECT above cannot both land (the loser reads back as a conflict).
    conn.execute(
        "UPDATE notes SET title=?, doc=?, body_text=?, size=?, rev=rev+1, updated_at=? "
        "WHERE id=? AND owner_id=? AND rev=?",
        (title, body, text, size, _now(), note_id, uid, base_rev),
    )
    conn.commit()
    note = get_note(conn, uid, note_id)
    if note is None:
        return "missing", None
    if note["rev"] != base_rev + 1:
        return "conflict", note
    if quota is not None:
        quota.charge(add_bytes=grow)
    return "ok", note


def update_note_meta(conn, uid: str, note_id: str, fields: dict) -> dict | None:
    """Move / pin / trash / restore. Deliberately does NOT bump rev or updated_at:
    organising a note is not editing it (Recent is 'last edited')."""
    cur = conn.cursor()
    cur.execute("SELECT folder_id, deleted_at FROM notes WHERE id=? AND owner_id=?", (note_id, uid))
    r = cur.fetchone()
    if not r:
        return None
    sets, args = [], []
    if "folder_id" in fields:
        fid = fields["folder_id"]
        if not _folder_exists(conn, uid, fid):
            raise ValueError("no such folder")
        sets.append("folder_id=?"); args.append(fid)
    if "pinned" in fields:
        sets.append("pinned=?"); args.append(1 if fields["pinned"] else 0)
    if "trashed" in fields:
        if fields["trashed"]:
            sets.append("deleted_at=?"); args.append(_now())
        else:
            sets.append("deleted_at=NULL")
            # Restoring into a folder that was deleted meanwhile lands at the top level.
            if "folder_id" not in fields and not _folder_exists(conn, uid, r["folder_id"]):
                sets.append("folder_id=NULL")
    if sets:
        conn.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id=? AND owner_id=?",
                     (*args, note_id, uid))
        conn.commit()
    return get_note(conn, uid, note_id)


def delete_note_forever(conn, uid: str, note_id: str) -> bool:
    """Only a TRASHED note can be deleted for good — one misclick never loses a note."""
    cur = conn.cursor()
    cur.execute("SELECT deleted_at FROM notes WHERE id=? AND owner_id=?", (note_id, uid))
    r = cur.fetchone()
    if not r or r["deleted_at"] is None:
        return False
    conn.execute("DELETE FROM notes WHERE id=? AND owner_id=?", (note_id, uid))
    conn.commit()
    return True


def empty_trash(conn, uid: str) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notes WHERE owner_id=? AND deleted_at IS NOT NULL", (uid,))
    n = cur.fetchone()[0]
    conn.execute("DELETE FROM notes WHERE owner_id=? AND deleted_at IS NOT NULL", (uid,))
    conn.commit()
    return n


# ── folder writes ────────────────────────────────────────────────────────────
def create_folder(conn, uid: str, parent_id, name: str, quota: Meter | None = None) -> dict:
    parents = _folder_parents(conn, uid)
    if parent_id is not None and parent_id not in parents:
        raise ValueError("no such folder")
    if _depth(parents, parent_id) >= MAX_DEPTH:
        raise ValueError("folders are nested too deeply")
    if quota is not None:
        quota.check(conn, add_folders=1)
    fid, now = _gen_id(), _now()
    name = _clean_name(name, "New folder")
    conn.execute(
        "INSERT INTO note_folders (id, owner_id, parent_id, name, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (fid, uid, parent_id, name, now, now),
    )
    conn.commit()
    if quota is not None:
        quota.charge(add_folders=1)
    return {"id": fid, "parent_id": parent_id, "name": name}


def update_folder(conn, uid: str, folder_id: str, fields: dict) -> dict | None:
    parents = _folder_parents(conn, uid)
    if folder_id not in parents:
        return None
    sets, args = [], []
    if "name" in fields:
        sets.append("name=?"); args.append(_clean_name(fields["name"], "Untitled folder"))
    if "parent_id" in fields:
        pid = fields["parent_id"]
        if pid is not None:
            if pid not in parents:
                raise ValueError("no such folder")
            if pid in _subtree(parents, folder_id):
                raise ValueError("a folder cannot move inside itself")
            # depth of the new parent + the height of the moved subtree
            if _depth(parents, pid) + _height(parents, folder_id) > MAX_DEPTH:
                raise ValueError("folders are nested too deeply")
        sets.append("parent_id=?"); args.append(pid)
    if sets:
        sets.append("updated_at=?"); args.append(_now())
        conn.execute(f"UPDATE note_folders SET {', '.join(sets)} WHERE id=? AND owner_id=?",
                     (*args, folder_id, uid))
        conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT id, parent_id, name FROM note_folders WHERE id=? AND owner_id=?", (folder_id, uid))
    r = cur.fetchone()
    return {"id": r["id"], "parent_id": r["parent_id"], "name": r["name"]}


def delete_folder(conn, uid: str, folder_id: str) -> int | None:
    """Delete a folder and its subfolders. Their notes go to the TRASH (keeping
    their folder id, so a restore falls back to the top level). Returns the number
    of notes trashed, or None if the folder does not exist."""
    parents = _folder_parents(conn, uid)
    if folder_id not in parents:
        return None
    sub = sorted(_subtree(parents, folder_id))
    marks = ",".join("?" * len(sub))
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM notes WHERE owner_id=? AND deleted_at IS NULL "
                f"AND folder_id IN ({marks})", (uid, *sub))
    n = cur.fetchone()[0]
    conn.execute(
        f"UPDATE notes SET deleted_at=? WHERE owner_id=? AND deleted_at IS NULL AND folder_id IN ({marks})",
        (_now(), uid, *sub),
    )
    conn.execute(f"DELETE FROM note_folders WHERE owner_id=? AND id IN ({marks})", (uid, *sub))
    conn.commit()
    return n


# ── images ───────────────────────────────────────────────────────────────────
def save_image(conn, uid: str, note_id: str, mime: str, data_b64: str, width: int = 0, height: int = 0,
               quota: Meter | None = None) -> dict:
    if mime not in _MAGIC:
        raise ValueError("unsupported image type")
    if len(data_b64) > _IMAGE_B64:
        raise ValueError("image is too large")
    try:
        raw = base64.b64decode(data_b64, validate=True)
    except (ValueError, TypeError):
        raise ValueError("image is not valid base64")
    if not raw or len(raw) > _IMAGE_BYTES:
        raise ValueError("image is too large")
    if not any(raw.startswith(m) for m in _MAGIC[mime]) or (mime == "image/webp" and raw[8:12] != b"WEBP"):
        raise ValueError("image data does not match its type")
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM notes WHERE id=? AND owner_id=?", (note_id, uid))
    if not cur.fetchone():
        raise ValueError("no such note")
    if quota is not None:
        quota.check(conn, add_bytes=len(raw))
    iid = _gen_id()
    conn.execute(
        "INSERT INTO note_images (id, owner_id, note_id, mime, width, height, bytes, data, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (iid, uid, note_id, mime, max(0, int(width)), max(0, int(height)), len(raw), data_b64, _now()),
    )
    conn.commit()
    if quota is not None:
        quota.charge(add_bytes=len(raw), add_images=1)
    return {"id": iid, "width": width, "height": height, "bytes": len(raw)}


def get_image(conn, uid: str, image_id: str) -> tuple[str, bytes] | None:
    cur = conn.cursor()
    cur.execute("SELECT mime, data FROM note_images WHERE id=? AND owner_id=?", (image_id, uid))
    r = cur.fetchone()
    if not r:
        return None
    return r["mime"], base64.b64decode(r["data"])


# ── search ───────────────────────────────────────────────────────────────────
SEARCH_MAX_Q = 200
SEARCH_LIMIT = 100
SNIPPETS_PER_NOTE = 3
_SNIP_SIDE = 40


def _find_all(text: str, q: str) -> list[int]:
    """Case-insensitive match offsets IN `text`. `lower()` is length-preserving for
    almost everything; where it is not (a handful of characters like 'İ'), that line
    falls back to a case-sensitive search so an offset can never point at the wrong
    character."""
    hay = text.lower()
    needle = q.lower()
    if len(hay) != len(text) or len(needle) != len(q):
        hay, needle = text, q
    out, i = [], hay.find(needle)
    while i != -1:
        out.append(i)
        i = hay.find(needle, i + max(1, len(needle)))
    return out


def _snippet(line: str, start: int, length: int) -> dict:
    a = max(0, start - _SNIP_SIDE)
    b = min(len(line), start + length + _SNIP_SIDE)
    # widen to word boundaries so a snippet does not open mid-word
    while a > 0 and line[a - 1] not in " \t":
        a -= 1
        if start - a > _SNIP_SIDE + 15:
            break
    text = ("…" if a > 0 else "") + line[a:b] + ("…" if b < len(line) else "")
    return {"text": text, "start": start - a + (1 if a > 0 else 0), "length": length}


def search_notes(conn, uid: str, query: str, folder_id: str | None = None) -> list[dict]:
    """Notes (not in the Trash) whose title or text contains `query`, case-
    insensitively. `folder_id` limits it to that folder AND every folder inside it.
    Each hit carries a match count and up to three snippets with the match offsets,
    so the client can highlight without ever rendering server text as HTML."""
    q = (query or "").strip()[:SEARCH_MAX_Q]
    if not q:
        return []
    args: list = [uid]
    where = "owner_id=? AND deleted_at IS NULL"
    if folder_id is not None:
        parents = _folder_parents(conn, uid)
        if folder_id not in parents:
            return []
        sub = sorted(_subtree(parents, folder_id))
        where += f" AND folder_id IN ({','.join('?' * len(sub))})"
        args += sub
    # SQL narrows only when the query is ASCII: sqlite's lower() folds ASCII alone,
    # so for anything else the exact filter below is the only one that is right.
    if q.isascii():
        where += " AND (instr(lower(title), ?) > 0 OR instr(lower(body_text), ?) > 0)"
        args += [q.lower(), q.lower()]
    cur = conn.cursor()
    cur.execute(f"SELECT id, folder_id, title, body_text, pinned, updated_at FROM notes WHERE {where}", args)
    hits = []
    for r in cur.fetchall():
        title = r["title"] or ""
        in_title = bool(_find_all(title, q))
        count, snippets = 0, []
        for line in (r["body_text"] or "").split("\n"):
            offs = _find_all(line, q)
            count += len(offs)
            for o in offs:
                if len(snippets) < SNIPPETS_PER_NOTE:
                    snippets.append(_snippet(line, o, len(q)))
        if not (in_title or count):
            continue
        hits.append({
            "id": r["id"], "folder_id": r["folder_id"], "title": title, "pinned": bool(r["pinned"]),
            "updated_at": r["updated_at"], "title_match": in_title, "count": count, "snippets": snippets,
        })
    # a title hit is the note you meant; after that, the most recently edited
    hits.sort(key=lambda h: (not h["title_match"], -(h["updated_at"] or 0)))
    return hits[:SEARCH_LIMIT]


# ── retention ────────────────────────────────────────────────────────────────
def sweep(conn, now: int | None = None, *, uid: str | None = None, grace: int = IMAGE_GRACE) -> dict:
    """Purge trash older than TRASH_DAYS, then images none of their OWNER's notes
    references (trashed notes included — a restore must get its screenshots back)
    once they are older than `grace`. With `uid`, only that account's rows. Image
    ids are 16 random chars, so `instr` on the doc text is an exact reference test
    in practice. `IS` rather than `=` keeps the pre-owner rows (both NULL) matched."""
    now = _now() if now is None else now
    own, own_args = ("AND owner_id=? ", (uid,)) if uid is not None else ("", ())
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM notes WHERE deleted_at IS NOT NULL AND deleted_at < ? {own}",
                (now - TRASH_DAYS * 86400, *own_args))
    trashed = cur.fetchone()[0]
    conn.execute(f"DELETE FROM notes WHERE deleted_at IS NOT NULL AND deleted_at < ? {own}",
                 (now - TRASH_DAYS * 86400, *own_args))
    orphan_sql = (
        f"FROM note_images WHERE created_at < ? {own}AND NOT EXISTS "
        "(SELECT 1 FROM notes WHERE notes.owner_id IS note_images.owner_id "
        "AND instr(notes.doc, note_images.id) > 0)"
    )
    cur.execute(f"SELECT COUNT(*) {orphan_sql}", (now - grace, *own_args))
    images = cur.fetchone()[0]
    conn.execute(f"DELETE {orphan_sql}", (now - grace, *own_args))
    conn.commit()
    forget_usage(uid)
    return {"notes": trashed, "images": images}


_last_sweep = 0


def maybe_sweep(conn) -> None:
    global _last_sweep
    now = _now()
    if now - _last_sweep < _SWEEP_INTERVAL:
        return
    _last_sweep = now
    try:
        sweep(conn, now)
    except Exception:  # noqa: BLE001 - housekeeping must never fail a user's request
        pass


# ── request models ───────────────────────────────────────────────────────────
class NoteCreate(BaseModel):
    folder_id: str | None = Field(default=None, max_length=_ID)
    title: str = Field(default="", max_length=_NAME)


class NoteSave(BaseModel):
    title: str = Field(default="", max_length=_NAME)
    doc: dict | None = None
    base_rev: int = 0


class NoteMeta(BaseModel):
    # Absent vs null matters (null = move to the top level), so the handler reads
    # model_fields_set rather than the values alone.
    folder_id: str | None = Field(default=None, max_length=_ID)
    pinned: bool | None = None
    trashed: bool | None = None


class FolderCreate(BaseModel):
    parent_id: str | None = Field(default=None, max_length=_ID)
    name: str = Field(default="", max_length=_NAME)


class FolderUpdate(BaseModel):
    parent_id: str | None = Field(default=None, max_length=_ID)
    name: str | None = Field(default=None, max_length=_NAME)


class ImageIn(BaseModel):
    note_id: str = Field(max_length=_ID)
    mime: str = Field(max_length=32)
    data: str = Field(max_length=_IMAGE_B64)
    width: int = Field(default=0, ge=0, le=20000)
    height: int = Field(default=0, ge=0, le=20000)


def _set_fields(model: BaseModel, names: tuple) -> dict:
    return {k: getattr(model, k) for k in names if k in model.model_fields_set}


# ── who may do what ──────────────────────────────────────────────────────────
def require_member(user: dict | None) -> dict:
    """The one gate: any signed-in account. Guests have no session, so no notebook."""
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="sign in to use Notes")
    return user


def owns_legacy_notes(user: dict) -> bool:
    """The account the pre-owner rows belong to: SITE_OWNER by name when it is set
    (an admin grant alone must not claim someone else's notebook), else an admin."""
    owner = site_owner_name()
    if owner:
        return bool(user.get("name")) and user["name"].casefold() == owner.casefold()
    return bool(user.get("is_admin"))


def meter_for(user: dict) -> Meter | None:
    """None = unmetered (the site owner and admins)."""
    return None if is_site_owner(user) else Meter(user["id"], user.get("name") or "")


def limit(user: dict, *limiters) -> None:
    """Charge one hit against each limiter for this account; 429 if any is spent."""
    uid = user["id"]
    for lim in limiters:
        if lim.exceeded(uid):
            alerts.alert("notes-rate", f"{user.get('name') or uid} is writing to Notes faster than "
                         f"the limit ({lim.max_hits} per {int(lim.window)}s); requests are refused.",
                         key=f"notes-rate:{uid}")
            raise HTTPException(status_code=429, detail="You're saving too fast. Wait a minute and try again.")
    for lim in limiters:
        lim.record(uid)


def _usage_view(conn, user: dict) -> dict:
    m = meter_for(user)
    u = (m or Meter(user["id"])).current(conn)
    return {"bytes": u["bytes"], "notes": u["notes"], "folders": u["folders"],
            "quota_bytes": m.quota_bytes if m else None,
            "max_notes": m.max_notes if m else None}


# ── route registration ───────────────────────────────────────────────────────
def _default_token_resolver(token: str | None = Query(default=None)) -> str | None:
    return token


def setup_notes(app, get_db_conn, get_user_by_session, token_resolver=None) -> None:
    """Create tables and register the /notes routes on `app`. Dependencies are
    injected from the composition root (the Books pattern) so this package never
    imports a game module."""
    conn = get_db_conn()
    try:
        init_notes_db(conn)
    finally:
        conn.close()

    resolve_token = token_resolver or _default_token_resolver
    claimed = {"done": False}

    def run(fn):
        conn = get_db_conn()
        try:
            return fn(conn)
        finally:
            conn.close()

    # Every route below takes this dependency; tests/test_notes.py walks the
    # registered routes and fails any /notes route that does not.
    def member(token: str | None = Depends(resolve_token)) -> dict:
        user = require_member(get_user_by_session(token) if token else None)
        if not claimed["done"] and owns_legacy_notes(user):
            run(lambda c: claim_unowned(c, user["id"]))
            claimed["done"] = True
        return user

    def bad(e: ValueError):
        if isinstance(e, QuotaError):
            raise HTTPException(status_code=413, detail=str(e))
        raise HTTPException(status_code=400, detail=str(e))

    writes = (_writes_minute, _writes_hour)

    @app.get("/notes/tree")
    def notes_tree(user: dict = Depends(member)):
        uid = user["id"]
        return {"ok": True, **run(lambda c: {**fetch_tree(c, uid), "usage": _usage_view(c, user)})}

    @app.get("/notes/search")
    def notes_search(q: str = Query(default="", max_length=SEARCH_MAX_Q * 2),
                     folder_id: str | None = Query(default=None, max_length=_ID),
                     user: dict = Depends(member)):
        limit(user, _searches_minute)
        return {"ok": True, "results": run(lambda c: search_notes(c, user["id"], q, folder_id or None))}

    @app.post("/notes/note")
    def notes_create(payload: NoteCreate, user: dict = Depends(member)):
        limit(user, *writes)

        def go(c):
            maybe_sweep(c)
            return create_note(c, user["id"], payload.folder_id, payload.title, quota=meter_for(user))
        try:
            return {"ok": True, "note": run(go)}
        except ValueError as e:
            bad(e)

    @app.get("/notes/note/{note_id}")
    def notes_get(note_id: str, user: dict = Depends(member)):
        note = run(lambda c: get_note(c, user["id"], note_id))
        if note is None:
            raise HTTPException(status_code=404, detail="no such note")
        return {"ok": True, "note": note}

    @app.put("/notes/note/{note_id}")
    def notes_save(note_id: str, payload: NoteSave, user: dict = Depends(member)):
        limit(user, *writes)
        try:
            status, note = run(lambda c: save_note(c, user["id"], note_id, payload.title, payload.doc,
                                                   payload.base_rev, quota=meter_for(user)))
        except ValueError as e:
            bad(e)
        if status == "missing":
            raise HTTPException(status_code=404, detail="no such note")
        if status == "conflict":
            return JSONResponse(status_code=409, content={"ok": False, "conflict": True, "note": note})
        return {"ok": True, "note": note}

    @app.post("/notes/note/{note_id}/meta")
    def notes_meta(note_id: str, payload: NoteMeta, user: dict = Depends(member)):
        limit(user, *writes)
        fields = _set_fields(payload, ("folder_id", "pinned", "trashed"))
        fields = {k: v for k, v in fields.items() if not (k in ("pinned", "trashed") and v is None)}
        try:
            note = run(lambda c: update_note_meta(c, user["id"], note_id, fields))
        except ValueError as e:
            bad(e)
        if note is None:
            raise HTTPException(status_code=404, detail="no such note")
        return {"ok": True, "note": note}

    @app.delete("/notes/note/{note_id}")
    def notes_delete(note_id: str, user: dict = Depends(member)):
        limit(user, *writes)
        uid = user["id"]

        def go(c):
            gone = delete_note_forever(c, uid, note_id)
            if gone:
                sweep(c, uid=uid, grace=EMPTY_TRASH_GRACE)
            return gone
        if not run(go):
            raise HTTPException(status_code=400, detail="only a note in the Trash can be deleted")
        return {"ok": True}

    @app.post("/notes/trash/empty")
    def notes_empty_trash(user: dict = Depends(member)):
        limit(user, *writes)
        uid = user["id"]

        def go(c):
            n = empty_trash(c, uid)
            sweep(c, uid=uid, grace=EMPTY_TRASH_GRACE)
            return n
        return {"ok": True, "deleted": run(go)}

    @app.post("/notes/folder")
    def folders_create(payload: FolderCreate, user: dict = Depends(member)):
        limit(user, *writes)
        try:
            return {"ok": True, "folder": run(lambda c: create_folder(
                c, user["id"], payload.parent_id, payload.name, quota=meter_for(user)))}
        except ValueError as e:
            bad(e)

    @app.post("/notes/folder/{folder_id}")
    def folders_update(folder_id: str, payload: FolderUpdate, user: dict = Depends(member)):
        limit(user, *writes)
        fields = _set_fields(payload, ("parent_id", "name"))
        try:
            folder = run(lambda c: update_folder(c, user["id"], folder_id, fields))
        except ValueError as e:
            bad(e)
        if folder is None:
            raise HTTPException(status_code=404, detail="no such folder")
        return {"ok": True, "folder": folder}

    @app.delete("/notes/folder/{folder_id}")
    def folders_delete(folder_id: str, user: dict = Depends(member)):
        limit(user, *writes)
        n = run(lambda c: delete_folder(c, user["id"], folder_id))
        if n is None:
            raise HTTPException(status_code=404, detail="no such folder")
        return {"ok": True, "trashed": n}

    @app.post("/notes/image")
    def images_upload(payload: ImageIn, user: dict = Depends(member)):
        limit(user, *writes, _uploads_hour)
        try:
            img = run(lambda c: save_image(c, user["id"], payload.note_id, payload.mime, payload.data,
                                           payload.width, payload.height, quota=meter_for(user)))
        except ValueError as e:
            bad(e)
        return {"ok": True, "image": img}

    @app.get("/notes/image/{image_id}")
    def images_get(image_id: str, user: dict = Depends(member)):
        got = run(lambda c: get_image(c, user["id"], image_id))
        if got is None:
            raise HTTPException(status_code=404, detail="no such image")
        mime, raw = got
        # An image id never changes content, so the browser may keep it forever —
        # but only privately (it is a personal note, never a shared cache's).
        return Response(content=raw, media_type=mime,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
