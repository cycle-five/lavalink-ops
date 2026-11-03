"""Tests for the log viewer's filter predicates and buffer/docker split:
``tail <= len(RECENT_LOGS)`` slices the ring buffer; larger tails fall back
to the Docker logs call.
"""

from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import logs as logs_router
from app.services.log_watcher import RECENT_LOGS


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(logs_router.router)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _seed_logs():
    RECENT_LOGS.clear()
    RECENT_LOGS.extend([
        "INFO Track loaded fine",
        "ERROR youtube exploded",
        "WARN something warm",
        "INFO OAuth device code here",
        "DEBUG plain line",
    ])
    yield
    RECENT_LOGS.clear()


def test_stream_all_returns_buffer_slice(client):
    res = client.get("/logs/stream", params={"filter_type": "all", "tail": 2})
    assert res.status_code == 200
    assert "plain line" in res.text
    assert "Track loaded" not in res.text


def test_stream_errors_filter(client):
    res = client.get("/logs/stream", params={"filter_type": "errors", "tail": 5})
    assert "youtube exploded" in res.text
    assert "something warm" in res.text
    assert "Track loaded" not in res.text


def test_stream_youtube_filter_is_case_insensitive(client):
    res = client.get("/logs/stream", params={"filter_type": "youtube", "tail": 5})
    assert "youtube exploded" in res.text
    assert "plain line" not in res.text


def test_stream_oauth_filter_matches_device(client):
    res = client.get("/logs/stream", params={"filter_type": "oauth", "tail": 5})
    assert "OAuth device code" in res.text
    assert "Track loaded" not in res.text


def test_stream_tail_beyond_buffer_falls_back_to_docker(client):
    with patch.object(
        logs_router, "get_container_logs", return_value="docker line 1\ndocker line 2"
    ) as mock_logs, patch.object(logs_router, "get_settings") as mock_settings:
        mock_settings.return_value.lavalink_container_name = "lavalink"
        res = client.get("/logs/stream", params={"filter_type": "all", "tail": 999})
    assert res.status_code == 200
    assert "docker line 1" in res.text
    mock_logs.assert_called_once()


def test_stream_tail_zero_rejected_422(client):
    res = client.get("/logs/stream", params={"tail": 0})
    assert res.status_code == 422


def test_stream_tail_over_max_rejected_422(client):
    res = client.get("/logs/stream", params={"tail": 5000})
    assert res.status_code == 422


def test_logs_page_renders(client):
    assert client.get("/logs").status_code == 200
