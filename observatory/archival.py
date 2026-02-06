"""Data archival for Observatory - exports old data before cleanup."""

from __future__ import annotations

import gzip
import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from observatory.config import settings


class DataArchiver:
    """Archives old telemetry and event data before deletion.

    Exports data to compressed JSONL files for historical analysis.
    """

    def __init__(self, archive_path: str | Path | None = None, db_path: str | Path | None = None):
        self.archive_path = Path(
            archive_path or os.environ.get("OBSERVATORY_ARCHIVE_PATH", "archives")
        )
        self.db_path = Path(db_path or settings.database_path)

        # Ensure archive directory exists
        self.archive_path.mkdir(parents=True, exist_ok=True)

    async def archive_old_data(self) -> dict[str, Any]:
        """Archive old data before cleanup.

        Returns statistics about archived data.
        """
        now = int(time.time())
        tel_cutoff = now - settings.telemetry_retention
        evt_cutoff = now - settings.event_retention

        date_str = datetime.now().strftime("%Y-%m-%d")

        stats = {
            "date": date_str,
            "telemetry_archived": 0,
            "events_archived": 0,
            "telemetry_file": None,
            "events_file": None,
        }

        async with aiosqlite.connect(self.db_path) as conn:
            conn.row_factory = aiosqlite.Row

            # Archive old telemetry
            tel_count = await self._archive_telemetry(conn, tel_cutoff, date_str)
            stats["telemetry_archived"] = tel_count
            if tel_count > 0:
                stats["telemetry_file"] = f"telemetry-{date_str}.jsonl.gz"

            # Archive old events
            evt_count = await self._archive_events(conn, evt_cutoff, date_str)
            stats["events_archived"] = evt_count
            if evt_count > 0:
                stats["events_file"] = f"events-{date_str}.jsonl.gz"

        return stats

    async def _archive_telemetry(
        self,
        conn: aiosqlite.Connection,
        cutoff: int,
        date_str: str,
    ) -> int:
        """Archive old telemetry records.

        Returns count of archived records.
        """
        query = """
            SELECT * FROM telemetry
            WHERE timestamp < ?
            ORDER BY timestamp
        """

        archive_file = self.archive_path / f"telemetry-{date_str}.jsonl.gz"

        # If file exists for today, append a counter
        counter = 1
        while archive_file.exists():
            archive_file = self.archive_path / f"telemetry-{date_str}-{counter}.jsonl.gz"
            counter += 1

        count = 0
        async with conn.execute(query, (cutoff,)) as cursor:
            with gzip.open(archive_file, "wt", encoding="utf-8") as f:
                async for row in cursor:
                    record = self._row_to_dict(row)
                    f.write(json.dumps(record, default=str) + "\n")
                    count += 1

        # Remove empty archive file
        if count == 0 and archive_file.exists():
            archive_file.unlink()

        return count

    async def _archive_events(
        self,
        conn: aiosqlite.Connection,
        cutoff: int,
        date_str: str,
    ) -> int:
        """Archive old event records.

        Returns count of archived records.
        """
        query = """
            SELECT * FROM events
            WHERE timestamp < ?
            ORDER BY timestamp
        """

        archive_file = self.archive_path / f"events-{date_str}.jsonl.gz"

        # If file exists for today, append a counter
        counter = 1
        while archive_file.exists():
            archive_file = self.archive_path / f"events-{date_str}-{counter}.jsonl.gz"
            counter += 1

        count = 0
        async with conn.execute(query, (cutoff,)) as cursor:
            with gzip.open(archive_file, "wt", encoding="utf-8") as f:
                async for row in cursor:
                    record = self._row_to_dict(row)
                    # Parse JSON data field
                    if record.get("data"):
                        try:
                            record["data"] = json.loads(record["data"])
                        except json.JSONDecodeError:
                            pass
                    f.write(json.dumps(record, default=str) + "\n")
                    count += 1

        # Remove empty archive file
        if count == 0 and archive_file.exists():
            archive_file.unlink()

        return count

    def _row_to_dict(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a dictionary."""
        return dict(row)

    def list_archives(self) -> list[dict[str, Any]]:
        """List all available archives."""
        archives = []

        for archive_file in sorted(self.archive_path.glob("*.jsonl.gz")):
            stat = archive_file.stat()
            archives.append({
                "filename": archive_file.name,
                "size_bytes": stat.st_size,
                "created": datetime.fromtimestamp(stat.st_ctime).isoformat(),
                "type": "telemetry" if archive_file.name.startswith("telemetry") else "events",
            })

        return archives

    def get_archive_path(self, filename: str) -> Path | None:
        """Get the full path to an archive file.

        Returns None if file doesn't exist or is outside archive directory.
        """
        archive_file = self.archive_path / filename

        # Security check: ensure file is within archive directory
        try:
            archive_file.resolve().relative_to(self.archive_path.resolve())
        except ValueError:
            return None

        if not archive_file.exists():
            return None

        return archive_file


# Singleton instance
archiver = DataArchiver()
