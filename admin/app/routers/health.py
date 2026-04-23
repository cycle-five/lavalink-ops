import asyncio
import os
from datetime import datetime, timezone

from fastapi import APIRouter, Request, Header
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.services import lavalink, cipher, pot

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


# Probes Lavalink is the only one that gates everything else, so it's the only
# component that flips the aggregate to 503. cipher and pot are reported but
# treated as advisory — yt-cipher/bgutil-pot can be temporarily down without
# the node being unusable for non-YouTube sources.
_PROBES = {
    "lavalink": (lavalink.is_healthy, True),
    "cipher": (cipher.is_healthy, False),
    "pot": (pot.is_healthy, False),
}


@router.get("/health", response_class=HTMLResponse)
async def health_page(request: Request, hx_request: str | None = Header(default=None)):
    """
    Render the health checks dashboard.
    If it's an HTMX request, return the partial component.
    """
    lavalink_healthy = await lavalink.is_healthy()
    cipher_healthy = await cipher.is_healthy()
    pot_healthy = await pot.is_healthy()

    context = {
        "lavalink_healthy": lavalink_healthy,
        "cipher_healthy": cipher_healthy,
        "pot_healthy": pot_healthy,
        "now": datetime.now
    }

    if hx_request:
        return templates.TemplateResponse(request=request, name="partials/health_cards.html", context=context)

    return templates.TemplateResponse(request=request, name="health.html", context=context)


@router.get("/healthz")
async def healthz_aggregate():
    """Aggregate JSON health for external monitors (CloudWatch, Uptime Kuma, etc).

    Returns 200 when every critical service is up, 503 if any critical service
    is down. The JSON body always includes per-service state so monitors can
    alert on advisory-only failures (cipher, pot) too.
    """
    names = list(_PROBES.keys())
    results = await asyncio.gather(
        *(probe() for probe, _ in _PROBES.values()),
        return_exceptions=True,
    )

    services: dict[str, str] = {}
    critical_down = False
    for name, ok in zip(names, results):
        healthy = ok is True
        services[name] = "ok" if healthy else "down"
        if not healthy and _PROBES[name][1]:
            critical_down = True

    body = {
        "status": "down" if critical_down else "ok",
        "services": services,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(body, status_code=503 if critical_down else 200)


@router.get("/healthz/{service}")
async def healthz_service(service: str):
    """Per-service probe — 200 if up, 503 if down, 404 for unknown service."""
    probe = _PROBES.get(service)
    if probe is None:
        return JSONResponse({"status": "unknown", "service": service}, status_code=404)

    try:
        healthy = await probe[0]()
    except Exception:
        healthy = False

    body = {
        "status": "ok" if healthy else "down",
        "service": service,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    return JSONResponse(body, status_code=200 if healthy else 503)
