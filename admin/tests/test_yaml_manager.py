import os
import shutil
import pytest
from unittest.mock import patch, MagicMock
from ruamel.yaml import YAML

from app.services.yaml_manager import read_config, write_config, update_config_field, get_config_field, validate_yaml_string

DUMMY_YML = """
# Lavalink Config
lavalink:
  server:
    password: "old_password" # This is a comment
plugins:
  youtube:
    oauth:
      enabled: false
"""

@pytest.fixture
def temp_config(tmp_path):
    config_file = tmp_path / "application.yml"
    config_file.write_text(DUMMY_YML)
    
    with patch("app.services.yaml_manager.get_settings") as mock_settings:
        mock = MagicMock()
        mock.config_path = str(config_file)
        mock_settings.return_value = mock
        yield str(config_file)

@pytest.mark.asyncio
async def test_read_config(temp_config):
    data = await read_config()
    assert data["lavalink"]["server"]["password"] == "old_password"

@pytest.mark.asyncio
async def test_update_config_field(temp_config):
    await update_config_field(["lavalink", "server", "password"], "new_password")
    
    # Reload to verify
    data = await read_config()
    assert data["lavalink"]["server"]["password"] == "new_password"
    
    # Verify comment was preserved
    with open(temp_config, "r") as f:
        content = f.read()
        assert "# This is a comment" in content

@pytest.mark.asyncio
async def test_create_missing_nested_fields(temp_config):
    await update_config_field(["plugins", "youtube", "pot", "token"], "abc1234")
    
    data = await read_config()
    assert data["plugins"]["youtube"]["pot"]["token"] == "abc1234"

@pytest.mark.asyncio
async def test_get_config_field(temp_config):
    val = await get_config_field(["plugins", "youtube", "oauth", "enabled"])
    assert val is False
    
    val2 = await get_config_field(["not_exist"])
    assert val2 is None

@pytest.mark.asyncio
async def test_validate_yaml_string():
    # Valid
    data = await validate_yaml_string("test: true")
    assert data["test"] is True
    
    # Invalid
    with pytest.raises(Exception):
        await validate_yaml_string("test: true\ninvalid: [")

@pytest.mark.asyncio
async def test_backup_creation(temp_config):
    await update_config_field(["lavalink", "server", "password"], "test")
    assert os.path.exists(temp_config + ".bak")
