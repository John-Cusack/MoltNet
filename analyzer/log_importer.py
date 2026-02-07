"""Log importer for analyzer.

Parses JSONL telemetry logs and populates the bot_summaries table
with lifecycle data (births, deaths, replications, cycles).
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def import_run_logs(
    run_id: str,
    logs_dir: Path,
    db_path: Path,
) -> dict[str, Any]:
    """Import JSONL logs from a run into the analyzer database.

    Args:
        run_id: The run identifier
        logs_dir: Directory containing bot-*.jsonl files
        db_path: Path to the analyzer database

    Returns:
        Summary of imported data
    """
    bots: dict[str, dict[str, Any]] = {}
    replications: list[tuple[str, str, int]] = []

    # Parse all JSONL log files
    log_files = list(logs_dir.glob("*.jsonl"))

    for log_file in log_files:
        with open(log_file) as f:
            for line in f:
                try:
                    event = json.loads(line)
                    _process_event(event, bots, replications)
                except json.JSONDecodeError:
                    continue

    # Set parent relationships from replications
    for parent, child, gen in replications:
        if child not in bots:
            # Create entry for child if not seen
            parent_model = bots[parent]["model"] if parent in bots else "unknown"
            bots[child] = _create_bot_entry(child, gen, parent_model)
        bots[child]["parent_name"] = parent

    # Insert into database
    conn = sqlite3.connect(db_path)
    _ensure_table(conn)

    for bot_name, bot in bots.items():
        _insert_bot(conn, run_id, bot)

    conn.commit()
    conn.close()

    return {
        "run_id": run_id,
        "bots_imported": len(bots),
        "replications": len(replications),
        "log_files_processed": len(log_files),
    }


def _process_event(
    event: dict[str, Any],
    bots: dict[str, dict[str, Any]],
    replications: list[tuple[str, str, int]],
) -> None:
    """Process a single log event."""
    event_type = event.get("type")
    bot_name = event.get("bot")

    if event_type == "openclaw_bot_started":
        bots[bot_name] = {
            "bot_name": bot_name,
            "generation": event.get("generation", 1),
            "model": event.get("model", "").replace("claude_code/", ""),
            "birth_time": event.get("ts"),
            "parent_name": None,
            "children_spawned": 0,
            "cycles_lived": 0,
            "success_rate": 0.0,
            "death_cause": None,
            "death_time": None,
            "tasks_completed": 0,
            "tasks_failed": 0,
        }

    elif event_type == "openclaw_replication":
        parent = event.get("bot")
        child = event.get("child_name")
        child_gen = event.get("child_generation", 2)

        if parent and child:
            if parent in bots:
                bots[parent]["children_spawned"] = bots[parent].get("children_spawned", 0) + 1
            replications.append((parent, child, child_gen))

    elif event_type == "openclaw_bot_died":
        if bot_name and bot_name in bots:
            bots[bot_name]["death_cause"] = event.get("cause")
            bots[bot_name]["death_time"] = event.get("ts")
            bots[bot_name]["cycles_lived"] = event.get("cycles_lived", bots[bot_name].get("cycles_lived", 0))

    elif event_type == "openclaw_bot_stopped":
        if bot_name and bot_name in bots:
            bots[bot_name]["cycles_lived"] = event.get("cycles", bots[bot_name].get("cycles_lived", 0))
            if not bots[bot_name].get("death_cause"):
                bots[bot_name]["death_cause"] = event.get("death_cause", "shutdown")

    elif event_type == "telemetry":
        if bot_name and bot_name in bots:
            bots[bot_name]["cycles_lived"] = max(
                bots[bot_name].get("cycles_lived", 0),
                event.get("cycle_count", 0)
            )
            completed = event.get("tasks_completed", 0)
            failed = event.get("tasks_failed", 0)
            bots[bot_name]["tasks_completed"] = completed
            bots[bot_name]["tasks_failed"] = failed
            total = completed + failed
            if total > 0:
                bots[bot_name]["success_rate"] = completed / total


def _create_bot_entry(bot_name: str, generation: int, model: str) -> dict[str, Any]:
    """Create a default bot entry."""
    return {
        "bot_name": bot_name,
        "generation": generation,
        "model": model,
        "parent_name": None,
        "birth_time": None,
        "death_time": None,
        "death_cause": None,
        "cycles_lived": 0,
        "success_rate": 0.0,
        "children_spawned": 0,
        "tasks_completed": 0,
        "tasks_failed": 0,
    }


def _ensure_table(conn: sqlite3.Connection) -> None:
    """Ensure bot_summaries table exists."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS bot_summaries (
            run_id TEXT NOT NULL,
            bot_name TEXT NOT NULL,
            generation INTEGER,
            model TEXT,
            parent_name TEXT,
            birth_time REAL,
            death_time REAL,
            death_cause TEXT,
            cycles_lived INTEGER,
            success_rate REAL,
            children_spawned INTEGER,
            tasks_completed INTEGER,
            tasks_failed INTEGER,
            total_api_spend REAL,
            PRIMARY KEY (run_id, bot_name)
        )
    """)


def _insert_bot(conn: sqlite3.Connection, run_id: str, bot: dict[str, Any]) -> None:
    """Insert a bot into the database."""
    conn.execute("""
        INSERT OR REPLACE INTO bot_summaries
        (run_id, bot_name, generation, model, parent_name, birth_time, death_time,
         death_cause, cycles_lived, success_rate, children_spawned, tasks_completed, tasks_failed)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        run_id,
        bot["bot_name"],
        bot["generation"],
        bot["model"],
        bot["parent_name"],
        bot["birth_time"],
        bot["death_time"],
        bot["death_cause"],
        bot["cycles_lived"],
        bot["success_rate"],
        bot["children_spawned"],
        bot.get("tasks_completed", 0),
        bot.get("tasks_failed", 0),
    ))


# CLI interface
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Import run logs into analyzer")
    parser.add_argument("run_path", help="Path to run directory (e.g., runs/2026-02-05_10-07-55)")
    parser.add_argument("--db", default="data/analyzer/combined.db", help="Database path")
    args = parser.parse_args()

    run_path = Path(args.run_path)
    run_id = run_path.name
    logs_dir = run_path / "logs"

    if not logs_dir.exists():
        print(f"Error: logs directory not found at {logs_dir}")
        exit(1)

    db_path = Path(args.db)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    result = import_run_logs(run_id, logs_dir, db_path)
    print(f"Imported run {result['run_id']}:")
    print(f"  - {result['bots_imported']} bots")
    print(f"  - {result['replications']} replications")
    print(f"  - {result['log_files_processed']} log files processed")
