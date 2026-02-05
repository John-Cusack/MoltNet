"""SQLite database operations for MoltGit."""

from __future__ import annotations

import ast
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

import aiosqlite

from moltgit.config import settings


SCHEMA_SQL = """
-- Enable WAL mode for better concurrent read performance
PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA cache_size = -32000;  -- 32MB cache

-- Repositories
CREATE TABLE IF NOT EXISTS repositories (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    owner_bot TEXT NOT NULL,
    description TEXT,
    created_at REAL NOT NULL,
    updated_at REAL NOT NULL,
    stars INTEGER DEFAULT 0,
    readme TEXT,
    UNIQUE(owner_bot, name)
);

-- Files (flat structure for MVP)
CREATE TABLE IF NOT EXISTS files (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    path TEXT NOT NULL,
    content TEXT NOT NULL,
    version INTEGER DEFAULT 1,
    updated_at REAL NOT NULL,
    FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE,
    UNIQUE(repo_id, path)
);

-- Pull Requests
CREATE TABLE IF NOT EXISTS pull_requests (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,
    author_bot TEXT NOT NULL,
    status TEXT DEFAULT 'open',
    created_at REAL NOT NULL,
    merged_at REAL,
    FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE
);

-- PR Changes
CREATE TABLE IF NOT EXISTS pr_changes (
    id TEXT PRIMARY KEY,
    pr_id TEXT NOT NULL,
    file_path TEXT NOT NULL,
    action TEXT NOT NULL,
    new_content TEXT,
    FOREIGN KEY (pr_id) REFERENCES pull_requests(id) ON DELETE CASCADE
);

-- Stars (likes)
CREATE TABLE IF NOT EXISTS stars (
    repo_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    starred_at REAL NOT NULL,
    PRIMARY KEY (repo_id, bot_name),
    FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE
);

-- Downloads tracking
CREATE TABLE IF NOT EXISTS downloads (
    id TEXT PRIMARY KEY,
    repo_id TEXT NOT NULL,
    bot_name TEXT NOT NULL,
    downloaded_at REAL NOT NULL,
    FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE
);

-- Repo analysis (cached)
CREATE TABLE IF NOT EXISTS repo_analysis (
    repo_id TEXT PRIMARY KEY,
    analyzed_at REAL NOT NULL,
    line_count INTEGER,
    file_count INTEGER,
    function_count INTEGER,
    class_count INTEGER,
    docstring_coverage REAL,
    complexity_score REAL,
    patterns TEXT,
    FOREIGN KEY (repo_id) REFERENCES repositories(id) ON DELETE CASCADE
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_repos_owner ON repositories(owner_bot);
CREATE INDEX IF NOT EXISTS idx_repos_updated ON repositories(updated_at DESC);
CREATE INDEX IF NOT EXISTS idx_repos_stars ON repositories(stars DESC);
CREATE INDEX IF NOT EXISTS idx_files_repo ON files(repo_id);
CREATE INDEX IF NOT EXISTS idx_prs_repo ON pull_requests(repo_id);
CREATE INDEX IF NOT EXISTS idx_prs_status ON pull_requests(status);
CREATE INDEX IF NOT EXISTS idx_downloads_repo ON downloads(repo_id);
CREATE INDEX IF NOT EXISTS idx_downloads_time ON downloads(downloaded_at DESC);

-- Full-text search for code
CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5(
    id,
    path,
    content,
    content='files',
    content_rowid='rowid'
);

-- Triggers to keep FTS in sync
CREATE TRIGGER IF NOT EXISTS files_ai AFTER INSERT ON files BEGIN
    INSERT INTO files_fts(rowid, id, path, content)
    VALUES (NEW.rowid, NEW.id, NEW.path, NEW.content);
END;

CREATE TRIGGER IF NOT EXISTS files_ad AFTER DELETE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, id, path, content)
    VALUES('delete', OLD.rowid, OLD.id, OLD.path, OLD.content);
END;

CREATE TRIGGER IF NOT EXISTS files_au AFTER UPDATE ON files BEGIN
    INSERT INTO files_fts(files_fts, rowid, id, path, content)
    VALUES('delete', OLD.rowid, OLD.id, OLD.path, OLD.content);
    INSERT INTO files_fts(rowid, id, path, content)
    VALUES (NEW.rowid, NEW.id, NEW.path, NEW.content);
END;
"""


class MoltGitDatabase:
    """Async SQLite database wrapper for MoltGit."""

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

    # ==================== Repository Operations ====================

    async def create_repo(self, data: dict[str, Any]) -> str:
        """Create a new repository.

        Returns the repo ID.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        repo_id = str(uuid.uuid4())
        timestamp = time.time()

        query = """
            INSERT INTO repositories (
                id, name, owner_bot, description, created_at, updated_at, stars, readme
            ) VALUES (?, ?, ?, ?, ?, ?, 0, ?)
        """
        values = (
            repo_id,
            data["name"],
            data["owner_bot"],
            data.get("description"),
            timestamp,
            timestamp,
            data.get("readme"),
        )

        await self._connection.execute(query, values)
        await self._connection.commit()
        return repo_id

    async def get_repo(self, owner: str, name: str) -> dict[str, Any] | None:
        """Get a repository by owner and name."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM repositories WHERE owner_bot = ? AND name = ?"
        async with self._connection.execute(query, (owner, name)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        repo = self._row_to_repo(row)

        # Get file count
        count_query = "SELECT COUNT(*) as count FROM files WHERE repo_id = ?"
        async with self._connection.execute(count_query, (repo["id"],)) as cursor:
            count_row = await cursor.fetchone()
            repo["file_count"] = count_row["count"] if count_row else 0

        return repo

    async def get_repo_by_id(self, repo_id: str) -> dict[str, Any] | None:
        """Get a repository by ID."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM repositories WHERE id = ?"
        async with self._connection.execute(query, (repo_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        repo = self._row_to_repo(row)

        # Get file count
        count_query = "SELECT COUNT(*) as count FROM files WHERE repo_id = ?"
        async with self._connection.execute(count_query, (repo["id"],)) as cursor:
            count_row = await cursor.fetchone()
            repo["file_count"] = count_row["count"] if count_row else 0

        return repo

    async def list_repos(
        self,
        owner: str | None = None,
        search: str | None = None,
        limit: int = 20,
        offset: int = 0,
        order_by: str = "updated_at",
        order_desc: bool = True,
    ) -> tuple[list[dict[str, Any]], int]:
        """List repositories with optional filters.

        Returns (repos, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = []
        params: list[Any] = []

        if owner:
            conditions.append("owner_bot = ?")
            params.append(owner)

        if search:
            conditions.append("(name LIKE ? OR description LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        # Valid order columns
        valid_orders = {"updated_at", "created_at", "stars", "name"}
        if order_by not in valid_orders:
            order_by = "updated_at"

        order_dir = "DESC" if order_desc else "ASC"

        # Count total
        count_query = f"SELECT COUNT(*) as total FROM repositories WHERE {where_clause}"
        async with self._connection.execute(count_query, params) as cursor:
            count_row = await cursor.fetchone()
            total = count_row["total"] if count_row else 0

        # Fetch repos
        query = f"""
            SELECT * FROM repositories
            WHERE {where_clause}
            ORDER BY {order_by} {order_dir}
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        repos = []
        for row in rows:
            repo = self._row_to_repo(row)
            # Get file count for each repo
            count_query = "SELECT COUNT(*) as count FROM files WHERE repo_id = ?"
            async with self._connection.execute(count_query, (repo["id"],)) as cursor:
                count_row = await cursor.fetchone()
                repo["file_count"] = count_row["count"] if count_row else 0
            repos.append(repo)

        return repos, total

    async def delete_repo(self, owner: str, name: str) -> bool:
        """Delete a repository (and cascade to files, PRs, stars).

        Returns True if deleted.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Check if exists and owned by this bot
        repo = await self.get_repo(owner, name)
        if not repo:
            return False

        await self._connection.execute(
            "DELETE FROM repositories WHERE id = ?",
            (repo["id"],),
        )
        await self._connection.commit()
        return True

    async def update_repo(
        self,
        repo_id: str,
        description: str | None = None,
        readme: str | None = None,
    ) -> bool:
        """Update repository metadata."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        updates = []
        params = []

        if description is not None:
            updates.append("description = ?")
            params.append(description)

        if readme is not None:
            updates.append("readme = ?")
            params.append(readme)

        if not updates:
            return True

        updates.append("updated_at = ?")
        params.append(time.time())
        params.append(repo_id)

        query = f"UPDATE repositories SET {', '.join(updates)} WHERE id = ?"
        await self._connection.execute(query, params)
        await self._connection.commit()
        return True

    # ==================== Star Operations ====================

    async def star_repo(self, repo_id: str, bot_name: str) -> bool:
        """Star a repository.

        Returns True if star was added, False if already starred.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        try:
            await self._connection.execute(
                "INSERT INTO stars (repo_id, bot_name, starred_at) VALUES (?, ?, ?)",
                (repo_id, bot_name, time.time()),
            )
            await self._connection.execute(
                "UPDATE repositories SET stars = stars + 1 WHERE id = ?",
                (repo_id,),
            )
            await self._connection.commit()
            return True
        except aiosqlite.IntegrityError:
            return False

    async def unstar_repo(self, repo_id: str, bot_name: str) -> bool:
        """Remove star from a repository."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "DELETE FROM stars WHERE repo_id = ? AND bot_name = ?",
            (repo_id, bot_name),
        )
        if cursor.rowcount > 0:
            await self._connection.execute(
                "UPDATE repositories SET stars = MAX(0, stars - 1) WHERE id = ?",
                (repo_id,),
            )
            await self._connection.commit()
            return True
        return False

    async def get_stargazers(self, repo_id: str) -> list[dict[str, Any]]:
        """Get list of bots who starred a repo."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT bot_name, starred_at FROM stars WHERE repo_id = ? ORDER BY starred_at DESC"
        async with self._connection.execute(query, (repo_id,)) as cursor:
            rows = await cursor.fetchall()

        return [{"bot_name": r["bot_name"], "starred_at": r["starred_at"]} for r in rows]

    # ==================== File Operations ====================

    async def create_or_update_file(
        self,
        repo_id: str,
        path: str,
        content: str,
        bot_name: str,
    ) -> tuple[str, bool]:
        """Create or update a file.

        Returns (file_id, is_new).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        timestamp = time.time()

        # Check if file exists
        query = "SELECT id, version FROM files WHERE repo_id = ? AND path = ?"
        async with self._connection.execute(query, (repo_id, path)) as cursor:
            existing = await cursor.fetchone()

        if existing:
            # Update existing file
            await self._connection.execute(
                "UPDATE files SET content = ?, version = version + 1, updated_at = ? WHERE id = ?",
                (content, timestamp, existing["id"]),
            )
            await self._connection.execute(
                "UPDATE repositories SET updated_at = ? WHERE id = ?",
                (timestamp, repo_id),
            )
            await self._connection.commit()
            return existing["id"], False
        else:
            # Create new file
            file_id = str(uuid.uuid4())
            await self._connection.execute(
                """INSERT INTO files (id, repo_id, path, content, version, updated_at)
                VALUES (?, ?, ?, ?, 1, ?)""",
                (file_id, repo_id, path, content, timestamp),
            )
            await self._connection.execute(
                "UPDATE repositories SET updated_at = ? WHERE id = ?",
                (timestamp, repo_id),
            )
            await self._connection.commit()
            return file_id, True

    async def get_file(self, repo_id: str, path: str) -> dict[str, Any] | None:
        """Get a file by repo and path."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM files WHERE repo_id = ? AND path = ?"
        async with self._connection.execute(query, (repo_id, path)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return self._row_to_file(row)

    async def list_files(self, repo_id: str) -> list[dict[str, Any]]:
        """List all files in a repository."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM files WHERE repo_id = ? ORDER BY path"
        async with self._connection.execute(query, (repo_id,)) as cursor:
            rows = await cursor.fetchall()

        return [self._row_to_file_summary(row) for row in rows]

    async def delete_file(self, repo_id: str, path: str) -> bool:
        """Delete a file."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "DELETE FROM files WHERE repo_id = ? AND path = ?",
            (repo_id, path),
        )
        if cursor.rowcount > 0:
            await self._connection.execute(
                "UPDATE repositories SET updated_at = ? WHERE id = ?",
                (time.time(), repo_id),
            )
            await self._connection.commit()
            return True
        return False

    # ==================== Pull Request Operations ====================

    async def create_pr(self, repo_id: str, data: dict[str, Any]) -> str:
        """Create a pull request with changes.

        Returns the PR ID.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        pr_id = str(uuid.uuid4())
        timestamp = time.time()

        await self._connection.execute(
            """INSERT INTO pull_requests (id, repo_id, title, description, author_bot, status, created_at)
            VALUES (?, ?, ?, ?, ?, 'open', ?)""",
            (pr_id, repo_id, data["title"], data.get("description"), data["author_bot"], timestamp),
        )

        # Insert changes
        for change in data.get("changes", []):
            change_id = str(uuid.uuid4())
            await self._connection.execute(
                """INSERT INTO pr_changes (id, pr_id, file_path, action, new_content)
                VALUES (?, ?, ?, ?, ?)""",
                (change_id, pr_id, change["file_path"], change["action"], change.get("new_content")),
            )

        await self._connection.commit()
        return pr_id

    async def get_pr(self, pr_id: str) -> dict[str, Any] | None:
        """Get a pull request with its changes."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM pull_requests WHERE id = ?"
        async with self._connection.execute(query, (pr_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        pr = self._row_to_pr(row)

        # Get changes
        changes_query = "SELECT * FROM pr_changes WHERE pr_id = ?"
        async with self._connection.execute(changes_query, (pr_id,)) as cursor:
            change_rows = await cursor.fetchall()

        pr["changes"] = [self._row_to_pr_change(r) for r in change_rows]
        return pr

    async def list_prs(
        self,
        repo_id: str,
        status: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """List pull requests for a repository.

        Returns (prs, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        conditions = ["repo_id = ?"]
        params: list[Any] = [repo_id]

        if status:
            conditions.append("status = ?")
            params.append(status)

        where_clause = " AND ".join(conditions)

        # Count total
        count_query = f"SELECT COUNT(*) as total FROM pull_requests WHERE {where_clause}"
        async with self._connection.execute(count_query, params) as cursor:
            count_row = await cursor.fetchone()
            total = count_row["total"] if count_row else 0

        # Fetch PRs
        query = f"""
            SELECT * FROM pull_requests
            WHERE {where_clause}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
        """
        params.extend([limit, offset])

        async with self._connection.execute(query, params) as cursor:
            rows = await cursor.fetchall()

        prs = []
        for row in rows:
            pr = self._row_to_pr_summary(row)
            # Get change count
            changes_query = "SELECT COUNT(*) as count FROM pr_changes WHERE pr_id = ?"
            async with self._connection.execute(changes_query, (pr["id"],)) as cursor:
                count_row = await cursor.fetchone()
                pr["change_count"] = count_row["count"] if count_row else 0
            prs.append(pr)

        return prs, total

    async def merge_pr(self, pr_id: str) -> bool:
        """Merge a pull request by applying its changes.

        Returns True if merged successfully.
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Get PR
        pr = await self.get_pr(pr_id)
        if not pr or pr["status"] != "open":
            return False

        repo_id = pr["repo_id"]
        timestamp = time.time()

        # Apply changes
        for change in pr["changes"]:
            if change["action"] == "add" or change["action"] == "modify":
                await self.create_or_update_file(
                    repo_id=repo_id,
                    path=change["file_path"],
                    content=change["new_content"] or "",
                    bot_name=pr["author_bot"],
                )
            elif change["action"] == "delete":
                await self.delete_file(repo_id, change["file_path"])

        # Update PR status
        await self._connection.execute(
            "UPDATE pull_requests SET status = 'merged', merged_at = ? WHERE id = ?",
            (timestamp, pr_id),
        )
        await self._connection.commit()
        return True

    async def close_pr(self, pr_id: str) -> bool:
        """Close a pull request without merging."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        cursor = await self._connection.execute(
            "UPDATE pull_requests SET status = 'closed' WHERE id = ? AND status = 'open'",
            (pr_id,),
        )
        await self._connection.commit()
        return cursor.rowcount > 0

    # ==================== Search Operations ====================

    async def search_repos(
        self,
        query_text: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Search repositories by name/description.

        Returns (repos, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        search_pattern = f"%{query_text}%"

        count_query = """
            SELECT COUNT(*) as total FROM repositories
            WHERE name LIKE ? OR description LIKE ?
        """
        async with self._connection.execute(count_query, (search_pattern, search_pattern)) as cursor:
            count_row = await cursor.fetchone()
            total = count_row["total"] if count_row else 0

        query = """
            SELECT * FROM repositories
            WHERE name LIKE ? OR description LIKE ?
            ORDER BY stars DESC, updated_at DESC
            LIMIT ? OFFSET ?
        """
        async with self._connection.execute(query, (search_pattern, search_pattern, limit, offset)) as cursor:
            rows = await cursor.fetchall()

        repos = []
        for row in rows:
            repo = self._row_to_repo(row)
            count_query = "SELECT COUNT(*) as count FROM files WHERE repo_id = ?"
            async with self._connection.execute(count_query, (repo["id"],)) as cursor:
                count_row = await cursor.fetchone()
                repo["file_count"] = count_row["count"] if count_row else 0
            repos.append(repo)

        return repos, total

    async def search_code(
        self,
        query_text: str,
        limit: int = 20,
        offset: int = 0,
    ) -> tuple[list[dict[str, Any]], int]:
        """Full-text search across code files.

        Returns (results, total_count).
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        safe_query = query_text.replace('"', '""')

        count_query = """
            SELECT COUNT(*) as total FROM files_fts
            WHERE files_fts MATCH ?
        """
        async with self._connection.execute(count_query, (safe_query,)) as cursor:
            count_row = await cursor.fetchone()
            total = count_row["total"] if count_row else 0

        search_query = """
            SELECT f.*, r.name as repo_name, r.owner_bot, bm25(files_fts) as rank
            FROM files_fts fts
            JOIN files f ON fts.id = f.id
            JOIN repositories r ON f.repo_id = r.id
            WHERE files_fts MATCH ?
            ORDER BY rank
            LIMIT ? OFFSET ?
        """
        async with self._connection.execute(search_query, (safe_query, limit, offset)) as cursor:
            rows = await cursor.fetchall()

        results = []
        for row in rows:
            content = row["content"]
            # Create a preview around the match
            preview_start = max(0, content.lower().find(query_text.lower()) - 50)
            preview_end = min(len(content), preview_start + 200)
            preview = content[preview_start:preview_end]
            if preview_start > 0:
                preview = "..." + preview
            if preview_end < len(content):
                preview = preview + "..."

            results.append({
                "repo_id": row["repo_id"],
                "repo_name": row["repo_name"],
                "owner_bot": row["owner_bot"],
                "file_path": row["path"],
                "file_id": row["id"],
                "content_preview": preview,
            })

        return results, total

    async def get_trending(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get trending repositories (most stars + recent activity)."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Simple trending: weight stars and recency
        query = """
            SELECT * FROM repositories
            ORDER BY stars DESC, updated_at DESC
            LIMIT ?
        """
        async with self._connection.execute(query, (limit,)) as cursor:
            rows = await cursor.fetchall()

        repos = []
        for row in rows:
            repo = self._row_to_repo(row)
            count_query = "SELECT COUNT(*) as count FROM files WHERE repo_id = ?"
            async with self._connection.execute(count_query, (repo["id"],)) as cursor:
                count_row = await cursor.fetchone()
                repo["file_count"] = count_row["count"] if count_row else 0
            repos.append(repo)

        return repos

    # ==================== Download Operations ====================

    async def record_download(self, repo_id: str, bot_name: str) -> None:
        """Record a package download."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        download_id = str(uuid.uuid4())
        await self._connection.execute(
            "INSERT INTO downloads (id, repo_id, bot_name, downloaded_at) VALUES (?, ?, ?, ?)",
            (download_id, repo_id, bot_name, time.time()),
        )
        await self._connection.commit()

    async def get_download_count(self, repo_id: str) -> int:
        """Get download count for a repository."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT COUNT(*) as count FROM downloads WHERE repo_id = ?"
        async with self._connection.execute(query, (repo_id,)) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0

    # ==================== Analysis Operations ====================

    async def analyze_repo(self, repo_id: str) -> dict[str, Any]:
        """Analyze a repository's code and cache results."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Get all Python files
        query = "SELECT * FROM files WHERE repo_id = ? AND path LIKE '%.py'"
        async with self._connection.execute(query, (repo_id,)) as cursor:
            rows = await cursor.fetchall()

        total_lines = 0
        total_functions = 0
        total_classes = 0
        total_docstrings = 0
        total_items = 0  # functions + classes
        patterns: list[str] = []

        for row in rows:
            content = row["content"]
            lines = content.split("\n")
            total_lines += len(lines)

            try:
                tree = ast.parse(content)

                for node in ast.walk(tree):
                    if isinstance(node, ast.FunctionDef):
                        total_functions += 1
                        total_items += 1
                        if ast.get_docstring(node):
                            total_docstrings += 1
                        # Detect common patterns
                        if node.name.startswith("test_"):
                            if "test_pattern" not in patterns:
                                patterns.append("test_pattern")
                        if node.name.startswith("_"):
                            if "private_methods" not in patterns:
                                patterns.append("private_methods")
                    elif isinstance(node, ast.ClassDef):
                        total_classes += 1
                        total_items += 1
                        if ast.get_docstring(node):
                            total_docstrings += 1
                    elif isinstance(node, ast.AsyncFunctionDef):
                        total_functions += 1
                        total_items += 1
                        if "async_pattern" not in patterns:
                            patterns.append("async_pattern")
                        if ast.get_docstring(node):
                            total_docstrings += 1
            except SyntaxError:
                pass  # Skip files with syntax errors

        docstring_coverage = total_docstrings / total_items if total_items > 0 else 0.0

        # Simple complexity score based on size
        complexity = min(1.0, (total_functions + total_classes * 2) / 50)

        timestamp = time.time()

        # Upsert analysis
        await self._connection.execute(
            """INSERT OR REPLACE INTO repo_analysis
            (repo_id, analyzed_at, line_count, file_count, function_count, class_count,
             docstring_coverage, complexity_score, patterns)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (repo_id, timestamp, total_lines, len(rows), total_functions, total_classes,
             docstring_coverage, complexity, json.dumps(patterns)),
        )
        await self._connection.commit()

        return {
            "repo_id": repo_id,
            "analyzed_at": datetime.fromtimestamp(timestamp),
            "line_count": total_lines,
            "file_count": len(rows),
            "function_count": total_functions,
            "class_count": total_classes,
            "docstring_coverage": docstring_coverage,
            "complexity_score": complexity,
            "patterns": patterns,
        }

    async def get_repo_analysis(self, repo_id: str) -> dict[str, Any] | None:
        """Get cached analysis for a repository."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        query = "SELECT * FROM repo_analysis WHERE repo_id = ?"
        async with self._connection.execute(query, (repo_id,)) as cursor:
            row = await cursor.fetchone()

        if not row:
            return None

        return {
            "repo_id": row["repo_id"],
            "analyzed_at": datetime.fromtimestamp(row["analyzed_at"]),
            "line_count": row["line_count"],
            "file_count": row["file_count"],
            "function_count": row["function_count"],
            "class_count": row["class_count"],
            "docstring_coverage": row["docstring_coverage"],
            "complexity_score": row["complexity_score"],
            "patterns": json.loads(row["patterns"]) if row["patterns"] else [],
        }

    # ==================== Export Operations ====================

    async def export_repos_since(self, since_timestamp: float) -> dict[str, Any]:
        """Export all repos and files created since timestamp.

        Returns: {repos: [...], files: {repo_id: [files]}}
        """
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Get repos created since timestamp
        repos_query = "SELECT * FROM repositories WHERE created_at >= ?"
        async with self._connection.execute(repos_query, (since_timestamp,)) as cursor:
            repo_rows = await cursor.fetchall()

        repos = [self._row_to_repo(row) for row in repo_rows]
        repo_ids = [r["id"] for r in repos]

        # Get all files for these repos
        files_by_repo: dict[str, list[dict[str, Any]]] = {}
        for repo_id in repo_ids:
            files_query = "SELECT * FROM files WHERE repo_id = ?"
            async with self._connection.execute(files_query, (repo_id,)) as cursor:
                file_rows = await cursor.fetchall()
            files_by_repo[repo_id] = [self._row_to_file(row) for row in file_rows]

        return {
            "repos": repos,
            "files": files_by_repo,
            "exported_at": time.time(),
            "since": since_timestamp,
        }

    # ==================== Statistics ====================

    async def get_stats(self) -> dict[str, Any]:
        """Get overall MoltGit statistics."""
        if not self._connection:
            raise RuntimeError("Database not connected")

        # Basic counts
        repo_count = await self._count_table("repositories")
        file_count = await self._count_table("files")
        pr_count = await self._count_table("pull_requests")
        star_count = await self._count_table("stars")
        download_count = await self._count_table("downloads")

        # Unique contributors
        contrib_query = "SELECT COUNT(DISTINCT owner_bot) as count FROM repositories"
        async with self._connection.execute(contrib_query) as cursor:
            row = await cursor.fetchone()
            unique_contributors = row["count"] if row else 0

        # Top repos
        top_repos = await self.get_trending(5)

        # Recent repos
        recent_query = "SELECT * FROM repositories ORDER BY created_at DESC LIMIT 5"
        async with self._connection.execute(recent_query) as cursor:
            recent_rows = await cursor.fetchall()
        recent_repos = [self._row_to_repo(row) for row in recent_rows]

        return {
            "total_repos": repo_count,
            "total_files": file_count,
            "total_prs": pr_count,
            "total_stars": star_count,
            "total_downloads": download_count,
            "unique_contributors": unique_contributors,
            "top_repos": top_repos,
            "recent_repos": recent_repos,
        }

    async def _count_table(self, table: str) -> int:
        """Count rows in a table."""
        if not self._connection:
            return 0
        query = f"SELECT COUNT(*) as count FROM {table}"
        async with self._connection.execute(query) as cursor:
            row = await cursor.fetchone()
            return row["count"] if row else 0

    # ==================== Helper Methods ====================

    def _row_to_repo(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a repo dict."""
        return {
            "id": row["id"],
            "name": row["name"],
            "owner_bot": row["owner_bot"],
            "description": row["description"],
            "created_at": datetime.fromtimestamp(row["created_at"]),
            "updated_at": datetime.fromtimestamp(row["updated_at"]),
            "stars": row["stars"],
            "readme": row["readme"],
        }

    def _row_to_file(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a file dict."""
        return {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "path": row["path"],
            "content": row["content"],
            "version": row["version"],
            "updated_at": datetime.fromtimestamp(row["updated_at"]),
        }

    def _row_to_file_summary(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a file summary dict."""
        return {
            "id": row["id"],
            "path": row["path"],
            "version": row["version"],
            "updated_at": datetime.fromtimestamp(row["updated_at"]),
            "size": len(row["content"]),
        }

    def _row_to_pr(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a PR dict."""
        return {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "title": row["title"],
            "description": row["description"],
            "author_bot": row["author_bot"],
            "status": row["status"],
            "created_at": datetime.fromtimestamp(row["created_at"]),
            "merged_at": datetime.fromtimestamp(row["merged_at"]) if row["merged_at"] else None,
        }

    def _row_to_pr_summary(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a PR summary dict."""
        return {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "title": row["title"],
            "author_bot": row["author_bot"],
            "status": row["status"],
            "created_at": datetime.fromtimestamp(row["created_at"]),
        }

    def _row_to_pr_change(self, row: aiosqlite.Row) -> dict[str, Any]:
        """Convert a database row to a PR change dict."""
        return {
            "id": row["id"],
            "pr_id": row["pr_id"],
            "file_path": row["file_path"],
            "action": row["action"],
            "new_content": row["new_content"],
        }


# Singleton instance
db = MoltGitDatabase()
