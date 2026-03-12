import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_settings, get_state
from app.services import yaml_manager, pot

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@router.get("/tokens", response_class=HTMLResponse)
async def tokens_page(request: Request, hx_request: str | None = Header(default=None)):
    """Render the Tokens & OAuth status dashboard."""
    settings = get_settings()
    state = get_state()
    
    # Read config for current tokens
    try:
        config_data = await yaml_manager.read_config()
        oauth_refresh = yaml_manager._get_nested(config_data, ["plugins", "youtube", "oauth", "refreshToken"])
        pot_token = yaml_manager._get_nested(config_data, ["plugins", "youtube", "pot", "token"])
        pot_visitor = yaml_manager._get_nested(config_data, ["plugins", "youtube", "pot", "visitorData"])
    except Exception:
        oauth_refresh, pot_token, pot_visitor = None, None, None

    context = {
        "request": request,
        "pot_token_preview": f"{pot_token[:8]}...{pot_token[-8:]}" if pot_token else "None",
        "pot_visitor_preview": visitor_preview(pot_visitor),
        "pot_last_refresh": state.get("pot_last_refresh", "Never"),
        "pot_history": state.get("pot_history", []),
        "pot_auto_refresh": settings.pot_refresh_enabled,
        "pot_interval": settings.pot_refresh_interval_hours,
        "oauth_device_code": state.get("oauth_device_code"),
        "oauth_status": "Active" if oauth_refresh else ("Needs Setup" if state.get("oauth_device_code") else "Unknown"),
    }

    if hx_request:
        return templates.TemplateResponse("partials/tokens_content.html", context)

    return templates.TemplateResponse("tokens.html", context)


def visitor_preview(visitor: Optional[str]) -> str:
    if not visitor:
        return "None"
    return f"{visitor[:5]}...{visitor[-5:]}" if len(visitor) > 10 else visitor


@router.post("/tokens/refresh-pot")
async def manual_pot_refresh(request: Request):
    """Trigger a manual PoToken refresh."""
    try:
        # Long running background task so we don't timeout the request, but we want 
        # to show success. Let's run it inline but potentially it takes 15s.
        await pot.refresh_and_inject()
        return templates.TemplateResponse("partials/save_success.html", {"request": request, "message": "PoToken refreshed and Lavalink restarted!"})
    except Exception as e:
        return templates.TemplateResponse("partials/save_error.html", {"request": request, "error": f"Refresh failed: {e}"})

