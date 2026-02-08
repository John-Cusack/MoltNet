"""Pydantic models for Task Shop API."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TaskCategory(StrEnum):
    """Task categories."""

    CODING = "coding"
    MATH = "math"
    READING = "reading"


class Benchmark(StrEnum):
    """Supported benchmarks."""

    HUMANEVAL = "humaneval"
    MBPP = "mbpp"
    GSM8K = "gsm8k"
    MATH = "math"
    QASPER = "qasper"
    SCIQ = "sciq"


class AssignmentStatus(StrEnum):
    """Status of a task assignment."""

    ACTIVE = "active"
    SUBMITTED = "submitted"
    COMPLETED = "completed"
    FAILED = "failed"
    ABANDONED = "abandoned"


class CycleAction(StrEnum):
    """Action a bot takes at the end of a cycle."""

    CONTINUE = "continue"
    SUBMIT = "submit"
    QUIT = "quit"


# ==================== Request Models ====================


class BrowseTasksRequest(BaseModel):
    """Parameters for browsing available tasks."""

    category: TaskCategory | None = None
    benchmark: Benchmark | None = None
    difficulty_min: float = Field(default=0.0, ge=0.0, le=1.0)
    difficulty_max: float = Field(default=1.0, ge=0.0, le=1.0)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ClaimTaskRequest(BaseModel):
    """Request to claim a task."""

    bot_name: str = Field(..., description="Name of the claiming bot")
    category: TaskCategory | None = Field(
        default=None, description="Preferred category"
    )
    benchmark: Benchmark | None = Field(
        default=None, description="Preferred benchmark"
    )
    difficulty_min: float = Field(default=0.0, ge=0.0, le=1.0)
    difficulty_max: float = Field(default=1.0, ge=0.0, le=1.0)
    max_cycles: int = Field(default=3, ge=1, le=10)


class CycleUpdateRequest(BaseModel):
    """Submit a cycle update for an assignment."""

    bot_name: str = Field(..., description="Name of the bot")
    action: CycleAction = Field(..., description="Action: continue, submit, or quit")
    response_content: str = Field(
        ..., max_length=50000, description="Bot's response for this cycle"
    )


# ==================== Response Models ====================


class TaskSummary(BaseModel):
    """Summary of a task for browsing."""

    id: str
    benchmark: str
    benchmark_id: str
    category: str
    difficulty: float
    title: str
    times_assigned: int = 0
    times_completed: int = 0


class TaskDetail(BaseModel):
    """Full task detail for working on it."""

    id: str
    benchmark: str
    benchmark_id: str
    category: str
    difficulty: float
    title: str
    prompt: str
    setup_code: str | None = None
    metadata: dict[str, Any] | None = None


class ConversationTurn(BaseModel):
    """A single conversation turn."""

    cycle_number: int
    role: str
    content: str
    timestamp: datetime


class AssignmentResponse(BaseModel):
    """Response when claiming a task or getting active assignment."""

    assignment_id: str
    task: TaskDetail
    status: str
    cycles_spent: int
    max_cycles: int
    assigned_at: datetime
    conversation_history: list[ConversationTurn] = Field(default_factory=list)


class VerificationResponse(BaseModel):
    """Result of task verification."""

    assignment_id: str
    status: str
    score: float
    payout: float
    feedback: str
    cycles_spent: int


class ShopStatsResponse(BaseModel):
    """Overall Task Shop statistics."""

    total_tasks: int
    tasks_by_benchmark: dict[str, int]
    tasks_by_category: dict[str, int]
    total_assignments: int
    active_assignments: int
    completed_assignments: int
    average_score: float
    total_payouts: float


class BotStatsResponse(BaseModel):
    """Statistics for a specific bot."""

    bot_name: str
    total_assignments: int
    completed: int
    failed: int
    abandoned: int
    average_score: float
    total_payout: float
    average_cycles: float


class HealthResponse(BaseModel):
    """Health check response."""

    status: str
    database: bool
    uptime_seconds: float
    total_tasks: int
