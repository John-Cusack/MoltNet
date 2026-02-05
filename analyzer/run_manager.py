"""Run manager for lifecycle and data combination.

This module handles:
- Starting and ending runs
- Combining run data into the main analysis database
- Archiving completed runs
"""

from __future__ import annotations

import asyncio
import gzip
import json
import os
import shutil
import sqlite3
import tarfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from analyzer.config import settings


class RunManager:
    """Manages run lifecycle and data combination."""

    def __init__(self, data_dir: Path | str | None = None):
        """Initialize run manager.

        Args:
            data_dir: Base data directory
        """
        self.data_dir = Path(data_dir) if data_dir else settings.data_dir
        self.runs_dir = self.data_dir / "runs"
        self.archives_dir = self.data_dir / "archives"
        self.combined_db = self.data_dir / "combined.db"

        # Directories will be created on first use (lazy initialization)
        self._initialized = False

    def _ensure_dirs(self) -> None:
        """Ensure directories exist (lazy initialization)."""
        if not self._initialized:
            self.runs_dir.mkdir(parents=True, exist_ok=True)
            self.archives_dir.mkdir(parents=True, exist_ok=True)
            self._initialized = True

    def start_run(
        self,
        run_id: str | None = None,
        config: dict[str, Any] | None = None,
    ) -> str:
        """Start a new run.

        Args:
            run_id: Optional run ID (auto-generated if not provided)
            config: Optional run configuration

        Returns:
            Run ID
        """
        self._ensure_dirs()

        if run_id is None:
            run_id = datetime.now().strftime("%Y%m%d_%H%M%S")

        run_dir = self.runs_dir / run_id
        run_dir.mkdir(parents=True, exist_ok=True)

        # Create run-specific database files
        (run_dir / "conversations.db").touch()

        # Write metadata
        metadata = {
            "run_id": run_id,
            "started_at": time.time(),
            "started_at_iso": datetime.now().isoformat(),
            "config": config,
            "status": "running",
        }
        (run_dir / "metadata.json").write_text(json.dumps(metadata, indent=2))

        # Set environment variable for conversation logger
        os.environ["RUN_ID"] = run_id

        return run_id

    def end_run(
        self,
        run_id: str,
        stats: dict[str, Any] | None = None,
        combine: bool = True,
        archive: bool = True,
    ) -> dict[str, Any]:
        """End a run and optionally combine/archive data.

        Args:
            run_id: Run ID to end
            stats: Final run statistics
            combine: Whether to combine data into main DB
            archive: Whether to archive the run

        Returns:
            Summary of operations performed
        """
        run_dir = self.runs_dir / run_id
        if not run_dir.exists():
            raise ValueError(f"Run not found: {run_id}")

        result = {
            "run_id": run_id,
            "combined": False,
            "archived": False,
        }

        # Update metadata
        metadata_path = run_dir / "metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text())
        else:
            metadata = {"run_id": run_id}

        metadata["ended_at"] = time.time()
        metadata["ended_at_iso"] = datetime.now().isoformat()
        metadata["status"] = "completed"
        metadata["final_stats"] = stats or {}
        metadata_path.write_text(json.dumps(metadata, indent=2))

        # Combine data if requested
        if combine and settings.auto_combine_on_shutdown:
            try:
                self._combine_run_data(run_id, run_dir, metadata)
                result["combined"] = True
            except Exception as e:
                result["combine_error"] = str(e)

        # Archive if requested
        if archive and settings.archive_completed_runs:
            try:
                archive_path = self._archive_run(run_id, run_dir)
                result["archived"] = True
                result["archive_path"] = str(archive_path)
            except Exception as e:
                result["archive_error"] = str(e)

        return result

    def get_run_info(self, run_id: str) -> dict[str, Any] | None:
        """Get information about a run.

        Args:
            run_id: Run ID

        Returns:
            Run metadata or None if not found
        """
        run_dir = self.runs_dir / run_id
        metadata_path = run_dir / "metadata.json"

        if not metadata_path.exists():
            return None

        metadata = json.loads(metadata_path.read_text())

        # Add conversation stats if available
        conv_db = run_dir / "conversations.db"
        if conv_db.exists():
            try:
                conn = sqlite3.connect(str(conv_db))
                cursor = conn.execute("SELECT COUNT(*) FROM conversations")
                metadata["conversation_count"] = cursor.fetchone()[0]
                conn.close()
            except sqlite3.Error:
                pass

        return metadata

    def list_runs(self) -> list[dict[str, Any]]:
        """List all runs.

        Returns:
            List of run metadata
        """
        self._ensure_dirs()
        runs = []

        if not self.runs_dir.exists():
            return runs

        for run_dir in sorted(self.runs_dir.iterdir(), reverse=True):
            if run_dir.is_dir():
                info = self.get_run_info(run_dir.name)
                if info:
                    runs.append(info)

        return runs

    def list_archives(self) -> list[dict[str, Any]]:
        """List all archived runs.

        Returns:
            List of archive information
        """
        self._ensure_dirs()
        archives = []

        if not self.archives_dir.exists():
            return archives

        for archive_path in sorted(self.archives_dir.iterdir(), reverse=True):
            if archive_path.suffix == ".gz" or archive_path.name.endswith(".tar.gz"):
                stat = archive_path.stat()
                archives.append({
                    "filename": archive_path.name,
                    "path": str(archive_path),
                    "size_bytes": stat.st_size,
                    "created_at": stat.st_mtime,
                })

        return archives

    def _combine_run_data(
        self,
        run_id: str,
        run_dir: Path,
        metadata: dict[str, Any],
    ) -> None:
        """Combine run data into the main analysis database.

        Args:
            run_id: Run ID
            run_dir: Run directory path
            metadata: Run metadata
        """
        from analyzer.database import AnalyzerDatabase

        # Connect to both databases
        run_conv_db = run_dir / "conversations.db"
        if not run_conv_db.exists():
            return

        # Use sync SQLite for simplicity in combination
        run_conn = sqlite3.connect(str(run_conv_db))
        run_conn.row_factory = sqlite3.Row

        main_conn = sqlite3.connect(str(self.combined_db))

        # Initialize main DB schema
        from analyzer.database import SCHEMA_SQL
        main_conn.executescript(SCHEMA_SQL)

        # Insert run record
        config = metadata.get("config")
        meta = metadata.get("final_stats")
        main_conn.execute(
            """
            INSERT OR REPLACE INTO runs (run_id, started_at, ended_at, config, metadata, total_bots, total_cycles)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                metadata.get("started_at"),
                metadata.get("ended_at"),
                json.dumps(config) if config else None,
                json.dumps(meta) if meta else None,
                meta.get("total_bots", 0) if meta else 0,
                meta.get("total_cycles", 0) if meta else 0,
            ),
        )

        # Copy conversations
        try:
            cursor = run_conn.execute("SELECT * FROM conversations")
            rows = cursor.fetchall()

            for row in rows:
                main_conn.execute(
                    """
                    INSERT OR IGNORE INTO conversations (
                        id, run_id, bot_name, bot_generation, model, timestamp,
                        interaction_type, task_id, task_type,
                        system_prompt, user_prompt, assistant_response,
                        input_tokens, output_tokens, latency_ms, cost_usd,
                        success, score, thread_id, turn_number
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row["id"],
                        row["run_id"],
                        row["bot_name"],
                        row["bot_generation"],
                        row["model"],
                        row["timestamp"],
                        row["interaction_type"],
                        row["task_id"],
                        row["task_type"],
                        row["system_prompt"],
                        row["user_prompt"],
                        row["assistant_response"],
                        row["input_tokens"],
                        row["output_tokens"],
                        row["latency_ms"],
                        row["cost_usd"],
                        row["success"],
                        row["score"],
                        row["thread_id"],
                        row["turn_number"],
                    ),
                )
        except sqlite3.Error:
            pass  # Table may not exist if no conversations logged

        # Compute bot summaries
        self._compute_bot_summaries(run_id, run_conn, main_conn, metadata)

        main_conn.commit()
        main_conn.close()
        run_conn.close()

    def _compute_bot_summaries(
        self,
        run_id: str,
        run_conn: sqlite3.Connection,
        main_conn: sqlite3.Connection,
        metadata: dict[str, Any],
    ) -> None:
        """Compute and store bot summaries.

        Args:
            run_id: Run ID
            run_conn: Run database connection
            main_conn: Main database connection
            metadata: Run metadata
        """
        # Get bot stats from conversations
        try:
            cursor = run_conn.execute(
                """
                SELECT
                    bot_name,
                    bot_generation,
                    model,
                    MIN(timestamp) as birth_time,
                    MAX(timestamp) as last_seen,
                    COUNT(*) as total_conversations,
                    SUM(CASE WHEN interaction_type = 'task_execution' THEN 1 ELSE 0 END) as task_conversations,
                    SUM(CASE WHEN interaction_type LIKE 'reflection_%' THEN 1 ELSE 0 END) as reflection_conversations,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) as tasks_completed,
                    SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END) as tasks_failed,
                    SUM(cost_usd) as total_api_spend
                FROM conversations
                GROUP BY bot_name
                """
            )
            rows = cursor.fetchall()

            for row in rows:
                tasks_total = row["tasks_completed"] + row["tasks_failed"]
                success_rate = row["tasks_completed"] / tasks_total if tasks_total > 0 else 0

                main_conn.execute(
                    """
                    INSERT OR REPLACE INTO bot_summaries (
                        run_id, bot_name, generation, model,
                        birth_time, total_api_spend,
                        tasks_completed, tasks_failed, success_rate,
                        total_conversations, task_conversations, reflection_conversations
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        row["bot_name"],
                        row["bot_generation"],
                        row["model"],
                        row["birth_time"],
                        row["total_api_spend"],
                        row["tasks_completed"],
                        row["tasks_failed"],
                        success_rate,
                        row["total_conversations"],
                        row["task_conversations"],
                        row["reflection_conversations"],
                    ),
                )
        except sqlite3.Error:
            pass

    def _archive_run(self, run_id: str, run_dir: Path) -> Path:
        """Archive a run directory.

        Args:
            run_id: Run ID
            run_dir: Run directory path

        Returns:
            Path to archive file
        """
        archive_path = self.archives_dir / f"{run_id}.tar.gz"

        with tarfile.open(archive_path, "w:gz") as tar:
            tar.add(run_dir, arcname=run_id)

        # Remove original directory after archiving
        shutil.rmtree(run_dir)

        return archive_path

    def extract_archive(self, archive_name: str) -> Path:
        """Extract an archived run.

        Args:
            archive_name: Archive filename

        Returns:
            Path to extracted directory
        """
        archive_path = self.archives_dir / archive_name
        if not archive_path.exists():
            raise ValueError(f"Archive not found: {archive_name}")

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(self.runs_dir)

        # Get extracted run ID from archive name
        run_id = archive_name.replace(".tar.gz", "")
        return self.runs_dir / run_id

    def delete_run(self, run_id: str, include_archive: bool = False) -> bool:
        """Delete a run and optionally its archive.

        Args:
            run_id: Run ID
            include_archive: Also delete archive if exists

        Returns:
            True if deleted
        """
        run_dir = self.runs_dir / run_id
        deleted = False

        if run_dir.exists():
            shutil.rmtree(run_dir)
            deleted = True

        if include_archive:
            archive_path = self.archives_dir / f"{run_id}.tar.gz"
            if archive_path.exists():
                archive_path.unlink()
                deleted = True

        return deleted

    async def get_run_conversations_db(self, run_id: str) -> Path | None:
        """Get path to run's conversation database.

        Args:
            run_id: Run ID

        Returns:
            Path to database or None if not found
        """
        run_dir = self.runs_dir / run_id
        conv_db = run_dir / "conversations.db"

        if conv_db.exists():
            return conv_db

        return None


# Lazy singleton - created on first access via get_run_manager()
_run_manager: RunManager | None = None


def get_run_manager(data_dir: Path | str | None = None) -> RunManager:
    """Get the singleton RunManager instance.

    Args:
        data_dir: Optional data directory (only used on first call)

    Returns:
        RunManager singleton
    """
    global _run_manager
    if _run_manager is None:
        _run_manager = RunManager(data_dir=data_dir)
    return _run_manager
