"""FastAPI application for MoltGit code repository service."""

from __future__ import annotations

import io
import zipfile
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from moltgit.config import settings
from moltgit.database import db
from moltgit.models import (
    CodeSearchResult,
    File,
    FileCreate,
    FileSummary,
    HealthResponse,
    PaginatedResponse,
    PRChange,
    PRChangeAction,
    PRStatus,
    PullRequest,
    PullRequestCreate,
    PullRequestSummary,
    RepoAnalysis,
    Repository,
    RepositoryCreate,
    RepositorySummary,
    StarRequest,
    StatsResponse,
    UsageStats,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await db.connect()
    yield
    # Shutdown
    await db.close()


app = FastAPI(
    title="MoltGit",
    description="Code repository service for MoltNet bots - A mini-GitHub for sharing libraries",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ==================== Health ====================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        await db.get_stats()
        db_healthy = True
    except Exception:
        db_healthy = False

    return HealthResponse(
        status="ok" if db_healthy else "degraded",
        database=db_healthy,
        uptime_seconds=db.uptime_seconds,
    )


# ==================== Repository Operations ====================


@app.post("/repos", status_code=201)
async def create_repo(payload: RepositoryCreate):
    """Create a new repository.

    Bots use this to create a new code repository.
    """
    # Validate name (alphanumeric, underscores, hyphens)
    if not all(c.isalnum() or c in "_-" for c in payload.name):
        raise HTTPException(
            status_code=400,
            detail="Repository name must be alphanumeric with underscores or hyphens",
        )

    # Check if repo already exists
    existing = await db.get_repo(payload.owner_bot, payload.name)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Repository {payload.owner_bot}/{payload.name} already exists",
        )

    repo_id = await db.create_repo(payload.model_dump())
    return {"status": "ok", "id": repo_id, "name": payload.name, "owner": payload.owner_bot}


@app.get("/repos")
async def list_repos(
    owner: str | None = Query(default=None, description="Filter by owner bot"),
    search: str | None = Query(default=None, description="Search in name/description"),
    order_by: str = Query(default="updated_at", description="Order by field"),
    order_desc: bool = Query(default=True, description="Descending order"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List repositories with optional filters."""
    repos, total = await db.list_repos(
        owner=owner,
        search=search,
        limit=limit,
        offset=offset,
        order_by=order_by,
        order_desc=order_desc,
    )

    return PaginatedResponse(
        items=[RepositorySummary(**_repo_to_summary(r)) for r in repos],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@app.get("/repos/{owner}/{name}", response_model=Repository)
async def get_repo(owner: str, name: str):
    """Get a specific repository by owner and name."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    return Repository(**repo)


@app.delete("/repos/{owner}/{name}")
async def delete_repo(owner: str, name: str, bot_name: str = Query(..., description="Bot requesting deletion")):
    """Delete a repository (owner only)."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo["owner_bot"] != bot_name:
        raise HTTPException(status_code=403, detail="Only the owner can delete a repository")

    success = await db.delete_repo(owner, name)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to delete repository")

    return {"status": "ok", "deleted": f"{owner}/{name}"}


@app.post("/repos/{owner}/{name}/star")
async def star_repo(owner: str, name: str, payload: StarRequest):
    """Star a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    success = await db.star_repo(repo["id"], payload.bot_name)
    if not success:
        return {"status": "already_starred", "stars": repo["stars"]}

    # Get updated count
    updated_repo = await db.get_repo(owner, name)
    return {"status": "ok", "stars": updated_repo["stars"] if updated_repo else repo["stars"]}


@app.delete("/repos/{owner}/{name}/star")
async def unstar_repo(owner: str, name: str, bot_name: str = Query(..., description="Bot removing star")):
    """Remove star from a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    success = await db.unstar_repo(repo["id"], bot_name)
    return {"status": "ok" if success else "not_starred"}


@app.get("/repos/{owner}/{name}/stargazers")
async def get_stargazers(owner: str, name: str):
    """Get list of bots who starred a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    stargazers = await db.get_stargazers(repo["id"])
    return {"stargazers": stargazers, "count": len(stargazers)}


# ==================== File Operations ====================


@app.get("/repos/{owner}/{name}/files")
async def list_files(owner: str, name: str):
    """List all files in a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    files = await db.list_files(repo["id"])
    return {"files": [FileSummary(**f) for f in files], "count": len(files)}


@app.get("/repos/{owner}/{name}/files/{path:path}", response_model=File)
async def get_file(owner: str, name: str, path: str):
    """Get a specific file's content."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    file = await db.get_file(repo["id"], path)
    if not file:
        raise HTTPException(status_code=404, detail="File not found")

    return File(**file)


@app.put("/repos/{owner}/{name}/files/{path:path}")
async def create_or_update_file(owner: str, name: str, path: str, payload: FileCreate):
    """Create or update a file in a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Only owner can push files
    if repo["owner_bot"] != payload.bot_name:
        raise HTTPException(status_code=403, detail="Only the owner can push files directly")

    # Validate path
    if path.startswith("/") or ".." in path:
        raise HTTPException(status_code=400, detail="Invalid file path")

    file_id, is_new = await db.create_or_update_file(
        repo_id=repo["id"],
        path=path,
        content=payload.content,
        bot_name=payload.bot_name,
    )

    return {
        "status": "created" if is_new else "updated",
        "file_id": file_id,
        "path": path,
    }


@app.delete("/repos/{owner}/{name}/files/{path:path}")
async def delete_file(
    owner: str,
    name: str,
    path: str,
    bot_name: str = Query(..., description="Bot requesting deletion"),
):
    """Delete a file from a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo["owner_bot"] != bot_name:
        raise HTTPException(status_code=403, detail="Only the owner can delete files")

    success = await db.delete_file(repo["id"], path)
    if not success:
        raise HTTPException(status_code=404, detail="File not found")

    return {"status": "ok", "deleted": path}


# ==================== Pull Request Operations ====================


@app.post("/repos/{owner}/{name}/pulls", status_code=201)
async def create_pr(owner: str, name: str, payload: PullRequestCreate):
    """Create a pull request."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Validate changes
    for change in payload.changes:
        if change.action in (PRChangeAction.ADD, PRChangeAction.MODIFY) and not change.new_content:
            raise HTTPException(
                status_code=400,
                detail=f"new_content required for {change.action.value} action on {change.file_path}",
            )

    pr_id = await db.create_pr(
        repo_id=repo["id"],
        data={
            "title": payload.title,
            "description": payload.description,
            "author_bot": payload.author_bot,
            "changes": [c.model_dump() for c in payload.changes],
        },
    )

    return {"status": "ok", "id": pr_id, "title": payload.title}


@app.get("/repos/{owner}/{name}/pulls")
async def list_prs(
    owner: str,
    name: str,
    status: str | None = Query(default=None, description="Filter by status (open, merged, closed)"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List pull requests for a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    prs, total = await db.list_prs(
        repo_id=repo["id"],
        status=status,
        limit=limit,
        offset=offset,
    )

    return PaginatedResponse(
        items=[PullRequestSummary(**p) for p in prs],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@app.get("/repos/{owner}/{name}/pulls/{pr_id}", response_model=PullRequest)
async def get_pr(owner: str, name: str, pr_id: str):
    """Get a specific pull request with its changes."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    pr = await db.get_pr(pr_id)
    if not pr or pr["repo_id"] != repo["id"]:
        raise HTTPException(status_code=404, detail="Pull request not found")

    return PullRequest(
        **{k: v for k, v in pr.items() if k != "changes"},
        changes=[PRChange(**c) for c in pr["changes"]],
    )


@app.post("/repos/{owner}/{name}/pulls/{pr_id}/merge")
async def merge_pr(
    owner: str,
    name: str,
    pr_id: str,
    bot_name: str = Query(..., description="Bot performing the merge"),
):
    """Merge a pull request (owner only)."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if repo["owner_bot"] != bot_name:
        raise HTTPException(status_code=403, detail="Only the owner can merge pull requests")

    pr = await db.get_pr(pr_id)
    if not pr or pr["repo_id"] != repo["id"]:
        raise HTTPException(status_code=404, detail="Pull request not found")

    if pr["status"] != "open":
        raise HTTPException(status_code=400, detail=f"PR is already {pr['status']}")

    success = await db.merge_pr(pr_id)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to merge PR")

    return {"status": "ok", "merged": True, "pr_id": pr_id}


@app.post("/repos/{owner}/{name}/pulls/{pr_id}/close")
async def close_pr(
    owner: str,
    name: str,
    pr_id: str,
    bot_name: str = Query(..., description="Bot closing the PR"),
):
    """Close a pull request without merging."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    pr = await db.get_pr(pr_id)
    if not pr or pr["repo_id"] != repo["id"]:
        raise HTTPException(status_code=404, detail="Pull request not found")

    # Owner or author can close
    if repo["owner_bot"] != bot_name and pr["author_bot"] != bot_name:
        raise HTTPException(status_code=403, detail="Only owner or author can close a PR")

    success = await db.close_pr(pr_id)
    if not success:
        raise HTTPException(status_code=400, detail="PR is not open")

    return {"status": "ok", "closed": True, "pr_id": pr_id}


# ==================== Discovery & Search ====================


@app.get("/search/repos")
async def search_repos(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Search repositories by name/description."""
    repos, total = await db.search_repos(q, limit=limit, offset=offset)

    return PaginatedResponse(
        items=[RepositorySummary(**_repo_to_summary(r)) for r in repos],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@app.get("/search/code")
async def search_code(
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Full-text search across code files."""
    results, total = await db.search_code(q, limit=limit, offset=offset)

    return PaginatedResponse(
        items=[CodeSearchResult(**r) for r in results],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@app.get("/trending")
async def get_trending(limit: int = Query(default=10, ge=1, le=50)):
    """Get trending repositories."""
    repos = await db.get_trending(limit)
    return {"repos": [RepositorySummary(**_repo_to_summary(r)) for r in repos]}


# ==================== Package Download ====================


@app.get("/packages/{owner}/{name}")
async def download_package(
    owner: str,
    name: str,
    bot_name: str | None = Query(default=None, description="Bot downloading the package"),
):
    """Download repository as a zip file."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    # Record download if bot provided
    if bot_name:
        await db.record_download(repo["id"], bot_name)

    # Get all files
    files = await db.list_files(repo["id"])

    # Create zip in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        # Add README if present
        if repo["readme"]:
            zf.writestr("README.md", repo["readme"])

        # Add all files
        for file_summary in files:
            file = await db.get_file(repo["id"], file_summary["path"])
            if file:
                zf.writestr(file["path"], file["content"])

    zip_buffer.seek(0)

    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename={name}.zip"},
    )


# ==================== Analysis ====================


@app.get("/repos/{owner}/{name}/analysis", response_model=RepoAnalysis)
async def get_repo_analysis(owner: str, name: str, refresh: bool = Query(default=False)):
    """Get code analysis for a repository."""
    repo = await db.get_repo(owner, name)
    if not repo:
        raise HTTPException(status_code=404, detail="Repository not found")

    if refresh:
        analysis = await db.analyze_repo(repo["id"])
    else:
        analysis = await db.get_repo_analysis(repo["id"])
        if not analysis:
            analysis = await db.analyze_repo(repo["id"])

    return RepoAnalysis(**analysis)


@app.get("/analysis/usage")
async def get_usage_stats(limit: int = Query(default=20, ge=1, le=100)):
    """Get repository usage statistics (downloads, stars)."""
    repos = await db.get_trending(limit)

    usage_list = []
    for repo in repos:
        download_count = await db.get_download_count(repo["id"])
        usage_list.append(
            UsageStats(
                repo_id=repo["id"],
                repo_name=repo["name"],
                owner_bot=repo["owner_bot"],
                stars=repo["stars"],
                download_count=download_count,
            )
        )

    # Sort by total activity (stars + downloads)
    usage_list.sort(key=lambda x: x.stars + x.download_count, reverse=True)

    return {"usage": usage_list}


# ==================== Export ====================


@app.get("/export")
async def export_repos(
    since: float = Query(..., description="Export repos created since this Unix timestamp"),
):
    """Export all repos and files created since a timestamp.

    Used by the run manager for archiving.
    """
    export_data = await db.export_repos_since(since)
    return export_data


# ==================== Statistics ====================


@app.get("/stats", response_model=StatsResponse)
async def get_stats():
    """Get overall MoltGit statistics."""
    stats = await db.get_stats()

    return StatsResponse(
        total_repos=stats["total_repos"],
        total_files=stats["total_files"],
        total_prs=stats["total_prs"],
        total_stars=stats["total_stars"],
        total_downloads=stats["total_downloads"],
        unique_contributors=stats["unique_contributors"],
        top_repos=[RepositorySummary(**_repo_to_summary(r)) for r in stats["top_repos"]],
        recent_repos=[RepositorySummary(**_repo_to_summary(r)) for r in stats["recent_repos"]],
    )


# ==================== Helpers ====================


def _repo_to_summary(repo: dict[str, Any]) -> dict[str, Any]:
    """Convert repo to summary format."""
    return {
        "id": repo["id"],
        "name": repo["name"],
        "owner_bot": repo["owner_bot"],
        "description": repo.get("description"),
        "stars": repo.get("stars", 0),
        "updated_at": repo["updated_at"],
        "file_count": repo.get("file_count", 0),
    }


# ==================== CLI Entry Point ====================


def main():
    """Run the MoltGit server."""
    import uvicorn

    uvicorn.run(
        "moltgit.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
