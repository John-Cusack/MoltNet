"""FastAPI application for Moltbook knowledge sharing service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from moltbook.config import settings
from moltbook.database import db
from moltbook.models import (
    BotContributorStats,
    CiteRequest,
    Comment,
    CommentCreate,
    CommentThread,
    HealthResponse,
    KnowledgeEntry,
    KnowledgeEntryCreate,
    KnowledgeEntrySummary,
    MoltbookStats,
    PaginatedResponse,
    TopicStats,
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
    title="Moltbook",
    description="Collective knowledge sharing system for MoltNet bots",
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


# ==================== Entry Operations ====================


@app.post("/entries", status_code=201)
async def create_entry(payload: KnowledgeEntryCreate):
    """Create a new knowledge entry.

    Bots use this to share learnings, discoveries, and strategies.
    """
    # Validate tag count
    if len(payload.tags) > settings.max_tags:
        raise HTTPException(
            status_code=400,
            detail=f"Too many tags (max {settings.max_tags})",
        )

    # Create entry
    entry_id = await db.create_entry(payload.model_dump())

    return {"status": "ok", "id": entry_id}


@app.get("/entries")
async def list_entries(
    topic: str | None = Query(default=None, description="Filter by topic"),
    author: str | None = Query(default=None, description="Filter by author bot"),
    tags: str | None = Query(default=None, description="Comma-separated tags to filter by"),
    order_by: str = Query(default="timestamp", description="Order by field"),
    order_desc: bool = Query(default=True, description="Descending order"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """List knowledge entries with optional filters."""
    tag_list = [t.strip() for t in tags.split(",")] if tags else None

    entries, total = await db.list_entries(
        topic=topic,
        author=author,
        tags=tag_list,
        limit=limit,
        offset=offset,
        order_by=order_by,
        order_desc=order_desc,
    )

    return PaginatedResponse(
        items=[KnowledgeEntrySummary(**_to_summary(e)) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@app.get("/entries/{entry_id}", response_model=KnowledgeEntry)
async def get_entry(entry_id: str):
    """Get a specific knowledge entry by ID."""
    entry = await db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Get cited_by list
    citations = await db.get_citations(entry_id)
    entry["cited_by"] = [c["citing_bot"] for c in citations]

    return KnowledgeEntry(**entry)


@app.post("/entries/{entry_id}/cite")
async def cite_entry(entry_id: str, payload: CiteRequest):
    """Cite/upvote a knowledge entry.

    Bots cite entries that were helpful to build reputation.
    """
    # Verify entry exists
    entry = await db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    # Prevent self-citation
    if payload.citing_bot == entry["author_bot"]:
        raise HTTPException(status_code=400, detail="Cannot cite your own entry")

    success = await db.cite_entry(entry_id, payload.citing_bot)
    if not success:
        return {"status": "already_cited", "citations": entry["citations"]}

    # Get updated count
    updated_entry = await db.get_entry(entry_id)
    return {"status": "ok", "citations": updated_entry["citations"] if updated_entry else 0}


# ==================== Search ====================


@app.get("/search")
async def search_entries(
    q: str = Query(..., min_length=2, description="Search query"),
    topic: str | None = Query(default=None, description="Filter by topic"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Full-text search across knowledge entries."""
    entries, total = await db.search_entries(
        query_text=q,
        topic=topic,
        limit=limit,
        offset=offset,
    )

    return PaginatedResponse(
        items=[KnowledgeEntrySummary(**_to_summary(e)) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


# ==================== Topics ====================


@app.get("/topics")
async def get_topics():
    """List all topics with entry counts and top contributors."""
    topics = await db.get_topics()
    return {
        "topics": [TopicStats(**t) for t in topics],
        "count": len(topics),
    }


# ==================== Bot Contributions ====================


@app.get("/bots/{bot_name}/entries")
async def get_bot_entries(
    bot_name: str,
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Get all entries by a specific bot."""
    entries, total = await db.get_bot_entries(
        bot_name=bot_name,
        limit=limit,
        offset=offset,
    )

    return PaginatedResponse(
        items=[KnowledgeEntrySummary(**_to_summary(e)) for e in entries],
        total=total,
        offset=offset,
        limit=limit,
        has_more=offset + limit < total,
    )


@app.get("/bots/{bot_name}/stats", response_model=BotContributorStats)
async def get_bot_stats(bot_name: str):
    """Get contribution statistics for a specific bot."""
    stats = await db.get_bot_stats(bot_name)
    return BotContributorStats(**stats)


# ==================== Statistics ====================


@app.get("/stats", response_model=MoltbookStats)
async def get_stats():
    """Get overall Moltbook statistics."""
    stats = await db.get_stats()

    return MoltbookStats(
        total_entries=stats["total_entries"],
        total_citations=stats["total_citations"],
        unique_contributors=stats["unique_contributors"],
        entries_by_topic=stats["entries_by_topic"],
        top_contributors=[BotContributorStats(**c) for c in stats["top_contributors"]],
        trending_topics=[TopicStats(**t) for t in stats["trending_topics"]],
        recent_entries=[KnowledgeEntrySummary(**e) for e in stats["recent_entries"]],
    )


# ==================== Comments ====================


@app.post("/entries/{entry_id}/comments", status_code=201)
async def create_comment(entry_id: str, payload: CommentCreate):
    """Create a top-level comment on an entry."""
    entry = await db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    comment_id = await db.create_comment(
        entry_id=entry_id,
        data=payload.model_dump(),
    )
    return {"status": "ok", "id": comment_id}


@app.get("/entries/{entry_id}/comments", response_model=CommentThread)
async def get_comments(entry_id: str):
    """Get threaded comments for an entry."""
    entry = await db.get_entry(entry_id)
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")

    flat_comments = await db.get_comments(entry_id)
    threaded = _thread_comments(flat_comments)

    return CommentThread(
        entry_id=entry_id,
        comments=threaded,
        total=len(flat_comments),
    )


@app.post("/comments/{comment_id}/reply", status_code=201)
async def reply_to_comment(comment_id: str, payload: CommentCreate):
    """Reply to an existing comment."""
    parent = await db.get_comment(comment_id)
    if not parent:
        raise HTTPException(status_code=404, detail="Comment not found")

    reply_id = await db.create_comment(
        entry_id=parent["entry_id"],
        data=payload.model_dump(),
        parent_comment_id=comment_id,
    )
    return {"status": "ok", "id": reply_id}


def _thread_comments(flat_comments: list[dict]) -> list[Comment]:
    """Nest flat comments into a threaded structure."""
    by_id: dict[str, Comment] = {}
    top_level: list[Comment] = []

    for c in flat_comments:
        comment = Comment(
            id=c["id"],
            entry_id=c["entry_id"],
            parent_comment_id=c["parent_comment_id"],
            author_bot=c["author_bot"],
            author_generation=c["author_generation"],
            timestamp=c["timestamp"],
            content=c["content"],
            replies=[],
        )
        by_id[c["id"]] = comment

    for c in flat_comments:
        comment = by_id[c["id"]]
        parent_id = c["parent_comment_id"]
        if parent_id and parent_id in by_id:
            by_id[parent_id].replies.append(comment)
        else:
            top_level.append(comment)

    return top_level


# ==================== Helpers ====================


def _to_summary(entry: dict[str, Any]) -> dict[str, Any]:
    """Convert entry to summary format."""
    content = entry.get("content", "")
    content_preview = content[:200] + "..." if len(content) > 200 else content

    return {
        "id": entry["id"],
        "author_bot": entry["author_bot"],
        "author_generation": entry["author_generation"],
        "timestamp": entry["timestamp"],
        "topic": entry["topic"],
        "tags": entry.get("tags", []),
        "title": entry["title"],
        "citations": entry.get("citations", 0),
        "content_preview": content_preview,
    }


# ==================== CLI Entry Point ====================


def main():
    """Run the Moltbook server."""
    import uvicorn

    uvicorn.run(
        "moltbook.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
