"""SQLite database setup, schema, and queries for Observatory."""

from __future__ import annotations

import time
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from observatory.config import settings

# Schema SQL
SCHEMA_SQL = """
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  -- 64MB cache

-- Telemetry table with Unix timestamps for efficiency
CREATE TABLE IF NOT EXISTS telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bot_name TEXT NOT NULL,
    timestamp INTEGER NOT NULL,  -- Unix epoch seconds
    generation INTEGER,
    fitness_score REAL,
    wallet_balance REAL,
    cycle_count INTEGER,
    state TEXT,
    brain_primary TEXT,
    cycle_revenue REAL,
    cycle_api_spend REAL,
    tasks_completed INTEGER,
    tasks_failed INTEGER,
    genome_hash TEXT,
    parent_name TEXT,
    raw_packet TEXT  -- Full JSON for flexibility
);

-- Events table
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    bot_name TEXT,
    timestamp INTEGER NOT NULL,  -- Unix epoch seconds
    data TEXT  -- JSON data
);

-- Optimized indexes
CREATE INDEX IF NOT EXISTS idx_tel_bot_time ON telemetry(bot_name, timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tel_time ON telemetry(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_tel_brain ON telemetry(brain_primary);

CREATE INDEX IF NOT EXISTS idx_evt_type ON events(event_type);
CREATE INDEX IF NOT EXISTS idx_evt_time ON events(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_evt_bot ON events(bot_name);
"""


class Database:
    """Async SQLite database wrapper for Observatory."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or settings.database_path)
        self._connection: aiosqlite.Connection | None = None
        self._start_time = time.time()

    async def connect(self) -> None:
        """Connect to the database and initialize schema."""
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA_SQL)
        await self._connection.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @asynccontextmanager
    async def cursor(self):
        """Get a database cursor as a context manager."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        async with self._connection.execute("SELECT 1") as cur:
            yield cur

    @property
    def uptime_seconds(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self._start_time

    # ==================== Write Operations ====================

    async def insert_telemetry(self, payload: dict[str, Any]) -> int:
        """Insert a telemetry record.

        Args:
            payload: Telemetry data dict

        Returns:
            Inserted row ID
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        timestamp = payload.get("timestamp")
        if isinstance(timestamp, datetime):
            timestamp = int(timestamp.timestamp())
        elif timestamp is None:
            timestamp = int(time.time())

        import json

        raw_packet = json.dumps(payload.get("extra") or {})

        query = """
            INSERT INTO telemetry (
                bot_name, timestamp, generation, fitness_score, wallet_balance,
                cycle_count, state, brain_primary, cycle_revenue, cycle_api_spend,
                tasks_completed, tasks_failed, genome_hash, parent_name, raw_packet
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        values = (
            payload["bot_name"],
            timestamp,
            payload.get("generation"),
            payload.get("fitness_score"),
            payload.get("wallet_balance"),
            payload.get("cycle_count"),
            payload.get("state"),
            payload.get("brain_primary"),
            payload.get("cycle_revenue"),
            payload.get("cycle_api_spend"),
            payload.get("tasks_completed"),
            payload.get("tasks_failed"),
            payload.get("genome_hash"),
            payload.get("parent_name"),
            raw_packet,
        )

        async with self._connection.execute(query, values) as cursor:
            row_id = cursor.lastrowid
        await self._connection.commit()
        return row_id

    async def insert_event(self, payload: dict[str, Any]) -> int:
        """Insert an event record.

        Args:
            payload: Event data dict

        Returns:
            Inserted row ID
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        timestamp = payload.get("timestamp")
        if isinstance(timestamp, datetime):
            timestamp = int(timestamp.timestamp())
        elif timestamp is None:
            timestamp = int(time.time())

        import json

        data = json.dumps(payload.get("data") or {})

        query = """
            INSERT INTO events (event_type, bot_name, timestamp, data)
            VALUES (?, ?, ?, ?)
        """
        values = (
            payload["event_type"],
            payload.get("bot_name"),
            timestamp,
            data,
        )

        async with self._connection.execute(query, values) as cursor:
            row_id = cursor.lastrowid
        await self._connection.commit()
        return row_id

    # ==================== Read Operations ====================

    async def get_current_bots(self, since_seconds: int = 300) -> list[dict[str, Any]]:
        """Get the most recent telemetry for each bot.

        Args:
            since_seconds: Only include bots seen within this many seconds

        Returns:
            List of bot status dicts
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        cutoff = int(time.time()) - since_seconds

        query = """
            SELECT t1.*
            FROM telemetry t1
            INNER JOIN (
                SELECT bot_name, MAX(timestamp) as max_ts
                FROM telemetry
                WHERE timestamp > ?
                GROUP BY bot_name
            ) t2 ON t1.bot_name = t2.bot_name AND t1.timestamp = t2.max_ts
            ORDER BY t1.fitness_score DESC
        """

        async with self._connection.execute(query, (cutoff,)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_colony_stats(self, since_seconds: int = 3600) -> dict[str, Any]:
        """Get aggregate colony statistics.

        Args:
            since_seconds: Time window in seconds

        Returns:
            Colony stats dict
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        cutoff = int(time.time()) - since_seconds

        query = """
            SELECT
                COUNT(DISTINCT bot_name) as total_bots,
                COALESCE(SUM(cycle_revenue), 0) as total_revenue,
                COALESCE(SUM(cycle_api_spend), 0) as total_api_spend,
                COALESCE(AVG(fitness_score), 0) as avg_fitness,
                COALESCE(SUM(cycle_count), 0) as total_cycles,
                MIN(generation) as min_gen,
                MAX(generation) as max_gen
            FROM telemetry
            WHERE timestamp > ?
        """

        async with self._connection.execute(query, (cutoff,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return {
                "total_bots": 0,
                "active_bots": 0,
                "total_revenue": 0.0,
                "total_api_spend": 0.0,
                "avg_fitness": 0.0,
                "total_cycles": 0,
                "generation_range": None,
            }

        # Count active bots (seen in last 5 minutes)
        active_cutoff = int(time.time()) - 300
        active_query = """
            SELECT COUNT(DISTINCT bot_name) as active_count
            FROM telemetry
            WHERE timestamp > ?
        """
        async with self._connection.execute(active_query, (active_cutoff,)) as cursor:
            active_row = await cursor.fetchone()

        gen_range = None
        if row["min_gen"] is not None and row["max_gen"] is not None:
            gen_range = (row["min_gen"], row["max_gen"])

        return {
            "total_bots": row["total_bots"],
            "active_bots": active_row["active_count"] if active_row else 0,
            "total_revenue": row["total_revenue"],
            "total_api_spend": row["total_api_spend"],
            "avg_fitness": row["avg_fitness"],
            "total_cycles": row["total_cycles"],
            "generation_range": gen_range,
        }

    async def get_brain_leaderboard(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get brain model leaderboard.

        Args:
            limit: Maximum entries to return

        Returns:
            List of leaderboard entries
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT
                brain_primary as brain_model,
                COUNT(*) as usage_count,
                COALESCE(SUM(cycle_revenue), 0) as total_revenue,
                COALESCE(SUM(cycle_api_spend), 0) as total_cost,
                COALESCE(AVG(fitness_score), 0) as avg_fitness,
                COUNT(DISTINCT bot_name) as bot_count
            FROM telemetry
            WHERE brain_primary IS NOT NULL
            GROUP BY brain_primary
            ORDER BY avg_fitness DESC, usage_count DESC
            LIMIT ?
        """

        async with self._connection.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_time_series(
        self,
        metric: str,
        since_seconds: int = 3600,
        bucket_seconds: int = 60,
    ) -> list[dict[str, Any]]:
        """Get time series data for a metric.

        Args:
            metric: Metric name (fitness_score, wallet_balance, etc.)
            since_seconds: Time window
            bucket_seconds: Bucket size for aggregation

        Returns:
            List of time series points
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Validate metric to prevent SQL injection
        valid_metrics = {
            "fitness_score",
            "wallet_balance",
            "cycle_revenue",
            "cycle_api_spend",
        }
        if metric not in valid_metrics:
            return []

        cutoff = int(time.time()) - since_seconds

        query = f"""
            SELECT
                (timestamp / ?) * ? as bucket_time,
                AVG({metric}) as value
            FROM telemetry
            WHERE timestamp > ? AND {metric} IS NOT NULL
            GROUP BY bucket_time
            ORDER BY bucket_time
        """

        async with self._connection.execute(
            query, (bucket_seconds, bucket_seconds, cutoff)
        ) as cursor:
            rows = await cursor.fetchall()

        return [
            {"timestamp": datetime.fromtimestamp(row["bucket_time"]), "value": row["value"]}
            for row in rows
        ]

    async def get_recent_events(
        self, limit: int = 50, event_type: str | None = None
    ) -> list[dict[str, Any]]:
        """Get recent events.

        Args:
            limit: Maximum events to return
            event_type: Filter by event type

        Returns:
            List of event dicts
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        import json

        if event_type:
            query = """
                SELECT id, event_type, bot_name, timestamp, data
                FROM events
                WHERE event_type = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params = (event_type, limit)
        else:
            query = """
                SELECT id, event_type, bot_name, timestamp, data
                FROM events
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params = (limit,)

        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            data = None
            if row["data"]:
                try:
                    data = json.loads(row["data"])
                except json.JSONDecodeError:
                    data = {"raw": row["data"]}

            results.append(
                {
                    "id": row["id"],
                    "event_type": row["event_type"],
                    "bot_name": row["bot_name"],
                    "timestamp": datetime.fromtimestamp(row["timestamp"]),
                    "data": data,
                }
            )

        return results

    async def get_bot_history(
        self, bot_name: str, since_seconds: int = 3600
    ) -> list[dict[str, Any]]:
        """Get telemetry history for a specific bot.

        Args:
            bot_name: Bot identifier
            since_seconds: Time window

        Returns:
            List of telemetry records
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        cutoff = int(time.time()) - since_seconds

        query = """
            SELECT *
            FROM telemetry
            WHERE bot_name = ? AND timestamp > ?
            ORDER BY timestamp DESC
        """

        async with self._connection.execute(query, (bot_name, cutoff)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # ==================== Cleanup Operations ====================

    async def cleanup_old_data(self) -> tuple[int, int]:
        """Delete old telemetry and event data.

        Returns:
            Tuple of (telemetry_deleted, events_deleted)
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        now = int(time.time())
        tel_cutoff = now - settings.telemetry_retention
        evt_cutoff = now - settings.event_retention

        # Delete old telemetry
        async with self._connection.execute(
            "DELETE FROM telemetry WHERE timestamp < ?", (tel_cutoff,)
        ) as cursor:
            tel_deleted = cursor.rowcount

        # Delete old events
        async with self._connection.execute(
            "DELETE FROM events WHERE timestamp < ?", (evt_cutoff,)
        ) as cursor:
            evt_deleted = cursor.rowcount

        await self._connection.commit()
        return tel_deleted, evt_deleted


# Singleton instance
db = Database()
