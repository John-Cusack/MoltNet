"""FastAPI application for Observatory telemetry service."""

from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from observatory.config import settings
from observatory.database import db
from observatory.models import (
    BotStatus,
    BrainLeaderboardEntry,
    ColonyStats,
    EventPayload,
    HealthResponse,
    RecentEvent,
    TelemetryPayload,
    TimeSeriesData,
    TimeSeriesPoint,
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
    title="MoltNet Observatory",
    description="Colony telemetry and monitoring service",
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

# Dashboard static files
DASHBOARD_DIR = Path(__file__).parent / "dashboard"
if DASHBOARD_DIR.exists():
    app.mount("/static", StaticFiles(directory=DASHBOARD_DIR), name="static")


# ==================== Dashboard Routes ====================


@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Serve the dashboard HTML."""
    index_path = DASHBOARD_DIR / "index.html"
    if not index_path.exists():
        return HTMLResponse("<h1>Dashboard not found</h1>", status_code=404)
    return FileResponse(index_path)


# ==================== Health & Status ====================


@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    try:
        # Simple database check
        await db.get_colony_stats(since_seconds=60)
        db_healthy = True
    except Exception:
        db_healthy = False

    return HealthResponse(
        status="ok" if db_healthy else "degraded",
        database=db_healthy,
        uptime_seconds=db.uptime_seconds,
    )


# ==================== Telemetry Ingestion ====================


@app.post("/telemetry", status_code=201)
async def ingest_telemetry(payload: TelemetryPayload):
    """Ingest telemetry data from a bot.

    This is the primary endpoint for bots to report their status.
    """
    data = payload.model_dump()
    if data.get("timestamp") is None:
        data["timestamp"] = datetime.now()

    row_id = await db.insert_telemetry(data)
    return {"status": "ok", "id": row_id}


@app.post("/events", status_code=201)
async def ingest_event(payload: EventPayload):
    """Ingest an event.

    Events are used for logging significant occurrences.
    """
    data = payload.model_dump()
    if data.get("timestamp") is None:
        data["timestamp"] = datetime.now()

    row_id = await db.insert_event(data)
    return {"status": "ok", "id": row_id}


# ==================== Colony Status ====================


@app.get("/api/colony/current")
async def get_current_colony(since_seconds: int = Query(default=300, ge=60, le=3600)):
    """Get current status of all active bots.

    Args:
        since_seconds: Only include bots seen within this window
    """
    bots = await db.get_current_bots(since_seconds=since_seconds)

    return {
        "bots": [
            BotStatus(
                bot_name=b["bot_name"],
                last_seen=datetime.fromtimestamp(b["timestamp"]),
                generation=b.get("generation"),
                fitness_score=b.get("fitness_score"),
                wallet_balance=b.get("wallet_balance"),
                cycle_count=b.get("cycle_count"),
                state=b.get("state"),
                brain_primary=b.get("brain_primary"),
                is_active=True,
            )
            for b in bots
        ],
        "count": len(bots),
        "timestamp": datetime.now(),
    }


@app.get("/api/colony/stats", response_model=ColonyStats)
async def get_colony_stats(since_seconds: int = Query(default=3600, ge=60, le=86400)):
    """Get aggregate colony statistics."""
    stats = await db.get_colony_stats(since_seconds=since_seconds)
    return ColonyStats(**stats)


# ==================== Brain Leaderboard ====================


@app.get("/api/brains/leaderboard")
async def get_brain_leaderboard(limit: int = Query(default=10, ge=1, le=100)):
    """Get brain model leaderboard.

    Shows which brain models are performing best across the colony.
    """
    entries = await db.get_brain_leaderboard(limit=limit)
    return {
        "leaderboard": [BrainLeaderboardEntry(**e) for e in entries],
        "timestamp": datetime.now(),
    }


# ==================== Time Series ====================


@app.get("/api/timeseries/{metric}")
async def get_time_series(
    metric: str,
    since_seconds: int = Query(default=3600, ge=60, le=86400),
    bucket_seconds: int = Query(default=60, ge=10, le=3600),
):
    """Get time series data for a metric.

    Valid metrics: fitness_score, wallet_balance, cycle_revenue, cycle_api_spend
    """
    valid_metrics = {"fitness_score", "wallet_balance", "cycle_revenue", "cycle_api_spend"}
    if metric not in valid_metrics:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid metric. Valid options: {', '.join(valid_metrics)}",
        )

    points = await db.get_time_series(
        metric=metric,
        since_seconds=since_seconds,
        bucket_seconds=bucket_seconds,
    )

    return TimeSeriesData(
        metric=metric,
        points=[TimeSeriesPoint(**p) for p in points],
    )


# ==================== Events ====================


@app.get("/api/events/recent")
async def get_recent_events(
    limit: int = Query(default=50, ge=1, le=500),
    event_type: str | None = Query(default=None),
):
    """Get recent events."""
    events = await db.get_recent_events(limit=limit, event_type=event_type)
    return {
        "events": [RecentEvent(**e) for e in events],
        "count": len(events),
        "timestamp": datetime.now(),
    }


# ==================== Bot Details ====================


@app.get("/api/bots/{bot_name}")
async def get_bot_details(
    bot_name: str,
    since_seconds: int = Query(default=3600, ge=60, le=86400),
):
    """Get detailed telemetry history for a specific bot."""
    history = await db.get_bot_history(bot_name=bot_name, since_seconds=since_seconds)

    if not history:
        raise HTTPException(status_code=404, detail=f"Bot not found: {bot_name}")

    # Latest status
    latest = history[0]

    return {
        "bot_name": bot_name,
        "current": BotStatus(
            bot_name=latest["bot_name"],
            last_seen=datetime.fromtimestamp(latest["timestamp"]),
            generation=latest.get("generation"),
            fitness_score=latest.get("fitness_score"),
            wallet_balance=latest.get("wallet_balance"),
            cycle_count=latest.get("cycle_count"),
            state=latest.get("state"),
            brain_primary=latest.get("brain_primary"),
        ),
        "history_count": len(history),
        "history": [
            {
                "timestamp": datetime.fromtimestamp(h["timestamp"]),
                "fitness_score": h.get("fitness_score"),
                "wallet_balance": h.get("wallet_balance"),
                "cycle_count": h.get("cycle_count"),
                "state": h.get("state"),
            }
            for h in history[:100]  # Limit history in response
        ],
    }


# ==================== Maintenance ====================


@app.post("/api/admin/cleanup")
async def cleanup_old_data():
    """Delete old telemetry and event data based on retention settings."""
    tel_deleted, evt_deleted = await db.cleanup_old_data()
    return {
        "status": "ok",
        "telemetry_deleted": tel_deleted,
        "events_deleted": evt_deleted,
        "timestamp": datetime.now(),
    }


# ==================== Dashboard Config ====================


@app.get("/api/config")
async def get_dashboard_config():
    """Get dashboard configuration."""
    return {
        "poll_interval_ms": settings.poll_interval_ms,
        "telemetry_retention_hours": settings.telemetry_retention // 3600,
        "event_retention_days": settings.event_retention // 86400,
    }
