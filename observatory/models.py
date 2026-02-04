"""Pydantic models for Observatory API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class TelemetryPayload(BaseModel):
    """Telemetry data from a bot."""

    bot_name: str = Field(..., description="Unique bot identifier")
    timestamp: datetime | None = Field(default=None, description="Event timestamp")
    generation: int | None = Field(default=None, description="Bot generation number")
    fitness_score: float | None = Field(default=None, ge=0.0, le=1.0)
    wallet_balance: float | None = Field(default=None, description="Current wallet balance USD")
    cycle_count: int | None = Field(default=None, ge=0)
    state: str | None = Field(default=None, description="Current bot state")
    brain_primary: str | None = Field(default=None, description="Primary brain model in use")
    cycle_revenue: float | None = Field(default=None, description="Revenue this cycle")
    cycle_api_spend: float | None = Field(default=None, description="API spend this cycle")
    tasks_completed: int | None = Field(default=None, ge=0)
    tasks_failed: int | None = Field(default=None, ge=0)
    genome_hash: str | None = Field(default=None, description="Hash of current genome")
    parent_name: str | None = Field(default=None, description="Parent bot name if replicated")
    extra: dict[str, Any] | None = Field(default=None, description="Additional custom fields")


class EventPayload(BaseModel):
    """Event data for logging."""

    event_type: str = Field(..., description="Type of event")
    bot_name: str | None = Field(default=None, description="Bot that generated the event")
    timestamp: datetime | None = Field(default=None)
    data: dict[str, Any] | None = Field(default=None, description="Event-specific data")


class BotStatus(BaseModel):
    """Current status of a bot."""

    bot_name: str
    last_seen: datetime
    generation: int | None = None
    fitness_score: float | None = None
    wallet_balance: float | None = None
    cycle_count: int | None = None
    state: str | None = None
    brain_primary: str | None = None
    is_active: bool = True


class ColonyStats(BaseModel):
    """Aggregate colony statistics."""

    total_bots: int
    active_bots: int
    total_revenue: float
    total_api_spend: float
    avg_fitness: float
    total_cycles: int
    generation_range: tuple[int, int] | None = None


class BrainLeaderboardEntry(BaseModel):
    """Entry in the brain leaderboard."""

    brain_model: str
    usage_count: int
    total_revenue: float
    total_cost: float
    avg_fitness: float
    bot_count: int


class TimeSeriesPoint(BaseModel):
    """A single point in a time series."""

    timestamp: datetime
    value: float


class TimeSeriesData(BaseModel):
    """Time series data for charts."""

    metric: str
    points: list[TimeSeriesPoint]


class RecentEvent(BaseModel):
    """A recent event for display."""

    id: int
    event_type: str
    bot_name: str | None
    timestamp: datetime
    data: dict[str, Any] | None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str = "ok"
    database: bool = True
    uptime_seconds: float = 0.0
