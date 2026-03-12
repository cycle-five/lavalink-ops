import asyncio
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.dependencies import get_settings, set_http_client, get_http_client
from app.routers import dashboard, config, health, tokens, logs, test

# Initialize APScheduler (we'll start it in lifespan)
from apscheduler.schedulers.asyncio import AsyncIOScheduler

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions
    client = httpx.AsyncClient(timeout=10.0)
    set_http_client(client)
    
    settings = get_settings()
    if settings.pot_refresh_enabled:
        from app.services.pot import refresh_and_inject
        # Schedule the pot refresh task
        scheduler.add_job(
            refresh_and_inject, 
            'interval', 
            hours=settings.pot_refresh_interval_hours,
            id='pot_refresh'
        )
        scheduler.start()
        print(f"Started scheduler for pot refresh every {settings.pot_refresh_interval_hours}h")

    # Start the log watcher background task
    from app.services.log_watcher import start_log_watcher
    app.state.log_watcher_task = asyncio.create_task(start_log_watcher())

    yield

    # Shutdown actions
    client = get_http_client()
    await client.aclose()
    
    if scheduler.running:
        scheduler.shutdown()
        
    if hasattr(app.state, "log_watcher_task"):
        app.state.log_watcher_task.cancel()


app = FastAPI(title="Lavalink Ops Admin", lifespan=lifespan)

# Setup Templates and Static Files
import os
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(BASE_DIR, "templates"))
app.mount("/static", StaticFiles(directory=os.path.join(BASE_DIR, "static")), name="static")


class BasicAuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Allow requests to static files
        if request.url.path.startswith("/static"):
            return await call_next(request)
            
        # Allow login page itself
        if request.url.path == "/login" or request.url.path == "/do-login":
            return await call_next(request)

        # Check authentication (simple cookie)
        settings = get_settings()
        auth_cookie = request.cookies.get("admin_session")
        if auth_cookie != settings.admin_password:
            # For HTMX requests, we should redirect using HX-Redirect header
            if request.headers.get("HX-Request"):
                response = Response(status_code=401)
                response.headers["HX-Redirect"] = "/login"
                return response
            return RedirectResponse(url="/login", status_code=303)
            
        return await call_next(request)

app.add_middleware(BasicAuthMiddleware)


# Routes
app.include_router(dashboard.router)
app.include_router(health.router)
app.include_router(config.router)
app.include_router(tokens.router)
app.include_router(logs.router)
app.include_router(test.router)

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/do-login")
async def do_login(request: Request):
    form = await request.form()
    password = form.get("password")
    
    settings = get_settings()
    if password == settings.admin_password:
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="admin_session", 
            value=settings.admin_password, # In a real app we'd sign this with admin_secret_key, but simple is ok here based on prompt
            httponly=True,
            samesite="lax"
        )
        return response
        
    # Login failed
    return templates.TemplateResponse(
        "login.html", 
        {"request": request, "error": "Invalid password"}, 
        status_code=401
    )

@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("admin_session")
    return response

