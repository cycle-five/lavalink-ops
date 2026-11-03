"""Tests for ``app.services.oauth.rotate()`` — destructive-ish and previously
untested: it clears the OAuth refresh token in the real config, drops state
markers, and restarts Lavalink. Ordering matters and is pinned here.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.services import oauth


@pytest.fixture
def harness():
    settings = MagicMock()
    settings.config_path = "/fake/application.yml"
    settings.lavalink_container_name = "test-lavalink"

    state = MagicMock()
    lock = asyncio.Lock()
    written = {}

    def fake_write(data, path):
        written["data"] = data
        written["path"] = path

    patches = [
        patch("app.services.oauth.get_settings", return_value=settings),
        patch("app.services.oauth.get_state", return_value=state),
        patch("app.services.oauth.get_config_lock", return_value=lock),
        patch("app.services.oauth.read_config", new_callable=AsyncMock, return_value={}),
        patch("app.services.oauth.write_config_to_disk", side_effect=fake_write),
        patch("app.services.oauth.restart_container"),
    ]
    for p in patches:
        p.start()
    try:
        yield {
            "settings": settings,
            "state": state,
            "written": written,
            "restart": patches[-1],
        }
    finally:
        for p in reversed(patches):
            p.stop()


@pytest.mark.asyncio
async def test_rotate_clears_refresh_token_in_config(harness):
    await oauth.rotate()
    data = harness["written"]["data"]
    assert data["plugins"]["youtube"]["oauth"]["refreshToken"] == ""
    assert harness["written"]["path"] == "/fake/application.yml"


@pytest.mark.asyncio
async def test_rotate_deletes_device_code_timestamp_and_success_from_state(harness):
    await oauth.rotate()
    deleted = {c.args[0] for c in harness["state"].delete.call_args_list}
    assert deleted == {"oauth_device_code", "oauth_timestamp", "oauth_success"}


@pytest.mark.asyncio
async def test_rotate_restarts_lavalink_container(harness):
    await oauth.rotate()
    # restart_container is patched in the oauth module namespace; rotate()
    # calls it via asyncio.to_thread, so the mock records a normal call.
    from app.services import oauth as oauth_mod

    assert oauth_mod.restart_container.call_count == 1
    assert oauth_mod.restart_container.call_args.args[0] == "test-lavalink"


@pytest.mark.asyncio
async def test_rotate_propagates_restart_failure_after_clearing_token(harness):
    from app.services import oauth as oauth_mod

    oauth_mod.restart_container.side_effect = RuntimeError("docker down")
    with pytest.raises(RuntimeError, match="docker down"):
        await oauth.rotate()
    # Pin the ordering: the token is already cleared/written when the
    # restart fails. That's the current (arguably unfortunate) contract —
    # a failed rotate still forces a new device flow on next successful start.
    assert harness["written"]["data"]["plugins"]["youtube"]["oauth"]["refreshToken"] == ""
