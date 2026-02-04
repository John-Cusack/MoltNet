# MoltNet Quick Start Guide

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- Docker & Docker Compose (for containerized deployment)
- Claude Code CLI (for Max plan integration)

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd MoltNet

# Install dependencies with uv
uv sync

# Install dev dependencies (for testing)
uv sync --all-extras
```

## Running Locally

### 1. Start the Observatory

```bash
uv run uvicorn observatory.main:app --host 0.0.0.0 --port 9100
```

Open http://localhost:9100 to view the dashboard.

### 2. Run a Bot

```bash
# Basic bot (uses Ollama if available)
uv run python -m clawdbot.bot --name my-bot --cycles 100

# With Observatory integration
export OBSERVATORY_URL=http://localhost:9100
uv run python -m clawdbot.bot --name my-bot --cycles 100
```

### 3. With Ollama (Local LLM)

```bash
# Start Ollama and pull a model
ollama serve &
ollama pull phi4-mini

# Run bot (will auto-detect Ollama)
uv run python -m clawdbot.bot --name local-bot
```

## Running with Docker

### Full Stack

```bash
cd docker

# Create .env file with API keys
cat > .env << EOF
ANTHROPIC_API_KEY=your-key
OPENAI_API_KEY=your-key
CEREBRAS_API_KEY=your-key
EOF

# Start everything
docker compose up -d

# View logs
docker compose logs -f bot-alpha
```

### With Local Ollama

```bash
docker compose --profile local-llm up -d
```

## Using Claude Code CLI (Max Plan)

If you have a Claude Max subscription:

```bash
# Install and authenticate Claude Code CLI
npm install -g @anthropic-ai/claude-code
claude auth login

# Verify it works
claude "test" --print

# The bot will automatically detect and use it
# Models: claude_code/sonnet-4-5, claude_code/opus-4
```

## Configuration

### Bot Genome

```python
from clawdbot.bot import Bot, BotGenome

genome = BotGenome(
    name="my-bot",
    generation=1,
    brain_config={
        "budget_per_cycle": 0.05,      # Max $0.05 per cycle
        "prefer_local": True,           # Prefer free models
        "fallback_to_free": True,       # Fall back when over budget
        "routing_strategy": "best_value",
    },
    cycle_interval_seconds=30.0,        # 30s between cycles
    replication_fitness_threshold=0.8,  # 80% fitness to replicate
    max_cycles_per_run=1000,            # Max 1000 cycles
)

bot = Bot(genome=genome)
await bot.run()
```

### Environment Variables

```bash
export OBSERVATORY_URL=http://localhost:9100
export LLM_REGISTRY_PATH=config/llm-registry.yaml
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
export CEREBRAS_API_KEY=...
```

## Testing

```bash
# Run all tests
uv run pytest tests/ -v

# Run specific test file
uv run pytest tests/test_registry.py -v

# With coverage
uv run pytest tests/ --cov=clawdbot --cov=observatory
```

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/` | GET | Dashboard UI |
| `/health` | GET | Health check |
| `/telemetry` | POST | Ingest bot telemetry |
| `/events` | POST | Ingest events |
| `/api/colony/current` | GET | Current bot statuses |
| `/api/colony/stats` | GET | Aggregate statistics |
| `/api/brains/leaderboard` | GET | Brain model rankings |
| `/api/timeseries/{metric}` | GET | Time series data |
| `/api/events/recent` | GET | Recent events |
| `/api/bots/{name}` | GET | Bot detail & history |

## Architecture

See [ARCHITECTURE.md](./ARCHITECTURE.md) for detailed documentation on:

- Bot lifecycle and state machine
- Replication conditions and fitness calculation
- Hardware resource limits
- Claude Code CLI / Max plan integration
- Cerebras high-speed inference
- Model selection strategies
