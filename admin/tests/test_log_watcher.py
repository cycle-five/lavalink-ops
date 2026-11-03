"""Tests for the log watcher's line processing — the sole source of the
OAuth device code shown to the user. Previously untestable: the regexes and
state writes were inline in an infinite loop. ``process_log_line`` is the
extracted seam.
"""

import pytest

from app.services import log_watcher
from app.services.log_watcher import RECENT_LOGS, _get_next_chunk, process_log_line


class FakeState:
    def __init__(self):
        self.data = {}

    def set(self, key, value):
        self.data[key] = value

    def delete(self, key):
        self.data.pop(key, None)


@pytest.fixture(autouse=True)
def _clear_recent_logs():
    RECENT_LOGS.clear()
    yield
    RECENT_LOGS.clear()


def test_get_next_chunk_returns_next_item():
    assert _get_next_chunk(iter([b"a", b"b"])) == b"a"


def test_get_next_chunk_empty_stream_returns_none():
    assert _get_next_chunk(iter([])) is None


def test_get_next_chunk_exception_returns_none():
    def exploding():
        yield b"x"
        raise RuntimeError("stream died")

    stream = exploding()
    assert _get_next_chunk(stream) == b"x"
    assert _get_next_chunk(stream) is None


def test_process_line_oauth_code_sets_state_code_and_timestamp():
    state = FakeState()
    process_log_line("go to https://www.google.com/device and enter code ABCD-1234 now", state)
    assert state.data["oauth_device_code"] == "ABCD-1234"
    assert "oauth_timestamp" in state.data


def test_process_line_oauth_success_clears_code_and_sets_success():
    state = FakeState()
    state.set("oauth_device_code", "ABCD-1234")
    process_log_line("OAuth integration was successful", state)
    assert "oauth_device_code" not in state.data
    assert "oauth_success" in state.data


def test_process_line_oauth_success_is_case_insensitive():
    state = FakeState()
    process_log_line("oauth integration was successful", state)
    assert "oauth_success" in state.data


def test_process_line_unrelated_line_only_appends_to_recent_logs():
    state = FakeState()
    process_log_line("Track loaded: some song", state)
    assert state.data == {}
    assert list(RECENT_LOGS) == ["Track loaded: some song"]


@pytest.mark.asyncio
async def test_start_log_watcher_processes_stream_then_sleeps_on_eof(monkeypatch):
    """One loop iteration: a finite fake Docker stream is folded into state,
    then the EOF pause is where we cancel out of the infinite loop.
    (CancelledError is a BaseException, so the watcher's `except Exception`
    retry handler does not swallow it.)
    """
    import asyncio
    from unittest.mock import MagicMock, patch

    state = FakeState()
    container = MagicMock()
    container.logs.return_value = iter(
        [b"please enter code WATCH-42 at google.com/device\n", b"unrelated\n"]
    )
    docker_client = MagicMock()
    docker_client.containers.get.return_value = container
    settings = MagicMock()
    settings.lavalink_container_name = "lavalink"

    async def fake_sleep(_seconds):
        raise asyncio.CancelledError

    with patch.object(log_watcher, "get_settings", return_value=settings), \
         patch.object(log_watcher, "get_state", return_value=state), \
         patch.object(log_watcher, "get_docker_client", return_value=docker_client), \
         patch.object(log_watcher.asyncio, "sleep", fake_sleep):
        with pytest.raises(asyncio.CancelledError):
            await log_watcher.start_log_watcher()

    assert state.data["oauth_device_code"] == "WATCH-42"
    assert "unrelated" in list(RECENT_LOGS)


def test_recent_logs_ring_buffer_capped_at_500():
    state = FakeState()
    for i in range(550):
        process_log_line(f"line {i}", state)
    assert len(RECENT_LOGS) == 500
    assert RECENT_LOGS[0] == "line 50"
    assert log_watcher.RECENT_LOGS is RECENT_LOGS
