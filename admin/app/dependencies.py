import asyncio
import json
import os
import tempfile
from functools import lru_cache
from typing import Any, Dict

import docker
import httpx

from app.config import Settings

# Global state / singletons
_http_client: httpx.AsyncClient | None = None
_docker_client: docker.DockerClient | None = None
_config_lock = asyncio.Lock()


@lru_cache()
def get_settings() -> Settings:
    return Settings()


def set_http_client(client: httpx.AsyncClient):
    global _http_client
    _http_client = client


def get_http_client() -> httpx.AsyncClient:
    if _http_client is None:
        raise RuntimeError("HTTP Client not initialized.")
    return _http_client


def get_docker_client() -> docker.DockerClient:
    global _docker_client
    if _docker_client is None:
        _docker_client = docker.from_env()
    return _docker_client


def get_config_lock() -> asyncio.Lock:
    return _config_lock


class StateStore:
    def __init__(self, state_path: str):
        self.state_path = state_path
        self._ensure_dir()

    def _ensure_dir(self):
        os.makedirs(os.path.dirname(self.state_path), exist_ok=True)

    def read(self) -> Dict[str, Any]:
        """Read the entire state dictionary."""
        if not os.path.exists(self.state_path):
            return {}
        try:
            with open(self.state_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, IOError):
            return {}

    def write(self, state: Dict[str, Any]) -> None:
        """Write the entire state dictionary atomically.

        Tempfile + os.replace only needs write permission on the directory,
        not the existing file — sidesteps stale ownership (e.g. a state.json
        left over from when admin ran as root) and prevents partial writes
        if the process is killed mid-flush.
        """
        self._ensure_dir()
        directory = os.path.dirname(self.state_path)
        fd, tmp_path = tempfile.mkstemp(prefix=".state-", suffix=".tmp", dir=directory)
        try:
            # Wrap the raw fd in a file object as the very next step. If
            # fdopen itself raises (extremely rare — e.g. memory pressure)
            # the bare fd would otherwise leak.
            try:
                f = os.fdopen(fd, "w", encoding="utf-8")
            except Exception:
                os.close(fd)
                raise
            with f:
                json.dump(state, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_path, self.state_path)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def get(self, key: str, default: Any = None) -> Any:
        state = self.read()
        return state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        state = self.read()
        state[key] = value
        self.write(state)

    def delete(self, key: str) -> None:
        state = self.read()
        if key in state:
            del state[key]
            self.write(state)

@lru_cache()
def get_state() -> StateStore:
    settings = get_settings()
    return StateStore(settings.state_path)
