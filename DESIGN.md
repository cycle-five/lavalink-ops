# Lavalink Stack — Design Document

## Project: `lavalink-ops`

A self-hosted Lavalink audio node with YouTube anti-detection, automated token lifecycle management, and a web-based admin panel.

---

## 1. Architecture Overview

```
┌─────────────────────────────────────────────────────────┐
│                    Docker Network: lavalink              │
│                                                         │
│  ┌──────────────┐   ┌──────────────┐  ┌─────────────┐  │
│  │   Lavalink   │   │  yt-cipher   │  │ bgutil-pot  │  │
│  │  (Java 17+)  │──▶│   (Deno)     │  │   (Rust)    │  │
│  │  :2333       │   │  :8001       │  │  :4416      │  │
│  └──────┬───────┘   └──────────────┘  └──────┬──────┘  │
│         │                                     │         │
│         │  ┌──────────────────────────────┐   │         │
│         └──│        Admin Panel           │───┘         │
│            │  FastAPI + htmx/Jinja2       │             │
│            │  :8080                       │             │
│            └──────────────────────────────┘             │
│                        │                                │
│              Shared Volume: ./config                    │
│              (application.yml, logs, state)             │
└─────────────────────────────────────────────────────────┘
```

### Component Responsibilities

| Component | Role | Image / Build |
|-----------|------|---------------|
| **Lavalink** | Audio sending node, YouTube source plugin, OAuth handler | `ghcr.io/lavalink-devs/lavalink:4` |
| **yt-cipher** | Remote signature deciphering (Deno-based) | `ghcr.io/kikkia/yt-cipher:master` |
| **bgutil-pot** | PoToken generation via BotGuard attestation | `jim60105/bgutil-pot` (Rust) |
| **Admin Panel** | Config management, health monitoring, token lifecycle, log viewer | Custom build (Python 3.12 + FastAPI) |

---

## 2. Component Details

### 2.1 Lavalink

- **Image**: `ghcr.io/lavalink-devs/lavalink:4`
- **Config**: `./config/application.yml` mounted at `/opt/Lavalink/application.yml`
- **Plugins dir**: `./data/lavalink/plugins/` mounted at `/opt/Lavalink/plugins/`
- **Logs**: Lavalink logs to stdout by default; we capture via Docker logging driver and also configure file logging to `./data/lavalink/logs/`
- **Key REST endpoints (v4)**:
  - `GET /v4/info` — node info, plugin versions
  - `GET /v4/stats` — players, memory, CPU, uptime
  - `GET /v4/sessions` — active sessions
  - `GET /version` — Lavalink version string
  - `GET /v4/loadtracks?identifier=...` — test track resolution (useful for health checks)
- **WebSocket**: `/v4/websocket` — dispatches `stats` op every 60s with player counts, memory, CPU, frame stats

### 2.2 yt-cipher

- **Image**: `ghcr.io/kikkia/yt-cipher:master`
- **Purpose**: YouTube frequently rotates cipher algorithms in their player JS. Lavalink's youtube-plugin can offload signature deciphering to this external Deno server, which downloads and evaluates the actual YouTube player script.
- **Auth**: Token-based (`API_TOKEN` env var, referenced in Lavalink config as `remoteCipher.password`)
- **Health check**: `GET /` or test the decrypt endpoint
- **Concern**: Must be kept updated when YouTube changes cipher format. The `master` tag auto-updates but that's risky in prod — consider pinning a specific commit SHA.

### 2.3 bgutil-pot (PoToken Provider)

- **Image**: `jim60105/bgutil-pot`
- **Purpose**: Generates Proof-of-Origin tokens by running BotGuard attestation challenges. These tokens convince YouTube that requests originate from a real browser.
- **Modes**:
  - HTTP Server mode (`:4416`): Always-running REST API, recommended
  - Script mode: Per-request CLI invocation (not used here)
- **Integration with Lavalink**: The admin panel will periodically call bgutil-pot's API to generate fresh tokens, then write them into `application.yml` under `plugins.youtube.pot.token` and `plugins.youtube.pot.visitorData`, then restart Lavalink.
- **Note**: PoTokens are session-bound (to visitorData). A token+visitorData pair has a limited lifetime. The admin panel should refresh on a configurable schedule (default: every 6 hours).
- **Concern**: BgUtils relies on reverse-engineered BotGuard internals. YouTube can (and does) change these. The Rust image needs periodic updates.

### 2.4 Admin Panel

- **Stack**: Python 3.12, FastAPI, Jinja2 + htmx (server-rendered, minimal JS), uvicorn
- **Auth**: Simple token/password auth (configurable via env var). Not exposed to the internet without a reverse proxy.
- **Config volume**: Reads/writes `./config/application.yml`

#### Features (Priority Order)

**P0 — MVP**:
1. **Dashboard**: Live stats from Lavalink REST API (players, memory, CPU, uptime). Polls `/v4/stats` and `/v4/info`.
2. **Config Editor**: YAML editor with schema validation. Edit `application.yml` with a form-based UI for common fields (password, clients list, OAuth toggle, cipher URL, PoToken values) plus a raw YAML editor for advanced use.
3. **Service Health**: Green/yellow/red status indicators for each container. Checks Lavalink `/v4/info`, yt-cipher health endpoint, bgutil-pot health.
4. **Restart Control**: Trigger Lavalink container restart after config changes. Uses Docker socket.

**P1 — Token Lifecycle**:
5. **PoToken Manager**: Button to generate fresh PoToken + visitorData from bgutil-pot, preview the values, inject into config, and restart Lavalink. Optionally run on a cron schedule.
6. **OAuth Flow Helper**: Parse Lavalink logs for the OAuth device code prompt (`go to https://www.google.com/device and enter code XXX`). Display prominently in the UI. Track whether a refresh token has been obtained. Show warning when OAuth errors appear in logs.

**P2 — Observability**:
7. **Log Viewer**: Tail Lavalink container logs with filtering. Highlight YouTube-specific errors (IP bans, cipher failures, OAuth expiry, rate limits).
8. **Track Tester**: Input a YouTube URL/search query, hit Lavalink's `/v4/loadtracks` endpoint, display the result. Quick way to verify the pipeline works.
9. **Prometheus Metrics**: If Lavalink's Prometheus endpoint is enabled, proxy/display key metrics.

**P3 — Advanced**:
10. **Multi-account OAuth rotation**: Manage a pool of burner accounts. When one gets flagged, rotate to the next.
11. **IPv6 rotation config**: UI for configuring IP blocks and rotation strategy.
12. **Plugin version management**: Check for youtube-plugin updates, display current vs latest version.

---

## 3. Key Design Decisions

### 3.1 YAML Manipulation Strategy

**Problem**: `application.yml` contains comments, specific formatting, and nested structures. Naive YAML parsing destroys comments and reorders keys.

**Solution**: Use `ruamel.yaml` (Python) which preserves comments, key order, and formatting. The admin panel loads the YAML via ruamel, modifies specific paths programmatically, and writes back. For the raw editor, we just write the string directly after basic YAML validation.

### 3.2 Container Restart Mechanism

**Problem**: After config changes, Lavalink must be restarted. No hot-reload support exists.

**Options**:
- **(A) Docker socket mount**: Mount `/var/run/docker.sock` into the admin panel container. Use the Docker SDK for Python to restart the Lavalink container by name/ID. **Risk**: Docker socket access is a privilege escalation vector.
- **(B) Docker socket proxy**: Use something like `tecnativa/docker-socket-proxy` to expose only specific Docker API endpoints (container restart). Much safer.
- **(C) Signal-based**: Send `SIGTERM` to Lavalink container, let Docker restart policy (`restart: unless-stopped`) bring it back. Requires `docker kill` access, same socket issue.
- **(D) Sidecar/webhook**: A tiny sidecar container with socket access that exposes a single authenticated endpoint for "restart lavalink". The admin panel calls this endpoint.

**Decision**: Start with **(A)** for simplicity with a strong warning in docs. Move to **(B)** or **(D)** before any production/public deployment. The admin panel should never be exposed to the public internet regardless.

### 3.3 PoToken Refresh Architecture

**Flow**:
1. Admin panel calls `POST http://bgutil-pot:4416/token` (or equivalent endpoint)
2. bgutil-pot runs BotGuard attestation, returns `{ poToken, visitorData }`
3. Admin panel loads `application.yml` via ruamel.yaml
4. Updates `plugins.youtube.pot.token` and `plugins.youtube.pot.visitorData`
5. Writes config back
6. Restarts Lavalink container
7. Logs the rotation event with timestamp

**Cron**: A background task (APScheduler or simple asyncio loop) can run this on a configurable interval. Default 6 hours, configurable via `POT_REFRESH_INTERVAL_HOURS` env var. Should be disableable.

### 3.4 OAuth Device Code Extraction

**Problem**: When Lavalink starts with OAuth enabled but no refresh token, it logs a device code to stdout. The admin panel needs to surface this.

**Approach**:
- Tail Lavalink container logs via Docker SDK (`container.logs(stream=True, follow=True)`)
- Regex for the pattern: `go to https://www.google.com/device and enter code (\w+)`
- Store the latest code in memory + display in UI
- Also watch for `OAuth integration was successful` / error patterns
- After successful OAuth, Lavalink writes the refresh token to its config or logs. The admin panel should capture and persist this.

### 3.5 Frontend Approach

**htmx + Jinja2** over a full SPA because:
- Minimal build tooling (no node, no webpack, no npm)
- Server-rendered HTML with htmx for dynamic updates (polling, partial page swaps)
- Perfect for an admin panel — we don't need offline support, complex client state, or SEO
- Alpine.js for any small client-side interactivity (modals, dropdowns)
- Tailwind CSS via CDN for styling

---

## 4. Anticipated Issues & Mitigations

### 4.1 YouTube Breakage (High Likelihood, Ongoing)

**Issue**: YouTube regularly changes cipher algorithms, client validation, PoToken requirements, and API responses. Any of the three bypass mechanisms (OAuth, PoToken, cipher) can break at any time.

**Mitigation**:
- Defense in depth: use all three mechanisms simultaneously
- Client fallback chain in youtube-plugin config (multiple clients in priority order)
- Admin panel health check specifically tests track loading, not just "is Lavalink up"
- Alerting/log highlighting for YouTube-specific errors
- Easy update path for yt-cipher and bgutil-pot images

### 4.2 OAuth Account Termination

**Issue**: Google can and does terminate burner accounts used for OAuth. The youtube-source docs explicitly warn about this.

**Mitigation**:
- Never use a primary account
- P3 feature: multi-account pool with rotation
- Admin panel should detect OAuth errors in logs and surface them prominently
- Document the burner account creation process

### 4.3 Race Condition on Config Writes

**Issue**: Multiple admin panel features might try to write `application.yml` simultaneously (e.g., user edits config while PoToken cron fires).

**Mitigation**:
- File-level lock (fcntl/flock) around all config read-modify-write operations
- Or: single async queue for config mutations, serialized execution
- Display "config locked" in UI if another operation is in progress

### 4.4 Lavalink Restart Disrupts Active Players

**Issue**: Restarting Lavalink drops all active audio sessions.

**Mitigation**:
- Display active player count before restart, require confirmation if > 0
- Consider scheduling restarts for low-activity periods
- Lavalink v4 supports session resuming — clients can reconnect after restart if they implement it

### 4.5 PoToken/BgUtils Breakage

**Issue**: BgUtils is a reverse-engineering project. When YouTube updates BotGuard, bgutil-pot may generate invalid tokens until the project is updated.

**Mitigation**:
- Track tester in admin panel will surface this quickly
- Fall back to OAuth-only mode
- Admin panel should show PoToken generation success/failure status
- Pin bgutil-pot to a known-good version, don't blindly pull `:latest`

### 4.6 Docker Socket Security

**Issue**: Mounting the Docker socket gives the admin panel container root-equivalent access to the host.

**Mitigation**:
- Admin panel should never be exposed to the public internet
- Run admin panel as non-root user inside the container
- Move to docker-socket-proxy (P1 hardening task)
- Document the risk clearly

### 4.7 Memory/Resource Constraints

**Issue**: Lavalink's JVM, Deno (yt-cipher), and a Rust binary all running simultaneously.

**Mitigation**:
- Set explicit memory limits in docker-compose
- Lavalink: `-Xmx512M` for small deployments (adjust based on player count)
- yt-cipher: lightweight, ~50-100MB
- bgutil-pot: Rust binary, very light (~20-50MB)
- Admin panel: ~50-100MB
- Total: ~700MB-1GB minimum, comfortable at 2GB

---

## 5. File Structure

```
lavalink-ops/
├── docker-compose.yml
├── .env                          # Secrets and tunables
├── .env.example                  # Template
├── config/
│   └── application.yml           # Lavalink config (mounted into container)
├── data/
│   ├── lavalink/
│   │   ├── plugins/              # Lavalink auto-downloads plugins here
│   │   └── logs/                 # Lavalink file logs
│   └── admin/
│       └── state.json            # Admin panel state (OAuth codes, rotation history, etc.)
├── admin/
│   ├── Dockerfile
│   ├── pyproject.toml            # uv/pip project (fastapi, uvicorn, ruamel.yaml, docker, httpx, apscheduler)
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py               # FastAPI app, lifespan, middleware
│   │   ├── config.py             # Settings via pydantic-settings (env vars)
│   │   ├── dependencies.py       # Shared deps (docker client, httpx clients, config lock)
│   │   ├── routers/
│   │   │   ├── __init__.py
│   │   │   ├── dashboard.py      # GET / — main dashboard with stats
│   │   │   ├── config.py         # Config editor (form + raw YAML)
│   │   │   ├── health.py         # Service health checks
│   │   │   ├── tokens.py         # PoToken + OAuth management
│   │   │   ├── logs.py           # Log viewer
│   │   │   └── test.py           # Track tester
│   │   ├── services/
│   │   │   ├── __init__.py
│   │   │   ├── lavalink.py       # Lavalink REST API client
│   │   │   ├── cipher.py         # yt-cipher health check client
│   │   │   ├── pot.py            # bgutil-pot API client + refresh logic
│   │   │   ├── yaml_manager.py   # ruamel.yaml config read/write with locking
│   │   │   ├── docker_ctl.py     # Docker SDK wrapper for container restart
│   │   │   └── log_watcher.py    # Docker log stream parser (OAuth codes, errors)
│   │   ├── templates/
│   │   │   ├── base.html         # Layout with nav, htmx includes, tailwind CDN
│   │   │   ├── dashboard.html
│   │   │   ├── config.html
│   │   │   ├── config_form.html  # htmx partial for form-based config editor
│   │   │   ├── health.html
│   │   │   ├── tokens.html
│   │   │   ├── logs.html
│   │   │   └── test.html
│   │   └── static/
│   │       └── (minimal — maybe a favicon and any non-CDN assets)
│   └── tests/
│       ├── __init__.py
│       ├── test_yaml_manager.py
│       ├── test_lavalink_client.py
│       └── test_pot_service.py
└── README.md
```

---

## 6. Environment Variables

```env
# Lavalink
LAVALINK_PASSWORD=change-me-to-something-secure
LAVALINK_PORT=2333
LAVALINK_JAVA_OPTS=-Xmx512M

# yt-cipher
CIPHER_API_TOKEN=generate-a-random-token-here

# Admin Panel
ADMIN_PASSWORD=change-me-admin-password
ADMIN_PORT=8080
ADMIN_SECRET_KEY=generate-for-session-signing

# PoToken Refresh
POT_REFRESH_ENABLED=true
POT_REFRESH_INTERVAL_HOURS=6

# Docker (for admin panel container restart capability)
# DOCKER_HOST=unix:///var/run/docker.sock  (default)
LAVALINK_CONTAINER_NAME=lavalink
```

---

## 7. Implementation Phases

### Phase 1: Infrastructure (docker-compose + configs)
- Working docker-compose with all 4 services
- Base `application.yml` with youtube-plugin, yt-cipher, OAuth, PoToken placeholders
- `.env` template
- Verify Lavalink boots and can resolve a YouTube track

### Phase 2: Admin Panel MVP
- FastAPI skeleton with Jinja2 + htmx
- Dashboard route with Lavalink stats
- Health check route for all services
- Config editor (raw YAML only first, then form-based)
- Container restart via Docker SDK

### Phase 3: Token Lifecycle
- bgutil-pot integration (generate + inject PoToken)
- Scheduled PoToken refresh
- OAuth log watcher + device code display
- Rotation history/audit log

### Phase 4: Observability
- Log viewer with filtering
- Track tester
- Error pattern detection + alerting indicators

### Phase 5: Hardening
- Docker socket proxy
- Rate limiting on admin panel
- HTTPS via reverse proxy config (Caddy/nginx example)
- Backup/restore for config + state
