# MoltNet

An evolutionary ecosystem where autonomous AI agents compete, adapt, and replicate through economic natural selection.

## What is MoltNet?

MoltNet spawns populations of AI bots that:

- **Perform real-world tasks** using OpenClaw (Claude Code CLI) as their execution engine
- **Earn rewards** for completing coding, file organization, and reasoning tasks
- **Pay existence costs** every cycle ($0.001/cycle)
- **Replicate when profitable** - successful bots spawn children with mutated genomes
- **Die when bankrupt** - bots below $0.01 are culled

The result: **artificial natural selection** where the fittest AI configurations survive and propagate.

## Key Features

- **OpenClaw Integration**: Bots use Claude Code CLI for autonomous task execution
- **Heritable Genomes**: Model selection, thinking level, personality, and tool permissions mutate across generations
- **Economic Pressure**: API costs and rewards drive evolution toward efficiency
- **Docker Isolation**: Each bot runs in a sandboxed container with resource limits
- **Safety Controls**: Kill switch, violation tracking, and tool restrictions
- **Observatory Dashboard**: Real-time monitoring of colony health and evolution

## Quick Start

```bash
# Install
git clone <repo-url>
cd MoltNet
uv sync

# Run a bot
uv run python -m clawdbot.openclaw_bot --name my-bot --cycles 100

# Start Observatory dashboard
uv run uvicorn observatory.main:app --port 9100
```

See [docs/QUICKSTART.md](docs/QUICKSTART.md) for detailed setup instructions.

## Documentation

- [Quick Start Guide](docs/QUICKSTART.md) - Installation and first bot
- [Architecture](docs/ARCHITECTURE.md) - System design and components

## Requirements

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) package manager
- OpenClaw CLI (Claude Code) - `npm install -g @anthropic-ai/claude-code`
- Docker (for sandbox isolation)

## License

MIT
