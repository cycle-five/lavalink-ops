"""Tests for ``app.dependencies.StateStore`` — the admin panel's only
persistence (PoToken history, OAuth device code/success markers).

It was completely untested despite doing atomic tempfile+fsync+replace
writes; a bug here silently loses or corrupts all token state.
"""

import json
import os

import pytest

import app.dependencies as dependencies
from app.dependencies import StateStore, get_http_client


@pytest.fixture
def store(tmp_path):
    return StateStore(str(tmp_path / "state.json"))


def test_read_missing_file_returns_empty_dict(store):
    assert store.read() == {}


def test_read_corrupt_json_returns_empty_dict(store, tmp_path):
    (tmp_path / "state.json").write_text("{not json", encoding="utf-8")
    assert store.read() == {}


def test_write_then_read_round_trip(store):
    store.write({"a": 1, "nested": {"b": [1, 2, 3]}})
    assert store.read() == {"a": 1, "nested": {"b": [1, 2, 3]}}


def test_write_is_atomic_no_tmp_files_left_on_success(store, tmp_path):
    store.write({"a": 1})
    leftovers = [p.name for p in tmp_path.iterdir() if p.name != "state.json"]
    assert leftovers == []


def test_write_failure_removes_tmp_and_reraises(store, tmp_path, monkeypatch):
    def boom(src, dst):
        raise OSError("replace failed")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="replace failed"):
        store.write({"a": 1})
    assert [p.name for p in tmp_path.iterdir()] == []


def test_get_returns_default_for_missing_key(store):
    assert store.get("nope") is None
    assert store.get("nope", 42) == 42


def test_set_preserves_other_keys(store):
    store.set("first", 1)
    store.set("second", 2)
    assert store.read() == {"first": 1, "second": 2}


def test_set_overwrites_existing_key(store):
    store.set("k", "old")
    store.set("k", "new")
    assert store.get("k") == "new"


def test_delete_existing_key_persists(store):
    store.write({"keep": 1, "drop": 2})
    store.delete("drop")
    assert store.read() == {"keep": 1}


def test_delete_missing_key_does_not_rewrite_file(store, tmp_path):
    store.write({"keep": 1})
    path = tmp_path / "state.json"
    before_mtime = path.stat().st_mtime_ns
    before_content = path.read_text(encoding="utf-8")
    store.delete("absent")
    assert path.stat().st_mtime_ns == before_mtime
    assert path.read_text(encoding="utf-8") == before_content


def test_bare_filename_state_path_works(tmp_path, monkeypatch):
    """A state path with no directory component must not crash _ensure_dir
    (``os.path.dirname('state.json')`` is ``''`` and ``makedirs('')`` raises).
    """
    monkeypatch.chdir(tmp_path)
    store = StateStore("state.json")
    store.set("k", "v")
    assert json.loads((tmp_path / "state.json").read_text(encoding="utf-8")) == {"k": "v"}


def test_get_http_client_raises_when_uninitialized(monkeypatch):
    monkeypatch.setattr(dependencies, "_http_client", None)
    with pytest.raises(RuntimeError, match="not initialized"):
        get_http_client()


def test_get_settings_and_get_state_are_cached():
    assert dependencies.get_settings() is dependencies.get_settings()
    assert dependencies.get_state() is dependencies.get_state()
