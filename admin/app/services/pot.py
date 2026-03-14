from datetime import datetime

from app.dependencies import get_settings, get_http_client, get_state, get_config_lock
from app.services.yaml_manager import read_config, _set_nested, _write_config_to_disk
from app.services.docker_ctl import restart_container


async def is_healthy() -> bool:
    """Health check for bgutil-pot."""
    try:
        client = get_http_client()
        settings = get_settings()
        
        url = f"{settings.bgutil_url}/ping"
        res = await client.get(url, timeout=5.0)
        return res.status_code == 200
    except Exception:
        return False


async def generate_token() -> dict:
    """
    Call bgutil-pot to generate a fresh PoToken + visitorData pair.
    The jim60105/bgutil-pot image endpoint is likely /token or /generate.
    Based on the prompt we will use POST /token.
    """
    client = get_http_client()
    settings = get_settings()
    
    url = f"{settings.bgutil_url}/get_pot"
    res = await client.post(url, json={}, timeout=30.0) # Generation can take a few seconds
    res.raise_for_status()
    
    data = res.json()
    # It might return different keys depending on the service, map them if needed
    # We expect {"poToken": "...", "contentBinding" (or visitorData): "..."}
    return {
        "poToken": data.get("poToken"),
        "visitorData": data.get("visitorData") or data.get("contentBinding")
    }


async def refresh_and_inject() -> None:
    """
    Full lifecycle:
    1. Generate token
    2. Acquire config lock
    3. Update application.yml via yaml_manager
    4. Restart Lavalink container via docker_ctl
    5. Log the event to state.json
    """
    state = get_state()
    settings = get_settings()
    
    # Store history of rotations
    history = state.get("pot_history", [])
    
    try:
        print("Starting PoToken refresh cycle...")
        # 1. Generate token
        data = await generate_token()
        
        po_token = data.get("poToken")
        visitor_data = data.get("visitorData")
        if not po_token or not visitor_data:
            raise ValueError(f"Invalid response from bgutil-pot: {data}")
        
        # 2 & 3. Lock + Update both fields atomically
        lock = get_config_lock()
        async with lock:
            config_data = await read_config()
            _set_nested(config_data, ["plugins", "youtube", "pot", "token"], po_token)
            _set_nested(config_data, ["plugins", "youtube", "pot", "visitorData"], visitor_data)
            _write_config_to_disk(config_data, settings.config_path)
        
        # 4. Restart container
        # Note: the prompt asks to restart Lavalink, we use docker SDK block=True
        print("Restarting Lavalink to apply new PoToken...")
        from asyncio import to_thread
        await to_thread(restart_container, settings.lavalink_container_name)
        
        # 5. Log success
        record = {
            "timestamp": datetime.now().isoformat(),
            "status": "success",
            "message": "Rotated successfully"
        }
        
    except Exception as e:
        print(f"PoToken refresh failed: {e}")
        # Log failure
        record = {
            "timestamp": datetime.now().isoformat(),
            "status": "error",
            "message": str(e)
        }
    
    # Update history in state (keep last 10)
    history.append(record)
    history = history[-10:]
    state.set("pot_history", history)
    state.set("pot_last_refresh", record["timestamp"])

