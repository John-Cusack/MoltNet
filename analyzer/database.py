"""SQLite database schema and queries for Analyzer service."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from analyzer.config import settings


SCHEMA_SQL = """
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -64000;  -- 64MB cache

-- Runs table: tracks individual colony runs
CREATE TABLE IF NOT EXISTS runs (
    run_id TEXT PRIMARY KEY,
    started_at REAL NOT NULL,
    ended_at REAL,
    config TEXT,              -- JSON: run configuration
    total_bots INTEGER DEFAULT 0,
    total_cycles INTEGER DEFAULT 0,
    metadata TEXT             -- JSON: arbitrary metadata
);

-- Conversations table: all LLM interactions
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,      -- UUID
    run_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    bot_generation INTEGER,
    model TEXT NOT NULL,
    timestamp REAL NOT NULL,

    -- Classification
    interaction_type TEXT NOT NULL,  -- task_execution, reflection, moltbook_query, etc.
    task_id TEXT,
    task_type TEXT,

    -- Content
    system_prompt TEXT,
    user_prompt TEXT NOT NULL,
    assistant_response TEXT,

    -- Metrics
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms REAL,
    cost_usd REAL,

    -- Outcome
    success INTEGER,          -- 1=pass, 0=fail, NULL=n/a
    score REAL,               -- 0.0-1.0 for tasks

    -- Threading
    thread_id TEXT,           -- Groups multi-turn conversations
    turn_number INTEGER DEFAULT 1,

    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

-- Indexes for conversations
CREATE INDEX IF NOT EXISTS idx_conv_run_bot ON conversations(run_id, bot_name);
CREATE INDEX IF NOT EXISTS idx_conv_model ON conversations(model);
CREATE INDEX IF NOT EXISTS idx_conv_type ON conversations(interaction_type);
CREATE INDEX IF NOT EXISTS idx_conv_time ON conversations(timestamp);
CREATE INDEX IF NOT EXISTS idx_conv_thread ON conversations(thread_id);

-- Full-text search for conversations
CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
    user_prompt,
    assistant_response,
    content='conversations',
    content_rowid='rowid'
);

-- Trigger to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO conversations_fts(rowid, user_prompt, assistant_response)
    VALUES (NEW.rowid, NEW.user_prompt, NEW.assistant_response);
END;

CREATE TRIGGER IF NOT EXISTS conversations_ad AFTER DELETE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, user_prompt, assistant_response)
    VALUES('delete', OLD.rowid, OLD.user_prompt, OLD.assistant_response);
END;

CREATE TRIGGER IF NOT EXISTS conversations_au AFTER UPDATE ON conversations BEGIN
    INSERT INTO conversations_fts(conversations_fts, rowid, user_prompt, assistant_response)
    VALUES('delete', OLD.rowid, OLD.user_prompt, OLD.assistant_response);
    INSERT INTO conversations_fts(rowid, user_prompt, assistant_response)
    VALUES (NEW.rowid, NEW.user_prompt, NEW.assistant_response);
END;

-- Lifecycle events (denormalized from Observatory for analysis)
CREATE TABLE IF NOT EXISTS lifecycle_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    event_type TEXT NOT NULL,
    timestamp REAL NOT NULL,
    data TEXT,                -- JSON

    FOREIGN KEY (run_id) REFERENCES runs(run_id)
);

CREATE INDEX IF NOT EXISTS idx_life_run_bot ON lifecycle_events(run_id, bot_name);
CREATE INDEX IF NOT EXISTS idx_life_type ON lifecycle_events(event_type);
CREATE INDEX IF NOT EXISTS idx_life_time ON lifecycle_events(timestamp);

-- Bot summary (computed on run end)
CREATE TABLE IF NOT EXISTS bot_summaries (
    run_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    generation INTEGER,
    model TEXT,
    parent_name TEXT,

    -- Lifecycle
    birth_time REAL,
    death_time REAL,
    death_cause TEXT,
    cycles_lived INTEGER,

    -- Economics
    initial_balance REAL,
    final_balance REAL,
    total_revenue REAL,
    total_api_spend REAL,

    -- Performance
    tasks_completed INTEGER,
    tasks_failed INTEGER,
    success_rate REAL,

    -- Family
    children_spawned INTEGER,
    children_survived INTEGER,

    -- Conversations
    total_conversations INTEGER,
    task_conversations INTEGER,
    reflection_conversations INTEGER,

    PRIMARY KEY (run_id, bot_name)
);

CREATE INDEX IF NOT EXISTS idx_summary_model ON bot_summaries(model);
CREATE INDEX IF NOT EXISTS idx_summary_gen ON bot_summaries(generation);
"""


class AnalyzerDatabase:
    """Async SQLite database for conversation analysis."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else settings.combined_db_path
        self._connection: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        """Connect to database and initialize schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA_SQL)
        await self._connection.commit()

    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @asynccontextmanager
    async def transaction(self):
        """Context manager for transactions."""
        if not self._connection:
            raise RuntimeError("Database not connected")
        try:
            yield self._connection
            await self._connection.commit()
        except Exception:
            await self._connection.rollback()
            raise

    # ==================== Run Management ====================

    async def create_run(
        self,
        run_id: str,
        config: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> str:
        """Create a new run record."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            INSERT INTO runs (run_id, started_at, config, metadata)
            VALUES (?, ?, ?, ?)
        """
        await self._connection.execute(
            query,
            (
                run_id,
                time.time(),
                json.dumps(config) if config else None,
                json.dumps(metadata) if metadata else None,
            ),
        )
        await self._connection.commit()
        return run_id

    async def end_run(
        self,
        run_id: str,
        total_bots: int = 0,
        total_cycles: int = 0,
    ) -> None:
        """Mark a run as ended."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            UPDATE runs
            SET ended_at = ?, total_bots = ?, total_cycles = ?
            WHERE run_id = ?
        """
        await self._connection.execute(
            query, (time.time(), total_bots, total_cycles, run_id)
        )
        await self._connection.commit()

    async def get_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        """Get recent runs."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT * FROM runs
            ORDER BY started_at DESC
            LIMIT ?
        """
        async with self._connection.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_run(self, run_id: str) -> dict[str, Any] | None:
        """Get a specific run."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM runs WHERE run_id = ?"
        async with self._connection.execute(query, (run_id,)) as cursor:
            row = await cursor.fetchone()

        return dict(row) if row else None

    # ==================== Conversation Logging ====================

    async def log_conversation(
        self,
        run_id: str,
        bot_name: str,
        bot_generation: int,
        model: str,
        interaction_type: str,
        user_prompt: str,
        assistant_response: str | None = None,
        system_prompt: str | None = None,
        task_id: str | None = None,
        task_type: str | None = None,
        input_tokens: int = 0,
        output_tokens: int = 0,
        latency_ms: float = 0,
        cost_usd: float = 0,
        success: bool | None = None,
        score: float | None = None,
        thread_id: str | None = None,
        turn_number: int = 1,
    ) -> str:
        """Log a conversation and return its ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        conv_id = str(uuid.uuid4())
        success_int = None if success is None else (1 if success else 0)

        query = """
            INSERT INTO conversations (
                id, run_id, bot_name, bot_generation, model, timestamp,
                interaction_type, task_id, task_type,
                system_prompt, user_prompt, assistant_response,
                input_tokens, output_tokens, latency_ms, cost_usd,
                success, score, thread_id, turn_number
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """
        await self._connection.execute(
            query,
            (
                conv_id,
                run_id,
                bot_name,
                bot_generation,
                model,
                time.time(),
                interaction_type,
                task_id,
                task_type,
                system_prompt,
                user_prompt,
                assistant_response,
                input_tokens,
                output_tokens,
                latency_ms,
                cost_usd,
                success_int,
                score,
                thread_id,
                turn_number,
            ),
        )
        await self._connection.commit()
        return conv_id

    async def search_conversations(
        self,
        query: str,
        run_id: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Full-text search in prompts and responses."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        if run_id:
            sql = """
                SELECT c.* FROM conversations c
                JOIN conversations_fts fts ON c.rowid = fts.rowid
                WHERE conversations_fts MATCH ? AND c.run_id = ?
                ORDER BY c.timestamp DESC
                LIMIT ?
            """
            params = (query, run_id, limit)
        else:
            sql = """
                SELECT c.* FROM conversations c
                JOIN conversations_fts fts ON c.rowid = fts.rowid
                WHERE conversations_fts MATCH ?
                ORDER BY c.timestamp DESC
                LIMIT ?
            """
            params = (query, limit)

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_bot_conversations(
        self,
        run_id: str,
        bot_name: str,
        interaction_type: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Get all conversations for a bot."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        if interaction_type:
            sql = """
                SELECT * FROM conversations
                WHERE run_id = ? AND bot_name = ? AND interaction_type = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params = (run_id, bot_name, interaction_type, limit)
        else:
            sql = """
                SELECT * FROM conversations
                WHERE run_id = ? AND bot_name = ?
                ORDER BY timestamp DESC
                LIMIT ?
            """
            params = (run_id, bot_name, limit)

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_model_conversations(
        self,
        model: str,
        interaction_type: str | None = None,
        exclude_tasks: bool = False,
        run_id: str | None = None,
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        """Get conversations by model (e.g., 'what did opus talk about')."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = ["model LIKE ?"]
        params: list[Any] = [f"%{model}%"]

        if interaction_type:
            conditions.append("interaction_type = ?")
            params.append(interaction_type)

        if exclude_tasks:
            conditions.append("interaction_type != 'task_execution'")

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        params.append(limit)

        sql = f"""
            SELECT * FROM conversations
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp DESC
            LIMIT ?
        """

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_conversation(self, conv_id: str) -> dict[str, Any] | None:
        """Get a single conversation by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        sql = "SELECT * FROM conversations WHERE id = ?"
        async with self._connection.execute(sql, (conv_id,)) as cursor:
            row = await cursor.fetchone()

        return dict(row) if row else None

    async def get_conversations(
        self,
        run_id: str | None = None,
        interaction_type: str | None = None,
        model: str | None = None,
        bot_name: str | None = None,
        since_timestamp: float | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """Get conversations with filters."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = []
        params: list[Any] = []

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        if interaction_type:
            conditions.append("interaction_type = ?")
            params.append(interaction_type)

        if model:
            conditions.append("model LIKE ?")
            params.append(f"%{model}%")

        if bot_name:
            conditions.append("bot_name = ?")
            params.append(bot_name)

        if since_timestamp:
            conditions.append("timestamp > ?")
            params.append(since_timestamp)

        where_clause = f"WHERE {' AND '.join(conditions)}" if conditions else ""
        params.extend([limit, offset])

        sql = f"""
            SELECT * FROM conversations
            {where_clause}
            ORDER BY timestamp DESC
            LIMIT ? OFFSET ?
        """

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # ==================== Lifecycle Events ====================

    async def log_lifecycle_event(
        self,
        run_id: str,
        bot_name: str,
        event_type: str,
        data: dict[str, Any] | None = None,
    ) -> int:
        """Log a lifecycle event."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            INSERT INTO lifecycle_events (run_id, bot_name, event_type, timestamp, data)
            VALUES (?, ?, ?, ?, ?)
        """
        async with self._connection.execute(
            query,
            (run_id, bot_name, event_type, time.time(), json.dumps(data) if data else None),
        ) as cursor:
            row_id = cursor.lastrowid

        await self._connection.commit()
        return row_id or 0

    async def get_lifecycle_events(
        self,
        run_id: str,
        bot_name: str | None = None,
        event_type: str | None = None,
    ) -> list[dict[str, Any]]:
        """Get lifecycle events."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = ["run_id = ?"]
        params: list[Any] = [run_id]

        if bot_name:
            conditions.append("bot_name = ?")
            params.append(bot_name)

        if event_type:
            conditions.append("event_type = ?")
            params.append(event_type)

        sql = f"""
            SELECT * FROM lifecycle_events
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp
        """

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            d = dict(row)
            if d.get("data"):
                try:
                    d["data"] = json.loads(d["data"])
                except json.JSONDecodeError:
                    pass
            results.append(d)

        return results

    # ==================== Bot Summaries ====================

    async def upsert_bot_summary(
        self,
        run_id: str,
        bot_name: str,
        **fields,
    ) -> None:
        """Insert or update a bot summary."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Build dynamic INSERT OR REPLACE query
        columns = ["run_id", "bot_name"] + list(fields.keys())
        placeholders = ["?"] * len(columns)
        values = [run_id, bot_name] + list(fields.values())

        sql = f"""
            INSERT OR REPLACE INTO bot_summaries ({', '.join(columns)})
            VALUES ({', '.join(placeholders)})
        """

        await self._connection.execute(sql, values)
        await self._connection.commit()

    async def get_bot_summary(
        self, run_id: str, bot_name: str
    ) -> dict[str, Any] | None:
        """Get a bot summary."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        sql = "SELECT * FROM bot_summaries WHERE run_id = ? AND bot_name = ?"
        async with self._connection.execute(sql, (run_id, bot_name)) as cursor:
            row = await cursor.fetchone()

        return dict(row) if row else None

    async def get_run_summaries(self, run_id: str) -> list[dict[str, Any]]:
        """Get all bot summaries for a run."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        sql = "SELECT * FROM bot_summaries WHERE run_id = ? ORDER BY birth_time"
        async with self._connection.execute(sql, (run_id,)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    # ==================== Analysis Queries ====================

    async def get_timeline_data(self, run_id: str) -> list[dict[str, Any]]:
        """Get timeline data for Gantt visualization."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        sql = """
            SELECT
                bot_name,
                generation,
                model,
                parent_name,
                birth_time,
                death_time,
                death_cause,
                cycles_lived,
                success_rate,
                children_spawned
            FROM bot_summaries
            WHERE run_id = ?
            ORDER BY birth_time
        """

        async with self._connection.execute(sql, (run_id,)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_family_tree_data(self, run_id: str) -> dict[str, Any]:
        """Get family tree data for genealogy visualization."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Get all bots with their relationships
        sql = """
            SELECT
                bot_name,
                generation,
                model,
                parent_name,
                cycles_lived,
                success_rate,
                children_spawned,
                death_cause
            FROM bot_summaries
            WHERE run_id = ?
        """

        async with self._connection.execute(sql, (run_id,)) as cursor:
            rows = await cursor.fetchall()

        bots = [dict(row) for row in rows]

        # Build nodes and edges
        nodes = []
        edges = []

        for bot in bots:
            nodes.append({
                "id": bot["bot_name"],
                "generation": bot["generation"],
                "model": bot["model"],
                "cycles_lived": bot["cycles_lived"],
                "success_rate": bot["success_rate"],
                "children_spawned": bot["children_spawned"],
                "death_cause": bot["death_cause"],
            })

            if bot["parent_name"]:
                edges.append({
                    "source": bot["parent_name"],
                    "target": bot["bot_name"],
                })

        return {"nodes": nodes, "edges": edges}

    async def get_model_comparison(
        self, run_id: str | None = None
    ) -> list[dict[str, Any]]:
        """Compare model performance."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        where_clause = "WHERE run_id = ?" if run_id else ""
        params = (run_id,) if run_id else ()

        sql = f"""
            SELECT
                model,
                COUNT(*) as bot_count,
                AVG(cycles_lived) as avg_lifespan,
                AVG(success_rate) as avg_success,
                AVG(CAST(children_survived AS REAL) / NULLIF(children_spawned, 0)) as offspring_survival,
                SUM(total_revenue) as total_revenue,
                SUM(total_api_spend) as total_cost
            FROM bot_summaries
            {where_clause}
            GROUP BY model
            ORDER BY avg_lifespan DESC
        """

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_reflection_conversations(
        self,
        run_id: str | None = None,
        reflection_type: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        """Get reflection conversations (what bots thought about)."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = ["interaction_type LIKE 'reflection_%'"]
        params: list[Any] = []

        if run_id:
            conditions.append("run_id = ?")
            params.append(run_id)

        if reflection_type:
            conditions.append("interaction_type = ?")
            params.append(f"reflection_{reflection_type}")

        params.append(limit)

        sql = f"""
            SELECT
                bot_name,
                model,
                interaction_type,
                user_prompt,
                assistant_response,
                timestamp
            FROM conversations
            WHERE {' AND '.join(conditions)}
            ORDER BY timestamp DESC
            LIMIT ?
        """

        async with self._connection.execute(sql, params) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]

    async def get_conversation_stats(self, run_id: str) -> dict[str, Any]:
        """Get conversation statistics for a run."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        sql = """
            SELECT
                COUNT(*) as total_conversations,
                COUNT(DISTINCT bot_name) as bots_with_conversations,
                SUM(CASE WHEN interaction_type = 'task_execution' THEN 1 ELSE 0 END) as task_conversations,
                SUM(CASE WHEN interaction_type LIKE 'reflection_%' THEN 1 ELSE 0 END) as reflection_conversations,
                SUM(CASE WHEN interaction_type = 'moltbook_query' THEN 1 ELSE 0 END) as moltbook_queries,
                SUM(input_tokens) as total_input_tokens,
                SUM(output_tokens) as total_output_tokens,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency_ms
            FROM conversations
            WHERE run_id = ?
        """

        async with self._connection.execute(sql, (run_id,)) as cursor:
            row = await cursor.fetchone()

        return dict(row) if row else {}

    async def get_interaction_type_breakdown(
        self, run_id: str
    ) -> list[dict[str, Any]]:
        """Get breakdown by interaction type."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        sql = """
            SELECT
                interaction_type,
                COUNT(*) as count,
                AVG(CASE WHEN success = 1 THEN 1.0 WHEN success = 0 THEN 0.0 ELSE NULL END) as success_rate,
                SUM(cost_usd) as total_cost,
                AVG(latency_ms) as avg_latency_ms
            FROM conversations
            WHERE run_id = ?
            GROUP BY interaction_type
            ORDER BY count DESC
        """

        async with self._connection.execute(sql, (run_id,)) as cursor:
            rows = await cursor.fetchall()

        return [dict(row) for row in rows]


# Singleton instance
analyzer_db = AnalyzerDatabase()
