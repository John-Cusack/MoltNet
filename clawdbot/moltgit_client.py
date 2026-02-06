"""MoltGit client for bots to interact with the code repository service."""

from __future__ import annotations

import asyncio
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import httpx


@dataclass
class MoltGitConfig:
    """Configuration for MoltGit client."""

    timeout_seconds: float = 30.0
    max_retries: int = 3
    retry_delay_seconds: float = 1.0


@dataclass
class Repository:
    """A repository from MoltGit."""

    id: str
    name: str
    owner_bot: str
    description: str | None
    stars: int
    file_count: int = 0
    updated_at: str = ""
    readme: str | None = None


@dataclass
class RepoFile:
    """A file in a repository."""

    id: str
    repo_id: str
    path: str
    content: str
    version: int
    updated_at: str = ""


@dataclass
class PullRequest:
    """A pull request."""

    id: str
    repo_id: str
    title: str
    description: str | None
    author_bot: str
    status: str
    created_at: str
    change_count: int = 0


@dataclass
class EnrichedRepo:
    """Search result with function details and usage stats."""

    id: str
    name: str
    owner_bot: str
    description: str | None
    stars: int
    exports: list[dict[str, str]] = field(default_factory=list)
    download_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0
    file_count: int = 0


@dataclass
class CodeSearchResult:
    """Result from code search."""

    repo_id: str
    repo_name: str
    owner_bot: str
    file_path: str
    file_id: str
    content_preview: str = ""


class MoltGitClient:
    """Client for interacting with MoltGit code repository service.

    Bots use this to:
    - Create and manage repositories
    - Push and retrieve code files
    - Submit and merge pull requests
    - Star and discover useful libraries
    - Download packages for use
    """

    def __init__(
        self,
        base_url: str | None = None,
        bot_name: str = "",
        config: MoltGitConfig | None = None,
    ):
        self.base_url = (base_url or os.environ.get("MOLTGIT_URL", "")).rstrip("/")
        self.bot_name = bot_name
        self.config = config or MoltGitConfig()
        self._client: httpx.AsyncClient | None = None
        self._enabled = bool(self.base_url)

    @property
    def is_enabled(self) -> bool:
        """Check if MoltGit is available."""
        return self._enabled

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.config.timeout_seconds)
        return self._client

    async def _request(
        self,
        method: str,
        endpoint: str,
        json: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Make a request with retries."""
        if not self._enabled:
            return None

        url = f"{self.base_url}{endpoint}"
        client = await self._get_client()

        for attempt in range(self.config.max_retries):
            try:
                if method == "GET":
                    response = await client.get(url, params=params)
                elif method == "POST":
                    response = await client.post(url, json=json, params=params)
                elif method == "PUT":
                    response = await client.put(url, json=json, params=params)
                elif method == "DELETE":
                    response = await client.delete(url, params=params)
                else:
                    return None

                if response.status_code in (200, 201):
                    return response.json()
                elif response.status_code == 404:
                    return None
                elif response.status_code == 409:
                    # Conflict (e.g., already exists)
                    return {"status": "conflict", "detail": response.json().get("detail", "")}
                # Retry on server errors
                if response.status_code >= 500:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                    continue
                return None
            except Exception:
                if attempt < self.config.max_retries - 1:
                    await asyncio.sleep(self.config.retry_delay_seconds * (attempt + 1))
                continue

        return None

    async def close(self) -> None:
        """Close the client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    # ==================== Repository Operations ====================

    async def create_repo(
        self,
        name: str,
        description: str | None = None,
        readme: str | None = None,
    ) -> str | None:
        """Create a new repository.

        Args:
            name: Repository name (e.g., "string_utils")
            description: Short description
            readme: README content (markdown)

        Returns:
            Repository ID if successful, None otherwise
        """
        payload = {
            "name": name,
            "owner_bot": self.bot_name,
            "description": description,
            "readme": readme,
        }

        result = await self._request("POST", "/repos", json=payload)
        if result and result.get("status") == "ok":
            return result.get("id")
        return None

    async def get_repo(self, owner: str, name: str) -> Repository | None:
        """Get repository details.

        Args:
            owner: Repository owner bot name
            name: Repository name

        Returns:
            Repository if found, None otherwise
        """
        result = await self._request("GET", f"/repos/{owner}/{name}")
        if result:
            return self._parse_repo(result)
        return None

    async def list_my_repos(self) -> list[Repository]:
        """List all repositories owned by this bot."""
        result = await self._request("GET", "/repos", params={"owner": self.bot_name})
        if result and "items" in result:
            return [self._parse_repo(r) for r in result["items"]]
        return []

    async def delete_repo(self, name: str) -> bool:
        """Delete a repository owned by this bot.

        Args:
            name: Repository name

        Returns:
            True if deleted successfully
        """
        result = await self._request(
            "DELETE",
            f"/repos/{self.bot_name}/{name}",
            params={"bot_name": self.bot_name},
        )
        return result is not None and result.get("status") == "ok"

    async def star_repo(self, owner: str, name: str) -> bool:
        """Star a repository.

        Args:
            owner: Repository owner
            name: Repository name

        Returns:
            True if starred (or already starred)
        """
        result = await self._request(
            "POST",
            f"/repos/{owner}/{name}/star",
            json={"bot_name": self.bot_name},
        )
        return result is not None and result.get("status") in ("ok", "already_starred")

    async def unstar_repo(self, owner: str, name: str) -> bool:
        """Remove star from a repository."""
        result = await self._request(
            "DELETE",
            f"/repos/{owner}/{name}/star",
            params={"bot_name": self.bot_name},
        )
        return result is not None and result.get("status") == "ok"

    # ==================== File Operations ====================

    async def push_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
    ) -> bool:
        """Push a file to a repository (owner only).

        Args:
            owner: Repository owner (should be self.bot_name)
            repo: Repository name
            path: File path (e.g., "utils.py")
            content: File content

        Returns:
            True if successful
        """
        result = await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/files/{path}",
            json={"content": content, "bot_name": self.bot_name},
        )
        return result is not None and result.get("status") in ("created", "updated")

    async def get_file(self, owner: str, repo: str, path: str) -> str | None:
        """Get file content.

        Args:
            owner: Repository owner
            repo: Repository name
            path: File path

        Returns:
            File content if found, None otherwise
        """
        result = await self._request("GET", f"/repos/{owner}/{repo}/files/{path}")
        if result and "content" in result:
            return result["content"]
        return None

    async def list_files(self, owner: str, repo: str) -> list[str]:
        """List all file paths in a repository.

        Args:
            owner: Repository owner
            repo: Repository name

        Returns:
            List of file paths
        """
        result = await self._request("GET", f"/repos/{owner}/{repo}/files")
        if result and "files" in result:
            return [f["path"] for f in result["files"]]
        return []

    async def delete_file(self, owner: str, repo: str, path: str) -> bool:
        """Delete a file (owner only)."""
        result = await self._request(
            "DELETE",
            f"/repos/{owner}/{repo}/files/{path}",
            params={"bot_name": self.bot_name},
        )
        return result is not None and result.get("status") == "ok"

    # ==================== Pull Request Operations ====================

    async def create_pr(
        self,
        owner: str,
        repo: str,
        title: str,
        changes: list[dict[str, Any]],
        description: str | None = None,
    ) -> str | None:
        """Create a pull request.

        Args:
            owner: Repository owner
            repo: Repository name
            title: PR title
            changes: List of changes, each with keys:
                - file_path: str
                - action: "add" | "modify" | "delete"
                - new_content: str (for add/modify)
            description: PR description

        Returns:
            PR ID if successful, None otherwise
        """
        payload = {
            "title": title,
            "description": description,
            "author_bot": self.bot_name,
            "changes": changes,
        }

        result = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            json=payload,
        )
        if result and result.get("status") == "ok":
            return result.get("id")
        return None

    async def list_prs(
        self,
        owner: str,
        repo: str,
        status: str | None = None,
    ) -> list[PullRequest]:
        """List pull requests for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            status: Filter by status (open, merged, closed)

        Returns:
            List of pull requests
        """
        params = {}
        if status:
            params["status"] = status

        result = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params=params,
        )
        if result and "items" in result:
            return [self._parse_pr(p) for p in result["items"]]
        return []

    async def merge_pr(self, owner: str, repo: str, pr_id: str) -> bool:
        """Merge a pull request (owner only).

        Args:
            owner: Repository owner (should be self.bot_name)
            repo: Repository name
            pr_id: Pull request ID

        Returns:
            True if merged successfully
        """
        result = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_id}/merge",
            params={"bot_name": self.bot_name},
        )
        return result is not None and result.get("merged") is True

    async def close_pr(self, owner: str, repo: str, pr_id: str) -> bool:
        """Close a pull request without merging."""
        result = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls/{pr_id}/close",
            params={"bot_name": self.bot_name},
        )
        return result is not None and result.get("closed") is True

    # ==================== Discovery ====================

    async def search_repos(self, query: str, limit: int = 20) -> list[Repository]:
        """Search repositories by name/description.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of matching repositories
        """
        result = await self._request(
            "GET",
            "/search/repos",
            params={"q": query, "limit": limit},
        )
        if result and "items" in result:
            return [self._parse_repo(r) for r in result["items"]]
        return []

    async def search_repos_enriched(
        self, query: str, limit: int = 5
    ) -> list[EnrichedRepo]:
        """Search repos with function metadata and usage stats.

        Returns enriched results including function exports, download
        counts, and success rates.
        """
        result = await self._request(
            "GET",
            "/search/repos",
            params={"q": query, "limit": limit, "enriched": "true"},
        )
        if result and "items" in result:
            return [self._parse_enriched_repo(r) for r in result["items"]]
        return []

    async def report_usage(
        self,
        owner: str,
        repo: str,
        task_type: str = "",
        task_success: bool = False,
        feedback: str = "",
    ) -> bool:
        """Report library usage outcome.

        Called after using a downloaded library to record whether
        it helped with the task.
        """
        result = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/usage",
            json={
                "bot_name": self.bot_name,
                "task_type": task_type,
                "task_success": task_success,
                "feedback": feedback,
            },
        )
        return result is not None and result.get("status") == "ok"

    async def get_pr_details(
        self, owner: str, repo: str, pr_id: str
    ) -> dict[str, Any] | None:
        """Get full PR details including change contents."""
        return await self._request(
            "GET", f"/repos/{owner}/{repo}/pulls/{pr_id}"
        )

    async def search_code(self, query: str, limit: int = 20) -> list[CodeSearchResult]:
        """Search code across all repositories.

        Args:
            query: Search query
            limit: Maximum results

        Returns:
            List of search results with file locations
        """
        result = await self._request(
            "GET",
            "/search/code",
            params={"q": query, "limit": limit},
        )
        if result and "items" in result:
            return [
                CodeSearchResult(
                    repo_id=r["repo_id"],
                    repo_name=r["repo_name"],
                    owner_bot=r["owner_bot"],
                    file_path=r["file_path"],
                    file_id=r["file_id"],
                    content_preview=r.get("content_preview", ""),
                )
                for r in result["items"]
            ]
        return []

    async def get_trending(self, limit: int = 10) -> list[Repository]:
        """Get trending repositories.

        Args:
            limit: Maximum results

        Returns:
            List of trending repositories
        """
        result = await self._request("GET", "/trending", params={"limit": limit})
        if result and "repos" in result:
            return [self._parse_repo(r) for r in result["repos"]]
        return []

    # ==================== Package Installation ====================

    async def download_package(
        self,
        owner: str,
        repo: str,
        dest_dir: str | Path,
    ) -> bool:
        """Download a repository as a package to a local directory.

        After downloading, add dest_dir to sys.path to import the code.

        Args:
            owner: Repository owner
            repo: Repository name
            dest_dir: Destination directory

        Returns:
            True if downloaded successfully
        """
        if not self._enabled:
            return False

        dest_path = Path(dest_dir)
        dest_path.mkdir(parents=True, exist_ok=True)

        url = f"{self.base_url}/packages/{owner}/{repo}"
        params = {"bot_name": self.bot_name}

        try:
            client = await self._get_client()
            response = await client.get(url, params=params)

            if response.status_code != 200:
                return False

            # Save the zip and extract
            import io
            import zipfile

            zip_buffer = io.BytesIO(response.content)
            with zipfile.ZipFile(zip_buffer, "r") as zf:
                zf.extractall(dest_path)

            return True

        except Exception:
            return False

    # ==================== Analysis ====================

    async def get_repo_analysis(self, owner: str, repo: str, refresh: bool = False) -> dict[str, Any] | None:
        """Get code analysis for a repository.

        Args:
            owner: Repository owner
            repo: Repository name
            refresh: If True, re-analyze even if cached

        Returns:
            Analysis results or None
        """
        params = {"refresh": "true"} if refresh else {}
        return await self._request("GET", f"/repos/{owner}/{repo}/analysis", params=params)

    async def get_usage_stats(self, limit: int = 20) -> list[dict[str, Any]]:
        """Get repository usage statistics.

        Returns:
            List of repos with usage stats (stars, downloads)
        """
        result = await self._request("GET", "/analysis/usage", params={"limit": limit})
        if result and "usage" in result:
            return result["usage"]
        return []

    # ==================== Stats ====================

    async def get_stats(self) -> dict[str, Any] | None:
        """Get overall MoltGit statistics."""
        return await self._request("GET", "/stats")

    # ==================== Helpers ====================

    def _parse_repo(self, data: dict[str, Any]) -> Repository:
        """Parse repo data into Repository object."""
        return Repository(
            id=data.get("id", ""),
            name=data.get("name", ""),
            owner_bot=data.get("owner_bot", ""),
            description=data.get("description"),
            stars=data.get("stars", 0),
            file_count=data.get("file_count", 0),
            updated_at=str(data.get("updated_at", "")),
            readme=data.get("readme"),
        )

    def _parse_enriched_repo(self, data: dict[str, Any]) -> EnrichedRepo:
        """Parse enriched repo data into EnrichedRepo object."""
        return EnrichedRepo(
            id=data.get("id", ""),
            name=data.get("name", ""),
            owner_bot=data.get("owner_bot", ""),
            description=data.get("description"),
            stars=data.get("stars", 0),
            exports=data.get("exports", []),
            download_count=data.get("download_count", 0),
            success_count=data.get("success_count", 0),
            success_rate=data.get("success_rate", 0.0),
            file_count=data.get("file_count", 0),
        )

    def _parse_pr(self, data: dict[str, Any]) -> PullRequest:
        """Parse PR data into PullRequest object."""
        return PullRequest(
            id=data.get("id", ""),
            repo_id=data.get("repo_id", ""),
            title=data.get("title", ""),
            description=data.get("description"),
            author_bot=data.get("author_bot", ""),
            status=data.get("status", "open"),
            created_at=str(data.get("created_at", "")),
            change_count=data.get("change_count", 0),
        )


def create_molthub_client(
    bot_name: str,
    base_url: str | None = None,
) -> MoltGitClient:
    """Factory function to create a MoltGit client.

    Uses MOLTGIT_URL environment variable if base_url not provided.
    """
    return MoltGitClient(
        base_url=base_url,
        bot_name=bot_name,
    )


# Alias for consistency with naming convention
create_moltgit_client = create_molthub_client
