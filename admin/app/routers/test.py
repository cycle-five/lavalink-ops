import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.services import lavalink

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))

@router.get("/test", response_class=HTMLResponse)
async def test_page(request: Request):
    """Render the Track Tester page."""
    return templates.TemplateResponse("test.html", {"request": request})

@router.post("/test/resolve", response_class=HTMLResponse)
async def resolve_track(request: Request, identifier: str = Form(...)):
    """Resolve a track identifier and return the result partial."""
    try:
        result = await lavalink.load_tracks(identifier)
        
        # If Lavalink 4: result contains loadType, data (track, playlist, search, error)
        load_type = result.get("loadType", "UNKNOWN")
        data = result.get("data", {})
        plugin_info = result.get("pluginInfo", {})
        
        # Format something readable
        if load_type == "empty":
            parsed_result = {"status": "No matches found."}
        elif load_type == "error":
            parsed_result = {
                "status": "Error loading track",
                "message": data.get("message"),
                "severity": data.get("severity")
            }
        elif load_type in ["track", "short"]: # 'short' might be standard in v4 single track? NO, v4 is 'track'
            track = data.get("info", data)
            parsed_result = {
                "status": "Success",
                "title": track.get("title"),
                "author": track.get("author"),
                "duration": track.get("length", track.get("duration", 0)),
                "source": plugin_info.get("clientName", track.get("sourceName", "Unknown"))
            }
        elif load_type == "playlist":
            parsed_result = {
                "status": f"Found Playlist: {data.get('info', {}).get('name')}",
                "track_count": len(data.get("tracks", []))
            }
        elif load_type == "search":
            tracks = data
            parsed_result = {
                "status": "Search Results",
                "first_match": tracks[0].get("info", {}).get("title") if tracks else "None",
                "source": plugin_info.get("clientName", tracks[0].get("info", {}).get("sourceName") if tracks else "Unknown")
            }
        else:
            parsed_result = {"status": f"Unknown LoadType: {load_type}", "raw": str(data)[:200]}

        
        context = {
            "request": request,
            "parsed": parsed_result,
            "raw": str(result)
        }
        return templates.TemplateResponse("partials/test_result.html", context)
        
    except Exception as e:
        context = {
            "request": request,
            "parsed": {"status": "Exception", "message": str(e)},
            "raw": ""
        }
        return templates.TemplateResponse("partials/test_result.html", context)
