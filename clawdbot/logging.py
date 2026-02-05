"""File-based logging for bots - provides persistent logs independent of Observatory.

Logs are written in JSONL format (one JSON object per line) for easy parsing.
Supports daily rotation and size-based rotation.
"""

from __future__ import annotations

import gzip
import json
import os
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


@dataclass
class FileLoggerConfig:
    """Configuration for file-based logging."""

    max_size_bytes: int = 100 * 1024 * 1024  # 100MB
    rotate_daily: bool = True
    compress_rotated: bool = True
    max_rotated_files: int = 30


class BotFileLogger:
    """File-based logger for bot telemetry and events.

    Writes logs in JSONL format for easy parsing and streaming.
    Supports rotation by size and/or date.
    """

    def __init__(
        self,
        log_dir: str | Path,
        bot_name: str,
        config: FileLoggerConfig | None = None,
    ):
        self.log_dir = Path(log_dir)
        self.bot_name = bot_name
        self.config = config or FileLoggerConfig()

        # Create log directory
        self.log_dir.mkdir(parents=True, exist_ok=True)

        # Track current log file state
        self._current_date: str | None = None
        self._current_file: Path | None = None
        self._current_size: int = 0

        # Initialize log file
        self._rotate_if_needed()

    def _get_date_str(self) -> str:
        """Get current date string for log file naming."""
        return datetime.now().strftime("%Y-%m-%d")

    def _get_log_path(self, date_str: str | None = None) -> Path:
        """Get the log file path for a given date."""
        date_str = date_str or self._get_date_str()
        return self.log_dir / f"{self.bot_name}-{date_str}.jsonl"

    def _rotate_if_needed(self) -> None:
        """Check if rotation is needed and perform it."""
        current_date = self._get_date_str()

        # Check for date rotation
        if self.config.rotate_daily and self._current_date != current_date:
            self._current_date = current_date
            self._current_file = self._get_log_path(current_date)
            self._current_size = (
                self._current_file.stat().st_size if self._current_file.exists() else 0
            )
            return

        # Check for size rotation
        if (
            self._current_file
            and self._current_size >= self.config.max_size_bytes
        ):
            self._rotate_current_file()

    def _rotate_current_file(self) -> None:
        """Rotate the current log file due to size."""
        if not self._current_file or not self._current_file.exists():
            return

        # Find next available rotation number
        base_name = self._current_file.stem
        rotation_num = 1
        while True:
            if self.config.compress_rotated:
                rotated_path = self.log_dir / f"{base_name}.{rotation_num}.jsonl.gz"
            else:
                rotated_path = self.log_dir / f"{base_name}.{rotation_num}.jsonl"

            if not rotated_path.exists():
                break
            rotation_num += 1

        # Compress and move
        if self.config.compress_rotated:
            with open(self._current_file, "rb") as f_in:
                with gzip.open(rotated_path, "wb") as f_out:
                    f_out.writelines(f_in)
            self._current_file.unlink()
        else:
            self._current_file.rename(rotated_path)

        # Reset size tracking
        self._current_size = 0

        # Cleanup old rotated files
        self._cleanup_old_rotated_files()

    def _cleanup_old_rotated_files(self) -> None:
        """Remove old rotated files beyond the max count."""
        pattern = f"{self.bot_name}-*.jsonl*"
        rotated_files = sorted(
            [
                f
                for f in self.log_dir.glob(pattern)
                if ".gz" in f.name or f.name.count(".") > 1
            ],
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )

        # Remove files beyond the limit
        for old_file in rotated_files[self.config.max_rotated_files :]:
            try:
                old_file.unlink()
            except OSError:
                pass  # Best effort

    def log(self, event_type: str, data: dict[str, Any] | None = None) -> None:
        """Log an event to the file.

        Args:
            event_type: Type of event (e.g., 'telemetry', 'task_completed', 'error')
            data: Event data dictionary
        """
        self._rotate_if_needed()

        entry = {
            "ts": time.time(),
            "type": event_type,
            "bot": self.bot_name,
            **(data or {}),
        }

        line = json.dumps(entry, default=str) + "\n"
        line_bytes = line.encode("utf-8")

        try:
            if self._current_file:
                with open(self._current_file, "a", encoding="utf-8") as f:
                    f.write(line)
                self._current_size += len(line_bytes)
        except OSError as e:
            # Log to stderr as fallback
            import sys
            print(f"[FileLogger] Write error: {e}", file=sys.stderr)

    def log_telemetry(
        self,
        generation: int | None = None,
        fitness_score: float | None = None,
        wallet_balance: float | None = None,
        cycle_count: int | None = None,
        state: str | None = None,
        brain_primary: str | None = None,
        cycle_revenue: float | None = None,
        cycle_api_spend: float | None = None,
        tasks_completed: int | None = None,
        tasks_failed: int | None = None,
        genome_hash: str | None = None,
        parent_name: str | None = None,
        extra: dict[str, Any] | None = None,
    ) -> None:
        """Log telemetry data.

        Mirrors TelemetryReporter.report_telemetry() signature for easy integration.
        """
        data = {
            "generation": generation,
            "fitness_score": fitness_score,
            "wallet_balance": wallet_balance,
            "cycle_count": cycle_count,
            "state": state,
            "brain_primary": brain_primary,
            "cycle_revenue": cycle_revenue,
            "cycle_api_spend": cycle_api_spend,
            "tasks_completed": tasks_completed,
            "tasks_failed": tasks_failed,
            "genome_hash": genome_hash,
            "parent_name": parent_name,
            **(extra or {}),
        }
        # Remove None values
        data = {k: v for k, v in data.items() if v is not None}
        self.log("telemetry", data)

    def log_event(
        self,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> None:
        """Log a named event.

        Args:
            event_type: Type of event (e.g., 'bot_started', 'task_completed')
            data: Event-specific data
        """
        self.log(event_type, data)

    def get_stats(self) -> dict[str, Any]:
        """Get logger statistics."""
        return {
            "log_dir": str(self.log_dir),
            "current_file": str(self._current_file) if self._current_file else None,
            "current_size_bytes": self._current_size,
            "current_date": self._current_date,
            "config": {
                "max_size_bytes": self.config.max_size_bytes,
                "rotate_daily": self.config.rotate_daily,
                "compress_rotated": self.config.compress_rotated,
                "max_rotated_files": self.config.max_rotated_files,
            },
        }


def create_file_logger(
    bot_name: str,
    log_dir: str | Path | None = None,
    config: FileLoggerConfig | None = None,
) -> BotFileLogger:
    """Factory function to create a file logger.

    Uses environment variables for configuration:
    - BOT_LOG_DIR: Base log directory (default: /logs or ./logs)
    - BOT_LOG_ROTATION_SIZE_MB: Max file size before rotation (default: 100)

    Args:
        bot_name: Name of the bot
        log_dir: Override log directory
        config: Override logger configuration

    Returns:
        Configured BotFileLogger instance
    """
    # Determine log directory
    if log_dir is None:
        log_dir = os.environ.get("BOT_LOG_DIR")
        if log_dir is None:
            # Default to /logs if it exists, otherwise ./logs
            if Path("/logs").exists():
                log_dir = "/logs"
            else:
                log_dir = "./logs"

    # Build config from environment if not provided
    if config is None:
        max_size_mb = int(os.environ.get("BOT_LOG_ROTATION_SIZE_MB", "100"))
        config = FileLoggerConfig(max_size_bytes=max_size_mb * 1024 * 1024)

    return BotFileLogger(log_dir=log_dir, bot_name=bot_name, config=config)
