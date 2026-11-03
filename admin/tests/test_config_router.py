"""Tests for the config router — it writes the *real* Lavalink config, so
its conditional-write logic is worth pinning:

- ``oauth_refresh`` is only written when truthy (an empty form field must
  not wipe the stored refresh token),
- PoT token/visitor are only written as a pair,
- ``spotify_country_code`` only when truthy,
- raw saves reject empty/invalid YAML without touching the file.
"""

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from ruamel.yaml import YAML

from app.routers import config as config_router

BASE_YML = """\
lavalink:
  server:
    password: "pw"
plugins:
  youtube:
    clients: [MUSIC, TV]
    oauth:
      enabled: true
      refreshToken: "existing-refresh"
    pot:
      token: "old-token"
      visitorData: "old-visitor"
  lavasrc:
    sources:
      spotify: false
    spotify:
      clientId: ""
      clientSecret: ""
      countryCode: "US"
"""


@pytest.fixture
def harness(tmp_path):
    cfg = tmp_path / "application.yml"
    cfg.write_text(BASE_YML, encoding="utf-8")

    settings = MagicMock()
    settings.config_path = str(cfg)
    settings.lavalink_container_name = "lavalink"

    app = FastAPI()
    app.include_router(config_router.router)
    client = TestClient(app)

    def read_back():
        return cfg.read_text(encoding="utf-8")

    def parsed():
        return YAML(typ="rt").load(read_back())

    with patch.object(config_router, "get_settings", return_value=settings), \
         patch("app.services.yaml_manager.get_settings", return_value=settings):
        yield client, cfg, parsed


def _save_form(client, **overrides):
    form = {
        "clients": ["MUSIC", "WEB"],
        "oauth_enabled": "true",
        "oauth_refresh": "",
        "pot_token": "",
        "pot_visitor": "",
        "spotify_enabled": "false",
        "spotify_client_id": "",
        "spotify_client_secret": "",
        "spotify_country_code": "US",
    }
    form.update(overrides)
    return client.post("/config/save-form", data=form)


def test_save_form_writes_clients_and_oauth_enabled(harness):
    client, _cfg, parsed = harness
    res = _save_form(client)
    assert res.status_code == 200
    data = parsed()
    assert list(data["plugins"]["youtube"]["clients"]) == ["MUSIC", "WEB"]
    assert data["plugins"]["youtube"]["oauth"]["enabled"] is True


def test_save_form_empty_oauth_refresh_does_not_overwrite_existing(harness):
    client, _cfg, parsed = harness
    _save_form(client, oauth_refresh="")
    assert parsed()["plugins"]["youtube"]["oauth"]["refreshToken"] == "existing-refresh"


def test_save_form_oauth_refresh_written_when_present(harness):
    client, _cfg, parsed = harness
    _save_form(client, oauth_refresh="new-refresh")
    assert parsed()["plugins"]["youtube"]["oauth"]["refreshToken"] == "new-refresh"


def test_save_form_pot_written_only_when_both_fields_present(harness):
    client, _cfg, parsed = harness
    _save_form(client, pot_token="new-token", pot_visitor="")
    data = parsed()
    assert data["plugins"]["youtube"]["pot"]["token"] == "old-token"

    _save_form(client, pot_token="new-token", pot_visitor="new-visitor")
    data = parsed()
    assert data["plugins"]["youtube"]["pot"]["token"] == "new-token"
    assert data["plugins"]["youtube"]["pot"]["visitorData"] == "new-visitor"


def test_save_form_empty_country_code_preserves_existing(harness):
    client, _cfg, parsed = harness
    _save_form(client, spotify_country_code="")
    assert parsed()["plugins"]["lavasrc"]["spotify"]["countryCode"] == "US"


def test_save_raw_valid_yaml_writes_and_returns_success(harness):
    client, _cfg, parsed = harness
    res = client.post("/config/save-raw", data={"raw_yaml": "lavalink:\n  server:\n    password: changed\n"})
    assert res.status_code == 200
    assert parsed()["lavalink"]["server"]["password"] == "changed"


def test_save_raw_invalid_yaml_returns_error_and_does_not_write(harness):
    client, cfg, _parsed = harness
    before = cfg.read_text(encoding="utf-8")
    res = client.post("/config/save-raw", data={"raw_yaml": "a: [unclosed"})
    assert res.status_code == 200
    assert "Invalid YAML" in res.text
    assert cfg.read_text(encoding="utf-8") == before


def test_save_raw_empty_yaml_rejected(harness):
    client, cfg, _parsed = harness
    before = cfg.read_text(encoding="utf-8")
    res = client.post("/config/save-raw", data={"raw_yaml": "   \n"})
    assert res.status_code == 200
    assert cfg.read_text(encoding="utf-8") == before


def test_restart_success_and_failure_partials(harness):
    client, _cfg, _parsed = harness
    with patch.object(config_router.docker_ctl, "restart_container") as mock_restart:
        res = client.post("/config/restart")
    assert res.status_code == 200
    mock_restart.assert_called_once_with("lavalink")

    with patch.object(
        config_router.docker_ctl, "restart_container",
        side_effect=RuntimeError("docker down"),
    ):
        res = client.post("/config/restart")
    assert res.status_code == 200
    assert "docker down" in res.text


def test_config_page_renders_values_from_real_config_shape(harness):
    client, _cfg, _parsed = harness
    res = client.get("/config")
    assert res.status_code == 200
    assert "existing-refresh" in res.text or "old-token" in res.text
