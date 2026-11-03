"""Small pure-function tests: Settings URL properties/defaults and the
tokens page's ``_mask`` — a secret-leak boundary, so pin that the full
secret never appears in its output.
"""

import pytest
from pydantic import ValidationError

from app.config import Settings
from app.routers.tokens import _mask


def _settings(**overrides):
    base = {
        "admin_password": "a",
        "admin_secret_key": "s",
        "lavalink_password": "l",
    }
    base.update(overrides)
    return Settings(**base)


def test_url_properties_built_from_host_and_port():
    s = _settings(
        lavalink_host="10.0.0.1", lavalink_port=2333,
        cipher_host="10.0.0.2", cipher_port=8001,
        bgutil_host="10.0.0.3", bgutil_port=4416,
    )
    assert s.lavalink_url == "http://10.0.0.1:2333"
    assert s.cipher_url == "http://10.0.0.2:8001"
    assert s.bgutil_url == "http://10.0.0.3:4416"


def test_settings_defaults():
    s = _settings()
    assert s.admin_port == 8080
    assert s.admin_cookie_secure is False
    assert s.pot_refresh_enabled is True
    assert s.pot_refresh_interval_hours == 6
    assert s.lavalink_container_name == "lavalink"
    assert s.config_path == "/config/application.yml"
    assert s.state_path == "/state/state.json"


def test_settings_missing_required_field_raises(monkeypatch):
    # Required fields can also arrive via the environment (that's how
    # conftest supplies them), so clear the env before asserting that a
    # missing field is an error.
    for var in ("ADMIN_PASSWORD", "ADMIN_SECRET_KEY", "LAVALINK_PASSWORD"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ValidationError):
        Settings(admin_secret_key="s", lavalink_password="l", _env_file=None)


def test_mask_none_and_empty():
    assert _mask(None) == "None"
    assert _mask("") == "None"


def test_mask_short_value_fully_masked():
    assert _mask("abcd") == "****"
    assert _mask("a") == "****"


def test_mask_long_value_shows_last_four_only():
    secret = "super-secret-token-1234"
    masked = _mask(secret)
    assert masked == "****1234"
    assert secret not in masked
    assert "super" not in masked
