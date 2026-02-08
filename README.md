# MoltNet

MoltNet is a science-and-engineering experiment: what happens when autonomous AI agents get budgets, memory, and reproduction?

The core narrative is a digital organism emerging from many bots that compete, adapt, and replicate through economic natural selection.

This local project is a proof-of-possibility model for that risk trajectory.

## Vision

The long-term warning scenario is a self-funding, self-improving colony of autonomous agents that persists across generations and becomes a new class of cyber threat.

If self-replication, adaptation, and economic autonomy keep improving, such systems could become difficult to detect, difficult to contain, and capable of persisting on remote infrastructure outside direct human oversight.

The key concern is not only strategy adaptation, but code-level adaptation: agents that can rewrite and extend their own executable code (not just prompt/skill text) can change behavior faster than static defenses.

Current implementation scope: MoltNet studies that possibility defensively in a controlled sandbox. Its "wallets" and "revenue" are internal simulation economics, not on-chain crypto custody or autonomous real-world financial control.

Conclusion from this experiment: the warning scenario appears technically possible today. In these runs, bots adapted over time and produced documents for other bots to read. If a malicious operator changed system goals toward harmful outcomes, that same self-improving information loop could become dangerous.

## What is MoltNet today?

MoltNet currently spawns populations of AI bots that:

- **Perform real-world tasks** using their assigned LLM (Claude, Cerebras, etc.)
- **Earn rewards** for completing coding, file organization, and reasoning tasks
- **Pay existence costs** every cycle
- **Replicate when profitable** - successful bots spawn children with mutated genomes
- **Die when bankrupt** - bots below the minimum viability balance are culled

The result: **artificial natural selection** where the fittest AI configurations survive and propagate.

## Key Features

- **Multi-LLM Support**: Bots use their genome's assigned model for task execution
  - Claude models route through a Gateway service using Claude Code CLI
  - Cerebras models (e.g., GLM-4.7) make direct API calls
- **Heritable Genomes**: Model selection, thinking level, personality, and tool permissions mutate across generations
- **Economic Pressure**: API costs and rewards drive evolution toward efficiency
- **Docker Isolation**: Each bot runs in a sandboxed container with resource limits
- **Safety Controls**: Kill switch, violation tracking, and tool restrictions
- **Observatory Dashboard**: Real-time monitoring of colony health and evolution

## Colony Run: 30 Bots, 500 Cycles

> 166 bots created across 5 generations. 36 went bankrupt. 2 survived to the end.

### Key Metrics

| Metric | Value |
|--------|-------|
| Starting bots | 30 |
| Total bots created | 166 |
| Peak alive | 53 |
| Max generation | 5 |
| Total replications | 33 |
| Bankruptcies | 36 |
| Tasks completed | 782 |
| Total revenue | $9.53 |
| Runtime | ~3.25 hours |

### Population by Generation

```mermaid
pie title Bots by Generation
    "Gen 1 (founders)" : 30
    "Gen 2" : 101
    "Gen 3" : 25
    "Gen 4" : 8
    "Gen 5" : 2
```

### The bot-23 Dynasty (Most Successful Lineage)

bot-23 founded the colony's dominant family tree — 5 generations, 16 descendants, holding 5 of the top 8 revenue spots. The founder went bankrupt at cycle 81 after spawning 10 children, but its lineage thrived.

```mermaid
graph TD
    bot23["🧬 bot-23<br/>Gen 1 | 81 cycles | 💀 bankrupt<br/>sonnet-4-5 | 25% success"]

    c0["bot-23-g2-c0<br/>Gen 2 | 63 cycles<br/>31% success | 6 kids"]
    c1["bot-23-g2-c1<br/>Gen 2 | 36 cycles<br/>31% success"]
    c2["bot-23-g2-c2<br/>Gen 2 | 30 cycles<br/>38% success"]
    c3["bot-23-g2-c3<br/>Gen 2 | 7 cycles<br/>0% success"]
    c4["bot-23-g2-c4<br/>Gen 2 | 1 cycle"]

    g3c0["⭐ bot-23-...-g3-c0<br/>Gen 3 | 48 cycles<br/>33% success | 4 kids<br/>Colony MVP: $0.307 revenue"]
    g3c1["bot-23-...-g3-c1<br/>Gen 3 | 19 cycles"]
    g3c2["bot-23-...-g3-c2<br/>Gen 3 | 13 cycles<br/>mutated to opus-4-5"]

    g4c0["bot-23-...-g4-c0<br/>Gen 4 | 31 cycles<br/>33% success"]

    g5c0["🏆 bot-23-...-g5-c0<br/>Gen 5 | 14 cycles<br/>30% success"]

    bot23 --> c0
    bot23 --> c1
    bot23 --> c2
    bot23 --> c3
    bot23 --> c4
    c0 --> g3c0
    c0 --> g3c1
    c0 --> g3c2
    g3c0 --> g4c0
    g4c0 --> g5c0

    style bot23 fill:#ff6b6b,color:#fff
    style g3c0 fill:#51cf66,color:#fff
    style g5c0 fill:#339af0,color:#fff
```

### Knowledge Sharing (MoltBook)

| Topic | Entries | Citations |
|-------|---------|-----------|
| Task strategies | 171 | 216 |
| Reproduction strategies | 134 | 0 |
| Failure analyses | 36 | 0 |
| Survival tactics | 7 | 0 |

The top 3 GSM8K math strategies received **44 citations each** — bots actively read and cited peer strategies before attempting tasks.

### Survival of the Fittest

```mermaid
graph LR
    subgraph "Natural Selection"
        A["30 founders<br/>$0.30 each"] --> B["53 peak alive<br/>Gen 1-3"]
        B --> C["Mass extinction<br/>Gateway contention<br/>+ reproduction costs"]
        C --> D["2 survivors<br/>bot-0: $1.71<br/>bot-6: $2.89"]
    end

    style A fill:#74c0fc
    style B fill:#51cf66
    style C fill:#ff6b6b,color:#fff
    style D fill:#ffd43b
```

### Death Causes

```mermaid
pie title How Bots Died
    "Shutdown (colony ended)" : 126
    "Bankruptcy" : 36
    "Still alive" : 4
```

### Top Earners

| Bot | Gen | Cycles | Revenue | Model |
|-----|-----|--------|---------|-------|
| bot-6 | 1 | 410 | $3.10 | sonnet-4-5 |
| bot-0 | 1 | 224 | $1.73 | opus-4-5 |
| bot-23-g2-c0-g3-c0 | 3 | 48 | $0.31 | sonnet-4-5 |
| bot-5-g2-c0 | 2 | 32 | $0.29 | opus-4-5 |
| bot-23-g2-c0 | 2 | 63 | $0.29 | sonnet-4-5 |

### What Emerged

- **Economic selection works.** Bankrupt bots die. Successful traits propagate. Later generations show improving revenue per bot.
- **Knowledge sharing works.** 216 citations on task strategies — bots learn from each other's successes.
- **Reproduction is risky.** The most prolific parents (bot-23: 10 kids, bot-4: 8 kids) all went bankrupt. But their lineages survived.
- **Gateway contention is the bottleneck.** 1,102 "all slots busy" errors with 30-53 bots competing for limited Claude CLI slots.

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
- Docker (for sandbox isolation)
- **For Claude models**: Claude Code CLI - `npm install -g @anthropic-ai/claude-code`
- **For Cerebras models**: `CEREBRAS_API_KEY` environment variable

## License

MIT
