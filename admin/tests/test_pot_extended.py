"""Extensions to ``test_pot.py``: token-mapping precedence, HTTP errors,
history truncation/appending, and the failure-recording contract of
``refresh_and_inject`` (record error to state, re-raise; on failure before
the live push completes, no seed write either).
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.pot import generate_token, refresh_and_inject


def _client_returning(json_data):
    client = MagicMock(spec=httpx.AsyncClient)
    resp = MagicMock()
    resp.json.return_value = json_data
    client.post = AsyncMock(return_value=resp)
    return client


def _settings():
    s = MagicMock()
    s.bgutil_url = "http://fake-bgutil:4416"
    s.lavalink_url = "http://fake-lavalink:2333"
    s.lavalink_password = "fake-password"
    s.lavalink_container_name = "test-lavalink"
    s.config_path = "/fake/path.yml"
    return s


@pytest.mark.asyncio
async def test_generate_token_prefers_visitor_data_over_content_binding():
    client = _client_returning(
        {"poToken": "po", "visitorData": "vd-real", "contentBinding": "vd-fallback"}
    )
    with patch("app.services.pot.get_http_client", return_value=client), \
         patch("app.services.pot.get_settings", return_value=_settings()):
        data = await generate_token()
    assert data == {"poToken": "po", "visitorData": "vd-real"}


@pytest.mark.asyncio
async def test_generate_token_both_visitor_fields_missing_returns_none():
    client = _client_returning({"poToken": "po"})
    with patch("app.services.pot.get_http_client", return_value=client), \
         patch("app.services.pot.get_settings", return_value=_settings()):
        data = await generate_token()
    assert data["visitorData"] is None


@pytest.mark.asyncio
async def test_generate_token_raises_on_http_error():
    client = _client_returning({})
    client.post.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    with patch("app.services.pot.get_http_client", return_value=client), \
         patch("app.services.pot.get_settings", return_value=_settings()):
        with pytest.raises(httpx.HTTPStatusError):
            await generate_token()


def _refresh_harness(existing_history):
    """Patch refresh_and_inject's collaborators; return the mocks + state."""
    state = MagicMock()
    state.get.return_value = list(existing_history)
    client = _client_returning({"poToken": "po123", "visitorData": "vd123"})
    patches = {
        "get_settings": patch("app.services.pot.get_settings", return_value=_settings()),
        "get_state": patch("app.services.pot.get_state", return_value=state),
        "get_http_client": patch("app.services.pot.get_http_client", return_value=client),
        "read_config": patch(
            "app.services.pot.read_config", new_callable=AsyncMock, return_value={}
        ),
        "write": patch("app.services.pot.write_config_to_disk"),
    }
    for p in patches.values():
        p.start()
    return state, client, patches


def _stop(patches):
    for p in patches.values():
        p.stop()


@pytest.mark.asyncio
async def test_refresh_history_truncated_to_10():
    existing = [{"status": "success", "i": i} for i in range(10)]
    state, _client, patches = _refresh_harness(existing)
    try:
        await refresh_and_inject()
    finally:
        _stop(patches)
    history_calls = [c for c in state.set.call_args_list if c.args[0] == "pot_history"]
    assert len(history_calls) == 1
    new_history = history_calls[0].args[1]
    assert len(new_history) == 10
    assert new_history[-1]["status"] == "success"
    # Oldest entry was dropped to make room.
    assert new_history[0].get("i") == 1


@pytest.mark.asyncio
async def test_refresh_generate_failure_records_error_and_reraises_without_write():
    state = MagicMock()
    state.get.return_value = []
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=httpx.ConnectError("bgutil down"))
    with patch("app.services.pot.get_settings", return_value=_settings()), \
         patch("app.services.pot.get_state", return_value=state), \
         patch("app.services.pot.get_http_client", return_value=client), \
         patch("app.services.pot.read_config", new_callable=AsyncMock, return_value={}), \
         patch("app.services.pot.write_config_to_disk") as mock_write:
        with pytest.raises(httpx.ConnectError):
            await refresh_and_inject()
    history_calls = [c for c in state.set.call_args_list if c.args[0] == "pot_history"]
    assert history_calls[0].args[1][-1]["status"] == "error"
    mock_write.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_live_push_failure_records_error_and_reraises():
    """Phase 0 ordering: the live push happens *before* the seed write, so
    a rejected push leaves the on-disk seed matching the token Lavalink is
    actually still running with."""
    state = MagicMock()
    state.get.return_value = []
    token_resp = MagicMock()
    token_resp.json.return_value = {"poToken": "po123", "visitorData": "vd123"}
    push_resp = MagicMock()
    push_resp.raise_for_status.side_effect = RuntimeError("lavalink rejected")
    client = MagicMock(spec=httpx.AsyncClient)
    client.post = AsyncMock(side_effect=[token_resp, push_resp])
    with patch("app.services.pot.get_settings", return_value=_settings()), \
         patch("app.services.pot.get_state", return_value=state), \
         patch("app.services.pot.get_http_client", return_value=client), \
         patch("app.services.pot.read_config", new_callable=AsyncMock, return_value={}), \
         patch("app.services.pot.write_config_to_disk") as mock_write:
        with pytest.raises(RuntimeError, match="lavalink rejected"):
            await refresh_and_inject()
    # Push failed before the seed write; the error is recorded.
    mock_write.assert_not_called()
    history_calls = [c for c in state.set.call_args_list if c.args[0] == "pot_history"]
    assert history_calls[0].args[1][-1]["status"] == "error"
