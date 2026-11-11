"""data-worker/datastore.py — the data jobs' take/publish, against a stand-in store."""
import importlib.util
import io
import json
import os
import urllib.error

import pytest

_spec = importlib.util.spec_from_file_location(
    "datastore", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "datastore.py"))
ds = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ds)


class _Resp(io.BytesIO):
    def __init__(self, status, body):
        super().__init__(body)
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class Store:
    """GET/PUT like data-worker/src/index.js, plus failure switches."""

    def __init__(self, files=None, token="tok"):
        self.files = {k: v.encode() for k, v in (files or {}).items()}
        self.token, self.puts, self.down, self.lag = token, [], False, 0

    def __call__(self, req, timeout=None):
        if self.down:
            raise urllib.error.URLError("down")
        name = req.full_url.split("/")[-1].split("?")[0]
        if req.get_method() == "PUT":
            if req.get_header("Authorization") != f"Bearer {self.token}":
                raise urllib.error.HTTPError(req.full_url, 401, "bad token", {}, io.BytesIO(b"{}"))
            self.puts.append(name)
            self.files[name], self.pending = req.data, self.lag
            return _Resp(200, b'{"ok":true}')
        if getattr(self, "pending", 0) > 0:        # eventually consistent: stale for a while
            self.pending -= 1
            return _Resp(200, b'{"stale":true}')
        if name not in self.files:
            raise urllib.error.HTTPError(req.full_url, 404, "nf", {}, io.BytesIO(b"{}"))
        return _Resp(200, self.files[name])


@pytest.fixture()
def data(tmp_path, monkeypatch):
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setattr(ds, "DATA", str(d))
    monkeypatch.setenv("RUNNER_TEMP", str(tmp_path / "tmp"))
    monkeypatch.setattr(ds.time, "sleep", lambda s: None)
    return d


def test_take_replaces_the_repo_copy_with_the_published_one(data):
    (data / "a.json").write_text('{"v":"repo"}')
    ds.take(["a.json"], "https://s", Store({"a.json": '{"v":"store"}'}))
    assert json.loads((data / "a.json").read_text()) == {"v": "store"}


def test_a_file_never_published_keeps_the_repo_copy_and_is_published_after(data):
    (data / "a.json").write_text('{"v":"repo"}')
    store = Store()
    ds.take(["a.json"], "https://s", store)
    assert json.loads((data / "a.json").read_text()) == {"v": "repo"}
    assert ds.publish(["a.json"], "https://s", "tok", store) == ["a.json"]   # unchanged, but absent
    assert store.files["a.json"] == b'{"v":"repo"}'


def test_only_what_changed_is_published(data):
    store = Store({"a.json": '{"v":1}', "b.json": '{"v":1}'})
    ds.take(["a.json", "b.json"], "https://s", store)
    (data / "b.json").write_text('{"v":2}')
    assert ds.publish(["a.json", "b.json"], "https://s", "tok", store) == ["b.json"]
    assert store.puts == ["b.json"]


def test_a_broken_store_fails_the_job_rather_than_building_on_a_stale_copy(data):
    (data / "a.json").write_text("{}")
    store = Store()
    store.down = True
    with pytest.raises(SystemExit, match="did not answer"):
        ds.take(["a.json"], "https://s", store)
    with pytest.raises(SystemExit, match="not JSON"):
        ds.take(["a.json"], "https://s", Store({"a.json": "<html>502</html>"}))


def test_publish_needs_the_token_and_the_right_one(data):
    (data / "a.json").write_text("{}")
    with pytest.raises(SystemExit, match="DATA_PUBLISH_TOKEN"):
        ds.publish(["a.json"], "https://s", "", Store())
    with pytest.raises(SystemExit, match="HTTP 401"):
        ds.publish(["a.json"], "https://s", "wrong", Store())


def test_publish_waits_out_the_store_catching_up_and_fails_if_it_never_does(data):
    (data / "a.json").write_text('{"v":1}')
    store = Store()
    store.lag = 3
    assert ds.publish(["a.json"], "https://s", "tok", store, settle_tries=5) == ["a.json"]
    (data / "a.json").write_text('{"v":2}')
    store.lag = 99
    with pytest.raises(SystemExit, match="not serving"):
        ds.publish(["a.json"], "https://s", "tok", store, settle_tries=3)


def test_take_lol_takes_every_year_the_index_lists(data):
    store = Store({"lol-champs-index.json": json.dumps({"years": [{"year": 2025}, {"year": 2026}]}),
                   "lol-champs-2025.json": '{"y":2025}', "lol-champs-2026.json": '{"y":2026}'})
    ds.take_lol("https://s", store)
    assert sorted(p.name for p in data.iterdir()) == [
        "lol-champs-2025.json", "lol-champs-2026.json", "lol-champs-index.json"]


def test_with_no_store_configured_nothing_happens(data, monkeypatch):
    monkeypatch.delenv("DATA_URL", raising=False)
    ds.main(["publish", "a.json"])          # would raise on the missing file if it ran
