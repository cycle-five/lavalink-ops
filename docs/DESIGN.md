# Lavalink Stack — Design

A self-hosted Lavalink audio node with YouTube anti-detection, automated
PoToken refresh, and a web admin panel. This document describes how the stack
is wired together today; it is not a roadmap.

---

## 1. Architecture

The stack mixes host networking and a private bridge network depending on what
each service needs to talk to.

```
              ┌───────────────────────── host network ──────────────────────────┐
              │                                                                  │
              │   ┌──────────────────┐          ┌──────────────────┐             │
              │   │     Lavalink     │          │    Admin Panel   │             │
              │   │   (Java 17+)     │          │  FastAPI + htmx  │             │
              │   │  127.0.0.1:2333  │          │  127.0.0.1:8080  │             │
              │   └────────┬─────────┘          └────────┬─────────┘             │
              │            │                             │                       │
              │            │ /v4/info, /v4/loadtracks    │                       │
              │            │            ┌────────────────┘                       │
              │            ▼            ▼                                        │
              │   ┌──────────────────────────────────────────────┐               │
              │   │   bridge network (loopback-published only)    │               │
              │   │                                                │               │
              │   │  yt-cipher    bgutil-pot    docker-socket-     │               │
              │   │  :8001        :4416         proxy :2375        │               │
              │   └──────────────────────────────────────────────┘               │
              │                              │                                    │
              │                              │ scoped: containers/                │
              │                              ▼ post/ping/version                  │
              │                    /var/run/docker.sock (ro)                      │
              └──────────────────────────────────────────────────────────────────┘
```

- **Lavalink** and the **admin panel** run with `network_mode: host` so the
  admin panel can reach Lavalink at `127.0.0.1:2333` and Lavalink can reach
  yt-cipher at `127.0.0.1:8001` without crossing a Docker network.
- **yt-cipher**, **bgutil-pot**, and **docker-socket-proxy** run on the default
  bridge network. Their ports are published to `127.0.0.1` only — never bound
  to all interfaces — so a misconfigured firewall cannot accidentally expose
  them.
- An **init** container runs once on `docker compose up`, creates the data
  directories, and chowns them to the matching service UIDs (322 for Lavalink,
  1001 for admin).

### Component Responsibilities

| Component | Role | Image |
|-----------|------|-------|
| **Lavalink** | Audio sending node, YouTube source plugin, OAuth handler | `ghcr.io/lavalink-devs/lavalink:4` |
| **yt-cipher** | Remote signature deciphering for YouTube | `ghcr.io/kikkia/yt-cipher:master` |
| **bgutil-pot** | PoToken generation via BotGuard attestation (Node, distroless) | `jim60105/bgutil-pot:v0.8.1` |
| **docker-socket-proxy** | Scoped gateway in front of `/var/run/docker.sock` | `tecnativa/docker-socket-proxy:0.3.0` |
| **Admin Panel** | Config management, health, token lifecycle, log viewer | Custom build (Python 3.12 + FastAPI) |
| **init** | One-shot `mkdir`/`chown` for bind-mounted data dirs | `busybox:1.36.1` |

---

## 2. Component Details

### 2.1 Lavalink

- Config: `./config/application.yml` mounted read-only at `/opt/Lavalink/application.yml`.
- Plugins: `./data/lavalink/plugins/` — Lavalink auto-downloads here on boot.
- File logs: `./data/lavalink/logs/` (also streamed to stdout for `docker logs`).
- Healthcheck inside the container hits `/version` with the configured password.

### 2.2 yt-cipher

- Distroless upstream image — no shell, no `wget`/`curl`. Liveness is exposed
  to monitors via the admin panel's `GET /healthz/cipher`, not via a
  container-level healthcheck.
- Auth: `API_TOKEN` env var, referenced in `application.yml` as
  `remoteCipher.password`.
- The `:master` tag auto-updates. Pin a specific commit if drift breaks
  production.

### 2.3 bgutil-pot

- Distroless Node image (also no shell). Same liveness story as yt-cipher —
  see `GET /healthz/pot`.
- Pinned to `:v0.8.1`. The image sets `WORKDIR=/` and runs as UID 1001, so the
  compose entry sets `working_dir: /tmp` and `HOME=/tmp` to give the BotGuard
  attestation code a writable scratch space (`./snapshot` mkdir would
  otherwise fail and the v0.8.1 error path aborts).
- Bound to `127.0.0.1:4416` only. No upstream auth — keep it off public
  interfaces.

### 2.4 docker-socket-proxy

- Replaces the historical "mount the docker socket directly" pattern. The
  admin panel never sees the real socket.
- Admin reaches it via `DOCKER_HOST=tcp://127.0.0.1:2375`.
- We override the image's default env-var-driven config with a custom
  `haproxy.cfg` (in `config/dockerproxy/`) that allowlists exactly the
  endpoint + method combinations the admin panel uses:

  | Method | Path | Used by |
  |--------|------|---------|
  | `GET` | `/_ping` | proxy healthcheck, admin liveness |
  | `GET` | `/version` (and `/vX.Y/version`) | docker-py `from_env()` API negotiation |
  | `GET` | `/containers/{name}/json` | `containers.get` (inspect by name) |
  | `GET` | `/containers/{id}/logs` | log viewer + log watcher |
  | `POST` | `/containers/{id}/restart` | config-change + PoToken refresh |

  Everything else returns 403 — `containers.create`, `containers.start`,
  `containers.kill`, `containers.exec`, `containers.prune`, the entire
  images/volumes/networks/swarm/system surface, and so on.

**Why endpoint-level instead of the env-var interface.** The image's default
env vars (`CONTAINERS=1`, `POST=1`, etc.) are granular at the *resource*
level. `CONTAINERS=1` + `POST=1` would also pass `POST /containers/create`,
which is enough for an attacker with admin RCE to create a privileged
container with a bind-mount of `/` and escape to host root. The custom
HAProxy config is path-regex granular, so we can permit the one POST verb we
actually need (`/restart`) without opening the rest of the `/containers/*`
POST surface. The cost is that we own a small `haproxy.cfg` (versioned
alongside the codebase); the benefit is that an admin-panel compromise stays
genuinely contained.

### 2.5 Admin Panel

- Stack: Python 3.12, FastAPI, Jinja2 + htmx (server-rendered, minimal JS),
  uvicorn, Alpine.js + Tailwind via CDN.
- Auth: HMAC-signed session cookie (`{issued_at}.{nonce}.{sig}`, 7-day TTL,
  rejects future-dated tokens). Per-IP login rate limit (5 failed attempts in
  60s). `hmac.compare_digest` for the password compare.
- Runs as **UID 1001** with `cap_drop: ALL`, `read_only: true`, and `tmpfs:
  /tmp`. Bind mounts (`./config`, `./data/admin`) stay writable.
- Bind defaults to `127.0.0.1:8080` so the supported workflow is an SSH
  tunnel: `ssh -L 8080:localhost:8080 user@host`. Optional reverse-proxy
  support via `ADMIN_TRUST_PROXY` + `ADMIN_TRUSTED_PROXY_IPS` so login rate
  limiting keys on the real client IP via `X-Forwarded-For`.
- State (`./data/admin/state.json`): rotation history, OAuth markers. Written
  atomically (tempfile + `os.replace`) so a stale-ownership file can't lock
  out writes and partial flushes can't corrupt the JSON.

#### Features

- **Dashboard** — live `/v4/stats` + `/v4/info` polling.
- **Config Editor** — form view for common YouTube/cipher/PoToken fields plus
  a raw YAML editor; both go through the same `ruamel.yaml` round-trip path.
- **Service Health** — green/yellow/red cards in the UI. Same probes are also
  exposed as unauthenticated JSON at `/healthz` (aggregate, 200/503) and
  `/healthz/{lavalink,cipher,pot}` for external monitors. Lavalink is the
  only critical service that flips the aggregate to 503; cipher and pot are
  advisory.
- **Restart Control** — restart Lavalink via the docker-socket-proxy after
  config changes.
- **PoToken Manager** — manual rotate or scheduled via APScheduler
  (`POT_REFRESH_INTERVAL_HOURS`, default 6h).
- **OAuth Helper** — log watcher tails Lavalink and surfaces device codes /
  success / errors.
- **Log Viewer** — htmx-polled log tail with filter chips (errors, YouTube,
  OAuth) and color highlighting.
- **Track Tester** — `/v4/loadtracks` against a user-supplied identifier; raw
  JSON result for debugging.

---

## 3. Key Design Decisions

### 3.1 YAML manipulation

`application.yml` has comments and a specific shape we want to preserve.
`ruamel.yaml` (round-trip mode) loads, the admin panel mutates specific paths
programmatically, and writes back. Raw-editor saves still go through a
validation parse before being written. All writes hold the asyncio config lock
to serialize the PoToken cron and user edits.

### 3.2 Container restart goes through a scoped proxy

The admin panel never sees `/var/run/docker.sock`. It talks to
`tecnativa/docker-socket-proxy`, which exposes only the API verbs we use
(containers list/inspect/restart/logs, plus ping/version for SDK
handshake). This keeps an admin-panel RCE from being equivalent to host root.

### 3.3 PoToken refresh

1. Admin POSTs to bgutil-pot, gets `{poToken, visitorData}`.
2. Acquires the config lock.
3. Updates `plugins.youtube.pot.token` / `visitorData` via `ruamel.yaml`.
4. Writes config back atomically.
5. Restarts Lavalink via the docker-socket-proxy.
6. Appends a rotation event to `state.json`.

A background APScheduler job runs the same flow on
`POT_REFRESH_INTERVAL_HOURS` (default 6h, disable with
`POT_REFRESH_ENABLED=false`).

### 3.4 OAuth device code extraction

`log_watcher.py` streams Lavalink container logs through the
docker-socket-proxy and regex-matches the `enter code (\w+)` pattern, the
"OAuth integration was successful" line, and known error patterns. Latest
state lands in `state.json` and surfaces on the Tokens page. The watcher
sleeps on clean EOF so a dead Lavalink doesn't hot-spin.

### 3.5 Frontend approach

htmx + Jinja2 over a SPA: no Node toolchain, no bundle step, server-rendered
HTML with htmx for partial updates and Alpine.js for tabs/modals/dropdowns.
Tailwind via CDN for styling. Dark theme only — this is an ops tool.

### 3.6 Network defaults: host + loopback bridge

- Lavalink and admin are `network_mode: host` because Lavalink needs the host
  IP for IPv6 rotation strategies and the admin panel benefits from talking
  to Lavalink over loopback without an extra hop.
- yt-cipher / bgutil-pot / dockerproxy are bridge with `127.0.0.1:PORT:PORT`
  publishes — the bridge gives them isolation, the loopback bind keeps them
  off public interfaces even if the host firewall drifts.

---

## 4. Operational Considerations

### 4.1 YouTube breakage

YouTube rotates cipher algorithms, client validation, and PoToken
requirements on its own schedule. Defense in depth: OAuth + PoToken + remote
cipher run together. The youtube-plugin client list in `application.yml`
provides a fallback chain. The admin panel's track tester is the fastest
way to confirm the pipeline is end-to-end working after YouTube changes.

### 4.2 OAuth account termination

Google can and does terminate burner accounts used for OAuth. Never use a
primary account. The Tokens page surfaces OAuth errors from the log watcher
so termination is visible without grepping logs by hand.

### 4.3 Race conditions on config writes

All `application.yml` mutations acquire `_config_lock` (asyncio.Lock) in
`dependencies.py`. Atomic write of `state.json` covers the same hazard for
admin state.

### 4.4 Lavalink restart drops players

Restarting kills active audio sessions. The dashboard shows the active
player count; Lavalink v4 supports session resuming for clients that
implement it.

### 4.5 PoToken / BgUtils breakage

BgUtils reverse-engineers BotGuard. When Google ships a BotGuard update,
bgutil-pot can return invalid tokens until upstream catches up. The track
tester surfaces this; falling back to OAuth-only is the temporary mitigation.
Pin the bgutil-pot tag rather than running `:latest`.

### 4.6 Docker socket exposure

Hardened: scoped via `tecnativa/docker-socket-proxy`, admin runs UID 1001
with `cap_drop: ALL` and `read_only: true`, real socket is read-only mounted
into the proxy and never the admin container.

### 4.7 Resource footprint

Approximate steady-state memory:
- Lavalink JVM: 512MB (`-Xmx512M`, tunable via `LAVALINK_JAVA_OPTS`)
- yt-cipher: ~50–100MB
- bgutil-pot: ~80–150MB
- Admin panel: ~80–120MB
- docker-socket-proxy: tiny

Comfortable on a 2GB instance; tight on 1GB.

---

## 5. Repository Layout

```
lavalink-ops/
├── docker-compose.yml
├── setup.sh                       # One-click: secrets, .env, config sync
├── .env / .env.example
├── README.md
├── docs/
│   └── DESIGN.md                  # this file
├── config/
│   └── application.yml            # Lavalink config (mounted into container)
├── data/                          # bind mounts (created by init container)
│   ├── lavalink/
│   │   ├── plugins/
│   │   └── logs/
│   └── admin/
│       └── state.json             # rotation history, OAuth markers
├── terraform/                     # Optional cloud bootstrap
│   ├── aws/
│   ├── upcloud/
│   └── vultr/
└── admin/
    ├── Dockerfile                 # python:3.12-slim, runs as UID 1001
    ├── pyproject.toml
    ├── app/
    │   ├── main.py                # FastAPI app, lifespan, auth middleware
    │   ├── config.py              # Settings (pydantic-settings)
    │   ├── dependencies.py        # http client, docker client, state, lock
    │   ├── routers/
    │   │   ├── dashboard.py
    │   │   ├── config.py
    │   │   ├── health.py          # HTML + JSON /healthz endpoints
    │   │   ├── tokens.py
    │   │   ├── logs.py
    │   │   └── test.py
    │   ├── services/
    │   │   ├── lavalink.py
    │   │   ├── cipher.py
    │   │   ├── pot.py
    │   │   ├── yaml_manager.py
    │   │   ├── docker_ctl.py
    │   │   └── log_watcher.py
    │   ├── templates/             # base + per-page + partials/
    │   └── static/
    └── tests/
        ├── test_auth.py
        ├── test_lavalink.py
        ├── test_pot.py
        └── test_yaml_manager.py
```

---

## 6. Environment Variables

See `.env.example` for the full annotated list. The non-obvious ones:

| Var | Default | Purpose |
|-----|---------|---------|
| `ADMIN_BIND_HOST` | `127.0.0.1` | Bind address for uvicorn. Keep loopback for SSH tunnel; `0.0.0.0` only behind a real firewall. |
| `ADMIN_COOKIE_SECURE` | `false` | Set `true` when admin is served over HTTPS. Leaving it true on plain HTTP locks you out (Secure cookies aren't sent). |
| `ADMIN_TRUST_PROXY` | `false` | Honor `X-Forwarded-For` so login rate limiting keys on the real client IP. |
| `ADMIN_TRUSTED_PROXY_IPS` | `127.0.0.1` | Comma-separated list of every proxy hop. Required when `ADMIN_TRUST_PROXY=true`. |
| `POT_REFRESH_INTERVAL_HOURS` | `6` | APScheduler interval for automatic PoToken refresh. Disable entirely with `POT_REFRESH_ENABLED=false`. |
| `LAVALINK_CONTAINER_NAME` | `lavalink` | Name the admin panel uses to look up the container for restart / logs. Keep in sync if you rename the service. |

Spotify `clientId` / `clientSecret` are intentionally **not** env vars — they
live in `application.yml` (Config → LavaSrc → Spotify in the admin panel) so
LavaSrc has a single source of truth.
