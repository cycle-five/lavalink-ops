import pytest
import httpx
from unittest.mock import patch, MagicMock

from app.services.lavalink import get_info, get_stats, load_tracks

@pytest.fixture
def mock_httpx_client():
    client = MagicMock(spec=httpx.AsyncClient)
    
    with patch("app.services.lavalink.get_http_client", return_value=client):
        with patch("app.services.lavalink.get_settings") as mock_settings:
            mock_set = MagicMock()
            mock_set.lavalink_url = "http://fake-lavalink:2333"
            mock_set.lavalink_password = "youshallnotpass"
            mock_settings.return_value = mock_set
            yield client

@pytest.mark.asyncio
async def test_get_info(mock_httpx_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"version": {"semver": "4.0.0"}}
    mock_httpx_client.get.return_value = mock_resp
    
    info = await get_info()
    assert info["version"]["semver"] == "4.0.0"
    
    mock_httpx_client.get.assert_called_once_with(
        "http://fake-lavalink:2333/v4/info", 
        headers={"Authorization": "youshallnotpass"}
    )

@pytest.mark.asyncio
async def test_load_tracks(mock_httpx_client):
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"loadType": "track", "data": {"info": {"title": "Test"}}}
    mock_httpx_client.get.return_value = mock_resp
    
    result = await load_tracks("ytsearch:test_query")
    assert result["loadType"] == "track"
    assert result["data"]["info"]["title"] == "Test"
    
    mock_httpx_client.get.assert_called_once_with(
        "http://fake-lavalink:2333/v4/loadtracks", 
        params={"identifier": "ytsearch:test_query"},
        headers={"Authorization": "youshallnotpass"}
    )
