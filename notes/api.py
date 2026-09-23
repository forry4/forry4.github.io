"""Notes — a private notebook for the site owner.

Nested folders of notes; a note is a flowing rich-text document whose body is the
editor's (TipTap/ProseMirror) JSON, stored verbatim as TEXT. Screenshots are
separate rows referenced from the document by id, so saving a note never re-sends
its images.

EVERYTHING IS OWNER-ONLY, READS INCLUDED. Unlike Books (public read, owner write)
these are personal notes, so every route resolves the caller and refuses anyone
who is not `core.auth.is_site_owner` — the frontend hiding the Extras tile is a
convenience, never the gate.

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
    never deleted directly: a sweep drops any image no note references once it is
    IMAGE_GRACE old, which keeps editor undo of an image delete working and lets an
    image pasted into a second note survive the first note's deletion.
  * libsql has no `cur.rowcount`, so every "did it exist" is a SELECT first.

The pure functions take a connection so they are unit-tested on `:memory:`.
"""
import base64
import json
import secrets
import string
import time

from fastapi import Depends, HTTPException, Query, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from core.auth import is_site_owner


# ── limits ───────────────────────────────────────────────────────────────────
_ID = 32
_NAME = 200                 # folder name / note title
_DOC = 2_000_000            # editor JSON (images are references, so this is text only)
_IMAGE_BYTES = 3_000_000    # decoded; the client downscales to <=1920px WebP first
_IMAGE_B64 = (_IMAGE_BYTES * 4) // 3 + 8
MAX_DEPTH = 12              # folder nesting depth
TRASH_DAYS = 30
IMAGE_GRACE = 7 * 86400
_SWEEP_INTERVAL = 3600

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
    # body_text: the note's PLAIN text (one block per line, image captions included),
    # written on every save. Search reads this, never `doc` — in the editor JSON a
    # bolded word is its own text node, so "reads 3:15" is not a substring of the doc.
    # Added by ALTER for tables created before search existed; it raises once the
    # column is there, on both sqlite and libsql.
    try:
        cur.execute("ALTER TABLE notes ADD COLUMN body_text TEXT")
    except Exception:  # noqa: BLE001 - "duplicate column" is the expected steady state
        pass
    cur.execute("SELECT id, doc FROM notes WHERE body_text IS NULL")
    for r in cur.fetchall():
        try:
            doc = json.loads(r["doc"]) if r["doc"] else None
        except ValueError:
            doc = None
        conn.execute("UPDATE notes SET body_text=? WHERE id=?", (doc_text(doc), r["id"]))
    conn.commit()


# ── helpers ──────────────────────────────────────────────────────────────────
def _folder_parents(conn) -> dict:
    cur = conn.cursor()
    cur.execute("SELECT id, parent_id FROM note_folders")
    return {r["id"]: r["parent_id"] for r in cur.fetchall()}


def _folder_exists(conn, folder_id) -> bool:
    if folder_id is None:
        return True
    return folder_id in _folder_parents(conn)


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


def _note_meta(r) -> dict:
    return {
        "id": r["id"], "folder_id": r["folder_id"], "title": r["title"] or "",
        "pinned": bool(r["pinned"]), "created_at": r["created_at"],
        "updated_at": r["updated_at"], "deleted_at": r["deleted_at"],
    }


_META_COLS = "id, folder_id, title, pinned, created_at, updated_at, deleted_at"


# ── reads ────────────────────────────────────────────────────────────────────
def fetch_tree(conn) -> dict:
    """Folders + note METADATA (no bodies): enough to draw the sidebar, Pinned,
    Recent and Trash without downloading every document."""
    cur = conn.cursor()
    cur.execute("SELECT id, parent_id, name FROM note_folders ORDER BY name COLLATE NOCASE")
    folders = [{"id": r["id"], "parent_id": r["parent_id"], "name": r["name"]} for r in cur.fetchall()]
    cur.execute(f"SELECT {_META_COLS} FROM notes ORDER BY updated_at DESC")
    notes = [_note_meta(r) for r in cur.fetchall()]
    return {"folders": folders, "notes": notes}


def get_note(conn, note_id: str) -> dict | None:
    cur = conn.cursor()
    cur.execute(f"SELECT {_META_COLS}, doc, rev FROM notes WHERE id=?", (note_id,))
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
def create_note(conn, folder_id=None, title: str = "") -> dict:
    if not _folder_exists(conn, folder_id):
        folder_id = None
    nid, now = _gen_id(), _now()
    conn.execute(
        "INSERT INTO notes (id, folder_id, title, doc, rev, pinned, created_at, updated_at) "
        "VALUES (?, ?, ?, '', 0, 0, ?, ?)",
        (nid, folder_id, (title or "").strip()[:_NAME], now, now),
    )
    conn.commit()
    return get_note(conn, nid)


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


def save_note(conn, note_id: str, title: str, doc, base_rev: int) -> tuple[str, dict | None]:
    """Content save. Returns ("ok", note) | ("conflict", server_note) | ("missing", None).
    A trashed note cannot be saved into (restore it first)."""
    cur = conn.cursor()
    cur.execute("SELECT rev, deleted_at FROM notes WHERE id=?", (note_id,))
    r = cur.fetchone()
    if not r:
        return "missing", None
    if r["deleted_at"] is not None:
        return "missing", None
    if (r["rev"] or 0) != base_rev:
        return "conflict", get_note(conn, note_id)
    body = _encode_doc(doc)
    # The rev in the WHERE makes the check-and-write one statement, so two savers
    # racing past the SELECT above cannot both land (the loser reads back as a conflict).
    conn.execute(
        "UPDATE notes SET title=?, doc=?, body_text=?, rev=rev+1, updated_at=? WHERE id=? AND rev=?",
        ((title or "").strip()[:_NAME], body, doc_text(doc), _now(), note_id, base_rev),
    )
    conn.commit()
    note = get_note(conn, note_id)
    if note is None:
        return "missing", None
    if note["rev"] != base_rev + 1:
        return "conflict", note
    return "ok", note


def update_note_meta(conn, note_id: str, fields: dict) -> dict | None:
    """Move / pin / trash / restore. Deliberately does NOT bump rev or updated_at:
    organising a note is not editing it (Recent is 'last edited')."""
    cur = conn.cursor()
    cur.execute("SELECT folder_id, deleted_at FROM notes WHERE id=?", (note_id,))
    r = cur.fetchone()
    if not r:
        return None
    sets, args = [], []
    if "folder_id" in fields:
        fid = fields["folder_id"]
        if not _folder_exists(conn, fid):
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
            if "folder_id" not in fields and not _folder_exists(conn, r["folder_id"]):
                sets.append("folder_id=NULL")
    if sets:
        conn.execute(f"UPDATE notes SET {', '.join(sets)} WHERE id=?", (*args, note_id))
        conn.commit()
    return get_note(conn, note_id)


def delete_note_forever(conn, note_id: str) -> bool:
    """Only a TRASHED note can be deleted for good — one misclick never loses a note."""
    cur = conn.cursor()
    cur.execute("SELECT deleted_at FROM notes WHERE id=?", (note_id,))
    r = cur.fetchone()
    if not r or r["deleted_at"] is None:
        return False
    conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    conn.commit()
    return True


def empty_trash(conn) -> int:
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notes WHERE deleted_at IS NOT NULL")
    n = cur.fetchone()[0]
    conn.execute("DELETE FROM notes WHERE deleted_at IS NOT NULL")
    conn.commit()
    return n


# ── folder writes ────────────────────────────────────────────────────────────
def create_folder(conn, parent_id, name: str) -> dict:
    parents = _folder_parents(conn)
    if parent_id is not None and parent_id not in parents:
        raise ValueError("no such folder")
    if _depth(parents, parent_id) >= MAX_DEPTH:
        raise ValueError("folders are nested too deeply")
    fid, now = _gen_id(), _now()
    name = _clean_name(name, "New folder")
    conn.execute(
        "INSERT INTO note_folders (id, parent_id, name, created_at, updated_at) VALUES (?, ?, ?, ?, ?)",
        (fid, parent_id, name, now, now),
    )
    conn.commit()
    return {"id": fid, "parent_id": parent_id, "name": name}


def update_folder(conn, folder_id: str, fields: dict) -> dict | None:
    parents = _folder_parents(conn)
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
        conn.execute(f"UPDATE note_folders SET {', '.join(sets)} WHERE id=?", (*args, folder_id))
        conn.commit()
    cur = conn.cursor()
    cur.execute("SELECT id, parent_id, name FROM note_folders WHERE id=?", (folder_id,))
    r = cur.fetchone()
    return {"id": r["id"], "parent_id": r["parent_id"], "name": r["name"]}


def delete_folder(conn, folder_id: str) -> int | None:
    """Delete a folder and its subfolders. Their notes go to the TRASH (keeping
    their folder id, so a restore falls back to the top level). Returns the number
    of notes trashed, or None if the folder does not exist."""
    parents = _folder_parents(conn)
    if folder_id not in parents:
        return None
    sub = sorted(_subtree(parents, folder_id))
    marks = ",".join("?" * len(sub))
    cur = conn.cursor()
    cur.execute(f"SELECT COUNT(*) FROM notes WHERE deleted_at IS NULL AND folder_id IN ({marks})", sub)
    n = cur.fetchone()[0]
    conn.execute(
        f"UPDATE notes SET deleted_at=? WHERE deleted_at IS NULL AND folder_id IN ({marks})",
        (_now(), *sub),
    )
    conn.execute(f"DELETE FROM note_folders WHERE id IN ({marks})", sub)
    conn.commit()
    return n


# ── images ───────────────────────────────────────────────────────────────────
def save_image(conn, note_id: str, mime: str, data_b64: str, width: int = 0, height: int = 0) -> dict:
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
    cur.execute("SELECT 1 FROM notes WHERE id=?", (note_id,))
    if not cur.fetchone():
        raise ValueError("no such note")
    iid = _gen_id()
    conn.execute(
        "INSERT INTO note_images (id, note_id, mime, width, height, bytes, data, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (iid, note_id, mime, max(0, int(width)), max(0, int(height)), len(raw), data_b64, _now()),
    )
    conn.commit()
    return {"id": iid, "width": width, "height": height, "bytes": len(raw)}


def get_image(conn, image_id: str) -> tuple[str, bytes] | None:
    cur = conn.cursor()
    cur.execute("SELECT mime, data FROM note_images WHERE id=?", (image_id,))
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


def search_notes(conn, query: str, folder_id: str | None = None) -> list[dict]:
    """Notes (not in the Trash) whose title or text contains `query`, case-
    insensitively. `folder_id` limits it to that folder AND every folder inside it.
    Each hit carries a match count and up to three snippets with the match offsets,
    so the client can highlight without ever rendering server text as HTML."""
    q = (query or "").strip()[:SEARCH_MAX_Q]
    if not q:
        return []
    args: list = []
    where = "deleted_at IS NULL"
    if folder_id is not None:
        parents = _folder_parents(conn)
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
def sweep(conn, now: int | None = None) -> dict:
    """Purge trash older than TRASH_DAYS, then images no note references (trashed
    notes included — a restore must get its screenshots back) once they are older
    than IMAGE_GRACE. Image ids are 16 random chars, so `instr` on the doc text is
    an exact reference test in practice."""
    now = _now() if now is None else now
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM notes WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                (now - TRASH_DAYS * 86400,))
    trashed = cur.fetchone()[0]
    conn.execute("DELETE FROM notes WHERE deleted_at IS NOT NULL AND deleted_at < ?",
                 (now - TRASH_DAYS * 86400,))
    orphan_sql = (
        "FROM note_images WHERE created_at < ? AND NOT EXISTS "
        "(SELECT 1 FROM notes WHERE instr(notes.doc, note_images.id) > 0)"
    )
    cur.execute(f"SELECT COUNT(*) {orphan_sql}", (now - IMAGE_GRACE,))
    images = cur.fetchone()[0]
    conn.execute(f"DELETE {orphan_sql}", (now - IMAGE_GRACE,))
    conn.commit()
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


# ── route registration ───────────────────────────────────────────────────────
def require_owner(user: dict | None) -> dict:
    """The one gate: 401 for no session, 403 for anyone who is not the site owner."""
    if not user or not user.get("id"):
        raise HTTPException(status_code=401, detail="sign in")
    if not is_site_owner(user):
        raise HTTPException(status_code=403, detail="these notes are private")
    return user


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

    # Every route below takes this dependency; tests/test_notes.py walks the
    # registered routes and fails any /notes route that does not.
    def owner(token: str | None = Depends(resolve_token)) -> dict:
        return require_owner(get_user_by_session(token) if token else None)

    def run(fn):
        conn = get_db_conn()
        try:
            return fn(conn)
        finally:
            conn.close()

    def bad(e: ValueError):
        raise HTTPException(status_code=400, detail=str(e))

    @app.get("/notes/tree")
    def notes_tree(_: dict = Depends(owner)):
        return {"ok": True, **run(fetch_tree)}

    @app.get("/notes/search")
    def notes_search(q: str = Query(default="", max_length=SEARCH_MAX_Q * 2),
                     folder_id: str | None = Query(default=None, max_length=_ID),
                     _: dict = Depends(owner)):
        return {"ok": True, "results": run(lambda c: search_notes(c, q, folder_id or None))}

    @app.post("/notes/note")
    def notes_create(payload: NoteCreate, _: dict = Depends(owner)):
        def go(c):
            maybe_sweep(c)
            return create_note(c, payload.folder_id, payload.title)
        return {"ok": True, "note": run(go)}

    @app.get("/notes/note/{note_id}")
    def notes_get(note_id: str, _: dict = Depends(owner)):
        note = run(lambda c: get_note(c, note_id))
        if note is None:
            raise HTTPException(status_code=404, detail="no such note")
        return {"ok": True, "note": note}

    @app.put("/notes/note/{note_id}")
    def notes_save(note_id: str, payload: NoteSave, _: dict = Depends(owner)):
        try:
            status, note = run(lambda c: save_note(c, note_id, payload.title, payload.doc, payload.base_rev))
        except ValueError as e:
            bad(e)
        if status == "missing":
            raise HTTPException(status_code=404, detail="no such note")
        if status == "conflict":
            return JSONResponse(status_code=409, content={"ok": False, "conflict": True, "note": note})
        return {"ok": True, "note": note}

    @app.post("/notes/note/{note_id}/meta")
    def notes_meta(note_id: str, payload: NoteMeta, _: dict = Depends(owner)):
        fields = _set_fields(payload, ("folder_id", "pinned", "trashed"))
        fields = {k: v for k, v in fields.items() if not (k in ("pinned", "trashed") and v is None)}
        try:
            note = run(lambda c: update_note_meta(c, note_id, fields))
        except ValueError as e:
            bad(e)
        if note is None:
            raise HTTPException(status_code=404, detail="no such note")
        return {"ok": True, "note": note}

    @app.delete("/notes/note/{note_id}")
    def notes_delete(note_id: str, _: dict = Depends(owner)):
        if not run(lambda c: delete_note_forever(c, note_id)):
            raise HTTPException(status_code=400, detail="only a note in the Trash can be deleted")
        return {"ok": True}

    @app.post("/notes/trash/empty")
    def notes_empty_trash(_: dict = Depends(owner)):
        return {"ok": True, "deleted": run(empty_trash)}

    @app.post("/notes/folder")
    def folders_create(payload: FolderCreate, _: dict = Depends(owner)):
        try:
            return {"ok": True, "folder": run(lambda c: create_folder(c, payload.parent_id, payload.name))}
        except ValueError as e:
            bad(e)

    @app.post("/notes/folder/{folder_id}")
    def folders_update(folder_id: str, payload: FolderUpdate, _: dict = Depends(owner)):
        fields = _set_fields(payload, ("parent_id", "name"))
        try:
            folder = run(lambda c: update_folder(c, folder_id, fields))
        except ValueError as e:
            bad(e)
        if folder is None:
            raise HTTPException(status_code=404, detail="no such folder")
        return {"ok": True, "folder": folder}

    @app.delete("/notes/folder/{folder_id}")
    def folders_delete(folder_id: str, _: dict = Depends(owner)):
        n = run(lambda c: delete_folder(c, folder_id))
        if n is None:
            raise HTTPException(status_code=404, detail="no such folder")
        return {"ok": True, "trashed": n}

    @app.post("/notes/image")
    def images_upload(payload: ImageIn, _: dict = Depends(owner)):
        try:
            img = run(lambda c: save_image(c, payload.note_id, payload.mime, payload.data,
                                           payload.width, payload.height))
        except ValueError as e:
            bad(e)
        return {"ok": True, "image": img}

    @app.get("/notes/image/{image_id}")
    def images_get(image_id: str, _: dict = Depends(owner)):
        got = run(lambda c: get_image(c, image_id))
        if got is None:
            raise HTTPException(status_code=404, detail="no such image")
        mime, raw = got
        # An image id never changes content, so the browser may keep it forever —
        # but only privately (it is a personal note, never a shared cache's).
        return Response(content=raw, media_type=mime,
                        headers={"Cache-Control": "private, max-age=31536000, immutable"})
