from fastapi import APIRouter, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

from app.services import lavalink, cipher, pot

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

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
        "request": request,
        "lavalink_healthy": lavalink_healthy,
        "cipher_healthy": cipher_healthy,
        "pot_healthy": pot_healthy
    }

    if hx_request:
        return templates.TemplateResponse("partials/health_cards.html", context)
    
    return templates.TemplateResponse("health.html", context)
