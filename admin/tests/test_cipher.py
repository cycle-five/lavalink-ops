"""Tests for ``app.services.cipher`` and the health halves of
``lavalink``/``pot`` — same httpx pattern as the existing lavalink tests,
previously at zero coverage.
"""

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services import cipher, lavalink, pot


def _mock_client(status_code=200, json_data=None, text=""):
    client = MagicMock(spec=httpx.AsyncClient)
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = text
    client.get = AsyncMock(return_value=resp)
    client.post = AsyncMock(return_value=resp)
    return client


@pytest.fixture
def settings():
    s = MagicMock()
    s.cipher_url = "http://fake-cipher:8001"
    s.bgutil_url = "http://fake-bgutil:4416"
    s.lavalink_url = "http://fake-lavalink:2333"
    s.lavalink_password = "pw"
    return s


@pytest.mark.asyncio
async def test_cipher_is_healthy_true_on_200(settings):
    client = _mock_client(200)
    with patch("app.services.cipher.get_http_client", return_value=client), \
         patch("app.services.cipher.get_settings", return_value=settings):
        assert await cipher.is_healthy() is True
    client.get.assert_called_once_with("http://fake-cipher:8001/", timeout=5.0)


@pytest.mark.asyncio
async def test_cipher_is_healthy_false_on_500(settings):
    client = _mock_client(500)
    with patch("app.services.cipher.get_http_client", return_value=client), \
         patch("app.services.cipher.get_settings", return_value=settings):
        assert await cipher.is_healthy() is False


@pytest.mark.asyncio
async def test_cipher_is_healthy_false_on_exception(settings):
    client = MagicMock(spec=httpx.AsyncClient)
    client.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch("app.services.cipher.get_http_client", return_value=client), \
         patch("app.services.cipher.get_settings", return_value=settings):
        assert await cipher.is_healthy() is False


@pytest.mark.asyncio
async def test_cipher_get_status_wraps_is_healthy(settings):
    client = _mock_client(200)
    with patch("app.services.cipher.get_http_client", return_value=client), \
         patch("app.services.cipher.get_settings", return_value=settings):
        assert await cipher.get_status() == {"healthy": True}


@pytest.mark.asyncio
async def test_pot_is_healthy_true_false_exception(settings):
    with patch("app.services.pot.get_http_client", return_value=_mock_client(200)), \
         patch("app.services.pot.get_settings", return_value=settings):
        assert await pot.is_healthy() is True

    with patch("app.services.pot.get_http_client", return_value=_mock_client(503)), \
         patch("app.services.pot.get_settings", return_value=settings):
        assert await pot.is_healthy() is False

    bad = MagicMock(spec=httpx.AsyncClient)
    bad.get = AsyncMock(side_effect=httpx.ConnectError("down"))
    with patch("app.services.pot.get_http_client", return_value=bad), \
         patch("app.services.pot.get_settings", return_value=settings):
        assert await pot.is_healthy() is False


@pytest.mark.asyncio
async def test_lavalink_get_stats(settings):
    client = _mock_client(200, json_data={"players": 3})
    with patch("app.services.lavalink.get_http_client", return_value=client), \
         patch("app.services.lavalink.get_settings", return_value=settings):
        assert await lavalink.get_stats() == {"players": 3}
    args, _ = client.get.call_args
    assert args[0] == "http://fake-lavalink:2333/v4/stats"


@pytest.mark.asyncio
async def test_lavalink_get_version_returns_text_not_json(settings):
    client = _mock_client(200, text="4.0.0")
    with patch("app.services.lavalink.get_http_client", return_value=client), \
         patch("app.services.lavalink.get_settings", return_value=settings):
        assert await lavalink.get_version() == "4.0.0"


@pytest.mark.asyncio
async def test_lavalink_is_healthy_true_and_false_on_http_error(settings):
    with patch("app.services.lavalink.get_http_client", return_value=_mock_client(200, text="4")), \
         patch("app.services.lavalink.get_settings", return_value=settings):
        assert await lavalink.is_healthy() is True

    resp_client = _mock_client(500)
    resp_client.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    with patch("app.services.lavalink.get_http_client", return_value=resp_client), \
         patch("app.services.lavalink.get_settings", return_value=settings):
        assert await lavalink.is_healthy() is False


@pytest.mark.asyncio
async def test_lavalink_get_info_raises_on_500(settings):
    client = _mock_client(500)
    client.get.return_value.raise_for_status.side_effect = httpx.HTTPStatusError(
        "500", request=MagicMock(), response=MagicMock()
    )
    with patch("app.services.lavalink.get_http_client", return_value=client), \
         patch("app.services.lavalink.get_settings", return_value=settings):
        with pytest.raises(httpx.HTTPStatusError):
            await lavalink.get_info()
