"""Extensions to ``test_yaml_manager.py``: direct ``get_nested``/``set_nested``
semantics, the invalid-output path of ``write_config_to_disk``, and a
contract test against the *shipped* ``config/application.yml``.

The contract test matters beyond YAML: ``setup.sh`` syncs secrets into that
file with sed patterns keyed purely on indentation, and ``pot.py`` /
``oauth.py`` write hard-coded paths (``plugins.youtube.pot.*``,
``plugins.youtube.oauth.refreshToken``). If someone restructures the shipped
YAML, those break silently — this test is the tripwire.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from ruamel.yaml.comments import CommentedMap

from app.services.yaml_manager import (
    get_nested,
    read_config,
    set_nested,
    validate_yaml_string,
    write_config_to_disk,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SHIPPED_CONFIG = REPO_ROOT / "config" / "application.yml"


def test_get_nested_missing_intermediate_returns_none():
    assert get_nested({"a": {}}, ["a", "b", "c"]) is None


def test_get_nested_through_scalar_returns_none():
    assert get_nested({"a": 5}, ["a", "b"]) is None


def test_set_nested_no_create_missing_raises_key_error():
    with pytest.raises(KeyError):
        set_nested({}, ["a", "b"], 1, create_missing=False)


def test_set_nested_no_create_through_scalar_raises_type_error():
    with pytest.raises(TypeError):
        set_nested({"a": 5}, ["a", "b"], 1, create_missing=False)


def test_set_nested_overwrites_scalar_with_map_when_creating():
    data = {"a": 5}
    set_nested(data, ["a", "b"], 1)
    assert data["a"]["b"] == 1


def test_write_config_to_disk_backup_content_matches_previous_file(tmp_path):
    cfg = tmp_path / "application.yml"
    cfg.write_text("old: true\n", encoding="utf-8")
    data = CommentedMap()
    data["new"] = True
    write_config_to_disk(data, str(cfg))
    assert (tmp_path / "application.yml.bak").read_text(encoding="utf-8") == "old: true\n"
    assert "new: true" in cfg.read_text(encoding="utf-8")


def test_write_config_to_disk_rejects_unserializable_and_keeps_original(tmp_path):
    cfg = tmp_path / "application.yml"
    cfg.write_text("old: true\n", encoding="utf-8")

    class Unserializable:
        pass

    data = CommentedMap()
    data["bad"] = Unserializable()
    with pytest.raises(Exception):
        write_config_to_disk(data, str(cfg))
    # Original file untouched, no tmp litter.
    assert cfg.read_text(encoding="utf-8") == "old: true\n"
    assert not (tmp_path / "application.yml.tmp").exists()


@pytest.mark.asyncio
async def test_validate_yaml_string_empty_returns_none():
    assert await validate_yaml_string("") is None


@pytest.mark.asyncio
async def test_read_config_missing_file_raises(tmp_path):
    missing = tmp_path / "nope.yml"
    with patch("app.services.yaml_manager.get_settings") as mock_settings:
        mock = MagicMock()
        mock.config_path = str(missing)
        mock_settings.return_value = mock
        with pytest.raises(FileNotFoundError):
            await read_config()


@pytest.mark.asyncio
async def test_real_application_yml_contract():
    assert SHIPPED_CONFIG.exists(), f"shipped config missing at {SHIPPED_CONFIG}"
    with patch("app.services.yaml_manager.get_settings") as mock_settings:
        mock = MagicMock()
        mock.config_path = str(SHIPPED_CONFIG)
        mock_settings.return_value = mock
        data = await read_config()

    # Paths pot.py and oauth.py write to — they must exist/resolve.
    assert get_nested(data, ["plugins", "youtube", "pot", "token"]) is not None
    assert "visitorData" in get_nested(data, ["plugins", "youtube", "pot"])
    assert "refreshToken" in get_nested(data, ["plugins", "youtube", "oauth"])
    assert get_nested(data, ["plugins", "youtube", "clients"])
    # Paths setup.sh's indentation-keyed sed rewrites.
    assert get_nested(data, ["lavalink", "server", "password"]) is not None
    assert get_nested(data, ["plugins", "youtube", "remoteCipher", "password"]) is not None
    assert get_nested(data, ["plugins", "youtube", "remoteCipher", "url"])
