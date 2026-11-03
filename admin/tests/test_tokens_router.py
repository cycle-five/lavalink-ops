"""Tests for the tokens router: the tri-state ``oauth_status`` logic and
the manual refresh/rotate partials. Secret previews go through ``_mask``
(covered directly in test_settings_and_mask.py); here we assert the full
secret never lands in the rendered page.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.routers import tokens as tokens_router


@pytest.fixture
def harness():
    settings = MagicMock()
    settings.pot_refresh_enabled = True
    settings.pot_refresh_interval_hours = 6
    state = MagicMock()
    # Behave like StateStore.get: return the caller's default for missing keys
    # (the tokens template iterates pot_history — a None there crashes it).
    state.get.side_effect = lambda key, default=None: default

    app = FastAPI()
    app.include_router(tokens_router.router)
    client = TestClient(app)

    with patch.object(tokens_router, "get_settings", return_value=settings), \
         patch.object(tokens_router, "get_state", return_value=state):
        yield client, state


def _config_with(oauth_refresh="", pot_token="tok-secret-9999", pot_visitor="vis-secret-8888"):
    data = {
        "plugins": {
            "youtube": {
                "oauth": {"refreshToken": oauth_refresh},
                "pot": {"token": pot_token, "visitorData": pot_visitor},
            }
        }
    }
    return AsyncMock(return_value=data)


def test_tokens_page_status_active_with_refresh_token(harness):
    client, _state = harness
    with patch.object(tokens_router.yaml_manager, "read_config", _config_with("refresh-abc")):
        res = client.get("/tokens")
    assert res.status_code == 200
    assert "Active" in res.text
    # Secrets are masked in the page — full values must not appear.
    assert "tok-secret-9999" not in res.text
    assert "****9999" in res.text


def test_tokens_page_status_needs_setup_with_device_code_only(harness):
    client, state = harness
    state.get.side_effect = lambda key, default=None: (
        "DEVICE-CODE" if key == "oauth_device_code" else default
    )
    with patch.object(tokens_router.yaml_manager, "read_config", _config_with("")):
        res = client.get("/tokens")
    assert res.status_code == 200
    assert "Needs Setup" in res.text


def test_tokens_page_status_unknown_with_neither(harness):
    client, _state = harness
    with patch.object(tokens_router.yaml_manager, "read_config", _config_with("")):
        res = client.get("/tokens")
    assert res.status_code == 200
    assert "Unknown" in res.text


def test_tokens_page_config_read_failure_falls_back(harness):
    client, _state = harness
    with patch.object(
        tokens_router.yaml_manager, "read_config",
        new_callable=AsyncMock, side_effect=RuntimeError("config gone"),
    ):
        res = client.get("/tokens")
    assert res.status_code == 200


def test_manual_pot_refresh_success_partial(harness):
    client, _state = harness
    with patch.object(tokens_router.pot, "refresh_and_inject", new_callable=AsyncMock):
        res = client.post("/tokens/refresh-pot")
    assert res.status_code == 200
    assert "refreshed" in res.text.lower()


def test_manual_pot_refresh_error_partial(harness):
    client, _state = harness
    with patch.object(
        tokens_router.pot, "refresh_and_inject",
        new_callable=AsyncMock, side_effect=RuntimeError("bgutil down"),
    ):
        res = client.post("/tokens/refresh-pot")
    assert res.status_code == 200
    assert "bgutil down" in res.text


def test_manual_oauth_rotate_success_and_error_partials(harness):
    client, _state = harness
    with patch.object(tokens_router.oauth, "rotate", new_callable=AsyncMock):
        res = client.post("/tokens/rotate-oauth")
    assert res.status_code == 200

    with patch.object(
        tokens_router.oauth, "rotate",
        new_callable=AsyncMock, side_effect=RuntimeError("docker down"),
    ):
        res = client.post("/tokens/rotate-oauth")
    assert res.status_code == 200
    assert "docker down" in res.text
