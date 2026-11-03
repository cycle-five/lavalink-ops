import asyncio
import logging
import re
from collections import deque
from datetime import datetime

from app.dependencies import get_settings, get_state, get_docker_client

logger = logging.getLogger(__name__)

# Ring buffer for recent logs, accessible via routers
RECENT_LOGS = deque(maxlen=500)

# Regex patterns
# go to https://www.google.com/device and enter code XXXX
OAUTH_CODE_PATTERN = re.compile(r"enter code ([A-Z0-9-]+)")
OAUTH_SUCCESS_PATTERN = re.compile(r"OAuth integration was successful", re.IGNORECASE)


def process_log_line(line: str, state) -> None:
    """Fold one Lavalink log line into the ring buffer and OAuth state.

    Extracted from ``start_log_watcher`` so the parsing/state transitions —
    the part that decides which device code the user sees on the Tokens
    page — can be unit-tested without a Docker log stream or an infinite
    loop. ``state`` is anything with the StateStore ``set``/``delete``
    interface.
    """
    RECENT_LOGS.append(line)

    match = OAUTH_CODE_PATTERN.search(line)
    if match:
        code = match.group(1)
        state.set("oauth_device_code", code)
        state.set("oauth_timestamp", datetime.now().isoformat())
        logger.info("Found OAuth device code in Lavalink logs")

    if OAUTH_SUCCESS_PATTERN.search(line):
        state.delete("oauth_device_code")
        state.set("oauth_success", datetime.now().isoformat())
        logger.info("OAuth success detected")


async def start_log_watcher():
    """Background task to tail Lavalink logs, parse errors/OAuth codes, and update state."""
    settings = get_settings()
    state = get_state()
    container_name = settings.lavalink_container_name

    # Run loop
    while True:
        try:
            client = get_docker_client()
            container = client.containers.get(container_name)

            # Use lower level API for non-blocking stream if possible, or simple generator in a thread
            log_stream = container.logs(stream=True, follow=True, tail=100)

            # Since this is a simple implementation, we iterate over the blocking generator in the async loop
            # using asyncio.to_thread but per chunk.
            while True:
                # Get next chunk in a background thread to avoid blocking event loop
                chunk = await asyncio.to_thread(_get_next_chunk, log_stream)
                if not chunk:
                    break

                line = chunk.decode('utf-8', errors='replace').strip()
                if not line:
                    continue

                process_log_line(line, state)

            # Clean EOF on the stream (e.g., Lavalink restarted). Pause before
            # reconnecting so a crash-looping container doesn't hot-spin us.
            await asyncio.sleep(5)
        except Exception:
            logger.exception("Log watcher failed, retrying in 10s")
            await asyncio.sleep(10)

def _get_next_chunk(stream):
    try:
        return next(stream, None)
    except StopIteration:
        return None
    except Exception:
        return None
