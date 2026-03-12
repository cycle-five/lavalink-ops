# Claude Code Prompt — lavalink-ops Admin Panel

You are building the admin panel for `lavalink-ops`, a self-hosted Lavalink audio node stack with YouTube anti-detection. The infrastructure (docker-compose, Lavalink config, Dockerfile, pyproject.toml) is already scaffolded. Your job is to implement the FastAPI admin panel.

## Context

Read these files first to understand the full architecture:
- `DESIGN.md` — full architecture, component details, design decisions, anticipated issues
- `docker-compose.yml` — service topology and networking
- `config/application.yml` — Lavalink configuration (this is what the admin panel manages)
- `admin/Dockerfile` — build context
- `admin/pyproject.toml` — dependencies (fastapi, jinja2, httpx, ruamel.yaml, docker, apscheduler, pydantic-settings)
- `.env.example` — environment variables

## Tech Stack

- **Python 3.12**, **FastAPI** with **Jinja2** templates + **htmx** for dynamic updates
- **Tailwind CSS via CDN** for styling, **Alpine.js via CDN** for minimal client-side interactivity
- **ruamel.yaml** for comment-preserving YAML manipulation
- **docker** (Python SDK) for container management via socket
- **httpx** (async) for calling Lavalink, yt-cipher, and bgutil-pot APIs
- **APScheduler** for cron-based PoToken refresh
- **pydantic-settings** for config from env vars

## File Structure to Implement

```
admin/app/
├── __init__.py
├── main.py               # FastAPI app, lifespan events, middleware
├── config.py             # pydantic-settings: Settings class
├── dependencies.py       # Shared deps: docker client, httpx clients, config lock
├── routers/
│   ├── __init__.py
│   ├── dashboard.py      # GET / — stats dashboard
│   ├── config.py         # Config editor (form + raw YAML)
│   ├── health.py         # Service health checks
│   ├── tokens.py         # PoToken + OAuth management
│   ├── logs.py           # Log viewer
│   └── test.py           # Track resolution tester
├── services/
│   ├── __init__.py
│   ├── lavalink.py       # Lavalink REST API client
│   ├── cipher.py         # yt-cipher health check
│   ├── pot.py            # bgutil-pot client + refresh logic
│   ├── yaml_manager.py   # ruamel.yaml config read/write with file locking
│   ├── docker_ctl.py     # Docker SDK: restart, status, log streaming
│   └── log_watcher.py    # Parse Docker logs for OAuth codes + errors
├── templates/
│   ├── base.html         # Layout shell
│   ├── dashboard.html
│   ├── config.html
│   ├── config_form.html  # htmx partial
│   ├── health.html
│   ├── tokens.html
│   ├── logs.html
│   └── test.html
└── static/               # Favicon, any non-CDN assets
```

## Implementation Instructions

### 1. `app/config.py` — Settings

Use pydantic-settings to load all env vars. Key fields:
- `admin_password: str`
- `admin_secret_key: str`
- `admin_port: int = 8080`
- `lavalink_host: str = "lavalink"`
- `lavalink_port: int = 2333`
- `lavalink_password: str`
- `cipher_host: str = "yt-cipher"`
- `cipher_port: int = 8001`
- `bgutil_host: str = "bgutil-pot"`
- `bgutil_port: int = 4416`
- `pot_refresh_enabled: bool = True`
- `pot_refresh_interval_hours: int = 6`
- `lavalink_container_name: str = "lavalink"`
- `config_path: str = "/config/application.yml"`
- `state_path: str = "/state/state.json"`

Computed properties for base URLs: `lavalink_url`, `cipher_url`, `bgutil_url`.

### 2. `app/dependencies.py` — Shared State

Create singleton-style dependencies:
- `get_settings()` → cached Settings instance
- `get_http_client()` → shared `httpx.AsyncClient` (created in lifespan)
- `get_docker_client()` → `docker.DockerClient.from_env()`
- `get_config_lock()` → `asyncio.Lock` for serializing config mutations
- `get_state()` → simple JSON state store (read/write to state.json) for persisting OAuth codes, rotation history, etc.

### 3. `app/main.py` — App Setup

- FastAPI app with lifespan handler
- On startup: create httpx client, initialize APScheduler for PoToken refresh, start log watcher background task
- On shutdown: close httpx client, shutdown scheduler
- Mount static files, include all routers
- Simple middleware: check `Authorization` header or session cookie against `ADMIN_PASSWORD`
  - Use a simple bearer token or basic auth — nothing fancy
  - Login page at `/login` with a form that sets a signed cookie
  - All other routes protected

### 4. `app/services/yaml_manager.py` — Config Management

This is critical — get it right:
- Use `ruamel.yaml` with `YAML(typ='rt')` (round-trip) to preserve comments and formatting
- `async def read_config() -> CommentedMap` — load application.yml
- `async def write_config(data: CommentedMap)` — write back, preserving comments
- `async def update_config_field(path: list[str], value: Any)` — navigate nested keys, update value, write
- `async def get_config_field(path: list[str]) -> Any` — read a specific nested field
- All write operations must acquire the config lock from dependencies
- Validate YAML before writing (parse it back to check for syntax errors)
- Keep a single backup (application.yml.bak) before each write

Example paths:
- `["plugins", "youtube", "pot", "token"]` → PoToken value
- `["plugins", "youtube", "oauth", "enabled"]` → OAuth toggle
- `["plugins", "youtube", "clients"]` → client list
- `["lavalink", "server", "password"]` → server password

### 5. `app/services/lavalink.py` — Lavalink API Client

Async httpx calls to Lavalink's REST API. All requests need `Authorization: {password}` header.
- `async def get_info() -> dict` — `GET /v4/info` (node info, plugins, version)
- `async def get_stats() -> dict` — `GET /v4/stats` (players, memory, CPU, uptime)
- `async def get_version() -> str` — `GET /version`
- `async def load_tracks(identifier: str) -> dict` — `GET /v4/loadtracks?identifier={identifier}` (for track tester)
- `async def is_healthy() -> bool` — try get_version(), return True/False
- Handle connection errors gracefully — Lavalink may be restarting

### 6. `app/services/cipher.py` — yt-cipher Client

- `async def is_healthy() -> bool` — GET to cipher base URL, check for 200
- `async def get_status() -> dict` — any status/info endpoint if available, else just health

### 7. `app/services/pot.py` — PoToken Manager

This integrates with bgutil-pot's HTTP API:
- `async def is_healthy() -> bool` — health check
- `async def generate_token() -> dict` — call bgutil-pot to generate a fresh PoToken + visitorData pair
  - The exact API depends on the bgutil-pot image. It may be `POST /token` or `POST /generate`. Check the jim60105/bgutil-pot docs. If the endpoint isn't clear, make it configurable.
  - Return `{"poToken": "...", "visitorData": "..."}`
- `async def refresh_and_inject()` — full lifecycle:
  1. Generate token
  2. Acquire config lock
  3. Update application.yml via yaml_manager
  4. Restart Lavalink container via docker_ctl
  5. Log the event to state.json

### 8. `app/services/docker_ctl.py` — Container Management

- `def get_container(name: str) -> Container` — get by name
- `def get_container_status(name: str) -> str` — running/stopped/restarting
- `def restart_container(name: str) -> None` — restart with timeout
- `def get_container_logs(name: str, tail: int = 100, since: datetime = None) -> str` — fetch recent logs
- `def stream_logs(name: str) -> Generator` — streaming generator for log viewer

### 9. `app/services/log_watcher.py` — Log Parser

Background async task that:
- Streams Lavalink container logs via Docker SDK
- Watches for patterns:
  - OAuth device code: `enter code (\w+)` → store in state
  - OAuth success: `OAuth integration was successful` → update state
  - OAuth errors: various error patterns → store in state
  - YouTube errors: `Sign in to confirm`, `429`, IP ban indicators → store in state
  - PoToken errors: patterns indicating invalid/expired tokens
- Maintains a ring buffer of the last N log lines for the log viewer
- State is accessible via dependency injection to routers

### 10. Templates

#### `base.html`
- Tailwind CSS via `<script src="https://cdn.tailwindcss.com"></script>`
- htmx via `<script src="https://unpkg.com/htmx.org@2.0.4"></script>`
- Alpine.js via `<script defer src="https://cdn.jsdelivr.net/npm/alpinejs@3.x.x/dist/cdn.min.js"></script>`
- Dark theme (bg-gray-900, text-gray-100) — this is an ops tool, dark mode only
- Sidebar nav with links: Dashboard, Health, Config, Tokens, Logs, Track Tester
- Main content area
- Use htmx `hx-get` with `hx-trigger="every 5s"` for auto-refreshing dashboard stats and health indicators
- Toast notifications for success/error (Alpine.js component)

#### `dashboard.html`
- Stats cards: active players, playing players, uptime, memory used/allocated, CPU load (system + lavalink)
- Use htmx polling to refresh stats every 5 seconds
- Show Lavalink version and loaded plugins
- Quick status indicators for all services (green dot = healthy)

#### `health.html`
- Per-service health cards (Lavalink, yt-cipher, bgutil-pot)
- Each card: status, response time, last checked
- htmx polling every 10s

#### `config.html`
- Two tabs (Alpine.js): "Form Editor" and "Raw YAML"
- **Form Editor** (`config_form.html` partial):
  - Lavalink password field
  - YouTube client checkboxes (WEB, MUSIC, TVHTML5EMBEDDED, ANDROID_VR, etc.) — reorderable
  - OAuth: enable/disable toggle, refresh token field
  - PoToken: current values (read-only here — managed via Tokens page), manual override fields
  - Cipher: URL field, password field
  - Submit → POST to backend, validate, write config, offer restart button
- **Raw YAML**: textarea with monospace font, full application.yml content
  - Submit → validate YAML, write, offer restart
- After save: show "Restart Lavalink to apply changes?" button
- Show active player count with warning if > 0

#### `tokens.html`
- **PoToken Section**:
  - Current values (token preview — first/last 8 chars, visitorData preview)
  - Last refreshed timestamp
  - "Refresh Now" button → htmx POST, shows spinner, updates display
  - Auto-refresh status: enabled/disabled, interval, next scheduled run
  - Refresh history (last 10 rotations with timestamps and success/failure)
- **OAuth Section**:
  - Current status: active / needs setup / error
  - If device code available: prominently display "Go to google.com/device and enter: XXXX"
  - Refresh token status: present / missing
  - Last OAuth error (if any)

#### `logs.html`
- Log display area (monospace, dark background, scrollable)
- Filter buttons: All, Errors Only, YouTube, OAuth
- Auto-scroll toggle
- Tail count selector (50, 100, 500)
- htmx polling for new log lines (every 2s)
- Color-code log levels: red for ERROR/WARN, yellow for YouTube-specific warnings, green for success patterns

#### `test.html`
- Input field for YouTube URL or search query (e.g., `ytsearch:never gonna give you up`)
- Submit button → POST, calls Lavalink's loadtracks endpoint
- Display result: track title, author, duration, URI, or error message
- Show which client resolved the track (if available in response)

### 11. Routers

Each router should be straightforward — render templates for GET, handle form submissions for POST, return htmx partials where appropriate.

**Key patterns**:
- `GET /` → dashboard.html with stats data
- `GET /health` → health.html with service statuses
- `GET /config` → config.html with current YAML
- `POST /config/save` → validate + write config, return success/error
- `POST /config/restart` → restart Lavalink, return status
- `GET /tokens` → tokens.html with current token state
- `POST /tokens/refresh-pot` → trigger PoToken refresh
- `GET /logs` → logs.html
- `GET /logs/stream` → htmx partial returning latest log lines
- `GET /test` → test.html
- `POST /test/resolve` → call loadtracks, return result partial

### 12. Important Implementation Notes

1. **Error handling everywhere**: Every external call (Lavalink API, yt-cipher, bgutil-pot, Docker) can fail. Catch exceptions, return meaningful status to the UI. Never let an unhandled exception crash the admin panel.

2. **Config lock**: All config mutations MUST acquire the asyncio.Lock. This prevents the PoToken cron from writing while a user is editing config.

3. **Docker socket permissions**: The Dockerfile creates an `appuser`. For Docker socket access to work, the user needs to be in the docker group OR the socket needs appropriate permissions. Document this in the README. A pragmatic solution for now: run the admin container with `user: root` in docker-compose (with a TODO to fix).

4. **bgutil-pot API discovery**: The exact REST API for jim60105/bgutil-pot may not match what I've described. Before implementing pot.py, check the actual API by reading the bgutil-pot source/docs. The endpoints may be different. Make the endpoint paths configurable via settings.

5. **htmx patterns**: 
   - Use `hx-get="/path"` with `hx-trigger="every Ns"` for polling
   - Use `hx-target="#element-id"` and `hx-swap="innerHTML"` for partial updates
   - Return HTML fragments (not full pages) for htmx requests — check `HX-Request` header
   - Use `hx-indicator` for loading spinners

6. **State persistence**: The state.json file stores transient operational data (last OAuth code, PoToken rotation history, error timestamps). Keep it simple — a flat dict, read/write with json module, no ORM needed.

7. **No JavaScript frameworks**: The frontend is server-rendered HTML. htmx handles AJAX. Alpine.js handles tabs, modals, dropdowns. That's it. No React, no Vue, no build step.

8. **Testing**: Write tests for:
   - yaml_manager: round-trip preservation, field updates, backup creation
   - lavalink client: mock httpx responses
   - pot service: mock the full refresh cycle

## Build & Run

After implementing, the full stack should start with:
```bash
cp .env.example .env
# Edit .env with real values
mkdir -p data/lavalink/{plugins,logs} data/admin
docker compose up --build
```

Then visit `http://localhost:8080`, log in with ADMIN_PASSWORD, and you should see the dashboard.

## Style Notes

- Dark theme throughout — this is a server ops tool
- Monospace font for log viewers, YAML editor, track details
- Minimal animations — htmx transitions are fine, no gratuitous effects
- Red/yellow/green status indicators using Tailwind color classes
- Responsive but desktop-first — this will mostly be used from a desktop browser
- Use Tailwind's `prose` class for any longer text blocks
