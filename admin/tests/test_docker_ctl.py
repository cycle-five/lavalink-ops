"""Tests for ``app.services.docker_ctl`` — every restart/log path in the
panel funnels through here, and its error-translation contract is subtle:
``get_container`` raises, ``get_container_status`` returns sentinel strings,
``get_container_logs`` *returns* an error string instead of raising.
"""

from unittest.mock import MagicMock, patch

import docker
import pytest

from app.services import docker_ctl


def _not_found(msg="no such container"):
    return docker.errors.NotFound(msg, response=MagicMock(status_code=404))


@pytest.fixture
def fake_container():
    container = MagicMock()
    container.status = "running"
    container.logs.return_value = "line1\nline2\n".encode()
    return container


@pytest.fixture
def fake_client(fake_container):
    client = MagicMock()
    client.containers.get.return_value = fake_container
    return client


@pytest.fixture(autouse=True)
def _patch_client(fake_client):
    with patch("app.services.docker_ctl.get_docker_client", return_value=fake_client):
        yield fake_client


def test_get_container_returns_container(fake_container):
    assert docker_ctl.get_container("lavalink") is fake_container


def test_get_container_not_found_raises_value_error(fake_client):
    fake_client.containers.get.side_effect = _not_found()
    with pytest.raises(ValueError, match="not found"):
        docker_ctl.get_container("ghost")


def test_get_container_api_error_raises_runtime_error(fake_client):
    fake_client.containers.get.side_effect = docker.errors.APIError("daemon exploded")
    with pytest.raises(RuntimeError, match="Error getting container"):
        docker_ctl.get_container("lavalink")


def test_get_container_status_running(fake_client, fake_container):
    fake_container.status = "running"
    assert docker_ctl.get_container_status("lavalink") == "running"


def test_get_container_status_not_found(fake_client):
    fake_client.containers.get.side_effect = _not_found()
    assert docker_ctl.get_container_status("ghost") == "not_found"


def test_get_container_status_unknown_on_error(fake_client):
    fake_client.containers.get.side_effect = docker.errors.APIError("boom")
    assert docker_ctl.get_container_status("lavalink") == "unknown"


def test_restart_container_calls_restart_with_timeout(fake_container):
    docker_ctl.restart_container("lavalink")
    fake_container.restart.assert_called_once_with(timeout=10)


def test_restart_container_custom_timeout(fake_container):
    docker_ctl.restart_container("lavalink", timeout=30)
    fake_container.restart.assert_called_once_with(timeout=30)


def test_restart_container_failure_raises_runtime_error(fake_container):
    fake_container.restart.side_effect = RuntimeError("restart blew up")
    with pytest.raises(RuntimeError, match="Failed to restart"):
        docker_ctl.restart_container("lavalink")


def test_restart_missing_container_raises_runtime_error(fake_client):
    # get_container's ValueError is re-wrapped by restart_container — callers
    # only ever see RuntimeError out of a restart. Pin that.
    fake_client.containers.get.side_effect = _not_found()
    with pytest.raises(RuntimeError, match="Failed to restart"):
        docker_ctl.restart_container("ghost")


def test_get_container_logs_decodes_utf8_with_replace(fake_container):
    fake_container.logs.return_value = b"ok \xff\xfe bytes\n"
    out = docker_ctl.get_container_logs("lavalink", tail=50)
    assert out.startswith("ok ")
    assert out.endswith(" bytes\n")
    fake_container.logs.assert_called_once()
    _, kwargs = fake_container.logs.call_args
    assert kwargs["tail"] == 50


def test_get_container_logs_failure_returns_error_string_not_raise(fake_client):
    fake_client.containers.get.side_effect = _not_found()
    out = docker_ctl.get_container_logs("ghost")
    assert out.startswith("Failed to get logs for ghost:")


def test_stream_logs_yields_decoded_chunks(fake_container):
    fake_container.logs.return_value = iter([b"one\n", b"two\n"])
    assert list(docker_ctl.stream_logs("lavalink")) == ["one\n", "two\n"]


def test_stream_logs_missing_container_yields_not_found_message(fake_client):
    fake_client.containers.get.side_effect = _not_found()
    assert list(docker_ctl.stream_logs("ghost")) == ["Container ghost not found.\n"]


def test_stream_logs_failure_yields_interrupted_message(fake_container):
    def exploding_logs(**kwargs):
        raise RuntimeError("stream died")

    fake_container.logs.side_effect = exploding_logs
    out = list(docker_ctl.stream_logs("lavalink"))
    assert len(out) == 1
    assert out[0].startswith("Stream interrupted:")
