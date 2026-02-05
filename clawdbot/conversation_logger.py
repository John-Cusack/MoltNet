"""Conversation logger for capturing all LLM interactions.

This module provides logging of all LLM conversations to SQLite for analysis.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass
class ConversationEntry:
    """A logged conversation entry."""

    id: str
    run_id: str
    bot_name: str
    bot_generation: int
    model: str
    timestamp: float
    interaction_type: str
    task_id: str | None
    task_type: str | None
    system_prompt: str | None
    user_prompt: str
    assistant_response: str | None
    input_tokens: int
    output_tokens: int
    latency_ms: float
    cost_usd: float
    success: bool | None
    score: float | None
    thread_id: str | None
    turn_number: int

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> "ConversationEntry":
        """Create from database row."""
        return cls(
            id=row["id"],
            run_id=row["run_id"],
            bot_name=row["bot_name"],
            bot_generation=row["bot_generation"],
            model=row["model"],
            timestamp=row["timestamp"],
            interaction_type=row["interaction_type"],
            task_id=row["task_id"],
            task_type=row["task_type"],
            system_prompt=row["system_prompt"],
            user_prompt=row["user_prompt"],
            assistant_response=row["assistant_response"],
            input_tokens=row["input_tokens"],
            output_tokens=row["output_tokens"],
            latency_ms=row["latency_ms"],
            cost_usd=row["cost_usd"],
            success=None if row["success"] is None else bool(row["success"]),
            score=row["score"],
            thread_id=row["thread_id"],
            turn_number=row["turn_number"],
        )


SCHEMA_SQL = """
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;

-- Conversations table
CREATE TABLE IF NOT EXISTS conversations (
    id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    bot_generation INTEGER,
    model TEXT NOT NULL,
    timestamp REAL NOT NULL,
    interaction_type TEXT NOT NULL,
    task_id TEXT,
    task_type TEXT,
    system_prompt TEXT,
    user_prompt TEXT NOT NULL,
    assistant_response TEXT,
    input_tokens INTEGER,
    output_tokens INTEGER,
    latency_ms REAL,
    cost_usd REAL,
    success INTEGER,
    score REAL,
    thread_id TEXT,
    turn_number INTEGER DEFAULT 1
);

CREATE INDEX IF NOT EXISTS idx_conv_run_bot ON conversations(run_id, bot_name);
CREATE INDEX IF NOT EXISTS idx_conv_type ON conversations(interaction_type);
CREATE INDEX IF NOT EXISTS idx_conv_time ON conversations(timestamp);

-- Full-text search
CREATE VIRTUAL TABLE IF NOT EXISTS conversations_fts USING fts5(
    user_prompt,
    assistant_response,
    content='conversations',
    content_rowid='rowid'
);

-- Triggers for FTS sync
CREATE TRIGGER IF NOT EXISTS conversations_ai AFTER INSERT ON conversations BEGIN
    INSERT INTO conversations_fts(rowid, user_prompt, assistant_response)
    VALUES (NEW.rowid, NEW.user_prompt, NEW.assistant_response);
END;
"""


class ConversationLogger:
    """Logs all LLM conversations to SQLite.

    This logger captures all interactions with language models for
    later analysis, including task execution, reflections, and
    knowledge sharing.

    Thread-safe for use from async contexts.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        run_id: str | None = None,
        enabled: bool = True,
    ):
        """Initialize conversation logger.

        Args:
            db_path: Path to SQLite database. If None, uses default based on run_id.
            run_id: Identifier for the current run.
            enabled: Whether logging is enabled.
        """
        self.enabled = enabled and os.environ.get("CONVERSATION_LOG_ENABLED", "true").lower() == "true"
        self.run_id = run_id or os.environ.get("RUN_ID", "default")

        if db_path:
            self.db_path = Path(db_path)
        else:
            # Use run-specific database (lazy path construction)
            data_dir = Path(os.environ.get("ANALYZER_DATA_DIR", "/data"))
            self.db_path = data_dir / "runs" / self.run_id / "conversations.db"

        self._conn: sqlite3.Connection | None = None
        self._initialized = False

    def _ensure_initialized(self) -> None:
        """Ensure database is initialized."""
        if not self.enabled:
            return

        if not self._initialized:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.executescript(SCHEMA_SQL)
            self._conn.commit()
            self._initialized = True

    def log_conversation(
        self,
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
        """Log a conversation and return its ID.

        Args:
            bot_name: Name of the bot
            bot_generation: Generation number
            model: Model used (e.g., 'claude_code/opus-4-5')
            interaction_type: Type of interaction (task_execution, reflection_periodic, etc.)
            user_prompt: The prompt sent to the model
            assistant_response: The model's response
            system_prompt: System prompt if any
            task_id: Task ID if this is a task execution
            task_type: Task type if applicable
            input_tokens: Number of input tokens
            output_tokens: Number of output tokens
            latency_ms: Response latency in milliseconds
            cost_usd: Cost in USD
            success: Whether the task succeeded (for task_execution)
            score: Score (0-1) for task verification
            thread_id: Thread ID for multi-turn conversations
            turn_number: Turn number in conversation thread

        Returns:
            Conversation ID
        """
        if not self.enabled:
            return str(uuid.uuid4())

        self._ensure_initialized()
        if not self._conn:
            return str(uuid.uuid4())

        conv_id = str(uuid.uuid4())
        success_int = None if success is None else (1 if success else 0)

        try:
            self._conn.execute(
                """
                INSERT INTO conversations (
                    id, run_id, bot_name, bot_generation, model, timestamp,
                    interaction_type, task_id, task_type,
                    system_prompt, user_prompt, assistant_response,
                    input_tokens, output_tokens, latency_ms, cost_usd,
                    success, score, thread_id, turn_number
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    conv_id,
                    self.run_id,
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
            self._conn.commit()
        except sqlite3.Error:
            # Log errors but don't crash the bot
            pass

        return conv_id

    def search(self, query: str, limit: int = 100) -> list[ConversationEntry]:
        """Full-text search in prompts and responses.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching conversation entries
        """
        if not self.enabled:
            return []

        self._ensure_initialized()
        if not self._conn:
            return []

        try:
            cursor = self._conn.execute(
                """
                SELECT c.* FROM conversations c
                JOIN conversations_fts fts ON c.rowid = fts.rowid
                WHERE conversations_fts MATCH ? AND c.run_id = ?
                ORDER BY c.timestamp DESC
                LIMIT ?
                """,
                (query, self.run_id, limit),
            )
            return [ConversationEntry.from_row(row) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def get_bot_conversations(
        self,
        bot_name: str,
        interaction_type: str | None = None,
        limit: int = 1000,
    ) -> list[ConversationEntry]:
        """Get all conversations for a bot.

        Args:
            bot_name: Bot name
            interaction_type: Filter by type
            limit: Maximum results

        Returns:
            List of conversation entries
        """
        if not self.enabled:
            return []

        self._ensure_initialized()
        if not self._conn:
            return []

        try:
            if interaction_type:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE run_id = ? AND bot_name = ? AND interaction_type = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (self.run_id, bot_name, interaction_type, limit),
                )
            else:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE run_id = ? AND bot_name = ?
                    ORDER BY timestamp DESC
                    LIMIT ?
                    """,
                    (self.run_id, bot_name, limit),
                )
            return [ConversationEntry.from_row(row) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def get_model_conversations(
        self,
        model: str,
        interaction_type: str | None = None,
        exclude_tasks: bool = False,
        limit: int = 500,
    ) -> list[ConversationEntry]:
        """Get conversations by model (e.g., 'what did opus talk about').

        Args:
            model: Model name or partial match
            interaction_type: Filter by specific type
            exclude_tasks: If True, exclude task_execution
            limit: Maximum results

        Returns:
            List of conversation entries
        """
        if not self.enabled:
            return []

        self._ensure_initialized()
        if not self._conn:
            return []

        conditions = ["run_id = ?", "model LIKE ?"]
        params: list[Any] = [self.run_id, f"%{model}%"]

        if interaction_type:
            conditions.append("interaction_type = ?")
            params.append(interaction_type)

        if exclude_tasks:
            conditions.append("interaction_type != 'task_execution'")

        params.append(limit)

        try:
            cursor = self._conn.execute(
                f"""
                SELECT * FROM conversations
                WHERE {' AND '.join(conditions)}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            )
            return [ConversationEntry.from_row(row) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def get_reflections(self, bot_name: str | None = None) -> list[ConversationEntry]:
        """Get all reflection conversations.

        Args:
            bot_name: Optional bot name filter

        Returns:
            List of reflection entries
        """
        if not self.enabled:
            return []

        self._ensure_initialized()
        if not self._conn:
            return []

        try:
            if bot_name:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE run_id = ? AND bot_name = ? AND interaction_type LIKE 'reflection_%'
                    ORDER BY timestamp DESC
                    """,
                    (self.run_id, bot_name),
                )
            else:
                cursor = self._conn.execute(
                    """
                    SELECT * FROM conversations
                    WHERE run_id = ? AND interaction_type LIKE 'reflection_%'
                    ORDER BY timestamp DESC
                    """,
                    (self.run_id,),
                )
            return [ConversationEntry.from_row(row) for row in cursor.fetchall()]
        except sqlite3.Error:
            return []

    def get_stats(self) -> dict[str, Any]:
        """Get conversation statistics for this run.

        Returns:
            Statistics dictionary
        """
        if not self.enabled:
            return {"enabled": False}

        self._ensure_initialized()
        if not self._conn:
            return {"enabled": False, "error": "not connected"}

        try:
            cursor = self._conn.execute(
                """
                SELECT
                    COUNT(*) as total,
                    COUNT(DISTINCT bot_name) as bots,
                    SUM(CASE WHEN interaction_type = 'task_execution' THEN 1 ELSE 0 END) as tasks,
                    SUM(CASE WHEN interaction_type LIKE 'reflection_%' THEN 1 ELSE 0 END) as reflections,
                    SUM(input_tokens) as input_tokens,
                    SUM(output_tokens) as output_tokens,
                    SUM(cost_usd) as cost
                FROM conversations
                WHERE run_id = ?
                """,
                (self.run_id,),
            )
            row = cursor.fetchone()
            return {
                "enabled": True,
                "total_conversations": row["total"],
                "bots_with_conversations": row["bots"],
                "task_conversations": row["tasks"],
                "reflection_conversations": row["reflections"],
                "total_input_tokens": row["input_tokens"] or 0,
                "total_output_tokens": row["output_tokens"] or 0,
                "total_cost_usd": row["cost"] or 0,
            }
        except sqlite3.Error as e:
            return {"enabled": False, "error": str(e)}

    def close(self) -> None:
        """Close database connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            self._initialized = False


def create_conversation_logger(
    run_id: str | None = None,
    db_path: Path | str | None = None,
) -> ConversationLogger:
    """Create a conversation logger instance.

    Args:
        run_id: Run identifier
        db_path: Optional database path

    Returns:
        ConversationLogger instance
    """
    return ConversationLogger(db_path=db_path, run_id=run_id)
