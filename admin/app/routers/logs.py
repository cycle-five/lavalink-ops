import os
from fastapi import APIRouter, Request, Query, Header
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_settings
from app.services.log_watcher import RECENT_LOGS
from app.services.docker_ctl import get_container_logs

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@router.get("/logs", response_class=HTMLResponse)
async def logs_page(request: Request):
    """Render the log viewer."""
    context = {"request": request}
    return templates.TemplateResponse("logs.html", context)

@router.get("/logs/stream", response_class=HTMLResponse)
async def stream_logs(
    request: Request,
    filter_type: str = Query("all"),
    tail: int = Query(100)
):
    """
    Return recent log lines as an HTMX partial.
    Called every few seconds via HTMX polling on the logs page.
    """
    settings = get_settings()
    
    # Normally we'd fetch directly from RECENT_LOGS buff, 
    # but if they want N tail that exceeds buffer, we use docker SDK.
    if tail <= len(RECENT_LOGS):
        # We slice from the deque
        # Deque doesn't support slicing directly without itertools
        import itertools
        lines = list(itertools.islice(RECENT_LOGS, max(0, len(RECENT_LOGS) - tail), len(RECENT_LOGS)))
    else:
        # Fallback to docker socket to grab larger chunk
        raw_logs = get_container_logs(settings.lavalink_container_name, tail=tail)
        lines = raw_logs.splitlines()

    # Apply pseudo-filters
    filtered_lines = []
    for line in lines:
        lower = line.lower()
        if filter_type == "errors" and ("error" not in lower and "warn" not in lower and "exception" not in lower):
            continue
        if filter_type == "youtube" and "youtube" not in lower:
            continue
        if filter_type == "oauth" and "oauth" not in lower and "device" not in lower:
            continue
        
        filtered_lines.append(line)

    context = {
        "request": request,
        "logs": filtered_lines
    }
    return templates.TemplateResponse("partials/log_lines.html", context)
