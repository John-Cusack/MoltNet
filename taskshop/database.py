"""SQLite database operations for Task Shop."""

from __future__ import annotations

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from taskshop.config import settings

SCHEMA_SQL = """
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;

-- Tasks table (benchmark problems)
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    benchmark TEXT NOT NULL,
    benchmark_id TEXT NOT NULL,
    category TEXT NOT NULL,
    difficulty REAL NOT NULL DEFAULT 0.5,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    setup_code TEXT,
    test_code TEXT,
    ground_truth TEXT,
    metadata TEXT,
    UNIQUE(benchmark, benchmark_id)
);

-- Task availability tracking
CREATE TABLE IF NOT EXISTS task_availability (
    task_id TEXT PRIMARY KEY,
    benchmark TEXT NOT NULL,
    category TEXT NOT NULL,
    difficulty REAL NOT NULL,
    times_assigned INTEGER DEFAULT 0,
    times_completed INTEGER DEFAULT 0,
    is_available INTEGER DEFAULT 1,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- Assignments table
CREATE TABLE IF NOT EXISTS assignments (
    id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    cycles_spent INTEGER DEFAULT 0,
    max_cycles INTEGER DEFAULT 3,
    assigned_at REAL NOT NULL,
    completed_at REAL,
    score REAL,
    payout REAL,
    verification_feedback TEXT,
    FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE CASCADE
);

-- Conversation turns for multi-cycle tasks
CREATE TABLE IF NOT EXISTS conversation_turns (
    id TEXT PRIMARY KEY,
    assignment_id TEXT NOT NULL,
    cycle_number INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    timestamp REAL NOT NULL,
    FOREIGN KEY (assignment_id) REFERENCES assignments(id) ON DELETE CASCADE
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tasks_benchmark ON tasks(benchmark);
CREATE INDEX IF NOT EXISTS idx_tasks_category ON tasks(category);
CREATE INDEX IF NOT EXISTS idx_tasks_difficulty ON tasks(difficulty);
CREATE INDEX IF NOT EXISTS idx_availability_category ON task_availability(category, difficulty);
CREATE INDEX IF NOT EXISTS idx_availability_available
    ON task_availability(is_available, category, difficulty);
CREATE INDEX IF NOT EXISTS idx_assignments_bot ON assignments(bot_name, status);
CREATE INDEX IF NOT EXISTS idx_assignments_task ON assignments(task_id);
CREATE INDEX IF NOT EXISTS idx_assignments_status ON assignments(status);
CREATE INDEX IF NOT EXISTS idx_conversation_assignment
    ON conversation_turns(assignment_id, cycle_number);
"""


class TaskShopDatabase:
    """Async SQLite database wrapper for Task Shop."""

    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path or settings.database_path)
        self._connection: aiosqlite.Connection | None = None
        self._start_time = time.time()
        self._claim_lock = asyncio.Lock()

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

    # ==================== Task Operations ====================

    async def insert_task(self, data: dict[str, Any]) -> str:
        """Insert a benchmark task.

        Returns the task ID.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        task_id = data.get("id", str(uuid.uuid4()))
        metadata_json = json.dumps(data.get("metadata")) if data.get("metadata") else None

        await self._connection.execute(
            """
            INSERT OR IGNORE INTO tasks (
                id, benchmark, benchmark_id, category, difficulty,
                title, prompt, setup_code, test_code, ground_truth, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                data["benchmark"],
                data["benchmark_id"],
                data["category"],
                data.get("difficulty", 0.5),
                data["title"],
                data["prompt"],
                data.get("setup_code"),
                data.get("test_code"),
                data.get("ground_truth"),
                metadata_json,
            ),
        )

        # Create availability record
        await self._connection.execute(
            """
            INSERT OR IGNORE INTO task_availability (
                task_id, benchmark, category, difficulty
            ) VALUES (?, ?, ?, ?)
            """,
            (task_id, data["benchmark"], data["category"], data.get("difficulty", 0.5)),
        )

        await self._connection.commit()
        return task_id

    async def insert_tasks_batch(self, tasks: list[dict[str, Any]]) -> int:
        """Insert multiple tasks in a batch.

        Returns the number of tasks inserted.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        count = 0
        for task_data in tasks:
            task_id = task_data.get("id", str(uuid.uuid4()))
            metadata_json = (
                json.dumps(task_data.get("metadata")) if task_data.get("metadata") else None
            )

            try:
                await self._connection.execute(
                    """
                    INSERT OR IGNORE INTO tasks (
                        id, benchmark, benchmark_id, category, difficulty,
                        title, prompt, setup_code, test_code, ground_truth, metadata
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        task_data["benchmark"],
                        task_data["benchmark_id"],
                        task_data["category"],
                        task_data.get("difficulty", 0.5),
                        task_data["title"],
                        task_data["prompt"],
                        task_data.get("setup_code"),
                        task_data.get("test_code"),
                        task_data.get("ground_truth"),
                        metadata_json,
                    ),
                )

                await self._connection.execute(
                    """
                    INSERT OR IGNORE INTO task_availability (
                        task_id, benchmark, category, difficulty
                    ) VALUES (?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        task_data["benchmark"],
                        task_data["category"],
                        task_data.get("difficulty", 0.5),
                    ),
                )
                count += 1
            except Exception:
                continue

        await self._connection.commit()
        return count

    async def browse_tasks(
        self,
        category: str | None = None,
        benchmark: str | None = None,
        difficulty_min: float = 0.0,
        difficulty_max: float = 1.0,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Browse available tasks with filters.

        Returns (tasks, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = ["ta.is_available = 1", "ta.difficulty >= ?", "ta.difficulty <= ?"]
        params: list[Any] = [difficulty_min, difficulty_max]

        if category:
            conditions.append("ta.category = ?")
            params.append(category)
        if benchmark:
            conditions.append("ta.benchmark = ?")
            params.append(benchmark)

        where = " AND ".join(conditions)

        # Count
        count_query = f"""
            SELECT COUNT(*) as total FROM task_availability ta WHERE {where}
        """
        async with self._connection.execute(count_query, params) as cursor:
            row = await cursor.fetchone()
            total = row["total"] if row else 0

        # Fetch
        query = f"""
            SELECT t.id, t.benchmark, t.benchmark_id, t.category, t.difficulty,
                   t.title, ta.times_assigned, ta.times_completed
            FROM tasks t
            JOIN task_availability ta ON t.id = ta.task_id
            WHERE {where}
            ORDER BY ta.times_assigned ASC, t.difficulty ASC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        tasks = [
            {
                "id": row["id"],
                "benchmark": row["benchmark"],
                "benchmark_id": row["benchmark_id"],
                "category": row["category"],
                "difficulty": row["difficulty"],
                "title": row["title"],
                "times_assigned": row["times_assigned"],
                "times_completed": row["times_completed"],
            }
            for row in rows
        ]

        return tasks, total

    async def get_task(self, task_id: str) -> dict[str, Any] | None:
        """Get a task by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM tasks WHERE id = ?"
        async with self._connection.execute(query, (task_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_task(row)

    # ==================== Assignment Operations ====================

    async def claim_task(
        self,
        bot_name: str,
        category: str | None = None,
        benchmark: str | None = None,
        difficulty_min: float = 0.0,
        difficulty_max: float = 1.0,
        max_cycles: int = 3,
    ) -> dict[str, Any] | None:
        """Claim an available task for a bot.

        Serialized with asyncio.Lock to prevent race conditions when
        multiple bots claim simultaneously on the same SQLite connection.
        Returns assignment dict or None if no tasks available.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        async with self._claim_lock:
            # Check if bot already has an active assignment
            active_check = """
                SELECT COUNT(*) as count FROM assignments
                WHERE bot_name = ? AND status = 'active'
            """
            async with self._connection.execute(active_check, (bot_name,)) as cursor:
                row = await cursor.fetchone()
                if row and row["count"] >= settings.max_active_assignments:
                    return None

            # Find an available task
            conditions = ["ta.is_available = 1", "ta.difficulty >= ?", "ta.difficulty <= ?"]
            params: list[Any] = [difficulty_min, difficulty_max]

            if category:
                conditions.append("ta.category = ?")
                params.append(category)
            if benchmark:
                conditions.append("ta.benchmark = ?")
                params.append(benchmark)

            where = " AND ".join(conditions)

            # Select task with fewest assignments (least-served first)
            select_query = f"""
                SELECT ta.task_id FROM task_availability ta
                WHERE {where}
                ORDER BY ta.times_assigned ASC, RANDOM()
                LIMIT 1
            """
            async with self._connection.execute(select_query, params) as cursor:
                row = await cursor.fetchone()

            if not row:
                return None

            task_id = row["task_id"]

            # Mark as assigned
            await self._connection.execute(
                """
                UPDATE task_availability
                SET times_assigned = times_assigned + 1
                WHERE task_id = ?
                """,
                (task_id,),
            )

            # Create assignment
            assignment_id = str(uuid.uuid4())
            now = time.time()

            await self._connection.execute(
                """
                INSERT INTO assignments (
                    id, task_id, bot_name, status, cycles_spent,
                    max_cycles, assigned_at
                ) VALUES (?, ?, ?, 'active', 0, ?, ?)
                """,
                (assignment_id, task_id, bot_name, max_cycles, now),
            )

            # Add initial prompt as first conversation turn
            task = await self.get_task(task_id)
            if task:
                await self._connection.execute(
                    """
                    INSERT INTO conversation_turns (
                        id, assignment_id, cycle_number, role, content, timestamp
                    ) VALUES (?, ?, 0, 'system', ?, ?)
                    """,
                    (str(uuid.uuid4()), assignment_id, task["prompt"], now),
                )

            await self._connection.commit()

            return {
                "assignment_id": assignment_id,
                "task_id": task_id,
                "bot_name": bot_name,
                "status": "active",
                "cycles_spent": 0,
                "max_cycles": max_cycles,
                "assigned_at": now,
            }

    async def get_active_assignment(
        self, bot_name: str
    ) -> dict[str, Any] | None:
        """Get a bot's active assignment with task and conversation history."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT a.*, t.benchmark, t.benchmark_id, t.category, t.difficulty,
                   t.title, t.prompt, t.setup_code, t.metadata
            FROM assignments a
            JOIN tasks t ON a.task_id = t.id
            WHERE a.bot_name = ? AND a.status = 'active'
            ORDER BY a.assigned_at DESC
            LIMIT 1
        """
        async with self._connection.execute(query, (bot_name,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        # Get conversation history
        history = await self._get_conversation_history(row["id"])

        metadata = json.loads(row["metadata"]) if row["metadata"] else None

        return {
            "assignment_id": row["id"],
            "task": {
                "id": row["task_id"],
                "benchmark": row["benchmark"],
                "benchmark_id": row["benchmark_id"],
                "category": row["category"],
                "difficulty": row["difficulty"],
                "title": row["title"],
                "prompt": row["prompt"],
                "setup_code": row["setup_code"],
                "metadata": metadata,
            },
            "status": row["status"],
            "cycles_spent": row["cycles_spent"],
            "max_cycles": row["max_cycles"],
            "assigned_at": datetime.fromtimestamp(row["assigned_at"]),
            "conversation_history": history,
        }

    async def submit_cycle(
        self,
        assignment_id: str,
        bot_name: str,
        action: str,
        response_content: str,
    ) -> dict[str, Any] | None:
        """Submit a cycle update for an assignment.

        Returns updated assignment info.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Verify assignment belongs to bot and is active
        query = """
            SELECT a.*, t.category, t.test_code, t.ground_truth, t.setup_code,
                   t.benchmark, t.difficulty, t.metadata
            FROM assignments a
            JOIN tasks t ON a.task_id = t.id
            WHERE a.id = ? AND a.bot_name = ? AND a.status = 'active'
        """
        async with self._connection.execute(query, (assignment_id, bot_name)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        cycles_spent = row["cycles_spent"] + 1
        now = time.time()

        # Record conversation turn
        await self._connection.execute(
            """
            INSERT INTO conversation_turns (
                id, assignment_id, cycle_number, role, content, timestamp
            ) VALUES (?, ?, ?, 'assistant', ?, ?)
            """,
            (str(uuid.uuid4()), assignment_id, cycles_spent, response_content, now),
        )

        # Update cycles_spent
        await self._connection.execute(
            "UPDATE assignments SET cycles_spent = ? WHERE id = ?",
            (cycles_spent, assignment_id),
        )

        result: dict[str, Any] = {
            "assignment_id": assignment_id,
            "cycles_spent": cycles_spent,
            "max_cycles": row["max_cycles"],
            "action": action,
        }

        if action == "submit":
            # Verify and complete
            from taskshop.payout import calculate_payout
            from taskshop.verification import verify_submission

            task_metadata = (
                json.loads(row["metadata"]) if row["metadata"] else None
            )
            verification = await verify_submission(
                category=row["category"],
                response=response_content,
                test_code=row["test_code"],
                ground_truth=row["ground_truth"],
                setup_code=row["setup_code"],
                metadata=task_metadata,
            )

            payout = 0.0
            if verification.passed:
                payout = calculate_payout(
                    benchmark=row["benchmark"],
                    difficulty=row["difficulty"],
                    score=verification.score,
                    cycles_spent=cycles_spent,
                )
                status = "completed"
            else:
                status = "failed"

            await self._connection.execute(
                """
                UPDATE assignments
                SET status = ?, completed_at = ?, score = ?,
                    payout = ?, verification_feedback = ?
                WHERE id = ?
                """,
                (
                    status,
                    now,
                    verification.score,
                    payout,
                    verification.feedback,
                    assignment_id,
                ),
            )

            # Update task_availability completion count
            if verification.passed:
                await self._connection.execute(
                    """
                    UPDATE task_availability
                    SET times_completed = times_completed + 1
                    WHERE task_id = ?
                    """,
                    (row["task_id"],),
                )

            result.update({
                "status": status,
                "score": verification.score,
                "payout": payout,
                "feedback": verification.feedback,
            })

        elif action == "quit":
            await self._connection.execute(
                "UPDATE assignments SET status = 'abandoned', completed_at = ? WHERE id = ?",
                (now, assignment_id),
            )
            result["status"] = "abandoned"

        elif action == "continue":
            # Check if max cycles reached
            if cycles_spent >= row["max_cycles"]:
                # Auto-submit on last cycle
                from taskshop.payout import calculate_payout
                from taskshop.verification import verify_submission

                task_metadata = (
                    json.loads(row["metadata"]) if row["metadata"] else None
                )
                verification = await verify_submission(
                    category=row["category"],
                    response=response_content,
                    test_code=row["test_code"],
                    ground_truth=row["ground_truth"],
                    setup_code=row["setup_code"],
                    metadata=task_metadata,
                )

                payout = 0.0
                if verification.passed:
                    payout = calculate_payout(
                        benchmark=row["benchmark"],
                        difficulty=row["difficulty"],
                        score=verification.score,
                        cycles_spent=cycles_spent,
                    )
                    status = "completed"
                else:
                    status = "failed"

                await self._connection.execute(
                    """
                    UPDATE assignments
                    SET status = ?, completed_at = ?, score = ?,
                        payout = ?, verification_feedback = ?
                    WHERE id = ?
                    """,
                    (status, now, verification.score, payout, verification.feedback, assignment_id),
                )

                if verification.passed:
                    await self._connection.execute(
                        """
                        UPDATE task_availability
                        SET times_completed = times_completed + 1
                        WHERE task_id = ?
                        """,
                        (row["task_id"],),
                    )

                result.update({
                    "status": status,
                    "score": verification.score,
                    "payout": payout,
                    "feedback": verification.feedback,
                    "auto_submitted": True,
                })
            else:
                result["status"] = "active"

        await self._connection.commit()
        return result

    async def get_assignment_result(
        self, assignment_id: str
    ) -> dict[str, Any] | None:
        """Get the result of a completed assignment."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT a.*, t.benchmark, t.category, t.difficulty, t.title
            FROM assignments a
            JOIN tasks t ON a.task_id = t.id
            WHERE a.id = ?
        """
        async with self._connection.execute(query, (assignment_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return {
            "assignment_id": row["id"],
            "task_id": row["task_id"],
            "bot_name": row["bot_name"],
            "status": row["status"],
            "cycles_spent": row["cycles_spent"],
            "score": row["score"],
            "payout": row["payout"],
            "feedback": row["verification_feedback"],
            "assigned_at": datetime.fromtimestamp(row["assigned_at"]),
            "completed_at": (
                datetime.fromtimestamp(row["completed_at"]) if row["completed_at"] else None
            ),
        }

    # ==================== Statistics ====================

    async def get_stats(self) -> dict[str, Any]:
        """Get overall Task Shop statistics."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Total tasks
        async with self._connection.execute("SELECT COUNT(*) as total FROM tasks") as cursor:
            row = await cursor.fetchone()
            total_tasks = row["total"] if row else 0

        # Tasks by benchmark
        async with self._connection.execute(
            "SELECT benchmark, COUNT(*) as count FROM tasks GROUP BY benchmark"
        ) as cursor:
            rows = await cursor.fetchall()
            tasks_by_benchmark = {r["benchmark"]: r["count"] for r in rows}

        # Tasks by category
        async with self._connection.execute(
            "SELECT category, COUNT(*) as count FROM tasks GROUP BY category"
        ) as cursor:
            rows = await cursor.fetchall()
            tasks_by_category = {r["category"]: r["count"] for r in rows}

        # Assignment stats
        async with self._connection.execute(
            """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'active' THEN 1 ELSE 0 END) as active,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                AVG(CASE WHEN score IS NOT NULL THEN score ELSE NULL END) as avg_score,
                COALESCE(SUM(payout), 0) as total_payouts
            FROM assignments
            """
        ) as cursor:
            row = await cursor.fetchone()

        return {
            "total_tasks": total_tasks,
            "tasks_by_benchmark": tasks_by_benchmark,
            "tasks_by_category": tasks_by_category,
            "total_assignments": row["total"] if row else 0,
            "active_assignments": row["active"] if row else 0,
            "completed_assignments": row["completed"] if row else 0,
            "average_score": row["avg_score"] if row and row["avg_score"] else 0.0,
            "total_payouts": row["total_payouts"] if row else 0.0,
        }

    async def get_bot_stats(self, bot_name: str) -> dict[str, Any]:
        """Get statistics for a specific bot."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = """
            SELECT
                COUNT(*) as total,
                SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed,
                SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed,
                SUM(CASE WHEN status = 'abandoned' THEN 1 ELSE 0 END) as abandoned,
                AVG(CASE WHEN score IS NOT NULL THEN score ELSE NULL END) as avg_score,
                COALESCE(SUM(payout), 0) as total_payout,
                AVG(cycles_spent) as avg_cycles
            FROM assignments
            WHERE bot_name = ?
        """
        async with self._connection.execute(query, (bot_name,)) as cursor:
            row = await cursor.fetchone()

        return {
            "bot_name": bot_name,
            "total_assignments": row["total"] if row else 0,
            "completed": row["completed"] if row else 0,
            "failed": row["failed"] if row else 0,
            "abandoned": row["abandoned"] if row else 0,
            "average_score": row["avg_score"] if row and row["avg_score"] else 0.0,
            "total_payout": row["total_payout"] if row else 0.0,
            "average_cycles": row["avg_cycles"] if row and row["avg_cycles"] else 0.0,
        }

    # ==================== Helpers ====================

    async def _get_conversation_history(
        self, assignment_id: str
    ) -> list[dict[str, Any]]:
        """Get conversation history for an assignment."""
        if not self._connection:
            return []

        query = """
            SELECT cycle_number, role, content, timestamp
            FROM conversation_turns
            WHERE assignment_id = ?
            ORDER BY cycle_number ASC, timestamp ASC
        """
        async with self._connection.execute(query, (assignment_id,)) as cursor:
            rows = await cursor.fetchall()

        return [
            {
                "cycle_number": row["cycle_number"],
                "role": row["role"],
                "content": row["content"],
                "timestamp": datetime.fromtimestamp(row["timestamp"]),
            }
            for row in rows
        ]

    def _row_to_task(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a task dict."""
        metadata = json.loads(row["metadata"]) if row["metadata"] else None

        return {
            "id": row["id"],
            "benchmark": row["benchmark"],
            "benchmark_id": row["benchmark_id"],
            "category": row["category"],
            "difficulty": row["difficulty"],
            "title": row["title"],
            "prompt": row["prompt"],
            "setup_code": row["setup_code"],
            "test_code": row["test_code"],
            "ground_truth": row["ground_truth"],
            "metadata": metadata,
        }


# Singleton instance
db = TaskShopDatabase()
