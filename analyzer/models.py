"""Pydantic models for Analyzer API."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ==================== Run Models ====================


class RunInfo(BaseModel):
    """Information about a run."""

    run_id: str
    started_at: float | None = None
    ended_at: float | None = None
    status: str = "unknown"
    total_bots: int = 0
    total_cycles: int = 0
    conversation_count: int | None = None
    config: dict[str, Any] | None = None


class RunList(BaseModel):
    """List of runs."""

    runs: list[RunInfo]
    count: int


class RunStats(BaseModel):
    """Statistics for a run."""

    run_id: str
    total_conversations: int = 0
    bots_with_conversations: int = 0
    task_conversations: int = 0
    reflection_conversations: int = 0
    moltbook_queries: int = 0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cost: float = 0
    avg_latency_ms: float = 0


# ==================== Conversation Models ====================


class ConversationSummary(BaseModel):
    """Summary of a conversation."""

    id: str
    run_id: str
    bot_name: str
    bot_generation: int | None = None
    model: str
    timestamp: float
    interaction_type: str
    task_id: str | None = None
    task_type: str | None = None
    success: bool | None = None
    score: float | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0


class ConversationDetail(BaseModel):
    """Full conversation details."""

    id: str
    run_id: str
    bot_name: str
    bot_generation: int | None = None
    model: str
    timestamp: float
    interaction_type: str
    task_id: str | None = None
    task_type: str | None = None
    system_prompt: str | None = None
    user_prompt: str
    assistant_response: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float = 0
    cost_usd: float = 0
    success: bool | None = None
    score: float | None = None
    thread_id: str | None = None
    turn_number: int = 1


class ConversationList(BaseModel):
    """List of conversations."""

    conversations: list[ConversationSummary]
    count: int
    total: int | None = None


class ConversationSearchResult(BaseModel):
    """Search result for conversations."""

    query: str
    results: list[ConversationSummary]
    count: int


# ==================== Bot Models ====================


class BotSummary(BaseModel):
    """Summary of a bot's run."""

    run_id: str
    bot_name: str
    generation: int | None = None
    model: str | None = None
    parent_name: str | None = None
    birth_time: float | None = None
    death_time: float | None = None
    death_cause: str | None = None
    cycles_lived: int | None = None
    initial_balance: float | None = None
    final_balance: float | None = None
    total_revenue: float | None = None
    total_api_spend: float | None = None
    tasks_completed: int | None = None
    tasks_failed: int | None = None
    success_rate: float | None = None
    children_spawned: int | None = None
    children_survived: int | None = None
    total_conversations: int | None = None
    task_conversations: int | None = None
    reflection_conversations: int | None = None


class BotDetail(BaseModel):
    """Detailed bot information with conversations."""

    summary: BotSummary
    conversations: list[ConversationSummary]
    lifecycle_events: list[dict[str, Any]]


class BotList(BaseModel):
    """List of bots."""

    bots: list[BotSummary]
    count: int


# ==================== Timeline Models ====================


class TimelineEntry(BaseModel):
    """Entry for timeline visualization."""

    bot_name: str
    generation: int | None = None
    model: str | None = None
    parent_name: str | None = None
    birth_time: float | None = None
    death_time: float | None = None
    death_cause: str | None = None
    cycles_lived: int | None = None
    success_rate: float | None = None
    children_spawned: int | None = None


class TimelineData(BaseModel):
    """Timeline data for Gantt visualization."""

    run_id: str
    entries: list[TimelineEntry]
    start_time: float | None = None
    end_time: float | None = None


# ==================== Family Tree Models ====================


class FamilyTreeNode(BaseModel):
    """Node in family tree."""

    id: str
    generation: int | None = None
    model: str | None = None
    cycles_lived: int | None = None
    success_rate: float | None = None
    children_spawned: int | None = None
    death_cause: str | None = None


class FamilyTreeEdge(BaseModel):
    """Edge in family tree."""

    source: str
    target: str


class FamilyTreeData(BaseModel):
    """Family tree data for D3.js visualization."""

    run_id: str
    nodes: list[FamilyTreeNode]
    edges: list[FamilyTreeEdge]


# ==================== Metrics Models ====================


class ModelComparison(BaseModel):
    """Comparison metrics for a model."""

    model: str
    bot_count: int = 0
    avg_lifespan: float | None = None
    avg_success: float | None = None
    offspring_survival: float | None = None
    total_revenue: float | None = None
    total_cost: float | None = None


class MetricsData(BaseModel):
    """Metrics dashboard data."""

    run_id: str | None = None
    model_comparison: list[ModelComparison]
    interaction_breakdown: list[dict[str, Any]]
    conversation_stats: dict[str, Any]


# ==================== Reflection Models ====================


class ReflectionEntry(BaseModel):
    """A reflection conversation."""

    bot_name: str
    model: str
    interaction_type: str
    user_prompt: str
    assistant_response: str | None = None
    timestamp: float


class ReflectionList(BaseModel):
    """List of reflections."""

    reflections: list[ReflectionEntry]
    count: int


# ==================== Event Models ====================


class LifecycleEvent(BaseModel):
    """A lifecycle event."""

    id: int | None = None
    run_id: str
    bot_name: str
    event_type: str
    timestamp: float
    data: dict[str, Any] | None = None


class EventList(BaseModel):
    """List of lifecycle events."""

    events: list[LifecycleEvent]
    count: int


# ==================== API Response Models ====================


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: bool
    uptime_seconds: float = 0


class ErrorResponse(BaseModel):
    """Error response."""

    error: str
    detail: str | None = None
