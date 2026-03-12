from app.dependencies import get_settings, get_http_client


async def is_healthy() -> bool:
    """Check yt-cipher health by asserting a 200 OK from the root."""
    try:
        client = get_http_client()
        settings = get_settings()
        
        # Depending on yt-cipher image, / or /health 
        res = await client.get(f"{settings.cipher_url}/", timeout=5.0)
        return res.status_code == 200
    except Exception:
        return False


async def get_status() -> dict:
    """Return status endpoint if available, else standard health check."""
    status = await is_healthy()
    return {"healthy": status}
