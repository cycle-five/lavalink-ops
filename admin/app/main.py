import asyncio
import hashlib
import hmac
import logging
import secrets
import time
from collections import defaultdict, deque
from contextlib import asynccontextmanager

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from app.dependencies import get_settings, set_http_client, get_http_client
from app.routers import dashboard, config, health, tokens, logs, test

# Initialize APScheduler (we'll start it in lifespan)
from apscheduler.schedulers.asyncio import AsyncIOScheduler


SESSION_MAX_AGE_SECONDS = 7 * 86400

LOGIN_WINDOW_SECONDS = 60
LOGIN_MAX_FAILURES = 5
_login_failures: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=LOGIN_MAX_FAILURES))


def _login_rate_limited(client_ip: str) -> bool:
    """True if this IP is locked out. Prunes old entries as a side effect."""
    if client_ip not in _login_failures:
        return False
    now = time.time()
    window_start = now - LOGIN_WINDOW_SECONDS
    attempts = _login_failures[client_ip]
    while attempts and attempts[0] < window_start:
        attempts.popleft()
    if not attempts:
        _login_failures.pop(client_ip, None)
        return False
    return len(attempts) >= LOGIN_MAX_FAILURES


def _record_login_failure(client_ip: str) -> None:
    _login_failures[client_ip].append(time.time())


def _clear_login_failures(client_ip: str) -> None:
    _login_failures.pop(client_ip, None)


def _sign_session(secret_key: str) -> str:
    """Mint a fresh session token: issued_at.nonce.hmac(issued_at.nonce)."""
    issued_at = int(time.time())
    nonce = secrets.token_hex(16)
    payload = f"{issued_at}.{nonce}"
    sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def _verify_session(cookie_value: str, secret_key: str) -> bool:
    """Verify the HMAC and reject expired tokens."""
    try:
        issued_at_str, nonce, sig = cookie_value.split(".", 2)
        issued_at = int(issued_at_str)
    except (ValueError, AttributeError):
        return False

    payload = f"{issued_at_str}.{nonce}"
    expected_sig = hmac.new(secret_key.encode(), payload.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False

    # Reject future-dated tokens too — clock skew could otherwise produce a
    # "valid for a very long time" window if a token was minted ahead of time.
    age = time.time() - issued_at
    return 0 <= age < SESSION_MAX_AGE_SECONDS

scheduler = AsyncIOScheduler()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup actions — cap the pool so a stalled upstream (Lavalink, yt-cipher,
    # bgutil) can't exhaust file descriptors while retries pile up.
    client = httpx.AsyncClient(
        timeout=10.0,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
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
        logger.info("Started scheduler for pot refresh every %sh", settings.pot_refresh_interval_hours)

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

        # Check authentication (HMAC-signed cookie)
        settings = get_settings()
        auth_cookie = request.cookies.get("admin_session")
        if not auth_cookie or not _verify_session(auth_cookie, settings.admin_secret_key):
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
    return templates.TemplateResponse(request=request, name="login.html")

@app.post("/do-login")
async def do_login(request: Request):
    client_ip = request.client.host if request.client else "unknown"

    if _login_rate_limited(client_ip):
        return templates.TemplateResponse(
            request=request,
            name="login.html",
            context={"error": f"Too many failed attempts. Try again in {LOGIN_WINDOW_SECONDS}s."},
            status_code=429,
        )

    form = await request.form()
    password = form.get("password")

    settings = get_settings()
    if password and hmac.compare_digest(password, settings.admin_password):
        _clear_login_failures(client_ip)
        response = RedirectResponse(url="/", status_code=303)
        response.set_cookie(
            key="admin_session",
            value=_sign_session(settings.admin_secret_key),
            httponly=True,
            secure=settings.admin_cookie_secure,
            samesite="lax",
            max_age=SESSION_MAX_AGE_SECONDS,
        )
        return response

    _record_login_failure(client_ip)
    return templates.TemplateResponse(
        request=request,
        name="login.html",
        context={"error": "Invalid password"},
        status_code=401,
    )

@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie("admin_session")
    return response

