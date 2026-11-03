"""Tests for the ``/healthz`` JSON contract — what external monitors scrape.

The subtle part: Lavalink is *critical* (down flips the aggregate to 503);
cipher and pot are *advisory* (reported, but the aggregate stays 200, since
Lavalink can serve non-YouTube sources without them). A regression either
pages falsely or masks a real outage, so pin it exactly.
"""

from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import health


@pytest.fixture
def health_client(monkeypatch):
    """A minimal app with only the health router and controllable probes.

    ``_PROBES`` captured the probe function objects at import time, so
    patching ``app.services.lavalink.is_healthy`` would *not* change what
    ``/healthz`` calls — we replace the ``_PROBES`` entries themselves.
    The HTML ``/health`` page calls the service modules directly, so patch
    those too.
    """
    probes = {
        "lavalink": AsyncMock(return_value=True),
        "cipher": AsyncMock(return_value=True),
        "pot": AsyncMock(return_value=True),
    }
    critical = {"lavalink": True, "cipher": False, "pot": False}
    for name, mock in probes.items():
        monkeypatch.setitem(health._PROBES, name, (mock, critical[name]))
    monkeypatch.setattr(health.lavalink, "is_healthy", probes["lavalink"])
    monkeypatch.setattr(health.cipher, "is_healthy", probes["cipher"])
    monkeypatch.setattr(health.pot, "is_healthy", probes["pot"])

    app = FastAPI()
    app.include_router(health.router)
    return TestClient(app), probes


def test_healthz_all_ok_returns_200(health_client):
    client, _ = health_client
    res = client.get("/healthz")
    assert res.status_code == 200
    body = res.json()
    assert body["status"] == "ok"
    assert body["services"] == {"lavalink": "ok", "cipher": "ok", "pot": "ok"}
    assert "checked_at" in body


def test_healthz_lavalink_down_returns_503(health_client):
    client, probes = health_client
    probes["lavalink"].return_value = False
    res = client.get("/healthz")
    assert res.status_code == 503
    assert res.json()["status"] == "down"
    assert res.json()["services"]["lavalink"] == "down"


def test_healthz_cipher_down_still_200_advisory(health_client):
    client, probes = health_client
    probes["cipher"].return_value = False
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["services"]["cipher"] == "down"


def test_healthz_pot_down_still_200_advisory(health_client):
    client, probes = health_client
    probes["pot"].return_value = False
    res = client.get("/healthz")
    assert res.status_code == 200
    assert res.json()["services"]["pot"] == "down"


def test_healthz_probe_raising_exception_counts_as_down(health_client):
    client, probes = health_client
    probes["lavalink"].side_effect = RuntimeError("connection refused")
    res = client.get("/healthz")
    assert res.status_code == 503
    assert res.json()["services"]["lavalink"] == "down"


def test_healthz_service_ok_200(health_client):
    client, _ = health_client
    res = client.get("/healthz/cipher")
    assert res.status_code == 200
    assert res.json()["service"] == "cipher"
    assert res.json()["status"] == "ok"


def test_healthz_service_down_503(health_client):
    client, probes = health_client
    probes["pot"].return_value = False
    res = client.get("/healthz/pot")
    assert res.status_code == 503
    assert res.json()["status"] == "down"


def test_healthz_service_unknown_404(health_client):
    client, _ = health_client
    res = client.get("/healthz/nope")
    assert res.status_code == 404
    assert res.json()["status"] == "unknown"


def test_healthz_service_probe_exception_503(health_client):
    client, probes = health_client
    probes["cipher"].side_effect = RuntimeError("boom")
    res = client.get("/healthz/cipher")
    assert res.status_code == 503


def test_health_page_renders(health_client):
    client, _ = health_client
    res = client.get("/health")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]
