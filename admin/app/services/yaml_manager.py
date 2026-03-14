import os
import shutil
from typing import Any, List

from ruamel.yaml import YAML
from ruamel.yaml.comments import CommentedMap

from app.dependencies import get_settings, get_config_lock

def _get_yaml_instance() -> YAML:
    yaml = YAML(typ='rt')
    yaml.preserve_quotes = True
    yaml.indent(mapping=2, sequence=4, offset=2)
    return yaml


async def read_config() -> CommentedMap:
    """Read the configuration YAML file, preserving comments."""
    settings = get_settings()
    yaml = _get_yaml_instance()
    
    # We do file I/O synchrnously here, but since it's a small config file
    # and we protect with a lock during writes, it should be fine.
    # In a full-blown async app we might use aiofiles.
    with open(settings.config_path, "r", encoding="utf-8") as f:
        return yaml.load(f)


def _write_config_to_disk(data: CommentedMap, config_path: str) -> None:
    """Internal: write config to disk with backup and validation. Caller must hold lock."""
    # 1. Create backup
    if os.path.exists(config_path):
        backup_path = f"{config_path}.bak"
        shutil.copy2(config_path, backup_path)

    # 2. Write to a temporary file first
    tmp_path = f"{config_path}.tmp"
    yaml = _get_yaml_instance()
    with open(tmp_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f)

    # 3. Validate the written YAML structure
    try:
        with open(tmp_path, "r", encoding="utf-8") as f:
            _get_yaml_instance().load(f)
    except Exception as e:
        os.remove(tmp_path)
        raise RuntimeError(f"Failed to generate valid YAML: {e}")

    # 4. Atomic replace
    os.replace(tmp_path, config_path)


async def write_config(data: CommentedMap) -> None:
    """Write back the configuration, preserving comments and creating a backup."""
    settings = get_settings()
    lock = get_config_lock()

    async with lock:
        _write_config_to_disk(data, settings.config_path)


def _get_nested(data: dict, path: List[str]) -> Any:
    current = data
    for key in path:
        if isinstance(current, dict) and key in current:
            current = current[key]
        else:
            return None
    return current


def _set_nested(data: dict, path: List[str], value: Any, create_missing: bool = True) -> None:
    current = data
    for key in path[:-1]:
        if key not in current:
            if create_missing:
                current[key] = CommentedMap()
            else:
                raise KeyError(f"Key '{key}' not found in path {path}")
        elif not isinstance(current[key], dict):
            if create_missing:
                current[key] = CommentedMap()
            else:
                raise TypeError(f"Key '{key}' is not a dictionary in path {path}")
        current = current[key]
    
    current[path[-1]] = value


async def get_config_field(path: List[str]) -> Any:
    """Read a specific nested field from the config."""
    data = await read_config()
    return _get_nested(data, path)


async def update_config_field(path: List[str], value: Any) -> None:
    """Navigate nested keys, update value, write file while preserving comments."""
    lock = get_config_lock()
    async with lock:
        settings = get_settings()
        yaml = _get_yaml_instance()

        with open(settings.config_path, "r", encoding="utf-8") as f:
            data = yaml.load(f)

        _set_nested(data, path, value)
        _write_config_to_disk(data, settings.config_path)


async def validate_yaml_string(yaml_str: str) -> CommentedMap:
    """Parse a YAML string to ensure it's valid, returning the CommentedMap if so."""
    yaml = _get_yaml_instance()
    # Ruamel loads from stream or string
    # We load it, which raises if invalid
    return yaml.load(yaml_str)
