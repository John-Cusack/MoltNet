"""FastAPI application for MoltNet Analyzer service."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from analyzer.config import settings
from analyzer.database import analyzer_db
from analyzer.models import (
    BotDetail,
    BotList,
    BotSummary,
    ConversationDetail,
    ConversationList,
    ConversationSearchResult,
    ConversationSummary,
    EventList,
    FamilyTreeData,
    FamilyTreeEdge,
    FamilyTreeNode,
    HealthResponse,
    LifecycleEvent,
    MetricsData,
    ModelComparison,
    ReflectionEntry,
    ReflectionList,
    RunInfo,
    RunList,
    RunStats,
    TimelineData,
    TimelineEntry,
)
from analyzer.run_manager import get_run_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    # Startup
    await analyzer_db.connect()
    yield
    # Shutdown
    await analyzer_db.close()


app = FastAPI(
    title="MoltNet Analyzer",
    description="Conversation analysis and visualization service for MoltNet colonies",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Frontend static files
FRONTEND_DIR = Path(__file__).parent / "frontend"
if FRONTEND_DIR.exists():
    app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


# ==================== Dashboard Routes ====================


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the analyzer dashboard."""
    index_path = FRONTEND_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>MoltNet Analyzer</h1><p>Dashboard not found. API available at /docs</p>")
    return FileResponse(index_path)


# ==================== Health & Status ====================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        runs = await analyzer_db.get_runs(limit=1)
        db_healthy = True
    except Exception:
        db_healthy = False

    return HealthResponse(
        status="ok" if db_healthy else "degraded",
        database=db_healthy,
    )


# ==================== Run Endpoints ====================


@app.get("/api/runs", response_model=RunList)
async def list_runs(limit: int = Query(default=50, ge=1, le=200)):
    """List all runs.

    Returns both active (in runs directory) and completed (in database) runs.
    """
    # Get runs from database
    db_runs = await analyzer_db.get_runs(limit=limit)

    # Get active runs from run manager
    active_runs = get_run_manager().list_runs()

    # Merge, preferring database info
    runs_map = {}
    for run in db_runs:
        runs_map[run["run_id"]] = RunInfo(
            run_id=run["run_id"],
            started_at=run.get("started_at"),
            ended_at=run.get("ended_at"),
            status="completed" if run.get("ended_at") else "unknown",
            total_bots=run.get("total_bots", 0),
            total_cycles=run.get("total_cycles", 0),
        )

    for run in active_runs:
        if run["run_id"] not in runs_map:
            runs_map[run["run_id"]] = RunInfo(
                run_id=run["run_id"],
                started_at=run.get("started_at"),
                ended_at=run.get("ended_at"),
                status=run.get("status", "unknown"),
                conversation_count=run.get("conversation_count"),
            )

    runs_list = sorted(runs_map.values(), key=lambda r: r.started_at or 0, reverse=True)

    return RunList(runs=runs_list[:limit], count=len(runs_list))


@app.post("/api/runs/import")
async def import_run(run_path: str = Query(..., description="Path to run directory")):
    """Import a run's logs into the analyzer database.

    This parses JSONL telemetry logs and populates bot_summaries
    with lifecycle data (births, deaths, replications, cycles).
    """
    from analyzer.log_importer import import_run_logs

    run_dir = Path(run_path)
    if not run_dir.exists():
        # Try relative to common locations
        for base in [Path("."), Path("runs"), settings.data_dir / "runs"]:
            candidate = base / run_path
            if candidate.exists():
                run_dir = candidate
                break

    if not run_dir.exists():
        raise HTTPException(status_code=404, detail=f"Run directory not found: {run_path}")

    logs_dir = run_dir / "logs"
    if not logs_dir.exists():
        raise HTTPException(status_code=404, detail=f"Logs directory not found: {logs_dir}")

    run_id = run_dir.name
    db_path = settings.combined_db_path

    try:
        result = import_run_logs(run_id, logs_dir, db_path)
        return {"status": "success", **result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/runs/import-all")
async def import_all_runs():
    """Import all runs from the runs directory."""
    from analyzer.log_importer import import_run_logs

    runs_dir = settings.data_dir / "runs"
    if not runs_dir.exists():
        raise HTTPException(status_code=404, detail=f"Runs directory not found: {runs_dir}")

    results = []
    for run_dir in runs_dir.iterdir():
        if run_dir.is_dir():
            logs_dir = run_dir / "logs"
            if logs_dir.exists():
                try:
                    result = import_run_logs(run_dir.name, logs_dir, settings.combined_db_path)
                    results.append(result)
                except Exception as e:
                    results.append({"run_id": run_dir.name, "error": str(e)})

    return {"status": "success", "runs_imported": len(results), "results": results}


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str):
    """Get details for a specific run."""
    # Try database first
    run = await analyzer_db.get_run(run_id)
    if run:
        stats = await analyzer_db.get_conversation_stats(run_id)
        return {
            "run": run,
            "stats": stats,
            "source": "database",
        }

    # Try active runs
    run_info = get_run_manager().get_run_info(run_id)
    if run_info:
        return {
            "run": run_info,
            "source": "active",
        }

    raise HTTPException(status_code=404, detail=f"Run not found: {run_id}")


@app.get("/api/runs/{run_id}/stats", response_model=RunStats)
async def get_run_stats(run_id: str):
    """Get statistics for a run."""
    stats = await analyzer_db.get_conversation_stats(run_id)
    if not stats or stats.get("total_conversations", 0) == 0:
        raise HTTPException(status_code=404, detail=f"No data for run: {run_id}")

    return RunStats(
        run_id=run_id,
        total_conversations=stats.get("total_conversations", 0),
        bots_with_conversations=stats.get("bots_with_conversations", 0),
        task_conversations=stats.get("task_conversations", 0),
        reflection_conversations=stats.get("reflection_conversations", 0),
        moltbook_queries=stats.get("moltbook_queries", 0),
        total_input_tokens=stats.get("total_input_tokens", 0),
        total_output_tokens=stats.get("total_output_tokens", 0),
        total_cost=stats.get("total_cost", 0),
        avg_latency_ms=stats.get("avg_latency_ms", 0),
    )


@app.get("/api/runs/{run_id}/timeline", response_model=TimelineData)
async def get_run_timeline(run_id: str):
    """Get timeline data for Gantt visualization."""
    data = await analyzer_db.get_timeline_data(run_id)

    entries = [
        TimelineEntry(
            bot_name=d["bot_name"],
            generation=d.get("generation"),
            model=d.get("model"),
            parent_name=d.get("parent_name"),
            birth_time=d.get("birth_time"),
            death_time=d.get("death_time"),
            death_cause=d.get("death_cause"),
            cycles_lived=d.get("cycles_lived"),
            success_rate=d.get("success_rate"),
            children_spawned=d.get("children_spawned"),
        )
        for d in data
    ]

    start_time = min((e.birth_time for e in entries if e.birth_time), default=None)
    end_time = max((e.death_time or e.birth_time for e in entries if e.birth_time), default=None)

    return TimelineData(
        run_id=run_id,
        entries=entries,
        start_time=start_time,
        end_time=end_time,
    )


@app.get("/api/runs/{run_id}/family-tree", response_model=FamilyTreeData)
async def get_family_tree(run_id: str):
    """Get family tree data for genealogy visualization."""
    data = await analyzer_db.get_family_tree_data(run_id)

    nodes = [
        FamilyTreeNode(
            id=n["id"],
            generation=n.get("generation"),
            model=n.get("model"),
            cycles_lived=n.get("cycles_lived"),
            success_rate=n.get("success_rate"),
            children_spawned=n.get("children_spawned"),
            death_cause=n.get("death_cause"),
        )
        for n in data.get("nodes", [])
    ]

    edges = [
        FamilyTreeEdge(source=e["source"], target=e["target"])
        for e in data.get("edges", [])
    ]

    return FamilyTreeData(run_id=run_id, nodes=nodes, edges=edges)


@app.get("/api/runs/{run_id}/metrics", response_model=MetricsData)
async def get_run_metrics(run_id: str):
    """Get aggregated metrics for a run."""
    model_data = await analyzer_db.get_model_comparison(run_id)
    interaction_data = await analyzer_db.get_interaction_type_breakdown(run_id)
    conv_stats = await analyzer_db.get_conversation_stats(run_id)

    model_comparison = [
        ModelComparison(
            model=m.get("model", "unknown"),
            bot_count=m.get("bot_count", 0),
            avg_lifespan=m.get("avg_lifespan"),
            avg_success=m.get("avg_success"),
            offspring_survival=m.get("offspring_survival"),
            total_revenue=m.get("total_revenue"),
            total_cost=m.get("total_cost"),
        )
        for m in model_data
    ]

    return MetricsData(
        run_id=run_id,
        model_comparison=model_comparison,
        interaction_breakdown=interaction_data,
        conversation_stats=conv_stats,
    )


# ==================== Conversation Endpoints ====================


@app.get("/api/conversations", response_model=ConversationList)
async def list_conversations(
    run_id: str | None = Query(default=None),
    interaction_type: str | None = Query(default=None),
    model: str | None = Query(default=None),
    bot_name: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
):
    """List conversations with filters."""
    convs = await analyzer_db.get_conversations(
        run_id=run_id,
        interaction_type=interaction_type,
        model=model,
        bot_name=bot_name,
        limit=limit,
        offset=offset,
    )

    summaries = [
        ConversationSummary(
            id=c["id"],
            run_id=c["run_id"],
            bot_name=c["bot_name"],
            bot_generation=c.get("bot_generation"),
            model=c["model"],
            timestamp=c["timestamp"],
            interaction_type=c["interaction_type"],
            task_id=c.get("task_id"),
            task_type=c.get("task_type"),
            success=None if c.get("success") is None else bool(c["success"]),
            score=c.get("score"),
            input_tokens=c.get("input_tokens", 0),
            output_tokens=c.get("output_tokens", 0),
            cost_usd=c.get("cost_usd", 0),
        )
        for c in convs
    ]

    return ConversationList(conversations=summaries, count=len(summaries))


@app.get("/api/conversations/search", response_model=ConversationSearchResult)
async def search_conversations(
    q: str = Query(..., min_length=2),
    run_id: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Full-text search in conversations."""
    results = await analyzer_db.search_conversations(query=q, run_id=run_id, limit=limit)

    summaries = [
        ConversationSummary(
            id=c["id"],
            run_id=c["run_id"],
            bot_name=c["bot_name"],
            bot_generation=c.get("bot_generation"),
            model=c["model"],
            timestamp=c["timestamp"],
            interaction_type=c["interaction_type"],
            task_id=c.get("task_id"),
            task_type=c.get("task_type"),
            success=None if c.get("success") is None else bool(c["success"]),
            score=c.get("score"),
            input_tokens=c.get("input_tokens", 0),
            output_tokens=c.get("output_tokens", 0),
            cost_usd=c.get("cost_usd", 0),
        )
        for c in results
    ]

    return ConversationSearchResult(query=q, results=summaries, count=len(summaries))


@app.get("/api/conversations/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: str):
    """Get a single conversation with full content."""
    conv = await analyzer_db.get_conversation(conversation_id)
    if not conv:
        raise HTTPException(status_code=404, detail="Conversation not found")

    return ConversationDetail(
        id=conv["id"],
        run_id=conv["run_id"],
        bot_name=conv["bot_name"],
        bot_generation=conv.get("bot_generation"),
        model=conv["model"],
        timestamp=conv["timestamp"],
        interaction_type=conv["interaction_type"],
        task_id=conv.get("task_id"),
        task_type=conv.get("task_type"),
        system_prompt=conv.get("system_prompt"),
        user_prompt=conv["user_prompt"],
        assistant_response=conv.get("assistant_response"),
        input_tokens=conv.get("input_tokens", 0),
        output_tokens=conv.get("output_tokens", 0),
        latency_ms=conv.get("latency_ms", 0),
        cost_usd=conv.get("cost_usd", 0),
        success=None if conv.get("success") is None else bool(conv["success"]),
        score=conv.get("score"),
        thread_id=conv.get("thread_id"),
        turn_number=conv.get("turn_number", 1),
    )


# ==================== Bot Endpoints ====================


@app.get("/api/bots/{run_id}/{bot_name}", response_model=BotDetail)
async def get_bot_details(run_id: str, bot_name: str):
    """Get detailed information for a specific bot."""
    summary_data = await analyzer_db.get_bot_summary(run_id, bot_name)
    if not summary_data:
        # Try to build from conversations
        convs = await analyzer_db.get_bot_conversations(run_id, bot_name, limit=1)
        if not convs:
            raise HTTPException(status_code=404, detail=f"Bot not found: {bot_name}")
        summary_data = {
            "run_id": run_id,
            "bot_name": bot_name,
            "model": convs[0].get("model"),
            "generation": convs[0].get("bot_generation"),
        }

    summary = BotSummary(**summary_data)

    # Get conversations
    convs = await analyzer_db.get_bot_conversations(run_id, bot_name, limit=100)
    conv_summaries = [
        ConversationSummary(
            id=c["id"],
            run_id=c["run_id"],
            bot_name=c["bot_name"],
            bot_generation=c.get("bot_generation"),
            model=c["model"],
            timestamp=c["timestamp"],
            interaction_type=c["interaction_type"],
            task_id=c.get("task_id"),
            task_type=c.get("task_type"),
            success=None if c.get("success") is None else bool(c["success"]),
            score=c.get("score"),
            input_tokens=c.get("input_tokens", 0),
            output_tokens=c.get("output_tokens", 0),
            cost_usd=c.get("cost_usd", 0),
        )
        for c in convs
    ]

    # Get lifecycle events
    events = await analyzer_db.get_lifecycle_events(run_id, bot_name)

    return BotDetail(
        summary=summary,
        conversations=conv_summaries,
        lifecycle_events=events,
    )


@app.get("/api/bots", response_model=BotList)
async def list_bots(run_id: str = Query(...)):
    """List all bots in a run."""
    summaries = await analyzer_db.get_run_summaries(run_id)

    bots = [BotSummary(**s) for s in summaries]
    return BotList(bots=bots, count=len(bots))


# ==================== Reflection Endpoints ====================


@app.get("/api/reflections", response_model=ReflectionList)
async def list_reflections(
    run_id: str | None = Query(default=None),
    reflection_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get reflection conversations.

    Use this to see what bots thought about (outside of tasks).
    """
    convs = await analyzer_db.get_reflection_conversations(
        run_id=run_id,
        reflection_type=reflection_type,
        limit=limit,
    )

    reflections = [
        ReflectionEntry(
            bot_name=c["bot_name"],
            model=c["model"],
            interaction_type=c["interaction_type"],
            user_prompt=c["user_prompt"],
            assistant_response=c.get("assistant_response"),
            timestamp=c["timestamp"],
        )
        for c in convs
    ]

    return ReflectionList(reflections=reflections, count=len(reflections))


@app.get("/api/reflections/death")
async def get_death_reflections(
    run_id: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
):
    """Get all death reflections (bots' final thoughts)."""
    convs = await analyzer_db.get_reflection_conversations(
        run_id=run_id,
        reflection_type="death",
        limit=limit,
    )

    return {
        "reflections": [
            {
                "bot_name": c["bot_name"],
                "model": c["model"],
                "user_prompt": c["user_prompt"],
                "final_thoughts": c.get("assistant_response"),
                "timestamp": c["timestamp"],
            }
            for c in convs
        ],
        "count": len(convs),
    }


# ==================== Model Analysis Endpoints ====================


@app.get("/api/compare")
async def compare_models(
    run_id: str | None = Query(default=None),
):
    """Compare model performance across runs or within a run.

    Example queries this enables:
    - "What did opus 4.5 models talk about when not doing tasks?"
    - "Compare opus vs glm performance"
    """
    model_stats = await analyzer_db.get_model_comparison(run_id)

    return {
        "run_id": run_id,
        "models": model_stats,
        "count": len(model_stats),
    }


@app.get("/api/models/{model}/conversations")
async def get_model_conversations(
    model: str,
    run_id: str | None = Query(default=None),
    exclude_tasks: bool = Query(default=False),
    interaction_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=500),
):
    """Get conversations for a specific model.

    This enables queries like "what did opus talk about when not doing tasks?"
    """
    convs = await analyzer_db.get_model_conversations(
        model=model,
        interaction_type=interaction_type,
        exclude_tasks=exclude_tasks,
        run_id=run_id,
        limit=limit,
    )

    return {
        "model": model,
        "exclude_tasks": exclude_tasks,
        "conversations": [
            {
                "id": c["id"],
                "bot_name": c["bot_name"],
                "interaction_type": c["interaction_type"],
                "user_prompt": c["user_prompt"][:500] + "..." if len(c.get("user_prompt", "")) > 500 else c.get("user_prompt"),
                "assistant_response": c.get("assistant_response", "")[:500] + "..." if len(c.get("assistant_response", "") or "") > 500 else c.get("assistant_response"),
                "timestamp": c["timestamp"],
            }
            for c in convs
        ],
        "count": len(convs),
    }


# ==================== Archive Endpoints ====================


@app.get("/api/archives")
async def list_archives():
    """List all archived runs."""
    archives = get_run_manager().list_archives()
    return {"archives": archives, "count": len(archives)}


@app.get("/api/archives/{filename}")
async def download_archive(filename: str):
    """Download an archive file."""
    archives = get_run_manager().list_archives()
    for archive in archives:
        if archive["filename"] == filename:
            return FileResponse(
                path=archive["path"],
                filename=filename,
                media_type="application/gzip",
            )

    raise HTTPException(status_code=404, detail="Archive not found")


# ==================== Dashboard Config ====================


@app.get("/api/config")
async def get_dashboard_config():
    """Get dashboard configuration."""
    return {
        "poll_interval_ms": settings.poll_interval_ms,
        "reflection_enabled": settings.reflection_enabled,
        "reflection_interval_cycles": settings.reflection_interval_cycles,
    }
