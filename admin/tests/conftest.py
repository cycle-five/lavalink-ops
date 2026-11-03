"""Shared test fixtures.

Why this file exists: importing ``app.main`` builds ``Settings()`` at module
level (``app/main.py`` reads settings at boot to decide on proxy middleware),
and ``Settings`` requires ``ADMIN_PASSWORD``, ``ADMIN_SECRET_KEY`` and
``LAVALINK_PASSWORD``. Without env set *before* any ``app`` import, the whole
suite died at collection with a pydantic ValidationError — which is exactly
what happened in a clean environment before this file existed. ``conftest``
is imported by pytest before the test modules in this directory, so setting
defaults here (``setdefault`` — real env still wins) makes
``python -m pytest`` work out of the box.
"""

import asyncio
import os

os.environ.setdefault("ADMIN_PASSWORD", "test-admin-password")
os.environ.setdefault("ADMIN_SECRET_KEY", "test-secret-key")
os.environ.setdefault("LAVALINK_PASSWORD", "test-lavalink-password")

import pytest

import app.dependencies as dependencies


@pytest.fixture(autouse=True)
def fresh_config_lock():
    """Reset the global config lock per test.

    ``dependencies._config_lock`` is one ``asyncio.Lock`` created at import
    time. pytest-asyncio gives each test a fresh event loop; a lock that was
    contended under a previous loop can complain about being attached to a
    different loop. Handing each test a fresh lock removes that hazard.
    """
    dependencies._config_lock = asyncio.Lock()
    yield dependencies._config_lock
    dependencies._config_lock = asyncio.Lock()


@pytest.fixture
def client():
    """A TestClient for the real app, *without* entering its lifespan.

    Not entering the context manager means the lifespan never runs: no
    APScheduler, no log-watcher task tailing Docker, no pooled httpx client.
    Routes that need upstream services must mock them (see the health and
    login tests for the patterns).
    """
    from fastapi.testclient import TestClient

    from app.main import app

    return TestClient(app, raise_server_exceptions=False)


@pytest.fixture
def authed_client(client):
    """``client`` with a valid, freshly-signed session cookie."""
    from app.dependencies import get_settings
    from app.main import _sign_session

    settings = get_settings()
    client.cookies.set("admin_session", _sign_session(settings.admin_secret_key))
    return client
