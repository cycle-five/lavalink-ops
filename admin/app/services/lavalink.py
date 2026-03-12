import httpx

from app.dependencies import get_settings, get_http_client


def _get_headers() -> dict:
    settings = get_settings()
    return {"Authorization": settings.lavalink_password}


async def get_info() -> dict:
    """GET /v4/info (node info, plugins, version)"""
    client = get_http_client()
    settings = get_settings()
    
    url = f"{settings.lavalink_url}/v4/info"
    res = await client.get(url, headers=_get_headers())
    res.raise_for_status()
    return res.json()


async def get_stats() -> dict:
    """GET /v4/stats (players, memory, CPU, uptime)"""
    client = get_http_client()
    settings = get_settings()
    
    url = f"{settings.lavalink_url}/v4/stats"
    res = await client.get(url, headers=_get_headers())
    res.raise_for_status()
    return res.json()


async def get_version() -> str:
    """GET /version"""
    client = get_http_client()
    settings = get_settings()
    
    url = f"{settings.lavalink_url}/version"
    # /version doesn't strictly need auth, but it's fine 
    res = await client.get(url, headers=_get_headers())
    res.raise_for_status()
    return res.text


async def load_tracks(identifier: str) -> dict:
    """GET /v4/loadtracks?identifier={identifier} (for track tester)"""
    client = get_http_client()
    settings = get_settings()
    
    url = f"{settings.lavalink_url}/v4/loadtracks"
    res = await client.get(url, params={"identifier": identifier}, headers=_get_headers())
    res.raise_for_status()
    return res.json()


async def is_healthy() -> bool:
    """Try get_version(), return True/False gracefully."""
    try:
        await get_version()
        return True
    except Exception:
        return False
