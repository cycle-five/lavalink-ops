"""Tests for the track tester router (``POST /test/resolve``) — the most
branch-dense router in the panel: each Lavalink ``loadType`` has a
different ``data`` shape.
"""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import test as test_router


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(test_router.router)
    return TestClient(app)


def _resolve(client, result):
    with patch.object(
        test_router.lavalink, "load_tracks", new_callable=AsyncMock, return_value=result
    ):
        return client.post("/test/resolve", data={"identifier": "some-id"})


def test_resolve_track(client):
    res = _resolve(client, {
        "loadType": "track",
        "data": {"info": {"title": "Song", "author": "Artist", "length": 123}},
        "pluginInfo": {"clientName": "WEB"},
    })
    assert res.status_code == 200
    assert "Song" in res.text


def test_resolve_playlist_counts_tracks(client):
    res = _resolve(client, {
        "loadType": "playlist",
        "data": {"info": {"name": "My Playlist"}, "tracks": [{}, {}, {}]},
        "pluginInfo": {},
    })
    assert res.status_code == 200
    assert "My Playlist" in res.text


def test_resolve_search_uses_first_match(client):
    res = _resolve(client, {
        "loadType": "search",
        "data": [{"info": {"title": "First Hit", "sourceName": "youtube"}}],
        "pluginInfo": {},
    })
    assert res.status_code == 200
    assert "First Hit" in res.text


def test_resolve_search_empty(client):
    res = _resolve(client, {"loadType": "search", "data": [], "pluginInfo": {}})
    assert res.status_code == 200


def test_resolve_empty(client):
    res = _resolve(client, {"loadType": "empty", "data": {}, "pluginInfo": {}})
    assert res.status_code == 200
    assert "No matches" in res.text


def test_resolve_error_includes_message(client):
    res = _resolve(client, {
        "loadType": "error",
        "data": {"message": "Something broke", "severity": "common"},
        "pluginInfo": {},
    })
    assert res.status_code == 200
    assert "Something broke" in res.text


def test_resolve_unknown_load_type(client):
    res = _resolve(client, {"loadType": "weird", "data": {}, "pluginInfo": {}})
    assert res.status_code == 200
    assert "Unknown LoadType" in res.text


def test_resolve_lavalink_exception_returns_exception_partial(client):
    with patch.object(
        test_router.lavalink, "load_tracks",
        new_callable=AsyncMock, side_effect=RuntimeError("lavalink down"),
    ):
        res = client.post("/test/resolve", data={"identifier": "x"})
    assert res.status_code == 200
    assert "Exception" in res.text
    assert "lavalink down" in res.text


def test_test_page_renders(client):
    assert client.get("/test").status_code == 200
