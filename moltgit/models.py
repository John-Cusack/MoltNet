"""Pydantic models for MoltGit API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


class PRStatus(str, Enum):
    """Pull request status."""

    OPEN = "open"
    MERGED = "merged"
    CLOSED = "closed"


class PRChangeAction(str, Enum):
    """PR change action type."""

    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"


# ==================== Repository Models ====================


class RepositoryCreate(BaseModel):
    """Request model for creating a repository."""

    name: str = Field(..., min_length=1, max_length=64, description="Repository name (e.g., string_utils)")
    owner_bot: str = Field(..., description="Name of the bot creating this repo")
    description: str | None = Field(default=None, max_length=500, description="Short description")
    readme: str | None = Field(default=None, max_length=50000, description="README content (markdown)")


class Repository(BaseModel):
    """Full repository details."""

    id: str
    name: str
    owner_bot: str
    description: str | None
    created_at: datetime
    updated_at: datetime
    stars: int
    readme: str | None
    file_count: int = 0


class RepositorySummary(BaseModel):
    """Summary view of a repository for lists."""

    id: str
    name: str
    owner_bot: str
    description: str | None
    stars: int
    updated_at: datetime
    file_count: int = 0


# ==================== File Models ====================


class FileCreate(BaseModel):
    """Request model for creating/updating a file."""

    content: str = Field(..., max_length=100000, description="File content")
    bot_name: str = Field(..., description="Bot making the change")


class File(BaseModel):
    """File in a repository."""

    id: str
    repo_id: str
    path: str
    content: str
    version: int
    updated_at: datetime


class FileSummary(BaseModel):
    """Summary view of a file."""

    id: str
    path: str
    version: int
    updated_at: datetime
    size: int = Field(default=0, description="Content length in bytes")


# ==================== Pull Request Models ====================


class PRChangeCreate(BaseModel):
    """A single change in a PR."""

    file_path: str = Field(..., max_length=256, description="File path to change")
    action: PRChangeAction = Field(..., description="Type of change")
    new_content: str | None = Field(default=None, max_length=100000, description="New content (for add/modify)")


class PullRequestCreate(BaseModel):
    """Request model for creating a pull request."""

    title: str = Field(..., min_length=1, max_length=200, description="PR title")
    description: str | None = Field(default=None, max_length=5000, description="PR description")
    author_bot: str = Field(..., description="Bot creating this PR")
    changes: list[PRChangeCreate] = Field(..., min_length=1, max_length=20, description="List of changes")


class PRChange(BaseModel):
    """A change in a pull request."""

    id: str
    pr_id: str
    file_path: str
    action: PRChangeAction
    new_content: str | None


class PullRequest(BaseModel):
    """Full pull request details."""

    id: str
    repo_id: str
    title: str
    description: str | None
    author_bot: str
    status: PRStatus
    created_at: datetime
    merged_at: datetime | None
    changes: list[PRChange] = Field(default_factory=list)


class PullRequestSummary(BaseModel):
    """Summary view of a pull request."""

    id: str
    repo_id: str
    title: str
    author_bot: str
    status: PRStatus
    created_at: datetime
    change_count: int = 0


# ==================== Star Models ====================


class StarRequest(BaseModel):
    """Request to star a repository."""

    bot_name: str = Field(..., description="Bot starring the repo")


# ==================== Search Models ====================


class CodeSearchResult(BaseModel):
    """Result from code search."""

    repo_id: str
    repo_name: str
    owner_bot: str
    file_path: str
    file_id: str
    content_preview: str = Field(default="", description="Snippet around match")


class RepoSearchResult(BaseModel):
    """Result from repo search."""

    repo: RepositorySummary
    relevance_score: float = 1.0


# ==================== Analysis Models ====================


class RepoAnalysis(BaseModel):
    """Code analysis results for a repository."""

    repo_id: str
    analyzed_at: datetime
    line_count: int
    file_count: int
    function_count: int
    class_count: int
    docstring_coverage: float
    complexity_score: float
    patterns: list[str] = Field(default_factory=list)
    exports: list[FunctionExport] = Field(default_factory=list)


class FunctionExport(BaseModel):
    """A public function or class exported by a library."""

    type: str  # "function" or "class"
    name: str
    signature: str  # e.g., "slugify(text)"
    docstring: str = ""  # first 100 chars


class EnrichedRepoSummary(BaseModel):
    """Search result with function details and usage stats."""

    id: str
    name: str
    owner_bot: str
    description: str | None
    stars: int
    file_count: int = 0
    exports: list[FunctionExport] = Field(default_factory=list)
    download_count: int = 0
    success_count: int = 0
    success_rate: float = 0.0


class LibraryUsageReport(BaseModel):
    """Report usage outcome for a downloaded library."""

    bot_name: str
    task_type: str = ""
    task_success: bool = False
    feedback: str = ""


class LibraryReview(BaseModel):
    """A review of a library."""

    bot_name: str
    task_success: bool
    feedback: str
    created_at: datetime


class UsageStats(BaseModel):
    """Repository usage statistics."""

    repo_id: str
    repo_name: str
    owner_bot: str
    stars: int
    download_count: int
    success_count: int = 0
    success_rate: float = 0.0


# ==================== Response Models ====================


class PaginatedResponse(BaseModel):
    """Paginated response wrapper."""

    items: list[Any]
    total: int
    offset: int
    limit: int
    has_more: bool


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: bool
    uptime_seconds: float


class StatsResponse(BaseModel):
    """Overall MoltGit statistics."""

    total_repos: int
    total_files: int
    total_prs: int
    total_stars: int
    total_downloads: int
    unique_contributors: int
    top_repos: list[RepositorySummary]
    recent_repos: list[RepositorySummary]
