from fastapi import APIRouter, Request, Header
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

from app.services.lavalink import get_info, get_stats

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@router.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, hx_request: str | None = Header(default=None)):
    """
    Render the main dashboard.
    If it's an HTMX request, just return the inner stats partial
    so it can auto-refresh without a full page reload.
    """
    try:
        info = await get_info()
        stats = await get_stats()
        error = None
    except Exception as e:
        info = {}
        stats = {}
        error = f"Failed to fetch Lavalink data: {str(e)}"

    context = {
        "request": request,
        "info": info,
        "stats": stats,
        "error": error
    }

    if hx_request:
        return templates.TemplateResponse("partials/dashboard_stats.html", context)
    
    return templates.TemplateResponse("dashboard.html", context)
