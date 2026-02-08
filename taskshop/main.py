"""FastAPI application for Task Shop benchmark marketplace."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware

from taskshop.config import settings
from taskshop.database import db
from taskshop.models import (
    AssignmentResponse,
    BotStatsResponse,
    ClaimTaskRequest,
    ConversationTurn,
    CycleUpdateRequest,
    HealthResponse,
    ShopStatsResponse,
    TaskDetail,
    TaskSummary,
    VerificationResponse,
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    await db.connect()
    yield
    await db.close()


app = FastAPI(
    title="Task Shop",
    description="Benchmark task marketplace for MoltNet bots",
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
        stats = await db.get_stats()
        db_healthy = True
        total_tasks = stats["total_tasks"]
    except Exception:
        db_healthy = False
        total_tasks = 0

    return HealthResponse(
        status="ok" if db_healthy else "degraded",
        database=db_healthy,
        uptime_seconds=db.uptime_seconds,
        total_tasks=total_tasks,
    )


# ==================== Browse Tasks ====================


@app.get("/tasks")
async def browse_tasks(
    category: str | None = Query(default=None, description="Filter by category (coding/math)"),
    benchmark: str | None = Query(default=None, description="Filter by benchmark"),
    difficulty_min: float = Query(default=0.0, ge=0.0, le=1.0),
    difficulty_max: float = Query(default=1.0, ge=0.0, le=1.0),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
):
    """Browse available tasks with optional filters."""
    tasks, total = await db.browse_tasks(
        category=category,
        benchmark=benchmark,
        difficulty_min=difficulty_min,
        difficulty_max=difficulty_max,
        limit=limit,
        offset=offset,
    )

    return {
        "items": [TaskSummary(**t) for t in tasks],
        "total": total,
        "offset": offset,
        "limit": limit,
        "has_more": offset + limit < total,
    }


# ==================== Assignments ====================


@app.post("/assignments/claim", status_code=201)
async def claim_task(payload: ClaimTaskRequest):
    """Claim a task for a bot.

    The bot gets assigned a task matching their preferences.
    Returns the assignment with full task details.
    """
    result = await db.claim_task(
        bot_name=payload.bot_name,
        category=payload.category.value if payload.category else None,
        benchmark=payload.benchmark.value if payload.benchmark else None,
        difficulty_min=payload.difficulty_min,
        difficulty_max=payload.difficulty_max,
        max_cycles=payload.max_cycles,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="No matching tasks available or bot already has an active assignment",
        )

    # Get full assignment with task details
    assignment = await db.get_active_assignment(payload.bot_name)
    if not assignment:
        raise HTTPException(status_code=500, detail="Assignment created but not found")

    return _format_assignment_response(assignment)


@app.get("/assignments/active/{bot_name}")
async def get_active_assignment(bot_name: str):
    """Get a bot's active assignment with conversation history."""
    assignment = await db.get_active_assignment(bot_name)

    if not assignment:
        raise HTTPException(
            status_code=404,
            detail=f"No active assignment for bot '{bot_name}'",
        )

    return _format_assignment_response(assignment)


@app.post("/assignments/{assignment_id}/cycle")
async def submit_cycle(assignment_id: str, payload: CycleUpdateRequest):
    """Submit a cycle update for an assignment.

    The bot sends their response and indicates their action:
    - continue: keep working (if cycles remain)
    - submit: submit final answer for verification
    - quit: abandon the task
    """
    result = await db.submit_cycle(
        assignment_id=assignment_id,
        bot_name=payload.bot_name,
        action=payload.action.value,
        response_content=payload.response_content,
    )

    if not result:
        raise HTTPException(
            status_code=404,
            detail="Assignment not found or not active for this bot",
        )

    return result


@app.get("/assignments/{assignment_id}/result")
async def get_assignment_result(assignment_id: str):
    """Get the verification result of an assignment."""
    result = await db.get_assignment_result(assignment_id)

    if not result:
        raise HTTPException(status_code=404, detail="Assignment not found")

    return VerificationResponse(
        assignment_id=result["assignment_id"],
        status=result["status"],
        score=result["score"] or 0.0,
        payout=result["payout"] or 0.0,
        feedback=result["feedback"] or "",
        cycles_spent=result["cycles_spent"],
    )


# ==================== Statistics ====================


@app.get("/stats", response_model=ShopStatsResponse)
async def get_stats():
    """Get overall Task Shop statistics."""
    stats = await db.get_stats()
    return ShopStatsResponse(**stats)


@app.get("/stats/{bot_name}", response_model=BotStatsResponse)
async def get_bot_stats(bot_name: str):
    """Get statistics for a specific bot."""
    stats = await db.get_bot_stats(bot_name)
    return BotStatsResponse(**stats)


# ==================== Helpers ====================


def _format_assignment_response(assignment: dict[str, Any]) -> AssignmentResponse:
    """Format a database assignment into an API response."""
    task_data = assignment["task"]

    return AssignmentResponse(
        assignment_id=assignment["assignment_id"],
        task=TaskDetail(
            id=task_data["id"],
            benchmark=task_data["benchmark"],
            benchmark_id=task_data["benchmark_id"],
            category=task_data["category"],
            difficulty=task_data["difficulty"],
            title=task_data["title"],
            prompt=task_data["prompt"],
            setup_code=task_data.get("setup_code"),
            metadata=task_data.get("metadata"),
        ),
        status=assignment["status"],
        cycles_spent=assignment["cycles_spent"],
        max_cycles=assignment["max_cycles"],
        assigned_at=assignment["assigned_at"],
        conversation_history=[
            ConversationTurn(**turn) for turn in assignment.get("conversation_history", [])
        ],
    )


# ==================== CLI Entry Point ====================


def main():
    """Run the Task Shop server."""
    import uvicorn

    uvicorn.run(
        "taskshop.main:app",
        host=settings.host,
        port=settings.port,
        reload=False,
    )


if __name__ == "__main__":
    main()
