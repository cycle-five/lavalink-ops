import logging
from asyncio import to_thread

from app.dependencies import get_settings, get_state, get_config_lock
from app.services.yaml_manager import read_config, set_nested, write_config_to_disk
from app.services.docker_ctl import restart_container

logger = logging.getLogger(__name__)


async def rotate() -> None:
    """Clear the OAuth refresh token and restart Lavalink so it begins a new
    device-code flow. The log watcher will pick up the new code and surface it
    on the Tokens page within ~30s of restart.

    Use this when switching to a new burner Google account or when the
    current refresh token has been invalidated by Google (account
    termination, password change, suspicious-activity revocation).
    """
    settings = get_settings()
    state = get_state()
    lock = get_config_lock()

    async with lock:
        config_data = await read_config()
        set_nested(config_data, ["plugins", "youtube", "oauth", "refreshToken"], "")
        write_config_to_disk(config_data, settings.config_path)

    # Drop stale state markers — the next device code we see is for the new
    # flow, not an artifact from the previous one.
    state.delete("oauth_device_code")
    state.delete("oauth_timestamp")
    state.delete("oauth_success")

    logger.info("Restarting Lavalink to begin new OAuth device-code flow")
    await to_thread(restart_container, settings.lavalink_container_name)
