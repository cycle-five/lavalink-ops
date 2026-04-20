import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock

from app.services.pot import generate_token, refresh_and_inject

@pytest.fixture
def mock_httpx_client():
    client = MagicMock(spec=httpx.AsyncClient)
    
    with patch("app.services.pot.get_http_client", return_value=client):
        with patch("app.services.pot.get_settings") as mock_settings:
            mock_set = MagicMock()
            mock_set.bgutil_url = "http://fake-bgutil:4416"
            mock_set.lavalink_container_name = "test-lavalink"
            mock_settings.return_value = mock_set
            yield client


@pytest.mark.asyncio
async def test_generate_token(mock_httpx_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"poToken": "po123", "contentBinding": "vd123"}
    mock_httpx_client.post.return_value = mock_resp
    
    data = await generate_token()
    assert data["poToken"] == "po123"
    assert data["visitorData"] == "vd123"


@pytest.mark.asyncio
@patch("app.services.pot.get_settings")
@patch("app.services.pot.restart_container")
@patch("app.services.pot.get_state")
@patch("app.services.pot.write_config_to_disk")
@patch("app.services.pot.set_nested")
@patch("app.services.pot.read_config", new_callable=AsyncMock)
async def test_refresh_and_inject(mock_read_config, mock_set_nested, mock_write, mock_get_state, mock_restart, mock_get_settings, mock_httpx_client):
    # Settings
    mock_settings = MagicMock()
    mock_settings.lavalink_container_name = "test-lavalink"
    mock_settings.config_path = "/fake/path.yml"
    mock_get_settings.return_value = mock_settings

    # State
    state_mock = MagicMock()
    state_mock.get.return_value = []
    mock_get_state.return_value = state_mock

    # read_config returns something mutable
    mock_read_config.return_value = {}

    # httpx
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"poToken": "po123", "contentBinding": "vd123"}
    mock_httpx_client.post.return_value = mock_resp

    await refresh_and_inject()

    
    # Verify state logged the success
    from unittest.mock import ANY
    # Two set_nested calls (token + visitorData)
    assert mock_set_nested.call_count == 2
    mock_write.assert_called_once_with({}, "/fake/path.yml")
    mock_restart.assert_called_once_with("test-lavalink")
    state_mock.set.assert_any_call("pot_last_refresh", ANY)
    state_mock.set.assert_any_call("pot_history", ANY)
