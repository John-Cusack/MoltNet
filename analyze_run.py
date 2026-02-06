#!/usr/bin/env python3
"""Analyze a MoltNet run by combining all data and querying Claude about it.

This tool:
1. Combines logs, databases, and metadata from a run
2. Exports to a single JSON file for analysis
3. Provides interactive Claude queries about the data

Usage:
    # Analyze the current run
    uv run python analyze_run.py

    # Analyze a specific archived run
    uv run python analyze_run.py --run runs/2026-02-04_10-30-00

    # Export data only (no Claude queries)
    uv run python analyze_run.py --export-only

    # Ask a specific question
    uv run python analyze_run.py --question "Which bot survived the longest and why?"

    # Use a specific model
    uv run python analyze_run.py --model sonnet
"""

import argparse
import gzip
import json
import sqlite3
import subprocess
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from pathlib import Path
from typing import Any


DEFAULT_DATA_DIR = Path("./data")
DEFAULT_LOGS_DIR = Path("./logs")
DEFAULT_RUNS_DIR = Path("./runs")


@dataclass
class RunData:
    """Combined data from a single run."""

    run_path: str
    collected_at: str

    # Summary stats
    total_bots: int = 0
    total_cycles: int = 0
    total_events: int = 0
    total_moltbook_entries: int = 0

    # Detailed data
    bots: list[dict] = None
    events: list[dict] = None
    telemetry_samples: list[dict] = None
    moltbook_entries: list[dict] = None
    death_causes: dict[str, int] = None
    model_performance: dict[str, dict] = None

    # Raw logs (last N lines per bot)
    bot_logs: dict[str, list[dict]] = None

    def __post_init__(self):
        if self.bots is None:
            self.bots = []
        if self.events is None:
            self.events = []
        if self.telemetry_samples is None:
            self.telemetry_samples = []
        if self.moltbook_entries is None:
            self.moltbook_entries = []
        if self.death_causes is None:
            self.death_causes = {}
        if self.model_performance is None:
            self.model_performance = {}
        if self.bot_logs is None:
            self.bot_logs = {}

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, default=str)

    def summary(self) -> str:
        """Generate a text summary of the run."""
        lines = [
            "=" * 60,
            "RUN SUMMARY",
            "=" * 60,
            f"Path: {self.run_path}",
            f"Collected: {self.collected_at}",
            "",
            "STATISTICS",
            "-" * 40,
            f"Total bots: {self.total_bots}",
            f"Total cycles: {self.total_cycles}",
            f"Total events: {self.total_events}",
            f"Moltbook entries: {self.total_moltbook_entries}",
            "",
        ]

        if self.death_causes:
            lines.append("DEATH CAUSES")
            lines.append("-" * 40)
            for cause, count in sorted(self.death_causes.items(), key=lambda x: -x[1]):
                lines.append(f"  {cause}: {count}")
            lines.append("")

        if self.model_performance:
            lines.append("MODEL PERFORMANCE")
            lines.append("-" * 40)
            for model, stats in sorted(
                self.model_performance.items(),
                key=lambda x: -x[1].get("avg_fitness", 0)
            ):
                lines.append(f"  {model}:")
                lines.append(f"    Bots: {stats.get('bot_count', 0)}")
                lines.append(f"    Avg fitness: {stats.get('avg_fitness', 0):.3f}")
                lines.append(f"    Avg cycles: {stats.get('avg_cycles', 0):.1f}")
            lines.append("")

        if self.bots:
            lines.append("TOP BOTS (by cycles)")
            lines.append("-" * 40)
            sorted_bots = sorted(self.bots, key=lambda b: -b.get("cycle_count", 0))[:5]
            for bot in sorted_bots:
                lines.append(f"  {bot.get('name', 'unknown')}:")
                lines.append(f"    Cycles: {bot.get('cycle_count', 0)}")
                lines.append(f"    Fitness: {bot.get('fitness_score', 0):.3f}")
                lines.append(f"    Children: {bot.get('children_spawned', 0)}")
                lines.append(f"    Death: {bot.get('death_cause', 'unknown')}")
            lines.append("")

        if self.moltbook_entries:
            lines.append("MOLTBOOK HIGHLIGHTS")
            lines.append("-" * 40)
            # Sort by citations
            sorted_entries = sorted(
                self.moltbook_entries,
                key=lambda e: -e.get("citations", 0)
            )[:5]
            for entry in sorted_entries:
                lines.append(f"  [{entry.get('topic', '')}] {entry.get('title', '')}")
                lines.append(f"    By: {entry.get('author_bot', '')} | Citations: {entry.get('citations', 0)}")
            lines.append("")

        lines.append("=" * 60)
        return "\n".join(lines)


def collect_from_sqlite(db_path: Path, table: str, limit: int = 1000) -> list[dict]:
    """Collect data from a SQLite table."""
    if not db_path.exists():
        return []

    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()

        cursor.execute(f"SELECT * FROM {table} ORDER BY timestamp DESC LIMIT ?", (limit,))
        rows = cursor.fetchall()

        conn.close()
        return [dict(row) for row in rows]
    except Exception as e:
        print(f"Warning: Could not read {db_path}: {e}", file=sys.stderr)
        return []


def collect_from_logs(logs_dir: Path, max_lines_per_bot: int = 500) -> dict[str, list[dict]]:
    """Collect data from JSONL log files."""
    bot_logs = {}

    if not logs_dir.exists():
        return bot_logs

    for bot_dir in logs_dir.iterdir():
        if not bot_dir.is_dir():
            continue

        bot_name = bot_dir.name
        bot_logs[bot_name] = []

        # Read all JSONL files for this bot
        for log_file in sorted(bot_dir.glob("*.jsonl")):
            try:
                lines = log_file.read_text().strip().split("\n")
                for line in lines[-max_lines_per_bot:]:
                    if line:
                        bot_logs[bot_name].append(json.loads(line))
            except Exception as e:
                print(f"Warning: Could not read {log_file}: {e}", file=sys.stderr)

        # Also check for gzipped files
        for log_file in sorted(bot_dir.glob("*.jsonl.gz")):
            try:
                with gzip.open(log_file, "rt") as f:
                    lines = f.read().strip().split("\n")
                    for line in lines[-max_lines_per_bot:]:
                        if line:
                            bot_logs[bot_name].append(json.loads(line))
            except Exception as e:
                print(f"Warning: Could not read {log_file}: {e}", file=sys.stderr)

        # Keep only last N entries
        bot_logs[bot_name] = bot_logs[bot_name][-max_lines_per_bot:]

    return bot_logs


def analyze_bots(telemetry: list[dict], events: list[dict]) -> list[dict]:
    """Analyze bot data from telemetry and events."""
    bots = {}

    # Get latest telemetry per bot
    for t in telemetry:
        bot_name = t.get("bot_name")
        if not bot_name:
            continue

        if bot_name not in bots or t.get("timestamp", 0) > bots[bot_name].get("timestamp", 0):
            bots[bot_name] = {
                "name": bot_name,
                "generation": t.get("generation"),
                "fitness_score": t.get("fitness_score"),
                "wallet_balance": t.get("wallet_balance"),
                "cycle_count": t.get("cycle_count"),
                "tasks_completed": t.get("tasks_completed"),
                "tasks_failed": t.get("tasks_failed"),
                "brain_primary": t.get("brain_primary"),
                "timestamp": t.get("timestamp"),
            }

    # Add death info from events
    for e in events:
        if e.get("event_type") in ("openclaw_bot_stopped", "openclaw_bot_died", "bot_stopped", "bot_died"):
            bot_name = e.get("bot_name")
            if bot_name and bot_name in bots:
                data = e.get("data", {})
                if isinstance(data, str):
                    try:
                        data = json.loads(data)
                    except:
                        data = {}
                bots[bot_name]["death_cause"] = data.get("death_cause", data.get("cause", "unknown"))
                bots[bot_name]["children_spawned"] = data.get("children_spawned", 0)

    return list(bots.values())


def analyze_death_causes(events: list[dict]) -> dict[str, int]:
    """Count death causes from events."""
    causes = {}

    for e in events:
        if e.get("event_type") in ("openclaw_bot_stopped", "openclaw_bot_died", "bot_stopped", "bot_died"):
            data = e.get("data", {})
            if isinstance(data, str):
                try:
                    data = json.loads(data)
                except:
                    data = {}
            cause = data.get("death_cause", data.get("cause", "unknown"))
            causes[cause] = causes.get(cause, 0) + 1

    return causes


def analyze_model_performance(bots: list[dict]) -> dict[str, dict]:
    """Analyze performance by model."""
    models = {}

    for bot in bots:
        model = bot.get("brain_primary", "unknown")
        if model not in models:
            models[model] = {
                "bot_count": 0,
                "total_fitness": 0,
                "total_cycles": 0,
                "total_children": 0,
            }

        models[model]["bot_count"] += 1
        models[model]["total_fitness"] += bot.get("fitness_score", 0) or 0
        models[model]["total_cycles"] += bot.get("cycle_count", 0) or 0
        models[model]["total_children"] += bot.get("children_spawned", 0) or 0

    # Calculate averages
    for model, stats in models.items():
        count = stats["bot_count"]
        if count > 0:
            stats["avg_fitness"] = stats["total_fitness"] / count
            stats["avg_cycles"] = stats["total_cycles"] / count
            stats["avg_children"] = stats["total_children"] / count

    return models


def collect_run_data(run_path: Path | None = None) -> RunData:
    """Collect all data from a run."""

    # Determine paths
    if run_path and run_path.exists():
        # Archived run
        data_dir = run_path / "data"
        logs_dir = run_path / "logs"
        observatory_db = data_dir / "observatory" / "observatory.db"
        moltbook_db = data_dir / "moltbook" / "moltbook.db"
    else:
        # Current run
        run_path = Path(".")
        data_dir = DEFAULT_DATA_DIR
        logs_dir = DEFAULT_LOGS_DIR
        observatory_db = data_dir / "observatory" / "observatory.db"
        moltbook_db = data_dir / "moltbook" / "moltbook.db"

    print(f"Collecting data from: {run_path}")
    print(f"  Observatory DB: {observatory_db}")
    print(f"  Moltbook DB: {moltbook_db}")
    print(f"  Logs: {logs_dir}")

    # Collect data
    telemetry = collect_from_sqlite(observatory_db, "telemetry", limit=5000)
    events = collect_from_sqlite(observatory_db, "events", limit=2000)
    moltbook_entries = collect_from_sqlite(moltbook_db, "entries", limit=500)
    bot_logs = collect_from_logs(logs_dir, max_lines_per_bot=200)

    # Analyze
    bots = analyze_bots(telemetry, events)
    death_causes = analyze_death_causes(events)
    model_performance = analyze_model_performance(bots)

    # Build run data
    run_data = RunData(
        run_path=str(run_path.absolute()),
        collected_at=datetime.now().isoformat(),
        total_bots=len(bots),
        total_cycles=sum(b.get("cycle_count", 0) or 0 for b in bots),
        total_events=len(events),
        total_moltbook_entries=len(moltbook_entries),
        bots=bots,
        events=events[:500],  # Limit for context size
        telemetry_samples=telemetry[:200],  # Sample for context
        moltbook_entries=moltbook_entries,
        death_causes=death_causes,
        model_performance=model_performance,
        bot_logs=bot_logs,
    )

    return run_data


def export_run_data(run_data: RunData, output_path: Path) -> None:
    """Export run data to JSON file."""
    output_path.write_text(run_data.to_json())
    print(f"Exported to: {output_path}")


def query_claude(question: str, run_data: RunData, model: str = "sonnet") -> str:
    """Query Claude about the run data."""

    # Build context
    context = f"""You are analyzing data from a MoltNet colony run. MoltNet is a system where AI bots:
- Compete economically by completing tasks
- Pay existence costs and API costs
- Die from bankruptcy (no money) or starvation (too many failures)
- Reproduce when profitable, passing mutated traits to offspring
- Share learnings in Moltbook (a collective knowledge base)

Here is the data from this run:

## Run Summary
{run_data.summary()}

## Detailed Bot Data
```json
{json.dumps(run_data.bots, indent=2, default=str)}
```

## Death Causes
```json
{json.dumps(run_data.death_causes, indent=2)}
```

## Model Performance
```json
{json.dumps(run_data.model_performance, indent=2, default=str)}
```

## Moltbook Entries (Bot Learnings)
```json
{json.dumps(run_data.moltbook_entries[:20], indent=2, default=str)}
```

## Sample Events
```json
{json.dumps(run_data.events[:50], indent=2, default=str)}
```

## Sample Bot Logs
"""
    # Add some bot log samples
    for bot_name, logs in list(run_data.bot_logs.items())[:3]:
        context += f"\n### {bot_name} (last 10 entries)\n```json\n"
        context += json.dumps(logs[-10:], indent=2, default=str)
        context += "\n```\n"

    # Build prompt
    prompt = f"""{context}

---

User Question: {question}

Please analyze the data and answer the question. Be specific and reference actual data from the run."""

    # Call Claude via CLI
    print(f"\nQuerying Claude ({model})...")

    try:
        result = subprocess.run(
            ["claude", "-p", prompt, "--model", model, "--output-format", "text"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return result.stdout.strip()
        else:
            return f"Error: {result.stderr}"

    except FileNotFoundError:
        return "Error: Claude CLI not found. Install it or use --export-only to just export the data."
    except subprocess.TimeoutExpired:
        return "Error: Claude query timed out after 120 seconds."
    except Exception as e:
        return f"Error: {e}"


def interactive_mode(run_data: RunData, model: str = "sonnet"):
    """Interactive question-answer mode."""
    print("\n" + "=" * 60)
    print("INTERACTIVE ANALYSIS MODE")
    print("=" * 60)
    print("Ask questions about the run data. Type 'quit' to exit.")
    print("Type 'summary' to see the run summary.")
    print("Type 'export <path>' to export data to JSON.")
    print()

    while True:
        try:
            question = input("Question: ").strip()
        except (KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break

        if not question:
            continue

        if question.lower() == "quit":
            break

        if question.lower() == "summary":
            print(run_data.summary())
            continue

        if question.lower().startswith("export "):
            path = Path(question[7:].strip())
            export_run_data(run_data, path)
            continue

        # Query Claude
        response = query_claude(question, run_data, model)
        print("\n" + "-" * 60)
        print(response)
        print("-" * 60 + "\n")


def main():
    parser = argparse.ArgumentParser(description="Analyze MoltNet run data with Claude")
    parser.add_argument("--run", type=Path, help="Path to archived run directory")
    parser.add_argument("--export-only", action="store_true", help="Only export data, don't query Claude")
    parser.add_argument("--export-path", type=Path, default=Path("run_analysis.json"), help="Export path")
    parser.add_argument("--question", "-q", type=str, help="Ask a specific question (non-interactive)")
    parser.add_argument("--model", type=str, default="sonnet", choices=["sonnet", "opus", "haiku"],
                        help="Claude model to use")
    args = parser.parse_args()

    # Collect data
    run_data = collect_run_data(args.run)

    print()
    print(run_data.summary())

    # Export
    if args.export_only or args.export_path:
        export_run_data(run_data, args.export_path)

    if args.export_only:
        return

    # Query mode
    if args.question:
        # Single question
        response = query_claude(args.question, run_data, args.model)
        print("\n" + "=" * 60)
        print("ANALYSIS")
        print("=" * 60)
        print(response)
    else:
        # Interactive mode
        interactive_mode(run_data, args.model)


if __name__ == "__main__":
    main()
