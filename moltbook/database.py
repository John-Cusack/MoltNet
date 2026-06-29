"""SQLite database operations for Moltbook."""

from __future__ import annotations

import json
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from moltbook.config import settings


SCHEMA_SQL = """
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;  -- 32MB cache

-- Knowledge entries table
CREATE TABLE IF NOT EXISTS entries (
    id TEXT PRIMARY KEY,
    author_bot TEXT NOT NULL,
    author_generation INTEGER DEFAULT 1,
    timestamp REAL NOT NULL,
    topic TEXT NOT NULL,
    tags TEXT,  -- JSON array
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    evidence TEXT,  -- JSON object
    citations INTEGER DEFAULT 0
);

-- Citations tracking table
CREATE TABLE IF NOT EXISTS citations (
    entry_id TEXT NOT NULL,
    citing_bot TEXT NOT NULL,
    timestamp REAL NOT NULL,
    PRIMARY KEY (entry_id, citing_bot),
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_entries_topic ON entries(topic);
CREATE INDEX IF NOT EXISTS idx_entries_author ON entries(author_bot);
CREATE INDEX IF NOT EXISTS idx_entries_timestamp ON entries(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_entries_citations ON entries(citations DESC);

-- Full-text search (FTS5)
CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
    id,
    title,
    content,
    tags,
    content='entries',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
    INSERT INTO entries_fts(rowid, id, title, content, tags)
    VALUES (NEW.rowid, NEW.id, NEW.title, NEW.content, NEW.tags);
END;

CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, id, title, content, tags)
    VALUES('delete', OLD.rowid, OLD.id, OLD.title, OLD.content, OLD.tags);
END;

CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
    INSERT INTO entries_fts(entries_fts, rowid, id, title, content, tags)
    VALUES('delete', OLD.rowid, OLD.id, OLD.title, OLD.content, OLD.tags);
    INSERT INTO entries_fts(rowid, id, title, content, tags)
    VALUES (NEW.rowid, NEW.id, NEW.title, NEW.content, NEW.tags);
END;

-- Comments table (threaded)
CREATE TABLE IF NOT EXISTS comments (
    id TEXT PRIMARY KEY,
    entry_id TEXT NOT NULL,
    parent_comment_id TEXT,
    author_bot TEXT NOT NULL,
    author_generation INTEGER DEFAULT 1,
    timestamp REAL NOT NULL,
    content TEXT NOT NULL,
    FOREIGN KEY (entry_id) REFERENCES entries(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_comments_entry ON comments(entry_id);
CREATE INDEX IF NOT EXISTS idx_comments_parent ON comments(parent_comment_id);
CREATE INDEX IF NOT EXISTS idx_comments_timestamp ON comments(timestamp);
"""


class MoltbookDatabase:
    """Async SQLite database wrapper for Moltbook."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or settings.database_path)
        self._connection: aiosqlite.Connection | None = None
        self._start_time = time.time()

    async def connect(self) -> None:
        """Connect to the database and initialize schema."""
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._connection = await aiosqlite.connect(self.db_path)
        self._connection.row_factory = aiosqlite.Row
        await self._connection.executescript(SCHEMA_SQL)
        await self._connection.commit()

    async def close(self) -> None:
        """Close the database connection."""
        if self._connection:
            await self._connection.close()
            self._connection = None

    @property
    def uptime_seconds(self) -> float:
        """Get uptime in seconds."""
        return time.time() - self._start_time

    # ==================== Entry Operations ====================

    async def create_entry(self, data: dict[str, Any]) -> str:
        """Create a new knowledge entry.

        Returns the entry ID.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        entry_id = str(uuid.uuid4())
        timestamp = time.time()

        tags_json = json.dumps(data.get("tags", []))
        evidence_json = json.dumps(data.get("evidence")) if data.get("evidence") else None

        query = """
            INSERT INTO entries (
                id, author_bot, author_generation, timestamp, topic,
                tags, title, content, evidence, citations
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """
        values = (
            entry_id,
            data["author_bot"],
            data.get("author_generation", 1),
            timestamp,
            data["topic"],
            tags_json,
            data["title"],
            data["content"],
            evidence_json,
        )

        await self._connection.execute(query, values)
        await self._connection.commit()
        return entry_id

    async def get_entry(self, entry_id: str) -> dict[str, Any] | None:
        """Get a single entry by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM entries WHERE id = ?"
        async with self._connection.execute(query, (entry_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_entry(row)

    async def list_entries(
        self,
        topic: str | None = None,
        author: str | None = None,
        tags: list[str] | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "timestamp",
        order_desc: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """List entries with optional filters.

        Returns (entries, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = []
        params: list[Any] = []

        if topic:
            conditions.append("topic = ?")
            params.append(topic)

        if author:
            conditions.append("author_bot = ?")
            params.append(author)

        if tags:
            # Match any of the provided tags
            tag_conditions = []
            for tag in tags:
                tag_conditions.append("tags LIKE ?")
                params.append(f'%"{tag}"%')
            conditions.append(f"({' OR '.join(tag_conditions)})")

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Valid order columns
        valid_orders = {"timestamp", "citations", "author_bot", "topic"}
        if order_by not in valid_orders:
            order_by = "timestamp"

        order_dir = "DESC" if order_desc else "ASC"

        # Count total
        count_query = f"SELECT COUNT(*) as total FROM entries WHERE {where_clause}"
        async with self._connection.execute(count_query, params) as cursor:
            count_row = await cursor.fetchone()
            total = count_row["total"] if count_row else 0

        # Fetch entries
        query = f"""
            SELECT * FROM entries
            WHERE {where_clause}
            ORDER BY {order_by} {order_dir}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        entries = [self._row_to_entry(row) for row in rows]
        return entries, total

    async def search_entries(
        self,
        query_text: str,
        topic: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Full-text search across entries.

        Returns (entries, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Build FTS query
        # Escape special characters for FTS5
        safe_query = query_text.replace('"', '""')

        if topic:
            count_query = """
                SELECT COUNT(*) as total FROM entries_fts f
                JOIN entries e ON f.id = e.id
                WHERE entries_fts MATCH ? AND e.topic = ?
            """
            params = [safe_query, topic]
        else:
            count_query = """
                SELECT COUNT(*) as total FROM entries_fts
                WHERE entries_fts MATCH ?
            """
            params = [safe_query]

        async with self._connection.execute(count_query, params) as cursor:
            count_row = await cursor.fetchone()
            total = count_row["total"] if count_row else 0

        if topic:
            search_query = """
                SELECT e.*, bm25(entries_fts) as rank
                FROM entries_fts f
                JOIN entries e ON f.id = e.id
                WHERE entries_fts MATCH ? AND e.topic = ?
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
            params = [safe_query, topic, limit, offset]
        else:
            search_query = """
                SELECT e.*, bm25(entries_fts) as rank
                FROM entries_fts f
                JOIN entries e ON f.id = e.id
                WHERE entries_fts MATCH ?
                ORDER BY rank
                LIMIT ? OFFSET ?
            """
            params = [safe_query, limit, offset]

        async with self._connection.execute(search_query, params) as cursor:
            rows = await cursor.fetchall()

        entries = [self._row_to_entry(row) for row in rows]
        return entries, total

    # ==================== Citation Operations ====================

    async def cite_entry(self, entry_id: str, citing_bot: str) -> bool:
        """Add a citation to an entry.

        Returns True if citation was added, False if already exists.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        try:
            # Insert citation record
            await self._connection.execute(
                "INSERT INTO citations (entry_id, citing_bot, timestamp) VALUES (?, ?, ?)",
                (entry_id, citing_bot, time.time()),
            )

            # Increment citation count
            await self._connection.execute(
                "UPDATE entries SET citations = citations + 1 WHERE id = ?",
                (entry_id,),
            )

            await self._connection.commit()
            return True
        except aiosqlite.IntegrityError:
            # Already cited
            return False

    async def get_citations(self, entry_id: str) -> list[dict[str, Any]]:
        """Get all citations for an entry."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT citing_bot, timestamp
            FROM citations
            WHERE entry_id = ?
            ORDER BY timestamp DESC
        """
        async with self._connection.execute(query, (entry_id,)) as cursor:
            rows = await cursor.fetchall()

        return [
            {"citing_bot": row["citing_bot"], "timestamp": row["timestamp"]}
            for row in rows
        ]

    # ==================== Topic Operations ====================

    async def get_topics(self) -> list[dict[str, Any]]:
        """Get all topics with statistics."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT
                topic,
                COUNT(*) as entry_count,
                COALESCE(SUM(citations), 0) as total_citations
            FROM entries
            GROUP BY topic
            ORDER BY entry_count DESC
        """
        async with self._connection.execute(query) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            # Get top contributors for this topic
            contrib_query = """
                SELECT author_bot, COUNT(*) as count
                FROM entries
                WHERE topic = ?
                GROUP BY author_bot
                ORDER BY count DESC
                LIMIT 3
            """
            async with self._connection.execute(contrib_query, (row["topic"],)) as contrib_cursor:
                contrib_rows = await contrib_cursor.fetchall()
                top_contributors = [r["author_bot"] for r in contrib_rows]

            results.append({
                "topic": row["topic"],
                "entry_count": row["entry_count"],
                "total_citations": row["total_citations"],
                "top_contributors": top_contributors,
            })

        return results

    # ==================== Bot Statistics ====================

    async def get_bot_entries(
        self,
        bot_name: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Get all entries by a specific bot."""
        return await self.list_entries(author=bot_name, limit=limit, offset=offset)

    async def get_bot_stats(self, bot_name: str) -> dict[str, Any]:
        """Get contribution statistics for a bot."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT
                COUNT(*) as entry_count,
                COALESCE(SUM(citations), 0) as total_citations
            FROM entries
            WHERE author_bot = ?
        """
        async with self._connection.execute(query, (bot_name,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return {
                "bot_name": bot_name,
                "entry_count": 0,
                "total_citations": 0,
                "topics": [],
            }

        # Get topics this bot has contributed to
        topics_query = """
            SELECT DISTINCT topic FROM entries
            WHERE author_bot = ?
        """
        async with self._connection.execute(topics_query, (bot_name,)) as cursor:
            topic_rows = await cursor.fetchall()
            topics = [r["topic"] for r in topic_rows]

        return {
            "bot_name": bot_name,
            "entry_count": row["entry_count"],
            "total_citations": row["total_citations"],
            "topics": topics,
        }

    # ==================== Overall Statistics ====================

    async def get_stats(self) -> dict[str, Any]:
        """Get overall Moltbook statistics."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Basic counts
        basic_query = """
            SELECT
                COUNT(*) as total_entries,
                COALESCE(SUM(citations), 0) as total_citations,
                COUNT(DISTINCT author_bot) as unique_contributors
            FROM entries
        """
        async with self._connection.execute(basic_query) as cursor:
            row = await cursor.fetchone()

        if not row:
            return {
                "total_entries": 0,
                "total_citations": 0,
                "unique_contributors": 0,
                "entries_by_topic": {},
                "top_contributors": [],
                "trending_topics": [],
                "recent_entries": [],
            }

        # Entries by topic
        topics_query = """
            SELECT topic, COUNT(*) as count
            FROM entries
            GROUP BY topic
        """
        async with self._connection.execute(topics_query) as cursor:
            topic_rows = await cursor.fetchall()
            entries_by_topic = {r["topic"]: r["count"] for r in topic_rows}

        # Top contributors
        contrib_query = """
            SELECT
                author_bot,
                COUNT(*) as entry_count,
                COALESCE(SUM(citations), 0) as total_citations
            FROM entries
            GROUP BY author_bot
            ORDER BY total_citations DESC, entry_count DESC
            LIMIT 10
        """
        async with self._connection.execute(contrib_query) as cursor:
            contrib_rows = await cursor.fetchall()
            top_contributors = [
                {
                    "bot_name": r["author_bot"],
                    "entry_count": r["entry_count"],
                    "total_citations": r["total_citations"],
                }
                for r in contrib_rows
            ]

        # Recent entries
        recent_query = """
            SELECT * FROM entries
            ORDER BY timestamp DESC
            LIMIT 10
        """
        async with self._connection.execute(recent_query) as cursor:
            recent_rows = await cursor.fetchall()
            recent_entries = [self._row_to_summary(row) for row in recent_rows]

        # Trending topics (most cited in last 24 hours)
        trending = await self.get_topics()

        return {
            "total_entries": row["total_entries"],
            "total_citations": row["total_citations"],
            "unique_contributors": row["unique_contributors"],
            "entries_by_topic": entries_by_topic,
            "top_contributors": top_contributors,
            "trending_topics": trending[:5],
            "recent_entries": recent_entries,
        }

    # ==================== Comment Operations ====================

    async def create_comment(
        self,
        entry_id: str,
        data: dict[str, Any],
        parent_comment_id: str | None = None,
    ) -> str:
        """Create a comment on an entry.

        Returns the comment ID.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        comment_id = str(uuid.uuid4())
        timestamp = time.time()

        query = """
            INSERT INTO comments (
                id, entry_id, parent_comment_id, author_bot,
                author_generation, timestamp, content
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
        """
        values = (
            comment_id,
            entry_id,
            parent_comment_id,
            data["author_bot"],
            data.get("author_generation", 1),
            timestamp,
            data["content"],
        )

        await self._connection.execute(query, values)
        await self._connection.commit()
        return comment_id

    async def get_comments(self, entry_id: str) -> list[dict[str, Any]]:
        """Get all comments for an entry (flat list, caller threads them)."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT * FROM comments
            WHERE entry_id = ?
            ORDER BY timestamp ASC
        """
        async with self._connection.execute(query, (entry_id,)) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_comment(row) for row in rows]

    async def get_comment(self, comment_id: str) -> dict[str, Any] | None:
        """Get a single comment by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM comments WHERE id = ?"
        async with self._connection.execute(query, (comment_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None
        return self._row_to_comment(row)

    def _row_to_comment(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a comment dict."""
        return {
            "id": row["id"],
            "entry_id": row["entry_id"],
            "parent_comment_id": row["parent_comment_id"],
            "author_bot": row["author_bot"],
            "author_generation": row["author_generation"],
            "timestamp": datetime.fromtimestamp(row["timestamp"]),
            "content": row["content"],
        }

    # ==================== Helper Methods ====================

    def _row_to_entry(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to an entry dict."""
        tags = json.loads(row["tags"]) if row["tags"] else []
        evidence = json.loads(row["evidence"]) if row["evidence"] else None

        return {
            "id": row["id"],
            "author_bot": row["author_bot"],
            "author_generation": row["author_generation"],
            "timestamp": datetime.fromtimestamp(row["timestamp"]),
            "topic": row["topic"],
            "tags": tags,
            "title": row["title"],
            "content": row["content"],
            "evidence": evidence,
            "citations": row["citations"],
        }

    def _row_to_summary(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to an entry summary dict."""
        tags = json.loads(row["tags"]) if row["tags"] else []
        content_preview = row["content"][:200] + "..." if len(row["content"]) > 200 else row["content"]

        return {
            "id": row["id"],
            "author_bot": row["author_bot"],
            "author_generation": row["author_generation"],
            "timestamp": datetime.fromtimestamp(row["timestamp"]),
            "topic": row["topic"],
            "tags": tags,
            "title": row["title"],
            "citations": row["citations"],
            "content_preview": content_preview,
        }


# Singleton instance
db = MoltbookDatabase()
