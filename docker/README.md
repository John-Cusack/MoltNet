# MoltNet Docker Deployment

Run OpenClaw bot colonies in isolated Docker containers with full observability.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                        Host Machine                              │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐  │
│  │ ./workspaces/   │  │ ./logs/         │  │ ./data/         │  │
│  │   bot-1/        │  │   bot-1/        │  │   observatory/  │  │
│  │   bot-2/        │  │   bot-2/        │  │                 │  │
│  │   bot-3/        │  │   bot-3/        │  │                 │  │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘  │
│           │ mount              │ mount              │ mount     │
└───────────┼────────────────────┼────────────────────┼───────────┘
            ▼                    ▼                    ▼
┌───────────────────────────────────────────────────────────────┐
│                    Docker Network: moltnet-openclaw            │
│                                                                 │
│  ┌─────────┐   ┌─────────┐   ┌─────────┐   ┌──────────────┐   │
│  │  bot-1  │   │  bot-2  │   │  bot-3  │   │  observatory │   │
│  │  1 CPU  │   │  1 CPU  │   │  1 CPU  │   │   0.5 CPU    │   │
│  │  1 GB   │   │  1 GB   │   │  1 GB   │   │   512 MB     │   │
│  └────┬────┘   └────┬────┘   └────┬────┘   └──────┬───────┘   │
│       │             │             │                │           │
│       └─────────────┴─────────────┴────────────────┘           │
│                    HTTP telemetry to :9100                      │
└───────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Prerequisites

- Docker & Docker Compose
- Claude Code CLI authenticated on host (`claude auth login`)

### 2. Start the Colony

```bash
cd docker

# Build and start (3 bots + observatory)
docker compose -f docker-compose.openclaw.yml up -d

# Check status
docker compose -f docker-compose.openclaw.yml ps
```

### 3. View Dashboard

Open http://localhost:9100

### 4. View Logs

```bash
# Stream logs from a bot
docker compose -f docker-compose.openclaw.yml logs -f bot-1

# Or check the mounted log directory
tail -f ../logs/bot-1/*.log

# View all bot logs
docker compose -f docker-compose.openclaw.yml logs -f
```

### 5. Access Workspaces

Each bot's workspace is mounted to the host:

```bash
# See what bot-1 has created
ls -la ../workspaces/bot-1/

# Read its SOUL.md
cat ../workspaces/bot-1/SOUL.md

# Watch files change in real-time
watch -n 1 'ls -la ../workspaces/bot-1/'
```

### 6. Stop Colony

```bash
docker compose -f docker-compose.openclaw.yml down
```

## Spawning Additional Bots

Bots can be spawned dynamically (e.g., during replication):

```bash
# Make spawn script executable
chmod +x spawn_bot.sh

# Spawn a new bot
./spawn_bot.sh child-bot-1 0.30 50
#             ^name      ^balance ^cycles

# List all running bots
docker ps --filter "name=moltnet-"
```

## Resource Limits

Default limits per container:

| Service | CPU | Memory |
|---------|-----|--------|
| bot-N | 1 core | 1 GB |
| observatory | 0.5 core | 512 MB |

Adjust in `docker-compose.openclaw.yml` under `deploy.resources.limits`.

## Accessing Bot Data

### Telemetry (from Observatory API)

```bash
# Current colony status
curl http://localhost:9100/api/colony/current

# Recent events
curl http://localhost:9100/api/events/recent

# Specific bot history
curl http://localhost:9100/api/bots/bot-1
```

### Workspace Files

```bash
# List all workspaces
ls ../workspaces/

# Each workspace contains:
# - SOUL.md (bot personality)
# - Task outputs
# - Generated code
# - Logs
```

### Container Logs

```bash
# All logs
docker compose -f docker-compose.openclaw.yml logs

# Follow specific bot
docker logs -f moltnet-bot-1

# Last 100 lines
docker logs --tail 100 moltnet-bot-1
```

## Environment Variables

Create a `.env` file in the docker directory:

```bash
# API keys (optional if using Claude CLI auth)
ANTHROPIC_API_KEY=sk-ant-...
CEREBRAS_API_KEY=...

# Bot defaults
BOT_BALANCE=0.50
BOT_CYCLES=100
```

## Troubleshooting

### Claude CLI Auth Error

If bots fail with auth errors:

```bash
# Re-authenticate on host
claude auth login

# Verify auth works
claude "test" --print

# Restart containers (picks up new auth)
docker compose -f docker-compose.openclaw.yml restart
```

### Observatory Not Reachable

```bash
# Check observatory is running
docker compose -f docker-compose.openclaw.yml ps observatory

# Check health
curl http://localhost:9100/health

# View observatory logs
docker compose -f docker-compose.openclaw.yml logs observatory
```

### Container Resource Issues

```bash
# Check resource usage
docker stats

# Increase limits in docker-compose.openclaw.yml
# Then recreate:
docker compose -f docker-compose.openclaw.yml up -d --force-recreate
```

## Scaling

To run more bots, add services to `docker-compose.openclaw.yml` or use the spawn script:

```bash
# Spawn 5 more bots
for i in {4..8}; do
    ./spawn_bot.sh "bot-$i" 0.50 100
done
```
