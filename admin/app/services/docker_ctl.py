import logging
from datetime import datetime
from typing import Generator

import docker

from app.dependencies import get_docker_client


def get_container(name: str) -> docker.models.containers.Container:
    """Retrieve a Docker container by name."""
    client = get_docker_client()
    try:
        return client.containers.get(name)
    except docker.errors.NotFound:
        raise ValueError(f"Container '{name}' not found.")
    except Exception as e:
        raise RuntimeError(f"Error getting container '{name}': {e}")


def get_container_status(name: str) -> str:
    """Return the container's status: 'running', 'stopped', 'restarting', 'unknown'."""
    try:
        container = get_container(name)
        return container.status
    except ValueError:
        return "not_found"
    except Exception:
        return "unknown"


def restart_container(name: str, timeout: int = 10) -> None:
    """Restart the specified container, waiting up to `timeout` seconds before killing."""
    try:
        container = get_container(name)
        # Using block=True so it waits until restarted
        container.restart(timeout=timeout)
    except Exception as e:
        raise RuntimeError(f"Failed to restart container '{name}': {e}")


def get_container_logs(name: str, tail: int = 100, since: datetime | None = None) -> str:
    """Fetch the recent log output (stdout/stderr) from the container."""
    try:
        container = get_container(name)
        # docker-py logs() method returns bytes
        logs_bytes = container.logs(tail=tail, since=since, stream=False)
        return logs_bytes.decode('utf-8', errors='replace')
    except Exception as e:
        return f"Failed to get logs for {name}: {e}"


def stream_logs(name: str) -> Generator[str, None, None]:
    """Provide a streaming generator for the container logs."""
    try:
        container = get_container(name)
        # docker-py logs() with stream=True yields bytestrings (chunks)
        # It's an iterator that yields logs in the background 
        log_stream = container.logs(stream=True, tail=100, follow=True)
        for chunk in log_stream:
            yield chunk.decode('utf-8', errors='replace')
    except docker.errors.NotFound:
        yield f"Container {name} not found.\n"
    except Exception as e:
        yield f"Stream interrupted: {e}\n"
