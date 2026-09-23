"""Tests for the Notes feature (notes/api.py).

The pure functions run against a real on-disk sqlite DB through core.db's _Conn
wrapper (the same shape prod uses). Routes are exercised by calling the
registered endpoints directly — the repo has no httpx/TestClient — and the owner
gate is held STRUCTURALLY: every registered /notes route must depend on it, so a
route added later without the gate fails here rather than shipping public.
"""
import base64
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException

from core.db import _Conn
from notes import api as N

OWNER = {"id": "u_owner", "name": "forrest", "is_admin": True}
OTHER = {"id": "u_other", "name": "someone", "is_admin": False}

# Smallest valid headers for each accepted type (the magic-byte check reads only these).
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture()
def db_path(tmp_path):
    return str(tmp_path / "notes.db")


@pytest.fixture()
def get_conn(db_path):
    def make():
        c = sqlite3.connect(db_path, check_same_thread=False)
        return _Conn(c)
    return make


@pytest.fixture()
def conn(get_conn):
    c = get_conn()
    N.init_notes_db(c)
    yield c
    c.close()


@pytest.fixture()
def app(get_conn, monkeypatch):
    monkeypatch.delenv("SITE_OWNER", raising=False)
    a = FastAPI()
    N.setup_notes(a, get_conn, lambda token: None)
    return a


def _endpoint(app, method: str, path: str):
    for r in app.routes:
        if getattr(r, "path", None) == path and method in getattr(r, "methods", ()):
            return r.endpoint
    raise AssertionError(f"no route {method} {path}")


# ── the owner gate ───────────────────────────────────────────────────────────
def _dep_names(dependant) -> set:
    out = set()
    for d in dependant.dependencies:
        out.add(getattr(d.call, "__name__", ""))
        out |= _dep_names(d)
    return out


def _ungated(app) -> list:
    return [
        f"{sorted(r.methods)} {r.path}"
        for r in app.routes
        if getattr(r, "path", "").startswith("/notes") and "owner" not in _dep_names(r.dependant)
    ]


def test_every_notes_route_requires_the_owner(app):
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/notes")]
    assert len(routes) >= 12, "the route walk found too few routes to mean anything"
    assert _ungated(app) == []


def test_the_route_walk_catches_an_ungated_route(app):
    @app.get("/notes/leak")
    def leak():
        return {}
    assert _ungated(app) == ["['GET'] /notes/leak"]


def test_require_owner(monkeypatch):
    monkeypatch.delenv("SITE_OWNER", raising=False)
    for who, code in ((None, 401), ({}, 401), (OTHER, 403), ({"id": "g", "name": "guest"}, 403)):
        with pytest.raises(HTTPException) as e:
            N.require_owner(who)
        assert e.value.status_code == code
    assert N.require_owner(OWNER) is OWNER
    # SITE_OWNER by name, case-insensitively, without an admin grant
    monkeypatch.setenv("SITE_OWNER", "Forrest")
    assert N.require_owner({"id": "x", "name": "forrest"})


def test_owner_dependency_resolves_the_session(get_conn):
    a = FastAPI()
    sessions = {"tok_owner": OWNER, "tok_other": OTHER}
    N.setup_notes(a, get_conn, sessions.get)
    route = next(r for r in a.routes if getattr(r, "path", "") == "/notes/tree")
    owner_dep = next(d.call for d in route.dependant.dependencies if d.call.__name__ == "owner")
    assert owner_dep(token="tok_owner") is OWNER
    for tok, code in (("tok_other", 403), (None, 401), ("bogus", 401)):
        with pytest.raises(HTTPException) as e:
            owner_dep(token=tok)
        assert e.value.status_code == code


# ── notes ────────────────────────────────────────────────────────────────────
def _doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def test_create_save_and_read_back(conn):
    n = N.create_note(conn, None, "Library")
    assert n["rev"] == 0 and n["doc"] is None and n["title"] == "Library"
    status, saved = N.save_note(conn, n["id"], "Library clue", _doc("the clock reads 3"), 0)
    assert status == "ok" and saved["rev"] == 1
    got = N.get_note(conn, n["id"])
    assert got["title"] == "Library clue" and got["doc"] == _doc("the clock reads 3")


def test_stale_rev_is_a_conflict_and_keeps_the_server_copy(conn):
    n = N.create_note(conn)
    assert N.save_note(conn, n["id"], "A", _doc("tab one"), 0)[0] == "ok"
    status, server = N.save_note(conn, n["id"], "B", _doc("tab two"), 0)
    assert status == "conflict"
    assert server["doc"] == _doc("tab one") and server["rev"] == 1
    assert N.get_note(conn, n["id"])["title"] == "A"


def test_organising_does_not_bump_rev_or_recent(conn):
    f = N.create_folder(conn, None, "Rooms")
    n = N.create_note(conn)
    N.save_note(conn, n["id"], "t", _doc("x"), 0)
    before = N.get_note(conn, n["id"])
    N.update_note_meta(conn, n["id"], {"folder_id": f["id"], "pinned": True})
    after = N.get_note(conn, n["id"])
    assert after["folder_id"] == f["id"] and after["pinned"] is True
    assert after["rev"] == before["rev"] and after["updated_at"] == before["updated_at"]
    # an open tab based on that rev can still save
    assert N.save_note(conn, n["id"], "t", _doc("y"), before["rev"])[0] == "ok"


def test_meta_move_to_missing_folder_is_rejected(conn):
    n = N.create_note(conn)
    with pytest.raises(ValueError):
        N.update_note_meta(conn, n["id"], {"folder_id": "nope"})


def test_trash_restore_and_delete_forever(conn):
    n = N.create_note(conn, None, "keep me")
    assert N.delete_note_forever(conn, n["id"]) is False  # not trashed yet
    N.update_note_meta(conn, n["id"], {"trashed": True})
    assert N.get_note(conn, n["id"])["deleted_at"] is not None
    assert N.save_note(conn, n["id"], "x", None, 0)[0] == "missing"  # no editing in the trash
    N.update_note_meta(conn, n["id"], {"trashed": False})
    assert N.get_note(conn, n["id"])["deleted_at"] is None
    N.update_note_meta(conn, n["id"], {"trashed": True})
    assert N.delete_note_forever(conn, n["id"]) is True
    assert N.get_note(conn, n["id"]) is None


def test_empty_trash_only_removes_trashed(conn):
    a, b = N.create_note(conn), N.create_note(conn)
    N.update_note_meta(conn, a["id"], {"trashed": True})
    assert N.empty_trash(conn) == 1
    assert N.get_note(conn, a["id"]) is None and N.get_note(conn, b["id"]) is not None


def test_doc_must_be_an_object_and_is_capped(conn, monkeypatch):
    n = N.create_note(conn)
    with pytest.raises(ValueError):
        N.save_note(conn, n["id"], "t", ["not", "a", "doc"], 0)
    monkeypatch.setattr(N, "_DOC", 50)
    with pytest.raises(ValueError):
        N.save_note(conn, n["id"], "t", _doc("x" * 100), 0)


def test_title_is_capped(conn):
    n = N.create_note(conn)
    N.save_note(conn, n["id"], "x" * 500, None, 0)
    assert len(N.get_note(conn, n["id"])["title"]) == N._NAME


# ── folders ──────────────────────────────────────────────────────────────────
def test_nested_folders_and_tree(conn):
    top = N.create_folder(conn, None, "Blue Prince")
    sub = N.create_folder(conn, top["id"], "Rooms")
    n = N.create_note(conn, sub["id"], "Library")
    tree = N.fetch_tree(conn)
    assert {f["id"]: f["parent_id"] for f in tree["folders"]} == {top["id"]: None, sub["id"]: top["id"]}
    assert tree["notes"][0]["id"] == n["id"] and "doc" not in tree["notes"][0]


def test_folder_cannot_move_inside_itself(conn):
    a = N.create_folder(conn, None, "a")
    b = N.create_folder(conn, a["id"], "b")
    c = N.create_folder(conn, b["id"], "c")
    for target in (a["id"], b["id"], c["id"]):
        with pytest.raises(ValueError):
            N.update_folder(conn, a["id"], {"parent_id": target})
    # moving a leaf up to the top level is fine
    assert N.update_folder(conn, c["id"], {"parent_id": None})["parent_id"] is None


def test_folder_depth_cap(conn, monkeypatch):
    monkeypatch.setattr(N, "MAX_DEPTH", 3)
    a = N.create_folder(conn, None, "a")
    b = N.create_folder(conn, a["id"], "b")
    c = N.create_folder(conn, b["id"], "c")
    with pytest.raises(ValueError):
        N.create_folder(conn, c["id"], "d")
    x = N.create_folder(conn, None, "x")
    y = N.create_folder(conn, x["id"], "y")
    # x (height 2) under b (depth 2) would be 4 deep
    with pytest.raises(ValueError):
        N.update_folder(conn, x["id"], {"parent_id": b["id"]})
    # y (height 1) under b fits exactly
    assert N.update_folder(conn, y["id"], {"parent_id": b["id"]})["parent_id"] == b["id"]


def test_rename_folder_blank_falls_back(conn):
    f = N.create_folder(conn, None, "  ")
    assert f["name"] == "New folder"
    assert N.update_folder(conn, f["id"], {"name": "Clues"})["name"] == "Clues"


def test_delete_folder_trashes_its_whole_subtree(conn):
    top = N.create_folder(conn, None, "top")
    sub = N.create_folder(conn, top["id"], "sub")
    n1 = N.create_note(conn, top["id"])
    n2 = N.create_note(conn, sub["id"])
    keep = N.create_note(conn, None)
    assert N.delete_folder(conn, top["id"]) == 2
    assert N.fetch_tree(conn)["folders"] == []
    assert N.get_note(conn, n1["id"])["deleted_at"] is not None
    assert N.get_note(conn, n2["id"])["deleted_at"] is not None
    assert N.get_note(conn, keep["id"])["deleted_at"] is None
    # restoring a note whose folder is gone lands it at the top level
    assert N.update_note_meta(conn, n2["id"], {"trashed": False})["folder_id"] is None
    assert N.delete_folder(conn, "gone") is None


# ── images ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mime,raw", [("image/png", PNG), ("image/webp", WEBP), ("image/jpeg", JPEG)])
def test_image_round_trip(conn, mime, raw):
    n = N.create_note(conn)
    img = N.save_image(conn, n["id"], mime, _b64(raw), 10, 20)
    assert N.get_image(conn, img["id"]) == (mime, raw)


def test_image_rejections(conn, monkeypatch):
    n = N.create_note(conn)
    bad = [
        ("image/svg+xml", _b64(b"<svg/>")),          # not an accepted type
        ("image/png", _b64(JPEG)),                   # bytes do not match the type
        ("image/webp", _b64(b"RIFF\x00\x00\x00\x00AVI ")),  # RIFF but not WEBP
        ("image/png", "not base64!!"),
    ]
    for mime, data in bad:
        with pytest.raises(ValueError):
            N.save_image(conn, n["id"], mime, data)
    with pytest.raises(ValueError):
        N.save_image(conn, "no-such-note", "image/png", _b64(PNG))
    monkeypatch.setattr(N, "_IMAGE_BYTES", 10)
    with pytest.raises(ValueError):
        N.save_image(conn, n["id"], "image/png", _b64(PNG))


def _image_node(iid: str) -> dict:
    return {"type": "doc", "content": [{"type": "noteImage", "attrs": {"imageId": iid, "width": "full"}}]}


def test_sweep_keeps_referenced_and_young_images(conn):
    n = N.create_note(conn)
    used = N.save_image(conn, n["id"], "image/png", _b64(PNG))["id"]
    orphan = N.save_image(conn, n["id"], "image/png", _b64(PNG))["id"]
    N.save_note(conn, n["id"], "t", _image_node(used), 0)
    now = N._now()
    assert N.sweep(conn, now)["images"] == 0  # both inside the grace window
    later = now + N.IMAGE_GRACE + 1
    assert N.sweep(conn, later)["images"] == 1
    assert N.get_image(conn, used) is not None and N.get_image(conn, orphan) is None


def test_sweep_keeps_images_of_trashed_notes_until_purged(conn):
    n = N.create_note(conn)
    iid = N.save_image(conn, n["id"], "image/png", _b64(PNG))["id"]
    N.save_note(conn, n["id"], "t", _image_node(iid), 0)
    N.update_note_meta(conn, n["id"], {"trashed": True})
    now = N._now()
    out = N.sweep(conn, now + N.IMAGE_GRACE + 1)
    assert out == {"notes": 0, "images": 0}
    out = N.sweep(conn, now + N.TRASH_DAYS * 86400 + 1)
    assert out == {"notes": 1, "images": 1}


# ── the routes, end to end ───────────────────────────────────────────────────
def test_routes_round_trip(app):
    create = _endpoint(app, "POST", "/notes/note")
    save = _endpoint(app, "PUT", "/notes/note/{note_id}")
    meta = _endpoint(app, "POST", "/notes/note/{note_id}/meta")
    tree = _endpoint(app, "GET", "/notes/tree")
    mkfolder = _endpoint(app, "POST", "/notes/folder")
    upload = _endpoint(app, "POST", "/notes/image")
    image = _endpoint(app, "GET", "/notes/image/{image_id}")

    f = mkfolder(N.FolderCreate(name="Blue Prince"), _=OWNER)["folder"]
    n = create(N.NoteCreate(folder_id=f["id"], title="Parlor"), _=OWNER)["note"]
    ok = save(n["id"], N.NoteSave(title="Parlor", doc=_doc("three boxes"), base_rev=0), _=OWNER)
    assert ok["note"]["rev"] == 1
    stale = save(n["id"], N.NoteSave(title="Parlor", doc=_doc("old"), base_rev=0), _=OWNER)
    assert stale.status_code == 409

    # an explicit null moves to the top level; an absent field leaves it alone
    assert meta(n["id"], N.NoteMeta(pinned=True), _=OWNER)["note"]["folder_id"] == f["id"]
    assert meta(n["id"], N.NoteMeta(folder_id=None), _=OWNER)["note"]["folder_id"] is None

    img = upload(N.ImageIn(note_id=n["id"], mime="image/png", data=_b64(PNG)), _=OWNER)["image"]
    resp = image(img["id"], _=OWNER)
    assert resp.body == PNG and resp.media_type == "image/png"
    assert "private" in resp.headers["cache-control"]

    t = tree(_=OWNER)
    assert [x["id"] for x in t["notes"]] == [n["id"]] and t["notes"][0]["pinned"] is True


def test_routes_map_errors_to_http(app):
    get = _endpoint(app, "GET", "/notes/note/{note_id}")
    upload = _endpoint(app, "POST", "/notes/image")
    delete = _endpoint(app, "DELETE", "/notes/note/{note_id}")
    for call, code in (
        (lambda: get("missing", _=OWNER), 404),
        (lambda: upload(N.ImageIn(note_id="missing", mime="image/png", data=_b64(PNG)), _=OWNER), 400),
        (lambda: delete("missing", _=OWNER), 400),
    ):
        with pytest.raises(HTTPException) as e:
            call()
        assert e.value.status_code == code


# ── search ───────────────────────────────────────────────────────────────────
def _rich(*blocks) -> dict:
    """A doc whose paragraphs are lists of (text, bold?) runs — i.e. split text nodes."""
    content = []
    for runs in blocks:
        content.append({"type": "paragraph", "content": [
            {"type": "text", "text": t, **({"marks": [{"type": "bold"}]} if b else {})} for t, b in runs]})
    return {"type": "doc", "content": content}


def test_doc_text_joins_split_runs_and_keeps_captions():
    doc = _rich([("The clock reads ", False), ("3:15", True)], [("second", False)])
    doc["content"].append({"type": "noteImage", "attrs": {"imageId": "x", "caption": "Portrait in the hall"}})
    doc["content"].append({"type": "bulletList", "content": [{"type": "listItem", "content": [
        {"type": "paragraph", "content": [{"type": "text", "text": "nested item"}]}]}]})
    assert N.doc_text(doc).split("\n") == ["The clock reads 3:15", "second", "Portrait in the hall", "nested item"]
    assert N.doc_text(None) == ""


def test_search_matches_across_formatting_and_is_case_insensitive(conn):
    n = N.create_note(conn, None, "Library")
    N.save_note(conn, n["id"], "Library", _rich([("The clock reads ", False), ("3:15", True)]), 0)
    hits = N.search_notes(conn, "READS 3:1")
    assert [h["id"] for h in hits] == [n["id"]]
    snip = hits[0]["snippets"][0]
    assert snip["text"][snip["start"]:snip["start"] + snip["length"]].lower() == "reads 3:1"


def test_search_never_matches_the_json_structure(conn):
    n = N.create_note(conn, None, "t")
    N.save_note(conn, n["id"], "t", _rich([("hello", True)]), 0)
    for q in ("paragraph", "marks", "bold", '"type"'):
        assert N.search_notes(conn, q) == [], q


def test_search_title_captions_counts_and_ordering(conn):
    a = N.create_note(conn, None, "Safe code")
    N.save_note(conn, a["id"], "Safe code", _rich([("nothing here", False)]), 0)
    b = N.create_note(conn, None, "Rooms")
    doc = _rich([("the safe is in the study", False)], [("another safe, a second safe", False)])
    doc["content"].append({"type": "noteImage", "attrs": {"imageId": "x", "caption": "safe dial"}})
    N.save_note(conn, b["id"], "Rooms", doc, 0)
    hits = N.search_notes(conn, "safe")
    assert [h["id"] for h in hits] == [a["id"], b["id"]]   # the title hit first
    assert hits[0]["title_match"] and hits[0]["count"] == 0
    assert hits[1]["count"] == 4 and len(hits[1]["snippets"]) == N.SNIPPETS_PER_NOTE


def test_search_scopes_to_a_folder_and_its_subfolders(conn):
    top = N.create_folder(conn, None, "Blue Prince")
    sub = N.create_folder(conn, top["id"], "Rooms")
    other = N.create_folder(conn, None, "Other game")
    ids = {}
    for key, fid in (("top", top["id"]), ("sub", sub["id"]), ("other", other["id"]), ("loose", None)):
        n = N.create_note(conn, fid, key)
        N.save_note(conn, n["id"], key, _rich([("a clue", False)]), 0)
        ids[key] = n["id"]
    got = lambda fid: {h["id"] for h in N.search_notes(conn, "clue", fid)}   # noqa: E731
    assert got(None) == set(ids.values())
    assert got(top["id"]) == {ids["top"], ids["sub"]}
    assert got(sub["id"]) == {ids["sub"]}
    assert got("no-such-folder") == set()


def test_search_skips_the_trash_and_blank_queries(conn):
    n = N.create_note(conn, None, "clue")
    N.update_note_meta(conn, n["id"], {"trashed": True})
    assert N.search_notes(conn, "clue") == []
    assert N.search_notes(conn, "   ") == []


def test_search_non_ascii_query_uses_the_exact_filter(conn):
    n = N.create_note(conn, None, "t")
    N.save_note(conn, n["id"], "t", _rich([("Élan in the Café", False)]), 0)
    assert [h["id"] for h in N.search_notes(conn, "café")] == [n["id"]]
    assert [h["id"] for h in N.search_notes(conn, "ÉLAN")] == [n["id"]]


def test_body_text_is_backfilled_for_notes_saved_before_search(get_conn):
    c = get_conn()
    N.init_notes_db(c)
    n = N.create_note(c, None, "old")
    N.save_note(c, n["id"], "old", _rich([("legacy clue", False)]), 0)
    c.execute("UPDATE notes SET body_text=NULL")   # as if written before the column existed
    c.commit()
    N.init_notes_db(c)                               # the next boot backfills
    assert [h["id"] for h in N.search_notes(c, "legacy")] == [n["id"]]
    c.close()


def test_search_route(app):
    create = _endpoint(app, "POST", "/notes/note")
    save = _endpoint(app, "PUT", "/notes/note/{note_id}")
    search = _endpoint(app, "GET", "/notes/search")
    n = create(N.NoteCreate(title="Parlor"), _=OWNER)["note"]
    save(n["id"], N.NoteSave(title="Parlor", doc=_rich([("three boxes", False)]), base_rev=0), _=OWNER)
    assert [h["id"] for h in search(q="boxes", folder_id=None, _=OWNER)["results"]] == [n["id"]]
    assert search(q="boxes", folder_id="", _=OWNER)["results"][0]["count"] == 1
