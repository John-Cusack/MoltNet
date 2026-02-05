"""Fitness package - Task system with verifiable outcomes for evolutionary selection."""

from clawdbot.fitness.tasks import (
    Task,
    TaskResult,
    TaskTier,
    TaskType,
    MathTask,
    JSONTask,
    LogicTask,
    CodeTask,
)
from clawdbot.fitness.verifiers import (
    Verifier,
    VerificationResult,
    MathVerifier,
    JSONVerifier,
    LogicVerifier,
    CodeVerifier,
    get_verifier,
)
from clawdbot.fitness.task_pool import TaskPool, OpenClawTaskPool
from clawdbot.fitness.rewards import RewardCalculator, RewardConfig, RewardStructure
from clawdbot.fitness.sandbox import Sandbox, SandboxResult

# OpenClaw-specific imports
from clawdbot.fitness.openclaw_tasks import (
    OpenClawTask,
    OpenClawTaskType,
    VerificationType,
    CodeGenerationTask,
    FileOrganizationTask,
    DataExtractionTask,
    ScriptCreationTask,
    MathProblemTask,
    generate_openclaw_task,
)
from clawdbot.fitness.openclaw_verifiers import (
    OpenClawVerifier,
    FileOutcomeVerifier,
    CodeTestVerifier,
    SchemaVerifier,
    LLMJudgeVerifier,
    ExactMatchVerifier,
    get_openclaw_verifier,
    verify_openclaw_task,
)

__all__ = [
    # Tasks
    "Task",
    "TaskResult",
    "TaskTier",
    "TaskType",
    "MathTask",
    "JSONTask",
    "LogicTask",
    "CodeTask",
    # Verifiers
    "Verifier",
    "VerificationResult",
    "MathVerifier",
    "JSONVerifier",
    "LogicVerifier",
    "CodeVerifier",
    "get_verifier",
    # Pool and rewards
    "TaskPool",
    "OpenClawTaskPool",
    "RewardCalculator",
    "RewardConfig",
    "RewardStructure",
    # Sandbox
    "Sandbox",
    "SandboxResult",
    # OpenClaw Tasks
    "OpenClawTask",
    "OpenClawTaskType",
    "VerificationType",
    "CodeGenerationTask",
    "FileOrganizationTask",
    "DataExtractionTask",
    "ScriptCreationTask",
    "MathProblemTask",
    "generate_openclaw_task",
    # OpenClaw Verifiers
    "OpenClawVerifier",
    "FileOutcomeVerifier",
    "CodeTestVerifier",
    "SchemaVerifier",
    "LLMJudgeVerifier",
    "ExactMatchVerifier",
    "get_openclaw_verifier",
    "verify_openclaw_task",
]
