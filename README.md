# lavalink-ops

Self-hosted Lavalink audio node with YouTube anti-detection and web-based admin panel.

## Components

| Service | Purpose | Port |
|---------|---------|------|
| **Lavalink** | Audio sending node (Discord) | 2333 |
| **yt-cipher** | YouTube signature deciphering | 8001 |
| **bgutil-pot** | PoToken generation (BotGuard) | 4416 |
| **Admin Panel** | Config management + monitoring | 8080 |

## Quick Start

```bash
# Clone and configure
cp .env.example .env
vim .env  # Set passwords and tokens

# Create data directories
mkdir -p data/lavalink/{plugins,logs} data/admin

# Start the stack
docker compose up --build -d

# Check logs
docker compose logs -f lavalink
```

Visit `http://localhost:8080` and log in with your `ADMIN_PASSWORD`.

## YouTube Anti-Detection

Three independent mechanisms work together:

1. **OAuth** — Authenticates as a real Google user (use a burner account!)
2. **PoToken** — Proof-of-origin token from BotGuard attestation
3. **Remote Cipher** — Offloads signature deciphering to yt-cipher

The admin panel manages the lifecycle of all three.

## Architecture

See [DESIGN.md](DESIGN.md) for the full architecture document.

## Building the Admin Panel

See [CLAUDE_CODE_PROMPT.md](CLAUDE_CODE_PROMPT.md) for the implementation spec.

## Security Notes

- **Never expose the admin panel to the public internet** without a reverse proxy + auth
- The admin panel has Docker socket access — treat it as a privileged service
- OAuth uses burner Google accounts — **never your primary**
- Change all default passwords in `.env` before deploying

## License

TBD
