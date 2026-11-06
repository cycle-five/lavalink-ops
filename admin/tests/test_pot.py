import pytest
import httpx
from unittest.mock import patch, MagicMock, AsyncMock, ANY

from app.services.pot import generate_token, push_token_live, refresh_and_inject

@pytest.fixture
def mock_httpx_client():
    client = MagicMock(spec=httpx.AsyncClient)
    
    with patch("app.services.pot.get_http_client", return_value=client):
        with patch("app.services.pot.get_settings") as mock_settings:
            mock_set = MagicMock()
            mock_set.bgutil_url = "http://fake-bgutil:4416"
            mock_set.lavalink_url = "http://fake-lavalink:2333"
            mock_set.lavalink_password = "fake-password"
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
async def test_push_token_live(mock_httpx_client):
    """The live push must hit POST /youtube on Lavalink with the password
    header and the refreshToken "x" sentinel, which is the route's way of
    saying "leave OAuth untouched" — omitting it or passing a real value
    would rotate OAuth as a side effect of a PoT refresh."""
    mock_resp = MagicMock()
    mock_httpx_client.post.return_value = mock_resp

    await push_token_live("po123", "vd123")

    mock_httpx_client.post.assert_called_once_with(
        "http://fake-lavalink:2333/youtube",
        headers={"Authorization": "fake-password"},
        json={"poToken": "po123", "visitorData": "vd123", "refreshToken": "x"},
        timeout=10.0,
    )
    mock_resp.raise_for_status.assert_called_once_with()


@pytest.mark.asyncio
@patch("app.services.pot.get_settings")
@patch("app.services.pot.get_state")
@patch("app.services.pot.write_config_to_disk")
@patch("app.services.pot.set_nested")
@patch("app.services.pot.read_config", new_callable=AsyncMock)
async def test_refresh_and_inject(mock_read_config, mock_set_nested, mock_write, mock_get_state, mock_get_settings, mock_httpx_client):
    # Settings
    mock_settings = MagicMock()
    mock_settings.lavalink_url = "http://fake-lavalink:2333"
    mock_settings.lavalink_password = "fake-password"
    mock_settings.config_path = "/fake/path.yml"
    mock_get_settings.return_value = mock_settings

    # State
    state_mock = MagicMock()
    state_mock.get.return_value = []
    mock_get_state.return_value = state_mock

    # read_config returns something mutable
    mock_read_config.return_value = {}

    # httpx: bgutil /get_pot returns the token pair; the Lavalink /youtube
    # push returns a bare response (raise_for_status is a mock no-op).
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"poToken": "po123", "contentBinding": "vd123"}
    mock_httpx_client.post.return_value = mock_resp

    await refresh_and_inject()

    # Two POSTs: bgutil token generation, then the live push to Lavalink.
    assert mock_httpx_client.post.call_count == 2
    live_call = mock_httpx_client.post.call_args_list[1]
    assert live_call.args[0] == "http://fake-lavalink:2333/youtube"
    assert live_call.kwargs["json"] == {
        "poToken": "po123", "visitorData": "vd123", "refreshToken": "x",
    }
    assert live_call.kwargs["headers"] == {"Authorization": "fake-password"}

    # The yaml write still happens — as the cold-start seed, not as the
    # delivery mechanism — and nothing restarts Lavalink anymore.
    assert mock_set_nested.call_count == 2
    mock_write.assert_called_once_with({}, "/fake/path.yml")
    state_mock.set.assert_any_call("pot_last_refresh", ANY)
    state_mock.set.assert_any_call("pot_history", ANY)


@pytest.mark.asyncio
@patch("app.services.pot.get_settings")
@patch("app.services.pot.get_state")
@patch("app.services.pot.write_config_to_disk")
@patch("app.services.pot.set_nested")
@patch("app.services.pot.read_config", new_callable=AsyncMock)
async def test_refresh_and_inject_reraises_on_partial_response(
    mock_read_config, mock_set_nested, mock_write, mock_get_state, mock_get_settings, mock_httpx_client
):
    """If bgutil returns an incomplete response, refresh_and_inject must
    raise (so the caller's error handling fires) AND record the failure to
    state. The earlier silent-success behavior masked real rotation
    failures behind a fake green toast."""
    mock_settings = MagicMock()
    mock_settings.lavalink_url = "http://fake-lavalink:2333"
    mock_settings.lavalink_password = "fake-password"
    mock_settings.config_path = "/fake/path.yml"
    mock_get_settings.return_value = mock_settings

    state_mock = MagicMock()
    state_mock.get.return_value = []
    mock_get_state.return_value = state_mock

    # bgutil returns poToken but no visitorData/contentBinding
    mock_resp = MagicMock()
    mock_resp.json.return_value = {"poToken": "po123"}
    mock_httpx_client.post.return_value = mock_resp

    with pytest.raises(ValueError, match="incomplete response"):
        await refresh_and_inject()

    # Failure was still recorded to state for the history view.
    state_mock.set.assert_any_call("pot_history", ANY)
    state_mock.set.assert_any_call("pot_last_refresh", ANY)
    # And we never pushed live or wrote the seed config.
    assert mock_httpx_client.post.call_count == 1
    mock_write.assert_not_called()


@pytest.mark.asyncio
@patch("app.services.pot.get_settings")
@patch("app.services.pot.get_state")
@patch("app.services.pot.write_config_to_disk")
@patch("app.services.pot.set_nested")
@patch("app.services.pot.read_config", new_callable=AsyncMock)
async def test_refresh_and_inject_reraises_on_live_push_failure(
    mock_read_config, mock_set_nested, mock_write, mock_get_state, mock_get_settings, mock_httpx_client
):
    """If the live POST /youtube push fails, the refresh must raise and
    record the failure, and the yaml seed must stay untouched — the token
    currently live in Lavalink and the seed on disk stay consistent."""
    mock_settings = MagicMock()
    mock_settings.lavalink_url = "http://fake-lavalink:2333"
    mock_settings.lavalink_password = "fake-password"
    mock_settings.config_path = "/fake/path.yml"
    mock_get_settings.return_value = mock_settings

    state_mock = MagicMock()
    state_mock.get.return_value = []
    mock_get_state.return_value = state_mock

    token_resp = MagicMock()
    token_resp.json.return_value = {"poToken": "po123", "contentBinding": "vd123"}
    push_resp = MagicMock()
    push_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "401", request=MagicMock(), response=MagicMock()
    )
    mock_httpx_client.post.side_effect = [token_resp, push_resp]

    with pytest.raises(httpx.HTTPStatusError):
        await refresh_and_inject()

    state_mock.set.assert_any_call("pot_history", ANY)
    mock_write.assert_not_called()
