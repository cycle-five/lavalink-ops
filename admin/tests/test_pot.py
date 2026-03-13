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
@patch("app.services.pot.update_config_field", new_callable=AsyncMock)
@patch("app.services.pot.get_state")
@patch("app.services.pot.restart_container")
async def test_refresh_and_inject(mock_restart, mock_get_state, mock_update, mock_httpx_client):
    state_mock = MagicMock()
    state_mock.get.return_value = []
    mock_get_state.return_value = state_mock
    
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"poToken": "po123", "contentBinding": "vd123"}
    mock_httpx_client.post.return_value = mock_resp
    
    await refresh_and_inject()
    
    # Verify config update called twice (token, visitor)
    assert mock_update.call_count == 2
    
    # Verify docker restart called
    mock_restart.assert_called_once_with("test-lavalink")
    
    # Verify state logged the success
    from unittest.mock import ANY
    state_mock.set.assert_any_call("pot_last_refresh", ANY)
    state_mock.set.assert_any_call("pot_history", ANY)

