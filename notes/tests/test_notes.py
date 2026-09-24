"""Tests for the Notes feature (notes/api.py).

The pure functions run against a real on-disk sqlite DB through core.db's _Conn
wrapper (the same shape prod uses). Routes are exercised by calling the
registered endpoints directly — the repo has no httpx/TestClient — and the
sign-in gate is held STRUCTURALLY: every registered /notes route must depend on
it, so a route added later without the gate fails here rather than shipping public.

Every pure function takes the caller's account id second; `U` is the account most
tests write as, and the ISOLATION tests below check that a second account can
neither see nor touch any of it.
"""
import base64
import sqlite3

import pytest
from fastapi import FastAPI, HTTPException

from core import alerts
from core.db import _Conn
from notes import api as N

OWNER = {"id": "u_owner", "name": "forrest", "is_admin": True}
OTHER = {"id": "u_other", "name": "someone", "is_admin": False}
U = OWNER["id"]

# Smallest valid headers for each accepted type (the magic-byte check reads only these).
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
WEBP = b"RIFF\x00\x00\x00\x00WEBPVP8 " + b"\x00" * 8
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 16


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


@pytest.fixture(autouse=True)
def _fresh_limits():
    """Rate limiters and the usage cache are per-process; start each test clean."""
    for lim in (N._writes_minute, N._writes_hour, N._uploads_hour, N._searches_minute):
        lim.reset()
    N.forget_usage()
    yield


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


# ── the sign-in gate ─────────────────────────────────────────────────────────
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
        if getattr(r, "path", "").startswith("/notes") and "member" not in _dep_names(r.dependant)
    ]


def test_every_notes_route_requires_a_signed_in_account(app):
    routes = [r for r in app.routes if getattr(r, "path", "").startswith("/notes")]
    assert len(routes) >= 12, "the route walk found too few routes to mean anything"
    assert _ungated(app) == []


def test_the_route_walk_catches_an_ungated_route(app):
    @app.get("/notes/leak")
    def leak():
        return {}
    assert _ungated(app) == ["['GET'] /notes/leak"]


def test_require_member():
    for who in (None, {}, {"name": "guest"}):
        with pytest.raises(HTTPException) as e:
            N.require_member(who)
        assert e.value.status_code == 401
    assert N.require_member(OTHER) is OTHER and N.require_member(OWNER) is OWNER


def test_member_dependency_resolves_the_session(get_conn):
    a = FastAPI()
    sessions = {"tok_owner": OWNER, "tok_other": OTHER}
    N.setup_notes(a, get_conn, sessions.get)
    route = next(r for r in a.routes if getattr(r, "path", "") == "/notes/tree")
    member = next(d.call for d in route.dependant.dependencies if d.call.__name__ == "member")
    assert member(token="tok_owner") is OWNER
    assert member(token="tok_other") is OTHER
    for tok in (None, "bogus"):
        with pytest.raises(HTTPException) as e:
            member(token=tok)
        assert e.value.status_code == 401


# ── notes ────────────────────────────────────────────────────────────────────
def _doc(text: str) -> dict:
    return {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def test_create_save_and_read_back(conn):
    n = N.create_note(conn, U, None, "Library")
    assert n["rev"] == 0 and n["doc"] is None and n["title"] == "Library"
    status, saved = N.save_note(conn, U, n["id"], "Library clue", _doc("the clock reads 3"), 0)
    assert status == "ok" and saved["rev"] == 1
    got = N.get_note(conn, U, n["id"])
    assert got["title"] == "Library clue" and got["doc"] == _doc("the clock reads 3")


def test_stale_rev_is_a_conflict_and_keeps_the_server_copy(conn):
    n = N.create_note(conn, U)
    assert N.save_note(conn, U, n["id"], "A", _doc("tab one"), 0)[0] == "ok"
    status, server = N.save_note(conn, U, n["id"], "B", _doc("tab two"), 0)
    assert status == "conflict"
    assert server["doc"] == _doc("tab one") and server["rev"] == 1
    assert N.get_note(conn, U, n["id"])["title"] == "A"


def test_organising_does_not_bump_rev_or_recent(conn):
    f = N.create_folder(conn, U, None, "Rooms")
    n = N.create_note(conn, U)
    N.save_note(conn, U, n["id"], "t", _doc("x"), 0)
    before = N.get_note(conn, U, n["id"])
    N.update_note_meta(conn, U, n["id"], {"folder_id": f["id"], "pinned": True})
    after = N.get_note(conn, U, n["id"])
    assert after["folder_id"] == f["id"] and after["pinned"] is True
    assert after["rev"] == before["rev"] and after["updated_at"] == before["updated_at"]
    # an open tab based on that rev can still save
    assert N.save_note(conn, U, n["id"], "t", _doc("y"), before["rev"])[0] == "ok"


def test_meta_move_to_missing_folder_is_rejected(conn):
    n = N.create_note(conn, U)
    with pytest.raises(ValueError):
        N.update_note_meta(conn, U, n["id"], {"folder_id": "nope"})


def test_trash_restore_and_delete_forever(conn):
    n = N.create_note(conn, U, None, "keep me")
    assert N.delete_note_forever(conn, U, n["id"]) is False  # not trashed yet
    N.update_note_meta(conn, U, n["id"], {"trashed": True})
    assert N.get_note(conn, U, n["id"])["deleted_at"] is not None
    assert N.save_note(conn, U, n["id"], "x", None, 0)[0] == "missing"  # no editing in the trash
    N.update_note_meta(conn, U, n["id"], {"trashed": False})
    assert N.get_note(conn, U, n["id"])["deleted_at"] is None
    N.update_note_meta(conn, U, n["id"], {"trashed": True})
    assert N.delete_note_forever(conn, U, n["id"]) is True
    assert N.get_note(conn, U, n["id"]) is None


def test_empty_trash_only_removes_trashed(conn):
    a, b = N.create_note(conn, U), N.create_note(conn, U)
    N.update_note_meta(conn, U, a["id"], {"trashed": True})
    assert N.empty_trash(conn, U) == 1
    assert N.get_note(conn, U, a["id"]) is None and N.get_note(conn, U, b["id"]) is not None


def test_doc_must_be_an_object_and_is_capped(conn, monkeypatch):
    n = N.create_note(conn, U)
    with pytest.raises(ValueError):
        N.save_note(conn, U, n["id"], "t", ["not", "a", "doc"], 0)
    monkeypatch.setattr(N, "_DOC", 50)
    with pytest.raises(ValueError):
        N.save_note(conn, U, n["id"], "t", _doc("x" * 100), 0)


def test_title_is_capped(conn):
    n = N.create_note(conn, U)
    N.save_note(conn, U, n["id"], "x" * 500, None, 0)
    assert len(N.get_note(conn, U, n["id"])["title"]) == N._NAME


# ── folders ──────────────────────────────────────────────────────────────────
def test_nested_folders_and_tree(conn):
    top = N.create_folder(conn, U, None, "Blue Prince")
    sub = N.create_folder(conn, U, top["id"], "Rooms")
    n = N.create_note(conn, U, sub["id"], "Library")
    tree = N.fetch_tree(conn, U)
    assert {f["id"]: f["parent_id"] for f in tree["folders"]} == {top["id"]: None, sub["id"]: top["id"]}
    assert tree["notes"][0]["id"] == n["id"] and "doc" not in tree["notes"][0]


def test_folder_cannot_move_inside_itself(conn):
    a = N.create_folder(conn, U, None, "a")
    b = N.create_folder(conn, U, a["id"], "b")
    c = N.create_folder(conn, U, b["id"], "c")
    for target in (a["id"], b["id"], c["id"]):
        with pytest.raises(ValueError):
            N.update_folder(conn, U, a["id"], {"parent_id": target})
    # moving a leaf up to the top level is fine
    assert N.update_folder(conn, U, c["id"], {"parent_id": None})["parent_id"] is None


def test_folder_depth_cap(conn, monkeypatch):
    monkeypatch.setattr(N, "MAX_DEPTH", 3)
    a = N.create_folder(conn, U, None, "a")
    b = N.create_folder(conn, U, a["id"], "b")
    c = N.create_folder(conn, U, b["id"], "c")
    with pytest.raises(ValueError):
        N.create_folder(conn, U, c["id"], "d")
    x = N.create_folder(conn, U, None, "x")
    y = N.create_folder(conn, U, x["id"], "y")
    # x (height 2) under b (depth 2) would be 4 deep
    with pytest.raises(ValueError):
        N.update_folder(conn, U, x["id"], {"parent_id": b["id"]})
    # y (height 1) under b fits exactly
    assert N.update_folder(conn, U, y["id"], {"parent_id": b["id"]})["parent_id"] == b["id"]


def test_rename_folder_blank_falls_back(conn):
    f = N.create_folder(conn, U, None, "  ")
    assert f["name"] == "New folder"
    assert N.update_folder(conn, U, f["id"], {"name": "Clues"})["name"] == "Clues"


def test_delete_folder_trashes_its_whole_subtree(conn):
    top = N.create_folder(conn, U, None, "top")
    sub = N.create_folder(conn, U, top["id"], "sub")
    n1 = N.create_note(conn, U, top["id"])
    n2 = N.create_note(conn, U, sub["id"])
    keep = N.create_note(conn, U, None)
    assert N.delete_folder(conn, U, top["id"]) == 2
    assert N.fetch_tree(conn, U)["folders"] == []
    assert N.get_note(conn, U, n1["id"])["deleted_at"] is not None
    assert N.get_note(conn, U, n2["id"])["deleted_at"] is not None
    assert N.get_note(conn, U, keep["id"])["deleted_at"] is None
    # restoring a note whose folder is gone lands it at the top level
    assert N.update_note_meta(conn, U, n2["id"], {"trashed": False})["folder_id"] is None
    assert N.delete_folder(conn, U, "gone") is None


# ── images ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("mime,raw", [("image/png", PNG), ("image/webp", WEBP), ("image/jpeg", JPEG)])
def test_image_round_trip(conn, mime, raw):
    n = N.create_note(conn, U)
    img = N.save_image(conn, U, n["id"], mime, _b64(raw), 10, 20)
    assert N.get_image(conn, U, img["id"]) == (mime, raw)


def test_image_rejections(conn, monkeypatch):
    n = N.create_note(conn, U)
    bad = [
        ("image/svg+xml", _b64(b"<svg/>")),          # not an accepted type
        ("image/png", _b64(JPEG)),                   # bytes do not match the type
        ("image/webp", _b64(b"RIFF\x00\x00\x00\x00AVI ")),  # RIFF but not WEBP
        ("image/png", "not base64!!"),
    ]
    for mime, data in bad:
        with pytest.raises(ValueError):
            N.save_image(conn, U, n["id"], mime, data)
    with pytest.raises(ValueError):
        N.save_image(conn, U, "no-such-note", "image/png", _b64(PNG))
    monkeypatch.setattr(N, "_IMAGE_BYTES", 10)
    with pytest.raises(ValueError):
        N.save_image(conn, U, n["id"], "image/png", _b64(PNG))


def _image_node(iid: str) -> dict:
    return {"type": "doc", "content": [{"type": "noteImage", "attrs": {"imageId": iid, "width": "full"}}]}


def test_sweep_keeps_referenced_and_young_images(conn):
    n = N.create_note(conn, U)
    used = N.save_image(conn, U, n["id"], "image/png", _b64(PNG))["id"]
    orphan = N.save_image(conn, U, n["id"], "image/png", _b64(PNG))["id"]
    N.save_note(conn, U, n["id"], "t", _image_node(used), 0)
    now = N._now()
    assert N.sweep(conn, now)["images"] == 0  # both inside the grace window
    later = now + N.IMAGE_GRACE + 1
    assert N.sweep(conn, later)["images"] == 1
    assert N.get_image(conn, U, used) is not None and N.get_image(conn, U, orphan) is None


def test_sweep_keeps_images_of_trashed_notes_until_purged(conn):
    n = N.create_note(conn, U)
    iid = N.save_image(conn, U, n["id"], "image/png", _b64(PNG))["id"]
    N.save_note(conn, U, n["id"], "t", _image_node(iid), 0)
    N.update_note_meta(conn, U, n["id"], {"trashed": True})
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

    f = mkfolder(N.FolderCreate(name="Blue Prince"), user=OWNER)["folder"]
    n = create(N.NoteCreate(folder_id=f["id"], title="Parlor"), user=OWNER)["note"]
    ok = save(n["id"], N.NoteSave(title="Parlor", doc=_doc("three boxes"), base_rev=0), user=OWNER)
    assert ok["note"]["rev"] == 1
    stale = save(n["id"], N.NoteSave(title="Parlor", doc=_doc("old"), base_rev=0), user=OWNER)
    assert stale.status_code == 409

    # an explicit null moves to the top level; an absent field leaves it alone
    assert meta(n["id"], N.NoteMeta(pinned=True), user=OWNER)["note"]["folder_id"] == f["id"]
    assert meta(n["id"], N.NoteMeta(folder_id=None), user=OWNER)["note"]["folder_id"] is None

    img = upload(N.ImageIn(note_id=n["id"], mime="image/png", data=_b64(PNG)), user=OWNER)["image"]
    resp = image(img["id"], user=OWNER)
    assert resp.body == PNG and resp.media_type == "image/png"
    assert "private" in resp.headers["cache-control"]

    t = tree(user=OWNER)
    assert [x["id"] for x in t["notes"]] == [n["id"]] and t["notes"][0]["pinned"] is True


def test_routes_map_errors_to_http(app):
    get = _endpoint(app, "GET", "/notes/note/{note_id}")
    upload = _endpoint(app, "POST", "/notes/image")
    delete = _endpoint(app, "DELETE", "/notes/note/{note_id}")
    for call, code in (
        (lambda: get("missing", user=OWNER), 404),
        (lambda: upload(N.ImageIn(note_id="missing", mime="image/png", data=_b64(PNG)), user=OWNER), 400),
        (lambda: delete("missing", user=OWNER), 400),
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
    n = N.create_note(conn, U, None, "Library")
    N.save_note(conn, U, n["id"], "Library", _rich([("The clock reads ", False), ("3:15", True)]), 0)
    hits = N.search_notes(conn, U, "READS 3:1")
    assert [h["id"] for h in hits] == [n["id"]]
    snip = hits[0]["snippets"][0]
    assert snip["text"][snip["start"]:snip["start"] + snip["length"]].lower() == "reads 3:1"


def test_search_never_matches_the_json_structure(conn):
    n = N.create_note(conn, U, None, "t")
    N.save_note(conn, U, n["id"], "t", _rich([("hello", True)]), 0)
    for q in ("paragraph", "marks", "bold", '"type"'):
        assert N.search_notes(conn, U, q) == [], q


def test_search_title_captions_counts_and_ordering(conn):
    a = N.create_note(conn, U, None, "Safe code")
    N.save_note(conn, U, a["id"], "Safe code", _rich([("nothing here", False)]), 0)
    b = N.create_note(conn, U, None, "Rooms")
    doc = _rich([("the safe is in the study", False)], [("another safe, a second safe", False)])
    doc["content"].append({"type": "noteImage", "attrs": {"imageId": "x", "caption": "safe dial"}})
    N.save_note(conn, U, b["id"], "Rooms", doc, 0)
    hits = N.search_notes(conn, U, "safe")
    assert [h["id"] for h in hits] == [a["id"], b["id"]]   # the title hit first
    assert hits[0]["title_match"] and hits[0]["count"] == 0
    assert hits[1]["count"] == 4 and len(hits[1]["snippets"]) == N.SNIPPETS_PER_NOTE


def test_search_scopes_to_a_folder_and_its_subfolders(conn):
    top = N.create_folder(conn, U, None, "Blue Prince")
    sub = N.create_folder(conn, U, top["id"], "Rooms")
    other = N.create_folder(conn, U, None, "Other game")
    ids = {}
    for key, fid in (("top", top["id"]), ("sub", sub["id"]), ("other", other["id"]), ("loose", None)):
        n = N.create_note(conn, U, fid, key)
        N.save_note(conn, U, n["id"], key, _rich([("a clue", False)]), 0)
        ids[key] = n["id"]
    got = lambda fid: {h["id"] for h in N.search_notes(conn, U, "clue", fid)}   # noqa: E731
    assert got(None) == set(ids.values())
    assert got(top["id"]) == {ids["top"], ids["sub"]}
    assert got(sub["id"]) == {ids["sub"]}
    assert got("no-such-folder") == set()


def test_search_skips_the_trash_and_blank_queries(conn):
    n = N.create_note(conn, U, None, "clue")
    N.update_note_meta(conn, U, n["id"], {"trashed": True})
    assert N.search_notes(conn, U, "clue") == []
    assert N.search_notes(conn, U, "   ") == []


def test_search_non_ascii_query_uses_the_exact_filter(conn):
    n = N.create_note(conn, U, None, "t")
    N.save_note(conn, U, n["id"], "t", _rich([("Élan in the Café", False)]), 0)
    assert [h["id"] for h in N.search_notes(conn, U, "café")] == [n["id"]]
    assert [h["id"] for h in N.search_notes(conn, U, "ÉLAN")] == [n["id"]]


def test_body_text_is_backfilled_for_notes_saved_before_search(get_conn):
    c = get_conn()
    N.init_notes_db(c)
    n = N.create_note(c, U, None, "old")
    N.save_note(c, U, n["id"], "old", _rich([("legacy clue", False)]), 0)
    c.execute("UPDATE notes SET body_text=NULL")   # as if written before the column existed
    c.commit()
    N.init_notes_db(c)                               # the next boot backfills
    assert [h["id"] for h in N.search_notes(c, U, "legacy")] == [n["id"]]
    c.close()


def test_search_route(app):
    create = _endpoint(app, "POST", "/notes/note")
    save = _endpoint(app, "PUT", "/notes/note/{note_id}")
    search = _endpoint(app, "GET", "/notes/search")
    n = create(N.NoteCreate(title="Parlor"), user=OWNER)["note"]
    save(n["id"], N.NoteSave(title="Parlor", doc=_rich([("three boxes", False)]), base_rev=0), user=OWNER)
    assert [h["id"] for h in search(q="boxes", folder_id=None, user=OWNER)["results"]] == [n["id"]]
    assert search(q="boxes", folder_id="", user=OWNER)["results"][0]["count"] == 1


# ── one account's notebook is invisible to every other ───────────────────────
V = OTHER["id"]


def test_another_account_cannot_see_or_touch_anything(conn):
    f = N.create_folder(conn, U, None, "Mine")
    n = N.create_note(conn, U, f["id"], "secret")
    N.save_note(conn, U, n["id"], "secret", _doc("the safe code is 4213"), 0)
    img = N.save_image(conn, U, n["id"], "image/png", _b64(PNG))

    assert N.fetch_tree(conn, V) == {"folders": [], "notes": []}
    assert N.get_note(conn, V, n["id"]) is None
    assert N.get_image(conn, V, img["id"]) is None
    assert N.search_notes(conn, V, "4213") == []
    assert N.search_notes(conn, V, "4213", f["id"]) == []
    assert N.save_note(conn, V, n["id"], "mine now", _doc("x"), 1)[0] == "missing"
    assert N.update_note_meta(conn, V, n["id"], {"trashed": True}) is None
    assert N.delete_note_forever(conn, V, n["id"]) is False
    assert N.update_folder(conn, V, f["id"], {"name": "renamed"}) is None
    assert N.delete_folder(conn, V, f["id"]) is None
    with pytest.raises(ValueError):
        N.save_image(conn, V, n["id"], "image/png", _b64(PNG))
    # the other account's folder id is just as unknown when used from this side
    theirs = N.create_folder(conn, V, None, "Theirs")
    with pytest.raises(ValueError):
        N.create_folder(conn, U, theirs["id"], "sneak in")
    with pytest.raises(ValueError):
        N.update_note_meta(conn, U, n["id"], {"folder_id": theirs["id"]})
    assert N.create_note(conn, V, f["id"])["folder_id"] is None   # a foreign folder -> top level
    N.update_note_meta(conn, V, N.create_note(conn, V)["id"], {"trashed": True})
    assert N.empty_trash(conn, V) == 1

    # ...and after all of that, the first account's notebook is exactly as it was
    got = N.get_note(conn, U, n["id"])
    assert got["title"] == "secret" and got["deleted_at"] is None and got["rev"] == 1
    assert [x["name"] for x in N.fetch_tree(conn, U)["folders"]] == ["Mine"]
    assert N.get_image(conn, U, img["id"]) == ("image/png", PNG)


def test_sweep_only_counts_references_from_the_images_own_account(conn):
    """Pasting another account's image id into your note must not keep it alive."""
    mine = N.create_note(conn, U)
    iid = N.save_image(conn, U, mine["id"], "image/png", _b64(PNG))["id"]
    theirs = N.create_note(conn, V)
    N.save_note(conn, V, theirs["id"], "t", _image_node(iid), 0)
    assert N.sweep(conn, N._now() + N.IMAGE_GRACE + 1)["images"] == 1


def test_emptying_the_trash_frees_its_pictures_for_that_account_only(conn):
    a = N.create_note(conn, U)
    ia = N.save_image(conn, U, a["id"], "image/png", _b64(PNG))["id"]
    N.save_note(conn, U, a["id"], "t", _image_node(ia), 0)
    b = N.create_note(conn, V)
    ib = N.save_image(conn, V, b["id"], "image/png", _b64(PNG))["id"]   # unreferenced
    N.update_note_meta(conn, U, a["id"], {"trashed": True})
    N.empty_trash(conn, U)
    later = N._now() + N.EMPTY_TRASH_GRACE + 1
    assert N.sweep(conn, later, uid=U, grace=N.EMPTY_TRASH_GRACE)["images"] == 1
    assert N.get_image(conn, U, ia) is None
    assert N.get_image(conn, V, ib) is not None   # the other orphan waits for the global sweep


def test_rows_from_before_owners_are_claimed_by_the_site_owner_only(get_conn, monkeypatch):
    c = get_conn()
    N.init_notes_db(c)
    n = N.create_note(c, U, None, "from before")
    f = N.create_folder(c, U, None, "old folder")
    i = N.save_image(c, U, n["id"], "image/png", _b64(PNG))
    for t in ("notes", "note_folders", "note_images"):
        c.execute(f"UPDATE {t} SET owner_id=NULL")   # as the rows were before the column
    c.commit()
    c.close()

    monkeypatch.setenv("SITE_OWNER", "Forrest")
    admin_not_owner = {"id": "u_admin", "name": "helper", "is_admin": True}
    sessions = {"o": OWNER, "x": OTHER, "a": admin_not_owner}
    a = FastAPI()
    N.setup_notes(a, get_conn, sessions.get)
    tree = _endpoint(a, "GET", "/notes/tree")
    route = next(r for r in a.routes if getattr(r, "path", "") == "/notes/tree")
    member = next(d.call for d in route.dependant.dependencies if d.call.__name__ == "member")

    for tok, user in (("x", OTHER), ("a", admin_not_owner)):   # visiting first claims nothing
        member(token=tok)
        assert tree(user=user)["notes"] == []
    member(token="o")
    t = tree(user=OWNER)
    assert [x["id"] for x in t["notes"]] == [n["id"]] and [x["id"] for x in t["folders"]] == [f["id"]]
    c = get_conn()
    assert N.get_image(c, U, i["id"]) is not None
    c.close()


def test_owns_legacy_notes(monkeypatch):
    monkeypatch.setenv("SITE_OWNER", "Forrest")
    assert N.owns_legacy_notes({"id": "1", "name": "forrest"})
    assert not N.owns_legacy_notes({"id": "2", "name": "helper", "is_admin": True})
    monkeypatch.delenv("SITE_OWNER")
    assert N.owns_legacy_notes({"id": "2", "name": "helper", "is_admin": True})
    assert not N.owns_legacy_notes(OTHER)


# ── quotas ───────────────────────────────────────────────────────────────────
def _meter(uid=V, **kw):
    limits = {"quota_bytes": 10_000, "max_notes": 3, "max_folders": 2, "site_budget": 10**9}
    return N.Meter(uid, "someone", **{**limits, **kw})


def test_note_and_folder_caps(conn):
    m = _meter()
    for _ in range(3):
        N.create_note(conn, V, quota=m)
    with pytest.raises(N.QuotaError):
        N.create_note(conn, V, quota=m)
    N.create_folder(conn, V, None, "a", quota=m)
    N.create_folder(conn, V, None, "b", quota=m)
    with pytest.raises(N.QuotaError):
        N.create_folder(conn, V, None, "c", quota=m)
    # one alert per account per day, not one per refusal
    assert [a["kind"] for a in alerts._sink] == ["notes-quota"]


def test_byte_quota_refuses_growth_but_never_shrinking(conn):
    m = _meter(quota_bytes=3_000)
    n = N.create_note(conn, V, quota=m)
    assert N.save_note(conn, V, n["id"], "t", _doc("x" * 1000), 0, quota=m)[0] == "ok"
    with pytest.raises(N.QuotaError, match="full"):
        N.save_note(conn, V, n["id"], "t", _doc("x" * 4000), 1, quota=m)
    assert N.get_note(conn, V, n["id"])["rev"] == 1                    # refused, not half-written
    assert N.save_note(conn, V, n["id"], "t", _doc("short"), 1, quota=m)[0] == "ok"
    with pytest.raises(N.QuotaError):
        N.save_image(conn, V, n["id"], "image/png", _b64(PNG + b"\x00" * 5000), quota=m)
    assert N.usage(conn, V)["images"] == 0


def test_the_cached_usage_follows_each_write(conn):
    m = _meter(quota_bytes=10**6)
    n = N.create_note(conn, V, quota=m)
    N.save_note(conn, V, n["id"], "t", _doc("x" * 500), 0, quota=m)
    N.save_image(conn, V, n["id"], "image/png", _b64(PNG), quota=m)
    assert m.current(conn) == N.usage(conn, V)      # the cache agrees with a fresh sum


def test_site_budget_across_accounts(conn):
    a = N.create_note(conn, "u_a")
    N.save_note(conn, "u_a", a["id"], "t", _doc("y" * 5000), 0)
    m = _meter(quota_bytes=10**6, site_budget=6_000)
    n = N.create_note(conn, V, quota=m)
    with pytest.raises(N.QuotaError, match="site"):
        N.save_note(conn, V, n["id"], "t", _doc("z" * 2000), 0, quota=m)
    assert any(x["kind"] == "notes-storage" and x["severity"] == "critical" for x in alerts._sink)


def test_the_site_owner_is_unmetered_and_quota_errors_are_413(app, monkeypatch):
    assert N.meter_for(OWNER) is None and N.meter_for(OTHER) is not None
    monkeypatch.setattr(N, "meter_for", lambda u: None if u is OWNER else _meter(u["id"], max_notes=1))
    create = _endpoint(app, "POST", "/notes/note")
    for _ in range(3):
        create(N.NoteCreate(), user=OWNER)
    create(N.NoteCreate(), user=OTHER)
    with pytest.raises(HTTPException) as e:
        create(N.NoteCreate(), user=OTHER)
    assert e.value.status_code == 413


def test_tree_reports_usage_and_the_quota(app):
    tree = _endpoint(app, "GET", "/notes/tree")
    create = _endpoint(app, "POST", "/notes/note")
    create(N.NoteCreate(title="hi"), user=OTHER)
    u = tree(user=OTHER)["usage"]
    assert u["notes"] == 1 and u["bytes"] == 2 and u["quota_bytes"] == N.QUOTA_BYTES
    assert tree(user=OWNER)["usage"]["quota_bytes"] is None


# ── rate limits ──────────────────────────────────────────────────────────────
def test_writes_are_rate_limited_per_account(app, monkeypatch):
    monkeypatch.setattr(N._writes_minute, "max_hits", 3)
    create = _endpoint(app, "POST", "/notes/note")
    for _ in range(3):
        create(N.NoteCreate(), user=OTHER)
    with pytest.raises(HTTPException) as e:
        create(N.NoteCreate(), user=OTHER)
    assert e.value.status_code == 429
    create(N.NoteCreate(), user=OWNER)        # a different account has its own budget
    assert [a["kind"] for a in alerts._sink] == ["notes-rate"]
