import os
from fastapi import APIRouter, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates

from app.dependencies import get_config_lock
from app.services import yaml_manager, docker_ctl

router = APIRouter()
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))


@router.get("/config", response_class=HTMLResponse)
async def config_page(request: Request):
    """Render the configuration page."""
    # We will load the yaml explicitly for the raw editor
    settings = yaml_manager.get_settings()
    try:
        with open(settings.config_path, "r", encoding="utf-8") as f:
            raw_yaml = f.read()
    except Exception:
        raw_yaml = ""
        
    config_data = await yaml_manager.read_config()
    password = yaml_manager._get_nested(config_data, ["lavalink", "server", "password"]) or ""
    
    plugins = yaml_manager._get_nested(config_data, ["plugins", "youtube"]) or {}
    
    clients = plugins.get("clients", ["MUSIC", "WEB", "WEBEMBEDDED", "TVHTML5EMBEDDED"])
    
    oauth_enabled = yaml_manager._get_nested(plugins, ["oauth", "enabled"])
    oauth_refresh = yaml_manager._get_nested(plugins, ["oauth", "refreshToken"]) or ""
    
    pot_token = yaml_manager._get_nested(plugins, ["pot", "token"]) or ""
    pot_visitor = yaml_manager._get_nested(plugins, ["pot", "visitorData"]) or ""
    
    pot_enabled = yaml_manager._get_nested(plugins, ["pot", "token"]) is not None # Best guess enabled
    
    context = {
        "request": request,
        "raw_yaml": raw_yaml,
        "password": password,
        "clients": clients,
        "oauth_enabled": bool(oauth_enabled),
        "oauth_refresh": oauth_refresh,
        "pot_token": pot_token,
        "pot_visitor": pot_visitor,
        "pot_enabled": pot_enabled
    }
    return templates.TemplateResponse("config.html", context)


@router.post("/config/save-form")
async def save_form(
    request: Request,
    password: str = Form(""),
    clients: list[str] = Form([]),
    oauth_enabled: bool = Form(False),
    oauth_refresh: str = Form(""),
    pot_token: str = Form(""),
    pot_visitor: str = Form("")
):
    try:
        lock = get_config_lock()
        async with lock:
            config_data = await yaml_manager.read_config()

            yaml_manager._set_nested(config_data, ["lavalink", "server", "password"], password)
            yaml_manager._set_nested(config_data, ["plugins", "youtube", "clients"], clients)
            yaml_manager._set_nested(config_data, ["plugins", "youtube", "oauth", "enabled"], oauth_enabled)

            if oauth_refresh:
                yaml_manager._set_nested(config_data, ["plugins", "youtube", "oauth", "refreshToken"], oauth_refresh)

            if pot_token and pot_visitor:
                yaml_manager._set_nested(config_data, ["plugins", "youtube", "pot", "token"], pot_token)
                yaml_manager._set_nested(config_data, ["plugins", "youtube", "pot", "visitorData"], pot_visitor)

            yaml_manager._write_config_to_disk(config_data, yaml_manager.get_settings().config_path)

        return templates.TemplateResponse("partials/save_success.html", {"request": request, "message": "Config saved successfully!"})
    except Exception as e:
        return templates.TemplateResponse("partials/save_error.html", {"request": request, "error": str(e)})


@router.post("/config/save-raw")
async def save_raw(request: Request, raw_yaml: str = Form(...)):
    try:
        data = await yaml_manager.validate_yaml_string(raw_yaml)
        if data is None:
            raise ValueError("Empty or invalid YAML")
        await yaml_manager.write_config(data)
        return templates.TemplateResponse("partials/save_success.html", {"request": request, "message": "Raw YAML saved successfully!"})
    except Exception as e:
        return templates.TemplateResponse("partials/save_error.html", {"request": request, "error": f"Invalid YAML: {e}"})

@router.post("/config/restart")
async def restart_container(request: Request):
    """Restart Lavalink via docker client."""
    from app.dependencies import get_settings
    settings = get_settings()
    try:
        # Use simple await if we implemented it properly with asyncio.to_thread, otherwise run in executor
        import asyncio
        await asyncio.to_thread(docker_ctl.restart_container, settings.lavalink_container_name)
        return templates.TemplateResponse("partials/save_success.html", {"request": request, "message": "Lavalink restarted successfully!"})
    except Exception as e:
        return templates.TemplateResponse("partials/save_error.html", {"request": request, "error": f"Restart failed: {e}"})

